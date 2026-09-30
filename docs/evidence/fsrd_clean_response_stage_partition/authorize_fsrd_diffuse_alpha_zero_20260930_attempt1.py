"""CPU root pin/absence verification only; no helper, GPU or SDK invocation."""
import sys
sys.dont_write_bytecode = True
import argparse, json, subprocess
from pathlib import Path
from authorize_fsrd_clean_converter_v4_20260930 import ROOT, sha, pin, verify, read

PREP = ROOT/'tools_tmp/fsrd_clean_roundtrip_diffuse_alpha_zero_preparation_20260930'
TARGET = ROOT/'tools_tmp/fsrd_diffuse_alpha_zero_root_authorization_20260930.json'
EXPECTED = {
    'readiness.json':'1eab6425998c218391ce2442322e23f9120e03bb6fce3f36d78ec7b2958726c0',
    'completion_manifest.json':'143bcea870991f0ed49fa2eae4331cdc281f920b2f1db0ba40a8164bed1b20a8',
    'registration.json':'a8be39dd76218594e890c73aa9cd04343a49e0b2a4b81a052c48514f6cb4eb0b',
    'pre_execution_freeze.json':'757075d9715495446d7f8a5b28349098de918a87244c7499ef6c99f78dacb950',
}

def main():
    parser = argparse.ArgumentParser()
    for name in ('review','review-sha256','review-manifest','review-manifest-sha256'):
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    assert not TARGET.exists(), 'Preserve prior authorization'
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip() == 'ffxD-experimental-alpha'
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip() == '50e376ce8c99739efbd9a86055dbe4995d50155e'
    assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip()
    for name, expected in EXPECTED.items():
        assert sha(PREP/name) == expected, name
    assert sha(args.review) == args.review_sha256 and sha(args.review_manifest) == args.review_manifest_sha256
    review = read(args.review)
    assert review['status'] == 'READY_FOR_ROOT_DIFFUSE_ALPHA_ZERO_AUTHORIZATION' and review['blocking_findings'] == []
    ready = read(PREP/'readiness.json')
    assert ready['blockers'] == [] and ready['actual_preparation_GPU_native_build_scores'] == 0
    assert ready['planned_helpers'] == 2 and ready['planned_new_SDK_API'] == 0
    assert ready['six_inherited_SIM_passed'] == 6 and ready['only_t2_A_control'] and ready['all_runtime_absent']
    assert ready['prior_R_independent_gate']['passed_at_freeze']
    manifest, frozen, reg = (read(PREP/name) for name in ('completion_manifest.json','pre_execution_freeze.json','registration.json'))
    assert manifest['self_excluded'] and frozen['self_excluded']
    assert len(manifest['records']) == 74 and len(frozen['owned']) == 72 and len(frozen['external_sources']) == 41
    checked = dict(manifest_records=verify(manifest['records']),freeze_owned=verify(frozen['owned']),freeze_external_sources=verify(frozen['external_sources']))
    rm = read(args.review_manifest)
    assert rm.get('self_entry_excluded') or rm.get('self_excluded')
    for key, records in rm.items():
        if isinstance(records,list) and records and all(isinstance(r,dict) and {'path','bytes','sha256'} <= set(r) for r in records):
            checked['review_'+key] = verify(records)
    assert any(key.startswith('review_') for key in checked), 'No review identities verified'
    for index, inherited in enumerate(rm.get('inherited_source_manifests', [])):
        inherited_records = read(inherited['path'])[inherited['records_key']]
        assert len(inherited_records) == inherited['record_count'] == 2252
        checked['review_inherited_expanded_'+str(index)] = verify(inherited_records)
    assert [(job['frame'],job['arm']) for job in reg['jobs']] == [(0,'RZ0'),(0,'RZ1')]
    assert reg['planned_helpers_only_if_completed'] == reg['planned_explicit_shader_Dispatches_only_if_completed'] == 2
    assert reg['planned_output_files_only_if_completed'] == 6 and reg['planned_SDK_API'] == reg['actual_helpers_GPU_native_build_scores'] == 0
    absent = [PREP/name for name in ('execution_results.json','alpha_zero_comparison.json','execution_TEMP')]
    for job in reg['jobs']:
        folder = Path(job['job']).parent
        assert folder.is_dir() and PREP in folder.parents
        assert job['command'] == [str(PREP/'fsrd_gpu_runner.exe'),job['job']]
        assert job['repetitions'] == job['explicit_shader_Dispatches_planned_only'] == 1 and len(job['outputs']) == 3
        absent += [folder/name for name in ('resource_guard.json','stdout.log','stderr.log')]
        absent += [Path(out['path']) for out in job['outputs']]
    assert all(not path.exists() for path in absent), 'Preserve prior runtime; no retry'
    record = dict(status='ROOT_AUTHORIZED_EXACT_DIFFUSE_ALPHA_ZERO_ONCE',
        authorized_command=['F:/OptiRevelations/OptiScaler/tools_tmp/albedo_stage1_venv/Scripts/python.exe',str(PREP/'run_alpha_zero_only.py'),'--execute-alpha-zero-only'],
        exact_preparation_pins=[pin(PREP/name) for name in EXPECTED],independent_review=pin(args.review),independent_review_manifest=pin(args.review_manifest),root_verifier=pin(__file__),checked_records=checked,absent_runtime_paths=len(absent),
        planned_only_helper_children=2,planned_only_explicit_helper_shader_Dispatches=2,planned_only_outputs=6,authorized_new_native_contexts=0,authorized_new_FFX_API=0,actual_new_helper_GPU_native_API=0,
        authorized_CPU_analysis='Exact frozen analyze_alpha_zero_bits_cpu.py --analyze-alpha-zero-bits once after two accepted jobs; six unordered pairs RZ0/RZ1/R0/R1 bits-only, no new scorer/model',
        native_cumulative_contexts=410,native_cumulative_API=21818,native_cumulative_queued_completed_RR=21810,native_recorded_only_discards=8,native_no_API_omissions_separate=4,
        required_environment='Driver exclusively creates owned F execution_TEMP and sets TEMP/TMP/OPENBLAS_NUM_THREADS=1',
        limitations=reg['limitations'],no_retries=True,production_changes=False,game_run=False,quality_accepted=False)
    with TARGET.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(record,stream,indent=2,allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(authorization=pin(TARGET),checked_records=checked,actual_helper_GPU_native_API=0)))

if __name__ == '__main__':
    main()
