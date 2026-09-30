"""Independent CPU-only final pre-continuation seal. Never invokes native."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json
P=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp/fsrd_native_gap_cpu_record_control_20260930')
OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(p):p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def check(rs):
    for r in rs:assert ident(r['path'])==r,r['path']
def save(n,v):
    with(OUT/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
manifestpath=P/'remaining_v2_preparation_completion_manifest.json'
assert sha(manifestpath)=='e2c6a2d5fb90b111e22c534f0cdf9d8a395fdbfcd2014ff327a6209850bca342'
manifest=load(manifestpath);check(manifest['files']);check(manifest['external_sources'])
assert len(manifest['files'])==241 and len(manifest['external_sources'])==23
assert sha(P/'remaining_v2_preparation_verification.json')=='a86437ca6657396166c0cd2836c67c6c52bb13c2df265579a52701e824a6d4b4'
verification=load(P/'remaining_v2_preparation_verification.json')
assert [verification[k]for k in ['actual_new_native_contexts','actual_new_API_RR_recordings','actual_new_queued_RR_dispatches']]==[0,0,0]
review=load(OUT/'source_review_v2.json');check(review['pins']);assert review['remaining_six_not_run']
spec=importlib.util.spec_from_file_location('sealed_warning_policy',P/'diagnostic_warning_policy_v2.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
cpu=load(P/'remaining_v2_CPU_check.json');assert cpu['status']=='passed' and cpu['SIMULATED_NOT_NATIVE_EVIDENCE'] and cpu['tests']==11
for test in cpu['outcomes']:
    # Independently replay only pure CPU policy from preserved simulated arguments.
    noapi=test['SIMULATED_case'].startswith('noAPI')
    try:policy.evaluate({'no_api_frame':24 if noapi else-1},test['counts'],bytes.fromhex(test['stderr_hex']));actual=True
    except AssertionError:actual=False
    assert actual==test['actual_admissible']==test['expected_admissible'],test['SIMULATED_case']
old=load(P/'evidence/results.json');reg=load(P/'registration.json');v2=load(P/'remaining_v2_registration.json')
assert old['status']=='failed_preserved' and old['metadata_accepted_native_contexts']==1
assert [old[k]for k in ['completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions']]==[2,127,126,1,1]
remaining=[c for c in reg['cases']if c['tag']in v2['remaining_case_tags']]
assert len(remaining)==6 and not(P/'evidence/remaining_v2_results.json').exists()
for c in remaining:
    for n in ['resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','native_work_accounting.json']:
        assert not(P/'evidence'/c['tag']/n).exists()
check(manifest['files']);check(manifest['external_sources']);check(review['pins'])
save('final_pre_continuation_review.json',{'schema':'gap-remaining6-independent-final-pre-continuation-review-v2',
 'UTC':datetime.now(timezone.utc).isoformat(),'status':'ready_for_new_root_authorized_exactly_six_continuation',
 'new_native_GPU_build_calls':0,'new_native_work_has_not_run_at_seal':True,'producer241_owned23_external_SHA_verified_before_after':True,
 'producer_completion_manifest':ident(manifestpath),'producer_verification':ident(P/'remaining_v2_preparation_verification.json'),
 'producer11_SIMULATED_policy_checks_independently_recomputed':True,'own14_SIMULATED_adversarial_checks_passed':True,
 'source_review':ident(OUT/'source_review_v2.json'),'source_pins_unchanged':review['pins'],
 'unchanged_CPP_EXE_inputs_controls_guard_accounting_whitelist_exact':True,
 'first2_original_failed_V1_and_accepted1_protected':True,'first2_not_rerun_counted_as_reference_only':True,
 'planned_new_only':[6,381,378,3,3],'actual_original_only':[2,127,126,1,1],
 'warning_policy':'noAPI SDKwarnings0 empty or1 exact measured ASCII CRLF warning only; record-discard0 empty; all D3Derrors/warnings and SDKerrors0. Counts/messages retained, work accounted before any admissibility rejection.',
 'chronology':'Post-observation diagnostic-retention amendment after original2 completed and V1 noAPI warning rejection. This cannot relabel8 as original zero-warning accepted successes.',
 'causal_scope':'Static synthetic wave/camera/jitter/provider/device context only; unframed warning does not prove exact emitting frame or universal SDK behavior/game stain cause.',
 'readiness_is_not_launch_authorization':True,'quality_accepted':False,'general_fix':False})
save('completion_ready_manifest.json',{'files':[ident(p)for p in sorted(OUT.rglob('*'))if p.is_file()],
 'new_native_work_has_not_run_at_seal':True,'source_evidence_modified':False,'quality_accepted':False})
print(json.dumps({'review':ident(OUT/'final_pre_continuation_review.json'),'manifest':ident(OUT/'completion_ready_manifest.json')}))
