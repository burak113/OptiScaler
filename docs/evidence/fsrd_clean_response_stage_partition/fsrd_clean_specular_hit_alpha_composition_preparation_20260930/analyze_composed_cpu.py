"""Future saved composed outputs only; no model or native/helper process. Frozen score AST."""
from pathlib import Path
import ast,types,json,hashlib,itertools
import numpy as np
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,o):
 with Path(p).open('x',encoding='utf-8',newline='\n')as f:json.dump(o,f,indent=2,allow_nan=False);f.write('\n')
def main():
 target=HERE/'composition_metrics.json';assert not target.exists()and not(HERE/'composed_sequences.npz').exists(),'Preserve prior CPU analysis'
 reg=json.loads((HERE/'registration.json').read_text());run=json.loads((HERE/'execution_results.json').read_text())
 assert run['status']=='completed_composition_only_awaiting_independent_review_not_quality_accepted'and run['completed_accepted_jobs']==192 and run['observed_replay_accepted_frames']==0
 for r in reg['metric_source_records']:assert Path(r['path']).stat().st_size==r['bytes']and sha(r['path'])==r['sha256']
 scope={'np':np}
 for item in reg['metric_function_extraction']:
  source=Path(item['source']);node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,(ast.FunctionDef,ast.Assign))and((isinstance(n,ast.FunctionDef)and n.name==item['name'])or(isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id==item['name']for t in n.targets))))
  if item['name']=='moments':scope['ref']=types.SimpleNamespace(score=scope['score'])
  if item['name']=='detail':scope['helper']=types.SimpleNamespace(moments=scope['moments'])
  exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
 detail=scope['detail'];arrays={};raw_arrays={}
 for arm in('A0_r0', 'A10_r0', 'A0_r1'):
  jobs=[j for j in reg['jobs']if j['arm']==arm];assert [j['frame']for j in jobs]==list(range(64))
  raw_arrays[arm]=[np.stack([np.fromfile(j['outputs'][i]['path'],'<f2'if i<2 else'<u4').reshape(80,128,4)for j in jobs])for i in range(3)]
  arrays[arm]=raw_arrays[arm][0][...,:3].astype('<f4')
 with np.load(reg['source_sequences']['path'])as z:
  truth=z['clean_reference'].copy();baseline=z['baseline'].copy();pilot_response=z['pilot_response'].copy();observed=z['observed'].copy();pilot=z['pilot'].copy()
 q=np.fromfile(reg['quantized_raw_reference']['path'],'<f2').reshape(80,128,4).astype('<f4')[...,:3];quantized=np.broadcast_to(q,truth.shape)
 windows=[('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]
 original=json.loads(Path(reg['original_report']['path']).read_text());oldrow=next(x for x in original['rows']if x['scene']=='weak_material')
 # Reconfirm exact unchanged oldB scorer before computing new response metrics.
 for label,sl in windows:assert detail(baseline[sl],truth[sl])==oldrow['baseline_metrics'][label]
 values=dict(raw_constructed_truth=truth,quantized_raw_reference=quantized,oldB=baseline,oldTP=pilot_response,old_observed=observed,old_pilot=pilot,**arrays)
 metrics={}
 for name,value in values.items():
  metrics[name]={refname:{label:detail(value[sl],ref[sl])for label,sl in windows}for refname,ref in [('raw_constructed_truth',truth),('quantized_raw_reference',quantized)]}
 y,x=np.indices((80,128));phi=np.exp(2j*np.pi*(64*(x-63.5)/128-40*(y-39.5)/80)).real;phi-=phi[5:-5,5:-5].mean();roi=phi[5:-5,5:-5];norm=np.sum(roi**2)
 coefficients={}
 for name,value in values.items():
  a=value[:,5:-5,5:-5].astype('float64');dc=a.mean((1,2));beta=np.einsum('hw,nhwc->nc',roi,a-dc[:,None,None])/norm
  coefficients[name]=dict(interior_DC_per_frame_RGB=dc.tolist(),full_DC_per_frame_RGB=value.astype('float64').mean((1,2)).tolist(),signed_Nyquist_beta_per_frame_RGB=beta.tolist())
 for name,record in coefficients.items():
  record['comparisons']={}
  for refname in('raw_constructed_truth','quantized_raw_reference'):
   d=np.asarray(record['interior_DC_per_frame_RGB'])-np.asarray(coefficients[refname]['interior_DC_per_frame_RGB']);beta=np.asarray(record['signed_Nyquist_beta_per_frame_RGB']);r=np.asarray(coefficients[refname]['signed_Nyquist_beta_per_frame_RGB'])
   record['comparisons'][refname]=dict(DC_bias_per_frame_RGB=d.tolist(),signed_beta_bias_per_frame_RGB=(beta-r).tolist(),signed_beta_gain_per_frame_RGB=(beta/r).tolist(),rank1_sign_phase_error_per_frame_RGB=np.where(beta*r>=0,0,np.pi).tolist())
 repeats={}
 for left,right in itertools.combinations(('A0_r0', 'A10_r0', 'A0_r1'),2):
  pair={}
  for i in range(3):
   a=raw_arrays[left][i];b=raw_arrays[right][i];d=a.astype('float64')-b.astype('float64')
   pair[f'out{i}']=dict(full_serialized_bits_exact=bool(np.array_equal(a.view('<u2')if i<2 else a,b.view('<u2')if i<2 else b)),RGB_bits_exact=bool(np.array_equal(a[...,:3].view('<u2')if i<2 else a[...,:3],b[...,:3].view('<u2')if i<2 else b[...,:3])),alpha_bits_exact=bool(np.array_equal(a[...,3].view('<u2')if i<2 else a[...,3],b[...,3].view('<u2')if i<2 else b[...,3])),RGBA_RMS=float(np.sqrt(np.mean(d*d))),RGB_RMS=float(np.sqrt(np.mean(d[...,:3]**2))))
  repeats[left+'__'+right]=pair
 prior_reg=json.loads(Path(reg['prior_composition_registration']['path']).read_text());sealed=json.loads(Path(reg['prior_composition_final_seal']['path']).read_text())
 pinmap={r['path'].lower():r for r in sealed['files']+sealed['external_records']};prior_raw={}
 for oldarm in('C0','C1'):
  oldjobs=[j for j in prior_reg['jobs']if j['arm']==oldarm];assert [j['frame']for j in oldjobs]==list(range(64));prior_raw[oldarm]=[]
  for i in range(3):
   for j in oldjobs:
    pp=Path(j['outputs'][i]['path']);rr=pinmap[str(pp.resolve()).lower()];assert pp.stat().st_size==rr['bytes']and sha(pp)==rr['sha256']
   prior_raw[oldarm].append(np.stack([np.fromfile(j['outputs'][i]['path'],'<f2'if i<2 else'<u4').reshape(80,128,4)for j in oldjobs]))
 for arm in('A0_r0', 'A10_r0', 'A0_r1'):
  for oldarm in('C0','C1'):
   repeats[arm+'__prior_'+oldarm]={f'out{i}':dict(full_serialized_bits_exact=bool(np.array_equal(a.view('<u2')if i<2 else a,b.view('<u2')if i<2 else b)),RGB_bits_exact=bool(np.array_equal(a[...,:3].view('<u2')if i<2 else a[...,:3],b[...,:3].view('<u2')if i<2 else b[...,:3])),alpha_bits_exact=bool(np.array_equal(a[...,3].view('<u2')if i<2 else a[...,3],b[...,3].view('<u2')if i<2 else b[...,3])))for i,(a,b)in enumerate(zip(raw_arrays[arm],prior_raw[oldarm]))}
 np.savez_compressed(HERE/'composed_sequences.npz',**{arm:raw_arrays[arm][0]for arm in raw_arrays},raw_constructed_truth=truth,quantized_raw_reference=quantized)
 STD_ratios={arm:{reference:{window:(metrics[arm][reference][window]['score']['residual_temporal_std']/metrics['oldB'][reference][window]['score']['residual_temporal_std']if metrics['oldB'][reference][window]['score']['residual_temporal_std']else None)for window,_ in windows}for reference in('raw_constructed_truth','quantized_raw_reference')}for arm in('A0_r0', 'A10_r0', 'A0_r1')}
 result=dict(status='completed_CPU_composed_clean_response_measurement_not_quality_accepted',execution_results_sha256=sha(HERE/'execution_results.json'),metrics=metrics,DC_beta=coefficients,raw_output_repeats=repeats,descriptive_STD_ratio_to_oldB=STD_ratios,frozen_oldB_four_windows_exact=True,source_frame_indices=list(range(64)),scorer_unchanged=True,scored_values9=True,actual_composed_traces3=True,excluded_A10_r1_not_measured=True,new_native_API_GPU=0,quality_accepted=False,game_run=False,limits=reg['limitations'])
 save(target,result)
if __name__=='__main__':main()
