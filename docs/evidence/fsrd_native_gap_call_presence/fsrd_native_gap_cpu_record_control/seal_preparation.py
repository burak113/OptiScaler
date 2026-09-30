"""Final CPU verification and immutable preparation manifest. No runner launch."""
from pathlib import Path
import hashlib,json,shlex,struct
HERE=Path(__file__).resolve().parent;PRIOR=HERE.parent/'fsrd_native_discarded_recording_diagnostic_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def verify(records):
    for r in records:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    freeze=json.loads((HERE/'pre_native_freeze.json').read_text());verify(freeze['files']);verify(freeze['external_sources'])
    prior=json.loads((PRIOR/'execution_completion_manifest.json').read_text());verify(prior['files']);verify(prior['external_frozen_sources']);verify(prior['review_external_files'])
    reg=json.loads((HERE/'registration.json').read_text());whitelist=json.loads((HERE/'source_insertion_whitelist.json').read_text())
    text=Path(whitelist['pinned_H2_source']['path']).read_text()
    for op in whitelist['operations']:assert text.count(op['before'])==1;text=text.replace(op['before'],op['after'])
    assert text.encode()==(HERE/'fsrd_rr_gap_control.cpp').read_bytes()
    assert(HERE/'copied_pinned_H2_runner.cpp').read_bytes()==Path(whitelist['pinned_H2_source']['path']).read_bytes()
    assert text.index('if(noApiFrame>=0 && sourceFrame==unsigned(noApiFrame)) {')>text.index('dispatch.flags|=FFX_DENOISER_DISPATCH_RESET;')
    assert text.index('if(noApiFrame>=0 && sourceFrame==unsigned(noApiFrame)) {')<text.index('auto record=[&]')<text.index('ff(api.Dispatch(&context,&dispatch.header),"dispatch RR");')
    tools=json.loads((HERE/'CPU_tool_source_whitelist.json').read_text());verify([tools[k]for k in('core_source','copied_core','analysis_source','new_analysis')])
    assert Path(tools['core_source']['path']).read_bytes()==(HERE/'native_work_accounting_core_v3.py').read_bytes()
    analysis=Path(tools['analysis_source']['path']).read_text()
    for op in tools['analysis_replacements']:assert analysis.count(op['before'])==1;analysis=analysis.replace(op['before'],op['after'])
    assert analysis.encode()==(HERE/'analyze.py').read_bytes()
    source=Path(reg['source_frozen_wave_P']);original_controls=(source/'dispatch_controls.bin').read_bytes();cases={c['tag']:c for c in reg['cases']};payload_bytes=0
    for c in reg['cases']:
        folder=HERE/'evidence'/c['tag'];rows=[shlex.split(s)for s in(folder/'job.txt').read_text().splitlines()]
        assert list(map(int,rows[0][:8]))==[128,80,64,2,32,0,1,0]and c['loop_frames']==64
        assert c['consumed_source_frame_indices']==list(range(64))and c['observed_frame_indices']==[f for f in range(64)if f!=24]
        for i,r in enumerate(c['inputs']):
            data=Path(r['path']).read_bytes();assert data==Path(r['source']['path']).read_bytes();payload_bytes+=len(data)
            assert len(data)==128*80*(8 if r['DXGI_format']==10 else 4)*r['uploads']
            assert Path(rows[i+1][0])==Path(r['path'])and list(map(int,rows[i+1][1:]))==[r['DXGI_format'],r['uploads']]
        full=bytearray(original_controls)
        if c['recovery_reset_frame']==25:struct.pack_into('<I',full,25*184+4,3)
        applied=(folder/'expected_applied_dispatch_controls.bin').read_bytes();queued=(folder/'expected_queued_dispatch_controls.bin').read_bytes()
        assert applied==b''.join(full[f*184:(f+1)*184]for f in c['source_frame_indices'])and len(applied)==c['frames_recorded']*184
        assert queued==b''.join(full[f*184:(f+1)*184]for f in c['observed_frame_indices'])and len(queued)==63*184
        for local,f in enumerate(c['source_frame_indices']):assert struct.unpack_from('<4I',applied,local*184)==(f,3 if f==0 or f==c['recovery_reset_frame']else 2,128,80)
        assert(folder/'expected_output_presence.bin').read_bytes()==bytes(c['output_presence_mask'])and c['output_presence_mask']==[0 if f==24 else 1 for f in range(64)]
        for name,key in(('expected_recorded_frame_indices.bin','source_frame_indices'),('expected_observed_frame_indices.bin','observed_frame_indices'),('expected_omitted_API_frame_indices.bin','omitted_API_frame_indices')):
            expected=c[key];assert(folder/name).read_bytes()==struct.pack('<'+str(len(expected))+'I',*expected)
        assert c['frames_recorded']==c['frames_queued']+c['frames_discarded']and c['frames_recorded']+c['frames_omitted_API']==64
        for name in('resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','dispatch_controls.bin','queued_dispatch_controls.bin','output_presence.bin','observed_frame_indices.bin','recorded_frame_indices.bin','omitted_API_frame_indices.bin','native_work_accounting.json'):
            assert not(folder/name).exists(),'Unexpected actual native artifact '+str(folder/name)
    for r in(0,1):
        for suffix in('','_reset25'):
            a=HERE/'evidence'/f'round{r}_record_discard24{suffix}';b=HERE/'evidence'/f'round{r}_no_api24{suffix}'
            assert(a/'expected_queued_dispatch_controls.bin').read_bytes()==(b/'expected_queued_dispatch_controls.bin').read_bytes()
            packet=(a/'expected_applied_dispatch_controls.bin').read_bytes();assert packet[:24*184]+packet[25*184:]==(b/'expected_applied_dispatch_controls.bin').read_bytes()
    assert[sum(c[k]for c in cases.values())for k in('frames_recorded','frames_queued','frames_discarded','frames_omitted_API')]==[508,504,4,4]
    assert not(HERE/'evidence/results.json').exists();assert(HERE/'build.stderr.bin').stat().st_size==0
    for p in HERE.glob('*.py'):compile(p.read_text(),str(p),'exec')
    cpu=json.loads((HERE/'accounting_cpu_check.json').read_text());assert cpu['status']=='passed'and cpu['cases']==8 and cpu['SIMULATED_NOT_NATIVE_EVIDENCE']
    assert cpu['script_sha256']==sha(HERE/'check_accounting_cpu.py')and cpu['wrapper_sha256']==sha(HERE/'native_work_accounting.py')
    verification={'schema':'matched-gap-CPUrecord-preparation-CPU-verification-v1','status':'passed_preparation_NOT_NATIVE_AUTHORIZATION',
        'source_whitelist_reconstruction_exact':True,'no_API_branch_after_consumption_control_parsing_before_packet_and_API':True,
        'frozen_pre_native_files_verified':len(freeze['files']),'external_frozen_sources_verified':len(freeze['external_sources']),
        'prior_H2_owned281_and_external14_and_review25_verified':True,'prior_H2_reference_not_new_measurement':True,
        'all56_original_raw_input_payloads_exact':True,'payload_files':56,'payload_bytes':payload_bytes,
        'all_expected184_controls_indices_presence_exact':True,'queued_source_frames':list(range(24))+list(range(25,64)),
        'no_API_applied_packet_and_recorded_index24_absent':True,'matched_queued_controls_within_reset_setting_exact':True,
        'accounting_core_V3_byte_exact':True,'SIMULATED_accounting_check':identity(HERE/'accounting_cpu_check.json'),'SIMULATED_CPU_cases':8,
        'new_source':identity(HERE/'fsrd_rr_gap_control.cpp'),'new_EXE':identity(HERE/'fsrd_rr_gap_control.exe'),
        'registration':identity(HERE/'registration.json'),'pre_native_freeze':identity(HERE/'pre_native_freeze.json'),
        'planned_native_contexts':8,'planned_successful_API_RR_recordings':508,'planned_queued_RR_dispatches':504,'planned_discarded_API_RR_recordings':4,'planned_no_API_omissions':4,
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,'actual_no_API_omissions':0,
        'no_actual_native_guard_stdout_output_results_artifacts':True,'run_gate':'Root authorization after independent source/preregistration/accounting review; preparation only.'}
    save(HERE/'preparation_cpu_verification.json',verification)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'preparation_completion_manifest.json',{'schema':'immutable-matched-gap-CPUrecord-preparation-completion-v1','status':'prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN',
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,'actual_no_API_omissions':0,
        'planned_native_contexts':8,'planned_successful_API_RR_recordings':508,'planned_queued_RR_dispatches':504,'planned_discarded_API_RR_recordings':4,'planned_no_API_omissions':4,
        'canonical_future_executor':identity(HERE/'run_native.py'),'files':[identity(p)for p in files],'external_sources':freeze['external_sources']})
    print(json.dumps({'verification':identity(HERE/'preparation_cpu_verification.json'),'completion_manifest':identity(HERE/'preparation_completion_manifest.json'),'owned_files':len(files),'actual_native_contexts':0}),flush=True)
if __name__=='__main__':main()
