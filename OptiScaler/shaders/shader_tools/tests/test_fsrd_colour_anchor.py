"""Production DXIL against immutable V10; targets defined independently.

Colour-correlated artwork with unrelated fine/coarse noise, new animated palettes,
exposure changes, and real Floor/Skip. This runner does NOT execute AMD RR.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_panel_recovery import blur
from fsrd_references import require_reference


def run():
    archive = require_reference('zero_rough_v10')
    t.OUT = t.OUT.parent/'colour_anchor'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w,h = 73,59
    y,x = np.indices((h,w))
    depth = np.full((h,w),10,np.float32)
    normal = t.rgba(w,h,(.5,.5,.1),1/3)
    albedo = t.rgba(w,h,(1,1,1))
    zero = t.rgba(w,h,(0,0,0))
    crop = (slice(6,-6),slice(6,-6),slice(0,3))
    def rms(out,target): return float(np.sqrt(np.mean((out[crop]-target[crop])**2)))
    def comp(rr,ref,directory=t.PRE,anchor=4,mix=1,flags=0,detail=.35,n=normal,z=depth,a=albedo,skip=zero,noise=.75):
        return t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
            'DetailPreservation':detail,'NoiseSuppression':noise,'FloorHandoverAnchorClamp':anchor,
            'FloorHandoverCorrelationMix':mix,'Flags':flags},
            [zero,a,rr,a,skip,n,ref,z],[10],(w,h),directory=directory)[0]
    rng = np.random.default_rng(11819)
    shape = .5+.22*np.sin(x*.39+y*.08)+.16*np.cos(y*.34-x*.12)
    glyph = np.array(list('11111100001111010000100001000010000'),dtype=int).reshape(7,5).astype(bool)
    for row in (9,27,42):
        for col in range(8,62,9): shape[row:row+7,col:col+5][glyph] = .10
    palettes = {'neutral':((.05,.05,.05),(.85,.85,.85)),
                'warm':((.08,.03,.02),(.9,.6,.3)),
                'isoluminant':((.15,.58,.32),(.8,.58-.65*.2126/.7152,.32))}
    grain = {}
    last = None
    for label,(lo,hi) in palettes.items():
        target = t.rgba(w,h,(0,0,0))
        target[...,:3] = np.array(lo)+(np.array(hi)-lo)*shape[...,None]
        results={'v10':[],'current':[]}
        for frame in range(3):
            coarse=t.rgba(w,h,(0,0,0));coarse[...,:3]=rng.normal(0,1,(h,w,3))
            noise=blur(coarse,7)[...,:3];noise*=.07/np.std(noise)
            noisy=target.copy();noisy[...,:3]=np.maximum(target[...,:3]+noise+rng.normal(0,.025,(h,w,3)),0)
            ref=t.seed(noisy)[3]
            for version,directory in [('v10',archive),('current',t.PRE)]:
                results[version].append(rms(comp(target,ref,directory),target))
            last=(target,noisy,ref)
        means={k:float(np.mean(v)) for k,v in results.items()}
        grain[label]=means
        t.check(label+' colour grain decreases at equal 4/1 controls',means['current'] < means['v10']*.97,**means)
    # Do not force the palette of an older animation frame. Independent RGB
    # structure deliberately breaks the single-colour relationship above.
    animation=t.rgba(w,h,(0,0,0))
    for ch,phase in enumerate((0,1.2,2.6)):
        animation[...,ch]=.45+.22*np.sin(x*.73+y*.31+phase)+.12*np.cos(y*.81-x*.19+phase)
    for shift in (0,1,3,7):
        target=np.roll(animation,shift,axis=1)
        ref=t.seed(target)[3];rr=blur(animation,3)
        old,new=comp(rr,ref,archive),comp(rr,ref)
        t.check(f'animated small RGB texture not degraded shift={shift}',rms(new,target)<=rms(old,target)+.001,
                v10=rms(old,target),current=rms(new,target))
    # A hard palette replacement, no correspondence to old content.
    target=animation.copy();target[...,:3]=1-animation[...,2::-1]
    ref=t.seed(target)[3];rr=blur(animation,4)
    old,new=comp(rr,ref,archive),comp(rr,ref)
    t.check('new frame palette remains responsive',rms(new,target)<=rms(old,target)+.001,
            v10=rms(old,target),current=rms(new,target))
    # Same spatial problem at different exposure levels. Measure normalized RMS.
    exposure=[]
    for level in (.01,.1,1,10,100):
        target=animation.copy();target[...,:3]*=level
        ref=t.seed(target)[3];rr=blur(np.roll(target,1,axis=1),3)
        old,new=comp(rr,ref,archive),comp(rr,ref)
        exposure.append({'level':level,'v10':rms(old,target)/level,'current':rms(new,target)/level})
        t.check(f'exposure finite and nonnegative level={level}',np.all(np.isfinite(new)) and np.all(new[...,:3]>=0))
        # The adaptive dark SSIM experiment was rejected: it improved these
        # clean cases but failed the dark correlated-noise cases below. V11
        # retains V10's correlation constants and makes no dark-detail claim.
        t.check(f'exposure texture retained level={level}',rms(new,target)<=rms(old,target)+.001*level,
                v10=rms(old,target)/level,current=rms(new,target)/level)
    t.records.append({'exposure':exposure,'grain':grain})
    # A centre-weight experiment improved flat noise by 1.2% but worsened
    # lettering RMS by 2.8%; it was removed. Keep its fixtures as reference
    # nonregressions, not as evidence for an improvement that was not shipped.
    for label,target in [('flat',t.rgba(w,h,(.4,.4,.4))),('lettering',last[0])]:
        errors={'v10':[],'current':[]}
        for seed in (343,560,910):
            random=np.random.default_rng(seed)
            noisy=target.copy();noisy[...,:3]+=random.normal(0,.04,(h,w,3))
            ref=t.seed(noisy)[3]
            for version,directory in [('v10',archive),('current',t.PRE)]:
                errors[version].append(rms(comp(target,ref,directory,flags=(1<<16)|(8<<17)),target))
        e0,e1=float(np.mean(errors['v10'])),float(np.mean(errors['current']))
        t.check(label+' patch reference retained from V10',abs(e1-e0)<1e-5,v10=e0,current=e1)
    # Held-out noise realizations, independent RGB pattern and exposure. Scaling
    # correlation tolerances must not simply let dark-scene grain return.
    for level in (.01,.1,1):
        for sigma in (.015,.05,.12):
            target=animation.copy();target[...,:3]*=level
            random=np.random.default_rng(607+int(sigma*1000))
            noisy=target.copy()
            noisy[...,:3]=np.maximum(target[...,:3]+random.normal(0,sigma*level,(h,w,3)),0)
            ref=t.seed(noisy)[3]
            old,new=comp(target,ref,archive),comp(target,ref)
            e0,e1=rms(old,target)/level,rms(new,target)/level
            t.check(f'held-out fine grain remains bounded level={level} sigma={sigma}',
                    e1<=max(.001,e0*1.05),v10=e0,current=e1)
    # Preserve actual Skip, including excess lighting; do not hide it with zero.
    from test_fsrd_zero_rough_screen import chain_cb
    target,noisy,ref=last
    for level in (.01,.1):
        darkTarget=target.copy();darkTarget[...,:3]*=level
        darkNoise=noisy.copy();darkNoise[...,:3]*=level
        darkRef=t.seed(darkNoise)[3]
        old,new=comp(darkTarget,darkRef,archive),comp(darkTarget,darkRef)
        e0,e1=rms(old,darkTarget)/level,rms(new,darkTarget)/level
        t.check(f'dark correlated grain remains bounded level={level}',e1<=max(.001,e0*1.05),v10=e0,current=e1)
    f,z,g,ref=t.seed(noisy)
    floor=t.filter_floor(f,z,g,albedo)
    packed=t.dispatch('FSRDInputConv',chain_cb(w,h,(1<<1)|(1<<7)),
        [noisy,z,zero,t.rgba(w,h,(0,0,1)),np.zeros((h,w),np.float32),z,
         albedo,albedo,zero,floor,zero,zero,zero,zero,z,zero,ref],
        [10,10,10,24,28,28,10,10],(w,h))
    residual=zero.copy()
    residual[...,:3]=np.maximum(target[...,:3]-packed[6][...,:3],0)/np.maximum(packed[5][...,:3],1e-5)
    old=comp(residual,packed[7],archive,n=packed[3],a=packed[5],skip=packed[6])
    new=comp(residual,packed[7],n=packed[3],a=packed[5],skip=packed[6])
    t.check('real Floor and Skip grain does not regress',rms(new,target)<=rms(old,target)+.001,
            v10=rms(old,target),current=rms(new,target))
    ref=t.seed(noisy)[3]
    for label,opts in [('anchor and patch filter off',dict(anchor=0,noise=0)),('detail off',dict(detail=0)),
                       ('ordinary',dict(n=t.rgba(w,h,(.5,.5,.1),0)))]:
        t.check(label+' unchanged from V10',np.array_equal(comp(target,ref,archive,**opts),comp(target,ref,**opts)))
    ref[...,3]=-1
    t.check('explicit routing unchanged from V10',np.array_equal(comp(target,ref,archive),comp(target,ref)))
    # Colour evidence remains surface bounded and excludes routed neighbours.
    ref=t.seed(noisy)[3]
    for boundary in ('depth','normal','albedo','routing'):
        z=depth.copy();n=normal.copy();a=albedo.copy();before=ref.copy()
        if boundary=='depth': z[:,w//2:]=40
        elif boundary=='normal': n[:,w//2:,0:2]=0
        elif boundary=='albedo': a[:,w//2:,:3]=.1
        else: before[:,w//2:,3]=-1
        changed=before.copy();changed[:,w//2:,:3]=4
        rr2=target.copy();rr2[:,w//2:,:3]=2
        one=comp(target,before,z=z,n=n,a=a);two=comp(rr2,changed,z=z,n=n,a=a)
        t.check(boundary+' cannot lend palette evidence',np.max(np.abs(one[:,:w//2,:3]-two[:,:w//2,:3]))<.001)
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'records':t.records,'dispatches':t.timings},indent=2))
    print(json.dumps(t.records,indent=2))
    assert all(c['passed'] for c in t.checks),'joint colour anchor regression'


if __name__=='__main__': run()
