"""Causal observable two-feature response fit. No truth or guide inputs."""
import numpy as np
HISTORY=16
MIN_COUNT=8
RIDGE=4.0
LUMA=np.array([.2126,.7152,.0722],float)

def calibrate(pilot,response,observed,controls,active):
    p=np.asarray(pilot,float);r=np.asarray(response,float);raw=np.asarray(observed,float)
    ctrl=np.asarray(controls,float);active=np.asarray(active,bool)
    if p.ndim!=4 or p.shape[-1]!=3 or p.shape!=r.shape or p.shape!=raw.shape or min(p.shape[1:3])<8:
        raise ValueError('Expected matching N,H,W,RGB arrays')
    if ctrl.shape!=(len(p),3) or active.shape!=(len(p),) or not np.isin(ctrl[:,0],[0,1]).all():
        raise ValueError('Invalid controls/activity')
    if not all(np.isfinite(a).all() for a in (p,r,raw,ctrl)):raise ValueError('Nonfinite observable input')
    h,w=p.shape[1:3];n=h*w;end=-1 if w%2==0 else None
    result=np.zeros_like(p);past=[];epoch=0;records=[]
    for i in range(len(p)):
        if ctrl[i,0] or (i and not np.array_equal(ctrl[i,1:],ctrl[i-1,1:])) or not active[i]:
            past.clear();epoch=i
        if not active[i]:
            records.append(dict(frame=i,epoch=epoch,count=0));continue
        z=np.fft.rfft2(p[i],axes=(0,1))/n
        y=np.fft.rfft2(p[i]-r[i],axes=(0,1))/n
        src=np.fft.rfft2(raw[i],axes=(0,1))/n
        median=float(np.median(abs(src[:,1:end])))
        q=max(median**2/np.log(2),(np.finfo(float).eps*max(1,float(abs(raw[i]).max())))**2/n)
        g=float(z[0,0].real@LUMA)
        past.append((z,y,g,q))
        if len(past)>HISTORY:past.pop(0)
        m=len(past)
        if m<MIN_COUNT:result[i]=p[i]-r[i]
        else:
            zs=np.stack([v[0] for v in past]);ys=np.stack([v[1] for v in past])
            gs=np.array([v[2] for v in past])[:,None,None,None]
            zm=zs.mean(0);ym=ys.mean(0);gm=float(gs.mean())
            zc=zs-zm;yc=ys-ym;gc=gs-gm
            ridge=RIDGE*np.mean([v[3] for v in past])
            vz=np.mean(abs(zc)**2,axis=0)+ridge
            vg=float(np.mean(gc**2))+ridge*float(LUMA@LUMA)
            cross=np.mean(np.conj(zc)*gc,axis=0)
            zy=np.mean(np.conj(zc)*yc,axis=0);gy=np.mean(gc*yc,axis=0)
            det=vz*vg-abs(cross)**2
            # Collinear global DC and local mode cannot identify two effects.
            # Avoid cancellation divided by a tiny clipped determinant. Use
            # the original one-feature model at numerical rank deficiency.
            identified=det>64*np.finfo(float).eps*(vz*vg)
            az=np.divide(vg*zy-cross*gy,det,out=zy/vz,where=identified)
            ag=np.divide(vz*gy-np.conj(cross)*zy,det,out=np.zeros_like(gy),where=identified)
            prediction=ym+az*(z-zm)+ag*(g-gm)
            result[i]=np.fft.irfft2(prediction*n,s=(h,w),axes=(0,1))
        records.append(dict(frame=i,epoch=epoch,count=m,nominal_variance=q,global_pilot_luminance_dc=g,
            joint_identified_fraction=float(identified.mean()) if m>=MIN_COUNT else None))
    if not np.isfinite(result).all():raise ValueError('Nonfinite response fit')
    return result,records
