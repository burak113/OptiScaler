"""Seal completed CPU-only review; no executable/SDK/guard invocation."""
from pathlib import Path
import hashlib,json,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
P=HERE.parent/'fsrd_sdk_default_scalar_query_preparation_20260930'
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(p):return json.loads(Path(p).read_bytes())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
before=read(HERE/'pins_before.json')['records']
for r in before:assert rec(r['path'])==r,r['path']
reg=read(P/'registration.json');assert all(not Path(p).exists()for p in reg['runtime_paths'])
assert not any((P/'execution_TEMP').iterdir())
assert read(HERE/'replay_checks.json')['completed_checks']==12
assert read(HERE/'independent_checks.json')['passed']==8
save('final_source_pin_check.json',dict(all_before_after_exact=True,records_checked=len(before),runtime_paths_absent=reg['runtime_paths'],execution_TEMP_empty=True,actual_queries=0,actual_native_RR=0,actual_GPU_jobs=0,actual_builds=0,actual_scores=0))
save('tool_observations.json',dict(label='Review tool observations, not producer execution logs',CPU_review_command=dict(script='review_cpu.py',exit_code=0,tool_chunk='8a39e2',observed_stdout='CPU_REVIEW_CHECKS_PASSED; 72 owned/15 external; freeze70/15; SIMULATED12; actualqueries0'),CPU_independent_command=dict(script='check_independent_cpu.py',exit_code=0,tool_chunk='12a737',observed_stdout='SIMULATED_checks_passed8; actualqueries0'),signature_metadata_only=dict(status='Valid',Status_numeric=0,StatusMessage='Signature verified.',SignerSubject='CN=Advanced Micro Devices, O=Advanced Micro Devices, S=California, C=US',SignerThumbprint='33D35682079E201671B738B7209B4586103BC271',provider_loaded_by_review=False),actual_review_native_or_GPU=0))
save('review.json',dict(
 status='READY_FOR_ROOT_PUBLIC_DEFAULT_SCALAR_QUERY_AUTHORIZATION',blocking_findings=[],
 scope='Independent CPU-only prelaunch review of the sealed fixed six-key query probe. No query executable, SDK, GPU, build or scorer invocation.',
 producer=dict(registration=rec(P/'registration.json'),freeze=rec(P/'pre_query_freeze.json'),readiness=rec(P/'readiness.json'),completion=rec(P/'completion_manifest.json'),source=reg['source'],EXE=reg['EXE'],provider=reg['provider'],design=reg['design']),
 source_and_header_findings=dict(API=4202496,max_render_size=[128,80],signals=34,checkerboard=0,validation_flags=2,adapter='First high-performance adapter, feature level12.0, same B342 selection',strict_debug_layer=True,default_scalar_keys=[6,1,2,3,4,5],query_count_per_key=1,scalar_bytes=4,source_Create_sites=1,source_Query_sites=1,loop_maximum_queries=6,source_Destroy_sites=1,Configure_calls=0,RR_calls=0,caller_Execute_calls=0,caller_queues_lists_fences_textures=False,query_before_any_configuration=True,public_query_desc_matches_local_header=True,no_actual_defaults_observed=True),
 lifetime_findings=[
  'Create/backend descriptors, device and provider module remain alive through explicit successful DestroyContext.',
  'Known-live context receives one cleanup attempt even if destroy_start logging fails. The attempt is not automatically counted as success.',
  'Failed Create with non-null context or failed Destroy marks ownership uncertain and invokes ExitProcess while descriptors/device/module remain alive; no speculative retry/unload or quiescence claim.',
  'Logging or output failure may leave missing return events/footer: returned totals then remain unknown; observed source-valid prefix is retained.'
 ],
 accounting_findings=dict(call_entry_markers_are_not_returned_API_proof=True,separate_counters=['create_entry','create_returned','created','query_entry','query_returned','query_ok','destroy_entry','destroy_returned','destroyed'],source_fixed_sequence_and_query_order=True,exact_zero_Configure_RR_callerExecute=True,physical_checkpoint_before_strict_acceptance=True,canonical_direct_guard_authority=True,explicit_nochild_stale_claims_not_actual_work=True,fresh_missing_guard_prefix='Qualified lowerbounds only; process identity and exact totals unknown',metadata_raw_numeric_or_diagnostic_rejection_preserves_work=True,duplicate_truncated_impossible_events_rejected=True),
 verification=dict(completion_owned_records=72,completion_external_records=15,freeze_owned_records=70,freeze_external_records=15,self_excluded_manifests=True,unique_before_after_records_checked=88,all_byte_exact=True,provider_signature_valid=True,producer_CPU_compile_invocations=1,compiler_stdout_bytes=24,compiler_stdout='fsrd_default_query.cpp CRLF',compiler_stderr_bytes=0,compiler_exit=0,compiler_warnings_observed=0,compiler_guard_current_child=True,CPU_fixed_replay_checks=12,CPU_independent_SIMULATED_checks=8,all_checks_passed=True,runtime_paths_absent=8,owned_F_TEMP_empty=True),
 guard_contract=dict(timeout_seconds=240,maximum_working_set_bytes=2147483648,minimum_available_memory_bytes=1073741824,interval_seconds=.2,owned_child_only=True,guard_byte_exact=True,F_TEMP_TMP=True),
 actual_review_work=dict(SDK_contexts=0,SDK_queries=0,native_RR_API=0,GPU_jobs=0,builds=0,scores=0),
 planned_only_if_completed=reg['planned_only_if_completed'],
 qualifications=[
  'This is prelaunch readiness, not execution authorization. Root must bind the exact registration/freeze/command and this review hash in its immutable authorization.',
  'SDK private callback warnings are unavailable/unknown because Configure is intentionally zero; ordinary D3D InfoQueue messages and public return codes remain strict acceptance evidence.',
  'Provider internal queues, initialization/GPU work and private semantics remain unknown. Caller submission is structurally zero.',
  'Source-equivalent B342 creation does not imply old tuned settings equal provider defaults. No settings are assumed or applied.',
  'OS process exit after uncertain ownership does not prove successful API cleanup or GPU quiescence.',
  'No quality, game-cause, model or production behavior claim follows from these queries.'
 ]))
with(HERE/'compact.md').open('x',encoding='utf-8',newline='\n')as f:
 f.write('Ready for root authorization of one query-only context. No blocking findings. The sealed source selects the B342 high-performance adapter/device path, creates API1.2 at128x80 with signals34/checkerboard0/validation2, then queries scalar keys6,1,2,3,4,5 with count1 before any configuration. It has no Configure, RR or caller queue/list/fence/texture/submission path.\n\n')
 f.write('Verified72 preparation and15 external records, plus the70+15 freeze;88 unique before/after records remained exact. The recorded single CPU compile succeeded with24 source-filename stdout bytes, zero stderr and an owned-child monitor. All12 existing simulations and8 independent fixed-probe regressions passed. All8 runtime paths are absent and F TEMP is empty. This review invoked0 SDK/query/GPU/build/scorer jobs.\n\n')
 f.write('Failed non-null Create and failed Destroy retain uncertain ownership until process exit. Call-entry markers never become returned/successful API proof. Missing/corrupt footer or pending call leaves unknown totals; metadata, raw-byte or diagnostic rejection preserves qualified physical work. Direct guard return has authority over conflicting stored markers; explicit no-child claims cannot become work.\n\n')
 f.write('Only if completed, the future plan is1 created context,6 successful default queries,1 successful Destroy and0 RR/Configure/caller Execute. Defaults remain unobserved and unapplied. SDK callback diagnostics and provider-internal GPU work are unknown. API cleanup, quality and game cause are not established. Root execution authorization remains separate.\n')
for r in before:assert rec(r['path'])==r
save('completion_manifest.json',dict(status='SEALED_READY_CPU_ONLY_DEFAULT_SCALAR_QUERY_PRELAUNCH_REVIEW',self_entry_excluded=True,owned=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name!='completion_manifest.json'],external_records=[rec(P/'completion_manifest.json')],external_inheritance=dict(manifest=str(P/'completion_manifest.json'),record_keys=['owned','external_sources'],expanded_producer_records=87,include_inherited_manifest_itself=True,expanded_unique_total=88),blocking_findings=[],actual_review_queries_native_GPU_build_scores=0))
for n in('review.json','completion_manifest.json'):print(json.dumps(rec(HERE/n)))
