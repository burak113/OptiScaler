#include "pch.h"
#include "shaders/fsrd_preprocess/FSRDNrdBridge_Dx12.h"
#include "misc/NrdBridgeDevice_Dx12.h"
#include "misc/NrdBridgePerf_Dx12.h"
#include "misc/NrdBridgeNativeBirth_Dx12.h"
#include "misc/NrdBridgeLifetime_Dx12.h"
#include "D3D12_Hooks.h"

#include <Util.h>
#include <Config.h>
#include <array>

#include <magic_enum.hpp>

#include <resource_tracking/ResTrack_Dx12.h>
#include <resource_tracking/FrameSurvey_Dx12.h>

#include <proxies/D3D12_Proxy.h>
#include <proxies/XeFG_Proxy.h>
#include <proxies/XeSS_Proxy.h>
#include <proxies/IGDExt_Proxy.h>
#include <proxies/Streamline_Proxy.h>
#include <proxies/KernelBase_Proxy.h>

#include <detours/detours.h>

#include <dxgi1_6.h>
#include <misc/IdentifyGpu.h>

#include "Hook_Utils.h"

#pragma intrinsic(_ReturnAddress)

using PFN_CheckFeatureSupport = rewrite_signature<decltype(&ID3D12Device::CheckFeatureSupport)>::type;
using PFN_CreateSampler = rewrite_signature<decltype(&ID3D12Device::CreateSampler)>::type;
using PFN_CreateCommittedResource = rewrite_signature<decltype(&ID3D12Device::CreateCommittedResource)>::type;
using PFN_CreatePlacedResource = rewrite_signature<decltype(&ID3D12Device::CreatePlacedResource)>::type;
using PFN_SetResidencyPriority = rewrite_signature<decltype(&ID3D12Device1::SetResidencyPriority)>::type;
using PFN_CreateRootSignature = rewrite_signature<decltype(&ID3D12Device::CreateRootSignature)>::type;

// GetResourceAllocationInfo is a special case because of the struct return,
// see comment on hkGetResourceAllocationInfo for details
typedef void(STDMETHODCALLTYPE* PFN_GetResourceAllocationInfo)(ID3D12Device* device,
                                                               D3D12_RESOURCE_ALLOCATION_INFO* pResult,
                                                               UINT visibleMask, UINT numResourceDescs,
                                                               D3D12_RESOURCE_DESC* pResourceDescs);

typedef decltype(&D3D12GetInterface) PFN_D3D12GetInterface;

using PFN_CreateDevice = rewrite_signature<decltype(&ID3D12DeviceFactory::CreateDevice)>::type;

using PFN_Release = rewrite_signature<decltype(&IUnknown::Release)>::type;

static PFN_CreateSampler o_CreateSampler = nullptr;
static PFN_CheckFeatureSupport o_CheckFeatureSupport = nullptr;
static PFN_CreateCommittedResource o_CreateCommittedResource = nullptr;
static PFN_CreatePlacedResource o_CreatePlacedResource = nullptr;
static PFN_SetResidencyPriority o_SetResidencyPriority = nullptr;
static PFN_GetResourceAllocationInfo o_GetResourceAllocationInfo = nullptr;
static bool gSurveyDeviceWrappers = false;
static bool gNrdBridgeDeviceWrappers = false;
static PFN_CreateRootSignature o_CreateRootSignature = nullptr;
static PFN_D3D12GetInterface o_D3D12GetInterface = nullptr;
static PFN_CreateDevice o_CreateDevice = nullptr;

static D3d12Proxy::PFN_D3D12CreateDevice o_D3D12CreateDevice = nullptr;
static D3d12Proxy::PFN_D3D12SerializeRootSignature o_D3D12SerializeRootSignature = nullptr;
static D3d12Proxy::PFN_D3D12SerializeVersionedRootSignature o_D3D12SerializeVersionedRootSignature = nullptr;
static PFN_Release o_D3D12DeviceRelease = nullptr;

static bool _creatingD3D12Device = false;
static bool _d3d12Captured = false;
static LUID _lastAdapterLuid = {};

// Common
using PFN_SetDescriptorHeaps = rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetDescriptorHeaps)>::type;
using PFN_SetPipelineState = rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetPipelineState)>::type;

// ComputeRoot
using PFN_SetComputeRootSignature =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetComputeRootSignature)>::type;
using PFN_SetComputeRootDescriptorTable =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetComputeRootDescriptorTable)>::type;
using PFN_SetComputeRoot32BitConstant =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetComputeRoot32BitConstant)>::type;
using PFN_SetComputeRoot32BitConstants =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetComputeRoot32BitConstants)>::type;
using PFN_SetComputeRootConstantBufferView =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetComputeRootConstantBufferView)>::type;
using PFN_SetComputeRootShaderResourceView =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetComputeRootShaderResourceView)>::type;
using PFN_SetComputeRootUnorderedAccessView =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetComputeRootUnorderedAccessView)>::type;

// GraphicsRoot
using PFN_SetGraphicsRootSignature =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetGraphicsRootSignature)>::type;
using PFN_SetGraphicsRootDescriptorTable =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable)>::type;
using PFN_SetGraphicsRoot32BitConstant =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetGraphicsRoot32BitConstant)>::type;
using PFN_SetGraphicsRoot32BitConstants =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetGraphicsRoot32BitConstants)>::type;
using PFN_SetGraphicsRootConstantBufferView =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetGraphicsRootConstantBufferView)>::type;
using PFN_SetGraphicsRootShaderResourceView =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetGraphicsRootShaderResourceView)>::type;
using PFN_SetGraphicsRootUnorderedAccessView =
    rewrite_signature<decltype(&ID3D12GraphicsCommandList::SetGraphicsRootUnorderedAccessView)>::type;

template <typename T> struct RootRestoreHook
{
    T o_earlyHook = nullptr;
    T o_lateHook = nullptr;

    T GetHook() const { return o_lateHook ? o_lateHook : o_earlyHook; };
};

struct DescriptorHeap
{
    UINT NumDescriptorHeaps {};
    ID3D12DescriptorHeap* Heaps[2] = { nullptr, nullptr }; // apparently 2 is max
    NrdBridgeBirth::Token receiverBirth;
    std::array<NrdBridgeBirth::Token,2> heapBirths;
};

enum class RootEntryType
{
    Invalid,
    Table,
    Constant,
    Constants,
    CBV,
    SRV,
    UAV,
};

struct RootState
{
    RootEntryType type = RootEntryType::Invalid;

    // Table
    D3D12_GPU_DESCRIPTOR_HANDLE rootDescriptorTable {};

    // CBV / SRV / UAV
    D3D12_GPU_VIRTUAL_ADDRESS bufferLocation {};

    // Constants; Constant uses Data[0] and DestOffset
    UINT Num32BitValues = 0;
    UINT DestOffset = 0;
    std::vector<uint32_t> Data;
    // Bridge-only: root constants may be written in several disjoint updates.
    std::vector<uint8_t> ValidConstants;
};

struct TrackedRootRows : std::vector<RootState>
{
    NrdBridgeBirth::Token receiverBirth, rootBirth;
    bool rootCountKnown = false;
};
struct TrackedPipelineState
{
    ID3D12PipelineState* ptr = nullptr;
    NrdBridgeBirth::Token receiverBirth, pipelineBirth;
    TrackedPipelineState() = default;
    TrackedPipelineState(ID3D12PipelineState* value) : ptr(value) {}
    TrackedPipelineState(ID3D12PipelineState* value, NrdBridgeBirth::Token receiver, NrdBridgeBirth::Token pipeline)
        : ptr(value), receiverBirth(std::move(receiver)), pipelineBirth(std::move(pipeline)) {}
    operator ID3D12PipelineState*() const noexcept { return ptr; }
    TrackedPipelineState& operator=(ID3D12PipelineState* value)
    { ptr=value; receiverBirth.reset(); pipelineBirth.reset(); return *this; }
};
static bool RootTrackerBirthsEnabled() noexcept
{ return gNrdBridgeDeviceWrappers && NrdBridgeNativeBirth::Ready(); }
template <class T> static NrdBridgeBirth::Token TrackerNativeReceiver(T* object)
{
    if (!RootTrackerBirthsEnabled() || !object || FrameSurvey::Internal()) return {};
    return NrdBridgeNativeBirth::ReceiverWithReleaseCoverage(object,[](auto* strong) noexcept {
        return NrdBridgeNativeBirth::ObserveReleaseCoverage(static_cast<IUnknown*>(strong));
    });
}
static bool TrackerBorrowMatches(const NrdBridgeBirth::Token& node, void* address) noexcept
{ return node && node->Address() == address && node->CacheAdmissible(); }
class RootTrackerPublication
{
    std::optional<NrdBridgeBirth::CurrentGuard> guard_;
  public:
    NrdBridgeBirth::Token receiver;
    explicit RootTrackerPublication(ID3D12GraphicsCommandList* list)
    {
        if (!RootTrackerBirthsEnabled()) return;
        receiver = TrackerNativeReceiver(list);
        guard_.emplace(receiver);
    }
    bool Accepted() const noexcept
    { return !RootTrackerBirthsEnabled() || (guard_ && guard_->MatchesCurrent() && NrdBridgeBirth::Healthy()); }
};

static void MergeBridgeConstants(RootState& state, UINT offset, UINT count, const uint32_t* source)
{
    if (!source || count == 0 || offset > 64 || count > 64 - offset) return;
    if (state.type != RootEntryType::Constants || state.ValidConstants.empty())
    { state.Data.clear(); state.ValidConstants.clear(); }
    state.type = RootEntryType::Constants;
    const size_t size = std::max(state.Data.size(), size_t(offset) + count);
    state.Data.resize(size); state.ValidConstants.resize(size);
    std::copy_n(source, count, state.Data.begin() + offset);
    std::fill_n(state.ValidConstants.begin() + offset, count, uint8_t(1));
    state.Num32BitValues = UINT(size); state.DestOffset = 0;
}

template <typename Lock> static void LockRootTracker(Lock& lock)
{
    if (lock.try_lock()) return; // Uncontended: not a wait.
    NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Tracking);
    lock.lock();
}

enum class SignatureEntryType
{
    Invalid,
    Compute,
    Graphics,
};

struct SignatureEntry
{
    SignatureEntryType type = SignatureEntryType::Invalid;
    ID3D12RootSignature* ptr {};
    NrdBridgeBirth::Token receiverBirth, rootBirth;
};

// Every legal D3D12 root signature fits in 64 DWORDs. Keep the restore copy
// allocation-free: an allocation failure after injection must not lose state.
template <typename T> struct RootRestoreValues
{
    std::array<T, D3D12_MAX_ROOT_COST> values {};
    size_t count = 0;
    size_t size() const { return count; }
    bool empty() const { return count == 0; }
    const T* data() const { return values.data(); }
    const T& operator[](size_t index) const { return values[index]; }
};
struct RootRestoreArgument
{
    RootEntryType type = RootEntryType::Invalid;
    D3D12_GPU_DESCRIPTOR_HANDLE rootDescriptorTable {};
    D3D12_GPU_VIRTUAL_ADDRESS bufferLocation {};
    UINT Num32BitValues = 0, DestOffset = 0;
    RootRestoreValues<uint32_t> Data;
    RootRestoreValues<uint8_t> ValidConstants;
};
struct D3D12RootRestoreSnapshot
{
    struct { SignatureEntryType type = SignatureEntryType::Invalid; ID3D12RootSignature* ptr = nullptr; } signature;
    struct { UINT NumDescriptorHeaps = 0; ID3D12DescriptorHeap* Heaps[2] = {nullptr,nullptr}; } heaps;
    ID3D12PipelineState* pipelineState = nullptr;
    RootRestoreValues<RootRestoreArgument> rootStates;
    bool hasSignature = false, hasHeaps = false, hasPipelineState = false, hasRootState = false;
};
static bool RootRestoreArgumentsSupported(const std::vector<RootState>& table)
{
    if (table.size() > D3D12_MAX_ROOT_COST) return false;
    for (const auto& entry : table)
    {
        if (entry.Data.size() > D3D12_MAX_ROOT_COST || entry.ValidConstants.size() > entry.Data.size()) return false;
        if (entry.type == RootEntryType::Constant && entry.Data.empty()) return false;
        if (entry.type == RootEntryType::Constants && entry.ValidConstants.empty() && entry.Num32BitValues > entry.Data.size()) return false;
    }
    return true;
}

static std::shared_mutex descriptorHeapsMutex;
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*, DescriptorHeap> descriptorHeaps;
static RootRestoreHook<PFN_SetDescriptorHeaps> s_SetDescriptorHeaps {};

static std::shared_mutex pipelineStatesMutex;
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*, TrackedPipelineState> pipelineStates;
static RootRestoreHook<PFN_SetPipelineState> s_SetPipelineState {};

// Those use a common rootSignatureMutex mutex
static std::shared_mutex rootSignatureMutex;
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*, SignatureEntry> signatures;
static RootRestoreHook<PFN_SetGraphicsRootSignature> s_SetGraphicsRootSignature {};
static RootRestoreHook<PFN_SetComputeRootSignature> s_SetComputeRootSignature {};

// Those use a common rootStatesMutex mutex
static std::shared_mutex rootStatesMutex;
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*, TrackedRootRows> rootStates;
static RootRestoreHook<PFN_SetComputeRootDescriptorTable> s_SetComputeRootDescriptorTable {};
static RootRestoreHook<PFN_SetComputeRoot32BitConstant> s_SetComputeRoot32BitConstant {};
static RootRestoreHook<PFN_SetComputeRoot32BitConstants> s_SetComputeRoot32BitConstants {};
static RootRestoreHook<PFN_SetComputeRootConstantBufferView> s_SetComputeRootConstantBufferView {};
static RootRestoreHook<PFN_SetComputeRootShaderResourceView> s_SetComputeRootShaderResourceView {};
static RootRestoreHook<PFN_SetComputeRootUnorderedAccessView> s_SetComputeRootUnorderedAccessView {};

static RootRestoreHook<PFN_SetGraphicsRootDescriptorTable> s_SetGraphicsRootDescriptorTable {};
static RootRestoreHook<PFN_SetGraphicsRoot32BitConstant> s_SetGraphicsRoot32BitConstant {};
static RootRestoreHook<PFN_SetGraphicsRoot32BitConstants> s_SetGraphicsRoot32BitConstants {};
static RootRestoreHook<PFN_SetGraphicsRootConstantBufferView> s_SetGraphicsRootConstantBufferView {};
static RootRestoreHook<PFN_SetGraphicsRootShaderResourceView> s_SetGraphicsRootShaderResourceView {};
static RootRestoreHook<PFN_SetGraphicsRootUnorderedAccessView> s_SetGraphicsRootUnorderedAccessView {};

static thread_local bool lateInProgressSetDescriptorHeaps = false;
static thread_local bool lateInProgressSetPipelineState = false;

static thread_local bool lateInProgressSetComputeRootSignature = false;
static thread_local bool lateInProgressSetComputeRootDescriptorTable = false;
static thread_local bool lateInProgressSetComputeRoot32BitConstants = false;
static thread_local bool lateInProgressSetComputeRoot32BitConstant = false;
static thread_local bool lateInProgressSetComputeRootConstantBufferView = false;
static thread_local bool lateInProgressSetComputeRootShaderResourceView = false;
static thread_local bool lateInProgressSetComputeRootUnorderedAccessView = false;

static thread_local bool lateInProgressSetGraphicsRootSignature = false;
static thread_local bool lateInProgressSetGraphicsRootDescriptorTable = false;
static thread_local bool lateInProgressSetGraphicsRoot32BitConstants = false;
static thread_local bool lateInProgressSetGraphicsRoot32BitConstant = false;
static thread_local bool lateInProgressSetGraphicsRootConstantBufferView = false;
static thread_local bool lateInProgressSetGraphicsRootShaderResourceView = false;
static thread_local bool lateInProgressSetGraphicsRootUnorderedAccessView = false;

static std::shared_mutex rootSigParameterCountMutex;
static ankerl::unordered_dense::map<ID3D12RootSignature*, UINT> rootSigParameterCount;
static ankerl::unordered_dense::map<ID3D12RootSignature*, NrdBridgeBirth::Token> rootSigBirths;

static bool isUpscalerActive = false;
// The bridge can inject while other CPU threads record independent title lists.
// Preserve the existing off path; bridge suppression applies only to the recording thread.
static thread_local bool isNrdBridgeInjection = false;
static thread_local const char* bridgeComputeRestoreFailure = nullptr;
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*, ID3D12RootSignature*> bridgeComputeRoots;
// Bridge-on compute arguments remain in rootStates; graphics setters must not
// overwrite them when both families are active on the same native list.
struct BridgeGraphicsState { ID3D12RootSignature* root = nullptr; TrackedRootRows rows; };
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*, BridgeGraphicsState> bridgeGraphicsStates;
// Absence means UNKNOWN, never disabled. Only a witnessed successful Reset,
// ClearState or SetPredication(nullptr) establishes the injection precondition.
enum class BridgePredication { Disabled, Enabled };
struct BridgePredicateState
{
    NrdBridgeBirth::Token receiverBirth;
    BridgePredication value = BridgePredication::Enabled;
};
static ankerl::unordered_dense::map<ID3D12GraphicsCommandList*, BridgePredicateState> bridgePredicates;
// Caller owns rootStatesMutex and, in native mode, the receiver CurrentGuard.
static bool BridgePredicateDisabledLocked(ID3D12GraphicsCommandList* list, const NrdBridgeBirth::Token& receiver)
{
    const auto found = bridgePredicates.find(list);
    return found != bridgePredicates.end() && found->second.value == BridgePredication::Disabled &&
        (!RootTrackerBirthsEnabled() || found->second.receiverBirth == receiver);
}
inline constexpr GUID RootParameterCountGuid = {0x72304b14,0x1a2e,0x46be,{0xae,0xdc,0x22,0x50,0x50,0x4d,0xc9,0x64}};
struct NativeRootParameterCount { uint64_t instanceStamp = 0; UINT count = 0, version = 1; };
static_assert(sizeof(NativeRootParameterCount) == 16);
static bool RootParameterCountKnown(ID3D12RootSignature* root, const NrdBridgeBirth::Token& birth)
{
    if (!RootTrackerBirthsEnabled()) return true;
    std::shared_lock lock(rootSigParameterCountMutex, std::defer_lock); LockRootTracker(lock);
    const auto node = rootSigBirths.find(root);
    return birth && birth->Live() && !birth->Failed() && node != rootSigBirths.end() && node->second == birth &&
        rootSigParameterCount.find(root) != rootSigParameterCount.end();
}
// A birth-only row records a cold NOT_FOUND count observation. Stable prehook
// roots remain locally unknown without repeating native getters on hot setters.
static bool RootParameterCountObserved(ID3D12RootSignature* root, const NrdBridgeBirth::Token& birth)
{
    if (!RootTrackerBirthsEnabled()) return true;
    std::shared_lock lock(rootSigParameterCountMutex, std::defer_lock); LockRootTracker(lock);
    const auto found = rootSigBirths.find(root);
    return birth && birth->Live() && !birth->Failed() && found != rootSigBirths.end() && found->second == birth;
}
static NrdBridgeBirth::Token TrackerRootReceiver(ID3D12RootSignature* root) noexcept
{
    try
    {
        auto birth = TrackerNativeReceiver(root);
        if (!birth || RootParameterCountObserved(root,birth)) return birth;
        NativeRootParameterCount native;
        UINT bytes = sizeof(native);
        // This cold native getter runs before the receiver/list CurrentGuard.
        const auto result = root->GetPrivateData(RootParameterCountGuid,&bytes,&native);
        const bool known = result != DXGI_ERROR_NOT_FOUND;
        if (known && (FAILED(result) || bytes != sizeof(native) || native.version != 1 ||
            native.instanceStamp != birth->InstanceStamp() || native.count > D3D12_MAX_ROOT_COST))
        { NrdBridgeNativeBirth::Detail::Fail("native root parameter count read failed"); return {}; }
        NrdBridgeBirth::CurrentGuard guard(birth);
        if (!guard.MatchesCurrent() || !NrdBridgeBirth::Healthy()) return {};
        std::unique_lock lock(rootSigParameterCountMutex, std::defer_lock); LockRootTracker(lock);
        if (known) rootSigParameterCount.insert_or_assign(root,native.count); else rootSigParameterCount.erase(root);
        rootSigBirths.insert_or_assign(root,birth);
        return birth;
    }
    catch (...)
    {
        if (RootTrackerBirthsEnabled()) NrdBridgeNativeBirth::Detail::Fail("native root count bootstrap publication failed");
        return {};
    }
}
UINT GetRootParameterCount(ID3D12RootSignature* root, const NrdBridgeBirth::Token& birth = {});
// Caller owns the receiver CurrentGuard and rootStatesMutex. No native call or
// owner with a COM/custom deleter is stored in these bounded tracker rows.
static TrackedRootRows& TrackerRows(ID3D12GraphicsCommandList* list,
                                    const NrdBridgeBirth::Token& receiver, bool graphics = false)
{
    auto& rows = gNrdBridgeDeviceWrappers && graphics ? bridgeGraphicsStates[list].rows : rootStates[list];
    if (RootTrackerBirthsEnabled() && rows.receiverBirth != receiver)
    {
        rows.clear(); rows.receiverBirth = receiver; rows.rootBirth.reset(); rows.rootCountKnown = false;
        if (graphics) bridgeGraphicsStates[list].root = nullptr;
        else bridgeComputeRoots.erase(list);
    }
    return rows;
}
static void TrackBridgeGraphicsRoot(ID3D12GraphicsCommandList* list, ID3D12RootSignature* root,
                                    const NrdBridgeBirth::Token& receiver, const NrdBridgeBirth::Token& birth)
{
    if (!gNrdBridgeDeviceWrappers) return;
    const auto count = GetRootParameterCount(root,birth);
    std::unique_lock lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
    auto& rows = TrackerRows(list,receiver,true);
    auto& state = bridgeGraphicsStates[list];
    if (state.root != root || (RootTrackerBirthsEnabled() && rows.rootBirth != birth))
    { rows.clear(); state.root = root; rows.rootBirth = birth; }
    rows.rootCountKnown = RootParameterCountKnown(root,birth);
    rows.resize(rows.rootCountKnown ? count : D3D12_MAX_ROOT_COST);
}

// Intel Atomic Extension
struct UE_D3D12_RESOURCE_DESC
{
    D3D12_RESOURCE_DIMENSION Dimension;
    UINT64 Alignment;
    UINT64 Width;
    UINT Height;
    UINT16 DepthOrArraySize;
    UINT16 MipLevels;
    DXGI_FORMAT Format;
    DXGI_SAMPLE_DESC SampleDesc;
    D3D12_TEXTURE_LAYOUT Layout;
    D3D12_RESOURCE_FLAGS Flags;

    // UE Part
    uint8_t PixelFormat { 0 };
    uint8_t UAVPixelFormat { 0 };
    bool bRequires64BitAtomicSupport : 1 = false;
    bool bReservedResource : 1 = false;
    bool bBackBuffer : 1 = false;
    bool bExternal : 1 = false;
};

static ID3D12Device* _intelD3D12Device = nullptr;
static ULONG _intelD3D12DeviceRefTarget = 0;
static bool _skipCommitedResource = false;
static bool _skipGetResourceAllocationInfo = false;

#ifdef ENABLE_DEBUG_LAYER_DX12
static ID3D12Debug3* debugController = nullptr;
static ID3D12InfoQueue* infoQueue = nullptr;
static ID3D12InfoQueue1* infoQueue1 = nullptr;

static void CALLBACK D3D12DebugCallback(D3D12_MESSAGE_CATEGORY Category, D3D12_MESSAGE_SEVERITY Severity,
                                        D3D12_MESSAGE_ID ID, LPCSTR pDescription, void* pContext)
{
    LOG_DEBUG("[{}] [{}] [{}]: {}", magic_enum::enum_name(Category), magic_enum::enum_name(Severity),
              magic_enum::enum_name(ID), pDescription);
}
#endif

static void HookToDevice(ID3D12Device* InDevice);
static void UnhookDevice();

static inline D3D12_FILTER UpgradeToAF(D3D12_FILTER f)
{
    // Skip point filter
    const auto minF = D3D12_DECODE_MIN_FILTER(f);
    const auto magF = D3D12_DECODE_MAG_FILTER(f);
    const auto mipF = D3D12_DECODE_MIP_FILTER(f);
    if (Config::Instance()->AnisotropySkipPointFilter.value_or_default() &&
        ((mipF == D3D12_FILTER_TYPE_POINT) || (minF == D3D12_FILTER_TYPE_POINT && magF == D3D12_FILTER_TYPE_POINT)))
    {
        return f;
    }

    const auto reduction = D3D12_DECODE_FILTER_REDUCTION(f);

    if (reduction == D3D12_FILTER_REDUCTION_TYPE_COMPARISON)
    {
        if (Config::Instance()->AnisotropyModifyComp.value_or_default())
            return D3D12_ENCODE_ANISOTROPIC_FILTER(D3D12_FILTER_REDUCTION_TYPE_COMPARISON);

        return f;
    }

    if (reduction == D3D12_FILTER_REDUCTION_TYPE_MINIMUM)
    {
        if (Config::Instance()->AnisotropyModifyMinMax.value_or_default())
            return D3D12_ENCODE_ANISOTROPIC_FILTER(D3D12_FILTER_REDUCTION_TYPE_MINIMUM);

        return f;
    }

    if (reduction == D3D12_FILTER_REDUCTION_TYPE_MAXIMUM)
    {
        if (Config::Instance()->AnisotropyModifyMinMax.value_or_default())
            return D3D12_ENCODE_ANISOTROPIC_FILTER(D3D12_FILTER_REDUCTION_TYPE_MAXIMUM);

        return f;
    }

    return D3D12_ENCODE_ANISOTROPIC_FILTER(D3D12_FILTER_REDUCTION_TYPE_STANDARD);
}

static void ApplySamplerOverrides(D3D12_STATIC_SAMPLER_DESC& samplerDesc)
{
    if (Config::Instance()->MipmapBiasOverride.has_value())
    {
        auto isMipmapped = samplerDesc.MinLOD != samplerDesc.MaxLOD;
        auto isAnisotropic = (samplerDesc.Filter == D3D12_FILTER_ANISOTROPIC) || (samplerDesc.MaxAnisotropy > 1);
        auto isAlreadyBiased = samplerDesc.MipLODBias < 0.0f;

        if ((isMipmapped && (isAnisotropic || isAlreadyBiased)) ||
            Config::Instance()->MipmapBiasOverrideAll.value_or_default())
        {
            if (Config::Instance()->MipmapBiasOverride.has_value())
            {
                LOG_DEBUG("Overriding mipmap bias {0} -> {1}", samplerDesc.MipLODBias,
                          Config::Instance()->MipmapBiasOverride.value());

                if (Config::Instance()->MipmapBiasFixedOverride.value_or_default())
                    samplerDesc.MipLODBias = Config::Instance()->MipmapBiasOverride.value();
                else if (Config::Instance()->MipmapBiasScaleOverride.value_or_default())
                    samplerDesc.MipLODBias = samplerDesc.MipLODBias * Config::Instance()->MipmapBiasOverride.value();
                else
                    samplerDesc.MipLODBias = samplerDesc.MipLODBias + Config::Instance()->MipmapBiasOverride.value();

                samplerDesc.MipLODBias = std::clamp(samplerDesc.MipLODBias, -16.0f, 15.99f);
            }

            if (State::Instance().lastMipBiasMax < samplerDesc.MipLODBias)
                State::Instance().lastMipBiasMax = samplerDesc.MipLODBias;

            if (State::Instance().lastMipBias > samplerDesc.MipLODBias)
                State::Instance().lastMipBias = samplerDesc.MipLODBias;
        }
    }

    if (Config::Instance()->AnisotropyOverride.has_value())
    {
        LOG_DEBUG("Overriding {2:X} to anisotropic filtering {0} -> {1}", samplerDesc.MaxAnisotropy,
                  Config::Instance()->AnisotropyOverride.value(), (UINT) samplerDesc.Filter);

        samplerDesc.Filter = UpgradeToAF(samplerDesc.Filter);
        samplerDesc.MaxAnisotropy = Config::Instance()->AnisotropyOverride.value();
    }
}

static void ApplySamplerOverrides(D3D12_STATIC_SAMPLER_DESC1& samplerDesc)
{
    if (Config::Instance()->MipmapBiasOverride.has_value())
    {
        if ((samplerDesc.MipLODBias < 0.0f && samplerDesc.MinLOD != samplerDesc.MaxLOD) ||
            Config::Instance()->MipmapBiasOverrideAll.value_or_default())
        {
            if (Config::Instance()->MipmapBiasOverride.has_value())
            {
                LOG_DEBUG("Overriding mipmap bias {0} -> {1}", samplerDesc.MipLODBias,
                          Config::Instance()->MipmapBiasOverride.value());

                if (Config::Instance()->MipmapBiasFixedOverride.value_or_default())
                    samplerDesc.MipLODBias = Config::Instance()->MipmapBiasOverride.value();
                else if (Config::Instance()->MipmapBiasScaleOverride.value_or_default())
                    samplerDesc.MipLODBias = samplerDesc.MipLODBias * Config::Instance()->MipmapBiasOverride.value();
                else
                    samplerDesc.MipLODBias = samplerDesc.MipLODBias + Config::Instance()->MipmapBiasOverride.value();
            }

            if (State::Instance().lastMipBiasMax < samplerDesc.MipLODBias)
                State::Instance().lastMipBiasMax = samplerDesc.MipLODBias;

            if (State::Instance().lastMipBias > samplerDesc.MipLODBias)
                State::Instance().lastMipBias = samplerDesc.MipLODBias;
        }
    }

    if (Config::Instance()->AnisotropyOverride.has_value())
    {
        LOG_DEBUG("Overriding {2:X} to anisotropic filtering {0} -> {1}", samplerDesc.MaxAnisotropy,
                  Config::Instance()->AnisotropyOverride.value(), (UINT) samplerDesc.Filter);

        samplerDesc.Filter = UpgradeToAF(samplerDesc.Filter);
        samplerDesc.MaxAnisotropy = Config::Instance()->AnisotropyOverride.value();
    }
}

// Early hooks, from Opti's own cmdlist
VALIDATE_HOOK(hkSetPipelineState, PFN_SetPipelineState)
static void hkSetPipelineState(ID3D12GraphicsCommandList* commandList, ID3D12PipelineState* pPipelineState)
{
    if (!lateInProgressSetPipelineState && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pPipelineState != nullptr)
    {
        const auto pipelineBirth = RootTrackerBirthsEnabled() ? TrackerNativeReceiver(pPipelineState) : NrdBridgeBirth::Token{};
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (pipelineBirth && pipelineBirth->Live() && !pipelineBirth->Failed())))
        {
            std::unique_lock<std::shared_mutex> lock(pipelineStatesMutex, std::defer_lock); LockRootTracker(lock);
            pipelineStates.insert_or_assign(commandList, TrackedPipelineState{pPipelineState,publication.receiver,pipelineBirth});

        }
    }

    s_SetPipelineState.o_earlyHook(commandList, pPipelineState);
}

VALIDATE_HOOK(hkSetDescriptorHeaps, PFN_SetDescriptorHeaps)
static void hkSetDescriptorHeaps(ID3D12GraphicsCommandList* commandList, UINT NumDescriptorHeaps,
                                 ID3D12DescriptorHeap* const* ppDescriptorHeaps)
{
    if (!lateInProgressSetDescriptorHeaps && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr &&
        ppDescriptorHeaps != nullptr)
    {
        std::array<NrdBridgeBirth::Token,2> heapBirths;
        if (RootTrackerBirthsEnabled() && NumDescriptorHeaps <= heapBirths.size())
            for (UINT i = 0; i < NumDescriptorHeaps; ++i) heapBirths[i] = TrackerNativeReceiver(ppDescriptorHeaps[i]);
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (NumDescriptorHeaps <= heapBirths.size() &&
            std::all_of(heapBirths.begin(),heapBirths.begin()+NumDescriptorHeaps,[](const auto& token){ return token && token->Live() && !token->Failed(); }))))
        {
            std::unique_lock<std::shared_mutex> lock(descriptorHeapsMutex, std::defer_lock); LockRootTracker(lock);
            DescriptorHeap temp {}; temp.receiverBirth = publication.receiver; temp.heapBirths = heapBirths;
            temp.NumDescriptorHeaps = NumDescriptorHeaps;
            for (UINT i = 0; i < NumDescriptorHeaps; ++i)
            {
                temp.Heaps[i] = ppDescriptorHeaps[i];
            }
            descriptorHeaps.insert_or_assign(commandList, std::move(temp));

        }
    }

    s_SetDescriptorHeaps.o_earlyHook(commandList, NumDescriptorHeaps, ppDescriptorHeaps);
}

static void hkSurveySetDescriptorHeaps(ID3D12GraphicsCommandList* commandList, UINT NumDescriptorHeaps,
                                 ID3D12DescriptorHeap* const* ppDescriptorHeaps)
{
    FrameSurvey::DescriptorHeaps(commandList,NumDescriptorHeaps,ppDescriptorHeaps);
    hkSetDescriptorHeaps(commandList,NumDescriptorHeaps,ppDescriptorHeaps);
}


UINT GetRootParameterCount(ID3D12RootSignature* pRootSignature, const NrdBridgeBirth::Token& birth)
{
    std::shared_lock lock(rootSigParameterCountMutex, std::defer_lock); LockRootTracker(lock);
    if (RootTrackerBirthsEnabled())
    {
        const auto node = rootSigBirths.find(pRootSignature);
        if (!birth || !birth->Live() || birth->Failed() || node == rootSigBirths.end() || node->second != birth) return 0;
    }
    const auto it = rootSigParameterCount.find(pRootSignature);
    return it != rootSigParameterCount.end() ? it->second : 0;
}

VALIDATE_HOOK(hkSetComputeRootSignature, PFN_SetComputeRootSignature)
static void hkSetComputeRootSignature(ID3D12GraphicsCommandList* commandList, ID3D12RootSignature* pRootSignature)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootSignature,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetComputeRootSignature &&
        (gNrdBridgeDeviceWrappers || Config::Instance()->RestoreComputeSignature.value_or_default()) &&
        !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pRootSignature != nullptr)
    {
        const auto rootBirth = RootTrackerBirthsEnabled() ? TrackerRootReceiver(pRootSignature) : NrdBridgeBirth::Token{};
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (rootBirth && rootBirth->Live() && !rootBirth->Failed())))
        {
            {
                auto paramCount = GetRootParameterCount(pRootSignature,rootBirth);
                std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
                auto& table = TrackerRows(commandList,publication.receiver);
                if (gNrdBridgeDeviceWrappers && (bridgeComputeRoots[commandList] != pRootSignature ||
                    (RootTrackerBirthsEnabled() && table.rootBirth != rootBirth)))
                { table.clear(); bridgeComputeRoots[commandList] = pRootSignature; table.rootBirth = rootBirth; }
                table.rootCountKnown = RootParameterCountKnown(pRootSignature,rootBirth);
                table.resize(table.rootCountKnown ? paramCount : D3D12_MAX_ROOT_COST);
            }

            std::unique_lock<std::shared_mutex> lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock);
            signatures.insert_or_assign(commandList, SignatureEntry { SignatureEntryType::Compute, pRootSignature, publication.receiver, rootBirth });

        }
    }

    s_SetComputeRootSignature.o_earlyHook(commandList, pRootSignature);
}

static void hkSurveySetComputeRootSignature(ID3D12GraphicsCommandList* commandList, ID3D12RootSignature* pRootSignature)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootSignature,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    FrameSurvey::RootBinding(commandList,false,pRootSignature);
    hkSetComputeRootSignature(commandList,pRootSignature);
}


VALIDATE_HOOK(hkSetComputeRootDescriptorTable, PFN_SetComputeRootDescriptorTable)
static void hkSetComputeRootDescriptorTable(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                            D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    if (!lateInProgressSetComputeRootDescriptorTable && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr &&
        BaseDescriptor.ptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::Table;
                table[RootParameterIndex].rootDescriptorTable = BaseDescriptor;
            }

        }
    }

    s_SetComputeRootDescriptorTable.o_earlyHook(commandList, RootParameterIndex, BaseDescriptor);
}

VALIDATE_HOOK(hkSetComputeRoot32BitConstants, PFN_SetComputeRoot32BitConstants)
static void hkSetComputeRoot32BitConstants(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                           UINT Num32BitValuesToSet, const void* pSrcData, UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetComputeRoot32BitConstants && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pSrcData)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, Num32BitValuesToSet,
                                         static_cast<const uint32_t*>(pSrcData));
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constants;
                    table[RootParameterIndex].Num32BitValues = Num32BitValuesToSet;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    auto* src = static_cast<const uint32_t*>(pSrcData);
                    table[RootParameterIndex].Data.assign(src, src + Num32BitValuesToSet);
                }
            }

        }
    }

    s_SetComputeRoot32BitConstants.o_earlyHook(commandList, RootParameterIndex, Num32BitValuesToSet, pSrcData,
                                               DestOffsetIn32BitValues);
}

VALIDATE_HOOK(hkSetComputeRoot32BitConstant, PFN_SetComputeRoot32BitConstant)
static void hkSetComputeRoot32BitConstant(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex, UINT SrcData,
                                          UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetComputeRoot32BitConstant && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, 1, &SrcData);
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constant;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    table[RootParameterIndex].Data.assign(1, SrcData);
                }
            }

        }
    }

    s_SetComputeRoot32BitConstant.o_earlyHook(commandList, RootParameterIndex, SrcData, DestOffsetIn32BitValues);
}

VALIDATE_HOOK(hkSetComputeRootConstantBufferView, PFN_SetComputeRootConstantBufferView)
static void hkSetComputeRootConstantBufferView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                               D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetComputeRootConstantBufferView && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::CBV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetComputeRootConstantBufferView.o_earlyHook(commandList, RootParameterIndex, BufferLocation);
}

static void hkSurveySetComputeRootConstantBufferView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                               D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    FrameSurvey::RootView(commandList,false,RootParameterIndex,D3D12_DESCRIPTOR_RANGE_TYPE_CBV,BufferLocation);
    hkSetComputeRootConstantBufferView(commandList,RootParameterIndex,BufferLocation);
}


VALIDATE_HOOK(hkSetComputeRootShaderResourceView, PFN_SetComputeRootShaderResourceView)
static void hkSetComputeRootShaderResourceView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                               D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetComputeRootShaderResourceView && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::SRV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetComputeRootShaderResourceView.o_earlyHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetComputeRootShaderResourceView = false;
}

static void hkSurveySetComputeRootShaderResourceView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                               D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    FrameSurvey::RootView(commandList,false,RootParameterIndex,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,BufferLocation);
    hkSetComputeRootShaderResourceView(commandList,RootParameterIndex,BufferLocation);
}


VALIDATE_HOOK(hkSetComputeRootUnorderedAccessView, PFN_SetComputeRootUnorderedAccessView)
static void hkSetComputeRootUnorderedAccessView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if ((gNrdBridgeDeviceWrappers ? !lateInProgressSetComputeRootUnorderedAccessView : lateInProgressSetComputeRootUnorderedAccessView) &&
        !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::UAV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetComputeRootUnorderedAccessView.o_earlyHook(commandList, RootParameterIndex, BufferLocation);
}

static void hkSurveySetComputeRootUnorderedAccessView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    FrameSurvey::RootView(commandList,false,RootParameterIndex,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,BufferLocation);
    hkSetComputeRootUnorderedAccessView(commandList,RootParameterIndex,BufferLocation);
}


VALIDATE_HOOK(hkSetGraphicsRootSignature, PFN_SetGraphicsRootSignature)
static void hkSetGraphicsRootSignature(ID3D12GraphicsCommandList* commandList, ID3D12RootSignature* pRootSignature)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootSignature,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetGraphicsRootSignature && (gNrdBridgeDeviceWrappers || Config::Instance()->RestoreGraphicSignature.value_or_default()) &&
        !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pRootSignature != nullptr)
    {
        const auto rootBirth = RootTrackerBirthsEnabled() ? TrackerRootReceiver(pRootSignature) : NrdBridgeBirth::Token{};
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (rootBirth && rootBirth->Live() && !rootBirth->Failed())))
        {
            TrackBridgeGraphicsRoot(commandList,pRootSignature,publication.receiver,rootBirth);
            std::unique_lock<std::shared_mutex> lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock);
            signatures.insert_or_assign(commandList, SignatureEntry { SignatureEntryType::Graphics, pRootSignature, publication.receiver, rootBirth });

        }
    }

    s_SetGraphicsRootSignature.o_earlyHook(commandList, pRootSignature);
}

static void hkSurveySetGraphicsRootSignature(ID3D12GraphicsCommandList* commandList, ID3D12RootSignature* pRootSignature)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootSignature,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    FrameSurvey::RootBinding(commandList,true,pRootSignature);
    hkSetGraphicsRootSignature(commandList,pRootSignature);
}


VALIDATE_HOOK(hkSetGraphicsRootDescriptorTable, PFN_SetGraphicsRootDescriptorTable)
static void hkSetGraphicsRootDescriptorTable(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                             D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    if (!lateInProgressSetGraphicsRootDescriptorTable && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr &&
        BaseDescriptor.ptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::Table;
                table[RootParameterIndex].rootDescriptorTable = BaseDescriptor;
            }

        }
    }

    s_SetGraphicsRootDescriptorTable.o_earlyHook(commandList, RootParameterIndex, BaseDescriptor);
}

VALIDATE_HOOK(hkSetGraphicsRoot32BitConstants, PFN_SetGraphicsRoot32BitConstants)
static void hkSetGraphicsRoot32BitConstants(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                            UINT Num32BitValuesToSet, const void* pSrcData,
                                            UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetGraphicsRoot32BitConstants && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pSrcData)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, Num32BitValuesToSet,
                                         static_cast<const uint32_t*>(pSrcData));
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constants;
                    table[RootParameterIndex].Num32BitValues = Num32BitValuesToSet;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    auto* src = static_cast<const uint32_t*>(pSrcData);
                    table[RootParameterIndex].Data.assign(src, src + Num32BitValuesToSet);
                }
            }

        }
    }

    s_SetGraphicsRoot32BitConstants.o_earlyHook(commandList, RootParameterIndex, Num32BitValuesToSet, pSrcData,
                                                DestOffsetIn32BitValues);
}

VALIDATE_HOOK(hkSetGraphicsRoot32BitConstant, PFN_SetGraphicsRoot32BitConstant)
static void hkSetGraphicsRoot32BitConstant(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                           UINT SrcData, UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetGraphicsRoot32BitConstant && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, 1, &SrcData);
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constant;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    table[RootParameterIndex].Data.assign(1, SrcData);
                }
            }

        }
    }

    s_SetGraphicsRoot32BitConstant.o_earlyHook(commandList, RootParameterIndex, SrcData, DestOffsetIn32BitValues);
}

VALIDATE_HOOK(hkSetGraphicsRootConstantBufferView, PFN_SetGraphicsRootConstantBufferView)
static void hkSetGraphicsRootConstantBufferView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetGraphicsRootConstantBufferView && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::CBV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetGraphicsRootConstantBufferView.o_earlyHook(commandList, RootParameterIndex, BufferLocation);
}

VALIDATE_HOOK(hkSetGraphicsRootShaderResourceView, PFN_SetGraphicsRootShaderResourceView)
static void hkSetGraphicsRootShaderResourceView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetGraphicsRootShaderResourceView && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::SRV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetGraphicsRootShaderResourceView.o_earlyHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetGraphicsRootShaderResourceView = false;
}

VALIDATE_HOOK(hkSetGraphicsRootUnorderedAccessView, PFN_SetGraphicsRootUnorderedAccessView)
static void hkSetGraphicsRootUnorderedAccessView(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                 D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    if (!lateInProgressSetGraphicsRootUnorderedAccessView && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::UAV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetGraphicsRootUnorderedAccessView.o_earlyHook(commandList, RootParameterIndex, BufferLocation);
}

// Late hooks, from upscaler eval
VALIDATE_HOOK(hkSetPipelineStateLate, PFN_SetPipelineState)
static void hkSetPipelineStateLate(ID3D12GraphicsCommandList* commandList, ID3D12PipelineState* pPipelineState)
{
    lateInProgressSetPipelineState = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pPipelineState != nullptr)
    {
        const auto pipelineBirth = RootTrackerBirthsEnabled() ? TrackerNativeReceiver(pPipelineState) : NrdBridgeBirth::Token{};
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (pipelineBirth && pipelineBirth->Live() && !pipelineBirth->Failed())))
        {
            std::unique_lock<std::shared_mutex> lock(pipelineStatesMutex, std::defer_lock); LockRootTracker(lock);
            pipelineStates.insert_or_assign(commandList, TrackedPipelineState{pPipelineState,publication.receiver,pipelineBirth});

        }
    }

    s_SetPipelineState.o_lateHook(commandList, pPipelineState);

    lateInProgressSetPipelineState = false;
}

VALIDATE_HOOK(hkSetDescriptorHeapsLate, PFN_SetDescriptorHeaps)
static void hkSetDescriptorHeapsLate(ID3D12GraphicsCommandList* commandList, UINT NumDescriptorHeaps,
                                     ID3D12DescriptorHeap* const* ppDescriptorHeaps)
{
    lateInProgressSetDescriptorHeaps = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && ppDescriptorHeaps != nullptr)
    {
        std::array<NrdBridgeBirth::Token,2> heapBirths;
        if (RootTrackerBirthsEnabled() && NumDescriptorHeaps <= heapBirths.size())
            for (UINT i = 0; i < NumDescriptorHeaps; ++i) heapBirths[i] = TrackerNativeReceiver(ppDescriptorHeaps[i]);
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (NumDescriptorHeaps <= heapBirths.size() &&
            std::all_of(heapBirths.begin(),heapBirths.begin()+NumDescriptorHeaps,[](const auto& token){ return token && token->Live() && !token->Failed(); }))))
        {
            std::unique_lock<std::shared_mutex> lock(descriptorHeapsMutex, std::defer_lock); LockRootTracker(lock);
            DescriptorHeap temp {}; temp.receiverBirth = publication.receiver; temp.heapBirths = heapBirths;
            temp.NumDescriptorHeaps = NumDescriptorHeaps;
            for (UINT i = 0; i < NumDescriptorHeaps; ++i)
            {
                temp.Heaps[i] = ppDescriptorHeaps[i];
            }
            descriptorHeaps.insert_or_assign(commandList, std::move(temp));

        }
    }

    s_SetDescriptorHeaps.o_lateHook(commandList, NumDescriptorHeaps, ppDescriptorHeaps);

    lateInProgressSetDescriptorHeaps = false;
}

VALIDATE_HOOK(hkSetComputeRootSignatureLate, PFN_SetComputeRootSignature)
static void hkSetComputeRootSignatureLate(ID3D12GraphicsCommandList* commandList, ID3D12RootSignature* pRootSignature)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootSignature,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetComputeRootSignature = true;

    if ((gNrdBridgeDeviceWrappers || Config::Instance()->RestoreComputeSignature.value_or_default()) &&
        !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pRootSignature != nullptr)
    {
        const auto rootBirth = RootTrackerBirthsEnabled() ? TrackerRootReceiver(pRootSignature) : NrdBridgeBirth::Token{};
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (rootBirth && rootBirth->Live() && !rootBirth->Failed())))
        {
            {
                auto paramCount = GetRootParameterCount(pRootSignature,rootBirth);
                std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
                auto& table = TrackerRows(commandList,publication.receiver);
                if (gNrdBridgeDeviceWrappers && (bridgeComputeRoots[commandList] != pRootSignature ||
                    (RootTrackerBirthsEnabled() && table.rootBirth != rootBirth)))
                { table.clear(); bridgeComputeRoots[commandList] = pRootSignature; table.rootBirth = rootBirth; }
                table.rootCountKnown = RootParameterCountKnown(pRootSignature,rootBirth);
                table.resize(table.rootCountKnown ? paramCount : D3D12_MAX_ROOT_COST);
            }

            std::unique_lock<std::shared_mutex> lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock);
            signatures.insert_or_assign(commandList, SignatureEntry { SignatureEntryType::Compute, pRootSignature, publication.receiver, rootBirth });

        }
    }

    s_SetComputeRootSignature.o_lateHook(commandList, pRootSignature);

    lateInProgressSetComputeRootSignature = false;
}

VALIDATE_HOOK(hkSetComputeRootDescriptorTableLate, PFN_SetComputeRootDescriptorTable)
static void hkSetComputeRootDescriptorTableLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    lateInProgressSetComputeRootDescriptorTable = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && BaseDescriptor.ptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::Table;
                table[RootParameterIndex].rootDescriptorTable = BaseDescriptor;
            }

        }
    }

    s_SetComputeRootDescriptorTable.o_lateHook(commandList, RootParameterIndex, BaseDescriptor);

    lateInProgressSetComputeRootDescriptorTable = false;
}

VALIDATE_HOOK(hkSetComputeRoot32BitConstantsLate, PFN_SetComputeRoot32BitConstants)
static void hkSetComputeRoot32BitConstantsLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                               UINT Num32BitValuesToSet, const void* pSrcData,
                                               UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetComputeRoot32BitConstants = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pSrcData)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, Num32BitValuesToSet,
                                         static_cast<const uint32_t*>(pSrcData));
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constants;
                    table[RootParameterIndex].Num32BitValues = Num32BitValuesToSet;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    auto* src = static_cast<const uint32_t*>(pSrcData);
                    table[RootParameterIndex].Data.assign(src, src + Num32BitValuesToSet);
                }
            }

        }
    }

    s_SetComputeRoot32BitConstants.o_lateHook(commandList, RootParameterIndex, Num32BitValuesToSet, pSrcData,
                                              DestOffsetIn32BitValues);

    lateInProgressSetComputeRoot32BitConstants = false;
}

VALIDATE_HOOK(hkSetComputeRoot32BitConstantLate, PFN_SetComputeRoot32BitConstant)
static void hkSetComputeRoot32BitConstantLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                              UINT SrcData, UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetComputeRoot32BitConstant = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, 1, &SrcData);
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constant;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    table[RootParameterIndex].Data.assign(1, SrcData);
                }
            }

        }
    }

    s_SetComputeRoot32BitConstant.o_lateHook(commandList, RootParameterIndex, SrcData, DestOffsetIn32BitValues);

    lateInProgressSetComputeRoot32BitConstant = false;
}

VALIDATE_HOOK(hkSetComputeRootConstantBufferViewLate, PFN_SetComputeRootConstantBufferView)
static void hkSetComputeRootConstantBufferViewLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                   D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetComputeRootConstantBufferView = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::CBV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetComputeRootConstantBufferView.o_lateHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetComputeRootConstantBufferView = false;
}

VALIDATE_HOOK(hkSetComputeRootShaderResourceViewLate, PFN_SetComputeRootShaderResourceView)
static void hkSetComputeRootShaderResourceViewLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                   D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetComputeRootShaderResourceView = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::SRV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetComputeRootShaderResourceView.o_lateHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetComputeRootShaderResourceView = false;
}

VALIDATE_HOOK(hkSetComputeRootUnorderedAccessViewLate, PFN_SetComputeRootUnorderedAccessView)
static void hkSetComputeRootUnorderedAccessViewLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                    D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetComputeRootUnorderedAccessView = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::UAV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetComputeRootUnorderedAccessView.o_lateHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetComputeRootUnorderedAccessView = false;
}

VALIDATE_HOOK(hkSetGraphicsRootSignatureLate, PFN_SetGraphicsRootSignature)
static void hkSetGraphicsRootSignatureLate(ID3D12GraphicsCommandList* commandList, ID3D12RootSignature* pRootSignature)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootSignature,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetGraphicsRootSignature = true;

    if ((gNrdBridgeDeviceWrappers || Config::Instance()->RestoreGraphicSignature.value_or_default()) && !(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr &&
        pRootSignature != nullptr)
    {
        const auto rootBirth = RootTrackerBirthsEnabled() ? TrackerRootReceiver(pRootSignature) : NrdBridgeBirth::Token{};
        RootTrackerPublication publication(commandList);
        if (publication.Accepted() && (!RootTrackerBirthsEnabled() || (rootBirth && rootBirth->Live() && !rootBirth->Failed())))
        {
            TrackBridgeGraphicsRoot(commandList,pRootSignature,publication.receiver,rootBirth);
            std::unique_lock<std::shared_mutex> lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock);
            signatures.insert_or_assign(commandList, SignatureEntry { SignatureEntryType::Graphics, pRootSignature, publication.receiver, rootBirth });

        }
    }

    s_SetGraphicsRootSignature.o_lateHook(commandList, pRootSignature);

    lateInProgressSetGraphicsRootSignature = false;
}

VALIDATE_HOOK(hkSetGraphicsRootDescriptorTableLate, PFN_SetGraphicsRootDescriptorTable)
static void hkSetGraphicsRootDescriptorTableLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                 D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor)
{
    lateInProgressSetGraphicsRootDescriptorTable = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && BaseDescriptor.ptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::Table;
                table[RootParameterIndex].rootDescriptorTable = BaseDescriptor;
            }

        }
    }

    s_SetGraphicsRootDescriptorTable.o_lateHook(commandList, RootParameterIndex, BaseDescriptor);

    lateInProgressSetGraphicsRootDescriptorTable = false;
}

VALIDATE_HOOK(hkSetGraphicsRoot32BitConstantsLate, PFN_SetGraphicsRoot32BitConstants)
static void hkSetGraphicsRoot32BitConstantsLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                UINT Num32BitValuesToSet, const void* pSrcData,
                                                UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetGraphicsRoot32BitConstants = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr && pSrcData)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, Num32BitValuesToSet,
                                         static_cast<const uint32_t*>(pSrcData));
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constants;
                    table[RootParameterIndex].Num32BitValues = Num32BitValuesToSet;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    auto* src = static_cast<const uint32_t*>(pSrcData);
                    table[RootParameterIndex].Data.assign(src, src + Num32BitValuesToSet);
                }
            }

        }
    }

    s_SetGraphicsRoot32BitConstants.o_lateHook(commandList, RootParameterIndex, Num32BitValuesToSet, pSrcData,
                                               DestOffsetIn32BitValues);

    lateInProgressSetGraphicsRoot32BitConstants = false;
}

VALIDATE_HOOK(hkSetGraphicsRoot32BitConstantLate, PFN_SetGraphicsRoot32BitConstant)
static void hkSetGraphicsRoot32BitConstantLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                               UINT SrcData, UINT DestOffsetIn32BitValues)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootConstants,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetGraphicsRoot32BitConstant = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                if (gNrdBridgeDeviceWrappers)
                    MergeBridgeConstants(table[RootParameterIndex], DestOffsetIn32BitValues, 1, &SrcData);
                else
                {
                    table[RootParameterIndex].type = RootEntryType::Constant;
                    table[RootParameterIndex].DestOffset = DestOffsetIn32BitValues;
                    table[RootParameterIndex].Data.assign(1, SrcData);
                }
            }

        }
    }

    s_SetGraphicsRoot32BitConstant.o_lateHook(commandList, RootParameterIndex, SrcData, DestOffsetIn32BitValues);

    lateInProgressSetGraphicsRoot32BitConstant = false;
}

VALIDATE_HOOK(hkSetGraphicsRootConstantBufferViewLate, PFN_SetGraphicsRootConstantBufferView)
static void hkSetGraphicsRootConstantBufferViewLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                    D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetGraphicsRootConstantBufferView = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::CBV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetGraphicsRootConstantBufferView.o_lateHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetGraphicsRootConstantBufferView = false;
}

VALIDATE_HOOK(hkSetGraphicsRootShaderResourceViewLate, PFN_SetGraphicsRootShaderResourceView)
static void hkSetGraphicsRootShaderResourceViewLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                    D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetGraphicsRootShaderResourceView = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::SRV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetGraphicsRootShaderResourceView.o_lateHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetGraphicsRootShaderResourceView = false;
}

VALIDATE_HOOK(hkSetGraphicsRootUnorderedAccessViewLate, PFN_SetGraphicsRootUnorderedAccessView)
static void hkSetGraphicsRootUnorderedAccessViewLate(ID3D12GraphicsCommandList* commandList, UINT RootParameterIndex,
                                                     D3D12_GPU_VIRTUAL_ADDRESS BufferLocation)
{
    NrdBridgePerf::Scope perf(NrdBridgePerf::Hook::RootView,gNrdBridgeDeviceWrappers && !FrameSurvey::Internal());
    lateInProgressSetGraphicsRootUnorderedAccessView = true;

    if (!(isUpscalerActive || isNrdBridgeInjection) && commandList != nullptr)
    {
        RootTrackerPublication publication(commandList);
        if (publication.Accepted())
        {
            std::unique_lock<std::shared_mutex> lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
            auto& table = TrackerRows(commandList,publication.receiver,true);
            if (RootParameterIndex < table.size())
            {
                table[RootParameterIndex].type = RootEntryType::UAV;
                table[RootParameterIndex].bufferLocation = BufferLocation;
            }

        }
    }

    s_SetGraphicsRootUnorderedAccessView.o_lateHook(commandList, RootParameterIndex, BufferLocation);

    lateInProgressSetGraphicsRootUnorderedAccessView = false;
}

// These six argument hooks are a bridge-only extension. Do not add new
// default-OFF detours merely because legacy graphics restoration is selected.
static bool bridgeGraphicsEarlyAttached = false, bridgeGraphicsLateAttached = false;
static void ReadBridgeGraphicsArgumentHooks(PVOID* table, bool late)
{
    if (!gNrdBridgeDeviceWrappers) return;
    if (late)
    {
        s_SetGraphicsRootDescriptorTable.o_lateHook = (PFN_SetGraphicsRootDescriptorTable) table[32];
        s_SetGraphicsRoot32BitConstant.o_lateHook = (PFN_SetGraphicsRoot32BitConstant) table[34];
        s_SetGraphicsRoot32BitConstants.o_lateHook = (PFN_SetGraphicsRoot32BitConstants) table[36];
        s_SetGraphicsRootConstantBufferView.o_lateHook = (PFN_SetGraphicsRootConstantBufferView) table[38];
        s_SetGraphicsRootShaderResourceView.o_lateHook = (PFN_SetGraphicsRootShaderResourceView) table[40];
        s_SetGraphicsRootUnorderedAccessView.o_lateHook = (PFN_SetGraphicsRootUnorderedAccessView) table[42];
    }
    else
    {
        s_SetGraphicsRootDescriptorTable.o_earlyHook = (PFN_SetGraphicsRootDescriptorTable) table[32];
        s_SetGraphicsRoot32BitConstant.o_earlyHook = (PFN_SetGraphicsRoot32BitConstant) table[34];
        s_SetGraphicsRoot32BitConstants.o_earlyHook = (PFN_SetGraphicsRoot32BitConstants) table[36];
        s_SetGraphicsRootConstantBufferView.o_earlyHook = (PFN_SetGraphicsRootConstantBufferView) table[38];
        s_SetGraphicsRootShaderResourceView.o_earlyHook = (PFN_SetGraphicsRootShaderResourceView) table[40];
        s_SetGraphicsRootUnorderedAccessView.o_earlyHook = (PFN_SetGraphicsRootUnorderedAccessView) table[42];
    }
}
static void ClearBridgeGraphicsArgumentHooks(bool late)
{
    auto clear = [late](auto& hooks) { (late ? hooks.o_lateHook : hooks.o_earlyHook) = nullptr; };
    clear(s_SetGraphicsRootDescriptorTable); clear(s_SetGraphicsRoot32BitConstant); clear(s_SetGraphicsRoot32BitConstants);
    clear(s_SetGraphicsRootConstantBufferView); clear(s_SetGraphicsRootShaderResourceView); clear(s_SetGraphicsRootUnorderedAccessView);
    (late ? bridgeGraphicsLateAttached : bridgeGraphicsEarlyAttached) = false;
}
static LONG AttachBridgeGraphicsArgumentHooks(bool late)
{
    if (!gNrdBridgeDeviceWrappers) return NO_ERROR;
    LONG result = NO_ERROR;
    auto attach = [&](auto& hooks, auto early, auto delayed) {
        auto& target = late ? hooks.o_lateHook : hooks.o_earlyHook;
        const LONG next = target ? DetourAttach(reinterpret_cast<PVOID*>(&target),
            reinterpret_cast<PVOID>(late ? delayed : early)) : ERROR_INVALID_PARAMETER;
        if (result == NO_ERROR) result = next;
    };
    attach(s_SetGraphicsRootDescriptorTable,hkSetGraphicsRootDescriptorTable,hkSetGraphicsRootDescriptorTableLate);
    attach(s_SetGraphicsRoot32BitConstant,hkSetGraphicsRoot32BitConstant,hkSetGraphicsRoot32BitConstantLate);
    attach(s_SetGraphicsRoot32BitConstants,hkSetGraphicsRoot32BitConstants,hkSetGraphicsRoot32BitConstantsLate);
    attach(s_SetGraphicsRootConstantBufferView,hkSetGraphicsRootConstantBufferView,hkSetGraphicsRootConstantBufferViewLate);
    attach(s_SetGraphicsRootShaderResourceView,hkSetGraphicsRootShaderResourceView,hkSetGraphicsRootShaderResourceViewLate);
    attach(s_SetGraphicsRootUnorderedAccessView,hkSetGraphicsRootUnorderedAccessView,hkSetGraphicsRootUnorderedAccessViewLate);
    return result;
}
static LONG DetachBridgeGraphicsArgumentHooks(bool late)
{
    if (!(late ? bridgeGraphicsLateAttached : bridgeGraphicsEarlyAttached)) return NO_ERROR;
    LONG result = NO_ERROR;
    auto detach = [&](auto& hooks, auto early, auto delayed) {
        auto& target = late ? hooks.o_lateHook : hooks.o_earlyHook;
        const LONG next = target ? DetourDetach(reinterpret_cast<PVOID*>(&target),
            reinterpret_cast<PVOID>(late ? delayed : early)) : ERROR_INVALID_PARAMETER;
        if (result == NO_ERROR) result = next;
    };
    detach(s_SetGraphicsRootDescriptorTable,hkSetGraphicsRootDescriptorTable,hkSetGraphicsRootDescriptorTableLate);
    detach(s_SetGraphicsRoot32BitConstant,hkSetGraphicsRoot32BitConstant,hkSetGraphicsRoot32BitConstantLate);
    detach(s_SetGraphicsRoot32BitConstants,hkSetGraphicsRoot32BitConstants,hkSetGraphicsRoot32BitConstantsLate);
    detach(s_SetGraphicsRootConstantBufferView,hkSetGraphicsRootConstantBufferView,hkSetGraphicsRootConstantBufferViewLate);
    detach(s_SetGraphicsRootShaderResourceView,hkSetGraphicsRootShaderResourceView,hkSetGraphicsRootShaderResourceViewLate);
    detach(s_SetGraphicsRootUnorderedAccessView,hkSetGraphicsRootUnorderedAccessView,hkSetGraphicsRootUnorderedAccessViewLate);
    return result;
}
static void UnhookBridgeGraphicsArguments()
{
    if (!bridgeGraphicsEarlyAttached && !bridgeGraphicsLateAttached) return;
    DetourTransactionBegin(); DetourUpdateThread(GetCurrentThread());
    // Reverse installation order also supports nested early/late decorators.
    const LONG late = DetachBridgeGraphicsArgumentHooks(true), early = DetachBridgeGraphicsArgumentHooks(false);
    LONG result = late != NO_ERROR ? late : early;
    if (result != NO_ERROR) DetourTransactionAbort(); else result = DetourTransactionCommit();
    if (result == NO_ERROR) { ClearBridgeGraphicsArgumentHooks(false); ClearBridgeGraphicsArgumentHooks(true); }
    else LOG_ERROR("Failed to unhook bridge graphics argument methods, error: {:X}", result);
}

void D3D12Hooks::HookToCommandListLate(ID3D12GraphicsCommandList* commandList)
{
    if (s_SetComputeRootSignature.o_lateHook || s_SetGraphicsRootSignature.o_lateHook)
        return;

    // Get the vtable pointer
    PVOID* pVTable = *(PVOID**) commandList;

    const bool restoreComputeSignature = gNrdBridgeDeviceWrappers || Config::Instance()->RestoreComputeSignature.value_or_default();
    const bool restoreGraphicSignature = gNrdBridgeDeviceWrappers || Config::Instance()->RestoreGraphicSignature.value_or_default();
    const bool extendedRestoreSignature = gNrdBridgeDeviceWrappers || Config::Instance()->ExtendedStateRestore.value_or_default();

    s_SetPipelineState.o_lateHook = (PFN_SetPipelineState) pVTable[25];
    s_SetDescriptorHeaps.o_lateHook = (PFN_SetDescriptorHeaps) pVTable[28];
    s_SetComputeRootSignature.o_lateHook = (PFN_SetComputeRootSignature) pVTable[29];
    s_SetGraphicsRootSignature.o_lateHook = (PFN_SetGraphicsRootSignature) pVTable[30];
    s_SetComputeRootDescriptorTable.o_lateHook = (PFN_SetComputeRootDescriptorTable) pVTable[31];
    s_SetComputeRoot32BitConstant.o_lateHook = (PFN_SetComputeRoot32BitConstant) pVTable[33];
    s_SetComputeRoot32BitConstants.o_lateHook = (PFN_SetComputeRoot32BitConstants) pVTable[35];
    s_SetComputeRootConstantBufferView.o_lateHook = (PFN_SetComputeRootConstantBufferView) pVTable[37];
    s_SetComputeRootShaderResourceView.o_lateHook = (PFN_SetComputeRootShaderResourceView) pVTable[39];
    s_SetComputeRootUnorderedAccessView.o_lateHook = (PFN_SetComputeRootUnorderedAccessView) pVTable[41];
    ReadBridgeGraphicsArgumentHooks(pVTable,true);

    if (s_SetPipelineState.o_lateHook || s_SetDescriptorHeaps.o_lateHook || s_SetComputeRootSignature.o_lateHook ||
        s_SetGraphicsRootSignature.o_lateHook || s_SetComputeRootDescriptorTable.o_lateHook ||
        s_SetComputeRoot32BitConstant.o_lateHook || s_SetComputeRoot32BitConstants.o_lateHook ||
        s_SetComputeRootConstantBufferView.o_lateHook || s_SetComputeRootShaderResourceView.o_lateHook ||
        s_SetComputeRootUnorderedAccessView.o_lateHook)
    {
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        LONG bridgeGraphicsResult = NO_ERROR;
        // Common
        if (extendedRestoreSignature)
        {
            if (s_SetPipelineState.o_lateHook != nullptr)
                DetourAttach(&(PVOID&) s_SetPipelineState.o_lateHook, hkSetPipelineStateLate);

            if (s_SetDescriptorHeaps.o_lateHook != nullptr)
                DetourAttach(&(PVOID&) s_SetDescriptorHeaps.o_lateHook, hkSetDescriptorHeapsLate);
        }

        if (restoreComputeSignature)
        {
            if (s_SetComputeRootSignature.o_lateHook != nullptr)
                DetourAttach(&(PVOID&) s_SetComputeRootSignature.o_lateHook, hkSetComputeRootSignatureLate);

            if (extendedRestoreSignature)
            {

                if (s_SetComputeRootDescriptorTable.o_lateHook != nullptr)
                {
                    DetourAttach(&(PVOID&) s_SetComputeRootDescriptorTable.o_lateHook,
                                 hkSetComputeRootDescriptorTableLate);
                }

                if (s_SetComputeRoot32BitConstant.o_lateHook != nullptr)
                {
                    DetourAttach(&(PVOID&) s_SetComputeRoot32BitConstant.o_lateHook, hkSetComputeRoot32BitConstantLate);
                }

                if (s_SetComputeRoot32BitConstants.o_lateHook != nullptr)
                {
                    DetourAttach(&(PVOID&) s_SetComputeRoot32BitConstants.o_lateHook,
                                 hkSetComputeRoot32BitConstantsLate);
                }

                if (s_SetComputeRootConstantBufferView.o_lateHook != nullptr)
                {
                    DetourAttach(&(PVOID&) s_SetComputeRootConstantBufferView.o_lateHook,
                                 hkSetComputeRootConstantBufferViewLate);
                }

                if (s_SetComputeRootShaderResourceView.o_lateHook != nullptr)
                {
                    DetourAttach(&(PVOID&) s_SetComputeRootShaderResourceView.o_lateHook,
                                 hkSetComputeRootShaderResourceViewLate);
                }

                if (s_SetComputeRootUnorderedAccessView.o_lateHook != nullptr)
                {
                    DetourAttach(&(PVOID&) s_SetComputeRootUnorderedAccessView.o_lateHook,
                                 hkSetComputeRootUnorderedAccessViewLate);
                }
            }
        }

        if (restoreGraphicSignature)
        {
            if (s_SetGraphicsRootSignature.o_lateHook != nullptr)
                DetourAttach(&(PVOID&) s_SetGraphicsRootSignature.o_lateHook, hkSetGraphicsRootSignatureLate);

            if (extendedRestoreSignature && gNrdBridgeDeviceWrappers)
                bridgeGraphicsResult = AttachBridgeGraphicsArgumentHooks(true);
        }

        LONG detourResult = bridgeGraphicsResult;
        if (detourResult != NO_ERROR) DetourTransactionAbort(); else detourResult = DetourTransactionCommit();
        if (detourResult == NO_ERROR)
        {
            bridgeGraphicsLateAttached = gNrdBridgeDeviceWrappers;
            LOG_DEBUG("Hooked RootSignature functions Late");
        }
        else
        {
            s_SetPipelineState.o_lateHook = nullptr;
            s_SetDescriptorHeaps.o_lateHook = nullptr;
            s_SetComputeRootSignature.o_lateHook = nullptr;
            s_SetGraphicsRootSignature.o_lateHook = nullptr;
            s_SetComputeRootDescriptorTable.o_lateHook = nullptr;
            s_SetComputeRoot32BitConstant.o_lateHook = nullptr;
            s_SetComputeRoot32BitConstants.o_lateHook = nullptr;
            s_SetComputeRootConstantBufferView.o_lateHook = nullptr;
            s_SetComputeRootShaderResourceView.o_lateHook = nullptr;
            s_SetComputeRootUnorderedAccessView.o_lateHook = nullptr;

            ClearBridgeGraphicsArgumentHooks(true);
            LOG_WARN("Hooking RootSignature Late failed");
        }
    }
    else
    {
        LOG_WARN("Late hooks into RootSignature are nullptr");
    }
}

static void HookToCommandList(ID3D12Device* InDevice)
{
    if (s_SetComputeRootSignature.o_earlyHook != nullptr || s_SetGraphicsRootSignature.o_earlyHook != nullptr)
        return;

    ID3D12GraphicsCommandList* commandList = nullptr;
    ID3D12CommandAllocator* commandAllocator = nullptr;

    if (InDevice->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&commandAllocator)) == S_OK)
    {
        if (InDevice->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, commandAllocator, nullptr,
                                        IID_PPV_ARGS(&commandList)) == S_OK)
        {
            // Get the vtable pointer
            PVOID* pVTable = *(PVOID**) commandList;

            const bool extendedRestoreSignature = gNrdBridgeDeviceWrappers || Config::Instance()->ExtendedStateRestore.value_or_default();

            s_SetPipelineState.o_earlyHook = (PFN_SetPipelineState) pVTable[25];
            s_SetDescriptorHeaps.o_earlyHook = (PFN_SetDescriptorHeaps) pVTable[28];
            s_SetComputeRootSignature.o_earlyHook = (PFN_SetComputeRootSignature) pVTable[29];
            s_SetGraphicsRootSignature.o_earlyHook = (PFN_SetGraphicsRootSignature) pVTable[30];
            s_SetComputeRootDescriptorTable.o_earlyHook = (PFN_SetComputeRootDescriptorTable) pVTable[31];
            s_SetComputeRoot32BitConstant.o_earlyHook = (PFN_SetComputeRoot32BitConstant) pVTable[33];
            s_SetComputeRoot32BitConstants.o_earlyHook = (PFN_SetComputeRoot32BitConstants) pVTable[35];
            s_SetComputeRootConstantBufferView.o_earlyHook = (PFN_SetComputeRootConstantBufferView) pVTable[37];
            s_SetComputeRootShaderResourceView.o_earlyHook = (PFN_SetComputeRootShaderResourceView) pVTable[39];
            s_SetComputeRootUnorderedAccessView.o_earlyHook = (PFN_SetComputeRootUnorderedAccessView) pVTable[41];
            ReadBridgeGraphicsArgumentHooks(pVTable,false);

            if (s_SetPipelineState.o_earlyHook || s_SetDescriptorHeaps.o_earlyHook ||
                s_SetComputeRootSignature.o_earlyHook || s_SetGraphicsRootSignature.o_earlyHook ||
                s_SetComputeRootDescriptorTable.o_earlyHook || s_SetComputeRoot32BitConstant.o_earlyHook ||
                s_SetComputeRoot32BitConstants.o_earlyHook || s_SetComputeRootConstantBufferView.o_earlyHook ||
                s_SetComputeRootShaderResourceView.o_earlyHook || s_SetComputeRootUnorderedAccessView.o_earlyHook)
            {
                DetourTransactionBegin();
                DetourUpdateThread(GetCurrentThread());

                if (s_SetPipelineState.o_earlyHook != nullptr && extendedRestoreSignature)
                    DetourAttach(&(PVOID&) s_SetPipelineState.o_earlyHook, hkSetPipelineState);

                if (s_SetDescriptorHeaps.o_earlyHook != nullptr && (extendedRestoreSignature || gSurveyDeviceWrappers))
                    DetourAttach(&(PVOID&) s_SetDescriptorHeaps.o_earlyHook, gSurveyDeviceWrappers ? hkSurveySetDescriptorHeaps : hkSetDescriptorHeaps);

                if (s_SetComputeRootSignature.o_earlyHook != nullptr)
                    DetourAttach(&(PVOID&) s_SetComputeRootSignature.o_earlyHook, gSurveyDeviceWrappers ? hkSurveySetComputeRootSignature : hkSetComputeRootSignature);

                if (s_SetGraphicsRootSignature.o_earlyHook != nullptr)
                    DetourAttach(&(PVOID&) s_SetGraphicsRootSignature.o_earlyHook, gSurveyDeviceWrappers ? hkSurveySetGraphicsRootSignature : hkSetGraphicsRootSignature);

                if (s_SetComputeRootDescriptorTable.o_earlyHook != nullptr && extendedRestoreSignature)
                    DetourAttach(&(PVOID&) s_SetComputeRootDescriptorTable.o_earlyHook,
                                 hkSetComputeRootDescriptorTable);

                if (s_SetComputeRoot32BitConstant.o_earlyHook != nullptr && extendedRestoreSignature)
                    DetourAttach(&(PVOID&) s_SetComputeRoot32BitConstant.o_earlyHook, hkSetComputeRoot32BitConstant);

                if (s_SetComputeRoot32BitConstants.o_earlyHook != nullptr && extendedRestoreSignature)
                    DetourAttach(&(PVOID&) s_SetComputeRoot32BitConstants.o_earlyHook, hkSetComputeRoot32BitConstants);

                if (s_SetComputeRootConstantBufferView.o_earlyHook != nullptr && (extendedRestoreSignature || gSurveyDeviceWrappers))
                {
                    DetourAttach(&(PVOID&) s_SetComputeRootConstantBufferView.o_earlyHook,
                                 gSurveyDeviceWrappers ? hkSurveySetComputeRootConstantBufferView : hkSetComputeRootConstantBufferView);
                }

                if (s_SetComputeRootShaderResourceView.o_earlyHook != nullptr && (extendedRestoreSignature || gSurveyDeviceWrappers))
                {
                    DetourAttach(&(PVOID&) s_SetComputeRootShaderResourceView.o_earlyHook,
                                 gSurveyDeviceWrappers ? hkSurveySetComputeRootShaderResourceView : hkSetComputeRootShaderResourceView);
                }

                if (s_SetComputeRootUnorderedAccessView.o_earlyHook != nullptr && (extendedRestoreSignature || gSurveyDeviceWrappers))
                {
                    DetourAttach(&(PVOID&) s_SetComputeRootUnorderedAccessView.o_earlyHook,
                                 gSurveyDeviceWrappers ? hkSurveySetComputeRootUnorderedAccessView : hkSetComputeRootUnorderedAccessView);
                }

                LONG detourResult = AttachBridgeGraphicsArgumentHooks(false);
                if (detourResult != NO_ERROR) DetourTransactionAbort(); else detourResult = DetourTransactionCommit();
                if (detourResult == NO_ERROR)
                {
                    bridgeGraphicsEarlyAttached = gNrdBridgeDeviceWrappers;
                    LOG_DEBUG("Hooked RootSignature functions");
                }
                else
                {
                    s_SetPipelineState.o_earlyHook = nullptr;
                    s_SetDescriptorHeaps.o_earlyHook = nullptr;
                    s_SetComputeRootSignature.o_earlyHook = nullptr;
                    s_SetGraphicsRootSignature.o_earlyHook = nullptr;
                    s_SetComputeRootDescriptorTable.o_earlyHook = nullptr;
                    s_SetComputeRoot32BitConstant.o_earlyHook = nullptr;
                    s_SetComputeRoot32BitConstants.o_earlyHook = nullptr;
                    s_SetComputeRootConstantBufferView.o_earlyHook = nullptr;
                    s_SetComputeRootShaderResourceView.o_earlyHook = nullptr;
                    s_SetComputeRootUnorderedAccessView.o_earlyHook = nullptr;

                    ClearBridgeGraphicsArgumentHooks(false);
                    LOG_WARN("Hooking RootSignature failed");
                }
            }
            else
            {
                LOG_WARN("Early hooks into RootSignature are nullptr");
            }

            commandList->Close();
            commandList->Release();
        }

        commandAllocator->Reset();
        commandAllocator->Release();
    }
}

static void UnhookAll()
{
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (s_SetComputeRootSignature.o_earlyHook != nullptr)
    {
        DetourDetach(&(PVOID&) s_SetComputeRootSignature.o_earlyHook, gSurveyDeviceWrappers ? hkSurveySetComputeRootSignature : hkSetComputeRootSignature);
        s_SetComputeRootSignature.o_earlyHook = nullptr;
    }

    if (s_SetGraphicsRootSignature.o_earlyHook != nullptr)
    {
        DetourDetach(&(PVOID&) s_SetGraphicsRootSignature.o_earlyHook, gSurveyDeviceWrappers ? hkSurveySetGraphicsRootSignature : hkSetGraphicsRootSignature);
        s_SetGraphicsRootSignature.o_earlyHook = nullptr;
    }
}

VALIDATE_HOOK(hkD3D12CreateDevice, D3d12Proxy::PFN_D3D12CreateDevice)
static HRESULT hkD3D12CreateDevice(IUnknown* pAdapter, D3D_FEATURE_LEVEL MinimumFeatureLevel, REFIID riid,
                                   void** ppDevice)
{
    if (FrameSurvey::Internal() || State::Instance().creatingD3DDevice)
        return o_D3D12CreateDevice(pAdapter, MinimumFeatureLevel, riid, ppDevice);

    LOG_DEBUG("Adapter: {:X}, Level: {:X}, Caller: {}", (size_t) pAdapter, (UINT) MinimumFeatureLevel,
              Util::WhoIsTheCaller(_ReturnAddress()));

#ifdef ENABLE_DEBUG_LAYER_DX12
    LOG_WARN("Debug layers active!");
    if (debugController == nullptr && D3D12GetDebugInterface(IID_PPV_ARGS(&debugController)) == S_OK)
    {
        debugController->EnableDebugLayer();

#ifdef ENABLE_GPU_VALIDATION
        LOG_WARN("GPU Based Validation active!");
        debugController->SetEnableGPUBasedValidation(TRUE);
#endif

        debugController->Release();
    }
#endif
    IdentifyGpu::updateD3d12Capabilities(o_D3D12CreateDevice);

    DXGI_ADAPTER_DESC desc {};
    std::wstring szName;
    bool nonPrimaryGpu = false;
    if (pAdapter != nullptr && MinimumFeatureLevel != D3D_FEATURE_LEVEL_1_0_CORE)
    {
        ScopedSkipSpoofingGlobal skipSpoofingGlobal {};

        if (((IDXGIAdapter*) pAdapter)->GetDesc(&desc) == S_OK)
        {
            szName = desc.Description;
            LOG_INFO("Adapter Desc: {}", wstring_to_string(szName));

            auto primaryGpu = IdentifyGpu::getPrimaryGpu();
            if (!IsEqualLUID(desc.AdapterLuid, primaryGpu.luid))
            {
                LOG_WARN("D3D12Device created with non-primary GPU");
                nonPrimaryGpu = true;
            }
        }
    }

    auto minLevel = MinimumFeatureLevel;
    if (Config::Instance()->SpoofFeatureLevel.value_or_default() && MinimumFeatureLevel != D3D_FEATURE_LEVEL_1_0_CORE)
    {
        LOG_INFO("Forcing feature level 0xb000 for new device");
        minLevel = D3D_FEATURE_LEVEL_11_0;
    }

    if (ppDevice == nullptr)
    {
        LOG_TRACE("ppDevice is nullptr");

        _creatingD3D12Device = true;
        ScopedCreatingD3DDevice skipCreatingD3DDevice {};
        auto result = o_D3D12CreateDevice(pAdapter, minLevel, riid, ppDevice);
        _creatingD3D12Device = false;

        return result;
    }

    HRESULT result;
    _creatingD3D12Device = true;
    if (desc.VendorId == VendorId::Intel)
    {
        ScopedSkipSpoofingGlobal skipSpoofingGlobal {};
        result = o_D3D12CreateDevice(pAdapter, minLevel, riid, ppDevice);
    }
    else
    {
        ScopedCreatingD3DDevice skipCreatingD3DDevice {};
        result = o_D3D12CreateDevice(pAdapter, minLevel, riid, ppDevice);
    }
    _creatingD3D12Device = false;

    LOG_DEBUG("o_D3D12CreateDevice result: {:X}", (UINT) result);

    if (result == S_OK && ppDevice != nullptr && MinimumFeatureLevel != D3D_FEATURE_LEVEL_1_0_CORE && !nonPrimaryGpu)
    {
        LOG_DEBUG("Device captured: {0:X}", (size_t) *ppDevice);
        State::Instance().currentD3D12Device = (ID3D12Device*) *ppDevice;

        if (desc.VendorId == VendorId::Intel && Config::Instance()->UESpoofIntelAtomics64.value_or_default())
        {
            IGDExtProxy::EnableAtomicSupport(State::Instance().currentD3D12Device);
            _intelD3D12Device = State::Instance().currentD3D12Device;
            _intelD3D12DeviceRefTarget = _intelD3D12Device->AddRef();

            if (o_D3D12DeviceRelease == nullptr)
                _intelD3D12Device->Release();
            else
                o_D3D12DeviceRelease(_intelD3D12Device);
        }

        // if (Config::Instance()->UESpoofIntelAtomics64.value_or_default())
        //     UnhookDevice();

        if (State::Instance().gameQuirks & GameQuirk::CreateSLOnThe2ndDevice)
        {
            static void* lastDevice = nullptr;

            if (lastDevice && lastDevice != *ppDevice && StreamlineProxy::IsD3D12Inited() &&
                StreamlineProxy::SetD3DDevice()(*ppDevice) == sl::Result::eOk)
            {
                auto reflexConst = sl::ReflexOptions {};
                reflexConst.mode = sl::ReflexMode::eLowLatency;
                reflexConst.useMarkersToOptimize = false;

                auto result = StreamlineProxy::ReflexSetOptions()(reflexConst);
                LOG_TRACE("ReflexSetOptions");
            }

            lastDevice = *ppDevice;
        }

        HookToDevice(State::Instance().currentD3D12Device);
        _d3d12Captured = true;

        State::Instance().d3d12Devices.push_back((ID3D12Device*) *ppDevice);

#ifdef ENABLE_DEBUG_LAYER_DX12
        if (infoQueue != nullptr)
            infoQueue->Release();

        if (infoQueue1 != nullptr)
            infoQueue1->Release();

        if (State::Instance().currentD3D12Device->QueryInterface(IID_PPV_ARGS(&infoQueue)) == S_OK)
        {
            LOG_DEBUG("infoQueue accuired");

            infoQueue->ClearRetrievalFilter();
            infoQueue->SetMuteDebugOutput(false);

            HRESULT res;
            res = infoQueue->SetBreakOnSeverity(D3D12_MESSAGE_SEVERITY_CORRUPTION, TRUE);
            // res = infoQueue->SetBreakOnSeverity(D3D12_MESSAGE_SEVERITY_ERROR, TRUE);
            // res = infoQueue->SetBreakOnSeverity(D3D12_MESSAGE_SEVERITY_WARNING, TRUE);

            if (infoQueue->QueryInterface(IID_PPV_ARGS(&infoQueue1)) == S_OK && infoQueue1 != nullptr)
            {
                LOG_DEBUG("infoQueue1 accuired, registering MessageCallback");
                res = infoQueue1->RegisterMessageCallback(D3D12DebugCallback, D3D12_MESSAGE_CALLBACK_FLAG_NONE, NULL,
                                                          NULL);
            }
        }
#endif
    }

    LOG_DEBUG("final result: {:X}", (UINT) result);
    return result;
}

VALIDATE_HOOK(hkCreateDevice, PFN_CreateDevice)
static HRESULT hkCreateDevice(ID3D12DeviceFactory* pFactory, IUnknown* pAdapter, D3D_FEATURE_LEVEL MinimumFeatureLevel,
                              REFIID riid, void** ppDevice)
{
    LOG_DEBUG("Adapter: {:X}, Level: {:X}, Caller: {}", (size_t) pAdapter, (UINT) MinimumFeatureLevel,
              Util::WhoIsTheCaller(_ReturnAddress()));

    if (_creatingD3D12Device || FrameSurvey::Internal() || State::Instance().creatingD3DDevice)
    {
        LOG_DEBUG("Calling from hkD3D12CreateDevice, calling original CreateDevice");
        return o_CreateDevice(pFactory, pAdapter, MinimumFeatureLevel, riid, ppDevice);
    }

#ifdef ENABLE_DEBUG_LAYER_DX12
    LOG_WARN("Debug layers active!");
    if (debugController == nullptr && D3D12GetDebugInterface(IID_PPV_ARGS(&debugController)) == S_OK)
    {
        debugController->EnableDebugLayer();

#ifdef ENABLE_GPU_VALIDATION
        LOG_WARN("GPU Based Validation active!");
        debugController->SetEnableGPUBasedValidation(TRUE);
#endif

        debugController->Release();
    }
#endif

    DXGI_ADAPTER_DESC desc {};
    std::wstring szName;
    if (pAdapter != nullptr && MinimumFeatureLevel != D3D_FEATURE_LEVEL_1_0_CORE)
    {
        ScopedSkipSpoofingGlobal skipSpoofingGlobal {};

        if (((IDXGIAdapter*) pAdapter)->GetDesc(&desc) == S_OK)
        {
            szName = desc.Description;
            LOG_INFO("Adapter Desc: {}", wstring_to_string(szName));

            auto primaryGpu = IdentifyGpu::getPrimaryGpu();
            if (!IsEqualLUID(desc.AdapterLuid, primaryGpu.luid))
                LOG_WARN("D3D12Device created with non-primary GPU");
        }
    }

    auto minLevel = MinimumFeatureLevel;
    if (Config::Instance()->SpoofFeatureLevel.value_or_default() && MinimumFeatureLevel != D3D_FEATURE_LEVEL_1_0_CORE)
    {
        LOG_INFO("Forcing feature level 0xb000 for new device");
        minLevel = D3D_FEATURE_LEVEL_11_0;
    }

    if (ppDevice == nullptr)
    {
        LOG_ERROR("ppDevice is nullptr");
        ScopedCreatingD3DDevice skipCreatingD3DDevice {};
        return o_CreateDevice(pFactory, pAdapter, minLevel, riid, ppDevice);
    }

    HRESULT result;
    if (desc.VendorId == VendorId::Intel)
    {
        ScopedSkipSpoofingGlobal skipSpoofingGlobal {};
        ScopedCreatingD3DDevice skipCreatingD3DDevice {};
        result = o_CreateDevice(pFactory, pAdapter, minLevel, riid, ppDevice);
    }
    else
    {
        ScopedCreatingD3DDevice skipCreatingD3DDevice {};
        result = o_CreateDevice(pFactory, pAdapter, minLevel, riid, ppDevice);
    }

    LOG_DEBUG("o_D3D12CreateDevice result: {:X}", (UINT) result);

    if (result == S_OK && ppDevice != nullptr && MinimumFeatureLevel != D3D_FEATURE_LEVEL_1_0_CORE)
    {
        LOG_DEBUG("Device captured: {0:X}", (size_t) *ppDevice);
        State::Instance().currentD3D12Device = (ID3D12Device*) *ppDevice;

        if (desc.VendorId == VendorId::Intel && Config::Instance()->UESpoofIntelAtomics64.value_or_default())
        {
            IGDExtProxy::EnableAtomicSupport(State::Instance().currentD3D12Device);
            _intelD3D12Device = State::Instance().currentD3D12Device;
            _intelD3D12DeviceRefTarget = _intelD3D12Device->AddRef();

            if (o_D3D12DeviceRelease == nullptr)
                _intelD3D12Device->Release();
            else
                o_D3D12DeviceRelease(_intelD3D12Device);
        }

        HookToDevice(State::Instance().currentD3D12Device);
        _d3d12Captured = true;

        State::Instance().d3d12Devices.push_back((ID3D12Device*) *ppDevice);

#ifdef ENABLE_DEBUG_LAYER_DX12
        if (infoQueue != nullptr)
            infoQueue->Release();

        if (infoQueue1 != nullptr)
            infoQueue1->Release();

        if (State::Instance().currentD3D12Device->QueryInterface(IID_PPV_ARGS(&infoQueue)) == S_OK)
        {
            LOG_DEBUG("infoQueue accuired");

            infoQueue->ClearRetrievalFilter();
            infoQueue->SetMuteDebugOutput(false);

            HRESULT res;
            res = infoQueue->SetBreakOnSeverity(D3D12_MESSAGE_SEVERITY_CORRUPTION, TRUE);
            // res = infoQueue->SetBreakOnSeverity(D3D12_MESSAGE_SEVERITY_ERROR, TRUE);
            // res = infoQueue->SetBreakOnSeverity(D3D12_MESSAGE_SEVERITY_WARNING, TRUE);

            if (infoQueue->QueryInterface(IID_PPV_ARGS(&infoQueue1)) == S_OK && infoQueue1 != nullptr)
            {
                LOG_DEBUG("infoQueue1 accuired, registering MessageCallback");
                res = infoQueue1->RegisterMessageCallback(D3D12DebugCallback, D3D12_MESSAGE_CALLBACK_IGNORE_FILTERS,
                                                          NULL, NULL);
            }
        }
#endif
    }

    LOG_DEBUG("final result: {:X}", (UINT) result);
    return result;
}

VALIDATE_HOOK(hkD3D12SerializeRootSignature, D3d12Proxy::PFN_D3D12SerializeRootSignature)
static HRESULT hkD3D12SerializeRootSignature(const D3D12_ROOT_SIGNATURE_DESC* pRootSignature,
                                             D3D_ROOT_SIGNATURE_VERSION Version, ID3DBlob** ppBlob,
                                             ID3DBlob** ppErrorBlob)
{
    if (pRootSignature == nullptr)
        return o_D3D12SerializeRootSignature(pRootSignature, Version, ppBlob, ppErrorBlob);

    auto localRootSignature = *pRootSignature;
    std::vector<D3D12_STATIC_SAMPLER_DESC> localSamplers;

    if (pRootSignature->NumStaticSamplers > 0)
    {
        localSamplers.assign(pRootSignature->pStaticSamplers,
                             pRootSignature->pStaticSamplers + pRootSignature->NumStaticSamplers);
    }

    for (auto& sampler : localSamplers)
    {
        ApplySamplerOverrides(sampler);
    }

    localRootSignature.pStaticSamplers = localSamplers.data();

    return o_D3D12SerializeRootSignature(&localRootSignature, Version, ppBlob, ppErrorBlob);
}

VALIDATE_HOOK(hkD3D12SerializeVersionedRootSignature, D3d12Proxy::PFN_D3D12SerializeVersionedRootSignature)
static HRESULT hkD3D12SerializeVersionedRootSignature(const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* pRootSignature,
                                                      ID3DBlob** ppBlob, ID3DBlob** ppErrorBlob)
{
    if (pRootSignature == nullptr)
        return o_D3D12SerializeVersionedRootSignature(pRootSignature, ppBlob, ppErrorBlob);

    auto localVersionedRootSignature = *pRootSignature;
    std::vector<D3D12_STATIC_SAMPLER_DESC> localSamplers;
    std::vector<D3D12_STATIC_SAMPLER_DESC1> localSamplers1;

    if (pRootSignature->Version == D3D_ROOT_SIGNATURE_VERSION_1_0)
    {
        if (pRootSignature->Desc_1_0.NumStaticSamplers > 0)
        {
            localSamplers.assign(pRootSignature->Desc_1_0.pStaticSamplers,
                                 pRootSignature->Desc_1_0.pStaticSamplers + pRootSignature->Desc_1_0.NumStaticSamplers);
        }

        for (auto& sampler : localSamplers)
        {
            ApplySamplerOverrides(sampler);
        }

        localVersionedRootSignature.Desc_1_0.pStaticSamplers = localSamplers.data();
    }
    else if (pRootSignature->Version == D3D_ROOT_SIGNATURE_VERSION_1_1)
    {
        if (pRootSignature->Desc_1_1.NumStaticSamplers > 0)
        {
            localSamplers.assign(pRootSignature->Desc_1_1.pStaticSamplers,
                                 pRootSignature->Desc_1_1.pStaticSamplers + pRootSignature->Desc_1_1.NumStaticSamplers);
        }

        for (auto& sampler : localSamplers)
        {
            ApplySamplerOverrides(sampler);
        }

        localVersionedRootSignature.Desc_1_1.pStaticSamplers = localSamplers.data();
    }
    else if (pRootSignature->Version == D3D_ROOT_SIGNATURE_VERSION_1_2)
    {
        if (pRootSignature->Desc_1_2.NumStaticSamplers > 0)
        {
            localSamplers1.assign(pRootSignature->Desc_1_2.pStaticSamplers,
                                  pRootSignature->Desc_1_2.pStaticSamplers +
                                      pRootSignature->Desc_1_2.NumStaticSamplers);
        }

        for (auto& sampler : localSamplers1)
        {
            ApplySamplerOverrides(sampler);
        }

        localVersionedRootSignature.Desc_1_2.pStaticSamplers = localSamplers1.data();
    }

    auto result = o_D3D12SerializeVersionedRootSignature(&localVersionedRootSignature, ppBlob, ppErrorBlob);

    return result;
}

VALIDATE_HOOK(hkD3D12DeviceRelease, PFN_Release)
static ULONG hkD3D12DeviceRelease(IUnknown* device)
{
    if (Config::Instance()->UESpoofIntelAtomics64.value_or_default() && device == _intelD3D12Device)
    {
        auto refCount = device->AddRef();

        if (refCount == _intelD3D12DeviceRefTarget)
        {
            LOG_INFO("Destroying IGDExt context!");
            _intelD3D12Device = nullptr;
            IGDExtProxy::DestroyContext();
        }

        o_D3D12DeviceRelease(device);
    }
    else if (State::Instance().currentD3D12Device == device)
    {
        device->AddRef();
        auto refCount = o_D3D12DeviceRelease(device);

        if (refCount == 1)
        {
            LOG_DEBUG("Set State::Instance().currentD3D12Device = nullptr, was: {:X}", (size_t) device);
            State::Instance().currentD3D12Device = nullptr;
        }
    }

    auto result = o_D3D12DeviceRelease(device);
    return result;
}

VALIDATE_HOOK(hkCheckFeatureSupport, PFN_CheckFeatureSupport)
static HRESULT hkCheckFeatureSupport(ID3D12Device* device, D3D12_FEATURE Feature, void* pFeatureSupportData,
                                     UINT FeatureSupportDataSize)
{
    auto result = o_CheckFeatureSupport(device, Feature, pFeatureSupportData, FeatureSupportDataSize);

    if (Config::Instance()->UESpoofIntelAtomics64.value_or_default() && Feature == D3D12_FEATURE_D3D12_OPTIONS9 &&
        device == State::Instance().currentD3D12Device)
    {
        auto featureSupport = (D3D12_FEATURE_DATA_D3D12_OPTIONS9*) pFeatureSupportData;
        LOG_INFO("Spoofing AtomicInt64OnTypedResourceSupported {} -> 1",
                 featureSupport->AtomicInt64OnTypedResourceSupported);

        featureSupport->AtomicInt64OnTypedResourceSupported = 1;
    }

    return result;
}

VALIDATE_HOOK(hkCreateCommittedResource, PFN_CreateCommittedResource)
static HRESULT hkCreateCommittedResource(ID3D12Device* device, const D3D12_HEAP_PROPERTIES* pHeapProperties,
                                         D3D12_HEAP_FLAGS HeapFlags, const D3D12_RESOURCE_DESC* pDesc,
                                         D3D12_RESOURCE_STATES InitialResourceState,
                                         const D3D12_CLEAR_VALUE* pOptimizedClearValue, REFIID riidResource,
                                         void** ppvResource)
{
    if (!_skipCommitedResource)
    {
        D3D12_RESOURCE_DESC localDesc = {};
        memcpy(&localDesc, pDesc, sizeof(D3D12_RESOURCE_DESC));
        auto ueDesc = reinterpret_cast<UE_D3D12_RESOURCE_DESC*>(&pDesc);

        if (Config::Instance()->UESpoofIntelAtomics64.value_or_default() && ueDesc != nullptr &&
            ueDesc->bRequires64BitAtomicSupport)
        {
            _skipCommitedResource = true;
            auto result =
                IGDExtProxy::CreateCommitedResource(pHeapProperties, HeapFlags, &localDesc, InitialResourceState,
                                                    pOptimizedClearValue, riidResource, ppvResource);

            LOG_DEBUG("IGDExtProxy::hkCreateCommittedResource result: {:X}", (UINT) result);
            _skipCommitedResource = false;

            return result;
        }
    }

    return o_CreateCommittedResource(device, pHeapProperties, HeapFlags, pDesc, InitialResourceState,
                                     pOptimizedClearValue, riidResource, ppvResource);
}

static HRESULT hkSurveyCreateCommittedResource(ID3D12Device* device, const D3D12_HEAP_PROPERTIES* pHeapProperties,
                                         D3D12_HEAP_FLAGS HeapFlags, const D3D12_RESOURCE_DESC* pDesc,
                                         D3D12_RESOURCE_STATES InitialResourceState,
                                         const D3D12_CLEAR_VALUE* pOptimizedClearValue, REFIID riidResource,
                                         void** ppvResource)
{
    const auto result = hkCreateCommittedResource(device,pHeapProperties,HeapFlags,pDesc,InitialResourceState,pOptimizedClearValue,riidResource,ppvResource);
    if (SUCCEEDED(result) && ppvResource && *ppvResource) FrameSurvey::ResourceCreated(static_cast<ID3D12Resource*>(*ppvResource),InitialResourceState);
    return result;
}


static bool skipPlacedResource = false;

VALIDATE_HOOK(hkCreatePlacedResource, PFN_CreatePlacedResource)
static HRESULT hkCreatePlacedResource(ID3D12Device* device, ID3D12Heap* pHeap, UINT64 HeapOffset,
                                      const D3D12_RESOURCE_DESC* pDesc, D3D12_RESOURCE_STATES InitialState,
                                      const D3D12_CLEAR_VALUE* pOptimizedClearValue, REFIID riid, void** ppvResource)
{
    if (!skipPlacedResource)
    {
        D3D12_RESOURCE_DESC localDesc = {};
        memcpy(&localDesc, pDesc, sizeof(D3D12_RESOURCE_DESC));
        auto ueDesc = reinterpret_cast<UE_D3D12_RESOURCE_DESC*>(&pDesc);

        if (Config::Instance()->UESpoofIntelAtomics64.value_or_default() && ueDesc != nullptr &&
            ueDesc->bRequires64BitAtomicSupport)
        {
            skipPlacedResource = true;
            auto result = IGDExtProxy::CreatePlacedResource(pHeap, HeapOffset, &localDesc, InitialState,
                                                            pOptimizedClearValue, riid, ppvResource);
            LOG_DEBUG("IGDExtProxy::hkCreatePlacedResource result: {:X}", (UINT) result);
            skipPlacedResource = false;

            return result;
        }
    }

    return o_CreatePlacedResource(device, pHeap, HeapOffset, pDesc, InitialState, pOptimizedClearValue, riid,
                                  ppvResource);
}

static HRESULT hkSurveyCreatePlacedResource(ID3D12Device* device, ID3D12Heap* pHeap, UINT64 HeapOffset,
                                      const D3D12_RESOURCE_DESC* pDesc, D3D12_RESOURCE_STATES InitialState,
                                      const D3D12_CLEAR_VALUE* pOptimizedClearValue, REFIID riid, void** ppvResource)
{
    const auto result = hkCreatePlacedResource(device,pHeap,HeapOffset,pDesc,InitialState,pOptimizedClearValue,riid,ppvResource);
    if (SUCCEEDED(result) && ppvResource && *ppvResource) FrameSurvey::ResourceCreated(static_cast<ID3D12Resource*>(*ppvResource),InitialState,pHeap,HeapOffset);
    return result;
}


VALIDATE_HOOK(hkSetResidencyPriority, PFN_SetResidencyPriority)
static HRESULT hkSetResidencyPriority(ID3D12Device1* This, UINT NumObjects, ID3D12Pageable* const* ppObjects,
                                      const D3D12_RESIDENCY_PRIORITY* pPriorities)
{
    auto result = o_SetResidencyPriority(This, NumObjects, ppObjects, pPriorities);

    // HACK: AMD Windows 25.20 drivers fail in xess/xefg with E_INVALIDARG
    // This hack allows them to work without the priority being actually set
    if (FAILED(result))
    {
        auto callerModule = Util::GetCallerModule(_ReturnAddress());
        auto xefgModule = XeFGProxy::Module();
        auto xessModule = XeSSProxy::Module();

        if (callerModule == xefgModule || callerModule == xessModule)
        {
            LOG_WARN("SetResidencyPriority failed, faking success for xess/xefg");
            result = S_OK;
        }
    }

    return result;
}

/*
The Golden Rule of x64 Struct Returns
If a Windows x64 function returns a struct larger than 8 bytes (and isn't a vector intrinsic):

Input: The caller allocates stack memory and passes a pointer to it as a hidden argument.

Static Function: RCX = Hidden Ptr, RDX = Arg1

Member Function: RCX = this, RDX = Hidden Ptr, R8 = Arg1

Output: The function must return that same hidden pointer in RAX.

Why Agility SDK crashed but legacy didn't: The Agility SDK is compiled with newer MSVC optimizations that strictly
enforce the "Return in RAX" rule for chained calls. The legacy DLL likely had some wiggle room or didn't immediately
dereference RAX after the call.
*/
// Not using validation because of this hooks special case
static D3D12_RESOURCE_ALLOCATION_INFO* STDMETHODCALLTYPE
hkGetResourceAllocationInfo(ID3D12Device* device, D3D12_RESOURCE_ALLOCATION_INFO* pResult, UINT visibleMask,
                            UINT numResourceDescs, D3D12_RESOURCE_DESC* pResourceDescs)
{
    if (!_skipGetResourceAllocationInfo)
    {
        auto ueDesc = reinterpret_cast<UE_D3D12_RESOURCE_DESC*>(pResourceDescs);

        if (Config::Instance()->UESpoofIntelAtomics64.value_or_default() && ueDesc != nullptr &&
            ueDesc->bRequires64BitAtomicSupport)
        {
            _skipGetResourceAllocationInfo = true;
            auto result = IGDExtProxy::GetResourceAllocationInfo(visibleMask, numResourceDescs, pResourceDescs);
            LOG_DEBUG("IGDExtProxy::GetResourceAllocationInfo result: SizeInBytes={}", result.SizeInBytes);
            _skipGetResourceAllocationInfo = false;
            *pResult = result;
            return pResult;
        }
    }

    pResult->Alignment = 0;
    pResult->SizeInBytes = 0;
    o_GetResourceAllocationInfo(device, pResult, visibleMask, numResourceDescs, pResourceDescs);
    return pResult;
}

VALIDATE_HOOK(hkCreateSampler, PFN_CreateSampler)
static void hkCreateSampler(ID3D12Device* device, const D3D12_SAMPLER_DESC* pDesc,
                            D3D12_CPU_DESCRIPTOR_HANDLE DestDescriptor)
{
    if (pDesc == nullptr || device == nullptr)
        return;

    D3D12_SAMPLER_DESC newDesc = *pDesc;

    if (Config::Instance()->AnisotropyOverride.has_value())
    {
        LOG_DEBUG("Overriding {2:X} to anisotropic filtering {0} -> {1}", pDesc->MaxAnisotropy,
                  Config::Instance()->AnisotropyOverride.value(), (UINT) newDesc.Filter);

        newDesc.Filter = UpgradeToAF(pDesc->Filter);
        newDesc.MaxAnisotropy = Config::Instance()->AnisotropyOverride.value();
    }
    else
    {
        newDesc.Filter = pDesc->Filter;
        newDesc.MaxAnisotropy = pDesc->MaxAnisotropy;
    }

    if ((newDesc.MipLODBias < 0.0f && newDesc.MinLOD != newDesc.MaxLOD) ||
        Config::Instance()->MipmapBiasOverrideAll.value_or_default())
    {
        if (Config::Instance()->MipmapBiasOverride.has_value())
        {
            LOG_DEBUG("Overriding mipmap bias {0} -> {1}", pDesc->MipLODBias,
                      Config::Instance()->MipmapBiasOverride.value());

            if (Config::Instance()->MipmapBiasFixedOverride.value_or_default())
                newDesc.MipLODBias = Config::Instance()->MipmapBiasOverride.value();
            else if (Config::Instance()->MipmapBiasScaleOverride.value_or_default())
                newDesc.MipLODBias = newDesc.MipLODBias * Config::Instance()->MipmapBiasOverride.value();
            else
                newDesc.MipLODBias = newDesc.MipLODBias + Config::Instance()->MipmapBiasOverride.value();
        }

        if (State::Instance().lastMipBiasMax < newDesc.MipLODBias)
            State::Instance().lastMipBiasMax = newDesc.MipLODBias;

        if (State::Instance().lastMipBias > newDesc.MipLODBias)
            State::Instance().lastMipBias = newDesc.MipLODBias;
    }

    return o_CreateSampler(device, &newDesc, DestDescriptor);
}

// The native Create caller owns its returned object. Normalize uncommon IID
// outputs with one short QI reference; release it after all metadata guards.
struct ReturnedRootInterface
{
    ID3D12RootSignature* root = nullptr;
    bool temporary = false;
    ReturnedRootInterface(void* output, REFIID iid)
    {
        if (!output) return;
        if (iid == __uuidof(ID3D12RootSignature)) root = static_cast<ID3D12RootSignature*>(output);
        else temporary = SUCCEEDED(static_cast<IUnknown*>(output)->QueryInterface(IID_PPV_ARGS(&root)));
    }
    ~ReturnedRootInterface() { if (temporary && root) root->Release(); }
    ReturnedRootInterface(const ReturnedRootInterface&) = delete;
    ReturnedRootInterface& operator=(const ReturnedRootInterface&) = delete;
};
static void PublishCreatedRootParameters(void* output, REFIID iid, UINT count) noexcept
{
    try
    {
        if (!output || (RootTrackerBirthsEnabled() && FrameSurvey::Internal())) return;
        ReturnedRootInterface returned(output,iid);
        if (!returned.root)
        {
            if (RootTrackerBirthsEnabled()) NrdBridgeNativeBirth::Detail::Fail("created root interface normalization failed");
            return;
        }
        NrdBridgeBirth::Token birth;
        if (RootTrackerBirthsEnabled())
        {
            if (!NrdBridgeNativeBirth::ObserveReleaseCoverage(returned.root) ||
                !NrdBridgeNativeBirth::ObserveReleaseCoverage(static_cast<IUnknown*>(output))) return;
            birth = NrdBridgeNativeBirth::Prepare(returned.root);
            if (!birth) return;
            const NativeRootParameterCount native{birth->InstanceStamp(),count,1};
            if (count > D3D12_MAX_ROOT_COST || FAILED(returned.root->SetPrivateData(RootParameterCountGuid,sizeof(native),&native)))
            { NrdBridgeNativeBirth::Detail::Fail("native root parameter count write failed"); return; }
            if (output != returned.root)
            {
                NrdBridgeNativeBirth::RetirementScope effects;
                if (!effects.Valid() || !NrdBridgeBirth::LinkAlias(birth->InstanceStamp(),output)) return;
            }
        }
        NrdBridgeBirth::CurrentGuard guard(birth,RootTrackerBirthsEnabled());
        if (RootTrackerBirthsEnabled() && (!guard.MatchesCurrent() || !NrdBridgeBirth::Healthy())) return;
        std::unique_lock lock(rootSigParameterCountMutex, std::defer_lock); LockRootTracker(lock);
        rootSigParameterCount.insert_or_assign(returned.root,count);
        if (RootTrackerBirthsEnabled()) rootSigBirths.insert_or_assign(returned.root,birth);
    }
    catch (...)
    {
        if (RootTrackerBirthsEnabled()) NrdBridgeNativeBirth::Detail::Fail("created root count metadata publication failed");
    }
}

VALIDATE_HOOK(hkCreateRootSignature, PFN_CreateRootSignature)
static HRESULT hkCreateRootSignature(ID3D12Device* device, UINT nodeMask, const void* pBlobWithRootSignature,
                                     SIZE_T blobLengthInBytes, REFIID riid, void** ppvRootSignature)
{
    if (!Config::Instance()->MipmapBiasOverride.has_value() && !Config::Instance()->AnisotropyOverride.has_value() &&
        !Config::Instance()->ExtendedStateRestore.value_or_default() && !gNrdBridgeDeviceWrappers)
    {
        return o_CreateRootSignature(device, nodeMask, pBlobWithRootSignature, blobLengthInBytes, riid,
                                     ppvRootSignature);
    }

    ID3D12VersionedRootSignatureDeserializer* deserializer = nullptr;
    auto result = D3d12Proxy::D3D12CreateVersionedRootSignatureDeserializer_()(
        pBlobWithRootSignature, blobLengthInBytes, IID_PPV_ARGS(&deserializer));

    // Deserialize the blob
    if (FAILED(result))
    {
        LOG_ERROR("Failed to create deserializer, error: {:X}", (UINT) result);
        return o_CreateRootSignature(device, nodeMask, pBlobWithRootSignature, blobLengthInBytes, riid,
                                     ppvRootSignature);
    }

    const D3D12_VERSIONED_ROOT_SIGNATURE_DESC* desc = deserializer->GetUnconvertedRootSignatureDesc();
    const UINT parameterCount = desc->Version == D3D_ROOT_SIGNATURE_VERSION_1_0 ? desc->Desc_1_0.NumParameters :
        desc->Version == D3D_ROOT_SIGNATURE_VERSION_1_1 ? desc->Desc_1_1.NumParameters :
        desc->Version == D3D_ROOT_SIGNATURE_VERSION_1_2 ? desc->Desc_1_2.NumParameters : 0;

    // Only ExtendedStateRestore is set, return early
    if (!Config::Instance()->MipmapBiasOverride.has_value() && !Config::Instance()->AnisotropyOverride.has_value())
    {
        auto result =
            o_CreateRootSignature(device, nodeMask, pBlobWithRootSignature, blobLengthInBytes, riid, ppvRootSignature);

        if (SUCCEEDED(result) && ppvRootSignature && *ppvRootSignature)
            PublishCreatedRootParameters(*ppvRootSignature,riid,parameterCount);

        deserializer->Release();
        return result;
    }

    // Create a modifiable copy
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC descCopy {};
    std::memcpy(&descCopy, desc, sizeof(D3D12_VERSIONED_ROOT_SIGNATURE_DESC));

    std::vector<D3D12_STATIC_SAMPLER_DESC> samplers;
    std::vector<D3D12_STATIC_SAMPLER_DESC1> samplers1;

    // Modify Samplers based on Version
    if (descCopy.Version == D3D_ROOT_SIGNATURE_VERSION_1_0)
    {
        if (descCopy.Desc_1_0.NumStaticSamplers > 0)
        {
            samplers.assign(descCopy.Desc_1_0.pStaticSamplers,
                            descCopy.Desc_1_0.pStaticSamplers + descCopy.Desc_1_0.NumStaticSamplers);

            for (auto& s : samplers)
                ApplySamplerOverrides(s);

            descCopy.Desc_1_0.pStaticSamplers = samplers.data();
        }
    }
    else if (descCopy.Version == D3D_ROOT_SIGNATURE_VERSION_1_1)
    {
        if (descCopy.Desc_1_1.NumStaticSamplers > 0)
        {
            samplers.assign(descCopy.Desc_1_1.pStaticSamplers,
                            descCopy.Desc_1_1.pStaticSamplers + descCopy.Desc_1_1.NumStaticSamplers);

            for (auto& s : samplers)
                ApplySamplerOverrides(s);

            descCopy.Desc_1_1.pStaticSamplers = samplers.data();
        }
    }
    else if (descCopy.Version == D3D_ROOT_SIGNATURE_VERSION_1_2)
    {
        if (descCopy.Desc_1_2.NumStaticSamplers > 0)
        {
            samplers1.assign(descCopy.Desc_1_2.pStaticSamplers,
                             descCopy.Desc_1_2.pStaticSamplers + descCopy.Desc_1_2.NumStaticSamplers);

            for (auto& s : samplers1)
                ApplySamplerOverrides(s);

            descCopy.Desc_1_2.pStaticSamplers = samplers1.data();
        }
    }

    ID3DBlob* newBlob = nullptr;
    ID3DBlob* errorBlob = nullptr;
    result = S_OK;

    // Reserialize
    result = o_D3D12SerializeVersionedRootSignature(&descCopy, &newBlob, &errorBlob);

    if (SUCCEEDED(result))
    {
        result = o_CreateRootSignature(device, nodeMask, newBlob->GetBufferPointer(), newBlob->GetBufferSize(), riid,
                                       ppvRootSignature);
        newBlob->Release();

        if (errorBlob)
            errorBlob->Release();
    }
    else
    {
        LOG_ERROR("Failed to reserialize modified RootSig, error: {:X}", (UINT) result);

        if (errorBlob)
        {
            LOG_ERROR("RootSig Serialization Failed: {}", (char*) errorBlob->GetBufferPointer());
            errorBlob->Release();
        }

        // Fallback to original blob
        result =
            o_CreateRootSignature(device, nodeMask, pBlobWithRootSignature, blobLengthInBytes, riid, ppvRootSignature);
    }

    if (SUCCEEDED(result) && ppvRootSignature && *ppvRootSignature)
        PublishCreatedRootParameters(*ppvRootSignature,riid,parameterCount);
    deserializer->Release();
    return result;
}

static HRESULT hkSurveyCreateRootSignature(ID3D12Device* device, UINT nodeMask, const void* pBlobWithRootSignature,
                                     SIZE_T blobLengthInBytes, REFIID riid, void** ppvRootSignature)
{
    const auto result = hkCreateRootSignature(device,nodeMask,pBlobWithRootSignature,blobLengthInBytes,riid,ppvRootSignature);
    if (SUCCEEDED(result) && ppvRootSignature && *ppvRootSignature)
    {
        ReturnedRootInterface returned(*ppvRootSignature,riid);
        if (returned.root) FrameSurvey::RootCreated(returned.root,pBlobWithRootSignature,blobLengthInBytes);
    }
    return result;
}


VALIDATE_HOOK(hkD3D12GetInterface, PFN_D3D12GetInterface)
static HRESULT hkD3D12GetInterface(REFCLSID rclsid, REFIID riid, void** ppvDebug)
{
    LOG_DEBUG("D3D12GetInterface called: {:X}, {:X}, Caller: {}", (size_t) &rclsid, (size_t) &riid,
              Util::WhoIsTheCaller(_ReturnAddress()));

    auto result = o_D3D12GetInterface(rclsid, riid, ppvDebug);

    if (rclsid == CLSID_D3D12DeviceFactory && o_CreateDevice == nullptr)
    {
        auto deviceFactory = (ID3D12DeviceFactory*) *ppvDebug;

        PVOID* pVTable = *(PVOID**) deviceFactory;

        o_CreateDevice = (PFN_CreateDevice) pVTable[9];

        if (o_CreateDevice != nullptr)
        {
            LOG_DEBUG("Detouring ID3D12DeviceFactory::CreateDevice");

            DetourTransactionBegin();
            DetourUpdateThread(GetCurrentThread());
            DetourAttach(&(PVOID&) o_CreateDevice, hkCreateDevice);
            auto detourResult = DetourTransactionCommit();
            if (detourResult != NO_ERROR)
            {
                LOG_ERROR("Failed to detour ID3D12DeviceFactory::CreateDevice, error: {:X}", detourResult);
                o_CreateDevice = nullptr;
            }
        }
    }

    return result;
}

static void HookToDevice(ID3D12Device* InDevice)
{
    if (InDevice == nullptr || FrameSurvey::Internal()) return;
    const auto native = NrdBridgeDevice::Native(InDevice);
    if (!native) return;
    auto* realDevice = native.Get();
    if (NrdBridge::StartupEnabled())
    {
        if (!NrdBridgeDevice::Selected(realDevice, State::Instance().currentD3D12Device)) return;
        // Existing native detours still need to rebind the selected title device.
        if (o_CreateSampler != nullptr)
        {
            ResTrack_Dx12::HookDevice(realDevice);
            return;
        }
    }
    if (o_CreateSampler != nullptr) return;

    LOG_DEBUG("Dx12");

    // Root-state tracking and metadata must use the same native COM surface.
    PVOID* pVTable = *(PVOID**) realDevice;

    gNrdBridgeDeviceWrappers = NrdBridge::StartupEnabled();
    gSurveyDeviceWrappers = Config::Instance()->FfxDenoiserFrameSurvey.value_or_default() || gNrdBridgeDeviceWrappers;
    if (gNrdBridgeDeviceWrappers && !NrdBridge::Initialize(realDevice)) return;
    if (gSurveyDeviceWrappers)
        FrameSurvey::BeginCreationTracking(Config::Instance()->FfxDenoiserFrameSurvey.value_or_default());

    // hudless
    o_D3D12DeviceRelease = (PFN_Release) pVTable[2];
    o_CreateSampler = (PFN_CreateSampler) pVTable[22];
    o_CheckFeatureSupport = (PFN_CheckFeatureSupport) pVTable[13];
    o_CreateRootSignature = (PFN_CreateRootSignature) pVTable[16];
    o_GetResourceAllocationInfo = (PFN_GetResourceAllocationInfo) pVTable[25];
    o_CreateCommittedResource = (PFN_CreateCommittedResource) pVTable[27];
    o_CreatePlacedResource = (PFN_CreatePlacedResource) pVTable[29];

    ID3D12Device1* device12_1 = nullptr;
    if (realDevice)
        realDevice->QueryInterface(IID_PPV_ARGS(&device12_1));
    else
        InDevice->QueryInterface(IID_PPV_ARGS(&device12_1));

    if (device12_1 /*&& isAMD*/)
    {
        PVOID* pVTable = *(PVOID**) device12_1;
        o_SetResidencyPriority = (PFN_SetResidencyPriority) pVTable[46];
        device12_1->Release();
    }

    // Apply the detour
    if (o_CreateSampler != nullptr)
    {
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        if (o_CreateSampler != nullptr)
            DetourAttach(&(PVOID&) o_CreateSampler, hkCreateSampler);

        if (o_CreateRootSignature != nullptr)
            DetourAttach(&(PVOID&) o_CreateRootSignature, gSurveyDeviceWrappers ? hkSurveyCreateRootSignature : hkCreateRootSignature);

        // Will be used for tracking current d3d12 device too
        if (o_D3D12DeviceRelease != nullptr)
            DetourAttach(&(PVOID&) o_D3D12DeviceRelease, hkD3D12DeviceRelease);

        // HACK: see reason in hkSetResidencyPriority
        if (o_SetResidencyPriority != nullptr)
            DetourAttach(&(PVOID&) o_SetResidencyPriority, hkSetResidencyPriority);

        if (Config::Instance()->UESpoofIntelAtomics64.value_or_default() || gSurveyDeviceWrappers)
        {
            LOG_DEBUG("UE spoofing for Intel Atomics64 enabled, applying detours");

            if (o_CheckFeatureSupport != nullptr)
                DetourAttach(&(PVOID&) o_CheckFeatureSupport, hkCheckFeatureSupport);

            if (o_CreateCommittedResource != nullptr)
                DetourAttach(&(PVOID&) o_CreateCommittedResource, gSurveyDeviceWrappers ? hkSurveyCreateCommittedResource : hkCreateCommittedResource);

            if (o_CreatePlacedResource != nullptr)
                DetourAttach(&(PVOID&) o_CreatePlacedResource, gSurveyDeviceWrappers ? hkSurveyCreatePlacedResource : hkCreatePlacedResource);

            if (o_GetResourceAllocationInfo != nullptr)
                DetourAttach(&(PVOID&) o_GetResourceAllocationInfo, hkGetResourceAllocationInfo);
        }

        auto detourResult = DetourTransactionCommit();
        if (detourResult != NO_ERROR)
        {
            LOG_ERROR("Failed to detour ID3D12Device methods, error: {:X}", detourResult);
            o_CreateSampler = nullptr;
            o_CheckFeatureSupport = nullptr;
            o_CreateRootSignature = nullptr;
            o_CreateCommittedResource = nullptr;
            o_CreatePlacedResource = nullptr;
            o_D3D12DeviceRelease = nullptr;
            o_GetResourceAllocationInfo = nullptr;
        }
    }

    HookToCommandList(realDevice);

    if (gSurveyDeviceWrappers || (State::Instance().activeFgInput == FGInput::Upscaler &&
        !Config::Instance()->FGDisableHUDFix.value_or_default() &&
        State::Instance().swapchainInteropApi == SwapchainInteropApi::None))
    {
        ResTrack_Dx12::HookDevice(realDevice);
    }

    if (State::Instance().activeFgOutput == FGOutput::DLSSG && StreamlineProxy::LoadStreamline())
    {
        StreamlineProxy::InitWithD3D12(InDevice);
    }
}

static void UnhookDevice()
{
    LOG_FUNC();

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_CreateSampler != nullptr)
        DetourDetach(&(PVOID&) o_CreateSampler, hkCreateSampler);

    if (o_CreateRootSignature != nullptr)
        DetourDetach(&(PVOID&) o_CreateRootSignature, gSurveyDeviceWrappers ? hkSurveyCreateRootSignature : hkCreateRootSignature);

    if (o_CheckFeatureSupport != nullptr)
        DetourDetach(&(PVOID&) o_CheckFeatureSupport, hkCheckFeatureSupport);

    if (o_CreateCommittedResource != nullptr)
        DetourDetach(&(PVOID&) o_CreateCommittedResource, gSurveyDeviceWrappers ? hkSurveyCreateCommittedResource : hkCreateCommittedResource);

    if (o_CreatePlacedResource != nullptr)
        DetourDetach(&(PVOID&) o_CreatePlacedResource, gSurveyDeviceWrappers ? hkSurveyCreatePlacedResource : hkCreatePlacedResource);

    if (o_D3D12DeviceRelease != nullptr)
        DetourDetach(&(PVOID&) o_D3D12DeviceRelease, hkD3D12DeviceRelease);

    if (o_GetResourceAllocationInfo != nullptr)
        DetourDetach(&(PVOID&) o_GetResourceAllocationInfo, hkGetResourceAllocationInfo);

    auto detourResult = DetourTransactionCommit();
    if (detourResult != NO_ERROR)
    {
        LOG_ERROR("Failed to unhook ID3D12Device methods, error: {:X}", detourResult);
    }
    else
    {
        o_CreateSampler = nullptr;
        o_CheckFeatureSupport = nullptr;
        o_CreateCommittedResource = nullptr;
        o_CreatePlacedResource = nullptr;
        o_D3D12DeviceRelease = nullptr;
        o_GetResourceAllocationInfo = nullptr;
    }

    ResTrack_Dx12::ReleaseDeviceHooks();
}

void D3D12Hooks::Hook()
{
    std::lock_guard<std::mutex> lock(hookMutex);

    LOG_DEBUG("");

    if (o_D3D12CreateDevice == nullptr)
        o_D3D12CreateDevice = D3d12Proxy::Hook_D3D12CreateDevice(hkD3D12CreateDevice);

    if (o_D3D12SerializeRootSignature == nullptr)
        o_D3D12SerializeRootSignature = D3d12Proxy::Hook_D3D12SerializeRootSignature(hkD3D12SerializeRootSignature);

    if (o_D3D12SerializeVersionedRootSignature == nullptr)
        o_D3D12SerializeVersionedRootSignature =
            D3d12Proxy::Hook_D3D12SerializeVersionedRootSignature(hkD3D12SerializeVersionedRootSignature);
}

void D3D12Hooks::HookAgility(HMODULE module)
{
    std::lock_guard<std::mutex> lock(agilityMutex);

    if (module == nullptr || o_D3D12GetInterface != nullptr)
        return;

    LOG_DEBUG("Hooking D3D12GetInterface from D3D12 Agility SDK");

    o_D3D12GetInterface = (PFN_D3D12GetInterface) KernelBaseProxy::GetProcAddress_()(module, "D3D12GetInterface");

    if (o_D3D12GetInterface != nullptr)
    {
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());
        DetourAttach(&(PVOID&) o_D3D12GetInterface, hkD3D12GetInterface);
        auto detourResult = DetourTransactionCommit();
        if (detourResult != NO_ERROR)
        {
            LOG_ERROR("Failed to detour D3D12GetInterface, error: {:X}", detourResult);
            o_D3D12GetInterface = nullptr;
        }
    }
}

void D3D12Hooks::Unhook()
{
    UnhookBridgeGraphicsArguments();
    if (o_D3D12CreateDevice == nullptr)
        return;

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_CreateSampler != nullptr)
        DetourDetach(&(PVOID&) o_CreateSampler, hkCreateSampler);

    if (o_CheckFeatureSupport != nullptr)
        DetourDetach(&(PVOID&) o_CheckFeatureSupport, hkCheckFeatureSupport);

    if (o_CreateCommittedResource != nullptr)
        DetourDetach(&(PVOID&) o_CreateCommittedResource, gSurveyDeviceWrappers ? hkSurveyCreateCommittedResource : hkCreateCommittedResource);

    if (o_CreatePlacedResource != nullptr)
        DetourDetach(&(PVOID&) o_CreatePlacedResource, gSurveyDeviceWrappers ? hkSurveyCreatePlacedResource : hkCreatePlacedResource);

    if (o_GetResourceAllocationInfo != nullptr)
        DetourDetach(&(PVOID&) o_GetResourceAllocationInfo, hkGetResourceAllocationInfo);

    if (o_D3D12DeviceRelease != nullptr)
        DetourDetach(&(PVOID&) o_D3D12DeviceRelease, hkD3D12DeviceRelease);

    auto detourResult = DetourTransactionCommit();
    if (detourResult != NO_ERROR)
    {
        LOG_ERROR("Failed to unhook ID3D12Device methods, error: {:X}", detourResult);
    }
    else
    {
        o_CreateSampler = nullptr;
        o_CheckFeatureSupport = nullptr;
        o_CreateCommittedResource = nullptr;
        o_CreatePlacedResource = nullptr;
        o_D3D12DeviceRelease = nullptr;
        o_GetResourceAllocationInfo = nullptr;
    }
}

void D3D12Hooks::SetRootSignatureTracking(bool enable)
{
    if (gNrdBridgeDeviceWrappers) isNrdBridgeInjection = !enable;
    else isUpscalerActive = !enable;
}
bool D3D12Hooks::RootSignatureTrackingEnabled() { return !(isUpscalerActive || isNrdBridgeInjection); }

void D3D12Hooks::OnBridgeCommandListReset(ID3D12GraphicsCommandList* list, ID3D12PipelineState* initial)
{
    if (!gNrdBridgeDeviceWrappers || !list) return;
    // Successful native Reset owns a live receiver; final Release uses the
    // exact-token cleanup below and never enters this native bootstrap path.
    const auto pipeline = RootTrackerBirthsEnabled() && initial ? TrackerNativeReceiver(initial) : NrdBridgeBirth::Token{};
    RootTrackerPublication publication(list);
    if (!publication.Accepted()) return;
    { std::unique_lock lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock); signatures.erase(list); }
    { std::unique_lock lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
      rootStates.erase(list); bridgeComputeRoots.erase(list); bridgeGraphicsStates.erase(list);
      bridgePredicates.erase(list);
      bridgePredicates.emplace(list,BridgePredicateState{publication.receiver,BridgePredication::Disabled}); }
    { std::unique_lock lock(descriptorHeapsMutex, std::defer_lock); LockRootTracker(lock); descriptorHeaps.erase(list); }
    { std::unique_lock lock(pipelineStatesMutex, std::defer_lock); LockRootTracker(lock);
      if (initial) pipelineStates[list] = TrackedPipelineState{initial,publication.receiver,pipeline}; else pipelineStates.erase(list); }
}

void D3D12Hooks::OnBridgeCommandListClearState(ID3D12GraphicsCommandList* list, ID3D12PipelineState* initial) noexcept
{
    if (!gNrdBridgeDeviceWrappers || !list || isNrdBridgeInjection || FrameSurvey::Internal()) return;
    // This is state invalidation only: ClearState is NOT a recording Reset and
    // must not detach submission leases or advance a recording epoch.
    try { OnBridgeCommandListReset(list,initial); }
    catch (...) { NrdBridgeNativeBirth::Detail::Fail("ClearState metadata publication failed"); }
}

void D3D12Hooks::OnBridgeSetPredication(ID3D12GraphicsCommandList* list, bool enabled) noexcept
{
    if (!gNrdBridgeDeviceWrappers || !list || isNrdBridgeInjection || FrameSurvey::Internal()) return;
    try
    {
        RootTrackerPublication publication(list);
        if (!publication.Accepted()) return;
        std::unique_lock lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
        bridgePredicates.erase(list);
        bridgePredicates.emplace(list,BridgePredicateState{publication.receiver,
            enabled ? BridgePredication::Enabled : BridgePredication::Disabled});
    }
    catch (...) { NrdBridgeNativeBirth::Detail::Fail("predication metadata publication failed"); }
}

void D3D12Hooks::OnBridgeOpaqueCommand(ID3D12GraphicsCommandList* list, bool bundle) noexcept
{
    if (!gNrdBridgeDeviceWrappers || !list || isNrdBridgeInjection || FrameSurvey::Internal()) return;
    try
    {
        RootTrackerPublication publication(list);
        if (!publication.Accepted()) return;
        // Called before AND after forwarding: a bundle may enter other native
        // setters while executing and must not republish a parent binding proof.
        { std::unique_lock lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock); signatures.erase(list); }
        { std::unique_lock lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
          rootStates.erase(list); bridgeComputeRoots.erase(list); bridgeGraphicsStates.erase(list);
          const auto predicate = bridgePredicates.find(list);
          if (predicate != bridgePredicates.end() && (bundle ||
              (RootTrackerBirthsEnabled() && predicate->second.receiverBirth != publication.receiver)))
              bridgePredicates.erase(predicate); }
        { std::unique_lock lock(descriptorHeapsMutex, std::defer_lock); LockRootTracker(lock); descriptorHeaps.erase(list); }
        { std::unique_lock lock(pipelineStatesMutex, std::defer_lock); LockRootTracker(lock); pipelineStates.erase(list); }
    }
    catch (...) { NrdBridgeNativeBirth::Detail::Fail("opaque command metadata invalidation failed"); }
}

bool D3D12Hooks::BridgePredicationDisabled(ID3D12GraphicsCommandList* list) noexcept
{
    if (!gNrdBridgeDeviceWrappers || !list) return false;
    try
    {
        const auto receiver = RootTrackerBirthsEnabled() ? NrdBridgeBirth::Capture(list) : NrdBridgeBirth::Token{};
        NrdBridgeBirth::CurrentGuard guard(receiver,RootTrackerBirthsEnabled());
        if (RootTrackerBirthsEnabled() && !guard.AdmitsBorrow()) return false;
        std::shared_lock lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
        return BridgePredicateDisabledLocked(list,receiver);
    }
    catch (...) { return false; }
}

void D3D12Hooks::OnBridgeObjectReleased(const NrdBridgeBirth::Token& retired) noexcept
{
    if (!gNrdBridgeDeviceWrappers || !retired) return;
    // Direct key + exact retired logical birth. Registry post-zero retirement
    // already substitutes the current sequence for the SAME physical stamp.
    // No native dereference, registry call, owned COM or notification here.
    auto* list = reinterpret_cast<ID3D12GraphicsCommandList*>(retired->Address());
    auto* root = reinterpret_cast<ID3D12RootSignature*>(retired->Address());
    try
    {
        { std::unique_lock lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock);
          const auto found = signatures.find(list); if (found != signatures.end() && found->second.receiverBirth == retired) signatures.erase(found); }
        { std::unique_lock lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock);
          const auto compute = rootStates.find(list);
          if (compute != rootStates.end() && compute->second.receiverBirth == retired) { rootStates.erase(compute); bridgeComputeRoots.erase(list); }
          const auto graphics = bridgeGraphicsStates.find(list);
          if (graphics != bridgeGraphicsStates.end() && graphics->second.rows.receiverBirth == retired) bridgeGraphicsStates.erase(graphics);
          const auto predicate = bridgePredicates.find(list);
          if (predicate != bridgePredicates.end() && predicate->second.receiverBirth == retired) bridgePredicates.erase(predicate); }
        { std::unique_lock lock(descriptorHeapsMutex, std::defer_lock); LockRootTracker(lock);
          const auto found = descriptorHeaps.find(list); if (found != descriptorHeaps.end() && found->second.receiverBirth == retired) descriptorHeaps.erase(found); }
        { std::unique_lock lock(pipelineStatesMutex, std::defer_lock); LockRootTracker(lock);
          const auto found = pipelineStates.find(list); if (found != pipelineStates.end() && found->second.receiverBirth == retired) pipelineStates.erase(found); }
        { std::unique_lock lock(rootSigParameterCountMutex, std::defer_lock); LockRootTracker(lock);
          const auto found = rootSigBirths.find(root); if (found != rootSigBirths.end() && found->second == retired) { rootSigBirths.erase(found); rootSigParameterCount.erase(root); } }
    }
    catch (...) { NrdBridgeNativeBirth::Detail::Fail("root tracker retirement failed"); }
}

bool D3D12Hooks::GetComputeBindingsForBridge(ID3D12GraphicsCommandList* list, FrameSurvey::ComputeBindings& out) noexcept
{
    out = {};
    if (!gNrdBridgeDeviceWrappers || !list) return false;
    try
    {
        // The title setters/bootstrap prepared native identity. This reader is
        // safe under coordinator locks: no native getter, factory or observer.
        const auto receiver = RootTrackerBirthsEnabled() ? NrdBridgeBirth::Capture(list) : NrdBridgeBirth::Token{};
        NrdBridgeBirth::CurrentGuard birthGuard(receiver,RootTrackerBirthsEnabled());
        if (RootTrackerBirthsEnabled() && !birthGuard.AdmitsBorrow()) return false;
        FrameSurvey::ComputeBindings current;
        std::shared_lock roots(rootStatesMutex, std::defer_lock);
        std::shared_lock heaps(descriptorHeapsMutex, std::defer_lock);
        { NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Tracking); std::lock(roots, heaps); }
        const auto root = bridgeComputeRoots.find(list);
        const auto arguments = rootStates.find(list);
        const auto boundHeaps = descriptorHeaps.find(list);
        if (root == bridgeComputeRoots.end() || !root->second || arguments == rootStates.end() ||
            boundHeaps == descriptorHeaps.end() || !boundHeaps->second.NumDescriptorHeaps ||
            boundHeaps->second.NumDescriptorHeaps > 2) return false;
        if (RootTrackerBirthsEnabled() && (arguments->second.receiverBirth != receiver ||
            boundHeaps->second.receiverBirth != receiver || !arguments->second.rootCountKnown ||
            !TrackerBorrowMatches(arguments->second.rootBirth,root->second))) return false;
        current.root = root->second;
        current.receiverBirth = receiver; current.rootBirth = arguments->second.rootBirth;
        for (UINT i = 0; i < boundHeaps->second.NumDescriptorHeaps; ++i)
        {
            auto* heap = boundHeaps->second.Heaps[i];
            if (!heap || (RootTrackerBirthsEnabled() && !TrackerBorrowMatches(boundHeaps->second.heapBirths[i],heap))) return false;
            current.heaps.push_back(heap);
            if (RootTrackerBirthsEnabled()) current.heapBirths.push_back(boundHeaps->second.heapBirths[i]);
        }
        for (UINT i = 0; i < arguments->second.size(); ++i)
        {
            const auto& argument = arguments->second[i];
            if (argument.type == RootEntryType::Table && argument.rootDescriptorTable.ptr)
                current.tables.emplace_back(i, argument.rootDescriptorTable);
            else if (argument.bufferLocation && (argument.type == RootEntryType::CBV ||
                argument.type == RootEntryType::SRV || argument.type == RootEntryType::UAV))
            {
                const auto kind = argument.type == RootEntryType::CBV ? D3D12_DESCRIPTOR_RANGE_TYPE_CBV :
                    argument.type == RootEntryType::SRV ? D3D12_DESCRIPTOR_RANGE_TYPE_SRV : D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
                current.views.push_back({i,kind,argument.bufferLocation});
            }
        }
        out = std::move(current);
        return true;
    }
    catch (...) { out = {}; return false; }
}

bool D3D12Hooks::GetGraphicsBindingsForBridge(ID3D12GraphicsCommandList* list, FrameSurvey::ComputeBindings& out,
                                             ID3D12PipelineState*& currentPipeline) noexcept
{
    out = {}; currentPipeline = nullptr;
    if (!gNrdBridgeDeviceWrappers || !list) return false;
    try
    {
        const auto receiver = RootTrackerBirthsEnabled() ? NrdBridgeBirth::Capture(list) : NrdBridgeBirth::Token{};
        NrdBridgeBirth::CurrentGuard birthGuard(receiver,RootTrackerBirthsEnabled());
        if (RootTrackerBirthsEnabled() && !birthGuard.AdmitsBorrow()) return false;
        FrameSurvey::ComputeBindings current;
        std::array<ID3D12DescriptorHeap*,2> nativeHeaps {};
        std::array<NrdBridgeBirth::Token,2> heapBirths;
        std::array<std::pair<UINT,D3D12_GPU_DESCRIPTOR_HANDLE>,D3D12_MAX_ROOT_COST> tables;
        std::array<FrameSurvey::ComputeRootView,D3D12_MAX_ROOT_COST> views;
        size_t heapCount = 0, tableCount = 0, viewCount = 0;
        ID3D12PipelineState* pipeline = nullptr;
        {
            std::shared_lock roots(rootStatesMutex, std::defer_lock);
            std::shared_lock heaps(descriptorHeapsMutex, std::defer_lock);
            std::shared_lock pipelines(pipelineStatesMutex, std::defer_lock);
            { NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Tracking); std::lock(roots,heaps,pipelines); }
            const auto graphics = bridgeGraphicsStates.find(list);
            const auto boundHeaps = descriptorHeaps.find(list);
            const auto boundPipeline = pipelineStates.find(list);
            if (graphics == bridgeGraphicsStates.end() || !graphics->second.root ||
                boundHeaps == descriptorHeaps.end() || !boundHeaps->second.NumDescriptorHeaps ||
                boundHeaps->second.NumDescriptorHeaps > 2 || boundPipeline == pipelineStates.end() || !boundPipeline->second.ptr)
                return false;
            const auto& rows = graphics->second.rows;
            if (!RootRestoreArgumentsSupported(rows)) return false;
            if (RootTrackerBirthsEnabled() && (rows.receiverBirth != receiver ||
                boundHeaps->second.receiverBirth != receiver || boundPipeline->second.receiverBirth != receiver ||
                !rows.rootCountKnown || !TrackerBorrowMatches(rows.rootBirth,graphics->second.root) ||
                !TrackerBorrowMatches(boundPipeline->second.pipelineBirth,boundPipeline->second.ptr))) return false;
            current.root = graphics->second.root; current.receiverBirth = receiver; current.rootBirth = rows.rootBirth;
            current.pipelineBirth = boundPipeline->second.pipelineBirth; pipeline = boundPipeline->second.ptr;
            heapCount = boundHeaps->second.NumDescriptorHeaps;
            for (UINT i = 0; i < heapCount; ++i)
            {
                auto* heap = boundHeaps->second.Heaps[i];
                if (!heap || (RootTrackerBirthsEnabled() && !TrackerBorrowMatches(boundHeaps->second.heapBirths[i],heap))) return false;
                nativeHeaps[i] = heap; heapBirths[i] = boundHeaps->second.heapBirths[i];
            }
            for (UINT i = 0; i < rows.size(); ++i)
            {
                const auto& argument = rows[i];
                if (argument.type == RootEntryType::Table && argument.rootDescriptorTable.ptr)
                    tables[tableCount++] = {i,argument.rootDescriptorTable};
                else if (argument.bufferLocation && (argument.type == RootEntryType::CBV ||
                    argument.type == RootEntryType::SRV || argument.type == RootEntryType::UAV))
                {
                    const auto kind = argument.type == RootEntryType::CBV ? D3D12_DESCRIPTOR_RANGE_TYPE_CBV :
                        argument.type == RootEntryType::SRV ? D3D12_DESCRIPTOR_RANGE_TYPE_SRV : D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
                    views[viewCount++] = {i,kind,argument.bufferLocation};
                }
            }
        }
        // Allocation and output replacement happen after ALL tracker locks.
        current.heaps.assign(nativeHeaps.begin(),nativeHeaps.begin()+heapCount);
        if (RootTrackerBirthsEnabled()) current.heapBirths.assign(heapBirths.begin(),heapBirths.begin()+heapCount);
        current.tables.assign(tables.begin(),tables.begin()+tableCount);
        current.views.assign(views.begin(),views.begin()+viewCount);
        out = std::move(current); currentPipeline = pipeline; return true;
    }
    catch (...) { out = {}; currentPipeline = nullptr; return false; }
}

static bool CaptureRootRestoreSnapshot(ID3D12GraphicsCommandList* cmdList, bool extended, bool bridgeCompute,
                                      D3D12RootRestoreSnapshot& snapshot, bool bridgeGraphics = false)
{
    if ((bridgeCompute || bridgeGraphics) && !extended) return false;
    const auto receiver = RootTrackerBirthsEnabled() ? NrdBridgeBirth::Capture(cmdList) : NrdBridgeBirth::Token{};
    NrdBridgeBirth::CurrentGuard birthGuard(receiver,RootTrackerBirthsEnabled());
    if (RootTrackerBirthsEnabled() && !birthGuard.AdmitsBorrow()) return false;
    // Caller retains the physical borrow through replay. No native calls,
    // callbacks, logging or COM ownership under Birth/tracker locks.
    std::shared_lock signaturesLock(rootSignatureMutex, std::defer_lock);
    std::shared_lock heapsLock(descriptorHeapsMutex, std::defer_lock);
    std::shared_lock pipelineLock(pipelineStatesMutex, std::defer_lock);
    std::shared_lock statesLock(rootStatesMutex, std::defer_lock);
    if (extended)
    {
        NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Tracking);
        std::lock(signaturesLock, heapsLock, pipelineLock, statesLock);
    }
    else LockRootTracker(signaturesLock);
    if ((bridgeCompute || bridgeGraphics) && !BridgePredicateDisabledLocked(cmdList,receiver)) return false;
    if (bridgeCompute)
    {
        const auto root = bridgeComputeRoots.find(cmdList);
        if (root == bridgeComputeRoots.end() || !root->second) return true;
        const auto rows = rootStates.find(cmdList);
        if (RootTrackerBirthsEnabled() && (rows == rootStates.end() || rows->second.receiverBirth != receiver ||
            !rows->second.rootCountKnown || !TrackerBorrowMatches(rows->second.rootBirth,root->second))) return false;
        snapshot.signature = {SignatureEntryType::Compute,root->second}; snapshot.hasSignature = true;
    }
    else if (bridgeGraphics)
    {
        const auto graphics = bridgeGraphicsStates.find(cmdList);
        if (graphics == bridgeGraphicsStates.end() || !graphics->second.root) return true;
        const auto& rows = graphics->second.rows;
        if (RootTrackerBirthsEnabled() && (rows.receiverBirth != receiver || !rows.rootCountKnown ||
            !TrackerBorrowMatches(rows.rootBirth,graphics->second.root))) return false;
        snapshot.signature = {SignatureEntryType::Graphics,graphics->second.root}; snapshot.hasSignature = true;
    }
    else
    {
        const auto signature = signatures.find(cmdList);
        if (signature == signatures.end()) return true;
        if (RootTrackerBirthsEnabled() && (signature->second.receiverBirth != receiver ||
            !TrackerBorrowMatches(signature->second.rootBirth,signature->second.ptr))) return false;
        snapshot.signature = {signature->second.type,signature->second.ptr}; snapshot.hasSignature = true;
    }
    if (!extended) return true;
    if (const auto heaps = descriptorHeaps.find(cmdList); heaps != descriptorHeaps.end())
    {
        if (heaps->second.NumDescriptorHeaps > 2) return false;
        if (RootTrackerBirthsEnabled() && heaps->second.receiverBirth != receiver) return false;
        snapshot.heaps.NumDescriptorHeaps = heaps->second.NumDescriptorHeaps;
        for (UINT i = 0; i < heaps->second.NumDescriptorHeaps; ++i)
        {
            if (RootTrackerBirthsEnabled() && !TrackerBorrowMatches(heaps->second.heapBirths[i],heaps->second.Heaps[i])) return false;
            snapshot.heaps.Heaps[i] = heaps->second.Heaps[i];
        }
        snapshot.hasHeaps = true;
    }
    if (const auto pipeline = pipelineStates.find(cmdList); pipeline != pipelineStates.end())
    {
        if (RootTrackerBirthsEnabled() && (pipeline->second.receiverBirth != receiver ||
            !TrackerBorrowMatches(pipeline->second.pipelineBirth,pipeline->second.ptr))) return false;
        snapshot.pipelineState = pipeline->second.ptr; snapshot.hasPipelineState = true;
    }
    const TrackedRootRows* states = nullptr;
    if (gNrdBridgeDeviceWrappers && snapshot.signature.type == SignatureEntryType::Graphics)
    {
        if (const auto found = bridgeGraphicsStates.find(cmdList); found != bridgeGraphicsStates.end()) states = &found->second.rows;
    }
    else if (const auto found = rootStates.find(cmdList); found != rootStates.end()) states = &found->second;
    if (states)
    {
        if (RootTrackerBirthsEnabled() && (states->receiverBirth != receiver ||
            !TrackerBorrowMatches(states->rootBirth,snapshot.signature.ptr))) return false;
        if (!RootRestoreArgumentsSupported(*states)) return false;
        snapshot.rootStates.count = states->size(); snapshot.hasRootState = true;
        for (size_t i = 0; i < states->size(); ++i)
        {
            const auto& source = (*states)[i]; auto& target = snapshot.rootStates.values[i];
            target.type = source.type; target.rootDescriptorTable = source.rootDescriptorTable;
            target.bufferLocation = source.bufferLocation; target.Num32BitValues = source.Num32BitValues;
            target.DestOffset = source.DestOffset;
            target.Data.count = source.Data.size(); target.ValidConstants.count = source.ValidConstants.size();
            std::copy(source.Data.begin(), source.Data.end(), target.Data.values.begin());
            std::copy(source.ValidConstants.begin(), source.ValidConstants.end(), target.ValidConstants.values.begin());
        }
    }
    return true;
}

bool D3D12Hooks::CanRestoreRootSignature(ID3D12GraphicsCommandList* cmdList)
{
    bridgeComputeRestoreFailure = nullptr;
    const auto fail = [](const char* reason) { bridgeComputeRestoreFailure = reason; return false; };
    if (!gNrdBridgeDeviceWrappers)
    {
        std::shared_lock lock(rootSignatureMutex, std::defer_lock); LockRootTracker(lock);
        return signatures.find(cmdList) != signatures.end() || fail("legacy_signature_missing");
    }
    if (!Config::Instance()->RestoreComputeSignature.value_or_default() ||
        !Config::Instance()->ExtendedStateRestore.value_or_default()) return fail("restore_configuration_disabled");
    if (!s_SetComputeRootSignature.GetHook() || !s_SetDescriptorHeaps.GetHook() || !s_SetPipelineState.GetHook() ||
        !s_SetComputeRootDescriptorTable.GetHook() || !s_SetComputeRoot32BitConstants.GetHook() ||
        !s_SetComputeRootConstantBufferView.GetHook() || !s_SetComputeRootShaderResourceView.GetHook() ||
        !s_SetComputeRootUnorderedAccessView.GetHook()) return fail("compute_setter_hook_missing");
    const auto receiver = RootTrackerBirthsEnabled() ? NrdBridgeBirth::Capture(cmdList) : NrdBridgeBirth::Token{};
    NrdBridgeBirth::CurrentGuard birthGuard(receiver,RootTrackerBirthsEnabled());
    if (RootTrackerBirthsEnabled() && !birthGuard.AdmitsBorrow()) return fail("command_list_birth_unavailable");
    { std::shared_lock lock(descriptorHeapsMutex, std::defer_lock); LockRootTracker(lock); auto found = descriptorHeaps.find(cmdList);
      if (found == descriptorHeaps.end() || !found->second.NumDescriptorHeaps || found->second.NumDescriptorHeaps > 2) return fail("bound_heaps_missing");
      if (RootTrackerBirthsEnabled()) {
          if (found->second.receiverBirth != receiver) return fail("heap_receiver_birth_mismatch");
          for (UINT i=0;i<found->second.NumDescriptorHeaps;++i)
              if (!TrackerBorrowMatches(found->second.heapBirths[i],found->second.Heaps[i])) return fail("bound_heap_birth_stale");
      } }
    { std::shared_lock lock(pipelineStatesMutex, std::defer_lock); LockRootTracker(lock); auto found = pipelineStates.find(cmdList);
      if (found == pipelineStates.end() || !found->second.ptr) return fail("pipeline_missing");
      if (RootTrackerBirthsEnabled() && found->second.receiverBirth != receiver) return fail("pipeline_receiver_birth_mismatch");
      if (RootTrackerBirthsEnabled() && !TrackerBorrowMatches(found->second.pipelineBirth,found->second.ptr)) return fail("pipeline_birth_stale"); }
    { std::shared_lock lock(rootStatesMutex, std::defer_lock); LockRootTracker(lock); auto found = rootStates.find(cmdList);
      const auto root = bridgeComputeRoots.find(cmdList);
      if (!BridgePredicateDisabledLocked(cmdList,receiver)) return fail("predication_enabled_or_unobserved");
      if (root == bridgeComputeRoots.end() || !root->second) return fail("compute_root_missing");
      if (found == rootStates.end() || found->second.size() <= 5) return fail("compute_arguments_missing");
      if (found->second[1].type != RootEntryType::Table || found->second[5].type != RootEntryType::Table) return fail("native_p1_or_p5_table_missing");
      if (!RootRestoreArgumentsSupported(found->second)) return fail("compute_arguments_unsupported");
      if (RootTrackerBirthsEnabled() && found->second.receiverBirth != receiver) return fail("root_receiver_birth_mismatch");
      if (RootTrackerBirthsEnabled() && !found->second.rootCountKnown) return fail("root_parameter_count_unknown");
      if (RootTrackerBirthsEnabled() && !TrackerBorrowMatches(found->second.rootBirth,root->second)) return fail("compute_root_birth_stale"); }
    return true;
}

const char* D3D12Hooks::ComputeRestoreFailureReason() noexcept { return bridgeComputeRestoreFailure; }

static bool BridgeGraphicsRestoreHooksReady()
{
    return s_SetDescriptorHeaps.GetHook() && s_SetPipelineState.GetHook() &&
        s_SetComputeRootSignature.GetHook() && s_SetGraphicsRootSignature.GetHook() &&
        s_SetComputeRootDescriptorTable.GetHook() && s_SetGraphicsRootDescriptorTable.GetHook() &&
        s_SetComputeRoot32BitConstant.GetHook() && s_SetGraphicsRoot32BitConstant.GetHook() &&
        s_SetComputeRoot32BitConstants.GetHook() && s_SetGraphicsRoot32BitConstants.GetHook() &&
        s_SetComputeRootConstantBufferView.GetHook() && s_SetGraphicsRootConstantBufferView.GetHook() &&
        s_SetComputeRootShaderResourceView.GetHook() && s_SetGraphicsRootShaderResourceView.GetHook() &&
        s_SetComputeRootUnorderedAccessView.GetHook() && s_SetGraphicsRootUnorderedAccessView.GetHook();
}
static bool BridgeGraphicsSnapshotPair(ID3D12GraphicsCommandList* list, D3D12RootRestoreSnapshot& compute,
                                      D3D12RootRestoreSnapshot& graphics)
{
    if (!BridgeGraphicsRestoreHooksReady() ||
        !CaptureRootRestoreSnapshot(list,true,true,compute) ||
        !CaptureRootRestoreSnapshot(list,true,false,graphics,true)) return false;
    // The first B implementation deliberately requires both known bound root
    // families. Absence is not evidence of an unbound prehook compute root.
    if (!compute.hasSignature || compute.signature.type != SignatureEntryType::Compute ||
        !graphics.hasSignature || graphics.signature.type != SignatureEntryType::Graphics ||
        !compute.hasRootState || !graphics.hasRootState || !compute.hasHeaps || !graphics.hasHeaps ||
        !compute.hasPipelineState || !graphics.hasPipelineState || !graphics.pipelineState ||
        compute.pipelineState != graphics.pipelineState || !compute.heaps.NumDescriptorHeaps ||
        compute.heaps.NumDescriptorHeaps != graphics.heaps.NumDescriptorHeaps)
        return false;
    for (UINT i = 0; i < compute.heaps.NumDescriptorHeaps; ++i)
        if (!compute.heaps.Heaps[i] || compute.heaps.Heaps[i] != graphics.heaps.Heaps[i]) return false;
    return true;
}

bool D3D12Hooks::CanRestoreGraphicsRootSignature(ID3D12GraphicsCommandList* list) noexcept
{
    if (!gNrdBridgeDeviceWrappers || !list ||
        !Config::Instance()->RestoreComputeSignature.value_or_default() ||
        !Config::Instance()->ExtendedStateRestore.value_or_default()) return false;
    try
    {
        D3D12RootRestoreSnapshot compute,graphics;
        return BridgeGraphicsSnapshotPair(list,compute,graphics);
    }
    catch (...) { return false; }
}

bool D3D12Hooks::RestoreGraphicsRootForBridge(ID3D12GraphicsCommandList* list) noexcept
{
    if (!gNrdBridgeDeviceWrappers || !list || !isNrdBridgeInjection) return false;
    try
    {
        D3D12RootRestoreSnapshot compute,graphics;
        if (!BridgeGraphicsSnapshotPair(list,compute,graphics)) return false;
        // The physical borrow spans this replay; both snapshot collectors have
        // already released every Birth/tracker lock before a native setter runs.
        bool restored = RestoreDescriptorHeaps(list,graphics);
        s_SetComputeRootSignature.GetHook()(list,compute.signature.ptr);
        restored = RestoreComputeRootState(list,compute) && restored;
        s_SetGraphicsRootSignature.GetHook()(list,graphics.signature.ptr);
        restored = RestoreGraphicsRootState(list,graphics) && restored;
        // Always restore the CURRENT graphics PSO last, not the early NRD CS PSO.
        restored = RestorePipelineState(list,graphics) && restored;
        return restored;
    }
    catch (...) { return false; }
}

bool D3D12Hooks::RestoreDescriptorHeaps(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot)
{
    if (snapshot.hasHeaps)
    {
        const auto& heaps = snapshot.heaps;

        if (heaps.NumDescriptorHeaps > 0 && heaps.Heaps[0] != nullptr)
        {
            if (auto hook = s_SetDescriptorHeaps.GetHook())
            {
                hook(cmdList, heaps.NumDescriptorHeaps, heaps.Heaps);
            }
            else
            {
                LOG_ERROR("Couldn't restore DescriptorHeaps, no original SetDescriptorHeaps");
                return false;
            }
        }

        return true;
    }

    return false;
}

bool D3D12Hooks::RestorePipelineState(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot)
{
    if (snapshot.hasPipelineState)
    {
        auto* pipelineState = snapshot.pipelineState;

        if (auto hook = s_SetPipelineState.GetHook())
        {
            hook(cmdList, pipelineState);
        }
        else
        {
            LOG_ERROR("Couldn't restore PipelineState, no original SetPipelineState");
            return false;
        }

        return true;
    }

    return false;
}

bool D3D12Hooks::RestoreComputeRootState(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot)
{
    if (snapshot.hasRootState)
    {
        const auto& table = snapshot.rootStates;

        for (uint32_t i = 0; i < table.size(); i++)
        {
            if (table[i].type == RootEntryType::Table)
            {
                if (auto hook = s_SetComputeRootDescriptorTable.GetHook())
                    hook(cmdList, i, table[i].rootDescriptorTable);
                else
                    LOG_ERROR("Couldn't restore ComputeRootDescriptorTable, no original SetComputeRootDescriptorTable");
            }
            else if (table[i].type == RootEntryType::Constant)
            {
                if (auto hook = s_SetComputeRoot32BitConstant.GetHook())
                    hook(cmdList, i, table[i].Data[0], table[i].DestOffset);
                else
                    LOG_ERROR("Couldn't restore ComputeRoot32BitConstant, no original SetComputeRoot32BitConstant");
            }
            else if (gNrdBridgeDeviceWrappers && table[i].type == RootEntryType::Constants && !table[i].ValidConstants.empty())
            {
                if (auto hook = s_SetComputeRoot32BitConstants.GetHook())
                {
                    UINT begin = 0;
                    while (begin < table[i].ValidConstants.size())
                    {
                        while (begin < table[i].ValidConstants.size() && !table[i].ValidConstants[begin]) ++begin;
                        UINT end = begin;
                        while (end < table[i].ValidConstants.size() && table[i].ValidConstants[end]) ++end;
                        if (end > begin) hook(cmdList, i, end - begin, table[i].Data.data() + begin, begin);
                        begin = end;
                    }
                }
            }
            else if (table[i].type == RootEntryType::Constants)
            {
                if (auto hook = s_SetComputeRoot32BitConstants.GetHook())
                {
                    hook(cmdList, i, table[i].Num32BitValues, table[i].Data.data(), table[i].DestOffset);
                }
                else
                {
                    LOG_ERROR("Couldn't restore ComputeRoot32BitConstants, no original SetComputeRoot32BitConstants");
                }
            }
            else if (table[i].type == RootEntryType::CBV)
            {
                if (auto hook = s_SetComputeRootConstantBufferView.GetHook())
                    hook(cmdList, i, table[i].bufferLocation);
                else
                    LOG_ERROR("Couldn't restore ComputeRoot CBV, no original SetComputeRootConstantBufferView");
            }
            else if (table[i].type == RootEntryType::SRV)
            {
                if (auto hook = s_SetComputeRootShaderResourceView.GetHook())
                    hook(cmdList, i, table[i].bufferLocation);
                else
                    LOG_ERROR("Couldn't restore ComputeRoot SRV, no original SetComputeRootShaderResourceView");
            }
            else if (table[i].type == RootEntryType::UAV)
            {
                if (auto hook = s_SetComputeRootUnorderedAccessView.GetHook())
                    hook(cmdList, i, table[i].bufferLocation);
                else
                    LOG_ERROR("Couldn't restore ComputeRoot UAV, no original SetComputeRootUnorderedAccessView");
            }
            else if (table[i].type != RootEntryType::Invalid)
            {
                LOG_WARN("Unsupported root argument at index: {} for CmdList: {:X}", i, (UINT64) cmdList);
            }
        }

        return true;
    }

    return false;
}

bool D3D12Hooks::RestoreGraphicsRootState(ID3D12GraphicsCommandList* cmdList, const D3D12RootRestoreSnapshot& snapshot)
{
    if (snapshot.hasRootState)
    {
        const auto& table = snapshot.rootStates;

        for (uint32_t i = 0; i < table.size(); i++)
        {
            if (table[i].type == RootEntryType::Table)
            {
                if (auto hook = s_SetGraphicsRootDescriptorTable.GetHook())
                {
                    hook(cmdList, i, table[i].rootDescriptorTable);
                }
                else
                {
                    LOG_ERROR(
                        "Couldn't restore GraphicsRootDescriptorTable, no original SetGraphicsRootDescriptorTable");
                }
            }
            else if (table[i].type == RootEntryType::Constant)
            {
                if (auto hook = s_SetGraphicsRoot32BitConstant.GetHook())
                    hook(cmdList, i, table[i].Data[0], table[i].DestOffset);
                else
                    LOG_ERROR("Couldn't restore GraphicsRoot32BitConstant, no original SetGraphicsRoot32BitConstant");
            }
            else if (gNrdBridgeDeviceWrappers && table[i].type == RootEntryType::Constants && !table[i].ValidConstants.empty())
            {
                if (auto hook = s_SetGraphicsRoot32BitConstants.GetHook())
                {
                    UINT begin = 0;
                    while (begin < table[i].ValidConstants.size())
                    {
                        while (begin < table[i].ValidConstants.size() && !table[i].ValidConstants[begin]) ++begin;
                        UINT end = begin;
                        while (end < table[i].ValidConstants.size() && table[i].ValidConstants[end]) ++end;
                        if (end > begin) hook(cmdList, i, end - begin, table[i].Data.data() + begin, begin);
                        begin = end;
                    }
                }
            }
            else if (table[i].type == RootEntryType::Constants)
            {
                if (auto hook = s_SetGraphicsRoot32BitConstants.GetHook())
                    hook(cmdList, i, table[i].Num32BitValues, table[i].Data.data(), table[i].DestOffset);
                else
                    LOG_ERROR("Couldn't restore GraphicsRoot32BitConstants, no original SetGraphicsRoot32BitConstants");
            }
            else if (table[i].type == RootEntryType::CBV)
            {
                if (auto hook = s_SetGraphicsRootConstantBufferView.GetHook())
                    hook(cmdList, i, table[i].bufferLocation);
                else
                    LOG_ERROR("Couldn't restore GraphicsRoot CBV, no original SetGraphicsRootConstantBufferView");
            }
            else if (table[i].type == RootEntryType::SRV)
            {
                if (auto hook = s_SetGraphicsRootShaderResourceView.GetHook())
                    hook(cmdList, i, table[i].bufferLocation);
                else
                    LOG_ERROR("Couldn't restore GraphicsRoot SRV, no original SetGraphicsRootShaderResourceView");
            }
            else if (table[i].type == RootEntryType::UAV)
            {
                if (auto hook = s_SetGraphicsRootUnorderedAccessView.GetHook())
                    hook(cmdList, i, table[i].bufferLocation);
                else
                    LOG_ERROR("Couldn't restore GraphicsRoot UAV, no original SetGraphicsRootUnorderedAccessView");
            }
            else if (table[i].type != RootEntryType::Invalid)
            {
                LOG_WARN("Unsupported root argument at index: {} for CmdList: {:X}", i, (UINT64) cmdList);
            }
        }

        return true;
    }

    return false;
}

void D3D12Hooks::RestoreRoot(ID3D12GraphicsCommandList* cmdList)
{
    // An admitted bridge injection must restore its snapshot even if an INI reload changes the flags.
    const bool bridgeRestore = gNrdBridgeDeviceWrappers && isNrdBridgeInjection;
    const bool restoreComputeSignature = bridgeRestore || Config::Instance()->RestoreComputeSignature.value_or_default();
    const bool restoreGraphicSignature = Config::Instance()->RestoreGraphicSignature.value_or_default();

    if (restoreComputeSignature || restoreGraphicSignature)
    {
        const bool extendedRestoreSignature = bridgeRestore || Config::Instance()->ExtendedStateRestore.value_or_default();
        D3D12RootRestoreSnapshot snapshot;
        if (!CaptureRootRestoreSnapshot(cmdList, extendedRestoreSignature, bridgeRestore, snapshot))
        {
            LOG_ERROR("Can't restore invalid cached root arguments for CmdList: {:X}", (UINT64) cmdList);
            return;
        }

        // Bridge callers keep their physical title borrow through replay. Tracker locks
        // are already released before any native setter or logging can run.
        if (snapshot.hasSignature)
        {
            const auto& signature = snapshot.signature;

            if (extendedRestoreSignature)
            {
                if (RestoreDescriptorHeaps(cmdList, snapshot))
                    LOG_TRACE("Restored DescriptorHeaps for CmdList: {:X}", (UINT64) cmdList);
                else
                    LOG_WARN("Can't restore DescriptorHeaps for CmdList: {:X}", (UINT64) cmdList);
            }

            if (signature.type == SignatureEntryType::Compute)
            {
                LOG_TRACE("Restore ComputeRootSig: {:X}, for CmdList: {:X}", (UINT64) signature.ptr, (UINT64) cmdList);

                if (auto hook = s_SetComputeRootSignature.GetHook())
                    hook(cmdList, signature.ptr);
                else
                    LOG_ERROR("Couldn't restore Compute RootSignature, no original SetComputeRootSignature");
            }
            else if (signature.type == SignatureEntryType::Graphics)
            {
                LOG_TRACE("Restore GraphicsRootSig: {:X}, for CmdList: {:X}", (UINT64) signature.ptr, (UINT64) cmdList);

                if (auto hook = s_SetGraphicsRootSignature.GetHook())
                    hook(cmdList, signature.ptr);
                else
                    LOG_ERROR("Couldn't restore Graphics RootSignature, no original SetGraphicsRootSignature");
            }

            if (extendedRestoreSignature)
            {
                if (signature.type == SignatureEntryType::Compute)
                {
                    if (RestoreComputeRootState(cmdList, snapshot))
                        LOG_TRACE("Restored ComputeRootState for CmdList: {:X}", (UINT64) cmdList);
                    else
                        LOG_WARN("Can't restore ComputeRootState for CmdList: {:X}", (UINT64) cmdList);
                }
                else if (signature.type == SignatureEntryType::Graphics)
                {
                    if (RestoreGraphicsRootState(cmdList, snapshot))
                        LOG_TRACE("Restored GraphicsRootState for CmdList: {:X}", (UINT64) cmdList);
                    else
                        LOG_WARN("Can't restore GraphicsRootState for CmdList: {:X}", (UINT64) cmdList);
                }

                if (RestorePipelineState(cmdList, snapshot))
                    LOG_TRACE("Restored PipelineState for CmdList: {:X}", (UINT64) cmdList);
                else
                    LOG_TRACE("Can't restore PipelineState for CmdList: {:X}", (UINT64) cmdList);
            }
        }
        else
        {
            LOG_TRACE("Can't restore Root Signature for CmdList: {:X}", (UINT64) cmdList);
        }
    }
}

void D3D12Hooks::HookDevice(ID3D12Device* device) { HookToDevice(device); }
