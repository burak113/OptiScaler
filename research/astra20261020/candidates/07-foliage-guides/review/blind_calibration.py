"""Independent pre-candidate calibration; CPU surrogate, NOT AMD RR output.

The normal-guided local estimator is intentionally small enough to audit. A
flat-normal intervention changes the admissible samples, leaving the input
radiance, sample count, exposure, and evaluation masks fixed. This proves the
scorer can reject noise reduction obtained through facade detail destruction.
It does not reproduce the magnitude of a historical native GPU experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


SEEDS = (17041, 31873, 60791)
FRAMES = 24
REVIEW_GATES = {
    "guide_and_signal_identity": "exact bytes, including all packed material bits and RGBA alpha",
    "diagnostic_identity": "candidate RGB equals original RGB, unsupported history does not claim support",
    "image_quality_if_claimed": {
        "detail_transfer_relative_to_exact_normal_control_min": 0.95,
        "flicker_ratio_max": 1.0,
        "sparkle_ratio_max": 1.0,
        "edge_error_ratio_max": 1.05,
    },
    "evidence": "no AMD RR, performance, or game improvement claim from a CPU surrogate",
    "mask_rule": "analytic truth / BASE only, fixed before interventions; fixed truth variance denominators",
}


def fixture():
    """Construct a static relief facade, window grid and raised FSR glyphs."""
    height, width = 48, 96
    yy, xx = np.mgrid[:height, :width]
    relief = np.zeros((height, width), dtype=bool)
    relief[:16] = ((xx[:16] // 2) % 2) == 0
    relief[16:32] = (xx[16:32] % 12 < 2) | (yy[16:32] % 8 < 2)
    glyphs = (
        ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
        ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
        ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    )
    for repeat in range(4):
        for gi, glyph in enumerate(glyphs):
            bitmap = np.array([[v == "1" for v in row] for row in glyph])
            x0 = repeat * 24 + gi * 7
            relief[35:42, x0 : x0 + 5] = bitmap
    truth = 0.18 + 0.55 * relief.astype(np.float64)
    # A small coplanar albedo texture shows that exact normal guidance itself is
    # a surrogate with limitations; the negative control is compared with it.
    truth += 0.012 * ((xx % 2) * 2 - 1)
    normal = np.zeros((height, width, 3), dtype=np.float64)
    angle = np.deg2rad(35.0)
    normal[..., 0] = np.where(relief, np.sin(angle), -np.sin(angle))
    normal[..., 2] = np.cos(angle)
    interior = (xx >= 3) & (xx < width - 3) & (yy >= 3) & (yy < height - 3)
    masks = {
        "all": interior,
        "facade": interior & (yy < 14),
        "windows": interior & (yy >= 18) & (yy < 30),
        "text": interior & (yy >= 34) & (yy < 44),
    }
    return truth, normal, masks


def guided_spatial(radiance, normal):
    """A 5x5 spatial normal-gated mean, explicit edge-clamped input reads."""
    radius = 2
    frames, height, width = radiance.shape
    padded = np.pad(radiance, ((0, 0), (radius, radius), (radius, radius)), mode="edge")
    pnormal = np.pad(normal, ((radius, radius), (radius, radius), (0, 0)), mode="edge")
    total = np.zeros_like(radiance, dtype=np.float64)
    denom = np.zeros((height, width), dtype=np.float64)
    for oy in range(2 * radius + 1):
        for ox in range(2 * radius + 1):
            neighbor_normal = pnormal[oy : oy + height, ox : ox + width]
            normal_d2 = np.sum((normal - neighbor_normal) ** 2, axis=-1)
            weight = np.exp(-normal_d2 / 0.04)
            total += padded[:, oy : oy + height, ox : ox + width] * weight
            denom += weight
    return total / denom


def highpass(field):
    p = np.pad(field, ((1, 1), (1, 1)), mode="edge")
    return field - 0.25 * (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:])


def metrics(output, truth, masks):
    mean = output.mean(axis=0)
    residual = output - truth
    true_detail = highpass(truth)
    out_detail = highpass(mean)
    values = {}
    for name, mask in masks.items():
        # Truth and mask are fixed; no candidate-derived threshold or divisor.
        denominator = float(np.sum(true_detail[mask] ** 2))
        values[name] = {
            "pixels": int(mask.sum()),
            "detail_denominator": denominator,
            "detail_transfer": float(np.sum(true_detail[mask] * out_detail[mask]) / denominator),
            "grain_rms": float(np.sqrt(np.mean((output - mean)[:, mask] ** 2))),
            "flicker_rms": float(np.sqrt(np.mean(np.diff(residual, axis=0)[:, mask] ** 2))),
            "sparkle_p995": float(np.quantile(np.abs((output - mean)[:, mask]), 0.995)),
            "edge_error": float(np.mean(np.abs(out_detail[mask] - true_detail[mask]))),
        }
    return values


def accept_image_claim(reference, proposed, ignore_detail=False):
    """Mandatory detail gate; ignore_detail is the explicit scorer mutant."""
    gates = REVIEW_GATES["image_quality_if_claimed"]
    rejected = []
    for region in reference:
        ref, val = reference[region], proposed[region]
        if not ignore_detail and val["detail_transfer"] < gates["detail_transfer_relative_to_exact_normal_control_min"] * ref["detail_transfer"]:
            rejected.append(region + ":detail")
        if val["flicker_rms"] > gates["flicker_ratio_max"] * ref["flicker_rms"]:
            rejected.append(region + ":flicker")
        if val["sparkle_p995"] > gates["sparkle_ratio_max"] * ref["sparkle_p995"]:
            rejected.append(region + ":sparkle")
        if not ignore_detail and val["edge_error"] > gates["edge_error_ratio_max"] * ref["edge_error"]:
            rejected.append(region + ":edge_error")
    return not rejected, rejected


def run():
    started = time.perf_counter()
    truth, normal, masks = fixture()
    flattened = np.broadcast_to(np.array([0.0, 0.0, 1.0]), normal.shape)
    results = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        noise = rng.normal(0.0, 0.09, (FRAMES,) + truth.shape)
        noise += 0.7 * ((rng.random(noise.shape) < 0.015).astype(np.float64) - 0.015)
        observed = truth[None] + noise
        exact = metrics(guided_spatial(observed, normal), truth, masks)
        flat = metrics(guided_spatial(observed, flattened), truth, masks)
        accepted, reasons = accept_image_claim(exact, flat)
        mutant_accepted, _ = accept_image_claim(exact, flat, ignore_detail=True)
        results.append({
            "seed": seed,
            "exact_normals": exact,
            "flat_normals": flat,
            "ratios": {
                name: {key: flat[name][key] / exact[name][key] for key in
                    ("detail_transfer", "grain_rms", "flicker_rms", "sparkle_p995", "edge_error")}
                for name in masks
            },
            "flat_accepted": accepted,
            "rejection_reasons": reasons,
            "noise_only_scorer_mutant_accepted": mutant_accepted,
        })
    return {
        "executor": "independent skeptical reviewer /root/skeptic",
        "stage": "independent blind CPU surrogate calibration, before candidate inspection",
        "gpu_executed": False,
        "historical_reference": {
            "path": "research/astra20261020/FINDINGS.md",
            "claim": "NormalEMA .25 lost 22-27% facade detail in a historical local native study",
            "reexecuted": False,
            "reason": "No AMD RR runtime or full historical variant replay is provided in the CPU package",
        },
        "seeds": list(SEEDS), "frames": FRAMES,
        "truth_sha256": hashlib.sha256(truth.tobytes()).hexdigest(),
        "mask_sha256": {k: hashlib.sha256(v.tobytes()).hexdigest() for k, v in masks.items()},
        "review_gates": REVIEW_GATES,
        "cases": results,
        "all_negative_controls_rejected": all(not r["flat_accepted"] for r in results),
        "all_noise_only_mutants_incorrectly_accept": all(r["noise_only_scorer_mutant_accepted"] for r in results),
        "elapsed_seconds": time.perf_counter() - started,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("blind_calibration.json"))
    parser.add_argument("--mutant-ignore-detail", action="store_true", help="Expected failure: weaken acceptance to noise only")
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if args.mutant_ignore_detail:
        # A correctness test must reject the known destructive intervention.
        assert not any(r["noise_only_scorer_mutant_accepted"] for r in result["cases"]), "MUTANT CAUGHT: noise-only scoring accepts destroyed facade detail"
    assert result["all_negative_controls_rejected"]
    assert result["all_noise_only_mutants_incorrectly_accept"]
    print(json.dumps({"negative_controls_rejected": True, "noise_only_mutant_falsified": True,
                      "all_region_ratios": [r["ratios"]["all"] for r in result["cases"]]}, indent=2))


if __name__ == "__main__":
    main()
