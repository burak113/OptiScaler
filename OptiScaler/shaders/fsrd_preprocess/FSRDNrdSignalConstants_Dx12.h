#pragma once
#include "FSRDNrdBridge_Types.h"
#include <wrl/client.h>
#include <cstring>
#include "precompile/FSRDNrdBridgeFlag_Shader.h"
#include "precompile/FSRDNrdBridgeFlagRoot_Shader.h"
#include "precompile/FSRDNrdBridgeFlagPixel_Shader.h"
#include "precompile/FSRDNrdBridgeFlagPixelRoot_Shader.h"

namespace NrdBridge
{
inline bool HasNativeTitleSignalConstants(const TitleSignalConstants& constants) noexcept
{
    return constants.address != 0 || (constants.nativeHeap && constants.cbvHandle.ptr);
}

inline bool ValidateTitleSignalConstants(const TitleSignalConstants& constants, ID3D12Device* device, std::string& error)
{
    if (!constants.address && !constants.nativeHeap && !constants.cbvHandle.ptr) return true;
    if (constants.wordIndex != 303 && constants.wordIndex != 36)
    { error = "NRD consumer signal flag word is unsupported"; return false; }
    if (bool(constants.nativeHeap) != bool(constants.cbvHandle.ptr))
    { error = "NRD Consumer CB6 native heap/table pair is incomplete"; return false; }
    // A table is the title's native descriptor, even when its buffer/VA is unknown.
    // A direct root CBV supplies only an aligned VA; never inspect a source buffer.
    if (!constants.nativeHeap)
    {
        if (constants.address & 255u)
        { error = "NRD Consumer CB6 direct root VA is unaligned"; return false; }
        return true;
    }
    Microsoft::WRL::ComPtr<ID3D12Device> actual;
    Microsoft::WRL::ComPtr<IUnknown> expectedIdentity, actualIdentity;
    if (!device || FAILED(device->QueryInterface(IID_PPV_ARGS(&expectedIdentity))))
    { error = "NRD Consumer CB6 heap device is unavailable"; return false; }
    if (constants.nativeHeap)
    {
        const auto heap = constants.nativeHeap->GetDesc();
        if (heap.Type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV ||
            !(heap.Flags & D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE) || !heap.NumDescriptors)
        { error = "NRD Consumer CB6 table requires a shader-visible resource heap"; return false; }
        if (FAILED(constants.nativeHeap->GetDevice(IID_PPV_ARGS(&actual))) ||
            FAILED(actual.As(&actualIdentity)) || expectedIdentity.Get() != actualIdentity.Get())
        { error = "NRD Consumer CB6 heap device mismatch"; return false; }
        const auto start = constants.nativeHeap->GetGPUDescriptorHandleForHeapStart().ptr;
        const auto stride = device->GetDescriptorHandleIncrementSize(heap.Type);
        if (!start || !stride || constants.cbvHandle.ptr < start ||
            (constants.cbvHandle.ptr - start) % stride ||
            (constants.cbvHandle.ptr - start) / stride >= heap.NumDescriptors)
        { error = "NRD Consumer CB6 GPU descriptor handle is outside its heap"; return false; }
    }
    return true;
}

struct SignalFlagSnapshot
{
    Microsoft::WRL::ComPtr<ID3D12Resource> resource;
    uint64_t bytes = 0;
    bool Initialize(ID3D12Device* device, std::string& error)
    {
        if (resource) return true;
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = 1536; desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        const auto code = device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&resource));
        if (FAILED(code)) { error = "NRD Consumer flag snapshot allocation failed (HRESULT " + std::to_string(code) + ")"; return false; }
        bytes = device->GetResourceAllocationInfo(0, 1, &desc).SizeInBytes;
        return true;
    }
    void Transition(ID3D12GraphicsCommandList* list, bool toConstant) const noexcept
    {
        D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            toConstant ? D3D12_RESOURCE_STATE_UNORDERED_ACCESS : D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER,
            toConstant ? D3D12_RESOURCE_STATE_VERTEX_AND_CONSTANT_BUFFER : D3D12_RESOURCE_STATE_COMMON};
        list->ResourceBarrier(1, &barrier);
    }
};

struct SignalFlagCapture
{
    Microsoft::WRL::ComPtr<ID3D12RootSignature> root, directRoot;
    Microsoft::WRL::ComPtr<ID3D12PipelineState> pso, rootPso;
    // Keep both profiles alive: closed recordings may still use either pair.
    Microsoft::WRL::ComPtr<ID3D12RootSignature> pixelRoot, pixelDirectRoot;
    Microsoft::WRL::ComPtr<ID3D12PipelineState> pixelPso, pixelRootPso;
    bool Initialize(ID3D12Device* device, std::string& error, uint32_t wordIndex = 303)
    {
        if (wordIndex != 303 && wordIndex != 36)
        { error = "NRD consumer signal flag word is unsupported"; return false; }
        const bool pixel = wordIndex == 36;
        if (pixel ? (pixelRoot && pixelDirectRoot && pixelPso && pixelRootPso)
                  : (root && directRoot && pso && rootPso)) return true;
        const auto* tableCode = pixel ? FSRDNrdBridgeFlagPixel_cso : FSRDNrdBridgeFlag_cso;
        const auto tableBytes = pixel ? sizeof(FSRDNrdBridgeFlagPixel_cso) : sizeof(FSRDNrdBridgeFlag_cso);
        const auto* rootCode = pixel ? FSRDNrdBridgeFlagPixelRoot_cso : FSRDNrdBridgeFlagRoot_cso;
        const auto rootBytes = pixel ? sizeof(FSRDNrdBridgeFlagPixelRoot_cso) : sizeof(FSRDNrdBridgeFlagRoot_cso);
        Microsoft::WRL::ComPtr<ID3D12RootSignature> nextRoot, nextDirectRoot;
        Microsoft::WRL::ComPtr<ID3D12PipelineState> nextPso, nextRootPso;
        auto code = device->CreateRootSignature(0, tableCode, tableBytes, IID_PPV_ARGS(&nextRoot));
        if (SUCCEEDED(code))
        {
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
            desc.pRootSignature = nextRoot.Get(); desc.CS = {tableCode, tableBytes};
            code = device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&nextPso));
        }
        if (SUCCEEDED(code))
            code = device->CreateRootSignature(0, rootCode, rootBytes, IID_PPV_ARGS(&nextDirectRoot));
        if (SUCCEEDED(code))
        {
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
            desc.pRootSignature = nextDirectRoot.Get(); desc.CS = {rootCode, rootBytes};
            code = device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&nextRootPso));
        }
        if (FAILED(code)) { error = "NRD Consumer flag capture pipeline failed (HRESULT " + std::to_string(code) + ")"; return false; }
        // Publish only this profile. Never release another profile's recorded PSOs.
        if (pixel)
        { pixelRoot = nextRoot; pixelDirectRoot = nextDirectRoot; pixelPso = nextPso; pixelRootPso = nextRootPso; }
        else
        { root = nextRoot; directRoot = nextDirectRoot; pso = nextPso; rootPso = nextRootPso; }
        return true;
    }
    // Record() selects its PSO/root pair from constants.wordIndex. Callers must
    // therefore prepare the exact accepted word before any possibly deferred GPU
    // recording and never allocate a fallible pair inside the record callback.
    // Both words keep their profiles alive together: publishing one word never
    // releases the other profile's recorded PSOs.
    bool Prepared(uint32_t wordIndex) const noexcept
    {
        if (wordIndex == 36) return bool(pixelRoot && pixelDirectRoot && pixelPso && pixelRootPso);
        if (wordIndex == 303) return bool(root && directRoot && pso && rootPso);
        return false;
    }
    void Record(ID3D12GraphicsCommandList* list, const TitleSignalConstants& constants,
                const SignalFlagSnapshot& snapshot) const noexcept
    {
        // Balanced COMMON -> UAV -> CBV -> COMMON also supports distinct closed
        // recordings executed together without an intervening decay boundary.
        D3D12_RESOURCE_BARRIER start {}; start.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        start.Transition = {snapshot.resource.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
        list->ResourceBarrier(1, &start);
        const bool pixel = constants.wordIndex == 36;
        if (constants.nativeHeap)
        {
            list->SetPipelineState(pixel ? pixelPso.Get() : pso.Get());
            list->SetComputeRootSignature(pixel ? pixelRoot.Get() : root.Get());
            ID3D12DescriptorHeap* heaps[] = {constants.nativeHeap}; list->SetDescriptorHeaps(1, heaps);
            list->SetComputeRootDescriptorTable(0, constants.cbvHandle);
        }
        else
        {
            list->SetPipelineState(pixel ? pixelRootPso.Get() : rootPso.Get());
            list->SetComputeRootSignature(pixel ? pixelDirectRoot.Get() : directRoot.Get());
            list->SetComputeRootConstantBufferView(0, constants.address);
        }
        list->SetComputeRootUnorderedAccessView(1, snapshot.resource->GetGPUVirtualAddress());
        list->Dispatch(1, 1, 1);
        snapshot.Transition(list, true);
    }
};

inline bool CreateZeroSignalConstants(ID3D12Device* device, Microsoft::WRL::ComPtr<ID3D12Resource>& result, std::string& error)
{
    constexpr uint32_t kBytes = 1536; // 76 registers rounded to a 256-byte CBV boundary.
    D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = kBytes; desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1;
    desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_UPLOAD;
    const auto code = device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
        D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&result));
    if (FAILED(code)) { error = "NRD fallback CB6 creation failed (HRESULT " + std::to_string(code) + ")"; return false; }
    void* mapped = nullptr; D3D12_RANGE noRead {0,0};
    if (FAILED(result->Map(0, &noRead, &mapped)))
    { error = "NRD fallback CB6 initialization failed"; return false; }
    std::memset(mapped, 0, kBytes); result->Unmap(0, nullptr);
    return true;
}
}
