"""Frozen causal conditional response calibration; posthoc, no native rerun.

Regress observable delta spectra on the current/past pilot spectra, with
source-only nominal coefficient variance as a fixed ridge prior. A second
variant admits an age trend when its nominal residual-standard-error ratio
exceeds four. Neither criterion establishes independence or confidence.
"""
from pathlib import Path
import importlib.util
import json
import numpy as np

REFERENCE = Path(__file__).resolve().parents[1]/'delta_history_offline_20260930/analyze.py'
spec = importlib.util.spec_from_file_location('delta_reference', REFERENCE)
reference = importlib.util.module_from_spec(spec); spec.loader.exec_module(reference)
HISTORY = 16
MIN_COUNT = 8
RIDGE_VARIANCE_MULTIPLIER = 4.0
AGE_STANDARD_ERROR_MULTIPLIER = 4.0


def calibrate(pilot, response, observed, controls, active, age_trend=False):
    p=np.asarray(pilot,float);r=np.asarray(response,float);raw=np.asarray(observed,float)
    ctrl=np.asarray(controls,float);active=np.asarray(active,bool)
    if p.ndim!=4 or p.shape[-1]!=3 or p.shape!=r.shape or p.shape!=raw.shape or min(p.shape[1:3])<8:
        raise ValueError('Expected equal finite N,H,W,RGB sources')
    if ctrl.shape!=(len(p),3) or active.shape!=(len(p),) or not np.isin(ctrl[:,0],[0,1]).all():
        raise ValueError('Invalid reset/jitter/activity controls')
    if not all(np.isfinite(a).all() for a in (p,r,raw,ctrl)):
        raise ValueError('Nonfinite observable input')
    n=p.shape[1]*p.shape[2];h,w=p.shape[1:3];end=-1 if w%2==0 else None
    result=np.zeros_like(p);history=[];epoch=0;records=[]
    for i in range(len(p)):
        if ctrl[i,0] or (i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:])) or not active[i]:
            history.clear();epoch=i
        if not active[i]:
            records.append(dict(frame=i,epoch=epoch,count=0,age_frequency_fraction=0));continue
        z=np.fft.rfft2(p[i],axes=(0,1))/n
        y=np.fft.rfft2(p[i]-r[i],axes=(0,1))/n
        source=np.fft.rfft2(raw[i],axes=(0,1))/n
        median=float(np.median(abs(source[:,1:end])))
        nominal_variance=max(median**2/np.log(2),
            (np.finfo(float).eps*max(1,float(abs(raw[i]).max())))**2/n)
        history.append((z,y,nominal_variance))
        if len(history)>HISTORY:history.pop(0)
        m=len(history);fraction=0.0
        if m<MIN_COUNT:
            result[i]=p[i]-r[i]
        else:
            zs=np.stack([a[0] for a in history]);ys=np.stack([a[1] for a in history])
            zm=zs.mean(0);ym=ys.mean(0);zc=zs-zm;yc=ys-ym
            ridge=RIDGE_VARIANCE_MULTIPLIER*np.mean([a[2] for a in history])
            vz=np.mean(abs(zc)**2,axis=0)+ridge
            cov=np.mean(np.conj(zc)*yc,axis=0)
            a=cov/vz
            prediction=ym+a*(z-zm)
            if age_trend:
                tc=(np.arange(m,dtype=float)-(m-1)/2)[:,None,None,None]
                vt=float(np.mean(tc**2));zt=np.mean(np.conj(zc)*tc,axis=0)
                ty=np.mean(tc*yc,axis=0)
                determinant=np.maximum(vz*vt-abs(zt)**2,np.finfo(float).tiny)
                joint_a=(cov*vt-zt*ty)/determinant
                joint_b=(vz*ty-np.conj(zt)*cov)/determinant
                fitted=joint_a[None]*zc+joint_b[None]*tc
                residual=np.sum(abs(yc-fitted)**2,axis=0)/max(m-3,1)
                # Conditional age information; a ridge prior is not a sample.
                age_information=np.maximum(vt-abs(zt)**2/vz,np.finfo(float).tiny)
                se=np.sqrt(residual/(m*age_information))
                numeric=np.finfo(float).eps*np.maximum(1,abs(ym))
                selected=np.any(abs(joint_b)>AGE_STANDARD_ERROR_MULTIPLIER*np.maximum(se,numeric),axis=-1)
                joint=ym+joint_a*(z-zm)+joint_b*(m-1)/2
                prediction=np.where(selected[...,None],joint,prediction)
                fraction=float(selected.mean())
            result[i]=np.fft.irfft2(prediction*n,s=(h,w),axes=(0,1))
        records.append(dict(frame=i,epoch=epoch,count=m,age_frequency_fraction=fraction))
    return result,records


def self_checks():
    rng=np.random.default_rng(24621);shape=(40,8,8,3)
    p=np.full(shape,.2)+rng.normal(0,.003,shape);r=.85*p+.004
    ctrl=np.zeros((40,3));ctrl[0,0]=1;active=np.ones(40,bool)
    for age in (False,True):
        a,j=calibrate(p,r,p,ctrl,active,age)
        changed=r.copy();changed[25:]+=.1;b,_=calibrate(p,changed,p,ctrl,active,age)
        np.testing.assert_array_equal(a[:25],b[:25]);assert max(v['count'] for v in j)==16
        ctrl[12,0]=1;ctrl[24:,1]=.25
        a,j=calibrate(p,r,p,ctrl,active,age)
        for index in (0,12,24):np.testing.assert_array_equal(a[index],p[index]-r[index]);assert j[index]['count']==1
        active[30]=False;a,j=calibrate(p,r,p,ctrl,active,age)
        assert not a[30].any();np.testing.assert_array_equal(a[31],p[31]-r[31])
        active[:]=True;ctrl[:]=0;ctrl[0,0]=1
    # A pure delta ramp with constant pilot has no light variation to regress on.
    p[:]=.2;y,x=np.indices((8,8));wave=np.cos(2*np.pi*x/8)
    delta=np.arange(40)[:,None,None,None]*.0001*wave[None,...,None]*np.ones((1,1,1,3))
    a,j=calibrate(p,p-delta,p,ctrl,active,True)
    np.testing.assert_allclose(a[-1],delta[-1],rtol=0,atol=1e-14)
    # Rotating illumination is predicted by complex pilot conditioning, not time averaging.
    p=np.full(shape,.2)+.02*np.cos(2*np.pi*x/8+.8*np.arange(40)[:,None,None])[...,None]*np.ones((1,1,1,3))
    r=.8*p+.003
    a,j=calibrate(p,r,p,ctrl,active,False)
    np.testing.assert_allclose(a[-1],p[-1]-r[-1],rtol=0,atol=1e-12)
    return dict(no_future=True,bounded16=True,reset_jitter_epochs=True,inactive_baseline=True,
                age_ramp_predicted=True,rotating_light_predicted=True)


def main():
    output=Path(__file__).with_name('results.json')
    if output.exists():raise ValueError('Use fresh evidence directory')
    report=dict(schema='response-affine-spectrum-posthoc-v1',status='running',history=HISTORY,min_count=MIN_COUNT,
        ridge_variance_multiplier=RIDGE_VARIANCE_MULTIPLIER,age_standard_error_multiplier=AGE_STANDARD_ERROR_MULTIPLIER,
        native_rerun=False,quality_accepted=False,game_run=False,runtime_implemented=False,
        script_sha256=reference.digest(__file__),reference_script_sha256=reference.digest(REFERENCE),
        self_checks=self_checks(),rows=[],limitations=[
            'Posthoc reuse; not independent acceptance or parameter tuning.',
            'Complex per-frequency affine response assumes stationary correspondences and guide-conditioned transfer.',
            'Nonlocal/nonlinear transfer and phase thresholds can violate the model.',
            'Source spectral median is nominal variance, not calibrated physical noise.',
            'Current-inclusive fit can attenuate noise but uses the current noisy response.',
            'Age significance assumes independent residuals, which native history does not establish.',
            'No motion reprojection or full-game context lifetime/cost validation.',
            'Truth is used by measurement only; shared source bias is unidentifiable.'])
    for study in reference.STUDIES:
        folder=reference.EVIDENCE/study;report_path=folder/'results.json';rh=reference.digest(report_path)
        original=json.loads(report_path.read_text())
        for row in original['rows']:
            scene=row['scene'];path=folder/scene/'sequences.npz';sh=reference.digest(path)
            control=folder/scene/'observed/frame_controls.txt';ch=reference.digest(control)
            with np.load(path) as arrays:
                ctrl=reference.controls_from_native(control,len(arrays['pilot']));variants={};diagnostics={}
                for label,age in (('affine_pilot',False),('affine_pilot_age',True)):
                    filtered,records=calibrate(arrays['pilot'],arrays['pilot_response'],arrays['observed'],ctrl,arrays['active'],age)
                    value=arrays['baseline']+filtered
                    dc=reference.dc_conservation(value,arrays['observed'],arrays['active'],ctrl,1,[v['epoch'] for v in records])
                    safe,fraction=reference.radiance_fallback(dc,arrays['baseline'])
                    for name,v,f in ((label,value,0),(label+'_dc_current',dc,0),(label+'_dc_current_safe',safe,fraction)):
                        variants[name]=reference.evaluate(v,arrays['baseline'],arrays['clean_reference'],scene,arrays['active'],row['null_rms'],f)
                    diagnostics[label]=records
            unchanged=all((reference.digest(p)==digest) for p,digest in ((path,sh),(control,ch),(report_path,rh)))
            if not unchanged:raise ValueError('Source evidence changed')
            report['rows'].append(dict(study=study,scene=scene,split_strength=original.get('split_strength',0),source_files_unchanged=unchanged,
                provenance=dict(report_sha256=rh,sequences_sha256=sh,controls_sha256=ch),variants=variants,diagnostics=diagnostics,
                baseline_full=row['baseline_full'],baseline_mature=row['baseline_mature'],null_rms=row['null_rms']))
            print(study,scene,{k:(v['full_gate']['failures'],v['mature_gate']['failures']) for k,v in variants.items()},flush=True)
    report['status']='completed_posthoc_not_solution'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__=='__main__':main()
