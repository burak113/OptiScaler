"""Compile the reused production lifetime state and reject a broken release rule.

Only portable CPU execution is claimed. All generated files go to --output.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SOURCE = HERE / "review_lifecycle_test.cpp"
HEADER = REPO / "OptiScaler/shaders/fsrd_preprocess/RRTraceFenceState.h"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cxx", help="A compiler executable path (g++, clang++, or cl).")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiler = args.cxx or os.environ.get("CXX") or next(
        (path for name in ("g++", "clang++", "cl") if (path := shutil.which(name))), None
    )
    if not compiler:
        print("No supported C++ compiler available; no native or GPU build claimed.", file=sys.stderr)
        return 2
    binary = output / ("review_lifecycle_test.exe" if os.name == "nt" else "review_lifecycle_test")
    if Path(compiler).name.lower() in ("cl", "cl.exe"):
        compile_cmd = [compiler, "/nologo", "/std:c++20", "/EHsc", "/W4", "/WX", f"/I{REPO}",
                       str(SOURCE), f"/Fe:{binary}", f"/Fo:{output / 'review_lifecycle_test.obj'}"]
    else:
        compile_cmd = [compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2",
                       "-I", str(REPO), str(SOURCE), "-o", str(binary)]
    commands = []
    for name, argv, expected in (
        ("compile", compile_cmd, 0),
        ("production_state", [str(binary)], 0),
        ("reject_broken_release", [str(binary), "--broken-release"], 1),
    ):
        result = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=120)
        log = result.stdout + result.stderr
        log_path = output / (name + ".txt")
        log_path.write_text(log, encoding="utf-8")
        passed = result.returncode == expected
        if expected == 1:
            passed = passed and "ASSERTION FAILED:" in log
        commands.append({"name": name, "argv": argv, "exit_code": result.returncode,
                         "expected_exit_code": expected, "passed": passed,
                         "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest()})
        print(f"{name}: {'PASS' if passed else 'FAIL'} (exit {result.returncode})", flush=True)
        if not passed:
            print(log, file=sys.stderr)
            break
    receipt = {"schema": "astra09-portable-lifetime-v1", "platform": platform.platform(),
               "python": platform.python_version(), "commands": commands,
               "sources": {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (SOURCE, HEADER, Path(__file__))},
               "passed": len(commands) == 3 and all(item["passed"] for item in commands),
               "windows_host_built": False, "gpu_executed": False}
    (output / "execution.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
