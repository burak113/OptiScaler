"""Previous-depth precision at the production disocclusion threshold."""
from pathlib import Path
import os
import sys
import numpy as np

OUT=Path(os.environ.get('FSRD_HISTORY_PRECISION_TEST_OUTPUT','E:/FSRD/recovery_v2/tests/history_precision'))
os.environ.setdefault('FSRD_GPU_TEST_OUTPUT',str(OUT/'gpu'))
import fsrd_alpha_common as a
import run_fsrd_gpu_tests as t


def main():
    w=h=32
    depth=np.full((h,w),10,np.float32)
    raw=a.rgba(np.full((h,w,3),.5,np.float32))
    zero=np.zeros((h,w,4),np.float32)
    flags=a.conversion_cb(w,h)['Flags']
    near=np.full((h,w),9.6998,np.float32)
    under=np.full((h,w),9.7002,np.float32)
    t.check('precision fixture straddles 3 percent but shares one FP16 value',
            np.array_equal(near.astype(np.float16),under.astype(np.float16)))
    expected=np.zeros((h,w),bool);expected[:-1,:-1]=True
    with a.GPUWorker(OUT/'worker'):
        results=[]
        for previous,enabled in ((near,True),(under,True),(near,False)):
            out=a.convert(raw,raw,raw,depth=depth,motion=zero,
                overrides=dict(Flags=flags|((1<<10) if enabled else 0)),
                resources={17:zero,18:previous})
            results.append(out[2][...,2])
        t.check('R32 previous depth above 3 percent restarts the complete footprint',
                np.array_equal(results[0]>.49*depth,expected))
        t.check('R32 previous depth below 3 percent does not restart',np.all(results[1]==0))
        t.check('disocclusion disabled remains exactly unchanged',np.all(results[2]==0))
    failures=sum(not row['passed'] for row in t.checks)
    print(f'history precision: {failures} failures',flush=True)
    return bool(failures)


if __name__=='__main__':sys.exit(main())
