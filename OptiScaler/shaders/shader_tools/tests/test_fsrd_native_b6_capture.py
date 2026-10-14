"""Production native b6 word303 GPU snapshot, without source-buffer/CBV metadata.

All input buffers, roots and the diagnostic Consumer are synthetic. This is a
focused capture/resolver test; it does not claim full game or AMD-provider proof.
Run through lead_ops/run_task_test.py to hold the shared GPU/build locks.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_fsrd_frame_survey as survey_fixture
import test_fsrd_nrd_register_bindings as register_fixture
import test_fsrd_nrd_constant_buffers as constants_fixture
from test_fsrd_nrd_root_restore import function
from fsrd_toolchain import compile_cpp

CPP = r'''
#include "shaders/fsrd_preprocess/FSRDNrdSignalConstants_Dx12.h"
#include <functional>
#include <cstring>
constexpr UINT kSnapshotWords=1536/4,kFlagWord=303,kSourceOffset=256;
constexpr uint32_t kNearWord=0x2468ace0u,kFirstWord=0x13579bdfu;
struct NativeCaptureHost {
 Host& h;ConstantHost bindings;
 NrdBridge::SignalFlagCapture capture;
 ComPtr<ID3D12RootSignature> directRoot,tableRoot;
 ComPtr<ID3D12PipelineState> directPso,tablePso;
 ComPtr<ID3D12Resource> consumerLog;
 unsigned captures=0,consumerDispatches=0,physicalSourceReleases=0;
 explicit NativeCaptureHost(Host& host):h(host),bindings(host) {
  std::string error;need(capture.Initialize(h.dev.Get(),error),error.c_str());
  directRoot=root(false);tableRoot=root(true);directPso=pso(directRoot.Get());tablePso=pso(tableRoot.Get());
  consumerLog=buffer(D3D12_HEAP_TYPE_DEFAULT,16,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,true);
  need(FrameSurvey::gResources.empty()&&FrameSurvey::gViews.empty(),"all capture inputs and private storage bypass source metadata");
 }
 ComPtr<ID3D12Resource> buffer(D3D12_HEAP_TYPE type,UINT64 bytes,D3D12_RESOURCE_STATES state,bool uav=false) {
  D3D12_HEAP_PROPERTIES hp{};hp.Type=type;
  const auto desc=CD3DX12_RESOURCE_DESC::Buffer(bytes,uav?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE);
  ComPtr<ID3D12Resource> result;
  hr(h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&result)));
  return result;
 }
 ComPtr<ID3D12Resource> source(uint32_t flag) {
  auto result=buffer(D3D12_HEAP_TYPE_UPLOAD,4096,D3D12_RESOURCE_STATE_GENERIC_READ);
  write(result.Get(),flag);return result;
 }
 void write(ID3D12Resource* resource,uint32_t flag) {
  void* data=nullptr;D3D12_RANGE noRead{0,0};hr(resource->Map(0,&noRead,&data));
  auto* words=reinterpret_cast<uint32_t*>(static_cast<uint8_t*>(data)+kSourceOffset);
  std::fill_n(words,kSnapshotWords,0xdeadbeefu);words[0]=kFirstWord;words[302]=kNearWord;words[303]=flag;words[304]=0xabcdef01u;
  D3D12_RANGE written{kSourceOffset,kSourceOffset+1536};resource->Unmap(0,&written);
 }
 void cbv(ID3D12Resource* resource) {
  D3D12_CONSTANT_BUFFER_VIEW_DESC desc{resource->GetGPUVirtualAddress()+kSourceOffset,1280};
  h.dev->CreateConstantBufferView(&desc,bindings.cpu(7,true));
 }
 ComPtr<ID3D12RootSignature> root(bool table) {
  D3D12_ROOT_PARAMETER1 params[6]{};
  for(UINT i=0;i<6;++i){params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV;params[i].Descriptor={100+i,0,D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};}
  D3D12_DESCRIPTOR_RANGE1 srvs{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,0,0,D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE|D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE,0};
  D3D12_DESCRIPTOR_RANGE1 uavs{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,2,0,0,D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE|D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE,0};
  D3D12_DESCRIPTOR_RANGE1 mixed[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1,20,0,D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE|D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE,0},
   {D3D12_DESCRIPTOR_RANGE_TYPE_CBV,8,0,0,D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE|D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE,D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND}};
  params[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[1].DescriptorTable={1,&srvs};
  params[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[5].DescriptorTable={1,&uavs};
  params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;params[2].Descriptor={20,0,D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};
  if(table){params[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[3].DescriptorTable={2,mixed};}
  else{params[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;params[0].Descriptor={6,0,D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};}
  D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};desc.Version=D3D_ROOT_SIGNATURE_VERSION_1_1;desc.Desc_1_1={6,params,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
  ComPtr<ID3DBlob> bytes,error;hr(D3D12SerializeVersionedRootSignature(&desc,&bytes,&error));
  ComPtr<ID3D12RootSignature> result;hr(h.dev->CreateRootSignature(0,bytes->GetBufferPointer(),bytes->GetBufferSize(),IID_PPV_ARGS(&result)));
  FrameSurvey::RootCreated(result.Get(),bytes->GetBufferPointer(),bytes->GetBufferSize());return result;
 }
 ComPtr<ID3D12PipelineState> pso(ID3D12RootSignature* root) {
  const char shader[]="cbuffer TitleConsumer:register(b6){uint4 CB[76];} RWByteAddressBuffer O:register(u20); [numthreads(1,1,1)] void main(){uint f=CB[75].w;O.Store(0,f);O.Store(4,f!=0?1u:0u);O.Store(8,CB[75].z);O.Store(12,CB[0].x);}";
  ComPtr<ID3DBlob> bytes,error;hr(D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"main","cs_5_0",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&bytes,&error));
  D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};desc.pRootSignature=root;desc.CS={bytes->GetBufferPointer(),bytes->GetBufferSize()};
  ComPtr<ID3D12PipelineState> result;hr(h.dev->CreateComputePipelineState(&desc,IID_PPV_ARGS(&result)));return result;
 }
 void transition(ID3D12Resource* resource,D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
  D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
  barrier.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,from,to};h.list->ResourceBarrier(1,&barrier);
 }
 void initializeSnapshot(NrdBridge::SignalFlagSnapshot& snapshot) {
  auto upload=buffer(D3D12_HEAP_TYPE_UPLOAD,1536,D3D12_RESOURCE_STATE_GENERIC_READ);
  void* data=nullptr;D3D12_RANGE noRead{0,0};hr(upload->Map(0,&noRead,&data));
  auto* words=static_cast<uint32_t*>(data);for(UINT i=0;i<kSnapshotWords;++i)words[i]=0x90000000u+i;
  upload->Unmap(0,nullptr);transition(snapshot.resource.Get(),D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST);
  h.list->CopyBufferRegion(snapshot.resource.Get(),0,upload.Get(),0,1536);
  transition(snapshot.resource.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_COMMON);h.uploads.push_back(upload);
 }
 void bindTitle(const NrdBridge::TitleSignalConstants& constants,bool table) {
  auto* titleRoot=table?tableRoot.Get():directRoot.Get();auto* titlePso=table?tablePso.Get():directPso.Get();
  bindings.bind(titleRoot);h.list->SetPipelineState(titlePso);
  if(table){h.list->SetComputeRootDescriptorTable(3,bindings.gpu);FrameSurvey::Table(h.list.Get(),false,3,bindings.gpu);}
  else{h.list->SetComputeRootConstantBufferView(0,constants.address);FrameSurvey::RootView(h.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,constants.address);}
  h.list->SetComputeRootUnorderedAccessView(2,consumerLog->GetGPUVirtualAddress());
  bindings.trackSnapshot(titleRoot,constants.address,table);auto& state=rootStates[h.list.Get()];
  state[2].type=RootEntryType::UAV;state[2].bufferLocation=consumerLog->GetGPUVirtualAddress();
 }
 J run(const char* name,const NrdBridge::TitleSignalConstants& constants,bool table,uint32_t expected,const std::function<void()>& afterRecord={}) {
  NrdBridge::SignalFlagSnapshot snapshot;std::string error;need(snapshot.Initialize(h.dev.Get(),error),error.c_str());
  need(NrdBridge::ValidateTitleSignalConstants(constants,h.dev.Get(),error),error.c_str());
  bindTitle(constants,table);FrameSurvey::BoundConstantBinding native;FrameSurvey::ComputeBindings current;
  need(FrameSurvey::ResolveComputeConstantBinding(h.list.Get(),6,0,native),"production native resolver accepts unregistered source before capture");
  need(GetComputeBindingsForBridge(h.list.Get(),current)&&FrameSurvey::ValidateComputeConstantBinding(current,6,0,native),"production getter validates exact current native binding");
  need(!constants.resource&&FrameSurvey::gResources.empty()&&FrameSurvey::gViews.empty(),"capture has no title resource pointer and no source/CBV metadata");
  initializeSnapshot(snapshot);capture.Record(h.list.Get(),constants,snapshot);++captures;
  // The diagnostic Consumer uses the original native root/table after explicit restoration.
  // Full production detour restoration is covered by the separate integrated E2E fixture.
  bindTitle(constants,table);h.list->Dispatch(1,1,1);++consumerDispatches;
  auto flagReadback=buffer(D3D12_HEAP_TYPE_READBACK,1536,D3D12_RESOURCE_STATE_COPY_DEST);
  auto titleReadback=buffer(D3D12_HEAP_TYPE_READBACK,16,D3D12_RESOURCE_STATE_COPY_DEST);
  transition(snapshot.resource.Get(),D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER,D3D12_RESOURCE_STATE_COPY_SOURCE);
  h.list->CopyBufferRegion(flagReadback.Get(),0,snapshot.resource.Get(),0,1536);
  transition(snapshot.resource.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_COMMON);
  transition(consumerLog.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
  h.list->CopyBufferRegion(titleReadback.Get(),0,consumerLog.Get(),0,16);
  transition(consumerLog.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  hr(h.list->Close());if(afterRecord)afterRecord();
  need(FrameSurvey::ValidateComputeConstantBinding(current,6,0,native),"native slot/VA remains current after permitted post-record data or descriptor change");
  h.execute();void* data=nullptr;D3D12_RANGE read{0,1536};hr(flagReadback->Map(0,&read,&data));
  const auto* words=static_cast<const uint32_t*>(data);
  need(words[kFlagWord]==expected,"owned snapshot copies exact word303 bits observed at Execute");
  bool untouched=true;for(UINT i=0;i<kSnapshotWords;++i)if(i!=kFlagWord)untouched&=words[i]==0x90000000u+i;
  need(untouched,"capture changes only word303; all other owned snapshot words retain exact sentinel bits");
  flagReadback->Unmap(0,nullptr);read={0,16};hr(titleReadback->Map(0,&read,&data));words=static_cast<const uint32_t*>(data);
  need(words[0]==expected&&words[1]==(expected?1u:0u)&&words[2]==kNearWord&&words[3]==kFirstWord,"original native Consumer sees the same exact flag, uint zero/nonzero selector and source offset");
  titleReadback->Unmap(0,nullptr);
  need(FrameSurvey::gResources.empty()&&FrameSurvey::gViews.empty(),"GPU capture and diagnostic Consumer leave all title source registries empty");
  h.reset();need(!FrameSurvey::ResolveComputeConstantBinding(h.list.Get(),6,0,native),"actual list Reset retires native mirror eligibility");
  return {{"name",name},{"word303",expected},{"table",table},{"source_registered",false},{"cbv_registered",false},{"owned_other_words_untouched",true}};
 }
 void errors() {
  need(bool(h.info),"D3D12 debug info queue is available");UINT64 errors=0,warnings=0;
  for(UINT64 i=0;i<h.info->GetNumStoredMessagesAllowedByRetrievalFilter();++i){
   SIZE_T size=0;hr(h.info->GetMessage(i,nullptr,&size));std::vector<uint8_t> bytes(size);auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());hr(h.info->GetMessage(i,message,&size));
   if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)++errors;if(message->Severity==D3D12_MESSAGE_SEVERITY_WARNING)++warnings;
   if(message->Severity<=D3D12_MESSAGE_SEVERITY_WARNING)std::cerr<<message->pDescription<<'\n';
  }
  need(errors==0&&warnings==0,"native capture and Consumer generate zero D3D12 debug errors/warnings");
 }
};
int main(int argc,char** argv) try {
 need(argc==2,"output path");g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Host host;FrameSurvey::Shutdown();NativeCaptureHost f(host);
 J cases=J::array();const std::array<uint32_t,4> flags{0u,1u,0x80000000u,0x7fc00000u};
 auto direct=f.source(0);NrdBridge::TitleSignalConstants constants{};constants.address=direct->GetGPUVirtualAddress()+kSourceOffset;
 for(auto flag:flags){f.write(direct.Get(),flag^0xffffffffu);cases.push_back(f.run("direct GPUVA; data updated after recording",constants,false,flag,[&]{f.write(direct.Get(),flag);}));}
 auto before=f.source(0),after=f.source(0);constants={};constants.nativeHeap=f.bindings.heap.Get();constants.cbvHandle={f.bindings.gpu.ptr+7*f.bindings.stride};
 for(auto flag:flags){f.write(before.Get(),flag^0xffffffffu);f.write(after.Get(),flag);f.cbv(before.Get());cases.push_back(f.run("native volatile table; descriptor updated after recording",constants,true,flag,[&]{f.cbv(after.Get());}));}
 auto temporary=f.source(0);f.write(after.Get(),0x80000000u);f.cbv(temporary.Get());
 cases.push_back(f.run("native volatile table; final source Release then live replacement",constants,true,0x80000000u,[&]{
  auto* raw=temporary.Detach();FrameSurvey::Released(raw);need(raw->Release()==0,"old unregistered table source has genuine physical final Release=0");++f.physicalSourceReleases;f.cbv(after.Get());}));
 // A default-heap title CBV is legal without any CPU map or source registry lookup.
 auto staging=f.source(0x7fc00000u);auto gpuSource=f.buffer(D3D12_HEAP_TYPE_DEFAULT,4096,D3D12_RESOURCE_STATE_COPY_DEST);
 host.list->CopyBufferRegion(gpuSource.Get(),0,staging.Get(),0,4096);f.transition(gpuSource.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER);
 hr(host.list->Close());host.execute();host.reset();f.cbv(gpuSource.Get());
 cases.push_back(f.run("native table; unregistered default-heap source",constants,true,0x7fc00000u));
 constants={};constants.address=gpuSource->GetGPUVirtualAddress()+kSourceOffset;
 cases.push_back(f.run("direct GPUVA; unregistered default-heap source",constants,false,0x7fc00000u));
 need(f.captures==11&&f.consumerDispatches==11&&f.physicalSourceReleases==1,"every scenario records exactly one capture and one original diagnostic Consumer");f.errors();
 J result{{"checks_passed",checks},{"adapter",host.adapter},{"capture_dispatches",f.captures},{"original_consumer_dispatches",f.consumerDispatches},
  {"source_final_release_zero",f.physicalSourceReleases},{"debug_errors",0},{"debug_warnings",0},{"cases",cases},
  {"scope","production native binding resolver/getter and both actual SignalFlagCapture PSOs; synthetic Consumer with explicit native restoration; no full coordinator/provider proof"},
  {"contains_title_binary",false},{"render_extent_dependency","one native word303 capture uses Dispatch(1,1,1) for every render extent"}};
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n';std::cout<<result.dump()<<'\n';return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
'''


def build(output):
    stubs = output / 'stubs'
    for folder in ('proxies', 'inputs'):
        (stubs / folder).mkdir(parents=True, exist_ok=True)
    (stubs / 'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#include <shared_mutex>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs / 'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    (stubs / 'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs / 'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    hooks = (ROOT / 'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    state = hooks[hooks.index('enum class RootEntryType'):hooks.index('enum class SignatureEntryType')]
    getter = function(hooks, 'bool D3D12Hooks::GetComputeBindingsForBridge(').replace('D3D12Hooks::', '')
    restrack = (ROOT / 'OptiScaler/resource_tracking/ResTrack_Dx12.cpp').read_text()
    cbvhook = function(restrack, 'void ResTrack_Dx12::hkSurveyCreateConstantBufferView(').replace('ResTrack_Dx12::', '')
    text = (survey_fixture.CPP.split('// GetStatus()')[0]
            + register_fixture.CPP.split('J registerTests')[0]
            + constants_fixture.CPP.split('J constantTests')[0] + CPP)
    text = text.replace('__TRACE__', (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix())
    text = text.replace('__SURVEY__', (ROOT / 'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix())
    text = text.replace('__STATE__', state).replace('__GETTER__', getter).replace('__CBVHOOK__', cbvhook)
    source = output / 'fixture.cpp'
    source.write_text(text, encoding='utf-8')
    executable = output / 'fixture.exe'
    compile_cpp(source, executable,
                ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib',
                 str(ROOT / 'OptiScaler/library/detours/detours.lib')),
                (stubs, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann',
                 ROOT / 'external/nvngx_dlss_sdk', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    return executable


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/12e-e2e/tests/native-b6-capture'))
    output.mkdir(parents=True, exist_ok=True)
    executable = build(output)
    subprocess.run([str(executable), str(output)], check=True,
                   creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result = json.loads((output / 'host-result.json').read_text())
    assert result['capture_dispatches'] == result['original_consumer_dispatches'] == 11
    assert result['source_final_release_zero'] == 1
    assert result['debug_errors'] == result['debug_warnings'] == 0
    assert {case['word303'] for case in result['cases']} == {0, 1, 0x80000000, 0x7fc00000}
    for name in ('FSRDNrdBridgeFlag_Shader.cso', 'FSRDNrdBridgeFlagRoot_Shader.cso'):
        path = ROOT / 'OptiScaler/shaders/fsrd_preprocess/precompile' / name
        result.setdefault('production_capture_shader_sha256', {})[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result['python_checks_passed'] = 4
    report = Path(os.environ.get('FSRD_TASK_REPORT_DIR', 'E:/FSRD/sol_batch/12e-e2e'))
    report.mkdir(parents=True, exist_ok=True)
    (report / 'native-b6-capture-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    run()
