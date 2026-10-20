"""Material writer -> actual native coordinator -> signed AMD provider regression.

Synthetic title PSOs and explicit native-readiness adapters; no game-quality claim.
Run through the shared GPU-lock wrapper.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import test_fsrd_nrd_native_transactions as native
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_bridge_rr import bounded_run, DLL


def main():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    _, command, keywords = native.prepare(out)
    source = Path(command[0]).read_text()
    header = HERE/'fsrd_nrd_native_material_e2e_case.h'
    include = '#include "'+header.as_posix()+'"'
    assert source.count(include) == 1
    material = header.read_text()
    for name in ('ResourceCreated', 'RootCreated', 'HeapCreated', 'PipelineCreated'):
        material = material.replace('FrameSurvey::'+name+'(', 'NativeFixture'+name+'(')
    source = source.replace(include, material)
    marker = 'int main(int argc,char** argv)try{'
    assert source.count(marker) == 1
    source = source.replace(marker, 'int UnusedNativeTransactionMain(int argc,char** argv)try{')
    fixture = HERE / 'fsrd_nrd_material_native.cpp'
    path, exe = out/'material_native.cpp', out/'material_native.exe'
    path.write_text(source + '\n' + fixture.read_text(), encoding='utf-8')
    os.environ['CL'] = os.environ.get('CL', '') + ' /bigobj'
    compile_cpp(path, exe, *command[2:], **keywords)
    _, peak, elapsed, log = bounded_run([str(exe), str(out), str(DLL)], out/'native_run')
    value = json.loads((out/'material-native-result.json').read_text())
    assert value['debug_errors'] == value['debug_warnings'] == 0
    value.update(elapsed_seconds=elapsed, peak_resident_bytes=peak, log=str(log),
                 exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
    (out/'material-native-result.json').write_text(json.dumps(value, indent=2)+'\n')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
