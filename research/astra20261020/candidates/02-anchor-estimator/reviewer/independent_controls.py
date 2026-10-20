"""Independent pre-candidate falsifiers; synthetic CPU evidence only.

This imports only the untouched baseline. It never opens any captured fixture.
Run from any directory; all generated output stays beside this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
sys.path.insert(0, str(PACKAGE / "portable" / "anchor"))
import anchor_reference as baseline

SEEDS = (20261020, 20261021, 20261022)
FACTORS = (0.5, 1 / 1.4, 1 / 1.25, 1 / 1.1, 1.1, 1.25, 1.4, 2.0)


def fields(current: np.ndarray, recalled: np.ndarray):
    s = np.zeros(current.shape + (4,), np.float32)
    r = np.zeros_like(s)
    s[..., 0], s[..., 1], s[..., 2] = current, 1.0, 1.0
    r[..., 0], r[..., 1], r[..., 3] = recalled, 1.0, 1.0
    return s, r


def energy_dose(current, gain):
    current = np.asarray(current, dtype=np.float64)
    return float(np.sum(current * (1 - gain), dtype=np.float64) / current.sum())


def analytic_exchange():
    c = np.array([1.2, 0.8], dtype=np.float64)
    r = c[::-1].copy()
    g = np.minimum(r / c, 1.0)
    expected = float(c.sum() - 0.5 * np.abs(c - r).sum())
    observed = float(np.dot(c, g))
    assert abs(observed - expected) < 1e-12
    assert abs(c.sum() - r.sum()) < 1e-12
    assert abs(observed / c.sum() - 0.8) < 1e-12
    return {"current": c.tolist(), "reference": r.tolist(),
            "frame_ratio": float(r.sum() / c.sum()),
            "output_energy": observed, "input_energy": float(c.sum()),
            "relative_loss": 1 - observed / float(c.sum()),
            "known_bad_rejected": True}


def antithetic_shader():
    # Broad stripes defeat the baseline's sparse 3x3 averaging without changing
    # total frame energy. Exchange signs for the independent antithetic pair.
    xx = np.arange(64)[None, :]
    residual = np.broadcast_to(np.where(xx < 32, 0.2, -0.2), (32, 64))
    result = []
    for sign in (-1, 1):
        c = 1 + sign * residual
        r = 1 - sign * residual
        s, old = fields(c, r)
        gain = baseline.predict(s, old, 0, 1.0, policy="native")
        dose = energy_dose(c, gain)
        assert dose > 1e-3
        result.append({"sign": sign, "frame_ratio": float(r.sum() / c.sum()),
                       "false_positive_dose": dose,
                       "changed_fraction": float(np.mean(gain < 1)),
                       "minimum_gain": float(gain.min())})
    return {"pairs": result, "known_bad_rejected": True}


def real_light_null():
    out = []
    for factor in FACTORS:
        s, r = fields(np.full((16, 16), factor), np.ones((16, 16)))
        trajectory = []
        for k in range(22):
            gain_a = baseline.predict(s, r, k, 1 / factor, policy="native")
            # Different causal labels are intentionally not passed as evidence.
            gain_b = baseline.predict(s.copy(), r.copy(), k, 1 / factor, policy="native")
            assert np.array_equal(gain_a, gain_b)
            output = factor * float(gain_a.mean())
            trajectory.append((output - 1) / (factor - 1))
        first = trajectory[0]
        latency = next((i for i, value in enumerate(trajectory) if value >= 0.95), None)
        out.append({"factor": factor, "response_trajectory": trajectory,
                    "first_frame_response": first,
                    "response_area_22": float(np.mean(trajectory)),
                    "latency_to_95_frames": latency,
                    "identical_observations_identical_output": True,
                    "real_light_safety_rejected": first < 0.95})
    lookup = {entry["factor"]: entry for entry in out}
    assert lookup[1.1]["first_frame_response"] < 0.01
    assert lookup[1.25]["first_frame_response"] < 0.01
    assert lookup[1.4]["first_frame_response"] < 0.31
    for factor in (1 / 1.1, 1 / 1.25, 1 / 1.4):
        assert abs(lookup[factor]["first_frame_response"] - 1) < 1e-12
    return out


def noise_controls():
    out = []
    shape = (32, 32)
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        for kind in ("stationary_independent", "spatial_correlated", "temporal_correlated", "heavy_tail_bursts"):
            doses = []
            previous = np.zeros(shape, np.float64)
            for frame in range(22):
                z = rng.standard_normal(shape)
                if kind == "spatial_correlated":
                    z = np.repeat(np.repeat(rng.standard_normal((4, 4)), 8, axis=0), 8, axis=1)
                elif kind == "temporal_correlated":
                    z = 0.9 * previous + np.sqrt(1 - 0.9**2) * z
                    previous = z
                elif kind == "heavy_tail_bursts":
                    z = z * 0.02 + (rng.random(shape) < 0.01) * rng.lognormal(1, 1, shape)
                c = np.exp(np.clip(z * 0.2, -3, 3))
                r = np.exp(np.clip(-z * 0.2, -3, 3))
                # Fixed all-valid support, exactly equal global physical energy
                # before FP32 storage. Float32 ratio is recorded, not assumed.
                r *= c.sum() / r.sum()
                s, old = fields(c, r)
                exact_ratio = float(old[..., 0].sum(dtype=np.float64) / s[..., 0].sum(dtype=np.float64))
                g = baseline.predict(s, old, frame, exact_ratio, policy="native")
                doses.append(energy_dose(s[..., 0], g))
            out.append({"seed": seed, "kind": kind,
                        "mean_false_positive_dose": float(np.mean(doses)),
                        "variance_of_frame_dose": float(np.var(doses)),
                        "early_dose_sum_k0_7": float(np.sum(doses[:8])),
                        "late_dose_sum_k8_21": float(np.sum(doses[8:])),
                        "trajectory": doses})
    return out


def bilinear_leakage():
    # Coarse gain g=[.8,1], with the right-hand cell declared dynamic. Its
    # nearest 8 full pixels sample toward the .8 neighbor for half their span.
    grid_gain = np.array([0.8, 1.0], np.float64)
    p = np.arange(16, dtype=np.float64)
    q = (p + 0.5) * 2 / 16 - 0.5
    lo = np.floor(q).astype(int)
    a = q - lo
    sampled = (1 - a) * grid_gain[np.clip(lo, 0, 1)] + a * grid_gain[np.clip(lo + 1, 0, 1)]
    dynamic_pixels = p >= 8
    values = sampled[dynamic_pixels]
    assert grid_gain[1] == 1.0
    assert float(values.min()) < 0.99
    assert float(np.mean(values < 1)) == 0.5
    return {"scope": "ideal CPU bilinear; no D3D parity claim",
            "grid_identity_at_dynamic_cell": True,
            "dynamic_pixel_gains": values.tolist(),
            "affected_dynamic_pixel_fraction": float(np.mean(values < 1)),
            "minimum_dynamic_gain": float(values.min()),
            "dynamic_energy_dose_for_unit_level": float(np.mean(1 - values)),
            "centre_identity_protection_claim_rejected": True}


def support_and_global_ratio_controls():
    shape = (32, 32)
    s, r = fields(np.full(shape, 1.25), np.ones(shape))
    original_s, original_r = s.copy(), r.copy()
    support = []
    selections = {"all": np.ones(shape, bool),
                  "none": np.zeros(shape, bool),
                  "single_pair": np.zeros(shape, bool),
                  "left_half": np.indices(shape)[1] < 16,
                  "centre_missing": np.ones(shape, bool)}
    selections["single_pair"][16, 16] = True
    selections["centre_missing"][16, 16] = False
    for name, mask in selections.items():
        old = original_r.copy()
        old[..., 1] = mask
        g = baseline.predict(original_s, old, 0, 0.8, policy="native")
        support.append({"case": name, "fixed_input_level": 1.25,
                        "fixed_reference_level": 1.0,
                        "recall_fraction": float(mask.mean()),
                        "centre_gain": float(g[16, 16]),
                        "whole_input_energy_dose": energy_dose(s[..., 0], g),
                        "changed_fraction": float(np.mean(g < 1))})
    rows = {x["case"]: x for x in support}
    assert rows["none"]["whole_input_energy_dose"] == 0
    assert rows["centre_missing"]["centre_gain"] < 1
    assert rows["all"]["whole_input_energy_dose"] > rows["single_pair"]["whole_input_energy_dose"]

    xx = np.indices(shape)[1]
    current = np.where(xx < 16, 1.1, 0.9)
    reference = np.where(xx < 16, 0.9, 1.2)
    s, r = fields(current, reference)
    ratio = float(reference.sum() / current.sum())
    g = baseline.predict(s, r, 0, ratio, policy="native")
    dose = energy_dose(current, g)
    assert ratio > 1 and dose > 1e-3
    return {"support_only_changes": support,
            "higher_frame_ratio_still_darkens": {
                "frame_ratio": ratio, "input_energy_dose": dose,
                "minimum_gain": float(g.min()),
                "changed_fraction": float(np.mean(g < 1)),
                "harmless_darkening_claim_rejected": True}}


def explicit_mutant():
    # A correctness gate expects a conservative output to preserve a real step.
    # Replacing identity with the known bad estimator is an explicit mutant.
    def safe_real_light_assertion(gain):
        output = 1.25 * float(np.mean(gain))
        assert (output - 1) / 0.25 >= 0.95, "moderate real-light response removed"

    safe_real_light_assertion(np.ones((8, 8)))
    s, r = fields(np.full((8, 8), 1.25), np.ones((8, 8)))
    try:
        safe_real_light_assertion(baseline.predict(s, r, 0, 0.8, policy="native"))
    except AssertionError as error:
        return {"mutation": "replace identity fallback with one-sided native estimate",
                "test_failed_as_required": True, "assertion": str(error)}
    raise AssertionError("falsifier accepted the known bad mutant")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(HERE / "preregistered_control_results.json"))
    args = parser.parse_args()
    begin = time.perf_counter()
    result = {"executor": "independent skeptical reviewer CPU",
              "phase": "before candidate inspection", "gpu_executed": False,
              "fixture_data_opened": [], "seeds": list(SEEDS),
              "analytic_exchange": analytic_exchange(),
              "antithetic_shader": antithetic_shader(),
              "real_light_null": real_light_null(),
              "noise_controls": noise_controls(),
              "bilinear_leakage": bilinear_leakage(),
              "support_and_global_ratio_controls": support_and_global_ratio_controls(),
              "explicit_mutant": explicit_mutant()}
    result["source_sha256"] = {
        str(path.relative_to(PACKAGE)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (HERE / "PREREGISTRATION.md", Path(__file__),
                     PACKAGE / "portable/anchor/anchor_reference.py")}
    result["elapsed_seconds"] = time.perf_counter() - begin
    target = Path(args.output).resolve()
    if not target.is_relative_to(HERE):
        raise ValueError("review outputs must stay inside reviewer/")
    target.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"known_bad_rejected": True,
                      "mutant_rejected": result["explicit_mutant"]["test_failed_as_required"],
                      "analytic_null_loss": result["analytic_exchange"]["relative_loss"],
                      "antithetic_native_dose": [x["false_positive_dose"] for x in result["antithetic_shader"]["pairs"]],
                      "real_light_responses": {str(x["factor"]): x["first_frame_response"] for x in result["real_light_null"]},
                      "output": str(target.relative_to(PACKAGE))}, indent=2))


if __name__ == "__main__":
    main()
