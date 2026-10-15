"""Exact compute descriptor offset -> shader register/space proof on real D3D12 roots.

Only synthetic roots are used. No title bytecode/assembly is embedded or shipped.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_fsrd_frame_survey as survey_fixture
from fsrd_toolchain import compile_cpp

CPP = r'''
#include <chrono>
using Kind=D3D12_DESCRIPTOR_RANGE_TYPE;
struct RegisterHost {
 Host& host; ComPtr<ID3D12DescriptorHeap> heap; std::vector<ComPtr<ID3D12RootSignature>> roots;
 D3D12_GPU_DESCRIPTOR_HANDLE gpu {};
 explicit RegisterHost(Host& h):host(h) {
  FrameSurvey::BeginCreationTracking(false); FrameSurvey::SetBindingWindow(true);
  D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
  hd.NumDescriptors=128; hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  hr(h.dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap))); FrameSurvey::HeapCreated(h.dev.Get(),heap.Get());
  gpu=heap->GetGPUDescriptorHandleForHeapStart();
 }
 ID3D12RootSignature* create(const std::vector<D3D12_DESCRIPTOR_RANGE>& ranges,
   D3D12_SHADER_VISIBILITY visibility=D3D12_SHADER_VISIBILITY_ALL,bool track=true) {
  D3D12_ROOT_PARAMETER params[6] {};
  for(UINT i=0;i<6;++i) { params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; params[i].Constants={100+i,0,1}; }
  params[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; params[1].DescriptorTable={UINT(ranges.size()),ranges.data()};
  params[1].ShaderVisibility=visibility;
  D3D12_DESCRIPTOR_RANGE output {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,2,0,0,0};
  params[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; params[5].DescriptorTable={1,&output};
  D3D12_ROOT_SIGNATURE_DESC desc {6,params,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
  ComPtr<ID3DBlob> blob,error; hr(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error));
  ComPtr<ID3D12RootSignature> root;
  hr(host.dev->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
  if(track) FrameSurvey::RootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
  roots.push_back(root); return root.Get();
 }
 void bind(ID3D12RootSignature* root,bool nativeTable=true) {
  host.list->SetComputeRootSignature(root); FrameSurvey::RootBinding(host.list.Get(),false,root);
  auto* ptr=heap.Get(); host.list->SetDescriptorHeaps(1,&ptr); FrameSurvey::DescriptorHeaps(host.list.Get(),1,&ptr);
  if(nativeTable) host.list->SetComputeRootDescriptorTable(1,gpu); FrameSurvey::Table(host.list.Get(),false,1,gpu);
  host.list->SetComputeRootDescriptorTable(5,gpu); FrameSurvey::Table(host.list.Get(),false,5,gpu);
 }
 bool match(UINT offset,UINT reg,UINT space=0,Kind kind=D3D12_DESCRIPTOR_RANGE_TYPE_SRV,UINT param=1) {
  return FrameSurvey::ComputeTableBindingMatches(host.list.Get(),param,kind,offset,reg,space);
 }
};
J registerTests(Host& h) {
 RegisterHost f(h);
 auto* base=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0}}); f.bind(base);
 for(UINT i=0;i<4;++i) need(f.match(i,i),"space0/t0-based native root proves exact Recon offsets");
 need(f.match(0,0,0,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5) && f.match(1,1,0,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5),"native root5 proves Consumer u0/u1");
 need(!f.match(2,1) && !f.match(2,2,1) && !f.match(2,2,0,D3D12_DESCRIPTOR_RANGE_TYPE_UAV),"query register/space/kind mismatch fails");
 need(!f.match(8,8) && !f.match(0,0,0,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,2),"out-of-range offset and non-table parameter fail");
 const ULONG rootRefs=base->AddRef(); base->Release();
 for(UINT i=0;i<100;++i) need(f.match(2,2),"repeated live cached mapping remains exact");
 const ULONG afterRefs=base->AddRef(); base->Release(); need(rootRefs==afterRefs,"mapping lookup never AddRefs the title root");
 auto* shifted=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,7,0,0}}); f.bind(shifted);
 need(!f.match(2,2) && f.match(2,9),"offset2 is t9 for a t7-based native range, never guessed t2");
 auto* space=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,3,0}}); f.bind(space);
 need(!f.match(2,2,0) && f.match(2,2,3),"nonzero native register space is preserved and checked exactly");
 auto* appended=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,2,0,0,0},
   {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,0,0,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND},
   {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,2,10,2,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND}}); f.bind(appended);
 need(f.match(0,0,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV) && f.match(1,1,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV),"first mixed table range maps CBV b0/b1");
 need(f.match(2,0) && f.match(4,2) && !f.match(2,2),"APPEND offset accounts for prior CBV range before t0/t2");
 need(f.match(6,10,2,D3D12_DESCRIPTOR_RANGE_TYPE_UAV) && f.match(7,11,2,D3D12_DESCRIPTOR_RANGE_TYPE_UAV),"second APPEND range preserves its UAV namespace and space");
 auto* backwards=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,2,50,0,10},
   {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,0,0,1},
   {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,100,0,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND}}); f.bind(backwards);
 need(f.match(10,50) && f.match(1,0) && f.match(5,100) && f.match(8,103),"explicit reverse offsets and APPEND follow the preceding range, not highest previous end");
 need(!f.match(0,0) && !f.match(9,104),"gaps between native ranges are never guessed");
 auto* alias=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,10,0,2}}); f.bind(alias);
 need(!f.match(0,0) && !f.match(2,2) && !f.match(2,10),"native overlapping descriptor ranges are ambiguous even if one proposed register matches");
 auto* unbounded=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,UINT_MAX,0,0,0}}); f.bind(unbounded);
 need(!f.match(0,0) && !f.match(2,2),"native unbounded ranges never claim a finite bridge proof");
 auto* pixel=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0}},D3D12_SHADER_VISIBILITY_PIXEL); f.bind(pixel,false);
 need(!f.match(2,2),"metadata-only PIXEL table callback cannot prove compute shader bindings");
 auto* unknown=f.create({{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,21,0,0}},D3D12_SHADER_VISIBILITY_ALL,false); f.bind(unknown);
 need(!f.match(2,23),"actual unique root with no captured creation metadata fails closed");
 f.bind(base); FrameSurvey::RootBinding(h.list.Get(),false,shifted);
 need(!f.match(2,2),"root switch clears previous table binding rather than accepting stale base-zero metadata");
 FrameSurvey::Table(h.list.Get(),false,1,f.gpu);
 need(!f.match(2,2) && f.match(2,9),"after rebinding, current shifted root replaces the stale schema");
 f.bind(base); FrameSurvey::Reset(h.list.Get(),nullptr);
 need(!f.match(2,2),"command-list Reset clears current root/table identity");
 FrameSurvey::ComputeBindings seeded {shifted,{f.heap.Get()},{{1,f.gpu},{5,f.gpu}}};
 need(FrameSurvey::SeedComputeBindings(h.list.Get(),seeded) && f.match(2,9) && !f.match(2,2),"seed uses the actual current root register mapping");
 FrameSurvey::Released(shifted); need(!f.match(2,9),"released root metadata and mirror cannot remain eligible");
 f.bind(base); FrameSurvey::Released(h.list.Get()); need(!f.match(2,2),"released list loses binding eligibility");
 f.bind(base); FrameSurvey::SetBindingWindow(false); need(!f.match(2,2),"closed bridge binding window performs no mapping proof");
 FrameSurvey::SetBindingWindow(true); need(!f.match(2,2),"opening a fresh window cannot resurrect an old root snapshot");
 f.bind(base); { FrameSurvey::ScopedInternal internal; need(!f.match(2,2),"internal injection callbacks cannot query title mapping"); }
 need(f.match(2,2),"internal scope leaves title mapping unchanged");
 FrameSurvey::gMetadataHealthy.store(false); need(!f.match(2,2),"unhealthy captured metadata fails closed"); FrameSurvey::gMetadataHealthy.store(true);
 auto captured=FrameSurvey::ReadRoot(base).tables.at(1); need(FrameSurvey::UnambiguousComputeRanges(captured),"actual captured finite table is structurally eligible");
 auto unsafe=captured; unsafe[0].offset=UINT_MAX-2; unsafe[0].count=4;
 need(!FrameSurvey::UnambiguousComputeRanges(unsafe),"descriptor interval overflow rejects metadata before cache eligibility");
 unsafe=captured; unsafe[0].shaderRegister=UINT_MAX-2; unsafe[0].count=4;
 need(!FrameSurvey::UnambiguousComputeRanges(unsafe),"shader-register interval overflow rejects metadata before cache eligibility");
 unsafe=captured; unsafe[0].count=0; need(!FrameSurvey::UnambiguousComputeRanges(unsafe),"empty range never proves a binding");
 unsafe=captured; unsafe.push_back({D3D12_DESCRIPTOR_RANGE_TYPE_SRV,12,3,2,0});
 need(!FrameSurvey::UnambiguousComputeRanges(unsafe),"two offsets mapping to overlapping shader registers are ambiguous");
 unsafe=captured; unsafe.push_back({D3D12_DESCRIPTOR_RANGE_TYPE_SRV,12,3,2,1});
 need(FrameSurvey::UnambiguousComputeRanges(unsafe),"different spaces keep overlapping register numbers distinct");
 f.bind(base); const auto before=std::chrono::steady_clock::now();
 for(UINT i=0;i<200000;++i) if(!f.match(2,2)) throw std::runtime_error("measured mapping unexpectedly failed");
 const double ns=double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-before).count())/200000;
 hr(h.list->Close()); h.execute(); h.reset(); h.errors();
 return {{"checks_passed",checks},{"adapter",h.adapter},{"mapping_callback_mean_ns",ns},
   {"scope","production ReadRoot/API on actual D3D12 roots; synthetic overflow/duplicate-register metadata validation"},
   {"contains_title_binary",false}};
}
int main(int argc,char** argv) try {
 need(argc==2,"output path"); g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";
 Host host; auto result=registerTests(host);
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
'''

def run():
    output=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/12a-discovery/tests/register-bindings'))
    output.mkdir(parents=True,exist_ok=True)
    stubs=output/'stubs'
    for folder in ('proxies','inputs'):
        (stubs/folder).mkdir(parents=True,exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    text=(survey_fixture.CPP.split('// GetStatus()')[0]+CPP).replace('__TRACE__',(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__',(ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix())
    source=output/'fixture.cpp'; source.write_text(text,encoding='utf-8'); exe=output/'fixture.exe'
    compile_cpp(source,exe,('d3d12.lib','dxgi.lib','dxguid.lib','d3dcompiler.lib','bcrypt.lib','user32.lib','psapi.lib',str(ROOT/'OptiScaler/library/detours/detours.lib')),
        (stubs,ROOT/'OptiScaler',ROOT/'OptiScaler/include',ROOT/'external/streamline', ROOT/'external/nlohmann',ROOT/'external/nvngx_dlss_sdk',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe),str(output)],check=True,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result=json.loads((output/'host-result.json').read_text()); report=Path('E:/FSRD/sol_batch/12a-discovery'); report.mkdir(parents=True,exist_ok=True)
    (report/'register-bindings-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':
    run()
