"""Seal completed saved-evidence audit. No SDK/probe/GPU/build/scorer."""
from pathlib import Path
import hashlib,json,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent
P=ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_preparation_20260930'
PRE=ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_prelaunch_review_20260930'
AUTH=ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_root_authorization_20261001.json'
OBS=ROOT/'tools_tmp/fsrd_default_scalar_query_root_tool_observations_20261001.json'
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(p):return json.loads(Path(p).read_bytes())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
data=read(HERE/'recomputed_saved_evidence.json');reg=read(P/'registration.json');auth=read(AUTH);obs=read(OBS)
before=read(HERE/'pins_before.json')['records']
for r in before:assert rec(r['path'])==r
root_verifier=auth['root_verifier'];assert rec(root_verifier['path'])==root_verifier
save('final_pin_verification.json',dict(status='ALL_SOURCE_AND_ACTUAL_EVIDENCE_REMAIN_EXACT',records_checked=len(before),root_verifier_pin_verified=root_verifier,preparation_owned_records=72,preparation_external_records=15,freeze_owned_records=70,freeze_external_records=15,prelaunch_owned_records=84,source_CPP=reg['source'],EXE=reg['EXE'],provider=reg['provider'],actual_review_queries_GPU_native_build_scores=0))
save('review.json',dict(
 status='PASSED_PUBLIC_DEFAULT_SCALAR_QUERY_EVIDENCE_REVIEW',blocking_findings=[],
 scope='Independent CPU-only post-run review of the one authorized public scalar-query context; no probe/SDK/GPU/build/scorer rerun.',
 source_and_authority=dict(preparation=rec(P/'completion_manifest.json'),prelaunch=rec(PRE/'completion_manifest.json'),authorization=rec(AUTH),root_tool_observations=rec(OBS),source=reg['source'],EXE=reg['EXE'],provider=reg['provider']),
 actual_counts=data['counts'],exact_returned_totals=True,totals_unknown=False,accepted=True,
 reconstruction=dict(prefix_events=18,unique_terminal_complete_seq=17,metadata_lines=1,all_public_return_codes=0,query_key_order=[6,1,2,3,4,5],per_key_count=1,raw_float_bytes=24,raw_file=data['raw_file'],raw_bits_match_all_six_child_returns=True,metadata_float_values_match_raw_bits=True,frozen_pure_parser_matches_full_saved_work=True,caller_Configure=0,native_RR=0,caller_Execute=0),
 observed_default_values=data['values'],
 actual_guard=dict(child_pid=data['guard']['child_pid'],status=data['guard']['status'],returncode=data['guard']['returncode'],terminated_owned_child=data['guard']['terminated_owned_child'],timeout_seconds=240,maximum_working_set_bytes=2147483648,minimum_available_memory_bytes=1073741824,interval_seconds=.2,minimum_observed_available_bytes=data['guard']['minimum_observed_available_bytes'],peak_observed_working_set_bytes=data['guard']['peak_observed_working_set_bytes'],elapsed_seconds=data['guard']['elapsed_seconds'],samples=data['guard']['samples'],direct_and_stored_guard_matching=True,canonical_authority='direct_owned_guard_return',fresh_runtime_attempt_matches_registered_command=True),
 ordinary_D3D_errors=0,ordinary_D3D_warnings=0,child_stderr_bytes=0,ownership_uncertain=False,
 lifecycle='Frozen source keeps device, module and creation descriptors alive through successful explicit DestroyContext; actual destroy_return has rc0 and null context. This is public API success evidence, not a private GPU quiescence claim.',
 source_freeze_verification=dict(preparation_owned=72,preparation_external=15,freeze_owned=70,freeze_external=15,prelaunch_owned=84,all_before_after_byte_exact=True,root_authorization_and_tool_observations_exact=True),
 context_controls=dict(api=4202496,max_render_size=[128,80],signals=34,checkerboard=0,validation=2,debug_layer=1,provider_path_verified=True,adapter_metadata=data['actual_adapter_metadata']),
 cumulative_context_accounting=dict(qualification='Earlier totals are carried forward from the pinned root authorization, not independently re-derived here.',previous_RR_workload_contexts=auth['previous_RR_workload_native_contexts'],new_query_only_contexts=1,all_completed_SDK_contexts=auth['previous_all_completed_SDK_contexts']+1,public_default_queries_separate=6,RR_API_unchanged=auth['previous_successful_RR_API_recordings'],queued_RR_unchanged=auth['previous_queued_completed_RR'],recorded_only_discards_separate=auth['previous_recorded_only_discards'],no_API_omissions_separate=auth['previous_no_API_omissions_separate']),
 actual_review_work=dict(query_EXE_invocations=0,SDK_queries=0,native_RR=0,GPU_jobs=0,builds=0,scores=0),
 limits=[
  'These six values are actual public query results from this pinned provider and fresh context; all six differ in float32 bits from the original B342 tuned vector [.1,.5,.5,40000,40,.5].',
  'No Configure calls or settings application occurred. This query run measured no RR output or default-vector image response.',
  'SDK private callback warnings remain unavailable/unknown because no global-debug Configure callback was installed. Ordinary D3D InfoQueue diagnostics and public return codes were observed separately.',
  'Provider-internal GPU initialization, private shader dispatches and internal queue behavior remain unknown; caller Execute is structurally and physically zero.',
  'No quality, physical-reference validity, game cause, vendor bug or production-fix conclusion follows. A matched default-vector RR test requires separate preparation and authorization.',
  'Root tool observations identify the once driver exit0/empty tool output separately from the retained actual child stdout/stderr/guard files.'
 ]))
with(HERE/'compact.md').open('x',encoding='utf-8',newline='\n')as f:
 f.write('Passed public default scalar query evidence review; no blocking findings. Independently reconstructed all18 events:1 created context,6 entered/returned/successful Queries,1 successful Destroy,0 RR/Configure/caller Execute. All return codes were0; the unique complete footer and matching direct/stored owned-child guard establish exact returned totals. Ordinary D3D errors/warnings were0 and child stderr was empty.\n\n')
 f.write('In key order6,1,2,3,4,5, actual float32 defaults are0.009999999776482582,1,1,65504,50,0. The24 raw bytes exactly match child return bits and saved JSON values. These correspond to disocclusion threshold, normal strength, stability bias, maximum radiance, clipping K and Gaussian relaxation. All six differ from the original runner\'s tuned vector0.1,0.5,0.5,40000,40,0.5. No settings were applied and no image response was measured.\n\n')
 f.write('All72 preparation records plus15 external pins,70+15 freeze records and84 prelaunch records remained exact. The review ran only saved-evidence CPU checks:0 SDK/probe/GPU/build/scorer work. Prior root totals carry forward to415 completed SDK contexts, comprising414 RR workloads and1 query-only context; RR API22074/queued22066 are unchanged, with8 recorded discards and4 separate no-API omissions. The6 public Queries are a separate count.\n\n')
 f.write('SDK callback warnings and provider-internal GPU work remain unknown. Successful Destroy is public API cleanup evidence without a private quiescence guarantee. These defaults support a separately prepared matched diagnostic; they establish no quality, game cause or production fix.\n')
for r in before:assert rec(r['path'])==r
externals=[rec(P/'completion_manifest.json'),rec(PRE/'completion_manifest.json'),rec(AUTH),rec(OBS),root_verifier]+[rec(p)for p in reg['runtime_paths']]
assert len({r['path']for r in externals})==len(externals)
save('completion_manifest.json',dict(status='SEALED_PASSED_PUBLIC_DEFAULT_SCALAR_QUERY_EVIDENCE_REVIEW',blocking_findings=[],self_entry_excluded=True,owned=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name!='completion_manifest.json'],external_records=externals,inheritance=[dict(manifest=str(P/'completion_manifest.json'),record_keys=['owned','external_sources'],records=87),dict(manifest=str(PRE/'completion_manifest.json'),record_keys=['owned','external_records'],records=85)],actual_review_queries_GPU_native_build_scores=0,actual_original_query_contexts=1,actual_original_successful_public_queries=6,actual_original_successful_destroy=1,actual_original_RR_Configure_callerExecute=0))
for n in('review.json','completion_manifest.json'):print(json.dumps(rec(HERE/n)))
