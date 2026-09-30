"""CPU-only exclusive final seal after prior R independent gate; no runtime launch."""
from pathlib import Path
import ast,hashlib,json
HERE=Path(__file__).resolve().parent
GATE=HERE.parent/'fsrd_weak_material_clean_roundtrip_postrun_review_20260930'
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
assert rec(GATE/'review.json')['sha256']=='781527903c10be0e17291a766c07db040d564b23b70aeeeded766f74d62bc97d'
assert rec(GATE/'completion_manifest.json')['sha256']=='200230c6abf03940cc2d4ee0c784503fbcbc41c93378386eebb0ecdc2dbb09fc'
gate=read(GATE/'review.json')
assert gate['status']=='PASSED_CLEAN_ROUNDTRIP_EVIDENCE_AND_EXACT_SINGLETON_METRIC_REVIEW'
assert gate['blocking_findings']==[]
guardobs=HERE.parent/'fsrd_clean_roundtrip_root_tool_observations_20260930.json'
assert rec(guardobs)['sha256']=='48bce8e159824933251360ee20f71dd9d48ead2fa589c906385f7d801d233ddb'
checks=read(HERE/'CPU_checks.json');assert checks['SIMULATED_passed']==6 and checks['SIMULATED_failed']==0
assert checks['new_GPU_native_build_scores']==0 and checks['only_diffuse_A_changed']
reg=read(HERE/'registration_draft.json')
reg['prior_roundtrip_independent_postreview']=dict(passed_at_freeze=True,status=gate['status'],review=rec(GATE/'review.json'),seal=rec(GATE/'completion_manifest.json'),root_tool_observations=rec(guardobs))
save('registration.json',reg)
external=read(HERE/'source_manifest.json')['records']+[rec(GATE/'review.json'),rec(GATE/'completion_manifest.json'),rec(guardobs)]
assert len({r['path']for r in external})==len(external)
for r in external:assert rec(r['path'])==r,r['path']
for p in HERE.glob('*.py'):ast.parse(p.read_text())
runtime=[HERE/n for n in('execution_results.json','alpha_zero_comparison.json','execution_TEMP')]
for j in reg['jobs']:
 folder=Path(j['job']).parent;assert sorted(p.name for p in folder.iterdir())==['job.txt']
 runtime += [folder/n for n in('resource_guard.json','stdout.log','stderr.log')]+[Path(o['path'])for o in j['outputs']]
assert not any(p.exists()for p in runtime)
save('analysis_plan.json',dict(status='FROZEN_BITS_ONLY_FUTURE_ANALYSIS_NOT_EXECUTED',
 observations=dict(new_RZ=2,prior_R=2,static_graph=1),
 arms=['RZ0','RZ1','R0','R1'],pairs='All6 unordered pairs; all3 buffers per pair, serialized RGBA/RGB/alpha exactness and differing channel element counts only.',
 color_interpretation='If every pair color RGB bit-exact, diffuse alpha65504-vs0 caveat is empirically closed for this actual CSO and complete frozen graph. Does not prove all branches, SDK-alpha behavior, real ray length or game cause.',
 retained_alpha='Explicit t2 A0x7bff→0 synthetic control; no silent input repair. t0 specular A already0; both lobe RGB untouched.',
 no_scorer=True,no_models=True,no_64_measured_series=True,no_SDK_calls=True,
 output_provenance='Same historical EXE/CSO/law identities. Auxiliary UAV bytes retained and compared but may be unwritten in active history0 fast path; no semantic history claim.',
 strict_contract='Zero ordinary helper validation errors/warnings required. Canonical direct guard and physical checkpoint precede metadata/output gates; failed prefix retained, no retry.',
 execution_authorization='Final R independent gate pinned; separate RZ independent prelaunch review and root authorization still required.'))
seal_names={'pre_execution_freeze.json','readiness.json','completion_manifest.json'}
assert not any((HERE/n).exists()for n in seal_names)
owned=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name not in seal_names]
save('pre_execution_freeze.json',dict(status='FROZEN_ALPHA_ZERO_CPU_PREPARATION_NO_GPU_AUTHORIZATION',owned=owned,external_sources=external,
 inherited_full2252_source_manifest_pinned_once=read(HERE/'source_manifest.json')['inherited_source_manifest'],
 runtime_paths_expected_absent=[str(p)for p in runtime],self_excluded=True,planned_helpers_only_if_completed=2,planned_shader_Dispatches_only_if_completed=2,planned_new_SDK_API=0,
 actual_GPU_native_build_scores=0))
save('readiness.json',dict(status='READY_FOR_INDEPENDENT_ALPHA_ZERO_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',blockers=[],
 registration=rec(HERE/'registration.json'),freeze=rec(HERE/'pre_execution_freeze.json'),CPU_checks=rec(HERE/'CPU_checks.json'),analysis_plan=rec(HERE/'analysis_plan.json'),
 prior_R_independent_gate=reg['prior_roundtrip_independent_postreview'],
 planned_helpers=2,planned_new_SDK_API=0,actual_preparation_GPU_native_build_scores=0,six_inherited_SIM_passed=6,
 only_t2_A_control=True,all_runtime_absent=True,quality_accepted=False,
 commands_after_independent_review_and_root_authorization_only=['python -B run_alpha_zero_only.py --execute-alpha-zero-only','python -B analyze_alpha_zero_bits_cpu.py --analyze-alpha-zero-bits'],
 python_runtime_read_only='F:/OptiRevelations/OptiScaler/tools_tmp/albedo_stage1_venv/Scripts/python.exe',limits=reg['limitations']))
records=[rec(p)for p in sorted(HERE.rglob('*'))if p.is_file()and p.name!='completion_manifest.json']
save('completion_manifest.json',dict(status='SEALED_ALPHA_ZERO_CPU_PREPARATION_AWAITING_INDEPENDENT_REVIEW',records=records,self_excluded=True,
 direct_external_records=len(external),source_manifest=rec(HERE/'source_manifest.json'),no_full2252_duplicate=True,actual_GPU_native_build_scores=0,runtime_absence_verified=True))
for n in('registration.json','pre_execution_freeze.json','readiness.json','completion_manifest.json'):print(json.dumps(rec(HERE/n)))
