"""Actual ResTrack inspector bodies with CPU COM-byte ABI and catalog seams.

Production Birth/NativeBirth/Lifetime headers, metadata/admission/recording
algorithms and successful creator/Reset/Close/barrier bodies are unchanged.
The COM methods, Detours, legacy FG/lease callbacks and heap registry facade
are explicit CPU adapters. This does not claim native COM, detours or GPU proof.
--prepare-only writes the source and source hashes without compiling/running.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fsrd_nrd_root_restore import function

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi.h>
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeLifetime_Dx12.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <future>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#define LOG_ERROR(...) ((void)0)
#define LOG_TRACE(...) ((void)0)
#define LOG_TRACK(...) ((void)0)
#define LOG_DEBUG(...) ((void)0)
#define LOG_WARN(...) ((void)0)
unsigned checks=0;
void need(bool ok,const char* message){if(!ok)throw std::runtime_error(message);++checks;}
thread_local unsigned commonLocks=0;
struct TestMutex{
 std::mutex mutex;
 void lock(){mutex.lock();++commonLocks;} void unlock(){--commonLocks;mutex.unlock();}
 bool try_lock(){if(!mutex.try_lock())return false;++commonLocks;return true;}
};
struct TestSharedMutex{
 std::shared_mutex mutex;
 void lock(){mutex.lock();++commonLocks;}void unlock(){--commonLocks;mutex.unlock();}
 bool try_lock(){if(!mutex.try_lock())return false;++commonLocks;return true;}
 void lock_shared(){mutex.lock_shared();++commonLocks;}void unlock_shared(){--commonLocks;mutex.unlock_shared();}
 bool try_lock_shared(){if(!mutex.try_lock_shared())return false;++commonLocks;return true;}
};
std::atomic<unsigned> nativeUnderMetadata=0,nativeDesc=0,nativePrivate=0,nativeQI=0,nativeCanonicalQI=0,nativeRefs=0;
void native(){if(commonLocks||NrdBridgeBirth::InMetadataScope())++nativeUnderMetadata;}
namespace FrameSurvey {
 thread_local bool internal=false;thread_local unsigned recordingDepth=0;
 bool Internal() noexcept{return internal;}bool OwnedRelease() noexcept{return internal&&!recordingDepth;}
 struct ScopedInternal{bool old;ScopedInternal():old(internal){internal=true;}~ScopedInternal(){internal=old;}};
 struct ScopedRecording{ScopedRecording(){++recordingDepth;}~ScopedRecording(){--recordingDepth;}};
 void MetadataHookFailed(const char*) noexcept{}
 void FlushMetadataFailure() noexcept{}
}
struct Gate{
 std::mutex mutex;std::condition_variable cv;bool entered=false,open=false;
 void wait(){std::unique_lock lock(mutex);entered=true;cv.notify_all();cv.wait(lock,[&]{return open;});}
 bool reached(){std::unique_lock lock(mutex);return cv.wait_for(lock,std::chrono::seconds(2),[&]{return entered;});}
 void release(){std::lock_guard lock(mutex);open=true;cv.notify_all();}
};
using Token=NrdBridgeBirth::Token;
using PFN_PsoRelease=ULONG(STDMETHODCALLTYPE*)(ID3D12PipelineState*);
using PFN_CommandListRelease=ULONG(STDMETHODCALLTYPE*)(IUnknown*);
using PFN_Release=ULONG(STDMETHODCALLTYPE*)(ID3D12Resource*);
using PFN_BirthRelease=ULONG(STDMETHODCALLTYPE*)(IUnknown*);
using PFN_Reset=HRESULT(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);
using PFN_Close=HRESULT(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*);
using PFN_ResourceBarrier=void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,UINT,const D3D12_RESOURCE_BARRIER*);
bool gNrdBridgeWrappers=false;
std::atomic<bool> gRRInspectorLifetimeProtection{false},gComputeListHooksAvailable{false};
std::recursive_mutex gReleaseHookInstallMutex;
PFN_Release o_Release=nullptr;PFN_PsoRelease o_PsoRelease=nullptr;PFN_CommandListRelease o_CommandListRelease=nullptr;
PFN_BirthRelease o_HeapRelease=nullptr;
PFN_Reset o_Reset=nullptr;PFN_Close o_Close=nullptr;PFN_ResourceBarrier o_ResourceBarrier=nullptr;
PVOID gResourceReleaseEntry=nullptr,gHeapReleaseEntry=nullptr,gPsoReleaseEntry=nullptr,gCommandListReleaseEntry=nullptr;
PVOID gComputeResetEntry=nullptr,gRRRecordingCloseEntry=nullptr,gRRRecordingBarrierEntry=nullptr;
PFN_BirthRelease FindBirthReleaseOriginal(PVOID) noexcept{return nullptr;}
ULONG hkPsoRelease(ID3D12PipelineState*){return 0;}
Gate* attachGate=nullptr;LONG attachResult=NO_ERROR;unsigned attaches=0;
LONG DetourTransactionBegin(){native();return NO_ERROR;}
LONG DetourUpdateThread(HANDLE){native();return NO_ERROR;}
LONG DetourAttach(PVOID*,PVOID){native();++attaches;if(attachGate)attachGate->wait();return attachResult;}
LONG DetourTransactionCommit(){native();return NO_ERROR;}
LONG DetourTransactionAbort(){native();return NO_ERROR;}
using FG_ResourceType=int;
enum ResourceType{SRV,UAV,RTV};
__CANDIDATE__
template<class K,class V>struct CountedMap:std::unordered_map<K,V>{
 using Base=std::unordered_map<K,V>;unsigned begins=0;
 auto begin(){++begins;return Base::begin();}auto begin()const{return Base::begin();}
};
bool failNextProof=false,failProducer=false;
template<class K,class V,class H>struct FailureMap:std::unordered_map<K,V,H>{
 using Base=std::unordered_map<K,V,H>;
 V& operator[](const K& key){if(failNextProof){failNextProof=false;throw std::bad_alloc();}return Base::operator[](key);}
};
__GLOBALS__
namespace MenuOverlayDx{ID3D12GraphicsCommandList* MenuCommandList(){return nullptr;}}
struct FakeFG{unsigned GetIndex(){return 0;}bool IsActive(){return false;}bool IsPaused(){return false;}bool IsResourceReady(int){return false;}};
struct State{bool skipHeapCapture=false;ID3D12Device* currentD3D12Device=nullptr;FakeFG* currentFG=nullptr;static State& Instance(){static State state;return state;}};
namespace RecordedComputeLease{unsigned captures=0,detaches=0;unsigned Capture(void*){return ++captures;}void Detach(unsigned){++detaches;}}
namespace RRTraceFence{unsigned resets=0;void ResetSucceeded(void*){++resets;}}
struct HeapInfo{
 ID3D12DescriptorHeap* heap;SIZE_T cpuStart,cpuEnd,gpuStart,gpuEnd;unsigned count,increment,type;
 std::atomic<bool> active{true};std::atomic<uint64_t> version{1};Token birth;
 HeapInfo(ID3D12DescriptorHeap* h,SIZE_T c,SIZE_T ce,SIZE_T g,SIZE_T ge,unsigned n,unsigned i,unsigned t):heap(h),cpuStart(c),cpuEnd(ce),gpuStart(g),gpuEnd(ge),count(n),increment(i),type(t){}
};
TestSharedMutex _heapRegistryMutex;
using HeapRanges=std::map<SIZE_T,std::shared_ptr<HeapInfo>>;
HeapRanges gHeapCpuRanges,gHeapGpuRanges;
std::vector<std::shared_ptr<HeapInfo>> heapRows;
std::shared_ptr<HeapInfo> FindIndexedHeapRangeLocked(HeapRanges& rows,SIZE_T address,bool gpu){
 const auto upper=rows.upper_bound(address);if(upper==rows.begin())return {};
 const auto heap=std::prev(upper)->second;
 return heap->active.load()&&address<(gpu?heap->gpuEnd:heap->cpuEnd)?heap:nullptr;
}
void EnsureHeapReleaseHook(ID3D12DescriptorHeap*){native();}
bool RegisterTrackedHeapLocked(const std::shared_ptr<HeapInfo>& h){heapRows.push_back(h);gHeapCpuRanges[h->cpuStart]=h;gHeapGpuRanges[h->gpuStart]=h;return true;}
using PFN_CreateGraphics=HRESULT(STDMETHODCALLTYPE*)(ID3D12Device*,const D3D12_GRAPHICS_PIPELINE_STATE_DESC*,REFIID,void**);
using PFN_CreateCompute=HRESULT(STDMETHODCALLTYPE*)(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,REFIID,void**);
using PFN_CreateStream=HRESULT(STDMETHODCALLTYPE*)(ID3D12Device2*,const D3D12_PIPELINE_STATE_STREAM_DESC*,REFIID,void**);
using PFN_CreateHeap=HRESULT(STDMETHODCALLTYPE*)(ID3D12Device*,D3D12_DESCRIPTOR_HEAP_DESC*,REFIID,void**);
PFN_CreateGraphics o_CreateGraphicsPipelineState=nullptr;PFN_CreateCompute o_CreateComputePipelineState=nullptr;
PFN_CreateStream o_CreatePipelineState=nullptr;PFN_CreateHeap o_CreateDescriptorHeap=nullptr;
unsigned originalCreates=0,originalBarriers=0,originalResets=0,originalCloses=0,originalSetters=0;
HRESULT originalResult=S_OK,resetResult=S_OK,closeResult=S_OK;void* originalOutput=nullptr;
class ResTrack_Dx12{
 public:
 static void HookDevice(ID3D12Device*){native();}
 static bool ObserveBridgeObjectRelease(IUnknown*) noexcept{return true;}
 static void SetRRResourceInspectorEnabled(bool);static bool IsRRResourceInspectorEnabled();
 static void NotifyRRResourceInspectorFrame(uint64_t);static void RefreshRRResourceCandidates(uint32_t,uint32_t);
 static std::vector<RRResourceCandidate> GetRRResourceCandidates();static void SetRRResourceCandidateIndex(int);static int GetRRResourceCandidateIndex();
 static ID3D12Resource* AcquireRRResourceCandidate(ID3D12GraphicsCommandList* =nullptr);static const char* GetRRResourceInspectorReason() noexcept;
 static HRESULT hkCreateGraphicsPipelineState(ID3D12Device*,const D3D12_GRAPHICS_PIPELINE_STATE_DESC*,REFIID,void**);
 static HRESULT hkCreateComputePipelineState(ID3D12Device*,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,REFIID,void**);
 static HRESULT hkCreatePipelineState(ID3D12Device2*,const D3D12_PIPELINE_STATE_STREAM_DESC*,REFIID,void**);
 static HRESULT hkCreateDescriptorHeap(ID3D12Device*,D3D12_DESCRIPTOR_HEAP_DESC*,REFIID,void**);
 static void hkResourceBarrier(ID3D12GraphicsCommandList*,UINT,const D3D12_RESOURCE_BARRIER*);
 static void hkSetPipelineState(ID3D12GraphicsCommandList*,ID3D12PipelineState*);
 static HRESULT hkReset(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*);
 static HRESULT hkClose(ID3D12GraphicsCommandList*);
 static SIZE_T GetGPUHandle(ID3D12Device*,SIZE_T,D3D12_DESCRIPTOR_HEAP_TYPE);static SIZE_T GetCPUHandle(ID3D12Device*,SIZE_T,D3D12_DESCRIPTOR_HEAP_TYPE);
 static inline std::mutex _resourceCommandListMutex;
 static inline std::unordered_map<int,ID3D12GraphicsCommandList*> _resourceCommandList[2],_resCmdList[2];
 static inline std::unordered_set<ID3D12GraphicsCommandList*> _notFoundCmdLists;
};
bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown*) noexcept{return true;}
std::pair<std::string,bool> GetRRActivePass(ID3D12GraphicsCommandList*){return {};}
void RecordRRComputeOutput(ID3D12GraphicsCommandList*,ID3D12Resource*){if(failProducer)throw std::bad_alloc();}
void(STDMETHODCALLTYPE* o_SetPipelineState)(ID3D12GraphicsCommandList*,ID3D12PipelineState*)=nullptr;
__BODIES__
struct Backing{
 std::atomic<ULONG> refs{1};std::mutex mutex;void* canonical=nullptr;bool stamped=false;NrdBridgeNativeBirth::NativeStamp stamp{};
};
struct CpuObject{
 PVOID* table;std::array<PVOID,64> slots{};std::shared_ptr<Backing> physical=std::make_shared<Backing>();
 D3D12_RESOURCE_DESC desc{};CpuObject* queried=nullptr;std::function<void()> afterIncrement,beforeAddRef;
 unsigned queries=0,canonicalQueries=0,canonicalReleased=0,descReads=0,privateReads=0,added=0,released=0,heapReads=0;
 bool nullQI=false;HRESULT qiResult=S_OK;UINT increment=32;
 template<class T>T* as(){return reinterpret_cast<T*>(this);}
 static CpuObject& self(void* p){return *static_cast<CpuObject*>(p);}
 // Preserve typed-interface queries separately from mandatory canonical IUnknown queries.
 static HRESULT STDMETHODCALLTYPE QI(IUnknown* p,REFIID iid,void** out){native();auto& o=self(p);const bool canonical=iid==IID_IUnknown;
  if(canonical){++nativeCanonicalQI;++o.canonicalQueries;}else{++nativeQI;++o.queries;}if(out)*out=nullptr;if(FAILED(o.qiResult)||!out)return o.qiResult;
  if(!o.nullQI){auto* t=canonical?static_cast<CpuObject*>(o.physical->canonical?o.physical->canonical:&o):o.queried?o.queried:&o;*out=t;Add(t->as<IUnknown>());}return o.qiResult;}
 static ULONG STDMETHODCALLTYPE Add(IUnknown* p){native();++nativeRefs;auto& o=self(p);++o.added;if(o.beforeAddRef)o.beforeAddRef();return ++o.physical->refs;}
 static ULONG STDMETHODCALLTYPE Release(IUnknown* p){native();++nativeRefs;auto& o=self(p);
  if(NrdBridgeNativeBirth::Detail::temporaryRelease==p)++o.canonicalReleased;else ++o.released;return --o.physical->refs;}
 static ULONG STDMETHODCALLTYPE DistinctRelease(IUnknown* p){return Release(p)+volatileTag;}
 static inline volatile unsigned volatileTag=0;
 static HRESULT STDMETHODCALLTYPE Get(IUnknown* p,REFGUID guid,UINT* bytes,void* output){native();++nativePrivate;auto& o=self(p);++o.privateReads;
  if(guid!=NrdBridgeNativeBirth::InstanceGuid)return DXGI_ERROR_NOT_FOUND;std::lock_guard lock(o.physical->mutex);
  if(!o.physical->stamped)return DXGI_ERROR_NOT_FOUND;if(*bytes<sizeof(o.physical->stamp)){*bytes=sizeof(o.physical->stamp);return DXGI_ERROR_MORE_DATA;}
  *bytes=sizeof(o.physical->stamp);std::memcpy(output,&o.physical->stamp,sizeof(o.physical->stamp));return S_OK;}
 static HRESULT STDMETHODCALLTYPE Set(IUnknown* p,REFGUID guid,UINT bytes,const void* input){native();auto& o=self(p);if(guid!=NrdBridgeNativeBirth::InstanceGuid||bytes!=sizeof(o.physical->stamp))return E_INVALIDARG;
  std::lock_guard lock(o.physical->mutex);o.physical->stamped=true;std::memcpy(&o.physical->stamp,input,bytes);return S_OK;}
 static D3D12_RESOURCE_DESC* STDMETHODCALLTYPE Desc(ID3D12Resource* p,D3D12_RESOURCE_DESC* output){native();++nativeDesc;auto& o=self(p);++o.descReads;*output=o.desc;return output;}
 static D3D12_CPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE Cpu(ID3D12DescriptorHeap* p,D3D12_CPU_DESCRIPTOR_HANDLE* output){native();++self(p).heapReads;*output={1000};return output;}
 static D3D12_GPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE Gpu(ID3D12DescriptorHeap* p,D3D12_GPU_DESCRIPTOR_HANDLE* output){native();++self(p).heapReads;*output={100000};return output;}
 static UINT STDMETHODCALLTYPE Increment(ID3D12Device* p,D3D12_DESCRIPTOR_HEAP_TYPE){native();auto& o=self(p);if(o.afterIncrement)o.afterIncrement();return o.increment;}
 CpuObject():table(slots.data()){
  physical->canonical=this;
  slots[0]=reinterpret_cast<PVOID>(QI);slots[1]=reinterpret_cast<PVOID>(Add);slots[2]=reinterpret_cast<PVOID>(Release);slots[3]=reinterpret_cast<PVOID>(Get);slots[4]=reinterpret_cast<PVOID>(Set);
  slots[9]=reinterpret_cast<PVOID>(closeNative);slots[10]=reinterpret_cast<PVOID>(resetNative);slots[26]=reinterpret_cast<PVOID>(barrierNative);
  desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=640;desc.Height=360;desc.DepthOrArraySize=1;desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Format=DXGI_FORMAT_R16_FLOAT;
 }
 void resourceLayout(){slots[10]=reinterpret_cast<PVOID>(Desc);}
 static HRESULT STDMETHODCALLTYPE resetNative(ID3D12GraphicsCommandList*,ID3D12CommandAllocator*,ID3D12PipelineState*){native();++originalResets;return resetResult;}
 static HRESULT STDMETHODCALLTYPE closeNative(ID3D12GraphicsCommandList*){native();++originalCloses;return closeResult;}
 static void STDMETHODCALLTYPE barrierNative(ID3D12GraphicsCommandList*,UINT,const D3D12_RESOURCE_BARRIER*){native();++originalBarriers;}
 static void STDMETHODCALLTYPE setterNative(ID3D12GraphicsCommandList*,ID3D12PipelineState*){native();++originalSetters;}
};
template<class Desc,class Device>HRESULT createNative(Device*,Desc*,REFIID,void** out){native();++originalCreates;if(out)*out=originalOutput;return originalResult;}
void* payload() noexcept{native();return new(std::nothrow) unsigned(0);}bool detach(void*,const Token& token) noexcept{
 try{ForgetRRRecording(token->Address(),token);{std::scoped_lock lock(gRRTrackedResourceMutex);EraseRRTrackedResourceLocked(static_cast<ID3D12Resource*>(token->Address()));}CleanupRRPsoReferences(token->Address());return true;}catch(...){return false;}
}void notify(void* p) noexcept{native();delete static_cast<unsigned*>(p);}
void setup(bool born,CpuObject& device){
 gNrdBridgeWrappers=born;if(born){need(NrdBridgeNativeBirth::ConfigureRetirement(payload,detach,notify),"native identity dispatcher setup");need(NrdBridgeLifetime::EnableConcurrentReleases(),"born inspector uses production concurrent physical release mode");}
 o_Release=reinterpret_cast<PFN_Release>(CpuObject::Release);gResourceReleaseEntry=reinterpret_cast<PVOID>(CpuObject::Release);
 o_Reset=CpuObject::resetNative;o_Close=CpuObject::closeNative;o_ResourceBarrier=CpuObject::barrierNative;o_SetPipelineState=CpuObject::setterNative;
 gComputeResetEntry=reinterpret_cast<PVOID>(o_Reset);gRRRecordingCloseEntry=reinterpret_cast<PVOID>(o_Close);gRRRecordingBarrierEntry=reinterpret_cast<PVOID>(o_ResourceBarrier);gComputeListHooksAvailable=true;
 o_CreateGraphicsPipelineState=createNative<const D3D12_GRAPHICS_PIPELINE_STATE_DESC,ID3D12Device>;o_CreateComputePipelineState=createNative<const D3D12_COMPUTE_PIPELINE_STATE_DESC,ID3D12Device>;
 o_CreatePipelineState=createNative<const D3D12_PIPELINE_STATE_STREAM_DESC,ID3D12Device2>;o_CreateDescriptorHeap=createNative<D3D12_DESCRIPTOR_HEAP_DESC,ID3D12Device>;
 device.slots[15]=reinterpret_cast<PVOID>(CpuObject::Increment);State::Instance().currentD3D12Device=device.as<ID3D12Device>();ResTrack_Dx12::SetRRResourceInspectorEnabled(true);
}
void barrier(CpuObject& list,CpuObject& resource,D3D12_RESOURCE_STATES after=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_BARRIER_FLAGS flags=D3D12_RESOURCE_BARRIER_FLAG_NONE,UINT subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES){
 D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;b.Flags=flags;b.Transition={resource.as<ID3D12Resource>(),subresource,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,after};ResTrack_Dx12::hkResourceBarrier(list.as<ID3D12GraphicsCommandList>(),1,&b);
}
bool acquire(CpuObject& list){auto* r=ResTrack_Dx12::AcquireRRResourceCandidate(list.as<ID3D12GraphicsCommandList>());if(r)r->Release();return r!=nullptr;}
void creators(CpuObject& device,bool born){
 CpuObject pso,alias;alias.queried=&pso;alias.physical=pso.physical;D3D12_GRAPHICS_PIPELINE_STATE_DESC g{};D3D12_COMPUTE_PIPELINE_STATE_DESC c{};D3D12_PIPELINE_STATE_STREAM_DESC s{};void* out=nullptr;
 originalOutput=&pso;need(ResTrack_Dx12::hkCreateGraphicsPipelineState(device.as<ID3D12Device>(),&g,__uuidof(ID3D12PipelineState),&out)==S_OK&&out==&pso&&pso.queries==0,"exact PSO IID requires no QI");
 for(unsigned kind=0;kind<3;++kind){originalOutput=&alias;const auto before=pso.physical->refs.load();HRESULT result=kind==0?ResTrack_Dx12::hkCreateGraphicsPipelineState(device.as<ID3D12Device>(),&g,IID_IUnknown,&out):kind==1?ResTrack_Dx12::hkCreateComputePipelineState(device.as<ID3D12Device>(),&c,IID_IUnknown,&out):ResTrack_Dx12::hkCreatePipelineState(device.as<ID3D12Device2>(),&s,IID_IUnknown,&out);
  need(result==S_OK&&out==&alias&&pso.physical->refs==before&&gRRPsoMetadata.contains(pso.as<ID3D12PipelineState>()),"all PSO creator kinds normalize valid IUnknown tearoff and balance typed temporary");}
 need(alias.queries==3&&pso.released==3,"exact typed-QI temporaries each released once outside guards");
 need(born ? pso.canonicalQueries>0&&pso.canonicalReleased==pso.canonicalQueries : pso.canonicalQueries==0&&pso.canonicalReleased==0,"canonical QI temporaries are separate, balanced, and absent from the legacy exact-IID path");
 if(born){const auto a=NrdBridgeBirth::Capture(&alias),b=NrdBridgeBirth::Capture(&pso);need(a&&b&&a->InstanceStamp()==b->InstanceStamp(),"successful typed QI proves alias physical native stamp");}
 originalOutput=nullptr;need(ResTrack_Dx12::hkCreateGraphicsPipelineState(device.as<ID3D12Device>(),&g,IID_IUnknown,&out)==S_OK&&!out,"null success preserves HRESULT without querying output");
 originalOutput=&alias;originalResult=E_FAIL;const auto queries=alias.queries;need(ResTrack_Dx12::hkCreateComputePipelineState(device.as<ID3D12Device>(),&c,IID_IUnknown,&out)==E_FAIL&&alias.queries==queries,"failed native creator does no typed normalization");originalResult=S_OK;
 CpuObject heap,heapAlias;heap.slots[9]=reinterpret_cast<PVOID>(CpuObject::Cpu);heap.slots[10]=reinterpret_cast<PVOID>(CpuObject::Gpu);heapAlias.queried=&heap;heapAlias.physical=heap.physical;
 D3D12_DESCRIPTOR_HEAP_DESC desc{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,16,D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE,0};originalOutput=&heap;
 need(ResTrack_Dx12::hkCreateDescriptorHeap(device.as<ID3D12Device>(),&desc,__uuidof(ID3D12DescriptorHeap),&out)==S_OK&&heap.queries==0,"exact heap IID fast path");
 originalOutput=&heapAlias;const auto refs=heap.physical->refs.load();need(ResTrack_Dx12::hkCreateDescriptorHeap(device.as<ID3D12Device>(),&desc,IID_IUnknown,&out)==S_OK&&out==&heapAlias&&heapAlias.queries==1&&heap.physical->refs==refs,"heap IUnknown tearoff normalizes typed native handle getters with balanced ref");
 need(heapRows.back()->heap==heap.as<ID3D12DescriptorHeap>(),"heap registry receives typed heap rather than IUnknown tearoff");
 const auto rows=heapRows.size();originalOutput=nullptr;need(ResTrack_Dx12::hkCreateDescriptorHeap(device.as<ID3D12Device>(),&desc,IID_IUnknown,&out)==S_OK&&heapRows.size()==rows,"null successful heap is not published");
 originalOutput=&heapAlias;originalResult=S_FALSE;need(ResTrack_Dx12::hkCreateDescriptorHeap(device.as<ID3D12Device>(),&desc,IID_IUnknown,&out)==S_FALSE&&heapRows.size()==rows,"successful non-S_OK native heap result preserved");originalResult=S_OK;
 auto tracked=heapRows.back();need(ResTrack_Dx12::GetGPUHandle(device.as<ID3D12Device>(),1064,desc.Type)==100064&&ResTrack_Dx12::GetCPUHandle(device.as<ID3D12Device>(),100064,desc.Type)==1064,"CPU/GPU indexed mapping arithmetic preserved");
 Gate getter;device.afterIncrement=[&]{getter.wait();};SIZE_T result=1;
 std::thread worker([&]{result=ResTrack_Dx12::GetGPUHandle(device.as<ID3D12Device>(),1064,desc.Type);});need(getter.reached(),"native device getter reached outside catalog");
 auto writer=std::async(std::launch::async,[&]{std::unique_lock lock(_heapRegistryMutex);tracked->active=false;++tracked->version;});const bool progressed=writer.wait_for(std::chrono::seconds(1))==std::future_status::ready;
 getter.release();worker.join();writer.get();device.afterIncrement={};need(progressed&&result==0,"parallel heap retirement progresses during blocked getter and invalidates copied range");
 CleanupRRPsoReferences(&pso);heapRows.clear();gHeapCpuRanges.clear();gHeapGpuRanges.clear();
}
void metadataScale(CpuObject& device,bool born){
 std::vector<std::unique_ptr<CpuObject>> live;live.reserve(100000);
 for(unsigned i=0;i<100000;++i){auto object=std::make_unique<CpuObject>();object->resourceLayout();if(i>=2){object->desc.Width=512;object->desc.Height=512;}TrackRRResourceView(object->as<ID3D12Resource>(),DXGI_FORMAT_R16_FLOAT,SRV);live.push_back(std::move(object));}
 need(gRRTrackedResources.size()==100000&&gRRResourceSizeIndex.size()==2,"100k actual metadata participants published into two size buckets");
 const auto descriptions=nativeDesc.load(),privateReads=nativePrivate.load();gRRTrackedResources.begins=0;ResTrack_Dx12::RefreshRRResourceCandidates(640,360);
 need(ResTrack_Dx12::GetRRResourceCandidates().size()==2&&gRRTrackedResources.begins==0,"refresh visits matching-size bucket without beginning full resource walk");
 need(nativeDesc==descriptions&&nativePrivate==privateReads,"refresh uses cached POD description/name and performs no native getter");
 auto& r=*live[0];const auto descReads=r.descReads,nameReads=r.privateReads;TrackRRResourceView(r.as<ID3D12Resource>(),DXGI_FORMAT_R16_FLOAT,UAV);
 need(r.descReads==descReads&&r.privateReads==nameReads,"warm view metadata reuse performs no native resource method");
 auto candidates=ResTrack_Dx12::GetRRResourceCandidates();unsigned index=0;for(unsigned i=0;i<candidates.size();++i)if(candidates[i].resourceAddress==&r)index=i;ResTrack_Dx12::SetRRResourceCandidateIndex(index);
 CpuObject a,b;
 const auto count=originalBarriers;failNextProof=true;barrier(b,r);need(originalBarriers==count+1&&!acquire(b),"failed optional proof allocation invalidates state and preserves native barrier exactly once");
 failProducer=true;barrier(b,r);failProducer=false;need(originalBarriers==count+2,"failed optional producer observation cannot suppress native barrier");
 barrier(b,r);need(!acquire(a),"list B unsubmitted readable state can never admit list A preview");need(acquire(b),"same recording whole-resource readable transition admits preview");
 barrier(a,r);need(acquire(a)&&!acquire(b),"foreign selected-resource state observation invalidates prior recording proof");
 resetResult=E_FAIL;need(FAILED(ResTrack_Dx12::hkReset(a.as<ID3D12GraphicsCommandList>(),nullptr,nullptr))&&acquire(a),"failed Reset preserves current recording proof");resetResult=S_OK;
 need(SUCCEEDED(ResTrack_Dx12::hkReset(a.as<ID3D12GraphicsCommandList>(),nullptr,nullptr))&&!acquire(a),"successful Reset invalidates recording even though physical stamp is unchanged");
 barrier(a,r);closeResult=E_FAIL;need(FAILED(ResTrack_Dx12::hkClose(a.as<ID3D12GraphicsCommandList>()))&&acquire(a),"failed Close preserves recording proof");closeResult=S_OK;
 need(SUCCEEDED(ResTrack_Dx12::hkClose(a.as<ID3D12GraphicsCommandList>()))&&!acquire(a),"successful Close invalidates recording proof");
 barrier(a,r);const auto epoch=gRRSelectionEpoch.load();ResTrack_Dx12::SetRRResourceCandidateIndex(index);need(epoch==gRRSelectionEpoch&&acquire(a),"unchanged selection does not invalidate proof");ResTrack_Dx12::SetRRResourceCandidateIndex(1-index);ResTrack_Dx12::SetRRResourceCandidateIndex(index);need(!acquire(a),"A-to-B-to-A selection requires new observation without scanning lists");
 barrier(a,r);barrier(a,r,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);need(!acquire(a),"split begin invalidates preview");barrier(a,r,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_BARRIER_FLAG_END_ONLY);need(!acquire(a),"split end does not invent whole completed proof");
 barrier(a,r);D3D12_RESOURCE_BARRIER alias{};alias.Type=D3D12_RESOURCE_BARRIER_TYPE_ALIASING;ResTrack_Dx12::hkResourceBarrier(a.as<ID3D12GraphicsCommandList>(),1,&alias);need(!acquire(a),"global alias barrier invalidates selected proof");
 barrier(a,r,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);need(!acquire(a),"pixel-only state cannot feed compute preview");barrier(a,r,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);need(!acquire(a),"writable UAV state rejected");
 barrier(a,r);const auto version=gRRTrackedResources.at(r.as<ID3D12Resource>()).version;{std::scoped_lock lock(gRRTrackedResourceMutex);EraseRRTrackedResourceLocked(r.as<ID3D12Resource>());}TrackRRResourceView(r.as<ID3D12Resource>(),DXGI_FORMAT_R16_FLOAT,SRV);need(gRRTrackedResources.at(r.as<ID3D12Resource>()).version!=version&&!acquire(a),"stale UI registry version cannot lend a weak AddRef");ResTrack_Dx12::RefreshRRResourceCandidates(640,360);candidates=ResTrack_Dx12::GetRRResourceCandidates();for(unsigned i=0;i<candidates.size();++i)if(candidates[i].resourceAddress==&r)index=i;ResTrack_Dx12::SetRRResourceCandidateIndex(index);barrier(a,r);
 CpuObject unknown;unknown.slots[10]=nullptr;need(!acquire(unknown)&&std::string(ResTrack_Dx12::GetRRResourceInspectorReason()).find("GPU state unavailable")!=std::string::npos,"unknown Reset/Release implementation is a GPU-proof denial");
 if(born){CpuObject same;same.physical=a.physical;need(acquire(same),"explicit identical native private GUID proves physical list alias");need(SUCCEEDED(ResTrack_Dx12::hkReset(same.as<ID3D12GraphicsCommandList>(),nullptr,nullptr))&&!acquire(a),"Reset on proved alias invalidates same physical recording");barrier(a,r);
  const auto old=NrdBridgeBirth::Capture(&a);{NrdBridgeBirth::ScopedRelease inFlight(old);a.physical=std::make_shared<Backing>();a.physical->canonical=&a;need(!acquire(a),"recycled address with different native GUID cannot inherit old recording");}barrier(a,r);need(acquire(a),"new physical recording can obtain independent proof");ForgetRRRecording(&a,NrdBridgeBirth::Capture(&a));need(!acquire(a),"native final retirement removes exact physical recording directly");
 }else{ForgetRRRecording(&a);need(!acquire(a),"legacy final list retirement removes exact recording address directly");}
 barrier(a,r);Gate add;std::atomic<bool> releaseEntered=false;ID3D12Resource* borrowed=nullptr;r.beforeAddRef=[&]{add.wait();};
 std::thread reader([&]{borrowed=ResTrack_Dx12::AcquireRRResourceCandidate(a.as<ID3D12GraphicsCommandList>());});need(add.reached(),"weak native AddRef reached after admission guards");
 auto releaser=std::async(std::launch::async,[&]{NrdBridgeLifetime::ScopedRelease guard(NeedsNativeReleaseGate());releaseEntered=true;return CpuObject::Release(r.as<IUnknown>());});
 const bool blocked=releaser.wait_for(std::chrono::milliseconds(30))==std::future_status::timeout&&!releaseEntered;add.release();reader.join();const auto refs=releaser.get();r.beforeAddRef={};need(blocked&&borrowed&&refs==1,"physical lifetime gate blocks caller final Release through weak AddRef without persistent refs");if(borrowed)borrowed->Release();
 need(gRRTrackedResources.begins==0,"all selected recording/candidate operations avoid whole resource traversal");
 CpuObject owned,ownedPso,ownedList;owned.resourceLayout();TrackRRResourceView(owned.as<ID3D12Resource>(),DXGI_FORMAT_R16_FLOAT,SRV);PublishRRPsoMetadata(ownedPso.as<ID3D12PipelineState>());ResTrack_Dx12::hkSetPipelineState(ownedList.as<ID3D12GraphicsCommandList>(),ownedPso.as<ID3D12PipelineState>());
 {FrameSurvey::ScopedInternal internal;TrackRRResourceView(owned.as<ID3D12Resource>(),DXGI_FORMAT_R16_FLOAT,SRV);PublishRRPsoMetadata(ownedPso.as<ID3D12PipelineState>());ResTrack_Dx12::hkSetPipelineState(ownedList.as<ID3D12GraphicsCommandList>(),ownedPso.as<ID3D12PipelineState>());
  need(!gRRTrackedResources.contains(owned.as<ID3D12Resource>())&&!gRRPsoMetadata.contains(ownedPso.as<ID3D12PipelineState>())&&!gRRCommandListPsoStates.contains(ownedList.as<ID3D12GraphicsCommandList>()),"identified owned resource/PSO/list calls remove old weak rows and publish none");
  NrdBridgeLifetime::ScopedBorrow borrow(true);need(borrow.Acquired()&&!NeedsNativeReleaseGate(),"sticky inspector preserves genuine owned Release bypass under legacy Borrow");}
 {FrameSurvey::ScopedInternal internal;FrameSurvey::ScopedRecording recording;need(NeedsNativeReleaseGate(),"ScopedRecording title Release remains protected when inspector sticky latch is on");TrackRRResourceView(owned.as<ID3D12Resource>(),DXGI_FORMAT_R16_FLOAT,SRV);need(gRRTrackedResources.contains(owned.as<ID3D12Resource>()),"ScopedRecording title resource remains eligible for weak metadata");}
 ResTrack_Dx12::SetRRResourceInspectorEnabled(false);need(gRRResourceSizeIndex.empty()&&gRRTrackedResources.empty()&&gRRRecordingProofs.empty(),"inspector disable clears cache/index/recording maps");
}
void slowLegacyInstall(){
 CpuObject slow,other;slow.slots[2]=reinterpret_cast<PVOID>(CpuObject::DistinctRelease);Gate blocked;attachGate=&blocked;bool published=false;
 std::thread installer([&]{published=PublishRRPsoMetadata(slow.as<ID3D12PipelineState>());});need(blocked.reached(),"cold Detours seam is reached with caller strong PSO");
 auto writer=std::async(std::launch::async,[&]{std::scoped_lock lock(gRRPsoMutex);EnsureRRPsoMetadata(other.as<ID3D12PipelineState>());});const bool progressed=writer.wait_for(std::chrono::seconds(1))==std::future_status::ready;blocked.release();installer.join();writer.get();attachGate=nullptr;
 need(progressed&&published&&attaches==1,"independent PSO metadata publication progresses during blocked native installer");
 CleanupRRPsoReferences(&slow);CleanupRRPsoReferences(&other);
}
int main(int argc,char**argv)try{
 SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);const bool born=argc>1&&std::string(argv[1])=="born";
 CpuObject device;setup(born,device);creators(device,born);metadataScale(device,born);if(!born)slowLegacyInstall();need(nativeUnderMetadata==0,"all native methods/AddRef/Release/installer/owner notification execute outside Birth and common metadata locks");
 std::cout<<"{\"case\":\""<<(born?"born":"legacy")<<"\",\"checks\":"<<checks<<",\"liveResources\":100000,\"nativeUnderMetadata\":"<<nativeUnderMetadata<<",\"originalCreates\":"<<originalCreates<<",\"originalBarriers\":"<<originalBarriers<<",\"originalResets\":"<<originalResets<<",\"originalCloses\":"<<originalCloses<<",\"typedQI\":"<<nativeQI<<",\"canonicalQI\":"<<nativeCanonicalQI<<"}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
'''


def block(source, name):
    start = source.index('struct ' + name)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:source.index(';', end) + 1]


def generate(out):
    source_path = ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp'
    header_path = ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.h'
    source, header = source_path.read_text(), header_path.read_text()
    globals_ = source[source.index('static std::atomic<bool> gRRResourceInspectorEnabled'):source.index('static uint64_t HashRRBytes')]
    # Lock instrumentation and container traversal probes are CPU seams only.
    globals_ = globals_.replace('NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking>', 'TestMutex')
    globals_ = globals_.replace('static std::mutex gRRResourceCandidateMutex', 'static TestMutex gRRResourceCandidateMutex')
    globals_ = globals_.replace('static std::mutex gRRMarkerMutex', 'static TestMutex gRRMarkerMutex')
    globals_ = globals_.replace('std::unordered_map<ID3D12Resource*, RRTrackedResourceViews>', 'CountedMap<ID3D12Resource*, RRTrackedResourceViews>')
    globals_ = globals_.replace('std::unordered_map<RRRecordingKey,RRRecordingProof,RRRecordingKeyHash>', 'FailureMap<RRRecordingKey,RRRecordingProof,RRRecordingKeyHash>')
    signatures = ['static bool NeedsNativeReleaseGate(', 'static bool RRPhysicalReleaseCovered(',
                  'static uint64_t HashRRBytes(', 'static uint64_t HashRRShader(',
                  'static uint64_t HashRRGraphicsPipeline(', 'static uint64_t HashRRComputePipeline(',
                  'static void CleanupRRPsoReferences(', 'static void ForgetOwnedRRList(',
                  'static bool EnsurePsoReleaseHook(', 'static bool RRInspectorBirthsEnabled(',
                  'template <class T> static NrdBridgeBirth::Token RRStrongReceiver(',
                  'static RRPreparedRecording PrepareRRRecording(', 'static RRSelectedIdentity CaptureRRSelectedIdentity(',
                  'static void SelectRRResourceLocked(', 'static bool RRBarrierTouchesSelected(',
                  'static void ObserveRRSelectedStateLocked(', 'static void RRRecordingSucceeded(']
    bodies = [function(source, name) for name in signatures]
    bodies += [block(source, 'ReturnedPipelineInterface'), block(source, 'ReturnedHeapInterface')]
    signatures2 = ['static RRPsoMetadata& EnsureRRPsoMetadata(', 'static RRPsoMetadata* FindRRPsoMetadataLocked(',
                   'static bool PublishRRPsoMetadata(', 'static void PublishCreatedRRPso(',
                   'static RRCommandListPsoState& RRPsoListStateLocked(',
                   'static uint32_t GetRRFormatChannelCount(', 'static bool IsRRScalarCandidateFormat(',
                   'static void TrackRRResourceView(', 'static bool IsRRResourceComputeReadable(',
                   'static bool IsRRResourceWritable(', 'static void RecordRRResourceWrite(',
                   'void ResTrack_Dx12::SetRRResourceInspectorEnabled(', 'bool ResTrack_Dx12::IsRRResourceInspectorEnabled(',
                   'void ResTrack_Dx12::SetRRResourceCandidateIndex(', 'int ResTrack_Dx12::GetRRResourceCandidateIndex(',
                   'void ResTrack_Dx12::NotifyRRResourceInspectorFrame(', 'void ResTrack_Dx12::RefreshRRResourceCandidates(',
                   'std::vector<RRResourceCandidate> ResTrack_Dx12::GetRRResourceCandidates(',
                   'const char* ResTrack_Dx12::GetRRResourceInspectorReason(', 'ID3D12Resource* ResTrack_Dx12::AcquireRRResourceCandidate(',
                   'HRESULT ResTrack_Dx12::hkCreateGraphicsPipelineState(', 'HRESULT ResTrack_Dx12::hkCreateComputePipelineState(',
                   'HRESULT ResTrack_Dx12::hkCreatePipelineState(', 'HRESULT ResTrack_Dx12::hkCreateDescriptorHeap(',
                   'void ResTrack_Dx12::hkResourceBarrier(', 'void ResTrack_Dx12::hkSetPipelineState(',
                   'HRESULT ResTrack_Dx12::hkReset(', 'HRESULT ResTrack_Dx12::hkClose(',
                   'SIZE_T ResTrack_Dx12::GetGPUHandle(', 'SIZE_T ResTrack_Dx12::GetCPUHandle(']
    bodies += [function(source, name) for name in signatures2]
    text = CPP.replace('__ROOT__', ROOT.as_posix()).replace('__CANDIDATE__', block(header, 'RRResourceCandidate'))
    text = text.replace('__GLOBALS__', globals_).replace('__BODIES__', '\n\n'.join(bodies))
    assert not re.search(r'__[A-Z_]+__', text)
    out.mkdir(parents=True, exist_ok=True)
    target = out/'rr_inspector.cpp'
    target.write_text(text, encoding='utf-8')
    paths = [source_path, header_path, *(ROOT/('OptiScaler/misc/'+name) for name in
             ['NrdBridgeBirth_Dx12.h', 'NrdBridgeNativeBirth_Dx12.h', 'NrdBridgeLifetime_Dx12.h', 'NrdBridgePerf_Dx12.h'])]
    contract = {'scope': __doc__, 'source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                'unchanged_extracted_function_count': len(signatures)+len(signatures2),
                'body_sha256': [hashlib.sha256(body.encode()).hexdigest() for body in bodies],
                'seams': ['native COM-byte ABI/vtables/refcounts/private GUID', 'Detours transaction',
                          'FG/queue lease/trace notification', 'heap registry facade',
                          'mutex lock-depth counters; resource map begin counter'],
                'existing_release_tests_modified': False, 'gpu_work': False}
    (out/'contract.json').write_text(json.dumps(contract, indent=2), encoding='utf-8')
    return target, contract


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT/'rr_inspector_output'))
    source, contract = generate(out)
    if '--prepare-only' in sys.argv:
        print(json.dumps({'source': str(source), 'extracted_bodies': contract['unchanged_extracted_function_count'],
                          'compiled': False, 'executed': False}))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe = out/'rr_inspector.exe'
    build = compile_cpp(source, exe, ('bcrypt.lib', 'dxguid.lib'), (ROOT/'OptiScaler',))
    (out/'build.json').write_text(json.dumps(build, indent=2), encoding='utf-8')
    results = []
    for case in ['legacy', 'born']:
        result = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=90)
        (out/(case+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        result.check_returncode()
        values = json.loads(result.stdout)
        assert values['checks'] > 0 and values['nativeUnderMetadata'] == 0 and values['liveResources'] == 100000
        results.append(values)
    result = {'scope': contract['scope'], 'cases': results, 'checks': sum(case['checks'] for case in results)}
    (out/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
