"""Six unchanged SIMULATED helper-law probes and exact one-field CPU control checks."""
from pathlib import Path
import ast,hashlib,importlib.util,json,shlex,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'fsrd_weak_material_clean_roundtrip_preparation_20260930'
def read(p):return json.loads(Path(p).read_text())
def module(n,p):s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert not(HERE/'CPU_checks.json').exists(),'Preserve probes'
 reg=read(HERE/'registration_draft.json')
 m=module('alpha_zero_helper_accounting_CPU',HERE/'helper_work_accounting.py');g=module('alpha_zero_guard_loader_CPU',HERE/'helper_guard_evidence.py')
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
 import numpy as np
 a=np.fromfile(OLD/'payloads/in2.bin','<u2').reshape(80,128,4);b=np.fromfile(HERE/'payloads/in2.bin','<u2').reshape(80,128,4)
 assert np.all(a[...,3]==0x7bff)and np.all(b[...,3]==0)and a[...,:3].tobytes()==b[...,:3].tobytes()
 for i in range(11):
  if i!=2:assert(HERE/f'payloads/in{i}.bin').read_bytes()==(OLD/f'payloads/in{i}.bin').read_bytes()
 assert(HERE/'payloads/cb.bin').read_bytes()==(OLD/'payloads/cb.bin').read_bytes()
 for job in reg['jobs']:
  rows=[shlex.split(x)for x in Path(job['job']).read_text().splitlines()];assert len(rows)==15 and rows[0][2:]==['128','80','11','3','1']
  assert Path(rows[0][0]).read_bytes()==(OLD/'frozen_shader/FSRDOutputComp_Shader.cso').read_bytes()
  assert Path(rows[0][1]).read_bytes()==(OLD/'payloads/cb.bin').read_bytes()
  assert [Path(x[0]).read_bytes()for x in rows[1:12]]==[(HERE/f'payloads/in{i}.bin').read_bytes()for i in range(11)]
  for n in('resource_guard.json','stdout.log','stderr.log'):assert not(Path(job['job']).parent/n).exists()
  for o in job['outputs']:assert not Path(o['path']).exists()
 for n in('execution_TEMP','execution_results.json','alpha_zero_comparison.json'):assert not(HERE/n).exists()
 for p in HERE.glob('*.py'):ast.parse(p.read_text())
 driver=(HERE/'run_alpha_zero_only.py').read_text();assert driver.index('save(target,report) # Actual physical work')<driver.index('if error:raise')
 assert driver.index('refuse_existing(reg)')<driver.index('from native_resource_guard import run_guarded')
 analyzer=(HERE/'analyze_alpha_zero_bits_cpu.py').read_text();assert 'itertools.combinations'in analyzer and 'np.array_equal'in analyzer
 assert 'np.broadcast_to'not in analyzer and 'score('not in analyzer
 oldcheck=(OLD/'check_preparation_cpu.py').read_text();newcheck=Path(__file__).read_text();start=' YES=dict(';end=" assert all(x['passed']for x in checks)"
 assert oldcheck[oldcheck.index(start):oldcheck.index(end)]==newcheck[newcheck.index(start):newcheck.index(end)]
 report=dict(status='PASSED_SIX_UNCHANGED_SIM_AND_EXACT_ONLY_T2_ALPHA_CHECKS',SIMULATED_helper_checks=checks,SIMULATED_passed=6,SIMULATED_failed=0,probe_body_byte_exact=True,copied_law_EXE_CSO_exact=True,only_diffuse_A_changed=True,all_runtime_absent=True,new_GPU_native_build_scores=0,quality_accepted=False)
 with (HERE/'CPU_checks.json').open('x',encoding='utf-8',newline='\n')as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
 print(json.dumps(dict(status='CPU_checks_passed',six_SIM=6,new_GPU_native_build_scores=0)))
if __name__=='__main__':main()
