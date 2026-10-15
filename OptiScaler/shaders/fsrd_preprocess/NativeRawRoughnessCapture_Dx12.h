#pragma once
#include "misc/NrdBridgeOwned_Dx12.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "State.h"
#include "precompile/FSRDNrdRawRoughnessCapture_Shader.h"
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#include <wrl/client.h>

namespace NrdBridge
{
// The caller attests the live writer/profile and holds the title lifetime borrow
// through recording/restoration. There is deliberately no source-resource owner,
// inferred GPU VA, copied descriptor, or persistent native-heap reference here.
struct NativeRawRoughnessBinding
{
    ID3D12DescriptorHeap* nativeHeap = nullptr;
    D3D12_GPU_DESCRIPTOR_HANDLE descriptor {};
    std::string_view shaderSha256, rootSha256;
    UINT rootParameter = UINT_MAX, descriptorOffset = UINT_MAX;
    UINT shaderRegister = UINT_MAX, registerSpace = UINT_MAX;
    D3D12_DESCRIPTOR_RANGE_TYPE kind = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
    DXGI_FORMAT viewFormat = DXGI_FORMAT_UNKNOWN;
    UINT subresource = UINT_MAX;
    D3D12_RESOURCE_DESC description {};
};

inline bool NativeRawRoughnessProfileSupported(const NativeRawRoughnessBinding& binding,
                                              uint32_t width, uint32_t height) noexcept
{
    const auto& desc = binding.description;
    return width && height &&
        binding.shaderSha256 == "3e09f2e0d948f77869a0628524c14463e1fdb06fcfb78aa60fc102c78fb0d5ed" &&
        binding.rootSha256 == "bcb5f3454f596992f694f54ddb53e0f6b0ac7a9d976e8a49d1fc9ddab6a6eb70" &&
        binding.rootParameter == 1 && binding.descriptorOffset == 5 &&
        binding.shaderRegister == 5 && binding.registerSpace == 0 &&
        binding.kind == D3D12_DESCRIPTOR_RANGE_TYPE_SRV && binding.viewFormat == DXGI_FORMAT_R8G8B8A8_UNORM &&
        binding.subresource == 0 && desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM && desc.Width == width && desc.Height == height &&
        desc.MipLevels == 1 && desc.DepthOrArraySize == 1 && desc.SampleDesc.Count == 1 &&
        !(desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE);
}

class NativeRawRoughnessCapture
{
    struct Slot
    {
        Microsoft::WRL::ComPtr<ID3D12Resource> resource;
        uint64_t bytes = 0;
    };
    struct Context
    {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> pso;
        uint32_t width = 0, height = 0;
        std::vector<std::shared_ptr<Slot>> slots;
        std::mutex mutex;
    };
    struct Snapshot
    {
        // Only private objects are retained through submission/cancel/Reset.
        std::shared_ptr<Context> owner;
        std::shared_ptr<Slot> slot;
    };
    mutable std::mutex mutex_;
    std::shared_ptr<Context> context_;

    static void Check(HRESULT code, const char* operation)
    {
        if (FAILED(code)) throw std::runtime_error(std::string(operation) + " (HRESULT " + std::to_string(code) + ")");
    }
    static std::shared_ptr<Slot> Acquire(Context& context)
    {
        for (const auto& slot : context.slots) if (slot.use_count() == 1) return slot;
        if (context.slots.size() >= 32) throw std::runtime_error("Native raw roughness has 32 unretired recordings");
        auto slot = MakeOwnedShared<Slot>();
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = uint64_t(context.width) * context.height * sizeof(uint32_t);
        desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        Check(context.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COMMON,
            nullptr,IID_PPV_ARGS(&slot->resource)),"Native raw roughness snapshot allocation failed");
        slot->bytes = context.device->GetResourceAllocationInfo(0,1,&desc).SizeInBytes;
        context.slots.push_back(slot); return slot;
    }
    static bool ValidateHeap(const NativeRawRoughnessBinding& binding, ID3D12Device* device, std::string& error)
    {
        if (!binding.nativeHeap || !binding.descriptor.ptr)
        { error = "Native raw roughness heap/table pair is incomplete"; return false; }
        const auto desc = binding.nativeHeap->GetDesc();
        if (desc.Type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV ||
            !(desc.Flags & D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE) || !desc.NumDescriptors)
        { error = "Native raw roughness requires a shader-visible resource heap"; return false; }
        Microsoft::WRL::ComPtr<ID3D12Device> heapDevice;
        Microsoft::WRL::ComPtr<IUnknown> expected, actual;
        if (FAILED(device->QueryInterface(IID_PPV_ARGS(&expected))) ||
            FAILED(binding.nativeHeap->GetDevice(IID_PPV_ARGS(&heapDevice))) ||
            FAILED(heapDevice.As(&actual)) || expected.Get() != actual.Get())
        { error = "Native raw roughness heap device mismatch"; return false; }
        const auto start = binding.nativeHeap->GetGPUDescriptorHandleForHeapStart().ptr;
        const auto stride = device->GetDescriptorHandleIncrementSize(desc.Type);
        if (!start || !stride || binding.descriptor.ptr < start ||
            (binding.descriptor.ptr - start) % stride ||
            (binding.descriptor.ptr - start) / stride >= desc.NumDescriptors)
        { error = "Native raw roughness descriptor is outside its native heap"; return false; }
        return true;
    }

  public:
    using SnapshotLease = std::shared_ptr<Snapshot>;
    bool Initialize(ID3D12Device* device, uint32_t width, uint32_t height, std::string& error) noexcept
    {
        if (!device || !width || !height || width > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION ||
            height > D3D12_REQ_TEXTURE2D_U_OR_V_DIMENSION)
        { error = "Native raw roughness device/extent is invalid"; return false; }
        std::shared_ptr<Context> retired;
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::lock_guard lock(mutex_);
            if (context_ && context_->device.Get() == device && context_->width == width && context_->height == height)
            { error.clear(); return true; }
            auto next = MakeOwnedShared<Context>(); next->device = device; next->width = width; next->height = height;
            Check(device->CreateRootSignature(0,FSRDNrdRawRoughnessCapture_cso,sizeof(FSRDNrdRawRoughnessCapture_cso),
                IID_PPV_ARGS(&next->root)),"Native raw roughness root creation failed");
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc {}; desc.pRootSignature = next->root.Get();
            desc.CS = {FSRDNrdRawRoughnessCapture_cso,sizeof(FSRDNrdRawRoughnessCapture_cso)};
            Check(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&next->pso)),"Native raw roughness PSO creation failed");
            next->slots.reserve(32);
            retired = std::move(context_); context_ = std::move(next);
            error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native raw roughness initialization allocation failed"; return false; }
    }
    bool Capture(ID3D12GraphicsCommandList* list, const NativeRawRoughnessBinding& binding,
                 SnapshotLease& out, std::string& error) noexcept
    {
        out.reset();
        if (!list) { error = "Native raw roughness command list is null"; return false; }
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::shared_ptr<Context> owner;
            { std::lock_guard lock(mutex_); owner = context_; }
            if (!owner) { error = "Native raw roughness capture is not initialized"; return false; }
            if (!NativeRawRoughnessProfileSupported(binding,owner->width,owner->height))
            { error = "Native raw roughness exact t5 writer/profile/view is unsupported"; return false; }
            if (!ValidateHeap(binding,owner->device.Get(),error)) return false;
            std::lock_guard lock(owner->mutex);
            auto lease = MakeOwnedShared<Snapshot>(); lease->owner = owner; lease->slot = Acquire(*owner);
            // Admission precedes the first GPU command; rejection cannot change
            // native state or leave an unleased private dispatch in the list.
            if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),list,lease))
            { error = "Native raw roughness recording lifetime tracking unavailable"; return false; }
            D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {lease->slot->resource.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            list->ResourceBarrier(1,&barrier);
            list->SetPipelineState(owner->pso.Get()); list->SetComputeRootSignature(owner->root.Get());
            ID3D12DescriptorHeap* heaps[] = {binding.nativeHeap}; list->SetDescriptorHeaps(1,heaps);
            list->SetComputeRootDescriptorTable(0,binding.descriptor);
            list->SetComputeRootUnorderedAccessView(1,lease->slot->resource->GetGPUVirtualAddress());
            const uint32_t extent[] = {owner->width,owner->height};
            list->SetComputeRoot32BitConstants(2,2,extent,0);
            list->Dispatch((owner->width+7)/8,(owner->height+7)/8,1);
            barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; list->ResourceBarrier(1,&barrier);
            out = std::move(lease); error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native raw roughness capture allocation failed"; return false; }
    }
    static ID3D12Resource* Resource(const SnapshotLease& lease) noexcept
    { return lease && lease->slot ? lease->slot->resource.Get() : nullptr; }
    static uint32_t Width(const SnapshotLease& lease) noexcept
    { return lease && lease->owner ? lease->owner->width : 0; }
    static uint32_t Height(const SnapshotLease& lease) noexcept
    { return lease && lease->owner ? lease->owner->height : 0; }
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
