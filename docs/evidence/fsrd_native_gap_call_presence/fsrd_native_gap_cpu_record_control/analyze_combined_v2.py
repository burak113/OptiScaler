"""Future CPU-only actual old2 + new6 comparisons; never run a native executable."""
from pathlib import Path
import hashlib,itertools,json,struct
import numpy as np
from analyze import metrics
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    original=json.loads((HERE/'evidence/results.json').read_text());new=json.loads((HERE/'evidence/remaining_v2_results.json').read_text())
    partial=json.loads((HERE/'partial_v1_inspection.json').read_text());reg=json.loads((HERE/'registration.json').read_text())
    assert original['status']=='failed_preserved'and original['completed_native_contexts']==2 and original['metadata_accepted_native_contexts']==1
    assert new['status']=='completed_matched_gap_CPU_record_remaining_V2_diagnostic_not_solution'and new['completed_native_contexts']==6
    assert list(original['cases'])==reg['mode_order'][:2]and list(new['cases'])==reg['mode_order'][2:]
    arrays={};indices={};controls={};case_summary={}
    for c in reg['cases']:
        tag=c['tag'];is_old=tag in original['cases'];p=original['cases'][tag]if is_old else new['cases'][tag];data=partial['cases'][tag]if is_old else p
        folder=HERE/'evidence'/tag;indices[tag]=data['observed_frame_indices'];recorded=data['recorded_frame_indices'];raw=(folder/'dispatch_controls.bin').read_bytes()
        assert raw==(folder/'expected_applied_dispatch_controls.bin').read_bytes()and indices[tag]==c['observed_frame_indices']
        controls[tag]={f:raw[i*184:(i+1)*184]for i,f in enumerate(recorded)}
        arrays[tag]={name:np.fromfile(folder/name,'<f2').reshape(len(indices[tag]),80,128,4)for name in('diffuse.bin','specular.bin')}
        for name in arrays[tag]:assert sha(folder/name)==data['lobes'][name]['sha256']
        account=p['native_work_accounting'];case_summary[tag]={'origin':'original_V1_completed2'if is_old else'remaining_post_observation_V2_new6',
            'original_V1_metadata_accepted':p['metadata_accepted']if is_old else None,'V2_diagnostic_retention_accepted':p['metadata_accepted']if not is_old else None,
            'SDK_warnings_actual':account['final_stdout_counters']['sdk_warnings'],'no_API_omissions_actual':account['no_API_omissions_confirmed'],
            'SDK_record_discards_actual':account['discarded_API_RR_recordings_confirmed'],'source25_flags':struct.unpack_from('<I',controls[tag][25],4)[0]}
    result={'schema':'actual-original2-plus-remaining6-post-observation-combined-CPU-comparisons-v2','original_V1_results_sha256':sha(HERE/'evidence/results.json'),
        'remaining_V2_results_sha256':sha(HERE/'evidence/remaining_v2_results.json'),'original_V1_actual_contexts':original['completed_native_contexts'],
        'new_remaining_V2_actual_contexts':new['completed_native_contexts'],'combined_actual_contexts':original['completed_native_contexts']+new['completed_native_contexts'],
        'actual_counts_separated':{origin:{k:p[k]for k in('completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions','metadata_accepted_native_contexts')}for origin,p in(('original_V1',original),('remaining_V2',new))},
        'combined_actual_stage_counts':{k:original[k]+new[k]for k in('completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions')},
        'SDK_warnings_actual_total':sum(c['SDK_warnings_actual']for c in case_summary.values()),'case_summary':case_summary,'comparisons':{},
        'new_native_contexts_in_CPU_analysis':0,'quality_accepted':False,'game_run':False,'prior_H2_reference_contexts_are_new_measurements':False,
        'chronology':'Original V1 rejected noAPI warning after two completed children; its false acceptance remains false. Remaining six execute only under a later diagnostic-retention amendment. Combined comparison is post-observation and creates no extra native measurement.',
        'causal_qualification':'API call presence can change SDK declared frame-gap reset behavior. Equal queued applied flags/controls do not prove equal effective opaque history. Keep actual warning reset mediator and manualRESET flags separate; no universal autoRESET, quality, stain or game cause.'}
    for left,right in itertools.combinations(reg['mode_order'],2):
        aidx=indices[left];bidx=indices[right];common=sorted(set(aidx)&set(bidx));alignments={}
        for label,pairs in(('submitted_ordinal',list(zip(aidx,bidx))),('common_source_frame',[(f,f)for f in common])):
            aa=[aidx.index(a)for a,b in pairs];bb=[bidx.index(b)for a,b in pairs]
            metadata=[{'left_source_frame':a,'right_source_frame':b,'left_submitted_ordinal':aidx.index(a),'right_submitted_ordinal':bidx.index(b),
                'left_flags':struct.unpack_from('<I',controls[left][a],4)[0],'right_flags':struct.unpack_from('<I',controls[right][b],4)[0],
                'applied_184_bytes_exact':controls[left][a]==controls[right][b]}for a,b in pairs]
            alignments[label]={'frames':metadata,'lobes':{n:metrics(arrays[left][n][aa],arrays[right][n][bb])for n in arrays[left]}}
        result['comparisons'][left+'__'+right]=alignments
    assert len(result['comparisons'])==28
    save(HERE/'combined_v2_raw_comparisons.json',result)
    print(json.dumps({'context_pairs':28,'alignments_per_pair':2,'lobes_per_alignment':2,'combined_actual_contexts':result['combined_actual_contexts'],'new_native_contexts':0,'sha256':sha(HERE/'combined_v2_raw_comparisons.json')}))
if __name__=='__main__':main()
