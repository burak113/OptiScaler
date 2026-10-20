"""Small source-shaped arithmetic probes, not a native NZR/AMD implementation.

Seed follows FSRDFlatDetailSeed.hlsl for a supplied flat 5x5 support. It omits
native tile routing, guide encoding, geometry weight construction and Refine.
FP16 LDS colour storage is modelled; Python float64 fitting is an arithmetic
diagnostic, not a float32 compiler/sampler parity claim.
"""
from __future__ import annotations

import numpy as np


def _fit(values: np.ndarray, weights: np.ndarray):
    yy, xx = np.mgrid[-2:3, -2:3]
    design = np.stack((np.ones(25), xx.ravel(), yy.ravel()), axis=-1)
    w = weights.reshape(-1).astype(np.float64)
    c = values.reshape(25, 3).astype(np.float64)
    total = float(w.sum())
    inv = 1.0 / max(total, 1e-6)
    pos = (design[:, 1:] * w[:, None]).sum(0) * inv
    mean = (c * w[:, None]).sum(0) * inv
    p = design[:, 1:]
    vv = (p[:, :, None] * p[:, None, :] * w[:, None, None]).sum(0) * inv - np.outer(pos, pos)
    cov = (p[:, :, None] * c[:, None, :] * w[:, None, None]).sum(0) * inv - pos[:, None] * mean
    det = vv[0, 0] * vv[1, 1] - vv[0, 1] ** 2
    if det > 1e-5:
        dx = (cov[0] * vv[1, 1] - cov[1] * vv[0, 1]) / det
        dy = (cov[1] * vv[0, 0] - cov[0] * vv[0, 1]) / det
    else:
        dx = dy = np.zeros(3)
    centre = mean - dx * pos[0] - dy * pos[1]
    variance = max(float(((c*c*w[:, None]).sum(0)*inv - mean*mean - dx*cov[0] - dy*cov[1]).mean()), 0.0)
    return centre, dx, dy, variance, total


def seed_flat_patch(rgb: np.ndarray, support: np.ndarray | None = None, epsilon: float = 1e-6):
    """Flat-surface 5x5 Seed subset with caller-supplied geometry weights.

    The positive centre sample and weights are not inferred from semantic class.
    This function deliberately leaves the shader's centre-conditioned robust
    mechanism intact so that a sparse-noise failure is reproducible.
    """
    rgb = np.asarray(rgb)
    if rgb.shape != (5, 5, 3) or not np.isfinite(rgb).all() or (rgb < 0).any() or (rgb > 65504).any():
        raise ValueError("Expected one finite nonnegative half-representable 5x5 RGB patch")
    values = rgb.astype(np.float16).astype(np.float64)
    weights = np.ones((5, 5)) if support is None else np.asarray(support, dtype=np.float64)
    if weights.shape != (5, 5) or not np.isfinite(weights).all() or (weights < 0).any() or (weights > 1).any():
        raise ValueError("Support must contain 25 weights in [0,1]")
    # The shader gates directional support before quantizing fitting weights.
    directional_weights = weights.copy()
    weights = np.rint(weights * 255.0) / 255.0
    weights[2, 2] = 1.0
    centre_raw = values[2, 2]
    small = max(float(centre_raw @ centre_raw) * (0.0025**2 / 3.0), epsilon**2)
    directional = float("inf")
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        if directional_weights[2-dy, 2-dx] > 0.1 and directional_weights[2+dy, 2+dx] > 0.1:
            error = centre_raw - 0.5*(values[2-dy, 2-dx] + values[2+dy, 2+dx])
            directional = min(directional, float(error @ error)*(2.0/9.0))
    if not np.isfinite(directional):
        directional = small
    radius = 16.0 * max(directional, small)
    delta = values - centre_raw
    yy, xx = np.mgrid[-2:3, -2:3]
    appearance = 1.0 / (1.0 + np.sum(delta*delta, axis=-1)/(3.0*radius))
    first = weights * appearance * ((np.abs(xx)+np.abs(yy)) <= 2)
    estimate, dx, dy, variance, _ = _fit(delta, first)
    sigma2 = max(min(variance, 4.0*max(directional, small)), small)
    residual = delta - estimate - xx[..., None]*dx - yy[..., None]*dy
    u = np.sum(residual*residual, axis=-1)/(3.0*4.0*sigma2)
    robust = np.maximum(1.0-u, 0.0)
    second = weights*robust*robust
    refined, _, _, _, total = _fit(delta, second)
    if total < 1.5:
        refined = np.zeros(3)
    out = np.maximum(centre_raw+refined, 0.0)
    effective_support = total*total/max(float(np.sum(second*second)), 1e-30)
    return out.astype(np.float32), {"robust_weight_sum": total, "weight_effective_support": effective_support,
                                    "directional_variance": directional, "fallback_to_centre": total < 1.5}


def hybrid_select(detail, raw_rr, selector, gain):
    """HybridApply's pre-Glass formula; no clamp/store/native scheduling."""
    return np.asarray(detail) + np.clip(selector, 0.0, 1.0) * (np.asarray(gain)*np.asarray(raw_rr)-np.asarray(detail))


def capped_history_variance(rho: float, max_count: int = 16):
    """Exact stationary AR(1) covariance of History's capped-count recurrence.

    At the cap, History uses EMA alpha=1/max_count for mean and second moment.
    Assume unit-variance stationary scalar input, exact support, no warping, no
    finite storage. This is an analytic counterexample, not an input-noise model
    asserted for the captured game.
    """
    if not -1.0 < rho < 1.0 or max_count < 2:
        raise ValueError("Invalid stationary correlation or count")
    alpha = 1.0 / max_count
    beta = 1.0-alpha
    actual = alpha/(2.0-alpha) * (1.0+beta*rho)/(1.0-beta*rho)
    source_estimate = (1.0-actual)/max_count
    return {"rho": rho, "max_count": max_count, "actual_mean_variance": actual,
            "expected_hybridprep_variance": source_estimate,
            "actual_over_source_estimate": actual/source_estimate,
            "effective_count_from_actual_variance": 1.0/actual}
