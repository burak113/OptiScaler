# HISTORICAL: removed production feature; excluded from validate_fsrd.py.
"""Fine structure/noise separation in the production zero-rough reference filter.

Current-only contracts plus optional explicit pre-fix CSO comparisons. The RR
images are synthetic. No screenshot is treated as clean linear ground truth.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_stage_probe as p
from test_fsrd_stage_diagnostics import fixture
from test_fsrd_panel_recovery import blur


def run(baseline=None):
    t.OUT=t.OUT.parent/'nlm_detail';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    records=[]
    for scale in (1,2,3):
        for noisy in (False,True):
            values,inputs,target,raw,ink=fixture(scale,noisy)
            rows,cols=np.where(ink)
            crop=(slice(rows.min()-2,rows.max()+3),slice(cols.min()-2,cols.max()+3),slice(0,3))
            label=f'colour lettering scale={scale} noisy={noisy}'
            rms=lambda image:float(np.sqrt(np.mean((image[crop]-target[crop])**2)))
            ref=p.dispatch(values,inputs,'reference');out=p.dispatch(values,inputs)
            result={'case':label,'seed_rmse':rms(inputs[6]),'reference_rmse':rms(ref),
                    'composition_rmse':rms(out),'rr_rmse':rms(inputs[2])}
            if not noisy:
                # The 2px fixture already loses a small bright cluster in the
                # seed's existing firefly guard. This NLM change must preserve
                # the seed it receives; keep truth error in the record as well.
                added=float(np.sqrt(np.mean((ref[crop]-inputs[6][crop])**2)))
                t.check(label+' NLM preserves clean seed contrast',added<.003,added_rmse=added,**result)
            else:
                t.check(label+' noisy reference remains bounded',rms(ref)<.060,**result)
            t.check(label+' normal output improves blurred RR at Anchor4 Mix1',rms(out)<rms(inputs[2])*.85,**result)
            if baseline:
                oldref=p.dispatch(values,inputs,'reference',baseline);old=p.dispatch(values,inputs,directory=baseline)
                result.update(old_reference_rmse=rms(oldref),old_composition_rmse=rms(old))
                t.check(label+' reference does not regress from pre-fix',rms(ref)<=rms(oldref)+.001,**result)
                t.check(label+' final output does not regress from pre-fix',rms(out)<=rms(old)+.001,**result)
                if scale==1:
                    t.check(label+' final small-letter error drops at least 20 percent',rms(out)<rms(old)*.8,**result)
            records.append(result)

    # Held-out rotations and diagonal, partially-covered samples. Quantization
    # makes exact zero-noise claims inappropriate; compare to the clean fixture.
    w,h=69,53; y,x=np.indices((h,w)); depth=np.full((h,w),10,np.float32)
    a=t.rgba(w,h,(1,1,1));zero=t.rgba(w,h,(0,0,0));n=t.rgba(w,h,(.5,.5,.1),1/3)
    values={'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':1.0,'NoiseSuppression':.75,
            'FloorHandoverAnchorClamp':4,'FloorHandoverCorrelationMix':1}
    crop=(slice(7,-7),slice(7,-7),slice(0,3))
    for direction in (-1,1):
        # AA diagonal stripes superposed with short vertical strokes/colour areas.
        phase=(x+direction*y*.7)%9
        coverage=np.clip(1.5-np.minimum(phase,9-phase),0,1)
        target=t.rgba(w,h,(.6,.48,.38))
        target[...,:3]=target[...,:3]*(1-coverage[...,None])+np.array([.12,.25,.67])*coverage[...,None]
        ref=t.seed(target)[3];rr=blur(target,3)
        inputs=[zero,a,rr,a,zero,n,ref,depth]
        filtered=p.dispatch(values,inputs,'reference')
        error=float(np.sqrt(np.mean((filtered[crop]-target[crop])**2)))
        t.check(f'diagonal antialias reference bounded direction={direction}',error<.015,error=error)
        if baseline:
            old=p.dispatch(values,inputs,'reference',baseline)
            olderror=float(np.sqrt(np.mean((old[crop]-target[crop])**2)))
            t.check(f'diagonal reference does not regress direction={direction}',error<=olderror+.001,
                    old_error=olderror,new_error=error)

    # Multiple independent realizations. Evaluate the filter itself as well as
    # final composition, so an exact flat RR Anchor cannot hide reference grain.
    for level in (.02,.4,8):
        reference_errors=[];seed_errors=[];old_errors=[]
        for frame in range(3):
            rng=np.random.default_rng(4800+frame)
            clean=t.rgba(w,h,(level,level*.8,level*.6))
            noisy=clean.copy();noisy[...,:3]+=rng.normal(0,level*.08,(h,w,3))
            ref=t.seed(noisy)[3]
            inputs=[zero,a,clean,a,zero,n,ref,depth]
            rms=lambda image:float(np.sqrt(np.mean((image[crop]-clean[crop])**2)))/level
            filtered=p.dispatch(values,inputs,'reference')
            reference_errors.append(rms(filtered));seed_errors.append(rms(ref))
            out=p.dispatch(values,inputs)
            t.check(f'flat RR not contaminated exposure={level} frame={frame}',rms(out)<.001,error=rms(out))
            if baseline:
                old_errors.append(rms(p.dispatch(values,inputs,'reference',baseline)))
        mean=float(np.mean(reference_errors));seed_mean=float(np.mean(seed_errors))
        t.check(f'fine grain still filtered exposure={level}',mean<seed_mean*.6,
                seed_error=seed_mean,reference_error=mean)
        if baseline:
            previous=float(np.mean(old_errors))
            t.check(f'fine-grain reference error within five percent exposure={level}',mean<=previous*1.05+.0001,
                    old_error=previous,new_error=mean)
        records.append({'case':f'flat fine grain exposure={level}','reference_error':mean,'seed_error':seed_mean})

    # Hold every non-screen domain exact. Valid neighbor pairs must not cross a
    # surface boundary; the existing colour suite additionally covers normal,
    # albedo and explicit routing boundaries.
    values,inputs,target,raw,ink=fixture(1,True)
    for label,change in [('detail off',lambda v,i:v.update(DetailPreservation=0)),
                         ('noise suppression off',lambda v,i:v.update(NoiseSuppression=0)),
                         ('ordinary',lambda v,i:i[5].__setitem__((Ellipsis,3),0)),
                         ('routed',lambda v,i:i[6].__setitem__((Ellipsis,3),-1))]:
        v=dict(values);i=[image.copy() for image in inputs];change(v,i)
        if baseline:
            t.check(label+' bit identical to pre-fix',np.array_equal(p.dispatch(v,i),p.dispatch(v,i,directory=baseline)))
    for size in ((1,1),(1,9),(9,1),(7,5)):
        w,h=size;values=dict(values,DstTexSize=[w,h,1/w,1/h])
        a=t.rgba(w,h,(1,1,1));zero=t.rgba(w,h,(0,0,0));rr=t.rgba(w,h,(.4,.4,.4))
        ref=t.rgba(w,h,(.4,.4,.4),.03);n=t.rgba(w,h,(.5,.5,.1),1/3)
        result=p.dispatch(values,[zero,a,rr,a,zero,n,ref,np.full((h,w),10,np.float32)])
        t.check(f'degenerate and partial groups finite size={size}',np.all(np.isfinite(result)) and
                np.max(np.abs(result[...,:3]-.4))<.001)
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings,'records':records},indent=2))
    assert all(c['passed'] for c in t.checks),'NLM detail/noise contract regression'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path)
    run(parser.parse_args().baseline)
