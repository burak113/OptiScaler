"""Bounded independent CPU prelaunch review of two single-graph helper repeats. No scores."""
from pathlib import Path
import ast,hashlib,importlib.util,json,shlex,struct,sys
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;PREP=HERE.parent/'fsrd_weak_material_clean_roundtrip_preparation_20260930'
COMP=HERE.parent/'fsrd_weak_material_clean_composition_preparation_20260930';CONV=HERE.parent/'fsrd_weak_material_clean_converter_preparation_20260930'
GATE=HERE.parent/'fsrd_weak_material_clean_composition_postrun_review_20260930'
FMT=[10,28,10,28,10,24,10,41,10,10,3];OFMT=[10,10,3];BPP={10:8,28:4,24:4,41:4,3:16}
def read(p):return json.loads(Path(p).read_text())
def ident(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def verify(r):
 a=ident(r['path']);assert(a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path'];return a
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def module(n,p):s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def rows(p):return[shlex.split(x)for x in Path(p).read_text().splitlines()]
def same(a,b):return Path(a).resolve()==Path(b).resolve()
def main():
 assert not(HERE/'review.json').exists(),'Preserve prior attempt'
 pins={'registration.json':'c0773b00053139dc75d537dc8db3c3d276175d82df799be8908d580a70f266a5','pre_execution_freeze.json':'722f90048bafeb8474edcd4584383c1bfa1ef674be170e66cc49e50c10f7779d',
 'readiness.json':'45b1a0caa029a662180d9d994b0c67df217d8e7242856cadde89111e4dccbb70','completion_manifest.json':'01311ce4b71da4577bb7548563876b0bdd37fa7d1e626065b41b34242bb3552d'}
 records={}
 for n,h in pins.items():assert ident(PREP/n)['sha256']==h;records[str(PREP/n)]=ident(PREP/n)
 for n,key in[('pre_execution_freeze.json','owned'),('completion_manifest.json','records')]:
  seal=read(PREP/n);assert seal['self_excluded']
  for r in seal[key]:
   assert not same(r['path'],PREP/n),'self record';a=verify(r);records[a['path']]=a
 freeze=read(PREP/'pre_execution_freeze.json')
 assert len(freeze['owned'])==78 and len(freeze['external_sources'])==2252
 for r in freeze['external_sources']:a=verify(r);records[a['path']]=a
 for r in read(HERE/'provisional_source_snapshot.json')['source_records']:verify(r)
 reg=read(PREP/'registration.json');proof=read(PREP/'graph_identity_proof.json');ready=read(PREP/'readiness.json')
 assert ready['blockers']==[] and len(reg['jobs'])==2 and [(j['frame'],j['arm'])for j in reg['jobs']]==[(0,'R0'),(0,'R1')]
 assert ident(GATE/'review.json')['sha256']=='57c97fbecce6711b4e46079a6d18ce354a54c4ea44795a69d3b6aaff27c2caab'
 assert ident(GATE/'completion_manifest.json')['sha256']=='a4236765a7de7b625d7317a8bf6112f8e69db2fb6bdf37c8a4df704b1461e6d8'
 assert read(GATE/'review.json')['status']=='PASSED_CLEAN_COMPOSITION_EVIDENCE_AND_EXACT_METRIC_REVIEW'
 oldreg=read(COMP/'registration.json');c0={j['frame']:j for j in oldreg['jobs']if j['arm']=='C0'}
 assert proof['unique_complete_graphs']==1 and len(proof['frames'])==64
 first=None;perframe=[]
 for f,frame in enumerate(proof['frames']):
  assert frame['source_frame']==f and len(frame['inputs'])==11
  cb=Path(frame['CB']['path']).read_bytes();assert cb==Path(c0[f]['CB']['path']).read_bytes()and len(cb)==96
  full=[cb]
  for s,(r,fmt)in enumerate(zip(frame['inputs'],FMT)):
   assert r['slot']==s and r['format']==fmt and r['width']==128 and r['height']==80
   data=Path(r['path']).read_bytes();assert len(data)==128*80*BPP[fmt]
   expected=CONV/'planned_jobs'/f'{f:02d}'/'clean'/('out0.bin'if s==0 else'out1.bin')if s in(0,2)else Path(c0[f]['inputs'][s]['path'])
   assert data==expected.read_bytes(),(f,s)
   full.append(data)
  if first is None:first=full
  assert full==first,(f,'not one full graph')
  for slot,halfbits in[(0,0),(2,31743)]:assert np.all(np.frombuffer(full[slot+1],'<u2').reshape(80,128,4)[...,3]==halfbits)
  # Preserve the differing destination nativeA, rather than silently repairing it.
  assert np.all(np.fromfile(c0[f]['inputs'][2]['path'],'<u2').reshape(80,128,4)[...,3]==0)
  perframe.append(dict(frame=f,CB11_fullbyte_equal=True,actual_converter_lobes_fullRGBA=True,specularA_u16=0,diffuseA_u16=31743,native_diffuseA_u16=0))
 assert struct.unpack_from('<I',first[0],16)[0]==8 and struct.unpack_from('<f',first[0],20)[0]==0
 assert struct.unpack_from('<I',first[0],52)[0]==struct.unpack_from('<I',first[0],64)[0]==0
 with np.load(reg['source_sequences']['path'])as z:
  truth=z['clean_reference'];assert truth.shape==(64,80,128,3)and all(truth[f].tobytes()==truth[0].tobytes()for f in range(64))
 jobchecks=[]
 for job in reg['jobs']:
  folder=Path(job['job']).parent;assert folder.is_dir()and {p.name for p in folder.iterdir()}=={'job.txt'}
  r=rows(job['job']);assert len(r)==15 and r[0][2:]==['128','80','11','3','1']
  assert same(r[0][0],PREP/'frozen_shader/FSRDOutputComp_Shader.cso')and same(r[0][1],PREP/'payloads/cb.bin')and Path(r[0][1]).read_bytes()==first[0]
  assert job['command']==[str(PREP/'fsrd_gpu_runner.exe'),job['job']]
  for s,(t,p,fmt)in enumerate(zip(r[1:12],job['inputs'],FMT)):
   assert t[1:]==['128','80',str(fmt)]and same(t[0],p['path'])and Path(t[0]).read_bytes()==first[s+1]
  for t,o,fmt in zip(r[12:],job['outputs'],OFMT):
   assert t[1:]==['128','80',str(fmt)]and same(t[0],o['path'])and o['bytes']==128*80*BPP[fmt]and not Path(o['path']).exists()
  for n in('resource_guard.json','stdout.log','stderr.log'):assert not(folder/n).exists()
  jobchecks.append(dict(arm=job['arm'],parent_exists_only_job=True,all3_outputs_and_guard_logs_absent=True,CB11inputs_same_class=True,repetition1=True))
 for n in('execution_results.json','roundtrip_metrics.json','roundtrip_sequences.npz','execution_TEMP'):assert not(PREP/n).exists()
 for n in('helper_work_accounting.py','helper_guard_evidence.py','native_resource_guard.py','fsrd_gpu_runner.exe','helper_source_reference.cpp'):
  assert(PREP/n).read_bytes()==(COMP/n).read_bytes()
 for n in('FSRDOutputComp_Shader.cso','FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):assert(PREP/'frozen_shader'/n).read_bytes()==(COMP/'frozen_shader'/n).read_bytes()
 for item in reg['metric_function_extraction']:assert Path(item['source']).read_bytes()==(COMP/'frozen_metric_sources'/Path(item['source']).name).read_bytes()
 hlsl=(PREP/'frozen_shader/FSRDOutputComp.hlsl').read_text()
 assert 'float3(InIndirectSpecular[p].rgb)'in hlsl and 'float3(InDirectDiffuse[p].rgb)'in hlsl
 assert 'if ((DetailPreservation <= 0.0f || RecoveryMask == 0) && !IsSet(FLAGS_DEBUG))'in hlsl and 'OutColor[p] = half4(Reconstruct(p), 1);'in hlsl
 helper=(PREP/'helper_source_reference.cpp').read_text();assert helper.count('cmd->Dispatch(')==1 and helper.index('WaitForSingleObject')<helper.index('gpu_ms_median=')<helper.index('validation_errors=')
 driver=(PREP/'run_roundtrip_only.py').read_text();assert driver.index('refuse_existing(reg)')<driver.index('from native_resource_guard import run_guarded')
 assert driver.index('save(target,report) # Actual physical work')<driver.index('if error:raise')<driver.index("if not work['metadata_accepted']")
 assert "HERE.resolve()in temp.parents"in driver and "Path(os.environ['TMP']).resolve()==temp==Path(os.environ['TEMP']).resolve()"in driver
 analyzer=(PREP/'analyze_roundtrip_cpu.py').read_text()
 assert 'colors[arm]=raw[arm][0][None,...,:3]'in analyzer and 'singleton_temporal_fields_noninferential=True'in analyzer
 assert analyzer.index('if all_exact:')<analyzer.index("reference=np.broadcast_to(colors['R0'],truth.shape)")
 assert 'No temporalstd result is computed over a duplicated R64 series.'in analyzer
 assert "reference_independent_temporal_samples=0"in analyzer
 # Replay exactly six already-created SIM fixtures; no new probes or scores.
 m=module('roundtrip_review_helper_law',PREP/'helper_work_accounting.py');g=module('roundtrip_review_guard',PREP/'helper_guard_evidence.py')
 checks=read(PREP/'CPU_checks.json');replays=[]
 yes=dict(status='completed',child_pid=123,returncode=0,terminated_owned_child=False);no=dict(status='not_launched_low_available_memory',child_pid=None,returncode=None)
 for t in checks['SIMULATED_helper_checks']:
  name=t['name'];folder=PREP/'SIMULATED_CPU'/name;returned={}if name=='fresh_missing_guard_marker_lowerbound'else no if name in('nochild_stale_marker_reject','stored_child_returned_nochild_canonical')else yes
  guard,error,artifact=g.load_guard_best_effort(folder,returned,None);out=[dict(path=str(folder/f'out{i}.bin'),bytes=4)for i in range(3)]
  work=m.accounting(folder,out,guard,error,fresh_scope_authenticated=True)
  assert t['passed']and guard==t['guard']and artifact==t['guard_artifact']and work==t['work']
  replays.append(dict(name=name,bitexact=True,work_lowerbound=work['confirmed_shader_dispatches_lower_bound'],exact_total=work['exact_shader_dispatch_total'],metadata_accepted=work['metadata_accepted']))
 for r in records.values():verify(r)
 result=dict(status='READY_FOR_ROOT_CLEAN_ROUNDTRIP_AUTHORIZATION',blocking_findings=[],producer_pins={n:ident(PREP/n)for n in pins},
  source_records_checked_pre_post=len(records),source_records=list(records.values()),provisional11_sourcepins_unchanged=True,
  graph=dict(all64_full11SRV_CB_one_byteidentical_class=True,frames=perframe,CB96_original=True,formats=FMT,outputs=OFMT,rawtruth64byteidentical=True,
  exact_substitution='Only t0 actual cleanconverterout0 specular and t2 out1 diffuse replace native lobes of cleancomposition C0 graph; other9SRV+CB exact.',
  alpha='SpecularA0/diffuseA65504 actual format10 fullRGBA unchanged; native destinationdiffuseA0 is deliberately different.'),
  runtime=dict(two_parents_ready=True,all6outputs_and6guard_logs_absent=True,globalresults_metrics_NPZ_TEMP_absent=True,jobs=jobchecks),
  accounting=dict(parser_canonicalguard_resourceguard_mature_byteexact=True,EXE_source_read_byteexact=True,physical_checkpoint_before_metadata=True,six_inherited_SIM_bitexact=replays,postfence_marker_sourcequalified=True,no_SDK_calls=True),
  analysis=dict(two_N1_scores_only=True,all3_repeat_bits_gates_static_reference=True,static_R64_broadcast_not_64measured_observations=True,no_R64_temporal_variance_inference=True,frozen_metric_sources_byteexact_not_executed=True,oldB_fourwindow_check_reused_priorreview=True,
  directional='R-q converter+composition versus encodedraw; T-R extra SDK/context/destinationAlpha pathway plus downstream composition. Not pure intrinsic SDK error.'),
  planned_only=dict(helpers=2,explicit_helper_shader_dispatches=2,outputs=6,native_API=0,graph_classes=1),actual_review=dict(GPU=0,native=0,build=0,devicequery=0,scores=0),
  provenance_qualification='HistoricalCSO/EXE and source identities/past observed replay pinned. Source fastpath RGB-only branch supports alpha-unused interpretation; no separate actualCSO alpha-dataflow disassembly or empirical alpha-insensitivity control establishes that property. Do not assert pure SDK-only RGB cause.',
  history_qualification='Flags8 notrawblit,detail0/writehistory0 source branch writesColorA1 and leaves auxiliaryUAVs unwritten; retainedauxbytes are a repeatcontrol, not semantic history.',
  limitations=reg['limitations'],quality_accepted=False)
 save('review.json',result)
 save('compact.json',dict(status=result['status'],blocking_findings=[],review=ident(HERE/'review.json'),source_records=len(records),graph_classes=1,source_frames_authenticated=64,planned_only=result['planned_only'],actual_review=result['actual_review'],runtime=result['runtime'],provenance_qualification=result['provenance_qualification'],quality_accepted=False))
 for r in records.values():verify(r)
 files=[ident(p)for p in sorted(HERE.iterdir())if p.is_file()]
 save('completion_manifest.json',dict(status='SEALED_READY_FOR_ROOT_CLEAN_ROUNDTRIP_AUTHORIZATION',files=files,external_sources=list(records.values()),self_entry_excluded=True,actual_GPU_native_build_scores=0))
 print(json.dumps(dict(status=result['status'],sources=len(records),review=ident(HERE/'review.json'),compact=ident(HERE/'compact.json'),manifest=ident(HERE/'completion_manifest.json'))))
if __name__=='__main__':main()
