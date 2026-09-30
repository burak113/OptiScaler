"""Seal post-observation preparation only; never launch the six pending cases."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def verify(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    prep=json.loads((HERE/'preparation_completion_manifest.json').read_text());verify(prep['files']);verify(prep['external_sources'])
    partial=json.loads((HERE/'partial_v1_completion_manifest.json').read_text());verify(partial['files'])
    freeze=json.loads((HERE/'remaining_v2_pre_native_freeze.json').read_text());verify(freeze['files'])
    old=json.loads((HERE/'evidence/results.json').read_text());reg=json.loads((HERE/'registration.json').read_text());amend=json.loads((HERE/'remaining_v2_registration.json').read_text())
    assert old['status']=='failed_preserved'and old['metadata_accepted_native_contexts']==1 and list(old['cases'])==reg['mode_order'][:2]
    assert amend['post_observation']and amend['remaining_case_tags']==reg['mode_order'][2:]and amend['actual_new_native_contexts']==0
    for c in reg['cases'][2:]:
        f=HERE/'evidence'/c['tag']
        for name in('resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','dispatch_controls.bin','queued_dispatch_controls.bin','native_work_accounting.json','recorded_frame_indices.bin','observed_frame_indices.bin','omitted_API_frame_indices.bin','output_presence.bin'):
            assert not(f/name).exists(),str(f/name)
    assert not(HERE/'evidence/remaining_v2_results.json').exists()and not(HERE/'combined_v2_raw_comparisons.json').exists()
    check=json.loads((HERE/'remaining_v2_CPU_check.json').read_text());assert check['status']=='passed'and check['tests']==11 and check['SIMULATED_NOT_NATIVE_EVIDENCE']
    assert check['script_sha256']==sha(HERE/'check_remaining_v2_cpu.py')and check['policy_sha256']==sha(HERE/'diagnostic_warning_policy_v2.py')and check['driver_sha256']==sha(HERE/'run_remaining_native_v2.py')
    verification={'schema':'post-observation-remaining6-V2-preparation-CPU-verification-v1','status':'prepared_NOT_AUTHORIZED_TO_RUN',
        'original199_preparation_and23external_verified':True,'original_first2_all_sealed_bytes_verified':True,
        'V2_frozen_files_verified':len(freeze['files']),'original_results_status':'failed_preserved','original_V1_metadata_accepted_contexts':1,
        'original_V1_actual_counts':amend['original_V1_actual_counts'],'planned_new_counts':{'contexts':6,'API':381,'queued':378,'SDKdiscard':3,'noAPIomit':3},
        'actual_new_native_contexts':0,'actual_new_API_RR_recordings':0,'actual_new_queued_RR_dispatches':0,
        'only6unattempted_original_cases_no_existing_guard_or_output':True,'unchanged_CPP_EXE_inputs_controls_guard_accounting':True,
        'diagnostic_CPU_check':identity(HERE/'remaining_v2_CPU_check.json'),'SIMULATED_cases':11,'quality_accepted':False,
        'remaining_V2_registration':identity(HERE/'remaining_v2_registration.json'),'remaining_V2_freeze':identity(HERE/'remaining_v2_pre_native_freeze.json'),
        'warning_policy':'noAPI0or1 exactknownwarning bytes; recordstrict0; allSDKerrors/D3Derrorswarnings0. Post-observation diagnostic retention only; warning counts retained.',
        'new_run_gate':'Independent SolHigh V2 readiness and root newauthorization for exactlysix pending cases; no retry or native launch in preparation.'}
    save(HERE/'remaining_v2_preparation_verification.json',verification)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'remaining_v2_preparation_completion_manifest.json',{'schema':'immutable-post-observation-remaining6-V2-preparation-completion-v1','status':'prepared_NOT_AUTHORIZED_TO_RUN',
        'original_V1_actual_contexts_reference_only':2,'original_V1_metadata_accepted_contexts':1,'actual_new_native_contexts':0,'actual_new_API_RR_recordings':0,
        'planned_new_native_contexts':6,'planned_new_API_RR_recordings':381,'planned_new_queued_RR_dispatches':378,'planned_new_SDK_record_discards':3,'planned_new_no_API_omissions':3,
        'new_executor':identity(HERE/'run_remaining_native_v2.py'),'preserved_first2_manifest':identity(HERE/'partial_v1_completion_manifest.json'),'files':[identity(p)for p in files],'external_sources':prep['external_sources']})
    print(json.dumps({'verification':identity(HERE/'remaining_v2_preparation_verification.json'),'manifest':identity(HERE/'remaining_v2_preparation_completion_manifest.json'),'owned_files':len(files),'actual_new_native_contexts':0}),flush=True)
if __name__=='__main__':main()
