"""Production DXIL surface selection, original-albedo and routing contracts.

These are synthetic evidence/false-positive tests, not recognition accuracy for
arbitrary games. No AMD model is executed and emission is not observable here.
"""
import json
import numpy as np
import run_fsrd_gpu_tests as t
from test_fsrd_zero_rough_screen import chain_cb


def run():
    t.OUT = t.OUT.parent/'surface_selection'
    t.OUT.mkdir(parents=True, exist_ok=True)
    t.build_runner()
    w,h = 53,37
    y,x = np.indices((h,w), dtype=np.float32)
    normal = t.rgba(w,h,(0,0,1))
    depth = np.full((h,w),10,np.float32)
    diffuse = t.rgba(w,h,(.7,.7,.7))
    specular = t.rgba(w,h,(.04,.04,.04))
    zero = t.rgba(w,h,(0,0,0))
    crop = (slice(4,-4),slice(4,-4))
    pattern = t.rgba(w,h,(.4,.4,.4))
    pattern[...,0] += .2*np.sin(x*.85)
    pattern[...,1] += .14*np.cos(y*.71)
    pattern[...,2] += .2*np.sin(x*.85+1.3)

    def convert(colour=pattern, diff=diffuse, spec=specular, z=depth, n=normal,
                rough=.35, enabled=True, ref=None, base=None, packed_rough=False,
                bias=None, extra_flags=0, overrides=None, floor=zero):
        if ref is None:
            ref = t.seed(colour,depth=z,normal=n,albedo=diff)[3]
        shape = colour.shape[:2]
        hh,ww = shape
        empty = t.rgba(ww,hh,(0,0,0))
        r = np.full(shape,rough,np.float32)
        n = n.copy()
        if packed_rough: n[...,3] = rough
        flags = (1<<1) | ((1<<7) if enabled else 0) | extra_flags
        if packed_rough: flags |= 1<<2
        if bias is not None: flags |= 1<<15
        cb = chain_cb(ww,hh,flags)
        if overrides: cb.update(overrides)
        if base:
            # Different origins for every external title resource. Internals,
            # including canonical depth and reference, remain render-sized.
            def padded(a,offset):
                ox,oy=offset
                b=np.full((hh+oy+3,ww+ox+3,*a.shape[2:]),.91,np.float32)
                b[oy:oy+hh,ox:ox+ww]=a
                return b
            colour=padded(colour,(3,2)); n=padded(n,(2,4)); r=padded(r,(5,1))
            diff=padded(diff,(1,3)); spec=padded(spec,(4,2))
            cb.update(InputBase0=[3,2,0,0],InputBase1=[2,4,5,1],
                      InputBase2=[0,0,1,3],InputBase3=[4,2,0,0])
        return t.dispatch('FSRDInputConv',cb,
            [colour,z,empty,n,r,z,diff,spec,bias if bias is not None else empty,
             floor,empty,empty,empty,empty,z,empty,ref],
            [10,10,10,24,28,28,10,10],(ww,hh))

    def selected(p): return p[3][...,3] > .16
    def fraction(p,area=crop): return float(np.mean(selected(p)[area]))

    # Existing CP77 cue remains useful, but albedo/surface validity is mandatory.
    flat = t.rgba(w,h,(.4,.4,.4))
    legacy = convert(flat,rough=0)
    t.check('flat valid zero-rough CP77 hint remains selected',fraction(legacy)==1)
    t.check('eligible zero rough receives local RR compatibility floor',
            np.max(np.abs(legacy[3][crop][...,2]-.1))<1/1023)

    for rough in (.0008,.05,.35,.8):
        p=convert(rough=rough)
        t.check(f'unrepresented RGB structure does not require zero roughness {rough}',
                fraction(p)>.95,selected_fraction=fraction(p))
        t.check(f'roughness is a floor not an addition {rough}',
                np.max(np.abs(p[3][crop][...,2]-max(rough,.1)))<1.5/1023)

    # Equal-luminance colours cannot disappear from either side of the evidence.
    isoluma=t.rgba(w,h,(.45,.45,.45))
    isoluma[...,0]+=.24*np.sin(x*.85)
    isoluma[...,1]-=(.2126/.7152)*.24*np.sin(x*.85)
    t.check('equal-luma radiance texture selected with flat albedo',
            fraction(convert(isoluma))>.95)
    for label,da,sa in [('diffuse',isoluma,specular),('specular',diffuse,isoluma)]:
        for rough in (0,.35):
            p=convert(diff=da,spec=sa,rough=rough)
            t.check(f'{label} RGB albedo structure vetoes special handover rough={rough}',
                    fraction(p)==0,selected_fraction=fraction(p))

    rng=np.random.default_rng(1029070)
    ramp=t.rgba(w,h,(.2,.25,.3)); ramp[...,:3]+=(x*.002+y*.003)[...,None]
    for label,c in [('constant',flat),('smooth RGB lighting ramp',ramp)]:
        p=convert(c)
        t.check(label+' is not sufficient surface evidence',fraction(p)==0)
    for sigma in (.01,.08,.2):
        c=flat.copy();c[...,:3]=np.maximum(c[...,:3]+rng.normal(0,sigma,(h,w,3)),0)
        p=convert(c)
        t.check(f'unstructured illumination grain rejected sigma={sigma}',
                fraction(p)<.005,selected_fraction=fraction(p))
    c=flat.copy();c[17,26,:3]=100
    p=convert(c)
    t.check('isolated bright ray is not a textured surface',fraction(p)==0)

    # Selection must survive illumination grain on a real pattern, not only
    # classify ideal clean textures. These frames have no accumulated history.
    masks=[]
    for frame in range(3):
        c=pattern.copy();c[...,:3]+=rng.normal(0,.01,(h,w,3))
        p=convert(c)
        masks.append(selected(p)[crop])
        t.check(f'noisy nonzero-rough texture retains selection frame={frame}',
                fraction(p)>.95,selected_fraction=fraction(p))
        out=t.compose(pattern,p[7],depth,p[3],diffuse)
        before=float(np.sqrt(np.mean((c[crop][...,:3]-pattern[crop][...,:3])**2)))
        after=float(np.sqrt(np.mean((out[crop][...,:3]-pattern[crop][...,:3])**2)))
        t.check(f'newly selected surface does not undo clean RR frame={frame}',
                after<before*.5,input_noise=before,output_error=after)
    flips=float(np.mean(masks[0]!=masks[1]))
    t.check('high-SNR selection stable across independent noise realizations',flips<.02,flip_fraction=flips)

    for label,da,sa in [('pure mirror',zero,t.rgba(w,h,(.9,.9,.9))),
                        ('specular dominant',t.rgba(w,h,(.1,.1,.1)),t.rgba(w,h,(.9,.9,.9))),
                        ('missing guides',zero,zero),
                        ('dark guides',t.rgba(w,h,(.001,.001,.001)),specular),
                        ('nonfinite guide',t.rgba(w,h,(np.nan,.7,.7)),specular),
                        ('negative guide',t.rgba(w,h,(-.1,.7,.7)),specular)]:
        p=convert(diff=da,spec=sa,rough=0,ref=pattern)
        t.check(label+' cannot authorize handover even with zero roughness',not np.any(selected(p)))
        t.check(label+' keeps original roughness',np.all(p[3][...,2]==0))

    for label,n,z in [('missing normal',zero,depth),
                      ('independently discontinuous geometry',normal,10+rng.uniform(0,30,(h,w)).astype(np.float32))]:
        p=convert(n=n,z=z,rough=0,ref=pattern)
        t.check(label+' cannot authorize handover',not np.any(selected(p)))
    slope=10+x*.2+y*.12
    p=convert(z=slope)
    t.check('sloped planar surface retains evidence',fraction(p)>.95,selected_fraction=fraction(p))

    # A textured neighbour behind an edge must not select the blank foreground.
    c=pattern.copy();c[:,:w//2,:3]=.4
    z=depth.copy();z[:,w//2:]=40
    p=convert(c,z=z)
    t.check('silhouette blocks borrowed texture evidence',not np.any(selected(p)[4:-4,:w//2]))
    n=normal.copy();n[:,w//2:,:3]=(1,0,0)
    p=convert(c,n=n)
    t.check('normal boundary blocks borrowed texture evidence',not np.any(selected(p)[4:-4,:w//2]))

    a=diffuse.copy();a[:,w//2:,:3]=.3
    p=convert(diff=a,rough=0)
    t.check('material edge not discarded as inconvenient evidence',
            not np.any(selected(p)[4:-4,w//2-2:w//2+2]))

    p=convert(); off=convert(enabled=False)
    t.check('original RR albedo RGB preserved exactly',
            np.array_equal(p[4][...,:3],off[4][...,:3]) and
            np.array_equal(p[5][...,:3],off[5][...,:3]))
    t.check('no synthetic pattern enters either RR albedo',
            np.max(np.ptp(p[4][...,:3],axis=(0,1)))==0 and
            np.max(np.ptp(p[5][...,:3],axis=(0,1)))==0)
    p2=convert(pattern*2)
    t.check('changing radiance never rewrites albedo RGB',
            np.array_equal(p[4][...,:3],p2[4][...,:3]) and
            np.array_equal(p[5][...,:3],p2[5][...,:3]))
    t.check('Floor off retains original RR roughness and ordinary type',
            np.all(off[3][...,3]==0) and np.max(np.abs(off[3][...,2]-.35))<1/1023)
    off0=convert(rough=0,enabled=False)
    t.check('Floor off preserves pre-existing RR zero-rough material encoding',
            np.all(off0[3][...,3]==np.float32(1/3)) and np.all(off0[3][...,2]==0))
    t.check('Floor off disallows detail reference',np.all(off[7][...,3]<0))
    pbase=convert(base=True)
    t.check('independent subrect origins preserve selection and signals',
            all(np.array_equal(a,b) for a,b in zip(p,pbase)))
    pp=convert(packed_rough=True)
    t.check('packed and separate roughness agree',all(np.array_equal(a,b) for a,b in zip(p,pp)))

    bias=np.ones((h,w),np.float32)
    pb=convert(rough=0,bias=bias)
    t.check('explicitly routed content cannot enter special handover',
            not np.any(selected(pb)) and np.all(pb[7][...,3]<0))
    badref=pattern.copy();badref[...,3]=-1
    t.check('invalid reference cannot lend structure',not np.any(selected(convert(ref=badref,rough=0))))

    # End-to-end closure for newly selected nonzero roughness, including F>C.
    pedestal=t.rgba(w,h,(.9,.8,.7))
    pc=convert(floor=pedestal)
    out=t.dispatch('FSRDOutputComp',{'DstTexSize':[w,h,1/w,1/h],'DetailPreservation':0},
        [pc[0],pc[4],pc[1],pc[5],pc[6],pc[3],pc[7],depth],[10],(w,h))[0]
    error=float(np.max(np.abs(out[crop][...,:3]-pattern[crop][...,:3])))
    t.check('selected nonzero-rough surface caps pedestal and closes identity RR',error<.002,error=error)
    for level in (.001,40,12000):
        c=pattern.copy();c[...,:3]*=level
        pp=convert(c)
        t.check(f'HDR/exposure invariant structure selection {level}',
                fraction(pp)>.95,selected_fraction=fraction(pp))

    for ww,hh in ((1,1),(1,9),(9,1),(7,5)):
        c=t.rgba(ww,hh,(.4,.4,.4));z=np.full((hh,ww),10,np.float32)
        a=t.rgba(ww,hh,(.7,.7,.7));n=t.rgba(ww,hh,(0,0,1))
        pp=convert(c,diff=a,spec=a,z=z,n=n,rough=0,ref=c,floor=t.rgba(ww,hh,(0,0,0)))
        t.check(f'partial groups and independent support {ww}x{hh}',
                not np.any(selected(pp)) if min(ww,hh)==1 else np.all(selected(pp)))

    (t.OUT/'results.json').write_text(json.dumps({'checks':t.checks,'dispatches':t.timings},indent=2))
    assert all(c['passed'] for c in t.checks),'surface selection regression'


if __name__=='__main__': run()
