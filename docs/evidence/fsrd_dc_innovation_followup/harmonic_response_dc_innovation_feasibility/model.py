"""Frozen source-only DC target, separate from saved-response application."""
import numpy as np
HISTORY=64;K=3.;MARGIN=5;MIN_MEAN=1e-4;MAX_RADIANCE=65504.

def make_source_dc_innovation_target(raw,controls,epoch_start_by_frame=None,exposure=None):
    c=np.asarray(raw);ctrl=np.asarray(controls,float)
    if c.ndim!=4 or c.shape[-1]!=3 or not len(c) or not np.issubdtype(c.dtype,np.floating):raise ValueError('floating N,H,W,RGB')
    if min(c.shape[1:3])<13 or ctrl.shape!=(len(c),3):raise ValueError('interior/control shape')
    epochs=None if epoch_start_by_frame is None else np.asarray(epoch_start_by_frame,float)
    ex=None if exposure is None else np.asarray(exposure,float)
    if epochs is not None and epochs.shape!=(len(c),):raise ValueError('epoch shape')
    if ex is not None and ex.shape!=(len(c),):raise ValueError('exposure shape')
    targets=np.full((len(c),3),np.nan);valid=np.zeros(len(c),bool);records=[];means=[];q=[]
    dc_epoch=0;last_jitter=None;last_source_epoch=None;last_exposure=None
    def cut(i):
        nonlocal dc_epoch
        means.clear();q.clear();dc_epoch=i
    for i,frame in enumerate(c):
        meta=bool(np.isfinite(ctrl[i]).all() and ctrl[i,0] in (0,1))
        source_epoch=None if epochs is None else epochs[i]
        if source_epoch is not None:meta=bool(meta and np.isfinite(source_epoch) and source_epoch==int(source_epoch) and 0<=source_epoch<=i and (last_source_epoch is None or source_epoch>=last_source_epoch))
        exp=None if ex is None else ex[i]
        if exp is not None:meta=bool(meta and np.isfinite(exp) and exp>0)
        source=bool(np.isfinite(frame).all() and frame.min()>=0 and frame.max()<=MAX_RADIANCE)
        reasons=[]
        if not meta or not source:
            cut(i+1);last_jitter=last_source_epoch=last_exposure=None
            records.append(dict(frame=i,valid=False,reason='invalid_source_or_metadata',dc_epoch=i,preceding_observations=0,target_RGB=None));continue
        if ctrl[i,0]:reasons.append('reset')
        if last_jitter is not None and not np.array_equal(ctrl[i,1:],last_jitter):reasons.append('jitter_change')
        if source_epoch is not None and last_source_epoch is not None and source_epoch!=last_source_epoch:reasons.append('source_epoch_change')
        if exp is not None and last_exposure is not None and exp!=last_exposure:reasons.append('exposure_change')
        if reasons:cut(i)
        last_jitter=ctrl[i,1:].copy();last_source_epoch=source_epoch;last_exposure=exp
        roi=frame[MARGIN:-MARGIN,MARGIN:-MARGIN].astype(float);mu=roi.mean((0,1));M=roi.shape[0]*roi.shape[1]
        if np.any(mu<=MIN_MEAN):
            cut(i+1);records.append(dict(frame=i,valid=False,reason='nearzero_source_mean',dc_epoch=i,preceding_observations=0,source_mean_RGB=mu.tolist(),target_RGB=None));continue
        F=np.fft.rfft2(roi-mu,axes=(0,1))/M;end=-1 if roi.shape[1]%2==0 else None
        interior=F[:,1:end,:];assert interior.size
        sigma=np.maximum(np.median(abs(interior),axis=(0,1))*np.sqrt(M/np.log(2)),np.finfo(float).eps*max(1.,float(abs(roi).max())))
        qi=sigma*sigma/M;m=len(means);innovation=False;prior=None;priorq=None;threshold=None
        if m:
            prior=np.mean(means,axis=0);priorq=np.sum(q,axis=0)/(m*m);threshold=K*np.sqrt(qi+priorq)
            innovation=bool(np.any(abs(mu-prior)>threshold))
        if innovation:
            cut(i);reasons.append('source_mean_innovation');target=mu;targetq=qi
        elif m:target=(np.sum(means,axis=0)+mu)/(m+1);targetq=(np.sum(q,axis=0)+qi)/(m+1)**2
        else:target=mu;targetq=qi
        targets[i]=target;valid[i]=True
        records.append(dict(frame=i,valid=True,reason=reasons or ['quiet_mean'],dc_epoch=dc_epoch,source_epoch=None if source_epoch is None else int(source_epoch),
            preceding_observations=m,history_used_including_current=1 if innovation else m+1,source_mean_RGB=mu.tolist(),sigma_RGB=sigma.tolist(),mean_q_RGB=qi.tolist(),
            prior_mean_RGB=None if prior is None else prior.tolist(),prior_q_RGB=None if priorq is None else priorq.tolist(),threshold_RGB=None if threshold is None else threshold.tolist(),
            innovation=innovation,target_RGB=target.tolist(),target_q_RGB=targetq.tolist(),ROI_pixels=M,proper_complex_coefficients_per_RGB=interior.shape[0]*interior.shape[1]))
        means.append(mu);q.append(qi)
        if len(means)>HISTORY-1:means.pop(0);q.pop(0)
    return targets,valid,dict(schema='final-source-DC-innovation-v1',history=HISTORY,frames=records,estimator_inputs=['raw','controls','optional_source_epoch','optional_exposure'],
        effective_independent_pixels=None,exposure_known=ex is not None,variance_scope='Source-adaptive plug-in perRGB spatial/time IID nominal only, not confidence',quality_accepted=False)

def apply_target(candidate,baseline,active,target,target_valid,safe=False):
    c=np.asarray(candidate);b=np.asarray(baseline);a=np.asarray(active);T=np.asarray(target);V=np.asarray(target_valid)
    if c.shape!=b.shape or c.ndim!=4 or c.shape[-1]!=3 or a.shape!=(len(c),) or T.shape!=(len(c),3) or V.shape!=(len(c),):raise ValueError('application shape')
    out=b.copy();records=[]
    for i in range(len(c)):
        if safe and not np.all(np.isfinite(b[i])&(b[i]>=0)&(b[i]<=MAX_RADIANCE)):raise ValueError('Invalid baseline cannot serve as radiance fallback')
        shift=np.zeros(3);fallback=np.zeros(c.shape[1:3],bool)
        if a[i] and V[i]:
            shift=T[i]-c[i,MARGIN:-MARGIN,MARGIN:-MARGIN].mean((0,1),dtype=float)
            value=c[i].copy();value+=shift
            if safe:
                fallback=~np.all(np.isfinite(value)&(value>=0)&(value<=MAX_RADIANCE),axis=-1);value=np.where(fallback[...,None],b[i],value)
            out[i]=value
        records.append(dict(frame=i,applied=bool(a[i] and V[i]),shift_RGB=shift.tolist(),fallback_pixel_fraction=float(fallback.mean()),
            target_closure_RGB=None if not (a[i] and V[i]) else (out[i,MARGIN:-MARGIN,MARGIN:-MARGIN].mean((0,1),dtype=float)-T[i]).tolist()))
    return out,dict(frames=records,atomic_fallback_pixel_fraction=float(np.mean([r['fallback_pixel_fraction'] for r in records])))
