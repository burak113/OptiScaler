"""Compile and exercise the production FSRD debug blit source mapping."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT/'tools_tmp/fsrd_blit_mapping/tests'))/'blit_mapping'
    exe = out/'fsrd_blit_mapping_test.exe'
    compile_cpp(Path(__file__).with_name('fsrd_blit_mapping_test.cpp'), exe)
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    run()
