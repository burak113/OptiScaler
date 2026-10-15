"""CPU proof/cost of actual contiguous descriptor-copy metadata owner pinning.

Run with lead_ops/run_task_test.py --cpu. Production hook, HeapInfo, ResourceInfo,
range indexes and TLS lookup bodies are extracted unchanged, except counters and
explicit native forward/increment/FrameSurvey-health seams. No D3D device/GPU.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_root_restore import function

OWN = Path(__file__).resolve().parents[4]
ROOT = Path(os.environ.get('FSRD_NRD_PRODUCTION_ROOT', OWN)).resolve()
OUT = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15a-motion/tests/descriptor-copy'))

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <psapi.h>
#include <ankerl/unordered_dense.h>
#include <json.hpp>
#include <algorithm>
#include <atomic>
#include <array>
#include <chrono>
#include <functional>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <new>
#include <cstdlib>
#include <shared_mutex>
#include <stdexcept>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "__ROOT__/OptiScaler/misc/NrdBridgeBirth_Dx12.h"
using J=nlohmann::json;
constexpr bool hashedParticipants=__HASHED_PARTICIPANTS__;
#define LOG_ERROR(...) ((void)0)
#define LOG_TRACK(...) ((void)0)
static std::atomic<unsigned> healthFailures{0};
namespace FrameSurvey {void MetadataHookFailed(const char*) noexcept{++healthFailures;}}
// Native GUID preparation is outside this metadata-only fixture. Real Birth
// tokens/retirement/admission execute; no synthetic "all tokens are valid" seam.
namespace NrdBridgeNativeBirth {bool Ready() noexcept{return true;}}
static std::atomic<uint64_t> allocations{0};
void* operator new(size_t bytes){++allocations;if(auto* value=std::malloc(bytes?bytes:1))return value;throw std::bad_alloc();}
void* operator new[](size_t bytes){return ::operator new(bytes);}
void operator delete(void* value)noexcept{std::free(value);}void operator delete[](void* value)noexcept{std::free(value);}
void operator delete(void* value,size_t)noexcept{std::free(value);}void operator delete[](void* value,size_t)noexcept{std::free(value);}
static thread_local uint64_t participantScans=0,participantVisits=0;
template<class Base>struct CountedParticipants:Base{
 using Base::Base;
 auto begin(){++participantScans;return Base::begin();}auto begin()const{++participantScans;return Base::begin();}
};
template<class Iterator>struct CountedParticipantIterator{
 Iterator value;
 using iterator_category=std::forward_iterator_tag;
 using value_type=typename std::iterator_traits<Iterator>::value_type;
 using difference_type=typename std::iterator_traits<Iterator>::difference_type;
 using reference=typename std::iterator_traits<Iterator>::reference;
 using pointer=typename std::iterator_traits<Iterator>::pointer;
 reference operator*()const{++participantVisits;return *value;}
 auto& operator++(){++value;return *this;}auto operator++(int){auto old=*this;++value;return old;}
 bool operator==(const CountedParticipantIterator& other)const{return value==other.value;}
 bool operator!=(const CountedParticipantIterator& other)const{return value!=other.value;}
};
template<class T>struct CountedVectorSlots:std::vector<T>{
 using Base=std::vector<T>;using Base::Base;
 using Iterator=CountedParticipantIterator<typename Base::iterator>;
 auto begin(){++participantScans;return Iterator{Base::begin()};}auto end(){return Iterator{Base::end()};}
 auto begin()const{++participantScans;return CountedParticipantIterator<typename Base::const_iterator>{Base::begin()};}
 auto end()const{return CountedParticipantIterator<typename Base::const_iterator>{Base::end()};}
 auto erase(Iterator first,Iterator last){return Base::erase(first.value,last.value);}
};
__RESOURCE_TYPES__
__TRACKED_PREAMBLE__
using FixtureSlots=typename decltype(_trackedResources)::mapped_type;
inline NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> _trackedResourcesMutex;
static thread_local uint64_t lookupCalls=0,registryReads=0,poolScans=0,poolReads=0,nativeCalls=0,incrementCalls=0;
static thread_local uint64_t descriptorGets=0,descriptorSets=0,descriptorClears=0;
static thread_local std::function<void()> beforeDescriptorRead;
__HEAP_INFO__;
struct CountedSharedMutex{
 std::shared_mutex value;
 void lock(){value.lock();}void unlock(){value.unlock();}
 void lock_shared(){++registryReads;value.lock_shared();}void unlock_shared(){value.unlock_shared();}
};
struct CountedHeapPool:std::vector<std::shared_ptr<HeapInfo>>{
 using Base=std::vector<std::shared_ptr<HeapInfo>>;
 auto begin(){++poolScans;return Base::begin();}auto begin()const{++poolScans;return Base::begin();}
 auto& operator[](size_t index){++poolReads;return Base::operator[](index);}
 const auto& operator[](size_t index)const{++poolReads;return Base::operator[](index);}
};
static CountedSharedMutex _heapRegistryMutex;
static CountedHeapPool fgHeaps;
static std::unordered_map<void*,size_t> gHeapSlotsByAddress;
static std::map<SIZE_T,size_t> gHeapCpuRanges,gHeapGpuRanges;
static std::vector<size_t> gFreeHeapSlots;
static bool gNrdBridgeWrappers=true;
__CACHE_TYPE__;
static thread_local HeapCacheTLS cache;
static std::atomic<unsigned> gHeapGeneration{1};
__INDEX_METHODS__
__LOOKUP_METHOD__
struct Option{bool value=true;bool value_or_default()const{return value;}};
struct Config{Option FGAlwaysTrackHeaps;static Config* Instance(){static Config value;return &value;}};
static bool hudActive=false;
static bool IsHudFixActive(){return hudActive;}
static UINT fixtureIncrement=32;
static UINT FixtureIncrement(ID3D12Device*,D3D12_DESCRIPTOR_HEAP_TYPE){++incrementCalls;return fixtureIncrement;}
struct ForwardArguments{ID3D12Device* device=nullptr;UINT count=0;SIZE_T dst=0,src=0;D3D12_DESCRIPTOR_HEAP_TYPE type{};};
static thread_local ForwardArguments forwarded;
static void NativeForward(ID3D12Device* device,UINT count,D3D12_CPU_DESCRIPTOR_HANDLE dst,
                          D3D12_CPU_DESCRIPTOR_HANDLE src,D3D12_DESCRIPTOR_HEAP_TYPE type){
 ++nativeCalls;forwarded={device,count,dst.ptr,src.ptr,type};
}
static auto o_CopyDescriptorsSimple=&NativeForward;
struct ResTrack_Dx12{
 static std::shared_ptr<HeapInfo> GetHeapByCpuHandle(SIZE_T);
 static void hkCopyDescriptorsSimple(ID3D12Device*,UINT,D3D12_CPU_DESCRIPTOR_HANDLE,D3D12_CPU_DESCRIPTOR_HANDLE,D3D12_DESCRIPTOR_HEAP_TYPE);
 static void baselineCopyDescriptorsSimple(ID3D12Device*,UINT,D3D12_CPU_DESCRIPTOR_HANDLE,D3D12_CPU_DESCRIPTOR_HANDLE,D3D12_DESCRIPTOR_HEAP_TYPE);
};
__CPU_LOOKUP__
__SCALAR_FORMAT__
__OLD_HOOK__
__HOOK__
static uint64_t checks=0;
static void need(bool value,const char* message){++checks;if(!value)throw std::runtime_error(message);}
struct Probe:IUnknown{
 std::atomic<unsigned> refs{1},addrefs{0},releases{0},queries{0};
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID,void** output) override{++queries;if(output)*output=nullptr;return E_NOINTERFACE;}
 ULONG STDMETHODCALLTYPE AddRef() override{++addrefs;return ++refs;}
 ULONG STDMETHODCALLTYPE Release() override{++releases;return --refs;}
};
static Probe resourceA,resourceB,retiredResource;
static ResourceInfo info(Probe& object,DXGI_FORMAT format=DXGI_FORMAT_R16_FLOAT){
 ResourceInfo result;result.buffer=reinterpret_cast<ID3D12Resource*>(&object);result.width=1536;result.height=864;
 result.format=format;result.state=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;result.flags=D3D12_RESOURCE_FLAG_NONE;
 result.type=SRV;result.lastUsedFrame=19;result.extended=true;result.captureInfo=7;
 result.birth=NrdBridgeBirth::ObserveInstance(&object,uintptr_t(&object));
 need(bool(result.birth)&&NrdBridgeBirth::CacheAdmissible(result.birth),"real metadata birth is ready/current");return result;
}
static std::shared_ptr<HeapInfo> makeHeap(size_t index,UINT count=2048,UINT stride=32,UINT type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV){
 const SIZE_T start=0x100000000ull+index*0x40000ull;
 auto heap=std::make_shared<HeapInfo>(reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(0x100000+index*64)),start,start+SIZE_T(count)*stride,0,0,count,stride,type);
 std::unique_lock lock(_heapRegistryMutex);need(RegisterTrackedHeapLocked(heap),"actual indexed heap publication");return heap;
}
static void fill(const std::shared_ptr<HeapInfo>& heap,const ResourceInfo& value,UINT count=2048){
 for(UINT index=0;index<count;++index)heap->SetByCpuHandle(heap->cpuStart+SIZE_T(index)*heap->increment,value);
}
static std::vector<uintptr_t> image(const std::shared_ptr<HeapInfo>& heap,UINT count=2048){
 std::vector<uintptr_t> result;result.reserve(count*3);
 for(UINT index=0;index<count;++index){ResourceInfo value;const bool found=heap->GetByCpuHandle(heap->cpuStart+SIZE_T(index)*heap->increment,value);
  result.push_back(found?uintptr_t(value.buffer):0);result.push_back(found?UINT(value.format):0);result.push_back(found?value.captureInfo:0);
 }return result;
}
template<class Slots>static size_t participantSize(const Slots& slots){
 if constexpr(requires{slots.get();})return slots?slots->size():0;else return slots.size();
}
template<class Slots>static bool containsEdge(const Slots& slots,const std::shared_ptr<HeapInfo>& heap,UINT index){
 const auto matches=[&](const auto& slot){return slot.heap.lock()==heap&&slot.index==index&&slot.heapVersion==heap->version.load();};
 if constexpr(requires{slots.get();}){if(!slots)return false;for(const auto& [key,slot]:*slots)if(matches(slot))return true;}
 else {for(const auto& slot:slots)if(matches(slot))return true;}
 return false;
}
static bool edge(const ResourceInfo& value,const std::shared_ptr<HeapInfo>& heap,UINT index){
 std::scoped_lock lock(_trackedResourcesMutex);auto found=_trackedResources.find(value.buffer);
 return found!=_trackedResources.end()&&containsEdge(found->second,heap,index);
}
static void resetCounters(){lookupCalls=registryReads=poolScans=poolReads=nativeCalls=incrementCalls=descriptorGets=descriptorSets=descriptorClears=participantScans=participantVisits=0;}
using Hook=decltype(&ResTrack_Dx12::hkCopyDescriptorsSimple);
static ID3D12Device* device=reinterpret_cast<ID3D12Device*>(uintptr_t(0x87654321));
static J invoke(Hook hook,UINT count,SIZE_T dst,SIZE_T src,D3D12_DESCRIPTOR_HEAP_TYPE type){
 resetCounters();hook(device,count,{dst},{src},type);
 need(nativeCalls==1,"exactly one original CopyDescriptorsSimple forward");
 need(forwarded.device==device&&forwarded.count==count&&forwarded.dst==dst&&forwarded.src==src&&forwarded.type==type,"original arguments preserved exactly");
 need(poolScans==0,"hot copy never begins a full heap registry scan");
 if(hashedParticipants)need(participantScans==0,"copy/replacement/clear never scans one resource's complete descriptor fanout");
 return {{"count",count},{"lookups",lookupCalls},{"registry_shared_acquisitions",registryReads},{"indexed_slot_reads",poolReads},
 {"descriptor_gets",descriptorGets},{"descriptor_sets",descriptorSets},{"descriptor_clears",descriptorClears},{"original_calls",nativeCalls},{"full_heap_scans",poolScans},{"full_resource_fanout_scans",participantScans},{"resource_fanout_element_visits",participantVisits}};
}
static void compareFallback(const char* name,const std::shared_ptr<HeapInfo>& src,const std::shared_ptr<HeapInfo>& dst,
                            UINT count,SIZE_T dstHandle,SIZE_T srcHandle,D3D12_DESCRIPTOR_HEAP_TYPE type){
 const auto a=info(resourceA),b=info(resourceB);fill(src,a);fill(dst,b);
 invoke(&ResTrack_Dx12::baselineCopyDescriptorsSimple,count,dstHandle,srcHandle,type);const auto old=image(dst);
 fill(dst,b);const auto row=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,count,dstHandle,srcHandle,type);
 need(image(dst)==old,name);need(row["lookups"].get<uint64_t>()>2,"unproven span uses the original indexed per-slot fallback");
}
static J correctness(const std::shared_ptr<HeapInfo>& src,const std::shared_ptr<HeapInfo>& dst,
                     const std::shared_ptr<HeapInfo>& rsrc,const std::shared_ptr<HeapInfo>& rdst){
 const auto a=info(resourceA),b=info(resourceB);J rows=J::array();
 for(const auto type:{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,D3D12_DESCRIPTOR_HEAP_TYPE_RTV}){
  const auto& s=type==D3D12_DESCRIPTOR_HEAP_TYPE_RTV?rsrc:src;const auto& d=type==D3D12_DESCRIPTOR_HEAP_TYPE_RTV?rdst:dst;
  fixtureIncrement=s->increment;fill(s,a);fill(d,b);Config::Instance()->FGAlwaysTrackHeaps.value=true;
  for(const UINT count:{64u,1024u}){
   auto old=invoke(&ResTrack_Dx12::baselineCopyDescriptorsSimple,count,d->cpuStart,s->cpuStart,type);
   need(old["lookups"]==2*count&&old["registry_shared_acquisitions"]==2*count,"immutable old control demonstrates two TLS-thrashing registry lookups per descriptor");
   fill(d,b);auto current=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,count,d->cpuStart,s->cpuStart,type);
   need(current["lookups"]==2&&current["registry_shared_acquisitions"]==2,"valid contiguous burst performs exactly two owner lookups");
   if(!hashedParticipants)need(current["resource_fanout_element_visits"].get<uint64_t>()>=uint64_t(count)*count,"frozen vector control exposes actual quadratic resource-fanout work");
   for(UINT i=0;i<count;++i){ResourceInfo found;need(d->GetByCpuHandle(d->cpuStart+SIZE_T(i)*d->increment,found)&&found.buffer==a.buffer&&found.birth==a.birth&&found.format==a.format&&found.width==a.width&&found.height==a.height&&found.extended==a.extended&&found.state==a.state&&found.flags==a.flags&&found.type==a.type&&found.lastUsedFrame==a.lastUsedFrame&&found.captureInfo==a.captureInfo,"copy preserves every actual ResourceInfo field and exact birth");}
   need(edge(a,d,count-1)&&!edge(b,d,count-1),"actual Set/Detach/Attach moves destination reverse participant");
   rows.push_back({{"heap_type",UINT(type)},{"old",old},{"current",current}});
  }
 }
 fixtureIncrement=32;Config::Instance()->FGAlwaysTrackHeaps.value=false;fill(src,a);fill(dst,b);
 auto gated=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(gated["lookups"]==2&&gated["descriptor_sets"]==64,"source scalar gate reuses both owner pins");
 auto nonScalar=a;nonScalar.format=DXGI_FORMAT_D32_FLOAT;auto nonScalarB=b;nonScalarB.format=DXGI_FORMAT_D32_FLOAT;
 fill(src,nonScalar);fill(dst,nonScalarB);const auto untouched=image(dst);
 auto skipped=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(skipped["lookups"]==2&&skipped["descriptor_sets"]==0&&skipped["descriptor_clears"]==0&&image(dst)==untouched,"no source/destination scalar participant preserves the original gate");
 fill(dst,b);auto clear=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,0,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(clear["lookups"]==1&&clear["descriptor_clears"]==64,"NULL source uses one destination pin and the scalar-destination clear gate");
 for(UINT i=0;i<64;++i){ResourceInfo found;need(!dst->GetByCpuHandle(dst->cpuStart+SIZE_T(i)*32,found)&&!edge(b,dst,i),"null source clears metadata and its reverse edge");}
 fill(dst,nonScalarB);const auto nullUntouched=image(dst);invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,0,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(image(dst)==nullUntouched,"NULL source without scalar destination still preserves gate");
 Config::Instance()->FGAlwaysTrackHeaps.value=true;
 for(const auto type:{D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER,D3D12_DESCRIPTOR_HEAP_TYPE_DSV}){
  const auto before=image(dst);auto row=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,type);
  need(row["lookups"]==0&&row["descriptor_gets"]==0&&incrementCalls==0&&image(dst)==before,"unsupported native heap type forwards once without metadata or stride queries");
 }
 auto zero=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,0,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(zero["lookups"]==0&&zero["descriptor_gets"]==0&&incrementCalls==0,"zero count forwards once then returns before metadata");
 compareFallback("misaligned source preserves old floored metadata",src,dst,5,dst->cpuStart,src->cpuStart+1,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 compareFallback("misaligned destination preserves old floored metadata",src,dst,5,dst->cpuStart+1,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 compareFallback("source span crossing heap end preserves per-slot copy/clear",src,dst,5,dst->cpuStart,src->cpuEnd-64,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 compareFallback("destination span crossing heap end preserves per-slot handling",src,dst,5,dst->cpuEnd-64,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 compareFallback("unknown source owner preserves destination clears",src,dst,5,dst->cpuStart,0xdeadbeefull,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 compareFallback("unknown destination preserves unrelated metadata",src,dst,5,0xdeadbeefull,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 compareFallback("source address overflow preserves unsigned old indexed behavior",src,dst,3,dst->cpuStart,std::numeric_limits<SIZE_T>::max()-15,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 compareFallback("destination address overflow preserves unsigned old indexed behavior",src,dst,3,std::numeric_limits<SIZE_T>::max()-15,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 fixtureIncrement=16;compareFallback("native/metadata increment mismatch preserves indexed metadata",src,dst,5,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);fixtureIncrement=32;
 auto retired=info(retiredResource);fill(src,retired);fill(dst,b);need(NrdBridgeBirth::RetireCurrentInstance(retired.birth),"retire actual source resource metadata birth");
 auto denied=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(denied["descriptor_sets"]==0&&denied["descriptor_clears"]==64,"retired source birth cannot resurrect through pinned heap metadata");
 fill(src,a);fill(dst,b);fill(src,b);invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(edge(b,dst,63)&&!edge(a,dst,63),"descriptor replacement preserves exact current resource reverse edges");
 const auto oldVersion=src->version.load();fill(src,a);fill(dst,b);
 beforeDescriptorRead=[&]{beforeDescriptorRead={};src->version.fetch_add(1);};
 auto version=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);beforeDescriptorRead={};
 need(src->version==oldVersion+1&&version["lookups"]==65,"per-iteration version guard re-enters indexed source lookup after first admitted slot");
 // Deliberate fence perturbation, not a legal native heap mutation: restore it
 // before actual reverse-index retirement so this probe cannot manufacture ABA.
 src->version.store(oldVersion);
 const auto dstVersion=dst->version.load();fill(src,a);fill(dst,a);
 beforeDescriptorRead=[&]{beforeDescriptorRead={};dst->version.fetch_add(1);};
 auto destinationVersion=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);beforeDescriptorRead={};
 need(dst->version==dstVersion+1&&destinationVersion["lookups"]==65,"per-iteration destination version guard re-enters indexed lookup");dst->version.store(dstVersion);
 fill(src,a);fill(dst,b);beforeDescriptorRead=[&]{beforeDescriptorRead={};need(DeactivateTrackedHeap(src),"actual owner retires before first slot read");};
 auto inactive=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,src->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);beforeDescriptorRead={};
 need(!src->active&&inactive["lookups"]==65&&inactive["descriptor_sets"]==0&&inactive["descriptor_clears"]==64,"retirement after pin admission cannot copy stale source slots");
 auto replacement=makeHeap(99996);need(replacement->version!=src->version,"recycled native range receives a new metadata version");fill(replacement,b);fill(dst,a);
 auto reused=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,dst->cpuStart,replacement->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
 need(reused["lookups"]==2&&edge(b,dst,63)&&!edge(a,dst,63),"generation invalidates generic TLS and pins replacement range exactly");
 auto retiredDestination=makeHeap(100006);fill(retiredDestination,b);
 beforeDescriptorRead=[&]{beforeDescriptorRead={};need(DeactivateTrackedHeap(retiredDestination),"actual destination owner retires before first slot write");};
 auto destinationInactive=invoke(&ResTrack_Dx12::hkCopyDescriptorsSimple,64,retiredDestination->cpuStart,replacement->cpuStart,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);beforeDescriptorRead={};
 need(!retiredDestination->active&&!retiredDestination->info&&destinationInactive["lookups"]==65&&destinationInactive["descriptor_sets"]==1,"retired destination rejects first admitted write and remaining slots re-enter index without stale storage");
 rows.push_back({{"scalar_gate",gated},{"no_participant",skipped},{"null_source",clear},{"retired_resource",denied},{"version_fence",version},{"destination_version_fence",destinationVersion},{"retired_heap",inactive},{"retired_destination",destinationInactive},{"replacement",reused}});
 return rows;
}
static J timing(unsigned threads,bool old){
 constexpr unsigned count=1024,repetitions=32;const auto a=info(resourceA);std::vector<std::pair<std::shared_ptr<HeapInfo>,std::shared_ptr<HeapInfo>>> pairs;
 for(unsigned i=0;i<threads;++i){auto src=makeHeap(100010+i*2),dst=makeHeap(100011+i*2);fill(src,a);fill(dst,a);pairs.emplace_back(src,dst);}
 Config::Instance()->FGAlwaysTrackHeaps.value=true;std::vector<J> results(threads);std::vector<std::thread> workers;std::atomic<unsigned> ready=0;std::atomic<bool> start=false;
 for(unsigned t=0;t<threads;++t)workers.emplace_back([&,t]{++ready;while(!start.load(std::memory_order_acquire))std::this_thread::yield();
  const auto& [src,dst]=pairs[t];std::vector<double> values;values.reserve(repetitions);uint64_t calls=0,locks=0,scans=0,fanout=0;
  for(unsigned i=0;i<repetitions;++i){resetCounters();auto begin=std::chrono::steady_clock::now();
   (old?ResTrack_Dx12::baselineCopyDescriptorsSimple:ResTrack_Dx12::hkCopyDescriptorsSimple)(device,count,{dst->cpuStart},{src->cpuStart},D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
   auto end=std::chrono::steady_clock::now();values.push_back(std::chrono::duration<double,std::micro>(end-begin).count());calls+=lookupCalls;locks+=registryReads;scans+=poolScans;fanout+=participantScans;
  }std::sort(values.begin(),values.end());double sum=0;for(const auto value:values)sum+=value;
  results[t]={{"mean_us",sum/repetitions},{"p50_us",values[repetitions/2]},{"p95_us",values[size_t(repetitions*.95)]},{"p99_us",values[size_t(repetitions*.99)]},{"max_us",values.back()},{"lookups",calls},{"registry_shared_acquisitions",locks},{"full_heap_scans",scans},{"full_resource_fanout_scans",fanout}};
 });while(ready.load()!=threads)std::this_thread::yield();start.store(true,std::memory_order_release);for(auto& worker:workers)worker.join();
 for(const auto& row:results)need(row["lookups"]==uint64_t(repetitions)*(old?2*count:2)&&row["registry_shared_acquisitions"]==uint64_t(repetitions)*(old?2*count:2)&&row["full_heap_scans"]==0&&row["full_resource_fanout_scans"]==0,"every warm concurrent burst keeps its exact complexity bound without scans");
 for(auto& [src,dst]:pairs){need(DeactivateTrackedHeap(src)&&DeactivateTrackedHeap(dst),"retire independent timing metadata heaps");}
 return {{"threads",threads},{"descriptors_per_burst",count},{"bursts_per_thread",repetitions},{"old_control",old},{"workers",results}};
}
static void participantMoveProof(){
 const auto a=info(resourceA);FixtureSlots toClean;size_t count=0;uint64_t before=0,after=0;
 {
  std::scoped_lock lock(_trackedResourcesMutex);auto found=_trackedResources.find(a.buffer);
  need(found!=_trackedResources.end()&&participantSize(found->second)>=1024,"actual resource has a large real descriptor participant fanout");
  count=participantSize(found->second);before=allocations.load();toClean=std::move(found->second);_trackedResources.erase(found);after=allocations.load();
 }
 need(before==after&&participantSize(toClean)==count,"actual participant alias moves out and erases outer key without allocation");
 // Restore this fixture's still-live metadata only after the retirement scope
 // ended. This checks container semantics, not an extracted native Release body.
 {std::scoped_lock lock(_trackedResourcesMutex);_trackedResources[a.buffer]=std::move(toClean);}
 need(participantSize(toClean)==0,"moved caller-owned participant batch has no duplicate owner");
}
static J fanoutTiming(const std::shared_ptr<HeapInfo>& src,const std::shared_ptr<HeapInfo>& dst){
 const auto a=info(resourceA),b=info(resourceB);fill(src,a);fixtureIncrement=src->increment;J rows=J::array();
 for(const UINT count:{64u,1024u}){std::vector<double> samples;uint64_t visits=0,scans=0;
  for(unsigned repeat=0;repeat<5;++repeat){fill(dst,b);resetCounters();const auto start=std::chrono::steady_clock::now();
   ResTrack_Dx12::hkCopyDescriptorsSimple(device,count,{dst->cpuStart},{src->cpuStart},D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
   const auto end=std::chrono::steady_clock::now();samples.push_back(std::chrono::duration<double,std::micro>(end-start).count());
   need(lookupCalls==2&&nativeCalls==1&&poolScans==0,"cold fanout burst still pins two indexed owners and forwards once");
   if(hashedParticipants)need(participantScans==0&&participantVisits==0,"new actual participant hash never walks the shared resource fanout");
   else need(participantVisits>=uint64_t(count)*count,"old actual vector helper has quadratic visits on the same cold burst");
   visits+=participantVisits;scans+=participantScans;
  }std::sort(samples.begin(),samples.end());double sum=0;for(const auto sample:samples)sum+=sample;
  rows.push_back({{"descriptors",count},{"repetitions",5},{"mean_us",sum/samples.size()},{"p50_us",samples[2]},{"max_us",samples.back()},{"fanout_element_visits",visits},{"fanout_range_begins",scans}});
 }fixtureIncrement=32;return rows;
}
int main(int argc,char** argv)try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
 const auto emptyStart=allocations.load();FixtureSlots emptySlots;FixtureSlots releaseSlots;
 need(allocations.load()==emptyStart&&participantSize(emptySlots)==0&&participantSize(releaseSlots)==0,"actual default participant/release aliases allocate zero");
 need(NrdBridgeBirth::ConfigureActions({+[](void*,const NrdBridgeBirth::Token&)noexcept{return true;},+[](void*,const NrdBridgeBirth::Token&)noexcept{return true;},nullptr}),"configure actual metadata birth actions");
 fgHeaps.reserve(100100);gFreeHeapSlots.reserve(100100);
 for(size_t i=0;i<99996;++i)makeHeap(i,1);
 auto src=makeHeap(99996),dst=makeHeap(99997),rsrc=makeHeap(99998,2048,16,D3D12_DESCRIPTOR_HEAP_TYPE_RTV),rdst=makeHeap(99999,2048,16,D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
 need(gHeapSlotsByAddress.size()==100000&&gHeapCpuRanges.size()==100000,"exact 100k live indexed heap registry before hot tests");
 const auto rows=correctness(src,dst,rsrc,rdst);const auto fanout=fanoutTiming(rsrc,rdst);J timings=J::array();
 if(argc==2){const auto threads=unsigned(std::stoul(argv[1]));need(threads==8||threads==16,"optional contention threads are eight or sixteen");timings.push_back(timing(threads,true));timings.push_back(timing(threads,false));}
 participantMoveProof();
 for(auto* object:{&resourceA,&resourceB,&retiredResource})need(object->refs==1&&object->addrefs==0&&object->releases==0&&object->queries==0,"metadata copying never calls title IUnknown AddRef/Release/QueryInterface");
 need(healthFailures==0&&NrdBridgeBirth::Healthy(),"all metadata and real birth admission remain healthy");
 PROCESS_MEMORY_COUNTERS memory{};GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory));need(memory.PeakWorkingSetSize<2500ull*1024*1024,"CPU process stays within 2.5GB");
 std::cout<<J{{"checks",checks},{"registry_heap_setup",100000},{"hashed_participants",hashedParticipants},{"correctness_and_complexity",rows},{"fanout_timings",fanout},{"timings",timings},{"peak_working_set_bytes",memory.PeakWorkingSetSize},
 {"scope","actual extracted ResTrack hook, HeapInfo/ResourceInfo, range indexes, TLS and real metadata births; native forwarding/increment and FrameSurvey health are explicit CPU adapters; no GPU/FPS claim"}}.dump(2)<<'\n';return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def extract(old_participants=False):
    source_path = ROOT/'OptiScaler/resource_tracking/ResTrack_Dx12.cpp'
    header_path = ROOT/'OptiScaler/resource_tracking/ResTrack_Dx12.h'
    source, production_header = source_path.read_text(), header_path.read_text()
    old_path = Path(__file__).with_name('fsrd_nrd_descriptor_copy_baseline.h')
    old_source = old_path.read_text()
    header = old_source if old_participants else production_header
    hud = (ROOT/'OptiScaler/hudfix/Hudfix_Dx12.h').read_text()
    signature = 'void ResTrack_Dx12::hkCopyDescriptorsSimple('
    hook, old = function(source,signature), function(old_source,signature)
    assert 'sourceRange' in hook and 'currentOwner' in hook, 'candidate must use the approved actual owner-pinning hook'
    assert 'sourceRange' not in old, 'old lookup-complexity control must remain unoptimized'
    assert hashlib.sha256(old.encode()).hexdigest() == '7d47125b9b643b73bc1db8ac921663d84ded20da444e93561cbb1b0b9aa318eb', 'frozen production negative control changed'
    cpp = CPP.replace('__ROOT__',ROOT.as_posix()).replace('__HASHED_PARTICIPANTS__','false' if old_participants else 'true')
    cpp = cpp.replace('__RESOURCE_TYPES__',function(hud,'enum ResourceType')+';\n'+function(hud,'typedef struct ResourceInfo')+' resource_info;')
    start=header.index('struct HeapInfo;')
    end=header.index('struct HeapInfo :',start) if old_participants else header.index('#ifdef USE_SPINLOCK_MUTEX',start)
    preamble=header[start:end]
    if old_participants:
        assert hashlib.sha256(function(header,'struct HeapInfo :').encode()).hexdigest() == 'dcef8a1643f903a705bc4fef265b40b92862635bbf9e6afa8e7c7f3e36ed7ba0', 'frozen actual vector helper changed'
        assert 'std::vector<TrackedResourceSlot>' in preamble
        preamble=preamble.replace('std::vector<TrackedResourceSlot>','CountedVectorSlots<TrackedResourceSlot>')
    else:
        alias='using TrackedResourceParticipants = '
        assert alias in preamble, 'actual hashed participant alias is required; do not substitute a handwritten map'
        begin=preamble.index(alias)+len(alias);end=preamble.index(';',begin)
        preamble=preamble[:begin]+'CountedParticipants<'+preamble[begin:end]+'>'+preamble[end:]
    cpp = cpp.replace('__TRACKED_PREAMBLE__',preamble)
    heap = function(header,'struct HeapInfo :')
    for marker, probe in (('bool GetByCpuHandle(SIZE_T cpuHandle, ResourceInfo& outInfo) const','++descriptorGets; {auto callback=beforeDescriptorRead; if(callback)callback();}'),
                          ('void SetByCpuHandle(SIZE_T cpuHandle, const ResourceInfo& setInfo)','++descriptorSets;'),
                          ('void ClearByCpuHandle(SIZE_T cpuHandle)','++descriptorClears;')):
        method = function(heap,marker); point = method.index('{')+1
        heap = heap.replace(method,method[:point]+'\n '+probe+method[point:],1)
    cpp = cpp.replace('__HEAP_INFO__',heap)
    cpp = cpp.replace('__CACHE_TYPE__',function(source,'struct HeapCacheTLS'))
    cpp = cpp.replace('__INDEX_METHODS__','\n'.join(function(source,s) for s in (
        'static bool HeapRangeAvailableLocked(', 'static std::shared_ptr<HeapInfo> FindIndexedHeapRangeLocked(',
        'static bool RegisterTrackedHeapLocked(', 'static bool DeactivateTrackedHeap(')))
    cpp = cpp.replace('__LOOKUP_METHOD__',function(source,'static std::shared_ptr<HeapInfo> FindHeapByCpuHandle('))
    lookup = function(source,'std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandle(SIZE_T cpuHandle)')
    point = lookup.index('{')+1;lookup = lookup[:point]+'\n ++lookupCalls;'+lookup[point:]
    cpp = cpp.replace('__CPU_LOOKUP__',lookup)
    cpp = cpp.replace('__SCALAR_FORMAT__',function(source,'static uint32_t GetRRFormatChannelCount(')+'\n'+function(source,'static bool IsRRScalarCandidateFormat('))
    for body in (hook,old):
        assert body.count('This->GetDescriptorHandleIncrementSize(DescriptorHeapsType)') == 1
    adapter = lambda body:body.replace('This->GetDescriptorHandleIncrementSize(DescriptorHeapsType)','FixtureIncrement(This,DescriptorHeapsType)')
    cpp = cpp.replace('__HOOK__',adapter(hook)).replace('__OLD_HOOK__',adapter(old).replace('::hkCopyDescriptorsSimple(','::baselineCopyDescriptorsSimple(',1))
    assert '__' not in cpp.replace('__forceinline',''), 'unresolved generated fixture placeholder'
    metadata = dict(source=str(source_path),source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                    header_sha256=hashlib.sha256(header_path.read_bytes()).hexdigest(),hook_sha256=hashlib.sha256(hook.encode()).hexdigest(),
                    old_hook_sha256=hashlib.sha256(old.encode()).hexdigest(),heap_info_sha256=hashlib.sha256(function(header,'struct HeapInfo :').encode()).hexdigest(),
                    old_hook_source=str(old_path),
                    old_participants=old_participants,
                    source_adapters=['native forward arguments/counter','device descriptor stride getter','FrameSurvey health callback',
                                     'NativeBirth readiness enabled; actual Birth tokens/retirement/admission','lookup/slot/index counters and deterministic retirement probes'])
    return cpp,metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--threads',type=int,choices=(8,16))
    parser.add_argument('--old-participants',action='store_true',help='Frozen actual vector HeapInfo control; preserves current hook and all correctness assertions')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    cpp,metadata=extract(args.old_participants);target=OUT/'descriptor_copy.cpp';target.write_text(cpp,encoding='utf-8')
    (OUT/'source.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    if args.prepare_only:
        print(json.dumps(dict(prepared=True,bytes=len(cpp),**metadata),indent=2));return
    exe=OUT/'descriptor_copy.exe'
    compile_cpp(target,exe,('psapi.lib',),(ROOT/'OptiScaler',ROOT/'external/nlohmann',ROOT/'external/unordered_dense/include'))
    command=[str(exe)]+([str(args.threads)] if args.threads else [])
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    (OUT/'native.stdout.log').write_text(result.stdout,encoding='utf-8');(OUT/'native.stderr.log').write_text(result.stderr,encoding='utf-8')
    result.check_returncode();values=json.loads(result.stdout);values['source']=metadata
    (OUT/'result.json').write_text(json.dumps(values,indent=2),encoding='utf-8')
    report=Path('E:/FSRD/sol_batch/15a-motion/descriptor-copy');report.mkdir(parents=True,exist_ok=True)
    suffix='vector' if args.old_participants else 'hash'
    (report/f'{OUT.name}_result_{suffix}.json').write_text(json.dumps(values,indent=2),encoding='utf-8')
    print('PASS:',values['checks'],'actual descriptor-copy CPU correctness/complexity checks; registry=',values['registry_heap_setup'])
    for row in values['correctness_and_complexity'][:4]:
        print('heap_type=',row['heap_type'],'count=',row['current']['count'],'old_lookups=',row['old']['lookups'],
              'current_lookups=',row['current']['lookups'],'current_registry_acquires=',row['current']['registry_shared_acquisitions'])


if __name__=='__main__':main()
