"""Source/EXE/control preparation seal only; query launcher is never imported."""
from pathlib import Path
import ast,hashlib,json,subprocess
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();assert head=='50e376ce8c99739efbd9a86055dbe4995d50155e'
before=read(HERE/'pre_compile_freeze.json')
for r in before['owned']+before['external_sources']:assert rec(r['path'])==r,r['path']
build=read(HERE/'build_result.json');assert build['passed']and build['actual_compile_invocations']==1 and build['query_EXE_invocations']==0
assert build['guard']['returncode']==0 and build['guard']['status']=='completed'and not build['guard']['terminated_owned_child']
assert(HERE/'compile_runtime/stderr.log').read_bytes()==b''
stdout=(HERE/'compile_runtime/stdout.log').read_bytes();assert b'warning'in stdout.lower()is False if False else b'warning'not in stdout.lower()
signature=read(HERE/'provider_signature.json');assert signature['Status']=='Valid'and signature['MetadataOnlyNoSDKLoaded']and 'Advanced Micro Devices'in signature['SignerSubject']
checks=read(HERE/'CPU_checks.json');assert checks['passed']==11 and checks['failed']==0 and checks['actual_query_native_GPU_build_scores']==0
assert read(HERE/'CPU_pending_entry_check.json')['passed']
for p in HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
runtime=['resource_guard.json','stdout.log','stderr.log','query_values.bin','executor_attempt.json','query_work_accounting.json']
folder=HERE/'planned_query';assert sorted(p.name for p in folder.iterdir())==['job.txt']
for n in runtime:assert not(folder/n).exists()
assert not(HERE/'execution_results.json').exists()and not(HERE/'default_values.json').exists()
temp=(HERE/'execution_TEMP').resolve();assert temp.is_dir()and not any(temp.iterdir())and temp.drive.upper()=='F:'and HERE.resolve()in temp.parents
source=(HERE/'fsrd_default_query.cpp').read_text();assert source.count('api.CreateContext(')==source.count('api.Query(')==source.count('api.DestroyContext(')==1
assert 'api.Configure('not in source and 'api.Dispatch('not in source
assert all(s not in source for s in('CreateCommandQueue(','CreateCommandList(','CreateCommandAllocator(','CreateCommittedResource(','ExecuteCommandLists(','WaitForSingleObject(','SetEventOnCompletion('))
provider=next(r for r in before['external_sources']if Path(r['path']).name=='amd_fidelityfx_denoiser_dx12.dll')
save('source_and_lifecycle_schema.json',dict(status='PINNED_FIXED_QUERY_PROBE_SCHEMA',HEAD=head,source=rec(HERE/'fsrd_default_query.cpp'),EXE=rec(HERE/'fsrd_default_query.exe'),
 query_key_order=[6,1,2,3,4,5],query_count=1,float_elements=1,float_bytes=4,query_output_bits_authoritative=True,
 context=dict(api=4202496,max_render_size=[128,80],signals=34,checkerboard=0,create_flags=2,allocator_callbacks='nullptr',same_B342_create_descriptor=True,global_debug_Configure_omitted=True),
 source_API_sites=dict(Create=1,Query=1,Query_loop_capacity=6,Destroy=1,Configure=0,Dispatch=0,caller_Execute=0),
 grammar='QUERY_EVENT strictJSON v1/seq/stage/key/rc/nonnull/rawbits/12physical-or-entrycounters/d3d_errors/d3d_warnings/ownership_uncertain/accepted; exactfull-line stdoutonly. QUERY_META contains exact context/adapter/driver/path-check; metadata is a separate acceptancegate.',
 prefix_law='Entry marker is a pending call boundary, not a successful/returnedcall. Legal returnevent counts before acceptance; call-before-egress gap, truncation/unknown/duplicate terminals keep lowerbounds and unknown totals. Metadata/file/diagnostic rejection preserves actualwork.',
 cleanup='Create/backend/device/values/module descriptors remainalive until explicitDestroy. One cleanupattempt forKnownLive even if stdout start loggingfails. FailedCreate-nonnull/failedDestroy retainsowners until ExitProcess; no speculative retry/unload or inventedDestroycount.',
 unknowns='Provider-internalGPU/initialization/queues and privatecallbackwarnings unknown. Configure0 means no SDK loggingcallback. Query support and numericdefaults still unmeasured.',
 source_cpp_no_RR_no_configuration_no_caller_submission=True))
save('registration.json',dict(status='PREPARED_QUERY_ONLY_NOT_AUTHORIZED',job=str((folder/'job.txt').resolve()),command=[str((HERE/'fsrd_default_query.exe').resolve()),str((folder/'job.txt').resolve())],
 provider=provider,source=rec(HERE/'fsrd_default_query.cpp'),EXE=rec(HERE/'fsrd_default_query.exe'),query_keys=[6,1,2,3,4,5],
 design=next(r for r in before['external_sources']if Path(r['path']).name=='design.json'),schema=rec(HERE/'source_and_lifecycle_schema.json'),provider_signature=rec(HERE/'provider_signature.json'),
 planned_only_if_completed=dict(fresh_created_contexts=1,successful_default_queries=6,returned_default_queries=6,successfully_destroyed_contexts=1,RRDispatch_API=0,Configure_API=0,caller_Execute=0),
 actual_query_work=dict(contexts=0,queries=0,RRDispatch_API=0,caller_Execute=0),actual_CPU_compiles=1,query_EXE_invocations=0,
 guard=dict(timeout_seconds=240,maximum_working_set_bytes=2147483648,minimum_available_memory_bytes=1073741824,interval_seconds=.2,TEMP_TMP=str(temp),single_owned_child=True),
 authorization_contract=dict(required=True,status='ROOT_AUTHORIZED_ONE_DEFAULT_SCALAR_QUERY_CONTEXT',fields=['registration_sha256','freeze_sha256','command','independent_prelaunch_review.path','independent_prelaunch_review.sha256'],review_status='READY_FOR_ROOT_PUBLIC_DEFAULT_SCALAR_QUERY_AUTHORIZATION',query_once_only=True),
 runtime_paths=[str(folder/n)for n in runtime]+[str(HERE/'execution_results.json'),str(HERE/'default_values.json')],
 actual_defaults_unobserved=True,no_defaults_assumed_or_applied=True,no_models_scores_or_RRsettings=True,provider_internal_GPU='unknown',SDK_private_callback_warnings='unavailable_unknown',quality_accepted=False,
 invocation_after_review_root_authorization_only='python -B run_query.py --execute-query --authorization <immutable root authorization.json>',
 cleanup_limit='OSowned-process exit after unresolved ownership is not API-cleanup proof; no other process is terminated or inspected.'))
seal_names={'pre_query_freeze.json','readiness.json','completion_manifest.json'}
assert not any((HERE/n).exists()for n in seal_names)
save('pre_query_freeze.json',dict(status='FROZEN_QUERY_CPU_PREPARATION_NOT_AUTHORIZATION',owned=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name not in seal_names],external_sources=before['external_sources'],self_entry_excluded=True,actual_queries_RRDispatch_contexts=0))
save('readiness.json',dict(status='READY_FOR_INDEPENDENT_PUBLIC_DEFAULT_QUERY_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',blocking_findings=[],registration=rec(HERE/'registration.json'),freeze=rec(HERE/'pre_query_freeze.json'),
 source=rec(HERE/'fsrd_default_query.cpp'),EXE=rec(HERE/'fsrd_default_query.exe'),build_result=rec(HERE/'build_result.json'),CPU_checks=rec(HERE/'CPU_checks.json'),pending_entry_check=rec(HERE/'CPU_pending_entry_check.json'),
 mature_guard_byte_exact=True,canonical_guard_loader_byte_exact=True,SDK_signature_valid=True,all_query_runtime_absent=True,ownedF_TEMP_empty=True,CPU_compile_invocations=1,compiler_exit=0,compiler_warnings=0,query_EXE_invocations=0,actual_contexts_queries_RRDispatch=0,
 limits='No observeddefaults/SDKquery/providerLoad/native/GPU; compileronlyCPU. SDKprivatecallbackwarnings unavailable and providerinternalGPUunknown in future probe. Requires independentprelaunchreview andimmutableRootauth before query.',
 reviewer_preparation_lookup_failures='Initial read guessed prior compile_cpu.py/fsrd_toolchain.ps1 paths returned missing; correct existing compile_once.py and shader_tools/fsrd_toolchain.py then read. No source/native work from these lookups.'))
save('completion_manifest.json',dict(status='SEALED_CPU_QUERY_PREPARATION_AWAITING_INDEPENDENT_REVIEW',owned=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name!='completion_manifest.json'],external_sources=before['external_sources'],self_entry_excluded=True,no_manifest_cycles=True,actual_CPU_compile=1,query_EXE_invocations=0,actual_contexts_queries_RRDispatch=0))
for n in('registration.json','pre_query_freeze.json','readiness.json','completion_manifest.json'):print(json.dumps(rec(HERE/n)))
