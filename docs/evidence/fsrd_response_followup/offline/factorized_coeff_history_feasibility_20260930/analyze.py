"""Single preregistered coefficient-history source-pilot feasibility run."""
from pathlib import Path
import hashlib,importlib.util,json,sys
import numpy as np
from coefficient_pilot import make_coefficient_history_pilot

ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT/'tools_tmp/factorized_pilot_feasibility_20260930'
sys.path.insert(0,str(OLD))
spec=importlib.util.spec_from_file_location('frozen_helpers',OLD/'analyze.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
ref=helper.ref
FOLDER=Path(__file__).resolve().parent
PRE=FOLDER/'preregistration.json'
PREREG_SHA=ref.digest(PRE)


def self_checks():
    y,x=np.indices((24,32));signal=.03*np.cos(2*np.pi*(3*x/32+2*y/24))
    rng=np.random.default_rng(6319);raw=.2+signal[None,...,None]+rng.normal(0,.012,(32,24,32,3))
    d=np.broadcast_to(.3+signal[None,...,None],raw.shape).copy();s=np.full_like(raw,.05)
    ctrl=np.zeros((32,3));ctrl[0,0]=1
    p,a,j=make_coefficient_history_pilot(raw,d,s,ctrl);np.testing.assert_array_equal(p[:3],raw[:3]);assert not a[:3].any()
    later=raw.copy();later[20:]+=.1;q,b,_=make_coefficient_history_pilot(later,d,s,ctrl)
    np.testing.assert_array_equal(p[:20],q[:20]);np.testing.assert_array_equal(a[:20],b[:20])
    cc=ctrl.copy();cc[12,0]=1;cc[24:,1:]=[.25,.125];p,a,j=make_coefficient_history_pilot(raw,d,s,cc)
    for i in (0,12,24):np.testing.assert_array_equal(p[i:i+3],raw[i:i+3]);assert not a[i:i+3].any()
    assert max(f.get('coefficient_history_count',0) for f in j['frames'])<=16
    assert max(f.get('residual_history_count',0) for f in j['frames'])<=16
    np.testing.assert_allclose(p.mean((1,2)),raw.mean((1,2)),atol=1e-14)
    no=np.full_like(raw,.2);p,a,j=make_coefficient_history_pilot(raw,no,no,ctrl)
    np.testing.assert_array_equal(p,raw);assert not a.any()
    # Large source contrast step must select current beta, not a slow mean.
    light=raw.copy();light[16:]=.2+1.6*(light[16:]-.2)
    p,a,j=make_coefficient_history_pilot(light,d,s,ctrl)
    assert j['frames'][16]['coefficient_innovation']
    return dict(raw_inactive_first_three=True,no_future=True,reset_jitter_histories_cut=True,bounded_16=True,
        current_source_DC=True,unsupported_rank_exact_raw=True,large_coefficient_step_current=True)


def evaluate(raw,diff,spec,truth,controls):
    p,active,j=make_coefficient_history_pilot(raw,diff,spec,controls)
    # Same FP16 source-pilot precision as the native research driver.
    p=p.astype(np.float16).astype(np.float32)
    return dict(active_fraction=float(active.mean()),full=helper.moments(p,truth),
        mature=helper.moments(p[-16:],truth[-16:]),diagnostics=j)


def adversaries():
    frames,h,w=32,64,96;y,x=np.indices((h,w));rng=np.random.default_rng(43197)
    controls=np.zeros((frames,3));controls[0,0]=1
    truth=np.full((frames,h,w,3),.2);bias=rng.normal(0,.012,(h,w,3))
    raw=truth+bias[None];diff=np.full_like(raw,.2);spec=np.broadcast_to(.2+.5*bias[None],raw.shape).copy()
    common=evaluate(raw,diff,spec,truth,controls)
    # Remove random noise's coefficient along this one feature to expose a
    # deterministic subthreshold slope; this intentionally violates exact iid.
    wave=np.cos(2*np.pi*(5*x/w+3*y/h));amplitude=.0015+np.arange(frames)*.000015
    truth=np.broadcast_to(.2+amplitude[:,None,None,None]*wave[None,...,None],(frames,h,w,3)).copy()
    noise=rng.normal(0,.012,truth.shape);noise-=noise.mean((1,2),keepdims=True)
    projection=np.sum(noise*wave[None,...,None],axis=(1,2))/np.sum(wave*wave)
    noise-=projection[:,None,None,:]*wave[None,...,None]
    raw=truth+noise;diff=np.broadcast_to(.3+.03*wave[None,...,None],raw.shape).copy();spec=np.full_like(raw,.05)
    slow=evaluate(raw,diff,spec,truth,controls)
    # Amplitude step on the same aligned guide must be tested without scene labels.
    step_truth=np.broadcast_to(.2+.02*wave[None,...,None],raw.shape).copy();step_truth[16:]=.2+1.6*(step_truth[16:]-.2)
    light=evaluate(step_truth+noise,diff,spec,step_truth,controls)
    controls_reset=controls.copy();controls_reset[16,0]=1
    reset=evaluate(step_truth+noise,diff,spec,step_truth,controls_reset)
    return [dict(family='persistent_spatial_noise_shared_with_guide',metrics=common),
        dict(family='slow_linear_amplitude_with_projected_noise_counterexample',metrics=slow,
             construction='Spatial noise projection removed only along the genuine feature; nominal iid-SE is intentionally conservative here'),
        dict(family='large_amplitude_step_same_guide',metrics=light),dict(family='large_amplitude_step_with_reset',metrics=reset)]


def main():
    output=FOLDER/'results.json'
    if output.exists():raise ValueError('Preserve prior feasibility')
    report=dict(schema='physical-beta-history-source-feasibility-v1',variant='plain_3SE_mean',quality_accepted=False,
        native_measured=False,native_response_reused=False,runtime_implemented=False,game_run=False,
        preregistration_sha256=PREREG_SHA,prototype_sha256=ref.digest(FOLDER/'coefficient_pilot.py'),script_sha256=ref.digest(__file__),
        authenticated_helper_sha256=ref.digest(OLD/'analyze.py'),self_checks=self_checks(),rows=[],counterexamples=[],
        limitations=['Post-hoc reuse of alpha fixture families; no independent native or game validation',
            'Coefficients/source covariances use observable sources only; truth enters fixture construction and scoring',
            'First <=2 prior guides or unsupported comparison retains exact raw inactive, no startup fix claim',
            'Spatial/temporal SE independence is not established; guide/source shared bias remains',
            'Absolute every-frame detail gains are reported separately from RMSE/noise improvement'])
    folder=ref.EVIDENCE/'response_temporal_spectral_alpha_holdout';rp=folder/'results.json';rh=ref.digest(rp);native=json.loads(rp.read_text())
    fixture,hashes=helper.snapshot_fixture(folder,native);report['frozen_fixture_sources']=hashes
    for row in native['rows']:
        scene=row['scene'];sp=folder/scene/'sequences.npz';cp=folder/scene/'observed/frame_controls.txt';sh=ref.digest(sp);ch=ref.digest(cp)
        observed,data=helper.regenerate(scene,native,fixture)
        with np.load(sp) as saved:
            np.testing.assert_array_equal(observed,saved['observed']);np.testing.assert_array_equal(data['truth'],saved['clean_reference'])
            controls=ref.controls_from_native(cp,len(observed));np.testing.assert_array_equal(controls,data['controls'])
            metric=evaluate(observed,data['diff'][...,:3],data['spec'][...,:3],saved['clean_reference'],controls)
        unchanged=ref.digest(rp)==rh and ref.digest(sp)==sh and ref.digest(cp)==ch;assert unchanged
        report['rows'].append(dict(scene=scene,source_files_unchanged=unchanged,authenticated_fixture_exact_match=True,
            provenance=dict(native_report_sha256=rh,native_sequences_sha256=sh,native_controls_sha256=ch),metrics=metric))
        print(scene,'active',metric['active_fraction'],{k:metric['mature'][k] for k in ('absolute_gain_min','absolute_gain_mean','absolute_gain_max')},
            'STD',metric['mature']['score']['residual_temporal_std'],'RMSE',metric['mature']['score']['rmse'],flush=True)
    report['counterexamples']=adversaries();assert ref.digest(PRE)==PREREG_SHA
    report['status']='completed_preregistered_cpu_source_feasibility_not_solution'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
