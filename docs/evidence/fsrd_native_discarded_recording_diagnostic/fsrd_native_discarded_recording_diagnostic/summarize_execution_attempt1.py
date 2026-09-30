"""CPU-only actual execution verification, descriptive segments, and new seal."""
from pathlib import Path
import hashlib,itertools,json,re,struct
import numpy as np
from analyze import metrics
HERE=Path(__file__).resolve().parent
REVIEW=HERE.parent/'fsrd_native_discarded_recording_review_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def main():
    prep=json.loads((HERE/'preparation_completion_manifest_v3.json').read_text());verify(prep['files'])
    freezes={name:json.loads((HERE/name).read_text())for name in('pre_native_freeze.json','accounting_v2_pre_native_freeze.json','accounting_v3_pre_native_freeze.json')}
    for data in freezes.values():verify(data['files']);verify(data.get('external_sources',[]))
    review=json.loads((REVIEW/'completion_final_manifest.json').read_text());verify(review['files'])
    assert sha(REVIEW/'completion_final_manifest.json')=='7148e5393a4754bf882037036bf7aec8e59fa1c447b1ca49e65d6d1d6276c63f'
    producer=json.loads((HERE/'evidence/results.json').read_text());reg=json.loads((HERE/'registration.json').read_text())
    raw=json.loads((HERE/'raw_comparisons.json').read_text())
    assert producer['status']=='completed_H2_native_record_discard_diagnostic_not_solution'
    assert raw['producer_sha256']==sha(HERE/'evidence/results.json')and len(raw['comparisons'])==28
    assert [producer[k]for k in('completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','metadata_accepted_native_contexts','observed_output_frames_confirmed')]==[8,462,458,4,8,458]
    arrays={};indices={};controls={};guards=[];case_summaries={};case_file_identities=0;debug_totals={k:0 for k in('validation_errors','validation_warnings','sdk_errors','sdk_warnings')}
    for c in reg['cases']:
        tag=c['tag'];folder=HERE/'evidence'/tag;p=producer['cases'][tag];verify(p['files']);case_file_identities+=len(p['files'])
        assert p['metadata_accepted']and p['native_work_accounting']['counter_authority']=='valid_bounded_final_CPP_footer_under_pinned_source'
        assert not p['native_work_accounting']['evidence_disagreements']and not p['native_work_accounting']['totals_unknown']
        g=json.loads((folder/'resource_guard.json').read_text());assert g==p['guard']and g['status']=='completed'and g['returncode']==0
        assert g['args']==c['command']and not g['terminated_owned_child']
        assert(g['timeout_seconds'],g['maximum_working_set_bytes'],g['minimum_available_memory_bytes'],g['sample_interval_seconds'])==(240,2147483648,1073741824,0.2)
        assert g['minimum_observed_available_bytes']>=1073741824 and g['peak_observed_working_set_bytes']<=2147483648
        guards.append(g)
        counts=p['completion_counts'];assert[counts[k]for k in('successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings')]==[c['frames_recorded'],c['frames_queued'],c['frames_discarded']]
        for k in debug_totals:assert counts[k]==0;debug_totals[k]+=counts[k]
        log=(folder/'stdout.log').read_text();assert'debug_layer=1'in log and'provider=unavailable from direct effect DLL id=0 version_query_result=6'in log
        assert(folder/'stderr.log').stat().st_size==0
        if c['skip_frame']==24:assert'discarded_recording source_frame=24 previous_submitted_source_frame=23 previous_completed_fence=24 external_state_shadow_restored=1 queued=0 observed_output=0'in log
        recorded=p['recorded_frame_indices'];indices[tag]=p['observed_frame_indices'];assert recorded==c['source_frame_indices']and indices[tag]==c['observed_frame_indices']
        assert(folder/'output_presence.bin').read_bytes()==bytes(c['output_presence_mask'])
        assert(folder/'dispatch_controls.bin').read_bytes()==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
        control=(folder/'dispatch_controls.bin').read_bytes();controls[tag]={f:control[i*184:(i+1)*184]for i,f in enumerate(recorded)}
        arrays[tag]={name:np.fromfile(folder/name,'<f2').reshape(c['frames_queued'],80,128,4)for name in('diffuse.bin','specular.bin')}
        for name,a in arrays[tag].items():assert np.isfinite(a).all()and sha(folder/name)==p['lobes'][name]['sha256']
        case_summaries[tag]={'counts':counts,'observed_source_frames':indices[tag],'output_presence':c['output_presence_mask'],
            'RGBA_alpha_bits':{name:np.unique(a[...,3].view('<u2')).astype(int).tolist()for name,a in arrays[tag].items()},
            'guard':{'child_pid':g['child_pid'],'elapsed_seconds':g['elapsed_seconds'],'peak_working_set_bytes':g['peak_observed_working_set_bytes'],'minimum_available_bytes':g['minimum_observed_available_bytes']}}
    assert len(set(g['child_pid']for g in guards))==8
    def segment(left,right,source_frames):
        aa=[indices[left].index(f)for f in source_frames];bb=[indices[right].index(f)for f in source_frames]
        return{'left':left,'right':right,'source_frames':source_frames,'frames':len(source_frames),
            'applied184_controls_exact':all(controls[left][f]==controls[right][f]for f in source_frames),
            'lobes':{name:metrics(arrays[left][name][aa],arrays[right][name][bb])for name in arrays[left]}}
    repeats={kind:segment('round0_'+kind,'round1_'+kind,indices['round0_'+kind])for kind in('baseline','discard24','discard24_reset25','fresh_tail25')}
    assert all(m['RGBA_bits_exact']and m['RGB_bits_exact']for v in repeats.values()for m in v['lobes'].values())
    full_tags=[c['tag']for c in reg['cases']if c['frames_recorded']==64]
    prefixes=[segment(a,b,list(range(24)))for a,b in itertools.combinations(full_tags,2)]
    assert len(prefixes)==15 and all(v['applied184_controls_exact']and all(m['RGBA_bits_exact']and m['RGB_bits_exact']for m in v['lobes'].values())for v in prefixes)
    drop_tail={f'round{r}':segment(f'round{r}_baseline',f'round{r}_discard24',list(range(25,64)))for r in(0,1)}
    reset_fresh={f'reset_round{a}_fresh_round{b}':segment(f'round{a}_discard24_reset25',f'round{b}_fresh_tail25',list(range(25,64)))for a in(0,1)for b in(0,1)}
    assert all(v['applied184_controls_exact']and all(m['RGBA_bits_exact']and m['RGB_bits_exact']for m in v['lobes'].values())for v in reset_fresh.values())
    pair_summary={};aggregate={label:{'pairs':0,'both_lobes_RGB_bits_exact':0,'both_lobes_RGBA_bits_exact':0,'all_applied184_controls_exact':0}for label in('submitted_ordinal','common_source_frame')}
    for key,alignments in raw['comparisons'].items():
        left,right=key.split('__');pair_summary[key]={}
        for label,v in alignments.items():
            a=aggregate[label];a['pairs']+=1;a['both_lobes_RGB_bits_exact']+=int(all(m['RGB_bits_exact']for m in v['lobes'].values()));a['both_lobes_RGBA_bits_exact']+=int(all(m['RGBA_bits_exact']for m in v['lobes'].values()))
            a['all_applied184_controls_exact']+=int(all(f['applied_184_bytes_exact']for f in v['frames']))
            rows={'frames':len(v['frames']),'same_source_frame_rows':sum(f['left_source_frame']==f['right_source_frame']for f in v['frames']),
                'same184_controls_rows':sum(f['applied_184_bytes_exact']for f in v['frames']),'lobes':{}}
            for name,m in v['lobes'].items():
                aa=[indices[left].index(f['left_source_frame'])for f in v['frames']];bb=[indices[right].index(f['right_source_frame'])for f in v['frames']]
                frame_exact=np.all(arrays[left][name][aa][...,:3].view('<u2')==arrays[right][name][bb][...,:3].view('<u2'),axis=(1,2,3))
                changed=[(f['left_source_frame'],f['right_source_frame'])for f,e in zip(v['frames'],frame_exact)if not e]
                rows['lobes'][name]={'RGB_bits_exact':m['RGB_bits_exact'],'RGBA_bits_exact':m['RGBA_bits_exact'],
                    'RGB_RMS':m['RGB']['RMS'],'RGB_max_abs':m['RGB']['max_abs'],'RGB_changed_scalar_fraction':m['RGB']['changed_fraction'],
                    'changed_RGB_frame_count':len(changed),'first_changed_source_pair':changed[0]if changed else None,'last_changed_source_pair':changed[-1]if changed else None,
                    'alpha_RMS':m['alpha']['RMS']}
            pair_summary[key][label]=rows
    interpretation={'schema':'H2-actual-execution-descriptive-interpretation-v1','status':'completed_observed_conditional_history_effect_not_solution',
        'producer':identity(HERE/'evidence/results.json'),'raw_comparisons':identity(HERE/'raw_comparisons.json'),
        'actual_native_contexts':8,'actual_successful_API_RR_recordings':462,'actual_queued_RR_dispatches':458,'actual_discarded_API_RR_recordings':4,
        'actual_observed_output_frames_per_lobe':458,'new_native_contexts_in_CPU_analysis':0,'new_API_RR_recordings_in_CPU_analysis':0,
        'ordinary_debug_SDK_totals':debug_totals,'all8_metadata_accepted':True,'all16_raw_lobes_finite':True,
        'case_summaries':case_summaries,'aggregate_all28_pairs':aggregate,'all28_pair_alignment_summary':pair_summary,
        'within_condition_repeats':repeats,'prefix0through23':{'full_length_contexts':full_tags,'pairs':15,'frames_per_pair':24,'both_lobes_RGBA_and_RGB_bits_exact_all_pairs':True,'applied184_controls_exact_all_pairs':True},
        'baseline_vs_discard_post25through63':drop_tail,'RESET25_recovery_vs_fresh_tail25_all4_pairings':reset_fresh,
        'guard_observed_range':{'seconds':[min(g['elapsed_seconds']for g in guards),max(g['elapsed_seconds']for g in guards)],
            'maximum_working_set_bytes':max(g['peak_observed_working_set_bytes']for g in guards),'minimum_available_bytes':min(g['minimum_observed_available_bytes']for g in guards)},
        'preserved_preparation_files_verified':len(prep['files']),'actual_case_file_identities_verified':case_file_identities,'preserved_review_files_verified':len(review['files']),
        'preserved_preparation_manifest_V3':identity(HERE/'preparation_completion_manifest_v3.json'),'preserved_independent_review_manifest':identity(REVIEW/'completion_final_manifest.json'),
        'conclusions':['All four same-condition repeats are bit exact in both RGB and RGBA.',
            'All six full-length contexts have exact RGB/RGBA at sourceframes0..23. Frame24 is absent in four discard contexts and never treated as observed zero output.',
            'Baseline versus successfulrecord-then-discard24 differs in RGB at each matched sourceframe25..63 in both lobes, with the same184-byte dispatch controls.',
            'RESET25 recovery matches fresh-tail25 RGB/RGBA bit for bit for all39 sourceframes in all four cross-round pairings; corresponding184-byte controls match.',
            'Observed equality is scoped to this frozen sequence and provider/device/driver. It is not a universal RESET or determinism contract.'],
        'causal_qualification':'Baseline/discard changes both successful CPU SDK recording followed by discard and missing GPU execution of sourceframe24. It does not isolate an effect of CPU successful-record advancement from missing GPU history. A matched no-API-Dispatch24 control is required for that separation.',
        'alignment_qualification':'Submitted ordinal aligns execution position and can compare different sourceframes/flags; common-source-frame comparisons align the actual retained source indices. Neither creates output for discarded24.',
        'provider_qualification':'Direct pinned effect DLL used. Provider version query unavailable: id0/result6; this is retained separately from ordinary SDK/debug warning counters.',
        'limitations':raw['limits'],'quality_accepted':False,'game_run':False,'stain_or_game_cause_established':False}
    save(HERE/'execution_interpretation.json',interpretation)
    d=drop_tail['round0']['lobes']['diffuse.bin']['RGB'];s=drop_tail['round0']['lobes']['specular.bin']['RGB']
    compact=f'''Eight fresh contexts completed: 462 successful API RR recordings, 458 queued and readback-completed frames, four recorded-then-discarded frames. Ordinary D3D12/SDK errors and warnings were zero; all 16 raw lobes were finite. No native/GPU work was added by the CPU analysis.

All four within-condition repeats were exact RGB/RGBA in both lobes. The six full-length contexts matched exactly at sourceframes 0–23 (all 15 context pairs). Discarded frame 24 has presence zero and no raw output; four such missing frames are not measured zero outputs.

With logical sourceframe alignment, baseline versus discard24 first differs at 25 and differs at every frame through 63 in both lobes. Controls match byte for byte. Over that 39-frame tail, diffuse RGB RMS is {d['RMS']:.17g}, max absolute difference {d['max_abs']:.17g}; specular RMS is {s['RMS']:.17g}, max {s['max_abs']:.17g}. Both rounds reproduce these differences exactly. These are descriptive scalar differences, without quality or truth thresholds.

RESET25 recovery and fresh-tail25 match RGB/RGBA bit for bit across all 39 sourceframes in all four cross-round pairings, with identical 184-byte controls. This observed equality is specific to the frozen sequence; it does not establish a universal RESET or provider determinism contract.

The frozen analysis retains all 28 context pairs, both submitted-ordinal and common-sourceframe alignments, and both lobes. Ordinal alignment can compare different sourceframes and controls after the discard or at the fresh-tail boundary; causal interpretation uses matched sourceframes. Alpha numeric differences are zero across all aligned pairs.

Baseline/discard also removes GPU execution of frame24, so it does not isolate a CPU successful-record effect from missing GPU history. A no-API-Dispatch24 control with the same queued frames is needed for that separation. External resource shadow restoration does not roll back opaque SDK state; support for discarding an SDK recording is not asserted. The direct DLL remains pinned, while its provider version query is unavailable (id0/result6). This synthetic diagnostic establishes no game scheduling, stain cause, image-quality judgment, or fix.

All 188 preparation identities and 22 independent pre-native review identities remained exact. V1/V2 accounting qualifications remain preserved; actual execution used frozen V3. Root performed the native execution; this task only analyzed and sealed its retained bytes.
'''
    with(HERE/'compact_execution.md').open('x',encoding='utf-8',newline='\n')as f:f.write(compact)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    manifest={'schema':'immutable-H2-actual-execution-completion-v1','status':'completed_native_execution_and_CPU_analysis_not_solution',
        'actual_native_contexts':8,'actual_successful_API_RR_recordings':462,'actual_queued_RR_dispatches':458,'actual_discarded_API_RR_recordings':4,
        'new_native_contexts_in_this_CPU_task':0,'new_API_RR_recordings_in_this_CPU_task':0,
        'preparation_V3_manifest':identity(HERE/'preparation_completion_manifest_v3.json'),
        'preserved_independent_pre_native_review_manifest':identity(REVIEW/'completion_final_manifest.json'),
        'retained_native_console':identity(HERE/'execution_console.log'),'retained_CPU_analysis_console_command':identity(HERE/'CPU_analysis_command.json'),
        'producer':identity(HERE/'evidence/results.json'),'raw_comparisons':identity(HERE/'raw_comparisons.json'),
        'interpretation':identity(HERE/'execution_interpretation.json'),'compact':identity(HERE/'compact_execution.md'),
        'files':[identity(p)for p in files],
        'external_frozen_sources':freezes['pre_native_freeze.json']['external_sources'],
        'review_external_files':review['files']+[identity(REVIEW/'completion_final_manifest.json')]}
    save(HERE/'execution_completion_manifest.json',manifest)
    print(json.dumps({'interpretation':identity(HERE/'execution_interpretation.json'),'compact':identity(HERE/'compact_execution.md'),
        'completion_manifest':identity(HERE/'execution_completion_manifest.json'),'sealed_owned_files':len(files),
        'aggregate':aggregate,'post25_RGB_RMS':{'diffuse':d['RMS'],'specular':s['RMS']},'new_native_contexts':0}),flush=True)
if __name__=='__main__':main()
