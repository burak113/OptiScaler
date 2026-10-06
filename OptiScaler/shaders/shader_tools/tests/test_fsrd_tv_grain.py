# HISTORICAL: removed production feature; excluded from validate_fsrd.py.
"""Actual composition DXIL: residual TV grain versus smooth lighting and fine text.

RR is a controlled noisy/clean image in this suite, not the AMD model. The
independent target separates grain reduction from blur. Optional old CSO A/B.
"""
from pathlib import Path
import argparse,json
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_stage_probe as p

def run(baseline=None):
    t.OUT=t.OUT.parent/'tv_grain';t.OUT.mkdir(parents=True,exist_ok=True)
    t.runner=t.OUT/'fsrd_gpu_runner.exe';t.build_runner()
    w,h=65,49;y,x=np.indices((h,w),dtype=np.float32)
    z=np.full((h,w),10,np.float32);white=t.rgba(w,h,(1,1,1));zero=t.rgba(w,h,(0,0,0))
    n=t.rgba(w,h,(.5,.5,.1),1/3)
    values={'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':1.0,'NoiseSuppression':.75,
            'FloorHandoverAnchorClamp':4,'FloorHandoverCorrelationMix':1}
    crop=(slice(7,-7),slice(7,-7),slice(0,3));records=[]
    for scene in ('tv','flat','ramp','text'):
        errors=[];old_errors=[];clean_errors=[];old_clean_errors=[];input_errors=[]
        for frame in range(8):
            sx=x-.17*frame;sy=y-.11*frame
            clean=t.rgba(w,h,(.06,.075,.09))
            if scene=='tv':
                clean[...,:3]+=np.exp(-((sx-22)**2+(sy-14)**2)/32)[...,None]*np.array([.45,.4,.35])
                clean[...,:3]+=np.exp(-((sy-32-.07*sx)**2)/9)[...,None]*np.array([.12,.025,.16])
            if scene=='ramp':clean[...,:3]+=(.003*sx+.001*sy)[...,None]
            if scene=='text':
                phase=np.abs(np.sin(sx*.65+np.sin(sy*.5)))
                stroke=np.clip((.24-phase)*5,0,1)
                clean[...,:3]+=stroke[...,None]*np.array([.4,.07,.26])
            rng=np.random.default_rng(91387+frame)
            noise=rng.normal(0,.008,(h,w,3))
            raw=clean.copy();raw[...,:3]=np.maximum(raw[...,:3]+noise,0)
            reference=t.seed(raw)[3]
            rr=clean.copy();rr[...,:3]=np.maximum(rr[...,:3]+.4*noise+rng.normal(0,.003,(h,w,3)),0)
            inputs=[zero,white,rr,white,zero,n,reference,z]
            out=p.dispatch(values,inputs);errors.append(out[crop]-clean[crop]);input_errors.append(rr[crop]-clean[crop])
            clean_input=[zero,white,clean,white,zero,n,reference,z]
            clean_out=p.dispatch(values,clean_input);clean_errors.append(clean_out[crop]-clean[crop])
            if baseline:
                old_errors.append(p.dispatch(values,inputs,directory=baseline)[crop]-clean[crop])
                old_clean_errors.append(p.dispatch(values,clean_input,directory=baseline)[crop]-clean[crop])
            if frame==7:
                np.savez_compressed(t.OUT/(scene+'.npz'),clean=clean,raw=raw,rr=rr,result=out,
                    old=p.dispatch(values,inputs,directory=baseline) if baseline else out)
        rms=lambda a:float(np.sqrt(np.mean(np.array(a)**2)))
        flicker=lambda a:rms(np.diff(np.array(a),axis=0))
        row=dict(scene=scene,rmse=rms(errors),temporal=flicker(errors),rr_rmse=rms(input_errors),
                 clean_rr_error=rms(clean_errors))
        t.check(scene+' finite nonnegative output',bool(np.all(np.isfinite(out))) and float(out.min())>=0)
        if scene!='text':
            t.check(scene+' residual grain below input RR',row['rmse']<row['rr_rmse']*.85,**row)
            t.check(scene+' clean RR absolute error bounded',row['clean_rr_error']<.0004,**row)
        if baseline:
            row.update(old_rmse=rms(old_errors),old_temporal=flicker(old_errors),old_clean_rr_error=rms(old_clean_errors))
            if scene!='text':
                t.check(scene+' residual grain RMSE reduced at least 15 percent',row['rmse']<row['old_rmse']*.85,**row)
                t.check(scene+' motion error reduced at least 15 percent',row['temporal']<row['old_temporal']*.85,**row)
            else:t.check('fine moving texture error does not regress',row['rmse']<=row['old_rmse']+.0001,**row)
            t.check(scene+' already clean RR remains within storage/small estimator error',
                    row['clean_rr_error']<=row['old_clean_rr_error']+.0003,**row)
        records.append(row);print(json.dumps(row),flush=True)
    # Exact clean thin features: a noise estimator must not erase newly appearing text.
    for direction in ('horizontal','vertical','diagonal','point','colour'):
        clean=t.rgba(w,h,(.1,.15,.2))
        mask={'horizontal':y==24,'vertical':x==32,'diagonal':x-y==8,'point':(x==32)&(y==24),
              'colour':(x//2+y//3)%2==0}[direction]
        clean[mask,:3]=(.6,.2,.5)
        reference=t.seed(clean)[3]
        inputs=[zero,white,clean,white,zero,n,reference,z]
        out=p.dispatch(values,inputs)
        storage_error=float(np.max(np.abs(out[...,:3]-clean[...,:3])))
        t.check(direction+' clean pattern retained',storage_error<.001,max_error=storage_error)
        if baseline:
            old=p.dispatch(values,inputs,directory=baseline)
            change=float(np.max(np.abs(out[...,:3]-old[...,:3])))
            t.check(direction+' clean detail is unchanged',change<.0006,max_change=change)
    # Non-target behavior must stay exactly equal to the frozen baseline.
    for label,change in [('ordinary',lambda v,i:i[5].__setitem__((Ellipsis,3),0)),
                         ('explicit bypass',lambda v,i:i[6].__setitem__((Ellipsis,3),-1)),
                         ('detail off',lambda v,i:v.update(DetailPreservation=0)),
                         ('noise off',lambda v,i:v.update(NoiseSuppression=0))]:
        v=dict(values);i=[a.copy() for a in inputs];change(v,i)
        if baseline:t.check(label+' bit identical',np.array_equal(p.dispatch(v,i),p.dispatch(v,i,directory=baseline)))
    # Target a noisy smooth patch so disabling cleanup at a boundary is exercised.
    rng=np.random.default_rng(600)
    clean=t.rgba(w,h,(.06,.075,.09));raw=clean.copy();raw[...,:3]+=rng.normal(0,.006,(h,w,3))
    reference=t.seed(raw)[3]
    inputs=[zero,white,raw,white,zero,n,reference,z]
    for boundary in ('depth','normal','material','bypass'):
        i=[a.copy() for a in inputs]
        if boundary=='depth':i[7][:,32:]=30
        if boundary=='normal':i[5][:,32:,0]=.8
        if boundary=='material':i[3][:,32:,:3]=.2
        if boundary=='bypass':i[6][:,32:,3]=-1
        if baseline:
            a=p.dispatch(values,i);b=p.dispatch(values,i,directory=baseline)
            change=float(np.max(np.abs(a[7:-7,30:34,:3]-b[7:-7,30:34,:3])))
            t.check(boundary+' boundary excludes grain fit',change<.0001,max_change=change)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,records=records),indent=2))
    if t.checks:assert all(c['passed'] for c in t.checks)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',type=Path);run(ap.parse_args().baseline)
