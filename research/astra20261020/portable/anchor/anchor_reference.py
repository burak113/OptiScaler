"""Frozen gain-estimator reference, not an improved algorithm.

Only NumPy and the Python standard library are required. Inputs are already
measured/reprojected cell grids: this does not implement keyframe recall or RR.
"""
import math
import numpy as np


def fixed_measurement_mask(stats, recalled):
    return ((stats[..., 2] > .5) & (recalled[..., 1] > .5) &
            (recalled[..., 3] > .5))


def local_statistics(stats, recalled, step=3):
    stats = np.asarray(stats, dtype=np.float32)
    recalled = np.asarray(recalled, dtype=np.float32)
    h, w = stats.shape[:2]
    weight = recalled[..., 1] * recalled[..., 3]
    numerator = np.zeros((h, w), np.float32)
    denominator = numerator.copy()
    coverage = numerator.copy()
    for dy in (-step, 0, step):
        for dx in (-step, 0, step):
            ix = np.ix_(np.clip(np.arange(h) + dy, 0, h - 1),
                        np.clip(np.arange(w) + dx, 0, w - 1))
            numerator += recalled[..., 0][ix] * weight[ix]
            denominator += stats[..., 0][ix] * weight[ix]
            coverage += weight[ix]
    return numerator, denominator, coverage


def reject_threshold(k):
    model = np.float32(.18 * math.exp(-max(k, 0) / 10))
    return np.float32(max(float(1.8 * model), .30))


def predict(stats, recalled, k, frame_ratio, policy="combined", strength=1.0,
            global_no_excess_gate=False):
    """Reproduce the pinned scalar Gain shaders, rounding output to FP16.

    combined: measured frame-global fallback when recall coverage >= .15.
    native: fallback 1, centre-static and some-local-recall required.
    global_no_excess_gate is an optional diagnostic control, NOT shipped policy.
    frame_ratio is an observation; do not silently replace exact atomics with a
    ratio of stored FP16 cells. Native fixture metadata labels its bounded estimate.
    """
    if policy not in ("combined", "native"):
        raise ValueError("policy must be combined or native")
    stats = np.asarray(stats, dtype=np.float32)
    recalled = np.asarray(recalled, dtype=np.float32)
    if stats.shape != recalled.shape or stats.ndim != 3 or stats.shape[2] != 4:
        raise ValueError("expected matching H x W x 4 cell grids")
    num, den, coverage = local_statistics(stats, recalled)
    weight = recalled[..., 1] * recalled[..., 3]
    frame_coverage = float(weight.mean())
    frame_ratio = min(float(frame_ratio), 4.0)
    model = np.float32(.18 * math.exp(-max(k, 0) / 10))
    threshold = reject_threshold(k)
    fallback = np.float32(1 if policy == "native" or frame_coverage < .15
                          else min(frame_ratio, 1))
    measurable = (coverage >= .5) & (den > 1e-9)
    measured = np.full(coverage.shape, fallback, np.float32)
    np.divide(num, den, out=measured, where=measurable)
    blend = np.clip(coverage / np.float32(2.7), 0, 1)
    gain = blend * measured + (1 - blend) * fallback
    gain = np.maximum(np.clip(gain, .8, 1),
                      np.float32(1 - min(float(model) + .05, .30)))
    gain[measurable & ((1 - measured) > threshold)] = 1
    if frame_coverage >= .15 and 1 - frame_ratio > threshold:
        gain[:] = 1
    if policy == "native":
        gain[(stats[..., 2] < .5) | (coverage < .5)] = 1
    gain = 1 + np.float32(np.clip(strength, 0, 1)) * (gain - 1)
    if global_no_excess_gate and frame_ratio >= 1:
        gain[:] = 1
    return gain.astype(np.float16).astype(np.float32)


def input_energy_gain(stats, gain):
    level = np.asarray(stats[..., 0], dtype=np.float64)
    return float(np.sum(np.asarray(gain, dtype=np.float64) * level) /
                 max(float(level.sum()), 1e-30))


def _qsum(a, scale):
    a = np.asarray(a, dtype=np.float64)
    return int(np.floor(np.clip(a, 0, 16) * scale).astype(np.uint64).sum())


def frame_ratio_from_stored_fields(stats, recalled, scale=65536):
    """Return central FP16-field estimate and rigorous pre-store FP32 bounds.

    Bounds assume round-to-nearest finite nonnegative FP16 outputs. Atomics see
    values before FP16 storage. Return is (estimate, lower, upper, valid_count).
    """
    s = np.asarray(stats, dtype=np.float16)
    r = np.asarray(recalled, dtype=np.float16)
    mask = fixed_measurement_mask(s, r)
    x, y = s[..., 0][mask], r[..., 0][mask]
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("nonfinite lighting is outside this reference fixture")
    def interval(a):
        v = a.astype(np.float64)
        lo = (np.nextafter(a, np.float16(-np.inf)).astype(np.float64) + v) * .5
        hi = (np.nextafter(a, np.float16(np.inf)).astype(np.float64) + v) * .5
        return np.maximum(lo, 0), hi
    xlo, xhi = interval(x)
    ylo, yhi = interval(y)
    den = _qsum(x, scale)
    if den == 0:
        return 1., 0., float("inf"), int(mask.sum())
    central = _qsum(y, scale) / den
    lower = _qsum(ylo, scale) / max(_qsum(xhi, scale), 1)
    upper = _qsum(yhi, scale) / max(_qsum(xlo, scale), 1)
    return central, lower, upper, int(mask.sum())


def antithetic_null(stats, recalled, k, amplitude, rng, pairs=16):
    """Equal-global-energy null from captured residuals, not pure-noise proof.

    Masks remain fixed. Observed residual may contain geometry/lighting/noise.
    Return input-energy gains for exchangeable signs and global-ratio errors.
    """
    stats = np.asarray(stats, dtype=np.float32)
    recalled = np.asarray(recalled, dtype=np.float32)
    mask = fixed_measurement_mask(stats, recalled)
    x = stats[..., 0][mask].astype(np.float64)
    y = recalled[..., 0][mask].astype(np.float64)
    y *= x.sum() / max(float(y.sum()), 1e-30)
    midpoint, residual = (x + y) * .5, (x - y) * .5
    gains, errors = [], []
    for _ in range(pairs):
        signed = residual * rng.choice(np.array([-1., 1.]), size=residual.size) * amplitude
        for sign in (-1, 1):
            a, b = midpoint + sign * signed, midpoint - sign * signed
            b *= a.sum() / max(float(b.sum()), 1e-30)
            ss, rr = stats.copy(), recalled.copy()
            ss[..., 0][mask], rr[..., 0][mask] = a.astype(np.float32), b.astype(np.float32)
            ratio = rr[..., 0][mask].sum(dtype=np.float64) / ss[..., 0][mask].sum(dtype=np.float64)
            errors.append(abs(float(ratio) - 1))
            gains.append(input_energy_gain(ss, predict(ss, rr, k, 1., policy="native")))
    return np.asarray(gains), np.asarray(errors)


def uniform_light_probe(candidate=predict, policy="native", steps=(.5, 1.1, 1.25, 1.4, 2.)):
    """Known real-light changes during armed k0. Baseline intentionally fails.

    Current/prior ratios alone cannot identify a light step versus a biased
    observation with the exact same values. Response1 would preserve the step.
    """
    result = []
    for step in steps:
        stats = np.zeros((8, 8, 4), np.float32)
        recalled = stats.copy()
        stats[..., 0], stats[..., 1], stats[..., 2] = step, 1, 1
        recalled[..., 0], recalled[..., 1], recalled[..., 3] = 1, 1, 1
        gain = candidate(stats, recalled, 0, 1 / step, policy=policy)
        output = step * float(gain.mean())
        result.append({"step":step, "gain":float(gain.mean()), "output":output,
                       "response":(output - 1) / (step - 1)})
    return result
