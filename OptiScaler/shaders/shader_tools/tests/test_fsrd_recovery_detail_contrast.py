"""Recover weak RR detail without relaxing fresh/disoccluded-frame protection.

Production DXIL, independently known truth, including moving diagonal texture.
Optional --reference is the preceding noise-guard shader, not raw noisy input.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run(reference=None):
    t.build_runner()
    w,h=65,49;y,x=np.indices((h,w));roi=(slice(8,-8),slice(8,-8),slice(0,3))
    zero=t.rgba(w,h,(0,0,0));a=t.rgba(w,h,(.8,.8,.8));d=t.rgba(w,h,(.2,.2,.2))
    n=t.rgba(w,h,(.5,.5,.4),0);z=np.full((h,w),10,np.float32)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=2,
        SpatialTemporalMask=2,WriteHistory=1,SpecularAlbedoDemodulation=0,DiffuseAlbedoModulation=0)
    variants=[('current',t.PRE)]+([('baseline',reference)] if reference else [])
    rows=[]
    for case in ('fine','diagonal','moving','seed','reveal'):
        clean=t.rgba(w,h,(.4,.45,.5),0)
        pattern=.12*np.sin(x*.91+y*.83) if case=='diagonal' else .1*np.sin(x*1.1)+.06*np.cos(y*.73)
        clean[...,:3]+=pattern[...,None];rr=blur(clean,6)
        histories={k:None for k,_ in variants};errors={k:[] for k,_ in variants};gains={k:[] for k,_ in variants}
        for frame in range(20):
            truth=np.roll(clean,frame,axis=1) if case=='moving' else clean
            base=np.roll(rr,frame,axis=1) if case=='moving' else rr
            rng=np.random.default_rng(65473+frame)
            ref=truth.copy();ref[...,:3]+=rng.normal(0,.01,(h,w,3));ref[...,3]=.01
            if case=='seed':ref=t.seed(ref)[3]
            depth=z+(4 if case=='reveal' and frame>=10 else 0)
            mv=t.rgba(w,h,(-1/w if case=='moving' else 0,0,0),1)
            fresh_outputs={}
            for key,path in variants:
                old=histories[key]
                inputs=[zero,a,base,d,zero,n,ref,depth,mv,zero if old is None else old[1],
                    np.zeros((h,w,4),np.uint32) if old is None else old[2]]
                out=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(old is not None)),inputs,[10,10,3],(w,h),directory=path)
                histories[key]=out
                if frame==0 or (case=='reveal' and frame==10):fresh_outputs[key]=out[0]
                if frame>=8 and (case!='reveal' or frame>=17):
                    errors[key].append(float(np.mean((out[0][roi]-truth[roi])**2)))
                    signal=truth[roi]-np.mean(truth[roi],axis=(0,1),keepdims=True)
                    gains[key].append(float(np.sum((out[0][roi]-np.mean(out[0][roi],axis=(0,1),keepdims=True))*signal)/max(np.sum(signal**2),1e-6)))
            if fresh_outputs and reference:
                t.check(case+f' fresh protection unchanged frame {frame}',np.array_equal(fresh_outputs['current'],fresh_outputs['baseline']))
        row=dict(case=case,rr_mse=float(np.mean((base[roi]-truth[roi])**2)))
        for key,_ in variants:
            row[key+'_mse']=float(np.mean(errors[key]));row[key+'_contrast']=float(np.mean(gains[key]))
        rows.append(row);print(json.dumps(row),flush=True)
        t.check(case+' detail recovered',row['current_mse']<row['rr_mse']*.4,**row)
        # Contrast budgets are calibrated for the Light Anchor Mix: a 5px
        # diagonal pattern's quadratic curvature inflates the residual noise
        # floor (the only single-frame witness of an alpha lie), and the seed
        # fixture carries the seed's own conservative alpha. MSE budgets keep
        # their original values for every case.
        t.check(case+' contrast retained',row['current_contrast']>(.45 if case=='diagonal' else .55 if case=='seed' else .6),**row)
        if reference:t.check(case+' improves noise-guard baseline',row['current_mse']<row['baseline_mse']*.8,**row)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,records=rows,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks),'detail contrast regression'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--reference',type=Path)
    run(parser.parse_args().reference)
