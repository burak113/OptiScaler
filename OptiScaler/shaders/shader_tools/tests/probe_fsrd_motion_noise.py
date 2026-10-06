"""Subpixel motion + independently changing illumination: actual Floor DXIL.

The target is known analytically at each frame. Error differences remove true
animation/camera motion; these are synthetic temporal-error proxies, not game
flicker scores. RR is an explicit clean/blurred mock, not the AMD model.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_zero_rough_screen import chain_cb, blur


def run():
    t.OUT=t.OUT.parent/'motion_noise';t.OUT.mkdir(parents=True,exist_ok=True)
    t.runner=t.OUT/'fsrd_gpu_runner.exe';t.build_runner()
    w,h=65,49
    y,x=np.indices((h,w),dtype=np.float32)
    normal=t.rgba(w,h,(0,0,1));zero=t.rgba(w,h,(0,0,0))
    spec=t.rgba(w,h,(.04,.04,.04));ones=t.rgba(w,h,(1,1,1))
    crop=(slice(7,-7),slice(7,-7),slice(0,3))
    rng=np.random.default_rng(109071)
    for kind in ('flat','glyph','silhouette'):
        for material in ('ordinary','screen'):
            errors=[];input_errors=[];reference_errors=[];pedestal_excess=[]
            selected=[];sharp_errors=[];blur_errors=[];sharp_clean_errors=[]
            worst=-1
            for frame in range(8):
                sx=x-.17*frame;sy=y-.11*frame
                clean=t.rgba(w,h,(.18,.22,.26))
                if kind!='flat':
                    # Antialiased curved strokes, short ends, equal-luma colours.
                    distance=np.abs(np.sin(sx*.28+np.sin(sy*.16)))*3.5
                    stroke=np.clip(1.4-distance,0,1)
                    clean[...,:3]+=stroke[...,None]*np.array([.5,.12,.31])
                z=np.full((h,w),10,np.float32)
                a=t.rgba(w,h,(.7,.7,.7))
                if material=='ordinary':
                    a[...,:3]+=(.1*np.sin(sx*.6)+.06*np.cos(sy*.7))[...,None]
                if kind=='silhouette':
                    edge=sx>32
                    z[edge]=30;clean[edge,:3]*=.35
                raw=clean.copy()
                raw[...,:3]=np.maximum(raw[...,:3]+rng.normal(0,.008,(h,w,3)),0)
                rays=rng.random((h,w))<.025
                raw[rays,:3]+=rng.uniform(.08,.7,(rays.sum(),3))
                f,d,g,ref=t.seed(raw,depth=z,normal=normal,albedo=a)
                f=t.filter_floor(f,d,g,a)
                rough=np.full((h,w),0 if material=='screen' else .5,np.float32)
                packed=t.dispatch('FSRDInputConv',chain_cb(w,h,(1<<1)|(1<<7)),
                    [raw,d,zero,normal,rough,z,a,spec,zero,f,zero,zero,zero,zero,z,zero,ref],
                    [10,10,10,24,28,28,10,10],(w,h))
                def compose(target,reference=packed[7]):
                    rr=target.copy();rr[...,:3]=np.maximum(target[...,:3]-packed[6][...,:3],0)
                    return t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
                        'DetailPreservation':1.0,'NoiseSuppression':.75,
                        'FloorHandoverAnchorClamp':4,'FloorHandoverCorrelationMix':1},
                        [zero,ones,rr,ones,packed[6],packed[3],reference,d],[10],(w,h))[0]
                out=compose(clean)
                error=out[crop]-clean[crop]
                peak=float(np.max(np.abs(error)))
                if peak>worst:
                    worst=peak
                    np.savez_compressed(t.OUT/f'{kind}_{material}_worst.npz',
                        frame=frame,raw=raw,clean=clean,output=out,depth=d,
                        floor=f,reference=ref,albedo=a,**{f'packed{i}':v for i,v in enumerate(packed)})
                errors.append(error);input_errors.append(raw[crop]-clean[crop])
                reference_errors.append(ref[crop]-clean[crop])
                pedestal_excess.append(np.maximum(packed[6][crop]-clean[crop],0))
                selected.append(float(np.mean(packed[3][...,3]>.16)))
                if kind=='glyph':
                    rr_blur=blur(clean,2)
                    restored=compose(rr_blur)
                    sharp_errors.append(float(np.mean((restored[crop]-clean[crop])**2)))
                    blur_errors.append(float(np.mean((rr_blur[crop]-clean[crop])**2)))
                    # Independent clean seed ensures optimizations also preserve
                    # fine texture at every subpixel phase, without relying on RR.
                    clean_ref=t.seed(clean,depth=z,normal=normal,albedo=a)[3]
                    sharp_clean_errors.append(float(np.max(np.abs(clean_ref[crop]-clean[crop]))))
            e=np.array(errors);raw_e=np.array(input_errors)
            row=dict(scene=kind,material=material,frames=8,
                output_rmse=float(np.sqrt(np.mean(e**2))),
                input_rmse=float(np.sqrt(np.mean(raw_e**2))),
                output_temporal_error=float(np.sqrt(np.mean(np.diff(e,axis=0)**2))),
                input_temporal_error=float(np.sqrt(np.mean(np.diff(raw_e,axis=0)**2))),
                positive_speckles=int(np.count_nonzero(np.max(e,axis=-1)>.04)),
                maximum_error=float(np.max(np.abs(e))),
                reference_rmse=float(np.sqrt(np.mean(np.array(reference_errors)**2))),
                maximum_pedestal_excess=float(np.max(pedestal_excess)),
                selected_fraction=selected)
            if sharp_errors:
                row.update(blurred_rr_mse=float(np.mean(blur_errors)),
                           restored_mse=float(np.mean(sharp_errors)),
                           clean_seed_max_error=float(np.max(sharp_clean_errors)))
            t.records.append(row)
            t.check(f'{kind}/{material} reduces independent ray error during subpixel motion',
                    row['output_rmse']<row['input_rmse'] and
                    row['output_temporal_error']<row['input_temporal_error'])
            print(json.dumps(row),flush=True)
    # An untracked animated screen can introduce a genuinely new one-pixel
    # colour while all neighbours still match RR. A residual-outlier veto can
    # suppress the rays above but erase this clean feature; guard that tradeoff.
    sx=x-.17*6;sy=y-.11*6
    rr=t.rgba(w,h,(.18,.22,.26))
    stroke=np.clip(1.4-np.abs(np.sin(sx*.28+np.sin(sy*.16)))*3.5,0,1)
    rr[...,:3]+=stroke[...,None]*np.array([.5,.12,.31])
    clean=rr.copy();clean[8,22,:3]=(.76,.45,.82)
    ref=t.seed(clean)[3]
    n=t.rgba(w,h,(.5,.5,.1),1/3);z=np.full((h,w),10,np.float32)
    out=t.compose(rr,ref,z,n,ones)
    error=float(np.linalg.norm(out[8,22,:3]-clean[8,22,:3]))
    t.check('new clean one-pixel screen colour is not discarded as isolated illumination',error<.25,error=error)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,records=t.records,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks)


if __name__=='__main__':run()
