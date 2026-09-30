"""CPU-only verify/summarize actual eight and seal every preserved execution byte."""
from pathlib import Path
import hashlib,itertools,json,struct
import numpy as np
from native_work_accounting import derive
from diagnostic_warning_policy_v2 import KNOWN_WARNING,evaluate
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def verify(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def ids(p):
    b=Path(p).read_bytes();assert len(b)%4==0;return list(struct.unpack('<'+str(len(b)//4)+'I',b))
def measure(a,b,frames):
    bits=a.view('<u2')==b.view('<u2');rgb=a[...,:3].astype(np.float64)-b[...,:3].astype(np.float64);frame_exact=np.all(bits[...,:3],axis=(1,2,3));changed=[f for f,e in zip(frames,frame_exact)if not e]
    return{'RGB_bits_exact':bool(np.all(bits[...,:3])),'RGBA_bits_exact':bool(np.all(bits)),'alpha_bits_exact':bool(np.all(bits[...,3])),
        'RGB_RMS':float(np.sqrt(np.mean(rgb*rgb))),'RGB_max_abs':float(np.max(np.abs(rgb))),'RGB_changed_scalar_fraction':float(np.mean(rgb!=0)),
        'changed_RGB_source_frames':changed,'first_changed_source_frame':changed[0]if changed else None,'last_changed_source_frame':changed[-1]if changed else None}
def main():
    manifests={name:json.loads((HERE/name).read_text())for name in('preparation_completion_manifest.json','partial_v1_completion_manifest.json','remaining_v2_preparation_completion_manifest.json')}
    for m in manifests.values():verify(m['files']);verify(m.get('external_sources',[]))
    prep_review_files=[]
    for dirname,expected in(('fsrd_native_gap_cpu_record_control_review_20260930','1acb148c4492657abcfcfe44530245c2d69616225903d82bd80b77a78d899a3b'),('fsrd_native_gap_remaining_v2_review_20260930','95f2b129f7092d785977d6ffdc86534cdde295c21ddec8dcc1b4fbe4f86449bf')):
        p=HERE.parent/dirname/'completion_ready_manifest.json';assert sha(p)==expected;review=json.loads(p.read_text());verify(review['files']);prep_review_files+=review['files']+[identity(p)]
    old=json.loads((HERE/'evidence/results.json').read_text());new=json.loads((HERE/'evidence/remaining_v2_results.json').read_text());reg=json.loads((HERE/'registration.json').read_text())
    comparisons=json.loads((HERE/'combined_v2_raw_comparisons.json').read_text())
    assert old['status']=='failed_preserved'and old['metadata_accepted_native_contexts']==1 and old['cases']['round0_no_api24']['metadata_accepted']is False
    assert new['status']=='completed_matched_gap_CPU_record_remaining_V2_diagnostic_not_solution'and new['metadata_accepted_native_contexts']==6
    assert new['previous_V1_results_sha256']==sha(HERE/'evidence/results.json')
    assert comparisons['original_V1_results_sha256']==sha(HERE/'evidence/results.json')and comparisons['remaining_V2_results_sha256']==sha(HERE/'evidence/remaining_v2_results.json')
    assert len(comparisons['comparisons'])==28
    arrays={};case_summary={};guards=[];output_files=[];warning_tags=[];source_ids=[f for f in range(64)if f!=24]
    totals={k:0 for k in('successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions','validation_errors','validation_warnings','sdk_errors','sdk_warnings')}
    for c in reg['cases']:
        tag=c['tag'];folder=HERE/'evidence'/tag;p=(old if tag in old['cases']else new)['cases'][tag]
        g=json.loads((folder/'resource_guard.json').read_text());assert g==p['guard']and g['status']=='completed'and g['returncode']==0 and not g['terminated_owned_child'];guards.append(g)
        accounting=derive(folder,g,c);assert accounting==p['native_work_accounting']and not accounting['totals_unknown']and not accounting['evidence_disagreements']
        footer=accounting['final_stdout_counters'];counts=[footer[k]for k in('successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','validation_errors','validation_warnings','sdk_errors','sdk_warnings')]+[accounting['no_API_omissions_confirmed']]
        stderr=(folder/'stderr.log').read_bytes();admissibility=evaluate(c,counts,stderr)
        if footer['sdk_warnings']:assert stderr==KNOWN_WARNING;warning_tags.append(tag)
        for k in totals:totals[k]+=accounting['no_API_omissions_confirmed']if k=='no_API_omissions'else footer[k]
        assert[footer[k]for k in('successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings')]==[c['frames_recorded'],63,c['frames_discarded']]
        assert ids(folder/'recorded_frame_indices.bin')==c['source_frame_indices']and ids(folder/'observed_frame_indices.bin')==source_ids
        assert ids(folder/'omitted_API_frame_indices.bin')==c['omitted_API_frame_indices']and(folder/'output_presence.bin').read_bytes()==bytes(c['output_presence_mask'])
        packets=(folder/'dispatch_controls.bin').read_bytes();assert packets==(folder/'expected_applied_dispatch_controls.bin').read_bytes();by_frame={f:packets[i*184:(i+1)*184]for i,f in enumerate(c['source_frame_indices'])}
        queued=b''.join(by_frame[f]for f in source_ids);assert queued==(folder/'expected_queued_dispatch_controls.bin').read_bytes()
        if(folder/'queued_dispatch_controls.bin').exists():assert queued==(folder/'queued_dispatch_controls.bin').read_bytes()
        for r in c['inputs']:assert sha(r['path'])==r['sha256']
        arrays[tag]={n:np.fromfile(folder/n,'<f2').reshape(63,80,128,4)for n in('diffuse.bin','specular.bin')}
        for n,a in arrays[tag].items():assert np.isfinite(a).all()and sha(folder/n)==accounting['raw_lobes'][n]['sha256']
        files=[identity(f)for f in sorted(folder.iterdir())if f.is_file()];output_files+=files
        case_summary[tag]={'origin':'original_V1_completed2'if tag in old['cases']else'post_observation_V2_new6','original_V1_metadata_accepted':p['metadata_accepted']if tag in old['cases']else None,
            'V2_diagnostic_retention_accepted':p['metadata_accepted']if tag in new['cases']else None,'actual_footer':footer,'actual_no_API_omissions':accounting['no_API_omissions_confirmed'],
            'source25_applied_flags':struct.unpack_from('<I',by_frame[25],4)[0],'diagnostic_retention_rule_inspection_only':admissibility,
            'raw_lobes':{n:identity(folder/n)for n in arrays[tag]},'actual_stderr':identity(folder/'stderr.log'),'files':files}
    assert warning_tags==['round0_no_api24','round1_no_api24']and totals=={'successful_API_RR_recordings':508,'queued_RR_dispatches':504,'discarded_RR_recordings':4,'no_API_omissions':4,'validation_errors':0,'validation_warnings':0,'sdk_errors':0,'sdk_warnings':2}
    assert len(set(g['child_pid']for g in guards))==8
    def compare(a,b,selection):
        frames=[source_ids[i]for i in selection]
        return{'left':a,'right':b,'source_frames':frames,'lobes':{n:measure(arrays[a][n][selection],arrays[b][n][selection],frames)for n in arrays[a]}}
    prefixes=[compare(a,b,list(range(24)))for a,b in itertools.combinations(reg['mode_order'],2)]
    assert all(m['RGBA_bits_exact']for v in prefixes for m in v['lobes'].values())
    kinds=('record_discard24','no_api24','record_discard24_reset25','no_api24_reset25')
    repeats={k:compare('round0_'+k,'round1_'+k,list(range(63)))for k in kinds};assert all(m['RGBA_bits_exact']for v in repeats.values()for m in v['lobes'].values())
    six=[tag for tag in reg['mode_order']if not tag.endswith('_record_discard24')];six_pairs=[compare(a,b,list(range(63)))for a,b in itertools.combinations(six,2)]
    assert len(six)==6 and all(m['RGBA_bits_exact']for v in six_pairs for m in v['lobes'].values())
    contrasts={f'round{r}':compare(f'round{r}_record_discard24',f'round{r}_no_api24',list(range(24,63)))for r in(0,1)}
    aggregate={label:{'pairs':28,'both_lobes_RGB_bits_exact':sum(all(m['RGB_bits_exact']for m in a[label]['lobes'].values())for a in comparisons['comparisons'].values()),
        'both_lobes_RGBA_bits_exact':sum(all(m['RGBA_bits_exact']for m in a[label]['lobes'].values())for a in comparisons['comparisons'].values()),
        'all_applied184_controls_exact':sum(all(f['applied_184_bytes_exact']for f in a[label]['frames'])for a in comparisons['comparisons'].values())}for label in('submitted_ordinal','common_source_frame')}
    summary={'schema':'actual-eight-gap-API-call-intervention-descriptive-execution-summary-v2','status':'completed_post_observation_diagnostic_not_solution',
        'actual_counts_separate':comparisons['actual_counts_separated'],'combined_actual_contexts':8,'combined_actual_stage_and_diagnostic_counts':totals,
        'original_V1_status_failed_preserved':True,'original_V1_metadata_accepted_contexts':1,'original_noAPI_V1_acceptance_false_preserved':True,
        'new_V2_diagnostic_retention_accepted_contexts':6,'new_native_contexts_in_CPU_task':0,'new_API_RR_recordings_in_CPU_task':0,
        'case_summary':case_summary,'four_condition_repeats':repeats,'all28_prefix0through23_RGBA_exact':True,'six_output_equivalent_contexts':six,
        'all15_pairs_within_six_RGBA_exact_all63observed_frames':True,'recorddiscard_noRESET_vs_noAPI_noRESET_post25through63':contrasts,'aggregate_all28pairs':aggregate,
        'actual_known_SDK_warning_contexts':warning_tags,'all16raw_lobes_finite':True,'alpha_raw_uint16_values':{tag:{n:np.unique(a[...,3].view('<u2')).astype(int).tolist()for n,a in lobes.items()}for tag,lobes in arrays.items()},
        'guard_range':{'elapsed_seconds':[min(g['elapsed_seconds']for g in guards),max(g['elapsed_seconds']for g in guards)],'max_working_set_bytes':max(g['peak_observed_working_set_bytes']for g in guards),'minimum_free_bytes':min(g['minimum_observed_available_bytes']for g in guards)},
        'chronology':'V1 stopped after2 completedcontexts with accepted1 because noAPI sdkwarning1. The known-warning retention rule was amended after observation. V2 then completed six never-attempted contexts. Original failedresults, acceptedfalse, consoles, first2seal and all preparation/reviewversions remain unchanged.',
        'control_and_warning_qualification':'Queued sourceframes and inputs/184-byte controls match within manualRESET setting. At source25 noAPI_noRESET and unresetrecorddiscard flags2; manualRESET arms flags3. Only two noAPI_noRESET contexts declare SDK frame-index jump reset warnings; all manualRESET/noAPIRESET and recorddiscard contexts warn0. Exact warning contains no frame number: linking it to omitted24->25 API gap is an inference. Equal applied controls do not imply equal opaque effective history.',
        'scope':'Observed API-call-presence intervention can alter SDK gap handling in this frozen fixture; it does not isolate a specific internal mechanism or establish SDK discard support, universal autoRESET/determinism, imagequality, game scheduling or stain cause.',
        'quality_accepted':False,'game_run':False,'production_changes_by_this_task':False,'old_H2_reference_contexts_are_new_measurements':False}
    save(HERE/'combined_execution_summary.json',summary)
    d=contrasts['round0']['lobes']['diffuse.bin'];s=contrasts['round0']['lobes']['specular.bin']
    compact=f'''Eight actual contexts are retained: original2 completed127API/126queued/1SDKdiscard/1noAPI plus new6 completed381API/378queued/3SDKdiscard/3noAPI, totaling508/504/4/4. Original V1 remains failed_preserved with metadata acceptance1/2; V2 admitted six under a post-observation diagnostic retention amendment. There is no image-quality pass.

Two actual SDK warnings occurred, one in each noAPI/no-manualRESET round: “SDK: Frame index jump detected. Resetting...”. Both noAPI+RESET25 arms emitted zero warnings; all record-discard arms emitted zero. D3D12 errors/warnings and SDK errors were zero. All16 raw lobes were finite;504 outputframes per lobe are retained. Frame24 is absent in everyarm, never a fabricated zero observation.

All four repeats are RGB/RGBA bit exact. All28contextpairs match at sourceframes0–23. Six contexts (noAPI arms plus manualRESET record-discard arms) are RGB/RGBA exact across all63 observedframes. The two record-discard/noRESET contexts match each other and differ at every sourceframe25–63 from those six. Both aligned all-pair sets have16 exactRGB/RGBA pairs and12 differentpairs. In the matched noRESET API-presence contrast, post25tail diffuseRGB RMS={d['RGB_RMS']:.17g}, max={d['RGB_max_abs']:.17g}; specularRMS={s['RGB_RMS']:.17g}, max={s['RGB_max_abs']:.17g}.

Source25 appliedflags are2 in noAPI/noRESET and record-discard/noRESET,3 when manualRESET25 is requested. The declared SDK gap reset accompanies the noAPI output difference; equal queued controls do not establish equal effective opaque history. The warning has no frame number, so association with the24→25 API gap is an inference. These results are conditional on the frozen synthetic sequence and pinned runtime; they establish no universal RESET contract, SDK discard-support promise, specific internal mechanism, image-quality judgment, stain cause, game scheduling, or production fix. CPU analysis added no native/GPU calls.
'''
    with(HERE/'compact_combined_execution.md').open('x',encoding='utf-8',newline='\n')as f:f.write(compact)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    manifest={'schema':'immutable-gap-original2-plus-V2remaining6-actual-execution-completion-v1','status':'completed_post_observation_diagnostic_not_solution',
        'original_V1_actual_counts':comparisons['actual_counts_separated']['original_V1'],'remaining_V2_actual_counts':comparisons['actual_counts_separated']['remaining_V2'],
        'combined_actual_contexts':8,'combined_actual_stage_and_diagnostic_counts':totals,'original_V1_acceptance_false_and_failure_preserved':True,
        'new_native_contexts_in_this_CPU_task':0,'new_API_RR_recordings_in_this_CPU_task':0,'combined_comparisons':identity(HERE/'combined_v2_raw_comparisons.json'),
        'summary':identity(HERE/'combined_execution_summary.json'),'compact':identity(HERE/'compact_combined_execution.md'),
        'original_console':identity(HERE/'execution_console.log'),'remaining_V2_console':identity(HERE/'remaining_v2_execution_console.log'),
        'CPU_analysis_console_command':identity(HERE/'combined_CPU_analysis_command.json'),
        'preserved_preparation_manifests':[identity(HERE/n)for n in manifests],
        'files':[identity(p)for p in files],'external_sources':manifests['preparation_completion_manifest.json']['external_sources'],'preserved_external_prelaunch_review_files':prep_review_files}
    save(HERE/'combined_execution_completion_manifest.json',manifest)
    print(json.dumps({'summary':identity(HERE/'combined_execution_summary.json'),'compact':identity(HERE/'compact_combined_execution.md'),'manifest':identity(HERE/'combined_execution_completion_manifest.json'),
        'owned_files':len(files),'review_entries':len(prep_review_files),'aggregate':aggregate,'SDK_warnings_actual':totals['sdk_warnings'],'new_native_contexts':0}),flush=True)
if __name__=='__main__':main()
