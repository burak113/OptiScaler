"""GPU checks for the complete five-pass fog-consistent guide chain.

Checked here:
- each pass matches the numpy reference (fsrd_fog_reference.py) on a scene with fog, a textured surface, water-like
  tiny guides, sky and motion, frame after frame with its own history fed back;
- an image that carries the guides' texture keeps kappa near 1 and its pair bit-exact;
- flat fog over textured guides drives kappa toward 0: near, the guides lose their texture but keep their level;
  far, the fog share moves to the specular lobe with a guide near 1;
- lighting x guide per channel equals the lobe radiance before the pass (energy exact);
- a diffuse guide at the divisor floor leaves that lobe alone;
- RESET and invalid motion restart the history, tiles without depth hold none, the debug flag writes kappa.
- the median rejects isolated guide-model failures, keeps extended fog, and respects surface depth.
"""
import os
for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_MAX_THREADS'):
    os.environ[k] = '2'
from pathlib import Path
import argparse
import json
import math
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as a
from fsrd_fog_reference import FogGuides, FLOOR, LUMA, P

RESET, DEBUG = 1, 1
W, H = 96, 72
TW, TH = (W + 7) // 8, (H + 7) // 8
FILL_SIGMA = P['fill_r'] / 1.5


def rgba(rgb, alpha=1.0):
    if rgb.shape[-1] == 4:
        return np.asarray(rgb, np.float32)
    out = np.empty(rgb.shape[:2] + (4,), np.float32); out[..., :3] = rgb; out[..., 3] = alpha
    return out


def q8(x):
    return np.rint(np.clip(x, 0, 1) * 255).astype(np.uint8)


def gpu_frame(orig, cur, depth, motion, hist, flags=0, route_flags=0, params=None, history_jitter_delta=(0.0, 0.0)):
    """orig/cur: RGB or RGBA pair; preserve captured hit distance and guide alpha. hist: tile A/B/C."""
    H, W = depth.shape
    TW, TH = (W + 7) // 8, (H + 7) // 8
    settings = dict(P); settings.update(params or {})
    fill_sigma = settings['fill_r'] / 1.5
    zeros = np.zeros((TH, TW, 4), np.float32)
    A0, B0, C0 = hist if hist is not None else (zeros, zeros, zeros)
    g = lambda x: rgba(x.astype(np.float32) / 255.0)
    sA, sB, sC, sG, sH = t._dispatch(
        'FSRDFogStats', dict(DstTexSize=[W, H, 1 / W, 1 / H], TileSize=[TW, TH], Rate=settings['rate'], DivisorFloor=FLOOR,
                             DepthTolerance=settings['reproj_dz'], Flags=flags | (RESET if hist is None else 0),
                             HistoryJitterDelta=list(history_jitter_delta)),
        [g(orig['qs8']), g(orig['qd8']), rgba(orig['U'], 3.0), rgba(orig['V']), g(cur['qs8']), g(cur['qd8']),
         depth, motion, A0, B0, C0], [2, 2, 2, 2, 2], (W, H), output_sizes=[(TW, TH)] * 5)
    kraw, = t._dispatch(
        'FSRDFogKappa', dict(TileSize=[TW, TH], Tau=settings['tau'], Z=settings['z'], TauFill=settings['tau_fill'], ZFill=settings['z_fill'],
                             MassLocal=settings['mass_local'], MassFill=64.0 * 2 * math.pi * fill_sigma ** 2, Sig0=settings['sig0'],
                             Sig1=settings['sig1'], FillSigma=fill_sigma, FillZSigma=settings['fill_zsig'], FillRadius=int(settings['fill_r'])),
        [sA, sB, sC], [41], (TW, TH))
    krank, = t._dispatch(
        'FSRDFogRank', dict(TileSize=[TW, TH], ZTolerance=settings['rank_dz'], Percentile=settings['rank_percentile'],
                            Radius=int(settings['rank_r'])), [kraw, sA, sC], [41], (TW, TH))
    ksm, = t._dispatch(
        'FSRDFogSmooth', dict(TileSize=[TW, TH], Sigma=settings['smooth_sigma'], ZSigma=settings['smooth_zsig'],
                              Radius=int(math.ceil(2 * settings['smooth_sigma']))), [krank, sA, sC], [41], (TW, TH))
    qs, qd, U2, V2 = t._dispatch(
        'FSRDFogRoute', dict(DstTexSize=[W, H, 1 / W, 1 / H], TileSize=[TW, TH], DivisorFloor=FLOOR,
                             LogNear=math.log(settings['near']), InvLogRange=1 / math.log(settings['far'] / settings['near']),
                             TargetZSigma=settings['target_zsig'], Flags=route_flags),
        [g(cur['qs8']), g(cur['qd8']), rgba(cur['U'], 3.0), rgba(cur['V']), depth, ksm, sG, sH], [28, 28, 10, 10], (W, H))
    return dict(A=sA, B=sB, C=sC, G=sG, H=sH, kraw=kraw, krank=krank, ksm=ksm, qs=qs, qd=qd, U=U2, V=V2)


def scene(rng, f, fog=1.0):
    """Left: textured surface whose image carries the guide texture (near). Middle: flat fog over textured
    guides (far). Right: sky. Bottom strip: water-like tiny guides. Light noise per frame."""
    yy, xx = np.mgrid[0:H, 0:W]
    tex = rng.uniform(.15, .85, (H, W, 3))
    qs = q8(.05 + .1 * tex); qd = q8(tex)
    depth = np.where(xx < 32, -6.0, np.where(xx < 72, -400.0, -16777.0)).astype(np.float32)
    qs[:, 72:] = q8(np.full((H, W - 72, 3), .97)); qd[:, 72:] = 0
    qd[56:, :72] = np.array([3, 2, 2], np.uint8); qs[56:, :72] = q8(np.full((H - 56, 72, 3), .04))  # one diffuse channel at the floor
    light = 1.0 + .05 * np.sin(xx / 9.0)[..., None]
    noise = lambda: 1 + .2 * np.random.default_rng(f * 7 + 1).standard_normal((H, W, 1))
    U = light * noise(); V = light * noise()
    fogmask = (xx >= 32) & (xx < 72)
    # fog: the radiance is flat, so the demodulated light is radiance / guide
    radiance = .3
    U = np.where(fogmask[..., None], fog * radiance / np.maximum(qs / 255.0, 1e-3) * noise() * .5, U)
    V = np.where(fogmask[..., None], fog * radiance / np.maximum(qd / 255.0, 1e-3) * noise() * .5, V)
    U[:, 72:] = .1 / .97
    V[:, 72:] = 0
    motion = np.zeros((H, W, 4), np.float32); motion[..., 3] = 1
    p = dict(qs8=qs, qd8=qd, U=U.astype(np.float16).astype(np.float32), V=V.astype(np.float16).astype(np.float32))
    return p, depth, motion


def radiance(p):
    qs, qd = p['qs8'].astype(np.float32) / 255, p['qd8'].astype(np.float32) / 255
    return np.where(qs > FLOOR, p['U'] * qs, 0) + np.where(qd > FLOOR, p['V'] * qd, 0)


def rank_checks(gpu=False):
    """Independent median properties protect small objects and extended fog at depth boundaries."""
    ref = FogGuides(W, H)
    z = np.zeros((TH, TW), np.float32)
    valid = np.ones((TH, TW), bool)

    def filtered(k, depth=z, mask=valid, **parameters):
        model = FogGuides(W, H, parameters)
        expected = model.rank(k, depth, mask)
        if not gpu:
            return expected
        A = np.zeros((TH, TW, 4), np.float32); A[..., 3] = mask
        C = np.zeros_like(A); C[..., 3] = depth
        actual, = t._dispatch('FSRDFogRank', dict(TileSize=[TW, TH], ZTolerance=model.p['rank_dz'],
            Percentile=model.p['rank_percentile'], Radius=int(model.p['rank_r'])), [k, A, C], [41], (TW, TH))
        t.check('rank GPU/reference parity ' + str(parameters), float(np.max(np.abs(actual - expected))) < 1e-6)
        return actual

    island = np.ones((TH, TW), np.float32); island[4, 5] = 0.0
    isolated = filtered(island)
    t.check('median removes an isolated low-kappa object-model failure', np.array_equal(isolated, np.ones_like(isolated)))
    fog = np.ones_like(island); fog[2:7, 3:10] = .125
    extended = filtered(fog)
    t.check('median keeps extended low-kappa fog', float(extended[4, 6]) == .125)
    split = np.ones_like(island); split[:, 6:] = .125
    zsplit = z.copy(); zsplit[:, 6:] = math.log(100.0)
    t.check('median does not mix different surface depths', np.array_equal(filtered(split, zsplit), split))
    nod = valid.copy(); nod[4, 5] = False; island[4, 5] = .375
    t.check('rank leaves a tile without geometry unchanged', float(filtered(island, mask=nod)[4, 5]) == .375)
    t.check('zero-radius rank is the identity', np.array_equal(filtered(fog, rank_r=0), fog))
    for percentile in (0.0, 25.0, 50.0, 100.0):
        ramp = np.linspace(0, 1, TW * TH, dtype=np.float32).reshape(TH, TW)
        result = filtered(ramp, rank_r=3, rank_percentile=percentile)
        t.check('rank output stays in its input range at percentile %g' % percentile,
                bool(np.all(np.isfinite(result)) and result.min() >= 0 and result.max() <= 1))


def route_range_checks(gpu=False):
    """A guide rewrite must never clip an otherwise finite, representable HDR source pair."""
    ref = FogGuides(W, H)
    for label, spec, diff, distance in (
            ('specular overflow', 65504.0, 2.0, 4.0),
            ('diffuse overflow', 2.0, 65504.0, 4.0),
            ('merged-lobe overflow', 65504.0, 65504.0, 400.0),
            ('negative finite overflow', -65504.0, 2.0, 4.0)):
        qs = np.full((H, W, 3), 32, np.uint8); qd = qs.copy()
        qs[32, 48] = qd[32, 48] = 255
        U = np.full((H, W, 3), 2.0, np.float32); V = U.copy()
        U[32, 48] = spec; V[32, 48] = diff
        pair = dict(qs8=qs, qd8=qd, U=U, V=V)
        depth = np.full((H, W), -distance, np.float32)
        G = np.zeros((TH, TW, 4), np.float32); Hm = G.copy()
        count = ref.tiles_count()[..., None]
        G[..., :3] = ref.tiles_sum(qs.astype(np.float32) / 255) / count
        Hm[..., :3] = ref.tiles_sum(qd.astype(np.float32) / 255) / count
        G[..., 3] = math.log(distance); Hm[..., 3] = 1
        kappa = np.full((TH, TW), .1, np.float32)
        if gpu:
            oqs, oqd, oU, oV = t._dispatch('FSRDFogRoute',
                dict(DstTexSize=[W,H,1/W,1/H], TileSize=[TW,TH], DivisorFloor=FLOOR,
                     LogNear=math.log(P['near']), InvLogRange=1/math.log(P['far']/P['near']),
                     TargetZSigma=P['target_zsig'], Flags=0),
                [rgba(qs.astype(np.float32)/255, .25), rgba(qd.astype(np.float32)/255, .75),
                 rgba(U, 7.0), rgba(V, 11.0), depth, kappa, G, Hm], [28,28,10,10], (W,H))
            actual = dict(qs8=np.rint(oqs[..., :3]*255).astype(np.uint8),
                          qd8=np.rint(oqd[..., :3]*255).astype(np.uint8), U=oU[..., :3], V=oV[..., :3])
            t.check(label + ': hit-distance alpha remains exact',
                    bool(np.all(oU[..., 3] == 7.0) and np.all(oV[..., 3] == 11.0)))
        else:
            oqs, oqd, oU, oV = ref.route(pair, ref.upsample(kappa), depth, G, Hm)
            actual = dict(qs8=oqs, qd8=oqd, U=oU, V=oV)
        px = (32,48)
        exact = all(np.array_equal(actual[key][px], pair[key][px]) for key in pair)
        relative = float(np.max(np.abs(radiance(actual)[px] - radiance(pair)[px]) / np.maximum(np.abs(radiance(pair)[px]), .001)))
        t.check(label + ': an unrepresentable rewrite keeps the original pair bit-exact', exact)
        t.check(label + ': original HDR energy preserved', relative < 1e-6, relative_error=relative)


def jitter_checks(gpu=False):
    """Known history tags cross an 8-pixel tile edge only after Jprev-Jcur is applied.

    Both the lighting EMA and the sufficient-statistic/age load must address the same tile.
    Expectations are independent tags, rather than GPU/reference agreement alone.
    """
    yy, xx = np.mgrid[:TH, :TW]
    tags = (1.0 + xx + 2.0 * yy).astype(np.float32)
    A = np.empty((TH, TW, 4), np.float32); B = np.empty_like(A); C = np.empty_like(A)
    A[..., :3] = tags[..., None]; A[..., 3] = 2.0 + xx * .5 + yy * .25
    B[..., :3] = (2.0 * tags)[..., None]; B[..., 3] = 3.0 * tags
    C[..., :3] = np.stack((tags, 2.0 * tags, 4.0 * tags), -1); C[..., 3] = math.log(100.0)
    q = np.full((H, W, 3), 128 / 255.0, np.float32)
    U = np.full_like(q, 2.0); V = np.full_like(q, 4.0)
    pair = dict(qs=q, qd=q, U=U, V=V)
    depth = np.full((H, W), -100.0, np.float32)
    cases = (
        ('positive X jitter', (3.2, 0.0), (.75, 0.0), (0, 1), False, True),
        ('negative X jitter', (4.0, 0.0), (-.75, 0.0), (0, 0), False, True),
        ('positive Y jitter', (0.0, 3.2), (0.0, .75), (1, 0), False, True),
        ('negative Y jitter', (0.0, 4.0), (0.0, -.75), (0, 0), False, True),
        ('diagonal jitter', (3.2, 3.2), (.75, .75), (1, 1), False, True),
        ('zero jitter keeps motion address', (4.0, 4.0), (0.0, 0.0), (1, 1), False, True),
        ('reset ignores jittered history', (3.2, 0.0), (.75, 0.0), None, True, True),
        ('invalid motion ignores jittered history', (3.2, 0.0), (.75, 0.0), None, False, False),
        ('offscreen jitter rejects history', (-4.0, 0.0), (-.75, 0.0), None, False, True),
    )
    for label, displacement, jitter, previous_tile, reset, valid in cases:
        motion = np.zeros((H, W, 4), np.float32)
        motion[..., 0] = displacement[0] / W; motion[..., 1] = displacement[1] / H; motion[..., 3] = valid
        # Motion uses the production FP16 input format.
        motion = motion.astype(np.float16).astype(np.float32)
        model = FogGuides(W, H); model.hist = (A, B, C)
        expected = model.stats(pair, pair, depth, motion, reset, jitter)
        if gpu:
            actual = t._dispatch('FSRDFogStats',
                dict(DstTexSize=[W,H,1/W,1/H], TileSize=[TW,TH], Rate=P['rate'], DivisorFloor=FLOOR,
                     DepthTolerance=P['reproj_dz'], Flags=RESET if reset else 0, HistoryJitterDelta=list(jitter)),
                [rgba(q), rgba(q), rgba(U, 3), rgba(V), rgba(q), rgba(q), depth, motion, A, B, C],
                [2,2,2,2,2], (W,H), output_sizes=[(TW,TH)] * 5)
            t.check(label + ': stats GPU/reference parity',
                    all(np.allclose(x, y, rtol=2e-5, atol=2e-5) for x,y in zip(actual, expected)))
        else:
            actual = expected
        ra, rb, rc = (x[0,0] for x in actual[:3])
        r = P['rate']; cbar = float((6.0 * q[0,0]) @ LUMA)
        if previous_tile is not None:
            py, px = previous_tile
            ls = A[py,px,:3] + r * (2.0 - A[py,px,:3])
            ld = B[py,px,:3] + r * (4.0 - B[py,px,:3])
            cb = B[py,px,3] + r * (cbar - B[py,px,3])
            age = min(A[py,px,3] + 1, 1/r); sums = C[py,px,:3] * (1-r)
        else:
            ls, ld, cb, age, sums = [2.0]*3, [4.0]*3, cbar, 1.0, [0.0]*3
        t.check(label + ': lighting loads the expected previous tile',
                np.allclose(ra[:3], ls, atol=2e-5) and np.allclose(rb[:3], ld, atol=2e-5) and np.isclose(rb[3], cb, atol=2e-5))
        t.check(label + ': age and sufficient statistics load the same tile',
                float(ra[3]) == age and np.allclose(rc[:3], sums, atol=2e-5))


def main(reference_only=False, route_range_only=False, jitter_only=False):
    out = Path(os.environ.get('FSRD_FOG_TEST_OUTPUT', str(t.ROOT / 'tools_tmp/fog_guides_tests')))
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(31)
    if reference_only:
        rank_checks()
        route_range_checks()
        jitter_checks()
        failures = sum(not x['passed'] for x in t.checks)
        (out / 'reference_results.json').write_text(json.dumps(dict(checks=t.checks, failures=failures), indent=2, default=str))
        print('fog reference: %d checks, %d failures' % (len(t.checks), failures))
        return bool(failures)
    with a.GPUWorker(out / 'worker'):
        if jitter_only:
            jitter_checks(gpu=True)
            failures = sum(not x['passed'] for x in t.checks)
            (out / 'jitter_results.json').write_text(json.dumps(dict(checks=t.checks, failures=failures), indent=2, default=str))
            print('fog jitter: %d checks, %d failures' % (len(t.checks), failures))
            return bool(failures)
        route_range_checks(gpu=True)
        if route_range_only:
            failures = sum(not x['passed'] for x in t.checks)
            (out / 'route_range_results.json').write_text(json.dumps(dict(checks=t.checks, failures=failures), indent=2, default=str))
            return bool(failures)
        rank_checks(gpu=True)
        jitter_checks(gpu=True)
        # 1. GPU vs reference, frame by frame with fed-back history
        ref = FogGuides(W, H); hist = None; worst = dict(stats=0.0, kraw=0.0, krank=0.0, ksm=0.0, level=0.0, light=0.0, energy=0.0)
        for f in range(12):
            p, depth, motion = scene(np.random.default_rng(5), f)
            if f >= 6:
                motion[..., 0] = 1.0 / W   # one pixel to the right per frame on the second half
            (rqs, rqd, rU, rV), rk = ref.frame(p, p, depth, motion, f == 0)
            A, B, Cst = ref.hist
            g = gpu_frame(p, p, depth, motion, hist)
            hist = (g['A'], g['B'], g['C'])
            rel = lambda x, y: float(np.max(np.abs(x - y) / np.maximum(np.abs(y), 1e-3)))
            worst['stats'] = max(worst['stats'], rel(g['A'][..., :3], A[..., :3]), rel(g['B'], B), rel(g['C'][..., :2], Cst[..., :2]))
            kr = ref.kappa(A, B, Cst); km = ref.rank(kr, Cst[..., 3], A[..., 3] > 0)
            ks = ref.smooth(km, Cst[..., 3], A[..., 3] > 0)
            worst['kraw'] = max(worst['kraw'], float(np.abs(g['kraw'] - kr).max()))
            worst['krank'] = max(worst['krank'], float(np.abs(g['krank'] - km).max()))
            worst['ksm'] = max(worst['ksm'], float(np.abs(g['ksm'] - ks).max()))
            lv = np.rint(g['qs'][..., :3] * 255) != rqs
            worst['level'] = max(worst['level'], float(lv.mean()))
            same = ~lv
            worst['light'] = max(worst['light'], float(np.percentile(np.abs(g['U'][..., :3] - rU)[same] / np.maximum(np.abs(rU[same]), 1e-2), 99.9)))
            gp = dict(qs8=np.rint(g['qs'][..., :3] * 255).astype(np.uint8), qd8=np.rint(g['qd'][..., :3] * 255).astype(np.uint8),
                      U=g['U'][..., :3], V=g['V'][..., :3])
            e0, e1 = radiance(p), radiance(gp)
            worst['energy'] = max(worst['energy'], float(np.percentile(np.abs(e1 - e0) / np.maximum(np.abs(e0), 1e-2), 99.9)))
        t.check('tile statistics match the reference (rel < 2e-3)', worst['stats'] < 2e-3, detail=worst)
        t.check('all three kappa passes match the reference (< 2e-3)',
                max(worst['kraw'], worst['krank'], worst['ksm']) < 2e-3, detail=worst)
        t.check('routed guide levels match the reference (> 99.5%)', worst['level'] < 5e-3, detail=worst)
        t.check('routed lighting matches the reference (< 2e-3)', worst['light'] < 2e-3, detail=worst)
        t.check('lighting x guide preserved per channel (< 2e-3)', worst['energy'] < 2e-3, detail=worst)

        # 2. fog: far kappa goes to ~0, the specular guide moves toward 1 and the diffuse lobe empties
        far = (slice(8, 48), slice(40, 64))
        t.check('kappa in flat fog falls below 0.2', float(np.median(g['ksm'][1:6, 5:8])) < .2, detail=float(np.median(g['ksm'][1:6, 5:8])))
        t.check('far fog: specular guide near 1', float(np.median(g['qs'][far][..., :3])) > .85, detail=float(np.median(g['qs'][far][..., :3])))
        kept_d = float(np.median(radiance(dict(qs8=np.zeros_like(p['qs8']), qd8=np.rint(g['qd'][..., :3] * 255).astype(np.uint8), U=g['U'][..., :3], V=g['V'][..., :3]))[far] /
                                 np.maximum(radiance(dict(qs8=np.zeros_like(p['qs8']), qd8=p['qd8'], U=p['U'], V=p['V']))[far], 1e-6)))
        t.check('far fog: the diffuse lobe keeps only about kappa of its light', kept_d < .3, detail=kept_d)

        # 3. a textured surface whose image carries the texture: pair unchanged
        near = (slice(8, 48), slice(4, 24))
        kept = float(np.mean(np.rint(g['qs'][near][..., :3] * 255) == p['qs8'][near]))
        t.check('textured surface keeps its specular guide (> 95%)', kept > .95, detail=kept)
        t.check('textured surface kappa above 0.8', float(np.median(g['ksm'][1:6, 0:3])) > .8, detail=float(np.median(g['ksm'][1:6, 0:3])))

        # 4. near fog keeps the guide level (no move): same scene with the fog band at near depth
        p2, depth2, motion2 = scene(np.random.default_rng(5), 0)
        depth2[:] = np.where(np.arange(W)[None, :] < 72, -4.0, -16777.0)
        hist2 = None
        for f in range(18):
            p2, _, _ = scene(np.random.default_rng(5), f)
            g2 = gpu_frame(p2, p2, depth2, motion2, hist2); hist2 = (g2['A'], g2['B'], g2['C'])
        fogn = (slice(8, 48), slice(40, 64))
        lvl_in = float(np.mean(p2['qd8'][fogn] / 255.0)); lvl_out = float(np.mean(g2['qd'][fogn][..., :3]))
        t.check('near fog: diffuse guide level kept (mean within 5%)', abs(lvl_out / lvl_in - 1) < .05, detail=(lvl_in, lvl_out))
        tex_in = float(np.std(p2['qd8'][fogn] / 255.0)); tex_out = float(np.std(g2['qd'][fogn][..., :3]))
        kn = float(np.median(g2['ksm'][1:6, 4:9]))
        t.check('near fog: diffuse guide texture scaled by about kappa', tex_out < (kn + .15) * tex_in and kn < .5, detail=(tex_in, tex_out, kn))

        # 5. water-like diffuse guide at the floor: diffuse lobe untouched
        water = (slice(58, 70), slice(4, 68))
        t.check('diffuse guide at the floor keeps its pair', np.array_equal(np.rint(g['qd'][water][..., :3] * 255), p['qd8'][water]) and
                np.allclose(g['V'][water][..., :3], p['V'][water], rtol=1e-3, atol=1e-6))

        # 6. history: reset restarts, invalid motion restarts, tiles without depth hold none
        t.check('history age grows to the cap on static frames', float(g2['A'][..., 3].max()) == 1 / P['rate'], detail=float(g2['A'][..., 3].max()))
        g3 = gpu_frame(p2, p2, depth2, motion2, hist2, flags=RESET)
        t.check('RESET restarts every tile', float(g3['A'][..., 3].max()) <= 1.0)
        m4 = motion2.copy(); m4[..., 3] = 0
        g4 = gpu_frame(p2, p2, depth2, m4, hist2)
        t.check('invalid motion restarts the tile', float(g4['A'][..., 3].max()) <= 1.0)
        d5 = depth2.copy(); d5[:16, :16] = 0
        g5 = gpu_frame(p2, p2, d5, motion2, hist2)
        t.check('tile without depth holds no history and kappa 1', float(g5['A'][0:2, 0:2, 3].max()) == 0 and float(g5['kraw'][0:2, 0:2].min()) == 1.0)

        # 7. debug flag writes kappa into the specular guide's alpha and rewrites nothing
        g6 = gpu_frame(p, p, depth, motion, hist, route_flags=DEBUG)
        t.check('debug flag: kappa in specular alpha, pair unchanged',
                np.array_equal(np.rint(g6['qs'][..., :3] * 255), p['qs8']) and np.allclose(g6['U'][..., :3], p['U'], rtol=1e-3, atol=1e-6)
                and float(g6['qs'][..., 3].min()) < .5)

        # Native replay carries the real hit distance in signal alpha and roughness in guide alpha.
        captured = {k: rgba(v.astype(np.float32) if k in ('U', 'V') else v).copy() for k, v in p.items()}
        yy, xx = np.mgrid[:H, :W]
        captured['U'][..., 3] = ((xx + 1) / 8).astype(np.float16).astype(np.float32)
        captured['V'][..., 3] = ((yy + 1) / 16).astype(np.float16).astype(np.float32)
        for k in ('qs8', 'qd8'):
            captured[k] = captured[k].astype(np.uint8)
            captured[k][..., 3] = (xx + yy) % 256
        g7 = gpu_frame(captured, captured, depth, motion, hist)
        t.check('route preserves captured signal hit-distance alpha exactly',
                np.array_equal(g7['U'][..., 3], captured['U'][..., 3]) and
                np.array_equal(g7['V'][..., 3], captured['V'][..., 3]))
        t.check('route preserves captured guide alpha exactly',
                np.array_equal(np.rint(g7['qs'][..., 3] * 255), captured['qs8'][..., 3]) and
                np.array_equal(np.rint(g7['qd'][..., 3] * 255), captured['qd8'][..., 3]))

    failures = sum(not x['passed'] for x in t.checks)
    (out / 'results.json').write_text(json.dumps(dict(checks=t.checks, failures=failures), indent=2, default=str))
    print('fog guides: %d checks, %d failures' % (len(t.checks), failures))
    return bool(failures)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-only', action='store_true', help='check median properties without compiling or using the GPU')
    parser.add_argument('--route-range-only', action='store_true', help='exercise HDR range on the production GPU Route pass')
    parser.add_argument('--jitter-only', action='store_true', help='check pixel jitter and motion across previous tile boundaries')
    args = parser.parse_args()
    raise SystemExit(main(args.reference_only, args.route_range_only, args.jitter_only))
