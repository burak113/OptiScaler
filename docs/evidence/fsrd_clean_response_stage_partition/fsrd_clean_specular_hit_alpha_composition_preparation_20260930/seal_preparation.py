"""Self-excluded CPU preparation seal; no device/scorer imports."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def ident(p):
 p=Path(p);b=p.read_bytes();return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def files():return[ident(p)for p in sorted(HERE.rglob('*'))if p.is_file()and '__pycache__'not in p.parts]
reg=read(HERE/'registration.json');check=read(HERE/'CPU_checks.json');external=read(HERE/'external_source_pins.json')['records']
assert check['SIMULATED_passed']==6 and not check['SIMULATED_failed']and not check['scoring_run_now']
assert len(reg['jobs'])==192 and [(j['frame'],j['arm'])for j in reg['jobs']]==[(f,a)for f in range(64)for a in('A0_r0','A10_r0','A0_r1')]
for r in external:assert ident(r['path'])==r,r['path']
for j in reg['jobs']:
 for r in j['inputs']+[j['CB']]:assert all(ident(r['path'])[k]==r[k]for k in('path','bytes','sha256')),r['path']
 for n in('resource_guard.json','stdout.log','stderr.log'):assert not(Path(j['job']).parent/n).exists()
 for o in j['outputs']:assert not Path(o['path']).exists()
for n in('execution_results.json','composition_metrics.json','composed_sequences.npz','execution_TEMP'):assert not(HERE/n).exists()
save('pre_execution_freeze.json',dict(schema='three-native-alpha-trace-composition192-self-excluded-freeze',owned=files(),external_sources=external,
 self_entry_excluded=True,status='FROZEN_CPU_ONLY_NO_EXECUTION_AUTHORIZATION',actual_helper_GPU_native_build_scores=0))
save('readiness.json',dict(status='READY_FOR_INDEPENDENT_ALPHA_THREE_TRACE_COMPOSITION_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',blocking_findings=[],
 registration=ident(HERE/'registration.json'),pre_execution_freeze=ident(HERE/'pre_execution_freeze.json'),CPU_checks=ident(HERE/'CPU_checks.json'),
 planned_only_helper_jobs=192,planned_only_explicit_helper_shader_Dispatches=192,planned_only_outputs=576,
 selected_native_traces=['A0_r0','A10_r0','A0_r1'],A10_r1_saved_raw_equal_not_measured_composition=True,
 native_independent_gate=reg['post_native_gate'],native_final_seal=reg['post_native_final_seal'],
 source_CSO_helper_accounting_guard_exact=True,fixed9_inputs_CB_exact=True,runtime1152_job_paths_absent=True,actual_helper_GPU_native_build_scores=0,
 original_scoring_sources_frozen_byte_exact_no_scores_now=True,existing_6_SIMULATED_checks_passed=True,
 root_authorization_required=True,quality_accepted=False))
save('completion_manifest.json',dict(schema='three-native-alpha-trace-composition192-final-self-excluded-seal',files=files(),external_records=external,
 self_entry_excluded=True,status='READY_FOR_INDEPENDENT_ALPHA_THREE_TRACE_COMPOSITION_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',actual_helper_GPU_native_build_scores=0))
print(json.dumps(dict(registration=ident(HERE/'registration.json'),freeze=ident(HERE/'pre_execution_freeze.json'),readiness=ident(HERE/'readiness.json'),
 completion=ident(HERE/'completion_manifest.json'),owned_records=len(read(HERE/'completion_manifest.json')['files']),external_records=len(external),actual_GPU_native_build_scores=0)))
