"""Bounded byte/AST/schema/runtime checks only: no scorer/helper/SDK/process call."""
from pathlib import Path
import ast, hashlib, json, shlex
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'fsrd_clean_specular_hit_alpha_composition_preparation_20260930'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(r):assert Path(r['path']).stat().st_size==r['bytes']and sha(r['path'])==r['sha256'],r['path']
reg=read(HERE/'assembled_registration_v1.json');assert reg['status']=='ASSEMBLED_CPU_PENDING_NATIVE_POSTGATE_AND_FINAL_FREEZE'
assert reg['logical_order']==['Fork_r0','AMD_r0','AMD_r1','Fork_r1']
assert reg['representative_order']==['Fork_r0','AMD_r0','AMD_r1']
assert len(reg['jobs'])==192 and len(reg['jobs'])==64*len(reg['representative_order'])
assert [(j['frame'],j['arm'])for j in reg['jobs']]==[(f,a)for f in range(64)for a in reg['representative_order']]
assert reg['trace_selection']['logical_rows']['Fork_r1']['representative']=='Fork_r0'
assert not reg['trace_selection']['logical_rows']['Fork_r1']['new_actual_composition_planned']
mapping=read(HERE/'graph_and_lobe_mapping_v1.json')['records'];assert len(mapping)==192
native_cache={};target_absent=[]
for job,m in zip(reg['jobs'],mapping):
 assert(job['frame'],job['arm'])==(m['frame'],m['arm'])
 lines=[shlex.split(x)for x in Path(job['job']).read_text().splitlines()]
 assert len(lines)==15 and lines[0][2:]==['128','80','11','3','1']
 assert len(job['inputs'])==11 and len(job['outputs'])==3
 verify(job['CB']);assert Path(lines[0][1]).resolve()==Path(job['CB']['path']).resolve()
 for r in job['inputs']:verify(r)
 for slot,expected_lobe in((0,'specular.bin'),(2,'diffuse.bin')):
  piece=m['native_actual_fullRGBA_slices'][str(slot)]
  source=piece['source']
  assert Path(source['path']).name==expected_lobe
  if source['path']not in native_cache:
   verify(source);native_cache[source['path']]=Path(source['path']).read_bytes()
  source_bytes=native_cache[source['path']]
  assert piece['offset']==job['frame']*81920 and piece['bytes']==81920
  assert Path(job['inputs'][slot]['path']).read_bytes()==source_bytes[piece['offset']:piece['offset']+81920]
 assert m['all_other9_inputs_fullbyte_exact']and m['CB96_byte_exact']and m['Flags8']and m['Detail0']and m['HistoryValid0']and m['WriteHistory0']
 for name in('resource_guard.json','stdout.log','stderr.log'):
  p=Path(job['job']).parent/name;assert not p.exists();target_absent.append(str(p))
 for out in job['outputs']:assert not Path(out['path']).exists();target_absent.append(out['path'])
for name in('execution_results.json','composition_metrics.json','composed_sequences.npz','execution_TEMP','pre_execution_freeze.json','readiness.json'):
 assert not(HERE/name).exists()
assert len(target_absent)==1152
for name in('helper_work_accounting.py','helper_guard_evidence.py','native_resource_guard.py','helper_source_reference.cpp','fsrd_gpu_runner.exe'):
 assert sha(HERE/name)==sha(OLD/name)
for r in reg['metric_source_records']:verify(r);assert sha(r['path'])==sha(OLD/'frozen_metric_sources'/Path(r['path']).name)
old_AST=ast.parse((OLD/'check_helper_contracts_cpu.py').read_text());new_AST=ast.parse((HERE/'check_helper_contracts_cpu.py').read_text())
def simulation_for(tree):
 main=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='main')
 return next(n for n in main.body if isinstance(n,ast.For))
assert ast.dump(simulation_for(old_AST),include_attributes=False)==ast.dump(simulation_for(new_AST),include_attributes=False)
assert read(HERE/'CPU_checks.json')['SIMULATED_passed']==6 and read(HERE/'CPU_checks.json')['SIMULATED_failed']==0
historical=read(reg['historical_metric_result']['path']);preserved=read(HERE/'historical_nine_metric_rows.json')
assert preserved['metrics']==historical['metrics']and len(historical['metrics'])==9
lookups=0
for registration,seal,arms in[(reg['prior_composition_registration'],reg['prior_composition_final_seal'],('C0','C1')),
                              (reg['historical_alpha_registration'],reg['historical_alpha_postseal'],('A0_r0','A0_r1'))]:
 verify(registration);verify(seal);p=read(seal['path'])
 assert'files'in p and'external_sources'in p and'external_records'not in p
 pins={r['path'].lower():r for r in p['files']+p['external_sources']}
 oldreg=read(registration['path'])
 for arm in arms:
  jobs=[j for j in oldreg['jobs']if j['arm']==arm];assert[j['frame']for j in jobs]==list(range(64))
  for j in jobs:
   for out in j['outputs']:
    pp=Path(out['path']);verify(pins[str(pp.resolve()).lower()]);lookups+=1
assert lookups==768
result=dict(status='PASSED_BOUNDED_ASSEMBLY_BYTE_AST_SCHEMA_CHECKS_NOT_FINAL_READINESS',blocking_findings=[],
 source_native_fullRGBA_slices_verified=384,fixed_template_jobs=192,output_targets_absent=576,runtime_job_targets_absent=1152,
 historical_raw_lookups_files_external_sources_verified=768,metric_source_functions_byte_exact=True,historical_nine_dicts_exact=True,
 original_six_SIMULATED_loop_AST_exact=True,SIMULATED_passed=6,helper_parser_directguard_law_EXE_exact=True,
 final_native_postgate_and_root_receipt_pending=True,finalfreeze_readiness_not_created=True,actual_GPU_native_build_scorer=0)
with(HERE/'assembly_cpu_checks_v1.json').open('x',encoding='utf-8')as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(result))
