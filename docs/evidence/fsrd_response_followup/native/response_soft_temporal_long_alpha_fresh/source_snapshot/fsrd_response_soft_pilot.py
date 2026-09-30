"""Continuous-weight source-only spectral pilot, research prototype only.

Frozen history/innovation rules match the original temporal spectral pilot.
Continuous shrinkage replaces its binary frequency support. Native response,
runtime cost and game quality require separate measurements.
"""
import numpy as np


def make_soft_temporal_spectral_pilot(raw, controls, history=16):
    """Current/past RGB and controls only; signed prediction is never clipped."""
    c=np.asarray(raw,float);ctrl=np.asarray(controls,float)
    if c.ndim!=4 or c.shape[-1]!=3 or min(c.shape[1:3])<8 or not len(c):
        raise ValueError('Expected N,H,W,RGB with at least 8x8 support')
    if not np.isfinite(c).all() or np.any(c<0) or np.any(c>65504):
        raise ValueError('Finite nonnegative representable observed RGB required')
    if ctrl.shape!=(len(c),3) or not np.isfinite(ctrl).all() or not np.isin(ctrl[:,0],[0,1]).all():
        raise ValueError('Expected finite reset,jitterX,jitterY per frame')
    if not isinstance(history,(int,np.integer)) or not 2<=history<=64:
        raise ValueError('History must count 2..64 observations including current')
    frames,h,w,_=c.shape;n=h*w;end=-1 if w%2==0 else None
    pilots=c.copy();active=np.zeros(frames,bool);records=[];epochs=[]
    spectra=[];sigmas=[];epoch=0
    for i,frame in enumerate(c):
        reset=bool(ctrl[i,0]);jitter_changed=bool(i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:]))
        if reset or jitter_changed:spectra.clear();sigmas.clear();epoch=i
        current=np.fft.rfft2(frame,axes=(0,1))/n
        sigma=max(float(np.median(abs(current[:,1:end,:])))*np.sqrt(n/np.log(2)),
            np.finfo(float).eps*max(1.,float(frame.max())))
        count=len(spectra);innovation=np.zeros(current.shape[:2],bool);innovation_limit=None
        if count:
            prior=sum(spectra)/count;prior_variance=sum(s*s for s in sigmas)/(count*count)
            innovation_limit=3*np.sqrt(sigma*sigma+prior_variance)/np.sqrt(n)
            innovation=np.any(abs(current-prior)>innovation_limit,axis=-1)
            mean=(sum(spectra)+current)/(count+1)
            mean_sigma=np.sqrt(sum(s*s for s in sigmas)+sigma*sigma)/(count+1)
        else:mean=current.copy();mean_sigma=sigma
        innovation[0,0]=False
        selected=np.where(innovation[...,None],current,mean);selected[0,0]=current[0,0]
        selected_sigma=np.where(innovation,sigma,mean_sigma)
        limit=4*selected_sigma/np.sqrt(n)
        magnitude=np.max(abs(selected),axis=-1)
        ratio=np.divide(limit,magnitude,out=np.full_like(magnitude,np.inf),where=magnitude>0)
        # max(0, 1 - (threshold / magnitude)^2) is continuous at the threshold.
        weight=np.maximum(0.,1-ratio*ratio);weight[0,0]=1.
        prediction=np.fft.irfft2(selected*weight[...,None]*n,s=(h,w),axes=(0,1))
        valid=bool(np.isfinite(prediction).all() and prediction.min()>=0 and prediction.max()<=65504)
        if valid:pilots[i]=prediction;active[i]=True
        epochs.append(epoch)
        records.append(dict(frame=i,active=valid,reason='accepted' if valid else 'invalid_unclamped_prediction',
            reset=reset,jitter_changed=jitter_changed,epoch_start=epoch,
            preceding_observations=count,total_observations=count+1,
            nominal_iid_pixel_sigma=sigma,nominal_mean_pixel_sigma=float(mean_sigma),
            current_coefficient_threshold=float(4*sigma/np.sqrt(n)),mean_coefficient_threshold=float(4*mean_sigma/np.sqrt(n)),
            innovation_threshold=innovation_limit,innovation_sigma_multiplier=3.,threshold_sigma_multiplier=4.,
            nominal_pixels=n,effective_independent_pixels=None,retained_frequencies=int(np.count_nonzero(weight)),
            total_rfft_frequencies=int(weight.size),current_innovation_frequencies=int(np.count_nonzero(innovation & (weight>0))),
            spectral_weight_min=float(weight.min()),spectral_weight_max=float(weight.max()),
            spectral_weight_sum=float(weight.sum()),spectral_weight_square_sum=float(np.sum(weight*weight)),
            prediction_min=float(prediction.min()),prediction_max=float(prediction.max()),
            signed_mean_delta_rgb=(prediction-frame).mean((0,1)).tolist()))
        spectra.append(current);sigmas.append(sigma)
        if len(spectra)>=history:spectra.pop(0);sigmas.pop(0)
    return pilots,active,dict(schema='fsrd-soft-temporal-spectral-pilot-research-v1',history=history,
        active_frames=int(active.sum()),frames=records,epoch_start_by_frame=epochs,
        quality_accepted=False,no_clean_truth_input=True,runtime_implemented=False,
        innovation_sigma_multiplier=3.,threshold_sigma_multiplier=4.,
        spectral_weight='shared RGB max(0, 1-(4 selected_sigma/sqrt(HW)/maxabs(selected_RGB))^2); DC weight 1',
        source_domain='Current and preceding observed RGB only; normalized rfft2',
        assumptions=['Periodic correctly corresponding ROI','Spatial/temporal iid approximately Gaussian noise',
            'Most pooled spectral magnitudes represent noise','Comparable channel noise scales'],
        limitations=['No independence or correspondence proof; effective independent pixels unknown',
            'Correlated source noise and dense material spectra invalidate nominal variance',
            'Weak genuine detail shrinks, especially during warmup; passing noise gates alone is insufficient',
            'Shared RGB weight can transmit weak-channel noise',
            'Nonperiodic detail leaks across frequencies; soft weighting does not remove leakage',
            'Slow subthreshold phase changes can lag; no motion compensation',
            'Innovation switching remains discrete even though spectral weighting is continuous',
            'Shared persistent source bias is unidentifiable',
            'Invalid signed prediction falls back to current RGB for the whole frame, without clipping',
            'No native/model/game/cost acceptance from CPU tests alone'])
