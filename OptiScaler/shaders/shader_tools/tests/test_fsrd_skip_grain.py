"""Negative raw excursions must not punch noisy holes in the spatial Skip pedestal.

Actual production DXIL; RR is independently simulated, not AMD model inference.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_zero_rough_screen import chain_cb


def run():
    t.OUT=t.OUT.parent/'skip_grain';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=97,65
    rng=np.random.default_rng(71651)
    zero=t.rgba(w,h,(0,0,0));normal=t.rgba(w,h,(0,0,1))
    albedo=t.rgba(w,h,(.7,.7,.7));spec=t.rgba(w,h,(.04,.04,.04))
    rough=np.zeros((h,w),np.float32);depth=np.full((h,w),10,np.float32)
    cb=chain_cb(w,h,(1<<1)|(1<<7))
    def pack(raw,f,ref):
        return t.dispatch('FSRDInputConv',cb,
            [raw,depth,zero,normal,rough,depth,albedo,spec,zero,f,zero,zero,zero,zero,depth,zero,ref],
            [10,10,10,24,28,28,10,10],(w,h))
    # The user-facing zero setting must remove the display pedestal, not only
    # mute composition. Test the published RR inputs and Skip independently.
    for scale in (.01,1,128):
        raw=t.rgba(w,h,(.3*scale,)*3)
        raw[...,:3]+=rng.normal(0,.025*scale,(h,w,3))
        f=t.rgba(w,h,(.25*scale,)*3,.04*scale)
        ref=raw.copy();ref[...,3]=.04*scale
        cb['FloorDetailPreservation']=0
        p=pack(raw,f,ref)
        roi=(slice(4,-4),slice(4,-4),slice(0,3))
        t.check(f'zero detail display Skip is exactly zero scale={scale}',
                np.count_nonzero(p[6][roi])==0,maximum=float(np.max(p[6][roi])))
        t.check(f'zero detail still lifts RR roughness scale={scale}',
                np.min(p[3][4:-4,4:-4,2])>.09)
        remod=p[0][...,:3]*p[4][...,:3]+p[1][...,:3]*p[5][...,:3]
        t.check(f'zero detail full noisy signal reaches RR scale={scale}',
                np.max(np.abs(remod-raw[...,:3]))<.001*scale)
        t.check(f'zero detail invalidates detail reference scale={scale}',np.all(p[7][...,3]<0))
        # Full-chain identity closure and independently clean RR prove that no
        # stored pedestal/rounding grain can leak back through composition.
        clean=t.rgba(w,h,(.3*scale,)*3);unit=t.rgba(w,h,(1,1,1))
        out=t.dispatch('FSRDOutputComp',dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=0),
            [zero,unit,clean,unit,p[6],p[3],p[7],depth],[10],(w,h))[0]
        t.check(f'zero detail clean RR remains constant scale={scale}',
                np.max(np.ptp(out[roi],axis=(0,1)))==0)
    # An ordinary wall retains Floor's volumetric bypass at the same setting.
    rough[:]=.5
    flat=t.rgba(w,h,(.3,.3,.3));flat_ref=flat.copy();flat_ref[...,3]=0
    p=pack(flat,t.rgba(w,h,(.25,.25,.25)),flat_ref)
    t.check('zero detail ordinary surface retains spatial Floor',np.min(p[6][4:-4,4:-4,:3])>=.249)
    rough[:]=0
    cb['FloorDetailPreservation']=.35
    rng=np.random.default_rng(71651)
    for scale in (.01,1,128):
        raw=t.rgba(w,h,(.3,.3,.3));raw[...,:3]+=rng.normal(0,.04,(h,w,3))
        raw[...,:3]*=scale
        floor=t.rgba(w,h,(.27*scale,)*3,.04*scale)
        ref=raw.copy();ref[...,3]=.04*scale
        p=pack(raw,floor,ref)
        skip=p[6][...,:3]
        old=np.minimum(floor[...,:3],raw[...,:3])
        rms=float(np.sqrt(np.mean(skip**2))/scale)
        old_rms=float(np.sqrt(np.mean((old-.27*scale)**2))/scale)
        # Selected screens must not carry a pedestal at any detail setting.
        t.check(f'positive detail selected Skip exactly zero scale={scale}',rms==0,
                current_rms=rms,hard_ceiling_rms=old_rms)
        remod=p[0][...,:3]*p[4][...,:3]+p[1][...,:3]*p[5][...,:3]+skip
        expected=np.maximum(raw[...,:3],skip)
        t.check(f'identity closure includes explicit pedestal excess scale={scale}',
                np.max(np.abs(remod-expected))<scale*.001)
        # Clean thin strokes still demand the exact raw ceiling (zero sigma).
        ref[...,3]=0;raw[:,::7,:3]=.025*scale;ref[...,:3]=raw[...,:3]
        p=pack(raw,floor,ref)
        t.check(f'clean dark stroke ceiling scale={scale}',np.max(p[6][:,::7,:3])<=.0251*scale)
    # Full seed/filter/conversion: this catches the original missing integration
    # coverage where only F, rather than the published Skip, was tested for noise.
    raw=t.rgba(w,h,(.25,.32,.4));raw[...,:3]+=rng.normal(0,.025,(h,w,3))
    f,z,g,ref=t.seed(raw,depth=depth,normal=normal,albedo=albedo)
    f=t.filter_floor(f,z,g,albedo)
    p=pack(raw,f,ref)
    roi=(slice(16,-16),slice(16,-16),slice(0,3))
    old=np.minimum(f[...,:3],raw[...,:3])
    def spread(c):return float(np.mean(np.var(c[roi],axis=(0,1))))
    t.check('full chain Skip variance reduced versus raw ceiling',spread(p[6])<spread(old)*.4,
            skip_variance=spread(p[6]),hard_ceiling_variance=spread(old),floor_variance=spread(f))
    # Independently clean residual plus published Skip, with maximal detail.
    clean=t.rgba(w,h,(.25,.32,.4))
    # A constant ideal residual does not cancel Skip's per-pixel error by
    # construction. It preserves only the known clean mean light balance.
    clean_residual=clean.copy();clean_residual[...,:3]=np.maximum(
        clean[...,:3]-np.mean(p[6][roi],axis=(0,1)),0)
    unit=t.rgba(w,h,(1,1,1))
    out=t.dispatch('FSRDOutputComp',dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,
        FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1),
        [zero,unit,clean_residual,unit,p[6],p[3],p[7],z],[10],(w,h))[0]
    t.check('clean RR does not regain reference grain',spread(out)<spread(raw)*.02,
            final_variance=spread(out),raw_variance=spread(raw))
    # Correlated RGB grain is closer to illumination noise than independent
    # channel noise. Repeat frames, including a low-frequency reflected ramp.
    y,x=np.indices((h,w));base=t.rgba(w,h,(.25,.32,.4))
    base[...,:3]+=(.025*np.sin(x*.035)+.018*np.cos(y*.045))[...,None]
    prior=[];current=[]
    for frame in range(4):
        raw=base.copy();raw[...,:3]+=rng.normal(0,.025,(h,w,1))
        f,z,g,ref=t.seed(raw,depth=depth,normal=normal,albedo=albedo)
        f=t.filter_floor(f,z,g,albedo);p=pack(raw,f,ref)
        prior.append(np.minimum(f[...,:3],raw[...,:3])[roi])
        current.append(p[6][roi])
    old_flicker=float(np.mean(np.var(prior,axis=0)))
    flicker=float(np.mean(np.var(current,axis=0)))
    t.check('luminance grain flicker through full Skip chain',flicker<old_flicker*.4,
            current_variance=flicker,hard_ceiling_variance=old_flicker)
    # Noisy lettering cannot use exact-colour neighbour protection. Its dark
    # strokes still must not be filled by uncertainty from the bright surround.
    ink=(x%9==4)&(y>6)&(y<h-7)
    clean=t.rgba(w,h,(.8,.8,.8));clean[ink,:3]=.04
    raw=clean.copy();raw[...,:3]+=rng.normal(0,.015,(h,w,3))
    f,z,g,ref=t.seed(raw,depth=depth,normal=normal,albedo=albedo)
    f=t.filter_floor(f,z,g,albedo);p=pack(raw,f,ref)
    lift=float(np.mean(np.maximum(p[6][ink,:3]-.04,0)))
    t.check('noisy dark lettering retains pedestal contrast',lift<.025,mean_positive_lift=lift)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks),'Skip grain regression'


if __name__=='__main__':run()
