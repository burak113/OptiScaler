"""Streak filter in composition: production DXIL against an exact NumPy model of the intended filter.

RR outputs carry column stripes (row stripes for the horizontal case). Where the motion field
magnifies the previous frame along one axis (stretch 0.5, gate 1), the demodulated lighting
must be the same-surface Gaussian (sigma 2, radius 5) across the stripes; where it does not
(stretch 1) the output must be bit-identical to the filter being off; off must be bit-identical
to the pre-change DXIL; a depth edge must not be averaged across. Generic, Light and NoRecovery
PSOs are all exercised.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

OUTPUT = Path(os.environ.get('FSRD_STREAK_TEST_OUTPUT', Path(tempfile.gettempdir()) / 'fsrd_streak_filter'))
os.environ.setdefault('FSRD_GPU_TEST_OUTPUT', str(OUTPUT / 'gpu'))
import numpy as np
import fsrd_alpha_common as a
import run_fsrd_gpu_tests as t

BASE = '8b46ea6a498e139b75edda273e0340fde813c1f5'
W = H = 64
STREAK = 1 << 9
failures = []


def check(name, ok, **detail):
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ' ' + repr(detail)), flush=True)
    if not ok:
        failures.append(name)


def directories():
    """Each PSO staged under the generic name, as test_fsrd_composition_variants does."""
    out = {}
    base = OUTPUT / 'base_src'
    base.mkdir(parents=True, exist_ok=True)
    for path in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE, a.SHADER_PATH],
                                        cwd=t.ROOT, text=True).splitlines():
        if Path(path).suffix in ('.hlsl', '.hlsli', '.cso'):
            (base / Path(path).name).write_bytes(subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=t.ROOT))
    for label, source, shader in [('base_generic', base, 'FSRDOutputComp'),
                                  ('base_norecovery', base, 'FSRDOutputCompNoRecovery'),
                                  ('generic', t.PRE, 'FSRDOutputComp'),
                                  ('light', t.PRE, 'FSRDOutputCompLight'),
                                  ('norecovery', t.PRE, 'FSRDOutputCompNoRecovery')]:
        d = OUTPUT / 'shaders' / label
        d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / (shader + '_Shader.cso'), d / 'FSRDOutputComp_Shader.cso')
        shutil.copyfile(source / 'FSRDOutputComp.hlsl', d / 'FSRDOutputComp.hlsl')
        out[label] = d
    return out


def constants(flags, detail=0.0, recovery=1, light_mask=0):
    return dict(DstTexSize=[W, H, 1 / W, 1 / H], Flags=(1 << 3) | flags, DetailPreservation=detail,
                RecoveryMask=recovery, FloorHandoverAnchorClamp=4, SourceUvScale=[1, 1], SourceUvOffset=[0, 0],
                FloorHandoverCorrelationMix=1, HistoryValid=0, HistoryJitterDelta=[0, 0], WriteHistory=0,
                SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1, SpatialTemporalMask=light_mask,
                LumaRecovery=0, ChromaRecovery=0, UnsupportedAlbedoRecovery=0, DemodDivisorFloor=.008)


def fixture(axis, depth_step=False):
    """axis 'y': vertical magnification in rows 16..47, column stripes. axis 'x': the transpose."""
    rng = np.random.default_rng(7 if axis == 'y' else 11)
    stripes_s = rng.uniform(-.3, .3, (W, 3)).astype(np.float32)
    stripes_d = rng.uniform(-.3, .3, (W, 3)).astype(np.float32)
    spec = np.zeros((H, W, 4), np.float32); diff = np.zeros((H, W, 4), np.float32)
    if axis == 'y':
        spec[..., :3] = 1.0 + stripes_s[None]; diff[..., :3] = .8 + stripes_d[None]
    else:
        spec[..., :3] = 1.0 + stripes_s[:, None]; diff[..., :3] = .8 + stripes_d[:, None]
    slope = np.where((np.arange(H) >= 16) & (np.arange(H) < 48), -.5, 0.0)
    mv = np.concatenate([[0], np.cumsum(slope[:-1])]).astype(np.float32)
    motion = np.zeros((H, W, 4), np.float32); motion[..., 3] = 1
    if axis == 'y':
        motion[..., 1] = (mv / H)[:, None]
    else:
        motion[..., 0] = (mv / W)[None, :]
    z = np.full((H, W), 10, np.float32)
    if depth_step:
        if axis == 'y':
            z[:, 32:] = 30
        else:
            z[32:, :] = 30
    normal = t.rgba(W, H, (.5, .5, .5))
    spec_alb = t.rgba(W, H, (.5, .45, .4)); diff_alb = t.rgba(W, H, (.4, .5, .6))
    skip = t.rgba(W, H, (0, 0, 0))
    zero = t.rgba(W, H, (0, 0, 0))
    inputs = [spec, spec_alb, diff, diff_alb, skip, normal, zero, z, motion, t.rgba(W, H, (-1, -1, -1), -1),
              np.zeros((H, W, 4), np.uint32), zero, zero, np.zeros((H, W, 2), np.float32), zero]
    return inputs, spec, diff, spec_alb, diff_alb, z


def expected(axis, spec, diff, spec_alb, diff_alb, z):
    """Exact model: Gaussian across the stripes on gated rows/columns, same surface only."""
    def filt(x):
        out = np.empty_like(x)
        for r in range(H):
            for c in range(W):
                acc = np.zeros(3); ws = 0.0
                for o in range(-5, 6):
                    rr, cc = (r, c + o) if axis == 'y' else (r + o, c)
                    if not (0 <= rr < H and 0 <= cc < W) or abs(z[rr, cc] - z[r, c]) > .02 * abs(z[r, c]):
                        continue
                    w = np.exp(-.125 * o * o); acc += w * x[rr, cc, :3]; ws += w
                out[r, c, :3] = acc / ws
        return out
    return filt(spec)[..., :3] * spec_alb[..., :3] + filt(diff)[..., :3] * diff_alb[..., :3]


def main():
    dirs = directories()
    gated = np.zeros((H, W), bool); untouched = np.zeros((H, W), bool)
    gated[18:46] = True; untouched[:14] = True; untouched[50:] = True
    with a.GPUWorker(OUTPUT / 'worker'):
        for axis in ('y', 'x'):
            for step in (False, True):
                inputs, spec, diff, sa, da, z = fixture(axis, step)
                g = gated if axis == 'y' else gated.T
                u = untouched if axis == 'y' else untouched.T
                want = expected(axis, spec, diff, sa, da, z)
                label = f'{"vertical" if axis == "y" else "horizontal"} magnification{" with depth edge" if step else ""}'
                for pso, detail, recovery, mask in (('generic', 0.0, 1, 0), ('norecovery', 0.0, 1, 0), ('light', .35, 1, 1)):
                    on = t._dispatch('FSRDOutputComp', constants(STREAK, detail, recovery, mask), inputs, [10], (W, H), dirs[pso])[0][..., :3]
                    off = t._dispatch('FSRDOutputComp', constants(0, detail, recovery, mask), inputs, [10], (W, H), dirs[pso])[0][..., :3]
                    err = np.abs(on[g] - want[g]) / np.maximum(want[g], 1e-3)
                    # Composition's own FP16 round trip is ~3e-3 relative with the filter off.
                    check(f'{pso}: {label}: gated pixels match the model', err.max() < 5e-3, max_rel=float(err.max()))
                    check(f'{pso}: {label}: unmagnified pixels bit-identical to off',
                          np.array_equal(on[u].view(np.uint32), off[u].view(np.uint32)))
                    stripes_before = np.abs(off[g] - want[g]).mean()
                    check(f'{pso}: {label}: stripes reduced', np.abs(on[g] - want[g]).mean() < .05 * stripes_before)
                for pso, base in (('generic', 'base_generic'), ('norecovery', 'base_norecovery')):
                    new = t._dispatch('FSRDOutputComp', constants(0), inputs, [10], (W, H), dirs[pso])[0]
                    old = t._dispatch('FSRDOutputComp', constants(0), inputs, [10], (W, H), dirs[base])[0]
                    check(f'{pso}: {label}: off is bit-identical to {BASE[:8]}',
                          np.array_equal(new.view(np.uint32), old.view(np.uint32)))
    print('streak filter: %d failures' % len(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
