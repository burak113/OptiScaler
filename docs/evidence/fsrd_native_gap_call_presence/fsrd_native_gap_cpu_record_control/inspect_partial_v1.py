"""CPU-only inspect and seal two completed V1 children, preserving rejection."""
from pathlib import Path
import hashlib,json,struct
import numpy as np
from analyze import metrics
from native_work_accounting import derive
HERE=Path(__file__).resolve().parent;PRIOR=HERE.parent/'fsrd_native_discarded_recording_diagnostic_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def verify(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def ids(p):
    b=Path(p).read_bytes();assert len(b)%4==0;return list(struct.unpack('<'+str(len(b)//4)+'I',b))
def main():
    prep=json.loads((HERE/'preparation_completion_manifest.json').read_text());verify(prep['files']);verify(prep['external_sources'])
    old=json.loads((PRIOR/'execution_completion_manifest.json').read_text());verify(old['files']);verify(old['external_frozen_sources']);verify(old['review_external_files'])
    reg=json.loads((HERE/'registration.json').read_text());report=json.loads((HERE/'evidence/results.json').read_text())
    assert report['status']=='failed_preserved'and report['error']=='AssertionError: ordinary D3D12/SDK diagnostics'
    assert[report[k]for k in('completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions','metadata_accepted_native_contexts')]==[2,127,126,1,1,1]
    assert list(report['cases'])==reg['mode_order'][:2]
    arrays={};index={};controls={};cases={};original_files=[]
    for c in reg['cases'][:2]:
        tag=c['tag'];folder=HERE/'evidence'/tag;info=report['cases'][tag];guard=json.loads((folder/'resource_guard.json').read_text())
        assert guard==info['guard']and guard['status']=='completed'and guard['returncode']==0
        accounting=derive(folder,guard,c);assert accounting==info['native_work_accounting']and not accounting['totals_unknown']and not accounting['evidence_disagreements']
        applied=(folder/'dispatch_controls.bin').read_bytes();assert applied==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
        recorded=ids(folder/'recorded_frame_indices.bin');observed=ids(folder/'observed_frame_indices.bin');omitted=ids(folder/'omitted_API_frame_indices.bin')
        assert recorded==c['source_frame_indices']and observed==c['observed_frame_indices']and omitted==c['omitted_API_frame_indices']
        assert(folder/'output_presence.bin').read_bytes()==bytes(c['output_presence_mask'])
        index[tag]=observed;controls[tag]={f:applied[i*184:(i+1)*184]for i,f in enumerate(recorded)}
        queued=b''.join(controls[tag][f]for f in observed);assert queued==(folder/'expected_queued_dispatch_controls.bin').read_bytes()
        if(folder/'queued_dispatch_controls.bin').exists():assert queued==(folder/'queued_dispatch_controls.bin').read_bytes()
        else:
            with(HERE/'partial_v1_derived_noAPI_queued_controls.bin').open('xb')as f:f.write(queued)
        arrays[tag]={n:np.fromfile(folder/n,'<f2').reshape(63,80,128,4)for n in('diffuse.bin','specular.bin')}
        for n,a in arrays[tag].items():assert np.isfinite(a).all()and sha(folder/n)==accounting['raw_lobes'][n]['sha256']
        stderr=(folder/'stderr.log').read_bytes()
        if c['no_api_frame']==24:assert stderr==b'SDK: Frame index jump detected. Resetting...\r\n'and accounting['final_stdout_counters']['sdk_warnings']==1 and info['metadata_accepted']is False
        else:assert stderr==b''and accounting['final_stdout_counters']['sdk_warnings']==0 and info['metadata_accepted']is True
        files=[identity(p)for p in sorted(folder.iterdir())if p.is_file()];original_files+=files
        cases[tag]={'original_V1_metadata_accepted':info['metadata_accepted'],'actual_guard':guard,'actual_accounting':accounting,'recorded_frame_indices':recorded,
            'observed_frame_indices':observed,'omitted_API_frame_indices':omitted,'output_presence':c['output_presence_mask'],
            'lobes':{n:{**identity(folder/n),'shape':[63,80,128,4],'all_finite':True}for n in arrays[tag]},'applied_controls':identity(folder/'dispatch_controls.bin'),
            'queued_controls_verified_expected_exact':True,'files':files,'source25_applied_flags':struct.unpack_from('<I',controls[tag][25],4)[0]}
    references={}
    for kind in('discard24','discard24_reset25','fresh_tail25'):
        for r in(0,1):
            tag=f'H2_round{r}_{kind}';folder=PRIOR/'evidence'/f'round{r}_{kind}';p=json.loads((PRIOR/'evidence/results.json').read_text())['cases'][f'round{r}_{kind}']
            references[tag]={'folder':str(folder),'prior_outputs_are_new_measurements':False}
            index[tag]=p['observed_frame_indices'];applied=(folder/'dispatch_controls.bin').read_bytes();controls[tag]={f:applied[i*184:(i+1)*184]for i,f in enumerate(p['recorded_frame_indices'])}
            arrays[tag]={n:np.fromfile(folder/n,'<f2').reshape(len(index[tag]),80,128,4)for n in('diffuse.bin','specular.bin')}
    def compare(a,b,frames):
        aa=[index[a].index(f)for f in frames];bb=[index[b].index(f)for f in frames]
        return{'left':a,'right':b,'source_frames':frames,'control_metadata':[{'source_frame':f,'left_flags':struct.unpack_from('<I',controls[a][f],4)[0],
            'right_flags':struct.unpack_from('<I',controls[b][f],4)[0],'applied184_bytes_exact':controls[a][f]==controls[b][f]}for f in frames],
            'lobes':{n:metrics(arrays[a][n][aa],arrays[b][n][bb])for n in arrays[a]}}
    a,b=reg['mode_order'][:2];comparisons={'first2_prefix0through23':compare(a,b,list(range(24))),'first2_common_source_frames':compare(a,b,index[a]),'first2_post25through63':compare(a,b,list(range(25,64)))}
    for name in references:
        frames=sorted(set(index[b])&set(index[name]));comparisons['noAPI_vs_'+name]=compare(b,name,frames)
        if name.endswith('_discard24'):comparisons['recorddiscard_vs_'+name]=compare(a,name,index[a])
    summary={'schema':'matched-gap-V1-two-completed-children-descriptive-inspection-v1','status':'V1_failed_metadata_preserved_actual2completed',
        'original_results':identity(HERE/'evidence/results.json'),'original_console':identity(HERE/'execution_console.log'),'original_V1_metadata_accepted_contexts':1,
        'actual_native_contexts':2,'actual_successful_API_RR_recordings':127,'actual_queued_RR_dispatches':126,'actual_SDK_record_discards':1,'actual_no_API_omissions':1,
        'actual_SDK_warnings':1,'ordinary_D3D12_errors':0,'ordinary_D3D12_warnings':0,'SDK_errors':0,'new_native_contexts':0,
        'cases':cases,'references':references,'comparisons':comparisons,'old_H2_reference_contexts_are_new_measurements':False,
        'warning':{'raw_stderr':identity(HERE/'evidence/round0_no_api24/stderr.log'),'exact_message':'SDK: Frame index jump detected. Resetting...',
            'count':1,'observed_on_noAPI_arm':True,'source25_applied_flag':2,'source25_RESET_bit_set':False,
            'qualification':'SDK declared a frame-index gap reset. Exact warning has no frame number; associating it with the24-to25 API frame-index gap is an inference. Equal queued applied controls do not establish equal effective opaque SDK history. No automatic RESET universal contract asserted.'},
        'chronology':'These CPU comparisons follow the observed V1 warning and metadata rejection. Original V1 acceptance false is preserved; inspection of retained complete readbacks is not a reinterpretation as V1 accepted or quality accepted.',
        'within_condition_repeats':'Only one context percondition in this stopped cohort; no current-cohort repeat claim. Old H2 references remain prior frozen measurements.',
        'quality_accepted':False,'game_run':False,'stain_or_game_cause_established':False}
    save(HERE/'partial_v1_inspection.json',summary)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'partial_v1_completion_manifest.json',{'schema':'immutable-gap-V1-two-completed-children-inspection-seal-v1','actual_native_contexts':2,'actual_API_RR_recordings':127,'actual_queued_RR_dispatches':126,
        'actual_SDK_record_discards':1,'actual_no_API_omissions':1,'original_V1_metadata_accepted_contexts':1,'new_native_contexts':0,'files':[identity(p)for p in files],
        'preserved_preparation_manifest':identity(HERE/'preparation_completion_manifest.json'),'old_H2_reference_manifest':identity(PRIOR/'execution_completion_manifest.json')})
    print(json.dumps({'inspection':identity(HERE/'partial_v1_inspection.json'),'manifest':identity(HERE/'partial_v1_completion_manifest.json'),
        'first2_post25':{n:{'RGB_bits_exact':m['RGB_bits_exact'],'RGB_RMS':m['RGB']['RMS'],'RGB_max_abs':m['RGB']['max_abs']}for n,m in comparisons['first2_post25through63']['lobes'].items()},
        'noAPI_vs_H2_fresh':{n:m['RGBA_bits_exact']for n,m in comparisons['noAPI_vs_H2_round0_fresh_tail25']['lobes'].items()},'new_native_contexts':0}),flush=True)
if __name__=='__main__':main()
