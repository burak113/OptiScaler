"""New actual-wrapper split regression. Run only through the shared GPU-lock task wrapper."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp, dxc
from test_fsrd_nrd_bridge_rr import bounded_run, DLL
import test_fsrd_nrd_owned_output as source_contracts


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('mock', 'real', 'both'), required=True)
    args = parser.parse_args()
    os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    source_contracts.main()
    work = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15c-rr/tests/owned-output-native'))
    report = Path('E:/FSRD/sol_batch/15c-rr/tests') / work.name
    work.mkdir(parents=True, exist_ok=True)
    report.mkdir(parents=True, exist_ok=True)
    modes = ('mock', 'real') if args.mode == 'both' else (args.mode,)
    for mode in modes:
        assert not (report / (mode + '-result.json')).exists(), 'Use a fresh task run name; preserve prior result/negative evidence'
    os.environ['FSRD_CPP_CACHE'] = str(work / 'cache')
    (work / 'pch.h').write_text('#pragma once\n', encoding='utf-8')
    for source, prefix, symbol in (
        ('nrd_bridge_consumer_fixture.hlsl', 'consumer', 'ConsumerShaderBytes'),
        ('nrd_bridge_owned_consumer36_fixture.hlsl', 'owned_consumer36', 'OwnedConsumer36ShaderBytes'),
    ):
        binary = work / (prefix + '.cso')
        subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                        str(HERE / source), '-Fo', str(binary)], check=True)
        (work / (prefix + '_shader.h')).write_text('const unsigned char ' + symbol + '[] = {' +
                                                  ','.join(str(v) for v in binary.read_bytes()) + '};\n', encoding='utf-8')
    exe = work / 'nrd_bridge_owned_output_fixture.exe'
    compile_cpp(HERE / 'nrd_bridge_owned_output_fixture.cpp', exe, ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib'],
                [work, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/streamline',
                 ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    for mode in modes:
        text, peak, elapsed, log = bounded_run([str(exe), '--' + mode], work / mode)
        passed = re.search(r'^PASS owned_checks=(\d+).*$', text, re.M)
        assert passed and 'debug_errors=0 debug_warnings=0' in passed.group(0)
        for required in (
            'owned_success cases=16 profiles=2 binding_routes=2 live_flags=4 no_early_title_write=1 exact_rr_codec=1 opaque_alpha=1 single_use=1',
            'owned_reject cases=5 cross_list_unsupported=1 guard_actions=0 exact_title_preservation=1 deferred_destroy=1',
            'owned_discard native_reset_aba=1 fresh_context=1 old_generation_abandon_safe=1 debug_checked=1',
            'owned_desired old_commit_immutable=1 next_chain_apply=1 requested_reset=1',
            'owned_observer after_wrapper_retirement=1 separate_copy_lease=1 exact_destroy=1',
        ):
            assert required in text, required
        if mode == 'mock':
            assert 'owned_provider_failure actual_partial_writes=1 no_success_lease=1 exact_title_preservation=1' in text
        sources = [HERE / 'nrd_bridge_owned_output_fixture.cpp', HERE / 'nrd_bridge_owned_consumer36_fixture.hlsl',
                   ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp',
                   ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h',
                   ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdBridgePureCommit_Shader.h']
        result = dict(mode=mode, native_checks=int(passed.group(1)), native_summary=passed.group(0),
                      executable=str(exe), executable_sha256=sha(exe), native_log=str(log),
                      peak_resident_bytes=peak, seconds=elapsed,
                      sources={str(p): sha(p) for p in sources},
                      scope='actual production RRWrapper split; proxy seam only; no native NRD output, no quality/FPS claim',
                      rows=[line for line in text.splitlines() if line.startswith('owned_')])
        if mode == 'real':
            result.update(provider_path=str(DLL), provider_sha256=sha(DLL),
                          provider_binary_scope='explicit fixture LoadLibraryEx path; production per-context routing witness tested separately by Trace')
        (report / (mode + '-result.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
