"""Owned raw/geometry real D3D12 fixture. Use run_task_test; --run needs lead GPU grant."""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys,time
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from fsrd_toolchain import compile_cpp,dxc
import test_fsrd_nrd_conversion as legacy
ROOT=Path(os.environ.get('FSRD_NRD_PRODUCTION_ROOT',HERE.parents[3])).resolve();PASS=ROOT/'OptiScaler/shaders/fsrd_preprocess'
TASK=Path('F:/FSRD/sol_batch/15c-rr');CHECKS=0

def need(value,name):
    global CHECKS
    CHECKS+=1
    if not value:raise AssertionError(name)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def prepare(output):
    need(output.resolve().is_relative_to(TASK.resolve()),'task-local output only')
    inputs=output/'inputs';inputs.mkdir(parents=True,exist_ok=True);w=h=128;y,x=np.mgrid[:h,:w]
    rows=[];configs=[]
    for word in [303,36]:
        for table in [0,1]:
            for flag in [0,1,0x80000000,0x7fc00000]:configs.append((word,table,flag,0,0,0))
    configs += [(303,0,1,3,2,0),(303,1,0,3,2,1),(36,1,1,3,2,2)]
    for i,(word,table,flag,ox,oy,material) in enumerate(configs):
        path=inputs/f'case{i:02d}';spec=np.empty((h,w,4),'<f2');diff=spec.copy()
        spec[...,:3]=[1,.375,-.25];diff[...,:3]=[.625,-.125,.25]
        spec[...,3]=((np.arange(w*h,dtype=np.uint32).reshape(h,w)+i*w*h)%65536).astype('<u2').view('<f2')
        diff[...,3]=((np.arange(w*h,dtype=np.uint32).reshape(h,w)[::-1]+(i+2)*w*h)%65536).astype('<u2').view('<f2')
        spec[0,0,:3]=[np.nan,np.inf,-np.inf];diff[0,1,:3]=[-0.,-.5,np.nan]
        nr=legacy.packed_nr(np.stack((.45+.08*x/(w-1),.47+.05*y/(h-1),.12+.5*((x+y)%13)/13,((x//16+y//16)%4)/3),axis=-1))
        depth=(1+(x+2*y)%61).astype('<f4');depth[0:2,0:2]=0.;depth[8,8]=1e7
        motion=np.zeros((h,w,4),'<f2');motion[...,3]=1
        base=np.stack(((x%11+.5)/12,(y%13+.5)/14,((x+y)%7+.5)/8,((x//8+y//8)%3)*.5),axis=-1).astype('<f2')
        rough=np.ones((h,w),'<f2');rough[(x+2*y)%7==0]=np.nan
        params=legacy.frame(w,h,0);params.update(jitter=(0,0),previous_jitter=(0,0),native_material_guides=bool(material),preserve_native_material_ids=True)
        payload={'spec':spec,'diff':diff,'nr':nr,'depth':depth,'motion':motion,'material':base,'material_roughness':rough}
        legacy.write_case(path,payload,params)
        rows.append({'name':path.name,'word':word,'table':table,'flag':flag,'origin':[ox,oy],'material':material})
    (inputs/'cases.txt').write_text(f'{len(rows)} {w} {h}\n'+''.join(f"{r['name']} {r['origin'][0]} {r['origin'][1]} {r['word']} {r['flag']} {r['table']} {r['material']}\n" for r in rows))
    hashes={str(p.relative_to(inputs)):digest(p) for p in sorted(inputs.rglob('*.bin'))}
    manifest={'schema':'fsrd.raw-helper-native.v1','width':w,'height':h,'cases':rows,'payload_sha256':hashes,'scope':'synthetic helper arithmetic/state/lifetime only; no native NRD result or game quality'}
    (inputs/'manifest.json').write_text(json.dumps(manifest,indent=2))
    # Same production logic, only application hook includes and observer probes replaced.
    support=(HERE/'dx12_shader_test_support.h').as_posix()
    source=(PASS/'FSRDNrdBridgePass_Dx12.cpp').read_text().replace('#include "pch.h"',f'#include "{support}"\n'+legacy.AUDIT)
    for line in ['#include "resource_tracking/ResTrack_Dx12.h"','#include "State.h"']:source=source.replace(line,'')
    need(source.count('list->ResourceBarrier(')==11,'all production conversion barrier sites retained')
    for old,new in [('list->ResourceBarrier(1, &barrier);','AuditedNrdBarriers(list,1,&barrier);'),('list->ResourceBarrier(2, barriers);','AuditedNrdBarriers(list,2,barriers);'),('list->ResourceBarrier(1, &shadowBarrier);','AuditedNrdBarriers(list,1,&shadowBarrier);'),('list->ResourceBarrier(1,&materialBarrier);','AuditedNrdBarriers(list,1,&materialBarrier);'),('list->ResourceBarrier(1,&geometryBarrier);','AuditedNrdBarriers(list,1,&geometryBarrier);')]:source=source.replace(old,new)
    # The audit function's forwarding call is deliberately the only unaudited site.
    need(source.count('list->ResourceBarrier(')==1,'every geometry and legacy production barrier audited')
    source=source.replace('for (auto* resource : srvs)\n        {','for (auto* resource : srvs)\n        {\n            AuditNrdSrv(resource);').replace('for (auto* resource : uavs)\n        {','for (auto* resource : uavs)\n        {\n            AuditNrdUav(resource);')
    (output/'production_nrd_pass.cpp').write_text(source)
    raw=(PASS/'FSRDNrdRawSignals_Dx12.cpp').read_text().replace('#include "pch.h"',f'#include "{support}"')
    for line in ['#include "resource_tracking/ResTrack_Dx12.h"','#include "State.h"']:raw=raw.replace(line,'')
    need(raw.count('list->ResourceBarrier(1,&barrier);')==1,'one raw state forwarding site')
    raw=raw.replace('list->ResourceBarrier(1,&barrier);','AuditedNrdBarriers(list,1,&barrier);')
    (output/'production_nrd_raw.cpp').write_text(raw)
    return inputs,manifest

def build(output):
    shader=output/'consumer.cso'
    subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-O3','-force-rootsig-ver','rootsig_1_0',str(HERE/'nrd_bridge_consumer_fixture.hlsl'),'-Fo',str(shader)],check=True)
    (output/'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {'+','.join(str(b) for b in shader.read_bytes())+'};\n')
    exe=output/'nrd_raw_signal_fixture.exe'
    compile_cpp(HERE/'nrd_raw_signal_fixture.cpp',exe,('d3d12.lib','dxgi.lib'),(output,HERE,PASS,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline'))
    return exe

def native(exe,inputs,output):
    import psutil
    log=output/'raw.native.log';start=time.monotonic();peak=0
    with log.open('w') as stream:
        proc=subprocess.Popen([str(exe),str(inputs)],stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        measured=psutil.Process(proc.pid);measured.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        while proc.poll() is None:
            try:peak=max(peak,measured.memory_info().rss)
            except psutil.NoSuchProcess:pass
            if peak>int(2.5*1024**3) or time.monotonic()-start>300:proc.kill();proc.wait();raise RuntimeError('native memory/time cap; log preserved')
            time.sleep(.02)
        rc=proc.wait()
    text=log.read_text(errors='replace');print(text,end='');need(rc==0,'native helper first exit0')
    need('debug_errors=0 debug_warnings=0' in text,'strict D3D12 zero errors/warnings')
    match=re.search(r'PASS raw_native_checks=(\d+) provider_calls=0 native_nrd_calls=0',text);need(match is not None,'actual helper terminal marker')
    return {'native_checks':int(match[1]),'seconds':time.monotonic()-start,'peak_resident_bytes':peak,'executable_sha256':digest(exe),'log':str(log)}

def shifted(array,ox,oy):
    out=np.zeros_like(array);h,w=array.shape[:2]
    out[:h-oy,:w-ox]=array[oy:,ox:];return out

def compare(inputs,manifest):
    h,w=manifest['height'],manifest['width'];rows=[];alpha_words=set()
    for case in manifest['cases']:
        path=inputs/case['name'];ox,oy=case['origin'];values={}
        for name,dtype,shape in [('spec','<f2',(h,w,4)),('diff','<f2',(h,w,4)),('nr','<u4',(h,w)),('depth','<f4',(h,w)),('motion','<f2',(h,w,4)),('material','<f2',(h,w,4)),('material_roughness','<f2',(h,w))]:values[name]=np.fromfile(path/f'{name}.bin',dtype).reshape(shape)
        raw=np.fromfile(path/'raw_owned.bin','<u2');header=raw[:768].view('<u4');packed=raw[768:].reshape(h,w,8)
        expected_header=np.zeros(384,'<u4');expected_header[112:116]=[0x51a2c3d4,0x12345678,ox,oy]
        need(np.array_equal(header,expected_header),'only actual geometry operands captured in zero header')
        native_words=np.concatenate((values['spec'].view('<u2'),values['diff'].view('<u2')),axis=-1)
        finite=(native_words&0x7c00)!=0x7c00
        need(np.array_equal(packed[finite],native_words[finite]),'all finite raw RGBA half words preserved before codec')
        need(np.all((packed[~finite]&0x7c00)==0x7c00),'nonfinite raw retained until late sanitize')
        for lobe,offset in [('spec',0),('diff',4)]:
            native=values[lobe];need(np.array_equal(np.fromfile(path/f'source_{lobe}_after.bin','<u2'),native.view('<u2').ravel()),'native noisy resource bytes unchanged')
            out=np.fromfile(path/f'out_{lobe}.bin','<f2').reshape(h,w,4);f=native.astype(np.float32)
            with np.errstate(invalid='ignore'):
                rgb=np.stack((f[...,0]-f[...,2]+f[...,1],f[...,0]+f[...,2],f[...,0]-f[...,2]-f[...,1]),-1) if case['flag'] else f[...,:3]
            rgb=np.where(np.isfinite(rgb),np.clip(rgb,0,65504),0)
            # HLSL clamp canonicalizes numeric RGB zero to +0; raw/alpha words remain exact.
            rgb=np.where(rgb==0,np.float32(0),rgb).astype('<f2')
            need(np.array_equal(out[...,:3].view('<u2'),rgb.view('<u2')),'executed native303/36 exact decoded RGB incl signed chroma')
            good=np.isfinite(native[...,3]);need(np.array_equal(out[...,3].view('<u2')[good],native[...,3].view('<u2')[good]),'finite native alpha exact incl negative/signedzero')
            need(np.all(out[...,3].view('<u2')[~good]==0),'malformed alpha sanitized to+0; no native semantic claim')
            need(np.isfinite(out).all(),'all owned RR input components finite')
            alpha_words.update(int(x) for x in native[...,3].view('<u2').ravel())
        flag=np.fromfile(path/'encoding_flag.bin','<u4')[303];need(int(flag)==case['flag'],'actual GPU executed root/table flag')
        nr=shifted(values['nr'],ox,oy);z=shifted(values['depth'],ox,oy)
        need(np.array_equal(np.fromfile(path/'out_nr.bin','<u4').reshape(h,w),nr),'normal/roughness/material ID exact global origin')
        params=legacy.frame(w,h,0);params.update(jitter=(0,0),previous_jitter=(0,0));expected_depth=params['sign']*np.clip(np.abs(z),params['near'],params['far'])
        need(np.array_equal(np.fromfile(path/'out_depth.bin','<f4').reshape(h,w),expected_depth),'signed RR depth global origin/clamp')
        epsilon=np.array([0x358637bd],'<u4').view('<f4')[0]
        need(np.array_equal(np.fromfile(path/'positive_viewz.bin','<f4').reshape(h,w),np.maximum(np.abs(z),epsilon)),'owned positive native ViewZ exact epsilon and no RR far clamp')
        motion=np.fromfile(path/'out_motion.bin','<f2').reshape(h,w,4);need(np.all(motion[...,:3]==0)&np.all(motion[...,3]==1),'deferred current Temporal motion')
        alb={key:np.fromfile(path/f'out_{key}.bin','u1').reshape(h,w,4) for key in ['spec_albedo','diff_albedo']}
        if not case['material']:
            need(np.all(alb['spec_albedo'][...,:3]==255)&np.all(alb['diff_albedo'][...,:3]==255),'white guide variant exact')
        else:
            base=shifted(values['material'],ox,oy);fake_nr=nr.copy();valid=np.zeros((h,w),bool);valid[:h-oy,:w-ox]=True
            rough=shifted(values['material_roughness'],ox,oy)
            if case['material']==2:fake_nr=(fake_nr&~np.uint32(1023<<20))|np.uint32(1023<<20)
            oracle=legacy.material_guide_bounds({'nr':fake_nr,'material':base},alb)
            for key,bounds in [('spec_albedo','spec_bounds'),('diff_albedo','diff_bounds')]:
                known=oracle['known']&valid
                if key=='spec_albedo' and case['material']==2:known&=np.isfinite(rough)
                actual=alb[key][...,:3].astype(np.float64)/255;lo,hi=oracle[bounds]
                need(np.all((actual[known]>=lo[known])&(actual[known]<=hi[known])),'nonzero origin material guide unchanged independent FP32/UNORM interval')
                fallback=(~oracle['known'])&valid
                if key=='spec_albedo' and case['material']==2:fallback|=(~np.isfinite(rough))&valid
                need(np.all(alb[key][fallback,:3]==255),'nonzero origin unsupported/invalid material exact white')
        need(np.all(alb['diff_albedo'][...,3]==0),'diffuse albedo alpha remains zero')
        rows.append({'case':case['name'],'origin':[ox,oy],'material':case['material'],'native_flag':int(flag)})
    need(len(alpha_words)==65536,'all65536 native alpha words exercised incl malformed')
    return rows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--output',type=Path,default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',TASK/'tests/raw-native')));args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);inputs,manifest=prepare(args.output)
    if not args.run:print(json.dumps({'prepared_cases':len(manifest['cases']),'checks':CHECKS,'compiler_run':False,'gpu_run':False}));return
    exe=build(args.output);result=native(exe,inputs,args.output);result['cases']=compare(inputs,manifest);result.update(python_checks=CHECKS,reference_interval_checks=legacy.CHECKS,scope='actual owned raw/geometry shaders and registry adapters; no provider, native NRD execution, quality, FPS or game-elision proof',sources={str(p):digest(p) for p in [Path(__file__),HERE/'nrd_raw_signal_fixture.cpp',PASS/'FSRDNrdRawSignals_Dx12.cpp',PASS/'FSRDNrdBridgePass_Dx12.cpp']})
    (args.output/'comparison.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
