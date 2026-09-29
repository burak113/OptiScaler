"""Fixed last-16 observable response-delta experiment, offline only.

Filter inputs exclude truth and source RGB. Current source RGB is used only by
the separately declared current-DC constraint. Truth enters measurement calls.
Original studies and their native sequences are never modified or rerun.
"""
from pathlib import Path
import hashlib,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
sys.path.insert(0,str(TESTS))
from probe_fsrd_statistical_resolve import score,acceptance
from probe_fsrd_response_calibration import dc_conservation,radiance_fallback
from fsrd_quality_contours import island_contours,contour_gate

EVIDENCE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce')
STUDIES=('response_spectral_primary','response_temporal_spectral_primary','response_temporal_spectral_alpha_holdout')
HISTORY=16


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def smooth_delta(delta,controls,active):
    """Only signed observable delta and immutable correspondence controls."""
    delta=np.asarray(delta,float);controls=np.asarray(controls,float);active=np.asarray(active,bool)
    if delta.ndim!=4 or delta.shape[-1]!=3 or controls.shape!=(len(delta),3) or active.shape!=(len(delta),):
        raise ValueError('Invalid delta/control/activity dimensions')
    if not np.isfinite(delta).all() or not np.isfinite(controls).all() or not np.isin(controls[:,0],[0,1]).all():
        raise ValueError('Nonfinite delta or invalid controls')
    result=np.zeros_like(delta);epochs=[];counts=[];past=[];epoch=0
    for i,current in enumerate(delta):
        if controls[i,0] or (i and not np.array_equal(controls[i,1:],controls[i-1,1:])) or not active[i]:
            past.clear();epoch=i
        if active[i]:
            past.append(current)
            if len(past)>HISTORY:past.pop(0)
            result[i]=sum(past)/len(past)
        epochs.append(epoch);counts.append(len(past))
    return result,epochs,counts


def controls_from_native(path,frames):
    controls=np.loadtxt(path,dtype=float,ndmin=2)
    if controls.shape!=(frames,3) or not np.isfinite(controls).all() or not np.isin(controls[:,0],[0,1]).all():
        raise ValueError('Invalid stored native controls')
    return controls


def self_checks():
    delta=np.random.default_rng(7123).normal(0,.01,(32,8,8,3));controls=np.zeros((32,3));controls[0,0]=1
    active=np.ones(32,bool);a,ep,ct=smooth_delta(delta,controls,active)
    changed=delta.copy();changed[20:]*=2;b,_,_=smooth_delta(changed,controls,active)
    np.testing.assert_array_equal(a[:20],b[:20]);assert max(ct)==16
    controls[12,0]=1;controls[24:,1:]=[.25,.125];a,ep,ct=smooth_delta(delta,controls,active)
    for i in (0,12,24):np.testing.assert_array_equal(a[i],delta[i]);assert ep[i]==i and ct[i]==1
    active[18]=False;a,ep,ct=smooth_delta(delta,controls,active)
    assert not a[18].any();np.testing.assert_array_equal(a[19],delta[19])
    # A known delta step exposes lag without truth or source observations.
    step=np.zeros_like(delta);step[16:]=1;controls[:]=0;controls[0,0]=1
    a,_,_=smooth_delta(step,controls,np.ones(32,bool));assert float(a[16,0,0,0])==1/16
    return dict(no_future=True,bounded_16=True,reset_and_jitter_epochs=True,inactive_baseline=True,known_delta_step_lag=True)


def evaluate(value,baseline,truth,scene,active,null_rms,fallback_fraction):
    activity=float(np.mean(abs(value-baseline)>1e-5))
    full=score(value,truth,None);mature=score(value[-16:],truth[-16:],None)
    bf=score(baseline,truth,None);bm=score(baseline[-16:],truth[-16:],None)
    fg=acceptance(full,bf,activity,null_rms,scene);mg=acceptance(mature,bm,activity,null_rms,scene)
    invalid=~np.all(np.isfinite(value)&(value>=0)&(value<=65504),axis=-1)
    if invalid.any():
        for gate in (fg,mg):gate['failures'].append('invalid_radiance');gate['nonregression']=gate['effective_success']=False
    contour=None
    if scene.startswith('fake_'):
        cc=island_contours(value,truth);bc=island_contours(baseline,truth);cg=contour_gate(cc,bc,value.shape[2],value.shape[1])
        contour=dict(candidate=cc,baseline=bc,gate=cg)
        if not cg['passed']:
            for gate in (fg,mg):gate['failures'].append('extended_stain_area');gate['nonregression']=gate['effective_success']=False
    return dict(full=full,mature=mature,full_gate=fg,mature_gate=mg,activity=activity,
        invalid_pixel_fraction=float(invalid.mean()),baseline_fallback_pixel_fraction=fallback_fraction,contour=contour)


def main():
    output=Path(__file__).with_name('results.json')
    if output.exists():raise ValueError('Preserve previous offline results')
    report=dict(schema='observable-response-delta-causal-mean-offline-v1',history=HISTORY,
        filtering_precision='float64 signed delta, mean includes current',quality_accepted=False,game_run=False,runtime_implemented=False,
        thresholds_changed=False,native_rerun=False,self_checks=self_checks(),script_sha256=digest(__file__),
        metric_source_sha256={name:digest(TESTS/name) for name in ('probe_fsrd_statistical_resolve.py','probe_fsrd_response_calibration.py','fsrd_quality_contours.py')},
        filter_inputs=['observable pilot minus native pilot response','native reset/jitter controls','frozen original activity mask'],
        limitations=['Corresponding static response-delta history is assumed, not established by frame count.',
            'Phase/lighting/material transitions without reset can lag; no innovation threshold or tuning.',
            'Current source RGB enters only the separate current-DC constraint, never the delta mean.',
            'Truth enters scores/contours only, never either filter.',
            'Each invalid RGB pixel falls back atomically to its native baseline; no clamp.',
            'Observed null variation is reused from the original native study, not a confidence interval.',
            'Frozen synthetic studies; this is not general game-quality acceptance.'],rows=[],source_files_unchanged=True)
    for study in STUDIES:
        folder=EVIDENCE/study;original=folder/'results.json';study_hash=digest(original);j=json.loads(original.read_text())
        if j['status']!='completed_research_not_solution':raise ValueError('Incomplete source study')
        for row in j['rows']:
            scene=row['scene'];path=folder/scene/'sequences.npz';sequence_hash=digest(path)
            control_path=folder/scene/'observed/frame_controls.txt';control_hash=digest(control_path)
            with np.load(path) as a:
                delta=a['pilot']-a['pilot_response'];baseline=a['baseline'].copy();active=a['active'].copy()
                controls=controls_from_native(control_path,len(delta))
                mean_delta,epochs,counts=smooth_delta(delta,controls,active)
                candidate=baseline+mean_delta
                # Source RGB is first introduced here, AFTER smoothing delta.
                current_dc=dc_conservation(candidate,a['observed'],active,controls,1,epochs)
                safe,fraction=radiance_fallback(current_dc,baseline)
                variants={}
                for name,value,fallback in (('delta_mean16',candidate,0),('delta_mean16_dc_current',current_dc,0),('delta_mean16_dc_current_safe',safe,fraction)):
                    # Clean reference is accessed only for measurement calls.
                    variants[name]=evaluate(value,baseline,a['clean_reference'],scene,active,row['null_rms'],fallback)
            unchanged=digest(path)==sequence_hash and digest(control_path)==control_hash and digest(original)==study_hash
            if not unchanged:raise ValueError('Original source evidence changed during read-only analysis')
            report['rows'].append(dict(study=study,scene=scene,split_strength=j.get('split_strength',0),
                provenance=dict(native_report_sha256=study_hash,native_sequences_sha256=sequence_hash,native_controls_sha256=control_hash),
                epoch_start_by_frame=epochs,total_observations_by_frame=counts,source_files_unchanged=unchanged,
                baseline_full=row['baseline_full'],baseline_mature=row['baseline_mature'],null_rms=row['null_rms'],
                original_variants={name:dict(full_gate=v['full_gate'],mature_gate=v['mature_gate'],full=v['full'],mature=v['mature']) for name,v in row['variants'].items()},
                variants=variants))
            print(study,scene,{name:dict(full=v['full_gate']['failures'],mature=v['mature_gate']['failures'],rmse=v['full']['rmse']) for name,v in variants.items()},flush=True)
    report['status']='completed_offline_falsification_not_solution'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__=='__main__':main()
