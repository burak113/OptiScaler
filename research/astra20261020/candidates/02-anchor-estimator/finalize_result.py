"""Build the machine-readable return and delivery hashes from executed evidence.

This does not execute experiments or modify their results. --source-commit may
be supplied only after the code/evidence revision actually exists in Git; the
later metadata-only delivery commit can then identify that source revision
without a circular self-commit claim.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
REPO = HERE.parents[3]
BASE = "5d7839a930106cf8fe1ba8dbbc6750509e7f26a8"
ALLOWED = {".py", ".json", ".md", ".txt", ".hlsl", ".png", ".npz"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name):
    return json.loads((HERE / name).read_text())


def files():
    return sorted(p for p in HERE.rglob("*") if p.is_file() and p.suffix in ALLOWED and
                  "__pycache__" not in p.parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", help="existing code/evidence commit, before metadata-only delivery commit")
    args = parser.parse_args()
    if args.source_commit and not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise SystemExit("source commit must be an actual full Git SHA")
    for name in ("REPORT.md", "GPU_REQUEST.json", "BLOCKED_DATA_REQUEST.json", "evidence/visual_qa.json"):
        if not (HERE / name).exists():
            raise SystemExit("missing required deliverable: " + name)
    ledger, original = load("evidence/run_ledger.json"), load("evidence/baseline/runs.json")
    assert ledger["success"] and all(r["exit_code"] == 0 for r in ledger["runs"])
    freeze = load("evidence/FROZEN_SOURCE.json")
    assert all(sha(HERE / p) == v for p, v in freeze["files"].items())
    synthetic, captured = load("evidence/synthetic_results.json"), load("evidence/captured_results.json")
    sources = {p.relative_to(HERE).as_posix(): sha(p) for p in files() if p.suffix in (".py", ".hlsl")}
    framed = "".join(f"{name}\0{value}\n" for name, value in sorted(sources.items()))
    source_fingerprint = hashlib.sha256(framed.encode()).hexdigest()
    fixture_hashes = {}
    for directory in ("portable/anchor/fixtures", "portable/colour/fixtures", "fixtures/clips", "fixtures/glass"):
        for path in sorted((PACKAGE / directory).glob("**/*.npz")):
            fixture_hashes[path.relative_to(PACKAGE).as_posix()] = sha(path)
    results = {}
    for path in files():
        name = path.relative_to(HERE).as_posix()
        if name in ("RESULT.json", "SHA256SUMS.json"):
            continue
        if path.suffix in (".png", ".npz") or name.endswith("results.json") or name in (
                "REPORT.md", "evidence/run_ledger.json", "reviewer/holdout_reproduction.json", "reviewer/REVIEW.md",
                "GPU_REQUEST.json", "BLOCKED_DATA_REQUEST.json"):
            results[name] = sha(path)
    calibration = synthetic["dose_calibration"]
    nulls = {}
    for kind, record in synthetic["null_and_support_controls"].items():
        ms = record["matched_excess_dose_strengths"]
        nulls[kind] = {name: value["correction_dose"] for name, value in ms.items()}
    light = []
    for row in synthetic["true_light_controls"]:
        if row["kind"] == "light_during_motion" and row["step"] in (1.1, 1.25, 1.4):
            light.append({"factor": row["step"], "response_area22": {
                n: m["light_response"]["response_area_ratio"] for n, m in row["matched_excess_dose_strengths"].items()}})
    native = {key: {"frames": row["source_frames"], "role": row["role"],
        "dose": {n: m["correction_dose"] for n, m in row["metrics"].items()},
        "base_mask_samples": row["metrics"]["baseline_cpu"]["base_mask_samples"]}
        for key, row in captured.items() if key.startswith("native_policy/")}
    changed = sorted({p.relative_to(REPO).as_posix() for p in files()} |
                     {(HERE / n).relative_to(REPO).as_posix() for n in ("RESULT.json", "SHA256SUMS.json")})
    result = {
        "schema": "astra20261020.return.v1", "task_id": "02-anchor-estimator",
        "candidate_version": "anchor-diagnostic-v1", "recommendation": "keep_as_research",
        "base_tag": "astra-handoff-20261020", "resolved_tag_commit": BASE,
        "audited_production_commit": "87e8b7ab2a428bd91d3c044decf7d4dbccd8cefd",
        "branch": "astra/02-anchor-estimator", "pr_base": "sol/26-integration",
        "source_revision": {"git_commit": args.source_commit, "source_fingerprint_sha256": source_fingerprint,
            "fingerprint_framing": "sorted candidate .py/.hlsl relative UTF-8 path + NUL + hex SHA256 + newline",
            "sources": sources, "frozen_before_holdout": freeze,
            "note": "Source commit identifies the actual preceding code/evidence revision. The final delivery revision may add only RESULT/manifest metadata; its head is returned with the PR. Null before publication never invents a commit."},
        "changed_paths": changed, "production_changed_paths": [], "baseline_reference_changed_paths": [],
        "dependencies": {"python": ledger["python"], "numpy": ledger["numpy"], "matplotlib": ledger["matplotlib"],
                         "platform": ledger["platform"], "installer_run": False,
                         "dependency_note": "Exact required NumPy was already installed; figures used available Matplotlib3.10.8."},
        "seeds": {"synthetic_root": load("EXPERIMENT_PROTOCOL.json")["synthetic_seeds"],
                  "reviewer_preregistered": [20261020, 20261021, 20261022],
                  "reviewer_independent": [271828, 314159],
                  "other_seed_provenance": "mechanism/results.json and source files record additional deterministic generator seeds"},
        "cpu_execution": {"initial_untouched_baseline": original["runs"], "final_reproduction": ledger["runs"],
                          "visual_qa_rerun": load("evidence/visual_qa.json"), "unit_tests": 26,
                          "original_portable_suites": 4, "all_final_exit_codes_zero": True,
                          "initial_development_failures": "reviewer/REVIEW.md records defensive API defects reproduced live and corrected before source freeze; no pre-fix source hash or failing-run log was retained. reviewer/initial_audit.txt and post_fix_audit.txt contain passing reruns. The mechanism report discloses its corrected initial syntax error."},
        "fixture_hashes": fixture_hashes, "result_hashes": results,
        "measurements": {"calibration_dose": calibration["target_dose"], "matched_strengths": calibration["strengths"],
            "matched_dose_residual": calibration["absolute_dose_mismatch"],
            "matched_excess_calibration_null_doses": nulls, "genuine_light_response": light,
            "native_captured_comparisons": native, "moving_object_bilinear_cpu_proxy": synthetic["moving_object_bilinear_apply"],
            "deployable_correction_dose": 0., "deployable_abstain_fraction": 1.,
            "positive_dose_efficacy_of_deployable_output": None, "fresh_rr_quality": None,
            "final_game_quality": None, "gpu_ms": None, "resident_gpu_memory_bytes": None},
        "rejected_hypotheses": [
            "Global frame ratio >=1 guarantees that local one-sided darkening is harmless.",
            "Median/MAD of current/recalled ratios identifies real illumination versus excess.",
            "Typical paired log change necessarily has the same sign as frame energy change.",
            "Static centre plus neighborhood recall guarantees unsupported-cell identity.",
            "Identity at dynamic gain-grid centres guarantees full-resolution pixel identity."
        ],
        "supported_mechanisms": [
            "For nonnegative inputs and gain<=1, fixed-mask energy drift equals minus correction dose.",
            "Four bilinear taps leave a 75%-zero/25%-four sampling distribution for a uniformly located 64-unit spike in an8x8 cell.",
            "Identical observed tensors can require different desired outputs under true light versus input excess.",
            "The robust diagnostic trades away most captured apparent correction and fails a matched-dose correlated null."
        ],
        "unresolved_risks": [
            "No independent same-pose physical illumination witness or converged truth is present.",
            "Native raw pre-store sums and six-slice keys are absent; only already recalled observations are tested.",
            "Native fixture has seven sparse snapshots, including one held-out snapshot; no native temporal efficacy claim.",
            "Half conversion/sampler fractions and new shader branch parity need actual local validation.",
            "No HLSL build, Windows host build, D3D lifetime execution, fresh AMD RR, performance, VRAM or gameplay measurement.",
            "Shared D+S scalar is not a validated independent per-lobe estimator; bilinear transport remains job04."
        ],
        "gpu_executed": False, "hlsl_compiled": False, "production_adapter_applied": False,
        "acceptance_status": {"research_reproducibility": "pass", "independent_falsifier_suite": "pass: rejects known bad controls",
            "provisional_as_active_correction": "reject", "causal_discrimination": "unidentifiable with provided observations",
            "production_recommendation": "Anchor OFF; preserve protected preset", "local_gpu_game_gate": "pending independent observation and actual native/RR acceptance",
            "decision": "keep_as_research"},
        "actual_executors": {"baseline_before_changes": "implementation subagent, Linux CPU",
            "mechanism_and_inventory": "mechanism subagent; reproduced by root coordinator on Linux CPU",
            "independent_controls_and_holdout": "skeptical reviewer, separate tuning boundary; reproduced by root coordinator on Linux CPU",
            "full_experiments_and_visual_QA": "root coordinator, Linux CPU",
            "historical_gpu_fields": "handoff owner's prior local capture, never newly executed here"}
    }
    (HERE / "RESULT.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    manifest = {"schema": "anchor02.sha256_manifest.v1", "algorithm": "SHA256",
                "scope": "candidate directory, excludes this manifest and temporary Python caches",
                "files": {p.relative_to(HERE).as_posix(): {"sha256": sha(p), "bytes": p.stat().st_size}
                          for p in files() if p.name != "SHA256SUMS.json"}}
    (HERE / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"files": len(manifest["files"]), "source_fingerprint_sha256": source_fingerprint,
                      "source_git_commit": args.source_commit, "recommendation": result["recommendation"]}, indent=2))


if __name__ == "__main__":
    main()
