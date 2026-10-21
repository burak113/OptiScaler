#!/usr/bin/env python3
"""Build/run the real portable C++ validators and four broken-header controls.

Outputs are always outside this immutable source directory. This does not compile
the Windows adapter or HLSL and never reports CPU validation as GPU execution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--cxx", default="cl" if platform.system() == "Windows" else "g++")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output.resolve()
    if output == root or root in output.parents:
        ap.error("test output must be outside the native source directory")
    output.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit(f"C++ compiler unavailable: {args.cxx}")
    msvc = Path(compiler).name.lower() in ("cl", "cl.exe")
    original = (root / "NativeColourContract.h").read_text(encoding="utf-8")
    mutations = {
        "baseline": None,
        "force_default_on": ("bool enabled = false;", "bool enabled = true;"),
        "ignore_reset": ("if (f.reset || f.resized) return Decision::ResetOrResize;", "// broken: reset and resize ignored"),
        "wrong_diffuse_scale": ("x.providerScale == 16", "x.providerScale == 256"),
        "omit_last_row_padding": ("x.offset + uint64_t(x.rowPitch)*x.height", "x.offset + uint64_t(x.rowPitch)*(x.height-1) + uint64_t(x.width)*8"),
    }
    records = []
    with tempfile.TemporaryDirectory(prefix="native-colour-cpp-") as temp:
        temp = Path(temp)
        for name, mutation in mutations.items():
            directory = temp / name
            directory.mkdir()
            text = original
            if mutation:
                old, new = mutation
                if text.count(old) != 1:
                    raise RuntimeError(f"mutation target drift: {name}")
                text = text.replace(old, new)
                if name == "force_default_on":
                    # Both default gates are deliberately broken; a single one
                    # remains fail-closed and is not a meaningful active mutant.
                    text = text.replace("bool acknowledgeRejectedResearch = false;", "bool acknowledgeRejectedResearch = true;")
            (directory / "NativeColourContract.h").write_text(text, encoding="utf-8")
            shutil.copy2(root / "contract_tests.cpp", directory / "contract_tests.cpp")
            executable = directory / ("contract.exe" if platform.system() == "Windows" else "contract")
            if msvc:
                build = [compiler, "/nologo", "/std:c++17", "/EHsc", "/W4",
                         str(directory / "contract_tests.cpp"), "/Fe:" + str(executable),
                         "/Fo:" + str(directory / "contract.obj")]
            else:
                build = [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                         str(directory / "contract_tests.cpp"), "-o", str(executable)]
            start = time.perf_counter()
            compiled = subprocess.run(build, capture_output=True, text=True, encoding="utf-8")
            if compiled.returncode:
                raise RuntimeError(f"C++ build failed for {name}: {compiled.stderr}")
            run = subprocess.run([str(executable)], capture_output=True, text=True, encoding="utf-8")
            (output / f"{name}.txt").write_text(compiled.stdout + compiled.stderr + run.stdout + run.stderr, encoding="utf-8")
            expected = 0 if name == "baseline" else 1
            record = {"name": name, "build": build, "build_exit": compiled.returncode,
                      "exit": run.returncode, "expected_exit": expected,
                      "passed": run.returncode == expected, "elapsed_seconds": time.perf_counter()-start,
                      "header_sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "stdout": run.stdout.strip(), "stderr": run.stderr.strip()}
            records.append(record)
    version = subprocess.run([compiler] if msvc else [compiler, "--version"], capture_output=True, text=True)
    version_lines = (version.stdout + version.stderr).splitlines()
    result = {"platform": platform.platform(), "compiler": compiler,
              "compiler_version": version_lines[0] if version_lines else "unreported",
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (root / "NativeColourContract.h", root / "contract_tests.cpp")},
              "scope": "portable C++ host validation only; no D3D12 or shader compilation",
              "checks": records, "passed": all(r["passed"] for r in records)}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "checks": len(records), "result": str(output / "result.json")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
