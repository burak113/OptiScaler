"""CPU-only postreview: two physical helper observations and unchanged saved-array metrics."""
from pathlib import Path
import ast,hashlib,importlib.util,json,sys,types
import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;PREP=HERE.parent/'fsrd_weak_material_clean_roundtrip_preparation_20260930';PRE=HERE.parent/'fsrd_weak_material_clean_roundtrip_prelaunch_review_20260930'
def read(p):return json.loads(Path(p).read_text())
def ident(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())
def check(r):
 a=ident(r['path']);assert(a['bytes'],a['sha256'])==(r['bytes'],r['sha256']),r['path'];return a
def save(n,v):
 with(HERE/n).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def module(n,p):s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 assert not(HERE/'review.json').exists(),'Preserve prior attempt'
 assert ident(PRE/'review.json')['sha256']=='39ba2d5853b476c3041e88b27815a998483c6b97aff98a6de678facdfae65271'
 assert ident(PRE/'completion_manifest.json')['sha256']=='5b64437dfb16dcc1d7e5b07b5654926725c49ae40e2fe50b633bb5cbe2e8388d'
 old=read(PRE/'completion_manifest.json');records={r['path']:r for r in old['external_sources']}
 for r in old['files']+old['external_sources']:check(r);records[r['path']]=ident(r['path'])
 records[str(PRE/'completion_manifest.json')]=ident(PRE/'completion_manifest.json')
 pins={'execution_results.json':'94b31ae3f743ec3d18b4110d4888f49a29a2ede350f4405215a3514ea6ffa6eb','roundtrip_metrics.json':'60d2356cca68e9f371ed695fee8b0b1da22f1b569775433ce8f16bc8e6e1d52c','roundtrip_sequences.npz':'6e15a70ba21e27d7fc0cf75ea1ec3337e5f4058856a016096196108c9c8585a2'}
 for n,h in pins.items():assert ident(PREP/n)['sha256']==h;records[str(PREP/n)]=ident(PREP/n)
 auth=HERE.parent/'fsrd_clean_roundtrip_root_authorization_20260930.json';assert ident(auth)['sha256']=='3d649c84b3478f89d90199ddcdefeeb70b865eeb8c98a27101d74591a760cf4f';records[str(auth)]=ident(auth)
 tool=HERE.parent/'fsrd_clean_roundtrip_root_tool_observations_20260930.json';assert tool.is_file(),'Wait for root tool-observations supplement before final review';assert ident(tool)['sha256']=='48bce8e159824933251360ee20f71dd9d48ead2fa589c906385f7d801d233ddb';records[str(tool)]=ident(tool)
 reg=read(PREP/'registration.json');run=read(PREP/'execution_results.json');producer=read(PREP/'roundtrip_metrics.json')
 assert run['status']=='completed_roundtrip_only_awaiting_independent_review_not_quality_accepted'and producer['execution_sha256']==pins['execution_results.json']
 assert [(r['frame'],r['arm'])for r in run['jobs']]==[(0,'R0'),(0,'R1')]
 assert not run['actual_new_native_contexts']and not run['actual_new_native_API']
 assert run['environment']['TMP']==run['environment']['TEMP']==str((PREP/'execution_TEMP').resolve())and run['environment']['OPENBLAS_NUM_THREADS']=='1'
 law=module('roundtrip_post_law',PREP/'helper_work_accounting.py');loader=module('roundtrip_post_guard',PREP/'helper_guard_evidence.py')
 raw={};evidence=[]
 for job,row in zip(reg['jobs'],run['jobs']):
  folder=Path(job['job']).parent;guard,error,artifact=loader.load_guard_best_effort(folder,row['guard_artifact']['returned_guard_claim'],None)
  assert error is None and guard==row['guard']and artifact==row['guard_artifact']and artifact['authority']=='direct_returned_guard'and not artifact['returned_stored_conflict']
  assert guard['status']=='completed'and guard['returncode']==0 and type(guard['child_pid'])is int and guard['child_pid']>0 and guard['args']==job['command']and not guard['terminated_owned_child']
  assert guard['timeout_seconds']==240 and guard['maximum_working_set_bytes']==2147483648 and guard['minimum_available_memory_bytes']==1073741824 and guard['sample_interval_seconds']==.2
  work=law.accounting(folder,job['outputs'],guard,None,fresh_scope_authenticated=True);assert work==row['work']and work['metadata_accepted']and row['metadata_accepted']and row['completed_accepted']
  assert work['confirmed_helper_children_lower_bound']==work['exact_helper_child_total']==work['confirmed_shader_dispatches_lower_bound']==work['confirmed_fence_completions_lower_bound']==work['exact_shader_dispatch_total']==1
  assert work['explicit_post_fence_stdout_proof']and not work['partial_dispatch_total_unknown']and not work['evidence_conflicts']and work['fields']['diagnostic']==dict(errors=0,warnings=0)
  assert work['fields']['timing']['debug_layer']==1 and (folder/'stderr.log').read_bytes()==b''
  for n in('resource_guard.json','stdout.log','stderr.log'):records[str(folder/n)]=ident(folder/n)
  raw[job['arm']]=[]
  for i,o in enumerate(job['outputs']):
   p=Path(o['path']);assert p.stat().st_size==o['bytes']and ident(p)['sha256']==work['outputs'][i]['sha256'];records[str(p)]=ident(p)
   raw[job['arm']].append(np.fromfile(p,'<f2'if i<2 else'<u4').reshape(80,128,4))
  assert np.isfinite(raw[job['arm']][0][...,:3]).all()
  evidence.append(dict(arm=job['arm'],PID=guard['child_pid'],guard_direct_equals_stored=True,postfence_marker_sourcequalified=True,helper_shader_counts_each1=True,metadata_accepted=True,all3_raw_sizes_hashes_verified=True,stderr_empty=True,debug_errors_warnings0=True))
 for k in('executor_job_invocations_started','helper_children_lower_bound','confirmed_shader_dispatches_lower_bound','confirmed_fence_completions_lower_bound','exact_helper_total','exact_shader_dispatch_total','metadata_accepted_jobs','completed_accepted_jobs'):assert run[k]==2
 repeats={f'out{i}':dict(full_serialized_bits_exact=bool(np.array_equal(raw['R0'][i].view('<u2')if i<2 else raw['R0'][i],raw['R1'][i].view('<u2')if i<2 else raw['R1'][i])),RGB_bits_exact=bool(np.array_equal(raw['R0'][i][...,:3].view('<u2')if i<2 else raw['R0'][i][...,:3],raw['R1'][i][...,:3].view('<u2')if i<2 else raw['R1'][i][...,:3])),alpha_bits_exact=bool(np.array_equal(raw['R0'][i][...,3].view('<u2')if i<2 else raw['R0'][i][...,3],raw['R1'][i][...,3].view('<u2')if i<2 else raw['R1'][i][...,3])))for i in range(3)}
 assert repeats==producer['all3_repeat_bits']and all(r['full_serialized_bits_exact']for r in repeats.values())
 with np.load(PREP/'roundtrip_sequences.npz')as z:
  assert set(z.files)=={'R0_actual_one_frame','R1_actual_one_frame'}
  for arm in('R0','R1'):assert np.array_equal(z[arm+'_actual_one_frame'].view('<u2'),raw[arm][0].view('<u2'))
 scope={'np':np}
 for item in reg['metric_function_extraction']:
  p=Path(item['source']);node=next(n for n in ast.parse(p.read_text()).body if isinstance(n,(ast.FunctionDef,ast.Assign))and((isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets))))
  if item['name']=='moments':scope['ref']=types.SimpleNamespace(score=scope['score'])
  if item['name']=='detail':scope['helper']=types.SimpleNamespace(moments=scope['moments'])
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope)
 with np.load(reg['source_sequences']['path'])as z:truth=z['clean_reference'].copy();B=z['baseline'].copy()
 assert all(truth[f].tobytes()==truth[0].tobytes()for f in range(64))
 q4=np.fromfile(reg['quantized_raw_reference']['path'],'<f2').reshape(80,128,4);q=q4[None,...,:3].astype('<f4')
 colors={a:raw[a][0][None,...,:3].astype('<f4')for a in raw};scores={a:{ref:scope['detail'](v,r)for ref,r in[('raw_constructed_truth',truth[:1]),('quantized_raw_reference',q)]}for a,v in colors.items()}
 assert scores==producer['single_frame_frozen_scores']
 assert all(np.array_equal(raw[a][0][...,:3].view('<u2'),q4[...,:3].view('<u2'))for a in raw)
 y,x=np.indices((80,128));phi=np.where((x-y)%2==0,1.,-1.);roi=phi[5:-5,5:-5];roi=roi-roi.mean();norm=np.sum(roi*roi)
 def coefficients(v):
  a=v[:,5:-5,5:-5].astype('float64');dc=a.mean((1,2));beta=np.einsum('hw,nhwc->nc',roi,a-dc[:,None,None])/norm
  return dict(interior_DC_RGB=dc.tolist(),signed_Nyquist_beta_RGB=beta.tolist())
 coef={n:coefficients(v)for n,v in{**colors,'raw_constructed_truth_single':truth[:1],'quantized_raw_single':q}.items()};assert coef==producer['single_frame_coefficients']
 delta={}
 for a,v in colors.items():
  d=v.astype('float64')-q.astype('float64');delta[a]=dict(operation='Actual single-frame GPU R minus encodedraw q; converter+composition roundtrip contrast',RGB_RMS=float(np.sqrt(np.mean(d*d))),RGB_max_abs=float(np.max(np.abs(d))),signed_interior_DC_RGB=(np.asarray(coef[a]['interior_DC_RGB'])-np.asarray(coef['quantized_raw_single']['interior_DC_RGB'])).tolist(),signed_Nyquist_beta_RGB=(np.asarray(coef[a]['signed_Nyquist_beta_RGB'])-np.asarray(coef['quantized_raw_single']['signed_Nyquist_beta_RGB'])).tolist())
 assert delta==producer['R_minus_encoded_raw']
 sdk=producer['SDK_static_reference_comparison'];assert sdk['eligible']and sdk['reference_is_static_not_measured_series']and sdk['reference_physical_observations']==2 and sdk['reference_independent_temporal_samples']==0
 with np.load(reg['prior_composed_sequences']['path'])as z:T={a:z[a][...,:3].astype('<f4')for a in('C0','C1')}
 reference=np.broadcast_to(colors['R0'],truth.shape);quantized=np.broadcast_to(q,truth.shape);windows=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]
 oldrow=next(v for v in read(reg['original_report']['path'])['rows']if v['scene']=='weak_material')
 for label,sl in windows:assert scope['detail'](B[sl],truth[sl])==oldrow['baseline_metrics'][label]
 Tscores={a:{r:{label:scope['detail'](v[sl],ref[sl])for label,sl in windows}for r,ref in[('raw_constructed_truth',truth),('quantized_raw_reference',quantized)]}for a,v in T.items()};assert Tscores==sdk['historical_measured64_T_scores']
 Tdelta={}
 for a,v in T.items():
  d=v.astype('float64')-reference.astype('float64');c=coefficients(v);r=coefficients(reference)
  Tdelta[a]=dict(operation='Prior actual64 SDK+composition T minus static GPU-roundtrip reference; source/process/context qualified',measured_T_frames=64,static_R_graphs=1,R_RGB_RMS_per_T_frame=np.sqrt(np.mean(d*d,axis=(1,2,3))).tolist(),signed_DC_per_T_frame_RGB=(np.asarray(c['interior_DC_RGB'])-np.asarray(r['interior_DC_RGB'])).tolist(),signed_Nyquist_beta_per_T_frame_RGB=(np.asarray(c['signed_Nyquist_beta_RGB'])-np.asarray(r['signed_Nyquist_beta_RGB'])).tolist())
 assert Tdelta==sdk['directional_T_minus_static_R']
 reproduction=dict(status='EXACT_SINGLE_OBSERVATION_FROZEN_METRIC_AND_DIRECTIONAL_REPRODUCTION',single_frame_scores=scores,single_coefficients=coef,R_minus_encoded_raw=delta,repeat_bits=repeats,historical_measured64_T_scores=Tscores,T_minus_static_R=Tdelta,actual_roundtrip_observations=2,roundtrip_temporal_samples=0,quality_accepted=False)
 save('metric_reproduction.json',reproduction)
 for r in records.values():check(r)
 result=dict(status='PASSED_CLEAN_ROUNDTRIP_EVIDENCE_AND_EXACT_SINGLETON_METRIC_REVIEW',blocking_findings=[],source_records_checked_pre_post=len(records),prelaunch=ident(PRE/'review.json'),prelaunch_seal=ident(PRE/'completion_manifest.json'),root_authorization=ident(auth),root_tool_observations=ident(tool),producer_execution=ident(PREP/'execution_results.json'),producer_metrics=ident(PREP/'roundtrip_metrics.json'),producer_NPZ=ident(PREP/'roundtrip_sequences.npz'),metric_reproduction=ident(HERE/'metric_reproduction.json'),
 actual_counts=dict(helper_children=2,explicit_helper_shader_dispatches=2,postfence_proofs=2,metadata_accepted=2,retained_outputs=6,new_native_API=0,new_native_contexts=0),cases=evidence,
 matches=dict(all3_R0_R1_fullbits_exact=True,NPZ_actual_one_frame_RGBA_bits_exact=True,R_color_RGB_bits_exact_encodedraw=True,singleton_scores_exact=True,independent_signed_Nyquist_DC_beta_exact=True,R_minus_q_zero=True,historicalT64_scores_and_T_minus_staticR_exact=True),
 actual_review=dict(GPU=0,native=0,build=0,devicequery=0,model=0,threshold_changes=0),quality_accepted=False,
 qualifications=['Measured R0/R1 are two single-graph helper observations, not64 measured roundtrip frames. Frozen N1 temporal fields are noninferential; no duplicatedR64 temporal noise estimate.',
 'Raw encoded input quantization versus constructedtruth is separate from actual converter+composition roundtrip. Measured R RGB exactly equals encodedraw under these settings.',
 'T-R is prior measured SDK path plus composition response against static roundtrip reference. DestinationAlpha differs from converterAlpha; actualCSO alpha-invariance not isolated by this run, so no pure intrinsic SDK-only RGB cause claim.',
 'Allthreeoutputbytes retained. Auxiliary UAV repeatbytes do not prove shader historywrites when WriteHistory0. Native/RGB sourcefastpath interpretation remains source/CSO provenance qualified.',
 'Helper postfence timing/source contract and positive child guard prove2explicit helper shaderdispatches. This review launches0helpers/SDK/build; current SDKtotal unchanged.',
 'Exact scalar/phase/detail comparisons are bounded to constructed weakchecker fixture. Neither physical clean truth nor general game-quality/cause proof is established.'])
 save('review.json',result)
 mature=Tscores['C0']['raw_constructed_truth']['mature'];matureq=Tscores['C0']['quantized_raw_reference']['mature']
 save('compact.json',dict(status=result['status'],blocking_findings=[],actual_counts=result['actual_counts'],source_records=len(records),R0_R1_all3_bits_exact=True,R_RGB_exact_encodedraw=True,R_vs_q=scores['R0']['quantized_raw_reference'],R_vs_constructedtruth=scores['R0']['raw_constructed_truth'],T_mature_gain_rawtruth=mature['absolute_gain_mean'],T_mature_gain_quantizedraw=matureq['absolute_gain_mean'],T_mature_detail_pass=mature['detail_within_5_percent_all_frames'],Rminusq=delta['R0'],physical_R_observations=2,R_temporal_independent_samples=0,quality_accepted=False,interpretation='Converter+composition roundtrip reproduces encodedraw RGB exactly. Prior measuredT response retains weakdetail gain bias beyond rawquantization; stage attribution is SDK+downstream/alpha/context qualified, not a purified intrinsic SDKcause.'))
 for r in records.values():check(r)
 files=[ident(p)for p in sorted(HERE.iterdir())if p.is_file()]
 save('completion_manifest.json',dict(status='SEALED_PASSED_CLEAN_ROUNDTRIP_POSTREVIEW',files=files,external_sources=list(records.values()),self_entry_excluded=True,actual_GPU_native_build=0))
 print(json.dumps(dict(status=result['status'],sources=len(records),review=ident(HERE/'review.json'),compact=ident(HERE/'compact.json'),metrics=ident(HERE/'metric_reproduction.json'),manifest=ident(HERE/'completion_manifest.json'))))
if __name__=='__main__':main()
