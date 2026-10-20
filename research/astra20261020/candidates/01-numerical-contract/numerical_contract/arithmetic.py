"""Named arithmetic staging; no assumption that DXC disables contraction.

The shaders declare float, uint and resource stores. ``-enable-16bit-types``
does not make their ordinary float expressions half precision. Separate/fused
operations here are explicit competing arithmetic models, not an inferred ISA.
"""
import numpy as np

from .storage import sanitize_radiance, store_fp16


def f32(values):
    return np.asarray(values, dtype=np.float32)


def f32_add(a, b):
    return np.add(f32(a), f32(b), dtype=np.float32)


def f32_sub(a, b):
    return np.subtract(f32(a), f32(b), dtype=np.float32)


def f32_mul(a, b):
    return np.multiply(f32(a), f32(b), dtype=np.float32)


def f32_div(a, b):
    return np.divide(f32(a), f32(b), dtype=np.float32)


def mad_separate(a, b, c):
    """Two rounding stages: binary32 multiply followed by binary32 add."""
    return f32_add(f32_mul(a, b), c)


def _finite_binary32_parts(bits):
    sign = -1 if bits & 0x80000000 else 1
    exponent = (bits >> 23) & 255
    fraction = bits & 0x7fffff
    if exponent == 255:
        raise ValueError("exact fused reference supports finite operands only")
    if exponent == 0:
        return sign * fraction, -149
    return sign * ((1 << 23) | fraction), exponent - 150


def _nearest_even_integer_shift(n, right):
    if right <= 0:
        return n << -right
    quotient, remainder = divmod(n, 1 << right)
    halfway = 1 << (right - 1)
    return quotient + int(remainder > halfway or (remainder == halfway and quotient & 1))


def _round_exact_binary32(n, exponent, negative_zero=False):
    """Round the exact dyadic integer n*2**exponent to IEEE binary32 RNE."""
    sign = 0x80000000 if n < 0 or (n == 0 and negative_zero) else 0
    n = abs(n)
    if not n:
        return sign
    top = n.bit_length() - 1 + exponent
    if top < -126:
        significand = _nearest_even_integer_shift(n, -(exponent + 149))
        # Rounding into the smallest normal has exactly the desired bit pattern.
        return sign | significand
    significand = _nearest_even_integer_shift(n, n.bit_length() - 24)
    if significand == (1 << 24):
        significand >>= 1
        top += 1
    if top > 127:
        return sign | 0x7f800000
    return sign | ((top + 127) << 23) | (significand & 0x7fffff)


def mad_fused(a, b, c):
    """One final binary32 RNE of exact float32(a)*float32(b)+float32(c).

    Integer significands avoid treating a float64 multiply/add as a universally
    exact fused oracle. Finite operands only; result overflow is signed infinity.
    Subnormal results are preserved. This is a reference, not a fast array kernel.
    """
    aa, bb, cc = np.broadcast_arrays(f32(a), f32(b), f32(c))
    out = np.empty(aa.shape, np.uint32)
    for i, (ab, bb_, cb) in enumerate(zip(aa.view(np.uint32).flat,
                                         bb.view(np.uint32).flat,
                                         cc.view(np.uint32).flat)):
        ab, bb_, cb = int(ab), int(bb_), int(cb)
        ai, ae = _finite_binary32_parts(ab)
        bi, be = _finite_binary32_parts(bb_)
        ci, ce = _finite_binary32_parts(cb)
        pe = ae + be
        exponent = min(pe, ce)
        n = ((ai * bi) << (pe - exponent)) + (ci << (ce - exponent))
        # RNE exact cancellation is +0, except the sum of two negative zeros.
        product_negative = bool((ab ^ bb_) & 0x80000000)
        both_negative_zero = (ai * bi == 0 and ci == 0 and product_negative
                              and bool(cb & 0x80000000))
        out.flat[i] = _round_exact_binary32(n, exponent, both_negative_zero)
    return out.view(np.float32)


def dot_f32(a, b):
    """Left-to-right, separately rounded float32 dot over the last dimension."""
    products = f32_mul(a, b)
    if products.ndim == 0:
        raise ValueError("dot requires a final component dimension")
    result = np.zeros(products.shape[:-1], np.float32)
    for lane in range(products.shape[-1]):
        result = f32_add(result, products[..., lane])
    return result


def to_uint32(values):
    """Truncation on the validated HLSL subset 0<=float32(x)<2**32.

    Invalid/out-of-range/nonfinite inputs raise. This is deliberately stricter
    than inventing a portable answer for unestablished conversion behavior.
    """
    a = f32(values)
    if not np.isfinite(a).all() or np.any(a < 0) or np.any(a >= np.float64(2**32)):
        raise ValueError("uint conversion requires finite float32 in [0,2**32)")
    return np.trunc(a).astype(np.uint32)


def to_int32(values):
    """Truncation on finite float32 inputs in [-2**31,2**31)."""
    a = f32(values)
    if not np.isfinite(a).all() or np.any(a < -(2**31)) or np.any(a >= np.float64(2**31)):
        raise ValueError("int conversion requires finite float32 in [-2**31,2**31)")
    return np.trunc(a).astype(np.int32)


def apply_anchor_lobes(diffuse, specular, gain, *, enabled=True, rounding="rne"):
    """Source-shaped pointwise native Apply after gain sampling.

    Gain sampling is a separate contract. Native inputs must be float32-expanded
    R16G16B16A16 payloads; this function leaves their alpha payload unchanged.
    OFF returns copies before reading any unused gain/rounding value. Enabled
    RGB follows source saturation, multiply, sanitize and typed-store boundaries.
    """
    d, s = f32(diffuse), f32(specular)
    if d.shape != s.shape or d.ndim < 1 or d.shape[-1] != 4:
        raise ValueError("expected equal ...x4 diffuse/specular textures")
    if not enabled:
        return d.copy(), s.copy()
    for signal in (d, s):
        if not np.isfinite(signal[..., 3]).all():
            raise ValueError("nonfinite alpha payload bits require an explicit device capture")
        finite = np.isfinite(signal)
        restored = store_fp16(signal, rounding=rounding)
        if not np.array_equal(restored.view(np.uint32)[finite], signal.view(np.uint32)[finite]):
            raise ValueError("native inputs must already contain expanded FP16 payloads")
    g = f32(gain)
    if not np.isfinite(g).all():
        raise ValueError("nonfinite sampled gain has unestablished device behavior")
    g = np.broadcast_to(np.clip(g, 0, 1), d.shape[:-1])
    result = []
    for signal in (d, s):
        out = signal.copy()
        out[..., :3] = store_fp16(sanitize_radiance(f32_mul(signal[..., :3], g[..., None])),
                                 rounding=rounding)
        result.append(out)
    return tuple(result)
