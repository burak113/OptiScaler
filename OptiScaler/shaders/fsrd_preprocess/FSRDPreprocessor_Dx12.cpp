#include "pch.h"
#include "FSRDPreprocessor_Dx12.h"
#include "precompile/FSRDInputConv_Shader.h" 
#include "precompile/FSRDOutputComp_Shader.h" 
#include "../Shader_Dx12Utils.h"

#include <d3dcompiler.h>
#include <d3d12.h>
#include <stdexcept>
#include <vector>
#include <string>
#include <array>
#include <algorithm>

#pragma comment(lib, "d3dcompiler.lib")

using Microsoft::WRL::ComPtr;
using ResFmtPair = std::pair<ID3D12Resource*, DXGI_FORMAT>;

constexpr UINT kBackBufferCount = 3;
constexpr UINT kInternalBufferCount = 0;

// Conversion Constants
constexpr UINT kConvInputCount = sizeof(FSRDPreprocessor_Dx12::ConvInput) / sizeof(ID3D12Resource*);
constexpr UINT kConvOutputCount = sizeof(FSRDPreprocessor_Dx12::ConvOutput) / sizeof(ID3D12Resource*);
constexpr UINT kConvDescriptorCount = kInternalBufferCount + kConvInputCount + kConvOutputCount;

// Composition Constants
constexpr UINT kCompInputCount = sizeof(FSRDPreprocessor_Dx12::CompInput) / sizeof(ID3D12Resource*);
constexpr UINT kCompOutputCount = 1;

constexpr UINT kThreadGroupSize = 8;

namespace FSRDFormats
{
    // ffxDispatchDescDenoiserInput1Signal
    constexpr DXGI_FORMAT Radiance = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT FusedAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;

    // ffxDispatchDescDenoiser
    constexpr DXGI_FORMAT Motion = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT Normals = DXGI_FORMAT_R10G10B10A2_UNORM;
    constexpr DXGI_FORMAT SpecAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;
    constexpr DXGI_FORMAT DiffAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;
    constexpr DXGI_FORMAT LinearDepth = DXGI_FORMAT_R32_FLOAT;

    constexpr DXGI_FORMAT SkipSignal = DXGI_FORMAT_R16G16B16A16_FLOAT;
}

using OutputSpan = std::array<ID3D12Resource*, kConvOutputCount>;

// A version of the output struct with ComPtrs for internal RAII lifetime management
struct InternalOutputs
{
    ComPtr<ID3D12Resource> Radiance;
    ComPtr<ID3D12Resource> FusedAlbedo;

    ComPtr<ID3D12Resource> Motion;
    ComPtr<ID3D12Resource> Normals;
    ComPtr<ID3D12Resource> SpecAlbedo;
    ComPtr<ID3D12Resource> DiffAlbedo;
    ComPtr<ID3D12Resource> LinearDepth;

    ComPtr<ID3D12Resource> SkipSignal;

    OutputSpan& AsRawArray() { return *reinterpret_cast<OutputSpan*>(this); }

    const OutputSpan& AsRawArray() const { return *reinterpret_cast<const OutputSpan*>(this); }

    const FSRDPreprocessor_Dx12::ConvOutput& AsRaw() const
    {
        return *reinterpret_cast<const FSRDPreprocessor_Dx12::ConvOutput*>(this);
    }
};

static_assert(sizeof(InternalOutputs) == sizeof(OutputSpan), 
    "Size mismatch.");
static_assert(alignof(InternalOutputs) == alignof(OutputSpan), 
    "Alignment mismatch.");
static_assert(sizeof(InternalOutputs) == sizeof(FSRDPreprocessor_Dx12::ConvOutput), 
    "Size mismatch.");
static_assert(alignof(InternalOutputs) == alignof(FSRDPreprocessor_Dx12::ConvOutput), 
    "Alignment mismatch.");

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

static void AddBarriers(std::span<ID3D12Resource* const> resources, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after,
    std::span<D3D12_RESOURCE_BARRIER> barriers, int& bCount)
{
    for (auto const& pRes: resources)
        AddBarrier(pRes, before, after, barriers, bCount);
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
        DirectX::XMFLOAT2 renderSize,
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
        const D3D12_RESOURCE_STATES srvState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        constexpr UINT kMaxBarriers = 16;
        D3D12_RESOURCE_BARRIER barriers[kMaxBarriers] = {};
        int bCount = 0;

        if (autoTransitionUAV)
            AddBarriers(output, srvState, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, barriers, bCount);

        if (bCount > 0)
            cmdList->ResourceBarrier(bCount, barriers);  

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
        const uint32_t dimX = ((uint32_t)renderSize.x + (kThreadGroupSize - 1)) / kThreadGroupSize;
        const uint32_t dimY = ((uint32_t)renderSize.y + (kThreadGroupSize - 1)) / kThreadGroupSize;
        cmdList->Dispatch(dimX, dimY, 1);

        // Transition the UAVs back to SRV
        bCount = 0;

        if (autoTransitionUAV)
            AddBarriers(output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, srvState, barriers, bCount);

        if (bCount > 0)
            cmdList->ResourceBarrier(bCount, barriers);
    }
};

// Private implementation
struct FSRDPreprocessor_Dx12::Impl
{
    ID3D12Device* m_pDev = nullptr;
    
    ComputeState m_convShader;
    ComputeState m_compShader;

    uint32_t m_maxWidth = 0;
    uint32_t m_maxHeight = 0;

    // Output Targets
    InternalOutputs m_Out;

    void Initialize(std::span<const byte> convBytecode, std::span<const byte> compBytecode)
    {
        ScopedSkipHeapCapture skipHeapCapture {};

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

        static const auto initState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        auto CreateTex = [&](DXGI_FORMAT fmt, LPCWSTR name)
        {
            return CreateInternalTexture(m_pDev, width, height, fmt, name, initState);
        };        

        m_Out = 
        {
            .Radiance       = CreateTex(FSRDFormats::Radiance,      L"FSR_Conv_Radiance"),
            .FusedAlbedo    = CreateTex(FSRDFormats::FusedAlbedo,   L"FSR_Conv_FusedAlbedo"),
            .Motion         = CreateTex(FSRDFormats::Motion,        L"FSR_Conv_Motion"),
            .Normals        = CreateTex(FSRDFormats::Normals,       L"FSR_Conv_Normals"),
            .SpecAlbedo     = CreateTex(FSRDFormats::SpecAlbedo,    L"FSR_Conv_SpecAlbedo"),
            .DiffAlbedo     = CreateTex(FSRDFormats::DiffAlbedo,    L"FSR_Conv_DiffAlbedo"),
            .LinearDepth    = CreateTex(FSRDFormats::LinearDepth,   L"FSR_Conv_LinearDepth"),
            .SkipSignal     = CreateTex(FSRDFormats::SkipSignal,    L"FSR_Conv_SkipSignal")
        };
    }

    void DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConvInput& inputs, const ConvConstants& constants) 
    {
        if (!cmdList || !m_maxWidth)
            return;

        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));
        m_convShader.Dispatch(cmdList, cbData, inputs.AsArray, m_Out.AsRawArray(), constants.RenderSize, true);
    }

    void DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompInput& inputs, const CompConstants& constants)
    {
        if (!cmdList || !m_maxWidth)
            return;

        std::array<ID3D12Resource*, 1> uavs { m_Out.Radiance.Get() };
        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));
        m_compShader.Dispatch(cmdList, cbData, inputs.AsArray, uavs, constants.RenderSize, true);
    }

    void Blit(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* srcTex, ID3D12Resource* dstTex,
              DirectX::XMFLOAT2 dim) 
    {
        if (dim.x == 0 || dim.y == 0)
        {
            D3D12_RESOURCE_DESC srcDesc = srcTex->GetDesc();
            dim.x = (float)srcDesc.Width;
            dim.y = (float)srcDesc.Height;
        }

        if (!cmdList || dim.x == 0.0f)
            return;

        CompInput inputs = 
        {
            .InPrimaryColor = srcTex
        };
        CompConstants constants = 
        {
            .RenderSize = dim,
            .Flags = (uint32_t)CompFlags::RawSourceBlit
        };

        std::array<ID3D12Resource*, 1> uavs { dstTex };
        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));

        m_compShader.Dispatch(cmdList, cbData, inputs.AsArray, uavs, dim, false);
    }
};

// Public interface

FSRDPreprocessor_Dx12::FSRDPreprocessor_Dx12(std::string_view name, ID3D12Device* pDev) :
    m_impl(std::make_unique<Impl>()), 
    m_InstanceName(name),
    m_IsInitialized(false)
{
    try
    {
        m_impl->m_pDev = pDev;
        m_impl->Initialize(
            { reinterpret_cast<const byte*>(FSRDInputConv_cso), sizeof(FSRDInputConv_cso) },
            { reinterpret_cast<const byte*>(FSRDOutputComp_cso), sizeof(FSRDOutputComp_cso) }
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

FSRDPreprocessor_Dx12::ConvOutput FSRDPreprocessor_Dx12::GetConvOutput() const
{ 
    return m_impl->m_Out.AsRaw(); 
}

bool FSRDPreprocessor_Dx12::DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompInput& inputs, const CompConstants& constants)
{
    try
    {
        m_impl->DispatchComposition(cmdList, inputs, constants);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD output composition failed. Details: {}", err.what());
    }

    return false;
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetCompOutput() const 
{
    return m_impl->m_Out.Radiance.Get(); }

bool FSRDPreprocessor_Dx12::Blit(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* srcTex,
                                 ID3D12Resource* dstTex, DirectX::XMFLOAT2 dim) const

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
