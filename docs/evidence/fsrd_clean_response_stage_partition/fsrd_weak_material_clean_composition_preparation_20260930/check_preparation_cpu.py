"""Bounded SIMULATED helper accounting and oldB frozen scorer checks; no real helper/native/GPU."""
from pathlib import Path
import sys,ast,types,json,hashlib,importlib.util
sys.dont_write_bytecode=True
import numpy as np
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def identity(p):p=Path(p);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(n,o):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(o,f,indent=2,allow_nan=False);f.write('\n')
def module(n,p):s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 reg=read(HERE/'registration.json');assert len(reg['jobs'])==192
 m=module('composition_helper_accounting_CPU',HERE/'helper_work_accounting.py');g=module('composition_guard_loader_CPU',HERE/'helper_guard_evidence.py')
 YES=dict(status='completed',child_pid=123,returncode=0,terminated_owned_child=False);NO=dict(status='not_launched_low_available_memory',child_pid=None,returncode=None)
 checks=[];root=HERE/'SIMULATED_CPU';root.mkdir(exist_ok=False)
 for name,stored,returned,warning,wanted,known in [('valid_helper_marker_outputs',YES,YES,0,1,True),('diagnostic_reject_retains_dispatch',YES,YES,1,1,True),('nochild_stale_marker_reject',NO,NO,0,0,True),('stored_child_returned_nochild_canonical',YES,NO,0,0,True),('stored_nochild_returned_child_canonical',NO,YES,0,1,False),('fresh_missing_guard_marker_lowerbound',None,{},0,1,False)]:
  folder=root/name;folder.mkdir();(folder/'stdout.log').write_bytes(f'adapter=SIMULATED\ngpu_ms_median=0.1 gpu_ms_p95=0.1 debug_layer=1\nvalidation_errors=0 validation_warnings={warning}\n'.encode());(folder/'stderr.log').write_bytes(b'')
  outputs=[]
  for i in range(3):p=folder/f'out{i}.bin';p.write_bytes(bytes(4));outputs.append(dict(path=str(p),bytes=4))
  if stored is not None:(folder/'resource_guard.json').write_text(json.dumps(stored)+'\n')
  guard,error,artifact=g.load_guard_best_effort(folder,returned,None);work=m.accounting(folder,outputs,guard,error,fresh_scope_authenticated=True)
  passed=work['confirmed_shader_dispatches_lower_bound']==wanted
  if name=='valid_helper_marker_outputs':passed &= work['metadata_accepted']and work['exact_shader_dispatch_total']==1
  else:passed &= not work['metadata_accepted']
  if not known:passed &= work['exact_shader_dispatch_total']is None
  if 'canonical'in name:passed &= guard['status']==returned['status']and artifact['returned_stored_conflict']
  checks.append(dict(name=name,SIMULATED=True,passed=bool(passed),guard=guard,guard_artifact=artifact,work=work))
 scope={'np':np}
 for item in reg['metric_function_extraction']:
  p=Path(item['source']);node=next(n for n in ast.parse(p.read_text()).body if(isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets)))
  if item['name']=='moments':scope['ref']=types.SimpleNamespace(score=scope['score'])
  if item['name']=='detail':scope['helper']=types.SimpleNamespace(moments=scope['moments'])
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope)
 with np.load(reg['source_sequences']['path'])as z:baseline=z['baseline'].copy();truth=z['clean_reference'].copy()
 original=read(reg['original_report']['path']);row=next(x for x in original['rows']if x['scene']=='weak_material');metric_checks=[]
 for label,sl in[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]:
  measured=scope['detail'](baseline[sl],truth[sl]);metric_checks.append(dict(window=label,exact_to_original_report=measured==row['baseline_metrics'][label],metrics=measured))
 assert all(x['passed']for x in checks)and all(x['exact_to_original_report']for x in metric_checks)
 helper=(HERE/'helper_source_reference.cpp').read_text();assert helper.count('cmd->Dispatch(')==1 and 'for (UINT r=0;r<repetitions;++r)'in helper
 assert helper.index('WaitForSingleObject')<helper.index('gpu_ms_median=')<helper.index('validation_errors=')
 driver=(HERE/'run_composition_only.py').read_text();assert driver.index('save(target,report) # Actual physical work')<driver.index("if error:raise")<driver.index("if job['arm']=='observed_control':")
 assert driver.index('refuse_existing(reg)')<driver.index('from native_resource_guard import run_guarded')
 absent=[]
 for job in reg['jobs']:
  for n in('resource_guard.json','stdout.log','stderr.log'):
   p=Path(job['job']).parent/n;assert not p.exists();absent.append(str(p))
  for out in job['outputs']:assert not Path(out['path']).exists();absent.append(out['path'])
 for n in('execution_results.json','composition_metrics.json','composed_sequences.npz'):assert not(HERE/n).exists()
 result=dict(status='PASSED_BOUNDED_CPU_PREPARATION_CHECKS',SIMULATED_helper_checks=checks,SIMULATED_passed=6,SIMULATED_failed=0,frozen_oldB_metric_checks=metric_checks,frozen_oldB_four_windows_exact=True,registered192jobs=True,registered576outputs_absent=True,runtime1152_job_paths_absent=True,helper_source_one_explicit_Dispatch_per_repetition1=True,source_timing_after_wait_before_output_diagnostics=True,driver_actual_checkpoint_before_gates=True,driver_all_runtime_preflight_before_guard_import=True,actual_helper_GPU_native_build_model_trials=0,quality_accepted=False)
 save('CPU_checks.json',result);print(json.dumps(dict(status=result['status'],SIMULATED_passed=6,oldB_metric_windows_exact=4,actual_helper_GPU_native_build=0)))
if __name__=='__main__':main()
