"""Broad radiance damage on weak/animated detail must recover without noise return.

Known synthetic truth, actual production composition DXIL. This does not execute
AMD's neural denoiser or establish visual acceptance in Cyberpunk.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run(reference=None):
    t.build_runner()
    w,h=65,49; y,x=np.indices((h,w)); roi=(slice(9,-9),slice(9,-9),slice(0,3))
    zero=t.rgba(w,h,(0,0,0)); spec=t.rgba(w,h,(.8,.8,.8)); diff=t.rgba(w,h,(.2,.2,.2))
    depth=np.full((h,w),10,np.float32)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=2,SpatialTemporalMask=2,
            WriteHistory=1,SpecularAlbedoDemodulation=0,DiffuseAlbedoModulation=0)
    records=[]
    for case in ('smooth','waves','pan','reveal','animated_guides','bright_blotch','coarse_noise','common_noise'):
        history=None; old_history=None; old_errors=[]; old_residuals=[]
        errors=[]; rr_errors=[]; residuals=[]; biases=[]
        for frame in range(24):
            shift=frame*.37 if case=='pan' else 0
            truth=t.rgba(w,h,(.3,.35,.4),0)
            truth[...,:3]+=(.02*np.sin((x-shift)*.04)+
                (.012*np.sin((x-shift)*.8+y*.2+frame*.12) if case!='smooth' else 0))[...,None]
            noisy_case=case in ('coarse_noise','common_noise')
            rr=truth.copy() if noisy_case else blur(truth,3)
            if not noisy_case:
                blotch=.12*np.exp(-((x-shift-32)**2+(y-24)**2)/240)
                rr[...,:3]+=(1 if case=='bright_blotch' else -1)*blotch[...,None]
            rng=np.random.default_rng(4201+frame)
            ref=truth.copy();ref[...,:3]+=rng.normal(0,.012,(h,w,3));ref[...,3]=.012
            if case=='coarse_noise':
                field=zero.copy();field[...,:3]=rng.normal(0,1,(h,w,1))
                grain=blur(field,12)[...,:3]
                ref[...,:3]+=grain*.055/max(float(np.std(grain[roi])),1e-6)
            if case=='common_noise':ref[...,:3]+=rng.normal(0,.055)
            normal=t.rgba(w,h,(.5,.5,.4),0)
            if case=='animated_guides':normal[...,2]+=.012*np.sin(x*.3+frame*.3)
            z=depth+(4 if case=='reveal' and frame>=12 else 0)
            motion=t.rgba(w,h,(-.37/w if case=='pan' else 0,0,0),1)
            inputs=[zero,spec,rr,diff,zero,normal,ref,z,motion,
                    zero if history is None else history[1],
                    np.zeros((h,w,4),np.uint32) if history is None else history[2]]
            out=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(history is not None)),inputs,[10,10,3],(w,h))
            if case=='reveal' and frame==12:
                fresh=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=0),inputs,[10,10,3],(w,h))
                t.check('disocclusion discards broad history',np.array_equal(out[0],fresh[0]))
            history=out
            if reference and noisy_case:
                old_inputs=inputs[:9]+[zero if old_history is None else old_history[1],
                    np.zeros((h,w,4),np.uint32) if old_history is None else old_history[2]]
                old_history=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(old_history is not None)),
                    old_inputs,[10,10,3],(w,h),directory=reference)
                if frame>=8:
                    residual=old_history[0][roi]-truth[roi]
                    old_errors.append(float(np.mean(residual**2)));old_residuals.append(residual)
            if frame>=8:
                residual=out[0][roi]-truth[roi]
                errors.append(float(np.mean(residual**2)));biases.append(float(np.mean(residual)))
                rr_errors.append(float(np.mean((rr[roi]-truth[roi])**2)));residuals.append(residual)
        row=dict(case=case,mse=float(np.mean(errors)),rr_mse=float(np.mean(rr_errors)),
                 bias=float(np.mean(biases)),flicker=float(np.mean(np.diff(residuals,axis=0)**2)))
        records.append(row);print(json.dumps(row),flush=True)
        if noisy_case:
            # This accepted-history coarse-noise fixture already measured MSE
            # 5.14e-5 / flicker 8.85e-5 in the frozen previous shader. Keep an
            # absolute ceiling AND a separate historical regression bound; do
            # not confuse it with the existing rejected-history noise fixture.
            limit=(.00006,.0001) if case=='coarse_noise' else (.000025,.00005)
            t.check(case+' absolute noise return bounded',row['mse']<limit[0] and row['flicker']<limit[1],**row)
            if reference:
                row['previous_mse']=float(np.mean(old_errors))
                row['previous_flicker']=float(np.mean(np.diff(old_residuals,axis=0)**2))
                t.check(case+' within previous noise tolerance',
                    row['mse']<=row['previous_mse']*1.04+1e-9 and
                    row['flicker']<=row['previous_flicker']*1.04+1e-9,**row)
        else:
            t.check(case+' broad damage recovered',row['mse']<row['rr_mse']*(.5 if case=='reveal' else .2),**row)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,records=records,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks),'broad recovery regression'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--reference',type=Path)
    run(parser.parse_args().reference)
