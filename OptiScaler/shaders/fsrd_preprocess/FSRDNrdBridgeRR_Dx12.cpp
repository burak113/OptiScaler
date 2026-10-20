#include "pch.h"
#include "misc/NrdBridgeStagePerf_Dx12.h"
#include "misc/NrdBridgeCaptureSlotBudget_Dx12.h"
#if defined(FSRD_NRD_BRIDGE_RR_TEST_BACKEND)
#include "../shader_tools/tests/nrd_bridge_rr_test_support.h"
#else
#include <proxies/FfxApi_Proxy.h>
#include <resource_tracking/ResTrack_Dx12.h>
#include <hooks/Streamline_Hooks.h>
#endif
#include "misc/NrdBridgeOwned_Dx12.h"
#include "misc/RecordedComputeLease_Dx12.h"
#include "FSRDNrdBridgeRR_Dx12.h"
#include "FSRDNrdLightingGuard_Dx12.h"
#include "FSRDRadianceScale_Dx12.h"
#include "FSRDNrdLobeRecovery_Dx12.h"
#include "FSRDNrdFlatAlbedoRecovery_Dx12.h"
#include "FSRDNrdPostMotionAnchor_Dx12.h"
#include "FSRDNrdSignalConstants_Dx12.h"
#include "precompile/FSRDNrdBridgePureCommit_Shader.h"
#include "precompile/FSRDNrdBridgeNativeDebug_Shader.h"
#include "precompile/FSRDNrdBridgeSignalScale_Shader.h"
#include "precompile/FSRDNrdBridgeTurnColour_Shader.h"
#include <upscalers/fsr31/FSRDRRInterop.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <cstring>
#include <bit>
#include <cstdio>
#include <sstream>
#include <optional>
#include <vector>

namespace NrdBridge
{
struct RRRecoveryFamily { LobeRecovery::Family budget; };
std::shared_ptr<RRRecoveryFamily> CreateRRRecoveryFamily() noexcept
{
    try { return MakeOwnedShared<RRRecoveryFamily>(); }
    catch (...) { return {}; } // Optional postprocessing never disables the RR bridge.
}
const char* LobeRecoveryTierName(uint32_t tier) noexcept
{
    switch (tier)
    {
    case uint32_t(LobeRecoveryTier::FullPrecision): return "full_precision";
    case uint32_t(LobeRecoveryTier::MixedPrecision): return "mixed_precision";
    default: return "none";
    }
}
const char* LobeRecoveryFallbackReasonName(uint32_t reason) noexcept
{
    switch (reason)
    {
    case uint32_t(LobeRecoveryFallbackReason::NotRequested): return "not_requested";
    case uint32_t(LobeRecoveryFallbackReason::DebugConstraint): return "debug_constraint";
    case uint32_t(LobeRecoveryFallbackReason::ZeroStrength): return "zero_strength";
    case uint32_t(LobeRecoveryFallbackReason::ExternalFamilyUnavailable): return "external_family_unavailable";
    case uint32_t(LobeRecoveryFallbackReason::FamilyCapacity): return "family_capacity";
    case uint32_t(LobeRecoveryFallbackReason::PreparationFailed): return "preparation_failed";
    default: return "none";
    }
}
// P05: cheap metadata reads so a service-level consumer can publish the
// family retained peak without reaching into the recovery helper internals.
RRRecoveryFamilyMemory SnapshotRecoveryFamilyMemory(const std::shared_ptr<RRRecoveryFamily>& family) noexcept
{
    RRRecoveryFamilyMemory result;
    if (!family) return result;
    result.graphBytes = family->budget.graphBytes.load(std::memory_order_acquire);
    result.familyRetainedPeakBytes = family->budget.retainedPeakBytes.load(std::memory_order_acquire);
    result.slotBytes = family->budget.slots.allocatedBytes.load(std::memory_order_acquire);
    result.slots = family->budget.slots.allocatedSlots.load(std::memory_order_acquire);
    return result;
}
namespace
{
using Microsoft::WRL::ComPtr;
static_assert(FFX_DENOISER_VERSION_MAJOR == 1 && FFX_DENOISER_VERSION_MINOR == 2);
static_assert(sizeof(ffxDispatchDescDenoiser) == 448u);
static_assert(offsetof(ffxDispatchDescDenoiser, motionVectorScale) == 264u);
static_assert(sizeof(ffxDispatchDescDenoiser) - offsetof(ffxDispatchDescDenoiser, motionVectorScale) == 184u);

template<class Proxy> std::string OwnedProviderAttestation(ffxContext context) noexcept
{
    if constexpr (requires { Proxy::DenoiserRouteAttestationDx12(context); })
        return Proxy::DenoiserRouteAttestationDx12(context);
    return {}; // Minimal test proxies cannot attest an actual module route.
}

bool Fail(std::string& error, const char* operation, ffxReturnCode_t code)
{
    error = std::string(operation) + " failed (FFX code " + std::to_string(code) + ")";
    return false;
}
// Rate-limited classification from the helper's stable message constants;
// the full optional error text is always preserved verbatim regardless.
bool LobeRecoveryCapacityText(const std::string& text) noexcept
{
    return text.find("family exceeds") != std::string::npos ||
        text.find("retained recording slots") != std::string::npos ||
        text.find("slot capacity is exhausted") != std::string::npos;
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
// Validation is kept separate so legacy Dispatch can reject bad borrowed targets before any provider work.
bool ValidateCommitTarget(ID3D12GraphicsCommandList* list, uint32_t width, uint32_t height,
                          const std::array<ID3D12Resource*, 7>& inputs, ID3D12Resource* outputSpec,
                          ID3D12Resource* outputDiff, const FrameParameters& frame,
                          ID3D12Device* expectedDevice, std::string& error)
{
    const auto reject = [&](const char* reason) { error = reason; return false; };
    if (!list || (list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT && list->GetType() != D3D12_COMMAND_LIST_TYPE_COMPUTE))
        return reject("RR command list is missing or unsupported");
    if (frame.outputEncoding != SignalEncoding::Rgb && frame.outputEncoding != SignalEncoding::YCoCg)
        return reject("NRD output encoding is unsupported");
    if (!width || !height || outputSpec == outputDiff)
        return reject("RR dimensions or title output pair are invalid");
    for (auto* output : {outputSpec,outputDiff})
        if (!TextureMatches(output,width,height,DXGI_FORMAT_R16G16B16A16_FLOAT) ||
            !(output->GetDesc().Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))
            return reject("RR title output format, size or UAV flags are invalid");
    for (auto* input : inputs)
        if (input == outputSpec || input == outputDiff)
            return reject("RR bridge resource format, size or output alias is invalid");
    ComPtr<ID3D12Device> device, other;
    if (FAILED(list->GetDevice(IID_PPV_ARGS(&device))) || (expectedDevice && !SameDevice(device.Get(),expectedDevice)))
        return reject("RR command list and owned output devices do not match");
    for (auto* output : {outputSpec,outputDiff})
    {
        other.Reset();
        if (FAILED(output->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device.Get(),other.Get()))
            return reject("RR title output devices do not match the command list");
    }
    return ValidateTitleSignalConstants(frame.outputConstants,device.Get(),error);
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
    std::array<char, 128> providerName {};
    bool debugEnabled = false;
    struct Slot
    {
        ComPtr<ID3D12Resource> spec, diff;
        ComPtr<ID3D12DescriptorHeap> descriptors;
        ComPtr<ID3D12DescriptorHeap> scaleDescriptors; // UAVs: input spec, input diff, staged spec, staged diff.
        ComPtr<ID3D12DescriptorHeap> turnDescriptors; // SRVs: input spec, diff; UAVs: RR-only filtered spec, diff.
        ComPtr<ID3D12Resource> nativeDebug;
        ComPtr<ID3D12DescriptorHeap> nativeDebugGpuUav, nativeDebugCpuUav;
        SignalFlagSnapshot flag;
        uint64_t bytes = 0, nativeDebugBytes = 0;
    };
    struct PresentSlot
    {
        ComPtr<ID3D12DescriptorHeap> descriptors;
    };
    ComPtr<ID3D12RootSignature> commitRoot;
    ComPtr<ID3D12PipelineState> commitPso;
    ComPtr<ID3D12RootSignature> scaleRoot;
    ComPtr<ID3D12PipelineState> scalePso;
    // Post-turn colour filter / brightness correction (RRSettings::turnColourFilter, turnBrightness), created on first use only.
    ComPtr<ID3D12RootSignature> turnRoot;
    ComPtr<ID3D12PipelineState> turnPso;
    std::array<ComPtr<ID3D12Resource>, 2> turnSignals; // RR inputs: filtered spec, diff (UAV between frames).
    uint64_t turnBytes = 0;
    ComPtr<ID3D12Resource> zeroConstants;
    SignalFlagCapture flagCapture;
    uint8_t flagReadyMask = 0;
    std::optional<LobeRecovery> recovery;
    std::optional<FlatAlbedoRecovery> flatAlbedo;
    bool flatWasActive = false;
    ComPtr<ID3D12RootSignature> nativeDebugRoot;
    ComPtr<ID3D12PipelineState> nativeDebugPso;
    uint64_t zeroBytes = 0;
    std::vector<std::shared_ptr<Slot>> slots;
    std::vector<std::shared_ptr<PresentSlot>> presentSlots;
    uint32_t descriptorStride = 0;
    uint64_t stagingBytes = 0;
    // D07/WP10 byte admission ledger (retained generations, pairs only).
    // limit 0 = disabled: identical shipped admission behavior.
    std::shared_ptr<NrdBridgeCaptureBudget::StagingLedger> ledger;
    uint64_t ledgerBytes = 0;
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
        // Configure is also called before each native recording. Keep the last per-frame key 2 here;
        // restoring the fixed slider would otherwise mark lightingChanged and reset RR every frame.
        if (requested.motionStability.enabled) target[1] = configuredValues[1];
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
    bool ApplyMotionStability(float value, std::string& error)
    {
        if (configuredValues[1] == value) return true;
        ffxConfigureDescDenoiserKeyValue apply {};
        apply.header.type = FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE;
        apply.key = 2; apply.count = 1; apply.data = &value;
        const auto result = FfxApiProxy::D3D12_Configure(&handle, &apply.header);
        if (result != FFX_API_RETURN_OK) return Fail(error, "RR motion-adaptive stability key 2", result);
        configuredValues[1] = value;
        return true; // Runtime key 2 changes preserve history; no lightingChanged/resetPending path.
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
        if (debugEnabled)
        {
            if (!Check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr, IID_PPV_ARGS(&slot->nativeDebug)),
                "RR native debug target creation failed", error)) return nullptr;
            slot->nativeDebug->SetName(L"NRD RR native AMD debug view");
            slot->nativeDebugBytes = device->GetResourceAllocationInfo(0, 1, &desc).SizeInBytes;
            D3D12_DESCRIPTOR_HEAP_DESC viewHeap {};
            viewHeap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; viewHeap.NumDescriptors = 1;
            viewHeap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
            if (!Check(device->CreateDescriptorHeap(&viewHeap, IID_PPV_ARGS(&slot->nativeDebugGpuUav)),
                "RR native debug GPU clear heap creation failed", error)) return nullptr;
            viewHeap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
            if (!Check(device->CreateDescriptorHeap(&viewHeap, IID_PPV_ARGS(&slot->nativeDebugCpuUav)),
                "RR native debug CPU clear heap creation failed", error)) return nullptr;
            D3D12_UNORDERED_ACCESS_VIEW_DESC view {};
            view.Format = desc.Format; view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(slot->nativeDebug.Get(), nullptr, &view,
                slot->nativeDebugGpuUav->GetCPUDescriptorHandleForHeapStart());
            device->CreateUnorderedAccessView(slot->nativeDebug.Get(), nullptr, &view,
                slot->nativeDebugCpuUav->GetCPUDescriptorHandleForHeapStart());
        }
        D3D12_DESCRIPTOR_HEAP_DESC descriptors {};
        descriptors.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; descriptors.NumDescriptors = 4;
        descriptors.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (!Check(device->CreateDescriptorHeap(&descriptors, IID_PPV_ARGS(&slot->descriptors)), "RR commit heap creation failed", error))
            return nullptr;
        if (!Check(device->CreateDescriptorHeap(&descriptors, IID_PPV_ARGS(&slot->scaleDescriptors)), "RR signal scale heap creation failed", error))
            return nullptr;
        if (flagCapture.pso && !slot->flag.Initialize(device.Get(), error)) return nullptr;
        // D07/WP10 byte admission (retained generations, pair bytes only).
        // Disabled at the ledger default limit 0; the rejection keeps the
        // mandatory-RR fail-closed contract: no slot, no recording, no denoise.
        if (ledger && !ledger->TryAdmit(slot->bytes))
        {
            error = "RR staging pool byte budget is exhausted";
            return nullptr;
        }
        stagingBytes += slot->bytes; slots.push_back(slot);
        if (ledger) ledgerBytes += slot->bytes;
        return slot;
    }
    std::shared_ptr<PresentSlot> NewPresentSlot(std::string& error)
    {
        if (presentSlots.size() >= 32) { error = "RR native debug presentation pool has 32 unretired recordings"; return nullptr; }
        auto slot = MakeOwnedShared<PresentSlot>();
        D3D12_DESCRIPTOR_HEAP_DESC desc {};
        desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; desc.NumDescriptors = 2;
        desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (!Check(device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&slot->descriptors)),
            "RR native debug presentation heap creation failed", error)) return nullptr;
        presentSlots.push_back(slot);
        return slot;
    }
    bool InitializeNativeDebug(std::string& error)
    {
        if (!debugEnabled) return true;
        if (!Check(device->CreateRootSignature(0, FSRDNrdBridgeNativeDebug_cso, sizeof(FSRDNrdBridgeNativeDebug_cso),
            IID_PPV_ARGS(&nativeDebugRoot)), "RR native debug presentation root creation failed", error)) return false;
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
        desc.pRootSignature = nativeDebugRoot.Get(); desc.CS = {FSRDNrdBridgeNativeDebug_cso, sizeof(FSRDNrdBridgeNativeDebug_cso)};
        if (!Check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&nativeDebugPso)),
            "RR native debug presentation PSO creation failed", error)) return false;
        presentSlots.reserve(32);
        for (uint32_t i = 0; i < 4; ++i) if (!NewPresentSlot(error)) return false;
        return true;
    }
    bool InitializeCommit(std::string& error)
    {
        if (!CreateZeroSignalConstants(device.Get(), zeroConstants, error)) return false;
        const auto zeroDesc = zeroConstants->GetDesc();
        zeroBytes = device->GetResourceAllocationInfo(0, 1, &zeroDesc).SizeInBytes;
        if (!Check(device->CreateRootSignature(0, FSRDNrdBridgePureCommit_cso, sizeof(FSRDNrdBridgePureCommit_cso),
            IID_PPV_ARGS(&commitRoot)), "RR commit root creation failed", error)) return false;
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
        desc.pRootSignature = commitRoot.Get(); desc.CS = {FSRDNrdBridgePureCommit_cso, sizeof(FSRDNrdBridgePureCommit_cso)};
        if (!Check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&commitPso)), "RR commit PSO creation failed", error)) return false;
        if (!Check(device->CreateRootSignature(0, FSRDNrdBridgeSignalScale_cso, sizeof(FSRDNrdBridgeSignalScale_cso),
            IID_PPV_ARGS(&scaleRoot)), "RR signal scale root creation failed", error)) return false;
        desc.pRootSignature = scaleRoot.Get(); desc.CS = {FSRDNrdBridgeSignalScale_cso, sizeof(FSRDNrdBridgeSignalScale_cso)};
        if (!Check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&scalePso)), "RR signal scale PSO creation failed", error)) return false;
        descriptorStride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        slots.reserve(32);
        for (uint32_t i = 0; i < 4; ++i) if (!NewSlot(error)) return false;
        return InitializeNativeDebug(error);
    }
    bool PrepareTableFlags(std::string& error, uint32_t wordIndex = 303)
    {
        const uint8_t profile = wordIndex == 303 ? 1u : wordIndex == 36 ? 2u : 0u;
        if (!profile) { error = "RR native encoding word is unsupported"; return false; }
        // Capture owns both profile PSO/root pairs for this entire context generation.
        if (!flagCapture.Initialize(device.Get(), error, wordIndex)) return false;
        for (const auto& slot : slots) if (!slot->flag.Initialize(device.Get(), error)) return false;
        flagReadyMask |= profile;
        return true;
    }
    bool TableFlagsReady(const Slot& slot, uint32_t wordIndex) const noexcept
    {
        const uint8_t profile = wordIndex == 303 ? 1u : wordIndex == 36 ? 2u : 0u;
        return profile && (flagReadyMask & profile) && bool(slot.flag.resource);
    }
    uint64_t AuxiliaryBytes() const noexcept
    {
        uint64_t bytes = zeroBytes + turnBytes;
        for (const auto& slot : slots) bytes += slot->flag.bytes + slot->nativeDebugBytes;
        return bytes;
    }
    bool EnsureTurnColour(Slot& slot, std::string& error)
    {
        if (!slot.turnDescriptors)
        {
            D3D12_DESCRIPTOR_HEAP_DESC descriptors {};
            descriptors.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; descriptors.NumDescriptors = 4;
            descriptors.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
            if (!Check(device->CreateDescriptorHeap(&descriptors, IID_PPV_ARGS(&slot.turnDescriptors)), "RR turn colour heap creation failed", error))
                return false;
        }
        if (turnPso) return true;
        if (!Check(device->CreateRootSignature(0, FSRDNrdBridgeTurnColour_cso, sizeof(FSRDNrdBridgeTurnColour_cso),
            IID_PPV_ARGS(&turnRoot)), "RR turn colour root creation failed", error)) return false;
        D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline {};
        pipeline.pRootSignature = turnRoot.Get(); pipeline.CS = {FSRDNrdBridgeTurnColour_cso, sizeof(FSRDNrdBridgeTurnColour_cso)};
        ComPtr<ID3D12PipelineState> pso;
        if (!Check(device->CreateComputePipelineState(&pipeline, IID_PPV_ARGS(&pso)), "RR turn colour PSO creation failed", error)) return false;
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; desc.Width = width; desc.Height = height;
        desc.DepthOrArraySize = desc.MipLevels = 1; desc.SampleDesc.Count = 1;
        desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT; desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        for (auto& signal : turnSignals)
            if (!Check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                nullptr, IID_PPV_ARGS(&signal)), "RR turn colour signal creation failed", error)) return false;
        turnSignals[0]->SetName(L"NRD RR turn colour specular"); turnSignals[1]->SetName(L"NRD RR turn colour diffuse");
        turnBytes = 2 * device->GetResourceAllocationInfo(0, 1, &desc).SizeInBytes;
        turnPso = pso;
        return true;
    }
    // Reads the scaled inputs (NON_PIXEL_SHADER_RESOURCE) and leaves the filtered copies readable by RR.
    void TurnColour(ID3D12GraphicsCommandList* list, const Slot& slot, ID3D12Resource* inputSpec, ID3D12Resource* inputDiff,
                    float weight, float gain) const noexcept
    {
        auto cpu = slot.turnDescriptors->GetCPUDescriptorHandleForHeapStart();
        for (auto* signal : {inputSpec, inputDiff})
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC view {}; view.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            view.Texture2D.MipLevels = 1;
            device->CreateShaderResourceView(signal, &view, cpu); cpu.ptr += descriptorStride;
        }
        for (const auto& signal : turnSignals)
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC view {}; view.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(signal.Get(), nullptr, &view, cpu); cpu.ptr += descriptorStride;
        }
        list->SetPipelineState(turnPso.Get()); list->SetComputeRootSignature(turnRoot.Get());
        ID3D12DescriptorHeap* heaps[] = {slot.turnDescriptors.Get()}; list->SetDescriptorHeaps(1, heaps);
        const uint32_t constants[] = {width, height, std::bit_cast<uint32_t>(weight), std::bit_cast<uint32_t>(gain)};
        list->SetComputeRoot32BitConstants(0, 4, constants, 0);
        list->SetComputeRootDescriptorTable(1, slot.turnDescriptors->GetGPUDescriptorHandleForHeapStart());
        list->Dispatch((width+15)/16, (height+15)/16, 1); // 16x16 groups
        TurnColourBarriers(list, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    void TurnColourBarriers(ID3D12GraphicsCommandList* list, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) const noexcept
    {
        std::array<D3D12_RESOURCE_BARRIER, 2> barriers {};
        for (uint32_t i = 0; i < 2; ++i)
        {
            barriers[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers[i].Transition = {turnSignals[i].Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        }
        list->ResourceBarrier(2, barriers.data());
    }
    // CP77 NRD-domain radiance is ~1e-4, where the AMD provider clamps its output
    // to an absolute floor of ~1e-5 that greys dark specular (water). Lighting
    // enters RR scaled by 2^8 and leaves divided by it; power-of-two scaling is
    // exact in fp16, so every other reader still sees the original words.
    static constexpr float SignalScale = 256.0f;
    void BindScaleSignals(const Slot& slot, ID3D12Resource* inputSpec, ID3D12Resource* inputDiff) const noexcept
    {
        auto cpu = slot.scaleDescriptors->GetCPUDescriptorHandleForHeapStart();
        for (auto* signal : {inputSpec, inputDiff, slot.spec.Get(), slot.diff.Get()})
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC view {}; view.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(signal, nullptr, &view, cpu); cpu.ptr += descriptorStride;
        }
    }
    // Inputs are in the provider's COMPUTE_READ state; staged RR outputs stay UAV.
    // Up scales the two inputs; restore divides inputs and the RR outputs.
    void ScaleSignals(ID3D12GraphicsCommandList* list, const Slot& slot, ID3D12Resource* inputSpec,
                      ID3D12Resource* inputDiff, bool restore) const noexcept
    {
        std::array<D3D12_RESOURCE_BARRIER, 4> barriers {};
        for (uint32_t i = 0; i < 2; ++i)
        {
            barriers[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers[i].Transition = {i ? inputDiff : inputSpec, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            barriers[i+2].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            barriers[i+2].UAV.pResource = i ? slot.diff.Get() : slot.spec.Get();
        }
        const UINT count = restore ? 4u : 2u;
        list->ResourceBarrier(count, barriers.data());
        list->SetPipelineState(scalePso.Get()); list->SetComputeRootSignature(scaleRoot.Get());
        ID3D12DescriptorHeap* heaps[] = {slot.scaleDescriptors.Get()}; list->SetDescriptorHeaps(1, heaps);
        const uint32_t constants[] = {width, height, std::bit_cast<uint32_t>(restore ? 1.0f/SignalScale : SignalScale), count};
        list->SetComputeRoot32BitConstants(0, 4, constants, 0);
        list->SetComputeRootDescriptorTable(1, slot.scaleDescriptors->GetGPUDescriptorHandleForHeapStart());
        list->Dispatch((width+7)/8, (height+7)/8, 1);
        for (uint32_t i = 0; i < 2; ++i) std::swap(barriers[i].Transition.StateBefore, barriers[i].Transition.StateAfter);
        list->ResourceBarrier(count, barriers.data());
    }
    void ClearNativeDebug(ID3D12GraphicsCommandList* list, const Slot& slot) const noexcept
    {
        const float zero[4] {};
        ID3D12DescriptorHeap* heaps[] = {slot.nativeDebugGpuUav.Get()}; list->SetDescriptorHeaps(1, heaps);
        list->ClearUnorderedAccessViewFloat(slot.nativeDebugGpuUav->GetGPUDescriptorHandleForHeapStart(),
            slot.nativeDebugCpuUav->GetCPUDescriptorHandleForHeapStart(), slot.nativeDebug.Get(), zero, 0, nullptr);
        D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
        barrier.UAV.pResource = slot.nativeDebug.Get(); list->ResourceBarrier(1, &barrier);
    }
    std::shared_ptr<PresentSlot> AcquirePresentSlot(ID3D12Resource* source, ID3D12Resource* output,
                                                   DXGI_FORMAT format, std::string& error)
    {
        std::shared_ptr<PresentSlot> slot;
        for (const auto& candidate : presentSlots) if (candidate.use_count() == 1) { slot = candidate; break; }
        if (!slot) slot = NewPresentSlot(error);
        if (!slot) return nullptr;
        auto cpu = slot->descriptors->GetCPUDescriptorHandleForHeapStart();
        D3D12_SHADER_RESOURCE_VIEW_DESC srv {}; srv.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
        srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; srv.Texture2D.MipLevels = 1;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        device->CreateShaderResourceView(source, &srv, cpu); cpu.ptr += descriptorStride;
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav {}; uav.Format = format;
        uav.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(output, nullptr, &uav, cpu);
        return slot;
    }
    void Present(ID3D12GraphicsCommandList* list, const PresentSlot& slot, ID3D12Resource* source,
                 ID3D12Resource* output, D3D12_RESOURCE_STATES outputState, uint32_t sourceWidth,
                 uint32_t sourceHeight, uint32_t outputWidth, uint32_t outputHeight) const noexcept
    {
        D3D12_RESOURCE_BARRIER barriers[2] {};
        barriers[0].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barriers[0].Transition = {source, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
        barriers[1].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV; barriers[1].UAV.pResource = output;
        if (outputState != D3D12_RESOURCE_STATE_UNORDERED_ACCESS)
        {
            barriers[1].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers[1].Transition = {output, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                outputState, D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
        }
        list->ResourceBarrier(2, barriers);
        list->SetPipelineState(nativeDebugPso.Get()); list->SetComputeRootSignature(nativeDebugRoot.Get());
        ID3D12DescriptorHeap* heaps[] = {slot.descriptors.Get()}; list->SetDescriptorHeaps(1, heaps);
        const uint32_t constants[] = {sourceWidth, sourceHeight, outputWidth, outputHeight};
        list->SetComputeRoot32BitConstants(0, 4, constants, 0);
        auto gpu = slot.descriptors->GetGPUDescriptorHandleForHeapStart(); list->SetComputeRootDescriptorTable(1, gpu);
        gpu.ptr += descriptorStride; list->SetComputeRootDescriptorTable(2, gpu);
        list->Dispatch((outputWidth+7)/8, (outputHeight+7)/8, 1);
        std::swap(barriers[0].Transition.StateBefore, barriers[0].Transition.StateAfter);
        if (barriers[1].Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION)
            std::swap(barriers[1].Transition.StateBefore, barriers[1].Transition.StateAfter);
        list->ResourceBarrier(2, barriers);
    }
    std::shared_ptr<Slot> AcquireOwnedSlot(std::string& error)
    {
        std::shared_ptr<Slot> slot;
        for (const auto& candidate : slots) if (candidate.use_count() == 1) { slot = candidate; break; }
        if (!slot) slot = NewSlot(error);
        if (!slot) return nullptr;
        SetCommitInputs(*slot,slot->spec.Get(),slot->diff.Get());
        return slot;
    }
    void SetCommitOutputs(const Slot& slot, ID3D12Resource* outputSpec, ID3D12Resource* outputDiff) noexcept
    {
        auto cpu = slot.descriptors->GetCPUDescriptorHandleForHeapStart();
        cpu.ptr += uint64_t(2) * descriptorStride;
        for (auto* output : {outputSpec, outputDiff})
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC desc {}; desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            desc.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(output, nullptr, &desc, cpu); cpu.ptr += descriptorStride;
        }
    }
    std::shared_ptr<Slot> AcquireSlot(ID3D12Resource* outputSpec, ID3D12Resource* outputDiff, std::string& error)
    {
        auto slot = AcquireOwnedSlot(error);
        if (slot) SetCommitOutputs(*slot,outputSpec,outputDiff);
        return slot;
    }
    void SetCommitInputs(const Slot& slot, ID3D12Resource* spec, ID3D12Resource* diff) noexcept
    {
        auto cpu = slot.descriptors->GetCPUDescriptorHandleForHeapStart();
        for (auto* input : {spec,diff})
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC view {}; view.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D; view.Texture2D.MipLevels = 1;
            view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            device->CreateShaderResourceView(input,&view,cpu); cpu.ptr += descriptorStride;
        }
    }
    // The raw staged pair remains the canonical commit for existing standalone callers.
    void Commit(ID3D12GraphicsCommandList* list, const Slot& slot,
                ID3D12Resource* outputSpec, ID3D12Resource* outputDiff, SignalEncoding encoding,
                const TitleSignalConstants& titleConstants, float) noexcept
    {
        Commit(list,slot,outputSpec,outputDiff,encoding,titleConstants,0.0f,slot.spec.Get(),slot.diff.Get());
    }
    void Commit(ID3D12GraphicsCommandList* list, const Slot& slot,
                ID3D12Resource* outputSpec, ID3D12Resource* outputDiff, SignalEncoding encoding,
                const TitleSignalConstants& titleConstants, float,
                ID3D12Resource* committedSpec, ID3D12Resource* committedDiff) noexcept
    {
        const bool nativeConstants = HasNativeTitleSignalConstants(titleConstants);
        if (nativeConstants)
        {
            flagCapture.Record(list, titleConstants, slot.flag);
        }
        const auto address = nativeConstants ? slot.flag.resource->GetGPUVirtualAddress() : zeroConstants->GetGPUVirtualAddress();
        // Every fallible allocation and lease admission precedes the guarded commit.
        // Title resources only receive UAV barriers; transitions belong to staging.
        std::array<D3D12_RESOURCE_BARRIER, 4> barriers {};
        for (uint32_t i = 0; i < 2; ++i)
        {
            barriers[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers[i].Transition = {i ? committedDiff : committedSpec, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
            barriers[i+2].Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
            barriers[i+2].UAV.pResource = i ? outputDiff : outputSpec;
        }
        list->ResourceBarrier(static_cast<UINT>(barriers.size()), barriers.data());
        list->SetPipelineState(commitPso.Get()); list->SetComputeRootSignature(commitRoot.Get());
        ID3D12DescriptorHeap* heaps[] = {slot.descriptors.Get()}; list->SetDescriptorHeaps(1, heaps);
        // Keep the five-DWORD ABI, but never let an internal caller enable native RGB blending.
        const uint32_t constants[] = {width, height, uint32_t(encoding), nativeConstants ? 1u : 0u, 0u};
        list->SetComputeRoot32BitConstants(0, 5, constants, 0);
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
        // Metadata retirement happens before any early-return guard so a partial
        // teardown never leaves the shared staging ledger with phantom bytes;
        // the ledger attached before the first warm slot saw every successful
        // allocation, so each allocated slot retires exactly its own charge.
        if (ledger)
        {
            uint64_t retired = 0;
            for (const auto& slot : slots) if (slot) { ledger->Retire(slot->bytes); retired += slot->bytes; }
            if (retired != ledgerBytes)
                LOG_ERROR("[NRD_BRIDGE] staging ledger retirement mismatch: counted {} of {}", retired, ledgerBytes);
        }
        if (!handle) return;
        const auto result = FfxApiProxy::D3D12_DestroyContext(&handle, nullptr);
        if (result != FFX_API_RETURN_OK)
            LOG_ERROR("[NRD_BRIDGE] retired RR context destroy failed: {}", static_cast<uint32_t>(result));
    }
};
struct DispatchLease
{
    FSRDNrdLightingGuardDx12::Lease lightingGuard;
    std::shared_ptr<Context> context;
    std::shared_ptr<Context::Slot> slot;
    LobeRecovery::Prepared recovery; // Retained before the provider; owns every graph binding.
    FlatAlbedoRecovery::Prepared flatAlbedo;
    NativePostMotionAnchor::Prepared inputAnchor;
    // These are exclusively bridge-owned. Title outputs are borrowed and never retained.
    std::array<ComPtr<ID3D12Resource>, 7> inputs;
};
struct PresentLease
{
    std::shared_ptr<Context> context;
    std::shared_ptr<Context::PresentSlot> slot;
    std::shared_ptr<void> sourceOwner;
};

bool CreateContext(ID3D12Device* device, uint32_t width, uint32_t height,
                   std::shared_ptr<Context>& output, std::string& error, bool debugEnabled = false,
                   const std::shared_ptr<NrdBridgeCaptureBudget::StagingLedger>& ledger = {})
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
    // F03: the shared ledger attaches BEFORE any warm slot exists, so every
    // successful allocation (including a partial InitializeCommit) is charged
    // and later retired from exactly the same set. Attaching after creation
    // let the four hot pairs escape admission and retire uncharged bytes.
    fresh->ledger = ledger;
    std::snprintf(fresh->providerName.data(),fresh->providerName.size(),"%s",providerName);
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
            error = "RR AMD default is nonfinite or has invalid debug-depth bounds";
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
             "signals=DirectDiffuse|IndirectSpecular, AMD defaults=7 keys, nativeDebugEnabled={}",
             providerName, versionId, width, height, debugEnabled);
    output = std::move(fresh);
    return true;
}
} // namespace

struct RRRecordedOutput
{
    static constexpr uint8_t Recorded = 0, Preparing = 1, Committed = 2, Abandoned = 3;
    mutable std::atomic<uint8_t> phase {Recorded};
    std::weak_ptr<void> wrapper;
    std::weak_ptr<RecordedComputeLease::Recording> nativeRecording; // Never form a registry ownership cycle.
    std::shared_ptr<DispatchLease> lease;
    ID3D12GraphicsCommandList* source = nullptr; // Borrowed identity, never AddRef the title list.
    ID3D12Resource *selectedSpec = nullptr, *selectedDiff = nullptr;
    uint32_t frameIndex = 0, frameSL = UINT32_MAX;
    uint64_t contextGeneration = 0, recordingId = 0;
    uint64_t resetEpoch = 0;
    FSRDNrdObservation::SelectionPath specularSelection = FSRDNrdObservation::SelectionPath::Unknown;
    FSRDNrdObservation::SelectionPath diffuseSelection = FSRDNrdObservation::SelectionPath::Unknown;
    std::weak_ptr<void> nativeObservationInputs;
    bool recoveryFallback = false, nativeCommitPrepared = false;
    bool flatAlbedoFallback = false;
    bool inputAnchorFallback = false;
    std::string inputAnchorError;
    uint32_t flatAlbedoRoughness = 0;
    std::string flatAlbedoError;
    // F04: these are frozen at the recording frame, exactly like the recovery
    // resources above; getters must never read the wrapper's later state here.
    uint32_t recoveryTier = uint32_t(LobeRecoveryTier::None);
    uint32_t recoveryFallbackReason = uint32_t(LobeRecoveryFallbackReason::None);
    std::string recoveryErrorText; // The real optional error text of THIS recording.
    mutable bool nativeEncodingCaptured = false;
    std::array<uint8_t, 184> providerControl {};
    uint32_t providerCheckerboardSignalFlags = 0, diffuseCheckerboardOrigin = 0, specularCheckerboardOrigin = 0;
    float diffuseRadianceScale = 256.0f, specularRadianceScale = 256.0f;
    bool runtimeTuningValid = false;
    std::array<float,8> runtimeEffective {};
};

struct RRWrapper::Impl
{
    std::shared_ptr<Context> context;
    FSRDRadianceScaleDx12 radianceScale;
    NativePostMotionAnchor inputAnchor;
    bool inputAnchorActive = false, inputAnchorFallback = false;
    std::string inputAnchorError, loggedInputAnchorError;
    FSRDNrdLightingGuardDx12 lightingGuard;
    bool lightingValidationActive = false;
    std::string lightingValidationError, loggedLightingValidationError;
    uint64_t generation = 0;
    uint64_t resetEpoch = 0; // Monotonic actual provider-reset attempt, frozen per recording.
    uint32_t nextFrame = 0;
    bool resetPending = true, historyValid = false;
    bool motionStabilityReady = false; // First enabled frame starts low; updated only after a successful recording.
    FrameParameters previous {};
    RRSettings settings {};
    std::shared_ptr<RRRecoveryFamily> recoveryFamily;
    bool recoveryActive = false, recoveryFallback = false, externalRecoveryFamily = false;
    std::shared_ptr<NrdBridgeCaptureBudget::StagingLedger> stagingLedger; // Shared across retained generations.
    std::shared_ptr<NrdBridgeCaptureBudget::StagingLedger>& EnsureStagingLedger() noexcept
    { if (!stagingLedger) stagingLedger = MakeOwnedShared<NrdBridgeCaptureBudget::StagingLedger>(); return stagingLedger; }
    // D06/D07 tier/fallback diagnostic vocabulary (control-model names, not keys).
    uint32_t recoveryRequestedTier = uint32_t(LobeRecoveryTier::None);
    uint32_t recoveryTier = uint32_t(LobeRecoveryTier::None);
    uint32_t recoveryFallbackReason = uint32_t(LobeRecoveryFallbackReason::None);
    std::string recoveryErrorText; // Last real optional error; cleared on success.
    std::string loggedRecoveryFailure; // Rate-limit key of the last warned fallback.
    bool flatAlbedoActive = false, flatAlbedoFallback = false;
    std::string flatAlbedoError, loggedFlatFailure;
    uint32_t turnAge = 0; // Recorded frames since the last fast camera turn or RR reset (turn colour filter).
    float turnPeakDegrees = 0.0f; // Fastest per-frame rotation of the last turn (0 when only a reset restarted it).
    std::string loggedTurnFailure;
    RRWrapperNativeDebugOutputSnapshot nativeDebug {};
    std::string conventions;
};
// Camera rotation between two views in degrees. trace(A B^T) of the 3x3 blocks is the element-wise product sum,
// so the result does not depend on the row/column storage convention. Non-finite input gives NaN (a turn).
static float CameraTurnDegrees(const DirectX::XMMATRIX& previous, const DirectX::XMMATRIX& current) noexcept
{
    DirectX::XMFLOAT4X4 a, b;
    DirectX::XMStoreFloat4x4(&a, previous); DirectX::XMStoreFloat4x4(&b, current);
    float trace = 0.0f;
    for (int i = 0; i < 3; ++i) for (int j = 0; j < 3; ++j) trace += a.m[i][j] * b.m[i][j];
    if (!std::isfinite(trace)) return std::numeric_limits<float>::quiet_NaN();
    return std::acos(std::clamp((trace - 1.0f) * 0.5f, -1.0f, 1.0f)) * (180.0f / 3.14159265358979f);
}
bool ValidateRRSettings(const RRSettings& settings, std::string& error)
{
    error.clear();
    if (!ValidMotionStability(settings.motionStability))
    { error = "RR motion-adaptive stability settings are invalid"; return false; }
    if (settings.lightingValidation && !ValidMotionThresholds(settings.motionStability))
    { error = "RR lighting validation camera thresholds are invalid"; return false; }
    if (!std::isfinite(settings.recoverySpecular) || !std::isfinite(settings.recoveryDiffuse) ||
        settings.recoverySpecular < 0.0f || settings.recoverySpecular > 1.0f ||
        settings.recoveryDiffuse < 0.0f || settings.recoveryDiffuse > 1.0f)
    { error = "RR detail recovery strengths must be finite values in [0,1]"; return false; }
    if (!ValidFSRDRadianceScale(settings.radianceScale.diffuse) || !ValidFSRDRadianceScale(settings.radianceScale.specular))
    { error = "RR radiance scales must be powers of two in [1,4096]"; return false; }
    if (!std::isfinite(settings.turnColourFrames) || settings.turnColourFrames < 0.0f || settings.turnColourFrames > 600.0f ||
        !std::isfinite(settings.turnColourDegrees) || settings.turnColourDegrees <= 0.0f || settings.turnColourDegrees > 180.0f)
    { error = "RR turn colour filter needs frames in [0,600] and degrees in (0,180]"; return false; }
    if (!std::isfinite(settings.turnBrightnessAmount) || settings.turnBrightnessAmount < 0.0f || settings.turnBrightnessAmount > 0.5f ||
        !std::isfinite(settings.turnBrightnessFrames) || settings.turnBrightnessFrames < 1.0f || settings.turnBrightnessFrames > 120.0f)
    { error = "RR turn brightness correction needs amount in [0,0.5] and frames in [1,120]"; return false; }
    if (!std::isfinite(settings.postMotionAnchorStrength) || settings.postMotionAnchorStrength < 0.0f || settings.postMotionAnchorStrength > 1.0f)
    { error = "RR post-motion anchor strength must be finite in [0,1]"; return false; }
    const auto& f = settings.flatAlbedo;
    if (f.roughness > 1023 || f.historyLength < 1 || f.historyLength > 6 ||
        !std::isfinite(f.strength) || f.strength < 0 || f.strength > 1 ||
        !std::isfinite(f.anchor) || f.anchor < 0 || f.anchor > 8 ||
        !std::isfinite(f.mix) || f.mix < 0 || f.mix > 1 ||
        !std::isfinite(f.reflectionPolish) || f.reflectionPolish < 0 || f.reflectionPolish > 1 ||
        !std::isfinite(f.temporalDenoise) || f.temporalDenoise < 0 || f.temporalDenoise > 2)
    { error = "RR Flat Albedo Recovery settings are invalid"; return false; }
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
    const float nativeSpecularBlend = NormalizeNativeSpecularBlend(requested.nativeSpecularBlend);
    if (!impl_ && !requested.overrideMask && requested.nativeDebugView == -1 &&
        requested.nativeDebugViewport == 0 && !requested.preserveNativeMaterialIDs && !requested.nativeTemporalMotion &&
        !requested.nativeMaterialGuides && !requested.lobeRecovery && !requested.flatAlbedo.enabled && !requested.surfaceValidFill &&
        !requested.radianceScale.enabled && !requested.motionStability.enabled && !requested.lightingValidation && !requested.turnColourFilter && !requested.postMotionAnchor && !requested.turnBrightness && nativeSpecularBlend == 0.0f) return true;
    if (!impl_) impl_ = MakeOwnedShared<Impl>();
    // The D02/WP08 fill selector changes which raw-decode pipeline produces the
    // RR inputs, and the D01 legacy selector changes the motion Z provenance;
    // either flip must reset provider history like the other visual path
    // selectors instead of silently mixing profiles inside one history.
    if (impl_->settings.preserveNativeMaterialIDs != requested.preserveNativeMaterialIDs ||
        impl_->settings.nativeTemporalMotion != requested.nativeTemporalMotion ||
        impl_->settings.nativeMaterialGuides != requested.nativeMaterialGuides ||
        impl_->settings.lobeRecovery != requested.lobeRecovery ||
        impl_->settings.flatAlbedo != requested.flatAlbedo ||
        impl_->settings.radianceScale != requested.radianceScale ||
        impl_->settings.recoverySpecular != requested.recoverySpecular ||
        impl_->settings.recoveryDiffuse != requested.recoveryDiffuse ||
        impl_->settings.surfaceValidFill != requested.surfaceValidFill ||
        impl_->settings.legacyMotionDepth != requested.legacyMotionDepth)
    { impl_->resetPending = true; impl_->nativeDebug = {}; }
    if (impl_->settings.nativeDebugView != requested.nativeDebugView ||
        impl_->settings.nativeDebugViewport != requested.nativeDebugViewport) impl_->nativeDebug = {};
    if (impl_->context && impl_->settings.flatAlbedo != requested.flatAlbedo) impl_->context->flatAlbedo.reset();
    if (requested.motionStability.enabled && !impl_->settings.motionStability.enabled) impl_->motionStabilityReady = false;
    if (impl_->settings.lightingValidation != requested.lightingValidation)
    {
        impl_->lightingGuard.Reset();impl_->lightingValidationActive=false;
        impl_->lightingValidationError.clear();impl_->loggedLightingValidationError.clear();
    }
    const bool wasAnchorEnabled = impl_->settings.postMotionAnchor && impl_->settings.postMotionAnchorStrength > 0.0f;
    const bool anchorEnabled = requested.postMotionAnchor && requested.postMotionAnchorStrength > 0.0f;
    if (wasAnchorEnabled != anchorEnabled)
    {
        impl_->inputAnchor.DiscardRecordingHistory();
        impl_->inputAnchorActive = impl_->inputAnchorFallback = false; impl_->inputAnchorError.clear();
    }
    impl_->settings = {};
    impl_->settings.overrideMask = requested.overrideMask;
    impl_->settings.nativeDebugView = requested.nativeDebugView;
    impl_->settings.nativeDebugViewport = requested.nativeDebugViewport;
    impl_->settings.preserveNativeMaterialIDs = requested.preserveNativeMaterialIDs;
    impl_->settings.nativeTemporalMotion = requested.nativeTemporalMotion;
    impl_->settings.nativeMaterialGuides = requested.nativeMaterialGuides;
    impl_->settings.legacyMotionDepth = requested.legacyMotionDepth;
    impl_->settings.lobeRecovery = requested.lobeRecovery;
    impl_->settings.flatAlbedo = requested.flatAlbedo;
    impl_->settings.radianceScale = requested.radianceScale;
    impl_->settings.motionStability = requested.motionStability;
    impl_->settings.lightingValidation = requested.lightingValidation;
    impl_->settings.recoverySpecular = requested.recoverySpecular;
    impl_->settings.recoveryDiffuse = requested.recoveryDiffuse;
    impl_->settings.surfaceValidFill = requested.surfaceValidFill;
    impl_->settings.nativeSpecularBlend = nativeSpecularBlend;
    // Input-side only and fading: switching it never resets RR history.
    impl_->settings.turnColourFilter = requested.turnColourFilter;
    impl_->settings.turnColourFrames = requested.turnColourFrames;
    impl_->settings.turnColourDegrees = requested.turnColourDegrees;
    impl_->settings.postMotionAnchor = requested.postMotionAnchor;
    impl_->settings.postMotionAnchorStrength = requested.postMotionAnchorStrength;
    impl_->settings.turnBrightness = requested.turnBrightness;
    impl_->settings.turnBrightnessAmount = requested.turnBrightnessAmount;
    impl_->settings.turnBrightnessFrames = requested.turnBrightnessFrames;
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
    const auto previousValues = impl_->context->configuredValues;
    try
    {
        if (!impl_->context->ApplySettings(impl_->settings, lightingChanged, error))
        { DiscardRecordingHistory(); return false; }
    }
    catch (...) { DiscardRecordingHistory(); throw; }
    if (previousValues != impl_->context->configuredValues) impl_->nativeDebug = {};
    if (lightingChanged) impl_->resetPending = true;
    return true;
}
RRSettingsState RRWrapper::GetSettingsState() const noexcept
{
    RRSettingsState state;
    if (impl_) { state.lightingValidationActive=impl_->lightingValidationActive;state.lightingValidationLastError=impl_->lightingValidationError; }
    if (!impl_) return state;
    state.requested = impl_->settings;
    state.postMotionAnchorActive = impl_->inputAnchorActive;
    state.postMotionAnchorFallback = impl_->inputAnchorFallback;
    state.postMotionAnchorLastError = impl_->inputAnchorError;
    state.flatAlbedoActive = impl_->flatAlbedoActive;
    state.flatAlbedoFallback = impl_->flatAlbedoFallback;
    state.flatAlbedoLastError = impl_->flatAlbedoError;
    state.lobeRecoveryActive = impl_->recoveryActive;
    state.lobeRecoveryFallback = impl_->recoveryFallback;
    state.lobeRecoveryRequestedTier = impl_->recoveryRequestedTier;
    state.lobeRecoveryTier = impl_->recoveryTier;
    state.lobeRecoveryFallbackReason = impl_->recoveryFallbackReason;
    state.lobeRecoveryLastError = impl_->recoveryErrorText;
    if (impl_->context)
    {
        state.ready = true;
        state.defaults = impl_->context->defaultValues;
        state.effective = impl_->context->configuredValues;
    }
    return state;
}
void RRWrapper::SetRecoveryFamily(const std::shared_ptr<RRRecoveryFamily>& family) noexcept
{
    if (impl_) { impl_->recoveryFamily = family; impl_->externalRecoveryFamily = true; }
}
RRWrapperNativeDebugOutputSnapshot RRWrapper::GetNativeDebugOutputSnapshot() const noexcept
{
    return impl_ ? impl_->nativeDebug : RRWrapperNativeDebugOutputSnapshot {};
}
bool RRWrapper::PresentNativeDebug(ID3D12GraphicsCommandList* list, ID3D12Resource* output,
                                   D3D12_RESOURCE_STATES outputState, uint32_t frameSL, std::string& error,
                                   bool orderedAcrossLists, const OutputCommitGuard& guard)
{
    error.clear();
    const auto reject = [&](const char* reason) { error = reason; return false; };
    if (!impl_ || !impl_->context || impl_->settings.nativeDebugView == -1 ||
        !impl_->nativeDebug.resource || !impl_->nativeDebug.owner || frameSL == UINT32_MAX ||
        impl_->nativeDebug.frameSL != frameSL)
        return reject("RR native debug output for this SL frame is unavailable");
    return PresentNativeDebug(list, output, outputState, impl_->nativeDebug, error, orderedAcrossLists, guard);
}
bool RRWrapper::PresentNativeDebug(ID3D12GraphicsCommandList* list, ID3D12Resource* output,
                                   D3D12_RESOURCE_STATES outputState, const RRWrapperNativeDebugOutputSnapshot& image,
                                   std::string& error, bool orderedAcrossLists, const OutputCommitGuard& guard)
{
    error.clear();
    const auto reject = [&](const char* reason) { error = reason; return false; };
    if (!impl_ || !impl_->context || impl_->settings.nativeDebugView == -1 ||
        !image.resource || !image.owner || image.frameSL == UINT32_MAX ||
        !TextureMatches(image.resource, image.width, image.height, DXGI_FORMAT_R16G16B16A16_FLOAT))
        return reject("RR native debug source snapshot is missing or incompatible");
    if (image.state != D3D12_RESOURCE_STATE_UNORDERED_ACCESS || !image.recording ||
        (image.recording != list && !orderedAcrossLists))
        return reject("RR native debug source recording has no proven GPU ordering");
    if (!list || !output || output == image.resource ||
        (list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT && list->GetType() != D3D12_COMMAND_LIST_TYPE_COMPUTE))
        return reject("RR native debug presentation command list or output is invalid");
    const auto desc = output->GetDesc();
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || !desc.Width || !desc.Height ||
        desc.Width > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION || desc.Height > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION ||
        desc.DepthOrArraySize != 1 || desc.MipLevels != 1 || desc.SampleDesc.Count != 1 ||
        !(desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))
        return reject("RR native debug presentation output shape or UAV flags are invalid");
    // These floating/normalized color targets have the intended RGB channels;
    // typed-load support is also required to preserve a target's existing alpha.
    switch (desc.Format)
    {
    case DXGI_FORMAT_R16G16B16A16_FLOAT: case DXGI_FORMAT_R32G32B32A32_FLOAT:
    case DXGI_FORMAT_R11G11B10_FLOAT: case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R10G10B10A2_UNORM: break;
    default: return reject("RR native debug presentation output format is unsupported");
    }
    ComPtr<ID3D12Device> device, other;
    if (FAILED(output->GetDevice(IID_PPV_ARGS(&device))) ||
        !SameDevice(device.Get(), impl_->context->device.Get()) ||
        FAILED(list->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device.Get(), other.Get()))
        return reject("RR native debug presentation devices do not match");
    other.Reset();
    if (FAILED(image.resource->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device.Get(), other.Get()))
        return reject("RR native debug source device does not match presentation");
    D3D12_FEATURE_DATA_FORMAT_SUPPORT support {}; support.Format = desc.Format;
    if (FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &support, sizeof(support))) ||
        !(support.Support2 & D3D12_FORMAT_SUPPORT2_UAV_TYPED_LOAD) ||
        !(support.Support2 & D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE))
        return reject("RR native debug presentation target lacks typed UAV load/store");
    auto lease = MakeOwnedShared<PresentLease>(); lease->context = impl_->context; lease->sourceOwner = image.owner;
    lease->slot = lease->context->AcquirePresentSlot(image.resource, output, desc.Format, error);
    if (!lease->slot) return false;
    if (!ResTrack_Dx12::RetainComputeDispatch(device.Get(), list, lease))
        return reject("RR native debug presentation lifetime tracking is unavailable");
    struct PreparedPresent
    {
        const Context* context;
        const Context::PresentSlot* slot;
        ID3D12GraphicsCommandList* list;
        ID3D12Resource *source, *output;
        D3D12_RESOURCE_STATES state;
        uint32_t sourceWidth, sourceHeight, outputWidth, outputHeight;
    } prepared {lease->context.get(), lease->slot.get(), list, image.resource, output, outputState,
        image.width, image.height, static_cast<uint32_t>(desc.Width), desc.Height};
    const auto record=+[](void* state) noexcept {
        const auto& value=*static_cast<PreparedPresent*>(state);
        value.context->Present(value.list,*value.slot,value.source,value.output,value.state,
            value.sourceWidth,value.sourceHeight,value.outputWidth,value.outputHeight);
    };
    if (guard.admit && !guard.admit(guard.state, record, &prepared))
    { error = "RR native debug presentation ticket expired before final admission"; return false; }
    if (!guard.admit) record(&prepared);
    return true;
}
bool RRWrapper::PrepareFrame(const SLConstantsSnapshot& snapshot, bool requestedReset,
                            FrameParameters& out, std::string& error)
{
    error.clear();
    out = {};
    if (!impl_) impl_ = MakeOwnedShared<Impl>();
    const auto reject = [&](const char* reason) {
        impl_->resetPending = true;
        impl_->nativeDebug = {};
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
    if (requestedReset || snapshot.frameIndex != impl_->nativeDebug.frameSL) impl_->nativeDebug = {};
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
            << ", cameraMotionIncluded=1; signals demodulated RGB; albedos linear native material or white fallback (see material admission counters); RR output alpha preserved";
        impl_->conventions = log.str();
    }
    return true;
}

bool RRWrapper::RecordOwned(ID3D12GraphicsCommandList* list, const ConvertedResources& input,
                            const FrameParameters& frame, RRRecordedOutputLease& output, std::string& error,
                            NrdBridgeStagePerf::Sample* profiling, const RRNativeObservationRequest& observations)
{
    return RecordOwnedImpl(list,input,frame,output,error,profiling,true,observations);
}

bool RRWrapper::RecordOwnedImpl(ID3D12GraphicsCommandList* list, const ConvertedResources& sourceInput,
                                const FrameParameters& frame, RRRecordedOutputLease& output, std::string& error,
                                NrdBridgeStagePerf::Sample* profiling, bool prepareNativeCommit,
                                const RRNativeObservationRequest& observations)
{
    error.clear(); output.reset();
    auto input = sourceInput;
    if (!impl_) impl_ = MakeOwnedShared<Impl>();
    impl_->nativeDebug = {}; impl_->recoveryActive = impl_->recoveryFallback = false;
    const auto reject = [&](const char* reason) {
        impl_->resetPending = true; error = reason; return false;
    };
    if (!list || (list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT && list->GetType() != D3D12_COMMAND_LIST_TYPE_COMPUTE))
        return reject("RR command list is missing or unsupported");
    if (!frame.camera.Complete() || frame.motionVectors3D || frame.frameIndex != impl_->nextFrame)
        return reject("RR frame parameters are missing, unsupported or stale");
    if (!input.width || !input.height) return reject("RR dimensions are invalid");
    const std::array<ID3D12Resource*, 7> inputs {input.spec,input.diff,input.linearDepth,input.motion,
        input.normals,input.specAlbedo,input.diffAlbedo};
    const std::array<DXGI_FORMAT, 7> formats {DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
        DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R10G10B10A2_UNORM,
        DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R8G8B8A8_UNORM};
    for (size_t i = 0; i < inputs.size(); ++i)
        if (!TextureMatches(inputs[i],input.width,input.height,formats[i]))
            return reject("RR bridge resource format or size is invalid");
    ComPtr<ID3D12Device> device, other;
    if (FAILED(list->GetDevice(IID_PPV_ARGS(&device)))) return reject("RR command list device is unavailable");
    for (auto* resource : inputs)
    {
        other.Reset();
        if (FAILED(resource->GetDevice(IID_PPV_ARGS(&other))) || !SameDevice(device.Get(),other.Get()))
            return reject("RR bridge resource device does not match the command list");
    }
    const bool recreate = !impl_->context || impl_->context->width != input.width ||
        impl_->context->height != input.height || !SameDevice(device.Get(),impl_->context->device.Get());
    if (recreate)
    {
        impl_->inputAnchor.DiscardRecordingHistory();
        std::shared_ptr<Context> fresh;
        if (!CreateContext(device.Get(),input.width,input.height,fresh,error,impl_->settings.nativeDebugView != -1,
            impl_->EnsureStagingLedger()))
        { impl_->resetPending = true; return false; }
        bool lightingChanged = false;
        try
        {
            if (!fresh->ApplySettings(impl_->settings,lightingChanged,error))
            { DiscardRecordingHistory(); return false; }
        }
        catch (...) { DiscardRecordingHistory(); throw; }
        fresh->generation = ++impl_->generation;
        impl_->context = std::move(fresh); // Old GPU leases retain their exact physical generation.
        if(impl_->settings.lightingValidation)
        { impl_->lightingGuard.Reset();impl_->lightingValidationActive=false; }
        impl_->resetPending = true;
    }
    auto lease = MakeOwnedShared<DispatchLease>(); lease->context = impl_->context;
    lease->slot = lease->context->AcquireOwnedSlot(error);
    if (!lease->slot) { impl_->resetPending = true; return false; }
    // D06/D07 requested/effective tier + rate-limited failure text division.
    // Names are proposed control-model vocabulary; not INI keys.
    impl_->recoveryRequestedTier = impl_->settings.lobeRecovery ?
        uint32_t(LobeRecoveryTier::FullPrecision) : uint32_t(LobeRecoveryTier::None);
    impl_->recoveryTier = uint32_t(LobeRecoveryTier::None);
    impl_->recoveryErrorText.clear();
    uint32_t recoverySkipReason = uint32_t(LobeRecoveryFallbackReason::None);
    if (!impl_->settings.lobeRecovery)
        recoverySkipReason = uint32_t(LobeRecoveryFallbackReason::NotRequested);
    else if (lease->context->debugEnabled)
        recoverySkipReason = uint32_t(LobeRecoveryFallbackReason::DebugConstraint);
    else if (impl_->settings.recoverySpecular == 0.0f && impl_->settings.recoveryDiffuse == 0.0f)
        recoverySkipReason = uint32_t(LobeRecoveryFallbackReason::ZeroStrength);
    impl_->recoveryFallbackReason = recoverySkipReason;
    // Deferred native recording must know every late capture object exists before provider/suppression.
    if (prepareNativeCommit && (!lease->context->PrepareTableFlags(error,303) ||
        !lease->context->PrepareTableFlags(error,36))) { impl_->resetPending = true; return false; }
    for (size_t i = 0; i < inputs.size(); ++i) lease->inputs[i] = inputs[i];
    bool reset = frame.reset || impl_->resetPending || recreate;
    // Prepare the complete input graph before recovery/provider/suppression.
    // Recovery reads the same corrected physical pair as RR, so NZR cannot
    // silently restore the uncorrected post-motion level after denoising.
    impl_->inputAnchorActive = impl_->inputAnchorFallback = false;
    impl_->inputAnchorError.clear();
    if (impl_->settings.postMotionAnchor && impl_->settings.postMotionAnchorStrength > 0.0f && !lease->context->debugEnabled)
    {
        if (!impl_->recoveryFamily && !impl_->externalRecoveryFamily) impl_->recoveryFamily = CreateRRRecoveryFamily();
        bool prepared = false;
        if (impl_->recoveryFamily)
        {
            const std::shared_ptr<LobeRecovery::Family> family(impl_->recoveryFamily,&impl_->recoveryFamily->budget);
            auto anchorFrame = frame; anchorFrame.reset = reset;
            prepared = impl_->inputAnchor.Prepare(device.Get(),list,input,anchorFrame,true,
                impl_->settings.postMotionAnchorStrength,family,lease->inputAnchor,impl_->inputAnchorError);
        }
        else impl_->inputAnchorError = "Native anchor shared family unavailable";
        if (prepared)
        {
            input.spec = lease->inputAnchor.specular; input.diff = lease->inputAnchor.diffuse;
            impl_->inputAnchorActive = lease->inputAnchor.active;
        }
        else
        {
            impl_->inputAnchorFallback = true;
            if (impl_->loggedInputAnchorError != impl_->inputAnchorError)
            { LOG_WARN("[NRD_BRIDGE] native post-motion anchor inactive: {}",impl_->inputAnchorError); impl_->loggedInputAnchorError = impl_->inputAnchorError; }
        }
    }
    auto* committedSpec = lease->slot->spec.Get(); auto* committedDiff = lease->slot->diff.Get();
    auto selectionPath = FSRDNrdObservation::SelectionPath::RawRR;
    bool recoveryFallback = false;
    const bool requestRecovery = recoverySkipReason == uint32_t(LobeRecoveryFallbackReason::None);
    if (requestRecovery)
    {
        bool prepared = false;
        try
        {
            if (!impl_->recoveryFamily && !impl_->externalRecoveryFamily) impl_->recoveryFamily = CreateRRRecoveryFamily();
            if (impl_->recoveryFamily)
            {
                if (!lease->context->recovery) lease->context->recovery.emplace();
                LobeRecoveryInputs recoveryInputs {input.spec,input.diff,input.linearDepth,input.motion,input.normals,
                    committedSpec,committedDiff,input.width,input.height};
                LobeRecoveryFrame recoveryFrame;
                recoveryFrame.frameIndex = frame.frameIndex; recoveryFrame.reset = reset;
                recoveryFrame.jitterPixels = {frame.jitter.x,frame.jitter.y};
                recoveryFrame.jitterDeltaUv = {(frame.previousJitter.x-frame.jitter.x)/input.width,
                    (frame.previousJitter.y-frame.jitter.y)/input.height};
                recoveryFrame.strength = {impl_->settings.recoverySpecular,impl_->settings.recoveryDiffuse};
                std::string optionalError;
                const std::shared_ptr<LobeRecovery::Family> family(impl_->recoveryFamily,&impl_->recoveryFamily->budget);
                prepared = lease->context->recovery->Prepare(device.Get(),list,recoveryInputs,recoveryFrame,family,lease->recovery,optionalError);
            }
        }
        catch (...) { prepared = false; }
        if (prepared)
        {
            committedSpec = lease->recovery.specular; committedDiff = lease->recovery.diffuse;
            selectionPath = FSRDNrdObservation::SelectionPath::LobeRecovery;
            lease->context->SetCommitInputs(*lease->slot,committedSpec,committedDiff);
            impl_->recoveryFallbackReason = uint32_t(LobeRecoveryFallbackReason::None);
        }
        else
        {
            lease->recovery = {}; lease->context->recovery.reset(); recoveryFallback = true;
            impl_->recoveryFallbackReason = !impl_->recoveryFamily ?
                uint32_t(LobeRecoveryFallbackReason::ExternalFamilyUnavailable) :
                LobeRecoveryCapacityText(error) ?
                uint32_t(LobeRecoveryFallbackReason::FamilyCapacity) :
                uint32_t(LobeRecoveryFallbackReason::PreparationFailed);
            // Real helper text travels with the effective fallback; rate limit
            // is one log per new (reason,text) pair, never per frame.
            if (error.empty())
                impl_->recoveryErrorText = !impl_->recoveryFamily ?
                    "Lobe recovery family is unavailable" : "Lobe recovery preparation failed";
            else impl_->recoveryErrorText = error;
            const std::string failureKey = std::string(
                LobeRecoveryFallbackReasonName(impl_->recoveryFallbackReason)) + "|" + impl_->recoveryErrorText;
            if (impl_->loggedRecoveryFailure != failureKey)
            {
                impl_->loggedRecoveryFailure = failureKey;
                LOG_WARN("[NRD_BRIDGE] lobe recovery {} for this Consumer: {}",
                    LobeRecoveryFallbackReasonName(impl_->recoveryFallbackReason), impl_->recoveryErrorText);
            }
        }
    }
    else lease->context->recovery.reset();
    // Compatibility floor and existing Flat Albedo Recovery are one prepared
    // unit: never floor RR's geometry if the detail graph cannot be retained.
    const auto& flat = impl_->settings.flatAlbedo;
    const bool requestFlat = flat.enabled && flat.strength > 0 && flat.roughness > 0 && !lease->context->debugEnabled;
    bool flatPrepared = false;
    impl_->flatAlbedoError.clear();
    if (requestFlat)
    {
        try
        {
            if (!impl_->recoveryFamily && !impl_->externalRecoveryFamily) impl_->recoveryFamily = CreateRRRecoveryFamily();
            if (impl_->recoveryFamily)
            {
                if (!lease->context->flatAlbedo) lease->context->flatAlbedo.emplace();
                const LobeRecoveryInputs flatInputs {input.spec,input.diff,input.linearDepth,input.motion,input.normals,
                    committedSpec,committedDiff,input.width,input.height};
                LobeRecoveryFrame flatFrame; flatFrame.frameIndex = frame.frameIndex; flatFrame.reset = reset;
                if (!reset)
                {
                    const float dx = frame.cameraPosition.x - frame.previousCameraPosition.x;
                    const float dy = frame.cameraPosition.y - frame.previousCameraPosition.y;
                    const float dz = frame.cameraPosition.z - frame.previousCameraPosition.z;
                    const float focal = std::abs(DirectX::XMVectorGetX(frame.camera.projection.r[0]))*0.5f*float(input.width);
                    const float parallax = std::sqrt(dx*dx+dy*dy+dz*dz)*focal;
                    flatFrame.parallaxPixels = std::isfinite(parallax) ? parallax : 0.0f;
                }
                if (frame.camera.Complete())
                {
                    DirectX::XMFLOAT4X4 view, projection;
                    DirectX::XMStoreFloat4x4(&view,frame.camera.view); DirectX::XMStoreFloat4x4(&projection,frame.camera.projection);
                    for (int i = 0;i < 16;++i) { flatFrame.view[i] = view.m[i/4][i%4]; flatFrame.projection[i] = projection.m[i/4][i%4]; }
                    flatFrame.camera = true;
                }
                const std::shared_ptr<LobeRecovery::Family> family(impl_->recoveryFamily,&impl_->recoveryFamily->budget);
                flatPrepared = lease->context->flatAlbedo->Prepare(device.Get(),list,flatInputs,flatFrame,flat,
                    family,lease->flatAlbedo,impl_->flatAlbedoError);
            }
            else impl_->flatAlbedoError = "Flat recovery shared family is unavailable";
        }
        catch (...) { impl_->flatAlbedoError = "Flat recovery preparation allocation failed"; }
        if (!flatPrepared)
        {
            lease->flatAlbedo = {}; lease->context->flatAlbedo.reset();
            if (impl_->loggedFlatFailure != impl_->flatAlbedoError)
            {
                impl_->loggedFlatFailure = impl_->flatAlbedoError;
                LOG_WARN("[NRD_BRIDGE] Flat Albedo Recovery unavailable; original roughness retained: {}",impl_->flatAlbedoError);
            }
        }
    }
    else lease->context->flatAlbedo.reset();
    if (lease->context->flatWasActive != flatPrepared) reset = true;
    if (impl_->settings.motionStability.enabled)
    {
        const auto& s = impl_->settings.motionStability;
        const float degrees = CameraTurnDegrees(impl_->previous.camera.view, frame.camera.view);
        const auto& a = frame.cameraPosition; const auto& b = frame.previousCameraPosition;
        const float dx = a.x-b.x, dy = a.y-b.y, dz = a.z-b.z;
        const float metres = std::sqrt(dx*dx + dy*dy + dz*dz);
        const float value = NextMotionStability(s,lease->context->configuredValues[1],
            !reset && frame.previousValid && impl_->motionStabilityReady,degrees,metres);
        if (!lease->context->ApplyMotionStability(value,error))
        { DiscardRecordingHistory(); return false; }
    }
    if (flatPrepared)
    {
        committedSpec = lease->flatAlbedo.specular; committedDiff = lease->flatAlbedo.diffuse;
        selectionPath = FSRDNrdObservation::SelectionPath::FlatAlbedo;
        lease->context->SetCommitInputs(*lease->slot,committedSpec,committedDiff);
    }
    // Allocate the public opaque owner before any provider commands can be recorded.
    auto recorded = MakeOwnedShared<RRRecordedOutput>();
    recorded->wrapper = impl_; recorded->lease = lease; recorded->source = list;
    recorded->selectedSpec = committedSpec; recorded->selectedDiff = committedDiff;
    recorded->specularSelection = recorded->diffuseSelection = selectionPath;
    if (reset) ++impl_->resetEpoch;
    recorded->resetEpoch = impl_->resetEpoch;
    recorded->frameIndex = frame.frameIndex; recorded->frameSL = frame.streamlineFrame;
    recorded->contextGeneration = lease->context->generation; recorded->recoveryFallback = recoveryFallback;
    recorded->nativeCommitPrepared = prepareNativeCommit;
    recorded->flatAlbedoFallback = requestFlat && !flatPrepared;
    recorded->inputAnchorFallback = impl_->inputAnchorFallback;
    recorded->inputAnchorError = impl_->inputAnchorError;
    recorded->flatAlbedoRoughness = flatPrepared ? flat.roughness : 0;
    recorded->flatAlbedoError = impl_->flatAlbedoError;
    if (!ResTrack_Dx12::RetainComputeDispatch(device.Get(),list,lease))
        return reject("RR recorded-dispatch lifetime tracking is unavailable");
    const auto nativeRecording = RecordedComputeLease::Capture(list);
    if (!nativeRecording || !nativeRecording->id) return reject("RR native recording identity is unavailable");
    recorded->nativeRecording = nativeRecording; recorded->recordingId = nativeRecording->id;
    // Leased before recording: the guard and every recovery reader see initialized physical copies.
    if (lease->inputAnchor.owner) impl_->inputAnchor.RecordInputs(list,lease->inputAnchor);
    if (observations.record && observations.domain)
        recorded->nativeObservationInputs = observations.record(device.Get(),list,sourceInput,input,
            observations.domain,recorded->recordingId,recorded->contextGeneration,recorded->resetEpoch,
            recorded->frameIndex,recorded->frameSL,reset);
    // Post-turn colour filter: full weight on a fast turn or RR reset, fading over turnColourFrames recorded frames.
    // Post-turn brightness correction: gain 1/(1+bias), the bias scaled by the turn's peak speed (full at 20 deg/frame)
    // and fading over turnBrightnessFrames. A reset without a fast turn restarts the colour fade only.
    float turnWeight = 0.0f, turnGain = 1.0f;
    if (impl_->settings.turnColourFilter || impl_->settings.turnBrightness)
    {
        const float degrees = CameraTurnDegrees(impl_->previous.camera.view, frame.camera.view);
        const bool fast = !(degrees <= impl_->settings.turnColourDegrees);
        if (reset || !impl_->historyValid || fast)
        {
            const float measured = fast && std::isfinite(degrees) ? degrees : 0.0f;
            impl_->turnPeakDegrees = impl_->turnAge == 0u ? std::max(impl_->turnPeakDegrees, measured) : measured;
            impl_->turnAge = 0u;
        }
        else impl_->turnAge = std::min(impl_->turnAge + 1u, 1u << 20);
        const float age = float(impl_->turnAge);
        if (impl_->settings.turnColourFilter)
        {
            const float frames = impl_->settings.turnColourFrames;
            turnWeight = frames <= 0.0f ? 1.0f : std::max(0.0f, 1.0f - age / frames);
        }
        if (impl_->settings.turnBrightness)
        {
            constexpr float FullStrengthDegrees = 20.0f;
            const float bias = impl_->settings.turnBrightnessAmount * std::min(1.0f, impl_->turnPeakDegrees / FullStrengthDegrees) *
                std::max(0.0f, 1.0f - age / impl_->settings.turnBrightnessFrames);
            turnGain = 1.0f / (1.0f + bias);
        }
        std::string turnError;
        if ((turnWeight > 0.0f || turnGain < 1.0f) && !lease->context->EnsureTurnColour(*lease->slot, turnError))
        {
            if (impl_->loggedTurnFailure != turnError)
            {
                impl_->loggedTurnFailure = turnError;
                LOG_WARN("[NRD_BRIDGE] Turn colour/brightness pass unavailable; RR reads the unfiltered inputs: {}", turnError);
            }
            turnWeight = 0.0f; turnGain = 1.0f;
        }
    }
    const bool turnPass = turnWeight > 0.0f || turnGain < 1.0f;
    ID3D12Resource* rrSpec = turnPass ? lease->context->turnSignals[0].Get() : input.spec;
    ID3D12Resource* rrDiff = turnPass ? lease->context->turnSignals[1].Get() : input.diff;
    ffxDispatchDescDenoiserDirectDiffuse diffuse {};
    diffuse.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
    diffuse.signal.input = ffxApiGetResourceDX12(rrDiff, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    diffuse.signal.output = ffxApiGetResourceDX12(lease->slot->diff.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
    ffxDispatchDescDenoiserIndirectSpecular specular {};
    specular.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;
    specular.signal.input = ffxApiGetResourceDX12(rrSpec, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    specular.signal.output = ffxApiGetResourceDX12(lease->slot->spec.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
    diffuse.header.pNext = &specular.header; // AMD1.2 ABI ascending order: 0x44 then 0x48.
    ffxDispatchDescDenoiserDebugView nativeDebug {};
    if (lease->context->debugEnabled)
    {
        lease->context->ClearNativeDebug(list, *lease->slot);
        nativeDebug.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW;
        nativeDebug.output = ffxApiGetResourceDX12(lease->slot->nativeDebug.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
        nativeDebug.outputSize = {input.width, input.height};
        nativeDebug.mode = static_cast<uint32_t>(impl_->settings.nativeDebugView);
        nativeDebug.viewportIndex = impl_->settings.nativeDebugViewport;
        specular.header.pNext = &nativeDebug.header;
    }
    ffxDispatchDescDenoiser dispatch {};
    dispatch.header.type = FFX_API_DISPATCH_DESC_TYPE_DENOISER;
    dispatch.header.pNext = &diffuse.header;
    dispatch.commandList = list;
    dispatch.linearDepth = ffxApiGetResourceDX12(input.linearDepth, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.motionVectors = ffxApiGetResourceDX12(input.motion, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.normals = ffxApiGetResourceDX12(flatPrepared ? lease->flatAlbedo.normals : input.normals, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.specularAlbedo = ffxApiGetResourceDX12(input.specAlbedo, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.diffuseAlbedo = ffxApiGetResourceDX12(input.diffAlbedo, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    dispatch.motionVectorScale = { 1.0f, 1.0f, 1.0f };
    dispatch.jitterOffsets = { frame.jitter.x, frame.jitter.y };
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
    if (impl_->settings.lightingValidation)
    {
        const auto& s=impl_->settings.motionStability;
        const float degrees=CameraTurnDegrees(impl_->previous.camera.view,frame.camera.view);
        const auto& a=frame.cameraPosition;const auto& b=frame.previousCameraPosition;
        const float dx=a.x-b.x,dy=a.y-b.y,dz=a.z-b.z;
        const float metres=std::sqrt(dx*dx+dy*dy+dz*dz);
        impl_->lightingValidationActive=false;
        if(reset) impl_->lightingGuard.Invalidate();
        if(frame.previousValid&&(!std::isfinite(degrees)||!std::isfinite(metres)||
            degrees>s.rotationDegrees||metres>s.translationMetres)) impl_->lightingGuard.Invalidate();
        else
        {
            std::string optionalError;
            const float projectionToViewY=DirectX::XMVectorGetY(DirectX::XMMatrixInverse(nullptr,frame.camera.projection).r[1]);
            if(impl_->lightingGuard.Before(device.Get(),list,input.width,input.height,frame.frameIndex,
                sourceInput.diff,sourceInput.spec,input.motion,input.linearDepth,lease->lightingGuard,optionalError,
                lease->context->configuredValues[5],projectionToViewY,frame.farPlane))
            {
                dispatch.motionVectors=ffxApiGetResourceDX12(lease->lightingGuard->Motion(),FFX_API_RESOURCE_STATE_COMPUTE_READ);
                impl_->lightingValidationActive=true;impl_->lightingValidationError.clear();
            }
            else
            {
                // Optional preparation failed before any GPU mutation. Lighting still goes through ordinary RR.
                impl_->lightingGuard.Invalidate();impl_->lightingValidationError=optionalError;
                if(impl_->loggedLightingValidationError!=optionalError)
                { LOG_WARN("[NRD_BRIDGE] lighting validation inactive: {}",optionalError);impl_->loggedLightingValidationError=optionalError; }
            }
        }
    }
    recorded->providerCheckerboardSignalFlags = lease->context->create.checkerboardSignalFlags;
    recorded->diffuseCheckerboardOrigin = diffuse.signal.checkerboardOrigin;
    recorded->specularCheckerboardOrigin = specular.signal.checkerboardOrigin;
    std::memcpy(recorded->providerControl.data(),reinterpret_cast<const uint8_t*>(&dispatch) +
        offsetof(ffxDispatchDescDenoiser,motionVectorScale),recorded->providerControl.size());
    if (impl_->settings.motionStability.enabled)
    { recorded->runtimeTuningValid=true;recorded->runtimeEffective=lease->context->configuredValues; }
    ScopedSkipHeapCapture skipHeapCapture;
    if (flatPrepared) lease->context->flatAlbedo->RecordInputs(list,lease->flatAlbedo);
    ffxReturnCode_t result;
    {
        // Lighting is restored on every path before any other reader (recovery,
        // capture, commit) is recorded.
        struct RestoreSignals
        {
            const Context& context; ID3D12GraphicsCommandList* list; const Context::Slot& slot; ID3D12Resource* spec; ID3D12Resource* diff;
            bool active = true;
            ~RestoreSignals() { if (active) context.ScaleSignals(list,slot,spec,diff,true); }
        };
        const bool shared = impl_->settings.radianceScale.enabled;
        if (!shared)
        {
            lease->context->BindScaleSignals(*lease->slot,input.spec,input.diff);
            lease->context->ScaleSignals(list,*lease->slot,input.spec,input.diff,false);
        }
        const RestoreSignals restore {*lease->context,list,*lease->slot,input.spec,input.diff,!shared};
        // Preserve the legacy filter's scaled-domain order while OFF. With the
        // shared experiment it writes physical-unit RR copies before scaling.
        // Declare this guard first: shared-scale cleanup must restore the copies
        // to their readable state before they transition back to UAV.
        struct RestoreTurn
        {
            const Context& context; ID3D12GraphicsCommandList* list; bool active;
            ~RestoreTurn() { if (active) context.TurnColourBarriers(list,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS); }
        };
        if (turnPass) lease->context->TurnColour(list,*lease->slot,input.spec,input.diff,turnWeight,turnGain);
        const RestoreTurn restoreTurn {*lease->context,list,turnPass};
        FSRDRadianceScaleDx12::Scope sharedScale;
        if (shared)
        {
            if (!impl_->radianceScale.Before(device.Get(),list,dispatch,impl_->settings.radianceScale,sharedScale.work,error))
            { AbandonOwned(recorded); return false; }
            recorded->diffuseRadianceScale = float(impl_->settings.radianceScale.diffuse);
            recorded->specularRadianceScale = float(impl_->settings.radianceScale.specular);
        }
        try
        {
            NrdBridgeStagePerf::StackTimer provider(profiling,NrdBridgeStagePerf::Stage::ProviderDispatch);
            result = FfxApiProxy::D3D12_Dispatch(&lease->context->handle,&dispatch.header);
        }
        catch (...) { AbandonOwned(recorded); throw; }
    }
    if (result != FFX_API_RETURN_OK)
    { AbandonOwned(recorded); return Fail(error,"RR dispatch",result); }
    if (lease->recovery.owner) lease->context->recovery->Record(list,lease->recovery);
    if (flatPrepared) lease->context->flatAlbedo->RecordOutput(list,lease->flatAlbedo);
    lease->context->flatWasActive = flatPrepared;
    impl_->flatAlbedoActive = flatPrepared; impl_->flatAlbedoFallback = requestFlat && !flatPrepared;
    // SDK CPU history advances here, once. Late Commit never changes camera/frame history.
    impl_->recoveryActive = bool(lease->recovery.owner); impl_->recoveryFallback = recoveryFallback;
    impl_->recoveryTier = lease->recovery.owner ? uint32_t(LobeRecoveryTier::FullPrecision) : uint32_t(LobeRecoveryTier::None);
    // F04: freeze this recording's effective diagnostics into the immutable
    // recorded output at publication. They describe the recorded frame (after
    // the provider recording, before any title Commit), never the wrapper's
    // later mutable latest-state.
    recorded->recoveryTier = impl_->recoveryTier;
    recorded->recoveryFallbackReason = impl_->recoveryFallbackReason;
    recorded->recoveryErrorText = impl_->recoveryErrorText;
    impl_->previous = frame; impl_->previous.reset = reset;
    impl_->previous.outputConstants = {}; impl_->previous.nativeSpecularBlend = 0.0f;
    if (impl_->settings.motionStability.enabled) impl_->motionStabilityReady = true;
    impl_->historyValid = true; impl_->resetPending = false; ++impl_->nextFrame;
    output = std::move(recorded);
    return true;
}

void RRWrapper::AbandonOwned(const RRRecordedOutputLease& output) noexcept
{
    if (!output || !impl_ || output->wrapper.lock().get() != impl_.get()) return;
    output->phase.store(RRRecordedOutput::Abandoned,std::memory_order_release);
    const auto context = output->lease ? output->lease->context : nullptr;
    if (context && impl_->context == context && context->generation == output->contextGeneration)
        DiscardRecordingHistory(); // Outside coordinator/registry locks; GPU leases retain old work.
}

RRRecordedOutputSnapshot RRWrapper::GetOwnedOutputSnapshot(const RRRecordedOutputLease& output) const noexcept
{
    RRRecordedOutputSnapshot result;
    if (!output || !impl_ || output->wrapper.lock().get() != impl_.get() ||
        output->phase.load(std::memory_order_acquire) == RRRecordedOutput::Abandoned || !output->lease) return result;
    const auto& lease = output->lease;
    result.rawSpec = lease->slot->spec.Get(); result.rawDiff = lease->slot->diff.Get();
    result.selectedSpec = output->selectedSpec; result.selectedDiff = output->selectedDiff; result.owner = lease;
    result.recording = output->source; result.recordingId = output->recordingId;
    result.frameSL = output->frameSL; result.frameIndex = output->frameIndex;
    result.width = lease->context->width; result.height = lease->context->height;
    result.contextGeneration = output->contextGeneration;
    result.resetEpoch = output->resetEpoch;
    result.specularSelection = output->specularSelection; result.diffuseSelection = output->diffuseSelection;
    result.nativeObservationInputs = output->nativeObservationInputs;
    result.outputCommitted = output->phase.load(std::memory_order_acquire) == RRRecordedOutput::Committed;
    result.nativeEncodingCaptured = result.outputCommitted && output->nativeEncodingCaptured;
    if (result.nativeEncodingCaptured) result.encodingFlag = lease->slot->flag.resource.Get();
    result.recoveryActive = bool(lease->recovery.owner); result.recoveryFallback = output->recoveryFallback;
    result.providerNormals = lease->flatAlbedo.owner ? lease->flatAlbedo.normals : lease->inputs[4].Get();
    result.providerMotion=lease->lightingGuard?lease->lightingGuard->Motion():lease->inputs[3].Get();
    result.providerPhysicalSpec = lease->inputAnchor.owner ? lease->inputAnchor.specular : lease->inputs[0].Get();
    result.providerPhysicalDiff = lease->inputAnchor.owner ? lease->inputAnchor.diffuse : lease->inputs[1].Get();
    result.postMotionAnchorGain = lease->inputAnchor.active ? lease->inputAnchor.gain : nullptr;
    result.postMotionAnchorSums = lease->inputAnchor.active ? lease->inputAnchor.diagnosticSums : nullptr;
    result.postMotionAnchorActive = lease->inputAnchor.active;
    result.postMotionAnchorFallback = output->inputAnchorFallback;
    result.postMotionAnchorError = output->inputAnchorError;
    result.runtimeTuningValid=output->runtimeTuningValid;
    if(result.runtimeTuningValid)result.runtimeEffective=output->runtimeEffective;
    result.flatAlbedoActive = bool(lease->flatAlbedo.owner); result.flatAlbedoFallback = output->flatAlbedoFallback;
    result.flatAlbedoRoughness = output->flatAlbedoRoughness; result.flatAlbedoError = output->flatAlbedoError;
    // F04: tier/reason/error are read from the immutable recorded output, so an
    // older held snapshot can never inherit a later recording's state.
    result.recoveryTier = output->recoveryTier;
    result.recoveryFallbackReason = output->recoveryFallbackReason;
    result.recoveryErrorText = output->recoveryErrorText;
    result.providerDiffuseRadianceScale = output->diffuseRadianceScale;
    result.providerSpecularRadianceScale = output->specularRadianceScale;
    result.providerRadianceScale = output->diffuseRadianceScale == output->specularRadianceScale ? output->diffuseRadianceScale : 0.0f;
    result.providerControl = output->providerControl;
    result.providerVersionId = lease->context->overrideVersion.versionId;
    result.providerApiVersion = lease->context->create.version;
    result.providerSignalFlags = lease->context->create.signalFlags; result.providerContextFlags = lease->context->create.flags;
    result.providerName = lease->context->providerName;
    result.providerCheckerboardSignalFlags = output->providerCheckerboardSignalFlags;
    result.diffuseCheckerboardOrigin = output->diffuseCheckerboardOrigin;
    result.specularCheckerboardOrigin = output->specularCheckerboardOrigin;
    return result;
}

std::string RRWrapper::GetOwnedOutputProviderAttestation(const RRRecordedOutputLease& output) const noexcept
{
    if (!output || !impl_ || output->wrapper.lock().get() != impl_.get() || !output->lease ||
        output->phase.load(std::memory_order_acquire) == RRRecordedOutput::Abandoned) return {};
    return OwnedProviderAttestation<FfxApiProxy>(output->lease->context->handle);
}

bool RRWrapper::CommitOwned(ID3D12GraphicsCommandList* list, const RRRecordedOutputLease& output,
                            ID3D12Resource* outputSpec, ID3D12Resource* outputDiff, const FrameParameters& frame,
                            std::string& error, const OutputCommitGuard& guard, NrdBridgeStagePerf::Sample* profiling)
{
    error.clear();
    const auto reject = [&](const char* reason) { error = reason; return false; };
    if (!output || !impl_ || output->wrapper.lock().get() != impl_.get() || !output->lease)
        return reject("RR owned output belongs to no live matching wrapper");
    uint8_t expected = RRRecordedOutput::Recorded;
    if (!output->phase.compare_exchange_strong(expected,RRRecordedOutput::Preparing,std::memory_order_acq_rel))
        return reject("RR owned output is already committed, preparing or abandoned");
    struct Claim
    {
        RRWrapper* wrapper; const RRRecordedOutputLease* output; bool committed = false;
        ~Claim() { if (!committed) wrapper->AbandonOwned(*output); }
    } claim {this,&output};
    const auto& lease = output->lease;
    if (impl_->context != lease->context || lease->context->generation != output->contextGeneration)
        return reject("RR owned output context generation is stale");
    if (list != output->source || frame.frameIndex != output->frameIndex || frame.streamlineFrame != output->frameSL)
        return reject("RR owned output requires its exact source recording and frame; cross-list commit is unsupported");
    const auto originalRecording = output->nativeRecording.lock();
    const auto currentRecording = RecordedComputeLease::Capture(list);
    if (!RecordedComputeLease::Available() || !originalRecording || !currentRecording ||
        currentRecording != originalRecording || !output->recordingId || currentRecording->id != output->recordingId)
        return reject("RR owned output native recording identity expired or changed");
    const std::array<ID3D12Resource*, 7> inputs {lease->inputs[0].Get(),lease->inputs[1].Get(),lease->inputs[2].Get(),
        lease->inputs[3].Get(),lease->inputs[4].Get(),lease->inputs[5].Get(),lease->inputs[6].Get()};
    if (!ValidateCommitTarget(list,lease->context->width,lease->context->height,inputs,outputSpec,outputDiff,
        frame,lease->context->device.Get(),error)) return false;
    for (auto* owned : {lease->slot->spec.Get(),lease->slot->diff.Get(),output->selectedSpec,output->selectedDiff,
        lease->slot->nativeDebug.Get(),lease->lightingGuard?lease->lightingGuard->Motion():nullptr,
        lease->inputAnchor.specular,lease->inputAnchor.diffuse})
        if (owned && (owned == outputSpec || owned == outputDiff)) return reject("RR title output aliases owned stages");
    if (HasNativeTitleSignalConstants(frame.outputConstants))
    {
        if (output->nativeCommitPrepared)
        {
            if (!lease->context->TableFlagsReady(*lease->slot,frame.outputConstants.wordIndex))
                return reject("RR deferred native capture was not prepared before the provider");
        }
        else if (!lease->context->PrepareTableFlags(error,frame.outputConstants.wordIndex)) return false;
    }
    // This exact live recording already owns the early DispatchLease. Its owned slot
    // covers late flag/descriptor objects too; never create an opaque-owner/registry cycle.
    lease->context->SetCommitOutputs(*lease->slot,outputSpec,outputDiff);
    struct PreparedCommit
    {
        Context* context; ID3D12GraphicsCommandList* list; Context::Slot* slot;
        ID3D12Resource *spec,*diff,*selectedSpec,*selectedDiff;
        SignalEncoding encoding; TitleSignalConstants constants;
        const RRRecordedOutput* output; NrdBridgeStagePerf::Sample* profiling;
    } prepared {lease->context.get(),list,lease->slot.get(),outputSpec,outputDiff,output->selectedSpec,output->selectedDiff,
        frame.outputEncoding,frame.outputConstants,output.get(),profiling};
    const auto record = +[](void* state) noexcept {
        const auto& action = *static_cast<PreparedCommit*>(state);
        NrdBridgeStagePerf::StackTimer outputCommit(action.profiling,NrdBridgeStagePerf::Stage::OutputCommit);
        action.context->Commit(action.list,*action.slot,action.spec,action.diff,action.encoding,action.constants,
            0.0f,action.selectedSpec,action.selectedDiff);
        action.output->nativeEncodingCaptured = HasNativeTitleSignalConstants(action.constants);
        action.output->phase.store(RRRecordedOutput::Committed,std::memory_order_release);
    };
    if (guard.admit && !guard.admit(guard.state,record,&prepared))
        return reject("RR output ticket expired before owned commit");
    if (!guard.admit) record(&prepared);
    claim.committed = true;
    // An older successful commit cannot overwrite newer private SDK camera/history.
    if (impl_->previous.frameIndex == output->frameIndex && impl_->previous.streamlineFrame == output->frameSL && lease->context->debugEnabled)
    {
        impl_->nativeDebug.resource = lease->slot->nativeDebug.Get(); impl_->nativeDebug.owner = lease;
        impl_->nativeDebug.recording = list; impl_->nativeDebug.frameSL = output->frameSL;
        impl_->nativeDebug.width = lease->context->width; impl_->nativeDebug.height = lease->context->height;
        impl_->nativeDebug.state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    }
    return true;
}

bool RRWrapper::Dispatch(ID3D12GraphicsCommandList* list, const ConvertedResources& input,
                         ID3D12Resource* outputSpec, ID3D12Resource* outputDiff,
                         const FrameParameters& frame, std::string& error, const OutputCommitGuard& guard,
                         NrdBridgeStagePerf::Sample* profiling)
{
    error.clear();
    if (impl_) { impl_->nativeDebug = {}; impl_->recoveryActive = impl_->recoveryFallback = false; }
    const std::array<ID3D12Resource*, 7> inputs {input.spec,input.diff,input.linearDepth,input.motion,
        input.normals,input.specAlbedo,input.diffAlbedo};
    if (!ValidateCommitTarget(list,input.width,input.height,inputs,outputSpec,outputDiff,frame,nullptr,error))
    { if (impl_) impl_->resetPending = true; return false; }
    RRRecordedOutputLease output;
    // Legacy standalone path keeps its existing optional-flag allocation behavior.
    return RecordOwnedImpl(list,input,frame,output,error,profiling,false) &&
        CommitOwned(list,output,outputSpec,outputDiff,frame,error,guard,profiling);
}
void RRWrapper::ResetHistory() noexcept
{
    if (impl_) { impl_->resetPending = true; impl_->nativeDebug = {}; }
}
void RRWrapper::DiscardRecordingHistory() noexcept
{
    if (!impl_) return;
    impl_->nativeDebug = {};
    impl_->recoveryActive = impl_->recoveryFallback = false;
    impl_->recoveryTier = uint32_t(LobeRecoveryTier::None);
    impl_->recoveryFallbackReason = uint32_t(LobeRecoveryFallbackReason::None);
    impl_->context.reset();
    impl_->inputAnchor.DiscardRecordingHistory();
    impl_->inputAnchorActive = impl_->inputAnchorFallback = false; impl_->inputAnchorError.clear();
    // A discarded recording may still be leased on another queue. Its detector
    // images must not become the next physical provider generation's scratch.
    if(impl_->settings.lightingValidation)
    { impl_->lightingGuard.Reset();impl_->lightingValidationActive=false; }
    impl_->flatAlbedoActive = impl_->flatAlbedoFallback = false; impl_->flatAlbedoError.clear();
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
    uint64_t bytes = impl_ && impl_->context ? impl_->context->AuxiliaryBytes() : 0;
    if (impl_) bytes += impl_->lightingGuard.ImageBytes();
    if (impl_ && impl_->recoveryFamily)
        bytes += impl_->recoveryFamily->budget.graphBytes.load(std::memory_order_acquire) +
            impl_->recoveryFamily->budget.slots.allocatedBytes.load(std::memory_order_acquire);
    return bytes;
}
RRWrapper::StagingLedgerSnapshot RRWrapper::SnapshotStagingLedger() const noexcept
{
    StagingLedgerSnapshot result;
    // F03: read the wrapper-owned ledger, which survives context destruction
    // and lives across every retained generation. The current context, when
    // present, shares this exact object; when it is absent (after discard),
    // the retained totals stay observable instead of collapsing to zero.
    if (!impl_ || !impl_->stagingLedger) return result;
    const auto& ledger = *impl_->stagingLedger;
    result.limitBytes = ledger.limit;
    result.byteAdmissionActive = ledger.byteAdmissionActive();
    result.retainedBytes = ledger.RetainedBytes();
    result.retainedPeakBytes = ledger.RetainedPeakBytes();
    result.retiredTotalBytes = ledger.RetiredTotalBytes();
    result.retainedSlots = ledger.RetainedSlots();
    result.rejections = ledger.Rejections();
    result.retirementGuards = ledger.RetirementGuards();
    return result;
}
const std::string& RRWrapper::CameraConventionDescription() const noexcept
{
    static const std::string empty;
    return impl_ ? impl_->conventions : empty;
}
}
