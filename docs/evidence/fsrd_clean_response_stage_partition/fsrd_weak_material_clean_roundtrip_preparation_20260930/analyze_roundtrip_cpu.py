"""Future saved-output analysis only; two actual single-frame R observations, no launcher/model."""
from pathlib import Path
import argparse,ast,hashlib,itertools,json,types
import numpy as np
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--analyze-roundtrip',action='store_true',required=True);p.parse_args()
 target=HERE/'roundtrip_metrics.json';assert not target.exists()and not(HERE/'roundtrip_sequences.npz').exists(),'Preserve previous analysis'
 reg=json.loads((HERE/'registration.json').read_text());run=json.loads((HERE/'execution_results.json').read_text());proof=json.loads((HERE/'graph_identity_proof.json').read_text())
 assert run['status']=='completed_roundtrip_only_awaiting_independent_review_not_quality_accepted'and run['completed_accepted_jobs']==2 and run['exact_shader_dispatch_total']==2
 assert proof['unique_complete_graphs']==1 and proof['raw_constructed_truth_all64_byte_identical']
 for r in reg['metric_source_records']+[reg['source_sequences'],reg['quantized_raw_reference'],reg['prior_composed_sequences'],reg['prior_composed_metrics'],reg['original_report']]:
  assert Path(r['path']).stat().st_size==r['bytes']and sha(r['path'])==r['sha256']
 scope={'np':np}
 for item in reg['metric_function_extraction']:
  source=Path(item['source']);node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,(ast.FunctionDef,ast.Assign))and((isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets))))
  if item['name']=='moments':scope['ref']=types.SimpleNamespace(score=scope['score'])
  if item['name']=='detail':scope['helper']=types.SimpleNamespace(moments=scope['moments'])
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
 detail=scope['detail'];raw={};colors={}
 for job in reg['jobs']:
  arm=job['arm'];raw[arm]=[np.fromfile(o['path'],'<f2'if i<2 else'<u4').reshape(80,128,4)for i,o in enumerate(job['outputs'])]
  colors[arm]=raw[arm][0][None,...,:3].astype('<f4');assert np.isfinite(colors[arm]).all()
 with np.load(reg['source_sequences']['path'])as z:truth=z['clean_reference'].copy();baseline=z['baseline'].copy()
 assert all(truth[f].tobytes()==truth[0].tobytes()for f in range(64))
 q=np.fromfile(reg['quantized_raw_reference']['path'],'<f2').reshape(80,128,4).astype('<f4')[None,...,:3]
 single_scores={arm:{'raw_constructed_truth':detail(value,truth[:1]),'quantized_raw_reference':detail(value,q)}for arm,value in colors.items()}
 repeats={f'out{i}':dict(full_serialized_bits_exact=bool(np.array_equal(raw['R0'][i].view('<u2')if i<2 else raw['R0'][i],raw['R1'][i].view('<u2')if i<2 else raw['R1'][i])),RGB_bits_exact=bool(np.array_equal(raw['R0'][i][...,:3].view('<u2')if i<2 else raw['R0'][i][...,:3],raw['R1'][i][...,:3].view('<u2')if i<2 else raw['R1'][i][...,:3])),alpha_bits_exact=bool(np.array_equal(raw['R0'][i][...,3].view('<u2')if i<2 else raw['R0'][i][...,3],raw['R1'][i][...,3].view('<u2')if i<2 else raw['R1'][i][...,3])))for i in range(3)}
 all_exact=all(v['full_serialized_bits_exact']for v in repeats.values())
 y,x=np.indices((80,128));phi=np.exp(2j*np.pi*(64*(x-63.5)/128-40*(y-39.5)/80)).real;phi-=phi[5:-5,5:-5].mean();roi=phi[5:-5,5:-5];norm=np.sum(roi**2)
 def coefficients(value):
  a=value[:,5:-5,5:-5].astype('float64');dc=a.mean((1,2));beta=np.einsum('hw,nhwc->nc',roi,a-dc[:,None,None])/norm
  return dict(interior_DC_RGB=dc.tolist(),signed_Nyquist_beta_RGB=beta.tolist())
 actual_coefficients={name:coefficients(v)for name,v in {**colors,'raw_constructed_truth_single':truth[:1],'quantized_raw_single':q}.items()}
 single_delta={}
 for arm,value in colors.items():
  d=value.astype('float64')-q.astype('float64');single_delta[arm]=dict(operation='Actual single-frame GPU R minus encodedraw q; converter+composition roundtrip contrast',RGB_RMS=float(np.sqrt(np.mean(d*d))),RGB_max_abs=float(np.max(np.abs(d))),signed_interior_DC_RGB=(np.asarray(actual_coefficients[arm]['interior_DC_RGB'])-np.asarray(actual_coefficients['quantized_raw_single']['interior_DC_RGB'])).tolist(),signed_Nyquist_beta_RGB=(np.asarray(actual_coefficients[arm]['signed_Nyquist_beta_RGB'])-np.asarray(actual_coefficients['quantized_raw_single']['signed_Nyquist_beta_RGB'])).tolist())
 sdk=dict(eligible=all_exact,reference_is_static_not_measured_series=True,reference_physical_observations=2,reference_independent_temporal_samples=0,reason='All3 R0/R1 bits exact plus all64 complete graph bytes equal required')
 if all_exact:
  with np.load(reg['prior_composed_sequences']['path'])as z:T={name:z[name][...,:3].astype('<f4')for name in('C0','C1')}
  reference=np.broadcast_to(colors['R0'],truth.shape);quantized=np.broadcast_to(q,truth.shape)
  windows=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]
  oldrow=next(v for v in json.loads(Path(reg['original_report']['path']).read_text())['rows']if v['scene']=='weak_material')
  for label,sl in windows:assert detail(baseline[sl],truth[sl])==oldrow['baseline_metrics'][label]
  sdk['historical_measured64_T_scores']={name:{r:{label:detail(value[sl],target_ref[sl])for label,sl in windows}for r,target_ref in [('raw_constructed_truth',truth),('quantized_raw_reference',quantized)]}for name,value in T.items()}
  sdk['directional_T_minus_static_R']={}
  for name,value in T.items():
   d=value.astype('float64')-reference.astype('float64');a=coefficients(value);base=coefficients(reference)
   sdk['directional_T_minus_static_R'][name]=dict(operation='Prior actual64 SDK+composition T minus static GPU-roundtrip reference; source/process/context qualified',measured_T_frames=64,static_R_graphs=1,R_RGB_RMS_per_T_frame=np.sqrt(np.mean(d*d,axis=(1,2,3))).tolist(),signed_DC_per_T_frame_RGB=(np.asarray(a['interior_DC_RGB'])-np.asarray(base['interior_DC_RGB'])).tolist(),signed_Nyquist_beta_per_T_frame_RGB=(np.asarray(a['signed_Nyquist_beta_RGB'])-np.asarray(base['signed_Nyquist_beta_RGB'])).tolist())
 np.savez_compressed(HERE/'roundtrip_sequences.npz',R0_actual_one_frame=raw['R0'][0],R1_actual_one_frame=raw['R1'][0])
 save(target,dict(status='completed_single_graph_two_actual_GPU_observations_stage_partition_not_quality_accepted',execution_sha256=sha(HERE/'execution_results.json'),actual_R_observations=2,actual_R_observation_shape=[80,128,4],
  single_frame_frozen_scores=single_scores,single_frame_coefficients=actual_coefficients,R_minus_encoded_raw=single_delta,all3_repeat_bits=repeats,SDK_static_reference_comparison=sdk,
  singleton_temporal_fields_noninferential=True,singleton_temporal_qualification='Unchanged frozen detail/score mathematically returns temporal fields on N1; these are not measured temporal variation,64 independent observations, confidence or variance estimates. No temporalstd result is computed over a duplicated R64 series.',
  scorer_unchanged=True,new_native_API_GPU=0,model_fitting=False,quality_accepted=False,game_run=False,limits=reg['limitations']))
if __name__=='__main__':main()
