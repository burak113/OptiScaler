# NEW research-only fork of frozen V5 sampler SHA bbe8c9fe301b804d5ac5d6801e938605120fd1c88ad1463ffe1909381fbdc97b.
# Only the validation domain expands from r>=.1 to r>0; equations/license stay intact.
"""Separate low-positive-roughness GGX math fork for the r80 sensitivity control.

Bounded VNDF direction construction is ported from AMD's MIT-licensed
importance_sampling.hlsl, citing Eto/Tokuyoshi2023. Its PDF uses the matching
paper GGX NDF (alpha squared), independently checked against NDF sampling.
The local demo's D_GGX/PDF and .5/pdf weighting are retained as diagnostics,
not silently treated as a physical BRDF estimator. No provider is called.

Ported direction construction copyright(C)2026 Advanced Micro Devices, Inc.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files(the Software), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions: The above copyright notice and this
permission notice shall be included in all copies or substantial portions of
the Software. THE SOFTWARE IS PROVIDED AS IS, WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES
OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""
from __future__ import annotations

import numpy as np

from fsrd_nrd_rr_mirror_oracle import NORMAL, TANGENT, BITANGENT


BASIS = np.stack((TANGENT, BITANGENT, NORMAL))


def normalize(value):
    return value / np.linalg.norm(value, axis=-1, keepdims=True)


def ggx_ndf(no_h, alpha):
    alpha_squared = alpha * alpha
    denominator = 1. - no_h * no_h + alpha_squared * no_h * no_h
    return np.where(no_h > 0., alpha_squared / (np.pi * denominator * denominator), 0.)


def smith_visibility(no_l, no_v, alpha):
    alpha_squared = alpha * alpha
    first = no_l * np.sqrt(no_v * no_v * (1. - alpha_squared) + alpha_squared)
    second = no_v * np.sqrt(no_l * no_l * (1. - alpha_squared) + alpha_squared)
    denominator = first + second
    return np.where((no_l > 0.) & (no_v > 0.), .5 / np.maximum(denominator, 1e-300), 0.)


def sdk_demo_ndf(no_h, alpha):
    """Exact local helper algebra, including epsilon; this is not our PDF."""
    denominator = (1. - no_h * no_h) / (alpha + 1e-5) + no_h * no_h
    return np.where(no_h >= 0., 1. / (np.pi * alpha * denominator * denominator), 0.)


def bounded_vndf(v_world, roughness, xi):
    """Strictly positive roughness; xi independently uniform in[0,1)^2.

    Broadcasting is explicit: v_world may be[pixels,1,3], xi[pixels,samples,2].
    No rough0/mirror shortcut exists in this fixture.
    """
    if not 0. < roughness <= 1.:
        raise ValueError('GGX control always uses genuinely positive non-mirror roughness')
    alpha = roughness * roughness
    v = np.asarray(v_world, np.float64) @ BASIS.T
    stretched = normalize(v * [alpha, alpha, 1.])
    length_xy = np.linalg.norm(v[..., :2], axis=-1)
    s_squared = (1. + length_xy) ** 2
    k = (1. - alpha * alpha) * s_squared / (s_squared + alpha * alpha * v[..., 2] ** 2)
    b = np.where(v[..., 2] > 0., k * stretched[..., 2], stretched[..., 2])
    phi = 2. * np.pi * xi[..., 0]
    z = (1. - xi[..., 1]) * (1. + b) - b
    radius = np.sqrt(np.clip(1. - z * z, 0., 1.))
    cap = np.stack((radius * np.cos(phi), radius * np.sin(phi), z), axis=-1)
    half = normalize((stretched + cap) * [alpha, alpha, 1.])
    vo_h = np.sum(v * half, axis=-1)
    outgoing = 2. * vo_h[..., None] * half - v
    no_l, no_v, no_h = outgoing[..., 2], v[..., 2], half[..., 2]
    t = np.sqrt(alpha * alpha * np.sum(v[..., :2] ** 2, axis=-1) + no_v * no_v)
    ndf = ggx_ndf(no_h, alpha)
    pdf = ndf / (2. * (k * no_v + t))
    visibility = smith_visibility(no_l, no_v, alpha)
    weight = np.where((no_l > 0.) & (vo_h > 0.), ndf * visibility * np.maximum(no_l, 0.) / pdf, 0.)
    return dict(direction=normalize(outgoing @ BASIS), pdf=pdf, weight=weight,
                no_l=no_l, no_v=np.broadcast_to(no_v, no_l.shape), no_h=no_h, vo_h=vo_h,
                sdk_demo_pdf=sdk_demo_ndf(no_h, alpha) / (2. * (k * no_v + t)))


def ndf_reference(v_world, roughness, xi):
    """Independent half-vector NDF inverse-CDF reference, never bounded VNDF.

    Physical estimator is(F=1) D*SmithVisibility*NoL/pdf. Invalid reflection
    directions contribute exactly zero; their probability is not renormalized.
    """
    if not 0. < roughness <= 1.:
        raise ValueError('nonzero GGX reference only')
    alpha = roughness * roughness
    v = np.asarray(v_world, np.float64) @ BASIS.T
    phi = 2. * np.pi * xi[..., 0]
    cos_theta = np.sqrt((1. - xi[..., 1]) / (1. + (alpha * alpha - 1.) * xi[..., 1]))
    sin_theta = np.sqrt(np.maximum(1. - cos_theta * cos_theta, 0.))
    half = np.stack((sin_theta * np.cos(phi), sin_theta * np.sin(phi), cos_theta), axis=-1)
    vo_h = np.sum(v * half, axis=-1)
    outgoing = 2. * vo_h[..., None] * half - v
    no_l, no_v = outgoing[..., 2], v[..., 2]
    ndf = ggx_ndf(cos_theta, alpha)
    pdf = ndf * cos_theta / (4. * np.maximum(vo_h, 1e-300))
    visibility = smith_visibility(no_l, no_v, alpha)
    weight = np.where((no_l > 0.) & (vo_h > 0.),
        4. * np.maximum(vo_h, 0.) * visibility * np.maximum(no_l, 0.) / cos_theta, 0.)
    return dict(direction=normalize(outgoing @ BASIS), pdf=pdf, weight=weight,
                no_l=no_l, no_v=np.broadcast_to(no_v, no_l.shape), no_h=cos_theta, vo_h=vo_h)


def normal_incidence_quadrature(roughness, order=1024):
    """Independent solid-angle hemisphere quadrature, constant environmentF1."""
    nodes, weights = np.polynomial.legendre.leggauss(order)
    no_l = (nodes + 1.) * .5
    no_h = np.sqrt((1. + no_l) * .5)
    alpha = roughness * roughness
    integrand = ggx_ndf(no_h, alpha) * smith_visibility(no_l, 1., alpha) * no_l
    return float(np.pi * np.sum(weights * integrand))


def radical_inverse(index, base):
    values = np.asarray(index, np.uint64).copy()
    result = np.zeros(values.shape, np.float64)
    scale = 1.
    while np.any(values):
        scale /= base
        result += (values % base).astype(np.float64) * scale
        values //= base
    return result


def reference_points(count):
    if count < 16 or count > 65536:
        raise ValueError('bounded deterministic many-sample reference count')
    indices = np.arange(1, count + 1, dtype=np.uint64)
    return np.stack((radical_inverse(indices, 2), radical_inverse(indices, 3)), axis=-1)
