"""Authenticated source-only CPU feasibility. Clean reference only scorer/generator."""
from pathlib import Path
import hashlib, importlib.util, inspect, json, sys
import numpy as np
from normalized_pilot import make_dc_normalized_phase_pilot
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
OLD=ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930'
sys.path.insert(0,str(OLD))
spec=importlib.util.spec_from_file_location('frozen_significant_analysis',OLD/'analyze.py')
old=importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
first=old.first; ref=old.ref; helper=old.helper

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def selfchecks():
    rng=np.random.default_rng(773021); y,x=np.indices((24,32)); w=.02*np.cos(2*np.pi*(3*x/32+2*y/24))
    raw=.2+w[None,...,None]+rng.normal(0,.012,(72,24,32,3)); ctrl=np.zeros((72,3)); ctrl[0,0]=1
    p,a,d=make_dc_normalized_phase_pilot(raw,ctrl)
    future=raw.copy(); future[48:]+=.1; q,b,e=make_dc_normalized_phase_pilot(future,ctrl)
    np.testing.assert_array_equal(p[:48],q[:48]); np.testing.assert_array_equal(a[:48],b[:48]); assert d['frames'][:48]==e['frames'][:48]
    np.testing.assert_allclose(p.mean((1,2)),raw.mean((1,2)),atol=1e-14)
    assert max(f['preceding_observations'] for f in d['frames'])==63
    cc=ctrl.copy(); cc[12,0]=1; cc[43:,1:]=[.25,.125]
    pp,aa,dd=make_dc_normalized_phase_pilot(raw,cc)
    for i in (0,12,43):
        alone,_,_=make_dc_normalized_phase_pilot(raw[i:i+1],ctrl[:1]); np.testing.assert_array_equal(pp[i],alone[0]); assert dd['frames'][i]['preceding_observations']==0
    assert list(inspect.signature(make_dc_normalized_phase_pilot).parameters)==['raw','controls']
    constant=np.broadcast_to(np.array([.2,.3,.4]),(16,24,32,3)).copy()
    q,_,_=make_dc_normalized_phase_pilot(constant,ctrl[:16]); np.testing.assert_allclose(q,constant,atol=1e-15)
    scales=np.stack([np.linspace(.6,1.4,16),np.linspace(1.2,.8,16),np.linspace(.9,1.1,16)],-1)
    pure=(np.array([.2,.3,.4])+w[...,None])*scales[:,None,None,:]
    q,aa,_=make_dc_normalized_phase_pilot(pure,ctrl[:16]); assert aa.all(); np.testing.assert_allclose(q,pure,atol=1e-14)
    cases={}
    for reason in ('nearzero','negative','nan','overflow','metadata'):
        r=raw[:16].copy(); cc=ctrl[:16].copy()
        if reason=='nearzero': r[5,...,0]=1e-5
        if reason=='negative': r[5,1,1,0]=-1
        if reason=='nan': r[5,1,1,0]=np.nan
        if reason=='overflow': r[5,1,1,0]=65505
        if reason=='metadata': cc[5,0]=.5
        q,aa,dd=make_dc_normalized_phase_pilot(r,cc)
        np.testing.assert_array_equal(q[5],r[5]); assert not aa[5] and dd['frames'][6]['preceding_observations']==0
        cases[reason]=True
    binary=np.zeros((16,24,32,3)); binary[:,:,16:]=1
    q,aa,_=make_dc_normalized_phase_pilot(binary,ctrl[:16]); assert (~aa).any(); np.testing.assert_array_equal(q[~aa],binary[~aa]); assert q.min()>=0
    return dict(no_future=True,reset_jitter_epoch=True,history64=True,current_DC=True,no_truth_guide_API=True,
        exact_noiseless_multiplicative_RGB_closure=True,constant_RGB=True,invalid_Gibbs_raw=True,invalid_fallbacks=cases)

def evaluate(raw,truth,controls,scene):
    p,a,diag=make_dc_normalized_phase_pilot(raw,controls)
    s,sa,sd=old.make_significant_phase_pilot(raw,controls)
    h,ha,hd=old.make_hard(raw,controls,history=64)
    outputs={'raw_source':(raw,np.zeros(len(raw),bool)), 'frozen_hard64':(h,ha), 'frozen_significant64':(s,sa), 'DC_normalized_significant64':(p,a)}
    metrics={}
    for name,(value,active) in outputs.items():
        rounded=value.astype(np.float16).astype(np.float32)
        metrics[name]=dict(active_fraction=float(active.mean()),full=first.detail(rounded,truth),mature=first.detail(rounded[-16:],truth[-16:]),
            startup_first8=first.detail(rounded[:8],truth[:8]),invalid_pixel_fraction=float(np.mean(~np.all(np.isfinite(rounded)&(rounded>=0)&(rounded<=65504),-1))))
    for window in ('full','mature'):
        cand=metrics['DC_normalized_significant64'][window]
        for name,value in (('frozen_hard64',h),('frozen_significant64',s)):
            baseline=metrics[name][window]['score']
            activity=float(np.mean(abs(p-value)>1e-5))
            cand['source_only_relative_gate_against_'+name]=ref.acceptance(cand['score'],baseline,activity,0,scene)
            cand['STD_ratio_to_'+name]=cand['score']['residual_temporal_std']/baseline['residual_temporal_std'] if baseline['residual_temporal_std'] else None
    def counts(d):
        records=d['frames']; return dict(full_retained_innovation_sum=sum(r.get('retained_innovation_frequencies',0) for r in records),
            mature_retained_innovation_sum=sum(r.get('retained_innovation_frequencies',0) for r in records[-16:]),
            full_retained_frequency_sum=sum(r.get('retained_frequencies',0) for r in records))
    return dict(metrics=metrics,candidate_diagnostics=diag,innovation_counts=dict(candidate=counts(diag),frozen_significant=counts(sd)),no_native_response_used=True)

def adversaries():
    f,h,w=64,64,96; y,x=np.indices((h,w)); base=2*np.pi*(5*x/w+3*y/h)
    rng=np.random.default_rng(83729); noise=rng.normal(0,.012,(f,h,w,3)); ctrl=np.zeros((f,3)); ctrl[0,0]=1
    static=np.broadcast_to(.2+.008*np.cos(base)[None,...,None],noise.shape).copy(); out=[]
    def add(name,truth,obs=None,controls=None,**extra):
        out.append(dict(family=name,result=evaluate(truth+noise if obs is None else obs,truth,ctrl if controls is None else controls,name),**extra))
    for name,angles in (('slow_constant_phase',np.arange(f)*.02),('phase_acceleration',.0015*np.arange(f)**2)):
        truth=np.broadcast_to(.2+.008*np.cos(base[None]+angles[:,None,None])[...,None],noise.shape).copy(); add(name,truth)
    truth=static.copy(); truth[32:]*=1.7; add('multiplicative_illumination_step',truth)
    truth=static.copy(); truth[32:]+=.08; add('additive_DC_only_illumination_step',truth)
    scale=np.ones((f,3)); scale[32:]=[1.7,.7,1.2]; add('colored_multiplicative_illumination',static*scale[:,None,None,:])
    truth=static.copy(); truth[32:]=.2+.008*np.cos(2*np.pi*(2*x/w-5*y/h))[None,...,None]; add('disocclusion_shape_swap',truth)
    checker=np.broadcast_to(.2+.0008*((-1.)**x)[None,...,None],noise.shape).copy(); add('weak_Nyquist_startup',checker)
    add('colored_RGB_noise',static,static+noise*np.array([.5,1,2]),nominal_shared_noise_scale_false=True)
    add('current_RGB_fully_correlated_noise',static,static+np.repeat(noise[...,:1],3,-1),nominal_RGB_independence_false=True)
    ar=noise.copy()
    for i in range(1,f): ar[i]=.8*ar[i-1]+.6*noise[i]
    add('temporal_AR_source_noise',static,static+ar,nominal_temporal_independence_false=True)
    clean=np.full_like(noise,.2); bias=.008*np.cos(base)[None,...,None]*np.array([1,.8,.6])
    add('persistent_correlated_source_bias',clean,clean+bias+noise,unidentifiable_clean_or_true_texture=True)
    return out

def main():
    if (HERE/'results.json').exists():raise ValueError('Preserve existing result')
    freeze=json.loads((HERE/'pre_score_freeze.json').read_text())
    assert all(sha(HERE/name)==digest for name,digest in freeze['sources'].items())
    report=dict(schema='source-DC-normalized-phase-feasibility-v1',status='running',quality_accepted=False,native_measured=False,native_response_reused=False,
        estimator_inputs=['observed source','reset/jitter controls'],clean_truth_used_only_in_fixture_generator_authentication_and_scoring=True,
        pre_score_freeze=freeze,selfchecks=selfchecks(),rows=[],counterexamples=[],metric_source_sha256=sha(ref.TESTS/'probe_fsrd_statistical_resolve.py'),
        limitations=['Known posthoc CPU source fixtures; no native acceptance','Global ratio/estimated variance induce coefficient and RGB covariance',
        'Nominal IID/circular/constant-amplitude phase model; no actual covariance/confidence proof','DC retained, static source noise expected to remain',
        'Relative source gates with null0/+1e-4 cannot replace absolute per-frame detail/noise','No old native T(P) used or substituted'])
    folder=ref.EVIDENCE/'response_temporal_spectral_alpha_holdout'; rp=folder/'results.json'; rh=sha(rp)
    native=json.loads(rp.read_text()); fixture,hashes=helper.snapshot_fixture(folder,native); report['frozen_fixture_sources']=hashes
    for row in native['rows']:
        scene=row['scene']; sp=folder/scene/'sequences.npz'; cp=folder/scene/'observed/frame_controls.txt'; sh=sha(sp); ch=sha(cp)
        observed,data=helper.regenerate(scene,native,fixture)
        with np.load(sp) as saved:
            np.testing.assert_array_equal(observed,saved['observed']); np.testing.assert_array_equal(data['truth'],saved['clean_reference'])
            controls=ref.controls_from_native(cp,len(observed)); np.testing.assert_array_equal(controls,data['controls'])
            result=evaluate(observed,saved['clean_reference'],controls,scene)
        assert sha(rp)==rh and sha(sp)==sh and sha(cp)==ch
        report['rows'].append(dict(scene=scene,authenticated_observed_reference_controls_exact=True,source_files_unchanged=True,
            provenance=dict(report_sha256=rh,sequences_sha256=sh,controls_sha256=ch),result=result))
        m=result['metrics']; cand=m['DC_normalized_significant64']; print(scene,'matureSTD hard/sig/norm',*[m[n]['mature']['score']['residual_temporal_std'] for n in ('frozen_hard64','frozen_significant64','DC_normalized_significant64')],
            'gain',cand['full']['absolute_gain_min'],cand['full']['absolute_gain_max'],'phase',cand['full']['absolute_phase_max'],flush=True)
    report['counterexamples']=adversaries()
    assert all(sha(HERE/name)==digest for name,digest in freeze['sources'].items())
    report['status']='completed_CPU_source_feasibility_not_solution'
    (HERE/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('results_sha256',sha(HERE/'results.json'),flush=True)

if __name__=='__main__': main()
