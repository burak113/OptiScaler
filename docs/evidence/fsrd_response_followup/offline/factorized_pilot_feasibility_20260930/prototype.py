"""Guide-factorized source-only pilot; CPU feasibility, no native claim."""
import numpy as np

HISTORY=16
RIDGE_NOISE_MULTIPLIER=4.
SOURCE_SE_MULTIPLIER=4.
BLENDS=('bounded','full_after_two')


def guide_component(current,past,sigma,blend):
    """Current source target against past-only guide covariance/means."""
    h,w,_=current.shape;n=h*w;m=len(past);out=np.zeros_like(current);records=[]
    alpha=m/(m+8) if blend=='bounded' else float(m>=2)
    if m<2:return out,dict(alpha=alpha,reason='insufficient_guide_covariance',channels=[])
    f=np.stack(past);mean=f.mean(0)
    for ch in range(3):
        xa=f[::2,...,ch,:].mean(0).reshape(-1,2);xb=f[1::2,...,ch,:].mean(0).reshape(-1,2)
        aa=xa-xa.mean(0);bb=xb-xb.mean(0);x=mean[...,ch,:].reshape(-1,2);x-=x.mean(0)
        y=current[...,ch].ravel();y=y-y.mean()
        cov=(aa.T@bb+bb.T@aa)/(2*n);noise=(aa-bb).T@(aa-bb)/(4*n)
        regularizer=max(1e-12,float(np.trace(noise))*1e-6)
        ev,vec=np.linalg.eigh(noise+regularizer*np.eye(2));whitening=(vec/np.sqrt(ev))@vec.T
        values,directions=np.linalg.eigh(whitening@cov@whitening)
        v=whitening@directions[:,values>0]
        if v.shape[1]:
            projected=v.T@(cov+RIDGE_NOISE_MULTIPLIER*(noise+regularizer*np.eye(2)))@v
            coefficient=np.linalg.solve(projected,v.T@(x.T@y/n))
            z=x@v;amplitude=abs(coefficient)*np.sqrt(np.mean(z*z,axis=0))
            limit=SOURCE_SE_MULTIPLIER*sigma/np.sqrt(n)
            ratio=np.divide(limit,amplitude,out=np.full_like(amplitude,np.inf),where=amplitude>0)
            weight=np.maximum(0.,1-ratio*ratio)
            beta=v@(coefficient*weight)
            out[...,ch]=(alpha*(x@beta)).reshape(h,w)
        else:beta=np.zeros(2);weight=np.empty(0)
        records.append(dict(beta=beta.tolist(),positive_covariance_rank=int(v.shape[1]),
            whitened_covariance_eigenvalues=values.tolist(),source_coefficient_weights=weight.tolist()))
    return out,dict(alpha=alpha,reason='fit',channels=records)


def make_factorized_pilot(raw,diff,spec,controls,blend='bounded'):
    """No truth/scene argument; always estimates a signed spectral residual."""
    c=np.asarray(raw,float);d=np.asarray(diff,float);s=np.asarray(spec,float);ctrl=np.asarray(controls,float)
    if blend not in BLENDS or c.ndim!=4 or c.shape[-1]!=3 or d.shape!=c.shape or s.shape!=c.shape:
        raise ValueError('Invalid RGB source/guide dimensions or blend')
    if min(c.shape[1:3])<8 or not len(c) or ctrl.shape!=(len(c),3):raise ValueError('Invalid dimensions/controls')
    if not np.isfinite(c).all() or np.any(c<0) or np.any(c>65504) or not np.isfinite(ctrl).all() or not np.isin(ctrl[:,0],[0,1]).all():
        raise ValueError('Invalid observed RGB or immutable native controls')
    frames,h,w,_=c.shape;n=h*w;end=-1 if w%2==0 else None
    pilot=c.copy();active=np.zeros(frames,bool);guide_past=[];spectra=[];sigmas=[];records=[];epoch=0
    for i,frame in enumerate(c):
        reset=bool(ctrl[i,0]);jitter_changed=bool(i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:]))
        if reset or jitter_changed:guide_past.clear();spectra.clear();sigmas.clear();epoch=i
        source=np.fft.rfft2(frame,axes=(0,1))/n
        sigma=max(float(np.median(abs(source[:,1:end,:])))*np.sqrt(n/np.log(2)),np.finfo(float).eps*max(1.,float(frame.max())))
        guides_valid=bool(np.isfinite(d[i]).all() and np.isfinite(s[i]).all() and d[i].min()>=0 and s[i].min()>=0 and d[i].max()<=1 and s[i].max()<=1)
        if guides_valid:g,fit=guide_component(frame,guide_past,sigma,blend)
        else:guide_past.clear();g=np.zeros_like(frame);fit=dict(alpha=0.,reason='invalid_guides_spectral_only',channels=[])
        residual=frame-g;current=np.fft.rfft2(residual,axes=(0,1))/n;count=len(spectra)
        innovation=np.zeros(current.shape[:2],bool);innovation_limit=None
        if count:
            prior=sum(spectra)/count;prior_var=sum(x*x for x in sigmas)/(count*count)
            innovation_limit=3*np.sqrt(sigma*sigma+prior_var)/np.sqrt(n)
            innovation=np.any(abs(current-prior)>innovation_limit,axis=-1)
            mean=(sum(spectra)+current)/(count+1);mean_sigma=np.sqrt(sum(x*x for x in sigmas)+sigma*sigma)/(count+1)
        else:mean=current.copy();mean_sigma=sigma
        selected=np.where(innovation[...,None],current,mean);selected_sigma=np.where(innovation,sigma,mean_sigma)
        magnitude=np.max(abs(selected),axis=-1);limit=4*selected_sigma/np.sqrt(n)
        ratio=np.divide(limit,magnitude,out=np.full_like(magnitude,np.inf),where=magnitude>0)
        weight=np.maximum(0.,1-ratio*ratio);weight[0,0]=1;selected[0,0]=current[0,0];innovation[0,0]=False
        predicted=g+np.fft.irfft2(selected*weight[...,None]*n,s=(h,w),axes=(0,1))
        predicted+=frame.mean((0,1))-predicted.mean((0,1))
        valid=bool(np.isfinite(predicted).all() and predicted.min()>=0 and predicted.max()<=65504)
        if valid:pilot[i]=predicted;active[i]=True
        records.append(dict(frame=i,epoch_start=epoch,reset=reset,jitter_changed=jitter_changed,active=valid,
            guide_fit=fit,guide_history_count=len(guide_past),residual_history_count=count+1,
            source_sigma=sigma,source_uncertainty_coeff_limit=4*sigma/np.sqrt(n),
            residual_innovation_threshold=innovation_limit,residual_support=int(np.count_nonzero(weight)),
            residual_weight_square_sum=float(np.sum(weight*weight)),current_innovation_frequencies=int(np.count_nonzero(innovation & (weight>0))),
            guide_shape_rms=float(np.sqrt(np.mean(g*g))),prediction_min=float(predicted.min()),prediction_max=float(predicted.max())))
        if guides_valid:
            guide_past.append(np.stack((d[i],s[i]),-1))
            if len(guide_past)>=HISTORY:guide_past.pop(0)
        spectra.append(current);sigmas.append(sigma)
        if len(spectra)>=HISTORY:spectra.pop(0);sigmas.pop(0)
    return pilot,active,dict(schema='factorized-guide-soft-residual-source-pilot-v1',blend=blend,history=HISTORY,
        frames=records,no_clean_truth_input=True,quality_accepted=False,effective_independent_pixels=None,
        fixed_constants=dict(guide_noise_ridge=4,source_coefficient_SE=4,residual_weight_RMS=4,innovation_RMS=3,blend_history_scale=8),
        limitations=['Global aligned single-surface affine guide relation is assumed, not established',
            'Independent source current noise and prior guide streams is assumed; correlated noise violates it',
            'No current-guide noise copying: guide evaluation uses only past means, but shared persistent bias remains unidentifiable',
            'Covariance/coefficients and blend warmup can change the residual model; no history activation quality guarantee',
            'Source coefficient shrink can attenuate weak genuine material; absolute detail metrics are required',
            'Global current DC is retained; nonperiodic residual leakage and slow-phase lag remain',
            'Clean reference used only for scoring; no new native T(P), runtime, or game claim'])
