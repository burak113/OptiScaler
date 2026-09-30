"""One preregistered source-only RGB-DC-normalized nominal phase prototype."""
import numpy as np

def make_dc_normalized_phase_pilot(raw, controls):
    c=np.asarray(raw,float); ctrl=np.asarray(controls,float)
    if c.ndim!=4 or c.shape[-1]!=3 or not len(c) or min(c.shape[1:3])<8:
        raise ValueError('N,H,W,RGB >=8 required')
    if ctrl.shape!=(len(c),3): raise ValueError('Nx3 controls required')
    nf,h,w,_=c.shape; n=h*w; end=-1 if w%2==0 else None
    boundaries=[0]+([w//2] if w%2==0 else [])
    out=c.copy(); active=np.zeros(nf,bool); past=[]; pastq=[]; records=[]; epoch=0
    def cut(i):
        nonlocal epoch
        past.clear(); pastq.clear(); epoch=i
    for i,frame in enumerate(c):
        metadata=bool(np.isfinite(ctrl[i]).all() and ctrl[i,0] in (0,1))
        reset=bool(metadata and ctrl[i,0])
        jitter=bool(i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:]))
        if reset or jitter: cut(i)
        source_valid=bool(np.isfinite(frame).all() and frame.min()>=0 and frame.max()<=65504)
        if not metadata or not source_valid:
            cut(i+1)
            records.append(dict(frame=i,active=False,epoch_start=i,preceding_observations=0,reason='invalid_metadata_or_source_exact_raw'))
            continue
        F=np.fft.rfft2(frame,axes=(0,1))/n; dc=F[0,0].real
        if np.any(dc<=1e-4):
            cut(i+1)
            records.append(dict(frame=i,active=False,epoch_start=i,preceding_observations=0,reason='nearzero_DC_exact_raw',DC_RGB=dc.tolist()))
            continue
        sigma=max(float(np.median(abs(F[:,1:end,:])))*np.sqrt(n/np.log(2)),np.finfo(float).eps*max(1.,float(frame.max())))
        qraw=sigma*sigma/n; G=F/dc
        q=qraw/(dc*dc)*(1+abs(G)**2); q[0,0]=0
        m=len(past); theta=np.zeros(G.shape[:2]); qualified=np.zeros_like(theta,bool)
        used=np.zeros_like(theta,bool); se_used=np.zeros_like(theta)
        if m>=8:
            old=np.stack(past); oldq=np.stack(pastq); a=old[1:]; b=old[:-1]
            Ar=np.mean(abs(a)**2,0); Br=np.mean(abs(b)**2,0)
            qar=np.mean(oldq[1:],0); qbr=np.mean(oldq[:-1],0)
            A=Ar.sum(-1); B=Br.sum(-1); qa=qar.sum(-1); qb=qbr.sum(-1)
            C=np.sum(np.sum(a*np.conj(b),-1),0)
            coherence=np.divide(abs(C),(m-1)*np.sqrt(A*B),out=np.zeros_like(A),where=A*B>0)
            pa=np.divide(np.maximum(A-qa,0),qa,out=np.zeros_like(A),where=qa>0)
            pb=np.divide(np.maximum(B-qb,0),qb,out=np.zeros_like(B),where=qb>0)
            qualified=(np.minimum(pa,pb)>16)&(coherence>=.8)
            E=np.maximum((Ar+Br-qar-qbr)/2,0)
            V=np.sum(E*(oldq[0]+oldq[-1])/2,-1)+np.sum(np.sum(oldq[1:]*oldq[:-1],-1),0)/2
            se=np.divide(np.sqrt(V),abs(C),out=np.full_like(A,np.inf),where=abs(C)>0)
            angle=np.angle(C); used=qualified&(abs(angle)>3*se)
            theta=np.where(used,angle,0); se_used=np.where(used,se,0)
            for x in boundaries:
                theta[0,x]=0; used[0,x]=False; se_used[0,x]=0
                for y in range(1,(h+1)//2):
                    j=(-y)%h; ok=bool(used[y,x] and used[j,x]); used[y,x]=used[j,x]=ok
                    t=theta[y,x] if ok else 0.; s=se_used[y,x] if ok else 0.
                    theta[y,x]=t; theta[j,x]=-t; se_used[y,x]=se_used[j,x]=s
                if h%2==0: theta[h//2,x]=0; used[h//2,x]=False; se_used[h//2,x]=0
        theta[0,0]=0; used[0,0]=False; se_used[0,0]=0
        if m:
            aligned=[g*np.exp(1j*theta*(m-j))[...,None] for j,g in enumerate(past)]
            total=sum(aligned); weighted=sum((m-j)*g for j,g in enumerate(aligned))
            prior=total/m; mean=(total+G)/(m+1)
            vprior0=sum(pastq)/(m*m); vmean0=(sum(pastq)+q)/(m+1)**2
            vprior=(np.sqrt(vprior0)+abs(1j*weighted/m)*se_used[...,None])**2
            vmean=(np.sqrt(vmean0)+abs(1j*weighted/(m+1))*se_used[...,None])**2
            innovation=np.any(abs(G-prior)>3*np.sqrt(q+vprior),-1)
        else:
            mean=G.copy(); vmean=q.copy(); innovation=np.zeros_like(theta,bool)
        innovation[0,0]=False
        selected=np.where(innovation[...,None],G,mean); selected[0,0]=G[0,0]
        variance=np.where(innovation[...,None],q,vmean)
        keep=np.any(abs(selected)>4*np.sqrt(variance),-1); keep[0,0]=True
        restored=selected*dc; restored[0,0]=F[0,0]
        vradiance=np.where(innovation[...,None],qraw,(dc*np.sqrt(vmean)+abs(mean)*np.sqrt(qraw))**2)
        prediction=np.fft.irfft2(restored*keep[...,None]*n,s=(h,w),axes=(0,1))
        valid=bool(np.isfinite(prediction).all() and prediction.min()>=0 and prediction.max()<=65504)
        if valid: out[i]=prediction; active[i]=True
        records.append(dict(frame=i,active=valid,epoch_start=epoch,reset=reset,jitter_changed=jitter,preceding_observations=m,
            nominal_iid_pixel_sigma=sigma,DC_RGB=dc.tolist(),retained_frequencies=int(keep.sum()),
            phase_power_coherence_qualified_frequencies=int(qualified.sum()),nominal_3SE_used_phase_frequencies=int(used.sum()),
            retained_innovation_frequencies=int((keep&innovation).sum()),retained_used_phase_frequencies=int((keep&used).sum()),
            max_used_phase_increment=float(abs(theta[used]).max()) if used.any() else None,
            max_used_nominal_phase_SE=float(se_used[used].max()) if used.any() else None,
            restored_nominal_coefficient_variance_mean=float(vradiance.mean()),prediction_min=float(prediction.min()),prediction_max=float(prediction.max()),
            reason='accepted' if valid else 'invalid_prediction_exact_raw_epoch_cut'))
        if valid:
            past.append(G); pastq.append(q)
            if len(past)>=64: past.pop(0); pastq.pop(0)
        else: cut(i+1)
    return out,active,dict(schema='source-DC-normalized-nominal-significant-phase-v1',history=64,frames=records,
        no_clean_truth_input=True,guide_inputs=False,native_measured=False,quality_accepted=False,
        phase_estimator_uses_current=False,current_DC=True,effective_independent_pixels=None,
        variance_scope='First-order ratio and Cauchy RMS plug-in nominal IID; not confidence or nonlinear bound',
        normalization='own per-frame per-RGB full-image observed DC',invalid_prediction_cuts_history=True)
