"""Compile and exercise the production FSR output/context resolution policy."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT/'tools_tmp/fsr_output_scaling/tests'))/'output_scaling'
    exe = out/'fsr_output_scaling_test.exe'
    compile_cpp(Path(__file__).with_name('fsr_output_scaling_test.cpp'), exe)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    run()
