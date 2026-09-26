"""V10: independent small/chromatic screen fixtures against the accepted V9.

Explicit Anchor=4, Mix=1 in both versions is the user's accepted game setting.
These fixtures execute actual DXIL but do not run AMD RR.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur
from fsrd_references import require_reference


def run():
    archive = require_reference('zero_rough_v9')
    t.OUT=t.OUT.parent/'small_colour_screen';t.OUT.mkdir(exist_ok=True)
    t.build_runner()
    w,h=81,65; y,x=np.indices((h,w)); rng=np.random.default_rng(10907)
    z=np.full((h,w),10,np.float32)
    normal=t.rgba(w,h,(.5,.5,.1),1/3)
    a=t.rgba(w,h,(1,1,1));zero=t.rgba(w,h,(0,0,0))
    crop=(slice(6,-6),slice(6,-6),slice(0,3))
    def comp(rr,ref,directory=t.PRE,anchor=4,mix=1,flags=0,detail=1.0,n=normal):
        return t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
            'DetailPreservation':detail,'FloorHandoverAnchorClamp':anchor,
            'FloorHandoverCorrelationMix':mix,'Flags':flags},
            [zero,a,rr,a,zero,n,ref,z],[10],(w,h),directory=directory)[0]
    def rms(out,target):return float(np.sqrt(np.mean((out[crop]-target[crop])**2)))
    glyph=np.array(list('11111100001111010000100001000010000'),dtype=int).reshape(7,5).astype(bool)
    clean=t.rgba(w,h,(.4,.4,.4))
    # Luminance is mathematically constant; chromatic structure is real, not noise.
    red=.22*np.sin(x*.55+y*.13)+.08*np.cos(y*.6)
    blue=.18*np.sin(x*.2-y*.7)
    clean[...,0]+=red;clean[...,2]+=blue
    clean[...,1]-=(.2126*red+.0722*blue)/.7152
    ink=np.zeros((h,w),bool)
    for row in (12,31,47):
        for col in range(8,70,9):ink[row:row+7,col:col+5]=glyph
    clean[ink,:3]=[.75,.4-.35*.2126/.7152,.4]
    for sigma in (0,.02):
        noisy=clean.copy();noisy[...,:3]+=rng.normal(0,sigma,noisy[...,:3].shape)
        ref=t.seed(noisy)[3]
        for passes in (1,3):
            rr=blur(np.roll(clean,1,axis=1),passes)
            old=comp(rr,ref,archive);new=comp(rr,ref)
            eo,en=rms(old,clean),rms(new,clean)
            t.check(f'chromatic small-screen detail improves sigma={sigma} blur={passes}',
                    en<eo*.95,v9=eo,current=en,rr=rms(rr,clean))
    # Small corners and strokes surrounded by another colour: NLM must not let
    # eight background pixels swamp its centre while evaluating patch similarity.
    texture=t.rgba(w,h,(.6,.52,.46));texture[ink,:3]=[.2,.25,.3]
    noisy=texture.copy();noisy[...,:3]+=rng.normal(0,.035,noisy[...,:3].shape)
    ref=t.seed(noisy)[3]
    old=comp(texture,ref,archive,flags=(1<<16)|(8<<17))
    new=comp(texture,ref,flags=(1<<16)|(8<<17))
    before=float(np.mean(np.abs(old[ink,:3]-texture[ink,:3])))
    after=float(np.mean(np.abs(new[ink,:3]-texture[ink,:3])))
    t.check('centre-aware matching preserves small glyph samples',after<before*.9,
            v9_ink_error=before,current_ink_error=after)
    t.check('small glyph preservation also improves the whole reference',rms(new,texture)<rms(old,texture)*.95,
            v9_rms=rms(old,texture),current_rms=rms(new,texture))
    t.records.append(dict(metric='small glyph filtered reference',v9_ink_error=before,current_ink_error=after,
                          v9_rms=rms(old,texture),current_rms=rms(new,texture)))
    # Different sizes and diagonal samples: do not win only on one binary font.
    for size in (1,2,4):
        pattern=t.rgba(w,h,(0,0,0))
        for ch,phase in enumerate((0,1.3,2.7)):
            pattern[...,ch]=.45+.2*np.sin((x*.8+y*.35)/size+phase)+.12*np.cos((y*.9-x*.25)/size+phase)
        pattern[((x+2*y)%(11*size))<size,:3]=(.07,.11,.16)
        ref=t.seed(pattern)[3];rr=blur(np.roll(pattern,1,axis=1),2)
        old=comp(rr,ref,archive);new=comp(rr,ref)
        t.check(f'mixed RGB and diagonal content does not regress at scale={size}',
                rms(new,pattern)<=rms(old,pattern)+.001,v9=rms(old,pattern),current=rms(new,pattern))
    large=t.rgba(w,h,(.65,.55,.4))
    big=np.repeat(np.repeat(glyph,5,axis=0),5,axis=1)
    large[14:49,26:51,:3][big]=(.12,.18,.25)
    ref=t.seed(large)[3];rr=blur(np.roll(large,1,axis=1),3)
    old=comp(rr,ref,archive);new=comp(rr,ref)
    t.check('large screen accepted reconstruction does not regress',
            rms(new,large)<=rms(old,large)+.001,v9=rms(old,large),current=rms(new,large))
    # Noise-rejection nonregression against V9 at the SAME anchor, both flat and
    # textured, independently varying noise frames, including coarse colour blobs.
    for label,target in [('flat',t.rgba(w,h,(.4,.4,.4))),('lettering',texture),('colour',clean)]:
        errors={'v9':[],'current':[]}
        for frame in range(3):
            noise=t.rgba(w,h,(0,0,0));noise[...,:3]=rng.normal(0,1,noise[...,:3].shape)
            noise=blur(noise,10)[...,:3];noise*=.085/np.std(noise)
            noisy=target.copy();noisy[...,:3]=np.maximum(target[...,:3]+noise+rng.normal(0,.025,noise.shape),0)
            ref=t.seed(noisy)[3]
            errors['v9'].append(rms(comp(target,ref,archive),target))
            errors['current'].append(rms(comp(target,ref),target))
        e0,e1=float(np.mean(errors['v9'])),float(np.mean(errors['current']))
        t.check(label+' accepted V9 grain rejection retained',e1<=max(.002,e0*1.1),v9=e0,current=e1)
    # Q's colour moments include Skip too. Preserve actual Floor + conversion
    # routing here: a clean full-image RR input would hide that shared-noise risk.
    from test_fsrd_zero_rough_screen import chain_cb
    for label,target in [('lettering',texture),('colour',clean)]:
        noise=t.rgba(w,h,(0,0,0));noise[...,:3]=rng.normal(0,1,noise[...,:3].shape)
        grain=blur(noise,10)[...,:3];grain*=.085/np.std(grain)
        current=target.copy();current[...,:3]=np.maximum(target[...,:3]+grain+rng.normal(0,.025,grain.shape),0)
        f,depth,guide,ref=t.seed(current)
        floor=t.filter_floor(f,depth,guide,a)
        packed=t.dispatch('FSRDInputConv',chain_cb(w,h,(1<<1)|(1<<7)),
            [current,depth,zero,t.rgba(w,h,(0,0,1)),np.zeros((h,w),np.float32),depth,
             a,a,zero,floor,zero,zero,zero,zero,depth,zero,ref],
            [10,10,10,24,28,28,10,10],(w,h))
        residual=zero.copy()
        residual[...,:3]=np.maximum(target[...,:3]-packed[6][...,:3],0)/np.maximum(packed[5][...,:3],1e-5)
        errors={}
        for version,directory in [('v9',archive),('current',t.PRE)]:
            out=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
                'DetailPreservation':1.0,'FloorHandoverAnchorClamp':4.,
                'FloorHandoverCorrelationMix':1.},
                [zero,packed[4],residual,packed[5],packed[6],packed[3],packed[7],depth],
                [10],(w,h),directory=directory)[0]
            errors[version]=rms(out,target)
        t.check(label+' grain with real Skip remains bounded against V9',
                errors['current']<=max(.002,errors['v9']*1.1),**errors)
    # Large screen/static RR, HDR, ordinary material and controls-off contracts.
    reference=t.seed(clean)[3]
    # Zero Mix must remove correlation rejection. Comparing full colour against
    # V9 conflated that contract with NLM identity: the post-checkpoint filter now
    # intentionally preserves more detail even while both RR controls are off.
    weights=comp(blur(clean,2),reference,anchor=0,mix=0,flags=(1<<16)|(16<<17))
    t.check('disabling mix removes all colour agreement rejection',np.all(weights[...,2]==1))
    for level in (.001,1,40):
        target=clean*level;target[...,3]=0
        ref=t.seed(target)[3];out=comp(target,ref)
        t.check(f'already sharp colour unchanged scale={level}',
                rms(out,target)<.001*level,rms=rms(out,target))
    ordinary=normal.copy();ordinary[...,3]=0
    rr=blur(clean,2)
    t.check('ordinary material remains bit-identical to V9',
            np.array_equal(comp(rr,reference,n=ordinary),comp(rr,reference,archive,n=ordinary)))
    t.check('detail disabled remains bit-identical to V9',
            np.array_equal(comp(rr,reference,detail=0),comp(rr,reference,archive,detail=0)))
    reference[...,3]=-1
    t.check('routed content remains bit-identical to V9',
            np.array_equal(comp(rr,reference),comp(rr,reference,archive)))
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'records':t.records,'dispatches':t.timings},indent=2))
    print(json.dumps(t.records,indent=2))
    assert all(c['passed'] for c in t.checks),'small/chromatic screen regression'


if __name__=='__main__':run()
