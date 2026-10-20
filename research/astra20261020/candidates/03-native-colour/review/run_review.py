"""Frozen, independent native-colour falsification suite.

Run from any cwd. This records failures honestly and returns one with
--quality-gate when the primary candidate fails a frozen quality condition.
Ordinary execution returns zero when measurement execution itself succeeded.
The latter is not an image-quality acceptance result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from independent_checks import (
    HERE, CANDIDATE, PACKAGE, LUMA, assert_word_contract, at_luma,
    basic_scene, call_model, chroma, edge_metrics, edge_scene, luma,
    normal_oct, original_eligibility, rgba, unchanged, words,
)
import colour_portable as cp
from native_colour import Config, NativeColourModel


SEEDS = (104729, 130363, 155921)
METHODS = ("raw", "B4", "soft2", "log", "linear")
LOBE_LEVELS = {"diffuse": .3, "specular": .045}
REPRESENTATIVES = {}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def models():
    return {"B4": cp.baseline_model(), "soft2": cp.rejected_soft2_model(),
            "log": NativeColourModel(Config(enabled=True, representation="log")),
            "linear": NativeColourModel(Config(enabled=True, representation="linear"))}


def all_outputs(instances, scene, frame_id=0):
    source, raw, selected, depth, normals, roughness, authority = scene
    eligible = original_eligibility(raw, selected, authority)
    output = {"raw": selected.copy()}
    diagnostics = {}
    for name in ("B4", "soft2"):
        # These are frozen RGB models, wrapped only for a fair per-lobe CPU
        # comparison. This wrapper is not existing native production integration.
        rgb, data = instances[name].frame(
            source[..., :3].astype(np.float32), raw[..., :3].astype(np.float32),
            depth, normal_oct(normals), np.zeros(depth.shape + (4,), np.float32))
        if name == "soft2":
            rgb = cp.rejected_soft2_apply(raw[..., :3].astype(np.float32),
                                           depth, normal_oct(normals), data)
        wrapped = selected.copy()
        wrapped[eligible, :3] = rgb[eligible].astype(selected.dtype)
        assert_word_contract(wrapped, raw, selected, authority)
        output[name] = wrapped
    for name in ("log", "linear"):
        value, diag = call_model(instances[name], scene, frame_id=frame_id)
        assert_word_contract(value, raw, selected, authority)
        output[name], diagnostics[name] = value, diag
    return output, diagnostics


def benchmark_boundaries():
    rows, thin_rows, moving_rows = [], [], []
    for lobe, level in LOBE_LEVELS.items():
        for pair in ("red_blue", "green_magenta"):
            for kind in ("normal", "depth", "roughness", "same_guides"):
                for angle in (0, 27, 45, 73, 90):
                    for phase in range(8):
                        scene, meta = edge_scene(pair, kind, phase, angle, level)
                        outputs, _ = all_outputs(models(), scene)
                        rows.append({"lobe": lobe, "pair": pair, "guide": kind,
                                     "angle_degrees": angle, "phase": phase,
                                     "methods": {n: edge_metrics(v, scene, meta)
                                                 for n, v in outputs.items()}})
                        if lobe == "diffuse" and pair == "red_blue" and kind == "normal" and angle == 27 and phase == 4:
                            for name, value in outputs.items():
                                REPRESENTATIVES["boundary_" + name] = value
                            REPRESENTATIVES["boundary_truth"] = meta["truth"].astype(np.float32)
    for lobe, level in LOBE_LEVELS.items():
        for width in (1, 2, 3):
            for phase in range(8):
                for angle in (0, 27, 73):
                    scene, meta = edge_scene("green_magenta", "normal", phase,
                                             angle, level, thin_width=width)
                    outputs, _ = all_outputs(models(), scene)
                    thin_rows.append({"lobe": lobe, "width_pixels": width,
                                      "angle_degrees": angle, "phase": phase,
                                      "methods": {n: edge_metrics(v, scene, meta)
                                                  for n, v in outputs.items()}})
    for lobe, level in LOBE_LEVELS.items():
        for pair in ("red_blue", "green_magenta"):
            for kind in ("normal", "depth", "roughness", "same_guides"):
                instances = models()
                # Eight chronological frames, one subcell phase per frame. The
                # zero-motion CP control deliberately witnesses a disocclusion;
                # candidate has no history and cannot claim motion handling.
                for frame in range(8):
                    scene, meta = edge_scene(pair, kind, 0, 27, level, movement=frame)
                    outputs, _ = all_outputs(instances, scene, frame_id=frame)
                    moving_rows.append({"lobe": lobe, "pair": pair, "guide": kind,
                                        "angle_degrees": 27, "frame": frame,
                                        "methods": {n: edge_metrics(v, scene, meta)
                                                    for n, v in outputs.items()}})
    return {"static": rows, "thin": thin_rows, "moving": moving_rows}


def make_sequence(seed, family, lobe, frames=24, h=32, w=48):
    level = LOBE_LEVELS[lobe]
    yy, xx = np.indices((h, w))
    # Known high-frequency colour detail, with exactly zero luminance component.
    stripe = np.sin(2 * np.pi * xx / 6) + .4 * np.sin(2 * np.pi * yy / 9)
    colour = np.zeros((h, w, 3), np.float64) + np.array([.85, 1, .9])
    colour[..., 0] += .06 * stripe
    colour[..., 1] -= .06 * stripe * LUMA[0] / LUMA[1]
    truth = at_luma(colour, level)
    bias = np.exp([.12, -.08, .08])
    raw_base = at_luma(truth * bias, level)
    rng_source = np.random.default_rng(seed + (0 if lobe == "diffuse" else 1000003))
    rng_rr = np.random.default_rng(seed + 8000009 + (0 if lobe == "diffuse" else 1000003))
    states = np.zeros((h, w, 3), np.float64)
    scenes, truths, source_expectations = [], [], []
    protection = ((xx + 3 * yy) % 19) == 0
    authority = ((2 * xx + yy) % 31) != 0
    normals = np.zeros((h, w, 3), np.float32)
    normals[..., 2] = 1
    for frame in range(frames):
        if family == "independent":
            # E[exp(sigma*N-.5*sigma^2)]=1 in analytic real arithmetic.
            sigma = .22
            multiplier = np.exp(sigma * rng_source.normal(size=truth.shape) - .5 * sigma * sigma)
        elif family == "outliers":
            # A positive two-component distribution with E[multiplier]=1.
            p, high = .012, 14.0
            low = (1 - p * high) / (1 - p)
            multiplier = np.where(rng_source.random(truth.shape) < p, high, low)
        elif family == "temporal_AR":
            rho, sigma = .85, .3
            states = rho * states + np.sqrt(1 - rho * rho) * rng_source.normal(size=truth.shape)
            # Account for finite startup variance; this is not looped warmup.
            variance = 1 - rho ** (2 * (frame + 1))
            multiplier = np.exp(sigma * states - .5 * sigma * sigma * variance)
        elif family == "sparse":
            # Achromatic dropout followed by independent chromatic variation.
            keep, sigma = .16, .35
            visible = rng_source.random((h, w, 1)) < keep
            multiplier = visible / keep * np.exp(sigma * rng_source.normal(size=truth.shape) - .5 * sigma * sigma)
        else:
            raise ValueError(family)
        source = rgba(truth * multiplier, alpha=0 if lobe == "diffuse" else 2.5)
        # Independent raw-RR residual and persistent low-frequency chroma bias.
        rr_noise = np.exp(.006 * rng_rr.normal(size=truth.shape) - .5 * .006 ** 2)
        raw = rgba(at_luma(raw_base * rr_noise, level), alpha=0 if lobe == "diffuse" else 2.5)
        selected = raw.copy()
        selected[protection, :3] = truth[protection].astype(np.float16)
        # Guarantee all intended protected pixels differ even if quantization
        # accidentally erases a correction in one channel.
        words(selected)[protection, 3] ^= np.uint16(1)
        scene = (source, raw, selected, np.full((h, w), 10, np.float32),
                 normals.copy(), np.full((h, w), .3, np.float32), authority.copy())
        scenes.append(scene)
        truths.append(truth.copy())
        source_expectations.append(truth.copy())
    truth_stack = np.stack(truths)
    den = np.stack([luma(s[1]) for s in scenes]).mean(0)
    eligible = np.logical_and.reduce([original_eligibility(s[1], s[2], s[-1]) for s in scenes])
    border = (xx >= 4) & (xx < w - 4) & (yy >= 4) & (yy < h - 4)
    mask = eligible & border
    return scenes, truth_stack, mask, den


def gaussian_spatial(value, sigma=1.5):
    return np.moveaxis(cp.gaussian(np.moveaxis(value, -1, 0), sigma), 0, -1).astype(np.float64)


def stack_metrics(stack, truth, mask, den):
    stack = np.asarray(stack, np.float64)[..., :3]
    residual = chroma(stack) - chroma(truth)
    normalized = residual / den[None, ..., None]
    hf = np.stack([r - gaussian_spatial(r) for r in residual]) / den[None, ..., None]
    hf_temporal = np.sqrt(np.var(hf, axis=0).sum(-1))
    temporal_diff = np.sqrt(np.mean(np.diff(hf, axis=0) ** 2, axis=0).sum(-1))
    amplitude = np.linalg.norm(normalized, axis=-1)
    grain = np.linalg.norm(hf, axis=-1)
    lf_vector = normalized[:, mask].mean(axis=(0, 1))
    detail = chroma(truth[0])
    detail -= detail[mask].mean(0)
    observed = chroma(stack.mean(0))
    observed -= observed[mask].mean(0)
    denom_detail = float(np.sum(detail[mask] ** 2))
    return {
        "chroma_RMSE": float(np.sqrt(np.mean(normalized[:, mask] ** 2))),
        "chroma_error_p99": float(np.percentile(amplitude[:, mask], 99)),
        "sparkle_error_p999": float(np.percentile(amplitude[:, mask], 99.9)),
        "grain_HF_p90": float(np.percentile(grain[:, mask], 90)),
        "chroma_HF_temporal_p50": float(np.median(hf_temporal[mask])),
        "chroma_HF_temporal_p90": float(np.percentile(hf_temporal[mask], 90)),
        "chroma_HF_temporal_p99": float(np.percentile(hf_temporal[mask], 99)),
        "chroma_HF_temporal_difference_p90": float(np.percentile(temporal_diff[mask], 90)),
        "low_band_chroma_bias_norm": float(np.linalg.norm(lf_vector)),
        "truth_detail_projection_ratio": float(np.sum(observed[mask] * detail[mask]) / denom_detail),
        "luma_relative_error_max": float((np.abs(luma(stack) - luma(truth)) / den[None])[..., mask].max()),
        "immutable_mask_pixels": int(mask.sum()),
    }


def benchmark_temporal():
    rows = []
    for seed in SEEDS:
        for lobe in LOBE_LEVELS:
            for family in ("independent", "outliers", "temporal_AR", "sparse"):
                scenes, truth, mask, den = make_sequence(seed, family, lobe)
                instances = models()
                stacks = {name: [] for name in METHODS}
                support = {name: [] for name in ("log", "linear")}
                protected_count = 0
                for frame, scene in enumerate(scenes):
                    outputs, diagnostics = all_outputs(instances, scene, frame_id=frame)
                    for name, output in outputs.items():
                        stacks[name].append(output)
                    for name, diag in diagnostics.items():
                        support[name].append({
                            "confidence_mean": float(diag["confidence"][mask].mean()),
                            "effective_samples_mean": float(diag["effective_samples"][mask].mean()),
                            "eligible_fraction": float(diag["eligible"].mean()),
                            "supported_fraction": float(diag["supported"].mean()),
                            "changed_fraction": float(diag["changed"].mean()),
                        })
                    protected_count += int((~original_eligibility(scene[1], scene[2], scene[-1])).sum())
                results = {n: stack_metrics(v, truth, mask, den) for n, v in stacks.items()}
                raw_lf = results["raw"]["low_band_chroma_bias_norm"]
                for result in results.values():
                    result["low_band_bias_correction_fraction"] = 1 - result["low_band_chroma_bias_norm"] / raw_lf
                    result["temporal_p90_over_B4"] = result["chroma_HF_temporal_p90"] / results["B4"]["chroma_HF_temporal_p90"]
                rows.append({
                    "seed": seed, "lobe": lobe, "noise_family": family,
                    "frames": [0, len(scenes) - 1], "frame_count": len(scenes),
                    "shape_height_width": list(mask.shape), "chronology": "one unlooped pass; fresh model state",
                    "source_distribution_expected_RGB": "analytic truth BEFORE generated RNE half storage",
                    "truth_scope": "synthetic analytic expectation, not game/capture truth",
                    "mask_sha256": hashlib.sha256(mask.tobytes()).hexdigest(),
                    "denominator_sha256": hashlib.sha256(den.tobytes()).hexdigest(),
                    "source_sha256": hashlib.sha256(b"".join(s[0].tobytes() for s in scenes)).hexdigest(),
                    "raw_sha256": hashlib.sha256(b"".join(s[1].tobytes() for s in scenes)).hexdigest(),
                    "protected_pixel_frames_checked": protected_count,
                    "protected_word_changes": 0, "alpha_word_changes": 0,
                    "methods": results, "candidate_support": support,
                })
                if seed == SEEDS[0] and lobe == "diffuse" and family in ("independent", "outliers", "sparse"):
                    for name in METHODS:
                        REPRESENTATIVES[family + "_" + name] = np.stack(stacks[name])
                    REPRESENTATIVES[family + "_truth"] = truth.astype(np.float32)
                    REPRESENTATIVES[family + "_source"] = np.stack([s[0] for s in scenes])
                    REPRESENTATIVES[family + "_mask"] = mask
                    REPRESENTATIVES[family + "_denominator"] = den.astype(np.float32)
    return rows


def benchmark_closure_and_response():
    closure = []
    responses = []
    for lobe, level in LOBE_LEVELS.items():
        h, w = 32, 48
        yy, xx = np.indices((h, w))
        wave = np.where(xx % 2 == 0, 1, -1).astype(np.float64)
        rgb = np.zeros((h, w, 3), np.float64) + level
        rgb[..., 0] += level * .15 * wave
        rgb[..., 1] -= level * .15 * wave * LUMA[0] / LUMA[1]
        # Include level detail as well as equal-Y chroma detail.
        rgb *= (1 + .1 * np.sin(2 * np.pi * yy / 4))[..., None]
        source = raw = rgba(rgb)
        normals = np.zeros((h, w, 3), np.float32)
        normals[..., 2] = 1
        scene = (source, raw, raw.copy(), np.full((h, w), 10, np.float32),
                 normals, np.full((h, w), .3, np.float32), np.ones((h, w), bool))
        outputs, _ = all_outputs(models(), scene)
        baseline_chroma_contrast = float(np.mean(chroma(raw)[:, ::2, 0] - chroma(raw)[:, 1::2, 0]))
        baseline_luma_contrast = float(luma(raw).max() - luma(raw).min())
        for name, output in outputs.items():
            cc = float(np.mean(chroma(output)[:, ::2, 0] - chroma(output)[:, 1::2, 0]))
            yc = float(luma(output).max() - luma(output).min())
            closure.append({"lobe": lobe, "method": name,
                            "chroma_detail_contrast_ratio": cc / baseline_chroma_contrast,
                            "luma_detail_contrast_ratio": yc / baseline_luma_contrast,
                            "RGBA_identical": unchanged(output, raw)})
        for change in ("step", "flash"):
            instances = models()
            stacks = {n: [] for n in METHODS}
            # Raw RR deliberately retains the prior colour. The source undergoes
            # a moderate genuine step or one-frame flash at frame8. This isolates
            # response from arbitrary noise or RR temporal quality assumptions.
            old = at_luma([.85, 1, .9], level)
            new = at_luma(old * np.exp([.10, -.05, .07]), level)
            raw = rgba(np.broadcast_to(old, (h, w, 3)))
            truth = []
            for frame in range(18):
                changed = frame >= 8 if change == "step" else frame == 8
                now = new if changed else old
                source = rgba(np.broadcast_to(now, (h, w, 3)))
                scene = (source, raw, raw.copy(), np.full((h, w), 10, np.float32),
                         normals, np.full((h, w), .3, np.float32), np.ones((h, w), bool))
                outputs, _ = all_outputs(instances, scene, frame)
                for name in METHODS:
                    stacks[name].append(outputs[name])
                truth.append(now)
            direction = chroma(new) - chroma(old)
            direction_energy = float(np.dot(direction, direction))
            response = {}
            for name, stack in stacks.items():
                mean = chroma(np.stack(stack)[:, 4:-4, 4:-4, :3]).mean(axis=(1, 2))
                fraction = (mean - chroma(old)) @ direction / direction_energy
                response[name] = {
                    "response_fraction_by_frame": [float(x) for x in fraction],
                    "response_fraction_at_change": float(fraction[8]),
                    "response_fraction_within_4_frames": float(fraction[8:12].max()),
                    "post_flash_residual_fraction_max": float(np.abs(fraction[9:]).max()) if change == "flash" else None,
                }
            responses.append({"lobe": lobe, "change": change, "change_frame": 8,
                              "frames": [0, 17], "methods": response,
                              "gate": "step >=0.90 response fraction within frames8..11"})
    return {"closure": closure, "response": responses}


def summarize(boundaries, temporal, dynamics):
    summary = {"quality_pass": True, "failed_gates": [], "boundary": {}, "temporal": {}}
    for section, rows in boundaries.items():
        by_method = {}
        for method in METHODS:
            available = [(r, r["methods"][method]) for r in rows
                         if r["methods"][method]["unchanged_side_max_contamination"] is not None]
            worst = max(available, key=lambda pair: pair[1]["unchanged_side_max_contamination"])
            correction = [r["methods"][method]["interior_correction_fraction"] for r in rows
                          if r["methods"][method]["interior_correction_fraction"] is not None]
            by_method[method] = {
                "case_count": len(rows),
                "worst_contamination": worst[1]["unchanged_side_max_contamination"],
                "worst_case": {k: v for k, v in worst[0].items() if k != "methods"},
                "max_above_storage_envelope": max(v["max_contamination_above_storage_envelope"] for _, v in available),
                "interior_correction_fraction_median": float(np.median(correction)) if correction else None,
                "interior_correction_fraction_min": float(min(correction)) if correction else None,
            }
        summary["boundary"][section] = by_method
        if by_method["log"]["max_above_storage_envelope"] > 0:
            summary["failed_gates"].append("primary_log_" + section + "_boundary_contamination")
    if any(r["method"] == "log" and min(r["chroma_detail_contrast_ratio"], r["luma_detail_contrast_ratio"]) < .95
           for r in dynamics["closure"]):
        summary["failed_gates"].append("primary_log_constant_closure_detail_below_0.95")
    for row in dynamics["response"]:
        if row["change"] == "step" and row["methods"]["log"]["response_fraction_within_4_frames"] < .90:
            summary["failed_gates"].append("primary_log_" + row["lobe"] + "_true_step_response_below_0.90")
    for method in METHODS:
        summary["temporal"][method] = {
            "sequence_count": len(temporal),
            "median_temporal_p90_over_B4": float(np.median([r["methods"][method]["temporal_p90_over_B4"] for r in temporal])),
            "worst_temporal_p90_over_B4": float(max(r["methods"][method]["temporal_p90_over_B4"] for r in temporal)),
            "median_low_band_bias_correction_fraction": float(np.median([r["methods"][method]["low_band_bias_correction_fraction"] for r in temporal])),
            "worst_chroma_RMSE": float(max(r["methods"][method]["chroma_RMSE"] for r in temporal)),
            "worst_sparkle_error_p999": float(max(r["methods"][method]["sparkle_error_p999"] for r in temporal)),
        }
    # Noise/strength metrics remain separate. No weighted average or changed
    # threshold can turn a failed frozen gate into an accepted production result.
    if summary["boundary"]["static"]["log"]["interior_correction_fraction_median"] <= 0:
        summary["failed_gates"].append("primary_log_identity_without_correction")
    summary["quality_pass"] = len(summary["failed_gates"]) == 0
    summary["recommendation"] = "keep_as_research"  # No GPU/native/game acceptance exists.
    return summary


def render_panels(dynamics):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {"rendered": False, "reason": "matplotlib unavailable; arrays supplied"}
    for prefix, label in (("boundary", "27-degree normal boundary, phase4"),
                          ("outliers", "heldout chromatic outliers, frame23"),
                          ("sparse", "heldout sparse source, frame23")):
        names = ["truth", "raw", "B4", "soft2", "log", "linear"]
        fig, axes = plt.subplots(2, 3, figsize=(12, 5), constrained_layout=True)
        for ax, name in zip(axes.ravel(), names):
            rgb = REPRESENTATIVES[prefix + "_" + name]
            if rgb.ndim == 4:
                rgb = rgb[-1]
            # Identical linear exposure and display gamma for every panel.
            view = np.clip(rgb[..., :3].astype(np.float32) / 1.0, 0, 1) ** (1 / 2.2)
            ax.imshow(view, interpolation="nearest")
            ax.set_title(name)
            ax.axis("off")
        fig.suptitle(label + " | common exposure1.0, gamma2.2, original aspect")
        fig.savefig(HERE / (prefix + "_panels.png"), dpi=140)
        plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for ax, change in zip(axes, ("step", "flash")):
        row = next(r for r in dynamics["response"] if r["lobe"] == "diffuse" and r["change"] == change)
        for name in METHODS:
            ax.plot(row["methods"][name]["response_fraction_by_frame"], label=name)
        target = [float(i >= 8 if change == "step" else i == 8) for i in range(18)]
        ax.plot(target, "k--", label="analytic truth")
        ax.axhline(.9, color="grey", linewidth=.7)
        ax.set_title("Diffuse true-colour " + change)
        ax.set_xlabel("Chronological synthetic frame")
        ax.set_ylabel("Response fraction")
    axes[-1].legend(fontsize=8)
    fig.savefig(HERE / "true_change_response.png", dpi=140)
    plt.close(fig)
    return {"rendered": True, "matplotlib": matplotlib.__version__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-gate", action="store_true")
    parser.add_argument("--section", choices=("all", "boundaries", "temporal", "dynamics"), default="all")
    args = parser.parse_args()
    if not json.loads((HERE / "known_bad_receipt.json").read_text())["known_bad_reproduced"]:
        raise RuntimeError("Reviewer must reproduce known-bad control before candidate")
    started = time.perf_counter()
    boundaries = benchmark_boundaries() if args.section in ("all", "boundaries") else None
    if boundaries is not None:
        (HERE / "boundary_results.json").write_text(json.dumps(boundaries, indent=2, allow_nan=False) + "\n")
        print("Boundary measurements complete", flush=True)
    temporal = benchmark_temporal() if args.section in ("all", "temporal") else None
    if temporal is not None:
        (HERE / "temporal_results.json").write_text(json.dumps(temporal, indent=2, allow_nan=False) + "\n")
        print("Temporal measurements complete", flush=True)
    dynamics = benchmark_closure_and_response() if args.section in ("all", "dynamics") else None
    if dynamics is not None:
        (HERE / "dynamics_results.json").write_text(json.dumps(dynamics, indent=2, allow_nan=False) + "\n")
        print("Closure and true-change measurements complete", flush=True)
    if args.section != "all":
        print(json.dumps({"section": args.section, "elapsed_seconds": time.perf_counter() - started}))
        return 0
    summary = summarize(boundaries, temporal, dynamics)
    rendering = render_panels(dynamics)
    np.savez_compressed(HERE / "representative_arrays.npz", **REPRESENTATIVES)
    report = {
        "executor": "independent_skeptical_reviewer",
        "scope": "heldout synthetic CPU truth tests; no game truth, GPU execution, or native bridge execution",
        "gpu_executed": False,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__},
        "command": "python -B research/astra20261020/candidates/03-native-colour/review/run_review.py --quality-gate",
        "source_sha256": sha256(CANDIDATE / "native_colour.py"),
        "frozen_protocol_sha256": sha256(HERE / "frozen_protocol.json"),
        "holdout_seeds": list(SEEDS),
        "input_precision": "generated positive analytic RGB, RNE float16 input store; original words preserved thereafter",
        "control_scope": "B4/soft2 frozen RGB CPU references applied per lobe behind identical original-word selection/authority gate; this is not production native integration",
        "temporal_history": "candidate stateless; B4/soft2 fresh initial CPU histories, one unlooped sequence",
        "correction_strength_caveat": "default controls have different achieved correction; all low-band correction fractions reported separately, no claim of equal-strength dominance",
        "summary": summary,
        "rendering": rendering,
        "elapsed_seconds": time.perf_counter() - started,
        "quality_gate_exit_code": 0 if summary["quality_pass"] else 1,
        "hashes": {name: sha256(HERE / name) for name in (
            "boundary_results.json", "temporal_results.json", "dynamics_results.json", "representative_arrays.npz")},
    }
    (HERE / "review_result.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return report["quality_gate_exit_code"] if args.quality_gate else 0


if __name__ == "__main__":
    raise SystemExit(main())
