"""Screen-only handover and full-radiance RR routing, using production DXIL.

RR is an independent synthetic input here, not AMD model inference.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_zero_rough_screen import chain_cb


def run():
    t.OUT=t.OUT.parent/'screen_only_handover';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    w,h=53,37;y,x=np.indices((h,w));roi=(slice(4,-4),slice(4,-4))
    zero=t.rgba(w,h,(0,0,0));unit=t.rgba(w,h,(1,1,1))
    depth=np.full((h,w),10,np.float32)
    normal=t.rgba(w,h,(0,0,1));a=t.rgba(w,h,(.7,.7,.7));s=t.rgba(w,h,(.04,.04,.04))
    raw=t.rgba(w,h,(.4,.45,.5));raw[...,:3]+=.08*np.sin(x*.7)[...,None]
    raw[...,:3]+=np.random.default_rng(51).normal(0,.025,(h,w,3))
    f,z,g,ref=t.seed(raw,depth=depth,normal=normal,albedo=a)
    f=t.filter_floor(f,z,g,a)
    packed=[]
    for detail in (0,.35,1):
        cb=chain_cb(w,h,(1<<1)|(1<<7),detail=detail)
        p=t.dispatch('FSRDInputConv',cb,
            [raw,z,zero,normal,np.zeros((h,w),np.float32),z,a,s,zero,f,zero,zero,zero,zero,z,zero,ref],
            [10,10,10,24,28,28,10,10],(w,h))
        packed.append(p)
        t.check(f'selected screen Skip exactly zero detail={detail}',np.all(p[6][roi][...,:3]==0))
        t.check(f'RR roughness floor independent of detail={detail}',np.min(p[3][roi][...,2])>.09)
        remod=p[0][...,:3]*p[4][...,:3]+p[1][...,:3]*p[5][...,:3]
        t.check(f'full current signal reaches RR detail={detail}',np.max(np.abs(remod[roi]-raw[roi][...,:3]))<.001)
    for i in (1,2):
        t.check(f'detail cannot change RR signal split variant={i}',all(np.array_equal(packed[0][j],packed[i][j]) for j in range(7)))

    # Mixed groups and partial edge groups: material type, not reference alpha,
    # determines which pixels receive correction or valid temporal decisions.
    sharp=t.rgba(w,h,(.4,.4,.4),0);sharp[:,x[0]%7<2,:3]=.9
    rr=t.rgba(w,h,(.4,.4,.4))
    for kind in ('ordinary','screen','mixed'):
        n=t.rgba(w,h,(.5,.5,.1),0)
        selected=np.zeros((h,w),bool)
        if kind=='screen':selected[:]=True
        if kind=='mixed':selected=(x>=w//2)&(y>3)
        n[selected,3]=1/3
        history=t.rgba(w,h,(1,1,1),1);motion=t.rgba(w,h,(0,0,0),1)
        def comp(detail,anchor,mix,flags=0):
            return t.dispatch('FSRDOutputComp',dict(DstTexSize=[w,h,1/w,1/h],
                DetailPreservation=detail,FloorHandoverAnchorClamp=anchor,
                FloorHandoverCorrelationMix=mix,Flags=flags,WriteHistory=1),
                [zero,unit,rr,unit,zero,n,sharp,z,motion,history,np.zeros((h,w,4),np.uint32)],
                [10,10,3],(w,h))
        off=comp(0,0,0)
        free=comp(1,0,0)
        bounded=comp(1,4,1)
        debug=comp(1,4,1,(1<<16)|(19<<17))  # CompositionFinal
        if np.any(~selected):
            t.check(kind+' ordinary pixels have exactly no correction',
                np.array_equal(free[0][~selected],off[0][~selected]) and np.array_equal(bounded[0][~selected],off[0][~selected]))
            t.check(kind+' ordinary history invalidated',
                np.all(bounded[1][~selected]==-1) and np.all((bounded[2][~selected,1]&0x80000000)==0),
                decision_min=float(np.min(bounded[1][~selected])),decision_max=float(np.max(bounded[1][~selected])),
                valid_count=int(np.count_nonzero(bounded[2][~selected,1]&0x80000000)),
                decision_samples=np.unique(bounded[1][~selected],axis=0)[:8].tolist())
        if np.any(selected):
            t.check(kind+' selected screens still restore detail',np.max(np.abs(free[0][selected]-off[0][selected]))>.1)
            t.check(kind+' screen anchor still constrains grain',np.array_equal(bounded[0][selected],off[0][selected]))
        t.check(kind+' debug and normal composition agree',np.array_equal(debug[0],bounded[0]))
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks),'screen-only routing regression'


if __name__=='__main__':run()
