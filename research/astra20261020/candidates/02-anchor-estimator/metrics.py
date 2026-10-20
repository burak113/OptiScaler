"""Fixed-denominator CPU diagnostics; no RR or final-image quality claims."""
from pathlib import Path
import importlib.util
import numpy as np


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
_spec = importlib.util.spec_from_file_location(
    "untouched_anchor_v1", PACKAGE / "portable/anchor/anchor_reference.py")
BASELINE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BASELINE)


def native_half_ratio(stats, recalled):
    """Exact modeled 16.16 sums when the synthetic pre-store source IS the half.

    This is only for generated controls. Recorded native pre-store sums are
    absent; callers must use the stored ratio plus its bounds for those data.
    """
    mask = BASELINE.fixed_measurement_mask(stats, recalled)
    x, y = stats[..., 0][mask], recalled[..., 0][mask]
    den = np.floor(np.clip(x.astype(np.float64), 0., 16.) * 65536).astype(np.uint64).sum()
    num = np.floor(np.clip(y.astype(np.float64), 0., 16.) * 65536).astype(np.uint64).sum()
    return min(float(num) / float(den), 4.) if den else 1.


def baseline_gain(stats, recalled, k, *, strength=1., active=True, reset=False,
                  ratio=None, policy="native"):
    if not active or reset:
        return np.ones(stats.shape[:2], np.float32)
    return BASELINE.predict(stats, recalled, k,
                            native_half_ratio(stats, recalled) if ratio is None else ratio,
                            policy=policy, strength=strength)


def erode_cross(mask):
    """Only original BASE neighbors enter spatial-error denominators."""
    m = np.asarray(mask, bool)
    result = m.copy()
    result[..., 0, :] = False; result[..., -1, :] = False
    result[..., :, 0] = False; result[..., :, -1] = False
    result[..., 1:-1, 1:-1] &= (m[..., :-2, 1:-1] & m[..., 2:, 1:-1] &
                                m[..., 1:-1, :-2] & m[..., 1:-1, 2:])
    return result


def highpass(a):
    out = np.zeros_like(a, dtype=np.float64)
    out[..., 1:-1, 1:-1] = (a[..., 1:-1, 1:-1] - .25 *
        (a[..., :-2, 1:-1] + a[..., 2:, 1:-1] + a[..., 1:-1, :-2] + a[..., 1:-1, 2:]))
    return out


def safe_mean(values):
    a = np.asarray(values, np.float64)
    return float(a.mean()) if a.size else None


def sequence_metrics(level, gain, mask, frames, ages, *, truth=None,
                     valid=None, static=None, abstain=None):
    """Evaluate identical BASE support, with explicit unsupported/gap scope.

    With synthetic truth, grain and flicker measure output-error components.
    Without truth these are field proxies, never an image-quality verdict.
    One-sided gain is applied in float64 to stored cell levels: this stage does
    not model full-resolution Apply rounding or downstream RR.
    """
    x, g = np.asarray(level, np.float64), np.asarray(gain, np.float64)
    m = np.asarray(mask, bool)
    assert x.shape == g.shape == m.shape
    assert np.all(np.isfinite(x)) and np.all(np.isfinite(g))
    assert np.all((g >= 0.) & (g <= 1.))
    frames, ages = np.asarray(frames), np.asarray(ages)
    assert np.all(np.diff(frames) > 0)
    y = x * g
    count = m.sum(axis=(1, 2))
    energy = np.sum(np.where(m, x, 0.), axis=(1, 2))
    removal = np.sum(np.where(m, x - y, 0.), axis=(1, 2))
    denominator = float(energy.sum())
    total_pixels = int(count.sum())
    err = y - np.asarray(truth, np.float64) if truth is not None else y
    local_values = err[m]
    fixed_mean = denominator / total_pixels if total_pixels else 0.
    if truth is not None and total_pixels:
        fixed_mean = float(np.asarray(truth, np.float64)[m].mean())
    scale = max(abs(fixed_mean), 1e-30)
    spatial_mask = erode_cross(m)
    grain = highpass(err)[spatial_mask]
    adjacent = np.diff(frames) == 1
    temporal_mask = m[1:] & m[:-1] & adjacent[:, None, None]
    deltas = np.diff(err, axis=0)[temporal_mask]
    gain_deltas = np.diff(g, axis=0)[temporal_mask]
    base_values = x[m]
    # A BASE-derived threshold stays fixed for every variant of this sequence.
    sparkle_threshold = float(np.quantile(base_values, .995)) if base_values.size else None
    early = (ages >= 0) & (ages <= 5)
    late = (ages >= 6) & (ages <= 25)
    changed = g < 1.
    unsupported = ~np.asarray(valid, bool) if valid is not None else np.zeros_like(m)
    dynamic = ~np.asarray(static, bool) if static is not None else np.zeros_like(m)
    per_frame = []
    for t in range(len(frames)):
        per_frame.append({
            "frame": int(frames[t]), "k": int(ages[t]), "base_mask_cells": int(count[t]),
            "input_energy": float(energy[t]), "removed_energy": float(removal[t]),
            "energy_drift_fraction": -float(removal[t] / energy[t]) if energy[t] > 0 else None,
            "changed_fraction_on_base_mask": float(np.sum(changed[t] & m[t]) / count[t]) if count[t] else None,
            "abstain_fraction_on_base_mask": float(np.sum(abstain[t] & m[t]) / count[t])
                if abstain is not None and count[t] else None,
        })
    return {
        "scope": "synthetic known-truth cell model" if truth is not None else "captured stored-cell input/gain proxies, no truth",
        "frames": len(frames), "base_mask_samples": total_pixels,
        "input_energy": denominator, "correction_energy": float(removal.sum()),
        "correction_dose": float(removal.sum() / denominator) if denominator else None,
        "global_energy_drift": -float(removal.sum() / denominator) if denominator else None,
        "early_correction_energy_k0_5": float(removal[early].sum()),
        "late_correction_energy_k6_25": float(removal[late].sum()),
        "changed_fraction_on_base_mask": float(np.sum(changed & m) / total_pixels) if total_pixels else None,
        "changed_cells_outside_base_mask": int(np.sum(changed & ~m)),
        "unsupported_changed_cells": int(np.sum(changed & unsupported)),
        "dynamic_changed_cells_at_grid": int(np.sum(changed & dynamic)),
        "local_error_bias": safe_mean(local_values) if truth is not None else None,
        "local_error_variance": float(np.var(local_values)) if truth is not None and local_values.size else None,
        "local_error_rmse": float(np.sqrt(np.mean(local_values**2))) if truth is not None and local_values.size else None,
        "spatial_grain_proxy_rms_over_base_level": float(np.sqrt(np.mean(grain**2)) / scale) if grain.size else None,
        "spatial_grain_denominator": int(grain.size),
        "temporal_flicker_proxy_rms_over_base_level": float(np.sqrt(np.mean(deltas**2)) / scale) if deltas.size else None,
        "gain_delta_rms": float(np.sqrt(np.mean(gain_deltas**2))) if gain_deltas.size else None,
        "temporal_denominator": int(deltas.size),
        "adjacent_original_frame_pairs": int(adjacent.sum()),
        "gaps_not_interpolated": int((~adjacent).sum()),
        "sparkle_threshold_from_base_q995": sparkle_threshold,
        "sparkle_fraction_over_fixed_base_threshold": float(np.sum((y > sparkle_threshold) & m) / total_pixels)
            if sparkle_threshold is not None and total_pixels else None,
        "abstain_fraction_on_base_mask": float(np.sum(np.asarray(abstain) & m) / total_pixels)
            if abstain is not None and total_pixels else None,
        "trajectory": per_frame,
    }


def response_metrics(truth, output, base_truth, mask, onset=6, window=22):
    m = np.asarray(mask[onset:onset + window], bool)
    delta = np.asarray(truth[onset:onset + window], np.float64) - base_truth
    observed = np.asarray(output[onset:onset + window], np.float64) - base_truth
    den = np.sum(np.where(m, delta, 0.), axis=(1, 2))
    num = np.sum(np.where(m, observed, 0.), axis=(1, 2))
    valid = np.abs(den) > 1e-30
    ratios = np.divide(num, den, out=np.zeros_like(num), where=valid)
    # Latency is the first point with all remaining observed responses >=90%.
    sustained = [i for i in range(len(ratios)) if np.all(valid[i:] & (ratios[i:] >= .9))]
    sustained95 = [i for i in range(len(ratios)) if np.all(valid[i:] & (ratios[i:] >= .95))]
    return {"window_frames": len(den),
            "response_area_ratio": float(num.sum() / den.sum()) if abs(den.sum()) > 1e-30 else None,
            "sustained_90pct_latency_frames": sustained[0] if sustained else None,
            "latency_censored_at_frames": None if sustained else len(den),
            "sustained_95pct_latency_frames": sustained95[0] if sustained95 else None,
            "latency_95pct_censored_at_frames": None if sustained95 else len(den),
            "per_frame_response_fraction": [float(v) if ok else None for v, ok in zip(ratios, valid)]}
