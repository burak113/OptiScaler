"""Fixed-probe SIMULATED accounting fixtures; no SDK/native/helper execution."""
from pathlib import Path
import ast,copy,json,struct
from query_accounting import derive,COUNTERS
from executor_evidence import safe_guard_load
HERE=Path(__file__).resolve().parent
ROOT=HERE/'SIMULATED_CPU'
def save(p,v):
 with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def make(failure=None):
 counters={k:0 for k in COUNTERS};events=[];ambiguous=False
 def event(stage,key=0,rc=0,nonnull=False,bits=0,accepted=False):
  events.append(dict(v=1,seq=len(events),stage=stage,key=key,rc=rc,nonnull=nonnull,bits=bits,**counters,d3d_errors=0,d3d_warnings=0,ownership_uncertain=ambiguous,accepted=accepted))
 event('boot');counters['create_entry']=1;event('create_start');counters['create_returned']=counters['created']=1;event('create_return',rc=0,nonnull=True)
 raw=[]
 for i,key in enumerate((6,1,2,3,4,5)):
  counters['query_entry']+=1;event('query_start',key)
  counters['query_returned']+=1;rc=6 if failure==i else 0
  if rc==0:counters['query_ok']+=1
  bits=0x7fc12345 if rc else 0x3f800000;raw.append(bits);event('query_return',key,rc,True,bits)
  if rc:break
 counters['destroy_entry']=1;event('destroy_start');counters['destroy_returned']=counters['destroyed']=1;event('destroy_return')
 event('complete'if failure is None else'failed',accepted=failure is None)
 meta=dict(v=1,api=4202496,width=128,height=80,signals=34,checkerboard=0,create_flags=2,debug_layer=1,provider_path_verified=True,SDK_callback_warning_count_available=False)
 lines=[b'QUERY_EVENT '+json.dumps(events[0]).encode()+b'\n',b'QUERY_META '+json.dumps(meta).encode()+b'\n']+[b'QUERY_EVENT '+json.dumps(v).encode()+b'\n'for v in events[1:]]
 return lines,b''.join(struct.pack('<I',b)for b in raw)
def main():
 assert not(HERE/'CPU_checks.json').exists();ROOT.mkdir(exist_ok=False)
 YES=dict(child_pid=123,status='completed',returncode=0);NO=dict(child_pid=None,status='not_launched_low_available_memory',returncode=None)
 attempt={k:True for k in('invocation_started','fresh_runtime_files_verified_absent','case_command_matches','before_guard_call_checkpointed')}
 rows=[]
 def test(name,lines,raw,guard,expected=None):
  f=ROOT/name;f.mkdir();(f/'stdout.log').write_bytes(b''.join(lines));(f/'stderr.log').write_bytes(b'');(f/'query_values.bin').write_bytes(raw)
  result=derive(f,guard);assert expected(result),name;rows.append(dict(name=name,SIMULATED=True,passed=True,result=result));return f
 complete,raw=make()
 test('complete6',complete,raw,YES,lambda r:r['accepted']and r['exact_returned_totals']and r['counts_lower_bound']['created']==1 and r['counts_lower_bound']['query_ok']==6 and r['counts_lower_bound']['destroyed']==1)
 partial,praw=make(2)
 test('failed_query3_preserved',partial,praw,dict(YES,status='failed_or_terminated',returncode=1),lambda r:not r['accepted']and r['exact_returned_totals']and r['counts_lower_bound']['query_returned']==3 and r['counts_lower_bound']['query_ok']==2 and r['counts_lower_bound']['destroyed']==1)
 test('missing_footer_unknown_not_false0',complete[:-1],raw,YES,lambda r:not r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6 and r['counts_lower_bound']['destroyed']==1)
 test('explicit_nochild_stale_footer0',complete,raw,NO,lambda r:r['known_no_child']and not r['exact_returned_totals']and all(v==0 for v in r['counts_lower_bound'].values())and not r['accepted'])
 test('fresh_missing_guard_lowerbounds',complete,raw,dict(status='guard_evidence_unavailable',child_pid=None,returncode=None,executor_launch_attempt=attempt),lambda r:not r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6 and r['totals_unknown'])
 test('metadata_raw_missing_retains6',complete,b'',YES,lambda r:r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6 and not r['accepted'])
 test('duplicate_terminal_no_exact',complete+[complete[-1]],raw,YES,lambda r:not r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6)
 test('truncated_terminal_prefix_retains6',complete[:-1]+[complete[-1][:-1]],raw,YES,lambda r:not r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6)
 bad=copy.deepcopy(complete);value=json.loads(bad[-1][len(b'QUERY_EVENT '):]);value['query_ok']=64;bad[-1]=b'QUERY_EVENT '+json.dumps(value).encode()+b'\n'
 test('impossible_counter64_not_capacity',bad,raw,YES,lambda r:not r['exact_returned_totals']and r['counts_lower_bound']['query_ok']==6)
 # Both canonical direct-return conflict directions use exact mature guard loader.
 for name,stored,returned,wanted in [('returned_child_stored_nochild',NO,YES,6),('returned_nochild_stored_child',YES,NO,0)]:
  f=ROOT/name;f.mkdir();(f/'stdout.log').write_bytes(b''.join(complete));(f/'stderr.log').write_bytes(b'');(f/'query_values.bin').write_bytes(raw);(f/'resource_guard.json').write_text(json.dumps(stored))
  guard=safe_guard_load(f,attempt,['SIMULATED_NOT_RUN'],returned);result=derive(f,guard)
  assert result['counts_lower_bound']['query_ok']==wanted and not result['accepted']and guard['guard_load_evidence']['errors'];rows.append(dict(name=name,SIMULATED=True,passed=True,result=result))
 source=(HERE/'fsrd_default_query.cpp').read_text();assert source.count('api.CreateContext(')==source.count('api.Query(')==source.count('api.DestroyContext(')==1
 assert 'api.Configure('not in source and 'api.Dispatch('not in source
 assert all(v not in source for v in('CreateCommandQueue(','CreateCommandList(','CreateCommandAllocator(','CreateCommittedResource(','ExecuteCommandLists(','SetEventOnCompletion(','WaitForSingleObject('))
 assert 'try{s.event("destroy_start");}catch'in source and 'ExitProcess(1);'in source
 for p in HERE.glob('*.py'):ast.parse(p.read_text())
 save(HERE/'CPU_checks.json',dict(status='PASSED_FIXED_QUERY_PROBE_CPU_CHECKS',SIMULATED_checks=rows,passed=len(rows),failed=0,synthetic_values_not_provider_defaults=True,source_has_oneCreate_oneQuery_loop_oneDestroy=True,source_Configure_RR_submission_resource_paths_absent=True,actual_query_native_GPU_build_scores=0))
 print(json.dumps(dict(status='CPU_checks_passed',probes=len(rows),actual_query_native_GPU=0)))
if __name__=='__main__':main()
