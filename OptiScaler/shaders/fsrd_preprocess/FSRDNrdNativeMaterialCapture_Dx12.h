#pragma once
#include <d3d12.h>
#include <wrl/client.h>
#include <cstdint>
#include <initializer_list>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#include "misc/NrdBridgeOwned_Dx12.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "State.h"
#include "precompile/FSRDNrdNativeMaterialCapture_Shader.h"

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
        ComResource resource;
        Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> descriptors;
        uint64_t bytes = 0;
    };
    struct Context
    {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pso;
        uint32_t width = 0, height = 0, stride = 0;
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

    static void Check(HRESULT code, const char* operation)
    {
        if (FAILED(code)) throw std::runtime_error(std::string(operation) +
            " (HRESULT " + std::to_string(code) + ")");
    }
    static std::shared_ptr<Slot> Acquire(Context& context)
    {
        for (const auto& slot : context.slots) if (slot.use_count() == 1) return slot;
        if (context.slots.size() >= 32)
            throw std::runtime_error("Native material capture has 32 unretired recordings");
        auto slot = MakeOwnedShared<Slot>();
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = context.width; desc.Height = context.height;
        desc.DepthOrArraySize = desc.MipLevels = 1; desc.SampleDesc.Count = 1;
        desc.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        Check(context.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
            D3D12_RESOURCE_STATE_COMMON,nullptr,IID_PPV_ARGS(&slot->resource)),
            "Native material snapshot allocation failed");
        const auto allocation = context.device->GetResourceAllocationInfo(0,1,&desc);
        if (allocation.SizeInBytes == UINT64_MAX)
            throw std::runtime_error("Native material snapshot allocation size is invalid");
        slot->bytes = allocation.SizeInBytes;
        D3D12_DESCRIPTOR_HEAP_DESC descriptors {};
        descriptors.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        descriptors.NumDescriptors = 3; descriptors.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        Check(context.device->CreateDescriptorHeap(&descriptors,IID_PPV_ARGS(&slot->descriptors)),
            "Native material snapshot descriptor allocation failed");
        context.slots.push_back(slot); return slot;
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
    {
        if (!device || !width || !height || width > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION ||
            height > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION)
        { error = "Native material capture device/extent is invalid"; return false; }
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::lock_guard lock(mutex_);
            if (context_ && context_->device.Get() == device && context_->width == width && context_->height == height)
            { error.clear(); return true; }
            auto next = MakeOwnedShared<Context>(); next->device = device;
            next->width = width; next->height = height;
            next->stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            if (!next->stride) throw std::runtime_error("Native material descriptor stride is zero");
            Check(device->CreateRootSignature(0,FSRDNrdNativeMaterialCapture_cso,
                sizeof(FSRDNrdNativeMaterialCapture_cso),IID_PPV_ARGS(&next->root)),
                "Native material capture root creation failed");
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc {}; desc.pRootSignature = next->root.Get();
            desc.CS = {FSRDNrdNativeMaterialCapture_cso,sizeof(FSRDNrdNativeMaterialCapture_cso)};
            Check(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&next->pso)),
                "Native material capture pipeline creation failed");
            next->slots.reserve(32); context_ = std::move(next); error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native material capture initialization allocation failed"; return false; }
    }
    // Caller holds the physical lifetime borrow/restoration scope and proves
    // both title views are currently compute-readable in this exact recording.
    // The helper neither infers nor transitions a borrowed source state.
    bool Capture(ID3D12GraphicsCommandList* list, ID3D12Resource* baseColor,
                 ID3D12Resource* materialParams, SnapshotLease& out, std::string& error) noexcept
    {
        out.reset();
        if (!list) { error = "Native material capture command list is null"; return false; }
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::shared_ptr<Context> owner;
            { std::lock_guard lock(mutex_); owner = context_; }
            if (!owner) { error = "Native material capture is not initialized"; return false; }
            if (!TextureMatches(baseColor,*owner,DXGI_FORMAT_R10G10B10A2_UNORM) ||
                !TextureMatches(materialParams,*owner,DXGI_FORMAT_R8G8B8A8_UNORM))
            { error = "Native material source format/extent/device does not match the exact profile"; return false; }
            if (baseColor == materialParams)
            { error = "Native material source textures alias"; return false; }
            std::lock_guard lock(owner->mutex);
            auto lease = MakeOwnedShared<Snapshot>(); lease->owner = owner; lease->slot = Acquire(*owner);
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
            // No GPU command is recorded until the actual recording lease exists.
            if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),list,lease))
            { error = "Native material snapshot GPU lifetime tracking unavailable"; return false; }
            D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {lease->slot->resource.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            list->ResourceBarrier(1,&barrier);
            list->SetPipelineState(owner->pso.Get()); list->SetComputeRootSignature(owner->root.Get());
            ID3D12DescriptorHeap* heaps[] = {lease->slot->descriptors.Get()}; list->SetDescriptorHeaps(1,heaps);
            const uint32_t extent[] = {owner->width,owner->height}; list->SetComputeRoot32BitConstants(0,2,extent,0);
            auto gpu = lease->slot->descriptors->GetGPUDescriptorHandleForHeapStart();
            list->SetComputeRootDescriptorTable(1,gpu); gpu.ptr += uint64_t(owner->stride) * 2;
            list->SetComputeRootDescriptorTable(2,gpu);
            list->Dispatch((owner->width + 7) / 8,(owner->height + 7) / 8,1);
            // Only the private snapshot transitions; title SRVs are never changed.
            barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; list->ResourceBarrier(1,&barrier);
            out = std::move(lease); error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native material snapshot allocation failed"; return false; }
    }
    static ID3D12Resource* Resource(const SnapshotLease& lease) noexcept
    { return lease && lease->slot ? lease->slot->resource.Get() : nullptr; }
    uint64_t OwnedAuxiliaryBytes() const noexcept
    {
        try
        {
            std::shared_ptr<Context> owner;
            { std::lock_guard lock(mutex_); owner = context_; }
            if (!owner) return 0;
            std::lock_guard lock(owner->mutex); uint64_t bytes = 0;
            for (const auto& slot : owner->slots) bytes += slot->bytes;
            return bytes;
        }
        catch (...) { return 0; }
    }
};
}
