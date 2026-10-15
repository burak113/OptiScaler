"""Actual-host regression: runtime OFF must profile Consumers without starting RR.

Reuses the native transaction fixture's explicit shipping-role/Release-coverage
adapters. Exercises actual production coordinator, D3D detours and native GPU
forwarding in four fresh processes, including exact root and descriptor-table b6.
"""
from pathlib import Path
import json
import os

import test_fsrd_nrd_native_transactions as native
from test_fsrd_nrd_bridge_rr import bounded_run, DLL
from fsrd_toolchain import compile_cpp


def run():
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    exe, command, keywords = native.prepare(out)
    source = command[0]
    text = source.read_text()
    marker = 'int main(int argc,char** argv)try{'
    assert text.count(marker) == 1
    text = text.replace(marker, 'int PreservedNativeTransactionsMain(int argc,char** argv)try{')
    fixture = Path(__file__).with_name('fsrd_nrd_runtime_off.cpp')
    source.write_text(text + '\n' + fixture.read_text())
    prior_cl = os.environ.get('CL')
    os.environ['CL'] = ((prior_cl + ' ') if prior_cl else '') + '/bigobj'
    try:
        compile_cpp(*command, **keywords)
    finally:
        if prior_cl is None:
            os.environ.pop('CL', None)
        else:
            os.environ['CL'] = prior_cl
    cases = {}
    for mode in ('startup-root', 'startup-table', 'toggle-root', 'toggle-table'):
        directory = out / mode
        directory.mkdir(parents=True, exist_ok=True)
        _, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL), mode], directory / 'native_run')
        value = json.loads((directory / 'runtime-off-result.json').read_text())
        assert value['debug_errors'] == value['debug_warnings'] == 0
        assert value['provider_dispatches'] == value['contexts'] == value['denied_submissions'] == 0
        assert value['native_submissions'] == 101 and value['stale_actions_checked'] == 2
        assert value['perf_reports'] == 1 and value['perf_frames'] == 100
        value.update(elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log))
        cases[mode] = value
    result = dict(cases=cases, native_checks=sum(v['native_checks'] for v in cases.values()), python_checks=16,
                  source_sha256=native.sha(source), fixture_sha256=native.sha(fixture),
                  driver_sha256=native.sha(__file__), exe_sha256=native.sha(exe))
    (out / 'runtime-off-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
