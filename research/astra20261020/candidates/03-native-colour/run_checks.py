"""One command for meaningful CPU contracts and retained-experiment integrity.

This does not change the frozen independent review receipts. The complete
scientific experiments can be rerun with the individual commands in REPORT.md.
Exit0 means execution/contracts/integrity passed; it NEVER means colour quality
was accepted. The independent --quality-gate result remains exit1 and is reported.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
REPO = PACKAGE.parents[1]
BASE = "5d7839a930106cf8fe1ba8dbbc6750509e7f26a8"
CANDIDATE_PREFIX = "research/astra20261020/candidates/03-native-colour/"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strict_json(path):
    def invalid(value):
        raise ValueError(f"Non-JSON numeric literal {value} in {path.name}")
    return json.loads(Path(path).read_text(), parse_constant=invalid)


def integrity():
    manifest = strict_json(HERE / "review/REVIEW_MANIFEST.json")
    for entry in manifest["files"]:
        path = HERE / entry["path"]
        if not path.resolve().is_relative_to(HERE):
            raise AssertionError("Escaping review manifest path")
        if path.stat().st_size != entry["bytes"] or file_hash(path) != entry["sha256"]:
            raise AssertionError("Independent review evidence changed: " + entry["path"])
    core_sha = file_hash(HERE / "native_colour.py")
    review = strict_json(HERE / "review/review_result.json")
    confidence = strict_json(HERE / "mechanism/confidence_results.json")
    clips = strict_json(HERE / "evidence/clip_results.json")
    low_contrast = strict_json(HERE / "review/low_contrast_results.json")
    if any(value != core_sha for value in (review["source_sha256"], confidence["native_source_sha256"],
                                          clips["source_sha256"], low_contrast["source_sha256"])):
        raise AssertionError("Source changed after a recorded experiment")
    if low_contrast["original_review_result_sha256_unchanged"] != file_hash(HERE / "review/review_result.json"):
        raise AssertionError("Follow-up replaced original heldout review")
    if review["quality_gate_exit_code"] != 1 or review["summary"]["quality_pass"]:
        raise AssertionError("Frozen rejected candidate was relabelled as accepted")
    if low_contrast["case_count"] != 32 or not low_contrast["counterexample_found"]:
        raise AssertionError("Low-contrast counterexample receipt is missing")
    checked_arrays = 0
    for path in HERE.rglob("*.json"):
        strict_json(path)
    for path in HERE.rglob("*.npz"):
        with np.load(path, allow_pickle=False) as data:
            for key in data.files:
                if data[key].dtype.hasobject:
                    raise AssertionError("Object/pickle evidence is forbidden")
                checked_arrays += 1
    if (REPO / ".git").exists():
        result = subprocess.run(["git", "diff", "--name-only", BASE], cwd=REPO,
                                capture_output=True, text=True, check=True)
        outside = [p for p in result.stdout.splitlines() if not p.startswith(CANDIDATE_PREFIX)]
        if outside:
            raise AssertionError("Changed paths outside candidate: " + repr(outside))
    return {"independent_review_manifest_files": len(manifest["files"]),
            "candidate_evidence_npz_arrays": checked_arrays, "source_sha256": core_sha,
            "gpu_executed": False, "recorded_quality_gate_exit_code": 1,
            "quality_accepted": False, "recommendation": "keep_as_research"}


def main():
    stages = [
        ("package_integrity_final", ["-B", "research/astra20261020/validate_package.py"]),
        ("portable_baselines_final", ["-B", "research/astra20261020/run_cpu.py"]),
        ("native_contracts_and_independent_mutations", ["-B", "-m", "unittest", "discover", "-s", CANDIDATE_PREFIX + "tests", "-p", "test_*.py", "-v"]),
    ]
    env = dict(os.environ, OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2",
               PYTHONDONTWRITEBYTECODE="1", MPLCONFIGDIR="/tmp/native-colour-matplotlib")
    receipts = []
    for name, command in stages:
        start = time.monotonic()
        r = subprocess.run([sys.executable, *command], cwd=REPO, env=env, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = HERE / "evidence" / (name + ".txt")
        log.write_text(r.stdout)
        row = {"stage": name, "command": "python " + " ".join(command),
               "cwd": "repository_root", "executor": "root_cpu_verification",
               "exit_code": r.returncode, "elapsed_seconds": time.monotonic() - start,
               "log": str(log.relative_to(HERE)), "log_sha256": file_hash(log)}
        receipts.append(row)
        print(json.dumps(row), flush=True)
        if r.returncode:
            print(r.stdout, flush=True)
            raise SystemExit(r.returncode)
    check = integrity()
    result = {"schema": "native-colour-root-verification-v1", "python": platform.python_version(),
              "numpy": np.__version__, "stages": receipts, "integrity": check,
              "execution_and_contracts_pass": True, "quality_accepted": False,
              "quality_gate_scope": "Independent recorded synthetic --quality-gate failed with exit1; low-contrast counterexample also retained. No failure relabelled as a quality pass."}
    (HERE / "evidence/root_verification.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("CPU execution/contracts/integrity PASS. Native image quality NOT ACCEPTED; keep as research.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
