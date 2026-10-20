"""Independent post-freeze held-out audit and scalar metric reproduction.

The synthetic generator is the shared preregistered generator. Gain/energy and
response calculations here are independent of metrics.py and its aggregations.
This file writes only reviewer/ and never tunes or changes candidate constants.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
PACKAGE = HERE.parents[2]
sys.path.insert(0, str(CANDIDATE))
sys.path.insert(0, str(PACKAGE / "portable/anchor"))
import anchor_reference as old
import estimator as candidate
from experiments import make_sequence


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def own_dose(level, gain, mask):
    x = np.asarray(level, np.float64)[mask]
    g = np.asarray(gain, np.float64)[mask]
    return float(np.sum(x * (1. - g)) / np.sum(x)) if np.sum(x) else None


def synthetic_ratio(stats, recalled):
    mask = old.fixed_measurement_mask(stats, recalled)
    den = np.floor(np.clip(stats[..., 0][mask].astype(np.float64), 0, 16) * 65536).sum()
    num = np.floor(np.clip(recalled[..., 0][mask].astype(np.float64), 0, 16) * 65536).sum()
    return min(float(num / den), 4.) if den else 1.


def old_sequence(seq, strength):
    gs = []
    for i, (s, r) in enumerate(zip(seq["stats"], seq["recalled"])):
        if not seq["active"][i] or seq["reset"][i]:
            gs.append(np.ones(s.shape[:2], np.float32))
        else:
            gs.append(old.predict(s, r, int(seq["ages"][i]), synthetic_ratio(s, r),
                                  policy="native", strength=strength))
    return np.asarray(gs)


def diagnostic_sequence(seq):
    gs = []
    for i, (s, r) in enumerate(zip(seq["stats"], seq["recalled"])):
        output = candidate.estimate(s, r, int(seq["ages"][i]),
            active=bool(seq["active"][i]), reset=bool(seq["reset"][i]))
        assert np.all(output["gain"] == 1) and np.all(output["abstain"])
        gs.append(output["provisional_gain"])
    return np.asarray(gs)


def synthetic_reproduction():
    calibration = make_sequence("known_excess")
    diag = diagnostic_sequence(calibration)
    native = old_sequence(calibration, 1.)
    target = min(own_dose(calibration["stats"][..., 0], g, calibration["mask"]) for g in (diag, native))
    # Here the provisional full-strength dose is the smaller attainable dose.
    assert abs(target - own_dose(calibration["stats"][..., 0], diag, calibration["mask"])) < 1e-15
    lo, hi = 0., 1.
    best = (float("inf"), None, None)
    for _ in range(32):
        strength = .5 * (lo + hi)
        g = old_sequence(calibration, strength)
        dose = own_dose(calibration["stats"][..., 0], g, calibration["mask"])
        if abs(dose - target) < best[0]:
            best = abs(dose - target), strength, dose
        if dose < target:
            lo = strength
        else:
            hi = strength
    strength = best[1]
    seq = make_sequence("equal_energy_antithetic")
    null_baseline = own_dose(seq["stats"][..., 0], old_sequence(seq, strength), seq["mask"])
    null_diag = own_dose(seq["stats"][..., 0], diagnostic_sequence(seq), seq["mask"])
    assert null_diag > null_baseline
    lights = []
    for step in (1.1, 1.25, 1.4):
        seq = make_sequence("light_during_motion", step=step)
        mask = seq["mask"][6:28]
        desired = seq["truth"][6:28] - seq["base_truth"]
        denom = float(desired[mask].sum())
        row = {"step": step}
        for name, g in (("baseline", old_sequence(seq, strength)),
                        ("provisional_diagnostic", diagnostic_sequence(seq)),
                        ("deployed_abstainer", np.ones_like(seq["stats"][..., 0]))):
            observed = seq["stats"][6:28, ..., 0].astype(np.float64) * g[6:28] - seq["base_truth"]
            row[name + "_response_area"] = float(observed[mask].sum() / denom)
        assert row["provisional_diagnostic_response_area"] < row["baseline_response_area"]
        lights.append(row)
    return {"shared_component": "preregistered synthetic data generator only; scalar metrics computed independently",
            "positive_calibration_target_dose": target,
            "baseline_matched_strength": strength,
            "baseline_matched_dose": best[2],
            "diagnostic_strength": 1.,
            "absolute_dose_residual": best[0],
            "antithetic_null_baseline_loss": null_baseline,
            "antithetic_null_diagnostic_loss": null_diag,
            "diagnostic_rejected_as_active_correction": True,
            "light_response_areas_22_frames": lights,
            "deployed_dose": 0., "deployed_positive_dose_comparison": None}


def heldout_reproduction():
    result = {}
    for group in ("native_policy", "combined"):
        path = PACKAGE / "portable/anchor/fixtures" / group / "2405579e.npz"
        with np.load(path, allow_pickle=False) as z:
            data = {key: z[key] for key in z.files}
        mask = data["fixed_mask"].astype(bool)
        mask_hash = hashlib.sha256(mask.tobytes()).hexdigest()
        assert np.array_equal(mask, old.fixed_measurement_mask(data["stats"], data["recalled"]))
        frames = data["frames"]
        assert np.all(np.diff(frames) > 0)
        gs_old, gs_diag, gs_deploy, eligibility, trajectories = [], [], [], [], []
        for i, (s, r) in enumerate(zip(data["stats"], data["recalled"])):
            g_old = old.predict(s, r, int(data["k"][i]), float(data["frame_ratio"][i]),
                               policy="native" if group == "native_policy" else "combined")
            out = candidate.estimate(s, r, int(data["k"][i]))
            assert np.all(out["gain"] == 1) and np.all(out["abstain"])
            assert np.isfinite(out["provisional_gain"]).all()
            gs_old.append(g_old); gs_diag.append(out["provisional_gain"])
            gs_deploy.append(out["gain"]); eligibility.append(out["eligible"])
            trajectories.append({"frame": int(frames[i]), "k": int(data["k"][i]),
                "fixed_mask_cells": int(mask[i].sum()),
                "old_dose": own_dose(s[..., 0], g_old, mask[i]),
                "diagnostic_dose": own_dose(s[..., 0], out["provisional_gain"], mask[i]),
                "deployed_dose": own_dose(s[..., 0], out["gain"], mask[i])})
        assert mask_hash == hashlib.sha256(mask.tobytes()).hexdigest()
        result[group] = {
            "fixture_sha256": sha(path), "mask_sha256": mask_hash,
            "frame_ids": frames.astype(int).tolist(),
            "adjacent_original_frame_pairs": int(np.sum(np.diff(frames) == 1)),
            "old_stored_gpu_gain_max_abs_difference": float(np.max(np.abs(np.asarray(gs_old) - data["gain"]))),
            "fixed_mask_samples": int(mask.sum()),
            "old_dose": own_dose(data["stats"][..., 0], np.asarray(gs_old), mask),
            "provisional_diagnostic_dose": own_dose(data["stats"][..., 0], np.asarray(gs_diag), mask),
            "deployed_dose": own_dose(data["stats"][..., 0], np.asarray(gs_deploy), mask),
            "numeric_eligible_fraction_on_original_mask": float(np.asarray(eligibility)[mask].mean()),
            "deployed_abstention_fraction": 1.,
            "trajectory": trajectories,
            "quality_truth_available": False,
            "native_atomic_sums_present": False,
            "domain": "native D+S stored calibration" if group == "native_policy" else "separate combined stress; no native claim"}
    return result


def main():
    start = time.perf_counter()
    freeze = json.loads((CANDIDATE / "evidence/FROZEN_SOURCE.json").read_text())
    for relative, expected in freeze["files"].items():
        assert sha(CANDIDATE / relative) == expected, "post-freeze source changed: " + relative
    result = {"executor": "independent skeptical reviewer CPU",
              "gpu_executed": False, "frozen_utc": freeze["frozen_utc"],
              "frozen_source_hashes_verified": len(freeze["files"]),
              "heldout_release": "explicit coordinator message after source freeze; no tuning",
              "heldout": heldout_reproduction(),
              "synthetic_independent_metric_check": synthetic_reproduction()}
    result["elapsed_seconds"] = time.perf_counter() - start
    result["reviewer_script_sha256"] = sha(Path(__file__))
    (HERE / "holdout_reproduction.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"freeze_verified": result["frozen_source_hashes_verified"],
                      "heldout": {k: {a: v[a] for a in ("old_dose", "provisional_diagnostic_dose", "deployed_dose")} for k, v in result["heldout"].items()},
                      "synthetic": result["synthetic_independent_metric_check"]}, indent=2))


if __name__ == "__main__":
    main()
