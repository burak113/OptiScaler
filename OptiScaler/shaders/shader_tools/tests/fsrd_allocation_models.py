"""Research-only spatial allocation models. No clean truth, no temporal state.

An 8x8 held-out block is predicted from a surrounding, connected surface ring.
Coefficients are shared within that block, not extrapolated from an unobserved
constant interior. This is a bounded feasibility candidate, not a game algorithm.
"""
import numpy as np
from fsrd_small_regression import applied_fit, nnls_small


def connected(mask, start):
    out=np.zeros_like(mask)
    if not mask[start]: return out
    if mask.all(): return mask.copy()
    stack=[start]; out[start]=True
    h,w=mask.shape
    while stack:
        y,x=stack.pop()
        for yy,xx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
            if 0<=yy<h and 0<=xx<w and mask[yy,xx] and not out[yy,xx]:
                out[yy,xx]=True; stack.append((yy,xx))
    return out


def estimate(raw, diffuse, specular, depth, normals, roughness, mode='surface', radius=16):
    """Returns p and an explicit per-channel activity mask plus fit diagnostics.

    surface: a*(Ad+As)+b, only flat specular; b routing remains a tested hypothesis.
    lobes: ad*Ad+as*As; also evaluate a third additive term, but never route it.
    """
    overlap=mode.endswith('_overlap')
    mode=mode.removesuffix('_overlap')
    if mode not in ('surface','lobes'): raise ValueError('Unknown research model')
    c=np.asarray(raw[...,:3],np.float64)
    d=np.rint(np.clip(diffuse[...,:3].astype(np.float16).astype(float),0,1)*255)/255
    s=np.rint(np.clip(specular[...,:3].astype(np.float16).astype(float),0,1)*255)/255
    h,w=c.shape[:2]
    p=s/np.maximum(d+s,.008)
    baseline=p.copy()
    transfer_sum=np.zeros_like(p); support_weight=np.zeros_like(p)
    active=np.zeros_like(p,bool)
    names=('reason','rank','condition','train_rmse','heldout_rmse','baseline_rmse',
           'slope_d','slope_s','intercept','share_uncertainty','additive_rank',
           'additive_condition','additive_heldout_rmse','additive_intercept',
           'unconstrained_slope_d','unconstrained_slope_s','unconstrained_heldout_rmse')
    diag={k:np.zeros_like(p) for k in names}
    accepted_diag={k:np.zeros_like(p) for k in names} if overlap else {}
    # Reason: 1 samples, 2 rank/conditioning, 3 negative coefficients,
    # 4 no independent prediction improvement, 5 lighting gradient confound,
    # 6 coefficient uncertainty, 7 patterned/unsafe specular, 8 unexplained additive.
    stride=4 if overlap else 8
    for by in range(0,h,stride):
      for bx in range(0,w,stride):
        cy,cx=min(by+4,h-1),min(bx+4,w-1)
        y0,y1=max(0,by-radius),min(h,by+8+radius)
        x0,x1=max(0,bx-radius),min(w,bx+8+radius)
        yy,xx=np.indices((y1-y0,x1-x0)); gy,gx=yy+y0,xx+x0
        z=depth[y0:y1,x0:x1].astype(float)
        n=normals[y0:y1,x0:x1,:3].astype(float)
        norm=np.linalg.norm(n,axis=-1)
        n=n/np.maximum(norm[...,None],1e-12)
        cn=n[cy-y0,cx-x0]
        # Fit depth plane from the central local 3x3, not from a different surface.
        local=(abs(gy-cy)<=1)&(abs(gx-cx)<=1)&np.isfinite(z)
        xy=np.stack([np.ones_like(xx),(gx-cx)/max(w,1),(gy-cy)/max(h,1)],axis=-1)
        plane=np.linalg.lstsq(xy[local],z[local],rcond=None)[0] if local.sum()>=3 else np.array([depth[cy,cx],0,0])
        surface=(np.abs(z-xy@plane)<=max(.01,.02*abs(depth[cy,cx])))
        surface &= (n@cn>=.95)&(norm>1e-8)&np.isfinite(z)
        surface &= abs(roughness[y0:y1,x0:x1]-roughness[cy,cx])<=max(.02,.1*roughness[cy,cx])
        surface=connected(surface,(cy-y0,cx-x0))
        held=(gy>=by)&(gy<by+8)&(gx>=bx)&(gx<bx+8)&surface
        train=surface&~held
        sl=np.s_[by:min(by+8,h),bx:min(bx+8,w)]
        target=held[by-y0:min(by+8,h)-y0,bx-x0:min(bx+8,w)-x0]
        if train.sum()<32 or held.sum()<8:
            diag['reason'][sl]=1; continue
        ds=d[y0:y1,x0:x1]; ss=s[y0:y1,x0:x1]; cc=c[y0:y1,x0:x1]
        for ch in range(3):
            def record(key,val): diag[key][sl+(ch,)]=val
            a=ds[...,ch]+ss[...,ch]; bcolor=cc[...,ch]
            basis=np.stack((a,np.ones_like(a)),axis=-1) if mode=='surface' else np.stack((ds[...,ch],ss[...,ch]),axis=-1)
            X,Y=basis[train],bcolor[train]
            V,T=basis[held],bcolor[held]
            scale=np.sqrt(np.mean(X*X,axis=0)); Xn=X/np.maximum(scale,1e-12)
            coef,_,rank,sv=np.linalg.lstsq(Xn,Y,rcond=1e-4)
            condition=float(sv[0]/max(sv[-1],1e-20))
            record('rank',rank); record('condition',min(condition,1e12))
            if rank<2 or condition>30:
                record('reason',2); continue
            coef=coef/scale
            residual=Y-X@coef
            mse=float(np.mean(residual**2))
            cov=np.linalg.inv(Xn.T@Xn)*mse
            cov=cov/scale[:,None]/scale[None,:]
            error=np.sqrt(np.maximum(np.diag(cov),0))
            record('unconstrained_slope_d',coef[0]); record('unconstrained_slope_s',coef[1])
            record('unconstrained_heldout_rmse',float(np.sqrt(np.mean((T-V@coef)**2))))
            roundoff=64*np.finfo(np.float64).eps*condition*max(1,float(np.linalg.norm(coef)))
            # Preserve the evidence that a physical two-positive-lobe explanation
            # is incompatible. Small negatives are refit, never merely clipped.
            if np.any(coef < -np.maximum(2*error,roundoff)):
                record('reason',3); continue
            coef,cov,trainerr,validerr=applied_fit(X,Y,V,T)
            error=np.sqrt(np.maximum(np.diag(cov),0))
            a0=a[train]; slope0=np.dot(a0,Y)/max(np.dot(a0,a0),1e-20)
            baseerr=np.sqrt(np.mean((T-a[held]*slope0)**2))
            record('train_rmse',trainerr); record('heldout_rmse',validerr); record('baseline_rmse',baseerr)
            record('slope_d',coef[0]); record('slope_s',coef[0] if mode=='surface' else coef[1])
            record('intercept',coef[1] if mode=='surface' else 0)
            # Evaluate added independent term only where the design identifies it.
            if mode=='lobes':
                X3=np.column_stack((X,np.ones(len(X))))
                scale3=np.sqrt(np.mean(X3*X3,axis=0))
                k3,_,rank3,sv3=np.linalg.lstsq(X3/np.maximum(scale3,1e-12),Y,rcond=1e-4)
                cond3=sv3[0]/max(sv3[-1],1e-20)
                record('additive_rank',rank3); record('additive_condition',min(float(cond3),1e12))
                if rank3==3 and cond3<=50:
                    k3=nnls_small(X3,Y)
                    e3=np.sqrt(np.mean((T-np.column_stack((V,np.ones(len(V))))@k3)**2))
                    record('additive_heldout_rmse',e3); record('additive_intercept',k3[2])
                    if k3[2]>.01*np.mean(Y) and e3<.8*validerr:
                        record('reason',8); continue # Unknown layer has no safe destination.
            if validerr>max(.8*baseerr,1e-5):
                record('reason',4); continue
            # A lighting plane is a competing explanation, not albedo evidence.
            grad=np.column_stack((X,xy[train,1:]))
            kg=np.linalg.lstsq(grad,Y,rcond=1e-4)[0]
            eg=np.sqrt(np.mean((T-np.column_stack((V,xy[held,1:]))@kg)**2))
            grad_mse=np.mean((Y-grad@kg)**2)
            grad_cov=np.linalg.pinv(grad.T@grad,rcond=1e-10)*grad_mse
            grad_error=np.sqrt(np.maximum(np.diag(grad_cov)[-2:],1e-20))
            # Significance uses the fit covariance, not a large arbitrary drop in
            # total residual RMSE: independent noise can conceal a real gradient.
            if (np.any(abs(kg[-2:])>3*grad_error) and eg<=1.02*validerr and
                np.ptp(xy[surface,1:]@kg[-2:])>.01*np.mean(Y)):
                record('reason',5); continue
            sd,sp=d[sl+(ch,)],s[sl+(ch,)]
            if mode=='surface':
                if coef[1]<=2*error[1]:
                    record('reason',6); continue
                if ss[...,ch][surface].min()<max(4/255,.008) or np.ptp(ss[...,ch][surface])>.1*np.mean(ss[...,ch][surface])+1e-6:
                    record('reason',7); continue
                num=coef[0]*sp+coef[1]; den=coef[0]*(sd+sp)+coef[1]
                jac=np.stack((-sd*coef[1],coef[0]*sd),axis=-1)/np.maximum(den[...,None]**2,1e-20)
            else:
                num=coef[1]*sp; den=coef[0]*sd+coef[1]*sp
                jac=np.stack((-num*sd,coef[0]*sd*sp),axis=-1)/np.maximum(den[...,None]**2,1e-20)
            uncertainty=np.sqrt(np.maximum(np.einsum('...i,ij,...j->...',jac,cov,jac),0))
            record('share_uncertainty',float(uncertainty.max()))
            if uncertainty.max()>.10:
                record('reason',6); continue
            predicted=np.clip(num/np.maximum(den,1e-12),0,1)
            safe=target&(den>1e-8)&(c[sl+(ch,)]*predicted<=65504*np.maximum(sp,.008))
            if overlap:
                # Separable partition-of-unity tents blend supported predictions.
                # Missing support contributes baseline, not a fabricated intercept.
                wy=1-abs((np.arange(sd.shape[0])+.5-4)/4)
                wx=1-abs((np.arange(sd.shape[1])+.5-4)/4)
                weight=wy[:,None]*wx[None,:]*safe
                transfer_sum[sl+(ch,)]+=weight*(predicted-baseline[sl+(ch,)])
                support_weight[sl+(ch,)]+=weight
                for key in names:
                    if key!='reason': accepted_diag[key][sl+(ch,)]+=weight*diag[key][sl+(ch,)]
                active[sl+(ch,)] |= safe
            else:
                active[sl+(ch,)]=safe
                p[sl+(ch,)]=np.where(safe,predicted,p[sl+(ch,)])
    if overlap:
        p=np.clip(baseline+transfer_sum/np.maximum(support_weight,1),0,1)
        for key in names:
            if key!='reason':
                diag[key]=np.where(support_weight>0,accepted_diag[key]/np.maximum(support_weight,1e-20),diag[key])
        diag['reason']=np.where(active,0,diag['reason'])
        diag['support_weight']=support_weight
    return p,active,diag
