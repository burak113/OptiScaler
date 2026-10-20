"""RR Lab metrics (luma, camera-aligned where the camera moves). All take a runner.Result (or [N,H,W,3] + Capture).

boiling(res, ref, frames)   temporal CV of the camera-aligned output on flat, non-sky, valid pixels: p50, p90 and
                            'detail' (mean |temporal mean - blur(1.5)|, compare as a ratio to a base variant)
static_cv(res, last)        unaligned CV of the last frames (static captures such as d6d2a083)
post_turn(res)              level excess after the last fast turn (+1/+6/+16/+24 frames, vs the settled level)
specks(res, last)           white specks per 10k px per frame (> 1.6x 5x5 median and > 1.6x converged input)
level(res, frames)          output luma / input luma over the given frames (energy bias)
step(res, at, ...)          lighting-step response on a Step fixture: residual at +1/+4/+16/+32, frames to 5 %
step_chroma(...)            same for a ChromaStep fixture, tracked on the robust R share (task 25)
evaluate(res, preset)       the standard set for a capture (bench presets or automatic segments)
Run-to-run noise: compare 'base' with 'base+rep2' (identical RR work, separate run)."""
import numpy as np
from .imgutil import LUMA, gaussian, medf, boxf

_masks = {}


def _arr(res):
    return (res.rgb, res.cap, res.frames) if hasattr(res, 'rgb') else res


def _flat_mask(c, ref):
    k = (c.uuid, ref)
    if k not in _masks:
        z = c.depth(ref)
        sky = np.abs(z) > 500
        inner = np.zeros((c.H, c.W), bool)
        inner[8:-8, 8:-8] = True
        gz = np.hypot(*np.gradient(np.log(np.abs(z) + 1e-3)))
        flat = gaussian((gz > 0.02).astype(np.float32), 1.5) < 0.05
        _masks[k] = (inner & ~sky, flat)
    return _masks[k]


def aligned_stack(c, out, frames_all, ref, frames):
    """Luma of out[t] for t in frames, reprojected into frame ref's view; plus the joint validity mask."""
    idx = {t: k for k, t in enumerate(frames_all)}
    A, ok = [], np.ones((c.H, c.W), bool)
    for t in frames:
        img = out[idx[t]]
        if t == ref:
            A.append(img @ LUMA)
            continue
        w, m = c.warp(ref, t, img)
        A.append(w @ LUMA)
        ok &= m
    return np.stack(A), ok


def boiling(res, ref, frames, flat=True):
    out, c, fa = _arr(res)
    L, ok = aligned_stack(c, out, fa, ref, list(frames))
    base, flatm = _flat_mask(c, ref)
    m = ok & base & (flatm if flat else True)
    mean = L.mean(0)
    cv = L.std(0) / np.maximum(mean, 1e-6)
    if not m.any():
        return dict(p50=None, p90=None, detail=None, cv_map=cv, mask=m)
    return dict(p50=float(np.median(cv[m])), p90=float(np.quantile(cv[m], .9)),
                detail=float(np.abs(mean - gaussian(mean, 1.5))[m].mean()), cv_map=cv, mask=m)


def static_cv(res, last=24):
    out, c, fa = _arr(res)
    z = np.abs(c.depth(fa[0]))
    mk = (z < 500) & (z > 0)
    L = out[-last:] @ LUMA
    cv = L.std(0) / np.maximum(L.mean(0), 1e-9)
    return dict(p50=float(np.median(cv[mk])), p90=float(np.quantile(cv[mk], .9)), cv_map=cv, mask=mk)


def post_turn(res, ks=(1, 6, 16, 24)):
    out, c, fa = _arr(res)
    rot = c.motion()[0]
    fast = [t for t in fa if rot[t] > 3.0]
    if not fast:
        return None
    last, N = max(fast), fa[-1] + 1
    REF = fa[-3]
    idx = {t: k for k, t in enumerate(fa)}
    mask = np.abs(c.depth(REF)) < 500
    vals = {}
    for t in range(last + 1, N):
        if t == REF:
            vals[t] = out[idx[t]] @ LUMA
            continue
        w, ok = c.warp(REF, t, out[idx[t]])
        vals[t] = w @ LUMA
        mask &= ok
    settled = np.mean([vals[t][mask].mean() for t in range(N - 8, N)])
    ex = {f'+{k}': float(vals[last + k][mask].mean() / settled - 1) for k in ks if last + k < N}
    tail = boiling(res, REF, range(N - 12, N), flat=False)
    return dict(turn_end=last, excess=ex, settled_p50=tail['p50'], settled_p90=tail['p90'])


def specks(res, last=24):
    out, c, fa = _arr(res)
    z = np.abs(c.depth(fa[0]))
    m = (z < 500) & (z > 0)
    m &= boxf(m.astype(np.float32), 5) > 0.99
    refm = medf(np.mean([c.rgb(t, 'in') for t in fa], 0) @ LUMA, 3)
    L = out[-last:] @ LUMA
    sp = np.stack([(L[t] > 1.6 * medf(L[t], 5)) & (L[t] > 1.6 * refm) & m for t in range(len(L))])
    again = (sp[1:] & sp[:-1]).sum() / max(sp[:-1].sum(), 1)
    Lm = L.mean(0)
    msp = (Lm > 1.6 * medf(Lm, 5)) & (Lm > 1.6 * refm) & m
    return dict(per10k=float(sp.mean() * 1e4), persist=float(again), in_mean_per10k=float(msp.mean() * 1e4))


def level(res, frames=None):
    out, c, fa = _arr(res)
    frames = fa if frames is None else list(frames)
    idx = {t: k for k, t in enumerate(fa)}
    z = np.abs(c.depth(frames[0]))
    m = (z < 500) & (z > 0)
    o = np.mean([out[idx[t]] @ LUMA for t in frames], 0)
    i = np.mean([c.rgb(t, 'in') @ LUMA for t in frames], 0)
    return float(o[m].mean() / max(i[m].mean(), 1e-12))


def step(res, at, gain, ks=(1, 4, 16, 32, 64), box=None):
    """Residual of the lighting step: (level/target - 1) / (1/gain - 1) -> 1 at the old level, 0 at the new level."""
    out, c, fa = _arr(res)
    idx = {t: k for k, t in enumerate(fa)}
    z = np.abs(c.depth(fa[0]))
    m = (z < 500) & (z > 0)
    if box:
        x0, y0, x1, y1 = box
        bm = np.zeros_like(m)
        bm[y0:y1, x0:x1] = True
        m &= bm
    lv = np.array([(out[idx[t]] @ LUMA)[m].mean() for t in fa])
    pre = lv[[idx[t] for t in fa if at - 8 <= t < at]].mean()
    target = pre * gain
    resid = (lv / target - 1) / (1.0 / gain - 1)  # 1 = still at the old level, 0 = at the new level
    after = {t: resid[idx[t]] for t in fa if t >= at}
    r = {f'+{k}': float(after[at + k]) for k in ks if at + k in after}
    t5 = next((t - at for t in sorted(after) if all(abs(after[u]) < 0.05 for u in after if u >= t)), None)
    return dict(residual=r, frames_to_5pct=t5, curve=[float(after[t]) for t in sorted(after)])


def step_independent(res_step, res_old, res_new, at, ks=(1, 4, 16, 32, 64), box=None):
    """Lighting step against independent endpoints (Sol's step_independent_endpoint semantics):
    old = same variant on the unchanged capture, new = same variant with the gain applied from frame 0.
    residual(t) = (step - new) / (old - new) per frame -> RR's non-linearity in scale cannot pose as lag.
    Also returns 'bias' = new-run level / (old-run level * gain) - 1 (scale non-linearity of the variant)."""
    c, fa = res_step.cap, res_step.frames
    z = np.abs(c.depth(fa[0]))
    m = (z < 500) & (z > 0)
    if box:
        x0, y0, x1, y1 = box
        bm = np.zeros_like(m)
        bm[y0:y1, x0:x1] = True
        m &= bm
    lv = lambda r: np.array([(r.frame(t) @ LUMA)[m].mean() for t in fa])
    s, o, n = lv(res_step), lv(res_old), lv(res_new)
    idx = {t: k for k, t in enumerate(fa)}
    resid = {t: float((s[idx[t]] - n[idx[t]]) / (o[idx[t]] - n[idx[t]])) for t in fa if t >= at}
    r = {f'+{k}': resid[at + k] for k in ks if at + k in resid}
    t5 = next((t - at for t in sorted(resid) if all(abs(resid[u]) < 0.05 for u in resid if u >= t)), None)
    gain = res_step.cap.gain
    bias = float(n[idx[fa[-1]]] / (o[idx[fa[-1]]] * gain) - 1)
    return dict(residual=r, frames_to_5pct=t5, scale_bias=bias, curve=[resid[t] for t in sorted(resid)])


def rshare(img, m):
    """Robust colour metric used by the task-25 pre-tests (tmp/pfmeasure.py): sigma-6 smoothed R share,
    median over the mask. Noise-free for ~10^4-sample neighbourhoods."""
    s = np.moveaxis(gaussian(np.moveaxis(img.astype(np.float32), -1, 0), 6.0), 0, -1)
    return float(np.median((s[..., 0] / np.maximum(s.sum(-1), 1e-9))[m]))


def step_chroma(res_step, res_old, res_new, at, ks=(1, 4, 16, 32, 64), box=None):
    """Chroma step against independent endpoints (task 25): same residual definition as step_independent,
    but the quantity tracked is the robust R share, so it measures RR's colour response to a luma-neutral
    input colour step. 'rshare_shift' = adapted R share - old R share (size of the step RR must follow)."""
    c, fa = res_step.cap, res_step.frames
    z = np.abs(c.depth(fa[0]))
    m = (z < 500) & (z > 0)
    if box:
        x0, y0, x1, y1 = box
        bm = np.zeros_like(m)
        bm[y0:y1, x0:x1] = True
        m &= bm
    lv = lambda r: np.array([rshare(r.frame(t), m) for t in fa])
    s, o, n = lv(res_step), lv(res_old), lv(res_new)
    idx = {t: k for k, t in enumerate(fa)}
    resid = {t: float((s[idx[t]] - n[idx[t]]) / (o[idx[t]] - n[idx[t]])) for t in fa if t >= at}
    r = {f'+{k}': resid[at + k] for k in ks if at + k in resid}
    t5 = next((t - at for t in sorted(resid) if all(abs(resid[u]) < 0.05 for u in resid if u >= t)), None)
    return dict(residual=r, frames_to_5pct=t5, rshare_shift=float(n[idx[fa[-1]]] - o[idx[fa[-1]]]),
                curve=[resid[t] for t in sorted(resid)])


# ---- presets: the windows behind the 2026-10-19 numbers (fsrd-adaptive-stability memory)
PRESETS = {
    'f2ef375f': lambda r: dict(all=_bp(boiling(r, 30, range(10, r.cap.n))), stop=_bp(boiling(r, 42, range(34, r.cap.n))),
                               pan=_bp(boiling(r, 20, range(10, 31)))),
    'd6d2a083': lambda r: dict(static=_bp(static_cv(r, 24)), specks=specks(r, 24)),
    '06fadf38': lambda r: dict(turn=post_turn(r)),
}


def _bp(b):
    return {k: v for k, v in b.items() if k not in ('cv_map', 'mask')}


def auto(res):
    """Segments from the capture's own camera motion: still/moving runs + post-turn when present."""
    c = res.cap
    seg = c.segments()
    out = {}
    fa = set(res.frames)
    for kind, a, b in seg['runs']:
        fr = [t for t in range(a, b) if t in fa]
        if len(fr) < 8:
            continue
        out[f'{kind}{a}-{b - 1}'] = _bp(boiling(res, fr[len(fr) // 2], fr, flat=True))
    if seg['last_fast_turn'] is not None and res.frames[-1] - seg['last_fast_turn'] >= 16:
        out['turn'] = post_turn(res)
    return out


def evaluate(res, preset=None):
    key = preset or res.cap.id
    return PRESETS[key](res) if key in PRESETS else auto(res)


def flatten(ev, prefix=''):
    """{'stop': {'p90': .1}} -> {'stop.p90': .1} for tables."""
    out = {}
    for k, v in (ev or {}).items():
        if isinstance(v, dict):
            out.update(flatten(v, f'{prefix}{k}.'))
        elif isinstance(v, (int, float)) or v is None:
            out[prefix + k] = v
    return out
