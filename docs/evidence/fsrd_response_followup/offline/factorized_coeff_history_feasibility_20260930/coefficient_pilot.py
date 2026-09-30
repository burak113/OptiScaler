"""Physical guide-coefficient history prototype; no native/runtime claim."""
import numpy as np

HISTORY=16
GUIDE_RIDGE=4.
GUIDE_SNR=4.
INNOVATION_MAHALANOBIS_SQUARED=9.
SOURCE_SHRINK_SE=4.
PROJECTOR_TOLERANCE=1e-6


def fit_beta(current,past,sigma):
    n=np.prod(current.shape[:2]);f=np.stack(past);mean=f.mean(0)
    estimates=[];covariances=[];projectors=[];features=[];info=[]
    for ch in range(3):
        xa=f[::2,...,ch,:].mean(0).reshape(-1,2);xb=f[1::2,...,ch,:].mean(0).reshape(-1,2)
        aa=xa-xa.mean(0);bb=xb-xb.mean(0)
        x=mean[...,ch,:].reshape(-1,2);x=x-x.mean(0);y=current[...,ch].ravel();y=y-y.mean()
        signal=(aa.T@bb+bb.T@aa)/(2*n);noise=(aa-bb).T@(aa-bb)/(4*n)
        regularizer=max(1e-12,float(np.trace(noise))*1e-6)
        ev,vec=np.linalg.eigh(noise+regularizer*np.eye(2));whitening=(vec/np.sqrt(ev))@vec.T
        snr,directions=np.linalg.eigh(whitening@signal@whitening)
        v=whitening@directions[:,snr>GUIDE_SNR]
        if not v.shape[1]:return None,dict(reason='unidentifiable_guide_rank',channel=ch,whitened_eigenvalues=snr.tolist())
        matrix=v.T@(signal+GUIDE_RIDGE*(noise+regularizer*np.eye(2)))@v
        inverse=v@np.linalg.solve(matrix,v.T)
        beta=inverse@(x.T@y/n);cx=x.T@x/n
        covariance=(sigma*sigma/n)*inverse@cx@inverse.T;covariance=.5*(covariance+covariance.T)
        projector=v@np.linalg.pinv(v)
        if not np.isfinite(beta).all() or not np.isfinite(covariance).all() or np.linalg.eigvalsh(covariance).min() < -1e-12:
            return None,dict(reason='unidentifiable_coefficient_covariance',channel=ch)
        estimates.append(beta);covariances.append(covariance);projectors.append(projector);features.append(x)
        info.append(dict(rank=int(v.shape[1]),whitened_eigenvalues=snr.tolist()))
    return (np.stack(estimates),np.stack(covariances),np.stack(projectors),features),dict(reason='fit',channels=info)


def compare_beta(beta,covariance,past_beta,past_covariance,projector):
    if not past_beta:return beta,covariance,False,[None]*3
    m=len(past_beta);prior=np.mean(past_beta,axis=0);prior_cov=sum(past_covariance)/(m*m)
    combined=covariance+prior_cov;distance=[]
    for ch in range(3):
        difference=beta[ch]-prior[ch]
        # Every difference must lie in the current identifiable physical span.
        if np.linalg.norm(difference-projector[ch]@difference)>1e-8*(1+np.linalg.norm(difference)):
            raise ValueError('Coefficient comparison outside identifiable support')
        distance.append(max(0.,float(difference@np.linalg.pinv(combined[ch],rcond=1e-12)@difference)))
    innovation=bool(max(distance)>INNOVATION_MAHALANOBIS_SQUARED)
    if innovation:return beta,covariance,True,distance
    return (sum(past_beta)+beta)/(m+1),(sum(past_covariance)+covariance)/((m+1)**2),False,distance


def make_coefficient_history_pilot(raw,diff,spec,controls):
    c=np.asarray(raw,float);d=np.asarray(diff,float);s=np.asarray(spec,float);ctrl=np.asarray(controls,float)
    if c.ndim!=4 or c.shape[-1]!=3 or d.shape!=c.shape or s.shape!=c.shape or not len(c) or min(c.shape[1:3])<8:
        raise ValueError('Invalid source/guide dimensions')
    if not np.isfinite(c).all() or c.min()<0 or c.max()>65504 or ctrl.shape!=(len(c),3) or not np.isfinite(ctrl).all() or not np.isin(ctrl[:,0],[0,1]).all():
        raise ValueError('Invalid source RGB or controls')
    frames,h,w,_=c.shape;n=h*w;end=-1 if w%2==0 else None
    pilots=c.copy();active=np.zeros(frames,bool);records=[];guide_past=[];betas=[];covariances=[];spectra=[];sigmas=[]
    last_projector=None;epoch=0
    for i,frame in enumerate(c):
        boundary=bool(ctrl[i,0] or (i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:])))
        if boundary:guide_past.clear();betas.clear();covariances.clear();spectra.clear();sigmas.clear();last_projector=None;epoch=i
        source=np.fft.rfft2(frame,axes=(0,1))/n
        sigma=max(float(np.median(abs(source[:,1:end,:])))*np.sqrt(n/np.log(2)),np.finfo(float).eps*max(1.,float(frame.max())))
        valid_guide=bool(np.isfinite(d[i]).all() and np.isfinite(s[i]).all() and d[i].min()>=0 and s[i].min()>=0 and d[i].max()<=1 and s[i].max()<=1)
        record=dict(frame=i,epoch_start=epoch,source_sigma=sigma,guide_history_count=len(guide_past),active=False,reason='early_history_raw')
        fit=None;fit_info={}
        if valid_guide and len(guide_past)>2:fit,fit_info=fit_beta(frame,guide_past,sigma)
        if fit is not None:
            beta,covariance,projector,x=fit
            changed=bool(last_projector is not None and np.max(abs(projector-last_projector))>PROJECTOR_TOLERANCE)
            if changed:betas.clear();covariances.clear();spectra.clear();sigmas.clear();epoch=i
            try:selected,selected_cov,innovation,distance=compare_beta(beta,covariance,betas,covariances,projector)
            except ValueError:
                fit=None;record['reason']='unidentifiable_comparison_raw';betas.clear();covariances.clear();spectra.clear();sigmas.clear();last_projector=None;epoch=i
            if fit is not None:
                guide=np.zeros_like(frame);weights=[];uncertainties=[]
                for ch in range(3):
                    cx=x[ch].T@x[ch]/n
                    signal_rms=np.sqrt(max(0.,float(selected[ch]@cx@selected[ch])))
                    se_rms=np.sqrt(max(0.,float(np.trace(cx@selected_cov[ch]))))
                    weight=max(0.,1-(SOURCE_SHRINK_SE*se_rms/signal_rms)**2) if signal_rms>0 else 0.
                    guide[...,ch]=(weight*(x[ch]@selected[ch])).reshape(h,w)
                    weights.append(weight);uncertainties.append(se_rms)
                residual=frame-guide;current=np.fft.rfft2(residual,axes=(0,1))/n;count=len(spectra)
                res_innovation=np.zeros(current.shape[:2],bool)
                if count:
                    prior=sum(spectra)/count;threshold=3*np.sqrt(sigma*sigma+sum(z*z for z in sigmas)/(count*count))/np.sqrt(n)
                    res_innovation=np.any(abs(current-prior)>threshold,axis=-1)
                    mean=(sum(spectra)+current)/(count+1);mean_sigma=np.sqrt(sum(z*z for z in sigmas)+sigma*sigma)/(count+1)
                else:mean=current.copy();mean_sigma=sigma
                coefficients=np.where(res_innovation[...,None],current,mean);selected_sigma=np.where(res_innovation,sigma,mean_sigma)
                magnitude=np.max(abs(coefficients),axis=-1);ratio=np.divide(4*selected_sigma/np.sqrt(n),magnitude,out=np.full_like(magnitude,np.inf),where=magnitude>0)
                spectral_weight=np.maximum(0.,1-ratio*ratio);spectral_weight[0,0]=1;coefficients[0,0]=current[0,0]
                predicted=guide+np.fft.irfft2(coefficients*spectral_weight[...,None]*n,s=(h,w),axes=(0,1))
                predicted+=frame.mean((0,1))-predicted.mean((0,1))
                valid=bool(np.isfinite(predicted).all() and predicted.min()>=0 and predicted.max()<=65504)
                if valid:pilots[i]=predicted;active[i]=True
                record.update(reason='accepted' if valid else 'invalid_signed_prediction_raw',active=valid,epoch_start=epoch,
                    support_changed=changed,beta_current=beta.tolist(),beta_selected=selected.tolist(),selected_covariance=selected_cov.tolist(),
                    coefficient_innovation=innovation,innovation_mahalanobis_squared=distance,shape_shrink_weights=weights,
                    shape_uncertainty_rms_rgb=uncertainties,coefficient_history_count=len(betas)+1,
                    residual_history_count=count+1,prediction_min=float(predicted.min()),prediction_max=float(predicted.max()),guide_fit=fit_info)
                betas.append(beta);covariances.append(covariance);spectra.append(current);sigmas.append(sigma);last_projector=projector
                if len(betas)>=HISTORY:betas.pop(0);covariances.pop(0)
                if len(spectra)>=HISTORY:spectra.pop(0);sigmas.pop(0)
        elif len(guide_past)>2:
            record['reason']=fit_info.get('reason','invalid_guides_raw');record['guide_fit']=fit_info
            betas.clear();covariances.clear();spectra.clear();sigmas.clear();last_projector=None;epoch=i
        if not valid_guide:guide_past.clear()
        else:
            guide_past.append(np.stack((d[i],s[i]),-1))
            if len(guide_past)>=HISTORY:guide_past.pop(0)
        record['epoch_start']=epoch;records.append(record)
    return pilots,active,dict(schema='physical-beta-causal-history-pilot-v1',frames=records,quality_accepted=False,
        no_clean_truth_input=True,history=16,effective_independent_pixels=None,
        limitations=['First <=2 guide observations are exact raw inactive; baseline/startup errors remain',
            'Rank0 or unsupported covariance comparison is raw inactive; unrepresented waves receive no correction',
            'Nominal SE assumes spatial/temporal independent noise and aligned guides; correlated bias invalidates it',
            'Shared guide/source persistent bias is not identifiable and remains a counterexample',
            'Slow subthreshold coefficient changes can lag; no age/motion model',
            'Guide rank/support changes cut beta and residual histories; model transition quality is unproved',
            'Shrink occurs after covariance-aware coefficient averaging, but weak-detail bias can persist',
            'No native paired response, game/runtime, or quality acceptance'])
