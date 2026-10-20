"""Run source-shaped and analytic H1-H4 discriminators; no game-quality claim."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE / "src"))
from native_subset import capped_history_variance, hybrid_select, seed_flat_patch


def reference_support_probe():
    rows = []
    truth = np.float32(0.03)
    seeds = list(range(31000, 31256))
    yy, xx = np.mgrid[-2:3, -2:3]
    support = {"full_5x5": np.ones((5, 5)), "diamond": ((abs(xx)+abs(yy)) <= 2).astype(float)}
    for count in (1, 4, 16):
        outputs = {name: [] for name in support}
        counts = {name: [] for name in support}
        raw, averages = [], []
        for seed in seeds:
            # Same 16 independent samples and RNG stream across support variants.
            rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
            hit = rng.random((16, 5, 5)) < 0.15
            patch = (hit[:count].mean(0)*float(truth)/0.15).astype(np.float32)
            rgb = np.repeat(patch[..., None], 3, axis=-1)
            raw.append(float(rgb[2, 2, 0])); averages.append(float(rgb[..., 0].mean()))
            for name, weights in support.items():
                out, info = seed_flat_patch(rgb, weights)
                outputs[name].append(float(out[0])); counts[name].append(info["weight_effective_support"])
        def describe(values):
            a = np.array(values)
            return {"mean": float(a.mean()), "bias_from_analytic_truth": float(a.mean()-truth),
                    "rmse": float(np.sqrt(np.mean((a-truth)**2))),
                    "p99_absolute_error": float(np.quantile(abs(a-truth), .99)),
                    "zero_fraction": float(np.mean(a == 0))}
        row = {"independent_history_samples": count, "truth": float(truth), "raw_centre": describe(raw),
               "unweighted_patch_mean_null": describe(averages),
               "source_shaped_seed": {name: describe(out) for name, out in outputs.items()},
               "weight_effective_support_median": {name: float(np.median(c)) for name, c in counts.items()},
               "changed_values_full_vs_diamond": int(np.count_nonzero(np.array(outputs["full_5x5"]) != outputs["diamond"]))}
        rows.append(row)
    return {"kind": "source-shaped CPU subset, flat supplied geometry; independent sparse synthetic inputs",
            "seeds": seeds, "raw_realizations_identical_across_support_interventions": True,
            "selector_fixed": "identity", "rows": rows,
            "native_inference": "Not identified: real Seed/Refine/support/history tensors absent"}


def selector_probe():
    rng = np.random.default_rng(32005)
    frames, paths = 48, 4096
    light = np.ones((frames, 1)); light[24:] = 1.25
    detail = np.full((frames, paths), .03)*light
    rr = np.full((frames, paths), .02)*light
    noisy_w = np.clip(.45 + rng.normal(0, .08, (frames, paths)), 0, 1)
    noisy_k = 1.0 + rng.normal(0, .08, (frames, paths))
    target = hybrid_select(detail, rr, .45, 1.0)
    result = {}
    for label, w, k in (("selector_only", noisy_w, np.ones_like(noisy_k)),
                        ("gain_only", np.full_like(noisy_w, .45), noisy_k),
                        ("both", noisy_w, noisy_k)):
        controls = {"current": hybrid_select(detail, rr, w, k),
                    "replace_selector_only": hybrid_select(detail, rr, .45, k),
                    "replace_gain_only": hybrid_select(detail, rr, w, 1.0),
                    "replace_both": target.copy()}
        frozen_w = np.broadcast_to(w[:1], w.shape)
        frozen_k = np.broadcast_to(k[:1], k.shape)
        controls["freeze_selector_first_frame"] = hybrid_select(detail, rr, frozen_w, k)
        controls["freeze_gain_first_frame"] = hybrid_select(detail, rr, w, frozen_k)
        controls["freeze_output_first_frame"] = np.broadcast_to(controls["current"][:1], target.shape)
        result[label] = {name: {"rmse_from_fixed_selector_gain_truth": float(np.sqrt(np.mean((out-target)**2))),
                               "temporal_error_rms": float(np.sqrt(np.mean(np.diff(out-target, axis=0)**2))),
                               "light_step_ratio_frame24_over23": float(out[24].mean()/out[23].mean())}
                         for name, out in controls.items()}
    # Three latent variables cannot be inferred from just raw and selected RGB.
    observed = hybrid_select(detail, rr, noisy_w, noisy_k)
    reconstructed_detail = (observed-.2*rr)/.8
    reconstructed = hybrid_select(reconstructed_detail, rr, .2, 1.0)
    return {"kind": "synthetic algebra following HybridApply's pre-Glass formula", "frames": frames,
            "realizations": paths, "true_light_step": 1.25, "controls": result,
            "different_latent_decomposition_max_output_error": float(abs(reconstructed-observed).max()),
            "native_inference": "Raw/selected alone cannot identify a unique hidden reference, selector and gain"}


def reflection_probe():
    frames, width = 32, 160
    x = np.arange(width)
    truth = np.stack([.01 + .08*np.exp(-.5*((x-(30+2*t))/1.2)**2) for t in range(frames)])
    truth[16:] *= 1.25
    masks = np.stack([abs(x-(30+2*t)) <= 4 for t in range(frames)])
    outputs = {}
    for label, shift in (("surface_zero_motion", 0), ("true_virtual_feature_motion", 2)):
        history = truth[0].copy(); result = [history.copy()]
        for t in range(1, frames):
            previous = np.full(width, np.nan)
            if shift:
                previous[shift:] = history[:-shift]
            else:
                previous[:] = history
            valid = np.isfinite(previous)
            current = truth[t].copy()
            current[valid] = previous[valid] + (truth[t, valid]-previous[valid])/8.0
            history = current; result.append(current.copy())
        out = np.stack(result)
        outputs[label] = {"feature_mae": float(np.mean(abs(out-truth)[masks])),
                          "all_pixel_rmse": float(np.sqrt(np.mean((out-truth)**2))),
                          "first_light_change_feature_relative_error": float(np.mean(abs(out[16]-truth[16])[masks[16]])/np.mean(truth[16][masks[16]]))}
    return {"kind": "analytic moving reflected feature; surface fixed and virtual correspondence explicitly known",
            "surface_mv_pixels": 0, "reflected_feature_pixels_per_frame": 2, "frames": frames,
            "true_light_step": 1.25, "controls": outputs,
            "native_inference": "Surface-MV improvement does not certify reflected-feature transport"}


def run():
    return {"schema": "glass-nzr-causal-probes-v1", "gpu_executed": False,
            "H1_reference_support": reference_support_probe(), "H2_selector_gain": selector_probe(),
            "H3_capped_count": {"kind": "exact stationary scalar AR(1) analytic covariance; unit input variance",
                                  "rows": [capped_history_variance(rho) for rho in (0.0, .5, .85, .95)]},
            "H4_virtual_transport": reflection_probe(),
            "source_subset_sha256": hashlib.sha256((CANDIDATE/"src/native_subset.py").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=CANDIDATE/"evidence/causal_probes.json")
    args = parser.parse_args()
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"output": args.out.name, "H1_rows": result["H1_reference_support"]["rows"],
                      "H3": result["H3_capped_count"]["rows"], "H4": result["H4_virtual_transport"]["controls"]}, indent=2))


if __name__ == "__main__":
    main()
