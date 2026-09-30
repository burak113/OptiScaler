"""Future guarded sequential executor. Preparation never passes --execute-native."""
from pathlib import Path
import hashlib,json,re,struct,sys
import numpy as np
from native_resource_guard import run_guarded
from native_work_accounting import derive
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with Path(p).open('w',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def check(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def u32s(p):
    data=Path(p).read_bytes();assert len(data)%4==0;return list(struct.unpack('<'+str(len(data)//4)+'I',data))
def main():
    if sys.argv[1:]!=['--execute-native']:raise RuntimeError('Preparation only: root authorization after independent prelaunch review is required before --execute-native.')
    reg=json.loads((HERE/'registration.json').read_text());freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    assert reg['status']=='prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN'
    check(freeze['files']);check(freeze['external_sources'])
    target=HERE/'evidence/results.json'
    if target.exists()or any((HERE/'evidence'/c['tag']/'resource_guard.json').exists()for c in reg['cases']):raise ValueError('Preserve prior attempt')
    report={'schema':'matched-gap-CPU-record-actual-native-stage-evidence-v1','status':'running','registration_sha256':sha(HERE/'registration.json'),'pre_native_freeze_sha256':sha(HERE/'pre_native_freeze.json'),
        'completed_native_contexts':0,'successful_API_RR_recordings':0,'queued_RR_dispatches':0,'discarded_RR_recordings':0,'no_API_omissions':0,'cases':{},
        'attempted_owned_children':0,'created_native_contexts_confirmed':0,'metadata_accepted_native_contexts':0,'observed_output_frames_confirmed':0,
        'incomplete_children_with_unquantified_native_work':0,'quality_accepted':False,'game_run':False,
        'prior_H2_reference_contexts':8,'prior_H2_reference_contexts_count_as_new':False,
        'accounting_qualification':'Actual stage counters are derived before metadata/debug acceptance. Valid bounded pinned CPP footers are authoritative despite invalid metadata; no reliable footer yields qualified lower bounds/unknown totals. Missing output presence alone is not a successful SDK discard. Registered totals never fill absent work measurements.'}
    def checkpoint():save(target,report)
    checkpoint()
    try:
        for c in reg['cases']:
            check(freeze['files']);check(freeze['external_sources']);folder=HERE/'evidence'/c['tag'];guard_error=None
            try:guard=run_guarded(c['command'],folder)
            except BaseException as error:
                guard_error=error
                guard=json.loads((folder/'resource_guard.json').read_text())if(folder/'resource_guard.json').exists()else{'status':'guard_exception_without_saved_child_marker','child_pid':None,'returncode':None}
            # This checkpoint runs even after guard exceptions, and before any
            # accepted-output assumptions. The unchanged guard owns termination.
            accounting=derive(folder,guard,c);save(folder/'native_work_accounting.json',accounting)
            info={'guard':guard,'native_work_accounting':accounting,'native_work_accounting_file':identity(folder/'native_work_accounting.json'),'metadata_accepted':False}
            if guard_error is not None:info['guard_exception']=type(guard_error).__name__+': '+str(guard_error)
            report['cases'][c['tag']]=info
            for report_key,accounting_key in(('attempted_owned_children','attempted_owned_child'),('created_native_contexts_confirmed','created_native_context_confirmed'),('completed_native_contexts','completed_native_context_final_marker'),
                ('successful_API_RR_recordings','successful_API_RR_recordings_confirmed'),('queued_RR_dispatches','queued_RR_dispatches_confirmed_completed'),('discarded_RR_recordings','discarded_API_RR_recordings_confirmed'),
                ('no_API_omissions','no_API_omissions_confirmed'),('observed_output_frames_confirmed','observed_output_frames_confirmed'),('incomplete_children_with_unquantified_native_work','incomplete_child_native_work_may_exceed_confirmed_lower_bounds')):
                report[report_key]+=int(accounting[accounting_key])
            checkpoint()
            if guard_error is not None:raise guard_error
            if guard['status']!='completed':raise RuntimeError('Guard/native not completed '+c['tag'])
            assert not accounting['totals_unknown']and not accounting['evidence_disagreements']
            log=(folder/'stdout.log').read_text()+(folder/'stderr.log').read_text()
            m=re.search(r'RR_recordings=(\d+) queued_RR_dispatches=(\d+) discarded_RR_recordings=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+) no_API_omissions=(\d+)',log)
            assert m is not None;counts=list(map(int,m.groups()))
            assert counts[:3]==[c['frames_recorded'],c['frames_queued'],c['frames_discarded']]and counts[7]==c['frames_omitted_API']
            assert counts[3:7]==[0,0,0,0],'ordinary D3D12/SDK diagnostics';assert'debug_layer=1'in log
            assert(folder/'stderr.log').stat().st_size==0
            controls=(folder/'dispatch_controls.bin').read_bytes();assert controls==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
            presence=(folder/'output_presence.bin').read_bytes();assert presence==(folder/'expected_output_presence.bin').read_bytes()
            recorded=u32s(folder/'recorded_frame_indices.bin');observed=u32s(folder/'observed_frame_indices.bin');omitted=u32s(folder/'omitted_API_frame_indices.bin')
            assert recorded==c['source_frame_indices']and observed==c['observed_frame_indices']and omitted==c['omitted_API_frame_indices']
            assert observed==[f for f,b in zip(c['consumed_source_frame_indices'],presence)if b]
            by_frame={f:controls[i*184:(i+1)*184]for i,f in enumerate(recorded)}
            queued_controls=b''.join(by_frame[f]for f in observed)
            assert queued_controls==(folder/'expected_queued_dispatch_controls.bin').read_bytes()
            with(folder/'queued_dispatch_controls.bin').open('xb')as f:f.write(queued_controls)
            for r in c['inputs']:assert sha(r['path'])==r['sha256']
            lobes={}
            for name in('diffuse.bin','specular.bin'):
                p=folder/name;assert p.stat().st_size==c['expected_raw_lobe_bytes'];a=np.fromfile(p,'<f2').reshape(c['frames_queued'],80,128,4)
                lobes[name]={**identity(p),'shape':list(a.shape),'all_finite':bool(np.isfinite(a).all())}
            info.update(completion_counts={'successful_API_RR_recordings':counts[0],'queued_RR_dispatches':counts[1],'discarded_RR_recordings':counts[2],
                'validation_errors':counts[3],'validation_warnings':counts[4],'sdk_errors':counts[5],'sdk_warnings':counts[6],'no_API_omissions':counts[7]},
                recorded_frame_indices=recorded,observed_frame_indices=observed,omitted_API_frame_indices=omitted,output_presence=list(presence),lobes=lobes,
                applied_controls=identity(folder/'dispatch_controls.bin'),queued_controls={**identity(folder/'queued_dispatch_controls.bin'),'derivation':'CPU selection of actual184-byte API packets by retained submitted/observed source-index mapping'},
                files=[identity(p)for p in sorted(folder.iterdir())if p.is_file()])
            info['metadata_accepted']=True;report['metadata_accepted_native_contexts']+=1;checkpoint();print(c['tag'],'completed',counts[:3],'omitted_API',counts[7],flush=True)
        assert[report[k]for k in('completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions','metadata_accepted_native_contexts')]==[8,508,504,4,4,8]
        check(freeze['files']);check(freeze['external_sources']);report['sources_unchanged']=True
        report['status']='completed_matched_gap_CPU_record_diagnostic_not_solution';checkpoint()
    except BaseException as e:
        report['status']='failed_preserved';report['error']=type(e).__name__+': '+str(e);checkpoint();raise
if __name__=='__main__':main()
