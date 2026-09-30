"""Count confirmed actual child work before metadata/debug acceptance can fail.

Incomplete children yield qualified lower bounds, never claims of no native work.
This module launches nothing and does not substitute any absent output bytes.
"""
from pathlib import Path
import hashlib,re,struct
FRAME_BYTES=128*80*8
def artifact(p):
    p=Path(p)
    if not p.exists():return{'path':str(p),'present':False,'bytes':None,'sha256':None}
    data=p.read_bytes();return{'path':str(p),'present':True,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
def indices(p):
    p=Path(p)
    if not p.exists():return{'present':False,'values':[],'whole_u32_records':0,'trailing_bytes':0}
    data=p.read_bytes();n=len(data)//4;return{'present':True,'values':list(struct.unpack('<'+str(n)+'I',data[:n*4])),
                                          'whole_u32_records':n,'trailing_bytes':len(data)%4}
def derive(folder,guard,case):
    folder=Path(folder);log=''
    for name in('stdout.log','stderr.log'):
        p=folder/name
        if p.exists():log+=p.read_text(errors='replace')
    m=re.search(r'RR_recordings=(\d+) queued_RR_dispatches=(\d+) discarded_RR_recordings=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+)',log)
    final=None
    if m:
        v=list(map(int,m.groups()));final=dict(zip(('successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','validation_errors','validation_warnings','sdk_errors','sdk_warnings'),v))
    recorded=indices(folder/'recorded_frame_indices.bin');observed=indices(folder/'observed_frame_indices.bin')
    presence_path=folder/'output_presence.bin';presence=presence_path.read_bytes()if presence_path.exists()else b''
    zeros=presence.count(0);ones=presence.count(1);other=len(presence)-zeros-ones
    lobes={name:{**artifact(folder/name)}for name in('diffuse.bin','specular.bin')}
    for r in lobes.values():
        r['whole_raw_frames']=0 if r['bytes'] is None else r['bytes']//FRAME_BYTES
        r['trailing_raw_bytes']=0 if r['bytes'] is None else r['bytes']%FRAME_BYTES
    record_evidence={'final_stdout':None if final is None else final['successful_API_RR_recordings'],'successful_recorded_u32_indices':recorded['whole_u32_records']}
    queue_evidence={'final_stdout':None if final is None else final['queued_RR_dispatches'],'observed_u32_indices':observed['whole_u32_records'],
                    'presence_ones':ones,'diffuse_whole_readback_frames':lobes['diffuse.bin']['whole_raw_frames'],'specular_whole_readback_frames':lobes['specular.bin']['whole_raw_frames']}
    discard_evidence={'final_stdout':None if final is None else final['discarded_RR_recordings'],'presence_zeros':zeros}
    # Registered frame capacities constrain validity; they never fill missing counts.
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
    if final is not None and not footer_valid:disagreements.append('final_CPP_footer_out_of_bounds_or_recording_partition_invalid')
    if final is not None:
        if recorded['whole_u32_records']!=final['successful_API_RR_recordings']:disagreements.append('successful_record_indices_vs_final_stdout')
        for key in('observed_u32_indices','presence_ones','diffuse_whole_readback_frames','specular_whole_readback_frames'):
            if queue_evidence[key]!=final['queued_RR_dispatches']:disagreements.append(key+'_vs_final_stdout')
        if zeros!=final['discarded_RR_recordings']:disagreements.append('presence_zeros_vs_final_stdout')
    if recorded['trailing_bytes']or observed['trailing_bytes']or other or any(r['trailing_raw_bytes']for r in lobes.values()):disagreements.append('partial_or_invalid_artifact_bytes')
    child_launched=guard.get('child_pid')is not None
    return{'schema':'confirmed-native-work-before-validation-accounting-v1','case':case['tag'],
        'attempted_owned_child':child_launched,'guard_status':guard.get('status'),'returncode':guard.get('returncode'),
        'created_native_context_confirmed':bool('provider='in log or successful>0),
        'completed_native_context_final_marker':footer_valid,
        'successful_API_RR_recordings_confirmed':successful,'queued_RR_dispatches_confirmed_completed':queued,
        'discarded_API_RR_recordings_confirmed':discarded,
        'observed_output_frames_confirmed':min(observed['whole_u32_records']if observed_valid else 0,ones if presence_valid else 0,*(r['whole_raw_frames']if raw_valid[name]else 0 for name,r in lobes.items())),
        'counter_authority':counter_authority,'final_CPP_footer_valid':footer_valid,'semantically_valid_artifact_lower_bounds':artifact_lower_bounds,
        'totals_unknown':not footer_valid,'unified_count_status':('authoritative_footer_with_metadata_conflicts'if disagreements else'authoritative_footer')if footer_valid else'confirmed_lower_bounds_only_totals_unknown',
        'artifact_validity':{'successful_recorded_indices':recorded_valid,'observed_indices':observed_valid,'presence':presence_valid,'raw_lobes':raw_valid},
        'final_stdout_counters':final,'recording_evidence_counts':record_evidence,'queue_evidence_counts':queue_evidence,'discard_evidence_counts':discard_evidence,
        'successful_recorded_indices':recorded,'observed_indices':observed,'presence':{'present':presence_path.exists(),'values':list(presence),'ones':ones,'zeros':zeros,'invalid_values':other},
        'raw_lobes':lobes,'evidence_disagreements':disagreements,
        'counts_qualification':'Valid bounded CPP footer is authoritative for recorded/completed queued work under pinned source, even when metadata artifacts conflict or validation rejects. All artifact claims remain retained. Without a reliable bounded footer, only semantically valid registered-prefix/capacity artifact lower bounds are aggregated; totals remain unknown. Registered capacities never populate missing measurements.',
        'incomplete_child_native_work_may_exceed_confirmed_lower_bounds':bool(child_launched and not footer_valid),
        'metadata_acceptance_evaluated':False,'planned_counts_are_measurements':False,
        'accounting_artifacts':[artifact(folder/n)for n in('stdout.log','stderr.log','recorded_frame_indices.bin','observed_frame_indices.bin','output_presence.bin','diffuse.bin','specular.bin')]}
