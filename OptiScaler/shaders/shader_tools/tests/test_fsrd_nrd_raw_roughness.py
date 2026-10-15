"""Actual same-native-descriptor raw-alpha capture; no RR quality claim.

Run under run_task_test's GPU lock. --prepare-only invokes no compiler/GPU.
Only new research capture/shader files are built; production host is untouched.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
TEST=Path(__file__).parent
PASS=ROOT/'OptiScaler/shaders/fsrd_preprocess'
PRE=PASS/'precompile'
OUT=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/15a-motion/tests/raw-roughness'))
REPORT=Path(os.environ.get('FSRD_RAW_ROUGHNESS_REPORT','E:/FSRD/sol_batch/15a-motion/raw-roughness'))
CHECKS=0


def need(value,message):
    global CHECKS
    CHECKS+=1
    if not value: raise AssertionError(message)


SENTINEL=r'''
#define MainRS \
 "RootFlags(0), RootConstants(num32BitConstants=1,b0), " \
 "DescriptorTable(SRV(t0,numDescriptors=6,flags=DESCRIPTORS_VOLATILE|DATA_VOLATILE)), " \
 "CBV(b6,flags=DATA_VOLATILE), UAV(u16,flags=DATA_VOLATILE), " \
 "RootConstants(num32BitConstants=1,b1), " \
 "DescriptorTable(UAV(u0,numDescriptors=5,flags=DESCRIPTORS_VOLATILE|DATA_VOLATILE))"
cbuffer Primary:register(b0){uint Salt;}
cbuffer Auxiliary:register(b1){uint Salt2;}
cbuffer NativeConstants:register(b6){uint Magic;}
Texture2D<float4> NativeNormal:register(t5);
RWByteAddressBuffer Marker:register(u16);
RWTexture2D<float4> NativeNR:register(u4);
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 id:SV_DispatchThreadID){
 uint width,height;NativeNormal.GetDimensions(width,height);
 if(id.x>=width||id.y>=height)return;
 float a=NativeNormal.Load(int3(id.xy,0)).a;
 uint code=(uint)(a*255.0f+0.5f);
 Marker.Store((id.y*width+id.x)*4u,code^Salt^Salt2^Magic);
 NativeNR[id.xy]=float4(.5f,.5f,a*smoothstep(.04f,.11f,a),2.0f/3.0f);
}
'''


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    for name,width,height in [('codes',257,3),('positive',37,19),('1505x847',1505,847),('2560x1440',2560,1440)]:
        path=OUT/name;path.mkdir(parents=True,exist_ok=True)
        yy,xx=np.mgrid[:height,:width]
        alpha=((xx+width*yy)*37+11)%256
        if name=='positive':alpha=np.array([15,20,25],dtype=np.uint32)[(xx+yy)%3]
        image=np.stack(((alpha*3+9)%256,(alpha*5+17)%256,(alpha*7+29)%256,alpha),axis=-1).astype('u1')
        image.tofile(path/'normal.bin');image[...,3]=255-image[...,3];image.tofile(path/'other.bin')
        (path/'size.txt').write_text(f'{width} {height}\n')
    source=(PASS/'NativeRawRoughnessCapture_Dx12.h').read_text()
    need('ID3D12Resource*' not in source.split('class NativeRawRoughnessCapture')[0], 'binding contains no source resource pointer')
    for forbidden in ('CopyDescriptors','CreateShaderResourceView','CreateDescriptorHeap','->Map(','->AddRef('):
        need(forbidden not in source,'capture has no source descriptor copy, mapping, AddRef or private heap: '+forbidden)
    need(source.count('list->ResourceBarrier(1,&barrier);')==2,'all two production barrier sites audited')
    need(source.index('RetainComputeDispatch')<source.index('list->ResourceBarrier'),'real lease admission before any GPU command')
    source=source.replace('#include "resource_tracking/ResTrack_Dx12.h"','').replace('#include "State.h"','')
    source=source.replace('list->ResourceBarrier(1,&barrier);','rawBarrier(list,1,&barrier);')
    source=source.replace('list->SetDescriptorHeaps(1,heaps);','rawHeaps(list,1,heaps,binding.nativeHeap);')
    source=source.replace('list->','(++gRawCommands,list)->')
    source=source.replace('context.slots.push_back(slot);','++gRawAllocations; context.slots.push_back(slot);')
    support=(TEST/'dx12_shader_test_support.h').as_posix()
    audit=r'''
#include <unordered_set>
inline std::unordered_set<ID3D12Resource*> gRawBorrowed;
inline uint64_t gRawCommands=0,gRawAllocations=0,gRawBarriers=0,gRawHeapSets=0;
inline void rawBarrier(ID3D12GraphicsCommandList* list,UINT count,const D3D12_RESOURCE_BARRIER* barriers){
 ++gRawCommands;
 for(UINT i=0;i<count;++i){++gRawBarriers;if(barriers[i].Type!=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION||gRawBorrowed.contains(barriers[i].Transition.pResource))throw std::runtime_error("raw capture touched borrowed source state");}
 list->ResourceBarrier(count,barriers);
}
inline void rawHeaps(ID3D12GraphicsCommandList* list,UINT count,ID3D12DescriptorHeap*const* heaps,ID3D12DescriptorHeap* expected){
 ++gRawCommands;++gRawHeapSets;if(count!=1||heaps[0]!=expected)throw std::runtime_error("capture replaced native descriptor heap");list->SetDescriptorHeaps(count,heaps);
}
'''
    (OUT/'raw_capture_under_test.h').write_text(f'#include "{support}"\n'+audit+source)
    context=(TEST/'fsrd_nrd_conversion_fixture.cpp').read_text().split('static ULONG References')[0]
    context=context.replace('#include "production_nrd_pass.cpp"','#include "raw_capture_under_test.h"')
    (OUT/'raw_fixture_context.h').write_text(context)
    (OUT/'sentinel.hlsl').write_text(SENTINEL)
    shutil.copyfile(TEST/'fsrd_nrd_raw_roughness_fixture.cpp',OUT/'fixture.cpp')
    return {'capture_header_sha256':hashlib.sha256((PASS/'NativeRawRoughnessCapture_Dx12.h').read_bytes()).hexdigest(),
            'capture_hlsl_sha256':hashlib.sha256((PRE/'FSRDNrdRawRoughnessCapture.hlsl').read_bytes()).hexdigest()}


def verify():
    for name in ('codes','positive'):
        path=OUT/name;width,height=map(int,(path/'size.txt').read_text().split())
        image=np.fromfile(path/'normal.bin',dtype='u1').reshape(height,width,4)
        other=np.fromfile(path/'other.bin',dtype='u1').reshape(height,width,4)
        for route,expected in [('normal',image),('late',other)]:
            raw=np.fromfile(path/(route+'-raw.bin'),dtype='<u4').reshape(height,width)
            need(np.array_equal(raw,expected[...,3]),name+'/'+route+' all alpha codes are exact uint values')
            need(np.all(raw<=255),name+'/'+route+' no padding/sentinel codes')
            native=np.fromfile(path/(route+'-native.bin'),dtype='<u4').reshape(height,width)
            stored_b=(native>>20)&1023
            a=expected[...,3].astype(np.float64)/255
            t=np.clip((a-.04)/.07,0,1)
            ideal=a*(3*t*t-2*t*t*t)
            # <=8 scalar ops; each intermediate is bounded by15. FMA/reassociation
            # allowance128*u conservatively encloses FP32 source/math error, in
            # addition to the D3D0.6 integer-ULP normalized-store allowance.
            bound=.6+128*(2**-24)/(1-128*(2**-24))*1023
            need(float(np.max(np.abs(stored_b-ideal*1023)))<=bound,name+'/'+route+' native10bit mapping agrees with independent FP64 polynomial')
            need(np.all(stored_b[expected[...,3]<=11]==0),name+'/'+route+' native mapping loses true low-positive raw codes')
            for code in (15,20,25):
                mask=expected[...,3]==code
                if np.any(mask):need(np.all((raw[mask]>0)&(stored_b[mask]>0)),name+'/'+route+f' raw{code} and mappedB both positive; no zero-bypass control')
            marker=np.fromfile(path/(route+'-marker.bin'),dtype='<u4').reshape(height,width)
            need(np.array_equal(marker,expected[...,3].astype(np.uint32)^0x12345^0x45678^0x13579bdf),name+'/'+route+' caller root/PSO/heaps/tables/constants/CBV restoration verified by GPU')
        need((path/'source-after.bin').read_bytes()==(path/'normal.bin').read_bytes(),name+' source normal/RGB/A unchanged')
        need((path/'other-after.bin').read_bytes()==(path/'other.bin').read_bytes(),name+' late descriptor source unchanged')
    need(len(np.unique(np.fromfile(OUT/'codes'/'normal.bin',dtype='u1').reshape(-1,4)[:,3]))==256,'all256 source alpha codes covered')
    need(np.array_equal(np.fromfile(OUT/'canceled-raw.bin',dtype='<u4'),np.fromfile(OUT/'codes'/'normal.bin',dtype='u1').reshape(-1,4)[:,3]),'canceled context retains exact snapshot through actual GPU execution')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    identities=prepare()
    if args.prepare_only:
        print(json.dumps({'prepared':True,'python_checks':CHECKS,'source':identities,'compiler_gpu':'not run'}));return
    sys.path.insert(0,str(TEST.parent))
    from fsrd_toolchain import compile_cpp,dxc
    import build_fsrd_shader
    compiler=dxc();build_fsrd_shader.build('FSRDNrdRawRoughnessCapture',compiler)
    command=[str(compiler),'-T','cs_6_2','-E','CSMain','-O3','-Qstrip_debug','-Qstrip_reflect',str(OUT/'sentinel.hlsl'),'-Fo',str(OUT/'sentinel.cso')]
    result=subprocess.run(command,capture_output=True,text=True);(OUT/'sentinel-compile.stdout.log').write_text(result.stdout);(OUT/'sentinel-compile.stderr.log').write_text(result.stderr);result.check_returncode()
    raw=(OUT/'sentinel.cso').read_bytes();(OUT/'sentinel_shader.h').write_text('const unsigned char SentinelShader[]={'+','.join(map(str,raw))+'};\n')
    exe=OUT/'raw_roughness.exe'
    compile_cpp(OUT/'fixture.cpp',exe,('d3d12.lib','dxgi.lib'),(OUT,TEST,PASS,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline'))
    runs={}
    for mode in ('cases','timing'):
        run=subprocess.run([str(exe),mode,str(OUT)],capture_output=True,text=True,errors='replace',timeout=180)
        (OUT/(mode+'.stdout.log')).write_text(run.stdout);(OUT/(mode+'.stderr.log')).write_text(run.stderr)
        print(run.stdout,end='');print(run.stderr,end='',file=sys.stderr);run.check_returncode()
        need('debug_errors=0 debug_warnings=0' in run.stdout,mode+' debug validation clean');runs[mode]=run.stdout
    verify();REPORT.mkdir(parents=True,exist_ok=True)
    identities['capture_cso_sha256']=hashlib.sha256((PRE/'FSRDNrdRawRoughnessCapture_Shader.cso').read_bytes()).hexdigest()
    report={'python_checks':CHECKS,'source':identities,'native_runs':runs,
            'scope':'actual new capture class/shader and RecordedComputeLease, explicit Reset/queue adapters; native profile supplied by synthetic fixture; no installed hook/fullDLL/game-quality claim'}
    (REPORT/'tests.json').write_text(json.dumps(report,indent=2));print(json.dumps({'result':'PASS','python_checks':CHECKS}))


if __name__=='__main__':main()
