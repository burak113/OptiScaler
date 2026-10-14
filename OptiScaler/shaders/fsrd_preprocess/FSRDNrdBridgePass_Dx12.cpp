#include "pch.h"
#include "misc/NrdBridgeOwned_Dx12.h"
#include "FSRDNrdBridgePass_Dx12.h"
#include "FSRDNrdSignalConstants_Dx12.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "State.h"
#include "precompile/FSRDNrdBridge_Shader.h"
#include "precompile/FSRDNrdBridgeCopy_Shader.h"
#include "precompile/FSRDNrdBridgeMotion_Shader.h"
#include <wrl/client.h>
#include <array>
#include <cmath>
#include <cstddef>
#include <mutex>
#include <stdexcept>
#include <vector>

namespace NrdBridge
{
namespace
{
using Microsoft::WRL::ComPtr;
constexpr auto kRead = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
constexpr auto kWrite = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
constexpr uint32_t kWarmSlots = 4, kMaximumSlots = 32;

void Check(HRESULT result, const char* operation)
{
    if (FAILED(result)) throw std::runtime_error(std::string(operation) + " (HRESULT " + std::to_string(result) + ")");
}

struct BridgeConstants
{
    uint32_t width, height;
    float nearPlane, farPlane;
    float depthSign;
    uint32_t previousValid;
    DirectX::XMFLOAT2 motionScale, jitterDelta;
    uint32_t reserved[2] {};
    DirectX::XMFLOAT4X4 inverseProjection, worldToView;
    DirectX::XMFLOAT4 previousViewDepthRow;
    DirectX::XMFLOAT2 currentJitterUv;
    uint32_t cameraReserved[2] {};
};
static_assert(sizeof(BridgeConstants) == 52 * sizeof(uint32_t));
static_assert(offsetof(BridgeConstants, inverseProjection) == 12 * sizeof(uint32_t));

struct OwnedTexture
{
    ComPtr<ID3D12Resource> resource;
    D3D12_RESOURCE_STATES state = kRead;
    void Transition(ID3D12GraphicsCommandList* list, D3D12_RESOURCE_STATES next)
    {
        if (next == state) return;
        D3D12_RESOURCE_BARRIER barrier {};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, state, next};
        list->ResourceBarrier(1, &barrier);
        state = next;
    }
};

void UavBarrier(ID3D12GraphicsCommandList* list, ID3D12Resource* first, ID3D12Resource* second)
{
    D3D12_RESOURCE_BARRIER barriers[2] {};
    for (auto& barrier : barriers) barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
    barriers[0].UAV.pResource = first;
    barriers[1].UAV.pResource = second;
    list->ResourceBarrier(2, barriers);
}

bool TextureMatches(ID3D12Resource* resource, uint32_t width, uint32_t height, DXGI_FORMAT format, bool uav)
{
    if (!resource) return false;
    const auto desc = resource->GetDesc();
    return desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && desc.Width == width && desc.Height == height &&
           desc.DepthOrArraySize == 1 && desc.MipLevels >= 1 && desc.SampleDesc.Count == 1 && desc.Format == format &&
           (!uav || (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS) != 0);
}

struct DescriptorSlot { ComPtr<ID3D12DescriptorHeap> heap; SignalFlagSnapshot flag; };
struct Pipeline
{
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pso;
    std::vector<std::shared_ptr<DescriptorSlot>> slots;
    uint32_t srvCount = 0, uavCount = 0, stride = 0;

    std::shared_ptr<DescriptorSlot> NewSlot(ID3D12Device* device)
    {
        if (slots.size() >= kMaximumSlots) throw std::runtime_error("NRD descriptor pool has 32 unretired recordings");
        auto slot = MakeOwnedShared<DescriptorSlot>();
        D3D12_DESCRIPTOR_HEAP_DESC desc {};
        desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        desc.NumDescriptors = srvCount + uavCount;
        desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&slot->heap)), "create NRD descriptor slot");
        slots.push_back(slot);
        return slot;
    }
    void Initialize(ID3D12Device* device, const unsigned char* bytes, size_t length, uint32_t srvs, uint32_t uavs)
    {
        srvCount = srvs; uavCount = uavs;
        stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        Check(device->CreateRootSignature(0, bytes, length, IID_PPV_ARGS(&root)), "create NRD root signature");
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
        desc.pRootSignature = root.Get(); desc.CS = {bytes, length};
        Check(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pso)), "create NRD conversion pipeline");
        slots.reserve(kMaximumSlots);
        for (uint32_t i = 0; i < kWarmSlots; ++i) NewSlot(device);
    }
    std::shared_ptr<DescriptorSlot> Acquire(ID3D12Device* device)
    {
        for (const auto& slot : slots) if (slot.use_count() == 1) return slot;
        return NewSlot(device);
    }
    void Describe(ID3D12Device* device, const DescriptorSlot& slot,
                  const std::vector<ID3D12Resource*>& srvs, const std::vector<ID3D12Resource*>& uavs)
    {
        auto cpu = slot.heap->GetCPUDescriptorHandleForHeapStart();
        // Zero the descriptor union for every view. No inherited Buffer fields.
        for (auto* resource : srvs)
        {
            D3D12_SHADER_RESOURCE_VIEW_DESC desc {};
            desc.Format = resource ? resource->GetDesc().Format : DXGI_FORMAT_R16G16B16A16_FLOAT;
            desc.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            desc.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            desc.Texture2D.MipLevels = 1;
            device->CreateShaderResourceView(resource, &desc, cpu); cpu.ptr += stride;
        }
        for (auto* resource : uavs)
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC desc {};
            desc.Format = resource->GetDesc().Format; desc.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            device->CreateUnorderedAccessView(resource, nullptr, &desc, cpu); cpu.ptr += stride;
        }
    }
    void Record(ID3D12GraphicsCommandList* list, const DescriptorSlot& slot,
                const void* constants, uint32_t count, uint32_t width, uint32_t height,
                D3D12_GPU_VIRTUAL_ADDRESS constantAddress = 0)
    {
        list->SetPipelineState(pso.Get()); list->SetComputeRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[] = {slot.heap.Get()}; list->SetDescriptorHeaps(1, heaps);
        list->SetComputeRoot32BitConstants(0, count, constants, 0);
        if (constantAddress) list->SetComputeRootConstantBufferView(3, constantAddress);
        auto gpu = slot.heap->GetGPUDescriptorHandleForHeapStart();
        list->SetComputeRootDescriptorTable(1, gpu); gpu.ptr += uint64_t(srvCount) * stride;
        list->SetComputeRootDescriptorTable(2, gpu);
        list->Dispatch((width + 7) / 8, (height + 7) / 8, 1);
    }
};
}

struct ConversionPass::Impl
{
    ComPtr<ID3D12Device> device;
    uint32_t width = 0, height = 0, previousIndex = 0;
    uint64_t textureBytes = 0;
    bool historyValid = false;
    std::mutex mutex;
    Pipeline conversion, copy, motionPass;
    ComPtr<ID3D12Resource> zeroConstants;
    SignalFlagCapture flagCapture;
    uint64_t zeroBytes = 0;
    bool motionInitialized = false, pendingMotion = false;
    uint32_t motionPreviousIndex = 0, motionSLFrame = UINT32_MAX, motionBridgeFrame = 0;
    bool motionPreviousValid = false, motionCameraProjectedDepthDelta = false;
    bool previousCameraValid = false;
    DirectX::XMFLOAT4X4 previousCameraView {}, motionInverseProjection {};
    DirectX::XMFLOAT4 motionPreviousViewDepthRow {};
    DirectX::XMFLOAT2 motionCurrentJitterUv {};
    ID3D12GraphicsCommandList* motionList = nullptr;
    OwnedTexture spec, diff, motion, normals, specAlbedo, diffAlbedo;
    std::array<OwnedTexture, 2> depth;
    // The only strong COM references are bridge-owned objects. All title textures
    // remain borrowed, including descriptors in a slot retained by a GPU lease.
    struct Lease { std::shared_ptr<Impl> owner; std::shared_ptr<DescriptorSlot> slot; };

    void Create(OwnedTexture& target, DXGI_FORMAT format, const wchar_t* name)
    {
        D3D12_RESOURCE_DESC desc {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = width; desc.Height = height; desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Format = format; desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        Check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, kRead, nullptr,
                                             IID_PPV_ARGS(&target.resource)), "create NRD bridge texture");
        target.resource->SetName(name);
        textureBytes += device->GetResourceAllocationInfo(0, 1, &desc).SizeInBytes;
    }
    ConvertedResources Resources() const
    {
        return {spec.resource.Get(), diff.resource.Get(), depth[previousIndex].resource.Get(), motion.resource.Get(),
                normals.resource.Get(), specAlbedo.resource.Get(), diffAlbedo.resource.Get(), width, height};
    }
};

ConversionPass::ConversionPass() = default;
ConversionPass::~ConversionPass() = default;
bool ConversionPass::Initialize(ID3D12Device* device, uint32_t width, uint32_t height, std::string& error)
{
    if (!device || !width || !height || width > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION ||
        height > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION)
    { error = "Invalid NRD conversion device or render size"; return false; }
    if (impl_ && impl_->device.Get() == device && impl_->width == width && impl_->height == height)
    { error.clear(); return true; }
    try
    {
        ScopedSkipHeapCapture skipHeapCapture;
        auto next = MakeOwnedShared<Impl>(); next->device = device; next->width = width; next->height = height;
        if (!CreateZeroSignalConstants(device, next->zeroConstants, error)) return false;
        const auto zeroDesc = next->zeroConstants->GetDesc();
        next->zeroBytes = device->GetResourceAllocationInfo(0, 1, &zeroDesc).SizeInBytes;
        next->conversion.Initialize(device, FSRDNrdBridge_cso, sizeof(FSRDNrdBridge_cso), 4, 9);
        next->copy.Initialize(device, FSRDNrdBridgeCopy_cso, sizeof(FSRDNrdBridgeCopy_cso), 7, 2);
        next->Create(next->spec, DXGI_FORMAT_R16G16B16A16_FLOAT, L"NRD_Bridge_Spec");
        next->Create(next->diff, DXGI_FORMAT_R16G16B16A16_FLOAT, L"NRD_Bridge_Diff");
        next->Create(next->motion, DXGI_FORMAT_R16G16B16A16_FLOAT, L"NRD_Bridge_Motion");
        next->Create(next->normals, DXGI_FORMAT_R10G10B10A2_UNORM, L"NRD_Bridge_NormalRoughness");
        next->Create(next->specAlbedo, DXGI_FORMAT_R8G8B8A8_UNORM, L"NRD_Bridge_SpecAlbedo");
        next->Create(next->diffAlbedo, DXGI_FORMAT_R8G8B8A8_UNORM, L"NRD_Bridge_DiffAlbedo");
        next->Create(next->depth[0], DXGI_FORMAT_R32_FLOAT, L"NRD_Bridge_Depth0");
        next->Create(next->depth[1], DXGI_FORMAT_R32_FLOAT, L"NRD_Bridge_Depth1");
        impl_ = std::move(next); // An old generation remains in its recorded GPU leases.
        error.clear(); return true;
    }
    catch (const std::exception& e) { error = e.what(); return false; }
}

bool ConversionPass::Dispatch(ID3D12GraphicsCommandList* list, const ConversionInputs& inputs,
                              const FrameParameters& frame, ConvertedResources& out, std::string& error)
{
    out = {};
    if (!list || !impl_) { error = "NRD conversion is not initialized"; return false; }
    auto owner = impl_;
    std::lock_guard lock(owner->mutex);
    if (!TextureMatches(inputs.reconSpec, owner->width, owner->height, DXGI_FORMAT_R16G16B16A16_FLOAT, true) ||
        !TextureMatches(inputs.reconDiff, owner->width, owner->height, DXGI_FORMAT_R16G16B16A16_FLOAT, true) ||
        !TextureMatches(inputs.normals, owner->width, owner->height, DXGI_FORMAT_R10G10B10A2_UNORM, false) ||
        !TextureMatches(inputs.viewDepth, owner->width, owner->height, DXGI_FORMAT_R32_FLOAT, false) ||
        (inputs.motion && !TextureMatches(inputs.motion, owner->width, owner->height, DXGI_FORMAT_R16G16B16A16_FLOAT, false)))
    { error = "NRD conversion input format, size or UAV flag mismatch"; return false; }
    DirectX::XMMATRIX inverseProjection, inverseView;
    if (!frame.camera.Complete() || !FSRDCamera::TryInvert(frame.camera.projection, inverseProjection) ||
        !FSRDCamera::TryInvert(frame.camera.view, inverseView) || !std::isfinite(frame.nearPlane) ||
        !std::isfinite(frame.farPlane) || frame.nearPlane <= 0 || frame.farPlane <= frame.nearPlane ||
        frame.farPlane > 65504.0f || !std::isfinite(frame.depthSign) || std::abs(frame.depthSign) != 1.0f ||
        !std::isfinite(frame.motionScale.x) || !std::isfinite(frame.motionScale.y) ||
        !std::isfinite(frame.jitter.x) || !std::isfinite(frame.jitter.y) ||
        !std::isfinite(frame.previousJitter.x) || !std::isfinite(frame.previousJitter.y))
    { error = "NRD conversion requires finite camera, depth and motion conventions"; return false; }
    try
    {
        ScopedSkipHeapCapture skipHeapCapture;
        auto lease = std::make_shared<Impl::Lease>(); lease->owner = owner;
        lease->slot = owner->conversion.Acquire(owner->device.Get());
        if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(), list, lease))
        { error = "NRD conversion GPU lifetime tracking unavailable"; return false; }
        const uint32_t writeIndex = 1 - owner->previousIndex;
        auto& writeDepth = owner->depth[writeIndex];
        BridgeConstants constants {};
        constants.width = owner->width; constants.height = owner->height;
        constants.nearPlane = frame.nearPlane; constants.farPlane = frame.farPlane; constants.depthSign = frame.depthSign;
        constants.previousValid = owner->historyValid && frame.previousValid && !frame.reset;
        constants.motionScale = frame.motionScale;
        constants.reserved[0] = inputs.motion ? 0u : 1u;
        constants.reserved[1] = frame.cameraProjectedDepthDelta ? 1u : 0u;
        if (frame.cameraProjectedDepthDelta)
        {
            constants.previousValid = constants.previousValid && owner->previousCameraValid;
            if (constants.previousValid)
            {
                // Signed Z of the same current world surface in the previous camera.
                const auto currentToPreviousView = DirectX::XMMatrixMultiply(
                    DirectX::XMLoadFloat4x4(&owner->previousCameraView), inverseView);
                DirectX::XMStoreFloat4(&constants.previousViewDepthRow, currentToPreviousView.r[2]);
                constants.currentJitterUv = {frame.jitter.x / owner->width, frame.jitter.y / owner->height};
            }
        }
        if (!frame.motionVectorsJittered)
            constants.jitterDelta = {(frame.previousJitter.x - frame.jitter.x) / owner->width,
                                    (frame.previousJitter.y - frame.jitter.y) / owner->height};
        if (!std::isfinite(constants.jitterDelta.x) || !std::isfinite(constants.jitterDelta.y))
        { error = "NRD jitter delta overflow"; return false; }
        DirectX::XMStoreFloat4x4(&constants.inverseProjection, inverseProjection);
        DirectX::XMStoreFloat4x4(&constants.worldToView, frame.camera.view);
        owner->conversion.Describe(owner->device.Get(), *lease->slot,
            {inputs.normals, inputs.viewDepth, inputs.motion, owner->depth[owner->previousIndex].resource.Get()},
            {inputs.reconSpec, inputs.reconDiff, owner->spec.resource.Get(), owner->diff.resource.Get(),
             writeDepth.resource.Get(), owner->motion.resource.Get(), owner->normals.resource.Get(),
             owner->specAlbedo.resource.Get(), owner->diffAlbedo.resource.Get()});
        UavBarrier(list, inputs.reconSpec, inputs.reconDiff);
        const std::array<OwnedTexture*, 7> outputs {&owner->spec, &owner->diff, &writeDepth, &owner->motion,
                                                   &owner->normals, &owner->specAlbedo, &owner->diffAlbedo};
        for (auto* texture : outputs) texture->Transition(list, kWrite);
        owner->conversion.Record(list, *lease->slot, &constants, 52, owner->width, owner->height);
        for (auto* texture : outputs) texture->Transition(list, kRead);
        owner->pendingMotion = inputs.motion == nullptr;
        owner->motionPreviousIndex = owner->previousIndex;
        owner->motionPreviousValid = constants.previousValid != 0;
        owner->motionCameraProjectedDepthDelta = frame.cameraProjectedDepthDelta;
        if (frame.cameraProjectedDepthDelta)
        {
            owner->motionInverseProjection = constants.inverseProjection;
            owner->motionPreviousViewDepthRow = constants.previousViewDepthRow;
            owner->motionCurrentJitterUv = constants.currentJitterUv;
            DirectX::XMStoreFloat4x4(&owner->previousCameraView, frame.camera.view);
        }
        owner->previousCameraValid = frame.cameraProjectedDepthDelta;
        owner->motionList = list;
        owner->motionSLFrame = frame.streamlineFrame;
        owner->motionBridgeFrame = frame.frameIndex;
        owner->previousIndex = writeIndex; owner->historyValid = true;
        out = owner->Resources(); error.clear(); return true;
    }
    catch (const std::exception& e) { owner->historyValid = false; error = e.what(); return false; }
}

bool ConversionPass::DispatchMotion(ID3D12GraphicsCommandList* list, const ConvertedResources& resources,
                                    ID3D12Resource* titleMotion, const FrameParameters& frame, std::string& error)
{
    if (!list || !impl_) { error = "NRD motion conversion is not initialized"; return false; }
    auto owner = impl_;
    std::lock_guard lock(owner->mutex);
    const auto current = owner->Resources();
    if (!owner->pendingMotion || !owner->historyValid || owner->motionList != list ||
        owner->motionSLFrame != frame.streamlineFrame || owner->motionBridgeFrame != frame.frameIndex ||
        owner->motionCameraProjectedDepthDelta != frame.cameraProjectedDepthDelta ||
        resources.width != current.width || resources.height != current.height || resources.spec != current.spec ||
        resources.diff != current.diff || resources.linearDepth != current.linearDepth || resources.motion != current.motion ||
        resources.normals != current.normals || resources.specAlbedo != current.specAlbedo || resources.diffAlbedo != current.diffAlbedo ||
        frame.motionVectors3D || titleMotion == current.motion || titleMotion == current.spec || titleMotion == current.diff ||
        !TextureMatches(titleMotion, owner->width, owner->height, DXGI_FORMAT_R16G16B16A16_FLOAT, false))
    { error = "NRD motion conversion requires the current same-list Recon ticket and Temporal motion"; return false; }
    struct MotionConstants
    {
        uint32_t width, height, previousValid, reserved;
        DirectX::XMFLOAT2 scale, jitterDelta;
        DirectX::XMFLOAT4X4 inverseProjection;
        DirectX::XMFLOAT4 previousViewDepthRow;
        DirectX::XMFLOAT2 currentJitterUv;
        uint32_t cameraReserved[2];
    };
    static_assert(sizeof(MotionConstants) == 32 * sizeof(uint32_t));
    MotionConstants constants {};
    constants.width = owner->width; constants.height = owner->height;
    constants.previousValid = owner->motionPreviousValid ? 1u : 0u;
    constants.reserved = owner->motionCameraProjectedDepthDelta ? 1u : 0u;
    constants.scale = frame.motionScale;
    if (owner->motionCameraProjectedDepthDelta)
    {
        constants.inverseProjection = owner->motionInverseProjection;
        constants.previousViewDepthRow = owner->motionPreviousViewDepthRow;
        constants.currentJitterUv = owner->motionCurrentJitterUv;
    }
    if (!frame.motionVectorsJittered)
        constants.jitterDelta = {(frame.previousJitter.x - frame.jitter.x) / owner->width,
                                (frame.previousJitter.y - frame.jitter.y) / owner->height};
    if (!std::isfinite(constants.scale.x) || !std::isfinite(constants.scale.y) ||
        !std::isfinite(constants.jitterDelta.x) || !std::isfinite(constants.jitterDelta.y))
    { error = "NRD motion scale or jitter delta is nonfinite"; return false; }
    try
    {
        ScopedSkipHeapCapture skipHeapCapture;
        if (!owner->motionInitialized)
        {
            owner->motionPass.Initialize(owner->device.Get(), FSRDNrdBridgeMotion_cso, sizeof(FSRDNrdBridgeMotion_cso), 3, 1);
            owner->motionInitialized = true;
        }
        auto lease = std::make_shared<Impl::Lease>(); lease->owner = owner;
        lease->slot = owner->motionPass.Acquire(owner->device.Get());
        if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(), list, lease))
        { error = "NRD motion conversion GPU lifetime tracking unavailable"; return false; }
        owner->motionPass.Describe(owner->device.Get(), *lease->slot,
            {titleMotion, current.linearDepth, owner->depth[owner->motionPreviousIndex].resource.Get()}, {current.motion});
        owner->motion.Transition(list, kWrite);
        owner->motionPass.Record(list, *lease->slot, &constants, 32, owner->width, owner->height);
        owner->motion.Transition(list, kRead);
        owner->pendingMotion = false;
        error.clear(); return true;
    }
    catch (const std::exception& e) { owner->historyValid = false; owner->pendingMotion = false; error = e.what(); return false; }
}

bool ConversionPass::WriteDebug(ID3D12GraphicsCommandList* list, const ConvertedResources& resources,
                                ID3D12Resource* outputSpec, ID3D12Resource* outputDiff,
                                DebugMode mode, std::string& error, const OutputCommitGuard& guard, SignalEncoding encoding,
                                const TitleSignalConstants& titleConstants)
{
    if (!list || !impl_ || (mode != DebugMode::RawSignals && mode != DebugMode::RRInputs) ||
        (encoding != SignalEncoding::Rgb && encoding != SignalEncoding::YCoCg))
    { error = "Invalid NRD debug-copy request"; return false; }
    auto owner = impl_;
    if (!ValidateTitleSignalConstants(titleConstants, owner->device.Get(), error)) return false;
    std::lock_guard lock(owner->mutex);
    const auto current = owner->Resources();
    if (!owner->historyValid || owner->pendingMotion || resources.width != current.width || resources.height != current.height ||
        resources.spec != current.spec || resources.diff != current.diff || resources.linearDepth != current.linearDepth ||
        resources.motion != current.motion || resources.normals != current.normals ||
        resources.specAlbedo != current.specAlbedo || resources.diffAlbedo != current.diffAlbedo ||
        outputSpec == outputDiff ||
        !TextureMatches(outputSpec, owner->width, owner->height, DXGI_FORMAT_R16G16B16A16_FLOAT, true) ||
        !TextureMatches(outputDiff, owner->width, owner->height, DXGI_FORMAT_R16G16B16A16_FLOAT, true))
    { error = "NRD debug-copy resource mismatch"; return false; }
    if (outputSpec == resources.spec || outputSpec == resources.diff ||
        outputDiff == resources.spec || outputDiff == resources.diff)
    { error = "NRD debug output aliases a bridge input"; return false; }
    try
    {
        ScopedSkipHeapCapture skipHeapCapture;
        const bool nativeConstants = HasNativeTitleSignalConstants(titleConstants);
        if (nativeConstants && !owner->flagCapture.Initialize(owner->device.Get(), error)) return false;
        auto lease = std::make_shared<Impl::Lease>(); lease->owner = owner;
        lease->slot = owner->copy.Acquire(owner->device.Get());
        if (nativeConstants)
        {
            if (!lease->slot->flag.Initialize(owner->device.Get(), error)) return false;
        }
        if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(), list, lease))
        { error = "NRD debug-copy GPU lifetime tracking unavailable"; return false; }
        owner->copy.Describe(owner->device.Get(), *lease->slot,
            {resources.spec, resources.diff, resources.normals, resources.linearDepth, resources.motion,
             resources.specAlbedo, resources.diffAlbedo}, {outputSpec, outputDiff});
        const uint32_t constants[] = {owner->width, owner->height, uint32_t(mode), uint32_t(encoding), nativeConstants ? 1u : 0u};
        struct PreparedCopy
        {
            Impl* owner;
            ID3D12GraphicsCommandList* list;
            DescriptorSlot* slot;
            ID3D12Resource *spec, *diff;
            const uint32_t* constants;
            D3D12_GPU_VIRTUAL_ADDRESS address;
            TitleSignalConstants titleConstants;
        } copy {owner.get(), list, lease->slot.get(), outputSpec, outputDiff, constants,
            nativeConstants ? lease->slot->flag.resource->GetGPUVirtualAddress() :
                owner->zeroConstants->GetGPUVirtualAddress(), titleConstants};
        const auto record = +[](void* state) noexcept {
            const auto& prepared = *static_cast<PreparedCopy*>(state);
            if (HasNativeTitleSignalConstants(prepared.titleConstants))
                prepared.owner->flagCapture.Record(prepared.list, prepared.titleConstants, prepared.slot->flag);
            UavBarrier(prepared.list, prepared.spec, prepared.diff);
            // Sample the native flag at execution; the conversion reads only the private snapshot.
            prepared.owner->copy.Record(prepared.list, *prepared.slot, prepared.constants, 5,
                prepared.owner->width, prepared.owner->height, prepared.address);
            UavBarrier(prepared.list, prepared.spec, prepared.diff);
            if (HasNativeTitleSignalConstants(prepared.titleConstants)) prepared.slot->flag.Transition(prepared.list, false);
        };
        if (guard.admit && !guard.admit(guard.state, record, &copy))
        { error = "NRD output ticket expired before debug commit"; return false; }
        if (!guard.admit) record(&copy);
        error.clear(); return true;
    }
    catch (const std::exception& e) { error = e.what(); return false; }
}

void ConversionPass::ResetHistory() noexcept
{
    if (impl_) { std::lock_guard lock(impl_->mutex); impl_->historyValid = false; impl_->previousCameraValid = false; impl_->pendingMotion = false; }
}
uint64_t ConversionPass::OwnedTextureBytes() const noexcept { return impl_ ? impl_->textureBytes : 0; }
uint64_t ConversionPass::OwnedAuxiliaryBytes() const noexcept
{
    if (!impl_) return 0;
    uint64_t bytes = impl_->zeroBytes;
    for (const auto& slot : impl_->copy.slots) bytes += slot->flag.bytes;
    return bytes;
}
}
