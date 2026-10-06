"""Independent temporal evidence for detail absent from RR, with motion/noise controls.

Runs the production composition DXIL against known clean references. This does
not execute AMD's neural denoiser or certify Cyberpunk image quality.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run(reference=None, candidate=None, report_only=False):
    t.build_runner()
    w,h=65,49;y,x=np.indices((h,w));roi=(slice(8,-8),slice(8,-8),slice(0,3))
    zero=t.rgba(w,h,(0,0,0));a=t.rgba(w,h,(.8,.8,.8));d=t.rgba(w,h,(.2,.2,.2))
    n=t.rgba(w,h,(.5,.5,.4),0);z=np.full((h,w),10,np.float32)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=2,
        SpatialTemporalMask=2,WriteHistory=1,SpecularAlbedoDemodulation=0,DiffuseAlbedoModulation=0)
    variants=[('current',candidate or t.PRE)]+([('old_strong',reference)] if reference else [])
    rows=[]
    for case in ('missing','tiles','subpixel','chroma','sharp_static','sharp_subpixel'):
        histories={k:None for k,_ in variants};errors={k:[] for k,_ in variants};gains={k:[] for k,_ in variants}
        residuals={k:[] for k,_ in variants}
        for frame in range(24):
            shift=frame*.37 if 'subpixel' in case else 0
            clean=t.rgba(w,h,(.4,.45,.5),0)
            pattern=.1*np.sin((x-shift)*1.1)+.06*np.cos(y*.73)
            if case=='tiles':pattern=.12*((x//3+y//4)%2)*2-.12
            clean[...,:3]+=pattern[...,None]
            if case=='chroma':
                clean[...,:3]=(.4,.45,.5)
                clean[...,:3]+=np.stack((pattern,-pattern*.4,pattern*.2),axis=-1)
            rr=clean if case.startswith('sharp') else blur(clean,6)
            if case=='missing':rr[...,:3]=(.4,.45,.5)
            rng=np.random.default_rng(781731+frame)
            ref=clean.copy();ref[...,:3]+=rng.normal(0,.045 if case.startswith('sharp') else .01,(h,w,3))
            ref[...,3]=.006 if case.startswith('sharp') else .01
            mv=t.rgba(w,h,(-.37/w if 'subpixel' in case else 0,0,0),1)
            inputs=[zero,a,rr,d,zero,n,ref,z,mv,zero,np.zeros((h,w,4),np.uint32)]
            for key,path in variants:
                old=histories[key];inputs[9:]=[zero,np.zeros((h,w,4),np.uint32)] if old is None else old[1:]
                out=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(old is not None)),inputs,[10,10,3],(w,h),directory=path)
                histories[key]=out
                if frame>=8:
                    delta=out[0][roi]-clean[roi];errors[key].append(float(np.mean(delta**2)));residuals[key].append(delta)
                    signal=clean[roi]-np.mean(clean[roi],axis=(0,1),keepdims=True)
                    gains[key].append(float(np.sum((out[0][roi]-np.mean(out[0][roi],axis=(0,1),keepdims=True))*signal)/max(np.sum(signal**2),1e-6)))
        row=dict(case=case,rr_mse=float(np.mean((rr[roi]-clean[roi])**2)))
        for key,_ in variants:
            row[key+'_mse']=float(np.mean(errors[key]));row[key+'_contrast']=float(np.mean(gains[key]))
            row[key+'_residual_change']=float(np.mean(np.diff(residuals[key],axis=0)**2))
        rows.append(row);print(json.dumps(row),flush=True)
        if case.startswith('sharp'):
            t.check(case+' does not significantly contaminate sharp RR',row['current_mse']<.0001,**row)
        else:
            t.check(case+' substantial contrast restored',row['current_contrast']>.67,**row)
            t.check(case+' lower error than blurred RR',row['current_mse']<row['rr_mse']*.25,**row)
            if reference:t.check(case+' approaches old strong recovery',row['current_contrast']>=row['old_strong_contrast']*.9,**row)
        # Mature moments must not survive newly revealed geometry or a scene cut.
        for reason,index,value in [('depth',7,z+5),('motion',8,zero),('animation',6,t.rgba(w,h,(1.5,.1,.2),.01))]:
            altered=list(inputs);altered[index]=value;altered[9:]=histories['current'][1:]
            mapped=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=1),altered,[10,10,3],(w,h),directory=candidate or t.PRE)
            fresh=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=0),altered,[10,10,3],(w,h),directory=candidate or t.PRE)
            t.check(case+' mature moments reject '+reason,np.array_equal(mapped[0],fresh[0]))
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,records=rows,dispatches=t.timings),indent=2))
    if not report_only:assert all(c['passed'] for c in t.checks),'temporal detail evidence regression'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path);p.add_argument('--candidate',type=Path);p.add_argument('--report-only',action='store_true')
    a=p.parse_args();run(a.reference,a.candidate,a.report_only)
