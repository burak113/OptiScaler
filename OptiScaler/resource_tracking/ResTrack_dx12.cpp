#include "pch.h"
#include "misc/NrdBridgePerf_Dx12.h"
#include "shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h"
#include "misc/NrdBridgeDevice_Dx12.h"
#include "shaders/fsrd_preprocess/RRTraceFence.h"
#include "misc/RecordedComputeLease_Dx12.h"
#include "misc/NrdBridgeLifetime_Dx12.h"
#include "misc/NrdBridgeRelease_Dx12.h"
#include "misc/NrdBridgeTitleCallbacks_Dx12.h"
#include "ResTrack_dx12.h"
#include "FrameSurvey_Dx12.h"
#include "hooks/D3D12_Hooks.h"

#include <Config.h>
#include <State.h>
#include <Util.h>

#include <menu/menu_overlay_dx.h>

#include <algorithm>
#include <future>
#include <map>
#include <unordered_set>

#include <magic_enum_utility.hpp>
#include <include/d3dx/d3dx12.h>
#include <detours/detours.h>

namespace NrdBridgeNativeBirth { bool ObserveReleaseCoverage(IUnknown*) noexcept; }

#ifndef STDMETHODCALLTYPE
#include <Unknwn.h> // or <objbase.h> to get STDMETHODCALLTYPE
#endif

#ifdef USE_SPINLOCK_MUTEX
#define LOCK_GUARD(mutex) std::lock_guard<SpinLock> name(mutex)
#else
#define LOCK_GUARD(mutex) std::lock_guard<std::mutex> name(mutex)
#endif

// Device hooks for FG
typedef void(STDMETHODCALLTYPE* PFN_CreateRenderTargetView)(ID3D12Device* This, ID3D12Resource* pResource,
                                                            D3D12_RENDER_TARGET_VIEW_DESC* pDesc,
                                                            D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor);
typedef void(STDMETHODCALLTYPE* PFN_CreateShaderResourceView)(ID3D12Device* This, ID3D12Resource* pResource,
                                                              D3D12_SHADER_RESOURCE_VIEW_DESC* pDesc,
                                                              D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor);
typedef void(STDMETHODCALLTYPE* PFN_CreateUnorderedAccessView)(ID3D12Device* This, ID3D12Resource* pResource,
                                                               ID3D12Resource* pCounterResource,
                                                               D3D12_UNORDERED_ACCESS_VIEW_DESC* pDesc,
                                                               D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor);
typedef HRESULT(STDMETHODCALLTYPE* PFN_CreateGraphicsPipelineState)(
    ID3D12Device* This, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* pDesc, REFIID riid,
    void** ppPipelineState);
typedef HRESULT(STDMETHODCALLTYPE* PFN_CreateComputePipelineState)(
    ID3D12Device* This, const D3D12_COMPUTE_PIPELINE_STATE_DESC* pDesc, REFIID riid,
    void** ppPipelineState);
typedef HRESULT(STDMETHODCALLTYPE* PFN_CreatePipelineState)(
    ID3D12Device2* This, const D3D12_PIPELINE_STATE_STREAM_DESC* pDesc, REFIID riid,
    void** ppPipelineState);
typedef void(STDMETHODCALLTYPE* PFN_CreateDepthStencilView)(ID3D12Device* This, ID3D12Resource* pResource,
                                                            const D3D12_DEPTH_STENCIL_VIEW_DESC* pDesc,
                                                            D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor);
typedef void(STDMETHODCALLTYPE* PFN_CreateConstantBufferView)(ID3D12Device* This,
                                                              const D3D12_CONSTANT_BUFFER_VIEW_DESC* pDesc,
                                                              D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor);

typedef void(STDMETHODCALLTYPE* PFN_CreateSampler)(ID3D12Device* This, const D3D12_SAMPLER_DESC* pDesc,
                                                   D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor);

typedef HRESULT(STDMETHODCALLTYPE* PFN_CreateDescriptorHeap)(ID3D12Device* This,
                                                             D3D12_DESCRIPTOR_HEAP_DESC* pDescriptorHeapDesc,
                                                             REFIID riid, void** ppvHeap);
typedef ULONG(STDMETHODCALLTYPE* PFN_HeapRelease)(ID3D12DescriptorHeap* This);
typedef void(STDMETHODCALLTYPE* PFN_CopyDescriptors)(ID3D12Device* This, UINT NumDestDescriptorRanges,
                                                     D3D12_CPU_DESCRIPTOR_HANDLE* pDestDescriptorRangeStarts,
                                                     UINT* pDestDescriptorRangeSizes, UINT NumSrcDescriptorRanges,
                                                     D3D12_CPU_DESCRIPTOR_HANDLE* pSrcDescriptorRangeStarts,
                                                     UINT* pSrcDescriptorRangeSizes,
                                                     D3D12_DESCRIPTOR_HEAP_TYPE DescriptorHeapsType);
typedef void(STDMETHODCALLTYPE* PFN_CopyDescriptorsSimple)(ID3D12Device* This, UINT NumDescriptors,
                                                           D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptorRangeStart,
                                                           D3D12_CPU_DESCRIPTOR_HANDLE SrcDescriptorRangeStart,
                                                           D3D12_DESCRIPTOR_HEAP_TYPE DescriptorHeapsType);

// Command list hooks for FG
typedef void(STDMETHODCALLTYPE* PFN_OMSetRenderTargets)(ID3D12GraphicsCommandList* This,
                                                        UINT NumRenderTargetDescriptors,
                                                        D3D12_CPU_DESCRIPTOR_HANDLE* pRenderTargetDescriptors,
                                                        BOOL RTsSingleHandleToDescriptorRange,
                                                        D3D12_CPU_DESCRIPTOR_HANDLE* pDepthStencilDescriptor);
typedef void(STDMETHODCALLTYPE* PFN_SetGraphicsRootDescriptorTable)(ID3D12GraphicsCommandList* This,
                                                                    UINT RootParameterIndex,
                                                                    D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor);
typedef void(STDMETHODCALLTYPE* PFN_SetComputeRootDescriptorTable)(ID3D12GraphicsCommandList* This,
                                                                   UINT RootParameterIndex,
                                                                   D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor);
typedef void(STDMETHODCALLTYPE* PFN_DrawIndexedInstanced)(ID3D12GraphicsCommandList* This, UINT IndexCountPerInstance,
                                                          UINT InstanceCount, UINT StartIndexLocation,
                                                          INT BaseVertexLocation, UINT StartInstanceLocation);
typedef void(STDMETHODCALLTYPE* PFN_DrawInstanced)(ID3D12GraphicsCommandList* This, UINT VertexCountPerInstance,
                                                   UINT InstanceCount, UINT StartVertexLocation,
                                                   UINT StartInstanceLocation);
typedef void(STDMETHODCALLTYPE* PFN_Dispatch)(ID3D12GraphicsCommandList* This, UINT ThreadGroupCountX,
                                              UINT ThreadGroupCountY, UINT ThreadGroupCountZ);
typedef void(STDMETHODCALLTYPE* PFN_ExecuteBundle)(ID3D12GraphicsCommandList* This,
                                                   ID3D12GraphicsCommandList* pCommandList);
typedef void(STDMETHODCALLTYPE* PFN_ResourceBarrier)(ID3D12GraphicsCommandList* This, UINT NumBarriers,
                                                     const D3D12_RESOURCE_BARRIER* pBarriers);
typedef void(STDMETHODCALLTYPE* PFN_SetPipelineState)(ID3D12GraphicsCommandList* This,
                                                      ID3D12PipelineState* pPipelineState);
typedef HRESULT(STDMETHODCALLTYPE* PFN_Reset)(ID3D12GraphicsCommandList* This,
                                              ID3D12CommandAllocator* pAllocator,
                                              ID3D12PipelineState* pInitialState);
typedef void(STDMETHODCALLTYPE* PFN_ClearState)(ID3D12GraphicsCommandList* This, ID3D12PipelineState* initial);
typedef void(STDMETHODCALLTYPE* PFN_SetPredication)(ID3D12GraphicsCommandList* This, ID3D12Resource* predicate,
    UINT64 offset, D3D12_PREDICATION_OP operation);
typedef void(STDMETHODCALLTYPE* PFN_SetMarker)(ID3D12GraphicsCommandList* This, UINT Metadata, const void* pData,
                                              UINT Size);
typedef void(STDMETHODCALLTYPE* PFN_BeginEvent)(ID3D12GraphicsCommandList* This, UINT Metadata, const void* pData,
                                               UINT Size);
typedef void(STDMETHODCALLTYPE* PFN_EndEvent)(ID3D12GraphicsCommandList* This);
typedef HRESULT(STDMETHODCALLTYPE* PFN_Close)(ID3D12GraphicsCommandList* This);

typedef void(STDMETHODCALLTYPE* PFN_ExecuteCommandLists)(ID3D12CommandQueue* This, UINT NumCommandLists,
                                                         ID3D12CommandList* const* ppCommandLists);

typedef ULONG(STDMETHODCALLTYPE* PFN_Release)(ID3D12Resource* This);
typedef ULONG(STDMETHODCALLTYPE* PFN_PsoRelease)(ID3D12PipelineState* This);
typedef ULONG(STDMETHODCALLTYPE* PFN_CommandListRelease)(IUnknown* This);
using PFN_BirthRelease = ULONG(STDMETHODCALLTYPE*)(IUnknown*);

// Original method calls for device
static PFN_CreateRenderTargetView o_CreateRenderTargetView = nullptr;
static PFN_CreateShaderResourceView o_CreateShaderResourceView = nullptr;
static PFN_CreateUnorderedAccessView o_CreateUnorderedAccessView = nullptr;
static PFN_CreateGraphicsPipelineState o_CreateGraphicsPipelineState = nullptr;
static PFN_CreateComputePipelineState o_CreateComputePipelineState = nullptr;
static PFN_CreatePipelineState o_CreatePipelineState = nullptr;
static PFN_CreateDepthStencilView o_CreateDepthStencilView = nullptr;
static PFN_CreateConstantBufferView o_CreateConstantBufferView = nullptr;
static PFN_CreateSampler o_CreateSampler = nullptr;

static PFN_CreateDescriptorHeap o_CreateDescriptorHeap = nullptr;
static PFN_HeapRelease o_HeapRelease = nullptr;
static PFN_CopyDescriptors o_CopyDescriptors = nullptr;
static PFN_CopyDescriptorsSimple o_CopyDescriptorsSimple = nullptr;

// Original method calls for command list
static bool gSurveyWrappers = false;
static bool gNrdBridgeWrappers = false;
static PFN_Dispatch o_Dispatch = nullptr;
static PFN_DrawInstanced o_DrawInstanced = nullptr;
static PFN_DrawIndexedInstanced o_DrawIndexedInstanced = nullptr;
static PFN_ExecuteBundle o_ExecuteBundle = nullptr;
static PFN_ResourceBarrier o_ResourceBarrier = nullptr;
static PFN_SetPipelineState o_SetPipelineState = nullptr;
static PFN_Reset o_Reset = nullptr;
static PFN_ClearState o_ClearState = nullptr;
static PFN_SetPredication o_SetPredication = nullptr;
static void STDMETHODCALLTYPE hkBridgeClearState(ID3D12GraphicsCommandList*, ID3D12PipelineState*);
static void STDMETHODCALLTYPE hkBridgeSetPredication(ID3D12GraphicsCommandList*, ID3D12Resource*, UINT64, D3D12_PREDICATION_OP);
static PFN_SetMarker o_SetMarker = nullptr;
static PFN_BeginEvent o_BeginEvent = nullptr;
static PFN_EndEvent o_EndEvent = nullptr;
static PFN_Close o_Close = nullptr;

static PFN_ExecuteCommandLists o_ExecuteCommandLists = nullptr;
static PFN_Release o_Release = nullptr;
// Bound to the private resource observer from class scope when its shared entry
// is installed. Free Release detours use this route without exposing hook APIs.
static ULONG (*gSharedResourceReleaseObserver)(ID3D12Resource*) = nullptr;
static PFN_PsoRelease o_PsoRelease = nullptr;
// Detours rewrites the function body, not the COM vtable slot. Keep the original resource
// Release entry so a PSO that shares the same implementation can reuse hkRelease instead of
// attempting to detour the already-detoured address a second time.
static PVOID gResourceReleaseEntry = nullptr;
static PVOID gHeapReleaseEntry = nullptr;
static bool gHeapOwnsReleaseHook = false;
static std::atomic<bool> gHeapReleaseSharesResource { false };
static bool gResourceReleaseSharesHeap = false;
static std::recursive_mutex gReleaseHookInstallMutex;
static PVOID gPsoReleaseEntry = nullptr;
static PVOID gCommandListReleaseEntry = nullptr;
static PVOID gComputeResetEntry = nullptr;
static PVOID gRRRecordingCloseEntry = nullptr;
static PVOID gRRRecordingBarrierEntry = nullptr;
static PVOID gComputeExecuteEntry = nullptr;
static Microsoft::WRL::ComPtr<IUnknown> gComputeQueueDeviceIdentity;
static PFN_CommandListRelease o_CommandListRelease = nullptr;
static bool gResourceReleaseSharesCommandList = false;
static bool gResourceReleaseSharesPso = false;
static bool gResourceReleaseSharesBirth = false;
static std::atomic<bool> gComputeListHooksAvailable { false };
static std::atomic<bool> gComputeQueueHookAvailable { false };
static std::mutex gComputeHookInitMutex;

static ULONG hkPsoRelease(ID3D12PipelineState* This);
static ULONG STDMETHODCALLTYPE hkCommandListRelease(IUnknown* This);
// Once an inspector weak pointer is published its Release protection stays on.
// The never-enabled OFF path still enters no physical gate.
static std::atomic<bool> gRRInspectorLifetimeProtection {false};
static bool NeedsNativeReleaseGate() noexcept
{
    return !FrameSurvey::OwnedRelease() && (gNrdBridgeWrappers ||
        gRRInspectorLifetimeProtection.load(std::memory_order_acquire));
}
static PFN_BirthRelease FindBirthReleaseOriginal(PVOID entry) noexcept;
static bool RRPhysicalReleaseCovered(IUnknown* object) noexcept
{
    const PVOID entry = (*reinterpret_cast<PVOID**>(object))[2];
    // The legacy resource observer removes the weak resource row before native
    // destruction. Other physical entries need the native birth dispatcher.
    return entry == gResourceReleaseEntry && o_Release;
}
static bool UseNrdNativeRetirement() noexcept
{
    return gNrdBridgeWrappers && !FrameSurvey::OwnedRelease() &&
        NrdBridgeNativeBirth::Ready();
}
// A distinct root/list/PSO/heap implementation is observed without assuming
// another object's IUnknown vtable. The small installation table is bounded;
// ordinary resource/heap/PSO/list Release hooks have no table lookup.
struct BirthReleaseEntry { std::atomic<PVOID> entry {nullptr}; PFN_BirthRelease original = nullptr; };
static constexpr size_t MaxBirthReleaseEntries = 16;
static std::array<BirthReleaseEntry,MaxBirthReleaseEntries> gBirthReleaseEntries;
static size_t gBirthReleaseEntriesUsed = 0; // Installation mutex only.
static PFN_BirthRelease FindBirthReleaseOriginal(PVOID entry) noexcept
{
    for (size_t i = 0; i != MaxBirthReleaseEntries; ++i)
        if (gBirthReleaseEntries[i].entry.load(std::memory_order_acquire) == entry) return gBirthReleaseEntries[i].original;
    return nullptr;
}
template <size_t Index> static ULONG STDMETHODCALLTYPE hkBirthRelease(IUnknown* object)
{
    const auto original = gBirthReleaseEntries[Index].original;
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::Release,UseNrdNativeRetirement());
    if (State::Instance().isShuttingDown) return original(object);
    if (!UseNrdNativeRetirement())
    {
        NrdBridgeLifetime::ScopedRelease titleRelease(NeedsNativeReleaseGate());
        auto recording = RecordedComputeLease::BeginRelease(object);
        const ULONG result = original(object);
        RecordedComputeLease::EndRelease(recording,result == 0);
        return result;
    }
    return NrdBridgeRelease::Title(object,original);
}
template <size_t... Index> static constexpr auto BirthReleaseHooks(std::index_sequence<Index...>)
{ return std::array<PFN_BirthRelease,sizeof...(Index)>{&hkBirthRelease<Index>...}; }
static constexpr auto gBirthReleaseHooks = BirthReleaseHooks(std::make_index_sequence<MaxBirthReleaseEntries>{});

static void PublishComputeHookAvailability()
{
    RecordedComputeLease::SetHooksAvailable(gComputeListHooksAvailable.load(),
                                            gComputeQueueHookAvailable.load());
}

// A required owned-RR packet may fail before Track retained a participant.
// Do not let the empty/unknown-list selector or runtime/FG OFF hide that denial.
static bool RequiredComputeSubmissionAllowed(RecordedComputeLease::SubmissionDecision* decision = nullptr) noexcept
{
    const HRESULT failure = RecordedComputeLease::RequiredSubmissionFailure();
    if (SUCCEEDED(failure)) return true;
    RecordedComputeLease::DenySubmission(failure);
    if (decision)
    {
        if (decision->allowed) decision->orderingFailure = failure;
        decision->allowed = false;
    }
    return false;
}

std::shared_ptr<RecordedComputeLease::Submission> ResTrack_Dx12::BeforeComputeSubmission(
    ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists,
    RecordedComputeLease::SubmissionDecision* decision) noexcept
{
    if (!RequiredComputeSubmissionAllowed(decision)) return {};
    // No identity vector or logging/string allocation may hide necessary queue
    // waits after an intent-snapshot OOM. Use the same native-object IID without
    // a string/log allocation or a dependency on lazy IID initialization.
    const RecordedComputeLease::IdentityRange range {lists, lists ? count : 0,
        [](const void* context, size_t index, IUnknown** out) -> HRESULT {
            *out = nullptr;
            auto* object = static_cast<ID3D12CommandList* const*>(context)[index];
            if (!object) return S_OK;
            constexpr IID nativeObject {0xadec44e2, 0x61f0, 0x45c3, {0xad, 0x9f, 0x1b, 0x37, 0x37, 0x92, 0x84, 0xff}};
            Microsoft::WRL::ComPtr<IUnknown> unwrapped;
            IUnknown* actual = object;
            if (SUCCEEDED(object->QueryInterface(nativeObject, reinterpret_cast<void**>(unwrapped.GetAddressOf()))) && unwrapped)
                actual = unwrapped.Get();
            return actual->QueryInterface(IID_PPV_ARGS(out));
        },
        [](const void* context, size_t index) -> void* { return static_cast<ID3D12CommandList* const*>(context)[index]; }};
    return RecordedComputeLease::BeforeSubmission(queue, range, decision);
}

static PFN_OMSetRenderTargets o_OMSetRenderTargets = nullptr;
static PFN_SetGraphicsRootDescriptorTable o_SetGraphicsRootDescriptorTable = nullptr;
static PFN_SetComputeRootDescriptorTable o_SetComputeRootDescriptorTable = nullptr;

static std::mutex _hudlessTrackMutex;
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*,
                                    ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo>>
    fgPossibleHudless[BUFFER_COUNT];

// heaps section

static std::shared_mutex _heapRegistryMutex;
static std::vector<std::shared_ptr<HeapInfo>> fgHeaps;
static std::unordered_map<void*, size_t> gHeapSlotsByAddress;
static std::map<SIZE_T, size_t> gHeapCpuRanges;
static std::map<SIZE_T, size_t> gHeapGpuRanges;
static std::vector<size_t> gFreeHeapSlots;

static std::set<void*> _notFoundCmdLists;
static std::unordered_map<FG_ResourceType, void*> _resCmdList[BUFFER_COUNT];

struct HeapCacheTLS
{
    unsigned genSeen = 0;
    std::shared_ptr<HeapInfo> heap;
    uint64_t heapVersion = 0;
};

static thread_local HeapCacheTLS cache;
static thread_local HeapCacheTLS cacheRTV;
static thread_local HeapCacheTLS cacheCBV;
static thread_local HeapCacheTLS cacheSRV;
static thread_local HeapCacheTLS cacheUAV;
static std::atomic<unsigned> gHeapGeneration { 1 };

static thread_local HeapCacheTLS cacheGR;
static thread_local HeapCacheTLS cacheCR;

// Heap registry indexes are changed only under _heapRegistryMutex. Live native
// descriptor ranges do not overlap; ambiguous ranges are rejected explicitly.
static bool HeapRangeAvailableLocked(const std::map<SIZE_T, size_t>& ranges,
                                     SIZE_T start, SIZE_T end, bool gpu)
{
    if (!start || end <= start) return false;
    const auto next = ranges.lower_bound(start);
    if (next != ranges.end() && next->first < end) return false;
    if (next != ranges.begin())
    {
        const auto& previous = fgHeaps[std::prev(next)->second];
        if (previous && (gpu ? previous->gpuEnd : previous->cpuEnd) > start) return false;
    }
    return true;
}

static std::shared_ptr<HeapInfo> FindIndexedHeapRangeLocked(const std::map<SIZE_T, size_t>& ranges,
                                                           SIZE_T handle, bool gpu)
{
    auto next = ranges.upper_bound(handle);
    if (next == ranges.begin()) return nullptr;
    const auto& heap = fgHeaps[std::prev(next)->second];
    if (!heap || !heap->active.load(std::memory_order_acquire) ||
        handle >= (gpu ? heap->gpuEnd : heap->cpuEnd)) return nullptr;
    return heap;
}

static bool RegisterTrackedHeapLocked(const std::shared_ptr<HeapInfo>& heap)
{
    if (gHeapSlotsByAddress.contains(heap->heap) ||
        !HeapRangeAvailableLocked(gHeapCpuRanges,heap->cpuStart,heap->cpuEnd,false) ||
        (heap->gpuStart && !HeapRangeAvailableLocked(gHeapGpuRanges,heap->gpuStart,heap->gpuEnd,true)))
    {
        LOG_ERROR("Tracked descriptor heap address/range overlaps a live heap; rejecting ambiguous heap");
        if (gNrdBridgeWrappers) FrameSurvey::MetadataHookFailed("Tracked descriptor heap ranges are ambiguous");
        return false;
    }
    const size_t slot = gFreeHeapSlots.empty() ? fgHeaps.size() : gFreeHeapSlots.back();
    bool addressAdded = false, cpuAdded = false, gpuAdded = false;
    try
    {
        if (slot == fgHeaps.size() && fgHeaps.capacity() == fgHeaps.size())
            fgHeaps.reserve(fgHeaps.size()+65536);
        // Final release can recycle its slot without an allocation.
        if (gFreeHeapSlots.capacity() < fgHeaps.capacity()) gFreeHeapSlots.reserve(fgHeaps.capacity());
        addressAdded = gHeapSlotsByAddress.emplace(heap->heap,slot).second;
        cpuAdded = gHeapCpuRanges.emplace(heap->cpuStart,slot).second;
        if (heap->gpuStart) gpuAdded = gHeapGpuRanges.emplace(heap->gpuStart,slot).second;
        if (slot == fgHeaps.size()) fgHeaps.push_back(heap);
        else { fgHeaps[slot] = heap; gFreeHeapSlots.pop_back(); }
        gHeapGeneration.fetch_add(1,std::memory_order_release);
        return true;
    }
    catch (...)
    {
        if (addressAdded) gHeapSlotsByAddress.erase(heap->heap);
        if (cpuAdded) gHeapCpuRanges.erase(heap->cpuStart);
        if (gpuAdded) gHeapGpuRanges.erase(heap->gpuStart);
        if (gNrdBridgeWrappers) FrameSurvey::MetadataHookFailed("Tracked descriptor heap index allocation failed");
        return false;
    }
}

static std::shared_ptr<HeapInfo> FindTrackedHeapByAddress(void* address)
{
    std::shared_lock lock(_heapRegistryMutex);
    const auto found = gHeapSlotsByAddress.find(address);
    if (found == gHeapSlotsByAddress.end()) return nullptr;
    const auto& heap = fgHeaps[found->second];
    return heap && heap->active.load(std::memory_order_acquire) ? heap : nullptr;
}

static bool DeactivateTrackedHeap(const std::shared_ptr<HeapInfo>& heap)
{
    std::unique_lock lock(_heapRegistryMutex);
    const auto found = gHeapSlotsByAddress.find(heap->heap);
    if (found == gHeapSlotsByAddress.end() || fgHeaps[found->second] != heap || !heap->DeactivateAndClear()) return false;
    const auto slot = found->second;
    gHeapSlotsByAddress.erase(found);
    gHeapCpuRanges.erase(heap->cpuStart);
    if (heap->gpuStart) gHeapGpuRanges.erase(heap->gpuStart);
    gFreeHeapSlots.push_back(slot);
    gHeapGeneration.fetch_add(1,std::memory_order_release);
    return true;
}

static std::atomic<bool> gRRResourceInspectorEnabled { false };
static std::atomic<int> gRRResourceCandidateIndex { 0 };
static std::atomic<uintptr_t> gRRResourceCandidateAddress { 0 };
static std::atomic<uint64_t> gRRSelectedResourceVersion {0};
static std::atomic<uint64_t> gRRSelectionEpoch {1};
static std::atomic<const char*> gRRInspectorReason {"GPU state unavailable: preview has not been verified in the consumer recording."};
static std::atomic<uint32_t> gRRResourceChannel { 0 };
static std::atomic<float> gRRResourceViewScale { 1.0f };
static std::atomic<uint64_t> gRRResourceInspectorFrame { 0 };
static std::mutex gRRResourceCandidateMutex;
static std::vector<RRResourceCandidate> gRRResourceCandidates;
static NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> gRRResourceStateMutex;
static std::unordered_map<ID3D12Resource*, D3D12_RESOURCE_STATES> gRRResourceStates;
// Only selected-resource observations create rows. Native aliases share a key
// solely when their reserved GUID proves the same physical command list.
struct RRRecordingKey
{
    uintptr_t legacyAddress = 0; uint64_t instanceStamp = 0;
    bool operator==(const RRRecordingKey& other) const noexcept
    { return legacyAddress == other.legacyAddress && instanceStamp == other.instanceStamp; }
};
struct RRRecordingKeyHash
{
    size_t operator()(const RRRecordingKey& key) const noexcept
    { return std::hash<uintptr_t>{}(key.legacyAddress) ^ (std::hash<uint64_t>{}(key.instanceStamp) << 1); }
};
struct RRPreparedRecording
{
    RRRecordingKey key {}; NrdBridgeBirth::Token birth; bool born = false; bool valid = false;
};
struct RRSelectedIdentity
{
    ID3D12Resource* resource = nullptr; NrdBridgeBirth::Token birth;
    uint64_t version = 0; uint64_t selectionEpoch = 0;
};
struct RRRecordingProof
{
    uint64_t recordingSerial = 0;
    RRSelectedIdentity selected {}; uint64_t stateEpoch = 0;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
};
static std::unordered_map<RRRecordingKey,RRRecordingProof,RRRecordingKeyHash> gRRRecordingProofs;
// These counters are protected by gRRResourceStateMutex. Reset/Close erase one
// recording; every selected state observation invalidates foreign stale proofs.
static uint64_t gRRNextRecordingSerial = 1;
static uint64_t gRRSelectedStateEpoch = 1;
static void ForgetRRRecording(void* object,const NrdBridgeBirth::Token& birth = NrdBridgeBirth::Token())
{
    std::scoped_lock lock(gRRResourceStateMutex);
    gRRRecordingProofs.erase({reinterpret_cast<uintptr_t>(object),0});
    if (birth) gRRRecordingProofs.erase({0,birth->InstanceStamp()});
}
struct RRResourceActivity
{
    uint64_t lastWriteFrame = 0;
    uint64_t previousWriteFrame = 0;
    uint64_t writtenFrameCount = 0;
    uint64_t writeTransitionCount = 0;
    uint64_t passWriteCount = 0;
    std::string lastWritePass;
    bool emissivePassMatch = false;
    bool writeObserved = false;
};
static std::unordered_map<ID3D12Resource*, RRResourceActivity> gRRResourceActivity;
struct RRTrackedResourceViews
{
    uint32_t srvViews = 0;
    uint32_t uavViews = 0;
    uint32_t rtvViews = 0;
    D3D12_RESOURCE_DESC desc {};
    std::array<char,256> debugName {};
    uint64_t version = 0;
    NrdBridgeBirth::Token birth;
};
struct RRResourceSize
{
    uint64_t width; uint32_t height;
    bool operator==(const RRResourceSize& other) const noexcept { return width == other.width && height == other.height; }
};
struct RRResourceSizeHash
{
    size_t operator()(const RRResourceSize& size) const noexcept
    { return std::hash<uint64_t>{}(size.width) ^ (std::hash<uint32_t>{}(size.height) << 1); }
};
static NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> gRRTrackedResourceMutex;
static std::unordered_map<ID3D12Resource*, RRTrackedResourceViews> gRRTrackedResources;
static std::atomic<uint64_t> gRRNextResourceVersion {1};
static std::unordered_map<RRResourceSize,std::unordered_set<ID3D12Resource*>,RRResourceSizeHash> gRRResourceSizeIndex;
// Caller holds the inspector registry lock. Touch one size bucket and address.
static void EraseRRTrackedResourceLocked(ID3D12Resource* resource)
{
    const auto found = gRRTrackedResources.find(resource);
    if (found == gRRTrackedResources.end()) return;
    const RRResourceSize size{found->second.desc.Width,found->second.desc.Height};
    if (const auto bucket = gRRResourceSizeIndex.find(size); bucket != gRRResourceSizeIndex.end())
    { bucket->second.erase(resource); if (bucket->second.empty()) gRRResourceSizeIndex.erase(bucket); }
    gRRTrackedResources.erase(found);
}
struct RRCommandListMarkerState
{
    std::vector<std::string> stack;
    std::string lastMarker;
};
struct RRMarkerInventoryItem
{
    uint64_t count = 0;
    uint64_t lastFrame = 0;
};
static std::mutex gRRMarkerMutex;
static std::unordered_map<ID3D12GraphicsCommandList*, RRCommandListMarkerState> gRRCommandListMarkers;
static std::unordered_map<std::string, RRMarkerInventoryItem> gRRMarkerInventory;

enum class RRPsoKind : uint8_t
{
    Unknown = 0,
    Graphics = 1,
    Compute = 2,
    Stream = 3,
};

struct RRPsoMetadata
{
    uint64_t id = 0;
    uint64_t hash = 0;
    RRPsoKind kind = RRPsoKind::Unknown;
    NrdBridgeBirth::Token birth;
};

struct RRPsoProducerStats
{
    RRPsoMetadata metadata {};
    uint64_t hits = 0;
    uint64_t lastFrame = 0;
    bool ambiguous = false;
};

struct RRCommandListPsoState
{
    ID3D12PipelineState* currentPso = nullptr;
    std::vector<ID3D12Resource*> renderTargets;
    ID3D12PipelineState* lastGraphicsPso = nullptr;
    uint64_t renderTargetGeneration = 0;
    uint64_t lastGraphicsGeneration = std::numeric_limits<uint64_t>::max();
    uint64_t lastGraphicsFrame = std::numeric_limits<uint64_t>::max();
    ID3D12PipelineState* lastComputePso = nullptr;
    uint32_t dispatchesSinceBarrier = 0;
    NrdBridgeBirth::Token receiverBirth;
};

static std::atomic<uint64_t> gRRNextPsoId { 1 };
static NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> gRRPsoMutex;
static std::unordered_map<ID3D12PipelineState*, RRPsoMetadata> gRRPsoMetadata;
static std::unordered_map<ID3D12GraphicsCommandList*, RRCommandListPsoState> gRRCommandListPsoStates;
static std::unordered_map<ID3D12Resource*,
                          std::unordered_map<ID3D12PipelineState*, RRPsoProducerStats>>
    gRRResourcePsoProducers;
static std::unordered_map<ID3D12PipelineState*, std::unordered_set<ID3D12Resource*>> gRRPsoProducerResources;
static std::unordered_map<ID3D12PipelineState*, std::unordered_set<ID3D12GraphicsCommandList*>> gRRPsoCommandLists;

static std::array<ID3D12PipelineState*, 3> RRPsoPointers(const RRCommandListPsoState& state)
{
    return {state.currentPso,state.lastGraphicsPso,state.lastComputePso};
}

// Caller holds gRRPsoMutex. These sets contain only actual participants.
static void RemoveRRPsoListMembershipLocked(ID3D12PipelineState* pso, ID3D12GraphicsCommandList* list)
{
    if (!pso) return;
    const auto found = gRRPsoCommandLists.find(pso);
    if (found == gRRPsoCommandLists.end()) return;
    found->second.erase(list);
    if (found->second.empty()) gRRPsoCommandLists.erase(found);
}

static void UpdateRRPsoListReferencesLocked(ID3D12GraphicsCommandList* list,
                                           const std::array<ID3D12PipelineState*,3>& previous,
                                           RRCommandListPsoState& state) noexcept
{
    const auto current = RRPsoPointers(state);
    try
    {
        for (size_t index = 0; index < current.size(); ++index)
            if (current[index] && std::find(current.begin(),current.begin()+index,current[index]) == current.begin()+index &&
                std::find(previous.begin(),previous.end(),current[index]) == previous.end())
                gRRPsoCommandLists[current[index]].insert(list);
    }
    catch (...)
    {
        // A failed optional inspector index must not leave an unindexed raw PSO.
        for (auto* pso : previous) RemoveRRPsoListMembershipLocked(pso,list);
        for (auto* pso : current) RemoveRRPsoListMembershipLocked(pso,list);
        state.currentPso = state.lastGraphicsPso = state.lastComputePso = nullptr;
        if (gNrdBridgeWrappers) FrameSurvey::MetadataHookFailed("RR PSO participant index allocation failed");
        return;
    }
    for (auto* pso : previous)
        if (std::find(current.begin(),current.end(),pso) == current.end()) RemoveRRPsoListMembershipLocked(pso,list);
}

static void EraseRRCommandListPsoStateLocked(ID3D12GraphicsCommandList* list)
{
    const auto found = gRRCommandListPsoStates.find(list);
    if (found == gRRCommandListPsoStates.end()) return;
    for (auto* pso : RRPsoPointers(found->second)) RemoveRRPsoListMembershipLocked(pso,list);
    gRRCommandListPsoStates.erase(found);
}

static void CleanupRRResourcePsoProducersLocked(ID3D12Resource* resource)
{
    const auto found = gRRResourcePsoProducers.find(resource);
    if (found == gRRResourcePsoProducers.end()) return;
    for (const auto& [pso,stats] : found->second)
    {
        const auto reverse = gRRPsoProducerResources.find(pso);
        if (reverse == gRRPsoProducerResources.end()) continue;
        reverse->second.erase(resource);
        if (reverse->second.empty()) gRRPsoProducerResources.erase(reverse);
    }
    gRRResourcePsoProducers.erase(found);
}

static uint64_t HashRRBytes(const void* data, size_t size, uint64_t hash = 1469598103934665603ull)
{
    if (data == nullptr || size == 0)
        return hash;

    const auto* bytes = static_cast<const uint8_t*>(data);
    for (size_t index = 0; index < size; ++index)
    {
        hash ^= bytes[index];
        hash *= 1099511628211ull;
    }
    return hash;
}

static uint64_t HashRRShader(const D3D12_SHADER_BYTECODE& shader, uint64_t hash)
{
    return HashRRBytes(shader.pShaderBytecode, shader.BytecodeLength, hash);
}

static uint64_t HashRRGraphicsPipeline(const D3D12_GRAPHICS_PIPELINE_STATE_DESC& desc)
{
    uint64_t hash = HashRRShader(desc.VS, 1469598103934665603ull);
    hash = HashRRShader(desc.PS, hash);
    hash = HashRRShader(desc.DS, hash);
    hash = HashRRShader(desc.HS, hash);
    hash = HashRRShader(desc.GS, hash);
    hash = HashRRBytes(&desc.NumRenderTargets, sizeof(desc.NumRenderTargets), hash);
    hash = HashRRBytes(desc.RTVFormats, sizeof(desc.RTVFormats), hash);
    hash = HashRRBytes(&desc.DSVFormat, sizeof(desc.DSVFormat), hash);
    hash = HashRRBytes(&desc.PrimitiveTopologyType, sizeof(desc.PrimitiveTopologyType), hash);
    hash = HashRRBytes(&desc.SampleDesc, sizeof(desc.SampleDesc), hash);
    return hash;
}

static uint64_t HashRRComputePipeline(const D3D12_COMPUTE_PIPELINE_STATE_DESC& desc)
{
    return HashRRShader(desc.CS, 1469598103934665603ull);
}

// Caller has proved the object is on its final external reference. Erasing by address is safe
// for both the dedicated PSO hook and the shared-IUnknown path through hkRelease; a resource
// address that has no PSO metadata exits immediately.
static void CleanupRRPsoReferences(void* object)
{
    ForgetRRRecording(object); // Direct legacy list retirement, outside the PSO lock.
    auto* pipelineState = static_cast<ID3D12PipelineState*>(object);
    std::scoped_lock psoLock(gRRPsoMutex);
    EraseRRCommandListPsoStateLocked(static_cast<ID3D12GraphicsCommandList*>(object));
    if (gRRPsoMetadata.erase(pipelineState) == 0 &&
        !gRRPsoProducerResources.contains(pipelineState) && !gRRPsoCommandLists.contains(pipelineState))
        return;

    if (const auto found = gRRPsoProducerResources.find(pipelineState); found != gRRPsoProducerResources.end())
    {
        for (auto* resource : found->second)
            if (const auto producer = gRRResourcePsoProducers.find(resource); producer != gRRResourcePsoProducers.end())
                producer->second.erase(pipelineState);
        gRRPsoProducerResources.erase(found);
    }

    // Recorded bindings would re-register the dying pointer through later draws/dispatches on
    // these command lists, resurrecting metadata for an address the driver may recycle.
    const auto lists = gRRPsoCommandLists.find(pipelineState);
    if (lists == gRRPsoCommandLists.end()) return;
    for (auto* commandList : lists->second)
    {
        const auto found = gRRCommandListPsoStates.find(commandList);
        if (found == gRRCommandListPsoStates.end()) continue;
        auto& state = found->second;
        if (state.currentPso == pipelineState)
            state.currentPso = nullptr;
        if (state.lastGraphicsPso == pipelineState)
            state.lastGraphicsPso = nullptr;
        if (state.lastComputePso == pipelineState)
            state.lastComputePso = nullptr;
    }
    gRRPsoCommandLists.erase(lists);
}

static void ForgetOwnedRRList(ID3D12GraphicsCommandList* list)
{
    ForgetRRRecording(list);
    { std::scoped_lock lock(gRRPsoMutex); EraseRRCommandListPsoStateLocked(list); }
    { std::scoped_lock lock(gRRMarkerMutex); gRRCommandListMarkers.erase(list); }
}

// Cold native installation uses a caller-owned PSO before any metadata guard.
static bool EnsurePsoReleaseHook(ID3D12PipelineState* pipelineState)
{
    if (!pipelineState || NrdBridgeBirth::InMetadataScope()) return false;
    std::unique_lock installation(gReleaseHookInstallMutex);
    const PVOID releaseEntry = (*reinterpret_cast<PVOID**>(pipelineState))[2];
    if ((releaseEntry == gResourceReleaseEntry && o_Release) ||
        (releaseEntry == gCommandListReleaseEntry && o_CommandListRelease) ||
        (releaseEntry == gPsoReleaseEntry && o_PsoRelease)) return true;
    if ((releaseEntry == gHeapReleaseEntry && o_HeapRelease) || FindBirthReleaseOriginal(releaseEntry)) return false;
    if (o_PsoRelease) return false; // A distinct implementation needs native birth coverage.
    gPsoReleaseEntry = releaseEntry; o_PsoRelease = reinterpret_cast<PFN_PsoRelease>(releaseEntry);
    const auto begin = DetourTransactionBegin();
    const auto update = begin == NO_ERROR ? DetourUpdateThread(GetCurrentThread()) : begin;
    const auto attach = update == NO_ERROR ? DetourAttach(reinterpret_cast<PVOID*>(&o_PsoRelease),
        reinterpret_cast<PVOID>(hkPsoRelease)) : update;
    const auto commit = attach == NO_ERROR ? DetourTransactionCommit() :
        (begin == NO_ERROR ? DetourTransactionAbort() : begin);
    if (attach == NO_ERROR && commit == NO_ERROR) return true;
    o_PsoRelease = nullptr; gPsoReleaseEntry = nullptr;
    installation.unlock();
    LOG_ERROR("Failed to hook PSO Release: {:X}", attach == NO_ERROR ? commit : attach);
    if (gNrdBridgeWrappers) FrameSurvey::MetadataHookFailed("RR PSO Release observer installation failed");
    return false;
}
static bool RRInspectorBirthsEnabled() noexcept
{ return gNrdBridgeWrappers && NrdBridgeNativeBirth::Ready(); }
template <class T> static NrdBridgeBirth::Token RRStrongReceiver(T* object)
{
    if (!RRInspectorBirthsEnabled() || !object || FrameSurvey::OwnedRelease()) return {};
    return NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(object,
        [](auto* strong) noexcept { return NrdBridgeNativeBirth::ObserveReleaseCoverage(strong); });
}

// This API caller owns its list. Validate native recording-hook implementations
// before any metadata lock; unknown forwarding surfaces cannot lend state proof.
static RRPreparedRecording PrepareRRRecording(ID3D12GraphicsCommandList* list) noexcept
{
    RRPreparedRecording receiver {};
    if (!list || FrameSurvey::OwnedRelease() || NrdBridgeBirth::InMetadataScope() ||
        !gComputeListHooksAvailable.load(std::memory_order_acquire)) return receiver;
    auto** table = *reinterpret_cast<PVOID**>(list);
    if (!o_Reset || !o_Close || !o_ResourceBarrier || table[10] != gComputeResetEntry ||
        table[9] != gRRRecordingCloseEntry || table[26] != gRRRecordingBarrierEntry) return receiver;
    receiver.born = RRInspectorBirthsEnabled();
    if (receiver.born)
    {
        // ScopedRecording deliberately permits this title-list cold bootstrap.
        // Owned injection callers are excluded above; cached coverage is native-free.
        receiver.birth = NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(list,
            [](auto* strong) noexcept { return NrdBridgeNativeBirth::ObserveReleaseCoverage(strong); });
        if (!receiver.birth || !NrdBridgeBirth::Healthy()) return receiver;
        receiver.key.instanceStamp = receiver.birth->InstanceStamp();
    }
    else
    {
        const auto entry = table[2];
        if (!((entry == gResourceReleaseEntry && o_Release) ||
              (entry == gCommandListReleaseEntry && o_CommandListRelease) ||
              (entry == gPsoReleaseEntry && o_PsoRelease))) return receiver;
        receiver.key.legacyAddress = reinterpret_cast<uintptr_t>(list);
    }
    receiver.valid = true;
    return receiver;
}
static RRSelectedIdentity CaptureRRSelectedIdentity()
{
    RRSelectedIdentity selected {};
    std::scoped_lock lock(gRRResourceCandidateMutex);
    const auto index = gRRResourceCandidateIndex.load(std::memory_order_relaxed);
    if (index < 0 || size_t(index) >= gRRResourceCandidates.size()) return selected;
    const auto& candidate = gRRResourceCandidates[size_t(index)];
    if (reinterpret_cast<uintptr_t>(candidate.resourceAddress) != gRRResourceCandidateAddress.load(std::memory_order_acquire) ||
        !candidate.previewSupported) return selected;
    selected.resource = static_cast<ID3D12Resource*>(candidate.resourceAddress);
    selected.birth = candidate.resourceBirth; selected.version = candidate.registryVersion;
    selected.selectionEpoch = gRRSelectionEpoch.load(std::memory_order_acquire);
    return selected;
}
// Called only while gRRResourceCandidateMutex is held. An empty inventory or
// recycled selected address changes the epoch without scanning recording rows.
static void SelectRRResourceLocked(const RRResourceCandidate* candidate)
{
    const auto address = candidate ? reinterpret_cast<uintptr_t>(candidate->resourceAddress) : 0;
    const auto version = candidate ? candidate->registryVersion : 0;
    const auto oldAddress = gRRResourceCandidateAddress.exchange(address,std::memory_order_acq_rel);
    const auto oldVersion = gRRSelectedResourceVersion.exchange(version,std::memory_order_acq_rel);
    if (oldAddress != address || oldVersion != version) gRRSelectionEpoch.fetch_add(1,std::memory_order_acq_rel);
}
static bool RRBarrierTouchesSelected(const D3D12_RESOURCE_BARRIER& barrier,ID3D12Resource* selected) noexcept
{
    if (!selected) return false;
    if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION) return barrier.Transition.pResource == selected;
    if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_UAV) return !barrier.UAV.pResource || barrier.UAV.pResource == selected;
    if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING)
        return !barrier.Aliasing.pResourceBefore || !barrier.Aliasing.pResourceAfter ||
            barrier.Aliasing.pResourceBefore == selected || barrier.Aliasing.pResourceAfter == selected;
    return false;
}
// State lock held; whole resources only, no native methods, no foreign-list walk.
static void ObserveRRSelectedStateLocked(const RRPreparedRecording& receiver,const RRSelectedIdentity& selected,
                                         const D3D12_RESOURCE_BARRIER& barrier,bool wholeResource)
{
    if (!RRBarrierTouchesSelected(barrier,selected.resource) ||
        selected.selectionEpoch != gRRSelectionEpoch.load(std::memory_order_acquire)) return;
    ++gRRSelectedStateEpoch;
    if (!receiver.valid || (receiver.born && !receiver.birth->CacheAdmissible())) return;
    auto& proof = gRRRecordingProofs[receiver.key];
    if (!proof.recordingSerial) proof.recordingSerial = gRRNextRecordingSerial++;
    proof.selected = selected; proof.stateEpoch = gRRSelectedStateEpoch;
    proof.state = barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION && wholeResource &&
        barrier.Flags == D3D12_RESOURCE_BARRIER_FLAG_NONE ? barrier.Transition.StateAfter : D3D12_RESOURCE_STATE_COMMON;
}
static void RRRecordingSucceeded(const RRPreparedRecording& receiver,void* list)
{
    std::scoped_lock lock(gRRResourceStateMutex);
    gRRRecordingProofs.erase({reinterpret_cast<uintptr_t>(list),0});
    if (receiver.valid) gRRRecordingProofs.erase(receiver.key);
    else ++gRRSelectedStateEpoch; // Unknown identity must not leave a prior recording admissible.
}
// Unknown IID outputs own one temporary typed reference, released after guards.
struct ReturnedPipelineInterface
{
    ID3D12PipelineState* pipeline = nullptr;
    bool temporary = false;
    ReturnedPipelineInterface(void* output, REFIID iid)
    {
        if (!output) return;
        if (iid == __uuidof(ID3D12PipelineState)) pipeline = static_cast<ID3D12PipelineState*>(output);
        else temporary = SUCCEEDED(static_cast<IUnknown*>(output)->QueryInterface(IID_PPV_ARGS(&pipeline)));
    }
    ~ReturnedPipelineInterface() { if (temporary && pipeline) pipeline->Release(); }
    ReturnedPipelineInterface(const ReturnedPipelineInterface&) = delete;
    ReturnedPipelineInterface& operator=(const ReturnedPipelineInterface&) = delete;
};
struct ReturnedHeapInterface
{
    ID3D12DescriptorHeap* heap = nullptr; bool temporary = false;
    ReturnedHeapInterface(void* output, REFIID iid)
    {
        if (!output) return;
        if (iid == __uuidof(ID3D12DescriptorHeap)) heap = static_cast<ID3D12DescriptorHeap*>(output);
        else temporary = SUCCEEDED(static_cast<IUnknown*>(output)->QueryInterface(IID_PPV_ARGS(&heap)));
    }
    ~ReturnedHeapInterface() { if (temporary && heap) heap->Release(); }
    ReturnedHeapInterface(const ReturnedHeapInterface&) = delete;
    ReturnedHeapInterface& operator=(const ReturnedHeapInterface&) = delete;
};
static RRPsoMetadata& EnsureRRPsoMetadata(ID3D12PipelineState* pipelineState,
                                         RRPsoKind kind = RRPsoKind::Unknown,
                                         uint64_t hash = 0,
                                         const NrdBridgeBirth::Token& birth = NrdBridgeBirth::Token())
{
    RRPsoMetadata& metadata = gRRPsoMetadata[pipelineState];
    if (RRInspectorBirthsEnabled() && metadata.birth != birth) metadata = {};
    metadata.birth = birth;
    if (metadata.id == 0)
        metadata.id = gRRNextPsoId.fetch_add(1, std::memory_order_relaxed);
    if (metadata.kind == RRPsoKind::Unknown && kind != RRPsoKind::Unknown)
        metadata.kind = kind;
    if (metadata.hash == 0 && hash != 0)
        metadata.hash = hash;
    return metadata;
}

// Caller holds gRRPsoMutex; weak producer paths only inspect prepared metadata.
static RRPsoMetadata* FindRRPsoMetadataLocked(ID3D12PipelineState* pipeline)
{
    const auto found = gRRPsoMetadata.find(pipeline);
    if (found == gRRPsoMetadata.end()) return nullptr;
    if (RRInspectorBirthsEnabled() && (!found->second.birth || !found->second.birth->CacheAdmissible())) return nullptr;
    return &found->second;
}
static bool PublishRRPsoMetadata(ID3D12PipelineState* pipeline, RRPsoKind kind = RRPsoKind::Unknown,
                                uint64_t hash = 0) noexcept
{
    if (!pipeline) return false;
    if (FrameSurvey::OwnedRelease()) { CleanupRRPsoReferences(pipeline); return false; }
    try
    {
        const bool born = RRInspectorBirthsEnabled();
        if (!born && !EnsurePsoReleaseHook(pipeline)) return false;
        const auto birth = born ? RRStrongReceiver(pipeline) : NrdBridgeBirth::Token{};
        NrdBridgeBirth::CurrentGuard current(birth,born);
        if (born && (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy())) return false;
        std::scoped_lock lock(gRRPsoMutex);
        EnsureRRPsoMetadata(pipeline,kind,hash,birth);
        return true;
    }
    catch (...) { NrdBridgeNativeBirth::Detail::Fail("RR PSO metadata publication failed"); return false; }
}
static void PublishCreatedRRPso(void* output, REFIID iid, RRPsoKind kind, uint64_t hash) noexcept
{
    try
    {
        ReturnedPipelineInterface returned(output,iid);
        if (!returned.pipeline) return;
        if (RRInspectorBirthsEnabled() && output != returned.pipeline && !FrameSurvey::OwnedRelease())
        {
            if (!NrdBridgeNativeBirth::ObserveReleaseCoverage(static_cast<IUnknown*>(output))) return;
            const auto birth = RRStrongReceiver(returned.pipeline);
            NrdBridgeNativeBirth::RetirementScope effects;
            if (!birth || !effects.Valid() || !NrdBridgeBirth::LinkAlias(birth->InstanceStamp(),output)) return;
        }
        PublishRRPsoMetadata(returned.pipeline,kind,hash);
    }
    catch (...) { NrdBridgeNativeBirth::Detail::Fail("created RR PSO metadata failed"); }
}
static RRCommandListPsoState& RRPsoListStateLocked(ID3D12GraphicsCommandList* list,
                                                 const NrdBridgeBirth::Token& receiver)
{
    auto& state = gRRCommandListPsoStates[list];
    if (RRInspectorBirthsEnabled() && state.receiverBirth != receiver)
    {
        for (auto* pso : RRPsoPointers(state)) RemoveRRPsoListMembershipLocked(pso,list);
        state = {}; state.receiverBirth = receiver;
    }
    return state;
}
static bool RRPsoListAvailable(const RRCommandListPsoState& state, ID3D12GraphicsCommandList* list) noexcept
{
    return !RRInspectorBirthsEnabled() || (state.receiverBirth && state.receiverBirth->Address() == list &&
        state.receiverBirth->CacheAdmissible());
}
static void RecordRRPsoProducer(ID3D12Resource* resource, ID3D12PipelineState* pipelineState,
                                bool ambiguous)
{
    if (resource == nullptr || pipelineState == nullptr || FrameSurvey::OwnedRelease())
        return;

    const auto prepared = FindRRPsoMetadataLocked(pipelineState);
    if (!prepared) return;
    const RRPsoMetadata metadata = *prepared;
    RRPsoProducerStats& stats = gRRResourcePsoProducers[resource][pipelineState];
    stats.metadata = metadata;
    ++stats.hits;
    stats.lastFrame = gRRResourceInspectorFrame.load(std::memory_order_relaxed);
    stats.ambiguous = stats.ambiguous || ambiguous;
    try { gRRPsoProducerResources[pipelineState].insert(resource); }
    catch (...)
    {
        gRRResourcePsoProducers[resource].erase(pipelineState);
        if (gNrdBridgeWrappers) FrameSurvey::MetadataHookFailed("RR producer participant index allocation failed");
    }
}

// Called only while gRRPsoMutex is held.
static void RecordRRGraphicsOutputs(ID3D12GraphicsCommandList* commandList)
{
    if (FrameSurvey::OwnedRelease()) return;
    const auto found = gRRCommandListPsoStates.find(commandList);
    if (found == gRRCommandListPsoStates.end())
        return;

    RRCommandListPsoState& state = found->second;
    if (!RRPsoListAvailable(state,commandList) || state.currentPso == nullptr || state.renderTargets.empty())
        return;

    const auto prepared = FindRRPsoMetadataLocked(state.currentPso);
    if (!prepared) return;
    RRPsoMetadata& metadata = *prepared;
    if (metadata.kind == RRPsoKind::Unknown || metadata.kind == RRPsoKind::Stream)
        metadata.kind = RRPsoKind::Graphics;

    const uint64_t frame = gRRResourceInspectorFrame.load(std::memory_order_relaxed);
    if (state.lastGraphicsPso == state.currentPso &&
        state.lastGraphicsGeneration == state.renderTargetGeneration &&
        state.lastGraphicsFrame == frame)
    {
        return;
    }

    for (ID3D12Resource* resource : state.renderTargets)
        RecordRRPsoProducer(resource, state.currentPso, false);

    const auto previous = RRPsoPointers(state);
    state.lastGraphicsPso = state.currentPso;
    UpdateRRPsoListReferencesLocked(commandList,previous,state);
    state.lastGraphicsGeneration = state.renderTargetGeneration;
    state.lastGraphicsFrame = frame;
}

static void RecordRRComputeOutput(ID3D12GraphicsCommandList* commandList, ID3D12Resource* resource)
{
    if (resource == nullptr || FrameSurvey::OwnedRelease())
        return;

    std::scoped_lock psoLock(gRRPsoMutex);
    const auto found = gRRCommandListPsoStates.find(commandList);
    if (found == gRRCommandListPsoStates.end())
        return;

    RRCommandListPsoState& state = found->second;
    if (!RRPsoListAvailable(state,commandList) || state.lastComputePso == nullptr)
        return;

    const auto prepared = FindRRPsoMetadataLocked(state.lastComputePso);
    if (!prepared) return;
    RRPsoMetadata& metadata = *prepared;
    if (metadata.kind == RRPsoKind::Unknown || metadata.kind == RRPsoKind::Stream)
        metadata.kind = RRPsoKind::Compute;
    RecordRRPsoProducer(resource, state.lastComputePso,
                        state.dispatchesSinceBarrier > 1);
    state.dispatchesSinceBarrier = 0;
}

static const char* GetRRPsoKindName(uint8_t kind)
{
    switch (static_cast<RRPsoKind>(kind))
    {
    case RRPsoKind::Graphics:
        return "Graphics";
    case RRPsoKind::Compute:
        return "Compute";
    case RRPsoKind::Stream:
        return "Stream";
    default:
        return "Unknown";
    }
}

static std::string DecodeRRMarkerName(const void* data, UINT size)
{
    if (data == nullptr || size == 0)
        return {};

    constexpr UINT kMaxMarkerBytes = 4096;
    const auto* bytes = static_cast<const uint8_t*>(data);
    const size_t byteCount = std::min<size_t>(size, kMaxMarkerBytes);
    const auto printable = [](uint8_t value) { return value >= 32 && value <= 126; };

    std::string best;
    for (size_t begin = 0; begin < byteCount;)
    {
        while (begin < byteCount && !printable(bytes[begin]))
            ++begin;
        size_t end = begin;
        while (end < byteCount && printable(bytes[end]))
            ++end;
        if (end - begin >= 4 && end - begin > best.size())
            best.assign(reinterpret_cast<const char*>(bytes + begin), end - begin);
        begin = end + 1;
    }

    for (size_t alignment = 0; alignment < 2; ++alignment)
    {
        for (size_t begin = alignment; begin + 1 < byteCount;)
        {
            while (begin + 1 < byteCount &&
                   !(printable(bytes[begin]) && bytes[begin + 1] == 0))
            {
                begin += 2;
            }
            size_t end = begin;
            std::string candidate;
            while (end + 1 < byteCount && printable(bytes[end]) && bytes[end + 1] == 0)
            {
                candidate.push_back(static_cast<char>(bytes[end]));
                end += 2;
            }
            if (candidate.size() >= 4 && candidate.size() > best.size())
                best = std::move(candidate);
            begin = end + 2;
        }
    }

    while (!best.empty() && std::isspace(static_cast<unsigned char>(best.front())))
        best.erase(best.begin());
    while (!best.empty() && std::isspace(static_cast<unsigned char>(best.back())))
        best.pop_back();
    return best;
}

static bool IsRREmissiveMarker(std::string_view name)
{
    return std::search(name.begin(), name.end(), "emiss", "emiss" + 5,
                       [](char left, char right) {
                           return std::tolower(static_cast<unsigned char>(left)) == right;
                       }) != name.end();
}

static void ObserveRRMarker(const std::string& name)
{
    if (name.empty())
        return;

    constexpr size_t kMaxMarkerInventory = 2048;
    if (!gRRMarkerInventory.contains(name) &&
        gRRMarkerInventory.size() >= kMaxMarkerInventory)
    {
        return;
    }

    RRMarkerInventoryItem& item = gRRMarkerInventory[name];
    ++item.count;
    item.lastFrame = gRRResourceInspectorFrame.load(std::memory_order_relaxed);
}

static std::pair<std::string, bool> GetRRActivePass(ID3D12GraphicsCommandList* commandList)
{
    std::scoped_lock markerLock(gRRMarkerMutex);
    const auto found = gRRCommandListMarkers.find(commandList);
    if (found == gRRCommandListMarkers.end())
        return {};

    const RRCommandListMarkerState& markers = found->second;
    std::string path;
    for (const std::string& marker : markers.stack)
    {
        if (marker.empty())
            continue;
        if (!path.empty())
            path += " > ";
        path += marker;
    }
    if (path.empty())
        path = markers.lastMarker;
    return { path, IsRREmissiveMarker(path) };
}

static uint32_t GetRRFormatChannelCount(DXGI_FORMAT format)
{
    switch (format)
    {
    case DXGI_FORMAT_R8_UNORM:
    case DXGI_FORMAT_R8_SNORM:
    case DXGI_FORMAT_R16_FLOAT:
    case DXGI_FORMAT_R16_UNORM:
    case DXGI_FORMAT_R16_SNORM:
    case DXGI_FORMAT_R32_FLOAT:
    case DXGI_FORMAT_R32_TYPELESS:
    case DXGI_FORMAT_R16_TYPELESS:
    case DXGI_FORMAT_R8_TYPELESS:
        return 1;

    case DXGI_FORMAT_R8G8_UNORM:
    case DXGI_FORMAT_R8G8_SNORM:
    case DXGI_FORMAT_R16G16_FLOAT:
    case DXGI_FORMAT_R16G16_UNORM:
    case DXGI_FORMAT_R16G16_SNORM:
    case DXGI_FORMAT_R32G32_FLOAT:
    case DXGI_FORMAT_R8G8_TYPELESS:
    case DXGI_FORMAT_R16G16_TYPELESS:
    case DXGI_FORMAT_R32G32_TYPELESS:
        return 2;

    case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_SNORM:
    case DXGI_FORMAT_R8G8B8A8_TYPELESS:
    case DXGI_FORMAT_B8G8R8A8_UNORM:
    case DXGI_FORMAT_B8G8R8A8_TYPELESS:
    case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R10G10B10A2_TYPELESS:
    case DXGI_FORMAT_R16G16B16A16_FLOAT:
    case DXGI_FORMAT_R16G16B16A16_UNORM:
    case DXGI_FORMAT_R16G16B16A16_SNORM:
    case DXGI_FORMAT_R16G16B16A16_TYPELESS:
    case DXGI_FORMAT_R32G32B32A32_FLOAT:
    case DXGI_FORMAT_R32G32B32A32_TYPELESS:
        return 4;

    default:
        return 0;
    }
}

// Retain the original helper names because descriptor-copy tracking uses them
// to keep candidate views alive even when HUD tracking is disabled. "Scalar"
// now also includes packed normalized/float formats so specular occlusion can
// be discovered in any component.
static bool IsRRScalarCandidateFormat(DXGI_FORMAT format)
{
    return GetRRFormatChannelCount(format) > 0;
}

static bool IsRRScalarCandidateResource(ID3D12Resource* resource, DXGI_FORMAT viewFormat)
{
    if (resource == nullptr)
        return false;

    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    const DXGI_FORMAT effectiveFormat =
        viewFormat == DXGI_FORMAT_UNKNOWN ? desc.Format : viewFormat;
    return desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
           desc.SampleDesc.Count == 1 && desc.Width >= 256 && desc.Height >= 256 &&
           !(desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) &&
           IsRRScalarCandidateFormat(effectiveFormat);
}

static void TrackRRResourceView(ID3D12Resource* resource, DXGI_FORMAT viewFormat, ResourceType type)
{
    if (!gRRResourceInspectorEnabled.load(std::memory_order_relaxed) || !resource) return;
    if (FrameSurvey::OwnedRelease())
    { std::scoped_lock lock(gRRTrackedResourceMutex); EraseRRTrackedResourceLocked(resource); return; }
    // This native API caller owns the input; prepare identity/description before locks.
    try
    {
        const bool born = RRInspectorBirthsEnabled();
        RRTrackedResourceViews prepared;
        {
            std::scoped_lock lock(gRRTrackedResourceMutex);
            const auto found = gRRTrackedResources.find(resource);
            if (found != gRRTrackedResources.end() && (!born ||
                (found->second.birth && found->second.birth->CacheAdmissible()))) prepared = found->second;
        }
        auto birth = born ? prepared.birth : NrdBridgeBirth::Token{};
        if (!prepared.version)
        {
            if (born) { birth = RRStrongReceiver(resource); if (!birth) return; }
            else if (!RRPhysicalReleaseCovered(resource)) return;
            prepared.desc = resource->GetDesc();
        }
        const auto& desc = prepared.desc;
        const auto effectiveFormat = viewFormat == DXGI_FORMAT_UNKNOWN ? desc.Format : viewFormat;
        if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.SampleDesc.Count != 1 ||
            desc.Width < 256 || desc.Height < 256 || (desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            !IsRRScalarCandidateFormat(effectiveFormat)) return;
        if (!prepared.version)
        {
            UINT bytes = UINT(prepared.debugName.size());
            if (FAILED(resource->GetPrivateData(WKPDID_D3DDebugObjectName,&bytes,prepared.debugName.data()))) prepared.debugName = {};
            prepared.debugName.back() = '\0';
        }
        NrdBridgeBirth::CurrentGuard current(birth,born);
        if (born && (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy())) return;
        std::scoped_lock lock(gRRTrackedResourceMutex);
        auto found = gRRTrackedResources.find(resource);
        if (found != gRRTrackedResources.end() && born && found->second.birth != birth)
        { EraseRRTrackedResourceLocked(resource); found = gRRTrackedResources.end(); }
        if (found == gRRTrackedResources.end())
        {
            prepared.birth = birth; prepared.version = gRRNextResourceVersion.fetch_add(1,std::memory_order_relaxed);
            if (!prepared.version) throw std::overflow_error("RR inspector resource generation exhausted");
            found = gRRTrackedResources.emplace(resource,prepared).first;
            try { gRRResourceSizeIndex[{desc.Width,desc.Height}].insert(resource); }
            catch (...) { EraseRRTrackedResourceLocked(resource); throw; }
        }
        auto& views = found->second;
        if (type == SRV) ++views.srvViews; else if (type == UAV) ++views.uavViews; else if (type == RTV) ++views.rtvViews;
    }
    catch (...)
    {
        if (RRInspectorBirthsEnabled()) NrdBridgeNativeBirth::Detail::Fail("RR inspector view metadata allocation failed");
    }
}

// Whether the preview can read this resource without first transitioning it.
//
// The preview is built by the conversion pass, which is a compute shader, so the non-pixel bit
// is the one that matters. Accepting either shader-read bit let a resource the title had only
// ever handed to a pixel pass reach that one, where the read is undefined - and the inspector
// deliberately records no barrier of its own, because the resource belongs to the title and its
// state is only ever what the tracker observed. Restoring a state that was inferred rather than
// declared is a worse failure than a preview that declines to run, so a resource in the wrong
// read state is reported as non-readable and left alone.
static bool IsRRResourceComputeReadable(D3D12_RESOURCE_STATES state)
{
    constexpr D3D12_RESOURCE_STATES kComputeRead =
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    constexpr D3D12_RESOURCE_STATES kWritable =
        D3D12_RESOURCE_STATE_RENDER_TARGET | D3D12_RESOURCE_STATE_UNORDERED_ACCESS |
        D3D12_RESOURCE_STATE_DEPTH_WRITE | D3D12_RESOURCE_STATE_COPY_DEST |
        D3D12_RESOURCE_STATE_RESOLVE_DEST;
    return (state & kComputeRead) != 0 && (state & kWritable) == 0;
}

static bool IsRRResourceWritable(D3D12_RESOURCE_STATES state)
{
    constexpr D3D12_RESOURCE_STATES kWritable =
        D3D12_RESOURCE_STATE_RENDER_TARGET | D3D12_RESOURCE_STATE_UNORDERED_ACCESS |
        D3D12_RESOURCE_STATE_DEPTH_WRITE | D3D12_RESOURCE_STATE_COPY_DEST |
        D3D12_RESOURCE_STATE_RESOLVE_DEST;
    return (state & kWritable) != 0;
}

// Called while gRRResourceStateMutex is held.
static void RecordRRResourceWrite(ID3D12Resource* resource, const std::string& passName,
                                  bool emissivePassMatch)
{
    if (resource == nullptr)
        return;

    RRResourceActivity& activity = gRRResourceActivity[resource];
    const uint64_t frame = gRRResourceInspectorFrame.load(std::memory_order_relaxed);
    ++activity.writeTransitionCount;
    if (!passName.empty())
    {
        activity.lastWritePass = passName;
        activity.emissivePassMatch = emissivePassMatch;
        ++activity.passWriteCount;
    }

    if (!activity.writeObserved || activity.lastWriteFrame != frame)
    {
        if (activity.writeObserved)
            activity.previousWriteFrame = activity.lastWriteFrame;
        activity.lastWriteFrame = frame;
        ++activity.writtenFrameCount;
        activity.writeObserved = true;
    }
}

void ResTrack_Dx12::SetRRResourceInspectorEnabled(bool enabled)
{
    if (enabled) gRRInspectorLifetimeProtection.store(true,std::memory_order_release);
    gRRSelectionEpoch.fetch_add(1,std::memory_order_acq_rel);
    gRRResourceInspectorEnabled.store(enabled, std::memory_order_release);

    if (enabled)
    {
        // The device hook is not installed for FSR-RR at device-creation time, because
        // this inspector is off by default and the upscaler can be switched at runtime.
        // Install it on demand instead. HookDevice is idempotent, so this is a no-op
        // when OptiFG's HUD fix already hooked the device. Descriptor heaps created
        // before this point are not tracked, but every consumer null-checks the heap
        // lookup and the candidate registry is fed by the view-creation hooks, which
        // games exercise continuously.
        ResTrack_Dx12::HookDevice(State::Instance().currentD3D12Device);
    }
    else
    {
        {
            std::scoped_lock lock(gRRResourceStateMutex);
            gRRResourceStates.clear();
            gRRResourceActivity.clear();
            gRRRecordingProofs.clear(); ++gRRSelectedStateEpoch;
        }
        {
            std::scoped_lock markerLock(gRRMarkerMutex);
            gRRCommandListMarkers.clear();
            gRRMarkerInventory.clear();
        }
        {
            std::scoped_lock psoLock(gRRPsoMutex);
            gRRCommandListPsoStates.clear();
            gRRResourcePsoProducers.clear();
            gRRPsoCommandLists.clear();
            gRRPsoProducerResources.clear();
            // PSO metadata is only collected while the inspector is on, so it
            // is cleared here as well instead of surviving until global
            // teardown; ids restart on the next enable, matching teardown.
            gRRPsoMetadata.clear();
            gRRNextPsoId.store(1, std::memory_order_release);
        }
        {
            // This map is only fed while the inspector is on and otherwise shrinks
            // solely through hkRelease, so without this it survives every level load
            // for the rest of the process.
            std::scoped_lock resourceLock(gRRTrackedResourceMutex);
            gRRTrackedResources.clear(); gRRResourceSizeIndex.clear();
        }
    }
}

bool ResTrack_Dx12::IsRRResourceInspectorEnabled()
{
    return gRRResourceInspectorEnabled.load(std::memory_order_acquire);
}

void ResTrack_Dx12::NotifyRRResourceInspectorFrame(uint64_t frameIndex)
{
    gRRResourceInspectorFrame.store(frameIndex, std::memory_order_release);
}

void ResTrack_Dx12::SetRRResourceCandidateIndex(int index)
{
    std::scoped_lock candidateLock(gRRResourceCandidateMutex);
    if (gRRResourceCandidates.empty())
    {
        gRRResourceCandidateIndex.store(0, std::memory_order_release);
        SelectRRResourceLocked(nullptr);
        return;
    }

    const int selected =
        std::clamp(index, 0, static_cast<int>(gRRResourceCandidates.size()) - 1);
    gRRResourceCandidateIndex.store(selected, std::memory_order_release);
    SelectRRResourceLocked(&gRRResourceCandidates[selected]);
}

int ResTrack_Dx12::GetRRResourceCandidateIndex()
{
    return gRRResourceCandidateIndex.load(std::memory_order_acquire);
}

void ResTrack_Dx12::SetRRResourceChannel(uint32_t channel)
{
    gRRResourceChannel.store(std::min(channel, 3u), std::memory_order_release);
}

uint32_t ResTrack_Dx12::GetRRResourceChannel()
{
    return gRRResourceChannel.load(std::memory_order_acquire);
}

void ResTrack_Dx12::SetRRResourceViewScale(float scale)
{
    gRRResourceViewScale.store(std::clamp(scale, 0.01f, 100.0f), std::memory_order_release);
}

float ResTrack_Dx12::GetRRResourceViewScale()
{
    return gRRResourceViewScale.load(std::memory_order_acquire);
}

void ResTrack_Dx12::RefreshRRResourceCandidates(uint32_t renderWidth, uint32_t renderHeight)
{
    std::vector<RRResourceCandidate> candidates;
    const uint64_t currentFrame =
        gRRResourceInspectorFrame.load(std::memory_order_acquire);
    {
        // This registry is populated directly by CreateSRV/CreateUAV/CreateRTV.
        // It intentionally does not depend on the HUD descriptor cache, whose
        // auto settings may discard non-HUD views.
        std::scoped_lock resourceLock(gRRTrackedResourceMutex);
        const auto bucket = gRRResourceSizeIndex.find({renderWidth,renderHeight});
        if (bucket != gRRResourceSizeIndex.end()) for (auto* resource : bucket->second)
        {
            const auto found = gRRTrackedResources.find(resource);
            if (found == gRRTrackedResources.end()) continue;
            const auto& views = found->second;
            if (RRInspectorBirthsEnabled() && (!views.birth || !views.birth->CacheAdmissible())) continue;
            const auto& desc = views.desc;
            RRResourceCandidate candidate {};
            candidate.resourceAddress = resource;
            candidate.resourceBirth = views.birth; candidate.registryVersion = views.version;
            candidate.debugName = views.debugName.data();
            candidate.width = desc.Width;
            candidate.height = desc.Height;
            candidate.format = desc.Format;
            candidate.flags = desc.Flags;
            candidate.channelCount = GetRRFormatChannelCount(desc.Format);
            candidate.previewSupported = candidate.channelCount > 0;
            candidate.srvViews = views.srvViews;
            candidate.uavViews = views.uavViews;
            candidate.rtvViews = views.rtvViews;

            if (candidate.previewSupported && candidate.srvViews > 0)
                candidates.push_back(candidate);
        }
    }

    {
        std::scoped_lock stateLock(gRRResourceStateMutex);
        for (RRResourceCandidate& candidate : candidates)
        {
            ID3D12Resource* resource = static_cast<ID3D12Resource*>(candidate.resourceAddress);
            const auto state = gRRResourceStates.find(resource);
            if (state != gRRResourceStates.end())
            {
                candidate.stateKnown = true;
                candidate.state = state->second;
                candidate.computeReadable = IsRRResourceComputeReadable(candidate.state);
            }

            candidate.currentFrame = currentFrame;
            const auto activity = gRRResourceActivity.find(resource);
            if (activity != gRRResourceActivity.end() && activity->second.writeObserved)
            {
                const RRResourceActivity& observed = activity->second;
                candidate.writeObserved = true;
                candidate.lastWriteFrame = observed.lastWriteFrame;
                candidate.previousWriteFrame = observed.previousWriteFrame;
                candidate.writtenFrameCount = observed.writtenFrameCount;
                candidate.writeTransitionCount = observed.writeTransitionCount;
                candidate.passWriteCount = observed.passWriteCount;
                candidate.lastWritePass = observed.lastWritePass;
                candidate.emissivePassMatch = observed.emissivePassMatch;
                candidate.writeAgeFrames =
                    currentFrame >= observed.lastWriteFrame
                        ? currentFrame - observed.lastWriteFrame
                        : 0;
                candidate.lastWriteInterval =
                    observed.previousWriteFrame > 0 &&
                            observed.lastWriteFrame >= observed.previousWriteFrame
                        ? observed.lastWriteFrame - observed.previousWriteFrame
                        : 0;
                candidate.active = candidate.writeAgeFrames <= 4;
                candidate.alternating =
                    candidate.active && candidate.lastWriteInterval >= 2 &&
                    candidate.lastWriteInterval <= 4;
            }
        }
    }

    {
        std::scoped_lock psoLock(gRRPsoMutex);
        for (RRResourceCandidate& candidate : candidates)
        {
            ID3D12Resource* resource = static_cast<ID3D12Resource*>(candidate.resourceAddress);
            const auto producers = gRRResourcePsoProducers.find(resource);
            if (producers == gRRResourcePsoProducers.end())
                continue;

            candidate.producerCount = static_cast<uint32_t>(producers->second.size());
            const RRPsoProducerStats* topProducer = nullptr;
            for (const auto& [pipelineState, stats] : producers->second)
            {
                if (topProducer == nullptr || stats.hits > topProducer->hits ||
                    (stats.hits == topProducer->hits &&
                     stats.lastFrame > topProducer->lastFrame))
                {
                    topProducer = &stats;
                }
            }

            if (topProducer != nullptr)
            {
                candidate.producerPsoId = topProducer->metadata.id;
                candidate.producerPsoHash = topProducer->metadata.hash;
                candidate.producerKind = static_cast<uint8_t>(topProducer->metadata.kind);
                candidate.producerHitCount = topProducer->hits;
                candidate.producerAmbiguous = topProducer->ambiguous;
            }
        }
    }

    std::sort(candidates.begin(), candidates.end(), [](const RRResourceCandidate& left,
                                                       const RRResourceCandidate& right) {
        if (left.channelCount != right.channelCount)
            return left.channelCount < right.channelCount;
        if (left.format != right.format)
            return left.format < right.format;
        return left.resourceAddress < right.resourceAddress;
    });

    {
        std::scoped_lock candidateLock(gRRResourceCandidateMutex);
        gRRResourceCandidates = std::move(candidates);
        if (gRRResourceCandidates.empty())
        {
            gRRResourceCandidateIndex.store(0, std::memory_order_release);
            SelectRRResourceLocked(nullptr);
            return;
        }

        const uintptr_t selectedAddress =
            gRRResourceCandidateAddress.load(std::memory_order_acquire);
        int selected = -1;
        if (selectedAddress != 0)
        {
            const auto found = std::find_if(
                gRRResourceCandidates.begin(), gRRResourceCandidates.end(),
                [selectedAddress](const RRResourceCandidate& candidate) {
                    return reinterpret_cast<uintptr_t>(candidate.resourceAddress) ==
                           selectedAddress;
                });
            if (found != gRRResourceCandidates.end())
                selected = static_cast<int>(
                    std::distance(gRRResourceCandidates.begin(), found));
        }

        if (selected < 0)
        {
            selected = std::clamp(
                gRRResourceCandidateIndex.load(std::memory_order_acquire), 0,
                static_cast<int>(gRRResourceCandidates.size()) - 1);

        }
        gRRResourceCandidateIndex.store(selected, std::memory_order_release);
        SelectRRResourceLocked(&gRRResourceCandidates[selected]);
    }
}

std::vector<RRResourceCandidate> ResTrack_Dx12::GetRRResourceCandidates()
{
    std::scoped_lock lock(gRRResourceCandidateMutex);
    return gRRResourceCandidates;
}

const char* ResTrack_Dx12::GetRRResourceInspectorReason() noexcept
{ return gRRInspectorReason.load(std::memory_order_acquire); }

ID3D12Resource* ResTrack_Dx12::AcquireRRResourceCandidate(ID3D12GraphicsCommandList* consumer)
{
    const auto reject = [](const char* reason) -> ID3D12Resource* {
        gRRInspectorReason.store(reason,std::memory_order_release); return nullptr;
    };
    if (!IsRRResourceInspectorEnabled()) return reject("CPU lifetime unavailable: resource inspector is disabled.");
    const auto receiver = PrepareRRRecording(consumer); // Strong caller; no metadata locks held.
    if (!receiver.valid) return reject("GPU state unavailable: consumer Reset/Close/Barrier or Release coverage is unknown.");
    NrdBridgeLifetime::ScopedBorrow lifetime(gRRInspectorLifetimeProtection.load(std::memory_order_acquire));
    if (!lifetime.Acquired()) return reject("CPU lifetime unavailable: nested Release cannot borrow the selected resource.");
    const auto selected = CaptureRRSelectedIdentity();
    if (!selected.resource) return reject("CPU lifetime unavailable: selected resource is no longer in the preview inventory.");
    {
        NrdBridgeBirth::CurrentGuard current(selected.birth,RRInspectorBirthsEnabled());
        if (RRInspectorBirthsEnabled() && !current.AdmitsBorrow())
            return reject("CPU lifetime unavailable: selected native resource identity is not admissible.");
        std::scoped_lock lock(gRRTrackedResourceMutex);
        const auto found = gRRTrackedResources.find(selected.resource);
        if (found == gRRTrackedResources.end() || found->second.version != selected.version || found->second.birth != selected.birth)
            return reject("CPU lifetime unavailable: selected resource was released or its registry version changed.");
    }
    {
        NrdBridgeBirth::CurrentGuard current(receiver.birth,receiver.born);
        if (receiver.born && !current.AdmitsBorrow())
            return reject("CPU lifetime unavailable: consumer native command-list identity is not admissible.");
        std::scoped_lock lock(gRRResourceStateMutex);
        const auto found = gRRRecordingProofs.find(receiver.key);
        if (found == gRRRecordingProofs.end() || !found->second.recordingSerial)
            return reject("GPU state unavailable: no selected-resource transition was observed in this recording.");
        const auto& proof = found->second;
        if (selected.selectionEpoch != gRRSelectionEpoch.load(std::memory_order_acquire) ||
            proof.selected.selectionEpoch != selected.selectionEpoch || proof.selected.resource != selected.resource ||
            proof.selected.version != selected.version || proof.selected.birth != selected.birth ||
            proof.stateEpoch != gRRSelectedStateEpoch || !IsRRResourceComputeReadable(proof.state))
            return reject("GPU state unavailable: selected resource changed state, selection, or recording; a fresh whole-resource readable transition is required.");
    }
    selected.resource->AddRef(); // No metadata/Birth guards; physical Borrow still protects the weak native call.
    gRRInspectorReason.store("",std::memory_order_release);
    return selected.resource;
}

void ResTrack_Dx12::LogRRScalarResourceCandidates(uint32_t renderWidth, uint32_t renderHeight)
{
    RefreshRRResourceCandidates(renderWidth, renderHeight);
    const std::vector<RRResourceCandidate> candidates = GetRRResourceCandidates();

    LOG_INFO("[RR_RESOURCE_CANDIDATE] snapshot: render={}x{}, previewableResources={}",
             renderWidth, renderHeight, candidates.size());
    for (size_t index = 0; index < candidates.size(); ++index)
    {
        const RRResourceCandidate& candidate = candidates[index];
        const auto formatName = magic_enum::enum_name(candidate.format);
        LOG_INFO(
            "[RR_RESOURCE_CANDIDATE] candidate[{}]: ptr={:X}, size={}x{}, format={}({}), "
            "flags={:#x}, channels={}, views=[SRV:{}, UAV:{}, RTV:{}], writable={}, "
            "stateKnown={}, state={:#x}, computeReadable={}, name='{}', writeObserved={}, "
            "active={}, alternating={}, writeAge={}, interval={}, writtenFrames={}, transitions={}, "
            "passWrites={}, emissivePassMatch={}, lastWritePass='{}', producer=[id:{}, hash:{:016X}, "
            "kind:{}, hits:{}, count:{}, ambiguous:{}]",
            index, reinterpret_cast<uintptr_t>(candidate.resourceAddress),
            candidate.width, candidate.height,
            formatName.empty() ? "UNKNOWN" : formatName, static_cast<uint32_t>(candidate.format),
            static_cast<uint32_t>(candidate.flags), candidate.channelCount,
            candidate.srvViews, candidate.uavViews, candidate.rtvViews,
            !!(candidate.flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS),
            candidate.stateKnown, static_cast<uint32_t>(candidate.state), candidate.computeReadable,
            candidate.debugName, candidate.writeObserved, candidate.active, candidate.alternating,
            candidate.writeObserved ? std::to_string(candidate.writeAgeFrames) : "never",
            candidate.lastWriteInterval, candidate.writtenFrameCount,
            candidate.writeTransitionCount, candidate.passWriteCount,
            candidate.emissivePassMatch, candidate.lastWritePass,
            candidate.producerPsoId, candidate.producerPsoHash,
            candidate.producerKind, candidate.producerHitCount,
            candidate.producerCount, candidate.producerAmbiguous);
    }

    if (candidates.empty())
    {
        struct InventoryItem
        {
            ID3D12Resource* resource = nullptr;
            D3D12_RESOURCE_DESC desc {};
            RRTrackedResourceViews views {};
            uint64_t sizeDelta = 0;
        };

        std::vector<InventoryItem> inventory;
        {
            std::scoped_lock resourceLock(gRRTrackedResourceMutex);
            inventory.reserve(gRRTrackedResources.size());
            for (const auto& [resource, views] : gRRTrackedResources)
            {
                if (resource == nullptr || views.srvViews == 0)
                    continue;

                const D3D12_RESOURCE_DESC desc = views.desc;
                if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D)
                    continue;

                InventoryItem item {};
                item.resource = resource;
                item.desc = desc;
                item.views = views;
                item.sizeDelta =
                    static_cast<uint64_t>(std::abs(static_cast<int64_t>(desc.Width) - renderWidth)) +
                    static_cast<uint64_t>(std::abs(static_cast<int64_t>(desc.Height) - renderHeight));
                inventory.push_back(item);
            }
        }

        std::sort(inventory.begin(), inventory.end(), [](const InventoryItem& left, const InventoryItem& right) {
            return left.sizeDelta < right.sizeDelta;
        });

        constexpr size_t kInventoryLogLimit = 64;
        LOG_INFO(
            "[RR_RESOURCE_INVENTORY] no exact preview candidates; trackedTexture2DResources={}, "
            "logging closest {}",
            inventory.size(), std::min(inventory.size(), kInventoryLogLimit));
        for (size_t index = 0; index < std::min(inventory.size(), kInventoryLogLimit); ++index)
        {
            const InventoryItem& item = inventory[index];
            const auto formatName = magic_enum::enum_name(item.desc.Format);
            LOG_INFO(
                "[RR_RESOURCE_INVENTORY] resource[{}]: ptr={:X}, size={}x{}, format={}({}), "
                "flags={:#x}, mips={}, arrays={}, views=[SRV:{}, UAV:{}, RTV:{}], sizeDelta={}",
                index, reinterpret_cast<uintptr_t>(item.resource),
                item.desc.Width, item.desc.Height,
                formatName.empty() ? "UNKNOWN" : formatName,
                static_cast<uint32_t>(item.desc.Format), static_cast<uint32_t>(item.desc.Flags),
                item.desc.MipLevels, item.desc.DepthOrArraySize,
                item.views.srvViews, item.views.uavViews, item.views.rtvViews, item.sizeDelta);
        }
    }
}

void ResTrack_Dx12::LogRREmissivePassSnapshot(uint32_t renderWidth, uint32_t renderHeight)
{
    RefreshRRResourceCandidates(renderWidth, renderHeight);
    const std::vector<RRResourceCandidate> candidates = GetRRResourceCandidates();

    std::vector<std::pair<std::string, RRMarkerInventoryItem>> markers;
    {
        std::scoped_lock markerLock(gRRMarkerMutex);
        markers.reserve(gRRMarkerInventory.size());
        for (const auto& marker : gRRMarkerInventory)
            markers.push_back(marker);
    }
    std::sort(markers.begin(), markers.end(), [](const auto& left, const auto& right) {
        const bool leftEmissive = IsRREmissiveMarker(left.first);
        const bool rightEmissive = IsRREmissiveMarker(right.first);
        if (leftEmissive != rightEmissive)
            return leftEmissive > rightEmissive;
        if (left.second.lastFrame != right.second.lastFrame)
            return left.second.lastFrame > right.second.lastFrame;
        return left.second.count > right.second.count;
    });

    const size_t emissiveMarkerCount = static_cast<size_t>(std::count_if(
        markers.begin(), markers.end(),
        [](const auto& marker) { return IsRREmissiveMarker(marker.first); }));
    const size_t associatedResourceCount = static_cast<size_t>(std::count_if(
        candidates.begin(), candidates.end(),
        [](const RRResourceCandidate& candidate) { return !candidate.lastWritePass.empty(); }));
    const size_t emissiveResourceCount = static_cast<size_t>(std::count_if(
        candidates.begin(), candidates.end(),
        [](const RRResourceCandidate& candidate) { return candidate.emissivePassMatch; }));

    LOG_INFO(
        "[RR_EMISSIVE_PASS] snapshot: render={}x{}, markerNames={}, emissiveMarkerNames={}, "
        "passAssociatedResources={}, emissivePassResources={}",
        renderWidth, renderHeight, markers.size(), emissiveMarkerCount,
        associatedResourceCount, emissiveResourceCount);

    constexpr size_t kMarkerLogLimit = 128;
    for (size_t index = 0; index < std::min(markers.size(), kMarkerLogLimit); ++index)
    {
        const auto& [name, item] = markers[index];
        LOG_INFO(
            "[RR_EMISSIVE_PASS] marker[{}]: emissiveMatch={}, count={}, lastFrame={}, name='{}'",
            index, IsRREmissiveMarker(name), item.count, item.lastFrame, name);
    }

    for (size_t index = 0; index < candidates.size(); ++index)
    {
        const RRResourceCandidate& candidate = candidates[index];
        if (candidate.lastWritePass.empty())
            continue;
        const auto formatName = magic_enum::enum_name(candidate.format);
        LOG_INFO(
            "[RR_EMISSIVE_PASS] resource[{}]: ptr={:X}, size={}x{}, format={}({}), "
            "emissiveMatch={}, passWrites={}, writeAge={}, views=[SRV:{}, UAV:{}, RTV:{}], pass='{}'",
            index, reinterpret_cast<uintptr_t>(candidate.resourceAddress),
            candidate.width, candidate.height,
            formatName.empty() ? "UNKNOWN" : formatName,
            static_cast<uint32_t>(candidate.format), candidate.emissivePassMatch,
            candidate.passWriteCount,
            candidate.writeObserved ? std::to_string(candidate.writeAgeFrames) : "never",
            candidate.srvViews, candidate.uavViews, candidate.rtvViews,
            candidate.lastWritePass);
    }
}

void ResTrack_Dx12::LogRRPsoProducerSnapshot(uint32_t renderWidth, uint32_t renderHeight)
{
    RefreshRRResourceCandidates(renderWidth, renderHeight);
    const std::vector<RRResourceCandidate> candidates = GetRRResourceCandidates();
    const size_t associated = static_cast<size_t>(std::count_if(
        candidates.begin(), candidates.end(),
        [](const RRResourceCandidate& candidate) { return candidate.producerPsoId != 0; }));
    const size_t ambiguous = static_cast<size_t>(std::count_if(
        candidates.begin(), candidates.end(),
        [](const RRResourceCandidate& candidate) { return candidate.producerAmbiguous; }));

    LOG_INFO(
        "[RR_PSO_PRODUCER] snapshot: render={}x{}, resources={}, associated={}, ambiguous={}",
        renderWidth, renderHeight, candidates.size(), associated, ambiguous);
    for (size_t index = 0; index < candidates.size(); ++index)
    {
        const RRResourceCandidate& candidate = candidates[index];
        if (candidate.producerPsoId == 0)
            continue;

        const auto formatName = magic_enum::enum_name(candidate.format);
        LOG_INFO(
            "[RR_PSO_PRODUCER] resource[{}]: ptr={:X}, format={}({}), producerId={}, "
            "producerHash={:016X}, kind={}, hits={}, producerCount={}, ambiguous={}, "
            "writeAge={}, views=[SRV:{}, UAV:{}, RTV:{}]",
            index, reinterpret_cast<uintptr_t>(candidate.resourceAddress),
            formatName.empty() ? "UNKNOWN" : formatName,
            static_cast<uint32_t>(candidate.format), candidate.producerPsoId,
            candidate.producerPsoHash, GetRRPsoKindName(candidate.producerKind),
            candidate.producerHitCount, candidate.producerCount,
            candidate.producerAmbiguous,
            candidate.writeObserved ? std::to_string(candidate.writeAgeFrames) : "never",
            candidate.srvViews, candidate.uavViews, candidate.rtvViews);
    }
}

bool ResTrack_Dx12::CheckResource(ID3D12Resource* resource)
{
    if (State::Instance().isShuttingDown)
        return false;

    auto resDesc = resource->GetDesc();

    if (resDesc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D)
        return false;

    auto& s = State::Instance();

    if (resDesc.Height != s.currentSwapchainDesc.BufferDesc.Height ||
        resDesc.Width != s.currentSwapchainDesc.BufferDesc.Width)
    {
        auto result = Config::Instance()->FGRelaxedResolutionCheck.value_or_default() &&
                      resDesc.Height >= s.currentSwapchainDesc.BufferDesc.Height - 32 &&
                      resDesc.Height <= s.currentSwapchainDesc.BufferDesc.Height + 32 &&
                      resDesc.Width >= s.currentSwapchainDesc.BufferDesc.Width - 32 &&
                      resDesc.Width <= s.currentSwapchainDesc.BufferDesc.Width + 32;

        // LOG_TRACK("Resource: {}x{} ({}), Swapchain: {}x{} ({}), Relaxed Result: {}", resDesc.Width, resDesc.Height,
        //           (UINT) resDesc.Format, scDesc.BufferDesc.Width, scDesc.BufferDesc.Height,
        //           (UINT) scDesc.BufferDesc.Format, result);

        return result;
    }

    return true;
}

inline static IID streamlineRiid {};
inline static std::once_flag streamlineRiidInitFlag;

bool ResTrack_Dx12::CheckForRealObject(const std::string functionName, IUnknown* pObject, IUnknown** ppRealObject)
{
    std::call_once(streamlineRiidInitFlag,
                   []() { IIDFromString(L"{ADEC44E2-61F0-45C3-AD9F-1B37379284FF}", &streamlineRiid); });

    auto qResult = pObject->QueryInterface(streamlineRiid, (void**) ppRealObject);

    if (qResult == S_OK && *ppRealObject != nullptr)
    {
        LOG_INFO("{} Streamline proxy found!", functionName);
        (*ppRealObject)->Release();
        return true;
    }

    return false;
}

#pragma region Resource methods

bool ResTrack_Dx12::CreateBufferResource(ID3D12Device* InDevice, ResourceInfo* InSource, D3D12_RESOURCE_STATES InState,
                                         ID3D12Resource** OutResource)
{
    if (InDevice == nullptr || InSource == nullptr || InSource->buffer == nullptr)
        return false;

    if (*OutResource != nullptr)
    {
        auto bufDesc = (*OutResource)->GetDesc();

        if (bufDesc.Width != (UINT64) (InSource->width) || bufDesc.Height != (UINT) (InSource->height) ||
            bufDesc.Format != InSource->format)
        {
            (*OutResource)->Release();
            (*OutResource) = nullptr;
        }
        else
            return true;
    }

    D3D12_HEAP_PROPERTIES heapProperties;
    D3D12_HEAP_FLAGS heapFlags;
    HRESULT hr = InSource->buffer->GetHeapProperties(&heapProperties, &heapFlags);

    if (hr != S_OK)
    {
        LOG_ERROR("GetHeapProperties result: {0:X}", (UINT64) hr);
        return false;
    }

    D3D12_RESOURCE_DESC texDesc = InSource->buffer->GetDesc();
    texDesc.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET | D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;

    hr = InDevice->CreateCommittedResource(&heapProperties, D3D12_HEAP_FLAG_NONE, &texDesc, InState, nullptr,
                                           IID_PPV_ARGS(OutResource));

    if (hr != S_OK)
    {
        LOG_ERROR("CreateCommittedResource result: {0:X}", (UINT64) hr);
        return false;
    }

    (*OutResource)->SetName(L"fgHudlessSCBufferCopy");
    return true;
}

void ResTrack_Dx12::ResourceBarrier(ID3D12GraphicsCommandList* InCommandList, ID3D12Resource* InResource,
                                    D3D12_RESOURCE_STATES InBeforeState, D3D12_RESOURCE_STATES InAfterState)
{
    if (InBeforeState == InAfterState)
        return;

    D3D12_RESOURCE_BARRIER barrier = {};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = InResource;
    barrier.Transition.StateBefore = InBeforeState;
    barrier.Transition.StateAfter = InAfterState;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    InCommandList->ResourceBarrier(1, &barrier);
}

#pragma endregion

#pragma region Heap helpers

SIZE_T ResTrack_Dx12::GetGPUHandle(ID3D12Device* This, SIZE_T cpuHandle, D3D12_DESCRIPTOR_HEAP_TYPE type)
{
    SIZE_T sourceStart = 0, destinationStart = 0; uint64_t version = 0;
    std::shared_ptr<HeapInfo> heap;
    {
        std::shared_lock lock(_heapRegistryMutex);
        heap = FindIndexedHeapRangeLocked(gHeapCpuRanges,cpuHandle,false);
        if (heap) { sourceStart = heap->cpuStart; version = heap->version.load(std::memory_order_relaxed); destinationStart = heap->gpuStart; }
    }
    if (!destinationStart) return 0;
    const auto increment = This->GetDescriptorHandleIncrementSize(type); // Strong device, outside the heap registry lock.
    if (!increment || !heap->active.load(std::memory_order_acquire) ||
        heap->version.load(std::memory_order_acquire) != version) return 0;
    return destinationStart + ((cpuHandle-sourceStart)/increment)*increment;
}

SIZE_T ResTrack_Dx12::GetCPUHandle(ID3D12Device* This, SIZE_T gpuHandle, D3D12_DESCRIPTOR_HEAP_TYPE type)
{
    SIZE_T sourceStart = 0, destinationStart = 0; uint64_t version = 0;
    std::shared_ptr<HeapInfo> heap;
    {
        std::shared_lock lock(_heapRegistryMutex);
        heap = FindIndexedHeapRangeLocked(gHeapGpuRanges,gpuHandle,true);
        if (heap) { sourceStart = heap->gpuStart; version = heap->version.load(std::memory_order_relaxed); destinationStart = heap->cpuStart; }
    }
    if (!destinationStart) return 0;
    const auto increment = This->GetDescriptorHandleIncrementSize(type); // Strong device, outside the heap registry lock.
    if (!increment || !heap->active.load(std::memory_order_acquire) ||
        heap->version.load(std::memory_order_acquire) != version) return 0;
    return destinationStart + ((gpuHandle-sourceStart)/increment)*increment;
}

static std::shared_ptr<HeapInfo> FindHeapByCpuHandle(SIZE_T cpuHandle, HeapCacheTLS& heapCache)
{
    const auto currentGen = gHeapGeneration.load(std::memory_order_acquire);
    auto* cachedHeap = heapCache.heap.get();
    if (heapCache.genSeen == currentGen && cachedHeap != nullptr &&
        cachedHeap->version.load(std::memory_order_relaxed) == heapCache.heapVersion &&
        cachedHeap->active.load(std::memory_order_acquire) && cachedHeap->cpuStart <= cpuHandle &&
        cpuHandle < cachedHeap->cpuEnd)
    {
        return heapCache.heap;
    }

    std::shared_lock lock(_heapRegistryMutex);
    const auto registryGen = gHeapGeneration.load(std::memory_order_acquire);
    const auto heap = FindIndexedHeapRangeLocked(gHeapCpuRanges,cpuHandle,false);
    if (heap)
    {
        heapCache.genSeen = registryGen;
        heapCache.heap = heap;
        heapCache.heapVersion = heap->version.load(std::memory_order_relaxed);
        return heap;
    }

    heapCache.genSeen = registryGen;
    heapCache.heapVersion = 0;
    heapCache.heap.reset();
    return nullptr;
}

static std::shared_ptr<HeapInfo> FindHeapByGpuHandle(SIZE_T gpuHandle, HeapCacheTLS& heapCache)
{
    if (gpuHandle == NULL)
        return nullptr;

    const auto currentGen = gHeapGeneration.load(std::memory_order_acquire);
    auto* cachedHeap = heapCache.heap.get();
    if (heapCache.genSeen == currentGen && cachedHeap != nullptr &&
        cachedHeap->version.load(std::memory_order_relaxed) == heapCache.heapVersion &&
        cachedHeap->active.load(std::memory_order_acquire) && cachedHeap->gpuStart <= gpuHandle &&
        gpuHandle < cachedHeap->gpuEnd)
    {
        return heapCache.heap;
    }

    std::shared_lock lock(_heapRegistryMutex);
    const auto registryGen = gHeapGeneration.load(std::memory_order_acquire);
    const auto heap = FindIndexedHeapRangeLocked(gHeapGpuRanges,gpuHandle,true);
    if (heap)
    {
        heapCache.genSeen = registryGen;
        heapCache.heap = heap;
        heapCache.heapVersion = heap->version.load(std::memory_order_relaxed);
        return heap;
    }

    heapCache.genSeen = registryGen;
    heapCache.heapVersion = 0;
    heapCache.heap.reset();
    return nullptr;
}

std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandleCBV(SIZE_T cpuHandle)
{
    return FindHeapByCpuHandle(cpuHandle, cacheCBV);
}

std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandleRTV(SIZE_T cpuHandle)
{
    return FindHeapByCpuHandle(cpuHandle, cacheRTV);
}

std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandleSRV(SIZE_T cpuHandle)
{
    return FindHeapByCpuHandle(cpuHandle, cacheSRV);
}

std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandleUAV(SIZE_T cpuHandle)
{
    return FindHeapByCpuHandle(cpuHandle, cacheUAV);
}

std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByCpuHandle(SIZE_T cpuHandle)
{
    return FindHeapByCpuHandle(cpuHandle, cache);
}

std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByGpuHandleGR(SIZE_T gpuHandle)
{
    return FindHeapByGpuHandle(gpuHandle, cacheGR);
}

std::shared_ptr<HeapInfo> ResTrack_Dx12::GetHeapByGpuHandleCR(SIZE_T gpuHandle)
{
    return FindHeapByGpuHandle(gpuHandle, cacheCR);
}

#pragma endregion

#pragma region Hudless methods

void ResTrack_Dx12::FillResourceInfo(ID3D12Resource* resource, ResourceInfo* info)
{
    auto desc = resource->GetDesc();
    if (gNrdBridgeWrappers && NrdBridgeNativeBirth::Ready() && !FrameSurvey::Internal() &&
        ObserveBridgeObjectRelease(resource)) info->birth = NrdBridgeNativeBirth::Receiver(resource);
    info->buffer = resource;
    info->width = desc.Width;
    info->height = desc.Height;
    info->format = desc.Format;
    info->flags = desc.Flags;
}

bool ResTrack_Dx12::IsHudFixActive()
{
    if (!Config::Instance()->FGEnabled.value_or_default() || !Config::Instance()->FGHUDFix.value_or_default())
    {
        LOG_TRACK(
            "!Config::Instance()->FGEnabled.value_or_default() || !Config::Instance()->FGHUDFix.value_or_default()");
        return false;
    }

    if (State::Instance().currentFG == nullptr || State::Instance().currentFeature == nullptr ||
        State::Instance().fgChanged)
    {
        LOG_TRACK("State::Instance().currentFG == nullptr || State::Instance().currentFeature == nullptr || "
                  "State::Instance().fgChanged");
        return false;
    }

    if (!State::Instance().currentFG->IsActive())
    {
        LOG_TRACK("!State::Instance().currentFG->IsActive()");
        return false;
    }

    if (!_presentDone)
    {
        LOG_TRACK("!_presentDone");
        return false;
    }

    if (Hudfix_Dx12::SkipHudlessChecks())
    {
        LOG_TRACK("!Hudfix_Dx12::SkipHudlessChecks()");
        return false;
    }

    if (!Hudfix_Dx12::IsResourceCheckActive())
    {
        // LOG_TRACK("!Hudfix_Dx12::IsResourceCheckActive()");
        return false;
    }

    return true;
}

#pragma endregion

#pragma region Resource input hooks

void ResTrack_Dx12::hkCreateRenderTargetView(ID3D12Device* This, ID3D12Resource* pResource,
                                             D3D12_RENDER_TARGET_VIEW_DESC* pDesc,
                                             D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor)
{
    // force hdr for swapchain buffer
    if (pResource != nullptr && pDesc != nullptr && Config::Instance()->ForceHDR.value_or_default())
    {
        for (size_t i = 0; i < State::Instance().scBuffers.size(); i++)
        {
            if (State::Instance().scBuffers[i] == pResource)
            {
                if (Config::Instance()->UseHDR10.value_or_default())
                    pDesc->Format = DXGI_FORMAT_R10G10B10A2_UNORM;
                else
                    pDesc->Format = DXGI_FORMAT_R16G16B16A16_FLOAT;

                break;
            }
        }
    }

    o_CreateRenderTargetView(This, pResource, pDesc, DestDescriptor);

    const DXGI_FORMAT viewFormat = pDesc == nullptr ? DXGI_FORMAT_UNKNOWN : pDesc->Format;
    const bool isTexture2D =
        pDesc == nullptr || pDesc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2D;
    if (isTexture2D)
        TrackRRResourceView(pResource, viewFormat, RTV);

    if (Config::Instance()->FGHudfixDisableRTV.value_or_default())
        return;

    const bool isHudResource = pResource != nullptr && pDesc != nullptr &&
                               pDesc->ViewDimension == D3D12_RTV_DIMENSION_TEXTURE2D &&
                               CheckResource(pResource);
    // Retaining a candidate in the HUD descriptor cache is only useful while the
    // inspector is running, and RefreshRRResourceCandidates does not read that cache
    // anyway - its registry is fed directly by these hooks. Leaving this ungated
    // widens OptiFG's hudless candidate set for every user.
    const bool isRRCandidate = isTexture2D &&
                               gRRResourceInspectorEnabled.load(std::memory_order_relaxed) &&
                               IsRRScalarCandidateResource(pResource, viewFormat);

    if (!isHudResource && !isRRCandidate)
    {
        auto heap = GetHeapByCpuHandleRTV(DestDescriptor.ptr);

        if (heap != nullptr)
            heap->ClearByCpuHandle(DestDescriptor.ptr);

        return;
    }

    // if (!CheckResource(pResource))
    //     return;

    auto heap = GetHeapByCpuHandleRTV(DestDescriptor.ptr);
    if (heap != nullptr)
    {
        ResourceInfo resInfo {};
        FillResourceInfo(pResource, &resInfo);
        if (viewFormat != DXGI_FORMAT_UNKNOWN)
            resInfo.format = viewFormat;
        resInfo.type = RTV;
        resInfo.captureInfo = CaptureInfo::CreateRTV;
        heap->SetByCpuHandle(DestDescriptor.ptr, resInfo);
    }
    // else
    //{
    //     LOG_TRACK("Heap not found for RTV: {:X}", DestDescriptor.ptr);
    // }
}

void ResTrack_Dx12::hkCreateShaderResourceView(ID3D12Device* This, ID3D12Resource* pResource,
                                               D3D12_SHADER_RESOURCE_VIEW_DESC* pDesc,
                                               D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor)
{
    // force hdr for swapchain buffer
    if (pResource != nullptr && pDesc != nullptr && Config::Instance()->ForceHDR.value_or_default())
    {
        for (size_t i = 0; i < State::Instance().scBuffers.size(); i++)
        {
            if (State::Instance().scBuffers[i] == pResource)
            {
                if (Config::Instance()->UseHDR10.value_or_default())
                    pDesc->Format = DXGI_FORMAT_R10G10B10A2_UNORM;
                else
                    pDesc->Format = DXGI_FORMAT_R16G16B16A16_FLOAT;

                break;
            }
        }
    }

    o_CreateShaderResourceView(This, pResource, pDesc, DestDescriptor);

    const DXGI_FORMAT viewFormat = pDesc == nullptr ? DXGI_FORMAT_UNKNOWN : pDesc->Format;
    const bool isTexture2D =
        pDesc == nullptr || pDesc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2D;
    if (isTexture2D)
        TrackRRResourceView(pResource, viewFormat, SRV);

    if (Config::Instance()->FGHudfixDisableSRV.value_or_default())
        return;

    const bool isHudResource = pResource != nullptr && pDesc != nullptr &&
                               pDesc->ViewDimension == D3D12_SRV_DIMENSION_TEXTURE2D &&
                               CheckResource(pResource);
    // Retaining a candidate in the HUD descriptor cache is only useful while the
    // inspector is running, and RefreshRRResourceCandidates does not read that cache
    // anyway - its registry is fed directly by these hooks. Leaving this ungated
    // widens OptiFG's hudless candidate set for every user.
    const bool isRRCandidate = isTexture2D &&
                               gRRResourceInspectorEnabled.load(std::memory_order_relaxed) &&
                               IsRRScalarCandidateResource(pResource, viewFormat);

    if (!isHudResource && !isRRCandidate)
    {
        auto heap = GetHeapByCpuHandleSRV(DestDescriptor.ptr);

        if (heap != nullptr)
            heap->ClearByCpuHandle(DestDescriptor.ptr);

        return;
    }

    // if (!CheckResource(pResource))
    //     return;

    auto heap = GetHeapByCpuHandleSRV(DestDescriptor.ptr);
    if (heap != nullptr)
    {
        ResourceInfo resInfo {};
        FillResourceInfo(pResource, &resInfo);
        if (viewFormat != DXGI_FORMAT_UNKNOWN)
            resInfo.format = viewFormat;
        resInfo.type = SRV;
        resInfo.captureInfo = CaptureInfo::CreateSRV;
        heap->SetByCpuHandle(DestDescriptor.ptr, resInfo);
    }
    // else
    //{
    //     LOG_TRACK("Heap not found for SRV: {:X}", DestDescriptor.ptr);
    // }
}

void ResTrack_Dx12::hkCreateUnorderedAccessView(ID3D12Device* This, ID3D12Resource* pResource,
                                                ID3D12Resource* pCounterResource,
                                                D3D12_UNORDERED_ACCESS_VIEW_DESC* pDesc,
                                                D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor)
{
    if (pResource != nullptr && pDesc != nullptr && Config::Instance()->ForceHDR.value_or_default())
    {
        for (size_t i = 0; i < State::Instance().scBuffers.size(); i++)
        {
            if (State::Instance().scBuffers[i] == pResource)
            {
                if (Config::Instance()->UseHDR10.value_or_default())
                    pDesc->Format = DXGI_FORMAT_R10G10B10A2_UNORM;
                else
                    pDesc->Format = DXGI_FORMAT_R16G16B16A16_FLOAT;

                break;
            }
        }
    }

    o_CreateUnorderedAccessView(This, pResource, pCounterResource, pDesc, DestDescriptor);

    const DXGI_FORMAT viewFormat = pDesc == nullptr ? DXGI_FORMAT_UNKNOWN : pDesc->Format;
    const bool isTexture2D =
        pDesc == nullptr || pDesc->ViewDimension == D3D12_UAV_DIMENSION_TEXTURE2D;
    if (isTexture2D)
        TrackRRResourceView(pResource, viewFormat, UAV);

    if (Config::Instance()->FGHudfixDisableUAV.value_or_default())
        return;

    const bool isHudResource = pResource != nullptr && pDesc != nullptr &&
                               pDesc->ViewDimension == D3D12_UAV_DIMENSION_TEXTURE2D &&
                               CheckResource(pResource);
    // Retaining a candidate in the HUD descriptor cache is only useful while the
    // inspector is running, and RefreshRRResourceCandidates does not read that cache
    // anyway - its registry is fed directly by these hooks. Leaving this ungated
    // widens OptiFG's hudless candidate set for every user.
    const bool isRRCandidate = isTexture2D &&
                               gRRResourceInspectorEnabled.load(std::memory_order_relaxed) &&
                               IsRRScalarCandidateResource(pResource, viewFormat);

    if (!isHudResource && !isRRCandidate)
    {
        auto heap = GetHeapByCpuHandleUAV(DestDescriptor.ptr);

        if (heap != nullptr)
            heap->ClearByCpuHandle(DestDescriptor.ptr);

        return;
    }

    // if (!CheckResource(pResource))
    //     return;

    auto heap = GetHeapByCpuHandleUAV(DestDescriptor.ptr);
    if (heap != nullptr)
    {
        ResourceInfo resInfo {};
        FillResourceInfo(pResource, &resInfo);
        if (viewFormat != DXGI_FORMAT_UNKNOWN)
            resInfo.format = viewFormat;
        resInfo.type = UAV;
        resInfo.captureInfo = CaptureInfo::CreateUAV;
        heap->SetByCpuHandle(DestDescriptor.ptr, resInfo);
    }
    // else
    //{
    //     LOG_TRACK("Heap not found for UAV: {:X}", DestDescriptor.ptr);
    // }
}

#pragma endregion

void ResTrack_Dx12::hkExecuteCommandLists(ID3D12CommandQueue* This, UINT NumCommandLists,
                                          ID3D12CommandList* const* ppCommandLists)
{
    if (!RequiredComputeSubmissionAllowed()) return;
    auto fg = State::Instance().currentFG;

    if (fg != nullptr && fg->IsActive() && !fg->IsPaused())
    {
        LOG_TRACK("NumCommandLists: {}", NumCommandLists);

        std::vector<FG_ResourceType> found;
        auto fIndex = fg->GetIndex();

        do
        {
            std::lock_guard<std::mutex> lock2(_resourceCommandListMutex);

            if (!_notFoundCmdLists.empty())
            {
                for (size_t i = 0; i < NumCommandLists; i++)
                {
                    if (_notFoundCmdLists.contains(ppCommandLists[i]))
                    {
                        LOG_WARN("Found last frames cmdList: {:X}", (size_t) ppCommandLists[i]);
                        _notFoundCmdLists.erase(ppCommandLists[i]);
                    }
                }
            }

            if (_resCmdList[fIndex].empty())
                break;

            for (size_t i = 0; i < NumCommandLists; i++)
            {
                LOG_TRACK("ppCommandLists[{}]: {:X}", i, (size_t) ppCommandLists[i]);

                for (const auto& pair : _resCmdList[fIndex])
                {
                    if (pair.second == ppCommandLists[i])
                    {
                        LOG_DEBUG("found {} cmdList: {:X}, queue: {:X}", (UINT) pair.first, (size_t) pair.second,
                                  (size_t) This);
                        fg->SetResourceReady(pair.first);
                        found.push_back(pair.first);
                    }
                }

                for (size_t i = 0; i < found.size(); i++)
                {
                    _resCmdList[fIndex].erase(found[i]);
                }

                if (_resCmdList[fIndex].empty())
                    break;
            }

        } while (false);

        if (!found.empty())
        {
            RecordedComputeLease::SubmissionDecision decision;
            auto computeIntent = BeforeComputeSubmission(This, NumCommandLists, ppCommandLists,&decision);
            if (!decision.allowed)
            {
                LOG_ERROR("[NRD_BRIDGE] required GPU ordering failed (HRESULT {:X}); submission denied; restart the title/device",uint32_t(decision.orderingFailure));
                return;
            }
            auto additiveTickets = RRTraceFence::BeforeSubmission(This, NumCommandLists, ppCommandLists);
            if (!RequiredComputeSubmissionAllowed(&decision)) return;
            o_ExecuteCommandLists(This, NumCommandLists, ppCommandLists);
            RecordedComputeLease::AfterSubmission(computeIntent);
            RRTraceFence::AfterSubmission(This, additiveTickets);

            for (size_t i = 0; i < found.size(); i++)
            {
                fg->SetCommandQueue(found[i], This);
            }

            return;
        }
    }

    LOG_TRACK("Done NumCommandLists: {}", NumCommandLists);

    RecordedComputeLease::SubmissionDecision decision;
    auto computeIntent = BeforeComputeSubmission(This, NumCommandLists, ppCommandLists,&decision);
    if (!decision.allowed)
    {
        LOG_ERROR("[NRD_BRIDGE] required GPU ordering failed (HRESULT {:X}); submission denied; restart the title/device",uint32_t(decision.orderingFailure));
        return;
    }
    auto additiveTickets = RRTraceFence::BeforeSubmission(This, NumCommandLists, ppCommandLists);
    if (!RequiredComputeSubmissionAllowed(&decision)) return;
    o_ExecuteCommandLists(This, NumCommandLists, ppCommandLists);
    RecordedComputeLease::AfterSubmission(computeIntent);
    RRTraceFence::AfterSubmission(This, additiveTickets);
}

#pragma region Heap hooks

static ULONG STDMETHODCALLTYPE hkHeapRelease(ID3D12DescriptorHeap* This)
{
    if (gHeapReleaseSharesResource.load(std::memory_order_acquire) && gSharedResourceReleaseObserver)
        return gSharedResourceReleaseObserver(reinterpret_cast<ID3D12Resource*>(This));
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::Release,gNrdBridgeWrappers && !FrameSurvey::OwnedRelease());
    if (UseNrdNativeRetirement() && !State::Instance().isShuttingDown)
        return NrdBridgeRelease::Title(This,o_HeapRelease);
    NrdBridgeLifetime::ScopedRelease titleRelease(NeedsNativeReleaseGate());
    if (State::Instance().isShuttingDown)
        return o_HeapRelease(This);

    const auto heapInfo = FindTrackedHeapByAddress(This);

    if (heapInfo == nullptr)
    {
        const auto remaining = o_HeapRelease(This);
        // Metadata removal uses only the address, before the physical borrow gate reopens.
        if (!remaining && gNrdBridgeWrappers && !FrameSurvey::OwnedRelease()) FrameSurvey::Released(This);
        return remaining;
    }

    This->AddRef();
    if (o_HeapRelease(This) <= 1)
    {
        if (DeactivateTrackedHeap(heapInfo))
        {
            if (gSurveyWrappers) FrameSurvey::Released(This);
            LOG_INFO("Heap released: {:X}", (size_t) This);
        }
    }

    return o_HeapRelease(This);
}

static void EnsureHeapReleaseHook(ID3D12DescriptorHeap* heap)
{
    std::unique_lock installation(gReleaseHookInstallMutex);
    const auto entry = (*reinterpret_cast<PVOID**>(heap))[2];
    if (const auto original = FindBirthReleaseOriginal(entry))
    {
        if (!o_HeapRelease) { o_HeapRelease = reinterpret_cast<PFN_HeapRelease>(original);
            gHeapReleaseEntry = entry; gHeapOwnsReleaseHook = false; }
        return;
    }
    if (o_HeapRelease)
    {
        if (entry != gHeapReleaseEntry && gNrdBridgeWrappers)
        {
            installation.unlock();
            FrameSurvey::MetadataHookFailed("Descriptor heap Release implementation is not covered by the installed observer");
        }
        return;
    }
    if (entry == gResourceReleaseEntry && o_Release)
    {
        // The resource observer already owns this physical IUnknown entry.
        gHeapReleaseEntry = entry;
        o_HeapRelease = reinterpret_cast<PFN_HeapRelease>(o_Release);
        gHeapOwnsReleaseHook = false;
        gHeapReleaseSharesResource.store(true,std::memory_order_release);
        return;
    }
    if ((entry == gPsoReleaseEntry && o_PsoRelease) ||
        (entry == gCommandListReleaseEntry && o_CommandListRelease))
    {
        // No second detour may own a previously observed IUnknown implementation.
        if (gNrdBridgeWrappers)
        {
            installation.unlock();
            FrameSurvey::MetadataHookFailed("Descriptor heap Release shares an unsupported native observer");
        }
        return;
    }
    gHeapReleaseEntry = entry;
    o_HeapRelease = reinterpret_cast<PFN_HeapRelease>(entry);
    const auto begin = DetourTransactionBegin();
    const auto update = begin == NO_ERROR ? DetourUpdateThread(GetCurrentThread()) : begin;
    const auto attach = update == NO_ERROR ? DetourAttach(&(PVOID&) o_HeapRelease, hkHeapRelease) : update;
    const auto commit = attach == NO_ERROR ? DetourTransactionCommit() :
        (begin == NO_ERROR ? DetourTransactionAbort() : begin);
    const auto result = attach == NO_ERROR ? commit : attach;
    if (result != NO_ERROR)
    {
        LOG_ERROR("Failed to hook Heap Release: {:X}", result);
        o_HeapRelease = nullptr; gHeapReleaseEntry = nullptr;
        if (gNrdBridgeWrappers)
        {
            installation.unlock();
            FrameSurvey::MetadataHookFailed("Descriptor heap Release observer installation failed");
        }
    }
    else gHeapOwnsReleaseHook = true;
}

static bool HeapReleaseObserverCovers(ID3D12DescriptorHeap* heap)
{
    std::lock_guard installation(gReleaseHookInstallMutex);
    const auto entry = (*reinterpret_cast<PVOID**>(heap))[2];
    // The generic resource observer also removes heap metadata by raw address.
    // Uncovered heaps must never enter the borrowed native-descriptor registry.
    return (entry == gResourceReleaseEntry && o_Release) ||
        (entry == gHeapReleaseEntry && o_HeapRelease && gHeapOwnsReleaseHook) || FindBirthReleaseOriginal(entry);
}

// The common resource/heap Release observer cannot use a heap as a resource.
// Resolve only its address and run reverse-index removal outside the resource lock.
static void DeactivateSharedHeap(void* address)
{
    if (!gHeapReleaseSharesResource.load(std::memory_order_acquire)) return;
    if (const auto found = FindTrackedHeapByAddress(address)) DeactivateTrackedHeap(found);
}

namespace
{
struct NativeRetirementPayload
{
    FrameSurvey::RetirementEffects survey;
    TrackedResourceSlots descriptors;
    std::shared_ptr<HeapInfo> heap;
    bool used = false;
};
// Empty payload construction and the common nonfinal Release allocate nothing.
// Only a possible detach enters RetirementScope and prepares raw metadata owners.
thread_local std::array<NativeRetirementPayload,16> gNativeRetirements;
thread_local size_t gNativeRetirementDepth = 0;
void* PrepareNativeRetirement() noexcept
{
    if (gNativeRetirementDepth == gNativeRetirements.size()) return nullptr;
    auto& payload = gNativeRetirements[gNativeRetirementDepth];
    if (payload.used || !FrameSurvey::PrepareRetirementEffects(payload.survey)) return nullptr;
    ++gNativeRetirementDepth;
    return &payload;
}
bool DetachNativeRetirement(void* state,const NrdBridgeBirth::Token& birth) noexcept
{
    auto& payload = *static_cast<NativeRetirementPayload*>(state);
    if (payload.used || !birth || !NrdBridgeBirth::InMetadataAction()) return false;
    payload.used = true;
    if (!FrameSurvey::DetachReleaseMetadata(birth,payload.survey)) return false;
    // The dispatcher receives the actual retired CURRENT token while its address
    // shard is held. Creation/publication must match a current token too.
    D3D12Hooks::OnBridgeObjectReleased(birth);
    auto* resource = static_cast<ID3D12Resource*>(birth->Address());
    try
    {
        { std::scoped_lock lock(gRRResourceStateMutex);
          gRRResourceStates.erase(resource); gRRResourceActivity.erase(resource); }
        { std::scoped_lock lock(gRRTrackedResourceMutex); EraseRRTrackedResourceLocked(resource); }
        { std::scoped_lock lock(gRRPsoMutex); CleanupRRResourcePsoProducersLocked(resource); }
        ForgetRRRecording(resource,birth);
        CleanupRRPsoReferences(resource);
        { std::scoped_lock lock(_trackedResourcesMutex);
          if (const auto found = _trackedResources.find(resource); found != _trackedResources.end())
          { payload.descriptors = std::move(found->second); _trackedResources.erase(found); }
          State::Instance().capturedHudlesses.erase(resource); }
        // Slots are participant-indexed. No traversal of all resources or heaps.
        if (payload.descriptors)
            for (const auto& [key,slot] : *payload.descriptors)
                if (auto heap = slot.heap.lock()) heap->ClearSlotIfMatches(slot.index,resource,birth);
        payload.heap = FindTrackedHeapByAddress(birth->Address());
        if (payload.heap && payload.heap->birth == birth) DeactivateTrackedHeap(payload.heap);
        return true;
    }
    catch (...) { return false; }
}
void NotifyNativeRetirement(void* state) noexcept
{
    auto& payload = *static_cast<NativeRetirementPayload*>(state);
    FrameSurvey::NotifyRelease(payload.survey);
    // Every owner/callback is drained after CurrentGuard and catalog/tracker locks.
    payload.survey = {};
    payload.descriptors.reset();
    payload.heap.reset();
    payload.used = false;
    --gNativeRetirementDepth;
}
}

bool ResTrack_Dx12::ConfigureNrdNativeBirthRetirement() noexcept
{
    if (!NrdBridgeNativeBirth::ConfigureRetirement(PrepareNativeRetirement,DetachNativeRetirement,
                                                  NotifyNativeRetirement)) return false;
    return NrdBridgeLifetime::EnableConcurrentReleases();
}

bool ResTrack_Dx12::ObserveBridgeObjectRelease(IUnknown* object) noexcept
{
    if (!object || !NrdBridgeNativeBirth::Ready() || FrameSurvey::OwnedRelease()) return false;
    if (NrdBridgeBirth::InMetadataScope())
    { FrameSurvey::MetadataHookFailed("Native Release coverage entered under a metadata guard"); return false; }
    const PVOID entry = (*reinterpret_cast<PVOID**>(object))[2];
    const auto covered = [entry] {
        return (entry == gResourceReleaseEntry && o_Release) ||
            (entry == gHeapReleaseEntry && o_HeapRelease) ||
            (entry == gPsoReleaseEntry && o_PsoRelease) ||
            (entry == gCommandListReleaseEntry && o_CommandListRelease) || FindBirthReleaseOriginal(entry);
    };
    if (covered()) return true; // Frequent receivers take no installation lock.
    try
    {
        std::unique_lock installation(gReleaseHookInstallMutex);
        if (covered()) return true;
        if (gBirthReleaseEntriesUsed == MaxBirthReleaseEntries)
        { installation.unlock(); FrameSurvey::MetadataHookFailed("Native Release implementation table is full"); return false; }
        const size_t index = gBirthReleaseEntriesUsed;
        auto& record = gBirthReleaseEntries[index];
        record.original = reinterpret_cast<PFN_BirthRelease>(entry);
        const auto begin = DetourTransactionBegin();
        const auto update = begin == NO_ERROR ? DetourUpdateThread(GetCurrentThread()) : begin;
        const auto attach = update == NO_ERROR ? DetourAttach(reinterpret_cast<PVOID*>(&record.original),
            reinterpret_cast<PVOID>(gBirthReleaseHooks[index])) : update;
        const auto commit = attach == NO_ERROR ? DetourTransactionCommit() :
            (begin == NO_ERROR ? DetourTransactionAbort() : begin);
        if (attach != NO_ERROR || commit != NO_ERROR)
        { record.original = nullptr; installation.unlock();
          FrameSurvey::MetadataHookFailed("Native Release observer installation failed"); return false; }
        record.entry.store(entry,std::memory_order_release);
        ++gBirthReleaseEntriesUsed;
        return true;
    }
    catch (...) { FrameSurvey::MetadataHookFailed("Native Release coverage raised an exception"); return false; }
}

bool NrdBridgeNativeBirth::ObserveReleaseCoverage(IUnknown* object) noexcept
{ return ResTrack_Dx12::ObserveBridgeObjectRelease(object); }

HRESULT ResTrack_Dx12::hkCreateDescriptorHeap(ID3D12Device* This, D3D12_DESCRIPTOR_HEAP_DESC* pDescriptorHeapDesc,
                                              REFIID riid, void** ppvHeap)
{
    auto result = o_CreateDescriptorHeap(This, pDescriptorHeapDesc, riid, ppvHeap);

    if (State::Instance().skipHeapCapture)
        return result;

    if (NrdBridgeNativeBirth::Ready() && FrameSurvey::Internal()) return result;

    try
    {
        if (FAILED(result) || !pDescriptorHeapDesc || !ppvHeap || !*ppvHeap) return result;
        // Normalize a successful uncommon IID with a caller-owned temporary reference.
        ReturnedHeapInterface returned(*ppvHeap,riid);
        if (!returned.heap) return result;
        auto* heap = returned.heap;

        // try to calculate handle ranges for heap
        if (result == S_OK && (pDescriptorHeapDesc->Type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV ||
                               pDescriptorHeapDesc->Type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV))
        {
            EnsureHeapReleaseHook(heap);

            auto increment = This->GetDescriptorHandleIncrementSize(pDescriptorHeapDesc->Type);
            auto numDescriptors = pDescriptorHeapDesc->NumDescriptors;
            auto cpuStart = (SIZE_T) (heap->GetCPUDescriptorHandleForHeapStart().ptr);
            auto cpuEnd = cpuStart + (increment * numDescriptors);
            auto gpuStart = (SIZE_T) (heap->GetGPUDescriptorHandleForHeapStart().ptr);
            auto gpuEnd = gpuStart + (increment * numDescriptors);
            auto type = (UINT) pDescriptorHeapDesc->Type;

            LOG_TRACE("Heap: {:X}, Heap type: {}, Cpu: {}-{}, Gpu: {}-{}, Desc count: {}", (size_t) *ppvHeap, type,
                      cpuStart, cpuEnd, gpuStart, gpuEnd, numDescriptors);
            const auto trackedHeap = std::make_shared<HeapInfo>(heap,cpuStart,cpuEnd,gpuStart,gpuEnd,numDescriptors,increment,type);
            const bool born = gNrdBridgeWrappers && NrdBridgeNativeBirth::Ready() && !FrameSurvey::Internal();
            if (born)
            {
                if (!ObserveBridgeObjectRelease(heap) || !ObserveBridgeObjectRelease(static_cast<IUnknown*>(*ppvHeap))) return result;
                trackedHeap->birth = NrdBridgeNativeBirth::Prepare(heap);
                if (*ppvHeap != heap)
                {
                    NrdBridgeNativeBirth::RetirementScope effects;
                    if (!trackedHeap->birth || !effects.Valid() || !NrdBridgeBirth::LinkAlias(trackedHeap->birth->InstanceStamp(),*ppvHeap)) return result;
                }
            }
            { NrdBridgeBirth::CurrentGuard current(trackedHeap->birth,born);
              if (born && (!current.MatchesCurrent() || !NrdBridgeBirth::Healthy())) return result;
              std::unique_lock lock(_heapRegistryMutex); RegisterTrackedHeapLocked(trackedHeap); }
        }
        else
        {
            if (ppvHeap != nullptr && *ppvHeap != nullptr)
            {
                LOG_TRACE("Skipping, Heap type: {}, Cpu: {}, Gpu: {}", (UINT) pDescriptorHeapDesc->Type,
                          heap->GetCPUDescriptorHandleForHeapStart().ptr, heap->GetGPUDescriptorHandleForHeapStart().ptr);
            }
        }

    }
    catch (...)
    {
        if (gNrdBridgeWrappers) NrdBridgeNativeBirth::Detail::Fail("created heap metadata publication failed");
    }

    return result;
}

ULONG ResTrack_Dx12::hkRelease(ID3D12Resource* This)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::Release,gNrdBridgeWrappers && !FrameSurvey::OwnedRelease());
    if (UseNrdNativeRetirement() && !State::Instance().isShuttingDown)
        return NrdBridgeRelease::Title(This,o_Release);
    NrdBridgeLifetime::ScopedRelease titleRelease(NeedsNativeReleaseGate());
    if (State::Instance().isShuttingDown)
        return o_Release(This);
    auto computeRecording = RecordedComputeLease::BeginRelease(This);

    TrackedResourceSlots toClean;
    // Startup-selected title releases have the physical lifetime guard. Keep the
    // legacy probe serialization for other callers; only the bridge fast path
    // moves native calls/callbacks outside the descriptor reverse-index lock.
    std::unique_lock legacyProbe(_trackedResourcesMutex,std::defer_lock);
    if (!gNrdBridgeWrappers || FrameSurvey::OwnedRelease()) legacyProbe.lock();
    This->AddRef();
    const auto refCount = o_Release(This);
    const bool finalProbe = refCount <= 1;
    if (finalProbe)
    {
        if (gSurveyWrappers) FrameSurvey::Released(This);
        // Release may be shared with command lists; erase by address before final destruction.
        if (gNrdBridgeWrappers)
            D3D12Hooks::OnBridgeCommandListReset(reinterpret_cast<ID3D12GraphicsCommandList*>(This), nullptr);
        {
            std::scoped_lock stateLock(gRRResourceStateMutex);
            gRRResourceStates.erase(This);
            gRRResourceActivity.erase(This);
        }

        {
            std::scoped_lock rrResourceLock(gRRTrackedResourceMutex);
            EraseRRTrackedResourceLocked(This);
        }
        {
            std::scoped_lock psoLock(gRRPsoMutex);
            CleanupRRResourcePsoProducersLocked(This);
        }

        // A runtime may use the same IUnknown::Release implementation for resources and
        // PSOs. In that case this hook also owns PSO cleanup; the helper is a no-op for an
        // ordinary resource address.
        CleanupRRPsoReferences(This);

        {
            if (!legacyProbe.owns_lock()) legacyProbe.lock();
            if (auto it = _trackedResources.find(This); it != _trackedResources.end())
            {
                toClean = std::move(it->second);
                _trackedResources.erase(it);
            }
            State::Instance().capturedHudlesses.erase(This);
        }
    }
    if (legacyProbe.owns_lock()) legacyProbe.unlock();

    if (finalProbe) DeactivateSharedHeap(This);
    // Clean descriptor slots outside the reverse-index lock.
    if (toClean)
        for (const auto& [key,slot] : *toClean)
            if (auto heap = slot.heap.lock()) heap->ClearSlotIfMatches(slot.index,This);

    const ULONG result = o_Release(This);
    RecordedComputeLease::EndRelease(computeRecording, result == 0);
    return result;
}

ULONG hkPsoRelease(ID3D12PipelineState* This)
{
    if (gResourceReleaseSharesPso)
        return gSharedResourceReleaseObserver(reinterpret_cast<ID3D12Resource*>(This));
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::Release,gNrdBridgeWrappers && !FrameSurvey::OwnedRelease());
    if (UseNrdNativeRetirement() && !State::Instance().isShuttingDown)
        return NrdBridgeRelease::Title(This,o_PsoRelease);
    NrdBridgeLifetime::ScopedRelease titleRelease(NeedsNativeReleaseGate());
    if (State::Instance().isShuttingDown)
        return o_PsoRelease(This);
    auto computeRecording = RecordedComputeLease::BeginRelease(This);

    // Same probe as hkRelease: keep the object alive while its metadata is
    // cleaned up, then perform the caller's release.
    This->AddRef();
    auto refCount = o_PsoRelease(This);

    if (refCount <= 1)
    {
        if (gSurveyWrappers) FrameSurvey::Released(This);
        if (gNrdBridgeWrappers)
            D3D12Hooks::OnBridgeCommandListReset(reinterpret_cast<ID3D12GraphicsCommandList*>(This),nullptr);
        CleanupRRPsoReferences(This);
    }

    const ULONG result = o_PsoRelease(This);
    RecordedComputeLease::EndRelease(computeRecording, result == 0);
    return result;
}

static ULONG STDMETHODCALLTYPE hkCommandListRelease(IUnknown* This)
{
    if (gResourceReleaseSharesCommandList)
        return gSharedResourceReleaseObserver(reinterpret_cast<ID3D12Resource*>(This));
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::Release,gNrdBridgeWrappers && !FrameSurvey::OwnedRelease());
    if (UseNrdNativeRetirement() && !State::Instance().isShuttingDown)
        return NrdBridgeRelease::Title(This,o_CommandListRelease);
    NrdBridgeLifetime::ScopedRelease titleRelease(NeedsNativeReleaseGate());
    if (State::Instance().isShuttingDown)
        return o_CommandListRelease(This);
    auto computeRecording = RecordedComputeLease::BeginRelease(This);
    // May also be a PSO using the same original IUnknown entry.
    This->AddRef();
    const ULONG remaining = o_CommandListRelease(This);
    if (remaining <= 1)
    {
        CleanupRRPsoReferences(This);
        if (gSurveyWrappers) FrameSurvey::Released(This);
        if (gNrdBridgeWrappers) D3D12Hooks::OnBridgeCommandListReset(reinterpret_cast<ID3D12GraphicsCommandList*>(This),nullptr);
    }
    const ULONG result = o_CommandListRelease(This);
    RecordedComputeLease::EndRelease(computeRecording, result == 0);
    return result;
}

HRESULT ResTrack_Dx12::hkCreateGraphicsPipelineState(
    ID3D12Device* This, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* pDesc,
    REFIID riid, void** ppPipelineState)
{
    const HRESULT result = o_CreateGraphicsPipelineState(This, pDesc, riid, ppPipelineState);
    if (SUCCEEDED(result) && pDesc != nullptr && ppPipelineState != nullptr &&
        *ppPipelineState != nullptr &&
        gRRResourceInspectorEnabled.load(std::memory_order_relaxed))
    {
        PublishCreatedRRPso(*ppPipelineState,riid,RRPsoKind::Graphics,HashRRGraphicsPipeline(*pDesc));
    }
    return result;
}

HRESULT ResTrack_Dx12::hkCreateComputePipelineState(
    ID3D12Device* This, const D3D12_COMPUTE_PIPELINE_STATE_DESC* pDesc,
    REFIID riid, void** ppPipelineState)
{
    const HRESULT result = o_CreateComputePipelineState(This, pDesc, riid, ppPipelineState);
    if (SUCCEEDED(result) && pDesc != nullptr && ppPipelineState != nullptr &&
        *ppPipelineState != nullptr &&
        gRRResourceInspectorEnabled.load(std::memory_order_relaxed))
    {
        PublishCreatedRRPso(*ppPipelineState,riid,RRPsoKind::Compute,HashRRComputePipeline(*pDesc));
    }
    return result;
}

HRESULT ResTrack_Dx12::hkCreatePipelineState(
    ID3D12Device2* This, const D3D12_PIPELINE_STATE_STREAM_DESC* pDesc,
    REFIID riid, void** ppPipelineState)
{
    const HRESULT result = o_CreatePipelineState(This, pDesc, riid, ppPipelineState);
    if (SUCCEEDED(result) && pDesc != nullptr && ppPipelineState != nullptr &&
        *ppPipelineState != nullptr &&
        gRRResourceInspectorEnabled.load(std::memory_order_relaxed))
    {
        const uint64_t hash = HashRRBytes(
            pDesc->pPipelineStateSubobjectStream, pDesc->SizeInBytes);
        PublishCreatedRRPso(*ppPipelineState,riid,RRPsoKind::Stream,hash);
    }
    return result;
}

void ResTrack_Dx12::hkResourceBarrier(ID3D12GraphicsCommandList* This, UINT NumBarriers,
                                      const D3D12_RESOURCE_BARRIER* pBarriers)
{
    std::vector<ID3D12Resource*> computeWrites;
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && pBarriers != nullptr)
    {
        try
        {
            const auto [passName, emissivePassMatch] = GetRRActivePass(This);
            RRSelectedIdentity selected {}; RRPreparedRecording receiver {};
            auto* selectedAddress = reinterpret_cast<ID3D12Resource*>(gRRResourceCandidateAddress.load(std::memory_order_acquire));
            for (UINT index=0;selectedAddress && index<NumBarriers;++index)
                if (RRBarrierTouchesSelected(pBarriers[index],selectedAddress))
                { selected = CaptureRRSelectedIdentity(); receiver = PrepareRRRecording(This); break; }
            // Native getters use this API caller's valid resource inputs, before any
            // common state lock. Whole-resource transitions need no description at all.
            std::vector<uint8_t> wholeResources(NumBarriers);
            for (UINT index=0;index<NumBarriers;++index)
            {
                const auto& barrier = pBarriers[index];
                if (barrier.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION || !barrier.Transition.pResource) continue;
                if (barrier.Transition.Subresource == D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES) wholeResources[index] = 1;
                else
                {
                    D3D12_RESOURCE_DESC desc {}; bool cached = false;
                    {
                        std::scoped_lock lock(gRRTrackedResourceMutex);
                        const auto found = gRRTrackedResources.find(barrier.Transition.pResource);
                        if (found != gRRTrackedResources.end()) { desc=found->second.desc; cached=true; }
                    }
                    if (!cached) desc = barrier.Transition.pResource->GetDesc();
                    wholeResources[index] = desc.MipLevels == 1 && desc.DepthOrArraySize == 1;
                }
            }
            NrdBridgeBirth::CurrentGuard recording(receiver.birth,receiver.born && receiver.valid);
            if (receiver.born && receiver.valid && !recording.MatchesCurrent()) receiver.valid = false;
            std::scoped_lock stateLock(gRRResourceStateMutex);
            for (UINT index = 0; index < NumBarriers; ++index)
            {
                const D3D12_RESOURCE_BARRIER& barrier = pBarriers[index];
                ObserveRRSelectedStateLocked(receiver,selected,barrier,wholeResources[index] != 0);
                if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING)
                {
                    if (barrier.Aliasing.pResourceBefore != nullptr)
                    {
                        gRRResourceStates.erase(barrier.Aliasing.pResourceBefore);
                        gRRResourceActivity.erase(barrier.Aliasing.pResourceBefore);
                    }
                    if (barrier.Aliasing.pResourceAfter != nullptr)
                    {
                        gRRResourceStates.erase(barrier.Aliasing.pResourceAfter);
                        gRRResourceActivity.erase(barrier.Aliasing.pResourceAfter);
                    }
                    continue;
                }

                if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_UAV)
                {
                    RecordRRResourceWrite(barrier.UAV.pResource, passName, emissivePassMatch);
                    if (barrier.UAV.pResource != nullptr)
                        computeWrites.push_back(barrier.UAV.pResource);
                    continue;
                }

                if (barrier.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                    barrier.Transition.pResource == nullptr)
                {
                    continue;
                }

                ID3D12Resource* resource = barrier.Transition.pResource;
                const bool wholeResource = wholeResources[index] != 0;

                if (!wholeResource ||
                    (barrier.Flags & D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY) != 0)
                {
                    gRRResourceStates.erase(resource);
                    continue;
                }

                gRRResourceStates[resource] = barrier.Transition.StateAfter;
                if (IsRRResourceWritable(barrier.Transition.StateBefore) &&
                    !IsRRResourceWritable(barrier.Transition.StateAfter))
                {
                    RecordRRResourceWrite(resource, passName, emissivePassMatch);
                    if ((barrier.Transition.StateBefore &
                         D3D12_RESOURCE_STATE_UNORDERED_ACCESS) != 0)
                    {
                        computeWrites.push_back(resource);
                    }
                }
            }
        }
        catch (...)
        {
            // Erase only this batch's actual affected resources; cached readable
            // states may never survive a failed observation of their new state.
            std::scoped_lock stateLock(gRRResourceStateMutex);
            for (UINT index=0;index<NumBarriers;++index)
            {
                const auto& barrier = pBarriers[index];
                if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION) gRRResourceStates.erase(barrier.Transition.pResource);
                else if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_UAV) gRRResourceStates.erase(barrier.UAV.pResource);
                else if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING)
                { gRRResourceStates.erase(barrier.Aliasing.pResourceBefore); gRRResourceStates.erase(barrier.Aliasing.pResourceAfter); }
            }
            ++gRRSelectedStateEpoch; // A failed observation cannot preserve any selected state proof.
            computeWrites.clear();
        }
    }

    try { for (ID3D12Resource* resource : computeWrites) RecordRRComputeOutput(This, resource); }
    catch (...) { /* Optional producer metadata cannot suppress the original barrier. */ }

    o_ResourceBarrier(This, NumBarriers, pBarriers);
}

void ResTrack_Dx12::hkSetPipelineState(ID3D12GraphicsCommandList* This,
                                       ID3D12PipelineState* pPipelineState)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && FrameSurvey::OwnedRelease()) ForgetOwnedRRList(This);
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) &&
        !FrameSurvey::OwnedRelease() &&
        This != MenuOverlayDx::MenuCommandList())
    {
        try
        {
            const bool prepared = !pPipelineState || PublishRRPsoMetadata(pPipelineState);
            const bool born = RRInspectorBirthsEnabled();
            const auto receiver = born ? RRStrongReceiver(This) : NrdBridgeBirth::Token{};
            {
                NrdBridgeBirth::CurrentGuard current(receiver,born);
                if (!born || (current.MatchesCurrent() && NrdBridgeBirth::Healthy()))
                {
                    std::scoped_lock psoLock(gRRPsoMutex);
                    auto& state = RRPsoListStateLocked(This,receiver);
                    const auto previous = RRPsoPointers(state);
                    state.currentPso = prepared ? pPipelineState : nullptr;
                    UpdateRRPsoListReferencesLocked(This,previous,state);
                }
            }
        }
        catch (...)
        {
            if (RRInspectorBirthsEnabled()) NrdBridgeNativeBirth::Detail::Fail("RR list PSO metadata failed");
        }
    }
    o_SetPipelineState(This, pPipelineState);
}

HRESULT ResTrack_Dx12::hkReset(ID3D12GraphicsCommandList* This,
                               ID3D12CommandAllocator* pAllocator,
                               ID3D12PipelineState* pInitialState)
{
    const auto inspectorRecording = gRRResourceInspectorEnabled.load(std::memory_order_acquire) ? PrepareRRRecording(This) : RRPreparedRecording{};
    auto computeRecording = RecordedComputeLease::Capture(This);
    const HRESULT result = o_Reset(This, pAllocator, pInitialState);
    if (SUCCEEDED(result)) RecordedComputeLease::Detach(computeRecording);
    if (SUCCEEDED(result)) RRTraceFence::ResetSucceeded(This);
    if (SUCCEEDED(result) && gRRResourceInspectorEnabled.load(std::memory_order_acquire))
    { RRRecordingSucceeded(inspectorRecording,This); if (FrameSurvey::OwnedRelease()) ForgetOwnedRRList(This); }
    if (SUCCEEDED(result) &&
        gRRResourceInspectorEnabled.load(std::memory_order_relaxed) &&
        !FrameSurvey::OwnedRelease())
    {
        try
        {
            const bool prepared = !pInitialState || PublishRRPsoMetadata(pInitialState);
            const bool born = RRInspectorBirthsEnabled();
            const auto receiver = born ? RRStrongReceiver(This) : NrdBridgeBirth::Token{};
            NrdBridgeBirth::CurrentGuard current(receiver,born);
            if (!born || (current.MatchesCurrent() && NrdBridgeBirth::Healthy()))
            {
                std::scoped_lock psoLock(gRRPsoMutex);
                auto& state = RRPsoListStateLocked(This,receiver);
                const auto previous = RRPsoPointers(state);
                state = {}; state.receiverBirth = receiver;
                state.currentPso = prepared ? pInitialState : nullptr;
                UpdateRRPsoListReferencesLocked(This,previous,state);
            }
        }
        catch (...)
        {
            if (RRInspectorBirthsEnabled()) NrdBridgeNativeBirth::Detail::Fail("RR list PSO metadata failed");
        }
    }
    return result;
}

void ResTrack_Dx12::hkSetMarker(ID3D12GraphicsCommandList* This, UINT Metadata, const void* pData, UINT Size)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && !FrameSurvey::OwnedRelease())
    {
        std::string name = DecodeRRMarkerName(pData, Size);
        if (!name.empty())
        {
            std::scoped_lock markerLock(gRRMarkerMutex);
            RRCommandListMarkerState& state = gRRCommandListMarkers[This];
            state.lastMarker = name;
            ObserveRRMarker(name);
        }
    }
    o_SetMarker(This, Metadata, pData, Size);
}

void ResTrack_Dx12::hkBeginEvent(ID3D12GraphicsCommandList* This, UINT Metadata, const void* pData, UINT Size)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && !FrameSurvey::OwnedRelease())
    {
        std::string name = DecodeRRMarkerName(pData, Size);
        std::scoped_lock markerLock(gRRMarkerMutex);
        RRCommandListMarkerState& state = gRRCommandListMarkers[This];
        state.stack.push_back(name);
        if (!name.empty())
        {
            state.lastMarker = name;
            ObserveRRMarker(name);
        }
    }
    o_BeginEvent(This, Metadata, pData, Size);
}

void ResTrack_Dx12::hkEndEvent(ID3D12GraphicsCommandList* This)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && !FrameSurvey::OwnedRelease())
    {
        std::scoped_lock markerLock(gRRMarkerMutex);
        const auto found = gRRCommandListMarkers.find(This);
        if (found != gRRCommandListMarkers.end() && !found->second.stack.empty())
            found->second.stack.pop_back();
    }
    o_EndEvent(This);
}

void ResTrack_Dx12::hkCopyDescriptors(ID3D12Device* This, UINT NumDestDescriptorRanges,
                                      D3D12_CPU_DESCRIPTOR_HANDLE* pDestDescriptorRangeStarts,
                                      UINT* pDestDescriptorRangeSizes, UINT NumSrcDescriptorRanges,
                                      D3D12_CPU_DESCRIPTOR_HANDLE* pSrcDescriptorRangeStarts,
                                      UINT* pSrcDescriptorRangeSizes, D3D12_DESCRIPTOR_HEAP_TYPE DescriptorHeapsType)
{
    o_CopyDescriptors(This, NumDestDescriptorRanges, pDestDescriptorRangeStarts, pDestDescriptorRangeSizes,
                      NumSrcDescriptorRanges, pSrcDescriptorRangeStarts, pSrcDescriptorRangeSizes, DescriptorHeapsType);

    // Early exit conditions - consistent validation
    if (DescriptorHeapsType != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV &&
        DescriptorHeapsType != D3D12_DESCRIPTOR_HEAP_TYPE_RTV)
        return;

    if (NumDestDescriptorRanges == 0 || pDestDescriptorRangeStarts == nullptr)
        return;

    const UINT inc = This->GetDescriptorHandleIncrementSize(DescriptorHeapsType);

    if (!Config::Instance()->FGAlwaysTrackHeaps.value_or_default() && !IsHudFixActive())
    {
        const auto rangeContainsScalarCandidate =
            [inc](UINT rangeCount, const D3D12_CPU_DESCRIPTOR_HANDLE* starts, const UINT* sizes) {
                if (rangeCount == 0 || starts == nullptr)
                    return false;

                for (UINT range = 0; range < rangeCount; ++range)
                {
                    const UINT descriptorCount = sizes == nullptr ? 1u : sizes[range];
                    auto heap = GetHeapByCpuHandle(starts[range].ptr);
                    if (heap == nullptr)
                        continue;

                    for (UINT descriptor = 0; descriptor < descriptorCount; ++descriptor)
                    {
                        const SIZE_T handle = starts[range].ptr + static_cast<SIZE_T>(descriptor) * inc;
                        ResourceInfo info {};
                        if (heap->GetByCpuHandle(handle, info) && info.buffer != nullptr &&
                            IsRRScalarCandidateFormat(info.format))
                        {
                            return true;
                        }
                    }
                }

                return false;
            };

        // Process a copy only when it propagates a scalar candidate or
        // overwrites a destination slot that previously contained one.
        if (!rangeContainsScalarCandidate(
                NumSrcDescriptorRanges, pSrcDescriptorRangeStarts, pSrcDescriptorRangeSizes) &&
            !rangeContainsScalarCandidate(
                NumDestDescriptorRanges, pDestDescriptorRangeStarts, pDestDescriptorRangeSizes))
        {
            return;
        }
    }

    // Validate that we have source descriptors to copy
    bool haveSources = (NumSrcDescriptorRanges > 0 && pSrcDescriptorRangeStarts != nullptr);

    // Track positions in both source and destination ranges
    UINT srcRangeIndex = 0;
    UINT srcOffsetInRange = 0;
    UINT destRangeIndex = 0;
    UINT destOffsetInRange = 0;

    // Cache for heap lookups to avoid repeated lookups within the same range
    std::shared_ptr<HeapInfo> cachedDestHeap;
    SIZE_T cachedDestRangeStart = 0;
    UINT cachedDestRangeSize = 0;
    std::shared_ptr<HeapInfo> cachedSrcHeap;
    SIZE_T cachedSrcRangeStart = 0;
    UINT cachedSrcRangeSize = 0;

    // Process all destination descriptors
    while (destRangeIndex < NumDestDescriptorRanges)
    {
        // Update destination heap cache if we've moved to a new range
        if (destOffsetInRange == 0)
        {
            cachedDestRangeStart = pDestDescriptorRangeStarts[destRangeIndex].ptr;
            cachedDestRangeSize =
                (pDestDescriptorRangeSizes == nullptr) ? 1 : pDestDescriptorRangeSizes[destRangeIndex];
            cachedDestHeap = GetHeapByCpuHandle(cachedDestRangeStart);
        }

        // Calculate current destination handle
        const SIZE_T destHandle = cachedDestRangeStart + (static_cast<SIZE_T>(destOffsetInRange) * inc);

        // Get or update source information
        ResourceInfo srcInfo {};
        bool haveSrcInfo = false;
        if (haveSources && srcRangeIndex < NumSrcDescriptorRanges)
        {
            // Update source heap cache if we've moved to a new range
            if (srcOffsetInRange == 0)
            {
                cachedSrcRangeStart = pSrcDescriptorRangeStarts[srcRangeIndex].ptr;
                cachedSrcRangeSize =
                    (pSrcDescriptorRangeSizes == nullptr) ? 1 : pSrcDescriptorRangeSizes[srcRangeIndex];
                cachedSrcHeap = GetHeapByCpuHandle(cachedSrcRangeStart);
            }

            // Calculate current source handle
            const SIZE_T srcHandle = cachedSrcRangeStart + (static_cast<SIZE_T>(srcOffsetInRange) * inc);

            if (cachedSrcHeap != nullptr)
                haveSrcInfo = cachedSrcHeap->GetByCpuHandle(srcHandle, srcInfo);

            // Advance source position
            srcOffsetInRange++;
            if (srcOffsetInRange >= cachedSrcRangeSize)
            {
                srcOffsetInRange = 0;
                srcRangeIndex++;
            }
        }

        if (cachedDestHeap != nullptr)
        {
            if (haveSrcInfo)
                cachedDestHeap->SetByCpuHandle(destHandle, srcInfo);
            else
                cachedDestHeap->ClearByCpuHandle(destHandle);
        }

        // Advance destination position
        destOffsetInRange++;
        if (destOffsetInRange >= cachedDestRangeSize)
        {
            destOffsetInRange = 0;
            destRangeIndex++;
        }
    }
}

void ResTrack_Dx12::hkCopyDescriptorsSimple(ID3D12Device* This, UINT NumDescriptors,
                                            D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptorRangeStart,
                                            D3D12_CPU_DESCRIPTOR_HANDLE SrcDescriptorRangeStart,
                                            D3D12_DESCRIPTOR_HEAP_TYPE DescriptorHeapsType)
{
    o_CopyDescriptorsSimple(This, NumDescriptors, DestDescriptorRangeStart, SrcDescriptorRangeStart,
                            DescriptorHeapsType);

    if (DescriptorHeapsType != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV &&
        DescriptorHeapsType != D3D12_DESCRIPTOR_HEAP_TYPE_RTV)
        return;

    if (NumDescriptors == 0) return;
    const auto size = This->GetDescriptorHandleIncrementSize(DescriptorHeapsType);
    auto sourceHeap = SrcDescriptorRangeStart.ptr ? GetHeapByCpuHandle(SrcDescriptorRangeStart.ptr) : nullptr;
    auto destinationHeap = GetHeapByCpuHandle(DestDescriptorRangeStart.ptr);
    const auto sourceVersion = sourceHeap ? sourceHeap->version.load(std::memory_order_acquire) : 0;
    const auto destinationVersion = destinationHeap ? destinationHeap->version.load(std::memory_order_acquire) : 0;
    const auto containsRange = [size,NumDescriptors](const std::shared_ptr<HeapInfo>& heap, SIZE_T start) {
        if (!heap || !size || heap->increment != size || !heap->active.load(std::memory_order_acquire) ||
            start < heap->cpuStart || start >= heap->cpuEnd || (start-heap->cpuStart)%size) return false;
        const auto first = (start-heap->cpuStart)/size;
        return first < heap->numDescriptors && NumDescriptors <= heap->numDescriptors-first &&
            SIZE_T(NumDescriptors-1) <= (heap->cpuEnd-1-start)/size;
    };
    const bool sourceRange = containsRange(sourceHeap,SrcDescriptorRangeStart.ptr);
    const bool destinationRange = containsRange(destinationHeap,DestDescriptorRangeStart.ptr);
    const auto currentOwner = [](const std::shared_ptr<HeapInfo>& heap, uint64_t version) {
        return heap && heap->active.load(std::memory_order_acquire) &&
            heap->version.load(std::memory_order_acquire) == version;
    };

    if (!Config::Instance()->FGAlwaysTrackHeaps.value_or_default() && !IsHudFixActive())
    {
        bool containsScalarCandidate = false;
        const auto& srcHeap = sourceHeap;
        const auto& dstHeap = destinationHeap;
        for (UINT descriptor = 0; descriptor < NumDescriptors && !containsScalarCandidate; ++descriptor)
        {
            const SIZE_T srcHandle = SrcDescriptorRangeStart.ptr + static_cast<SIZE_T>(descriptor) * size;
            const SIZE_T dstHandle = DestDescriptorRangeStart.ptr + static_cast<SIZE_T>(descriptor) * size;
            ResourceInfo srcInfo {};
            ResourceInfo dstInfo {};
            const bool hasSrc = srcHeap != nullptr && srcHeap->GetByCpuHandle(srcHandle, srcInfo);
            const bool hasDst = dstHeap != nullptr && dstHeap->GetByCpuHandle(dstHandle, dstInfo);
            containsScalarCandidate =
                (hasSrc && srcInfo.buffer != nullptr && IsRRScalarCandidateFormat(srcInfo.format)) ||
                (hasDst && dstInfo.buffer != nullptr && IsRRScalarCandidateFormat(dstInfo.format));
        }

        if (!containsScalarCandidate)
            return;
    }

    for (size_t i = 0; i < NumDescriptors; i++)
    {
        std::shared_ptr<HeapInfo> srcHeap;
        SIZE_T srcHandle = 0;

        // source
        if (SrcDescriptorRangeStart.ptr != 0)
        {
            srcHandle = SrcDescriptorRangeStart.ptr + i * size;
            // Valid native ranges keep two metadata owners. A retired owner or an
            // unproven span falls back to the existing indexed per-slot lookup.
            srcHeap = sourceRange && currentOwner(sourceHeap,sourceVersion) ? sourceHeap : GetHeapByCpuHandle(srcHandle);
        }

        auto destHandle = DestDescriptorRangeStart.ptr + i * size;
        auto dstHeap = destinationRange && currentOwner(destinationHeap,destinationVersion)
            ? destinationHeap : GetHeapByCpuHandle(destHandle);

        // destination
        if (dstHeap == nullptr)
            continue;

        if (srcHeap == nullptr)
        {
            dstHeap->ClearByCpuHandle(destHandle);
            continue;
        }

        ResourceInfo buffer {};
        if (!srcHeap->GetByCpuHandle(srcHandle, buffer))
        {
            dstHeap->ClearByCpuHandle(destHandle);
            continue;
        }

        dstHeap->SetByCpuHandle(destHandle, buffer);
    }
}

#pragma endregion

#pragma region Shader input hooks

void ResTrack_Dx12::hkSetGraphicsRootDescriptorTable(ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
                                                     D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    // Consistent early exit - always call original function
    auto shouldTrack = !Config::Instance()->FGHudfixDisableSGR.value_or_default() && BaseDescriptor.ptr != 0 &&
                       IsHudFixActive() && !Hudfix_Dx12::SkipHudlessChecks() &&
                       This != MenuOverlayDx::MenuCommandList();

    if (!shouldTrack)
    {
        o_SetGraphicsRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
        return;
    }

    auto heap = GetHeapByGpuHandleGR(BaseDescriptor.ptr);
    if (heap == nullptr)
    {
        LOG_DEBUG_ONLY("No heap for handle: {:X}", BaseDescriptor.ptr);
        o_SetGraphicsRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
        return;
    }

    ResourceInfo capturedBuffer {};
    if (!heap->GetByGpuHandle(BaseDescriptor.ptr, capturedBuffer) || capturedBuffer.buffer == nullptr)
    {
        LOG_DEBUG_ONLY("No resource at RootParameterIndex: {}, CommandList: {:X}, gpuHandle: {:X}", RootParameterIndex,
                       (SIZE_T) This, BaseDescriptor.ptr);
        o_SetGraphicsRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
        return;
    }

    LOG_DEBUG_ONLY("CommandList: {:X}, Resource: {:X}", (size_t) This, (size_t) capturedBuffer.buffer);

    // Only proceed with tracking if we have a valid buffer
    capturedBuffer.state = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    capturedBuffer.captureInfo = CaptureInfo::SetGR;

    // Track the resource
    bool capturedImmediately = false;
    if (Config::Instance()->FGImmediateCapture.value_or_default())
    {
        capturedImmediately = Hudfix_Dx12::CheckForHudless(This, &capturedBuffer, capturedBuffer.state);
    }

    if (!capturedImmediately)
    {
        auto fIndex = Hudfix_Dx12::ActivePresentFrame() % BUFFER_COUNT;

        if (!_useShards)
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);

            if (!fgPossibleHudless[fIndex].contains(This))
            {
                ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> newMap;
                newMap.reserve(32);
                fgPossibleHudless[fIndex].insert_or_assign(This, std::move(newMap));
            }

            LOG_TRACK("Tracking Resource: {:X}, Desc: {:X}", (size_t) capturedBuffer.buffer, BaseDescriptor.ptr);
            fgPossibleHudless[fIndex][This].insert_or_assign(capturedBuffer.buffer, capturedBuffer);
        }
        else
        {
            size_t shardIdx = GetShardIndex(This);
            auto& shard = _hudlessShards[fIndex][shardIdx];

            LOCK_GUARD(shard.mutex);

            if (!shard.map.contains(This))
            {
                ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> newMap;
                newMap.reserve(32);
                shard.map.insert_or_assign(This, std::move(newMap));
            }

            LOG_TRACK("CmdList: {:X}, Tracking Resource: {:X}, Desc: {:X}, Format: {}", (size_t) This,
                      (size_t) capturedBuffer.buffer, BaseDescriptor.ptr, (UINT) capturedBuffer.format);

            shard.map[This].insert_or_assign(capturedBuffer.buffer, capturedBuffer);
        }
    }

    o_SetGraphicsRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
}

#pragma endregion

#pragma region Shader output hooks

void ResTrack_Dx12::hkOMSetRenderTargets(ID3D12GraphicsCommandList* This, UINT NumRenderTargetDescriptors,
                                         D3D12_CPU_DESCRIPTOR_HANDLE* pRenderTargetDescriptors,
                                         BOOL RTsSingleHandleToDescriptorRange,
                                         D3D12_CPU_DESCRIPTOR_HANDLE* pDepthStencilDescriptor)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && FrameSurvey::OwnedRelease()) ForgetOwnedRRList(This);
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && !FrameSurvey::OwnedRelease() &&
        This != MenuOverlayDx::MenuCommandList())
    {
        std::vector<ID3D12Resource*> renderTargets;
        if (NumRenderTargetDescriptors > 0 && pRenderTargetDescriptors != nullptr)
        {
            renderTargets.reserve(NumRenderTargetDescriptors);
            for (UINT index = 0; index < NumRenderTargetDescriptors; ++index)
            {
                std::shared_ptr<HeapInfo> heap;
                SIZE_T handle = 0;
                if (RTsSingleHandleToDescriptorRange)
                {
                    heap = GetHeapByCpuHandleRTV(pRenderTargetDescriptors[0].ptr);
                    if (heap != nullptr)
                    {
                        handle = pRenderTargetDescriptors[0].ptr +
                                 static_cast<SIZE_T>(index) * heap->increment;
                    }
                }
                else
                {
                    handle = pRenderTargetDescriptors[index].ptr;
                    heap = GetHeapByCpuHandleRTV(handle);
                }

                ResourceInfo info {};
                if (heap != nullptr && heap->GetByCpuHandle(handle, info) && info.buffer != nullptr)
                    renderTargets.push_back(info.buffer);
            }
        }

        const bool born = RRInspectorBirthsEnabled();
        const auto receiver = born ? RRStrongReceiver(This) : NrdBridgeBirth::Token{};
        NrdBridgeBirth::CurrentGuard current(receiver,born);
        if (!born || (current.MatchesCurrent() && NrdBridgeBirth::Healthy()))
        {
            std::scoped_lock psoLock(gRRPsoMutex);
            auto& state = RRPsoListStateLocked(This,receiver);
            state.renderTargets = std::move(renderTargets);
            ++state.renderTargetGeneration;
        }
    }

    // Consistent early exit validation
    auto shouldTrack = State::Instance().activeFgInput == FGInput::Upscaler &&
                       !Config::Instance()->FGHudfixDisableOM.value_or_default() && NumRenderTargetDescriptors > 0 &&
                       pRenderTargetDescriptors != nullptr && IsHudFixActive() && !Hudfix_Dx12::SkipHudlessChecks() &&
                       This != MenuOverlayDx::MenuCommandList();

    if (!shouldTrack)
    {
        o_OMSetRenderTargets(This, NumRenderTargetDescriptors, pRenderTargetDescriptors,
                             RTsSingleHandleToDescriptorRange, pDepthStencilDescriptor);
        return;
    }

    LOG_DEBUG_ONLY("NumRenderTargetDescriptors: {}", NumRenderTargetDescriptors);

    auto fIndex = Hudfix_Dx12::ActivePresentFrame() % BUFFER_COUNT;

    // Process render targets
    for (size_t i = 0; i < NumRenderTargetDescriptors; i++)
    {
        std::shared_ptr<HeapInfo> heap;
        D3D12_CPU_DESCRIPTOR_HANDLE handle {};

        // Get the appropriate handle
        if (RTsSingleHandleToDescriptorRange)
        {
            heap = GetHeapByCpuHandleRTV(pRenderTargetDescriptors[0].ptr);
            if (heap == nullptr)
            {
                LOG_DEBUG_ONLY("No heap at index: {}", i);
                continue;
            }

            handle.ptr = pRenderTargetDescriptors[0].ptr + (i * heap->increment);
        }
        else
        {
            handle = pRenderTargetDescriptors[i];
            heap = GetHeapByCpuHandleRTV(handle.ptr);
            if (heap == nullptr)
            {
                LOG_DEBUG_ONLY("No heap at index: {}", i);
                continue;
            }
        }

        ResourceInfo capturedBuffer {};
        if (!heap->GetByCpuHandle(handle.ptr, capturedBuffer) || capturedBuffer.buffer == nullptr)
        {
            LOG_DEBUG_ONLY("No resource at index: {}, cpu: {:X}", i, handle.ptr);
            continue;
        }

        // Valid resource found, update state
        capturedBuffer.state = D3D12_RESOURCE_STATE_RENDER_TARGET;
        capturedBuffer.captureInfo = CaptureInfo::OMSetRTV;

        // Check for immediate capture
        bool capturedImmediately = false;
        if (Config::Instance()->FGImmediateCapture.value_or_default())
        {
            capturedImmediately = Hudfix_Dx12::CheckForHudless(This, &capturedBuffer, capturedBuffer.state);
            if (capturedImmediately)
                break; // Early exit if captured
        }

        // Track for later processing
        if (!capturedImmediately)
        {
            if (!_useShards)
            {
                std::lock_guard<std::mutex> lock(_hudlessTrackMutex);

                if (!fgPossibleHudless[fIndex].contains(This))
                {
                    ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> newMap;
                    newMap.reserve(32);
                    fgPossibleHudless[fIndex].insert_or_assign(This, std::move(newMap));
                }

                LOG_TRACK("Tracking Resource: {:X}, Desc: {:X}", (size_t) capturedBuffer.buffer, handle.ptr);
                fgPossibleHudless[fIndex][This].insert_or_assign(capturedBuffer.buffer, capturedBuffer);
            }
            else
            {
                size_t shardIdx = GetShardIndex(This);
                auto& shard = _hudlessShards[fIndex][shardIdx];

                LOCK_GUARD(shard.mutex);

                if (!shard.map.contains(This))
                {
                    ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> newMap;
                    newMap.reserve(32);
                    shard.map.insert_or_assign(This, std::move(newMap));
                }

                LOG_TRACK("CmdList: {:X}, Tracking Resource: {:X}, Desc: {:X}, Format: {}", (size_t) This,
                          (size_t) capturedBuffer.buffer, handle.ptr, (UINT) capturedBuffer.format);

                shard.map[This].insert_or_assign(capturedBuffer.buffer, capturedBuffer);
            }
        }
    }

    o_OMSetRenderTargets(This, NumRenderTargetDescriptors, pRenderTargetDescriptors, RTsSingleHandleToDescriptorRange,
                         pDepthStencilDescriptor);
}

#pragma endregion

#pragma region Compute paramter hooks

void ResTrack_Dx12::hkSetComputeRootDescriptorTable(ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
                                                    D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    // Consistent early exit - always call original function
    auto shouldTrack = !Config::Instance()->FGHudfixDisableSCR.value_or_default() && BaseDescriptor.ptr != 0 &&
                       IsHudFixActive() && !Hudfix_Dx12::SkipHudlessChecks() &&
                       This != MenuOverlayDx::MenuCommandList();

    if (!shouldTrack)
    {
        o_SetComputeRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
        return;
    }

    auto heap = GetHeapByGpuHandleCR(BaseDescriptor.ptr);
    if (heap == nullptr)
    {
        LOG_DEBUG_ONLY("No heap for handle: {:X}", BaseDescriptor.ptr);
        o_SetComputeRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
        return;
    }

    ResourceInfo capturedBuffer {};
    if (!heap->GetByGpuHandle(BaseDescriptor.ptr, capturedBuffer) || capturedBuffer.buffer == nullptr)
    {
        LOG_DEBUG_ONLY("No resource at RootParameterIndex: {}, CommandList: {:X}, gpuHandle: {:X}", RootParameterIndex,
                       (SIZE_T) This, BaseDescriptor.ptr);
        o_SetComputeRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
        return;
    }

    LOG_DEBUG_ONLY("CommandList: {:X}, Resource: {:X}", (size_t) This, (size_t) capturedBuffer.buffer);

    // Only proceed with tracking if we have a valid buffer
    if (capturedBuffer.type == UAV)
        capturedBuffer.state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    else
        capturedBuffer.state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;

    capturedBuffer.captureInfo = CaptureInfo::SetCR;

    // Track the resource
    bool capturedImmediately = false;
    if (Config::Instance()->FGImmediateCapture.value_or_default())
    {
        capturedImmediately = Hudfix_Dx12::CheckForHudless(This, &capturedBuffer, capturedBuffer.state);
    }

    if (!capturedImmediately)
    {
        auto fIndex = Hudfix_Dx12::ActivePresentFrame() % BUFFER_COUNT;

        if (!_useShards)
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);

            if (!fgPossibleHudless[fIndex].contains(This))
            {
                ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> newMap;
                newMap.reserve(32);
                fgPossibleHudless[fIndex].insert_or_assign(This, std::move(newMap));
            }

            LOG_TRACK("Tracking Resource: {:X}, Desc: {:X}", (size_t) capturedBuffer.buffer, BaseDescriptor.ptr);
            fgPossibleHudless[fIndex][This].insert_or_assign(capturedBuffer.buffer, capturedBuffer);
        }
        else
        {
            size_t shardIdx = GetShardIndex(This);
            auto& shard = _hudlessShards[fIndex][shardIdx];

            LOCK_GUARD(shard.mutex);

            if (!shard.map.contains(This))
            {
                ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> newMap;
                newMap.reserve(32);
                shard.map.insert_or_assign(This, std::move(newMap));
            }

            LOG_TRACK("CmdList: {:X}, Tracking Resource: {:X}, Desc: {:X}, Format: {}", (size_t) This,
                      (size_t) capturedBuffer.buffer, BaseDescriptor.ptr, (UINT) capturedBuffer.format);

            shard.map[This].insert_or_assign(capturedBuffer.buffer, capturedBuffer);
        }
    }

    o_SetComputeRootDescriptorTable(This, RootParameterIndex, BaseDescriptor);
}

#pragma endregion

#pragma region Shader finalizer hooks

// Capture if render target matches, wait for DrawIndexed
void ResTrack_Dx12::hkDrawInstanced(ID3D12GraphicsCommandList* This, UINT VertexCountPerInstance, UINT InstanceCount,
                                    UINT StartVertexLocation, UINT StartInstanceLocation)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && FrameSurvey::OwnedRelease()) ForgetOwnedRRList(This);
    o_DrawInstanced(This, VertexCountPerInstance, InstanceCount, StartVertexLocation, StartInstanceLocation);

    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && !FrameSurvey::OwnedRelease() &&
        This != MenuOverlayDx::MenuCommandList())
    {
        std::scoped_lock psoLock(gRRPsoMutex);
        RecordRRGraphicsOutputs(This);
    }

    if (State::Instance().activeFgInput != FGInput::Upscaler || !IsHudFixActive())
    {
        LOG_TRACK("Skipping {:X}", (size_t) This);
        return;
    }

    LOG_TRACK("CmdList: {:X}", (size_t) This);

    auto fIndex = Hudfix_Dx12::ActivePresentFrame() % BUFFER_COUNT;

    if (!_useShards)
    {
        if (This == MenuOverlayDx::MenuCommandList())
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);
            fgPossibleHudless[fIndex].erase(This);
            return;
        }

        ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> val0;
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);

            if (fgPossibleHudless[fIndex].size() == 0 || !fgPossibleHudless[fIndex].contains(This))
                return;

            val0 = std::move(fgPossibleHudless[fIndex][This]);
            fgPossibleHudless[fIndex].erase(This);
        }

        do
        {
            // if this command list does not have entries skip
            if (val0.size() == 0)
                break;

            if (Config::Instance()->FGHudfixDisableDI.value_or_default())
                break;

            std::lock_guard<std::mutex> lock(_drawMutex);
            for (auto& [key, val] : val0)
            {
                val.captureInfo |= CaptureInfo::DrawInstanced;

                if (Hudfix_Dx12::CheckForHudless(This, &val, val.state))
                    break;
            }

        } while (false);
    }
    else
    {
        size_t shardIdx = GetShardIndex(This);
        auto& shard = _hudlessShards[fIndex][shardIdx];

        if (This == MenuOverlayDx::MenuCommandList() && shard.map.contains(This))
        {
            LOCK_GUARD(shard.mutex);

            shard.map.erase(This);
            return;
        }

        ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> val0;
        {

            LOCK_GUARD(shard.mutex);

            // if can't find output skip
            if (shard.map.size() == 0)
            {
                LOG_DEBUG_ONLY("Early exit");
                return;
            }

            if (!shard.map.contains(This))
                return;

            val0 = std::move(shard.map[This]);
            shard.map.erase(This);
        }

        do
        {
            // if this command list does not have entries skip
            if (val0.size() == 0)
                break;

            if (Config::Instance()->FGHudfixDisableDI.value_or_default())
                break;

            for (auto& [key, val] : val0)
            {
                std::lock_guard<std::mutex> lock(_drawMutex);

                val.captureInfo |= CaptureInfo::DrawInstanced;

                if (Hudfix_Dx12::CheckForHudless(This, &val, val.state))
                    break;
            }

        } while (false);
    }
}

void ResTrack_Dx12::hkDrawIndexedInstanced(ID3D12GraphicsCommandList* This, UINT IndexCountPerInstance,
                                           UINT InstanceCount, UINT StartIndexLocation, INT BaseVertexLocation,
                                           UINT StartInstanceLocation)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && FrameSurvey::OwnedRelease()) ForgetOwnedRRList(This);
    o_DrawIndexedInstanced(This, IndexCountPerInstance, InstanceCount, StartIndexLocation, BaseVertexLocation,
                           StartInstanceLocation);

    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && !FrameSurvey::OwnedRelease() &&
        This != MenuOverlayDx::MenuCommandList())
    {
        std::scoped_lock psoLock(gRRPsoMutex);
        RecordRRGraphicsOutputs(This);
    }

    if (State::Instance().activeFgInput != FGInput::Upscaler || !IsHudFixActive())
    {
        LOG_TRACK("Skipping CmdList: {:X}", (size_t) This);
        return;
    }

    LOG_TRACK("CmdList: {:X}", (size_t) This);

    auto fIndex = Hudfix_Dx12::ActivePresentFrame() % BUFFER_COUNT;

    if (!_useShards)
    {
        if (This == MenuOverlayDx::MenuCommandList())
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);
            fgPossibleHudless[fIndex].erase(This);
            return;
        }

        ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> val0;
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);

            if (fgPossibleHudless[fIndex].size() == 0 || !fgPossibleHudless[fIndex].contains(This))
                return;

            val0 = std::move(fgPossibleHudless[fIndex][This]);
            fgPossibleHudless[fIndex].erase(This);
        }

        do
        {
            // if this command list does not have entries skip
            if (val0.size() == 0)
                break;

            if (Config::Instance()->FGHudfixDisableDII.value_or_default())
                break;

            std::lock_guard<std::mutex> lock(_drawMutex);
            for (auto& [key, val] : val0)
            {
                val.captureInfo |= CaptureInfo::DrawIndexedInstanced;

                if (Hudfix_Dx12::CheckForHudless(This, &val, val.state))
                    break;
            }

        } while (false);
    }
    else
    {
        size_t shardIdx = GetShardIndex(This);
        auto& shard = _hudlessShards[fIndex][shardIdx];

        if (This == MenuOverlayDx::MenuCommandList() && shard.map.contains(This))
        {
            LOCK_GUARD(shard.mutex);

            shard.map.erase(This);
            return;
        }

        ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> val0;
        {
            LOCK_GUARD(shard.mutex);

            // if can't find output skip
            if (shard.map.size() == 0)
            {
                LOG_DEBUG_ONLY("Early exit");
                return;
            }

            if (!shard.map.contains(This))
                return;

            val0 = std::move(shard.map[This]);
            shard.map.erase(This);
        }

        do
        {
            // if this command list does not have entries skip
            if (val0.size() == 0)
                break;

            if (Config::Instance()->FGHudfixDisableDII.value_or_default())
                break;

            for (auto& [key, val] : val0)
            {
                // LOG_DEBUG("Waiting _drawMutex {:X}", (size_t)val.buffer);
                std::lock_guard<std::mutex> lock(_drawMutex);

                val.captureInfo |= CaptureInfo::DrawIndexedInstanced;

                if (Hudfix_Dx12::CheckForHudless(This, &val, val.state))
                    break;
            }

        } while (false);
    }
}

void ResTrack_Dx12::hkExecuteBundle(ID3D12GraphicsCommandList* This, ID3D12GraphicsCommandList* pCommandList)
{
    LOG_FUNC();

    IFGFeature_Dx12* fg = State::Instance().currentFG;
    auto index = fg != nullptr ? fg->GetIndex() : 0;

    {
        std::lock_guard<std::mutex> lock(_resourceCommandListMutex);

        if (fg != nullptr && fg->IsActive() && (_resourceCommandList[index].size() > 0 || !_resCmdList[index].empty()))
        {
            if (_notFoundCmdLists.contains(pCommandList))
                LOG_WARN("Found last frames cmdList: {:X}", (size_t) This);

            auto& frameCmdList = _resourceCommandList[index];
            for (std::unordered_map<FG_ResourceType, ID3D12GraphicsCommandList*>::iterator it = frameCmdList.begin();
                 it != frameCmdList.end(); ++it)
            {
                if (it->second == pCommandList)
                    it->second = This;
            }

            for (std::unordered_map<FG_ResourceType, void*>::iterator it = _resCmdList[index].begin();
                 it != _resCmdList[index].end(); ++it)
            {
                if (it->second == pCommandList)
                    it->second = This;
            }
        }
    }

    o_ExecuteBundle(This, pCommandList);
}

HRESULT ResTrack_Dx12::hkClose(ID3D12GraphicsCommandList* This)
{
    const auto inspectorRecording = gRRResourceInspectorEnabled.load(std::memory_order_acquire) ? PrepareRRRecording(This) : RRPreparedRecording{};
    auto fg = State::Instance().currentFG;
    auto index = fg != nullptr ? fg->GetIndex() : 0;

    if (fg != nullptr && fg->IsActive() && !fg->IsPaused() && _resourceCommandList[index].size() > 0)
    {
        LOG_TRACK("CmdList: {:X}", (size_t) This);

        std::lock_guard<std::mutex> lock(_resourceCommandListMutex);

        if (_notFoundCmdLists.contains(This))
            LOG_WARN("Found last frames cmdList: {:X}", (size_t) This);

        std::vector<FG_ResourceType> found;

        for (const auto& pair : _resourceCommandList[index])
        {
            if (This == pair.second)
            {
                if (!fg->IsResourceReady(pair.first))
                {
                    LOG_DEBUG("{} cmdList: {:X}", (UINT) pair.first, (size_t) This);
                    _resCmdList[index][pair.first] = pair.second;
                    found.push_back(pair.first);
                }
            }
        }

        for (size_t i = 0; i < found.size(); i++)
        {
            _resourceCommandList[index].erase(found[i]);
        }
    }

    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed))
    {
        {
            std::scoped_lock markerLock(gRRMarkerMutex);
            gRRCommandListMarkers.erase(This);
        }
        {
            std::scoped_lock psoLock(gRRPsoMutex);
            EraseRRCommandListPsoStateLocked(This);
        }
    }

    const HRESULT result = o_Close(This);
    if (SUCCEEDED(result) && gRRResourceInspectorEnabled.load(std::memory_order_acquire)) RRRecordingSucceeded(inspectorRecording,This);
    return result;
}

void ResTrack_Dx12::hkDispatch(ID3D12GraphicsCommandList* This, UINT ThreadGroupCountX, UINT ThreadGroupCountY,
                               UINT ThreadGroupCountZ)
{
    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && FrameSurvey::OwnedRelease()) ForgetOwnedRRList(This);
    o_Dispatch(This, ThreadGroupCountX, ThreadGroupCountY, ThreadGroupCountZ);

    if (gRRResourceInspectorEnabled.load(std::memory_order_relaxed) && !FrameSurvey::OwnedRelease() &&
        This != MenuOverlayDx::MenuCommandList())
    {
        std::scoped_lock psoLock(gRRPsoMutex);
        RRCommandListPsoState& state = gRRCommandListPsoStates[This];
        if (state.currentPso != nullptr && RRPsoListAvailable(state,This))
        {
            const auto prepared = FindRRPsoMetadataLocked(state.currentPso);
            if (prepared)
            {
                RRPsoMetadata& metadata = *prepared;
                if (metadata.kind == RRPsoKind::Unknown || metadata.kind == RRPsoKind::Stream) metadata.kind = RRPsoKind::Compute;
                const auto previous = RRPsoPointers(state); state.lastComputePso = state.currentPso;
                UpdateRRPsoListReferencesLocked(This,previous,state); ++state.dispatchesSinceBarrier;
            }
        }
    }

    if (State::Instance().activeFgInput != FGInput::Upscaler || !IsHudFixActive())
    {
        LOG_TRACK("Skipping {:X}", (size_t) This);
        return;
    }

    LOG_TRACK("CmdList: {:X}", (size_t) This);

    auto fIndex = Hudfix_Dx12::ActivePresentFrame() % BUFFER_COUNT;

    if (!_useShards)
    {
        if (This == MenuOverlayDx::MenuCommandList())
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);
            fgPossibleHudless[fIndex].erase(This);
            return;
        }

        ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> val0;
        {
            std::lock_guard<std::mutex> lock(_hudlessTrackMutex);

            if (fgPossibleHudless[fIndex].size() == 0 || !fgPossibleHudless[fIndex].contains(This))
                return;

            val0 = std::move(fgPossibleHudless[fIndex][This]);
            fgPossibleHudless[fIndex].erase(This);
        }

        do
        {
            // if this command list does not have entries skip
            if (val0.size() == 0)
                break;

            if (Config::Instance()->FGHudfixDisableDispatch.value_or_default())
                break;

            std::lock_guard<std::mutex> lock(_drawMutex);
            for (auto& [key, val] : val0)
            {
                val.captureInfo |= CaptureInfo::Dispatch;

                if (Hudfix_Dx12::CheckForHudless(This, &val, val.state))
                    break;
            }
        } while (false);
    }
    else
    {
        size_t shardIdx = GetShardIndex(This);
        auto& shard = _hudlessShards[fIndex][shardIdx];

        if (This == MenuOverlayDx::MenuCommandList() && shard.map.contains(This))
        {
            LOCK_GUARD(shard.mutex);

            shard.map.erase(This);
            return;
        }

        ankerl::unordered_dense::map<ID3D12Resource*, ResourceInfo> val0;
        {

            LOCK_GUARD(shard.mutex);

            // if can't find output skip
            if (shard.map.size() == 0)
            {
                LOG_DEBUG_ONLY("Early exit");
                return;
            }

            if (!shard.map.contains(This))
                return;

            val0 = std::move(shard.map[This]);
            shard.map.erase(This);
        }

        do
        {
            // if this command list does not have entries skip
            if (val0.size() == 0)
                break;

            if (Config::Instance()->FGHudfixDisableDispatch.value_or_default())
                break;

            for (auto& [key, val] : val0)
            {
                // LOG_DEBUG("Waiting _drawMutex {:X}", (size_t)val.buffer);
                std::lock_guard<std::mutex> lock(_drawMutex);

                val.captureInfo |= CaptureInfo::Dispatch;
                if (Hudfix_Dx12::CheckForHudless(This, &val, val.state))
                {
                    break;
                }
            }
        } while (false);
    }
}

#pragma endregion

void ResTrack_Dx12::HookResource(ID3D12Device* InDevice)
{
    std::unique_lock installation(gReleaseHookInstallMutex);
    if (o_Release != nullptr)
        return;

    ID3D12Resource* tmp = nullptr;
    auto d = CD3DX12_RESOURCE_DESC::Buffer(4);
    auto heapProps = CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_UPLOAD);

    HRESULT hr = InDevice->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE, &d,
                                                   D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&tmp));

    if (hr == S_OK)
    {
        PVOID* pVTable = *(PVOID**) tmp;
        gResourceReleaseEntry = pVTable[2];
        gSharedResourceReleaseObserver = hkRelease;
        if (const auto original = FindBirthReleaseOriginal(gResourceReleaseEntry))
        {
            o_Release = reinterpret_cast<PFN_Release>(original);
            gResourceReleaseSharesBirth = true;
            tmp->Release();
            return;
        }
        if (gResourceReleaseEntry == gHeapReleaseEntry && o_HeapRelease && gHeapOwnsReleaseHook)
        {
            // A heap detour installed first. Its universal wrapper delegates to
            // hkRelease; both aliases call the existing original trampoline.
            o_Release = reinterpret_cast<PFN_Release>(o_HeapRelease);
            gResourceReleaseSharesHeap = true;
            gHeapReleaseSharesResource.store(true,std::memory_order_release);
            tmp->Release();
            return;
        }
        if (gResourceReleaseEntry == gCommandListReleaseEntry && o_CommandListRelease)
        {
            // Already detoured for command lists: use that observer for this shared entry.
            o_Release = reinterpret_cast<PFN_Release>(o_CommandListRelease);
            gResourceReleaseSharesCommandList = true;
            tmp->Release();
            return;
        }
        if (gResourceReleaseEntry == gPsoReleaseEntry && o_PsoRelease)
        {
            o_Release = reinterpret_cast<PFN_Release>(o_PsoRelease);
            gResourceReleaseSharesPso = true;
            tmp->Release();
            return;
        }
        o_Release = (PFN_Release) pVTable[2];

        if (o_Release != nullptr)
        {
            const auto beginResult = DetourTransactionBegin();
            const auto updateResult = beginResult == NO_ERROR ? DetourUpdateThread(GetCurrentThread()) : beginResult;
            const auto attachResult = updateResult == NO_ERROR ? DetourAttach(&(PVOID&) o_Release, hkRelease) : updateResult;
            const auto commitResult = attachResult == NO_ERROR ? DetourTransactionCommit() :
                (beginResult == NO_ERROR ? DetourTransactionAbort() : beginResult);
            const auto detourResult = attachResult == NO_ERROR ? commitResult : attachResult;

            if (detourResult != NO_ERROR)
            {
                LOG_ERROR("Failed to hook Resource Release: {:X}", detourResult);
                o_Release = nullptr;
                gResourceReleaseEntry = nullptr;
                gSharedResourceReleaseObserver = nullptr;
                tmp->Release();
                if (gNrdBridgeWrappers)
                {
                    installation.unlock();
                    FrameSurvey::MetadataHookFailed("Native resource Release observer installation failed");
                }
            }
            else
            {
                o_Release(tmp); // drop temp
            }
        }
        else
        {
            tmp->Release();
        }
    }
}

void ResTrack_Dx12::HookCommandList(ID3D12Device* InDevice)
{

    if (o_OMSetRenderTargets != nullptr)
        return;

    ID3D12GraphicsCommandList* commandList = nullptr;
    ID3D12CommandAllocator* commandAllocator = nullptr;

    if (InDevice->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&commandAllocator)) == S_OK)
    {
        if (InDevice->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, commandAllocator, nullptr,
                                        IID_PPV_ARGS(&commandList)) == S_OK)
        {
            ID3D12GraphicsCommandList* realCL = nullptr;
            if (!CheckForRealObject(__FUNCTION__, commandList, (IUnknown**) &realCL))
                realCL = commandList;

            // Get the vtable pointer
            PVOID* pVTable = *(PVOID**) realCL;

            // hudless shader
            o_OMSetRenderTargets = (PFN_OMSetRenderTargets) pVTable[46];
            o_SetGraphicsRootDescriptorTable = (PFN_SetGraphicsRootDescriptorTable) pVTable[32];

            o_DrawInstanced = (PFN_DrawInstanced) pVTable[12];
            o_DrawIndexedInstanced = (PFN_DrawIndexedInstanced) pVTable[13];
            o_Dispatch = (PFN_Dispatch) pVTable[14];
            o_Close = (PFN_Close) pVTable[9];
            gRRRecordingCloseEntry = pVTable[9];
            gRRRecordingBarrierEntry = pVTable[26];
            const bool resetAlreadyHooked = o_Reset != nullptr;
            const bool releaseAlreadyHooked = o_CommandListRelease != nullptr;
            if (!resetAlreadyHooked) o_Reset = (PFN_Reset) pVTable[10];
            const bool resetEntryMatches = !resetAlreadyHooked || gComputeResetEntry == pVTable[10];
            if (!resetAlreadyHooked) gComputeResetEntry = pVTable[10];
            const PVOID releaseEntry = pVTable[2];
            const bool sharedRelease = releaseEntry == gResourceReleaseEntry ||
                releaseEntry == gPsoReleaseEntry || FindBirthReleaseOriginal(releaseEntry);
            if (!sharedRelease && !releaseAlreadyHooked)
            {
                gCommandListReleaseEntry = releaseEntry;
                o_CommandListRelease = reinterpret_cast<PFN_CommandListRelease>(releaseEntry);
            }
            if (gNrdBridgeWrappers)
            {
                o_ClearState = (PFN_ClearState) pVTable[11];
                o_SetPredication = (PFN_SetPredication) pVTable[55];
            }
            o_SetPipelineState = (PFN_SetPipelineState) pVTable[25];
            o_ResourceBarrier = (PFN_ResourceBarrier) pVTable[26];
            o_SetMarker = (PFN_SetMarker) pVTable[56];
            o_BeginEvent = (PFN_BeginEvent) pVTable[57];
            o_EndEvent = (PFN_EndEvent) pVTable[58];

            // hudless compute
            o_SetComputeRootDescriptorTable = (PFN_SetComputeRootDescriptorTable) pVTable[31];

            o_ExecuteBundle = (PFN_ExecuteBundle) pVTable[27];

            if (o_OMSetRenderTargets != nullptr)
            {
                DetourTransactionBegin();
                DetourUpdateThread(GetCurrentThread());

                if (o_OMSetRenderTargets != nullptr)
                    DetourAttach(&(PVOID&) o_OMSetRenderTargets, gSurveyWrappers ? hkSurveyOMSetRenderTargets : hkOMSetRenderTargets);

                if (o_DrawIndexedInstanced != nullptr)
                    DetourAttach(&(PVOID&) o_DrawIndexedInstanced, gSurveyWrappers ? hkSurveyDrawIndexedInstanced : hkDrawIndexedInstanced);

                if (o_DrawInstanced != nullptr)
                    DetourAttach(&(PVOID&) o_DrawInstanced, gSurveyWrappers ? hkSurveyDrawInstanced : hkDrawInstanced);

                if (o_Dispatch != nullptr)
                    DetourAttach(&(PVOID&) o_Dispatch, gSurveyWrappers ? hkSurveyDispatch : hkDispatch);

                // Root descriptor tracking is only needed by the HUD fix.
                if (State::Instance().activeFgInput == FGInput::Upscaler || gSurveyWrappers)
                {
                    if (o_SetGraphicsRootDescriptorTable != nullptr)
                        DetourAttach(&(PVOID&) o_SetGraphicsRootDescriptorTable, gSurveyWrappers ? hkSurveySetGraphicsRootDescriptorTable : hkSetGraphicsRootDescriptorTable);

                    if (o_SetComputeRootDescriptorTable != nullptr)
                        DetourAttach(&(PVOID&) o_SetComputeRootDescriptorTable, gSurveyWrappers ? hkSurveySetComputeRootDescriptorTable : hkSetComputeRootDescriptorTable);
                }

                const auto closeAttachResult = o_Close ?
                    DetourAttach(&(PVOID&) o_Close, gSurveyWrappers ? hkSurveyClose : hkClose) : ERROR_INVALID_FUNCTION;

                const auto resetAttachResult = resetAlreadyHooked ? NO_ERROR :
                    (o_Reset ? DetourAttach(&(PVOID&) o_Reset, gSurveyWrappers ? hkSurveyReset : hkReset) : ERROR_INVALID_FUNCTION);
                const auto clearStateAttachResult = !gNrdBridgeWrappers ? NO_ERROR : (o_ClearState ?
                    DetourAttach(&(PVOID&) o_ClearState,hkBridgeClearState) : ERROR_INVALID_FUNCTION);
                const auto predicationAttachResult = !gNrdBridgeWrappers ? NO_ERROR : (o_SetPredication ?
                    DetourAttach(&(PVOID&) o_SetPredication,hkBridgeSetPredication) : ERROR_INVALID_FUNCTION);
                const auto releaseAttachResult = releaseAlreadyHooked ? NO_ERROR : (o_CommandListRelease ?
                    DetourAttach(&(PVOID&) o_CommandListRelease, hkCommandListRelease) :
                    (sharedRelease ? NO_ERROR : ERROR_INVALID_FUNCTION));

                if (o_SetPipelineState != nullptr)
                    DetourAttach(&(PVOID&) o_SetPipelineState, gSurveyWrappers ? hkSurveySetPipelineState : hkSetPipelineState);

                const auto barrierAttachResult = o_ResourceBarrier ?
                    DetourAttach(&(PVOID&) o_ResourceBarrier, gSurveyWrappers ? hkSurveyResourceBarrier : hkResourceBarrier) : ERROR_INVALID_FUNCTION;

                if (o_SetMarker != nullptr)
                    DetourAttach(&(PVOID&) o_SetMarker, gSurveyWrappers ? hkSurveySetMarker : hkSetMarker);

                if (o_BeginEvent != nullptr)
                    DetourAttach(&(PVOID&) o_BeginEvent, gSurveyWrappers ? hkSurveyBeginEvent : hkBeginEvent);

                if (o_EndEvent != nullptr)
                    DetourAttach(&(PVOID&) o_EndEvent, gSurveyWrappers ? hkSurveyEndEvent : hkEndEvent);

                if (o_ExecuteBundle != nullptr)
                    DetourAttach(&(PVOID&) o_ExecuteBundle, gSurveyWrappers ? hkSurveyExecuteBundle : hkExecuteBundle);

                const auto criticalAttachResult = resetAttachResult != NO_ERROR ? resetAttachResult :
                    releaseAttachResult != NO_ERROR ? releaseAttachResult : closeAttachResult != NO_ERROR ? closeAttachResult :
                    barrierAttachResult != NO_ERROR ? barrierAttachResult : clearStateAttachResult != NO_ERROR ? clearStateAttachResult : predicationAttachResult;
                const auto commitResult = criticalAttachResult == NO_ERROR ? DetourTransactionCommit() : DetourTransactionAbort();
                const auto detourResult = criticalAttachResult == NO_ERROR ? commitResult : criticalAttachResult;
                if (detourResult != NO_ERROR)
                {
                    LOG_ERROR("Failed to hook CommandList methods: {:X}", detourResult);
                    o_OMSetRenderTargets = nullptr;
                    o_SetGraphicsRootDescriptorTable = nullptr;
                    o_DrawInstanced = nullptr;
                    o_DrawIndexedInstanced = nullptr;
                    o_Dispatch = nullptr;
                    o_Close = nullptr; gRRRecordingCloseEntry = gRRRecordingBarrierEntry = nullptr;
                    o_SetComputeRootDescriptorTable = nullptr;
                    o_ExecuteBundle = nullptr; o_ClearState = nullptr; o_SetPredication = nullptr;
                    if (!resetAlreadyHooked) { o_Reset = nullptr; gComputeResetEntry = nullptr; }
                    if (!releaseAlreadyHooked) { o_CommandListRelease = nullptr; gCommandListReleaseEntry = nullptr; }
                }
                gComputeListHooksAvailable.store(detourResult == NO_ERROR && resetEntryMatches && o_Reset &&
                    (sharedRelease || o_CommandListRelease));
                PublishComputeHookAvailability();
            }

            if (gSurveyWrappers)
            {
                const auto& passHashes = Config::Instance()->FfxDenoiserFrameSurveyPassHashes;
                FrameSurvey::SetPassHashes(passHashes.has_value() ? wstring_to_string(passHashes.value()) : std::string());
                FrameSurvey::Install(InDevice,realCL,Config::Instance()->FfxDenoiserFrameSurvey.value_or_default());
            }
            commandList->Close();
            commandList->Release();
        }

        commandAllocator->Reset();
        commandAllocator->Release();
    }
}

void ResTrack_Dx12::HookToQueue(ID3D12Device* InDevice)
{
    if (o_ExecuteCommandLists != nullptr)
        return;

    ID3D12CommandQueue* queue = nullptr;
    D3D12_COMMAND_QUEUE_DESC queueDesc = {};
    queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    queueDesc.Flags = D3D12_COMMAND_QUEUE_FLAG_NONE;
    queueDesc.NodeMask = 0;
    queueDesc.Priority = D3D12_COMMAND_QUEUE_PRIORITY_NORMAL;

    auto hr = InDevice->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&queue));

    if (hr == S_OK)
    {
        ID3D12CommandQueue* realQueue = nullptr;
        if (!CheckForRealObject(__FUNCTION__, queue, (IUnknown**) &realQueue))
            realQueue = queue;

        // Get the vtable pointer
        PVOID* pVTable = *(PVOID**) realQueue;

        o_ExecuteCommandLists = (PFN_ExecuteCommandLists) pVTable[10];
        gComputeExecuteEntry = pVTable[10];
        IUnknown* actualDevice = InDevice;
        IUnknown* unwrappedDevice = nullptr;
        if (CheckForRealObject(__FUNCTION__, actualDevice, &unwrappedDevice)) actualDevice = unwrappedDevice;
        const bool deviceIdentityAvailable = SUCCEEDED(actualDevice->QueryInterface(IID_PPV_ARGS(&gComputeQueueDeviceIdentity)));

        // ComputeState may be submitted on DIRECT or COMPUTE queues. Publish eligibility
        // only when both implementations use the entry that this detour observes.
        Microsoft::WRL::ComPtr<ID3D12CommandQueue> computeQueue;
        queueDesc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
        bool computeEntryMatches = false;
        if (SUCCEEDED(InDevice->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&computeQueue))))
        {
            ID3D12CommandQueue* actualCompute = computeQueue.Get();
            IUnknown* unwrapped = nullptr;
            if (CheckForRealObject(__FUNCTION__, actualCompute, &unwrapped))
                actualCompute = static_cast<ID3D12CommandQueue*>(unwrapped);
            computeEntryMatches = (*reinterpret_cast<PVOID**>(actualCompute))[10] == gComputeExecuteEntry;
        }

        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        const auto attachResult = o_ExecuteCommandLists ?
            DetourAttach(&(PVOID&) o_ExecuteCommandLists, gSurveyWrappers ? hkSurveyExecuteCommandLists : hkExecuteCommandLists) : ERROR_INVALID_FUNCTION;
        const auto commitResult = attachResult == NO_ERROR ? DetourTransactionCommit() : DetourTransactionAbort();
        const auto detourResult = attachResult == NO_ERROR ? commitResult : attachResult;
        if (detourResult != NO_ERROR)
        {
            LOG_ERROR("Failed to hook CommandList methods: {:X}", detourResult);
            o_ExecuteCommandLists = nullptr;
            gComputeExecuteEntry = nullptr;
        }
        gComputeQueueHookAvailable.store(detourResult == NO_ERROR && o_ExecuteCommandLists &&
            computeEntryMatches && deviceIdentityAvailable);
        PublishComputeHookAvailability();

        queue->Release();
    }
}

bool ResTrack_Dx12::RefreshComputeHookDevice(ID3D12Device* selectedNativeDevice, const char** reason) noexcept
{
    if (reason) *reason = nullptr;
    const auto reject = [&](const char* message) { if (reason) *reason = message; return false; };
    if (!selectedNativeDevice || State::Instance().isShuttingDown)
        return reject("Selected native device is unavailable");
    try
    {
        FrameSurvey::ScopedInternal internal;
        std::lock_guard initialization(gComputeHookInitMutex);
        HookResource(selectedNativeDevice);
        HookCommandList(selectedNativeDevice);
        HookToQueue(selectedNativeDevice);
        {
            auto& registry = RecordedComputeLease::GetRegistry();
            std::lock_guard lock(registry.mutex);
            if (registry.completionFailed)
                return reject("Recorded-compute completion is uncertain; restart the title before reusing bridge work");
        }
        if (!gComputeListHooksAvailable.load() || !gComputeQueueHookAvailable.load() ||
            !gResourceReleaseEntry || !gComputeResetEntry || !gComputeExecuteEntry)
            return reject("Native recording or submission hooks are unavailable");
        Microsoft::WRL::ComPtr<IUnknown> identity;
        if (FAILED(selectedNativeDevice->QueryInterface(IID_PPV_ARGS(&identity))))
            return reject("Selected native device canonical identity is unavailable");
        if (identity.Get() == gComputeQueueDeviceIdentity.Get()) return true;

        // Rebind only the selected title device, after verifying its implementations
        // are already observed. Never detach old hooks while their leases can run.
        Microsoft::WRL::ComPtr<ID3D12CommandQueue> directQueue, computeQueue;
        D3D12_COMMAND_QUEUE_DESC queueDesc {};
        queueDesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(selectedNativeDevice->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&directQueue))))
            return reject("Cannot create a native direct-queue eligibility probe");
        queueDesc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
        if (FAILED(selectedNativeDevice->CreateCommandQueue(&queueDesc, IID_PPV_ARGS(&computeQueue))))
            return reject("Cannot create a native compute-queue eligibility probe");
        if ((*reinterpret_cast<PVOID**>(directQueue.Get()))[10] != gComputeExecuteEntry ||
            (*reinterpret_cast<PVOID**>(computeQueue.Get()))[10] != gComputeExecuteEntry)
            return reject("Selected device queue implementation is not observed by the existing native hook");
        for (const auto type : {D3D12_COMMAND_LIST_TYPE_DIRECT, D3D12_COMMAND_LIST_TYPE_COMPUTE})
        {
            Microsoft::WRL::ComPtr<ID3D12CommandAllocator> allocator;
            Microsoft::WRL::ComPtr<ID3D12GraphicsCommandList> list;
            if (FAILED(selectedNativeDevice->CreateCommandAllocator(type, IID_PPV_ARGS(&allocator))) ||
                FAILED(selectedNativeDevice->CreateCommandList(0, type, allocator.Get(), nullptr, IID_PPV_ARGS(&list))))
                return reject("Cannot create a native command-list eligibility probe");
            const auto table = *reinterpret_cast<PVOID**>(list.Get());
            if (table[10] != gComputeResetEntry ||
                (table[2] != gCommandListReleaseEntry && table[2] != gResourceReleaseEntry && table[2] != gPsoReleaseEntry))
                return reject("Selected device Reset or Release implementation is not observed by existing native hooks");
        }
        Microsoft::WRL::ComPtr<ID3D12Resource> resource;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = 16; desc.Height = desc.DepthOrArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(selectedNativeDevice->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&resource))))
            return reject("Cannot create a native resource Release eligibility probe");
        if ((*reinterpret_cast<PVOID**>(resource.Get()))[2] != gResourceReleaseEntry)
            return reject("Selected device resource Release implementation is not observed by the existing native hook");
        gComputeQueueDeviceIdentity = std::move(identity);
        return true;
    }
    catch (...) { return reject("Native compute eligibility probe raised an exception"); }
}

bool ResTrack_Dx12::RetainComputeDispatch(ID3D12Device* device, ID3D12GraphicsCommandList* list,
                                         const std::shared_ptr<void>& lease,
                                         std::function<void(ID3D12CommandQueue*)> beforeSubmit,
                                         RecordedComputeLease::SubmissionCallbacks callbacks)
{
    if (!device || !list || !lease || State::Instance().isShuttingDown) return false;
    IUnknown* actualDevice = device;
    IUnknown* unwrappedDevice = nullptr;
    if (CheckForRealObject(__FUNCTION__, actualDevice, &unwrappedDevice)) actualDevice = unwrappedDevice;
    Microsoft::WRL::ComPtr<IUnknown> deviceIdentity;
    if (FAILED(actualDevice->QueryInterface(IID_PPV_ARGS(&deviceIdentity)))) return false;
    {
        std::lock_guard lock(gComputeHookInitMutex);
        HookResource(device); // shared Release entry must be known before attaching a list observer
        HookCommandList(device);
        HookToQueue(device);
        if (deviceIdentity.Get() != gComputeQueueDeviceIdentity.Get()) return false;
    }
    if (!RecordedComputeLease::Available() || (gNrdBridgeWrappers && !gResourceReleaseEntry)) return false;
    ID3D12GraphicsCommandList* actual = list;
    IUnknown* unwrapped = nullptr;
    if (CheckForRealObject(__FUNCTION__, list, &unwrapped))
        actual = static_cast<ID3D12GraphicsCommandList*>(unwrapped);
    if (actual->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT &&
        actual->GetType() != D3D12_COMMAND_LIST_TYPE_COMPUTE) return false; // bundles require parent propagation
    Microsoft::WRL::ComPtr<ID3D12Device> listDevice;
    if (FAILED(actual->GetDevice(IID_PPV_ARGS(&listDevice)))) return false;
    IUnknown* actualListDevice = listDevice.Get();
    IUnknown* unwrappedListDevice = nullptr;
    if (CheckForRealObject(__FUNCTION__, actualListDevice, &unwrappedListDevice)) actualListDevice = unwrappedListDevice;
    Microsoft::WRL::ComPtr<IUnknown> listDeviceIdentity;
    if (FAILED(actualListDevice->QueryInterface(IID_PPV_ARGS(&listDeviceIdentity))) ||
        listDeviceIdentity.Get() != deviceIdentity.Get()) return false;
    PVOID* vtable = *reinterpret_cast<PVOID**>(actual);
    if (vtable[10] != gComputeResetEntry ||
        (vtable[2] != gCommandListReleaseEntry && vtable[2] != gResourceReleaseEntry &&
         vtable[2] != gPsoReleaseEntry && !FindBirthReleaseOriginal(vtable[2]))) return false;
    Microsoft::WRL::ComPtr<IUnknown> identity;
    if (FAILED(actual->QueryInterface(IID_PPV_ARGS(&identity)))) return false;
    if (NrdBridgeNativeBirth::Ready() && gNrdBridgeWrappers && NrdBridgeBirth::Capture(actual))
    {
        // This explicit title list already passed device/type/hook eligibility.
        // Keep helper work internal, but admit its native recording identity even
        // when the caller is inside ScopedInternal. Never broaden owned creation.
        FrameSurvey::ScopedRecording titleRecording;
        if (!ObserveBridgeObjectRelease(actual) || !ObserveBridgeObjectRelease(identity.Get())) return false;
        const auto nativeBirth = NrdBridgeNativeBirth::Receiver(actual);
        // Query the canonical ID3D12Object while QI owns its temporary reference.
        // IUnknown itself has no private-data API. The native object's GUID is
        // explicit alias evidence; forwarding proxies keep their own identity.
        if (!nativeBirth) return false;
        const auto link = [&nativeBirth](void* alias) {
            NrdBridgeNativeBirth::RetirementScope retirement;
            return retirement.Valid() && bool(NrdBridgeBirth::LinkAlias(nativeBirth->InstanceStamp(),alias));
        };
        if (!link(identity.Get()) || !link(static_cast<ID3D12CommandList*>(actual))) return false;
        // A failed Track may leave a harmless true marker. Marking before Track
        // prevents any Release between publication and the capability flag.
        NrdBridgeBirth::MarkRecordingMayExist(nativeBirth);
    }
    return RecordedComputeLease::Track(identity.Get(),
        { list, actual, static_cast<ID3D12CommandList*>(actual), identity.Get() }, lease, std::move(beforeSubmit), std::move(callbacks));
}

void ResTrack_Dx12::HookDevice(ID3D12Device* device)
{
    if (device == nullptr || FrameSurvey::Internal()) return;
    if (o_CreateDescriptorHeap == nullptr || NrdBridge::StartupEnabled())
    {
        gNrdBridgeWrappers = NrdBridge::StartupEnabled();
        gSurveyWrappers = Config::Instance()->FfxDenoiserFrameSurvey.value_or_default() || gNrdBridgeWrappers;
    }
    Microsoft::WRL::ComPtr<ID3D12Device> native;
    if (NrdBridge::StartupEnabled())
    {
        native = NrdBridgeDevice::Native(device);
        if (!native || !NrdBridgeDevice::Selected(native.Get(), State::Instance().currentD3D12Device)) return;
        device = native.Get();
        const char* reason = nullptr;
        if (o_CreateDescriptorHeap != nullptr && !RefreshComputeHookDevice(device, &reason))
        {
            if (!reason) reason = "Selected title device could not be bound to installed compute hooks; restart required";
            NrdBridge::ReportUnavailable(reason);
            LOG_ERROR("[NRD_BRIDGE] {}", reason);
            return;
        }
        if (!NrdBridge::Initialize(device)) return;
    }
    if (o_CreateDescriptorHeap != nullptr ||
        (State::Instance().activeFgInput == FGInput::NvngxFG && !NrdBridge::StartupEnabled()))
        return;

    if (gSurveyWrappers) FrameSurvey::BeginCreationTracking(Config::Instance()->FfxDenoiserFrameSurvey.value_or_default());
    bool initializeTracking = false;
    {
        std::unique_lock lock(_heapRegistryMutex);
        if (fgHeaps.capacity() < 65536)
        {
            fgHeaps.reserve(65536);
            initializeTracking = true;
        }
        if (gFreeHeapSlots.capacity() < fgHeaps.capacity()) gFreeHeapSlots.reserve(fgHeaps.capacity());
    }

    if (initializeTracking)
    {
        _useShards = Config::Instance()->FGUseShards.value_or_default();
        std::scoped_lock lock(_trackedResourcesMutex);
        _trackedResources.reserve(1024);
    }

    LOG_FUNC();

    ID3D12Device* realDevice = nullptr;
    if (!CheckForRealObject(__FUNCTION__, device, (IUnknown**) &realDevice))
        realDevice = device;

    // Get the vtable pointer
    PVOID* pVTable = *(PVOID**) realDevice;

    // Hudfix
    o_CreateDescriptorHeap = (PFN_CreateDescriptorHeap) pVTable[14];
    o_CreateGraphicsPipelineState = (PFN_CreateGraphicsPipelineState) pVTable[10];
    o_CreateComputePipelineState = (PFN_CreateComputePipelineState) pVTable[11];
    o_CreateShaderResourceView = (PFN_CreateShaderResourceView) pVTable[18];
    o_CreateUnorderedAccessView = (PFN_CreateUnorderedAccessView) pVTable[19];
    o_CreateRenderTargetView = (PFN_CreateRenderTargetView) pVTable[20];
    o_CreateSampler = (PFN_CreateSampler) pVTable[22];
    o_CopyDescriptors = (PFN_CopyDescriptors) pVTable[23];
    o_CopyDescriptorsSimple = (PFN_CopyDescriptorsSimple) pVTable[24];

    ID3D12Device2* device2 = nullptr;
    if (SUCCEEDED(realDevice->QueryInterface(IID_PPV_ARGS(&device2))) && device2 != nullptr)
    {
        PVOID* device2VTable = *(PVOID**) device2;
        o_CreatePipelineState = (PFN_CreatePipelineState) device2VTable[47];
    }

    // o_CreateDepthStencilView = (PFN_CreateDepthStencilView) pVTable[21];
    if (gNrdBridgeWrappers) o_CreateConstantBufferView = (PFN_CreateConstantBufferView) pVTable[17];

    // Apply the detour

    if (o_CreateDescriptorHeap != nullptr)
    {
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        if (o_CreateDescriptorHeap != nullptr)
            DetourAttach(&(PVOID&) o_CreateDescriptorHeap, gSurveyWrappers ? hkSurveyCreateDescriptorHeap : hkCreateDescriptorHeap);

        if (o_CreateGraphicsPipelineState != nullptr)
            DetourAttach(&(PVOID&) o_CreateGraphicsPipelineState, gSurveyWrappers ? hkSurveyCreateGraphicsPipelineState : hkCreateGraphicsPipelineState);

        if (o_CreateComputePipelineState != nullptr)
            DetourAttach(&(PVOID&) o_CreateComputePipelineState, gSurveyWrappers ? hkSurveyCreateComputePipelineState : hkCreateComputePipelineState);

        if (o_CreatePipelineState != nullptr)
            DetourAttach(&(PVOID&) o_CreatePipelineState, gSurveyWrappers ? hkSurveyCreatePipelineState : hkCreatePipelineState);

        if (o_CreateRenderTargetView != nullptr)
            DetourAttach(&(PVOID&) o_CreateRenderTargetView, gSurveyWrappers ? hkSurveyCreateRenderTargetView : hkCreateRenderTargetView);

        if (gNrdBridgeWrappers && o_CreateConstantBufferView != nullptr)
            DetourAttach(&(PVOID&) o_CreateConstantBufferView, hkSurveyCreateConstantBufferView);

        if (o_CreateShaderResourceView != nullptr)
            DetourAttach(&(PVOID&) o_CreateShaderResourceView, gSurveyWrappers ? hkSurveyCreateShaderResourceView : hkCreateShaderResourceView);

        if (o_CreateUnorderedAccessView != nullptr)
            DetourAttach(&(PVOID&) o_CreateUnorderedAccessView, gSurveyWrappers ? hkSurveyCreateUnorderedAccessView : hkCreateUnorderedAccessView);

        if (o_CopyDescriptors != nullptr)
            DetourAttach(&(PVOID&) o_CopyDescriptors, gSurveyWrappers ? hkSurveyCopyDescriptors : hkCopyDescriptors);

        if (o_CopyDescriptorsSimple != nullptr)
            DetourAttach(&(PVOID&) o_CopyDescriptorsSimple, gSurveyWrappers ? hkSurveyCopyDescriptorsSimple : hkCopyDescriptorsSimple);

        auto detourResult = DetourTransactionCommit();
        if (detourResult != NO_ERROR)
        {
            LOG_ERROR("Failed to hook Descriptor methods: {:X}", detourResult);
            o_CreateDescriptorHeap = nullptr;
            o_CreateRenderTargetView = nullptr;
            o_CreateConstantBufferView = nullptr;
            o_CreateShaderResourceView = nullptr;
            o_CreateUnorderedAccessView = nullptr;
            o_CopyDescriptors = nullptr;
            o_CopyDescriptorsSimple = nullptr;
        }
    }

    if (device2 != nullptr)
        device2->Release();

    {
        std::lock_guard lock(gComputeHookInitMutex);
        HookResource(realDevice);
        HookToQueue(realDevice);
        HookCommandList(realDevice);
    }
}

void ResTrack_Dx12::ReleaseDeviceHooks()
{
    if (gNrdBridgeWrappers) NrdBridge::Shutdown();
    if (gSurveyWrappers) FrameSurvey::Shutdown();
    gComputeListHooksAvailable.store(false);
    gComputeQueueHookAvailable.store(false);
    PublishComputeHookAvailability();
    LOG_DEBUG("");

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_CreateDescriptorHeap != nullptr)
        DetourDetach(&(PVOID&) o_CreateDescriptorHeap, gSurveyWrappers ? hkSurveyCreateDescriptorHeap : hkCreateDescriptorHeap);

    if (o_CreateGraphicsPipelineState != nullptr)
        DetourDetach(&(PVOID&) o_CreateGraphicsPipelineState, gSurveyWrappers ? hkSurveyCreateGraphicsPipelineState : hkCreateGraphicsPipelineState);

    if (o_CreateComputePipelineState != nullptr)
        DetourDetach(&(PVOID&) o_CreateComputePipelineState, gSurveyWrappers ? hkSurveyCreateComputePipelineState : hkCreateComputePipelineState);

    if (o_CreatePipelineState != nullptr)
        DetourDetach(&(PVOID&) o_CreatePipelineState, gSurveyWrappers ? hkSurveyCreatePipelineState : hkCreatePipelineState);

    if (o_CreateRenderTargetView != nullptr)
        DetourDetach(&(PVOID&) o_CreateRenderTargetView, gSurveyWrappers ? hkSurveyCreateRenderTargetView : hkCreateRenderTargetView);

    if (o_CreateConstantBufferView != nullptr)
        DetourDetach(&(PVOID&) o_CreateConstantBufferView, hkSurveyCreateConstantBufferView);

    if (o_CreateShaderResourceView != nullptr)
        DetourDetach(&(PVOID&) o_CreateShaderResourceView, gSurveyWrappers ? hkSurveyCreateShaderResourceView : hkCreateShaderResourceView);

    if (o_CreateUnorderedAccessView != nullptr)
        DetourDetach(&(PVOID&) o_CreateUnorderedAccessView, gSurveyWrappers ? hkSurveyCreateUnorderedAccessView : hkCreateUnorderedAccessView);

    if (o_CopyDescriptors != nullptr)
        DetourDetach(&(PVOID&) o_CopyDescriptors, gSurveyWrappers ? hkSurveyCopyDescriptors : hkCopyDescriptors);

    if (o_CopyDescriptorsSimple != nullptr)
        DetourDetach(&(PVOID&) o_CopyDescriptorsSimple, gSurveyWrappers ? hkSurveyCopyDescriptorsSimple : hkCopyDescriptorsSimple);

    // Queue
    if (o_ExecuteCommandLists != nullptr)
        DetourDetach(&(PVOID&) o_ExecuteCommandLists, gSurveyWrappers ? hkSurveyExecuteCommandLists : hkExecuteCommandLists);

    // CommandList
    if (o_OMSetRenderTargets != nullptr)
        DetourDetach(&(PVOID&) o_OMSetRenderTargets, gSurveyWrappers ? hkSurveyOMSetRenderTargets : hkOMSetRenderTargets);

    if (o_SetGraphicsRootDescriptorTable != nullptr)
        DetourDetach(&(PVOID&) o_SetGraphicsRootDescriptorTable, gSurveyWrappers ? hkSurveySetGraphicsRootDescriptorTable : hkSetGraphicsRootDescriptorTable);

    if (o_SetComputeRootDescriptorTable != nullptr)
        DetourDetach(&(PVOID&) o_SetComputeRootDescriptorTable, gSurveyWrappers ? hkSurveySetComputeRootDescriptorTable : hkSetComputeRootDescriptorTable);

    if (o_DrawIndexedInstanced != nullptr)
        DetourDetach(&(PVOID&) o_DrawIndexedInstanced, gSurveyWrappers ? hkSurveyDrawIndexedInstanced : hkDrawIndexedInstanced);

    if (o_DrawInstanced != nullptr)
        DetourDetach(&(PVOID&) o_DrawInstanced, gSurveyWrappers ? hkSurveyDrawInstanced : hkDrawInstanced);

    if (o_Dispatch != nullptr)
        DetourDetach(&(PVOID&) o_Dispatch, gSurveyWrappers ? hkSurveyDispatch : hkDispatch);

    if (o_Close != nullptr)
        DetourDetach(&(PVOID&) o_Close, gSurveyWrappers ? hkSurveyClose : hkClose);

    if (o_Reset != nullptr)
        DetourDetach(&(PVOID&) o_Reset, gSurveyWrappers ? hkSurveyReset : hkReset);
    if (o_ClearState != nullptr) DetourDetach(&(PVOID&) o_ClearState,hkBridgeClearState);
    if (o_SetPredication != nullptr) DetourDetach(&(PVOID&) o_SetPredication,hkBridgeSetPredication);
    if (o_CommandListRelease != nullptr)
        DetourDetach(&(PVOID&) o_CommandListRelease, hkCommandListRelease);

    if (o_SetPipelineState != nullptr)
        DetourDetach(&(PVOID&) o_SetPipelineState, gSurveyWrappers ? hkSurveySetPipelineState : hkSetPipelineState);

    if (o_ResourceBarrier != nullptr)
        DetourDetach(&(PVOID&) o_ResourceBarrier, gSurveyWrappers ? hkSurveyResourceBarrier : hkResourceBarrier);

    if (o_SetMarker != nullptr)
        DetourDetach(&(PVOID&) o_SetMarker, gSurveyWrappers ? hkSurveySetMarker : hkSetMarker);

    if (o_BeginEvent != nullptr)
        DetourDetach(&(PVOID&) o_BeginEvent, gSurveyWrappers ? hkSurveyBeginEvent : hkBeginEvent);

    if (o_EndEvent != nullptr)
        DetourDetach(&(PVOID&) o_EndEvent, gSurveyWrappers ? hkSurveyEndEvent : hkEndEvent);

    if (o_ExecuteBundle != nullptr)
        DetourDetach(&(PVOID&) o_ExecuteBundle, gSurveyWrappers ? hkSurveyExecuteBundle : hkExecuteBundle);

    // Resource
    if (o_Release != nullptr && !gResourceReleaseSharesCommandList && !gResourceReleaseSharesPso &&
        !gResourceReleaseSharesHeap && !gResourceReleaseSharesBirth)
        DetourDetach(&(PVOID&) o_Release, hkRelease);

    if (o_PsoRelease != nullptr)
        DetourDetach(&(PVOID&) o_PsoRelease, hkPsoRelease);

    for (size_t i = 0; i != gBirthReleaseEntriesUsed; ++i)
        DetourDetach(reinterpret_cast<PVOID*>(&gBirthReleaseEntries[i].original),
                     reinterpret_cast<PVOID>(gBirthReleaseHooks[i]));

    DetourTransactionCommit();

    // Device
    o_CreateDescriptorHeap = nullptr;
    o_CreateGraphicsPipelineState = nullptr;
    o_CreateComputePipelineState = nullptr;
    o_CreatePipelineState = nullptr;
    o_CreateRenderTargetView = nullptr;
    o_CreateConstantBufferView = nullptr;
    o_CreateShaderResourceView = nullptr;
    o_CreateUnorderedAccessView = nullptr;
    o_CopyDescriptors = nullptr;
    o_CopyDescriptorsSimple = nullptr;

    // Queue
    o_ExecuteCommandLists = nullptr;

    // CommandList
    o_OMSetRenderTargets = nullptr;
    o_SetGraphicsRootDescriptorTable = nullptr;
    o_SetComputeRootDescriptorTable = nullptr;
    o_DrawIndexedInstanced = nullptr;
    o_DrawInstanced = nullptr;
    o_Dispatch = nullptr;
    o_Close = nullptr;
    o_Reset = nullptr;
    o_CommandListRelease = nullptr;
    gCommandListReleaseEntry = nullptr;
    gComputeResetEntry = nullptr;
    gRRRecordingCloseEntry = gRRRecordingBarrierEntry = nullptr;
    o_SetPipelineState = nullptr;
    o_ResourceBarrier = nullptr;
    o_SetMarker = nullptr;
    o_BeginEvent = nullptr;
    o_EndEvent = nullptr;
    o_ExecuteBundle = nullptr;

    // Resource
    o_Release = nullptr;
    gSharedResourceReleaseObserver = nullptr;
    o_PsoRelease = nullptr;
    gResourceReleaseEntry = nullptr;
    gPsoReleaseEntry = nullptr;
    gResourceReleaseSharesCommandList = false;
    gResourceReleaseSharesPso = false;
    gResourceReleaseSharesHeap = false;
    gResourceReleaseSharesBirth = false;
    for (size_t i = 0; i != gBirthReleaseEntriesUsed; ++i)
    { gBirthReleaseEntries[i].entry.store(nullptr,std::memory_order_release);
      gBirthReleaseEntries[i].original = nullptr; }
    gBirthReleaseEntriesUsed = 0;
    gHeapReleaseSharesResource.store(false,std::memory_order_release);
    // A resource-owned trampoline is retired by Detours; never leave a dangling
    // heap alias. A legacy heap-owned detour keeps its own original trampoline.
    if (!gHeapOwnsReleaseHook) { o_HeapRelease = nullptr; gHeapReleaseEntry = nullptr; }
    gComputeExecuteEntry = nullptr;
    gComputeQueueDeviceIdentity.Reset();

    {
        std::scoped_lock resourceLock(gRRTrackedResourceMutex);
        gRRTrackedResources.clear(); gRRResourceSizeIndex.clear();
    }
    {
        std::scoped_lock stateLock(gRRResourceStateMutex);
        gRRResourceStates.clear();
        gRRResourceActivity.clear();
        gRRRecordingProofs.clear(); ++gRRSelectedStateEpoch;
    }
    {
        std::scoped_lock candidateLock(gRRResourceCandidateMutex);
        gRRResourceCandidates.clear();
    }
    {
        std::scoped_lock markerLock(gRRMarkerMutex);
        gRRCommandListMarkers.clear();
        gRRMarkerInventory.clear();
    }
    {
        std::scoped_lock psoLock(gRRPsoMutex);
        gRRPsoMetadata.clear();
        gRRCommandListPsoStates.clear();
        gRRResourcePsoProducers.clear();
        gRRPsoCommandLists.clear();
        gRRPsoProducerResources.clear();
        gRRNextPsoId.store(1, std::memory_order_release);
    }
    gRRResourceCandidateAddress.store(0, std::memory_order_release);
}

void ResTrack_Dx12::ReleaseHooks()
{
    LOG_DEBUG("");

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    // if (o_CreateDescriptorHeap != nullptr)
    //     DetourDetach(&(PVOID&) o_CreateDescriptorHeap, gSurveyWrappers ? hkSurveyCreateDescriptorHeap : hkCreateDescriptorHeap);

    // if (o_CreateRenderTargetView != nullptr)
    //     DetourDetach(&(PVOID&) o_CreateRenderTargetView, gSurveyWrappers ? hkSurveyCreateRenderTargetView : hkCreateRenderTargetView);

    // if (o_CreateShaderResourceView != nullptr)
    //     DetourDetach(&(PVOID&) o_CreateShaderResourceView, gSurveyWrappers ? hkSurveyCreateShaderResourceView : hkCreateShaderResourceView);

    // if (o_CreateUnorderedAccessView != nullptr)
    //     DetourDetach(&(PVOID&) o_CreateUnorderedAccessView, gSurveyWrappers ? hkSurveyCreateUnorderedAccessView : hkCreateUnorderedAccessView);

    // if (o_CopyDescriptors != nullptr)
    //     DetourDetach(&(PVOID&) o_CopyDescriptors, gSurveyWrappers ? hkSurveyCopyDescriptors : hkCopyDescriptors);

    // if (o_CopyDescriptorsSimple != nullptr)
    //     DetourDetach(&(PVOID&) o_CopyDescriptorsSimple, gSurveyWrappers ? hkSurveyCopyDescriptorsSimple : hkCopyDescriptorsSimple);

    // o_CreateDescriptorHeap = nullptr;
    // o_CreateRenderTargetView = nullptr;
    // o_CreateShaderResourceView = nullptr;
    // o_CreateUnorderedAccessView = nullptr;
    // o_CopyDescriptors = nullptr;
    // o_CopyDescriptorsSimple = nullptr;

    // if (o_ExecuteCommandLists != nullptr)
    //     DetourAttach(&(PVOID&) o_ExecuteCommandLists, gSurveyWrappers ? hkSurveyExecuteCommandLists : hkExecuteCommandLists);

    // o_ExecuteCommandLists = nullptr;

    // if (o_Release != nullptr)
    //     DetourAttach(&(PVOID&) o_Release, hkRelease);

    // o_Release = nullptr;

    if (o_OMSetRenderTargets != nullptr)
        DetourDetach(&(PVOID&) o_OMSetRenderTargets, gSurveyWrappers ? hkSurveyOMSetRenderTargets : hkOMSetRenderTargets);

    if (o_SetGraphicsRootDescriptorTable != nullptr)
        DetourDetach(&(PVOID&) o_SetGraphicsRootDescriptorTable, gSurveyWrappers ? hkSurveySetGraphicsRootDescriptorTable : hkSetGraphicsRootDescriptorTable);

    if (o_SetComputeRootDescriptorTable != nullptr)
        DetourDetach(&(PVOID&) o_SetComputeRootDescriptorTable, gSurveyWrappers ? hkSurveySetComputeRootDescriptorTable : hkSetComputeRootDescriptorTable);

    if (o_DrawIndexedInstanced != nullptr)
        DetourDetach(&(PVOID&) o_DrawIndexedInstanced, gSurveyWrappers ? hkSurveyDrawIndexedInstanced : hkDrawIndexedInstanced);

    if (o_DrawInstanced != nullptr)
        DetourDetach(&(PVOID&) o_DrawInstanced, gSurveyWrappers ? hkSurveyDrawInstanced : hkDrawInstanced);

    if (o_Dispatch != nullptr)
        DetourDetach(&(PVOID&) o_Dispatch, gSurveyWrappers ? hkSurveyDispatch : hkDispatch);

    if (o_Close != nullptr)
        DetourDetach(&(PVOID&) o_Close, gSurveyWrappers ? hkSurveyClose : hkClose);

    // HUD-only teardown must preserve RR recording retirement observers. Full
    // ReleaseDeviceHooks disables admission before detaching these device hooks.

    if (o_SetPipelineState != nullptr)
        DetourDetach(&(PVOID&) o_SetPipelineState, gSurveyWrappers ? hkSurveySetPipelineState : hkSetPipelineState);

    if (o_ResourceBarrier != nullptr)
        DetourDetach(&(PVOID&) o_ResourceBarrier, gSurveyWrappers ? hkSurveyResourceBarrier : hkResourceBarrier);

    if (o_SetMarker != nullptr)
        DetourDetach(&(PVOID&) o_SetMarker, gSurveyWrappers ? hkSurveySetMarker : hkSetMarker);

    if (o_BeginEvent != nullptr)
        DetourDetach(&(PVOID&) o_BeginEvent, gSurveyWrappers ? hkSurveyBeginEvent : hkBeginEvent);

    if (o_EndEvent != nullptr)
        DetourDetach(&(PVOID&) o_EndEvent, gSurveyWrappers ? hkSurveyEndEvent : hkEndEvent);

    if (o_ExecuteBundle != nullptr)
        DetourDetach(&(PVOID&) o_ExecuteBundle, gSurveyWrappers ? hkSurveyExecuteBundle : hkExecuteBundle);

    o_OMSetRenderTargets = nullptr;
    o_SetGraphicsRootDescriptorTable = nullptr;
    o_SetComputeRootDescriptorTable = nullptr;
    o_DrawIndexedInstanced = nullptr;
    o_DrawInstanced = nullptr;
    o_Dispatch = nullptr;
    o_Close = nullptr;
    o_SetPipelineState = nullptr;
    o_ResourceBarrier = nullptr;
    o_SetMarker = nullptr;
    o_BeginEvent = nullptr;
    o_EndEvent = nullptr;
    o_ExecuteBundle = nullptr;

    DetourTransactionCommit();
}

void ResTrack_Dx12::ClearPossibleHudless()
{
    LOG_DEBUG("");

    auto hfIndex = Hudfix_Dx12::ActivePresentFrame() % BUFFER_COUNT;

    if (!_useShards)
    {
        std::lock_guard<std::mutex> lock(_hudlessTrackMutex);
        fgPossibleHudless[hfIndex].clear();
    }
    else
    {
        for (size_t i = 0; i < SHARD_COUNT; i++)
        {
            auto& shard = _hudlessShards[hfIndex][i];

            LOCK_GUARD(shard.mutex);

            shard.map.clear();
        }
    }

    std::lock_guard<std::mutex> lock2(_resourceCommandListMutex);

    auto fg = State::Instance().currentFG;
    if (fg != nullptr)
    {
        auto fIndex = fg->GetIndex();

        if (_notFoundCmdLists.size() > 10)
            _notFoundCmdLists.clear();

        for (const auto& pair : _resourceCommandList[fIndex])
        {
            LOG_WARN("{} cmdList: {:X}, not closed!", (UINT) pair.first, (size_t) pair.second);
            _notFoundCmdLists.insert(pair.second);
        }

        _resourceCommandList[fIndex].clear();

        for (const auto& pair : _resCmdList[fIndex])
        {
            LOG_WARN("{} cmdList: {:X}, not executed!", (UINT) pair.first, (size_t) pair.second);
            _notFoundCmdLists.insert(pair.second);
        }

        _resCmdList[fIndex].clear();
    }
}

void ResTrack_Dx12::SetResourceCmdList(FG_ResourceType type, ID3D12GraphicsCommandList* cmdList)
{
    auto fg = State::Instance().currentFG;
    if (fg != nullptr && fg->IsActive())
    {
        auto index = fg->GetIndex();

        ID3D12GraphicsCommandList* realCmdList = nullptr;
        if (!CheckForRealObject(__FUNCTION__, cmdList, (IUnknown**) &realCmdList))
            realCmdList = cmdList;

        _resourceCommandList[index][type] = realCmdList;
        LOG_DEBUG("_resourceCommandList[{}][{}]: {:X}", index, magic_enum::enum_name(type), (size_t) realCmdList);
    }
}

bool ResTrack_Dx12::EnsureRRTraceHooks(ID3D12Device* device)
{
    static std::mutex mutex;
    std::scoped_lock lock(mutex);
    if (!device) return false;
    HookToQueue(device);
    HookCommandList(device);
    return o_ExecuteCommandLists != nullptr && o_Reset != nullptr;
}

// Selected only when the NRD bridge is installed at startup.
void ResTrack_Dx12::hkSurveyCreateConstantBufferView(ID3D12Device* This, const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc,
                                                   D3D12_CPU_DESCRIPTOR_HANDLE handle)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::ConstantBufferView,gNrdBridgeWrappers && !FrameSurvey::Internal());
    o_CreateConstantBufferView(This,desc,handle);
    FrameSurvey::View(handle,desc);
}

// Selected only for startup FrameSurvey instrumentation.
void ResTrack_Dx12::hkSurveyCreateRenderTargetView(ID3D12Device* This, ID3D12Resource* pResource,
                                             D3D12_RENDER_TARGET_VIEW_DESC* pDesc,
                                             D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor)
{
    hkCreateRenderTargetView(This,pResource,pDesc,DestDescriptor);
    FrameSurvey::View(pResource,DestDescriptor,pDesc);
}

void ResTrack_Dx12::hkSurveyCreateShaderResourceView(ID3D12Device* This, ID3D12Resource* pResource,
                                               D3D12_SHADER_RESOURCE_VIEW_DESC* pDesc,
                                               D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::ShaderResourceView,gNrdBridgeWrappers && !FrameSurvey::Internal());
    hkCreateShaderResourceView(This,pResource,pDesc,DestDescriptor);
    FrameSurvey::View(pResource,DestDescriptor,pDesc);
}

void ResTrack_Dx12::hkSurveyCreateUnorderedAccessView(ID3D12Device* This, ID3D12Resource* pResource,
                                                ID3D12Resource* pCounterResource,
                                                D3D12_UNORDERED_ACCESS_VIEW_DESC* pDesc,
                                                D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::UnorderedAccessView,gNrdBridgeWrappers && !FrameSurvey::Internal());
    hkCreateUnorderedAccessView(This,pResource,pCounterResource,pDesc,DestDescriptor);
    FrameSurvey::View(pResource,DestDescriptor,pDesc);
}

HRESULT ResTrack_Dx12::hkSurveyCreateDescriptorHeap(ID3D12Device* This, D3D12_DESCRIPTOR_HEAP_DESC* pDescriptorHeapDesc,
                                              REFIID riid, void** ppvHeap)
{
    const auto result = hkCreateDescriptorHeap(This,pDescriptorHeapDesc,riid,ppvHeap);
    if (SUCCEEDED(result) && ppvHeap && *ppvHeap)
    {
        ReturnedHeapInterface returned(*ppvHeap,riid);
        if (returned.heap && (!gNrdBridgeWrappers || HeapReleaseObserverCovers(returned.heap)))
        {
            if (RRInspectorBirthsEnabled() && *ppvHeap != returned.heap && !FrameSurvey::Internal())
            {
                if (!ObserveBridgeObjectRelease(static_cast<IUnknown*>(*ppvHeap))) return result;
                const auto birth = NrdBridgeNativeBirth::Prepare(returned.heap);
                NrdBridgeNativeBirth::RetirementScope effects;
                if (!birth || !effects.Valid() || !NrdBridgeBirth::LinkAlias(birth->InstanceStamp(),*ppvHeap)) return result;
            }
            FrameSurvey::HeapCreated(This,returned.heap);
        }
    }
    return result;
}

HRESULT ResTrack_Dx12::hkSurveyCreateGraphicsPipelineState(
    ID3D12Device* This, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* pDesc,
    REFIID riid, void** ppPipelineState)
{
    const auto result = hkCreateGraphicsPipelineState(This,pDesc,riid,ppPipelineState);
    if (SUCCEEDED(result) && pDesc && ppPipelineState && *ppPipelineState)
    {
        ReturnedPipelineInterface returned(*ppPipelineState,riid);
        if (returned.pipeline)
        {
            if (RRInspectorBirthsEnabled() && *ppPipelineState != returned.pipeline && !FrameSurvey::Internal())
            {
                if (!NrdBridgeNativeBirth::ObserveReleaseCoverage(static_cast<IUnknown*>(*ppPipelineState))) return result;
                const auto birth = RRStrongReceiver(returned.pipeline);
                NrdBridgeNativeBirth::RetirementScope effects;
                if (!birth || !effects.Valid() || !NrdBridgeBirth::LinkAlias(birth->InstanceStamp(),*ppPipelineState)) return result;
            }
            FrameSurvey::PipelineCreated(returned.pipeline,*pDesc);
        }
    }
    return result;
}

HRESULT ResTrack_Dx12::hkSurveyCreateComputePipelineState(
    ID3D12Device* This, const D3D12_COMPUTE_PIPELINE_STATE_DESC* pDesc,
    REFIID riid, void** ppPipelineState)
{
    const auto result = hkCreateComputePipelineState(This,pDesc,riid,ppPipelineState);
    if (SUCCEEDED(result) && pDesc && ppPipelineState && *ppPipelineState)
    {
        ReturnedPipelineInterface returned(*ppPipelineState,riid);
        if (returned.pipeline)
        {
            if (RRInspectorBirthsEnabled() && *ppPipelineState != returned.pipeline && !FrameSurvey::Internal())
            {
                if (!NrdBridgeNativeBirth::ObserveReleaseCoverage(static_cast<IUnknown*>(*ppPipelineState))) return result;
                const auto birth = RRStrongReceiver(returned.pipeline);
                NrdBridgeNativeBirth::RetirementScope effects;
                if (!birth || !effects.Valid() || !NrdBridgeBirth::LinkAlias(birth->InstanceStamp(),*ppPipelineState)) return result;
            }
            FrameSurvey::PipelineCreated(returned.pipeline,*pDesc);
        }
    }
    return result;
}

HRESULT ResTrack_Dx12::hkSurveyCreatePipelineState(
    ID3D12Device2* This, const D3D12_PIPELINE_STATE_STREAM_DESC* pDesc,
    REFIID riid, void** ppPipelineState)
{
    const auto result = hkCreatePipelineState(This,pDesc,riid,ppPipelineState);
    if (SUCCEEDED(result) && pDesc && ppPipelineState && *ppPipelineState)
    {
        ReturnedPipelineInterface returned(*ppPipelineState,riid);
        if (returned.pipeline)
        {
            if (RRInspectorBirthsEnabled() && *ppPipelineState != returned.pipeline && !FrameSurvey::Internal())
            {
                if (!NrdBridgeNativeBirth::ObserveReleaseCoverage(static_cast<IUnknown*>(*ppPipelineState))) return result;
                const auto birth = RRStrongReceiver(returned.pipeline);
                NrdBridgeNativeBirth::RetirementScope effects;
                if (!birth || !effects.Valid() || !NrdBridgeBirth::LinkAlias(birth->InstanceStamp(),*ppPipelineState)) return result;
            }
            FrameSurvey::PipelineCreated(returned.pipeline,*pDesc);
        }
    }
    return result;
}

void ResTrack_Dx12::hkSurveySetGraphicsRootDescriptorTable(ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
                                                     D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootTable,gNrdBridgeWrappers && !FrameSurvey::Internal());
    FrameSurvey::Table(This,true,RootParameterIndex,BaseDescriptor);
    hkSetGraphicsRootDescriptorTable(This,RootParameterIndex,BaseDescriptor);
}

void ResTrack_Dx12::hkSurveySetComputeRootDescriptorTable(ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
                                                    D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootTable,gNrdBridgeWrappers && !FrameSurvey::Internal());
    if (FrameSurvey::Internal()) { o_SetComputeRootDescriptorTable(This,RootParameterIndex,BaseDescriptor); return; }
    FrameSurvey::Table(This,false,RootParameterIndex,BaseDescriptor);
    hkSetComputeRootDescriptorTable(This,RootParameterIndex,BaseDescriptor);
}

void ResTrack_Dx12::hkSurveyOMSetRenderTargets(ID3D12GraphicsCommandList* This, UINT NumRenderTargetDescriptors,
                                         D3D12_CPU_DESCRIPTOR_HANDLE* pRenderTargetDescriptors,
                                         BOOL RTsSingleHandleToDescriptorRange,
                                         D3D12_CPU_DESCRIPTOR_HANDLE* pDepthStencilDescriptor)
{
    FrameSurvey::RenderTargets(This,NumRenderTargetDescriptors,pRenderTargetDescriptors,RTsSingleHandleToDescriptorRange);
    hkOMSetRenderTargets(This,NumRenderTargetDescriptors,pRenderTargetDescriptors,RTsSingleHandleToDescriptorRange,pDepthStencilDescriptor);
}

void ResTrack_Dx12::hkSurveyResourceBarrier(ID3D12GraphicsCommandList* This, UINT NumBarriers,
                                      const D3D12_RESOURCE_BARRIER* pBarriers)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::Barrier,gNrdBridgeWrappers && !FrameSurvey::Internal());
    if (FrameSurvey::Internal()) { o_ResourceBarrier(This,NumBarriers,pBarriers); return; }
    NrdBridge::OnResourceBarriers(This,NumBarriers,pBarriers);
    FrameSurvey::Barrier(This,NumBarriers,pBarriers);
    hkResourceBarrier(This,NumBarriers,pBarriers);
}

void ResTrack_Dx12::hkSurveySetPipelineState(ID3D12GraphicsCommandList* This,
                                       ID3D12PipelineState* pPipelineState)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::SetPipelineState,gNrdBridgeWrappers && !FrameSurvey::Internal());
    if (FrameSurvey::Internal()) { o_SetPipelineState(This,pPipelineState); return; }
    NrdBridgeTitleCallbacks::Scope forwarding(NrdBridgeTitleCallbacks::Method::Pipeline, gNrdBridgeWrappers);
    if (forwarding.Nested()) { hkSetPipelineState(This,pPipelineState); return; }
    FrameSurvey::SetPipeline(This,pPipelineState);
    hkSetPipelineState(This,pPipelineState);
    if (gNrdBridgeWrappers) NrdBridge::OnSetPipeline(This,pPipelineState);
}

static void STDMETHODCALLTYPE hkBridgeClearState(ID3D12GraphicsCommandList* This, ID3D12PipelineState* initial)
{
    if (FrameSurvey::Internal()) { o_ClearState(This,initial); return; }
    NrdBridgeTitleCallbacks::Scope forwarding(NrdBridgeTitleCallbacks::Method::ClearState,gNrdBridgeWrappers);
    if (forwarding.Nested()) { o_ClearState(This,initial); return; }
    if (gNrdBridgeWrappers) NrdBridge::InvalidateRecordingProof(This,"ClearState before native forwarding");
    o_ClearState(This,initial);
    if (gNrdBridgeWrappers)
    {
        D3D12Hooks::OnBridgeCommandListClearState(This,initial);
        NrdBridge::InvalidateRecordingProof(This,"ClearState invalidated the current root/dispatch proof");
        FrameSurvey::RootBinding(This,false,nullptr); FrameSurvey::RootBinding(This,true,nullptr);
        FrameSurvey::DescriptorHeaps(This,0,nullptr); FrameSurvey::SetPipeline(This,initial);
    }
}

static void STDMETHODCALLTYPE hkBridgeSetPredication(ID3D12GraphicsCommandList* This, ID3D12Resource* predicate,
    UINT64 offset, D3D12_PREDICATION_OP operation)
{
    if (FrameSurvey::Internal()) { o_SetPredication(This,predicate,offset,operation); return; }
    NrdBridgeTitleCallbacks::Scope forwarding(NrdBridgeTitleCallbacks::Method::Predication,gNrdBridgeWrappers);
    if (forwarding.Nested()) { o_SetPredication(This,predicate,offset,operation); return; }
    if (gNrdBridgeWrappers && predicate)
        NrdBridge::InvalidateRecordingProof(This,"Predication enabled before native forwarding");
    o_SetPredication(This,predicate,offset,operation);
    if (gNrdBridgeWrappers)
    {
        D3D12Hooks::OnBridgeSetPredication(This,predicate != nullptr);
        if (predicate) NrdBridge::InvalidateRecordingProof(This,"Predicated recording cannot admit owned RR work");
    }
}

HRESULT ResTrack_Dx12::hkSurveyReset(ID3D12GraphicsCommandList* This,
                               ID3D12CommandAllocator* pAllocator,
                               ID3D12PipelineState* pInitialState)
{
    NrdBridgeTitleCallbacks::Scope forwarding(NrdBridgeTitleCallbacks::Method::Reset,
                                               gNrdBridgeWrappers && !FrameSurvey::Internal());
    if (forwarding.Nested()) return hkReset(This,pAllocator,pInitialState);
    const auto result = hkReset(This,pAllocator,pInitialState);
    if (SUCCEEDED(result))
    {
        FrameSurvey::Reset(This,pInitialState);
        if (gNrdBridgeWrappers)
        {
            D3D12Hooks::OnBridgeCommandListReset(This,pInitialState);
            NrdBridge::OnReset(This,pInitialState);
        }
    }
    return result;
}

HRESULT ResTrack_Dx12::hkSurveyClose(ID3D12GraphicsCommandList* This)
{
    const auto result = hkClose(This);
    FrameSurvey::Close(This,result);
    NrdBridge::OnRecordingClosed(This,result);
    return result;
}

void ResTrack_Dx12::hkSurveySetMarker(ID3D12GraphicsCommandList* This, UINT Metadata, const void* pData, UINT Size)
{
    FrameSurvey::Event(This,Metadata,pData,Size,0);
    hkSetMarker(This,Metadata,pData,Size);
}

void ResTrack_Dx12::hkSurveyBeginEvent(ID3D12GraphicsCommandList* This, UINT Metadata, const void* pData, UINT Size)
{
    FrameSurvey::Event(This,Metadata,pData,Size,1);
    hkBeginEvent(This,Metadata,pData,Size);
}

void ResTrack_Dx12::hkSurveyEndEvent(ID3D12GraphicsCommandList* This)
{
    FrameSurvey::Event(This,0,nullptr,0,-1);
    hkEndEvent(This);
}

void ResTrack_Dx12::hkSurveyDispatch(ID3D12GraphicsCommandList* This, UINT ThreadGroupCountX, UINT ThreadGroupCountY,
                               UINT ThreadGroupCountZ)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::Dispatch,gNrdBridgeWrappers && !FrameSurvey::Internal());
    if (FrameSurvey::Internal()) { o_Dispatch(This,ThreadGroupCountX,ThreadGroupCountY,ThreadGroupCountZ); return; }
    NrdBridgeTitleCallbacks::Scope forwarding(NrdBridgeTitleCallbacks::Method::Dispatch, gNrdBridgeWrappers);
    if (forwarding.Nested()) { hkDispatch(This,ThreadGroupCountX,ThreadGroupCountY,ThreadGroupCountZ); return; }
    if (gNrdBridgeWrappers) NrdBridge::BeforeDispatch(This);
    const bool suppress = gNrdBridgeWrappers &&
        NrdBridge::OriginalDispatchDisposition(This,NrdBridge::DispatchKind::Direct) == NrdBridge::DispatchDisposition::Suppress;
    const std::array<uint64_t,3> args {ThreadGroupCountX,ThreadGroupCountY,ThreadGroupCountZ};
    FrameSurvey::Pass(This,suppress ? "DispatchSkipped" : "Dispatch",args);
    if (!suppress)
    {
        hkDispatch(This,ThreadGroupCountX,ThreadGroupCountY,ThreadGroupCountZ);
        FrameSurvey::SnapshotWrites(This);
    }
    if (gNrdBridgeWrappers) NrdBridge::AfterDispatch(This);
}

void ResTrack_Dx12::hkSurveyDrawInstanced(ID3D12GraphicsCommandList* This, UINT VertexCountPerInstance, UINT InstanceCount,
                                    UINT StartVertexLocation, UINT StartInstanceLocation)
{
    const std::array<uint64_t,4> args {VertexCountPerInstance,InstanceCount,StartVertexLocation,StartInstanceLocation};
    FrameSurvey::Pass(This,"DrawInstanced",args);
    hkDrawInstanced(This,VertexCountPerInstance,InstanceCount,StartVertexLocation,StartInstanceLocation);
    FrameSurvey::SnapshotWrites(This);
}

void ResTrack_Dx12::hkSurveyDrawIndexedInstanced(ID3D12GraphicsCommandList* This, UINT IndexCountPerInstance,
                                           UINT InstanceCount, UINT StartIndexLocation, INT BaseVertexLocation,
                                           UINT StartInstanceLocation)
{
    const std::array<uint64_t,5> args {IndexCountPerInstance,InstanceCount,StartIndexLocation,uint64_t(int64_t(BaseVertexLocation)),StartInstanceLocation};
    FrameSurvey::Pass(This,"DrawIndexedInstanced",args);
    hkDrawIndexedInstanced(This,IndexCountPerInstance,InstanceCount,StartIndexLocation,BaseVertexLocation,StartInstanceLocation);
    FrameSurvey::SnapshotWrites(This);
}

void ResTrack_Dx12::hkSurveyExecuteBundle(ID3D12GraphicsCommandList* This, ID3D12GraphicsCommandList* pCommandList)
{
    if (FrameSurvey::Internal()) { hkExecuteBundle(This,pCommandList); return; }
    NrdBridgeTitleCallbacks::Scope forwarding(NrdBridgeTitleCallbacks::Method::Bundle,gNrdBridgeWrappers);
    if (forwarding.Nested()) { hkExecuteBundle(This,pCommandList); return; }
    if (gNrdBridgeWrappers)
    {
        NrdBridge::OriginalDispatchDisposition(This,NrdBridge::DispatchKind::Bundle);
        D3D12Hooks::OnBridgeOpaqueCommand(This,true);
    }
    const std::array<uint64_t,1> args {uint64_t(reinterpret_cast<uintptr_t>(pCommandList))};
    FrameSurvey::Pass(This,"ExecuteBundle",args);
    hkExecuteBundle(This,pCommandList);
    if (gNrdBridgeWrappers)
    {
        D3D12Hooks::OnBridgeOpaqueCommand(This,true);
        NrdBridge::InvalidateRecordingProof(This,"ExecuteBundle invalidated the current root/dispatch proof");
        FrameSurvey::RootBinding(This,false,nullptr); FrameSurvey::RootBinding(This,true,nullptr);
        FrameSurvey::DescriptorHeaps(This,0,nullptr); FrameSurvey::SetPipeline(This,nullptr);
    }
    FrameSurvey::SnapshotWrites(This);
}

static bool HasRetainedSubmissionParticipant(UINT count, ID3D12CommandList* const* lists) noexcept
{
    if (FAILED(RecordedComputeLease::RequiredSubmissionFailure())) return true;
    if (!count) return false;
    if (!lists) return true;
    try
    {
        for (UINT index = 0; index != count; ++index)
        {
            auto* list = lists[index];
            if (!list) return true;
            const bool nativeBirth = NrdBridgeNativeBirth::Ready();
            const auto birth = nativeBirth ? NrdBridgeBirth::Capture(list) : NrdBridgeBirth::Token{};
            // Only an exact CacheAdmissible physical CommandList birth can prove
            // this negative. Its recording marker is monotonic across Reset and
            // every proven alias; no canonical identity is guessed from a pointer.
            if (birth && birth->Address() == list && birth->CacheAdmissible() && !birth->RecordingMayExist())
                continue;
            const bool uncertainBirth = nativeBirth && (!NrdBridgeBirth::Healthy() ||
                (birth && !birth->CacheAdmissible()));
            // The caller owns each closed list throughout Execute. Pin optional
            // native unwrapping and canonical IUnknown before any registry lookup;
            // their COM calls/destruction never occur under the lease registry.
            constexpr IID nativeObject {0xadec44e2, 0x61f0, 0x45c3, {0xad, 0x9f, 0x1b, 0x37, 0x37, 0x92, 0x84, 0xff}};
            Microsoft::WRL::ComPtr<IUnknown> unwrapped, identity;
            IUnknown* actual = list;
            const auto nativeResult = list->QueryInterface(nativeObject, reinterpret_cast<void**>(unwrapped.GetAddressOf()));
            if (SUCCEEDED(nativeResult))
            {
                if (!unwrapped) return true;
                actual = unwrapped.Get();
            }
            else if (nativeResult != E_NOINTERFACE) return true;
            if (FAILED(actual->QueryInterface(IID_PPV_ARGS(&identity))) || !identity) return true;
            if (uncertainBirth || RecordedComputeLease::HasSubmissionParticipant(identity.Get(),list) ||
                (actual != list && RecordedComputeLease::HasSubmissionParticipant(identity.Get(),actual))) return true;
        }
    }
    catch (...) { return true; }
    return false;
}

void ResTrack_Dx12::hkSurveyExecuteCommandLists(ID3D12CommandQueue* This, UINT NumCommandLists,
                                          ID3D12CommandList* const* ppCommandLists)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::ExecuteCommandLists,gNrdBridgeWrappers && !FrameSurvey::Internal());
    if (!RequiredComputeSubmissionAllowed()) return;
    std::unique_lock transaction(FrameSurvey::SubmissionMutex(),std::defer_lock);
    // Legal Execute submits caller-owned CLOSED lists; concurrent Reset/recording
    // mutation is not a legal native use. Thus first Track cannot race selection.
    // Preserve the whole Before/Execute/Signal publication transaction for any
    // retained work, including old closed bridge recordings after runtime OFF.
    if (FrameSurvey::Enabled() || HasRetainedSubmissionParticipant(NumCommandLists,ppCommandLists))
    {
        NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Tracking);
        transaction.lock();
    }
    FrameSurvey::Submit(This,NumCommandLists,ppCommandLists);
    hkExecuteCommandLists(This,NumCommandLists,ppCommandLists);
}

void ResTrack_Dx12::hkSurveyCopyDescriptors(ID3D12Device* This, UINT NumDestDescriptorRanges,
                                      D3D12_CPU_DESCRIPTOR_HANDLE* pDestDescriptorRangeStarts,
                                      UINT* pDestDescriptorRangeSizes, UINT NumSrcDescriptorRanges,
                                      D3D12_CPU_DESCRIPTOR_HANDLE* pSrcDescriptorRangeStarts,
                                      UINT* pSrcDescriptorRangeSizes, D3D12_DESCRIPTOR_HEAP_TYPE DescriptorHeapsType)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::CopyDescriptors,gNrdBridgeWrappers && !FrameSurvey::Internal());
    FrameSurvey::CopyDescriptors(This,NumDestDescriptorRanges,pDestDescriptorRangeStarts,pDestDescriptorRangeSizes,NumSrcDescriptorRanges,pSrcDescriptorRangeStarts,pSrcDescriptorRangeSizes,DescriptorHeapsType);
    hkCopyDescriptors(This,NumDestDescriptorRanges,pDestDescriptorRangeStarts,pDestDescriptorRangeSizes,NumSrcDescriptorRanges,pSrcDescriptorRangeStarts,pSrcDescriptorRangeSizes,DescriptorHeapsType);
}

void ResTrack_Dx12::hkSurveyCopyDescriptorsSimple(ID3D12Device* This, UINT NumDescriptors,
                                            D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptorRangeStart,
                                            D3D12_CPU_DESCRIPTOR_HANDLE SrcDescriptorRangeStart,
                                            D3D12_DESCRIPTOR_HEAP_TYPE DescriptorHeapsType)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::CopyDescriptors,gNrdBridgeWrappers && !FrameSurvey::Internal());
    FrameSurvey::CopyDescriptors(This,1,&DestDescriptorRangeStart,&NumDescriptors,1,&SrcDescriptorRangeStart,&NumDescriptors,DescriptorHeapsType);
    hkCopyDescriptorsSimple(This,NumDescriptors,DestDescriptorRangeStart,SrcDescriptorRangeStart,DescriptorHeapsType);
}
