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
#include <unordered_map>
#include <unordered_set>
#include "__ROOT__/OptiScaler/hooks/Hook_Utils.h"
#include "__ROOT__/OptiScaler/include/detours/detours.h"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeTitleCallbacks_Dx12.h"
#include "hooks/D3D12_Hooks.h"
using Microsoft::WRL::ComPtr;
using J=nlohmann::json;
unsigned checks=0,restores=0;
std::function<void()> emitDebug;
void need(bool value,const char* message) { if(!value) throw std::runtime_error(message); ++checks; }
void RecordTestProviderWrites(ID3D12GraphicsCommandList*,ID3D12Resource*,ID3D12Resource*) { throw std::runtime_error("End-to-end fixture requires real signed provider work"); }
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
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __D3D_ATTACH__
 need(DetourTransactionCommit()==NO_ERROR,"actual D3D12 root trackers attached");
}
void DetachRoots() {
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __D3D_DETACH__
 need(DetourTransactionCommit()==NO_ERROR,"actual D3D12 root trackers detached");
}

#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp"
#include "__ROOT__/OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgePass_Dx12.cpp"
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp"
#define FSRD_NRD_BRIDGE_TEST
#include "__ROOT__/OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.cpp"
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
struct Host {
 ComPtr<ID3D12Device> device; ComPtr<ID3D12GraphicsCommandList> list;
 ComPtr<ID3D12CommandAllocator> allocator; ComPtr<ID3D12CommandQueue> queue;
 ComPtr<ID3D12Fence> fence; ComPtr<ID3D12InfoQueue> info;
 std::vector<ComPtr<ID3D12Resource>> uploads;
 UINT64 tick=0; std::string adapter;
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
  hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
  RecordedComputeLease::SetHooksAvailable(true,true);
 }
 void submit() {
  hr(list->Close()); ComPtr<IUnknown> identity; hr(list.As(&identity));
  auto pending=RecordedComputeLease::BeforeSubmission(queue.Get(),{identity.Get()});
  ID3D12CommandList* cmd=list.Get(); queue->ExecuteCommandLists(1,&cmd); RecordedComputeLease::AfterSubmission(pending);
  hr(queue->Signal(fence.Get(),++tick)); const auto end=GetTickCount64()+60000;
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
cbuffer BufferValue:register(b2) { uint CB; };
cbuffer Extent:register(b6) { uint Width,Height; };
Texture2D<float4> S0:register(t0); Texture2D<float4> S1:register(t1);
Texture2D<float4> S2:register(t2);
SamplerState Samp:register(s0);
StructuredBuffer<uint> RootSRV:register(t0,space1);
RWStructuredBuffer<uint> Checks:register(u0,space1);
RWTexture2D<float4> U0:register(u0); RWTexture2D<float4> U1:register(u1);
[numthreads(8,8,1)] void main(uint3 p:SV_DispatchThreadID) {
 if(any(p.xy>=uint2(Width,Height))) return;
 if(ROLE==2) { U0[p.xy]=S0.Load(int3(p.xy,0)); U1[p.xy]=S1.Load(int3(p.xy,0)); }
 if(ROLE==9) { U0[p.xy]=float4(.75,.5,.25,0); U1[p.xy]=float4(.625,.375,.125,0); }
 if(all(p.xy==0)) {
  uint base=ROLE*16; Checks[base+0]=C0; Checks[base+1]=C1; Checks[base+2]=C2; Checks[base+3]=C5;
  Checks[base+4]=CB; Checks[base+5]=RootSRV[0]; Checks[base+6]=Width; Checks[base+7]=Height;
  Checks[base+8]=(uint)round(S0.Load(int3(0,0,0)).x*65536);
  Checks[base+9]=ROLE; Checks[base+10]=(uint)round(S0.SampleLevel(Samp,float2(.5/Width,.5/Height),0).x*65536);
  InterlockedAdd(Checks[base+11],1);
  if(ROLE==10) { Checks[base+12]=asuint(U0[uint2(0,0)].x); Checks[base+13]=asuint(U1[uint2(0,0)].x); }
  if(ROLE==4) Checks[base+14]=asuint(S2.Load(int3(0,0,0)).x);
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
 Host& h; UINT width,height,increment=0; bool registered;
 ComPtr<ID3D12RootSignature> root; std::array<ComPtr<ID3D12PipelineState>,11> pso;
 std::array<ComPtr<ID3D12Resource>,13> tex;
 std::array<std::vector<uint16_t>,2> raw;
 ComPtr<ID3D12DescriptorHeap> staging,visible,sampler;
 ComPtr<ID3D12Resource> cb,rootSrv,checksum;
 ~Title() { for(const auto& texture:tex) titleTextures.erase(texture.Get()); }
 Title(Host& host,UINT w,UINT height_,bool metadata):h(host),width(w),height(height_),registered(metadata) {
  D3D12_DESCRIPTOR_RANGE ranges[3]={{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,8,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,5,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER,1,0,0,0}};
  D3D12_ROOT_PARAMETER p[8]{}; p[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; p[0].Constants={0,0,8};
  p[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[1].DescriptorTable={1,&ranges[0]};
  p[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV; p[2].Descriptor={2,0};
  p[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV; p[3].Descriptor={0,1};
  p[4].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV; p[4].Descriptor={0,1};
  p[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[5].DescriptorTable={1,&ranges[1]};
  p[6].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; p[6].Constants={6,0,2};
  p[7].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; p[7].DescriptorTable={1,&ranges[2]};
  D3D12_ROOT_SIGNATURE_DESC desc{8,p,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE}; ComPtr<ID3DBlob> blob,error;
  hr(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error));
  hr(h.device->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
  rootSigParameterCount[root.Get()]=8; // Equivalent device creation-hook metadata, isolated from its adapter setup.
  if(registered) FrameSurvey::RootCreated(root.Get(),blob->GetBufferPointer(),blob->GetBufferSize());
  for(UINT role=1;role<11;++role) {
   ComPtr<ID3DBlob> cs; const std::string number=std::to_string(role); D3D_SHADER_MACRO defines[]={{"ROLE",number.c_str()},{nullptr,nullptr}};
   const auto result=D3DCompile(titleShader,sizeof(titleShader),nullptr,defines,nullptr,"main","cs_5_1",D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&cs,&error);
   if(FAILED(result) && error) std::cerr<<static_cast<const char*>(error->GetBufferPointer())<<'\n'; hr(result);
   D3D12_COMPUTE_PIPELINE_STATE_DESC pd{}; pd.pRootSignature=root.Get(); pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
   hr(h.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso[role])));
   if(registered) { FrameSurvey::PipelineCreated(pso[role].Get(),pd); NrdBridge::RegisterPipelineRoleForTesting(pso[role].Get(),Role(role)); }
  }
  cb=h.upload(55); rootSrv=h.upload(66); checksum=h.buffer(1024,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,true);
  createTextures(); D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors=64;
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
 }
 void copyDescriptors() {
  for(const auto& range:std::array<std::array<UINT,2>,7>{{{0,8},{8,5},{16,8},{24,5},{32,5},{40,5},{48,5}}}) {
   const UINT count=range[1]; const D3D12_CPU_DESCRIPTOR_HANDLE src{staging->GetCPUDescriptorHandleForHeapStart().ptr+uint64_t(range[0])*increment};
   const D3D12_CPU_DESCRIPTOR_HANDLE dst{visible->GetCPUDescriptorHandleForHeapStart().ptr+uint64_t(range[0])*increment};
   h.device->CopyDescriptors(1,&dst,&count,1,&src,&count,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
   if(registered) FrameSurvey::CopyDescriptors(h.device.Get(),1,&dst,&count,1,&src,&count,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  }
 }
 void begin(UINT frame,bool tagMotion=true) {
  StreamlineHooks::snapshot=camera(frame,width,height);
  if(registered && tagMotion) NrdBridge::OnTitleTag(h.list.Get(),"MotionVectors",tex[6].Get());
  auto zero=h.upload(0,1024); h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_DEST);
  h.list->CopyBufferRegion(checksum.Get(),0,zero.Get(),0,1024); h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS); h.uploads.push_back(zero);
  h.list->SetComputeRootSignature(root.Get()); ID3D12DescriptorHeap* heaps[]={visible.Get(),sampler.Get()}; h.list->SetDescriptorHeaps(2,heaps);
  const UINT first[]={11,22,30}, dimensions[]={width,height}; h.list->SetComputeRoot32BitConstants(0,3,first,0);
  h.list->SetComputeRoot32BitConstant(0,40,5); h.list->SetComputeRoot32BitConstant(0,33,2);
  h.list->SetComputeRootConstantBufferView(2,cb->GetGPUVirtualAddress()); h.list->SetComputeRootShaderResourceView(3,rootSrv->GetGPUVirtualAddress());
  h.list->SetComputeRootUnorderedAccessView(4,checksum->GetGPUVirtualAddress()); h.list->SetComputeRoot32BitConstants(6,2,dimensions,0);
  h.list->SetComputeRootDescriptorTable(7,sampler->GetGPUDescriptorHandleForHeapStart());
 }
 void pass(Role role,UINT uav=24,bool probe=false) {
  h.list->SetPipelineState(pso[UINT(role)].Get());
  // PrepLast wakes a new bounded window before title descriptor copies.
  if(role==Role::PrepLast) copyDescriptors();
  h.list->SetComputeRootDescriptorTable(1,{visible->GetGPUDescriptorHandleForHeapStart().ptr+uint64_t(role==Role::Temporal?16:0)*increment});
  h.list->SetComputeRootDescriptorTable(5,{visible->GetGPUDescriptorHandleForHeapStart().ptr+uint64_t(uav)*increment});
  h.list->Dispatch((width+7)/8,(height+7)/8,1); h.uav(checksum.Get());
  if(probe) {
   // No title state is set between the preceding injected RestoreRoot and this GPU check.
   // Bypass coordinator recursion using the real native trampoline, as a separate requested probe dispatch.
   FrameSurvey::ScopedInternal internal; Wiring::o_Dispatch(h.list.Get(),(width+7)/8,(height+7)/8,1); h.uav(checksum.Get());
  }
 }
 void frame(UINT id,UINT a=3,UINT b=2,bool probe=true,bool tagMotion=true) {
  begin(id,tagMotion); pass(Role::PrepLast); pass(Role::Recon,8,probe); h.uav(tex[4].Get()); h.uav(tex[5].Get());
  pass(Role::PrePass); pass(Role::Temporal,24,probe); pass(Role::Chain3); pass(Role::HistSave); pass(Role::HistFix); pass(Role::Clamp);
  for(UINT i=0;i<a;++i) { pass(Role::ATrous,i+1==a?32:24); h.uav(tex[i+1==a?7:9].Get()); h.uav(tex[i+1==a?8:10].Get()); }
  pass(Role::PrePass); pass(Role::Temporal); pass(Role::Clamp);
  for(UINT i=0;i<b;++i) { pass(Role::ATrous,40); h.uav(tex[11].Get()); h.uav(tex[12].Get()); }
  h.uav(tex[7].Get()); h.uav(tex[8].Get()); pass(Role::Consumer,48);
 }
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
 std::array<std::vector<uint16_t>,2> finish(UINT a=3,UINT b=2,bool probe=true) {
  auto spec=readback(7),diff=readback(8); auto read=h.buffer(1024,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
  h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
  h.list->CopyBufferRegion(read.Get(),0,checksum.Get(),0,1024); h.barrier(checksum.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  h.submit(); void* data=nullptr; hr(read->Map(0,nullptr,&data)); const auto* words=static_cast<const UINT*>(data);
  for(UINT role=1;role<11;++role) {
   const std::array<UINT,11> wanted={11,22,33,40,55,66,width,height,2048,role,2048};
   need(std::equal(wanted.begin(),wanted.end(),words+role*16),"title GPU sees exact sparse constants, CBV, root SRV/UAV, descriptor and sampler heaps/PSO");
   const UINT count=role==2?(probe?2:1):role==4?(probe?3:2):role==3 || role==8?2:role==9?a+b:1;
   need(words[role*16+11]==count,"each requested title shader executes exactly once, including distinct post-conversion probe");
   if(role==4) need(words[role*16+14]==0,"Temporal and post-motion probe read exactly the current MV descriptor at p1+2");
  }
  read->Unmap(0,nullptr); auto result=std::array<std::vector<uint16_t>,2>{spec.signal(),diff.signal()}; h.reset(); return result;
 }
 bool sentinel(const std::array<std::vector<uint16_t>,2>& data) const {
  for(UINT signal=0;signal<2;++signal) {
   const std::array<float,4> values=signal==0?std::array<float,4>{.75f,.5f,.25f,0}:std::array<float,4>{.625f,.375f,.125f,0};
   for(size_t i=0;i<data[signal].size();++i) if(data[signal][i]!=PackedVector::XMConvertFloatToHalf(values[i%4])) return false;
  }
  return true;
 }
 J rawChecks(const std::array<std::vector<uint16_t>,2>& data) const {
  bool rgb=true,alpha=true;
  for(UINT signal=0;signal<2;++signal) for(size_t i=0;i<data[signal].size();++i) {
   if(i%4==3) alpha &= data[signal][i]==0; else rgb &= data[signal][i]==raw[signal][i];
  }
  need(rgb,"Raw debug mode copies exact reconstructed half RGB"); need(alpha,"Raw debug mode writes documented zero alpha");
  return {{"exact_rgb",rgb},{"alpha_zero",alpha},{"rgb_values_checked",uint64_t(width)*height*6}};
 }
 J rrChecks(const std::array<std::vector<uint16_t>,2>& data) const {
  UINT64 finite=0,total=0; double sum=0; bool nonnegative=true;
  for(const auto& signal:data) for(size_t i=0;i<signal.size();++i) {
   const float value=PackedVector::XMConvertHalfToFloat(signal[i]); ++total; if(std::isfinite(value)) ++finite;
   if(i%4!=3) { sum+=value; nonnegative &= value>=0 && value<2; }
  }
  const auto mean=sum/(uint64_t(width)*height*6);
  need(finite==total,"real signed RR output is entirely finite"); need(nonnegative,"synthetic low-radiance RR RGB remains in plausible nonnegative bounds");
  need(mean>.005 && mean<.25,"real RR synthetic mean remains plausible"); need(!sentinel(data),"real RR overwrites native NRD sentinels");
  return {{"finite_values",finite},{"total_values",total},{"mean_rgb",mean},{"rgb_minimum_bound",0},{"rgb_maximum_bound",2}};
 }
};
unsigned internalCalls() { unsigned count=0; for(const auto& [_,value]:detourDispatches) count+=value[1]; return count; }
void disableRestoreFlagsAfterSDK() {
 Config::Instance()->RestoreComputeSignature.value=false; Config::Instance()->ExtendedStateRestore.value=false;
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
 need(argc==3,"scratch folder and signed AMD DLL arguments"); g_dllPath=std::filesystem::path(argv[1])/"fixture.dll"; Host h;
 requestedList=h.list.Get(); J result; result["adapter"]=h.adapter;
 need(!NrdBridge::Initialize(h.device.Get()),"startup OFF allocates no coordinator");
 AttachRoots(h.list.Get()); Wiring::Attach(h.list.Get());
 {
  Title disabled(h,128,128,false); disabled.frame(0,3,2,false); auto output=disabled.finish(3,2,false);
  need(disabled.sentinel(output),"startup OFF leaves title NRD output untouched"); need(!NrdBridge::gService,"startup OFF has no bridge owner");
  need(FfxApiProxy::creates==0 && FfxApiProxy::dispatches==0 && restores==0,"startup OFF allocates/dispatched/restored no bridge work");
  result["startup_off"]={{"provider_creates",0},{"provider_dispatches",0},{"restore_calls",0},{"nrdsentinel_untouched",true}};
 }
 Wiring::Detach(); DetachRoots(); Config::Instance()->FfxDenoiserNrdBridge.value=true;
 loadProvider(argv[2]);
 FrameSurvey::BeginCreationTracking(false); need(FrameSurvey::Install(h.device.Get(),h.list.Get(),false),"real metadata-only survey installed");
 need(NrdBridge::Initialize(h.device.Get()),"production coordinator initialized"); AttachRoots(h.list.Get()); Wiring::Attach(h.list.Get());
 Title title(h,128,128,true);
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
 const auto offDispatches=FfxApiProxy::dispatches,offInternal=internalCalls(),offRestores=restores;
 NrdBridge::SetRuntimeEnabled(false); title.frame(4,3,2,false); auto off=title.finish(3,2,false);
 need(title.sentinel(off),"runtime OFF keeps complete title NRD sentinel output");
 need(FfxApiProxy::dispatches==offDispatches && internalCalls()==offInternal && restores==offRestores,"runtime OFF records zero conversion/RR/restoration work");
 result["runtime_off"]={{"provider_dispatches",FfxApiProxy::dispatches-offDispatches},{"internal_detour_calls",internalCalls()-offInternal},{"restore_calls",restores-offRestores},{"nrdsentinel_untouched",true}};
 NrdBridge::SetRuntimeEnabled(true); title.frame(5); auto on=title.finish(); title.rrChecks(on);
 need(FfxApiProxy::dispatches==offDispatches+1 && (FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"runtime ON recovers with reset and one RR call");
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
 const auto beforeDiscard=FfxApiProxy::dispatches; resized.frame(18); need(FfxApiProxy::dispatches==beforeDiscard+1,"real provider records complete frame before discard");
 hr(h.list->Close()); h.reset(); // Deliberately discard without BeforeSubmission or ExecuteCommandLists.
 resized.frame(19); resized.rrChecks(resized.finish());
 need((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0,"complete unsubmitted list discard resets depth and actual RR history");
 result["discarded_recording"]={{"complete_recordings_discarded",1},{"following_rr_reset",true}};
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
 result["owned_conversion_bytes"]=NrdBridge::gService->conversion.OwnedTextureBytes();
 result["owned_rr_staging_bytes"]=NrdBridge::gService->rr.OwnedStagingBytes();
 UINT64 directStagingBytes=0;
 for(void* pointer:{FfxApiProxy::lastSpecular.signal.output.resource,FfxApiProxy::lastDiffuse.signal.output.resource}) {
  auto* texture=static_cast<ID3D12Resource*>(pointer); const auto description=texture->GetDesc();
  need(description.Width==96 && description.Height==64 && description.Format==DXGI_FORMAT_R16G16B16A16_FLOAT,"transaction outputs match the current extent and exact signal format");
  directStagingBytes+=h.device->GetResourceAllocationInfo(0,1,&description).SizeInBytes;
 }
 need(NrdBridge::gService->rr.OwnedStagingBytes()==directStagingBytes,"reported RR staging bytes equal independent device allocation queries");
 result["provider"]={{"creates",FfxApiProxy::creates},{"dispatches",FfxApiProxy::dispatches},{"defaults",FfxApiProxy::defaults},{"configures",FfxApiProxy::configures}};
 result["proxy_routed_calls"]=FfxApiProxy::routed;
 result["title_restore_calls"]=restores; result["frames_bridged"]=NrdBridge::GetStatus().framesBridged;
 result["recon_callbacks"]=NrdBridge::gService->frame; result["submitted_rr_frames"]=FfxApiProxy::dispatches-2;
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
