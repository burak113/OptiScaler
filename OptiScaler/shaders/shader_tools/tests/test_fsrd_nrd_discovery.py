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
unsigned convertCalls=0, motionCalls=0, rrCalls=0, debugCalls=0, depthResets=0, rrResets=0, rrDiscards=0;
bool internalObserved=true, trackingSuppressed=true, observerUnlocked=true, throwPrepare=false, deferredMotion=true;
void (*afterRRForTesting)() = nullptr;
NrdBridge::ConversionInputs lastReconInputs {};
NrdBridge::FrameParameters lastRGBFrame {},lastMotionFrame {},lastRRFrame {};
ID3D12Resource* lastMotion=nullptr; ID3D12Resource* lastOutSpec=nullptr; ID3D12Resource* lastOutDiff=nullptr;
namespace NrdBridge {
struct ConversionPass::Impl {};
ConversionPass::ConversionPass()=default; ConversionPass::~ConversionPass()=default;
bool ConversionPass::Initialize(ID3D12Device*,uint32_t,uint32_t,std::string&) { return true; }
bool ConversionPass::Dispatch(ID3D12GraphicsCommandList* cmd,const ConversionInputs& inputs,const FrameParameters& frame,
                             ConvertedResources& out,std::string&) {
 ++convertCalls; lastReconInputs=inputs; lastRGBFrame=frame; deferredMotion &= !inputs.motion;
 internalObserved &= FrameSurvey::Internal(); trackingSuppressed &= !D3D12Hooks::tracking;
 // Internal callbacks must not alter either mirror or the live title role.
 FrameSurvey::RootBinding(cmd,false,nullptr); OnSetPipeline(cmd,nullptr); out.width=64; out.height=32; return true;
}
__MOTION_STUB__
bool ConversionPass::WriteDebug(ID3D12GraphicsCommandList*,const ConvertedResources&,ID3D12Resource*,
                               ID3D12Resource*,DebugMode,std::string&,const OutputCommitGuard& guard,SignalEncoding,const TitleSignalConstants&) {
 ++debugCalls; return !guard.admit || guard.admit(guard.state,+[](void*) noexcept {},nullptr); }
void ConversionPass::ResetHistory() noexcept { ++depthResets; }
uint64_t ConversionPass::OwnedTextureBytes() const noexcept { return 0; }
struct RRWrapper::Impl {};
RRWrapper::RRWrapper()=default; RRWrapper::~RRWrapper()=default;
bool RRWrapper::PrepareFrame(const SLConstantsSnapshot& sl,bool reset,FrameParameters& out,std::string&) {
 if(throwPrepare) throw std::runtime_error("fixture provider exception");
 out.streamlineFrame=sl.frameIndex; out.frameIndex=rrCalls; out.reset=reset; return true;
}
bool RRWrapper::Dispatch(ID3D12GraphicsCommandList*,const ConvertedResources&,ID3D12Resource* outputSpec,ID3D12Resource* outputDiff,
                        const FrameParameters& frame,std::string&,const OutputCommitGuard& guard) {
 ++rrCalls; lastOutSpec=outputSpec; lastOutDiff=outputDiff; lastRRFrame=frame;
 internalObserved &= FrameSurvey::Internal(); trackingSuppressed &= !D3D12Hooks::tracking;
 if(afterRRForTesting) afterRRForTesting();
 return !guard.admit || guard.admit(guard.state,+[](void*) noexcept {},nullptr);
}
void RRWrapper::ResetHistory() noexcept { ++rrResets; }
void RRWrapper::DiscardRecordingHistory() noexcept { ++rrDiscards; }
uint64_t RRWrapper::ContextGeneration() const noexcept { return 0; }
__CAMERA_STUB__
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
std::atomic<bool> conversionStaged {false};
void conversionLockProbe() { conversionStaged.store(true,std::memory_order_release); }
thread_local bool delayWindowPublisher=false;
std::atomic<bool> windowPublisherPaused {false},resumeWindowPublisher {false};
void windowPublicationProbe() { if(delayWindowPublisher) { windowPublisherPaused.store(true,std::memory_order_release); while(!resumeWindowPublisher.load(std::memory_order_acquire)) std::this_thread::yield(); } }
using Bound=FrameSurvey::BoundResource;
using Role=NrdBridge::Role;
struct ChainHost {
 Host& h; ComPtr<ID3D12RootSignature> root;
 std::array<ComPtr<ID3D12PipelineState>,11> pipelines;
 ComPtr<ID3D12DescriptorHeap> staging, visible;
 ComPtr<ID3D12Resource> consumerConstants;
 std::array<ComPtr<ID3D12Resource>,13> textures;
 UINT increment=0;
 D3D12_CPU_DESCRIPTOR_HANDLE cpu {}; D3D12_GPU_DESCRIPTOR_HANDLE gpu {};
 explicit ChainHost(Host& host):h(host) {
  FrameSurvey::BeginCreationTracking(false);
  need(FrameSurvey::Install(h.dev.Get(),h.list.Get(),false),"metadata-only hooks install");
  need(!FrameSurvey::Enabled() && !FrameSurvey::GetStatus().installed,"metadata hooks do not enable survey recorder");
  Config::Instance()->FfxDenoiserNrdBridge.value=false;
  need(!NrdBridge::Initialize(h.dev.Get()),"startup disabled creates no service");
  NrdBridge::OnReset(h.list.Get(),nullptr); NrdBridge::SetRuntimeEnabled(true);
  need(!Config::Instance()->RestoreComputeSignature.value && !Config::Instance()->ExtendedStateRestore.value,"startup OFF leaves existing restore preferences unchanged");
  Config::Instance()->FfxDenoiserNrdBridge.value=true;
  NrdBridge::ConfigureStartup(true);
  need(NrdBridge::Initialize(h.dev.Get()),"bridge coordinator initializes");
  need(NrdBridge::Initialize(h.dev.Get()),"same-device initialization is idempotent");
  FrameSurvey::SetPipelineObserver(pipelineObserved); FrameSurvey::SetReleaseObserver(releaseObserved);
  D3D12_DESCRIPTOR_RANGE ranges[2]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5,0,0,0}};
  D3D12_ROOT_PARAMETER params[6] {};
  for(UINT i=0;i<6;++i) { params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; params[i].Constants={i,0,1}; }
  params[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; params[1].DescriptorTable={1,&ranges[0]};
  params[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; params[5].DescriptorTable={1,&ranges[1]};
  params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV; params[2].Descriptor={6,0};
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
  auto cbDesc=CD3DX12_RESOURCE_DESC::Buffer(1536); D3D12_HEAP_PROPERTIES cbHeap {}; cbHeap.Type=D3D12_HEAP_TYPE_UPLOAD;
  hr(h.dev->CreateCommittedResource(&cbHeap,D3D12_HEAP_FLAG_NONE,&cbDesc,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&consumerConstants)));
  FrameSurvey::ResourceCreated(consumerConstants.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
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
 void copy() {
  auto dst=visible->GetCPUDescriptorHandleForHeapStart(); UINT n=64;
  h.dev->CopyDescriptors(1,&dst,&n,1,&cpu,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  FrameSurvey::CopyDescriptors(h.dev.Get(),1,&dst,&n,1,&cpu,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 }
 void begin(bool copyDescriptors=true) {
  FrameSurvey::Reset(h.list.Get(),nullptr); NrdBridge::OnReset(h.list.Get(),nullptr); ResTrack_Dx12::ResetForTesting(h.list.Get());
  D3D12Hooks::current = {}; D3D12Hooks::current.root=root.Get(); D3D12Hooks::current.heaps={visible.Get()};
  h.list->SetComputeRootSignature(root.Get()); FrameSurvey::RootBinding(h.list.Get(),false,root.Get());
  ID3D12DescriptorHeap* heap=visible.Get(); h.list->SetDescriptorHeaps(1,&heap); FrameSurvey::DescriptorHeaps(h.list.Get(),1,&heap);
  for(UINT i : {0u,3u,4u}) h.list->SetComputeRoot32BitConstant(i,0,0);
  const auto cb=consumerConstants->GetGPUVirtualAddress(); h.list->SetComputeRootConstantBufferView(2,cb);
  FrameSurvey::RootView(h.list.Get(),false,2,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,cb);
  D3D12Hooks::current.views={{2,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,cb}};
  if(copyDescriptors) copy();
 }
 void bind(UINT parameter,UINT index) {
  D3D12_GPU_DESCRIPTOR_HANDLE handle {gpu.ptr+uint64_t(index)*increment};
  h.list->SetComputeRootDescriptorTable(parameter,handle); FrameSurvey::Table(h.list.Get(),false,parameter,handle);
  auto& tables=D3D12Hooks::current.tables; auto entry=std::find_if(tables.begin(),tables.end(),[&](const auto& value){return value.first==parameter;});
  if(entry==tables.end()) tables.emplace_back(parameter,handle); else entry->second=handle;
 }
 void pass(Role role,UINT uav=8) {
  h.list->SetPipelineState(pipelines[UINT(role)].Get()); FrameSurvey::SetPipeline(h.list.Get(),pipelines[UINT(role)].Get());
  NrdBridge::OnSetPipeline(h.list.Get(),pipelines[UINT(role)].Get());
  bind(1,role==Role::Temporal ? 16 : 0); bind(5,uav);
  NrdBridge::BeforeDispatch(h.list.Get()); h.list->Dispatch(1,1,1); NrdBridge::AfterDispatch(h.list.Get());
 }
 void incompleteRecon() {
  h.list->SetPipelineState(pipelines[UINT(Role::Recon)].Get()); FrameSurvey::SetPipeline(h.list.Get(),pipelines[UINT(Role::Recon)].Get());
  NrdBridge::OnSetPipeline(h.list.Get(),pipelines[UINT(Role::Recon)].Get());
  bind(1,120); bind(5,8); // Eight legal heap slots with intentionally unknown descriptor metadata.
  NrdBridge::BeforeDispatch(h.list.Get()); h.list->Dispatch(1,1,1); NrdBridge::AfterDispatch(h.list.Get());
 }
 void postTemporal(UINT count,UINT bcount=2) {
  pass(Role::Chain3); pass(Role::HistSave); pass(Role::HistFix); pass(Role::Clamp);
  for(UINT i=0;i<count;++i) pass(Role::ATrous,i+1==count ? 32 : 24);
  pass(Role::PrePass); pass(Role::Temporal); pass(Role::Clamp);
  for(UINT i=0;i<bcount;++i) pass(Role::ATrous,40);
  pass(Role::Consumer,48);
 }
 void frame(UINT count,UINT bcount=2,bool copyDescriptors=true) {
  begin(copyDescriptors); pass(Role::PrepLast); pass(Role::Recon); pass(Role::PrePass); pass(Role::Temporal); postTemporal(count,bcount);
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
 timings.push_back(measure("closed binding window: CopyDescriptors callback one descriptor",200000,[&]{FrameSurvey::CopyDescriptors(c.h.dev.Get(),1,&dest,&n,1,&c.cpu,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);}));
 UINT batchDescriptors=64;
 timings.push_back(measure("closed binding window: CopyDescriptors callback 64 descriptors",10000,[&]{FrameSurvey::CopyDescriptors(c.h.dev.Get(),1,&dest,&batchDescriptors,1,&c.cpu,&batchDescriptors,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);}));
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
J descriptorMetadataTests(ChainHost& c) {
 FrameSurvey::SetBindingWindow(false);
 auto oldResource=c.h.texture(64,32,srv), newResource=c.h.texture(64,32,srv);
 D3D12_SHADER_RESOURCE_VIEW_DESC view {}; view.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
 view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D; view.Texture2D.MipLevels=1; view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
 const auto source=D3D12_CPU_DESCRIPTOR_HANDLE {c.cpu.ptr+64ull*c.increment};
 c.h.dev->CreateShaderResourceView(oldResource.Get(),&view,source); FrameSurvey::View(oldResource.Get(),source,&view);
 const auto destinationCpu=D3D12_CPU_DESCRIPTOR_HANDLE {c.cpu.ptr+65ull*c.increment};
 const auto chainedCpu=D3D12_CPU_DESCRIPTOR_HANDLE {c.cpu.ptr+66ull*c.increment};
 const auto originalNew=D3D12_CPU_DESCRIPTOR_HANDLE {c.cpu.ptr+67ull*c.increment};
 c.h.dev->CreateShaderResourceView(newResource.Get(),&view,originalNew); FrameSurvey::View(newResource.Get(),originalNew,&view);
 const auto destinationGpu=D3D12_CPU_DESCRIPTOR_HANDLE {c.visible->GetCPUDescriptorHandleForHeapStart().ptr+64ull*c.increment};
 auto copy=[&](D3D12_CPU_DESCRIPTOR_HANDLE destination,D3D12_CPU_DESCRIPTOR_HANDLE source) {
  UINT n=1; c.h.dev->CopyDescriptors(1,&destination,&n,1,&source,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  FrameSurvey::CopyDescriptors(c.h.dev.Get(),1,&destination,&n,1,&source,&n,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 };
 copy(destinationCpu,source); copy(source,originalNew); copy(chainedCpu,source); copy(destinationGpu,chainedCpu);
 FrameSurvey::SetBindingWindow(true);
 FrameSurvey::ComputeBindings seed {c.root.Get(),{c.visible.Get()},{{1,{c.gpu.ptr+64ull*c.increment}}}};
 need(FrameSurvey::SeedComputeBindings(c.h.list.Get(),seed),"borrowed compute state seeds reopened mirror");
 auto table=c.table(1); need(table.size()==1 && table[0].resource==newResource.Get(),"closed-window CPU chain and direct CPU overwrite resolve current copied resource");
 FrameSurvey::Released(oldResource.Get()); table=c.table(1);
 need(table.size()==1 && table[0].resource==newResource.Get(),"release of overwritten old resource does not erase new descriptor ownership");
 FrameSurvey::SetBindingWindow(false); FrameSurvey::SetBindingWindow(true); need(FrameSurvey::SeedComputeBindings(c.h.list.Get(),seed),"persistent table seeds a second window");
 table=c.table(1); need(table.size()==1 && table[0].resource==newResource.Get(),"persistent shader-visible table survives window edges without recopy");
 FrameSurvey::SetBindingWindow(false);
 c.h.dev->CreateShaderResourceView(oldResource.Get(),&view,destinationGpu); FrameSurvey::View(oldResource.Get(),destinationGpu,&view);
 copy(destinationGpu,originalNew); // Direct shader-visible view is overwritten while bindings are closed.
 FrameSurvey::SetBindingWindow(true); need(FrameSurvey::SeedComputeBindings(c.h.list.Get(),seed),"direct-visible overwrite window seeded");
 table=c.table(1); need(table.size()==1 && table[0].resource==newResource.Get(),"closed visible copy replaces old direct-visible metadata exactly");
 FrameSurvey::SetBindingWindow(false); D3D12_CPU_DESCRIPTOR_HANDLE unknown {c.cpu.ptr+68ull*c.increment};
 c.h.dev->CreateShaderResourceView(nullptr,&view,unknown); FrameSurvey::View(nullptr,unknown,&view); copy(destinationGpu,unknown);
 FrameSurvey::SetBindingWindow(true); need(FrameSurvey::SeedComputeBindings(c.h.list.Get(),seed),"unknown-source tombstone window seeded");
 table=c.table(1); need(table.empty(),"unknown/null source tombstones overwritten visible destination");
 copy(destinationGpu,originalNew); FrameSurvey::Released(newResource.Get()); table=c.table(1);
 need(table.empty(),"release of current copied resource invalidates every owned descriptor handle");
 FrameSurvey::SetBindingWindow(false); return {{"cpu_chains",true},{"persistent_visible_tables",true},{"unknown_source_tombstones",true}};
}
J discoveryTests(Host& h) {
 ChainHost c(h); need(FrameSurvey::BindingWindow(),"initial binding window opens before title recording");
 // Loading can take thousands of Presents before the title dispatches any NRD shader.
 for(UINT i=0;i<400;++i) NrdBridge::OnPresent();
 need(!FrameSurvey::BindingWindow() && NrdBridge::GetStatus().phase=="Waiting for NRD" && NrdBridge::gService->attempts==0 && NrdBridge::gService->failures==0,
  "empty startup/loading windows do not consume discovery or provider failure budgets");
 // Record root/heaps while the window is closed; waking in the middle of a list must wait for its next full Reset.
 c.begin(); D3D12Hooks::current={}; c.pass(Role::PrepLast); need(FrameSurvey::BindingWindow(),"PrepLast activity wakes a bounded window after loading");
 c.pass(Role::Recon);
 need(FrameSurvey::BindingWindow() && !NrdBridge::gService->cache.Valid() && NrdBridge::gService->failures==0,
  "missing initial root/heap mirror keeps fail-closed discovery open for the next Reset");
 const ULONG refs=c.textures[7]->AddRef(); c.textures[7]->Release();
 c.frame(3,5); auto status=NrdBridge::GetStatus();
 need(status.width==64 && status.height==32 && !status.resources.empty(),"first full chain caches render extent/resources");
 need(convertCalls==0 && rrCalls==0,"discovery frame injects nothing before full cache is known");
 need(!FrameSurvey::BindingWindow(),"stable discovery closes the short binding mirror window");
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
 need(D3D12Hooks::restores==3 && motionCalls==1,"state restore invoked after RGB, current motion and RR injections");
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
 // Releasing a cached game output while conversion waits for lifecycle serialization must cancel all work.
 c.begin(); h.list->SetPipelineState(c.pipelines[UINT(Role::Recon)].Get());
 NrdBridge::OnSetPipeline(h.list.Get(),c.pipelines[UINT(Role::Recon)].Get()); c.bind(1,0); c.bind(5,8); h.list->Dispatch(1,1,1);
 const auto beforeReleaseRace=convertCalls; NrdBridge::gBeforeConversionLockForTesting=conversionLockProbe;
 std::unique_lock serial(NrdBridge::gInjectionMutex);
 std::thread pendingConversion([&]{NrdBridge::AfterDispatch(h.list.Get());});
 await([]{return conversionStaged.load(std::memory_order_acquire);},"conversion reaches lifecycle mutex with staged cache");
 FrameSurvey::Released(c.textures[8].Get()); serial.unlock(); pendingConversion.join(); NrdBridge::gBeforeConversionLockForTesting=nullptr;
 need(convertCalls==beforeReleaseRace && !NrdBridge::gService->cache.Valid(),"release during conversion mutex wait cancels stale conversion without GPU work");
 FrameSurvey::ResourceCreated(c.textures[8].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS); c.views(48,{8,7,9,10,9},true); c.views(32,{7,8,9,10,9},true);
 c.frame(3); need(NrdBridge::gService->cache.Valid(),"race cancellation permits clean rediscovery");
 // Missing restoration and provider exceptions fail closed; successful rediscovery cannot hide repeated failures.
 const auto beforeFailedConversion=convertCalls; D3D12Hooks::canRestore=false;
 StreamlineHooks::frame=40; c.frame(3);
 need(convertCalls==beforeFailedConversion && !NrdBridge::GetStatus().active && !NrdBridge::gService->cache.Valid(),"missing state restore prevents conversion and invalidates discovery");
 D3D12Hooks::canRestore=true;
 const auto cooldownFailure=NrdBridge::gService->failures,cooldownConversion=convertCalls;
 for(UINT cooldownFrame=0;cooldownFrame<5;++cooldownFrame) c.frame(3);
 need(NrdBridge::gService->failures==cooldownFailure && convertCalls==cooldownConversion && !FrameSurvey::BindingWindow(),"ordinary NRD frames during retry cooldown consume no additional failures or conversion work");
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
 c.frame(3); c.frame(3); need(NrdBridge::GetStatus().active,"explicit re-enable restores active current-frame validation");
 // SL null untag is authoritative: the fresh first-Temporal table remains usable when the tag is unknown.
 NrdBridge::OnTitleTag(h.list.Get(),"MotionVectors",nullptr);
 need(!NrdBridge::gService->taggedMotion,"SL null motion untag clears the previously known tag");
 const auto untagRR=rrCalls; c.frame(3);
 need(rrCalls==untagRR+1 && NrdBridge::GetStatus().active,"unknown motion tag permits validated current Temporal binding");
 // Exact metadata copied before Reset or persistently reused without recopy must survive the closed window.
 need(!FrameSurvey::BindingWindow(),"active Consumer closes its frame-local validation window");
 c.copy(); const auto persistentRR=rrCalls; c.frame(3,2,false);
 need(rrCalls==persistentRR+1 && NrdBridge::GetStatus().active,"visible metadata copied before Reset reaches valid Active Consumer");
 c.frame(3,2,false);
 need(rrCalls==persistentRR+2 && NrdBridge::GetStatus().active,"persistent visible tables remain valid without any descriptor recopy");
 // Alive, typed Recon guides are per-recording inputs; their rotation must not starve a stable signal profile.
 const auto savedNormals=c.textures[2],savedDepth=c.textures[3];
 auto guide=[&](ID3D12Resource* original) {
  const auto desc=original->GetDesc();D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
  ComPtr<ID3D12Resource> value;hr(h.dev->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&value)));
  FrameSurvey::ResourceCreated(value.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);return value;
 };
 const auto alternateNormals=guide(savedNormals.Get()),alternateDepth=guide(savedDepth.Get());
 ResTrack_Dx12::SubmitForTesting(h.list.Get());
 const auto guideGeneration=NrdBridge::gService->cache.Generation(),guideCancellation=NrdBridge::gService->cancellationSerial;
 const auto guideConversions=convertCalls,guideRR=rrCalls;
 for(UINT i=0;i<6;++i) {
  c.textures[2]=i%2?savedNormals:alternateNormals;c.textures[3]=i%2?savedDepth:alternateDepth;
  c.views(0,{0,1,2,3,0,1,2,3},false);c.frame(3);
  need(convertCalls==guideConversions+i+1&&rrCalls==guideRR+i+1&&NrdBridge::GetStatus().active,"every alternating Recon guide frame converts and reaches Active exactly once");
  need(lastReconInputs.normals==c.textures[2].Get()&&lastReconInputs.viewDepth==c.textures[3].Get(),"conversion receives the current recording's exact normal/depth pointers, not previous cached guides");
  need(NrdBridge::gService->cache.Generation()==guideGeneration&&NrdBridge::gService->cancellationSerial==guideCancellation&&!lastRRFrame.reset,"alive typed guide rotation preserves stable profile generation and submitted temporal history");
  need(NrdBridge::gService->cache.Get().normals==c.textures[2].Get()&&NrdBridge::gService->cache.Get().viewDepth==c.textures[3].Get(),"latest diagnostics refresh current guides without republishing the stable lighting profile");
  ResTrack_Dx12::SubmitForTesting(h.list.Get());
 }
 // The newly bound depth differs from the last Consumer cache. Retire it while Convert waits for injection.
 c.textures[3]=alternateDepth;c.views(0,{0,1,2,3,0,1,2,3},false);c.begin();
 h.list->SetPipelineState(c.pipelines[UINT(Role::Recon)].Get());NrdBridge::OnSetPipeline(h.list.Get(),c.pipelines[UINT(Role::Recon)].Get());c.bind(1,0);c.bind(5,8);h.list->Dispatch(1,1,1);
 conversionStaged.store(false);NrdBridge::gBeforeConversionLockForTesting=conversionLockProbe;
 const auto beforeCurrentRelease=convertCalls;const auto currentReleaseEpoch=NrdBridge::gService->cancellationSerial;
 std::unique_lock guideSerial(NrdBridge::gInjectionMutex);std::thread pendingGuide([&]{NrdBridge::AfterDispatch(h.list.Get());});
 await([]{return conversionStaged.load(std::memory_order_acquire);},"current-guide conversion reaches its lifecycle wait");
 need(NrdBridge::gService->cache.Get().viewDepth==savedDepth.Get()&&NrdBridge::gService->lists.at(h.list.Get()).chain.Get().viewDepth==alternateDepth.Get(),"released pending guide is demonstrably absent from the last published cache");
 FrameSurvey::Released(alternateDepth.Get());guideSerial.unlock();pendingGuide.join();NrdBridge::gBeforeConversionLockForTesting=nullptr;
 need(convertCalls==beforeCurrentRelease&&!NrdBridge::gService->cache.Valid()&&NrdBridge::gService->cancellationSerial>currentReleaseEpoch,"release of a current uncached guide cancels conversion before native/source access and invalidates the epoch");
 FrameSurvey::ResourceCreated(alternateDepth.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
 c.textures[2]=savedNormals;c.textures[3]=savedDepth;c.views(0,{0,1,2,3,0,1,2,3},false);c.frame(3);c.frame(3);
 need(NrdBridge::GetStatus().active,"current-guide release permits complete profile rediscovery and safe recovery");
 ResTrack_Dx12::SubmitForTesting(h.list.Get());
 // Keep all old resources alive while changing bindings: old pointers must never authorize output writes.
 c.views(8,{5,4,9,0,2},true); const auto reconConversion=convertCalls,reconRR=rrCalls; c.frame(3);
 need(convertCalls==reconConversion && rrCalls==reconRR && !NrdBridge::GetStatus().active,"alive Recon resource swap cancels conversion and RR before current cache publication");
 c.frame(3);
 need(rrCalls==reconRR+1 && lastReconInputs.reconSpec==c.textures[5].Get() && lastReconInputs.reconDiff==c.textures[4].Get(),"next Recon converts newly validated current specular/diffuse bindings");
 c.views(8,{4,5,9,0,2},true); c.frame(3); c.frame(3);
 c.views(16,{9,10,11,2,3,0,1,2},false); const auto motionConversion=convertCalls,motionBefore=motionCalls,motionRR=rrCalls; c.frame(3);
 need(convertCalls==motionConversion+1 && motionCalls==motionBefore && rrCalls==motionRR && deferredMotion,"alive MV swap never reads the old MV during Recon or finalizes stale motion");
 c.frame(3);
 need(motionCalls==motionBefore+1 && lastMotion==c.textures[11].Get() && rrCalls==motionRR+1,"first Temporal finalizes only the newly validated current MV");
 c.views(16,{9,10,6,2,3,0,1,2},false); c.frame(3); c.frame(3);
 c.views(32,{8,7,9,10,9},true); c.views(48,{7,8,9,10,9},true); const auto outputRR=rrCalls; c.frame(3);
 need(rrCalls==outputRR && !NrdBridge::GetStatus().active,"alive Consumer output swap cancels writes and resets staged history");
 c.frame(3);
 need(rrCalls==outputRR+1 && lastOutSpec==c.textures[8].Get() && lastOutDiff==c.textures[7].Get(),"validated current Consumer receives the newly bound output pair");
 c.views(32,{7,8,9,10,9},true); c.views(48,{8,7,9,10,9},true); c.frame(3); c.frame(3);
 // A second SL snapshot must not replace the immutable camera prepared at this frame's first injection.
 StreamlineHooks::frame=100; c.begin(); c.pass(Role::PrepLast); c.pass(Role::Recon); StreamlineHooks::frame=101;
 c.pass(Role::PrePass); c.pass(Role::Temporal); c.postTemporal(3);
 need(lastRGBFrame.streamlineFrame==100 && lastMotionFrame.streamlineFrame==100 && lastRRFrame.streamlineFrame==100,"RGB, motion and RR share the same immutable prepared SL camera frame");
 // The retained submission token outlives successful Consumer's converted=false state.
 auto recorded=NrdBridge::gService->lists.at(h.list.Get()).recording; const auto discardSerial=NrdBridge::gService->resetSerial;
 need(recorded && !recorded->submitted.load() && !NrdBridge::gService->lists.at(h.list.Get()).converted,"successful Consumer retains an unsubmitted recording token");
 NrdBridge::OnReset(h.list.Get(),nullptr);
 need(NrdBridge::gService->resetSerial>discardSerial && NrdBridge::gService->discardRequested,"Reset of a successful recorded-but-unsubmitted Consumer drops temporal history and requests fresh private RR context");
 const auto resetDiscards=rrDiscards; c.frame(3);
 need(rrDiscards==resetDiscards+1 && !NrdBridge::gService->discardRequested,"next Convert consumes discarded recording by retiring private RR history inside injection scope");
 recorded=NrdBridge::gService->lists.at(h.list.Get()).recording; ResTrack_Dx12::SubmitForTesting(h.list.Get());
 const auto submittedSerial=NrdBridge::gService->resetSerial; const auto submittedDepth=depthResets,submittedRR=rrResets,submittedDiscards=rrDiscards;
 need(recorded && recorded->submitted.load(),"retained beforeSubmit callback marks the recording token submitted");
 NrdBridge::OnReset(h.list.Get(),nullptr); c.frame(3);
 need(NrdBridge::gService->resetSerial==submittedSerial && depthResets==submittedDepth && rrResets==submittedRR && rrDiscards==submittedDiscards,"Reset after normal submission preserves temporal history and the private RR context");
 ResTrack_Dx12::SubmitForTesting(h.list.Get()); const auto toggleDiscards=rrDiscards,toggleResets=rrResets;
 NrdBridge::SetRuntimeEnabled(false); NrdBridge::SetRuntimeEnabled(true); c.frame(3);
 need(rrDiscards==toggleDiscards && rrResets>toggleResets,"ordinary runtime A/B resets valid submitted history without discarding private RR context");
 // A new chain on the same open list must not hide successful but unsubmitted provider work.
 auto overlapRecording=NrdBridge::gService->lists.at(h.list.Get()).recording; const auto overlapResetDiscards=rrDiscards;
 c.incompleteRecon();
 need(NrdBridge::gService->lists.at(h.list.Get()).recording==overlapRecording && !overlapRecording->submitted.load() && !NrdBridge::gService->cache.Valid(),"second incomplete Recon preserves the first successful Consumer submission token");
 NrdBridge::OnReset(h.list.Get(),nullptr); c.frame(3); c.frame(3);
 need(rrDiscards==overlapResetDiscards+1 && !NrdBridge::gService->discardRequested,"Reset after an incomplete second Recon discards prior unsubmitted private RR context exactly once");
 overlapRecording=NrdBridge::gService->lists.at(h.list.Get()).recording; const auto overlapReleaseDiscards=rrDiscards;
 c.incompleteRecon();
 need(NrdBridge::gService->lists.at(h.list.Get()).recording==overlapRecording && !overlapRecording->submitted.load(),"second incomplete Recon retains prior recording through its binding failure for Release");
 FrameSurvey::Released(h.list.Get()); c.frame(3); c.frame(3);
 need(rrDiscards==overlapReleaseDiscards+1 && !NrdBridge::gService->discardRequested,"Release after an incomplete second Recon discards prior unsubmitted private RR context exactly once");
 const auto releaseSerial=NrdBridge::gService->resetSerial; const auto releaseDiscards=rrDiscards; FrameSurvey::Released(h.list.Get());
 need(NrdBridge::gService->resetSerial>releaseSerial && !NrdBridge::gService->lists.contains(h.list.Get()),"list Release discards an unsubmitted successful Consumer even after converted is cleared");
 c.frame(3); need(rrDiscards==releaseDiscards+1 && !NrdBridge::gService->discardRequested,"list Release consumes unsubmitted RR context discard on the next Convert");
 const auto retainConversion=convertCalls,retainMotion=motionCalls,retainRR=rrCalls;
 ResTrack_Dx12::retentionAvailable=false; c.frame(3); ResTrack_Dx12::retentionAvailable=true;
 need(convertCalls==retainConversion && motionCalls==retainMotion && rrCalls==retainRR && !NrdBridge::GetStatus().active && NrdBridge::GetStatus().reason.find("submission token")!=std::string::npos,"submission-token retention failure stops all conversion/motion/output writes");
 NrdBridge::SetRuntimeEnabled(false); NrdBridge::SetRuntimeEnabled(true); c.frame(3); c.frame(3);
 need(NrdBridge::GetStatus().active,"retention failure permits explicit runtime reset and clean rediscovery");
 auto* config=Config::Instance(); config->RestoreComputeSignature.value=false; config->ExtendedStateRestore.value=false;
 NrdBridge::OnReset(h.list.Get(),nullptr);
 need(config->RestoreComputeSignature.value && config->ExtendedStateRestore.value && config->RestoreComputeSignature.volatileValue && config->ExtendedStateRestore.volatileValue,"active Reset restores both volatile state tracking flags after INI reload");
 NrdBridge::SetRuntimeEnabled(false); config->RestoreComputeSignature.value=false; config->ExtendedStateRestore.value=false;
 const auto offRestoreWrites=config->RestoreComputeSignature.volatileWrites; NrdBridge::OnReset(h.list.Get(),nullptr);
 need(!config->RestoreComputeSignature.value && !config->ExtendedStateRestore.value && config->RestoreComputeSignature.volatileWrites==offRestoreWrites,"runtime-off Reset preserves reloaded restore preferences");
 NrdBridge::SetRuntimeEnabled(true);
 need(config->RestoreComputeSignature.value && config->ExtendedStateRestore.value,"runtime enable restores required tracking flags");
 config->RestoreComputeSignature.value=false; config->ExtendedStateRestore.value=false; NrdBridge::SetRuntimeEnabled(true);
 need(config->RestoreComputeSignature.value && config->ExtendedStateRestore.value,"idempotent runtime enable restores flags cleared by later reload");
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
 NrdBridge::RegisterPipelineRoleForTesting(c.pipelines[UINT(Role::Recon)].Get(),Role::Recon);
 // The provider can succeed after the coordinator epoch changed on another path.
 // Admission must preserve the newer state and avoid an Active/counter publication.
 NrdBridge::SetRuntimeEnabled(false); NrdBridge::SetRuntimeEnabled(true); c.frame(3); c.frame(3);
 need(NrdBridge::GetStatus().active,"output admission fixture starts from a valid active chain");
 const auto beforeCancelledReset=NrdBridge::GetStatus().framesBridged;
 const auto beforeResetFailures=NrdBridge::gService->failures; const auto beforeResetEpoch=NrdBridge::gService->resetSerial;
 afterRRForTesting=+[] { NrdBridge::RequestHistoryReset(); }; c.frame(3); afterRRForTesting=nullptr;
 need(NrdBridge::GetStatus().framesBridged==beforeCancelledReset && !NrdBridge::GetStatus().active,
  "provider success after an explicit history reset cannot commit or republish Active");
 need(NrdBridge::gService->resetSerial>beforeResetEpoch && NrdBridge::gService->failures==beforeResetFailures,
  "reset cancellation preserves the new epoch without spending a provider failure retry");
 c.frame(3); need(NrdBridge::GetStatus().active,"fresh frame recovers after output admission cancellation");
 const auto beforeCancelledTag=NrdBridge::GetStatus().framesBridged;
 const auto beforeTagFailures=NrdBridge::gService->failures;
 afterRRForTesting=+[] {
  auto* foreign=lastReconInputs.reconSpec;
  std::thread tagger([foreign] { NrdBridge::OnTitleTag(nullptr,"MotionVectors",foreign); }); tagger.join();
 }; c.frame(3); afterRRForTesting=nullptr;
 need(NrdBridge::GetStatus().framesBridged==beforeCancelledTag && !NrdBridge::GetStatus().active &&
  !NrdBridge::gService->cache.Valid() && FrameSurvey::BindingWindow(),
  "normal-thread tag change during provider success cancels the stale commit and preserves rediscovery");
 need(NrdBridge::gService->failures==beforeTagFailures && NrdBridge::GetStatus().reason.find("motion tag")!=std::string::npos,
  "tag cancellation preserves its diagnostic and does not consume provider retry budget");
 NrdBridge::OnTitleTag(h.list.Get(),"MotionVectors",c.textures[6].Get()); c.frame(3); c.frame(3);
 need(NrdBridge::GetStatus().active,"clean tagged chain rediscovers and recovers after cancellation");
 // A new list may use Reset/CreateCommandList initial PSO without SetPipelineState.
 ComPtr<ID3D12CommandAllocator> initialAllocator; ComPtr<ID3D12GraphicsCommandList> initialList;
 hr(h.dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&initialAllocator)));
 hr(h.dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,initialAllocator.Get(),c.pipelines[UINT(Role::Recon)].Get(),IID_PPV_ARGS(&initialList)));
 FrameSurvey::Reset(initialList.Get(),c.pipelines[UINT(Role::Recon)].Get());
 NrdBridge::OnReset(initialList.Get(),c.pipelines[UINT(Role::Recon)].Get());
 need(NrdBridge::gService->window && FrameSurvey::BindingWindow(),"new list initial Recon PSO opens binding window without SetPipelineState");
 initialList->SetComputeRootSignature(c.root.Get());FrameSurvey::RootBinding(initialList.Get(),false,c.root.Get());
 ID3D12DescriptorHeap* initialHeap=c.visible.Get();initialList->SetDescriptorHeaps(1,&initialHeap);FrameSurvey::DescriptorHeaps(initialList.Get(),1,&initialHeap);
 for(UINT i : {0u,3u,4u})initialList->SetComputeRoot32BitConstant(i,0,0);
 initialList->SetComputeRootConstantBufferView(2,c.consumerConstants->GetGPUVirtualAddress());FrameSurvey::RootView(initialList.Get(),false,2,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,c.consumerConstants->GetGPUVirtualAddress());
 for(auto [parameter,index] : {std::pair<UINT,UINT>{1,0},{5,8}}){D3D12_GPU_DESCRIPTOR_HANDLE handle {c.gpu.ptr+uint64_t(index)*c.increment};initialList->SetComputeRootDescriptorTable(parameter,handle);FrameSurvey::Table(initialList.Get(),false,parameter,handle);}
 const auto initialConversions=convertCalls;initialList->Dispatch(1,1,1);NrdBridge::AfterDispatch(initialList.Get());
 need(convertCalls==initialConversions+1 && NrdBridge::gService->lists.at(initialList.Get()).converted,"initial Recon records conversion without any explicit SetPipelineState callback");
 NrdBridge::OnReset(initialList.Get(),nullptr);ResTrack_Dx12::ResetForTesting(initialList.Get());FrameSurvey::Released(initialList.Get());hr(initialList->Close());
 c.frame(3);
 // Pause an old close before publication, then publish and seed a newer open.
 NrdBridge::gBeforeBindingWindowPublishForTesting=windowPublicationProbe;
 windowPublisherPaused.store(false);resumeWindowPublisher.store(false);
 std::thread lateClose([&]{delayWindowPublisher=true;NrdBridge::PublishBindingWindow();});
 try { await([]{return windowPublisherPaused.load(std::memory_order_acquire);},"old window publisher is delayed before reading current state"); }
 catch (...) { resumeWindowPublisher.store(true);lateClose.join();NrdBridge::gBeforeBindingWindowPublishForTesting=nullptr;throw; }
 NrdBridge::OnSetPipeline(h.list.Get(),c.pipelines[UINT(Role::Recon)].Get());
 need(NrdBridge::gService->window && FrameSurvey::BindingWindow(),"new Recon opens and seeds its binding window while an old close waits");
 resumeWindowPublisher.store(true,std::memory_order_release);lateClose.join();NrdBridge::gBeforeBindingWindowPublishForTesting=nullptr;
 need(NrdBridge::gService->window && FrameSurvey::BindingWindow(),"delayed close publishes current desired state and cannot override a newer open");
 std::vector<Bound> liveAfterClose;
 need(FrameSurvey::ResolveComputeTable(h.list.Get(),5,liveAfterClose) && !liveAfterClose.empty(),"newly seeded live descriptor mirror survives delayed old publication");
 c.frame(3);
 auto metadata=descriptorMetadataTests(c); auto timings=cpuTimings(c); FrameSurvey::SetBindingWindow(true); c.begin(); c.bind(1,0);
 FrameSurvey::Fail("fixture recorder-only capture failure");
 need(FrameSurvey::gMetadataHealthy.load(),"recorder-only capture failures do not latch creation or binding metadata unhealthy");
 c.pass(Role::Recon); c.pass(Role::PrePass); c.pass(Role::Temporal); c.postTemporal(3); c.frame(3);
 c.begin(); h.list->SetPipelineState(c.pipelines[UINT(Role::Recon)].Get());
 NrdBridge::OnSetPipeline(h.list.Get(),c.pipelines[UINT(Role::Recon)].Get()); c.bind(1,0); c.bind(5,8); h.list->Dispatch(1,1,1);
 const auto healthWaitConversion=convertCalls; conversionStaged.store(false); NrdBridge::gBeforeConversionLockForTesting=conversionLockProbe;
 std::unique_lock healthSerial(NrdBridge::gInjectionMutex);
 std::thread healthWaiter([&]{NrdBridge::AfterDispatch(h.list.Get());});
 try { await([]{return conversionStaged.load(std::memory_order_acquire);},"validated conversion stages before a metadata allocation fault while waiting for native serialization"); }
 catch (...) { healthSerial.unlock(); healthWaiter.join(); NrdBridge::gBeforeConversionLockForTesting=nullptr; throw; }
 auto faultDestination=c.visible->GetCPUDescriptorHandleForHeapStart(); D3D12_CPU_DESCRIPTOR_HANDLE faultSource {c.cpu.ptr+c.increment}; UINT one=1;
 h.dev->CopyDescriptorsSimple(1,faultDestination,faultSource,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 FrameSurvey::gCopyFailureAfterForTesting=0;
 FrameSurvey::CopyDescriptors(h.dev.Get(),1,&faultDestination,&one,1,&faultSource,&one,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 healthSerial.unlock(); healthWaiter.join(); NrdBridge::gBeforeConversionLockForTesting=nullptr;
 need(convertCalls==healthWaitConversion && !NrdBridge::GetStatus().active && NrdBridge::GetStatus().reason.find("unhealthy")!=std::string::npos,"metadata fault during injection mutex wait cancels staged conversion before native work");
 need(!FrameSurvey::gMetadataHealthy.load() && !FrameSurvey::ResolveComputeTable(h.list.Get(),1,empty) && empty.empty(),"copy allocation fault rejects stale old descriptor metadata while both resources remain alive");
 need(!FrameSurvey::SeedComputeBindings(h.list.Get(),D3D12Hooks::current),"unhealthy metadata cannot be made eligible by root-state seeding");
 FrameSurvey::BeginCreationTracking(false);
 need(!FrameSurvey::gMetadataHealthy.load(),"repeated creation tracking and binding windows cannot clear the device health latch");
 const auto unhealthyConversion=convertCalls,unhealthyRR=rrCalls; c.frame(3);
 need(convertCalls==unhealthyConversion && rrCalls==unhealthyRR && !NrdBridge::GetStatus().active && !NrdBridge::gService->cache.Valid(),"unhealthy current-table metadata stops all bridge writes until clean device restart");
 FrameSurvey::Released(c.visible.Get());
 need(!FrameSurvey::ResolveComputeTable(h.list.Get(),1,empty),"descriptor heap release invalidates bindings");
 FrameSurvey::SetBindingWindow(false); need(!FrameSurvey::ResolveComputeTable(h.list.Get(),1,empty),"closed binding window resolves no cached stale copies");
 NrdBridge::Shutdown(); hr(h.list->Close()); h.execute(); h.reset(); h.errors();
 FrameSurvey::Shutdown();
 need(FrameSurvey::gMetadataHealthy.load() && !FrameSurvey::gTracking.load(),"clean device shutdown clears failed metadata before another device starts");
 FrameSurvey::BeginCreationTracking(false);
 need(FrameSurvey::gMetadataHealthy.load() && FrameSurvey::gTracking.load(),"a fresh device creation registry resumes with healthy metadata");
 const auto priorEnabled=FrameSurvey::gEnabled.load(), priorRecording=FrameSurvey::gRecording.load();
 FrameSurvey::gEnabled=true; FrameSurvey::gRecording=true;
 {
  std::scoped_lock injection(NrdBridge::gInjectionMutex);
  std::scoped_lock held(FrameSurvey::gRecordMutex,FrameSurvey::gLifetimeMutex,FrameSurvey::gMirrorMutex);
  FrameSurvey::MetadataHookFailed("fixture inside injection and recorder/registry locks");
  need(!FrameSurvey::MetadataHealthy() && !FrameSurvey::Recording(),"native hook failure latch takes no lifecycle/recorder locks and stops unsafe recorder work");
 }
 FrameSurvey::BeginCreationTracking(false);
 need(!FrameSurvey::MetadataHealthy(),"hook failure cannot be cleared by retrying creation tracking");
 FrameSurvey::gEnabled=priorEnabled; FrameSurvey::gRecording=priorRecording;
 FrameSurvey::Shutdown();
 for(const auto& role:NrdBridge::ShaderRoles) {
  need(role.sha256.size()==64,"all roles use full SHA256"); need(NrdBridge::IdentifyRole(role.sha256)==role.role,"full shader digest identifies exact role");
  need(NrdBridge::IdentifyRole(role.sha256.substr(0,8))==Role::None,"hash prefixes never identify roles");
  std::string altered(role.sha256); altered.back()=altered.back()=='0' ? '1' : '0';
  need(NrdBridge::IdentifyRole(altered)==Role::None,"same prefix with different full hash never identifies a role");
 }
 return {{"descriptor_metadata",metadata},{"metadata_allocation_fault_fail_closed",true},{"cpu_callback_timings",timings},{"conversion_stub_calls",convertCalls},{"motion_stub_calls",motionCalls},{"rr_stub_calls",rrCalls},{"debug_stub_calls",debugCalls},
  {"history_resets",{{"conversion",depthResets},{"rr",rrResets},{"discarded_rr_contexts",rrDiscards}}},{"restore_callback_calls",D3D12Hooks::restores}};
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
 result["scope"]="real D3D12 registry, binding-window resolution and coordinator; conversion/RR/state-restore callback stubs; typed submission publication is a CPU counter adapter without a GPU fence";
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/12a-discovery/tests/discovery'))
    output.mkdir(parents=True, exist_ok=True)
    stubs = output / 'stubs'
    for folder in ('proxies', 'inputs', 'hooks', 'resource_tracking'):
        (stubs / folder).mkdir(parents=True, exist_ok=True)
    (stubs / 'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#include <memory>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs / 'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline bool CheckForRealObject(std::string,IUnknown*,IUnknown**) { return false; } inline std::filesystem::path DllPath() { return g_dllPath; } inline std::filesystem::path ExePath() { return L"cyberpunk2077.exe"; } }\n')
    (stubs / 'Config.h').write_text('#pragma once\ntemplate<class T> struct FixtureOptional { T value; unsigned volatileWrites=0; bool volatileValue=false; T value_or_default() const { return value; } void set_volatile_value(const T& next) { value=next; volatileValue=true; ++volatileWrites; } };\nstruct Config { FixtureOptional<bool> FfxDenoiserNrdBridge {false}, FfxDenoiserNrdBridgeEnabled {true}, RestoreComputeSignature {false}, ExtendedStateRestore {false}; static Config* Instance() { static Config config; return &config; } };\n')
    (stubs / 'hooks/D3D12_Hooks.h').write_text('#pragma once\nstruct D3D12Hooks { inline static bool tracking=true, canRestore=true; inline static unsigned restores=0; inline static FrameSurvey::ComputeBindings current {}; static bool GetComputeBindingsForBridge(ID3D12GraphicsCommandList*,FrameSurvey::ComputeBindings& out) noexcept { out=current; return out.root && !out.heaps.empty(); } static void SetRootSignatureTracking(bool enabled) { tracking=enabled; } static bool RootSignatureTrackingEnabled() { return tracking; } static bool CanRestoreRootSignature(ID3D12GraphicsCommandList*) { return canRestore && Config::Instance()->RestoreComputeSignature.value_or_default() && Config::Instance()->ExtendedStateRestore.value_or_default(); } static void RestoreRoot(ID3D12GraphicsCommandList*) { ++restores; } };\n')
    (stubs / 'hooks/Streamline_Hooks.h').write_text('#pragma once\n#include <sl_consts.h>\nstruct SLConstantsSnapshot { sl::Constants constants {}; uint32_t frameIndex=UINT32_MAX, viewport=UINT32_MAX; };\nstruct StreamlineHooks { inline static uint32_t frame=0; static SLConstantsSnapshot getSLConstantsSnapshot() { SLConstantsSnapshot result; result.frameIndex=frame; return result; } };\n')
    (stubs / 'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs / 'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    (stubs / 'resource_tracking/ResTrack_dx12.h').write_text('#pragma once\n#include <functional>\n#include <unordered_map>\n#include "misc/RecordedComputeLease_Dx12.h"\nstruct ResTrack_Dx12 { struct Lease { std::shared_ptr<void> payload; std::function<void(ID3D12CommandQueue*)> callback; RecordedComputeLease::SubmissionCallbacks typed; uint64_t ordinal=0; }; inline static std::unordered_map<ID3D12GraphicsCommandList*,std::vector<Lease>> leases; inline static bool retentionAvailable=true; static bool RetainComputeDispatch(ID3D12Device*,ID3D12GraphicsCommandList* list,const std::shared_ptr<void>& payload,std::function<void(ID3D12CommandQueue*)> callback={},RecordedComputeLease::SubmissionCallbacks typed={}) { if(!retentionAvailable) return false; leases[list].push_back({payload,std::move(callback),std::move(typed),0}); return true; } static void ResetForTesting(ID3D12GraphicsCommandList* list) { leases.erase(list); } static void SubmitForTesting(ID3D12GraphicsCommandList* list) { for(auto& lease:leases[list]) { RecordedComputeLease::SubmissionInfo info {nullptr,1,1,++lease.ordinal,false}; if(lease.callback) lease.callback(nullptr); if(lease.typed.beforeSubmit) lease.typed.beforeSubmit(info); if(lease.typed.fencePublished) lease.typed.fencePublished(info,{}); } } };\n')
    host = '#define FSRD_NRD_BRIDGE_TEST\n' + survey_fixture.CPP.split('// GetStatus()')[0]
    rr_header = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h').read_text()
    camera_stub = 'const std::string& RRWrapper::CameraConventionDescription() const noexcept { static const std::string text; return text; }' if 'CameraConventionDescription' in rr_header else ''
    pass_header = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgePass_Dx12.h').read_text()
    motion_stub = 'bool ConversionPass::DispatchMotion(ID3D12GraphicsCommandList*,const ConvertedResources&,ID3D12Resource* motion,const FrameParameters& frame,std::string&) { ++motionCalls; lastMotion=motion; lastMotionFrame=frame; internalObserved &= FrameSurvey::Internal(); trackingSuppressed &= !D3D12Hooks::tracking; return motion!=nullptr; }' if 'DispatchMotion' in pass_header else ''
    fixture_cpp = CPP.replace('__CAMERA_STUB__', camera_stub).replace('__MOTION_STUB__', motion_stub)
    source_text = (host + fixture_cpp).replace('__TRACE__', (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__', (ROOT / 'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').as_posix()).replace('__COORDINATOR__', (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp').as_posix())
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
    report = Path(os.environ.get('FSRD_NRD_DISCOVERY_REPORT', f'E:/FSRD/sol_batch/{output.parents[1].name}'))
    report.mkdir(parents=True, exist_ok=True)
    (report / 'host-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'checks_passed': result['checks_passed'], 'python_checks_passed': 4, 'result': str(output / 'host-result.json')}))


if __name__ == '__main__':
    run()
