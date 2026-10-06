"""Spatial/temporal recovery: correlated noise, motion and disocclusion on real DXIL.

Known clean synthetic truth, not a claim about Cyberpunk/AMD RR image quality.
--reference compares an immutable previous production shader; --report-only audits.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run(reference=None, report_only=False, stability_reference=None):
    t.build_runner()
    w,h=65,49; y,x=np.indices((h,w)); roi=(slice(9,-9),slice(9,-9),slice(0,3))
    clean=t.rgba(w,h,(.4,.45,.5),0)
    clean[...,:3]+=(.09*np.sin(x*.67)+.06*np.cos(y*.19))[...,None]
    clean[...,1]+=.06*np.sin(x*.31+y*.45)
    rr=blur(clean,4)
    # Broad, stable denoiser damage AND missing fine detail must both recover.
    rr[...,:3]-=(.08*np.exp(-((x-32)**2+(y-24)**2)/170))[...,None]
    zero=t.rgba(w,h,(0,0,0)); a=t.rgba(w,h,(.5,.5,.5))
    n=t.rgba(w,h,(.5,.5,.4),0); z=np.full((h,w),10,np.float32)
    mv=t.rgba(w,h,(0,0,0),1)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=6,SpatialTemporalMask=6,
            WriteHistory=1,SpecularAlbedoDemodulation=0,DiffuseAlbedoModulation=0,
            FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,LumaRecovery=1,ChromaRecovery=1)
    records=[]
    stability={} if stability_reference is None else {r['case']:r for r in json.loads(stability_reference.read_text())['records']}
    variants=[('current',t.PRE)]+([('baseline',reference)] if reference else [])
    def shifted(image,shift):
        first=int(np.floor(shift));fraction=shift-first
        return (1-fraction)*np.roll(image,first,axis=1)+fraction*np.roll(image,first+1,axis=1)
    for case in ('static','pan','subpixel_pan','reveal','clean','stable_bias','upstream_seed'):
        histories={name:None for name,_ in variants}; errors={name:[] for name,_ in variants}
        residuals={name:[] for name,_ in variants}; early={name:[] for name,_ in variants}
        for frame in range(28):
            shift=frame if case=='pan' else frame*.5 if case=='subpixel_pan' else 0
            truth=shifted(clean,shift); base=shifted(rr,shift)
            rng=np.random.default_rng(48021+frame)
            field=t.rgba(w,h,(0,0,0),0);field[...,:3]=rng.normal(0,1,(h,w,1))
            grain=blur(field,12)[...,:3];grain*=.055/max(float(np.std(grain[roi])),1e-6)
            ref=truth.copy()
            if case not in ('clean','stable_bias'):
                ref[...,:3]+=grain+rng.normal(0,.012,(h,w,3));ref[...,3]=.012
            elif case=='stable_bias':
                ref[...,3]=.012  # Stable detail must not be judged noise by amplitude alone.
            if case=='upstream_seed':
                ref=t.seed(ref)[3]  # Exercise the real fine-noise estimator, not only fixed alpha.
            motion=mv.copy();motion[...,0]=-1/w if case=='pan' else -.5/w if case=='subpixel_pan' else 0
            depth=z+(4 if case=='reveal' and frame>=14 else 0)
            for name,directory in variants:
                old=histories[name]
                inputs=[zero,a,base,a,zero,n,ref,depth,motion,
                        t.rgba(w,h,(-1,-1,-1),-1) if old is None else old[1],
                        np.zeros((h,w,4),np.uint32) if old is None else old[2]]
                out=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(old is not None)),inputs,[10,10,3],(w,h),directory)
                histories[name]=out
                delta=out[0][roi]-truth[roi]
                if frame>=8:
                    errors[name].append(float(np.mean(delta**2)))
                    residuals[name].append(shifted(out[0]-truth,-shift)[roi])
                if frame in (0,14,15,16):early[name].append(float(np.mean(delta**2)))
        row=dict(case=case,rr_mse=float(np.mean((rr[roi]-clean[roi])**2)))
        for name,_ in variants:
            row[name+'_mse']=float(np.mean(errors[name]))
            row[name+'_flicker']=float(np.mean(np.diff(residuals[name],axis=0)**2))
            row[name+'_early_mse']=float(np.mean(early[name]))
        records.append(row);print(json.dumps(row),flush=True)
        t.check(case+' recovery improves damaged RR',row['current_mse']<row['rr_mse'],**row)
        if stability and case in ('static','pan','subpixel_pan','reveal','upstream_seed'):
            old=stability[case]
            # Error energy and temporal RMS are separate: a sharper result can
            # retain its total error while its grain becomes less stationary.
            t.check(case+' previous error budget',row['current_mse']<=old['current_mse']*1.10,**row)
            t.check(case+' previous temporal RMS budget',row['current_flicker']<=old['current_flicker']*1.15**2,**row)
        if reference and case in ('static','pan','subpixel_pan','reveal','upstream_seed'):
            t.check(case+' correlated noise reduced',row['current_mse']<row['baseline_mse']*.7,**row)
            t.check(case+' flicker reduced',row['current_flicker']<row['baseline_flicker']*.7,**row)
        if case in ('clean','stable_bias'):
            budget=row['baseline_mse']*1.05+1e-6 if reference else .00003
            t.check(case+' broad correction and sharp detail retained',row['current_mse']<budget,**row)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,records=records,dispatches=t.timings),indent=2))
    if not report_only:assert all(c['passed'] for c in t.checks),'ST coarse noise regression'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path);p.add_argument('--report-only',action='store_true')
    p.add_argument('--stability-reference',type=Path,help='Frozen same-fixture results; <=10%% error energy and <=15%% temporal RMS increase')
    args=p.parse_args();run(args.reference,args.report_only,args.stability_reference)
