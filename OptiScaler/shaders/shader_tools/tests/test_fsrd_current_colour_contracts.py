"""Current-only colour contracts; no archived shader is needed for correctness.

Keep these mandatory even when the V9/V10 relative quality comparisons are skipped.
RR is an independent synthetic estimate; this does not execute the AMD model.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run():
    t.OUT = t.OUT.parent/'current_colour_contracts'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w,h = 73,59
    y,x = np.indices((h,w))
    depth = np.full((h,w),10,np.float32)
    normal = t.rgba(w,h,(.5,.5,.1),1/3)
    albedo = t.rgba(w,h,(1,1,1))
    zero = t.rgba(w,h,(0,0,0))
    target = t.rgba(w,h,(.4,.4,.4))
    red=.22*np.sin(x*.55+y*.13)+.08*np.cos(y*.6)
    blue=.18*np.sin(x*.2-y*.7)
    target[...,0]+=red; target[...,2]+=blue
    target[...,1]-=(.2126*red+.0722*blue)/.7152
    crop=(slice(6,-6),slice(6,-6),slice(0,3))

    def comp(rr,ref,n=normal,z=depth,a=albedo,detail=1.0,anchor=4,mix=1):
        return t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
            'DetailPreservation':detail,'FloorHandoverAnchorClamp':anchor,'FloorHandoverCorrelationMix':mix},
            [zero,a,rr,a,zero,n,ref,z],[10],(w,h))[0]

    for level in (.001,.01,.1,1,10,40,100):
        clean=target.copy(); clean[...,:3]*=level
        ref=t.seed(clean)[3]; out=comp(clean,ref)
        error=float(np.sqrt(np.mean((out[crop]-clean[crop])**2)))
        t.check(f'already sharp chromatic structure retained exposure={level}',
                error<.001*level,error=error)
        t.check(f'colour radiance finite and nonnegative exposure={level}',
                np.all(np.isfinite(out)) and np.all(out[...,:3]>=0))

    random=np.random.default_rng(11819)
    noisy=target.copy(); noisy[...,:3]=np.maximum(target[...,:3]+random.normal(0,.06,(h,w,3)),0)
    ref=t.seed(noisy)[3]; rr=blur(target,3)
    for label,opts in [('detail disabled',dict(detail=0))]:
        t.check(label+' is unaffected by handover controls',
                np.array_equal(comp(rr,ref,anchor=0,mix=0,**opts),comp(rr,ref,**opts)))
    t.check('ordinary material excludes Anchor/Mix/recovery',
            np.array_equal(comp(rr,ref,detail=0),comp(rr,ref,n=t.rgba(w,h,(.5,.5,.1),0))))
    routed=ref.copy(); routed[...,3]=-1
    t.check('routed content excludes correction exactly',
            np.array_equal(comp(rr,routed),comp(rr,routed,detail=0)))

    for boundary in ('depth','normal','albedo','routing'):
        z=depth.copy(); n=normal.copy(); a=albedo.copy(); before=ref.copy()
        if boundary=='depth': z[:,w//2:]=40
        elif boundary=='normal': n[:,w//2:,0:2]=0
        elif boundary=='albedo': a[:,w//2:,:3]=.1
        else: before[:,w//2:,3]=-1
        changed=before.copy(); changed[:,w//2:,:3]=4
        rr2=target.copy(); rr2[:,w//2:,:3]=2
        one=comp(target,before,z=z,n=n,a=a); two=comp(rr2,changed,z=z,n=n,a=a)
        t.check(boundary+' cannot lend palette evidence',
                np.max(np.abs(one[:,:w//2,:3]-two[:,:w//2,:3]))<.001)
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'current colour contract regression'


if __name__=='__main__': run()
