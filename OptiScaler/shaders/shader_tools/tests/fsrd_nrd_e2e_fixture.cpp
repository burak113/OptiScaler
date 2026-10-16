// Test template: Python inserts the actual detours and restore functions.
#include "fixture_support.h"
#include <d3d12sdklayers.h>
#include <d3dcompiler.h>
#include <DirectXPackedVector.h>
#include <json.hpp>
#include <array>
#include <fstream>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <source_location>
#include <shared_mutex>
#include <bit>
#include <thread>
#include <unordered_map>
#include <unordered_set>
// The test-only bridge adapters below are declared under this guard; it must be
// visible before the first header include, not only before the .cpp include.
#define FSRD_NRD_BRIDGE_TEST
#include "__ROOT__/OptiScaler/hooks/Hook_Utils.h"
#include "__ROOT__/OptiScaler/include/detours/detours.h"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeTitleCallbacks_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
#include "hooks/D3D12_Hooks.h"
using Microsoft::WRL::ComPtr;
using J=nlohmann::json;
unsigned checks=0,restores=0;
std::function<void()> emitDebug;
void need(bool value,const char* message) { if(!value) throw std::runtime_error(message); ++checks; }
void RecordTestProviderWrites(ID3D12GraphicsCommandList*,ID3D12Resource*,ID3D12Resource*) { throw std::runtime_error("End-to-end fixture requires real signed provider work"); }
void RecordTestProviderDebugWrites(ID3D12GraphicsCommandList*,ID3D12Resource*,uint32_t,uint32_t) { throw std::runtime_error("End-to-end fixture requires real signed provider debug work"); }
void hr(HRESULT code,const std::source_location& location=std::source_location::current()) {
 if(FAILED(code)) {
  if(emitDebug) emitDebug();
  throw std::runtime_error("D3D12 HRESULT "+std::to_string(uint32_t(code))+" at "+location.file_name()+":"+std::to_string(location.line()));
 }
}
ID3D12GraphicsCommandList* requestedList=nullptr;
std::unordered_map<uint64_t,std::array<unsigned,2>> detourDispatches;
std::unordered_set<ID3D12Resource*> titleTextures;
unsigned internalBarriers=0,titleTransitions=0;
void auditBarriers(ID3D12GraphicsCommandList*,UINT count,const D3D12_RESOURCE_BARRIER* barriers,bool internal) {
 if(!internal) return;
 for(UINT i=0;i<count;++i) {
  ++internalBarriers;
  if(barriers[i].Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION && titleTextures.contains(barriers[i].Transition.pResource)) ++titleTransitions;
 }
}
void recordDispatch(ID3D12GraphicsCommandList* list,bool internal) { ++detourDispatches[uint64_t(list)][internal?1:0]; }
// Config-wiring witness: every SetPipelineState through the real detour chain,
// including bridge-internal decode work. The caller scopes the map per window.
std::unordered_map<const void*,unsigned> gPipelineStateUses;
void noteGpuPipelineState(ID3D12GraphicsCommandList*,ID3D12PipelineState* pso) { if(pso) ++gPipelineStateUses[pso]; }
bool gSurveyDeviceWrappers=false,gNrdBridgeDeviceWrappers=false;
__STATE__
__TRACKERS__
__CONTROL__
namespace Wiring {
bool gSurveyWrappers=false,gNrdBridgeWrappers=false;
using ResetFn=HRESULT(WINAPI*)(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);
using DispatchFn=void(WINAPI*)(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
ResetFn o_Reset=nullptr;
DispatchFn o_Dispatch=nullptr;
using BarrierFn=void(WINAPI*)(ID3D12GraphicsCommandList*,UINT,const D3D12_RESOURCE_BARRIER*);
BarrierFn o_ResourceBarrier=nullptr;
PFN_SetPipelineState o_SetPipelineState=nullptr;
PFN_SetComputeRootDescriptorTable o_SetComputeRootDescriptorTable=nullptr;
HRESULT hkReset(ID3D12GraphicsCommandList* list,ID3D12CommandAllocator* allocator,ID3D12PipelineState* pso) {
 return o_Reset(list,allocator,pso);
}
void hkSetPipelineState(ID3D12GraphicsCommandList* list,ID3D12PipelineState* pso) { o_SetPipelineState(list,pso); }
void hkSetComputeRootDescriptorTable(ID3D12GraphicsCommandList* list,UINT index,D3D12_GPU_DESCRIPTOR_HANDLE table) {
 o_SetComputeRootDescriptorTable(list,index,table);
}
void hkDispatch(ID3D12GraphicsCommandList* list,UINT x,UINT y,UINT z) { o_Dispatch(list,x,y,z); }
void hkResourceBarrier(ID3D12GraphicsCommandList* list,UINT count,const D3D12_RESOURCE_BARRIER* barriers) { o_ResourceBarrier(list,count,barriers); }
__WIRING__
void Attach(ID3D12GraphicsCommandList* list) {
 __SELECTORS__
 auto** table=*reinterpret_cast<void***>(list);
 o_SetPipelineState=reinterpret_cast<PFN_SetPipelineState>(table[25]);
 o_SetComputeRootDescriptorTable=reinterpret_cast<PFN_SetComputeRootDescriptorTable>(table[31]);
 o_Dispatch=reinterpret_cast<DispatchFn>(table[14]); o_Reset=reinterpret_cast<ResetFn>(table[10]);
 o_ResourceBarrier=reinterpret_cast<BarrierFn>(table[26]);
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __RES_ATTACH__
 need(DetourTransactionCommit()==NO_ERROR,"actual ResTrack compute detours attached");
}
void Detach() {
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __RES_DETACH__
 need(DetourTransactionCommit()==NO_ERROR,"actual ResTrack compute detours detached");
}
}
void AttachRoots(ID3D12GraphicsCommandList* list) {
 __DEVICE_SELECTORS__
 auto** table=*reinterpret_cast<void***>(list);
 s_SetPipelineState.o_earlyHook=reinterpret_cast<PFN_SetPipelineState>(table[25]);
 s_SetDescriptorHeaps.o_earlyHook=reinterpret_cast<PFN_SetDescriptorHeaps>(table[28]);
 s_SetComputeRootSignature.o_earlyHook=reinterpret_cast<PFN_SetComputeRootSignature>(table[29]);
 s_SetComputeRootDescriptorTable.o_earlyHook=reinterpret_cast<PFN_SetComputeRootDescriptorTable>(table[31]);
 s_SetComputeRoot32BitConstant.o_earlyHook=reinterpret_cast<PFN_SetComputeRoot32BitConstant>(table[33]);
 s_SetComputeRoot32BitConstants.o_earlyHook=reinterpret_cast<PFN_SetComputeRoot32BitConstants>(table[35]);
 s_SetComputeRootConstantBufferView.o_earlyHook=reinterpret_cast<PFN_SetComputeRootConstantBufferView>(table[37]);
 s_SetComputeRootShaderResourceView.o_earlyHook=reinterpret_cast<PFN_SetComputeRootShaderResourceView>(table[39]);
 s_SetComputeRootUnorderedAccessView.o_earlyHook=reinterpret_cast<PFN_SetComputeRootUnorderedAccessView>(table[41]);
 s_SetGraphicsRootSignature.o_earlyHook=reinterpret_cast<PFN_SetGraphicsRootSignature>(table[30]);
 ReadBridgeGraphicsArgumentHooks(reinterpret_cast<PVOID*>(table),false); // Actual production six-slot installer input.
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __D3D_ATTACH__
 need(DetourTransactionCommit()==NO_ERROR,"actual D3D12 root trackers attached");
 D3D12Hooks::OnBridgeCommandListReset(list,nullptr); // Explicit successful creation/Reset adapter, including known-OFF predication.
}
void DetachRoots() {
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __D3D_DETACH__
 need(DetourTransactionCommit()==NO_ERROR,"actual D3D12 root trackers detached");
}

#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp"
#include "__ROOT__/OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdRawSignals_Dx12.cpp"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgePass_Dx12.cpp"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp"
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
using Role=NrdBridge::Role;
using namespace DirectX;

SLConstantsSnapshot camera(UINT frame,UINT width,UINT height) {
 SLConstantsSnapshot s; s.frameIndex=frame; s.viewport=0; auto& c=s.constants;
 const float y=1.f/std::tan(XM_PI/6.f), aspect=float(width)/height;
 c.cameraViewToClip[0]=sl::float4(y/aspect,0,0,0); c.cameraViewToClip[1]=sl::float4(0,y,0,0);
 c.cameraViewToClip[2]=sl::float4(0,0,0,-1); c.cameraViewToClip[3]=sl::float4(0,0,.01f,0);
 c.cameraPos=sl::float3(0,0,0); c.cameraRight=sl::float3(1,0,0);
 c.cameraUp=sl::float3(0,1,0); c.cameraFwd=sl::float3(0,0,-1);
 c.cameraNear=.01f; c.cameraFar=0; c.cameraFOV=XM_PI/3.f; c.cameraAspectRatio=aspect;
 c.mvecScale=sl::float2(1,1); c.jitterOffset=sl::float2(0,0);
 c.cameraMotionIncluded=sl::Boolean::eTrue; c.motionVectors3D=sl::Boolean::eFalse;
 c.motionVectorsJittered=sl::Boolean::eFalse; c.depthInverted=sl::Boolean::eTrue; c.reset=sl::Boolean::eFalse;
 return s;
}
namespace QueueAudit {
enum class Kind { Wait, Execute, Signal };
struct Event { Kind kind; ID3D12CommandQueue* queue; ID3D12Fence* fence=nullptr; UINT64 value=0; ID3D12CommandList* list=nullptr; };
using FenceFn=HRESULT(WINAPI*)(ID3D12CommandQueue*,ID3D12Fence*,UINT64);
using ExecuteFn=void(WINAPI*)(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*);
FenceFn originalWait=nullptr,originalSignal=nullptr; ExecuteFn originalExecute=nullptr;
std::unordered_set<ID3D12CommandQueue*> observed; std::vector<Event> events;
ID3D12CommandQueue* failSignalQueue=nullptr;ID3D12Fence* signalExemptFence=nullptr;bool failNextSignal=false;unsigned injectedSignalFailures=0;
HRESULT WINAPI Wait(ID3D12CommandQueue* queue,ID3D12Fence* fence,UINT64 value) {
 if(observed.contains(queue)) events.push_back({Kind::Wait,queue,fence,value});
 return originalWait(queue,fence,value);
}
HRESULT WINAPI Signal(ID3D12CommandQueue* queue,ID3D12Fence* fence,UINT64 value) {
 if(observed.contains(queue)) events.push_back({Kind::Signal,queue,fence,value});
 if(failNextSignal && queue==failSignalQueue && fence!=signalExemptFence) {failNextSignal=false;++injectedSignalFailures;return E_FAIL;}
 return originalSignal(queue,fence,value);
}
void WINAPI Execute(ID3D12CommandQueue* queue,UINT count,ID3D12CommandList* const* lists) {
 if(observed.contains(queue)) for(UINT i=0;i<count;++i) events.push_back({Kind::Execute,queue,nullptr,0,lists[i]});
 originalExecute(queue,count,lists);
}
void Attach(ID3D12CommandQueue* a,ID3D12CommandQueue* b) {
 observed={a,b}; events.clear(); auto** va=*reinterpret_cast<void***>(a); auto** vb=*reinterpret_cast<void***>(b);
 need(va[10]==vb[10] && va[14]==vb[14] && va[15]==vb[15],"two native queues share observed Execute/Signal/Wait entries");
 originalExecute=reinterpret_cast<ExecuteFn>(va[10]); originalSignal=reinterpret_cast<FenceFn>(va[14]); originalWait=reinterpret_cast<FenceFn>(va[15]);
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 need(DetourAttach(&(PVOID&)originalExecute,Execute)==NO_ERROR,"native queue Execute observer attached");
 need(DetourAttach(&(PVOID&)originalSignal,Signal)==NO_ERROR,"native queue Signal observer attached");
 need(DetourAttach(&(PVOID&)originalWait,Wait)==NO_ERROR,"native queue Wait observer attached");
 need(DetourTransactionCommit()==NO_ERROR,"native queue observers committed");
}
void Detach() {
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 need(DetourDetach(&(PVOID&)originalExecute,Execute)==NO_ERROR,"native queue Execute observer detached");
 need(DetourDetach(&(PVOID&)originalSignal,Signal)==NO_ERROR,"native queue Signal observer detached");
 need(DetourDetach(&(PVOID&)originalWait,Wait)==NO_ERROR,"native queue Wait observer detached");
 need(DetourTransactionCommit()==NO_ERROR,"native queue observers detached"); observed.clear();
}
}
struct SubmissionProbe {
 RecordedComputeLease::FencePointPtr point; unsigned before=0,published=0,failed=0; uint64_t ordinal=0;
 void attach(ID3D12Device* device,ID3D12GraphicsCommandList* list) {
  RecordedComputeLease::SubmissionCallbacks callbacks;
  callbacks.beforeSubmit=[this](const RecordedComputeLease::SubmissionInfo& info) { ++before;ordinal=info.recordingSubmission;return true; };
  callbacks.fencePublished=[this](const RecordedComputeLease::SubmissionInfo& info,const RecordedComputeLease::FencePointPtr& next) { ordinal=info.recordingSubmission;++published;point=next; };
  callbacks.failed=[this](const RecordedComputeLease::SubmissionInfo&,RecordedComputeLease::SubmissionFailure) { ++failed; };
  need(ResTrack_Dx12::RetainComputeDispatch(device,list,std::make_shared<unsigned>(1),{},std::move(callbacks)),"submission probe uses typed callbacks in actual production ledger");
 }
};
struct Host {
 ComPtr<ID3D12Device> device; ComPtr<ID3D12GraphicsCommandList> list;
 ComPtr<ID3D12CommandAllocator> allocator; ComPtr<ID3D12CommandQueue> queue;
 ComPtr<ID3D12Fence> fence; ComPtr<ID3D12InfoQueue> info;
 std::vector<ComPtr<ID3D12Resource>> uploads;
 UINT64 tick=0; unsigned denied=0;HRESULT lastOrderingFailure=S_OK; std::string adapter;
 Host() {
  ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))); debug->EnableDebugLayer();
  ComPtr<IDXGIFactory6> factory; hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
  ComPtr<IDXGIAdapter1> chosen;
  for(UINT i=0;;++i) {
   ComPtr<IDXGIAdapter1> a;
   if(factory->EnumAdapterByGpuPreference(i,DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,IID_PPV_ARGS(&a))==DXGI_ERROR_NOT_FOUND) break;
   DXGI_ADAPTER_DESC1 d{}; hr(a->GetDesc1(&d));
   if(d.VendorId==0x1002 && !(d.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)) { chosen=a; break; }
  }
  need(bool(chosen),"AMD hardware required"); DXGI_ADAPTER_DESC1 ad{}; hr(chosen->GetDesc1(&ad));
  for(const auto c:ad.Description) { if(!c) break; adapter.push_back(c<128?char(c):'?'); }
  hr(D3D12CreateDevice(chosen.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device))); hr(device.As(&info));
  emitDebug=[this] {
   for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
    SIZE_T bytes=0; info->GetMessage(i,nullptr,&bytes); std::vector<uint8_t> data(bytes);
    auto* m=reinterpret_cast<D3D12_MESSAGE*>(data.data()); info->GetMessage(i,m,&bytes);
    std::cerr<<"D3D12 message severity="<<m->Severity<<" id="<<m->ID<<" "<<m->pDescription<<'\n';
   }
  };
  D3D12_COMMAND_QUEUE_DESC q{}; hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
  hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
  hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
  D3D12Hooks::OnBridgeCommandListReset(list.Get(),nullptr);
  hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
  RecordedComputeLease::SetHooksAvailable(true,true);
 }
 struct Stream {
  ComPtr<ID3D12GraphicsCommandList> list; ComPtr<ID3D12CommandAllocator> allocator;
  ComPtr<ID3D12CommandQueue> queue; ComPtr<ID3D12Fence> fence;
  std::vector<ComPtr<ID3D12Resource>> uploads; UINT64 tick=0;
 };
 Stream newStream(bool newQueue) {
  Stream stream; if(newQueue) { D3D12_COMMAND_QUEUE_DESC q{}; hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&stream.queue))); } else stream.queue=queue;
  hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&stream.allocator)));
  hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,stream.allocator.Get(),nullptr,IID_PPV_ARGS(&stream.list)));
  D3D12Hooks::OnBridgeCommandListReset(stream.list.Get(),nullptr);
  hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&stream.fence))); return stream;
 }
 void exchange(Stream& stream) {
  std::swap(list,stream.list); std::swap(allocator,stream.allocator); std::swap(queue,stream.queue);
  std::swap(fence,stream.fence); std::swap(uploads,stream.uploads); std::swap(tick,stream.tick); requestedList=list.Get();
 }
 void submit(bool wait=true) { hr(list->Close());need(executeClosed(wait),"production submission decision allows normal original title Execute"); }
 bool executeClosed(bool wait=true) {
  RecordedComputeLease::SubmissionDecision decision;ID3D12CommandList* cmd=list.Get();
  auto pending=ResTrack_Dx12::BeforeComputeSubmission(queue.Get(),1,&cmd,&decision);
  if(!decision.allowed) {++denied;lastOrderingFailure=decision.orderingFailure;
   const auto status=NrdBridge::GetStatus();
   std::cerr<<"title submission denied required="<<std::hex<<RecordedComputeLease::RequiredSubmissionFailure()
    <<" decision="<<decision.orderingFailure<<std::dec<<" denied="<<denied<<" bridged="<<status.framesBridged
    <<" phase="<<status.phase<<" reason="<<status.reason<<std::endl;return false;}
  queue->ExecuteCommandLists(1,&cmd); RecordedComputeLease::AfterSubmission(pending);
  hr(queue->Signal(fence.Get(),++tick)); if(wait) waitComplete();return true;
 }
 void waitComplete() {
  const auto end=GetTickCount64()+60000;
  while(fence->GetCompletedValue()<tick && GetTickCount64()<end) Sleep(1);
  need(fence->GetCompletedValue()>=tick,"GPU completed every recorded title/injection command"); RecordedComputeLease::Poll();
 }
 void reset() {
  const auto old=RecordedComputeLease::Capture(list.Get());
  hr(allocator->Reset()); hr(list->Reset(allocator.Get(),nullptr)); RecordedComputeLease::Detach(old); uploads.clear();
 }
 ComPtr<ID3D12Resource> buffer(UINT64 bytes,D3D12_HEAP_TYPE type,D3D12_RESOURCE_STATES state,bool uav=false) {
  D3D12_HEAP_PROPERTIES hp{}; hp.Type=type;
  D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; d.Width=std::max(UINT64(256),bytes);
  d.Height=d.DepthOrArraySize=d.MipLevels=d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  d.Flags=uav?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE;
  ComPtr<ID3D12Resource> r;
  const auto initial=type==D3D12_HEAP_TYPE_DEFAULT?D3D12_RESOURCE_STATE_COMMON:state;
  hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,initial,nullptr,IID_PPV_ARGS(&r)));
  if(initial!=state) barrier(r.Get(),initial,state);
  return r;
 }
 ComPtr<ID3D12Resource> upload(UINT value,UINT64 bytes=256) {
  auto r=buffer(bytes,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ); void* p=nullptr; hr(r->Map(0,nullptr,&p));
  std::fill_n(static_cast<UINT*>(p),size_t(r->GetDesc().Width)/4,value); r->Unmap(0,nullptr); return r;
 }
 void barrier(ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
  D3D12_RESOURCE_BARRIER b{}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
  b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after}; list->ResourceBarrier(1,&b);
 }
 void uav(ID3D12Resource* r) { D3D12_RESOURCE_BARRIER b{}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV; b.UAV.pResource=r; list->ResourceBarrier(1,&b); }
 std::array<unsigned,2> debugCounts() {
  std::array<unsigned,2> counts{};
  for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
   SIZE_T bytes=0; hr(info->GetMessage(i,nullptr,&bytes)); std::vector<uint8_t> data(bytes);
   auto* m=reinterpret_cast<D3D12_MESSAGE*>(data.data()); hr(info->GetMessage(i,m,&bytes));
   if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR) ++counts[0];
   else if(m->Severity==D3D12_MESSAGE_SEVERITY_WARNING) ++counts[1]; else continue;
   std::cerr<<m->pDescription<<'\n';
  }
  need(counts[0]==0,"D3D12 debug errors absent"); need(counts[1]==0,"D3D12 debug warnings absent"); return counts;
 }
};
const char titleShader[]=R"(
cbuffer Root:register(b0) { uint C0,C1,C2,P3,P4,C5,P6,P7; };
cbuffer BufferValue:register(b6) { uint4 TitleWords[96]; };
cbuffer Extent:register(b8) { uint Width,Height; };
Texture2D<float4> S0:register(t0); Texture2D<float4> S1:register(t1);
Texture2D<float4> S2:register(t2);
#ifdef NATIVE_TEMPORAL_FIXTURE
Texture2D<float> NativeInputZ:register(t3); Texture2D<float> NativeCurrentZ:register(t4);
RWTexture2D<float> NativeOutputZ:register(u2);
#endif
SamplerState Samp:register(s0);
StructuredBuffer<uint> RootSRV:register(t0,space1);
RWStructuredBuffer<uint> Checks:register(u0,space1);
RWTexture2D<float4> U0:register(u0); RWTexture2D<float4> U1:register(u1);
float3 ConsumerRGB(float3 c) {
 if(TitleWords[75].w==0) return c;
 return max(float3(c.x-c.z+c.y,c.x+c.z,c.x-c.z-c.y),0);
}
[numthreads(8,8,1)] void main(uint3 p:SV_DispatchThreadID) {
 if(any(p.xy>=uint2(Width,Height))) return;
#ifdef NATIVE_TEMPORAL_FIXTURE
 if(ROLE==3) NativeOutputZ[p.xy]=max(abs(NativeInputZ.Load(int3(p.xy,0))),1e-6);
#endif
 if(ROLE==2) { U0[p.xy]=S0.Load(int3(p.xy,0)); U1[p.xy]=S1.Load(int3(p.xy,0)); }
 if(ROLE==9) { U0[p.xy]=float4(.75,.5,.25,9); U1[p.xy]=float4(.625,.375,.125,11); }
 if(all(p.xy==0)) {
  uint base=ROLE*16; Checks[base+0]=C0; Checks[base+1]=C1; Checks[base+2]=C2; Checks[base+3]=C5;
  Checks[base+4]=TitleWords[0].x; Checks[base+5]=RootSRV[0]; Checks[base+6]=Width; Checks[base+7]=Height;
  Checks[base+8]=(uint)round(S0.Load(int3(0,0,0)).x*65536);
  Checks[base+9]=ROLE; Checks[base+10]=(uint)round(S0.SampleLevel(Samp,float2(.5/Width,.5/Height),0).x*65536);
  InterlockedAdd(Checks[base+11],1);
  if(ROLE==10) { Checks[base+12]=asuint(ConsumerRGB(U0[uint2(0,0)].rgb).x); Checks[base+13]=asuint(ConsumerRGB(U1[uint2(0,0)].rgb).x); Checks[base+15]=TitleWords[75].w; }
  if(ROLE==4) Checks[base+14]=asuint(S2.Load(int3(0,0,0)).x);
#ifdef NATIVE_TEMPORAL_FIXTURE
  if(ROLE==4) Checks[base+12]=asuint(NativeCurrentZ.Load(int3(0,0,0)));
#endif
 }
})";
struct Readback {
 ComPtr<ID3D12Resource> resource;
 D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
 UINT width=0,height=0;
 std::vector<uint16_t> signal() const {
  void* p=nullptr; hr(resource->Map(0,nullptr,&p)); std::vector<uint16_t> result(size_t(width)*height*4);
  for(UINT y=0;y<height;++y) std::memcpy(result.data()+size_t(y)*width*4,static_cast<uint8_t*>(p)+size_t(y)*footprint.Footprint.RowPitch,size_t(width)*8);
  resource->Unmap(0,nullptr); return result;
 }
};
struct Title {
 Host& h; UINT width,height,increment=0,codecBits=0; bool registered,tableConstants=false,nativeProfile=false;void (*beforeConsumer)()=nullptr;
 ComPtr<ID3D12Resource> nativeViewDepth; D3D12_RESOURCE_STATES nativeDepthState=D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
 ComPtr<ID3D12RootSignature> root; std::array<ComPtr<ID3D12PipelineState>,11> pso;
 std::array<ComPtr<ID3D12Resource>,13> tex;
 std::array<std::vector<uint16_t>,2> raw;
 ComPtr<ID3D12DescriptorHeap> staging,visible,sampler;
 ComPtr<ID3D12Resource> cb,rootSrv,checksum;
 ~Title() { for(const auto& texture:tex) titleTextures.erase(texture.Get()); if(nativeViewDepth)titleTextures.erase(nativeViewDepth.Get()); }
 Title(Host& host,UINT w,UINT height_,bool metadata,bool tableCbv=false,bool nativeMode=false):h(host),width(w),height(height_),registered(metadata),tableConstants(tableCbv),nativeProfile(nativeMode) {
  D3D12_DESCRIPTOR_RANGE ranges[3]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER,1,0,0,0}};
  D3D12_ROOT_PARAMETER p[8]{}; p[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; p[0].Constants={0,0,8};
  p[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[1].DescriptorTable={1,&ranges[0]};
  p[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV; p[2].Descriptor={6,0};
  p[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV; p[3].Descriptor={0,1};
  p[4].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV; p[4].Descriptor={0,1};
  p[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[5].DescriptorTable={1,&ranges[1]};
  p[6].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; p[6].Constants={8,0,2};
  p[7].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[7].DescriptorTable={1,&ranges[2]};
  D3D12_ROOT_SIGNATURE_DESC desc{8,p,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE}; ComPtr<ID3DBlob> blob,error;
  if(tableConstants) {
   const auto volatileFlags=D3D12_DESCRIPTOR_RANGE_FLAGS(D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE|D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE);
   D3D12_DESCRIPTOR_RANGE1 range1[4]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,volatileFlags,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5,0,0,volatileFlags,0},
    {D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER,1,0,0,D3D12_DESCRIPTOR_RANGE_FLAG_DESCRIPTORS_VOLATILE,0},{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,1,6,0,volatileFlags,0}};
   D3D12_ROOT_PARAMETER1 parameter1[8]{};
   for(UINT i=0;i<8;++i) {
    parameter1[i].ParameterType=p[i].ParameterType;
    if(p[i].ParameterType==D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS) parameter1[i].Constants=p[i].Constants;
    else if(p[i].ParameterType!=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) parameter1[i].Descriptor={p[i].Descriptor.ShaderRegister,p[i].Descriptor.RegisterSpace,D3D12_ROOT_DESCRIPTOR_FLAG_DATA_VOLATILE};
   }
   parameter1[1].DescriptorTable={1,&range1[0]};parameter1[5].DescriptorTable={1,&range1[1]};parameter1[7].DescriptorTable={1,&range1[2]};
   parameter1[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameter1[2].DescriptorTable={1,&range1[3]};
   D3D12_VERSIONED_ROOT_SIGNATURE_DESC versioned{};versioned.Version=D3D_ROOT_SIGNATURE_VERSION_1_1;versioned.Desc_1_1={8,parameter1,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
   hr(D3D12SerializeVersionedRootSignature(&versioned,&blob,&error));
  } else hr(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error));
  hr(h.device->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
  rootSigParameterCount[root.Get()]=8; // Equivalent device creation-hook metadata, isolated from its adapter setup.
  if(registered) FrameSurvey::RootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
  for(UINT role=1;role<11;++role) {
   ComPtr<ID3DBlob> cs; const std::string number=std::to_string(role); D3D_SHADER_MACRO defines[]={{"ROLE",number.c_str()},{nullptr,nullptr},{nullptr,nullptr}};
   if(nativeProfile)defines[1]={"NATIVE_TEMPORAL_FIXTURE","1"};
   const auto result=D3DCompile(titleShader,sizeof(titleShader),nullptr,defines,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&cs,&error);
   if(FAILED(result) && error) std::cerr<<static_cast<const char*>(error->GetBufferPointer())<<'\n'; hr(result);
   D3D12_COMPUTE_PIPELINE_STATE_DESC pd{}; pd.pRootSignature=root.Get(); pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
   hr(h.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso[role])));
   if(registered) { FrameSurvey::PipelineCreated(pso[role].Get(),pd); NrdBridge::RegisterPipelineRoleForTesting(pso[role].Get(),Role(role)); }
  }
  cb=h.upload(0,1536); void* constants=nullptr; hr(cb->Map(0,nullptr,&constants));
  static_cast<UINT*>(constants)[0]=55; cb->Unmap(0,nullptr);
  if(registered) FrameSurvey::ResourceCreated(cb.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
  rootSrv=h.upload(66); checksum=h.buffer(1024,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,true);
  createTextures();
  if(nativeProfile) {
   D3D12_RESOURCE_DESC depth{};depth.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;depth.Width=width;depth.Height=height;depth.DepthOrArraySize=depth.MipLevels=depth.SampleDesc.Count=1;
   depth.Format=DXGI_FORMAT_R32_FLOAT;depth.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
   hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&depth,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&nativeViewDepth)));
   titleTextures.insert(nativeViewDepth.Get());if(registered)FrameSurvey::ResourceCreated(nativeViewDepth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  }
  D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors=64;
  hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&staging))); hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&visible))); hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER; hd.NumDescriptors=1;
  hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&sampler)));
  if(registered) { FrameSurvey::HeapCreated(h.device.Get(),staging.Get()); FrameSurvey::HeapCreated(h.device.Get(),visible.Get()); FrameSurvey::HeapCreated(h.device.Get(),sampler.Get()); }
  D3D12_SAMPLER_DESC sd{}; sd.Filter=D3D12_FILTER_MIN_MAG_MIP_POINT; sd.AddressU=sd.AddressV=sd.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
  sd.MaxLOD=D3D12_FLOAT32_MAX; sd.ComparisonFunc=D3D12_COMPARISON_FUNC_NEVER; h.device->CreateSampler(&sd,sampler->GetCPUDescriptorHandleForHeapStart());
  increment=h.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV); views();
 }
 void createTextures() {
  for(UINT i=0;i<tex.size();++i) {
   const bool read=i==0 || i==1 || i==2 || i==3 || i==6;
   D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width=width; d.Height=height;
   d.DepthOrArraySize=d.MipLevels=d.SampleDesc.Count=1; d.Format=i==2?DXGI_FORMAT_R10G10B10A2_UNORM:i==3?DXGI_FORMAT_R32_FLOAT:DXGI_FORMAT_R16G16B16A16_FLOAT;
   d.Flags=read && i!=6?D3D12_RESOURCE_FLAG_NONE:D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
   if(i==7 || i==8) d.Flags|=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
   D3D12_HEAP_PROPERTIES hp{}; hp.Type=D3D12_HEAP_TYPE_DEFAULT;
   hr(h.device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,read?D3D12_RESOURCE_STATE_COPY_DEST:D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&tex[i])));
   titleTextures.insert(tex[i].Get());
   if(registered) FrameSurvey::ResourceCreated(tex[i].Get(),read?D3D12_RESOURCE_STATE_COPY_DEST:D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
   if(!read) continue;
   const UINT bpp=(i==0 || i==1 || i==6)?8:4; std::vector<uint8_t> data(size_t(width)*height*bpp);
   for(size_t pixel=0;pixel<size_t(width)*height;++pixel) {
    if(i==0 || i==1) {
     const float noise=float((pixel%width+pixel/width)%3)*.00390625f;
     const std::array<float,4> values=i==0?std::array<float,4>{.03125f+noise,.0625f,.015625f,5.f}:std::array<float,4>{.125f,.0625f,.03125f,7.f};
     auto* dst=reinterpret_cast<uint16_t*>(data.data()+pixel*bpp); for(UINT c=0;c<4;++c) dst[c]=PackedVector::XMConvertFloatToHalf(values[c]);
    } else if(i==2) reinterpret_cast<UINT*>(data.data())[pixel]=512u | (512u<<10) | (768u<<20);
    else if(i==3) reinterpret_cast<float*>(data.data())[pixel]=5.f;
   }
   if(i<2) { raw[i].resize(size_t(width)*height*4); std::memcpy(raw[i].data(),data.data(),data.size()); }
   D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 bytes=0; h.device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
   auto up=h.buffer(bytes,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ); void* mapped=nullptr; hr(up->Map(0,nullptr,&mapped));
   for(UINT y=0;y<height;++y) std::memcpy(static_cast<uint8_t*>(mapped)+size_t(y)*fp.Footprint.RowPitch,data.data()+size_t(y)*width*bpp,size_t(width)*bpp);
   up->Unmap(0,nullptr); D3D12_TEXTURE_COPY_LOCATION src{},dst{}; src.pResource=up.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=fp;
   dst.pResource=tex[i].Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
   h.barrier(tex[i].Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE); h.uploads.push_back(up);
  }
 }
 void tableViews(UINT start,std::initializer_list<UINT> ids,bool uav) {
  UINT at=start; for(const auto id:ids) {
   const auto r=tex[id].Get(); D3D12_CPU_DESCRIPTOR_HANDLE handle{staging->GetCPUDescriptorHandleForHeapStart().ptr+uint64_t(at++)*increment};
   if(uav) { D3D12_UNORDERED_ACCESS_VIEW_DESC d{}; d.Format=r->GetDesc().Format; d.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
    h.device->CreateUnorderedAccessView(r,nullptr,&d,handle); if(registered) FrameSurvey::View(r,handle,&d);
   } else { D3D12_SHADER_RESOURCE_VIEW_DESC d{}; d.Format=r->GetDesc().Format; d.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
    d.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; d.Texture2D.MipLevels=1;
    h.device->CreateShaderResourceView(r,&d,handle); if(registered) FrameSurvey::View(r,handle,&d); }
  }
 }
 void views() {
  tableViews(0,{0,1,2,3,0,1,2,3},false); tableViews(8,{4,5,9,10,9},true);
  tableViews(16,{0,1,6,2,3,0,1,2},false); tableViews(24,{9,10,9,10,9},true);
  tableViews(32,{7,8,9,10,9},true); tableViews(40,{11,12,9,10,9},true); tableViews(48,{8,7,9,10,9},true);
  if(nativeProfile) {
   D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.Format=DXGI_FORMAT_R32_FLOAT;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;srv.Texture2D.MipLevels=1;
   const D3D12_CPU_DESCRIPTOR_HANDLE read{staging->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(20)*increment};h.device->CreateShaderResourceView(nativeViewDepth.Get(),&srv,read);if(registered)FrameSurvey::View(nativeViewDepth.Get(),read,&srv);
   D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.Format=DXGI_FORMAT_R32_FLOAT;uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
   const D3D12_CPU_DESCRIPTOR_HANDLE write{staging->GetCPUDescriptorHandleForHeapStart().ptr+UINT64(26)*increment};h.device->CreateUnorderedAccessView(nativeViewDepth.Get(),nullptr,&uav,write);if(registered)FrameSurvey::View(nativeViewDepth.Get(),write,&uav);
  }
 }
 void copyDescriptors() {
  for(const auto& range:std::array<std::array<UINT,2>,7>{{{0,8},{8,5},{16,8},{24,5},{32,5},{40,5},{48,5}}}) {
   const UINT count=range[1]; const D3D12_CPU_DESCRIPTOR_HANDLE src{staging->GetCPUDescriptorHandleForHeapStart().ptr+uint64_t(range[0])*increment};
   const D3D12_CPU_DESCRIPTOR_HANDLE dst{visible->GetCPUDescriptorHandleForHeapStart().ptr+uint64_t(range[0])*increment};
   h.device->CopyDescriptors(1,&dst,&count,1,&src,&count,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
   if(registered) FrameSurvey::CopyDescriptors(h.device.Get(),1,&dst,&count,1,&src,&count,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  }
 }
 void writeDepth(float value) {
  const auto desc=tex[3]->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 bytes=0;
  h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);
  auto up=h.buffer(bytes,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ); void* mapped=nullptr; hr(up->Map(0,nullptr,&mapped));
  std::memset(mapped,0,size_t(bytes));
  for(UINT y=0;y<height;++y) std::fill_n(reinterpret_cast<float*>(static_cast<uint8_t*>(mapped)+size_t(y)*fp.Footprint.RowPitch),width,value);
  up->Unmap(0,nullptr); D3D12_TEXTURE_COPY_LOCATION src{},dst{}; src.pResource=up.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
  dst.pResource=tex[3].Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  h.barrier(tex[3].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
  h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
  h.barrier(tex[3].Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);h.uploads.push_back(up);
 }
 // Left-half/step-right depth pattern for the config-wiring case: reproduces
 // the D04 far-step class so decode tap gates and legacy/camera B provably separate.
 void writeDepthStep(float nearValue,float farValue) {
  const auto desc=tex[3]->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 bytes=0;
  h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);
  auto up=h.buffer(bytes,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ); void* mapped=nullptr; hr(up->Map(0,nullptr,&mapped));
  std::memset(mapped,0,size_t(bytes));
  for(UINT y=0;y<height;++y) {
   auto* row=reinterpret_cast<float*>(static_cast<uint8_t*>(mapped)+size_t(y)*fp.Footprint.RowPitch);
   std::fill_n(row,width/2,nearValue); std::fill_n(row+width/2,width-width/2,farValue);
  }
  up->Unmap(0,nullptr); D3D12_TEXTURE_COPY_LOCATION src{},dst{}; src.pResource=up.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
  dst.pResource=tex[3].Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  h.barrier(tex[3].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);
  h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
  h.barrier(tex[3].Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);h.uploads.push_back(up);
 }
 void setCodec(UINT bits) {
  void* mapped=nullptr; hr(cb->Map(0,nullptr,&mapped)); static_cast<UINT*>(mapped)[303]=bits; cb->Unmap(0,nullptr); codecBits=bits;
 }
 std::array<float,3> decode(const uint16_t* value) const {
  std::array<float,3> c; for(UINT i=0;i<3;++i) c[i]=PackedVector::XMConvertHalfToFloat(value[i]);
  if(codecBits) c={std::max(c[0]-c[2]+c[1],0.f),std::max(c[0]+c[2],0.f),std::max(c[0]-c[2]-c[1],0.f)};
  return c;
 }
 void bindConstants(ID3D12Resource* resource,UINT slot=56,bool observe=true) {
  if(!tableConstants) {h.list->SetComputeRootConstantBufferView(2,resource->GetGPUVirtualAddress());return;}
  const D3D12_CONSTANT_BUFFER_VIEW_DESC view{resource->GetGPUVirtualAddress(),1536};
  const D3D12_CPU_DESCRIPTOR_HANDLE cpu{visible->GetCPUDescriptorHandleForHeapStart().ptr+uint64_t(slot)*increment};
  h.device->CreateConstantBufferView(&view,cpu);if(registered && observe)FrameSurvey::View(cpu,&view);
  h.list->SetComputeRootDescriptorTable(2,{visible->GetGPUDescriptorHandleForHeapStart().ptr+uint64_t(slot)*increment});
 }
 void begin(UINT frame,bool tagMotion=true) {
  StreamlineHooks::snapshot=camera(frame,width,height);
  if(registered && tagMotion) NrdBridge::OnTitleTag(h.list.Get(),"MotionVectors",tex[6].Get());
  auto zero=h.upload(0,1024); h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);
  h.list->CopyBufferRegion(checksum.Get(),0,zero.Get(),0,1024); h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS); h.uploads.push_back(zero);
  h.list->SetComputeRootSignature(root.Get()); ID3D12DescriptorHeap* heaps[]={visible.Get(),sampler.Get()}; h.list->SetDescriptorHeaps(2,heaps);
  const UINT first[]={11,22,30}, dimensions[]={width,height}; h.list->SetComputeRoot32BitConstants(0,3,first,0);
  h.list->SetComputeRoot32BitConstant(0,40,5); h.list->SetComputeRoot32BitConstant(0,33,2);
  bindConstants(cb.Get()); h.list->SetComputeRootShaderResourceView(3,rootSrv->GetGPUVirtualAddress());
  h.list->SetComputeRootUnorderedAccessView(4,checksum->GetGPUVirtualAddress()); h.list->SetComputeRoot32BitConstants(6,2,dimensions,0);
  h.list->SetComputeRootDescriptorTable(7,sampler->GetGPUDescriptorHandleForHeapStart());
 }
 void pass(Role role,UINT uav=24,bool probe=false) {
  if(nativeProfile&&role==Role::PrePass&&nativeDepthState!=D3D12_RESOURCE_STATE_UNORDERED_ACCESS){h.barrier(nativeViewDepth.Get(),nativeDepthState,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);nativeDepthState=D3D12_RESOURCE_STATE_UNORDERED_ACCESS;}
  h.list->SetPipelineState(pso[UINT(role)].Get());
  // PrepLast wakes a new bounded window before title descriptor copies.
  if(role==Role::PrepLast) copyDescriptors();
  h.list->SetComputeRootDescriptorTable(1,{visible->GetGPUDescriptorHandleForHeapStart().ptr+uint64_t(role==Role::Temporal?16:0)*increment});
  h.list->SetComputeRootDescriptorTable(5,{visible->GetGPUDescriptorHandleForHeapStart().ptr+uint64_t(uav)*increment});
  h.list->Dispatch((width+7)/8,(height+7)/8,1); h.uav(checksum.Get());
  if(nativeProfile&&role==Role::PrePass){h.uav(nativeViewDepth.Get());h.barrier(nativeViewDepth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);nativeDepthState=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;}
  if(probe) {
   // No title state is set between the preceding injected RestoreRoot and this GPU check.
   // Bypass coordinator recursion using the real native trampoline, as a separate requested probe dispatch.
   FrameSurvey::ScopedInternal internal; Wiring::o_Dispatch(h.list.Get(),(width+7)/8,(height+7)/8,1); h.uav(checksum.Get());
  }
 }
 void recon(UINT id,bool probe=true,bool tagMotion=true) {
  begin(id,tagMotion); pass(Role::PrepLast); pass(Role::Recon,8,probe); h.uav(tex[4].Get()); h.uav(tex[5].Get());
 }
 void tail(UINT a=3,UINT b=2,bool probe=true) {
  pass(Role::PrePass); pass(Role::Temporal,24,probe); pass(Role::Chain3); pass(Role::HistSave); pass(Role::HistFix); pass(Role::Clamp);
  for(UINT i=0;i<a;++i) { pass(Role::ATrous,i+1==a?32:24); h.uav(tex[i+1==a?7:9].Get()); h.uav(tex[i+1==a?8:10].Get()); }
  pass(Role::PrePass); pass(Role::Temporal); pass(Role::Clamp);
  for(UINT i=0;i<b;++i) { pass(Role::ATrous,40); h.uav(tex[11].Get()); h.uav(tex[12].Get()); }
  h.uav(tex[7].Get()); h.uav(tex[8].Get());if(beforeConsumer)beforeConsumer();pass(Role::Consumer,48);
 }
 void frame(UINT id,UINT a=3,UINT b=2,bool probe=true,bool tagMotion=true) { recon(id,probe,tagMotion); tail(a,b,probe); }
 Readback readback(UINT texture) {
  return readback(tex[texture].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 }
 Readback readback(ID3D12Resource* texture,D3D12_RESOURCE_STATES state) {
  Readback result; const auto d=texture->GetDesc(); result.width=UINT(d.Width); result.height=d.Height; UINT64 bytes=0;
  h.device->GetCopyableFootprints(&d,0,1,0,&result.footprint,nullptr,nullptr,&bytes); result.resource=h.buffer(bytes,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
  if(state!=D3D12_RESOURCE_STATE_COPY_SOURCE) h.barrier(texture,state,D3D12_RESOURCE_STATE_COPY_SOURCE);
  D3D12_TEXTURE_COPY_LOCATION src{},dst{}; src.pResource=texture; src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  dst.pResource=result.resource.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=result.footprint;
  h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
  if(state!=D3D12_RESOURCE_STATE_COPY_SOURCE) h.barrier(texture,D3D12_RESOURCE_STATE_COPY_SOURCE,state);
  return result;
 }
 std::array<ComPtr<ID3D12Resource>,2> replaceOutputs() {
  std::array<ComPtr<ID3D12Resource>,2> old{tex[7],tex[8]};
  for(UINT i=7;i<=8;++i) {
   const auto desc=tex[i]->GetDesc(); D3D12_HEAP_PROPERTIES heap{}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
   ComPtr<ID3D12Resource> next;
   hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&next)));
   tex[i]=next; FrameSurvey::ResourceCreated(next.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
   titleTextures.insert(next.Get());
  }
  views(); return old;
 }
 ComPtr<ID3D12Resource> replaceMotion() {
  auto old=tex[6]; const auto desc=old->GetDesc(); D3D12_HEAP_PROPERTIES heap{}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
  ComPtr<ID3D12Resource> next;
  hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&next)));
  D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 bytes=0; h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);
  auto up=h.upload(0,bytes); D3D12_TEXTURE_COPY_LOCATION src{},dst{};
  src.pResource=up.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=fp;
  dst.pResource=next.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
  h.barrier(next.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE); h.uploads.push_back(up);
  tex[6]=next; titleTextures.insert(next.Get()); FrameSurvey::ResourceCreated(next.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE); views(); return old;
 }
 struct Captured { Readback spec,diff; ComPtr<ID3D12Resource> read; UINT a=3,b=2; bool probe=true; };
 Captured capture(UINT a=3,UINT b=2,bool probe=true) {
  Captured captured{readback(7),readback(8),h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST),a,b,probe};
  auto& read=captured.read;
  h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
  h.list->CopyBufferRegion(read.Get(),0,checksum.Get(),0,1024); h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  return captured;
 }
 std::array<std::vector<uint16_t>,2> validate(const Captured& captured) {
  auto result=std::array<std::vector<uint16_t>,2>{captured.spec.signal(),captured.diff.signal()};
  auto& read=captured.read; const auto a=captured.a,b=captured.b; const auto probe=captured.probe;
  void* data=nullptr; hr(read->Map(0,nullptr,&data)); const auto* words=static_cast<const UINT*>(data);
  for(UINT role=1;role<11;++role) {
   const std::array<UINT,11> wanted={11,22,33,40,55,66,width,height,2048,role,2048};
   need(std::equal(wanted.begin(),wanted.end(),words+role*16),"title GPU sees exact sparse constants, CBV, root SRV/UAV, descriptor and sampler heaps/PSO");
   const UINT count=role==2?(probe?2:1):role==4?(probe?3:2):role==3 || role==8?2:role==9?a+b:1;
   need(words[role*16+11]==count,"each requested title shader executes exactly once, including distinct post-conversion probe");
   if(role==4) need(words[role*16+14]==0,"Temporal and post-motion probe read exactly the current MV descriptor at p1+2");
  }
  need(words[10*16+12]==std::bit_cast<UINT>(decode(result[1].data())[0]) && words[10*16+13]==std::bit_cast<UINT>(decode(result[0].data())[0]),"native Consumer reads and decodes the actual post-injection title outputs");
  need(words[10*16+15]==codecBits,"Consumer observes the GPU execution-time native b6 encoding flag");
  read->Unmap(0,nullptr); return result;
 }
 void validateIncomplete(const Captured& captured) {
  void* mapped=nullptr;hr(captured.read->Map(0,nullptr,&mapped));const auto* words=static_cast<const UINT*>(mapped);
  const std::array<UINT,11> expectedCounts={0,1,2,1,2,0,0,0,0,0,0};
  for(UINT role=1;role<11;++role) {
   need(words[role*16+11]==expectedCounts[role],"conversion-only recording executes exactly its requested original title prefix and both restore probes");
   if(expectedCounts[role]) {
    const std::array<UINT,11> expected={11,22,33,40,55,66,width,height,2048,role,2048};
    need(std::equal(expected.begin(),expected.end(),words+role*16),"incomplete recording still preserves exact title root/heap/PSO GPU bindings");
   }
  }
  captured.read->Unmap(0,nullptr);
 }
 std::array<std::vector<uint16_t>,2> finish(UINT a=3,UINT b=2,bool probe=true) {
  const auto captured=capture(a,b,probe); h.submit(); auto result=validate(captured); h.reset(); return result;
 }
 bool sentinel(const std::array<std::vector<uint16_t>,2>& data) const {
  for(UINT signal=0;signal<2;++signal) {
   const std::array<float,4> values=signal==0?std::array<float,4>{.75f,.5f,.25f,9}:std::array<float,4>{.625f,.375f,.125f,11};
   for(size_t i=0;i<data[signal].size();++i) if(data[signal][i]!=PackedVector::XMConvertFloatToHalf(values[i%4])) return false;
  }
  return true;
 }
 J rawChecks(const std::array<std::vector<uint16_t>,2>& data) const {
  bool rgb=true,alpha=true;
  for(UINT signal=0;signal<2;++signal) for(size_t i=0;i<data[signal].size();i+=4) {
   alpha &= data[signal][i+3]==0;
   if(codecBits) { const auto decoded=decode(data[signal].data()+i); for(UINT c=0;c<3;++c) rgb &= decoded[c]==PackedVector::XMConvertHalfToFloat(raw[signal][i+c]); }
   else for(UINT c=0;c<3;++c) rgb &= data[signal][i+c]==raw[signal][i+c];
  }
  need(rgb,"Raw debug mode copies exact reconstructed half RGB"); need(alpha,"Raw debug mode writes documented zero alpha");
  return {{"exact_rgb",rgb},{"alpha_zero",alpha},{"rgb_values_checked",uint64_t(width)*height*6}};
 }
 J rrChecks(const std::array<std::vector<uint16_t>,2>& data) const {
  UINT64 finite=0,total=0; double sum=0; bool nonnegative=true,alphaNative=true;
  for(UINT id=0;id<2;++id) for(size_t i=0;i<data[id].size();i+=4) {
   for(UINT c=0;c<4;++c) { ++total; if(std::isfinite(PackedVector::XMConvertHalfToFloat(data[id][i+c]))) ++finite; }
   for(const auto value:decode(data[id].data()+i)) { sum+=value; nonnegative &= value>=0 && value<2; }
   alphaNative &= data[id][i+3]==PackedVector::XMConvertFloatToHalf(id==0?9.f:11.f);
  }
  const auto mean=sum/(uint64_t(width)*height*6);
  need(finite==total,"real signed RR output is entirely finite"); need(alphaNative,"real RR RGB commit preserves every native title alpha bit"); need(nonnegative,"synthetic low-radiance RR RGB remains in plausible nonnegative bounds");
  need(mean>.005 && mean<.25,"real RR synthetic mean remains plausible"); need(!sentinel(data),"real RR overwrites native NRD sentinels");
  return {{"finite_values",finite},{"total_values",total},{"mean_rgb",mean},{"rgb_minimum_bound",0},{"rgb_maximum_bound",2},{"native_alpha_preserved",alphaNative},{"gpu_encoding_flag",codecBits}};
 }
};
unsigned internalCalls() { unsigned count=0; for(const auto& [_,value]:detourDispatches) count+=value[1]; return count; }
void disableRestoreFlagsAfterSDK() {
 Config::Instance()->RestoreComputeSignature.value=false; Config::Instance()->ExtendedStateRestore.value=false;
}
ID3D12GraphicsCommandList* tagCallbackList=nullptr;
ID3D12Resource* tagCallbackMotion=nullptr;
void resetAfterSDK() { NrdBridge::RequestHistoryReset(); }
void normalThreadTagAfterSDK() {
 bool normal=false;std::thread ordinary([&] { normal=!FrameSurvey::Internal();NrdBridge::OnTitleTag(tagCallbackList,"MotionVectors",tagCallbackMotion); });ordinary.join();
 need(normal,"concurrent title tag callback runs on a genuine ordinary thread with untouched TLS");
}
void motionEquals(const Readback& read,float z) {
 const auto values=read.signal();bool correct=true;
 const std::array<uint16_t,4> expected={0,0,PackedVector::XMConvertFloatToHalf(z),PackedVector::XMConvertFloatToHalf(1.f)};
 for(size_t i=0;i<values.size();++i)correct &= values[i]==expected[i%4];
 need(correct,"actual GPU motion guide has exact causal XY/depth delta and W=1 across every pixel");
}
Readback motionCapture(Title& title,const ProviderExports::Record& record) {
 need(record.list==title.h.list.Get(),"actual signed provider dispatch targets the requested native command list");
 return title.readback(static_cast<ID3D12Resource*>(record.motion),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
}
void privateGuides(const ProviderExports::Record& a,const ProviderExports::Record& b) {
 need(a.context!=b.context,"overlapping recordings own different live physical signed SDK contexts");
 need(a.spec!=b.spec && a.diff!=b.diff && a.depth!=b.depth && a.motion!=b.motion,"overlapping recordings own disjoint conversion signals, depth and motion guides");
}
struct GateRelease { ComPtr<ID3D12Fence> fence; ~GateRelease() { if(fence) fence->Signal(1); } };
void deepCases(Host& h,Title& title,J& result,std::vector<std::unique_ptr<Title>>& keepTitles) {
 UINT frame=25;J deep;J codec=J::array();
 for(const UINT flag:std::array<UINT,4>{0,1,0x80000000u,0x7fc00000u}) {
  title.setCodec(0);const auto before=FfxApiProxy::dispatches;title.frame(frame++);
  need(FfxApiProxy::dispatches==before+1,"codec fixture records actual signed RR exactly once");
  title.setCodec(flag);const auto stats=title.rrChecks(title.finish());codec.push_back({{"flag_mutated_after_record",flag},{"statistics",stats}});
 }
 deep["gpu_consumer_codec"]=codec;
 title.setCodec(0);NrdBridge::SetDebugMode(NrdBridge::DebugMode::RawSignals);title.frame(frame++);title.setCodec(1);
 deep["gpu_raw_codec"]=title.rawChecks(title.finish());title.setCodec(0);NrdBridge::SetDebugMode(NrdBridge::DebugMode::Off);
 title.frame(frame++);title.rrChecks(title.finish());
 // A reset between real provider recording and output admission must not be republished as Active.
 auto before=NrdBridge::GetStatus();auto calls=FfxApiProxy::dispatches,creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys;
 auto failures=NrdBridge::gService->failures,attempts=NrdBridge::gService->attempts;
 FfxApiProxy::afterRealDispatch=resetAfterSDK;title.frame(frame++);FfxApiProxy::afterRealDispatch=nullptr;
 need(FfxApiProxy::dispatches==calls+1 && FfxApiProxy::destroys==destroys,"cancelled reset SDK work retains its old physical context before submission");
 need(!NrdBridge::GetStatus().active && NrdBridge::GetStatus().framesBridged==before.framesBridged,"post-provider reset cancels title commit and never republishes Active or frames");
 need(NrdBridge::gService->failures==failures && NrdBridge::gService->attempts==attempts,"post-provider reset cancellation spends no failure or retry budget");
 need(title.sentinel(title.finish()),"post-provider reset preserves every title NRD RGBA sentinel bit");
 title.frame(frame++);title.rrChecks(title.finish());
 need(FfxApiProxy::creates==creates+1 && FfxApiProxy::destroys==destroys+1 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"post-provider reset recovers with one fresh physical SDK context and RESET");
 deep["post_provider_reset"]={{"title_rgba_untouched",true},{"active_not_republished",true},{"failure_retry_budget_unchanged",true},{"physical_fresh_recovery",true}};
 // Prepare another live MV without changing the title descriptors seen by this recording.
 const auto originalMotion=title.replaceMotion();const auto nextMotion=title.tex[6];title.tex[6]=originalMotion;title.views();
 tagCallbackList=h.list.Get();tagCallbackMotion=nextMotion.Get();before=NrdBridge::GetStatus();calls=FfxApiProxy::dispatches;creates=FfxApiProxy::creates;destroys=FfxApiProxy::destroys;
 failures=NrdBridge::gService->failures;attempts=NrdBridge::gService->attempts;
 FfxApiProxy::afterRealDispatch=normalThreadTagAfterSDK;title.frame(frame++);FfxApiProxy::afterRealDispatch=nullptr;
 need(FfxApiProxy::dispatches==calls+1 && FfxApiProxy::destroys==destroys,"normal-thread tag cancellation retains the real SDK context through recording");
 need(!NrdBridge::GetStatus().active && NrdBridge::GetStatus().framesBridged==before.framesBridged && !NrdBridge::gService->cache.Valid(),"post-provider ordinary tag invalidation stays Discovering without commit/frame republish");
 need(NrdBridge::gService->failures==failures && NrdBridge::gService->attempts==attempts,"ordinary concurrent tag cancellation spends no failure or retry budget");
 need(title.sentinel(title.finish()),"ordinary concurrent tag after real SDK preserves the complete native NRD RGBA pair");
 title.tex[6]=nextMotion;title.views();title.frame(frame++);need(title.sentinel(title.finish()),"ordinary tag recovery first rediscovers the current resource profile");
 title.frame(frame++);title.rrChecks(title.finish());
 need(FfxApiProxy::creates==creates+1 && FfxApiProxy::destroys==destroys+1 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"ordinary tag recovery retires its old leased SDK context and creates a fresh RESET context");
 deep["post_provider_normal_thread_tag"]={{"untouched_tls",true},{"title_rgba_untouched",true},{"active_not_republished",true},{"failure_retry_budget_unchanged",true},{"physical_fresh_recovery",true}};
 tagCallbackList=nullptr;tagCallbackMotion=nullptr;
 auto alternate=h.newStream(true);const auto checksumA=title.checksum;ComPtr<ID3D12Resource> checksumB;
 const auto interFrames=NrdBridge::GetStatus().framesBridged;const auto interCalls=FfxApiProxy::dispatches;failures=NrdBridge::gService->failures;
 // Record A's Recon, all of B, then A's remaining stages. Execute B before A.
 NrdBridge::RequestHistoryReset(); // Start this two-recording reset-depth scenario independently of preceding submitted history.
 title.writeDepth(5.f);title.recon(frame++);const auto listA=h.list.Get();
 h.exchange(alternate);checksumB=h.buffer(1024,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,true);title.checksum=checksumB;
 title.writeDepth(7.f);title.frame(frame++);const auto recordB=FfxApiProxy::records.back();const auto motionB=motionCapture(title,recordB);const auto readB=title.capture();SubmissionProbe probeB;probeB.attach(h.device.Get(),h.list.Get());hr(h.list->Close());
 h.exchange(alternate);title.checksum=checksumA;need(h.list.Get()==listA,"stream exchange returns the original A recording");title.tail();
 const auto recordA=FfxApiProxy::records.back();const auto motionA=motionCapture(title,recordA);const auto readA=title.capture();SubmissionProbe probeA;probeA.attach(h.device.Get(),h.list.Get());hr(h.list->Close());
 privateGuides(recordA,recordB);need((recordA.flags&FFX_DENOISER_DISPATCH_RESET) && (recordB.flags&FFX_DENOISER_DISPATCH_RESET),"unpublished overlapping predecessors receive independent fresh RESET histories");
 need(FfxApiProxy::dispatches==interCalls+2 && NrdBridge::GetStatus().framesBridged==interFrames+2 && NrdBridge::gService->failures==failures,"interleaved Recon/Temporal/Consumer bridges both recordings without overwrite, cancellation or failure");
 h.exchange(alternate);title.checksum=checksumB;h.executeClosed();title.rrChecks(title.validate(readB));motionEquals(motionB,0);h.reset();
 h.exchange(alternate);title.checksum=checksumA;h.executeClosed();title.rrChecks(title.validate(readA));motionEquals(motionA,0);h.reset();
 need(probeA.before==1 && probeA.published==1 && !probeA.failed && probeB.before==1 && probeB.published==1 && !probeB.failed,"actual ledger publishes one fence for each reversed-order submitted recording");
 deep["interleaved_reversed_submission"]={{"bridged_recordings",2},{"private_contexts_guides",true},{"both_rr_reset",true},{"both_gpu_depth_delta_zero",true},{"title_bindings_counts_exact",true}};
 // Publish a still-unfinished predecessor on QA, then record shared history on QB.
 QueueAudit::Attach(h.queue.Get(),alternate.queue.Get());ComPtr<ID3D12Fence> gate;hr(h.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));GateRelease gateRelease{gate};
 hr(h.queue->Wait(gate.Get(),1));title.writeDepth(5.f);title.frame(frame++);const auto queueRecordA=FfxApiProxy::records.back();const auto queueReadA=title.capture();SubmissionProbe queuedA;queuedA.attach(h.device.Get(),h.list.Get());h.submit(false);
 need(queuedA.point && queuedA.point->IsPublished() && queuedA.point->fence->GetCompletedValue()<queuedA.point->value,"actual predecessor point is published after native Signal while QA is physically stalled");
 h.exchange(alternate);title.checksum=checksumB;title.writeDepth(7.f);title.frame(frame++);const auto queueRecordB=FfxApiProxy::records.back();const auto queueMotionB=motionCapture(title,queueRecordB);const auto queueReadB=title.capture();SubmissionProbe queuedB;queuedB.attach(h.device.Get(),h.list.Get());h.submit(false);
 std::cerr<<"cross-queue history A context="<<queueRecordA.context<<" spec="<<queueRecordA.spec<<" motion="<<queueRecordA.motion<<" depth="<<queueRecordA.depth
  <<" B context="<<queueRecordB.context<<" spec="<<queueRecordB.spec<<" motion="<<queueRecordB.motion<<" depth="<<queueRecordB.depth<<" flags="<<queueRecordB.flags<<'\n';
 need(queueRecordA.context==queueRecordB.context && queueRecordA.spec==queueRecordB.spec && queueRecordA.motion==queueRecordB.motion && queueRecordA.depth!=queueRecordB.depth,"published predecessor shares temporal context/spec/motion while alternating independent current depth endpoints on the next queue");
 need(!(queueRecordB.flags&FFX_DENOISER_DISPATCH_RESET),"published consecutive cross-queue frame inherits actual RR history");
 size_t waitAt=SIZE_MAX,executeAt=SIZE_MAX;unsigned waits=0,executes=0;
 for(size_t i=0;i<QueueAudit::events.size();++i) {const auto& e=QueueAudit::events[i];
  if(e.kind==QueueAudit::Kind::Wait && e.queue==h.queue.Get() && e.fence==queuedA.point->fence.Get() && e.value==queuedA.point->value) {++waits;waitAt=i;}
  if(e.kind==QueueAudit::Kind::Execute && e.queue==h.queue.Get() && e.list==h.list.Get()) {++executes;executeAt=i;}
 }
 need(waits==1 && executes==1 && waitAt<executeAt,"actual native QB Wait on the precise published QA fence precedes exactly one original title Execute");
 need(h.fence->GetCompletedValue()<h.tick,"QB completion remains blocked until the real QA predecessor gate opens");
 hr(gate->Signal(1));h.waitComplete();title.rrChecks(title.validate(queueReadB));motionEquals(queueMotionB,2.f);
 h.exchange(alternate);title.checksum=checksumA;h.waitComplete();title.rrChecks(title.validate(queueReadA));h.reset();
 h.exchange(alternate);title.checksum=checksumB;
 need(queuedA.published==1 && queuedB.published==1 && !queuedA.failed && !queuedB.failed,"both ordered real submissions publish successful actual fence points");
 deep["cross_queue_history"]={{"actual_waits",waits},{"original_executes",executes},{"wait_precedes_execute",true},{"gate_blocks_consumer",true},{"same_context_and_guides",true},{"gpu_depth_delta",2}};
 // Re-execution of an already closed list is visible to the actual typed ledger.
 const auto replayCalls=FfxApiProxy::dispatches,replayCreates=FfxApiProxy::creates;h.executeClosed();title.rrChecks(title.validate(queueReadB));
 need(FfxApiProxy::dispatches==replayCalls && queuedB.before==2 && queuedB.published==2 && queuedB.ordinal==2,"closed-list replay executes original GPU work once without another SDK recording and advances actual submission ordinal");
 h.reset();title.writeDepth(9.f);title.frame(frame++);const auto freshRecord=FfxApiProxy::records.back();const auto freshMotion=motionCapture(title,freshRecord);const auto freshRead=title.capture();h.submit();title.rrChecks(title.validate(freshRead));motionEquals(freshMotion,0);h.reset();
 need(FfxApiProxy::creates==replayCreates+1 && (freshRecord.flags&FFX_DENOISER_DISPATCH_RESET),"closed-list resubmission poisons future temporal reuse and creates a fresh RESET context/depth domain");
 deep["closed_list_resubmission"]={{"native_replays",1},{"second_submission_ordinal",2},{"future_fresh_reset",true},{"future_depth_delta_zero",true}};
 h.exchange(alternate);title.checksum=checksumA;
 // Even a successful publication is not RR history when no Consumer output was committed.
 const auto incompleteCalls=FfxApiProxy::dispatches,incompleteCreates=FfxApiProxy::creates;
 const auto incompleteFrames=NrdBridge::GetStatus().framesBridged;const auto precedingRecord=FfxApiProxy::records.back();const UINT incompleteSL=frame++;
 title.writeDepth(5.f);title.recon(incompleteSL);title.pass(Role::PrePass);title.pass(Role::Temporal,24,true);
 const auto partialInputs=NrdBridge::gService->lists.at(h.list.Get()).inputs;const auto incompleteRead=title.capture();SubmissionProbe incompleteProbe;incompleteProbe.attach(h.device.Get(),h.list.Get());h.submit();title.validateIncomplete(incompleteRead);
 need(FfxApiProxy::dispatches==incompleteCalls && NrdBridge::GetStatus().framesBridged==incompleteFrames && incompleteProbe.point && incompleteProbe.point->IsPublished(),"conversion-only submitted prefix publishes a real fence without provider/output commit");
 h.exchange(alternate);title.checksum=checksumB;title.writeDepth(11.f);title.frame(incompleteSL);const auto afterIncomplete=FfxApiProxy::records.back();
 const auto incompleteMotion=motionCapture(title,afterIncomplete);const auto completeRead=title.capture();h.submit();title.rrChecks(title.validate(completeRead));motionEquals(incompleteMotion,0);h.reset();
 need(FfxApiProxy::creates==incompleteCreates+1 && afterIncomplete.context!=precedingRecord.context && afterIncomplete.depth!=partialInputs.linearDepth && afterIncomplete.motion!=partialInputs.motion && (afterIncomplete.flags&FFX_DENOISER_DISPATCH_RESET),"before incomplete predecessor Reset, a following Recon gets a private fresh SDK/depth RESET domain despite its published fence");
 h.exchange(alternate);title.checksum=checksumA;h.reset();
 deep["submitted_without_consumer"]={{"real_fence_published",true},{"provider_dispatches_in_prefix",0},{"fresh_before_old_list_reset",true},{"same_sl_frame",true},{"gpu_depth_delta_zero",true},{"title_prefix_bindings_counts_exact",true}};
 // Two disjoint same-size title profiles use QA and QB without borrowing owned history.
 auto titleA=std::make_unique<Title>(h,64,64,true);titleA->frame(frame++);need(titleA->sentinel(titleA->finish()),"disjoint profile A first validates through native NRD discovery");
 ComPtr<ID3D12Fence> disjointGate;hr(h.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&disjointGate)));GateRelease disjointRelease{disjointGate};hr(h.queue->Wait(disjointGate.Get(),1));
 titleA->frame(frame++);const auto disjointA=FfxApiProxy::records.back();const auto disjointMotionA=motionCapture(*titleA,disjointA);const auto disjointReadA=titleA->capture();SubmissionProbe disjointProbeA;disjointProbeA.attach(h.device.Get(),h.list.Get());h.submit(false);
 need(disjointProbeA.point && disjointProbeA.point->IsPublished() && disjointProbeA.point->fence->GetCompletedValue()<1,"disjoint profile A is published and retained while its actual queue remains stalled");
 h.exchange(alternate);auto titleB=std::make_unique<Title>(h,64,64,true);titleB->frame(frame++);need(titleB->sentinel(titleB->finish()),"disjoint profile B rediscovers its own resources on the other queue");
 titleB->frame(frame++);const auto disjointB=FfxApiProxy::records.back();const auto disjointMotionB=motionCapture(*titleB,disjointB);const auto disjointReadB=titleB->capture();SubmissionProbe disjointProbeB;disjointProbeB.attach(h.device.Get(),h.list.Get());
 privateGuides(disjointA,disjointB);need((disjointA.flags&FFX_DENOISER_DISPATCH_RESET) && (disjointB.flags&FFX_DENOISER_DISPATCH_RESET),"disjoint same-size resource generations get separate fresh RR histories");
 const auto eventsBefore=QueueAudit::events.size();h.submit();titleB->rrChecks(titleB->validate(disjointReadB));motionEquals(disjointMotionB,0);
 unsigned foreignWaits=0;for(size_t i=eventsBefore;i<QueueAudit::events.size();++i) {const auto& event=QueueAudit::events[i];if(event.kind==QueueAudit::Kind::Wait && event.fence==disjointProbeA.point->fence.Get()) ++foreignWaits;}
 need(foreignWaits==0 && disjointProbeA.point->fence->GetCompletedValue()<1,"private disjoint QB work completes without waiting for the still-stalled QA generation");h.reset();
 hr(disjointGate->Signal(1));h.exchange(alternate);h.waitComplete();titleA->rrChecks(titleA->validate(disjointReadA));motionEquals(disjointMotionA,0);h.reset();
 need(disjointProbeA.published==1 && disjointProbeB.published==1 && !disjointProbeA.failed && !disjointProbeB.failed,"disjoint queue generations retain owned state through independent successful publications");
 deep["disjoint_resource_queues"]={{"same_extent",{64,64}},{"private_contexts_guides",true},{"qb_completes_while_qa_stalled",true},{"foreign_waits",foreignWaits},{"both_gpu_depth_delta_zero",true},{"both_title_bindings_counts_exact",true}};
 keepTitles.push_back(std::move(titleA));keepTitles.push_back(std::move(titleB));QueueAudit::Detach();
 deep["synthetic_last_frame"]=frame-1;deep["provider_recordings_added"]=FfxApiProxy::dispatches-14;result["deep_native"]=deep;
}
void depthEquals(const Readback& read,float expected) {
 need(read.footprint.Footprint.Format==DXGI_FORMAT_R32_FLOAT,"actual signed provider receives an R32_FLOAT linear-depth guide");
 void* mapped=nullptr;hr(read.resource->Map(0,nullptr,&mapped));bool exact=true;
 for(UINT y=0;y<read.height;++y) {
  const auto* values=reinterpret_cast<const float*>(static_cast<const uint8_t*>(mapped)+size_t(y)*read.footprint.Footprint.RowPitch);
  for(UINT x=0;x<read.width;++x)exact &= std::bit_cast<UINT>(values[x])==std::bit_cast<UINT>(expected);
 }
 read.resource->Unmap(0,nullptr);need(exact,"actual GPU current linear-depth guide matches every pixel of this frame's native VIEWZ source");
}
void guidePingPongCase(Host& h,Title& title,J& result) {
 constexpr UINT bridgeFrames=8;const auto createsBefore=FfxApiProxy::creates,dispatchesBefore=FfxApiProxy::dispatches;
 const auto framesBefore=NrdBridge::GetStatus().framesBridged;
 std::array<ComPtr<ID3D12Resource>,2> depths{title.tex[3],{}};
 const auto desc=depths[0]->GetDesc();D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
 hr(h.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&depths[1])));
 titleTextures.insert(depths[1].Get());FrameSurvey::ResourceCreated(depths[1].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
 need(depths[0].Get()!=depths[1].Get(),"guide ping-pong uses two genuinely distinct live native VIEWZ resources");
 const auto stable=title.tex;title.frame(1);need(title.sentinel(title.finish()),"guide ping-pong discovery frame executes untouched original title NRD");
 need(NrdBridge::gService->cache.Valid()&&FfxApiProxy::dispatches==dispatchesBefore,"cold guide scenario validates its full chain before any signed RR dispatch");
 const auto generation=NrdBridge::gService->cache.Generation();std::shared_ptr<NrdBridge::HistoryDomain> history;
 ProviderExports::Record previous{};J frames=J::array();float previousDepth=0;
 for(UINT i=0;i<bridgeFrames;++i) {
  const UINT index=(i+1)%2,frame=i+2;const float value=index?7.f:5.f,delta=i?value-previousDepth:0.f;
  title.tex[3]=depths[index];title.views();title.writeDepth(value);
  for(UINT slot=0;slot<9;++slot)if(slot!=3) {
   const UINT texture=std::array<UINT,9>{0,1,2,3,4,5,6,7,8}[slot];
   need(title.tex[texture].Get()==stable[texture].Get(),"only VIEWZ identity rotates; all signal, normal, motion and output anchors remain exact");
  }
  const auto dispatchBefore=FfxApiProxy::dispatches,restoreBefore=restores;const auto bridgedBefore=NrdBridge::GetStatus().framesBridged;
  title.frame(frame);
  need(FfxApiProxy::dispatches==dispatchBefore+1&&restores==restoreBefore+3,"every rotated-guide frame records one actual signed RR and all three production title restores");
  need(NrdBridge::GetStatus().active&&NrdBridge::GetStatus().framesBridged==bridgedBefore+1,"every frame after discovery becomes Active immediately despite a changed current VIEWZ pointer");
  need(NrdBridge::gService->cache.Generation()==generation&&NrdBridge::gService->cache.Get().viewDepth==depths[index].Get(),"validated current guide publication preserves the same signal-profile generation");
  const auto record=FfxApiProxy::records.back();const bool reset=(record.flags&FFX_DENOISER_DISPATCH_RESET)!=0;
  if(!i) {history=NrdBridge::gService->history;need(reset&&bool(history),"first rotated-guide RR frame owns one real RESET history domain");}
  else {
   need(!reset,"submitted guide ping-pong preserves RR history without further RESET flags");
   need(record.context==previous.context&&record.spec==previous.spec&&record.diff==previous.diff&&record.motion==previous.motion&&record.depth!=previous.depth,"guide rotation reuses the same signed context/spec/diff/motion and alternates causal current-depth endpoints");
   need(NrdBridge::gService->history==history,"guide pointer rotation retains the exact same production history domain");
  }
  need(FfxApiProxy::creates==createsBefore+1,"no rotated-guide frame recreates its physical signed AMD provider context");
  const auto motion=motionCapture(title,record);
  const auto linearDepth=title.readback(static_cast<ID3D12Resource*>(record.depth),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  const auto outputs=title.capture();h.submit();const auto stats=title.rrChecks(title.validate(outputs));
  need(NrdBridge::gService->lists.at(h.list.Get()).parameters.depthSign==-1.f,"synthetic right-handed camera requires negative signed linear depth");
  depthEquals(linearDepth,-value);motionEquals(motion,delta);
  need(NrdBridge::GetStatus().active,"submitted rotated-guide frame stays Active after GPU execution");
  h.reset();need(NrdBridge::GetStatus().active&&NrdBridge::gService->history==history,"successful list Reset retains the submitted Active history domain");
  frames.push_back({{"frame",frame},{"native_depth_identity",index?"B":"A"},{"native_viewz",value},{"gpu_current_linear_depth",-value},{"gpu_motion_depth_delta",delta},{"provider_reset",reset},{"active",true},{"statistics",stats}});
  previous=record;previousDepth=value;
 }
 need(FfxApiProxy::dispatches==dispatchesBefore+bridgeFrames&&FfxApiProxy::creates==createsBefore+1&&NrdBridge::GetStatus().framesBridged==framesBefore+bridgeFrames,"all eight guide ping-pong frames commit without discovery gaps or provider recreation");
 result["guide_pingpong"]={{"submitted_frames",bridgeFrames},{"initial_discovery_frames",1},{"provider_dispatches",bridgeFrames},{"physical_provider_creates",1},
  {"same_history_domain",true},{"same_signal_profile_generation",true},{"reset_frames",1},{"active_every_frame",true},{"current_depth_and_causal_motion_every_pixel",true},
  {"title_root_heaps_pso_rgb_alpha_checks_unchanged",true},{"frames",frames}};
 titleTextures.erase(depths[1].Get());
}
std::vector<uint8_t> qualityBytes(const std::filesystem::path& file) {
 std::ifstream stream(file,std::ios::binary);need(bool(stream),"quality replay input exists");
 stream.seekg(0,std::ios::end);const auto size=stream.tellg();need(size>0&&size<1024*1024,"quality input payload has a bounded declared size");
 stream.seekg(0);std::vector<uint8_t> bytes(static_cast<size_t>(size));stream.read(reinterpret_cast<char*>(bytes.data()),size);
 need(bool(stream),"quality replay input reads every declared byte");return bytes;
}
std::vector<uint8_t> qualityPayload(const std::filesystem::path& directory,const J& payload,size_t expected) {
 const auto name=payload["file"].get<std::string>();need(std::filesystem::path(name).filename()==name&&name.find('\\')==std::string::npos&&name.find('/')==std::string::npos,"quality payload path is an exact local basename");
 auto bytes=qualityBytes(directory/name);need(bytes.size()==expected&&payload["bytes"].get<size_t>()==expected,"quality native payload size matches its exact texture shape");
 need(RRTraceAdditiveIO::Sha256({bytes.data(),bytes.size()})==payload["sha256"].get<std::string>(),"quality replay consumes the sealed input payload hash");return bytes;
}
void qualityUpload(Title& title,UINT slot,const std::vector<uint8_t>& bytes,UINT bpp) {
 auto& h=title.h;const auto desc=title.tex[slot]->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 size=0;
 h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&size);auto up=h.buffer(size,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
 void* mapped=nullptr;hr(up->Map(0,nullptr,&mapped));std::memset(mapped,0,size_t(size));
 for(UINT y=0;y<title.height;++y)std::memcpy(static_cast<uint8_t*>(mapped)+size_t(y)*fp.Footprint.RowPitch,bytes.data()+size_t(y)*title.width*bpp,size_t(title.width)*bpp);
 up->Unmap(0,nullptr);D3D12_TEXTURE_COPY_LOCATION source{},target{};source.pResource=up.Get();source.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;source.PlacedFootprint=fp;
 target.pResource=title.tex[slot].Get();target.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
 h.barrier(title.tex[slot].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);h.list->CopyTextureRegion(&target,0,0,0,&source,nullptr);
 h.barrier(title.tex[slot].Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);h.uploads.push_back(up);
 if(slot<2) {title.raw[slot].resize(bytes.size()/2);std::memcpy(title.raw[slot].data(),bytes.data(),bytes.size());}
}
SLConstantsSnapshot qualityCamera(const J& frame,UINT width,UINT height,UINT id) {
 auto sample=camera(id,width,height);auto& c=sample.constants;const auto& projection=frame["projection"];const auto& view=frame["view"];
 for(UINT row=0;row<4;++row)c.cameraViewToClip[row]=sl::float4(projection[0][row].get<float>(),projection[1][row].get<float>(),projection[2][row].get<float>(),projection[3][row].get<float>());
 c.cameraRight=sl::float3(view[0][0].get<float>(),view[0][1].get<float>(),view[0][2].get<float>());
 c.cameraUp=sl::float3(view[1][0].get<float>(),view[1][1].get<float>(),view[1][2].get<float>());
 c.cameraFwd=sl::float3(-view[2][0].get<float>(),-view[2][1].get<float>(),-view[2][2].get<float>());
 const auto& position=frame["camera"];c.cameraPos=sl::float3(position[0].get<float>(),position[1].get<float>(),position[2].get<float>());
 c.cameraNear=projection[2][3].get<float>();c.cameraFar=0;c.cameraFOV=2.f*std::atan(1.f/projection[1][1].get<float>());
 c.jitterOffset=sl::float2(frame["jitter"][0].get<float>(),frame["jitter"][1].get<float>());c.reset=frame["reset"].get<bool>()?sl::Boolean::eTrue:sl::Boolean::eFalse;
 c.motionVectorsJittered=sl::Boolean::eFalse;return sample;
}
std::string qualitySave(const std::filesystem::path& path,const std::vector<uint16_t>& values) {
 std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(values.data()),std::streamsize(values.size()*2));file.flush();need(bool(file),"quality replay exports exact native half output bytes");
 return RRTraceAdditiveIO::Sha256({reinterpret_cast<const uint8_t*>(values.data()),values.size()*2});
}
void qualityReplayCase(Host& h,Title& title,J& result,const std::filesystem::path& output,bool projected,std::vector<ComPtr<ID3D12Resource>>& keepGuides) {
 const auto input=output.parent_path()/"quality_input";const auto manifestBytes=qualityBytes(input/"sequence.json");const auto manifest=J::parse(manifestBytes);
 need(manifest["schema"]=="fsrd-native-rr-synthetic-quality-v1"&&manifest["width"]==title.width&&manifest["height"]==title.height,"quality replay uses the exact supported synthetic input schema/extent");
 need(manifest["submitted_frames"]==manifest["frames"].size()&&manifest["frames"].size()>=16&&manifest["frames"].size()<=96,"quality sequence is bounded and includes temporal warmup");
 need(title.codecBits==0&&manifest["source_motion_jittered"]==false,"quality replay reads native RGB output and one explicit canonical motion convention");
 NrdBridge::RRSettings settings;std::string error;need(NrdBridge::ApplyRRSettings(settings,projected,error),"quality candidate convention applies before the discovery prefix");
 std::array<ComPtr<ID3D12Resource>,2> depths{title.tex[3],{}},normals{title.tex[2],{}};
 for(auto* pair:{&depths,&normals}) {
  const auto desc=(*pair)[0]->GetDesc();D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_DEFAULT;
  hr(h.device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&(*pair)[1])));
  FrameSurvey::ResourceCreated((*pair)[1].Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);titleTextures.insert((*pair)[1].Get());
  keepGuides.push_back((*pair)[0]);keepGuides.push_back((*pair)[1]);need((*pair)[0].Get()!=(*pair)[1].Get(),"quality sequence rotates genuinely distinct live native guide resources");
 }
 ComPtr<ID3D12QueryHeap> queries;D3D12_QUERY_HEAP_DESC queryDesc{D3D12_QUERY_HEAP_TYPE_TIMESTAMP,2,0};hr(h.device->CreateQueryHeap(&queryDesc,IID_PPV_ARGS(&queries)));
 UINT64 frequency=0;hr(h.queue->GetTimestampFrequency(&frequency));need(frequency>0,"quality diagnostic timestamp clock is available");
 const auto creates=FfxApiProxy::creates,dispatches=FfxApiProxy::dispatches;const auto initialBridged=NrdBridge::GetStatus().framesBridged;
 std::shared_ptr<NrdBridge::HistoryDomain> history;ffxContext context=nullptr;J frames=J::array();UINT resets=0;
 const std::array<std::pair<const char*,UINT>,5> slots{{{"spec",0},{"diff",1},{"nr",2},{"depth",3},{"motion",6}}};
 for(UINT index=0;index<manifest["frames"].size();++index) {
  const auto& frame=manifest["frames"][index];const UINT id=frame["frame"].get<UINT>();need(id==index+2,"quality frames are consecutive rendered evaluations");
  title.tex[2]=normals[index%2];title.tex[3]=depths[index%2];title.views();std::array<std::vector<uint8_t>,5> data;
  for(UINT n=0;n<slots.size();++n) {
   const auto [name,slot]=slots[n];const UINT bpp=slot==2||slot==3?4:8;data[n]=qualityPayload(input,frame["payloads"][name],size_t(title.width)*title.height*bpp);qualityUpload(title,slot,data[n],bpp);
  }
  const auto delta=qualityPayload(input,frame["payloads"]["expected_delta"],size_t(title.width)*title.height*4);
  if(index==0) {
   title.begin(1);StreamlineHooks::snapshot=qualityCamera(frame,title.width,title.height,1);StreamlineHooks::snapshot.constants.reset=sl::Boolean::eFalse;
   title.pass(Role::PrepLast);title.pass(Role::Recon,8,true);h.uav(title.tex[4].Get());h.uav(title.tex[5].Get());title.tail();need(title.sentinel(title.finish()),"quality cold prefix runs untouched original title shader and no signed RR");
   need(FfxApiProxy::dispatches==dispatches&&NrdBridge::gService->cache.Valid(),"quality discovery prefix completes before any provider dispatch");
  }
  const auto beforeDispatch=FfxApiProxy::dispatches,beforeRestore=restores;
  const auto beforeBridged=NrdBridge::GetStatus().framesBridged;
  h.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
  title.begin(id);StreamlineHooks::snapshot=qualityCamera(frame,title.width,title.height,id);title.pass(Role::PrepLast);title.pass(Role::Recon,8,true);
  h.uav(title.tex[4].Get());h.uav(title.tex[5].Get());title.tail();h.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
  need(NrdBridge::GetStatus().active&&FfxApiProxy::dispatches==beforeDispatch+1&&restores==beforeRestore+3&&NrdBridge::GetStatus().framesBridged==beforeBridged+1,"every synthetic quality frame reaches one signed RR commit and all exact production restores");
  const auto record=FfxApiProxy::records.back();const auto& list=NrdBridge::gService->lists.at(h.list.Get());
  need(list.parameters.cameraProjectedDepthDelta==projected,"quality frame captures the selected motion convention at its Recon ticket");
  if(!index){history=NrdBridge::gService->history;context=record.context;}else need(history==NrdBridge::gService->history&&context==record.context,"moving camera/projection/jitter and fresh guides preserve one submitted history/context");
  const bool reset=(record.flags&FFX_DENOISER_DISPATCH_RESET)!=0;resets+=reset;need(reset==(index==0),"quality replay RESETs exactly its first submitted frame");
  need(FfxApiProxy::creates==creates+1,"quality moving camera does not recreate its physical signed provider");
  const auto gpuMotion=motionCapture(title,record),gpuNR=title.readback(list.inputs.normals,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  const auto gpuDepth=title.readback(static_cast<ID3D12Resource*>(record.depth),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  const std::array<Readback,2> converted{title.readback(static_cast<ID3D12Resource*>(record.spec),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),title.readback(static_cast<ID3D12Resource*>(record.diff),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)};
  const auto outputData=title.capture();auto stamps=h.buffer(16,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);h.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,stamps.Get(),0);h.submit();
  const auto rgb=title.validate(outputData);const auto stats=title.rrChecks(rgb);const auto motion=gpuMotion.signal();
  for(UINT signal=0;signal<2;++signal)need(converted[signal].signal()==title.raw[signal],"actual signed provider's converted signal preserves every sealed finite native RGB/alpha input bit");
  bool currentDepth=true,currentNormal=true,currentXY=true,projectedDelta=true;void* depthMap=nullptr;hr(gpuDepth.resource->Map(0,nullptr,&depthMap));
  need(gpuNR.footprint.Footprint.Format==DXGI_FORMAT_R10G10B10A2_UNORM,"quality normal readback uses the attested native packed RGB10/A2 format");
  void* normalMap=nullptr;hr(gpuNR.resource->Map(0,nullptr,&normalMap));
  const auto* nativeZ=reinterpret_cast<const float*>(data[3].data());const auto* nativeNR=reinterpret_cast<const UINT*>(data[2].data());const auto* nativeMV=reinterpret_cast<const uint16_t*>(data[4].data());const auto* expectedDelta=reinterpret_cast<const float*>(delta.data());
  const auto parameters=list.parameters;
  need(!parameters.preserveNativeMaterialIDs,"camera-depth quality A/B keeps the independent material-ID experiment OFF");
  for(UINT y=0;y<title.height;++y)for(UINT x=0;x<title.width;++x) {
   const size_t pixel=size_t(y)*title.width+x,at=pixel*4;const auto* depthRow=reinterpret_cast<const float*>(static_cast<const uint8_t*>(depthMap)+size_t(y)*gpuDepth.footprint.Footprint.RowPitch);
   currentDepth &= std::bit_cast<UINT>(depthRow[x])==std::bit_cast<UINT>(-nativeZ[pixel]);
   const auto* normalRow=reinterpret_cast<const UINT*>(static_cast<const uint8_t*>(normalMap)+size_t(y)*gpuNR.footprint.Footprint.RowPitch);
   currentNormal &= normalRow[x]==(nativeNR[pixel]&0x3fffffffu); // Every current RGB bit, and exact A=0.
   for(UINT c=0;c<2;++c) {
    const float raw=PackedVector::XMConvertHalfToFloat(nativeMV[at+c]);const float jitter=c?(parameters.previousJitter.y-parameters.jitter.y)/title.height:(parameters.previousJitter.x-parameters.jitter.x)/title.width;
    currentXY &= std::abs(PackedVector::XMConvertHalfToFloat(motion[at+c])-(raw+jitter))<.0002f;
   }
   if(!index)projectedDelta &= motion[at+2]==0;
   if(x>=16&&x+16<title.width&&y>=16&&y+16<title.height)projectedDelta &= std::abs(PackedVector::XMConvertHalfToFloat(motion[at+2])-expectedDelta[pixel])<.005f;
  }
  gpuNR.resource->Unmap(0,nullptr);gpuDepth.resource->Unmap(0,nullptr);need(currentDepth&&currentNormal,"actual GPU guides use every current native normal/depth byte after each identity rotation");need(currentXY,"actual GPU motion XY uses the current native vector and jitter once");need(projectedDelta,"candidate GPU B matches the independent same-surface camera oracle in the interior");
  void* timestampData=nullptr;hr(stamps->Map(0,nullptr,&timestampData));const auto* ticks=static_cast<const UINT64*>(timestampData);need(ticks[1]>=ticks[0],"quality diagnostic timestamp pair is ordered");const double gpuMs=double(ticks[1]-ticks[0])*1000./frequency;stamps->Unmap(0,nullptr);
  const auto number=std::to_string(id);const auto prefix="frame"+std::string(3-number.size(),'0')+number;J hashes;
  hashes["spec"]=qualitySave(output/(prefix+"-spec.bin"),rgb[0]);hashes["diff"]=qualitySave(output/(prefix+"-diff.bin"),rgb[1]);hashes["motion"]=qualitySave(output/(prefix+"-motion.bin"),motion);
  frames.push_back({{"frame",id},{"provider_reset",reset},{"active",true},{"current_native_guides",true},{"camera_projected_depth_delta",projected},{"gpu_synthetic_title_chain_with_bridge_ms",gpuMs},{"output_sha256",hashes},{"statistics",stats}});h.reset();
 }
 need(FfxApiProxy::dispatches==dispatches+manifest["submitted_frames"].get<UINT>()&&FfxApiProxy::creates==creates+1&&NrdBridge::GetStatus().framesBridged==initialBridged+manifest["submitted_frames"].get<UINT>(),"whole immutable quality sequence commits every requested frame with one physical context");
 result["quality_replay"]={{"camera_projected_depth_delta",projected},{"input_manifest_sha256",RRTraceAdditiveIO::Sha256({manifestBytes.data(),manifestBytes.size()})},{"submitted_frames",frames.size()},
  {"physical_provider_creates",1},{"provider_resets",resets},{"same_history_domain",true},{"native_current_guides_every_pixel",true},{"title_root_heaps_pso_rgb_alpha_checks_unchanged",true},{"frames",frames},
  {"scope",manifest["scope"]},{"timestamp_scope","synthetic original-title shader chain + probes + production bridge; excludes uploads/readback; not game FPS or real NRD cost"}};
}
#include "__ROOT__/OptiScaler/shaders/shader_tools/tests/fsrd_nrd_native_motion_e2e_case.h"
#include "__ROOT__/OptiScaler/shaders/shader_tools/tests/fsrd_nrd_native_material_e2e_case.h"
namespace RROnlyCapture {
Title* title=nullptr;std::array<Readback,2> native;std::array<std::vector<uint16_t>,2> words;float pending=0.f;unsigned gapApplies=0,variant=0;
void Capture() {
 // Explicit original-title copies poison only the unused native output RGB
 // and opaque alpha. No noisy lighting, guide or provider input is modified.
 auto& h=title->h;
 for(UINT lobe=0;lobe<2;++lobe) {
  auto& values=words[lobe];values.resize(size_t(title->width)*title->height*4);
  for(size_t pixel=0;pixel<values.size()/4;++pixel) {
   for(UINT c=0;c<3;++c)values[pixel*4+c]=variant==1?uint16_t(0x7e00u|((pixel+c)&255u)):
    PackedVector::XMConvertFloatToHalf((variant==0?16.f:-8.f)+float((pixel+c)%7)*.125f);
   values[pixel*4+3]=pixel%3==2?uint16_t(0x8000u):PackedVector::XMConvertFloatToHalf(pixel%3==1?-3.5f:float(lobe?11:9));
  }
  auto* target=title->tex[lobe?8:7].Get();const auto desc=target->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 size=0;
  h.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&size);auto up=h.buffer(size,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
  void* mapped=nullptr;hr(up->Map(0,nullptr,&mapped));std::memset(mapped,0,size_t(size));
  for(UINT y=0;y<title->height;++y)std::memcpy(static_cast<uint8_t*>(mapped)+size_t(y)*fp.Footprint.RowPitch,values.data()+size_t(y)*title->width*4,size_t(title->width)*8);
  up->Unmap(0,nullptr);D3D12_TEXTURE_COPY_LOCATION source{},destination{};source.pResource=up.Get();source.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;source.PlacedFootprint=fp;
  destination.pResource=target;destination.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  h.barrier(target,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);h.list->CopyTextureRegion(&destination,0,0,0,&source,nullptr);
  h.barrier(target,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);h.uploads.push_back(up);
 }
 native={title->readback(7),title->readback(8)};
}
void ApplyGap() {
 auto settings=NrdBridge::GetRRSettingsState().requested;settings.nativeSpecularBlend=pending;std::string error;
 need(NrdBridge::ApplyRRSettings(settings,false,error)&&NrdBridge::GetRRSettingsState().requested.nativeSpecularBlend==0.f,"deprecated native-weight request in admission gap stays effective zero");++gapApplies;
}
}
J rrOnlyPixels(const Title& title,const std::array<std::vector<uint16_t>,2>& output,
               const std::array<std::vector<uint16_t>,2>& stage,const std::array<std::vector<uint16_t>,2>& native) {
 UINT64 finite=0,stageFinite=0,alpha=0,expected=0,nativeNonfinite=0,differentNative=0;
 for(UINT lobe=0;lobe<2;++lobe)for(size_t p=0;p<size_t(title.width)*title.height;++p) {
  const auto at=p*4;std::array<float,3> rgb;for(UINT c=0;c<3;++c){rgb[c]=PackedVector::XMConvertHalfToFloat(stage[lobe][at+c]);stageFinite+=std::isfinite(rgb[c]);nativeNonfinite+=!std::isfinite(PackedVector::XMConvertHalfToFloat(native[lobe][at+c]));}
  alpha+=output[lobe][at+3]==native[lobe][at+3];
  if(title.codecBits)rgb={(rgb[0]+2.f*rgb[1]+rgb[2])*.25f,(rgb[0]-rgb[2])*.5f,(-rgb[0]+2.f*rgb[1]-rgb[2])*.25f};
  for(UINT c=0;c<3;++c){const auto word=PackedVector::XMConvertFloatToHalf(rgb[c]);finite+=std::isfinite(PackedVector::XMConvertHalfToFloat(output[lobe][at+c]));expected+=output[lobe][at+c]==word;differentNative+=output[lobe][at+c]!=native[lobe][at+c];}
 }
 const auto pixels=UINT64(title.width)*title.height,components=pixels*6;
 need(stageFinite==components,"actual signed RR stage RGB is finite before the pure commit");
 need(finite==components&&alpha==pixels*2,"native RGB poison cannot contaminate either lobe and every opaque alpha bit survives, including signed zero");
 need(expected==components,"every title RGB word exclusively matches actual staged RR and exact word303 encoding/nearest-even YCoCg");
 need(differentNative==components,"final RGB never preserves the deliberately distinct finite or NaN native endpoint");
 return {{"rgb_values",components},{"finite_rgb",finite},{"native_alpha_values",alpha},{"rr_reference_matches",expected},{"native_nonfinite_rgb_values",nativeNonfinite},{"different_from_native_rgb",differentNative}};
}
void rrOnlyPolicyCase(Host& h,Title& title,J& result,const std::filesystem::path& output) {
 const auto input=output.parent_path()/"rr_only_policy_input";const auto bytes=qualityBytes(input/"sequence.json");const auto manifest=J::parse(bytes);
 need(manifest["schema"]=="fsrd-native-rr-synthetic-quality-v1"&&manifest["width"]==title.width&&manifest["height"]==title.height&&manifest["submitted_frames"]==44,
      "RR-only policy uses the unchanged sealed44-frame geometry/radiance/camera oracle");
 RROnlyCapture::title=&title;RROnlyCapture::gapApplies=0;std::shared_ptr<NrdBridge::HistoryDomain> history;ffxContext context=nullptr;
 const auto creates=FfxApiProxy::creates,dispatches=FfxApiProxy::dispatches,configures=FfxApiProxy::configures;UINT resets=0,lateChanges=0,closedChanges=0,poisonFrames=0;J rows=J::array();
 const std::array<std::pair<const char*,UINT>,5> slots{{{"spec",0},{"diff",1},{"nr",2},{"depth",3},{"motion",6}}};
 const std::array<float,5> requests{0.f,.375f,1.f,std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity()};
 const std::array<const char*,5> requestNames{"zero","fraction","one","nan","infinity"};
 for(const float value:requests)need(NrdBridge::NormalizeNativeSpecularBlend(value)==0.f,"all deprecated direct native weights normalize unconditionally to zero");
 need(!NrdBridge::GetRRSettingsState().requested.lobeRecovery,"stage identity proof explicitly has no optional private recovery applied");
 UINT64 cancellation=0,generation=0,staging=0,auxiliary=0;unsigned initializedConfigureCalls=0;
 for(UINT mode=0;mode<2;++mode)for(UINT index=0;index<44;++index) {
  const auto& frame=manifest["frames"][index];const UINT id=frame["frame"].get<UINT>()+mode*44;
  for(const auto [name,slot]:slots) {const UINT bpp=slot==2||slot==3?4:8;const auto data=qualityPayload(input,frame["payloads"][name],size_t(title.width)*title.height*bpp);qualityUpload(title,slot,data,bpp);}
  if(mode==0 && index==0) {
   title.begin(1);StreamlineHooks::snapshot=qualityCamera(frame,title.width,title.height,1);StreamlineHooks::snapshot.constants.reset=sl::Boolean::eFalse;
   title.pass(Role::PrepLast);title.pass(Role::Recon,8,true);h.uav(title.tex[4].Get());h.uav(title.tex[5].Get());title.tail();need(title.sentinel(title.finish()),"cold discovery executes untouched original output before any signed RR work");
  }
  title.setCodec(mode?0u:1u); // Deliberately opposite final flag during CPU recording.
  auto settings=NrdBridge::GetRRSettingsState().requested;settings.nativeSpecularBlend=requests[index%requests.size()];std::string error;
  const auto resetSerial=NrdBridge::gService->resetSerial,cancelSerial=NrdBridge::gService->cancellationSerial;
  const auto beforeDispatch=FfxApiProxy::dispatches;
  need(NrdBridge::ApplyRRSettings(settings,false,error)&&NrdBridge::GetRRSettingsState().requested.nativeSpecularBlend==0.f,"every live deprecated request is accepted only with effective native weight zero");
  need(NrdBridge::gService->resetSerial==resetSerial&&NrdBridge::gService->cancellationSerial==cancelSerial,"ignored legacy weights cancel no Recon ticket and reset no RR/conversion history");
  title.begin(id);StreamlineHooks::snapshot=qualityCamera(frame,title.width,title.height,id);title.pass(Role::PrepLast);title.pass(Role::Recon,8,true);h.uav(title.tex[4].Get());h.uav(title.tex[5].Get());
  if(index==17) {RROnlyCapture::pending=.375f;NrdBridge::gBeforeOutputLockForTesting=RROnlyCapture::ApplyGap;++lateChanges;}
  RROnlyCapture::variant=index%3;poisonFrames+=RROnlyCapture::variant==1;title.beforeConsumer=RROnlyCapture::Capture;title.tail();title.beforeConsumer=nullptr;NrdBridge::gBeforeOutputLockForTesting=nullptr;
  const auto& token=NrdBridge::gService->lists.at(h.list.Get());const auto record=FfxApiProxy::records.back();
  need(NrdBridge::GetStatus().active&&token.parameters.streamlineFrame==id&&record.list==h.list.Get()&&FfxApiProxy::dispatches==beforeDispatch+1,
       "current Consumer admits exactly one signed RR record and pure RR output");
  need(token.parameters.nativeSpecularBlend==0.f,"admitted Consumer parameters carry no deprecated native RGB contribution");
  if(mode==0 && index==0) {
   history=NrdBridge::gService->history;context=record.context;cancellation=NrdBridge::gService->cancellationSerial;generation=history->rr.ContextGeneration();
   staging=history->rr.OwnedStagingBytes();auxiliary=history->rr.OwnedAuxiliaryBytes();initializedConfigureCalls=FfxApiProxy::configures;need(initializedConfigureCalls==configures+7,"first physical context applies the same seven queried AMD defaults");
  }
  need(history==NrdBridge::gService->history&&context==record.context&&history->rr.ContextGeneration()==generation,"moving geometry and ignored native weights retain one physical RR context/history");
  need(NrdBridge::gService->cancellationSerial==cancellation&&history->rr.OwnedStagingBytes()==staging&&history->rr.OwnedAuxiliaryBytes()==auxiliary,
       "ignored native weights change neither cancellation epoch nor owned GPU allocation");
  need(FfxApiProxy::configures==initializedConfigureCalls,"ignored native weights issue no extra provider key/default configuration");
  const bool reset=(record.flags&FFX_DENOISER_DISPATCH_RESET)!=0;resets+=reset;need(reset==(index==0),"only explicit oracle phase starts reset RR; native RGB poison never seeds its history");
  const std::array<Readback,2> staged{title.readback(static_cast<ID3D12Resource*>(FfxApiProxy::lastSpecular.signal.output.resource),D3D12_RESOURCE_STATE_UNORDERED_ACCESS),
                                    title.readback(static_cast<ID3D12Resource*>(FfxApiProxy::lastDiffuse.signal.output.resource),D3D12_RESOURCE_STATE_UNORDERED_ACCESS)};
  const std::array<Readback,2> converted{title.readback(static_cast<ID3D12Resource*>(record.spec),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),title.readback(static_cast<ID3D12Resource*>(record.diff),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)};
  const auto captured=title.capture();title.setCodec(mode?0x80000000u:0u); // Original Consumer and commit capture read this only on GPU.
  if(index==5) {
   hr(h.list->Close());auto changed=settings;changed.nativeSpecularBlend=1.f;
   need(NrdBridge::ApplyRRSettings(changed,false,error)&&NrdBridge::GetRRSettingsState().requested.nativeSpecularBlend==0.f,"legacy request after Close remains zero for both old and future recordings");
   need(h.executeClosed(),"unchanged closed pure-RR recording remains legally submitted");++closedChanges;
  }
  else h.submit();
  const auto outputs=title.validate(captured);std::array<std::vector<uint16_t>,2> source{staged[0].signal(),staged[1].signal()},native{RROnlyCapture::native[0].signal(),RROnlyCapture::native[1].signal()};
  for(UINT lobe=0;lobe<2;++lobe){need(converted[lobe].signal()==title.raw[lobe],"every noisy RGB/hit-distance alpha bit still enters actual RR");need(native[lobe]==RROnlyCapture::words[lobe],"actual pre-commit GPU bytes contain the exact title finite/NaN RGB poison and opaque alpha");}
  const auto stats=rrOnlyPixels(title,outputs,source,native);
  rows.push_back({{"source_frame",frame["frame"]},{"frame",id},{"encoding",mode?"YCoCg":"RGB"},{"request",requestNames[index%requests.size()]},{"effective_strength",0.f},{"native_rgb_variant",RROnlyCapture::variant},
                  {"provider_reset",reset},{"admission_gap_request",index==17},{"closed_list_request",index==5},{"statistics",stats}});h.reset();
 }
 need(FfxApiProxy::dispatches==dispatches+88&&FfxApiProxy::creates==creates+1&&resets==2&&lateChanges==2&&closedChanges==2&&RROnlyCapture::gapApplies==2&&poisonFrames==30,
      "two entire44-frame encodings retain one actual context with88 signed records,30 NaN-poison controls and both admission/Close proofs");
 result["rr_only_policy"]={{"input_manifest_sha256",RRTraceAdditiveIO::Sha256({bytes.data(),bytes.size()})},{"binding",title.tableConstants?"native table":"root VA"},{"frames",rows},
  {"submitted_frames",88},{"physical_provider_creates",1},{"provider_resets",resets},{"noisy_input_identity",true},{"both_lobes_only_rr",true},{"admission_gap_requests",lateChanges},{"closed_list_requests",closedChanges},{"native_nan_rgb_frames",poisonFrames},
  {"extra_provider_configures",FfxApiProxy::configures-initializedConfigureCalls},{"same_history_context",true},{"extra_owned_bytes",0},
  {"scope","production bridge + signed RR on sealed camera inputs; native OUT is adversarial synthetic data used only for opaque alpha; no native NRD quality truth or claim its dispatches are suppressed"}};
 RROnlyCapture::native={};RROnlyCapture::words={};RROnlyCapture::title=nullptr;
}
// SOL F01/F02 repair witness: actual Config setter inputs -> production
// ReadStartupSettings -> per-frame RR Configure storage -> native Decode
// profile selection and native frame parameters, observed through real GPU
// pipelines and provider input bytes in the ordinary native RR-only flow.
struct WiringInputs { Readback spec,diff,motion; };
WiringInputs wiringInputs(Title& title) {
 const auto& record=FfxApiProxy::records.back();
 return {title.readback(static_cast<ID3D12Resource*>(record.spec),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),
  title.readback(static_cast<ID3D12Resource*>(record.diff),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),
  title.readback(static_cast<ID3D12Resource*>(record.motion),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)};
}
J wiringSignalDiff(const Readback& gated,const Readback& plain) {
 const auto a=gated.signal(),b=plain.signal();
 need(a.size()==b.size()&&(a.size()%4)==0,"comparable decode output word counts");
 uint64_t differing=0,gatedZeroPlainNonzero=0,plainZeroGatedNonzero=0;
 for(size_t i=0;i<a.size();++i) if(a[i]!=b[i]) {
  ++differing;
  if(a[i]==0&&b[i]!=0) ++gatedZeroPlainNonzero; // gated fill writes finite positive zero where plain filled
  if(b[i]==0&&a[i]!=0) ++plainZeroGatedNonzero;
 }
 return {{"differing_words",differing},{"gated_zero_plain_nonzero",gatedZeroPlainNonzero},
  {"plain_zero_gated_nonzero",plainZeroGatedNonzero},{"words",a.size()}};
}
J wiringMotionDiff(const Readback& legacy,const Readback& camera) {
 const auto a=legacy.signal(),b=camera.signal();
 need(a.size()==b.size()&&(a.size()%4)==0,"comparable motion guide word counts");
 uint64_t zDiffering=0,otherDiffering=0;
 for(size_t i=0;i<a.size();i+=4) for(UINT c=0;c<4;++c)
  if(a[i+c]!=b[i+c]) (c==2?zDiffering:otherDiffering)++;
 return {{"depth_delta_words",zDiffering},{"xyw_words",otherDiffering},{"pixels",a.size()/4}};
}
std::vector<const void*> wiringPsoOnlyIn(const std::unordered_map<const void*,unsigned>& inner,
 const std::unordered_map<const void*,unsigned>& outer) {
 std::vector<const void*> only;
 for(const auto& [pso,uses]:inner) if(!outer.contains(pso)) only.push_back(pso);
 return only;
}
J wiringState() {
 need(NrdBridge::gService&&NrdBridge::gService->history,"native RR history exists for the wrapper state witness");
 const auto state=NrdBridge::gService->history->rr.GetSettingsState().requested;
 return {{"surface_valid_fill",state.surfaceValidFill},{"legacy_motion_depth",state.legacyMotionDepth}};
}
void configWiringCase(Host& h,Title& title,J& result) {
 auto* config=Config::Instance();
 need(config->FfxDenoiserNrdBridgeSurfaceValidFill.value_or_default()&&config->FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default(),
  "case bootstrap requested both selectors through the Config setter path");
 need(NrdBridge::gService&&NrdBridge::gService->rrSettings.surfaceValidFill&&NrdBridge::gService->rrSettings.legacyMotionDepth,
  "production ReadStartupSettings stored both requested selectors in the installed service");
 need(NrdBridge::GetRRSettingsState().requested.surfaceValidFill&&NrdBridge::GetRRSettingsState().requested.legacyMotionDepth,
  "coordinator settings state publishes both startup requests");
 title.frame(1);need(title.sentinel(title.finish()),"cold discovery executes untouched original output before any signed RR work");
 // Warm frames use flat depth 5; capture frames use a 5/55 step. With the
 // static fixture camera the legacy rollback samples the warm frame's flat
 // previous-visible depth while the camera-only default predicts the current
 // step surface, so the motion depth delta separates the two provably.
 // Every frame owns one submitted recording, like the other scenarios.
 auto warm=[&](UINT id) {
  title.writeDepth(5.f);title.frame(id);
  const auto flags=FfxApiProxy::records.back().flags;
  const auto captured=title.capture();h.submit();
  title.rrChecks(title.validate(captured));h.reset();
  return flags;
 };
 auto stepCapture=[&](UINT id) {
  title.writeDepthStep(5.f,55.f);title.frame(id);
  const auto flags=FfxApiProxy::records.back().flags;
  const auto inputs=wiringInputs(title);
  const auto pso=gPipelineStateUses;
  const auto captured=title.capture();h.submit();
  title.rrChecks(title.validate(captured));h.reset();
  return std::make_tuple(flags,inputs,pso);
 };
 // Epoch ON: both selectors requested since startup.
 const auto warmOnFlags=warm(2);
 need((warmOnFlags&FFX_DENOISER_DISPATCH_RESET)!=0,"first configured frame starts with an actual provider reset");
 need(wiringState()["surface_valid_fill"].get<bool>()&&wiringState()["legacy_motion_depth"].get<bool>(),
  "per-frame RR Configure stored both selectors for this native Decode");
 const auto generation=NrdBridge::gService->history->rr.ContextGeneration();
 gPipelineStateUses.clear();
 const auto [onFlags,onA,psoOnA]=stepCapture(3);
 need(!(onFlags&FFX_DENOISER_DISPATCH_RESET),"capture frame continues the epoch without a new reset");
 // Epoch OFF: flip both selectors through the production request path.
 std::string error;
 auto settings=NrdBridge::GetRRSettingsState().requested;
 settings.surfaceValidFill=false;settings.legacyMotionDepth=false;
 need(NrdBridge::ApplyRRSettings(settings,false,error)&&error.empty(),"both-off request applies through the production request path");
 need(!NrdBridge::GetRRSettingsState().requested.surfaceValidFill&&!NrdBridge::GetRRSettingsState().requested.legacyMotionDepth,
  "coordinator state reflects the both-off request");
 const auto warmOffFlags=warm(4);
 need((warmOffFlags&FFX_DENOISER_DISPATCH_RESET)!=0,"selector flips reset the provider history before the next capture");
 gPipelineStateUses.clear();
 const auto [offFlags,offB,psoOffB]=stepCapture(5);
 need(!(offFlags&FFX_DENOISER_DISPATCH_RESET),"off capture frame continues without another reset");
 need(NrdBridge::gService->history->rr.ContextGeneration()==generation,"selector flips reset history without discarding the physical context");
 // Default-path pin: plain decode pipeline population, camera-only B and
 // byte-stable repeats while both selectors stay false.
 const auto repeatFlags=warm(6);
 need(!(repeatFlags&FFX_DENOISER_DISPATCH_RESET),"unchanged off settings request no further reset");
 gPipelineStateUses.clear();
 const auto [offRepeatFlags,offC,psoOffC]=stepCapture(7);
 need(!(offRepeatFlags&FFX_DENOISER_DISPATCH_RESET),"off repeat capture continues without another reset");
 need(wiringSignalDiff(offC.spec,offB.spec)["differing_words"]==0&&wiringSignalDiff(offC.diff,offB.diff)["differing_words"]==0&&
      wiringMotionDiff(offC.motion,offB.motion)["depth_delta_words"]==0&&wiringMotionDiff(offC.motion,offB.motion)["xyw_words"]==0,
  "unchanged default settings reproduce byte-identical RR inputs");
 const auto psoOnlyInOffRepeat=wiringPsoOnlyIn(psoOffC,psoOffB);
 need(psoOnlyInOffRepeat.empty(),"default repeats bind no additional pipeline state");
 // Epoch ON again: the same gated pipeline and the same legacy bytes return.
 settings.surfaceValidFill=true;settings.legacyMotionDepth=true;
 need(NrdBridge::ApplyRRSettings(settings,false,error)&&error.empty(),"both-on request re-applies through the production request path");
 const auto warmOn2Flags=warm(8);
 need((warmOn2Flags&FFX_DENOISER_DISPATCH_RESET)!=0,"re-enabling selectors resets the provider history again");
 gPipelineStateUses.clear();
 const auto [onAgainFlags,onC,psoOnC]=stepCapture(9);
 need(!(onAgainFlags&FFX_DENOISER_DISPATCH_RESET),"re-enabled capture frame continues without a new reset");
 need(NrdBridge::gService->history->rr.ContextGeneration()==generation,"re-enabled selectors still reuse the same physical context");
 // F01/F02 storage continuity on this flow: selector flips reset history,
 // return byte-identical outputs, and never leak into the default path. The
 // conversion-paradigm flow has no raw decode, so the gated-fill profile
 // witness lives in the native-transactions config-wiring case.
 need(wiringSignalDiff(onC.spec,onA.spec)["differing_words"]==0&&wiringSignalDiff(onC.diff,onA.diff)["differing_words"]==0,
  "re-enabled selectors reproduce byte-identical converted RR inputs");
 // F02: the frame parameters carried the legacy Z selector end to end.
 const auto motionDiff=wiringMotionDiff(onA.motion,offB.motion);
 const std::string motionCounts="legacy z words="+std::to_string(motionDiff["depth_delta_words"].get<uint64_t>())+
  " xyw words="+std::to_string(motionDiff["xyw_words"].get<uint64_t>());
 need(motionDiff["depth_delta_words"]>0,motionCounts.c_str());
 need(motionDiff["xyw_words"]==0,"the legacy selector changes only the motion depth delta component");
 need(wiringMotionDiff(onC.motion,onA.motion)["depth_delta_words"]==0&&wiringMotionDiff(onC.motion,onA.motion)["xyw_words"]==0,
  "re-enabled legacy selector reproduces byte-identical motion guides");
 need(wiringState()["surface_valid_fill"].get<bool>()&&wiringState()["legacy_motion_depth"].get<bool>(),
  "wrapper storage ends with both selectors requested again");
 result["config_wiring"]={{"startup_selectors_stored",true},{"epochs",{"on","off","off-repeat","on-again"}},
  {"motion_legacy_diff",motionDiff},{"context_generation_stable",true},
  {"provider_input_source","actual signed AMD dispatch records (signal input resources)"},
  {"scope","conversion-paradigm flow: production startup/request/Configure wiring and legacy motion Z GPU bytes; the gated raw-decode profile witness lives in the native-transactions config-wiring case"}};
}
void failureCase(Host& h,Title& title,J& result) {
 title.frame(1);need(title.sentinel(title.finish()),"fault scenario starts with a fully validated native discovery frame");
 title.frame(2);title.rrChecks(title.finish());title.frame(3);title.rrChecks(title.finish()); // Warm both native depth/SDK ping-pong histories.
 auto alternate=h.newStream(true);const auto checksumA=title.checksum;auto checksumB=h.buffer(1024,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,true);
 auto zero=h.upload(0,1024);h.barrier(checksumB.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);
 h.list->CopyBufferRegion(checksumB.Get(),0,zero.Get(),0,1024);h.barrier(checksumB.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);h.uploads.push_back(zero);
 QueueAudit::Attach(h.queue.Get(),alternate.queue.Get());title.frame(4);const auto recordA=FfxApiProxy::records.back();const auto readA=title.capture();SubmissionProbe probeA;probeA.attach(h.device.Get(),h.list.Get());h.submit();title.rrChecks(title.validate(readA));
 need(probeA.point && probeA.point->IsPublished() && probeA.point->fence->GetCompletedValue()>=1,"fault predecessor A has a real successfully completed publication");
 h.exchange(alternate);title.checksum=checksumB;title.frame(5);const auto recordB=FfxApiProxy::records.back();SubmissionProbe probeB;probeB.attach(h.device.Get(),h.list.Get());hr(h.list->Close());const auto dependentList=h.list.Get();const auto dependentQueue=h.queue.Get();
 need(recordA.context==recordB.context && recordA.spec==recordB.spec && recordA.motion==recordB.motion && recordA.depth!=recordB.depth && !(recordB.flags&FFX_DENOISER_DISPATCH_RESET),"already recorded B shares actual A context/spec/motion and alternates current-depth endpoints before failure");
 h.exchange(alternate);title.checksum=checksumA;ComPtr<ID3D12Fence> gate;hr(h.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));GateRelease release{gate};hr(h.queue->Wait(gate.Get(),1));
 QueueAudit::failSignalQueue=h.queue.Get();QueueAudit::signalExemptFence=h.fence.Get();QueueAudit::failNextSignal=true;const auto recordsBefore=FfxApiProxy::dispatches;
 need(h.executeClosed(false),"gated A replay executes once before its post-Execute publication fails");
 need(QueueAudit::injectedSignalFailures==1 && !QueueAudit::failNextSignal && probeA.before==2 && probeA.published==1 && probeA.failed==1,"native failed new Signal cannot publish or replace A's old fence point");
 need(FfxApiProxy::dispatches==recordsBefore && h.fence->GetCompletedValue()<h.tick,"failed publication returns while actual replay remains gated and records no new SDK call");
 h.exchange(alternate);title.checksum=checksumB;const auto before=GetTickCount64();const bool allowed=h.executeClosed(false);const auto returnedMs=GetTickCount64()-before;
 unsigned dependentExecutes=0,dependentSignals=0,oldPointWaits=0;
 for(const auto& e:QueueAudit::events) {
  if(e.queue!=dependentQueue)continue;
  if(e.kind==QueueAudit::Kind::Execute && e.list==dependentList)++dependentExecutes;
  if(e.kind==QueueAudit::Kind::Signal)++dependentSignals;
  if(e.kind==QueueAudit::Kind::Wait && e.fence==probeA.point->fence.Get())++oldPointWaits;
 }
 need(!allowed && h.denied==1 && FAILED(h.lastOrderingFailure),"actual typed SubmissionDecision denies the already recorded dependent B");
 need(dependentExecutes==0 && dependentSignals==0 && oldPointWaits==0 && probeB.published==0,"B neither executes nor signals nor waits the stale old publication");
 need(returnedMs<10000,"denied dependent submission returns to this CPU thread without polling a gated queue");
 need(!RecordedComputeLease::Available() && !NrdBridge::GetStatus().active && NrdBridge::GetStatus().reason.find("restart")!=std::string::npos,"actual submission failure pins history and surfaces an Inactive restart diagnostic");
 hr(gate->Signal(1));h.exchange(alternate);title.checksum=checksumA;h.waitComplete();title.rrChecks(title.validate(readA));
 // A probe owns its own list/fence and inspects B's independently initialized root-UAV output.
 auto probe=h.newStream(false);h.exchange(probe);auto read=h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
 h.barrier(checksumB.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);h.list->CopyBufferRegion(read.Get(),0,checksumB.Get(),0,1024);h.barrier(checksumB.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 hr(h.list->Close());ID3D12CommandList* inspect=h.list.Get();QueueAudit::originalExecute(h.queue.Get(),1,&inspect);hr(h.queue->Signal(h.fence.Get(),++h.tick));h.waitComplete();
 void* values=nullptr;hr(read->Map(0,nullptr,&values));bool untouched=true;for(UINT i=0;i<256;++i)untouched &= static_cast<UINT*>(values)[i]==0;read->Unmap(0,nullptr);need(untouched,"denied B leaves every initialized title root-UAV checksum byte untouched");
 h.reset();h.exchange(probe);h.reset();h.exchange(alternate);title.checksum=checksumB;h.reset();h.exchange(alternate);title.checksum=checksumA;QueueAudit::Detach();
 need(FfxApiProxy::creates==1 && FfxApiProxy::dispatches==4 && FfxApiProxy::destroys==0,"real SDK context and all recorded leases remain pinned across uncertain Signal completion");
 result["submission_failure"]={{"injected_native_signal_failures",1},{"dependent_denied",true},{"dependent_original_executes",dependentExecutes},{"dependent_signals",dependentSignals},{"old_point_waits",oldPointWaits},{"same_thread_return_ms",returnedMs},{"gpu_dependent_checksum_untouched",untouched},{"old_sdk_context_pinned",true},{"sdk_recordings",FfxApiProxy::dispatches}};
}
namespace CbLifetime {
using DescFn=D3D12_RESOURCE_DESC*(WINAPI*)(ID3D12Resource*,D3D12_RESOURCE_DESC*);
using DeviceFn=HRESULT(WINAPI*)(ID3D12Resource*,REFIID,void**);
using AddressFn=D3D12_GPU_VIRTUAL_ADDRESS(WINAPI*)(ID3D12Resource*);
DescFn originalDesc=nullptr;DeviceFn originalDevice=nullptr;AddressFn originalAddress=nullptr;
ID3D12Resource* watched=nullptr;bool dead=false;unsigned deadComCalls=0;
Title* title=nullptr;ComPtr<ID3D12Resource> temporary,replacement;ULONG finalReferences=ULONG_MAX;FrameSurvey::BoundConstantBuffer captured;
D3D12_RESOURCE_DESC* WINAPI Desc(ID3D12Resource* resource,D3D12_RESOURCE_DESC* out) {
 if(dead && resource==watched) {++deadComCalls;*out={};return out;}return originalDesc(resource,out);
}
HRESULT WINAPI Device(ID3D12Resource* resource,REFIID iid,void** out) {
 if(dead && resource==watched) {++deadComCalls;*out=nullptr;return E_FAIL;}return originalDevice(resource,iid,out);
}
D3D12_GPU_VIRTUAL_ADDRESS WINAPI Address(ID3D12Resource* resource) {
 if(dead && resource==watched) {++deadComCalls;return 0;}return originalAddress(resource);
}
void Attach(ID3D12Resource* resource) {
 watched=resource;dead=false;deadComCalls=0;auto** v=*reinterpret_cast<void***>(resource);
 originalDesc=reinterpret_cast<DescFn>(v[10]);originalDevice=reinterpret_cast<DeviceFn>(v[7]);originalAddress=reinterpret_cast<AddressFn>(v[11]);
 hr(DetourTransactionBegin());hr(DetourUpdateThread(GetCurrentThread()));
 need(DetourAttach(&(PVOID&)originalDesc,Desc)==NO_ERROR,"actual native Resource GetDesc observer uses installed SDK Win64 struct-return ABI");
 need(DetourAttach(&(PVOID&)originalDevice,Device)==NO_ERROR,"actual native Resource GetDevice observer attached");
 need(DetourAttach(&(PVOID&)originalAddress,Address)==NO_ERROR,"actual native Resource GPU-address observer attached");need(DetourTransactionCommit()==NO_ERROR,"native b6 lifetime observers committed");
}
void Detach() {
 hr(DetourTransactionBegin());hr(DetourUpdateThread(GetCurrentThread()));
 need(DetourDetach(&(PVOID&)originalDesc,Desc)==NO_ERROR,"native Resource GetDesc observer detached");need(DetourDetach(&(PVOID&)originalDevice,Device)==NO_ERROR,"native Resource GetDevice observer detached");
 need(DetourDetach(&(PVOID&)originalAddress,Address)==NO_ERROR,"native Resource GPU-address observer detached");need(DetourTransactionCommit()==NO_ERROR,"native b6 lifetime observers detached");watched=nullptr;
}
void BindTemporary() {
 // This separate volatile table slot is never used by any earlier native GPU Dispatch.
 title->bindConstants(temporary.Get(),57);
 need(FrameSurvey::ResolveComputeConstantBuffer(title->h.list.Get(),6,0,1216,captured) && captured.resource==temporary.Get() && captured.resourceGeneration && captured.descriptorHeap==title->visible.Get(),"actual native volatile b6 resolver captures the exact live generation and heap before the staged gap");
}
void ReleaseAndReplace() {
 need(!FrameSurvey::Internal() && NrdBridgeLifetime::Detail::borrowDepth==0,"staged Consumer gap runs on an ordinary thread outside the physical-resource borrow");
 temporary->AddRef();need(temporary->Release()==1,"bridge has added no permanent COM reference to the staged native b6");
 {NrdBridgeLifetime::ScopedRelease release(true);auto* old=temporary.Detach();FrameSurvey::Released(old);finalReferences=old->Release();}
 dead=true;need(finalReferences==0,"temporary native b6 is genuinely physically final-released in the staged gap");
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(captured),"pure production generation validation rejects the genuinely released native b6 token");
 title->cb=replacement;title->setCodec(0x80000000u);title->bindConstants(replacement.Get(),57,false);
 const auto cpu=title->visible->GetCPUDescriptorHandleForHeapStart().ptr+uint64_t(57)*title->increment;
 need(!FrameSurvey::gResources.contains(replacement.Get()) && !FrameSurvey::gViews.contains(cpu),"replacement b6 has neither resource identity nor CBV creation metadata; native table remains exact and live");
}
}
void cbvReleaseCase(Host& h,Title& title,J& result) {
 title.frame(1);need(title.sentinel(title.finish()),"CBV lifetime scenario validates the native title resource profile");title.frame(2);title.rrChecks(title.finish());
 const auto prefixConstants=title.cb;CbLifetime::title=&title;
 auto constants=[&] {auto value=h.upload(0,1536);void* mapped=nullptr;hr(value->Map(0,nullptr,&mapped));static_cast<UINT*>(mapped)[0]=55;value->Unmap(0,nullptr);return value;};
 CbLifetime::temporary=constants();CbLifetime::replacement=constants();need(CbLifetime::temporary.Get()!=CbLifetime::replacement.Get(),"replacement is preallocated while old native b6 is alive, so dead-pointer observation is unambiguous");
 FrameSurvey::ResourceCreated(CbLifetime::temporary.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);CbLifetime::Attach(CbLifetime::temporary.Get());
 const auto calls=FfxApiProxy::dispatches;const auto before=NrdBridge::GetStatus();const auto beforeRestores=restores;
 title.beforeConsumer=CbLifetime::BindTemporary;NrdBridge::gBeforeOutputLockForTesting=CbLifetime::ReleaseAndReplace;
 title.frame(3);title.beforeConsumer=nullptr;NrdBridge::gBeforeOutputLockForTesting=nullptr;
 need(CbLifetime::finalReferences==0 && CbLifetime::deadComCalls==0,"native capture ignores diagnostic source identity with zero GetDesc/GetDevice/GetGPUVA calls on the genuinely dead object");
 CbLifetime::Detach();need(NrdBridge::GetStatus().reason.empty(),"source registry generation is diagnostic and cannot reject the same live native b6 slot");need(FfxApiProxy::dispatches==calls+1 && NrdBridge::GetStatus().framesBridged==before.framesBridged+1 && NrdBridge::GetStatus().active,"same volatile b6 slot with a live unregistered replacement reaches real signed RR and publishes Active");
 need(restores==beforeRestores+3,"live Recon/motion and native b6 flag/RR injections each restore exact Consumer state");
 title.rrChecks(title.finish());need(title.codecBits==0x80000000u,"original Consumer and private flag snapshot observe the same replacement word303 bits");
 NrdBridge::SetRuntimeEnabled(false);NrdBridge::SetRuntimeEnabled(true);title.frame(4);title.rrChecks(title.finish());
 need(FfxApiProxy::dispatches==calls+2 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"runtime reset uses the still-valid native resource profile and unregistered b6 immediately");title.frame(5);title.rrChecks(title.finish());
 need(FfxApiProxy::dispatches==calls+3 && !(FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"same unregistered native b6 retains consecutive real RR history after runtime reset");
 const auto beforeRebind=FfxApiProxy::dispatches,beforeRebindRestores=restores;const auto beforeRebindFrames=NrdBridge::GetStatus().framesBridged;
 title.beforeConsumer=+[] {CbLifetime::title->bindConstants(CbLifetime::replacement.Get(),57,false);};
 NrdBridge::gBeforeOutputLockForTesting=+[] {CbLifetime::title->bindConstants(CbLifetime::replacement.Get(),58,false);};
 title.frame(6);title.beforeConsumer=nullptr;NrdBridge::gBeforeOutputLockForTesting=nullptr;
 need(NrdBridge::GetStatus().reason=="Consumer native b6 binding changed while awaiting injection; waiting for rediscovery","changing the actual native table argument cancels the stale bridge binding before provider work");
 need(FfxApiProxy::dispatches==beforeRebind && NrdBridge::GetStatus().framesBridged==beforeRebindFrames && !NrdBridge::GetStatus().active,"native table rebind never publishes stale RR work or Active");
 need(restores==beforeRebindRestores+2 && title.sentinel(title.finish()),"rebound original Consumer executes with exact live GPU bindings and native NRD RGBA untouched");
 NrdBridge::SetRuntimeEnabled(false);NrdBridge::SetRuntimeEnabled(true);title.frame(7);need(title.sentinel(title.finish()),"native rebind recovery validates the live replacement profile first");title.frame(8);title.rrChecks(title.finish());
 need(FfxApiProxy::dispatches==beforeRebind+1 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET),"native binding revalidation failure recovers with real RR RESET");
 result["cbv_lifetime"]={{"physical_final_reference_count",CbLifetime::finalReferences},{"dead_com_calls",CbLifetime::deadComCalls},{"sdk_calls_with_unregistered_replacement",1},{"replacement_resource_and_cbv_metadata_absent",true},{"same_live_slot_follows_gpu_descriptor",true},{"replacement_word303",0x80000000u},{"changed_table_argument_cancels_before_provider",true},{"cancelled_title_rgba_untouched",true},{"original_gpu_bindings_counts_exact",true},{"live_recovery_reset",true},{"volatile_native_table",true}};
 CbLifetime::temporary.Reset();CbLifetime::replacement.Reset();CbLifetime::title=nullptr;
}
void loadProvider(const char* path) {
 FfxApiProxy::real=true; auto module=LoadLibraryA(path); need(module!=nullptr,"signed AMD DLL loaded read-only");
 FfxApiProxy::denoiser_dx12.dll=module;
 FfxApiProxy::createFunction=reinterpret_cast<PfnFfxCreateContext>(GetProcAddress(module,"ffxCreateContext"));
 FfxApiProxy::destroyFunction=reinterpret_cast<PfnFfxDestroyContext>(GetProcAddress(module,"ffxDestroyContext"));
 FfxApiProxy::queryFunction=reinterpret_cast<PfnFfxQuery>(GetProcAddress(module,"ffxQuery"));
 FfxApiProxy::configureFunction=reinterpret_cast<PfnFfxConfigure>(GetProcAddress(module,"ffxConfigure"));
 FfxApiProxy::dispatchFunction=reinterpret_cast<PfnFfxDispatch>(GetProcAddress(module,"ffxDispatch"));
 need(FfxApiProxy::createFunction && FfxApiProxy::destroyFunction && FfxApiProxy::queryFunction && FfxApiProxy::configureFunction && FfxApiProxy::dispatchFunction,"all actual AMD exports resolved");
}
int main(int argc,char** argv) try {
 need(argc==3 || (argc==4 && (std::string(argv[3])=="--startup-off" || std::string(argv[3])=="--submission-failure" || std::string(argv[3])=="--cbv-lifetime" || std::string(argv[3])=="--guide-pingpong" || std::string(argv[3])=="--quality-off" || std::string(argv[3])=="--quality-on" || std::string(argv[3])=="--rr-only-policy" || std::string(argv[3])=="--rr-only-policy-table" || std::string(argv[3])=="--native-motion-quality" || std::string(argv[3])=="--native-motion-quality-baseline" || std::string(argv[3])=="--native-motion-quality-table" || std::string(argv[3])=="--native-material-guides" || std::string(argv[3])=="--native-material-guides-off" || std::string(argv[3])=="--config-wiring")),"scratch folder, signed AMD DLL and optional fresh-process scenario arguments");
 const bool startupOff=argc==4 && std::string(argv[3])=="--startup-off",submissionFailure=argc==4 && std::string(argv[3])=="--submission-failure",cbvLifetime=argc==4 && std::string(argv[3])=="--cbv-lifetime",guidePingPong=argc==4 && std::string(argv[3])=="--guide-pingpong",qualityReplay=argc==4 && (std::string(argv[3])=="--quality-off" || std::string(argv[3])=="--quality-on"); if(startupOff) NrdBridge::ConfigureStartup(false);
 const bool rrOnlyPolicy=argc==4 && (std::string(argv[3])=="--rr-only-policy" || std::string(argv[3])=="--rr-only-policy-table"),rrOnlyPolicyTable=argc==4 && std::string(argv[3])=="--rr-only-policy-table";
 const bool nativeMotionQuality=argc==4&&(std::string(argv[3])=="--native-motion-quality"||std::string(argv[3])=="--native-motion-quality-baseline"||std::string(argv[3])=="--native-motion-quality-table");
 const bool nativeMotionTable=argc==4&&std::string(argv[3])=="--native-motion-quality-table";
 const bool nativeMaterial=argc==4&&(std::string(argv[3])=="--native-material-guides"||std::string(argv[3])=="--native-material-guides-off");
 const bool configWiring=argc==4&&std::string(argv[3])=="--config-wiring";
 g_dllPath=std::filesystem::path(argv[1])/"fixture.dll"; Host h;
 need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled(),"standalone signed-provider fixture uses legacy metadata tracking without native retirement coverage");
 requestedList=h.list.Get(); J result; result["adapter"]=h.adapter;
 result["native_birth_coverage"]={{"dispatcher_ready",false},{"concurrent_release_gate",false},{"physical_release_coverage_proved",false}};
 need(!NrdBridge::Initialize(h.device.Get()),"startup OFF allocates no coordinator");
 AttachRoots(h.list.Get()); Wiring::Attach(h.list.Get());
 {
  Title disabled(h,128,128,false); disabled.frame(0,3,2,false); auto output=disabled.finish(3,2,false);
  need(disabled.sentinel(output),"startup OFF leaves title NRD output untouched"); need(!NrdBridge::gService,"startup OFF has no bridge owner");
  need(FfxApiProxy::creates==0 && FfxApiProxy::dispatches==0 && restores==0,"startup OFF allocates/dispatched/restored no bridge work");
  result["startup_off"]={{"provider_creates",0},{"provider_dispatches",0},{"restore_calls",0},{"nrdsentinel_untouched",true}};
 }
 Wiring::Detach(); DetachRoots(); Config::Instance()->FfxDenoiserNrdBridge.value=true;
 if(configWiring) {
  // Config setter path: the production Initialize below must consume these
  // exactly like INI startup values through ReadStartupSettings.
  Config::Instance()->FfxDenoiserNrdBridgeSurfaceValidFill.value=true;
  Config::Instance()->FfxDenoiserNrdBridgeLegacyMotionDepth.value=true;
 }
 NrdBridge::ConfigureStartup(true);
 need(!NrdBridgeNativeBirth::Ready()&&!NrdBridgeLifetime::ConcurrentReleasesEnabled()&&NrdBridgeNativeBirth::fixtureNativeCoverageRequests.load(std::memory_order_relaxed)==0,"minimal ResTrack adapter neither configures native retirement nor supplies coverage success");
 if(startupOff) {
  need(!NrdBridge::StartupEnabled() && !NrdBridge::Initialize(h.device.Get()),"configured OFF remains latched after live config and repeated bootstrap");
  need(FfxApiProxy::creates==0 && FfxApiProxy::dispatches==0 && restores==0,"fresh configured OFF performs no provider work or root restoration");
  const auto debug=h.debugCounts(); result["debug_errors"]=debug[0]; result["debug_warnings"]=debug[1]; result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"startup-off-result.json")<<result.dump(2)<<'\n';
  std::cout<<"PASS startup_off checks="<<checks<<'\n';return 0;
 }
 loadProvider(argv[2]);
 FrameSurvey::BeginCreationTracking(false); need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false),"real metadata-only survey installed");
 need(NrdBridge::Initialize(h.device.Get()),"production coordinator initialized"); AttachRoots(h.list.Get()); Wiring::Attach(h.list.Get());
 Title title(h,128,128,true,cbvLifetime||rrOnlyPolicyTable||nativeMotionTable,nativeMotionQuality);
 if(nativeMaterial) {
  nativeMaterialGuideCase(h,title,result,std::filesystem::path(argv[1]),std::string(argv[3])=="--native-material-guides");
  NrdBridge::Shutdown();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==FfxApiProxy::creates&&FfxApiProxy::contextToType.empty(),"native material shutdown retires every actual signed context after GPU leases");
  Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"native-material-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS native_material checks="<<checks<<'\n';return 0;
 }
 if(nativeMotionQuality) {
  nativeMotionQualityCase(h,title,result,std::filesystem::path(argv[1]),std::string(argv[3])!="--native-motion-quality-baseline");
  NrdBridge::Shutdown();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==FfxApiProxy::creates&&FfxApiProxy::contextToType.empty(),"native-motion shutdown retires every actual signed context after all captured GPU recording leases");
  Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"native-motion-quality-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS native_motion_quality checks="<<checks<<'\n';return 0;
 }
 if(rrOnlyPolicy) {
  rrOnlyPolicyCase(h,title,result,std::filesystem::path(argv[1]));NrdBridge::Shutdown();RecordedComputeLease::Poll();
  need(FfxApiProxy::destroys==FfxApiProxy::creates&&FfxApiProxy::contextToType.empty(),"pure-RR shutdown retires every actual signed context after all GPU fences");
  Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"rr-only-policy-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS rr_only_policy checks="<<checks<<'\n';return 0;
 }
 if(configWiring) {
  configWiringCase(h,title,result);NrdBridge::Shutdown();RecordedComputeLease::Poll();
  need(FfxApiProxy::destroys==FfxApiProxy::creates&&FfxApiProxy::contextToType.empty(),"config-wiring shutdown retires every actual signed context after GPU fences");
  Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"config-wiring-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS config_wiring checks="<<checks<<'\n';return 0;
 }
 if(qualityReplay) {
  std::vector<ComPtr<ID3D12Resource>> keepGuides;qualityReplayCase(h,title,result,std::filesystem::path(argv[1]),std::string(argv[3])=="--quality-on",keepGuides);
  NrdBridge::Shutdown();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==FfxApiProxy::creates&&FfxApiProxy::contextToType.empty(),"quality shutdown retires its exact signed context after every real fence");
  for(const auto& guide:keepGuides)titleTextures.erase(guide.Get());Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"quality-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS synthetic_quality checks="<<checks<<'\n';return 0;
 }
 if(guidePingPong) {
  guidePingPongCase(h,title,result);NrdBridge::Shutdown();RecordedComputeLease::Poll();
  need(FfxApiProxy::destroys==FfxApiProxy::creates&&FfxApiProxy::contextToType.empty(),"guide ping-pong shutdown retires its single signed context after every real fence");
  Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"guide-pingpong-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS guide_pingpong checks="<<checks<<'\n';return 0;
 }
 if(cbvLifetime) {
  cbvReleaseCase(h,title,result);NrdBridge::Shutdown();RecordedComputeLease::Poll();need(FfxApiProxy::destroys==FfxApiProxy::creates && FfxApiProxy::contextToType.empty(),"healthy CBV recovery retires every actual SDK context after fences");
  Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"cbv-lifetime-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS cbv_lifetime checks="<<checks<<'\n';return 0;
 }
 if(submissionFailure) {
  failureCase(h,title,result);NrdBridge::Shutdown();RecordedComputeLease::Poll();
  need(FfxApiProxy::destroys==0 && FfxApiProxy::contextToType.size()==1,"uncertain native SDK context stays pinned after coordinator shutdown");
  Wiring::Detach();DetachRoots();FrameSurvey::Shutdown();const auto debug=h.debugCounts();result["debug_errors"]=debug[0];result["debug_warnings"]=debug[1];result["native_checks"]=checks;
  std::ofstream(std::filesystem::path(argv[1])/"submission-failure-result.json")<<result.dump(2)<<'\n';std::cout<<"PASS submission_failure checks="<<checks<<'\n';return 0;
 }
 title.frame(1); auto first=title.finish(); need(title.sentinel(first),"discovery frame leaves title NRD output untouched");
 need(NrdBridge::gService->cache.Valid() && FfxApiProxy::dispatches==0,"first full chain discovers without pre-discovery RR");
 NrdBridge::SetDebugMode(NrdBridge::DebugMode::RawSignals); const auto rawBefore=restores; const auto bridgedBefore=NrdBridge::GetStatus().framesBridged;
 title.frame(2); auto raw=title.finish();
 if(raw[0][0]!=title.raw[0][0]) {
  const auto status=NrdBridge::GetStatus();
  std::cerr<<"Raw first pixel got="<<PackedVector::XMConvertHalfToFloat(raw[0][0])<<" expected="<<PackedVector::XMConvertHalfToFloat(title.raw[0][0])
   <<" phase="<<status.phase<<" reason="<<status.reason<<" bridged="<<status.framesBridged<<" restores="<<restores<<" cache="<<NrdBridge::gService->cache.Valid()<<'\n';
  for(const auto& [list,signature]:signatures) {
   std::cerr<<"root-cache this="<<list<<" requested="<<h.list.Get()<<" signature="<<signature.ptr<<" type="<<UINT(signature.type)
    <<" count="<<GetRootParameterCount(signature.ptr)<<" states="<<rootStates[list].size()<<" heaps="<<descriptorHeaps[list].NumDescriptorHeaps<<" PSO="<<pipelineStates[list]<<'\n';
   for(UINT index=0;index<rootStates[list].size();++index) std::cerr<<" p"<<index<<" type="<<UINT(rootStates[list][index].type)<<" table="<<rootStates[list][index].rootDescriptorTable.ptr<<'\n';
  }
  emitDebug();
 }
 result["raw"]=title.rawChecks(raw);
 need(restores==rawBefore+3,"three actual RestoreRoot calls in Raw bridge frame (Recon, Temporal motion, Consumer)");
 need(NrdBridge::GetStatus().framesBridged==bridgedBefore+1 && FfxApiProxy::dispatches==0,"exactly one frame bridged without RR in Raw mode");
 NrdBridge::SetDebugMode(NrdBridge::DebugMode::Off); const auto rrBefore=FfxApiProxy::dispatches,rrRestores=restores;
 FfxApiProxy::afterRealDispatch=disableRestoreFlagsAfterSDK; title.frame(3,6,1); FfxApiProxy::afterRealDispatch=nullptr;
 need(!Config::Instance()->RestoreComputeSignature.value && !Config::Instance()->ExtendedStateRestore.value,"fixture flips both restore flags after real SDK recording while injection is admitted");
 auto rr=title.finish(6,1); result["rr"]=title.rrChecks(rr);
 need(Config::Instance()->RestoreComputeSignature.value && Config::Instance()->ExtendedStateRestore.value,"active list Reset restores required volatile flags for the next title recording");
 result["config_reload"]={{"mid_sdk_flags_disabled",true},{"consumer_gpu_state_restored",true},{"next_reset_reasserts_flags",true}};
 need(FfxApiProxy::dispatches==rrBefore+1 && restores==rrRestores+3,"one real AMD RR call and three title restores per requested frame");
 need(NrdBridge::GetStatus().active,"real RR makes coordinator Active");
 const auto rrFirstFlags=FfxApiProxy::lastDispatch.flags; need((rrFirstFlags&FFX_DENOISER_DISPATCH_RESET)!=0,"first RR frame resets history");
 const auto offDispatches=FfxApiProxy::dispatches,offInternal=internalCalls(),offRestores=restores,offCreates=FfxApiProxy::creates;
 NrdBridge::SetRuntimeEnabled(false); title.frame(4,3,2,false); auto off=title.finish(3,2,false);
 need(title.sentinel(off),"runtime OFF keeps complete title NRD sentinel output");
 need(FfxApiProxy::dispatches==offDispatches && internalCalls()==offInternal && restores==offRestores,"runtime OFF records zero conversion/RR/restoration work");
 result["runtime_off"]={{"provider_dispatches",FfxApiProxy::dispatches-offDispatches},{"internal_detour_calls",internalCalls()-offInternal},{"restore_calls",restores-offRestores},{"nrdsentinel_untouched",true}};
 NrdBridge::SetRuntimeEnabled(true); title.frame(5); auto on=title.finish(); title.rrChecks(on);
 need(FfxApiProxy::dispatches==offDispatches+1 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"runtime ON recovers with reset and one RR call");
 need(FfxApiProxy::creates==offCreates,"submitted runtime OFF/ON retains the same physical RR context");
 title.frame(6); title.rrChecks(title.finish()); need((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==0,"consecutive submitted RR frame reuses valid history");
 NrdBridge::RequestHistoryReset(); title.frame(7); const auto beforeReplacement=title.finish(); title.rrChecks(beforeReplacement);
 need((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"menu reset reaches real AMD RR");
 // A title may replace a pair while the old resources remain alive in unrelated states.
 const auto oldOutputs=title.replaceOutputs();
 for(const auto& texture:oldOutputs) h.barrier(texture.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
 const auto beforeOutputSwap=FfxApiProxy::dispatches;
 title.frame(8); const auto oldSpec=title.readback(oldOutputs[0].Get(),D3D12_RESOURCE_STATE_COPY_SOURCE);
 const auto oldDiff=title.readback(oldOutputs[1].Get(),D3D12_RESOURCE_STATE_COPY_SOURCE);
 auto replaced=title.finish(); need(title.sentinel(replaced),"first changed Consumer pair keeps current native NRD outputs");
 need(FfxApiProxy::dispatches==beforeOutputSwap,"changed current Consumer identity cancels RR before any borrowed output write");
 need(oldSpec.signal()==beforeReplacement[0] && oldDiff.signal()==beforeReplacement[1],"old live outputs in COPY_SOURCE stay bit-identical");
 need(NrdBridge::gService->cache.Valid() && NrdBridge::gService->cache.Get().outputSpec==title.tex[7].Get(),"fresh chain publishes replacement output identities");
 title.frame(9); title.rrChecks(title.finish());
 need(FfxApiProxy::dispatches==beforeOutputSwap+1 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"replacement outputs recover with reset on next complete frame");
 // The old tagged MV is still alive, but belongs to unrelated UAV work. No stale read is legal.
 const auto oldMotion=title.replaceMotion(); h.barrier(oldMotion.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
 const auto beforeMotionSwap=FfxApiProxy::dispatches; title.frame(10,3,2,true,false); auto lateMotion=title.finish();
 need(title.sentinel(lateMotion) && FfxApiProxy::dispatches==beforeMotionSwap,"late SL motion tag fails closed without stale cached MV read or output replacement");
 NrdBridge::OnTitleTag(h.list.Get(),"MotionVectors",title.tex[6].Get()); NrdBridge::SetRuntimeEnabled(false); NrdBridge::SetRuntimeEnabled(true);
 title.frame(11); need(title.sentinel(title.finish()),"explicit recovery rediscovers current MV before RR resumes");
 title.frame(12); title.rrChecks(title.finish());
 need(FfxApiProxy::dispatches==beforeMotionSwap+1 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"current motion recovers with history reset after tag refresh");
 FrameSurvey::Released(title.tex[7].Get()); need(!NrdBridge::gService->cache.Valid(),"actual release observer invalidates a discovered borrowed output");
 const auto releasedPair=title.replaceOutputs(); title.frame(13); need(title.sentinel(title.finish()),"release replacement gets one safe discovery frame");
 title.frame(14); title.rrChecks(title.finish());
 result["live_replacement"]={{"old_output_state","COPY_SOURCE"},{"old_outputs_bit_identical",true},{"old_motion_state","UNORDERED_ACCESS"},
  {"late_motion_tag_safe",true},{"recovery_reset",true},{"release_rediscovers",true}};
 Title resized(h,96,64,true); const auto beforeResize=FfxApiProxy::creates;
 resized.frame(15); need(resized.sentinel(resized.finish()),"render extent change uses a safe discovery frame");
 resized.frame(16); const auto resizedRR=resized.finish(); const auto resizeStats=resized.rrChecks(resizedRR);
 need(FfxApiProxy::creates==beforeResize+1 && NrdBridge::GetStatus().width==96 && NrdBridge::GetStatus().height==64,"extent change recreates real provider context and guides at exact dimensions");
 result["resize"]={{"extent",{96,64}},{"provider_recreated",true},{"statistics",resizeStats}};
 resized.frame(17); resized.rrChecks(resized.finish()); need((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)==0,"submitted resized frame has valid consecutive history");
 const auto beforeDiscard=FfxApiProxy::dispatches,beforeDiscardCreates=FfxApiProxy::creates,beforeDiscardDestroys=FfxApiProxy::destroys;
 resized.frame(18); need(FfxApiProxy::dispatches==beforeDiscard+1,"real provider records complete frame before discard");
 hr(h.list->Close()); h.reset(); // Deliberately discard without BeforeSubmission or ExecuteCommandLists.
 resized.frame(19); resized.rrChecks(resized.finish());
 need((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"complete unsubmitted list discard resets depth and actual RR history");
 need(FfxApiProxy::creates==beforeDiscardCreates+1 && FfxApiProxy::destroys==beforeDiscardDestroys+1,"discard retires the physical real SDK context and creates exactly one fresh context before next RR");
 result["discarded_recording"]={{"complete_recordings_discarded",1},{"following_rr_reset",true},{"physical_context_creates",FfxApiProxy::creates-beforeDiscardCreates},{"physical_context_destroys",FfxApiProxy::destroys-beforeDiscardDestroys}};
 const auto beforeInputs=FfxApiProxy::dispatches; NrdBridge::SetDebugMode(NrdBridge::DebugMode::RRInputs);
 resized.frame(20); const auto inputsView=resized.finish(); bool inputFinite=true,inputAlpha=true;
 for(const auto& signal:inputsView) for(size_t i=0;i<signal.size();++i) {
  const auto value=PackedVector::XMConvertHalfToFloat(signal[i]); inputFinite &= std::isfinite(value) && value>=0 && value<=1;
  if(i%4==3) inputAlpha &= signal[i]==0;
 }
 const auto white=PackedVector::XMConvertFloatToHalf(1.f); const size_t last=size_t(resized.width-1)*4;
 need(inputFinite && inputAlpha,"RR inputs debug view contains finite bounded guides and zero alpha");
 need(inputsView[1][last]==white && inputsView[1][last+1]==white && inputsView[1][last+2]==white,"RR inputs debug view exposes actual white demodulated albedo band");
 need(FfxApiProxy::dispatches==beforeInputs,"RR inputs debug mode performs no provider dispatch");
 result["rr_inputs_debug"]={{"finite_bounded",inputFinite},{"alpha_zero",inputAlpha},{"white_albedo_band",true},{"provider_dispatches",0}};
 NrdBridge::SetDebugMode(NrdBridge::DebugMode::Off); resized.frame(21); resized.rrChecks(resized.finish());
 need((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"returning from guide debug mode resets actual RR history");
 // Simulate a provider reporting an error after its actual GPU commands have been recorded.
 const auto beforePartial=FfxApiProxy::dispatches;
 FfxApiProxy::partialFailure=true; resized.frame(22); FfxApiProxy::partialFailure=false;
 const auto partial=resized.finish();
 need(resized.sentinel(partial),"partial SDK work cannot alter either borrowed title output before successful commit");
 need(FfxApiProxy::dispatches==beforePartial+1 && !NrdBridge::GetStatus().active && !NrdBridge::gService->cache.Valid(),
  "provider error after real SDK recording fails closed and invalidates discovery");
 need(FfxApiProxy::lastSpecular.signal.output.resource!=resized.tex[7].Get() && FfxApiProxy::lastDiffuse.signal.output.resource!=resized.tex[8].Get(),
  "real provider writes only bridge-owned transaction outputs");
 NrdBridge::SetRuntimeEnabled(false); NrdBridge::SetRuntimeEnabled(true);
 resized.frame(23); need(resized.sentinel(resized.finish()),"partial-provider failure recovery first validates current title resources");
 resized.frame(24); resized.rrChecks(resized.finish());
 need(FfxApiProxy::dispatches==beforePartial+2 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,
  "partial-provider failure recovery uses reset and one successful transactional RR dispatch");
 result["partial_sdk_failure"]={{"real_sdk_commands_recorded",true},{"title_pair_bit_exact_nrd",true},{"provider_targets_owned",true},{"recovery_reset",true}};
 need(FfxApiProxy::badDefaults==0 && FfxApiProxy::defaults==7*FfxApiProxy::creates && FfxApiProxy::configures==FfxApiProxy::defaults,"actual provider defaults queried and applied exactly");
 need(FfxApiProxy::wrongRoute==0 && FfxApiProxy::routed[0]==FfxApiProxy::creates && FfxApiProxy::routed[3]==FfxApiProxy::dispatches,
  "actual proxy effect selectors route every RR create/dispatch to denoiser module");
 need(NrdBridge::gService->frame==23,"nested debug-layer COM forwarding counts each runtime-enabled Recon exactly once");
 need(FfxApiProxy::dispatches==14 && NrdBridge::GetStatus().framesBridged==15,"exact bridge/provider work count includes one deliberately unsubmitted recording and one real SDK error");
 need(internalBarriers>0 && titleTransitions==0,"conversion/motion/debug/real RR never transition a borrowed title texture");
 result["barrier_audit"]={{"internal_barriers_observed",internalBarriers},{"borrowed_title_transitions",titleTransitions}};
 result["owned_conversion_bytes"]=NrdBridge::gService->history->conversion.OwnedTextureBytes();
 result["owned_rr_staging_bytes"]=NrdBridge::gService->history->rr.OwnedStagingBytes();
 UINT64 directStagingBytes=0;
 for(void* pointer:{FfxApiProxy::lastSpecular.signal.output.resource,FfxApiProxy::lastDiffuse.signal.output.resource}) {
  auto* texture=static_cast<ID3D12Resource*>(pointer); const auto description=texture->GetDesc();
  need(description.Width==96 && description.Height==64 && description.Format==DXGI_FORMAT_R16G16B16A16_FLOAT,"transaction outputs match the current extent and exact signal format");
  directStagingBytes+=h.device->GetResourceAllocationInfo(0,1,&description).SizeInBytes;
 }
 constexpr UINT warmedTransactionSlots=4; // Production initializes four independent pairs; sequential submissions reuse them.
 need(NrdBridge::gService->history->rr.OwnedStagingBytes()==directStagingBytes*warmedTransactionSlots,"reported RR staging bytes equal independently queried pair allocations across all four warmed slots");
 result["rr_staging_allocation"]={{"independent_pair_bytes",directStagingBytes},{"warmed_slots",warmedTransactionSlots},{"total_bytes",directStagingBytes*warmedTransactionSlots}};
 std::vector<std::unique_ptr<Title>> deepTitles;deepCases(h,resized,result,deepTitles);
 result["provider"]={{"creates",FfxApiProxy::creates},{"dispatches",FfxApiProxy::dispatches},{"defaults",FfxApiProxy::defaults},{"configures",FfxApiProxy::configures}};
 result["proxy_routed_calls"]=FfxApiProxy::routed;
 result["title_restore_calls"]=restores; result["frames_bridged"]=NrdBridge::GetStatus().framesBridged;
 result["recon_callbacks"]=NrdBridge::gService->frame; result["submitted_rr_frames"]=FfxApiProxy::dispatches-4;
 result["submitted_cancelled_rr_records"]=2;
 result["submitted_partial_sdk_records"]=1;
 J identities=J::array(); for(const auto& [id,count]:detourDispatches) identities.push_back({{"this",id},{"external_dispatch_callbacks",count[0]},{"internal_dispatch_callbacks",count[1]}});
 result["detour_identities"]=identities;
 NrdBridge::Shutdown(); RecordedComputeLease::Poll(); need(FfxApiProxy::destroys==FfxApiProxy::creates,"all RR contexts retire after real GPU fences");
 result["provider"]["destroys"]=FfxApiProxy::destroys; need(FfxApiProxy::badCreateChains==0,"RR context descriptor chains stay alive until actual destroy");
 need(FfxApiProxy::contextToType.empty() && FfxApiProxy::routed[4]==FfxApiProxy::destroys,"actual proxy context map retires only after provider destruction");
 result["proxy_routed_calls"]=FfxApiProxy::routed;
 Wiring::Detach(); DetachRoots(); FrameSurvey::Shutdown(); const auto debug=h.debugCounts(); result["debug_errors"]=debug[0]; result["debug_warnings"]=debug[1]; result["native_checks"]=checks;
 std::ofstream(std::filesystem::path(argv[1])/"result.json")<<result.dump(2)<<'\n'; std::cout<<"PASS checks="<<checks<<" debug_errors="<<debug[0]<<" debug_warnings="<<debug[1]<<'\n'; return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
