"""Actual native-b6 capture + production motion shader; run under run_task_test GPU lock.

--prepare-only builds input/source artifacts without invoking any compiler/GPU.
The independent surface oracle uses known previous/current surface coordinates;
neither previous visible depth nor the shader reconstruction helper is its oracle.
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
PASS=ROOT/'OptiScaler/shaders/fsrd_preprocess'
TEST=Path(__file__).parent
OUT=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/15a-motion/tests/native-motion'))
REPORT=Path('E:/FSRD/sol_batch/15a-motion')
PY_CHECKS=0

def need(condition,message):
    global PY_CHECKS
    PY_CHECKS+=1
    if not condition: raise AssertionError(message)

def make_case(path,kind,width=16,height=16):
    path.mkdir(parents=True,exist_ok=True)
    sign=-1.0 if kind.endswith('_negative') else 1.0
    world=kind.startswith('world')
    ortho=kind.startswith('ortho')
    scaled_basis=kind.startswith('basis2')
    reset=kind=='reset'
    fallback=kind.startswith('invalid_')
    title=np.zeros((32,4),dtype='<u4');floats=title.view('<f4')
    def f(reg,values): floats[reg,:len(values)]=values
    f(0,[1,0,0,0]);f(1,[0,1,0,0]);f(2,[0,0,1,1]);f(3,[0,0,0,0])
    f(4,[0,0,0,0]);f(5,[0,0,0,0]);f(6,[0,0,1,0]);f(7,[0,0,.25 if world else 0,0])
    f(20,[1,0,0]);f(21,[0,1,0]);f(22,[0,0,1])
    basis=2.0 if scaled_basis else 1.0
    f(23,[basis,0,0]);f(24,[0,basis,0]);f(25,[0,0,basis]);f(26,[0,0,0])
    scales=np.array([2,-.5,-.25 if kind=='scale_negative' else .5],dtype=np.float32)
    f(27,scales);title[28,2:]=[0,0];title[29,2:]=[width,height]
    f(30,[0,0,1/width,1/height]);f(31,[width,height,0,float(ortho)])
    title[31,2]=37 if kind=='world_nonzero_mode' else int(world)
    yy,xx=np.mgrid[:height,:width]
    uv=np.stack(((xx+.5)/width,(yy+.5)/height),axis=-1).astype(np.float32)
    ndc=2*uv-1
    current=np.stack((ndc[...,0]*(1 if ortho else 8),-ndc[...,1]*(1 if ortho else 8),np.full((height,width),8)),axis=-1).astype(np.float32)
    previous=current+np.array([1,-.5,3],dtype=np.float32)
    raw=np.zeros((height,width,4),dtype='<f2')
    if world: raw[...,:3]=(previous-current)/scales
    else:
        prior_uv=np.stack((previous[...,0]/(1 if ortho else previous[...,2])*.5+.5,
                           .5-previous[...,1]/(1 if ortho else previous[...,2])*.5),axis=-1)
        raw[...,:2]=(prior_uv-uv)/scales[:2]
        raw[...,2]=(previous[...,2]/basis-8)/scales[2]
    expected=np.full((height,width),sign*(3.25 if world else 3),dtype=np.float32)
    if kind=='screen_zero_zscale':
        f(27,[2,-.5,0]);f(7,[0,0,2,0]);expected.fill(sign*2)
    if kind=='wrong_z_control':raw[...,2]*=-1
    corrupt=232 if kind=='invalid_signature' else 236 if kind=='invalid_version' else 0
    if kind=='invalid_origin':title[28,2]=1
    if kind=='invalid_current_rect':title[29,2]=width-1
    if kind=='invalid_previous_rect':floats[31,0]=width+1
    if kind=='invalid_reciprocal':floats[30,2]*=2
    if kind=='invalid_ortho':floats[31,3]=np.nan
    if kind=='invalid_scale':floats[27,2]=np.inf
    if kind=='invalid_raw':raw[...,2]=np.nan
    if kind=='invalid_world_clip':
        title[31,2]=1;floats[0:4,3]=[0,0,0,-1]
    depth=np.full((height,width),sign*8,dtype='<f4')
    native_depth=np.full((height,width),8,dtype='<f4')
    if kind=='invalid_depth_mismatch':native_depth.fill(9)
    if kind=='invalid_depth_nan':native_depth.fill(np.nan)
    constants=np.zeros(32,dtype='<u4');cf=constants.view('<f4')
    constants[:4]=[width,height,int(not reset),1]
    cf[4:8]=[1/width,-1/height,.375/width,-.625/height]
    cf[8:24]=np.eye(4,dtype=np.float32).ravel();cf[24:28]=[0,0,1,sign*.75]
    cf[28:30]=[.25/width,-.125/height]
    if fallback:expected.fill(sign*.75)
    if reset:expected.fill(0)
    raw.tofile(path/'raw.bin');depth.tofile(path/'depth.bin');native_depth.tofile(path/'native_depth.bin')
    np.full((height,width),sign*2,dtype='<f4').tofile(path/'previous.bin')
    title.tofile(path/'title.bin');constants.tofile(path/'constants.bin')
    expected.tofile(path/'expected.bin')
    # Fixed ABI mapping, including integer origin/extent and all zero padding.
    snapshot=np.zeros(64,dtype='<u4')
    snapshot[0:4]=title[:4,0];snapshot[4:8]=title[:4,1];snapshot[8:12]=title[:4,3];snapshot[12:16]=title[4:8,2]
    for dst,src in ((16,20),(20,21),(24,22),(28,23),(32,24),(36,25),(40,26),(44,27)):
        snapshot[dst:dst+3]=title[src,:3]
    snapshot[48:52]=np.r_[title[28,2:],title[29,2:]];snapshot[52:56]=np.r_[title[30,2:],title[31,:2]]
    snapshot[56:60]=[title[31,2],title[31,3],0x4e544d31,1]
    if corrupt:snapshot[corrupt//4]=0
    snapshot.tofile(path/'expected-shadow.bin')
    return {'name':kind,'width':width,'height':height,'sign':sign,'fallback':fallback,'reset':reset,'corrupt':corrupt,'negative_control':kind=='wrong_z_control'}

def prepare_inputs():
    names=['screen_positive','screen_negative','basis2_positive','basis2_negative','scale_negative',
           'screen_zero_zscale','world_positive','world_negative','world_nonzero_mode','ortho_positive','ortho_negative',
           'invalid_origin','invalid_current_rect','invalid_previous_rect','invalid_reciprocal',
           'invalid_depth_mismatch','invalid_depth_nan','invalid_signature','invalid_version','invalid_ortho',
           'invalid_scale','invalid_raw','invalid_world_clip','reset','wrong_z_control']
    cases=[make_case(OUT/'cases'/name,name) for name in names]
    (OUT/'cases'/'cases.txt').write_text(f'{len(cases)} 16 16\n'+''.join(f'{c["name"]} {c["corrupt"]}\n' for c in cases))
    for width,height in ((1505,847),(2560,1440)):make_case(OUT/'timing'/f'{width}x{height}','screen_positive',width,height)
    (OUT/'inputs.json').write_text(json.dumps(cases,indent=2))
    return cases

def build_sources(compiled_root):
    OUT.mkdir(parents=True,exist_ok=True)
    source=(PASS/'FSRDNrdNativeTemporalConstants_Dx12.h').read_text()
    source=source.replace('#include "resource_tracking/ResTrack_Dx12.h"','').replace('#include "State.h"','')
    source=source.replace('#include "precompile/FSRDNrdNativeTemporalCapture_Shader.h"',f'#include "{(compiled_root/"FSRDNrdNativeTemporalCapture_Shader.h").as_posix()}"')
    source=source.replace('#include "precompile/FSRDNrdNativeTemporalCaptureRoot_Shader.h"',f'#include "{(compiled_root/"FSRDNrdNativeTemporalCaptureRoot_Shader.h").as_posix()}"')
    need(source.count('list->ResourceBarrier(1,&barrier);')==2,'exact two production capture transition sites instrumented')
    source=source.replace('list->ResourceBarrier(1,&barrier);','auditCaptureBarriers(list,1,&barrier);')
    source=source.replace('context.slots.push_back(slot);','++gNativeCaptureAllocations; context.slots.push_back(slot);')
    support=(TEST/'dx12_shader_test_support.h').as_posix()
    audit='''
#include <unordered_set>
inline std::unordered_set<ID3D12Resource*> gNativeBorrowed;
inline uint64_t gNativeCaptureAllocations=0,gNativeCaptureBarriers=0;
inline void auditCaptureBarriers(ID3D12GraphicsCommandList* list,UINT count,const D3D12_RESOURCE_BARRIER* barriers){
 for(UINT i=0;i<count;++i){++gNativeCaptureBarriers;if(barriers[i].Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION&&gNativeBorrowed.contains(barriers[i].Transition.pResource))throw std::runtime_error("native capture transitioned a borrowed source");}
 list->ResourceBarrier(count,barriers);
}
'''
    (OUT/'native_capture_under_test.h').write_text(f'#include "{support}"\n'+audit+source)
    context=(TEST/'fsrd_nrd_conversion_fixture.cpp').read_text().split('static ULONG References')[0]
    context=context.replace('#include "production_nrd_pass.cpp"','#include "native_capture_under_test.h"')
    (OUT/'native_fixture_context.h').write_text(context)
    shaders={}
    for name,var in [('FSRDNrdBridgeMotionNative','NativeMotionBytes'),('FSRDNrdBridgeMotion','BaselineMotionBytes')]:
        raw=(compiled_root/(name+'_Shader.cso')).read_bytes();shaders[name]=hashlib.sha256(raw).hexdigest()
        with (OUT/'native_motion_shaders.h').open('a' if var=='BaselineMotionBytes' else 'w') as f:f.write('const unsigned char '+var+'[]={'+','.join(map(str,raw))+'};\n')
    for name in ('FSRDNrdNativeTemporalCapture','FSRDNrdNativeTemporalCaptureRoot'):
        shaders[name]=hashlib.sha256((compiled_root/(name+'_Shader.cso')).read_bytes()).hexdigest()
    shutil.copyfile(TEST/'fsrd_nrd_native_motion_fixture.cpp',OUT/'fixture.cpp')
    return shaders

def verify(cases):
    errors={}
    for case in cases:
        path=OUT/'cases'/case['name'];shape=(case['height'],case['width'],4)
        expected=np.fromfile(path/'expected.bin',dtype='<f4').reshape(shape[:2])
        for route in ('root','table'):
            actual=np.fromfile(path/f'{route}-motion.bin',dtype='<f2').reshape(shape).astype(np.float32)
            camera=np.fromfile(path/f'{route}-camera.bin',dtype='<f2').reshape(shape).astype(np.float32)
            visible=np.fromfile(path/f'{route}-visible.bin',dtype='<f2').reshape(shape).astype(np.float32)
            need((path/f'{route}-shadow.bin').read_bytes()==(path/'expected-shadow.bin').read_bytes(),f'{case["name"]}/{route} exact selected native operands after late binding overwrite')
            need(np.array_equal(actual[...,:2],camera[...,:2]),f'{case["name"]}/{route} outputXY byte parity')
            need(np.isfinite(actual).all() and np.all(actual[...,3]==1),f'{case["name"]}/{route} finite motion and preservedW')
            error=float(np.max(np.abs(actual[...,2]-expected)))
            errors[case['name']+'/'+route]=error
            if case['negative_control']:need(error>=2.0,'deliberately wrong nativeZ fails independent moving-surface oracle')
            else:need(error<=0.004,f'{case["name"]}/{route} previous surface Z oracle error{error}')
            if case['fallback']:need(np.array_equal(actual[...,2],camera[...,2]),f'{case["name"]}/{route} invalid native uses exact camera fallback')
            if case['name']=='screen_positive':need(float(np.max(np.abs(visible[2:-2,2:-2,2]-expected[2:-2,2:-2])))>=8,'old visible occluder depth is a distinct wrong negative control')
    need((OUT/'cases'/'canceled-shadow.bin').read_bytes()==(OUT/'cases'/'screen_positive'/'expected-shadow.bin').read_bytes(),'canceled recording retains exact GPU shadow')
    return errors

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--compiled-root',type=Path,default=Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/fsrd_preprocess/precompile'))
    args=parser.parse_args();cases=prepare_inputs();shaders=build_sources(args.compiled_root)
    if args.prepare_only:print(json.dumps({'prepared_cases':len(cases),'shaders':shaders,'checks':PY_CHECKS}));return
    sys.path.insert(0,str(TEST.parent));from fsrd_toolchain import compile_cpp
    exe=OUT/'native_motion.exe';compile_cpp(OUT/'fixture.cpp',exe,('d3d12.lib','dxgi.lib'),
        (OUT,TEST,PASS,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline'))
    runs={}
    for mode in ('cases','timing'):
        result=subprocess.run([str(exe),mode,str(OUT/mode)],capture_output=True,text=True,errors='replace',timeout=180)
        (OUT/(mode+'.stdout.log')).write_text(result.stdout);(OUT/(mode+'.stderr.log')).write_text(result.stderr)
        print(result.stdout,end='');print(result.stderr,end='',file=sys.stderr);result.check_returncode()
        need('debug_errors=0 debug_warnings=0' in result.stdout,mode+' GPU validation clean');runs[mode]=result.stdout
    errors=verify(cases);REPORT.mkdir(parents=True,exist_ok=True)
    report={'python_checks':PY_CHECKS,'cases':cases,'max_depth_errors':errors,'shaders':shaders,'native_runs':runs,
        'scope':'actual source-free capture class and production CSOs; actual RecordedComputeLease with explicit queue/Reset adapters; synthetic physical inputs; no live game quality verdict'}
    (REPORT/'native-motion-tests.json').write_text(json.dumps(report,indent=2));print(json.dumps({'python_checks':PY_CHECKS,'native_motion_tests':'PASS'}))

if __name__=='__main__':main()
