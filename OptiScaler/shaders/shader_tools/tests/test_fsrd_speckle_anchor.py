"""Independent sparse-ray fixtures and zero-rough anchor/correlation controls."""
import json
import numpy as np
import run_fsrd_gpu_tests as t

def run():
    t.OUT=t.OUT.parent/'speckle_anchor';t.OUT.mkdir(parents=True,exist_ok=True);t.build_runner()
    w,h=49,41;y,x=np.indices((h,w));rng=np.random.default_rng(873)
    clean=t.rgba(w,h,(.15,.15,.15));c=clean.copy()
    rays=rng.random((h,w))<.10
    c[rays,:3]+=rng.uniform(.2,1.2,(rays.sum(),3))
    z=np.full((h,w),10,np.float32)
    fragmented=10+((x%3)+3*(y%3)).astype(np.float32)*5
    original=t.dispatch
    for version in ('spatial_v2','spatial_v3','zero_rough_v7','current'):
        directory=t.PRE if version=='current' else t.reference(version)
        if directory is None:
            t.skip('sparse-ray historical measurements '+version)
            continue
        def archived(shader,values,inputs,formats,size,**kw):
            return original(shader,values,inputs,formats,size,directory=directory,**kw)
        t.dispatch=archived
        for label,depth in [('supported',z),('fragmented',fragmented)]:
            f,d,g,r=t.seed(c,depth=depth)
            for material in (0,1):
                n=t.rgba(w,h,(.5,.5,.1),material/3)
                o=t.compose(clean,r,d,n,clean)
                err=np.max(np.abs(o[...,:3]-clean[...,:3]),axis=2)
                if version=='current':
                    t.check(f'{label} sparse rays do not return through detail material={material}',
                            np.sum(err>.02)==0,maximum=float(err.max()))
                    if material==0:
                        t.check(f'{label} lower-tail pedestal rejects coloured rays including border',
                                np.max(f[...,:3]-.15)<.02,maximum=float(np.max(f[...,:3])))
                t.records.append(dict(version=version,guide=label,material=material,
                    detail_speckles=int(np.sum(err>.02)),detail_max=float(err.max()),
                    pedestal_speckles=int(np.sum(np.max(f[...,:3]-.15,axis=2)>.02))))
    t.dispatch=original
    normal=t.rgba(w,h,(.5,.5,.1),1/3);zero=t.rgba(w,h,(0,0,0));ones=t.rgba(w,h,(1,1,1))
    def comp(rr,ref,anchor,mix):
        return original('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
            'DetailPreservation':1.0,'FloorHandoverAnchorClamp':anchor,'FloorHandoverCorrelationMix':mix},
            [zero,ones,rr,ones,zero,normal,ref,z],[10],(w,h))[0]
    ref=clean.copy();ref[...,3]=0;ref[h//2,w//2]=[1,1,1,.4]
    off=comp(clean,ref,0,0);on=comp(clean,ref,2,0)
    t.check('anchor clamps uncertain isolated transfer toward RR',
            on[h//2,w//2,0]<off[h//2,w//2,0]-.1,
            off=float(off[h//2,w//2,0]),on=float(on[h//2,w//2,0]))
    ref=t.rgba(w,h,(0,0,0),.06);ref[...,:3]=(.5+.4*np.sin(x*.6))[...,None]
    rr=ref.copy();rr[...,:3]+=.065
    off=comp(rr,ref,0,0);on=comp(rr,ref,0,1)
    before=float(np.mean(np.abs(off[...,:3]-rr[...,:3])))
    after=float(np.mean(np.abs(on[...,:3]-rr[...,:3])))
    t.check('correlation mix prefers agreeing RR',after<before*.8,off=before,on=after)
    ordinary=normal.copy();ordinary[...,3]=0
    def ordinary_comp(anchor,mix):
        return original('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],
            'DetailPreservation':1.0,'FloorHandoverAnchorClamp':anchor,'FloorHandoverCorrelationMix':mix},
            [zero,ones,rr,ones,zero,ordinary,ref,z],[10],(w,h))[0]
    t.check('handover controls do not affect ordinary materials',
            np.array_equal(ordinary_comp(0,0),ordinary_comp(2,1)))
    t.check('ordinary reconstruction retains RR exactly',
            np.array_equal(ordinary_comp(2,1)[...,:3],rr[...,:3].astype(np.float16).astype(np.float32)))
    print(json.dumps(t.records,indent=2))
    (t.OUT/'diagnosis.json').write_text(json.dumps(t.records,indent=2))
    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'records':t.records,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'speckle/anchor regression'

if __name__=='__main__':run()
