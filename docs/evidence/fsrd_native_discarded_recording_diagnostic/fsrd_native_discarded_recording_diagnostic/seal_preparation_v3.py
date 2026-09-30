"""Verify preserved preparation and seal V3 accounting supplement; CPU only."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def main():
    original=json.loads((HERE/'preparation_completion_manifest.json').read_text());verify(original['files'])
    freezes={name:json.loads((HERE/name).read_text())for name in('pre_native_freeze.json','accounting_v2_pre_native_freeze.json','accounting_v3_pre_native_freeze.json')}
    for data in freezes.values():verify(data['files']);verify(data.get('external_sources',[]))
    reg=json.loads((HERE/'registration.json').read_text())
    v3reg=json.loads((HERE/'accounting_v3_registration.json').read_text())
    verify([v3reg[k]for k in('preserved_V1_registration','preserved_V1_freeze','preserved_V2_freeze','canonical_future_executor','accounting_module')])
    assert reg['preparation_only']and reg['actual_native_contexts']==0
    check=json.loads((HERE/'accounting_v3_cpu_check.json').read_text())
    assert check['status']=='passed'and check['cases']==6 and check['SIMULATED_NOT_NATIVE_EVIDENCE']
    assert check['actual_native_contexts']==check['actual_API_RR_recordings']==check['actual_queued_RR_dispatches']==0
    assert check['script_sha256']==sha(HERE/'check_accounting_v3_cpu.py')
    assert check['accounting_module_sha256']==sha(HERE/'native_work_accounting_v3.py')
    assert check['registration_sha256']==sha(HERE/'registration.json')
    for c in reg['cases']:
        folder=HERE/'evidence'/c['tag']
        for name in('resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','dispatch_controls.bin','output_presence.bin','observed_frame_indices.bin','recorded_frame_indices.bin','native_work_accounting.json'):
            assert not(folder/name).exists(),'Unexpected actual native artifact '+str(folder/name)
    assert not(HERE/'evidence/results.json').exists()
    for name in('run_native_v3.py','native_work_accounting_v3.py','check_accounting_v3_cpu.py','prepare_accounting_v3.py'):
        compile((HERE/name).read_text(),str(HERE/name),'exec')
    verification={'schema':'H2-accounting-V3-preparation-CPU-verification-v1','status':'passed_preparation_NOT_NATIVE_AUTHORIZATION',
        'preserved_historical_preparation_files_verified':len(original['files']),
        'preserved_historical_preparation_manifest':identity(HERE/'preparation_completion_manifest.json'),
        'all_original_V1_external_sources_frozen_and_verified':True,
        'freeze_files_verified':{name:len(data['files'])for name,data in freezes.items()},
        'source_and_EXE_unchanged':True,'source':identity(HERE/'fsrd_rr_discard.cpp'),'EXE':identity(HERE/'fsrd_rr_discard.exe'),
        'all56_raw_inputs_commands_controls_masks_indices_analysis_unchanged':True,
        'accounting_V3_registration':identity(HERE/'accounting_v3_registration.json'),
        'accounting_V3_freeze':identity(HERE/'accounting_v3_pre_native_freeze.json'),
        'canonical_future_executor':identity(HERE/'run_native_v3.py'),'accounting_V3_module':identity(HERE/'native_work_accounting_v3.py'),
        'SIMULATED_CPU_tests':identity(HERE/'accounting_v3_cpu_check.json'),'SIMULATED_CPU_cases':6,
        'V1_accounting_qualification':'Frozen V1 driver counted completed native work only after metadata/debug acceptance; it is preserved for review history and is superseded for execution.',
        'V2_accounting_qualification':'Frozen V2 module max across contradictory count claims could incorrectly call65 exact despite valid64 footer; preserved and superseded for execution.',
        'V3_accounting_rule':'Valid bounded pinned CPP final footer authoritative before metadata acceptance; invalid conflicting artifact claims retained. Without valid footer, only valid-prefix/capacity artifact lower bounds and unknown totals. Planned counts never fill observations.',
        'planned_native_contexts':8,'planned_successful_API_RR_recordings':462,'planned_discarded_API_RR_recordings':4,'planned_queued_RR_dispatches':458,
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
        'no_actual_native_guard_stdout_output_or_results_artifacts':True,
        'run_gate':'Preparation only; root authorization after independent source and bounded V3 accounting review.'}
    save(HERE/'preparation_cpu_verification_v3.json',verification)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'preparation_completion_manifest_v3.json',{'schema':'immutable-H2-preparation-completion-V3-accounting-v1',
        'status':'prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN','actual_native_contexts':0,
        'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
        'planned_native_contexts':8,'planned_successful_API_RR_recordings':462,'planned_discarded_API_RR_recordings':4,'planned_queued_RR_dispatches':458,
        'canonical_future_executor':identity(HERE/'run_native_v3.py'),
        'immutable_historical_manifest':identity(HERE/'preparation_completion_manifest.json'),
        'files':[identity(p)for p in files]})
    print(json.dumps({'verification':identity(HERE/'preparation_cpu_verification_v3.json'),
        'completion_manifest':identity(HERE/'preparation_completion_manifest_v3.json'),
        'frozen_package_files':len(files),'actual_native_contexts':0}),flush=True)
if __name__=='__main__':main()
