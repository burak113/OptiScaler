"""Ready=true regression for retaining a title command list inside an internal injection.

RetainComputeDispatch, ObserveBridgeObjectRelease, the Release-entry lookup and
FrameSurvey scope definitions are extracted verbatim from production.  The real
Birth/native-GUID/lifetime/lease headers run against WARP command lists.  A second
COM fixture forwards native identity data, GetDevice, Close and Reset while giving
IUnknown a distinct address.  Hook installation and retirement effects are
explicit adapters: this does not prove physical Detours patching or game startup.

The immutable 81420385 Retain body is an optional negative control.  It must fail
the SAME positive internal-retain assertion, not merely return any nonzero code.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp, visual_studio, _toolchain_environment
from test_recorded_compute_submission import methods

ROOT = Path(__file__).resolve().parents[4]
OLD = '814203852469c336b90845ed160d0f65936af653'
RESTRACK = 'OptiScaler/resource_tracking/ResTrack_dx12.cpp'
REGRESSION = 'INTERNAL_RETAIN_REGRESSION: eligible title recording is retained inside ScopedInternal'


def definition(source, signature):
    """Skip forward declarations/default arguments before balancing the real body."""
    search = 0
    while True:
        start = source.index(signature, search)
        opening = source.index('(', start)
        depth, end = 1, opening + 1
        while depth:
            depth += (source[end] == '(') - (source[end] == ')')
            end += 1
        brace = source.index('{', end)
        declaration = source.find(';', end, brace)
        if declaration == -1:
            break
        search = declaration + 1
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def extracted(use_old=False):
    source = (ROOT / RESTRACK).read_text(encoding='utf-8')
    old_source = subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{OLD}:{RESTRACK}']).decode('utf-8')
    retain_signature = 'bool ResTrack_Dx12::RetainComputeDispatch('
    old = definition(old_source, retain_signature)
    current = definition(source, retain_signature)
    addition = ('        // This explicit title list already passed device/type/hook eligibility.\n'
                '        // Keep helper work internal, but admit its native recording identity even\n'
                '        // when the caller is inside ScopedInternal. Never broaden owned creation.\n'
                '        FrameSurvey::ScopedRecording titleRecording;\n')
    if current.replace(addition, '', 1) != old:
        raise AssertionError('Current Retain differs from the immutable old body beyond the reviewed four lines')
    survey = (ROOT / 'OptiScaler/resource_tracking/FrameSurvey_Dx12.cpp').read_text(encoding='utf-8')
    tls = '\n'.join(re.search(r'^' + re.escape(prefix) + r'.*$', survey, re.M).group(0)
                    for prefix in ('thread_local bool gInternal =', 'thread_local unsigned gRecordingDepth ='))
    scopes = '\n'.join(definition(survey, signature) for signature in (
        'ScopedInternal::ScopedInternal()', 'ScopedInternal::~ScopedInternal()',
        'ScopedRecording::ScopedRecording()', 'ScopedRecording::~ScopedRecording()',
        'bool OwnedRelease()', 'bool Internal()'))
    bodies = {
        'RetainComputeDispatch': old if use_old else current,
        'ObserveBridgeObjectRelease': definition(source, 'bool ResTrack_Dx12::ObserveBridgeObjectRelease('),
        'FindBirthReleaseOriginal': definition(source, 'static PFN_BirthRelease FindBirthReleaseOriginal('),
        'FrameSurvey_scope_definitions': tls + '\n' + scopes,
    }
    return bodies, hashlib.sha256(old.encode()).hexdigest()


CPP = r'''
#define NOMINMAX
#define FSRD_RECORDED_COMPUTE_LEASE_TEST
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <json.hpp>
#include "__ROOT__/OptiScaler/resource_tracking/FrameSurvey_Dx12.h"
#include "__ROOT__/OptiScaler/misc/RecordedComputeLease_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
using Microsoft::WRL::ComPtr;
using J = nlohmann::json;
static std::atomic<unsigned> checks=0, metadataFailures=0, scopeViolations=0;
static const char* stage="initialization";
void need(bool ok,const char* message) {
 ++checks;
 if(!ok) {std::fprintf(stderr,"FAIL [%s] %s\n",stage,message);std::fflush(stderr);throw std::runtime_error(message);}
}
void hr(HRESULT result,const char* where) {if(FAILED(result)){std::fprintf(stderr,"HRESULT %s: 0x%08lx\n",where,static_cast<unsigned long>(result));std::fflush(stderr);}need(SUCCEEDED(result),where);}
namespace FrameSurvey {
__SCOPES__
void MetadataHookFailed(const char* message) noexcept {++metadataFailures;std::fprintf(stderr,"METADATA FAILURE: %s\n",message);std::fflush(stderr);}
void FlushMetadataFailure() noexcept {}
}
struct State {bool isShuttingDown=false;static State& Instance(){static State value;return value;}};
using PFN_BirthRelease=ULONG(STDMETHODCALLTYPE*)(IUnknown*);
PVOID gResourceReleaseEntry=nullptr,gHeapReleaseEntry=nullptr,gPsoReleaseEntry=nullptr,gCommandListReleaseEntry=nullptr,gComputeResetEntry=nullptr;
PFN_BirthRelease o_Release=nullptr,o_HeapRelease=nullptr,o_PsoRelease=nullptr,o_CommandListRelease=nullptr;
ComPtr<IUnknown> gComputeQueueDeviceIdentity;
std::mutex gComputeHookInitMutex,gReleaseHookInstallMutex;
bool gNrdBridgeWrappers=true;
struct BirthReleaseEntry {std::atomic<PVOID> entry{nullptr};PFN_BirthRelease original=nullptr;};
static constexpr size_t MaxBirthReleaseEntries=16;
static std::array<BirthReleaseEntry,MaxBirthReleaseEntries> gBirthReleaseEntries;
static size_t gBirthReleaseEntriesUsed=0;
static ULONG STDMETHODCALLTYPE detourAdapter(IUnknown*) {return 0;}
static const auto gBirthReleaseHooks=[] {std::array<PFN_BirthRelease,MaxBirthReleaseEntries> values{};values.fill(detourAdapter);return values;}();
static unsigned installs=0, hookBootstrapCalls=0;
static bool watchInternal=false;
static void watchScope() noexcept {if(watchInternal&&!FrameSurvey::Internal())++scopeViolations;if(NrdBridgeBirth::InMetadataScope())++scopeViolations;}
// Installation adapter records the actual observer's selected entry and decision;
// no executable code is patched, and no Release-return policy is synthesized.
LONG DetourTransactionBegin(){watchScope();return NO_ERROR;}
LONG DetourUpdateThread(HANDLE){watchScope();return NO_ERROR;}
LONG DetourAttach(PVOID*,PVOID){watchScope();++installs;return NO_ERROR;}
LONG DetourTransactionCommit(){watchScope();return NO_ERROR;}
LONG DetourTransactionAbort(){return NO_ERROR;}
struct ResTrack_Dx12 {
 static bool ObserveBridgeObjectRelease(IUnknown*) noexcept;
 static bool RetainComputeDispatch(ID3D12Device*,ID3D12GraphicsCommandList*,const std::shared_ptr<void>&,std::function<void(ID3D12CommandQueue*)> = {},RecordedComputeLease::SubmissionCallbacks = {});
 static bool CheckForRealObject(const std::string,IUnknown*,IUnknown**){return false;}
 // Host supplies actual vtable entry witnesses; bootstrap does not patch or
 // silently repair a deliberately rejected device/list/queue hook state.
 static void HookResource(ID3D12Device*){watchScope();++hookBootstrapCalls;}
 static void HookCommandList(ID3D12Device*){watchScope();++hookBootstrapCalls;}
 static void HookToQueue(ID3D12Device*){watchScope();++hookBootstrapCalls;}
};
__LOOKUP__
__OBSERVER__
bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown* object) noexcept {return ResTrack_Dx12::ObserveBridgeObjectRelease(object);}
__RETAIN__

struct RetirementPayload {unsigned detached=0;};
static std::atomic<unsigned> retiredMetadata=0, retirementDrains=0;
void* retirementFactory() noexcept {if(NrdBridgeBirth::InMetadataScope()){++scopeViolations;return nullptr;}return new(std::nothrow) RetirementPayload;}
bool retirementDetach(void* state,const NrdBridgeBirth::Token& token) noexcept {
 if(!state||!token||!NrdBridgeBirth::InMetadataAction()) {++scopeViolations;return false;}
 ++static_cast<RetirementPayload*>(state)->detached;return true;
}
void retirementNotify(void* state) noexcept {
 if(NrdBridgeBirth::InMetadataScope())++scopeViolations;
 auto* payload=static_cast<RetirementPayload*>(state);retiredMetadata+=payload->detached;++retirementDrains;delete payload;
}
bool ledgerFree(){auto& registry=RecordedComputeLease::GetRegistry();if(!registry.mutex.try_lock())return false;registry.mutex.unlock();return true;}
struct Lease {
 std::atomic<unsigned>* deaths;
 ~Lease(){if(!ledgerFree()||NrdBridgeBirth::InMetadataScope())++scopeViolations;++*deaths;}
};
struct Host {
 ComPtr<ID3D12Device> device;ComPtr<ID3D12InfoQueue> info;
 struct List {ComPtr<ID3D12CommandAllocator> allocator;ComPtr<ID3D12GraphicsCommandList> list;};
 Host(){
  ComPtr<ID3D12Debug> debug;hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)),"debug interface");debug->EnableDebugLayer();
  ComPtr<IDXGIFactory4> factory;hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)),"DXGI factory");
  ComPtr<IDXGIAdapter> adapter;hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)),"WARP adapter");
  hr(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)),"WARP device");
  hr(device.As(&info),"debug info queue");
 }
 List create(D3D12_COMMAND_LIST_TYPE type=D3D12_COMMAND_LIST_TYPE_DIRECT){List result;hr(device->CreateCommandAllocator(type,IID_PPV_ARGS(&result.allocator)),"native allocator");hr(device->CreateCommandList(0,type,result.allocator.Get(),nullptr,IID_PPV_ARGS(&result.list)),"native list");return result;}
 void witness(ID3D12GraphicsCommandList* list){
  auto table=*reinterpret_cast<PVOID**>(list);gComputeResetEntry=table[10];gCommandListReleaseEntry=table[2];o_CommandListRelease=reinterpret_cast<PFN_BirthRelease>(table[2]);
  D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
  D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=16;desc.Height=desc.DepthOrArraySize=desc.MipLevels=desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
  ComPtr<ID3D12Resource> resource;hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&resource)),"native resource entry witness");
  gResourceReleaseEntry=(*reinterpret_cast<PVOID**>(resource.Get()))[2];o_Release=reinterpret_cast<PFN_BirthRelease>(gResourceReleaseEntry);
  hr(device->QueryInterface(IID_PPV_ARGS(&gComputeQueueDeviceIdentity)),"selected native device identity");
  RecordedComputeLease::SetHooksAvailable(true,true);
 }
 J debugMessages(){unsigned errors=0,warnings=0;for(UINT64 i=0;i<info->GetNumStoredMessages();++i){SIZE_T bytes=0;hr(info->GetMessage(i,nullptr,&bytes),"debug message size");std::vector<unsigned char> storage(bytes);auto* message=reinterpret_cast<D3D12_MESSAGE*>(storage.data());hr(info->GetMessage(i,message,&bytes),"debug message");if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)++errors;else if(message->Severity==D3D12_MESSAGE_SEVERITY_WARNING)++warnings;if(message->Severity<=D3D12_MESSAGE_SEVERITY_WARNING)std::fprintf(stderr,"D3D12 #%u: %s\n",message->ID,message->pDescription);}need(!errors&&!warnings,"native WARP debug errors and warnings are zero");return {{"errors",errors},{"warnings",warnings}};}
};

// Explicit interface-forwarding adapter: a canonical IUnknown has a distinct
// This address. GUID storage, device/type and successful Reset/Close are native.
// Unused graphics methods are SDK-generated no-ops: no GPU Dispatch is tested.
struct AliasList final : ID3D12GraphicsCommandList {
 struct Canonical final:IUnknown {
  AliasList* owner;
  explicit Canonical(AliasList* value):owner(value){}
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override{return owner->QueryInterface(iid,out);}
  ULONG STDMETHODCALLTYPE AddRef() override{return owner->AddRef();}
  ULONG STDMETHODCALLTYPE Release() override{return owner->Release();}
 } canonical{this};
 ComPtr<ID3D12GraphicsCommandList> native;
 std::atomic<ULONG> refs{1};std::atomic<unsigned> gets=0,sets=0,queries=0;
 bool failIdentity=false,failDevice=false,failReset=false;
 explicit AliasList(ID3D12GraphicsCommandList* value):native(value){}
 HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override {
  watchScope();++queries;*out=nullptr;
  if(iid==IID_IUnknown){if(failIdentity)return E_NOINTERFACE;*out=&canonical;}
  else if(iid==__uuidof(ID3D12Object)||iid==__uuidof(ID3D12DeviceChild)||iid==__uuidof(ID3D12CommandList)||iid==__uuidof(ID3D12GraphicsCommandList))*out=static_cast<ID3D12GraphicsCommandList*>(this);
  else return E_NOINTERFACE;
  AddRef();return S_OK;
 }
 ULONG STDMETHODCALLTYPE AddRef() override{watchScope();return ++refs;}
 ULONG STDMETHODCALLTYPE Release() override{watchScope();auto value=--refs;if(!value)delete this;return value;}
 HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID guid,UINT* size,void* data) override{watchScope();++gets;return native->GetPrivateData(guid,size,data);}
 HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid,UINT size,const void* data) override{watchScope();++sets;return native->SetPrivateData(guid,size,data);}
 HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID guid,const IUnknown* data) override{watchScope();return native->SetPrivateDataInterface(guid,data);}
 HRESULT STDMETHODCALLTYPE SetName(LPCWSTR name) override{return native->SetName(name);}
 HRESULT STDMETHODCALLTYPE GetDevice(REFIID iid,void** out) override{watchScope();if(failDevice){*out=nullptr;return E_FAIL;}return native->GetDevice(iid,out);}
 D3D12_COMMAND_LIST_TYPE STDMETHODCALLTYPE GetType() override{watchScope();return native->GetType();}
__GRAPHICS_METHODS__
};

NrdBridgeBirth::Token seedUnverified(AliasList* list){
 const auto stamp=NrdBridgeBirth::AllocateInstanceStamp();need(stamp!=0,"cold test native instance stamp allocated");
 NrdBridgeNativeBirth::NativeStamp bytes{NrdBridgeNativeBirth::Detail::ProcessNonce(),stamp};
 hr(list->SetPrivateData(NrdBridgeNativeBirth::InstanceGuid,sizeof(bytes),&bytes),"creator writes actual native GUID without Receiver cache");
 NrdBridgeNativeBirth::RetirementScope retirement;need(retirement.Valid(),"cold metadata publication has real retirement payload");
 auto canonical=NrdBridgeBirth::ObserveInstance(&list->canonical,stamp);auto typed=NrdBridgeBirth::ObserveInstance(list,stamp);
 need(canonical&&typed&&typed->CacheAdmissible()&&!typed->NativeReceiverVerified(),"metadata-only typed alias is live but has no completed native Receiver proof");
 need(canonical->InstanceStamp()==typed->InstanceStamp(),"creator GUID gives both exact aliases one physical instance");return typed;
}
void assertIdentity(ID3D12GraphicsCommandList* list,const NrdBridgeBirth::Token& expected){
 ComPtr<IUnknown> canonical;hr(list->QueryInterface(IID_PPV_ARGS(&canonical)),"canonical query after retention");
 auto typed=NrdBridgeBirth::Capture(list),identity=NrdBridgeBirth::Capture(canonical.Get());
 need(typed&&identity&&typed->InstanceStamp()==identity->InstanceStamp()&&typed->InstanceStamp()==expected->InstanceStamp(),"typed and canonical aliases match exact native GUID instance");
 need(typed->RecordingMayExist()&&identity->RecordingMayExist(),"recording marker is shared across physical aliases");
 {NrdBridgeBirth::CurrentGuard current(typed);need(current.AdmitsBorrow(),"typed native birth is current after Retain");}
 {NrdBridgeBirth::CurrentGuard current(identity);need(current.AdmitsBorrow(),"canonical native birth is current after Retain");}
 auto a=RecordedComputeLease::Capture(list),b=RecordedComputeLease::Capture(canonical.Get());
 need(a&&a==b&&a->identity==canonical.Get(),"actual ledger uses canonical identity and both typed aliases");
}
bool retainInternal(Host& host,ID3D12GraphicsCommandList* list,const std::shared_ptr<void>& lease){
 NrdBridgeLifetime::ScopedBorrow borrow;need(borrow.Acquired(),"exclusive lifetime borrow acquired with concurrent releases enabled");
 const auto priorRecordingDepth=FrameSurvey::gRecordingDepth;
 FrameSurvey::ScopedInternal internal;
 need(FrameSurvey::Internal()&&FrameSurvey::OwnedRelease()==(priorRecordingDepth==0),"outer injection preserves its exact caller recording/owned-release policy");
 watchInternal=true;const bool result=ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),list,lease);watchInternal=false;
 need(FrameSurvey::Internal()&&FrameSurvey::OwnedRelease()==(priorRecordingDepth==0),"Retain restores caller's internal owned-release policy before returning");
 need(FrameSurvey::gRecordingDepth==priorRecordingDepth,"temporary title recording depth is balanced at Retain return");
 return result;
}
// Exact Reset ledger ordering is a fixture adapter: capture before real Reset,
// detach only on success. The wider inspector/FrameSurvey Reset hook is not linked.
HRESULT resetRecording(ID3D12GraphicsCommandList* list,ID3D12CommandAllocator* allocator){auto before=RecordedComputeLease::Capture(list);const auto result=list->Reset(allocator,nullptr);if(SUCCEEDED(result))RecordedComputeLease::Detach(before);return result;}
ULONG finalRelease(ID3D12GraphicsCommandList* object){
 auto token=NrdBridgeBirth::Capture(object);need(bool(token),"final Release has exact prior native token");
 NrdBridgeBirth::AliasSnapshot aliases;need(NrdBridgeBirth::CaptureProvenAliasesForFinalZero(token,aliases)&&aliases.complete,"bounded native alias snapshot captured before physical zero");
 auto recording=RecordedComputeLease::BeginRelease(object);
 NrdBridgeLifetime::ScopedRelease lifetime(true);NrdBridgeBirth::ScopedRelease release(token);
 const ULONG result=object->Release();need(result==0,"owned COM identity actually reaches final Release zero");
 {NrdBridgeNativeBirth::RetirementScope retirement;need(retirement.Valid(),"physical-zero effects have an outside-lock payload");const auto actions=NrdBridgeBirth::ProcessRegistry().Actions();const auto count=NrdBridgeBirth::ProcessRegistry().RetireProvenAliases(aliases,actions.detachOld,actions.state);need(count==aliases.count,"actual Birth retirement removes every proven alias");}
 RecordedComputeLease::EndRelease(recording,true);recording.reset();
 for(size_t i=0;i<aliases.count;++i)need(!NrdBridgeBirth::Capture(aliases.tokens[i]->Address()),"no retired alias remains current after physical zero");
 return result;
}

J run(){
 stage="bootstrap";Host host;RecordedComputeLease::ResetRegistryForTesting();
 need(NrdBridgeNativeBirth::ConfigureRetirement(retirementFactory,retirementDetach,retirementNotify),"actual native retirement dispatcher configured");
 need(NrdBridgeNativeBirth::Ready(),"actual NativeBirth Ready is true");
 need(NrdBridgeLifetime::EnableConcurrentReleases()&&NrdBridgeLifetime::ConcurrentReleasesEnabled(),"actual concurrent Release lifetime mode enabled before Borrow");
 need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"initial FrameSurvey scope policy is external");
 auto direct=host.create();host.witness(direct.list.Get());
 auto nativeBirth=NrdBridgeNativeBirth::Prepare(direct.list.Get());need(nativeBirth&&nativeBirth->CacheAdmissible()&&nativeBirth->NativeReceiverVerified(),"native WARP command list has a completed GUID proof");
 std::atomic<unsigned> directDeaths=0;auto directLease=std::make_shared<Lease>();directLease->deaths=&directDeaths;std::weak_ptr<Lease> directWeak=directLease;
 stage="regression.internal-retain";
 const bool retained=retainInternal(host,direct.list.Get(),directLease);
 need(retained,"__REGRESSION__");
 need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"outer scope restoration remains external after injection");
 assertIdentity(direct.list.Get(),nativeBirth);directLease.reset();need(!directWeak.expired()&&directDeaths==0,"successful Retain keeps the strong lease after the caller's own scope ends");
 hr(direct.list->Close(),"close native retained list");hr(resetRecording(direct.list.Get(),direct.allocator.Get()),"successful native Reset");
 need(!RecordedComputeLease::Capture(direct.list.Get())&&directWeak.expired()&&directDeaths==1,"successful actual Reset retires unsubmitted recording and releases exactly one lease outside registry locks");
 need(nativeBirth->RecordingMayExist(),"Reset cannot clear the physical monotonic recording marker");hr(direct.list->Close(),"close reset native list");

 stage="distinct-alias.cold-receiver";
 auto native=host.create();ComPtr<AliasList> alias;alias.Attach(new AliasList(native.list.Get()));host.witness(alias.Get());
 need(static_cast<void*>(alias.Get())!=static_cast<void*>(&alias->canonical),"typed and canonical COM This addresses are genuinely distinct");
 auto cold=seedUnverified(alias.Get());const ULONG refsBefore=alias->refs;const auto getsBefore=alias->gets.load();
 std::atomic<unsigned> aliasDeaths=0;auto aliasLease=std::make_shared<Lease>();aliasLease->deaths=&aliasDeaths;std::weak_ptr<Lease> aliasWeak=aliasLease;
 need(retainInternal(host,alias.Get(),aliasLease),"cold TLS and unverified global Receiver admits the exact eligible title list inside injection");
 need(alias->gets>getsBefore,"cold Receiver actually rereads the native GUID instead of assuming metadata identity");
 need(alias->refs==refsBefore,"cold canonical QI and Release balance all temporary COM references");
 assertIdentity(alias.Get(),cold);need(NrdBridgeBirth::Capture(alias.Get())->NativeReceiverVerified(),"cold Receiver publishes completed global native proof");
 const auto warmedGets=alias->gets.load();need(retainInternal(host,alias.Get(),aliasLease),"warm TLS Receiver retains a second lease reference");
 need(alias->gets==warmedGets,"warm TLS Receiver does not reread native GUID");
 stage="distinct-alias.global-cache";std::exception_ptr threadFailure;
 std::thread freshThread([&]{try{need(retainInternal(host,alias.Get(),aliasLease),"fresh-thread TLS miss accepts globally verified exact Receiver");need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"fresh thread restores its own external scope");}catch(...){threadFailure=std::current_exception();}});freshThread.join();if(threadFailure)std::rethrow_exception(threadFailure);
 need(alias->gets==warmedGets,"global verified-cache path avoids native GUID reread on a fresh thread");
 need(alias->refs==refsBefore,"warm/global Retain paths preserve canonical COM refcount");
 stage="scope.nested-recording";
 {FrameSurvey::ScopedRecording recording;need(FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease(),"ordinary recording remains internal while preserving title Release observation");need(retainInternal(host,alias.Get(),aliasLease),"an existing ordinary recording can nest the explicit title-retention scope");need(FrameSurvey::gRecordingDepth==1&&!FrameSurvey::OwnedRelease(),"nested Retain leaves the caller's ordinary recording protection active");}
 need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease()&&FrameSurvey::gRecordingDepth==0,"all nested scopes restore external policy and zero recording depth");
 need(alias->refs==refsBefore,"all nested native QI/Release references balance");

 stage="reset.failed-success-late-token";
 auto oldRecording=RecordedComputeLease::Capture(alias.Get());need(oldRecording&&oldRecording->leases.size()==4,"all four Retain calls append strong leases to the same recording");
 aliasLease.reset();hr(alias->Close(),"close alias native list before Reset");alias->failReset=true;
 need(FAILED(resetRecording(alias.Get(),native.allocator.Get())),"explicit failed native-Reset adapter reports failure");
 need(RecordedComputeLease::Capture(alias.Get())==oldRecording&&!aliasWeak.expired(),"failed Reset preserves the exact old recording and its leases");alias->failReset=false;
 hr(resetRecording(alias.Get(),native.allocator.Get()),"successful forwarded native Reset");
 need(!RecordedComputeLease::Capture(alias.Get())&&!aliasWeak.expired(),"successful Reset detaches the registry while the caller's old token remains strong");
 std::atomic<unsigned> replacementDeaths=0;auto replacementLease=std::make_shared<Lease>();replacementLease->deaths=&replacementDeaths;std::weak_ptr<Lease> replacementWeak=replacementLease;
 need(retainInternal(host,alias.Get(),replacementLease),"post-Reset recording can retain fresh leases under injection");
 auto replacementRecording=RecordedComputeLease::Capture(alias.Get());need(replacementRecording&&replacementRecording!=oldRecording,"successful Reset creates a distinct recording generation");
 RecordedComputeLease::Detach(oldRecording);need(RecordedComputeLease::Capture(alias.Get())==replacementRecording,"late old-recording detach cannot erase the replacement generation");
 oldRecording.reset();need(aliasWeak.expired()&&aliasDeaths==1,"old recording releases its opaque lease once outside metadata and ledger locks");
 replacementLease.reset();hr(alias->Close(),"close replacement recording");hr(resetRecording(alias.Get(),native.allocator.Get()),"reset replacement recording");replacementRecording.reset();
 need(replacementWeak.expired()&&replacementDeaths==1,"replacement recording retires its own lease independently");hr(alias->Close(),"close empty alias list");

 stage="eligibility.reject-before-title-scope";
 auto rejectionNative=host.create();ComPtr<AliasList> rejected;rejected.Attach(new AliasList(rejectionNative.list.Get()));host.witness(rejected.Get());
 auto rejectedBirth=seedUnverified(rejected.Get());std::atomic<unsigned> rejectedDeaths=0;auto rejectedLease=std::make_shared<Lease>();rejectedLease->deaths=&rejectedDeaths;
 const auto beforeInstalls=installs;const auto rejectedRefs=rejected->refs.load();const auto rejectedGets=rejected->gets.load();
 auto noSideEffects=[&]{need(!RecordedComputeLease::Capture(rejected.Get())&&!rejectedBirth->RecordingMayExist(),"rejected eligibility publishes no recording or physical marker");need(installs==beforeInstalls&&rejected->gets==rejectedGets,"rejected eligibility cannot reach native coverage installation or GUID reads");need(rejected->refs==rejectedRefs,"early rejection balances canonical references");need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease()&&FrameSurvey::gRecordingDepth==0,"early rejection restores every FrameSurvey scope");};
 ComPtr<IUnknown> selectedIdentity=gComputeQueueDeviceIdentity;gComputeQueueDeviceIdentity=static_cast<IUnknown*>(&rejected->canonical);
 need(!retainInternal(host,rejected.Get(),rejectedLease),"wrong selected device identity rejects before title scope");gComputeQueueDeviceIdentity=selectedIdentity;noSideEffects();
 rejected->failDevice=true;need(!retainInternal(host,rejected.Get(),rejectedLease),"GetDevice failure rejects before title scope");noSideEffects();rejected->failDevice=false;
 auto resetEntry=gComputeResetEntry;gComputeResetEntry=nullptr;need(!retainInternal(host,rejected.Get(),rejectedLease),"missing observed Reset entry rejects before title scope");noSideEffects();gComputeResetEntry=resetEntry;
 auto resourceEntry=gResourceReleaseEntry;gResourceReleaseEntry=nullptr;need(!retainInternal(host,rejected.Get(),rejectedLease),"missing resource Release coverage rejects before title scope");noSideEffects();gResourceReleaseEntry=resourceEntry;
 RecordedComputeLease::SetHooksAvailable(false,true);need(!retainInternal(host,rejected.Get(),rejectedLease),"unavailable list hooks reject before title scope");noSideEffects();RecordedComputeLease::SetHooksAvailable(true,true);
 RecordedComputeLease::SetHooksAvailable(true,false);need(!retainInternal(host,rejected.Get(),rejectedLease),"unavailable queue hook rejects before title scope");noSideEffects();RecordedComputeLease::SetHooksAvailable(true,true);
 rejected->failIdentity=true;need(!retainInternal(host,rejected.Get(),rejectedLease),"canonical QI failure rejects before title scope");noSideEffects();rejected->failIdentity=false;
 State::Instance().isShuttingDown=true;need(!retainInternal(host,rejected.Get(),rejectedLease),"shutdown rejects before title scope");noSideEffects();State::Instance().isShuttingDown=false;
 need(!retainInternal(host,rejected.Get(),{}),"empty lease rejects before title scope");noSideEffects();
 {NrdBridgeLifetime::ScopedBorrow borrow;FrameSurvey::ScopedInternal internal;need(!ResTrack_Dx12::RetainComputeDispatch(nullptr,rejected.Get(),rejectedLease),"null device rejects before title scope");need(!ResTrack_Dx12::RetainComputeDispatch(host.device.Get(),nullptr,rejectedLease),"null command list rejects before title scope");need(FrameSurvey::OwnedRelease(),"null-input exits preserve intended owned-release suppression");}noSideEffects();
 auto bundle=host.create(D3D12_COMMAND_LIST_TYPE_BUNDLE);need(!retainInternal(host,bundle.list.Get(),rejectedLease),"real native bundle is rejected before title scope");noSideEffects();hr(bundle.list->Close(),"close rejected native bundle");hr(rejected->Close(),"close rejected native list");

 stage="owned-helper.suppression";
 auto owned=host.create();const auto ownedInstalls=installs;
 {NrdBridgeLifetime::ScopedBorrow borrow;FrameSurvey::ScopedInternal internal;
  need(FrameSurvey::OwnedRelease(),"owned helper has its original internal suppression policy");
  need(!ResTrack_Dx12::ObserveBridgeObjectRelease(owned.list.Get()),"actual Release observer still rejects an ordinary owned helper");
  need(!NrdBridgeNativeBirth::Prepare(owned.list.Get()),"actual NativeBirth bootstrap still suppresses owned helper creation");
  need(!NrdBridgeBirth::Capture(owned.list.Get()),"owned helper did not gain title metadata identity");
  need(installs==ownedInstalls&&FrameSurvey::OwnedRelease(),"owned helper suppression neither installs nor broadens title scope");
 }
 need(!ResTrack_Dx12::ObserveBridgeObjectRelease(nullptr),"actual observer rejects null even with NativeBirth Ready true");hr(owned.list->Close(),"close owned native helper");

 stage="retirement.unsubmitted-distinct-alias";
 auto retirementNative=host.create();ComPtr<AliasList> retiring;retiring.Attach(new AliasList(retirementNative.list.Get()));host.witness(retiring.Get());auto retiringBirth=seedUnverified(retiring.Get());
 std::atomic<unsigned> retiringDeaths=0;auto retiringLease=std::make_shared<Lease>();retiringLease->deaths=&retiringDeaths;std::weak_ptr<Lease> retiringWeak=retiringLease;
 need(retainInternal(host,retiring.Get(),retiringLease),"unsubmitted distinct-alias recording is retained before final zero");assertIdentity(retiring.Get(),retiringBirth);retiringLease.reset();
 auto* canonicalAddress=static_cast<void*>(&retiring->canonical);auto* typedAddress=static_cast<void*>(retiring.Get());hr(retiring->Close(),"close final-zero alias recording");
 auto* retiringRaw=retiring.Detach();need(finalRelease(retiringRaw)==0,"forwarding COM fixture reaches final zero through retirement adapter");
 need(!RecordedComputeLease::Capture(typedAddress)&&!RecordedComputeLease::Capture(canonicalAddress)&&retiringWeak.expired()&&retiringDeaths==1,"physical-zero ledger effects detach both exact aliases and free unsubmitted leases once");
 need(!retiringBirth->Live(),"retired title birth cannot admit later weak borrowing");

 stage="retirement.native-warp-zero";
 auto physical=host.create();host.witness(physical.list.Get());auto physicalBirth=NrdBridgeNativeBirth::Prepare(physical.list.Get());need(bool(physicalBirth),"actual native list has a birth before unsubmitted physical zero");
 std::atomic<unsigned> physicalDeaths=0;auto physicalLease=std::make_shared<Lease>();physicalLease->deaths=&physicalDeaths;std::weak_ptr<Lease> physicalWeak=physicalLease;
 need(retainInternal(host,physical.list.Get(),physicalLease),"actual WARP list retains unsubmitted work before physical zero");physicalLease.reset();hr(physical.list->Close(),"close physical native list");
 auto* physicalRaw=physical.list.Detach();need(finalRelease(physicalRaw)==0,"actual WARP command list reaches native final Release zero");
 need(physicalWeak.expired()&&physicalDeaths==1&&!physicalBirth->Live(),"native-zero retirement adapter retires exact birth and opaque lease");
 need(RecordedComputeLease::Available(),"Reset and unsubmitted retirement leave actual lease ledger healthy");
 {auto& registry=RecordedComputeLease::GetRegistry();std::lock_guard lock(registry.mutex);need(registry.recordings.empty()&&registry.aliases.empty()&&registry.submissions.empty(),"all unsubmitted recording and alias ledger entries are cleaned");}
 need(metadataFailures==0&&scopeViolations==0,"no metadata failure, native-under-metadata call, scope violation or owner destruction under a registry lock");
 need(!FrameSurvey::Internal()&&!FrameSurvey::OwnedRelease()&&FrameSurvey::gRecordingDepth==0,"final thread scope policy is fully restored");
 rejectedLease.reset();need(rejectedDeaths==1,"rejected call never retained its caller's lease");
 alias.Reset();rejected.Reset();native.list.Reset();rejectionNative.list.Reset();retirementNative.list.Reset();owned.list.Reset();bundle.list.Reset();direct.list.Reset();
 const auto debug=host.debugMessages();gComputeQueueDeviceIdentity.Reset();
 return {{"checks",checks.load()},{"native_birth_ready",NrdBridgeNativeBirth::Ready()},{"concurrent_releases",NrdBridgeLifetime::ConcurrentReleasesEnabled()},{"distinct_canonical_alias",true},{"warm_receiver",true},{"cold_native_receiver",true},{"global_receiver_fresh_thread",true},{"unsubmitted_native_final_zero",true},{"sdk_dispatches",0},{"gpu_submissions",0},{"debug",debug},{"metadata_failures",metadataFailures.load()},{"scope_violations",scopeViolations.load()},{"adapter_installations",installs},{"retired_metadata",retiredMetadata.load()},{"retirement_payload_drains",retirementDrains.load()},{"physical_detours_coverage_proved",false}};
}
int main() try {auto result=run();std::cout<<result.dump()<<'\n';return 0;}catch(const std::exception& e){std::fprintf(stderr,"EXCEPTION [%s] %s\n",stage,e.what());std::fflush(stderr);return 42;}
'''


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-old-failure', action='store_true')
    parser.add_argument('--source-only', action='store_true', help='verify extraction/control only; no SDK/compiler/native process')
    args = parser.parse_args()
    bodies, old_hash = extracted(args.expect_old_failure)
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/13e-e2e/tests/internal_retain'))
    output.mkdir(parents=True, exist_ok=True)
    witness = dict(old_revision=OLD, old_retain_sha256=old_hash, negative_control=args.expect_old_failure,
                   production_body_sha256={key: hashlib.sha256(value.encode()).hexdigest() for key, value in bodies.items()},
                   scope='actual Retain/observer/scope bodies + real Birth/NativeBirth/lifetime/lease headers; native WARP device/lists; distinct-IUnknown forwarding adapter; vtable bootstrap/Detours installation/Reset ordering/retirement effects adapters; no physical hook coverage, AMD or game-output claim')
    (output / 'source-witness.json').write_text(json.dumps(witness, indent=2) + '\n', encoding='utf-8')
    if args.source_only:
        print(json.dumps(witness, indent=2))
        return
    environment = _toolchain_environment(visual_studio())
    sdk = next((Path(path) / 'd3d12.h' for path in environment['INCLUDE'].split(';') if (Path(path) / 'd3d12.h').is_file())).read_text()
    graphics = methods(sdk, 'ID3D12GraphicsCommandList', {
        'Close': '{watchScope();return native->Close();}',
        'Reset': '{watchScope();if(failReset)return E_FAIL;return native->Reset(pAllocator,pInitialState);}',
    })
    generated = (CPP.replace('__ROOT__', ROOT.as_posix()).replace('__SCOPES__', bodies['FrameSurvey_scope_definitions'])
                 .replace('__LOOKUP__', bodies['FindBirthReleaseOriginal']).replace('__OBSERVER__', bodies['ObserveBridgeObjectRelease'])
                 .replace('__RETAIN__', bodies['RetainComputeDispatch']).replace('__GRAPHICS_METHODS__', graphics).replace('__REGRESSION__', REGRESSION))
    source = output / 'internal_retain.cpp'
    source.write_text(generated, encoding='utf-8')
    exe = output / 'internal_retain.exe'
    os.environ['FSRD_CPP_CACHE'] = str(output / 'cache')
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'dxguid.lib', 'bcrypt.lib'), (ROOT / 'external/nlohmann',))
    result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60, creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    native_log = output / 'native.log'
    native_log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if args.expect_old_failure:
        exact = f'FAIL [regression.internal-retain] {REGRESSION}'
        if result.returncode != 42 or exact not in result.stderr:
            raise AssertionError(f'Old-source control did not fail the original exact assertion: exit={result.returncode}; {native_log}')
        witness['old_source_failed_exact_original_assertion'] = True
    else:
        if result.returncode:
            raise RuntimeError(f'Native internal-retain fixture failed ({result.returncode}): {native_log}\n{result.stdout}{result.stderr}')
        witness['native'] = json.loads(result.stdout)
    witness.update(native_exit=result.returncode, native_log=str(native_log), generated_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    (output / 'result.json').write_text(json.dumps(witness, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(witness, indent=2))


if __name__ == '__main__':
    run()
