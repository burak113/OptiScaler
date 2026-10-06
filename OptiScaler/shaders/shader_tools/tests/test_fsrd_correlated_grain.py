"""Production GPU Floor: correlated ray noise must not gain a stronger RR bypass.

Unlike independent pixel noise, coherent patches can fool a spatial light ridge
detector. The clean radiance and stochastic illumination are generated separately.
--report-only collects evidence before fixing a known failing shader.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur

def run(reference=None, report_only=False):
    t.OUT=t.OUT.parent/'correlated_grain';t.OUT.mkdir(parents=True,exist_ok=True);t.build_runner()
    w,h=65,49;roi=(slice(10,-10),slice(10,-10),slice(0,3))
    a=t.rgba(w,h,(.5,.5,.5));n=t.rgba(w,h,(0,0,1));z=np.full((h,w),10,np.float32)
    cb=dict(InvProjMatrix=np.eye(4).ravel(),RenderSize=[w,h,1/w,1/h],NearPlane=.1,FarPlane=1000,Flags=1,FloorEnabled=1)
    records=[]
    def floor(raw,pre):
        f,d,g,_=t.dispatch('FSRDFloorSeed',cb,[raw,n,z,z,a],[10,41,10,10],(w,h),pre)
        for step in (1,2,4,8,16):
            f=t.dispatch('FSRDFloor',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),[f,d,g,a],[10],(w,h),pre)[0]
        return f
    for scale in (2,5,12):
        variants=[('current',t.PRE)]+([('accepted',reference)] if reference else [])
        values={name:[] for name,_ in variants}
        for frame in range(8):
            rng=np.random.default_rng(3021+frame)
            field=t.rgba(w,h,(0,0,0));noise=rng.normal(0,1,(h,w,1))
            field[...,:3]=noise
            smooth=blur(field,scale)[...,0];smooth/=np.std(smooth[10:-10,10:-10])
            raw=t.rgba(w,h,(.12,.18,.24));raw[...,:3]+=np.maximum(smooth,0)[...,None]*[.06,.09,.12]
            for name,pre in variants:
                f=floor(raw,pre)
                # A perfect residual denoiser cannot remove excess already in Skip.
                excess=np.maximum(f[roi]-[.12,.18,.24],0)
                values[name].append(excess)
        row=dict(scale=scale)
        for name,v in values.items():
            row[name+'_rms']=float(np.sqrt(np.mean(np.square(v))))
            row[name+'_variation']=float(np.sqrt(np.mean(np.var(v,axis=0))))
        # Stored quality budgets for these fixed independent-noise fixtures;
        # wider correlated noise remains harder for the spatial pedestal.
        rms_budget,variation_budget={2:(.006,.004),5:(.013,.009),12:(.025,.018)}[scale]
        t.check(f'correlated grain scale {scale} bypass energy bounded',row['current_rms']<rms_budget,**row)
        t.check(f'correlated grain scale {scale} flicker bounded',row['current_variation']<variation_budget,**row)
        if reference:
            t.check(f'correlated positive grain scale {scale} no bypass regression',
                    row['current_rms']<=row['accepted_rms']*1.05+.0001,**row)
            t.check(f'correlated grain scale {scale} no flicker regression',
                    row['current_variation']<=row['accepted_variation']*1.05+.0001,**row)
        records.append(row)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,records=records),indent=2))
    if not report_only:assert all(c['passed'] for c in t.checks),'correlated Floor grain regression'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path);p.add_argument('--report-only',action='store_true')
    args=p.parse_args();run(args.reference,args.report_only)
