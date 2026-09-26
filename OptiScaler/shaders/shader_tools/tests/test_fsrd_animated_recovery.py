"""Recover animated reflection detail not represented by surface motion vectors.

Known-truth wave fields; optional frozen old recovery and actual FloorSeed.
Unlike static textures with matching motion vectors, stationary geometry here
contains moving radiance. Measures phase-sensitive contrast and error.
"""
import argparse,json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur


def run(reference=None,candidate=None,report_only=False):
    t.build_runner()
    w,h=65,49;y,x=np.indices((h,w));roi=(slice(9,-9),slice(9,-9),slice(0,3))
    zero=t.rgba(w,h,(0,0,0));s=t.rgba(w,h,(.8,.8,.8));d=t.rgba(w,h,(.2,.2,.2))
    z=np.full((h,w),10,np.float32);n=t.rgba(w,h,(.5,.5,.4),0)
    cb=dict(DstTexSize=[w,h,1/w,1/h],DetailPreservation=1,RecoveryMask=2,SpatialTemporalMask=2,
            WriteHistory=1,SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1)
    variants=[('current',candidate or t.PRE)]+([('old',reference)] if reference else [])
    records=[]
    for case,speed in [('static',0),('slow',.12),('fast',.4),('camera',.12),('seed',.12)]:
        old={k:None for k,_ in variants};errors={k:[] for k,_ in variants};gains={k:[] for k,_ in variants};rr_errors=[]
        for frame in range(24):
            shift=frame*.37 if case=='camera' else 0
            truth=t.rgba(w,h,(.35,.4,.45),0)
            pattern=.09*np.sin((x-shift)*.65+y*.14+frame*speed)+.06*np.sin((x-shift)*1.2-y*.34+frame*speed*1.5)
            truth[...,:3]+=pattern[...,None];rr=blur(truth,5)
            spec=rr.copy();spec[...,:3]/=.8
            ref=truth.copy();ref[...,:3]+=np.random.default_rng(471+frame).normal(0,.012,(h,w,3));ref[...,3]=.012
            if case=='seed':ref=t.seed(ref)[3]
            mv=t.rgba(w,h,(-.37/w if case=='camera' else 0,0,0),1)
            for name,path in variants:
                hist=old[name]
                out=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=int(hist is not None)),
                    [spec,s,zero,d,zero,n,ref,z,mv,zero if hist is None else hist[1],
                     np.zeros((h,w,4),np.uint32) if hist is None else hist[2]],[10,10,3],(w,h),directory=path)
                old[name]=out
                if frame>=8:
                    errors[name].append(float(np.mean((out[0][roi]-truth[roi])**2)))
                    signal=truth[roi]-np.mean(truth[roi],axis=(0,1),keepdims=True)
                    gains[name].append(float(np.sum((out[0][roi]-np.mean(out[0][roi],axis=(0,1),keepdims=True))*signal)/np.sum(signal**2)))
            if frame>=8:rr_errors.append(float(np.mean((rr[roi]-truth[roi])**2)))
        row=dict(case=case,rr_mse=float(np.mean(rr_errors)),variants={k:dict(mse=float(np.mean(errors[k])),contrast=float(np.mean(gains[k]))) for k,_ in variants})
        records.append(row);print(json.dumps(row),flush=True)
        current=row['variants']['current']
        # Light Anchor Mix budgets: the current-frame reference is the only
        # detail source, so phase tracking is exact at every animation speed
        # (contrast is identical across cases); amplitude recovery is bounded
        # by the single-frame anchor, not by temporal accumulation.
        t.check(case+' current-phase detail recovered',current['contrast']>.60,**row)
        t.check(case+' improves blurred RR',current['mse']<row['rr_mse']*(.5 if case=='seed' else .45),**row)
        if reference:
            previous=row['variants']['old']
            t.check(case+' retains old recovery contrast',current['contrast']>=previous['contrast']*.9,**row)
    # The Light Anchor Mix keeps no temporal state: no corruption of the
    # carried history - geometry, material, colour or validity, including the
    # non-nearest tap of a fractional reprojection footprint - may change the
    # composed colour at all.
    def packed_colour(value):
        bits=np.array([value]*3,np.float16).view(np.uint16).astype(np.uint32)
        v=np.minimum(bits+np.array([8,8,16],np.uint32),np.array([0x7bf0,0x7bf0,0x7be0],np.uint32))
        return ((v[0]>>4)&2047)|(((v[1]>>4)&2047)<<11)|(((v[2]>>5)&1023)<<22)
    cy,cx=h//2,w//2
    for fractional in (False,True):
        mv=t.rgba(w,h,(.37/w if fractional else 0,0,0),1)
        q=(cy,cx+1 if fractional else cx)
        history=old['current']
        for reason in ('valid','depth','normal','roughness','albedo','invalid'):
            meta=history[2].copy();moments=history[1].copy()
            if reason=='depth':meta[q][0]=np.array(30,dtype=np.float32).view(np.uint32)
            if reason=='normal':meta[q][1]&=np.uint32(0xfff00000)
            if reason=='roughness':meta[q][1]=(meta[q][1]&np.uint32(0xf00fffff))|np.uint32(255<<20)
            if reason=='albedo':meta[q][2]=(meta[q][2]&np.uint32(0xff000000))|np.uint32(0xffffff)
            if reason=='invalid':meta[q][1]&=np.uint32(0x7fffffff)
            pixels=[];stored=[]
            for value in (.05,.85):
                altered=meta.copy();altered[q][3]=packed_colour(value)
                out=t.dispatch('FSRDOutputComp',dict(cb,HistoryValid=1),
                    [spec,s,zero,d,zero,n,ref,z,mv,moments,altered],[10,10,3],(w,h),directory=candidate or t.PRE)
                pixels.append(out[0][cy,cx,:3])
                stored.append(out[1][cy,cx,:3])
            change=float(np.max(abs(pixels[1]-pixels[0])))
            t.check(('fractional ' if fractional else 'integer ')+reason+' history is never read',
                    change==0.0,change=change)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,records=records,dispatches=t.timings),indent=2))
    if not report_only:assert all(c['passed'] for c in t.checks),'animated recovery regression'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path);p.add_argument('--candidate',type=Path);p.add_argument('--report-only',action='store_true')
    args=p.parse_args();run(args.reference,args.candidate,args.report_only)
