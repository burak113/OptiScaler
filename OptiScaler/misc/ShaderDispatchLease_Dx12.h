#pragma once
#include <d3d12.h>
#include <wrl/client.h>
#include <memory>
#include <mutex>
#include <vector>
#include <initializer_list>
#include <shaders/Shader_Dx12Utils.h>
#include <gpu_time/GpuTime_Dx12.h>

// Payload for the existing recorded-compute registry; no second lifetime registry.
namespace ShaderDispatchLease
{
struct Slot
{
    FrameDescriptorHeap heap;
    Microsoft::WRL::ComPtr<ID3D12Resource> constants;
};
struct Intermediate
{
    Microsoft::WRL::ComPtr<ID3D12Resource> resource;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
};
struct Dispatch
{
    std::shared_ptr<Slot> slot;
    Microsoft::WRL::ComPtr<ID3D12Device> device;
    Microsoft::WRL::ComPtr<ID3D12RootSignature> root;
    Microsoft::WRL::ComPtr<ID3D12PipelineState> pipeline;
    std::vector<Microsoft::WRL::ComPtr<ID3D12Resource>> resources;
    std::vector<std::shared_ptr<Intermediate>> intermediates;
    // Keeps the actual query heap/readback owner alive; query-ring accuracy is separate.
    std::shared_ptr<GpuTime_Dx12> timer;
};
}
