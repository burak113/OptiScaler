"""Light Anchor Mix must retain attenuated diagonal detail at Anchor=4.

Independent noisy frames and moving radiance on stationary geometry. The existing
specular-noise suite separately bounds grain, shared noise and lying seed alpha.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run():
    t.build_runner()
    w,h=65,49
    y,x=np.indices((h,w))
    roi=(slice(8,-8),slice(8,-8),slice(0,3))
    zero=t.rgba(w,h,(0,0,0))
    spec=t.rgba(w,h,(.8,.8,.8)); diff=t.rgba(w,h,(.2,.2,.2))
    normal=t.rgba(w,h,(.5,.5,.4),0)
    depth=np.full((h,w),10,np.float32)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=2,
            SpatialTemporalMask=2,SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,
            FloorHandoverCorrelationMix=1,LumaRecovery=1,ChromaRecovery=1)
    records=[]
    for frame,phase in enumerate((0.0,.85,2.4)):
        truth=t.rgba(w,h,(.35,.4,.45))
        truth[...,:3]+=(.12*np.sin(x*.91+y*.83+phase))[...,None]
        rr=blur(truth,6)
        rr_spec=rr.copy(); rr_spec[...,:3]/=.8
        ref=truth.copy()
        ref[...,:3]+=np.random.default_rng(137551+frame).normal(0,.01,(h,w,3))
        ref[...,3]=.01
        signal=truth[roi]-np.mean(truth[roi],axis=(0,1),keepdims=True)
        gains={}
        for anchor in (0,4):
            out=t.dispatch('FSRDOutputComp',dict(cb,FloorHandoverAnchorClamp=anchor),
                [rr_spec,spec,zero,diff,zero,normal,ref,depth],[10],(w,h))[0]
            error=float(np.mean((out[roi]-truth[roi])**2))
            gains[anchor]=float(np.sum((out[roi]-np.mean(out[roi],axis=(0,1),keepdims=True))*signal)/
                                np.sum(signal**2))
            records.append(dict(frame=frame,anchor=anchor,mse=error,contrast=gains[anchor]))
            t.check(f'phase {phase} anchor {anchor} improves blurred RR',
                    error < float(np.mean((rr[roi]-truth[roi])**2))*.3,mse=error,contrast=gains[anchor])
        t.check(f'phase {phase} positive anchor retains diagonal detail',gains[4]>.60,contrast=gains[4])
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,records=records),indent=2))
    assert all(c['passed'] for c in t.checks), 'light recovery detail regression'


if __name__=='__main__': run()
