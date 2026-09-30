"""Independent complex-ridge math, actual pulse adversary and frozen results audit."""
from pathlib import Path
import hashlib,importlib.util,json,sys
import numpy as np
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent;CASE=ROOT/'tools_tmp/response_global_dc_offline_20260930';SOURCE=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
before={p:sha(p) for p in (CASE/'model.py',CASE/'analyze.py',CASE/'preregistration.md',CASE/'results.json',CASE/'pre_execution_erratum.md',SOURCE/'results.json')}
sys.path.insert(0,str(CASE));spec=importlib.util.spec_from_file_location('root_global_model_analysis',CASE/'analyze.py');root=importlib.util.module_from_spec(spec);spec.loader.exec_module(root);model=root.calibrate;ref=root.ref
r=json.loads((CASE/'results.json').read_text());native=json.loads((SOURCE/'results.json').read_text())
assert r['status']=='completed_posthoc_falsification_not_solution' and len(r['rows'])==6 and not r['quality_accepted'] and not r['native_rerun']
assert r['model_sha256']==sha(CASE/'model.py') and r['script_sha256']==sha(CASE/'analyze.py') and r['source_report_sha256']==sha(SOURCE/'results.json') and r['preregistration_sha256']==sha(CASE/'preregistration.md') and r['prior_sha256']==sha(root.PRIOR)
assert root.self_checks()==r['self_checks']
# Compare actual full image output to independently solved augmented ridge LS.
rng=np.random.default_rng(98103);f,h,w=24,16,16;y,x=np.indices((h,w));ctrl=np.zeros((f,3));ctrl[0,0]=1;active=np.ones(f,bool)
P=.2+rng.normal(0,.012,(f,h,w,3))+.01*np.sin(np.arange(f)*.3)[:,None,None,None]
R=.83*P+.004+.002*np.sin(np.arange(f)*.3)[:,None,None,None]*np.cos(2*np.pi*y/h)[None,...,None]
out,records=model(P,R,P,ctrl,active);N=h*w;max_error=0.
for i in (8,15,23):
 lo=max(0,i-15);ps=np.fft.rfft2(P[lo:i+1],axes=(1,2))/N;ds=np.fft.rfft2((P-R)[lo:i+1],axes=(1,2))/N;gs=ps[:,0,0].real@np.array([.2126,.7152,.0722]);m=len(gs);ridge=4*np.mean([records[j]['nominal_variance'] for j in range(lo,i+1)])
 measured=np.fft.rfft2(out[i],axes=(0,1))/N
 for ky,kx in ((0,0),(1,0),(3,2),(h//2,w//2)):
  for c in range(3):
   z=ps[:,ky,kx,c];target=ds[:,ky,kx,c];features=np.c_[z-z.mean(),gs-gs.mean()]
   reg=np.diag(np.sqrt([ridge,ridge*(.2126**2+.7152**2+.0722**2)]))
   aug=np.vstack((features/np.sqrt(m),reg));rhs=np.r_[(target-target.mean())/np.sqrt(m),[0.,0.]]
   beta=np.linalg.lstsq(aug,rhs,rcond=None)[0];prediction=target.mean()+features[-1]@beta
   error=float(abs(prediction-measured[ky,kx,c]));max_error=max(max_error,error);assert error<1e-12
# Actual model evaluation of high-leverage one-current-DC-pulse response noise.
f,h,w=16,64,96;y,x=np.indices((h,w));ctrl=np.zeros((f,3));ctrl[0,0]=1;active=np.ones(f,bool)
P=np.full((f,h,w,3),.2);P[-1]=.25;impulse=np.zeros_like(P);impulse[-1]=.004*np.cos(2*np.pi*4*x/w)[...,None]
noise=rng.normal(0,.012,P.shape);noise-=noise.mean((1,2),keepdims=True);observed=P+noise;TP=P-impulse
delta,d=model(P,TP,observed,ctrl,active);old,_=root.prior.calibrate(P,TP,observed,ctrl,active)
last=impulse[-1];retention=float(np.sum(delta[-1]*last)/np.sum(last*last));old_retention=float(np.sum(old[-1]*last)/np.sum(last*last))
qbar=np.mean([v['nominal_variance'] for v in d]);ridgeDC=4*qbar*float(np.sum(np.array([.2126,.7152,.0722])**2));vz=.05**2*15/256;expected=1/16+15/16*vz/(vz+ridgeDC)
np.testing.assert_allclose(retention,expected,rtol=0,atol=1e-12);assert retention>.99 and old_retention<.07
# Distinct moving detail shows that keeping an intended mode need not reject
# independent nonlocal impulse noise; positive TP remains representable.
wave=.01*np.cos(2*np.pi*3*x/w+.3*np.arange(f)[:,None,None]);moving=P+wave[...,None];truthdelta=.2*wave[...,None]*np.ones((1,1,1,3));delta2,_=model(moving,moving-truthdelta-impulse,moving+noise,ctrl,active)
FT=np.fft.rfft2(delta2[-1],axes=(0,1))/(h*w);target=np.fft.rfft2(truthdelta[-1],axes=(0,1))/(h*w);ratio=FT[0,3]/target[0,3]
moving_gain=abs(ratio).tolist();moving_phase=abs(np.angle(ratio)).tolist();impulse_retention_with_detail=float(np.sum((delta2[-1]-truthdelta[-1])*last)/np.sum(last*last))
rows=[]
for row in r['rows']:
 scene=row['scene'];sp=SOURCE/scene/'sequences.npz';cp=SOURCE/scene/'observed/frame_controls.txt';assert sha(sp)==row['sequences_sha256'] and sha(cp)==row['controls_sha256'];before[sp]=sha(sp);before[cp]=sha(cp)
 nr=next(v for v in native['rows'] if v['scene']==scene)
 with np.load(sp) as arrays:
  controls=ref.controls_from_native(cp,len(arrays['pilot']));variants={};diagnostics={}
  for label,fn in (('affine_control',root.prior.calibrate),('global_dc',model)):
   delta,j=fn(arrays['pilot'],arrays['pilot_response'],arrays['observed'],controls,arrays['active']);value=arrays['baseline']+delta;dc=ref.dc_conservation(value,arrays['observed'],arrays['active'],controls,1,[v['epoch'] for v in j]);safe,fraction=ref.radiance_fallback(dc,arrays['baseline'])
   assert j==row['diagnostics'][label];diagnostics[label]=j
   for suffix,v,fallback in (('',value,0),('_dc_current',dc,0),('_dc_current_safe',safe,fraction)):
    measured=ref.evaluate(v,arrays['baseline'],arrays['clean_reference'],scene,arrays['active'],row['null_rms'],fallback)
    for window in ('full','mature'):
     measured[window+'_absolute_gain_phase']=root.absolute_gates(measured[window]);measured[window+'_std_ratio']=measured[window]['residual_temporal_std']/row['baseline_'+window]['residual_temporal_std']
    assert measured==row['variants'][label+suffix];variants[label+suffix]=measured
  selected=variants['global_dc_dc_current_safe'];control=variants['affine_control_dc_current_safe']
  rows.append(dict(scene=scene,source_sequences_sha256=sha(sp),source_controls_sha256=sha(cp),recomputed_variants_exact=True,full_gate=selected['full_gate'],mature_gate=selected['mature_gate'],
   full_absolute_gain_phase=selected['full_absolute_gain_phase'],mature_absolute_gain_phase=selected['mature_absolute_gain_phase'],
   full_STD=selected['full']['residual_temporal_std'],mature_STD=selected['mature']['residual_temporal_std'],baseline_mature_STD=row['baseline_mature']['residual_temporal_std'],affine_control_mature_STD=control['mature']['residual_temporal_std'],mature_STD_ratio=selected['mature_std_ratio'],
   full_gain_range=[min(v for v in selected['full']['contrast_gain'] if v is not None),max(v for v in selected['full']['contrast_gain'] if v is not None)],full_phase_max=max(v for v in selected['full']['phase_error_radians'] if v is not None),fallback_pixel_fraction=selected['baseline_fallback_pixel_fraction']))
assert all(sha(p)==v for p,v in before.items())
report=dict(schema='observable-globalDC-actual-model-independent-review-v1',analysis_sha256=sha(__file__),root_results_sha256=sha(CASE/'results.json'),root_model_sha256=sha(CASE/'model.py'),source_native_report_sha256=sha(SOURCE/'results.json'),new_GPU_native_calls=0,quality_accepted=False,all_original_evidence_unchanged=True,
 producer_selfchecks_reproduced=True,independent_augmented_complex_ridge_max_error=max_error,
 actual_impulse_counterexample=dict(current_delta_retention=retention,analytic_nominal_retention=expected,old_affine_retention=old_retention,source_nominal_q_average=qbar,DC_ridge=ridgeDC,detail_mode_gain_RGB=moving_gain,detail_mode_phase_RGB=moving_phase,nonlocal_impulse_retention_with_moving_detail=impulse_retention_with_detail,
  qualification='Constructed observable P/TP/raw sequence. Independent response-noise impulse coincides with a new DC jump; no native rerun or unavailable clean input enters filter.'),
 rows=rows,
 rank_guard_review=['Complex conjugation and two-feature inverse match independent augmented ridge least-squares.',
 'det>64eps*vz*vg is a numerical nonsingularity guard, not causal identification. joint_identified_fraction means numerical acceptance of ridge-conditioned joint solve.',
 'Noiseless collinear DC/local feature can lose tiny ridge in subtraction; fallback az=zy/vz,ag0 is the same original single-feature fit and avoids huge finite cancellation output.',
 'Numerically accepted positive-ridge covariance can remain physically unidentifiable; current-inclusive high leverage and correlated data remain.'],
 conclusions=['Actual model retains >99.9% of a unique current response-noise impulse coincident with a DC jump; original constant-P affine mean retains6.25%. Intended moving detail can survive at the same time. This is a concrete failure, not a causality diagnosis.',
 'Six frozen native-array posthoc results independently recomputed exactly. Material/reset noise, lighting contrast and weak detail/noise limits remain; the candidate is not a solution.'])
dest=HERE/'audit.json';assert not dest.exists();dest.write_text(json.dumps(report,indent=2)+'\n');print('audit_sha256',sha(dest),'pulse retention',retention,'old',old_retention,'LSerr',max_error)
for row in rows:print(row['scene'],row['full_gate']['failures'],row['mature_gate']['failures'],'matureSTD',row['mature_STD'],'ratio',row['mature_STD_ratio'])
