"""Six inherited SIMULATED accounting probes plus byte/AST/absence checks; no scoring."""
from pathlib import Path
import ast,hashlib,importlib.util,json,shlex,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'fsrd_weak_material_clean_composition_preparation_20260930'
def read(p):return json.loads(Path(p).read_text())
def ident(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(p,v):
 with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def module(n,p):s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert not(HERE/'CPU_checks.json').exists(),'Preserve CPU probes'
 reg=read(HERE/'registration.json');assert len(reg['jobs'])==2
 m=module('roundtrip_helper_accounting_CPU',HERE/'helper_work_accounting.py');g=module('roundtrip_guard_loader_CPU',HERE/'helper_guard_evidence.py')
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
 assert all(x['passed']for x in checks)
 for n in('helper_work_accounting.py','helper_guard_evidence.py','native_resource_guard.py','fsrd_gpu_runner.exe','helper_source_reference.cpp'):assert(HERE/n).read_bytes()==(OLD/n).read_bytes()
 graph=read(HERE/'graph_identity_proof.json');assert graph['unique_complete_graphs']==1 and len(graph['frames'])==64
 first=None
 for frame in graph['frames']:
  full=[Path(frame['CB']['path']).read_bytes()]+[Path(r['path']).read_bytes()for r in frame['inputs']]
  if first is None:first=full
  assert full==first
 for job in reg['jobs']:
  rows=[shlex.split(x)for x in Path(job['job']).read_text().splitlines()];assert len(rows)==15 and rows[0][2:]==['128','80','11','3','1']
  assert Path(rows[0][1]).read_bytes()==first[0]
  assert [Path(x[0]).read_bytes()for x in rows[1:12]]==first[1:]
  for n in('resource_guard.json','stdout.log','stderr.log'):assert not(Path(job['job']).parent/n).exists()
  for o in job['outputs']:assert not Path(o['path']).exists()
 assert not(HERE/'execution_TEMP').exists()
 for n in('execution_results.json','roundtrip_metrics.json','roundtrip_sequences.npz'):assert not(HERE/n).exists()
 for p in HERE.rglob('*.py'):ast.parse(p.read_text())
 for item in reg['metric_function_extraction']:
  source=Path(item['source']);assert source.read_bytes()==(OLD/'frozen_metric_sources'/source.name).read_bytes()
 helper=(HERE/'helper_source_reference.cpp').read_text();assert helper.count('cmd->Dispatch(')==1 and 'for (UINT r=0;r<repetitions;++r)'in helper
 assert helper.index('WaitForSingleObject')<helper.index('gpu_ms_median=')<helper.index('validation_errors=')
 driver=(HERE/'run_roundtrip_only.py').read_text();assert driver.index('save(target,report) # Actual physical work')<driver.index('if error:raise')
 assert driver.index('refuse_existing(reg)')<driver.index('from native_resource_guard import run_guarded')
 analyzer=(HERE/'analyze_roundtrip_cpu.py').read_text();assert 'colors[arm]=raw[arm][0][None,...,:3]'in analyzer and 'single_scores='in analyzer and 'if all_exact:'in analyzer
 assert 'singleton_temporal_fields_noninferential=True'in analyzer and 'No temporalstd result is computed over a duplicated R64 series'in analyzer
 oldblock=(OLD/'check_preparation_cpu.py').read_text();newblock=Path(__file__).read_text()
 start=' YES=dict(';stop=' scope={';oldpart=oldblock[oldblock.index(start):oldblock.index(stop)];newpart=newblock[newblock.index(start):newblock.index(' assert all(x[\'passed\']for x in checks)')]
 # The inherited producer appends its assertion after metric checks; the shared six-probe body is byte exact.
 assert oldpart.rstrip()==newpart.rstrip()
 save(HERE/'CPU_checks.json',dict(status='PASSED_SIX_INHERITED_ACCOUNTING_PROBES_AND_STATIC_GRAPH_BYTE_CHECKS',SIMULATED_helper_checks=checks,SIMULATED_passed=6,SIMULATED_failed=0,probe_body_byte_exact_to_existing=True,
  mature_parser_guard_resource_guard_EXE_byte_exact=True,all64full11SRV_CB_equal=True,two_registered_graphs_full_bytes_exact=True,all6outputs_guard_logs_result_TEMP_absent=True,
  metric_sources_byte_exact_not_executed=True,oldB_fourwindow_checks_reused_pinned_not_rerun=ident(OLD/'CPU_checks.json'),future_R_scores_single_observation_only=True,static_SDK_reference_requires_all3_repeat_bits_exact=True,
  helper_source_one_Dispatch_per_repetition1=True,driver_actual_checkpoint_before_gates=True,initial_system_numpy_failure_preserved=True,actual_helper_GPU_native_build_model_trials_scores=0,quality_accepted=False))
 print(json.dumps(dict(status='CPU_probes_passed',SIMULATED=6,scores=0,actual_GPU_native_build=0)))
if __name__=='__main__':main()
