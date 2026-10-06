#pragma once
#include <d3d12.h>
#include <d3dx/d3dx12.h>
#include <shaders/Shader_Dx12Utils.h>
#include <shaders/Shader_Dx12.h>

#define DE_NUM_OF_HEAPS 2

/**
 * @brief Writes a linear view distance as the device depth FFX SR decodes for the given
 * planes and inverted/infinite flags (see precompile/depth_encode.hlsl).
 */
class DE_Dx12 : public Shader_Dx12
{
  public:
    struct Encoding
    {
        float cameraNear = 0.0f;
        float cameraFar = 0.0f;
        bool inverted = false;
        bool infinite = false;
    };

  private:
    struct alignas(256) InternalConstants
    {
        float CameraNear;
        float CameraFar;
        uint32_t Inverted;
        uint32_t Infinite;
        uint32_t Width;
        uint32_t Height;
    };

    FrameDescriptorHeap _frameHeaps[DE_NUM_OF_HEAPS];

    ID3D12Resource* _buffer = nullptr;
    D3D12_RESOURCE_STATES _bufferState = D3D12_RESOURCE_STATE_COMMON;

    UINT InNumThreadsX = 16;
    UINT InNumThreadsY = 16;

  public:
    // The buffer copies the source's extent as R32_FLOAT.
    bool CreateBufferResource(ID3D12Device* InDevice, ID3D12Resource* InSource, D3D12_RESOURCE_STATES InState,
                              ID3D12GraphicsCommandList* InCommandList = nullptr);
    void SetBufferState(ID3D12GraphicsCommandList* InCommandList, D3D12_RESOURCE_STATES InState);
    // InResource must be readable as an SRV; only the top-left width x height region is written.
    bool Dispatch(ID3D12GraphicsCommandList* InCmdList, ID3D12Resource* InResource, const Encoding& encoding,
                  uint32_t width, uint32_t height, ID3D12Resource* OutResource);

    ID3D12Resource* Buffer() { return _buffer; }
    bool CanRender() const { return _init && _buffer != nullptr; }

    DE_Dx12(std::string InName, ID3D12Device* InDevice);

    ~DE_Dx12();
};
