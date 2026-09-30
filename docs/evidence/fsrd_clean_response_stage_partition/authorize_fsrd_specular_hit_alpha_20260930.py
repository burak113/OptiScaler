"""CPU-only exact preparation and independently sealed R/RZ gates; no SDK invocation."""
import sys
sys.dont_write_bytecode = True
import argparse, json, subprocess
from pathlib import Path
from authorize_fsrd_clean_converter_v4_20260930 import ROOT, sha, pin, verify, read

PREP = ROOT/'tools_tmp/fsrd_clean_specular_hit_alpha_contrast_preparation_20260930'
TARGET = ROOT/'tools_tmp/fsrd_specular_hit_alpha_root_authorization_20260930.json'
EXPECTED = {
    'prelaunch_ready_manifest.json':'8fa973050ac156ef3895e9c7e9deaf61fe0dfa3552626d8d0eb9eaea5c1d2295',
    'pre_native_freeze.json':'5afd215fc53a4175dbca1063fb735afb8eede838727abb9cb336a86b0cbb6ae3',
    'registration.json':'fb300d09a738fed1b946b0e14c64c91a2c73c1f9eebe418aed1cd069d12237b2',
    'completion_manifest.json':'b025ca512ceb2f8a89633346aa41d60633116d295e851967fa874f78355bc81d',
}

def verify_seal(path):
    data = read(path)
    assert data.get('self_entry_excluded') or data.get('self_excluded')
    checked = {}
    for key, records in data.items():
        if isinstance(records,list) and records and all(isinstance(r,dict) and {'path','bytes','sha256'} <= set(r) for r in records):
            checked[key] = verify(records)
    assert checked, 'No source identities in manifest'
    for index, inherited in enumerate(data.get('inherited_source_manifests', [])):
        source = read(inherited['path'])
        if 'records_key' in inherited:
            rows = source[inherited['records_key']]
            assert len(rows) == inherited['record_count']
            checked['inherited_'+str(index)] = verify(rows)
        else:
            checked['inherited_'+str(index)] = verify_seal(inherited['path'])
    return checked

def main():
    parser = argparse.ArgumentParser()
    for name in ('review','review-sha256','review-manifest','review-manifest-sha256','rz-review','rz-review-sha256','rz-manifest','rz-manifest-sha256','rz-expected-status'):
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    assert not TARGET.exists(), 'Preserve prior authorization'
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip() == 'ffxD-experimental-alpha'
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip() == '50e376ce8c99739efbd9a86055dbe4995d50155e'
    assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip()
    for name, expected in EXPECTED.items():
        assert sha(PREP/name) == expected, name
    for path, expected in ((args.review,args.review_sha256),(args.review_manifest,args.review_manifest_sha256),(args.rz_review,args.rz_review_sha256),(args.rz_manifest,args.rz_manifest_sha256)):
        assert sha(path) == expected, path
    review, rz = read(args.review), read(args.rz_review)
    assert review['status'] == 'READY_FOR_ROOT_SPECULAR_HIT_ALPHA_CONTRAST_AUTHORIZATION_SUBJECT_TO_FINAL_RZ_GATE' and review['blocking_findings'] == []
    assert rz['status'] == args.rz_expected_status and args.rz_expected_status.startswith('PASSED_') and rz['blocking_findings'] == []
    rz_comparison = ROOT/'tools_tmp/fsrd_clean_roundtrip_diffuse_alpha_zero_preparation_20260930/alpha_zero_comparison.json'
    comparison = read(rz_comparison)
    assert comparison['color_RGB_alpha_caveat_closed_for_this_graph'] and len(comparison['pairs']) == 6
    assert all(o['full_RGBA_serialized_bits_exact'] for p in comparison['pairs'] for o in p['outputs'])
    ready, frozen, reg, manifest = (read(PREP/name) for name in ('prelaunch_ready_manifest.json','pre_native_freeze.json','registration.json','completion_manifest.json'))
    assert ready['actual_native_GPU_build_scores'] == frozen['actual_native_GPU_build_scores'] == manifest['actual_native_GPU_build_scores'] == 0
    assert ready['all4_runtime_cases_fresh'] and ready['not_execution_authorization']
    assert len(ready['files']) == 59 and len(frozen['files']) == 58 and len(manifest['files']) == 62
    assert len(ready['external_sources']) == len(frozen['external_sources']) == len(manifest['external_records']) == 26
    checked = dict(ready=verify_seal(PREP/'prelaunch_ready_manifest.json'),freeze=verify_seal(PREP/'pre_native_freeze.json'),preparation=verify_seal(PREP/'completion_manifest.json'),review=verify_seal(args.review_manifest),RZ=verify_seal(args.rz_manifest))
    inherited_clean = next(r for r in manifest['external_records'] if Path(r['path']).name == 'completion_manifest_final.json')
    checked['expanded_clean_native_sources'] = verify_seal(inherited_clean['path'])
    R = reg['pending_external_execution_gates']['R']
    assert R['status'] == 'PASSED_SEALED'
    verify([R['review'],R['seal']])
    assert read(R['review']['path'])['status'] == 'PASSED_CLEAN_ROUNDTRIP_EVIDENCE_AND_EXACT_SINGLETON_METRIC_REVIEW'
    assert read(R['review']['path'])['blocking_findings'] == []
    checked['R_seal'] = verify_seal(R['seal']['path'])
    assert reg['fixed_order'] == [c['tag'] for c in reg['cases']] == ['A0_r0','A10_r0','A10_r1','A0_r1']
    assert [c['specular_input_A'] for c in reg['cases']] == [0,10,10,0]
    assert reg['input_upload_counts'] == [1]*7 and reg['input_formats'] == [41,10,24,28,28,10,10]
    assert reg['runner']['sha256'] == '3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2'
    assert reg['provider']['sha256'] == '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    assert reg['guard']['sha256'] == 'b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
    assert not reg['quality_accepted'] and not reg['composition_authorized']
    runtime_names = ('resource_guard.json','stdout.log','stderr.log','stage_events.jsonl','recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin','observed_frame_indices.bin','output_presence.bin','dispatch_controls.bin','diffuse.bin','specular.bin','native_work_accounting.json','executor_attempt.json')
    absent = [PREP/'execution_results.json',PREP/'raw_comparisons.json']
    for case in reg['cases']:
        folder = Path(case['job']).parent.resolve()
        assert folder.is_dir() and folder.parent == (PREP/'planned_native').resolve()
        assert case['command'] == [reg['runner']['path'],case['job']]
        assert case['source_frame_indices'] == list(range(64)) and case['input_upload_counts'] == [1]*7
        absent += [folder/name for name in runtime_names]
    assert all(not path.exists() for path in absent), 'Prior native runtime; no retry'
    temp = (PREP/'execution_TEMP').resolve()
    assert temp.drive.upper() == 'F:' and PREP.resolve() in temp.parents and temp.is_dir() and not any(temp.iterdir())
    result = dict(status='ROOT_AUTHORIZED_FOUR_FRESH_SPECULAR_HIT_ALPHA_CONTEXTS_ONCE',
        command=['F:/OptiRevelations/OptiScaler/tools_tmp/albedo_stage1_venv/Scripts/python.exe',str(PREP/'run_native.py'),'--execute-native'],
        preparation_pins=[pin(PREP/name) for name in EXPECTED],review=pin(args.review),review_manifest=pin(args.review_manifest),RZ_review=pin(args.rz_review),RZ_manifest=pin(args.rz_manifest),RZ_comparison=pin(rz_comparison),R_gate=R,root_verifier=pin(__file__),checked_records=checked,absent_runtime_paths=len(absent),
        reconsideration='R and RZ actual color RGB equal encoded raw bits. Extra mature Tclean gain/DC departure is not explained by this converter/composition static graph; numeric specular-hit alpha sensitivity test remains warranted. This does not identify a private SDK mechanism or game cause.',
        fixed_order=reg['fixed_order'],doses=[0,10,10,0],planned_only_native_contexts=4,planned_only_successful_API=256,planned_only_queued_completed_RR=256,current_actual_new_native_API_GPU=0,
        previous_native_contexts=410,previous_successful_API=21818,previous_queued_completed_RR=21810,previous_recorded_only_discards=8,previous_no_API_omissions_separate=4,
        environment='Driver sets owned F TEMP/TMP; root sets OPENBLAS_NUM_THREADS=1',guard_policy=reg['guards'],CPU_analysis_after_four_accepted='Exact frozen analyze_raw_cpu.py --analyze-raw once; descriptive raw differences only',
        limitations=reg['treatment'],no_retries=True,composition_GPU_authorized=False,production_changes=False,game_run=False,quality_accepted=False)
    with TARGET.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(authorization=pin(TARGET),checked_records=checked,actual_new_native_API_GPU=0)))

if __name__ == '__main__':
    main()
