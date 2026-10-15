"""Actual-host OFF-to-ON activation with already-bound Recon and cold restore flags."""
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
    fixture = Path(__file__).with_name('fsrd_nrd_hot_activation.cpp')
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
    for mode in ('root', 'table', 'table0', 'missing-table', 'native-indirect'):
        directory = out / mode
        directory.mkdir(parents=True, exist_ok=True)
        _, peak, elapsed, log = bounded_run([str(exe), str(directory), str(DLL), mode], directory / 'native_run')
        value = json.loads((directory / 'hot-activation-result.json').read_text())
        assert value['debug_errors'] == value['debug_warnings'] == 0
        if mode in ('missing-table', 'native-indirect'):
            assert value['provider_dispatches'] == value['native_submissions'] == 0
            expected = 'unsupported_native_indirect role=2' if mode == 'native-indirect' else 'gate=compute_restore reason=native_p1_or_p5_table_missing'
            assert expected in value['failure_reason']
        else:
            assert value['provider_dispatches'] == 4 and value['native_submissions'] == 5
            assert len(value['frames']) == 2 and all(v['native_filter_gpu_executions'] == 0 for v in value['frames'])
        value.update(elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(log))
        cases[mode] = value
    result = dict(cases=cases, native_checks=sum(v['native_checks'] for v in cases.values()), python_checks=15,
                  source_sha256=native.sha(source), fixture_sha256=native.sha(fixture), exe_sha256=native.sha(exe))
    (out / 'hot-activation-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
