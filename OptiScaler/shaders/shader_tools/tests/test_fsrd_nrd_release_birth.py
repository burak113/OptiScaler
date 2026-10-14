"""Supplement the existing Release suite with the actual native-birth dispatcher.

The production Birth/NativeBirth/Lifetime/Perf headers are included unchanged.
Title/Retire and ResTrack's payload factory, pure detach, notification, dedicated
wrappers and bounded installer are extracted unchanged from current source.
Survey/HUD/RR catalogs, recorded leases, byte-data COM objects and Detours are
explicit CPU adapters. No native COM object, real detour or GPU claim is made.
Each failure runs in a fresh process because metadata health is irreversible.
--prepare-only generates source/contract without compiling or executing it.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fsrd_nrd_root_restore import function


CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include "__ROOT__/OptiScaler/misc/NrdBridgeBirth_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgeLifetime_Dx12.h"
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>
#define LOG_INFO(...) ((void)0)
using Token = NrdBridgeBirth::Token;
unsigned checks = 0;
void need(bool value, const char* message)
{ if (!value) throw std::runtime_error(message); ++checks; }

// Allocation measurement is enabled only around warmed, nonfinal Title calls.
thread_local bool meterAllocations = false;
std::atomic<unsigned> allocations = 0;
void* operator new(size_t size)
{ if (meterAllocations) ++allocations; if (auto* p = std::malloc(size ? size : 1)) return p; throw std::bad_alloc(); }
void* operator new[](size_t size) { return ::operator new(size); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }

// Catalog/installation mutex adapters retain explicit per-thread lock evidence.
thread_local unsigned catalogLocks = 0, installerLocks = 0;
thread_local bool legacyNativeAllowed = false;
struct CatalogMutex
{
    std::recursive_mutex native;
    void lock() { native.lock(); ++catalogLocks; }
    void unlock() { --catalogLocks; native.unlock(); }
    bool try_lock() { if (!native.try_lock()) return false; ++catalogLocks; return true; }
};
struct InstallerMutex
{
    std::recursive_mutex native;
    void lock() { native.lock(); ++installerLocks; }
    void unlock() { --installerLocks; native.unlock(); }
    bool try_lock() { if (!native.try_lock()) return false; ++installerLocks; return true; }
};
std::atomic<unsigned> nativeUnderMetadata = 0, factoryUnderMetadata = 0;
std::atomic<unsigned> notifyUnderMetadata = 0, destructorUnderMetadata = 0;
std::atomic<unsigned> factoryCalls = 0, detachCalls = 0, notifyCalls = 0;
std::atomic<unsigned> ownerDestructions = 0, heapDestructions = 0;
std::atomic<unsigned> metadataFailures = 0, failuresUnderInstaller = 0;
std::atomic<unsigned> pureFailureUnderBirth = 0, legacyReleased = 0;
std::atomic<unsigned> leaseBegins = 0, leaseEnds = 0, leaseFinals = 0;
std::atomic<bool> failPrepareEffects = false, failDetachEffects = false;
std::atomic<bool> surveyHealthy = true;
bool outsideMetadata() noexcept
{ return !NrdBridgeBirth::InMetadataScope() && !catalogLocks && !installerLocks; }
void noteNative() noexcept
{
    if (NrdBridgeBirth::InMetadataScope() || installerLocks ||
        (catalogLocks && !legacyNativeAllowed)) ++nativeUnderMetadata;
}
struct DetachedOwner
{
    ~DetachedOwner()
    { if (!outsideMetadata()) ++destructorUnderMetadata; ++ownerDestructions; }
};

// The physical lifetime/refcount/private bytes are explicit deterministic COM seams.
// Template Release overrides have distinct side effects so /O2 ICF cannot merge them.
std::array<std::atomic<unsigned>, 64> entryTouches {};
struct PhysicalObject
{
    std::atomic<ULONG> refs {1};
    std::mutex mutex;
    bool stamped = false;
    NrdBridgeNativeBirth::NativeStamp stamp {};
};
struct CpuObject;
thread_local CpuObject* callingObject = nullptr;
thread_local unsigned originalOrdinal = 0, nestedReleaseDepth = 0;
struct NativeCall
{ void* address = nullptr; unsigned ordinal = 0; ULONG result = 0; };
std::array<NativeCall, 32768> nativeTrace {};
std::atomic<unsigned> nativeTraceSize = 0;
struct CpuObject : IUnknown
{
    std::shared_ptr<PhysicalObject> physical = std::make_shared<PhysicalObject>();
    std::atomic<unsigned> addRefs = 0, releases = 0, zeros = 0, reads = 0, writes = 0;
    std::function<void(unsigned, ULONG)> afterRelease;
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID, void** output) override
    { noteNative(); if (output) *output = nullptr; return E_NOINTERFACE; }
    ULONG STDMETHODCALLTYPE AddRef() override
    { noteNative(); ++addRefs; return ++physical->refs; }
    ULONG STDMETHODCALLTYPE Release() override { return releaseNative(0); }
    ULONG releaseNative(unsigned tag)
    {
        noteNative(); ++entryTouches[tag]; ++releases;
        const auto allocation = physical;
        const ULONG result = --allocation->refs;
        const unsigned ordinal = callingObject == this ? ++originalOrdinal : 0;
        const unsigned index = nativeTraceSize.fetch_add(1);
        if (index < nativeTrace.size()) nativeTrace[index] = {this, ordinal, result};
        if (!result) ++zeros;
        if (afterRelease) afterRelease(ordinal, result);
        return result;
    }
    HRESULT GetPrivateData(REFGUID guid, UINT* bytes, void* output)
    {
        noteNative(); ++reads;
        if (guid != NrdBridgeNativeBirth::InstanceGuid) return E_INVALIDARG;
        std::lock_guard lock(physical->mutex);
        if (!physical->stamped) return DXGI_ERROR_NOT_FOUND;
        if (*bytes < sizeof(physical->stamp)) { *bytes = sizeof(physical->stamp); return DXGI_ERROR_MORE_DATA; }
        *bytes = sizeof(physical->stamp); std::memcpy(output, &physical->stamp, sizeof(physical->stamp));
        return S_OK;
    }
    HRESULT SetPrivateData(REFGUID guid, UINT bytes, const void* input)
    {
        noteNative(); ++writes;
        if (guid != NrdBridgeNativeBirth::InstanceGuid || bytes != sizeof(physical->stamp)) return E_INVALIDARG;
        std::lock_guard lock(physical->mutex);
        std::memcpy(&physical->stamp, input, bytes); physical->stamped = true; return S_OK;
    }
    virtual ~CpuObject() = default;
};
template<unsigned Tag> struct DistinctObject : CpuObject
{ ULONG STDMETHODCALLTYPE Release() override { return releaseNative(Tag); } };
struct CallIdentity
{
    CpuObject* previous = callingObject;
    unsigned previousOrdinal = originalOrdinal;
    explicit CallIdentity(CpuObject* object) { callingObject = object; originalOrdinal = 0; }
    ~CallIdentity() { callingObject = previous; originalOrdinal = previousOrdinal; }
};
struct Barrier
{
    std::mutex mutex;
    std::condition_variable cv;
    unsigned arrivals = 0;
    bool timedOut = false;
    bool first()
    {
        std::unique_lock lock(mutex);
        return cv.wait_for(lock, std::chrono::seconds(2), [&]{ return arrivals >= 1; });
    }
    void meet()
    {
        std::unique_lock lock(mutex);
        ++arrivals; cv.notify_all();
        if (!cv.wait_for(lock, std::chrono::seconds(2), [&]{ return arrivals >= 2; })) timedOut = true;
    }
};

// Legacy catalog seams: token comparisons and lock/destructor evidence are real;
// resource contents, GPU ownership, HUD behavior and production catalog coverage are not modeled.
struct SurveyRecord { Token birth; std::shared_ptr<DetachedOwner> owner; };
CatalogMutex surveyMutex, observerMutex, d3dMutex;
std::unordered_map<void*, SurveyRecord> surveyRecords;
std::unordered_map<void*, Token> observerRecords, d3dRecords;
std::function<void(const Token&)> notifyObserver;
namespace FrameSurvey
{
    thread_local bool ownedRelease = false;
    bool OwnedRelease() noexcept { return ownedRelease; }
    struct RetirementEffects
    { Token birth; std::array<std::shared_ptr<DetachedOwner>, 4> owners; };
    bool PrepareRetirementEffects(RetirementEffects&) noexcept
    {
        ++factoryCalls; if (!outsideMetadata()) ++factoryUnderMetadata;
        return !failPrepareEffects.load();
    }
    bool DetachReleaseMetadata(const Token& birth, RetirementEffects& effects) noexcept
    {
        ++detachCalls;
        if (!NrdBridgeBirth::InMetadataAction() || failDetachEffects.load()) return false;
        std::scoped_lock lock(surveyMutex);
        effects.birth = birth;
        const auto found = surveyRecords.find(birth->Address());
        if (found != surveyRecords.end() && found->second.birth == birth)
        { effects.owners[0] = std::move(found->second.owner); surveyRecords.erase(found); }
        return true;
    }
    void NotifyRelease(RetirementEffects& effects) noexcept
    {
        ++notifyCalls; if (!outsideMetadata()) ++notifyUnderMetadata;
        if (effects.birth)
        {
            { std::scoped_lock lock(observerMutex);
              const auto found = observerRecords.find(effects.birth->Address());
              if (found != observerRecords.end() && found->second == effects.birth) observerRecords.erase(found); }
            if (notifyObserver) notifyObserver(effects.birth);
        }
    }
    void MetadataHookFailed(const char*) noexcept
    {
        surveyHealthy = false; ++metadataFailures;
        if (installerLocks) ++failuresUnderInstaller;
        // The actual health latch is permitted inside metadata guards; it is not a lifecycle observer.
        if (NrdBridgeBirth::InMetadataScope()) ++pureFailureUnderBirth;
    }
    void FlushMetadataFailure() noexcept {}
    template<class T> void Released(T*) noexcept { ++legacyReleased; }
}
struct D3D12Hooks
{
    static void OnBridgeObjectReleased(const Token& birth) noexcept
    {
        std::scoped_lock lock(d3dMutex);
        const auto found = d3dRecords.find(birth->Address());
        if (found != d3dRecords.end() && found->second == birth) d3dRecords.erase(found);
    }
    static void OnBridgeCommandListReset(ID3D12GraphicsCommandList* list, ID3D12PipelineState*) noexcept
    { std::scoped_lock lock(d3dMutex); d3dRecords.erase(list); }
};
namespace RecordedComputeLease
{
    struct ReleaseIntent { void* object; };
    template<class T> ReleaseIntent BeginRelease(T* object) noexcept { ++leaseBegins; return {object}; }
    void EndRelease(const ReleaseIntent&, bool final) noexcept { ++leaseEnds; if (final) ++leaseFinals; }
}
struct State
{
    bool isShuttingDown = false;
    std::unordered_map<ID3D12Resource*, bool> capturedHudlesses;
    static State& Instance() { static State state; return state; }
};
CatalogMutex gRRResourceStateMutex, gRRTrackedResourceMutex, gRRPsoMutex, _trackedResourcesMutex, heapMutex;
std::unordered_map<ID3D12Resource*, unsigned> gRRResourceStates, gRRResourceActivity, gRRTrackedResources;
std::unordered_map<void*, unsigned> rrProducers, rrPsoReferences;
struct HeapInfo
{
    Token birth, slotBirth;
    void* address = nullptr;
    ID3D12Resource* slotResource = nullptr;
    unsigned slotClears = 0;
    ~HeapInfo() { if (!outsideMetadata()) ++destructorUnderMetadata; ++heapDestructions; }
    void ClearSlotIfMatches(unsigned, ID3D12Resource* resource, const Token& expected = {}) noexcept
    {
        std::scoped_lock lock(heapMutex);
        if (slotResource == resource && (!expected || expected == slotBirth))
        { slotResource = nullptr; slotBirth.reset(); ++slotClears; }
    }
};
struct TrackedResourceSlot { std::weak_ptr<HeapInfo> heap; unsigned index; };
std::unordered_map<ID3D12Resource*, std::vector<TrackedResourceSlot>> _trackedResources;
std::unordered_map<void*, std::shared_ptr<HeapInfo>> heaps;
void CleanupRRResourcePsoProducersLocked(ID3D12Resource* object) { rrProducers.erase(object); }
void CleanupRRPsoReferences(void* object) { std::scoped_lock lock(gRRPsoMutex); rrPsoReferences.erase(object); }
std::shared_ptr<HeapInfo> FindTrackedHeapByAddress(void* address)
{
    std::scoped_lock lock(heapMutex);
    const auto found = heaps.find(address); return found == heaps.end() ? nullptr : found->second;
}
bool DeactivateTrackedHeap(const std::shared_ptr<HeapInfo>& heap)
{
    std::scoped_lock lock(heapMutex);
    const auto found = heaps.find(heap->address);
    if (found == heaps.end() || found->second != heap) return false;
    heaps.erase(found); return true;
}
void DeactivateSharedHeap(void* address)
{ if (auto heap = FindTrackedHeapByAddress(address)) DeactivateTrackedHeap(heap); }

// The only replaced production dependency of the actual release header is the lease seam above.
__RELEASE_HELPERS__

bool gNrdBridgeWrappers = true, gSurveyWrappers = true;
PVOID gResourceReleaseEntry = nullptr, gHeapReleaseEntry = nullptr;
PVOID gPsoReleaseEntry = nullptr, gCommandListReleaseEntry = nullptr;
bool gResourceReleaseSharesPso = false, gResourceReleaseSharesCommandList = false;
std::atomic<bool> gHeapReleaseSharesResource = false;
InstallerMutex gReleaseHookInstallMutex;
std::array<std::atomic<unsigned>, 4> dedicatedForwards {};
ULONG resourceForward(ID3D12Resource* object) { ++dedicatedForwards[0]; return reinterpret_cast<IUnknown*>(object)->Release(); }
ULONG heapForward(ID3D12DescriptorHeap* object) { ++dedicatedForwards[1]; return reinterpret_cast<IUnknown*>(object)->Release(); }
ULONG psoForward(ID3D12PipelineState* object) { ++dedicatedForwards[2]; return reinterpret_cast<IUnknown*>(object)->Release(); }
ULONG STDMETHODCALLTYPE listForward(IUnknown* object) { ++dedicatedForwards[3]; return object->Release(); }
using ResourceRelease = ULONG (*)(ID3D12Resource*);
using HeapRelease = ULONG (*)(ID3D12DescriptorHeap*);
using PsoRelease = ULONG (*)(ID3D12PipelineState*);
ResourceRelease o_Release = resourceForward;
HeapRelease o_HeapRelease = heapForward;
PsoRelease o_PsoRelease = psoForward;
ULONG(STDMETHODCALLTYPE* o_CommandListRelease)(IUnknown*) = listForward;
ResourceRelease gSharedResourceReleaseObserver = nullptr;

// Transaction adapters do not patch any vtable or executable entrypoint.
enum class InstallFailure { None, Begin, Update, Attach, Commit };
InstallFailure installFailure = InstallFailure::None;
unsigned installBegins = 0, installUpdates = 0, installAttaches = 0, installCommits = 0, installAborts = 0;
PVOID lastAttachTarget = nullptr;
constexpr LONG installError = ERROR_INVALID_OPERATION;
LONG DetourTransactionBegin() { ++installBegins; return installFailure == InstallFailure::Begin ? installError : NO_ERROR; }
LONG DetourUpdateThread(HANDLE) { ++installUpdates; return installFailure == InstallFailure::Update ? installError : NO_ERROR; }
LONG DetourAttach(PVOID*, PVOID target)
{ ++installAttaches; lastAttachTarget = target; return installFailure == InstallFailure::Attach ? installError : NO_ERROR; }
LONG DetourTransactionCommit() { ++installCommits; return installFailure == InstallFailure::Commit ? installError : NO_ERROR; }
LONG DetourTransactionAbort() { ++installAborts; return NO_ERROR; }
struct ResTrack_Dx12
{
    static bool ConfigureNrdNativeBirthRetirement() noexcept;
    static bool ObserveBridgeObjectRelease(IUnknown*) noexcept;
    static ULONG hkRelease(ID3D12Resource*);
};
__GATE_AND_GENERIC__
__RETIREMENT_PAYLOAD__
__CONFIGURE__
__INSTALLER__
__DEDICATED_WRAPPERS__

PVOID entry(IUnknown* object) { return (*reinterpret_cast<PVOID**>(object))[2]; }
ULONG callResource(CpuObject& object)
{ CallIdentity identity(&object); return ResTrack_Dx12::hkRelease(reinterpret_cast<ID3D12Resource*>(&object)); }
ULONG callHeap(CpuObject& object)
{ CallIdentity identity(&object); return hkHeapRelease(reinterpret_cast<ID3D12DescriptorHeap*>(&object)); }
ULONG callPso(CpuObject& object)
{ CallIdentity identity(&object); return hkPsoRelease(reinterpret_cast<ID3D12PipelineState*>(&object)); }
ULONG callList(CpuObject& object)
{ CallIdentity identity(&object); return hkCommandListRelease(&object); }
ULONG callGeneric(CpuObject& object)
{
    CallIdentity identity(&object);
    for (size_t i = 0; i < gBirthReleaseEntriesUsed; ++i)
        if (gBirthReleaseEntries[i].entry.load() == entry(&object)) return gBirthReleaseHooks[i](&object);
    throw std::runtime_error("generic callback was not installed");
}
void publish(const Token& birth, bool heap = false, const std::shared_ptr<HeapInfo>& descriptorHeap = {})
{
    auto owner = std::make_shared<DetachedOwner>();
    std::shared_ptr<HeapInfo> heapOwner;
    if (heap) { heapOwner = std::make_shared<HeapInfo>(); heapOwner->birth = birth; heapOwner->address = birth->Address(); }
    std::vector<TrackedResourceSlot> slots;
    if (descriptorHeap) slots.push_back({descriptorHeap, 0});
    NrdBridgeBirth::CurrentGuard current(birth);
    need(current.MatchesCurrent(), "publication uses actual current-generation guard");
    { std::scoped_lock lock(surveyMutex); surveyRecords.emplace(birth->Address(), SurveyRecord{birth, std::move(owner)}); }
    { std::scoped_lock lock(observerMutex); observerRecords[birth->Address()] = birth; }
    { std::scoped_lock lock(d3dMutex); d3dRecords[birth->Address()] = birth; }
    auto* resource = static_cast<ID3D12Resource*>(birth->Address());
    { std::scoped_lock lock(gRRResourceStateMutex); gRRResourceStates[resource] = 1; gRRResourceActivity[resource] = 1; }
    { std::scoped_lock lock(gRRTrackedResourceMutex); gRRTrackedResources[resource] = 1; }
    { std::scoped_lock lock(gRRPsoMutex); rrProducers[resource] = 1; rrPsoReferences[resource] = 1; }
    { std::scoped_lock lock(_trackedResourcesMutex); _trackedResources[resource] = std::move(slots); State::Instance().capturedHudlesses[resource] = true; }
    if (descriptorHeap)
    { std::scoped_lock lock(heapMutex); descriptorHeap->slotResource = resource; descriptorHeap->slotBirth = birth; }
    if (heapOwner) { std::scoped_lock lock(heapMutex); heaps[birth->Address()] = std::move(heapOwner); }
}
Token prepare(CpuObject& object, bool heap = false, const std::shared_ptr<HeapInfo>& descriptorHeap = {})
{
    const auto birth = NrdBridgeNativeBirth::Prepare(&object);
    need(birth && birth->Admissible(), "native byte-data helper returns a ready current birth");
    publish(birth, heap, descriptorHeap); return birth;
}
void cleared(const Token& birth)
{
    void* address = birth->Address(); auto* resource = static_cast<ID3D12Resource*>(address);
    need(!birth->Live() && !NrdBridgeBirth::Capture(address), "retired address has no live logical generation");
    need(!surveyRecords.count(address) && !observerRecords.count(address) && !d3dRecords.count(address), "survey/observer/root-list metadata retired by actual dispatcher");
    need(!gRRResourceStates.count(resource) && !gRRResourceActivity.count(resource) && !gRRTrackedResources.count(resource), "RR state/activity/participants erased");
    need(!rrProducers.count(address) && !rrPsoReferences.count(address), "producer/PSO reverse references erased");
    need(!_trackedResources.count(resource) && !State::Instance().capturedHudlesses.count(resource), "descriptor/HUD reverse references erased");
    need(!heaps.count(address), "matching heap generation deactivated");
}
void outsideAssertions()
{
    need(nativeUnderMetadata == 0, "new title native byte/AddRef/Release calls run outside metadata locks");
    need(factoryUnderMetadata == 0 && notifyUnderMetadata == 0, "factory/notification run outside Birth/catalog/installer locks");
    need(destructorUnderMetadata == 0, "detached survey/heap owners die outside every metadata lock");
    need(failuresUnderInstaller == 0, "failure status is published after installer unlock");
    need(factoryCalls == notifyCalls, "every prepared actual TLS payload drains exactly once");
    need(gNativeRetirementDepth == 0, "TLS payload depth is restored after nested work");
}

void finalKinds()
{
    DistinctObject<1> resource; DistinctObject<2> heap; DistinctObject<3> pso;
    DistinctObject<4> list; DistinctObject<5> root;
    gResourceReleaseEntry = entry(&resource); gHeapReleaseEntry = entry(&heap);
    gPsoReleaseEntry = entry(&pso); gCommandListReleaseEntry = entry(&list);
    gSharedResourceReleaseObserver = ResTrack_Dx12::hkRelease;
    std::array<CpuObject*,5> objects {&resource, &heap, &pso, &list, &root};
    std::array<ULONG(*)(CpuObject&),5> callbacks {callResource, callHeap, callPso, callList, callGeneric};
    auto slots = std::make_shared<HeapInfo>();
    for (unsigned i = 0; i < objects.size(); ++i)
    {
        auto& object = *objects[i];
        const unsigned destroyed = ownerDestructions.load(), detached = detachCalls.load();
        const unsigned heapDestroyed = heapDestructions.load();
        const auto birth = prepare(object, i == 1, i == 0 ? slots : nullptr);
        need(ResTrack_Dx12::ObserveBridgeObjectRelease(&object), "actual installer recognizes dedicated or installs distinct root Release");
        if (i != 4) need(installAttaches == 0, "covered resource/heap/PSO/list fast paths attach no generic observer");
        const unsigned calls = nativeTraceSize.load();
        need(callbacks[i](object) == 0, "actual title wrapper returns native final zero");
        need(object.addRefs == 1 && object.releases == 2 && object.zeros == 1, "one temporary probe and one caller Release, with one destruction");
        need(nativeTrace[calls].ordinal == 1 && nativeTrace[calls].result == 1 &&
             nativeTrace[calls+1].ordinal == 2 && nativeTrace[calls+1].result == 0, "probe<=1 is retired before actual final zero");
        need(detachCalls == detached+1 && ownerDestructions == destroyed+1, "final exact generation detaches/destroys owners only once");
        if (i == 0) need(slots->slotClears == 1 && !slots->slotResource, "actual payload clears indexed descriptor slot with exact birth");
        if (i == 1) need(heapDestructions == heapDestroyed+1, "actual payload retains heap until its unlocked notification drain");
        cleared(birth);
    }
    need(installAttaches == 1 && lastAttachTarget == reinterpret_cast<PVOID>(gBirthReleaseHooks[0]), "distinct root implementation installs the real bounded callback target");
    need(leaseBegins == 5 && leaseEnds == 5 && leaseFinals == 5, "all five kinds preserve recorded-release begin/end and actual-final intent");
    need(NrdBridgeBirth::Healthy() && surveyHealthy && metadataFailures == 0, "valid final paths preserve metadata health");
    outsideAssertions();
}
void sharedKinds()
{
    DistinctObject<6> pso; DistinctObject<7> list; DistinctObject<8> heap;
    gSharedResourceReleaseObserver = ResTrack_Dx12::hkRelease;
    std::array<CpuObject*,3> objects {&pso,&list,&heap};
    std::array<ULONG(*)(CpuObject&),3> callbacks {callPso,callList,callHeap};
    gResourceReleaseSharesPso = true; gResourceReleaseSharesCommandList = true; gHeapReleaseSharesResource = true;
    for (unsigned i = 0; i < objects.size(); ++i)
    {
        const auto birth = prepare(*objects[i], i == 2);
        need(callbacks[i](*objects[i]) == 0, "shared dedicated entry executes actual resource dispatcher");
        need(objects[i]->addRefs == 1 && objects[i]->releases == 2, "shared observer has exactly one probe/caller pair");
        cleared(birth);
    }
    need(dedicatedForwards[0] == 6 && dedicatedForwards[1] == 0 &&
         dedicatedForwards[2] == 0 && dedicatedForwards[3] == 0, "shared wrappers do not forward through two original trampolines");
    outsideAssertions();
}
void nonfinal()
{
    DistinctObject<9> object; object.physical->refs = 10004;
    const auto birth = prepare(object);
    callResource(object); // Warm TLS/native/perf paths before allocation measurement.
    const unsigned factories = factoryCalls.load(), notifications = notifyCalls.load();
    const unsigned reads = object.reads.load(), writes = object.writes.load();
    allocations = 0; meterAllocations = true;
    for (unsigned i = 0; i < 1000; ++i) callResource(object);
    meterAllocations = false;
    need(allocations == 0, "1000 warmed nonfinal actual wrappers make zero C++ allocations");
    need(factoryCalls == factories && notifyCalls == notifications && detachCalls == 0, "nonfinal path creates no retirement payload or catalog cleanup");
    need(object.reads == reads && object.writes == writes, "nonfinal Release performs no native private-data queries/writes");
    need(object.addRefs == 1001 && object.releases == 2002 && object.physical->refs == 9003, "nonfinal forwarding consumes only caller references");
    need(birth->Live() && birth->ReleasesInFlight() == 0 && birth->CacheAdmissible(), "nonfinal completion restores release counter and cache eligibility");
    NrdBridgeRelease::RetireExact(birth); cleared(birth); outsideAssertions();
}
void simultaneous(bool aliases)
{
    DistinctObject<10> object; DistinctObject<11> alias;
    object.physical->refs = 2;
    const auto birth = prepare(object);
    Token aliasBirth;
    if (aliases) { alias.physical = object.physical; aliasBirth = prepare(alias); }
    Barrier probe; std::array<ULONG,2> results {};
    object.afterRelease = [&](unsigned ordinal,ULONG result)
    { if (ordinal == 1) { probe.meet(); } };
    const unsigned firstTrace = nativeTraceSize.load();
    std::thread left([&]{ results[0] = callResource(object); });
    const bool firstProbeEntered = probe.first();
    std::thread right([&]{ results[1] = callResource(object); });
    left.join(); right.join();
    need(firstProbeEntered && !probe.timedOut, "concurrent native probes finish without exclusive-lifetime deadlock");
    unsigned probeCount = 0;
    for (unsigned i = firstTrace; i < nativeTraceSize; ++i)
        if (nativeTrace[i].ordinal == 1) { need(nativeTrace[i].result == 2, "both temporary probes observe refcount2"); ++probeCount; }
    need(probeCount == 2 && std::min(results[0],results[1]) == 0 && std::max(results[0],results[1]) == 1,
         "actual final zero cleans up after both probes miss <=1");
    need(object.addRefs == 2 && object.releases == 4 && object.zeros == 1, "simultaneous calls forward exactly two probe/caller pairs");
    cleared(birth);
    if (aliases)
    {
        need(aliasBirth->InstanceStamp() == birth->InstanceStamp() && aliasBirth->Sequence() != birth->Sequence(), "aliases are proved only by exact shared native byte stamp");
        cleared(aliasBirth);
        need(alias.addRefs == 0 && alias.releases == 0, "alias metadata retirement makes no extra native COM calls");
    }
    need(NrdBridgeBirth::Healthy() && surveyHealthy, "concurrent final retirement preserves health");
    outsideAssertions();
}
void interned()
{
    DistinctObject<12> object; const auto old = prepare(object); Token fresh;
    bool reobserved = false;
    notifyObserver = [&](const Token& retired)
    {
        if (retired == old && !reobserved)
        {
            reobserved = true; fresh = NrdBridgeNativeBirth::Prepare(&object);
            if (fresh) publish(fresh);
        }
    };
    need(callResource(object) == 0, "interned logical re-observation still returns physical final zero");
    notifyObserver = {};
    need(reobserved && fresh && fresh != old && fresh->Sequence() != old->Sequence() &&
         fresh->InstanceStamp() == old->InstanceStamp(), "same native stamp re-observation has a new logical generation");
    need(!fresh->Live() && !old->Live() && !NrdBridgeBirth::Capture(&object), "actual zero retires current same-stamp generation after exact pre-retire");
    need(object.addRefs == 1 && object.releases == 2 && object.writes == 1, "interning adds no COM reference or second stamp write");
    cleared(fresh); outsideAssertions();
}
void recycled()
{
    DistinctObject<13> object; const auto old = prepare(object); Token fresh;
    object.afterRelease = [&](unsigned ordinal,ULONG result)
    {
        if (ordinal == 2 && result == 0)
        { object.physical = std::make_shared<PhysicalObject>(); fresh = NrdBridgeNativeBirth::Prepare(&object); if (fresh) publish(fresh); }
    };
    need(callResource(object) == 0, "old physical final returns zero despite recycled address");
    object.afterRelease = {};
    need(fresh && fresh != old && fresh->InstanceStamp() != old->InstanceStamp() && fresh->Live(), "different native stamp at same address survives old final ticket");
    need(NrdBridgeBirth::Capture(&object) == fresh && observerRecords.at(&object) == fresh &&
         surveyRecords.at(&object).birth == fresh && d3dRecords.at(&object) == fresh, "newborn catalog/root/observer generation is intact");
    NrdBridgeRelease::RetireExact(old); NrdBridgeRelease::RetirePhysical(old);
    need(NrdBridgeBirth::Capture(&object) == fresh && fresh->Live(), "late exact and physical old tickets cannot retire newborn");
    // Deliver a delayed old notification through the ACTUAL root notifier body.
    auto* payload = static_cast<NativeRetirementPayload*>(PrepareNativeRetirement());
    need(payload != nullptr, "late callback gets real TLS notification payload");
    payload->survey.birth = old; payload->survey.owners[0] = std::make_shared<DetachedOwner>();
    NotifyNativeRetirement(payload);
    need(observerRecords.at(&object) == fresh && surveyRecords.at(&object).birth == fresh,
         "late old notification token preserves newborn observer and catalog");
    need(callResource(object) == 0, "new physical generation can independently retire");
    cleared(fresh); outsideAssertions();
}
void aliases()
{
    DistinctObject<14> object; DistinctObject<15> alias; DistinctObject<16> recycledAlias;
    const auto first = prepare(object); alias.physical = object.physical; recycledAlias.physical = object.physical;
    const auto second = prepare(alias); const auto third = prepare(recycledAlias);
    Token newborn;
    object.afterRelease = [&](unsigned ordinal,ULONG result)
    {
        if (ordinal == 2 && result == 0)
        {
            recycledAlias.physical = std::make_shared<PhysicalObject>();
            newborn = NrdBridgeNativeBirth::Prepare(&recycledAlias); if (newborn) publish(newborn);
        }
    };
    need(callResource(object) == 0, "alias title caller reaches native final zero");
    object.afterRelease = {};
    cleared(first); cleared(second);
    need(!third->Live() && newborn && newborn->Live() && newborn->InstanceStamp() != third->InstanceStamp(),
         "final-zero alias batch retires old physical identity while preserving recycled alias address");
    need(alias.addRefs == 0 && alias.releases == 0 && recycledAlias.addRefs == 0 && recycledAlias.releases == 0,
         "bounded alias retirement performs no extra COM calls on proven aliases");
    need(NrdBridgeBirth::Capture(&recycledAlias) == newborn && observerRecords.at(&recycledAlias) == newborn,
         "alias final ticket cannot erase newborn token or observer");
    need(callResource(recycledAlias) == 0, "recycled alias later retires its own physical instance");
    cleared(newborn); outsideAssertions();
}
void nested()
{
    DistinctObject<17> left; DistinctObject<18> right;
    left.physical->refs = right.physical->refs = 4;
    const auto first = prepare(left), second = prepare(right);
    need(ResTrack_Dx12::ObserveBridgeObjectRelease(&left) && ResTrack_Dx12::ObserveBridgeObjectRelease(&right), "both distinct nested Release implementations installed");
    Barrier probes; std::atomic<unsigned> nestedCalls = 0;
    left.afterRelease = [&](unsigned ordinal,ULONG)
    { if (ordinal == 1 && nestedReleaseDepth == 0) { probes.meet(); ++nestedReleaseDepth; ++nestedCalls; callGeneric(right); --nestedReleaseDepth; } };
    right.afterRelease = [&](unsigned ordinal,ULONG)
    { if (ordinal == 1 && nestedReleaseDepth == 0) { probes.meet(); ++nestedReleaseDepth; ++nestedCalls; callGeneric(left); --nestedReleaseDepth; } };
    std::thread a([&]{ callGeneric(left); }); std::thread b([&]{ callGeneric(right); }); a.join(); b.join();
    left.afterRelease = {}; right.afterRelease = {};
    need(!probes.timedOut && nestedCalls == 2, "opposite concurrent A-to-B/B-to-A native reentrancy completes without ABBA deadlock");
    need(left.releases == 4 && right.releases == 4 && left.addRefs == 2 && right.addRefs == 2,
         "each outer/nested actual generic callback forwards only its probe/caller pair");
    need(left.physical->refs == 2 && right.physical->refs == 2 && first->Live() && second->Live(), "nonfinal nested calls keep both current generations live");
    need(first->ReleasesInFlight() == 0 && second->ReleasesInFlight() == 0 && NrdBridgeBirth::Healthy(), "nested per-physical counters unwind independently");
    NrdBridgeRelease::RetireExact(first); NrdBridgeRelease::RetireExact(second);
    cleared(first); cleared(second); outsideAssertions();
}
void off()
{
    gNrdBridgeWrappers = gSurveyWrappers = false;
    DistinctObject<19> object; object.physical->refs = 2;
    legacyNativeAllowed = true;
    need(callResource(object) == 1, "startup OFF retains legacy resource Release behavior");
    legacyNativeAllowed = false;
    need(object.addRefs == 1 && object.releases == 2, "OFF original resource probe/caller pair is retained");
    need(!ResTrack_Dx12::ObserveBridgeObjectRelease(&object), "OFF unconfigured birth dispatcher installs nothing");
    need(NrdBridgeBirth::Detail::constructedRegistries == 0 && !NrdBridgeNativeBirth::Ready() &&
         factoryCalls == 0 && detachCalls == 0 && object.reads == 0 && object.writes == 0,
         "OFF constructs no birth registry/payload and performs no private-data identity work");
    need(installAttaches == 0 && metadataFailures == 0, "OFF attaches no generic hooks and reports no birth failure");
}
void ownedOrShutdown(bool shutdown)
{
    DistinctObject<20> object; const auto birth = prepare(object);
    need(ResTrack_Dx12::ObserveBridgeObjectRelease(&object), "generic callback installed before bypass scenario");
    const auto factories = factoryCalls.load(), detached = detachCalls.load();
    const auto reads = object.reads.load(), writes = object.writes.load();
    FrameSurvey::ownedRelease = !shutdown; State::Instance().isShuttingDown = shutdown;
    need(callGeneric(object) == 0, "actual generic owned/shutdown bypass forwards native caller once");
    FrameSurvey::ownedRelease = false; State::Instance().isShuttingDown = false;
    need(object.addRefs == 0 && object.releases == 1, "generic bypass adds no physical probe");
    need(factoryCalls == factories && detachCalls == detached && object.reads == reads && object.writes == writes,
         "owned/shutdown bypass has no identity/retirement callback work");
    need(birth->Live() && birth->ReleasesInFlight() == 0, "bypass does not claim native-birth retirement");
    NrdBridgeRelease::RetireExact(birth); cleared(birth); outsideAssertions();
}
template<size_t... Id> auto installObjects(std::index_sequence<Id...>)
{ return std::array<std::unique_ptr<CpuObject>,sizeof...(Id)>{std::make_unique<DistinctObject<unsigned(Id)+25>>()...}; }
void installerFull()
{
    auto objects = installObjects(std::make_index_sequence<17>{});
    for (unsigned i = 0; i < 16; ++i)
    {
        const auto birth = prepare(*objects[i]);
        need(ResTrack_Dx12::ObserveBridgeObjectRelease(objects[i].get()), "bounded installer covers distinct native implementation");
        need(gBirthReleaseEntriesUsed == i+1 && lastAttachTarget == reinterpret_cast<PVOID>(gBirthReleaseHooks[i]), "actual installed callback target/index published");
        const unsigned attaches = installAttaches;
        need(ResTrack_Dx12::ObserveBridgeObjectRelease(objects[i].get()) && installAttaches == attaches, "covered receiver does not install twice");
        need(callGeneric(*objects[i]) == 0 && objects[i]->releases == 2 && objects[i]->addRefs == 1, "each actual installed generic target executes Title forwarding");
        cleared(birth);
    }
    need(!ResTrack_Dx12::ObserveBridgeObjectRelease(objects[16].get()), "seventeenth distinct implementation fails closed at bounded capacity");
    need(gBirthReleaseEntriesUsed == 16 && installAttaches == 16 && !surveyHealthy && metadataFailures == 1,
         "table-full failure preserves all covered entries without an extra attach");
    need(objects[16]->reads == 0 && objects[16]->writes == 0 && objects[16]->releases == 0, "uncovered receiver has no admitted identity or native Release work");
    outsideAssertions();
}
void installerFailure(const std::string& kind)
{
    DistinctObject<43> object;
    if (kind == "install-begin") installFailure = InstallFailure::Begin;
    else if (kind == "install-update") installFailure = InstallFailure::Update;
    else if (kind == "install-attach") installFailure = InstallFailure::Attach;
    else if (kind == "install-commit") installFailure = InstallFailure::Commit;
    else throw std::runtime_error("unknown installer failure");
    need(!ResTrack_Dx12::ObserveBridgeObjectRelease(&object), "actual transaction failure denies uncovered Release implementation");
    need(gBirthReleaseEntriesUsed == 0 && !gBirthReleaseEntries[0].entry.load() && !gBirthReleaseEntries[0].original,
         "failed transaction publishes no callback entry or trampoline");
    need(metadataFailures == 1 && !surveyHealthy && failuresUnderInstaller == 0,
         "actual failure path reports after installer unlock");
    need(object.releases == 0 && object.addRefs == 0 && object.reads == 0 && object.writes == 0,
         "failed installer makes no COM/private-data calls");
    need(installBegins == 1 && installUpdates == (kind != "install-begin"), "transaction stops after failed begin/update stage");
    need(installAttaches == (kind == "install-attach" || kind == "install-commit") &&
         installCommits == (kind == "install-commit") && installAborts == (kind == "install-update" || kind == "install-attach"),
         "attach/commit/abort sequence follows actual error path exactly");
    outsideAssertions();
}
void dispatcherFailure(const std::string& kind)
{
    DistinctObject<44> object; const auto birth = prepare(object);
    std::array<void*,16> outer {};
    if (kind == "factory") failPrepareEffects = true;
    else if (kind == "detach") failDetachEffects = true;
    else if (kind == "payload-depth")
    {
        for (auto& payload : outer) { payload = PrepareNativeRetirement(); need(payload != nullptr, "bounded TLS outer payload prepared"); }
        need(!PrepareNativeRetirement(), "seventeenth TLS payload is rejected without allocation");
    }
    else throw std::runtime_error("unknown dispatcher failure");
    need(callResource(object) == 0 && object.releases == 2 && object.addRefs == 1, "retirement failure preserves both native forwards and final return");
    failPrepareEffects = false; failDetachEffects = false;
    if (kind == "payload-depth") for (size_t i = outer.size(); i; --i) NotifyNativeRetirement(outer[i-1]);
    need(!NrdBridgeBirth::Healthy() && !surveyHealthy && metadataFailures >= 1, "actual helper failure latches health and rejects later birth use");
    need(!NrdBridgeNativeBirth::Prepare(&object), "latched failure admits no later receiver");
    need(nativeUnderMetadata == 0 && factoryUnderMetadata == 0 && notifyUnderMetadata == 0 && destructorUnderMetadata == 0,
         "failure never executes native calls/owner drain under metadata guards");
    need(gNativeRetirementDepth == 0 && failuresUnderInstaller == 0, "failure unwinds caller TLS payload state outside installer lock");
}
int main(int argc,char** argv) try
{
    SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS);
    const std::string kind = argc > 1 ? argv[1] : "final-kinds";
    if (kind == "off") off();
    else
    {
        need(ResTrack_Dx12::ConfigureNrdNativeBirthRetirement(), "actual cold dispatcher registration enables concurrent title Release");
        need(ResTrack_Dx12::ConfigureNrdNativeBirthRetirement(), "same actual dispatcher registration is idempotent");
        if (kind == "final-kinds") finalKinds();
        else if (kind == "shared-kinds") sharedKinds();
        else if (kind == "nonfinal") nonfinal();
        else if (kind == "simultaneous") simultaneous(false);
        else if (kind == "simultaneous-aliases") simultaneous(true);
        else if (kind == "interned") interned();
        else if (kind == "recycled") recycled();
        else if (kind == "aliases") aliases();
        else if (kind == "nested") nested();
        else if (kind == "owned") ownedOrShutdown(false);
        else if (kind == "shutdown") ownedOrShutdown(true);
        else if (kind == "installer-full") installerFull();
        else if (kind.rfind("install-",0) == 0) installerFailure(kind);
        else dispatcherFailure(kind);
    }
    std::cout << "{\"case\":\"" << kind << "\",\"checks\":" << checks
              << ",\"factory_calls\":" << factoryCalls << ",\"detach_calls\":" << detachCalls
              << ",\"notify_calls\":" << notifyCalls << ",\"native_releases\":" << nativeTraceSize
              << ",\"allocations_in_nonfinal\":" << allocations << ",\"owner_destructions\":" << ownerDestructions
              << ",\"metadata_failures\":" << metadataFailures << "}\n";
    return 0;
}
catch (const std::exception& error)
{
    std::cerr << error.what() << '\n' << "checks=" << checks << " factory=" << factoryCalls
              << " detach=" << detachCalls << " notify=" << notifyCalls << " metadata_failures=" << metadataFailures
              << " native_under_metadata=" << nativeUnderMetadata << " notify_under_metadata=" << notifyUnderMetadata
              << " destructor_under_metadata=" << destructorUnderMetadata << " payload_depth=" << gNativeRetirementDepth << '\n';
    const unsigned end = std::min(nativeTraceSize.load(), unsigned(nativeTrace.size()));
    for (unsigned i = end > 16 ? end-16 : 0; i < end; ++i)
        std::cerr << "native[" << i << "] object=" << nativeTrace[i].address
                  << " ordinal=" << nativeTrace[i].ordinal << " result=" << nativeTrace[i].result << '\n';
    return 1;
}
'''


def generate(out):
    resource_path = ROOT/'OptiScaler/resource_tracking/ResTrack_dx12.cpp'
    release_path = ROOT/'OptiScaler/misc/NrdBridgeRelease_Dx12.h'
    resource = resource_path.read_text()
    release = release_path.read_text()
    helpers = release[release.index('namespace NrdBridgeRelease'):]
    gate_begin = resource.index('static bool UseNrdNativeRetirement()')
    gate_end = resource.index('static void PublishComputeHookAvailability()', gate_begin)
    gate = resource[gate_begin:gate_end]
    payload_begin = resource.index('struct NativeRetirementPayload')
    factory_begin = resource.index('void* PrepareNativeRetirement()', payload_begin)
    payload = resource[payload_begin:factory_begin] + '\n' + '\n'.join(
        function(resource, signature) for signature in (
            'void* PrepareNativeRetirement()',
            'bool DetachNativeRetirement(',
            'void NotifyNativeRetirement('))
    wrappers = '\n'.join(function(resource, signature) for signature in (
        'ULONG ResTrack_Dx12::hkRelease(',
        'static ULONG STDMETHODCALLTYPE hkHeapRelease(',
        'ULONG hkPsoRelease(',
        'static ULONG STDMETHODCALLTYPE hkCommandListRelease('))
    blocks = {
        'release_helpers': helpers,
        'gate_and_generic': gate,
        'retirement_payload': payload,
        'configure': function(resource, 'bool ResTrack_Dx12::ConfigureNrdNativeBirthRetirement()'),
        'installer': function(resource, 'bool ResTrack_Dx12::ObserveBridgeObjectRelease('),
        'dedicated_wrappers': wrappers,
    }
    cpp = CPP.replace('__ROOT__', ROOT.as_posix())
    for name, source in blocks.items():
        cpp = cpp.replace('__'+name.upper()+'__', source)
    assert '__RELEASE_' not in cpp and '__GATE_' not in cpp and '__DEDICATED_' not in cpp
    assert '#include "'+ROOT.as_posix()+'/OptiScaler/misc/NrdBridgePerf_Dx12.h"' in cpp
    assert 'NrdBridgeRelease::Title(This,o_Release)' in blocks['dedicated_wrappers']
    assert 'NrdBridgeRelease::Title(object,original)' in blocks['gate_and_generic']
    assert 'DetachNativeRetirement' in blocks['retirement_payload']
    assert 'NotifyNativeRetirement' in blocks['retirement_payload']
    out.mkdir(parents=True, exist_ok=True)
    target = out/'nrd_release_birth.cpp'
    target.write_text(cpp, encoding='utf-8')
    contract = {
        'scope': 'CPU adapters, actual headers/helper/callback/installer bodies; no native COM, real Detours or GPU',
        'production_source_sha256': {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (resource_path, release_path,
                         ROOT/'OptiScaler/misc/NrdBridgeBirth_Dx12.h',
                         ROOT/'OptiScaler/misc/NrdBridgeNativeBirth_Dx12.h',
                         ROOT/'OptiScaler/misc/NrdBridgeLifetime_Dx12.h',
                         ROOT/'OptiScaler/misc/NrdBridgePerf_Dx12.h')},
        'extracted_block_sha256': {name: hashlib.sha256(source.encode()).hexdigest() for name, source in blocks.items()},
        'supplement_only': 'test_fsrd_nrd_release.py and its existing 264 invariants are unchanged',
        'allocation_probe': 'global C++ operator new/new[] count, enabled only around 1000 warmed nonfinal calls',
        'adapters': ['FrameSurvey retirement effects/catalog/owned flag/health latch',
                     'D3D root/list catalog', 'RR producers/states', 'HUD/heap/descriptor catalogs',
                     'RecordedComputeLease begin/end', 'IUnknown refcount/native private-data bytes',
                     'Detours transaction stages; actual installed callback targets invoked explicitly'],
        'cases': CASES,
    }
    (out/'contract.json').write_text(json.dumps(contract, indent=2)+'\n', encoding='utf-8')
    return target, contract


CASES = ['off', 'final-kinds', 'shared-kinds', 'nonfinal', 'simultaneous',
         'simultaneous-aliases', 'interned', 'recycled', 'aliases', 'nested',
         'owned', 'shutdown', 'installer-full', 'install-begin', 'install-update',
         'install-attach', 'install-commit', 'factory', 'detach', 'payload-depth']


def run():
    out = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT/'nrd_release_birth_output'))
    source, contract = generate(out)
    if '--prepare-only' in sys.argv or os.environ.get('FSRD_RELEASE_BIRTH_GENERATE_ONLY') == '1':
        print(json.dumps({'generated_source': str(source), 'production_sha256': contract['production_source_sha256'],
                          'cases_prepared': len(CASES), 'compiled': False, 'executed': False}, indent=2))
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fsrd_toolchain import compile_cpp
    exe = out/'nrd_release_birth.exe'
    compile_cpp(source, exe, ('bcrypt.lib', 'dxguid.lib'), (ROOT/'OptiScaler',))
    results = []
    for case in CASES:
        result = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=15)
        (out/(case+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        result.check_returncode()
        values = json.loads(result.stdout)
        assert values['case'] == case and values['checks'] > 0
        results.append(values)
    result = {'scope': contract['scope'], 'fresh_processes': len(results),
              'checks': sum(item['checks'] for item in results), 'cases': results,
              'old_release_fixture_modified': False}
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
