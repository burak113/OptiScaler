"""Compile actual serializer regions with portable POD adapters; no native build claim."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PRODUCTION = ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = PRODUCTION.read_text(encoding="utf-8")
    regions = {
        "production_observation_state.inc": ("struct NativeObservationState\n", "struct Frame\n"),
        "production_copy_footprint.inc": ("Json CopyFootprintMetadata(", "Json NativeResourceMetadata("),
        "production_observation_helpers.inc": ("Json ObservationStamp(", "// This function is called ONLY under WithCompletedSnapshot."),
    }
    sources = [PRODUCTION, Path(__file__), HERE / "metadata_compile_test.cpp",
               ROOT / "external/nlohmann/json.hpp",
               ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdObservationContract.h",
               ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdSupportContract.h"]
    for filename, (begin, end) in regions.items():
        if text.count(begin) != 1 or text.count(end) != 1:
            raise RuntimeError("Production extraction boundary is not unique: " + filename)
        region = text[text.index(begin):text.index(end, text.index(begin))]
        path = out / filename
        path.write_text(region, encoding="utf-8")
        sources.append(path)
    compiler = shutil.which("g++")
    if not compiler:
        raise RuntimeError("Portable g++ compiler unavailable; this is not a Windows build runner")
    exe = out / "metadata_compile_test"
    commands = [("compile", [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                              "-I", str(ROOT), "-I", str(out), str(HERE / "metadata_compile_test.cpp"), "-o", str(exe)]),
                ("execute", [str(exe)])]
    receipt = {"schema": "astra09-production-metadata-cpu-v1", "command": sys.argv,
               "platform": platform.platform(), "python": sys.version,
               "scope": "unmodified production serializer helper regions; POD native-type adapters",
               "windows_build": False, "gpu_executed": False, "quality_accepted": False,
               "sources_sha256": {str(path): sha(path) for path in sources}, "commands": []}
    passed = True
    for name, command in commands:
        start = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        log = out / (name + ".log")
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        receipt["commands"].append({"name": name, "arguments": command, "exit_code": result.returncode,
                                    "elapsed_seconds": time.monotonic() - start, "log_sha256": sha(log)})
        print(name + ": " + str(result.returncode))
        if result.returncode:
            print(result.stdout + result.stderr)
            passed = False
            break
    if exe.exists():
        receipt["executable_sha256"] = sha(exe)
    receipt["passed"] = passed
    (out / "metadata_execution.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
