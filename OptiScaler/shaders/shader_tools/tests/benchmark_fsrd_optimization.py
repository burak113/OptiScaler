"""Paired DXIL benchmark + exact-output gate against a frozen current baseline.

No AMD model or upscaler. GPU timestamps exclude uploads/compilation/readback;
sum of per-stage p95 is NOT the p95 of a complete frame. Run alone on the GPU.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_zero_rough_screen import chain_cb


def fixture(w,h,kind):
    y,x=np.indices((h,w),dtype=np.float32)
    clean=t.rgba(w,h,(.4,.4,.4))
    clean[...,0]+=.18*np.sin(x*.31+y*.12)
    clean[...,1]+=.13*np.cos(x*.08-y*.44)
    clean[...,2]+=.16*np.sin(x*.51+y*.05)
    rng=np.random.default_rng(90217)
    raw=clean.copy();raw[...,:3]+=rng.normal(0,.035,(h,w,3))
    normal=t.rgba(w,h,(0,0,1))
    rough=np.full((h,w),.5,np.float32)
    albedo=t.rgba(w,h,(.5,.5,.5))
    albedo[...,:3]+=(.12*np.sin(x*.55)+.1*np.cos(y*.67))[...,None]
    screen=np.zeros((h,w),bool)
    if kind in ('screens','sloped_screens','curved_screens','perspective_screens'): screen[:]=True
    elif kind=='mixed': screen=(x>w*.2)&(x<w*.6)&(y>h*.2)&(y<h*.8)
    rough[screen]=0;albedo[screen,:3]=.7
    depth=np.full((h,w),10,np.float32);depth[screen]=12
    if kind=='sloped_screens': depth=12+x*.002+y*.001
    if kind=='perspective_screens': depth=1/(.1+.000035*x+.000015*y)
    if kind=='curved_screens':
        depth=12+.12*np.sin(x*.025)+.09*np.cos(y*.017)
        normal[...,0]=.08*np.sin(x*.013)
        normal[...,1]=.06*np.cos(y*.019)
        normal[...,2]=np.sqrt(1-normal[...,0]**2-normal[...,1]**2)
    return raw,normal,rough,albedo,depth,clean


def run(args):
    if min(args.width,args.height,args.trials)<=0 or args.repetitions<=10:
        raise ValueError('Positive dimensions/trials and more than ten warmup repetitions are required')
    if not np.isfinite(args.detail) or not 0<=args.detail<=1:
        raise ValueError('Detail must be finite and between zero and one')
    if not set(args.cases.split(',')) <= {'ordinary','mixed','screens','sloped_screens','curved_screens','perspective_screens'}:
        raise ValueError('Unknown benchmark case')
    if args.baseline.resolve()==t.PRE.resolve():
        raise ValueError('Baseline must be a separate frozen precompile directory')
    args.output=args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=False)
    t.OUT=args.output/'dispatches';t.OUT.mkdir();t.runner=t.OUT/'fsrd_gpu_runner.exe'
    t.build_runner()
    w,h=args.width,args.height
    baseline=args.baseline.resolve()
    manifest={'baseline':str(baseline),'current':str(t.PRE),'size':[w,h],
              'trials':args.trials,'repetitions':args.repetitions,'detail':args.detail,
              'warmup_dispatches_per_stage':10,'shader_hashes':{}}
    manifest['temporal_helpers_current']=args.temporal_helpers
    manifest['production_albedo_guides']=True
    for label,directory in [('baseline',baseline),('current',t.PRE)]:
        manifest['shader_hashes'][label]={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in directory.glob('*_Shader.cso')}
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    records=[]
    for kind in args.cases.split(','):
        raw,n,rough,a,z,clean=fixture(w,h,kind)
        zero=t.rgba(w,h,(0,0,0));spec=t.rgba(w,h,(.04,.04,.04))
        seed_cb={'InvProjMatrix':np.eye(4).ravel(),'RenderSize':[w,h,1/w,1/h],
                 'NearPlane':.1,'FarPlane':1000,'Flags':1,'FloorEnabled':1,'NoiseSuppression':.75}
        conv_cb=chain_cb(w,h,(1<<1)|(1<<7),detail=args.detail)
        comp_cb={'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':args.detail,'NoiseSuppression':.75,
                 'FloorHandoverAnchorClamp':4,'FloorHandoverCorrelationMix':1}
        for trial in range(args.trials):
            captures={}; rows={}
            variants=[('baseline',baseline)] if args.baseline_only else [('baseline',baseline),('current',t.PRE)]
            if trial%2: variants.reverse()
            for name,directory in variants:
                outputs=[]; start=len(t.timings)
                def dispatch(shader,cb,inputs,formats):
                    result=t.dispatch(shader,cb,inputs,formats,(w,h),directory,args.repetitions)
                    outputs.extend(result)
                    return result
                f,d,g,ref=dispatch('FSRDFloorSeed',seed_cb,[raw,n,z,z,a],[10,41,10,10])
                for step in (1,2,4,8,16):
                    f=dispatch('FSRDFloor',{'DstTexSize':[w,h,1/w,1/h],
                        'StepSize':step,'NoiseSuppression':.75},[f,d,g,a],[10])[0]
                packed=dispatch('FSRDInputConv',conv_cb,
                    [raw,d,zero,n,rough,z,a,spec,zero,f,zero,zero,zero,zero,z,zero,ref],
                    [10,10,10,24,28,28,10,10])
                # Independent clean RR radiance, while keeping actual production
                # conversion normals/reference/Skip. All variants see the same target.
                rr=clean.copy();rr[...,:3]=np.maximum(clean[...,:3]-packed[6][...,:3],0)/np.maximum(packed[5][...,:3],1e-4)
                comp_inputs=[zero,packed[4],rr,packed[5],packed[6],packed[3],packed[7],d]
                measured_cb=dict(comp_cb)
                if args.temporal_helpers and args.detail>0 and 'InHistoryMetadata' in (directory/'FSRDOutputComp.hlsl').read_text():
                    # A real prior GPU dispatch supplies valid packed history.
                    # Exclude this initialization dispatch from measured stages.
                    motion=packed[2].copy();motion[...,2]=0
                    motion[...,0] += args.history_offset_pixels / w
                    temporal_inputs=comp_inputs+[motion,t.rgba(w,h,(-1,-1,-1),-1),np.zeros((h,w,4),np.uint32)]
                    prior=t.dispatch('FSRDOutputComp',dict(comp_cb,WriteHistory=1),
                                     temporal_inputs,[10,10,3],(w,h),directory)
                    t.timings.pop()
                    comp_inputs += [motion,prior[1],prior[2]]
                    measured_cb.update(WriteHistory=1,HistoryValid=1)
                dispatch('FSRDOutputComp',measured_cb,comp_inputs,[10])
                stages=t.timings[start:]
                row=dict(case=kind,trial=trial,variant=name,size=[w,h],stages=stages,
                    median_sum_ms=sum(float(s['gpu_ms_median']) for s in stages),
                    p95_sum_ms=sum(float(s['gpu_ms_p95']) for s in stages))
                records.append(row);captures[name]=outputs;rows[name]=row
                (args.output/'results.json').write_text(json.dumps(records,indent=2))
                print(json.dumps({k:v for k,v in row.items() if k!='stages'}),flush=True)
            if not args.baseline_only:
                differences=[dict(output=i,maximum=float(np.max(np.abs(b-c))),changed=int(np.count_nonzero(b!=c)))
                             for i,(b,c) in enumerate(zip(captures['baseline'],captures['current'])) if not np.array_equal(b,c)]
                rows['current']['differences']=differences
                print('OUTPUT '+('IDENTICAL' if not differences else json.dumps(differences)),flush=True)
                if differences and not args.allow_differences:
                    (args.output/'results.json').write_text(json.dumps(records,indent=2))
                    raise AssertionError('Optimization changed stored output')
    (args.output/'results.json').write_text(json.dumps(records,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--width',type=int,default=1280);p.add_argument('--height',type=int,default=720)
    p.add_argument('--trials',type=int,default=3);p.add_argument('--repetitions',type=int,default=610)
    p.add_argument('--cases',default='ordinary,mixed,screens')
    p.add_argument('--detail',type=float,default=.35)
    p.add_argument('--baseline-only',action='store_true');p.add_argument('--allow-differences',action='store_true')
    p.add_argument('--temporal-helpers',action='store_true',help='Include current production decision-history reads/writes')
    p.add_argument('--history-offset-pixels',type=float,default=0,
                   help='Horizontal subpixel reprojection offset for temporal-helper timing')
    run(p.parse_args())
