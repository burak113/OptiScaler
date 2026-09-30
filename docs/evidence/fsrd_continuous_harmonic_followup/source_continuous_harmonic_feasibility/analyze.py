"""One frozen source-only continuous-harmonic feasibility; truth scorer only."""
from pathlib import Path
import hashlib,importlib.util,json,sys,time
import numpy as np
import harmonic_pilot as pilot
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
OLD=ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930';sys.path.insert(0,str(OLD))
s=importlib.util.spec_from_file_location('frozen_old_significant_analysis',OLD/'analyze.py');old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
first=old.first;ref=old.ref;helper=old.helper
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def bytesha(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def evaluate(raw,truth,controls,scene,exposure=None,old_controls_supported=True):
    start=time.perf_counter();p,active,diag=pilot.make_continuous_harmonic_pilot(raw,controls,exposure);wall=time.perf_counter()-start
    outputs={'raw_source':(raw,np.zeros(len(raw),bool)),'continuous_harmonic64':(p,active)}
    if old_controls_supported:
        hard,ha,_=old.make_hard(raw,controls,history=64);sig,sa,_=old.make_significant_phase_pilot(raw,controls)
        outputs.update(frozen_hard64=(hard,ha),frozen_significant64=(sig,sa))
    metrics={}
    for name,(value,a) in outputs.items():
        with np.errstate(over='ignore',invalid='ignore'):rounded=value.astype('f2').astype('f4')
        invalid=~np.all(np.isfinite(rounded)&(rounded>=0)&(rounded<=65504),-1)
        windows={}
        for window,sl in [('full',slice(None)),('mature',slice(-16,None)),('startup_first8',slice(0,8)),('activation8to16',slice(8,16))]:
            if not np.isfinite(rounded[sl]).all():windows[window]=dict(unscorable_nonfinite=True,absolute_detail_pass=False,invalid_pixel_fraction=float(invalid[sl].mean()))
            else:windows[window]=first.detail(rounded[sl],truth[sl])
        actual_invalid=~np.all(np.isfinite(value)&(value>=0)&(value<=65504),-1)
        metrics[name]=dict(active_fraction=float(a.mean()),invalid_pixel_fraction=float(invalid.mean()),
            invalid_pixel_fraction_before_FP16=float(actual_invalid.mean()),**windows)
    if old_controls_supported:
        for window,sl in [('full',slice(None)),('mature',slice(-16,None))]:
            candidate=metrics['continuous_harmonic64'][window]
            for name in ('frozen_hard64','frozen_significant64'):
                base=metrics[name][window]['score'];activity=float(np.mean(abs(p[sl]-outputs[name][0][sl])>1e-5))
                candidate['source_only_relative_gate_against_'+name]=ref.acceptance(candidate['score'],base,activity,0,scene)
                candidate['STD_ratio_to_'+name]=candidate['score']['residual_temporal_std']/base['residual_temporal_std'] if base['residual_temporal_std'] else None
    fallback=[r['frame'] for r in diag['frames'] if r['raw_passthrough']]
    for i in fallback:assert np.asarray(p[i]).tobytes()==np.asarray(raw[i]).tobytes()
    selection=[r for r in diag['frames'] if r['selection'] is not None]
    total=diag['total_counts'];total['source_sigma_rFFT_calls']=total['background_FFT_steps'];total['total_rFFT_calls']=2*total['background_FFT_steps']+total['residual_FFT_steps']
    return dict(metrics=metrics,diagnostics=diag,source_sha256=bytesha(raw),controls_array_sha256=bytesha(controls),
        exposure_metadata_sha256=None if exposure is None else bytesha(exposure),source_dtype=str(raw.dtype),source_shape=list(raw.shape),CPU_wall_seconds=wall,
        unsupported_raw_fallback_frames_exact=fallback,selection_events=len(selection),no_native_response_used=True,
        old_control_comparison_supported=old_controls_supported)

def adversaries():
    f,h,w=64,64,96;y,x=np.indices((h,w));rng=np.random.default_rng(83729)
    noise=rng.normal(0,.012,(f,h,w,3));ctrl=np.zeros((f,3));ctrl[0,0]=1
    phi=2*np.pi*(5.23*x/w+3.17*y/h);psi=2*np.pi*(8.43*x/w-2.31*y/h)
    static=np.broadcast_to(.2+.008*np.cos(phi)[None,...,None],noise.shape).copy();out=[]
    def add(name,truth,observed=None,controls=None,exposure=None,supported=True,**extra):
        observed=truth+noise if observed is None else observed;observed=observed.astype('f4');truth=truth.astype('f4')
        out.append(dict(family=name,result=evaluate(observed,truth,ctrl if controls is None else controls,name,exposure,supported),**extra))
        c=out[-1]['result']['metrics']['continuous_harmonic64'];print('adversary',name,'STD',c['mature'].get('score',{}).get('residual_temporal_std'),'atoms',sum(bool(z['atom_frequencies']) for z in out[-1]['result']['diagnostics']['frames']),flush=True)
    add('offgrid_stationary_one_wave',static)
    two=np.broadcast_to(.2+.006*np.cos(phi)[None,...,None]+.004*np.cos(psi)[None,...,None],noise.shape).copy();add('two_offgrid_waves',two)
    dense=np.full_like(noise,.2)
    for fx,fy in ((1.2,2.37),(4.53,-1.41),(7.17,5.81),(12.19,-3.44),(15.21,6.13),(9.6,10.2)):dense+=.004*np.cos(2*np.pi*(fx*x/w+fy*y/h))[None,...,None]
    add('dense_more_than_two_components',dense)
    close=np.broadcast_to(.2+.008*(np.cos(phi)+np.cos(2*np.pi*(5.26*x/w+3.2*y/h)))[None,...,None],noise.shape).copy();add('close_frequency_illconditioning',close)
    weak=np.broadcast_to(.2+.0008*((-1.)**x)[None,...,None],noise.shape).copy();add('weak_Nyquist_startup',weak)
    late=np.full_like(noise,.2);late[32:]=weak[32:];add('late_weak_appearance',late)
    for name,angle in (('slow_moving_phase',.02*np.arange(f)),('phase_acceleration',.0015*np.arange(f)**2)):
        truth=np.broadcast_to(.2+.008*np.cos(phi[None]+angle[:,None,None])[...,None],noise.shape).copy();add(name,truth)
    drift=np.stack([.2+.008*np.cos(2*np.pi*((5.23+.015*i)*x/w+3.17*y/h)) for i in range(f)])
    add('frequency_drift',np.repeat(drift[...,None],3,-1))
    light=static.copy();light[32:]*=1.7;add('multiplicative_illumination_step',light)
    light=static.copy();light[32:]+=.08;add('additive_DC_illumination_step',light)
    disco=static.copy();disco[32:]=.2+.008*np.cos(psi)[None,...,None];add('disocclusion',disco)
    controls=ctrl.copy();controls[20,0]=1;controls[40:,1:]=[.25,.125];ex=np.ones(f);ex[56:]=2
    exposed=static.copy();exposed[56:]*=2;add('reset_jitter_exposure_metadata',exposed,controls=controls,exposure=ex)
    add('colored_RGB_noise',static,static+noise*np.array([.5,1,2]),nominal_RGB_scale_false=True)
    add('current_RGB_correlated_noise',static,static+np.repeat(noise[...,:1],3,-1),nominal_RGB_independence_false=True)
    ar=noise.copy()
    for i in range(1,f):ar[i]=.8*ar[i-1]+.6*noise[i]
    add('temporal_AR_noise',static,static+ar,nominal_time_independence_false=True)
    clean=np.full_like(noise,.2);bias=.008*np.cos(phi)[None,...,None]*np.array([1,.8,.6])
    add('persistent_shared_bias',clean,clean+bias+noise,unidentifiable_clean_or_true_texture=True)
    checker=np.broadcast_to(.2+.02*((-1.)**x)[None,...,None],noise.shape).copy();add('Nyquist_real_checker',checker)
    signed=static+noise;signed[32,1,1,0]=-.001;add('signed_source_fallback',static,signed,supported=False)
    near=static+noise;near[32,...,0]=1e-5;near_truth=static.copy();near_truth[32,...,0]=1e-5;add('nearzero_channel_fallback',near_truth,near)
    overflow=static+noise;overflow[32,1,1,0]=65505;add('overflow_source_fallback',static,overflow,supported=False)
    high=np.zeros_like(noise);high[:,:,w//2:]=65504;add('residual_carrier_or_Gibbs_fallback',high,high)
    return out

def main():
    if (HERE/'results.json').exists():raise ValueError('Preserve result')
    freeze=json.loads((HERE/'pre_score_freeze.json').read_text())
    assert all(sha(ROOT/path)==digest for path,digest in freeze['sources'].items())
    check=json.loads((HERE/'selfcheck_results.json').read_text());assert check['status']=='passed_pre_score_selfchecks' and check['prototype_sha256']==sha(HERE/'harmonic_pilot.py')
    r=dict(schema='continuous-harmonic-source-feasibility-v2',status='running',quality_accepted=False,native_measured=False,native_response_reused=False,
        pre_score_freeze=freeze,selfchecks=check,rows=[],counterexamples=[],metric_source_sha256=sha(ref.TESTS/'probe_fsrd_statistical_resolve.py'),
        qualifications=json.loads((ROOT/'tools_tmp/source_continuous_harmonic_design_20260930/qualification_v2.json').read_text()),
        truth_only_generator_authentication_and_scoring=True,estimator_inputs=['source','reset/jitter controls','optional supplied exposure metadata'])
    folder=ref.EVIDENCE/'response_temporal_spectral_alpha_holdout';rp=folder/'results.json';rh=sha(rp)
    native=json.loads(rp.read_text());fixture,hashes=helper.snapshot_fixture(folder,native);r['frozen_fixture_sources']=hashes
    for row in native['rows']:
        scene=row['scene'];sp=folder/scene/'sequences.npz';cp=folder/scene/'observed/frame_controls.txt';sh=sha(sp);ch=sha(cp)
        observed,data=helper.regenerate(scene,native,fixture)
        with np.load(sp) as saved:
            np.testing.assert_array_equal(observed,saved['observed']);np.testing.assert_array_equal(data['truth'],saved['clean_reference'])
            controls=ref.controls_from_native(cp,len(observed));np.testing.assert_array_equal(controls,data['controls'])
            result=evaluate(observed,saved['clean_reference'],controls,scene)
        assert sha(rp)==rh and sha(sp)==sh and sha(cp)==ch
        r['rows'].append(dict(scene=scene,authenticated_source_reference_controls_exact=True,original_files_unchanged=True,
            provenance=dict(report_sha256=rh,sequences_sha256=sh,controls_sha256=ch),result=result))
        m=result['metrics'];c=m['continuous_harmonic64'];print(scene,'matureSTD significant/harmonic',m['frozen_significant64']['mature']['score']['residual_temporal_std'],c['mature']['score']['residual_temporal_std'],
            'gain',c['full']['absolute_gain_min'],c['full']['absolute_gain_max'],'phase',c['full']['absolute_phase_max'],'time',result['CPU_wall_seconds'],flush=True)
    r['counterexamples']=adversaries();assert all(sha(ROOT/path)==digest for path,digest in freeze['sources'].items())
    r['status']='completed_CPU_source_feasibility_not_solution';(HERE/'results.json').write_text(json.dumps(r,indent=2,allow_nan=False)+'\n')
    print('result SHA',sha(HERE/'results.json'),flush=True)
if __name__=='__main__':main()
