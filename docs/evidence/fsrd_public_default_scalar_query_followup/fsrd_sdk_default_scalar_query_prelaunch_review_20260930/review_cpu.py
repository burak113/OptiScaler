"""Read-only fixed-probe prelaunch review. No SDK/probe/guard launcher imports."""
from pathlib import Path
import ast, hashlib, json, shutil, subprocess, sys
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PRODUCER = ROOT/'tools_tmp/fsrd_sdk_default_scalar_query_preparation_20260930'
PINS = {
 'registration.json':'395b85ba6b02456d253a5ba57bd2d525141bd2c0c693a87df96506e20bf47ab6',
 'pre_query_freeze.json':'5ddeb8978550a316dc858e7ac9f0807f2f5bb9ea934e952c8e58eb3b6bba7aae',
 'readiness.json':'d024a4520e73bf53840bbffd373c9dc3c8c5ba705db90ee1e11c495ba334b262',
 'completion_manifest.json':'8606b76754f334665026d41c6815d3609de019808dc3961b0ec72c47d60e5f5d',
}
def rec(p):
 p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate JSON key '+k)
  d[k]=v
 return d
def read(p):return json.loads(Path(p).read_bytes(),object_pairs_hook=unique)
def save(n,v):
 with (HERE/n).open('x',encoding='utf-8',newline='\n') as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def verify(rows):
 for r in rows:assert rec(r['path'])==r,r['path']
def main():
 for n,s in PINS.items():assert rec(PRODUCER/n)['sha256']==s,n
 reg=read(PRODUCER/'registration.json');freeze=read(PRODUCER/'pre_query_freeze.json');manifest=read(PRODUCER/'completion_manifest.json')
 rows=manifest['owned']+manifest['external_sources'];assert len({r['path'] for r in rows})==len(rows)
 assert all(Path(r['path'])!=PRODUCER/'completion_manifest.json' for r in rows)
 verify(rows);verify(freeze['owned']+freeze['external_sources'])
 assert manifest['self_entry_excluded'] and freeze['self_entry_excluded']
 for n in PINS:assert n=='completion_manifest.json' or str((PRODUCER/n).resolve()) in {r['path'] for r in rows}
 before=[rec(r['path']) for r in rows]+[rec(PRODUCER/'completion_manifest.json')]
 save('pins_before.json',dict(records=before,manifest_owned_count=len(manifest['owned']),manifest_external_count=len(manifest['external_sources']),freeze_owned_count=len(freeze['owned']),freeze_external_count=len(freeze['external_sources'])))
 source=(PRODUCER/'fsrd_default_query.cpp').read_text()
 assert reg['EXE']['sha256']=='cb1db4d103665c49d1e956222d69b9c407903d2290e25928593d2e95bb259b27' and reg['EXE']['bytes']==307200
 assert reg['source']['sha256']=='68c4b30fd9d2a9805a235cc45996f60461217bc2e677e287a62bfbabafaa36e5'
 assert reg['query_keys']==[6,1,2,3,4,5]
 for fn in ('CreateContext','Query','DestroyContext'):assert source.count('api.'+fn+'(')==1
 forbidden=('api.Configure(','api.Dispatch(','CreateCommandQueue(','CreateCommandList(','CreateCommandAllocator(','CreateCommittedResource(','CreatePlacedResource(','CreateFence(','ExecuteCommandLists(','SetEventOnCompletion(','WaitForSingleObject(')
 assert all(t not in source for t in forbidden)
 for t in ('FFX_DENOISER_VERSION,{128,80},FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR','0,FFX_DENOISER_ENABLE_VALIDATION','DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE','D3D_FEATURE_LEVEL_12_0','Keys[i],1,&values[i]','if(!live||s.de)return;','try{s.event("destroy_start");}catch','if(s.ambiguous||(live&&!s.destroyed))','ExitProcess(1);'):assert t in source,t
 assert source.index('ffxCreateBackendDX12Desc backend')<source.index('try {\n  s.event("boot")')
 assert source.index('ExitProcess(1);')<source.index('if(module)FreeLibrary(module);')
 headers={Path(r['path']).name:Path(r['path']) for r in manifest['external_sources']}
 den=headers['ffx_denoiser.h'].read_text()
 for name,value in [('CROSS_BILATERAL_NORMAL_STRENGTH',1),('STABILITY_BIAS',2),('MAX_RADIANCE',3),('RADIANCE_CLIP_STD_K',4),('GAUSSIAN_KERNEL_RELAXATION',5),('DISOCCLUSION_THRESHOLD',6)]:
  import re
  assert re.search(r'FFX_API_CONFIGURE_DENOISER_KEY_'+name+r'\s*=\s*'+str(value)+r'\s*,',den)
 assert 'uint64_t count;' in den and 'void* data;' in den and 'Required to be passed to @c ffxQuery with a non-nullptr denoiser' in den
 assert reg['design']['sha256']=='bb80daa56058ef57f7be03d37ef217acaaca8f4ad285b5bee4cad1ddf3f372e6'
 assert (PRODUCER/'planned_query/job.txt').read_text().strip()=='"'+reg['provider']['path'].replace('\\','/')+'"'
 assert reg['provider']['sha256']=='48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
 signature=read(PRODUCER/'provider_signature.json');assert signature['Status']=='Valid' and signature['MetadataOnlyNoSDKLoaded']
 build=read(PRODUCER/'build_result.json');assert build['actual_compile_invocations']==1 and build['query_EXE_invocations']==0 and build['passed']
 g=build['guard'];assert g['status']=='completed' and g['returncode']==0 and type(g['child_pid'])is int and g['child_pid']>0 and not g['terminated_owned_child']
 assert (PRODUCER/'compile_runtime/stdout.log').read_bytes()==b'fsrd_default_query.cpp\r\n'
 assert (PRODUCER/'compile_runtime/stderr.log').read_bytes()==b''
 assert rec(PRODUCER/'native_resource_guard.py')['sha256']=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
 assert reg['guard']['timeout_seconds']==240 and reg['guard']['maximum_working_set_bytes']==2147483648 and reg['guard']['minimum_available_memory_bytes']==1073741824 and reg['guard']['interval_seconds']==.2
 loader_prior=next(r for r in manifest['external_sources'] if Path(r['path']).name=='executor_evidence.py')
 assert (PRODUCER/'executor_evidence.py').read_bytes()==Path(loader_prior['path']).read_bytes()
 driver=(PRODUCER/'run_query.py').read_text();ast.parse(driver)
 assert driver.index('work=derive(folder,guard)')<driver.index("assert not guard['guard_load_evidence']['errors']and work['accepted']")
 assert driver.index("status='physical_work_checkpointed_before_acceptance'")<driver.index("assert not guard['guard_load_evidence']['errors']and work['accepted']")
 assert 'READY_FOR_ROOT_PUBLIC_DEFAULT_SCALAR_QUERY_AUTHORIZATION' in driver and 'ROOT_AUTHORIZED_ONE_DEFAULT_SCALAR_QUERY_CONTEXT' in driver
 assert "os.environ['TEMP']=str(temp);os.environ['TMP']=str(temp)" in driver
 runtime=[dict(path=p,absent=not Path(p).exists()) for p in reg['runtime_paths']]
 assert all(r['absent'] for r in runtime)
 assert sorted(p.name for p in (PRODUCER/'planned_query').iterdir())==['job.txt']
 assert not any((PRODUCER/'execution_TEMP').iterdir())
 # Exact check scripts are replayed only against copies in our owned folder.
 replay=HERE/'SIMULATED_REPLAY';replay.mkdir()
 copies=('check_query_cpu.py','check_pending_entry_cpu.py','query_accounting.py','executor_evidence.py','fsrd_default_query.cpp')
 for n in copies:
  shutil.copyfile(PRODUCER/n,replay/n);assert rec(replay/n)['sha256']==rec(PRODUCER/n)['sha256']
 commands=[]
 for n in copies[:2]:
  command=[sys.executable,'-B',str(replay/n)];r=subprocess.run(command,cwd=replay,capture_output=True)
  (HERE/(n+'.stdout.bin')).write_bytes(r.stdout);(HERE/(n+'.stderr.bin')).write_bytes(r.stderr)
  commands.append(dict(command=command,exit_code=r.returncode,stdout_bytes=len(r.stdout),stderr_bytes=len(r.stderr),no_probe_invoked=True));assert r.returncode==0,(n,r.stderr)
 cpu=read(replay/'CPU_checks.json');assert cpu['passed']==11 and cpu['failed']==0
 pending=read(replay/'CPU_pending_entry_check.json');assert pending['passed']
 original=read(PRODUCER/'CPU_checks.json')
 for actual,old in zip(cpu['SIMULATED_checks'],original['SIMULATED_checks']):
  assert actual['name']==old['name'] and actual['passed']==old['passed']
  assert {k:v for k,v in actual['result'].items() if k!='artifacts'}=={k:v for k,v in old['result'].items() if k!='artifacts'}
 save('replay_checks.json',dict(status='PASSED_EXACT_FIXED_PROBE_CPU_REPLAY',SIMULATED=True,completed_checks=12,commands=commands,actual_SDK_queries=0,actual_native_RR=0,actual_GPU_jobs=0,actual_builds=0,actual_scores=0))
 verify(before)
 after=[rec(r['path']) for r in before];assert before==after
 save('pins_after.json',dict(records=after,all_before_after_byte_exact=True,runtime_absence=runtime,owned_F_TEMP_empty=True))
 save('source_checks.json',dict(status='PASSED_BOUNDED_SOURCE_AND_SEALED_BYTE_REVIEW',producer_manifest_owned=len(manifest['owned']),producer_manifest_external=len(manifest['external_sources']),producer_freeze_owned=len(freeze['owned']),producer_freeze_external=len(freeze['external_sources']),source=reg['source'],EXE=reg['EXE'],provider=reg['provider'],API=4202496,dimensions=[128,80],signals=34,checkerboard=0,validation=2,query_keys=reg['query_keys'],query_count_per_key=1,source_API_sites=dict(Create=1,Query=1,query_loop_maximum=6,Destroy=1,Configure=0,RR=0,caller_Execute=0),runtime_absent=True,source_before_after_exact=True,actual_review_CPU_compiles=0,actual_review_queries=0))
 print(json.dumps(dict(status='CPU_REVIEW_CHECKS_PASSED',manifest_owned=len(manifest['owned']),manifest_external=len(manifest['external_sources']),freeze_owned=len(freeze['owned']),freeze_external=len(freeze['external_sources']),CPU_SIMULATED=12,actual_queries=0)))
if __name__=='__main__':main()
