"""Measured native stages before acceptance, with explicit missing-output causes.

API/queue accounting retains the byte-pinned V3 rule. Missing output is not an
SDK discard by itself: an uncalled API omission is recorded separately.
"""
from pathlib import Path
import re
from native_work_accounting_core_v3 import derive as derive_core,indices,artifact
def derive(folder,guard,case):
    folder=Path(folder);v=derive_core(folder,guard,case)
    omitted=indices(folder/'omitted_API_frame_indices.bin');expected=case['omitted_API_frame_indices']
    omitted_valid=omitted['trailing_bytes']==0 and omitted['values']==expected[:len(omitted['values'])]and len(omitted['values'])<=len(expected)
    log=''.join((folder/name).read_text(errors='replace')for name in('stdout.log','stderr.log')if(folder/name).exists())
    m=re.search(r'RR_recordings=(\d+) queued_RR_dispatches=(\d+) discarded_RR_recordings=(\d+) validation_errors=(\d+) validation_warnings=(\d+) sdk_errors=(\d+) sdk_warnings=(\d+) no_API_omissions=(\d+)',log)
    final_omitted=None if m is None else int(m.group(8))
    omission_footer_valid=v['final_CPP_footer_valid']and final_omitted is not None and 0<=final_omitted<=case['frames_omitted_API']and v['final_stdout_counters']['successful_API_RR_recordings']+final_omitted<=case['loop_frames']
    omission_count=final_omitted if omission_footer_valid else omitted['whole_u32_records']if omitted_valid else 0
    # A presence-zero slot may be no-API. Confirm an SDK discard lower bound
    # only with a valid successful API record for that exact skip-frame.
    valid_recorded=set(v['successful_recorded_indices']['values'])if v['artifact_validity']['successful_recorded_indices']else set()
    valid_absent={case['consumed_source_frame_indices'][i]for i,b in enumerate(v['presence']['values'])if b==0}if v['artifact_validity']['presence']else set()
    discarded_lower=int(case['skip_frame']>=0 and case['skip_frame']in valid_recorded and case['skip_frame']in valid_absent)
    v['semantically_valid_artifact_lower_bounds']['discarded_RR_recordings']=discarded_lower
    if not v['final_CPP_footer_valid']:v['discarded_API_RR_recordings_confirmed']=discarded_lower
    v['discard_evidence_counts']['missing_output_presence_zeros']=v['discard_evidence_counts'].pop('presence_zeros')
    v['discard_evidence_counts']['valid_successful_API_discard_presence_lower_bound']=discarded_lower
    v['evidence_disagreements']=[s for s in v['evidence_disagreements']if s!='presence_zeros_vs_final_stdout']
    if not omitted_valid:v['evidence_disagreements'].append('omitted_API_indices_not_registered_prefix')
    if final_omitted is not None and not omission_footer_valid:v['evidence_disagreements'].append('final_CPP_omission_footer_invalid')
    if omission_footer_valid and omitted['whole_u32_records']!=final_omitted:v['evidence_disagreements'].append('omitted_API_indices_vs_final_stdout')
    if v['final_CPP_footer_valid']and omission_footer_valid and v['presence']['present']and v['artifact_validity']['presence']and v['presence']['zeros']!=v['final_stdout_counters']['discarded_RR_recordings']+final_omitted:
        v['evidence_disagreements'].append('missing_output_presence_vs_final_discard_plus_omission')
    v['schema']='matched-gap-actual-stage-accounting-before-acceptance-v1'
    v['omitted_API_frame_indices']=omitted;v['artifact_validity']['omitted_API_indices']=omitted_valid
    v['no_API_omissions_confirmed']=omission_count;v['final_stdout_no_API_omissions']=final_omitted
    v['omission_counter_authority']='valid_bounded_final_CPP_footer_under_pinned_source'if omission_footer_valid else'valid_omitted_index_prefix_lower_bound_total_unknown'
    v['API_RR_totals_unknown']=v['totals_unknown'];v['omission_total_unknown']=not omission_footer_valid
    v['totals_unknown']=v['API_RR_totals_unknown']or v['omission_total_unknown']
    v['completed_native_context_final_marker']=v['final_CPP_footer_valid']and omission_footer_valid
    v['incomplete_child_native_work_may_exceed_confirmed_lower_bounds']=v['attempted_owned_child']and v['totals_unknown']
    v['unified_count_status']=('authoritative_stage_footers_with_metadata_conflicts'if v['evidence_disagreements']else'authoritative_stage_footers')if not v['totals_unknown']else'qualified_per_stage_counts_totals_unknown'
    v['stage_count_qualification']='API/queue/discard footer partition is successfulAPI=queued+SDKdiscard. Missing-output presence zeros combine SDKdiscard and noAPIomission and alone never prove a successful SDK discard. Omissions have their own pinned CPP footer and source-index evidence. Valid bounded footer counters are retained despite metadata rejection; without reliable footer only valid semantic prefix lower bounds are confirmed and totals remain unknown.'
    v['accounting_artifacts'].append(artifact(folder/'omitted_API_frame_indices.bin'))
    return v
