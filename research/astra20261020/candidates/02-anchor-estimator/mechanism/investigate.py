"""Small falsifiable mechanism experiments for job 02; no GPU execution.

Only the predeclared development capture 22f9ca14 is inspected. Captured grids
contain already-recalled scalar observations, not independent path samples.
The script deliberately does not derive a noise confidence interval from them.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
ANCHOR = PACKAGE / "portable" / "anchor"
sys.path.insert(0, str(ANCHOR))
import anchor_reference as baseline  # noqa: E402

SEEDS = [1103, 2909, 5419]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def correlation(x, y):
    x, y = np.asarray(x, np.float64), np.asarray(y, np.float64)
    if x.size < 2 or x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def concentration(values):
    x = np.asarray(values, np.float64)
    if not x.size:
        return {"count": 0}
    total = float(x.sum())
    sorted_x = np.sort(x)
    return {
        "count": int(x.size),
        "zero_fraction": float(np.mean(x == 0)),
        "above_physical_cap16_fraction": float(np.mean(x > 16)),
        "min": float(x.min()),
        "median": float(np.median(x)),
        "p90": float(np.percentile(x, 90)),
        "p99": float(np.percentile(x, 99)),
        "max": float(x.max()),
        "sum": total,
        "energy_effective_count": float(total * total / np.square(x).sum()) if np.any(x) else 0.0,
        "top_one_percent_energy_fraction": float(sorted_x[-max(1, int(np.ceil(x.size * .01))):].sum() / total) if total else None,
        "top_five_percent_energy_fraction": float(sorted_x[-max(1, int(np.ceil(x.size * .05))):].sum() / total) if total else None,
    }


def fixture_inventory():
    result = {}
    for group in ("combined", "native_policy"):
        path = ANCHOR / "fixtures" / group / "22f9ca14.npz"
        with np.load(path, allow_pickle=False) as archive:
            data = {key: archive[key] for key in archive.files}
        frames = []
        for index, ordinal in enumerate(data["frames"]):
            stats = data["stats"][index].astype(np.float32)
            recalled = data["recalled"][index].astype(np.float32)
            mask = data["fixed_mask"][index]
            assert np.array_equal(mask, baseline.fixed_measurement_mask(stats, recalled))
            x, y = stats[..., 0][mask], recalled[..., 0][mask]
            positive = mask & (stats[..., 0] > 0) & (recalled[..., 0] > 0)
            logs = np.zeros(mask.shape, np.float64)
            logs[positive] = np.log(stats[..., 0][positive] / recalled[..., 0][positive])
            hpair = positive[:, 1:] & positive[:, :-1]
            vpair = positive[1:] & positive[:-1]
            gain = baseline.predict(stats, recalled, int(data["k"][index]),
                                    float(data["frame_ratio"][index]),
                                    policy="native" if group == "native_policy" else "combined")
            unsupported = ~mask
            frame = {
                "frame": int(ordinal),
                "motion_window_age": int(data["k"][index]),
                "fixed_support_count": int(mask.sum()),
                "fixed_support_fraction": float(mask.mean()),
                "current_static_without_own_recall_count": int(((stats[..., 2] > .5) & (recalled[..., 1] < .5)).sum()),
                "current": concentration(x),
                "recalled": concentration(y),
                "paired_level_pearson": correlation(x, y),
                "paired_log_ratio_median": float(np.median(logs[positive])) if positive.any() else None,
                "paired_log_ratio_mad": float(np.median(np.abs(logs[positive] - np.median(logs[positive])))) if positive.any() else None,
                "log_residual_horizontal_correlation": correlation(logs[:, 1:][hpair], logs[:, :-1][hpair]),
                "log_residual_vertical_correlation": correlation(logs[1:][vpair], logs[:-1][vpair]),
                "zero_pair_count": int((mask & ~positive).sum()),
                "observed_frame_ratio": float(data["frame_ratio"][index]),
                "unclipped_stored_field_ratio": float(y.sum(dtype=np.float64) / x.sum(dtype=np.float64)),
                "ratio_provenance": "exact exported 1/1024 counters" if group == "combined" else "bounded pre-store native 16.16 estimate",
                "baseline_changed_unsupported_cell_count": int(((gain < 1) & unsupported).sum()),
                "baseline_full_grid_energy_gain": baseline.input_energy_gain(stats, gain),
            }
            if group == "native_policy":
                bounds = data["frame_ratio_bounds"][index].astype(float)
                threshold = float(baseline.reject_threshold(int(data["k"][index])))
                frame["native_ratio_bounds"] = bounds.tolist()
                frame["native_strict_guard_constant_on_interval"] = bool((1 - bounds[1] > threshold) == (1 - bounds[2] > threshold))
            frames.append(frame)
        adjacent = []
        for index in range(1, len(frames)):
            if int(data["frames"][index]) - int(data["frames"][index - 1]) != 1:
                continue
            a = data["stats"][index - 1].astype(np.float64)
            b = data["stats"][index].astype(np.float64)
            m = data["fixed_mask"][index - 1] & data["fixed_mask"][index]
            adjacent.append({
                "frames": [int(data["frames"][index - 1]), int(data["frames"][index])],
                "fixed_intersection_count": int(m.sum()),
                "screen_grid_current_level_correlation": correlation(a[..., 0][m], b[..., 0][m]),
                "qualification": "same grid positions; not motion aligned and not a Monte Carlo temporal correlation estimate",
            })
        result[group] = {
            "path": path.relative_to(PACKAGE).as_posix(),
            "sha256": sha256(path),
            "arrays": {k: {"shape": list(v.shape), "dtype": str(v.dtype)} for k, v in data.items()},
            "frames": frames,
            "consecutive_pairs_only": adjacent,
            "missing_ordinals_not_interpolated": True,
            "raw_history_not_reconstructed": True,
        }
    return result


def uniform_fields(shape=(32, 32), level=1.0, reference=1.0):
    s = np.zeros((*shape, 4), np.float32)
    r = np.zeros_like(s)
    s[..., 0], s[..., 1], s[..., 2] = level, 1.0, 1.0
    r[..., 0], r[..., 1], r[..., 3] = reference, 1.0, 1.0
    return s, r


def analytic_null():
    cases = []
    for a in (.01, .05, .1, .2):
        x = np.array([1 - a, 1 + a], np.float64)
        y = x[::-1]
        output = np.minimum(x, y)
        assert np.isclose(output.mean(), 1 - a)
        assert x.sum() == y.sum()
        cases.append({"amplitude": a, "input_mean": float(x.mean()),
                      "reference_mean": float(y.mean()),
                      "output_mean": float(output.mean()), "analytic_output_mean": 1 - a})
    # Large blocks survive the native 3x3 step3 ratio-of-sums smoothing.
    s, r = uniform_fields()
    s[:, :16, 0], s[:, 16:, 0] = 1.1, .9
    r[:, :16, 0], r[:, 16:, 0] = .9, 1.1
    g = baseline.predict(s, r, 0, 1.0, policy="native")
    dose = float(np.sum(s[..., 0].astype(float) * (1 - g.astype(float)))) / float(s[..., 0].sum(dtype=float))
    drift = baseline.input_energy_gain(s, g) - 1
    assert np.isclose(drift, -dose)
    assert drift < -.01
    return {"two_cell_exact": cases, "block_native_baseline": {
        "physical_current_reference_global_energy_equal": True,
        "gain_mean": float(g.mean()), "energy_drift": drift, "correction_dose": dose,
        "proof": "drift = -dose for every non-brightening gain on nonnegative inputs, independently of noise model"}}


def identifiability():
    probes = []
    for change in (.5, .8, 1 / 1.4, 1 / 1.25, 1 / 1.1, 1.1, 1.25, 1.4, 2.0):
        s, r = uniform_fields(level=change)
        g = baseline.predict(s, r, 0, 1 / change, policy="native")
        # Two causes have deliberately byte-identical visible arrays/metadata.
        true_light_observations = s.tobytes() + r.tobytes()
        estimator_bias_observations = s.copy().tobytes() + r.copy().tobytes()
        assert true_light_observations == estimator_bias_observations
        probes.append({"change": change, "observation_sha256": hashlib.sha256(true_light_observations).hexdigest(),
                       "baseline_gain": float(g.mean()),
                       "response_fraction": float((change * g.mean() - 1) / (change - 1)),
                       "two_causes_identical_observations": True,
                       "light_truth": change, "bias_truth": 1.0})
    return {"cases": probes,
            "additional_observation": "independent same-pose high-sample native physical D/S reference with controlled known illumination intervention, or a certified external illumination-change interval; neither is packaged",
            "bound": "For observations X=aR: preserving true light requires gain=1; removing excess requires gain=1/a. No deterministic or randomized function of identical observations can guarantee both."}


def sampling_sparse_tail():
    # D3D linear texture coordinate pixel/size maps to pixel-0.5 texel index.
    selected = np.zeros((8, 8), bool)
    selected[np.ix_([1, 2, 5, 6], [1, 2, 5, 6])] = True
    outcomes = []
    for y in range(8):
        for x in range(8):
            image = np.zeros((8, 8), np.float64)
            image[y, x] = 64.0
            outcomes.append(float(image[selected].mean()))
    outcomes = np.asarray(outcomes)
    assert np.isclose(outcomes.mean(), 1)
    assert np.isclose(outcomes.var(), 3)
    return {"all_spike_positions": 64, "sampled_texels": int(selected.sum()),
            "full_64_texel_mean": 1.0, "four_bilinear_tap_mean_expected": float(outcomes.mean()),
            "four_tap_mean_variance": float(outcomes.var()),
            "miss_probability": float(np.mean(outcomes == 0)),
            "hit_estimate": float(outcomes.max()),
            "claim_scope": "synthetic static single-spike 8x8 cell, no D3D sampler precision issue at exact half fractions; not a claim that captured residual is pure path noise"}


def support_interventions():
    results = []
    for label in ("full", "one_centre_missing_recall", "moving_centre", "one_tap_only", "no_recall"):
        s, r = uniform_fields((17, 17), 1.25, 1.0)
        p = (8, 8)
        if label == "one_centre_missing_recall":
            r[p][1] = 0
        elif label == "moving_centre":
            s[p][2] = 0
            r[p][1] = 0
            r[p][3] = 0
        elif label == "one_tap_only":
            r[..., 1] = 0
            r[5, 5, 1] = 1
        elif label == "no_recall":
            r[..., 1] = 0
        mask = baseline.fixed_measurement_mask(s, r)
        g = baseline.predict(s, r, 0, .8, policy="native")
        results.append({"name": label, "centre_gain": float(g[p]),
                        "changed_without_fixed_support": int(((g < 1) & ~mask).sum()),
                        "fixed_support_count": int(mask.sum()),
                        "energy_gain": baseline.input_energy_gain(s, g)})
    assert results[1]["centre_gain"] < 1
    assert results[2]["centre_gain"] == 1
    assert results[3]["changed_without_fixed_support"] > 0
    return results


def bilinear_boundary():
    # Exact ideal linear interpolation for one cell boundary at full pixel x=64.
    # No guide/depth/alpha changes are claimed. This is Apply's scalar field.
    width, grid_width = 128, 16
    gains = np.ones(grid_width, np.float64)
    gains[:8] = .8
    x = (np.arange(width) + .5) / width * grid_width - .5
    lo = np.floor(x).astype(int)
    frac = x - lo
    full = gains[np.clip(lo, 0, grid_width-1)] * (1-frac) + gains[np.clip(lo+1, 0, grid_width-1)] * frac
    dynamic = np.arange(width) >= 64
    changed = dynamic & (full < 1)
    assert int(changed.sum()) == 4
    return {"grid_static_gain": .8, "grid_dynamic_gain": 1,
            "dynamic_full_pixel_count": int(dynamic.sum()),
            "changed_dynamic_pixel_count_per_row": int(changed.sum()),
            "max_dynamic_pixel_loss": float((1-full[dynamic]).max()),
            "dynamic_side_mean_loss": float((1-full[dynamic]).mean()),
            "boundary_gains_x60_to67": full[60:68].tolist(),
            "scope": "ideal bilinear CPU scalar Apply; hardware sampler parity is a separate local gate"}


def physical_thresholds():
    records = []
    for level in (2**-25, 2**-24, 2**-17, 2**-16, 1e-4, .01, .0625, .1, 1.0, 15.0, 16.0, 20.0, 32.0):
        reference = .8 * level
        d = int(np.clip(level, 0, 16) * 65536)
        n = int(np.clip(reference, 0, 16) * 65536)
        ds = int(np.clip(level * 256, 0, 16) * 65536)
        ns = int(np.clip(reference * 256, 0, 16) * 65536)
        records.append({"current_physical": level, "recalled_physical": reference,
                        "current_half_stored": float(np.float16(level)),
                        "current_native_increment": d, "recalled_native_increment": n,
                        "native_ratio_or_no_measurement": n/d if d else None,
                        "forbidden_scaled_physical_ratio": ns/ds if ds else None,
                        "physical_cap_active": level > 16 or reference > 16})
    assert next(r for r in records if r["current_physical"] == .1)["forbidden_scaled_physical_ratio"] == 1
    return records


def interval_guard():
    # Counterexamples use known physical inputs, converted to stored FP16.
    # Averages near a strict branch cannot certify a pre-store decision.
    s, r = uniform_fields((8, 8), 1.0, .7)
    central, lo, hi, count = baseline.frame_ratio_from_stored_fields(s, r)
    threshold = float(baseline.reject_threshold(10))
    flags = [bool((1-v) > threshold) for v in (lo, hi)]
    assert flags[0] != flags[1]
    return {"constructed_current": 1.0, "constructed_reference": .7,
            "native_ratio_estimate": central, "interval": [lo, hi], "count": count,
            "strict_reject_threshold": threshold, "guard_at_endpoints": flags,
            "decision": "uncertain: abstain; a central estimate alone is insufficient"}


def correlation_controls():
    # Pure synthetic independent/same-block/temporal noise; equal expected energy.
    # Baseline is evaluated with the exact paired sums, not a fabricated label.
    records = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        h = w = 32
        for kind in ("independent", "spatial_blocks8", "temporal_ar09", "sparse_burst"):
            outcomes = []
            # Stationary initialization prevents warmup variance from being
            # mistaken for a benefit of temporal correlation.
            state = rng.normal(size=(h, w))
            for frame in range(32):
                z = rng.normal(size=(h, w))
                if kind == "spatial_blocks8":
                    z = np.repeat(np.repeat(rng.normal(size=(4, 4)), 8, 0), 8, 1)
                if kind == "temporal_ar09":
                    state = .9 * state + np.sqrt(1 - .9**2) * z
                    z = state
                if kind == "sparse_burst":
                    z = np.zeros((h, w), float)
                    z[rng.random((h, w)) < .01] = 2.5
                # Normalize each visible frame to exactly equal global energy;
                # this leaves only local variation and support unchanged.
                current = np.exp(.25 * z)
                current /= current.mean()
                s, r = uniform_fields((h, w))
                s[..., 0] = current.astype(np.float32)
                ratio = float(r[..., 0].sum(dtype=float)/s[..., 0].sum(dtype=float))
                g = baseline.predict(s, r, 0, ratio, policy="native")
                outcomes.append(1-baseline.input_energy_gain(s, g))
            records.append({"seed": seed, "kind": kind, "frames": 32,
                            "mean_false_positive_energy_dose": float(np.mean(outcomes)),
                            "std_frame_energy_dose": float(np.std(outcomes)),
                            "dose_lag1_correlation": correlation(outcomes[:-1], outcomes[1:]),
                            "trajectory": outcomes})
    return records


def main():
    result = {
        "task": "02-anchor-estimator", "executor": "mechanism subagent CPU NumPy",
        "gpu_executed": False, "development_capture": "22f9ca14",
        "holdout_npz_opened": False,
        "historical_metadata_disclosure": "The shared published manifest includes historical summaries for all captures; no held-out NPZ numerical arrays are used here.",
        "seeds": SEEDS, "numpy_version": np.__version__,
        "baseline_source_sha256": sha256(ANCHOR / "anchor_reference.py"),
        "script_sha256": sha256(__file__),
        "fixture_inventory": fixture_inventory(),
        "one_sided_null": analytic_null(),
        "identifiability": identifiability(),
        "sparse_sampling": sampling_sparse_tail(),
        "support_only_intervention": support_interventions(),
        "full_resolution_boundary": bilinear_boundary(),
        "physical_scale": physical_thresholds(),
        "strict_guard_quantization_counterexample": interval_guard(),
        "synthetic_correlation_controls": correlation_controls(),
    }
    path = HERE / "results.json"
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    native = result["fixture_inventory"]["native_policy"]["frames"]
    summary = {
        "output": path.name, "self_checks": "passed", "development_native": [
            {"frame": f["frame"], "coverage": f["fixed_support_fraction"],
             "top1_energy": f["current"]["top_one_percent_energy_fraction"],
             "energy_effective_count": f["current"]["energy_effective_count"],
             "valid_count": f["fixed_support_count"],
             "changed_unsupported": f["baseline_changed_unsupported_cell_count"]} for f in native],
        "null": result["one_sided_null"]["block_native_baseline"],
        "sampling": result["sparse_sampling"],
        "strict_guard": result["strict_guard_quantization_counterexample"],
    }
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
