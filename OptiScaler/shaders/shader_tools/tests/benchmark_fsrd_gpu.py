"""Per-stage synthetic GPU timings, not an in-game performance acceptance result."""
import json
import argparse
import numpy as np
import run_fsrd_gpu_tests as t

def run(trials=3, roughness=.5):
    t.OUT=t.OUT.parent/('gpu_benchmark_type1' if roughness==0 else 'gpu_benchmark')
    t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    references = [(name, t.reference(name)) for name in ('baseline', 'spatial_v1')]
    variants = [(name, path) for name, path in references if path is not None] + [('current', t.PRE)]
    w,h=1280,720
    rng=np.random.default_rng(771)
    color=t.rgba(w,h,(.5,.5,.5));color[...,:3]+=rng.normal(0,.06,color[...,:3].shape)
    # Real material/depth boundaries as well as flat noisy surfaces.
    color[:,w//2:,:3]*=2
    normal=t.rgba(w,h,(0,0,1));albedo=t.rgba(w,h,(.5,.5,.5));spec=t.rgba(w,h,(.1,.1,.1))
    depth=np.ones((h,w),np.float32)*10;depth[:,w//2:]=12
    zero=t.rgba(w,h,(0,0,0));rough=np.ones((h,w),np.float32)*roughness
    results=[]
    for trial in range(trials):
        for label,directory in variants:
            rewritten = label != 'baseline'
            start=len(t.timings)
            v={'InvProjMatrix':np.eye(4).ravel(),'RenderSize':[w,h,1/w,1/h], 'NearPlane':.1,'FarPlane':1000,
                'Flags':1,'FloorEnabled':1,'NoiseSuppression':.75}
            inputs=[color,normal,depth,depth]+([albedo] if rewritten else [])
            seeded=t.dispatch('FSRDFloorSeed',v,inputs,[10,41,10]+([10] if rewritten else []),(w,h),directory,610)
            floor,z,guide=seeded[:3]
            for step in (1,2,4,8,16):
                v={'DstTexSize':[w,h,1/w,1/h],'StepSize':step,'NoiseSuppression':.75,
                    'RcpCrossBlNorm':2,'RcpSelfBlNorm':.01/.3,'NormalSharpness':16,'AlbedoGuideStrength':1,'LumSymmetry':1}
                floor=t.dispatch('FSRDFloor',v,[floor,z,guide,albedo],[10],(w,h),directory,610)[0]
            v={'InvViewMatrix':np.eye(4).ravel(),'InvProjMatrix':np.eye(4).ravel(),'PrevViewMatrix':np.eye(4).ravel(),
               'DstTexSize':[w,h,1/w,1/h],'MotionInputSize':[w,h,1/w,1/h],'MotionTransform':[1,1,0,0],
               'NearPlane':.1,'FarPlane':1000,'FloorDetailPreservation':.35,
               'Flags':(1<<1)|(1<<7),'DemodDivisorFloor':.008,'BiasMaskStrength':1,
               'FloorIsolation':1,'FloorHandoverMode':1,'FloorHandoverStrength':1,'FloorHandoverDetail':1,'FloorRawBlend':1,'FloorStructureGate':1}
            inputs=[color,z,zero,normal,rough,z,albedo,spec,zero,floor,zero,zero,zero,zero,z,zero]
            if rewritten:inputs.append(seeded[3])
            packed=t.dispatch('FSRDInputConv',v,inputs,[10,10,10,24,28,28,10,10],(w,h),directory,610)
            # Identity RR makes the pre/post-processing timing independent of AMD DLL availability.
            inputs=[packed[0],packed[4],packed[1],packed[5],packed[6]]
            inputs += [packed[3],packed[7],z] if rewritten else [color,packed[0],packed[3],packed[7]]
            t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':.35,'NoiseSuppression':.75,
                       'CorrelationBias':1,'FloorHandoverAnchorClamp':2,'FloorHandoverCorrelationMix':1},inputs,[10],(w,h),directory,610)
            stages=t.timings[start:]
            row={'trial':trial,'variant':label,'roughness':roughness,'median_sum_ms':sum(float(x['gpu_ms_median']) for x in stages),
                 'p95_sum_ms':sum(float(x['gpu_ms_p95']) for x in stages),'stages':stages}
            results.append(row)
            print(json.dumps({k:v for k,v in row.items() if k!='stages'}),flush=True)
    (t.OUT/'results.json').write_text(json.dumps(results,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--trials',type=int,default=3)
    parser.add_argument('--roughness',type=float,default=.5)
    args=parser.parse_args()
    run(args.trials,args.roughness)
