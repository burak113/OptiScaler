"""Unexecuted Part 2 GPU regressions; run only after user authorizes validation."""
import os
for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_MAX_THREADS'):os.environ[k]='2'
import psutil
psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
from pathlib import Path
import json
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as a

def main():
    out=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/tmp/research_tests'));out.mkdir(parents=True,exist_ok=True)
    with a.GPUWorker(out/'worker'):
        n=64;rng=np.random.default_rng(17)
        image=rng.uniform(-1,1,(n,n,4)).astype(np.float32)
        stats=t._dispatch('FSRDProbeInputs',dict(Extent=[n,n],Base=[0,0],ChannelMask=[1,1,1,1],Row=0),[image],[2],(1,1),output_sizes=[(4,1)])[0][0]
        t.check('64x64 input probe signed means',np.allclose(stats[0],image.mean((0,1)),atol=1e-6))
        t.check('64x64 input probe maximum absolute values',np.array_equal(stats[1],abs(image).max((0,1))))
        t.check('64x64 input probe nonzero fractions',np.all(stats[2]==1))
        black=np.zeros_like(image);black[...,3]=1
        stats=t._dispatch('FSRDProbeInputs',dict(Extent=[n,n],Base=[0,0],ChannelMask=[1,0,0,0],Row=0),[black],[2],(1,1),output_sizes=[(4,1)])[0][0]
        t.check('absent scalar channels do not count as populated',np.all(stats[:3]==0))
        for label,raw in [('constant',np.full_like(image,.25)),('spatial_noise',image)]:
            final=raw*.5
            means=t._dispatch('FSRDReference',dict(Extent=[n,n],RawBase=[0,0],Count=1,Target=1),[raw,final],[2,2,2],(n,n))
            t.check('reference '+label+' first-sample raw mean exact',np.array_equal(means[0],raw))
            t.check('reference '+label+' first-sample variance zero',np.all(means[1]==0))
            t.check('reference '+label+' first-sample final mean exact',np.array_equal(means[2],final))
        # Positive and inverse known lighting/albedo relationships exercise the real leak shader.
        albedo=np.broadcast_to(np.linspace(.05,.95,n,dtype=np.float32)[None,:,None],(n,n,3)).copy()
        q=a.rgba(albedo);depth=np.ones((n,n),np.float32);normal=a.rgba(np.broadcast_to([.5,.5,0],(n,n,3)))
        for beta in [-1,0,1]:
            light=a.rgba(albedo**beta)
            view=t._dispatch('FSRDLeak',dict(DstTexSize=[n,n,1/n,1/n],Flags=1),[light,light,q,q,depth,normal],[10],(n,n))[0][8:-8,8:-8,:3]
            if beta==1:passed=np.mean(view[...,0])>5*np.mean(view[...,2])+1e-3
            elif beta==-1:passed=np.mean(view[...,2])>5*np.mean(view[...,0])+1e-3
            else:passed=np.max(abs(view[...,0]-view[...,2]))<2e-3
            t.check('leak known log-log slope '+str(beta),passed)
    failures=sum(not x['passed'] for x in t.checks)
    (out/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,failures=failures,peak_wset=psutil.Process().memory_info().peak_wset),indent=2))
    return bool(failures)
if __name__=='__main__':raise SystemExit(main())
