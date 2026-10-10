"""GPU checks for FSRDRRMotion (RR's copy of the motion vectors with the jitter difference).

RR ignores jitterOffsets and reads its motion vectors as the texel-to-texel displacement between the jittered
rasters; the converter keeps the canonical unjittered field for every other consumer. Checked here:
- XY gain exactly (J_prev - J_cur) / size and Z/W pass through, for arbitrary motion;
- zero jitter difference (reset) returns the canonical field bit-exactly;
- the dispatch covers a render size that is not a multiple of the 8x8 group.
The registration itself was measured with real AMD RR (noise-free synthetic sequence, Halton jitter): with the
canonical field RR's output trails the current frame by -1 x J_cur (0.23 px mean shift); with the difference added
the shift is 0.04 px and independent of the jitter.
"""
import os
for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_MAX_THREADS'):
    os.environ[k] = '2'
from pathlib import Path
import json
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as a


def rr_motion(motion, w, h, j_cur, j_prev):
    delta = [(j_prev[0] - j_cur[0]) / w, (j_prev[1] - j_cur[1]) / h]
    out, = t._dispatch('FSRDRRMotion', dict(DstTexSize=[w, h, 1 / w, 1 / h], JitterDeltaUv=delta), [motion], [10], (w, h))
    return out, np.array(delta, np.float32)


def main():
    out = Path(os.environ.get('FSRD_RR_MOTION_TEST_OUTPUT', 'F:/FSRD/tmp/rr_motion_tests'))
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    with a.GPUWorker(out / 'worker'):
        for w, h in ((64, 48), (61, 37)):
            motion = rng.uniform(-.02, .02, (h, w, 4)).astype(np.float16).astype(np.float32)
            motion[..., 3] = (rng.uniform(size=(h, w)) > .2).astype(np.float32)
            res, delta = rr_motion(motion, w, h, (-0.09375, 0.40625), (0.34375, -0.15625))
            expect = motion[..., :2] + delta
            err = float(np.abs(res[..., :2] - expect).max())
            t.check('%dx%d: XY gain the jitter difference' % (w, h), err < 1e-4, detail=dict(max_error=err))
            t.check('%dx%d: depth delta and valid pass through' % (w, h), np.array_equal(res[..., 2:], motion[..., 2:]))
            same, _ = rr_motion(motion, w, h, (0.2, -0.3), (0.2, -0.3))
            t.check('%dx%d: equal jitter returns the canonical field' % (w, h), np.array_equal(same, motion))
    failures = sum(not x['passed'] for x in t.checks)
    (out / 'results.json').write_text(json.dumps(dict(checks=t.checks, failures=failures), indent=2))
    print('rr motion: %d checks, %d failures' % (len(t.checks), failures))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
