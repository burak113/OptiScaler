"""Independent reproduction of the frozen soft2 rejection before candidate review.

This executes the packaged CPU comparison unchanged. The expected subprocess
exit status is one: the known-bad quality candidate fails its boundary gate.
Nothing in this file imports the new candidate or scores its performance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
COLOUR = PACKAGE / "portable" / "colour"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    started = time.perf_counter()
    run = subprocess.run(
        [sys.executable, "-B", "compare.py", "--quality-gate"],
        cwd=COLOUR, capture_output=True, text=True, check=False,
    )
    elapsed = time.perf_counter() - started
    (HERE / "known_bad_stdout.json").write_text(run.stdout, encoding="utf-8")
    (HERE / "known_bad_stderr.txt").write_text(run.stderr, encoding="utf-8")
    report = json.loads(run.stdout)
    phases = [r for r in report["edges"]["cases"]
              if r["kind"] in ("normal", "depth") and r["phase"] == 4]
    for row in phases:
        row["soft2_over_B4_ratio"] = (
            row["soft2_right_bleed_mean"] / row["B4_right_bleed_mean"]
        )
    accepted_reproduction = (
        run.returncode == 1
        and report["edges"]["verdict"] == "rejected_halo_regression"
        and len(report["edges"]["cases"]) == 32
        and len(phases) == 2
        and all(row["soft2_over_B4_ratio"] > 1.5 for row in phases)
    )
    receipt = {
        "executor": "independent_skeptical_reviewer",
        "scope": "New CPU execution of packaged controls; no candidate inspected and no GPU executed.",
        "command": "python -B compare.py --quality-gate",
        "cwd": "research/astra20261020/portable/colour",
        "exit_code": run.returncode,
        "expected_exit_code": 1,
        "elapsed_seconds": elapsed,
        "known_bad_reproduced": accepted_reproduction,
        "worse_cases_of_32": report["edges"]["worse_cases"],
        "phase4_counterexamples": phases,
        "gpu_executed": False,
        "hashes": {
            "colour_portable.py": sha256(COLOUR / "colour_portable.py"),
            "compare.py": sha256(COLOUR / "compare.py"),
            "test_colour_portable.py": sha256(COLOUR / "test_colour_portable.py"),
            "fixtures/soft2_gpu_87ee63.npz": sha256(COLOUR / "fixtures" / "soft2_gpu_87ee63.npz"),
            "frozen_protocol.json": sha256(HERE / "frozen_protocol.json"),
            "known_bad_stdout.json": sha256(HERE / "known_bad_stdout.json"),
            "known_bad_stderr.txt": sha256(HERE / "known_bad_stderr.txt"),
        },
    }
    (HERE / "known_bad_receipt.json").write_text(
        json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, allow_nan=False))
    return 0 if accepted_reproduction else 1


if __name__ == "__main__":
    raise SystemExit(main())
