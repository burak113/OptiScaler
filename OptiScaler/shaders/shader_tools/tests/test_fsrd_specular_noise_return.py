"""Specular-only recovery must not turn already denoised surfaces into raw noise.

Unlike the improvement-only fixture, absolute noise-return budgets apply even
when alpha underestimates noise and motion rejects history on every frame.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run(reference=None,report_only=False):
    t.build_runner()
    w,h=65,49;y,x=np.indices((h,w));roi=(slice(8,-8),slice(8,-8),slice(0,3))
    zero=t.rgba(w,h,(0,0,0));a=t.rgba(w,h,(.8,.8,.8));d=t.rgba(w,h,(.2,.2,.2))
    n=t.rgba(w,h,(.5,.5,.4),0);z=np.full((h,w),10,np.float32)
    motion=t.rgba(w,h,(0,0,0),1)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=2,SpatialTemporalMask=2,
        WriteHistory=1,SpecularAlbedoDemodulation=0,DiffuseAlbedoModulation=0,
        FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,LumaRecovery=1,ChromaRecovery=1)
    variants=[('current',t.PRE)]+([('baseline',reference)] if reference else [])
    records=[]
    for case in ('grain_static','grain_motion','grain_reject','zero_alpha','coarse_reject','smooth_zero_alpha','impulse_reject','shared_noise','detail'):
        clean=t.rgba(w,h,(.32,.35,.38),0)
        clean[...,:3]+=(.008*np.sin(x*.23)+.012*np.cos(y*.19))[...,None]
        if case=='detail':
            clean[...,:3]+=(.12*np.sin(x*.63)+.1*np.cos(y*.37))[...,None]
        origin=clean.copy()
        rr=blur(clean,4) if case=='detail' else clean
        rr_errors=[]
        histories={key:None for key,_ in variants};errors={key:[] for key,_ in variants}
        peaks={key:[] for key,_ in variants};changes={key:[] for key,_ in variants}
        for frame in range(16):
            if case=='grain_motion':
                clean=np.roll(origin,frame,axis=1);rr=clean
            rng=np.random.default_rng(90917+frame)
            ref=clean.copy();ref[...,:3]+=rng.normal(0,.06,(h,w,3));ref[...,3]=.006
            if case=='zero_alpha':ref[...,3]=0
            if case=='detail':
                ref=clean.copy();ref[...,:3]+=rng.normal(0,.01,(h,w,3));ref[...,3]=.01
            if case in ('coarse_reject','smooth_zero_alpha'):
                field=t.rgba(w,h,(0,0,0));field[...,:3]=rng.normal(0,1,(h,w,1))
                grain=blur(field,10)[...,:3];grain*=.055/np.std(grain[roi])
                if case=='smooth_zero_alpha':ref=clean.copy();ref[...,3]=0
                ref[...,:3]+=grain
            if case=='impulse_reject':
                ref[...,:3]+=(rng.random((h,w))<.04)[...,None]*rng.uniform(.25,.6,(h,w,1))
            mv=motion.copy()
            if case=='grain_motion':mv[...,0]=-1/w
            if case=='shared_noise':rr=clean+.25*(ref-clean)
            if 'reject' in case or case in ('zero_alpha','smooth_zero_alpha'):mv[...,3]=0
            rr_errors.append(float(np.mean((rr[roi]-clean[roi])**2)))
            for key,path in variants:
                old=histories[key]
                inputs=[zero,a,rr,d,zero,n,ref,z,mv,
                    t.rgba(w,h,(-1,-1,-1),-1) if old is None else old[1],
                    np.zeros((h,w,4),np.uint32) if old is None else old[2]]
                out=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(old is not None)),inputs,[10,10,3],(w,h),directory=path)
                histories[key]=out
                delta=out[0][roi]-clean[roi]
                errors[key].append(float(np.mean(delta**2)))
                peaks[key].append(float(np.percentile(abs(delta),99)))
                changes[key].append(delta)
        row=dict(case=case,rr_mse=float(np.mean(rr_errors)))
        for key,_ in variants:
            row[key+'_mse']=float(np.mean(errors[key]));row[key+'_p99']=float(np.mean(peaks[key]))
            row[key+'_flicker']=float(np.mean(np.diff(changes[key],axis=0)**2))
        records.append(row);print(json.dumps(row),flush=True)
        if case=='detail':
            t.check('supported detail improves blurred RR',row['current_mse']<row['rr_mse']*.65,**row)
        elif case=='shared_noise':
            t.check('shared residual noise is not amplified',row['current_mse']<row['rr_mse']*1.05,**row)
        else:
            t.check(case+' absolute noise return bounded',row['current_mse']<.000025 and row['current_p99']<.02,**row)
            if reference:t.check(case+' noise return reduced',row['current_mse']<row['baseline_mse']*.25,**row)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,records=records),indent=2))
    if not report_only:assert all(c['passed'] for c in t.checks),'specular noise return regression'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path);p.add_argument('--report-only',action='store_true')
    args=p.parse_args();run(args.reference,args.report_only)
