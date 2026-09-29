"""CPU post-RR feasibility estimator. Signed coefficients reconstruct net RGB.

No truth input, motion estimation, physical-lobe interpretation, or runtime use.
Independent streams and verified correspondence are experimental prerequisites,
not properties inferred from consecutive frames of an AMD history.
"""
import numpy as np
from fsrd_allocation_models import connected


def observation_evidence(sequences):
    """Conservative correlation of raw temporal increments, without clean truth.

    Shared lighting/motion can reduce this count too. Independent RNG provenance
    is still required: a shared static bias is invisible to temporal differences.
    Consecutive outputs from a common AMD context are never observations here.
    """
    a=np.asarray(sequences,float)
    if a.ndim!=5 or a.shape[0]<2 or a.shape[1]<2 or not np.isfinite(a).all():
        return dict(effective_count=1.,maximum_positive_correlation=1.,matrix=None)
    increments=np.diff(a,axis=1).reshape(len(a),-1)
    if np.any(increments.std(1)<1e-12):
        return dict(effective_count=1.,maximum_positive_correlation=1.,matrix=None)
    corr=np.corrcoef(increments)
    rho=float(max(0,corr[np.triu_indices(len(a),1)].max()))
    return dict(effective_count=float(len(a)/(1+(len(a)-1)*rho)),
                maximum_positive_correlation=rho,matrix=corr.tolist())


def resolve(response, features, baseline, depth, normals, roughness, *, radius=12,
            history_raw=None, stream_ids=None, correspondence=None, reset=False,
            feature_variance=None, require_independence=True, effective_observations=None,
            validation_response=None):
    c, f, base = (np.asarray(a, float) for a in (response, features, baseline))
    if c.ndim != 3 or c.shape[-1] != 3 or base.shape != c.shape or f.shape[:3] != c.shape or f.ndim != 4:
        raise ValueError('Expected H,W,RGB response/baseline and H,W,RGB,F features')
    h,w=c.shape[:2]
    z,n,r=(np.asarray(a,float) for a in (depth,normals,roughness))
    if z.shape!=(h,w) or n.shape[:2]!=(h,w) or n.shape[-1]<3 or r.shape!=(h,w):
        raise ValueError('Mismatched geometry')
    if not all(np.isfinite(a).all() for a in (c,f,base,z,n,r)) or np.any(c<0) or np.any(base<0):
        raise ValueError('Finite nonnegative observed/baseline radiance required')
    validation=c if validation_response is None else np.asarray(validation_response,float)
    if validation.shape!=c.shape or not np.isfinite(validation).all() or np.any(validation<0):
        raise ValueError('Invalid validation observation')
    # A separate observation must also be independent of feature construction.
    # The experimental caller owns that stream split and correspondence proof.
    if radius<4 or not 1<=f.shape[-1]<=3: raise ValueError('Invalid regression support')
    variance=np.zeros_like(f) if feature_variance is None else np.asarray(feature_variance,float)
    if variance.shape!=f.shape or not np.isfinite(variance).all() or np.any(variance<0):
        raise ValueError('Invalid feature variance')
    valid=np.ones((h,w),bool) if correspondence is None else np.asarray(correspondence,bool)
    if valid.shape!=(h,w): raise ValueError('Invalid correspondence mask')
    history=None if history_raw is None else np.asarray(history_raw,float)
    independent=False; effective_count=0.
    if history is not None:
        if history.ndim!=4 or history.shape[1:]!=c.shape or not np.isfinite(history).all() or np.any(history<0):
            raise ValueError('History must already be aligned, exposure-normalized and finite')
        count=len(history)
        independent=(count>=4 and stream_ids is not None and len(stream_ids)==count and len(set(stream_ids))==count)
        # Detect duplicated observations even when incorrectly given distinct IDs.
        duplicate=any(np.array_equal(history[i],history[j]) for i in range(count) for j in range(i))
        # Identical noiseless observations convey no independence evidence either.
        independent=independent and not duplicate
        effective_count=float(count if independent else min(count,1))
        if effective_observations is not None:
            if not np.isfinite(effective_observations) or effective_observations<1:
                raise ValueError('Invalid effective observation count')
            effective_count=min(effective_count,float(effective_observations))
            independent=independent and effective_count>=3
    diag={k:np.zeros_like(c) for k in ('reason','rank','condition','heldout_rmse','baseline_rmse',
                                     'leverage','prediction_sigma','temporal_ratio','confidence')}
    accepted_diag={k:np.zeros_like(c) for k in diag if k not in ('reason','confidence')}
    prediction=base.copy(); correction=np.zeros_like(c); weight=np.zeros_like(c)
    coefficients=np.zeros((*c.shape,f.shape[-1]+1))
    reason_codes={1:'samples',2:'conditioning',3:'net_radiance',4:'heldout',5:'leverage',
                  6:'feature_uncertainty',7:'independence_or_reset',8:'correspondence',9:'temporal_mismatch'}
    if reset or (require_independence and not independent):
        diag['reason'][:]=7
        return base.copy(),dict(**diag,prediction=prediction,residual=c-prediction,
            delta=np.zeros_like(c),coefficients=coefficients,effective_observations=effective_count,reason_codes=reason_codes)
    n=n[...,:3]/np.maximum(np.linalg.norm(n[...,:3],axis=-1,keepdims=True),1e-12)
    for by in range(-4,h,4):
      for bx in range(-4,w,4):
        cy,cx=np.clip(by+4,0,h-1),np.clip(bx+4,0,w-1)
        y0,y1=max(0,by-radius),min(h,by+8+radius)
        x0,x1=max(0,bx-radius),min(w,bx+8+radius)
        yy,xx=np.indices((y1-y0,x1-x0)); yy+=y0;xx+=x0
        xy=np.stack((np.ones_like(xx),xx-cx,yy-cy),-1)
        local=(abs(xx-cx)<=1)&(abs(yy-cy)<=1)
        zz=z[y0:y1,x0:x1]
        plane=np.linalg.lstsq(xy[local],zz[local],rcond=None)[0]
        surface=abs(zz-xy@plane)<=max(.01,.02*abs(z[cy,cx]))
        surface&=(n[y0:y1,x0:x1]@n[cy,cx]>.95)
        surface&=abs(r[y0:y1,x0:x1]-r[cy,cx])<=max(.02,.1*r[cy,cx])
        surface=connected(surface,(cy-y0,cx-x0))
        center=(yy>=by)&(yy<by+8)&(xx>=bx)&(xx<bx+8)&surface
        ring=surface&~center
        train=ring&(((xx//4+yy//4)%2)==0)
        validation_mask=ring&~train
        sl=np.s_[max(by,0):min(by+8,h),max(bx,0):min(bx+8,w)]
        target=surface[max(by,0)-y0:min(by+8,h)-y0,max(bx,0)-x0:min(bx+8,w)-x0]
        if min(train.sum(),validation_mask.sum())<24 or center.sum()<8:
            diag['reason'][sl]=1;continue
        if not valid[y0:y1,x0:x1][surface].all():
            diag['reason'][sl]=8;continue
        for ch in range(3):
            numbers={}
            def record(key,value):
                diag[key][sl+(ch,)]=value
                numbers[key]=value
            cc=c[y0:y1,x0:x1,ch]; bb=base[y0:y1,x0:x1,ch]
            if history is not None and independent:
                past=history[:,y0:y1,x0:x1,ch][:,surface]
                observation_variance=np.mean(np.var(past,axis=0,ddof=1))
                difference=cc[surface]-past.mean(0)
                expected=observation_variance*(1+1/len(past))
                ratio=float(np.mean(difference**2)/max(expected,1e-20))
                record('temporal_ratio',ratio)
                if (np.mean(difference**2)>1.5*expected+1e-10 or
                    abs(difference.mean())>4*np.sqrt(expected/len(difference))+1e-5):
                    record('reason',9);continue
            ff=f[y0:y1,x0:x1,ch]
            mean=ff[train].mean(0); scale=ff[train].std(0)
            use=scale>1e-8*np.maximum(1,abs(mean))
            xf=(ff[...,use]-mean[use])/scale[use]
            design=np.concatenate((np.ones((*xf.shape[:2],1)),xf),axis=-1)
            X,Y=design[train],cc[train]
            # A rank-reduced statistical span is valid; it does not identify lobes.
            u,s,vh=np.linalg.svd(X,full_matrices=False)
            keep=s>s[0]*1e-3; rank=int(keep.sum());condition=float(s[0]/s[keep][-1])
            record('rank',rank);record('condition',condition)
            if condition>100 or len(Y)<8*rank:
                record('reason',2);continue
            inverse=(vh[keep].T/s[keep])@u[:,keep].T
            unexplained=design-design@vh[keep].T@vh[keep]
            if np.max(abs(unexplained[surface]))>1e-3:
                record('reason',2);continue
            coef=inverse@Y
            pred=design@coef
            # Never validate before clipping and apply a different net prediction.
            if not np.isfinite(pred[surface]).all() or np.any(pred[surface]<0) or np.any(pred[surface]>65504):
                record('reason',3);continue
            evaluate=validation_mask|center
            observed=validation[y0:y1,x0:x1,ch]
            error=float(np.sqrt(np.mean((observed[evaluate]-pred[evaluate])**2)))
            base_error=float(np.sqrt(np.mean((observed[evaluate]-bb[evaluate])**2)))
            record('heldout_rmse',error);record('baseline_rmse',base_error)
            if error>max(.99*base_error,1e-10):
                record('reason',4);continue
            covariance=inverse@inverse.T*np.mean((Y-X@coef)**2)
            inverse_gram=inverse@inverse.T
            leverage=np.einsum('...i,ij,...j->...',design,inverse_gram,design)
            record('leverage',float(leverage[center].max()))
            if leverage[center].max()>.25:
                record('reason',5);continue
            beta=np.zeros(f.shape[-1]);beta[use]=coef[1:]/scale[use]
            propagated=np.sum(variance[y0:y1,x0:x1,ch]*beta**2,axis=-1)
            sigma=np.sqrt(np.maximum(np.einsum('...i,ij,...j->...',design,covariance,design)+propagated,0))
            record('prediction_sigma',float(sigma[center].max()))
            if sigma[center].max()>max(.02*np.mean(cc[surface]),.002):
                record('reason',6);continue
            block=pred[max(by,0)-y0:min(by+8,h)-y0,max(bx,0)-x0:min(bx+8,w)-x0]
            wy=1-abs((np.arange(max(by,0),min(by+8,h))+.5-by-4)/4)
            wx=1-abs((np.arange(max(bx,0),min(bx+8,w))+.5-bx-4)/4)
            tent=wy[:,None]*wx[None,:]*target
            correction[sl+(ch,)]+=tent*(block-base[sl+(ch,)])
            weight[sl+(ch,)]+=tent
            applied=np.r_[coef[0]-mean@beta,beta]
            coefficients[sl+(ch,)]+=tent[...,None]*applied
            for key in accepted_diag:
                accepted_diag[key][sl+(ch,)]+=tent*numbers.get(key,0)
    confidence=np.minimum(weight,1)
    prediction=base+correction/np.maximum(weight,1e-20)
    delta=confidence*(prediction-base)
    diag['confidence']=confidence
    diag['reason']=np.where(weight>0,0,diag['reason'])
    for key,total in accepted_diag.items():
        diag[key]=np.where(weight>0,total/np.maximum(weight,1e-20),diag[key])
    return base+delta,dict(**diag,prediction=prediction,residual=c-prediction,delta=delta,
        coefficients=coefficients/np.maximum(weight[...,None],1e-20),
        effective_observations=effective_count,reason_codes=reason_codes)
