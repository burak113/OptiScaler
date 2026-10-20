"""Small post-review counterexample search; never a replacement acceptance set."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from independent_checks import (HERE, CANDIDATE, at_luma, edge_scene, edge_metrics,
                                luma, local_half_envelope, original_eligibility)
from run_review import all_outputs, models


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def opponent_gap(left, right):
    # Independent analytic measurement of the raw guide jump. The candidate
    # uses a dimensionless epsilon; this positive palette is far from zero.
    a = np.log(left[[0, 2]] / left[1])
    b = np.log(right[[0, 2]] / right[1])
    return float(np.linalg.norm(a - b))


def main():
    started = time.perf_counter()
    protocol = json.loads((HERE / "low_contrast_probe_protocol.json").read_text())
    original_receipt_hash = sha256(HERE / "review_result.json")
    source_hash = sha256(CANDIDATE / "native_colour.py")
    rows, samples = [], {}
    for lobe, level in protocol["lobe_levels"].items():
        a = at_luma(protocol["raw_left_relative_RGB"], level)
        b = at_luma(protocol["raw_right_relative_RGB"], level)
        target_a = at_luma(protocol["target_left_relative_RGB"], level)
        for angle in protocol["angles_degrees"]:
            for phase in protocol["phases_pixels"]:
                scene, meta = edge_scene("red_blue", "same_guides", phase, angle, level)
                source, raw, selected, depth, normals, roughness, authority = scene
                left = meta["left"]
                raw[..., :3] = np.where(left[..., None], a, b).astype(np.float16)
                selected[..., :3] = raw[..., :3]
                source[..., :3] = np.where(left[..., None], target_a, b).astype(np.float16)
                meta["truth"] = np.where(left[..., None], target_a, b)
                meta["base_denominator"] = luma(raw)
                meta["half_envelope"] = local_half_envelope(raw)
                meta["eligible"] = original_eligibility(raw, selected, authority)
                outputs, _ = all_outputs(models(), scene)
                rows.append({"lobe": lobe, "phase": phase, "angle_degrees": angle,
                             "raw_opponent_gap_without_epsilon": opponent_gap(a, b),
                             "methods": {n: edge_metrics(v, scene, meta) for n, v in outputs.items()}})
                if lobe == "diffuse" and angle == 27 and phase == 4:
                    for name, value in outputs.items():
                        samples[name] = value
                    samples["truth"] = meta["truth"].astype(np.float32)
                    samples["unchanged_band"] = meta["band"]
    summary = {}
    for method in ("raw", "B4", "soft2", "log", "linear"):
        worst = max(rows, key=lambda r: r["methods"][method]["unchanged_side_max_contamination"])
        summary[method] = {
            "max_unchanged_right_contamination": worst["methods"][method]["unchanged_side_max_contamination"],
            "max_above_original_storage_envelope": max(r["methods"][method]["max_contamination_above_storage_envelope"] for r in rows),
            "cases_with_contamination_above_original_storage_envelope": sum(r["methods"][method]["max_contamination_above_storage_envelope"] > 0 for r in rows),
            "worst_case": {k: v for k, v in worst.items() if k != "methods"},
        }
    np.savez_compressed(HERE / "low_contrast_arrays.npz", **samples)
    report = {
        "executor": "independent_skeptical_reviewer",
        "scope": protocol["scope"],
        "command": "python -B research/astra20261020/candidates/03-native-colour/review/low_contrast_probe.py",
        "source_sha256": source_hash,
        "original_review_result_sha256_unchanged": original_receipt_hash,
        "protocol_sha256": sha256(HERE / "low_contrast_probe_protocol.json"),
        "gpu_executed": False,
        "case_count": len(rows),
        "summary": summary,
        "counterexample_found": summary["log"]["cases_with_contamination_above_original_storage_envelope"] > 0,
        "interpretation": "Zero leakage in the original high-contrast set is not universal boundary safety. Compact support can mix distinct low-contrast colours that lie inside its radius.",
        "cases": rows,
        "elapsed_seconds": time.perf_counter() - started,
        "representative_arrays_sha256": sha256(HERE / "low_contrast_arrays.npz"),
    }
    assert sha256(HERE / "review_result.json") == original_receipt_hash
    assert sha256(CANDIDATE / "native_colour.py") == source_hash
    (HERE / "low_contrast_results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
