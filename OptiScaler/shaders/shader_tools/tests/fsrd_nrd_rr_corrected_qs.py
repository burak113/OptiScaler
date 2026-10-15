"""Independent V7 oracle for AMD RR1.2 section5.5.2 material guides.

Frozen V2/V5/V6 research used NoV instead of NoV**2 in the SCALE denominator.
Do not alter or call that frozen albedo implementation. Production HLSL is
already correct. This new full-four-power matrix oracle and a separately
expanded scalar oracle intentionally distinguish nonendpoint view angles.
CPU FP32 predictions are not an assertion about hardware FMA/UNORM rounding.
"""
from __future__ import annotations

import numpy as np


DOC = 'https://gpuopen.com/manuals/fsr_sdk/techniques/denoising/#552-ggx'
CORRECTION = 'scale denominator x.xzw=(1,NoV^2,NoV^3), not bias x.xyw'


def full_matrices(dtype=np.float64):
    """Rows are alpha powers; columns are NoV powers0,1,2,3.

    Embedding the published 2x2/3x3 expressions in full4x4 matrices makes
    the distinct bias/scale power selection explicit, rather than sharing
    one abbreviated x vector between both expressions.
    """
    bias_num = np.array([[.99044, -1.28514, 0, 0],
        [1.29678, -.755907, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], dtype=dtype)
    bias_den = np.array([[1, 2.92338, 0, 59.4188],
        [20.3225, -27.0302, 0, 222.592], [0, 0, 0, 0],
        [121.563, 626.13, 0, 316.627]], dtype=dtype)
    scale_num = np.array([[.0365463, 3.32707, 0, 0],
        [9.0632, -9.04756, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], dtype=dtype)
    scale_den = np.array([[1, 0, 3.59685, -1.36772],
        [9.04401, 0, -16.3174, 9.22949], [0, 0, 0, 0],
        [5.56589, 0, 19.7886, -20.2123]], dtype=dtype)
    return bias_num, bias_den, scale_num, scale_den


def polynomials(no_v, alpha, dtype=np.float64):
    d = np.dtype(dtype).type
    n, a = np.broadcast_arrays(np.abs(np.asarray(no_v, dtype=d)), np.asarray(alpha, dtype=d))
    if not (np.isfinite(n).all() and np.isfinite(a).all() and
            np.all((n >= 0) & (n <= 1)) and np.all((a >= 0) & (a <= 1))):
        raise ValueError('finite supported NoV/alpha domain required')
    x = np.stack((np.ones_like(n), n, n*n, n*n*n), -1)
    y = np.stack((np.ones_like(a), a, a*a, a*a*a), -1)
    return tuple(np.sum((x @ matrix.T)*y, axis=-1) for matrix in full_matrices(dtype))


def scalar_polynomials(no_v, alpha):
    """Hand-expanded FP64 scalar evaluator, separate from matrix construction."""
    n, a = abs(float(no_v)), float(alpha)
    return (
        .99044 - 1.28514*n + a*(1.29678 - .755907*n),
        1 + 2.92338*n + 59.4188*n**3 + a*(20.3225 - 27.0302*n + 222.592*n**3)
          + a**3*(121.563 + 626.13*n + 316.627*n**3),
        .0365463 + 3.32707*n + a*(9.0632 - 9.04756*n),
        1 + 3.59685*n**2 - 1.36772*n**3 + a*(9.04401 - 16.3174*n**2 + 9.22949*n**3)
          + a**3*(5.56589 + 19.7886*n**2 - 20.2123*n**3))


def reflectance(f0, roughness, no_v, dtype=np.float64):
    d = np.dtype(dtype).type
    f0 = np.asarray(f0, dtype=d)
    roughness = np.asarray(roughness, dtype=d)
    if f0.shape[-1] != 3 or not np.isfinite(f0).all() or not np.all((f0 >= 0) & (f0 <= 1)):
        raise ValueError('three finite unit-range Fresnel channels required')
    if not np.isfinite(roughness).all() or not np.all((roughness >= 0) & (roughness <= 1)):
        raise ValueError('finite supported perceptual roughness required')
    nb, db, ns, ds = polynomials(no_v, roughness*roughness, dtype)
    if np.any(db <= 0) or np.any(ds <= 0):
        raise AssertionError('published rational denominators remain positive')
    bias = (nb/db)*np.clip(f0[..., 1]*d(50), d(0), d(1))
    return f0*np.maximum(d(0), ns/ds)[..., None] + np.maximum(d(0), bias)[..., None]


def scalar_reflectance(f0, roughness, no_v):
    nb, db, ns, ds = scalar_polynomials(no_v, float(roughness)**2)
    gate = max(0., min(1., float(f0[1])*50))
    return np.array([float(c)*max(0., ns/ds) + max(0., (nb/db)*gate) for c in f0])


def unorm8(value):
    """Chosen immutable CPU upload words: nearest-even direct UNORM8, no half.

    Hardware typed stores permit a small conversion interval and may reorder
    FP32 arithmetic. A separate actual-HLSL comparison must attest that path.
    """
    return np.rint(np.clip(np.asarray(value, np.float64), 0., 1.)*255.).astype('u1')


def corrected_guide(roughness, no_v, f0=(1., 1., 1.)):
    return unorm8(reflectance(f0, roughness, no_v, np.float64))


def float32_to_half_rne(value):
    """Integer IEEE RNE for the nonnegative[0,1] captured material packet.

    This mirrors the explicitly rounded production capture, and avoids
    depending on a legacy typed FP16 store's rounding mode. The final guide
    store itself is direct UNORM8 and does not call this helper.
    """
    value = np.ascontiguousarray(value, dtype='<f4')
    if not np.isfinite(value).all() or not np.all((value >= 0) & (value <= 1)):
        raise ValueError('captured material fields must be finite in[0,1]')
    words = value.view('<u4')
    exponent = ((words >> 23) & 255).astype(np.int32)
    mantissa = words & 0x7fffff
    result = np.zeros(value.shape, dtype='<u2')
    normal = exponent >= 113
    m = mantissa[normal]
    rounded = (m >> 13) + (((m & 8191) > 4096) | (((m & 8191) == 4096) & ((m >> 13) & 1))).astype(np.uint32)
    result[normal] = (((exponent[normal] - 112).astype(np.uint32) << 10) + rounded).astype('<u2')
    subnormal = (exponent >= 102) & (exponent < 113)
    significand = mantissa[subnormal] | 0x800000
    shift = (126 - exponent[subnormal]).astype(np.uint32)
    truncated = significand >> shift
    remainder = significand & ((np.uint32(1) << shift) - 1)
    midpoint = np.uint32(1) << (shift - 1)
    result[subnormal] = (truncated + ((remainder > midpoint) | ((remainder == midpoint) & ((truncated & 1) != 0)))).astype('<u2')
    result |= ((words >> 16) & 0x8000).astype('<u2')
    return result.view('<f2')


def captured_material(rgb10, metal8):
    rgb10, metal8 = np.asarray(rgb10, '<u4'), np.asarray(metal8, 'u1')
    if rgb10.shape[-1] != 3 or np.any(rgb10 > 1023):
        raise ValueError('native-style exact RGB10/R8 codes required')
    encoded = rgb10.astype(np.float32)/np.float32(1023)
    linear = encoded*encoded
    packet = np.concatenate((linear, (metal8.astype(np.float32)/np.float32(255))[..., None]), -1)
    return float32_to_half_rne(packet)


def material_factors(base_metal, roughness, no_v):
    """Use exact decoded half cues consistently for physical F0 and guide Q."""
    packet = np.asarray(base_metal, '<f2').astype(np.float64)
    base, metal = packet[..., :3], packet[..., 3:]
    f0 = .04*(1-metal) + base*metal
    return dict(f0=f0, qd=base*(1-metal), qs=reflectance(f0, roughness, no_v))
