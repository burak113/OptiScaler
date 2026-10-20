"""Run the new job09 portable checks and prepare, without executing, native WARP checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.is_relative_to(HERE) or out.is_relative_to(ROOT / "research/astra20261020/candidates"):
        raise RuntimeError("Use a separate scratch output directory; delivered evidence is immutable")
    out.mkdir(parents=True, exist_ok=True)
    stages = [
        ("observation", "observation_checks.py", []),
        ("support", "support_run_checks.py", []),
        ("lifecycle", "review_run_lifecycle.py", []),
        ("metadata", "metadata_compile_checks.py", []),
        ("reader", "observation_capture_reader_tests.py", []),
        ("gpu_prepare", "review_run_capture_gpu.py", ["--prepare-only"]),
    ]
    source_paths = sorted([*HERE.glob("*.py"), *HERE.glob("*.cpp")])
    source_paths += [ROOT / "OptiScaler/shaders/fsrd_preprocess" / name for name in (
        "FSRDNrdObservationContract.h", "FSRDNrdSupportContract.h", "FSRDGameTraceSession.cpp",
        "FSRDGameTraceSession.h", "FSRDNrdBridgeRR_Dx12.cpp", "FSRDNrdBridgeRR_Dx12.h",
        "FSRDNrdBridge_Dx12.cpp", "FSRDNrdPostMotionAnchor_Dx12.h", "RRTraceFence.h", "RRTraceFenceState.h")]
    before = {str(path.relative_to(ROOT)): sha(path) for path in source_paths}
    receipt = {"schema": "astra09-local-checks-v1", "base_tag": "astra-audit-20261020",
               "base_commit": "5fe436dd9a21cb9cc69dec371521a055c9af049d",
               "command": sys.argv, "platform": platform.platform(), "python": sys.version,
               "source_sha256": before, "windows_build": False, "gpu_executed": False,
               "quality_accepted": False, "stages": []}
    passed = True
    for name, filename, extra in stages:
        command = [sys.executable, str(HERE / filename), "--output", str(out / name), *extra]
        start = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
        log = out / (name + ".log")
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        success = result.returncode == 0
        passed &= success
        receipt["stages"].append({"name": name, "arguments": command, "exit_code": result.returncode,
                                  "passed": success, "elapsed_seconds": time.monotonic() - start,
                                  "log_sha256": sha(log),
                                  "scope": "source preparation only" if name == "gpu_prepare" else "portable CPU execution"})
        print(f"{name}: exit {result.returncode}", flush=True)
    receipt["source_unchanged_after_execution"] = before == {
        str(path.relative_to(ROOT)): sha(path) for path in source_paths}
    receipt["passed"] = passed and receipt["source_unchanged_after_execution"]
    receipt["exit_code"] = 0 if receipt["passed"] else 1
    (out / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
