"""Exact output gate for adaptive LDS tiles, partial groups and sliding NLM cache.

Requires FSRD_LOSSLESS_BASELINE pointing to frozen pre-optimization shaders.
"""
import json
import os
import numpy as np
import run_fsrd_gpu_tests as t


def run():
    if not os.environ.get('FSRD_LOSSLESS_BASELINE'):
        raise RuntimeError('FSRD_LOSSLESS_BASELINE is required for an independent GPU comparison')
    t.OUT=t.OUT.parent/'optimization_equivalence';t.OUT.mkdir(parents=True,exist_ok=True)
    t.runner=t.OUT/'fsrd_gpu_runner.exe';t.build_runner()
    rng=np.random.default_rng(907012)
    for w,h in ((1,1),(1,9),(9,1),(7,5),(17,13),(41,25)):
        y,x=np.indices((h,w))
        for scale in (1,12000):
            rr=t.rgba(w,h,(0,0,0));rr[...,:3]=rng.uniform(.1,.8,(h,w,3))*scale
            ref=rr.copy();ref[...,:3]*=rng.uniform(.8,1.2,(h,w,3))
            ref[...,3]=.03*scale;ref[(x+y)%13==0,3]=-1
            ref[(x//8+y//8)%3==0,3]=0
            a=t.rgba(w,h,(.5,.5,.5));a[x>w//2,:3]=(.2,.6,.3)
            n=t.rgba(w,h,(.5,.5,.1))
            # Ordinary-only tiles adjacent to wide tiles, a single selected lane
            # at a tile corner, routed classes, and partial image-edge groups.
            mask=((x//8)%3==1)&((y//8)%2==0)
            n[mask,3]=1/3;n[-1,-1,3]=1/3
            n[(x+y)%11==0,3]=2/3
            z=(10+x*.05+y*.03).astype(np.float32);z[x>w//2]+=20
            zero=t.rgba(w,h,(0,0,0));ones=t.rgba(w,h,(1,1,1))
            inputs=[zero,ones,rr,ones,zero,n,ref,z]
            for mode in (0,1,8,15,19,20):
                flags=0 if mode==0 else (1<<16)|(mode<<17)
                t.dispatch('FSRDOutputComp',dict(DstTexSize=[w,h,1/w,1/h],Flags=flags,
                    DetailPreservation=1.0,NoiseSuppression=.75,
                    FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1),inputs,[10],(w,h))
            for detail,noise,anchor,mix in ((0,.75,4,1),(.35,0,0,0),(1,1,8,.3)):
                t.dispatch('FSRDOutputComp',dict(DstTexSize=[w,h,1/w,1/h],
                    DetailPreservation=detail,NoiseSuppression=noise,
                    FloorHandoverAnchorClamp=anchor,FloorHandoverCorrelationMix=mix),inputs,[10],(w,h))
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks)


if __name__=='__main__':run()
