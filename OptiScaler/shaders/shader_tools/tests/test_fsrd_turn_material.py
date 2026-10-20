"""Production shader + host selection, fixed-truth colour boundaries and lobe/alpha contracts.
No final-game quality claim. FSRD_GPU_TEST_OUTPUT must point outside the repository.
"""
import json,os,sys,subprocess
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(HERE.parent))
from fsrd_toolchain import compile_cpp,dxc
L=np.array([.2126,.7152,.0722],np.float32)
def build(out):
    (out/'pch.h').write_text('#pragma once\n')
    subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',str(HERE/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(out/'consumer.cso')],check=True,capture_output=True)
    (out/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+','.join(map(str,(out/'consumer.cso').read_bytes()))+'};\n')
    os.environ['FSRD_CPP_CACHE']=str(out/'cache');exe=out/'turn_material.exe'
    compile_cpp(HERE/'fsrd_turn_material.cpp',exe,['d3d12.lib','dxgi.lib','d3dcompiler.lib'],[out,HERE,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    return exe
def fixture(w,h,kind,seed=361):
    y,x=np.mgrid[:h,:w];cut=w//2+1
    a=np.array([2,.4,.2],np.float32);a/=a@L
    b=np.array([.25,.6,2.8],np.float32);b/=b@L
    qd=np.where((x<cut)[...,None],[.4,.05,.1],[.03,.3,.1]);qs=np.where((y<h//2)[...,None],[.1,.4,.03],[.3,.03,.1])
    d=np.where((x<cut)[...,None],a,b)*.013;s=np.where((y<h//2)[...,None],b,a)*.008
    z=np.full((h,w),10.,np.float32);n=np.full((h,w),512|(512<<10)|(600<<20),np.uint32)
    if kind=='light_edge':qd[:]=[.2,.1,.1];qs[:]=[.2,.1,.1]
    if kind=='depth_edge':qd[:]=.2;qs[:]=.2;z[:,cut:]=20;s=d.copy()
    if kind=='normal_edge':qd[:]=.2;qs[:]=.2;n[:,cut:]=1023|(512<<10)|(600<<20);s=d.copy()
    if kind=='roughness_edge':qd[:]=.2;qs[:]=.2;n[:,cut:]=512|(512<<10)|(100<<20);s=d.copy()
    if kind=='curved_edge':
        mask=(x-w*.48)**2+(y-h*.52)**2<(w*.31)**2
        qd=np.where(mask[...,None],[.4,.05,.1],[.03,.3,.1]);qs=qd[...,::-1].copy()
        d=np.where(mask[...,None],a,b)*.013;s=np.where(mask[...,None],b,a)*.008
    if kind=='thin':
        qd[:]=.2;qs[:]=.2;d[:]=a*.013;s=d.copy();qd[:,cut]=[.02,.5,.01];qs[:,cut]=qd[:,cut];d[:,cut]=b*.013;s[:,cut]=d[:,cut]
    if kind=='flat':qd[:]=.2;qs[:]=.1;d[:]=a*.013;s[:]=b*.008
    if kind=='hdr':
        qd[:]=.2;qs[:]=.1;d[:]=[0,0,50000];s[:]=[50000,0,0]
        d[h//2,w//2]=[65000,65000,65000];s[h//2,w//2]=d[h//2,w//2]
    if kind=='noisy':
        rng=np.random.default_rng(seed);d*=rng.lognormal(-.5,1,d.shape[:2])[...,None];s*=rng.lognormal(-.5,1,s.shape[:2])[...,None]
    alpha=((x+y*w)%37/3).astype(np.float16)
    rgba=lambda a:np.concatenate([a,alpha[...,None]],-1).astype('f2')
    return {'diff':rgba(d),'spec':rgba(s),'depth':z,'normals':n,'motion':np.zeros((h,w,4),'f2'),
            'diff_albedo':np.uint8(np.concatenate([qd,np.ones((h,w,1))],-1)*255),
            'spec_albedo':np.uint8(np.concatenate([qs,np.ones((h,w,1))],-1)*255)}
def execute(exe,out,name,data,weight=1.,gain=1.):
    folder=out/name;folder.mkdir(exist_ok=True);src=folder/'inputs';src.mkdir(exist_ok=True)
    h,w=data['depth'].shape
    for key,v in data.items():v.tofile(src/(key+'.bin'))
    result=folder/'gpu';r=subprocess.run([str(exe),str(w),str(h),str(src),str(result),str(weight),str(gain)],capture_output=True,text=True,timeout=180,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    (folder/'native.log').write_text(r.stdout+r.stderr);r.check_returncode()
    assert 'debug_errors=0 debug_warnings=0' in r.stdout,r.stdout+r.stderr
    record={'case':name,'weight':weight,'gain':gain,'measurements':{}}
    for lobe in ['diff','spec']:
        a=data[lobe].astype('f4');read=lambda n:np.fromfile(result/(n+'-'+lobe+'.bin'),'f2').reshape(h,w,4)
        orig=read('source');new=read('material');old=read('old')
        assert np.array_equal(orig.view('u2'),data[lobe].view('u2')),'source changed'
        assert np.array_equal(new[...,3].view('u2'),data[lobe][...,3].view('u2')),'alpha changed'
        assert np.isfinite(new).all(),'nonfinite output'
        expected=(a[...,:3]@L)*gain;actual=new[...,:3].astype('f4')@L
        # Half output can round a subnormal channel to zero. Use its absolute ULP
        # as well as the normal-range relative bound, including truly dark pixels.
        assert np.all(np.abs(actual-expected)<=expected*.001+2**-24),'sample luminance changed beyond half quantization'
        truth=a[...,:3];err=lambda v:float(np.abs(v[...,:3].astype('f4')-truth*gain).sum()/np.maximum((truth*gain).sum(),1e-9))
        record['measurements'][lobe]={'old_truth_relative_l1':err(old),'material_truth_relative_l1':err(new)}
        if name in ['boundary','depth_edge','normal_edge','roughness_edge','curved_edge','thin','noisy']:
            assert err(new)<err(old)*.02,'cross-boundary colour not prevented'
        if name in ['flat','light_edge']:
            assert np.max(np.abs(new[...,:3].astype('f4')-old[...,:3].astype('f4')))<.0001,'uniform-guide aperture deviated from old filter'
        if weight==0:assert np.allclose(new[...,:3],(truth*gain).astype('f2'),rtol=.001,atol=1e-7)
    print(json.dumps(record),flush=True);return record
def main():
    out=Path(os.environ['FSRD_GPU_TEST_OUTPUT']);out.mkdir(parents=True,exist_ok=True);exe=build(out)
    records=[]
    for kind in ['boundary','flat','light_edge','depth_edge','normal_edge','roughness_edge','curved_edge','thin','noisy','hdr']:
        records.append(execute(exe,out,kind,fixture(65,67,kind)))
    records.append(execute(exe,out,'fade-zero',fixture(65,67,'boundary'),0,.87))
    records.append(execute(exe,out,'fade-half',fixture(65,67,'boundary'),.5,.9))
    (out/'summary.json').write_text(json.dumps(records,indent=2))
    print('PASS 12 production shader/host fixtures; fixed-truth tests do not establish gameplay quality')
if __name__=='__main__':main()
