"""Preregistered bounded GPU execution; keeps every actual child/log/payload byte."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,re,struct
from native_resource_guard import run_guarded
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,v,exclusive=False):
    with Path(p).open('x'if exclusive else'w',encoding='utf-8',newline='\n')as f:
        json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def check(items):
    for item in items:
        p=Path(item['path']);assert p.stat().st_size==item['bytes']and sha(p)==item['sha256'],str(p)
def tuple_bytes(rows):return b''.join(struct.pack('<4I',*r)for r in rows)
def main():
    result_path=HERE/'evidence/results.json'
    if result_path.exists()or(HERE/'run_schedule_registration.json').exists():raise ValueError('Preserve attempted GPU evidence')
    reg=json.loads((HERE/'registration.json').read_text());freeze=json.loads((HERE/'pre_gpu_freeze.json').read_text())
    assert reg['GPU_child_jobs']==9 and reg['identity_shader_dispatches']==40
    check(freeze['files']);check(freeze['original_sources'])
    schedule={'schema':'compute-ring-exact-GPU-command-schedule-before-launch-v1','utc':datetime.now(timezone.utc).isoformat(),
              'source_registration':identity(HERE/'registration.json'),'source_freeze':identity(HERE/'pre_gpu_freeze.json'),
              'driver':identity(Path(__file__)),'guard':identity(HERE/'native_resource_guard.py'),
              'commands':[],'GPU_jobs_already_run':0,'shader_dispatches_already_run':0,'native_SDK_dispatches_already_run':0}
    for c in reg['cases']:
        folder=HERE/'evidence'/c['case'];args=[str(HERE/'fixture.exe'),str(folder/'job.txt'),str(HERE/'identity.cso')]
        assert not(folder/'resource_guard.json').exists()
        schedule['commands'].append({'case':c['case'],'args':args,'job':identity(folder/'job.txt'),
                                     'intended':c['intended'],'last_CPU_slot_contents_hypothesis':c['last_CPU_slot_contents_hypothesis']})
    save(HERE/'run_schedule_registration.json',schedule,True)
    save(HERE/'driver_pre_gpu_freeze.json',{'schema':'compute-ring-runner-before-GPU-byte-freeze-v1',
        'files':[identity(HERE/n)for n in('run_gpu.py','run_schedule_registration.json','registration.json','pre_gpu_freeze.json','fixture.exe','identity.cso','native_resource_guard.py')],
        'GPU_jobs_already_run':0,'native_SDK_dispatches_already_run':0},True)
    driver_freeze=json.loads((HERE/'driver_pre_gpu_freeze.json').read_text())
    result={'schema':'extracted-compute-ring-actual-GPU-evidence-v1','status':'running',
            'registration_sha256':sha(HERE/'registration.json'),'pre_gpu_freeze_sha256':sha(HERE/'pre_gpu_freeze.json'),
            'driver_pre_gpu_freeze_sha256':sha(HERE/'driver_pre_gpu_freeze.json'),
            'GPU_child_jobs_launched':0,'GPU_child_jobs_completed':0,'identity_shader_dispatches_completed':0,
            'native_SDK_contexts':0,'native_SDK_dispatches':0,'game_run':False,'quality_accepted':False,
            'queue_executes':0,'fence_signals':0,'fence_waits':0,'cases':{},'limits':reg['limitations']}
    def checkpoint():save(result_path,result)
    checkpoint()
    try:
        for c,command in zip(reg['cases'],schedule['commands']):
            folder=HERE/'evidence'/c['case'];check(freeze['files']);check(freeze['original_sources']);check(driver_freeze['files'])
            guard=run_guarded(command['args'],folder)
            if guard['child_pid'] is not None:result['GPU_child_jobs_launched']+=1
            result['cases'][c['case']]={'guard':guard};checkpoint()
            if guard['status']!='completed':raise RuntimeError('Owned-child guard did not complete: '+c['case'])
            log=(folder/'stdout.log').read_text()+(folder/'stderr.log').read_text()
            m=re.search(r'shader_dispatches=(\d+) queue_executes=(\d+) signals=(\d+) fence_waits=(\d+) validation_errors=(\d+) validation_warnings=(\d+) native_SDK_dispatches=(\d+)',log)
            assert m is not None,'actual completion counters';counts=list(map(int,m.groups()))
            assert counts[0]==c['shader_dispatches']and counts[6]==0
            assert counts[1]==counts[2]==counts[3]==c['expected_queue_executes_including_input_upload']
            assert' debug_layer=1 gpu_validation=0'in log
            result['GPU_child_jobs_completed']+=1;result['identity_shader_dispatches_completed']+=counts[0]
            result['queue_executes']+=counts[1];result['fence_signals']+=counts[2];result['fence_waits']+=counts[3]
            n=c['shader_dispatches'];actual=[]
            for i in range(n):
                data=(folder/f'out{i}.bin').read_bytes();assert len(data)==16;actual.append(list(struct.unpack('<4I',data)))
            assert(folder/'outputs.bin').read_bytes()==tuple_bytes(actual),'each raw readback concatenation'
            intended=c['intended'];expected=c['last_CPU_slot_contents_hypothesis']
            assert(folder/'constants.bin').read_bytes()==b''.join(struct.pack('<4I',r[0],r[2],0,0)for r in intended),'actual CPU constants bytes'
            assert(folder/'inputs.bin').read_bytes()==b''.join(struct.pack('<I',r[1])for r in intended),'actual serialized input values'
            trace=(folder/'recording_trace.txt').read_text();assert trace.count('dispatch=')==n
            if c['fence_before_reuse']:assert'completed_before_slot_reuse 3'in trace
            observed={'guard':guard,'completion_counts':{'shader_dispatches':counts[0],'queue_executes':counts[1],
                'signals':counts[2],'fence_waits':counts[3],'validation_errors':counts[4],'validation_warnings':counts[5],'native_SDK_dispatches':0},
                'actual':actual,'intended':intended,'last_CPU_slot_contents_hypothesis':expected,
                'all_match_intended':actual==intended,'all_match_last_slot_contents':actual==expected,
                'changed_dispatch_rows':[i for i,(a,b)in enumerate(zip(actual,intended))if a!=b],
                'changed_CB_rows':[i for i,(a,b)in enumerate(zip(actual,intended))if a[0]!=b[0]or a[2]!=b[2]],
                'changed_SRV_rows':[i for i,(a,b)in enumerate(zip(actual,intended))if a[1]!=b[1]],
                'all_magic_values_correct':all(a[3]==0xD1A60001 for a in actual),
                'payloads':[identity(p)for p in sorted(folder.iterdir())if p.is_file()]}
            result['cases'][c['case']]=observed;checkpoint()
            line=f"{c['case']} completed {n} shader dispatches; intended={observed['all_match_intended']} last-slot={observed['all_match_last_slot_contents']}"
            with(HERE/'gpu_driver_transcript.txt').open('a',encoding='utf-8',newline='\n')as f:f.write(line+'\n')
            print(line,flush=True)
        assert result['GPU_child_jobs_completed']==9 and result['identity_shader_dispatches_completed']==40
        assert result['queue_executes']==result['fence_signals']==result['fence_waits']==20
        check(freeze['files']);check(freeze['original_sources']);check(driver_freeze['files'])
        control_names=('safe_three','immutable_four','immutable_five','fenced_four','fenced_five')
        result['all_safe_controls_exact']=all(result['cases'][name]['all_match_intended']for name in control_names)
        result['all_cases_match_preregistered_last_slot_hypothesis']=all(c['all_match_last_slot_contents']for c in result['cases'].values())
        result['all_ordinary_debug_errors_warnings_zero']=all(c['completion_counts']['validation_errors']==c['completion_counts']['validation_warnings']==0 for c in result['cases'].values())
        result['changed_dispatch_rows_total']=sum(len(c['changed_dispatch_rows'])for c in result['cases'].values())
        result['changed_CB_rows_total']=sum(len(c['changed_CB_rows'])for c in result['cases'].values())
        result['changed_SRV_rows_total']=sum(len(c['changed_SRV_rows'])for c in result['cases'].values())
        result['sources_and_originals_unchanged']=True
        result['status']='completed_preregistered_GPU_fixture_not_game_causation';checkpoint()
        post_items=freeze['files']+freeze['original_sources']+driver_freeze['files']
        save(HERE/'post_gpu_freeze.json',{'schema':'compute-ring-post-GPU-source-identity-freeze-v1','all_unchanged':True,'files':post_items},True)
        compact={'schema':'compute-ring-GPU-fixture-compact-v1','report':identity(result_path),'registration':identity(HERE/'registration.json'),
            'GPU_jobs':9,'identity_shader_dispatches':40,'queue_executes':20,'signals':20,'fence_waits':20,
            'native_SDK_contexts':0,'native_SDK_dispatches':0,
            'all_safe_controls_exact':result['all_safe_controls_exact'],
            'all_last_slot_hypotheses_match':result['all_cases_match_preregistered_last_slot_hypothesis'],
            'ordinary_debug_errors_warnings_all_zero':result['all_ordinary_debug_errors_warnings_zero'],
            'changed_dispatch_rows_total':result['changed_dispatch_rows_total'],'changed_CB_rows_total':result['changed_CB_rows_total'],
            'changed_SRV_rows_total':result['changed_SRV_rows_total'],
            'cases':{name:{k:c[k]for k in('actual','changed_dispatch_rows','changed_CB_rows','changed_SRV_rows','all_match_intended','all_match_last_slot_contents')}for name,c in result['cases'].items()},
            'source_boundary':'Exact extracted ComputeState and original helper implementations; forced1.0 identity root signature differs from actual production embedded1.1 flags0 static descriptor defaults. Legal before-submit volatile aliases reveal per-dispatch identity errors, not a defined production1.1 violation outcome.',
            'limits':reg['limitations'],'quality_accepted':False}
        save(HERE/'compact.json',compact,True)
        files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
        save(HERE/'completion_manifest.json',{'schema':'immutable-compute-ring-GPU-fixture-completion-v1','status':result['status'],
            'GPU_child_jobs':9,'identity_shader_dispatches':40,'native_SDK_contexts':0,'native_SDK_dispatches':0,
            'quality_accepted':False,'files':[identity(p)for p in files]},True)
        print(json.dumps({'compact':identity(HERE/'compact.json'),'completion_manifest':identity(HERE/'completion_manifest.json')}),flush=True)
    except BaseException as e:
        result['status']='failed_preserved';result['error']=type(e).__name__+': '+str(e);checkpoint();raise
if __name__=='__main__':main()
