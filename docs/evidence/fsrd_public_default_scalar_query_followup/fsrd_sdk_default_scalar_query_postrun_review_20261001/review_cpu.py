"""Bounded saved-evidence review only. Never invoke SDK/probe/guard/scorer."""
from pathlib import Path
import hashlib,json,math,struct,sys,importlib.util
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent.parent
P=ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_preparation_20260930'
PRE=ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_prelaunch_review_20260930'
AUTH=ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_root_authorization_20261001.json'
OBS=ROOT/'tools_tmp/fsrd_default_scalar_query_root_tool_observations_20261001.json'
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate JSON key '+k)
  d[k]=v
 return d
def loads(b):return json.loads(b,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def read(p):return loads(Path(p).read_bytes())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(rows):
 for r in rows:assert rec(r['path'])==r,r['path']
def main():
 assert rec(AUTH)['sha256']=='b15bb2e4ec269fd98d6e0a179433fb703b16403bcc5060e2ca7d10d670f002bd'
 assert rec(OBS)['sha256']=='7a3469e98b1d24ebbbddbd6879a8ce5c6133fa48b44fa8b4170b48385aa2e300'
 auth=read(AUTH);obs=read(OBS);reg=read(P/'registration.json');freeze=read(P/'pre_query_freeze.json');manifest=read(P/'completion_manifest.json');pre=read(PRE/'completion_manifest.json')
 assert rec(P/'completion_manifest.json')['sha256']=='8606b76754f334665026d41c6815d3609de019808dc3961b0ec72c47d60e5f5d'
 assert rec(PRE/'completion_manifest.json')['sha256']=='126006946eca8b3211a41eb26ceb89a18a05fe89df39ce30f8422f2f227efd82'
 assert auth['status']=='ROOT_AUTHORIZED_ONE_DEFAULT_SCALAR_QUERY_CONTEXT' and auth['command']==reg['command']
 assert auth['registration_sha256']==rec(P/'registration.json')['sha256'] and auth['freeze_sha256']==rec(P/'pre_query_freeze.json')['sha256']
 for name in ('independent_prelaunch_review','independent_prelaunch_review_manifest'):
  r=auth[name];actual=rec(ROOT/r['path']);assert actual['bytes']==r['bytes'] and actual['sha256']==r['sha256']
 assert read(PRE/'review.json')['status']=='READY_FOR_ROOT_PUBLIC_DEFAULT_SCALAR_QUERY_AUTHORIZATION'
 inherited=manifest['owned']+manifest['external_sources']+pre['owned']+pre['external_records']+freeze['owned']+freeze['external_sources']
 unique_rows={r['path']:r for r in inherited}
 verify(list(unique_rows.values()));verify(auth['preparation_pins'])
 verify(obs['runtime_artifacts']+[obs['execution'],obs['default_values'],obs['authorization']])
 actual_rows=[rec(p)for p in reg['runtime_paths']]
 before=list(unique_rows.values())+[rec(AUTH),rec(OBS)]+actual_rows
 before={r['path']:r for r in before};save('pins_before.json',dict(records=list(before.values()),unique_records=len(before)))
 result=read(P/'execution_results.json');work=read(P/'planned_query/query_work_accounting.json');values=read(P/'default_values.json');stored=read(P/'planned_query/resource_guard.json');attempt=read(P/'planned_query/executor_attempt.json');guard=result['guard']
 assert result['status']=='completed_query_only_awaiting_independent_postreview_not_applied' and result['accepted']
 assert result['authorization_sha256']==rec(AUTH)['sha256'] and result['monitor_error'] is None
 assert result['query_work']==work
 assert result['actual_RRDispatch_API']==result['caller_Configure']==result['caller_Execute']==0
 assert guard['guard_load_evidence']['authority']=='direct_owned_guard_return' and not guard['guard_load_evidence']['errors']
 assert guard['guard_load_evidence']['returned_guard_valid'] and guard['guard_load_evidence']['stored_guard_valid']
 assert guard['guard_load_evidence']['stored_guard_claim']==stored
 assert {k:guard[k]for k in stored}==stored
 assert guard['executor_launch_attempt']==attempt and attempt['command']==reg['command']
 assert all(attempt[k]is True for k in ('invocation_started','fresh_runtime_files_verified_absent','case_command_matches','before_guard_call_checkpointed'))
 assert stored['status']=='completed' and stored['returncode']==0 and type(stored['child_pid'])is int and stored['child_pid']>0 and not stored['terminated_owned_child']
 assert stored['args']==reg['command']
 assert stored['timeout_seconds']==240 and stored['maximum_working_set_bytes']==2147483648 and stored['minimum_available_memory_bytes']==1073741824 and stored['sample_interval_seconds']==.2
 assert stored['minimum_observed_available_bytes']>=1073741824 and stored['peak_observed_working_set_bytes']<=2147483648 and stored['elapsed_seconds']<=240
 assert rec(P/'planned_query/resource_guard.json')['sha256']==guard['guard_load_evidence']['sha256']
 raw=(P/'planned_query/query_values.bin').read_bytes();assert len(raw)==24 and rec(P/'planned_query/query_values.bin')['sha256']=='5da237f78cc5546c678d4473ee415b19fc6aab3bd7ca6d5a839e562808895274'
 expected_bits=[1008981770,1065353216,1065353216,1199562752,1112014848,0];assert list(struct.unpack('<6I',raw))==expected_bits
 lines=(P/'planned_query/stdout.log').read_bytes().splitlines(keepends=True)
 assert len(lines)==19 and all(l.endswith(b'\r\n')for l in lines)
 assert lines[0].startswith(b'QUERY_EVENT ')and lines[1].startswith(b'QUERY_META ')and all(l.startswith(b'QUERY_EVENT ')for l in lines[2:])
 meta=loads(lines[1][len(b'QUERY_META '):]);events=[loads(l[len(b'QUERY_EVENT '):])for l in [lines[0]]+lines[2:]]
 assert len(events)==18
 assert events==work['valid_prefix_events'] and events[-1]==work['terminal_claim']
 COUNTERS=('create_entry','create_returned','created','query_entry','query_returned','query_ok','destroy_entry','destroy_returned','destroyed','rr_dispatch','configure','owned_execute')
 counts={k:0 for k in COUNTERS};keys=[6,1,2,3,4,5]
 stages=['boot','create_start','create_return']+[s for _ in keys for s in ('query_start','query_return')]+['destroy_start','destroy_return','complete']
 # Independent exact source-order reconstruction, separate from producer parser.
 for i,(v,stage)in enumerate(zip(events,stages)):
  assert v['stage']==stage and v['seq']==i and v['v']==1 and v['rc']==0
  assert not v['ownership_uncertain'] and v['d3d_errors']==v['d3d_warnings']==0 and v['accepted']==(i==17)
  if i==1:counts['create_entry']=1
  elif i==2:counts['create_returned']=counts['created']=1
  elif 3<=i<=14:
   q=(i-3)//2;assert v['key']==keys[q]
   if stage=='query_start':counts['query_entry']+=1;assert not v['nonnull'] and v['bits']==0
   else:counts['query_returned']+=1;counts['query_ok']+=1;assert v['nonnull'] and v['bits']==expected_bits[q]
  elif i==15:counts['destroy_entry']=1
  elif i==16:counts['destroy_returned']=counts['destroyed']=1
  assert {k:v[k]for k in COUNTERS}==counts
  if i<3 or i>14:assert v['key']==v['bits']==0 and v['nonnull']==(i==2)
 assert counts==work['counts_lower_bound']==obs['counts']
 assert all(meta[k]==v for k,v in dict(v=1,api=4202496,width=128,height=80,signals=34,checkerboard=0,create_flags=2,debug_layer=1,provider_path_verified=True,SDK_callback_warning_count_available=False).items())
 assert work['exact_returned_totals'] and not work['totals_unknown'] and work['accepted'] and not work['evidence_errors'] and work['pending_entry_not_completed_API'] is None
 assert (P/'planned_query/stderr.log').read_bytes()==b''
 # Reuse the frozen pure parser only after independent event reconstruction.
 spec=importlib.util.spec_from_file_location('fixed_query_accounting',P/'query_accounting.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 recomputed=module.derive(P/'planned_query',guard);assert recomputed==work
 assert values['source_work_sha256']==rec(P/'planned_query/query_work_accounting.json')['sha256']=='c05569b99dd15fa34cbe7c9b2a7d3700f989b49d0d593f2d74f1e2aa95afe50d'
 floats=list(struct.unpack('<6f',raw));assert all(math.isfinite(v)for v in floats)
 assert values['values']==obs['observed_default_values']
 for k,b,f,v in zip(keys,expected_bits,floats,values['values']):assert v==dict(key=k,float32_bits=b,float_value=f) and struct.pack('<f',v['float_value'])==struct.pack('<I',b)
 assert values['no_settings_applied'] and values['no_RRDispatch'] and values['provider']==reg['provider']
 names=['disocclusion threshold','cross bilateral normal strength','stability bias','maximum radiance','radiance clipping standard-deviation K','Gaussian kernel relaxation']
 old=[.1,.5,.5,40000.,40.,.5]
 original=ROOT/'OptiScaler/shaders/shader_tools/tests/fsrd_rr_runner.cpp';source=original.read_text()
 assert rec(original)['sha256']=='f6cfbecc4704d7f4f891f5c2ae88baf69546a316a9738ed03da0413d6ef0d077'
 assert 'const float values[]={.1f,.5f,.5f,40000.f,40.f,.5f};' in source
 comparison=[]
 for k,n,b,f,tuned in zip(keys,names,expected_bits,floats,old):
  tuned_raw=struct.pack('<f',tuned);comparison.append(dict(key=k,public_field=n,actual_default_float32_bits=b,actual_default_hex='0x%08x'%b,actual_default=f,original_B342_tuned_float32=struct.unpack('<f',tuned_raw)[0],original_B342_tuned_bits=struct.unpack('<I',tuned_raw)[0],different_bits=tuned_raw!=struct.pack('<I',b)))
 assert all(v['different_bits']for v in comparison)
 save('recomputed_saved_evidence.json',dict(status='PASSED_SAVED_QUERY_EVIDENCE_RECONSTRUCTION',prefix_events=18,metadata_lines=1,counts=counts,exact_returned_totals=True,totals_unknown=False,all_public_return_codes=0,accepted=True,raw_file=rec(P/'planned_query/query_values.bin'),values=comparison,actual_adapter_metadata=meta,guard=stored,direct_and_stored_guard_match=True,frozen_parser_recompute_exact=True,original_preparation_records_unchanged=72,original_external_records_unchanged=15,freeze_records_unchanged=70,prelaunch_owned_records_unchanged=84,allsix_default_vs_prior_tuned_bits_different=True,actual_review_queries_GPU_native_build_scores=0))
 verify(list(before.values()));save('pins_after.json',dict(records=[rec(r['path'])for r in before.values()],all_before_after_exact=True,unique_records=len(before)))
 print(json.dumps(dict(status='POSTRUN_CPU_REVIEW_PASSED',prefix_events=18,created=1,returned_OK_queries=6,destroyed=1,RR=0,Configure=0,caller_Execute=0,all_before_after_exact=True,actual_review_queries=0)))
if __name__=='__main__':main()
