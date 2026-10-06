"""Volume survival under incompatible surface guides and signed RR band replacement.

The RR fixtures deliberately remove volume or contain displaced texture. Identity RR
cannot detect these regressions. Baseline DXIL supplies an independent handover comparison.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t

def run():
    t.OUT=t.OUT.parent/'volume_handover';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=49,33
    rng=np.random.default_rng(838)
    z=10+rng.uniform(0,30,(h,w)).astype(np.float32)
    n=t.rgba(w,h,(0,0,1));a=t.rgba(w,h,(.5,.5,.5))
    volume=np.array([.12,.18,.3],np.float32)
    c=t.rgba(w,h,volume)
    c[8,9,:3]+=80
    f,z,g,r=t.seed(c,depth=z,normal=n,albedo=a)
    f=t.filter_floor(f,z,g,a)
    # RR erases the residual entirely: only the Floor can preserve this layer.
    crop=f[3:-3,3:-3,:3]
    t.check('common volume survives incompatible background geometry',
        np.min(np.mean(crop,axis=(0,1))/volume)>.9,
        retained_fraction=float(np.min(np.mean(crop,axis=(0,1))/volume)))
    t.check('volume protection does not restore isolated bright noise',np.max(f[8,9,:3])<.5)
    zero=t.rgba(w,h,(0,0,0));alb=t.rgba(w,h,(.5,.5,.5))
    vals={'InvViewMatrix':np.eye(4).ravel(),'InvProjMatrix':np.eye(4).ravel(),
        'PrevViewMatrix':np.eye(4).ravel(),'DstTexSize':[w,h,1/w,1/h],
        'MotionInputSize':[w,h,1/w,1/h],'MotionTransform':[1,1,0,0],
        'NearPlane':.1,'FarPlane':1000,'DemodDivisorFloor':.008}
    for enabled in (True,False):
        vals['Flags']=(1<<1)|((1<<7) if enabled else 0)
        packed=t.dispatch('FSRDInputConv',vals,[c,z,zero,n,np.full((h,w),.5,np.float32),
            z,alb,alb,zero,f,zero,zero,zero,zero,z,zero,r],
            [10,10,10,24,28,28,10,10],(w,h))
        output=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h]},
            [zero,packed[4],zero,packed[5],packed[6],packed[3],packed[7],z],[10],(w,h))[0]
        retained=float(np.min(np.mean(output[3:-3,3:-3,:3],axis=(0,1))/volume))
        t.check(f'RR-erased volume after actual packing/composition Floor={enabled}',
            retained>.9 if enabled else retained<.01,retained_fraction=retained)
    noisy=t.rgba(w,h,(1,1,1));noisy[...,:3]+=rng.normal(0,.12,noisy[...,:3].shape)
    nf,nz,ng,nr=t.seed(noisy,depth=z,normal=n,albedo=a)
    nf=t.filter_floor(nf,nz,ng,a)
    t.check('non-surface pedestal still suppresses grain',
        np.std(nf[3:-3,3:-3,:3])<np.std(noisy[3:-3,3:-3,:3])*.7,
        floor_std=float(np.std(nf[3:-3,3:-3,:3])))
    dark=c.copy();dark[h//2,w//2,:3]=0
    df=t.seed(dark,depth=z,normal=n,albedo=a)[0]
    t.check('volume fallback cannot lift unsupported black foreground',np.max(df[h//2,w//2,:3])<.001)
    # Sharp current animated panel with a displaced RR high band. A same-sign
    # magnitude-only boost leaves the obsolete RR stripe in place.
    yy,xx=np.indices((h,w))
    ref=t.rgba(w,h,(.3,.3,.3))
    for x in (12,24,36):ref[:,x:x+2,:3]=.8
    rr=t.rgba(w,h,(.3,.3,.3))
    for x in (14,26,38):rr[:,x:x+2,:3]=.8
    depth=np.full((h,w),10,np.float32);normal=t.rgba(w,h,(.5,.5,.1),1/3)
    alb=t.rgba(w,h,(1,1,1));zero=t.rgba(w,h,(0,0,0))
    out=t.compose(rr,ref,depth,normal,alb)
    old=t.reference('baseline')
    hand=ref.copy();hand[...,3]=1
    idx=(slice(3,-3),[14,26,38],slice(0,3))
    error_before=float(np.mean(np.abs(rr[idx]-ref[idx])))
    error_after=float(np.mean(np.abs(out[idx]-ref[idx])))
    t.check('new handover replaces obsolete RR high band',error_after<error_before*.8,
        before=error_before,after=error_after)
    if old is not None:
        baseline=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
            'FloorHandoverAnchorClamp':2,'FloorHandoverCorrelationMix':1,'CorrelationBias':0},
            [zero,zero,rr,alb,zero,ref,zero,normal,hand],[10],(w,h),directory=old)[0]
        old_error=float(np.mean(np.abs(baseline[idx]-ref[idx])))
        t.check('reference handover removes displaced RR stripe',old_error<error_before*.8,
            baseline_error=old_error)
        t.check('new handover approaches reference displaced-stripe error',error_after<=old_error+.05)
    else:
        t.skip('original reference displaced-stripe and curved glyph A/B comparisons')
    # RGB mid-tone glyph samples are valid bounded samples, not necessarily
    # bilateral averages of other strokes. Rank acceptance must retain them.
    panel=t.rgba(w,h,(.1,.1,.1))
    panel[7:26,12:36,:3]=.7
    panel[10:23:3,14:34,0]=.85
    panel[10:23:3,14:34,1]=.45
    panel[10:23:3,14:34,2]=.2
    r=t.seed(panel)[3]
    t.check('rank reference keeps bounded coloured glyph interiors',
        np.max(np.abs(r[11:22:3,17:31,:3]-panel[11:22:3,17:31,:3]))<.01)
    radius=np.sqrt((xx-w//2)**2+(yy-h//2)**2)
    coverage=np.clip(1.2-np.abs(radius-7),0,1)
    glyph=t.rgba(w,h,(.1,.1,.1))
    glyph[...,:3]+=coverage[...,None]*np.array([.8,.6,.2])
    ref=t.seed(glyph)[3]
    vals={'InvViewMatrix':np.eye(4).ravel(),'InvProjMatrix':np.eye(4).ravel(),
        'PrevViewMatrix':np.eye(4).ravel(),'DstTexSize':[w,h,1/w,1/h],
        'MotionInputSize':[w,h,1/w,1/h],'MotionTransform':[1,1,0,0],
        'NearPlane':.1,'FarPlane':1000,'Flags':(1<<1)|(1<<7),
        'DemodDivisorFloor':.008,'FloorIsolation':1,'FloorHandoverMode':1,
        'FloorHandoverStrength':1,'FloorHandoverDetail':1}
    rr=glyph.copy();rr[...,:3]=np.roll(glyph[...,:3],2,axis=1)
    out=t.compose(rr,ref,depth,normal,alb)
    active=(coverage>0)|(np.roll(coverage,2,axis=1)>0)
    err=float(np.mean(np.abs(out[active,:3]-glyph[active,:3])))
    if old is not None:
        packed=t.dispatch('FSRDInputConv',vals,[glyph,depth,zero,t.rgba(w,h,(0,0,1)),
            np.zeros((h,w),np.float32),depth,alb,alb,zero,zero,zero,zero,zero,zero,depth,zero],
            [10,10,10,24,28,28,10,10],(w,h),directory=old)
        glyph_error=float(np.max(np.abs(ref[...,:3]-glyph[...,:3])))
        rank_error=float(np.max(np.abs(packed[7][...,:3]-glyph[...,:3])))
        t.check('curved antialiased glyph approaches reference rank fidelity',glyph_error<rank_error+.025,
            new_max_error=glyph_error,reference_rank_max_error=rank_error)
        baseline=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
            'FloorHandoverAnchorClamp':2,'FloorHandoverCorrelationMix':1,'CorrelationBias':0},
            [zero,zero,rr,alb,zero,glyph,zero,normal,packed[7]],[10],(w,h),directory=old)[0]
        old_err=float(np.mean(np.abs(baseline[active,:3]-glyph[active,:3])))
        t.check('animated curved glyph approaches reference final handover',err<=old_err+.025,
            new_error=err,reference_error=old_err)
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'records':t.records,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'Volume/handover regression'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')

if __name__=='__main__':run()
