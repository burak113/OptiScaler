#include "pch.h"
#include "DE_Dx12.h"

#include <cmath>

#include "DE_Common.h"
#include "precompile/depth_encode_Shader.h"

#include <Config.h>

bool DE_Dx12::CreateBufferResource(ID3D12Device* InDevice, ID3D12Resource* InSource, D3D12_RESOURCE_STATES InState,
                                   ID3D12GraphicsCommandList* InCommandList)
{
    auto resourceFlags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS | D3D12_RESOURCE_FLAG_ALLOW_SIMULTANEOUS_ACCESS;

    auto result = Shader_Dx12::CreateBufferResource(InDevice, InSource, InState, &_buffer, resourceFlags, 0, 0,
                                                    DXGI_FORMAT_R32_FLOAT, InCommandList);

    if (result)
    {
        _buffer->SetName(L"SR_DeviceDepth_Buffer");
        _bufferState = _recordedLifetime ? D3D12_RESOURCE_STATE_COMMON : InState;
    }

    return result;
}

void DE_Dx12::SetBufferState(ID3D12GraphicsCommandList* InCommandList, D3D12_RESOURCE_STATES InState)
{
    return Shader_Dx12::SetBufferState(InCommandList, InState, _buffer, &_bufferState);
}

bool DE_Dx12::Dispatch(ID3D12GraphicsCommandList* InCmdList, ID3D12Resource* InResource, const Encoding& encoding,
                       uint32_t width, uint32_t height, ID3D12Resource* OutResource)
{
    if (!_init || _device == nullptr || InCmdList == nullptr || InResource == nullptr || OutResource == nullptr ||
        width == 0 || height == 0)
        return false;

    // The encoding divides by z and by (far - near); the caller passes the planes SR decodes with.
    if (!std::isfinite(encoding.cameraNear) || !std::isfinite(encoding.cameraFar) || encoding.cameraNear <= 0.0f ||
        encoding.cameraFar <= encoding.cameraNear)
        return false;

    const auto inDesc = InResource->GetDesc();
    const auto outDesc = OutResource->GetDesc();
    if (inDesc.Width < width || inDesc.Height < height || outDesc.Width < width || outDesc.Height < height)
        return false;

    LOG_DEBUG("[{0}] Start!", _name);

    auto lease = AcquireDispatchLease(InCmdList, _pipelineState, { InResource, OutResource });
    if (_recordedLifetime && !lease)
        return false;
    ScopedGpuTime_Dx12 scopedGpuTime(GpuTime.get(), InCmdList);

    if (!_recordedLifetime)
    {
        _counter++;
        _counter = _counter % DE_NUM_OF_HEAPS;
    }
    FrameDescriptorHeap& currentHeap = lease ? lease->slot->heap : _frameHeaps[_counter];
    auto* constantsBuffer = lease ? lease->slot->constants.Get() : _constantBuffer;

    CreateShaderResourceView(_device, InResource, currentHeap.GetSrvCPU(0), DXGI_FORMAT_R32_FLOAT);
    CreateUnorderedAccessView(_device, OutResource, currentHeap.GetUavCPU(0), 0);

    InternalConstants constants {};
    constants.CameraNear = encoding.cameraNear;
    constants.CameraFar = encoding.cameraFar;
    constants.Inverted = encoding.inverted ? 1u : 0u;
    constants.Infinite = encoding.infinite ? 1u : 0u;
    constants.Width = width;
    constants.Height = height;

    if (!CreateConstantsBuffer(_device, constantsBuffer, constants, currentHeap.GetCbvCPU(0)))
    {
        LOG_ERROR("[{0}] Failed to create a constants buffer", _name);
        return false;
    }

    ID3D12DescriptorHeap* heaps[] = { currentHeap.GetHeapCSU() };
    InCmdList->SetDescriptorHeaps(_countof(heaps), heaps);

    InCmdList->SetComputeRootSignature(_rootSignature);
    InCmdList->SetPipelineState(_pipelineState);

    InCmdList->SetComputeRootDescriptorTable(0, currentHeap.GetTableGPUStart());

    InCmdList->Dispatch((width + InNumThreadsX - 1) / InNumThreadsX, (height + InNumThreadsY - 1) / InNumThreadsY, 1);

    return true;
}

DE_Dx12::DE_Dx12(std::string InName, ID3D12Device* InDevice) : Shader_Dx12(InName, InDevice)
{
    if (InDevice == nullptr)
    {
        LOG_ERROR("InDevice is nullptr!");
        return;
    }

    LOG_DEBUG("{0} start!", _name);

    if (!SetupRootSignature(InDevice, 1, 1, 1))
    {
        LOG_ERROR("Failed to setup root signature");
        return;
    }

    D3D12_RESOURCE_DESC desc = CD3DX12_RESOURCE_DESC::Buffer(sizeof(InternalConstants));
    auto heapProps = CD3DX12_HEAP_PROPERTIES(D3D12_HEAP_TYPE_UPLOAD);

    auto result =
        InDevice->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_GENERIC_READ,
                                          nullptr, IID_PPV_ARGS(&_constantBuffer));

    if (result != S_OK)
    {
        LOG_ERROR("[{0}] CreateCommittedResource error {1:x}", _name, (unsigned int) result);
        return;
    }

    if (!CreateComputePipeline(InDevice, &_pipelineState, depth_encode_cso, sizeof(depth_encode_cso),
                               depthEncodeShader.c_str()))
    {
        LOG_ERROR("[{0}] Failed to create compute pipeline", _name);
        return;
    }

    _init = InitHeaps(InDevice, _frameHeaps, DE_NUM_OF_HEAPS);
}

DE_Dx12::~DE_Dx12()
{
    if (!_init || State::Instance().isShuttingDown)
        return;

    for (int i = 0; i < DE_NUM_OF_HEAPS; i++)
    {
        _frameHeaps[i].ReleaseHeaps();
    }

    SAFE_RELEASE(_buffer);
}
