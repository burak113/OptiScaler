#pragma once
#include "FSRDNrdSignalConstants_Dx12.h"
#include "misc/NrdBridgeOwned_Dx12.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "State.h"
#include "precompile/FSRDNrdNativeTemporalCapture_Shader.h"
#include "precompile/FSRDNrdNativeTemporalCaptureRoot_Shader.h"
#include <array>
#include <cstddef>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <vector>

namespace NrdBridge
{
// Shader/fixture layout only. Production never maps or fills this buffer on CPU.
struct NativeTemporalSnapshotData
{
    std::array<float,4> previousClipX {}, previousClipY {}, previousClipW {}, previousViewDepthRow {};
    std::array<float,4> currentRight {}, currentUp {}, currentForward {};
    std::array<float,4> previousRight {}, previousUp {}, previousForward {};
    std::array<float,4> cameraDelta {}, motionScale {};
    std::array<int32_t,2> sourceOrigin {};
    std::array<uint32_t,2> rectSize {};
    std::array<float,2> inverseRectSize {}, previousRectSize {};
    uint32_t motionSpace = 0;
    float orthographic = 0;
    uint32_t signature = 0, version = 0;
    std::array<uint32_t,4> reserved {};
};
static_assert(sizeof(NativeTemporalSnapshotData) == 256);
static_assert(offsetof(NativeTemporalSnapshotData,previousViewDepthRow) == 48);
static_assert(offsetof(NativeTemporalSnapshotData,currentRight) == 64);
static_assert(offsetof(NativeTemporalSnapshotData,previousRight) == 112);
static_assert(offsetof(NativeTemporalSnapshotData,cameraDelta) == 160);
static_assert(offsetof(NativeTemporalSnapshotData,motionScale) == 176);
static_assert(offsetof(NativeTemporalSnapshotData,sourceOrigin) == 192);
static_assert(offsetof(NativeTemporalSnapshotData,rectSize) == 200);
static_assert(offsetof(NativeTemporalSnapshotData,inverseRectSize) == 208);
static_assert(offsetof(NativeTemporalSnapshotData,previousRectSize) == 216);
static_assert(offsetof(NativeTemporalSnapshotData,motionSpace) == 224);
static_assert(offsetof(NativeTemporalSnapshotData,signature) == 232);

class NativeTemporalCapture
{
    using ComResource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    struct Slot { ComResource resource; uint64_t bytes = 0; };
    struct Context
    {
        Microsoft::WRL::ComPtr<ID3D12Device> device;
        Microsoft::WRL::ComPtr<ID3D12RootSignature> tableRoot, directRoot;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> tablePso, directPso;
        std::vector<std::shared_ptr<Slot>> slots;
        std::mutex mutex;
    };
    struct Snapshot
    {
        // Both owners contain only bridge-owned COM; no source buffer/heap/list.
        std::shared_ptr<Context> owner;
        std::shared_ptr<Slot> slot;
    };
    mutable std::mutex mutex_;
    std::shared_ptr<Context> context_;

    static void Check(HRESULT code, const char* operation)
    {
        if (FAILED(code)) throw std::runtime_error(std::string(operation) + " (HRESULT " + std::to_string(code) + ")");
    }
    static void Pipeline(ID3D12Device* device, const void* code, size_t bytes,
        Microsoft::WRL::ComPtr<ID3D12RootSignature>& root,
        Microsoft::WRL::ComPtr<ID3D12PipelineState>& pso)
    {
        Check(device->CreateRootSignature(0,code,bytes,IID_PPV_ARGS(&root)),"Native Temporal shadow root creation failed");
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {}; desc.pRootSignature = root.Get(); desc.CS = {code,bytes};
        Check(device->CreateComputePipelineState(&desc,IID_PPV_ARGS(&pso)),"Native Temporal shadow pipeline creation failed");
    }
    static std::shared_ptr<Slot> Acquire(Context& context)
    {
        for (const auto& slot : context.slots) if (slot.use_count() == 1) return slot;
        if (context.slots.size() >= 32) throw std::runtime_error("Native Temporal shadow has32 unretired recordings");
        auto slot = MakeOwnedShared<Slot>();
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = sizeof(NativeTemporalSnapshotData); desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        Check(context.device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_COMMON,
            nullptr,IID_PPV_ARGS(&slot->resource)),"Native Temporal shadow allocation failed");
        slot->bytes = context.device->GetResourceAllocationInfo(0,1,&desc).SizeInBytes;
        context.slots.push_back(slot); return slot;
    }

  public:
    using SnapshotLease = std::shared_ptr<Snapshot>;
    bool Initialize(ID3D12Device* device, std::string& error) noexcept
    {
        if (!device) { error = "Native Temporal shadow device is null"; return false; }
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::lock_guard lock(mutex_);
            if (context_)
            {
                if (context_->device.Get() != device) { error = "Native Temporal shadow device changed"; return false; }
                error.clear(); return true;
            }
            auto next = MakeOwnedShared<Context>(); next->device = device;
            Pipeline(device,FSRDNrdNativeTemporalCapture_cso,sizeof(FSRDNrdNativeTemporalCapture_cso),next->tableRoot,next->tablePso);
            Pipeline(device,FSRDNrdNativeTemporalCaptureRoot_cso,sizeof(FSRDNrdNativeTemporalCaptureRoot_cso),next->directRoot,next->directPso);
            context_ = std::move(next); error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native Temporal shadow initialization allocation failed"; return false; }
    }
    bool Capture(ID3D12GraphicsCommandList* list, const FrameSurvey::BoundConstantBinding& binding,
                 SnapshotLease& out, std::string& error) noexcept
    {
        // Drop an old caller lease outside all context/metadata guards.
        out.reset();
        if (!list) { error = "Native Temporal shadow command list is null"; return false; }
        try
        {
            FrameSurvey::ScopedInternal internal; ScopedSkipHeapCapture skip;
            std::shared_ptr<Context> owner;
            { std::lock_guard lock(mutex_); owner = context_; }
            if (!owner) { error = "Native Temporal shadow is not initialized"; return false; }
            TitleSignalConstants native {}; native.address = binding.address;
            native.nativeHeap = binding.descriptorHeap; native.cbvHandle = binding.descriptor;
            if (!HasNativeTitleSignalConstants(native) || !ValidateTitleSignalConstants(native,owner->device.Get(),error))
            { if (error.empty()) error = "Native Temporal b6 binding is absent"; return false; }
            std::lock_guard lock(owner->mutex);
            auto lease = MakeOwnedShared<Snapshot>(); lease->owner = owner; lease->slot = Acquire(*owner);
            // Acquire the real recording lease BEFORE recording any shadow work.
            if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),list,lease))
            { error = "Native Temporal shadow GPU lifetime tracking unavailable"; return false; }
            D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {lease->slot->resource.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_COMMON,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
            list->ResourceBarrier(1,&barrier);
            if (native.nativeHeap)
            {
                list->SetPipelineState(owner->tablePso.Get()); list->SetComputeRootSignature(owner->tableRoot.Get());
                ID3D12DescriptorHeap* heaps[] = {native.nativeHeap}; list->SetDescriptorHeaps(1,heaps);
                list->SetComputeRootDescriptorTable(0,native.cbvHandle);
            }
            else
            {
                list->SetPipelineState(owner->directPso.Get()); list->SetComputeRootSignature(owner->directRoot.Get());
                list->SetComputeRootConstantBufferView(0,native.address);
            }
            list->SetComputeRootUnorderedAccessView(1,lease->slot->resource->GetGPUVirtualAddress());
            list->Dispatch(1,1,1);
            // Balance immediately: cancellation before deferred motion is safe.
            barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; list->ResourceBarrier(1,&barrier);
            out = std::move(lease); error.clear(); return true;
        }
        catch (const std::exception& exception) { error = exception.what(); return false; }
        catch (...) { error = "Native Temporal shadow capture allocation failed"; return false; }
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
