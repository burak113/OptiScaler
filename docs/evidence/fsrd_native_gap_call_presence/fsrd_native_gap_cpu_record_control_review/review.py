"""CPU-only pre-native source/payload/accounting review."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json,struct,sys,shlex
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp')
P=ROOT/'fsrd_native_gap_cpu_record_control_20260930';OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):
    p=Path(p);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p):return json.loads(Path(p).read_text())
def check(items):
    for item in items:assert identity(item['path'])==item,item['path']
def save(name,v):
    with(OUT/name).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
reg=load(P/'registration.json');freeze=load(P/'pre_native_freeze.json')
check(freeze['files']);check(freeze['external_sources'])
assert reg['status']=='prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN'
assert not(P/'evidence/results.json').exists()
assert all(reg[k]==0 for k in ['actual_native_contexts','actual_successful_API_RR_recordings','actual_queued_RR_dispatches','actual_no_API_omissions'])
pins=[identity(P/n)for n in ['registration.json','pre_native_freeze.json','fsrd_rr_gap_control.cpp','fsrd_rr_gap_control.exe','native_work_accounting.py','native_work_accounting_core_v3.py','run_native.py','analyze.py']]
whitelist=load(P/'source_insertion_whitelist.json')
assert whitelist['pinned_H2_source']['sha256']=='5446243c4a7b18f94254f1b1098313102da9d601ee4dcec6433eb3a36993207c'
source=Path(whitelist['pinned_H2_source']['path']).read_text()
assert source==(P/'copied_pinned_H2_runner.cpp').read_text()
labels={'optional_no_API_argument','no_API_argument_validation','registered_argument_log','no_API_frame_range',
 'separate_actual_omission_metadata','no_API_branch_after_inputs_controls_before_applied_packet_and_API',
 'close_omission_metadata','direct_footer_omission_counter'}
assert {o['label']for o in whitelist['operations']}==labels
for op in whitelist['operations']:
    assert source.count(op['before'])==1;source=source.replace(op['before'],op['after'])
actual=(P/'fsrd_rr_gap_control.cpp').read_text();assert actual==source
branch_start=actual.index('if(noApiFrame>=0 && sourceFrame==unsigned(noApiFrame))')
control_write=actual.index('auto record=[&]',branch_start)
api=actual.index('ff(api.Dispatch(&context,&dispatch.header)',control_write)
recordindex=actual.index('recordedFrameIndicesOut.write',api)
branch=actual[branch_start:control_write]
assert branch_start<control_write<api<recordindex
assert 'hr(cmd->Close(),"close no-API discarded recording")' in branch
assert 'tex[i].state=externalStatesBeforeRecording[i]' in branch
assert 'omittedAPIFrameIndicesOut.write' in branch and 'continue;'in branch
assert 'api.Dispatch('not in branch and 'controlsOut.write'not in branch and 'ExecuteCommandLists('not in branch
assert 'dispatch.frameIndex=sourceFrame;'in actual
assert actual.index('t.input.read')<branch_start and actual.index('controlsIn>>reset>>jx>>jy')<branch_start
assert 'previousSubmittedSourceFrame!=int(sourceFrame)-1 || previousCompletedFence==0'in branch
prior=ROOT/'fsrd_native_discarded_recording_diagnostic_20260930'
assert (P/'native_work_accounting_core_v3.py').read_bytes()==(prior/'native_work_accounting_v3.py').read_bytes()
driver=(P/'run_native.py').read_text()
assert driver.index('accounting=derive(')<driver.index("if guard['status']")
old=Path(reg['source_frozen_wave_P']);oid=load(old/'amd_context_identity.json')
for name,h in oid['inputs'].items():assert sha(old/name)==h
assert sha(old/'dispatch_controls.bin')==oid['applied_dispatch_sha256']
old_controls=(old/'dispatch_controls.bin').read_bytes();original_rows=[shlex.split(x)for x in(old/'job.txt').read_text().splitlines()]
case_rows=[];group_hashes={};total=[0,0,0,0]
for c in reg['cases']:
    folder=P/'evidence'/c['tag'];noapi=c['no_api_frame']==24;reset=c['recovery_reset_frame']==25
    assert not(folder/'resource_guard.json').exists() and not(folder/'diffuse.bin').exists()
    expected_observed=[f for f in range(64)if f!=24];expected_recorded=expected_observed if noapi else list(range(64))
    assert c['observed_frame_indices']==expected_observed and c['source_frame_indices']==expected_recorded
    assert c['omitted_API_frame_indices']==([24]if noapi else[])
    assert c['consumed_source_frame_indices']==list(range(64)) and c['source_frame_start']==0
    assert [c[k]for k in ['frames_recorded','frames_queued','frames_discarded','frames_omitted_API']]==[63 if noapi else 64,63,0 if noapi else 1,1 if noapi else 0]
    full=bytearray(old_controls)
    if reset:struct.pack_into('<I',full,25*184+4,3)
    expected_applied=b''.join(full[f*184:(f+1)*184]for f in expected_recorded)
    expected_queued=b''.join(full[f*184:(f+1)*184]for f in expected_observed)
    assert(folder/'expected_applied_dispatch_controls.bin').read_bytes()==expected_applied
    assert(folder/'expected_queued_dispatch_controls.bin').read_bytes()==expected_queued
    assert len(expected_applied)==184*len(expected_recorded) and len(expected_queued)==184*63
    for filename,ids in [('expected_recorded_frame_indices.bin',expected_recorded),('expected_observed_frame_indices.bin',expected_observed),('expected_omitted_API_frame_indices.bin',[24]if noapi else[])]:
        assert(folder/filename).read_bytes()==struct.pack('<'+'I'*len(ids),*ids)
    assert(folder/'expected_output_presence.bin').read_bytes()==bytes(f!=24 for f in range(64))
    job=[shlex.split(x)for x in(folder/'job.txt').read_text().splitlines()]
    assert list(map(int,job[0][:8]))==[128,80,64,2,32,0,1,0]
    assert Path(job[0][8])==Path(reg['dll']['path'])
    ih=[]
    for i,item in enumerate(c['inputs']):
        p=Path(item['path']);assert p.read_bytes()==(old/f'input{i}.bin').read_bytes()
        assert item['DXGI_format']==int(original_rows[i+1][1]) and item['uploads']==int(original_rows[i+1][2])
        assert identity(p)=={k:item[k]for k in ['path','bytes','sha256']};ih.append(sha(p))
    assert [x['uploads']for x in c['inputs']]==[1,1,1,1,1,64,64]
    if reset in group_hashes:assert group_hashes[reset]==(ih,hashlib.sha256(expected_queued).hexdigest())
    else:group_hashes[reset]=(ih,hashlib.sha256(expected_queued).hexdigest())
    assert(folder/'frame_controls.txt').read_bytes()==(old/'frame_controls.txt').read_bytes()
    assert(folder/'camera.txt').exists()==(old/'camera.txt').exists()
    if(old/'camera.txt').exists():assert(folder/'camera.txt').read_bytes()==(old/'camera.txt').read_bytes()
    case_rows.append({'tag':c['tag'],'noAPI24':noapi,'RESET25':reset,'API_recordings':len(expected_recorded),'queued_frames':63,
                     'applied_control_bytes':len(expected_applied),'queued_control_SHA':hashlib.sha256(expected_queued).hexdigest(),
                     'all7_input_copies_authenticated':True})
    for i,k in enumerate(['frames_recorded','frames_queued','frames_discarded','frames_omitted_API']):total[i]+=c[k]
assert total==[508,504,4,4] and len(case_rows)==8
sys.path.insert(0,str(P))
spec=importlib.util.spec_from_file_location('reviewed_gap_accounting',P/'native_work_accounting.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
checks=[]
for noapi in [False,True]:
    c={**next(c for c in reg['cases']if(c['no_api_frame']==24)==noapi),'tag':'SIMULATED_only_'+('no_api'if noapi else'API_discard')}
    f=OUT/('SIMULATED_unit_'+('no_api'if noapi else'API_discard'));f.mkdir()
    api_count=63 if noapi else 64;discard=0 if noapi else 1;omitted=1 if noapi else 0
    (f/'stdout.log').write_text(f'SIMULATED ONLY NOT NATIVE\nprovider=SIMULATED\nRR_recordings={api_count} queued_RR_dispatches=63 discarded_RR_recordings={discard} validation_errors=1 validation_warnings=0 sdk_errors=0 sdk_warnings=0 no_API_omissions={omitted}\n')
    for name,ids in [('recorded_frame_indices.bin',c['source_frame_indices']),('observed_frame_indices.bin',c['observed_frame_indices']),('omitted_API_frame_indices.bin',c['omitted_API_frame_indices'])]:
        (f/name).write_bytes(struct.pack('<'+'I'*len(ids),*ids))
    (f/'output_presence.bin').write_bytes(bytes(c['output_presence_mask']))
    a=m.derive(f,{'child_pid':1,'status':'completed','returncode':0},c)
    assert [a[k]for k in ['successful_API_RR_recordings_confirmed','queued_RR_dispatches_confirmed_completed','discarded_API_RR_recordings_confirmed','no_API_omissions_confirmed']]==[api_count,63,discard,omitted]
    assert not a['totals_unknown'] and not a['metadata_acceptance_evaluated']
    checks.append({'SIMULATED_NOT_NATIVE_EVIDENCE':True,'case':c['tag'],'derived':a})
check(freeze['files']);check(freeze['external_sources']);assert pins==[identity(item['path'])for item in pins]
assert not(P/'evidence/results.json').exists()
report={'schema':'matched-gap-CPU-record-independent-pre-native-review-v1','UTC':datetime.now(timezone.utc).isoformat(),
 'status':'source_review_passed_final_producer_manifest_pending','native_has_not_run':True,'own_GPU_native_build_calls':0,
 'source_whitelist_reconstruction_exact':True,'noAPI_branch_before_applied_control_API_and_successful_record_index':True,
 'all56_input_files_and_queued_controls_within_reset_factor_exact':True,'cases':case_rows,
 'planned_only':{'contexts':8,'API_recordings':508,'queued':504,'SDK_discard':4,'noAPI_omissions':4},
 'accounting_byte_exact_V3_core_verified':True,'independent_SIMULATED_stage_checks':checks,
 'qualifications':['Matched queued input/control topology isolates successfulSDKrecord24 call-presence conditional effect in this fixture; it does not identify opaque CPU history, camera bookkeeping or private resource mutation mechanism.',
                   'Frozen synthetic wave source, static camera/jitter, this provider/device/context setup cannot imply all SDK contexts, game scheduling, supported discarded-recording contract or a quality/stain fix.',
                   'Metadata/debug acceptance is separate from native work accounting. Registered capacities constrain footer/prefix validity but never populate planned counts as measurements.',
                   'Final producer selfcheck/manifest hash verification is still required before readiness; source review alone does not authorize native execution.'],
 'source_pins_pre_and_post':pins,'quality_accepted':False}
save('source_review.json',report)
print(json.dumps({'review':identity(OUT/'source_review.json')}))
