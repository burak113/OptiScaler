"""CPU-only one query-context authorization; no provider load, query or GPU launch."""
import sys
sys.dont_write_bytecode = True
import argparse, json, subprocess
from pathlib import Path
from authorize_fsrd_clean_converter_v4_20260930 import ROOT, sha, pin, read, verify
from authorize_fsrd_specular_hit_alpha_20260930 import verify_seal

PREP = ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_preparation_20260930'
TARGET = ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_root_authorization_20261001.json'
EXPECTED = {
    'registration.json':'395b85ba6b02456d253a5ba57bd2d525141bd2c0c693a87df96506e20bf47ab6',
    'pre_query_freeze.json':'5ddeb8978550a316dc858e7ac9f0807f2f5bb9ea934e952c8e58eb3b6bba7aae',
    'readiness.json':'d024a4520e73bf53840bbffd373c9dc3c8c5ba705db90ee1e11c495ba334b262',
    'completion_manifest.json':'8606b76754f334665026d41c6815d3609de019808dc3961b0ec72c47d60e5f5d',
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
    assert review['status'] == 'READY_FOR_ROOT_PUBLIC_DEFAULT_SCALAR_QUERY_AUTHORIZATION' and review['blocking_findings'] == []
    ready, reg, frozen, manifest = (read(PREP/name) for name in ('readiness.json','registration.json','pre_query_freeze.json','completion_manifest.json'))
    assert ready['blocking_findings'] == [] and ready['query_EXE_invocations'] == ready['actual_contexts_queries_RRDispatch'] == 0
    assert ready['CPU_compile_invocations'] == 1 and ready['compiler_exit'] == ready['compiler_warnings'] == 0
    assert ready['mature_guard_byte_exact'] and ready['canonical_guard_loader_byte_exact'] and ready['SDK_signature_valid'] and ready['all_query_runtime_absent'] and ready['ownedF_TEMP_empty']
    assert len(frozen['owned']) == 70 and len(manifest['owned']) == 72 and len(frozen['external_sources']) == len(manifest['external_sources']) == 15
    checked = dict(freeze=verify_seal(PREP/'pre_query_freeze.json'),preparation=verify_seal(PREP/'completion_manifest.json'),review=verify_seal(args.review_manifest))
    assert reg['query_keys'] == [6,1,2,3,4,5] and reg['command'] == [str(PREP/'fsrd_default_query.exe'),reg['job']]
    assert reg['EXE']['sha256'] == 'cb1db4d103665c49d1e956222d69b9c407903d2290e25928593d2e95bb259b27'
    assert reg['source']['sha256'] == '68c4b30fd9d2a9805a235cc45996f60461217bc2e677e287a62bfbabafaa36e5'
    assert reg['provider']['sha256'] == '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
    assert reg['actual_CPU_compiles'] == 1 and reg['query_EXE_invocations'] == 0 and all(v == 0 for v in reg['actual_query_work'].values())
    assert reg['planned_only_if_completed'] == dict(fresh_created_contexts=1,successful_default_queries=6,returned_default_queries=6,successfully_destroyed_contexts=1,RRDispatch_API=0,Configure_API=0,caller_Execute=0)
    verify([reg['provider'],reg['source'],reg['EXE'],reg['design'],reg['schema'],reg['provider_signature']])
    folder = Path(reg['job']).parent.resolve()
    assert folder == (PREP/'planned_query').resolve() and folder.is_dir()
    assert all(PREP.resolve() in Path(path).resolve().parents and not Path(path).exists() for path in reg['runtime_paths'])
    temp = (PREP/'execution_TEMP').resolve()
    assert temp.drive.upper() == 'F:' and PREP.resolve() in temp.parents and temp.is_dir() and not any(temp.iterdir())
    result = dict(status='ROOT_AUTHORIZED_ONE_DEFAULT_SCALAR_QUERY_CONTEXT',
        registration_sha256=EXPECTED['registration.json'],freeze_sha256=EXPECTED['pre_query_freeze.json'],command=reg['command'],independent_prelaunch_review=pin(args.review),independent_prelaunch_review_manifest=pin(args.review_manifest),
        authorized_driver=['F:/OptiRevelations/OptiScaler/tools_tmp/albedo_stage1_venv/Scripts/python.exe',str(PREP/'run_query.py'),'--execute-query','--authorization',str(TARGET)],
        preparation_pins=[pin(PREP/name) for name in EXPECTED],root_verifier=pin(__file__),checked_records=checked,absent_runtime_paths=len(reg['runtime_paths']),
        planned_only_new_query_contexts_created_destroyed=1,planned_only_successful_public_default_queries=6,authorized_new_RRDispatch_API=0,authorized_Configure_API=0,authorized_caller_Execute=0,actual_new_contexts_queries_RRDispatch=0,
        previous_RR_workload_native_contexts=414,previous_all_completed_SDK_contexts=414,previous_successful_RR_API_recordings=22074,previous_queued_completed_RR=22066,previous_recorded_only_discards=8,previous_no_API_omissions_separate=4,clean_pipeline_helpers_completed=516,
        required_environment='Driver sets owned F TEMP/TMP; root sets OPENBLAS_NUM_THREADS=1',guard_policy=reg['guard'],
        limits='Only six public default scalar queries in one fresh context. SDK private callback warnings unavailable/unknown and provider internal GPU work unknown. Failed/ambiguous ownership is preserved; process exit is not Destroy/quiescence proof. No guessed scalar values or settings application.',
        no_retries=True,no_settings_applied=True,no_new_model=True,production_changes=False,game_run=False,quality_accepted=False)
    with TARGET.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(authorization=pin(TARGET),checked_records=checked,actual_new_contexts_queries_RRDispatch=0)))

if __name__ == '__main__':
    main()
