"""One reproducibility command for job02, including independent falsifiers.

No GPU, DLL installation, build, network access, or production edits occur.
Output files are confined to this candidate directory. The packaged references
are read-only inputs, verified both before and after running the experiments.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
PREFIX = HERE.relative_to(REPO).as_posix()
OUT = HERE / "evidence/checks"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_freeze():
    frozen = json.loads((HERE / "evidence/FROZEN_SOURCE.json").read_text())
    bad = [p for p, expected in frozen["files"].items() if sha(HERE / p) != expected]
    if bad:
        raise RuntimeError("frozen sources differ; do not silently rerun/tune holdout: " + ", ".join(bad))
    return {"verified_files": len(frozen["files"]), "receipt_sha256": sha(HERE / "evidence/FROZEN_SOURCE.json")}


def run(name, args):
    command = [sys.executable, "-B", *args]
    human = "python -B " + " ".join(args)
    print("START " + name, flush=True)
    begin = time.perf_counter()
    result = subprocess.run(command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    elapsed = time.perf_counter() - begin
    # Preserve useful failure text without embedding machine-specific paths.
    output = result.stdout.replace(str(REPO), "<repo>")
    log = OUT / (name + ".txt")
    log.write_text(output)
    receipt = {"name": name, "command": human, "cwd": "repository root", "exit_code": result.returncode,
               "elapsed_seconds": elapsed, "log": log.relative_to(HERE).as_posix(), "log_sha256": sha(log),
               "executor": "root coordinator, Linux CPU; independent reviewer source reproduced where labeled"}
    print(f"END {name}: exit={result.returncode}, elapsed={elapsed:.3f}s", flush=True)
    if result.returncode:
        print(output[-8000:], flush=True)
    return receipt


def verify_results():
    captured = json.loads((HERE / "evidence/captured_results.json").read_text())
    synthetic = json.loads((HERE / "evidence/synthetic_results.json").read_text())
    reviewer = json.loads((HERE / "reviewer/holdout_reproduction.json").read_text())
    assert "native_policy/2405579e" in captured
    for record in captured.values():
        assert record["metrics"]["causal_abstainer"]["correction_dose"] == 0.
        assert record["metrics"]["causal_abstainer"]["abstain_fraction_on_base_mask"] == 1.
        assert record["metrics"]["provisional_diagnostic"]["unsupported_changed_cells"] == 0
    calibration = synthetic["dose_calibration"]
    assert calibration["production_at_nonzero_matched_dose"] is None
    assert calibration["absolute_dose_mismatch"] < 1e-6
    anti = synthetic["null_and_support_controls"]["equal_energy_antithetic"]["matched_excess_dose_strengths"]
    assert anti["provisional_diagnostic"]["correction_dose"]["mean"] > anti["baseline"]["correction_dose"]["mean"]
    # This is an explicit known-bad rejection gate, not approving the diagnostic.
    for light in synthetic["true_light_controls"]:
        if light["kind"] == "light_during_motion" and light["step"] in (1.1, 1.25, 1.4):
            m = light["matched_excess_dose_strengths"]
            assert m["provisional_diagnostic"]["light_response"]["response_area_ratio"] < .95
            assert m["causal_abstainer"]["light_response"]["response_area_ratio"] > .999
    # Strict JSON serialization: unknown observations are null, never NaN/Inf.
    json.dumps([captured, synthetic, reviewer], allow_nan=False)
    return {"production_abstention_verified": True, "active_diagnostic_rejected": True,
            "matched_excess_dose_error": calibration["absolute_dose_mismatch"],
            "native_holdout_temporal_replay": False, "gpu_executed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-plots", action="store_true", help="core checks need only packaged NumPy")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    freeze = verify_freeze()
    commands = [
        ("package_integrity_before", ["research/astra20261020/validate_package.py"]),
        ("untouched_package_cpu", ["research/astra20261020/run_cpu.py"]),
        ("candidate_and_measurement_tests", ["-m", "unittest", "discover", "-s", PREFIX + "/tests", "-v"]),
        ("independent_audit_tests", ["-m", "unittest", "discover", "-s", PREFIX + "/reviewer", "-p", "test_independent_audit.py", "-v"]),
        ("known_bad_controls", [PREFIX + "/reviewer/independent_controls.py"]),
        ("mechanism_investigation", [PREFIX + "/mechanism/investigate.py"]),
        ("data_inventory", [PREFIX + "/mechanism/inventory.py", "--include-bottle"]),
    ]
    runs = [run(name, argv) for name, argv in commands]
    if not any(r["exit_code"] for r in runs):
        # Independent scripts read the same frozen inputs but write disjoint
        # evidence folders. Neither tunes the source and each verifies scope.
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs = [("full_experiments", [PREFIX + "/experiments.py", "--include-holdout"]),
                    ("independent_holdout_reproduction", [PREFIX + "/reviewer/reproduce_holdout.py"])]
            futures = [executor.submit(run, name, argv) for name, argv in jobs]
            runs.extend(f.result() for f in futures)
    verification = None
    if not any(r["exit_code"] for r in runs):
        verification = verify_results()
        if not args.skip_plots:
            runs.append(run("visual_panels", [PREFIX + "/plot_results.py"]))
        runs.append(run("package_integrity_after", ["research/astra20261020/validate_package.py"]))
    verify_freeze()
    ledger = {"schema": "anchor02.cpu_execution.v1", "started_utc": started,
              "finished_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "numpy": importlib.metadata.version("numpy"),
              "matplotlib": importlib.metadata.version("matplotlib") if not args.skip_plots else None,
              "platform": platform.platform(), "freeze": freeze, "runs": runs,
              "result_gates": verification, "gpu_executed": False,
              "success": not any(r["exit_code"] for r in runs) and verification is not None}
    path = HERE / "evidence/run_ledger.json"
    path.write_text(json.dumps(ledger, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"success": ledger["success"], "runs": len(runs), "gpu_executed": False}, indent=2))
    raise SystemExit(0 if ledger["success"] else 1)


if __name__ == "__main__":
    main()
