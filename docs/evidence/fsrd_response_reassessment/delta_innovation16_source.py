"""Post-hoc fixed 3-RMS spectral-delta innovation falsification; offline only."""
from pathlib import Path
import importlib.util
import json,sys
import numpy as np
REFERENCE=Path(__file__).resolve().parents[1]/'delta_history_offline_20260930/analyze.py'
spec=importlib.util.spec_from_file_location('delta_history_reference',REFERENCE)
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
HISTORY=16;MIN_PAST=8;INNOVATION_RMS=3.


def spectral_delta(delta,controls,active):
    """Only observed signed delta and immutable control/activity inputs.

    Compare current to preceding mean, using complex unbiased sample variance
    and nominal iid prediction variance Var_past*(1+1/m). A common RGB frequency
    uses current on ANY channel innovation, otherwise current+past causal mean.
    First eight observations use current unchanged. History includes current.
    Real motion contaminates variance; this is not calibrated confidence.
    """
    delta=np.asarray(delta,float);controls=np.asarray(controls,float);active=np.asarray(active,bool)
    if delta.ndim!=4 or delta.shape[-1]!=3 or controls.shape!=(len(delta),3) or active.shape!=(len(delta),):
        raise ValueError('Invalid delta/control/activity dimensions')
    if not np.isfinite(delta).all() or not np.isfinite(controls).all() or not np.isin(controls[:,0],[0,1]).all():
        raise ValueError('Invalid observed delta or reset/jitter controls')
    result=np.zeros_like(delta);past=[];epoch=0;records=[];h,w=delta.shape[1:3];n=h*w
    for i,frame in enumerate(delta):
        reset=bool(controls[i,0]);jitter_changed=bool(i and not np.array_equal(controls[i,1:],controls[i-1,1:]))
        if reset or jitter_changed or not active[i]:past.clear();epoch=i
        current=np.fft.rfft2(frame,axes=(0,1))/n;count=len(past)
        innovation=np.ones(current.shape[:2],bool) if active[i] else np.zeros(current.shape[:2],bool)
        if active[i]:
            if count>=MIN_PAST:
                samples=np.stack(past);prior=samples.mean(0)
                variance=np.sum(abs(samples-prior)**2,axis=0)/(count-1)
                limit=INNOVATION_RMS*np.sqrt(variance*(1+1/count))
                innovation=np.any(abs(current-prior)>limit,axis=-1)
                mean=(prior*count+current)/(count+1)
                selected=np.where(innovation[...,None],current,mean)
                result[i]=np.fft.irfft2(selected*n,s=(h,w),axes=(0,1))
            else:
                result[i]=frame
            past.append(current)
            if len(past)>=HISTORY:past.pop(0)
        records.append(dict(frame=i,epoch_start=epoch,preceding_observations=count,
            total_observations=count+1 if active[i] else 0,history_eligible=bool(active[i] and count>=MIN_PAST),
            current_frequency_fraction=float(innovation.mean()),reset=reset,jitter_changed=jitter_changed))
    return result,records


def self_checks():
    controls=np.zeros((32,3));controls[0,0]=1;active=np.ones(32,bool)
    delta=np.random.default_rng(7123).normal(0,.01,(32,8,8,3))
    a,j=spectral_delta(delta,controls,active);changed=delta.copy();changed[20:]*=2;b,_=spectral_delta(changed,controls,active)
    np.testing.assert_array_equal(a[:20],b[:20]);np.testing.assert_array_equal(a[:8],delta[:8])
    assert max(r['total_observations'] for r in j)==16
    assert a[16:].std()<.5*delta[16:].std()
    controls[12,0]=1;controls[24:,1:]=[.25,.125];a,j=spectral_delta(delta,controls,active)
    for i in (0,12,24):np.testing.assert_array_equal(a[i],delta[i]);assert j[i]['epoch_start']==i
    active[18]=False;a,j=spectral_delta(delta,controls,active)
    assert not a[18].any();np.testing.assert_array_equal(a[19],delta[19])
    # Analytic counterexample: a linearly drifting complex coefficient has
    # prediction-normalized innovation sqrt(3), always below the frozen 3 gate.
    y,x=np.indices((8,8));wave=np.cos(2*np.pi*x/8)
    ramp=np.broadcast_to(np.arange(32)[:,None,None,None]*.001*wave[None,...,None],delta.shape).copy()
    controls[:]=0;controls[0,0]=1;active[:]=True;a,j=spectral_delta(ramp,controls,active)
    expected=np.mean(ramp[-16:],axis=0)
    np.testing.assert_allclose(a[-1],expected,rtol=0,atol=1e-14)
    current=np.fft.rfft2(ramp[-1,...,0])[0,1]
    predicted=np.fft.rfft2(a[-1,...,0])[0,1]
    return dict(no_future=True,bounded_16=True,min8_current_warmup=True,reset_and_jitter_epochs=True,
        stationary_delta_noise_reduced=True,linear_coefficient_ramp_undetected=True,
        analytic_linear_ramp_prediction_rms_ratio=float(np.sqrt(3)),
        linear_ramp_filtered_current_amplitude_ratio=float(abs(predicted/current)))


def main():
    output=Path(__file__).with_name('results.json')
    if output.exists():raise ValueError('Preserve previous post-hoc analysis')
    report=dict(schema='delta-spectrum-past-only-innovation-offline-v1',status='running',
        quality_accepted=False,native_rerun=False,game_run=False,runtime_implemented=False,
        history=HISTORY,min_preceding_observations=MIN_PAST,innovation_prediction_rms_multiplier=INNOVATION_RMS,
        filter_inputs=['observable pilot minus native pilot response','native reset/jitter controls','frozen original activity'],
        self_checks=self_checks(),script_sha256=reference.digest(__file__),reference_script_sha256=reference.digest(REFERENCE),
        metric_source_sha256={name:reference.digest(reference.TESTS/name) for name in ('probe_fsrd_statistical_resolve.py','probe_fsrd_response_calibration.py','fsrd_quality_contours.py')},
        limitations=['Post-hoc reused study data; not an independent holdout or tuned estimator.',
            'Past complex variance mixes actual response change, noise and correlated RR history.',
            'Nominal prediction variance assumes temporal independence; not established.',
            '3 RMS is a frozen heuristic, not calibrated confidence or a motion guarantee.',
            'Linear coefficient drift stays below the gate and is averaged with lag.',
            'Before eight preceding observations, current delta is returned unchanged.',
            'Current source RGB enters only subsequent current-DC, never the spectral delta filter.',
            'Truth enters scores/contours only. Shared persistent bias remains unidentifiable.'],rows=[])
    for study in reference.STUDIES:
        root=reference.EVIDENCE/study;report_path=root/'results.json';report_hash=reference.digest(report_path)
        original=json.loads(report_path.read_text())
        if original['status']!='completed_research_not_solution':raise ValueError('Incomplete original native study')
        for row in original['rows']:
            scene=row['scene'];path=root/scene/'sequences.npz';sequence_hash=reference.digest(path)
            controls_path=root/scene/'observed/frame_controls.txt';controls_hash=reference.digest(controls_path)
            with np.load(path) as a:
                controls=reference.controls_from_native(controls_path,len(a['pilot']))
                filtered,diagnostics=spectral_delta(a['pilot']-a['pilot_response'],controls,a['active'])
                candidate=a['baseline']+filtered;epochs=[r['epoch_start'] for r in diagnostics]
                dc=reference.dc_conservation(candidate,a['observed'],a['active'],controls,1,epochs)
                safe,fraction=reference.radiance_fallback(dc,a['baseline']);variants={}
                for name,value,fallback in (('delta_spectral_innovation',candidate,0),('delta_spectral_innovation_dc_current',dc,0),('delta_spectral_innovation_dc_current_safe',safe,fraction)):
                    variants[name]=reference.evaluate(value,a['baseline'],a['clean_reference'],scene,a['active'],row['null_rms'],fallback)
            unchanged=(reference.digest(path)==sequence_hash and reference.digest(controls_path)==controls_hash and reference.digest(report_path)==report_hash)
            if not unchanged:raise ValueError('Original native evidence changed during read-only analysis')
            report['rows'].append(dict(study=study,scene=scene,split_strength=original.get('split_strength',0),
                source_files_unchanged=unchanged,provenance=dict(native_report_sha256=report_hash,native_sequences_sha256=sequence_hash,native_controls_sha256=controls_hash),
                diagnostics=diagnostics,null_rms=row['null_rms'],baseline_full=row['baseline_full'],baseline_mature=row['baseline_mature'],variants=variants))
            print(study,scene,{n:dict(full=v['full_gate']['failures'],mature=v['mature_gate']['failures'],rmse=v['full']['rmse']) for n,v in variants.items()},flush=True)
    report['status']='completed_posthoc_falsification_not_solution'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__=='__main__':main()
