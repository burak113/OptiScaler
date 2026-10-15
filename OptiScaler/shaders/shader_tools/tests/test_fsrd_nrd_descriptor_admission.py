"""Deterministic actual-header CPU concurrency proof; no D3D/GPU claim."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def run():
    output = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    if output.exists():
        raise AssertionError('fresh output required; preserve negatives')
    output.mkdir(parents=True)
    source = output/'admission.cpp'
    source.write_text((HERE/'fsrd_nrd_descriptor_admission_fixture.cpp').read_text().replace('__ROOT__', ROOT.as_posix()))
    executable = output/'admission.exe'
    compile_cpp(source, executable, libraries=['Synchronization.lib'])
    rows = []
    for mode in ('normal', 'submit-in-mutation', 'mutation-in-submit', 'failure-before-wait'):
        completed = subprocess.run([str(executable), mode], capture_output=True, text=True, timeout=40)
        (output/f'{mode}.stdout.txt').write_text(completed.stdout)
        (output/f'{mode}.stderr.txt').write_text(completed.stderr)
        rows.append(dict(mode=mode, exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr))
        print(completed.stdout, end='')
        print(completed.stderr, end='')
        (output/'result.json').write_text(json.dumps(dict(
            scope='actual production admission header; native/mirror API seams; CPU only',
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            header_sha256=hashlib.sha256((ROOT/'OptiScaler/misc/NrdBridgeDescriptorAdmission_Dx12.h').read_bytes()).hexdigest(),
            executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(), rows=rows), indent=2)+'\n')
        completed.check_returncode()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    if parser.parse_args().run:
        run()
