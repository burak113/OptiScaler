#include "pch.h"
#if defined(FSRD_NRD_BRIDGE_RR_TEST_BACKEND)
#include "../shader_tools/tests/nrd_bridge_rr_test_support.h"
#else
#include <proxies/FfxApi_Proxy.h>
#include <resource_tracking/ResTrack_Dx12.h>
#include <hooks/Streamline_Hooks.h>
#endif
#include "misc/NrdBridgeOwned_Dx12.h"
#include "FSRDNrdBridgeRR_Dx12.h"
#include "FSRDNrdSignalConstants_Dx12.h"
#include "precompile/FSRDNrdBridgeCommit_Shader.h"
#include <upscalers/fsr31/FSRDRRInterop.h>
#include <wrl/client.h>
#include <array>
#include <cstdio>
#include <sstream>
#include <vector>

namespace NrdBridge
{
namespace
{
using Microsoft::WRL::ComPtr;
static_assert(FFX_DENOISER_VERSION_MAJOR == 1 && FFX_DENOISER_VERSION_MINOR == 2);
static_assert(sizeof(ffxDispatchDescDenoiser) == 448u);

bool Fail(std::string& error, const char* operation, ffxReturnCode_t code)
{
    error = std::string(operation) + " failed (FFX code " + std::to_string(code) + ")";
    return false;
}
bool BooleanIsSet(sl::Boolean value)
{
    return value == sl::Boolean::eTrue || value == sl::Boolean::eFalse;
}
bool TextureMatches(ID3D12Resource* resource, uint32_t width, uint32_t height, DXGI_FORMAT format)
{
    if (!resource) return false;
    const auto desc = resource->GetDesc();
    return desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && desc.Width == width &&
        desc.Height == height && desc.DepthOrArraySize == 1 && desc.MipLevels == 1 &&
        desc.SampleDesc.Count == 1 && desc.Format == format;
}
bool SameDevice(ID3D12Device* device, ID3D12Device* other)
{
    ComPtr<IUnknown> first, second;
    return device && other && SUCCEEDED(device->QueryInterface(IID_PPV_ARGS(&first))) &&
        SUCCEEDED(other->QueryInterface(IID_PPV_ARGS(&second))) && first.Get() == second.Get();
}
struct Context
{
    ffxContext handle = nullptr;
    ComPtr<ID3D12Device> device;
    // Generic FFX create requires descriptor pointers to live until DestroyContext.
    // The shared generation allocation keeps the entire chain stable through fences.
    ffxOverrideVersion overrideVersion {};
    ffxCreateBackendDX12Desc backend {};
    ffxCreateContextDescDenoiser create {};
    uint32_t width = 0, height = 0;
    uint64_t generation = 0;
    bool debugEnabled = false;
    struct Slot
    {
        ComPtr<ID3D12Resource> spec, diff;
        ComPtr<ID3D12DescriptorHeap> descriptors;
        SignalFlagSnapshot flag;
        uint64_t bytes = 0;
    };
    ComPtr<ID3D12RootSignature> commitRoot;
    ComPtr<ID3D12PipelineState> commitPso;
    ComPtr<ID3D12Resource> zeroConstants;
    SignalFlagCapture flagCapture;
    uint64_t zeroBytes = 0;
    std::vector<std::shared_ptr<Slot>> slots;
    uint32_t descriptorStride = 0;
    uint64_t stagingBytes = 0;
    std::array<float, 8> defaultValues {}, configuredValues {};
    bool ApplySettings(const RRSettings& requested, bool& lightingChanged, std::string& error)
    {
        lightingChanged = false;
        auto target = defaultValues;
        for (uint32_t index = 0; index < 7; ++index)
            if (requested.overrideMask & (1u << index))
            {
                target[index] = requested.values[index];
                if (index == 6) target[7] = requested.values[7];
            }
        for (uint32_t index = 0; index < 7; ++index)
        {
            const bool bounds = index == 6;
            if (target[index] == configuredValues[index] && (!bounds || target[7] == configuredValues[7])) continue;
            const std::array<float, 2> previous {configuredValues[index], bounds ? configuredValues[7] : 0.0f};
            configuredValues[index] = target[index];
            if (bounds) configuredValues[7] = target[7];
            ffxConfigureDescDenoiserKeyValue apply {};
            apply.header.type = FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE;
            apply.key = uint64_t(index) + 1u; apply.count = 1;
            apply.data = configuredValues.data() + index;
            const auto result = FfxApiProxy::D3D12_Configure(&handle, &apply.header);
            if (result != FFX_API_RETURN_OK)
            {
                configuredValues[index] = previous[0];
                if (bounds) configuredValues[7] = previous[1];
                const auto operation = "RR runtime configuration key " + std::to_string(index + 1u);
                return Fail(error, operation.c_str(), result);
            }
            lightingChanged |= !bounds;
        }
        return true;
    }
    bool Check(HRESULT result, const char* operation, std::string& error)
    {
        if (SUCCEEDED(result)) return true;
        error = std::string(operation) + " (HRESULT " + std::to_string(result) + ")";
        return false;
    }
    std::shared_ptr<Slot> NewSlot(std::string& error)
    {
        if (slots.size() >= 32) { error = "RR staging pool has 32 unretired recordings"; return nullptr; }
        auto slot = MakeOwnedShared<Slot>();
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; desc.Width = width; desc.Height = height;
        desc.DepthOrArraySize = desc.MipLevels = 1; desc.SampleDesc.Count = 1;
        desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT; desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        for (auto* resource : {std::addressof(slot->spec), std::addressof(slot->diff)})
        {
            if (!Check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr, IID_PPV_ARGS(resource->GetAddressOf())), "RR staged output creation failed", error))
                return nullptr;
            slot->bytes += device->GetResourceAllocationInfo(0, 1, &desc).SizeInBytes;
        }
        slot->spec->SetName(L"NRD RR staged specular"); slot->diff->SetName(L"NRD RR staged diffuse");
        D3D12_DESCRIPTOR_HEAP_DESC descriptors {};
        descriptors.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; descriptors.NumDescriptors = 4;
        descriptors.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (!Check(device->CreateDescriptorHeap(&descriptors, IID_PPV_ARGS(&slot->descriptors)), "RR commit heap creation failed", error))
            return nullptr;
        if (flagCapture.pso && !slot->flag.Initialize(device.Get(), error)) return nullptr;
        stagingBytes += slot->bytes; slots.push_back(slot);
        return slot;
    }
    bool InitializeCommit(std::string& error)
    {
        if (!CreateZeroSignalConstants(device.Get(), zeroConstants, error)) return false;
        const auto zeroDesc = zeroConstants->GetDesc();
        zeroBytes = device->GetResourceAllocationInfo(0, 1, &zeroDesc).SizeInBytes;
        if (!Check(device->CreateRootSignature(0, FSRDNrdBridgeCommit_cso, sizeof(FSRDNrdBridgeCommit_cso),
            IID_PPV_ARGS(&commitRoot)), "RR commit root creation failed", error)) return false;
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
        desc.pRootSignature = commitRoot.Get(); desc.CS = {FSRDNrdBridgeCommit_cso, sizeof(FSRDNrdBridgeCommit_cso)};
        if (!Check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&commitPso)), "RR commit PSO creation failed", error)) return false;
        descriptorStride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        slots.reserve(32);
        for (uint32_t i = 0; i < 4; ++i) if (!NewSlot(error)) return false;
        return true;
    }
    bool PrepareTableFlags(std::string& error)
    {
        // Both native table and direct root-VA routes capture into a leased snapshot.
        if (!flagCapture.Initialize(device.Get(), error)) return false;
        for (const auto& slot : slots) if (!slot->flag.Initialize(device.Get(), error)) return false;
        return true;
    }
    uint64_t AuxiliaryBytes() const noexcept
    {
        uint64_t bytes = zeroBytes;
        for (const auto& slot : slots) bytes += slot->flag.bytes;
        return bytes;
    }
    std::shared_ptr<Slot> AcquireSlot(ID3D12Resource* outputSpec, ID3D12Resource* outputDiff, std::string& error)
    {
        std::shared_ptr<Slot> slot;
        for (const auto& candidate : slots) if (candidate.use_count() == 1) { slot = candidate; break; }
        if (!slot) slot = NewSlot(error);
        if (!slot) return nullptr;
        auto cpu = slot->descriptors->GetCPUDescriptorHandleForHeapStart();
        for (auto* input : {slot->spec.Get(), slot->diff.Get()})
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC desc {}; desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            desc.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; desc.Texture2D.MipLevels = 1;
            desc.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            device->CreateShaderResourceView(input, &desc, cpu); cpu.ptr += descriptorStride;
        }
        for (auto* output : {outputSpec, outputDiff})
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC desc {}; desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            desc.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(output, nullptr, &desc, cpu); cpu.ptr += descriptorStride;
        }
        return slot;
    }
    void Commit(ID3D12GraphicsCommandList* list, const Slot& slot,
                ID3D12Resource* outputSpec, ID3D12Resource* outputDiff, SignalEncoding encoding,
                const TitleSignalConstants& titleConstants) noexcept
    {
        const bool nativeConstants = HasNativeTitleSignalConstants(titleConstants);
        if (nativeConstants)
        {
            flagCapture.Record(list, titleConstants, slot.flag);
        }
        const auto address = nativeConstants ? slot.flag.resource->GetGPUVirtualAddress() : zeroConstants->GetGPUVirtualAddress();
        // Every fallible allocation and lease admission precedes the provider.
        // Title resources only receive UAV barriers; transitions belong to staging.
        std::array<D3D12_RESOURCE_BARRIER, 4> barriers {};
        for (uint32_t i = 0; i < 2; ++i)
        {
            barriers[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers[i].Transition = {i ? slot.diff.Get() : slot.spec.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
            barriers[i+2].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            barriers[i+2].UAV.pResource = i ? outputDiff : outputSpec;
        }
        list->ResourceBarrier(static_cast<UINT>(barriers.size()), barriers.data());
        list->SetPipelineState(commitPso.Get()); list->SetComputeRootSignature(commitRoot.Get());
        ID3D12DescriptorHeap* heaps[] = {slot.descriptors.Get()}; list->SetDescriptorHeaps(1, heaps);
        const uint32_t constants[] = {width, height, uint32_t(encoding), nativeConstants ? 1u : 0u};
        list->SetComputeRoot32BitConstants(0, 4, constants, 0);
        list->SetComputeRootConstantBufferView(3, address);
        auto gpu = slot.descriptors->GetGPUDescriptorHandleForHeapStart(); list->SetComputeRootDescriptorTable(1, gpu);
        gpu.ptr += uint64_t(2) * descriptorStride; list->SetComputeRootDescriptorTable(2, gpu);
        list->Dispatch((width+7)/8, (height+7)/8, 1);
        for (uint32_t i = 0; i < 2; ++i) std::swap(barriers[i].Transition.StateBefore, barriers[i].Transition.StateAfter);
        list->ResourceBarrier(static_cast<UINT>(barriers.size()), barriers.data());
        if (nativeConstants) slot.flag.Transition(list, false);
    }
    ~Context()
    {
        if (!handle) return;
        const auto result = FfxApiProxy::D3D12_DestroyContext(&handle, nullptr);
        if (result != FFX_API_RETURN_OK)
            LOG_ERROR("[NRD_BRIDGE] retired RR context destroy failed: {}", static_cast<uint32_t>(result));
    }
};
struct DispatchLease
{
    std::shared_ptr<Context> context;
    std::shared_ptr<Context::Slot> slot;
    // These are exclusively bridge-owned. Title outputs are borrowed and never retained.
    std::array<ComPtr<ID3D12Resource>, 7> inputs;
};

bool CreateContext(ID3D12Device* device, uint32_t width, uint32_t height,
                   std::shared_ptr<Context>& output, std::string& error, bool debugEnabled = false)
{
    // The signed 1.2 provider terminates inside create at 64x48. Separate native
    // probes verified 64x64 and larger, including odd heights. Use the conservative
    // measured lower bound per axis before calling any provider entry point.
    if (width < 64 || height < 64)
    {
        error = "RR dimensions are below the empirically validated 64x64 minimum";
        return false;
    }
    ScopedSkipSpoofingGlobal skipSpoofing;
    ScopedSkipHeapCapture skipHeapCapture;
    if (!FfxApiProxy::InitFfxDx12_Denoiser())
    {
        error = "AMD RR provider could not be loaded";
        return false;
    }
    uint64_t count = 0;
    ffxQueryDescGetVersions versions {};
    versions.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
    versions.createDescType = FFX_API_EFFECT_ID_DENOISER;
    versions.device = device;
    versions.outputCount = &count;
    auto result = FfxApiProxy::D3D12_Query(nullptr, &versions.header);
    if (result != FFX_API_RETURN_OK) return Fail(error, "RR provider count query", result);
    if (count == 0 || count > 64)
    {
        error = "RR provider count is invalid";
        return false;
    }
    const auto capacity = count;
    std::vector<uint64_t> ids(static_cast<size_t>(capacity));
    std::vector<const char*> names(static_cast<size_t>(capacity));
    versions.versionIds = ids.data();
    versions.versionNames = names.data();
    result = FfxApiProxy::D3D12_Query(nullptr, &versions.header);
    if (result != FFX_API_RETURN_OK) return Fail(error, "RR provider version query", result);
    if (count == 0 || count > capacity)
    {
        error = "RR provider count changed during enumeration";
        return false;
    }
    uint64_t versionId = 0;
    const char* providerName = nullptr;
    bool found = false;
    for (size_t i = 0; i < count; ++i)
    {
        if (!names[i]) continue;
        const char* number = names[i];
        while (*number && (*number < '0' || *number > '9')) ++number;
        unsigned major = 0, minor = 0, patch = 0;
        if (std::sscanf(number, "%u.%u.%u", &major, &minor, &patch) == 3 &&
            major == FFX_DENOISER_VERSION_MAJOR && minor == FFX_DENOISER_VERSION_MINOR &&
            patch == FFX_DENOISER_VERSION_PATCH)
        {
            versionId = ids[i];
            providerName = names[i];
            found = true;
            break;
        }
    }
    if (!found)
    {
        error = "AMD RR 1.2.0 provider is unavailable or incompatible";
        return false;
    }
    auto fresh = MakeOwnedShared<Context>();
    fresh->device = device;
    fresh->width = width;
    fresh->height = height;
    fresh->debugEnabled = debugEnabled;
    if (!fresh->InitializeCommit(error)) return false;
    fresh->overrideVersion.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION;
    fresh->overrideVersion.versionId = versionId;
    fresh->backend.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12;
    fresh->backend.header.pNext = &fresh->overrideVersion.header;
    fresh->backend.device = device;
    fresh->create.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER;
    fresh->create.header.pNext = &fresh->backend.header;
    fresh->create.version = FFX_DENOISER_VERSION;
    fresh->create.maxRenderSize = { width, height };
    fresh->create.signalFlags = FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE | FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR;
    fresh->create.flags = debugEnabled ? FFX_DENOISER_ENABLE_DEBUGGING : 0u;
    result = FfxApiProxy::D3D12_CreateContext(&fresh->handle, &fresh->create.header, nullptr);
    if (result != FFX_API_RETURN_OK) return Fail(error, "RR context creation", result);
    if (!fresh->handle)
    {
        error = "RR context creation returned an empty handle";
        return false;
    }
    for (uint64_t key = FFX_API_CONFIGURE_DENOISER_KEY_CROSS_BILATERAL_NORMAL_STRENGTH;
         key <= FFX_API_CONFIGURE_DENOISER_KEY_DEBUG_VIEW_LINEAR_DEPTH_BOUNDS; ++key)
    {
        // Scalar keys occupy one float; the final debug-depth key occupies two.
        const auto index = static_cast<size_t>(key - 1u);
        ffxQueryDescDenoiserGetDefaultKeyValue query {};
        query.header.type = FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE;
        query.key = key;
        query.count = 1;
        query.data = fresh->defaultValues.data() + index;
        result = FfxApiProxy::D3D12_Query(&fresh->handle, &query.header);
        if (result != FFX_API_RETURN_OK) return Fail(error, "RR AMD-default query", result);
        if (!std::isfinite(fresh->defaultValues[index]) ||
            (index == 6 && (!std::isfinite(fresh->defaultValues[7]) ||
                fresh->defaultValues[6] < 0.0f || fresh->defaultValues[7] <= fresh->defaultValues[6])))
        {
            error = "RR AMD default contains a nonfinite value";
            return false;
        }
        ffxConfigureDescDenoiserKeyValue apply {};
        apply.header.type = FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE;
        apply.key = key;
        apply.count = 1;
        fresh->configuredValues[index] = fresh->defaultValues[index];
        if (index == 6) fresh->configuredValues[7] = fresh->defaultValues[7];
        apply.data = fresh->configuredValues.data() + index;
        result = FfxApiProxy::D3D12_Configure(&fresh->handle, &apply.header);
        if (result != FFX_API_RETURN_OK) return Fail(error, "RR AMD-default apply", result);
    }
    LOG_INFO("[NRD_BRIDGE] RR context initialized: provider='{}', id={:#x}, api=1.2.0, size={}x{}, "
             "signals=DirectDiffuse|IndirectSpecular, AMD defaults=7 keys", providerName, versionId, width, height);
    output = std::move(fresh);
    return true;
}
} // namespace

struct RRWrapper::Impl
{
    std::shared_ptr<Context> context;
    uint64_t generation = 0;
    uint32_t nextFrame = 0;
    bool resetPending = true, historyValid = false;
    FrameParameters previous {};
    RRSettings settings {};
    std::string conventions;
};
bool ValidateRRSettings(const RRSettings& settings, std::string& error)
{
    error.clear();
    if (settings.overrideMask & ~0x7fu)
    { error = "RR settings contain an unsupported AMD key"; return false; }
    if (settings.nativeDebugView < -1 || settings.nativeDebugView >
        FFX_API_DENOISER_DEBUG_VIEW_MODE_FULLSCREEN_VIEWPORT ||
        settings.nativeDebugViewport >= FFX_API_DENOISER_DEBUG_VIEW_MAX_VIEWPORTS)
    { error = "RR native debug view or viewport is unsupported"; return false; }
    for (uint32_t index = 0; index < 7; ++index)
    {
        if (!(settings.overrideMask & (1u << index))) continue;
        const auto value = settings.values[index];
        if (!std::isfinite(value) || (index == 6 && !std::isfinite(settings.values[7])))
        { error = "RR override contains a nonfinite value"; return false; }
        // Conservative bridge domains fit the existing UI; AMD's public API
        // does not specify these as exhaustive provider limits.
        if (((index == 0 || index == 1 || index == 4) && (value < 0.0f || value > 1.0f)) ||
            (index == 2 && (value <= 0.0f || value > 65504.0f)) ||
            (index == 3 && value <= 0.0f) ||
            (index == 5 && (value <= 0.0f || value > 1.0f)) ||
            (index == 6 && (value < 0.0f || settings.values[7] <= value)))
        { error = "RR override is outside the validated bridge domain for key " + std::to_string(index + 1u); return false; }
    }
    return true;
}
RRWrapper::RRWrapper() = default;
RRWrapper::~RRWrapper() = default;
bool RRWrapper::Configure(const RRSettings& requested, std::string& error)
{
    if (!ValidateRRSettings(requested, error)) return false;
    if (!impl_ && !requested.overrideMask && requested.nativeDebugView == -1 &&
        requested.nativeDebugViewport == 0) return true;
    if (!impl_) impl_ = MakeOwnedShared<Impl>();
    impl_->settings = {};
    impl_->settings.overrideMask = requested.overrideMask;
    impl_->settings.nativeDebugView = requested.nativeDebugView;
    impl_->settings.nativeDebugViewport = requested.nativeDebugViewport;
    for (uint32_t index = 0; index < 7; ++index)
        if (requested.overrideMask & (1u << index))
        {
            impl_->settings.values[index] = requested.values[index];
            if (index == 6) impl_->settings.values[7] = requested.values[7];
        }
    if (!impl_->context) return true;
    if (impl_->context->debugEnabled != (requested.nativeDebugView != -1))
    {
        // FFX debugging is a creation flag. Existing GPU leases retain the old
        // generation; the next recording creates a physically fresh context.
        DiscardRecordingHistory();
        return true;
    }
    bool lightingChanged = false;
    try
    {
        if (!impl_->context->ApplySettings(impl_->settings, lightingChanged, error))
        { DiscardRecordingHistory(); return false; }
    }
    catch (...) { DiscardRecordingHistory(); throw; }
    if (lightingChanged) impl_->resetPending = true;
    return true;
}
RRSettingsState RRWrapper::GetSettingsState() const noexcept
{
    RRSettingsState state;
    if (!impl_) return state;
    state.requested = impl_->settings;
    if (impl_->context)
    {
        state.ready = true;
        state.defaults = impl_->context->defaultValues;
        state.effective = impl_->context->configuredValues;
    }
    return state;
}
bool RRWrapper::PrepareFrame(const SLConstantsSnapshot& snapshot, bool requestedReset,
                            FrameParameters& out, std::string& error)
{
    error.clear();
    out = {};
    if (!impl_) impl_ = MakeOwnedShared<Impl>();
    const auto reject = [&](const char* reason) {
        impl_->resetPending = true;
        error = reason;
        return false;
    };
    const auto& sl = snapshot.constants;
    if (snapshot.frameIndex == UINT32_MAX) return reject("Streamline frame constants are missing");
    if (!BooleanIsSet(sl.depthInverted) || !BooleanIsSet(sl.reset) ||
        !BooleanIsSet(sl.motionVectors3D) || !BooleanIsSet(sl.motionVectorsJittered) ||
        !BooleanIsSet(sl.cameraMotionIncluded))
        return reject("Streamline motion/depth/reset convention is missing or invalid");
    if (sl.motionVectors3D == sl::Boolean::eTrue)
        return reject("Streamline 3D motion vectors are unsupported by the NRD bridge");
    if (sl.cameraMotionIncluded != sl::Boolean::eTrue)
        return reject("Streamline motion vectors do not include camera motion");
    if (sl.orthographicProjection != sl::Boolean::eFalse)
        return reject("Streamline perspective projection is missing or unsupported");
    if (!FSRDCamera::IsInitialized(sl.mvecScale.x) || !FSRDCamera::IsInitialized(sl.mvecScale.y) ||
        sl.mvecScale.x == 0.0f || sl.mvecScale.y == 0.0f)
        return reject("Streamline motion-vector scale is missing, invalid or zero");
    if (!FSRDCamera::IsInitialized(sl.jitterOffset.x) || !FSRDCamera::IsInitialized(sl.jitterOffset.y))
        return reject("Streamline pixel jitter is missing or invalid");
    out.camera = FSRDCamera::Resolve(nullptr, nullptr, &sl, sl.depthInverted == sl::Boolean::eTrue);
    if (!out.camera.Complete()) return reject("Streamline camera projection or world-space basis is missing/invalid");
    const auto planes = GetViewPlanes(out.camera.projection, sl.depthInverted == sl::Boolean::eTrue);
    if (!std::isfinite(out.camera.projection.r[3].m128_f32[2]) ||
        out.camera.projection.r[3].m128_f32[2] == 0.0f)
        return reject("Streamline perspective handedness is invalid");
    out.nearPlane = planes.nearPlane;
    out.farPlane = planes.farPlane;
    out.depthSign = planes.isRightHanded ? -1.0f : 1.0f;
    out.motionScale = { sl.mvecScale.x, sl.mvecScale.y };
    out.jitter = { sl.jitterOffset.x, sl.jitterOffset.y };
    out.cameraPosition = { sl.cameraPos.x, sl.cameraPos.y, sl.cameraPos.z };
    out.motionVectorsJittered = sl.motionVectorsJittered == sl::Boolean::eTrue;
    out.motionVectors3D = false;
    out.streamlineFrame = snapshot.frameIndex;
    out.frameIndex = impl_->nextFrame;
    const auto& previous = impl_->previous;
    // Unsigned subtraction handles wrap; UINT32_MAX is the missing-token sentinel.
    const auto delta = uint32_t(snapshot.frameIndex - previous.streamlineFrame);
    const bool consecutive = delta == 1u ||
        (previous.streamlineFrame == UINT32_MAX - 1u && snapshot.frameIndex == 0u);
    const bool frameGap = impl_->historyValid && !consecutive;
    const bool conventionChanged = impl_->historyValid &&
        (out.depthSign != previous.depthSign || out.motionScale.x != previous.motionScale.x ||
         out.motionScale.y != previous.motionScale.y || out.motionVectorsJittered != previous.motionVectorsJittered ||
         out.nearPlane != previous.nearPlane || out.farPlane != previous.farPlane);
    out.reset = requestedReset || impl_->resetPending || !impl_->historyValid || frameGap ||
        conventionChanged || sl.reset == sl::Boolean::eTrue;
    out.previousValid = impl_->historyValid && !out.reset;
    out.previousJitter = out.previousValid ? previous.jitter : out.jitter;
    out.previousCameraPosition = out.previousValid ? previous.cameraPosition : out.cameraPosition;
    if (impl_->conventions.empty())
    {
        std::ostringstream log;
        log << "SL frame=" << snapshot.frameIndex << ", bridge frame=" << out.frameIndex
            << ", mvecScale=(" << sl.mvecScale.x << ',' << sl.mvecScale.y << ")"
            << ", jitterPixels=(" << sl.jitterOffset.x << ',' << sl.jitterOffset.y << ")"
            << ", motionVectorsJittered=" << out.motionVectorsJittered << ", motionVectors3D=0"
            << ", depthInverted=" << (sl.depthInverted == sl::Boolean::eTrue)
            << ", SL cameraNear/Far=(" << sl.cameraNear << ',' << sl.cameraFar << ")"
            << ", projectionNear/Far=(" << out.nearPlane << ',' << out.farPlane << ")"
            << ", infiniteProjection=" << planes.isInfinite << ", rightHanded=" << planes.isRightHanded
            << ", cameraMotionIncluded=1; signals demodulated RGB, white albedos; RR output alpha preserved";
        impl_->conventions = log.str();
    }
    return true;
}

bool RRWrapper::Dispatch(ID3D12GraphicsCommandList* list, const ConvertedResources& input,
                         ID3D12Resource* outputSpec, ID3D12Resource* outputDiff,
                         const FrameParameters& frame, std::string& error, const OutputCommitGuard& guard)
{
    error.clear();
    if (frame.outputEncoding != SignalEncoding::Rgb && frame.outputEncoding != SignalEncoding::YCoCg)
    {
        if (impl_) impl_->resetPending = true;
        error = "NRD output encoding is unsupported";
        return false;
    }
    if (!impl_) impl_ = MakeOwnedShared<Impl>();
    const auto reject = [&](const char* reason) {
        impl_->resetPending = true;
        error = reason;
        return false;
    };
    if (!list || (list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT &&
                  list->GetType() != D3D12_COMMAND_LIST_TYPE_COMPUTE))
        return reject("RR command list is missing or unsupported");
    if (!frame.camera.Complete() || frame.motionVectors3D || frame.frameIndex != impl_->nextFrame)
        return reject("RR frame parameters are missing, unsupported or stale");
    if (!input.width || !input.height || outputSpec == outputDiff)
        return reject("RR dimensions or title output pair are invalid");
    const std::array<ID3D12Resource*, 7> inputs { input.spec, input.diff, input.linearDepth, input.motion,
        input.normals, input.specAlbedo, input.diffAlbedo };
    const std::array<DXGI_FORMAT, 7> formats { DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT,
        DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R10G10B10A2_UNORM,
        DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R8G8B8A8_UNORM };
    for (size_t i = 0; i < inputs.size(); ++i)
        if (!TextureMatches(inputs[i], input.width, input.height, formats[i]) ||
            inputs[i] == outputSpec || inputs[i] == outputDiff)
            return reject("RR bridge resource format, size or output alias is invalid");
    for (auto* output : { outputSpec, outputDiff })
        if (!TextureMatches(output, input.width, input.height, DXGI_FORMAT_R16G16B16A16_FLOAT) ||
            !(output->GetDesc().Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))
            return reject("RR title output format, size or UAV flags are invalid");
    ComPtr<ID3D12Device> device, other;
    if (FAILED(outputSpec->GetDevice(IID_PPV_ARGS(&device))) ||
        FAILED(list->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device.Get(), other.Get()))
        return reject("RR command list and output devices do not match");
    for (auto* resource : inputs)
    {
        other.Reset();
        if (FAILED(resource->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device.Get(), other.Get()))
            return reject("RR bridge resource device does not match the title output");
    }
    other.Reset();
    if (FAILED(outputDiff->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device.Get(), other.Get()))
        return reject("RR title output devices do not match");
    if (!ValidateTitleSignalConstants(frame.outputConstants, device.Get(), error))
    { impl_->resetPending = true; return false; }
    const bool nativeConstants = HasNativeTitleSignalConstants(frame.outputConstants);
    const bool recreate = !impl_->context || impl_->context->width != input.width ||
        impl_->context->height != input.height || !SameDevice(device.Get(), impl_->context->device.Get());
    if (recreate)
    {
        std::shared_ptr<Context> fresh;
        if (!CreateContext(device.Get(), input.width, input.height, fresh, error, impl_->settings.nativeDebugView != -1))
        {
            impl_->resetPending = true;
            return false;
        }
        bool lightingChanged = false;
        try
        {
            if (!fresh->ApplySettings(impl_->settings, lightingChanged, error))
            { DiscardRecordingHistory(); return false; }
        }
        catch (...) { DiscardRecordingHistory(); throw; }
        fresh->generation = ++impl_->generation;
        // Recorded/submitted leases own the previous generation through GPU completion.
        impl_->context = std::move(fresh);
        impl_->resetPending = true;
    }
    if (nativeConstants && !impl_->context->PrepareTableFlags(error))
    { impl_->resetPending = true; return false; }
    auto lease = MakeOwnedShared<DispatchLease>();
    lease->context = impl_->context;
    lease->slot = impl_->context->AcquireSlot(outputSpec, outputDiff, error);
    if (!lease->slot) { impl_->resetPending = true; return false; }
    for (size_t i = 0; i < inputs.size(); ++i) lease->inputs[i] = inputs[i];
    if (!ResTrack_Dx12::RetainComputeDispatch(device.Get(), list, lease))
        return reject("RR recorded-dispatch lifetime tracking is unavailable");
    ffxDispatchDescDenoiserDirectDiffuse diffuse {};
    diffuse.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
    diffuse.signal.input = ffxApiGetResourceDX12(input.diff, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    diffuse.signal.output = ffxApiGetResourceDX12(lease->slot->diff.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
    ffxDispatchDescDenoiserIndirectSpecular specular {};
    specular.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
    specular.signal.input = ffxApiGetResourceDX12(input.spec, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    specular.signal.output = ffxApiGetResourceDX12(lease->slot->spec.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
    diffuse.header.pNext = &specular.header; // AMD1.2 ABI ascending order: 0x44 then 0x48.
    ffxDispatchDescDenoiser dispatch {};
    dispatch.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER;
    dispatch.header.pNext = &diffuse.header;
    dispatch.commandList = list;
    dispatch.linearDepth = ffxApiGetResourceDX12(input.linearDepth, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.motionVectors = ffxApiGetResourceDX12(input.motion, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.normals = ffxApiGetResourceDX12(input.normals, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.specularAlbedo = ffxApiGetResourceDX12(input.specAlbedo, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.diffuseAlbedo = ffxApiGetResourceDX12(input.diffAlbedo, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.motionVectorScale = { 1.0f, 1.0f, 1.0f };
    dispatch.jitterOffsets = { frame.jitter.x, frame.jitter.y };
    const bool reset = frame.reset || impl_->resetPending || recreate;
    dispatch.cameraPositionDelta = reset ? FfxApiFloatCoords3D {} : FfxApiFloatCoords3D {
        frame.previousCameraPosition.x - frame.cameraPosition.x,
        frame.previousCameraPosition.y - frame.cameraPosition.y,
        frame.previousCameraPosition.z - frame.cameraPosition.z };
    dispatch.view = GetRRMatrix(frame.camera.view);
    dispatch.projection = GetRRMatrix(frame.camera.projection);
    dispatch.linearDepthBounds = { frame.nearPlane, frame.farPlane };
    dispatch.renderSize = { input.width, input.height };
    dispatch.frameIndex = frame.frameIndex;
    dispatch.flags = FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO | (reset ? FFX_DENOISER_DISPATCH_RESET : 0);
    ScopedSkipHeapCapture skipHeapCapture;
    ffxReturnCode_t result;
    try { result = FfxApiProxy::D3D12_Dispatch(&lease->context->handle, &dispatch.header); }
    catch (...) { DiscardRecordingHistory(); throw; }
    if (result != FFX_API_RETURN_OK)
    {
        DiscardRecordingHistory();
        return Fail(error, "RR dispatch", result);
    }
    struct PreparedCommit
    {
        Context* context;
        ID3D12GraphicsCommandList* list;
        Context::Slot* slot;
        ID3D12Resource *spec, *diff;
        SignalEncoding encoding;
        TitleSignalConstants constants;
    } commit {lease->context.get(), list, lease->slot.get(), outputSpec, outputDiff, frame.outputEncoding, frame.outputConstants};
    const auto record = +[](void* state) noexcept {
        const auto& prepared = *static_cast<PreparedCommit*>(state);
        prepared.context->Commit(prepared.list, *prepared.slot, prepared.spec, prepared.diff, prepared.encoding, prepared.constants);
    };
    if (guard.admit && !guard.admit(guard.state, record, &commit))
    {
        // SDK work stays leased, but an expired title ticket never receives it.
        DiscardRecordingHistory();
        error = "NRD output ticket expired before RR commit";
        return false;
    }
    if (!guard.admit) record(&commit);
    impl_->previous = frame;
    impl_->previous.reset = reset;
    impl_->historyValid = true;
    impl_->resetPending = false;
    ++impl_->nextFrame;
    return true;
}
void RRWrapper::ResetHistory() noexcept
{
    if (impl_) impl_->resetPending = true;
}
void RRWrapper::DiscardRecordingHistory() noexcept
{
    if (!impl_) return;
    impl_->context.reset();
    impl_->historyValid = false;
    impl_->resetPending = true;
    impl_->previous = {};
}
uint64_t RRWrapper::ContextGeneration() const noexcept { return impl_ ? impl_->generation : 0; }
uint64_t RRWrapper::OwnedStagingBytes() const noexcept
{
    return impl_ && impl_->context ? impl_->context->stagingBytes : 0;
}
uint64_t RRWrapper::OwnedAuxiliaryBytes() const noexcept
{
    return impl_ && impl_->context ? impl_->context->AuxiliaryBytes() : 0;
}
const std::string& RRWrapper::CameraConventionDescription() const noexcept
{
    static const std::string empty;
    return impl_ ? impl_->conventions : empty;
}
}
