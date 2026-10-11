"""GPU checks for the Recovery v2 lobe recovery (FSRDRecoveryLobeAccumulate/Down/Band.hlsl).

Every pass is compared with fsrd_recovery_lobe_reference.py at reset, immature and mature history, and the chain is
checked for behaviour on a static synthetic scene whose demodulated lighting carries fine stripes, a checkerboard and
a large-scale ramp, observed with multiplicative noise:
- when RR's output is the blurred lighting, the recovered composition moves towards the truth on every scale;
- when RR's output is the truth, the Wiener weights leave almost nothing (noise is not detail);
- Anchor only limits the correction (zero strength stays bit-exact even with RR outliers), Mix 1 transfers more;
- zero strength returns the composition bit-exactly; current-source pixels (Skip alpha -1) are untouched;
- a depth change restarts the reference and withdraws the correction there; the output stays non-negative;
- the gated bands carry no net energy (each is band-passed again);
- the FP16 reference is rounded stochastically: an increment below half a unit still converges;
- the split diffuse lobe reproduces the whole lobe's difference; NoSpecular removes the specular correction;
- on a still, jittered scene the reference at this frame's samples keeps the fine detail (value and sub-pixel
  gradient are fitted at each frame's sample position) far better than a plain average of the jittered samples.
"""
import os
for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_MAX_THREADS'):
    os.environ[k] = '2'
from pathlib import Path
import json
import hashlib
import time
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as a
import fsrd_recovery_lobe_reference as ref

W, H = 61, 43
L = ref.LEVELS


def rgba(x, alpha=0.0):
    x = np.asarray(x, np.float32)
    if x.ndim == 2:
        x = np.repeat(x[..., None], 3, -1)
    if x.shape[-1] == 4:
        return x
    return np.concatenate([x, np.full(x.shape[:2] + (1,), alpha, np.float32)], -1)


def constants(flags, frame, strength=(1, 1, 0, 1), level=0, sizes=None, jitter=(0.0, 0.0), blend=(0.0, 2.0, 1.0, 0.0)):
    sizes = sizes or ref.level_sizes(W, H)
    s0 = sizes[level]; s1 = sizes[min(level + 1, L)]
    return dict(DstTexSize=[W, H, 1 / W, 1 / H], LevelSize=[s0[0], s0[1], s1[0], s1[1]], Strength=list(strength),
                Jitter=[float(v) for v in jitter], Modulation=[1.0, 1.0], Response=0.03, Threshold=3.0, MatureAge=8.0,
                Flags=flags, Level=level, FrameIndex=frame, Debug=0, GradientAge=8.0, Blend=list(blend))


def halton(i, b):
    f, r = 1.0, 0.0
    while i > 0:
        f /= b; r += f * (i % b); i //= b
    return r


JITTER = [(halton(i + 1, 2) - 0.5, halton(i + 1, 3) - 0.5) for i in range(16)]


class Scene:
    def __init__(self, rng, loss=True):
        y, x = np.mgrid[:H, :W].astype(np.float32)
        stripes = 0.35 * np.sin(2 * np.pi * x / 5.0)
        checker = 0.3 * (((x // 3 + y // 3) % 2) * 2 - 1)
        ramp = 0.4 * (y / H)
        self.Ls = np.stack([1.0 + stripes + ramp, 0.9 + stripes + ramp, 0.8 + stripes], -1).astype(np.float32)
        self.Ld = np.stack([0.7 + checker + ramp, 0.8 + checker, 0.9 + checker + ramp], -1).astype(np.float32)
        blur = lambda v: np.stack([a_box(v[..., i], 2) for i in range(3)], -1)
        self.Ys = blur(self.Ls) if loss else self.Ls.copy()
        self.Yd = blur(self.Ld) if loss else self.Ld.copy()
        qs = np.where(x[..., None] < W // 2, 0.2 + 0.6 * rng.uniform(size=(H, W, 1)), 0.5)
        self.Qs = np.round(np.repeat(qs, 3, -1) * 255) / 255
        self.Qd = np.round(np.clip(0.3 + 0.3 * rng.uniform(size=(H, W, 3)), 0, 1) * 255) / 255
        self.depth = np.full((H, W), 10.0, np.float32)
        self.normals = np.zeros((H, W, 4), np.float32); self.normals[..., :2] = 0.5
        self.motion = np.zeros((H, W, 4), np.float32); self.motion[..., 3] = 1.0
        self.skip = np.zeros((H, W, 4), np.float32); self.skip[30:36, 50:56, 3] = -1.0
        self.rng = rng

    def sample(self, sigma=0.2):
        n = lambda: np.clip(self.rng.normal(0, sigma, (H, W, 3)), -0.9, None).astype(np.float32)
        return self.Ls * (1 + n()), self.Ld * (1 + n())

    def composed(self, Ys=None, Yd=None):
        Ys = self.Ys if Ys is None else Ys; Yd = self.Yd if Yd is None else Yd
        return (Ys * self.Qs + Yd * self.Qd).astype(np.float16).astype(np.float32)


def a_box(v, r):
    p = np.pad(v, r, mode='edge'); s = 0
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            s = s + p[dy:dy + v.shape[0], dx:dx + v.shape[1]]
    return s / (2 * r + 1) ** 2


# Only Strength, Blend and NoSpecular differ between several checks. Reuse the
# exact final-frame pyramid and pre-band histories from that GPU chain. The
# six band passes are still dispatched for each setting being checked.
CHAIN_CACHE = {}
PREFIX_CACHE = {}


def _chain_key(scene, frames, depth_change, flags_extra, sigma, jitter):
    h = hashlib.sha256()
    for name in ('Ls','Ld','Ys','Yd','Qs','Qd','depth','normals','motion','skip'):
        h.update(np.asarray(getattr(scene,name)).tobytes())
    return (h.digest(), repr(scene.rng.bit_generator.state), frames, repr(depth_change),
            flags_extra & ref.EXTRA_DIFFUSE, sigma, jitter)


def _cached_band(scene, entry, frames, strength, flags_extra, blend):
    A,B,C,noise,jit,info,RRd,RRd2 = entry
    sizes = ref.level_sizes(W,H)
    tiny = np.zeros((1,1,4),np.float32); Rs=Rd=tiny; color=None
    flags=ref.HISTORY_VALID | flags_extra if frames>1 else flags_extra
    comp=rgba(scene.composed(),1.)
    for l in range(L-1,-1,-1):
        final=l==0
        fl=flags | (ref.COARSEST if l==L-1 else 0) | (ref.FINAL if final else 0)
        cb=constants(fl,frames-1,strength,level=l,jitter=jit,blend=blend)
        ins=[A[l],B[l],C[l],A[l+1],B[l+1],Rs,Rd,noise[l],scene.motion,
             comp if final else tiny,rgba(scene.Qs,1) if final else tiny,rgba(scene.Qd,1) if final else tiny,
             scene.skip if final else tiny,rgba(scene.Ys) if final else tiny,rgba(RRd) if final else tiny,
             rgba(RRd2) if final else tiny]
        Rs,Rd,_,color=t._dispatch('FSRDRecoveryLobeBand',cb,ins,[10]*4,sizes[l],
            output_sizes=[sizes[l] if not final else (1,1)]*2+[sizes[l],sizes[0] if final else (1,1)])
    return color,{},info


def run_chain(scene, frames, strength=(1, 1, 0, 1), compare=False, depth_change=None, flags_extra=0, sigma=0.2, jitter=False,
              blend=(0.0, 2.0, 1.0, 0.0)):
    key = _chain_key(scene,frames,depth_change,flags_extra,sigma,jitter)
    if key in CHAIN_CACHE and not compare:
        return _cached_band(scene,CHAIN_CACHE[key],frames,strength,flags_extra,blend)
    sizes = ref.level_sizes(W, H)
    z4 = lambda s: np.zeros((s[1], s[0], 4), np.float32)
    hist = dict(s=z4(sizes[0]), d=z4(sizes[0]), g=z4(sizes[0]), grad=z4(sizes[0]))
    noise = [z4(sizes[l]) for l in range(L)]
    tiny = np.zeros((1, 1, 4), np.float32)
    errors = {}
    def err(key, gpu, cpu, rel=2e-3, ab=2e-4):
        e = float(np.max(np.abs(gpu - cpu) / (ab + rel * np.abs(cpu)))) if gpu.size else 0.0
        errors[key] = max(errors.get(key, 0.0), e)
    color = None; info = {}
    start_frame = 0
    if depth_change is not None:
        prefix_key = _chain_key(scene,depth_change[0],None,flags_extra,sigma,jitter)
        if prefix_key in PREFIX_CACHE:
            previous = PREFIX_CACHE[prefix_key]
            hist = {k:v.copy() for k,v in previous[0].items()}
            noise = [v.copy() for v in previous[1]]
            scene.rng.bit_generator.state = previous[2]
            start_frame = depth_change[0]
    for f in range(start_frame,frames):
        flags = (ref.HISTORY_VALID if f else 0) | flags_extra
        depth = scene.depth.copy()
        if depth_change is not None and f >= depth_change[0]:
            y0, y1, x0, x1 = depth_change[1]; depth[y0:y1, x0:x1] = 4.0
        Us, Vd = scene.sample(sigma)
        RRd = scene.Yd; RRd2 = np.zeros_like(RRd)
        if flags_extra & ref.EXTRA_DIFFUSE:
            Vd = Vd * 0.5; RRd = scene.Yd * 0.5; RRd2 = scene.Yd * 0.5
        jit = JITTER[f % 16] if jitter else (0.0, 0.0)
        c = constants(flags, f, strength, jitter=jit, blend=blend)
        ins = [rgba(Us), rgba(Vd), rgba(scene.Ys), rgba(RRd), rgba(RRd2), rgba(scene.Qs, 1), rgba(scene.Qd, 1), depth,
               scene.normals, scene.motion, scene.skip, hist['s'], hist['d'], hist['g'], hist['grad']]
        ms, md, geo, A0, B0, C0, grad = t._dispatch('FSRDRecoveryLobeAccumulate', c, ins, [10] * 7, (W, H))
        compare_frame = compare and f in (0,3,frames-1)
        if compare_frame:
            h16 = lambda v: ref.f16(rgba(v))  # the inputs are RGBA16F textures
            r = ref.accumulate(c, h16(Us), h16(Vd), h16(scene.Ys), h16(RRd), h16(RRd2), rgba(scene.Qs, 1), rgba(scene.Qd, 1),
                               depth, np.round(scene.normals * [1023, 1023, 1023, 3]) / [1023, 1023, 1023, 3], scene.motion,
                               scene.skip, hist['s'], hist['d'], hist['g'], hist['grad'])
            err('accumulate reference', ms[..., :3], r[0], rel=1.5e-3, ab=1e-4)
            err('accumulate reference', md[..., :3], r[1], rel=1.5e-3, ab=1e-4)
            err('accumulate gradient', grad, r[6], rel=1.5e-3, ab=1e-4)
            for name_, g_, c_ in (('geometry', geo, r[2]), ('level A', A0, r[3]), ('level B', B0, r[4]), ('level C', C0, r[5])):
                err('accumulate ' + name_, g_, c_)
        hist = dict(s=ms, d=md, g=geo, grad=grad)
        A, B, C = [A0], [B0], [C0]
        for l in range(1, L + 1):
            o = t._dispatch('FSRDRecoveryLobeDown', constants(flags, f, strength, level=l, jitter=jit) | dict(
                LevelSize=[sizes[l][0], sizes[l][1], sizes[l - 1][0], sizes[l - 1][1]]), [A[-1], B[-1], C[-1]], [10] * 3,
                sizes[l], output_sizes=[sizes[l]] * 3)
            if compare_frame:
                for x_, y_ in zip(o, (A[-1], B[-1], C[-1])):
                    err('down', x_, ref.down(y_, sizes[l]))
            A.append(o[0]); B.append(o[1]); C.append(o[2])
        Rs, Rd = tiny, tiny
        comp = rgba(scene.composed(), 1.0)
        if f == frames-1:
            CHAIN_CACHE[key]=(A,B,C,[v.copy() for v in noise],jit,dict(geo=geo,C0=C0),RRd,RRd2)
        for l in range(L - 1, -1, -1):
            fl = flags | (ref.COARSEST if l == L - 1 else 0) | (ref.FINAL if l == 0 else 0)
            cb = constants(fl, f, strength, level=l, jitter=jit, blend=blend)
            final = l == 0
            ins = [A[l], B[l], C[l], A[l + 1], B[l + 1], Rs, Rd, noise[l], scene.motion,
                   comp if final else tiny, rgba(scene.Qs, 1) if final else tiny, rgba(scene.Qd, 1) if final else tiny,
                   scene.skip if final else tiny, rgba(scene.Ys) if final else tiny, rgba(RRd) if final else tiny,
                   rgba(RRd2) if final else tiny]
            rs, rd, nz, col = t._dispatch('FSRDRecoveryLobeBand', cb, ins, [10] * 4, sizes[l],
                                          output_sizes=[sizes[l] if not final else (1, 1)] * 2 + [sizes[l], sizes[0] if final else (1, 1)])
            if compare_frame:
                h16 = lambda v: ref.f16(rgba(v))
                r = ref.band(cb, l, A[l], B[l], C[l], A[l + 1], B[l + 1], Rs, Rd, noise[l], scene.motion,
                             comp, rgba(scene.Qs, 1), rgba(scene.Qd, 1), scene.skip, h16(scene.Ys), h16(RRd), h16(RRd2))
                err('band noise', nz, r[2])
                if final:
                    err('band colour', col, r[3], rel=3e-3, ab=3e-4)
                else:
                    err('band correction', rs[..., :3], r[0], rel=3e-3, ab=3e-4); err('band correction', rd[..., :3], r[1], rel=3e-3, ab=3e-4)
            noise[l] = nz
            if not final:
                Rs, Rd = rs, rd
            else:
                color = col
        info = dict(geo=geo, C0=C0)
    PREFIX_CACHE[key]=({k:v.copy() for k,v in hist.items()},[v.copy() for v in noise],scene.rng.bit_generator.state)
    return color, errors, info



def check_new_behaviour():
    """Direct small fixtures isolate video, motion onset, anchor and dark-hole guards."""
    sc=Scene(np.random.default_rng(91)); sc.normals[...,3]=1.0/3.0
    z=np.zeros((H,W,4),np.float32)
    geo=z.copy(); geo[...,0]=10;geo[...,1:3]=.5;geo[...,3]=40
    y,x=np.mgrid[:H,:W].astype(np.float32)
    us=rgba(1.+.3*np.sin(2*np.pi*x/5)); vd=rgba(.8+.25*np.cos(2*np.pi*y/6))
    cb=constants(ref.HISTORY_VALID,41,jitter=(0,0),blend=(0,2,.15,1))
    common=[us,vd,rgba(sc.Ys),rgba(sc.Yd),z,rgba(sc.Qs,1),rgba(sc.Qd,1),sc.depth,sc.normals,sc.motion,sc.skip]
    low=t._dispatch('FSRDRecoveryLobeAccumulate',cb,common+[rgba(np.full((H,W),.2)),rgba(np.full((H,W),.2)),geo,z],[10]*7,(W,H))
    high=t._dispatch('FSRDRecoveryLobeAccumulate',cb,common+[rgba(np.full((H,W),2.5)),rgba(np.full((H,W),2.5)),geo,z],[10]*7,(W,H))
    t.check('video detail follows this frame independently of old billboard content',
            np.array_equal(low[3],high[3]) and np.array_equal(low[4],high[4]))
    c0=constants(0,0,jitter=(0,0),blend=(0,2,.15,1))
    first=t._dispatch('FSRDRecoveryLobeAccumulate',c0,common+[z,z,z,z],[10]*7,(W,H))
    cpu=ref.accumulate(c0,*[ref.f16(v) if i not in (7,8) else v for i,v in enumerate(common)],z,z,z,z)
    error=max(float(np.max(np.abs(first[i]-cpu[j]))) for i,j in ((3,3),(4,4),(5,5)))
    t.check('spatial display path matches the reference at reset',error<.008,detail=dict(max_error=error))
    t.check('spatial display detail is available on its first valid frame',float(first[5][...,2][sc.skip[...,3]!=-1].min())==1.)
    invalid_inputs=list(common);invalid_inputs[7]=sc.depth.copy();invalid_inputs[7][12,12]=0.
    invalid=t._dispatch('FSRDRecoveryLobeAccumulate',c0,invalid_inputs+[z,z,z,z],[10]*7,(W,H))
    t.check('invalid display geometry cannot enable spatial recovery',invalid[5][12,12,2]==0.)

    sizes=ref.level_sizes(W,H)
    def one_band(level=0,moving=False,innovation=.1,anchor=0.,mix=1.,negative=False,compare=False,threshold=3.,history=None,amplitude=.4):
        w,h=sizes[level]; yy,xx=np.mgrid[:h,:w].astype(np.float32)
        amp=(-8. if negative else amplitude)*np.sin(2*np.pi*xx/5.)
        A=rgba(amp,innovation);B=rgba(amp*.7,innovation)
        C=np.zeros((h,w,4),np.float32);C[...,2]=1.;C[...,3]=.125
        co=np.zeros((sizes[level+1][1],sizes[level+1][0],4),np.float32)
        hist=np.zeros((h,w,4),np.float32);hist[...,:2]=.1;hist[...,2]=20.
        if history is not None:hist=history
        mv=sc.motion.copy();mv[...,0]=(32./W if moving else 0.)
        rrS=rgba(np.full((H,W),1.));rrD=rgba(np.full((H,W),.7))
        qs=rgba(np.full((H,W),.08),1);qd=rgba(np.full((H,W),.03),1)
        comp=rgba(rrS[...,:3]*qs[...,:3]+rrD[...,:3]*qd[...,:3],1)
        fl=ref.HISTORY_VALID|ref.COARSEST|(ref.FINAL if level==0 else 0)
        cc=constants(fl,25,level=level,blend=(mix,anchor,.15,1))
        cc['Threshold']=threshold
        ins=[A,B,C,co,co,np.zeros((1,1,4),np.float32),np.zeros((1,1,4),np.float32),hist,mv,comp,qs,qd,z,rrS,rrD,z]
        out=t._dispatch('FSRDRecoveryLobeBand',cc,ins,[10]*4,sizes[level],output_sizes=[(1,1) if level==0 else sizes[level]]*2+[sizes[level],sizes[0] if level==0 else (1,1)])
        if compare:
            r=ref.band(cc,level,*[ref.f16(v) if i!=8 else v for i,v in enumerate(ins)])
            target=r[3] if level==0 else r[0]
            measured=out[3] if level==0 else out[0][...,:3]
            t.check('new guarded band path matches the reference',float(np.max(np.abs(measured-target)))<.008)
        return out,comp
    # Start from a static frame with no lobe difference, then introduce a
    # moving difference. Both policies receive the same pre-onset noise.
    warm,_=one_band(3,moving=False,mix=0.,amplitude=0.)
    legacy,_=one_band(3,moving=True,mix=0.,threshold=3./5.5,history=warm[2])
    moving,_=one_band(3,moving=True,mix=0.,history=warm[2],compare=True)
    stationary,_=one_band(3,moving=False,mix=0.,history=warm[2])
    t.check('stationary ordinary detail keeps the original coarse noise margin',
            np.allclose(stationary[0],legacy[0],rtol=0,atol=.001))
    a=float(np.sqrt(np.mean(legacy[0][...,:3]**2)));b=float(np.sqrt(np.mean(moving[0][...,:3]**2)))
    t.check('motion onset coarse energy is restrained by the larger noise margin',b<a*.8,detail=dict(legacy_margin=a,coarse_margin=b))
    lo,_=one_band(innovation=.01,anchor=2.)
    hi,_=one_band(innovation=8.,anchor=2.)
    t.check('Anchor width is independent of reference noise',np.array_equal(lo[3],hi[3]))
    dark,base=one_band(negative=True,compare=True)
    t.check('low-albedo negative corrections retain at least 75 percent of RR',
            bool(np.all(dark[3][...,:3]>=.75*base[...,:3]-.001)))
    # Signed HDR inputs must not make the negative cap invent a correction
    # when all recovery strengths are zero.
    rrS=rgba(np.full((H,W),-.2));rrD=rgba(np.full((H,W),.7))
    comp=rgba(np.full((H,W),.5),1.)
    A=rgba(np.full((H,W),.2),.1);C=z.copy();C[...,2]=1.;C[...,3]=.125
    cb=constants(ref.HISTORY_VALID|ref.COARSEST|ref.FINAL,25,strength=(0,0,0,0))
    result=t._dispatch('FSRDRecoveryLobeBand',cb,[A,A,C,z,z,z,z,z,sc.motion,comp,rgba(sc.Qs,1),rgba(sc.Qd,1),z,rrS,rrD,z],[10]*4,(W,H),output_sizes=[(1,1),(1,1),(W,H),(W,H)])
    t.check('zero recovery cannot inject energy from signed RR channels',np.array_equal(result[3],comp))


def main():
    started = time.perf_counter()
    out = Path(os.environ.get('FSRD_RECOVERY_LOBE_TEST_OUTPUT', str(t.OUT)))
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11)
    with a.GPUWorker(out / 'worker'):
        scene = Scene(rng, loss=True)
        _, errors, _ = run_chain(scene, 8, compare=True)
        for key, value in errors.items():
            t.check('GPU matches the reference: ' + key, value <= 1.0, detail=dict(normalised_error=value))
        _, errors, _ = run_chain(Scene(np.random.default_rng(17), loss=True), 10, compare=True, jitter=True)
        for key, value in errors.items():
            t.check('GPU matches the reference with jitter: ' + key, value <= 1.0, detail=dict(normalised_error=value))

        # The transfer itself (Anchor off): the synthetic RR is a 5x5 box blur, whose local spread is far below the
        # lost stripes and checkerboard, so Anchor 2 would (correctly) hold most of that hard-edged detail back.
        color, _, _ = run_chain(Scene(np.random.default_rng(11), loss=True), 8, blend=(0.0, 0.0, 1.0, 0.0))
        truth = scene.composed(scene.Ls, scene.Ld)
        rr = scene.composed()
        inner = (slice(4, H - 4), slice(4, W - 4))
        e_rr = float(np.sqrt(np.mean(((rr - truth) @ ref.LUMA)[inner] ** 2)))
        e_v2 = float(np.sqrt(np.mean(((color[..., :3] - truth) @ ref.LUMA)[inner] ** 2)))
        t.check('blurred RR: the recovery moves the composition towards the truth', e_v2 < 0.75 * e_rr,
                detail=dict(rr_rmse=e_rr, recovered_rmse=e_v2))
        corr = (color[..., :3] - rr) @ ref.LUMA
        mean, rms = float(corr[inner].mean()), float(np.sqrt(np.mean(corr[inner] ** 2)))
        t.check('the weighted bands carry no net energy', abs(mean) < 0.1 * rms, detail=dict(mean=mean, rms=rms))
        t.check('output is non-negative', float(color[..., :3].min()) >= 0.0)
        cs = (slice(30, 36), slice(50, 56))
        t.check('current-source pixels are untouched', np.array_equal(color[cs][..., :3], rr[cs]))

        clean, _, _ = run_chain(Scene(np.random.default_rng(12), loss=False), 8)
        exact = Scene(np.random.default_rng(12), loss=False)
        false_rms = float(np.sqrt(np.mean(((clean[..., :3] - exact.composed()) @ ref.LUMA)[inner] ** 2)))
        t.check('RR without loss: noise is not mistaken for detail', false_rms < 0.15 * rms,
                detail=dict(false_correction_rms=false_rms, recovered_correction_rms=rms))

        zero, _, _ = run_chain(Scene(np.random.default_rng(13), loss=True), 1, strength=(0, 0, 0, 0))
        z_scene = Scene(np.random.default_rng(13), loss=True)
        t.check('zero strength returns the composition bit-exactly', np.array_equal(zero[..., :3], z_scene.composed()))
        # Anchor limits the correction only: an RR outlier outside its own 3x3 range is not pulled in.
        o_scene = Scene(np.random.default_rng(13), loss=True)
        o_scene.Ys[20, 20] *= 6.0; o_scene.Yd[30, 40] *= 0.05
        outlier, _, _ = run_chain(o_scene, 1, strength=(0, 0, 0, 0), blend=(0.0, 0.5, 1.0, 0.5))
        t.check('Anchor never moves RR itself', np.array_equal(outlier[..., :3], o_scene.composed()))
        anchored, _, _ = run_chain(Scene(np.random.default_rng(11), loss=True), 8)
        corr_anchor = float(np.sqrt(np.mean(((anchored[..., :3] - rr) @ ref.LUMA)[inner] ** 2)))
        e_anchor = float(np.sqrt(np.mean(((anchored[..., :3] - truth) @ ref.LUMA)[inner] ** 2)))
        t.check('Anchor 2 limits the correction and still moves towards the truth', corr_anchor < rms and e_anchor < e_rr,
                detail=dict(anchor2=corr_anchor, anchor_off=rms, anchor2_rmse=e_anchor, rr_rmse=e_rr))
        mixed, _, _ = run_chain(Scene(np.random.default_rng(11), loss=True), 8, blend=(1.0, 0.0, 1.0, 0.0))
        corr_mix = float(np.sqrt(np.mean(((mixed[..., :3] - rr) @ ref.LUMA)[inner] ** 2)))
        t.check('Mix 1 transfers more of the reference than Mix 0', corr_mix > rms, detail=dict(mix1=corr_mix, mix0=rms))

        nospec, _, _ = run_chain(Scene(np.random.default_rng(11), loss=True), 8, strength=(1, 0, 0, 0), flags_extra=ref.NO_SPECULAR)
        t.check('NoSpecular removes the specular correction', np.array_equal(nospec[..., :3], Scene(np.random.default_rng(11)).composed()))

        # Test local disocclusion with the selected production Anchor/Mix defaults.
        box = (8, 24, 8, 24)
        restart_blend = (0., 4., .15, .75)
        before, _, _ = run_chain(Scene(np.random.default_rng(15), loss=True), 8, blend=restart_blend)
        after, _, info = run_chain(Scene(np.random.default_rng(15), loss=True), 9, depth_change=(8, box), blend=restart_blend)
        sc = Scene(np.random.default_rng(15), loss=True)
        region = (slice(box[0] + 2, box[1] - 2), slice(box[2] + 2, box[3] - 2))
        c_before = float(np.abs(((before[..., :3] - sc.composed()) @ ref.LUMA)[region]).mean())
        c_after = float(np.abs(((after[..., :3] - sc.composed()) @ ref.LUMA)[region]).mean())
        t.check('a depth change restarts the reference', float(info['geo'][region][..., 3].max()) == 1.0)
        t.check('the correction is withdrawn where the reference restarted', c_after < 0.35 * c_before,
                detail=dict(before=c_before, after=c_after))

        # split diffuse lobe: the same difference as the whole lobe
        sc = Scene(np.random.default_rng(16), loss=True)
        Us, Vd = sc.sample()
        base = [rgba(Us), None, rgba(sc.Ys), None, None, rgba(sc.Qs, 1), rgba(sc.Qd, 1), sc.depth, sc.normals, sc.motion,
                sc.skip, np.zeros((H, W, 4), np.float32), np.zeros((H, W, 4), np.float32), np.zeros((H, W, 4), np.float32),
                np.zeros((H, W, 4), np.float32)]
        whole = list(base); whole[1] = rgba(Vd); whole[3] = rgba(sc.Yd); whole[4] = np.zeros((H, W, 4), np.float32)
        split = list(base); split[1] = rgba(0.5 * Vd); split[3] = rgba(0.5 * sc.Yd); split[4] = rgba(0.5 * sc.Yd)
        ow = t._dispatch('FSRDRecoveryLobeAccumulate', constants(0, 0), whole, [10] * 7, (W, H))
        os_ = t._dispatch('FSRDRecoveryLobeAccumulate', constants(ref.EXTRA_DIFFUSE, 0), split, [10] * 7, (W, H))
        t.check('split diffuse lobe reproduces the whole lobe', float(np.abs(ow[4] - os_[4]).max()) <= 1e-3 * float(np.abs(ow[4]).max()))

        # stochastic FP16 rounding: an increment far below half a unit still converges
        target = np.float32(np.float16(1.0) + np.float16(2 ** -10))  # the next FP16 value above 1
        state = np.ones((H, W, 4), np.float32)
        geo = np.zeros((H, W, 4), np.float32); geo[..., 0] = 10.0; geo[..., 1:3] = 0.5; geo[..., 3] = 100.0
        means = []
        for f in range(32):
            c = constants(ref.HISTORY_VALID, f)
            ins = [np.full((H, W, 4), target, np.float32), np.full((H, W, 4), target, np.float32), np.ones((H, W, 4), np.float32),
                   np.ones((H, W, 4), np.float32), np.zeros((H, W, 4), np.float32), rgba(np.full((H, W, 3), .5), 1),
                   rgba(np.full((H, W, 3), .5), 1), np.full((H, W), 10.0, np.float32), sc.normals, sc.motion,
                   np.zeros((H, W, 4), np.float32), state, state, geo, np.zeros((H, W, 4), np.float32)]
            ms, md, g2, *_ = t._dispatch('FSRDRecoveryLobeAccumulate', c, ins, [10] * 7, (W, H))
            state = ms; geo = g2
            means.append(float(ms[..., :3].mean()))
        expected = 1.0 + (float(target) - 1.0) * (1 - 0.97 ** 32)
        t.check('FP16 reference rounds stochastically (no stall below half a unit)', abs(means[-1] - expected) < 1e-4,
                detail=dict(mean=means[-1], expected=float(expected), round_to_nearest_would_stay=1.0))

        # a still, jittered scene: pixel p samples the lighting at p - jitter; RR's output is zero, so level A is the
        # reference at this frame's samples. Its 3x3 high-pass must keep most of the input's.
        y, x = np.mgrid[:H, :W].astype(np.float32)
        light = lambda xx, yy: (1.0 + 0.3 * np.sin(2 * np.pi * xx / 3.7 + 0.4) + 0.3 * np.sin(2 * np.pi * yy / 4.3)
                                + 0.2 * np.sin(2 * np.pi * (xx + yy) / 5.1)).astype(np.float32)
        zero4 = np.zeros((H, W, 4), np.float32)
        state = dict(s=zero4, d=zero4, g=zero4, grad=zero4)
        ema = None
        for f in range(48):
            jx, jy = JITTER[f % 16]
            U = rgba(light(x - jx, y - jy))
            ema = U[..., 1].copy() if ema is None else ema + 0.03 * (U[..., 1] - ema)
            c = constants(ref.HISTORY_VALID if f else 0, f, jitter=(jx, jy))
            ins = [U, U, zero4, zero4, zero4, rgba(sc.Qs, 1), rgba(sc.Qd, 1), np.full((H, W), 10.0, np.float32), sc.normals,
                   sc.motion, zero4, state['s'], state['d'], state['g'], state['grad']]
            ms, md, g2, A0, B0, _, gr = t._dispatch('FSRDRecoveryLobeAccumulate', c, ins, [10] * 7, (W, H))
            state = dict(s=ms, d=md, g=g2, grad=gr)
        hp = lambda v: v - a_box(v, 1)
        core = (slice(4, H - 4), slice(4, W - 4))
        target = hp(U[..., 1])[core]
        keep = float(np.sum(hp(A0[..., 1])[core] * target) / np.sum(target ** 2))
        samples = light(x - jx, y - jy)
        e_value = float(np.sqrt(np.mean((A0[..., 1] - samples)[core] ** 2)))
        e_average = float(np.sqrt(np.mean((ema - samples)[core] ** 2)))
        t.check('a still jittered scene keeps its fine detail at this frame\'s samples', keep > 0.85, detail=dict(kept=keep))
        t.check("the reference at this frame's samples beats a plain average of the jittered samples",
                e_value < 0.5 * e_average, detail=dict(reference_rmse=e_value, plain_average_rmse=e_average))

        check_new_behaviour()

    failures = sum(not x['passed'] for x in t.checks)
    (out / 'results.json').write_text(json.dumps(dict(checks=t.checks, failures=failures), indent=2))
    print('recovery lobe: %d checks, %d failures' % (len(t.checks), failures))
    for x in t.checks:
        if not x['passed']:
            print('FAIL', x['name'], x.get('detail'))
    print('recovery lobe wall seconds: %.3f' % (time.perf_counter()-started))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
