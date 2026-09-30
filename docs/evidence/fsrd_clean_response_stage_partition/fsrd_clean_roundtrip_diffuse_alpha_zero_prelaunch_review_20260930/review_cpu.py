"""Independent CPU prelaunch review: one actual diffuse-alpha field control, zero scores."""
from pathlib import Path
import hashlib,importlib.util,itertools,json,shlex,sys
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;PREP=HERE.parent/'fsrd_clean_roundtrip_diffuse_alpha_zero_preparation_20260930';OLD=HERE.parent/'fsrd_weak_material_clean_roundtrip_preparation_20260930';GATE=HERE.parent/'fsrd_weak_material_clean_roundtrip_postrun_review_20260930'
FMT=[10,28,10,28,10,24,10,41,10,10,3];OFMT=[10,10,3]
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
def main():
 assert not(HERE/'review.json').exists(),'Preserve prior attempt'
 pins={'registration.json':'a8be39dd76218594e890c73aa9cd04343a49e0b2a4b81a052c48514f6cb4eb0b','pre_execution_freeze.json':'757075d9715495446d7f8a5b28349098de918a87244c7499ef6c99f78dacb950',
 'readiness.json':'1eab6425998c218391ce2442322e23f9120e03bb6fce3f36d78ec7b2958726c0','completion_manifest.json':'143bcea870991f0ed49fa2eae4331cdc281f920b2f1db0ba40a8164bed1b20a8'}
 direct={}
 for n,h in pins.items():assert ident(PREP/n)['sha256']==h;direct[str(PREP/n)]=ident(PREP/n)
 for n,key in[('completion_manifest.json','records'),('pre_execution_freeze.json','owned')]:
  seal=read(PREP/n);assert seal['self_excluded']
  for r in seal[key]:
   assert Path(r['path']).resolve()!=(PREP/n).resolve();a=verify(r);direct[a['path']]=a
 frozen=read(PREP/'pre_execution_freeze.json');assert len(frozen['owned'])==72 and len(frozen['external_sources'])==41
 for r in frozen['external_sources']:a=verify(r);direct[a['path']]=a
 source=read(PREP/'source_manifest.json');anchor=source['inherited_source_manifest'];verify(anchor)
 assert anchor==frozen['inherited_full2252_source_manifest_pinned_once']
 expanded=read(anchor['path'])['records'];assert len(expanded)==2252
 for r in expanded:verify(r)
 reg=read(PREP/'registration.json');assert len(reg['jobs'])==2 and [(j['frame'],j['arm'])for j in reg['jobs']]==[(0,'RZ0'),(0,'RZ1')]
 assert read(PREP/'readiness.json')['blockers']==[]
 assert ident(GATE/'review.json')['sha256']=='781527903c10be0e17291a766c07db040d564b23b70aeeeded766f74d62bc97d'
 assert ident(GATE/'completion_manifest.json')['sha256']=='200230c6abf03940cc2d4ee0c784503fbcbc41c93378386eebb0ecdc2dbb09fc'
 assert read(GATE/'review.json')['status']=='PASSED_CLEAN_ROUNDTRIP_EVIDENCE_AND_EXACT_SINGLETON_METRIC_REVIEW'
 for key in('review','seal','root_tool_observations'):
  r=reg['prior_roundtrip_independent_postreview'][key];a=verify(r);direct[a['path']]=a
 orig=(OLD/'payloads/in2.bin').read_bytes();changed=(PREP/'payloads/in2.bin').read_bytes()
 a=np.frombuffer(orig,'<u2').reshape(80,128,4);b=np.frombuffer(changed,'<u2').reshape(80,128,4)
 assert np.all(a[...,3]==0x7bff)and np.all(b[...,3]==0)and a[...,:3].tobytes()==b[...,:3].tobytes()
 assert np.count_nonzero(a!=b)==10240 and np.count_nonzero(np.frombuffer(orig,'u1')!=np.frombuffer(changed,'u1'))==20480
 for i in range(11):
  if i!=2:assert(PREP/f'payloads/in{i}.bin').read_bytes()==(OLD/f'payloads/in{i}.bin').read_bytes()
 assert(PREP/'payloads/cb.bin').read_bytes()==(OLD/'payloads/cb.bin').read_bytes()
 assert np.all(np.fromfile(PREP/'payloads/in0.bin','<u2').reshape(80,128,4)[...,3]==0)
 for n in('helper_work_accounting.py','helper_guard_evidence.py','native_resource_guard.py','fsrd_gpu_runner.exe','helper_source_reference.cpp','historical_gpu_runner.build.cmd'):assert(PREP/n).read_bytes()==(OLD/n).read_bytes()
 for n in('FSRDOutputComp_Shader.cso','FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):assert(PREP/'frozen_shader'/n).read_bytes()==(OLD/'frozen_shader'/n).read_bytes()
 jobs=[]
 for j in reg['jobs']:
  folder=Path(j['job']).parent;assert folder.is_dir()and {p.name for p in folder.iterdir()}=={'job.txt'}
  rows=[shlex.split(x)for x in Path(j['job']).read_text().splitlines()];assert len(rows)==15 and rows[0][2:]==['128','80','11','3','1']
  assert Path(rows[0][0]).resolve()==(PREP/'frozen_shader/FSRDOutputComp_Shader.cso').resolve()and Path(rows[0][1]).read_bytes()==(OLD/'payloads/cb.bin').read_bytes()
  assert j['command']==[str(PREP/'fsrd_gpu_runner.exe'),j['job']]
  for i,(t,fmt)in enumerate(zip(rows[1:12],FMT)):assert t[1:]==['128','80',str(fmt)]and Path(t[0]).read_bytes()==(PREP/f'payloads/in{i}.bin').read_bytes()
  for t,o,fmt in zip(rows[12:],j['outputs'],OFMT):assert t[1:]==['128','80',str(fmt)]and Path(t[0]).resolve()==Path(o['path']).resolve()and not Path(o['path']).exists()
  for n in('resource_guard.json','stdout.log','stderr.log'):assert not(folder/n).exists()
  jobs.append(dict(arm=j['arm'],same_graph1=True,parent_exists_only_job=True,all3output_guard_logs_absent=True))
 for n in('execution_TEMP','execution_results.json','alpha_zero_comparison.json'):assert not(PREP/n).exists()
 for j in reg['prior_R_outputs']:
  for o in j['outputs']:verify(o)
 driver=(PREP/'run_alpha_zero_only.py').read_text();assert driver.index('refuse_existing(reg)')<driver.index('from native_resource_guard import run_guarded')
 assert driver.index('save(target,report) # Actual physical work')<driver.index('if error:raise')<driver.index("if not work['metadata_accepted']")
 assert "assert reg['prior_roundtrip_independent_postreview']['passed_at_freeze'] is True"in driver
 assert "HERE.resolve()in temp.parents"in driver and "Path(os.environ['TMP']).resolve()==temp==Path(os.environ['TEMP']).resolve()"in driver
 analyzer=(PREP/'analyze_alpha_zero_bits_cpu.py').read_text()
 assert "itertools.combinations(('RZ0','RZ1','R0','R1'),2)"in analyzer and 'np.array_equal'in analyzer
 assert 'np.broadcast_to'not in analyzer and 'score('not in analyzer
 m=module('RZ_review_law',PREP/'helper_work_accounting.py');g=module('RZ_review_guard',PREP/'helper_guard_evidence.py')
 yes=dict(status='completed',child_pid=123,returncode=0,terminated_owned_child=False);no=dict(status='not_launched_low_available_memory',child_pid=None,returncode=None);sim=[]
 for t in read(PREP/'CPU_checks.json')['SIMULATED_helper_checks']:
  name=t['name'];returned={}if name=='fresh_missing_guard_marker_lowerbound'else no if name in('nochild_stale_marker_reject','stored_child_returned_nochild_canonical')else yes
  folder=PREP/'SIMULATED_CPU'/name;guard,error,artifact=g.load_guard_best_effort(folder,returned,None)
  outs=[dict(path=str(folder/f'out{i}.bin'),bytes=4)for i in range(3)];work=m.accounting(folder,outs,guard,error,fresh_scope_authenticated=True)
  assert t['passed']and guard==t['guard']and artifact==t['guard_artifact']and work==t['work']
  sim.append(dict(name=name,bitexact=True,dispatch_lowerbound=work['confirmed_shader_dispatches_lower_bound'],exact_total=work['exact_shader_dispatch_total'],metadata_accepted=work['metadata_accepted']))
 inherited_ref=dict(**anchor,records_key='records',record_count=2252)
 for r in list(direct.values())+expanded:verify(r)
 allunique={r['path']for r in list(direct.values())+expanded}
 report=dict(status='READY_FOR_ROOT_DIFFUSE_ALPHA_ZERO_AUTHORIZATION',blocking_findings=[],producer_pins={n:ident(PREP/n)for n in pins},direct_records_checked_pre_post=len(direct),inherited_records_checked_pre_post=2252,expanded_unique_records=len(allunique),inherited_source_manifest=inherited_ref,
  exact_change=dict(slot='t2 diffuse alpha only',format=10,old_u16=31743,new_u16=0,changed_halfwords=10240,changed_bytes=20480,RGB_bits_unchanged=True,other10_fullfields_unchanged=True,CB96_unchanged=True,specularA0_unchanged=True),
  copies=dict(historicalEXE_CSO_source_mature_parser_directguard_resourceguard_byteexact=True),runtime=dict(jobs=jobs,all6outputs_and6logs_absent=True,results_TEMP_absent=True),
  accounting=dict(physical_checkpoint_before_acceptance=True,canonical_returned_guard=True,nochild0_stale_claims_rejected=True,fresh_missing_guard_partial_marker_qualified=True,six_inherited_existing_SIM_replays=sim),
  analysis=dict(six_unordered_pairs=[list(x)for x in itertools.combinations(('RZ0','RZ1','R0','R1'),2)],fullRGBA_RGB_alpha_bits_only=True,prior_R0_R1_raw_outputs_pinned=True,no_score_or_R64_temporal_fields=True),
  planned_only=dict(helper_children=2,explicit_helper_shader_dispatches=2,outputs=6,SDK_API=0),actual_review=dict(GPU=0,native=0,build=0,devicequery=0,scores=0),quality_accepted=False,
  qualification=['Prelaunch only. Whether this actual historical CSO changes color RGB when t2A becomes0 is an unmeasured hypothesis; future output comparison closes that question for this graph only.',
  'Source/CSO/EXE pinned; no fresh compilation equivalence claim. Same actual converterRGB and fixedCB8/detail0/history0 retained.',
  'Auxiliary UAV repeatbytes are retained, but WriteHistory0 source fastpath may not write them; colorRGB effect must be separated from auxiliary semantics.',
  'Only two fresh helper observations with zero SDK calls. No temporal independence, game cause, native alpha preservation, quality or universal SDK conclusion.'])
 save('review.json',report)
 save('compact.json',dict(status=report['status'],blocking_findings=[],review=ident(HERE/'review.json'),direct_records=len(direct),inherited_records=2252,expanded_unique_records=len(allunique),inherited_source_manifest=inherited_ref,change=report['exact_change'],runtime=report['runtime'],planned_only=report['planned_only'],actual_review=report['actual_review'],quality_accepted=False))
 for r in list(direct.values())+expanded:verify(r)
 files=[ident(p)for p in sorted(HERE.iterdir())if p.is_file()]
 save('completion_manifest.json',dict(status='SEALED_READY_FOR_ROOT_DIFFUSE_ALPHA_ZERO_AUTHORIZATION',files=files,external_sources=list(direct.values()),inherited_source_manifests=[inherited_ref],expanded_unique_record_count=len(allunique),self_entry_excluded=True,actual_GPU_native_build_scores=0))
 print(json.dumps(dict(status=report['status'],direct=len(direct),inherited=2252,expanded_unique=len(allunique),review=ident(HERE/'review.json'),compact=ident(HERE/'compact.json'),manifest=ident(HERE/'completion_manifest.json'))))
if __name__=='__main__':main()
