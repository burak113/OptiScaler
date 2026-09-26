"""Actual DXIL: narrow volume retention, false-light controls, subpixel visibility.

Known analytical radiance is independent of the shader. Frozen baseline is optional.
No AMD model or game acceptance claim is made by these tests.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run(baseline=None):
    t.OUT=t.OUT.parent/'volume_visibility';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=65,49;y,x=np.indices((h,w));roi=(slice(6,-6),slice(6,-6))
    a=t.rgba(w,h,(.5,.5,.5));n=t.rgba(w,h,(0,0,1));z=np.full((h,w),10,np.float32)
    records=[]
    # Visibility reveals a small same-surface patch. RGB is held fixed while
    # guide support moves continuously through five effective samples. A hard
    # fallback switch must not print a light flash into Skip.
    support_images={};filtered_support={}
    for label,directory in [('current',t.PRE)]+([('previous',baseline)] if baseline else []):
        levels=[];filtered=[]
        for weight in (.48,.49,.5,.51,.52):
            raw=t.rgba(w,h,(.06,.06,.06));raw[23:26,31:34,:3]=.3
            depth=np.full((h,w),20,np.float32);depth[23:26,31:34]=10
            normals=n.copy();cosine=.9+np.sqrt(weight)/10
            normals[23:26,31:34,:3]=[np.sqrt(1-cosine*cosine),0,cosine];normals[24,32,:3]=[0,0,1]
            cb=dict(InvProjMatrix=np.eye(4).ravel(),RenderSize=[w,h,1/w,1/h],NearPlane=.1,FarPlane=1000,Flags=1,FloorEnabled=1)
            result=t.dispatch('FSRDFloorSeed',cb,[raw,normals,depth,depth,a],[10,41,10,10],(w,h),directory)
            levels.append(float(result[0][24,32,0]))
            f=result[0]
            for step in (1,2,4,8,16):
                f=t.dispatch('FSRDFloor',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),[f,result[1],result[2],a],[10],(w,h),directory)[0]
            filtered.append(float(f[24,32,0]))
        support_images[label]=levels
        filtered_support[label]=filtered
    t.check('visibility support transition has no brightness step',np.max(abs(np.diff(support_images['current'])))<.01,**support_images)
    if baseline:t.check('fixture exposes old visibility flash',np.max(abs(np.diff(support_images['previous'])))>.1)
    t.check('filtered pedestal visibility transition bounded',np.max(abs(np.diff(filtered_support['current'])))<.015,**filtered_support)
    def floor(raw,directory,depth=z):
        values=dict(InvProjMatrix=np.eye(4).ravel(),RenderSize=[w,h,1/w,1/h],NearPlane=.1,FarPlane=1000,Flags=1,FloorEnabled=1)
        f,d,g,r=t.dispatch('FSRDFloorSeed',values,[raw,n,depth,depth,a],[10,41,10,10],(w,h),directory)
        for step in (1,2,4,8,16):
            f=t.dispatch('FSRDFloor',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),[f,d,g,a],[10],(w,h),directory)[0]
        return f
    for angle in (0,45,90,135,23):
        d=(x-w//2)*np.cos(np.deg2rad(angle))+(y-h//2)*np.sin(np.deg2rad(angle))
        for width in (.65,1.2,3):
            beam=np.exp(-.5*(d/width)**2)
            raw=t.rgba(w,h,(.04,.06,.08));raw[...,:3]+=beam[...,None]*np.array([.18,.27,.4])
            f=floor(raw,t.PRE)
            peak=(beam>.85);peak[:6]=False;peak[-6:]=False;peak[:,:6]=False;peak[:,-6:]=False
            retained=float(np.mean((f[...,:3]-[.04,.06,.08])[peak])/np.mean((raw[...,:3]-[.04,.06,.08])[peak]))
            row=dict(angle=angle,width=width,retained=retained,rmse=float(np.sqrt(np.mean((f[roi][...,:3]-raw[roi][...,:3])**2))))
            t.check(f'volume {angle}/{width} bounded radiance',np.min(f[...,:3])>=0 and np.max(f[...,:3])<=np.max(raw[...,:3])+.001)
            # Retention is characterization, not an unconditional recovery goal:
            # the high-retention ridge path also bypassed correlated ray noise
            # and was rejected by game feedback + test_fsrd_correlated_grain.
            if baseline:
                old=floor(raw,baseline)
                row['previous_retained']=float(np.mean((old[...,:3]-[.04,.06,.08])[peak])/np.mean((raw[...,:3]-[.04,.06,.08])[peak]))
                row['previous_rmse']=float(np.sqrt(np.mean((old[roi][...,:3]-raw[roi][...,:3])**2)))
                t.check(f'volume {angle}/{width} no error regression',row['rmse']<=row['previous_rmse']+.0005,**row)
                halo=float(np.max(f[roi][...,:3]-raw[roi][...,:3]));old_halo=float(np.max(old[roi][...,:3]-raw[roi][...,:3]))
                t.check(f'volume {angle}/{width} no added halo',halo<=max(old_halo,.002)+.001,halo=halo,previous=old_halo)
            records.append(row)
    for label in ('impulse','cluster','random','ramp','silhouette'):
        raw=t.rgba(w,h,(.1,.12,.15));depth=z.copy();rng=np.random.default_rng(9042)
        if label=='impulse':raw[h//2,w//2,:3]=[30,2,1]
        if label=='cluster':raw[20:22,30:32,:3]=[4,1,10]
        if label=='random':raw[...,:3]+=np.maximum(rng.normal(0,.07,(h,w,3)),0)
        if label=='ramp':raw[...,:3]+=(x/w*.1)[...,None]
        if label=='silhouette':raw[:,w//2:,:3]=0;depth[:,w//2:]=2
        current=floor(raw,t.PRE,depth)
        if label in ('impulse','cluster'):t.check(label+' cannot invent volumetric light',np.max(current[...,:3])<.16)
        if label=='silhouette':t.check('black foreground stays black',np.max(current[:,w//2:,:3])<.001)
        if label=='ramp':t.check('smooth light ramp error bounded',np.max(abs(current[roi][...,:3]-raw[roi][...,:3]))<.008)
        if baseline:
            old=floor(raw,baseline,depth)
            if label in ('impulse','cluster','silhouette'):
                t.check(label+' no material floor regression',np.max(abs(current-old))<.001,max_difference=float(np.max(abs(current-old))))
            if label=='random':
                e=float(np.sqrt(np.mean((current[roi][...,:3]-[.1,.12,.15])**2)))
                old_e=float(np.sqrt(np.mean((old[roi][...,:3]-[.1,.12,.15])**2)))
                t.check('random noise not reintroduced',e<=old_e*1.02+.0001,rmse=e,previous=old_e)

    # The volume estimator must not flicker between full recovery and deletion
    # when independent Monte Carlo noise perturbs an otherwise fixed light.
    clean=t.rgba(w,h,(.04,.06,.08));clean[...,:3]+=np.exp(-.5*((x-w//2)/.65)**2)[...,None]*[.18,.27,.4]
    for sigma in (.003,.01,.03):
        outputs=[];observations=[]
        for frame in range(8):
            raw=clean.copy();raw[...,:3]+=np.random.default_rng(2982+frame).normal(0,sigma,(h,w,3))
            outputs.append(floor(raw,t.PRE)[8:-8,w//2,:3]);observations.append(raw[8:-8,w//2,:3])
        output_std=float(np.sqrt(np.mean(np.var(outputs,axis=0))))
        raw_std=float(np.sqrt(np.mean(np.var(observations,axis=0))))
        retained=float(np.mean(np.stack(outputs)-[.04,.06,.08])/np.mean(clean[8:-8,w//2,:3]-[.04,.06,.08]))
        t.check(f'noisy narrow volume {sigma} does not amplify flicker',output_std<=raw_std+.002,output_std=output_std,raw_std=raw_std,retained=retained)

    # A subpixel sample can touch an occluder although its nearest tap still
    # names the old background. Deliberately different history exposes reuse.
    target=t.rgba(w,h,(.4,.4,.4),.005)
    for c,phase in enumerate((0,1.1,2.3)):target[...,c]+=.13*np.sin(.35*x+.2*y+phase)
    rr=blur(target,2);zero=t.rgba(w,h,(0,0,0));alb=t.rgba(w,h,(1,1,1))
    normal=t.rgba(w,h,(.5,.5,.1),1/3);motion=t.rgba(w,h,(0,0,0),1)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1.0,FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,WriteHistory=1)
    def comp(history=None,mv=motion,directory=t.PRE):
        inputs=[zero,alb,rr,alb,zero,normal,target,z,mv,
                history[1] if history else t.rgba(w,h,(-1,-1,-1),-1),
                history[2] if history else np.zeros((h,w,4),np.uint32)]
        return t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(history is not None)),inputs,[10,10,3],(w,h),directory)
    first=comp();history=[q.copy() for q in first];history[1]=np.clip(history[1]+.1,0,1)
    mv=motion.copy();mv[...,0]=.25/w
    iy,ix=20,30
    history[2][iy,ix+1,0]=np.array(2,np.float32).view(np.uint32)
    fresh=comp(mv=mv);result=comp(history,mv)
    t.check('fractional disocclusion rejects whole history footprint',np.array_equal(result[1][iy,ix],fresh[1][iy,ix]))
    if baseline:
        old=comp(history,mv,baseline)
        t.check('fixture exposes previous point-history leak',np.max(abs(old[1][iy,ix]-fresh[1][iy,ix]))>.005)
    # Identical-colour metadata isolates decision resampling from content rejection.
    history=[q.copy() for q in first]
    history[2][...,3]=first[2][iy,ix,3]
    center=first[1][iy,ix]
    history[1]=np.clip(center+np.where((x%2)[...,None],.08,-.08),0,1).astype(np.float32)
    samples={}
    for name,directory in [('current',t.PRE)]+([('previous',baseline)] if baseline else []):
        values=[]
        for shift in (.49,.51):
            mv=motion.copy();mv[...,0]=shift/w
            values.append(comp(history,mv,directory)[1][iy,ix])
        samples[name]=float(np.max(abs(values[1]-values[0])))
    t.check('subpixel decision transition bounded',samples['current']<.005,**samples)
    if baseline:t.check('subpixel jump reduced',samples['current']<samples['previous']*.2,**samples)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,records=records,dispatches=t.timings),indent=2))
    assert all(q['passed'] for q in t.checks),'volume/visibility regression'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',type=Path)
    run(parser.parse_args().baseline)
