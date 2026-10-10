"""Production skin DXIL: routing, bounded separation, surface filters and object motion."""
import os
for _key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_MAX_THREADS'):
    os.environ[_key] = '2'
import psutil
psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
from pathlib import Path
import json
import sys
import subprocess
import time
import numpy as np
import run_fsrd_gpu_tests as t
import fsrd_alpha_common as a

OUT=Path(os.environ.get('FSRD_SKIN_TEST_OUTPUT',
    str(Path(os.environ['FSRD_GPU_TEST_OUTPUT'])/'skin_sss') if 'FSRD_GPU_TEST_OUTPUT' in os.environ else 'E:/FSRD/skin_sss/tests/synthetic'))
OUT.mkdir(parents=True,exist_ok=True)

def gaussian_filter(data, sigmas, mode='nearest', radius=None):
    result=np.asarray(data,np.float32).copy()
    for axis,sigma in enumerate(sigmas):
        if sigma == 0: continue
        r=radius[axis] if radius is not None else int(4*sigma+.5)
        x=np.arange(-r,r+1,dtype=np.float64)
        kernel=np.exp(-.5*(x/sigma)**2);kernel/=kernel.sum()
        result=np.apply_along_axis(lambda v:np.convolve(np.pad(v,(r,r),mode='edge'),kernel,mode='valid'),axis,result).astype(np.float32)
    return result

def prepare(c,g,mode=1,depth=None,diff=None,spec=None,bias=None,**kw):
    h,w=c.shape[:2]
    z=np.ones((h,w),np.float32) if depth is None else depth
    alb=a.rgba(np.full((h,w,3),.25,np.float32))
    zero=np.zeros((h,w),np.float32)
    cb=dict(InvProjMatrix=np.eye(4).ravel(),DstTexSize=[w,h,1/w,1/h],NearPlane=.1,
            FarPlane=10000,Flags=2 | ((1<<15) if bias is not None else 0),Mode=mode,BiasStrength=1,**kw)
    return t._dispatch('FSRDSssPrepare',cb,[c,z,alb if diff is None else diff,
        alb if spec is None else spec,g,zero if bias is None else bias,z],[10,41],(w,h))

def blur(c,g,z,scale=6,strength=.56):
    h,w=c.shape[:2]
    cb=dict(DstTexSize=[w,h,1/w,1/h],SigmaScale=scale,RadiusMeters=.00218,
            Strength=strength,Falloff=1,Vertical=0)
    x=t._dispatch('FSRDSssBlur',cb,[c,g,z,c],[10],(w,h))[0]
    cb['Vertical']=1
    return t._dispatch('FSRDSssBlur',cb,[x,g,z,c],[10],(w,h))[0]

def reference_reblur(c,g,z,scale,strength=1.,falloff=1.):
    """Apply math from Zakrisson e643bf5f, with the two FP16 stores."""
    original=np.asarray(c,np.float16).astype(np.float32)
    depth=np.abs(np.asarray(z,np.float64))
    h,w=depth.shape
    yy,xx=np.indices((h,w))
    sigma_px=scale/np.maximum(depth,1e-3)
    sigma=np.maximum(sigma_px[...,None]*[1.,1.-.6*falloff,1.-.7*falloff],1e-3)
    reach=3*sigma_px
    count=np.minimum(np.ceil(reach),32)
    stride=np.maximum(reach/32,1.)
    tolerance=6*.00218+.01*depth
    valid=(g!=0)&np.isfinite(depth)&(depth>0)
    current=original.copy()
    for vertical in (False,True):
        weighted=np.zeros((h,w,3),np.float64)
        total=np.zeros_like(weighted)
        for i in range(-32,33):
            offset=np.rint(i*stride).astype(np.int32)
            qx=xx if vertical else xx+offset
            qy=yy+offset if vertical else yy
            inside=(qx>=0)&(qx<w)&(qy>=0)&(qy<h)&(abs(i)<=count)
            qx=np.clip(qx,0,w-1);qy=np.clip(qy,0,h-1)
            depth_weight=np.clip(1-np.abs(depth[qy,qx]-depth)/tolerance,0,1)
            take=inside&(g[qy,qx]!=0)
            weight=np.exp(-.5*offset[...,None]**2/sigma**2)*(depth_weight*take)[...,None]
            weighted+=current[qy,qx,:3]*weight
            total+=weight
        blurred=weighted/np.maximum(total,1e-6)
        result=original[...,:3]*(1-strength)+blurred*strength if vertical else blurred
        fallback=original if vertical else current
        current=np.concatenate([np.where(valid[...,None],result,fallback[...,:3]),original[...,3:]],axis=2).astype(np.float16).astype(np.float32)
    return current

def reference_blur_cases():
    w,h=129,9
    yy,xx=np.indices((h,w))
    guide=np.ones((h,w),np.float32)
    colors=a.rgba(np.stack([np.where(xx<64,.1,3.),np.where(xx<64,2.,.15),np.where(xx<64,.3,1.2)],axis=-1).astype(np.float32),alpha=.25)
    gradient=1.+.0015*(xx-64)
    yield 'smooth depth weights match reference',colors,guide,gradient.astype(np.float32),3.14
    stripes=a.rgba(np.stack([np.where(xx%5==0,4.,.1),1.1+np.sin(xx*.17),.1+(xx%3)*.9],axis=-1).astype(np.float32),alpha=.25)
    yield 'continuous wide-kernel stride matches reference',stripes,guide,np.ones((h,w),np.float32),11.21
    signed=np.ones((h,w),np.float32);signed[:,:64]=-1
    yield 'opposite depth signs use absolute view distance',colors,guide,signed,3.14

def prefilter(c,g,z,n,sigma=4):
    h,w=c.shape[:2]
    cb=dict(DstTexSize=[w,h,1/w,1/h],Sigma=sigma,Vertical=0)
    horizontal=t._dispatch('FSRDSkinPrefilter',cb,[c,g,z,n],[10],(w,h))[0]
    cb['Vertical']=1
    return t._dispatch('FSRDSkinPrefilter',cb,[horizontal,g,z,n],[10],(w,h))[0]

def conversion(c,motion=None,previous=None,options=0,guide=None,mode=0):
    h,w=c.shape[:2]
    zeros=np.zeros((h,w,4),np.float32)
    z=np.full((h,w),10,np.float32)
    alb=a.rgba(np.full((h,w,3),.25,np.float32))
    normal=a.rgba(np.broadcast_to([0,0,1],(h,w,3)))
    rough=np.full((h,w),.2,np.float32)
    inputs=[c,z,zeros if motion is None else motion,normal,rough,z,alb,alb,
            z*0,zeros,zeros,zeros,zeros,zeros,z,zeros,c,zeros,
            z if previous is None else previous,
            z*0 if guide is None else guide,c]
    cb=a.conversion_cb(w,h,RecoveryMask=0,SkinOptions=[0,0,mode,options],SkinDebug=[0,0,0,0])
    return t._dispatch('FSRDInputConvSkin',cb,inputs,[10,10,10,24,28,28,10,10,10,10],(w,h)),inputs,cb

def main():
    while psutil.virtual_memory().available < 1.5 * 1024**3:
        time.sleep(30)
    from fsrd_toolchain import compile_cpp
    executable=OUT/'fsrd_skin_input_test.exe'
    compile_cpp(Path(__file__).with_name('fsrd_skin_input_test.cpp'),executable,())
    subprocess.run([str(executable)],check=True,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    rng=np.random.default_rng(67011)
    w=h=64
    z=np.ones((h,w),np.float32)
    guide=np.ones((h,w),np.float32)
    normal=a.rgba(np.broadcast_to([.5,.5,0],(h,w,3)))
    x=(.4+rng.random((h,w,3))*.3).astype(np.float16).astype(np.float32)
    c=gaussian_filter(x,(1.4,1.4,0),mode='nearest').astype(np.float16).astype(np.float32)
    lum=lambda v: (v[...,0]+2*v[...,1]+v[...,2])*.25
    g=lum(c)-lum(x)
    with a.GPUWorker(OUT/'worker') as worker:
        psutil.Process(worker.worker.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        separated,active=prepare(a.rgba(c),g)
        t.check('unclamped separation restores raw lum4 to FP16 tolerance',
                np.max(np.abs(lum(separated)-lum(x))) < .00055)
        zero=prepare(a.rgba(c),g*0)[0]
        t.check('zero guide is bit-exact',np.array_equal(zero,a.rgba(c).astype(np.float16)))
        # Signed values and signed zero expose an accidental radiance clamp
        # before an inactive-guide bypass. Compare decoded FP16 storage bits.
        signed=np.random.default_rng(67012).uniform(-2,2,(h,w,4)).astype(np.float16).astype(np.float32)
        signed[0,0]=[-0.,+0.,-1.,1.]
        for label,mask,options in (
            ('zero',g*0,{}),
            ('null',None,{}),
            ('mode off',guide,dict(mode=0)),
            ('nonfinite',np.full_like(g,np.nan),{}),
            ('bias excluded',guide,dict(bias=np.ones_like(z))),
            ('emissive excluded',guide,dict(diff=a.rgba(np.full_like(c,3)),spec=a.rgba(np.full_like(c,3)))),
            ('sky excluded',guide,dict(depth=z*10000))):
            unchanged,inactive=prepare(signed,mask,**options)
            t.check(f'{label} guide preserves signed source storage exactly',
                np.array_equal(unchanged.astype(np.float32).view(np.uint32),signed.view(np.uint32)) and
                np.all(inactive==0))
        bounded=np.full((h,w,3),.125,np.float32)
        low=prepare(a.rgba(bounded),np.full((h,w),-.9,np.float32))[0]
        high=prepare(a.rgba(bounded),np.full((h,w),1,np.float32))[0]
        t.check('negative clamp at -4 bounds output to five times source',np.all(low[...,:3]==np.float16(.625)))
        t.check('positive clamp at one bounds output to zero',np.all(high[...,:3]==0))
        t.check('mode zero is bit-exact and guide inert',all(np.array_equal(p,q) for p,q in zip(prepare(a.rgba(c),g,0),[a.rgba(c).astype(np.float16),z*0])))
        null_pre,null_mask=prepare(a.rgba(c),None)
        t.check('real null SRV makes separation inert',np.array_equal(null_pre,a.rgba(c).astype(np.float16)) and np.all(null_mask==0))
        for label,overrides in (
            ('bias-masked',dict(bias=np.ones_like(z))),
            ('emissive',dict(diff=a.rgba(np.full_like(c,3)),spec=a.rgba(np.full_like(c,3)))),
            ('far-plane skip',dict(depth=z*10000))):
            original,eligible=prepare(a.rgba(c),guide,**overrides)
            t.check(f'{label} retains game post-SSS colour',
                    np.array_equal(original,a.rgba(c).astype(np.float16)) and np.all(eligible==0))

        field=a.rgba(np.full((h,w,3),.7,np.float32),alpha=.25)
        t.check('reblur strength zero is bit-exact',np.array_equal(blur(field,guide,z,strength=0),field.astype(np.float16)))
        t.check('reblur constant field mean preserved',np.max(abs(blur(field,guide,z)[...,:3].mean((0,1))/.7-1))<.005)
        edge=field.copy();edge[...,:3]=0;edge[:,32:,:3]=1
        depth=z.copy();depth[:,32:]=3
        t.check('reblur respects depth edge',np.array_equal(blur(edge,guide,depth),edge.astype(np.float16)))
        mask=guide.copy();mask[:,32:]=0
        t.check('reblur preserves nonguide pixels exactly',np.array_equal(blur(a.rgba(c),mask,z)[:,32:],a.rgba(c).astype(np.float16)[:,32:]))
        point=np.zeros((h,w,3),np.float32);point[32,32]=1
        a1=blur(a.rgba(point),guide,z,strength=1)[32,:,0]
        a2=blur(a.rgba(point),guide,z*2,strength=1)[32,:,0]
        axis=np.arange(w)-32
        width1=np.sqrt((a1*axis**2).sum()/a1.sum());width2=np.sqrt((a2*axis**2).sum()/a2.sum())
        t.check('reblur sigma halves at twice the depth',abs(width2/width1-.5)<.035)

        for label,signal,reference_mask,dist,scale in reference_blur_cases():
            expected=reference_reblur(signal,reference_mask,dist,scale)
            actual=blur(signal,reference_mask,dist,scale=scale,strength=1.)
            error=np.abs(actual[...,:3]-expected[...,:3])
            tolerance=2*np.abs(np.spacing(expected[...,:3].astype(np.float16))).astype(np.float32)+1e-6
            t.check('reblur '+label,np.all(error<=tolerance),max_error=float(error.max()),
                    max_tolerance=float(tolerance.max()))

        t.check('prefilter constant field mean preserved',np.max(abs(prefilter(field,guide,z,normal)[...,:3].mean((0,1))/.7-1))<.005)
        p=prefilter(a.rgba(c),mask,z,normal)
        t.check('prefilter nonguide bit-exact',np.array_equal(p[:,32:],a.rgba(c).astype(np.float16)[:,32:]))
        t.check('real null guide makes both prefilter passes inert',np.array_equal(prefilter(a.rgba(c),None,z,normal),a.rgba(c).astype(np.float16)))
        t.check('prefilter depth edge holds',np.array_equal(prefilter(edge,guide,depth,normal),edge.astype(np.float16)))
        normal_edge=normal.copy();normal_edge[:,32:,0]=1
        t.check('prefilter normal edge holds',np.array_equal(prefilter(edge,guide,z,normal_edge),edge.astype(np.float16)))
        noise=a.rgba(rng.random((h,w,3)).astype(np.float16).astype(np.float32))
        expected=gaussian_filter(noise[...,:3],(4,4,0),mode='nearest',radius=(10,10,0))
        filtered=prefilter(noise,guide,z,normal)
        # Each separable pass stores FP16; allow one rounding interval per store.
        error=abs(filtered[...,:3]-expected)
        # Intermediate values can cross an FP16 exponent boundary; the source
        # range bounds both positive Gaussian averages, including their ULP.
        tolerance=2*float(np.spacing(noise[...,:3].astype(np.float16)).max())
        t.check('separable prefilter matches full 2D Gaussian on one surface',
                np.all(error<=tolerance),max_error=float(error.max()),max_tolerance=tolerance)

        converted,inputs,cb=conversion(a.rgba(c))
        # Let each production/frozen shader append its optional previous-depth slot.
        # It is not read by the all-off baseline; the frozen ABI ends at t17.
        baseline=t.dispatch('FSRDInputConv',cb,inputs[:18],[10,10,10,24,28,28,10,10,10,10],(w,h))
        t.check('skin conversion all controls off bit-exact in all 10 outputs',all(np.array_equal(x,y) for x,y in zip(converted,baseline)))
        for mode in [1,2]:
            empty,_,_=conversion(a.rgba(c),mode=mode)
            t.check(f'skin mode {mode} zero guide keeps all 10 outputs bit-exact',
                    all(np.array_equal(x,y) for x,y in zip(empty,baseline)))
        static,_,_=conversion(a.rgba(c),options=7)
        t.check('D and E static camera-only scene bit-exact',all(np.array_equal(x,y) for x,y in zip(static,baseline)))
        motion=np.zeros((h,w,4),np.float32);motion[16:48,16:48,0]=2/w
        previous=np.full((h,w),3,np.float32)
        d,_,_=conversion(a.rgba(c),motion,previous,5)
        e,_,_=conversion(a.rgba(c),motion,previous,2)
        both,_,_=conversion(a.rgba(c),motion,previous,7)
        t.check('D moving block gets previous depth minus current depth',np.all(d[2][16:48,16:48,2]==-7))
        t.check('E moving block gets valid zero hit distance',np.all(e[0][16:48,16:48,3]==0))
        outside=np.ones((h,w),bool);outside[16:48,16:48]=False
        t.check('D and E leave static neighbours unchanged',np.array_equal(d[2][outside],baseline[2][outside]) and np.array_equal(e[0][outside],baseline[0][outside]))
        t.check('D and E compose independently',np.array_equal(both[2],d[2]) and np.array_equal(both[0],e[0]))
    failures=sum(not r['passed'] for r in t.checks)
    (OUT/'results.json').write_text(json.dumps(dict(checks=t.checks,dispatches=t.timings,
        failures=failures,peak_wset=psutil.Process().memory_info().peak_wset),indent=2))
    print('skin SSS:',len(t.checks),'checks;',failures,'failures; peak_wset',psutil.Process().memory_info().peak_wset)
    return bool(failures)

if __name__=='__main__':sys.exit(main())
