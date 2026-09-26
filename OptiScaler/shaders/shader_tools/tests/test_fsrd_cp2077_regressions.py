"""GPU regressions for the mechanisms exposed by the CP2077 captures.

Synthetic guides exercise failure mechanisms, not a replay of the game's G-buffer.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t

def run():
    t.OUT=t.OUT.parent/'cp2077_regressions';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=33,25
    mid=(h//2,w//2)
    c=t.rgba(w,h,(.2,.2,.2));c[mid][:3]=100
    for guide in ('depth','normal','albedo'):
        z=np.full((h,w),10,np.float32)
        n=t.rgba(w,h,(0,0,1));a=t.rgba(w,h,(.5,.5,.5))
        if guide=='depth':z[mid]=20
        elif guide=='normal':n[mid][:3]=(1,0,0)
        else:a[mid][:3]=(1,0,0)
        f,z,g,r=t.seed(c,depth=z,normal=n,albedo=a)
        f=t.filter_floor(f,z,g,a)
        # Preserve the common .2 pedestal even when background guides disagree;
        # reject the 100-valued impulse, not the shared illumination beneath it.
        t.check('unsupported '+guide+' preserves pedestal, rejects impulse',np.max(np.abs(f[mid][:3]-.2))<.001,
                maximum=float(np.max(f[mid][:3])))
        t.check('unsupported '+guide+' sample has no detail',r[mid][3]<0)
        zero=t.rgba(w,h,(0,0,0));rough=np.zeros((h,w),np.float32)
        vals={'InvViewMatrix':np.eye(4).ravel(),'InvProjMatrix':np.eye(4).ravel(),
            'PrevViewMatrix':np.eye(4).ravel(),'DstTexSize':[w,h,1/w,1/h],
            'MotionInputSize':[w,h,1/w,1/h],'MotionTransform':[1,1,0,0],
            'NearPlane':.1,'FarPlane':1000,'FloorDetailPreservation':.35,
            'Flags':(1<<1)|(1<<7),'DemodDivisorFloor':.008}
        # Keep the RR albedos representable, independently of the rejected seed guide.
        alb=t.rgba(w,h,(.5,.5,.5))
        packed=t.dispatch('FSRDInputConv',vals,
            [c,z,zero,n,rough,z,alb,alb,zero,f,zero,zero,zero,zero,z,zero,r],
            [10,10,10,24,28,28,10,10],(w,h))
        # Quantized demodulation roundoff intentionally remains in Skip for closure.
        # Permit one FP16 relative spacing, not a raw-radiance bypass.
        t.check('unsupported '+guide+' Skip limited to pedestal and storage loss; detail rejected',
            np.max(packed[6][mid][:3])<.2+np.max(c[mid][:3])/1024 and packed[7][mid][3]<0,
            skip=float(np.max(packed[6][mid][:3])), detail_alpha=float(packed[7][mid][3]))
        out=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':0},
            [packed[0],packed[4],packed[1],packed[5],packed[6],packed[3],packed[7],z],[10],(w,h))[0]
        t.check('unsupported '+guide+' energy remains available to RR',
            np.max(np.abs(out[mid][:3]-c[mid][:3]))<.2)
    # Clean, broad structure is deliberately >25% of the 5x5 window: IQR is
    # contrast here, not noise. One-pixel-line tests do not expose this failure.
    for orient in ('horizontal','vertical'):
        c=t.rgba(w,h,(.05,.05,.05))
        if orient=='vertical':c[:,w//2:,:3]=1
        else:c[h//2:,:,:3]=1
        f,z,g,r=t.seed(c)
        t.check(orient+' edge reference intact',np.max(np.abs(r[2:-2,2:-2,:3]-c[2:-2,2:-2,:3]))<.01)
        t.check(orient+' clean edge not labelled noise',float(r[mid][3])<.005,sigma=float(r[mid][3]))
        # A blurred RR output, not identity RR, tests whether detail actually returns.
        rr=c.copy()
        dim=1 if orient=='vertical' else 0
        rr[...,:3]=(.25*np.roll(c[...,:3],1,axis=dim)+.5*c[...,:3]+.25*np.roll(c[...,:3],-1,axis=dim))
        for material in (0,1):
            normal=t.rgba(w,h,(.5,.5,.1),material/3)
            out=t.compose(rr,r,z,normal,t.rgba(w,h,(1,1,1)))
            before=float(np.mean(np.abs(rr[2:-2,2:-2,:3]-c[2:-2,2:-2,:3])))
            after=float(np.mean(np.abs(out[2:-2,2:-2,:3]-c[2:-2,2:-2,:3])))
            if material==1:
                t.check(f'{orient} selected screen restores blurred RR',after<before*.95,
                        error_before=before,error_after=after)
            else:
                t.check(f'{orient} ordinary surface stays on RR plus filtered Floor',
                        np.array_equal(out[...,:3],rr[...,:3].astype(np.float16).astype(np.float32)))
        # Zero-roughness by itself may never authorize noisy or bypassed detail.
        for sigma in (100,-1):
            blocked=r.copy();blocked[...,3]=sigma
            out=t.compose(rr,blocked,z,normal,t.rgba(w,h,(1,1,1)))
            t.check(f'{orient} material1 sigma={sigma} unchanged',np.max(np.abs(out[...,:3]-rr[...,:3]))<.002)
        out=t.compose(rr,r,z,normal,t.rgba(w,h,(1,1,1)),detail=0)
        t.check(orient+' material1 detail zero unchanged',np.max(np.abs(out[...,:3]-rr[...,:3]))<.002)
    # Preserve the historical meaning of DenoiserOutput independently of albedo/skip.
    zero=t.rgba(w,h,(0,0,0));spec=t.rgba(w,h,(1,2,3));diff=t.rgba(w,h,(.2,.3,.4))
    skip=t.rgba(w,h,(4,4,4));alb=t.rgba(w,h,(.1,.1,.1))
    out=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'Flags':(3<<17)|(1<<16)},
        [spec,alb,diff,alb,skip,normal,r,z],[10],(w,h))[0]
    t.check('DenoiserOutput compares same demodulated signals as baseline',
        np.max(np.abs(out[...,:3]-(spec+diff)[...,:3]))<.005)
    out=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'Flags':(13<<17)|(1<<16)},
        [spec,alb,diff,alb,skip,normal,r,z],[10],(w,h))[0]
    expected=(spec[...,:3]+diff[...,:3])*(26/255)+skip[...,:3]
    t.check('ReconstructedColor displays remodulated RR plus Skip',np.max(np.abs(out[...,:3]-expected))<.005)
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings},indent=2))
    assert all(x['passed'] for x in t.checks),'CP2077 regression failed'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')

if __name__=='__main__':run()
