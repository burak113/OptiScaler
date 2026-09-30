"""Independent prelaunch hash/delta review and explicitly simulated CPU accounting checks."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json,struct,ast
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp')
P=ROOT/'fsrd_native_discarded_recording_diagnostic_20260930'
OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):
    p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def check(items):
    for item in items:assert identity(item['path'])==item,item['path']
def save(name,v):
    with(OUT/name).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
v1=load(P/'pre_native_freeze.json');v2=load(P/'accounting_v2_pre_native_freeze.json');v3=load(P/'accounting_v3_pre_native_freeze.json')
for frozen in [v1,v2,v3]:check(frozen['files'])
check(v1['external_sources'])
old_review=load(OUT/'review.json');check(old_review['source_pins_pre_and_post'])
reg=load(P/'accounting_v3_registration.json');base=load(P/'registration.json')
assert reg['canonical_future_executor']==identity(P/'run_native_v3.py')
assert reg['accounting_module']==identity(P/'native_work_accounting_v3.py')
assert not(P/'evidence/results.json').exists()
assert not any((P/'evidence'/c['tag']/'resource_guard.json').exists()for c in base['cases'])
assert all(reg[k]==0 for k in ['actual_native_contexts','actual_successful_API_RR_recordings','actual_queued_RR_dispatches'])
pins=[identity(P/n)for n in ['accounting_v3_registration.json','accounting_v3_pre_native_freeze.json','run_native_v3.py','native_work_accounting_v3.py']]
v2driver=(P/'run_native_v2.py').read_text()
expected=v2driver.replace('from native_work_accounting import derive','from native_work_accounting_v3 import derive')
expected=expected.replace('accounting_v2_pre_native_freeze.json','accounting_v3_pre_native_freeze.json')
expected=expected.replace('discarded-record-H2-actual-native-evidence-v2-accounted-before-validation','discarded-record-H2-actual-native-evidence-v3-authoritative-or-qualified-accounting')
actual=(P/'run_native_v3.py').read_text();assert expected==actual
ast.parse(actual)
assert actual.index('accounting=derive(folder,guard,c)')<actual.index("if guard['status']!='completed'")
assert actual.index("report['queued_RR_dispatches']+=accounting")<actual.index('assert counts[3:]==[0,0,0,0]')
spec=importlib.util.spec_from_file_location('pinned_v3_accounting',P/'native_work_accounting_v3.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
case={**base['cases'][0],'tag':'SIMULATED_only_baseline64'}
guard={'child_pid':1,'status':'completed','returncode':0}
checks=[]
def test(name,folder,expected):
    a=m.derive(folder,guard,case)
    for k,v in expected.items():assert a[k]==v,(name,k,a[k],v)
    checks.append({'name':name,'SIMULATED_NOT_NATIVE_EVIDENCE':True,'derived':a})
test('V2_conflicting65_indices_now_rejected_footer64_authoritative',OUT/'SIMULATED_V2_conflicting_accounting_unit_input',
 {'successful_API_RR_recordings_confirmed':64,'queued_RR_dispatches_confirmed_completed':64,
  'counter_authority':'valid_bounded_final_CPP_footer_under_pinned_source','totals_unknown':False,
  'unified_count_status':'authoritative_footer_with_metadata_conflicts'})
f=OUT/'SIMULATED_V3_partial_prefix_unit_input';f.mkdir()
(f/'stdout.log').write_text('SIMULATED ONLY, NOT NATIVE\nprovider=SIMULATED\n')
(f/'recorded_frame_indices.bin').write_bytes(struct.pack('<5I',0,1,2,3,4))
(f/'observed_frame_indices.bin').write_bytes(struct.pack('<3I',0,1,2))
(f/'output_presence.bin').write_bytes(bytes([1,1,1]))
for name in ['diffuse.bin','specular.bin']:(f/name).write_bytes(bytes(3*m.FRAME_BYTES))
test('No_footer_semantically_valid_partial_counts_remain_lower_bounds_totals_unknown',f,
 {'successful_API_RR_recordings_confirmed':5,'queued_RR_dispatches_confirmed_completed':3,
  'totals_unknown':True,'completed_native_context_final_marker':False,
  'incomplete_child_native_work_may_exceed_confirmed_lower_bounds':True})
f=OUT/'SIMULATED_V3_invalid65_no_footer_unit_input';f.mkdir()
(f/'stdout.log').write_text('SIMULATED ONLY, NOT NATIVE\nprovider=SIMULATED\n')
(f/'recorded_frame_indices.bin').write_bytes(struct.pack('<65I',*range(65)))
test('Invalid65_prefix_without_footer_is_not_confirmed_count_and_planned64_is_not_filled',f,
 {'successful_API_RR_recordings_confirmed':0,'queued_RR_dispatches_confirmed_completed':0,
  'created_native_context_confirmed':True,'totals_unknown':True,
  'incomplete_child_native_work_may_exceed_confirmed_lower_bounds':True})
f=OUT/'SIMULATED_V3_footer_debug_error_unit_input';f.mkdir()
(f/'stdout.log').write_text('SIMULATED ONLY, NOT NATIVE\nprovider=SIMULATED\nRR_recordings=64 queued_RR_dispatches=64 discarded_RR_recordings=0 validation_errors=1 validation_warnings=2 sdk_errors=0 sdk_warnings=0\n')
test('Valid_completed_footer_preserves64_even_when_later_debug_metadata_acceptance_would_fail',f,
 {'successful_API_RR_recordings_confirmed':64,'queued_RR_dispatches_confirmed_completed':64,
  'completed_native_context_final_marker':True,'metadata_acceptance_evaluated':False})
for frozen in [v1,v2,v3]:check(frozen['files'])
check(v1['external_sources']);assert pins==[identity(p['path'])for p in pins]
assert not(P/'evidence/results.json').exists()
report={'schema':'independent-H2-accounting-V3-pre-native-review-v1','utc':datetime.now(timezone.utc).isoformat(),
 'status':'pre_native_source_and_accounting_ready_for_separate_root_authorization',
 'native_has_not_run':True,'own_GPU_native_build_calls':0,
 'prior_source_review':identity(OUT/'review.json'),'V1_source_inputs_controls_and_metric_analysis_unchanged':True,
 'V1_V2_V3_freezes_verified':True,'V3_driver_delta_from_V2_exact_three_accounting_identity_changes':True,
 'physical_work_accounting_before_guard_debug_metadata_acceptance':True,
 'case_schedule_unchanged':{'contexts':8,'successful_API_recordings':462,'discarded_recordings':4,'queued_RR_dispatches':458},
 'V3_pins_pre_and_post':pins,'CPU_simulated_checks':checks,'CPU_simulated_checks_passed':len(checks),
 'count_authority':'Bounded final CPP footer is the authoritative child-produced counter under the pinned C++ source. Contradictory artifacts remain explicit and cannot increase the authoritative64 to65. Without this marker only registered-prefix/capacity-valid artifact lower bounds are reported; total work remains unknown.',
 'qualifications':[
  'The final marker is an accounting claim from the pinned child, not a GPU quality or SDK validation pass. Debug/metadata rejection must remain separately failed.',
  'Registered capacities constrain validity only; they are never substituted as measurements. Missing or invalid record streams do not prove no native work.',
  'Artifact lower bounds are not exhaustive counts. Partial failure after queue/fence completion but before flushed readback markers may leave additional work unquantified.',
  'Original SDK discard-safe/history rollback gap and no guaranteed RESET-to-fresh identity qualifications remain unchanged. No game, stain cause or accepted fix claim.',
  'Native launch still belongs to root. This review itself runs only Python CPU derivation on clearly labelled simulated data; no helper executable was invoked.'
 ],'quality_accepted':False}
save('review_v3_accounting.json',report)
save('completion_final_manifest.json',{'schema':'independent-H2-full-pre-native-review-completion-v1','status':report['status'],
 'native_has_not_run':True,'own_GPU_native_build_calls':0,'files':[identity(p)for p in sorted(OUT.rglob('*'))if p.is_file()]})
print(json.dumps({'review':identity(OUT/'review_v3_accounting.json'),'manifest':identity(OUT/'completion_final_manifest.json')}))
