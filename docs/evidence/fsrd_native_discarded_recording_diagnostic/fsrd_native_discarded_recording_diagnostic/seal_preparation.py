"""CPU verification and immutable preparation seal; never execute any helper EXE."""
from pathlib import Path
import hashlib,json,shlex,struct
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(items):
    for r in items:
        p=Path(r['path']);assert p.stat().st_size==r['bytes']and sha(p)==r['sha256'],str(p)
def main():
    freeze=json.loads((HERE/'pre_native_freeze.json').read_text());v2=json.loads((HERE/'accounting_v2_pre_native_freeze.json').read_text())
    verify(freeze['files']);verify(freeze['external_sources']);verify(v2['files'])
    reg=json.loads((HERE/'registration.json').read_text());assert reg['preparation_only']and reg['actual_native_contexts']==0
    whitelist=json.loads((HERE/'source_insertion_whitelist.json').read_text());text=Path(whitelist['original']['path']).read_text()
    for op in whitelist['operations']:
        assert text.count(op['before'])==1;text=text.replace(op['before'],op['after'])
    assert text.encode()==(HERE/'fsrd_rr_discard.cpp').read_bytes()
    source=Path(reg['source_frozen_wave_P']);original_controls=(source/'dispatch_controls.bin').read_bytes();cases={c['tag']:c for c in reg['cases']};input_bytes=0
    for c in reg['cases']:
        folder=HERE/'evidence'/c['tag'];rows=[shlex.split(s)for s in(folder/'job.txt').read_text().splitlines()]
        assert list(map(int,rows[0][:8]))==[128,80,c['frames_recorded'],2,32,0,1,0]
        assert[int(r[1])for r in rows[1:8]]==[41,10,24,28,28,10,10]
        for i,r in enumerate(c['inputs']):
            data=Path(r['path']).read_bytes();src=Path(r['source']['path']).read_bytes();bpp=8 if r['DXGI_format']==10 else 4
            expected=src[25*128*80*bpp:]if c['kind']=='fresh_tail25'and r['source']['bytes']==64*128*80*bpp else src
            assert data==expected and len(data)==128*80*bpp*r['uploads'];input_bytes+=len(data)
            assert Path(rows[i+1][0])==Path(r['path'])and list(map(int,rows[i+1][1:]))==[r['DXGI_format'],r['uploads']]
        control=(folder/'expected_applied_dispatch_controls.bin').read_bytes();assert len(control)==c['frames_recorded']*184
        for local,source_frame in enumerate(c['source_frame_indices']):
            flags=3 if local==0 or source_frame==c['recovery_reset_frame']else 2
            assert struct.unpack_from('<4I',control,local*184)==(source_frame,flags,128,80)
        presence=(folder/'expected_output_presence.bin').read_bytes();assert list(presence)==c['output_presence_mask']
        assert presence.count(0)==c['frames_discarded']and presence.count(1)==c['frames_queued']
        observed=(folder/'expected_observed_frame_indices.bin').read_bytes();assert list(struct.unpack('<'+str(c['frames_queued'])+'I',observed))==c['observed_frame_indices']
        assert c['expected_raw_lobe_bytes']==c['frames_queued']*128*80*8
        for name in('resource_guard.json','stdout.log','stderr.log','diffuse.bin','specular.bin','dispatch_controls.bin','output_presence.bin','observed_frame_indices.bin','recorded_frame_indices.bin'):
            assert not(folder/name).exists(),'Unexpected actual native artifact '+str(folder/name)
    for round_ in(0,1):
        def controls(kind):return(HERE/'evidence'/f'round{round_}_{kind}'/'expected_applied_dispatch_controls.bin').read_bytes()
        baseline=controls('baseline');drop=controls('discard24');reset=controls('discard24_reset25');tail=controls('fresh_tail25')
        assert baseline==drop==original_controls
        assert sum(a!=b for a,b in zip(baseline,reset))==1 and reset[25*184+4]==3
        assert tail==reset[25*184:]and len(tail)==39*184
    assert sum(c['frames_recorded']for c in cases.values())==462 and sum(c['frames_queued']for c in cases.values())==458 and sum(c['frames_discarded']for c in cases.values())==4
    assert not(HERE/'evidence/results.json').exists()
    for name in('prepare.py','run_native.py','run_native_v2.py','native_work_accounting.py','analyze.py'):
        compile((HERE/name).read_text(),str(HERE/name),'exec')
    assert(HERE/'build.stderr.bin').stat().st_size==0
    verification={'schema':'H2-preparation-CPU-verification-v1','status':'passed_preparation_NOT_NATIVE_AUTHORIZATION',
        'original_whitelist_reconstruction_exact':True,'frozen_V1_files_verified':len(freeze['files']),'external_sources_verified':len(freeze['external_sources']),
        'accounting_V2_frozen_files_verified':len(v2['files']),'all8x7_raw_input_payloads_exact':True,'payload_files':56,'payload_bytes':input_bytes,
        'all_expected_184_controls_masks_indices_exact':True,'tail_source_frame_indices':list(range(25,64)),
        'fresh_tail_expected_controls_exact_to_RESET25_recovery_tail':True,'source_original_SHA':reg['original_runner']['sha256'],
        'new_source':identity(HERE/'fsrd_rr_discard.cpp'),'new_EXE':identity(HERE/'fsrd_rr_discard.exe'),
        'original_registration':identity(HERE/'registration.json'),'original_freeze':identity(HERE/'pre_native_freeze.json'),
        'accounting_V2_registration':identity(HERE/'accounting_v2_registration.json'),'accounting_V2_freeze':identity(HERE/'accounting_v2_pre_native_freeze.json'),
        'planned_native_contexts':8,'planned_successful_API_RR_recordings':462,'planned_discarded_API_RR_recordings':4,'planned_queued_RR_dispatches':458,
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
        'no_actual_native_guard_stdout_output_or_results_artifacts':True,'accounting_tests':'Four SIMULATED CPU-only cases; test fixtures do not represent native work.',
        'run_gate':'Root authorization after both reviews; current task is preparation only.'}
    save(HERE/'preparation_cpu_verification.json',verification)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'preparation_completion_manifest.json',{'schema':'immutable-H2-preparation-completion-v1','status':'prepared_built_preregistered_NOT_AUTHORIZED_TO_RUN',
        'actual_native_contexts':0,'actual_successful_API_RR_recordings':0,'actual_queued_RR_dispatches':0,
        'planned_native_contexts':8,'planned_successful_API_RR_recordings':462,'planned_discarded_API_RR_recordings':4,'planned_queued_RR_dispatches':458,
        'canonical_future_executor':identity(HERE/'run_native_v2.py'),'files':[identity(p)for p in files]})
    print(json.dumps({'verification':identity(HERE/'preparation_cpu_verification.json'),'completion_manifest':identity(HERE/'preparation_completion_manifest.json'),
                      'source':identity(HERE/'fsrd_rr_discard.cpp'),'EXE':identity(HERE/'fsrd_rr_discard.exe'),'frozen_package_files':len(files),'actual_native_contexts':0}),flush=True)
if __name__=='__main__':main()
