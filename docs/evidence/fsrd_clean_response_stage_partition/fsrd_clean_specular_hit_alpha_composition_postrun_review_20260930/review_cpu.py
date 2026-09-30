"""Saved actual helper bytes and frozen descriptive metrics; no executable invocation."""
from pathlib import Path
import ast,hashlib,importlib.util,itertools,json,sys,types
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
PRE=BASE/'fsrd_clean_specular_hit_alpha_composition_prelaunch_review_20260930'
PREP=BASE/'fsrd_clean_specular_hit_alpha_composition_preparation_20260930'
ARMS=('A0_r0','A10_r0','A0_r1')
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
def module(n,p):s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def bits(a,b,i):
 return dict(full_serialized_bits_exact=bool(np.array_equal(a.view('<u2')if i<2 else a,b.view('<u2')if i<2 else b)),RGB_bits_exact=bool(np.array_equal(a[...,:3].view('<u2')if i<2 else a[...,:3],b[...,:3].view('<u2')if i<2 else b[...,:3])),alpha_bits_exact=bool(np.array_equal(a[...,3].view('<u2')if i<2 else a[...,3],b[...,3].view('<u2')if i<2 else b[...,3])))
def main():
 assert not(HERE/'review.json').exists(),'Preserve prior attempt'
 assert ident(PRE/'review.json')['sha256']=='f460f343c9ec7efa2303d9bea6a63d1cc65f3ad44c77c767fcbd0706ae743900'
 assert ident(PRE/'completion_manifest.json')['sha256']=='cd209fa1d2da9be1e6b014e505366a278576a3b46a0e1fcf1d51aa19ad81bad9'
 assert read(PRE/'review.json')['blocking_findings']==[]
 seal=read(PRE/'completion_manifest.json');direct={};expanded={}
 for r in seal['files']+seal['external_sources']:a=verify(r);direct[a['path']]=a
 direct[str(PRE/'completion_manifest.json')]=ident(PRE/'completion_manifest.json')
 for a in seal['inherited_source_manifests']:
  verify(a);m=read(a['path']);records=sum((m[k]for k in a['records_keys']),[]);assert len(records)==a['record_count']
  for r in records:b=verify(r);expanded[b['path']]=b
 auth=BASE/'fsrd_specular_hit_alpha_composition_v2_root_authorization_20260930.json';obs=BASE/'fsrd_specular_hit_alpha_composition_root_tool_observations_20260930.json'
 assert ident(auth)['sha256']=='218eb036d0f8bac349eb5d02b62ea9cb7d7c7654a19539cfa88afdd5dffd58ac'
 assert ident(obs)['sha256']=='6471737109cb29f7c8cbb99f98710f92b0f4b48da366e20d1babacfe3e64841f'
 for p in(auth,obs,PREP/'execution_results.json',PREP/'composition_metrics.json',PREP/'composed_sequences.npz'):direct[str(p)]=ident(p)
 rootobs=read(obs)
 for k in('authorization','execution','metrics','composed_sequences'):verify(rootobs[k])
 assert rootobs['actual_tool_observations']['driver_final_exit_code']==rootobs['actual_tool_observations']['analyzer_exit_code']==0
 reg=read(PREP/'registration.json');run=read(PREP/'execution_results.json');producer=read(PREP/'composition_metrics.json')
 assert run['status']=='completed_composition_only_awaiting_independent_review_not_quality_accepted'
 assert producer['status']=='completed_CPU_composed_clean_response_measurement_not_quality_accepted'
 assert producer['execution_results_sha256']==ident(PREP/'execution_results.json')['sha256']
 assert [(r['frame'],r['arm'])for r in run['jobs']]==[(f,a)for f in range(64)for a in ARMS]
 assert run['actual_new_native_contexts']==run['actual_new_native_API']==run['observed_replay_accepted_frames']==0 and run['inherited_prior_observed_replay_passed_frames']==64
 assert Path(run['environment']['TMP']).resolve()==Path(run['environment']['TEMP']).resolve()==(PREP/'execution_TEMP').resolve()and run['environment']['OPENBLAS_NUM_THREADS']=='1'
 law=module('alpha_comp_post_law',PREP/'helper_work_accounting.py');loader=module('alpha_comp_post_guard',PREP/'helper_guard_evidence.py')
 raw={a:[[]for _ in range(3)]for a in ARMS};workrows=[];pids=[];runtime=[]
 for j,r in zip(reg['jobs'],run['jobs']):
  folder=Path(j['job']).parent;g,e,artifact=loader.load_guard_best_effort(folder,r['guard_artifact']['returned_guard_claim'],None)
  assert e is None and g==r['guard']==read(folder/'resource_guard.json')and artifact==r['guard_artifact']
  assert artifact['authority']=='direct_returned_guard'and not artifact['returned_stored_conflict']
  assert g['args']==j['command']and g['status']=='completed'and g['returncode']==0 and not g['terminated_owned_child']and type(g['child_pid'])is int and g['child_pid']>0
  assert g['timeout_seconds']==240 and g['maximum_working_set_bytes']==2**31 and g['minimum_available_memory_bytes']==2**30 and g['sample_interval_seconds']==.2
  assert g['peak_observed_working_set_bytes']<=2**31 and g['minimum_observed_available_bytes']>=2**30
  pids.append(g['child_pid']);w=law.accounting(folder,j['outputs'],g,None,fresh_scope_authenticated=True);assert w==r['work']
  assert w['exact_helper_child_total']==w['exact_shader_dispatch_total']==w['confirmed_fence_completions_lower_bound']==1 and w['explicit_post_fence_stdout_proof']and w['metadata_accepted']
  assert not w['partial_dispatch_total_unknown']and not w['evidence_conflicts']and w['fields']['diagnostic']==dict(errors=0,warnings=0)and w['fields']['timing']['debug_layer']==1
  assert r['metadata_accepted']and r['completed_accepted']and r['observed_replay_accepted']is None and(folder/'stderr.log').read_bytes()==b''
  for n in('resource_guard.json','stdout.log','stderr.log'):a=ident(folder/n);direct[a['path']]=a;runtime.append(a)
  for i,o in enumerate(j['outputs']):
   b=Path(o['path']).read_bytes();assert len(b)==o['bytes']and hashlib.sha256(b).hexdigest()==w['outputs'][i]['sha256']
   a=ident(o['path']);direct[a['path']]=a;runtime.append(a)
   raw[j['arm']][i].append(np.frombuffer(b,'<f2'if i<2 else'<u4').reshape(80,128,4).copy())
  color=raw[j['arm']][0][-1];assert np.isfinite(color[...,:3]).all()and r['consumed_color_RGB_finite']
  assert r['consumed_color_RGB_valid_range']==bool(np.all((color[...,:3]>=0)&(color[...,:3]<=65504)))
  workrows.append(dict(frame=j['frame'],arm=j['arm'],PID=g['child_pid'],postfence_dispatch_proven=True,direct_stored_equal=True,diagnostics0=True,all3sizes_hashes=True))
 for k in('executor_job_invocations_started','helper_children_lower_bound','confirmed_shader_dispatches_lower_bound','confirmed_fence_completions_lower_bound','exact_helper_total','exact_shader_dispatch_total','metadata_accepted_jobs','completed_accepted_jobs'):assert run[k]==192
 assert len(runtime)==1152
 raw={a:[np.stack(v)for v in vv]for a,vv in raw.items()};arrays={a:vv[0][...,:3].astype('<f4')for a,vv in raw.items()}
 repeats={}
 for a,b in itertools.combinations(ARMS,2):
  pair={}
  for i,(x,y)in enumerate(zip(raw[a],raw[b])):
   d=x.astype('float64')-y.astype('float64');pair[f'out{i}']=dict(**bits(x,y,i),RGBA_RMS=float(np.sqrt(np.mean(d*d))),RGB_RMS=float(np.sqrt(np.mean(d[...,:3]**2))))
  repeats[a+'__'+b]=pair
 oldreg=read(reg['prior_composition_registration']['path']);oldseal=read(reg['prior_composition_final_seal']['path']);pinmap={str(Path(r['path']).resolve()).lower():r for r in oldseal['files']+oldseal['external_sources']};oldraw={}
 for a in('C0','C1'):
  oldjobs=[j for j in oldreg['jobs']if j['arm']==a];assert[j['frame']for j in oldjobs]==list(range(64));oldraw[a]=[]
  for i in range(3):
   for j in oldjobs:verify(pinmap[str(Path(j['outputs'][i]['path']).resolve()).lower()])
   oldraw[a].append(np.stack([np.fromfile(j['outputs'][i]['path'],'<f2'if i<2 else'<u4').reshape(80,128,4)for j in oldjobs]))
 for a in ARMS:
  for b in('C0','C1'):repeats[a+'__prior_'+b]={f'out{i}':bits(x,y,i)for i,(x,y)in enumerate(zip(raw[a],oldraw[b]))}
 assert repeats==producer['raw_output_repeats']
 assert all(x['full_serialized_bits_exact']for b in('C0','C1')for x in repeats['A10_r0__prior_'+b].values())
 with np.load(reg['source_sequences']['path'])as z:truth=z['clean_reference'].copy();B=z['baseline'].copy();TP=z['pilot_response'].copy();O=z['observed'].copy();P=z['pilot'].copy()
 q=np.fromfile(reg['quantized_raw_reference']['path'],'<f2').reshape(80,128,4).astype('<f4')[...,:3];quantized=np.broadcast_to(q,truth.shape)
 with np.load(PREP/'composed_sequences.npz')as z:
  assert set(z.files)==set(ARMS)|{'raw_constructed_truth','quantized_raw_reference'}
  for a in ARMS:assert z[a].tobytes()==raw[a][0].tobytes()
  assert z['raw_constructed_truth'].tobytes()==truth.tobytes()and z['quantized_raw_reference'].tobytes()==quantized.tobytes()
 scope={'np':np}
 for item in reg['metric_function_extraction']:
  source=Path(item['source']);node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,(ast.FunctionDef,ast.Assign))and((isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets))))
  if item['name']=='moments':scope['ref']=types.SimpleNamespace(score=scope['score'])
  if item['name']=='detail':scope['helper']=types.SimpleNamespace(moments=scope['moments'])
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
 values=dict(raw_constructed_truth=truth,quantized_raw_reference=quantized,oldB=B,oldTP=TP,old_observed=O,old_pilot=P,**arrays)
 windows=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]
 metrics={name:{refname:{label:scope['detail'](value[sl],ref[sl])for label,sl in windows}for refname,ref in[('raw_constructed_truth',truth),('quantized_raw_reference',quantized)]}for name,value in values.items()}
 assert metrics==producer['metrics']
 y,x=np.indices((80,128));phi=np.exp(2j*np.pi*(64*(x-63.5)/128-40*(y-39.5)/80)).real;phi-=phi[5:-5,5:-5].mean();roi=phi[5:-5,5:-5];norm=np.sum(roi**2)
 independent=np.where((x-y)%2==0,1.,-1.);independent-=independent[5:-5,5:-5].mean();iroi=independent[5:-5,5:-5];inorm=np.sum(iroi**2)
 coefs={};independent_errors={}
 for name,value in values.items():
  a=value[:,5:-5,5:-5].astype('float64');dc=a.mean((1,2));beta=np.einsum('hw,nhwc->nc',roi,a-dc[:,None,None])/norm;ibeta=np.einsum('hw,nhwc->nc',iroi,a-dc[:,None,None])/inorm
  independent_errors[name]=float(np.max(abs(beta-ibeta)));assert independent_errors[name]<1e-16
  coefs[name]=dict(interior_DC_per_frame_RGB=dc.tolist(),full_DC_per_frame_RGB=value.astype('float64').mean((1,2)).tolist(),signed_Nyquist_beta_per_frame_RGB=beta.tolist())
 for name,c in coefs.items():
  c['comparisons']={}
  for ref in('raw_constructed_truth','quantized_raw_reference'):
   dc=np.asarray(c['interior_DC_per_frame_RGB'])-np.asarray(coefs[ref]['interior_DC_per_frame_RGB']);beta=np.asarray(c['signed_Nyquist_beta_per_frame_RGB']);rb=np.asarray(coefs[ref]['signed_Nyquist_beta_per_frame_RGB'])
   c['comparisons'][ref]=dict(DC_bias_per_frame_RGB=dc.tolist(),signed_beta_bias_per_frame_RGB=(beta-rb).tolist(),signed_beta_gain_per_frame_RGB=(beta/rb).tolist(),rank1_sign_phase_error_per_frame_RGB=np.where(beta*rb>=0,0,np.pi).tolist())
 assert coefs==producer['DC_beta']
 ratios={arm:{ref:{label:(metrics[arm][ref][label]['score']['residual_temporal_std']/metrics['oldB'][ref][label]['score']['residual_temporal_std']if metrics['oldB'][ref][label]['score']['residual_temporal_std']else None)for label,_ in windows}for ref in('raw_constructed_truth','quantized_raw_reference')}for arm in ARMS}
 assert ratios==producer['descriptive_STD_ratio_to_oldB']
 save('metric_reproduction.json',dict(status='INDEPENDENT_EXACT_FROZEN_SAVED_FP16_METRIC_REPRODUCTION',metrics=metrics,DC_beta=coefs,independent_parity_rank1_max_errors=independent_errors,raw_output_repeats=repeats,STD_ratios=ratios,quality_accepted=False))
 for r in list(direct.values())+list(expanded.values()):verify(r)
 unique=len({str(Path(r['path']).resolve()).lower()for r in list(direct.values())+list(expanded.values())})
 summaries={}
 for a in ARMS:
  summaries[a]={ref:{label:dict(gain_min=m['absolute_gain_min'],gain_mean=m['absolute_gain_mean'],gain_max=m['absolute_gain_max'],phase_max=m['absolute_phase_max'],detail_pass=m['detail_within_5_percent_all_frames'],gain_failing_frames=m['absolute_gain_failing_frames'],phase_failing_frames=m['absolute_phase_failing_frames'],temporal_STD=m['score']['residual_temporal_std'])for label,m in metrics[a][ref].items()}for ref in('raw_constructed_truth','quantized_raw_reference')}
 biases={a:np.asarray(coefs[a]['comparisons']['raw_constructed_truth']['DC_bias_per_frame_RGB'])[-16:].mean(0).tolist()for a in ARMS}
 limits=['192 source-qualified helperDispatch/fence observations are separate from SDK:0new SDK/native work; inherited64 observedreplays are historical,0new observedreplay.', 'Three actual composition traces only; A10_r1 omission is old full64rawRGBA input equality, not a fourth measured composition repeat.', 'A0 within-dose native and composed repeats vary. Conditional between-dose differences of comparable scale cannot isolate hit-alpha cause.', 'Constructed rawtruth and actual rawformat10 quantizedreference are scorer references, not physical/game clean groundtruth. +10 is viewdepthproxy, not tracedray.', 'Historical source/CSO/EXE identities are retained; source-qualified post-fence marker interpretation does not invent freshcompile provenance or privateSDK shadercounts.', 'History0 auxiliary UAV bytes may be unwritten; equality is storage-level observation rather than proof of writes/semantic validity.', 'Preserved V1 metadata key issue and reviewer rawalpha1 expectation were fixed before any actual scoring/GPU; only frozenV2 analyzer once was executed byroot. Independent reviewer applies only samefrozen AST to savedarrays.', 'No new model, corrections, tuning, runtime/production/game changes or acceptance claim. VerylowSTD coexists with failed absolute detail gains.']
 report=dict(status='PASSED_SPECULAR_HIT_ALPHA_COMPOSITION_V2_EVIDENCE_AND_METRIC_REVIEW',blocking_findings=[],actual_counts=dict(helper_children=192,explicit_helper_Dispatches=192,post_fence_helpers=192,metadata_accepted=192,outputs=576,new_SDK_contexts=0,new_SDK_API=0,new_observed_replay=0,inherited_observed_replay=64,actual_composed_traces=3),source_validation=dict(direct_pre_post=len(direct),inherited_unique_pre_post=len(expanded),expanded_unique=unique,inherited_manifests_pinned_once=len(seal['inherited_source_manifests'])),case_evidence=workrows,guard=dict(errors_warnings0=True,all_stderr_empty=True,all_direct_stored_equal=True,unknown_total_jobs=0,terminated_children=0,distinct_PID_count=len(set(pids)),maximum_WS=max(r['guard']['peak_observed_working_set_bytes']for r in run['jobs']),minimum_available_memory=min(r['guard']['minimum_observed_available_bytes']for r in run['jobs'])),metrics=dict(all9values2refs4windows_dicts_exact=True,all_DC_beta_signed_gain_phase_exact=True,all_STD_ratios_exact=True,NPZ_FP16_outputs_exact=True,all3pairs_and6priorcomp_comparisons_exact=True,independent_parity_maxerror=max(independent_errors.values()),summaries=summaries,mature_signed_RGB_DC_bias_to_rawtruth=biases,STD_ratios_to_oldB=ratios),raw_output_repeats=repeats,limits=limits,actual_review_GPU_native_build_newmodel=0,quality_accepted=False,game_run=False)
 save('review.json',report)
 save('compact.json',dict(status=report['status'],blocking_findings=[],actual_counts=report['actual_counts'],source_validation=report['source_validation'],all_producer_metrics_exact=True,summaries=summaries,mature_signed_RGB_DC_bias_to_rawtruth=biases,STD_ratios_to_oldB=ratios,raw_output_repeats=repeats,limits=limits,quality_accepted=False))
 save('completion_manifest.json',dict(status='SEALED_SPECULAR_HIT_ALPHA_COMPOSITION_V2_POSTREVIEW',files=[ident(HERE/n)for n in('review_cpu.py','metric_reproduction.json','review.json','compact.json')],external_sources=list(direct.values()),inherited_source_manifests=seal['inherited_source_manifests'],expanded_unique_record_count=unique,self_entry_excluded=True,actual_review_GPU_native_build_newmodel=0))
 print(json.dumps(dict(status=report['status'],files=4,direct=len(direct),inherited=len(seal['inherited_source_manifests']),expanded_unique=unique,pins={n:ident(HERE/n)for n in('review.json','compact.json','metric_reproduction.json','completion_manifest.json')})))
if __name__=='__main__':main()
