"""GPU conversion/composition contracts for all 15 nonempty signal layouts.

Uses identity/injected RR outputs; it does not claim to validate AMD inference quality.
Exercises real production DXIL, native hit precedence, missing guides and non-multiple tiles.
"""
import json
import os
import numpy as np
import run_fsrd_gpu_tests as t

def run():
    os.environ.pop('FSRD_LOSSLESS_BASELINE',None)
    t.OUT=t.OUT.parent/'signal_modes'; t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=19,13
    y,x=np.indices((h,w))
    color=t.rgba(w,h,(.25,.45,.7)); color[...,:3]*=(1+.3*np.sin(x*.4))[...,None]
    z=np.full((h,w),10,np.float32)
    zero=t.rgba(w,h,(0,0,0))
    normal=t.rgba(w,h,(0,0,1))
    rough=np.full((h,w),.1,np.float32) # Full specular hit-distance tracking, without the rough-surface handover.
    spec=t.rgba(w,h,(.12,.18,.23)); diff=t.rgba(w,h,(.5,.4,.3))
    spec_hit=np.full((h,w),7,np.float32)
    ray_hit=t.rgba(w,h,(9,9,9),11)
    cb={'InvViewMatrix':np.eye(4).ravel(),'InvProjMatrix':np.eye(4).ravel(),'PrevViewMatrix':np.eye(4).ravel(),
        'DstTexSize':[w,h,1/w,1/h],'MotionInputSize':[w,h,1/w,1/h],'MotionTransform':[1,1,0,0],
        'NearPlane':.1,'FarPlane':1000,'DemodDivisorFloor':.008,'BiasMaskStrength':1,
        'RecoveryMask':0,'DiffuseHitDistanceMode':1,'Flags':(1<<1)|(1<<4)|(1<<5)}
    inputs=[color,z,zero,normal,rough,spec_hit,diff,spec,zero,zero,zero,zero,zero,ray_hit,z,zero,t.rgba(w,h,(0,0,0),-1)]
    formats=[10,10,10,24,28,28,10,10,10]
    baseline=t.dispatch('FSRDInputConv',cb,inputs,formats,(w,h))
    reference=baseline[0][...,:3]*baseline[4][...,:3]+baseline[1][...,:3]*baseline[5][...,:3]+baseline[6][...,:3]
    for mask in range(1,16):
        extra_d=(mask&5)==5; extra_s=(mask&10)==10
        conv=t.dispatch('FSRDInputConv',dict(cb,Flags=cb['Flags']|(int(extra_d)<<24)|(int(extra_s)<<25)),inputs,formats,(w,h))
        # The backend binds the packed signal for an omitted family, and each selected
        # family output for identity RR. Same-family pairs consume half radiance each.
        comp_flags=(int(extra_d)<<6)|(int(extra_s)<<7)
        comp_inputs=[conv[0],conv[4],conv[1],conv[5],conv[6],conv[3],conv[7],z,conv[2],
                     t.rgba(w,h,(-1,-1,-1),-1),np.zeros((h,w,4),np.uint32),conv[0],conv[8],np.zeros((h,w,2),np.float32),conv[1]]
        values={'DstTexSize':[w,h,1/w,1/h],'Flags':comp_flags,'DetailPreservation':0,'RecoveryMask':0}
        output=t.dispatch('FSRDOutputComp',values,comp_inputs,[10],(w,h))[0][...,:3]
        error=float(np.max(np.abs(output-reference)))
        t.check(f'layout {mask:04b}: summed identity RR preserves radiance',error<.0015,error=error)
        if extra_d or extra_s:
            altered=list(comp_inputs)
            if extra_s: altered[11]=conv[0]*1.5
            if extra_d: altered[14]=conv[1]*.5
            expected=reference.copy()
            if extra_s: expected+=.5*conv[0][...,:3]*conv[4][...,:3]
            if extra_d: expected-=.5*conv[1][...,:3]*conv[5][...,:3]
            output=t.dispatch('FSRDOutputComp',values,altered,[10],(w,h))[0][...,:3]
            error=float(np.max(np.abs(output-expected)))
            t.check(f'layout {mask:04b}: independent extra outputs are composed',error<.002,error=error)

    approximate=(1<<26)|(1<<27)
    native=t.dispatch('FSRDInputConv',dict(cb,Flags=cb['Flags']|approximate),inputs,formats,(w,h))
    t.check('valid native specular/ray distances override approximation',
            np.array_equal(native[0][...,3],baseline[0][...,3]) and np.array_equal(native[1][...,3],baseline[1][...,3]))
    missing=dict(cb,Flags=(1<<1)|(1<<5),DiffuseHitDistanceMode=0)
    off=t.dispatch('FSRDInputConv',missing,inputs,formats,(w,h))
    on=t.dispatch('FSRDInputConv',dict(missing,Flags=missing['Flags']|approximate),inputs,formats,(w,h))
    t.check('missing distances remain absent with approximation disabled',np.all(off[0][...,3]<0) and np.all(off[1][...,3]==65504))
    t.check('explicit approximations use finite primary view depth',np.allclose(on[0][...,3],10,atol=.02) and np.all(on[1][...,3]==10))
    t.check('approximation changes metadata only, not packed RGB',np.array_equal(off[0][...,:3],on[0][...,:3]) and np.array_equal(off[1][...,:3],on[1][...,:3]))
    inputs[5]=np.full((h,w),65504,np.float32); inputs[13]=t.rgba(w,h,(65504,)*3,65504)
    sky=t.dispatch('FSRDInputConv',dict(cb,Flags=cb['Flags']|approximate),inputs,formats,(w,h))
    t.check('native environment misses are not replaced by approximate hits',np.all(sky[0][...,3]==65504) and np.all(sky[1][...,3]==65504))
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'signal mode GPU contract failed'
    print(f'{len(t.checks)} checks passed; {len(t.timings)} production shader dispatches')

if __name__=='__main__': run()
