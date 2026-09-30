"""Bounded SIMULATED B342 accounting contracts; no executable/device/native call."""
from pathlib import Path
import json
from native_work_accounting import derive,FRAME_BYTES
from executor_evidence import safe_guard_load
HERE=Path(__file__).resolve().parent;BASE=HERE/'SIMULATED_accounting';BASE.mkdir(exist_ok=False)
YES={'child_pid':123,'status':'completed','returncode':0};NO={'child_pid':None,'status':'not_launched_low_available_memory','returncode':None}
FOOTER=b'dispatches=64 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0\n'
checks=[]
def test(name,guard,stdout=b'',stderr=b'',diff=0,spec=0,controls=0,predicate=None):
    p=BASE/name;p.mkdir();(p/'stdout.log').write_bytes(stdout);(p/'stderr.log').write_bytes(stderr)
    if diff:(p/'diffuse.bin').write_bytes(bytes(FRAME_BYTES*diff))
    if spec:(p/'specular.bin').write_bytes(bytes(FRAME_BYTES*spec))
    if controls:(p/'dispatch_controls.bin').write_bytes(bytes(184*controls))
    result=derive(p,guard);passed=bool(predicate(result));checks.append({'name':name,'passed':passed,'result':result});assert passed,name
test('trusted_footer_metadata_output_missing_retains_actual64',YES,FOOTER,predicate=lambda r:r['exact_totals']and r['counts']['api']==64 and r['completed_context_confirmed']and r['evidence_disagreements'])
test('nochild_stale_footer_claims_zero',NO,FOOTER,predicate=lambda r:r['counts']['api']==0 and not r['created_context_confirmed']and r['totals_unknown'])
test('stderr_footer_not_authority',YES,stderr=FOOTER,predicate=lambda r:r['counts']['api']==0 and r['totals_unknown'])
test('duplicate_footer_not_authority',YES,FOOTER+FOOTER,predicate=lambda r:r['counts']['api']==0 and r['totals_unknown'])
test('truncated_footer_not_authority',YES,FOOTER[:-1],predicate=lambda r:r['counts']['api']==0 and r['totals_unknown'])
test('wrong_capacity_footer_not_authority',YES,FOOTER.replace(b'dispatches=64',b'dispatches=1'),predicate=lambda r:r['counts']['api']==0 and r['totals_unknown'])
test('controls_before_API_not_success',YES,controls=10,predicate=lambda r:r['counts']['api']==0 and r['totals_unknown'])
test('asymmetric_readback_prefix_physical_lowerbounds',YES,diff=2,spec=1,predicate=lambda r:r['counts']['api']==2 and r['counts']['completed_GPU']==2 and r['counts']['observed_readback_pairs']==1 and r['totals_unknown'])
test('warning_footer_preserves_actual_before_rejection',YES,FOOTER.replace(b'sdk_warnings=0',b'sdk_warnings=1'),predicate=lambda r:r['counts']['api']==64 and r['terminal_stdout_claim']['sdk_warnings']==1)
attempt={q:True for q in('invocation_started','fresh_runtime_files_verified_absent','case_command_matches','before_guard_call_checkpointed')}
test('fresh_unknown_guard_footer_lowerbound_not_exact',{'status':'guard_evidence_unavailable','child_pid':None,'returncode':None,'executor_launch_attempt':attempt},FOOTER,
    predicate=lambda r:r['counts']['api']==64 and r['totals_unknown']and not r['completed_context_confirmed']and r['completed_context_physical_lowerbound']==1)
for name,stored,returned,expected in [('returned_child_stored_nochild',NO,YES,64),('returned_nochild_stored_child',YES,NO,0)]:
    p=BASE/name;p.mkdir();(p/'resource_guard.json').write_text(json.dumps(stored));(p/'stdout.log').write_bytes(FOOTER)
    guard=safe_guard_load(p,attempt,['SIMULATED_not_launched'],returned);result=derive(p,guard)
    passed=result['counts']['api']==expected and bool(guard['guard_load_evidence']['errors']);checks.append({'name':name,'passed':passed,'result':result});assert passed
out={'schema':'SIMULATED-clean-native-B342-prefix-and-terminal-CPU-checks','checks':checks,'all_passed':True,'native_GPU_build':0}
with(HERE/'CPU_accounting_checks.json').open('x',encoding='utf-8',newline='\n')as f:json.dump(out,f,indent=2,allow_nan=False);f.write('\n')
print(json.dumps({'checks':len(checks),'all_passed':True,'native_GPU_build':0}))
