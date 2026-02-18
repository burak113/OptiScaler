#include "pch.h"
#include "FSRDInputConv_Dx12.h"
#include "precompile/FSRDInputConv_Shader.h" 

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
constexpr UINT kConvInputCount = sizeof(FSRDInputConv_Dx12::InputResources) / sizeof(ID3D12Resource*);
constexpr UINT kConvOutputCount = sizeof(FSRDInputConv_Dx12::OutputResources) / sizeof(ID3D12Resource*);
constexpr UINT kConvDescriptorCount = kInternalBufferCount + kConvInputCount + kConvOutputCount;
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

    OutputSpan& AsRawArray() { return *reinterpret_cast<OutputSpan*>(this); }

    const OutputSpan& AsRawArray() const { return *reinterpret_cast<const OutputSpan*>(this); }

    const FSRDInputConv_Dx12::OutputResources& AsRaw() const
    {
        return *reinterpret_cast<const FSRDInputConv_Dx12::OutputResources*>(this);
    }
};

static_assert(sizeof(InternalOutputs) == sizeof(OutputSpan), 
    "Size mismatch.");
static_assert(alignof(InternalOutputs) == alignof(OutputSpan), 
    "Alignment mismatch.");
static_assert(sizeof(InternalOutputs) == sizeof(FSRDInputConv_Dx12::OutputResources), 
    "Size mismatch.");
static_assert(alignof(InternalOutputs) == alignof(FSRDInputConv_Dx12::OutputResources), 
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

static void CreateSRV(ID3D12Device* pDev, D3D12_CPU_DESCRIPTOR_HANDLE& destHandle, UINT handleInc,
                      ID3D12Resource* pRes)
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

    destHandle.ptr += handleInc;
}

static void CreateSRVs(ID3D12Device* pDev, D3D12_CPU_DESCRIPTOR_HANDLE& destHandle, UINT handleInc,
    std::span<ID3D12Resource* const> inputs)
{
    for (auto& pRes : inputs)
        CreateSRV(pDev, destHandle, handleInc, pRes);
}

static void CreateUAV(ID3D12Device* pDev, D3D12_CPU_DESCRIPTOR_HANDLE& destHandle, UINT handleInc, ID3D12Resource* pRes,
    DXGI_FORMAT fmt)
{
    ScopedSkipHeapCapture skipHeapCapture {};

    D3D12_UNORDERED_ACCESS_VIEW_DESC uavDesc = {};
    uavDesc.Format = fmt;
    uavDesc.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    pDev->CreateUnorderedAccessView(pRes, nullptr, &uavDesc, destHandle);
    destHandle.ptr += handleInc;
}

static void CreateUAVs(ID3D12Device* pDev, D3D12_CPU_DESCRIPTOR_HANDLE& destHandle, UINT handleInc, std::span<ResFmtPair> resources)
{
    for (const auto& res : resources)
        CreateUAV(pDev, destHandle, handleInc, res.first, res.second);
}

// Private implementation
struct FSRDInputConv_Dx12::Impl
{
    ID3D12Device* m_pDev = nullptr;
    ComPtr<ID3D12RootSignature> m_rootSignature;
    ComPtr<ID3D12PipelineState> m_pso;

    // Descriptor
    ComPtr<ID3D12DescriptorHeap> m_descHeap;
    UINT m_descriptorSize = 0;

    // Constant buffer
    ComPtr<ID3D12Resource> m_constUploadBuffer;
    UINT8* m_cbMappedData = nullptr;
    UINT m_cbSlotSize = 0;
    UINT m_cbCurrentFrameIndex = 0;

    uint32_t m_maxWidth = 0;
    uint32_t m_maxHeight = 0;

    // Output Targets
    InternalOutputs m_Out;

    ~Impl()
    {
        // Ensure we unmap before destruction
        if (m_constUploadBuffer && m_cbMappedData)
        {
            m_constUploadBuffer->Unmap(0, nullptr);
            m_cbMappedData = nullptr;
        }
    }

    void Initialize(const void* shaderBytecode, size_t shaderLength)
    {
        ScopedSkipHeapCapture skipHeapCapture {};

        LOG_DEBUG("Creating FSRD Conv shader. ({} bytes)", shaderLength);

        // Create Root Signature
        // Note: The shader source must now specify a CBV at b0, not RootConstants!
        ThrowIfFailed(m_pDev->CreateRootSignature(0, shaderBytecode, shaderLength, IID_PPV_ARGS(&m_rootSignature)),
                      "Failed to create Root Signature");

        // Create PSO
        D3D12_COMPUTE_PIPELINE_STATE_DESC psoDesc = {};
        psoDesc.pRootSignature = m_rootSignature.Get();
        psoDesc.CS = { shaderBytecode, shaderLength };
        ThrowIfFailed(m_pDev->CreateComputePipelineState(&psoDesc, IID_PPV_ARGS(&m_pso)), "Failed to create PSO");

        // Create Constant Buffer Upload Heap
        m_cbSlotSize = AlignTo256(sizeof(Constants));
        
        // Total size for all in-flight frames
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

        ThrowIfFailed(m_pDev->CreateCommittedResource(
            &heapProps,
            D3D12_HEAP_FLAG_NONE,
            &bufferDesc,
            D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,
            IID_PPV_ARGS(&m_constUploadBuffer)),
            "Failed to create Constant Buffer"
        );
        
        m_constUploadBuffer->SetName(L"FSRD_Conv_ConstantBuffer");

        D3D12_RANGE readRange = { 0, 0 }; // We do not intend to read from this resource on the CPU
        ThrowIfFailed(m_constUploadBuffer->Map(0, &readRange, reinterpret_cast<void**>(&m_cbMappedData)), 
            "Failed to map Constant Buffer");

        // Create Descriptor Heap
        D3D12_DESCRIPTOR_HEAP_DESC heapDesc = {};
        heapDesc.NumDescriptors = kConvDescriptorCount;
        heapDesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heapDesc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;

        ThrowIfFailed(m_pDev->CreateDescriptorHeap(&heapDesc, IID_PPV_ARGS(&m_descHeap)),
                      "Failed to create Descriptor Heap");

        m_descriptorSize = m_pDev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);

        LOG_DEBUG("Creating FSRD Conv shader and resources initialized.", shaderLength);
    }

    void SetMaxRenderSize(uint32_t width, uint32_t height)
    {
        if (m_maxWidth == width && m_maxHeight == height)
            return;

        m_maxWidth = width;
        m_maxHeight = height;

        static const auto initState =
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;

        auto CreateTex = [&](DXGI_FORMAT fmt, LPCWSTR name)
        {
            return CreateInternalTexture(m_pDev, width, height, fmt, name, initState);
        };        

        m_Out = 
        {
            .Radiance = CreateTex(FSRDFormats::Radiance, L"FSR_Conv_Radiance"),
            .FusedAlbedo = CreateTex(FSRDFormats::FusedAlbedo, L"FSR_Conv_FusedAlbedo"),
            .Motion = CreateTex(FSRDFormats::Motion, L"FSR_Conv_Motion"),
            .Normals = CreateTex(FSRDFormats::Normals, L"FSR_Conv_Normals"),
            .SpecAlbedo = CreateTex(FSRDFormats::SpecAlbedo, L"FSR_Conv_SpecAlbedo"),
            .DiffAlbedo = CreateTex(FSRDFormats::DiffAlbedo, L"FSR_Conv_DiffAlbedo"),
            .LinearDepth = CreateTex(FSRDFormats::LinearDepth, L"FSR_Conv_LinearDepth")
        };
    }

    void Dispatch(ID3D12GraphicsCommandList* cmdList, const InputResources& inputs, const Constants& constants) 
    {
        if (!cmdList || !m_maxWidth)
            return;

        // Update constant buffer
        // Copy data to the current frame's slot in the upload buffer
        UINT currentOffset = m_cbCurrentFrameIndex * m_cbSlotSize;
        memcpy(m_cbMappedData + currentOffset, &constants, sizeof(Constants));

        // Get the GPU Virtual Address for this slot
        D3D12_GPU_VIRTUAL_ADDRESS cbAddress = m_constUploadBuffer->GetGPUVirtualAddress() + currentOffset;

        // Advance ring buffer index
        m_cbCurrentFrameIndex = (m_cbCurrentFrameIndex + 1) % kBackBufferCount;

        // Resource transitions
        D3D12_RESOURCE_BARRIER barriers[kConvOutputCount] = {};
        int bCount = 0;

        const D3D12_RESOURCE_STATES srvState = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        AddBarriers(m_Out.AsRawArray(), srvState, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, barriers, bCount);

        if (bCount > 0)
            cmdList->ResourceBarrier(bCount, barriers);

        // Update descriptor heap
        D3D12_CPU_DESCRIPTOR_HANDLE destHandle = m_descHeap->GetCPUDescriptorHandleForHeapStart();
        UINT handleInc = m_descriptorSize;

        // SRV Inputs (t0 - t7)
        CreateSRVs(m_pDev, destHandle, handleInc, inputs.AsArray);

        // UAV Outputs (u0 - u6)
        auto uavs = std::to_array<ResFmtPair>(
        {
            { m_Out.Radiance.Get(), FSRDFormats::Radiance },
            { m_Out.FusedAlbedo.Get(), FSRDFormats::FusedAlbedo },
            { m_Out.Motion.Get(), FSRDFormats::Motion },
            { m_Out.Normals.Get(), FSRDFormats::Normals },
            { m_Out.SpecAlbedo.Get(), FSRDFormats::SpecAlbedo },
            { m_Out.DiffAlbedo.Get(), FSRDFormats::DiffAlbedo },
            { m_Out.LinearDepth.Get(), FSRDFormats::LinearDepth }
        }); 

        CreateUAVs(m_pDev, destHandle, handleInc, uavs);

        // Configure pipeline and dispatch
        cmdList->SetPipelineState(m_pso.Get());
        cmdList->SetComputeRootSignature(m_rootSignature.Get());

        ID3D12DescriptorHeap* heaps[] = { m_descHeap.Get() };
        cmdList->SetDescriptorHeaps(1, heaps);

        cmdList->SetComputeRootConstantBufferView(0, cbAddress);

        // t0-t8: SRV Table
        const D3D12_GPU_DESCRIPTOR_HANDLE tableStart = m_descHeap->GetGPUDescriptorHandleForHeapStart();
        cmdList->SetComputeRootDescriptorTable(1, tableStart);

        // u0-u5: UAV Table
        D3D12_GPU_DESCRIPTOR_HANDLE uavStart = tableStart;
        uavStart.ptr += kConvInputCount * (uint64_t)handleInc;
        cmdList->SetComputeRootDescriptorTable(2, uavStart);

        const uint32_t dimX = ((uint32_t)constants.RenderSize.x + (kThreadGroupSize - 1)) / kThreadGroupSize;
        const uint32_t dimY = ((uint32_t)constants.RenderSize.y + (kThreadGroupSize - 1)) / kThreadGroupSize;
        cmdList->Dispatch(dimX, dimY, 1);

        // Transition the UAVs back to SRV
        bCount = 0;
        AddBarriers(m_Out.AsRawArray(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, srvState, barriers, bCount);

        if (bCount > 0)
            cmdList->ResourceBarrier(bCount, barriers);
    }
};

// Public interface

FSRDInputConv_Dx12::FSRDInputConv_Dx12(std::string_view name, ID3D12Device* pDev, std::string_view hlslSrc) : 
    m_impl(std::make_unique<Impl>()), 
    m_InstanceName(name),
    m_IsInitialized(false)
{
    try
    {
        m_impl->m_pDev = pDev;

        ComPtr<ID3DBlob> shaderBlob;
        ComPtr<ID3DBlob> errorBlob;

        // Compile Shader for SM 5.1
        const HRESULT hr = D3DCompile(hlslSrc.data(), hlslSrc.size(), "FSRDInputConv", nullptr, nullptr, "CSMain",
                                      "cs_5_1", 0, 0, &shaderBlob, &errorBlob);

        if (FAILED(hr))
        {
            if (errorBlob)
            {
                std::string err = (char*) errorBlob->GetBufferPointer();
                throw std::runtime_error("Shader Compilation Failed: " + err);
            }
            else
                throw std::runtime_error("Shader Compilation Failed with unknown error");
        }

        m_impl->Initialize(shaderBlob->GetBufferPointer(), shaderBlob->GetBufferSize());
        m_IsInitialized = true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD input converter failed to initialize. Details: {}", err.what());
    }
}

FSRDInputConv_Dx12::FSRDInputConv_Dx12(std::string_view name, ID3D12Device* pDev) :
    m_impl(std::make_unique<Impl>()), 
    m_InstanceName(name),
    m_IsInitialized(false)
{
    try
    {
        m_impl->m_pDev = pDev;
        m_impl->Initialize(reinterpret_cast<const void*>(FSRDInputConv_cso), sizeof(FSRDInputConv_cso));
        m_IsInitialized = true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD input converter failed to initialize. Details: {}", err.what());
    }
}

FSRDInputConv_Dx12::~FSRDInputConv_Dx12() = default;

bool FSRDInputConv_Dx12::IsInit() const { return m_IsInitialized; }

std::string_view FSRDInputConv_Dx12::GetName() const { return m_InstanceName; }

bool FSRDInputConv_Dx12::SetMaxRenderSize(uint32_t width, uint32_t height)
{ 
    try
    {
        m_impl->SetMaxRenderSize(width, height);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("Failed to resize FSRD conversion buffers. Details: {}", err.what());
    }

    return false;
}

bool FSRDInputConv_Dx12::Dispatch(ID3D12GraphicsCommandList* cmdList, const InputResources& inputs, const Constants& constants)
{ 
    try
    {
        m_impl->Dispatch(cmdList, inputs, constants);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD input conversion failed. Details: {}", err.what());
    }

    return false;
}

FSRDInputConv_Dx12::OutputResources FSRDInputConv_Dx12::GetOutputs() const
{ 
    return m_impl->m_Out.AsRaw();
}