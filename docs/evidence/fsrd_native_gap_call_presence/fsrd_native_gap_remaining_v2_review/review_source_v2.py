"""CPU-only review of frozen V2 continuation; no native entrypoint invoked."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp')
P=ROOT/'fsrd_native_gap_cpu_record_control_20260930';OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(p):p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def check(rs):
    for r in rs:assert ident(r['path'])==r,r['path']
def save(n,v):
    with(OUT/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
reg=load(P/'registration.json');v=load(P/'remaining_v2_registration.json');seal=load(P/'remaining_v2_pre_native_freeze.json')
assert sha(P/'remaining_v2_registration.json')=='8c126e93e85260af70e7ca5e13801c7ed7a0e5bc09e2d38a1f382829e6ff9e79'
assert sha(P/'remaining_v2_pre_native_freeze.json')=='82209ebfaa0b7ec5cb61dc9e5167633a987b81949eceea6543a4ba3b17687799'
old=load(P/'pre_native_freeze.json');partial=load(P/'partial_v1_completion_manifest.json')
for rs in [seal['files'],old['files'],old['external_sources'],partial['files']]:check(rs)
assert v['post_observation'] and v['status']=='prepared_post_observation_NOT_AUTHORIZED_TO_RUN'
assert v['remaining_case_tags']==reg['mode_order'][2:]
remaining=[c for c in reg['cases']if c['tag']in v['remaining_case_tags']]
assert len(remaining)==6 and v['commands']==[c['command']for c in remaining]
assert [sum(c[k]for c in remaining)for k in ['frames_recorded','frames_queued','frames_discarded','frames_omitted_API']]==[381,378,3,3]
for c in remaining:
    for n in ['resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','native_work_accounting.json']:
        assert not(P/'evidence'/c['tag']/n).exists()
assert not(P/'evidence/remaining_v2_results.json').exists()
w=load(P/'remaining_v2_driver_whitelist.json');check([w['frozen_V1_driver'],w['new_V2_driver']])
s=Path(w['frozen_V1_driver']['path']).read_text()
for o in w['operations']:
    assert s.count(o['before'])==o['occurrences'];s=s.replace(o['before'],o['after'])
actual=(P/'run_remaining_native_v2.py').read_text();assert s==actual
assert actual.index('accounting=derive(')<actual.index('checkpoint()\n            if guard_error is not None:raise guard_error')<actual.index('evaluate_diagnostics(c,counts')
assert "target=HERE/'evidence/remaining_v2_results.json'"in actual
assert "if sys.argv[1:]!=['--execute-remaining-native']"in actual
assert "'only6remaining_contexts_counted_here':True"in actual
assert actual.count("check(supplement['files']);check(partial['files'])")==3
spec=importlib.util.spec_from_file_location('reviewed_exact_warning_policy',P/'diagnostic_warning_policy_v2.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
known=(P/'evidence/round0_no_api24/stderr.log').read_bytes()
assert known==policy.KNOWN_WARNING==b'SDK: Frame index jump detected. Resetting...\r\n'
checks=[]
def test(name,noapi,warnings,stderr,accepted,errors=(0,0,0)):
    c={'no_api_frame':24 if noapi else-1};counts=[63,63,0,*errors,warnings,1]
    try:r=policy.evaluate(c,counts,stderr);success=True
    except AssertionError:r=None;success=False
    assert success==accepted,name
    if r:assert not r['quality_accepted'] and not r['warning_count_is_quality_score'] and r['actual_SDK_warning_count']==warnings
    checks.append({'SIMULATED_CPU_ONLY':True,'name':name,'accepted_diagnostic_retention':success,'counts':counts,'stderr_hex':stderr.hex()})
test('noAPI_exact_measured_CRLF_warning',True,1,known,True)
test('noAPI_zero_empty',True,0,b'',True)
test('record_zero_empty',False,0,b'',True)
test('record_known_warning_rejected',False,1,known,False)
test('noAPI_two_warning_count_rejected',True,2,known,False)
test('noAPI_unknown_warning_rejected',True,1,b'SDK: unknown\r\n',False)
test('noAPI_warning_count0_message_rejected',True,0,known,False)
test('noAPI_warning_count1_empty_rejected',True,1,b'',False)
test('noAPI_LF_only_not_actual_bytes_rejected',True,1,known.replace(b'\r\n',b'\n'),False)
test('noAPI_duplicate_warning_rejected',True,1,known+known,False)
test('noAPI_extra_whitespace_rejected',True,1,known+b' ',False)
test('noAPI_D3D_error_rejected',True,1,known,False,(1,0,0))
test('noAPI_D3D_warning_rejected',True,1,known,False,(0,1,0))
test('noAPI_SDK_error_rejected',True,1,known,False,(0,0,1))
rep=load(P/'evidence/results.json')
assert rep['status']=='failed_preserved' and rep['metadata_accepted_native_contexts']==1
assert [rep[k]for k in ['completed_native_contexts','successful_API_RR_recordings','queued_RR_dispatches','discarded_RR_recordings','no_API_omissions']]==[2,127,126,1,1]
combined=(P/'analyze_combined_v2.py').read_text()
assert "'original_V1_metadata_accepted':p['metadata_accepted']if is_old else None"in combined
assert "'V2_diagnostic_retention_accepted':p['metadata_accepted']if not is_old else None"in combined
assert "original['metadata_accepted_native_contexts']==1"in combined
for rs in [seal['files'],old['files'],old['external_sources'],partial['files']]:check(rs)
save('source_review_v2.json',{'schema':'gap-six-continuation-independent-source-review-v2','UTC':datetime.now(timezone.utc).isoformat(),
 'status':'source_passed_final_producer_completion_pending','new_native_GPU_build_calls':0,'remaining_six_not_run':True,
 'source_whitelist_exact':True,'original_CPP_EXE56inputs_controls_and_first2_seal_unchanged':True,'actual_work_checkpoint_before_guard_metadata_rejection':True,
 'warning_policy_measured_CRLF_exact_and14_SIMULATED_checks':checks,
 'post_observation_chronology_and_original_V1_rejection_preserved':True,'original_actual_counts':[2,127,126,1,1],'original_metadata_accepted':1,
 'new_planned_only_counts':[6,381,378,3,3],'old2_not_rerun_or_new_counts':True,
 'pins':[ident(P/n)for n in ['remaining_v2_registration.json','remaining_v2_pre_native_freeze.json','remaining_v2_driver_whitelist.json','run_remaining_native_v2.py','diagnostic_warning_policy_v2.py','analyze_combined_v2.py','evidence/results.json']],
 'limits':['Diagnostic retention after measured warning is not original preregistration or quality acceptance.', 'SDK warning has no emitting-frame timestamp; association with next25 is an inference. Static wave/camera/jitter and this provider/context cannot establish game scheduling, universal SDK contract, visible stain cause or quality.', 'Final producer CPU/selfcheck/completion seal still required before root-authorized execution.'],
 'quality_accepted':False})
print(json.dumps(ident(OUT/'source_review_v2.json')))
