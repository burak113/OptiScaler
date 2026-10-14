"""Actual View/Release hook contention with native D3D12 objects and 100k records.

The large registry is explicitly metadata emulation. Only actual native objects
reach COM/native hooks. No shader dispatch or ExecuteCommandLists occurs. Legacy
HUD and RR-inspector seams are inert. Actual lease/Birth/retirement helpers run.
Native forwarding is explicit: this fixture does not measure Detours installation.
Run through run_task_test.py (GPU lock required even for this object-only fixture).
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fsrd_nrd_root_restore import function
import test_fsrd_frame_survey_game_scale as native

BASELINE = '6edf7d3d1c639250db6534496227fc91fc3e5306'

ADAPTER = r'''
#include "misc/NrdBridgeLifetime_Dx12.h"
#include "__RELEASE_HEADER__"
// Native helper and lease registry are production. HUD and RR cache adapters are
// inactive; explicit wrapper forwarding avoids installing recursively into COM.
__BASELINE_FAILURE_ADAPTER__
__USE_NATIVE__
namespace D3D12Hooks {inline void OnBridgeCommandListReset(ID3D12GraphicsCommandList*,ID3D12PipelineState*){}inline void OnBridgeObjectReleased(const NrdBridgeBirth::Token&)noexcept{}}
bool gSurveyWrappers=true;
struct TrackedResourceSlot {std::weak_ptr<HeapInfo> heap;uint64_t heapVersion=0;UINT index=0;};
NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> _trackedResourcesMutex;
std::unordered_map<ID3D12Resource*,std::vector<TrackedResourceSlot>> _trackedResources;
NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> gRRResourceStateMutex,gRRTrackedResourceMutex,gRRPsoMutex;
std::unordered_set<ID3D12Resource*> gRRResourceStates,gRRResourceActivity,gRRTrackedResources;
void CleanupRRResourcePsoProducersLocked(ID3D12Resource*){}void CleanupRRPsoReferences(void*){}void DeactivateSharedHeap(void*){}
struct PausedNativeRelease {
 void* object=nullptr;std::atomic<unsigned> calls{0};std::promise<void> entered,resume;
 std::shared_future<void> resumeFuture=resume.get_future().share();
};
std::atomic<PausedNativeRelease*> gPausedNativeRelease{nullptr};
void PauseAfterNativeRelease(void* object){auto* pause=gPausedNativeRelease.load();if(pause&&pause->object==object&&pause->calls.fetch_add(1)==0){pause->entered.set_value();pause->resumeFuture.wait();}}
ULONG forwardRelease(ID3D12Resource* object){ULONG result;{OriginalForwardTimer time;result=object->Release();}PauseAfterNativeRelease(object);return result;}auto o_Release=&forwardRelease;
ULONG forwardHeapRelease(ID3D12DescriptorHeap* object){ULONG result;{OriginalForwardTimer time;result=object->Release();}PauseAfterNativeRelease(object);return result;}auto o_HeapRelease=&forwardHeapRelease;
std::atomic<bool> gHeapReleaseSharesResource=false;
ULONG(*gSharedResourceReleaseObserver)(ID3D12Resource*)=nullptr;
NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> heapPoolMutex;
std::unordered_map<ID3D12DescriptorHeap*,std::shared_ptr<HeapInfo>> heapPool;
std::shared_ptr<HeapInfo> FindTrackedHeapByAddress(void* object){std::scoped_lock lock(heapPoolMutex);auto it=heapPool.find(static_cast<ID3D12DescriptorHeap*>(object));return it==heapPool.end()?nullptr:it->second;}
bool DeactivateTrackedHeap(const std::shared_ptr<HeapInfo>& info){std::scoped_lock lock(heapPoolMutex);return heapPool.erase(info->heap)!=0;}
__NATIVE_RETIREMENT__
namespace NrdBridgeNativeBirth {
bool ObserveReleaseCoverage(IUnknown* object)noexcept{
 if(!object||NrdBridgeBirth::InMetadataScope())return false;
 const auto address=uintptr_t(object);
 if(address>=0x400000000000ull&&address<0x400200000000ull)std::terminate(); // synthetic metadata never reaches COM
 const auto entry=(*reinterpret_cast<void***>(object))[2];
 static std::mutex installation;static std::array<void*,16> entries{};
 std::scoped_lock lock(installation);for(auto known:entries)if(known==entry)return true;
 for(auto& known:entries)if(!known){known=entry;return true;}return false;
}
}
__RELEASE__
__HEAP_RELEASE__
'''

DRIVER = r'''
#include <barrier>
#include <numeric>
std::atomic<uint64_t> observedReleases{0};
void onRelease(void*)noexcept{observedReleases.fetch_add(1,std::memory_order_relaxed);}
void onBirthRelease(const NrdBridgeBirth::Token&)noexcept{if(NrdBridgeBirth::InMetadataScope())std::terminate();onRelease(nullptr);}
uint64_t qpc(){LARGE_INTEGER value{};QueryPerformanceCounter(&value);return uint64_t(value.QuadPart);}
uint64_t frequency(){LARGE_INTEGER value{};QueryPerformanceFrequency(&value);return uint64_t(value.QuadPart);}
uint64_t rss(){PROCESS_MEMORY_COUNTERS_EX pm{};GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pm),sizeof(pm));return uint64_t(pm.WorkingSetSize);}
uint64_t peakRss(){PROCESS_MEMORY_COUNTERS_EX pm{};GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pm),sizeof(pm));return uint64_t(pm.PeakWorkingSetSize);}
constexpr size_t samples=4096,logicalRecords=100000;
constexpr bool candidate=__CANDIDATE__,bornMode=__BORN__;
enum Event {CBV,SRVEvent,UAVEvent,ResourceRelease,HeapRelease,CopyBurst,Events};
const std::array<const char*,Events> eventNames{"CBV","SRV","UAV","resource_release","pooled_heap_release","copy_burst"};
struct Observation {std::array<std::vector<uint64_t>,Events> ticks;std::array<std::array<std::vector<uint64_t>,size_t(NrdBridgePerf::WaitKind::Count)>,Events> waits;std::array<std::array<std::vector<uint64_t>,size_t(FrameSurveyMetadata::MetadataLock::Count)>,Events> metadataLocks;std::vector<uint64_t> finalTicks,nonfinalTicks;};
std::array<NrdBridgePerf::Sample,size_t(NrdBridgePerf::Hook::Count)> counters(){
 std::array<NrdBridgePerf::Sample,size_t(NrdBridgePerf::Hook::Count)> out{};
 const auto& state=NrdBridgePerf::Detail::Get();for(size_t i=0;i<out.size();++i){out[i].calls=state.hooks[i].calls.load();out[i].ticks=state.hooks[i].ticks.load();for(size_t j=0;j<out[i].waitTicks.size();++j)out[i].waitTicks[j]=state.hooks[i].waitTicks[j].load();}return out;
}
J percentile(std::vector<uint64_t> values){
 if(values.empty())return{{"samples",0}};
 std::sort(values.begin(),values.end());const double scale=1000000.0/double(frequency());
 const double sum=std::accumulate(values.begin(),values.end(),0.0);
 return{{"samples",values.size()},{"total_us",sum*scale},{"mean_us",sum*scale/values.size()},
  {"p50_us",values[values.size()/2]*scale},{"p95_us",values[size_t((values.size()-1)*.95)]*scale},
  {"p99_us",values[size_t((values.size()-1)*.99)]*scale},{"max_us",values.back()*scale}};
}
ComPtr<ID3D12Resource> buffer(ID3D12Device* device){
 D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=8192;desc.Height=1;
 desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
 D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_UPLOAD;ComPtr<ID3D12Resource> out;
 hr(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&out)));return out;
}
void restart(Host& h){
 FrameSurvey::Shutdown();FrameSurvey::BeginCreationTracking(false);FrameSurvey::SetBindingWindow(false);
 FrameSurvey::ResourceCreated(h.buffer.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
 FrameSurvey::ResourceCreated(h.texture.Get(),D3D12_RESOURCE_STATE_COMMON);FrameSurvey::HeapCreated(h.device.Get(),h.heap.Get());
 if(bornMode){
  auto token=NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(h.root.Get(),&NrdBridgeNativeBirth::ObserveReleaseCoverage);
  FrameSurvey::PreparedRoot prepared{h.root.Get(),std::make_shared<FrameSurvey::RootLayout>(FrameSurvey::ReadRoot(h.root.Get()))};
  need(FrameSurvey::PublishRootMetadata(prepared,token),"actual native root metadata reseeded with current birth");
  FrameSurvey::SetBirthReleaseObserver(&onBirthRelease);
 }else FrameSurvey::gRootLayouts.emplace(h.root.Get(),FrameSurvey::ReadRoot(h.root.Get()));
 FrameSurvey::SetReleaseObserver(&onRelease);
}
std::atomic<uint64_t> indirectForwards{0};
void STDMETHODCALLTYPE indirectForward(ID3D12GraphicsCommandList*,ID3D12CommandSignature*,UINT,ID3D12Resource*,UINT64,ID3D12Resource*,UINT64){need(FrameSurvey::Internal(),"Indirect native forwarding preserves internal suppression");++indirectForwards;}
void startupAndIndirectRegressions(Host& h,bool profile){
 FrameSurvey::Shutdown();gNrdBridgeWrappers=gSurveyWrappers=false;
 const auto before=counters();
 for(UINT i=0;i<1000;++i){hkSurveyCreateConstantBufferView(h.device.Get(),&h.cbv,h.handle(0));hkSurveyCreateShaderResourceView(h.device.Get(),h.texture.Get(),&h.srvDesc,h.handle(1));hkSurveyCreateUnorderedAccessView(h.device.Get(),h.texture.Get(),nullptr,&h.uavDesc,h.handle(2));}
 need(FrameSurvey::gResources.empty()&&FrameSurvey::gViews.empty()&&FrameSurvey::gHeaps.empty(),"startupOFF1000 nativeView calls each never allocate new registry metadata");
 FrameSurvey::oIndirect=&indirectForward;FrameSurvey::Indirect(h.list.Get(),nullptr,0,nullptr,0,nullptr,0);
 const auto after=counters();for(size_t i=0;i<4;++i)need(after[i].calls==before[i].calls,"startupOFF physical wrappers create no measured bridge hook scope");
 gNrdBridgeWrappers=gSurveyWrappers=true;restart(h);FrameSurvey::oIndirect=&indirectForward;
 const auto index=size_t(NrdBridgePerf::Hook::ExecuteIndirect);const auto count=NrdBridgePerf::Detail::Get().hooks[index].calls.load();
 FrameSurvey::Indirect(h.list.Get(),nullptr,0,nullptr,0,nullptr,0);
 need(NrdBridgePerf::Detail::Get().hooks[index].calls.load()==count+uint64_t(candidate&&profile),"actualIndirect profiler captures startupON only while sampling, frozenbaseline records none");
 {FrameSurvey::ScopedInternal owned;FrameSurvey::Indirect(h.list.Get(),nullptr,0,nullptr,0,nullptr,0);}
 need(NrdBridgePerf::Detail::Get().hooks[index].calls.load()==count+uint64_t(candidate&&profile),"ownedIndirect forwarding never contributes another title hook sample");
 need(indirectForwards.load()==3,"startupOFF/ON/internalIndirect all forward exactly once");
}
void metadataRegressions(Host& h){
 const auto releasedBefore=observedReleases.load();
 {FrameSurvey::ScopedInternal owned;FrameSurvey::Released(h.texture.Get());}
 if(candidate)need(observedReleases.load()==releasedBefore&&FrameSurvey::gResources.contains(h.texture.Get()),"owned final Release bypasses actual metadata and observer reentry");
 else{need(observedReleases.load()==releasedBefore+1&&!FrameSurvey::gResources.contains(h.texture.Get()),"frozenbaseline explicitly reproduces owned observer reentry bug");FrameSurvey::ResourceCreated(h.texture.Get(),D3D12_RESOURCE_STATE_COMMON);}
 const auto titleBefore=observedReleases.load();
 {FrameSurvey::ScopedRecording titleAlias;FrameSurvey::Released(h.texture.Get());}
 need(observedReleases.load()==titleBefore+1&&!FrameSurvey::gResources.contains(h.texture.Get()),"ordinary title recording aliases still retire metadata and notify observer");
 FrameSurvey::ResourceCreated(h.texture.Get(),D3D12_RESOURCE_STATE_COMMON);
 FrameSurvey::SetBindingWindow(true);FrameSurvey::Reset(h.list.Get(),nullptr);FrameSurvey::RootBinding(h.list.Get(),false,h.root.Get());
 FrameSurvey::RootView(h.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,h.cbv.BufferLocation);
 FrameSurvey::BoundConstantBuffer base;
 need(FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,base)&&base.resource==h.buffer.Get(),"native root b6 resolves exact live buffer");
 auto old=buffer(h.device.Get());FrameSurvey::ResourceCreated(old.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
 D3D12_CONSTANT_BUFFER_VIEW_DESC desc{old->GetGPUVirtualAddress(),1536};
 hkSurveyCreateConstantBufferView(h.device.Get(),&desc,h.handle(1));
 FrameSurvey::RootView(h.list.Get(),false,0,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,desc.BufferLocation);
 FrameSurvey::BoundConstantBuffer token;
 need(FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,token)&&token.resource==old.Get(),"native current root resolves newly registered upload buffer");
 UINT one=1;auto src=h.handle(1),dst=h.handle(2);
 h.device->CopyDescriptorsSimple(1,dst,src,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 FrameSurvey::CopyDescriptors(h.device.Get(),1,&dst,&one,1,&src,&one,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 hkSurveyCreateConstantBufferView(h.device.Get(),&h.cbv,h.handle(1));
 need(FrameSurvey::gViews.at(src.ptr).object==h.buffer.Get()&&FrameSurvey::gViews.at(dst.ptr).object==old.Get(),"overwrite detaches only old source ownership, copied slot still belongs to old buffer");
 auto* retired=old.Detach();need(hkRelease(retired)==0,"actual native final resource Release");
 need(!FrameSurvey::gViews.contains(dst.ptr)&&FrameSurvey::gViews.at(src.ptr).object==h.buffer.Get(),"old final release removes copied slot and preserves overwritten current slot");
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(token),"released staged CBV generation fails pure metadata validation without COM");
 hkSurveyCreateConstantBufferView(h.device.Get(),nullptr,src);
 need(!FrameSurvey::gViews.contains(src.ptr),"native null CBV tombstones previous live slot");
 // An exclusive reader which already passed the healthy precheck must wait for
 // shared copy writers and then reject their partial/allocation-failed metadata.
 hkSurveyCreateShaderResourceView(h.device.Get(),h.texture.Get(),&h.srvDesc,h.handle(4));
 hkSurveyCreateShaderResourceView(h.device.Get(),h.texture.Get(),&h.srvDesc,h.handle(5));
 std::promise<void> entered,done;auto enteredFuture=entered.get_future(),doneFuture=done.get_future();std::atomic<bool> accepted{true};
 std::jthread reader;
 {
  __SHARED_COPY_GUARD__
  reader=std::jthread([&]{entered.set_value();accepted=FrameSurvey::ValidateBorrowedConstantBuffer(base);done.set_value();});
  enteredFuture.wait();need(doneFuture.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout,"snapshot reader waits for entire in-progress copy callback");
  UINT two=2;auto from=h.handle(4),to=h.handle(6);FrameSurvey::gCopyFailureAfterForTesting=1;
  h.device->CopyDescriptorsSimple(2,to,from,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  FrameSurvey::CopyDescriptors(h.device.Get(),1,&to,&two,1,&from,&two,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  need(!FrameSurvey::MetadataHealthy(),"partial copy failure latches unhealthy before writer releases catalog");
 }
 doneFuture.wait();reader.join();need(!accepted,"reader rechecks health after draining failed concurrent copy");
 need(!FrameSurvey::ValidateBorrowedConstantBuffer(base),"failed metadata stays quarantined until device restart");
 restart(h);need(FrameSurvey::MetadataHealthy(),"clean device metadata restart restores health");
}
struct Cache {
 std::vector<ID3D12Resource*> objects;size_t prior;
 explicit Cache(Host& h):prior(FrameSurvey::gResources.size()){
  objects.reserve(logicalRecords);
  for(size_t i=0;i<logicalRecords;++i){auto* object=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x400000000000ull+(i+1)*65536));
   FrameSurvey::Resource r;r.id=++FrameSurvey::gNextResource;r.object=object;r.desc.Width=8192;r.desc.Height=1;
   r.desc.DepthOrArraySize=r.desc.MipLevels=1;r.desc.SampleDesc.Count=1;
   if(i%10==0){r.desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;r.va=0x700000000000ull+(i+1)*65536;}
   else{r.desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;r.desc.Height=32;r.desc.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;}
   need(FrameSurvey::gResources.emplace(object,r).second,"unique synthetic metadata record; never passed to COM");
   if(r.va){FrameSurvey::gAddresses.emplace(r.va,object);FrameSurvey::gBufferAddresses.Insert(r.va,r.desc.Width,r.id,object);}
   const uint64_t slot=0x600000000000ull+(i+1)*64;FrameSurvey::ViewInfo view{object,r.id,r.va?uint32_t(D3D12_DESCRIPTOR_RANGE_TYPE_CBV):uint32_t(D3D12_DESCRIPTOR_RANGE_TYPE_SRV),uint32_t(r.desc.Format),0,!r.va};
   view.descriptorCpu=slot;view.rootVa=r.va;view.constantBytes=r.va?1536:0;
   FrameSurvey::gViews.emplace(slot,view);FrameSurvey::IndexView(view);_trackedResources.emplace(object,std::vector<TrackedResourceSlot>{});objects.push_back(object);
  }
  need(FrameSurvey::gResources.size()==prior+logicalRecords,"100k logical resources plus actual native objects live together");
  need(!FrameSurvey::gRecording.load()&&!FrameSurvey::BindingWindow(),"normal hot path has no recorder and closed binding window");
  need(rss()<2ull*1024*1024*1024,"registry fixture stays below2GB resident memory budget");
  const auto hit=FrameSurvey::gBufferAddresses.Find(h.cbv.BufferLocation);need(hit.matches==1&&hit.object==h.buffer.Get(),"native CBV VA resolves amid100k logical records");
 }
 ~Cache(){for(auto* object:objects){FrameSurvey::Released(object);_trackedResources.erase(object);}}
};
struct WorkerPool {
 std::vector<ID3D12Resource*> finals;std::vector<ID3D12DescriptorHeap*> heaps;bool observed=false;
 explicit WorkerPool(Host& h,size_t worker,bool wrappers):observed(wrappers){
  finals.reserve(samples/8);heaps.reserve(samples/128);
  for(size_t i=0;i<samples/8;++i){auto resource=buffer(h.device.Get());
   if(wrappers){FrameSurvey::ResourceCreated(resource.Get(),D3D12_RESOURCE_STATE_GENERIC_READ);
    D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{resource->GetGPUVirtualAddress(),1536};
    hkSurveyCreateConstantBufferView(h.device.Get(),&cbv,h.handle(UINT(40000+worker*(samples/8)+i)));}
   finals.push_back(resource.Detach());
  }
  for(size_t i=0;i<samples/128;++i){D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;desc.NumDescriptors=32;
   ComPtr<ID3D12DescriptorHeap> heap;hr(h.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&heap)));
   if(wrappers){FrameSurvey::HeapCreated(h.device.Get(),heap.Get());auto handle=heap->GetCPUDescriptorHandleForHeapStart();
    for(UINT slot=0;slot<32;++slot){auto at=handle;at.ptr+=uint64_t(slot)*h.stride;hkSurveyCreateShaderResourceView(h.device.Get(),h.texture.Get(),&h.srvDesc,at);}
    auto info=std::make_shared<HeapInfo>();info->heap=heap.Get();info->birth=NrdBridgeBirth::Capture(heap.Get());std::scoped_lock lock(heapPoolMutex);heapPool.emplace(heap.Get(),info);}
   heaps.push_back(heap.Detach());
  }
 }
 ~WorkerPool(){for(auto* resource:finals)if(resource){if(bornMode&&observed)hkRelease(resource);else{FrameSurvey::Released(resource);resource->Release();}}for(auto* heap:heaps)if(heap){if(bornMode&&observed)hkHeapRelease(heap);else{FrameSurvey::Released(heap);heap->Release();}}}
};
ULONG nativeProbeRelease(ID3D12Resource* resource){{OriginalForwardTimer native;resource->AddRef();}forwardRelease(resource);return forwardRelease(resource);}
J phase(Host& h,size_t threadCount,UINT burst,bool wrappers,bool profile,bool finals=true){
 std::vector<std::unique_ptr<WorkerPool>> pool;const auto setup=qpc();
 for(size_t t=0;t<threadCount;++t){pool.push_back(std::make_unique<WorkerPool>(h,t,wrappers));
  for(UINT i=0;i<1024;++i)hkSurveyCreateShaderResourceView(h.device.Get(),h.texture.Get(),&h.srvDesc,h.handle(UINT(2048+t*2048+i)));}
 const double setupMs=(qpc()-setup)*1000.0/double(frequency());need(rss()<2ull*1024*1024*1024,"native pool plus100k metadata remains within2GB resident budget");
 std::barrier start(threadCount+1);std::vector<std::jthread> threads;std::vector<Observation> records(threadCount),originals(threadCount);
 std::atomic<bool> bad{false};const auto before=counters();const auto beforeReleases=observedReleases.load();
 for(size_t t=0;t<threadCount;++t)threads.emplace_back([&,t]{
  for(auto& values:records[t].ticks)values.reserve(samples);
  for(auto& values:originals[t].ticks)values.reserve(samples);
  if(profile&&wrappers){for(auto& event:records[t].waits)for(auto& values:event)values.reserve(samples);for(auto& event:records[t].metadataLocks)for(auto& values:event)values.reserve(samples);}
  gMeasureOriginal=profile;
  size_t final=0,heap=0;start.arrive_and_wait();
  for(size_t i=0;i<samples;++i){const auto slot=h.handle(UINT(32+t*96+(i%32)));const auto operation=i%8;Event event=CBV;
   if(operation==3||(operation==7&&!finals))h.buffer->AddRef();gOriginalTicks=0;gLastWaits={};const auto begin=qpc();
   if(operation==0||operation==4){if(wrappers)hkSurveyCreateConstantBufferView(h.device.Get(),&h.cbv,slot);else forwardCBV(h.device.Get(),&h.cbv,slot);event=CBV;}
   else if(operation==1||operation==5){if(wrappers)hkSurveyCreateShaderResourceView(h.device.Get(),h.texture.Get(),&h.srvDesc,slot);else forwardSRV(h.device.Get(),h.texture.Get(),&h.srvDesc,slot);event=SRVEvent;}
   else if(operation==2||operation==6){if(wrappers)hkSurveyCreateUnorderedAccessView(h.device.Get(),h.texture.Get(),nullptr,&h.uavDesc,slot);else forwardUAV(h.device.Get(),h.texture.Get(),nullptr,&h.uavDesc,slot);event=UAVEvent;}
   else if(operation==3){const auto result=wrappers?hkRelease(h.buffer.Get()):nativeProbeRelease(h.buffer.Get());if(!result)bad=true;event=ResourceRelease;}
   else if(finals){auto*& resource=pool[t]->finals[final++];const auto result=wrappers?hkRelease(resource):nativeProbeRelease(resource);if(result)bad=true;resource=nullptr;event=ResourceRelease;}
   else{const auto result=wrappers?hkRelease(h.buffer.Get()):nativeProbeRelease(h.buffer.Get());if(!result)bad=true;event=ResourceRelease;}
   const auto elapsed=qpc()-begin;records[t].ticks[event].push_back(elapsed);
   if(event==ResourceRelease)(operation==7&&finals?records[t].finalTicks:records[t].nonfinalTicks).push_back(elapsed);
   if(profile)originals[t].ticks[event].push_back(gOriginalTicks);
   if(profile&&wrappers){for(size_t k=0;k<gLastWaits.size();++k)records[t].waits[event][k].push_back(gLastWaits[k]);for(size_t k=0;k<gLastMetadataLocks.size();++k)records[t].metadataLocks[event][k].push_back(gLastMetadataLocks[k]);}
   if(i%64==63){UINT count=burst;auto from=h.handle(UINT(2048+t*2048)),to=h.handle(UINT(3072+t*2048));const auto copyBegin=qpc();
    gOriginalTicks=0;gLastWaits={};{
     NrdBridgePerf::Scope copyProfile(NrdBridgePerf::Hook::CopyDescriptors,wrappers&&gNrdBridgeWrappers&&!FrameSurvey::Internal());PerCallWaitSnapshot snapshot;
     {OriginalForwardTimer original;h.device->CopyDescriptorsSimple(count,to,from,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);}
     if(wrappers)FrameSurvey::CopyDescriptors(h.device.Get(),1,&to,&count,1,&from,&count,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    }
    records[t].ticks[CopyBurst].push_back(qpc()-copyBegin);
    if(profile)originals[t].ticks[CopyBurst].push_back(gOriginalTicks);
    if(profile&&wrappers){for(size_t k=0;k<gLastWaits.size();++k)records[t].waits[CopyBurst][k].push_back(gLastWaits[k]);for(size_t k=0;k<gLastMetadataLocks.size();++k)records[t].metadataLocks[CopyBurst][k].push_back(gLastMetadataLocks[k]);}
   }
   if(i%128==127){auto*& object=pool[t]->heaps[heap++];gOriginalTicks=0;gLastWaits={};const auto heapBegin=qpc();const auto result=wrappers?hkHeapRelease(object):forwardHeapRelease(object);if(result)bad=true;object=nullptr;records[t].ticks[HeapRelease].push_back(qpc()-heapBegin);if(profile)originals[t].ticks[HeapRelease].push_back(gOriginalTicks);if(profile&&wrappers){for(size_t k=0;k<gLastWaits.size();++k)records[t].waits[HeapRelease][k].push_back(gLastWaits[k]);for(size_t k=0;k<gLastMetadataLocks.size();++k)records[t].metadataLocks[HeapRelease][k].push_back(gLastMetadataLocks[k]);}}
  }
 });
 const auto began=qpc();start.arrive_and_wait();threads.clear();const auto wall=qpc()-began;const auto after=counters();
 need(!bad&&FrameSurvey::MetadataHealthy(),"all native final/nonfinal resource and pooled heap releases preserve healthy metadata");
 if(wrappers){need(observedReleases.load()-beforeReleases==threadCount*((finals?samples/8:0)+samples/128),"exact final resource/heap callback count across concurrent threads");
  for(size_t t=0;t<threadCount;++t){for(size_t i=0;i<samples/8;++i){const auto slot=h.handle(UINT(40000+t*(samples/8)+i)).ptr;
    if(finals)need(!FrameSurvey::gViews.contains(slot),"actual final Release tombstones its indexed live CBV");
    else need(FrameSurvey::gViews.at(slot).object==pool[t]->finals[i],"nonfinal scenario retains each fixture-owned native resource and CBV");}
   auto destination=h.handle(UINT(3072+t*2048));for(UINT i=0;i<burst;++i){const auto found=FrameSurvey::gViews.find(destination.ptr+uint64_t(i)*h.stride);need(found!=FrameSurvey::gViews.end()&&found->second.object==h.texture.Get(),"every copied destination has current shared native texture identity");}
  }
 }
 J rows=J::array();size_t total=0;for(size_t e=0;e<Events;++e){std::vector<uint64_t> values;for(const auto& record:records)values.insert(values.end(),record.ticks[e].begin(),record.ticks[e].end());total+=values.size();auto row=percentile(std::move(values));row["event"]=eventNames[e];rows.push_back(row);}
 J nativeRows=J::array();for(size_t e=0;e<Events;++e){std::vector<uint64_t> values;for(const auto& record:originals)values.insert(values.end(),record.ticks[e].begin(),record.ticks[e].end());auto row=percentile(std::move(values));row["event"]=eventNames[e];nativeRows.push_back(row);}
 std::vector<uint64_t> finalValues,nonfinalValues;for(const auto& record:records){finalValues.insert(finalValues.end(),record.finalTicks.begin(),record.finalTicks.end());nonfinalValues.insert(nonfinalValues.end(),record.nonfinalTicks.begin(),record.nonfinalTicks.end());}
 J perCallWaits=J::array(),nonNative=J::array(),metadataLocks=J::array();
 const std::array<const char*,7> metadataNames{"catalog_shared","catalog_exclusive","descriptor_shard","identity_shard","interval_index","snapshot_gate","mirror"};
 const std::array<const char*,4> waitNames{"metadata","physical_lifetime_gate","tracking","coordinator"};
 if(profile)for(size_t e=0;e<Events;++e){
  std::vector<uint64_t> own;for(size_t t=0;t<threadCount;++t){need(records[t].ticks[e].size()==originals[t].ticks[e].size(),"paired original timings match every event");for(size_t i=0;i<records[t].ticks[e].size();++i)own.push_back(records[t].ticks[e][i]>=originals[t].ticks[e][i]?records[t].ticks[e][i]-originals[t].ticks[e][i]:0);}
  auto row=percentile(std::move(own));row["event"]=eventNames[e];nonNative.push_back(row);
   if(wrappers){
    for(size_t k=0;k<waitNames.size();++k){std::vector<uint64_t> values;for(const auto& record:records)values.insert(values.end(),record.waits[e][k].begin(),record.waits[e][k].end());auto wait=percentile(std::move(values));wait["event"]=eventNames[e];wait["kind"]=waitNames[k];perCallWaits.push_back(wait);}
    for(size_t k=0;k<metadataNames.size();++k){std::vector<uint64_t> values;for(const auto& record:records)values.insert(values.end(),record.metadataLocks[e][k].begin(),record.metadataLocks[e][k].end());auto wait=percentile(std::move(values));wait["event"]=eventNames[e];wait["kind"]=metadataNames[k];metadataLocks.push_back(wait);}
   }
 }
 J waits=J::array();const std::array<const char*,4> hooks{"CBV","SRV","UAV","Release"};
 for(size_t i=0;i<hooks.size();++i){const auto calls=after[i].calls-before[i].calls;J row{{"hook",hooks[i]},{"actual_profiled_calls",calls}};
  const std::array<const char*,4> categories{"metadata","physical_lifetime_gate","tracking","coordinator"};
  for(size_t j=0;j<categories.size();++j){const auto ticks=after[i].waitTicks[j]-before[i].waitTicks[j];row[std::string(categories[j])+"_total_us"]=double(ticks)*1000000.0/double(frequency());row[std::string(categories[j])+"_mean_us"]=calls?double(ticks)*1000000.0/double(frequency())/calls:0.0;}
  row["profiled_total_us"]=double(after[i].ticks-before[i].ticks)*1000000.0/double(frequency());waits.push_back(row);
 }
 need(heapPool.empty(),"all pooled native heaps leave their participant registry");
 return{{"threads",threadCount},{"copy_descriptors",burst},{"resource_final_fraction",finals?.5:0.0},{"resource_final",percentile(std::move(finalValues))},
  {"resource_nonfinal",percentile(std::move(nonfinalValues))},{"heap_final_fraction",1.0},{"mode",wrappers?"actual_production_hook_bodies":"native_forwarding_and_native_release_probe"},
  {"iterations_per_thread",samples},{"events",total},{"wall_ms",double(wall)*1000.0/double(frequency())},{"events_per_second",double(total)*double(frequency())/wall},
  {"pool_setup_ms_excluded_from_timings",setupMs},{"samples",rows},{"paired_original_forwarding",nativeRows},
  {"original_forwarding_scope","same-call native View/Copy and both native Release calls plus their AddRef; caller-owned AddRef before timed nonfinal release excluded; QPC/TLS snapshots only profileON; OFF retains disabled measurement branches"},
  {"paired_non_native",nonNative},{"per_call_waits",perCallWaits},{"metadata_lock_waits",metadataLocks},{"metadata_lock_wait_scope","same actual WaitScope ticks split by FrameSurvey lock; Birth waits remain in aggregate metadata; native mirror waits are named"},{"release_lookup_path",bornMode?"known_unmarked":"legacy_registry_lookup"},
  {"profile_waits",waits},{"working_set_bytes",rss()},{"peak_working_set_bytes",peakRss()}};
}
void nativeMetadataPendingReleaseRegressions(Host& h){
 D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=4;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
 ComPtr<ID3D12DescriptorHeap> heap;hr(h.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));FrameSurvey::HeapCreated(h.device.Get(),heap.Get());
 D3D12_DESCRIPTOR_RANGE range{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,1,6,0,0};D3D12_ROOT_PARAMETER parameter{};
 parameter.ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameter.DescriptorTable={1,&range};
 D3D12_ROOT_SIGNATURE_DESC layout{1,&parameter,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> bytes,error;ComPtr<ID3D12RootSignature> root;
 hr(D3D12SerializeRootSignature(&layout,D3D_ROOT_SIGNATURE_VERSION_1,&bytes,&error));
 hr(h.device->CreateRootSignature(0,bytes->GetBufferPointer(),bytes->GetBufferSize(),IID_PPV_ARGS(&root)));FrameSurvey::RootCreated(root.Get(),bytes->GetBufferPointer(),bytes->GetBufferSize());
 const auto source=heap->GetCPUDescriptorHandleForHeapStart();auto destination=source;destination.ptr+=h.stride;const auto gpu=heap->GetGPUDescriptorHandleForHeapStart();
 ID3D12DescriptorHeap* heaps[]{heap.Get()};h.list->SetDescriptorHeaps(1,heaps);h.list->SetComputeRootSignature(root.Get());h.list->SetComputeRootDescriptorTable(0,gpu);
 const auto run=[&](IUnknown* object,bool isHeap){
  hkSurveyCreateConstantBufferView(h.device.Get(),&h.cbv,source);FrameSurvey::SetBindingWindow(true);
  FrameSurvey::ComputeBindings bindings;bindings.root=root.Get();bindings.heaps={heap.Get()};bindings.tables={{0,gpu}};
  bindings.receiverBirth=NrdBridgeBirth::Capture(h.list.Get());bindings.rootBirth=NrdBridgeBirth::Capture(root.Get());bindings.heapBirths={NrdBridgeBirth::Capture(heap.Get())};
  FrameSurvey::BoundConstantBuffer before;need(FrameSurvey::SeedComputeBindings(h.list.Get(),bindings)&&FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,before),"paused nonfinal fixture captures valid actual shader-visible CBV before release");
  const auto token=NrdBridgeBirth::Capture(object);need(token&&token->CacheAdmissible(),"actual native resource/heap birth ready before nonfinal probe");
  const auto observed=observedReleases.load();object->AddRef(); // Fixture owner remains; caller ref is released by the real hook.
  PausedNativeRelease pause;pause.object=object;auto entered=pause.entered.get_future();gPausedNativeRelease=&pause;
  std::atomic<ULONG> result{0};std::jthread worker([&]{result=isHeap?hkHeapRelease(heap.Get()):hkRelease(h.buffer.Get());});
  entered.wait();const bool pending=token->Live()&&token->ReleasesInFlight()>0&&!token->CacheAdmissible();
  hkSurveyCreateConstantBufferView(h.device.Get(),&h.cbv,source);UINT one=1;
  h.device->CopyDescriptorsSimple(1,destination,source,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  FrameSurvey::CopyDescriptors(h.device.Get(),1,&destination,&one,1,&source,&one,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
  const auto found=FrameSurvey::gViews.find(destination.ptr);
  const bool kept=found!=FrameSurvey::gViews.end()&&found->second.object==h.buffer.Get()&&FrameSurvey::NativeViewMetadataFresh(found->second)&&!FrameSurvey::NativeViewFresh(found->second);
  const bool denied=!FrameSurvey::ValidateBorrowedConstantBuffer(before);
  // Always release the deterministic pause before asserting to avoid a hanging
  // native worker if the production regression fails.
  pause.resume.set_value();worker.join();gPausedNativeRelease=nullptr;
  need(pending,"paused actual first native Release is nonfinal and physical counter blocks weak admission");
  need(result.load()>0&&observedReleases.load()==observed,"actual caller release preserves retained resource/heap and performs no final retirement");
  need(kept&&denied,"pending nonfinal CBV/Copy preserve pure metadata without admitting native borrow");
  need(FrameSurvey::NativeViewFresh(FrameSurvey::gViews.at(destination.ptr))&&FrameSurvey::ValidateBorrowedConstantBuffer(before),"completed nonfinal native Release restores borrow eligibility without recopy");
 };
 run(h.buffer.Get(),false);run(heap.Get(),true);
 h.list->SetDescriptorHeaps(0,nullptr);h.list->SetComputeRootSignature(h.root.Get());h.list->SetComputeRootConstantBufferView(0,h.cbv.BufferLocation);
 need(hkHeapRelease(heap.Detach())==0,"actual paused-test table heap is finally retired through production helper");
 need(NrdBridgeRelease::Title(root.Detach(),[](auto* p){return p->Release();})==0,"actual paused-test root is finally retired through production helper");
 FrameSurvey::SetBindingWindow(false);
}
void samplerNativeRegressions(Host& h){
 if(!bornMode)return;
 FrameSurvey::SetBindingWindow(true);
 D3D12_DESCRIPTOR_HEAP_DESC desc{};desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;desc.NumDescriptors=8;desc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
 ComPtr<ID3D12DescriptorHeap> resourceHeap,sampler;hr(h.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&resourceHeap)));
 desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER;desc.NumDescriptors=1;hr(h.device->CreateDescriptorHeap(&desc,IID_PPV_ARGS(&sampler)));
 sampler->AddRef();const auto before=sampler->Release();
 FrameSurvey::HeapCreated(h.device.Get(),resourceHeap.Get());FrameSurvey::HeapCreated(h.device.Get(),sampler.Get());
 sampler->AddRef();need(sampler->Release()==before,"genuine native SAMPLER registration retains no title COM reference");
 const auto samplerBirth=NrdBridgeBirth::Capture(sampler.Get()),heapBirth=NrdBridgeBirth::Capture(resourceHeap.Get());
 need(samplerBirth&&heapBirth&&FrameSurvey::gHeaps.at(sampler.Get()).birth==samplerBirth,"genuine native SAMPLER stores exact birth identity");
 for(const auto& [handle,object]:FrameSurvey::gCpuHeaps)need(object!=sampler.Get(),"genuine SAMPLER never enters the resource-view interval index");
 D3D12_DESCRIPTOR_RANGE range{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,1,6,0,0};D3D12_ROOT_PARAMETER parameter{};
 parameter.ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;parameter.DescriptorTable={1,&range};
 D3D12_ROOT_SIGNATURE_DESC layout{1,&parameter,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> bytes,error;ComPtr<ID3D12RootSignature> root;
 hr(D3D12SerializeRootSignature(&layout,D3D_ROOT_SIGNATURE_VERSION_1,&bytes,&error));
 hr(h.device->CreateRootSignature(0,bytes->GetBufferPointer(),bytes->GetBufferSize(),IID_PPV_ARGS(&root)));
 FrameSurvey::RootCreated(root.Get(),bytes->GetBufferPointer(),bytes->GetBufferSize());
 const auto cpu=resourceHeap->GetCPUDescriptorHandleForHeapStart();const auto gpu=resourceHeap->GetGPUDescriptorHandleForHeapStart();
 hkSurveyCreateConstantBufferView(h.device.Get(),&h.cbv,cpu);ID3D12DescriptorHeap* heaps[]{resourceHeap.Get(),sampler.Get()};
 h.list->SetDescriptorHeaps(2,heaps);FrameSurvey::DescriptorHeaps(h.list.Get(),2,heaps);
 h.list->SetComputeRootSignature(root.Get());FrameSurvey::RootBinding(h.list.Get(),false,root.Get());
 h.list->SetComputeRootDescriptorTable(0,gpu);FrameSurvey::Table(h.list.Get(),false,0,gpu);
 FrameSurvey::BoundConstantBuffer cbv;
 need(FrameSurvey::ResolveComputeConstantBuffer(h.list.Get(),6,0,1216,cbv)&&cbv.resource==h.buffer.Get()&&cbv.descriptorHeapBirth==heapBirth,"genuine native b6 table resolves with SAMPLER bound alongside resource heap");
 FrameSurvey::ComputeBindings bindings;bindings.root=root.Get();bindings.heaps={resourceHeap.Get(),sampler.Get()};bindings.tables={{0,gpu}};
 bindings.receiverBirth=NrdBridgeBirth::Capture(h.list.Get());bindings.rootBirth=NrdBridgeBirth::Capture(root.Get());bindings.heapBirths={heapBirth,samplerBirth};
 FrameSurvey::BoundConstantBinding native;
 need(FrameSurvey::ResolveComputeConstantBinding(bindings,6,0,native)&&native.descriptorHeap==resourceHeap.Get(),"genuine volatile native table proof selects CBV heap by exact type/birth");
 h.list->SetDescriptorHeaps(0,nullptr);h.list->SetComputeRootSignature(h.root.Get());h.list->SetComputeRootConstantBufferView(0,h.cbv.BufferLocation);
 need(hkHeapRelease(sampler.Detach())==0,"genuine final SAMPLER Release uses production helper/counter/gate");
 need(FrameSurvey::ValidateBorrowedConstantBuffer(cbv)&&FrameSurvey::gHeaps.contains(resourceHeap.Get()),"SAMPLER-only final native Release preserves staged resource CBV");
 need(hkHeapRelease(resourceHeap.Detach())==0&&!FrameSurvey::ValidateBorrowedConstantBuffer(cbv),"actual resource heap final Release invalidates exact staged slot");
 auto* rawRoot=root.Detach();need(NrdBridgeRelease::Title(rawRoot,[](auto* p){return p->Release();})==0,"genuine root final Release uses actual helper");
 restart(h);
}
J releaseLookupPhase(ID3D12Resource* object,size_t threads,bool profile,const char* path){
 struct ReleaseSamples{std::vector<uint64_t> elapsed,native;std::array<std::vector<uint64_t>,size_t(NrdBridgePerf::WaitKind::Count)> waits;};
 std::vector<ReleaseSamples> rows(threads);std::vector<std::jthread> workers;std::barrier start(threads+1);std::atomic<bool> bad{false};const auto before=counters();
 for(size_t t=0;t<threads;++t)workers.emplace_back([&,t]{
  auto& row=rows[t];row.elapsed.reserve(samples);row.native.reserve(samples);if(profile)for(auto& wait:row.waits)wait.reserve(samples);gMeasureOriginal=profile;start.arrive_and_wait();
  for(size_t i=0;i<samples;++i){object->AddRef();gOriginalTicks=0;gLastWaits={};const auto begin=qpc();const auto result=hkRelease(object);row.elapsed.push_back(qpc()-begin);if(!result)bad=true;
   if(profile){row.native.push_back(gOriginalTicks);for(size_t k=0;k<gLastWaits.size();++k)row.waits[k].push_back(gLastWaits[k]);}}
 });
 const auto begin=qpc();start.arrive_and_wait();workers.clear();const auto wall=qpc()-begin;const auto after=counters();need(!bad&&FrameSurvey::MetadataHealthy(),"lookup path nonfinal native releases preserve caller-owned object");
 std::vector<uint64_t> elapsed,native,own;for(const auto& row:rows){elapsed.insert(elapsed.end(),row.elapsed.begin(),row.elapsed.end());native.insert(native.end(),row.native.begin(),row.native.end());if(profile){need(row.elapsed.size()==row.native.size(),"release lookup paired native measurement has exact sample count");for(size_t i=0;i<row.elapsed.size();++i)own.push_back(row.elapsed[i]>=row.native[i]?row.elapsed[i]-row.native[i]:0);}}
 J perCall=J::array(),waitTotals=J::object();const std::array<const char*,4> kinds{"metadata","physical_lifetime_gate","tracking","coordinator"};const auto release=size_t(NrdBridgePerf::Hook::Release),calls=after[release].calls-before[release].calls;
 for(size_t k=0;k<kinds.size();++k){std::vector<uint64_t> values;for(const auto& row:rows)values.insert(values.end(),row.waits[k].begin(),row.waits[k].end());auto measured=percentile(std::move(values));measured["kind"]=kinds[k];perCall.push_back(measured);const auto ticks=after[release].waitTicks[k]-before[release].waitTicks[k];waitTotals[kinds[k]]={{"total_us",double(ticks)*1000000.0/frequency()},{"mean_us",calls?double(ticks)*1000000.0/frequency()/calls:0.0}};}
 return{{"mode","actual_production_release_lookup_path"},{"release_lookup_path",path},{"threads",threads},{"logical_registry_records",logicalRecords},{"resource_final_fraction",0.0},{"calls",elapsed.size()},{"wall_ms",double(wall)*1000.0/frequency()},{"calls_per_second",double(elapsed.size())*frequency()/wall},{"hook",percentile(std::move(elapsed))},{"paired_native",percentile(std::move(native))},{"paired_non_native",percentile(std::move(own))},{"per_call_waits",perCall},{"profile_wait_totals",waitTotals}};
}
void leaseLookupRegressions(Host& h,bool profile,J& rows){
 RecordedComputeLease::SetHooksAvailable(true,true);ComPtr<IUnknown> identity;hr(h.buffer->QueryInterface(IID_PPV_ARGS(&identity)));
 const auto birth=NrdBridgeBirth::Capture(h.buffer.Get());if(bornMode)need(birth&&NrdBridgeBirth::MarkRecordingMayExist(birth),"actual known title object marked before recording lease admission");
 auto owner=std::make_shared<int>(42);need(RecordedComputeLease::Track(identity.Get(),{h.buffer.Get()},owner),"actual retained recording and weak alias installed in real lease registry");
 for(size_t threads:{size_t(1),size_t(8),size_t(16)})rows.push_back(releaseLookupPhase(h.buffer.Get(),threads,profile,"marked_actual_recording"));
 auto recorded=RecordedComputeLease::Capture(h.buffer.Get());need(recorded&&recorded->releasesInFlight==0&&recorded->leases.size()==1&&recorded->leases[0]==owner,"actual helper balances recording-release counters and preserves lease after nonfinal calls");
 RecordedComputeLease::Detach(recorded);need(!RecordedComputeLease::Capture(h.buffer.Get()),"actual recording detaches without submission outside native timing");recorded.reset();identity.Reset();
 auto unknown=buffer(h.device.Get());need(!NrdBridgeBirth::Capture(unknown.Get())&&!FrameSurvey::gResources.contains(unknown.Get()),"native unknown object has no fake metadata or Born admission");
 for(size_t threads:{size_t(1),size_t(8),size_t(16)})rows.push_back(releaseLookupPhase(unknown.Get(),threads,profile,"unknown_actual_registry_lookup"));
 need(hkRelease(unknown.Detach())==0,"actual unknown native final Release completes via production hook");
 need(RecordedComputeLease::GetRegistry().recordings.empty()&&RecordedComputeLease::GetRegistry().aliases.empty(),"real lease registry fully drained after marked/unknown scenarios");
}
void releaseNativeHost(Host& h){
 if(!bornMode)return;
 FrameSurvey::Shutdown();
 auto* list=h.list.Detach();need(NrdBridgeRelease::Title(list,[](auto* p){return p->Release();})==0,"actual native host list retires its exact birth");
 auto* root=h.root.Detach();need(NrdBridgeRelease::Title(root,[](auto* p){return p->Release();})==0,"actual native host root retires its exact birth");
 need(hkHeapRelease(h.heap.Detach())==0&&hkRelease(h.buffer.Detach())==0&&hkRelease(h.texture.Detach())==0,"remaining actual native host heaps/resources retire before process teardown");
}
int main(int argc,char** argv)try{
 need(argc==4,"output/profile/adapter arguments");SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 const bool profile=std::string(argv[2])=="on";gUseHardware=std::string(argv[3])=="hardware";
 if(profile){NrdBridgePerf::Configure([](const NrdBridgePerf::Report&)noexcept{});NrdBridgePerf::ConsumerFrame(1);}
 if(bornMode){need(NrdBridgeNativeBirth::ConfigureRetirement(PrepareNativeRetirement,DetachNativeRetirement,NotifyNativeRetirement),"actual native retirement dispatcher configured");need(NrdBridgeLifetime::EnableConcurrentReleases(),"actual concurrent physical release gate enabled");}
 (void)RecordedComputeLease::GetRegistry();
 g_dllPath=std::filesystem::path(argv[1])/"fixture.dll";Host h;FrameSurvey::SetReleaseObserver(&onRelease);if(bornMode)FrameSurvey::SetBirthReleaseObserver(&onBirthRelease);
 startupAndIndirectRegressions(h,profile);metadataRegressions(h);nativeMetadataPendingReleaseRegressions(h);samplerNativeRegressions(h);J rows=J::array();const auto cacheBegin=qpc();
 {
  Cache cache(h);const double insertionMs=(qpc()-cacheBegin)*1000.0/double(frequency());
  for(size_t threads:{size_t(1),size_t(8),size_t(16)})for(UINT burst:{64u,1024u}){
   rows.push_back(phase(h,threads,burst,false,profile));rows.push_back(phase(h,threads,burst,true,profile));
  }
  for(size_t threads:{size_t(1),size_t(8),size_t(16)})for(UINT burst:{64u,1024u}){
   rows.push_back(phase(h,threads,burst,false,profile,false));rows.push_back(phase(h,threads,burst,true,profile,false));
  }
  leaseLookupRegressions(h,profile,rows);
  need(FrameSurvey::gResources.size()==cache.prior+logicalRecords,"all concurrent native final pools retired,100k logical records preserved");
  for(size_t i=0;i<logicalRecords;++i){const auto object=cache.objects[i];const auto handle=0x600000000000ull+(i+1)*64;
   need(FrameSurvey::gViews.at(handle).object==object&&FrameSurvey::gResources.at(object).handles.contains(handle),"unrelated100k logical view ownership remains exact under real concurrent hooks");}
  rows.push_back({{"logical_cache_insertion_ms",insertionMs},{"records",logicalRecords},{"views",logicalRecords}});
 }
 need(FrameSurvey::gResources.size()==2,"synthetic teardown leaves only actual shared native buffer and texture");
 hr(h.list->Close());releaseNativeHost(h);need(peakRss()<2ull*1024*1024*1024,"measured peak process working set below2GB");
 J result{{"variant","__VARIANT__"},{"profile",profile},{"adapter",gUseHardware?"hardware":"WARP"},{"checks",checks},{"rows",rows},
  {"gpu_dispatches",0},{"ExecuteCommandLists_calls",0},{"synthetic_objects_passed_to_com",false},{"logical_registry_records",logicalRecords},
  {"peak_working_set_bytes",peakRss()},{"native_birth_mode",bornMode},{"Detours_installation_measured",false},{"lease_registry","actual production RecordedComputeLease, actual retirement counters and dispatcher"},{"scope","actual extracted native View/resource+heap Release hooks with explicit COM forwarding; live WARP/hardware pools;100k metadata-emulated resources/views; HUD/RR caches inactive; copy wrapper is native CopyDescriptorsSimple+actual FrameSurvey callback; profileON adds paired native QPC and profiler TLS snapshots; profileOFF has no inner QPC but disabled fixture measurement branches remain"}};
 std::ofstream(std::filesystem::path(argv[1])/(std::string("result-")+argv[2]+".json"))<<result.dump(2)<<'\n';std::cout<<result.dump()<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def snapshot(path, baseline):
    if baseline:
        return subprocess.check_output(['git', 'show', f'{BASELINE}:{path}'], cwd=ROOT).decode('utf-8-sig')
    return (ROOT/path).read_text(encoding='utf-8-sig')


NATIVE_CACHE = r'''
struct Cache {
 std::vector<ID3D12Resource*> objects;size_t prior,nativePrior,bufferPrior,heapPrior;
 ID3D12DescriptorHeap* logicalHeap=nullptr;
 explicit Cache(Host& h):prior(FrameSurvey::gResources.size()),nativePrior(FrameSurvey::gNativeResources.Size()),bufferPrior(FrameSurvey::gNativeBuffers.Size()),heapPrior(FrameSurvey::gNativeHeaps.Size()){
  objects.reserve(logicalRecords);
  logicalHeap=reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x400000000010ull));
  auto heapBirth=NrdBridgeBirth::ObserveInstance(logicalHeap,0x100000000000ull+logicalRecords+1);
  FrameSurvey::PreparedHeap hp;hp.object=logicalHeap;hp.cpu=0x600000000000ull;hp.increment=64;
  hp.description.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hp.description.NumDescriptors=UINT(logicalRecords+1);
  need(heapBirth&&FrameSurvey::PublishHeapMetadata(hp,heapBirth),"synthetic heap POD stages actual native identity/range tables without COM");
  auto heapOwner=FrameSurvey::gNativeHeaps.Find(logicalHeap);need(bool(heapOwner),"100k logical views have a native metadata heap owner");
  for(size_t i=0;i<logicalRecords;++i){auto* object=reinterpret_cast<ID3D12Resource*>(uintptr_t(0x400000000000ull+(i+1)*65536));
   FrameSurvey::PreparedResource p;p.object=object;p.description.Width=8192;p.description.Height=1;
   p.description.DepthOrArraySize=p.description.MipLevels=1;p.description.SampleDesc.Count=1;
   if(i%10==0){p.description.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;p.address=0x700000000000ull+(i+1)*65536;}
   else{p.description.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;p.description.Height=32;p.description.Format=DXGI_FORMAT_R16G16B16A16_FLOAT;}
   const auto birth=NrdBridgeBirth::ObserveInstance(object,0x100000000000ull+i+1);
   need(birth&&FrameSurvey::PublishResourceMetadata(p,birth),"unique synthetic metadata record; never passed to COM");
   auto resourceOwner=FrameSurvey::gNativeResources.Find(object);need(resourceOwner&&resourceOwner->birth==birth,"each logical resource occupies actual native identity table");
   const uint64_t slot=0x600000000000ull+(i+1)*64;
   FrameSurvey::ViewInfo view{object,resourceOwner->id,p.address?uint32_t(D3D12_DESCRIPTOR_RANGE_TYPE_CBV):uint32_t(D3D12_DESCRIPTOR_RANGE_TYPE_SRV),uint32_t(p.description.Format),0,!p.address};
   view.descriptorCpu=slot;view.rootVa=p.address;view.constantBytes=p.address?1536:0;view.heapKnown=true;
   view.descriptorHeap=uint64_t(reinterpret_cast<uintptr_t>(logicalHeap));view.resourceOwner=resourceOwner;view.heapOwner=heapOwner;
   {FrameSurvey::NativeSnapshotShared snapshot;std::scoped_lock slotLock(FrameSurvey::gViewMutexes[FrameSurveyMetadata::DescriptorShard(slot)]);FrameSurvey::NativeReplaceView(view);}
   _trackedResources.emplace(object,std::vector<TrackedResourceSlot>{});objects.push_back(object);
  }
  need(FrameSurvey::gResources.size()==prior+logicalRecords,"100k logical resources plus actual native objects live together");
  need(!FrameSurvey::gRecording.load()&&!FrameSurvey::BindingWindow(),"normal hot path has no recorder and closed binding window");
  need(rss()<2ull*1024*1024*1024,"registry fixture stays below2GB resident memory budget");
  const auto hit=FrameSurvey::gBufferAddresses.Find(h.cbv.BufferLocation);need(hit.matches==1&&hit.object==h.buffer.Get(),"native CBV VA resolves amid100k logical records");
  need(FrameSurvey::gNativeResources.Size()==nativePrior+logicalRecords&&FrameSurvey::gNativeBuffers.Size()==bufferPrior+logicalRecords/10&&FrameSurvey::gNativeHeaps.Size()==heapPrior+1,"actual native identity/VA/heap tables contain the full100k logical dataset");
 }
 ~Cache(){for(auto* object:objects){FrameSurvey::Released(object);_trackedResources.erase(object);}FrameSurvey::Released(logicalHeap);}
};
'''

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--adapter', choices=('warp', 'hardware'), default='warp')
    parser.add_argument('--profile', choices=('on', 'off', 'both'), default='both')
    args = parser.parse_args()
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    source = snapshot('OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp', args.baseline)
    hook_source = snapshot('OptiScaler/resource_tracking/ResTrack_dx12.cpp', args.baseline)
    original = source
    helper = (ROOT/"OptiScaler/misc/NrdBridgeRelease_Dx12.h").read_text()
    assert helper.count("object->AddRef();") == 1
    measured_helper = out/"NrdBridgeRelease_measured.h"
    measured_helper.write_text(helper.replace("object->AddRef();", "{ OriginalForwardTimer nativeAddRef; object->AddRef(); }"))
    if args.baseline:
        needle = 'std::recursive_mutex gLifetimeMutex, gRecordMutex;'
        assert source.count(needle) == 1
        replacement = 'FrameSurveyMetadata::MetadataMutex<std::recursive_mutex,FrameSurveyMetadata::MetadataLock::CatalogExclusive> gLifetimeMutex;\nstd::recursive_mutex gRecordMutex;'
        source = source.replace(needle, replacement)
        assert source.replace(replacement, needle) == original
    surveyed = out/'FrameSurvey_measured.cpp'
    surveyed.write_text(source, encoding='utf-8')
    # Preserve the established native host+hook seams; only enlarge the native
    # descriptor heap, disable debug overhead and allow a real hardware adapter.
    cpp = native.CPP[:native.CPP.index('#if __INDEXED__\n// Opaque')]
    cpp = cpp.replace('#include <thread>', '#include <thread>\n#include <future>\n#define FSRD_NRD_BRIDGE_TEST\nbool gUseHardware=false;')
    cpp = cpp.replace('#include "__SURVEY__"', '#include "resource_tracking/FrameSurveyConcurrentMetadata.h"\n#include "__SURVEY__"')
    cpp = cpp.replace('debug->EnableDebugLayer();', '(void)debug;')
    cpp = cpp.replace('hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));', 'if(gUseHardware)hr(factory->EnumAdapters(0,&warp));else hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));')
    cpp = cpp.replace('BeginCreationTracking(true)', 'BeginCreationTracking(false)').replace('hd.NumDescriptors=16', 'hd.NumDescriptors=65536')
    timing = r'''
thread_local bool gMeasureOriginal=false;
thread_local uint64_t gOriginalTicks=0;
thread_local std::array<uint64_t,size_t(NrdBridgePerf::WaitKind::Count)> gLastWaits{};
thread_local FrameSurveyMetadata::MetadataLockTicks gLastMetadataLocks{};
struct PerCallWaitSnapshot {
 FrameSurveyMetadata::MetadataLockTicks before{};
 PerCallWaitSnapshot(){if(gMeasureOriginal&&NrdBridgePerf::Detail::currentWaits)before=FrameSurveyMetadata::ThreadMetadataLockTicks();}
 ~PerCallWaitSnapshot(){if(gMeasureOriginal&&NrdBridgePerf::Detail::currentWaits){gLastWaits=*NrdBridgePerf::Detail::currentWaits;const auto after=FrameSurveyMetadata::ThreadMetadataLockTicks();for(size_t i=0;i<after.size();++i)gLastMetadataLocks[i]=after[i]-before[i];}}
};
struct OriginalForwardTimer {
 LARGE_INTEGER start{};bool active=false;
 OriginalForwardTimer(){active=gMeasureOriginal&&QueryPerformanceCounter(&start);}
 ~OriginalForwardTimer(){if(active){LARGE_INTEGER end{};if(QueryPerformanceCounter(&end)&&end.QuadPart>=start.QuadPart)gOriginalTicks+=uint64_t(end.QuadPart-start.QuadPart);}}
};
'''
    cpp = cpp.replace('// The exact production hook bodies use native WARP forwarding.', timing+'\n// The exact production hook bodies use native WARP forwarding.')
    for operation in ('CBV', 'SRV', 'UAV'):
        needle = '{d->Create'+{'CBV': 'ConstantBufferView', 'SRV': 'ShaderResourceView', 'UAV': 'UnorderedAccessView'}[operation]+'('
        assert cpp.count(needle) == 1
        cpp = cpp.replace(needle, '{OriginalForwardTimer original;d->Create'+{'CBV': 'ConstantBufferView', 'SRV': 'ShaderResourceView', 'UAV': 'UnorderedAccessView'}[operation]+'(')
    cpp = cpp.replace('struct State {', 'struct State {bool isShuttingDown=false;std::unordered_set<ID3D12Resource*> capturedHudlesses;')
    cpp = cpp.replace('struct HeapInfo {', 'struct HeapInfo {ID3D12DescriptorHeap* heap=nullptr;NrdBridgeBirth::Token birth;void ClearSlotIfMatches(UINT,ID3D12Resource*,const NrdBridgeBirth::Token& = {}){}')
    names = ('hkCreateShaderResourceView', 'hkCreateUnorderedAccessView', 'hkSurveyCreateConstantBufferView', 'hkSurveyCreateShaderResourceView', 'hkSurveyCreateUnorderedAccessView')
    bodies = {name: function(hook_source, 'void ResTrack_Dx12::'+name+'(') for name in names}
    def measured_body(body):
        if 'NrdBridgePerf::Scope perf(' in body:
            start = body.index('NrdBridgePerf::Scope perf(')
            end = body.index(';', start)+1
            body = body[:end]+'\n    PerCallWaitSnapshot perCallWait;'+body[end:]
        return body.replace('This->AddRef();', '{ OriginalForwardTimer nativeAddRef; This->AddRef(); }').replace('ResTrack_Dx12::', '')
    hooks = '\n'.join(measured_body(body) for body in bodies.values())
    release = function(hook_source, 'ULONG ResTrack_Dx12::hkRelease(')
    heap_release = function(hook_source, 'static ULONG STDMETHODCALLTYPE hkHeapRelease(')
    current_hooks = snapshot('OptiScaler/resource_tracking/ResTrack_dx12.cpp', False)
    retirement_start = current_hooks.index('struct NativeRetirementPayload\n{')
    retirement_end = current_hooks.index('void* PrepareNativeRetirement(', retirement_start)
    retirement = current_hooks[retirement_start:retirement_end]+'\n'+'\n'.join(function(current_hooks, name) for name in ('void* PrepareNativeRetirement(', 'bool DetachNativeRetirement(', 'void NotifyNativeRetirement('))
    adapter = ADAPTER.replace('__RELEASE_HEADER__', measured_helper.as_posix()).replace('__USE_NATIVE__', function(current_hooks, 'static bool UseNrdNativeRetirement('))
    adapter = adapter.replace('__BASELINE_FAILURE_ADAPTER__', 'namespace FrameSurvey {void FlushMetadataFailure() noexcept{}}' if args.baseline else '')
    if args.baseline:
        retirement = 'void* PrepareNativeRetirement() noexcept {std::terminate();} bool DetachNativeRetirement(void*,const NrdBridgeBirth::Token&) noexcept {std::terminate();} void NotifyNativeRetirement(void*) noexcept {std::terminate();}'
    adapter = adapter.replace('__NATIVE_RETIREMENT__', retirement).replace('__RELEASE__', measured_body(release)).replace('__HEAP_RELEASE__', measured_body(heap_release))
    guard = 'std::scoped_lock copyWriter(FrameSurvey::gLifetimeMutex);' if args.baseline else 'FrameSurvey::NativeSnapshotShared copyWriter;'
    if not args.baseline and 'NativeSnapshotShared' not in source:
        guard = 'std::shared_lock copyWriter(FrameSurvey::gLifetimeMutex);'
    variant = 'baseline6edf-real-lease-paired-locksplit' if args.baseline else 'native-pinned-metadata-paired-locksplit'
    driver = DRIVER
    if not args.baseline:
        cache_start = driver.index('struct Cache {')
        cache_end = driver.index('struct WorkerPool {', cache_start)
        driver = driver[:cache_start] + NATIVE_CACHE + driver[cache_end:]
        driver = driver.replace('rows.push_back({{"logical_cache_insertion_ms",insertionMs},{"records",logicalRecords},{"views",logicalRecords}});',
            'rows.push_back({{"logical_cache_insertion_ms",insertionMs},{"records",logicalRecords},{"views",logicalRecords},{"actual_native_resource_nodes",FrameSurvey::gNativeResources.Size()},{"actual_native_buffer_intervals",FrameSurvey::gNativeBuffers.Size()},{"actual_native_heap_nodes",FrameSurvey::gNativeHeaps.Size()},{"logical_native_views",logicalRecords}});')
        driver = driver.replace('const auto object=cache.objects[i];const auto handle=0x600000000000ull+(i+1)*64;',
            'const auto object=cache.objects[i];const auto handle=0x600000000000ull+(i+1)*64;need(FrameSurvey::NativeViewFresh(FrameSurvey::gViews.at(handle))&&FrameSurvey::gViews.at(handle).resourceOwner==FrameSurvey::gNativeResources.Find(object),"all100k logical native slot owners remain exact after concurrent native hooks");')
        driver = driver.replace('need(FrameSurvey::gResources.size()==2,"synthetic teardown leaves only actual shared native buffer and texture");',
            'need(FrameSurvey::gResources.size()==2,"synthetic teardown leaves only actual shared native buffer and texture");need(FrameSurvey::gNativeResources.Size()==2&&FrameSurvey::gNativeBuffers.Size()==1&&FrameSurvey::gNativeHeaps.Size()==1,"native synthetic teardown leaves only actual host metadata nodes");')
    if args.baseline:
        # The frozen catalog predates birth fields. Its original assertions stay;
        # the genuinely new SAMPLER identity fixture belongs only to the candidate.
        driver = driver.replace(function(driver, "void samplerNativeRegressions("), "void samplerNativeRegressions(Host&) {}")
        driver = driver.replace(function(driver, "void nativeMetadataPendingReleaseRegressions("), "void nativeMetadataPendingReleaseRegressions(Host&) {}")
    cpp += adapter+driver.replace('__SHARED_COPY_GUARD__', guard).replace('__VARIANT__', variant).replace('__CANDIDATE__', 'false' if args.baseline else 'true').replace('__BORN__', 'false' if args.baseline else 'true')
    cpp = cpp.replace('__TRACE__', (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()).replace('__SURVEY__', surveyed.as_posix()).replace('__INDEXED__', '1').replace('__HOOKS__', hooks)
    stubs = out/'stubs'
    for folder in ('proxies', 'inputs'):
        (stubs/folder).mkdir(parents=True, exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n#define LOG_INFO(...) ((void)0)\n#define LOG_ERROR(...) ((void)0)\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\nnamespace Util {inline std::filesystem::path DllPath(){return g_dllPath;}}\n')
    (stubs/'inputs/NVNGX_DLSS.h').write_text('#pragma once\n#include <nvsdk_ngx.h>\n')
    (stubs/'proxies/D3D12_Proxy.h').write_text('#pragma once\n#include <d3d12.h>\nnamespace D3d12Proxy {inline auto D3D12CreateVersionedRootSignatureDeserializer_(){return &D3D12CreateVersionedRootSignatureDeserializer;}inline auto D3D12SerializeVersionedRootSignature_(){return &D3D12SerializeVersionedRootSignature;}}\n')
    fixture, exe = out/'contention.cpp', out/'contention.exe'
    fixture.write_text(cpp, encoding='utf-8')
    compile_cpp(fixture, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'd3dcompiler.lib', 'bcrypt.lib', 'user32.lib', 'psapi.lib', str(ROOT/'OptiScaler/library/detours/detours.lib')),
                (stubs, ROOT/'OptiScaler', ROOT/'OptiScaler/misc', ROOT/'OptiScaler/resource_tracking', ROOT/'OptiScaler/include', ROOT/'external/nlohmann', ROOT/'external/nvngx_dlss_sdk', ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    profiles = ('on', 'off') if args.profile == 'both' else (args.profile,)
    for profile in profiles:
        result = subprocess.run([str(exe), str(out), profile, args.adapter], capture_output=True, text=True, check=False, timeout=240, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out/f'native-{profile}.log').write_text(result.stdout+result.stderr)
        result.check_returncode()
        report = json.loads((out/f'result-{profile}.json').read_text())
        report['production_source_sha256'] = hashlib.sha256(original.encode()).hexdigest()
        report['hook_body_sha256'] = {name: hashlib.sha256(body.encode()).hexdigest() for name, body in dict(bodies, hkRelease=release, hkHeapRelease=heap_release).items()}
        report['baseline_instrumentation'] = 'scratch catalog mutex WaitScope, same-call native AddRef/QPC and before-Scope-destructor TLS snapshot; production control flow and assertions unchanged' if args.baseline else None
        report['measurement_instrumentation'] = 'same-call native AddRef/Release/View/Copy QPC; profiler TLS snapshot before outer Scope destructor; copy native+callback boundary uses Hook::CopyDescriptors Scope'
        report['native_release_helper_sha256'] = hashlib.sha256(helper.encode()).hexdigest()
        report['source_commit'] = BASELINE if args.baseline else subprocess.check_output(['git', 'log', '-1', '--format=%H'], cwd=ROOT, text=True).strip()
        report_dir = Path(os.environ.get('FSRD_TASK_REPORT_DIR', 'E:/FSRD/sol_batch/13a-lifetime'))
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir/f'contention-{report["variant"]}-{profile}.json').write_text(json.dumps(report, indent=2)+'\n')
        summary = [{'threads': row['threads'], 'copy_descriptors': row['copy_descriptors'], 'resource_final_fraction': row['resource_final_fraction'],
                    'wall_ms': row['wall_ms'], 'mean_us': {sample['event']: sample['mean_us'] for sample in row['samples']},
                    'metadata_wait_us': {wait['hook']: wait['metadata_mean_us'] for wait in row['profile_waits']},
                    'paired_native_mean_us': {sample['event']: sample.get('mean_us') for sample in row['paired_original_forwarding']}}
                   for row in report['rows'] if row.get('mode') == 'actual_production_hook_bodies']
        print(json.dumps({'variant': report['variant'], 'profile': profile, 'checks': report['checks'], 'peak_working_set_bytes': report['peak_working_set_bytes'], 'summary': summary}))


if __name__ == '__main__':
    run()
