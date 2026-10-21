"""Run job10 CPU mechanics and verify separately recorded quality rejection.

Exit 0 means the mechanical checks completed, never native/GPU/quality adoption.
Use --with-frozen and --with-quality for fresh expensive suite execution; by
default their delivered fresh receipts are hash-verified, not relabelled as reruns.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
BASE = '5fe436dd9a21cb9cc69dec371521a055c9af049d'
PACKAGE = REPO/'research/astra20261020'
sys.path.insert(0, str(HERE/'portable'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_snapshot():
    roots = ['research/astra20261020/candidates', 'research/astra20261020/audit_round2',
        'research/astra20261020/portable',
        'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h',
        'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp', 'OptiScaler/OptiScaler.vcxproj']
    tree = subprocess.check_output(['git','ls-tree','-r','-z',BASE,'--',*roots], cwd=REPO)
    found = {}
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t',1)
        mode, kind, blob = metadata.split()
        assert kind == b'blob', 'unexpected immutable submodule'
        path = name.decode('utf-8')
        data = (REPO/path).read_bytes()
        actual_blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        assert actual_blob == blob.decode(), 'frozen file differs from tag: '+path
        found[path] = hashlib.sha256(data).hexdigest()
    assert found, 'empty frozen inventory'
    return found


def source_snapshot():
    return {p.relative_to(HERE).as_posix(): sha(p) for p in sorted(HERE.rglob('*'))
        if p.is_file() and 'evidence' not in p.parts and '__pycache__' not in p.parts
        and (p.suffix in ('.py','.h','.cpp','.hlsl','.patch') or p.name in ('PROTOCOL.json','patch_manifest.json'))}


def verify_saved_evidence():
    frozen_dir = HERE/'evidence/frozen_cpu'
    frozen = json.loads((frozen_dir/'execution.json').read_text(encoding='utf-8'))
    assert frozen['passed'] and frozen['intake_unchanged_after_execution']
    assert not frozen['quality_accepted'] and not frozen['gpu_executed']
    assert frozen['runner_sha256'] == sha(PACKAGE/'audit_round2/run_cpu.py')
    for check in frozen['commands']:
        assert check['passed'] and check['exit_code'] == check['expected_exit_code']
        assert sha(frozen_dir/(check['name']+'.txt')) == check['log_sha256']
    quality_dir = HERE/'quality/evidence/full'
    quality = json.loads((quality_dir/'execution.json').read_text(encoding='utf-8'))
    assert quality['mechanical_experiment_execution_pass'] and quality['immutable_files_unchanged']
    assert quality['all_variants_rejected'] and not quality['quality_accepted']
    assert quality['quality_gate_exit_code'] == 1 and not quality['gpu_executed']
    assert quality['protocol_sha256_before'] == sha(HERE/'quality/PROTOCOL.json')
    for name in ('experiment.py','run_quality.py'):
        assert quality['source_hashes'][name] == sha(HERE/'quality'/name)
    assert quality['source_hashes']['frozen_native_colour.py'] == sha(PACKAGE/'candidates/03-native-colour/native_colour.py')
    for name, expected in quality['output_sha256'].items():
        assert sha(quality_dir/name) == expected, name
    return dict(action='verified existing fresh receipts and bound sources/outputs; no suite re-execution',
        frozen_aggregate_stages=len(frozen['commands']), frozen_receipt_sha256=sha(frozen_dir/'execution.json'),
        quality_receipt_sha256=sha(quality_dir/'execution.json'),
        quality_numeric_boundary_cases=quality['holdout_numeric_boundary_cases'],
        quality_noise_sequences=quality['holdout_noise_sequences'], quality_accepted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--with-frozen', action='store_true')
    parser.add_argument('--with-quality', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    for immutable in (PACKAGE/'candidates', PACKAGE/'portable', PACKAGE/'audit_round2', REPO/'OptiScaler'):
        if out == immutable or immutable in out.parents:
            parser.error('output must not be inside immutable inputs or production sources')
    if out == HERE or (HERE in out.parents and HERE/'evidence' not in out.parents):
        parser.error('within this delivery, use an evidence subdirectory as output')
    out.mkdir(parents=True, exist_ok=True)
    before, sources = frozen_snapshot(), source_snapshot()
    receipt = dict(schema='astra10-local-mechanical-checks-v1', started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        base_commit=BASE, command=sys.argv, platform=platform.platform(), python=platform.python_version(),
        executor='current host running run_checks.py', quality_accepted=False, gpu_executed=False,
        native_windows_compiled=False, shader_compiled=False, commands=[], source_sha256=sources)

    def execute(name, arguments, expected=0, assertion=None):
        command = [sys.executable,'-B',*map(str,arguments)]
        start = time.perf_counter()
        process = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding='utf-8', errors='replace',
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
        log = out/(name+'.txt')
        combined = process.stdout+process.stderr
        log.write_text(combined, encoding='utf-8')
        okay = process.returncode == expected and (assertion is None or assertion in combined)
        counts = re.findall(r'Ran (\d+) tests? in ', combined)
        receipt['commands'].append(dict(name=name, command=command, exit_code=process.returncode,
            expected_exit_code=expected, required_assertion=assertion, passed=okay,
            unittest_count=sum(map(int,counts)) if counts else None,
            elapsed_seconds=time.perf_counter()-start, log_sha256=sha(log)))
        print(json.dumps(dict(stage=name, passed=okay, exit=process.returncode)), flush=True)
        assert okay, name+' failed; see '+str(log)

    try:
        execute('packed_tests', ['-m','unittest','discover','-s',HERE/'tests','-p','test_packed.py','-v'])
        execute('quality_metrology', ['-m','unittest','discover','-s',HERE/'quality','-p','test_quality.py','-v'])
        execute('native_contract', [HERE/'native/run_contract_tests.py','--output',out/'native_contract'])
        cpp = json.loads((out/'native_contract/result.json').read_text(encoding='utf-8'))
        assert cpp['passed'] and len(cpp['checks']) == 5
        assert all(c['build_exit'] == 0 for c in cpp['checks'])
        assert all('FAIL:' in c['stderr'] for c in cpp['checks'][1:])
        receipt['native_contract_assertions'] = int(re.search(r'(\d+)', cpp['checks'][0]['stdout']).group(1))
        expected_messages = {
            'forced_off':'eligible RGB differs beyond half-ULP gate',
            'alpha_repack':'native alpha words changed',
            'truthy_evidence':'protected/invalid pixels changed',
            'wrong_row_pitch':'native alpha words changed',
            'missing_prefill':'padding/canary/inactive extent changed',
            'raw_over_selection':'protected/invalid pixels changed'}
        for mutant, message in expected_messages.items():
            execute('reject_'+mutant, [HERE/'portable/known_bad.py',mutant], 1, 'AssertionError: '+message)
        execute('scale_domain', [HERE/'review/check_scale_domain.py','--output',out/'scale_domain.json'])
        execute('host_patch', [HERE/'host/verify_patch.py','--output',out/'host_patch.json'])
        execute('fixtures', [HERE/'portable/package_fixtures.py','--output',out/'native-fixtures.zip',
            '--manifest',out/'fixture_manifest.json'])
        from package_fixtures import package
        with tempfile.TemporaryDirectory(prefix='astra10-fixture-repeat-') as temporary:
            repeated = package(Path(temporary)/'repeat.zip', Path(temporary)/'manifest.json')
        fixtures = json.loads((out/'fixture_manifest.json').read_text(encoding='utf-8'))
        assert repeated == fixtures, 'fixture archive is not byte-deterministic'
        receipt['fixtures'] = dict(cases=fixtures['cases'], archive_sha256=fixtures['archive_sha256'],
            archive_bytes=fixtures['archive_bytes'], deterministic_repeat_identical=True)
        receipt['verified_saved_evidence'] = verify_saved_evidence()
        if args.with_frozen:
            execute('fresh_frozen_aggregate', [PACKAGE/'audit_round2/run_cpu.py','--output',out/'fresh_frozen'])
        if args.with_quality:
            execute('fresh_quality_matrix', [HERE/'quality/run_quality.py','--output',out/'fresh_quality','--quality-gate'],1)
            fresh = json.loads((out/'fresh_quality/execution.json').read_text(encoding='utf-8'))
            assert fresh['mechanical_experiment_execution_pass'] and fresh['all_variants_rejected']
            assert not fresh['quality_accepted'] and fresh['quality_gate_exit_code'] == 1
        # On Linux, check honest capability reporting. Do not launch a Windows
        # compiler/GPU accidentally; explicit Windows commands have their own gates.
        if os.name != 'nt':
            execute('shader_unavailable', [HERE/'portable/gpu_shader.py','--output',out/'shader_pending'],2)
            execute('native_unavailable', [HERE/'review/run_native_smoke.py','--output',out/'native_pending'],2)
            for path in ('shader_pending','native_pending'):
                pending = json.loads((out/path/'execution.json').read_text(encoding='utf-8'))
                assert not pending['gpu_executed']
            receipt['pending_platform_checks'] = 'expected exit2; pending is not a passed GPU gate'
        assert before == frozen_snapshot(), 'immutable files changed during execution'
        assert sources == source_snapshot(), 'test source changed during execution'
        receipt.update(passed=True, immutable_files_checked=len(before), immutable_files_unchanged=True,
            immutable_inventory_sha256=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
            source_unchanged=True, status='cpu_mechanics_passed_quality_rejected_native_pending')
    except Exception as error:
        receipt.update(passed=False, status='failed', error=str(error))
    (out/'execution.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=receipt['passed'], status=receipt['status'], receipt=str(out/'execution.json'))))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
