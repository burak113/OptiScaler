"""Compact self-excluded CPU preparation completion; never imports launchers."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
def ident(p):
    p=Path(p);b=p.read_bytes();return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
    with(HERE/n).open('x',encoding='utf-8')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
ready=read(HERE/'prelaunch_ready_manifest.json');freeze=read(HERE/'pre_native_freeze.json')
for package in(ready,freeze):
    for r in package['files']+package['external_sources']:assert ident(r['path'])==r,r['path']
reg=read(HERE/'registration.json');checks=read(HERE/'CPU_accounting_checks.json');runtime=read(HERE/'payload_and_runtime_verification.json')
assert len(reg['cases'])==4 and [c['specular_input_A']for c in reg['cases']]==[0,10,10,0]
assert checks['all_passed']and len(checks['checks'])==12
assert all(row['preflight']['all_absent']for row in runtime['runtime']['cases'])
assert not(HERE/'execution_results.json').exists()and not(HERE/'raw_comparisons.json').exists()
save('compact_preparation.json',dict(status='READY_FOR_INDEPENDENT_PREPARATION_REVIEW_RZ_AND_ROOT_EXECUTION_AUTHORIZATION_PENDING',
    registration=ident(HERE/'registration.json'),freeze=ident(HERE/'pre_native_freeze.json'),ready=ident(HERE/'prelaunch_ready_manifest.json'),
    fixed_order=reg['fixed_order'],specular_alpha_doses=[0,10,10,0],planned_only_if_all_complete=reg['planned_only_if_all_completed'],
    actual_new_work=reg['current_actual'],all56_registered_runtime_artifacts_absent=True,result_and_analysis_absent=True,
    sole_mutation='input6 alpha halfwords0x0000→0x4900 in A10; 10240 bytes at offsets8*p+7; RGB unchanged.',
    source_CPP_sha256=reg['source_reference']['sha256'],EXE_sha256=reg['runner']['sha256'],provider_sha256=reg['provider']['sha256'],
    unchanged_four_accounting_guard_test_modules=True,existing_SIMULATED_CPU_checks_passed=12,
    R_gate='PASSED_SEALED',RZ_gate='PENDING_NOT_READ',root_authorization=False,composition_authorization=False,quality_accepted=False,
    failed_preparation_attempts_preserved=1,qualification=ident(HERE/'preparation_attempt1_qualification.json'),
    successful_CPU_preparation_tool_observation=dict(tool='exec_command',chunk_id='5fdf00',exit_code=0,redirected_console_file=None,
      note='Tool stdout carried registration/freeze/ready identities. CPU checks have actual saved stdout/stderr; no native child logs exist.'),
    expanded_source_graph_via_existing_manifest=read(HERE/'source_reuse.json')['expanded_reviewed_provenance_manifest'],
    external_unique_records=len(ready['external_sources']),no_new_native_GPU_build_score=True))
files=[ident(p)for p in sorted(HERE.rglob('*'))if p.is_file()and '__pycache__'not in p.parts]
save('completion_manifest.json',dict(schema='CPU-alpha-contrast-preparation-self-excluded-completion',files=files,external_records=ready['external_sources'],self_entry_excluded=True,
    status='READY_FOR_INDEPENDENT_PREPARATION_REVIEW_RZ_AND_ROOT_EXECUTION_AUTHORIZATION_PENDING',
    actual_native_GPU_build_scores=0,old_sources_and_prior_freeze_bytes_unchanged=True,expanded_source_tables_not_duplicated=True))
print(json.dumps(dict(compact=ident(HERE/'compact_preparation.json'),completion=ident(HERE/'completion_manifest.json'),owned_records=len(files),external_records=len(ready['external_sources']),actual_native_GPU_build_scores=0)))
