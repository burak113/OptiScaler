"""Audit paired-case membership and uncertainty without rerunning candidates.

Consumes completed evidence. It never changes candidate constants, protocols,
raw experiment receipts or masks. The exact missing-case inventory is material
to interpreting an apparently clean matched-dose subset.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from experiment import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.input.resolve(), args.output.resolve()
    if output == source or source in output.parents:
        parser.error("postprocessing goes in a separate directory, preserving raw evidence")
    output.mkdir(parents=True, exist_ok=True)
    boundary = json.loads((source / "boundary_holdout.json").read_text(encoding="utf-8"))
    noise = json.loads((source / "noise_holdout.json").read_text(encoding="utf-8"))
    methods = tuple(boundary["summary"])
    paired = []
    missing_inventory = {}
    for name in methods:
        missing = [r for r in boundary["cases"] if r["methods"][name]["matched0.8"] is None]
        groups = sorted({(r["lobe"], r["gap_parameter"]) for r in missing})
        missing_inventory[name] = []
        for lobe, gap in groups:
            rows = [r for r in missing if r["lobe"] == lobe and r["gap_parameter"] == gap]
            receipts = [r["methods"][name]["matching"] for r in rows]
            missing_inventory[name].append({
                "lobe": lobe, "gap": gap, "cases": len(rows),
                "angles": sorted({r["angle"] for r in rows}),
                "phases": sorted({r["phase"] for r in rows}),
                "reasons": dict(Counter(r["reason"] for r in receipts)),
                "full_dose_range": [min(r["full_dose"] for r in receipts), max(r["full_dose"] for r in receipts)],
                "achieved_match_search_range": [min(r["achieved"] for r in receipts if "achieved" in r),
                                               max(r["achieved"] for r in receipts if "achieved" in r)]
                                               if any("achieved" in r for r in receipts) else None,
                "full_output_boundary_failures": sum(r["methods"][name]["full"]["max_contamination_above_storage_envelope"] > 0 for r in rows),
            })
        common = [r for r in boundary["cases"]
                  if r["methods"][name]["matched0.8"] is not None
                  and r["methods"]["original_log"]["matched0.8"] is not None]
        paired.append({
            "variant": name, "paired_case_count": len(common), "unpaired_cases": len(boundary["cases"])-len(common),
            "original_failures_on_same_cases": sum(r["methods"]["original_log"]["matched0.8"]["max_contamination_above_storage_envelope"] > 0 for r in common),
            "variant_failures_on_same_cases": sum(r["methods"][name]["matched0.8"]["max_contamination_above_storage_envelope"] > 0 for r in common),
            "paired_cases": [{k:r[k] for k in ("lobe", "gap_parameter", "angle", "phase")} for r in common],
        })
    caveats = []
    for row in noise["paired_matched_dose_summary"]:
        if len(row["paired_seeds"]) < 3:
            caveats.append({k:row[k] for k in ("lobe", "family", "variant", "target_dose", "paired_seeds", "unmatched_seed_count")})
    report = {
        "scope": "Postprocessing of completed immutable evidence, no candidate rerun or tuning.",
        "source_sha256": sha256(__file__),
        "input_sha256": {name: sha256(source / name) for name in ("boundary_holdout.json", "noise_holdout.json")},
        "boundary_missing_inventory": missing_inventory,
        "boundary_paired_intersections_against_original": paired,
        "interpretation": "Narrow RR support's 0/96 matched leaks omit all48 low-gap failures. The same paired original cases leak96/96. Neither fact removes narrow support's48 full-output failures.",
        "matching_language": "The original receipt reason quantized_target_unreachable means the specified scalar matching search did not attain the tolerance. It is not a global mathematical impossibility claim. A failed match is excluded from equal-dose claims and remains in full-output quality gates.",
        "insufficient_pairs_for_useful_interval": caveats,
        "uncertainty_caveat": "A one-seed bootstrap is a degenerate resampling of that single observation, not an inferential confidence interval. Two-seed intervals are also too weak for a general superiority claim. All such strata are listed explicitly here; no candidate is promoted.",
    }
    target = output / "paired_audit.json"
    target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "sha256": sha256(target), "candidate_rerun": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
