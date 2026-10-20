"""Portable, non-destructive checks of all seven returned research snapshots.

Exit zero means contracts passed, not visual quality acceptance. Original
receipts and source files are immutable; fresh logs go only to --output.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
REPO = PACKAGE.parents[1]
CANDIDATES = PACKAGE / "candidates"


def verify_intake():
    manifest = json.loads((HERE / "INTAKE.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["sha256"].items():
        path = REPO / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise AssertionError("Returned snapshot changed: " + relative)
    return len(manifest["sha256"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.is_relative_to(CANDIDATES):
        raise ValueError("Fresh evidence must not overwrite a returned snapshot")
    out.mkdir(parents=True, exist_ok=True)
    count = verify_intake()
    jobs = [
        ("frozen_package", [str(PACKAGE / "validate_package.py")], 0, PACKAGE),
        ("four_baselines", [str(PACKAGE / "run_cpu.py")], 0, PACKAGE),
    ]
    for candidate in sorted(CANDIDATES.iterdir()):
        if (candidate / "tests").is_dir():
            jobs.append((candidate.name, ["-m", "unittest", "discover", "-s",
                         str(candidate / "tests"), "-p", "test_*.py", "-v"], 0, candidate))
    anchor = CANDIDATES / "02-anchor-estimator"
    jobs.append(("anchor_independent", ["-m", "unittest", "discover", "-s",
                 str(anchor / "reviewer"), "-p", "test_independent_audit.py", "-v"], 0, anchor))
    numerical = CANDIDATES / "01-numerical-contract"
    jobs.append(("portable_adapters", [str(HERE / "verify_adapters.py")], 0, HERE))
    for script in ("adversary_controls.py",):
        jobs.append(("numerical_" + Path(script).stem, [str(numerical / script)], 0, numerical))
    for mutant in ("wrong_uv", "nearest", "old_normal", "missing_high", "premature_rounding"):
        jobs.append(("reject_" + mutant, [str(numerical / "mutants.py"), mutant], 1, numerical))
    glass = CANDIDATES / "05-glass-nzr"
    jobs.append(("glass_bundle_utf8", [str(glass / "verify_bundle.py")], 0, glass))
    for option, expected in (("--mutation-alpha", 1), ("--measurements", 0), ("--audit-holdout", 0)):
        jobs.append(("glass_" + option[2:], [str(glass / "tests/test_review_adversarial.py"), option], expected, glass))
    rows = []
    for name, arguments, expected, imports in jobs:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
                   PYTHONIOENCODING="utf-8", PYTHONPATH=str(imports),
                   OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
        start = time.perf_counter()
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", *arguments],
                                cwd=REPO, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=300)
        log = (result.stdout + result.stderr).replace(str(REPO), "<repo>")
        (out / (name + ".txt")).write_text(log, encoding="utf-8")
        match = re.search(r"Ran (\d+) tests? in", log)
        row = dict(name=name, arguments=[s.replace(str(REPO), "<repo>") for s in arguments],
                   exit_code=result.returncode, expected_exit_code=expected,
                   elapsed_seconds=time.perf_counter() - start,
                   unittest_count=int(match[1]) if match else None,
                   passed=result.returncode == expected,
                   log_sha256=hashlib.sha256((out / (name + ".txt")).read_bytes()).hexdigest())
        # A crash is not evidence that a deliberately broken implementation was caught.
        if expected == 1:
            row["passed"] &= ("AssertionError" in log or "FAIL" in log or '"detected": true' in log)
        rows.append(row)
        print(name, "PASS" if row["passed"] else "FAIL", "exit", result.returncode, flush=True)
        if not row["passed"]:
            print(log[-4000:], flush=True)
            break
    unchanged = verify_intake() == count
    receipt = dict(schema="astra-local-audit-cpu-v1", platform=platform.platform(),
                   python=platform.python_version(), runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   intake_files=count, intake_unchanged_after_execution=unchanged,
                   commands=rows, passed=len(rows) == len(jobs) and all(r["passed"] for r in rows),
                   quality_accepted=False, gpu_executed=False)
    (out / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
