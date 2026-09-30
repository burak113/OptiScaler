"""CPU-only exact one-field control preparation; never launches helper or scorer."""
from pathlib import Path
import ast, difflib, hashlib, json, shlex, shutil
import numpy as np

HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'fsrd_weak_material_clean_roundtrip_preparation_20260930'
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def save(name,v):
 with (HERE/name).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def text(name,v):
 with (HERE/name).open('x',encoding='utf-8',newline='\n')as f:f.write(v)
def copy(src,dst):
 assert not dst.exists();dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst);assert src.read_bytes()==dst.read_bytes()

assert not(HERE/'registration_draft.json').exists(),'Preserve prior preparation'
oldreg=json.loads((OLD/'registration.json').read_text())
oldrun=json.loads((OLD/'execution_results.json').read_text())
assert oldrun['status']=='completed_roundtrip_only_awaiting_independent_review_not_quality_accepted'
assert oldrun['completed_accepted_jobs']==oldrun['exact_helper_total']==oldrun['exact_shader_dispatch_total']==2
copied=[]
for n in ('helper_work_accounting.py','helper_guard_evidence.py','native_resource_guard.py','fsrd_gpu_runner.exe','helper_source_reference.cpp','historical_gpu_runner.build.cmd'):
 copy(OLD/n,HERE/n);copied.append(dict(original=rec(OLD/n),copy=rec(HERE/n),byte_exact=True))
for src in sorted((OLD/'frozen_shader').iterdir()):
 if src.is_file():copy(src,HERE/'frozen_shader'/src.name);copied.append(dict(original=rec(src),copy=rec(HERE/'frozen_shader'/src.name),byte_exact=True))
base=oldreg['jobs'][0]
inputs=[]
for r in base['inputs']:
 src=Path(r['path']);dst=HERE/'payloads'/src.name
 if r['slot']!=2:copy(src,dst)
 else:
  original=np.fromfile(src,'<u2').reshape(80,128,4);assert np.all(original[...,3]==0x7bff)
  control=original.copy();control[...,3]=0;dst.parent.mkdir(parents=True,exist_ok=True)
  with dst.open('xb')as f:f.write(control.tobytes())
  assert control[...,:3].tobytes()==original[...,:3].tobytes()
  assert np.count_nonzero(control!=original)==80*128
 inputs.append(dict(slot=r['slot'],format=r['format'],**rec(dst)))
copy(Path(base['CB']['path']),HERE/'payloads/cb.bin')
assert np.all(np.fromfile(HERE/'payloads/in0.bin','<u2').reshape(80,128,4)[...,3]==0)
proof=dict(status='PASSED_EXACT_ONLY_T2_ALPHA_CONTROL',original_R0_job=rec(base['job']),
 original_diffuse=rec(OLD/'payloads/in2.bin'),control_diffuse=rec(HERE/'payloads/in2.bin'),
 format=10,dimensions=[128,80],changed_channel='t2 FP16 A only',old_A_bits='0x7bff',new_A_bits='0x0000',
 alpha_elements_changed=10240,bytes_changed=20480,diffuse_RGB_bits_unchanged=True,
 other10_input_full_bytes_unchanged=True,CB_full_bytes_unchanged=True,specular_A_already_positive_zero=True,
 intended_scope='Synthetic actual-CSO alpha-dataflow control matching observed SDK output A=0. Not input repair, confidence, traced-raylength or native quality claim.')
for r in inputs:
 if r['slot']!=2:assert Path(r['path']).read_bytes()==Path(base['inputs'][r['slot']]['path']).read_bytes()
assert(HERE/'payloads/cb.bin').read_bytes()==Path(base['CB']['path']).read_bytes()
save('alpha_change_proof.json',proof)
jobs=[]
for arm in ('RZ0','RZ1'):
 folder=HERE/'planned_jobs'/arm;folder.mkdir(parents=True,exist_ok=False)
 outputs=[dict(slot=i,format=o['format'],path=str((folder/f'out{i}.bin').resolve()),bytes=o['bytes'])for i,o in enumerate(base['outputs'])]
 quote=lambda p:'"'+Path(p).as_posix()+'"'
 rows=[f'{quote(HERE/"frozen_shader/FSRDOutputComp_Shader.cso")} {quote(HERE/"payloads/cb.bin")} 128 80 11 3 1']
 rows += [f'{quote(r["path"])} 128 80 {r["format"]}'for r in inputs]
 rows += [f'{quote(o["path"])} 128 80 {o["format"]}'for o in outputs]
 (folder/'job.txt').write_text('\n'.join(rows)+'\n',encoding='utf-8',newline='\n')
 jobs.append(dict(frame=0,arm=arm,job=str((folder/'job.txt').resolve()),command=[str(HERE/'fsrd_gpu_runner.exe'),str(folder/'job.txt')],inputs=inputs,CB=rec(HERE/'payloads/cb.bin'),outputs=outputs))

original_driver=(OLD/'run_roundtrip_only.py').read_text()
driver=original_driver.replace('--execute-roundtrip-only','--execute-alpha-zero-only').replace('PREPARED_CPU_ONLY_NO_ROUNDTRIP_GPU_AUTHORIZATION','PREPARED_ALPHA_ZERO_CPU_ONLY_NO_GPU_AUTHORIZATION').replace("[(0,'R0'),(0,'R1')]","[(0,'RZ0'),(0,'RZ1')]").replace('roundtrip_metrics.json','alpha_zero_comparison.json').replace(",HERE/'roundtrip_sequences.npz'",'').replace('running_roundtrip_only','running_alpha_zero_only').replace('completed_roundtrip_only_awaiting_independent_review_not_quality_accepted','completed_alpha_zero_only_awaiting_independent_review_not_quality_accepted').replace('failed_preserved_roundtrip_only_no_retry','failed_preserved_alpha_zero_only_no_retry').replace('source_graph_dedup_64_proven=True','single_R0_alpha_control_graph=True')
needle=" assert len(reg['jobs'])==2 and [(j['frame'],j['arm'])for j in reg['jobs']]==[(0,'RZ0'),(0,'RZ1')]\n"
assert needle in driver
driver=driver.replace(needle,needle+" assert reg['prior_roundtrip_independent_postreview']['passed_at_freeze'] is True\n")
text('run_alpha_zero_only.py',driver)
text('executor_adaptation.diff',''.join(difflib.unified_diff(original_driver.splitlines(True),driver.splitlines(True),fromfile=str(OLD/'run_roundtrip_only.py'),tofile=str(HERE/'run_alpha_zero_only.py'))))

prior_outputs=[dict(arm=j['arm'],outputs=[dict(slot=o['slot'],format=o['format'],**rec(o['path']))for o in j['outputs']])for j in oldreg['jobs']]
external=[rec(OLD/n)for n in ('registration.json','pre_execution_freeze.json','readiness.json','completion_manifest.json','external_source_pins.json','CPU_checks.json','graph_identity_proof.json','execution_results.json','run_roundtrip_only.py','check_preparation_cpu.py')]
external += [rec(r['path'])for r in base['inputs']]+[rec(base['CB']['path'])]
external += [r['original']for r in copied]
external += [o for j in prior_outputs for o in j['outputs']]
# Compact direct records only. The inherited 2252-record source manifest is pinned once,
# rather than duplicated into both this source file and execution freeze.
external=list({r['path']:dict(path=r['path'],bytes=r['bytes'],sha256=r['sha256'])for r in external}.values())
save('source_manifest.json',dict(records=external,inherited_source_manifest=rec(OLD/'external_source_pins.json'),inherited_full_records_not_duplicated=True))
save('accounting_reuse.json',dict(copied_byte_exact=copied,existing_six_probe_report=rec(OLD/'CPU_checks.json'),driver_adaptation=rec(HERE/'executor_adaptation.diff'),physical_checkpoint_guard_and_parser_law_unchanged=True,old_source_provenance_limit='Historical source references are not new compiler equivalence proof. This planned actual-CSO dataflow control empirically tests its color result.'))
save('registration_draft.json',dict(schema='actual-CSO-diffuse-alpha-zero-control-v1',status='PREPARED_ALPHA_ZERO_CPU_ONLY_NO_GPU_AUTHORIZATION',
 jobs=jobs,source_manifest=rec(HERE/'source_manifest.json'),alpha_change_proof=rec(HERE/'alpha_change_proof.json'),
 prior_R_outputs=prior_outputs,prior_roundtrip_independent_postreview=None,
 planned_helpers_only_if_completed=2,planned_explicit_shader_Dispatches_only_if_completed=2,planned_SDK_API=0,
 planned_output_files_only_if_completed=6,actual_helpers_GPU_native_build_scores=0,
 quality_accepted=False,game_run=False,root_authorization_required_after_independent_prelaunch_review=True,
 limitations=['One static complete graph; two fresh helper observations only. No64-series inference.','Only converter diffuse A changes from65504 to positive0. Diffuse RGB, remaining10 full inputs and96byte CB are exact.','Compare all3 raw output buffers against each other and actual R0/R1; auxiliary UAV bytes may be unwritten in active WriteHistory0 path, so color RGB interpretation is separate.','Historical source/CSO/EXE identities preserved. No guaranteed historical compilation equivalence, real ray-length treatment, SDK correctness or game cause.','No scorer, quality model, filtering, fitting, settings or threshold changes.']))

# The future analyzer performs serialized comparisons only, no metrics/scorer/imported analyzer.
text('analyze_alpha_zero_bits_cpu.py', '''"""Future saved raw-buffer bit comparisons only; no launcher, scores or64-series."""
from pathlib import Path
import argparse,hashlib,itertools,json
import numpy as np
HERE=Path(__file__).resolve().parent
def rec(p):
 p=Path(p);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def main():
 p=argparse.ArgumentParser();p.add_argument('--analyze-alpha-zero-bits',action='store_true',required=True);p.parse_args()
 target=HERE/'alpha_zero_comparison.json';assert not target.exists(),'Preserve previous comparison'
 reg=json.loads((HERE/'registration.json').read_text());run=json.loads((HERE/'execution_results.json').read_text())
 assert run['status']=='completed_alpha_zero_only_awaiting_independent_review_not_quality_accepted'
 assert run['completed_accepted_jobs']==run['exact_helper_total']==run['exact_shader_dispatch_total']==2
 buffers={};records={}
 for job in reg['jobs']+reg['prior_R_outputs']:
  arm=job['arm'];buffers[arm]=[];records[arm]=[]
  for i,o in enumerate(job['outputs']):
   r=rec(o['path']);assert r['bytes']==o['bytes']
   if arm in ('R0','R1'):assert r['sha256']==o['sha256']
   records[arm].append(r);buffers[arm].append(np.fromfile(o['path'],'<u2'if i<2 else'<u4').reshape(80,128,4))
 pairs=[]
 for a,b in itertools.combinations(('RZ0','RZ1','R0','R1'),2):
  outs=[]
  for i in range(3):
   x,y=buffers[a][i],buffers[b][i]
   outs.append(dict(slot=i,format=10 if i<2 else 3,full_RGBA_serialized_bits_exact=bool(np.array_equal(x,y)),RGB_bits_exact=bool(np.array_equal(x[...,:3],y[...,:3])),alpha_bits_exact=bool(np.array_equal(x[...,3],y[...,3])),differing_channel_elements=int(np.count_nonzero(x!=y))))
  pairs.append(dict(arms=[a,b],outputs=outs))
 report=dict(status='COMPLETED_SAVED_BITS_ONLY_ALPHA_CONTROL_NOT_QUALITY_ACCEPTED',actual_new_helper_observations=2,prior_R_actual_observations=2,static_graphs=1,new_SDK_API=0,new_scores=0,output_records=records,pairs=pairs,
  color_RGB_alpha_caveat_closed_for_this_graph=all(p['outputs'][0]['RGB_bits_exact']for p in pairs),
  no_64_measured_series=True,quality_accepted=False,game_run=False,limits=reg['limitations'])
 with target.open('x',encoding='utf-8',newline='\\n')as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\\n')
if __name__=='__main__':main()
''')

# Reuse the existing six accounting simulations verbatim, with narrow control checks.
oldcheck=(OLD/'check_preparation_cpu.py').read_text();start=oldcheck.index(' YES=dict(');end=oldcheck.index(" assert all(x['passed']for x in checks)")
body=oldcheck[start:end]
checker='''"""Six unchanged SIMULATED helper-law probes and exact one-field CPU control checks."""
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
'''+body+''' assert all(x['passed']for x in checks)
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
 with (HERE/'CPU_checks.json').open('x',encoding='utf-8',newline='\\n')as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\\n')
 print(json.dumps(dict(status='CPU_checks_passed',six_SIM=6,new_GPU_native_build_scores=0)))
if __name__=='__main__':main()
'''
text('check_alpha_zero_cpu.py',checker)
for p in HERE.glob('*.py'):ast.parse(p.read_text())
print(json.dumps(dict(status='PREPARED_CORE_WAITING_CPU_CHECK_AND_PRIOR_ROUNDTRIP_POSTREVIEW',jobs=2,new_GPU_native_build_scores=0)))
