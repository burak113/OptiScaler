"""Independent colour/luminance targets for the production chromatic recovery.

Synthetic RR can lose colour contrast while keeping sharp luminance. It must
not authorize adding unrelated colour grain or replace the current palette.
Optional --baseline compares the previously delivered shader on identical inputs.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_stage_probe as p
from test_fsrd_panel_recovery import blur

LUMA=np.array([.2126,.7152,.0722])


def run(baseline=None):
    t.OUT=t.OUT.parent/'chroma_recovery'; t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=81,65; y,x=np.indices((h,w)); crop=(slice(8,-8),slice(8,-8))
    white=t.rgba(w,h,(1,1,1)); zero=t.rgba(w,h,(0,0,0))
    normal=t.rgba(w,h,(.5,.5,.1),1/3);depth=np.full((h,w),10,np.float32)
    values={'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':1.0,'FloorHandoverAnchorClamp':4,'FloorHandoverCorrelationMix':1}
    records=[]

    def pattern(scale, textured=True, phase=0):
        target=t.rgba(w,h,(.45,.45,.45))
        if textured:
            target[...,:3]+=(.15*np.sin(x*1.1)*np.cos(y*.65)+.12*np.sin(y*.87+x*.38))[...,None]
        red=.13*np.sin(x/scale*.9+y/scale*.35+phase)
        blue=.13*np.sin(y/scale*.8-x/scale*.3-phase)
        target[...,0]+=red; target[...,2]+=blue
        target[...,1]-=(red*LUMA[0]+blue*LUMA[2])/LUMA[1]
        return target

    def error(image,target):
        delta=(image[...,:3]-target[...,:3])[crop]
        lum=delta@LUMA
        return {'rgb':float(np.sqrt(np.mean(delta**2))),
                'chroma':float(np.sqrt(np.mean((delta-lum[...,None])**2))),
                'luma':float(np.sqrt(np.mean(lum**2)))}

    def inputs(rr,raw):
        return [zero,white,rr,white,zero,normal,t.seed(raw)[3],depth]

    # Colour blur with independently sharp luminance, at several spatial scales
    # and with held-out fine noise. Ground truth is generated before either filter.
    for scale in (1,2):
        for textured in (False,True):
            for sigma in (0,.025):
                target=pattern(scale,textured)
                rr=blur(target,3)
                rr[...,:3]+=(target[...,:3]@LUMA-rr[...,:3]@LUMA)[...,None]
                raw=target.copy(); raw[...,:3]+=np.random.default_rng(3700+scale).normal(0,sigma,(h,w,3))
                ins=inputs(rr,raw)
                out=p.dispatch(values,ins)
                e=error(out,target);r=error(rr,target)
                label=f'colour blur scale={scale} luma_texture={textured} sigma={sigma}'
                row={'case':label,'current':e,'rr':r}
                t.check(label+' bounded colour error',e['chroma']<=r['chroma']+.0003,**row)
                t.check(label+' sharp luminance retained',e['luma']<.0015,**row)
                encoded=p.dispatch(values,ins,'chroma_recovery')[...,:3]
                t.check(label+' diagnostic unsaturated',np.all((encoded>0)&(encoded<1)))
                stored_luma=np.maximum(rr[...,:3].astype(np.float16).astype(np.float32)@LUMA,1e-3)
                delta=(encoded-.5)*stored_luma[...,None]
                # The display texture is FP16. Allow one conversion ULP per
                # channel; do not assume the shader's half conversion rounds to
                # nearest like NumPy's fixture encoder. Scale that display error
                # back to radiance before testing the zero-luminance contract.
                ulp=np.spacing(encoded.astype(np.float16)).astype(np.float32)
                rounding=((ulp@LUMA)+2e-7)*stored_luma
                luma_error=np.abs(delta@LUMA)
                t.check(label+' additional recovery has zero luminance within FP16 readback',
                        np.all(luma_error<=rounding),max_error=float(np.max(luma_error)),
                        max_rounding_bound=float(np.max(rounding)))
                anchored=p.dispatch(values,ins,'anchor')
                low=np.minimum(rr[...,:3],anchored[...,:3]);hi=np.maximum(rr[...,:3],anchored[...,:3])
                handover=p.dispatch(values,ins,'before_clamp')[...,:3]
                t.check(label+' handover stays within RR and anchored candidate before grain cleanup',
                        np.all(handover>=low-.001) and np.all(handover<=hi+.001))
                if sigma==0 and scale==1:
                    t.check(label+' recovers at least a quarter of colour error',e['chroma']<r['chroma']*.75,**row)
                if baseline:
                    old=p.dispatch(values,ins,directory=baseline);row['previous']=error(old,target)
                    t.check(label+' no regression against delivered build',e['chroma']<=row['previous']['chroma']+.0003,**row)
                    if sigma==0:
                        ratio=.8 if scale==1 else .98
                        t.check(label+' improves delivered colour contrast',e['chroma']<row['previous']['chroma']*ratio,**row)
                records.append(row)

    # Correlated low-frequency noise and independent fine noise around a correct
    # RR, over multiple exposures. Include structure to avoid a flat Anchor
    # trivially masking a restoration leak.
    for level in (.02,1,16):
        for frame in range(3):
            target=pattern(1.7,True,frame*.3);target[...,:3]*=level
            rng=np.random.default_rng(6217+frame)
            noise=t.rgba(w,h,(0,0,0));noise[...,:3]=rng.normal(0,1,(h,w,3))
            coarse=blur(noise,6)[...,:3];coarse*=.055*level/np.std(coarse)
            raw=target.copy();raw[...,:3]=np.maximum(raw[...,:3]+coarse+rng.normal(0,.025*level,(h,w,3)),0)
            ins=inputs(target,raw);out=p.dispatch(values,ins)
            e=error(out,target);e={k:v/level for k,v in e.items()}
            label=f'correct RR colour grain exposure={level} frame={frame}'
            row={'case':label,'current_normalized':e}
            t.check(label+' finite and nonnegative',np.all(np.isfinite(out)) and np.all(out[...,:3]>=0))
            t.check(label+' noise remains below contaminated reference',e['rgb']<.022,**row)
            if baseline:
                old=error(p.dispatch(values,ins,directory=baseline),target)
                row['previous_normalized']={k:v/level for k,v in old.items()}
                t.check(label+' grain error bounded against delivered build',
                        e['rgb']<=max(old['rgb']/level*1.05,.0003),**row)
            records.append(row)

    # New/shifted palettes are not a gain of the old screen. Record quality
    # against the current frame and disallow regression, including a hue swap.
    old=pattern(1.3)
    for phase in (0,1.2,3.14):
        target=pattern(1.3,True,phase);rr=blur(old,3);ins=inputs(rr,target)
        out=p.dispatch(values,ins);e=error(out,target)
        if baseline:
            previous=error(p.dispatch(values,ins,directory=baseline),target)
            t.check(f'animated colour phase={phase} stays responsive',e['rgb']<=previous['rgb']+.0003,
                    current=e,previous=previous)
        t.check(f'animated colour phase={phase} finite',np.all(np.isfinite(out)) and np.all(out[...,:3]>=0))

    # No gain can be inferred from neutral RR, opposite colour patterns or a
    # perfect reconstruction. Additional chromatic correction must be zero.
    target=pattern(1,False)
    for label,rr,raw in [('neutral RR',t.rgba(w,h,(.45,.45,.45)),target),
                         ('already sharp',target,target),
                         ('opposite palette',target,pattern(1,False,np.pi))]:
        ins=inputs(rr,raw);encoded=p.dispatch(values,ins,'chroma_recovery')
        t.check(label+' no unsupported colour gain',np.max(np.abs(encoded[...,:3]-.5))<.0005)

    target=pattern(1);rr=blur(target,3);ins=inputs(rr,target)
    ordinary=[a.copy() for a in ins];ordinary[5][...,3]=0
    t.check('ordinary surfaces receive no chroma recovery',
            np.all(p.dispatch(values,ordinary,'chroma_recovery')[...,:3]==.5))
    for label,change in [('routed',lambda v,i:i[6].__setitem__((Ellipsis,3),-1)),
                         ('detail off',lambda v,i:v.update(DetailPreservation=0)),
                         ('mix off',lambda v,i:v.update(FloorHandoverCorrelationMix=0))]:
        v=dict(values);i=[a.copy() for a in ins];change(v,i)
        t.check(label+' chroma addition disabled exactly',np.all(p.dispatch(v,i,'chroma_recovery')[...,:3]==.5))
        if baseline:
            t.check(label+' output identical to delivered build',np.array_equal(p.dispatch(v,i),p.dispatch(v,i,directory=baseline)))

    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings,'records':records},indent=2))
    assert all(c['passed'] for c in t.checks),'chroma recovery regression'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path)
    run(parser.parse_args().baseline)
