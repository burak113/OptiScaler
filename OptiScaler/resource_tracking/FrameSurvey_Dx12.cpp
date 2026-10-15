#include "pch.h"
#include <optional>
#include "FrameSurvey_Dx12.h"
#include "FrameSurveyMetadata.h"
#include "FrameSurveyBufferRanges.h"
#include "FrameSurveyConcurrentMetadata.h"
#include "misc/NrdBridgeLifetime_Dx12.h"
#include "misc/NrdBridgeNativeBirth_Dx12.h"
#include "misc/NrdBridgePerf_Dx12.h"
#include "misc/NrdBridgeTitleCallbacks_Dx12.h"
#include "shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h"
#include "shaders/fsrd_preprocess/FSRDGameTraceSession.h"
#include "shaders/fsrd_preprocess/RRTraceAdditiveIO.h"
#include "proxies/D3D12_Proxy.h"
#include "inputs/NVNGX_DLSS.h"
#include <nvsdk_ngx_defs_dlssd.h>
#include "include/d3dx/d3dx12.h"
#include <detours/detours.h>
#include <json.hpp>
#include <map>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <atomic>
#include <cctype>
#include <exception>

namespace NrdBridgeNativeBirth { bool ObserveReleaseCoverage(IUnknown*) noexcept; }

namespace FrameSurvey
{
namespace
{
using Json = nlohmann::json;
using Microsoft::WRL::ComPtr;
const GUID RootBlobId = {0xe971fb39,0x45a2,0x41ea,{0xa1,0x55,0x64,0xa8,0xc7,0xa4,0xfd,0x11}};
const GUID PipelineId = {0xeb65bd20,0x3531,0x41b0,{0xbc,0x65,0x40,0xd9,0xc2,0xbe,0x31,0x11}};
std::atomic<bool> gEnabled {false}, gRecording {false};
// Creation metadata (root layouts, shader hashes, heaps, views) is tracked from device creation when
// FrameSurvey=true or the NRD bridge is enabled. Install() runs later, after title pipeline creation.
std::atomic<bool> gTracking {false}, gSurveyBindings {false}, gBindingWindow {false}, gHooksInstalled {false};
// A partial registry/mirror update is never eligible for bridge reads until a clean device restart.
std::atomic<bool> gMetadataHealthy {true};
struct MetadataMutation
{
    int exceptions = std::uncaught_exceptions();
    ~MetadataMutation() { if (std::uncaught_exceptions() > exceptions) gMetadataHealthy.store(false,std::memory_order_release); }
};
#ifdef FSRD_NRD_BRIDGE_TEST
std::atomic<int> gCopyFailureAfterForTesting {-1};
std::atomic<bool> gViewFailureAfterReverseForTesting {false};
thread_local uint64_t gCopyViewSnapshotsForTesting = 0;
#endif
std::atomic<PipelineObserver> gPipelineObserver {nullptr};
std::atomic<GraphicsPipelineObserver> gGraphicsPipelineObserver {nullptr};
std::atomic<ReleaseObserver> gReleaseObserver {nullptr};
std::atomic<BirthReleaseObserver> gBirthReleaseObserver {nullptr};
std::atomic<const char*> gDeferredMetadataFailure {nullptr};
bool NativeTracking() noexcept { return NrdBridgeNativeBirth::Detail::configured.load(std::memory_order_acquire) == 2; }
bool BirthAvailable(const NrdBridgeBirth::Token& birth, const void* object) noexcept
{
    return birth ? birth->Address() == object && NrdBridgeBirth::CacheAdmissible(birth) : !NativeTracking();
}
bool BindingTracking() noexcept
{
    return gSurveyBindings.load(std::memory_order_relaxed) || gBindingWindow.load(std::memory_order_relaxed);
}
bool Tracking() noexcept { return gTracking.load(std::memory_order_relaxed) || gEnabled.load(std::memory_order_relaxed); }
// FrameSurveyPassHashes: lowercase shader SHA-256 prefixes whose outputs are saved right after the dispatch.
std::mutex gPassHashMutex;
std::vector<std::string> gPassHashes;
bool TargetsConfigured()
{
    std::scoped_lock lock(gPassHashMutex);
    return !gPassHashes.empty();
}
bool Targeted(const Json& pso)
{
    std::scoped_lock lock(gPassHashMutex);
    if (gPassHashes.empty() || !pso.is_object()) return false;
    const auto shaders = pso.find("shader_hashes");
    if (shaders == pso.end() || !shaders->is_object()) return false;
    for (const auto& [stage,hash] : shaders->items())
    {
        if (!hash.is_string()) continue;
        const auto& text = hash.get_ref<const std::string&>();
        for (const auto& prefix : gPassHashes) if (text.rfind(prefix,0) == 0) return true;
    }
    return false;
}
thread_local bool gInternal = false;
thread_local unsigned gRecordingDepth = 0;
struct InternalScope { bool previous = gInternal; InternalScope() { gInternal = true; } ~InternalScope() { gInternal = previous; } };
// Catalog scopes never acquire recorder/GAME_TRACE locks. Native COM borrows
// are acquired before the catalog; final Release is excluded by the hook gate.
// Unconfigured/legacy writers retain catalog + ordered slot synchronization.
// Native hot writers and retirement use snapshot SH + exact slot shards instead;
// POD readers take snapshot EX before catalog/mirror. This is not lock-free.
FrameSurveyMetadata::RecursiveSharedMutex gLifetimeMutex;
std::recursive_mutex gRecordMutex;
using DescriptorMutex = FrameSurveyMetadata::MetadataMutex<std::mutex,FrameSurveyMetadata::MetadataLock::Descriptor>;
std::array<DescriptorMutex,FrameSurveyMetadata::DescriptorShards> gViewMutexes;
std::mutex gSubmissionMutex;
uint64_t gNextResource = 0, gNextList = 0, gNextPass = 0;
uint32_t gRenderWidth = 0, gRenderHeight = 0;
Status gStatus;
struct Resource
{
    uint64_t id = 0, heap = 0, offset = 0, va = 0;
    ID3D12Resource* object = nullptr;
    D3D12_RESOURCE_DESC desc {};
    D3D12_RESOURCE_STATES initial = D3D12_RESOURCE_STATE_COMMON;
    bool initialKnown = false;
    FrameSurveyMetadata::DescriptorHandleOwner handles;
    NrdBridgeBirth::Token birth;
};
struct NativeResourceNode;
struct NativeHeapNode;
struct ViewInfo
{
    ID3D12Resource* object = nullptr;
    uint64_t resource = 0;
    uint32_t kind = 0, format = 0, subresource = 0;
    bool snapshotSupported = false;
    uint64_t descriptorCpu = 0, descriptorGpu = 0, descriptorHeap = 0, rootVa = 0;
    uint32_t descriptorIndex = UINT_MAX, rootIndex = UINT_MAX;
    bool heapKnown = false;
    uint64_t constantBytes = 0;
    std::shared_ptr<NativeResourceNode> resourceOwner;
    std::shared_ptr<NativeHeapNode> heapOwner;
    bool texture2D = false; // Exact view dimension; snapshotSupported also admits a single array slice.
};
struct Heap
{
    ID3D12DescriptorHeap* object = nullptr;
    uint64_t cpu = 0, gpu = 0;
    uint32_t count = 0, increment = 0, type = 0;
    FrameSurveyMetadata::DescriptorHandleOwner views; // Explicit native alias; ordinary copies remain deep.
    NrdBridgeBirth::Token birth;
};
// Native nodes are immutable except for reverse buckets protected by the exact
// descriptor shard. Their owners pin raw metadata, never title COM objects.
struct NativeResourceNode
{
    ID3D12Resource* object = nullptr;
    uint64_t id = 0, epoch = 0, address = 0;
    D3D12_RESOURCE_DESC description {};
    NrdBridgeBirth::Token birth;
    std::shared_ptr<FrameSurveyMetadata::DescriptorHandles> handles;
};
FrameSurveyMetadata::DescriptorShardMask HeapDescriptorShards(uint64_t cpu,uint32_t count,uint32_t increment,uint32_t type) noexcept
{
    if (type == D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER) return {};
    if (type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV)
        return FrameSurveyMetadata::DescriptorShardMask::All();
    return FrameSurveyMetadata::DescriptorShardMask::ForRange(cpu,count,increment);
}
struct NativeHeapNode
{
    ID3D12DescriptorHeap* object = nullptr;
    uint64_t id = 0, epoch = 0, cpu = 0, gpu = 0;
    uint32_t count = 0, increment = 0, type = 0;
    NrdBridgeBirth::Token birth;
    std::shared_ptr<FrameSurveyMetadata::DescriptorHandles> views;
    const FrameSurveyMetadata::DescriptorShardMask legalDescriptorShards;
    explicit NativeHeapNode(FrameSurveyMetadata::DescriptorShardMask legal = FrameSurveyMetadata::DescriptorShardMask::All()) noexcept
        : legalDescriptorShards(legal) {}
};
std::atomic<uint64_t> gNativeMetadataEpoch {1};
uint64_t gNextNativeHeap = 0; // Cold publication, catalog exclusive.
FrameSurveyMetadata::PinnedIdentityMap<ID3D12Resource*,NativeResourceNode> gNativeResources;
FrameSurveyMetadata::PinnedIdentityMap<ID3D12DescriptorHeap*,NativeHeapNode> gNativeHeaps;
FrameSurveyMetadata::NativeRangeIndex gNativeBuffers;
std::array<FrameSurveyMetadata::NativeRangeIndex,2> gNativeHeapRanges; // CBV/SRV/UAV, RTV. SAMPLER has no range.
FrameSurveyMetadata::RecursiveSharedMutex gNativeSnapshotMutex(true);
// Lifecycle cleanup uses SH and can interleave long copies. POD readers/Shutdown
// use EX before any catalog/mirror lock, draining every view/copy/release writer.
struct NativeSnapshotShared
{
    std::optional<std::shared_lock<FrameSurveyMetadata::RecursiveSharedMutex>> lock;
    int exceptions = std::uncaught_exceptions();
    NativeSnapshotShared() { if (NativeTracking()) lock.emplace(gNativeSnapshotMutex); }
    ~NativeSnapshotShared()
    { if (lock && std::uncaught_exceptions() > exceptions) gMetadataHealthy.store(false,std::memory_order_release); }
};
struct NativeSnapshotExclusive
{
    std::optional<std::unique_lock<FrameSurveyMetadata::RecursiveSharedMutex>> lock;
    NativeSnapshotExclusive() { if (NativeTracking()) lock.emplace(gNativeSnapshotMutex); }
};
template<class Node> bool NativeNodeCurrent(const std::shared_ptr<Node>& node) noexcept
{
    return node && node->epoch == gNativeMetadataEpoch.load(std::memory_order_acquire) &&
        node->birth && node->birth->Address() == node->object && NrdBridgeBirth::CacheAdmissible(node->birth);
}
// Pure descriptor metadata never dereferences a native object. An in-flight
// NONFINAL release must not erase a still-owned descriptor declaration. Native
// readers/bootstrap remain strictly CacheAdmissible; final retirement sets Live
// false before draining each slot, and before-mark writes are drained afterwards.
template<class Node> bool NativeNodeMetadataCurrent(const std::shared_ptr<Node>& node) noexcept
{
    return node && node->epoch == gNativeMetadataEpoch.load(std::memory_order_acquire) && node->birth &&
        node->birth->Address() == node->object && node->birth->Live() && !node->birth->Failed() && NrdBridgeBirth::Healthy();
}
std::unordered_map<ID3D12Resource*,Resource> gResources;
std::map<uint64_t,ID3D12Resource*> gAddresses;
FrameSurveyMetadata::BufferAddressIndex gBufferAddresses;
FrameSurveyMetadata::DescriptorMap<ViewInfo> gViews;
std::unordered_map<ID3D12DescriptorHeap*,Heap> gHeaps;
std::map<uint64_t,ID3D12DescriptorHeap*> gCpuHeaps;
// Caller holds gLifetimeMutex. Both CPU and shader-visible descriptor copies are creation metadata.
// The binding mirror and table resolution remain confined to the short NRD window.
Heap* HeapAtCpu(uint64_t handle)
{
    const auto upper = gCpuHeaps.upper_bound(handle);
    if (upper == gCpuHeaps.begin()) return nullptr;
    const auto found = gHeaps.find(std::prev(upper)->second);
    if (found == gHeaps.end()) return nullptr;
    auto& heap = found->second;
    return heap.increment && handle >= heap.cpu && handle-heap.cpu < uint64_t(heap.count)*heap.increment &&
        (handle-heap.cpu)%heap.increment == 0 ? &heap : nullptr;
}
// Caller holds the catalog exclusively, or shared plus the descriptor slot shard.
// Reverse-handle buckets use that same shard, including shared-resource/shared-heap views.
void EraseView(uint64_t handle)
{
    const auto view = gViews.find(handle);
    if (view == gViews.end()) return;
    if (const auto resource = gResources.find(view->second.object); resource != gResources.end())
        resource->second.handles.erase(handle);
    if (view->second.heapKnown)
        if (const auto heap = gHeaps.find(reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(view->second.descriptorHeap))); heap != gHeaps.end())
            heap->second.views.erase(handle);
    gViews.erase(view);
}
void IndexView(const ViewInfo& view)
{
    if (const auto resource = gResources.find(view.object); resource != gResources.end()) resource->second.handles.insert(view.descriptorCpu);
    if (view.heapKnown)
        if (const auto heap = gHeaps.find(reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(view.descriptorHeap))); heap != gHeaps.end())
            heap->second.views.insert(view.descriptorCpu);
}
bool SameViewContent(const ViewInfo& a, const ViewInfo& b) noexcept
{
    return a.object == b.object && a.resource == b.resource && a.kind == b.kind && a.format == b.format &&
        a.subresource == b.subresource && a.snapshotSupported == b.snapshotSupported && a.descriptorGpu == b.descriptorGpu &&
        a.rootVa == b.rootVa && a.descriptorIndex == b.descriptorIndex && a.rootIndex == b.rootIndex &&
        a.constantBytes == b.constantBytes && a.resourceOwner == b.resourceOwner && a.texture2D == b.texture2D;
}
bool SameView(const ViewInfo& a, const ViewInfo& b) noexcept
{
    return SameViewContent(a,b) && a.descriptorCpu == b.descriptorCpu && a.descriptorHeap == b.descriptorHeap &&
        a.heapKnown == b.heapKnown && a.heapOwner == b.heapOwner;
}
bool SameCopiedView(const ViewInfo& destination, const ViewInfo& source, uint64_t handle,
    const std::shared_ptr<NativeHeapNode>& heap) noexcept
{
    return heap && SameViewContent(destination,source) && destination.descriptorCpu == handle &&
        destination.descriptorHeap == uint64_t(reinterpret_cast<uintptr_t>(heap->object)) &&
        destination.heapKnown && destination.heapOwner == heap;
}
void ReplaceView(const ViewInfo& view)
{
    const auto previous = gViews.find(view.descriptorCpu);
    if (previous != gViews.end())
    {
        auto& old = previous->second;
        if (SameView(old,view)) return;
        if (old.object != view.object || old.resource != view.resource)
        {
            if (const auto resource = gResources.find(old.object); resource != gResources.end()) resource->second.handles.erase(view.descriptorCpu);
            if (const auto resource = gResources.find(view.object); resource != gResources.end()) resource->second.handles.insert(view.descriptorCpu);
        }
        if (old.heapKnown != view.heapKnown || old.descriptorHeap != view.descriptorHeap)
        {
            if (old.heapKnown)
                if (const auto heap = gHeaps.find(reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(old.descriptorHeap))); heap != gHeaps.end()) heap->second.views.erase(view.descriptorCpu);
            if (view.heapKnown)
                if (const auto heap = gHeaps.find(reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(view.descriptorHeap))); heap != gHeaps.end()) heap->second.views.insert(view.descriptorCpu);
        }
        old = view; return;
    }
    gViews.emplace(view.descriptorCpu,view); IndexView(view);
}
std::shared_ptr<NativeResourceNode> NativeResource(ID3D12Resource* object)
{
    struct Cache { ID3D12Resource* object = nullptr; std::shared_ptr<NativeResourceNode> node; };
    static thread_local std::array<Cache,4> cache; static thread_local unsigned next = 0;
    for (const auto& hit : cache) if (hit.object == object && NativeNodeCurrent(hit.node)) return hit.node;
    auto node = gNativeResources.Find(object);
    if (!NativeNodeCurrent(node)) return {};
    cache[next++%cache.size()] = {object,node}; return node;
}
std::shared_ptr<NativeHeapNode> NativeHeapAtCpu(uint64_t handle,uint32_t type)
{
    if (type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV) return {};
    const auto index = type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ? 1u : 0u;
    auto& ranges = gNativeHeapRanges[index];
    struct Cache { uint64_t version = 0; std::shared_ptr<NativeHeapNode> node; };
    static thread_local std::array<std::array<Cache,4>,2> cache; static thread_local std::array<unsigned,2> next {};
    const auto version = ranges.Version();
    const auto contains = [&](const auto& node) {
        return NativeNodeCurrent(node) && node->type == type && node->increment && handle >= node->cpu &&
            handle-node->cpu < uint64_t(node->count)*node->increment && (handle-node->cpu)%node->increment == 0;
    };
    for (const auto& hit : cache[index]) if (hit.version == version && contains(hit.node)) return hit.node;
    const auto interval = ranges.Find(handle);
    if (interval.matches != 1) return {};
    auto node = gNativeHeaps.Find(static_cast<ID3D12DescriptorHeap*>(interval.object));
    if (!node || node->id != interval.generation || !contains(node) || version != ranges.Version()) return {};
    cache[index][next[index]++%cache[index].size()] = {version,node}; return node;
}
std::shared_ptr<NativeResourceNode> NativeMetadataResource(ID3D12Resource* object)
{
    struct Cache { ID3D12Resource* object=nullptr; std::shared_ptr<NativeResourceNode> node; };
    static thread_local std::array<Cache,4> cache; static thread_local unsigned next=0;
    for (const auto& hit : cache) if (hit.object == object && NativeNodeMetadataCurrent(hit.node)) return hit.node;
    auto node=gNativeResources.Find(object); if (!NativeNodeMetadataCurrent(node)) return {};
    cache[next++%cache.size()]={object,node}; return node;
}
std::shared_ptr<NativeHeapNode> NativeMetadataHeapAtCpu(uint64_t handle,uint32_t type)
{
    if (type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV) return {};
    const auto index=type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ? 1u : 0u; auto& ranges=gNativeHeapRanges[index];
    struct Cache { uint64_t version=0; std::shared_ptr<NativeHeapNode> node; };
    static thread_local std::array<std::array<Cache,4>,2> cache; static thread_local std::array<unsigned,2> next {};
    const auto version=ranges.Version();
    const auto contains=[&](const auto& node) {
        return NativeNodeMetadataCurrent(node) && node->type == type && node->increment && handle >= node->cpu &&
            handle-node->cpu < uint64_t(node->count)*node->increment && (handle-node->cpu)%node->increment == 0;
    };
    for (const auto& hit : cache[index]) if (hit.version == version && contains(hit.node)) return hit.node;
    const auto interval=ranges.Find(handle); if (interval.matches != 1) return {};
    auto node=gNativeHeaps.Find(static_cast<ID3D12DescriptorHeap*>(interval.object));
    if (!node || node->id != interval.generation || !contains(node) || version != ranges.Version()) return {};
    cache[index][next[index]++%cache[index].size()]={version,node}; return node;
}
std::shared_ptr<NativeResourceNode> NativeMetadataBufferAtAddress(uint64_t address)
{
    const auto version = gNativeBuffers.Version();
    const auto interval = gNativeBuffers.Find(address);
    if (interval.matches != 1) return {};
    auto node = NativeMetadataResource(static_cast<ID3D12Resource*>(interval.object));
    if (!node || node->id != interval.generation || node->description.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER ||
        !node->address || address < node->address || address-node->address >= node->description.Width ||
        version != gNativeBuffers.Version()) return {};
    return node;
}
// The descriptor creator has a strong native resource argument. A cold proof is
// completed before the callback snapshot/slot locks; cached hits require full
// CacheAdmissible, including physical releases in flight and publication epoch.
std::shared_ptr<NativeResourceNode> NativeStrongResource(ID3D12Resource* object)
{
    if (!object) return {};
    if (auto node = NativeResource(object)) return node;
    PreparedResource prepared;
    if (!PrepareResourceMetadata(object,prepared)) return {};
    const auto birth = NrdBridgeNativeBirth::Prepare(object);
    if (!PublishResourceMetadata(prepared,birth)) return {};
    auto node = gNativeResources.Find(object);
    // This exact token was proven from a caller-owned native argument. A second
    // legal creator may publish while the elected instance is still initializing.
    return node && node->birth == birth && node->epoch == gNativeMetadataEpoch.load(std::memory_order_acquire) &&
        birth && birth->Live() && !birth->Failed() && NrdBridgeBirth::Healthy() ? node : std::shared_ptr<NativeResourceNode>{};
}
bool NativeViewFresh(const ViewInfo& view) noexcept
{
    if (!NativeNodeCurrent(view.heapOwner) || view.heapOwner->object != reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(view.descriptorHeap))) return false;
    const bool declaration = view.kind == D3D12_DESCRIPTOR_RANGE_TYPE_CBV && !view.object && !view.resource &&
        view.rootVa && !(view.rootVa%256) && view.constantBytes && !(view.constantBytes%256) && view.constantBytes <= 65536;
    if (declaration) return true;
    return NativeNodeCurrent(view.resourceOwner) && view.resourceOwner->object == view.object && view.resourceOwner->id == view.resource;
}
bool NativeViewMetadataFresh(const ViewInfo& view) noexcept
{
    if (!NativeNodeMetadataCurrent(view.heapOwner) ||
        view.heapOwner->object != reinterpret_cast<ID3D12DescriptorHeap*>(uintptr_t(view.descriptorHeap))) return false;
    const bool declaration=view.kind == D3D12_DESCRIPTOR_RANGE_TYPE_CBV && !view.object && !view.resource &&
        view.rootVa && !(view.rootVa%256) && view.constantBytes && !(view.constantBytes%256) && view.constantBytes <= 65536;
    return declaration || (NativeNodeMetadataCurrent(view.resourceOwner) &&
        view.resourceOwner->object == view.object && view.resourceOwner->id == view.resource);
}
void NativeEraseView(uint64_t handle)
{
    const auto found = gViews.find(handle); if (found == gViews.end()) return;
    const auto& old = found->second;
    if (old.resourceOwner && old.resourceOwner->handles) old.resourceOwner->handles->erase(handle);
    if (old.heapOwner && old.heapOwner->views) old.heapOwner->views->erase(handle);
    gViews.erase(found);
}
#ifdef FSRD_NRD_BRIDGE_TEST_HEAP_MASK
thread_local FrameSurveyMetadata::DescriptorLockTestHook gNativeViewPublishTestHook {};
#endif
void NativeReplaceView(const ViewInfo& view)
{
#ifdef FSRD_NRD_BRIDGE_TEST_HEAP_MASK
    if (gNativeViewPublishTestHook.attempt) gNativeViewPublishTestHook.attempt(gNativeViewPublishTestHook.state,&view);
#endif
    const auto found = gViews.find(view.descriptorCpu);
    if (found != gViews.end() && SameView(found->second,view)) return;
    NativeEraseView(view.descriptorCpu);
    if (view.resourceOwner && view.resourceOwner->handles) view.resourceOwner->handles->insert(view.descriptorCpu);
    if (view.heapOwner && view.heapOwner->views) view.heapOwner->views->insert(view.descriptorCpu);
#ifdef FSRD_NRD_BRIDGE_TEST
    if (gViewFailureAfterReverseForTesting.exchange(false)) throw std::bad_alloc();
#endif
    gViews.emplace(view.descriptorCpu,view);
}
bool FreshView(const ViewInfo& view, const Heap* heap)
{
    if (NativeTracking() && (!NativeViewFresh(view) || !heap || !view.heapOwner || view.heapOwner->birth != heap->birth)) return false;
    const auto resource = gResources.find(view.object);
    return heap && BirthAvailable(heap->birth,heap->object) && view.heapKnown &&
        view.descriptorHeap == uint64_t(reinterpret_cast<uintptr_t>(heap->object)) && resource != gResources.end() &&
        resource->second.id == view.resource && BirthAvailable(resource->second.birth,view.object);
}
// Descriptor contents remain current even while root/table binding tracking is closed.
// This intentionally spends CPU work on enabled-bridge copy metadata for correctness.
struct Range { uint32_t kind = 0, offset = 0, count = 0, shaderRegister = UINT_MAX, registerSpace = UINT_MAX; };
struct RootDescriptor
{
    uint32_t kind = 0, shaderRegister = UINT_MAX, registerSpace = UINT_MAX;
};
struct TextureRegisterMapping { UINT parameter = UINT_MAX; Range range; bool table = false; };
using TextureRegisterIndex = std::map<std::pair<uint32_t,uint32_t>,std::map<uint32_t,TextureRegisterMapping>>;
struct RootLayout
{
    std::string hash;
    std::map<uint32_t,std::vector<Range>> tables;
    std::set<uint32_t> computeTables, computeVisibleTables;
    std::map<uint32_t,RootDescriptor> computeDescriptors;
    std::set<uint32_t> pixelTables, pixelVisibleTables;
    std::map<uint32_t,RootDescriptor> pixelDescriptors;
    bool complete = false, directIndexed = false;
    TextureRegisterIndex computeTextureRegisters, pixelTextureRegisters;
    bool computeTextureRegistersComplete = false, pixelTextureRegistersComplete = false;
    NrdBridgeBirth::Token birth;
};
std::unordered_map<ID3D12RootSignature*,RootLayout> gRootLayouts;
struct PipelineMetadata { Json description; NrdBridgeBirth::Token birth; PipelineShaderIdentity identity; };
std::unordered_map<ID3D12PipelineState*,PipelineMetadata> gPipelineMetadata;
std::unordered_map<ID3D12CommandSignature*,IndirectSignatureInfo> gIndirectSignatures;
struct RootState
{
    uint64_t identity = 0;
    RootLayout layout;
    std::map<uint32_t,uint64_t> tables;
    std::map<uint32_t,std::pair<uint32_t,uint64_t>> views;
};
struct List
{
    uint64_t id = 0;
    bool resetObserved = false, closed = false, inRenderPass = false;
    // The last pass matched FrameSurveyPassHashes: its outputs are saved right after it (per-pass keys).
    bool targeted = false;
    uint64_t lastPass = 0;
    Json pso = Json::object(), passes = Json::array();
    RootState compute, graphics;
    std::vector<ID3D12DescriptorHeap*> heaps;
    std::vector<ViewInfo> targets, writes;
    std::vector<std::string> events;
    std::string marker;
    std::map<std::pair<uint64_t,uint32_t>,D3D12_RESOURCE_STATES> states;
    std::set<std::pair<uint64_t,uint32_t>> splitTransitions;
    std::shared_ptr<void> payload;
    std::map<std::string,uint64_t> copied;
};
struct Service
{
    FSRDGameTraceSession trace;
    ComPtr<ID3D12Device> device;
    IDXGISwapChain* swapchain = nullptr;
    bool requested = false, recording = false;
    uint64_t startTick = 0, candidateBytes = 0;
    uint32_t constantReads = 0;
    // Targeted mode keeps the window open (up to 8 Presents) until a listed pass is saved: with frame
    // generation a Present-to-Present interval can hold only the interpolated frame's work.
    uint32_t targetedCopies = 0, presents = 0;
    Json manifest;
    std::map<uint64_t,Json> resources;
    std::unordered_map<ID3D12GraphicsCommandList*,List> lists;
    std::set<std::pair<uint64_t,uint32_t>> candidates;
};
std::unique_ptr<Service> gService;
ComPtr<ID3D12Device> gCreationDevice;
bool Recording() { return Enabled() && gRecording.load(std::memory_order_acquire) && !gInternal && gMetadataHealthy.load(std::memory_order_acquire); }
void Fail(const char* reason) noexcept
{
    InternalScope internal; // Recorder-owned cleanup must never upgrade a title-resource borrow.
    try
    {
        std::scoped_lock lock(gRecordMutex);
        gRecording.store(false,std::memory_order_release);
        gStatus.phase = "error"; gStatus.message = reason; gStatus.active = false;
        if (gService)
        {
            gService->recording = gService->requested = false;
            gService->trace.Abort(reason);
        }
        LOG_ERROR("[FRAME_SURVEY] {}",reason);
    } catch (...) {}
}
void MetadataFailed(const char* reason) noexcept
{
    gMetadataHealthy.store(false,std::memory_order_release);
    if (NrdBridgeBirth::InMetadataScope())
    {
        const char* empty = nullptr; gDeferredMetadataFailure.compare_exchange_strong(empty,reason,std::memory_order_release);
        return; // Fail may destroy recorder-owned COM; defer until every Birth guard is gone.
    }
    Fail(reason);
}
void Count(const char* reason)
{
    auto& value = gService->manifest["coverage_gaps"][reason];
    if (value.is_null()) value = uint64_t(0);
    value = value.get<uint64_t>()+1;
}
struct ResourceDescription
{
    D3D12_RESOURCE_DESC desc {};
    uint64_t va = 0;
};
Resource& Register(ID3D12Resource* resource, const ResourceDescription* prepared = nullptr)
{
    auto& result = gResources[resource];
    if (!result.id)
    {
        if (!prepared) throw std::logic_error("Resource description was not prepared outside the metadata catalog");
        result.id = ++gNextResource; result.object = resource; result.desc = prepared->desc;
        if (result.desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER)
        {
            result.va = prepared->va;
            if (result.va)
            {
                gAddresses[result.va] = resource;
                gBufferAddresses.Insert(result.va,result.desc.Width,result.id,resource);
            }
        }
    }
    return result;
}
// Only the rare first observation performs COM work. No registry or descriptor
// shard is held during native description lookup; physical Release is excluded.
void PublishNativeResource(Resource& resource)
{
    if (!NativeTracking()) return;
    const auto epoch = gNativeMetadataEpoch.load(std::memory_order_acquire);
    if (auto old = gNativeResources.Find(resource.object))
    {
        if (old->birth != resource.birth || old->id != resource.id || old->epoch != epoch)
            throw std::logic_error("Native resource publication would replace another identity");
        return;
    }
    auto node = std::make_shared<NativeResourceNode>();
    node->object = resource.object; node->id = resource.id; node->epoch = epoch;
    node->address = resource.va; node->description = resource.desc; node->birth = resource.birth;
    node->handles = resource.handles.Share();
    if (gNativeResources.Insert(resource.object,node) != node) throw std::logic_error("Native resource publication raced another node");
    if (resource.desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER && resource.va)
        gNativeBuffers.Insert(resource.va,resource.desc.Width,resource.id,resource.object);
}
void PublishNativeHeap(Heap& heap)
{
    if (!NativeTracking()) return;
    const auto epoch = gNativeMetadataEpoch.load(std::memory_order_acquire);
    if (auto old = gNativeHeaps.Find(heap.object))
    {
        if (old->birth != heap.birth || old->epoch != epoch)
            throw std::logic_error("Native heap publication would replace another identity");
        return;
    }
    auto node = std::make_shared<NativeHeapNode>(HeapDescriptorShards(heap.cpu,heap.count,heap.increment,heap.type));
    node->object = heap.object; node->id = ++gNextNativeHeap; node->epoch = epoch;
    node->cpu = heap.cpu; node->gpu = heap.gpu; node->count = heap.count; node->increment = heap.increment;
    node->type = heap.type; node->birth = heap.birth; node->views = heap.views.Share();
    if (!node->id || gNativeHeaps.Insert(heap.object,node) != node) throw std::logic_error("Native heap publication raced another node");
    if (heap.type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || heap.type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV)
        gNativeHeapRanges[heap.type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ? 1 : 0].Insert(heap.cpu,uint64_t(heap.count)*heap.increment,node->id,heap.object);
}
NrdBridgeBirth::Token EnsureResourceRegistered(ID3D12Resource* object)
{
    if (!object) return {};
    {
        std::shared_lock catalog(gLifetimeMutex);
        const auto found = gResources.find(object);
        if (found != gResources.end() && found->second.id && BirthAvailable(found->second.birth,object)) return found->second.birth;
    }
    if (NativeTracking())
    {
        PreparedResource prepared;
        if (!PrepareResourceMetadata(object,prepared)) throw std::runtime_error("Native resource metadata preparation failed");
        const auto birth = NrdBridgeNativeBirth::Prepare(object);
        if (!PublishResourceMetadata(prepared,birth)) throw std::runtime_error("Current resource metadata publication failed");
        return birth;
    }
    NrdBridgeLifetime::ScopedBorrow borrow;
    if (!borrow.Acquired()) throw std::runtime_error("Resource metadata lifetime borrow was denied");
    ResourceDescription description; description.desc = object->GetDesc();
    if (description.desc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER) description.va = object->GetGPUVirtualAddress();
    std::scoped_lock catalog(gLifetimeMutex); MetadataMutation mutation;
    return Register(object,&description).birth; // Rechecks a competing first observation under the exclusive catalog.
}
std::string DebugName(ID3D12Resource* object)
{
    UINT bytes = 0;
    if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectNameW,&bytes,nullptr)) && bytes && bytes <= 8192)
    {
        std::vector<wchar_t> words((bytes+1)/2+1,L'\0');
        if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectNameW,&bytes,words.data())))
            return FrameSurveyMetadata::DecodeMarker(1,words.data(),bytes).first;
    }
    bytes = 0;
    if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectName,&bytes,nullptr)) && bytes && bytes <= 4096)
    {
        std::vector<char> words(bytes+1,0);
        if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectName,&bytes,words.data())))
            return FrameSurveyMetadata::DecodeMarker(0,words.data(),bytes).first;
    }
    return {};
}
// A recorder description contains no reverse owner. Gather it under the catalog,
// then perform DebugName/retains only after every metadata scope has closed.
struct RecorderResource
{
    uint64_t id=0,heap=0,offset=0,va=0;
    ID3D12Resource* object=nullptr;
    D3D12_RESOURCE_DESC desc {};
    D3D12_RESOURCE_STATES initial=D3D12_RESOURCE_STATE_COMMON;
    bool initialKnown=false;
};
RecorderResource RecorderDescription(const Resource& resource) noexcept
{ return {resource.id,resource.heap,resource.offset,resource.va,resource.object,resource.desc,resource.initial,resource.initialKnown}; }
void Describe(const RecorderResource& resource)
{
    if (gService->resources.contains(resource.id)) return;
    const auto& d = resource.desc;
    gService->resources[resource.id] = {{"id",resource.id},{"pointer",uint64_t(reinterpret_cast<uintptr_t>(resource.object))},
        {"debug_name",DebugName(resource.object)},{"dimension",uint32_t(d.Dimension)},
        {"width",d.Width},{"height",d.Height},{"array_size",d.DepthOrArraySize},{"mip_levels",d.MipLevels},
        {"format",uint32_t(d.Format)},{"flags",uint32_t(d.Flags)},{"samples",d.SampleDesc.Count},
        {"heap_pointer",resource.heap},{"heap_offset",resource.offset},{"gpu_va",resource.va},
        {"initial_state_known",resource.initialKnown},{"initial_state",uint32_t(resource.initial)}};
}
// Creation-only validation. Keep the recorder's original range walk, while marking only finite,
// compute-visible tables with unique descriptor and register intervals eligible for bridge proof.
bool UnambiguousComputeRanges(const std::vector<Range>& ranges)
{
    if (ranges.empty()) return false;
    constexpr uint64_t endLimit = uint64_t(UINT_MAX)+1;
    for (const auto& range : ranges)
        if (range.kind > D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER || !range.count || range.count == UINT_MAX ||
            uint64_t(range.offset)+range.count > endLimit || uint64_t(range.shaderRegister)+range.count > endLimit) return false;
    if (ranges.size() == 1) return true;
    auto ordered = ranges;
    std::sort(ordered.begin(),ordered.end(),[](const auto& a,const auto& b) { return a.offset < b.offset; });
    for (size_t i=1;i<ordered.size();++i)
        if (uint64_t(ordered[i-1].offset)+ordered[i-1].count > ordered[i].offset) return false;
    std::sort(ordered.begin(),ordered.end(),[](const auto& a,const auto& b) {
        return std::tie(a.kind,a.registerSpace,a.shaderRegister) < std::tie(b.kind,b.registerSpace,b.shaderRegister); });
    for (size_t i=1;i<ordered.size();++i)
        if (ordered[i-1].kind == ordered[i].kind && ordered[i-1].registerSpace == ordered[i].registerSpace &&
            uint64_t(ordered[i-1].shaderRegister)+ordered[i-1].count > ordered[i].shaderRegister) return false;
    return true;
}
bool ValidComputeRange(const Range& range)
{
    if (range.kind > D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER || !range.count) return false;
    // UINT_MAX is the D3D12 unbounded sentinel, not an interval to add to a base register.
    return range.count == UINT_MAX || (uint64_t(range.offset)+range.count <= uint64_t(UINT_MAX)+1 &&
        uint64_t(range.shaderRegister)+range.count <= uint64_t(UINT_MAX)+1);
}
bool UniqueComputeMapping(const std::vector<Range>& ranges, const ComputeTableRequest& request)
{
    const Range* match = nullptr;
    UINT registerMappings = 0;
    for (const auto& range : ranges)
    {
        if (!ValidComputeRange(range)) return false;
        const bool atOffset = request.descriptorOffset >= range.offset &&
            (range.count == UINT_MAX || uint64_t(request.descriptorOffset)-range.offset < range.count);
        if (atOffset)
        {
            if (match) return false;
            match = &range;
        }
        if (range.kind == uint32_t(request.kind) && range.registerSpace == request.registerSpace &&
            request.shaderRegister >= range.shaderRegister &&
            (range.count == UINT_MAX || uint64_t(request.shaderRegister)-range.shaderRegister < range.count)) ++registerMappings;
    }
    return match && registerMappings == 1 && match->kind == uint32_t(request.kind) &&
        match->registerSpace == request.registerSpace &&
        uint64_t(match->shaderRegister)+request.descriptorOffset-match->offset == request.shaderRegister;
}
bool BuildTextureRegisterIndex(const RootLayout& layout, bool pixel, TextureRegisterIndex& out)
{
    out.clear();
    const auto add = [&](UINT parameter, const Range& range, bool table) {
        if (range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV && range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV) return true;
        if (!ValidComputeRange(range)) return false;
        auto& group = out[{range.kind,range.registerSpace}];
        const auto after = group.lower_bound(range.shaderRegister);
        const uint64_t end = range.count == UINT_MAX ? uint64_t(UINT_MAX)+1 : uint64_t(range.shaderRegister)+range.count;
        if (after != group.end() && after->first < end) return false;
        if (after != group.begin())
        {
            const auto& previous = std::prev(after)->second.range;
            const uint64_t previousEnd = previous.count == UINT_MAX ? uint64_t(UINT_MAX)+1 : uint64_t(previous.shaderRegister)+previous.count;
            if (previousEnd > range.shaderRegister) return false;
        }
        group.emplace_hint(after,range.shaderRegister,TextureRegisterMapping{parameter,range,table}); return true;
    };
    for (const auto parameter : pixel ? layout.pixelVisibleTables : layout.computeVisibleTables)
    {
        const auto table = layout.tables.find(parameter);
        if (table == layout.tables.end()) return false;
        std::map<uint32_t,uint64_t> occupied;
        for (const auto& range : table->second)
        {
            if (!ValidComputeRange(range)) return false;
            const auto after = occupied.lower_bound(range.offset);
            const uint64_t end = range.count == UINT_MAX ? uint64_t(UINT_MAX)+1 : uint64_t(range.offset)+range.count;
            if ((after != occupied.end() && after->first < end) ||
                (after != occupied.begin() && std::prev(after)->second > range.offset) || !add(parameter,range,true)) return false;
            occupied.emplace_hint(after,range.offset,end);
        }
    }
    for (const auto& [parameter,descriptor] : pixel ? layout.pixelDescriptors : layout.computeDescriptors)
        if (!add(parameter,{descriptor.kind,0,1,descriptor.shaderRegister,descriptor.registerSpace},false)) return false;
    return layout.complete;
}
void BuildTextureRegisterIndexes(RootLayout& layout)
{
    layout.computeTextureRegistersComplete = BuildTextureRegisterIndex(layout,false,layout.computeTextureRegisters);
    layout.pixelTextureRegistersComplete = BuildTextureRegisterIndex(layout,true,layout.pixelTextureRegisters);
}
bool FindTextureRegisterMapping(const RootLayout& layout, bool pixel, const ComputeTableRequest& request,
    UINT& parameter, UINT& offset)
{
    if (!(pixel ? layout.pixelTextureRegistersComplete : layout.computeTextureRegistersComplete)) return false;
    const auto& index = pixel ? layout.pixelTextureRegisters : layout.computeTextureRegisters;
    const auto group = index.find({uint32_t(request.kind),request.registerSpace});
    if (group == index.end()) return false;
    auto after = group->second.upper_bound(request.shaderRegister);
    if (after == group->second.begin()) return false;
    const auto& mapping = std::prev(after)->second; const auto& range = mapping.range;
    if (!mapping.table || request.shaderRegister < range.shaderRegister ||
        (range.count != UINT_MAX && uint64_t(request.shaderRegister)-range.shaderRegister >= range.count)) return false;
    const uint64_t derived = uint64_t(range.offset)+request.shaderRegister-range.shaderRegister;
    if (derived > UINT_MAX) return false;
    parameter = mapping.parameter; offset = UINT(derived); return true;
}
RootLayout ReadRoot(ID3D12RootSignature* root)
{
    RootLayout result; if (!root) return result;
    UINT length = 0;
    if (FAILED(root->GetPrivateData(RootBlobId,&length,nullptr)) || !length || length > (1u<<20)) return result;
    std::vector<uint8_t> blob(length);
    if (FAILED(root->GetPrivateData(RootBlobId,&length,blob.data()))) return result;
    ComPtr<ID3D12VersionedRootSignatureDeserializer> decoder;
    auto deserialize = D3d12Proxy::D3D12CreateVersionedRootSignatureDeserializer_();
    if (!deserialize || FAILED(deserialize(blob.data(),blob.size(),IID_PPV_ARGS(&decoder)))) return result;
    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* desc = nullptr;
    if (FAILED(decoder->GetRootSignatureDescAtVersion(D3D_ROOT_SIGNATURE_VERSION_1_1,&desc))) return result;
    ComPtr<ID3DBlob> canonical, errors;
    auto serialize = D3d12Proxy::D3D12SerializeVersionedRootSignature_();
    if (!serialize || FAILED(serialize(desc,&canonical,&errors))) return result;
    result.hash = RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(canonical->GetBufferPointer()),canonical->GetBufferSize()});
    result.complete = true;
    // Numeric bits are available even when compiling with an older D3D12 SDK.
    result.directIndexed = (uint32_t(desc->Desc_1_1.Flags)&0x400) != 0;
    for (UINT i=0;i<desc->Desc_1_1.NumParameters;++i)
    {
        const auto& param = desc->Desc_1_1.pParameters[i];
        const bool pixelVisible = !(desc->Desc_1_1.Flags&D3D12_ROOT_SIGNATURE_FLAG_DENY_PIXEL_SHADER_ROOT_ACCESS) &&
            (param.ShaderVisibility == D3D12_SHADER_VISIBILITY_ALL || param.ShaderVisibility == D3D12_SHADER_VISIBILITY_PIXEL);
        if (param.ParameterType != D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE)
        {
            if ((param.ShaderVisibility == D3D12_SHADER_VISIBILITY_ALL || pixelVisible) &&
                (param.ParameterType == D3D12_ROOT_PARAMETER_TYPE_CBV || param.ParameterType == D3D12_ROOT_PARAMETER_TYPE_SRV ||
                 param.ParameterType == D3D12_ROOT_PARAMETER_TYPE_UAV))
            {
                const auto kind = param.ParameterType == D3D12_ROOT_PARAMETER_TYPE_CBV ? D3D12_DESCRIPTOR_RANGE_TYPE_CBV :
                    param.ParameterType == D3D12_ROOT_PARAMETER_TYPE_SRV ? D3D12_DESCRIPTOR_RANGE_TYPE_SRV : D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
                const RootDescriptor descriptor {uint32_t(kind),param.Descriptor.ShaderRegister,param.Descriptor.RegisterSpace};
                if (param.ShaderVisibility == D3D12_SHADER_VISIBILITY_ALL) result.computeDescriptors[i] = descriptor;
                if (pixelVisible) result.pixelDescriptors[i] = descriptor;
            }
            continue;
        }
        if (param.ShaderVisibility == D3D12_SHADER_VISIBILITY_ALL) result.computeVisibleTables.insert(i);
        if (pixelVisible) result.pixelVisibleTables.insert(i);
        uint64_t offset = 0;
        for (UINT j=0;j<param.DescriptorTable.NumDescriptorRanges;++j)
        {
            const auto& range = param.DescriptorTable.pDescriptorRanges[j];
            const uint64_t start = range.OffsetInDescriptorsFromTableStart == D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND ? offset :
                range.OffsetInDescriptorsFromTableStart;
            if (start > UINT_MAX) { result.complete = false; break; }
            result.tables[i].push_back({uint32_t(range.RangeType),uint32_t(start),range.NumDescriptors,range.BaseShaderRegister,range.RegisterSpace});
            offset = start+range.NumDescriptors;
        }
        if (param.ShaderVisibility == D3D12_SHADER_VISIBILITY_ALL && UnambiguousComputeRanges(result.tables[i]))
            result.computeTables.insert(i);
        if (pixelVisible && UnambiguousComputeRanges(result.tables[i])) result.pixelTables.insert(i);
    }
    BuildTextureRegisterIndexes(result);
    return result;
}
Json ReadPipeline(ID3D12PipelineState* pso)
{
    Json result = {{"pointer",uint64_t(reinterpret_cast<uintptr_t>(pso))},{"shader_hashes",Json::object()},
        {"hash_known",false}};
    if (!pso) return result;
    UINT length = 0;
    if (SUCCEEDED(pso->GetPrivateData(PipelineId,&length,nullptr)) && length && length < 65536)
    {
        std::string text(length,'\0');
        if (SUCCEEDED(pso->GetPrivateData(PipelineId,&length,text.data()))) result.update(Json::parse(text));
    }
    return result;
}
// Binding state of every command list, kept while tracking. Lists reset before the recorded Present
// (Cyberpunk records its async compute list early) otherwise have no root layout, tables or pipeline.
struct Mirror
{
    struct Root
    {
        ID3D12RootSignature* object = nullptr;
        std::map<uint32_t,uint64_t> tables;
        std::map<uint32_t,std::pair<uint32_t,uint64_t>> views;
        NrdBridgeBirth::Token birth;
    };
    ID3D12PipelineState* pso = nullptr;
    Root compute, graphics;
    std::vector<ID3D12DescriptorHeap*> heaps;
    NrdBridgeBirth::Token receiverBirth, pipelineBirth;
    std::vector<NrdBridgeBirth::Token> heapBirths;
};
FrameSurveyMetadata::MetadataMutex<std::mutex,FrameSurveyMetadata::MetadataLock::Mirror> gMirrorMutex;
std::unordered_map<ID3D12GraphicsCommandList*,Mirror> gMirror;
std::unordered_map<void*,std::unordered_set<ID3D12GraphicsCommandList*>> gMirrorOwners;
std::unordered_map<ID3D12PipelineState*,NrdBridgeBirth::Token> gPipelineBirths;
struct RetiredMetadata
{
    decltype(gResources)::node_type resource;
    decltype(gHeaps)::node_type heap;
    decltype(gRootLayouts)::node_type root;
    decltype(gPipelineMetadata)::node_type pipeline;
    decltype(gIndirectSignatures)::node_type signature;
    decltype(gMirror)::node_type list;
    decltype(gMirrorOwners)::node_type references;
    std::shared_ptr<NativeResourceNode> nativeResource;
    std::shared_ptr<NativeHeapNode> nativeHeap;
};
NrdBridgeBirth::Token ReceiverBirth(ID3D12GraphicsCommandList* cmd)
{
    if (!NativeTracking()) return {};
    if (NrdBridgeBirth::InMetadataScope()) return NrdBridgeBirth::Capture(cmd);
    return NrdBridgeNativeBirth::ObserveReleaseCoverage(cmd) ? NrdBridgeNativeBirth::Receiver(cmd) : NrdBridgeBirth::Token{};
}
bool MirrorAvailable(const Mirror& mirror, ID3D12GraphicsCommandList* cmd)
{
    if (!BirthAvailable(mirror.receiverBirth,cmd) || !BirthAvailable(mirror.compute.birth,mirror.compute.object)) return false;
    if (mirror.pso && !BirthAvailable(mirror.pipelineBirth,mirror.pso)) return false;
    if (mirror.heapBirths.empty() && !NativeTracking()) return true;
    if (mirror.heapBirths.size() != mirror.heaps.size()) return false;
    for (size_t i=0;i<mirror.heaps.size();++i) if (!BirthAvailable(mirror.heapBirths[i],mirror.heaps[i])) return false;
    return true;
}
struct MirrorReferences
{
    std::array<void*,5> objects {}; size_t count = 0;
    bool Contains(void* object) const { return std::find(objects.begin(),objects.begin()+count,object) != objects.begin()+count; }
    void Add(void* object)
    {
        if (!object || Contains(object)) return;
        if (count == objects.size()) throw std::runtime_error("More than two shader-visible heaps in a native binding");
        objects[count++] = object;
    }
    explicit MirrorReferences(const Mirror& mirror)
    {
        Add(mirror.pso); Add(mirror.compute.object); Add(mirror.graphics.object);
        for (auto* heap : mirror.heaps) Add(heap);
    }
};
// Caller holds gMirrorMutex. Touch only the objects referenced by this list.
void UpdateMirrorOwners(ID3D12GraphicsCommandList* cmd, const MirrorReferences& before, const MirrorReferences& after)
{
    for (size_t i=0;i<before.count;++i) if (!after.Contains(before.objects[i]))
        if (const auto owner = gMirrorOwners.find(before.objects[i]); owner != gMirrorOwners.end())
        { owner->second.erase(cmd); if (owner->second.empty()) gMirrorOwners.erase(owner); }
    for (size_t i=0;i<after.count;++i) if (!before.Contains(after.objects[i])) gMirrorOwners[after.objects[i]].insert(cmd);
}
template<class Update> void Mirrored(ID3D12GraphicsCommandList* cmd, Update&& update, bool references = false) noexcept
{
    if (!BindingTracking() || gInternal || !cmd) return;
    try
    {
        const auto receiver = ReceiverBirth(cmd);
        NrdBridgeBirth::CurrentGuard current(receiver);
        if (receiver ? (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy()) : NativeTracking()) return;
        NativeSnapshotShared snapshot; if (!BindingTracking()) return;
        std::scoped_lock lock(gMirrorMutex); MetadataMutation mutation; auto& mirror = gMirror[cmd];
        const MirrorReferences before(mirror);
        const bool changedReceiver = mirror.receiverBirth != receiver;
        if (changedReceiver) mirror = {};
        mirror.receiverBirth = receiver; update(mirror);
        if (references || changedReceiver) UpdateMirrorOwners(cmd,before,MirrorReferences(mirror));
    }
    catch (...) { MetadataFailed("Binding mirror allocation failed"); }
}
bool PublishPipelineBirth(ID3D12PipelineState* pso)
{
    if (!NativeTracking()) return true;
    if (!NrdBridgeNativeBirth::ObserveReleaseCoverage(pso)) return false;
    const auto birth = NrdBridgeNativeBirth::Prepare(pso);
    NrdBridgeBirth::CurrentGuard current(birth);
    if (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy()) return false;
    NativeSnapshotShared snapshot; if (!Tracking()) return false;
    std::scoped_lock catalog(gLifetimeMutex); MetadataMutation mutation; gPipelineBirths[pso] = birth; return true;
}
PipelineShaderIdentity PipelineIdentity(ID3D12PipelineState* pso, const Json& description)
{
    PipelineShaderIdentity result; result.pipeline = pso;
    if (!description.value("hash_known",false) ||
        (description.contains("stream_parse_hresult") && FAILED(HRESULT(description["stream_parse_hresult"].get<int64_t>())))) return result;
    const auto& hashes = description.at("shader_hashes");
    if (!hashes.is_object()) return result;
    const auto add = [&](const char* name, uint32_t bit, std::array<char,65>* target) {
        if (!hashes.contains(name)) return true;
        if (!hashes[name].is_string()) return false;
        const auto& hash = hashes[name].get_ref<const std::string&>();
        if (hash.size() != 64 || !std::all_of(hash.begin(),hash.end(),[](char c) {
            return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); })) return false;
        if (target) std::copy(hash.begin(),hash.end(),target->begin());
        result.presentStages |= bit; return true;
    };
    if (!add("CS",PipelineCS,&result.compute) || !add("VS",PipelineVS,&result.vertex) ||
        !add("PS",PipelinePS,&result.pixel) || !add("HS",PipelineHS,nullptr) ||
        !add("DS",PipelineDS,nullptr) || !add("GS",PipelineGS,nullptr)) return result;
    // The complete native legacy descriptor or successful stream parser proves
    // absent stages. Unsupported stream subobjects make the parser fail above.
    result.complete = result.presentStages == PipelineCS ||
        (!(result.presentStages&PipelineCS) && (result.presentStages&PipelineVS));
    return result;
}
void StorePipelineMetadata(ID3D12PipelineState* pso, const std::string& text)
{
    auto description = Json::parse(text); auto identity = PipelineIdentity(pso,description); NrdBridgeBirth::Token birth;
    { std::shared_lock catalog(gLifetimeMutex); if (const auto found = gPipelineBirths.find(pso); found != gPipelineBirths.end()) birth = found->second; }
    NrdBridgeBirth::CurrentGuard current(birth);
    if (birth && (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy())) return;
    NativeSnapshotShared snapshot; if (!Tracking()) return;
    identity.pipelineBirth = birth;
    std::scoped_lock catalog(gLifetimeMutex); MetadataMutation mutation; gPipelineMetadata[pso] = {std::move(description),birth,std::move(identity)};
}
bool Seed(ID3D12GraphicsCommandList* cmd, List& list)
{
    NativeSnapshotExclusive metadataSnapshot;
    if (!gMetadataHealthy.load(std::memory_order_acquire) || !Recording()) return false;
    Mirror mirror;
    {
        std::scoped_lock lock(gMirrorMutex);
        const auto found = gMirror.find(cmd);
        if (found == gMirror.end()) return false;
        mirror = found->second;
    }
    if (!MirrorAvailable(mirror,cmd)) return false;
    std::shared_lock catalog(gLifetimeMutex);
    list.pso = {{"pointer",uint64_t(reinterpret_cast<uintptr_t>(mirror.pso))},{"shader_hashes",Json::object()},{"hash_known",false}};
    if (const auto pso = gPipelineMetadata.find(mirror.pso); pso != gPipelineMetadata.end() && pso->second.birth == mirror.pipelineBirth)
        list.pso.update(pso->second.description);
    auto seed = [](RootState& state, const Mirror::Root& root) {
        if (!root.object) return;
        const auto layout = gRootLayouts.find(root.object);
        if (layout == gRootLayouts.end() || layout->second.birth != root.birth || !BirthAvailable(root.birth,root.object)) return;
        state.identity = uint64_t(reinterpret_cast<uintptr_t>(root.object)); state.layout = layout->second;
        state.tables = root.tables; state.views = root.views; };
    seed(list.compute,mirror.compute); seed(list.graphics,mirror.graphics);
    list.heaps = mirror.heaps;
    return true;
}
List& GetList(ID3D12GraphicsCommandList* cmd)
{
    auto& state = gService->lists[cmd];
    if (!state.id)
    {
        state.id = ++gNextList; Count("list_without_observed_reset");
        if (Seed(cmd,state)) Count("list_bindings_seeded_from_tracking");
    }
    return state;
}
// Caller holds gLifetimeMutex. Cached creation descriptions avoid any COM call or title retain.
// Query live buffer intervals without scanning the title's texture/descriptor registry.
// The interval index retains overlapping placed buffers and rejects ambiguous addresses.
bool ResolveBufferAddress(uint64_t address, uint64_t declaredBytes, uint64_t minimumBytes, BoundConstantBuffer& out,
    ConstantBufferDiagnostic* diagnostic = nullptr)
{
    out = {};
    const auto fail = [&](const char* reason) { if (diagnostic) diagnostic->reason = reason; return false; };
    if (diagnostic) { diagnostic->address = address; diagnostic->declaredBytes = declaredBytes; diagnostic->trackedBuffers = gBufferAddresses.Size(); }
    if (!address || address%256 || !minimumBytes || minimumBytes > 65536 ||
        (declaredBytes && (declaredBytes%256 || declaredBytes > 65536))) return fail("CBV address/size alignment is invalid");
    const auto interval = gBufferAddresses.Find(address);
    if (diagnostic) diagnostic->intervalMatches = interval.matches;
    if (interval.matches != 1) return fail(interval.matches ? "CBV GPU address overlaps live buffers" : "CBV GPU address has no tracked buffer");
    const auto found = gResources.find(static_cast<ID3D12Resource*>(interval.object));
    if (found == gResources.end() || found->second.id != interval.generation || !BirthAvailable(found->second.birth,found->first)) return fail("CBV buffer generation is stale");
    const auto* match = &found->second;
    if (match->desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER || !match->va || address < match->va ||
        address-match->va >= match->desc.Width) return fail("CBV GPU address is outside its tracked buffer");
    const uint64_t offset = address-match->va, remaining = match->desc.Width-offset;
    if (diagnostic) { diagnostic->resourceBase = match->va; diagnostic->remainingBytes = remaining; }
    const uint64_t bytes = declaredBytes ? declaredBytes : std::min<uint64_t>(65536,remaining);
    if (bytes > remaining || bytes < minimumBytes) return fail("CBV byte range does not cover the requested field");
    out = {match->object,address,offset,bytes,match->id}; out.resourceBirth = match->birth; return true;
}
// Native hot writers use pinned immutable metadata. Every structural lookup
// finishes before slot locking, then exact birth/epoch/range proofs are rechecked
// inside the slot. No catalog, COM, Birth guard or callback is entered there.
void NativeStoreResourceView(ID3D12Resource* object, uint64_t handle, uint32_t kind, DXGI_FORMAT format,
    uint32_t mip, uint32_t slice, bool supported, bool texture2D)
{
    auto resource = NativeStrongResource(object);
    const auto type = kind == 4 ? D3D12_DESCRIPTOR_HEAP_TYPE_RTV : D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    auto& ranges = gNativeHeapRanges[type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ? 1 : 0];
    NativeSnapshotShared snapshot; if (!Tracking()) return;
    for (unsigned attempt=0;attempt<8;++attempt)
    {
        const auto version=ranges.Version(); auto heap=NativeMetadataHeapAtCpu(handle,type);
        std::scoped_lock slot(gViewMutexes[FrameSurveyMetadata::DescriptorShard(handle)]); MetadataMutation mutation;
        if (version != ranges.Version()) continue; // Retry unrelated heap changes without a false tombstone.
        const bool strong = resource && resource->epoch == gNativeMetadataEpoch.load(std::memory_order_acquire) &&
            resource->birth && resource->birth->Live() && !resource->birth->Failed() && NrdBridgeBirth::Healthy();
        if (!object || !strong || !NativeNodeMetadataCurrent(heap)) { NativeEraseView(handle); return; }
        ViewInfo view {object,resource->id,kind,uint32_t(format == DXGI_FORMAT_UNKNOWN ? resource->description.Format : format),
            mip+slice*resource->description.MipLevels,supported};
        view.texture2D = texture2D && resource->description.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
            resource->description.DepthOrArraySize == 1 && resource->description.SampleDesc.Count == 1;
        view.descriptorCpu=handle; view.descriptorHeap=uint64_t(reinterpret_cast<uintptr_t>(heap->object)); view.heapKnown=true;
        view.resourceOwner=std::move(resource); view.heapOwner=std::move(heap); NativeReplaceView(view); return;
    }
    std::scoped_lock slot(gViewMutexes[FrameSurveyMetadata::DescriptorShard(handle)]); NativeEraseView(handle);
}
void NativeStoreConstantView(uint64_t handle, const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc)
{
    const auto bufferVersion=gNativeBuffers.Version();
    const bool declared=desc && desc->BufferLocation && !(desc->BufferLocation%256) && desc->SizeInBytes &&
        !(desc->SizeInBytes%256) && desc->SizeInBytes <= 65536;
    auto resource=declared ? NativeMetadataBufferAtAddress(desc->BufferLocation) : std::shared_ptr<NativeResourceNode>{};
    NativeSnapshotShared snapshot; if (!Tracking()) return;
    for (unsigned attempt=0;attempt<8;++attempt)
    {
        const auto heapVersion=gNativeHeapRanges[0].Version(); auto heap=NativeMetadataHeapAtCpu(handle,D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        std::scoped_lock slot(gViewMutexes[FrameSurveyMetadata::DescriptorShard(handle)]); MetadataMutation mutation;
        if (heapVersion != gNativeHeapRanges[0].Version()) continue;
        if (!declared || !NativeNodeMetadataCurrent(heap)) { NativeEraseView(handle); return; }
        // A VA/size declaration remains useful when diagnostic ownership is
        // unknown/ambiguous. Native b6 admission never requires that ownership.
        if (!NativeNodeMetadataCurrent(resource) || bufferVersion != gNativeBuffers.Version() ||
            desc->BufferLocation < resource->address || desc->BufferLocation-resource->address >= resource->description.Width ||
            desc->SizeInBytes > resource->description.Width-(desc->BufferLocation-resource->address)) resource.reset();
        ViewInfo view {resource ? resource->object : nullptr,resource ? resource->id : 0,
            D3D12_DESCRIPTOR_RANGE_TYPE_CBV,uint32_t(DXGI_FORMAT_UNKNOWN),0,false};
        view.descriptorCpu=handle; view.rootVa=desc->BufferLocation; view.constantBytes=desc->SizeInBytes;
        view.descriptorHeap=uint64_t(reinterpret_cast<uintptr_t>(heap->object)); view.heapKnown=true;
        view.resourceOwner=std::move(resource); view.heapOwner=std::move(heap); NativeReplaceView(view); return;
    }
    std::scoped_lock slot(gViewMutexes[FrameSurveyMetadata::DescriptorShard(handle)]); NativeEraseView(handle);
}
void NativeCopyDescriptors(UINT stride, UINT nd, const D3D12_CPU_DESCRIPTOR_HANDLE* dst, const UINT* dn,
    UINT ns, const D3D12_CPU_DESCRIPTOR_HANDLE* src, const UINT* sn, D3D12_DESCRIPTOR_HEAP_TYPE type)
{
    if (!stride) throw std::logic_error("Descriptor copy stride is zero");
    auto& ranges = gNativeHeapRanges[type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ? 1 : 0];
    NativeSnapshotShared snapshot; if (!Tracking()) return;
    MetadataMutation mutation;
    UINT di=0,si=0,d=0,s=0;
    while (di<nd && si<ns)
    {
        const UINT dc=dn ? dn[di] : 1, sc=sn ? sn[si] : 1;
        if (d>=dc) { ++di; d=0; continue; }
        if (s>=sc) { ++si; s=0; continue; }
        const uint64_t destinationDelta=uint64_t(d)*stride, sourceDelta=uint64_t(s)*stride;
        if (destinationDelta>UINT64_MAX-dst[di].ptr || sourceDelta>UINT64_MAX-src[si].ptr)
            throw std::logic_error("Descriptor copy handle overflow");
        const uint64_t dh0=dst[di].ptr+destinationDelta, sh0=src[si].ptr+sourceDelta;
        auto version=ranges.Version();
        auto destinationHeap=NativeMetadataHeapAtCpu(dh0,type), sourceHeap=NativeMetadataHeapAtCpu(sh0,type);
        UINT count=std::min(dc-d,sc-s);
        if (destinationHeap && destinationHeap->increment == stride)
            count=std::min(count,destinationHeap->count-UINT((dh0-destinationHeap->cpu)/stride));
        else count=1;
        if (sourceHeap && sourceHeap->increment == stride)
            count=std::min(count,sourceHeap->count-UINT((sh0-sourceHeap->cpu)/stride));
        else count=1;
        for (UINT i=0;i<count;++i)
        {
#ifdef FSRD_NRD_BRIDGE_TEST
            if (gCopyFailureAfterForTesting == 0) { gCopyFailureAfterForTesting=-1; throw std::bad_alloc(); }
            if (gCopyFailureAfterForTesting > 0) --gCopyFailureAfterForTesting;
#endif
            const uint64_t delta=uint64_t(i)*stride;
            if (delta>UINT64_MAX-dh0 || delta>UINT64_MAX-sh0) throw std::logic_error("Descriptor copy slot overflow");
            const uint64_t dh=dh0+delta,sh=sh0+delta;
            const auto sourceShard=FrameSurveyMetadata::DescriptorShard(sh), destinationShard=FrameSurveyMetadata::DescriptorShard(dh);
            bool copied=false;
            for (unsigned attempt=0;attempt<8;++attempt)
            {
                if (attempt)
                {
                    version=ranges.Version(); destinationHeap=NativeMetadataHeapAtCpu(dh,type); sourceHeap=NativeMetadataHeapAtCpu(sh,type);
                }
                std::unique_lock<DescriptorMutex> first(gViewMutexes[std::min(sourceShard,destinationShard)]);
                std::unique_lock<DescriptorMutex> second;
                if (sourceShard != destinationShard) second=std::unique_lock<DescriptorMutex>(gViewMutexes[std::max(sourceShard,destinationShard)]);
                if (version != ranges.Version()) continue;
                const auto source=gViews.find(sh);
                const bool known=source != gViews.end() && NativeNodeMetadataCurrent(sourceHeap) && NativeNodeMetadataCurrent(destinationHeap) &&
                    sourceHeap->increment == stride && destinationHeap->increment == stride &&
                    sh >= sourceHeap->cpu && sh-sourceHeap->cpu < uint64_t(sourceHeap->count)*stride &&
                    dh >= destinationHeap->cpu && dh-destinationHeap->cpu < uint64_t(destinationHeap->count)*stride &&
                    source->second.heapOwner == sourceHeap && NativeViewMetadataFresh(source->second);
                // Snapshot before mutation, including same-slot and shared-owner copies.
                if (known)
                {
                    // Compare references before pinning a temporary. Exact no-op copies
                    // preserve the existing ordered-slot/source-snapshot semantics.
                    const auto destination=gViews.find(dh);
                    if (destination == gViews.end() || !SameCopiedView(destination->second,source->second,dh,destinationHeap))
                    {
#ifdef FSRD_NRD_BRIDGE_TEST
                        ++gCopyViewSnapshotsForTesting;
#endif
                        auto copy=source->second; copy.descriptorCpu=dh;
                        copy.descriptorHeap=uint64_t(reinterpret_cast<uintptr_t>(destinationHeap->object));
                        copy.heapKnown=true;
                        if (copy.heapOwner != destinationHeap) copy.heapOwner=destinationHeap;
                        NativeReplaceView(copy);
                    }
                }
                else NativeEraseView(dh);
                copied=true; break;
            }
            if (!copied) { std::scoped_lock slot(gViewMutexes[destinationShard]); NativeEraseView(dh); }
        }
        d+=count; s+=count;
    }
}
bool StoreKnownView(ID3D12Resource* object, uint64_t handle, uint32_t kind, DXGI_FORMAT format,
    uint32_t mip, uint32_t slice, bool supported, const NrdBridgeBirth::Token* proven = nullptr, bool texture2D = false)
{
    NrdBridgeBirth::CurrentGuard current(proven ? *proven : NrdBridgeBirth::Token{});
    if (proven && *proven && (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy())) return false;
    std::shared_lock catalog(gLifetimeMutex);
    const auto resource = gResources.find(object);
    if (object && (resource == gResources.end() || !resource->second.id ||
        (proven && *proven ? resource->second.birth != *proven : !BirthAvailable(resource->second.birth,object)))) return false;
    std::scoped_lock slot(gViewMutexes[FrameSurveyMetadata::DescriptorShard(handle)]); MetadataMutation mutation;
    if (!object) { EraseView(handle); return true; }
    const auto& metadata = resource->second;
    ViewInfo view {object,metadata.id,kind,uint32_t(format == DXGI_FORMAT_UNKNOWN ? metadata.desc.Format : format),
        mip+slice*metadata.desc.MipLevels,supported};
    view.texture2D = texture2D && metadata.desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        metadata.desc.DepthOrArraySize == 1 && metadata.desc.SampleDesc.Count == 1;
    view.descriptorCpu = handle;
    if (const auto heap = HeapAtCpu(handle))
    {
        view.descriptorHeap = uint64_t(reinterpret_cast<uintptr_t>(heap->object)); view.heapKnown = true;
    }
    ReplaceView(view); return true;
}
void StoreView(ID3D12Resource* object, uint64_t handle, uint32_t kind, DXGI_FORMAT format,
    uint32_t mip, uint32_t slice, bool supported, bool texture2D = false)
{
    if (!Tracking() || gInternal) return;
    if (NativeTracking()) { NativeStoreResourceView(object,handle,kind,format,mip,slice,supported,texture2D); return; }
    if (StoreKnownView(object,handle,kind,format,mip,slice,supported,nullptr,texture2D)) return;
    const auto proven = EnsureResourceRegistered(object);
    if (!StoreKnownView(object,handle,kind,format,mip,slice,supported,&proven,texture2D))
    {
        // A competing final Release may retire a first observation before publication.
        // Tombstone the destination instead of leaving an older live resource accepted.
        std::shared_lock catalog(gLifetimeMutex);
        std::scoped_lock slot(gViewMutexes[FrameSurveyMetadata::DescriptorShard(handle)]); EraseView(handle);
    }
}
std::vector<ViewInfo> Bindings(List& state, bool graphics, Json& unresolved)
{
    std::vector<ViewInfo> result;
    auto& root = graphics ? state.graphics : state.compute;
    if (!root.layout.complete) unresolved.push_back("root_signature_layout_unavailable");
    if (root.layout.directIndexed) unresolved.push_back("direct_heap_indexing_shader_usage_unknown");
    NativeSnapshotExclusive snapshot;
    if (!gMetadataHealthy.load(std::memory_order_acquire) || !Recording()) { unresolved.push_back("descriptor_metadata_unhealthy"); return result; }
    std::scoped_lock lock(gLifetimeMutex);
    for (const auto& [index,base] : root.tables)
    {
        const auto table = root.layout.tables.find(index);
        if (table == root.layout.tables.end()) continue;
        const Heap* heap = nullptr;
        for (auto* object : state.heaps)
        {
            const auto found = gHeaps.find(object);
            if (found == gHeaps.end()) continue;
            const auto& h = found->second;
            if (h.gpu && base >= h.gpu && base-h.gpu < uint64_t(h.count)*h.increment) { heap = &h; break; }
        }
        if (!heap || !heap->increment) { unresolved.push_back("descriptor_heap_unavailable"); continue; }
        const uint64_t first = (base-heap->gpu)/heap->increment;
        for (const auto& range : table->second)
        {
            if (range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV && range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV &&
                range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV) continue;
            if (first+range.offset >= heap->count) continue;
            uint64_t count = std::min<uint64_t>(range.count,heap->count-first-range.offset);
            // Unbounded/bindless ranges cannot reveal shader dynamic indexing.
            if (count > 512) { count = 512; unresolved.push_back("descriptor_range_capped_512"); }
            for (uint64_t i=0;i<count;++i)
            {
                const auto found = gViews.find(heap->cpu+(first+range.offset+i)*heap->increment);
                if (found == gViews.end()) continue;
                if (NativeTracking() && !NativeViewFresh(found->second)) continue;
                auto view = found->second;
                view.descriptorHeap = uint64_t(reinterpret_cast<uintptr_t>(heap->object));
                view.descriptorIndex = UINT(first+range.offset+i); view.rootIndex = index;
                view.descriptorCpu = heap->cpu+uint64_t(view.descriptorIndex)*heap->increment;
                view.descriptorGpu = heap->gpu+uint64_t(view.descriptorIndex)*heap->increment;
                // Range type is authoritative, not a guessed adjacent descriptor.
                if (view.kind == range.kind) result.push_back(view);
            }
        }
    }
    for (const auto& [index,view] : root.views)
    {
        const auto upper = gAddresses.upper_bound(view.second);
        if (upper == gAddresses.begin()) { unresolved.push_back("root_gpu_va_unresolved"); continue; }
        const auto found = gResources.find(std::prev(upper)->second);
        if (found == gResources.end() || view.second-found->second.va >= found->second.desc.Width)
        { unresolved.push_back("root_gpu_va_unresolved"); continue; }
        ViewInfo binding {found->first,found->second.id,view.first,uint32_t(found->second.desc.Format),0,false};
        binding.rootVa = view.second; binding.rootIndex = index; result.push_back(binding);
    }
    if (graphics) result.insert(result.end(),state.targets.begin(),state.targets.end());
    std::sort(result.begin(),result.end(),[](const auto& a,const auto& b) {
        return std::tie(a.resource,a.kind,a.subresource) < std::tie(b.resource,b.kind,b.subresource); });
    result.erase(std::unique(result.begin(),result.end(),[](const auto& a,const auto& b) {
        return a.resource == b.resource && a.kind == b.kind && a.subresource == b.subresource; }),result.end());
    return result;
}
bool CopyImage(ID3D12GraphicsCommandList* cmd, List& list, const ViewInfo& view,
    D3D12_RESOURCE_STATES state, const std::string& key, bool tagged, UINT x = 0, UINT y = 0, UINT w = 0, UINT h = 0)
{
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return false;
    InternalScope internal;
    ComPtr<ID3D12Resource> source;
    D3D12_RESOURCE_DESC desc {}; RecorderResource metadata;
    {
        std::scoped_lock lock(gLifetimeMutex);
        const auto found = gResources.find(view.object);
        if (found == gResources.end() || found->second.id != view.resource) { Count("released_descriptor_resource"); return false; }
        metadata = RecorderDescription(found->second);
    }
    source = view.object; desc = metadata.desc; Describe(metadata);
    const auto mip = view.subresource % desc.MipLevels;
    const uint32_t width = uint32_t(std::max<uint64_t>(1,desc.Width >> mip)), height = std::max(1u,desc.Height >> mip);
    // A targeted pass may sit in a list reset before the frame (async/early recording); its payload
    // still retires on that list's next Reset, like any other.
    if ((!list.resetObserved && !list.targeted) || list.inRenderPass)
    { Count("snapshot_recording_state_unavailable"); return false; }
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.SampleDesc.Count != 1 || !view.snapshotSupported) return false;
    if (!tagged && !FrameSurveyMetadata::CandidateExtent(width,height,gRenderWidth,gRenderHeight)) return false;
    // Targeted mode: the candidate budget belongs to the listed passes' outputs (one RGBA16F output is ~10 MiB
    // at 1505x847, the regular last-writer set alone fills most of the 192 MiB).
    if (!tagged && !list.targeted && TargetsConfigured()) { Count("regular_snapshot_skipped_targeted_mode"); return false; }
    const std::pair<uint64_t,uint32_t> identity {view.resource,view.subresource};
    if (list.splitTransitions.contains(identity)) { Count("pending_split_barrier_snapshot_skipped"); return false; }
    const bool fresh = !list.copied.contains(key);
    if (fresh && !tagged)
    {
        if (!gService->candidates.contains(identity) && gService->candidates.size() >= 96)
        { Count("candidate_count_cap"); return false; }
        // Reserve 64 MiB for the actual title tags. GAME_TRACE separately
        // enforces actual committed GPU allocations and CPU/disk payload limits.
        UINT bpp = 16;
        switch (uint32_t(desc.Format))
        {
        case 5: case 6: bpp = 12; break;
        case 9: case 10: case 11: case 15: case 16: bpp = 8; break;
        case 23: case 24: case 26: case 27: case 28: case 33: case 34: case 35:
        case 39: case 40: case 41: case 44: case 45: case 46: case 87: bpp = 4; break;
        case 53: case 54: case 56: bpp = 2; break; case 60: case 61: bpp = 1; break;
        }
        const uint64_t charge = uint64_t(width)*height*bpp;
        if (charge > (192ull<<20)-std::min<uint64_t>(192ull<<20,gService->candidateBytes))
        { Count("candidate_byte_cap"); return false; }
        gService->candidateBytes += charge;
    }
    if (!list.payload) list.payload = gService->trace.BeginSurveyBatch(gService->device.Get(),cmd,list.id);
    if (!list.payload) { Count("payload_batch_unavailable"); return false; }
    if (!gService->trace.SurveyTexture(list.payload,key,{source.Get(),state},view.subresource,x,y,w,h))
    { Count("unsupported_format_or_readback_budget"); return false; }
    if (!tagged) gService->candidates.insert(identity);
    if (list.targeted) ++gService->targetedCopies;
    list.copied[key] = list.lastPass;
    gService->manifest["snapshots"].push_back({{"key",key},{"list_id",list.id},{"resource",view.resource},
        {"subresource",view.subresource},{"writer_local_pass",list.lastPass},{"tagged",tagged},{"view_format",view.format},
        {"state_provenance",tagged ? "see_current_tag_metadata" : "observed_local_resource_barrier"}});
    return true;
}
bool CopyBuffer(ID3D12GraphicsCommandList* cmd, List& list, ID3D12Resource* object,
    const std::string& key, uint64_t offset, uint32_t bytes)
{
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return false;
    InternalScope internal;
    if (!object || !bytes || (!list.resetObserved && !list.targeted) || list.inRenderPass) return false;
    ComPtr<ID3D12Resource> source;
    uint64_t id = 0; RecorderResource metadata;
    EnsureResourceRegistered(object);
    {
        std::scoped_lock lock(gLifetimeMutex); auto& resource = Register(object);
        if (resource.desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER ||
            offset > resource.desc.Width || bytes > resource.desc.Width-offset) return false;
        metadata = RecorderDescription(resource);
    }
    source = object; id = metadata.id; Describe(metadata);
    D3D12_HEAP_PROPERTIES heap {}; D3D12_HEAP_FLAGS flags {};
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
    if (SUCCEEDED(source->GetHeapProperties(&heap,&flags)) && heap.Type == D3D12_HEAP_TYPE_UPLOAD)
        state = D3D12_RESOURCE_STATE_GENERIC_READ; // upload heaps have a fixed, proven state
    else
    {
        const auto observed = list.states.find({id,0});
        if (observed == list.states.end()) { Count("buffer_read_state_unproven"); return false; }
        state = observed->second;
    }
    if (list.splitTransitions.contains({id,0})) return false;
    if (!list.payload) list.payload = gService->trace.BeginSurveyBatch(gService->device.Get(),cmd,list.id);
    return list.payload && gService->trace.SurveyBuffer(list.payload,key,{source.Get(),state},offset,bytes);
}
}

ScopedInternal::ScopedInternal() noexcept : previous_(gInternal) { gInternal = true; }
ScopedInternal::~ScopedInternal() { gInternal = previous_; }
ScopedRecording::ScopedRecording() noexcept { ++gRecordingDepth; }
ScopedRecording::~ScopedRecording() { --gRecordingDepth; }
bool OwnedRelease() noexcept { return gInternal && !gRecordingDepth; }
void SetPipelineObserver(PipelineObserver observer) noexcept { gPipelineObserver.store(observer,std::memory_order_release); }
void SetGraphicsPipelineObserver(GraphicsPipelineObserver observer) noexcept { gGraphicsPipelineObserver.store(observer,std::memory_order_release); }
void SetReleaseObserver(ReleaseObserver observer) noexcept { gReleaseObserver.store(observer,std::memory_order_release); }
void SetBirthReleaseObserver(BirthReleaseObserver observer) noexcept { gBirthReleaseObserver.store(observer,std::memory_order_release); }
static IndirectSignatureKind ClassifyIndirectSignature(const D3D12_COMMAND_SIGNATURE_DESC& desc, ID3D12RootSignature* root) noexcept
{
    if (!root && desc.NumArgumentDescs == 1 && desc.pArgumentDescs)
    {
        const auto type = desc.pArgumentDescs[0].Type;
        if (type == D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH && desc.ByteStride == sizeof(D3D12_DISPATCH_ARGUMENTS))
            return IndirectSignatureKind::Dispatch;
        if (type == D3D12_INDIRECT_ARGUMENT_TYPE_DRAW_INDEXED && desc.ByteStride == sizeof(D3D12_DRAW_INDEXED_ARGUMENTS))
            return IndirectSignatureKind::DrawIndexed;
    }
    return IndirectSignatureKind::Unknown;
}
static bool PublishIndirectSignatureMetadata(IndirectSignatureInfo info)
{
    if (!Tracking() || !info.signature || !info.birth || info.birth->Address() != info.signature) return false;
    NrdBridgeBirth::CurrentGuard current(info.birth);
    if (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy()) return false;
    NativeSnapshotShared snapshot; if (!Tracking()) return false;
    std::scoped_lock catalog(gLifetimeMutex); MetadataMutation mutation;
    gIndirectSignatures[info.signature] = std::move(info); return true;
}
void CommandSignatureCreated(ID3D12CommandSignature* signature, const D3D12_COMMAND_SIGNATURE_DESC& desc,
    ID3D12RootSignature* root) noexcept
{
    if (!Tracking() || gInternal || !signature || !NativeTracking()) return;
    try
    {
        IndirectSignatureInfo info {signature,ClassifyIndirectSignature(desc,root),desc.ByteStride,{}};
        // The creating caller owns the native reference. Every native operation
        // precedes the Birth/catalog scopes; the map owns metadata tokens only.
        if (!NrdBridgeNativeBirth::ObserveReleaseCoverage(signature)) { MetadataFailed("Indirect signature Release coverage failed"); return; }
        info.birth = NrdBridgeNativeBirth::Prepare(signature);
        if (!PublishIndirectSignatureMetadata(std::move(info))) MetadataFailed("Indirect signature publication was denied");
    } catch (...) { MetadataFailed("Indirect signature publication failed"); }
}
bool ResolveIndirectSignature(ID3D12CommandSignature* signature, IndirectSignatureInfo& out) noexcept
{
    out = {};
    if (!Tracking() || !signature || !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        std::shared_lock catalog(gLifetimeMutex);
        const auto found = gIndirectSignatures.find(signature);
        if (!gMetadataHealthy.load(std::memory_order_acquire) || found == gIndirectSignatures.end() ||
            found->second.kind == IndirectSignatureKind::Unknown || !found->second.birth ||
            !BirthAvailable(found->second.birth,signature)) return false;
        out = found->second; return true;
    } catch (...) { return false; }
}
bool ValidateIndirectSignature(const IndirectSignatureInfo& expected) noexcept
{
    IndirectSignatureInfo current;
    return expected.birth && ResolveIndirectSignature(expected.signature,current) && current.birth == expected.birth &&
        current.kind == expected.kind && current.byteStride == expected.byteStride;
}
bool ResolvePipelineShaderIdentity(ID3D12PipelineState* pipeline, PipelineShaderIdentity& out) noexcept
{
    out = {};
    if (!Tracking() || !pipeline || !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        std::shared_lock catalog(gLifetimeMutex);
        const auto found = gPipelineMetadata.find(pipeline);
        if (!gMetadataHealthy.load(std::memory_order_acquire) || found == gPipelineMetadata.end()) return false;
        const auto& identity = found->second.identity;
        if (!identity.complete || !identity.pipelineBirth || identity.pipelineBirth != found->second.birth ||
            !BirthAvailable(identity.pipelineBirth,pipeline)) return false;
        out = identity; return true;
    } catch (...) { return false; }
}
bool ValidatePipelineShaderIdentity(const PipelineShaderIdentity& expected) noexcept
{
    PipelineShaderIdentity current;
    return expected.pipelineBirth && ResolvePipelineShaderIdentity(expected.pipeline,current) &&
        current.pipelineBirth == expected.pipelineBirth && current.complete == expected.complete &&
        current.presentStages == expected.presentStages && current.compute == expected.compute &&
        current.vertex == expected.vertex && current.pixel == expected.pixel;
}
void FlushMetadataFailure() noexcept
{
    if (NrdBridgeBirth::InMetadataScope()) return;
    if (const auto reason = gDeferredMetadataFailure.exchange(nullptr,std::memory_order_acq_rel)) Fail(reason);
}
void SetBindingWindow(bool enabled) noexcept
{
    if (gBindingWindow.exchange(enabled,std::memory_order_acq_rel) == enabled) return;
    if (gSurveyBindings.load(std::memory_order_relaxed)) return; // Preserve the survey's early-binding mirror.
    try
    {
        std::scoped_lock lock(gMirrorMutex); gMirror.clear(); gMirrorOwners.clear();
    } catch (...) { MetadataFailed("Binding window invalidation failed"); }
}
bool BindingWindow() noexcept { return gBindingWindow.load(std::memory_order_relaxed); }
bool MetadataHealthy() noexcept { return gMetadataHealthy.load(std::memory_order_acquire); }
void MetadataHookFailed(const char* reason) noexcept
{
    if (!gMetadataHealthy.exchange(false,std::memory_order_acq_rel)) return;
    // Hook installation may run inside bridge injection or survey recording.
    // The existing admission gates consume this latch; never enter Fail/Shutdown here.
    try { LOG_ERROR("[FRAME_SURVEY] native metadata observer failed: {}",reason ? reason : "unspecified observer"); } catch (...) {}
}
bool SeedComputeBindings(ID3D12GraphicsCommandList* cmd, const ComputeBindings& bindings) noexcept
{
    if (!BindingTracking() || gInternal || !cmd || !bindings.root || bindings.heaps.empty() || !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        if (!BirthAvailable(bindings.receiverBirth,cmd) || !BirthAvailable(bindings.rootBirth,bindings.root)) return false;
        if ((!bindings.heapBirths.empty() || NativeTracking()) && bindings.heapBirths.size() != bindings.heaps.size()) return false;
        for (size_t i=0;i<bindings.heapBirths.size();++i) if (!BirthAvailable(bindings.heapBirths[i],bindings.heaps[i])) return false;
        NrdBridgeBirth::CurrentGuard current(bindings.receiverBirth);
        if (bindings.receiverBirth && !current.AdmitsBorrow()) return false;
        NativeSnapshotShared snapshot; if (!BindingTracking()) return false;
        std::scoped_lock lock(gMirrorMutex); MetadataMutation mutation;
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return false;
        auto& mirror = gMirror[cmd]; const MirrorReferences before(mirror);
        if (mirror.receiverBirth != bindings.receiverBirth) mirror = {};
        if (mirror.compute.object != bindings.root || mirror.compute.birth != bindings.rootBirth) mirror.compute = {};
        if (mirror.heaps != bindings.heaps) mirror.graphics.tables.clear();
        mirror.receiverBirth = bindings.receiverBirth; mirror.compute.object = bindings.root; mirror.compute.birth = bindings.rootBirth;
        if (bindings.pipelineBirth) { mirror.pipelineBirth = bindings.pipelineBirth; mirror.pso = static_cast<ID3D12PipelineState*>(bindings.pipelineBirth->Address()); }
        mirror.compute.tables.clear(); mirror.compute.views.clear();
        for (const auto& [parameter,handle] : bindings.tables) mirror.compute.tables[parameter] = handle.ptr;
        for (const auto& view : bindings.views) mirror.compute.views[view.parameter] = {uint32_t(view.kind),view.address};
        mirror.heaps = bindings.heaps; mirror.heapBirths = bindings.heapBirths; UpdateMirrorOwners(cmd,before,MirrorReferences(mirror)); return true;
    } catch (...) { MetadataFailed("Compute binding seed failed"); return false; }
}
bool ComputeTableBindingMatches(ID3D12GraphicsCommandList* cmd, UINT parameter, D3D12_DESCRIPTOR_RANGE_TYPE kind,
    UINT descriptorOffset, UINT shaderRegister, UINT registerSpace) noexcept
{
    if (!BindingTracking() || gInternal || !cmd || !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        // Identity-only POD rows use catalog/mirror guards; slot readers still drain the snapshot gate.
        // Inspect the same live root/table and registry under one lock scope; no COM call, retain or allocation.
        std::scoped_lock lock(gMirrorMutex,gLifetimeMutex);
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return false;
        const auto list = gMirror.find(cmd);
        if (list == gMirror.end() || !list->second.compute.object || !MirrorAvailable(list->second,cmd)) return false;
        const auto& root = list->second.compute;
        const auto binding = root.tables.find(parameter);
        if (binding == root.tables.end() || !binding->second) return false;
        const auto layout = gRootLayouts.find(root.object);
        if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != root.birth || !BirthAvailable(layout->second.birth,root.object) || !layout->second.computeTables.contains(parameter)) return false;
        const auto table = layout->second.tables.find(parameter);
        if (table == layout->second.tables.end()) return false;
        for (const auto& range : table->second)
            if (uint64_t(descriptorOffset) >= range.offset && uint64_t(descriptorOffset) < uint64_t(range.offset)+range.count)
                return range.kind == uint32_t(kind) && range.registerSpace == registerSpace &&
                    uint64_t(range.shaderRegister)+descriptorOffset-range.offset == shaderRegister;
        return false;
    } catch (...) { return false; }
}
bool ResolveComputeBindings(ID3D12GraphicsCommandList* cmd, UINT parameter,
    std::span<const ComputeTableRequest> requests, std::vector<BoundResource>& out) noexcept
{
    out.clear();
    if (!BindingTracking() || gInternal || !cmd || requests.empty() || requests.size() > 8 ||
        !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        std::array<BoundResource,8> resolved {};
        {
            NativeSnapshotExclusive metadataSnapshot;
            std::scoped_lock lock(gMirrorMutex,gLifetimeMutex); MetadataMutation mutation;
            if (!gMetadataHealthy.load(std::memory_order_acquire)) return false;
            const auto list = gMirror.find(cmd);
            if (list == gMirror.end() || !list->second.compute.object || !MirrorAvailable(list->second,cmd)) return false;
            const auto& root = list->second.compute;
            const auto binding = root.tables.find(parameter);
            if (binding == root.tables.end() || !binding->second) return false;
            const auto layout = gRootLayouts.find(root.object);
            if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != root.birth || !BirthAvailable(layout->second.birth,root.object) || !layout->second.computeVisibleTables.contains(parameter)) return false;
            const auto table = layout->second.tables.find(parameter);
            if (table == layout->second.tables.end()) return false;
            for (size_t i=0;i<requests.size();++i)
            {
                const auto& request = requests[i];
                if (request.kind > D3D12_DESCRIPTOR_RANGE_TYPE_CBV || !UniqueComputeMapping(table->second,request)) return false;
                for (size_t j=0;j<i;++j)
                    if (requests[j].descriptorOffset == request.descriptorOffset ||
                        (requests[j].kind == request.kind && requests[j].shaderRegister == request.shaderRegister &&
                         requests[j].registerSpace == request.registerSpace)) return false;
            }
            const Heap* heap = nullptr;
            for (const auto object : list->second.heaps)
            {
                const auto found = gHeaps.find(object);
                if (found == gHeaps.end()) continue;
                const auto& candidate = found->second;
                const uint64_t base = binding->second;
                if (candidate.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || !candidate.gpu || !candidate.increment ||
                    base < candidate.gpu || base-candidate.gpu >= uint64_t(candidate.count)*candidate.increment ||
                    (base-candidate.gpu)%candidate.increment) continue;
                if (heap) return false;
                heap = &candidate;
            }
            if (!heap) return false;
            const uint64_t first = (binding->second-heap->gpu)/heap->increment;
            // Resolve only requested descriptors. Unused table length and missing tail views are irrelevant.
            for (size_t i=0;i<requests.size();++i)
            {
                const auto& request = requests[i];
                const uint64_t index = first+request.descriptorOffset;
                if (index >= heap->count) return false;
                const auto view = gViews.find(heap->cpu+index*heap->increment);
                if (view == gViews.end() || view->second.kind != uint32_t(request.kind) || !FreshView(view->second,heap)) return false;
                const auto resource = gResources.find(view->second.object);
                if (resource == gResources.end() || resource->second.id != view->second.resource) return false;
                if (request.kind == D3D12_DESCRIPTOR_RANGE_TYPE_CBV)
                {
                    BoundConstantBuffer buffer;
                    if (!view->second.constantBytes || !ResolveBufferAddress(view->second.rootVa,view->second.constantBytes,view->second.constantBytes,buffer) ||
                        buffer.resource != resource->first) return false;
                }
                else if (!view->second.snapshotSupported) return false;
                resolved[i] = {resource->first,resource->second.desc,DXGI_FORMAT(view->second.format),request.kind,
                    request.descriptorOffset,UINT(index),view->second.subresource,resource->second.birth,resource->second.id};
            }
        }
        out.assign(resolved.begin(),resolved.begin()+requests.size()); return true;
    } catch (...) { MetadataFailed("Compute requested-binding allocation failed"); out.clear(); return false; }
}
static bool ResolveTextureBindings(const ComputeBindings& bindings, UINT parameter,
    std::span<const ComputeTableRequest> requests, std::vector<BoundResource>& out, bool pixel) noexcept
{
    out.clear();
    if (!Tracking() || !bindings.root || bindings.heaps.size() > 2 || requests.empty() || requests.size() > 8 ||
        !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        std::array<BoundResource,8> resolved {};
        {
            NativeSnapshotExclusive metadataSnapshot;
            std::scoped_lock lock(gLifetimeMutex);
            if (!gMetadataHealthy.load(std::memory_order_acquire) || !BirthAvailable(bindings.rootBirth,bindings.root)) return false;
            if ((!bindings.heapBirths.empty() || NativeTracking()) && bindings.heapBirths.size() != bindings.heaps.size()) return false;
            for (size_t i=0;i<bindings.heapBirths.size();++i)
                if (!BirthAvailable(bindings.heapBirths[i],bindings.heaps[i])) return false;
            const auto layout = gRootLayouts.find(bindings.root);
            if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != bindings.rootBirth ||
                !(pixel ? layout->second.pixelVisibleTables : layout->second.computeVisibleTables).contains(parameter)) return false;
            const auto table = layout->second.tables.find(parameter);
            if (table == layout->second.tables.end()) return false;
            uint64_t base = 0;
            for (const auto& [index,handle] : bindings.tables) if (index == parameter)
            {
                if (base || !handle.ptr) return false;
                base = handle.ptr;
            }
            if (!base) return false;
            for (size_t i=0;i<requests.size();++i)
            {
                const auto& request = requests[i];
                // Explicit snapshots admit texture SRVs/UAVs; pixel consumers require SRVs.
                if ((request.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV && request.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV) ||
                    (pixel && request.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV) || !UniqueComputeMapping(table->second,request)) return false;
                for (size_t j=0;j<i;++j)
                    if (requests[j].descriptorOffset == request.descriptorOffset ||
                        (requests[j].kind == request.kind && requests[j].shaderRegister == request.shaderRegister &&
                         requests[j].registerSpace == request.registerSpace)) return false;
            }
            const Heap* heap = nullptr;
            for (const auto object : bindings.heaps)
            {
                const auto found = gHeaps.find(object);
                if (found == gHeaps.end()) continue;
                const auto& candidate = found->second;
                if (candidate.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || !candidate.gpu || !candidate.increment ||
                    base < candidate.gpu || base-candidate.gpu >= uint64_t(candidate.count)*candidate.increment ||
                    (base-candidate.gpu)%candidate.increment) continue;
                if (heap) return false;
                heap = &candidate;
            }
            if (!heap) return false;
            const uint64_t first = (base-heap->gpu)/heap->increment;
            for (size_t i=0;i<requests.size();++i)
            {
                const auto& request = requests[i];
                const uint64_t index = first+request.descriptorOffset;
                if (index >= heap->count || index*heap->increment > UINT64_MAX-heap->cpu) return false;
                const auto view = gViews.find(heap->cpu+index*heap->increment);
                if (view == gViews.end() || view->second.kind != uint32_t(request.kind) ||
                    !view->second.snapshotSupported || !FreshView(view->second,heap)) return false;
                const auto resource = gResources.find(view->second.object);
                if (resource == gResources.end() || resource->second.id != view->second.resource) return false;
                resolved[i] = {resource->first,resource->second.desc,DXGI_FORMAT(view->second.format),request.kind,
                    request.descriptorOffset,UINT(index),view->second.subresource,resource->second.birth,resource->second.id};
            }
        }
        out.assign(resolved.begin(),resolved.begin()+requests.size()); return true;
    } catch (...) { MetadataFailed("Explicit texture-binding allocation failed"); out.clear(); return false; }
}

bool ResolveComputeBindings(const ComputeBindings& bindings, UINT parameter,
    std::span<const ComputeTableRequest> requests, std::vector<BoundResource>& out) noexcept
{ return ResolveTextureBindings(bindings,parameter,requests,out,false); }
bool ResolveGraphicsBindings(const ComputeBindings& bindings, UINT parameter,
    std::span<const ComputeTableRequest> requests, std::vector<BoundResource>& out) noexcept
{ return ResolveTextureBindings(bindings,parameter,requests,out,true); }

static bool ResolveTextureBindingBatch(const ComputeBindings& bindings, std::span<const TextureTableRequest> requests,
    std::vector<BoundResource>& out, std::vector<TextureBindingWitness>* witnesses, bool pixel) noexcept
{
    out.clear(); if (witnesses) witnesses->clear();
    if (!Tracking() || !bindings.root || !bindings.rootBirth || bindings.heaps.size() > 2 || requests.empty() ||
        requests.size() > 16 || bindings.heapBirths.size() != bindings.heaps.size() ||
        !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        std::array<BoundResource,16> resolved {};
        std::array<TextureBindingWitness,16> proof {};
        {
            NativeSnapshotExclusive metadataSnapshot;
            std::shared_lock catalog(gLifetimeMutex);
            if (!gMetadataHealthy.load(std::memory_order_acquire) || !BirthAvailable(bindings.rootBirth,bindings.root)) return false;
            for (size_t i=0;i<bindings.heaps.size();++i)
                if (!bindings.heapBirths[i] || !BirthAvailable(bindings.heapBirths[i],bindings.heaps[i])) return false;
            const auto layout = gRootLayouts.find(bindings.root);
            if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != bindings.rootBirth) return false;
            for (size_t i=0;i<requests.size();++i)
            {
                const auto& row = requests[i]; auto request = row.binding; UINT parameter = UINT_MAX, offset = UINT_MAX;
                if (!FindTextureRegisterMapping(layout->second,pixel,request,parameter,offset)) return false;
                const bool automatic = row.rootParameter == UINT_MAX && request.descriptorOffset == UINT_MAX;
                if (!automatic && (row.rootParameter != parameter || request.descriptorOffset != offset)) return false;
                request.descriptorOffset = offset;
                if ((request.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV && request.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV) ||
                    (pixel && request.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV) ||
                    !(pixel ? layout->second.pixelVisibleTables : layout->second.computeVisibleTables).contains(parameter)) return false;
                const auto table = layout->second.tables.find(parameter);
                if (table == layout->second.tables.end() || !UniqueComputeMapping(table->second,request)) return false;
                for (size_t j=0;j<i;++j)
                    if ((proof[j].rootParameter == parameter && proof[j].descriptorOffset == request.descriptorOffset) ||
                        (proof[j].kind == request.kind && proof[j].shaderRegister == request.shaderRegister &&
                         proof[j].registerSpace == request.registerSpace)) return false;
                uint64_t base = 0;
                for (const auto& [boundParameter,handle] : bindings.tables) if (boundParameter == parameter)
                { if (base || !handle.ptr) return false; base = handle.ptr; }
                if (!base) return false;
                const Heap* heap = nullptr;
                for (size_t h=0;h<bindings.heaps.size();++h)
                {
                    const auto found = gHeaps.find(bindings.heaps[h]);
                    if (found == gHeaps.end()) continue;
                    const auto& candidate = found->second;
                    if (candidate.birth != bindings.heapBirths[h] || candidate.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV ||
                        !candidate.gpu || !candidate.increment || base < candidate.gpu ||
                        base-candidate.gpu >= uint64_t(candidate.count)*candidate.increment ||
                        (base-candidate.gpu)%candidate.increment) continue;
                    if (heap) return false;
                    heap = &candidate;
                }
                if (!heap) return false;
                const uint64_t index = (base-heap->gpu)/heap->increment+request.descriptorOffset;
                if (index >= heap->count || index*heap->increment > UINT64_MAX-heap->cpu) return false;
                const uint64_t cpu = heap->cpu+index*heap->increment;
                const auto view = gViews.find(cpu);
                if (view == gViews.end() || view->second.kind != uint32_t(request.kind) || !view->second.snapshotSupported ||
                    !view->second.texture2D || !FreshView(view->second,heap)) return false;
                const auto resource = gResources.find(view->second.object);
                if (resource == gResources.end() || resource->second.id != view->second.resource || !resource->second.birth ||
                    resource->second.desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || resource->second.desc.SampleDesc.Count != 1 ||
                    !resource->second.desc.MipLevels || view->second.subresource >= resource->second.desc.MipLevels) return false;
                resolved[i] = {resource->first,resource->second.desc,DXGI_FORMAT(view->second.format),request.kind,
                    request.descriptorOffset,UINT(index),view->second.subresource,resource->second.birth,resource->second.id};
                proof[i] = {bindings.root,bindings.rootBirth,parameter,request.descriptorOffset,request.shaderRegister,
                    request.registerSpace,request.kind,pixel,heap->object,heap->birth,base,cpu,resource->first,resource->second.birth,
                    resource->second.id,DXGI_FORMAT(view->second.format),view->second.subresource};
            }
        }
        // Dynamic containers and last-owner release remain outside every metadata guard.
        out.assign(resolved.begin(),resolved.begin()+requests.size());
        if (witnesses) witnesses->assign(proof.begin(),proof.begin()+requests.size());
        return true;
    } catch (...) { MetadataFailed("Coherent texture-binding allocation failed"); out.clear(); if (witnesses) witnesses->clear(); return false; }
}
bool ResolveComputeTextureBindings(const ComputeBindings& bindings, std::span<const TextureTableRequest> requests,
    std::vector<BoundResource>& out, std::vector<TextureBindingWitness>* witnesses) noexcept
{ return ResolveTextureBindingBatch(bindings,requests,out,witnesses,false); }
bool ResolveGraphicsTextureBindings(const ComputeBindings& bindings, std::span<const TextureTableRequest> requests,
    std::vector<BoundResource>& out, std::vector<TextureBindingWitness>* witnesses) noexcept
{ return ResolveTextureBindingBatch(bindings,requests,out,witnesses,true); }
bool ValidateTextureBindingWitnesses(std::span<const TextureBindingWitness> witnesses) noexcept
{
    if (!Tracking() || witnesses.empty() || witnesses.size() > MaximumTextureBindingWitnesses ||
        !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        NativeSnapshotExclusive metadataSnapshot;
        std::shared_lock catalog(gLifetimeMutex);
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return false;
        for (const auto& expected : witnesses)
        {
            if (!expected.root || !expected.rootBirth || !expected.heap || !expected.heapBirth || !expected.resource ||
                !expected.resourceBirth || !expected.resourceGeneration || !expected.tableBase ||
                !BirthAvailable(expected.rootBirth,expected.root) || !BirthAvailable(expected.heapBirth,expected.heap) ||
                !BirthAvailable(expected.resourceBirth,expected.resource)) return false;
            const auto layout = gRootLayouts.find(expected.root);
            const ComputeTableRequest request {expected.kind,expected.descriptorOffset,expected.shaderRegister,expected.registerSpace};
            if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != expected.rootBirth ||
                (expected.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV && expected.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV) ||
                (expected.pixel && expected.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV) ||
                !(expected.pixel ? layout->second.pixelVisibleTables : layout->second.computeVisibleTables).contains(expected.rootParameter)) return false;
            UINT parameter = UINT_MAX, offset = UINT_MAX;
            if (!FindTextureRegisterMapping(layout->second,expected.pixel,request,parameter,offset) ||
                parameter != expected.rootParameter || offset != expected.descriptorOffset) return false;
            const auto table = layout->second.tables.find(expected.rootParameter);
            if (table == layout->second.tables.end() || !UniqueComputeMapping(table->second,request)) return false;
            const auto heapFound = gHeaps.find(expected.heap);
            if (heapFound == gHeaps.end()) return false;
            const auto& heap = heapFound->second;
            if (heap.birth != expected.heapBirth || heap.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || !heap.gpu ||
                !heap.increment || expected.tableBase < heap.gpu ||
                expected.tableBase-heap.gpu >= uint64_t(heap.count)*heap.increment ||
                (expected.tableBase-heap.gpu)%heap.increment) return false;
            const uint64_t index = (expected.tableBase-heap.gpu)/heap.increment+expected.descriptorOffset;
            if (index >= heap.count || index*heap.increment > UINT64_MAX-heap.cpu ||
                heap.cpu+index*heap.increment != expected.descriptorCpu) return false;
            const auto view = gViews.find(expected.descriptorCpu);
            if (view == gViews.end() || view->second.object != expected.resource || view->second.resource != expected.resourceGeneration ||
                view->second.kind != uint32_t(expected.kind) || view->second.format != uint32_t(expected.viewFormat) ||
                view->second.subresource != expected.subresource || !view->second.snapshotSupported || !view->second.texture2D || !FreshView(view->second,&heap)) return false;
            const auto resource = gResources.find(expected.resource);
            if (resource == gResources.end() || resource->second.id != expected.resourceGeneration || resource->second.birth != expected.resourceBirth ||
                resource->second.desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || resource->second.desc.SampleDesc.Count != 1 ||
                !resource->second.desc.MipLevels || view->second.subresource >= resource->second.desc.MipLevels) return false;
        }
        return true;
    } catch (...) { return false; }
}

bool ValidateBorrowedConstantBuffer(const BoundConstantBuffer& buffer) noexcept
{
    if (!Tracking() || !buffer.resource || !buffer.resourceGeneration || !buffer.address || buffer.address%256 ||
        !buffer.size || buffer.size > 65536 || !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        NativeSnapshotExclusive metadataSnapshot;
        std::scoped_lock lock(gLifetimeMutex);
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return false;
        const auto found = gResources.find(buffer.resource);
        if (found == gResources.end()) return false;
        const auto& resource = found->second;
        if (resource.birth != buffer.resourceBirth || !BirthAvailable(resource.birth,buffer.resource) ||
            resource.id != buffer.resourceGeneration || resource.object != buffer.resource ||
            resource.desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER || !resource.va ||
            buffer.address < resource.va || buffer.address-resource.va != buffer.offset ||
            buffer.offset > resource.desc.Width || buffer.size > resource.desc.Width-buffer.offset) return false;
        if (!buffer.descriptorHeap) return !buffer.descriptor.ptr;
        const auto foundHeap = gHeaps.find(buffer.descriptorHeap);
        if (foundHeap == gHeaps.end()) return false;
        const auto& heap = foundHeap->second;
        if (heap.birth != buffer.descriptorHeapBirth || !BirthAvailable(heap.birth,heap.object) ||
            heap.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || !heap.gpu || !heap.increment ||
            buffer.descriptor.ptr < heap.gpu || buffer.descriptor.ptr-heap.gpu >= uint64_t(heap.count)*heap.increment ||
            (buffer.descriptor.ptr-heap.gpu)%heap.increment) return false;
        const auto view = gViews.find(heap.cpu+(buffer.descriptor.ptr-heap.gpu));
        return view != gViews.end() && FreshView(view->second,&heap) &&
            view->second.kind == D3D12_DESCRIPTOR_RANGE_TYPE_CBV && view->second.object == buffer.resource &&
            view->second.resource == buffer.resourceGeneration && view->second.rootVa == buffer.address &&
            view->second.constantBytes == buffer.size;
    } catch (...) { return false; }
}
bool ResolveComputeConstantBuffer(ID3D12GraphicsCommandList* cmd, UINT shaderRegister, UINT registerSpace,
    uint64_t minimumBytes, BoundConstantBuffer& out, ConstantBufferDiagnostic* diagnostic) noexcept
{
    out = {};
    if (diagnostic) *diagnostic = {};
    const auto fail = [&](const char* reason) { out = {}; if (diagnostic) diagnostic->reason = reason; return false; };
    if (!BindingTracking() || gInternal || !cmd || !minimumBytes || minimumBytes > 65536 ||
        !gMetadataHealthy.load(std::memory_order_acquire)) return fail("CBV binding tracking is unavailable");
    try
    {
        NativeSnapshotExclusive metadataSnapshot;
        std::scoped_lock lock(gMirrorMutex,gLifetimeMutex);
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return fail("CBV metadata is unhealthy");
        const auto list = gMirror.find(cmd);
        if (list == gMirror.end() || !list->second.compute.object || !MirrorAvailable(list->second,cmd)) return fail("Consumer compute root binding is missing or stale");
        const auto& root = list->second.compute;
        const auto layout = gRootLayouts.find(root.object);
        if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != root.birth || !BirthAvailable(layout->second.birth,root.object)) return fail("Consumer root layout is unavailable");
        UINT parameter = UINT_MAX;
        uint64_t descriptorOffset = 0;
        bool tableBinding = false;
        for (const auto& [index,descriptor] : layout->second.computeDescriptors)
        {
            if (descriptor.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || descriptor.shaderRegister != shaderRegister ||
                descriptor.registerSpace != registerSpace) continue;
            if (parameter != UINT_MAX) return fail("Consumer b-register maps to multiple root parameters");
            parameter = index;
        }
        for (const auto& [index,ranges] : layout->second.tables)
        {
            if (!layout->second.computeVisibleTables.contains(index)) continue;
            for (const auto& range : ranges)
            {
                if (range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || range.registerSpace != registerSpace) continue;
                if (!ValidComputeRange(range)) return fail("Consumer CBV table range is invalid");
                if (shaderRegister < range.shaderRegister ||
                    (range.count != UINT_MAX && uint64_t(shaderRegister)-range.shaderRegister >= range.count)) continue;
                const uint64_t offset = uint64_t(range.offset)+shaderRegister-range.shaderRegister;
                if (offset > UINT_MAX || parameter != UINT_MAX ||
                    !UniqueComputeMapping(ranges,{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT(offset),shaderRegister,registerSpace})) return fail("Consumer CBV register mapping is ambiguous");
                parameter = index; tableBinding = true; descriptorOffset = offset;
            }
        }
        if (parameter == UINT_MAX) return fail("Consumer b-register is absent from compute root layout");
        if (diagnostic) { diagnostic->rootParameter = parameter; diagnostic->table = tableBinding; diagnostic->trackedBuffers = gBufferAddresses.Size(); }
        if (!tableBinding)
        {
            const auto view = root.views.find(parameter);
            if (view == root.views.end() || view->second.first != D3D12_DESCRIPTOR_RANGE_TYPE_CBV)
                return fail("Consumer root CBV argument is missing");
            return ResolveBufferAddress(view->second.second,0,minimumBytes,out,diagnostic);
        }
        const auto binding = root.tables.find(parameter);
        if (binding == root.tables.end() || !binding->second) return fail("Consumer CBV table base is missing");
        if (diagnostic) diagnostic->tableBase = binding->second;
        const Heap* heap = nullptr;
        for (const auto object : list->second.heaps)
        {
            const auto found = gHeaps.find(object);
            if (found == gHeaps.end()) continue;
            const auto& candidate = found->second;
            const uint64_t base = binding->second;
            if (candidate.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || !candidate.gpu || !candidate.increment ||
                base < candidate.gpu || base-candidate.gpu >= uint64_t(candidate.count)*candidate.increment ||
                (base-candidate.gpu)%candidate.increment) continue;
            if (heap) return fail("Consumer CBV table matches multiple bound heaps");
            heap = &candidate;
        }
        if (!heap) return fail("Consumer CBV shader-visible heap is untracked");
        const uint64_t index = (binding->second-heap->gpu)/heap->increment+descriptorOffset;
        if (index >= heap->count) return fail("Consumer CBV slot is outside its heap");
        const auto handle = heap->cpu+index*heap->increment;
        if (diagnostic) diagnostic->descriptorCpu = handle;
        const auto view = gViews.find(handle);
        if (view == gViews.end() || view->second.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV ||
            !view->second.constantBytes || !FreshView(view->second,heap)) return fail("Consumer CBV descriptor slot is missing or stale");
        if (!ResolveBufferAddress(view->second.rootVa,view->second.constantBytes,minimumBytes,out,diagnostic)) return false;
        const auto resource = gResources.find(view->second.object);
        if (resource == gResources.end() || resource->second.id != view->second.resource)
            return fail("Consumer CBV buffer was not tracked at descriptor creation");
        if (out.resource != resource->first) return fail("Consumer CBV descriptor owner differs from the current buffer");
        out.descriptorHeap = heap->object; out.descriptor = {heap->gpu+index*heap->increment}; out.descriptorHeapBirth = heap->birth;
        return true;
    } catch (...) { return fail("Consumer CBV metadata resolution threw"); }
}
bool ResolveComputeConstantBinding(const ComputeBindings& bindings, UINT shaderRegister, UINT registerSpace,
    BoundConstantBinding& out, ConstantBufferDiagnostic* diagnostic) noexcept
{
    out = {};
    if (diagnostic) *diagnostic = {};
    const auto fail = [&](const char* reason) { out = {}; if (diagnostic) diagnostic->reason = reason; return false; };
    if (!Tracking() || !bindings.root || bindings.heaps.size() > 2 ||
        !gMetadataHealthy.load(std::memory_order_acquire)) return fail("Consumer native binding is unavailable");
    try
    {
        // Identity-only POD rows use catalog/mirror guards; slot readers still drain the snapshot gate.
        std::scoped_lock lock(gLifetimeMutex);
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return fail("Consumer root/heap metadata is unhealthy");
        if (!BirthAvailable(bindings.rootBirth,bindings.root)) return fail("Consumer native root birth is stale");
        if ((!bindings.heapBirths.empty() || NativeTracking()) && bindings.heapBirths.size() != bindings.heaps.size()) return fail("Consumer heap births are unavailable");
        for (size_t i=0;i<bindings.heapBirths.size();++i) if (!BirthAvailable(bindings.heapBirths[i],bindings.heaps[i])) return fail("Consumer heap birth is stale");
        const auto layout = gRootLayouts.find(bindings.root);
        if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != bindings.rootBirth) return fail("Consumer root layout is unavailable");
        UINT parameter = UINT_MAX;
        uint64_t descriptorOffset = 0;
        bool tableBinding = false;
        for (const auto& [index,descriptor] : layout->second.computeDescriptors)
        {
            if (descriptor.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || descriptor.shaderRegister != shaderRegister ||
                descriptor.registerSpace != registerSpace) continue;
            if (parameter != UINT_MAX) return fail("Consumer b-register maps to multiple root parameters");
            parameter = index;
        }
        for (const auto& [index,ranges] : layout->second.tables)
        {
            if (!layout->second.computeVisibleTables.contains(index)) continue;
            for (const auto& range : ranges)
            {
                if (range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || range.registerSpace != registerSpace) continue;
                if (!ValidComputeRange(range)) return fail("Consumer CBV table range is invalid");
                if (shaderRegister < range.shaderRegister ||
                    (range.count != UINT_MAX && uint64_t(shaderRegister)-range.shaderRegister >= range.count)) continue;
                const uint64_t offset = uint64_t(range.offset)+shaderRegister-range.shaderRegister;
                if (offset > UINT_MAX || parameter != UINT_MAX ||
                    !UniqueComputeMapping(ranges,{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT(offset),shaderRegister,registerSpace}))
                    return fail("Consumer CBV register mapping is ambiguous");
                parameter = index; tableBinding = true; descriptorOffset = offset;
            }
        }
        if (parameter == UINT_MAX) return fail("Consumer b-register is absent from compute root layout");
        if (diagnostic) { diagnostic->rootParameter = parameter; diagnostic->table = tableBinding; }
        out.root = bindings.root; out.rootParameter = parameter; out.rootBirth = bindings.rootBirth;
        if (!tableBinding)
        {
            bool found = false;
            for (const auto& view : bindings.views) if (view.parameter == parameter)
            {
                if (found || view.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || !view.address || view.address%256)
                    return fail("Consumer root CBV argument is missing or invalid");
                found = true; out.address = view.address;
            }
            if (!found) return fail("Consumer root CBV argument is missing");
            if (diagnostic) { diagnostic->address = out.address; diagnostic->reason = "native root CBV"; }
            return true;
        }
        uint64_t tableBase = 0;
        for (const auto& [index,handle] : bindings.tables) if (index == parameter)
        {
            if (tableBase || !handle.ptr) return fail("Consumer CBV table base is missing or duplicated");
            tableBase = handle.ptr;
        }
        if (!tableBase) return fail("Consumer CBV table base is missing");
        if (diagnostic) diagnostic->tableBase = tableBase;
        const Heap* heap = nullptr;
        // A native command list binds at most two heaps. Never scan the heap/resource registry.
        for (const auto object : bindings.heaps)
        {
            const auto found = gHeaps.find(object);
            if (found == gHeaps.end()) continue;
            const auto& candidate = found->second;
            if (candidate.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || !candidate.gpu || !candidate.increment ||
                tableBase < candidate.gpu || tableBase-candidate.gpu >= uint64_t(candidate.count)*candidate.increment ||
                (tableBase-candidate.gpu)%candidate.increment) continue;
            if (heap) return fail("Consumer CBV table matches multiple bound heaps");
            heap = &candidate;
        }
        if (!heap) return fail("Consumer CBV shader-visible heap is unavailable");
        const uint64_t index = (tableBase-heap->gpu)/heap->increment+descriptorOffset;
        if (index >= heap->count || index*heap->increment > UINT64_MAX-heap->gpu)
            return fail("Consumer CBV slot is outside its heap");
        out.descriptorHeap = heap->object; out.descriptor = {heap->gpu+index*heap->increment}; out.tableBase = tableBase; out.descriptorHeapBirth = heap->birth;
        if (diagnostic) { diagnostic->descriptorCpu = heap->cpu+index*heap->increment; diagnostic->reason = "native table CBV"; }
        // The title reads this same volatile slot. Do not infer its GPUVA or inspect its buffer owner.
        return true;
    } catch (...) { return fail("Consumer native binding resolution threw"); }
}
bool ResolveComputeConstantBinding(ID3D12GraphicsCommandList* cmd, UINT shaderRegister, UINT registerSpace,
    BoundConstantBinding& out, ConstantBufferDiagnostic* diagnostic) noexcept
{
    out = {};
    if (diagnostic) *diagnostic = {};
    if (!BindingTracking() || gInternal || !cmd || !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        // Identity-only POD rows use catalog/mirror guards; slot readers still drain the snapshot gate.
        ComputeBindings bindings;
        {
            std::scoped_lock lock(gMirrorMutex);
            const auto list = gMirror.find(cmd);
            if (list == gMirror.end() || !MirrorAvailable(list->second,cmd)) return false;
            bindings.root = list->second.compute.object; bindings.heaps = list->second.heaps;
            bindings.receiverBirth = list->second.receiverBirth; bindings.rootBirth = list->second.compute.birth;
            bindings.pipelineBirth = list->second.pipelineBirth; bindings.heapBirths = list->second.heapBirths;
            for (const auto& [parameter,handle] : list->second.compute.tables) bindings.tables.emplace_back(parameter,D3D12_GPU_DESCRIPTOR_HANDLE{handle});
            for (const auto& [parameter,view] : list->second.compute.views) bindings.views.push_back({parameter,D3D12_DESCRIPTOR_RANGE_TYPE(view.first),view.second});
        }
        return ResolveComputeConstantBinding(bindings,shaderRegister,registerSpace,out,diagnostic);
    } catch (...) { if (diagnostic) diagnostic->reason = "Consumer native binding snapshot threw"; return false; }
}
bool ValidateComputeConstantBinding(const ComputeBindings& current, UINT shaderRegister, UINT registerSpace,
    const BoundConstantBinding& expected) noexcept
{
    BoundConstantBinding actual;
    return expected.root && ResolveComputeConstantBinding(current,shaderRegister,registerSpace,actual) &&
        actual.root == expected.root && actual.rootParameter == expected.rootParameter && actual.address == expected.address &&
        actual.descriptorHeap == expected.descriptorHeap && actual.descriptor.ptr == expected.descriptor.ptr && actual.tableBase == expected.tableBase &&
        actual.rootBirth == expected.rootBirth && actual.descriptorHeapBirth == expected.descriptorHeapBirth;
}
bool ResolveGraphicsConstantBinding(const ComputeBindings& bindings, UINT shaderRegister, UINT registerSpace,
    BoundConstantBinding& out, ConstantBufferDiagnostic* diagnostic) noexcept
{
    out = {};
    if (diagnostic) *diagnostic = {};
    const auto fail = [&](const char* reason) { out = {}; if (diagnostic) diagnostic->reason = reason; return false; };
    if (!Tracking() || !bindings.root || bindings.heaps.size() > 2 ||
        !gMetadataHealthy.load(std::memory_order_acquire)) return fail("Consumer native binding is unavailable");
    try
    {
        // Identity-only POD rows use catalog/mirror guards; slot readers still drain the snapshot gate.
        std::scoped_lock lock(gLifetimeMutex);
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return fail("Consumer root/heap metadata is unhealthy");
        if (!BirthAvailable(bindings.rootBirth,bindings.root)) return fail("Consumer native root birth is stale");
        if ((!bindings.heapBirths.empty() || NativeTracking()) && bindings.heapBirths.size() != bindings.heaps.size()) return fail("Consumer heap births are unavailable");
        for (size_t i=0;i<bindings.heapBirths.size();++i) if (!BirthAvailable(bindings.heapBirths[i],bindings.heaps[i])) return fail("Consumer heap birth is stale");
        const auto layout = gRootLayouts.find(bindings.root);
        if (layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != bindings.rootBirth) return fail("Consumer root layout is unavailable");
        UINT parameter = UINT_MAX;
        uint64_t descriptorOffset = 0;
        bool tableBinding = false;
        for (const auto& [index,descriptor] : layout->second.pixelDescriptors)
        {
            if (descriptor.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || descriptor.shaderRegister != shaderRegister ||
                descriptor.registerSpace != registerSpace) continue;
            if (parameter != UINT_MAX) return fail("Consumer b-register maps to multiple root parameters");
            parameter = index;
        }
        for (const auto& [index,ranges] : layout->second.tables)
        {
            if (!layout->second.pixelVisibleTables.contains(index)) continue;
            for (const auto& range : ranges)
            {
                if (range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || range.registerSpace != registerSpace) continue;
                if (!ValidComputeRange(range)) return fail("Consumer CBV table range is invalid");
                if (shaderRegister < range.shaderRegister ||
                    (range.count != UINT_MAX && uint64_t(shaderRegister)-range.shaderRegister >= range.count)) continue;
                const uint64_t offset = uint64_t(range.offset)+shaderRegister-range.shaderRegister;
                if (offset > UINT_MAX || parameter != UINT_MAX ||
                    !UniqueComputeMapping(ranges,{D3D12_DESCRIPTOR_RANGE_TYPE_CBV,UINT(offset),shaderRegister,registerSpace}))
                    return fail("Consumer CBV register mapping is ambiguous");
                parameter = index; tableBinding = true; descriptorOffset = offset;
            }
        }
        if (parameter == UINT_MAX) return fail("Consumer b-register is absent from pixel root layout");
        if (diagnostic) { diagnostic->rootParameter = parameter; diagnostic->table = tableBinding; }
        out.root = bindings.root; out.rootParameter = parameter; out.rootBirth = bindings.rootBirth;
        if (!tableBinding)
        {
            bool found = false;
            for (const auto& view : bindings.views) if (view.parameter == parameter)
            {
                if (found || view.kind != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || !view.address || view.address%256)
                    return fail("Consumer root CBV argument is missing or invalid");
                found = true; out.address = view.address;
            }
            if (!found) return fail("Consumer root CBV argument is missing");
            if (diagnostic) { diagnostic->address = out.address; diagnostic->reason = "native root CBV"; }
            return true;
        }
        uint64_t tableBase = 0;
        for (const auto& [index,handle] : bindings.tables) if (index == parameter)
        {
            if (tableBase || !handle.ptr) return fail("Consumer CBV table base is missing or duplicated");
            tableBase = handle.ptr;
        }
        if (!tableBase) return fail("Consumer CBV table base is missing");
        if (diagnostic) diagnostic->tableBase = tableBase;
        const Heap* heap = nullptr;
        // A native command list binds at most two heaps. Never scan the heap/resource registry.
        for (const auto object : bindings.heaps)
        {
            const auto found = gHeaps.find(object);
            if (found == gHeaps.end()) continue;
            const auto& candidate = found->second;
            if (candidate.type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || !candidate.gpu || !candidate.increment ||
                tableBase < candidate.gpu || tableBase-candidate.gpu >= uint64_t(candidate.count)*candidate.increment ||
                (tableBase-candidate.gpu)%candidate.increment) continue;
            if (heap) return fail("Consumer CBV table matches multiple bound heaps");
            heap = &candidate;
        }
        if (!heap) return fail("Consumer CBV shader-visible heap is unavailable");
        const uint64_t index = (tableBase-heap->gpu)/heap->increment+descriptorOffset;
        if (index >= heap->count || index*heap->increment > UINT64_MAX-heap->gpu)
            return fail("Consumer CBV slot is outside its heap");
        out.descriptorHeap = heap->object; out.descriptor = {heap->gpu+index*heap->increment}; out.tableBase = tableBase; out.descriptorHeapBirth = heap->birth;
        if (diagnostic) { diagnostic->descriptorCpu = heap->cpu+index*heap->increment; diagnostic->reason = "native table CBV"; }
        // The title reads this same volatile slot. Do not infer its GPUVA or inspect its buffer owner.
        return true;
    } catch (...) { return fail("Consumer native binding resolution threw"); }
}
bool ValidateGraphicsConstantBinding(const ComputeBindings& current, UINT shaderRegister, UINT registerSpace,
    const BoundConstantBinding& expected) noexcept
{
    BoundConstantBinding actual;
    return expected.root && ResolveGraphicsConstantBinding(current,shaderRegister,registerSpace,actual) &&
        actual.root == expected.root && actual.rootParameter == expected.rootParameter && actual.address == expected.address &&
        actual.descriptorHeap == expected.descriptorHeap && actual.descriptor.ptr == expected.descriptor.ptr && actual.tableBase == expected.tableBase &&
        actual.rootBirth == expected.rootBirth && actual.descriptorHeapBirth == expected.descriptorHeapBirth;
}
bool ResolveComputeTable(ID3D12GraphicsCommandList* cmd, UINT parameter, std::vector<BoundResource>& out) noexcept
{
    out.clear();
    if (!BindingTracking() || gInternal || !cmd || !gMetadataHealthy.load(std::memory_order_acquire)) return false;
    try
    {
        NativeSnapshotExclusive metadataSnapshot;
        Mirror::Root root; std::vector<ID3D12DescriptorHeap*> heaps; Mirror snapshot;
        {
            std::scoped_lock lock(gMirrorMutex); MetadataMutation mutation;
            if (!gMetadataHealthy.load(std::memory_order_acquire)) return false;
            const auto list = gMirror.find(cmd);
            if (list == gMirror.end() || !MirrorAvailable(list->second,cmd)) return false;
            snapshot = list->second; root = snapshot.compute; heaps = snapshot.heaps;
        }
        const auto binding = root.tables.find(parameter);
        if (!root.object || binding == root.tables.end()) return false;
        std::scoped_lock lock(gLifetimeMutex); MetadataMutation mutation;
        if (!gMetadataHealthy.load(std::memory_order_acquire)) return false;
        const auto layout = gRootLayouts.find(root.object);
        if (!MirrorAvailable(snapshot,cmd) || layout == gRootLayouts.end() || !layout->second.complete || layout->second.birth != root.birth) return false;
        const auto table = layout->second.tables.find(parameter);
        if (table == layout->second.tables.end()) return false;
        const Heap* heap = nullptr;
        const auto base = binding->second;
        for (const auto object : heaps)
        {
            const auto found = gHeaps.find(object);
            if (found == gHeaps.end()) continue;
            const auto& candidate = found->second;
            if (candidate.gpu && candidate.increment && base >= candidate.gpu &&
                base-candidate.gpu < uint64_t(candidate.count)*candidate.increment &&
                (base-candidate.gpu)%candidate.increment == 0) { heap = &candidate; break; }
        }
        if (!heap) return false;
        const uint64_t first = (base-heap->gpu)/heap->increment;
        for (const auto& range : table->second)
        {
            if (range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_SRV && range.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV) continue;
            if (range.count > 512 || first+range.offset+range.count > heap->count) return false;
            for (uint32_t i=0;i<range.count;++i)
            {
                const uint64_t index = first+range.offset+i;
                const auto view = gViews.find(heap->cpu+index*heap->increment);
                if (view == gViews.end() || view->second.kind != range.kind || !view->second.snapshotSupported || !FreshView(view->second,heap)) continue;
                const auto resource = gResources.find(view->second.object);
                if (resource == gResources.end() || resource->second.id != view->second.resource) continue;
                out.push_back({resource->first,resource->second.desc,DXGI_FORMAT(view->second.format),
                    D3D12_DESCRIPTOR_RANGE_TYPE(range.kind),range.offset+i,uint32_t(index),view->second.subresource,resource->second.birth});
            }
        }
        std::sort(out.begin(),out.end(),[](const auto& a,const auto& b) {
            return std::tie(a.descriptorOffset,a.descriptorIndex,a.kind) < std::tie(b.descriptorOffset,b.descriptorIndex,b.kind); });
        return true;
    } catch (...) { MetadataFailed("Compute table resolution allocation failed"); out.clear(); return false; }
}
bool Enabled() noexcept { return gEnabled.load(std::memory_order_relaxed); }
void BeginCreationTracking(bool recorder) noexcept
{
    gSurveyBindings.store(recorder,std::memory_order_release);
    gTracking.store(true,std::memory_order_release);
}
void SetPassHashes(const std::string& list) noexcept
{
    try
    {
        std::vector<std::string> parsed; std::string token;
        auto flush = [&] {
            if (token.size() >= 8 && token.size() <= 64 && token.find_first_not_of("0123456789abcdef") == token.npos) parsed.push_back(token);
            token.clear(); };
        for (const char c : list)
        {
            if (c == ',' || c == ';' || c == ' ' || c == '\t') flush();
            else token.push_back(char(std::tolower(static_cast<unsigned char>(c))));
        }
        flush();
        std::scoped_lock lock(gPassHashMutex); gPassHashes = std::move(parsed);
    } catch (...) {}
}
bool Internal() noexcept { return gInternal; }
std::mutex& SubmissionMutex() { return gSubmissionMutex; }
bool PrepareResourceMetadata(ID3D12Resource* object, PreparedResource& out) noexcept
{
    out = {};
    if (!Tracking() || gInternal || !object || NrdBridgeBirth::InMetadataScope()) return false;
    if (NativeTracking() && !NrdBridgeNativeBirth::ObserveReleaseCoverage(object)) return false;
    try
    {
        out.object = object; out.description = object->GetDesc();
        if (out.description.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER) out.address = object->GetGPUVirtualAddress();
        return true;
    } catch (...) { out = {}; MetadataFailed("Resource metadata preparation failed"); return false; }
}
bool PrepareHeapMetadata(ID3D12Device* device, ID3D12DescriptorHeap* object, PreparedHeap& out) noexcept
{
    out = {};
    if (!Tracking() || gInternal || !device || !object || NrdBridgeBirth::InMetadataScope()) return false;
    if (NativeTracking() && !NrdBridgeNativeBirth::ObserveReleaseCoverage(object)) return false;
    try
    {
        out.object = object; out.description = object->GetDesc();
        if (out.description.Type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && out.description.Type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV &&
            out.description.Type != D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER)
        { out = {}; return false; }
        out.cpu = object->GetCPUDescriptorHandleForHeapStart().ptr;
        out.gpu = (out.description.Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE) ? object->GetGPUDescriptorHandleForHeapStart().ptr : 0;
        out.increment = device->GetDescriptorHandleIncrementSize(out.description.Type);
        return out.cpu && out.increment && out.description.NumDescriptors;
    } catch (...) { out = {}; MetadataFailed("Heap metadata preparation failed"); return false; }
}
bool PrepareRootMetadata(ID3D12RootSignature* root, const void* bytes, size_t length, PreparedRoot& out) noexcept
{
    out = {};
    if (!Tracking() || gInternal || !root || !bytes || length > (1u<<20) || NrdBridgeBirth::InMetadataScope()) return false;
    if (NativeTracking() && !NrdBridgeNativeBirth::ObserveReleaseCoverage(root)) return false;
    try
    {
        InternalScope internal;
        if (FAILED(root->SetPrivateData(RootBlobId,UINT(length),bytes))) throw std::runtime_error("Root blob storage failed");
        out.object = root; out.layout = std::make_shared<RootLayout>(ReadRoot(root)); return true;
    } catch (...) { out = {}; MetadataFailed("Root metadata preparation failed"); return false; }
}
bool PublishResourceMetadata(const PreparedResource& prepared, const NrdBridgeBirth::Token& birth) noexcept
{
    if (!Tracking() || !prepared.object || !birth || birth->Address() != prepared.object) return false;
    try
    {
        NrdBridgeBirth::CurrentGuard current(birth);
        if (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy()) return false;
        NativeSnapshotShared snapshot; if (!Tracking()) return false;
        std::scoped_lock catalog(gLifetimeMutex); MetadataMutation mutation;
        const auto old = gResources.find(prepared.object);
        if (old != gResources.end() && old->second.birth && old->second.birth != birth) return false;
        ResourceDescription description {prepared.description,prepared.address};
        auto& resource = Register(prepared.object,&description);
        resource.birth = birth; resource.initial = prepared.initial; resource.initialKnown = prepared.initialKnown;
        resource.heap = uint64_t(reinterpret_cast<uintptr_t>(prepared.heap)); resource.offset = prepared.offset;
        PublishNativeResource(resource); return true;
    } catch (...) { MetadataFailed("Prepared resource publication failed"); return false; }
}
bool PublishHeapMetadata(const PreparedHeap& prepared, const NrdBridgeBirth::Token& birth) noexcept
{
    if (!Tracking() || !prepared.object || !birth || birth->Address() != prepared.object || !prepared.cpu || !prepared.increment) return false;
    try
    {
        NrdBridgeBirth::CurrentGuard current(birth);
        if (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy()) return false;
        NativeSnapshotShared snapshot; if (!Tracking()) return false;
        std::scoped_lock catalog(gLifetimeMutex); MetadataMutation mutation;
        if (const auto found = gHeaps.find(prepared.object); found != gHeaps.end())
        {
            auto& heap = found->second;
            if ((heap.birth && heap.birth != birth) || heap.cpu != prepared.cpu || heap.gpu != prepared.gpu ||
                heap.count != prepared.description.NumDescriptors || heap.increment != prepared.increment || heap.type != uint32_t(prepared.description.Type)) return false;
            heap.birth = birth; PublishNativeHeap(heap); return true;
        }
        Heap heap {prepared.object,prepared.cpu,prepared.gpu,prepared.description.NumDescriptors,prepared.increment,uint32_t(prepared.description.Type)};
        heap.birth = birth; auto& stored = gHeaps.emplace(prepared.object,std::move(heap)).first->second;
        // SAMPLER handles belong to a distinct typed space. Only its object/birth
        // participates in heap seeding; it must never shadow resource-view slots.
        if (prepared.description.Type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV || prepared.description.Type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV)
            gCpuHeaps[prepared.cpu] = prepared.object;
        PublishNativeHeap(stored); return true;
    } catch (...) { MetadataFailed("Prepared heap publication failed"); return false; }
}
bool PublishRootMetadata(const PreparedRoot& prepared, const NrdBridgeBirth::Token& birth) noexcept
{
    if (!Tracking() || !prepared.object || !prepared.layout || !birth || birth->Address() != prepared.object) return false;
    try
    {
        auto layout = *std::static_pointer_cast<RootLayout>(prepared.layout); layout.birth = birth;
        BuildTextureRegisterIndexes(layout); // Cold allocation precedes all Birth/catalog scopes.
        NrdBridgeBirth::CurrentGuard current(birth);
        if (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy()) return false;
        NativeSnapshotShared snapshot; if (!Tracking()) return false;
        std::scoped_lock catalog(gLifetimeMutex); MetadataMutation mutation;
        if (const auto found = gRootLayouts.find(prepared.object); found != gRootLayouts.end() && found->second.birth && found->second.birth != birth) return false;
        gRootLayouts[prepared.object] = std::move(layout); return true;
    } catch (...) { MetadataFailed("Prepared root publication failed"); return false; }
}
NrdBridgeBirth::Token CaptureRelease(void* object) noexcept
{
    return Tracking() && !OwnedRelease() && object ? NrdBridgeBirth::Capture(object) : NrdBridgeBirth::Token{};
}
bool PrepareRetirementEffects(RetirementEffects& effects) noexcept
{
    if (NrdBridgeBirth::InMetadataScope()) return false;
    try { if (!effects.opaqueOwner) effects.opaqueOwner = std::make_shared<RetiredMetadata>(); return true; }
    catch (...) { effects.failure = "Retirement owner preparation failed"; MetadataFailed(effects.failure); return false; }
}
bool DetachReleaseMetadata(const NrdBridgeBirth::Token& birth, RetirementEffects& effects) noexcept
{
    if (!birth || birth->Live() || !effects.opaqueOwner || !NrdBridgeBirth::InMetadataAction()) return false;
    effects.birth = birth; effects.object = birth->Address(); effects.notify = Tracking();
    auto& detached = *std::static_pointer_cast<RetiredMetadata>(effects.opaqueOwner);
    try
    {
        NativeSnapshotShared snapshot;
        const bool native = NativeTracking();
        if (native)
        {
            detached.nativeResource = gNativeResources.EraseIf(reinterpret_cast<ID3D12Resource*>(effects.object),
                [&](const auto& node) { return node.birth == birth; });
            detached.nativeHeap = gNativeHeaps.EraseIf(reinterpret_cast<ID3D12DescriptorHeap*>(effects.object),
                [&](const auto& node) { return node.birth == birth; });
            if (detached.nativeResource && detached.nativeResource->address)
                gNativeBuffers.Erase(detached.nativeResource->address,detached.nativeResource->id);
            if (detached.nativeHeap && (detached.nativeHeap->type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV ||
                detached.nativeHeap->type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV))
                gNativeHeapRanges[detached.nativeHeap->type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV ? 1 : 0].Erase(detached.nativeHeap->cpu,detached.nativeHeap->id);
        }
        {
            // Cold identity extraction is brief. Native affected-slot draining
            // occurs afterwards, with no catalog writer held during a long copy.
            std::scoped_lock catalog(gLifetimeMutex);
            auto* object = reinterpret_cast<ID3D12Resource*>(effects.object);
            if (const auto found = gResources.find(object); found != gResources.end() && found->second.birth == birth)
            {
                uint64_t handle = 0;
                if (!native) while (found->second.handles.PopAny(handle))
                {
                    const auto view = gViews.find(handle);
                    if (view != gViews.end() && view->second.object == object && view->second.resource == found->second.id) EraseView(handle);
                }
                if (found->second.va)
                {
                    gBufferAddresses.Erase(found->second.va,found->second.id);
                    const auto address = gAddresses.find(found->second.va);
                    if (address != gAddresses.end() && address->second == object) gAddresses.erase(address);
                }
                detached.resource = gResources.extract(found);
            }
            auto* root = reinterpret_cast<ID3D12RootSignature*>(effects.object);
            if (const auto found = gRootLayouts.find(root); found != gRootLayouts.end() && found->second.birth == birth) detached.root = gRootLayouts.extract(found);
            auto* heap = reinterpret_cast<ID3D12DescriptorHeap*>(effects.object);
            if (const auto found = gHeaps.find(heap); found != gHeaps.end() && found->second.birth == birth)
            {
                uint64_t handle = 0;
                if (!native) while (found->second.views.PopAny(handle))
                {
                    const auto view = gViews.find(handle);
                    if (view != gViews.end() && view->second.heapKnown && view->second.descriptorHeap == uint64_t(reinterpret_cast<uintptr_t>(heap))) EraseView(handle);
                }
                if (const auto cpu = gCpuHeaps.find(found->second.cpu); cpu != gCpuHeaps.end() && cpu->second == heap) gCpuHeaps.erase(cpu);
                detached.heap = gHeaps.extract(found);
            }
            auto* pso = reinterpret_cast<ID3D12PipelineState*>(effects.object);
            if (const auto found = gPipelineBirths.find(pso); found != gPipelineBirths.end() && found->second == birth) gPipelineBirths.erase(found);
            if (const auto found = gPipelineMetadata.find(pso); found != gPipelineMetadata.end() && found->second.birth == birth) detached.pipeline = gPipelineMetadata.extract(found);
            auto* signature = reinterpret_cast<ID3D12CommandSignature*>(effects.object);
            if (const auto found = gIndirectSignatures.find(signature); found != gIndirectSignatures.end() && found->second.birth == birth) detached.signature = gIndirectSignatures.extract(found);
        }
        if (native)
        {
            const auto drain = [&](const std::shared_ptr<FrameSurveyMetadata::DescriptorHandles>& handles, const auto& matches,
                const FrameSurveyMetadata::DescriptorShardMask* legalShards = nullptr)
            {
                if (!handles) return;
                for (size_t shard=0;shard<FrameSurveyMetadata::DescriptorShards;++shard)
                {
                    if (legalShards && !legalShards->Contains(shard)) continue;
                    std::scoped_lock slot(gViewMutexes[shard]); uint64_t handle=0;
                    while (handles->PopShard(shard,handle))
                    {
                        const auto view=gViews.find(handle);
                        if (view != gViews.end() && matches(view->second)) NativeEraseView(handle);
                    }
                }
            };
            const auto resourceHandles = detached.nativeResource ? detached.nativeResource->handles :
                detached.resource ? detached.resource.mapped().handles.Share() : std::shared_ptr<FrameSurveyMetadata::DescriptorHandles>{};
            drain(resourceHandles,[&](const ViewInfo& view) {
                return detached.nativeResource ? view.resourceOwner == detached.nativeResource :
                    detached.resource && view.object == detached.resource.key() && view.resource == detached.resource.mapped().id;
            });
            const auto heapHandles = detached.nativeHeap ? detached.nativeHeap->views :
                detached.heap ? detached.heap.mapped().views.Share() : std::shared_ptr<FrameSurveyMetadata::DescriptorHandles>{};
            // Resource owners above retain arbitrary-shard coverage. Only a
            // prepared native heap supplies an immutable legal-address bound.
            drain(heapHandles,[&](const ViewInfo& view) {
                return detached.nativeHeap ? view.heapOwner == detached.nativeHeap :
                    detached.heap && view.heapKnown && view.descriptorHeap == uint64_t(reinterpret_cast<uintptr_t>(detached.heap.key()));
            },detached.nativeHeap ? &detached.nativeHeap->legalDescriptorShards : nullptr);
        }
        {
            std::scoped_lock mirrorLock(gMirrorMutex);
            auto* receiver = reinterpret_cast<ID3D12GraphicsCommandList*>(effects.object);
            if (const auto found = gMirror.find(receiver); found != gMirror.end() && found->second.receiverBirth == birth)
            {
                UpdateMirrorOwners(receiver,MirrorReferences(found->second),MirrorReferences(Mirror{}));
                detached.list = gMirror.extract(found);
            }
            if (const auto owners = gMirrorOwners.find(effects.object); owners != gMirrorOwners.end())
            {
                for (auto it = owners->second.begin(); it != owners->second.end();)
                {
                    const auto found = gMirror.find(*it);
                    if (found == gMirror.end()) { it = owners->second.erase(it); continue; }
                    auto& mirror = found->second;
                    if (mirror.pso == effects.object && mirror.pipelineBirth == birth) { mirror.pso = nullptr; mirror.pipelineBirth.reset(); }
                    if (mirror.compute.object == effects.object && mirror.compute.birth == birth) mirror.compute = {};
                    if (mirror.graphics.object == effects.object && mirror.graphics.birth == birth) mirror.graphics = {};
                    for (size_t i=mirror.heaps.size(); i; --i) if (mirror.heaps[i-1] == effects.object &&
                        mirror.heapBirths.size() == mirror.heaps.size() && mirror.heapBirths[i-1] == birth)
                    {
                        mirror.heaps.erase(mirror.heaps.begin()+i-1); mirror.heapBirths.erase(mirror.heapBirths.begin()+i-1);
                        mirror.compute.tables.clear(); mirror.graphics.tables.clear();
                    }
                    if (MirrorReferences(mirror).Contains(effects.object)) ++it; else it = owners->second.erase(it);
                }
                if (owners->second.empty()) detached.references = gMirrorOwners.extract(owners);
            }
        }
        return true;
    }
    catch (...)
    {
        gMetadataHealthy.store(false,std::memory_order_release);
        effects.failure = "Birth release metadata invalidation failed"; return false;
    }
}
void NotifyRelease(RetirementEffects& effects) noexcept
{
    if (NrdBridgeBirth::InMetadataScope())
    {
        gMetadataHealthy.store(false,std::memory_order_release);
        const char* empty = nullptr; gDeferredMetadataFailure.compare_exchange_strong(empty,"Release notification entered under Birth guard",std::memory_order_release);
        return;
    }
    if (effects.failure) Fail(effects.failure);
    if (effects.notify)
    {
        effects.notify = false;
        if (effects.birth)
        { if (const auto observer = gBirthReleaseObserver.load(std::memory_order_acquire)) observer(effects.birth); }
        else if (const auto observer = gReleaseObserver.load(std::memory_order_acquire)) observer(effects.object);
    }
    effects.opaqueOwner.reset(); FlushMetadataFailure();
}


void ResourceCreated(ID3D12Resource* object, D3D12_RESOURCE_STATES initial, ID3D12Heap* heap, uint64_t offset) noexcept
{
    if (!Tracking() || gInternal || !object) return;
    if (NativeTracking())
    {
        PreparedResource prepared;
        if (PrepareResourceMetadata(object,prepared))
        {
            prepared.initial = initial; prepared.initialKnown = true; prepared.heap = heap; prepared.offset = offset;
            const auto birth = NrdBridgeNativeBirth::Prepare(object);
            if (!PublishResourceMetadata(prepared,birth)) MetadataFailed("Current resource publication was denied");
        }
        FlushMetadataFailure(); return;
    }
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return; EnsureResourceRegistered(object);
        std::scoped_lock lock(gLifetimeMutex); MetadataMutation mutation; auto& resource = Register(object);
        resource.initial = initial; resource.initialKnown = true;
        resource.heap = uint64_t(reinterpret_cast<uintptr_t>(heap)); resource.offset = offset;
    } catch (...) { MetadataFailed("Resource metadata allocation failed"); }
}
void ResourceCreatedWithLayout(ID3D12Resource* object, D3D12_BARRIER_LAYOUT, ID3D12Heap* heap, uint64_t offset) noexcept
{
    if (!Tracking() || gInternal || !object) return;
    if (NativeTracking())
    {
        PreparedResource prepared;
        if (PrepareResourceMetadata(object,prepared))
        {
            prepared.heap = heap; prepared.offset = offset;
            const auto birth = NrdBridgeNativeBirth::Prepare(object);
            if (!PublishResourceMetadata(prepared,birth)) MetadataFailed("Current enhanced resource publication was denied");
        }
        FlushMetadataFailure(); return;
    }
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return; EnsureResourceRegistered(object);
        std::scoped_lock lock(gLifetimeMutex); MetadataMutation mutation; auto& resource = Register(object);
        resource.initialKnown = false; // Enhanced layouts cannot be cast to legacy resource-state bits.
        resource.heap = uint64_t(reinterpret_cast<uintptr_t>(heap)); resource.offset = offset;
    } catch (...) { MetadataFailed("Enhanced resource metadata allocation failed"); }
}
void RootCreated(ID3D12RootSignature* root, const void* bytes, size_t length) noexcept
{
    if (!Tracking() || gInternal || !root || !bytes || length > (1u<<20)) return;
    if (NativeTracking())
    {
        PreparedRoot prepared;
        if (PrepareRootMetadata(root,bytes,length,prepared))
        {
            const auto birth = NrdBridgeNativeBirth::Prepare(root);
            if (!PublishRootMetadata(prepared,birth)) MetadataFailed("Current root publication was denied");
        }
        FlushMetadataFailure(); return;
    }
    if (FAILED(root->SetPrivateData(RootBlobId,UINT(length),bytes))) { MetadataFailed("Root signature metadata storage failed"); return; }
    try { auto layout = ReadRoot(root); std::scoped_lock lock(gLifetimeMutex); MetadataMutation mutation; gRootLayouts[root] = std::move(layout); }
    catch (...) { MetadataFailed("Root signature layout allocation failed"); }
}
void PipelineCreated(ID3D12PipelineState* pso, const D3D12_COMPUTE_PIPELINE_STATE_DESC& desc) noexcept
{
    if (!Tracking() || gInternal || !pso) return;
    try
    {
        if (!PublishPipelineBirth(pso)) { MetadataFailed("Current pipeline metadata publication was denied"); return; }
        Json data = {{"shader_hashes",{{"CS",RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(desc.CS.pShaderBytecode),desc.CS.BytecodeLength})}}},
            {"hash_known",desc.CS.BytecodeLength != 0},{"root_hash",ReadRoot(desc.pRootSignature).hash}};
        auto text = data.dump(); StorePipelineMetadata(pso,text); pso->SetPrivateData(PipelineId,UINT(text.size()),text.data());
        if (const auto observer = gPipelineObserver.load(std::memory_order_acquire))
            observer(pso,data["shader_hashes"]["CS"].get_ref<const std::string&>().c_str());
        if (const auto observer = gGraphicsPipelineObserver.load(std::memory_order_acquire)) observer(pso,nullptr);
    } catch (...) { MetadataFailed("Compute shader hash failed"); }
}
void PipelineCreated(ID3D12PipelineState* pso, const D3D12_GRAPHICS_PIPELINE_STATE_DESC& desc) noexcept
{
    if (!Tracking() || gInternal || !pso) return;
    try
    {
        if (!PublishPipelineBirth(pso)) { MetadataFailed("Current pipeline metadata publication was denied"); return; }
        Json hashes = Json::object();
        auto add = [&](const char* name,const D3D12_SHADER_BYTECODE& shader) {
            if (shader.BytecodeLength) hashes[name] = RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(shader.pShaderBytecode),shader.BytecodeLength}); };
        add("VS",desc.VS); add("PS",desc.PS); add("GS",desc.GS); add("HS",desc.HS); add("DS",desc.DS);
        const auto text = Json{{"shader_hashes",hashes},{"hash_known",!hashes.empty()},{"root_hash",ReadRoot(desc.pRootSignature).hash}}.dump();
        StorePipelineMetadata(pso,text);
        pso->SetPrivateData(PipelineId,UINT(text.size()),text.data());
        if (const auto observer = gPipelineObserver.load(std::memory_order_acquire)) observer(pso,nullptr);
        if (const auto observer = gGraphicsPipelineObserver.load(std::memory_order_acquire))
            observer(pso,hashes.contains("PS") ? hashes["PS"].get_ref<const std::string&>().c_str() : nullptr);
    } catch (...) { MetadataFailed("Graphics shader hash failed"); }
}
void PipelineCreated(ID3D12PipelineState* pso, const D3D12_PIPELINE_STATE_STREAM_DESC& desc) noexcept
{
    if (!Tracking() || gInternal || !pso) return;
    try
    {
        if (!PublishPipelineBirth(pso)) { MetadataFailed("Current pipeline metadata publication was denied"); return; }
        struct Parser : ID3DX12PipelineParserCallbacks
        {
            Json shaders = Json::object(); ID3D12RootSignature* root = nullptr;
            void RootSignatureCb(ID3D12RootSignature* value) override { root = value; }
            void Add(const char* name,const D3D12_SHADER_BYTECODE& value) {
                if (value.BytecodeLength) shaders[name] = RRTraceAdditiveIO::Sha256({static_cast<const uint8_t*>(value.pShaderBytecode),value.BytecodeLength}); }
            void CSCb(const D3D12_SHADER_BYTECODE& v) override { Add("CS",v); }
            void VSCb(const D3D12_SHADER_BYTECODE& v) override { Add("VS",v); }
            void PSCb(const D3D12_SHADER_BYTECODE& v) override { Add("PS",v); }
            void GSCb(const D3D12_SHADER_BYTECODE& v) override { Add("GS",v); }
            void HSCb(const D3D12_SHADER_BYTECODE& v) override { Add("HS",v); }
            void DSCb(const D3D12_SHADER_BYTECODE& v) override { Add("DS",v); }
        } parser;
        const auto result = D3DX12ParsePipelineStream(desc,&parser);
        // Hash pointed-to bytecode, NEVER process-local stream pointer bytes.
        const auto text = Json{{"shader_hashes",parser.shaders},{"hash_known",SUCCEEDED(result)&&!parser.shaders.empty()},
            {"stream_parse_hresult",int64_t(result)},{"root_hash",ReadRoot(parser.root).hash}}.dump();
        StorePipelineMetadata(pso,text);
        pso->SetPrivateData(PipelineId,UINT(text.size()),text.data());
        if (const auto observer = gPipelineObserver.load(std::memory_order_acquire))
            observer(pso,SUCCEEDED(result) && parser.shaders.contains("CS") ?
                parser.shaders["CS"].get_ref<const std::string&>().c_str() : nullptr);
        if (const auto observer = gGraphicsPipelineObserver.load(std::memory_order_acquire))
            observer(pso,SUCCEEDED(result) && parser.shaders.contains("PS") ?
                parser.shaders["PS"].get_ref<const std::string&>().c_str() : nullptr);
    } catch (...) { MetadataFailed("Pipeline stream shader hash failed"); }
}
void Released(void* object) noexcept
{
    if (!Tracking() || OwnedRelease() || !object) return;
    if (NativeTracking())
    {
        const auto birth = CaptureRelease(object);
        if (birth)
        {
            NrdBridgeNativeBirth::RetirementScope retirement;
            if (!retirement.Valid()) return;
            NrdBridgeBirth::CurrentGuard current(birth); current.Retire(); return;
        }
    }
    bool lifetimeEntry = false;
    try
    {
        std::shared_lock catalog(gLifetimeMutex);
        lifetimeEntry = gResources.contains(reinterpret_cast<ID3D12Resource*>(object)) ||
            gHeaps.contains(reinterpret_cast<ID3D12DescriptorHeap*>(object)) ||
            gRootLayouts.contains(reinterpret_cast<ID3D12RootSignature*>(object)) ||
            gPipelineMetadata.contains(reinterpret_cast<ID3D12PipelineState*>(object)) ||
            gIndirectSignatures.contains(reinterpret_cast<ID3D12CommandSignature*>(object));
    } catch (...) { MetadataFailed("Release catalog lookup failed"); }
    try
    {
        if (lifetimeEntry)
        {
        NativeSnapshotExclusive metadataSnapshot;
        std::scoped_lock lock(gLifetimeMutex);
        auto* resource = reinterpret_cast<ID3D12Resource*>(object);
        if (const auto found = gResources.find(resource); found != gResources.end())
        {
            uint64_t handle = 0;
            while (found->second.handles.PopAny(handle))
            {
                const auto view = gViews.find(handle);
                if (view != gViews.end() && view->second.object == resource && view->second.resource == found->second.id) EraseView(handle);
            }
            if (found->second.va)
            {
                gBufferAddresses.Erase(found->second.va,found->second.id);
                const auto address = gAddresses.find(found->second.va);
                if (address != gAddresses.end() && address->second == resource) gAddresses.erase(address);
            }
            gResources.erase(found);
        }
        gRootLayouts.erase(reinterpret_cast<ID3D12RootSignature*>(object));
        gPipelineBirths.erase(reinterpret_cast<ID3D12PipelineState*>(object));
        gPipelineMetadata.erase(reinterpret_cast<ID3D12PipelineState*>(object));
        gIndirectSignatures.erase(reinterpret_cast<ID3D12CommandSignature*>(object));
        auto* heap = reinterpret_cast<ID3D12DescriptorHeap*>(object);
        if (const auto found = gHeaps.find(heap); found != gHeaps.end())
        {
            uint64_t handle = 0;
            while (found->second.views.PopAny(handle))
            {
                const auto view = gViews.find(handle);
                if (view != gViews.end() && view->second.heapKnown && view->second.descriptorHeap == uint64_t(reinterpret_cast<uintptr_t>(heap))) EraseView(handle);
            }
            if (const auto cpu = gCpuHeaps.find(found->second.cpu); cpu != gCpuHeaps.end() && cpu->second == heap) gCpuHeaps.erase(cpu);
            gHeaps.erase(found);
        }
        }
    } catch (...) { MetadataFailed("Resource release registry invalidation failed"); }
    try
    {
        std::scoped_lock lock(gMirrorMutex);
        auto* releasedList = reinterpret_cast<ID3D12GraphicsCommandList*>(object);
        if (const auto list = gMirror.find(releasedList); list != gMirror.end())
        { UpdateMirrorOwners(releasedList,MirrorReferences(list->second),MirrorReferences(Mirror{})); gMirror.erase(list); }
        if (const auto owners = gMirrorOwners.find(object); owners != gMirrorOwners.end())
        {
            auto affected = std::move(owners->second); gMirrorOwners.erase(owners);
            for (auto* cmd : affected)
            {
                const auto found = gMirror.find(cmd); if (found == gMirror.end()) continue;
                auto& mirror = found->second;
                if (mirror.pso == object) mirror.pso = nullptr;
                if (mirror.compute.object == object) mirror.compute = {};
                if (mirror.graphics.object == object) mirror.graphics = {};
                if (std::erase(mirror.heaps,reinterpret_cast<ID3D12DescriptorHeap*>(object)))
                { mirror.compute.tables.clear(); mirror.graphics.tables.clear(); }
            }
        }
    } catch (...) { MetadataFailed("Release binding invalidation failed"); }
    if (const auto observer = gReleaseObserver.load(std::memory_order_acquire)) observer(object);
}
void HeapCreated(ID3D12Device* device, ID3D12DescriptorHeap* object) noexcept
{
    if (!Tracking() || gInternal || !object) return;
    if (NativeTracking())
    {
        PreparedHeap prepared;
        if (PrepareHeapMetadata(device,object,prepared))
        {
            const auto birth = NrdBridgeNativeBirth::Prepare(object);
            if (!PublishHeapMetadata(prepared,birth)) MetadataFailed("Current heap publication was denied");
        }
        FlushMetadataFailure(); return;
    }
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        const auto desc = object->GetDesc();
        if (desc.Type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && desc.Type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV) return;
        const auto cpu = object->GetCPUDescriptorHandleForHeapStart().ptr;
        const auto gpu = (desc.Flags&D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE) ? object->GetGPUDescriptorHandleForHeapStart().ptr : 0;
        const auto increment = device->GetDescriptorHandleIncrementSize(desc.Type);
        std::scoped_lock lock(gLifetimeMutex); MetadataMutation mutation;
        if (const auto existing = gHeaps.find(object); existing != gHeaps.end())
        {
            const auto& heap = existing->second;
            if (heap.cpu != cpu || heap.gpu != gpu || heap.count != desc.NumDescriptors || heap.increment != increment || heap.type != uint32_t(desc.Type))
                throw std::runtime_error("A live descriptor heap was re-registered with inconsistent native ranges");
            return; // Multiple creation observers must retain the occupied-slot reverse index.
        }
        gHeaps.emplace(object,Heap{object,cpu,gpu,desc.NumDescriptors,increment,uint32_t(desc.Type)});
        gCpuHeaps[cpu] = object;
    } catch (...) { MetadataFailed("Descriptor heap metadata allocation failed"); }
}
void View(D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc) noexcept
{
    if (!Tracking() || gInternal) return;
    try
    {
        if (NativeTracking()) { NativeStoreConstantView(handle.ptr,desc); return; }
        std::shared_lock catalog(gLifetimeMutex);
        std::scoped_lock slot(gViewMutexes[FrameSurveyMetadata::DescriptorShard(handle.ptr)]); MetadataMutation mutation;
        if (!desc || !desc->BufferLocation || desc->BufferLocation%256 || !desc->SizeInBytes ||
            desc->SizeInBytes%256 || desc->SizeInBytes > 65536) { EraseView(handle.ptr); return; }
        BoundConstantBuffer buffer;
        const bool known = ResolveBufferAddress(desc->BufferLocation,desc->SizeInBytes,desc->SizeInBytes,buffer);
        ViewInfo view {known ? buffer.resource : nullptr,known ? buffer.resourceGeneration : 0,
            D3D12_DESCRIPTOR_RANGE_TYPE_CBV,uint32_t(DXGI_FORMAT_UNKNOWN),0,false};
        view.descriptorCpu = handle.ptr; view.rootVa = desc->BufferLocation; view.constantBytes = desc->SizeInBytes;
        if (const auto heap = HeapAtCpu(handle.ptr))
        {
            view.descriptorHeap = uint64_t(reinterpret_cast<uintptr_t>(heap->object)); view.heapKnown = true;
        }
        ReplaceView(view);
    } catch (...) { MetadataFailed("Constant buffer view metadata allocation failed"); }
}
void View(ID3D12Resource* resource, D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_SHADER_RESOURCE_VIEW_DESC* desc) noexcept
{
    try
    {
        UINT mip = 0, slice = 0; bool supported = !desc;
        if (desc && desc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2D) { mip = desc->Texture2D.MostDetailedMip; supported = desc->Texture2D.PlaneSlice == 0; }
        if (desc && desc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2DARRAY)
        { mip = desc->Texture2DArray.MostDetailedMip; slice = desc->Texture2DArray.FirstArraySlice; supported = desc->Texture2DArray.ArraySize == 1 && desc->Texture2DArray.PlaneSlice == 0; }
        StoreView(resource,handle.ptr,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,desc ? desc->Format : DXGI_FORMAT_UNKNOWN,mip,slice,supported,!desc || desc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2D);
    } catch (...) { MetadataFailed("SRV metadata allocation failed"); }
}
void View(ID3D12Resource* resource, D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc) noexcept
{
    try
    {
        UINT mip = 0, slice = 0; bool supported = !desc;
        if (desc && desc->ViewDimension == D3D12_UAV_DIMENSION_TEXTURE2D) { mip = desc->Texture2D.MipSlice; supported = desc->Texture2D.PlaneSlice == 0; }
        if (desc && desc->ViewDimension == D3D12_UAV_DIMENSION_TEXTURE2DARRAY)
        { mip = desc->Texture2DArray.MipSlice; slice = desc->Texture2DArray.FirstArraySlice; supported = desc->Texture2DArray.ArraySize == 1 && desc->Texture2DArray.PlaneSlice == 0; }
        StoreView(resource,handle.ptr,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,desc ? desc->Format : DXGI_FORMAT_UNKNOWN,mip,slice,supported,!desc || desc->ViewDimension == D3D12_UAV_DIMENSION_TEXTURE2D);
    } catch (...) { MetadataFailed("UAV metadata allocation failed"); }
}
void View(ID3D12Resource* resource, D3D12_CPU_DESCRIPTOR_HANDLE handle, const D3D12_RENDER_TARGET_VIEW_DESC* desc) noexcept
{
    try
    {
        UINT mip = 0, slice = 0; bool supported = !desc;
        if (desc && desc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2D) { mip = desc->Texture2D.MipSlice; supported = desc->Texture2D.PlaneSlice == 0; }
        if (desc && desc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2DARRAY)
        { mip = desc->Texture2DArray.MipSlice; slice = desc->Texture2DArray.FirstArraySlice; supported = desc->Texture2DArray.ArraySize == 1 && desc->Texture2DArray.PlaneSlice == 0; }
        StoreView(resource,handle.ptr,4,desc ? desc->Format : DXGI_FORMAT_UNKNOWN,mip,slice,supported,!desc || desc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2D);
    } catch (...) { MetadataFailed("RTV metadata allocation failed"); }
}
void CopyDescriptors(ID3D12Device* device, UINT nd, const D3D12_CPU_DESCRIPTOR_HANDLE* dst, const UINT* dn,
    UINT ns, const D3D12_CPU_DESCRIPTOR_HANDLE* src, const UINT* sn, D3D12_DESCRIPTOR_HEAP_TYPE type) noexcept
{
    if (!Tracking() || gInternal || !device || !dst || !src ||
        (type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV && type != D3D12_DESCRIPTOR_HEAP_TYPE_RTV)) return;
    try
    {
        const auto stride = device->GetDescriptorHandleIncrementSize(type);
        if (NativeTracking()) { NativeCopyDescriptors(stride,nd,dst,dn,ns,src,sn,type); return; }
        std::shared_lock catalog(gLifetimeMutex); MetadataMutation mutation;
        UINT di = 0, si = 0, d = 0, s = 0;
        while (di<nd && si<ns)
        {
            const UINT dc = dn ? dn[di] : 1, sc = sn ? sn[si] : 1;
            if (d >= dc) { ++di; d = 0; continue; }
            if (s >= sc) { ++si; s = 0; continue; }
            const auto firstDestination = dst[di].ptr+uint64_t(d)*stride;
            auto* destinationHeap = HeapAtCpu(firstDestination);
            UINT count = std::min(dc-d,sc-s);
            if (destinationHeap) count = std::min(count,destinationHeap->count-UINT((firstDestination-destinationHeap->cpu)/stride));
            for (UINT i=0;i<count;++i)
            {
#ifdef FSRD_NRD_BRIDGE_TEST
                if (gCopyFailureAfterForTesting == 0) { gCopyFailureAfterForTesting = -1; throw std::bad_alloc(); }
                if (gCopyFailureAfterForTesting > 0) --gCopyFailureAfterForTesting;
#endif
                const auto dh = dst[di].ptr+uint64_t(d++)*stride, sh = src[si].ptr+uint64_t(s++)*stride;
                const auto sourceShard = FrameSurveyMetadata::DescriptorShard(sh), destinationShard = FrameSurveyMetadata::DescriptorShard(dh);
                std::unique_lock<DescriptorMutex> first(gViewMutexes[std::min(sourceShard,destinationShard)],std::defer_lock);
                std::unique_lock<DescriptorMutex> second;
                first.lock();
                if (sourceShard != destinationShard) second = std::unique_lock<DescriptorMutex>(gViewMutexes[std::max(sourceShard,destinationShard)]);
                const auto source = gViews.find(sh);
                const bool known = source != gViews.end() && FreshView(source->second,HeapAtCpu(sh));
                const auto contents = known ? source->second : ViewInfo{};
                // Snapshot before mutation, including an exact same-slot copy.
                if (known)
                {
                    const auto resource = gResources.find(contents.object);
                    const bool live = resource != gResources.end() && resource->second.id == contents.resource;
                    // Unproven CBV declarations survive native copies for diagnostics, never as borrowed resources.
                    const bool declaration = contents.kind == D3D12_DESCRIPTOR_RANGE_TYPE_CBV && !contents.object &&
                        !contents.resource && contents.rootVa && contents.constantBytes;
                    if ((live || declaration) && destinationHeap)
                    {
                        auto copy = contents; copy.descriptorCpu = dh;
                        copy.descriptorHeap = uint64_t(reinterpret_cast<uintptr_t>(destinationHeap->object));
                        copy.heapKnown = true;
                        ReplaceView(copy);
                    }
                    else EraseView(dh);
                }
                else EraseView(dh);
            }
        }
    } catch (...) { MetadataFailed("Descriptor copy metadata allocation failed"); }
}

void Reset(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* initial) noexcept
{
    if ((!BindingTracking() && !Recording()) || gInternal || !cmd) return;
    NrdBridgeBirth::Token initialBirth;
    { std::shared_lock catalog(gLifetimeMutex); if (const auto found = gPipelineBirths.find(initial); found != gPipelineBirths.end()) initialBirth = found->second; }
    Mirrored(cmd,[&](Mirror& mirror) { const auto receiver = mirror.receiverBirth; mirror = {}; mirror.receiverBirth = receiver; mirror.pso = initial; mirror.pipelineBirth = initialBirth; },true);
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return;
        auto& list = gService->lists[cmd]; list = {};
        list.id = ++gNextList; list.resetObserved = true; list.pso = ReadPipeline(initial);
    } catch (...) { Fail("Command-list reset metadata failed"); }
}
void Close(ID3D12GraphicsCommandList* cmd, HRESULT result) noexcept
{
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return;
        if (FAILED(result)) { Fail("Original command-list Close failed"); return; }
        auto& list = GetList(cmd); list.closed = true;
        if (list.payload) gService->trace.SealSurveyBatch(list.payload);
    } catch (...) { Fail("Command-list Close metadata failed"); }
}
void SetPipeline(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* pso) noexcept
{
    if ((!BindingTracking() && !Recording()) || gInternal || !cmd) return;
    NrdBridgeBirth::Token pipelineBirth;
    { std::shared_lock catalog(gLifetimeMutex); if (const auto found = gPipelineBirths.find(pso); found != gPipelineBirths.end()) pipelineBirth = found->second; }
    Mirrored(cmd,[&](Mirror& mirror) { mirror.pso = pso; mirror.pipelineBirth = pipelineBirth; },true);
    if (!Recording()) return;
    try { std::scoped_lock lock(gRecordMutex); if (!Recording()) return; GetList(cmd).pso = ReadPipeline(pso); }
    catch (...) { Fail("Pipeline binding metadata failed"); }
}
void RootBinding(ID3D12GraphicsCommandList* cmd, bool graphics, ID3D12RootSignature* root) noexcept
{
    if ((!BindingTracking() && !Recording()) || gInternal || !cmd) return;
    NrdBridgeBirth::Token rootBirth;
    { std::shared_lock catalog(gLifetimeMutex); if (const auto found = gRootLayouts.find(root); found != gRootLayouts.end()) rootBirth = found->second.birth; }
    Mirrored(cmd,[&](Mirror& mirror) {
        auto& state = graphics ? mirror.graphics : mirror.compute;
        if (state.object != root || state.birth != rootBirth) { state = {}; state.object = root; state.birth = rootBirth; } },true);
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        auto& state = graphics ? list.graphics : list.compute;
        const uint64_t identity = uint64_t(reinterpret_cast<uintptr_t>(root));
        // Rebinding the same signature preserves root arguments (D3D12 contract).
        if (state.identity == identity) return;
        state = {}; state.identity = identity; state.layout = ReadRoot(root);
    } catch (...) { Fail("Root signature binding failed"); }
}
void DescriptorHeaps(ID3D12GraphicsCommandList* cmd, UINT count, ID3D12DescriptorHeap* const* heaps) noexcept
{
    std::vector<NrdBridgeBirth::Token> births;
    try
    {
        if (BindingTracking() && !gInternal && heaps)
        {
            births.resize(count); std::shared_lock catalog(gLifetimeMutex);
            for (UINT i=0;i<count;++i) if (const auto found = gHeaps.find(heaps[i]); found != gHeaps.end()) births[i] = found->second.birth;
        }
    } catch (...) { MetadataFailed("Descriptor heap birth snapshot failed"); return; }
    Mirrored(cmd,[&](Mirror& mirror) {
        std::vector<ID3D12DescriptorHeap*> next;
        if (heaps) next.assign(heaps,heaps+count);
        if (next != mirror.heaps) { mirror.compute.tables.clear(); mirror.graphics.tables.clear(); }
        mirror.heaps = std::move(next); mirror.heapBirths = std::move(births); },true);
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        std::vector<ID3D12DescriptorHeap*> next;
        if (heaps) next.assign(heaps,heaps+count);
        if (next != list.heaps) { list.compute.tables.clear(); list.graphics.tables.clear(); }
        list.heaps = std::move(next);
    } catch (...) { Fail("Descriptor heap binding failed"); }
}
void RootView(ID3D12GraphicsCommandList* cmd, bool graphics, UINT index, UINT kind, D3D12_GPU_VIRTUAL_ADDRESS va) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) { (graphics ? mirror.graphics : mirror.compute).views[index] = {kind,va}; });
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        (graphics ? list.graphics : list.compute).views[index] = {kind,va};
    } catch (...) { Fail("Root GPU virtual address binding failed"); }
}
void Table(ID3D12GraphicsCommandList* cmd, bool graphics, UINT index, D3D12_GPU_DESCRIPTOR_HANDLE handle) noexcept
{
    Mirrored(cmd,[&](Mirror& mirror) { (graphics ? mirror.graphics : mirror.compute).tables[index] = handle.ptr; });
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        (graphics ? list.graphics : list.compute).tables[index] = handle.ptr;
    } catch (...) { Fail("Root table binding metadata failed"); }
}
void RenderTargets(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_CPU_DESCRIPTOR_HANDLE* handles, BOOL contiguous) noexcept
{
    if (!Recording()) return;
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd); list.targets.clear();
        NativeSnapshotExclusive metadataSnapshot;
        if (!gMetadataHealthy.load(std::memory_order_acquire) || !Recording()) return;
        std::scoped_lock lifetime(gLifetimeMutex);
        UINT stride = 0;
        if (contiguous && count && handles)
            if (const auto* heap = HeapAtCpu(handles[0].ptr)) stride = heap->increment;
        for (UINT i=0;handles && i<count;++i)
        {
            const auto handle = contiguous ? handles[0].ptr+uint64_t(i)*stride : handles[i].ptr;
            const auto found = gViews.find(handle); if (found != gViews.end()) list.targets.push_back(found->second);
            else Count("RTV_descriptor_unavailable");
        }
    } catch (...) { Fail("Render target binding metadata failed"); }
}
void Barrier(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_RESOURCE_BARRIER* barriers) noexcept
{
    if (!Recording() || !barriers) return;
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        for (UINT i=0;i<count;++i) if (barriers[i].Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION && barriers[i].Transition.pResource)
            EnsureResourceRegistered(barriers[i].Transition.pResource);
        std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        std::vector<std::pair<ViewInfo,D3D12_RESOURCE_STATES>> exits;
        {
        NativeSnapshotExclusive metadataSnapshot;
        if (!gMetadataHealthy.load(std::memory_order_acquire) || !Recording()) return;
        std::scoped_lock lifetime(gLifetimeMutex);
        for (UINT i=0;i<count;++i)
        {
            const auto& b = barriers[i];
            if (b.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING)
            {
                gService->manifest["aliasing"].push_back({{"list_id",list.id},{"after_local_pass",gNextPass},
                    {"before",uint64_t(reinterpret_cast<uintptr_t>(b.Aliasing.pResourceBefore))},
                    {"after",uint64_t(reinterpret_cast<uintptr_t>(b.Aliasing.pResourceAfter))}});
                continue; // Snapshots were already copied before this alias barrier.
            }
            if (b.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION || !b.Transition.pResource) continue;
            auto& r = Register(b.Transition.pResource);
            const UINT first = b.Transition.Subresource == D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES ? 0 : b.Transition.Subresource;
            const UINT last = b.Transition.Subresource == D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES ?
                UINT(r.desc.MipLevels)*r.desc.DepthOrArraySize : first+1;
            for (UINT sub=first;sub<last;++sub)
            {
                const auto key = std::make_pair(r.id,sub);
                const auto writable = D3D12_RESOURCE_STATE_UNORDERED_ACCESS | D3D12_RESOURCE_STATE_RENDER_TARGET;
                const auto imageKey = "r"+std::to_string(r.id)+"s"+std::to_string(sub);
                if (b.Flags == D3D12_RESOURCE_BARRIER_FLAG_NONE && (b.Transition.StateBefore&writable) &&
                    !(b.Transition.StateAfter&writable) && (!list.copied.contains(imageKey) || list.copied[imageKey] != list.lastPass))
                {
                    ViewInfo view {r.object,r.id,6,uint32_t(r.desc.Format),sub,true};
                    for (auto handle : r.handles)
                        if (gViews.at(handle).snapshotSupported && gViews.at(handle).subresource == sub)
                        { view.format = gViews.at(handle).format; break; }
                    exits.push_back({view,b.Transition.StateBefore});
                }
                if (b.Flags&D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY) { list.splitTransitions.insert(key); list.states.erase(key); }
                else { list.states[key] = b.Transition.StateAfter; list.splitTransitions.erase(key); }
            }
        }
        } // release resource lifetime lock before allocating readback storage
        for (const auto& [view,state] : exits)
        {
            const auto key = "r"+std::to_string(view.resource)+"s"+std::to_string(view.subresource);
            if (CopyImage(cmd,list,view,state,key,false) && !list.passes.empty())
                list.passes.back()["write_state_exit_candidates"].push_back({{"resource",view.resource},
                    {"subresource",view.subresource},{"view_format",view.format},{"writer_identity_inferred",true}});
        }
    } catch (...) { Fail("Resource barrier metadata failed"); }
}
void Event(ID3D12GraphicsCommandList* cmd, UINT metadata, const void* data, UINT size, int kind) noexcept
{
    if (!Recording()) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        if (kind < 0) { if (!list.events.empty()) list.events.pop_back(); return; }
        const auto decoded = FrameSurveyMetadata::DecodeMarker(metadata,data,size);
        if (decoded.first.empty()) Count("marker_decode_unavailable");
        list.marker = decoded.first;
        if (kind > 0 && list.events.size() < 64) list.events.push_back(decoded.first);
        if (gService->manifest["markers"].size() < 8192)
        {
            std::string hex; const auto* bytes = static_cast<const uint8_t*>(data);
            for (UINT i=0;bytes && i<std::min(size,512u);++i)
            { hex.push_back("0123456789abcdef"[bytes[i]>>4]); hex.push_back("0123456789abcdef"[bytes[i]&15]); }
            gService->manifest["markers"].push_back({{"list_id",list.id},{"metadata",metadata},{"kind",kind},
                {"text",decoded.first},{"encoding",decoded.second},{"raw_hex",hex},{"raw_bytes",size},
                {"format_arguments_expanded",false}});
        }
    } catch (...) { Fail("Debug event metadata failed"); }
}
void Pass(ID3D12GraphicsCommandList* cmd, const char* kind, std::span<const uint64_t> args) noexcept
{
    if (!Recording()) return;
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        if (gNextPass >= 16384) { Fail("One-frame pass cap reached (16384)"); return; }
        const bool graphics = std::string_view(kind).find("Draw") == 0 || std::string_view(kind) == "ExecuteBundle" || (std::string_view(kind) == "ExecuteIndirect" && args.size()>5 && args[5]);
        Json unresolved = Json::array(); auto bindings = Bindings(list,graphics,unresolved);
        list.writes.clear(); Json reads = Json::array(), writes = Json::array();
        std::vector<RecorderResource> descriptions;
        {
            std::scoped_lock lifetime(gLifetimeMutex);
            for (const auto& binding : bindings)
            {
                const auto found = gResources.find(binding.object);
                if (found == gResources.end() || found->second.id != binding.resource) { unresolved.push_back("stale_resource"); continue; }
                descriptions.push_back(RecorderDescription(found->second));
                const auto row = Json{{"resource",binding.resource},{"subresource",binding.subresource},
                    {"kind",binding.kind},{"view_format",binding.format},{"snapshot_supported",binding.snapshotSupported},
                    {"descriptor_cpu",binding.descriptorCpu},{"descriptor_gpu",binding.descriptorGpu},
                    {"descriptor_heap",binding.descriptorHeap},{"descriptor_index",binding.descriptorIndex},
                    {"root_parameter",binding.rootIndex},{"root_gpu_va",binding.rootVa}};
                if (binding.kind == D3D12_DESCRIPTOR_RANGE_TYPE_UAV || binding.kind == 4)
                { writes.push_back(row); list.writes.push_back(binding); }
                else reads.push_back(row);
            }
        }
        for (const auto& description : descriptions) Describe(description);
        if (!unresolved.empty()) Count("pass_binding_resolution_incomplete");
        auto& root = graphics ? list.graphics : list.compute;
        const uint64_t id = ++gNextPass; list.lastPass = id;
        Json row = {{"local_pass",id},{"kind",kind},{"arguments",std::vector<uint64_t>(args.begin(),args.end())},{"pso",list.pso},
            {"root_signature_pointer",root.identity},{"root_signature_sha256",root.layout.hash},
            {"events",list.events},{"marker",list.marker},{"reads",reads},{"writes",writes},
            {"binding_semantics","potential_access_from_bound_views_not_shader_instruction_proof"},
            {"unresolved",unresolved}};
        if (std::string_view(kind) == "ExecuteBundle") Count("bundle_inherited_binding_usage_unknown");
        if (!list.pso.value("hash_known",false)) Count("pass_shader_hash_unavailable");
        list.targeted = Targeted(list.pso);
        if (list.targeted) { row["targeted_snapshot"] = true; Count("targeted_passes"); }
        list.passes.push_back(std::move(row));
        // Root CBV bytes aid NRD-version/encoding investigation. Size is unknown
        // for a root descriptor, so save a bounded 1 KiB prefix, explicitly labelled.
        for (const auto& [index,view] : root.views)
        {
            // Targeted passes get their own allowance: their constants decode the denoiser's settings.
            if (view.first != D3D12_DESCRIPTOR_RANGE_TYPE_CBV || gService->constantReads >= (list.targeted ? 192u : 64u)) continue;
            ComPtr<ID3D12Resource> object; ID3D12Resource* pointer = nullptr; uint64_t offset = 0; uint32_t bytes = 0;
            {
                std::scoped_lock lifetime(gLifetimeMutex); auto upper = gAddresses.upper_bound(view.second);
                if (upper == gAddresses.begin()) continue;
                const auto found = gResources.find(std::prev(upper)->second);
                if (found == gResources.end() || view.second-found->second.va >= found->second.desc.Width) continue;
                pointer = found->first; offset = view.second-found->second.va;
                bytes = UINT(std::min<uint64_t>(1024,found->second.desc.Width-offset));
            }
            { InternalScope internal; object = pointer; }
            const auto key = "cbv_p"+std::to_string(list.lastPass)+"i"+std::to_string(index);
            const bool copied = CopyBuffer(cmd,list,object.Get(),key,offset,bytes);
            ++gService->constantReads;
            list.passes.back()["root_constant_buffers"].push_back({{"root_parameter",index},{"snapshot_key",key},
                {"available",copied},{"bytes",bytes},{"prefix_only",true},{"gpu_va",view.second}});
        }
    } catch (...) { Fail("Pass metadata allocation failed"); }
}
void SnapshotWrites(ID3D12GraphicsCommandList* cmd) noexcept
{
    if (!Recording()) return;
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
        if (list.inRenderPass) { list.targeted = false; return; } // CopyTextureRegion is illegal inside a render pass.
        const std::string prefix = list.targeted ? "p"+std::to_string(list.lastPass)+"_" : std::string();
        for (const auto& view : list.writes)
        {
            const auto expected = view.kind == 4 ? D3D12_RESOURCE_STATE_RENDER_TARGET : D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            auto state = expected;
            const auto found = list.states.find({view.resource,view.subresource});
            if (found != list.states.end()) state = found->second;
            // A texture written through a UAV by a dispatch must be in UNORDERED_ACCESS (no implicit promotion);
            // only targeted passes rely on that rule, their barrier may precede the recorded frame.
            else if (!list.targeted || view.kind != D3D12_DESCRIPTOR_RANGE_TYPE_UAV)
            { Count("bound_write_state_unproven_snapshot_skipped"); continue; }
            else Count("targeted_snapshot_state_from_uav_binding");
            if ((state&expected) == 0)
            { Count("bound_write_state_mismatch_snapshot_skipped"); continue; }
            CopyImage(cmd,list,view,state,
                prefix+"r"+std::to_string(view.resource)+"s"+std::to_string(view.subresource),false);
        }
        list.writes.clear(); list.targeted = false;
    } catch (...) { Fail("Last-writer texture snapshot failed"); }
}
void Submit(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* commands) noexcept
{
    if (!Recording() || !commands) return;
    try
    {
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return; Json ids = Json::array();
        for (UINT i=0;i<count;++i)
        {
            auto* cmd = reinterpret_cast<ID3D12GraphicsCommandList*>(commands[i]);
            const auto found = gService->lists.find(cmd);
            if (found == gService->lists.end()) { Count("submitted_list_not_recorded"); ids.push_back(nullptr); continue; }
            const auto& list = found->second; ids.push_back(list.id);
            gService->manifest["command_lists"].push_back({{"id",list.id},{"pointer",uint64_t(reinterpret_cast<uintptr_t>(cmd))},
                {"type",uint32_t(commands[i]->GetType())},{"reset_observed",list.resetObserved},{"closed",list.closed},
                {"passes",list.passes}});
        }
        gService->manifest["batches"].push_back({{"submission",gService->manifest["batches"].size()},
            {"queue",uint64_t(reinterpret_cast<uintptr_t>(queue))},{"queue_type",uint32_t(queue->GetDesc().Type)},{"lists",ids}});
    } catch (...) { Fail("Submission metadata allocation failed"); }
}
Status GetStatus()
{
    std::scoped_lock lock(gRecordMutex); auto result = gStatus;
    if (gService)
    {
        const auto trace = gService->trace.SurveyStatus(); result.folder = trace.folder;
        result.active = gService->requested || gService->recording || trace.active;
        if (!gService->requested && !gService->recording) { result.phase = trace.phase; result.message = trace.message; }
    }
    return result;
}
bool Request(uint32_t width, uint32_t height) noexcept
{
    if (!Enabled()) return false;
    try
    {
        std::scoped_lock lock(gRecordMutex);
        if (!width) width = gRenderWidth; if (!height) height = gRenderHeight;
        if (!gService) gService = std::make_unique<Service>();
        if (gService->trace.SurveyStatus().active || gService->recording || gService->requested) return false;
        if (!gService->trace.StartSurvey(width,height))
        { gStatus.message = "Render size unavailable, GAME_TRACE busy, or earlier GPU resources await Reset."; return false; }
        gRenderWidth = width; gRenderHeight = height; gService->requested = true;
        gService->startTick = GetTickCount64(); gStatus.active = true;
        gStatus.phase = "armed"; gStatus.message = "Waiting for a real Present boundary; close the overlay.";
        LOG_INFO("[FRAME_SURVEY] armed {}x{}",width,height); return true;
    } catch (...) { Fail("Survey request failed"); return false; }
}
void Present(IDXGISwapChain* swapchain, UINT flags) noexcept
{
    if (!Enabled() || (flags&DXGI_PRESENT_TEST)) return;
    try
    {
        std::scoped_lock submission(gSubmissionMutex);
        std::scoped_lock lock(gRecordMutex);
        if (!gService) return;
        if (gService->recording)
        {
            if (gService->swapchain != swapchain) return;
            ++gService->presents;
            if (TargetsConfigured() && !gService->targetedCopies && gService->presents < 8)
            { Count("targeted_mode_window_extended_presents"); return; }
            gService->manifest["presents_in_window"] = gService->presents;
            gService->recording = false; gRecording.store(false,std::memory_order_release);
            gService->manifest["resources"] = Json::array();
            for (const auto& [id,resource] : gService->resources) gService->manifest["resources"].push_back(resource);
            gService->manifest["end_tick_ms"] = GetTickCount64();
            gService->trace.FinishSurvey(gService->manifest.dump());
            gService->lists.clear(); gService->resources.clear(); gService->manifest = Json::object();
            gStatus.phase = "draining"; gStatus.message = "Waiting for verified GPU snapshots and background disk writes.";
            LOG_INFO("[FRAME_SURVEY] frame recorded; draining asynchronously");
        }
        else if (gService->requested && gService->trace.SurveyStatus().phase == "requested")
        {
            ComPtr<ID3D12Device> device;
            if (FAILED(swapchain->GetDevice(IID_PPV_ARGS(&device)))) device = gCreationDevice;
            if (!device) { Fail("Present has no D3D12 creation device"); return; }
            gService->device = device; gService->swapchain = swapchain;
            gService->requested = false; gService->recording = true;
            gService->lists.clear(); gService->resources.clear(); gService->candidates.clear();
            gService->candidateBytes = 0; gNextPass = 0;
            gService->constantReads = 0; gService->targetedCopies = 0; gService->presents = 0;
            gService->manifest = {{"capture_start","previous_real_Present"},{"capture_end","next_real_Present"},
                {"start_tick_ms",GetTickCount64()},{"batches",Json::array()},{"command_lists",Json::array()},
                {"snapshots",Json::array()},{"tags",Json::array()},{"markers",Json::array()},
                {"aliasing",Json::array()},{"coverage_gaps",Json::object()},
                {"candidate_limit",96},{"candidate_budget_bytes",192ull<<20},{"tag_reserved_bytes",64ull<<20},
                {"ordering","serialized_execute_hook_entry_order; cross_queue_GPU_dependencies_are_not_reconstructed"},
                {"snapshot_scope","immediate_post_potential_write_or_proven_write_state_exit; last_observed_content_per_resource_subresource_per_list"},
                {"shader_hash_algorithm","SHA256_of_DXIL_or_DXBC_bytecode_per_stage"},
                {"root_signature_hash_algorithm","SHA256_of_canonical_serialized_version_1_1_root_signature"},
                {"encoding_identification","unknown_until_offline_evidence"}};
            gRecording.store(true,std::memory_order_release);
            gStatus.phase = "recording"; gStatus.message = "Surveying one frame.";
            LOG_INFO("[FRAME_SURVEY] started at Present");
        }
        else if (gService->requested && GetTickCount64()-gService->startTick > 10000)
            Fail("Survey destination did not become ready within 10 seconds");
        else if (gService->trace.SurveyStatus().active && GetTickCount64()-gService->startTick > 30000)
            Fail("Survey GPU/disk drain did not complete within 30 seconds; uncertain GPU storage remains quarantined until Reset");
    } catch (...) { Fail("Present frame boundary failed"); }
}
void Evaluate(ID3D12GraphicsCommandList* cmd, unsigned feature, const NVSDK_NGX_Parameter* params) noexcept
{
    if (!Enabled() || gInternal || !params || !cmd ||
        (feature != unsigned(NVSDK_NGX_Feature_SuperSampling) && feature != unsigned(NVSDK_NGX_Feature_RayReconstruction))) return;
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        UINT width = 0, height = 0;
        params->Get(NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Width,&width);
        params->Get(NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Height,&height);
        if (!width) params->Get(NVSDK_NGX_Parameter_Width,&width);
        if (!height) params->Get(NVSDK_NGX_Parameter_Height,&height);
        std::scoped_lock lock(gRecordMutex);
        if (width && height)
        {
            if (Recording() && (width != gRenderWidth || height != gRenderHeight))
            { Fail("Render extent changed inside the surveyed frame"); return; }
            gRenderWidth = width; gRenderHeight = height;
        }
        if (!Recording()) return;
        auto& list = GetList(cmd);
        const bool rr = feature == unsigned(NVSDK_NGX_Feature_RayReconstruction);
        gService->manifest["evaluate_entries"].push_back({{"entry","NVSDK_NGX_D3D12_EvaluateFeature"},
            {"feature",feature},{"rr_feature",rr},{"list_id",list.id},{"after_local_pass",gNextPass},
            {"render_extent",{width,height}}});
        struct Tag { const char* name; const char* key; const char* bx; const char* by; };
        const Tag tags[] = {
            {"Color",NVSDK_NGX_Parameter_Color,NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_Y},
            {"Depth",NVSDK_NGX_Parameter_Depth,NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_Y},
            {"MotionVectors",NVSDK_NGX_Parameter_MotionVectors,NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X,NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_Y},
            {"Normals",NVSDK_NGX_Parameter_GBuffer_Normals,NVSDK_NGX_Parameter_DLSS_Input_Normals_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_Normals_Subrect_Base_Y},
            {"DiffuseAlbedo",NVSDK_NGX_Parameter_DiffuseAlbedo,NVSDK_NGX_Parameter_DLSS_Input_DiffuseAlbedo_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_DiffuseAlbedo_Subrect_Base_Y},
            {"SpecularAlbedo",NVSDK_NGX_Parameter_SpecularAlbedo,NVSDK_NGX_Parameter_DLSS_Input_SpecularAlbedo_Subrect_Base_X,NVSDK_NGX_Parameter_DLSS_Input_SpecularAlbedo_Subrect_Base_Y}
        };
        for (const auto& tag : tags)
        {
            ID3D12Resource* object = nullptr; params->Get(tag.key,&object);
            UINT x = 0, y = 0; if (tag.bx) params->Get(tag.bx,&x); if (tag.by) params->Get(tag.by,&y);
            Json row = {{"name",tag.name},{"parameter",tag.key},{"bound",object != nullptr},{"list_id",list.id},{"base",{x,y}}};
            if (object)
            {
                EnsureResourceRegistered(object);
                ViewInfo view; RecorderResource description; D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON; bool known = false;
                {
                    std::scoped_lock lifetime(gLifetimeMutex); auto& resource = Register(object); description = RecorderDescription(resource);
                    view = {object,resource.id,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,uint32_t(resource.desc.Format),0,true};
                    row["resource"] = resource.id;
                    const auto observed = list.states.find({resource.id,0});
                    if (observed != list.states.end()) { known = true; state = observed->second; }
                }
                Describe(description);
                row["state_observed_in_current_list"] = known;
                // Never guess a title texture state merely because NGX tagged it.
                if (known)
                {
                    const std::string key = "tag_"+std::string(tag.name)+"_r"+std::to_string(view.resource);
                    row["snapshot_key"] = key;
                    row["snapshot_available"] = CopyImage(cmd,list,view,state,key,true,x,y,width,height);
                }
                else { row["snapshot_available"] = false; Count("tag_state_unavailable"); }
            }
            gService->manifest["tags"].push_back(std::move(row));
        }
    } catch (...) { Fail("NGX entry/tag capture failed"); }
}
void TitleTag(ID3D12GraphicsCommandList* cmd, const char* name, ID3D12Resource* object, uint32_t state,
    uint32_t x, uint32_t y, uint32_t width, uint32_t height) noexcept
{
    if (!Recording() || !cmd) return;
    try
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        std::scoped_lock lock(gRecordMutex); if (!Recording()) return;
        auto& list = GetList(cmd);
        Json row = {{"name",name},{"source","current_Streamline_tag_call"},{"bound",object != nullptr},
            {"list_id",list.id},{"base",{x,y}},{"extent",{width,height}},
            {"state_provenance","caller_declared_Streamline_tag; no_cached_pointer_reuse"},
            {"content_stage","tag_call_before_Streamline_evaluation; may_precede_later_title_writes"}};
        if (object)
        {
            EnsureResourceRegistered(object);
            ViewInfo view; RecorderResource description;
            {
                std::scoped_lock lifetime(gLifetimeMutex); auto& resource = Register(object); description = RecorderDescription(resource);
                view = {object,resource.id,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,uint32_t(resource.desc.Format),0,true};
            }
            Describe(description); row["resource"] = view.resource;
            const std::string key = "sl_"+std::string(name)+"_r"+std::to_string(view.resource);
            row["snapshot_key"] = key;
            // Only shader-readable, COPY_SOURCE or COMMON declarations are
            // copied; writable/incomplete tag contracts remain metadata only.
            const bool readable = (state&(D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_COPY_SOURCE)) != 0 || state == 0;
            row["snapshot_available"] = readable && CopyImage(cmd,list,view,D3D12_RESOURCE_STATES(state),key,true,x,y,width,height);
            if (!row["snapshot_available"].get<bool>()) Count("Streamline_tag_snapshot_unavailable");
        }
        gService->manifest["tags"].push_back(std::move(row));
    } catch (...) { Fail("Current Streamline tag observation failed"); }
}

namespace
{
using IndirectFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,ID3D12CommandSignature*,UINT,
    ID3D12Resource*,UINT64,ID3D12Resource*,UINT64);
using CopyResourceFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,ID3D12Resource*,ID3D12Resource*);
using CopyTextureFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,const D3D12_TEXTURE_COPY_LOCATION*,UINT,UINT,UINT,
    const D3D12_TEXTURE_COPY_LOCATION*,const D3D12_BOX*);
using RootViewFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*,UINT,D3D12_GPU_VIRTUAL_ADDRESS);
using SignatureFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12Device*,const D3D12_COMMAND_SIGNATURE_DESC*,ID3D12RootSignature*,REFIID,void**);
using BeginRenderFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*,UINT,const D3D12_RENDER_PASS_RENDER_TARGET_DESC*,
    const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC*,D3D12_RENDER_PASS_FLAGS);
using EndRenderFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*);
using RaysFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*,const D3D12_DISPATCH_RAYS_DESC*);
using RayPipelineFn = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList4*,ID3D12StateObject*);
IndirectFn oIndirect = nullptr;
CopyResourceFn oCopyResource = nullptr;
CopyTextureFn oCopyTexture = nullptr;
RootViewFn oGraphicsSrv = nullptr, oGraphicsUav = nullptr, oGraphicsCbv = nullptr;
SignatureFn oSignature = nullptr;
BeginRenderFn oBeginRender = nullptr;
EndRenderFn oEndRender = nullptr;
RaysFn oRays = nullptr;
RayPipelineFn oRayPipeline = nullptr;
// Cyberpunk loads most pipelines from an ID3D12PipelineLibrary (GamePipelineLibrary.cache), which bypasses
// the Create*PipelineState hooks; the Load* calls carry the same descriptions, so they are hashed here.
using CreateLibraryFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12Device1*,const void*,SIZE_T,REFIID,void**);
using LoadGraphicsFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12PipelineLibrary*,LPCWSTR,const D3D12_GRAPHICS_PIPELINE_STATE_DESC*,REFIID,void**);
using LoadComputeFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12PipelineLibrary*,LPCWSTR,const D3D12_COMPUTE_PIPELINE_STATE_DESC*,REFIID,void**);
using LoadStreamFn = HRESULT(STDMETHODCALLTYPE*)(ID3D12PipelineLibrary1*,LPCWSTR,const D3D12_PIPELINE_STATE_STREAM_DESC*,REFIID,void**);
CreateLibraryFn oCreateLibrary = nullptr;
LoadGraphicsFn oLoadGraphics = nullptr;
LoadComputeFn oLoadCompute = nullptr;
LoadStreamFn oLoadStream = nullptr;
std::mutex gLibraryHookMutex;
HRESULT STDMETHODCALLTYPE LoadGraphics(ID3D12PipelineLibrary* library, LPCWSTR name, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* desc,
    REFIID riid, void** pso)
{
    const auto result = oLoadGraphics(library,name,desc,riid,pso);
    if (SUCCEEDED(result) && desc && pso && *pso && riid == __uuidof(ID3D12PipelineState))
        PipelineCreated(static_cast<ID3D12PipelineState*>(*pso),*desc);
    return result;
}
HRESULT STDMETHODCALLTYPE LoadCompute(ID3D12PipelineLibrary* library, LPCWSTR name, const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc,
    REFIID riid, void** pso)
{
    const auto result = oLoadCompute(library,name,desc,riid,pso);
    if (SUCCEEDED(result) && desc && pso && *pso && riid == __uuidof(ID3D12PipelineState))
        PipelineCreated(static_cast<ID3D12PipelineState*>(*pso),*desc);
    return result;
}
HRESULT STDMETHODCALLTYPE LoadStream(ID3D12PipelineLibrary1* library, LPCWSTR name, const D3D12_PIPELINE_STATE_STREAM_DESC* desc,
    REFIID riid, void** pso)
{
    const auto result = oLoadStream(library,name,desc,riid,pso);
    if (SUCCEEDED(result) && desc && pso && *pso && riid == __uuidof(ID3D12PipelineState))
        PipelineCreated(static_cast<ID3D12PipelineState*>(*pso),*desc);
    return result;
}
void HookLibrary(IUnknown* object) noexcept
{
    try
    {
        std::scoped_lock lock(gLibraryHookMutex);
        if (oLoadGraphics) return;
        ComPtr<ID3D12PipelineLibrary> library;
        if (FAILED(object->QueryInterface(IID_PPV_ARGS(&library)))) return;
        auto** table = *reinterpret_cast<void***>(library.Get());
        oLoadGraphics = reinterpret_cast<LoadGraphicsFn>(table[9]);
        oLoadCompute = reinterpret_cast<LoadComputeFn>(table[10]);
        ComPtr<ID3D12PipelineLibrary1> library1;
        if (SUCCEEDED(object->QueryInterface(IID_PPV_ARGS(&library1))))
            oLoadStream = reinterpret_cast<LoadStreamFn>((*reinterpret_cast<void***>(library1.Get()))[13]);
        LONG result = DetourTransactionBegin();
        if (result == NO_ERROR) result = DetourUpdateThread(GetCurrentThread());
        if (result == NO_ERROR) result = DetourAttach(reinterpret_cast<PVOID*>(&oLoadGraphics),reinterpret_cast<PVOID>(LoadGraphics));
        if (result == NO_ERROR) result = DetourAttach(reinterpret_cast<PVOID*>(&oLoadCompute),reinterpret_cast<PVOID>(LoadCompute));
        if (result == NO_ERROR && oLoadStream) result = DetourAttach(reinterpret_cast<PVOID*>(&oLoadStream),reinterpret_cast<PVOID>(LoadStream));
        if (result == NO_ERROR) result = DetourTransactionCommit(); else DetourTransactionAbort();
        if (result != NO_ERROR)
        {
            oLoadGraphics = nullptr; oLoadCompute = nullptr; oLoadStream = nullptr;
            LOG_ERROR("[FRAME_SURVEY] pipeline library load hooks failed: {:X}",result); return;
        }
        LOG_INFO("[FRAME_SURVEY] pipeline library loads hooked (stream {})",oLoadStream != nullptr);
    } catch (...) { LOG_ERROR("[FRAME_SURVEY] pipeline library hook exception"); }
}
HRESULT STDMETHODCALLTYPE CreateLibrary(ID3D12Device1* device, const void* blob, SIZE_T length, REFIID riid, void** library)
{
    const auto result = oCreateLibrary(device,blob,length,riid,library);
    if (SUCCEEDED(result) && library && *library && Tracking() && !gInternal) HookLibrary(static_cast<IUnknown*>(*library));
    return result;
}
const GUID SignatureId ={0xe971fb40,0x45a2,0x41ea,{0xa1,0x55,0x64,0xa8,0xc7,0xa4,0xfd,0x11}};
const GUID SignatureLayoutId = {0xe971fb41,0x45a2,0x41ea,{0xa1,0x55,0x64,0xa8,0xc7,0xa4,0xfd,0x11}};
void STDMETHODCALLTYPE Indirect(ID3D12GraphicsCommandList* cmd, ID3D12CommandSignature* signature, UINT count,
    ID3D12Resource* arguments, UINT64 argumentOffset, ID3D12Resource* counts, UINT64 countOffset)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::ExecuteIndirect,
        NrdBridgePerf::Detail::configured.load(std::memory_order_relaxed) && Tracking() && !gInternal);
    if (gInternal) { oIndirect(cmd,signature,count,arguments,argumentOffset,counts,countOffset); return; }
    const bool bridge = NrdBridge::StartupEnabled();
    NrdBridgeTitleCallbacks::Scope forwarding(NrdBridgeTitleCallbacks::Method::Indirect,bridge);
    if (forwarding.Nested())
    { InternalScope internal; oIndirect(cmd,signature,count,arguments,argumentOffset,counts,countOffset); return; }
    const bool preserve = bridge && NrdBridge::PreserveIndirectRecording(cmd,signature);
    if (bridge && !preserve)
    {
        // Only exact no-root-argument signatures with current pipeline/resource
        // proofs preserve bindings. Every indirect invocation still forwards.
        NrdBridge::OriginalDispatchDisposition(cmd,NrdBridge::DispatchKind::Indirect);
        D3D12Hooks::OnBridgeOpaqueCommand(cmd,false);
    }
    NrdBridgeLifetime::ScopedBorrow borrow(Recording());
    if (!borrow.Acquired())
    {
        { InternalScope internal; oIndirect(cmd,signature,count,arguments,argumentOffset,counts,countOffset); }
        if (bridge)
        {
            D3D12Hooks::OnBridgeOpaqueCommand(cmd,false);
            NrdBridge::InvalidateRecordingProof(cmd,"ExecuteIndirect invalidated an unavailable recording proof");
        }
        return;
    }
    uint32_t graphics = 0; UINT bytes = sizeof(graphics);
    if (signature) signature->GetPrivateData(SignatureId,&bytes,&graphics);
    const std::array<uint64_t,6> args {count,uint64_t(reinterpret_cast<uintptr_t>(arguments)),argumentOffset,
        uint64_t(reinterpret_cast<uintptr_t>(counts)),countOffset,graphics};
    Json layout = Json::object();
    if (Recording())
    {
        try
        {
            std::scoped_lock lock(gRecordMutex);
            if (Recording())
            {
                UINT length = 0;
                if (signature && SUCCEEDED(signature->GetPrivateData(SignatureLayoutId,&length,nullptr)) && length && length < 65536)
                {
                    std::string text(length,'\0');
                    if (SUCCEEDED(signature->GetPrivateData(SignatureLayoutId,&length,text.data()))) layout = Json::parse(text);
                }
                auto& list = GetList(cmd);
                // ExecuteIndirect changes these addresses per GPU command and
                // resets the affected root arguments afterwards. Do not attribute
                // its accesses, or the next pass's accesses, to stale CPU bindings.
                for (const auto& arg : layout.value("arguments",Json::array()))
                    if (arg.value("type",0u) >= 6 && arg.value("type",0u) <= 8)
                    {
                        (graphics ? list.graphics : list.compute).views.erase(arg.value("root_parameter",UINT_MAX));
                        Count("indirect_dynamic_root_view_access_unresolved");
                    }
            }
        } catch (...) { Fail("Indirect root argument metadata failed"); }
    }
    Pass(cmd,"ExecuteIndirect",args);
    if (Recording())
    {
        try
        {
            std::scoped_lock lock(gRecordMutex);
            if (Recording())
            {
                auto& list = GetList(cmd);
                const uint32_t stride = layout.value("byte_stride",0u);
                const uint32_t bytes = UINT(std::min<uint64_t>(65536,uint64_t(stride)*count));
                const auto key = "indirect_p"+std::to_string(list.lastPass);
                const bool copied = stride && CopyBuffer(cmd,list,arguments,key,argumentOffset,bytes);
                const bool countCopied = !counts || CopyBuffer(cmd,list,counts,key+"_count",countOffset,4);
                list.passes.back()["indirect"] = {{"signature",layout},{"argument_key",key},{"arguments_available",copied},
                    {"count_key",key+"_count"},{"count_buffer_present",counts != nullptr},{"count_available",countCopied},
                    {"maximum_command_count",count},{"saved_argument_bytes",bytes},{"argument_snapshot_capped",uint64_t(stride)*count > 65536}};
                if (!copied || !countCopied) Count("indirect_argument_snapshot_unavailable");
            }
        } catch (...) { Fail("Indirect argument capture failed"); }
    }
    // The runtime can expand ExecuteIndirect into internal command lists.
    // Observe this public invocation once; helper recordings are not separate
    // title submissions and must not allocate unfenced survey payloads.
    { InternalScope internal; oIndirect(cmd,signature,count,arguments,argumentOffset,counts,countOffset); }
    if (bridge && !preserve)
    {
        D3D12Hooks::OnBridgeOpaqueCommand(cmd,false);
        NrdBridge::InvalidateRecordingProof(cmd,"ExecuteIndirect invalidated the current root/dispatch proof");
        RootBinding(cmd,false,nullptr); RootBinding(cmd,true,nullptr);
        DescriptorHeaps(cmd,0,nullptr); SetPipeline(cmd,nullptr);
    }
    SnapshotWrites(cmd);
}
void RecordCopy(ID3D12GraphicsCommandList* cmd, ID3D12Resource* dst, UINT subresource, ID3D12Resource* src)
{
    if (!Recording() || !dst) return;
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return; EnsureResourceRegistered(dst); EnsureResourceRegistered(src);
    std::scoped_lock record(gRecordMutex); if (!Recording()) return; auto& list = GetList(cmd);
    ViewInfo write; RecorderResource destinationDescription,sourceDescription;
    {
        std::scoped_lock lifetime(gLifetimeMutex); auto& resource = Register(dst); destinationDescription = RecorderDescription(resource);
        write = {dst,resource.id,5,uint32_t(resource.desc.Format),subresource,true};
        Json reads = Json::array();
        if (src) { auto& source = Register(src); sourceDescription = RecorderDescription(source); reads.push_back({{"resource",source.id}}); }
        list.lastPass = ++gNextPass;
        list.passes.push_back({{"local_pass",list.lastPass},{"kind","Copy"},{"reads",reads},
            {"writes",Json::array({{{"resource",resource.id},{"subresource",subresource}}})},
            {"events",list.events},{"marker",list.marker}});
    }
    Describe(destinationDescription); if (src) Describe(sourceDescription);
    const auto observed = list.states.find({write.resource,subresource});
    if (observed == list.states.end() || observed->second != D3D12_RESOURCE_STATE_COPY_DEST)
    { Count("copy_destination_state_unproven_snapshot_skipped"); return; }
    CopyImage(cmd,list,write,D3D12_RESOURCE_STATE_COPY_DEST,
        "r"+std::to_string(write.resource)+"s"+std::to_string(subresource),false);
}
void STDMETHODCALLTYPE CopyResource(ID3D12GraphicsCommandList* cmd, ID3D12Resource* dst, ID3D12Resource* src)
{
    oCopyResource(cmd,dst,src);
    try { RecordCopy(cmd,dst,0,src); } catch (...) { Fail("Resource copy observation failed"); }
}
void STDMETHODCALLTYPE CopyTexture(ID3D12GraphicsCommandList* cmd, const D3D12_TEXTURE_COPY_LOCATION* dst, UINT x, UINT y, UINT z,
    const D3D12_TEXTURE_COPY_LOCATION* src, const D3D12_BOX* box)
{
    oCopyTexture(cmd,dst,x,y,z,src,box);
    if (!dst || dst->Type != D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX) return;
    try { RecordCopy(cmd,dst->pResource,dst->SubresourceIndex,src ? src->pResource : nullptr); }
    catch (...) { Fail("Texture copy observation failed"); }
}
void STDMETHODCALLTYPE GraphicsSrv(ID3D12GraphicsCommandList* cmd, UINT index, D3D12_GPU_VIRTUAL_ADDRESS va)
{ RootView(cmd,true,index,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,va); oGraphicsSrv(cmd,index,va); }
void STDMETHODCALLTYPE GraphicsUav(ID3D12GraphicsCommandList* cmd, UINT index, D3D12_GPU_VIRTUAL_ADDRESS va)
{ RootView(cmd,true,index,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,va); oGraphicsUav(cmd,index,va); }
void STDMETHODCALLTYPE GraphicsCbv(ID3D12GraphicsCommandList* cmd, UINT index, D3D12_GPU_VIRTUAL_ADDRESS va)
{ RootView(cmd,true,index,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,va); oGraphicsCbv(cmd,index,va); }
static bool SignatureCreationInterfaceMatches(REFIID iid) noexcept
{ return iid == __uuidof(ID3D12CommandSignature); }
HRESULT STDMETHODCALLTYPE Signature(ID3D12Device* device, const D3D12_COMMAND_SIGNATURE_DESC* desc,
    ID3D12RootSignature* root, REFIID iid, void** output)
{
    const auto result = oSignature(device,desc,root,iid,output);
    if (SUCCEEDED(result) && desc && output && *output)
    {
        // The bridge proof accepts an exact typed return only. Preserve the
        // recorder's legacy metadata behavior for other requested interfaces.
        if (SignatureCreationInterfaceMatches(iid))
            CommandSignatureCreated(static_cast<ID3D12CommandSignature*>(*output),*desc,root);
        uint32_t graphics = 0;
        for (UINT i=0;i<desc->NumArgumentDescs;++i)
            if (desc->pArgumentDescs[i].Type == D3D12_INDIRECT_ARGUMENT_TYPE_DRAW ||
                desc->pArgumentDescs[i].Type == D3D12_INDIRECT_ARGUMENT_TYPE_DRAW_INDEXED) graphics = 1;
        static_cast<ID3D12CommandSignature*>(*output)->SetPrivateData(SignatureId,sizeof(graphics),&graphics);
        try
        {
            Json layout = {{"byte_stride",desc->ByteStride},{"arguments",Json::array()}};
            for (UINT i=0;i<desc->NumArgumentDescs;++i)
            {
                const auto& a = desc->pArgumentDescs[i]; Json row = {{"type",uint32_t(a.Type)}};
                if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT)
                    row.update({{"root_parameter",a.Constant.RootParameterIndex},{"word_offset",a.Constant.DestOffsetIn32BitValues},
                        {"words",a.Constant.Num32BitValuesToSet}});
                else if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT_BUFFER_VIEW) row["root_parameter"] = a.ConstantBufferView.RootParameterIndex;
                else if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_SHADER_RESOURCE_VIEW) row["root_parameter"] = a.ShaderResourceView.RootParameterIndex;
                else if (a.Type == D3D12_INDIRECT_ARGUMENT_TYPE_UNORDERED_ACCESS_VIEW) row["root_parameter"] = a.UnorderedAccessView.RootParameterIndex;
                layout["arguments"].push_back(std::move(row));
            }
            const auto text = layout.dump();
            static_cast<ID3D12CommandSignature*>(*output)->SetPrivateData(SignatureLayoutId,UINT(text.size()),text.data());
        } catch (...) { Fail("Indirect signature metadata failed"); }
    }
    return result;
}
void STDMETHODCALLTYPE BeginRender(ID3D12GraphicsCommandList4* cmd, UINT count,
    const D3D12_RENDER_PASS_RENDER_TARGET_DESC* targets, const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC* depth, D3D12_RENDER_PASS_FLAGS flags)
{
    if (Recording())
    {
        try
        {
            std::vector<D3D12_CPU_DESCRIPTOR_HANDLE> handles;
            for (UINT i=0;targets && i<count;++i) handles.push_back(targets[i].cpuDescriptor);
            RenderTargets(cmd,UINT(handles.size()),handles.data(),FALSE);
            std::scoped_lock lock(gRecordMutex);
            if (Recording())
            {
                auto& list = GetList(cmd); list.inRenderPass = true;
                for (size_t i=0;i<list.targets.size();++i)
                {
                    const auto found = std::find_if(targets,targets+count,[&](const auto& target) {
                        return target.cpuDescriptor.ptr == list.targets[i].descriptorCpu; });
                    if (found == targets+count || found->EndingAccess.Type != D3D12_RENDER_PASS_ENDING_ACCESS_TYPE_PRESERVE)
                    { list.targets[i].snapshotSupported = false; Count("render_pass_nonpreserved_target_snapshot_skipped"); }
                }
            }
        } catch (...) { Fail("Render pass observation failed"); }
    }
    oBeginRender(cmd,count,targets,depth,flags);
}
void STDMETHODCALLTYPE EndRender(ID3D12GraphicsCommandList4* cmd)
{
    oEndRender(cmd);
    if (Recording())
    {
        try { std::scoped_lock lock(gRecordMutex); if (Recording()) GetList(cmd).inRenderPass = false; }
        catch (...) { Fail("Render pass end observation failed"); }
        SnapshotWrites(cmd);
    }
}
void STDMETHODCALLTYPE RayPipeline(ID3D12GraphicsCommandList4* cmd, ID3D12StateObject* object)
{
    if (Recording())
    {
        try
        {
            std::scoped_lock lock(gRecordMutex);
            if (Recording()) GetList(cmd).pso = {{"pointer",uint64_t(reinterpret_cast<uintptr_t>(object))},
                {"kind","raytracing_state_object"},{"hash_known",false},{"shader_hashes",Json::object()}};
        } catch (...) { Fail("Raytracing state object observation failed"); }
    }
    oRayPipeline(cmd,object);
}
void STDMETHODCALLTYPE Rays(ID3D12GraphicsCommandList4* cmd, const D3D12_DISPATCH_RAYS_DESC* desc)
{
    if (desc)
    {
        const std::array<uint64_t,3> args {desc->Width,desc->Height,desc->Depth};
        Pass(cmd,"DispatchRays",args);
    }
    oRays(cmd,desc); SnapshotWrites(cmd);
}
}
bool Install(ID3D12Device* device, ID3D12GraphicsCommandList* list, bool recorder) noexcept
{
    if (gHooksInstalled.load(std::memory_order_acquire)) return true;
    gSurveyBindings.store(recorder,std::memory_order_release);
    if (!device || !list) return false;
    try
    {
        auto** table = *reinterpret_cast<void***>(list);
        auto** dt = *reinterpret_cast<void***>(device);
        oIndirect = reinterpret_cast<IndirectFn>(table[59]);
        oCopyTexture = reinterpret_cast<CopyTextureFn>(table[16]);
        oCopyResource = reinterpret_cast<CopyResourceFn>(table[17]);
        oGraphicsCbv = reinterpret_cast<RootViewFn>(table[38]);
        oGraphicsSrv = reinterpret_cast<RootViewFn>(table[40]);
        oGraphicsUav = reinterpret_cast<RootViewFn>(table[42]);
        oSignature = reinterpret_cast<SignatureFn>(dt[41]);
        ComPtr<ID3D12Device1> device1;
        if (SUCCEEDED(device->QueryInterface(IID_PPV_ARGS(&device1))))
            oCreateLibrary = reinterpret_cast<CreateLibraryFn>((*reinterpret_cast<void***>(device1.Get()))[44]);
        ComPtr<ID3D12GraphicsCommandList4> list4;
        if (SUCCEEDED(list->QueryInterface(IID_PPV_ARGS(&list4))))
        {
            auto** rt = *reinterpret_cast<void***>(list4.Get());
            oBeginRender = reinterpret_cast<BeginRenderFn>(rt[68]);
            oEndRender = reinterpret_cast<EndRenderFn>(rt[69]);
            oRayPipeline = reinterpret_cast<RayPipelineFn>(rt[75]);
            oRays = reinterpret_cast<RaysFn>(rt[76]);
        }
        LONG result = DetourTransactionBegin();
        if (result == NO_ERROR) result = DetourUpdateThread(GetCurrentThread());
        auto attach = [&](auto& original,auto replacement) {
            if (result == NO_ERROR) result = DetourAttach(reinterpret_cast<PVOID*>(&original),reinterpret_cast<PVOID>(replacement)); };
        attach(oIndirect,Indirect); attach(oCopyResource,CopyResource); attach(oCopyTexture,CopyTexture);
        attach(oGraphicsCbv,GraphicsCbv); attach(oGraphicsSrv,GraphicsSrv); attach(oGraphicsUav,GraphicsUav); attach(oSignature,Signature);
        if (oCreateLibrary) attach(oCreateLibrary,CreateLibrary);
        if (list4) { attach(oBeginRender,BeginRender); attach(oEndRender,EndRender); attach(oRayPipeline,RayPipeline); attach(oRays,Rays); }
        if (result == NO_ERROR) result = DetourTransactionCommit(); else DetourTransactionAbort();
        if (result != NO_ERROR)
        {
            oIndirect = nullptr; oCopyResource = nullptr; oCopyTexture = nullptr;
            oGraphicsCbv = oGraphicsSrv = oGraphicsUav = nullptr; oSignature = nullptr; oCreateLibrary = nullptr;
            oBeginRender = nullptr; oEndRender = nullptr; oRayPipeline = nullptr; oRays = nullptr;
            Fail("Survey-only hook installation failed; no capture will be started"); return false;
        }
        gCreationDevice = device;
        gHooksInstalled.store(true,std::memory_order_release);
        gEnabled.store(recorder,std::memory_order_release); gStatus.installed = recorder;
        gStatus.phase = recorder ? "idle" : "off";
        gStatus.message = recorder ? "Frame survey enabled at startup; request one frame." : "Survey recorder is off; creation registry is shared with the NRD bridge.";
        if (recorder) LOG_INFO("[FRAME_SURVEY] debug hooks installed; no denoiser dispatch is replaced");
        return true;
    } catch (...) { Fail("Survey hook installation exception"); return false; }
}
void Shutdown() noexcept
{
    gMetadataHealthy.store(false,std::memory_order_release);
    gTracking.store(false,std::memory_order_release);
    gSurveyBindings.store(false,std::memory_order_release); gBindingWindow.store(false,std::memory_order_release);
    gPipelineObserver.store(nullptr,std::memory_order_release); gGraphicsPipelineObserver.store(nullptr,std::memory_order_release);
    gReleaseObserver.store(nullptr,std::memory_order_release);
    const bool installed = gHooksInstalled.exchange(false,std::memory_order_acq_rel);
    gEnabled.store(false,std::memory_order_release); gRecording.store(false,std::memory_order_release);
    try
    {
        std::unique_ptr<Service> owner;
        { std::scoped_lock lock(gRecordMutex); owner = std::move(gService); }
        if (owner) { owner->trace.Abort("FRAME_SURVEY device/owner shutdown"); owner.reset(); }
        if (installed) { DetourTransactionBegin(); DetourUpdateThread(GetCurrentThread()); }
        auto detach = [](auto& original,auto replacement) {
            if (original) DetourDetach(reinterpret_cast<PVOID*>(&original),reinterpret_cast<PVOID>(replacement)); };
        detach(oIndirect,Indirect); detach(oCopyResource,CopyResource); detach(oCopyTexture,CopyTexture);
        detach(oGraphicsCbv,GraphicsCbv); detach(oGraphicsSrv,GraphicsSrv); detach(oGraphicsUav,GraphicsUav); detach(oSignature,Signature);
        detach(oBeginRender,BeginRender); detach(oEndRender,EndRender); detach(oRayPipeline,RayPipeline); detach(oRays,Rays);
        detach(oCreateLibrary,CreateLibrary);
        {
            std::scoped_lock library(gLibraryHookMutex);
            detach(oLoadGraphics,LoadGraphics); detach(oLoadCompute,LoadCompute); detach(oLoadStream,LoadStream);
        }
        if (installed) DetourTransactionCommit();
        oIndirect = nullptr; oCopyResource = nullptr; oCopyTexture = nullptr;
        oGraphicsCbv = oGraphicsSrv = oGraphicsUav = nullptr; oSignature = nullptr; oCreateLibrary = nullptr;
        oBeginRender = nullptr; oEndRender = nullptr; oRayPipeline = nullptr; oRays = nullptr;
        { std::scoped_lock library(gLibraryHookMutex); oLoadGraphics = nullptr; oLoadCompute = nullptr; oLoadStream = nullptr; }
        {
        NativeSnapshotExclusive metadataSnapshot;
        { std::scoped_lock mirror(gMirrorMutex); gMirror.clear(); gMirrorOwners.clear(); }
        std::scoped_lock lock(gLifetimeMutex); gNativeMetadataEpoch.fetch_add(1,std::memory_order_acq_rel);
        gNativeResources.Clear(); gNativeHeaps.Clear(); gNativeBuffers.Clear();
        for (auto& ranges : gNativeHeapRanges) ranges.Clear();
        gViews.clear(); gResources.clear(); gAddresses.clear(); gBufferAddresses.Clear(); gHeaps.clear(); gCpuHeaps.clear(); gRootLayouts.clear(); gPipelineBirths.clear(); gPipelineMetadata.clear(); gIndirectSignatures.clear();
        }
        gCreationDevice.Reset(); gStatus.installed = false;
        gMetadataHealthy.store(true,std::memory_order_release);
    } catch (...) {}
}
}
