"""Future sequential executor. This file is frozen for review and is NOT run in preparation."""
from pathlib import Path
import hashlib,json,struct,sys
sys.dont_write_bytecode=True
V1=Path(__file__).resolve().parent.parent
sys.path.append(str(V1))
import numpy as np
from native_resource_guard import run_guarded
from native_work_accounting import derive,COUNT_KEYS
from executor_evidence import safe_guard_load,fresh_runtime
HERE=Path(__file__).resolve().parent.parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with Path(p).open('w',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def check(records):
    for r in records:assert identity(r['path'])==r,r['path']
def main():
    if sys.argv[1:]!=['--execute-native']:raise RuntimeError('Preparation only. Root authorization after independent prelaunch review is required.')
    reg=json.loads((HERE/'registration.json').read_text());freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    assert reg['status']=='K1_command_list_rotation_NOT_AUTHORIZED_TO_RUN'
    check(freeze['files']);check(freeze['external_sources'])
    target=HERE/'evidence/results.json'
    if target.exists():raise ValueError('Preserve prior native attempt; no retry')
    for c in reg['cases']:
        folder=Path(c['command'][1]).parent
        assert folder==Path(c['native_runtime_folder'])
        assert fresh_runtime(folder)['all_absent'],'Preserve existing native runtime; no retry'
        assert not(HERE/'evidence'/c['tag']).exists(),'Preserve V3 case accounting'
    report={'schema':'K1-rotation-actual-native-stages-before-acceptance-V5-law','status':'running','registration_sha256':sha(HERE/'registration.json'),'freeze_sha256':sha(HERE/'pre_native_freeze.json'),
        'executor_invocations_started':0,'attempted_owned_children':0,'created_contexts_physical_lower_bound':0,'completed_contexts_physical_lower_bound':0,'created_contexts_confirmed':0,'completed_contexts_confirmed':0,'accepted_contexts':0,'counts':{q:0 for q in COUNT_KEYS},'cases':{},'unknown_total_children':0,'successful_unsubmitted_records_abandoned_on_exit':0,'exact_successful_not_submitted_records':0,
        'prior_H2_contexts_count_as_new':0,'quality_accepted':False,'game_run':False,'counts_qualification':'Current child plus globally reachable CPP stdout gives exact bounded terminal counters. Fresh checkpointed invocation with unavailable guard gives qualified physical lower bounds, process identity and totals unknown. Explicit no-child contributes0. Aggregate work checkpointed before guard/metadata/warning acceptance; if any totals unknown aggregate is a lower bound.'}
    def checkpoint():save(target,report)
    checkpoint()
    try:
        for c in reg['cases']:
            check(freeze['files']);check(freeze['external_sources']);folder=Path(c['command'][1]).parent;guard_error=None;returned=None
            fresh=fresh_runtime(folder);assert fresh['all_absent'],'Preserve existing native runtime; no retry'
            accounting_folder=HERE/'evidence'/c['tag'];accounting_folder.mkdir(parents=True,exist_ok=False)
            attempt={'invocation_started':True,'fresh_runtime_files_verified_absent':True,'case_command_matches':folder==Path(c['native_runtime_folder']),'before_guard_call_checkpointed':True,'command':c['command'],'fresh_runtime_evidence':fresh}
            save(accounting_folder/'executor_attempt.json',attempt)
            report['cases'][c['tag']]={'executor_attempt':attempt,'native_runtime_folder':str(folder),'accepted':False}
            report['executor_invocations_started']+=1;checkpoint()
            try:returned=run_guarded(c['command'],folder,timeout=reg['guard']['timeout_seconds'],maximum_working_set=reg['guard']['maximum_working_set_bytes'],minimum_available_memory=reg['guard']['minimum_available_memory_bytes'],interval=reg['guard']['sample_interval_seconds'])
            except BaseException as e:guard_error=e
            guard=safe_guard_load(folder,attempt,c['command'],returned)
            accounting=derive(folder,guard,c);save(accounting_folder/'native_work_accounting.json',accounting)
            info={'guard':guard,'accounting':accounting,'accounting_file':identity(accounting_folder/'native_work_accounting.json'),'executor_attempt':attempt,'native_runtime_folder':str(folder),'accepted':False}
            if guard_error is not None:info['guard_error']=type(guard_error).__name__+': '+str(guard_error)
            report['cases'][c['tag']]=info
            for dst,src in [('attempted_owned_children','attempted_owned_child'),('created_contexts_confirmed','created_native_context_confirmed'),('completed_contexts_confirmed','completed_context_final_marker'),('unknown_total_children','totals_unknown')]:report[dst]+=int(accounting[src])
            for q in COUNT_KEYS:report['counts'][q]+=accounting['counts'][q]
            report['created_contexts_physical_lower_bound']+=accounting['created_context_physical_lower_bound']
            report['completed_contexts_physical_lower_bound']+=accounting['completed_context_physical_lower_bound']
            if accounting['successful_not_submitted_records_exact'] is not None:report['exact_successful_not_submitted_records']+=accounting['successful_not_submitted_records_exact']
            if accounting['successful_unsubmitted_records_abandoned_on_confirmed_process_exit'] is not None:report['successful_unsubmitted_records_abandoned_on_exit']+=accounting['successful_unsubmitted_records_abandoned_on_confirmed_process_exit']
            checkpoint()
            if guard_error is not None:raise guard_error
            assert not guard['guard_load_evidence']['errors'],'guard evidence invalid; physical work already checkpointed'
            assert guard['status']=='completed'and guard['returncode']==0,'guard/native failure'
            assert not accounting['totals_unknown']and not accounting['evidence_disagreements']and accounting['registered_stage_pattern_exact']
            expected={'api':64,'queued':64,'completed':64,'observed':64,'executes':64,**{q:64//c['K']for q in('signal_attempts','signals','event_attempts','events','wait_attempts','waits')}}
            assert accounting['counts']==expected
            footer=accounting['terminal_CPP_snapshot'];assert footer['context_destroyed']and all(footer[q]==0 for q in('validation_errors','validation_warnings','sdk_errors','sdk_warnings','discarded','omitted'))
            log=(folder/'stdout.log').read_text()+(folder/'stderr.log').read_text();assert'debug_layer=1'in log
            assert(folder/'stderr.log').stat().st_size==0,'unexpected warning/error; stop without policy amendment'
            controls=(folder/'dispatch_controls.bin').read_bytes();assert controls==(folder/'expected_applied_dispatch_controls.bin').read_bytes()and len(controls)==64*184
            assert(folder/'output_presence.bin').read_bytes()==bytes([1])*64
            for name in('recorded_frame_indices.bin','queued_frame_indices.bin','completed_frame_indices.bin','observed_frame_indices.bin'):assert(folder/name).read_bytes()==(folder/'expected_frame_indices.bin').read_bytes()
            for r in c['inputs']:assert Path(r['path']).stat().st_size==r['bytes']and sha(r['path'])==r['sha256']
            lobes={}
            for name in('diffuse.bin','specular.bin'):
                p=folder/name;assert p.stat().st_size==c['expected_raw_lobe_bytes'];a=np.fromfile(p,'<f2').reshape(64,80,128,4)
                lobes[name]={**identity(p),'shape':list(a.shape),'all_finite':bool(np.isfinite(a).all())};assert lobes[name]['all_finite']
            info.update(accepted=True,lobes=lobes,observed_frame_indices=list(range(64)),recorded_frame_indices=list(range(64)),applied_controls=identity(folder/'dispatch_controls.bin'))
            report['accepted_contexts']+=1;checkpoint()
        assert report['accepted_contexts']==report['completed_contexts_confirmed']==4 and report['unknown_total_children']==0
        assert report['counts']=={'api':256,'queued':256,'completed':256,'observed':256,'executes':256,**{q:256 for q in('signal_attempts','signals','event_attempts','events','wait_attempts','waits')}}
        check(freeze['files']);check(freeze['external_sources']);report['status']='completed_native_K1_command_list_rotation_not_solution_V5_accounting';checkpoint()
    except BaseException as e:
        report['status']='failed_preserved_no_retry';report['error']=type(e).__name__+': '+str(e);checkpoint();raise
if __name__=='__main__':main()
