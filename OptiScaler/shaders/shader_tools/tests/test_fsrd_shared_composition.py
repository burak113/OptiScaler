"""Shared regional statistics versus weighted fallback on actual DXIL."""
import json,re
import numpy as np
import run_fsrd_gpu_tests as t


def run():
    t.OUT=t.OUT.parent/'shared_composition';t.OUT.mkdir(parents=True,exist_ok=True)
    t.build_runner()
    source=(t.PRE/'FSRDOutputComp.hlsl').read_text()
    body=source.split('QuartileNetwork[',1)[1].split('{',1)[1].split('}',1)[0]
    network=list(map(int,re.findall(r'\d+',body)))
    rng=np.random.default_rng(89274)
    # Exact 64-bit encoding used by the shader's two UINT words, including the
    # centre whose 3x3 stencil starts at bit 32.
    masks=rng.integers(0,1<<49,20000,dtype=np.uint64)
    masks[:100]=np.uint64((1<<49)-1)
    for oy in range(-2,3):
        for ox in range(-2,3):
            shift=(oy+2)*7+ox+2
            lo=(0x1c387<<shift)&0xffffffff if shift<32 else 0
            hi=0x1c387 if shift==32 else (0x1c387>>(32-shift) if shift>15 else 0)
            actual=((masks & np.uint64(0xffffffff)) & lo)==lo
            actual &= ((masks>>np.uint64(32)) & hi)==hi
            expected=np.ones(len(masks),bool)
            for dy in range(-1,2):
                for dx in range(-1,2):
                    expected &= ((masks>>np.uint64((oy+dy+3)*7+ox+dx+3))&1)!=0
            t.check(f'bit-parallel blur acceptance offset={ox},{oy}',np.array_equal(actual,expected))
    samples=rng.normal(size=(20000,25)).astype(np.float32)
    for count in range(9,26): samples[(count-9)*100:(count-8)*100,count:]=1e20
    expected=np.sort(samples,axis=1)[:,:7].copy()
    for a,b in zip(network[::2],network[1::2]):
        low=np.minimum(samples[:,a],samples[:,b]);samples[:,b]=np.maximum(samples[:,a],samples[:,b]);samples[:,a]=low
    t.check('pruned network retains exact ranks 0 through 6',np.array_equal(samples[:,:7],expected),comparators=len(network)//2)
    w,h=48,40;y,x=np.indices((h,w));zero=t.rgba(w,h,(0,0,0));a=t.rgba(w,h,(1,1,1))
    normal=t.rgba(w,h,(.5,.5,.1),1/3)
    fallback=normal.copy();fallback[12,12,:2]=(0,0)
    base=t.rgba(w,h,(.5,.5,.5),.025)
    for c,phase in enumerate((0,1.4,2.8)):
        base[...,c]+=.12*np.sin(x*.57+y*.17+phase)+.10*np.cos(y*.71-phase)
    rr=base.copy();rr[...,:3]=.5+.7*(base[...,:3]-.5)
    # The changed guide lies outside pixel (20,20)'s entire 9x9 footprint but
    # inside its shared tile. It forces the slow path without changing its data.
    def comp(ref,rr,z,n,mode):
        return t.dispatch('FSRDOutputComp',dict(DstTexSize=[w,h,1/w,1/h],
            DetailPreservation=1.0,FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,
            Flags=mode),[zero,a,rr,a,zero,n,ref,z],[10],(w,h))[0][20,20,:3]
    for scale in (.001,1,1024):
        ref=base*scale;r=rr.copy();r[...,:3]*=scale
        for sign in (-1,1):
            for slope in (0,.002,'perspective'):
                z=(sign/(.1+.0004*x+.0002*y) if slope=='perspective' else
                   sign*(12+x*slope+y*slope*.5)).astype(np.float32)
                for mode in (0,(1<<16)|(1<<17),(1<<16)|(22<<17),(1<<16)|(23<<17)):
                    fast=comp(ref,r,z,normal,mode);slow=comp(ref,r,z,fallback,mode)
                    error=float(np.max(np.abs(fast-slow)))
                    t.check(f'shared/fallback parity scale={scale} sign={sign} slope={slope} mode={mode}',
                            error <= (max(scale*.001,1e-6) if mode==0 else .002),max_error=error)
    (t.OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings),indent=2))
    assert all(c['passed'] for c in t.checks),'shared-statistic regression'


if __name__=='__main__':run()
