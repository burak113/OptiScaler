"""Final-composition contrast with independent blur, lighting and noise targets.

Runs production DXIL; the RR input is synthetic, not AMD inference. Optional
baseline is the previous chroma-recovery delivery. No screenshot is a target.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_stage_probe as p
from test_fsrd_panel_recovery import blur
from test_fsrd_stage_diagnostics import fixture


def run(baseline=None):
    t.OUT=t.OUT.parent/'luma_recovery';t.OUT.mkdir(parents=True,exist_ok=True);t.build_runner()
    w,h=81,65;y,x=np.indices((h,w));crop=(slice(8,-8),slice(8,-8),slice(0,3))
    a=t.rgba(w,h,(1,1,1));zero=t.rgba(w,h,(0,0,0));n=t.rgba(w,h,(.5,.5,.1),1/3)
    depth=np.full((h,w),10,np.float32)
    v={'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':1.0,'FloorHandoverAnchorClamp':4,'FloorHandoverCorrelationMix':1}
    records=[]
    def pattern(bright=False,phase=0):
        out=t.rgba(w,h,(0,0,0))
        mean,first,second=(8,.8,.4) if bright else (.5,.18,.10)
        out[...,:3]=(mean+first*np.sin(x*.63+y*.23+phase)+second*np.sin(y*.81-x*.38-phase))[...,None]
        return out
    def inputs(rr,raw):return [zero,a,rr,a,zero,n,t.seed(raw)[3],depth]
    def rms(out,target):return float(np.sqrt(np.mean((out[crop]-target[crop])**2)))

    # This is precisely the reported stage failure: a sharp reference/Anchor,
    # but overly blurred composition. Cover low contrast on bright backgrounds.
    for bright in (False,True):
        for level in (.02,1,32):
            target=pattern(bright);target[...,:3]*=level;rr=blur(target,3);i=inputs(rr,target)
            ref=p.dispatch(v,i,'reference');g=p.dispatch(v,i,'anchor')
            before=p.dispatch(v,i,'before_clamp');out=p.dispatch(v,i)
            label=f'final contrast bright={bright} exposure={level}'
            row={'case':label,'reference':rms(ref,target)/level,'anchor':rms(g,target)/level,
                 'rr':rms(rr,target)/level,'final':rms(out,target)/level,
                 'clamp_max_change':float(np.max(np.abs(before-out)))/level}
            t.check(label+' reference and Anchor remain sharp',row['reference']<.003 and row['anchor']<.003,**row)
            t.check(label+' final improves RR contrast',row['final']<row['rr']*.8,**row)
            if level>=1:
                t.check(label+' final restores most of the lost contrast',row['final']<row['rr']*.4,**row)
            t.check(label+' final clamp not responsible for blur',row['clamp_max_change']<.001,**row)
            t.check(label+' finite radiance',np.all(np.isfinite(out)) and np.all(out[...,:3]>=0))
            stored_rr=rr[...,:3].astype(np.float16).astype(np.float32)
            # The candidate diagnostic and final radiance are independently
            # converted to FP16. Bound their conversion error in ULPs, including
            # bright backgrounds whose absolute ULP exceeds 0.001*exposure.
            largest=np.maximum(np.abs(stored_rr),np.abs(g[...,:3]))
            slack=2*np.abs(np.spacing(largest.astype(np.float16)).astype(np.float32))+1e-7
            handover=p.dispatch(v,i,'before_clamp')[...,:3]
            t.check(label+' handover RGB stays inside anchored interval',
                    np.all(handover>=np.minimum(stored_rr,g[...,:3])-slack) and
                    np.all(handover<=np.maximum(stored_rr,g[...,:3])+slack))
            weights=p.dispatch(v,i,'weights')[...,:3]
            extra_c=p.dispatch(v,i,'chroma_recovery')[...,:3]
            extra_l=p.dispatch(v,i,'luma_recovery')[...,:3]
            t.check(label+' restoration diagnostics unsaturated',
                    np.all((extra_c>0)&(extra_c<1)) and np.all((extra_l>0)&(extra_l<1)))
            lum=np.maximum(stored_rr@np.array([.2126,.7152,.0722]),1e-3)
            reconstructed=stored_rr+np.prod(weights,axis=2)[...,None]*(g[...,:3]-stored_rr)+\
                (extra_c+extra_l-1.0)*lum[...,None]
            # Bound every independently quantized readback used in the public
            # reconstruction equation, rather than imposing an exposure-only
            # tolerance which is smaller than one ULP on bright backgrounds.
            ulp=lambda a:np.abs(np.spacing(a.astype(np.float16)).astype(np.float32))
            weight_error=np.sum(ulp(weights),axis=2)[...,None]
            diagnostic_bound=weight_error*np.abs(g[...,:3]-stored_rr)+\
                ulp(g[...,:3])*(np.prod(weights,axis=2)[...,None]+weight_error)+\
                (ulp(extra_c)+ulp(extra_l))*lum[...,None]+ulp(before[...,:3])+1e-6*level
            diagnostic_error=np.abs(reconstructed-before[...,:3])
            t.check(label+' stage readbacks explain actual final mix',np.all(diagnostic_error<=diagnostic_bound),
                    max_normalized_error=float(np.max(diagnostic_error))/level,
                    max_normalized_storage_bound=float(np.max(diagnostic_bound))/level)
            if baseline:
                old=p.dispatch(v,i,directory=baseline);row['previous']=rms(old,target)/level
                t.check(label+' improves previous delivered build',row['final']<row['previous']*.9,**row)
            records.append(row)

    # A pure illumination/exposure gain is not evidence of blur. This must not
    # turn the new contrast path into a way to amplify lighting grain.
    target=pattern()
    for gain in (1,1.1,1.3):
        raw=target.copy();raw[...,:3]*=gain;i=inputs(target,raw)
        encoded=p.dispatch(v,i,'luma_recovery')
        error=float(np.max(np.abs(encoded[...,:3]-.5)))
        t.check(f'uniform lighting gain={gain} is not contrast loss',error<.0005,max_display_delta=error)

    # Correct RR with both additive and multiplicative coarse illumination
    # grain. A constant RR would let Anchor hide a broken recovery estimator.
    for kind in ('additive','multiplicative'):
        for level in (.02,1,32):
            for frame in range(2):
                target=pattern(phase=frame*.17);target[...,:3]*=level
                rng=np.random.default_rng(8871+frame)
                field=t.rgba(w,h,(0,0,0));field[...,:3]=rng.normal(0,1,(h,w,3))
                coarse=blur(field,8)[...,:3];coarse/=np.std(coarse)
                raw=target.copy()
                if kind=='additive':raw[...,:3]+=.065*level*coarse
                else:raw[...,:3]*=np.clip(1+.16*coarse,.4,1.6)
                raw[...,:3]=np.maximum(raw[...,:3]+rng.normal(0,.02*level,(h,w,3)),0)
                i=inputs(target,raw);out=p.dispatch(v,i)
                err=rms(out,target)/level
                row={'case':f'{kind} grain exposure={level} frame={frame}','error':err}
                t.check(row['case']+' keeps lighting noise suppressed',err<.020,**row)
                if baseline:
                    old=p.dispatch(v,i,directory=baseline);row['previous']=rms(old,target)/level
                    t.check(row['case']+' no material grain regression',err<=max(row['previous']*1.05,.0005),**row)
                records.append(row)

    # Animated artwork need not have any correspondence to the previous RR.
    # Anti-correlated data, constant RR and a constant reference supply no gain.
    target=pattern();rr=blur(target,3)
    for label,r,raw in [('flat RR',t.rgba(w,h,(.5,.5,.5)),target),
                       ('flat reference',target,t.rgba(w,h,(.5,.5,.5))),
                       ('opposite pattern',target,pattern(phase=np.pi))]:
        i=inputs(r,raw)
        t.check(label+' no unsupported extra luminance',np.max(np.abs(p.dispatch(v,i,'luma_recovery')[...,:3]-.5))<.0005)
    for phase in (1.1,2.2):
        target=pattern(phase=phase);i=inputs(rr,target);out=p.dispatch(v,i)
        if baseline:
            old=p.dispatch(v,i,directory=baseline)
            t.check(f'new animation phase={phase} not replaced by old pattern',rms(out,target)<=rms(old,target)+.0005,
                    current=rms(out,target),previous=rms(old,target))

    # Shared luma/chroma budget must also hold on coloured tiny glyphs. Do not
    # trade away the already accepted NLM and chroma improvements.
    for scale in (1,2,3):
        for noisy in (False,True):
            vv,ii,clean,raw,ink=fixture(scale,noisy)
            result=p.dispatch(vv,ii);anchor=p.dispatch(vv,ii,'anchor');rr2=ii[2]
            handover=p.dispatch(vv,ii,'before_clamp')[...,:3]
            t.check(f'combined colour/luma anchored range before grain cleanup scale={scale} noisy={noisy}',
                    np.all(handover>=np.minimum(rr2[...,:3],anchor[...,:3])-.001) and
                    np.all(handover<=np.maximum(rr2[...,:3],anchor[...,:3])+.001))
            if baseline:
                old=p.dispatch(vv,ii,directory=baseline)
                e=float(np.sqrt(np.mean((result[...,:3]-clean[...,:3])**2)))
                oe=float(np.sqrt(np.mean((old[...,:3]-clean[...,:3])**2)))
                t.check(f'accepted glyph quality scale={scale} noisy={noisy}',e<=oe+.0003,current=e,previous=oe)

    target=pattern();i=inputs(blur(target,3),target)
    ordinary=[a.copy() for a in i];ordinary[5][...,3]=0
    t.check('ordinary surfaces receive no luma recovery',
            np.all(p.dispatch(v,ordinary,'luma_recovery')[...,:3]==.5))
    for label,change in [('routed',lambda v,i:i[6].__setitem__((Ellipsis,3),-1)),
                         ('detail off',lambda v,i:v.update(DetailPreservation=0)),
                         ('mix off',lambda v,i:v.update(FloorHandoverCorrelationMix=0))]:
        vv=dict(v);ii=[a.copy() for a in i];change(vv,ii)
        t.check(label+' extra luminance disabled exactly',np.all(p.dispatch(vv,ii,'luma_recovery')[...,:3]==.5))
        if baseline:
            t.check(label+' matches delivered output',np.array_equal(p.dispatch(vv,ii),p.dispatch(vv,ii,directory=baseline)))
    # Existing depth/normal/albedo/routing suites also check the broader support;
    # these degenerate extents specifically exercise its distinct sample count.
    for width,height in ((1,1),(1,9),(9,1),(7,5)):
        a=t.rgba(width,height,(1,1,1));z=t.rgba(width,height,(0,0,0));c=t.rgba(width,height,(.4,.4,.4))
        ref=t.rgba(width,height,(.4,.4,.4),.03);normal=t.rgba(width,height,(.5,.5,.1),1/3)
        vv=dict(v,DstTexSize=[width,height,1/width,1/height])
        out=p.dispatch(vv,[z,a,c,a,z,normal,ref,np.full((height,width),10,np.float32)])
        t.check(f'partial group {width}x{height} finite and constant',np.all(np.isfinite(out)) and np.max(np.abs(out[...,:3]-.4))<.001)

    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings,'records':records},indent=2))
    assert all(c['passed'] for c in t.checks),'final composition contrast regression'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path)
    run(parser.parse_args().baseline)
