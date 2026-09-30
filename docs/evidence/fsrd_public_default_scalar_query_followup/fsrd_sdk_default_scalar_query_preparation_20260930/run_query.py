"""Future one authorized query child only; never invoked by CPU preparation."""
from pathlib import Path
import argparse,hashlib,json,os,struct
from executor_evidence import safe_guard_load
from query_accounting import derive
HERE=Path(__file__).resolve().parent
RUNTIME=('resource_guard.json','stdout.log','stderr.log','query_values.bin','executor_attempt.json','query_work_accounting.json')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,v):
 with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(rows):
 for r in rows:assert Path(r['path']).stat().st_size==r['bytes']and sha(r['path'])==r['sha256'],r['path']
def main():
 p=argparse.ArgumentParser();p.add_argument('--execute-query',action='store_true',required=True);p.add_argument('--authorization',required=True);a=p.parse_args()
 reg=read(HERE/'registration.json');freeze=read(HERE/'pre_query_freeze.json');verify(freeze['owned']);verify(freeze['external_sources'])
 auth=read(a.authorization);assert auth['status']=='ROOT_AUTHORIZED_ONE_DEFAULT_SCALAR_QUERY_CONTEXT'
 assert auth['registration_sha256']==sha(HERE/'registration.json')and auth['freeze_sha256']==sha(HERE/'pre_query_freeze.json')and auth['command']==reg['command']
 review=auth['independent_prelaunch_review'];assert sha(review['path'])==review['sha256']
 assert read(review['path'])['status']=='READY_FOR_ROOT_PUBLIC_DEFAULT_SCALAR_QUERY_AUTHORIZATION'and not read(review['path'])['blocking_findings']
 folder=Path(reg['job']).parent;assert folder.is_dir()and not any((folder/n).exists()for n in RUNTIME)
 target=HERE/'execution_results.json';assert not target.exists()and not(HERE/'default_values.json').exists()
 temp=(HERE/'execution_TEMP').resolve();assert temp.drive.upper()=='F:'and HERE.resolve()in temp.parents and temp.is_dir()and not any(temp.iterdir())
 os.environ['TEMP']=str(temp);os.environ['TMP']=str(temp)
 attempt=dict(invocation_started=True,fresh_runtime_files_verified_absent=True,case_command_matches=True,before_guard_call_checkpointed=True,command=reg['command'])
 save(folder/'executor_attempt.json',attempt)
 report=dict(status='launch_attempt_checkpointed',actual_RRDispatch_API=0,caller_Configure=0,caller_Execute=0,query_work=None,accepted=False,provider_internal_GPU='unknown',SDK_private_callback_warnings='unavailable_unknown',authorization_sha256=sha(a.authorization))
 # Mutable result is updated only in this fresh owned execution, preserving actual work.
 def checkpoint():target.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 checkpoint()
 from native_resource_guard import run_guarded
 returned=None;error=None
 try:returned=run_guarded(reg['command'],folder,timeout=240,maximum_working_set=2147483648,minimum_available_memory=1073741824,interval=.2)
 except BaseException as e:error=type(e).__name__+': '+str(e)
 guard=safe_guard_load(folder,attempt,reg['command'],returned);work=derive(folder,guard)
 save(folder/'query_work_accounting.json',work);report.update(status='physical_work_checkpointed_before_acceptance',guard=guard,monitor_error=error,query_work=work);checkpoint()
 try:
  if error:raise RuntimeError(error)
  assert not guard['guard_load_evidence']['errors']and work['accepted'],'Query/diagnostic/numeric/output metadata rejected; physical work retained'
  verify(freeze['owned']);verify(freeze['external_sources'])
  values=[dict(key=k,float32_bits=b,float_value=struct.unpack('<f',struct.pack('<I',b))[0])for k,b in zip(reg['query_keys'],work['raw_float_bits'])]
  save(HERE/'default_values.json',dict(status='PUBLIC_DEFAULT_QUERY_VALUES_AWAITING_INDEPENDENT_POSTREVIEW_NOT_APPLIED',values=values,source_work_sha256=sha(folder/'query_work_accounting.json'),provider=reg['provider'],no_settings_applied=True,no_RRDispatch=True,provider_internal_GPU='unknown',SDK_callback_warnings='unavailable_unknown'))
  report.update(status='completed_query_only_awaiting_independent_postreview_not_applied',accepted=True);checkpoint()
 except BaseException as e:
  report.update(status='failed_preserved_query_only_no_retry',error=type(e).__name__+': '+str(e));checkpoint();raise
if __name__=='__main__':main()
