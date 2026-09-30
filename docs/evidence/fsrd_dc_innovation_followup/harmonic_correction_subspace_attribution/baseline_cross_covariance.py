"""Independent descriptive cross covariance; does not score a projected candidate."""
from pathlib import Path
import hashlib,json
import numpy as np
from analyze import basis,temporal
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
target=HERE/'baseline_cross_covariance.json'
if target.exists():raise ValueError('Preserve cross covariance')
folders=[ROOT/'tools_tmp/native_continuous_harmonic_fresh_retry_20260930/evidence',ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence']
report={'schema':'harmonic-correction-baseline-error-cross-covariance-v1','quality_accepted':False,'new_candidate_scored':False,'rows':[],'sources':{}}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for folder in folders:
 report['sources'][str(folder/'results.json')]=sha(folder/'results.json')
 for row in json.loads((folder/'results.json').read_text())['rows']:
  path=folder/row['scene']/'sequences.npz';report['sources'][str(path)]=sha(path);assert sha(path)==row['sequences_sha256']
  with np.load(path)as z:
   d=(z['harmonic'].astype(float)-z['baseline'].astype(float))[:,5:-5,5:-5]
   b=(z['baseline'].astype(float)-z['clean_reference'].astype(float))[:,5:-5,5:-5]
  n,h,w,_=d.shape;dc=d.mean((1,2),keepdims=True);non=d-dc;atom=np.zeros_like(non)
  for i,r in enumerate(row['pilot_diagnostics']['frames']):
   Q,rank=basis(r['atom_frequencies'],h+10,w+10);v=non[i].reshape(h*w,3);atom[i]=(Q@(Q.T@v)).reshape(h,w,3)
  orth=non-atom;bb=b-b.mean((1,2),keepdims=True);windows={}
  for name,sl in [('full',slice(None)),('mature',slice(-16,None))]:
   comps=[temporal(v[sl])for v in (bb,atom,orth)]
   matrix=np.array([[np.mean(x*y)for y in comps]for x in comps])
   total=float(np.mean(sum(comps)**2));assert abs(total-matrix.sum())<1e-16
   windows[name]={'component_names':['baseline_nonDC_error','correction_atom','correction_orthogonal'],
    'covariance_matrix':matrix.tolist(),'actual_total_nonDC_error_temporal_variance':total,
    'identity_error':abs(total-float(matrix.sum()))}
  report['rows'].append({'scene':row['scene'],'windows':windows})
assert all(sha(Path(p))==v for p,v in report['sources'].items())
report['status']='completed_descriptive_covariance_not_quality';report['script_sha256']=sha(Path(__file__))
report['limitations']=['Reference enters scored residual only; no projected candidate or post-score parameter choice',
 'Error variance includes deterministic appearance and context changes, not solely noise',
 'Covariance allocation does not identify a causal noise percentage']
target.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'result_sha256':sha(target),'weak_mature':next(r for r in report['rows']if r['scene']=='weak_material')['windows']['mature']},indent=2))
