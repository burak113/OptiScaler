#include "pch.h"
#include "FSRDPreprocessor_Dx12.h"
#include "precompile/FSRDInputConv_Shader.h" 
#include "precompile/FSRDOutputComp_Shader.h" 
#include "../Shader_Dx12Utils.h"

#include "dx12/ffx_api_dx12.h"
#include "fsr-rr/ffx_denoiser.h"

#include <d3dcompiler.h>
#include <d3d12.h>
#include <stdexcept>
#include <vector>
#include <string>
#include <array>
#include <algorithm>

#pragma comment(lib, "d3dcompiler.lib")

using Microsoft::WRL::ComPtr;
using namespace DirectX;
using ResFmtPair = std::pair<ID3D12Resource*, DXGI_FORMAT>;

/**
 * @brief Resources used for composition after denoising
 */
union CompInput
{
    struct
    {
        ID3D12Resource* InDenoisedSignal1;
        ID3D12Resource* InRawSignal1;
        ID3D12Resource* InAlbedo1;

        ID3D12Resource* InDenoisedSignal2;
        ID3D12Resource* InRawSignal2;
        ID3D12Resource* InAlbedo2;

        ID3D12Resource* InColorBeforeParticles; // NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles
        ID3D12Resource* InSkipSignal;
    };

    ID3D12Resource* AsArray[8];
};

struct alignas(16) CompConstants
{
    DirectX::XMFLOAT4 DstTexSize; // XY = Tex Size - ZW = 1 / XY

    float CorrelationBias; // Controls the contribution of stable elements to the final image
    uint32_t Flags;

    float _Padding[2];
};

constexpr UINT kBackBufferCount = 7;
constexpr UINT kInternalBufferCount = 0;

// Conversion Constants
constexpr UINT kConvInputCount = sizeof(FSRDPreprocessor_Dx12::ConvInput) / sizeof(ID3D12Resource*);
constexpr UINT kConvOutputCount = 8;
constexpr UINT kConvDescriptorCount = kInternalBufferCount + kConvInputCount + kConvOutputCount;

// Composition Constants
constexpr UINT kCompInputCount = sizeof(CompInput) / sizeof(ID3D12Resource*);
constexpr UINT kCompOutputCount = 1;

constexpr UINT kThreadGroupSizeX = 8;
constexpr UINT kThreadGroupSizeY = 8;

constexpr D3D12_RESOURCE_STATES kSrvState =
    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
constexpr D3D12_RESOURCE_STATES kUavState = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;

namespace FSRDFormats
{
    // ffxDispatchDescDenoiserInput1Signal
    constexpr DXGI_FORMAT Radiance = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT FusedAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;

    // ffxDispatchDescDenoiserInput2Signals
    constexpr DXGI_FORMAT SpecRadiance = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT DiffRadiance = DXGI_FORMAT_R16G16B16A16_FLOAT;

    // ffxDispatchDescDenoiser
    constexpr DXGI_FORMAT Motion = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT Normals = DXGI_FORMAT_R10G10B10A2_UNORM;
    constexpr DXGI_FORMAT SpecAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;
    constexpr DXGI_FORMAT DiffAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;
    constexpr DXGI_FORMAT LinearDepth = DXGI_FORMAT_R32_FLOAT;

    constexpr DXGI_FORMAT SkipSignal = DXGI_FORMAT_R16G16B16A16_FLOAT;

    constexpr DXGI_FORMAT OutputBuffer1 = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT OutputBuffer2 = DXGI_FORMAT_R16G16B16A16_FLOAT;
}

using OutputSpan = std::array<ID3D12Resource*, kConvOutputCount>;
using OutputSmartSpan = std::array<ComPtr<ID3D12Resource>, kConvOutputCount>;

// ffxDispatchDescDenoiserInput1Signal
struct Mode1Signal
{
    ComPtr<ID3D12Resource> Radiance; // RGB: Combined noisy color A: Specular Ray Length - RGBA16_FLOAT
    ComPtr<ID3D12Resource> FusedAlbedo; // RGB: max(specularAlbedo, diffuseAlbedo) A: NoV - RGBA8_UNORM
};

// ffxDispatchDescDenoiserInput2Signals
struct Mode2Signal
{
    ComPtr<ID3D12Resource> SpecRadiance; // RGB: Noisy specular lighting A: Specular Ray Length - RGBA16_FLOAT
    ComPtr<ID3D12Resource> DiffRadiance; // RGB: Noisy diffuse lighting - RGBA16_FLOAT
};

/**
 * @brief Output resources formatted for direct consumption by FSR Ray Regeneration.
 * All resources are automatically transitioned to SRV state after dispatch.
 */
union InternalOutputs
{
    struct
    {
        union 
        {
            Mode1Signal Mode1Inputs;
            Mode2Signal Mode2Inputs;
        };

        ComPtr<ID3D12Resource> Motion; // RG: Standard TSR motion vectors, B: Linear Depth Delta (CurrentLinearDepth - PrevLinearDepth) - RGBA16_FLOAT
        ComPtr<ID3D12Resource> Normals; // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional) - RGB10A2_UNORM
        ComPtr<ID3D12Resource> SpecAlbedo; // RGB: Specular Albedo, A: saturate(dot(Normal, ViewDir)) - RGBA8_UNORM
        ComPtr<ID3D12Resource> DiffAlbedo; // RGB: Diffuse Albedo, A: Metalness (heuristic approximate) - RGBA8_UNORM
        ComPtr<ID3D12Resource> LinearDepth; // R - R32_FLOAT

        ComPtr<ID3D12Resource> SkipSignal;
    };

    InternalOutputs()
    {
        for (auto& resource : AsArray)
            resource = ComPtr<ID3D12Resource>();
    }

    ~InternalOutputs() 
    { 
        for (auto& resource : AsArray)
            resource.~ComPtr();
    }

    ComPtr<ID3D12Resource> AsArray[8];

    ID3D12Resource* AsRawArray[8];
};

static void ThrowIfFailed(HRESULT hr, const char* msg)
{
    if (FAILED(hr))
        throw std::runtime_error(msg);
}

static UINT AlignTo256(UINT size)
{
    return (size + 255) & ~255;
}

static DXGI_FORMAT GetSRVFormat(DXGI_FORMAT defaultFormat) 
{
    switch (defaultFormat) 
    {
        case DXGI_FORMAT_D32_FLOAT:                return DXGI_FORMAT_R32_FLOAT;
        case DXGI_FORMAT_D16_UNORM:                return DXGI_FORMAT_R16_UNORM;
        case DXGI_FORMAT_D24_UNORM_S8_UINT:        return DXGI_FORMAT_R24_UNORM_X8_TYPELESS;
        case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:     return DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;

        case DXGI_FORMAT_R32_TYPELESS:             return DXGI_FORMAT_R32_FLOAT;
        case DXGI_FORMAT_R16_TYPELESS:             return DXGI_FORMAT_R16_UNORM;
        case DXGI_FORMAT_R8_TYPELESS:              return DXGI_FORMAT_R8_UNORM;

        case DXGI_FORMAT_R32G32B32A32_TYPELESS:    return DXGI_FORMAT_R32G32B32A32_FLOAT;
        case DXGI_FORMAT_R32G32B32_TYPELESS:       return DXGI_FORMAT_R32G32B32_FLOAT;
        case DXGI_FORMAT_R16G16B16A16_TYPELESS:    return DXGI_FORMAT_R16G16B16A16_FLOAT;
        case DXGI_FORMAT_R8G8B8A8_TYPELESS:        return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_R8G8_TYPELESS:            return DXGI_FORMAT_R8G8_UNORM;
        
        case DXGI_FORMAT_R10G10B10A2_TYPELESS:     return DXGI_FORMAT_R10G10B10A2_UNORM;
        case DXGI_FORMAT_R11G11B10_FLOAT:          return DXGI_FORMAT_R11G11B10_FLOAT;

        default: return defaultFormat;
    }
}

static ComPtr<ID3D12Resource> CreateInternalTexture(ID3D12Device* pDev, uint32_t width, uint32_t height,
    DXGI_FORMAT format, LPCWSTR name, D3D12_RESOURCE_STATES initialState)
{
    ScopedSkipHeapCapture skipHeapCapture {}; 

    D3D12_RESOURCE_DESC desc = {};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width;
    desc.Height = height;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = format;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;

    D3D12_HEAP_PROPERTIES heapProps = { D3D12_HEAP_TYPE_DEFAULT };
    ComPtr<ID3D12Resource> resource;

    ThrowIfFailed(pDev->CreateCommittedResource(
        &heapProps, 
        D3D12_HEAP_FLAG_NONE, 
        &desc, 
        initialState, 
        nullptr,
        IID_PPV_ARGS(&resource)),
        "Failed to create internal texture"
    );

    resource->SetName(name);
    return resource;
}

static void AddBarrier(ID3D12Resource* pRes, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after,
    std::span<D3D12_RESOURCE_BARRIER> barriers, int& bCount)
{
    if (!pRes) return;

    barriers[bCount].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barriers[bCount].Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    barriers[bCount].Transition.pResource = pRes;
    barriers[bCount].Transition.StateBefore = before;
    barriers[bCount].Transition.StateAfter = after;
    barriers[bCount].Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    bCount++;
}

static void AddBarriers(ID3D12GraphicsCommandList* cmdList, std::span<ID3D12Resource* const> resources,
                        D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
{
    constexpr UINT kMaxBarriers = 16;
    D3D12_RESOURCE_BARRIER barriers[kMaxBarriers] = {};   
    int bCount = 0;

    for (auto const& pRes: resources)
        AddBarrier(pRes, before, after, barriers, bCount);

    if (bCount > 0)
        cmdList->ResourceBarrier(bCount, barriers);
}

static void CreateSRV(ID3D12Device* pDev, D3D12_CPU_DESCRIPTOR_HANDLE destHandle, ID3D12Resource* pRes)
{
    ScopedSkipHeapCapture skipHeapCapture {};

    D3D12_SHADER_RESOURCE_VIEW_DESC srvDesc = {};
    srvDesc.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    srvDesc.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srvDesc.Texture2D.MipLevels = 1;

    if (pRes != nullptr)
    {
        srvDesc.Format = GetSRVFormat(pRes->GetDesc().Format);
        pDev->CreateShaderResourceView(pRes, &srvDesc, destHandle);
    }
    else
    {
        srvDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        pDev->CreateShaderResourceView(nullptr, &srvDesc, destHandle);
    }
}

static void CreateSRVs(ID3D12Device* pDev, FrameDescriptorHeap& heap, std::span<ID3D12Resource* const> inputs)
{
    for (UINT i = 0; i < (UINT)inputs.size(); i++)
        CreateSRV(pDev, heap.GetSrvCPU(i), inputs[i]);
}

static void CreateUAV(ID3D12Device* pDev, D3D12_CPU_DESCRIPTOR_HANDLE destHandle, ID3D12Resource* pRes,
    DXGI_FORMAT fmt = DXGI_FORMAT_UNKNOWN)
{
    ScopedSkipHeapCapture skipHeapCapture {};

    if (fmt == DXGI_FORMAT_UNKNOWN)
        fmt = (pRes != nullptr) ? GetSRVFormat(pRes->GetDesc().Format) : DXGI_FORMAT_R8G8B8A8_UNORM;

    D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = {};
    uavDesc.Format = fmt;
    uavDesc.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    pDev->CreateUnorderedAccessView(pRes, nullptr, &uavDesc, destHandle);
}

static void CreateUAVs(ID3D12Device* pDev, FrameDescriptorHeap& heap, std::span<ID3D12Resource*> resources, 
    std::span<DXGI_FORMAT> formats = {})
{
    for (UINT i = 0; i < (UINT)resources.size(); i++)
    {
        DXGI_FORMAT fmt = !formats.empty() ? formats[i] : DXGI_FORMAT_UNKNOWN;
        CreateUAV(pDev, heap.GetUavCPU(i), resources[i], fmt);
    }
}

struct ComputeState
{
    ID3D12Device* m_pDev = nullptr;
    
    ComPtr<ID3D12RootSignature> m_rootSig;
    ComPtr<ID3D12PipelineState> m_pso;
    std::array<FrameDescriptorHeap, kBackBufferCount> m_frameHeaps;

    ComPtr<ID3D12Resource> m_constUploadBuffer;
    byte* m_cbMappedData = nullptr;
    UINT m_cbSlotSize = 0;
    UINT m_cbCurrentFrameIndex = 0;

    ~ComputeState()
    {
        if (m_constUploadBuffer && m_cbMappedData)
        {
            m_constUploadBuffer->Unmap(0, nullptr);
            m_cbMappedData = nullptr;
        }
    }

    void Initialize(
        ID3D12Device* pDev,
        std::span<const byte> bytecode,
        UINT cbDataSize,
        UINT numSrvs,
        UINT numUavs,
        LPCWSTR cbName)
    {
        m_pDev = pDev;

        // Create Root Signature
        ThrowIfFailed(m_pDev->CreateRootSignature(0, bytecode.data(), bytecode.size(), IID_PPV_ARGS(&m_rootSig)),
              "Failed to create Root Signature");

        // Create PSO
        D3D12_COMPUTE_PIPELINE_STATE_DESC psoDesc = {};
        psoDesc.pRootSignature = m_rootSig.Get();
        psoDesc.CS = { bytecode.data(), bytecode.size() };
        ThrowIfFailed(m_pDev->CreateComputePipelineState(&psoDesc, IID_PPV_ARGS(&m_pso)), "Failed to create PSO");

        // Create Constant Buffer Upload Heap
        m_cbSlotSize = AlignTo256(cbDataSize);
        const UINT bufferSize = m_cbSlotSize * kBackBufferCount;

        D3D12_HEAP_PROPERTIES heapProps = { D3D12_HEAP_TYPE_UPLOAD };
        D3D12_RESOURCE_DESC bufferDesc = {};
        bufferDesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        bufferDesc.Width = bufferSize;
        bufferDesc.Height = 1;
        bufferDesc.DepthOrArraySize = 1;
        bufferDesc.MipLevels = 1;
        bufferDesc.SampleDesc.Count = 1;
        bufferDesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        bufferDesc.Flags = D3D12_RESOURCE_FLAG_NONE;

        ThrowIfFailed(m_pDev->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE, &bufferDesc, 
        D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&m_constUploadBuffer)), "Failed to create Constant Buffer");
        
        m_constUploadBuffer->SetName(cbName);
        D3D12_RANGE readRange = { 0, 0 }; 
        ThrowIfFailed(m_constUploadBuffer->Map(0, &readRange, reinterpret_cast<void**>(&m_cbMappedData)), "Failed to map Constant Buffer");

        // Create Descriptor Heaps
        for (auto& heap : m_frameHeaps)
        {
            if (!heap.Initialize(m_pDev, numSrvs, numUavs, 0, 0))
                throw std::runtime_error("Failed to initialize FrameDescriptorHeap");
        }
    }

    void Dispatch(
        ID3D12GraphicsCommandList* cmdList,
        std::span<const byte> cbData,
        std::span<ID3D12Resource* const> inputs,
        std::span<ID3D12Resource*> output,
        XMFLOAT2 outDim,
        bool autoTransitionUAV = true
    )
    {
        if (!cmdList) 
            return;

        ScopedSkipHeapCapture skipHeapCapture {};

        // Constant Buffer Updates
        const UINT currentFrame = m_cbCurrentFrameIndex;
        const UINT currentOffset = currentFrame * m_cbSlotSize;
        memcpy(m_cbMappedData + currentOffset, cbData.data(), cbData.size());

        D3D12_GPU_VIRTUAL_ADDRESS cbAddress = m_constUploadBuffer->GetGPUVirtualAddress() + currentOffset;
        m_cbCurrentFrameIndex = (m_cbCurrentFrameIndex + 1) % kBackBufferCount;

        // Transitions SRV -> UAV
        if (autoTransitionUAV)
            AddBarriers(cmdList, output, kSrvState, kUavState);

        // Update descriptors
        FrameDescriptorHeap& currentHeap = m_frameHeaps[currentFrame];
        CreateSRVs(m_pDev, currentHeap, inputs);
        CreateUAVs(m_pDev, currentHeap, output);

        // Configure pipeline
        cmdList->SetPipelineState(m_pso.Get());
        cmdList->SetComputeRootSignature(m_rootSig.Get());

        ID3D12DescriptorHeap* heaps[] = { currentHeap.GetHeapCSU() };
        cmdList->SetDescriptorHeaps(1, heaps);
        cmdList->SetComputeRootConstantBufferView(0, cbAddress);

        // SRV table
        cmdList->SetComputeRootDescriptorTable(1, currentHeap.GetTableGPUStart());

        // UAV table
        CD3DX12_GPU_DESCRIPTOR_HANDLE uavTable = currentHeap.GetTableGPUStart();
        uavTable.Offset((UINT)inputs.size(), m_pDev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV));
        cmdList->SetComputeRootDescriptorTable(2, uavTable);

        // Dispatch
        const uint32_t dimX = ((uint32_t)outDim.x + (kThreadGroupSizeX - 1)) / kThreadGroupSizeX;
        const uint32_t dimY = ((uint32_t)outDim.y + (kThreadGroupSizeY - 1)) / kThreadGroupSizeY;
        cmdList->Dispatch(dimX, dimY, 1);

        // Transition the UAVs back to SRV
        if (autoTransitionUAV)
            AddBarriers(cmdList, output, kUavState, kSrvState);
    }
};

// Private implementation
struct FSRDPreprocessor_Dx12::Impl
{
    ID3D12Device* m_pDev = nullptr;
    bool m_isMode2;

    ComputeState m_convShader;
    ComputeState m_compShader;

    uint32_t m_maxWidth = 0;
    uint32_t m_maxHeight = 0;

    // Output Targets
    InternalOutputs m_Out;
    ComPtr<ID3D12Resource> m_OutputBuffer1;
    ComPtr<ID3D12Resource> m_OutputBuffer2;

    void Initialize(std::span<const byte> convBytecode, std::span<const byte> compBytecode, bool isMode2)
    {
        ScopedSkipHeapCapture skipHeapCapture {};
        m_isMode2 = isMode2;

        LOG_DEBUG("Creating FSRD shaders.");

        m_convShader.Initialize(m_pDev, convBytecode, sizeof(ConvConstants), kConvInputCount, kConvOutputCount, L"FSRD_Conv_ConstantBuffer");
        m_compShader.Initialize(m_pDev, compBytecode, sizeof(CompConstants), kCompInputCount, kCompOutputCount, L"FSRD_Comp_ConstantBuffer");

        LOG_DEBUG("FSRD Conv & Comp shaders and resources initialized.");
    }

    void SetMaxRenderSize(uint32_t width, uint32_t height)
    {
        if (m_maxWidth == width && m_maxHeight == height)
            return;

        m_maxWidth = width;
        m_maxHeight = height;

        auto CreateTex = [&](DXGI_FORMAT fmt, LPCWSTR name)
        {
            return CreateInternalTexture(m_pDev, width, height, fmt, name, kSrvState);
        };

        m_Out.Motion = CreateTex(FSRDFormats::Motion, L"FSR_Conv_Motion");
        m_Out.Normals = CreateTex(FSRDFormats::Normals, L"FSR_Conv_Normals");
        m_Out.SpecAlbedo = CreateTex(FSRDFormats::SpecAlbedo, L"FSR_Conv_SpecAlbedo");
        m_Out.DiffAlbedo = CreateTex(FSRDFormats::DiffAlbedo, L"FSR_Conv_DiffAlbedo");
        m_Out.LinearDepth = CreateTex(FSRDFormats::LinearDepth, L"FSR_Conv_LinearDepth");
        m_Out.SkipSignal = CreateTex(FSRDFormats::SkipSignal, L"FSR_Conv_SkipSignal");
        m_OutputBuffer1 = CreateTex(FSRDFormats::OutputBuffer1, L"FSR_Conv_OutputBuffer1");

        if (m_isMode2)
        {
            m_OutputBuffer2 = CreateTex(FSRDFormats::OutputBuffer2, L"FSR_Conv_OutputBuffer2");

            m_Out.Mode2Inputs = 
            {
                .SpecRadiance = CreateTex(FSRDFormats::SpecRadiance, L"FSR_Conv_SpecRadiance"),
                .DiffRadiance = CreateTex(FSRDFormats::DiffRadiance, L"FSR_Conv_DiffRadiance")
            };
        }
        else
        {
            m_Out.Mode1Inputs = 
            {
                .Radiance = CreateTex(FSRDFormats::Radiance, L"FSR_Conv_Radiance"),
                .FusedAlbedo = CreateTex(FSRDFormats::FusedAlbedo, L"FSR_Conv_FusedAlbedo")
            };
        }
    }

    void DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConvInput& inputs, ConvConstants constants) 
    {
        if (!cmdList || !m_maxWidth)
            return;

        if (m_isMode2)
            constants.Flags |= uint32_t(ConvFlags::Mode2Signal);

        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));
        m_convShader.Dispatch(cmdList, cbData, inputs.AsArray, m_Out.AsRawArray, constants.RenderSize, true);

        // Transition output buffers to UAV after last composition pass or first init
        if (m_isMode2)
        {
            std::array<ID3D12Resource*, 2> buffers = { m_OutputBuffer1.Get(), m_OutputBuffer2.Get() };
            AddBarriers(cmdList, buffers, kSrvState, kUavState);
        }
        else
        {
            std::array<ID3D12Resource*, 1> buffers = { m_OutputBuffer1.Get() };
            AddBarriers(cmdList, buffers, kSrvState, kUavState);
        }
    }

    void DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        if (!cmdList || !m_maxWidth)
            return;

        CompInput inputs;
        CompConstants constants = 
        {
            .DstTexSize = desc.DstTexSize,
            .CorrelationBias = desc.CorrelationBias,
            .Flags = uint32_t(desc.Flags) 
        };

        if (m_isMode2)
        {
            auto& signalData = m_Out.Mode2Inputs;

            // Transition denoiser output buffers to SRV for composition
            std::array<ID3D12Resource*, 2> buffers = { m_OutputBuffer1.Get(), m_OutputBuffer2.Get() };
            AddBarriers(cmdList, buffers, kUavState, kSrvState);

            inputs = 
            {
                .InDenoisedSignal1 = m_OutputBuffer1.Get(),
                .InRawSignal1 = signalData.SpecRadiance.Get(),
                .InAlbedo1 = m_Out.SpecAlbedo.Get(),
                .InDenoisedSignal2 = m_OutputBuffer2.Get(),
                .InRawSignal2 = signalData.DiffRadiance.Get(),
                .InAlbedo2 = m_Out.DiffAlbedo.Get(),
                .InColorBeforeParticles = desc.InColorBeforeParticles,
                .InSkipSignal = m_Out.SkipSignal.Get()
            };

            constants.Flags |= uint32_t(CompFlags::Mode2Signal);
        }
        else
        {
            auto& signalData = m_Out.Mode1Inputs;
            std::array<ID3D12Resource*, 1> buffers = { m_OutputBuffer1.Get() };
            AddBarriers(cmdList, buffers, kUavState, kSrvState);

            inputs = 
            {
                .InDenoisedSignal1 = m_OutputBuffer1.Get(),
                .InRawSignal1 = signalData.Radiance.Get(),
                .InAlbedo1 = signalData.FusedAlbedo.Get(),
                .InColorBeforeParticles = desc.InColorBeforeParticles,
                .InSkipSignal = m_Out.SkipSignal.Get()
            };
        }  

        std::array<ID3D12Resource*, 1> uavs { m_Out.Motion.Get() };
        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));
        const XMFLOAT2 dstDim = { constants.DstTexSize.x, constants.DstTexSize.y };

        m_compShader.Dispatch(cmdList, cbData, inputs.AsArray, uavs, dstDim, true);
    }

    void Blit(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* srcTex, ID3D12Resource* dstTex,
              XMFLOAT2 dstDim) 
    {
        XMFLOAT2 srcDim = {};
        D3D12_RESOURCE_DESC srcDesc = srcTex->GetDesc();
        srcDim.x = (float)srcDesc.Width;
        srcDim.y = (float)srcDesc.Height;

        if (dstDim.x == 0 || dstDim.y == 0)
        {
            D3D12_RESOURCE_DESC dstDesc = dstTex->GetDesc();
            dstDim.x = (float)dstDesc.Width;
            dstDim.y = (float)dstDesc.Height;
        }

        if (!cmdList || dstDim.x == 0.0f)
            return;

        const CompInput inputs = 
        {
            .InDenoisedSignal1 = srcTex
        };
        const CompConstants constants = 
        {
            .DstTexSize = 
            {
                dstDim.x,           dstDim.y,
                (1.0f / dstDim.x),  (1.0f / dstDim.y)
            },
            .Flags = (uint32_t)CompFlags::RawSourceBlit | (uint32_t)CompFlags::ScaleSrc
        };

        std::array<ID3D12Resource*, 1> uavs { dstTex };
        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));

        m_compShader.Dispatch(cmdList, cbData, inputs.AsArray, uavs, dstDim, false);
    }
};

// Public interface

FSRDPreprocessor_Dx12::FSRDPreprocessor_Dx12(std::string_view name, ID3D12Device* pDev, bool isMode2) :
    m_impl(std::make_unique<Impl>()), 
    m_InstanceName(name),
    m_IsInitialized(false)
{
    try
    {
        m_impl->m_pDev = pDev;
        m_impl->Initialize(
            { reinterpret_cast<const byte*>(FSRDInputConv_cso), sizeof(FSRDInputConv_cso) },
            { reinterpret_cast<const byte*>(FSRDOutputComp_cso), sizeof(FSRDOutputComp_cso) },
            isMode2
        );
        m_IsInitialized = true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD shaders failed to initialize. Details: {}", err.what());
    }
}

FSRDPreprocessor_Dx12::~FSRDPreprocessor_Dx12() = default;

bool FSRDPreprocessor_Dx12::IsInit() const { return m_IsInitialized; }

std::string_view FSRDPreprocessor_Dx12::GetName() const { return m_InstanceName; }

bool FSRDPreprocessor_Dx12::SetMaxRenderSize(uint32_t width, uint32_t height)
{ 
    try
    {
        m_impl->SetMaxRenderSize(width, height);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("Failed to resize FSRD buffers. Details: {}", err.what());
    }

    return false;
}

bool FSRDPreprocessor_Dx12::DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConvInput& inputs, const ConvConstants& constants)
{ 
    try
    {
        m_impl->DispatchConversion(cmdList, inputs, constants);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD input conversion failed. Details: {}", err.what());
    }

    return false;
}

static void SetDescResources(InternalOutputs& descData, ffxDispatchDescHeader& signalHeader,
                             ffxDispatchDescDenoiser& dispatchDesc)
{
    dispatchDesc.header = 
    { 
        .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER,
        .pNext = &signalHeader // Link signal desc to main header
    };

    dispatchDesc.linearDepth = ffxApiGetResourceDX12(descData.LinearDepth.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
    dispatchDesc.motionVectors = ffxApiGetResourceDX12(descData.Motion.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
    dispatchDesc.normals = ffxApiGetResourceDX12(descData.Normals.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
    dispatchDesc.specularAlbedo = ffxApiGetResourceDX12(descData.SpecAlbedo.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
    dispatchDesc.diffuseAlbedo = ffxApiGetResourceDX12(descData.DiffAlbedo.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
}

void FSRDPreprocessor_Dx12::GetSignal(ffxDispatchDescDenoiserInput1Signal& signalDesc,
                                      ffxDispatchDescDenoiser& dispatchDesc) const
{
    auto& signalData = m_impl->m_Out.Mode1Inputs;

    signalDesc = 
    {
        .header = { .type = FFX_API_DISPATCH_DESC_INPUT_1_SIGNAL_TYPE_DENOISER },
        .radiance = 
        {
            .input = ffxApiGetResourceDX12(signalData.Radiance.Get()),
            .output = ffxApiGetResourceDX12(m_impl->m_OutputBuffer1.Get())
        },
        .fusedAlbedo = ffxApiGetResourceDX12(signalData.FusedAlbedo.Get())
    };

    SetDescResources(m_impl->m_Out, signalDesc.header, dispatchDesc);
}

void FSRDPreprocessor_Dx12::GetSignal(ffxDispatchDescDenoiserInput2Signals& signalDesc,
                                      ffxDispatchDescDenoiser& dispatchDesc) const
{
    auto& signalData = m_impl->m_Out.Mode2Inputs;
    auto& descData = m_impl->m_Out;

    signalDesc = 
    {
        .header = { .type = FFX_API_DISPATCH_DESC_INPUT_2_SIGNALS_TYPE_DENOISER }, 
        .specularRadiance = 
        {
            .input = ffxApiGetResourceDX12(signalData.SpecRadiance.Get()),
            .output = ffxApiGetResourceDX12(m_impl->m_OutputBuffer1.Get())
        },
        .diffuseRadiance = 
        {
            .input = ffxApiGetResourceDX12(signalData.DiffRadiance.Get()),
            .output = ffxApiGetResourceDX12(m_impl->m_OutputBuffer2.Get())
        },
    };

    SetDescResources(m_impl->m_Out, signalDesc.header, dispatchDesc);
}

bool FSRDPreprocessor_Dx12::DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
{
    try
    {
        m_impl->DispatchComposition(cmdList, desc);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD output composition failed. Details: {}", err.what());
    }

    return false;
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetCompositionOutput() const 
{ 
    return m_impl->m_Out.Motion.Get(); 
}

bool FSRDPreprocessor_Dx12::Blit(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* srcTex,
                                 ID3D12Resource* dstTex, XMFLOAT2 dim) const

{
    try
    {
        m_impl->Blit(cmdList, srcTex, dstTex, dim);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD blit failed. Details: {}", err.what());
    }

    return false;
}
