"""Compile and execute the production SR settings helper with a fake FFX provider."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp


def run():
    root = Path(__file__).resolve().parents[4]
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", root / "tools_tmp/fsr_upscale_settings/tests"))
    generated = out / "sr_settings"
    generated.mkdir(parents=True, exist_ok=True)
    # Keep pch.h first in the standalone test while isolating the header from
    # the application's device/proxy dependencies and precompiled header.
    (generated / "pch.h").write_text("#pragma once\n", encoding="utf-8")
    ffx_include = Path(os.environ.get(
        "FSRD_FFX_INCLUDE", root / "external/FidelityFX-SDK/ffx-api/include/ffx_api"))
    exe = generated / "fsr_upscale_settings_test.exe"
    compile_cpp(Path(__file__).with_name("fsr_upscale_settings_test.cpp"), exe,
                include_dirs=(generated, ffx_include))
    subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    run()
