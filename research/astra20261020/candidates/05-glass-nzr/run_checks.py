"""One reproducible CPU command, including known negative controls.

Run from any directory: python -B path/to/05-glass-nzr/run_checks.py
Use --skip-holdout for a subsequent contract-only check; that flag is NOT a new
holdout evaluation. Logs/results stay in this workstream's evidence directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
import time

import numpy as np

CANDIDATE = Path(__file__).resolve().parent
REPO = CANDIDATE.parents[3]
RELATIVE = CANDIDATE.relative_to(REPO).as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-holdout", action="store_true")
    args = parser.parse_args()
    outdir = CANDIDATE/"evidence"/("root_contract_rerun" if args.skip_holdout else "root_full_run")
    outdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
    steps = [
        ("package_validation", ["research/astra20261020/validate_package.py"], 0),
        ("frozen_cpu_baseline", ["research/astra20261020/run_cpu.py"], 0),
        ("candidate_and_independent_tests", ["-m", "unittest", "discover", "-s", RELATIVE+"/tests", "-p", "test_*.py", "-v"], 0),
        ("source_shaped_causal_probes", [RELATIVE+"/experiments/causal_probes.py"], 0),
        ("recorded_inventory", [RELATIVE+"/experiments/recorded.py", "--images"], 0),
        ("adapter_scope_and_clean_apply", [RELATIVE+"/adapter/validate_adapter.py"], 0),
        ("known_bad_colour_quality_gate", ["research/astra20261020/portable/colour/compare.py", "--quality-gate"], 1),
        ("alpha_authority_mutation", [RELATIVE+"/tests/test_review_adversarial.py", "--mutation-alpha"], 1),
    ]
    if not args.skip_holdout:
        steps.append(("frozen_holdout", [RELATIVE+"/experiments/synthetic.py", "--split", "holdout",
                                         "--executor", "cloud Linux CPU root agent"], 0))
    ledger = {"schema": "glass-nzr-cpu-execution-v1", "executor": "cloud Linux CPU root agent",
              "started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "numpy": np.__version__, "platform": platform.system()+" "+platform.machine(),
              "gpu_executed": False, "holdout_requested": not args.skip_holdout, "runs": []}
    started = time.monotonic()
    success = True
    for name, command, expected in steps:
        before = time.monotonic()
        process = subprocess.run([sys.executable, "-B", *command], cwd=REPO, env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        # Machine-specific checkout and Python installation prefixes are removed
        # from tracebacks; no result or failure text is discarded. Exact invocation
        # is recorded separately.
        output = process.stdout.replace(str(REPO)+"/", "")
        output = re.sub(r'File "(/[^"\n]*/site-packages/)([^"\n]+)"',
                        r'File "<python-site-packages>/\2"', output)
        log = outdir/(name+".txt")
        log.write_text(output, encoding="utf-8")
        item = {"command": shlex.join(["python", "-B", *command]), "command_argv": ["python", "-B", *command],
                "exit_code": process.returncode, "expected_exit_code": expected,
                "elapsed_seconds": time.monotonic()-before,
                "log": log.relative_to(CANDIDATE).as_posix(),
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        ledger["runs"].append(item)
        print(json.dumps({"step": name, "exit_code": process.returncode, "expected_exit_code": expected,
                          "elapsed_seconds": item["elapsed_seconds"]}), flush=True)
        if process.returncode != expected:
            success = False
            print(output[-5000:], flush=True)
            break
    ledger["elapsed_seconds"] = time.monotonic()-started
    ledger["status"] = "passed_with_detected_negative_controls" if success else "failed"
    ledger["exit_code"] = 0 if success else 1
    ledger["code_sha256"] = {p.relative_to(CANDIDATE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for folder in ("src", "tests", "experiments", "adapter")
                              for p in sorted((CANDIDATE/folder).rglob("*.py"))}
    (outdir/"execution.json").write_text(json.dumps(ledger, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"status": ledger["status"], "elapsed_seconds": ledger["elapsed_seconds"],
                      "ledger": (outdir/"execution.json").relative_to(CANDIDATE).as_posix()}), flush=True)
    return ledger["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
