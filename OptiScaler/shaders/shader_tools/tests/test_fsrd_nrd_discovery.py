"""Production NRD discovery replay and real D3D12 binding-window fixture.

Conversion/RR are explicit counter stubs here: GPU/provider output and real state
restoration are verified by the separate end-to-end fixture, not claimed by this test.
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
#define FSRD_NRD_BRIDGE_TEST
#include "__COORDINATOR__"
#include <thread>
#include <chrono>
unsigned convertCalls=0, rrCalls=0, debugCalls=0, depthResets=0, rrResets=0;
bool internalObserved=true, trackingSuppressed=true, observerUnlocked=true, throwPrepare=false;
namespace NrdBridge {
struct ConversionPass::Impl {};
ConversionPass::ConversionPass()=default; ConversionPass::~ConversionPass()=default;
bool ConversionPass::Initialize(ID3D12Device*,uint32_t,uint32_t,std::string&) { return true; }
bool ConversionPass::Dispatch(ID3D12GraphicsCommandList* cmd,const ConversionInputs&,const FrameParameters&,
                             ConvertedResources& out,std::string&) {
 ++convertCalls; internalObserved &= FrameSurvey::Internal(); trackingSuppressed &= !D3D12Hooks::tracking;
 // Internal callbacks must not alter either mirror or the live title role.
 FrameSurvey::RootBinding(cmd,false,nullptr); OnSetPipeline(cmd,nullptr); out.width=64; out.height=32; return true;
}
bool ConversionPass::WriteDebug(ID3D12GraphicsCommandList*,const ConvertedResources&,ID3D12Resource*,
                               ID3D12Resource*,DebugMode,std::string&) { ++debugCalls; return true; }
void ConversionPass::ResetHistory() noexcept { ++depthResets; }
uint64_t ConversionPass::OwnedTextureBytes() const noexcept { return 0; }
struct RRWrapper::Impl {};
RRWrapper::RRWrapper()=default; RRWrapper::~RRWrapper()=default;
bool RRWrapper::PrepareFrame(const SLConstantsSnapshot& sl,bool reset,FrameParameters& out,std::string&) {
 if(throwPrepare) throw std::runtime_error("fixture provider exception");
 out.streamlineFrame=sl.frameIndex; out.frameIndex=rrCalls; out.reset=reset; return true;
}
bool RRWrapper::Dispatch(ID3D12GraphicsCommandList*,const ConvertedResources&,ID3D12Resource*,ID3D12Resource*,
                        const FrameParameters&,std::string&) {
 ++rrCalls; internalObserved &= FrameSurvey::Internal(); trackingSuppressed &= !D3D12Hooks::tracking; return true;
}
void RRWrapper::ResetHistory() noexcept { ++rrResets; }
uint64_t RRWrapper::ContextGeneration() const noexcept { return 0; }
}
void observerLockProbe() {
 bool registry=false, mirror=false;
 std::thread probe([&] {
  registry=FrameSurvey::gLifetimeMutex.try_lock(); if(registry) FrameSurvey::gLifetimeMutex.unlock();
  mirror=FrameSurvey::gMirrorMutex.try_lock(); if(mirror) FrameSurvey::gMirrorMutex.unlock();
 }); probe.join(); observerUnlocked &= registry && mirror;
}
void pipelineObserved(ID3D12PipelineState* pso,const char* hash) { observerLockProbe(); NrdBridge::OnPipelineCreated(pso,hash); }
void releaseObserved(void* object) { observerLockProbe(); NrdBridge::OnReleased(object); }
using Bound=FrameSurvey::BoundResource;
using Role=NrdBridge::Role;
struct ChainHost {
 Host& h; ComPtr<ID3D12RootSignature> root;
 std::array<ComPtr<ID3D12PipelineState>,11> pipelines;
 ComPtr<ID3D12DescriptorHeap> staging, visible;
 std::array<ComPtr<ID3D12Resource>,13> textures;
 UINT increment=0;
 D3D12_CPU_DESCRIPTOR_HANDLE cpu {}; D3D12_GPU_DESCRIPTOR_HANDLE gpu {};
 explicit ChainHost(Host& host):h(host) {
  FrameSurvey::BeginCreationTracking(false);
  need(FrameSurvey::Install(h.dev.Get(),h.list.Get(),false),"metadata-only hooks install");
  need(!FrameSurvey::Enabled() && !FrameSurvey::GetStatus().installed,"metadata hooks do not enable survey recorder");
  Config::Instance()->FfxDenoiserNrdBridge.value=false;
  need(!NrdBridge::Initialize(h.dev.Get()),"startup disabled creates no service");
  Config::Instance()->FfxDenoiserNrdBridge.value=true;
  need(NrdBridge::Initialize(h.dev.Get()),"bridge coordinator initializes");
  need(NrdBridge::Initialize(h.dev.Get()),"same-device initialization is idempotent");
  FrameSurvey::SetPipelineObserver(pipelineObserved); FrameSurvey::SetReleaseObserver(releaseObserved);
  D3D12_DESCRIPTOR_RANGE ranges[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5,0,0,0}};
  D3D12_ROOT_PARAMETER params[6] {};
  for(UINT i=0;i<6;++i) { params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; params[i].Constants={i,0,1}; }
  params[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; params[1].DescriptorTable={1,&ranges[0]};
  params[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; params[5].DescriptorTable={1,&ranges[1]};
  D3D12_ROOT_SIGNATURE_DESC desc {6,params,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
  ComPtr<ID3DBlob> blob,error; hr(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error));
  hr(h.dev->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
  FrameSurvey::RootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
  const char shader[]="[numthreads(1,1,1)] void main(uint3 p:SV_DispatchThreadID) {}";
  ComPtr<ID3DBlob> cs; hr(D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"main","cs_5_0",0,0,&cs,&error));
  for(UINT i=0;i<pipelines.size();++i) {
   D3D12_COMPUTE_PIPELINE_STATE_DESC pd {}; pd.pRootSignature=root.Get(); pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
   hr(h.dev->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pipelines[i]))); FrameSurvey::PipelineCreated(pipelines[i].Get(),pd);
   NrdBridge::RegisterPipelineRoleForTesting(pipelines[i].Get(),Role(i));
  }
  for(UINT i=0;i<textures.size();++i) {
   auto desc=CD3DX12_RESOURCE_DESC::Tex2D(i==2 ? DXGI_FORMAT_R10G10B10A2_UNORM : i==3 ? DXGI_FORMAT_R32_FLOAT : DXGI_FORMAT_R16G16B16A16_FLOAT,
    64,32,1,1,1,0,i==7 || i==8 ? D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET|D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
   D3D12_HEAP_PROPERTIES hp {}; hp.Type=D3D12_HEAP_TYPE_DEFAULT;
   const auto state=(i==0 || i==1 || i==2 || i==3 || i==6) ? D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE : D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
   hr(h.dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&textures[i])));
   FrameSurvey::ResourceCreated(textures[i].Get(),state);
  }
  D3D12_DESCRIPTOR_HEAP_DESC hd {}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors=128;
  hr(h.dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&staging))); FrameSurvey::HeapCreated(h.dev.Get(),staging.Get());
  hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  hr(h.dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&visible))); FrameSurvey::HeapCreated(h.dev.Get(),visible.Get());
  increment=h.dev->GetDescriptorHandleIncrementSize(hd.Type); cpu=staging->GetCPUDescriptorHandleForHeapStart(); gpu=visible->GetGPUDescriptorHandleForHeapStart();
  views(0,{0,1,2,3,0,1,2,3},false); views(8,{4,5,9,0,2},true);
  views(16,{9,10,6,2,3,0,1,2},false);
  views(24,{9,10,9,10,9},true); views(32,{7,8,9,10,9},true);
  views(40,{11,12,9,10,9},true); views(48,{8,7,9,10,9},true);
  NrdBridge::OnTitleTag(h.list.Get(),"MotionVectors",textures[6].Get());
 }
 void views(UINT first,std::initializer_list<UINT> indices,bool uav) {
  UINT offset=0; for(const auto index:indices) {
   D3D12_CPU_DESCRIPTOR_HANDLE handle {cpu.ptr+uint64_t(first+offset++)*increment}; const auto resource=textures[index].Get();
   if(uav) {
    D3D12_UNORDERED_ACCESS_VIEW_DESC uv {}; uv.Format=resource->GetDesc().Format; uv.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
    h.dev->CreateUnorderedAccessView(resource,nullptr,&uv,handle); FrameSurvey::View(resource,handle,&uv);
   } else {
    D3D12_SHADER_RESOURCE_VIEW_DESC sv {}; sv.Format=resource->GetDesc().Format; sv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
    sv.Texture2D.MipLevels=1; sv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    h.dev->CreateShaderResourceView(resource,&sv,handle); FrameSurvey::View(resource,handle,&sv);
   }
  }
 }
 void begin() {
  FrameSurvey::Reset(h.list.Get(),nullptr); NrdBridge::OnReset(h.list.Get(),nullptr);
  h.list->SetComputeRootSignature(root.Get()); FrameSurvey::RootBinding(h.list.Get(),false,root.Get());
  ID3D12DescriptorHeap* heap=visible.Get(); h.list->SetDescriptorHeaps(1,&heap); FrameSurvey::DescriptorHeaps(h.list.Get(),1,&heap);
  for(UINT i : {0u,2u,3u,4u}) h.list->SetComputeRoot32BitConstant(i,0,0);
  auto dst=visible->GetCPUDescriptorHandleForHeapStart(); UINT n=64;
  h.dev->CopyDescriptors(1,&dst,&n,1,&cpu,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  FrameSurvey::CopyDescriptors(h.dev.Get(),1,&dst,&n,1,&cpu,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 }
 void bind(UINT parameter,UINT index) {
  D3D12_GPU_DESCRIPTOR_HANDLE handle {gpu.ptr+uint64_t(index)*increment};
  h.list->SetComputeRootDescriptorTable(parameter,handle); FrameSurvey::Table(h.list.Get(),false,parameter,handle);
 }
 void pass(Role role,UINT uav=8) {
  h.list->SetPipelineState(pipelines[UINT(role)].Get()); FrameSurvey::SetPipeline(h.list.Get(),pipelines[UINT(role)].Get());
  NrdBridge::OnSetPipeline(h.list.Get(),pipelines[UINT(role)].Get());
  bind(1,role==Role::Temporal ? 16 : 0); bind(5,uav);
  NrdBridge::BeforeDispatch(h.list.Get()); h.list->Dispatch(1,1,1); NrdBridge::AfterDispatch(h.list.Get());
 }
 void frame(UINT count,UINT bcount=2) {
  begin(); pass(Role::PrepLast); pass(Role::Recon); pass(Role::PrePass); pass(Role::Temporal);
  pass(Role::Chain3); pass(Role::HistSave); pass(Role::HistFix); pass(Role::Clamp);
  for(UINT i=0;i<count;++i) pass(Role::ATrous,i+1==count ? 32 : 24);
  pass(Role::PrePass); pass(Role::Temporal); pass(Role::Clamp);
  for(UINT i=0;i<bcount;++i) pass(Role::ATrous,40);
  pass(Role::Consumer,48);
 }
 std::vector<Bound> table(UINT parameter) { std::vector<Bound> out; need(FrameSurvey::ResolveComputeTable(h.list.Get(),parameter,out),"real descriptor table resolves"); return out; }
};
template<class Call> J measure(const char* name,UINT n,Call call) {
 for(UINT i=0;i<100;++i) call(); std::vector<double> samples;
 for(UINT batch=0;batch<7;++batch) {
  const auto start=std::chrono::steady_clock::now(); for(UINT i=0;i<n;++i) call();
  samples.push_back(double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count())/n);
 }
 std::sort(samples.begin(),samples.end()); return {{"callback",name},{"iterations_per_batch",n},{"batches",7},{"median_ns",samples[3]},{"minimum_ns",samples[0]},{"maximum_ns",samples[6]}};
}
J cpuTimings(ChainHost& c) {
 FrameSurvey::SetBindingWindow(false);
 const auto resource=c.textures[0].Get(); D3D12_SHADER_RESOURCE_VIEW_DESC view {};
 view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT; view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
 view.Texture2D.MipLevels=1; view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
 const auto dest=c.visible->GetCPUDescriptorHandleForHeapStart(); UINT n=1;
 J timings=J::array();
 timings.push_back(measure("creation registry: cached ResourceCreated",100000,[&]{FrameSurvey::ResourceCreated(resource,srv);}));
 timings.push_back(measure("creation registry: SRV overwrite",100000,[&]{FrameSurvey::View(resource,c.cpu,&view);}));
 timings.push_back(measure("closed binding window: Table callback",200000,[&]{FrameSurvey::Table(c.h.list.Get(),false,1,c.gpu);}));
 timings.push_back(measure("closed binding window: CopyDescriptors callback",200000,[&]{FrameSurvey::CopyDescriptors(c.h.dev.Get(),1,&dest,&n,1,&c.cpu,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);}));
 FrameSurvey::SetBindingWindow(true); c.begin(); c.bind(1,0); c.bind(5,8);
 timings.push_back(measure("open binding window: Table callback",100000,[&]{FrameSurvey::Table(c.h.list.Get(),false,1,c.gpu);}));
 timings.push_back(measure("open binding window: CopyDescriptors callback one descriptor",50000,[&]{FrameSurvey::CopyDescriptors(c.h.dev.Get(),1,&dest,&n,1,&c.cpu,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);}));
 std::vector<Bound> out;
 timings.push_back(measure("open binding window: ResolveComputeTable eight descriptors",20000,[&]{FrameSurvey::ResolveComputeTable(c.h.list.Get(),1,out);}));
 FrameSurvey::SetBindingWindow(false);
 FrameSurvey::SetPipelineObserver(NrdBridge::OnPipelineCreated);
 UINT bytes=0; hr(c.root->GetPrivateData(FrameSurvey::RootBlobId,&bytes,nullptr)); std::vector<uint8_t> rootBytes(bytes);
 hr(c.root->GetPrivateData(FrameSurvey::RootBlobId,&bytes,rootBytes.data()));
 timings.push_back(measure("creation registry: RootCreated serialization metadata and hash",1000,[&]{FrameSurvey::RootCreated(c.root.Get(),rootBytes.data(),rootBytes.size());}));
 const char shader[]="[numthreads(1,1,1)] void main(uint3 p:SV_DispatchThreadID) {}"; ComPtr<ID3DBlob> cs,errors;
 hr(D3DCompile(shader,sizeof(shader),nullptr,nullptr,nullptr,"main","cs_5_0",0,0,&cs,&errors));
 D3D12_COMPUTE_PIPELINE_STATE_DESC pd {}; pd.pRootSignature=c.root.Get(); pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
 timings.push_back(measure("creation registry: PipelineCreated compute shader and root hashes",1000,[&]{FrameSurvey::PipelineCreated(c.pipelines[0].Get(),pd);}));
 return timings;
}
J discoveryTests(Host& h) {
 ChainHost c(h); need(FrameSurvey::BindingWindow(),"initial binding window opens before title recording");
 const ULONG refs=c.textures[7]->AddRef(); c.textures[7]->Release();
 c.frame(3,5); auto status=NrdBridge::GetStatus();
 need(status.width==64 && status.height==32 && !status.resources.empty(),"first full chain caches render extent/resources");
 need(convertCalls==0 && rrCalls==0,"discovery frame injects nothing before full cache is known");
 need(!FrameSurvey::BindingWindow(),"stable discovery closes binding mirror and descriptor-copy window");
 auto resources=NrdBridge::gService->cache.Get();
 need(resources.inputSpec==c.textures[0].Get() && resources.inputDiff==c.textures[1].Get(),"Recon input spec/diff offsets");
 need(resources.normals==c.textures[2].Get() && resources.viewDepth==c.textures[3].Get(),"normal/depth offsets");
 need(resources.reconSpec==c.textures[4].Get() && resources.reconDiff==c.textures[5].Get(),"reconstructed spec/diff offsets");
 need(resources.motion==c.textures[6].Get(),"first Temporal motion equals Streamline tag");
 need(resources.outputSpec==c.textures[7].Get() && resources.outputDiff==c.textures[8].Get(),"Consumer reversed chain A pair ignores chain B");
 const ULONG after=c.textures[7]->AddRef(); c.textures[7]->Release(); need(refs==after,"discovery cache holds borrowed game resources without AddRef");
 StreamlineHooks::frame=1; c.frame(6,1);
 need(convertCalls==1 && rrCalls==1 && NrdBridge::GetStatus().active,"cache drives same-list conversion and pre-Consumer RR");
 need(internalObserved && trackingSuppressed && D3D12Hooks::tracking,"injected callbacks are internal and tracking restored");
 need(D3D12Hooks::restores==2,"state restore invoked after both injections");
 NrdBridge::OnPresent(); NrdBridge::OnPresent(); NrdBridge::OnPresent();
 need(NrdBridge::gService->cache.Valid(),"duplicate FG Presents retain discovery and history");
 const auto oldDepth=depthResets, oldRR=rrResets;
 NrdBridge::SetRuntimeEnabled(false); StreamlineHooks::frame=2; c.frame(3);
 need(convertCalls==1 && rrCalls==1 && !FrameSurvey::BindingWindow(),"runtime off dispatches no bridge work and closes binding window");
 NrdBridge::SetRuntimeEnabled(true); StreamlineHooks::frame=3; c.frame(3);
 need(convertCalls==2 && rrCalls==2 && depthResets>oldDepth && rrResets>oldRR,"runtime re-enable resets depth and RR histories");
 NrdBridge::SetDebugMode(NrdBridge::DebugMode::RawSignals); StreamlineHooks::frame=4; c.frame(3);
 need(debugCalls==1 && rrCalls==2,"Raw mode selects real conversion WriteDebug interface");
 NrdBridge::SetDebugMode(NrdBridge::DebugMode::Off); NrdBridge::RequestHistoryReset();
 const auto beforeReset=rrResets; StreamlineHooks::frame=5; c.frame(3); need(rrResets>beforeReset,"explicit menu reset reaches RR and conversion");
 // A conversion whose list resets before Consumer must not be used by the following frame.
 StreamlineHooks::frame=6; c.begin(); c.pass(Role::Recon); const auto beforeGap=rrResets;
 NrdBridge::OnReset(h.list.Get(),nullptr); StreamlineHooks::frame=7; c.frame(3); need(rrResets>beforeGap,"incomplete list recording resets histories");
 NrdBridge::OnPresent(); // Consume the most recent rendered frame before counting missing ones.
 for(UINT i=0;i<30;++i) { StreamlineHooks::frame=8+i; NrdBridge::OnPresent(); }
 need(!NrdBridge::gService->cache.Valid() && FrameSurvey::BindingWindow(),"missing Recon for thirty distinct SL frames invalidates cache");
 StreamlineHooks::frame=38; c.frame(6,4); need(NrdBridge::gService->cache.Valid(),"six-iteration chain rediscovers after missing Recon");
 FrameSurvey::Released(c.textures[8].Get());
 need(!NrdBridge::gService->cache.Valid() && FrameSurvey::BindingWindow(),"release invalidates discovered borrowed output");
 need(observerUnlocked,"pipeline/release observers run outside lifetime and mirror locks");
 // Re-register still-owned fixture resource solely to test rediscovery (the title would create a replacement).
 FrameSurvey::ResourceCreated(c.textures[8].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS); c.views(48,{8,7,9,10,9},true); c.views(32,{7,8,9,10,9},true);
 StreamlineHooks::frame=39; c.frame(3); need(NrdBridge::gService->cache.Valid(),"release invalidation permits a clean bounded rediscovery");
 // Missing restoration and provider exceptions fail closed; successful rediscovery cannot hide repeated failures.
 const auto beforeFailedConversion=convertCalls; D3D12Hooks::canRestore=false;
 StreamlineHooks::frame=40; c.frame(3);
 need(convertCalls==beforeFailedConversion && !NrdBridge::GetStatus().active && !NrdBridge::gService->cache.Valid(),"missing state restore prevents conversion and invalidates discovery");
 D3D12Hooks::canRestore=true;
 for(UINT attempt=0;attempt<2;++attempt) {
  for(UINT present=0;present<60;++present) NrdBridge::OnPresent();
  need(FrameSurvey::BindingWindow(),"bounded provider failure retry opens discovery window");
  StreamlineHooks::frame=41+2*attempt; c.frame(3); throwPrepare=true;
  const auto restores=D3D12Hooks::restores; StreamlineHooks::frame=42+2*attempt; c.frame(3); throwPrepare=false;
  need(D3D12Hooks::restores==restores+1 && D3D12Hooks::tracking && !NrdBridge::GetStatus().active,"provider exception restores title tracking and leaves inactive state");
 }
 for(UINT present=0;present<180;++present) NrdBridge::OnPresent();
 need(!FrameSurvey::BindingWindow() && NrdBridge::GetStatus().reason.find("3 bridge attempts")!=std::string::npos,"three repeated failures stop retries even when discovery succeeded between them");
 NrdBridge::SetRuntimeEnabled(false); NrdBridge::SetRuntimeEnabled(true);
 need(FrameSurvey::BindingWindow(),"explicit re-enable restarts an exhausted bounded retry budget");
 // Offset ordering and a root/heap reset are production resolver properties, independent of recorder service.
 FrameSurvey::SetBindingWindow(true); c.begin(); c.bind(1,0); c.bind(5,8); auto table=c.table(1);
 need(table.size()==8 && table[0].descriptorOffset==0 && table[3].descriptorOffset==3,"resolver preserves sorted offsets rather than resource-id order");
 need(table[0].resource==c.textures[0].Get() && table[3].resource==c.textures[3].Get(),"resolver returns real borrowed resources/view descriptions");
 NrdBridge::ChainDiscovery chain; std::string error; auto recon=c.table(5);
 need(chain.Begin(table,recon,error),"pure production chain accepts resolved Recon tables");
 c.bind(1,16); auto motion=c.table(1); need(!chain.Observe(Role::Temporal,motion,{},c.textures[0].Get(),error),"wrong SL motion tag fails validation");
 need(chain.Begin(table,recon,error),"chain can restart after validation failure");
 need(chain.Observe(Role::Temporal,motion,{},c.textures[6].Get(),error),"known motion validates");
 c.bind(5,32); auto output=c.table(5); need(chain.Observe(Role::ATrous,{},output,nullptr,error),"chain A outputs observed");
 need(chain.Observe(Role::PrePass,{},{},nullptr,error),"first post-ATrous PrePass seals chain A");
 c.bind(5,40); auto wrong=c.table(5); need(chain.Observe(Role::ATrous,{},wrong,nullptr,error),"chain B outputs cannot overwrite chain A identity");
 need(!chain.Observe(Role::Consumer,{},wrong,nullptr,error),"unreversed/mismatched Consumer pair fails closed");
 FrameSurvey::Reset(h.list.Get(),nullptr); std::vector<Bound> empty;
 need(!FrameSurvey::ResolveComputeTable(h.list.Get(),1,empty),"list Reset invalidates root/table/heap mirror");
 // Reuse notifications also erase stale roles when the object's Release vtable was not observed.
 FrameSurvey::PipelineCreated(c.pipelines[UINT(Role::Recon)].Get(),D3D12_GRAPHICS_PIPELINE_STATE_DESC {});
 need(!NrdBridge::gService->roles.contains(c.pipelines[UINT(Role::Recon)].Get()),"graphics creation erases an old role at reused PSO address");
 NrdBridge::RegisterPipelineRoleForTesting(c.pipelines[UINT(Role::Recon)].Get(),Role::Recon);
 FrameSurvey::PipelineCreated(c.pipelines[UINT(Role::Recon)].Get(),D3D12_PIPELINE_STATE_STREAM_DESC {});
 need(!NrdBridge::gService->roles.contains(c.pipelines[UINT(Role::Recon)].Get()),"failed/no-CS stream creation erases an old PSO role");
 auto timings=cpuTimings(c); FrameSurvey::SetBindingWindow(true); c.begin();
 FrameSurvey::Released(c.visible.Get());
 need(!FrameSurvey::ResolveComputeTable(h.list.Get(),1,empty),"descriptor heap release invalidates bindings");
 FrameSurvey::SetBindingWindow(false); need(!FrameSurvey::ResolveComputeTable(h.list.Get(),1,empty),"closed binding window resolves no cached stale copies");
 NrdBridge::Shutdown(); hr(h.list->Close()); h.execute(); h.reset(); h.errors();
 for(const auto& role:NrdBridge::ShaderRoles) {
  need(role.sha256.size()==64,"all roles use full SHA256"); need(NrdBridge::IdentifyRole(role.sha256)==role.role,"full shader digest identifies exact role");
  need(NrdBridge::IdentifyRole(role.sha256.substr(0,8))==Role::None,"hash prefixes never identify roles");
  std::string altered(role.sha256); altered.back()=altered.back()=='0' ? '1' : '0';
  need(NrdBridge::IdentifyRole(altered)==Role::None,"same prefix with different full hash never identifies a role");
 }
 return {{"cpu_callback_timings",timings},{"conversion_stub_calls",convertCalls},{"rr_stub_calls",rrCalls},{"debug_stub_calls",debugCalls},
  {"history_resets",{{"conversion",depthResets},{"rr",rrResets}}},{"restore_callback_calls",D3D12Hooks::restores}};
}
Bound manifestBinding(const J& row,const J& resource,UINT first) {
 Bound result; result.resource=reinterpret_cast<ID3D12Resource*>(uintptr_t(row["resource"].get<uint64_t>()));
 auto& d=result.description; d.Dimension=D3D12_RESOURCE_DIMENSION(resource["dimension"].get<UINT>());
 d.Width=resource["width"].get<uint64_t>(); d.Height=resource["height"].get<UINT>(); d.DepthOrArraySize=resource["array_size"].get<UINT16>();
 d.MipLevels=resource["mip_levels"].get<UINT16>(); d.SampleDesc.Count=resource["samples"].get<UINT>();
 d.Format=DXGI_FORMAT(resource["format"].get<UINT>()); d.Flags=D3D12_RESOURCE_FLAGS(resource["flags"].get<UINT>());
 result.viewFormat=DXGI_FORMAT(row["view_format"].get<UINT>()); result.kind=D3D12_DESCRIPTOR_RANGE_TYPE(row["kind"].get<UINT>());
 result.descriptorIndex=row["descriptor_index"].get<UINT>(); result.descriptorOffset=result.descriptorIndex-first;
 result.subresource=row["subresource"].get<UINT>(); return result;
}
J replayManifest(const char* path) {
 std::ifstream stream(path); auto manifest=J::parse(stream); std::unordered_map<uint64_t,J> resources;
 for(const auto& resource:manifest["resources"]) resources[resource["id"].get<uint64_t>()]=resource;
 ID3D12Resource* knownMotion=nullptr;
 for(const auto& tag:manifest["tags"]) if(tag.value("name","")=="MotionVectors" && tag.value("source","")=="current_Streamline_tag_call")
  knownMotion=reinterpret_cast<ID3D12Resource*>(uintptr_t(tag["resource"].get<uint64_t>()));
 J result=J::array();
 for(const auto& list:manifest["command_lists"]) {
  NrdBridge::ChainDiscovery chain; std::string error;
  for(const auto& pass:list["passes"]) {
   if(!pass.contains("pso")) continue;
   const auto role=NrdBridge::IdentifyRole(pass["pso"].value("shader_hashes",J::object()).value("CS",""));
   if(role==Role::None) continue;
   auto table=[&](const char* key,UINT parameter) {
    std::vector<Bound> views; UINT first=UINT_MAX;
    for(const auto& row:pass[key]) if(row.value("root_parameter",UINT_MAX)==parameter) first=std::min(first,row["descriptor_index"].get<UINT>());
    for(const auto& row:pass[key]) if(row.value("root_parameter",UINT_MAX)==parameter)
     views.push_back(manifestBinding(row,resources.at(row["resource"].get<uint64_t>()),first));
    std::sort(views.begin(),views.end(),[](const auto& a,const auto& b){return a.descriptorOffset<b.descriptorOffset;}); return views;
   };
   const auto srv=table("reads",1), uav=table("writes",5);
   if(role==Role::Recon) need(chain.Begin(srv,uav,error),error.c_str());
   else if(chain.Get().reconSpec) need(chain.Observe(role,srv,uav,knownMotion,error),error.c_str());
   if(chain.Complete()) {
    const auto& r=chain.Get(); auto id=[](auto* resource){return uint64_t(reinterpret_cast<uintptr_t>(resource));};
    result.push_back({{"list",list["id"]},{"chain_a_atrous",chain.ChainAIterations()},
     {"IN_SPEC",id(r.inputSpec)},{"IN_DIFF",id(r.inputDiff)},{"NR",id(r.normals)},{"VIEWZ",id(r.viewDepth)},
     {"RECON_SPEC",id(r.reconSpec)},{"RECON_DIFF",id(r.reconDiff)},{"MV",id(r.motion)},
     {"OUT_SPEC",id(r.outputSpec)},{"OUT_DIFF",id(r.outputDiff)},{"extent",{r.width,r.height}}});
    break;
   }
  }
 }
 need(!result.empty(),"capture produces a complete chain using production state machine"); return result;
}
int main(int argc,char** argv) try {
 if(argc==3 && std::string(argv[1])=="--replay") { std::cout<<replayManifest(argv[2]).dump()<<'\n'; return 0; }
 need(argc==2,"scratch directory argument"); g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";
 Host host; auto result=discoveryTests(host); result["checks_passed"]=checks; result["adapter"]=host.adapter;
 result["scope"]="real D3D12 registry, binding-window resolution and coordinator; conversion/RR/state-restore callback stubs";
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/12a-discovery/tests/discovery'))
    output.mkdir(parents=True, exist_ok=True)
    stubs = output / 'stubs'
    for folder in ('proxies', 'inputs', 'hooks'):
        (stubs / folder).mkdir(parents=True, exist_ok=True)
    (stubs / 'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#include <memory>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs / 'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } inline std::filesystem::path ExePath() { return L"cyberpunk2077.exe"; } }\n')
    (stubs / 'Config.h').write_text('#pragma once\ntemplate<class T> struct FixtureOptional { T value; T value_or_default() const { return value; } };\nstruct Config { FixtureOptional<bool> FfxDenoiserNrdBridge {false}, FfxDenoiserNrdBridgeEnabled {true}; static Config* Instance() { static Config config; return &config; } };\n')
    (stubs / 'hooks/D3D12_Hooks.h').write_text('#pragma once\nstruct D3D12Hooks { inline static bool tracking=true, canRestore=true; inline static unsigned restores=0; static void SetRootSignatureTracking(bool enabled) { tracking=enabled; } static bool CanRestoreRootSignature(ID3D12GraphicsCommandList*) { return canRestore; } static void RestoreRoot(ID3D12GraphicsCommandList*) { ++restores; } };\n')
    (stubs / 'hooks/Streamline_Hooks.h').write_text('#pragma once\n#include <sl_consts.h>\nstruct SLConstantsSnapshot { sl::Constants constants {}; uint32_t frameIndex=UINT32_MAX, viewport=UINT32_MAX; };\nstruct StreamlineHooks { inline static uint32_t frame=0; static SLConstantsSnapshot getSLConstantsSnapshot() { SLConstantsSnapshot result; result.frameIndex=frame; return result; } };\n')
    (stubs / 'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs / 'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    host = survey_fixture.CPP.split('// GetStatus()')[0]
    source_text = (host + CPP).replace('__TRACE__', (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__', (ROOT / 'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix()).replace('__COORDINATOR__', (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp').as_posix())
    source = output / 'fixture.cpp'
    source.write_text(source_text, encoding='utf-8')
    executable = output / 'fixture.exe'
    detours = ROOT / 'OptiScaler/library/detours/detours.lib'
    compile_cpp(source, executable, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib', str(detours)),
                (stubs, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann', ROOT / 'external/nvngx_dlss_sdk', ROOT / 'external/streamline', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(executable), str(output)], check=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result = json.loads((output / 'host-result.json').read_text())
    captures = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/FRAME_SURVEY')
    expected = {
        'bb22daa989a8e892ee4470e3cd9a8a14': [62025, 62023, 62162, 62029, 62049, 62051, 61997, 62026, 62024, 6],
        'da9f46edb00fd2144b531c8c0b6fc6a2': [44284, 44282, 3749, 44287, 44308, 44310, 44135, 44285, 44283, 3],
    }
    names = ['IN_SPEC', 'IN_DIFF', 'NR', 'VIEWZ', 'RECON_SPEC', 'RECON_DIFF', 'MV', 'OUT_SPEC', 'OUT_DIFF', 'chain_a_atrous']
    result['offline_replay'] = {}
    for capture, ids in expected.items():
        rows = json.loads(subprocess.check_output([str(executable), '--replay', str(captures / capture / 'capture.json')], text=True))
        assert [rows[0][name] for name in names] == ids, (capture, rows)
        assert rows[0]['extent'] == [1505, 847]
        result['offline_replay'][capture] = rows
    result['python_checks_passed'] = 4
    (output / 'host-result.json').write_text(json.dumps(result, indent=2) + '\n')
    report = Path('E:/FSRD/sol_batch/12a-discovery')
    report.mkdir(parents=True, exist_ok=True)
    (report / 'host-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'checks_passed': result['checks_passed'], 'python_checks_passed': 4, 'result': str(output / 'host-result.json')}))


if __name__ == '__main__':
    run()
