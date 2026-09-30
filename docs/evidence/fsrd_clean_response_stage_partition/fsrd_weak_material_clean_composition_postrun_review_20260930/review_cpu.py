"""Postrun CPU-only review and exact frozen metrics. Never invokes helper, SDK or build."""
from pathlib import Path
import ast,hashlib,importlib.util,itertools,json,sys,types
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
PREP=HERE.parent/'fsrd_weak_material_clean_composition_preparation_20260930'
PRE_REVIEW=HERE.parent/'fsrd_weak_material_clean_composition_prelaunch_review_20260930'
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
 assert ident(PRE_REVIEW/'review.json')['sha256']=='fa7e1a88f6f877bcdf2f42aadbbc43cf467c628f80e41d41cd9caefc03064df3'
 assert ident(PRE_REVIEW/'completion_manifest_final.json')['sha256']=='99adf2b1dfbee2740db71750000d790f7abf04762414484a78093f4088d0eeae'
 pre=read(PRE_REVIEW/'completion_manifest_final.json');records={r['path']:r for r in pre['external_sources']}
 for r in pre['files']+pre['external_sources']:verify(r);records[r['path']]=ident(r['path'])
 records[str(PRE_REVIEW/'completion_manifest_final.json')]=ident(PRE_REVIEW/'completion_manifest_final.json')
 auth=HERE.parent/'fsrd_clean_composition_root_authorization_20260930.json'
 obs=HERE.parent/'fsrd_clean_composition_root_tool_observations_20260930.json'
 assert ident(auth)['sha256']=='e8abe0ed7de98d10bfff932683ef78739f63992d496f7d1f5a564f3d00965663'
 assert ident(obs)['sha256']=='35357af1791831e69c7711783685503559a208ef10c654e7b2107f4b461d4743'
 for p in[auth,obs,PREP/'execution_results.json',PREP/'composition_metrics.json',PREP/'composed_sequences.npz']:records[str(p)]=ident(p)
 reg=read(PREP/'registration.json');run=read(PREP/'execution_results.json');producer=read(PREP/'composition_metrics.json')
 assert run['status']=='completed_composition_only_awaiting_independent_review_not_quality_accepted'
 assert producer['status']=='completed_CPU_composed_clean_response_measurement_not_quality_accepted'
 assert producer['execution_results_sha256']==ident(PREP/'execution_results.json')['sha256']
 assert [(j['frame'],j['arm'])for j in run['jobs']]==[(f,a)for f in range(64)for a in('observed_control','C0','C1')]
 assert len(run['jobs'])==len(reg['jobs'])==192 and not run['actual_new_native_contexts']and not run['actual_new_native_API']
 assert run['environment']['TMP']==run['environment']['TEMP']==str((PREP/'execution_TEMP').resolve())
 assert run['environment']['OPENBLAS_NUM_THREADS']=='1'and (PREP/'execution_TEMP').is_dir()
 accounting=module('clean_comp_post_parser',PREP/'helper_work_accounting.py');loader=module('clean_comp_post_guard',PREP/'helper_guard_evidence.py')
 counters={k:0 for k in ['helpers','dispatches','fences','metadata','accepted','replays']};cases=[];pids=[];runtime_records=[]
 raw={a:[[]for _ in range(3)]for a in('observed_control','C0','C1')}
 for job,row in zip(reg['jobs'],run['jobs']):
  folder=Path(job['job']).parent;assert folder.is_dir()
  assert row['guard']['args']==job['command'] and row['guard']['status']=='completed'and row['guard']['returncode']==0
  assert type(row['guard']['child_pid'])is int and row['guard']['child_pid']>0
  pids.append(row['guard']['child_pid'])
  guard,error,artifact=loader.load_guard_best_effort(folder,row['guard_artifact']['returned_guard_claim'],None)
  assert error is None and guard==row['guard'] and artifact==row['guard_artifact']
  assert artifact['authority']=='direct_returned_guard'and not artifact['returned_stored_conflict']and artifact['stored_guard_claim']==guard
  assert guard['timeout_seconds']==240 and guard['maximum_working_set_bytes']==2147483648 and guard['minimum_available_memory_bytes']==1073741824 and guard['sample_interval_seconds']==.2
  assert not guard['terminated_owned_child'] and guard['peak_observed_working_set_bytes']<=guard['maximum_working_set_bytes']
  assert guard['minimum_observed_available_bytes']>=guard['minimum_available_memory_bytes']
  work=accounting.accounting(folder,job['outputs'],guard,None,fresh_scope_authenticated=True)
  assert work==row['work']
  assert work['confirmed_helper_children_lower_bound']==work['exact_helper_child_total']==1
  assert work['confirmed_shader_dispatches_lower_bound']==work['confirmed_fence_completions_lower_bound']==work['exact_shader_dispatch_total']==1
  assert not work['partial_dispatch_total_unknown'] and not work['evidence_conflicts']
  assert work['metadata_accepted'] and work['fields']['diagnostic']==dict(errors=0,warnings=0)
  assert work['explicit_post_fence_stdout_proof']and work['fields']['timing']['debug_layer']==1
  assert row['metadata_accepted']and row['completed_accepted']
  assert (folder/'stderr.log').read_bytes()==b''
  for n in('resource_guard.json','stdout.log','stderr.log'):runtime_records.append(ident(folder/n))
  for i,out in enumerate(job['outputs']):
   verify(work['outputs'][i]if False else dict(path=out['path'],bytes=out['bytes'],sha256=work['outputs'][i]['sha256']))
   data=Path(out['path']).read_bytes();assert len(data)==out['bytes']
   runtime_records.append(ident(out['path']))
   arr=np.frombuffer(data,'<f2'if i<2 else'<u4').reshape(80,128,4).copy();raw[job['arm']][i].append(arr)
   if job['arm']=='observed_control':assert data==Path(out['historical_expected']['path']).read_bytes()
  if job['arm']=='observed_control':
   assert row['observed_replay_accepted']and all(x['full_bytes_exact']for x in row['observed_replay_checks']);counters['replays']+=1
  color=raw[job['arm']][0][-1];assert np.isfinite(color[...,:3]).all()
  valid=bool(np.all((color[...,:3]>=0)&(color[...,:3]<=65504)))
  assert row['consumed_color_RGB_finite']and valid==row['consumed_color_RGB_valid_range']
  counters['helpers']+=1;counters['dispatches']+=1;counters['fences']+=1;counters['metadata']+=1;counters['accepted']+=1
  cases.append(dict(frame=job['frame'],arm=job['arm'],PID=guard['child_pid'],postfence_stdout_proven=True,direct_stored_guard_equal=True,diagnostics0=True,all3_output_sizes_hashes_verified=True,RGB_valid=valid))
 assert counters==dict(helpers=192,dispatches=192,fences=192,metadata=192,accepted=192,replays=64)
 for k in('executor_job_invocations_started','helper_children_lower_bound','confirmed_shader_dispatches_lower_bound','confirmed_fence_completions_lower_bound','exact_helper_total','exact_shader_dispatch_total','metadata_accepted_jobs','completed_accepted_jobs'):assert run[k]==192
 assert run['observed_replay_accepted_frames']==64
 for r in runtime_records:records[r['path']]=r
 raw={a:[np.stack(v)for v in vv]for a,vv in raw.items()};arrays={a:vv[0][...,:3].astype('<f4')for a,vv in raw.items()}
 repeat={}
 for a,b in itertools.combinations(raw,2):
  pair={}
  for i in range(3):
   av=raw[a][i];bv=raw[b][i];d=av.astype('float64')-bv.astype('float64')
   pair[f'out{i}']=dict(full_serialized_bits_exact=bool(np.array_equal(av.view('<u2')if i<2 else av,bv.view('<u2')if i<2 else bv)),RGB_bits_exact=bool(np.array_equal(av[...,:3].view('<u2')if i<2 else av[...,:3],bv[...,:3].view('<u2')if i<2 else bv[...,:3])),alpha_bits_exact=bool(np.array_equal(av[...,3].view('<u2')if i<2 else av[...,3],bv[...,3].view('<u2')if i<2 else bv[...,3])),RGBA_RMS=float(np.sqrt(np.mean(d*d))),RGB_RMS=float(np.sqrt(np.mean(d[...,:3]**2))))
  repeat[a+'__'+b]=pair
 assert repeat==producer['raw_output_repeats']
 assert all(v['full_serialized_bits_exact']for v in repeat['C0__C1'].values())
 with np.load(reg['source_sequences']['path'])as z:truth=z['clean_reference'].copy();B=z['baseline'].copy();TP=z['pilot_response'].copy();O=z['observed'].copy();P=z['pilot'].copy()
 assert np.array_equal(arrays['observed_control'],B)
 q=np.fromfile(reg['quantized_raw_reference']['path'],'<f2').reshape(80,128,4).astype('<f4')[...,:3];quantized=np.broadcast_to(q,truth.shape)
 with np.load(PREP/'composed_sequences.npz')as saved:
  assert set(saved.files)==set(raw)|{'raw_constructed_truth','quantized_raw_reference'}
  for a in raw:assert np.array_equal(saved[a].view('<u2'),raw[a][0].view('<u2'))
  assert np.array_equal(saved['raw_constructed_truth'],truth)and np.array_equal(saved['quantized_raw_reference'],quantized)
 scope={'np':np}
 for item in reg['metric_function_extraction']:
  source=Path(item['source']);node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,(ast.FunctionDef,ast.Assign))and((isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets))))
  if item['name']=='moments':scope['ref']=types.SimpleNamespace(score=scope['score'])
  if item['name']=='detail':scope['helper']=types.SimpleNamespace(moments=scope['moments'])
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
 values=dict(raw_constructed_truth=truth,quantized_raw_reference=quantized,oldB=B,oldTP=TP,old_observed=O,old_pilot=P,**arrays)
 windows=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]
 oldrow=next(r for r in read(reg['original_report']['path'])['rows']if r['scene']=='weak_material')
 for label,sl in windows:assert scope['detail'](B[sl],truth[sl])==oldrow['baseline_metrics'][label]
 metrics={name:{refname:{label:scope['detail'](value[sl],ref[sl])for label,sl in windows}for refname,ref in [('raw_constructed_truth',truth),('quantized_raw_reference',quantized)]}for name,value in values.items()}
 assert metrics==producer['metrics']
 # Independent exact rank1 algebra: centered physical Nyquist cos equals (-1)^(x-y).
 y,x=np.indices((80,128));phi=np.where((x-y)%2==0,1.,-1.);phi-=phi[5:-5,5:-5].mean();roi=phi[5:-5,5:-5];norm=np.sum(roi*roi)
 coefs={};coef_errors={}
 for name,value in values.items():
  a=value[:,5:-5,5:-5].astype('float64');dc=a.mean((1,2));beta=np.einsum('hw,nhwc->nc',roi,a-dc[:,None,None])/norm
  full=value.astype('float64').mean((1,2));coefs[name]=dict(interior_DC_per_frame_RGB=dc.tolist(),full_DC_per_frame_RGB=full.tolist(),signed_Nyquist_beta_per_frame_RGB=beta.tolist())
  e={k:float(np.max(np.abs(np.asarray(v)-np.asarray(producer['DC_beta'][name][k]))))for k,v in coefs[name].items()};assert max(e.values())<1e-16;coef_errors[name]=e
 for name,c in coefs.items():
  c['comparisons']={}
  for refname in('raw_constructed_truth','quantized_raw_reference'):
   dc=np.asarray(c['interior_DC_per_frame_RGB'])-np.asarray(coefs[refname]['interior_DC_per_frame_RGB']);beta=np.asarray(c['signed_Nyquist_beta_per_frame_RGB']);ref=np.asarray(coefs[refname]['signed_Nyquist_beta_per_frame_RGB'])
   c['comparisons'][refname]=dict(DC_bias_per_frame_RGB=dc.tolist(),signed_beta_bias_per_frame_RGB=(beta-ref).tolist(),signed_beta_gain_per_frame_RGB=(beta/ref).tolist(),rank1_sign_phase_error_per_frame_RGB=np.where(beta*ref>=0,0,np.pi).tolist())
   for k,v in c['comparisons'][refname].items():assert np.max(np.abs(np.asarray(v)-np.asarray(producer['DC_beta'][name]['comparisons'][refname][k])))<1e-13
 ratios={arm:{ref:{label:(metrics[arm][ref][label]['score']['residual_temporal_std']/metrics['oldB'][ref][label]['score']['residual_temporal_std']if metrics['oldB'][ref][label]['score']['residual_temporal_std']else None)for label,_ in windows}for ref in('raw_constructed_truth','quantized_raw_reference')}for arm in('C0','C1')}
 assert ratios==producer['descriptive_STD_ratio_to_oldB']
 descriptive={}
 for arm in raw:
  av=raw[arm][0];descriptive[arm]=dict(color_RGB_min=float(av[...,:3].min()),color_RGB_max=float(av[...,:3].max()),color_alpha_unique=[float(v)for v in np.unique(av[...,3])],allRGBfinite=bool(np.isfinite(av[...,:3]).all()),negativeRGBpixels=int(np.any(av[...,:3]<0,axis=-1).sum()),overrangeRGBpixels=int(np.any(av[...,:3]>65504,axis=-1).sum()))
 measured=dict(status='INDEPENDENT_EXACT_FROZEN_METRIC_REPRODUCTION',metrics=metrics,DC_beta=coefs,independent_rank1_vs_producer_abs_errors=coef_errors,raw_output_repeats=repeat,STD_ratios=ratios,all_values_are_saved_constructed_or_measured=True,quality_accepted=False)
 save('metric_reproduction.json',measured)
 for r in records.values():verify(r)
 result=dict(status='PASSED_CLEAN_COMPOSITION_EVIDENCE_AND_EXACT_METRIC_REVIEW',blocking_findings=[],
  prereview=ident(PRE_REVIEW/'review.json'),prereview_seal=ident(PRE_REVIEW/'completion_manifest_final.json'),root_authorization=ident(auth),root_tool_observations=ident(obs),
  producer_execution=ident(PREP/'execution_results.json'),producer_metrics=ident(PREP/'composition_metrics.json'),producer_NPZ=ident(PREP/'composed_sequences.npz'),independent_metrics=ident(HERE/'metric_reproduction.json'),
  actual_counts=dict(helper_children=192,explicit_helper_shader_dispatches=192,postfence_proofs=192,metadata_accepted=192,completed_accepted=192,observed_all3_replays=64,retained_outputs=576,new_native_contexts=0,new_native_API=0),
  source_records_checked_pre_post=len(records),runtime_records=len(runtime_records),case_evidence=cases,guard=dict(all_direct_returned_equal_stored=True,positive_PID_all=True,distinct_PID_count=len(set(pids)),ordinary_D3D_errors=0,ordinary_D3D_warnings=0,stderr_all_empty=True,unknown_total_jobs=0,terminated_children=0,
  maximum_child_WS=max(r['guard']['peak_observed_working_set_bytes']for r in run['jobs']),minimum_available_memory=min(r['guard']['minimum_observed_available_bytes']for r in run['jobs'])),
  exact_reconstruction=dict(all64_observed3UAV_replays_bitexact=True,observed_RGB_equals_oldB=True,C0_C1_all3_UAV_bits_exact=True,NPZ_actual_output_bits_exact=True,all9x2refx4window_frozen_metrics_exact=True,oldB_four_windows_exact=True,independent_rank1_max_error=max(max(v.values())for v in coef_errors.values()),beta_DC_gain_phase_and_STD_ratios_verified=True),
  output_diagnostics=descriptive,conclusion='Composed genuine clean-input SDK response is reproducible across C0/C1 under this frozen weak-material graph. Very low temporal noise coexists with failed absolute detail gain against raw constructed and raw-quantized references. This does not identify the opaque SDK/camera/guide/conversion mechanism or establish game quality.',
  qualification=['192 source-qualified helper shader dispatches are separate from SDK calls; new SDK/native0 in this composition run. Source reading plus pinned historical helperEXE is not new compilation linkage proof.',
  'Original observed replay matches all3 buffers eachframe before clean arms. Cadence change is controlled by measured replay, not assumed.',
  'Truth is constructed fixture radiance; quantized_raw_reference is actual raw FP16 input proxy. Neither is a separately measured physical clean target or a native quality oracle.',
  'Signed rank1 beta gain/phase is an algebraic observation. Tclean gain bias cannot uniquely attribute source packing, albedo demod/remod, composition, native transfer/history or common bias.',
  'Source footer/helper timing proves explicit helper work postfence; output sizes alone do not. Acceptance/report counts are independently separated.',
  'Root original frozen analyzer ran once after accepted192. Reviewer re-executes only frozen score AST on saved arrays and does not launch original analyzer/helper/native/build.'],
  actual_review=dict(GPU=0,native=0,build=0,device_query=0,models=0,threshold_changes=0),quality_accepted=False)
 save('review.json',result)
 summary={}
 for name in('C0','C1','oldB','oldTP','quantized_raw_reference'):
  summary[name]={ref:{label:dict(gain_min=m['absolute_gain_min'],gain_mean=m['absolute_gain_mean'],gain_max=m['absolute_gain_max'],phase_max=m['absolute_phase_max'],detail_pass=m['detail_within_5_percent_all_frames'],temporal_STD=m['score']['residual_temporal_std'],gain_failing_frames=m['absolute_gain_failing_frames'],phase_failing_frames=m['absolute_phase_failing_frames'])for label,m in metrics[name][ref].items()}for ref in('raw_constructed_truth','quantized_raw_reference')}
 bias=np.asarray(coefs['C0']['comparisons']['raw_constructed_truth']['DC_bias_per_frame_RGB'])
 save('compact.json',dict(status=result['status'],blocking_findings=[],actual_counts=result['actual_counts'],source_records=len(records),all_metrics_exact=True,C0_C1_all3_bits_exact=True,summary=summary,C0_mature_interior_RGB_DC_bias_to_rawtruth=bias[-16:].mean(0).tolist(),C0_STD_ratio_to_oldB=ratios['C0'],quality_accepted=False,interpretation=result['conclusion'],producer_metrics=ident(PREP/'composition_metrics.json')))
 for r in records.values():verify(r)
 files=[ident(p)for p in sorted(HERE.iterdir())if p.is_file()]
 save('completion_manifest.json',dict(status='SEALED_PASSED_CLEAN_COMPOSITION_POSTREVIEW',files=files,external_sources=list(records.values()),self_entry_excluded=True,actual_GPU_native_build=0))
 print(json.dumps(dict(status=result['status'],sources=len(records),review=ident(HERE/'review.json'),compact=ident(HERE/'compact.json'),metrics=ident(HERE/'metric_reproduction.json'),manifest=ident(HERE/'completion_manifest.json'))))
if __name__=='__main__':main()
