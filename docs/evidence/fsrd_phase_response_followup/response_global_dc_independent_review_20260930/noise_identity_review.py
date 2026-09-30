"""Lightweight exact-identity audit; no DC-regression or native/GPU rerun."""
from pathlib import Path
import hashlib,json
import numpy as np
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent;CASE=ROOT/'tools_tmp/significant_phase_native_noise_attribution_20260930';SOURCE=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def centered(v):return v-v.mean(0,keepdims=True)
def identity(a,b,sign=1):
 x=centered(a);y=centered(b);va=float(np.mean(x*x));vb=float(np.mean(y*y));co=float(np.mean(x*y));measured=float(np.mean((x+sign*y)**2));predicted=va+vb+2*sign*co
 return dict(variance_a=va,variance_b=vb,covariance=co,measured_variance=measured,predicted_variance=predicted,identity_absolute_error=abs(measured-predicted))
rp=CASE/'results.json';r=json.loads(rp.read_text());before={p:sha(p) for p in (rp,CASE/'analyze.py',SOURCE/'results.json')}
assert r['status']=='completed_diagnostic_not_solution' and len(r['rows'])==6 and not r['quality_accepted'] and not r['native_rerun']
assert r['script_sha256']==sha(CASE/'analyze.py') and r['source_report_sha256']==sha(SOURCE/'results.json');assert sha(ROOT/'tools_tmp/response_noise_attribution_20260930/analyze.py')==r['reference_sha256']
rows=[]
for row in r['rows']:
 scene=row['scene'];sp=SOURCE/scene/'sequences.npz';assert sha(sp)==row['sequences_sha256'];before[sp]=sha(sp)
 for label,v in row['windows'].items():
  for name in ('pilot_response_difference','non_dc_difference','baseline_residual_plus_correction'):
   x=v[name];sign=1 if name=='baseline_residual_plus_correction' else -1;np.testing.assert_allclose(x['measured_variance'],x['variance_a']+x['variance_b']+2*sign*x['covariance'],rtol=1e-12,atol=1e-22)
 with np.load(sp) as saved:
  p=saved['pilot'][-16:,5:-5,5:-5].astype(float);tp=saved['pilot_response'][-16:,5:-5,5:-5].astype(float);b=saved['baseline'][-16:,5:-5,5:-5].astype(float);truth=saved['clean_reference'][-16:,5:-5,5:-5].astype(float)
  active=saved['active'][-16:,None,None,None].astype(float);delta=active*(p-tp);e=b-truth;stored=row['windows']['mature']
  data={'pilot_response_difference':identity(p,tp,-1),'non_dc_difference':identity(p-p.mean((1,2),keepdims=True),tp-tp.mean((1,2),keepdims=True),-1),'baseline_residual_plus_correction':identity(e,delta)}
  for name,values in data.items():
   for k,v in values.items():np.testing.assert_allclose(v,stored[name][k],rtol=1e-12,atol=1e-22)
  energies={}
  for name,v in (('pilot',p),('native_pilot_response',tp),('correction',delta),('baseline_residual',e)):
   dc=v.mean((1,2));shape=v-dc[:,None,None,:];total=float(np.mean(centered(v)**2));dvar=float(np.mean(centered(dc)**2));svar=float(np.mean(centered(shape)**2))
   np.testing.assert_allclose(total,dvar+svar,rtol=1e-12,atol=1e-22)
   for k,x in (('total_temporal_rms',np.sqrt(total)),('dc_temporal_rms',np.sqrt(dvar)),('non_dc_temporal_rms',np.sqrt(svar))):np.testing.assert_allclose(x,stored['energies'][name][k],rtol=1e-12,atol=1e-22)
   energies[name]=dict(temporal_RMS=float(np.sqrt(total)),non_DC_temporal_RMS=float(np.sqrt(svar)),DC_variance_fraction=dvar/total if total else 0)
  np.testing.assert_allclose(np.std(e,axis=0).mean(),stored['score_mean_pixel_std_baseline'],rtol=1e-12)
  np.testing.assert_allclose(np.std(e+delta,axis=0).mean(),stored['score_mean_pixel_std_candidate'],rtol=1e-12)
  global_dc=saved['pilot'][-16:].astype(float).mean((1,2));roi_dc=p.mean((1,2));dc_difference=float(np.sqrt(np.mean((centered(global_dc)-centered(roi_dc))**2)))
 rows.append(dict(scene=scene,actual_mature_identities_recomputed=data,mature_temporal_energies=energies,global_fullimage_vs_scoreROI_DC_temporal_difference_RMS=dc_difference,
  score_mean_pixel_std_baseline=stored['score_mean_pixel_std_baseline'],score_mean_pixel_std_candidate=stored['score_mean_pixel_std_candidate']))
assert all(sha(p)==v for p,v in before.items())
out=dict(schema='significant-phase-native-exact-noise-identity-independent-review-v1',analysis_sha256=sha(__file__),root_results_sha256=sha(rp),root_script_sha256=sha(CASE/'analyze.py'),all_original_evidence_unchanged=True,new_GPU_native_calls=0,quality_accepted=False,rows=rows,
 qualifications=['full means full64 time window; spatial energies use5-pixel-interior scoreROI70x118, not full128x80 image. mature16/early8 same ROI.',
 'Temporal RMS=sqrt(mean variance) differs from mean(pixel temporalSTD) used by gates; these must not be interchanged.',
 'Root decomposes raw significant_phase=baseline+active(P-TP), not currentDC/fallback selected variant. CurrentDC removes a different ROI mean; no identity equates their exact metrics.',
 'DC-to-spatial association uses pilot scoreROI mean, whereas globalDC estimator uses fullimage pilot luminance. Their regressors differ, particularly with nonperiodic/moving detail.',
 'DC/shape temporal orthogonality and exact variance identities are algebraic, not independence or causal evidence. Cleanreference enters baseline-residual decomposition only, no predictor.',
 'Heavy DC-spatial least-squares/LOO association was code reviewed, not independently rerun. All stored identities were arithmetically checked; actual mature sequence identities and energies recomputed.'])
p=HERE/'noise_identity_review.json';assert not p.exists();p.write_text(json.dumps(out,indent=2)+'\n');print('noise_identity_review_sha256',sha(p))
