"""Production Recovery v2 volumetry: energy, noise, history and depth isolation."""
from pathlib import Path
import json
import os
import sys
import numpy as np
import fsrd_alpha_common as a
import run_fsrd_gpu_tests as t


class VolumeState:
    def __init__(self, w, h, response=0.05, directory=None):
        self.w, self.h = w,h
        self.response = response
        self.directory = t.PRE if directory is None else Path(directory)
        self.tiles = ((w+7)//8,(h+7)//8)
        self.history = np.zeros((self.tiles[1],self.tiles[0],4),np.float32)
        self.variance = np.zeros_like(self.history)
        self.valid = False

    def step(self, raw, composed, depth, motion=None, strength=1, reset=False, jitter=(0,0), debug=0):
        w,h = self.w,self.h
        if motion is None:
            motion = np.zeros((h,w,4),np.float32)
            motion[...,3] = 1
        tiles = t._dispatch("FSRDVolumeGather",
            dict(RenderSize=[w,h,1/w,1/h],InputBase=[0,0]),
            [raw],[10],(w,h),directory=self.directory,output_sizes=[self.tiles])[0]
        self.history,self.variance = t._dispatch("FSRDRecoveryVolumeAccumulate",
            dict(DstTexSize=[w,h,1/w,1/h],HistoryJitterDelta=jitter,
                 HistoryValid=int(self.valid and not reset),Response=self.response),
            [composed,tiles,self.history,depth,motion,self.variance],
            [10,2],(w,h),directory=self.directory,output_sizes=[self.tiles,self.tiles])
        self.valid = True
        return self.apply(composed,depth,strength,debug)

    def apply(self, composed, depth, strength=1, debug=0):
        return t._dispatch("FSRDRecoveryVolumeApply",
            dict(DstTexSize=[self.w,self.h,1/self.w,1/self.h],Strength=strength,Debug=debug),
            [composed,self.history,depth,self.variance],[10],(self.w,self.h),directory=self.directory)[0]


def main():
    w=h=64
    depth=np.full((h,w),10,np.float32)
    zero=a.rgba(np.zeros((h,w,3),np.float32),.625)
    heavy=zero.copy()
    heavy[::8,::8,:3]=64
    with a.GPUWorker(t.OUT/"worker"):
        small=np.random.default_rng(8).uniform(0,3,(13,17,4)).astype(np.float32)
        partial=t._dispatch("FSRDVolumeGather",dict(RenderSize=[17,13,1/17,1/13],InputBase=[0,0]),
                            [small],[10],(17,13),output_sizes=[(3,2)])[0]
        expected=np.array([[small[y:y+8,x:x+8,:3].astype(np.float16).astype(np.float32).mean((0,1))
                            for x in range(0,17,8)] for y in range(0,13,8)])
        t.check("partial edge tiles use their actual sample count",np.max(abs(partial[...,:3]-expected))<.002)
        state=VolumeState(w,h)
        tile=t._dispatch("FSRDVolumeGather",dict(RenderSize=[w,h,1/w,1/h],InputBase=[0,0]),
                         [heavy],[10],(w,h),output_sizes=[state.tiles])[0]
        t.check("unclipped heavy-tail tile mean is one",np.all(tile[...,:3]==1))
        for f in range(40):
            output=state.step(heavy,zero,depth)
            if f==0:
                t.check("restart frame never displays a single-frame estimate",
                        np.array_equal(output,zero.astype(np.float16).astype(np.float32)))
        t.check("heavy-tailed input restores unbiased mean",np.max(abs(output[...,:3]-1))<.002,
                mean=float(output[...,:3].mean()))
        one=zero.copy(); one[...,:3]=1
        state=VolumeState(w,h)
        for _ in range(12):
            output=state.step(heavy,one,depth)
        t.check("composition equal to raw mean adds exactly zero",np.array_equal(output,one))
        base=zero.copy(); base[...,:3]=.5
        state=VolumeState(w,h)
        for f in range(128):
            raw=base.copy();raw[...,:3]+=.2 if f%2==0 else -.2
            output=state.step(raw,base,depth)
        t.check("zero-mean temporal noise does not lift",np.array_equal(output,base))
        z=depth.copy();z[:,w//2:]=100
        raw=zero.copy();raw[:,:w//2,:3]=1
        state=VolumeState(w,h)
        for _ in range(12):
            output=state.step(raw,zero,z)
        t.check("no restore crosses a depth edge",np.all(output[:,w//2:,:3]==0) and np.all(output[:,:w//2,:3]>.99))
        output=state.step(zero,zero,z*2)
        t.check("depth change restarts the accumulated correction",np.array_equal(output,zero) and np.all(state.variance[...,1]==1))
        rng=np.random.default_rng(5)
        signed=a.rgba(rng.uniform(-1,3,(h,w,3)).astype(np.float32),.625)
        output=state.apply(signed,depth,strength=0)
        t.check("strength zero is bit-exact, including negative HDR and alpha",
                np.array_equal(output,signed.astype(np.float16).astype(np.float32)))
        state.history[...,:3]=(.3,-.3,.3);state.history[...,3]=10
        state.variance[...,0]=.000001;state.variance[...,1]=40
        view=state.apply(base,depth,debug=1)
        t.check("signed debug distinguishes positive and negative correction",np.all(view[...,0]>.5) and np.all(view[...,1]<.5))
        confidence=state.apply(base,depth,debug=2)
        t.check("negative total energy displays zero diagnostic confidence",np.all(confidence[...,:3]==0))
        state.history[...,:3]=.3
        low_variance=state.apply(base,depth)
        high_confidence=state.apply(base,depth,debug=2)
        state.variance[...,0]=10000
        high_variance=state.apply(base,depth)
        low_confidence=state.apply(base,depth,debug=2)
        t.check("high-variance mature energy restores without a significance gate",
                np.array_equal(high_variance,low_variance) and np.all(high_variance[...,:3]>.79))
        t.check("confidence remains diagnostic and responds to variance",
                np.all(low_confidence[...,:3]<high_confidence[...,:3]))
        invalid=state.apply(base,np.zeros_like(depth))
        t.check("invalid depth never adds energy",np.array_equal(invalid,base))
    t.OUT.mkdir(parents=True,exist_ok=True)
    (t.OUT/"results.json").write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    count=sum(not x["passed"] for x in t.checks)
    print(f"recovery volume: {count} failures",flush=True)
    return bool(count)


if __name__=="__main__":
    sys.exit(main())
