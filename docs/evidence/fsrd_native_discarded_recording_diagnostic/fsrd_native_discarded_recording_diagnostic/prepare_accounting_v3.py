"""Preserve V1/V2. Resolve conflicts using valid bounded CPP footer or valid lower bounds."""
from pathlib import Path
import difflib,hashlib,json
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    for name in('pre_native_freeze.json','accounting_v2_pre_native_freeze.json'):
        frozen=json.loads((HERE/name).read_text())
        for r in frozen['files']+frozen.get('external_sources',[]):
            p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256']
    assert not(HERE/'evidence/results.json').exists()and not any((HERE/'evidence').rglob('resource_guard.json'))
    old=(HERE/'native_work_accounting.py').read_text();text=old
    before="""    successful=max(v for v in record_evidence.values()if v is not None)
    queued=max(v for v in queue_evidence.values()if v is not None)
    discarded=max(v for v in discard_evidence.values()if v is not None)
    disagreements=[]"""
    after="""    # Registered frame capacities constrain validity; they never fill missing counts.
    capacity=case['frames_recorded'];expected_recorded=case['source_frame_indices'];expected_observed=case['observed_frame_indices'];expected_presence=case['output_presence_mask']
    recorded_valid=recorded['trailing_bytes']==0 and recorded['values']==expected_recorded[:len(recorded['values'])] and len(recorded['values'])<=len(expected_recorded)
    observed_valid=observed['trailing_bytes']==0 and observed['values']==expected_observed[:len(observed['values'])] and len(observed['values'])<=len(expected_observed)
    presence_valid=other==0 and list(presence)==expected_presence[:len(presence)] and len(presence)<=len(expected_presence)
    raw_valid={name:r['whole_raw_frames']<=len(expected_observed) and (r['bytes'] is None or r['bytes']<=len(expected_observed)*FRAME_BYTES) for name,r in lobes.items()}
    artifact_lower_bounds={'successful_API_RR_recordings':recorded['whole_u32_records'] if recorded_valid else 0,
        'queued_RR_dispatches':max([observed['whole_u32_records'] if observed_valid else 0,ones if presence_valid else 0]+[r['whole_raw_frames']if raw_valid[name]else 0 for name,r in lobes.items()]),
        'discarded_RR_recordings':zeros if presence_valid else 0}
    footer_valid=final is not None and all(0<=final[k]<=capacity for k in ('successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings')) and final['successful_API_RR_recordings']==final['queued_RR_dispatches']+final['discarded_RR_recordings']
    if footer_valid:
        successful=final['successful_API_RR_recordings'];queued=final['queued_RR_dispatches'];discarded=final['discarded_RR_recordings']
        counter_authority='valid_bounded_final_CPP_footer_under_pinned_source'
    else:
        successful=artifact_lower_bounds['successful_API_RR_recordings'];queued=artifact_lower_bounds['queued_RR_dispatches'];discarded=artifact_lower_bounds['discarded_RR_recordings']
        counter_authority='semantically_valid_artifact_lower_bounds_totals_unknown'
    disagreements=[]
    if not recorded_valid:disagreements.append('recorded_indices_not_registered_prefix')
    if not observed_valid:disagreements.append('observed_indices_not_registered_prefix')
    if not presence_valid:disagreements.append('presence_not_registered_prefix')
    if not all(raw_valid.values()):disagreements.append('raw_lobe_frame_count_exceeds_registered_capacity')
    if final is not None and not footer_valid:disagreements.append('final_CPP_footer_out_of_bounds_or_recording_partition_invalid')"""
    assert text.count(before)==1;text=text.replace(before,after)
    text=text.replace("'completed_native_context_final_marker':final is not None,","'completed_native_context_final_marker':footer_valid,")
    text=text.replace("'observed_output_frames_confirmed':min(observed['whole_u32_records'],ones,*(r['whole_raw_frames']for r in lobes.values())),",
"""'observed_output_frames_confirmed':min(observed['whole_u32_records']if observed_valid else 0,ones if presence_valid else 0,*(r['whole_raw_frames']if raw_valid[name]else 0 for name,r in lobes.items())),
        'counter_authority':counter_authority,'final_CPP_footer_valid':footer_valid,'semantically_valid_artifact_lower_bounds':artifact_lower_bounds,
        'totals_unknown':not footer_valid,'unified_count_status':('authoritative_footer_with_metadata_conflicts'if disagreements else'authoritative_footer')if footer_valid else'confirmed_lower_bounds_only_totals_unknown',
        'artifact_validity':{'successful_recorded_indices':recorded_valid,'observed_indices':observed_valid,'presence':presence_valid,'raw_lobes':raw_valid},""")
    text=text.replace("'counts_qualification':'Final marker reports a completed SDK context lifecycle and recorded/completed queued work even if later metadata/debug acceptance fails. Without a final marker, these flushed artifacts are confirmed lower bounds; absent files or zero lower bounds do not prove zero native work.',",
"'counts_qualification':'Valid bounded CPP footer is authoritative for recorded/completed queued work under pinned source, even when metadata artifacts conflict or validation rejects. All artifact claims remain retained. Without a reliable bounded footer, only semantically valid registered-prefix/capacity artifact lower bounds are aggregated; totals remain unknown. Registered capacities never populate missing measurements.',")
    text=text.replace("'incomplete_child_native_work_may_exceed_confirmed_lower_bounds':bool(child_launched and final is None),","'incomplete_child_native_work_may_exceed_confirmed_lower_bounds':bool(child_launched and not footer_valid),")
    with(HERE/'native_work_accounting_v3.py').open('x',encoding='utf-8',newline='\n')as f:f.write(text)
    with(HERE/'accounting_v3_module.diff').open('x',encoding='utf-8',newline='\n')as f:f.write(''.join(difflib.unified_diff(old.splitlines(keepends=True),text.splitlines(keepends=True),fromfile='preserved_accounting_v2',tofile='accounting_v3')))
    driver=(HERE/'run_native_v2.py').read_text()
    driver=driver.replace('from native_work_accounting import derive','from native_work_accounting_v3 import derive')
    driver=driver.replace('accounting_v2_pre_native_freeze.json','accounting_v3_pre_native_freeze.json')
    driver=driver.replace('actual-native-evidence-v2-accounted-before-validation','actual-native-evidence-v3-authoritative-or-qualified-accounting')
    with(HERE/'run_native_v3.py').open('x',encoding='utf-8',newline='\n')as f:f.write(driver)
    supplement={'schema':'H2-accounting-V3-conflict-resolution-pre-native-supplement-v1','status':'prepared_NOT_AUTHORIZED_TO_RUN',
        'preserved_V1_registration':identity(HERE/'registration.json'),'preserved_V1_freeze':identity(HERE/'pre_native_freeze.json'),
        'preserved_V2_freeze':identity(HERE/'accounting_v2_pre_native_freeze.json'),
        'canonical_future_executor':identity(HERE/'run_native_v3.py'),'accounting_module':identity(HERE/'native_work_accounting_v3.py'),
        'erratum':'V2 max across evidence counts could label contradictory65-index artifact as confirmed65 despite valid bounded64 CPP footer. V3 uses valid bounded final footer as authority; all conflicting artifact claims remain explicit and reject metadata. No reliable footer => semantically valid artifact lower bounds with unknown totals.',
        'footer_validity':'Nonnegative counts bounded by recorded frame capacity; successfulAPI=queued+discarded. Debug errors/warnings and raw metadata acceptance do not suppress valid footer native work.',
        'unchanged':['C++/EXE','all56 inputs','commands/params/mode order','expected184 controls/masks/indices','RGB metrics/alignment analysis'],
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
        'planned_native_contexts':8,'planned_successful_API_RR_recordings':462,'planned_discarded_API_RR_recordings':4,'planned_queued_RR_dispatches':458,
        'run_gate':'Root authorization only after bounded V3 accounting review; preparation performs no native execution.'}
    save(HERE/'accounting_v3_registration.json',supplement)
    names=('run_native_v3.py','native_work_accounting_v3.py','prepare_accounting_v3.py','accounting_v3_module.diff','accounting_v3_registration.json','registration.json','pre_native_freeze.json','accounting_v2_pre_native_freeze.json')
    save(HERE/'accounting_v3_pre_native_freeze.json',{'schema':'H2-accounting-V3-before-any-native-byte-freeze-v1','files':[identity(HERE/n)for n in names],
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0})
    print(json.dumps({'V3_registration':identity(HERE/'accounting_v3_registration.json'),'V3_freeze':identity(HERE/'accounting_v3_pre_native_freeze.json'),'V3_executor':identity(HERE/'run_native_v3.py'),'actual_native_contexts':0}),flush=True)
if __name__=='__main__':main()
