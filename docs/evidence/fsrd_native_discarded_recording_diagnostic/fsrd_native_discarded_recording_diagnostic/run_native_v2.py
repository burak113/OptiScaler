"""Future sequential executor. Preparation task must never invoke --execute-native."""
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
    if sys.argv[1:]!=['--execute-native']:
        raise RuntimeError('Preparation only. Root must explicitly authorize native execution after reviews before invoking --execute-native.')
    reg=json.loads((HERE/'registration.json').read_text());freeze=json.loads((HERE/'pre_native_freeze.json').read_text())
    assert reg['status']=='prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN'
    check(freeze['files']);check(freeze['external_sources'])
    supplement=json.loads((HERE/'accounting_v2_pre_native_freeze.json').read_text());check(supplement['files'])
    target=HERE/'evidence/results.json'
    if target.exists()or any((HERE/'evidence'/c['tag']/'resource_guard.json').exists()for c in reg['cases']):raise ValueError('Preserve prior attempt')
    report={'schema':'discarded-record-H2-actual-native-evidence-v2-accounted-before-validation','status':'running','registration_sha256':sha(HERE/'registration.json'),
            'pre_native_freeze_sha256':sha(HERE/'pre_native_freeze.json'),'completed_native_contexts':0,
            'successful_API_RR_recordings':0,'queued_RR_dispatches':0,'discarded_RR_recordings':0,'cases':{},'quality_accepted':False,'game_run':False,
            'attempted_owned_children':0,'created_native_contexts_confirmed':0,'metadata_accepted_native_contexts':0,
            'observed_output_frames_confirmed':0,'incomplete_children_with_unquantified_native_work':0,
            'accounting_qualification':'Native work counters are derived before acceptance from actual stdout and flushed artifacts. Incomplete children may have additional unquantified work; no final marker/zero lower bound is not proof of no native work.'}
    def checkpoint():save(target,report)
    checkpoint()
    try:
        for c in reg['cases']:
            check(freeze['files']);check(freeze['external_sources']);check(supplement['files'])
            folder=HERE/'evidence'/c['tag'];guard=run_guarded(c['command'],folder)
            accounting=derive(folder,guard,c)
            save(folder/'native_work_accounting.json',accounting)
            info={'guard':guard,'native_work_accounting':accounting,'native_work_accounting_file':identity(folder/'native_work_accounting.json'),'metadata_accepted':False}
            report['cases'][c['tag']]=info
            report['attempted_owned_children']+=int(accounting['attempted_owned_child'])
            report['created_native_contexts_confirmed']+=int(accounting['created_native_context_confirmed'])
            report['completed_native_contexts']+=int(accounting['completed_native_context_final_marker'])
            report['successful_API_RR_recordings']+=accounting['successful_API_RR_recordings_confirmed']
            report['queued_RR_dispatches']+=accounting['queued_RR_dispatches_confirmed_completed']
            report['discarded_RR_recordings']+=accounting['discarded_API_RR_recordings_confirmed']
            report['observed_output_frames_confirmed']+=accounting['observed_output_frames_confirmed']
            report['incomplete_children_with_unquantified_native_work']+=int(accounting['incomplete_child_native_work_may_exceed_confirmed_lower_bounds'])
            checkpoint()
            if guard['status']!='completed':raise RuntimeError('Guard/native not completed '+c['tag'])
            log=(folder/'stdout.log').read_text()+(folder/'stderr.log').read_text();m=re.search(r'RR_recordings=(\d+) queued_RR_dispatches=(\d+) discarded_RR_recordings=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)',log)
            assert m is not None;counts=list(map(int,m.groups()))
            assert counts[:3]==[c['frames_recorded'],c['frames_queued'],c['frames_discarded']]
            assert counts[3:]==[0,0,0,0],'ordinary debug/SDK counts'
            assert'debug_layer=1'in log
            controls=(folder/'dispatch_controls.bin').read_bytes();assert controls==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
            presence=(folder/'output_presence.bin').read_bytes();assert presence==(folder/'expected_output_presence.bin').read_bytes()
            recorded=u32s(folder/'recorded_frame_indices.bin');observed=u32s(folder/'observed_frame_indices.bin')
            assert recorded==c['source_frame_indices']and observed==c['observed_frame_indices']
            assert observed==[f for f,b in zip(recorded,presence)if b]
            for row in c['inputs']:assert sha(row['path'])==row['sha256']
            lobes={}
            for name in('diffuse.bin','specular.bin'):
                p=folder/name;assert p.stat().st_size==c['expected_raw_lobe_bytes'];a=np.fromfile(p,'<f2').reshape(c['frames_queued'],80,128,4)
                lobes[name]={**identity(p),'shape':list(a.shape),'all_finite':bool(np.isfinite(a).all())}
            info.update(completion_counts={'successful_API_RR_recordings':counts[0],'queued_RR_dispatches':counts[1],'discarded_RR_recordings':counts[2],
                        'validation_errors':counts[3],'validation_warnings':counts[4],'sdk_errors':counts[5],'sdk_warnings':counts[6]},
                        recorded_frame_indices=recorded,observed_frame_indices=observed,output_presence=list(presence),lobes=lobes,
                        applied_controls=identity(folder/'dispatch_controls.bin'),files=[identity(p)for p in sorted(folder.iterdir())if p.is_file()])
            info['metadata_accepted']=True;report['metadata_accepted_native_contexts']+=1;checkpoint()
            print(c['tag'],'completed',counts[:3],flush=True)
        assert[report[k]for k in('completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings')]==[8,462,458,4]
        check(freeze['files']);check(freeze['external_sources']);check(supplement['files']);report['sources_unchanged']=True
        report['status']='completed_H2_native_record_discard_diagnostic_not_solution';checkpoint()
    except BaseException as e:
        report['status']='failed_preserved';report['error']=type(e).__name__+': '+str(e);checkpoint();raise
if __name__=='__main__':main()
