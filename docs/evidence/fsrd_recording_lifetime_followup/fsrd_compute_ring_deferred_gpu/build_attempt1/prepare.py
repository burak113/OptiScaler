"""Extract exact production classes/helpers, build, then freeze before any GPU job."""
from pathlib import Path
from datetime import datetime,timezone
import difflib,hashlib,json,os,re,shutil,struct,subprocess,sys
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha');HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def write(p,t):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:f.write(t)
def identity(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def section(text,start,end):
    i=text.index(start);j=text.index(end,i)+len(end);return text[i:j]
def main():
    if(HERE/'pre_gpu_freeze.json').exists():raise ValueError('Preserve fixture')
    os.environ['TEMP']=str(ROOT/'tools_tmp/native_compile_temp_20260930');os.environ['TMP']=os.environ['TEMP']
    assert Path(os.environ['TEMP']).is_dir()
    prod=ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp'
    utils=ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDShaderUtils.h'
    heaps=ROOT/'OptiScaler/shaders/Shader_Dx12Utils.h'
    d3dx=ROOT/'OptiScaler/include/d3dx/d3dx12.h'
    original=prod.read_text();compute=section(original,'struct ComputeState\n','\n};')
    heap=section(heaps.read_text(),'class FrameDescriptorHeap\n','\n};')
    helper_text=utils.read_text();i=helper_text.index('    constexpr UINT kMaxBarriers');j=helper_text.index('    /**\n     * @brief Calculates normalized 1D Gaussian weights',i)
    helpers=helper_text[i:j]
    # Diagnostic split-index class: original allocation/dispatch stays the same;
    # only the selected CB slot and descriptor slot can vary independently.
    split=compute.replace('struct ComputeState','struct SplitComputeState').replace('~ComputeState()','~SplitComputeState()')
    split=split.replace('    UINT backBufferCount = kBackBufferCount;','    UINT backBufferCount = kBackBufferCount;\n    UINT diagnosticCbSlots=3, diagnosticDescriptorSlots=3;')
    old='        const UINT currentFrame = m_cbCurrentFrameIndex;'
    new='        const UINT currentFrame = m_cbCurrentFrameIndex % diagnosticCbSlots;\n        const UINT descriptorFrame = m_cbCurrentFrameIndex % diagnosticDescriptorSlots;'
    assert split.count(old)==1;split=split.replace(old,new)
    old='FrameDescriptorHeap& currentHeap = m_frameHeaps[currentFrame];'
    new='FrameDescriptorHeap& currentHeap = m_frameHeaps[descriptorFrame];'
    assert split.count(old)==1;split=split.replace(old,new)
    write(HERE/'exact_ComputeState.h',compute+'\n');write(HERE/'exact_FrameDescriptorHeap.h',heap+'\n');write(HERE/'exact_helpers.h',helpers)
    shutil.copyfile(d3dx,HERE/'d3dx12.h')
    preamble='''#pragma once
#include "d3dx12.h"
using Microsoft::WRL::ComPtr;
using namespace DirectX;
// Outside runtime hooks: production heap-capture suppression is a no-op here.
struct ScopedSkipHeapCapture {};
#define LOG_ERROR(...) do { std::cerr << "helper range/error condition\\n"; } while(0)
#define SAFE_RELEASE(p) do { if(p) { (p)->Release(); (p)=nullptr; } } while(0)
constexpr UINT kBackBufferCount=3;
constexpr UINT kThreadGroupSizeX=8,kThreadGroupSizeY=8;
constexpr D3D12_RESOURCE_STATES kSrvState=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
constexpr D3D12_RESOURCE_STATES kUavState=D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
#include "exact_FrameDescriptorHeap.h"
namespace FSRD {
#include "exact_helpers.h"
}
using namespace FSRD;
#include "exact_ComputeState.h"
'''
    write(HERE/'production_extract.h',preamble+split+'\n')
    write(HERE/'split_index_adaptation.diff',''.join(difflib.unified_diff(compute.splitlines(keepends=True),split.splitlines(keepends=True),fromfile='exact_ComputeState',tofile='SplitComputeState')))
    for p in (prod,utils,heaps):shutil.copyfile(p,HERE/('source_'+p.name))
    guard=ROOT/'tools_tmp/native_output_initialization_diagnostic_20260930/native_resource_guard.py'
    assert sha(guard)=='b70e18d0f13963e0250c371171933429446cf304041c9a16d971e9898d211814'
    shutil.copyfile(guard,HERE/'native_resource_guard.py')
    sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools'))
    from fsrd_toolchain import compile_cpp,dxc
    compiler=dxc();shader_cmd=[str(compiler),'-T','cs_6_0','-E','main','-force-rootsig-ver','rootsig_1_0','-Fo',str(HERE/'identity.cso'),str(HERE/'identity.hlsl')]
    save(HERE/'shader_build_command.json',{'args':shader_cmd,'TEMP':os.environ['TEMP'],'TMP':os.environ['TMP'],'dxc':identity(compiler)})
    run=subprocess.run(shader_cmd,cwd=HERE,capture_output=True);(HERE/'shader_build.stdout.bin').write_bytes(run.stdout);(HERE/'shader_build.stderr.bin').write_bytes(run.stderr)
    assert run.returncode==0,'DXC failure retained'
    # Capture the repository compiler's exact stdout/stderr as persistent bytes.
    cpp_cmd=[sys.executable,str(HERE/'build_cpp.py')]
    save(HERE/'cpp_build_command.json',{'args':cpp_cmd,'TEMP':os.environ['TEMP'],'TMP':os.environ['TMP']})
    run=subprocess.run(cpp_cmd,cwd=HERE,capture_output=True)
    (HERE/'cpp_build.stdout.bin').write_bytes(run.stdout);(HERE/'cpp_build.stderr.bin').write_bytes(run.stderr)
    assert run.returncode==0,'MSVC failure retained'
    def root_blob(container):
        assert container[:4]==b'DXBC' and struct.unpack_from('<I',container,24)[0]==len(container)
        count=struct.unpack_from('<I',container,28)[0];found=[]
        for offset in struct.unpack_from('<'+str(count)+'I',container,32):
            fourcc=container[offset:offset+4];size=struct.unpack_from('<I',container,offset+4)[0]
            if fourcc==b'RTS0':found.append(container[offset+8:offset+8+size])
        assert len(found)==1;return found[0]
    signatures=[]
    embedded_dir=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile'
    shader_inputs=[('identity',HERE/'identity.cso')]
    source_shader_headers=[]
    for name in ('FSRDInputConv','FSRDFloorSeed','FSRDFloor'):
        header=embedded_dir/(name+'_Shader.h');text=header.read_text()
        m=re.search(r'const unsigned char '+name+r'_cso\[\]\s*=\s*\{(.*?)\};',text,re.S)
        assert m is not None,'production embedded shader array '+name
        data=bytes(int(s,16)for s in re.findall(r'0x([0-9a-fA-F]{2})',m.group(1)))
        target=HERE/('production_'+name+'_from_header.cso');target.write_bytes(data)
        source_shader_headers.append(identity(header));shader_inputs.append((name,target))
    for name,p in shader_inputs:
        blob=HERE/(name+'_root_signature.bin');blob.write_bytes(root_blob(p.read_bytes()))
        args=[str(HERE/'root_inspector.exe'),str(blob)]
        r=subprocess.run(args,cwd=HERE,capture_output=True)
        (HERE/(name+'_root_inspector.stdout.bin')).write_bytes(r.stdout);(HERE/(name+'_root_inspector.stderr.bin')).write_bytes(r.stderr)
        assert r.returncode==0,'CPU root signature inspector failure '+name
        decoded=json.loads(r.stdout);decoded.update(name=name,shader=identity(p),root_blob=identity(blob),command=args)
        signatures.append(decoded)
    save(HERE/'root_signatures.json',{'schema':'actual-embedded-root-signature-CPU-deserialization-v1','signatures':signatures,
        'version_enums':{'1':'1.0','2':'1.1'},'range_flag_bits':{'1':'DESCRIPTORS_VOLATILE','2':'DATA_VOLATILE','4':'DATA_STATIC_WHILE_SET_AT_EXECUTE','8':'DATA_STATIC'},
        'root_descriptor_flag_bits':{'2':'DATA_VOLATILE','4':'DATA_STATIC_WHILE_SET_AT_EXECUTE','8':'DATA_STATIC'},
        'fixture_semantics':'Identity forced 1.0: descriptor/data changes before submit have volatile semantics. No CPU overwrite occurs after a submission until its completion fence.',
        'primary_reference':'https://learn.microsoft.com/en-us/windows/win32/direct3d12/root-signature-version-1-1',
        'GPU_jobs_added_by_inspection':0})
    assert signatures[0]['version_enum']==1,'fixture root signature must be 1.0'
    cases=[('safe_three',3,3,3,0,0),('deferred_four',4,3,3,0,0),('deferred_five',5,3,3,0,0),
           ('immutable_four',4,4,4,0,0),('immutable_five',5,5,5,0,0),
           ('fenced_four',4,3,3,1,0),('fenced_five',5,3,3,1,0),
           ('cb_only_five',5,3,5,0,1),('descriptor_only_five',5,5,3,0,1)]
    registrations=[]
    for name,n,c,d,f,s in cases:
        folder=HERE/'evidence'/name;folder.mkdir(parents=True,exist_ok=False)
        write(folder/'job.txt',f'{n} {c} {d} {f} {s}\n')
        intended=[[100+i,5000+i,200+i,0xD1A60001]for i in range(n)]
        def last(i,slots):return i if f else max(j for j in range(n)if j%slots==i%slots)
        predicted=[[100+last(i,c),5000+last(i,d),200+last(i,c),0xD1A60001]for i in range(n)]
        registrations.append({'case':name,'shader_dispatches':n,'cb_slots':c,'descriptor_slots':d,'fence_before_reuse':bool(f),
                              'class':'SplitComputeState'if s else'ComputeState','intended':intended,
                              'last_CPU_slot_contents_hypothesis':predicted,'expected_queue_executes_including_input_upload':3 if f else 2})
    registration={'schema':'isolated-extracted-compute-ring-lifetime-fixture-registration-v1','utc':datetime.now(timezone.utc).isoformat(),
        'branch':subprocess.check_output(['git','-C',str(ROOT),'branch','--show-current']).decode().strip(),
        'head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip(),
        'cases':registrations,'GPU_child_jobs':9,'identity_shader_dispatches':40,'native_SDK_contexts':0,'native_SDK_dispatches':0,
        'expected_queue_executes':20,'expected_signals':20,'expected_fence_waits':20,
        'preregistered_expected_behavior':'Safe<=slots, sufficient immutable slots, and completion-before-reuse controls preserve intended tuples. Deferred reused slots are hypothesized to expose latest CPU CB/SRV slot contents. Predictions are evaluated after actual readback; failures are retained, not rewritten.',
        'capture':'One stable output UAV, GPU copy to a distinct per-dispatch readback immediately after each Dispatch; independent out0..outN.bin plus concatenation. Inputs unique immutable textures, fully uploaded/fence-completed first.',
        'source_equivalence':{'exact_classes':['ComputeState','FrameDescriptorHeap'],
            'exact_helper_extract':'FSRDShaderUtils.h from kMaxBarriers through CreateUAVs, retaining original implementation text',
            'diagnostic_adaptation':'SplitComputeState adds two slot-count fields and changes CB/descriptor index selection only; original memcpy/root binding/modulo allocation/descriptor-create calls preserved.',
            'boundary':['No-op ScopedSkipHeapCapture and logging/release shims replace production global-hook dependencies.',
                        'Tiny identity shader uses same root parameter order/kinds but force1.0 volatile semantics,1SRV/1UAV,16-byte CB and1x1 integer textures; actual production header root versions/flags recorded separately.',
                        'Stable shared output UAV and explicit readback transitions isolate CB/SRV overwrite; production shader math and game queue scheduling are not executed.',
                        'Normal debug layer required; GPU-based validation is not enabled. Intentional lifetime violations may create debug messages; retain every message.']},
        'guard':{'source_sha256':sha(HERE/'native_resource_guard.py'),'timeout_seconds':240,'maximum_working_set_bytes':2*1024**3,'minimum_available_memory_bytes':1024**3,'sample_interval_seconds':.2},
        'quality_accepted':False,'game_run':False,'production_changes':False,
        'limitations':['Conditional CB/descriptor lifetime fixture only; actual game submission depth is unmeasured.',
                       'No stain/wave root cause, native provider issue, or accepted runtime fix follows from this test.',
                       'Standalone runner prior results wait every frame and do not reproduce deferred production scheduling.'],
        'original_sources':[identity(p)for p in(prod,utils,heaps,d3dx,ROOT/'OptiScaler/shaders/shader_tools/fsrd_toolchain.py')]+source_shader_headers,
        'actual_serialized_root_signatures':signatures,
        'build':{'shader_command':str(HERE/'shader_build_command.json'),'cpp_command':str(HERE/'fixture.build.cmd'),'runner':identity(HERE/'fixture.exe')}}
    save(HERE/'registration.json',registration)
    files=sorted(p for p in HERE.rglob('*')if p.is_file()and'__pycache__'not in p.parts)
    save(HERE/'pre_gpu_freeze.json',{'schema':'preregistered-compute-ring-before-GPU-byte-freeze-v1','utc':datetime.now(timezone.utc).isoformat(),
                                   'files':[identity(p)for p in files],'original_sources':registration['original_sources'],
                                   'GPU_child_jobs_already_run':0,'shader_dispatches_already_run':0,'native_dispatches_already_run':0})
    print(json.dumps({'registration':identity(HERE/'registration.json'),'pre_gpu_freeze':identity(HERE/'pre_gpu_freeze.json'),'planned_GPU_jobs':9,'planned_shader_dispatches':40,'planned_native_dispatches':0}),flush=True)
if __name__=='__main__':main()
