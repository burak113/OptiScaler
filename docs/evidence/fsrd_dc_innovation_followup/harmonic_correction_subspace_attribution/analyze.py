"""Descriptive source-derived subspace identity, not a new correction candidate."""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
FIRST=ROOT/'tools_tmp/native_continuous_harmonic_fresh_retry_20260930/evidence'
REST=ROOT/'tools_tmp/native_continuous_harmonic_remaining_20260930/evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def temporal(a):return a-a.mean(0,keepdims=True)
def covariance(xs):
 z=np.stack([temporal(x)for x in xs]);matrix=np.einsum('itxyc,jtxyc->ij',z,z,optimize=True)/np.prod(z.shape[1:])
 actual=float(np.mean(temporal(sum(xs))**2));error=abs(actual-float(matrix.sum()));assert error<1e-16
 return {'matrix':matrix.tolist(),'sum':float(matrix.sum()),'actual_total_variance':actual,'identity_error':error}
def basis(freqs,h,w):
 y,x=np.indices((h,w));pos=(x-(w-1)/2)/w;py=(y-(h-1)/2)/h;columns=[]
 for fx,fy in freqs:
  z=np.exp(2j*np.pi*(fx*pos+fy*py))[5:-5,5:-5]
  columns.extend([z.real-z.real.mean(),z.imag-z.imag.mean()])
 if not columns:return np.empty(((h-10)*(w-10),0)),0
 a=np.stack(columns,-1).reshape((h-10)*(w-10),-1)
 u,s,_=np.linalg.svd(a,full_matrices=False);rank=int(np.sum(s>64*np.finfo(float).eps*max(s[0],1)))
 return u[:,:rank],rank
def main():
 target=HERE/'results.json'
 if target.exists():raise ValueError('Preserve diagnostic')
 pairs=[(FIRST,json.loads((FIRST/'results.json').read_text())),(REST,json.loads((REST/'results.json').read_text()))]
 pins={str(HERE/'analyze.py'):sha(HERE/'analyze.py'),**{str(f/'results.json'):sha(f/'results.json')for f,_ in pairs}}
 out={'schema':'harmonic-correction-source-derived-subspace-attribution-v1','quality_accepted':False,
 'new_pilot_or_response':False,'new_native_contexts':0,'new_native_RR_calls':0,'source_pins':pins,'rows':[],
 'limitations':['Spatial projection is descriptive, not causal noise removal or scored candidate',
  'Source-fitted basis selection remains uncertain and need not span all true detail',
  'Changing bases can create temporal cross covariance; it is retained',
  'Reference used only for baseline scored residual, never basis or projection input']}
 # Freeze script and all array/report identities before computing any attribution.
 for folder,report in pairs:
  for row in report['rows']:
   p=folder/row['scene']/'sequences.npz';assert sha(p)==row['sequences_sha256'];pins[str(p)]=sha(p)
 (HERE/'pre_analysis_freeze.json').write_text(json.dumps(pins,indent=2)+'\n')
 for folder,report in pairs:
  for row in report['rows']:
   with np.load(folder/row['scene']/'sequences.npz')as s:
    delta=(s['harmonic'].astype(float)-s['baseline'].astype(float))[:,5:-5,5:-5]
    eb=(s['baseline'].astype(float)-s['clean_reference'].astype(float))[:,5:-5,5:-5]
   n,hh,ww,_=delta.shape;dc=np.broadcast_to(delta.mean((1,2),keepdims=True),delta.shape).copy();atom=np.zeros_like(delta)
   ranks=[];freq_records=[];orthogonality=[]
   for i,rec in enumerate(row['pilot_diagnostics']['frames']):
    freqs=rec['atom_frequencies'];q,rank=basis(freqs,hh+10,ww+10)
    ranks.append(rank);freq_records.append(freqs)
    centered=(delta[i]-dc[i]).reshape(hh*ww,3)
    atom[i]=(q@(q.T@centered)).reshape(hh,ww,3)
    orthogonality.append(float(np.max(abs(q.T@(centered-atom[i].reshape(hh*ww,3)))))if rank else 0.)
   orth=delta-dc-atom
   np.testing.assert_allclose(dc+atom+orth,delta,rtol=0,atol=2e-16)
   windows={}
   for name,sl in [('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]:
    parts=[dc[sl],atom[sl],orth[sl]];c=covariance(parts);base=eb[sl]
    base_dc=base.mean((1,2),keepdims=True);base_non=base-base_dc
    windows[name]={'component_names':['correction_DC','source_fitted_atom_projection','orthogonal_correction'],
     'temporal_covariance':c,'spatial_time_orthogonality_max':max(orthogonality[sl]),
     'baseline_error_temporal_variance':float(np.mean(temporal(base)**2)),
     'baseline_error_DC_temporal_variance':float(np.mean(temporal(base_dc)**2)),
     'baseline_error_nonDC_temporal_variance':float(np.mean(temporal(base_non)**2)),
     'per_frame_component_energy':[np.mean(v**2,axis=(1,2,3)).tolist()for v in parts],
     'per_frame_ranks':ranks[sl],'basis_fixed_across_window':all(f==freq_records[sl][0]for f in freq_records[sl])}
   out['rows'].append({'scene':row['scene'],'windows':windows})
 assert all(sha(Path(p))==v for p,v in pins.items())
 out['status']='completed_descriptive_subspace_identity_not_solution'
 target.write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
 print(json.dumps({'rows':len(out['rows']),'results_sha256':sha(target),
 'mature':{r['scene']:r['windows']['mature']['temporal_covariance']['matrix']for r in out['rows']}},indent=2))
if __name__=='__main__':main()
