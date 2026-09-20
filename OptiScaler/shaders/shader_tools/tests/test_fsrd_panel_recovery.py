"""Severe billboard blur, packed roughness floor, and noise-return regressions."""
import json
import numpy as np
import run_fsrd_gpu_tests as t

def blur(c,passes):
    out=c.copy()
    for _ in range(passes):
        for axis in (0,1):
            out=.25*np.roll(out,1,axis)+.5*out+.25*np.roll(out,-1,axis)
    return out

def run():
    t.OUT=t.OUT.parent/'panel_recovery';t.OUT.mkdir(parents=True,exist_ok=True);t.build_runner()
    w,h=65,49;yy,xx=np.indices((h,w));rng=np.random.default_rng(4091)
    zero=t.rgba(w,h,(0,0,0));n=t.rgba(w,h,(0,0,1));a=t.rgba(w,h,(.5,.5,.5))
    depth=np.full((h,w),10,np.float32);rough=np.zeros((h,w),np.float32)
    c=t.rgba(w,h,(.8,.8,.8))
    ink=((xx>=17)&(xx<=19)&(yy>=8)&(yy<=40))|((yy>=20)&(yy<=22)&(xx>=17)&(xx<=45))
    c[ink,:3]=.1
    f,z,g,ref=t.seed(c)
    vals={'InvViewMatrix':np.eye(4).ravel(),'InvProjMatrix':np.eye(4).ravel(),
        'PrevViewMatrix':np.eye(4).ravel(),'DstTexSize':[w,h,1/w,1/h],
        'MotionInputSize':[w,h,1/w,1/h],'MotionTransform':[1,1,0,0],
        'NearPlane':.1,'FarPlane':1000,'FloorDetailPreservation':.35,
        'Flags':(1<<1)|(1<<7),'DemodDivisorFloor':.008}
    # The zero-rough classification stays the title's exact-zero reading, and the RR-facing
    # roughness is now this pipeline's own compatibility value: only the automatic policy
    # moves, and only while Floor is enabled.
    packed=t.dispatch('FSRDInputConv',vals,[c,z,zero,n,rough,z,a,a,zero,f,zero,zero,zero,zero,z,zero,ref],
        [10,10,10,24,28,28,10,10],(w,h))
    t.check('exact-zero title roughness keeps unified type1',np.all(np.abs(packed[3][...,3]-1/3)<.001))
    t.check('automatic zero-rough roughness published to RR',
            np.max(np.abs(packed[3][...,2]-.1))<=1/1023)
    off=dict(vals); off['Flags']=off['Flags']&~(1<<7)
    packedOff=t.dispatch('FSRDInputConv',off,[c,z,zero,n,rough,z,a,a,zero,f,zero,zero,zero,zero,z,zero,ref],
        [10,10,10,24,28,28,10,10],(w,h))
    t.check('floor disabled preserves the title roughness and the type',
            np.all(np.abs(packedOff[3][...,2])<=1/1023) and
            np.all(np.abs(packedOff[3][...,3]-1/3)<.001))
    rough2=np.full((h,w),.42,np.float32)
    packed2=t.dispatch('FSRDInputConv',vals,[c,z,zero,n,rough2,z,a,a,zero,f,zero,zero,zero,zero,z,zero,ref],
        [10,10,10,24,28,28,10,10],(w,h))
    t.check('non-zero title roughness is never raised',
            np.max(np.abs(packed2[3][...,2]-.42))<=1/1023 and np.all(packed2[3][...,3]<.001))
    for passes in (2,8,20):
        rr=blur(c,passes)
        # V9: measure maximum recovery with optional RR constraints disabled.
        # Their deliberate blur/cleanliness tradeoff is tested in patch_handover.
        out=t.compose(rr,packed[7],z,packed[3],a,anchor=0,mix=0)
        err=float(np.mean(np.abs(out[ink,:3]-c[ink,:3])))
        t.check(f'blurred panel ink recovers (anchor/mix off) passes={passes}',err<.07,ink_error=err)
    for material in (0,1):
        normal=t.rgba(w,h,(.5,.5,.1),material/3)
        clean=t.rgba(w,h,(.4,.4,.4))
        noisy=clean.copy();noisy[...,:3]+=rng.normal(0,.055,noisy[...,:3].shape)
        ref=t.seed(noisy)[3]
        out=t.compose(clean,ref,z,normal,a)
        rms=float(np.sqrt(np.mean((out[3:-3,3:-3,:3]-clean[3:-3,3:-3,:3])**2)))
        t.check(f'clean RR does not regain white noise material={material}',rms<.004,rms=rms)
    # Sparse positive ray noise over common light with unusable background guides.
    # Every quadrant can contain one impulse: means are not an outlier rejection.
    c=t.rgba(w,h,(.2,.2,.2));impulse=(xx%3==0)&(yy%3==0);c[impulse,:3]=5
    badDepth=10+rng.uniform(0,60,(h,w)).astype(np.float32)
    f,z,g,r=t.seed(c,depth=badDepth)
    t.check('volume pedestal rejects sparse positive ray samples',np.percentile(f[3:-3,3:-3,:3],99)<.3,
        p99=float(np.percentile(f[3:-3,3:-3,:3],99)))
    c=t.rgba(w,h,(.2,.2,.2));mask=rng.random((h,w))<.2;c[mask,:3]=5
    f,z,g,r=t.seed(c,depth=badDepth)
    t.check('volume pedestal rejects randomly clustered bright ray noise',
        np.percentile(f[3:-3,3:-3,:3],99)<.3,p99=float(np.percentile(f[3:-3,3:-3,:3],99)))
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'panel recovery regression'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')

if __name__=='__main__':run()
