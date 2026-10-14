#pragma once
#include "consumer_shader.h"

// Native title model, deliberately using a version1.0 root signature: descriptor
// overwrite after recording and before Execute is legal for this volatile table.
struct NativeTableConsumer
{
    Microsoft::WRL::ComPtr<ID3D12DescriptorHeap> heap;
    Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
    Microsoft::WRL::ComPtr<ID3D12PipelineState> pso;
    Microsoft::WRL::ComPtr<ID3D12Resource> spec, diff, seen, seenReadback;
    uint32_t width, height, stride;
    template<class HostType>
    NativeTableConsumer(HostType& host, ID3D12Resource* nativeSpec, ID3D12Resource* nativeDiff,
                        uint32_t w, uint32_t h) : width(w), height(h)
    {
        auto* device = host.device.Get();
        D3D12_DESCRIPTOR_HEAP_DESC heapDesc {}; heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heapDesc.NumDescriptors = 6; heapDesc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        hr(device->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&heap)));
        stride = device->GetDescriptorHandleIncrementSize(heapDesc.Type);
        D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = w; desc.Height = h; desc.DepthOrArraySize = desc.MipLevels = 1;
        desc.SampleDesc.Count = 1; desc.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES properties {}; properties.Type = D3D12_HEAP_TYPE_DEFAULT;
        for (auto* resource : {std::addressof(spec), std::addressof(diff)})
            hr(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &desc,
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr, IID_PPV_ARGS(resource->GetAddressOf())));
        desc = {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; desc.Width = 16;
        desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1; desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        hr(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&seen)));
        properties.Type = D3D12_HEAP_TYPE_READBACK; desc.Flags = D3D12_RESOURCE_FLAG_NONE;
        hr(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&seenReadback)));
        auto cpu = heap->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += UINT64(2) * stride;
        for (auto* resource : {nativeDiff, nativeSpec, diff.Get(), spec.Get()})
        {
            D3D12_UNORDERED_ACCESS_VIEW_DESC view {}; view.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
            view.Format = resource->GetDesc().Format;
            device->CreateUnorderedAccessView(resource, nullptr, &view, cpu); cpu.ptr += stride;
        }
        D3D12_DESCRIPTOR_RANGE ranges[2] {};
        ranges[0] = {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 1, 6, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND};
        ranges[1] = {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 4, 0, 0, D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND};
        D3D12_ROOT_PARAMETER parameters[4] {};
        parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS; parameters[0].Constants = {0, 0, 2};
        for (unsigned i = 0; i < 2; ++i)
        { parameters[i+1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE; parameters[i+1].DescriptorTable = {1, &ranges[i]}; }
        parameters[3].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV; parameters[3].Descriptor = {4, 0};
        D3D12_ROOT_SIGNATURE_DESC signature {}; signature.NumParameters = 4; signature.pParameters = parameters;
        Microsoft::WRL::ComPtr<ID3DBlob> serialized, errors;
        hr(D3D12SerializeRootSignature(&signature, D3D_ROOT_SIGNATURE_VERSION_1_0, &serialized, &errors));
        Microsoft::WRL::ComPtr<ID3D12VersionedRootSignatureDeserializer> deserializer;
        hr(D3D12CreateVersionedRootSignatureDeserializer(serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&deserializer)));
        need(deserializer->GetUnconvertedRootSignatureDesc()->Version == D3D_ROOT_SIGNATURE_VERSION_1_0,
             "native Consumer fixture must use a genuine volatile RSG1.0 table");
        hr(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root)));
        D3D12_COMPUTE_PIPELINE_STATE_DESC pipeline {}; pipeline.pRootSignature = root.Get();
        pipeline.CS = {ConsumerShaderBytes, sizeof(ConsumerShaderBytes)};
        hr(device->CreateComputePipelineState(&pipeline, IID_PPV_ARGS(&pso)));
    }
    void Overwrite(ID3D12Device* device, D3D12_GPU_VIRTUAL_ADDRESS address)
    {
        D3D12_CONSTANT_BUFFER_VIEW_DESC cbv {address, 1536};
        auto cpu = heap->GetCPUDescriptorHandleForHeapStart(); cpu.ptr += stride;
        device->CreateConstantBufferView(&cbv, cpu);
    }
    D3D12_GPU_DESCRIPTOR_HANDLE Handle() const
    { auto value = heap->GetGPUDescriptorHandleForHeapStart(); value.ptr += stride; return value; }
    template<class HostType> void Record(HostType& host)
    {
        auto* list = host.list.Get();
        D3D12_RESOURCE_BARRIER barrier {}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {seen.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
        list->ResourceBarrier(1, &barrier);
        list->SetPipelineState(pso.Get()); list->SetComputeRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[] {heap.Get()}; list->SetDescriptorHeaps(1, heaps);
        const uint32_t size[] {width, height}; list->SetComputeRoot32BitConstants(0, 2, size, 0);
        list->SetComputeRootDescriptorTable(1, Handle());
        auto gpu = heap->GetGPUDescriptorHandleForHeapStart(); gpu.ptr += UINT64(2) * stride;
        list->SetComputeRootDescriptorTable(2, gpu);
        list->SetComputeRootUnorderedAccessView(3, seen->GetGPUVirtualAddress());
        list->Dispatch((width+7)/8, (height+7)/8, 1);
        barrier.Transition = {seen.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COPY_SOURCE};
        list->ResourceBarrier(1, &barrier); list->CopyBufferRegion(seenReadback.Get(), 0, seen.Get(), 0, 16);
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COMMON; list->ResourceBarrier(1, &barrier);
    }
    uint32_t Flag() const
    {
        uint32_t* mapped = nullptr; hr(seenReadback->Map(0, nullptr, reinterpret_cast<void**>(&mapped)));
        const auto result = mapped[0]; seenReadback->Unmap(0, nullptr); return result;
    }
    ULONG References() const { const auto count = heap->AddRef(); heap->Release(); return count-1; }
};
