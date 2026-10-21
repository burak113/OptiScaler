"""Build/run the actual native D3D12 pass on Windows, under the shared GPU lock.

Example (PowerShell, using the existing local lock provider):
  python -B review/run_native_smoke.py --output F:/FSRD/tmp/astra10-direct \
      --gpu-lock-root F:/FSRD/sol_batch

--compile-only does not require a GPU lock.  --warp is a software-device
mechanical check and is never hardware performance evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = HERE.parents[4]
NATIVE = BASE / "native"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu-lock-root", type=Path,
                        default=Path(os.environ["FSRD_GPU_LOCK_ROOT"]) if "FSRD_GPU_LOCK_ROOT" in os.environ else None)
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument("--warp", action="store_true")
    parser.add_argument("--build-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "native-colour-direct-pass-execution-v1",
        "runtime": {"python": sys.version, "platform": platform.platform()},
        "sources": {str(p.relative_to(BASE)): sha(p) for p in [
            HERE / "native_pass_smoke.cpp", Path(__file__), NATIVE / "NativeColourContract.h",
            NATIVE / "NativeColourPass_Dx12.h", NATIVE / "NativeColourPass_Dx12.cpp",
            NATIVE / "NativeColourPacked.hlsl"] if p.is_file()},
        "windows_compile_executed": False,
        "gpu_executed": False,
        "quality_accepted": False,
        "stages": [],
    }
    receipt_path = out / "execution.json"

    def finish(status: str, code: int) -> int:
        receipt["status"] = status
        receipt_path.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": status, "receipt": str(receipt_path)}, ensure_ascii=False))
        return code

    if os.name != "nt":
        return finish("pending_windows_d3d12_msvc_dxc", 2)
    sys.path.insert(0, str(REPO / "OptiScaler/shaders/shader_tools"))
    from fsrd_toolchain import compile_cpp, dxc

    if args.build_child:
        os.environ["FSRD_CPP_CACHE"] = str(out / "cpp-cache")
        compile_cpp(HERE / "native_pass_smoke.cpp", out / "native_pass_smoke.exe",
                    ["d3d12.lib", "dxgi.lib", "dxguid.lib"])
        return 0

    def run(stage: str, command: list[str], timeout: int) -> subprocess.CompletedProcess:
        start = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout)
        (out / f"{stage}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        receipt["stages"].append({"name": stage, "command": command,
                                  "exit": result.returncode, "elapsed_seconds": time.perf_counter()-start,
                                  "log_sha256": sha(out / f"{stage}.log")})
        return result

    try:
        compiler = Path(dxc())
        receipt["dxc"] = {"path": str(compiler), "sha256": sha(compiler)}
        shader = out / "NativeColourPacked.cso"
        result = run("dxc", [str(compiler), "-T", "cs_6_2", "-E", "CSMain", "-HV", "2021",
                             "-Ges", "-Gis", "-O3", str(NATIVE / "NativeColourPacked.hlsl"),
                             "-Fo", str(shader)], 120)
        if result.returncode:
            return finish("shader_compile_failed", 1)
        result = run("msvc", [sys.executable, "-B", str(Path(__file__)), "--build-child",
                              "--output", str(out)], 300)
        if result.returncode:
            return finish("native_class_compile_failed", 1)
        receipt["windows_compile_executed"] = True
        receipt["artifacts"] = {name: sha(out / name) for name in
                                ("NativeColourPacked.cso", "native_pass_smoke.exe")}
        if args.compile_only:
            return finish("windows_compile_passed_gpu_pending", 0)
        if args.gpu_lock_root is None or not (args.gpu_lock_root / "gpu_lock.py").is_file():
            return finish("compiled_pending_existing_shared_gpu_lock_provider", 2)
        sys.path.insert(0, str(args.gpu_lock_root.resolve()))
        from gpu_lock import gpu_lock
        command = [str(out / "native_pass_smoke.exe"), str(shader), str(out / "native_result.json")]
        if args.warp:
            command.append("--warp")
        with gpu_lock(os.environ.get("FSRD_GPU_TEST_OWNER", "astra10-native-colour-direct")):
            result = run("native_run", command, 180)
        if (out / "native_result.json").is_file():
            native = json.loads((out / "native_result.json").read_text(encoding="utf-8"))
            receipt["gpu_executed"] = bool(native.get("gpu_executed", False))
            receipt["native_result_sha256"] = sha(out / "native_result.json")
            if result.returncode == 0 and native.get("passed") is True:
                return finish("native_mechanics_passed_quality_not_accepted", 0)
        return finish("native_mechanics_failed", 1)
    except Exception as error:
        receipt["error"] = str(error)
        return finish("blocked_or_failed_see_error", 1)


if __name__ == "__main__":
    raise SystemExit(main())
