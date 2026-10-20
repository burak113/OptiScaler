"""Isolate estimator changes from colour-coordinate changes; NumPy CPU only.

Run from the repository root:
  python research/astra20261020/candidates/03-native-colour/mechanism/experiment.py
Generated synthetic truth is not captured/GPU/game evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float64)
EPS = 2.0 ** -12
SEEDS = (17, 41, 73)
SUPPORTS = (64, 256, 4096)
REPETITIONS = 192


def luminance(rgb: np.ndarray) -> np.ndarray:
    return np.asarray(rgb) @ LUMA


def colour(rgb: np.ndarray) -> np.ndarray:
    """Scale-relative regularization; reject invalid/zero aggregate inputs."""
    rgb = np.asarray(rgb)
    if not np.all(np.isfinite(rgb)) or np.any(rgb < 0):
        raise ValueError("nonnegative finite physical RGB required")
    y = luminance(rgb)
    if np.any(y <= 0):
        raise ValueError("zero-radiance aggregate has no chroma observation")
    return (rgb / y[..., None] + EPS) / (1.0 + EPS)


def restore(raw: np.ndarray, gains: np.ndarray) -> np.ndarray:
    v = raw * gains
    return v * (luminance(raw) / luminance(v))[..., None]


def ratio_apply(raw: np.ndarray, target: np.ndarray) -> np.ndarray:
    gain = np.clip(colour(target) / colour(raw), 0.75, 1.33)
    return restore(raw, gain)


def log_apply(raw: np.ndarray, target: np.ndarray) -> np.ndarray:
    delta = np.log(colour(target)) - np.log(colour(raw))
    gain = np.exp(np.clip(delta, np.log(0.75), np.log(1.33)))
    return restore(raw, gain)


def robust_per_sample_log(samples: np.ndarray) -> np.ndarray:
    """Known-biased control: median sample colour loses radiance weighting.

    Samples contain exact repeats of a discrete colour population. Keeping the
    ordinary nonzero class as a median is not an implementation accident: it is
    the robust population target being tested. All-zero samples have no chroma.
    """
    y = luminance(samples)
    valid = y > 0
    safe = np.where(valid[..., None], samples, 1.0)
    encoded = np.log(colour(safe))
    encoded = np.where(valid[..., None], encoded, np.nan)
    if np.any(valid.sum(axis=1) == 0):
        raise ValueError("synthetic batch has no observed chroma")
    median = np.nanmedian(encoded, axis=1)
    decoded = np.exp(median)
    decoded /= luminance(decoded)[..., None]
    decoded = np.maximum(decoded * (1.0 + EPS) - EPS, 0.0)
    return decoded / luminance(decoded)[..., None]


def make_distribution(name: str, scale: float):
    base = np.array([0.20, 0.55, 0.12])
    if name == "valid_coloured_radiance_tail":
        probabilities = np.array([0.60, 0.38, 0.02])
        classes = np.array([np.zeros(3), base, [12.0, 0.35, 0.60]])
        truth = probabilities @ classes
    elif name == "biased_colour_contamination":
        probabilities = np.array([0.55, 0.44, 0.01])
        ordinary = base / 0.45
        classes = np.array([np.zeros(3), ordinary, ordinary + [30.0, 0.0, 12.0]])
        truth = base
    else:
        raise ValueError(name)
    return probabilities, classes * scale, truth * scale


def error_metrics(estimates: np.ndarray, truth: np.ndarray) -> dict:
    residual = colour(estimates) - colour(truth)
    # Denominator is the fixed true luminance, equivalently normalized chroma.
    per = np.sqrt(np.mean(residual * residual, axis=-1))
    adjacent = np.diff(colour(estimates), axis=0)
    return {
        "chroma_rmse_mean": float(np.mean(per)),
        "chroma_rmse_p90": float(np.quantile(per, 0.90)),
        "chroma_rmse_max": float(np.max(per)),
        "population_of_estimates_chroma_bias": float(
            np.sqrt(np.mean(np.mean(residual, axis=0) ** 2))),
        "adjacent_independent_window_chroma_rms": float(
            np.sqrt(np.mean(adjacent * adjacent))),
        "window_count": int(len(estimates)),
    }


def population_results() -> list[dict]:
    rows = []
    for scenario in ("valid_coloured_radiance_tail", "biased_colour_contamination"):
        probabilities, classes, truth = make_distribution(scenario, 1.0)
        arithmetic = probabilities @ classes
        # Ordinary chroma is >50% of the nonzero sample population.
        robust = classes[1] / luminance(classes[1])
        robust_error = float(np.sqrt(np.mean((colour(robust) - colour(truth)) ** 2)))
        mean_error = float(np.sqrt(np.mean((colour(arithmetic) - colour(truth)) ** 2)))
        rows.append({
            "scenario": scenario,
            "probabilities": probabilities.tolist(),
            "classes_rgb": classes.tolist(),
            "truth_rgb": truth.tolist(),
            "observation_expectation_rgb": arithmetic.tolist(),
            "mean_target_chroma_error": mean_error,
            "robust_log_target_chroma_error": robust_error,
            "zero_probability": float(probabilities[0]),
            "rare_class_energy_share": float(probabilities[2] * luminance(classes[2]) /
                                             luminance(arithmetic)),
            "rare_class_role": ("legitimate radiance expectation" if scenario.startswith("valid")
                                else "explicitly biased contamination added by the generator"),
        })
    assert rows[0]["robust_log_target_chroma_error"] > 0.015
    assert rows[0]["mean_target_chroma_error"] < 1e-12
    return rows


def monte_carlo() -> list[dict]:
    rows = []
    for seed in SEEDS:
        for lobe, scale in (("diffuse", 0.2), ("specular", 0.015)):
            for scenario in ("valid_coloured_radiance_tail", "biased_colour_contamination"):
                p, classes, truth = make_distribution(scenario, scale)
                # Shared random variates across both lobes keep scale invariance
                # testable; they are synthetic scales, not independent captures.
                for support in SUPPORTS:
                    rng = np.random.default_rng(seed + support)
                    choices = rng.choice(3, (REPETITIONS, support), p=p)
                    samples = classes[choices]
                    mean = samples.mean(axis=1)
                    robust = robust_per_sample_log(samples)
                    raw = np.broadcast_to(truth * [1.18, 0.93, 0.87], mean.shape)
                    raw = raw * (luminance(truth) / luminance(raw))[..., None]
                    linear_out = ratio_apply(raw, mean)
                    log_out = log_apply(raw, mean)
                    max_diff = float(np.max(np.abs(linear_out - log_out)))
                    assert max_diff < 5e-6
                    rows.append({
                        "seed": seed, "lobe_scale_only": lobe, "scale": scale,
                        "scenario": scenario, "support": support,
                        "arithmetic_before_transform": error_metrics(mean, truth),
                        "robust_per_sample_log": error_metrics(robust, truth),
                        "normalized_linear_apply": error_metrics(linear_out, truth),
                        "post_mean_log_apply": error_metrics(log_out, truth),
                        "matched_ratio_vs_log_max_abs": max_diff,
                        "base_denominator_luminance": float(luminance(truth)),
                        "zero_sample_fraction": float(np.mean(choices == 0)),
                        "rare_class_sample_count": int(np.count_nonzero(choices == 2)),
                    })
    return rows


def equivalence_checks() -> dict:
    rng = np.random.default_rng(SEEDS[0])
    # Positive values over ten decades, including extreme channel imbalance.
    raw = np.exp(rng.uniform(np.log(1e-7), np.log(1e3), (10000, 3)))
    target = np.exp(rng.uniform(np.log(1e-7), np.log(1e3), (10000, 3)))
    a = ratio_apply(raw, target)
    b = log_apply(raw, target)
    diff = np.max(np.abs(a - b))
    assert diff < 5e-6
    luma_error = np.max(np.abs(luminance(a) - luminance(raw)))
    identity = ratio_apply(raw, raw)
    assert np.allclose(identity, raw, atol=1e-12, rtol=1e-12)
    c = np.array([0.21, 0.57, 0.13])
    scales = 10.0 ** np.arange(-7, 4)
    scaled = colour(c[None] * scales[:, None])
    scale_error = float(np.max(np.abs(scaled - colour(c))))
    constant = np.broadcast_to(c, (8, 64, 3)).copy()
    constant_estimate = robust_per_sample_log(constant)
    constant_error = float(np.max(np.abs(colour(constant_estimate) - colour(c))))
    assert constant_error < 1e-12
    # Explicit float32 arithmetic path. Luma helpers otherwise promote using
    # float64 weights, so spell out the whole corresponding path here.
    r, t = raw.astype(np.float32), target.astype(np.float32)
    w = LUMA.astype(np.float32)
    cr = (r / (r @ w)[:, None] + np.float32(EPS)) / np.float32(1 + EPS)
    ct = (t / (t @ w)[:, None] + np.float32(EPS)) / np.float32(1 + EPS)
    gr = np.clip(ct / cr, np.float32(.75), np.float32(1.33))
    gl = np.exp(np.clip(np.log(ct) - np.log(cr), np.float32(np.log(.75)),
                        np.float32(np.log(1.33))))
    ar, al = r * gr, r * gl
    ar *= ((r @ w) / (ar @ w))[:, None]
    al *= ((r @ w) / (al @ w))[:, None]
    # Report relative-to-fixed-base-luma precision, not a misleading absolute
    # threshold on arbitrarily bright HDR values.
    f32_relative = float(np.max(np.abs(ar - al) / (r @ w)[:, None]))
    assert f32_relative < 5e-6
    rejected = 0
    for bad in ([0., 0., 0.], [-1., 2., 1.], [float("nan"), 1., 1.],
                [float("inf"), 1., 1.]):
        try:
            colour(np.array(bad))
        except ValueError:
            rejected += 1
    assert rejected == 4
    return {
        "sample_count": 10000, "exposure_interval": [1e-7, 1e3],
        "float64_matched_ratio_log_max_abs": float(diff),
        "float64_luma_max_abs": float(luma_error),
        "float64_scale_invariance_max_abs": scale_error,
        "float32_matched_ratio_log_max_abs": float(np.max(np.abs(ar - al))),
        "float32_matched_ratio_log_max_base_luma_relative": f32_relative,
        "identity_max_abs": float(np.max(np.abs(identity - raw))),
        "robust_constant_colour_closure_max_abs": constant_error,
        "invalid_classes_rejected": rejected,
        "gpu_parity_claimed": False,
    }


def _linear_interpolate_grid(v: np.ndarray, width: int) -> np.ndarray:
    qx = (np.arange(width) + .5) / 4.0 - .5
    lo = np.floor(qx).astype(int)
    fraction = qx - lo
    return (v[np.clip(lo, 0, len(v)-1)] * (1-fraction[:, None]) +
            v[np.clip(lo+1, 0, len(v)-1)] * fraction[:, None])


def mixing_ablation() -> list[dict]:
    """Information-loss witness using oracle regions, not candidate inputs.

    In dirty-target/oracle-reconstruction the correct region-specific raw mean
    is available and target estimate is the only contaminated quantity. The
    oracle exactly assigns each pixel to its own region with no interpolation.
    In clean-target/dirty-reconstruction both target and denominator means are
    oracle-clean and only the resulting gain is mixed at application.
    """
    width = 96
    pixel = np.arange(width)
    left_truth = colour(np.array([.65, .20, .10])) * .2
    right_truth = colour(np.array([.15, .38, .75])) * .2
    left_raw = left_truth * [1.18, .93, .87]
    left_raw *= .2 / luminance(left_raw)
    right_raw = right_truth.copy()
    rows = []
    for phase in range(4):
        left = pixel < 44 + phase
        truth = np.where(left[:, None], left_truth, right_truth)
        raw = np.where(left[:, None], left_raw, right_raw)
        correct_gain = np.where(left[:, None],
                                np.clip(colour(left_truth)/colour(left_raw), .75, 1.33),
                                1.0)
        clean_both = restore(raw, correct_gain)
        # Clean oracle target creates exact per-region gains. Averaging and
        # interpolating those gains is exclusively a reconstruction defect.
        gain_grid = correct_gain.reshape(-1, 4, 3).mean(axis=1)
        dirty_reconstruction = restore(raw, _linear_interpolate_grid(gain_grid, width))
        # Only target means are contaminated. Denominator and target assignment
        # both know the exact region, and no reconstruction interpolation occurs.
        mixed_target = truth.reshape(-1, 4, 3).mean(axis=1)
        assigned_target = mixed_target[pixel // 4]
        dirty_target = ratio_apply(raw, assigned_target)
        right_band = (~left) & (pixel < 48 + phase)
        den = luminance(raw)
        def bleed(out):
            return float(np.max(np.sum(np.abs(out-raw), axis=-1)[right_band] /
                                den[right_band]))
        rows.append({
            "phase": phase, "cell_pixels": 4, "right_band_pixels": int(right_band.sum()),
            "oracle_clean_both_right_contamination": bleed(clean_both),
            "clean_target_dirty_reconstruction_right_max": bleed(dirty_reconstruction),
            "dirty_target_oracle_reconstruction_right_max": bleed(dirty_target),
            "synthetic_oracle_region_assignment": True,
        })
    assert max(r["dirty_target_oracle_reconstruction_right_max"] for r in rows) > .015
    assert max(r["clean_target_dirty_reconstruction_right_max"] for r in rows) > .015
    return rows


def captured_distribution() -> list[dict]:
    rows = []
    for path in sorted((PACKAGE / "fixtures" / "clips").glob("*.npz")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with np.load(path, allow_pickle=False) as fixture:
            for key in ("input_diffuse", "input_specular"):
                a = fixture[key][..., :3].astype(np.float32)
                y = a @ LUMA.astype(np.float32)
                finite = np.isfinite(y)
                tail_threshold = np.quantile(y[finite], .99)
                tail = finite & (y >= tail_threshold)
                rows.append({
                    "fixture": str(path.relative_to(PACKAGE)), "sha256": digest,
                    "role": key, "shape": list(a.shape),
                    "frames": fixture["frame_indices"].astype(int).tolist(),
                    "zero_luminance_fraction": float(np.mean(y == 0)),
                    "nonfinite_luminance_count": int(np.count_nonzero(~finite)),
                    "negative_component_count": int(np.count_nonzero(a < 0)),
                    "luminance_quantiles_50_90_99_999":
                        np.quantile(y[finite], [.5, .9, .99, .999]).tolist(),
                    "top_1_percent_threshold_energy_fraction":
                        float(y[tail].sum(dtype=np.float64) / y[finite].sum(dtype=np.float64)),
                    "top_1_percent_threshold_actual_pixel_fraction": float(tail.mean()),
                    "interpretation": "observed sample distribution only; bright tail legitimacy unknown",
                })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    start = time.perf_counter()
    result = {
        "schema": "native-colour-mechanism-v1", "executor": "mechanism subagent; CPU NumPy",
        "gpu_executed": False, "seeds": list(SEEDS), "supports": list(SUPPORTS),
        "repetitions_per_seed_support": REPETITIONS,
        "frozen_falsifiers_sha256": hashlib.sha256((HERE / "MECHANISM.md").read_bytes()).hexdigest(),
        "numpy_version": np.__version__, "population": population_results(),
        "equivalence": equivalence_checks(), "finite_sample": monte_carlo(),
        "mixing_ablation": mixing_ablation(), "captured_distribution": captured_distribution(),
        "verdict": {
            "robust_per_sample_log_as_unbiased_radiance_target": "reject",
            "post_mean_log_coordinates_as_intrinsic_denoiser": "reject",
            "post_mean_log_coordinates_as_bounded_parameterization": "retain as research representation",
            "estimation_vs_reconstruction_mixing": "separate causal defects reproduced",
        },
    }
    result["elapsed_seconds"] = time.perf_counter() - start
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.name), "verdict": result["verdict"],
                      "population": result["population"], "equivalence": result["equivalence"],
                      "elapsed_seconds": result["elapsed_seconds"]}, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
