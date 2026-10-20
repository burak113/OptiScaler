"""Task-23 additive metrics. Existing metrics/presets retain their meanings."""
import numpy as np
from . import metrics as M
from .imgutil import LUMA

def post_turn_absolute(res, ks=(1, 6, 16, 24)):
    c, fa = res.cap, res.frames
    rot = c.motion()[0]
    fast = [t for t in fa if rot[t] > 3]
    if not fast: return None
    last, ref = max(fast), fa[-3]
    mask = np.abs(c.depth(ref)) < 500
    values = {}
    for t in fa:
        if t <= last: continue
        w, ok = c.warp(ref, t, res.frame(t))
        mask &= ok
        values[t] = w @ LUMA
    if not mask.any(): return dict(common_pixels=0)
    levels = {t: float(v[mask].mean()) for t,v in values.items()}
    settled = float(np.mean([levels[t] for t in fa[-8:]]))
    return dict(common_pixels=int(mask.sum()), settled_level=settled,
                first_levels={f'+{k}':levels[last+k] for k in ks if last+k in levels},
                units='captured game linear luminance; same original geometry support for all variants')

def step_tail(step_result):
    x = np.asarray(step_result['curve'],np.float64)
    return dict(tail_area_frame_contrast=float(np.abs(x).sum()),
                signed_area_frame_contrast=float(x.sum()), tail_frames=len(x),
                max_abs_residual=float(np.abs(x).max()))

def walking_pairs(res, rotation=.1, translation=.0015):
    """Pair-aligned output change on walking-only frames; proxy includes real scene/lighting change.
    Full-window alignment can have zero intersection in a narrow moving ROI. Each pair keeps its own original
    depth support. This is NOT the established whole-window boiling CV and must never replace that metric.
    """
    c=res.cap; rot,tr=c.motion(); fa=set(res.frames); values=[]; supports=[]; frames=[]
    for t in res.frames:
        if t-1 not in fa or rot[t]>rotation or tr[t]<=translation: continue
        a=res.frame(t)@LUMA; b,ok=c.warp(t,t-1,res.frame(t-1)); b=b@LUMA
        geom,flat=M._flat_mask(c,t); mask=ok&geom&flat
        if not mask.any(): continue
        values.append(float(np.median((np.abs(a-b)/np.maximum(a+b,1e-8))[mask])))
        supports.append(int(mask.sum())); frames.append(t)
    return dict(pair_count=len(values), frames=frames, support_min=min(supports,default=0),
                pair_change_p50=float(np.median(values)) if values else None,
                pair_change_p90=float(np.quantile(values,.9)) if values else None)

def dark_static(res):
    """Do not select candidates by cb550300 p90: it is known to vary strongly between identical runs."""
    return dict(static=M._bp(M.static_cv(res,24)), specks=M.specks(res,24),
                level=M.level(res,range(max(0,res.cap.n-24),res.cap.n)),
                warning='cb550300 p90 is unstable; inspect p50, energy, specks and images together')

PRESETS23={'cb550300':dark_static,'daa670e9':walking_pairs}
