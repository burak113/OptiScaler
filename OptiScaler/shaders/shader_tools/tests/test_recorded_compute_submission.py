"""Actual lease ledger and submission/eligibility functions, fake COM CPU + real WARP queues.

The CPU COM implementations come from the installed SDK interface declarations.
The application/FG/logging hooks are adapters; BeforeComputeSubmission, retention,
eligibility, before/after submission and fence-wait code are production extraction.
The actual native-birth facade is included but intentionally unconfigured here;
configured physical Release/birth behavior has separate native fixtures.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp, visual_studio, _toolchain_environment

ROOT = Path(__file__).resolve().parents[4]


def function(text, signature):
    start = text.index(signature)
    opening = text.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def methods(sdk, name, custom):
    body = re.search(r'\b' + name + r'\s*:\s*public\s+\w+\s*\{(.*?)\n\s*\};', sdk, re.S).group(1)
    # This fixture is compiled with MSVC. SDK aggregate-return declarations also
    # contain an alternate non-MSVC ABI; retain only the actual MSVC branch.
    body = re.sub(r'#if defined\(_MSC_VER\) \|\| !defined\(_WIN32\)\s*(.*?)#else.*?#endif', r'\1', body, flags=re.S)
    result = []
    for match in re.finditer(r'virtual\s+(.*?)\s*=\s*0\s*;', body, re.S):
        signature = re.sub(r'/\*.*?\*/', '', match.group(1), flags=re.S).strip()
        method = re.search(r'STDMETHODCALLTYPE\s+(\w+)\s*\(', signature).group(1)
        ret = signature[:signature.index('STDMETHODCALLTYPE')].strip()
        code = custom.get(method, '{}' if ret == 'void' else '{ return {}; }')
        result.append(signature + ' override ' + code)
    return '\n'.join(result)


def fake_com(sdk):
    base = r'''
#define OBJECT_BASE(IFACE) \
 std::atomic<ULONG> refs{1}; bool failIdentity=false; \
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override { \
  *out=nullptr; if(iid==IID_IUnknown && failIdentity) return E_FAIL; if(iid!=IID_IUnknown && iid!=__uuidof(IFACE)) return E_NOINTERFACE; \
  *out=static_cast<IFACE*>(this); AddRef(); return S_OK; } \
 ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; } \
 ULONG STDMETHODCALLTYPE Release() override { auto value=--refs; if(!value) delete this; return value; } \
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID,UINT*,void*) override { return E_NOTIMPL; } \
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID,UINT,const void*) override { return S_OK; } \
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*) override { return S_OK; } \
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR) override { return S_OK; }
#define CHILD_DEVICE \
 IUnknown* owner; \
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID iid,void** out) override { return owner->QueryInterface(iid,out); }
struct FakeDevice;
'''
    fence = methods(sdk, 'ID3D12Fence', {
        'GetCompletedValue': '{ return completed.load(); }',
        'Signal': '{ completed.store(Value); return S_OK; }',
    })
    queue = methods(sdk, 'ID3D12CommandQueue', {
        'Signal': '{ event("Signal"); if(failSignal) return E_FAIL; if(completeSignal) return pFence->Signal(Value); return S_OK; }',
        'Wait': '{ event("Wait"); ++waitAttempts; if(failWait || failNextWaits){if(failNextWaits)--failNextWaits;return E_OUTOFMEMORY;} return S_OK; }',
        'ExecuteCommandLists': '{ event("Execute"); ++executions; }',
    })
    allocator = methods(sdk, 'ID3D12CommandAllocator', {})
    resource = methods(sdk, 'ID3D12Resource', {})
    graphics = methods(sdk, 'ID3D12GraphicsCommandList', {})
    device = methods(sdk, 'ID3D12Device', {
        'CreateFence': '{ if(failFence) return E_FAIL; *ppFence=new FakeFence(this,InitialValue); return S_OK; }',
        'CreateCommandQueue': '{ *ppCommandQueue=new FakeQueue(this); return S_OK; }',
        'CreateCommandAllocator': '{ *ppCommandAllocator=new FakeAllocator(this); return S_OK; }',
        'CreateCommandList': '{ *ppCommandList=new FakeList(this); return S_OK; }',
        'CreateCommittedResource': '{ *ppvResource=new FakeResource(this); return S_OK; }',
    })
    observed_queue = methods(sdk, 'ID3D12CommandQueue', {
        'Signal': '{ event("RealSignal"); ++signals; return native->Signal(pFence,Value); }',
        'Wait': '{ ++waitAttempts;if(failWait || failNextWaits){event("RejectedWait");if(failNextWaits)--failNextWaits;return E_OUTOFMEMORY;} event("RealWait"); ++waits; return native->Wait(pFence,Value); }',
        'ExecuteCommandLists': '{ event("RealExecute"); ++executions; native->ExecuteCommandLists(NumCommandLists,ppCommandLists); }',
        'GetDesc': '{ return native->GetDesc(); }',
    })
    return base + r'''
struct FakeFence : ID3D12Fence {
 OBJECT_BASE(ID3D12Fence) CHILD_DEVICE
 std::atomic<UINT64> completed;
 FakeFence(IUnknown* device,UINT64 value):owner(device),completed(value) { owner->AddRef(); }
 ~FakeFence() { owner->Release(); }
''' + fence + r'''
};
struct FakeQueue : ID3D12CommandQueue {
 OBJECT_BASE(ID3D12CommandQueue) CHILD_DEVICE
 bool failSignal=false,failWait=false,completeSignal=true; unsigned executions=0,waitAttempts=0,failNextWaits=0;
 explicit FakeQueue(IUnknown* device):owner(device) { owner->AddRef(); }
 ~FakeQueue() { owner->Release(); }
''' + queue + r'''
};
struct FakeAllocator : ID3D12CommandAllocator {
 OBJECT_BASE(ID3D12CommandAllocator) CHILD_DEVICE
 explicit FakeAllocator(IUnknown* device):owner(device) { owner->AddRef(); }
 ~FakeAllocator() { owner->Release(); }
''' + allocator + r'''
};
struct FakeResource : ID3D12Resource {
 OBJECT_BASE(ID3D12Resource) CHILD_DEVICE
 explicit FakeResource(IUnknown* device):owner(device) { owner->AddRef(); }
 ~FakeResource() { owner->Release(); }
''' + resource + r'''
};
struct FakeList : ID3D12GraphicsCommandList {
 OBJECT_BASE(ID3D12GraphicsCommandList) CHILD_DEVICE
 explicit FakeList(IUnknown* device):owner(device) { owner->AddRef(); }
 ~FakeList() { owner->Release(); }
 D3D12_COMMAND_LIST_TYPE STDMETHODCALLTYPE GetType() override { return D3D12_COMMAND_LIST_TYPE_DIRECT; }
''' + graphics + r'''
};
struct FakeDevice : ID3D12Device {
 OBJECT_BASE(ID3D12Device)
 bool failFence=false;
''' + device + r'''
};
constexpr IID nativeIid {0xadec44e2,0x61f0,0x45c3,{0xad,0x9f,0x1b,0x37,0x37,0x92,0x84,0xff}};
struct ProxyList : ID3D12CommandList {
 std::atomic<ULONG> refs{1}; ComPtr<ID3D12GraphicsCommandList> native;bool failIdentity=false;
 explicit ProxyList(ID3D12GraphicsCommandList* list):native(list) {}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override {
  if(failIdentity && (iid==nativeIid || iid==IID_IUnknown)){*out=nullptr;return E_FAIL;}
  if(iid==nativeIid) return native->QueryInterface(IID_IUnknown,out);
  *out=nullptr; if(iid!=IID_IUnknown && iid!=__uuidof(ID3D12CommandList)) return E_NOINTERFACE;
  *out=this; AddRef(); return S_OK;
 }
 ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
 ULONG STDMETHODCALLTYPE Release() override { auto value=--refs; if(!value) delete this; return value; }
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID,UINT*,void*) override { return E_NOTIMPL; }
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID,UINT,const void*) override { return S_OK; }
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID,const IUnknown*) override { return S_OK; }
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR) override { return S_OK; }
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID iid,void** out) override { return native->GetDevice(iid,out); }
 D3D12_COMMAND_LIST_TYPE STDMETHODCALLTYPE GetType() override { return native->GetType(); }
};
struct ObservedQueue : ID3D12CommandQueue {
 OBJECT_BASE(ID3D12CommandQueue)
 ComPtr<ID3D12CommandQueue> native;unsigned executions=0,waits=0,signals=0,waitAttempts=0,failNextWaits=0;bool failWait=false;
 explicit ObservedQueue(ID3D12CommandQueue* queue):native(queue){}
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID iid,void** out) override{return native->GetDevice(iid,out);}
''' + observed_queue + r'''
};
'''


PREAMBLE = r'''
#define NOMINMAX
#define FSRD_RECORDED_COMPUTE_LEASE_TEST
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <new>
#include <thread>
#include <json.hpp>
#include "__LEDGER__"
#include "__NATIVE_BIRTH__"
#include "__SURVEY_HEADER__"
using Microsoft::WRL::ComPtr;
using J=nlohmann::json;
std::atomic<bool> denyAllocations=false;
std::atomic<long> allocationBudget=-1;
std::atomic<unsigned> deniedAllocations=0;
void* operator new(size_t bytes) { if(denyAllocations.load() || allocationBudget.load()==0) { ++deniedAllocations; throw std::bad_alloc(); } if(allocationBudget.load()>0)--allocationBudget; if(auto* p=std::malloc(bytes?bytes:1)) return p; throw std::bad_alloc(); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p,size_t) noexcept { std::free(p); }
void* operator new[](size_t bytes) { return ::operator new(bytes); }
void operator delete[](void* p) noexcept { ::operator delete(p); }
std::array<const char*,512> events{}; size_t eventCount=0;
void event(const char* text) { if(eventCount<events.size()) events[eventCount++]=text; }
unsigned checks=0;
void need(bool ok,const char* text) { ++checks; if(!ok) { std::fprintf(stderr,"FAIL %s\n",text); std::exit(1); } }
void hr(HRESULT result) { need(SUCCEEDED(result),"HRESULT succeeded"); }
bool registryFree() { auto& r=RecordedComputeLease::GetRegistry(); if(!r.mutex.try_lock()) return false; r.mutex.unlock(); return true; }
void resetRegistry() {
 RecordedComputeLease::ResetRegistryForTesting();
 eventCount=0; // Fixture only: every real GPU operation has been explicitly drained before this is called.
}
struct State { bool isShuttingDown=false; static State& Instance() { static State state; return state; } };
std::atomic<unsigned> unexpectedNativeCoverage=0,unexpectedMetadataFailure=0;
namespace FrameSurvey {
 thread_local bool gInternal=false;
 thread_local unsigned gRecordingDepth=0;
__SURVEY_SCOPES__
 void MetadataHookFailed(const char*) noexcept { ++unexpectedMetadataFailure; }
 void FlushMetadataFailure() noexcept {}
}
// This fixture owns an empty detour-installation table. Configured native birth
// and physical Release coverage have their separate actual production fixtures.
using PFN_BirthRelease=ULONG(STDMETHODCALLTYPE*)(IUnknown*);
static PFN_BirthRelease FindBirthReleaseOriginal(PVOID) noexcept { return nullptr; }
PVOID gResourceReleaseEntry=nullptr,gPsoReleaseEntry=nullptr,gCommandListReleaseEntry=nullptr,gComputeResetEntry=nullptr,gComputeExecuteEntry=nullptr;
ComPtr<IUnknown> gComputeQueueDeviceIdentity;
std::atomic<bool> gComputeListHooksAvailable=false,gComputeQueueHookAvailable=false;
std::mutex gComputeHookInitMutex;
bool gNrdBridgeWrappers=true, fixtureResourceHookFails=false;
struct ResTrack_Dx12 {
 static std::shared_ptr<RecordedComputeLease::Submission> BeforeComputeSubmission(ID3D12CommandQueue*,UINT,ID3D12CommandList* const*,RecordedComputeLease::SubmissionDecision* = nullptr) noexcept;
 static bool RefreshComputeHookDevice(ID3D12Device*,const char** =nullptr) noexcept;
 static bool RetainComputeDispatch(ID3D12Device*,ID3D12GraphicsCommandList*,const std::shared_ptr<void>&,std::function<void(ID3D12CommandQueue*)> = {},RecordedComputeLease::SubmissionCallbacks = {});
 static bool CheckForRealObject(const std::string,IUnknown*,IUnknown**) { return false; }
 static void HookResource(ID3D12Device*);
 static void HookCommandList(ID3D12Device*);
 static void HookToQueue(ID3D12Device*);
 static bool ObserveBridgeObjectRelease(IUnknown*) noexcept { ++unexpectedNativeCoverage; return false; }
};
bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown* object) noexcept {
 return ResTrack_Dx12::ObserveBridgeObjectRelease(object);
}
void ResTrack_Dx12::HookResource(ID3D12Device* device) {
 if(gResourceReleaseEntry || fixtureResourceHookFails) return;
 D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
 D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=16;desc.Height=desc.DepthOrArraySize=desc.MipLevels=desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
 ComPtr<ID3D12Resource> resource;hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&resource)));
 gResourceReleaseEntry=(*reinterpret_cast<PVOID**>(resource.Get()))[2];
}
void ResTrack_Dx12::HookCommandList(ID3D12Device* device) {
 if(gComputeResetEntry) return;
 ComPtr<ID3D12CommandAllocator> allocator;ComPtr<ID3D12GraphicsCommandList> list;
 hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
 hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
 auto** table=*reinterpret_cast<PVOID**>(list.Get());gComputeResetEntry=table[10];gCommandListReleaseEntry=table[2];gComputeListHooksAvailable=true;
 RecordedComputeLease::SetHooksAvailable(true,gComputeQueueHookAvailable.load());
}
void ResTrack_Dx12::HookToQueue(ID3D12Device* device) {
 if(gComputeExecuteEntry) return;
 ComPtr<ID3D12CommandQueue> direct,compute;D3D12_COMMAND_QUEUE_DESC desc{};desc.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
 hr(device->CreateCommandQueue(&desc,IID_PPV_ARGS(&direct)));desc.Type=D3D12_COMMAND_LIST_TYPE_COMPUTE;hr(device->CreateCommandQueue(&desc,IID_PPV_ARGS(&compute)));
 gComputeExecuteEntry=(*reinterpret_cast<PVOID**>(direct.Get()))[10];gComputeQueueHookAvailable=(*reinterpret_cast<PVOID**>(compute.Get()))[10]==gComputeExecuteEntry;
 hr(device->QueryInterface(IID_PPV_ARGS(&gComputeQueueDeviceIdentity)));RecordedComputeLease::SetHooksAvailable(true,gComputeQueueHookAvailable.load());
}
__PRODUCTION__
RecordedComputeLease::SubmissionDecision execute(ID3D12CommandQueue* queue,ID3D12CommandList* list) {
 RecordedComputeLease::SubmissionDecision decision;auto intent=ResTrack_Dx12::BeforeComputeSubmission(queue,1,&list,&decision);
 if(!decision.allowed)return decision;
 queue->ExecuteCommandLists(1,&list);
 RecordedComputeLease::AfterSubmission(intent);
 return decision;
}
void batch(ID3D12CommandQueue* queue,UINT count,ID3D12CommandList* const* lists){
 RecordedComputeLease::SubmissionDecision decision;auto intent=ResTrack_Dx12::BeforeComputeSubmission(queue,count,lists,&decision);if(!decision.allowed)return;
 queue->ExecuteCommandLists(count,lists);RecordedComputeLease::AfterSubmission(intent);
}
void detach(IUnknown* list) { auto record=RecordedComputeLease::Capture(list);RecordedComputeLease::Detach(record); }
'''


CPU = r'''
J cpuTests() {
 need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"scope fixture starts outside helper recording");
 {
  FrameSurvey::ScopedInternal helper;
  need(FrameSurvey::Internal()&&FrameSurvey::OwnedRelease(),"owned helper work remains suppressed");
  { FrameSurvey::ScopedRecording title;
   need(FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"explicit title recording stays internal but admits title lifetime");
   { FrameSurvey::ScopedRecording nested;need(FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"nested title recording keeps exact depth"); }
  }
  need(FrameSurvey::Internal()&&FrameSurvey::OwnedRelease(),"title scope restores owned helper suppression");
 }
 need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"all scope state restores after helper work");
 resetRegistry();ComPtr<FakeDevice> device;device.Attach(new FakeDevice);
 ComPtr<FakeQueue> qa,qb;qa.Attach(new FakeQueue(device.Get()));qb.Attach(new FakeQueue(device.Get()));
 ComPtr<FakeList> a,b;a.Attach(new FakeList(device.Get()));b.Attach(new FakeList(device.Get()));
 RecordedComputeLease::FencePointPtr previous;unsigned legacy=0,published=0,failed=0;uint64_t firstId=0;
 std::vector<uint64_t> ordinals;
 RecordedComputeLease::SubmissionCallbacks callbacks;
 callbacks.beforeSubmit=[&](const auto& info) { need(registryFree(),"prepare runs outside registry lock");if(!firstId)firstId=info.recordingId;ordinals.push_back(info.recordingSubmission);return SUCCEEDED(RecordedComputeLease::WaitForFence(info.queue,previous)); };
 callbacks.fencePublished=[&](const auto& info,const auto& point) { need(registryFree(),"publication runs outside registry lock");need(point && point->IsPublished() && point->value==1,"only successful signal publishes immutable lightweight point");previous=point;++published;event("Published"); };
 callbacks.failed=[&](const auto&,auto) { need(registryFree(),"failure runs outside registry lock");++failed; };
 auto lease=std::make_shared<int>(1);
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,[&](auto*){++legacy;},callbacks),"record first list");
 execute(qa.Get(),a.Get());need(legacy==1 && published==1 && !failed,"first preparation/signal/publication once");
 const auto firstPoint=previous;execute(qb.Get(),a.Get());
 need(legacy==2 && published==2 && previous!=firstPoint,"resubmission has independent fence and unchanged legacy callback");
 need(ordinals==std::vector<uint64_t>{1,2},"per-recording submission ordinal detects resubmission");
 need(firstId!=0,"recording ids are nonzero");
 need(std::string(events[3])=="Wait" && std::string(events[4])=="Execute" && std::string(events[5])=="Signal" && std::string(events[6])=="Published","actual second queue waits before execute, signal then publication");
 auto old=RecordedComputeLease::Capture(a.Get());RecordedComputeLease::Detach(old);old.reset();RecordedComputeLease::Poll();
 need(RecordedComputeLease::GetRegistry().submissions.empty(),"every completed resubmission retires independently");
 resetRegistry();previous.reset();ordinals.clear();published=legacy=0;
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,[&](auto*){++legacy;},callbacks),"duplicate list batch recording");
 ID3D12CommandList* duplicate[]{a.Get(),a.Get()};const auto duplicateExecutions=qa->executions;batch(qa.Get(),2,duplicate);
 need(ordinals==std::vector<uint64_t>{1,2} && legacy==2 && published==2 && qa->executions==duplicateExecutions+1,"each occurrence has its own ordinal, one original batch Execute and unchanged per-occurrence callbacks");
 need(RecordedComputeLease::GetRegistry().submissions.size()==1 && RecordedComputeLease::GetRegistry().submissions.front()->leases.size()==2,"duplicate batch shares completion fence while retaining both occurrences");
 resetRegistry();previous.reset();ordinals.clear();
 // Persistent failure must return before a gate completed by this same CPU thread.
 qa->completeSignal=false;previous.reset();ordinals.clear();
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},callbacks),"fresh recording generation");execute(qa.Get(),a.Get());
 auto pending=previous;qb->failWait=true;const auto failedAttempts=qb->waitAttempts;
 const auto waitResult=RecordedComputeLease::WaitForFence(qb.Get(),pending);
 need(FAILED(waitResult) && pending->fence->GetCompletedValue()==0 && qb->waitAttempts==failedAttempts+3 && !RecordedComputeLease::Available(),"persistent failed GPU Wait returns without CPU polling, with bounded retries and future denial");
 pending->fence->Signal(1);need(pending->fence->GetCompletedValue()==1,"same CPU thread can open the producer gate after failed wait returns");
 pending->fence->Signal(UINT64_MAX);need(RecordedComputeLease::WaitForFence(qb.Get(),pending)==DXGI_ERROR_DEVICE_REMOVED,"failed wait detects removed-device fence sentinel without spinning");
 resetRegistry();previous.reset();qa->completeSignal=true;qb->failWait=false;published=failed=legacy=0;ordinals.clear();
 callbacks.beforeSubmit=[&](const auto&){need(registryFree(),"before false unlocked");return false;};
 callbacks.failed=[&](const auto&,auto stage){need(stage==RecordedComputeLease::SubmissionFailure::Prepare,"prepare failure stage");++failed;};
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,[&](auto*){++legacy;},callbacks),"prepare rejection recording");const auto executionsBefore=qa->executions;execute(qa.Get(),a.Get());
 need(qa->executions==executionsBefore+1 && legacy==1 && published==0 && failed==1 && !RecordedComputeLease::Available(),"prepare false preserves exactly one original execute and prevents publication");
 resetRegistry();failed=published=0;callbacks.beforeSubmit={};callbacks.failed=[&](const auto&,auto stage){need(stage==RecordedComputeLease::SubmissionFailure::FenceCreate,"fence creation failure stage");++failed;};
 device->failFence=true;need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},callbacks),"fence failure recording");execute(qa.Get(),a.Get());
 need(failed==1 && published==0 && !RecordedComputeLease::Available(),"fence creation failure pins intent and denies work");
 resetRegistry();device->failFence=false;failed=0;callbacks.failed=[&](const auto&,auto stage){need(stage==RecordedComputeLease::SubmissionFailure::Signal,"signal failure stage");++failed;};qa->failSignal=true;
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},callbacks),"signal failure recording");execute(qa.Get(),a.Get());
 need(failed==1 && !RecordedComputeLease::GetRegistry().submissions.front()->signalPublished,"uncertain signal never publishes or retires intent");
 resetRegistry();qa->failSignal=false;failed=0;callbacks.failed=[&](const auto&,auto stage){need(stage==RecordedComputeLease::SubmissionFailure::Publish,"publication failure stage");++failed;};callbacks.fencePublished=[](const auto&,const auto&){throw 1;};
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},callbacks),"publication failure recording");execute(qa.Get(),a.Get());
 need(failed==1 && !RecordedComputeLease::Available(),"consumer publication exception latches future denial");
 // A snapshot allocation failure must still run the actual wrapped-list wait, without allocating.
 resetRegistry();failed=legacy=0;bool fallback=false;callbacks.fencePublished={};
 callbacks.beforeSubmit=[&](const auto& info){fallback=info.snapshotFallback;event("RequiredWait");return true;};
 callbacks.failed=[&](const auto& info,auto stage){need(info.snapshotFallback && stage==RecordedComputeLease::SubmissionFailure::Snapshot,"OOM failure event follows ordering fallback");++failed;};
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,[&](auto*){++legacy;},callbacks),"OOM recording");ComPtr<ProxyList> proxy;proxy.Attach(new ProxyList(a.Get()));
 const auto deniedBefore=deniedAllocations.load();denyAllocations=true;execute(qb.Get(),proxy.Get());denyAllocations=false;
 need(fallback && legacy==1 && failed==1,"OOM fallback resolves real proxy identity and runs callbacks once");
 need(deniedAllocations.load()==deniedBefore+1,"fallback itself performs no allocation after rejected snapshot allocation");
 need(std::string(events[0])=="RequiredWait" && std::string(events[1])=="Execute","OOM required ordering precedes original execute once");
 auto pinned=RecordedComputeLease::Capture(a.Get());RecordedComputeLease::Detach(pinned);need(RecordedComputeLease::Capture(a.Get())==pinned,"unknown OOM completion remains pinned through Reset");
 // Fail every allocation boundary in a multi-list snapshot, including after the first list was copied.
 resetRegistry();unsigned beforeCalls=0,legacyCalls=0,failureCalls=0;uint64_t fallbackOrdinal=0;
 RecordedComputeLease::SubmissionCallbacks partial;
 partial.beforeSubmit=[&,large=std::array<uint64_t,8>{}](const auto& info){++beforeCalls;fallbackOrdinal=info.recordingSubmission;need(registryFree(),"partial snapshot ordering callback unlocked");return true;};
 partial.failed=[&,large=std::array<uint64_t,8>{}](const auto& info,auto stage){++failureCalls;need(info.snapshotFallback && stage==RecordedComputeLease::SubmissionFailure::Snapshot,"partial snapshot fails only after allocation-free ordering");};
 const auto preparePartial=[&]{need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,[&](auto*){++legacyCalls;},partial),"partial snapshot first recording");need(RecordedComputeLease::Track(b.Get(),{b.Get()},lease,[&](auto*){++legacyCalls;},partial),"partial snapshot second recording");};
 preparePartial();ID3D12CommandList* pair[]{a.Get(),b.Get()};allocationBudget=100;auto counted=ResTrack_Dx12::BeforeComputeSubmission(qb.Get(),2,pair);const unsigned snapshotAllocations=100-allocationBudget.load();allocationBudget=-1;
 need(counted && snapshotAllocations>5 && beforeCalls==2,"count actual multi-list snapshot allocation boundaries");qb->ExecuteCommandLists(2,pair);RecordedComputeLease::AfterSubmission(counted);counted.reset();
 unsigned partialFailures=0;for(unsigned allowed=0;allowed<snapshotAllocations;++allowed){resetRegistry();beforeCalls=legacyCalls=failureCalls=0;preparePartial();const auto executeCount=qb->executions;const auto denies=deniedAllocations.load();allocationBudget=allowed;auto intent=ResTrack_Dx12::BeforeComputeSubmission(qb.Get(),2,pair);allocationBudget=-1;qb->ExecuteCommandLists(2,pair);RecordedComputeLease::AfterSubmission(intent);
  need(!intent && beforeCalls==2 && legacyCalls==2 && failureCalls==2 && fallbackOrdinal==1,"partial OOM runs both required preparations once without committing a partial ordinal");
  need(deniedAllocations.load()==denies+1 && qb->executions==executeCount+1 && !RecordedComputeLease::Available(),"partial OOM fallback allocates nothing and preserves exactly one original batch execute");++partialFailures;}
 // A canonical-QI failure still has an exact known alias; unknown aliases cannot invent dependencies.
 resetRegistry();beforeCalls=failureCalls=0;partial.beforeSubmit=[&](const auto&){++beforeCalls;return true;};partial.failed={};
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},partial),"known alias failure recording");a->failIdentity=true;execute(qb.Get(),a.Get());a->failIdentity=false;
 need(beforeCalls==1 && !RecordedComputeLease::Available(),"known exact alias runs necessary preparation despite canonical-QI failure");
 resetRegistry();beforeCalls=0;need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},partial),"unknown alias failure recording");proxy->failIdentity=true;const auto unknownExecute=qb->executions;execute(qb.Get(),proxy.Get());proxy->failIdentity=false;
 need(beforeCalls==0 && qb->executions==unknownExecute+1 && !RecordedComputeLease::Available() && RecordedComputeLease::GetRegistry().submissions.empty(),"catastrophic unknown identity executes original once, pins and makes no false ordering claim");
 // A throwing callback does not skip another callback's mandatory ordering or the original title batch.
 resetRegistry();unsigned ordered=0,rejections=0;RecordedComputeLease::SubmissionCallbacks throwing,following;
 throwing.beforeSubmit=[](const auto&)->bool{throw 1;};throwing.failed=[&](const auto&,auto reason){need(reason==RecordedComputeLease::SubmissionFailure::Prepare,"throwing prepare stage");++rejections;};
 following.beforeSubmit=[&](const auto&){++ordered;return true;};following.failed=throwing.failed;
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},throwing) && RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},following),"multiple necessary preparations recording");const auto throwExecute=qa->executions;execute(qa.Get(),a.Get());
 need(ordered==1 && rejections==2 && qa->executions==throwExecute+1,"prepare exception still runs following ordering and one original execute");
 resetRegistry();RecordedComputeLease::FencePointPtr lightweight;auto isolated=std::make_shared<int>(7);std::weak_ptr<int> weakOwner=isolated;RecordedComputeLease::SubmissionCallbacks ownerCallbacks;ownerCallbacks.fencePublished=[&](const auto&,const auto& point){lightweight=point;};
 need(RecordedComputeLease::Track(a.Get(),{a.Get()},isolated,{},ownerCallbacks),"lightweight published fence owner recording");execute(qa.Get(),a.Get());detach(a.Get());isolated.reset();RecordedComputeLease::Poll();
 need(lightweight && lightweight->IsPublished() && weakOwner.expired(),"published fence point has no recording, lease or callback ownership cycle");
 // Required ordering is separate from an ordinary private-prepare rejection.
 RecordedComputeLease::FencePointPtr retryPoint;unsigned retryPublished=0,orderingFailures=0;
 RecordedComputeLease::SubmissionCallbacks retryProducer,retryConsumer;
 retryProducer.fencePublished=[&](const auto&,const auto& point){retryPoint=point;++retryPublished;};
 retryConsumer.beforeSubmit=[&](const auto& event){return SUCCEEDED(RecordedComputeLease::WaitForFence(event.queue,retryPoint));};
 retryConsumer.fencePublished=[&](const auto&,const auto&){++retryPublished;};
 retryConsumer.failed=[&](const auto&,auto stage){need(stage==RecordedComputeLease::SubmissionFailure::Ordering,"unrepaired GPU ordering has its own failure stage");++orderingFailures;};
 const auto startRetryProducer=[&]{resetRegistry();retryPoint.reset();retryPublished=orderingFailures=0;qa->completeSignal=false;qb->failWait=false;qb->failNextWaits=0;need(RecordedComputeLease::Track(a.Get(),{a.Get()},lease,{},retryProducer),"retry producer recorded");execute(qa.Get(),a.Get());need(retryPoint && retryPoint->fence->GetCompletedValue()==0,"retry predecessor is published but unfinished");};
 startRetryProducer();need(RecordedComputeLease::Track(b.Get(),{b.Get()},lease,{},retryConsumer),"transient retry consumer recorded");qb->failNextWaits=2;const auto transientWaits=qb->waitAttempts,transientExecutions=qb->executions;auto transientDecision=execute(qb.Get(),b.Get());
 need(transientDecision.allowed && qb->waitAttempts==transientWaits+3 && qb->executions==transientExecutions+1 && retryPublished==2 && !orderingFailures && RecordedComputeLease::Available(),"two transient failures recover by actual third GPU Wait, with one allowed original Execute and no denial");
 retryPoint->fence->Signal(1);
 startRetryProducer();need(RecordedComputeLease::Track(b.Get(),{b.Get()},lease,{},retryConsumer),"permanent failure consumer recorded");qb->failWait=true;const auto deniedWaits=qb->waitAttempts,deniedExecutions=qb->executions;auto deniedDecision=execute(qb.Get(),b.Get());
 need(!deniedDecision.allowed && deniedDecision.orderingFailure==E_OUTOFMEMORY && qb->waitAttempts==deniedWaits+3 && qb->executions==deniedExecutions && orderingFailures==1 && retryPublished==1,"persistent unfinished GPU ordering denies original Execute and preserves restart HRESULT");
 need(retryPoint->fence->GetCompletedValue()==0 && !RecordedComputeLease::Available(),"permanent failure returns while same-thread producer gate is still closed");retryPoint->fence->Signal(1);
 auto deniedRecord=RecordedComputeLease::Capture(b.Get());RecordedComputeLease::Detach(deniedRecord);need(RecordedComputeLease::Capture(b.Get())==deniedRecord,"denied unsubmitted recording remains pinned");
 const auto deniedIntent=RecordedComputeLease::GetRegistry().submissions.back();need(!deniedIntent->decision.allowed && !deniedIntent->signalPublished,"denied intent cannot publish a completion fence");RecordedComputeLease::AfterSubmission(deniedIntent);need(!deniedIntent->fence,"After refuses a denied intent even if a caller incorrectly invokes it");
 startRetryProducer();retryConsumer.beforeSubmit=[&](const auto& event){RecordedComputeLease::WaitForFence(event.queue,retryPoint);return true;};need(RecordedComputeLease::Track(b.Get(),{b.Get()},lease,{},retryConsumer),"ignored wait-result consumer recorded");qb->failWait=true;const auto ignoredExecute=qb->executions;auto ignoredDecision=execute(qb.Get(),b.Get());need(!ignoredDecision.allowed && qb->executions==ignoredExecute,"scoped denial cannot be swallowed by a callback returning true");retryPoint->fence->Signal(1);
 startRetryProducer();retryPoint->fence->Signal(1);retryConsumer.beforeSubmit=[&](const auto& event){return SUCCEEDED(RecordedComputeLease::WaitForFence(event.queue,retryPoint));};need(RecordedComputeLease::Track(b.Get(),{b.Get()},lease,{},retryConsumer),"already completed predecessor consumer recorded");qb->failWait=true;const auto completedWaits=qb->waitAttempts,completedExecute=qb->executions;auto completeDecision=execute(qb.Get(),b.Get());need(completeDecision.allowed && qb->waitAttempts==completedWaits+1 && qb->executions==completedExecute+1 && RecordedComputeLease::Available(),"actual predecessor completion permits safe execution despite failed redundant Wait");
 // Under OOM a null intent still reports an allocation-free denial to the real resolver caller.
 startRetryProducer();need(RecordedComputeLease::Track(b.Get(),{b.Get()},lease,{},retryConsumer),"OOM ordering consumer recorded");qb->failWait=true;const auto oomDeniedExecute=qb->executions,oomDeniedAttempts=deniedAllocations.load();denyAllocations=true;auto oomDecision=execute(qb.Get(),b.Get());denyAllocations=false;
 need(!oomDecision.allowed && oomDecision.orderingFailure==E_OUTOFMEMORY && qb->executions==oomDeniedExecute && orderingFailures==1 && deniedAllocations.load()==oomDeniedAttempts+1,"null OOM intent retains denial/HRESULT and never calls original Execute after required Wait fails");retryPoint->fence->Signal(1);
 // The domain may deny an unrepairable predecessor without pretending a queue Wait occurred.
 startRetryProducer();retryConsumer.beforeSubmit=[&](const auto&){RecordedComputeLease::DenySubmission(E_ABORT);RecordedComputeLease::SubmissionDecision nested;RecordedComputeLease::BeforeSubmission(qb.Get(),std::vector<IUnknown*>{},&nested);need(nested.allowed,"nested independent submission has a separate decision");RecordedComputeLease::DenySubmission(E_INVALIDARG);return true;};need(RecordedComputeLease::Track(b.Get(),{b.Get()},lease,{},retryConsumer),"explicit domain denial consumer recorded");const auto explicitExecute=qb->executions;auto explicitDecision=execute(qb.Get(),b.Get());need(!explicitDecision.allowed && explicitDecision.orderingFailure==E_ABORT && qb->executions==explicitExecute,"explicit denial preserves first failure and survives nested decision scopes");retryPoint->fence->Signal(1);qa->completeSignal=true;qb->failWait=false;
 // Exercise actual selected-device eligibility rebind and actual Retain implementation.
 resetRegistry();gResourceReleaseEntry=gPsoReleaseEntry=gCommandListReleaseEntry=gComputeResetEntry=gComputeExecuteEntry=nullptr;gComputeQueueDeviceIdentity.Reset();gComputeListHooksAvailable=gComputeQueueHookAvailable=false;
 const char* reason=nullptr;need(ResTrack_Dx12::RefreshComputeHookDevice(device.Get(),&reason) && !reason,"initial native eligibility");
 ComPtr<FakeDevice> replacement;replacement.Attach(new FakeDevice);ComPtr<FakeList> replacementList;replacementList.Attach(new FakeList(replacement.Get()));
 need(ResTrack_Dx12::RefreshComputeHookDevice(replacement.Get(),&reason) && gComputeQueueDeviceIdentity.Get()==static_cast<IUnknown*>(replacement.Get()),"same native entries rebind the replacement canonical device");
 const auto coveredResourceEntry=gResourceReleaseEntry; const auto priorLeaseOwners=lease.use_count();
 gResourceReleaseEntry=nullptr; fixtureResourceHookFails=true;
 need(!ResTrack_Dx12::RetainComputeDispatch(replacement.Get(),replacementList.Get(),lease),"missing native resource Release observer rejects bridge retention after hook setup");
 need(!RecordedComputeLease::Capture(replacementList.Get()) && lease.use_count()==priorLeaseOwners,"uncovered resource observer publishes no recording and retains no payload");
 fixtureResourceHookFails=false; gResourceReleaseEntry=coveredResourceEntry;
 need(ResTrack_Dx12::RetainComputeDispatch(replacement.Get(),replacementList.Get(),lease),"actual Retain admits replacement list");
 auto supported=gComputeExecuteEntry;gComputeExecuteEntry=reinterpret_cast<PVOID>(1);
 need(!ResTrack_Dx12::RefreshComputeHookDevice(device.Get(),&reason) && reason && std::string(reason).find("queue implementation")!=std::string::npos,"unobserved implementation denies without detaching old hooks");gComputeExecuteEntry=supported;
 RecordedComputeLease::FailCompletion();need(!ResTrack_Dx12::RefreshComputeHookDevice(replacement.Get(),&reason) && std::string(reason).find("completion is uncertain")!=std::string::npos,"device recreation cannot clear unknown completion latch");
 resetRegistry();gComputeQueueDeviceIdentity.Reset();previous.reset();pending.reset();
 return {{"cpu_checks",checks},{"partial_snapshot_failure_boundaries",partialFailures},{"snapshot_allocations",snapshotAllocations},{"oom_allocation_attempts",deniedAllocations.load()-deniedBefore},{"proxy_identity_resolved",true},{"legacy_callbacks_preserved",true}};
}
'''


GPU = r'''
J gpuTests() {
 resetRegistry();ComPtr<ID3D12Debug> debug;hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));debug->EnableDebugLayer();
 ComPtr<IDXGIFactory4> factory;hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));ComPtr<IDXGIAdapter> warp;hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
 ComPtr<ID3D12Device> device;hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));ComPtr<ID3D12InfoQueue> info;hr(device.As(&info));
 ComPtr<ID3D12CommandQueue> nativeQa,nativeQb;D3D12_COMMAND_QUEUE_DESC qdesc{};hr(device->CreateCommandQueue(&qdesc,IID_PPV_ARGS(&nativeQa)));hr(device->CreateCommandQueue(&qdesc,IID_PPV_ARGS(&nativeQb)));ComPtr<ObservedQueue> qa,qb;qa.Attach(new ObservedQueue(nativeQa.Get()));qb.Attach(new ObservedQueue(nativeQb.Get()));
 std::array<ComPtr<ID3D12CommandAllocator>,2> allocators;std::array<ComPtr<ID3D12GraphicsCommandList>,2> lists;
 for(unsigned i=0;i<2;++i){hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocators[i])));hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocators[i].Get(),nullptr,IID_PPV_ARGS(&lists[i])));}
 auto buffer=[&](D3D12_HEAP_TYPE type,D3D12_RESOURCE_STATES state){ComPtr<ID3D12Resource> resource;D3D12_HEAP_PROPERTIES heap{};heap.Type=type;D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=256;desc.Height=desc.DepthOrArraySize=desc.MipLevels=desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&resource)));return resource;};
 auto upload=buffer(D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ),owned=buffer(D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COMMON),read=buffer(D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
 void* data=nullptr;hr(upload->Map(0,nullptr,&data));*static_cast<unsigned*>(data)=0x12345678;upload->Unmap(0,nullptr);
 D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;barrier.Transition={owned.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_COPY_DEST};lists[0]->ResourceBarrier(1,&barrier);lists[0]->CopyBufferRegion(owned.Get(),0,upload.Get(),0,4);barrier.Transition.StateBefore=D3D12_RESOURCE_STATE_COPY_DEST;barrier.Transition.StateAfter=D3D12_RESOURCE_STATE_COPY_SOURCE;lists[0]->ResourceBarrier(1,&barrier);hr(lists[0]->Close());
 lists[1]->CopyBufferRegion(read.Get(),0,owned.Get(),0,4);hr(lists[1]->Close());
 ComPtr<ID3D12Fence> gate;hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gate)));hr(qa->Wait(gate.Get(),1));
 RecordedComputeLease::FencePointPtr predecessor,result;unsigned published=0,waits=0;
 RecordedComputeLease::SubmissionCallbacks first;first.fencePublished=[&](const auto&,const auto& point){need(registryFree(),"real first publication outside lock");predecessor=point;++published;};
 RecordedComputeLease::SubmissionCallbacks second;second.beforeSubmit=[&](const auto& event){need(predecessor && predecessor->IsPublished(),"real predecessor published before second queue prepare");++waits;return SUCCEEDED(RecordedComputeLease::WaitForFence(event.queue,predecessor));};second.fencePublished=[&](const auto&,const auto& point){result=point;++published;};
 auto lease=std::make_shared<std::array<ComPtr<ID3D12Resource>,3>>();(*lease)[0]=owned;(*lease)[1]=upload;(*lease)[2]=read;
 need(RecordedComputeLease::Track(lists[0].Get(),{lists[0].Get()},lease,{},first),"real first recording");need(RecordedComputeLease::Track(lists[1].Get(),{lists[1].Get()},lease,{},second),"real second recording");
 execute(qa.Get(),lists[0].Get());need(predecessor && predecessor->fence->GetCompletedValue()==0,"first real queue is stalled after successful point publication");const auto waitEvent=eventCount;execute(qb.Get(),lists[1].Get());
 need(std::string(events[waitEvent])=="RealWait" && std::string(events[waitEvent+1])=="RealExecute" && std::string(events[waitEvent+2])=="RealSignal" && qb->waits==1 && qb->executions==1,"actual native queue Wait forwards before one native Execute and then Signal");Sleep(25);
 need(result && result->fence->GetCompletedValue()==0 && waits==1 && published==2,"second real queue cannot pass its required predecessor wait");
 detach(lists[0].Get());detach(lists[1].Get());lease.reset();RecordedComputeLease::Poll();need(RecordedComputeLease::GetRegistry().submissions.size()==2,"both real pending submissions retain their owners after Reset");
 hr(gate->Signal(1));const auto deadline=GetTickCount64()+30000;while(result->fence->GetCompletedValue()<1 && GetTickCount64()<deadline)Sleep(1);need(result->fence->GetCompletedValue()==1,"both independent real direct queues complete in dependency order");
 hr(read->Map(0,nullptr,&data));need(*static_cast<unsigned*>(data)==0x12345678,"second GPU consumer reads the exact first GPU producer value");read->Unmap(0,nullptr);RecordedComputeLease::Poll();need(RecordedComputeLease::GetRegistry().submissions.empty(),"both real fence-completed submissions retire");
 // Re-execute the actual closed lists while the second snapshot has no allocatable memory.
 resetRegistry();predecessor.reset();result.reset();hr(upload->Map(0,nullptr,&data));*static_cast<unsigned*>(data)=0x89abcdef;upload->Unmap(0,nullptr);
 ComPtr<ID3D12Fence> oomGate,oomDone;hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&oomGate)));hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&oomDone)));hr(qa->Wait(oomGate.Get(),1));
 bool oomFallback=false;unsigned oomFailures=0,allocationsAtFallback=0;second.beforeSubmit=[&](const auto& event){oomFallback=event.snapshotFallback;allocationsAtFallback=deniedAllocations.load();++waits;const auto result=RecordedComputeLease::WaitForFence(event.queue,predecessor);need(deniedAllocations.load()==allocationsAtFallback,"real required wait allocates nothing in fallback");return SUCCEEDED(result);};
 second.failed=[&](const auto& event,auto reason){need(event.snapshotFallback && reason==RecordedComputeLease::SubmissionFailure::Snapshot,"real OOM ordering failure event");need(deniedAllocations.load()==allocationsAtFallback,"real fallback notification allocates nothing");++oomFailures;};
 lease=std::make_shared<std::array<ComPtr<ID3D12Resource>,3>>();(*lease)[0]=owned;(*lease)[1]=upload;(*lease)[2]=read;
 need(RecordedComputeLease::Track(lists[0].Get(),{lists[0].Get()},lease,{},first) && RecordedComputeLease::Track(lists[1].Get(),{lists[1].Get()},lease,{},second),"real OOM recordings retained before snapshot failure");execute(qa.Get(),lists[0].Get());
 const auto realOomEvents=eventCount;const auto executeBeforeOom=qb->executions;const auto deniesBeforeGpu=deniedAllocations.load();denyAllocations=true;execute(qb.Get(),lists[1].Get());denyAllocations=false;hr(qb->Signal(oomDone.Get(),1));Sleep(25);
 // Poll is allocation-free; only the new Submission allocation is rejected.
 // OrderingFallback must not attempt another allocation.
 need(oomFallback && oomFailures==1 && allocationsAtFallback==deniesBeforeGpu+1 && deniedAllocations.load()==allocationsAtFallback,"real OOM denies only submission allocation, then fallback performs no allocation");
 need(std::string(events[realOomEvents])=="RealWait" && std::string(events[realOomEvents+1])=="RealExecute" && qb->executions==executeBeforeOom+1,"actual native Wait still precedes exactly one native Execute under OOM");
 need(oomDone->GetCompletedValue()==0 && predecessor->fence->GetCompletedValue()==0 && !RecordedComputeLease::Available(),"real consumer remains blocked under OOM and future bridge work is denied");
 detach(lists[0].Get());detach(lists[1].Get());need(RecordedComputeLease::Capture(lists[0].Get()) && RecordedComputeLease::Capture(lists[1].Get()),"OOM completion uncertainty pins both recordings through Reset");
 hr(oomGate->Signal(1));const auto oomDeadline=GetTickCount64()+30000;while(oomDone->GetCompletedValue()<1 && GetTickCount64()<oomDeadline)Sleep(1);need(oomDone->GetCompletedValue()==1,"real OOM work drains after the acyclic producer dependency completes");
 hr(read->Map(0,nullptr,&data));need(*static_cast<unsigned*>(data)==0x89abcdef,"OOM consumer reads exact resubmitted producer value");read->Unmap(0,nullptr);resetRegistry();lease.reset();
 // Inject HRESULT failures in the forwarding observer. The successful retry
 // still calls the real native Wait; permanently failed ordering must never
 // submit the shared consumer list, including a null-intent OOM fallback.
 unsigned deniedSubmissions=0,orderingReports=0,transientNativeRecoveries=0;unsigned lastReadValue=0x89abcdef;
 for(unsigned mode=0;mode<3;++mode){
  resetRegistry();predecessor.reset();result.reset();const unsigned value=0x01234567+mode;hr(upload->Map(0,nullptr,&data));*static_cast<unsigned*>(data)=value;upload->Unmap(0,nullptr);
  ComPtr<ID3D12Fence> retryGate,retryDone;hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&retryGate)));hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&retryDone)));hr(qa->Wait(retryGate.Get(),1));
  RecordedComputeLease::SubmissionCallbacks retryConsumer;retryConsumer.beforeSubmit=[&](const auto& event){++waits;return SUCCEEDED(RecordedComputeLease::WaitForFence(event.queue,predecessor));};retryConsumer.fencePublished=[&](const auto&,const auto& point){result=point;++published;};
  retryConsumer.failed=[&](const auto&,auto stage){need(stage==RecordedComputeLease::SubmissionFailure::Ordering,"real required ordering failure is distinct from private preparation failure");++orderingReports;};
  lease=std::make_shared<std::array<ComPtr<ID3D12Resource>,3>>();(*lease)[0]=owned;(*lease)[1]=upload;(*lease)[2]=read;
  need(RecordedComputeLease::Track(lists[0].Get(),{lists[0].Get()},lease,{},first) && RecordedComputeLease::Track(lists[1].Get(),{lists[1].Get()},lease,{},retryConsumer),"real retry recordings retained");execute(qa.Get(),lists[0].Get());
  qb->failWait=mode!=0;qb->failNextWaits=mode==0?2:0;const auto attempts=qb->waitAttempts;const auto nativeWaits=qb->waits;const auto originalExecutes=qb->executions;const auto rejectedAllocations=deniedAllocations.load();denyAllocations=mode==2;auto decision=execute(qb.Get(),lists[1].Get());denyAllocations=false;qb->failWait=false;
  need(qb->waitAttempts==attempts+3,"real forwarding observer records exactly three bounded Wait attempts");
  if(mode==0){need(decision.allowed && qb->waits==nativeWaits+1 && qb->executions==originalExecutes+1 && result && RecordedComputeLease::Available(),"two injected transient failures recover through one real native Wait and one original Execute");++transientNativeRecoveries;lastReadValue=value;}
  else{need(!decision.allowed && decision.orderingFailure==E_OUTOFMEMORY && qb->waits==nativeWaits && qb->executions==originalExecutes && !result && !RecordedComputeLease::Available(),"persistent failed ordering denies original native Execute and completion publication");++deniedSubmissions;if(mode==2)need(deniedAllocations.load()==rejectedAllocations+1,"real denied OOM path keeps permission without allocating after one rejected submission");}
  hr(qb->Signal(retryDone.Get(),1));
  if(mode){const auto beforeGateDeadline=GetTickCount64()+30000;while(retryDone->GetCompletedValue()<1 && GetTickCount64()<beforeGateDeadline)Sleep(1);need(retryDone->GetCompletedValue()==1,"denied submission returns so independent later title queue work progresses");}
  need(predecessor->fence->GetCompletedValue()==0,"same submitting CPU thread returns while producer gate remains closed");
  hr(retryGate->Signal(1));const auto retryDeadline=GetTickCount64()+30000;while((predecessor->fence->GetCompletedValue()<1 || retryDone->GetCompletedValue()<1) && GetTickCount64()<retryDeadline)Sleep(1);need(predecessor->fence->GetCompletedValue()==1 && retryDone->GetCompletedValue()==1,"same CPU thread opens gate and drains every allowed original GPU submission");
  hr(read->Map(0,nullptr,&data));need(*static_cast<unsigned*>(data)==lastReadValue,"permanently denied consumer never overwrites the last ordered GPU value");read->Unmap(0,nullptr);
  if(mode){auto retained=RecordedComputeLease::Capture(lists[1].Get());RecordedComputeLease::Detach(retained);need(RecordedComputeLease::Capture(lists[1].Get())==retained,"unrepaired ordering leaves consumer owner pinned through Reset");}
  resetRegistry();lease.reset();
 }
 need(deniedSubmissions==2 && orderingReports==2 && transientNativeRecoveries==1,"real normal and OOM denials plus transient recovery are all covered");
 // The helper probes actual native entries and Retain admits a same-entry replacement device.
 gResourceReleaseEntry=gPsoReleaseEntry=gCommandListReleaseEntry=gComputeResetEntry=gComputeExecuteEntry=nullptr;gComputeQueueDeviceIdentity.Reset();gComputeListHooksAvailable=gComputeQueueHookAvailable=false;
 const char* eligibilityReason=nullptr;need(ResTrack_Dx12::RefreshComputeHookDevice(device.Get(),&eligibilityReason) && !eligibilityReason,"real initial device helper eligibility");
 ComPtr<ID3D12Device> replacement;hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&replacement)));ComPtr<ID3D12InfoQueue> replacementInfo;hr(replacement.As(&replacementInfo));
 need(ResTrack_Dx12::RefreshComputeHookDevice(replacement.Get(),&eligibilityReason) && !eligibilityReason,"real same-entry replacement helper eligibility");
 ComPtr<ID3D12CommandAllocator> replacementAllocator;ComPtr<ID3D12GraphicsCommandList> replacementList;hr(replacement->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&replacementAllocator)));hr(replacement->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,replacementAllocator.Get(),nullptr,IID_PPV_ARGS(&replacementList)));hr(replacementList->Close());
 auto replacementLease=std::make_shared<int>(3);need(ResTrack_Dx12::RetainComputeDispatch(replacement.Get(),replacementList.Get(),replacementLease),"actual Retain admits real replacement device and list");detach(replacementList.Get());replacementLease.reset();gComputeQueueDeviceIdentity.Reset();
 unsigned errors=0,warnings=0;for(auto* messages:{info.Get(),replacementInfo.Get()})for(UINT64 i=0;i<messages->GetNumStoredMessages();++i){SIZE_T size=0;messages->GetMessage(i,nullptr,&size);std::vector<unsigned char> bytes(size);auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());messages->GetMessage(i,message,&size);if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)++errors;else if(message->Severity==D3D12_MESSAGE_SEVERITY_WARNING)++warnings;if(message->Severity<=D3D12_MESSAGE_SEVERITY_WARNING)std::fprintf(stderr,"D3D12 %u: %s\n",message->ID,message->pDescription);}
 need(!errors && !warnings,"real two-queue and replacement-device debug layers are clean");return {{"gpu_checks",checks},{"real_queues",2},{"published_fences",published},{"waits",waits},{"exact_gpu_value",0x12345678},{"exact_oom_gpu_value",0x89abcdef},{"real_snapshot_oom",true},{"transient_native_wait_recoveries",transientNativeRecoveries},{"denied_required_ordering_submissions",deniedSubmissions},{"same_thread_gate_progress",true},{"same_entry_native_device_replacement",true},{"debug_errors",errors},{"debug_warnings",warnings}};
}
int main(int argc,char** argv) try {
 need(!NrdBridgeNativeBirth::Ready(),"lease/eligibility fixture includes the actual unconfigured native-birth facade");
 const bool gpu=argc>1 && std::string(argv[1])=="gpu";auto result=gpu?gpuTests():cpuTests();
 need(!unexpectedNativeCoverage && !unexpectedMetadataFailure,"inactive native-birth/installer route was never fabricated or entered");
 result[gpu?"gpu_checks":"cpu_checks"]=checks;result["native_birth_ready"]=NrdBridgeNativeBirth::Ready();
 result["unexpected_native_coverage_calls"]=unexpectedNativeCoverage.load();result["unexpected_metadata_failure_calls"]=unexpectedMetadataFailure.load();
 std::cout<<result.dump()<<'\n';return 0;
} catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
'''


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/12f-audit/tests/recorded_submission'))
    output.mkdir(parents=True, exist_ok=True)
    env = _toolchain_environment(visual_studio())
    sdk = next((Path(path) / 'd3d12.h' for path in env['INCLUDE'].split(';') if (Path(path) / 'd3d12.h').is_file())).read_text()
    source = (ROOT / 'OptiScaler/resource_tracking/ResTrack_dx12.cpp').read_text()
    production = '\n'.join(function(source, signature) for signature in (
        'static bool RequiredComputeSubmissionAllowed(',
        'std::shared_ptr<RecordedComputeLease::Submission> ResTrack_Dx12::BeforeComputeSubmission(',
        'bool ResTrack_Dx12::RefreshComputeHookDevice(', 'bool ResTrack_Dx12::RetainComputeDispatch('))
    survey = (ROOT / 'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_text()
    scope_signatures = ('ScopedInternal::ScopedInternal(', 'ScopedInternal::~ScopedInternal(',
                        'ScopedRecording::ScopedRecording(', 'ScopedRecording::~ScopedRecording(',
                        'bool OwnedRelease(', 'bool Internal(')
    scopes = '\n'.join(function(survey, signature) for signature in scope_signatures)
    cpp = PREAMBLE.replace('__LEDGER__', (ROOT / 'OptiScaler/misc/RecordedComputeLease_Dx12.h').as_posix()).replace('__NATIVE_BIRTH__', (ROOT / 'OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h').as_posix()).replace('__PRODUCTION__', production)
    cpp = cpp.replace('__SURVEY_HEADER__', (ROOT / 'OptiScaler/resource_tracking/FrameSurvey_Dx12.h').as_posix()).replace('__SURVEY_SCOPES__', scopes)
    cpp += fake_com(sdk) + CPU + GPU
    path = output / 'recorded_submission.cpp'
    path.write_text(cpp)
    exe = output / 'recorded_submission.exe'
    os.environ['FSRD_CPP_CACHE'] = str(output / 'cache')
    compile_cpp(path, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'bcrypt.lib'), (ROOT / 'external/nlohmann',))
    mode = 'gpu' if '--gpu' in sys.argv else 'cpu'
    result = subprocess.run([str(exe), mode], capture_output=True, text=True, timeout=45)
    (output / 'native.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Native submission fixture failed ({result.returncode}): {result.stdout} {result.stderr}')
    values = json.loads(result.stdout)
    values['scope'] = 'production ledger, actual identity resolver/Retain/refresh extraction; fake COM CPU, real WARP two-queue GPU with forwarding queue observers; application hook bootstrap adapters'
    (output / 'result.json').write_text(json.dumps(values, indent=2) + '\n')
    print(json.dumps(values, indent=2))


if __name__ == '__main__':
    run()
