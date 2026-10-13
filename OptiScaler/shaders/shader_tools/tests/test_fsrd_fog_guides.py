"""GPU checks for the complete six-pass lighting-consistent guide chain.

Checked here:
- each pass matches the numpy reference (fsrd_fog_reference.py) on a scene with fog, a textured surface, water-like
  tiny guides, sky and motion, frame after frame with its own history (tiles and per-pixel guides) fed back;
- an image that carries the guides' texture keeps kappa near 1 and its pair bit-exact;
- flat fog over textured guides drives kappa toward 0: near, the guides lose their texture but keep their level;
  far, the fog share moves to the specular lobe, whose guide takes the surface's own flattened total level;
- water: guides that flicker together with the image inside each frame but carry a static print the image does
  not show (a sea floor) get kappa near 0, and the print leaves the guide although the floor's depth steps;
- the per-pixel guide history is an EMA along the motion, restarted by RESET and by a depth change;
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
from fsrd_fog_reference import FogGuides, FLOOR, LUMA, P, LOGZ_MIN, INV_LOGZ_RANGE
import fsrd_fog_reference as fogref

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


def stats_constants(W, H, settings, flags, history_jitter_delta):
    TW, TH = (W + 7) // 8, (H + 7) // 8
    return dict(DstTexSize=[W, H, 1 / W, 1 / H], TileSize=[TW, TH], Rate=settings['rate'], DivisorFloor=FLOOR,
                DepthTolerance=settings['reproj_dz'], Flags=flags, HistoryJitterDelta=list(history_jitter_delta),
                GuideRate=settings['guide_rate'], GuideDepthTolerance=math.log1p(settings['guide_dz']) * INV_LOGZ_RANGE, LogZMin=LOGZ_MIN,
                InvLogZRange=INV_LOGZ_RANGE)


def gpu_frame(orig, cur, depth, motion, hist, flags=0, route_flags=0, params=None, history_jitter_delta=(0.0, 0.0)):
    """orig/cur: RGB or RGBA pair; preserve captured hit distance and guide alpha. hist: tile A/B/C, pixel guides."""
    H, W = depth.shape
    TW, TH = (W + 7) // 8, (H + 7) // 8
    settings = dict(P); settings.update(params or {})
    fill_sigma = settings['fill_r'] / 1.5
    zeros = np.zeros((TH, TW, 4), np.float32)
    A0, B0, C0, G0 = hist if hist is not None else (zeros, zeros, zeros, np.zeros((H, W, 4), np.float32))
    g = lambda x: rgba(x.astype(np.float32) / 255.0)
    sA, sB, sC, sG, sH, sGuides = t._dispatch(
        'FSRDFogStats', stats_constants(W, H, settings, flags | (RESET if hist is None else 0), history_jitter_delta),
        [g(orig['qs8']), g(orig['qd8']), rgba(orig['U'], 3.0), rgba(orig['V']), g(cur['qs8']), g(cur['qd8']),
         depth, motion, A0, B0, C0, G0], [2, 2, 2, 2, 2, 24], (W, H), output_sizes=[(TW, TH)] * 5 + [(W, H)])
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
    tS, tD = t._dispatch(
        'FSRDFogTarget', dict(TileSize=[TW, TH], Sigma=settings['target_sigma'], ZSigma=settings['target_zsig'],
                              Radius=int(math.ceil(2 * settings['target_sigma']))), [ksm, sG, sH], [10, 10], (TW, TH))
    qs, qd, U2, V2 = t._dispatch(
        'FSRDFogRoute', dict(DstTexSize=[W, H, 1 / W, 1 / H], TileSize=[TW, TH], DivisorFloor=FLOOR,
                             LogNear=math.log(settings['near']), InvLogRange=1 / math.log(settings['far'] / settings['near']),
                             Flags=route_flags),
        [g(cur['qs8']), g(cur['qd8']), rgba(cur['U'], 3.0), rgba(cur['V']), depth, ksm, tS, tD, sGuides], [28, 28, 10, 10], (W, H))
    return dict(A=sA, B=sB, C=sC, G=sG, H=sH, GH=sGuides, kraw=kraw, krank=krank, ksm=ksm, tS=tS, tD=tD,
                qs=qs, qd=qd, U=U2, V=V2, hist=(sA, sB, sC, sGuides))


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
        Ts, Td = ref.target(kappa, G, Hm)
        if gpu:
            oqs, oqd, oU, oV = t._dispatch('FSRDFogRoute',
                dict(DstTexSize=[W,H,1/W,1/H], TileSize=[TW,TH], DivisorFloor=FLOOR,
                     LogNear=math.log(P['near']), InvLogRange=1/math.log(P['far']/P['near']), Flags=0),
                [rgba(qs.astype(np.float32)/255, .25), rgba(qd.astype(np.float32)/255, .75),
                 rgba(U, 7.0), rgba(V, 11.0), depth, kappa, rgba(Ts), rgba(Td), np.zeros((H, W, 4), np.float32)],
                [28,28,10,10], (W,H))
            actual = dict(qs8=np.rint(oqs[..., :3]*255).astype(np.uint8),
                          qd8=np.rint(oqd[..., :3]*255).astype(np.uint8), U=oU[..., :3], V=oV[..., :3])
            t.check(label + ': hit-distance alpha remains exact',
                    bool(np.all(oU[..., 3] == 7.0) and np.all(oV[..., 3] == 11.0)))
        else:
            oqs, oqd, oU, oV = ref.route(pair, ref.upsample(kappa), depth, ref.upsample(Ts), ref.upsample(Td))
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
            actual = t._dispatch('FSRDFogStats', stats_constants(W, H, P, RESET if reset else 0, jitter),
                [rgba(q), rgba(q), rgba(U, 3), rgba(V), rgba(q), rgba(q), depth, motion, A, B, C,
                 np.zeros((H, W, 4), np.float32)],
                [2,2,2,2,2,24], (W,H), output_sizes=[(TW,TH)] * 5 + [(W,H)])
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


def water_scene(f, depth_step=True):
    """Left 64 columns: water over a sea floor. The floor's print (a bright band, rows 24-48) is in both guides and,
    with a 30% shallower floor under it, in depth; the image does not show it. Every pixel's guide and image flicker
    together per frame (the image by twice the guide's relative change). Right: a textured surface the image shows."""
    yy, xx = np.mgrid[0:H, 0:W]
    rng = np.random.default_rng(1000 + f)
    band = (yy >= 24) & (yy < 48)
    flick = 1 + .12 * rng.standard_normal((H, W))
    base_s = np.where(band, .30, .10); base_d = np.where(band, .036, .012)
    tex = np.random.default_rng(77).uniform(.2, .8, (H, W))
    qs = np.where(xx < 64, base_s * flick, .05 + .1 * tex); qd = np.where(xx < 64, base_d * flick, tex)
    qs8 = q8(np.repeat(qs[..., None], 3, -1)); qd8 = q8(np.repeat(qd[..., None], 3, -1))
    radiance = np.where(xx < 64, .2 * (1 + 2 * (flick - 1)), .5 * (qs + qd)) * (1 + .1 * rng.standard_normal((H, W)))
    share = qs / (qs + qd)
    U = np.repeat((radiance * share / np.maximum(qs8[..., 0] / 255.0, 1e-3))[..., None], 3, -1)
    V = np.repeat((radiance * (1 - share) / np.maximum(qd8[..., 0] / 255.0, 1e-3))[..., None], 3, -1)
    depth = np.where(xx < 64, -300.0 * np.where(band & depth_step, .74, 1.0), -6.0).astype(np.float32)
    motion = np.zeros((H, W, 4), np.float32); motion[..., 3] = 1
    p = dict(qs8=qs8, qd8=qd8, U=U.astype(np.float16).astype(np.float32), V=V.astype(np.float16).astype(np.float32))
    return p, depth, motion


def water_checks(hist_frames=24):
    hist = None; same = None
    for f in range(hist_frames):
        p, depth, motion = water_scene(f)
        g = gpu_frame(p, p, depth, motion, hist); hist = g['hist']
    k_water = float(np.median(g['ksm'][1:8, 1:7])); k_tex = float(np.median(g['ksm'][1:8, 9:11]))
    t.check('water: kappa near 0 although guides and image flicker together', k_water < .3, detail=k_water)
    t.check('water: the textured surface beside it keeps kappa near 1', k_tex > .8, detail=k_tex)
    qs = g['qs'][..., 0]
    inside = float(np.mean(qs[30:42, 8:56])); outside = float(np.mean(np.r_[qs[6:18, 8:56], qs[54:66, 8:56]]))
    t.check('water: the sea-floor print leaves the guide although the floor depth steps (< 25% of 3x)',
            inside / outside < 1 + .25 * 2, detail=(inside, outside))
    for f in range(hist_frames, hist_frames + 2):
        p, depth, motion = water_scene(f)
        g = gpu_frame(p, p, depth, motion, hist); hist = g['hist']
        gp = dict(qs8=np.rint(g['qs'][..., :3] * 255).astype(np.uint8), qd8=np.rint(g['qd'][..., :3] * 255).astype(np.uint8),
                  U=g['U'][..., :3], V=g['V'][..., :3])
        e0, e1 = radiance(p), radiance(gp)
        same = max(same or 0.0, float(np.percentile(np.abs(e1 - e0) / np.maximum(np.abs(e0), 1e-2), 99.9)))
    t.check('water: lighting x guide preserved per channel (< 2e-3)', same < 2e-3, detail=same)


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
        ref = FogGuides(W, H); hist = None
        worst = dict(stats=0.0, guides=0.0, kraw=0.0, krank=0.0, ksm=0.0, target=0.0, level=0.0, level_max=0.0, light=0.0,
                     energy=0.0)
        for f in range(12):
            p, depth, motion = scene(np.random.default_rng(5), f)
            if f >= 6:
                # the content moves one pixel to the left per frame on the second half, and the motion says so
                motion[..., 0] = 1.0 / W
                p = {k: np.roll(v, 5 - f, axis=1) for k, v in p.items()}; depth = np.roll(depth, 5 - f, axis=1)
            if hist is not None:
                ref.ghist = hist[3].astype(np.float64)   # one step from the same stored history (UNORM10 readback)
            (rqs, rqd, rU, rV), rk = ref.frame(p, p, depth, motion, f == 0)
            A, B, Cst = ref.hist
            g = gpu_frame(p, p, depth, motion, hist)
            hist = g['hist']
            rel = lambda x, y: float(np.max(np.abs(x - y) / np.maximum(np.abs(y), 1e-3)))
            worst['stats'] = max(worst['stats'], rel(g['A'][..., :3], A[..., :3]), rel(g['B'], B), rel(g['C'][..., :2], Cst[..., :2]))
            # stored UNORM10 levels: an exact tie may round the other way in float32
            worst['guides'] = max(worst['guides'], float(np.mean(np.abs(g['GH'][..., :3] - ref.ghist[..., :3]) > .6 / 1023)))
            kr = ref.kappa(A, B, Cst); km = ref.rank(kr, Cst[..., 3], A[..., 3] > 0)
            ks = ref.smooth(km, Cst[..., 3], A[..., 3] > 0)
            Gr = np.concatenate([ref.tiles_sum(p['qs8'] / 255.0) / ref.tiles_count()[..., None], Cst[..., 3:4]], -1)
            Hr = np.concatenate([ref.tiles_sum(p['qd8'] / 255.0) / ref.tiles_count()[..., None], g['H'][..., 3:4]], -1)
            rTs, rTd = ref.target(g['ksm'], Gr, Hr)
            worst['target'] = max(worst['target'], rel(g['tS'][..., :3], rTs), rel(g['tD'][..., :3], rTd))
            worst['kraw'] = max(worst['kraw'], float(np.abs(g['kraw'] - kr).max()))
            worst['krank'] = max(worst['krank'], float(np.abs(g['krank'] - km).max()))
            worst['ksm'] = max(worst['ksm'], float(np.abs(g['ksm'] - ks).max()))
            lv = np.rint(g['qs'][..., :3] * 255) != rqs
            worst['level'] = max(worst['level'], float(lv.mean()))
            worst['level_max'] = max(worst['level_max'], float(np.abs(np.rint(g['qs'][..., :3] * 255) - rqs).max()))
            same = ~lv
            worst['light'] = max(worst['light'], float(np.percentile(np.abs(g['U'][..., :3] - rU)[same] / np.maximum(np.abs(rU[same]), 1e-2), 99.9)))
            gp = dict(qs8=np.rint(g['qs'][..., :3] * 255).astype(np.uint8), qd8=np.rint(g['qd'][..., :3] * 255).astype(np.uint8),
                      U=g['U'][..., :3], V=g['V'][..., :3])
            e0, e1 = radiance(p), radiance(gp)
            worst['energy'] = max(worst['energy'], float(np.percentile(np.abs(e1 - e0) / np.maximum(np.abs(e0), 1e-2), 99.9)))
        # the regressor sums cancel (high-passed products); float32 against float64 leaves a few 1e-3
        t.check('tile statistics match the reference (rel < 5e-3)', worst['stats'] < 5e-3, detail=worst)
        t.check('per-pixel guide history matches the reference (> 99.9% of levels)', worst['guides'] < 1e-3, detail=worst)
        t.check('all three kappa passes match the reference (< 2e-3)',
                max(worst['kraw'], worst['krank'], worst['ksm']) < 2e-3, detail=worst)
        t.check('flatten targets match the reference (rel < 2e-3)', worst['target'] < 2e-3, detail=worst)
        # most pixels are rewritten now (kappa below 1 over fog); a 1e-3 kappa difference flips a rounding
        t.check('routed guide levels match the reference (> 95%, never more than one level)',
                worst['level'] < .05 and worst['level_max'] <= 1, detail=worst)
        t.check('routed lighting matches the reference (< 2e-3)', worst['light'] < 2e-3, detail=worst)
        t.check('lighting x guide preserved per channel (< 2e-3)', worst['energy'] < 2e-3, detail=worst)

        # 2. fog: far kappa goes to ~0, the diffuse lobe empties into the specular lobe, whose guide takes the
        #    surface's own flattened total level (not a sky-like 1, which made RR's specular path brighten)
        far = (slice(8, 48), slice(40, 64))
        t.check('kappa in flat fog falls below 0.2', float(np.median(g['ksm'][1:6, 5:8])) < .2, detail=float(np.median(g['ksm'][1:6, 5:8])))
        level = float(np.median(g['qs'][far][..., :3])); own = float(np.median((g['tS'] + g['tD'])[1:6, 5:8, :3]))
        t.check('far fog: specular guide at the surface\'s flattened total level', abs(level / own - 1) < .1 and level < .85,
                detail=(level, own))
        kept_d = float(np.median(radiance(dict(qs8=np.zeros_like(p['qs8']), qd8=np.rint(g['qd'][..., :3] * 255).astype(np.uint8), U=g['U'][..., :3], V=g['V'][..., :3]))[far] /
                                 np.maximum(radiance(dict(qs8=np.zeros_like(p['qs8']), qd8=p['qd8'], U=p['U'], V=p['V']))[far], 1e-6)))
        t.check('far fog: the diffuse lobe keeps only about kappa of its light', kept_d < .3, detail=kept_d)

        # 3. a textured surface whose image carries the texture: pair unchanged
        near = (slice(8, 48), slice(2, 14))   # the content moved six pixels to the left
        kept = float(np.mean(np.rint(g['qs'][near][..., :3] * 255) == p['qs8'][near]))
        t.check('textured surface keeps its specular guide (> 95%)', kept > .95, detail=kept)
        t.check('textured surface kappa above 0.8', float(np.median(g['ksm'][1:6, 0:2])) > .8, detail=float(np.median(g['ksm'][1:6, 0:2])))

        # 4. near fog keeps the guide level (no move): same scene with the fog band at near depth
        p2, depth2, motion2 = scene(np.random.default_rng(5), 0)
        depth2[:] = np.where(np.arange(W)[None, :] < 72, -4.0, -16777.0)
        hist2 = None
        for f in range(18):
            p2, _, _ = scene(np.random.default_rng(5), f)
            g2 = gpu_frame(p2, p2, depth2, motion2, hist2); hist2 = g2['hist']
        fogn = (slice(8, 48), slice(40, 64))
        lvl_in = float(np.mean(p2['qd8'][fogn] / 255.0)); lvl_out = float(np.mean(g2['qd'][fogn][..., :3]))
        # the flatten target averages the surfaces around whose texture the image does not show either (here also
        # the dark strip below at the same depth), so the level moves a little; the light stays in its lobe
        t.check('near fog: diffuse guide level kept (mean within 15%)', abs(lvl_out / lvl_in - 1) < .15, detail=(lvl_in, lvl_out))
        kept_n = float(np.median(radiance(dict(qs8=np.zeros_like(p2['qs8']), qd8=np.rint(g2['qd'][..., :3] * 255).astype(np.uint8), U=g2['U'][..., :3], V=g2['V'][..., :3]))[fogn] /
                                 np.maximum(radiance(dict(qs8=np.zeros_like(p2['qs8']), qd8=p2['qd8'], U=p2['U'], V=p2['V']))[fogn], 1e-6)))
        t.check('near fog: the diffuse lobe keeps its light (no move)', abs(kept_n - 1) < 2e-3, detail=kept_n)
        tex_in = float(np.std(p2['qd8'][fogn] / 255.0)); tex_out = float(np.std(g2['qd'][fogn][..., :3]))
        kn = float(np.median(g2['ksm'][1:6, 4:9]))
        t.check('near fog: diffuse guide texture scaled by about kappa', tex_out < (kn + .15) * tex_in and kn < .5, detail=(tex_in, tex_out, kn))

        # 5. water-like diffuse guide at the floor: one decision for the whole strip (the flattened guide decides,
        #    not the frame's per-pixel sample), and lighting x guide preserved
        water = (slice(58, 70), slice(4, 68))
        # (the strip lies under the textured surface, kappa ~1, and under the fog band, kappa ~0: one decision each)
        for label, cols in (('under the texture', slice(2, 12)), ('under the fog', slice(44, 62))):   # content moved 6 px left
            part = (slice(58, 70), cols)
            untouched = np.all(np.rint(g['qd'][part][..., :3] * 255) == p['qd8'][part], -1)
            same = float(max(untouched.mean(), 1 - untouched.mean()))
            t.check('diffuse guide at the floor %s: one lobe decision (> 95%%)' % label, same > .95, detail=same)
        gp5 = dict(qs8=np.rint(g['qs'][..., :3] * 255).astype(np.uint8), qd8=np.rint(g['qd'][..., :3] * 255).astype(np.uint8),
                   U=g['U'][..., :3], V=g['V'][..., :3])
        e5 = float(np.percentile(np.abs(radiance(gp5)[water] - radiance(p)[water]) / np.maximum(np.abs(radiance(p)[water]), 1e-2), 99.9))
        t.check('diffuse guide at the floor: lighting x guide preserved (< 2e-3)', e5 < 2e-3, detail=e5)

        # 5b. water: a static sea-floor print in both guides that the image does not show, while guides and image
        #     flicker together inside each frame (CP77 water); the floor rises 30% toward the camera under the print
        water_checks(hist_frames=24)

        # 6. history: reset restarts, invalid motion restarts, tiles without depth hold none
        t.check('history age grows to the cap on static frames', float(g2['A'][..., 3].max()) == 1 / P['rate'], detail=float(g2['A'][..., 3].max()))
        g3 = gpu_frame(p2, p2, depth2, motion2, hist2, flags=RESET)
        t.check('RESET restarts every tile', float(g3['A'][..., 3].max()) <= 1.0)
        t.check('RESET leaves the regressor without history: kappa 1', float(g3['kraw'].min()) == 1.0, detail=float(g3['kraw'].min()))
        lum_now = (p2['qs8'] / 255.0) @ LUMA
        t.check('RESET restarts the pixel guide history at the current guide',
                float(np.max(np.abs(g3['GH'][..., 0] - np.round(lum_now * 1023) / 1023))) < 1.5 / 1023)
        dj = depth2.copy(); dj[:, :32] *= 1.1
        gj = gpu_frame(p2, p2, dj, motion2, hist2)
        t.check('a 10% depth change restarts that pixel guide history',
                float(np.max(np.abs(gj['GH'][:, :30, 0] - np.round(lum_now[:, :30] * 1023) / 1023))) < 1.5 / 1023)
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
