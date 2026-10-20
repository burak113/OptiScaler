"""Reproducible, deliberately falsifiable estimator experiments (CPU only).

Run from any directory; artifacts remain beside this file under evidence/.
Only --include-holdout reads held-out anchor arrays. It requires a frozen source
receipt written before release. Synthetic causes are analytic labels, not
classifications of the real captures. No chronological input is looped.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from estimator import DEFAULT_CONFIG, estimate, frame_interval, bilinear_gain
from metrics import (BASELINE, HERE, PACKAGE, baseline_gain, sequence_metrics,
                     response_metrics)


PROTOCOL = json.loads((HERE / "EXPERIMENT_PROTOCOL.json").read_text())
SEEDS = PROTOCOL["synthetic_seeds"]
H, W = PROTOCOL["synthetic_grid_hw"]
T = PROTOCOL["synthetic_frames"]
ONSET = PROTOCOL["light_step_onset"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def fields(x, y, static=None, valid=None):
    x, y = np.broadcast_arrays(np.asarray(x), np.asarray(y))
    s, r = np.zeros((*x.shape, 4), np.float16), np.zeros((*x.shape, 4), np.float16)
    s[..., 0], s[..., 1], s[..., 2] = x, 1., 1. if static is None else static
    r[..., 0], r[..., 1], r[..., 3] = y, 1. if valid is None else valid, s[..., 2]
    return s, r


def texture():
    yy, xx = np.mgrid[:H, :W]
    return 1. + .15 * np.sin(xx * .7) + .10 * np.cos(yy * .8)


def make_sequence(kind, seed=SEEDS[0], step=1.25):
    rng = np.random.default_rng(seed)
    base = texture()
    truth = np.repeat(base[None], T, axis=0)
    current, reference = truth.copy(), truth.copy()
    static, valid = np.ones((T, H, W), bool), np.ones((T, H, W), bool)
    active, reset = np.arange(T) <= 25, np.zeros(T, bool)
    ages = np.arange(T)
    sigma = PROTOCOL["noise_sigma_log"]
    if kind in ("stationary_independent", "spatial_correlated", "temporal_correlated", "heavy_tail_bursts"):
        if kind == "spatial_correlated":
            # Distinct coordinates within a 4x4 block share one stochastic sample.
            z = rng.standard_normal((2, T, H // 4, W // 4)).repeat(4, 2).repeat(4, 3)
        elif kind == "temporal_correlated":
            rho = PROTOCOL["temporal_ar1"]
            z = rng.standard_normal((2, T, H, W))
            for t in range(1, T):
                z[:, t] = rho * z[:, t - 1] + np.sqrt(1. - rho * rho) * z[:, t]
        else:
            z = rng.standard_normal((2, T, H, W))
        noise = np.exp(sigma * z - .5 * sigma * sigma)
        if kind == "heavy_tail_bursts":
            p, a = PROTOCOL["heavy_tail_probability"], PROTOCOL["heavy_tail_multiplier"]
            noise *= np.where(rng.random(noise.shape) < p, a, 1.) / (1. + p * (a - 1.))
        current *= noise[0]; reference *= noise[1]
    elif kind == "equal_energy_antithetic":
        truth[:] = 1.; base = np.ones_like(base)
        yy, xx = np.mgrid[:H, :W]
        residual = np.where((xx // 4) % 2 == 0, .12, -.12)
        for t in range(T):
            sign = 1 if t % 2 == 0 else -1
            current[t] = 1. + sign * residual
            reference[t] = 1. - sign * residual
    elif kind in ("sparse_support", "unbalanced_valid_masks", "new_view"):
        # Same radiance for the support interventions; no claimed pure-noise cause.
        current *= 1.18
        truth = current.copy()
        if kind == "sparse_support":
            valid = rng.random(valid.shape) < .08
        elif kind == "unbalanced_valid_masks":
            current[:, :, W // 2:] *= .70
            truth = current.copy()
            valid[:, :, W // 2:] = False
        else:
            for t in range(T):
                valid[t, :, :min(1 + t // 3, W // 2)] = False
    elif kind == "camera_cut_reset":
        for t in range(T):
            current[t] *= 1.18 if t < 16 else .8
        truth = current.copy()
        reset[16] = True
        valid[16:20] = False
        reference[20:] *= .8
        ages[16:] = np.arange(T - 16)
        active[:] = True
    elif kind == "known_excess":
        # Analytic true energy stays fixed. The disturbance is constructed, not
        # inferred, so matching removal here has an unambiguous calibration label.
        current *= (1. + .18 * np.exp(-np.arange(T) / 10.))[:, None, None]
    elif kind in ("light_same_pose_armed", "light_during_motion", "light_same_pose_unarmed", "moving_object_light"):
        current[ONSET:] *= step
        truth = current.copy()
        if kind == "light_during_motion":
            ages[ONSET:ONSET + 4] = 0
            ages[ONSET + 4:] = np.arange(1, T - ONSET - 3)
            active[:] = True
        elif kind == "light_same_pose_unarmed":
            active[:] = False
        if kind == "moving_object_light":
            for t in range(T):
                x0 = 4 + t // 4
                region = np.s_[8:15, x0:x0 + 5]
                current[t][region] = 2.
                truth[t][region] = 2.
                reference[t][region] = 2.
                static[t][region] = False; valid[t][region] = False
    elif kind != "exact_identity":
        raise ValueError(kind)
    s, r = fields(current, reference, static, valid)
    # Evaluation mask is fixed before running either algorithm, and includes
    # invalid/dynamic pixels for whole-field safety. Support is reported separately.
    return {"kind": kind, "stats": s, "recalled": r, "truth": truth,
            "base_truth": base, "static": static, "valid": valid & static,
            "mask": np.ones((T, H, W), bool), "frames": np.arange(T),
            "ages": ages, "active": active, "reset": reset,
            "seed": seed, "step": step}


def evaluate(seq, baseline_strength=1., provisional_strength=1., config=DEFAULT_CONFIG):
    baseline, provisional, certified, eligible = [], [], [], []
    for t, (s, r) in enumerate(zip(seq["stats"], seq["recalled"])):
        common = {"active": bool(seq["active"][t]), "reset": bool(seq["reset"][t])}
        baseline.append(baseline_gain(s, r, int(seq["ages"][t]), strength=baseline_strength, **common))
        result = estimate(s, r, int(seq["ages"][t]), strength=provisional_strength, config=config, **common)
        provisional.append(result["provisional_gain"])
        certified.append(result["gain"])
        eligible.append(result["eligible"])
    gains = {"baseline": np.asarray(baseline), "provisional_diagnostic": np.asarray(provisional),
             "causal_abstainer": np.asarray(certified)}
    metrics = {}
    for name, gain in gains.items():
        abstain = np.ones_like(gain, bool) if name == "causal_abstainer" else (
            ~np.asarray(eligible) if name == "provisional_diagnostic" else None)
        metrics[name] = sequence_metrics(seq["stats"][..., 0], gain, seq["mask"],
            seq["frames"], seq["ages"], truth=seq["truth"], valid=seq["valid"],
            static=seq["static"], abstain=abstain)
        if "light" in seq["kind"] and seq["kind"] != "moving_object_light":
            metrics[name]["light_response"] = response_metrics(seq["truth"],
                seq["stats"][..., 0].astype(np.float64) * gain, seq["base_truth"], seq["mask"],
                onset=ONSET, window=PROTOCOL["response_window_frames"])
    return metrics, gains


def match_known_excess():
    seq = make_sequence("known_excess")
    full, _ = evaluate(seq)
    target = min(full[n]["correction_dose"] for n in ("baseline", "provisional_diagnostic"))
    strengths, actual = {}, {}
    for name in ("baseline", "provisional_diagnostic"):
        lo, hi = 0., 1.
        best = (float("inf"), 0., 0.)
        for value in [0., 1.] + [None] * 22:
            strength = (lo + hi) * .5 if value is None else value
            ms, _ = evaluate(seq, baseline_strength=strength if name == "baseline" else 1.,
                             provisional_strength=strength if name != "baseline" else 1.)
            dose = ms[name]["correction_dose"]
            if abs(dose - target) < best[0]:
                best = (abs(dose - target), strength, dose)
            if dose < target:
                lo = strength
            else:
                hi = strength
        strengths[name], actual[name] = best[1], best[2]
    sweep = []
    for strength in PROTOCOL["strength_sweep"]:
        ms, _ = evaluate(seq, baseline_strength=strength, provisional_strength=strength)
        sweep.append({"strength": strength, "known_excess_dose":
                      {n: ms[n]["correction_dose"] for n in ms}})
    return {"target_dose": target, "strengths": strengths, "achieved_doses": actual,
            "absolute_dose_mismatch": abs(actual["baseline"] - actual["provisional_diagnostic"]),
            "production_abstainer_dose": 0., "production_at_nonzero_matched_dose": None,
            "production_nonmatch_reason": "No causal witness: production abstains; nonzero-dose efficacy is unidentifiable.",
            "full_strength_calibration": full, "strength_sweep": sweep}


def compact(metrics, keep_trajectory=False):
    if keep_trajectory:
        return metrics
    return {n: {k: v for k, v in row.items() if k != "trajectory"} for n, row in metrics.items()}


def aggregate(rows):
    result = {}
    keys = ["correction_dose", "global_energy_drift", "local_error_bias", "local_error_variance",
            "local_error_rmse", "spatial_grain_proxy_rms_over_base_level", "temporal_flicker_proxy_rms_over_base_level",
            "gain_delta_rms", "sparkle_fraction_over_fixed_base_threshold", "unsupported_changed_cells",
            "changed_fraction_on_base_mask", "abstain_fraction_on_base_mask", "early_correction_energy_k0_5",
            "late_correction_energy_k6_25"]
    for name in rows[0]:
        result[name] = {}
        for key in keys:
            vals = [r[name][key] for r in rows if r[name][key] is not None]
            result[name][key] = ({"mean": float(np.mean(vals)), "min": float(np.min(vals)),
                                  "max": float(np.max(vals)), "seeds": len(vals)} if vals else None)
    return result


def synthetic_experiments():
    matched = match_known_excess()
    sb, sp = matched["strengths"]["baseline"], matched["strengths"]["provisional_diagnostic"]
    scenarios = ["exact_identity", "stationary_independent", "spatial_correlated", "temporal_correlated",
                 "heavy_tail_bursts", "equal_energy_antithetic", "sparse_support", "unbalanced_valid_masks",
                 "new_view", "camera_cut_reset"]
    tests = {}
    for kind in scenarios:
        full_rows, matched_rows, per_seed = [], [], []
        seeds = SEEDS if kind in scenarios[1:5] or kind == "sparse_support" else SEEDS[:1]
        for seed in seeds:
            seq = make_sequence(kind, seed)
            full, _ = evaluate(seq)
            match, _ = evaluate(seq, sb, sp)
            full_rows.append(full); matched_rows.append(match)
            per_seed.append({"seed": seed, "full_strength": compact(full, seed == seeds[0]),
                             "matched_excess_dose_strengths": compact(match)})
        tests[kind] = {"full_strength": aggregate(full_rows), "matched_excess_dose_strengths": aggregate(matched_rows),
                       "per_seed": per_seed,
                       "false_positive_scope": "All correction is false-positive for supplied analytic no-excess truth; inputs may include true geometry/light/support changes."}
    lights = []
    for kind in ("light_same_pose_armed", "light_during_motion", "light_same_pose_unarmed"):
        for step in PROTOCOL["light_steps"]:
            seq = make_sequence(kind, step=step)
            full, _ = evaluate(seq); match, _ = evaluate(seq, sb, sp)
            lights.append({"kind": kind, "step": step, "full_strength": compact(full),
                           "matched_excess_dose_strengths": compact(match)})
    moving = make_sequence("moving_object_light", step=1.25)
    ms, gains = evaluate(moving)
    # Independent reviewer requested this denominator before seeing results:
    # remove every original foreground position once, then keep that background
    # region constant for all frames and variants of the joint control.
    background_mask = np.broadcast_to(moving["static"].all(axis=0), moving["mask"].shape)
    for name, gain in gains.items():
        ms[name]["static_background_light_response"] = response_metrics(moving["truth"],
            moving["stats"][..., 0].astype(np.float64) * gain, moving["base_truth"], background_mask,
            onset=ONSET, window=PROTOCOL["response_window_frames"])
        ms[name]["static_background_mask_cells_each_frame"] = int(background_mask[0].sum())
    interpolation = {}
    dynamic_full = (~moving["static"]).repeat(8, 1).repeat(8, 2)
    input_full = moving["stats"][..., 0].astype(np.float64).repeat(8, 1).repeat(8, 2)
    for name, gain in gains.items():
        sampled = np.stack([bilinear_gain(g, H * 8, W * 8) for g in gain])
        loss = input_full * (1. - sampled)
        interpolation[name] = {"scope": "ideal CPU bilinear, not D3D sampler parity or corrected transport",
            "dynamic_base_pixels": int(dynamic_full.sum()),
            "dynamic_changed_pixels": int(np.sum((sampled < 1.) & dynamic_full)),
            "dynamic_relative_energy_loss": float(loss[dynamic_full].sum() / input_full[dynamic_full].sum()),
            "minimum_gain_on_dynamic_pixels": float(sampled[dynamic_full].min())}
    # Same observations, opposite causal labels. Desired outputs differ, so no
    # estimator reading only these arrays can certify the distinction.
    twins = []
    for step in (1.1, 1.25, 1.4):
        s, r = fields(np.full((H, W), step), np.ones((H, W)))
        a, b = estimate(s, r, 0), estimate(s.copy(), r.copy(), 0)
        twins.append({"step": step, "observation_sha256": hashlib.sha256(s.tobytes() + r.tobytes()).hexdigest(),
                      "outputs_identical": bool(np.array_equal(a["provisional_gain"], b["provisional_gain"])),
                      "true_light_target": step, "input_excess_target": 1.,
                      "missing_observable": "independent per-pose physical-light witness"})
    return {"dose_calibration": matched, "null_and_support_controls": tests,
            "true_light_controls": lights, "moving_object_changing_background": compact(ms),
            "moving_object_bilinear_apply": interpolation, "identifiability_twins": twins,
            "rendered_rr_flicker": None, "gpu_executed": False}


def scale_experiments():
    rows = []
    for scale in PROTOCOL["physical_scale_probe"]:
        s, r = fields(np.full((H, W), scale * 1.25), np.full((H, W), scale))
        out = estimate(s, r, 0)
        rows.append({"reference_physical": scale, "current_physical_requested": scale * 1.25,
            "stored_current": float(s[0, 0, 0]), "stored_reference": float(r[0, 0, 0]),
            "frame_ratio": out["frame_ratio"], "production_gain_min": float(out["gain"].min()),
            "provisional_gain_min": float(out["provisional_gain"].min()),
            "eligible_fraction": float(out["eligible"].mean()),
            "reason_counts": {str(int(reason)): int(count) for reason, count in zip(*np.unique(out["reason"], return_counts=True))}})
    # Fixed physical clipping, without recommending a scale change.
    s, r = fields(np.full((H, W), 1.), np.full((H, W), .8))
    scaled = s.copy(); scaled[..., 0] *= 256.
    recalled_scaled = r.copy(); recalled_scaled[..., 0] *= 256.
    return {"scale_rows": rows, "illegal_x256_counterexample": {
        "unscaled_ratio": frame_interval(s, r), "scaled_ratio": frame_interval(scaled, recalled_scaled),
        "interpretation": "Multiplication by256 makes both operands exceed physical cap16 and destroys the physical ratio. Never proposed."}}


def captured_experiments(include_holdout):
    results, plot_arrays = {}, {}
    groups = ("native_policy", "combined")
    captures = ("22f9ca14", "87ee1fba") + (("2405579e",) if include_holdout else ())
    for group in groups:
        for capture in captures:
            path = PACKAGE / "portable/anchor/fixtures" / group / (capture + ".npz")
            with np.load(path, allow_pickle=False) as z:
                arrays = {k: z[k] for k in z.files}
            s, r, mask = arrays["stats"], arrays["recalled"], arrays["fixed_mask"]
            assert np.array_equal(mask, BASELINE.fixed_measurement_mask(s, r))
            original_masks_hash = hashlib.sha256(mask.tobytes()).hexdigest()
            frames, ages = arrays["frames"], arrays["k"]
            baseline, diagnostic, production, eligibility = [], [], [], []
            interval_diagnostics, sensitivity = [], {}
            for i in range(len(s)):
                # Compare the old estimator in its own domain. Combined fields
                # are only a conditional robustness stress, never a native proof.
                baseline.append(baseline_gain(s[i], r[i], int(ages[i]), ratio=arrays["frame_ratio"][i],
                                              policy="native" if group == "native_policy" else "combined"))
                out = estimate(s[i], r[i], int(ages[i]))
                diagnostic.append(out["provisional_gain"]); production.append(out["gain"])
                eligibility.append(out["eligible"])
                interval_diagnostics.append({"frame": int(frames[i]), "bounded_native_model": out["frame_ratio"],
                    "median_log_ratio_on_fixed_mask": float(np.median(out["median_log_ratio"][mask[i]])) if mask[i].any() else None,
                    "reason_counts_on_fixed_mask": {str(int(reason)): int(count) for reason, count in
                        zip(*np.unique(out["reason"][mask[i]], return_counts=True))}})
            variant_gains = {"baseline_cpu": np.asarray(baseline), "historical_stored_gpu_gain": arrays["gain"],
                             "provisional_diagnostic": np.asarray(diagnostic), "causal_abstainer": np.asarray(production)}
            measured = {}
            valid = BASELINE.fixed_measurement_mask(s, r)
            for name, gain in variant_gains.items():
                abstain = np.ones_like(mask) if name == "causal_abstainer" else (
                    ~np.asarray(eligibility) if name == "provisional_diagnostic" else None)
                measured[name] = sequence_metrics(s[..., 0], gain, mask, frames, ages,
                    valid=valid, static=s[..., 2] > .5, abstain=abstain)
            if group == "native_policy":
                # Prespecified sensitivity, all results retained; never tune on holdout.
                for pairs in PROTOCOL["sensitivity_pairs"]:
                    for dispersion in PROTOCOL["sensitivity_dispersion_multiplier"]:
                        cfg = replace(DEFAULT_CONFIG, min_pairs=pairs, dispersion_multiplier=dispersion)
                        gs = np.stack([estimate(s[i], r[i], int(ages[i]), config=cfg)["provisional_gain"] for i in range(len(s))])
                        m = sequence_metrics(s[..., 0], gs, mask, frames, ages, valid=valid, static=s[..., 2] > .5)
                        sensitivity[f"pairs={pairs},dispersion={dispersion}"] = {k: m[k] for k in (
                            "correction_dose", "changed_fraction_on_base_mask", "unsupported_changed_cells")}
            assert original_masks_hash == hashlib.sha256(mask.tobytes()).hexdigest()
            key = group + "/" + capture
            results[key] = {"fixture_sha256": digest(path), "mask_sha256": original_masks_hash,
                "role": "holdout" if capture == "2405579e" else ("development" if capture == "22f9ca14" else "validation"),
                "domain": "native physical D+S" if group == "native_policy" else "combined fields: separately labeled stress only",
                "source_frames": [int(f) for f in frames], "source_k": [int(k) for k in ages],
                "native_original_atomic_sums_present": False,
                "old_cpu_max_abs_gain_difference_from_stored_gpu": float(np.max(np.abs(np.asarray(baseline) - arrays["gain"]))),
                "metrics": measured, "intervals": interval_diagnostics, "prespecified_sensitivity": sensitivity}
            # Keep original aspect and same value scales in plotting. Source grids
            # are measured fields, not a reference radiance photograph.
            if group == "native_policy":
                plot_arrays[capture + "_stats"] = s
                plot_arrays[capture + "_recalled"] = r
                plot_arrays[capture + "_mask"] = mask
                plot_arrays[capture + "_frames"] = frames
                for name, gain in variant_gains.items():
                    plot_arrays[capture + "_" + name] = gain
    return results, plot_arrays


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-holdout", action="store_true")
    args = parser.parse_args()
    if args.include_holdout and not (HERE / "evidence/FROZEN_SOURCE.json").exists():
        raise SystemExit("freeze source/tests before releasing the held-out arrays")
    outdir = HERE / "evidence"
    synthetic = synthetic_experiments()
    write_json(outdir / "synthetic_results.json", synthetic)
    write_json(outdir / "physical_scale_results.json", scale_experiments())
    captured, plots = captured_experiments(args.include_holdout)
    write_json(outdir / "captured_results.json", captured)
    np.savez_compressed(outdir / "fixed_mask_fields.npz", **plots)
    print(json.dumps({"synthetic_scenarios": len(synthetic["null_and_support_controls"]),
        "true_light_controls": len(synthetic["true_light_controls"]),
        "captured_groups": list(captured), "holdout_included": args.include_holdout,
        "matched_excess_strengths": synthetic["dose_calibration"]["strengths"],
        "matched_dose_error": synthetic["dose_calibration"]["absolute_dose_mismatch"],
        "gpu_executed": False}, indent=2))


if __name__ == "__main__":
    main()
