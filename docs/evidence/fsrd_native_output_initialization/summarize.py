from pathlib import Path
import hashlib,json
import numpy as np
HERE=Path(__file__).resolve().parent;DEST=HERE/'evidence';target=HERE/'output_completeness_summary.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if target.exists():raise ValueError('Preserve summary')
report_path=DEST/'results.json';r=json.loads(report_path.read_text());assert r['completed_native_contexts']==12 and r['native_RR_calls']==768
row=r['rows'][0];summary={'schema':'external-output-initialization-descriptive-summary-v1','quality_accepted':False,
 'report_sha256':sha(report_path),'native_contexts_already_counted':12,'new_native_contexts':0,
 'modes':{},'all_sentinel_component_matches':0,'all_rgba_finite':True,'pairs':{}}
sentinel=np.array([257,513,769,17],'<f2');inputs=row['contexts']['round0_mode0']['inputs'];controls=row['contexts']['round0_mode0']['applied_dispatch_sha256']
for tag,identity in row['contexts'].items():
 assert identity['inputs']==inputs and identity['applied_dispatch_sha256']==controls
 info={}
 for name in ('diffuse.bin','specular.bin'):
  p=DEST/'wave'/tag/name;assert sha(p)==identity['outputs'][name]
  a=np.fromfile(p,'<f2').reshape(64,80,128,4);finite=bool(np.isfinite(a).all());summary['all_rgba_finite']&=finite
  matches=np.sum(a==sentinel,axis=(0,1,2));summary['all_sentinel_component_matches']+=int(matches.sum())
  info[name]={'sha256':sha(p),'minimum_RGBA':a.min(axis=(0,1,2)).astype(float).tolist(),
   'maximum_RGBA':a.max(axis=(0,1,2)).astype(float).tolist(),'sentinel_matches_RGBA':matches.tolist(),
   'output_alpha_all_zero':bool(np.all(a[...,3]==0)),'finite':finite}
 summary['modes'][tag]=info
for mode in range(6):
 key=f'round0_mode{mode}__round1_mode{mode}';reverse=f'round1_mode{mode}__round0_mode{mode}'
 pair=row['comparisons'].get(key,row['comparisons'].get(reverse));assert pair is not None
 summary['pairs'][f'mode{mode}_repeats']={name:{'bytes_exact':v['bytes_exact'],'RGB_RMS':v['RGB']['rms'],'max_abs_RGB':v['RGB']['max_abs']}for name,v in pair.items()}
for a,b in [(f'round{round}_mode1',f'round{round}_mode{mode}')for round in range(2)for mode in range(2,6)]:
 pair=row['comparisons'].get(a+'__'+b,row['comparisons'].get(b+'__'+a));assert pair is not None
 summary['pairs'][a+'__'+b]={name:{'bytes_exact':v['bytes_exact'],'RGB_RMS':v['RGB']['rms'],'max_abs_RGB':v['RGB']['max_abs']}for name,v in pair.items()}
summary['limitations']=['Raw output lifecycle intervention with two repeats per mode; no calibrated population or determinism claim',
 'Zero sentinel survival is only observed pixel/channel completeness, not proof no transient read or internal uninitialized state',
 'Output initialization and UAV barrier/heap allocation may change execution; bound-heap no-clear control remains explicit',
 'No causal attribution of game stain or acceptance of new runner as production harness']
summary['status']='completed_raw_completeness_diagnostic_not_solution';summary['script_sha256']=sha(Path(__file__))
target.write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'sentinel_matches':summary['all_sentinel_component_matches'],'all_finite':summary['all_rgba_finite'],
 'pair_summary':summary['pairs'],'summary_sha256':sha(target)},indent=2))
