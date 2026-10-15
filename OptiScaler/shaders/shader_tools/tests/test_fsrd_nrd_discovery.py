"""Production NRD discovery replay and real D3D12 binding-window fixture.

Conversion/RR are explicit counter stubs here: GPU/provider output and real state
restoration are verified by the separate end-to-end fixture, not claimed by this test.
The isolated native-debug process uses production leases/fences and real GPU queue
Wait edges; pixel presentation remains an explicit admission counter stub.
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
namespace NrdBridgeNativeBirth {
std::atomic<unsigned> fixtureNativeCoverageRequests {0};
// This standalone adapter links strong metadata preparation, but does not install native Release detours.
bool ObserveReleaseCoverage(IUnknown*) noexcept {
 fixtureNativeCoverageRequests.fetch_add(1,std::memory_order_relaxed);
 FrameSurvey::MetadataHookFailed(Ready() ? "Standalone fixture has no native Release coverage dispatcher" :
  "Unconfigured native Release coverage unexpectedly entered the legacy standalone fixture");
 return false; // In particular, Ready=true can never obtain synthetic coverage success.
}
}
unsigned convertCalls=0, motionCalls=0, rrCalls=0, debugCalls=0, depthResets=0, rrResets=0, rrDiscards=0;
bool internalObserved=true, trackingSuppressed=true, observerUnlocked=true, throwPrepare=false, deferredMotion=true;
void (*afterRRForTesting)() = nullptr;
void (*beforeDebugAdmissionForTesting)() = nullptr;
unsigned nativeSnapshotCalls=0,nativePresentPreparations=0,nativePresentActions=0,nativeImageRetirements=0,retirementReleaseCallbacks=0;
bool retirementProbeEnabled=false;
uint32_t lastNativeSourceSL=UINT32_MAX;
bool lastNativeOrdered=false;
D3D12_RESOURCE_STATES lastNativeTargetState=D3D12_RESOURCE_STATE_COMMON;
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
std::unordered_map<const RRWrapper*,RRSettingsState> fixtureRRStates;
struct ConfigureObservation { const RRWrapper* wrapper; RRSettings desired; std::array<float,8> effective; };
std::vector<ConfigureObservation> fixtureConfigureCalls;
RRWrapper::RRWrapper() {fixtureRRStates[this]={};fixtureRRStates[this].defaults.fill(.5f);fixtureRRStates[this].effective.fill(.5f);}
struct FixtureNativeOwner {
 ComPtr<ID3D12Resource> image;
 FixtureNativeOwner(ID3D12Resource* source,UINT width,UINT height) {
  ComPtr<ID3D12Device> device;hr(source->GetDevice(IID_PPV_ARGS(&device)));
  const auto desc=CD3DX12_RESOURCE_DESC::Tex2D(DXGI_FORMAT_R16G16B16A16_FLOAT,width,height,1,1,1,0,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
  D3D12_HEAP_PROPERTIES heap {};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
  hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&image)));
 }
 ~FixtureNativeOwner() { ++nativeImageRetirements; OnReleased(image.Get()); }
};
std::unordered_map<const RRWrapper*,RRWrapperNativeDebugOutputSnapshot> fixtureNativeImages;
RRWrapper::~RRWrapper() {
 fixtureNativeImages.erase(this);fixtureRRStates.erase(this);
 if(retirementProbeEnabled) { ++retirementReleaseCallbacks; OnReleased(reinterpret_cast<void*>(uintptr_t(0x13e02000))); }
}
bool ValidateRRSettings(const RRSettings& settings,std::string& error) {
 // Structural stub only; the production RR suite proves actual AMD key/range validation.
 if(settings.overrideMask&~0x7fu){error="fixture invalid mask";return false;}
 if(settings.nativeDebugView < -1 || settings.nativeDebugView > 1 || settings.nativeDebugViewport > 11){error="fixture invalid debug selector";return false;}
 for(UINT i=0;i<7;++i)if((settings.overrideMask&(1u<<i))&&!std::isfinite(settings.values[i])){error="fixture nonfinite setting";return false;}
 return true;
}
bool RRWrapper::Configure(const RRSettings& settings,std::string& error) {
 if(!ValidateRRSettings(settings,error))return false;
 auto& state=fixtureRRStates.at(this);state.requested=settings;state.effective=state.defaults;
 for(UINT i=0;i<8;++i)if(!(settings.overrideMask&(1u<<(i==7?6:i))))state.requested.values[i]=0;
 for(UINT i=0;i<8;++i)if(settings.overrideMask&(1u<<(i==7?6:i)))state.effective[i]=settings.values[i];
 fixtureConfigureCalls.push_back({this,state.requested,state.effective});return true;
}
RRSettingsState RRWrapper::GetSettingsState() const noexcept {return fixtureRRStates.at(this);}

bool RRWrapper::PrepareFrame(const SLConstantsSnapshot& sl,bool reset,FrameParameters& out,std::string&) {
 if(throwPrepare) throw std::runtime_error("fixture provider exception");
 fixtureRRStates.at(this).ready=true;
 out.streamlineFrame=sl.frameIndex; out.frameIndex=rrCalls; out.reset=reset; return true;
}
bool RRWrapper::Dispatch(ID3D12GraphicsCommandList* cmd,const ConvertedResources& inputs,ID3D12Resource* outputSpec,ID3D12Resource* outputDiff,
                        const FrameParameters& frame,std::string&,const OutputCommitGuard& guard) {
 ++rrCalls; lastOutSpec=outputSpec; lastOutDiff=outputDiff; lastRRFrame=frame;
 internalObserved &= FrameSurvey::Internal(); trackingSuppressed &= !D3D12Hooks::tracking;
 if(afterRRForTesting) afterRRForTesting();
 const bool committed=!guard.admit || guard.admit(guard.state,+[](void*) noexcept {},nullptr);
 if(committed&&fixtureRRStates.at(this).requested.nativeDebugView>=0) {
  auto owner=MakeOwnedShared<FixtureNativeOwner>(outputSpec,inputs.width,inputs.height);
  fixtureNativeImages[this]={owner->image.Get(),owner,cmd,frame.streamlineFrame,inputs.width,inputs.height,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
 }
 return committed;
}
RRWrapperNativeDebugOutputSnapshot RRWrapper::GetNativeDebugOutputSnapshot() const noexcept {
 ++nativeSnapshotCalls;const auto found=fixtureNativeImages.find(this);return found==fixtureNativeImages.end()?RRWrapperNativeDebugOutputSnapshot{}:found->second;
}
bool RRWrapper::PresentNativeDebug(ID3D12GraphicsCommandList* cmd,ID3D12Resource* out,D3D12_RESOURCE_STATES state,
                                  uint32_t frame,std::string& error,bool ordered,const OutputCommitGuard& guard) {
 const auto image=GetNativeDebugOutputSnapshot();if(image.frameSL!=frame)return false;
 return PresentNativeDebug(cmd,out,state,image,error,ordered,guard);
}
bool RRWrapper::PresentNativeDebug(ID3D12GraphicsCommandList*,ID3D12Resource*,D3D12_RESOURCE_STATES state,
                                  const RRWrapperNativeDebugOutputSnapshot& image,std::string&,bool ordered,const OutputCommitGuard& guard) {
 ++nativePresentPreparations;lastNativeSourceSL=image.frameSL;lastNativeOrdered=ordered;lastNativeTargetState=state;
 internalObserved &= FrameSurvey::Internal(); trackingSuppressed &= !D3D12Hooks::tracking;
 if(beforeDebugAdmissionForTesting)beforeDebugAdmissionForTesting();
 return !guard.admit || guard.admit(guard.state,+[](void*) noexcept {++nativePresentActions;},nullptr);
}
void RRWrapper::ResetHistory() noexcept { ++rrResets; }
void RRWrapper::DiscardRecordingHistory() noexcept { ++rrDiscards; }
uint64_t RRWrapper::ContextGeneration() const noexcept { return 0; }
__CAMERA_STUB__
}
using NrdBridge::fixtureConfigureCalls;
using NrdBridge::fixtureNativeImages;
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
  need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled(),"metadata-only ResTrack adapter leaves native retirement unconfigured and retains the legacy gate");
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
   NrdBridge::RegisterPipelineRoleForTesting(pipelines[i].Get(),Role(i),true);
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
 NrdBridge::RegisterPipelineRoleForTesting(c.pipelines[UINT(Role::Recon)].Get(),Role::Recon,true);
 FrameSurvey::PipelineCreated(c.pipelines[UINT(Role::Recon)].Get(),D3D12_PIPELINE_STATE_STREAM_DESC {});
 need(!NrdBridge::gService->roles.contains(c.pipelines[UINT(Role::Recon)].Get()),"failed/no-CS stream creation erases an old PSO role");
 NrdBridge::RegisterPipelineRoleForTesting(c.pipelines[UINT(Role::Recon)].Get(),Role::Recon,true);
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
J settingsTests(Host& h) {
 ChainHost c(h); std::string error;
 auto nextFrame=[&]{++StreamlineHooks::frame;c.frame(3);};
 auto submit=[&]{ResTrack_Dx12::SubmitForTesting(h.list.Get());};
 auto sameDesired=[](const NrdBridge::RRSettings& a,const NrdBridge::RRSettings& b) {
  return a.overrideMask==b.overrideMask && a.values==b.values && a.nativeDebugView==b.nativeDebugView && a.nativeDebugViewport==b.nativeDebugViewport && a.preserveNativeMaterialIDs==b.preserveNativeMaterialIDs;
 };
 nextFrame();need(convertCalls==0&&rrCalls==0,"settings process discovers a complete chain before bridge work");
 need(!lastRGBFrame.preserveNativeMaterialIDs&&!lastMotionFrame.preserveNativeMaterialIDs&&!lastRRFrame.preserveNativeMaterialIDs,"material ID experiment is OFF in every default stage");
 nextFrame();need(NrdBridge::GetStatus().active&&rrCalls==1,"settings process establishes a valid default frame");submit();
 auto defaults=NrdBridge::GetRRSettingsState();
 need(defaults.ready&&defaults.requested.overrideMask==0&&defaults.defaults==defaults.effective,"mask zero observes queried-default semantics through the wrapper adapter");
 need(!NrdBridge::CameraProjectedDepthEnabled()&&!lastRGBFrame.cameraProjectedDepthDelta&&!lastMotionFrame.cameraProjectedDepthDelta&&!lastRRFrame.cameraProjectedDepthDelta,"camera-projected depth is OFF in all default stages");
 NrdBridge::RRSettings configured;
 auto defaultSerial=NrdBridge::gService->cancellationSerial;
 const auto defaultResets=rrResets;
 need(NrdBridge::ApplyRRSettings(configured,false,error),"default mask-zero configuration is accepted");
 need(NrdBridge::gService->cancellationSerial==defaultSerial&&rrResets==defaultResets,"unchanged effective defaults do not cancel or reset submitted history");
 ++StreamlineHooks::frame;c.begin();c.pass(Role::PrepLast);c.pass(Role::Recon);
 const auto canceledRR=rrCalls,canceledMotion=motionCalls;
 const auto canceledBridged=NrdBridge::GetStatus().framesBridged;
 const auto reconSerial=NrdBridge::gService->cancellationSerial;
 need(lastRGBFrame.cameraProjectedDepthDelta==false&&NrdBridge::gService->lists.at(h.list.Get()).converted,"pre-change Recon stages the original immutable camera convention");
 configured.overrideMask=1;configured.values[0]=.25f;
 need(NrdBridge::ApplyRRSettings(configured,true,error),"valid scalar and motion settings apply atomically");
 need(NrdBridge::gService->cancellationSerial>reconSerial&&!NrdBridge::gService->lists.at(h.list.Get()).converted&&!NrdBridge::gService->lists.at(h.list.Get()).motionReady,"effective change cancels the already-converted current recording");
 need(NrdBridge::CameraProjectedDepthEnabled()&&!lastRGBFrame.cameraProjectedDepthDelta,"new desired motion mode cannot rewrite the already-recorded Recon snapshot");
 c.pass(Role::PrePass);c.pass(Role::Temporal);c.postTemporal(3);
 need(rrCalls==canceledRR&&motionCalls==canceledMotion&&NrdBridge::GetStatus().framesBridged==canceledBridged&&!NrdBridge::GetStatus().active,"canceled Recon produces no motion/RR commit and cannot republish Active");
 nextFrame();
 need(NrdBridge::GetStatus().active&&rrCalls==canceledRR+1&&lastRRFrame.reset,"next valid Recon recovers with one RR commit and first-frame RESET");
 need(lastRGBFrame.cameraProjectedDepthDelta&&lastMotionFrame.cameraProjectedDepthDelta&&lastRRFrame.cameraProjectedDepthDelta,"RGB, deferred motion and RR share the new immutable motion snapshot");
 auto applied=NrdBridge::GetRRSettingsState();
 need(applied.ready&&sameDesired(applied.requested,configured)&&applied.effective[0]==.25f,"cached state reports the coherent requested/effective scalar snapshot");
 need(!fixtureConfigureCalls.empty()&&sameDesired(fixtureConfigureCalls.back().desired,configured)&&fixtureConfigureCalls.back().effective[0]==.25f,"the actual coordinator passes desired settings into its private history wrapper");
 submit();nextFrame();
 need(NrdBridge::GetStatus().active&&!lastRRFrame.reset,"normal submitted continuation keeps new settings without repeated RESET");submit();
 const auto stableSerial=NrdBridge::gService->cancellationSerial;
 const auto stableResets=rrResets;
 need(NrdBridge::ApplyRRSettings(configured,true,error),"identical settings reapply succeeds");
 need(NrdBridge::gService->cancellationSerial==stableSerial&&rrResets==stableResets,"identical desired/effective settings preserve the admitted history epoch");
 auto invalid=configured;invalid.overrideMask=0x80;
 const auto callsBeforeInvalid=fixtureConfigureCalls.size();
 need(!NrdBridge::ApplyRRSettings(invalid,true,error)&&!error.empty(),"unknown override bits fail before provider mutation");
 invalid=configured;invalid.values[0]=std::numeric_limits<float>::quiet_NaN();error.clear();
 need(!NrdBridge::ApplyRRSettings(invalid,true,error)&&!error.empty(),"selected nonfinite scalar fails before provider mutation");
 need(NrdBridge::gService->cancellationSerial==stableSerial&&fixtureConfigureCalls.size()==callsBeforeInvalid&&sameDesired(NrdBridge::GetRRSettingsState().requested,configured),"invalid requests preserve epoch, provider calls and the last valid desired state");
 ++StreamlineHooks::frame;c.begin();c.pass(Role::PrepLast);c.pass(Role::Recon);c.pass(Role::PrePass);c.pass(Role::Temporal);
 const auto canceledTemporalRR=rrCalls;
 const auto canceledTemporalBridged=NrdBridge::GetStatus().framesBridged;
 const auto temporalSerial=NrdBridge::gService->cancellationSerial;
 need(lastRGBFrame.cameraProjectedDepthDelta&&lastMotionFrame.cameraProjectedDepthDelta&&NrdBridge::gService->lists.at(h.list.Get()).motionReady,"motion-ready recording uses the previous coherent snapshot");
 configured.values[0]=.125f;
 need(NrdBridge::ApplyRRSettings(configured,true,error),"scalar-only effective change succeeds after Temporal");
 need(NrdBridge::gService->cancellationSerial>temporalSerial&&!NrdBridge::gService->lists.at(h.list.Get()).converted,"scalar-only change also cancels the motion-ready recording");
 c.postTemporal(3);
 need(rrCalls==canceledTemporalRR&&NrdBridge::GetStatus().framesBridged==canceledTemporalBridged&&!NrdBridge::GetStatus().active,"canceled Temporal cannot reach RR output commit or Active publication");
 nextFrame();need(NrdBridge::GetStatus().active&&lastRRFrame.reset&&lastRGBFrame.cameraProjectedDepthDelta,"next Recon applies scalar-only change with RESET and the unchanged motion convention");submit();
 nextFrame();need(NrdBridge::GetStatus().active&&!lastRRFrame.reset,"new scalar history stabilizes after a normal published submission");
 // Successful but unsubmitted work cannot seed a later recording. Its replacement must inherit the desired snapshot.
 const auto inheritedConfigure=fixtureConfigureCalls.size();
 nextFrame();
 need(NrdBridge::GetStatus().active&&lastRRFrame.reset&&fixtureConfigureCalls.size()>inheritedConfigure,"discarded recording creates/reconfigures a fresh private history with RESET");
 const auto inherited=NrdBridge::GetRRSettingsState();
 need(sameDesired(inherited.requested,configured)&&inherited.effective[0]==.125f&&sameDesired(fixtureConfigureCalls.back().desired,configured),"fresh history inherits the exact desired settings instead of reverting to defaults");submit();
 ++StreamlineHooks::frame;c.begin();c.pass(Role::PrepLast);c.pass(Role::Recon);
 const auto canceledModeRR=rrCalls;
 const auto modeSerial=NrdBridge::gService->cancellationSerial;
 need(NrdBridge::ApplyRRSettings(configured,false,error),"motion-only mode change is accepted");
 c.pass(Role::PrePass);c.pass(Role::Temporal);c.postTemporal(3);
 need(NrdBridge::gService->cancellationSerial>modeSerial&&rrCalls==canceledModeRR&&!NrdBridge::GetStatus().active,"motion-only change cancels the old recorded guide interpretation");
 nextFrame();
 need(NrdBridge::GetStatus().active&&lastRRFrame.reset&&!lastRGBFrame.cameraProjectedDepthDelta&&!lastMotionFrame.cameraProjectedDepthDelta&&!lastRRFrame.cameraProjectedDepthDelta,"next frame returns every stage coherently to baseline OFF with RESET");submit();
 ++StreamlineHooks::frame;c.begin();c.pass(Role::PrepLast);c.pass(Role::Recon);
 const auto materialRR=rrCalls;const auto materialFrames=NrdBridge::GetStatus().framesBridged;
 const auto materialEpoch=NrdBridge::gService->cancellationSerial;
 configured.preserveNativeMaterialIDs=true;
 need(NrdBridge::ApplyRRSettings(configured,false,error),"material-only setting change is accepted after Recon");
 need(NrdBridge::gService->cancellationSerial>materialEpoch&&!lastRGBFrame.preserveNativeMaterialIDs,"material change cancels the recording without rewriting old Recon parameters");
 c.pass(Role::PrePass);c.pass(Role::Temporal);c.postTemporal(3);
 need(rrCalls==materialRR&&NrdBridge::GetStatus().framesBridged==materialFrames&&!NrdBridge::GetStatus().active,"canceled material recording has no RR commit or Active publication");
 nextFrame();
 need(lastRGBFrame.preserveNativeMaterialIDs&&lastMotionFrame.preserveNativeMaterialIDs&&lastRRFrame.preserveNativeMaterialIDs&&lastRRFrame.reset,"next Recon captures material preservation coherently with first RESET");submit();
 nextFrame();need(NrdBridge::GetStatus().active&&!lastRRFrame.reset&&NrdBridge::GetRRSettingsState().requested.preserveNativeMaterialIDs,"material history remains stable after published submission");
 nextFrame();need(lastRRFrame.reset&&sameDesired(NrdBridge::GetRRSettingsState().requested,configured),"fresh replacement history inherits the exact material setting");submit();
 ++StreamlineHooks::frame;c.begin();c.pass(Role::PrepLast);c.pass(Role::Recon);c.pass(Role::PrePass);c.pass(Role::Temporal);
 const auto materialOffRR=rrCalls;configured.preserveNativeMaterialIDs=false;
 need(NrdBridge::ApplyRRSettings(configured,false,error),"material OFF change is accepted after motion conversion");c.postTemporal(3);
 need(rrCalls==materialOffRR&&!NrdBridge::GetStatus().active,"material OFF cannot commit the already-recorded ON guides");
 nextFrame();need(!lastRGBFrame.preserveNativeMaterialIDs&&!lastMotionFrame.preserveNativeMaterialIDs&&!lastRRFrame.preserveNativeMaterialIDs&&lastRRFrame.reset,"material OFF recovers the default interpretation coherently with RESET");submit();
 NrdBridge::Shutdown();hr(h.list->Close());h.execute();h.reset();h.errors();FrameSurvey::Shutdown();
 return {{"material_snapshot_coherent",true},{"default_mask_zero",true},{"canceled_recon",true},{"canceled_temporal",true},{"invalid_preserves_state",true},
  {"fresh_history_inherits_settings",true},{"motion_snapshot_coherent",true},{"rr_calls",rrCalls},{"configure_observations",fixtureConfigureCalls.size()},
  {"sdk_called",false},{"debug_layer_errors",0}};
}

struct NativeWaitEvent { ID3D12CommandQueue* queue; ID3D12Fence* fence; UINT64 value; };
using NativeWaitFn=HRESULT(STDMETHODCALLTYPE*)(ID3D12CommandQueue*,ID3D12Fence*,UINT64);
NativeWaitFn originalNativeWait=nullptr;
ID3D12CommandQueue* watchedQueueA=nullptr;ID3D12CommandQueue* watchedQueueB=nullptr;DWORD watchedSubmitThread=0;
std::vector<NativeWaitEvent> nativeWaitEvents;
HRESULT STDMETHODCALLTYPE observeNativeWait(ID3D12CommandQueue* queue,ID3D12Fence* fence,UINT64 value) {
 if(GetCurrentThreadId()==watchedSubmitThread&&(queue==watchedQueueA||queue==watchedQueueB))nativeWaitEvents.push_back({queue,fence,value});
 return originalNativeWait(queue,fence,value);
}
struct NativeWaitProbe {
 bool armed=false;
 NativeWaitProbe(ID3D12CommandQueue* a,ID3D12CommandQueue* b) {
  watchedQueueA=a;watchedQueueB=b;watchedSubmitThread=GetCurrentThreadId();const auto table=*reinterpret_cast<void***>(b);
  originalNativeWait=reinterpret_cast<NativeWaitFn>(table[15]);
  need(DetourTransactionBegin()==NO_ERROR,"native Wait probe transaction");
  need(DetourUpdateThread(GetCurrentThread())==NO_ERROR,"native Wait probe thread");
  need(DetourAttach(reinterpret_cast<PVOID*>(&originalNativeWait),reinterpret_cast<PVOID>(observeNativeWait))==NO_ERROR,"native Wait probe attachment");
  need(DetourTransactionCommit()==NO_ERROR,"native Wait probe commit");armed=true;
 }
 void stop() {
  need(DetourTransactionBegin()==NO_ERROR,"native Wait probe detach transaction");
  need(DetourUpdateThread(GetCurrentThread())==NO_ERROR,"native Wait probe detach thread");
  need(DetourDetach(reinterpret_cast<PVOID*>(&originalNativeWait),reinterpret_cast<PVOID>(observeNativeWait))==NO_ERROR,"native Wait probe detach");
  need(DetourTransactionCommit()==NO_ERROR,"native Wait probe detach commit");armed=false;watchedQueueA=watchedQueueB=nullptr;
 }
 ~NativeWaitProbe() {
  if(armed) {DetourTransactionBegin();DetourUpdateThread(GetCurrentThread());DetourDetach(reinterpret_cast<PVOID*>(&originalNativeWait),reinterpret_cast<PVOID>(observeNativeWait));DetourTransactionCommit();}
 }
};
#ifdef FSRD_FIXTURE_NATIVE_RETIREMENT_METHOD
struct StartupConfigurationProbe {
 inline static std::atomic<bool> entered {false},release {false},unlocked {false};
 static void Pause() {
  unlocked.store(!NrdBridgeBirth::InMetadataScope(),std::memory_order_release);entered.store(true,std::memory_order_release);
  while(!release.load(std::memory_order_acquire))std::this_thread::yield();
 }
};
#endif
J startupConfigurationTests(Host& h,bool offFirst) {
#ifdef FSRD_FIXTURE_NATIVE_RETIREMENT_METHOD
 need(!NrdBridge::StartupEnabled()&&!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled(),"fresh startup fixture begins without dispatcher, selection or concurrent releases");
 need(ResTrack_Dx12::fixtureNativeConfigurations.load()==0&&FrameSurvey::MetadataHealthy()&&NrdBridgeBirth::Healthy(),"fresh native failure adapter starts healthy with zero configuration calls");
 if(offFirst) {
  NrdBridge::ConfigureStartup(false);
  for(UINT i=0;i<5;++i) {NrdBridge::ConfigureStartup(true);NrdBridge::ConfigureStartup(false);}
  need(!NrdBridge::StartupEnabled()&&ResTrack_Dx12::fixtureNativeConfigurations.load()==0,"initial OFF wins permanently and repeated ON cannot invoke native configuration");
  need(FrameSurvey::MetadataHealthy()&&NrdBridgeBirth::Healthy()&&!NrdBridge::gStartupFailure.load(),"latched OFF preserves healthy metadata and has no native initialization failure side effects");
 } else {
  using Probe=StartupConfigurationProbe;
  ResTrack_Dx12::fixtureBeforeNativeConfiguration=Probe::Pause;
  std::thread first([] {NrdBridge::ConfigureStartup(true);});
  struct Join {std::thread& thread;~Join(){Probe::release.store(true,std::memory_order_release);if(thread.joinable())thread.join();}} join {first};
  await([] {return Probe::entered.load(std::memory_order_acquire);},"initial startup winner reaches the deliberately paused native initializer");
  const bool stateUnlocked=NrdBridge::gMutex.try_lock();if(stateUnlocked)NrdBridge::gMutex.unlock();
  const bool injectionUnlocked=NrdBridge::gInjectionMutex.try_lock();if(injectionUnlocked)NrdBridge::gInjectionMutex.unlock();
  need(Probe::unlocked.load(std::memory_order_acquire)&&stateUnlocked&&injectionUnlocked,"native configuration runs outside coordinator, injection and Birth metadata locks");
  need(!NrdBridge::StartupEnabled()&&!NrdBridge::Initialize(h.dev.Get()),"initializing selection denies publication and coordinator creation before the native result");
  NrdBridge::ConfigureStartup(false);NrdBridge::ConfigureStartup(true);
  need(ResTrack_Dx12::fixtureNativeConfigurations.load()==1,"concurrent/repeated startup callers cannot invoke a second native initializer");
  Probe::release.store(true,std::memory_order_release);first.join();ResTrack_Dx12::fixtureBeforeNativeConfiguration=nullptr;
  need(!NrdBridge::StartupEnabled()&&ResTrack_Dx12::fixtureNativeConfigurations.load()==1,"present native method failure permanently denies startup after exactly one initialization");
  need(!FrameSurvey::MetadataHealthy()&&!NrdBridgeBirth::Healthy(),"native initialization failure marks both metadata and Birth health inadmissible");
  const auto status=NrdBridge::GetStatus();need(status.phase=="Inactive"&&status.reason.find("Native title lifetime initialization failed")!=std::string::npos,"failed native startup has a concrete latched diagnostic");
  NrdBridge::ConfigureStartup(true);need(ResTrack_Dx12::fixtureNativeConfigurations.load()==1&&!NrdBridge::StartupEnabled(),"later ON cannot retry a failed initial native setup");
 }
 need(!NrdBridge::Initialize(h.dev.Get())&&!NrdBridge::gService,"both failed-native and explicit OFF selection prevent creation of the coordinator");
 NrdBridge::SetRuntimeEnabled(true);NrdBridge::BeforeDispatch(h.list.Get());NrdBridge::AfterDispatch(h.list.Get());
 need(convertCalls==0&&motionCalls==0&&rrCalls==0&&fixtureConfigureCalls.empty(),"denied startup records zero conversion, motion, RR or provider configuration work");
 need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled()&&NrdBridgeNativeBirth::fixtureNativeCoverageRequests.load()==0,"startup control-flow fixture never supplies native Release coverage success");
 hr(h.list->Close());h.errors();FrameSurvey::Shutdown();
 return {{"initial_off",offFirst},{"method_present",true},{"native_configuration_calls",ResTrack_Dx12::fixtureNativeConfigurations.load()},{"one_winner",true},{"zero_rr_work",true},{"native_release_coverage_proved",false},{"debug_layer_errors",0}};
#else
 throw std::runtime_error("startup native-result fixture requires its explicit present-method variant");
#endif
}
J birthNotificationTests(Host& h) {
 ChainHost c(h);FrameSurvey::SetBindingWindow(true);c.begin();c.bind(1,0);c.bind(5,8);
 auto recon=c.table(1),reconOut=c.table(5);c.bind(1,16);auto temporal=c.table(1);
 c.bind(5,32);auto atrous=c.table(5);c.bind(5,48);auto consumer=c.table(5);
 // Controlled logical epochs test delayed notifications; this does not assert native GUID/physical Release coverage.
 NrdBridgeBirth::Registry registry;uint64_t stamp=1000;
 auto pod=+[](void*,const NrdBridgeBirth::Token&) noexcept {return true;};
 auto publish=[&](void* address) {auto token=registry.PublishFresh(address,++stamp,pod,pod,nullptr);need(token&&token->Admissible(),"local registry publishes an admissible logical birth");return token;};
 const auto pso=c.pipelines[UINT(Role::Recon)].Get();const auto list=h.list.Get();
 const auto depth=c.textures[3].Get(),motion=c.textures[6].Get();
 const auto oldPso=publish(pso),newPso=publish(pso),oldList=publish(list),newList=publish(list);
 const auto oldDepth=publish(depth),newDepth=publish(depth),oldMotion=publish(motion),newMotion=publish(motion);
 need(!oldPso->Live()&&!oldList->Live()&&!oldDepth->Live()&&!oldMotion->Live(),"each delayed event carries the retired epoch at the same actual object address");
 auto births=[&](auto& table) {for(auto& bound:table) {bound.resourceBirth=registry.Capture(bound.resource);if(!bound.resourceBirth)bound.resourceBirth=publish(bound.resource);}};
 births(recon);births(reconOut);births(temporal);births(atrous);births(consumer);
 NrdBridge::ChainDiscovery chain;std::string error;
 need(chain.Begin(recon,reconOut,error)&&chain.Observe(Role::Temporal,temporal,{},motion,error)&&chain.Observe(Role::ATrous,{},atrous,nullptr,error)&&chain.Observe(Role::Consumer,{},consumer,motion,error),"exact-birth notification replay starts with the full validated production chain");
 const auto resources=chain.ReferencedResources();const auto tokens=chain.ReferencedResourceBirths();
 for(size_t i=0;i<resources.size();++i)need(!resources[i]||(tokens[i]&&tokens[i]->Address()==resources[i]),"eleven-resource birth seam preserves the exact resource order including last ATrous endpoints");
 const auto owner=NrdBridge::gService;
 {std::scoped_lock lock(NrdBridge::gMutex);
  owner->roles[pso]={Role::Recon,newPso};auto& state=owner->lists[list];state.birth=newList;state.pipelineBirth=newPso;state.role=Role::Recon;
  state.chain=chain;state.followingRecon=true;state.frame=700;owner->followingChains.insert(list);NrdBridge::RefreshChainUsers(*owner,list,state);
  owner->chainUsers[{depth,oldDepth}].insert(list); // Stale partially published reverse pair, delivered after its replacement.
  owner->cache.Publish(chain);owner->cacheBirths=NrdBridge::CacheBirths(chain);owner->taggedMotion=motion;owner->taggedMotionBirth=newMotion;
  owner->pendingList=list;owner->status.active=true;owner->activeFrame=state.frame;
 }
 const auto generation=owner->cache.Generation(),serial=owner->cancellationSerial;
 auto notify=[&](const auto& token) {need(!NrdBridgeBirth::InMetadataScope(),"typed observer runs after metadata guards have ended");FrameSurvey::RetirementEffects effects;effects.birth=token;effects.object=token->Address();effects.notify=true;FrameSurvey::NotifyRelease(effects);};
 notify(oldPso);need(owner->roles.at(pso).birth==newPso,"delayed old PSO retirement keeps the newborn role");
 notify(oldList);need(owner->lists.at(list).birth==newList&&owner->pendingList==list,"delayed old list retirement keeps the newborn recording and pending owner");
 notify(oldDepth);need(!owner->chainUsers.contains({depth,oldDepth})&&owner->chainUsers.at({depth,newDepth}).contains(list),"delayed old guide retirement removes only its stale reverse pair and preserves the newborn index");
 notify(oldMotion);need(owner->taggedMotion==motion&&owner->taggedMotionBirth==newMotion,"delayed old motion retirement keeps the newborn title tag");
 need(owner->cache.Valid()&&owner->cache.Generation()==generation&&owner->cancellationSerial==serial&&owner->lists.at(list).chain.Complete()&&owner->status.active,"all delayed old notifications leave the current complete profile, epoch and Active state intact");
 notify(newDepth);need(owner->cache.Valid()&&owner->cancellationSerial==serial,"an erroneous live-token notification cannot retire current guides");
 need(registry.RetireCurrentInstance(newDepth,pod,nullptr),"current logical depth epoch retires outside the observer");notify(newDepth);
 need(!owner->cache.Valid()&&owner->cancellationSerial>serial&&!owner->lists.at(list).chain.Valid()&&!owner->status.active&&!owner->pendingList,"matching current guide retirement still invalidates discovery and cancels its current recording");
 need(owner->roles.at(pso).birth==newPso&&owner->lists.at(list).birth==newList,"guide retirement preserves unrelated live role and list identities");
 need(registry.RetireCurrentInstance(newList,pod,nullptr),"current logical list epoch retires");notify(newList);need(!owner->lists.contains(list),"matching current list retirement removes its exact recording");
 need(registry.RetireCurrentInstance(newPso,pod,nullptr),"current logical PSO epoch retires");notify(newPso);need(!owner->roles.contains(pso),"matching current PSO retirement removes its exact role");
 need(registry.RetireCurrentInstance(newMotion,pod,nullptr),"current logical motion epoch retires");notify(newMotion);need(!owner->taggedMotion&&!owner->taggedMotionBirth,"matching current motion retirement clears its exact title tag");
 NrdBridge::Shutdown();hr(h.list->Close());h.errors();FrameSurvey::Shutdown();
 return {{"delayed_old_role",true},{"delayed_old_list",true},{"delayed_old_guide_reverse_pair",true},{"delayed_old_motion_tag",true},{"exact_current_retirement",true},{"logical_metadata_replay",true},{"native_guid_or_final_release_proved",false},{"sdk_called",false},{"debug_layer_errors",0}};
}
J nativeDebugTests(Host& h) {
 auto step=[](const char* phase) {nrdFixtureStage=phase;std::cerr<<"[native-debug] "<<phase<<" checks="<<checks<<std::endl;};step("setup");
 ResTrack_Dx12::nativeSubmission=true;RecordedComputeLease::SetHooksAvailable(true,true);
 ChainHost c(h);std::string error;const auto a=h.list;
 ComPtr<ID3D12CommandQueue> queueB;D3D12_COMMAND_QUEUE_DESC q {};hr(h.dev->CreateCommandQueue(&q,IID_PPV_ARGS(&queueB)));
 struct Destination {ComPtr<ID3D12CommandAllocator> allocator;ComPtr<ID3D12GraphicsCommandList> list;};
 auto makeDestination=[&] {Destination d;hr(h.dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&d.allocator)));hr(h.dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,d.allocator.Get(),nullptr,IID_PPV_ARGS(&d.list)));return d;};
 auto b=makeDestination(),d=makeDestination(),third=makeDestination();
 // Every owner used by an executed list survives failure unwinding until the fixture's queues drain.
 // Private image owners are pinned per submission, then released after that exact observed fence completes.
 struct Cleanup {
  std::array<ID3D12CommandQueue*,2> queues;ComPtr<ID3D12Fence> gate,complete;
  struct Pins {RecordedComputeLease::FencePointPtr point;std::vector<std::shared_ptr<void>> owners;};std::vector<Pins> pending;
  void Prepare() {
   pending.emplace_back();auto& owners=pending.back().owners;
   for(const auto& [wrapper,image]:fixtureNativeImages)if(image.owner)owners.push_back(image.owner);
   std::array<std::shared_ptr<NrdBridge::NativeDebugSource>,4> sources;
   {std::scoped_lock lock(NrdBridge::gMutex);if(NrdBridge::gService)sources=NrdBridge::gService->nativeDebugSources;}
   for(const auto& source:sources)if(source&&source->image.owner)owners.push_back(source->image.owner);
  }
  void Published(const std::shared_ptr<RecordedComputeLease::Submission>& submission) {if(submission)pending.back().point=submission->point;}
  void Completed(const std::shared_ptr<RecordedComputeLease::Submission>& submission) {std::erase_if(pending,[&](const auto& pin){return pin.point&&pin.point==submission->point;});}
  ~Cleanup() {
   if(!complete)return; // Failed setup has executed no GPU work.
   if(gate)gate->Signal(1);
   UINT64 point=0;for(auto* queue:queues) {
    const auto signaled=queue->Signal(complete.Get(),++point);
    if(FAILED(signaled)){std::cerr<<"[native-debug] cleanup queue Signal failed HRESULT="<<uint32_t(signaled)<<std::endl;continue;}
    const auto deadline=GetTickCount64()+15000;
    while(complete->GetCompletedValue()<point&&GetTickCount64()<deadline)Sleep(2);
    if(complete->GetCompletedValue()<point)std::cerr<<"[native-debug] cleanup queue drain timed out point="<<point<<std::endl;
   }
   pending.clear(); // This can release real images/callback owners only after both queues have completed.
  }
 } cleanup {{h.queue.Get(),queueB.Get()}};
 hr(h.dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&cleanup.complete))); // Allocated before any Execute.
 auto sourceCount=[&] {std::scoped_lock lock(NrdBridge::gMutex);return std::count_if(NrdBridge::gService->nativeDebugSources.begin(),NrdBridge::gService->nativeDebugSources.end(),[](const auto& source){return bool(source);});};
 auto resetDestination=[&](Destination& dest) {hr(dest.allocator->Reset());hr(dest.list->Reset(dest.allocator.Get(),nullptr));};
 auto submit=[&](ID3D12CommandQueue* queue,ID3D12GraphicsCommandList* list) {
  RecordedComputeLease::SubmissionDecision decision;
  const auto before=ResTrack_Dx12::nativeExecutes;cleanup.Prepare();
  auto s=ResTrack_Dx12::SubmitNativeForTesting(queue,list,decision);cleanup.Published(s);
  need(decision.allowed&&s&&s->signalPublished&&s->point&&s->point->IsPublished(),"actual ledger publishes a successful exact native fence point");
  need(ResTrack_Dx12::nativeExecutes==before+1,"allowed native submission executes the original title list exactly once");return s;
 };
 auto finish=[&](const auto& s) {await([&]{return s->point->fence->GetCompletedValue()>=s->point->value;},"native debug submission GPU completion");RecordedComputeLease::Poll();cleanup.Completed(s);};
 auto next=[&] {h.list=a;++StreamlineHooks::frame;c.frame(3);};
 auto finishA=[&] {hr(a->Close());auto s=submit(h.queue.Get(),a.Get());finish(s);h.list=a;h.reset();};
 auto present=[&](ID3D12GraphicsCommandList* list,D3D12_RESOURCE_STATES state=D3D12_RESOURCE_STATE_UNORDERED_ACCESS) {error.clear();return NrdBridge::PresentNativeDebug(list,c.textures[7].Get(),state,error);};
 {std::scoped_lock state(NrdBridge::gMutex);std::scoped_lock injection(NrdBridge::gInjectionMutex);
  need(!present(a.Get())&&error.empty(),"default native-debug OFF returns without either coordinator mutex");}
 step("default OFF and baseline");
 need(nativeSnapshotCalls==0&&nativePresentPreparations==0&&fixtureNativeImages.empty(),"default OFF allocates no native image and prepares no debug work");
 next();
 const auto discovery=RecordedComputeLease::Capture(a.Get());const auto discoveryCallbacks=ResTrack_Dx12::leases.find(a.Get());
 need(!discovery&&(discoveryCallbacks==ResTrack_Dx12::leases.end()||discoveryCallbacks->second.empty())&&!NrdBridge::gService->lists.at(a.Get()).recording&&NrdBridge::GetStatus().framesBridged==0&&convertCalls==0&&rrCalls==0,"first discovery-only title list has recording ordinal zero, no callbacks and no private bridge work");
 hr(a->Close());RecordedComputeLease::SubmissionDecision discoveryDecision;const auto discoveryExecutes=ResTrack_Dx12::nativeExecutes;
 const auto titleOnly=ResTrack_Dx12::SubmitNativeForTesting(h.queue.Get(),a.Get(),discoveryDecision);
 need(discoveryDecision.allowed&&!titleOnly&&ResTrack_Dx12::nativeExecutes==discoveryExecutes+1,"discovery-only original title Execute remains exactly once with no fabricated participant ledger point");
 hr(h.queue->Signal(h.fence.Get(),++h.tick));await([&]{return h.fence->GetCompletedValue()>=h.tick;},"independent actual title-only fence completes before reset");h.list=a;h.reset();
 next();need(NrdBridge::GetStatus().active,"native-debug process establishes a baseline admitted frame");finishA();
 need(nativeSnapshotCalls==0&&fixtureNativeImages.empty()&&sourceCount()==0,"ordinary RR with debug OFF does not query or retain a diagnostic image");
 step("same-recording native image");
 NrdBridge::RRSettings settings;settings.nativeDebugView=0;
 need(NrdBridge::ApplyRRSettings(settings,false,error)&&NrdBridge::NativeDebugEnabled(),"native overview mode enables only the explicit diagnostic path");
 need(!present(a.Get())&&error.empty(),"startup without a native debug source is a quiet skip");
 next();need(NrdBridge::GetStatus().active&&sourceCount()==1,"successful native-mode RR admission captures one owned diagnostic image");
 const auto sameFrame=StreamlineHooks::frame;const auto frames=NrdBridge::GetStatus().framesBridged;const auto rrBefore=rrCalls;
 const auto restore=D3D12Hooks::restores;
 need(present(a.Get())&&!lastNativeOrdered&&lastNativeSourceSL==sameFrame,"same actual recording presents without a cross-list fence claim");
 need(present(a.Get())&&!lastNativeOrdered&&lastNativeSourceSL==sameFrame,"second same-recording presentation follows the same image's presentation tail");
 need(nativePresentActions==2&&D3D12Hooks::restores==restore+2&&rrCalls==rrBefore&&NrdBridge::GetStatus().framesBridged==frames,"diagnostic presentation restores compute state and never advances RR/Active accounting");
 need(internalObserved&&trackingSuppressed,"diagnostic recording is scoped internal with title tracking suppressed");finishA();
 step("controlled producer");
 // Mode change clears the old submitted snapshot before the controlled queue experiment.
 settings.nativeDebugView=1;settings.nativeDebugViewport=2;
 need(NrdBridge::ApplyRRSettings(settings,false,error)&&sourceCount()==0,"mode/index change invalidates old diagnostic selectors");
 next();const auto producerSL=StreamlineHooks::frame;
 std::shared_ptr<NrdBridge::NativeDebugSource> producer;
 {std::scoped_lock lock(NrdBridge::gMutex);for(const auto& entry:NrdBridge::gService->nativeDebugSources)if(entry)producer=entry;}
 NativeWaitProbe waitProbe(h.queue.Get(),queueB.Get());
 ComPtr<ID3D12Fence> gate;hr(h.dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));
 cleanup.gate=gate;
 hr(h.queue->Wait(gate.Get(),1));hr(a->Close());auto producerSubmission=submit(h.queue.Get(),a.Get());
 need(producer->recording->completion==producerSubmission->point&&producer->recording->phase.load()==NrdBridge::SubmissionPhase::FencePublished,"per-token publication stores the exact point before advertising FencePublished");
 need(gate->GetCompletedValue()==0&&producerSubmission->point->fence->GetCompletedValue()==0,"producer fence remains unfinished behind the same-thread gate");
 step("newer unsubmitted producer");
 // Record a newer image on a different list, but leave it unsubmitted.
 h.list=d.list;++StreamlineHooks::frame;c.frame(3);
 need(NrdBridge::GetStatus().active&&sourceCount()==2,"newer unsubmitted producer remains a distinct cached source");
 step("select submitted source");
 const auto newerSL=StreamlineHooks::frame;h.list=b.list;c.begin();
 need(present(b.list.Get())&&lastNativeSourceSL==producerSL&&lastNativeSourceSL!=newerSL&&lastNativeOrdered,"latest submitted source wins over a newer unsubmitted snapshot");
 // Age out any older source while keeping the selected producer within the four-SL window.
 StreamlineHooks::frame=producerSL+4;h.list=third.list;c.begin();const auto pending=nativePresentPreparations;
 need(!present(third.list.Get())&&error.empty()&&nativePresentPreparations==pending,"unsubmitted presentation on another recording blocks unordered source-image transitions");
 step("submit B with producer dependency");
 hr(b.list->Close());const auto waitsBeforeB=nativeWaitEvents.size();auto bSubmission=submit(queueB.Get(),b.list.Get());
 need(nativeWaitEvents.size()==waitsBeforeB+1&&nativeWaitEvents.back().queue==queueB.Get()&&nativeWaitEvents.back().fence==producerSubmission->point->fence.Get()&&nativeWaitEvents.back().value==producerSubmission->point->value,"native queue B waits for the exact producer token fence before original Execute");
 need(gate->GetCompletedValue()==0&&bSubmission->point->fence->GetCompletedValue()==0,"cross-queue submission returns while the same submitting thread still owns the unopened producer gate");
 step("present and submit C with presentation tail");
 need(present(third.list.Get())&&lastNativeSourceSL==producerSL&&lastNativeOrdered,"published prior presentation admits the next read of the same private image");
 hr(third.list->Close());const auto waitsBeforeThird=nativeWaitEvents.size();auto thirdSubmission=submit(h.queue.Get(),third.list.Get());
 need(nativeWaitEvents.size()==waitsBeforeThird+1&&nativeWaitEvents.back().queue==h.queue.Get()&&nativeWaitEvents.back().fence==bSubmission->point->fence.Get(),"native queue A orders the source-image transition after queue B's exact presentation fence");
 need(gate->GetCompletedValue()==0,"both required GPU edges return before the producer gate is opened");
 step("replay producer after submitted tail");
 const auto waitsBeforeReplay=nativeWaitEvents.size();const auto replayExecutes=ResTrack_Dx12::nativeExecutes;
 auto orderedReplay=submit(queueB.Get(),a.Get());
 need(nativeWaitEvents.size()==waitsBeforeReplay+2&&nativeWaitEvents[waitsBeforeReplay].queue==queueB.Get()&&nativeWaitEvents[waitsBeforeReplay].fence==thirdSubmission->point->fence.Get(),"producer replay GPU-waits for the last submitted presentation tail before rewriting that private image");
 need(nativeWaitEvents[waitsBeforeReplay+1].fence==producerSubmission->point->fence.Get(),"producer replay also preserves the temporal history predecessor edge");
 need(ResTrack_Dx12::nativeExecutes==replayExecutes+1&&gate->GetCompletedValue()==0,"ordered producer replay executes exactly once and returns before the same-thread gate is opened");
 step("open intentional gate and complete all submissions");
 hr(gate->Signal(1));finish(producerSubmission);finish(bSubmission);finish(thirdSubmission);finish(orderedReplay);waitProbe.stop();
 producerSubmission.reset();bSubmission.reset();thirdSubmission.reset();orderedReplay.reset();producer.reset();
 // Reset raw command-list pointers only after their submitted GPU work completes.
 ResTrack_Dx12::ResetForTesting(b.list.Get());NrdBridge::OnReset(b.list.Get(),nullptr);resetDestination(b);
 ResTrack_Dx12::ResetForTesting(third.list.Get());NrdBridge::OnReset(third.list.Get(),nullptr);resetDestination(third);
 hr(d.list->Close());NrdBridge::OnReset(d.list.Get(),nullptr);ResTrack_Dx12::ResetForTesting(d.list.Get());resetDestination(d);
 h.list=a;h.reset();
 next();need(lastRRFrame.reset&&NrdBridge::GetStatus().active,"discarded newer producer recovers through a fresh RESET domain");finishA();
 step("bounded source eviction");
 const auto retiredBefore=nativeImageRetirements;
 for(UINT i=0;i<6;++i){next();need(NrdBridge::GetStatus().active,"submitted diagnostic continuation remains Active");finishA();need(sourceCount()<=4,"native debug source cache is bounded to four successful snapshots");}
 need(sourceCount()==4&&nativeImageRetirements>retiredBefore,"cache eviction releases real private image owners outside the coordinator lock");
 step("reset list identity");
 // Reusing a raw list pointer after Reset requires a published producer point.
 h.list=a;StreamlineHooks::frame+=1;c.begin();
 need(present(a.Get())&&lastNativeOrdered,"Reset of the same raw command-list pointer uses exact fence ordering rather than same-recording identity");finishA();
 step("final admission cancellation");
 next();const auto canceledFrames=NrdBridge::GetStatus().framesBridged;const auto failures=NrdBridge::gService->failures;
 const auto actions=nativePresentActions;beforeDebugAdmissionForTesting=+[]{NrdBridge::RequestHistoryReset();};
 need(!present(a.Get())&&error.empty(),"normal reset at the final presentation gate quietly rejects prepared output commands");beforeDebugAdmissionForTesting=nullptr;
 need(nativePresentActions==actions&&NrdBridge::GetStatus().framesBridged==canceledFrames&&!NrdBridge::GetStatus().active&&NrdBridge::gService->failures==failures,"canceled presentation touches no target/action and spends no RR success or failure accounting");
 hr(a->Close());h.list=a;h.reset();next();need(NrdBridge::GetStatus().active&&lastRRFrame.reset,"presentation cancellation recovers on the next coherent Recon with RESET");finishA();
 step("runtime OFF and recovery");
 const auto disabledActions=nativePresentActions;NrdBridge::SetRuntimeEnabled(false);
 {std::scoped_lock state(NrdBridge::gMutex);std::scoped_lock injection(NrdBridge::gInjectionMutex);need(!present(a.Get())&&error.empty(),"runtime OFF diagnostic fast path acquires no coordinator locks");}
 need(sourceCount()==0&&nativePresentActions==disabledActions&&!NrdBridge::NativeDebugEnabled(),"runtime OFF clears cached images and records no presentation");
 NrdBridge::SetRuntimeEnabled(true);next();need(lastRRFrame.reset&&NrdBridge::GetStatus().active,"runtime ON restores one fresh coherent producer");finishA();
 step("age and wrap");
 const auto expiredPreparations=nativePresentPreparations;StreamlineHooks::frame+=5;h.list=b.list;c.begin();
 need(!present(b.list.Get())&&error.empty()&&nativePresentPreparations==expiredPreparations,"source beyond the bounded SL age quietly skips without provider preparation");
 StreamlineHooks::frame=UINT32_MAX;need(!present(b.list.Get())&&error.empty(),"unknown SL frame never guesses native debug provenance");
 h.list=a;StreamlineHooks::frame=UINT32_MAX-3;next();finishA();
 StreamlineHooks::frame=0;h.list=b.list;c.begin();
 need(present(b.list.Get())&&lastNativeSourceSL==UINT32_MAX-2&&lastNativeOrdered,"bounded source age crosses uint32 SL wrap using the exact published image");
 hr(b.list->Close());auto wrapped=submit(queueB.Get(),b.list.Get());finish(wrapped);wrapped.reset();
 NrdBridge::OnReset(b.list.Get(),nullptr);ResTrack_Dx12::ResetForTesting(b.list.Get());resetDestination(b);
 step("reentrant private-owner retirement");
 // Last-owner destruction re-enters the real coordinator callback. No fake TLS is used.
 retirementProbeEnabled=true;const auto resetReleases=retirementReleaseCallbacks;
 {auto orphan=NrdBridge::MakeOwnedShared<NrdBridge::HistoryDomain>();std::scoped_lock lock(NrdBridge::gMutex);NrdBridge::gService->lists[b.list.Get()].history=std::move(orphan);}
 NrdBridge::OnReset(b.list.Get(),nullptr);
 need(retirementReleaseCallbacks==resetReleases+1,"OnReset retires the last private history owner outside gMutex so a release callback can re-enter");
 {auto orphan=NrdBridge::MakeOwnedShared<NrdBridge::HistoryDomain>();std::scoped_lock lock(NrdBridge::gMutex);NrdBridge::gService->lists[third.list.Get()].history=std::move(orphan);}
 const auto erasedReleases=retirementReleaseCallbacks;NrdBridge::OnReleased(third.list.Get());
 need(retirementReleaseCallbacks==erasedReleases+1,"OnReleased erases a participant without destroying its last history owner under gMutex");retirementProbeEnabled=false;
 step("final unsubmitted-tail replay denial");
 // A recorded dependent keeps the producer's original point. Resubmission cannot replace that proof.
 StreamlineHooks::frame=100;h.list=a;next();hr(a->Close());auto first=submit(h.queue.Get(),a.Get());finish(first);
 h.list=b.list;c.begin();need(present(b.list.Get())&&lastNativeOrdered,"final dependent records against one exact submitted producer");hr(b.list->Close());
 const auto dependentActions=nativePresentActions;const auto failureBudget=NrdBridge::gService->failures;
 RecordedComputeLease::SubmissionDecision replayDenied;const auto replayExecutesBefore=ResTrack_Dx12::nativeExecutes;
 auto replay=ResTrack_Dx12::SubmitNativeForTesting(h.queue.Get(),a.Get(),replayDenied);
 need(!replayDenied.allowed&&FAILED(replayDenied.orderingFailure)&&ResTrack_Dx12::nativeExecutes==replayExecutesBefore,"unsubmitted presentation tail denies producer replay before any private image rewrite or original Execute");
 RecordedComputeLease::SubmissionDecision denied;const auto nativeExecutes=ResTrack_Dx12::nativeExecutes;
 auto rejected=ResTrack_Dx12::SubmitNativeForTesting(queueB.Get(),b.list.Get(),denied);
 need(!denied.allowed&&FAILED(denied.orderingFailure)&&ResTrack_Dx12::nativeExecutes==nativeExecutes,"producer resubmission invalidates an already-recorded exact-point dependency and denies its original Execute");
 need(nativePresentActions==dependentActions&&NrdBridge::gService->failures==failureBudget&&NrdBridge::GetStatus().phase=="Inactive","GPU ordering denial records no new output and surfaces Inactive without spending the provider retry budget");
 first.reset();replay.reset();rejected.reset();h.list=a;NrdBridge::Shutdown();hr(third.list->Close());hr(d.list->Close());h.errors();FrameSurvey::Shutdown();
 return {{"native_debug_default_off",true},{"latest_submitted_source",true},{"same_recording_order",true},{"per_image_fence_tail",true},
  {"typed_native_fence_publication",true},{"native_queue_wait_edges",4},{"producer_replay_waits_presentation_tail",true},{"unsubmitted_tail_denies_producer_replay",true},{"cache_bound",4},{"native_image_retirements",nativeImageRetirements},
  {"prepared_cancel_no_commit",true},{"raw_pointer_reset_requires_point",true},{"source_resubmit_denies_dependent",true},{"retirement_reentrant_release",true},
  {"rr_stub_calls",rrCalls},{"native_present_preparations",nativePresentPreparations},{"native_present_actions",nativePresentActions},
  {"native_original_executes",ResTrack_Dx12::nativeExecutes},{"sdk_called",false},{"pixel_shader_called",false},{"debug_layer_errors",0}};
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
 const bool settings=argc==3&&std::string(argv[1])=="--settings";
 const bool nativeDebug=argc==3&&std::string(argv[1])=="--native-debug";
 const bool birth=argc==3&&std::string(argv[1])=="--birth-notifications";
 const bool startupFailure=argc==3&&std::string(argv[1])=="--startup-native-failure",startupOff=argc==3&&std::string(argv[1])=="--startup-off-latched";
 const bool startup=startupFailure||startupOff;
 need(argc==2||settings||nativeDebug||birth||startup,"scratch directory argument or explicit fresh-process fixture selector");
 const std::filesystem::path output=(settings||nativeDebug||birth||startup)?argv[2]:argv[1];g_dllPath=output/"fixture.dll";
 Host host;auto result=startup?startupConfigurationTests(host,startupOff):birth?birthNotificationTests(host):nativeDebug?nativeDebugTests(host):settings?settingsTests(host):discoveryTests(host);
 need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled(),"standalone fixture never enables unsupported native retirement or concurrent Release mode");
 need(NrdBridgeNativeBirth::fixtureNativeCoverageRequests.load(std::memory_order_relaxed)==0,"legacy and logical-notification scenarios never request synthetic native Release coverage");
 result["checks_passed"]=checks;result["adapter"]=host.adapter;
 result["native_birth_coverage"]={{"dispatcher_ready",false},{"concurrent_release_gate",false},{"coverage_requests",0},{"physical_release_coverage_proved",false}};
 result["scope"]=startup ? "production startup admission with explicitly failing native initializer; lifecycle/locking control flow only, no physical native Release coverage" : birth ? "production registry typed observer and coordinator exact-token retirement under controlled logical epoch replay; no native GUID/final Release coverage or provider/pixel proof" : nativeDebug ?
  "real D3D12 registry/coordinator, unique private images and actual production lease fence publication/native queue Wait; conversion/RR/presentation pixels/restore are explicit stubs" :
  "real D3D12 registry, binding-window resolution and coordinator; conversion/RR/state-restore callback stubs; typed submission publication is a CPU counter adapter without a GPU fence";
 ResTrack_Dx12::leases.clear(); // Complete fixture-owned stub wrappers before their observation registry is destroyed.
 std::ofstream(output/(startup?(startupOff?"startup-off-latched-result.json":"startup-native-failure-result.json"):birth?"birth-notification-result.json":nativeDebug?"native-debug-result.json":settings?"settings-result.json":"host-result.json"))<<result.dump(2)<<'\n';std::cout<<result.dump()<<'\n';return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


RES_TRACK_STUB = r"""#pragma once
#include <functional>
#include <unordered_map>
#include "misc/RecordedComputeLease_Dx12.h"
struct ResTrack_Dx12 {
 struct Lease { std::shared_ptr<void> payload; std::function<void(ID3D12CommandQueue*)> callback; RecordedComputeLease::SubmissionCallbacks typed; uint64_t ordinal=0; };
 inline static std::unordered_map<ID3D12GraphicsCommandList*,std::vector<Lease>> leases;
 inline static bool retentionAvailable=true,nativeSubmission=false;
 inline static uint64_t nativeExecutes=0;
#ifdef FSRD_FIXTURE_NATIVE_RETIREMENT_METHOD
 inline static std::atomic<unsigned> fixtureNativeConfigurations {0};
 inline static void (*fixtureBeforeNativeConfiguration)() = nullptr;
 static bool ConfigureNrdNativeBirthRetirement() noexcept {
  fixtureNativeConfigurations.fetch_add(1,std::memory_order_relaxed);
  if(fixtureBeforeNativeConfiguration)fixtureBeforeNativeConfiguration();
  return false; // Deliberate present-method failure; no synthetic Ready/Release registration.
 }
#endif
 static bool RetainComputeDispatch(ID3D12Device*,ID3D12GraphicsCommandList* list,const std::shared_ptr<void>& payload,
   std::function<void(ID3D12CommandQueue*)> callback={},RecordedComputeLease::SubmissionCallbacks typed={}) {
  if(!retentionAvailable)return false;
  if(nativeSubmission) {
   Microsoft::WRL::ComPtr<IUnknown> identity;if(FAILED(list->QueryInterface(IID_PPV_ARGS(&identity))))return false;
   if(!RecordedComputeLease::Track(identity.Get(),{list},payload,callback,typed))return false;
  }
  leases[list].push_back({payload,std::move(callback),std::move(typed),0});return true;
 }
 static void ResetForTesting(ID3D12GraphicsCommandList* list) {
  if(nativeSubmission)if(auto recording=RecordedComputeLease::Capture(list))RecordedComputeLease::Detach(recording);
  leases.erase(list);
 }
 static void SubmitForTesting(ID3D12GraphicsCommandList* list) {
  for(auto& lease:leases[list]) {
   RecordedComputeLease::SubmissionInfo info {nullptr,1,1,++lease.ordinal,false};
   if(lease.callback)lease.callback(nullptr);if(lease.typed.beforeSubmit)lease.typed.beforeSubmit(info);
   if(lease.typed.fencePublished)lease.typed.fencePublished(info,{});
  }
 }
 static std::shared_ptr<RecordedComputeLease::Submission> SubmitNativeForTesting(ID3D12CommandQueue* queue,
   ID3D12GraphicsCommandList* list,RecordedComputeLease::SubmissionDecision& decision) {
  Microsoft::WRL::ComPtr<IUnknown> identity;
  if(FAILED(list->QueryInterface(IID_PPV_ARGS(&identity))))return {};
  const auto submission=RecordedComputeLease::BeforeSubmission(queue,std::vector<IUnknown*>{identity.Get()},&decision);
  if(!decision.allowed)return submission;
  ID3D12CommandList* base=list;queue->ExecuteCommandLists(1,&base);++nativeExecutes;
  RecordedComputeLease::AfterSubmission(submission);return submission;
 }
};
"""

def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/12a-discovery/tests/discovery'))
    output.mkdir(parents=True, exist_ok=True)
    stubs = output / 'stubs'
    for folder in ('proxies', 'inputs', 'hooks', 'resource_tracking'):
        (stubs / folder).mkdir(parents=True, exist_ok=True)
    (stubs / 'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#include <memory>\ninline void FlushLogger() noexcept {}\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs / 'Logger.h').write_text('#pragma once\nvoid FlushLogger() noexcept;\n')
    # The native temporal/material headers only carry State.h transitively; the
    # real State.h pulls Vulkan/Streamline/GameTrace dependencies that this
    # coordinator-only fixture does not exercise.
    (stubs / 'State.h').write_text('#pragma once\n')
    (stubs / 'Util.h').write_text('#pragma once\n#include <filesystem>\n#include <d3d12.h>\ninline std::filesystem::path g_dllPath;\nnamespace Util { inline bool CheckForRealObject(std::string,IUnknown*,IUnknown**) { return false; } inline std::filesystem::path DllPath() { return g_dllPath; } inline std::filesystem::path ExePath() { return L"cyberpunk2077.exe"; } inline void GetDeviceRemovedReason(ID3D12Device*) {} }\n')
    (stubs / 'Config.h').write_text('#pragma once\ntemplate<class T> struct FixtureOptional { T value; unsigned volatileWrites=0; bool volatileValue=false; T value_or_default() const { return value; } void set_volatile_value(const T& next) { value=next; volatileValue=true; ++volatileWrites; } };\nstruct Config { FixtureOptional<bool> FfxDenoiserNrdBridge {false}, FfxDenoiserNrdBridgeEnabled {true}, RestoreComputeSignature {false}, ExtendedStateRestore {false}; static Config* Instance() { static Config config; return &config; } };\n')
    (stubs / 'hooks/D3D12_Hooks.h').write_text('#pragma once\n#include "Config.h"\nstruct D3D12Hooks { inline static bool tracking=true, canRestore=true; inline static unsigned restores=0; inline static FrameSurvey::ComputeBindings current {}; static bool GetComputeBindingsForBridge(ID3D12GraphicsCommandList*,FrameSurvey::ComputeBindings& out) noexcept { out=current; return out.root && !out.heaps.empty(); } static void SetRootSignatureTracking(bool enabled) { tracking=enabled; } static bool RootSignatureTrackingEnabled() { return tracking; } static bool CanRestoreRootSignature(ID3D12GraphicsCommandList*) { return canRestore && Config::Instance()->RestoreComputeSignature.value_or_default() && Config::Instance()->ExtendedStateRestore.value_or_default(); } static void RestoreRoot(ID3D12GraphicsCommandList*) { ++restores; } static void OnBridgeOpaqueCommand(ID3D12GraphicsCommandList*, bool) noexcept {} };\n')
    (stubs / 'hooks/Streamline_Hooks.h').write_text('#pragma once\n#include <sl_consts.h>\nstruct SLConstantsSnapshot { sl::Constants constants {}; uint32_t frameIndex=UINT32_MAX, viewport=UINT32_MAX; };\nstruct StreamlineHooks { inline static uint32_t frame=0; static SLConstantsSnapshot getSLConstantsSnapshot() { SLConstantsSnapshot result; result.frameIndex=frame; return result; } };\n')
    (stubs / 'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs / 'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy { inline auto D3D12CreateVersionedRootSignatureDeserializer_() { return &D3D12CreateVersionedRootSignatureDeserializer; } inline auto D3D12SerializeVersionedRootSignature_() { return &D3D12SerializeVersionedRootSignature; } }\n')
    (stubs / 'resource_tracking/ResTrack_dx12.h').write_text(RES_TRACK_STUB)
    host = '#define FSRD_NRD_BRIDGE_TEST\n' + survey_fixture.CPP.split('// GetStatus()')[0]
    assertion = 'void need(bool ok,const char* msg) { if (!ok) throw std::runtime_error(msg); ++checks; }'
    diagnostic_assertion = 'const char* nrdFixtureStage="setup";\nvoid need(bool ok,const char* msg) { if (!ok) { std::cerr<<"[FSRD_ASSERT] stage="<<nrdFixtureStage<<" checks="<<checks<<" message="<<msg<<std::endl; throw std::runtime_error(msg); } ++checks; }'
    assert host.count(assertion) == 1
    host = host.replace(assertion, diagnostic_assertion)
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
    libraries = ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib', str(detours))
    includes = (stubs, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann', ROOT / 'external/nvngx_dlss_sdk', ROOT / 'external/streamline', ROOT / 'external/streamline1', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api', ROOT / 'external/spdlog/include')
    compile_cpp(source, executable, libraries, includes)
    if os.environ.get('FSRD_NRD_DISCOVERY_NATIVE_DEBUG_ONLY') == '1':
        subprocess.run([str(executable), '--native-debug', str(output)], check=True, timeout=60, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        result = json.loads((output / 'native-debug-result.json').read_text())
        result['execution_scope'] = 'targeted native-debug process only; full discovery/settings/birth/startup/replay suite not run'
        (output / 'targeted-native-debug-result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'native_debug_checks_passed': result['checks_passed'], 'execution_scope': result['execution_scope']}))
        return
    subprocess.run([str(executable), str(output)], check=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result = json.loads((output / 'host-result.json').read_text())
    subprocess.run([str(executable), '--settings', str(output)], check=True, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    settings = json.loads((output / 'settings-result.json').read_text())
    result['settings'] = settings
    result['settings_checks_passed'] = settings['checks_passed']
    subprocess.run([str(executable), '--native-debug', str(output)], check=True, timeout=60, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    native_debug = json.loads((output / 'native-debug-result.json').read_text())
    result['native_debug'] = native_debug
    result['native_debug_checks_passed'] = native_debug['checks_passed']
    subprocess.run([str(executable), '--birth-notifications', str(output)], check=True, timeout=60, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    birth = json.loads((output / 'birth-notification-result.json').read_text())
    result['birth_notifications'] = birth
    result['birth_notification_checks_passed'] = birth['checks_passed']
    startup_source = output / 'startup-fixture.cpp'
    startup_source.write_text('#define FSRD_FIXTURE_NATIVE_RETIREMENT_METHOD\n' + source_text, encoding='utf-8')
    startup_executable = output / 'startup-fixture.exe'
    compile_cpp(startup_source, startup_executable, libraries, includes)
    result['startup_configuration'] = {}
    for scenario in ('startup-native-failure', 'startup-off-latched'):
        subprocess.run([str(startup_executable), '--' + scenario, str(output)], check=True, timeout=60, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        result['startup_configuration'][scenario] = json.loads((output / (scenario + '-result.json')).read_text())
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
    print(json.dumps({'checks_passed': result['checks_passed'], 'settings_checks_passed': result['settings_checks_passed'], 'native_debug_checks_passed': result['native_debug_checks_passed'], 'python_checks_passed': 4, 'result': str(output / 'host-result.json')}))


if __name__ == '__main__':
    run()
