"""Game-scale FrameSurvey CBV metadata benchmark with real WARP objects, no GPU dispatch.

10k/50k/100k cache records are local metadata emulation, mostly textures. Fake cache
objects are never passed to COM. The full-scan baseline receives a node counter only
in its scratch translation unit; repository production source is not modified.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_fsrd_nrd_root_restore import function

CPP=r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <psapi.h>
#include <chrono>
#include <thread>
#include <iostream>
#include <fstream>
#include <stdexcept>
#include "__TRACE__"
#include "__SURVEY__"
using Microsoft::WRL::ComPtr; using J=nlohmann::json;
unsigned checks=0;
bool gNrdBridgeWrappers=true;
void need(bool ok,const char* reason){if(!ok)throw std::runtime_error(reason);++checks;}
void hr(HRESULT value){if(FAILED(value))throw std::runtime_error("D3D12 HRESULT "+std::to_string(value));}
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point begin){return double(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-begin).count())/1e6;}
// The exact production hook bodies use native WARP forwarding. Legacy HUD/inspector helpers
// are inert adapters and their branches are disabled, isolating FrameSurvey additions.
struct Option {bool enabled=false;bool value_or_default()const{return enabled;}};
struct Config {Option ForceHDR,UseHDR10;Option FGHudfixDisableSRV{true},FGHudfixDisableUAV{true};static Config* Instance(){static Config c;return &c;}};
struct State {std::vector<ID3D12Resource*> scBuffers;static State& Instance(){static State s;return s;}};
enum ResourceKind {SRV,UAV};enum class CaptureInfo{CreateSRV,CreateUAV};
struct ResourceInfo {DXGI_FORMAT format=DXGI_FORMAT_UNKNOWN;ResourceKind type=SRV;CaptureInfo captureInfo=CaptureInfo::CreateSRV;};
struct HeapInfo {void ClearByCpuHandle(SIZE_T){}void SetByCpuHandle(SIZE_T,const ResourceInfo&){} };
HeapInfo* GetHeapByCpuHandleSRV(SIZE_T){return nullptr;}HeapInfo* GetHeapByCpuHandleUAV(SIZE_T){return nullptr;}
bool CheckResource(ID3D12Resource*){return false;}bool IsRRScalarCandidateResource(ID3D12Resource*,DXGI_FORMAT){return false;}
void TrackRRResourceView(ID3D12Resource*,DXGI_FORMAT,ResourceKind){}void FillResourceInfo(ID3D12Resource*,ResourceInfo*){}
std::atomic<bool> gRRResourceInspectorEnabled{false};
void forwardCBV(ID3D12Device* d,const D3D12_CONSTANT_BUFFER_VIEW_DESC* p,D3D12_CPU_DESCRIPTOR_HANDLE h){d->CreateConstantBufferView(p,h);}
void forwardSRV(ID3D12Device* d,ID3D12Resource* r,D3D12_SHADER_RESOURCE_VIEW_DESC* p,D3D12_CPU_DESCRIPTOR_HANDLE h){d->CreateShaderResourceView(r,p,h);}
void forwardUAV(ID3D12Device* d,ID3D12Resource* r,ID3D12Resource* c,D3D12_UNORDERED_ACCESS_VIEW_DESC* p,D3D12_CPU_DESCRIPTOR_HANDLE h){d->CreateUnorderedAccessView(r,c,p,h);}
auto o_CreateConstantBufferView=&forwardCBV;auto o_CreateShaderResourceView=&forwardSRV;auto o_CreateUnorderedAccessView=&forwardUAV;
__HOOKS__
struct Host {
 ComPtr<ID3D12Device> device; ComPtr<ID3D12CommandAllocator> allocator; ComPtr<ID3D12GraphicsCommandList> list;
 ComPtr<ID3D12Resource> buffer,texture; ComPtr<ID3D12DescriptorHeap> heap; ComPtr<ID3D12RootSignature> root;
 D3D12_CONSTANT_BUFFER_VIEW_DESC cbv {};D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc {};D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc {};
 D3D12_CPU_DESCRIPTOR_HANDLE cpu {}; UINT stride=0;
 Host(){
  ComPtr<ID3D12Debug> debug;if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
  ComPtr<IDXGIFactory4> factory;hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));ComPtr<IDXGIAdapter> warp;
  hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
  FrameSurvey::BeginCreationTracking(true);FrameSurvey::SetBindingWindow(false);FrameSurvey::SetReleaseObserver(nullptr);
  D3D12_RESOURCE_DESC d {};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=8192;d.Height=1;
  d.DepthOrArraySize=d.MipLevels=1;d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  D3D12_HEAP_PROPERTIES hp {};hp.Type=D3D12_HEAP_TYPE_UPLOAD;
  hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&buffer)));
  FrameSurvey::ResourceCreated(buffer.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
  d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=64;d.Height=32;d.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;
  d.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;hp.Type=D3D12_HEAP_TYPE_DEFAULT;
  hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&texture)));
  FrameSurvey::ResourceCreated(texture.Get(),D3D12_RESOURCE_STATE_COMMON);
  srvDesc.Format=d.Format;srvDesc.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srvDesc.Texture2D.MipLevels=1;srvDesc.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
  uavDesc.Format=d.Format;uavDesc.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
  D3D12_DESCRIPTOR_HEAP_DESC hd {};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=16;
  hr(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));FrameSurvey::HeapCreated(device.Get(),heap.Get());
  cpu=heap->GetCPUDescriptorHandleForHeapStart();stride=device->GetDescriptorHandleIncrementSize(hd.Type);
  cbv={buffer->GetGPUVirtualAddress(),1536};
  D3D12_ROOT_PARAMETER param {};param.ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;param.Descriptor={6,0};
  D3D12_ROOT_SIGNATURE_DESC rd {1,&param,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> bytes,error;
  hr(D3D12SerializeRootSignature(&rd,D3D_ROOT_SIGNATURE_VERSION_1,&bytes,&error));
  hr(device->CreateRootSignature(0,bytes->GetBufferPointer(),bytes->GetBufferSize(),IID_PPV_ARGS(&root)));
  FrameSurvey::RootCreated(root.Get(),bytes->GetBufferPointer(),bytes->GetBufferSize());
  hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
  hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
  list->SetComputeRootSignature(root.Get());list->SetComputeRootConstantBufferView(0,cbv.BufferLocation);
  FrameSurvey::RootBinding(list.Get(),false,root.Get());FrameSurvey::RootView(list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,cbv.BufferLocation);
 }
 ~Host(){FrameSurvey::Shutdown();}
 D3D12_CPU_DESCRIPTOR_HANDLE handle(UINT slot){auto h=cpu;h.ptr+=UINT64(slot)*stride;return h;}
 void nativeView(UINT slot=0){hkSurveyCreateConstantBufferView(device.Get(),&cbv,handle(slot));}
 void nativeSRV(){hkSurveyCreateShaderResourceView(device.Get(),texture.Get(),&srvDesc,handle(8));}
 void nativeUAV(){hkSurveyCreateUnorderedAccessView(device.Get(),texture.Get(),nullptr,&uavDesc,handle(9));}
 size_t visited(){
#if __INDEXED__
  const auto match=FrameSurvey::gBufferAddresses.Find(cbv.BufferLocation);
  need(match.matches==1 && match.object==buffer.Get(),"indexed direct search is the real current native buffer");return match.visited;
#else
  FrameSurvey::gBufferLookupVisitsForTesting=0;FrameSurvey::BoundConstantBuffer out;
  need(FrameSurvey::ResolveBufferAddress(cbv.BufferLocation,1536,1216,out) && out.resource==buffer.Get(),"baseline helper resolves actual native buffer");
  return FrameSurvey::gBufferLookupVisitsForTesting;
#endif
 }
};
#if __INDEXED__
// Opaque records below emulate creation metadata only. No fake pointer is ever passed to COM.
void cacheBuffer(ID3D12Resource* object,uint64_t address,uint64_t bytes){
 FrameSurvey::Resource r;r.id=++FrameSurvey::gNextResource;r.object=object;r.va=address;
 r.desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;r.desc.Width=bytes;r.desc.Height=1;
 r.desc.DepthOrArraySize=r.desc.MipLevels=1;r.desc.SampleDesc.Count=1;
 need(FrameSurvey::gResources.emplace(object,r).second,"adversarial buffer record is unique metadata");
 FrameSurvey::gAddresses.emplace(address,object);FrameSurvey::gBufferAddresses.Insert(address,bytes,r.id,object);
}
J adversarialIntervals(){
 const auto records=FrameSurvey::gResources.size(),intervals=FrameSurvey::gBufferAddresses.Size();
 constexpr uint64_t base=0x750000000000ull;FrameSurvey::BoundConstantBuffer out;
 auto* a=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x510000000000ull));
 auto* b=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x510000010000ull));
 cacheBuffer(a,base,65536);cacheBuffer(b,base+4096,256);
 need(!FrameSurvey::ResolveBufferAddress(base+4096,256,256,out),"different-start live overlap is ambiguous even when the shorter buffer would not cover a larger query");
 need(FrameSurvey::ResolveBufferAddress(base+8192,256,256,out)&&out.resource==a,"long buffer remains discoverable beyond a nearer short buffer");
 need(!FrameSurvey::ResolveBufferAddress(base+4096,512,512,out),"any live overlap rejects even if only one interval covers the requested length");
 FrameSurvey::Released(b);
 need(FrameSurvey::ResolveBufferAddress(base+4096,256,256,out)&&out.resource==a,"release removes only the overlapping short interval");
 FrameSurvey::Released(a);
 auto* c=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x510000020000ull));
 auto* d=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x510000030000ull));
 cacheBuffer(c,base,4096);cacheBuffer(d,base,4096);
 need(!FrameSurvey::ResolveBufferAddress(base,256,256,out),"same-start generations remain ambiguous");
 FrameSurvey::Released(c);
 need(FrameSurvey::ResolveBufferAddress(base,256,256,out)&&out.resource==d,"release of one same-start generation restores the surviving interval");
 const auto oldGeneration=out.resourceGeneration;FrameSurvey::Released(d);cacheBuffer(d,base,4096);
 need(FrameSurvey::ResolveBufferAddress(base,256,256,out)&&out.resource==d&&out.resourceGeneration!=oldGeneration,"reused opaque address resolves only the newly registered generation");
 FrameSurvey::Released(d);
 auto* spanning=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x510000040000ull));
 cacheBuffer(spanning,base,1048576);std::vector<ID3D12Resource*> shortBuffers;
 for(UINT i=0;i<1024;++i){auto* object=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x520000000000ull+uint64_t(i)*65536));
  cacheBuffer(object,base+4096+uint64_t(i)*512,256);shortBuffers.push_back(object);}
 need(FrameSurvey::ResolveBufferAddress(base+917504,256,256,out)&&out.resource==spanning,"augmented range search finds a long spanning interval hidden behind 1024 nearer starts");
 need(!FrameSurvey::ResolveBufferAddress(base+4096+uint64_t(1023)*512,256,256,out),"near interval inside the spanning interval remains ambiguous");
 FrameSurvey::Released(spanning);need(!FrameSurvey::ResolveBufferAddress(base+917504,256,256,out),"released spanning interval never survives through nearer-start lookup");
 for(auto* object:shortBuffers)FrameSurvey::Released(object);
 FrameSurveyMetadata::BufferAddressIndex isolated;
 isolated.Insert(256,0,1,a);isolated.Insert(0,512,2,a);isolated.Insert(256,512,0,a);isolated.Insert(256,512,3,nullptr);
 need(isolated.Size()==0,"zero ranges, addresses, generations and objects are ignored");
 isolated.Insert(UINT64_MAX-255,512,4,a);auto match=isolated.Find(UINT64_MAX);
 need(match.matches==1&&match.object==a&&match.generation==4,"saturated end-address index does not wrap to the beginning of the VA space");
 need(isolated.Find(256).matches==0,"overflow interval cannot falsely match a low address");
 isolated.Erase(UINT64_MAX-255,5);need(isolated.Size()==1,"erasing a stale generation preserves a live interval");
 isolated.Erase(UINT64_MAX-255,4);need(isolated.Size()==0,"exact generation erase removes the live interval");
 isolated.Insert(4096,256,6,a);isolated.Insert(4096,512,6,b);match=isolated.Find(4352);
 need(isolated.Size()==1&&match.matches==1&&match.object==b,"same-key update changes interval width and object without duplicate size");
 isolated.Clear();need(isolated.Size()==0&&isolated.Find(4096).matches==0,"index clear releases all metadata");
 need(FrameSurvey::gResources.size()==records&&FrameSurvey::gBufferAddresses.Size()==intervals,"adversarial release teardown preserves the native buffer registry");
 return {{"short_ranges_hiding_long_buffer",1024},{"different_start_overlap_rejected",true},{"same_start_overlap_rejected",true},
  {"generation_reuse_checked",true},{"overflow_saturation_checked",true}};
}
J mirrorOwnersScale(Host& h){
 constexpr size_t count=100000;const auto mirrorCount=FrameSurvey::gMirror.size(),ownerCount=FrameSurvey::gMirrorOwners.size();
 std::vector<ID3D12GraphicsCommandList*> lists;std::vector<ID3D12RootSignature*> roots;lists.reserve(count);roots.reserve(count);
 const auto insertion=Clock::now();
 for(size_t i=0;i<count;++i){
  auto* cmd=reinterpret_cast<ID3D12GraphicsCommandList*>(uintptr_t(0x530000000000ull+(i+1)*65536));
  auto* root=reinterpret_cast<ID3D12RootSignature*>(uintptr_t(0x540000000000ull+(i+1)*65536));
  FrameSurvey::Reset(cmd,nullptr);FrameSurvey::RootBinding(cmd,false,root);
  FrameSurvey::RootView(cmd,false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,h.cbv.BufferLocation);lists.push_back(cmd);roots.push_back(root);
 }
 const double insertionMs=ms(insertion);const size_t selected=50000;auto* cmd=lists[selected];auto* root=roots[selected];
 need(FrameSurvey::MetadataHealthy()&&FrameSurvey::gMirror.size()==mirrorCount+count,"100k local mirror records created through actual Reset/RootBinding/RootView callbacks");
 need(FrameSurvey::gMirrorOwners.at(root).size()==1&&FrameSurvey::gMirrorOwners.at(root).contains(cmd),"reverse ownership lists exactly the selected mirror");
 FrameSurvey::gMirrorReleaseVisitsForTesting=0;const auto release=Clock::now();FrameSurvey::Released(root);const double releaseMs=ms(release);
 const auto releaseVisits=FrameSurvey::gMirrorReleaseVisitsForTesting;
 need(releaseVisits==1,"actual production release invalidates one participant without walking 100k mirrors");
 need(!FrameSurvey::gMirror.at(cmd).compute.object&&FrameSurvey::gMirror.at(cmd).compute.views.empty(),"released root clears its current view bindings");
 need(FrameSurvey::gMirror.at(lists[selected-1]).compute.object==roots[selected-1]&&
  FrameSurvey::gMirror.at(lists[selected+1]).compute.views.at(0).second==h.cbv.BufferLocation,"unrelated adjacent mirror bindings survive selected release");
 FrameSurvey::RootBinding(cmd,false,root);FrameSurvey::Reset(cmd,nullptr);FrameSurvey::gMirrorReleaseVisitsForTesting=0;FrameSurvey::Released(root);
 need(FrameSurvey::gMirrorReleaseVisitsForTesting==0&&!FrameSurvey::gMirrorOwners.contains(root),"Reset removes stale reverse participants before a later root release");
 auto* pso=reinterpret_cast<ID3D12PipelineState*>(uintptr_t(0x550000000000ull));
 FrameSurvey::SetPipeline(cmd,pso);FrameSurvey::gMirrorReleaseVisitsForTesting=0;FrameSurvey::Released(pso);
 need(FrameSurvey::gMirrorReleaseVisitsForTesting==1&&!FrameSurvey::gMirror.at(cmd).pso,"pipeline release invalidates only the actual owner");
 auto* heap=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x560000000000ull));
 FrameSurvey::DescriptorHeaps(cmd,1,&heap);FrameSurvey::Table(cmd,false,5,{0x123400});
 FrameSurvey::gMirrorReleaseVisitsForTesting=0;FrameSurvey::Released(heap);
 need(FrameSurvey::gMirrorReleaseVisitsForTesting==1&&FrameSurvey::gMirror.at(cmd).heaps.empty()&&FrameSurvey::gMirror.at(cmd).compute.tables.empty(),"heap release touches its sole mirror and clears affected tables");
 FrameSurvey::gMirrorReleaseVisitsForTesting=0;FrameSurvey::Released(reinterpret_cast<void*>(uintptr_t(0x570000000000ull)));
 need(FrameSurvey::gMirrorReleaseVisitsForTesting==0,"unreferenced object release performs no mirror iteration");
 FrameSurvey::RootBinding(lists.back(),false,roots.back());FrameSurvey::Released(lists.back());
 need(!FrameSurvey::gMirror.contains(lists.back())&&!FrameSurvey::gMirrorOwners.contains(roots.back()),"released command list removes its reverse root participant");
 const auto teardown=Clock::now();for(auto* list:lists)FrameSurvey::Released(list);const double teardownMs=ms(teardown);
 need(FrameSurvey::gMirror.size()==mirrorCount&&FrameSurvey::gMirrorOwners.size()==ownerCount,"100k mirror teardown restores exact native mirror and owner counts");
 FrameSurvey::BoundConstantBuffer out;need(FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out)&&out.resource==h.buffer.Get(),"native command-list bindings survive all synthetic mirror releases");
 PROCESS_MEMORY_COUNTERS_EX pm {};GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pm),sizeof(pm));
 return {{"synthetic_mirrors",count},{"production_callback_insertion_ms",insertionMs},{"selected_root_release_ms",releaseMs},
  {"selected_release_mirrors_visited",releaseVisits},{"teardown_via_production_release_ms",teardownMs},{"peak_working_set_bytes",uint64_t(pm.PeakWorkingSetSize)}};
}
#endif
J measure(Host& h,size_t count){
 constexpr uint64_t fakeBase=0x700000000000ull;constexpr uintptr_t objectBase=uintptr_t(0x400000000000ull);
 need(h.cbv.BufferLocation<fakeBase || h.cbv.BufferLocation>=fakeBase+(count+1)*65536,"synthetic VA range never aliases real native buffer");
 const auto baseResources=FrameSurvey::gResources.size();std::vector<ID3D12Resource*> objects;objects.reserve(count);
 const auto insertionStart=Clock::now();size_t buffers=0;
 for(size_t i=0;i<count;++i){
  auto* object=reinterpret_cast<ID3D12Resource*>(objectBase+(i+1)*65536);FrameSurvey::Resource cache;
  cache.id=++FrameSurvey::gNextResource;cache.object=object;cache.desc.Width=4096;cache.desc.Height=1;
  cache.desc.DepthOrArraySize=cache.desc.MipLevels=1;cache.desc.SampleDesc.Count=1;
  if(i%10==0){cache.desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;cache.va=fakeBase+(i+1)*65536;++buffers;}
  else {cache.desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;cache.desc.Height=32;cache.desc.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;}
  need(FrameSurvey::gResources.emplace(object,cache).second,"synthetic cache key is unique and never queried through COM");
  if(cache.va){FrameSurvey::gAddresses.emplace(cache.va,object);
#if __INDEXED__
   FrameSurvey::gBufferAddresses.Insert(cache.va,cache.desc.Width,cache.id,object);
#endif
  }
  const uint64_t fakeHandle=0x600000000000ull+(i+1)*64;
  FrameSurvey::ViewInfo view {object,cache.id,cache.va?uint32_t(D3D12_DESCRIPTOR_RANGE_TYPE_CBV):uint32_t(D3D12_DESCRIPTOR_RANGE_TYPE_SRV),uint32_t(cache.desc.Format),0,!cache.va};
  view.descriptorCpu=fakeHandle;view.rootVa=cache.va;view.constantBytes=cache.va?1536:0;
  FrameSurvey::gViews.emplace(fakeHandle,view);
#if __INDEXED__
  FrameSurvey::IndexView(view);
#else
  FrameSurvey::gResources.at(object).handles.insert(fakeHandle);
#endif
  objects.push_back(object);
 }
 const double insertionMs=ms(insertionStart);const auto resources=FrameSurvey::gResources.size();need(resources==baseResources+count,"exact metadata cache size");
 need(!FrameSurvey::gRecording.load() && !FrameSurvey::BindingWindow(),"benchmark records no survey and has no NRD window");
 const size_t visits=h.visited();
#if __INDEXED__
 need(visits<resources,"indexed lookup does not visit every resource record");
#else
 need(visits==resources,"baseline deterministic full-resource walk visits every buffer and texture record");
#endif
 constexpr UINT iterations=1000;
 const auto nativeCBVStart=Clock::now();for(UINT i=0;i<iterations;++i)forwardCBV(h.device.Get(),&h.cbv,h.handle(10));const double forwardCbvMs=ms(nativeCBVStart);
 const auto nativeSRVStart=Clock::now();for(UINT i=0;i<iterations;++i)forwardSRV(h.device.Get(),h.texture.Get(),&h.srvDesc,h.handle(11));const double forwardSrvMs=ms(nativeSRVStart);
 const auto nativeUAVStart=Clock::now();for(UINT i=0;i<iterations;++i)forwardUAV(h.device.Get(),h.texture.Get(),nullptr,&h.uavDesc,h.handle(12));const double forwardUavMs=ms(nativeUAVStart);
 const auto callbackStart=Clock::now();
 for(UINT i=0;i<iterations;++i)h.nativeView();const double callbackMs=ms(callbackStart);
 const auto srvStart=Clock::now();for(UINT i=0;i<iterations;++i)h.nativeSRV();const double srvMs=ms(srvStart);
 const auto uavStart=Clock::now();for(UINT i=0;i<iterations;++i)h.nativeUAV();const double uavMs=ms(uavStart);
 need(FrameSurvey::gViews.at(h.handle(8).ptr).object==h.texture.Get() && FrameSurvey::gViews.at(h.handle(9).ptr).object==h.texture.Get(),"1000 exact production SRV/UAV wrappers preserve actual native resource identity");
 FrameSurvey::BoundConstantBuffer out;bool correct=true;const auto rootStart=Clock::now();
 for(UINT i=0;i<iterations;++i)correct=FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,out)&&out.resource==h.buffer.Get()&&correct;
 const double rootMs=ms(rootStart);need(correct,"all 1000 actual root CBV lookups resolve correct borrowed buffer");
 double threadedMs=0;
 if(count==100000){
  const auto threadsStart=Clock::now();std::vector<std::thread> threads;
  for(UINT thread=0;thread<4;++thread)threads.emplace_back([&,thread]{for(UINT i=0;i<iterations;++i)h.nativeView(thread+1);});
  for(auto& thread:threads)thread.join();threadedMs=ms(threadsStart);
  need(FrameSurvey::MetadataHealthy(),"four-thread native callback pressure preserves metadata health");
 }
 const auto teardownStart=Clock::now();for(auto* object:objects)FrameSurvey::Released(object);const double teardownMs=ms(teardownStart);
 need(FrameSurvey::gResources.size()==baseResources,"real release callback tears down every emulated cache record");
 need(h.visited()==baseResources || __INDEXED__,"baseline restored registry contains only actual native objects");
 PROCESS_MEMORY_COUNTERS_EX pm {};GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pm),sizeof(pm));
 return {{"synthetic_metadata_resources",count},{"texture_records",count-buffers},{"buffer_records",buffers},{"actual_resource_records",baseResources},
  {"resources_during_queries",resources},{"deterministic_lookup_nodes_visited",visits},{"callback_iterations",iterations},{"root_iterations",iterations},
  {"live_synthetic_views",count},{"insertion_ms",insertionMs},{"native_cbv_forward_ms",forwardCbvMs},{"native_srv_forward_ms",forwardSrvMs},{"native_uav_forward_ms",forwardUavMs},
  {"production_cbv_wrapper_ms",callbackMs},{"production_srv_wrapper_ms",srvMs},{"production_uav_wrapper_ms",uavMs},
  {"root_lookup_ms",rootMs},{"teardown_via_production_release_ms",teardownMs},
  {"four_threads_1000_views_each_ms",threadedMs},{"working_set_bytes",uint64_t(pm.WorkingSetSize)},{"peak_working_set_bytes",uint64_t(pm.PeakWorkingSetSize)}};
}
int main(int argc,char** argv)try{
 NrdBridgePerf::Configure([](const NrdBridgePerf::Report&) noexcept {});NrdBridgePerf::RenderedFrame(1);
 need(argc==2,"output path");g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Host h;J rows=J::array();
 J intervals,mirrors;
#if __INDEXED__
 intervals=adversarialIntervals();
#endif
 for(size_t size:{size_t(10000),size_t(50000),size_t(100000)})rows.push_back(measure(h,size));
#if __INDEXED__
 mirrors=mirrorOwnersScale(h);
#endif
 hr(h.list->Close());ComPtr<ID3D12InfoQueue> info;if(SUCCEEDED(h.device.As(&info))){
  for(UINT64 i=0;i<info->GetNumStoredMessagesAllowedByRetrievalFilter();++i){SIZE_T size=0;info->GetMessage(i,nullptr,&size);std::vector<uint8_t> data(size);
   auto* m=reinterpret_cast<D3D12_MESSAGE*>(data.data());info->GetMessage(i,m,&size);need(m->Severity>D3D12_MESSAGE_SEVERITY_ERROR,"native WARP debug-layer clean");}
 }
 J result={{"mode",__INDEXED__?"indexed":"3251_full_resource_scan"},{"scope","local metadata emulation plus actual WARP buffer/heap/root; zero GPU dispatch; no game cost claim"},
  {"checks_passed",checks},{"synthetic_objects_queried_through_com",false},{"gpu_dispatches",0},{"recording",false},{"binding_window",false},{"scales",rows},{"interval_regression",intervals},{"mirror_regression",mirrors}};
 std::ofstream(std::filesystem::path(argv[1])/"host-result.json")<<result.dump(2)<<'\n';std::cout<<result.dump()<<'\n';return0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return1;}
'''

def run():
    output=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/12a-discovery/tests/game-scale-cbv'));output.mkdir(parents=True,exist_ok=True)
    source_path=ROOT/'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp';source=source_path.read_text()
    original=function(source,'bool ResolveBufferAddress(');indexed='gBufferAddresses' in original
    if not indexed:
        needle='    for (const auto& [object,resource] : gResources)\n    {\n'
        assert original.count(needle)==1
        counted=original.replace(needle,needle+'        ++gBufferLookupVisitsForTesting;\n')
        assert counted.replace('        ++gBufferLookupVisitsForTesting;\n','')==original
        source=source.replace(original,'size_t gBufferLookupVisitsForTesting=0;\n'+counted)
    original_release=function(source,'void Released(')
    if indexed:
        release_needle='            for (auto* cmd : affected)'+chr(10)+'            {'+chr(10)
        assert original_release.count(release_needle)==1
        release_counter='                ++gMirrorReleaseVisitsForTesting;'+chr(10)
        counted_release=original_release.replace(release_needle,release_needle+release_counter)
        assert counted_release.replace(release_counter,'')==original_release
        source=source.replace(original_release,'size_t gMirrorReleaseVisitsForTesting=0;'+chr(10)+counted_release)
    instrumented=output/'FrameSurvey_instrumented.cpp';instrumented.write_text(source,encoding='utf-8')
    stubs=output/'stubs'
    for folder in ('proxies','inputs'):(stubs/folder).mkdir(parents=True,exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util {inline std::filesystem::path DllPath(){return g_dllPath;}}\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy {inline auto D3D12CreateVersionedRootSignatureDeserializer_(){return &D3D12CreateVersionedRootSignatureDeserializer;}inline auto D3D12SerializeVersionedRootSignature_(){return &D3D12SerializeVersionedRootSignature;}}\n')
    hook_source=(ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    hook_names=('hkCreateShaderResourceView','hkCreateUnorderedAccessView','hkSurveyCreateConstantBufferView','hkSurveyCreateShaderResourceView','hkSurveyCreateUnorderedAccessView')
    hook_bodies=[function(hook_source,'void ResTrack_Dx12::'+name+'(') for name in hook_names]
    hooks='\n'.join(body.replace('ResTrack_Dx12::','') for body in hook_bodies)
    cpp=CPP.replace('__TRACE__',(ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__',instrumented.as_posix()).replace('__INDEXED__',str(int(indexed))).replace('__HOOKS__',hooks)
    cpp=cpp.replace('return0;','return 0;').replace('return1;','return 1;')
    fixture=output/'fixture.cpp';fixture.write_text(cpp,encoding='utf-8');exe=output/'fixture.exe'
    compile_cpp(fixture,exe,('d3d12.lib','dxgi.lib','dxguid.lib','d3dcompiler.lib','bcrypt.lib','user32.lib','psapi.lib',str(ROOT/'OptiScaler/library/detours/detours.lib')),
     (stubs,ROOT/'OptiScaler',ROOT/'OptiScaler/resource_tracking',ROOT/'OptiScaler/include',ROOT/'external/streamline', ROOT/'external/nlohmann',ROOT/'external/nvngx_dlss_sdk',ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    subprocess.run([str(exe),str(output)],check=True,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    result=json.loads((output/'host-result.json').read_text());result['production_helper_sha256']=hashlib.sha256(original.encode()).hexdigest()
    result['production_source_sha256']=hashlib.sha256(source_path.read_bytes()).hexdigest()
    result['source_commit']=subprocess.check_output(['git','log','-1','--format=%H'],cwd=ROOT,text=True).strip()
    result['counter_instrumented_only_in_scratch']=True
    result['buffer_visit_counter_in_scratch']=not indexed
    result['mirror_release_visit_counter_in_scratch']=indexed
    result['production_release_sha256']=hashlib.sha256(original_release.encode()).hexdigest()
    result['production_hook_body_sha256']={name:hashlib.sha256(body.encode()).hexdigest() for name,body in zip(hook_names,hook_bodies)}
    result['legacy_base_helpers']='inert adapters; ForceHDR/inspector disabled, FGHudfixDisableSRV/UAV=true; exact production hook bodies executed'
    report=Path(os.environ.get('FSRD_TASK_REPORT_DIR','E:/FSRD/sol_batch/12a-discovery'));report.mkdir(parents=True,exist_ok=True)
    (report/('game-scale-cbv-'+('indexed' if indexed else 'baseline')+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':run()
