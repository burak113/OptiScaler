from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, re, struct

P=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/tools_tmp/fsrd_compute_ring_deferred_gpu_20260930')
OUT=Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):
    p=Path(p); return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def load(p): return json.loads(Path(p).read_text())
def save(name,v):
    with (OUT/name).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def check(items):
    for item in items: assert identity(item['path'])==item,item['path']

reg=load(P/'registration.json'); report=load(P/'evidence/results.json')
source=load(OUT/'source_review.json')
assert report['status']=='completed_preregistered_GPU_fixture_not_game_causation'
source_names=['registration.json','pre_gpu_freeze.json','driver_pre_gpu_freeze.json','run_schedule_registration.json','post_gpu_freeze.json','completion_manifest.json']
pre_pins=[identity(P/n) for n in source_names]
manifest=load(P/'completion_manifest.json');check(manifest['files'])
freeze=load(P/'pre_gpu_freeze.json');check(freeze['files']);check(freeze['original_sources'])
driver=load(P/'driver_pre_gpu_freeze.json');check(driver['files'])
post=load(P/'post_gpu_freeze.json');check(post['files']);assert post['all_unchanged']
schedule=load(P/'run_schedule_registration.json')
assert len(schedule['commands'])==9 and schedule['GPU_jobs_already_run']==0
assert schedule['shader_dispatches_already_run']==schedule['native_SDK_dispatches_already_run']==0
assert schedule['driver']==identity(P/'run_gpu.py')
predictions={c['case']:c['independent_last_write_prediction'] for c in source['case_predictions']}
rows=[];total=0;executes=0;changed_all=0;changed_cb=0;changed_srv=0;peak=0;minimum_free=[]
source_sha_start={item['path']:item['sha256'] for item in freeze['files']+freeze['original_sources']}
for c,cmd in zip(reg['cases'],schedule['commands']):
    name=c['case'];folder=P/'evidence'/name;n=c['shader_dispatches'];got=report['cases'][name]
    guard=load(folder/'resource_guard.json')
    assert guard==got['guard'] and guard['args']==cmd['args']
    assert guard['status']=='completed' and guard['returncode']==0 and guard['child_pid'] is not None
    assert not guard['terminated_owned_child'] and guard['termination_reason'] is None
    assert guard['timeout_seconds']==240 and guard['maximum_working_set_bytes']==2**31 and guard['minimum_available_memory_bytes']==2**30
    assert cmd['job']==identity(folder/'job.txt')
    log=(folder/'stdout.log').read_text();stderr=(folder/'stderr.log').read_bytes()
    assert not stderr
    assert 'adapter=AMD Radeon RX 9070' in log and 'debug_layer=1 gpu_validation=0' in log
    m=re.findall(r'shader_dispatches=(\d+) queue_executes=(\d+) signals=(\d+) fence_waits=(\d+) validation_errors=(\d+) validation_warnings=(\d+) native_SDK_dispatches=(\d+)',log)
    assert len(m)==1;counts=list(map(int,m[0]))
    expected_exec=3 if c['fence_before_reuse'] else 2
    assert counts==[n,expected_exec,expected_exec,expected_exec,0,0,0]
    assert not (folder/'debug_messages.txt').read_bytes()
    actual=[list(struct.unpack('<4I',(folder/f'out{i}.bin').read_bytes())) for i in range(n)]
    raw=b''.join((folder/f'out{i}.bin').read_bytes() for i in range(n))
    assert raw==(folder/'outputs.bin').read_bytes()
    assert actual==got['actual']==predictions[name]
    intended=[[100+i,5000+i,200+i,0xD1A60001] for i in range(n)]
    assert (folder/'constants.bin').read_bytes()==b''.join(struct.pack('<4I',100+i,200+i,0,0) for i in range(n))
    assert (folder/'inputs.bin').read_bytes()==b''.join(struct.pack('<I',5000+i) for i in range(n))
    trace=(folder/'recording_trace.txt').read_text()
    recorded=re.findall(r'dispatch=(\d+) cbSlot=(\d+) descriptorSlot=(\d+) cbValue=(\d+) cbTag=(\d+) input=(\d+) readback=(\d+)',trace)
    assert [[int(x) for x in r] for r in recorded]==[[i,i%c['cb_slots'],i%c['descriptor_slots'],100+i,200+i,5000+i,i] for i in range(n)]
    assert ('completed_before_slot_reuse 3' in trace)==c['fence_before_reuse']
    assert f'completed_final fence={expected_exec}' in trace
    observed=re.findall(r'observation=(\d+) cb=(\d+) srv=(\d+) cbTag=(\d+) magic=(\d+)',log)
    assert [[int(x) for x in r] for r in observed]==[[i,*actual[i]] for i in range(n)]
    changed=[i for i in range(n) if actual[i]!=intended[i]]
    cbc=[i for i in range(n) if actual[i][0]!=intended[i][0] or actual[i][2]!=intended[i][2]]
    srvc=[i for i in range(n) if actual[i][1]!=intended[i][1]]
    assert changed==got['changed_dispatch_rows'] and cbc==got['changed_CB_rows'] and srvc==got['changed_SRV_rows']
    check(got['payloads'])
    rows.append({'case':name,'actual':actual,'all_intended':not changed,'changed_dispatch_rows':changed,
                 'changed_CB_rows':cbc,'changed_SRV_rows':srvc,'integer_alias_prediction_exact':True,
                 'queue_executes_signals_waits_each':expected_exec,'errors':0,'warnings':0,
                 'raw_output':identity(folder/'outputs.bin'),'guard':identity(folder/'resource_guard.json')})
    total+=n;executes+=expected_exec;changed_all+=len(changed);changed_cb+=len(cbc);changed_srv+=len(srvc)
    peak=max(peak,guard['peak_observed_working_set_bytes']);minimum_free.append(guard['minimum_observed_available_bytes'])
assert total==40 and executes==20
assert report['GPU_child_jobs_launched']==report['GPU_child_jobs_completed']==9
assert report['identity_shader_dispatches_completed']==total
assert report['queue_executes']==report['fence_signals']==report['fence_waits']==executes
assert report['native_SDK_contexts']==report['native_SDK_dispatches']==0
assert report['changed_dispatch_rows_total']==changed_all
assert report['changed_CB_rows_total']==changed_cb and report['changed_SRV_rows_total']==changed_srv
assert not report['quality_accepted'] and not report['game_run']
check(freeze['files']);check(freeze['original_sources']);assert pre_pins==[identity(P/n) for n in source_names]
audit={'schema':'independent-compute-ring-actual-GPU-audit-v1','utc':datetime.now(timezone.utc).isoformat(),
 'status':'completed_independent_fixture_audit_not_game_causation','source_review':identity(OUT/'source_review.json'),
 'producer_report':identity(P/'evidence/results.json'),'producer_completion_manifest':identity(P/'completion_manifest.json'),
 'completion_manifest_entries_verified':len(manifest['files']),
 'source_pre_post_unchanged':True,'GPU_child_jobs':9,'shader_dispatches':40,'native_contexts':0,'native_dispatches':0,
 'queue_executes':20,'signals':20,'fence_waits':20,'ordinary_debug_errors':0,'ordinary_debug_warnings':0,
 'all_five_safe_controls_exact':all(r['all_intended'] for r in rows if r['case'] in ['safe_three','immutable_four','immutable_five','fenced_four','fenced_five']),
 'all_nine_integer_alias_predictions_exact':True,'changed_dispatch_rows':changed_all,'changed_CB_rows':changed_cb,'changed_SRV_rows':changed_srv,
 'peak_child_observed_working_set_bytes':peak,'minimum_sampled_available_memory_bytes':min(minimum_free),
 'cases':rows,
 'findings':[
  'Reused three-slot recording aliases earlier CB and SRV contents in the forced1.0 controlled fixture. CB-only and descriptor-only five-dispatch controls isolate the two channels, respectively.',
  'Distinct per-dispatch GPU readback copies preserve intermediate shader outputs; the result is not merely a final shared-UAV overwrite observation.',
  'Sufficient slots and completion before reuse preserve intended values. Every input upload is completed before test recording and every readback is mapped after its final completion fence.'
 ],
 'qualifications':source['adaptation_boundaries']+[
  'Actual production embedded1.1/flags0 static-descriptor semantics differ; game completion depth and caller fencing remain separate evidence requirements. This cannot establish a stain/wave cause or accepted production fix.',
  'Preliminary source findings preceded completion; final exact-parser/source artifact was sealed afterward, before this independent result acceptance. No prelaunch final approval is claimed.',
  'Zero ordinary debug messages is not GPU-based-validation coverage. Shader-only40 dispatches do not increment native RR totals.'
 ],
 'quality_accepted':False,'actual_game_trigger_proven':False,'own_GPU_native_build_calls':0,
 'source_pins_pre_and_post':pre_pins,
 'preexisting_failures_preserved':{'MSVC_include_attempt':(P/'build_attempt1').is_dir(),'raw_RTS0_deserializer_attempt':(P/'build_attempt2').is_dir()}
}
save('audit.json',audit)
save('completion_manifest.json',{'schema':'independent-ring-fixture-audit-completion-v1','status':audit['status'],
     'files':[identity(p) for p in sorted(OUT.iterdir()) if p.is_file()], 'own_GPU_native_build_calls':0})
print(json.dumps({'audit':identity(OUT/'audit.json'),'completion_manifest':identity(OUT/'completion_manifest.json'),
 'changed_dispatch_rows':changed_all,'changed_CB_rows':changed_cb,'changed_SRV_rows':changed_srv}))
