"""Independent prelaunch three-trace composition graph and analyzer-V2 review."""
from pathlib import Path
import ast,hashlib,importlib.util,json,shlex,sys,types
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
PREP=BASE/'fsrd_clean_specular_hit_alpha_composition_preparation_20260930'
OLD=BASE/'fsrd_weak_material_clean_composition_preparation_20260930'
NATIVE=BASE/'fsrd_clean_specular_hit_alpha_contrast_preparation_20260930'
FMT=[10,28,10,28,10,24,10,41,10,10,3];OFMT=[10,10,3]
def read(p):return json.loads(Path(p).read_text())
def ident(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def verify(r):
 a=ident(r['path']);assert(a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path'];return a
def save(n,d):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(d,f,indent=2,allow_nan=False);f.write('\n')
def module(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert not(HERE/'review.json').exists(),'Preserve any prior attempt'
 direct={};expanded={};inherited={}
 def add(r):a=verify(r);direct[a['path']]=a
 def expand(r):
  a=verify(r)
  if a['path']in inherited:return
  m=read(a['path']);keys=[k for k in ('files','external_sources','external_records')if k in m]
  assert keys and m['self_entry_excluded']
  records=sum((m[k]for k in keys),[])
  inherited[a['path']]=dict(**a,records_keys=keys,record_count=len(records))
  for q in records:b=verify(q);expanded[b['path']]=b
  for q in m.get('inherited_source_manifests',[]):expand(q)
 pins={'readiness_v2.json':'e32359cd871236b0049570d12c8e442f675aa52343d150b95f832cc76a310181','registration_v2.json':'98e4267c0879cc894a7e7cd52d6b3bf6769bee545615edf67e4273557eb4e86c','pre_execution_freeze_v2.json':'a89ed7f26ee96bb3a36d54b9f8256d944de46fd79b890e931b70650c83ab4a5e','completion_manifest_v2.json':'b11ba9acbf4d7ce069ced6e270e5d208d597d95b6c9570d62ffec2dacfae823a','registration.json':'b0ed588f4af7ccb2bc38dedbc7777fce6bbf4c1c0a1c7f2d607160f5700ddc7b','pre_execution_freeze.json':'dffb689bd3c3084e10c468ee47462e74ad704e34fe0d126327dbae6b4cf95c6a','completion_manifest.json':'c30215d2acb49e377648d311000382d79b983b48d61e8072c69af4408f86ed58'}
 for n,h in pins.items():a=ident(PREP/n);assert a['sha256']==h;add(a)
 for n,key,ext in [('completion_manifest.json','files','external_records'),('pre_execution_freeze.json','owned','external_sources'),('completion_manifest_v2.json','files','external_records'),('pre_execution_freeze_v2.json','owned','external_sources')]:
  d=read(PREP/n);assert d['self_entry_excluded']
  for r in d[key]+d[ext]:assert Path(r['path']).resolve()!=(PREP/n).resolve();add(r)
 source=read(PREP/'external_source_pins.json')
 for r in source['records']:add(r)
 for r in source['inherited_expanded_manifests']:expand(r)
 ready=read(PREP/'readiness_v2.json');assert ready['blocking_findings']==[]
 reg=read(PREP/'registration.json');oldreg=read(OLD/'registration.json');native=read(NATIVE/'registration.json')
 assert len(reg['jobs'])==192 and[(j['frame'],j['arm'])for j in reg['jobs']]==[(f,a)for f in range(64)for a in('A0_r0','A10_r0','A0_r1')]
 for k in('actual_helper_jobs','actual_shader_Dispatches','actual_native_contexts','actual_native_API','actual_builds','actual_scores'):assert reg[k]==0
 assert reg['replay_frames_previously_passed']==64 and reg['new_observed_replay_jobs']==0
 gate=read(reg['post_native_gate']['path']);assert gate['status']=='PASSED_SPECULAR_HIT_ALPHA_NATIVE_RAW_EVIDENCE_REVIEW'and gate['blocking_findings']==[]
 assert verify(reg['post_native_gate'])['sha256']=='3bf5116b7030bce0ed3a59620c017bebf1b088558a893bddc1779f8d0a53dfad'
 assert verify(reg['post_native_final_seal'])['sha256']=='722aedb3f81256afb5015286021c4cf70b695338e16ab34543227e450dcb8ab4'
 for r in [reg['frozen_helper'],reg['frozen_guard'],reg['frozen_CSO'],reg['source_sequences'],reg['quantized_raw_reference'],reg['original_report']]:add(r)
 for n in('fsrd_gpu_runner.exe','helper_source_reference.cpp','historical_gpu_runner.build.cmd','helper_work_accounting.py','helper_guard_evidence.py','native_resource_guard.py'):assert(PREP/n).read_bytes()==(OLD/n).read_bytes()
 for n in('FSRDOutputComp_Shader.cso','FSRDOutputComp.hlsl','FSRDPreprocessCommon.hlsli','FSRDFloorCommon.hlsli'):assert(PREP/'frozen_shader'/n).read_bytes()==(OLD/'frozen_shader'/n).read_bytes()
 oldjobs={(j['frame'],j['arm']):j for j in oldreg['jobs']};nativecases={c['tag']:c for c in native['cases']}
 raw={a:{n:(Path(nativecases[a]['job']).parent/n).read_bytes()for n in('diffuse.bin','specular.bin')}for a in('A0_r0','A10_r0','A10_r1','A0_r1')}
 assert raw['A10_r0']==raw['A10_r1'] and raw['A0_r0']!=raw['A0_r1']
 trace=read(PREP/'native_trace_selection.json');assert trace['selected_actual_traces']==['A0_r0','A10_r0','A0_r1']and trace['excluded_actual_trace']=='A10_r1'
 paths=[];folders=[];CB_records=[]
 for j in reg['jobs']:
  f=j['frame'];a=j['arm'];folder=Path(j['job']).parent;assert folder.is_dir()and{p.name for p in folder.iterdir()}=={'in0.bin','in2.bin','job.txt'}
  old=oldjobs[(f,'C0')];rows=[shlex.split(x)for x in Path(j['job']).read_text().splitlines()]
  assert len(rows)==15 and rows[0][2:]==['128','80','11','3','1']
  assert Path(rows[0][0]).resolve()==(PREP/'frozen_shader/FSRDOutputComp_Shader.cso').resolve()
  assert Path(rows[0][1]).read_bytes()==Path(j['CB']['path']).read_bytes()==Path(old['CB']['path']).read_bytes()
  cb=np.fromfile(j['CB']['path'],'<u4');assert len(cb)==24 and cb[4]==8 and cb[5]==cb[13]==cb[16]==0
  for i,(r,oldr,t,fmt)in enumerate(zip(j['inputs'],old['inputs'],rows[1:12],FMT)):
   add(r);assert r['slot']==i and r['format']==fmt and Path(t[0]).resolve()==Path(r['path']).resolve()and t[1:]==['128','80',str(fmt)]
   b=Path(r['path']).read_bytes()
   if i in(0,2):assert b==raw[a]['specular.bin'if i==0 else'diffuse.bin'][f*81920:(f+1)*81920]
   else:assert b==Path(oldr['path']).read_bytes()
  assert j['command']==[str(PREP/'fsrd_gpu_runner.exe'),j['job']]and j['repetitions']==1
  for r,t,fmt in zip(j['outputs'],rows[12:],OFMT):
   assert r['format']==fmt and Path(t[0]).resolve()==Path(r['path']).resolve()and t[1:]==['128','80',str(fmt)]and r['bytes']==(81920 if fmt==10 else 163840)
   q=Path(r['path']);assert q.parent==folder and not q.exists();paths.append(str(q))
  for n in('resource_guard.json','stdout.log','stderr.log'):q=folder/n;assert not q.exists();paths.append(str(q))
  folders.append(str(folder));CB_records.append(j['CB']['sha256'])
 assert len(paths)==len(set(paths))==1152 and len(folders)==192
 for n in('execution_results.json','composition_metrics.json','composed_sequences.npz','execution_TEMP'):assert not(PREP/n).exists()
 driver=(PREP/'run_composition_only.py').read_text();assert driver.index('refuse_existing(reg)')<driver.index('temp.mkdir(exist_ok=False)')<driver.index('from native_resource_guard import run_guarded')
 assert driver.index('save(target,report) # Actual physical work')<driver.index('if error:raise')<driver.index("if not work['metadata_accepted']")
 assert "HERE.resolve()in temp.parents"in driver and "os.environ['OPENBLAS_NUM_THREADS']='1'"in driver
 assert "verify(job['inputs']);verify([job['CB']])"in driver
 law=module('CompAlpha_review_law',PREP/'helper_work_accounting.py');guard=module('CompAlpha_review_guard',PREP/'helper_guard_evidence.py');tests=read(PREP/'CPU_checks.json');checks=[]
 YES=dict(status='completed',child_pid=123,returncode=0,terminated_owned_child=False);NO=dict(status='not_launched_low_available_memory',child_pid=None,returncode=None)
 for t in tests['SIMULATED_helper_checks']:
  n=t['name'];returned={}if n=='fresh_missing_guard_marker_lowerbound'else NO if n in('nochild_stale_marker_reject','stored_child_returned_nochild_canonical')else YES
  folder=PREP/'SIMULATED_CPU'/n;g,e,artifact=guard.load_guard_best_effort(folder,returned,None);w=law.accounting(folder,[dict(path=str(folder/f'out{i}.bin'),bytes=4)for i in range(3)],g,e,fresh_scope_authenticated=True)
  assert t['passed']and t['SIMULATED']and g==t['guard']and artifact==t['guard_artifact']and w==t['work'];checks.append(dict(name=n,exact_existing_SIM_replay=True))
 assert len(checks)==6
 helper=(PREP/'helper_source_reference.cpp').read_text();assert helper.count('cmd->Dispatch(')==1 and helper.index('WaitForSingleObject')<helper.index('gpu_ms_median=')<helper.index('validation_errors=')
 V1=(PREP/'analyze_composed_cpu.py').read_bytes();V2=(PREP/'analyze_composed_cpu_v2.py').read_bytes()
 assert V1.count(b"sealed['external_records']")==1 and V1.replace(b"sealed['external_records']",b"sealed['external_sources']")==V2
 analyzer=V2.decode();assert "range(64)"in analyzer and "('A0_r0', 'A10_r0', 'A0_r1')"in analyzer and "excluded_A10_r1_not_measured=True"in analyzer
 # Source/AST inspection only: inherited oldB score evidence is not rerun.
 metricchecks=[]
 for item,olditem in zip(reg['metric_function_extraction'],oldreg['metric_function_extraction']):
  assert item['name']==olditem['name']and Path(item['source']).read_bytes()==Path(olditem['source']).read_bytes()
  source=Path(item['source']);node=next(n for n in ast.parse(source.read_text()).body if(isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets)))
  original_node=next(n for n in ast.parse(Path(olditem['source']).read_text()).body if(isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets)))
  assert ast.dump(node,include_attributes=False)==ast.dump(original_node,include_attributes=False)
  metricchecks.append(dict(name=item['name'],AST_and_source_bytes_exact=True,executed=False))
 with np.load(reg['source_sequences']['path'])as z:truth=z['clean_reference'].copy();baseline=z['baseline'].copy()
 assert truth.shape==baseline.shape==(64,80,128,3)
 # Original rgba() raw encoder fills alpha0; it is separate from OutColor alpha1.
 add(ident(BASE/'fsrd_weak_material_clean_response_design_20260930/prepare_design.py'))
 encoded=np.concatenate((truth[0],np.zeros((80,128,1),dtype=truth.dtype)),axis=-1).astype('<f2').tobytes();assert encoded==Path(reg['quantized_raw_reference']['path']).read_bytes()
 assert np.array_equal(truth,np.broadcast_to(truth[0],truth.shape))
 inherited_replay=read(reg['inherited_prior_observed_replay']['path'])
 assert inherited_replay['status']=='PASSED_CLEAN_COMPOSITION_EVIDENCE_AND_EXACT_METRIC_REVIEW'and inherited_replay['blocking_findings']==[]
 priorseal=read(reg['prior_composition_final_seal']['path']);pinmap={str(Path(r['path']).resolve()).lower():r for r in priorseal['files']+priorseal['external_sources']};prioroutputs=[]
 for a in('C0','C1'):
  for f in range(64):
   for o in oldjobs[(f,a)]['outputs']:r=pinmap[str(Path(o['path']).resolve()).lower()];verify(r);prioroutputs.append(r['path'])
 assert len(prioroutputs)==384
 for r in list(direct.values())+list(expanded.values()):verify(r)
 unique=len({str(Path(r['path']).resolve()).lower()for r in list(direct.values())+list(expanded.values())})
 limits=['Only3 selectedactual64-frame native traces feed192 planned composition helpers. A10_r1 is input-equivalent toA10_r0 but not a fourth measured composition trace.', 'Within-doseA0 native repeats differ; conditional between-dose composition metrics cannot isolate alpha causation.', 'All other9 full SRV fields and96CB match priorC0 graphs. Inherited64 observed all3-buffer replay is historical sealed evidence;0new observed replay jobs.', 'Helper timing fence interpretation is source-qualified, historical EXE/CSO bytes pinned; no new compile linkage or SDK/private shader-dispatch claim.', 'WriteHistory0 auxiliary UAV bytes may be unwritten. All3 outputs will be retained but consumedRGB interpretation remains separate.', 'No scorer executed during this review; oldB4-window score checks remain inherited sealed evidence. Fixed metrics/reference thresholds and signed rank1Nyquist phase are retained.', '+10 is view-depth proxy, not traced ray length; no vendor/game cause or quality acceptance.']
 report=dict(status='READY_FOR_ROOT_SPECULAR_HIT_ALPHA_COMPOSITION_V2_AUTHORIZATION',blocking_findings=[],producer_pins={n:ident(PREP/n)for n in pins},source_validation=dict(direct_pre_post=len(direct),inherited_unique_pre_post=len(expanded),expanded_unique=unique,inherited_seals_pinned_once=len(inherited),source_bytes_unchanged=True),graph=dict(frames=64,traces=3,jobs=192,planned_outputs=576,order='frame0..63 A0_r0,A10_r0,A0_r1',t0_spec_t2_diff_fullRGBA_actual_slices=True,other9_fullbytes_andCB96_priorC0_exact=True,Flags8_Detail0_HistoryValid0_WriteHistory0=True,excluded_A10_r1_full64_native_lobes_exact=True,new_fourth_composed_trace_claim=False),runtime=dict(PREP_exists=True,evidence_parent_PREP_exists=True,all192_job_parents_exist_only_immutable_in0_in2_job=True,all1152_job_targets_absent=True,three_global_results_and_TEMP_absent=True),accounting=dict(existing6_SIM_exact=checks,parser_guard_EXE_CSO_byteexact=True,physical_checkpoint_before_metadata=True,owned_F_TEMP_exclusive=True,source_one_Dispatch_per_repetition1_postfence_marker=True,no_retries=True),analysis=dict(V1_schema_failure_preserved=True,V2_only_one_metadata_lookup_key_repair=True,prior384_output_records_authenticated=True,scored_values9_references2_windows4_fixed=True,metric_AST_byteexact=metricchecks,oldB_four_window_checks_inherited_not_rerun=True,raw_constructed_truth_static_not_native_response=True,quantized_truth_actual_format10_encoder_exact=True,future_once_only_after192accepted=True,no_scorer_executed=True,no_future_actual_output_scores=True),limitations=limits,actual_review_GPU_native_build_new_scores=0,quality_accepted=False)
 save('review.json',report)
 save('compact.json',dict(status=report['status'],blocking_findings=[],source_validation=report['source_validation'],graph=report['graph'],runtime=report['runtime'],accounting=report['accounting'],analysis=report['analysis'],limitations=limits,actual_review_GPU_native_build_new_scores=0))
 save('completion_manifest.json',dict(status='SEALED_INDEPENDENT_THREE_TRACE_COMPOSITION_V2_PRELAUNCH_REVIEW',files=[ident(HERE/n)for n in('review_cpu.py','review.json','compact.json','review_cpu_attempt1.py.txt','audit_attempt1_erratum.json')],external_sources=list(direct.values()),inherited_source_manifests=list(inherited.values()),expanded_unique_record_count=unique,self_entry_excluded=True,actual_review_GPU_native_build_new_scores=0))
 print(json.dumps(dict(status=report['status'],files=5,direct=len(direct),inherited=len(inherited),expanded_unique=unique,pins={n:ident(HERE/n)for n in('review.json','compact.json','completion_manifest.json')})))
if __name__=='__main__':main()
