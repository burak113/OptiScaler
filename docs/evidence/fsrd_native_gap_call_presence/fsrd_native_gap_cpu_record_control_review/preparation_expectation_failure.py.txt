"""Read-only producer seal verification; explicitly simulated accounting checks."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, importlib.util, json, struct, sys
OUT=Path(__file__).resolve().parent
P=OUT.parent/'fsrd_native_gap_cpu_record_control_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ident(p):p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def save(name,v):
    with (OUT/name).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(records):
    for r in records:assert ident(r['path'])==r,r['path']
seal=P/'preparation_completion_manifest.json'
assert sha(seal)=='19b63ab8f27ceaa6a03632b29414afc654a273a47e5636f7f30f079de8d04317'
manifest=load(seal);verify(manifest['files']);verify(manifest['external_sources'])
assert len(manifest['files'])==199 and len(manifest['external_sources'])==23
assert manifest['actual_native_contexts']==manifest['actual_successful_API_RR_recordings']==manifest['actual_queued_RR_dispatches']==manifest['actual_no_API_omissions']==0
reg=load(P/'registration.json');pre=load(P/'pre_native_freeze.json');verify(pre['files']);verify(pre['external_sources'])
assert sha(P/'preparation_cpu_verification.json')=='4a6b39d4e32be33d89a85e0b006651673ce830b6063b4a44693e9964051a3345'
producer_checks=load(P/'accounting_cpu_check.json')
assert producer_checks['SIMULATED_NOT_NATIVE_EVIDENCE'] and producer_checks['cases']==8 and producer_checks['status']=='passed'
assert producer_checks['script_sha256']==sha(P/'check_accounting_cpu.py')
assert producer_checks['wrapper_sha256']==sha(P/'native_work_accounting.py')
source=load(OUT/'source_review.json');assert source['native_has_not_run']
verify(source['source_pins_pre_and_post'])
assert source['source_whitelist_reconstruction_exact'] and source['all56_input_files_and_queued_controls_within_reset_factor_exact']
# Explicit byte-level flags namespace check; no linear-depth flag attribution.
control_rows=[]
for c in reg['cases']:
    folder=P/'evidence'/c['tag']
    for forbidden in ['resource_guard.json','stdout.log','stderr.log','dispatch_controls.bin','diffuse.bin','specular.bin','recorded_frame_indices.bin','observed_frame_indices.bin','output_presence.bin','omitted_API_frame_indices.bin']:
        assert not (folder/forbidden).exists(),str(folder/forbidden)
    data=(folder/'expected_applied_dispatch_controls.bin').read_bytes()
    for i,sourceframe in enumerate(c['source_frame_indices']):
        sdkframe,flags,w,h=struct.unpack_from('<IIII',data,i*184)
        assert sdkframe==sourceframe and (w,h)==(128,80)
        assert flags==(3 if sourceframe==0 or sourceframe==c['recovery_reset_frame'] else 2)
    assert len(data)==184*c['frames_recorded']
    control_rows.append({'case':c['tag'],'184_byte_packets':c['frames_recorded'],'SDK_frameIndex_absolute_source_index':True,'flags_NON_GAMMA_ALBEDO_2_and_RESET_1':True})
assert not(P/'evidence/results.json').exists()
sys.path.insert(0,str(P))
spec=importlib.util.spec_from_file_location('independent_final_gap_accounting',P/'native_work_accounting.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
noapi=next(c for c in reg['cases']if c['no_api_frame']==24)
record=next(c for c in reg['cases']if c['skip_frame']==24)
def sim(name,c,footer,recorded,observed,presence,omitted,expected,unknown):
    d=OUT/('SIMULATED_final_'+name);d.mkdir()
    (d/'stdout.log').write_text('SIMULATED ONLY; no native child\nprovider=SIMULATED\n'+footer,encoding='utf-8')
    for n,v in [('recorded_frame_indices.bin',recorded),('observed_frame_indices.bin',observed),('omitted_API_frame_indices.bin',omitted)]:
        if v is not None:(d/n).write_bytes(struct.pack('<'+'I'*len(v),*v))
    if presence is not None:(d/'output_presence.bin').write_bytes(bytes(presence))
    result=m.derive(d,{'child_pid':123,'status':'SIMULATED_ONLY','returncode':2},{**c,'tag':'SIMULATED_'+name})
    got=[result[k]for k in ['successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed']]
    assert got==expected,(name,got)
    assert result['totals_unknown']==unknown and not result['planned_counts_are_measurements'] and not result['metadata_acceptance_evaluated']
    assert result['observed_output_frames_confirmed']==0
    assert result['evidence_disagreements'] # No raw lobes; metadata rejection must not erase actual stages.
    save('SIMULATED_final_'+name+'.json',result)
    return {'SIMULATED_NOT_NATIVE_EVIDENCE':True,'name':name,'counts':got,'totals_unknown':unknown,'raw_output_files_created':False}
def footer(a,q,d,o):return f'RR_recordings={a} queued_RR_dispatches={q} discarded_RR_recordings={d} validation_errors=1 validation_warnings=0 sdk_errors=0 sdk_warnings=0 no_API_omissions={o}\n'
checks=[]
checks.append(sim('noAPI_footer63_reject64_indices',noapi,footer(63,63,0,1),list(range(64)),noapi['observed_frame_indices'],noapi['output_presence_mask'],[24],[63,63,0,1],False))
checks.append(sim('noAPI_footer1_reject2_omissions',noapi,footer(63,63,0,1),noapi['source_frame_indices'],noapi['observed_frame_indices'],noapi['output_presence_mask'],[24,24],[63,63,0,1],False))
prefix=list(range(24))+[25]
checks.append(sim('noAPI_partial_nofooter',noapi,'',prefix,prefix,[1]*24+[0,1],[24],[25,25,0,1],True))
checks.append(sim('record_partial_nofooter',record,'',list(range(26)),prefix,[1]*24+[0,1],[],[26,25,1,0],True))
checks.append(sim('invalid_footer_capacity',noapi,footer(64,64,0,0),[0,1,2],[0],[1],[],[3,1,0,0],True))
# Guard is source-pinned, not executed here. Confirm usual unchanged process-local limits.
driver=(P/'run_native.py').read_text()
assert driver.index('accounting=derive(')<driver.index('if guard_error is not None:raise guard_error')<driver.index("if guard['status']")
guard=(P/'native_resource_guard.py').read_text()
assert sha(P/'native_resource_guard.py')=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
assert '240' in guard and '1024' in guard
verify(manifest['files']);verify(manifest['external_sources']);verify(source['source_pins_pre_and_post'])
assert not(P/'evidence/results.json').exists()
report={'schema':'matched-gap-CPUrecord-final-independent-pre-native-seal-v1','UTC':datetime.now(timezone.utc).isoformat(),
 'status':'ready_for_root_authorized_bounded_native_diagnostic','actual_native_has_not_run':True,'own_GPU_native_build_calls':0,
 'producer_owned199_external23_all_hashes_verified_before_and_after':True,'producer_completion_manifest':ident(seal),
 'producer_CPU_verification':ident(P/'preparation_cpu_verification.json'),'source_review':ident(OUT/'source_review.json'),
 'source_reg_freeze_and_executable': [ident(P/n)for n in ['registration.json','pre_native_freeze.json','fsrd_rr_gap_control.cpp','fsrd_rr_gap_control.exe','run_native.py','native_work_accounting.py','native_work_accounting_core_v3.py','native_resource_guard.py']],
 'controls':control_rows,'producer_SIMULATED_checks_authenticated':8,'own_additional_SIMULATED_checks':checks,
 'reviewer_preparation_erratum':'Initial own review.py had else64/else1/else0 lexical syntax errors and failed before imports, source reads, checks or measurements. That exact initial script is preserved as preparation_syntax_failure.py.txt; whitespace-only correction succeeded. No producer/evidence change.',
 'planned_only':{'contexts':8,'API_recordings':508,'queued_RR':504,'SDK_discard':4,'noAPI_omission':4},
 'causal_scope':'Same queued source input bytes and controls, matched RESET25 factor. API24 successful record versus noAPI24 while both abandon GPU24. A conditional difference does not identify opaque SDK CPU bookkeeping/private-resource mutation, establish discard support, or imply game behavior.',
 'readiness_is_not_execution_authorization':True,'quality_accepted':False,'general_stain_wave_fix':False}
save('final_pre_native_review.json',report)
files=[ident(p)for p in sorted(OUT.rglob('*'))if p.is_file()]
save('completion_ready_manifest.json',{'schema':'immutable-gap-control-independent-pre-native-review-completion-v1','files':files,'actual_native_has_not_run_at_seal':True,'quality_accepted':False})
print(json.dumps({'review':ident(OUT/'final_pre_native_review.json'),'manifest':ident(OUT/'completion_ready_manifest.json')}))
