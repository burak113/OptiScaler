"""GPU checks for FSRDAlbedoStabilise (albedo guide stabilisation after packing).

The pass replaces the packed albedo guides with a reprojected exponential average and rescales each lobe's
demodulated lighting so that lighting * guide is unchanged per channel. Checked here:
- a constant guide is returned bit-exactly, on static and on moving geometry, together with an exact signal;
- a flickering guide gets calmer while lighting * guide stays the same;
- depth/normal/motion mismatches and RESET restart from the current guide;
- the diffuse lobe passes through untouched when its flag is clear;
- the 3x3 clamp bounds the history;
- channels near the divisor floor keep their original pair.
"""
import os
for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_MAX_THREADS'):
    os.environ[k] = '2'
from pathlib import Path
import json
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as a

RESET, DIFFUSE, CLAMP = 1, 2, 4
N = 32
FLOOR = 0.008


def q8(x):
    return (np.rint(np.clip(x, 0, 1) * 255) / 255).astype(np.float32)


def same_level(x, y):
    return np.array_equal(np.rint(np.asarray(x) * 255), np.rint(np.asarray(y) * 255))


def frame(guide_s, guide_d, sig_s, sig_d, motion, depth, normal, prev, flags, rate=0.125, tol=0.03):
    n = guide_s.shape[0]
    zeros = np.zeros((n, n, 4), np.float32)
    hist_s, hist_d, hist_n = prev if prev is not None else (zeros, zeros, np.zeros((n, n, 2), np.float32))
    outputs = t._dispatch('FSRDAlbedoStabilise',
                          dict(DstTexSize=[n, n, 1 / n, 1 / n], Rate=rate, DivisorFloor=FLOOR, DepthTolerance=tol, Flags=flags),
                          [guide_s, guide_d, sig_s, sig_d, motion, depth, normal, hist_s, hist_d, hist_n],
                          [10, 10, 16, 28, 28, 10, 10], (n, n))
    return outputs


def rgba(rgb, alpha=1.0):
    out = np.empty(rgb.shape[:2] + (4,), np.float32); out[..., :3] = rgb; out[..., 3] = alpha
    return out


def static_inputs(n=N, z=-5.0):
    motion = np.zeros((n, n, 4), np.float32); motion[..., 3] = 1
    depth = np.full((n, n), z, np.float32)
    normal = np.zeros((n, n, 4), np.float32); normal[..., 0] = normal[..., 1] = .5
    return motion, depth, normal


def run_sequence(guides_s, guides_d, sigs_s, sigs_d, motion, depth, normal, flags, rate=0.125):
    prev = None; results = []
    for f in range(len(guides_s)):
        o = frame(guides_s[f], guides_d[f], sigs_s[f], sigs_d[f], motion, depth, normal, prev,
                  flags | (RESET if f == 0 else 0), rate)
        prev = (o[0], o[1], o[2]); results.append(o)
    return results


def main():
    out = Path(os.environ.get('FSRD_ALBEDO_STAB_TEST_OUTPUT', 'F:/FSRD/tmp/albedo_stab_tests'))
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(23)
    with a.GPUWorker(out / 'worker'):
        motion, depth, normal = static_inputs()
        texture = q8(rng.uniform(.05, .95, (N, N, 3)))
        light = rgba(rng.uniform(0, 4, (N, N, 3)).astype(np.float16).astype(np.float32), 7.0)

        # 1. constant guide, static geometry: bit-exact guides and signals
        seq = run_sequence([rgba(texture, .3)] * 6, [rgba(texture[::-1], .6)] * 6, [light] * 6, [light] * 6,
                           motion, depth, normal, DIFFUSE)
        last = seq[-1]
        t.check('constant guide returned exactly (specular)', same_level(last[3][..., :3], texture))
        t.check('constant guide returned exactly (diffuse)', same_level(last[4][..., :3], texture[::-1]))
        t.check('constant guide leaves signals exact', np.array_equal(last[5], light) and np.array_equal(last[6], light))
        t.check('guide alpha channels kept', np.allclose(last[3][..., 3], round(.3 * 255) / 255) and
                np.allclose(last[4][..., 3], round(.6 * 255) / 255))

        # 2. textured guide moving 2 px/frame right with exact motion vectors: no lag in the interior
        big = q8(rng.uniform(.05, .95, (N, N + 16, 3)))
        mv = motion.copy(); mv[..., 0] = -2.0 / N   # previous UV - current UV
        guides = [rgba(big[:, 16 - 2 * f:16 - 2 * f + N]) for f in range(6)]
        seq = run_sequence(guides, guides, [light] * 6, [light] * 6, mv, depth, normal, DIFFUSE)
        interior = (slice(None), slice(12, N))
        t.check('moving texture with exact motion: no lag',
                same_level(seq[-1][3][interior][..., :3], guides[-1][interior][..., :3]))

        # 3. flickering guide (4-frame cycle plus noise, CV ~0.35): calmer, energy per channel unchanged
        base = rng.uniform(.2, .6, (N, N, 3))
        cycle = rng.uniform(-.3, .3, (4, N, N, 1))
        frames = 32
        gs = [rgba(q8(base * (1 + cycle[f % 4] + rng.normal(0, .15, (N, N, 1))))) for f in range(frames)]
        energy = rng.uniform(.1, 2, (N, N, 3))
        sig = [rgba((energy / np.maximum(g[..., :3], FLOOR)).astype(np.float16).astype(np.float32)) for g in gs]
        seq = run_sequence(gs, gs, sig, sig, motion, depth, normal, DIFFUSE)
        g_in = np.stack([g[..., :3] for g in gs[16:]]); g_out = np.stack([o[3][..., :3] for o in seq[16:]])
        ratio = g_out.std(0).mean() / g_in.std(0).mean()
        t.check('flickering guide stabilised (temporal sd ratio %.3f < 0.4)' % ratio, ratio < .4)
        e_in = np.stack([s[..., :3] * g[..., :3] for s, g in zip(sig[16:], gs[16:])])
        e_out = np.stack([o[5][..., :3] * o[3][..., :3] for o in seq[16:]])
        rel = np.abs(e_out - e_in) / np.maximum(e_in, 1e-6)
        t.check('lighting * guide preserved (max rel %.2e)' % rel.max(), rel.max() < 2e-3)
        t.check('hit distance alpha kept', np.array_equal(seq[-1][5][..., 3], sig[-1][..., 3]))

        # 4. depth mismatch, normal mismatch, invalid motion and reset restart from the current guide
        prev = seq[-1][:3]
        cur = gs[0]
        for label, kw in [('depth mismatch', dict(depth=np.full((N, N), -5.5, np.float32))),
                          ('normal mismatch', dict(normal=np.dstack([np.full((N, N), .95), np.full((N, N), .5),
                                                                     np.zeros((N, N)), np.zeros((N, N))]).astype(np.float32))),
                          ('invalid motion', dict(motion=np.zeros((N, N, 4), np.float32))),
                          ('reset flag', dict(flags=RESET | DIFFUSE))]:
            args = dict(motion=motion, depth=depth, normal=normal, flags=DIFFUSE); args.update(kw)
            o = frame(cur, cur, sig[0], sig[0], args['motion'], args['depth'], args['normal'], prev, args['flags'])
            t.check(label + ' restarts from the current guide',
                    same_level(o[3][..., :3], cur[..., :3]) and np.array_equal(o[5], sig[0]))

        # 5. diffuse lobe untouched without its flag
        o = frame(gs[5], gs[6], sig[5], sig[6], motion, depth, normal, prev, 0)
        t.check('diffuse lobe passes through without the flag',
                same_level(o[4][..., :3], gs[6][..., :3]) and np.array_equal(o[6], sig[6]))
        t.check('specular lobe still stabilised without the diffuse flag', not same_level(o[3][..., :3], gs[5][..., :3]))

        # 6. 3x3 clamp bounds a stale history
        low = rgba(np.full((N, N, 3), .2, np.float32)); stale = np.zeros((N, N, 4), np.float32); stale[..., :3] = .9
        stale[..., 3] = depth
        hist_n = np.full((N, N, 2), .5, np.float32)
        o = frame(low, low, light, light, motion, depth, normal, (stale, stale, hist_n), CLAMP | DIFFUSE)
        t.check('clamped history stays within the current 3x3 range', same_level(o[3][..., :3], low[..., :3]))
        o = frame(low, low, light, light, motion, depth, normal, (stale, stale, hist_n), DIFFUSE)
        expected = q8(.9 + .125 * (.2 - .9))
        t.check('unclamped history follows the average', np.allclose(o[3][..., :3], expected, atol=1 / 255))

        # 7. channels at or below the divisor floor (0.008) keep their original pair
        tiny = rgba(np.full((N, N, 3), 2 / 255, np.float32))
        o = frame(tiny, tiny, light, light, motion, depth, normal, (stale, stale, hist_n), DIFFUSE)
        t.check('guide near the divisor floor keeps its original pair',
                same_level(o[3][..., :3], tiny[..., :3]) and np.array_equal(o[5], light))

    failures = sum(not x['passed'] for x in t.checks)
    (out / 'results.json').write_text(json.dumps(dict(checks=t.checks, failures=failures), indent=2))
    print('albedo stabilisation: %d checks, %d failures' % (len(t.checks), failures))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
