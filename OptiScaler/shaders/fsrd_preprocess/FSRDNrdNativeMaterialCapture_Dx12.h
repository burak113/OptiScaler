#pragma once
#include <d3d12.h>
#include <wrl/client.h>
#include <cstdint>
#include <array>
#include <initializer_list>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#include "misc/NrdBridgeOwned_Dx12.h"
#include "misc/NrdBridgeCaptureSlotBudget_Dx12.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "State.h"
#include "precompile/FSRDNrdNativeMaterialCapture_Shader.h"
#include "precompile/FSRDNrdNativeMaterialParamsCapture_Shader.h"

namespace NrdBridge
{
inline constexpr std::string_view NativeMaterialGuideWriterSha256 =
    "3e09f2e0d948f77869a0628524c14463e1fdb06fcfb78aa60fc102c78fb0d5ed";

// Exact writer profile, space0: p1+7=t7 baseColor (sqrt encoded),
// p2+1=t9 material parameters (.r=metallic), p5+4=u4 native normal/roughness.
// t7 is a bound guide, not an instruction read of this writer. Its interpretation
// is proved by the final material compositor 051b199b...38cc4, not by the binding.
// The coordinator must attest the actual root ranges and same-recording u4 birth.
class NativeMaterialCapture
{
    using ComResource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    struct Slot
    {
        // First member dies last: permits account resources through native Release.
        NrdBridgeCaptureBudget::Permit permit;
        explicit Slot(NrdBridgeCaptureBudget::Permit&& reservation) noexcept : permit(std::move(reservation)) {}
        ComResource resource, roughness;
        Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> descriptors;
        uint64_t bytes = 0;
    };
    struct Context
    {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pso;
        uint32_t width = 0, height = 0, stride = 0;
        bool retired = false, captureParams = false; // Immutable profile after publication.
        std::shared_ptr<NrdBridgeCaptureBudget::Family> budget;
        std::vector<std::shared_ptr<Slot>> slots;
        std::mutex mutex;
    };
    struct Snapshot
    {
        // Only bridge-owned COM is retained. Source textures/list are borrowed.
        std::shared_ptr<Context> owner;
        std::shared_ptr<Slot> slot;
    };
    mutable std::mutex mutex_;
    std::shared_ptr<Context> context_;
    std::shared_ptr<NrdBridgeCaptureBudget::Family> budget_; // Lazy; survives extent/device replacement.

    static void Check(HRESULT code, const char* operation)
    {
        if (FAILED(code)) throw std::runtime_error(std::string(operation) +
            " (HRESULT " + std::to_string(code) + ")");
    }
    static void Acquire(Context& context, std::shared_ptr<Slot>& candidate)
    {
        for (const auto& slot : context.slots)
            if (slot.use_count() == 1) { candidate = slot; return; }
        auto reservation = NrdBridgeCaptureBudget::Permit::TryAcquire(context.budget);
        if (!reservation) throw std::runtime_error("Native material capture family has 32 allocated snapshot slots");
        candidate = MakeOwnedShared<Slot>(std::move(reservation));
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = context.width; desc.Height = context.height;
        desc.DepthOrArraySize = desc.MipLevels = 1; desc.SampleDesc.Count = 1;
        desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        const auto allocation = context.device->GetResourceAllocationInfo(0,1,&desc);
        if (!allocation.SizeInBytes || allocation.SizeInBytes == UINT64_MAX)
            throw std::runtime_error("Native material snapshot allocation size is invalid");
        auto bytes = allocation.SizeInBytes;
        auto roughnessDesc = desc; roughnessDesc.Format = DXGI_FORMAT_R16_FLOAT;
        if (context.captureParams)
        {
            const auto roughnessAllocation = context.device->GetResourceAllocationInfo(0,1,&roughnessDesc);
            if (!roughnessAllocation.SizeInBytes || roughnessAllocation.SizeInBytes == UINT64_MAX ||
                roughnessAllocation.SizeInBytes >= UINT64_MAX - bytes)
                throw std::runtime_error("Native material roughness allocation size is invalid");
            bytes += roughnessAllocation.SizeInBytes;
        }
        // One immutable permit accounts BOTH resources until their actual slot destruction.
        if (!candidate->permit.SetBytes(bytes))
            throw std::runtime_error("Native material snapshot allocation size is invalid");
        candidate->bytes = bytes;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        Check(context.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
            D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&candidate->resource)),
            "Native material snapshot allocation failed");
        if (context.captureParams)
            Check(context.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&roughnessDesc,
                D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&candidate->roughness)),
                "Native material roughness snapshot allocation failed");
        D3D12_DESCRIPTOR_HEAP_DESC descriptors {};
        descriptors.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        descriptors.NumDescriptors = context.captureParams ? 4 : 3; descriptors.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(context.device->CreateDescriptorHeap(&descriptors,IID_PPV_ARGS(&candidate->descriptors)),
            "Native material snapshot descriptor allocation failed");
        context.slots.push_back(candidate);
    }
    static bool TextureMatches(ID3D12Resource* resource, const Context& context,
                               DXGI_FORMAT format) noexcept
    {
        if (!resource) return false;
        const auto desc = resource->GetDesc();
        if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.Width != context.width ||
            desc.Height != context.height || desc.DepthOrArraySize != 1 || desc.MipLevels != 1 ||
            desc.SampleDesc.Count != 1 || desc.Format != format ||
            (desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)) return false;
        Microsoft::WRL::ComPtr<ID3D12Device> actual;
        Microsoft::WRL::ComPtr<IUnknown> expectedIdentity, actualIdentity;
        return SUCCEEDED(resource->GetDevice(IID_PPV_ARGS(&actual))) &&
            SUCCEEDED(actual.As(&actualIdentity)) &&
            SUCCEEDED(context.device.As(&expectedIdentity)) &&
            actualIdentity.Get() == expectedIdentity.Get();
    }

  public:
    using SnapshotLease = std::shared_ptr<Snapshot>;
    bool Initialize(ID3D12Device* device, uint32_t width, uint32_t height,
                    std::string& error) noexcept
    { return InitializeMode(device,width,height,false,error); }
    bool InitializeParams(ID3D12Device* device, uint32_t width, uint32_t height,
                          std::string& error) noexcept
    { return InitializeMode(device,width,height,true,error); }
  private:
    bool InitializeMode(ID3D12Device* device, uint32_t width, uint32_t height,
                        bool captureParams, std::string& error) noexcept
    {
        if (!device || !width || !height || width > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION ||
            height > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION)
        { error = "Native material capture device/extent is invalid"; return false; }
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::shared_ptr<NrdBridgeCaptureBudget::Family> budget;
            std::shared_ptr<Context> next, previous;
            std::vector<std::shared_ptr<Slot>> retiredSlots;
            {
                std::lock_guard lock(mutex_);
                if (context_ && context_->device.Get() == device && context_->width == width && context_->height == height &&
                    context_->captureParams == captureParams)
                { error.clear(); return true; }
                if (!budget_) budget_ = MakeOwnedShared<NrdBridgeCaptureBudget::Family>();
                budget = budget_;
            }
            // Native creation and every losing/failed candidate die outside helper locks.
            next = MakeOwnedShared<Context>(); next->device = device; next->budget = budget;
            next->width = width; next->height = height; next->captureParams = captureParams;
            next->stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            if (!next->stride) throw std::runtime_error("Native material descriptor stride is zero");
            const auto* bytecode = captureParams ? FSRDNrdNativeMaterialParamsCapture_cso : FSRDNrdNativeMaterialCapture_cso;
            const auto bytecodeSize = captureParams ? sizeof(FSRDNrdNativeMaterialParamsCapture_cso) : sizeof(FSRDNrdNativeMaterialCapture_cso);
            Check(device->CreateRootSignature(0,bytecode,bytecodeSize,IID_PPV_ARGS(&next->root)),
                "Native material capture root creation failed");
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc {}; desc.pRootSignature = next->root.Get();
            desc.CS = {bytecode,bytecodeSize};
            Check(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&next->pso)),
                "Native material capture pipeline creation failed");
            next->slots.reserve(NrdBridgeCaptureBudget::Family::Capacity);
            {
                std::lock_guard lock(mutex_);
                // A concurrent same-extent initializer may already have published.
                if (context_ && context_->device.Get() == device && context_->width == width && context_->height == height &&
                    context_->captureParams == captureParams)
                { error.clear(); return true; }
                previous = std::move(context_);
                if (previous)
                {
                    std::lock_guard contextLock(previous->mutex);
                    previous->retired = true;
                    // Snapshot owns Slot directly. Drop ALL cache references now,
                    // so later-idle slots cannot remain pinned by an old context.
                    retiredSlots.swap(previous->slots);
                }
                context_ = std::move(next);
            }
            // Idle slots release here; pending snapshots retain only their needed slots.
            retiredSlots.clear(); previous.reset(); error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native material capture initialization allocation failed"; return false; }
    }
  public:
    using SourceStates = std::array<D3D12_RESOURCE_STATES,2>;
    static bool CanCaptureStates(const SourceStates& states, D3D12_COMMAND_LIST_TYPE type) noexcept
    {
        if (type != D3D12_COMMAND_LIST_TYPE_DIRECT && type != D3D12_COMMAND_LIST_TYPE_COMPUTE) return false;
        constexpr auto readMask = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        for (const auto state : states)
        {
            if ((state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE) && type != D3D12_COMMAND_LIST_TYPE_DIRECT) return false;
            if (state == D3D12_RESOURCE_STATE_COMMON || state == D3D12_RESOURCE_STATE_UNORDERED_ACCESS) continue;
            if ((state & ~readMask) != 0 ||
                !(state & (D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))) return false;
        }
        return true;
    }

    // Existing callers attest compute-readable sources and need no source barriers.
    bool Capture(ID3D12GraphicsCommandList* list, ID3D12Resource* baseColor,
                 ID3D12Resource* materialParams, SnapshotLease& out, std::string& error) noexcept
    {
        return Capture(list,baseColor,materialParams,
            {D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE},out,error);
    }

    // Caller holds the physical lifetime borrow/restoration scope and attests
    // both exact source states in this recording. All preparation and the GPU
    // lease precede title transitions; every transitioned source returns to its
    // exact attested state before return. Sources never acquire a COM owner.
    bool Capture(ID3D12GraphicsCommandList* list, ID3D12Resource* baseColor,
                 ID3D12Resource* materialParams, const SourceStates& sourceStates,
                 SnapshotLease& out, std::string& error) noexcept
    { return CaptureMode(list,baseColor,materialParams,sourceStates,false,out,error); }
    bool CaptureParams(ID3D12GraphicsCommandList* list, ID3D12Resource* baseColor,
                       ID3D12Resource* materialParams, SnapshotLease& out, std::string& error) noexcept
    {
        return CaptureParams(list,baseColor,materialParams,
            {D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE},out,error);
    }
    bool CaptureParams(ID3D12GraphicsCommandList* list, ID3D12Resource* baseColor,
                       ID3D12Resource* materialParams, const SourceStates& sourceStates,
                       SnapshotLease& out, std::string& error) noexcept
    { return CaptureMode(list,baseColor,materialParams,sourceStates,true,out,error); }
  private:
    bool CaptureMode(ID3D12GraphicsCommandList* list, ID3D12Resource* baseColor,
                     ID3D12Resource* materialParams, const SourceStates& sourceStates, bool captureParams,
                     SnapshotLease& out, std::string& error) noexcept
    {
        out.reset();
        if (!list) { error = "Native material capture command list is null"; return false; }
        if (!CanCaptureStates(sourceStates,list->GetType()))
        { error = "Native material source states or command-list type are unsupported"; return false; }
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::shared_ptr<Context> owner;
            { std::lock_guard lock(mutex_); owner = context_; }
            if (!owner) { error = "Native material capture is not initialized"; return false; }
            if (owner->captureParams != captureParams)
            { error = "Native material capture profile does not match Initialize/InitializeParams"; return false; }
            if (!TextureMatches(baseColor,*owner,DXGI_FORMAT_R10G10B10A2_UNORM) ||
                !TextureMatches(materialParams,*owner,DXGI_FORMAT_R8G8B8A8_UNORM))
            { error = "Native material source format/extent/device does not match the exact profile"; return false; }
            if (baseColor == materialParams)
            { error = "Native material source textures alias"; return false; }
            // These owners precede the guard, so failure releases native candidates after unlock.
            auto lease = MakeOwnedShared<Snapshot>(); lease->owner = owner;
            std::shared_ptr<Slot> candidate;
            std::lock_guard lock(owner->mutex);
            if (owner->retired) { error = "Native material capture context retired before recording"; return false; }
            Acquire(*owner,candidate); lease->slot = candidate;
            auto cpu = lease->slot->descriptors->GetCPUDescriptorHandleForHeapStart();
            for (auto* source : {baseColor,materialParams})
            {
                D3D12_SHADER_RESOURCE_VIEW_DESC desc {};
                desc.Format = source == baseColor ? DXGI_FORMAT_R10G10B10A2_UNORM : DXGI_FORMAT_R8G8B8A8_UNORM;
                desc.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
                desc.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                desc.Texture2D.MipLevels = 1;
                owner->device->CreateShaderResourceView(source,&desc,cpu); cpu.ptr += owner->stride;
            }
            D3D12_UNORDERED_ACCESS_VIEW_DESC uav {}; uav.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
            uav.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            owner->device->CreateUnorderedAccessView(lease->slot->resource.Get(),nullptr,&uav,cpu);
            if (captureParams)
            {
                cpu.ptr += owner->stride; uav.Format = DXGI_FORMAT_R16_FLOAT;
                owner->device->CreateUnorderedAccessView(lease->slot->roughness.Get(),nullptr,&uav,cpu);
            }
            std::array<D3D12_RESOURCE_BARRIER,2> sourceBefore {},sourceAfter {},sourceUav {};
            UINT transitionCount = 0, uavCount = 0;
            const std::array sources {baseColor,materialParams};
            for (size_t index = 0; index != sources.size(); ++index)
            {
                if (sourceStates[index] & D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE) continue;
                if (sourceStates[index] == D3D12_RESOURCE_STATE_UNORDERED_ACCESS)
                {
                    auto& uavBarrier = sourceUav[uavCount++];
                    uavBarrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV; uavBarrier.UAV.pResource = sources[index];
                }
                auto& before = sourceBefore[transitionCount]; before.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
                before.Transition = {sources[index],D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                    sourceStates[index],D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
                auto& after = sourceAfter[transitionCount++]; after = before;
                after.Transition.StateBefore = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                after.Transition.StateAfter = sourceStates[index];
            }
            // No GPU command is recorded until the actual recording lease exists.
            if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),list,lease))
            { error = "Native material snapshot GPU lifetime tracking unavailable"; return false; }
            if (uavCount) list->ResourceBarrier(uavCount,sourceUav.data());
            if (transitionCount) list->ResourceBarrier(transitionCount,sourceBefore.data());
            D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {lease->slot->resource.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            list->ResourceBarrier(1,&barrier);
            auto roughnessBarrier = barrier; roughnessBarrier.Transition.pResource = lease->slot->roughness.Get();
            if (captureParams) list->ResourceBarrier(1,&roughnessBarrier);
            list->SetPipelineState(owner->pso.Get()); list->SetComputeRootSignature(owner->root.Get());
            ID3D12DescriptorHeap* heaps[] = {lease->slot->descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
            const uint32_t extent[] = {owner->width,owner->height}; list->SetComputeRoot32BitConstants(0,2,extent,0);
            auto gpu = lease->slot->descriptors->GetGPUDescriptorHandleForHeapStart();
            list->SetComputeRootDescriptorTable(1,gpu); gpu.ptr += uint64_t(owner->stride) * 2;
            list->SetComputeRootDescriptorTable(2,gpu);
            list->Dispatch((owner->width + 7) / 8,(owner->height + 7) / 8,1);
            // Snapshot and every borrowed source are restored before exposing the lease.
            barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; list->ResourceBarrier(1,&barrier);
            if (captureParams)
            {
                roughnessBarrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
                roughnessBarrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON;
                list->ResourceBarrier(1,&roughnessBarrier);
            }
            if (transitionCount) list->ResourceBarrier(transitionCount,sourceAfter.data());
            out = std::move(lease); error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native material snapshot allocation failed"; return false; }
    }
  public:
    static ID3D12Resource* Resource(const SnapshotLease& lease) noexcept
    { return lease && lease->slot ? lease->slot->resource.Get() : nullptr; }
    static ID3D12Resource* RoughnessResource(const SnapshotLease& lease) noexcept
    { return lease && lease->slot ? lease->slot->roughness.Get() : nullptr; }
    uint64_t OwnedAuxiliaryBytes() const noexcept
    {
        try
        {
            std::shared_ptr<NrdBridgeCaptureBudget::Family> budget;
            { std::lock_guard lock(mutex_); budget = budget_; }
            return budget ? budget->allocatedBytes.load(std::memory_order_acquire) : 0;
        }
        catch (...) { return 0; }
    }
};
}
