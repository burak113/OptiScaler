// Generated into the task scratch folder with the marked production functions inserted.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <json.hpp>
#include <algorithm>
#include <array>
#include <vector>
#include <string>
#include <mutex>
#include <shared_mutex>
#include <unordered_map>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include "__ROOT__/OptiScaler/hooks/Hook_Utils.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeTitleCallbacks_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
#include "__ROOT__/OptiScaler/include/detours/detours.h"
#define LOG_WARN(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
#define LOG_TRACE(...) ((void)0)
using Microsoft::WRL::ComPtr;
using J=nlohmann::json;
unsigned checks=0;
void need(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); ++checks; }
void hr(HRESULT value) { if(FAILED(value)) throw std::runtime_error("D3D12 HRESULT "+std::to_string(value)); }
std::vector<std::string> calls;
std::vector<J> layerTrace;
ID3D12GraphicsCommandList* watchedList=nullptr;
std::unordered_map<uint64_t,std::vector<std::string>> identityCalls;
void observe(ID3D12GraphicsCommandList* list,const char* event) {
 identityCalls[uint64_t(list)].push_back(event);
 if(list==watchedList) calls.push_back(event);
}
struct Option { bool current=false; bool value_or_default() const { return current; } };
struct Config {
 Option RestoreComputeSignature{true}, RestoreGraphicSignature{false}, ExtendedStateRestore{true};
 Option FfxDenoiserFrameSurvey{false};
 static Config* Instance() { static Config c; return &c; }
};
bool startupEnabled=false;
namespace FrameSurvey {
thread_local bool gInternal=false;
__INTERNAL_DECL__
__INTERNAL_IMPL__
void SetPipeline(ID3D12GraphicsCommandList* list,ID3D12PipelineState*) { if(!gInternal) observe(list,"survey.set"); }
void Pass(ID3D12GraphicsCommandList* list,const char*,std::array<uint64_t,3>) { if(!gInternal) observe(list,"survey.pass"); }
void SnapshotWrites(ID3D12GraphicsCommandList* list) { if(!gInternal) observe(list,"survey.snapshot"); }
void Reset(ID3D12GraphicsCommandList* list,ID3D12PipelineState*) { observe(list,"survey.reset"); }
void DescriptorHeaps(ID3D12GraphicsCommandList* list,UINT,ID3D12DescriptorHeap* const*) { if(!gInternal) observe(list,"survey.heaps"); }
void RootBinding(ID3D12GraphicsCommandList* list,bool,ID3D12RootSignature*) { if(!gInternal) observe(list,"survey.root"); }
void RootView(ID3D12GraphicsCommandList* list,bool,UINT,D3D12_DESCRIPTOR_RANGE_TYPE,D3D12_GPU_VIRTUAL_ADDRESS) { if(!gInternal) observe(list,"survey.view"); }
void Table(ID3D12GraphicsCommandList* list,bool,UINT,D3D12_GPU_DESCRIPTOR_HANDLE) { if(!gInternal) observe(list,"survey.table"); }
}
namespace NrdBridge {
unsigned callbacks=0,totalCallbacks=0;
bool StartupEnabled() { return startupEnabled; }
void count(ID3D12GraphicsCommandList* list,const char* event) { ++totalCallbacks; if(list==watchedList) ++callbacks; observe(list,event); }
void OnSetPipeline(ID3D12GraphicsCommandList* list,ID3D12PipelineState*) { count(list,"bridge.set"); }
void BeforeDispatch(ID3D12GraphicsCommandList* list) { count(list,"bridge.before"); }
void AfterDispatch(ID3D12GraphicsCommandList* list) { count(list,"bridge.after"); }
void OnReset(ID3D12GraphicsCommandList* list,ID3D12PipelineState*) { count(list,"bridge.reset"); }
}
bool gSurveyDeviceWrappers=false,gNrdBridgeDeviceWrappers=false;
__STATE__
struct D3D12Hooks {
 static void SetRootSignatureTracking(bool);
 static bool RootSignatureTrackingEnabled();
 static void OnBridgeCommandListReset(ID3D12GraphicsCommandList*,ID3D12PipelineState*);
 static bool CanRestoreRootSignature(ID3D12GraphicsCommandList*);
 static bool RestoreDescriptorHeaps(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestorePipelineState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestoreComputeRootState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static bool RestoreGraphicsRootState(ID3D12GraphicsCommandList*,const D3D12RootRestoreSnapshot&);
 static void RestoreRoot(ID3D12GraphicsCommandList*);
};
__TRACKERS__
__CONTROL__
namespace Wiring {
bool gSurveyWrappers=false,gNrdBridgeWrappers=false;
using ResetFn=HRESULT(WINAPI*)(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);
using DispatchFn=void(WINAPI*)(ID3D12GraphicsCommandList*,UINT,UINT,UINT);
ResetFn o_Reset=nullptr;
DispatchFn o_Dispatch=nullptr;
PFN_SetPipelineState o_SetPipelineState=nullptr;
PFN_SetComputeRootDescriptorTable o_SetComputeRootDescriptorTable=nullptr;
HRESULT hkReset(ID3D12GraphicsCommandList* list,ID3D12CommandAllocator* allocator,ID3D12PipelineState* pso) {
 observe(list,"legacy.reset"); return o_Reset(list,allocator,pso);
}
void hkSetPipelineState(ID3D12GraphicsCommandList* list,ID3D12PipelineState* pso) {
 layerTrace.push_back({{"layer","ResTrack"},{"this",uint64_t(list)}});
 observe(list,"legacy.set"); o_SetPipelineState(list,pso);
}
void hkSetComputeRootDescriptorTable(ID3D12GraphicsCommandList* list,UINT index,D3D12_GPU_DESCRIPTOR_HANDLE table) {
 observe(list,"legacy.table"); o_SetComputeRootDescriptorTable(list,index,table);
}
void hkDispatch(ID3D12GraphicsCommandList* list,UINT x,UINT y,UINT z) {
 observe(list,"legacy.dispatch"); o_Dispatch(list,x,y,z);
}
__WIRING__
void Attach(ID3D12GraphicsCommandList* list) {
 __SELECTORS__
 auto** table=*reinterpret_cast<void***>(list);
 o_SetPipelineState=reinterpret_cast<PFN_SetPipelineState>(table[25]);
 o_SetComputeRootDescriptorTable=reinterpret_cast<PFN_SetComputeRootDescriptorTable>(table[31]);
 o_Dispatch=reinterpret_cast<DispatchFn>(table[14]); o_Reset=reinterpret_cast<ResetFn>(table[10]);
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __RES_ATTACH__
 need(DetourTransactionCommit()==NO_ERROR,"production ResTrack detours attach");
}
void Detach() {
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __RES_DETACH__
 need(DetourTransactionCommit()==NO_ERROR,"production ResTrack detours detach");
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
 need(DetourTransactionCommit()==NO_ERROR,"production root detours attach");
}
void DetachRoots() {
 hr(DetourTransactionBegin()); hr(DetourUpdateThread(GetCurrentThread()));
 __D3D_DETACH__
 need(DetourTransactionCommit()==NO_ERROR,"production root detours detach");
}
struct Host {
 ComPtr<ID3D12Device> device;
 ComPtr<ID3D12GraphicsCommandList> list;
 ComPtr<ID3D12CommandAllocator> allocator;
 ComPtr<ID3D12CommandQueue> queue;
 ComPtr<ID3D12Fence> fence;
 ComPtr<ID3D12InfoQueue> info;
 bool debug=false;
 UINT64 tick=0;
 Host() {
  ComPtr<ID3D12Debug> layer;
  if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&layer)))) { layer->EnableDebugLayer(); debug=true; }
  ComPtr<IDXGIFactory4> factory; hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
  ComPtr<IDXGIAdapter1> adapter; hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
  hr(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
  device.As(&info);
  D3D12_COMMAND_QUEUE_DESC desc{}; hr(device->CreateCommandQueue(&desc,IID_PPV_ARGS(&queue)));
  hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
  hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
  hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
 }
 void execute() {
  hr(list->Close()); ID3D12CommandList* submitted[]={list.Get()}; queue->ExecuteCommandLists(1,submitted);
  hr(queue->Signal(fence.Get(),++tick));
  const auto end=GetTickCount64()+15000;
  while(fence->GetCompletedValue()<tick && GetTickCount64()<end) Sleep(1);
  need(fence->GetCompletedValue()>=tick,"GPU completed synthetic title and injection dispatches");
 }
 void reset(ID3D12PipelineState* pso=nullptr) { hr(allocator->Reset()); hr(list->Reset(allocator.Get(),pso)); }
 ComPtr<ID3D12Resource> buffer(D3D12_HEAP_TYPE type,UINT words,D3D12_RESOURCE_STATES state,bool uav=false) {
  D3D12_HEAP_PROPERTIES hp{}; hp.Type=type;
  D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; d.Width=std::max(256u,4*words);
  d.Height=d.DepthOrArraySize=d.MipLevels=d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  d.Flags=uav?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE;
  ComPtr<ID3D12Resource> r; hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&r))); return r;
 }
 ComPtr<ID3D12Resource> upload(UINT value) {
  auto r=buffer(D3D12_HEAP_TYPE_UPLOAD,64,D3D12_RESOURCE_STATE_GENERIC_READ); void* data=nullptr;
  hr(r->Map(0,nullptr,&data)); std::fill_n(static_cast<UINT*>(data),64,value); r->Unmap(0,nullptr); return r;
 }
 void barrier(ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
  D3D12_RESOURCE_BARRIER b{}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
  b.Transition={r,0,before,after}; list->ResourceBarrier(1,&b);
 }
 unsigned errors() {
  unsigned count=0;
  if(info) for(UINT64 i=0;i<info->GetNumStoredMessagesAllowedByRetrievalFilter();++i) {
   SIZE_T length=0; hr(info->GetMessage(i,nullptr,&length)); std::vector<uint8_t> bytes(length);
   auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data()); hr(info->GetMessage(i,message,&length));
   if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR) { std::cerr<<message->pDescription<<'\n'; ++count; }
  }
  return count;
 }
};
const char* titleShader=R"hlsl(
cbuffer C:register(b0) { uint4 First; uint4 Last; }
cbuffer Extra:register(b1) { uint Cbv; }
cbuffer Single:register(b2) { uint Singleton; }
StructuredBuffer<uint> A:register(t0); StructuredBuffer<uint> B:register(t1);
Texture2D<float> T:register(t2); SamplerState S:register(s0);
StructuredBuffer<uint> RootSrv:register(t3);
RWStructuredBuffer<uint> Out:register(u0); RWStructuredBuffer<uint> RootUav:register(u1);
[numthreads(1,1,1)] void main() {
 Out[0]=A[0]; Out[1]=B[0]; Out[2]=(uint)T.SampleLevel(S,float2(1.25,0.5),0);
 Out[3]=First.x; Out[4]=First.y; Out[5]=Last.x; Out[6]=Last.y;
 Out[7]=Cbv; Out[8]=RootSrv[0]; Out[9]=RootUav[0]; Out[10]=Singleton;
 RootUav[1]=123;
 RootUav[2]=RootUav[2]+1; Out[11]=RootUav[2];
})hlsl";
const char* injectionShader=R"hlsl(
RWStructuredBuffer<uint> Out:register(u0);
[numthreads(1,1,1)] void main() { for(uint i=0;i<11;++i) Out[i]=999; }
)hlsl";
struct Bindings {
 Host& h;
 ComPtr<ID3D12RootSignature> root;
 ComPtr<ID3D12PipelineState> pso;
 ComPtr<ID3D12DescriptorHeap> heap,samplers;
 ComPtr<ID3D12Resource> a,b,texture,textureUpload,cbv,srv,uav,uavUpload,output,readback;
 UINT increment=0;
 Bindings(Host& host,bool injected):h(host) {
  D3D12_DESCRIPTOR_RANGE ranges[5]{};
  for(UINT i=0;i<5;++i) {
   ranges[i].RangeType=i==4?D3D12_DESCRIPTOR_RANGE_TYPE_UAV:(i==3?D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER:D3D12_DESCRIPTOR_RANGE_TYPE_SRV);
   ranges[i].NumDescriptors=1; ranges[i].BaseShaderRegister=i<3?i:0;
  }
  D3D12_ROOT_PARAMETER params[10]{};
  params[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; params[0].Constants={0,0,injected?9u:8u};
  for(UINT i=1;i<=5;++i) { params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; params[i].DescriptorTable={1,&ranges[i-1]}; }
  params[6].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV; params[6].Descriptor={1,0};
  params[7].ParameterType=D3D12_ROOT_PARAMETER_TYPE_SRV; params[7].Descriptor={3,0};
  params[8].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV; params[8].Descriptor={1,0};
  params[9].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; params[9].Constants={2,0,1};
  D3D12_ROOT_SIGNATURE_DESC rd{10,params,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
  ComPtr<ID3DBlob> blob,error; hr(D3D12SerializeRootSignature(&rd,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error));
  hr(h.device->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)));
  rootSigParameterCount[root.Get()]=10;
  const auto* shader=injected?injectionShader:titleShader;
  ComPtr<ID3DBlob> cs; const auto compiled=D3DCompile(shader,strlen(shader),nullptr,nullptr,nullptr,"main","cs_5_0",0,0,&cs,&error);
  if(FAILED(compiled) && error) std::cerr<<static_cast<const char*>(error->GetBufferPointer()); hr(compiled);
  D3D12_COMPUTE_PIPELINE_STATE_DESC pd{}; pd.pRootSignature=root.Get(); pd.CS={cs->GetBufferPointer(),cs->GetBufferSize()};
  hr(h.device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso)));
  D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors=4; hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
  hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));
  hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER; hd.NumDescriptors=1; hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&samplers)));
  increment=h.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  a=h.upload(injected?101:11); b=h.upload(injected?102:22); cbv=h.upload(injected?106:66); srv=h.upload(injected?107:77);
  uav=h.buffer(D3D12_HEAP_TYPE_DEFAULT,64,D3D12_RESOURCE_STATE_COPY_DEST,true); uavUpload=h.upload(injected?108:88);
  h.list->CopyBufferRegion(uav.Get(),0,uavUpload.Get(),0,256); h.barrier(uav.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
  output=h.buffer(D3D12_HEAP_TYPE_DEFAULT,64,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,true);
  readback=h.buffer(D3D12_HEAP_TYPE_READBACK,64,D3D12_RESOURCE_STATE_COPY_DEST);
  D3D12_RESOURCE_DESC td{}; td.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; td.Width=2; td.Height=1;
  td.DepthOrArraySize=td.MipLevels=td.SampleDesc.Count=1; td.Format=DXGI_FORMAT_R32_FLOAT;
  D3D12_HEAP_PROPERTIES hp{}; hp.Type=D3D12_HEAP_TYPE_DEFAULT;
  hr(h.device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&td,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&texture)));
  textureUpload=h.buffer(D3D12_HEAP_TYPE_UPLOAD,64,D3D12_RESOURCE_STATE_GENERIC_READ);
  void* mapped=nullptr; hr(textureUpload->Map(0,nullptr,&mapped)); auto* floats=static_cast<float*>(mapped);
  floats[0]=injected?103.f:33.f; floats[1]=injected?104.f:44.f; textureUpload->Unmap(0,nullptr);
  D3D12_TEXTURE_COPY_LOCATION src{},dst{}; src.pResource=textureUpload.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
  src.PlacedFootprint.Footprint={DXGI_FORMAT_R32_FLOAT,2,1,1,256}; dst.pResource=texture.Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
  h.list->CopyTextureRegion(&dst,0,0,0,&src,nullptr); h.barrier(texture.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
  auto cpu=heap->GetCPUDescriptorHandleForHeapStart();
  D3D12_SHADER_RESOURCE_VIEW_DESC sv{}; sv.ViewDimension=D3D12_SRV_DIMENSION_BUFFER; sv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
  sv.Buffer.NumElements=64; sv.Buffer.StructureByteStride=4;
  h.device->CreateShaderResourceView(a.Get(),&sv,cpu); cpu.ptr+=increment;
  h.device->CreateShaderResourceView(b.Get(),&sv,cpu); cpu.ptr+=increment;
  sv={}; sv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D; sv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
  sv.Format=DXGI_FORMAT_R32_FLOAT; sv.Texture2D.MipLevels=1; h.device->CreateShaderResourceView(texture.Get(),&sv,cpu); cpu.ptr+=increment;
  D3D12_UNORDERED_ACCESS_VIEW_DESC uv{}; uv.ViewDimension=D3D12_UAV_DIMENSION_BUFFER; uv.Buffer.NumElements=64; uv.Buffer.StructureByteStride=4;
  h.device->CreateUnorderedAccessView(output.Get(),nullptr,&uv,cpu);
  D3D12_SAMPLER_DESC sampler{}; sampler.Filter=D3D12_FILTER_MIN_MAG_MIP_POINT;
  sampler.AddressU=sampler.AddressV=sampler.AddressW=injected?D3D12_TEXTURE_ADDRESS_MODE_CLAMP:D3D12_TEXTURE_ADDRESS_MODE_WRAP;
  sampler.MaxLOD=D3D12_FLOAT32_MAX; sampler.MaxAnisotropy=1; sampler.ComparisonFunc=D3D12_COMPARISON_FUNC_ALWAYS;
  h.device->CreateSampler(&sampler,samplers->GetCPUDescriptorHandleForHeapStart());
 }
 void bind(bool sparse) {
  auto* list=h.list.Get(); ID3D12DescriptorHeap* heaps[]={heap.Get(),samplers.Get()}; list->SetDescriptorHeaps(2,heaps);
  list->SetComputeRootSignature(root.Get()); auto gpu=heap->GetGPUDescriptorHandleForHeapStart();
  for(UINT i=1;i<=3;++i) { list->SetComputeRootDescriptorTable(i,gpu); gpu.ptr+=increment; }
  list->SetComputeRootDescriptorTable(4,samplers->GetGPUDescriptorHandleForHeapStart()); list->SetComputeRootDescriptorTable(5,gpu);
  list->SetComputeRootConstantBufferView(6,cbv->GetGPUVirtualAddress()); list->SetComputeRootShaderResourceView(7,srv->GetGPUVirtualAddress());
  list->SetComputeRootUnorderedAccessView(8,uav->GetGPUVirtualAddress());
  if(sparse) { const UINT first[]={10,20},last[]={40,50}; list->SetComputeRoot32BitConstants(0,2,first,0); list->SetComputeRoot32BitConstant(0,12,1);
   list->SetComputeRoot32BitConstants(0,2,last,4); list->SetComputeRoot32BitConstant(0,55,5); }
  else { const UINT all[]={10,12,0,0,40,55,0,0}; list->SetComputeRoot32BitConstants(0,8,all,0); }
  list->SetComputeRoot32BitConstant(9,99,0); list->SetPipelineState(pso.Get());
 }
 std::vector<UINT> read() {
  void* data=nullptr; D3D12_RANGE range{0,48}; hr(readback->Map(0,&range,&data));
  auto* words=static_cast<UINT*>(data); std::vector<UINT> result(words,words+12); readback->Unmap(0,nullptr); return result;
 }
};
void expect(const std::vector<std::string>& expected,const char* message) {
 if(calls!=expected) { for(const auto& c:calls) std::cerr<<c<<' '; std::cerr<<'\n'<<J(layerTrace).dump(2)<<'\n'; }
 need(calls==expected,message);
}
HRESULT WINAPI failedReset(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*) { return E_FAIL; }
J exercise(Host& h,bool enabled) {
 startupEnabled=enabled; NrdBridge::callbacks=NrdBridge::totalCallbacks=0; watchedList=h.list.Get();
 Bindings title(h,false),injection(h,true); AttachRoots(h.list.Get()); Wiring::Attach(h.list.Get());
 need(Wiring::gSurveyWrappers==enabled && gSurveyDeviceWrappers==enabled,"startup true chooses both production survey-wrapper sets");
 calls.clear(); title.bind(enabled);
 calls.clear(); layerTrace.clear(); h.list->SetPipelineState(title.pso.Get());
 expect(enabled?std::vector<std::string>{"survey.set","legacy.set","bridge.set"}:std::vector<std::string>{"legacy.set"},"actual SetPipelineState callback order for title COM identity");
 calls.clear(); h.list->Dispatch(1,1,1);
 expect(enabled?std::vector<std::string>{"bridge.before","survey.pass","legacy.dispatch","survey.snapshot","bridge.after"}:
  std::vector<std::string>{"legacy.dispatch"},"actual Dispatch callback order for title COM identity");
 J result; result["dispatch_order"]=calls;
 if(enabled) {
  need(D3D12Hooks::CanRestoreRootSignature(h.list.Get()),"complete title root snapshot permits injection");
  Config::Instance()->RestoreComputeSignature.current=false;
  need(!D3D12Hooks::CanRestoreRootSignature(h.list.Get()),"configuration reload disabling compute restore rejects bridge injection");
  h.list->SetComputeRootSignature(injection.root.Get());
  need(signatures[h.list.Get()].ptr==injection.root.Get() && bridgeComputeRoots[h.list.Get()]==injection.root.Get(),
       "title root changes during disabled restoration still update the bridge snapshot");
  need(rootStates[h.list.Get()][0].type==RootEntryType::Invalid,"disabled-period root switch invalidates all stale root arguments");
  h.list->SetComputeRootSignature(title.root.Get());
  need(signatures[h.list.Get()].ptr==title.root.Get() && bridgeComputeRoots[h.list.Get()]==title.root.Get(),
       "latest title root is remembered before restoration becomes enabled again");
  Config::Instance()->RestoreComputeSignature.current=true;
  title.bind(true);
  Config::Instance()->ExtendedStateRestore.current=false;
  need(!D3D12Hooks::CanRestoreRootSignature(h.list.Get()),"configuration reload disabling extended restore rejects bridge injection");
  Config::Instance()->ExtendedStateRestore.current=true;
  need(D3D12Hooks::CanRestoreRootSignature(h.list.Get()),"both restore flags recover bridge preflight without clobbering title state");
  D3D12_RESOURCE_BARRIER barriers[2]{};
  barriers[0].Type=barriers[1].Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
  barriers[0].UAV.pResource=title.output.Get(); barriers[1].UAV.pResource=title.uav.Get(); h.list->ResourceBarrier(2,barriers);
  const auto saved=rootStates[h.list.Get()]; const auto before=NrdBridge::totalCallbacks;
  need(saved[0].ValidConstants==std::vector<uint8_t>({1,1,0,0,1,1}),"sparse mask preserves unwritten constant gap");
  need(saved[8].type==RootEntryType::UAV && saved[8].bufferLocation==title.uav->GetGPUVirtualAddress(),"early production root UAV hook captured title address");
  calls.clear(); const bool prior=D3D12Hooks::RootSignatureTrackingEnabled();
  { FrameSurvey::ScopedInternal internal; D3D12Hooks::SetRootSignatureTracking(false);
   { FrameSurvey::ScopedInternal nested; need(FrameSurvey::Internal(),"nested internal scope is active"); }
   need(FrameSurvey::Internal(),"nested internal scope restores enclosing guard");
   injection.bind(false); h.list->Dispatch(1,1,1);
   need(calls.empty(),"injected COM setters/dispatch bypass bridge/survey/legacy callback spies");
   need(NrdBridge::totalCallbacks==before,"internal injection bypasses role and dispatch callbacks for every COM identity");
   need(rootStates[h.list.Get()][0].Data==saved[0].Data && rootStates[h.list.Get()][0].ValidConstants==saved[0].ValidConstants,
        "injected constants never overwrite title snapshot");
   need(signatures[h.list.Get()].ptr==title.root.Get() && pipelineStates[h.list.Get()]==title.pso.Get(),"injected root signature and PSO never overwrite title snapshot");
   need(descriptorHeaps[h.list.Get()].Heaps[0]==title.heap.Get() && descriptorHeaps[h.list.Get()].Heaps[1]==title.samplers.Get(),"injected heaps never overwrite title snapshot");
   for(UINT i=1;i<=9;++i) need(rootStates[h.list.Get()][i].rootDescriptorTable.ptr==saved[i].rootDescriptorTable.ptr &&
     rootStates[h.list.Get()][i].bufferLocation==saved[i].bufferLocation && rootStates[h.list.Get()][i].Data==saved[i].Data,"every title root argument survives shader clobber");
   Config::Instance()->RestoreComputeSignature.current=false;
   Config::Instance()->ExtendedStateRestore.current=false;
   D3D12Hooks::RestoreRoot(h.list.Get()); D3D12Hooks::SetRootSignatureTracking(prior);
  }
  need(!Config::Instance()->RestoreComputeSignature.current && !Config::Instance()->ExtendedStateRestore.current,
       "in-flight reload keeps its settings while the admitted injection restores every title binding");
  Config::Instance()->RestoreComputeSignature.current=true;
  Config::Instance()->ExtendedStateRestore.current=true;
  need(!FrameSurvey::Internal() && D3D12Hooks::RootSignatureTrackingEnabled(),"both production guards restore title tracking");
  need(calls.empty(),"RestoreRoot calls original trampolines without recursive callbacks");
  result["injection_did_not_change_tracking"]=true;
  h.list->Dispatch(1,1,1);
 }
 h.barrier(title.output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
 h.list->CopyBufferRegion(title.readback.Get(),0,title.output.Get(),0,48); h.execute();
 auto words=title.read(); result["gpu_title_dispatches"]=words.back()-88;
 need(words.back()==UINT(enabled?90:89),"COM forwarding recorded exactly one GPU dispatch per requested title dispatch");
 words.pop_back(); result["restored_words"]=words;
 const std::vector<UINT> expected={11,22,33,10,12,40,55,66,77,88,99};
 need(words==expected,"title GPU shader consumes exact PSO/heaps/tables/sparse constants/root CBV/SRV/UAV after RestoreRoot");
 if(enabled) {
  const auto saved=rootStates[h.list.Get()][0]; const auto callbacks=NrdBridge::totalCallbacks;
  const auto original=Wiring::o_Reset; Wiring::o_Reset=&failedReset; calls.clear();
  const auto failed=Wiring::hkSurveyReset(h.list.Get(),h.allocator.Get(),title.pso.Get()); Wiring::o_Reset=original;
  need(failed==E_FAIL,"failed original Reset result is preserved");
  expect({"legacy.reset"},"failed Reset has no survey/bridge lifecycle callbacks");
  need(NrdBridge::totalCallbacks==callbacks,"failed Reset never advances discovery state");
  need(rootStates[h.list.Get()][0].Data==saved.Data && rootStates[h.list.Get()][0].ValidConstants==saved.ValidConstants &&
       signatures[h.list.Get()].ptr==title.root.Get() && descriptorHeaps[h.list.Get()].Heaps[0]==title.heap.Get(),"failed Reset retains exact title root snapshot");
 }
 calls.clear(); h.reset(title.pso.Get());
 expect(enabled?std::vector<std::string>{"legacy.reset","survey.reset","bridge.reset"}:std::vector<std::string>{"legacy.reset"},"actual Reset callback order for title COM identity");
 if(enabled) {
  need(!rootStates.contains(h.list.Get()) && !signatures.contains(h.list.Get()) && !descriptorHeaps.contains(h.list.Get()),"Reset removes title binding caches");
  need(pipelineStates[h.list.Get()]==title.pso.Get(),"Reset preserves the actual initial PSO");
  h.list->SetComputeRootSignature(title.root.Get()); h.list->SetComputeRoot32BitConstant(0,1234,2);
  const auto& sparse=rootStates[h.list.Get()][0];
  need(sparse.Data==std::vector<UINT>({0,0,1234}) && sparse.ValidConstants==std::vector<uint8_t>({0,0,1}),"Reset starts a fresh sparse constant mask");
  result["after_reset"]["sparse_mask"]=sparse.ValidConstants;
  h.list->SetComputeRootSignature(injection.root.Get());
  need(rootStates[h.list.Get()][0].type==RootEntryType::Invalid,"new root signature invalidates prior root arguments");
  need(!D3D12Hooks::CanRestoreRootSignature(h.list.Get()),"incomplete signature fails restore preflight");
 }
  need(NrdBridge::totalCallbacks==NrdBridge::callbacks,"forwarded title calls report bridge callbacks once across all COM identities");
  std::unordered_map<uint64_t,bool> resIdentities;
  for(const auto& layer:layerTrace) if(layer["layer"]=="ResTrack") resIdentities[layer["this"].get<uint64_t>()]=true;
  need(resIdentities.size()>=2,"WARP debug forwarding genuinely traverses different COM This pointers");
 result["bridge_callbacks"]=NrdBridge::callbacks;
 result["all_com_identities_bridge_callbacks"]=NrdBridge::totalCallbacks;
 result["hook_layers"]=layerTrace;
 Wiring::Detach(); DetachRoots();
 // No references retained beyond recording; this list is reset before local resources die.
 h.execute(); h.reset();
 signatures.clear(); rootStates.clear(); bridgeComputeRoots.clear(); descriptorHeaps.clear(); pipelineStates.clear(); rootSigParameterCount.clear();
 return result;
}
int main(int argc,char** argv) try {
 need(argc==2,"scratch output path"); Host host; J result;
 result["disabled"]=exercise(host,false); result["enabled"]=exercise(host,true);
 result["debug_layer_available"]=host.debug; result["debug_error_count"]=host.errors();
 need(host.debug,"D3D12 debug layer available"); need(result["debug_error_count"]==0,"D3D12 debug layer clean");
 result["native_checks"]=checks; result["adapter"]="WARP";
 std::ofstream(std::filesystem::path(argv[1])/"result.json")<<result.dump(2)<<'\n'; std::cout<<result.dump()<<'\n'; return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
