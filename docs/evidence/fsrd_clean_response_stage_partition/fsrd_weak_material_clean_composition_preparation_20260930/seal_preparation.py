"""Immutable source/params/pre-execution seal only; no real helper/native/GPU."""
from pathlib import Path
import json,hashlib
HERE=Path(__file__).resolve().parent
def identity(p):
 p=Path(p).resolve();h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def read(p):return json.loads(Path(p).read_text())
def save(n,o):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(o,f,indent=2,allow_nan=False);f.write('\n')
def files():return [p for p in sorted(HERE.rglob('*'))if p.is_file()and'__pycache__'not in p.parts]
def verify(r):
 a=identity(r['path']);assert(a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path']
def main():
 assert not(HERE/'pre_execution_freeze.json').exists()and not(HERE/'completion_manifest.json').exists()
 reg=read(HERE/'registration.json');checks=read(HERE/'CPU_checks.json');assert checks['status']=='PASSED_BOUNDED_CPU_PREPARATION_CHECKS'
 external=read(HERE/'external_source_pins.json')['records']
 external += [reg['source_sequences'],reg['quantized_raw_reference'],reg['original_report'],reg['post_native_gate'],reg['post_native_final_seal']]
 external=list({r['path'].lower():r for r in external}.values())
 for r in external:verify(r)
 for j in reg['jobs']:
  for out in j['outputs']:assert not Path(out['path']).exists()
  for n in('stdout.log','stderr.log','resource_guard.json'):assert not(Path(j['job']).parent/n).exists()
 owned=[identity(p)for p in files()]
 freeze=dict(schema='weak-clean-composition192-pre-execution-self-excluded-freeze',owned=owned,external_sources=external,self_entry_excluded=True,actual_helper_GPU_native_build=0,status='FROZEN_CPU_ONLY_NO_EXECUTION_AUTHORIZATION')
 save('pre_execution_freeze.json',freeze)
 ready=dict(status='READY_FOR_INDEPENDENT_CLEAN_COMPOSITION_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',blocking_findings=[],registration=identity(HERE/'registration.json'),source_mapping=identity(HERE/'source_mapping.json'),CPU_checks=identity(HERE/'CPU_checks.json'),pre_execution_freeze=identity(HERE/'pre_execution_freeze.json'),post_native_independent_gate=reg['post_native_gate'],post_native_final_seal=reg['post_native_final_seal'],frozen_helper=reg['frozen_helper'],frozen_CSO=reg['frozen_CSO'],planned_only_helper_jobs=192,planned_only_explicit_shader_Dispatches=192,planned_only_native_contexts=0,planned_only_native_API=0,planned_only_UAV_output_files=576,observed_replay_all3_output_bit_match_required_each_frame=True,metric_scorer_unchanged_and_oldB_four_windows_exact=True,actual_helper_GPU_native_API_build_model_trials=0,root_authorization_required_after_independent_review=True,quality_accepted=False,limitations=reg['limitations'])
 save('readiness.json',ready)
 completion=dict(schema='weak-clean-composition192-preparation-final-self-excluded-seal',files=[identity(p)for p in files()],external_records=external,self_entry_excluded=True,status=ready['status'],actual_helper_GPU_native_API_build=0)
 save('completion_manifest.json',completion)
 for r in completion['files']+external:verify(r)
 assert all(Path(r['path']).resolve()!=(HERE/'completion_manifest.json').resolve()for r in completion['files']+external)
 print(json.dumps(dict(status=ready['status'],registration=identity(HERE/'registration.json'),freeze=identity(HERE/'pre_execution_freeze.json'),readiness=identity(HERE/'readiness.json'),completion_manifest=identity(HERE/'completion_manifest.json'),owned_records=len(completion['files']),external_records=len(external),actual_helper_GPU_native_API_build=0)))
if __name__=='__main__':main()
