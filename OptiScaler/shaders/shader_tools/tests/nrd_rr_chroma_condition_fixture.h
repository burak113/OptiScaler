#pragma once
// RESEARCH ONLY. Include after nrd_bridge_rr_fixture.cpp in a native test.
// Every source here is fixture-owned. This helper must never retain game-owned
// resources; it is not a production lifetime/admission implementation.
#include "chroma_condition_shader.h"

namespace NrdChromaResearch
{
struct Parameters
{
    uint32_t width = 0, height = 0, historyCount = 0, mode = 0;
    float strength = 1.0f, chromaFloor = .05f, madScale = 3.0f, depthTolerance = .01f;
    float normalTolerance = .02f, roughnessTolerance = .05f, lumaFloor = .001f, temporalTolerance = 1.0f;
};
static_assert(sizeof(Parameters) == 12u*sizeof(uint32_t));
struct RawFrame
{
    ID3D12Resource* signal = nullptr;
    ID3D12Resource* depth = nullptr;
    ID3D12Resource* normals = nullptr;
    ID3D12Resource* motion = nullptr;
};
inline RawFrame Frame(const Scene& scene, bool specular, ID3D12Resource* motion = nullptr)
{
    return {specular ? scene.resources.spec : scene.resources.diff, scene.resources.linearDepth,
        scene.resources.normals, motion ? motion : scene.resources.motion};
}
struct Kernel
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pso;
    explicit Kernel(ID3D12Device* source) : device(source)
    {
        hr(device->CreateRootSignature(0, ChromaConditionShaderBytes, sizeof(ChromaConditionShaderBytes), IID_PPV_ARGS(&root)));
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc {};
        desc.pRootSignature = root.Get(); desc.CS = {ChromaConditionShaderBytes, sizeof(ChromaConditionShaderBytes)};
        hr(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pso)));
    }
};
inline ComPtr<ID3D12Resource> Target(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format)
{
    D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width; desc.Height = height; desc.DepthOrArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
    desc.Format = format; desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    ComPtr<ID3D12Resource> result;
    hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
        nullptr, IID_PPV_ARGS(&result)));
    return result;
}
struct Targets
{
    ComPtr<ID3D12Resource> signal, evidence;
    Targets(ID3D12Device* device, uint32_t width, uint32_t height)
    {
        signal = Target(device, width, height, DXGI_FORMAT_R16G16B16A16_FLOAT);
        evidence = Target(device, width, height, DXGI_FORMAT_R32G32B32A32_UINT);
    }
};
struct Recording
{
    std::shared_ptr<Kernel> kernel;
    ComPtr<ID3D12DescriptorHeap> heap;
    std::array<ComPtr<ID3D12Resource>, 13> ownedResources;
};
inline void Record(Host& host, const std::shared_ptr<Kernel>& kernel, const RawFrame& current,
                   const RawFrame& previous, const RawFrame& older, const Targets& target, const Parameters& parameters)
{
    need(kernel && parameters.width && parameters.height && parameters.mode <= 2 && parameters.historyCount <= 2,
        "declared chroma experiment dimensions/history/mode");
    const auto previousFrame = parameters.historyCount ? previous : current;
    const auto olderFrame = parameters.historyCount > 1 ? older : previousFrame;
    const std::array<ID3D12Resource*, 11> resources {current.signal, previousFrame.signal, olderFrame.signal,
        current.depth, previousFrame.depth, olderFrame.depth, current.normals, previousFrame.normals, olderFrame.normals,
        current.motion, previousFrame.motion};
    const std::array<DXGI_FORMAT, 11> formats {DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT,
        DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R32_FLOAT, DXGI_FORMAT_R32_FLOAT,
        DXGI_FORMAT_R10G10B10A2_UNORM, DXGI_FORMAT_R10G10B10A2_UNORM, DXGI_FORMAT_R10G10B10A2_UNORM,
        DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R16G16B16A16_FLOAT};
    for (size_t index = 0; index < resources.size(); ++index)
    {
        auto* resource = resources[index]; need(resource != nullptr, "complete owned chroma fixture inputs");
        const auto desc = resource->GetDesc();
        need(desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && desc.Width == parameters.width &&
            desc.Height == parameters.height && desc.Format == formats[index] && desc.DepthOrArraySize == 1 &&
            desc.MipLevels == 1 && desc.SampleDesc.Count == 1, "exact chroma source format and extent");
        need(resource != target.signal.Get() && resource != target.evidence.Get(), "no in-place neighbor read/write race");
    }
    for (const auto& value : {std::pair {target.signal.Get(), DXGI_FORMAT_R16G16B16A16_FLOAT},
                             std::pair {target.evidence.Get(), DXGI_FORMAT_R32G32B32A32_UINT}})
    {
        need(value.first != nullptr, "owned chroma result and evidence exist");
        const auto desc = value.first->GetDesc();
        need(desc.Width == parameters.width && desc.Height == parameters.height && desc.Format == value.second &&
            (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS), "exact owned chroma output format/extent");
    }
    auto owner = MakeOwnedShared<Recording>(); owner->kernel = kernel;
    D3D12_DESCRIPTOR_HEAP_DESC heap {}; heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE; heap.NumDescriptors = 13;
    hr(host.device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&owner->heap)));
    auto cpu = owner->heap->GetCPUDescriptorHandleForHeapStart();
    auto gpu = owner->heap->GetGPUDescriptorHandleForHeapStart();
    const auto stride = host.device->GetDescriptorHandleIncrementSize(heap.Type);
    for (size_t index = 0; index < resources.size(); ++index)
    {
        owner->ownedResources[index] = resources[index];
        D3D12_SHADER_RESOURCE_VIEW_DESC view {}; view.Format = formats[index];
        view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; view.Texture2D.MipLevels = 1;
        host.device->CreateShaderResourceView(resources[index], &view, cpu); cpu.ptr += stride;
    }
    owner->ownedResources[11] = target.signal; owner->ownedResources[12] = target.evidence;
    for (unsigned index = 11; index < 13; ++index)
    {
        D3D12_UNORDERED_ACCESS_VIEW_DESC view {}; view.Format = owner->ownedResources[index]->GetDesc().Format;
        view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
        host.device->CreateUnorderedAccessView(owner->ownedResources[index].Get(), nullptr, &view, cpu); cpu.ptr += stride;
    }
    need(ResTrack_Dx12::RetainComputeDispatch(host.device.Get(), host.list.Get(), owner),
        "chroma GPU lease retains PSO/root/device/immutable descriptors/all owned inputs and outputs");
    ID3D12DescriptorHeap* heaps[] {owner->heap.Get()}; host.list->SetDescriptorHeaps(1, heaps);
    host.list->SetComputeRootSignature(kernel->root.Get()); host.list->SetPipelineState(kernel->pso.Get());
    host.list->SetComputeRoot32BitConstants(0, 12, &parameters, 0);
    host.list->SetComputeRootDescriptorTable(1, gpu); gpu.ptr += 11u*stride;
    host.list->SetComputeRootDescriptorTable(2, gpu);
    host.list->Dispatch((parameters.width+7u)/8u, (parameters.height+7u)/8u, 1);
    for (auto* output : {target.signal.Get(), target.evidence.Get()})
    {
        D3D12_RESOURCE_BARRIER done {}; done.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV; done.UAV.pResource = output;
        host.list->ResourceBarrier(1, &done);
    }
    // Caller transitions only the OWNED conditioned signal UA->NPS, supplies it
    // to the unchanged RR wrapper, and restores UA only after GPU-ordered use.
}
}
