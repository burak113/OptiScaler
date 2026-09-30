"""Test-only causal single-surface response pilot, never a runtime option.

Reference: rr_reassessment_14b7/response_calibration.py::fit_pilot, reviewed
against commit 14b7cc16. Cross-moments use preceding even/odd observations;
noise propagation keeps the complete guide covariance. NumPy whitening replaces
the package's SciPy generalized eigensolver. Independent even/odd noise and
correct temporal/surface correspondence are experimental assumptions, NOT facts
inferred from arrays or frame count. No clean-reference argument is accepted.

Innovation gates are explicit heuristic falsification guards, not statistical
confidence bounds. Shared persistent source bias is not identifiable. Current
guide evaluation cannot restore lighting structure absent from those guides.
"""
import numpy as np

MIN_HISTORY = 8


def _fit(color, diffuse, specular, current_diffuse, current_specular, mask):
    """Full guide covariance, signed affine net color; no per-lobe claim."""
    c,d,s=(np.asarray(a,float) for a in (color,diffuse,specular))
    cd,cs=(np.asarray(a,float) for a in (current_diffuse,current_specular))
    f=np.stack((d,s),-1);prediction=np.empty_like(cd);coefficients=[];ranks=[]
    for ch in range(3):
        xa=f[::2,...,ch,:].mean(0)[mask]
        xb=f[1::2,...,ch,:].mean(0)[mask]
        ya=c[::2,...,ch].mean(0)[mask];yb=c[1::2,...,ch].mean(0)[mask]
        ma,mb=xa.mean(0),xb.mean(0);yma,ymb=ya.mean(),yb.mean()
        aa,bb=xa-ma,xb-mb
        cov=(aa.T@bb+bb.T@aa)/(2*len(xa))
        rhs=(aa.T@(yb-ymb)+bb.T@(ya-yma))/(2*len(xa))
        delta=aa-bb;noise=delta.T@delta/(4*len(xa))
        regularizer=max(1e-12,float(np.trace(noise))*1e-6)
        ev,vec=np.linalg.eigh(noise+regularizer*np.eye(2))
        whitening=(vec/np.sqrt(ev))@vec.T
        values,directions=np.linalg.eigh(whitening@cov@whitening)
        keep=values>4.0 # Original research SNR rule, not calibrated probability.
        v=whitening@directions[:,keep]
        beta=v@np.linalg.solve(v.T@cov@v,v.T@rhs) if keep.any() else np.zeros(2)
        intercept=.5*(yma+ymb)-.5*(ma+mb)@beta
        prediction[...,ch]=intercept+cd[...,ch]*beta[0]+cs[...,ch]*beta[1]
        coefficients.append([float(intercept),*map(float,beta)]);ranks.append(int(keep.sum()))
    return prediction,dict(coefficients=coefficients,ranks=ranks)


def _innovation(current,pilot,past,mask):
    error=(current-pilot)[mask];n=int(mask.sum())
    limits=.003+4*error.std(0)/np.sqrt(n)
    mean_changed=bool(np.any(abs(error.mean(0))>limits))
    noise=np.median(np.std(np.diff(past,axis=0),axis=0)[mask],axis=0)/np.sqrt(2)
    rms=np.sqrt(np.mean(error*error,axis=0))
    spatial_changed=bool(np.any(rms>1.5*noise+.003))
    return not(mean_changed or spatial_changed),dict(mean_changed=mean_changed,
        spatial_changed=spatial_changed,residual_mean_rgb=error.mean(0).tolist(),
        residual_rms_rgb=rms.tolist(),source_noise_rgb=noise.tolist())


def make_pilot(raw,diff,spec,controls,history=16,valid_masks=None):
    """Return pilots[N,H,W,3], active[N] bool, JSON diagnostics.

    controls[N,3] is reset,jitterX,jitterY. Jitter is recorded, not corrected by
    this static-surface experiment. valid_masks[N,H,W] must be caller-supplied
    correct aligned single-surface validity. Unsupported pixels retain current
    raw. The caller must mask the final response correction too; a spatial AMD
    filter can cross mask boundaries. A new invocation owns a fresh bounded
    history. This does not implement game reprojection or in-context DRS.
    """
    raw,diff,spec=(np.asarray(a,float) for a in (raw,diff,spec))
    controls=np.asarray(controls,float)
    if raw.ndim!=4 or raw.shape[-1]!=3 or diff.shape!=raw.shape or spec.shape!=raw.shape:
        raise ValueError('Expected matching N,H,W,RGB source arrays')
    frames,h,w,_=raw.shape
    if not frames or min(h,w)<4 or controls.shape!=(frames,3):
        raise ValueError('Invalid dimensions or reset/jitter controls')
    if not np.isfinite(raw).all() or np.any(raw<0) or np.any(raw>65504):
        raise ValueError('Finite nonnegative representable source RGB required')
    if not np.isfinite(controls).all() or not np.isin(controls[:,0],[0,1]).all():
        raise ValueError('Invalid reset/jitter controls')
    if not isinstance(history,(int,np.integer)) or not MIN_HISTORY<=history<=64:
        raise ValueError('History must be bounded to 8..64 preceding observations')
    masks=np.ones((frames,h,w),bool) if valid_masks is None else np.asarray(valid_masks,bool)
    if masks.shape!=(frames,h,w):raise ValueError('Invalid correspondence masks')
    guide_valid=(np.isfinite(diff).all(-1)&np.isfinite(spec).all(-1)&
                 (diff>=0).all(-1)&(spec>=0).all(-1)&(diff<=1).all(-1)&(spec<=1).all(-1))
    masks=masks&guide_valid
    # Excluded guides must not contaminate temporal means at supported pixels.
    safe_d=np.where(np.isfinite(diff),diff,0);safe_s=np.where(np.isfinite(spec),spec,0)
    pilot=raw.copy();active=np.zeros(frames,bool);indices=[];records=[]
    epoch_start=0;epochs=[]
    for i in range(frames):
        if controls[i,0]:indices.clear();epoch_start=i
        record=dict(frame=i,reset=bool(controls[i,0]),jitter=controls[i,1:].tolist(),
                    preceding_observations=len(indices),active=False,reason='early_history')
        if masks[i].sum()<16:
            indices.clear();epoch_start=i+1;record['reason']='invalid_current_support'
            epochs.append(epoch_start);records.append(record);continue
        if len(indices)>=MIN_HISTORY:
            support=masks[i]&np.all(masks[indices],axis=0)
            record['surface_samples']=int(support.sum())
            if support.sum()<16:
                record['reason']='invalid_history_support';indices.clear();epoch_start=i
            else:
                p,info=_fit(raw[indices],safe_d[indices],safe_s[indices],safe_d[i],safe_s[i],support)
                record.update(info)
                valid=bool(np.isfinite(p[support]).all() and np.min(p[support])>=0 and np.max(p[support])<=65504)
                if valid:
                    ok,innovation=_innovation(raw[i],p,raw[indices],support)
                    record['innovation']=innovation
                    if ok:
                        pilot[i,support]=p[support];active[i]=True
                        record.update(active=True,reason='accepted')
                    else:
                        record['reason']='innovation_rejected';indices.clear();epoch_start=i
                else:
                    record['reason']='invalid_prediction';indices.clear();epoch_start=i
        indices.append(i);indices=indices[-history:];epochs.append(epoch_start);records.append(record)
    diagnostics=dict(schema='fsrd-response-pilot-research-v1',history=history,min_history=MIN_HISTORY,
        source='rr_reassessment_14b7/response_calibration.py::fit_pilot; NumPy covariance whitening',
        no_clean_truth_input=True,quality_accepted=False,
        assumptions=['one connected surface','correct prior correspondence and exposure',
                     'independent even/odd preceding observation noise'],
        limitations=['No game motion or reflection-layer estimator','No automatic noise independence proof',
                     'Persistent shared source bias is unidentifiable','Current guide noise can enter prediction',
                     'Global support can fail on multiple layers','Innovation is heuristic, not confidence',
                     'No restoration of guide-independent waves','No HLSL/runtime or DRS implementation'],
        active_frames=int(active.sum()),epoch_start_by_frame=epochs,frames=records)
    return pilot,active,diagnostics


def make_constant_pilot(raw, *, require_flat=False, diff=None, spec=None, guard_guides=False):
    """Current observed spatial RGB mean from frame zero; no clean truth.

    The optional flat classifier is a falsification heuristic: spatially iid
    noise is assumed for its mixed-derivative MAD/binomial-band estimate. It
    cannot certify that low-contrast material detail is absent or that coarse
    correlated noise is structure. Same-frame source confounding remains open.
    Pilots stay constant even on rejected frames so the counterfactual context
    does not switch raw/constant representation with the acceptance gate.
    """
    c=np.asarray(raw,float)
    if c.ndim!=4 or c.shape[-1]!=3 or min(c.shape[1:3])<8 or not len(c):
        raise ValueError('Expected N,H,W,RGB with at least 8x8 support')
    if not np.isfinite(c).all() or np.any(c<0) or np.any(c>65504):
        raise ValueError('Finite representable nonnegative observed RGB required')
    guides=None
    if guard_guides:
        if diff is None or spec is None:
            raise ValueError('Guide rejection requires diffuse and specular source RGB')
        guides=[np.asarray(a,float) for a in (diff,spec)]
        if any(a.shape!=c.shape for a in guides):raise ValueError('Mismatched source guides')
    means=c.mean((1,2));pilot=np.broadcast_to(means[:,None,None,:],c.shape).copy()
    active=np.ones(len(c),bool);records=[];kernel=np.array([1,4,6,4,1])/16
    for i,frame in enumerate(c):
        mixed=frame[:-1,:-1]-frame[1:,:-1]-frame[:-1,1:]+frame[1:,1:]
        centered=mixed-np.median(mixed,axis=(0,1))
        noise=np.median(abs(centered),axis=(0,1))/(2*.6744897501960817)
        low=sum(weight*frame[j:frame.shape[0]-4+j] for j,weight in enumerate(kernel))
        low=sum(weight*low[:,j:frame.shape[1]-4+j] for j,weight in enumerate(kernel))
        band=np.std(low,axis=(0,1));limit=1.5*noise*np.sum(kernel*kernel)+.001
        flat=bool(np.all(band<=limit))
        active[i]=flat if require_flat else True
        record=dict(frame=i,active=bool(active[i]),flat=flat,source_mean_rgb=means[i].tolist(),
            iid_noise_estimate_rgb=noise.tolist(),lowband_std_rgb=band.tolist(),limit_rgb=limit.tolist())
        if guard_guides:
            # Frozen before independent native holdout: |rho|>.2 AND nominal
            # Fisher z>4. The nominal spatial-iid count is not effective support
            # for game noise. Significant coupling ONLY vetoes correction; it
            # never becomes evidence of a physical material or a better pilot.
            valid=all(np.isfinite(g[i]).all() and np.min(g[i])>=0 and np.max(g[i])<=1 for g in guides)
            correlations=[];nominal_z=[];n=frame.shape[0]*frame.shape[1]
            for g in guides if valid else []:
                a=frame.reshape(-1,3);b=g[i].reshape(-1,3)
                a=a-a.mean(0);b=b-b.mean(0)
                denom=np.sqrt(np.sum(a*a,axis=0)*np.sum(b*b,axis=0))
                rho=np.divide(np.sum(a*b,axis=0),denom,out=np.zeros(3),where=denom>1e-20)
                z=abs(np.arctanh(np.clip(rho,-1+1e-12,1-1e-12)))*np.sqrt(max(n-3,1))
                correlations.append(rho.tolist());nominal_z.append(z.tolist())
            reject=(not valid or any(np.any((abs(np.array(rho))>.2)&(np.array(z)>4))
                    for rho,z in zip(correlations,nominal_z)))
            active[i]=bool(active[i] and not reject);record['active']=bool(active[i])
            record['guide_rejection']=dict(rejected=bool(reject),valid=bool(valid),
                rho_diffuse_specular_rgb=correlations,nominal_iid_fisher_z=nominal_z,
                nominal_spatial_samples=n,effective_spatial_samples=None,
                absolute_correlation_limit=.2,nominal_fisher_z_limit=4.)
        records.append(record)
    return pilot,active,dict(schema='fsrd-constant-response-pilot-research-v1',
        require_flat=require_flat,guard_guides=guard_guides,active_frames=int(active.sum()),frames=records,
        quality_accepted=False,no_clean_truth_input=True,
        assumptions=['one correctly delimited connected surface','spatial iid noise for flat heuristic'],
        limitations=['Not a runtime surface classifier','Same-frame source confounding',
            'Low-contrast or Nyquist real material can pass flat test','Persistent shared source bias is unidentifiable',
            'Guide correlation only rejects; it does not identify physical texture',
            'Effective spatial sample count is unknown; Fisher z assumes iid nominal support',
            'Weak texture below the correlation cutoff can remain eligible',
            'Constant pilot can miscorrect genuine guide-dependent material','No Floor/upscaler/game acceptance'])


def make_spectral_pilot(raw):
    """Independent current-source appearance hypothesis, test-only.

    Frozen before native measurement: normalize rfft2 by H*W; pool non-boundary
    RGB coefficient magnitudes for the Rayleigh median iid nominal pixel sigma;
    retain a frequency for all RGB if any channel exceeds 4*sigma/sqrt(H*W).
    DC is always retained. No truth, guides, histories, phase estimator, clipping
    or threshold optimization. A real scene is not guaranteed periodic or iid.
    """
    c=np.asarray(raw,float)
    if c.ndim!=4 or c.shape[-1]!=3 or min(c.shape[1:3])<8 or not len(c):
        raise ValueError('Expected N,H,W,RGB with at least 8x8 support')
    if not np.isfinite(c).all() or np.any(c<0) or np.any(c>65504):
        raise ValueError('Finite nonnegative representable observed RGB required')
    frames,h,w,_=c.shape;n=h*w
    spectrum=np.fft.rfft2(c,axes=(1,2))/n
    pilots=c.copy();active=np.zeros(frames,bool);records=[]
    # Real-only/conjugate boundary columns are not Rayleigh noise samples.
    end=-1 if w%2==0 else None
    for i in range(frames):
        amplitudes=abs(spectrum[i])
        median=float(np.median(amplitudes[:,1:end,:]))
        numeric_floor=np.finfo(float).eps*max(1.,float(c[i].max()))
        sigma=max(median*np.sqrt(n/np.log(2)),numeric_floor)
        threshold=4*sigma/np.sqrt(n)
        keep=np.any(amplitudes>threshold,axis=-1);keep[0,0]=True
        filtered=spectrum[i]*keep[...,None]
        prediction=np.fft.irfft2(filtered*n,s=(h,w),axes=(0,1))
        valid=bool(np.isfinite(prediction).all() and np.min(prediction)>=0 and np.max(prediction)<=65504)
        if valid:pilots[i]=prediction;active[i]=True
        records.append(dict(frame=i,active=valid,reason='accepted' if valid else 'invalid_unclamped_prediction',
            nominal_iid_pixel_sigma=sigma,median_coefficient_amplitude=median,
            coefficient_threshold=threshold,threshold_sigma_multiplier=4.,
            nominal_pixels=n,effective_independent_pixels=None,
            retained_frequencies=int(keep.sum()),total_rfft_frequencies=int(keep.size),
            prediction_min=float(np.min(prediction)),prediction_max=float(np.max(prediction)),
            signed_mean_delta_rgb=(prediction-c[i]).mean((0,1)).tolist(),
            negative_prediction_fraction=float(np.mean(prediction<0))))
    return pilots,active,dict(schema='fsrd-spectral-response-pilot-research-v1',
        active_frames=int(active.sum()),frames=records,quality_accepted=False,no_clean_truth_input=True,
        threshold_sigma_multiplier=4.,source_domain='current observed RGB only; normalized rfft2',
        assumptions=['Periodic ROI','Spatial iid approximately Gaussian marginal noise',
                     'Most pooled spectral magnitudes represent noise','Comparable channel noise scales'],
        limitations=['No independence or correspondence proof','No scene boundary/motion model',
            'Shared persistent source bias is unidentifiable','Nonperiodic detail leaks across frequencies',
            'Noise selected by its own amplitude can enter pilot','RGB common mask can carry weak-channel noise',
            'Coarse correlated noise and dense material spectra invalidate noise calibration',
            'Threshold crossings can flicker; no temporal smoothing','No HLSL/runtime/game acceptance'])


def make_temporal_spectral_pilot(raw,controls,history=16):
    """Frozen causal spectral experiment; no truth, guide or future input.

    History counts current plus preceding observations. Innovation compares
    current coefficients to ONLY the preceding mean, using nominal complex
    coefficient RMS noise. Any RGB innovation beyond 3 RMS selects current for
    all channels of that frequency; otherwise use the causal mean. Shared keep
    support is current 4 RMS OR mean 4 RMS. DC is always current. Exact jitter
    changes and reset controls end correspondence, without reprojecting pixels.
    """
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
        if reset or jitter_changed:
            spectra.clear();sigmas.clear();epoch=i
        current=np.fft.rfft2(frame,axes=(0,1))/n
        sigma=max(float(np.median(abs(current[:,1:end,:])))*np.sqrt(n/np.log(2)),
                  np.finfo(float).eps*max(1.,float(frame.max())))
        count=len(spectra);current_limit=4*sigma/np.sqrt(n)
        innovation=np.zeros(current.shape[:2],bool);innovation_limit=None
        if count:
            prior=sum(spectra)/count
            prior_variance=sum(s*s for s in sigmas)/(count*count)
            innovation_limit=3*np.sqrt(sigma*sigma+prior_variance)/np.sqrt(n)
            innovation=np.any(abs(current-prior)>innovation_limit,axis=-1)
            mean=(sum(spectra)+current)/(count+1)
            mean_sigma=np.sqrt(sum(s*s for s in sigmas)+sigma*sigma)/(count+1)
        else:
            mean=current.copy();mean_sigma=sigma
        mean_limit=4*mean_sigma/np.sqrt(n)
        keep=np.any(abs(current)>current_limit,axis=-1)|np.any(abs(mean)>mean_limit,axis=-1)
        keep[0,0]=True;innovation[0,0]=False
        selected=np.where(innovation[...,None],current,mean)
        selected[0,0]=current[0,0]
        prediction=np.fft.irfft2(selected*keep[...,None]*n,s=(h,w),axes=(0,1))
        valid=bool(np.isfinite(prediction).all() and np.min(prediction)>=0 and np.max(prediction)<=65504)
        if valid:pilots[i]=prediction;active[i]=True
        epochs.append(epoch)
        records.append(dict(frame=i,active=valid,reason='accepted' if valid else 'invalid_unclamped_prediction',
            reset=reset,jitter_changed=jitter_changed,epoch_start=epoch,
            preceding_observations=count,total_observations=count+1,
            nominal_iid_pixel_sigma=sigma,nominal_mean_pixel_sigma=float(mean_sigma),
            coefficient_threshold=current_limit,mean_coefficient_threshold=float(mean_limit),
            innovation_threshold=innovation_limit,innovation_sigma_multiplier=3.,threshold_sigma_multiplier=4.,
            nominal_pixels=n,effective_independent_pixels=None,
            retained_frequencies=int(keep.sum()),current_innovation_frequencies=int((innovation&keep).sum()),
            total_rfft_frequencies=int(keep.size),prediction_min=float(np.min(prediction)),
            prediction_max=float(np.max(prediction)),signed_mean_delta_rgb=(prediction-frame).mean((0,1)).tolist()))
        spectra.append(current);sigmas.append(sigma)
        if len(spectra)>=history:
            spectra.pop(0);sigmas.pop(0)
    return pilots,active,dict(schema='fsrd-temporal-spectral-response-pilot-research-v1',
        active_frames=int(active.sum()),frames=records,epoch_start_by_frame=epochs,history=history,
        quality_accepted=False,no_clean_truth_input=True,innovation_sigma_multiplier=3.,threshold_sigma_multiplier=4.,
        source_domain='Current and preceding observed RGB only; normalized rfft2',
        assumptions=['Periodic correctly corresponding single-surface ROI',
            'Spatial iid approximately Gaussian noise; independent between observations',
            'Most pooled spectral magnitudes represent noise','Comparable channel noise scales',
            'Caller correspondence is valid within each reset/jitter epoch'],
        limitations=['No independence or correspondence proof','No reprojection or motion model',
            'Shared persistent source bias is unidentifiable','Slow subthreshold phase changes can lag',
            'Nonperiodic detail leaks across frequencies','Amplitude-selected noise can enter pilot',
            'Innovation thresholds are heuristic, not calibrated confidence bounds',
            'Dense material spectra and correlated noise invalidate nominal variance',
            'RGB common support and innovation can carry weak-channel noise',
            'No HLSL/runtime/game acceptance'])
