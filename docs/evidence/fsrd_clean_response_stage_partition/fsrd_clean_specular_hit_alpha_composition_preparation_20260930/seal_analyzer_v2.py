"""One-line inherited-seal key repair. Preserve V1; no scorer, model or device calls."""
from pathlib import Path
import ast,difflib,hashlib,json
HERE=Path(__file__).resolve().parent
def ident(p):
 p=Path(p);b=p.read_bytes();return dict(path=str(p.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):return json.loads(Path(p).read_text())
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
v1=read(HERE/'completion_manifest.json')
for r in v1['files']+v1['external_records']:assert ident(r['path'])==r,r['path']
old=(HERE/'analyze_composed_cpu.py').read_text();needle="sealed['files']+sealed['external_records']";assert old.count(needle)==1
new=old.replace(needle,"sealed['files']+sealed['external_sources']")
with(HERE/'analyze_composed_cpu_v2.py').open('x',encoding='utf-8',newline='\n')as f:f.write(new)
ast.parse(new)
with(HERE/'analyzer_v1_to_v2.diff').open('x',encoding='utf-8',newline='\n')as f:f.write(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='frozen_V1_analyzer',tofile='frozen_V2_analyzer')))
reg=read(HERE/'registration.json');seal=read(reg['prior_composition_final_seal']['path']);prior=read(reg['prior_composition_registration']['path'])
assert 'external_sources'in seal and 'external_records'not in seal
pinmap={r['path'].lower():r for r in seal['files']+seal['external_sources']};checked=0
for tag in('C0','C1'):
 jobs=[j for j in prior['jobs']if j['arm']==tag];assert [j['frame']for j in jobs]==list(range(64))
 for j in jobs:
  for o in j['outputs']:
   p=Path(o['path']);r=pinmap[str(p.resolve()).lower()];assert ident(p)==r,p;checked+=1
assert checked==384
save('analyzer_v2_source_schema_checks.json',dict(status='PASSED_CPU_METADATA_ONLY_SCHEMA_REPAIR',one_line_whitelist_exact=True,
 all384_prior_C0_C1_raw_output_records_found_and_SHA_exact=True,prior_seal_key='external_sources',all_V1_preparation_source_pins_unchanged=True,
 AST_parsed=True,scorer_executed=False,new_helper_GPU_native_build_scores=0))
save('preparation_v1_analyzer_qualification.json',dict(status='V1_ANLYZER_PRIOR_REFERENCE_SCHEMA_BLOCKER_PRESERVED',
 issue='V1 future analyzer expected inherited postmanifest external_records; actual pinned seal uses external_sources. It would fail the prior C0/C1 reference lookup.',
 chronology='V1 was sealed before acting on the CPU metadata-key read. No execution or analysis occurred. Its source/jobs/payload/driver and six SIM checks are unchanged.',
 resolution='V2 analyzer replaces only that one lookup key; all384 prior output pin records independently found and authenticated without scoring.',
 original_completion=ident(HERE/'completion_manifest.json'),use_future_analyzer=ident(HERE/'analyze_composed_cpu_v2.py'),
 original_V1_analyzer=ident(HERE/'analyze_composed_cpu.py'),new_helper_GPU_native_build_scores=0))
save('registration_v2.json',dict(schema='analyzer-only-V2-supplement',original_job_registration=ident(HERE/'registration.json'),
 execution_driver_unchanged=ident(HERE/'run_composition_only.py'),original_pre_execution_freeze=ident(HERE/'pre_execution_freeze.json'),
 future_analyzer=ident(HERE/'analyze_composed_cpu_v2.py'),future_targets_unchanged=['composition_metrics.json','composed_sequences.npz'],
 planned_only_helper_jobs=192,planned_only_outputs=576,selected_actual_traces=['A0_r0','A10_r0','A0_r1'],
 native_gate=reg['post_native_gate'],native_final_seal=reg['post_native_final_seal'],new_helper_GPU_native_build_scores=0,
 no_new_scoring_or_job_source_data_changes=True,root_authorization_after_independent_prelaunch_required=True))
names=['seal_analyzer_v2.py','analyze_composed_cpu_v2.py','analyzer_v1_to_v2.diff','analyzer_v2_source_schema_checks.json','preparation_v1_analyzer_qualification.json','registration_v2.json']
owned=[ident(HERE/n)for n in names];external=[ident(HERE/'completion_manifest.json'),reg['prior_composition_final_seal']]
save('pre_execution_freeze_v2.json',dict(schema='analyzer-only-V2-self-excluded-freeze',owned=owned,external_sources=external,
 inherited_V1_records_must_be_expanded_and_verified=True,self_entry_excluded=True,new_helper_GPU_native_build_scores=0))
save('readiness_v2.json',dict(status='READY_FOR_INDEPENDENT_ALPHA_THREE_TRACE_COMPOSITION_V2_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',blocking_findings=[],
 registration=ident(HERE/'registration_v2.json'),original_job_registration=ident(HERE/'registration.json'),
 original_pre_execution_freeze=ident(HERE/'pre_execution_freeze.json'),supplemental_freeze=ident(HERE/'pre_execution_freeze_v2.json'),
 future_execution_driver=ident(HERE/'run_composition_only.py'),future_CPU_analyzer=ident(HERE/'analyze_composed_cpu_v2.py'),
 native_gate=reg['post_native_gate'],native_final_seal=reg['post_native_final_seal'],
 preserved_V1_blocker=ident(HERE/'preparation_v1_analyzer_qualification.json'),schema_checks=ident(HERE/'analyzer_v2_source_schema_checks.json'),
 existing_6_SIMULATED_law_checks=ident(HERE/'CPU_checks.json'),jobs192_outputs576_unchanged=True,
 source_CSO_helper_guard_parser_unchanged=True,all384_prior_output_pin_lookups_verified=True,
 root_authorization_required=True,quality_accepted=False,new_helper_GPU_native_build_scores=0))
owned +=[ident(HERE/'pre_execution_freeze_v2.json'),ident(HERE/'readiness_v2.json')]
save('completion_manifest_v2.json',dict(schema='analyzer-only-V2-final-self-excluded-seal',files=owned,external_records=external,
 inherited_V1_source_graph_preserved=True,self_entry_excluded=True,status='READY_FOR_INDEPENDENT_V2_PRELAUNCH_REVIEW_NOT_EXECUTION_AUTHORIZATION',new_helper_GPU_native_build_scores=0))
for r in v1['files']+v1['external_records']:assert ident(r['path'])==r,r['path']
print(json.dumps(dict(registration=ident(HERE/'registration_v2.json'),freeze=ident(HERE/'pre_execution_freeze_v2.json'),readiness=ident(HERE/'readiness_v2.json'),
 completion=ident(HERE/'completion_manifest_v2.json'),owned_V2_records=len(owned),inherited_V1_owned_records=len(v1['files']),inherited_V1_external_records=len(v1['external_records']),actual_GPU_native_build_scores=0)))
