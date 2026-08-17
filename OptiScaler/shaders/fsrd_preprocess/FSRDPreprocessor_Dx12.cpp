#include "pch.h"
#include "FSRDPreprocessor_Dx12.h"
#include "FSRDShaderUtils.h"
#include "FSRDShaderData.h"
#include "precompile/FSRDInputConv_Shader.h" 
#include "precompile/FSRDFloorSeed_Shader.h" 
#include "precompile/FSRDFloor_Shader.h" 
#include "precompile/FSRDOutputComp_Shader.h" 

#include "dx12/ffx_api_dx12.h"
#include "fsr-rr/ffx_denoiser.h"

#include <d3dcompiler.h>
#include <d3d12.h>
#include <stdexcept>
#include <vector>
#include <string>
#include <array>
#include <algorithm>
#include <cmath>
#include <utility>

#pragma comment(lib, "d3dcompiler.lib")

using Microsoft::WRL::ComPtr;
using namespace DirectX;
using namespace FSRD;

constexpr UINT kBackBufferCount = 3;

constexpr UINT kThreadGroupSizeX = 8;
constexpr UINT kThreadGroupSizeY = 8;

constexpr D3D12_RESOURCE_STATES kSrvState =
    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
constexpr D3D12_RESOURCE_STATES kUavState = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;

namespace FSRDFormats
{
    constexpr DXGI_FORMAT IndirectSpecular = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT DirectDiffuse = DXGI_FORMAT_R16G16B16A16_FLOAT;

    // ffxDispatchDescDenoiser
    constexpr DXGI_FORMAT Motion = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT Normals = DXGI_FORMAT_R10G10B10A2_UNORM;
    constexpr DXGI_FORMAT SpecAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;
    constexpr DXGI_FORMAT DiffAlbedo = DXGI_FORMAT_R8G8B8A8_UNORM;
    constexpr DXGI_FORMAT LinearDepth = DXGI_FORMAT_R32_FLOAT;

    constexpr DXGI_FORMAT SkipSignal = DXGI_FORMAT_R16G16B16A16_FLOAT;

    // Carries a finished HDR image plus its mix weight, so it needs the same range as
    // the skip signal it is an alternative to.
    constexpr DXGI_FORMAT Handover = SkipSignal;

    constexpr DXGI_FORMAT OutputBuffer1 = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT OutputBuffer2 = DXGI_FORMAT_R16G16B16A16_FLOAT;

    constexpr DXGI_FORMAT AmbientOcclusion = DXGI_FORMAT_R8_UNORM;
    constexpr DXGI_FORMAT SpecularOcclusion = DXGI_FORMAT_R8_UNORM;
    constexpr DXGI_FORMAT DebugView = DXGI_FORMAT_R16G16B16A16_FLOAT;
}

struct ComputeState
{
    ID3D12Device* m_pDev = nullptr;
    
    ComPtr<ID3D12RootSignature> m_rootSig;
    ComPtr<ID3D12PipelineState> m_pso;
    std::vector<FrameDescriptorHeap> m_frameHeaps;

    ComPtr<ID3D12Resource> m_constUploadBuffer;
    byte* m_cbMappedData = nullptr;
    UINT m_cbSlotSize = 0;
    UINT m_cbCurrentFrameIndex = 0;
    UINT backBufferCount = kBackBufferCount;

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
        LPCWSTR cbName,
        UINT backBufferCount = kBackBufferCount)
    {
        m_pDev = pDev;
        this->backBufferCount = backBufferCount;

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
        const UINT bufferSize = m_cbSlotSize * backBufferCount;

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

        m_frameHeaps.resize(backBufferCount);

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
        std::span<const MipChainDesc> inputMips,
        std::span<ID3D12Resource*> output,
        std::span<const UINT> outputMips,
        XMFLOAT2 outDim,
        bool autoBarrierOutput = true
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
        m_cbCurrentFrameIndex = (m_cbCurrentFrameIndex + 1) % backBufferCount;

        // Transitions SRV -> UAV
        if (autoBarrierOutput)
            AddBarriers(cmdList, output, outputMips, kSrvState, kUavState);

        // Update descriptors
        FrameDescriptorHeap& currentHeap = m_frameHeaps[currentFrame];
        CreateSRVs(m_pDev, currentHeap, inputs, inputMips);
        CreateUAVs(m_pDev, currentHeap, output, outputMips);

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
        const UINT dimX = ((UINT)outDim.x + (kThreadGroupSizeX - 1)) / kThreadGroupSizeX;
        const UINT dimY = ((UINT)outDim.y + (kThreadGroupSizeY - 1)) / kThreadGroupSizeY;
        cmdList->Dispatch(dimX, dimY, 1);

        // Transition the UAVs back to SRV
        if (autoBarrierOutput)
            AddBarriers(cmdList, output, outputMips, kUavState, kSrvState);
    }

    void Dispatch(
        ID3D12GraphicsCommandList* cmdList,
        std::span<const byte> cbData,
        std::span<ID3D12Resource* const> inputs,
        std::span<ID3D12Resource*> output,
        XMFLOAT2 outDim,
        bool autoBarrierOutput = true
    )
    {
        Dispatch(cmdList, cbData, inputs, {}, output, {}, outDim, autoBarrierOutput);
    }
};

// Private implementation
struct FSRDPreprocessor_Dx12::Impl
{
    ID3D12Device* m_pDev = nullptr;

    ComputeState m_floorSeedShader;
    ComputeState m_floorFilterShader;
    ComputeState m_convShader;
    ComputeState m_compShader;

    UINT m_maxWidth = 0;
    UINT m_maxHeight = 0;

    // Drives the a-trous filter's temporal pattern rotation. Per instance, not a
    // function-local static: the feature can destroy and recreate the converter, and
    // two live converters would otherwise advance one shared counter twice a frame.
    uint32_t m_floorFilterFrameIndex = 0;

    // Output Targets
    // Internal storage
    Conversion::Output m_out;
    ComPtr<ID3D12Resource> m_LinearDepth;
    ComPtr<ID3D12Resource> m_outputBuffer1;
    ComPtr<ID3D12Resource> m_outputBuffer2;
    ComPtr<ID3D12Resource> m_ambientOcclusionOutput;
    ComPtr<ID3D12Resource> m_specularOcclusionOutput;
    ComPtr<ID3D12Resource> m_debugViewOutput;
    // A replaced debug target cannot be freed while an earlier command list can still
    // reference it. Retain one full descriptor/constant-buffer rotation rather than
    // assuming resolution changes are separated by several frames: DRS may resize on
    // consecutive frames.
    std::array<ComPtr<ID3D12Resource>, kBackBufferCount> m_retiredDebugViewOutputs;
    UINT m_retiredDebugViewOutputIndex = 0;
    UINT m_debugViewWidth = 0;
    UINT m_debugViewHeight = 0;

    // Floor filter
    ID3D12Resource* m_smoothFloor;

    bool m_radianceOutputsInUavState = false;
    bool m_ambientOcclusionOutputInUavState = false;
    bool m_specularOcclusionOutputInUavState = false;
    bool m_debugViewOutputInUavState = false;

    void Initialize(
        std::span<const byte> blSeedByteCode, 
        std::span<const byte> blPyramidByteCode, 
        std::span<const byte> convByteCode, 
        std::span<const byte> compByteCode
    )
    {
        ScopedSkipHeapCapture skipHeapCapture {};

        LOG_DEBUG("Creating FSRD interop shaders...");

        m_floorSeedShader.Initialize(m_pDev, blSeedByteCode, sizeof(FloorSeed::Constants), 
            FloorSeed::Input::kCount, FloorSeed::Output::kCount, L"FSRD_FloorSeed_Constants", FloorSeed::kBackBufferCount);
        m_floorFilterShader.Initialize(m_pDev, blPyramidByteCode, sizeof(FloorFilter::Constants), 
            FloorFilter::Input::kCount, FloorFilter::Output::kCount, L"FSRD_FloorFilter_Constants", FloorFilter::kBackBufferCount);
        m_convShader.Initialize(m_pDev, convByteCode, sizeof(Conversion::Constants), 
            Conversion::Input::kCount, Conversion::Output::kCount, L"FSRD_Conv_Constants", Conversion::kBackBufferCount);
        m_compShader.Initialize(m_pDev, compByteCode, sizeof(Composition::Constants), 
            Composition::Input::kCount, Composition::kOutputCount, L"FSRD_Comp_Constants", Composition::kBackBufferCount);

        LOG_DEBUG("FSRD interop shaders and resources initialized.");
    }

    void SetMaxRenderSize(UINT width, UINT height)
    {
        if (m_maxWidth == width && m_maxHeight == height)
            return;

        // Clear the latch before allocating rather than after. CreateTexture2D
        // throws on failure, which leaves the object holding a mix of new- and
        // old-sized textures; if the requested dimensions were already latched, an
        // identical retry would hit the early-out above and silently "succeed" with
        // that mix still in place. The latch is set at the end, once every
        // allocation has actually completed.
        m_maxWidth = 0;
        m_maxHeight = 0;

        auto CreateTex = [&](DXGI_FORMAT fmt, LPCWSTR name, UINT mipLevels = 1)
        { 
            return CreateTexture2D(m_pDev, width, height, fmt, name, kSrvState, mipLevels);
        };

        auto& outResources = m_out.Resources;
        outResources.Motion = CreateTex(FSRDFormats::Motion, L"FSR_Conv_Motion");
        outResources.Normals = CreateTex(FSRDFormats::Normals, L"FSR_Conv_Normals");
        outResources.SpecAlbedo = CreateTex(FSRDFormats::SpecAlbedo, L"FSR_Conv_SpecAlbedo");
        outResources.DiffAlbedo = CreateTex(FSRDFormats::DiffAlbedo, L"FSR_Conv_DiffAlbedo");
        outResources.SkipSignal = CreateTex(FSRDFormats::SkipSignal, L"FSR_Conv_SkipSignal");
        outResources.Handover = CreateTex(FSRDFormats::Handover, L"FSR_Conv_Handover");
        m_LinearDepth = CreateTex(FSRDFormats::LinearDepth, L"FSR_Conv_LinearDepth");
        m_outputBuffer1 = CreateTex(FSRDFormats::OutputBuffer1, L"FSR_Conv_OutputBuffer1");
        m_outputBuffer2 = CreateTex(FSRDFormats::OutputBuffer2, L"FSR_Conv_OutputBuffer2");
        m_ambientOcclusionOutput =
            CreateTex(FSRDFormats::AmbientOcclusion, L"FSR_RR_AmbientOcclusion_Output");
        m_specularOcclusionOutput =
            CreateTex(FSRDFormats::SpecularOcclusion, L"FSR_RR_SpecularOcclusion_Output");

        m_smoothFloor = nullptr;
        m_radianceOutputsInUavState = false;
        m_ambientOcclusionOutputInUavState = false;
        m_specularOcclusionOutputInUavState = false;

        outResources.Signals =
        {
            .IndirectSpecular = CreateTex(FSRDFormats::IndirectSpecular, L"FSR_Conv_IndirectSpecular"),
            .DirectDiffuse = CreateTex(FSRDFormats::DirectDiffuse, L"FSR_Conv_DirectDiffuse")
        };

        // Every allocation succeeded, so the new size is now the real state.
        m_maxWidth = width;
        m_maxHeight = height;
    }

    void DispatchFloorSeed(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc) 
    {
        const XMFLOAT2 dispatchSize = { desc.RenderSize.x, desc.RenderSize.y };
        const bool isDepthLinear = (desc.Flags & (uint32_t) ConvFlags::IsDepthLinear);
        ID3D12Resource* inColor = desc.Resources.InColor;

        for (int i = 0; i < FloorSeed::kPasses; i++)
        {
            // The game's subrect origin only applies while the colour source is still
            // the game's texture. From pass 1 on it is the zero-based internal buffer,
            // so carrying the origin forward would shift every read. Depth keeps its
            // own origin because it is re-read from the game texture every pass.
            DirectX::XMUINT4 sourceBase = desc.FloorSourceBase;
            if (i > 0)
            {
                sourceBase.x = 0;
                sourceBase.y = 0;
            }

            FloorSeed::Constants constants =
            {
                .InvProjMatrix = desc.InvProjMatrix,
                .RenderSize = desc.RenderSize,
                .NearPlane = desc.NearPlane,
                .FarPlane = desc.FarPlane,
                .Flags = (isDepthLinear ? uint32_t(FloorSeed::Flags::LinearDepth) : 0u) |
                         ((desc.Flags & uint32_t(ConvFlags::RightHanded))
                              ? uint32_t(FloorSeed::Flags::NegativeViewDepth)
                              : 0u),
                .CurrentJitter = { desc.JitterOffsets.x, desc.JitterOffsets.y },
                .InputBase = sourceBase
            };
            const auto cbData = GetAsByteSpan(constants);

            // Create median filtered raw color before cross bilateral filtering
            // Write to mip chain at top level
            FloorSeed::Input in = { .Resources =  
            {
                .InColor = inColor,
                .InNormals = desc.Resources.InNormals,
                .InDepth = desc.Resources.InDepth
            }};

            FloorSeed::Output out = { .Resources = 
            {
                .OutColor = m_outputBuffer1.Get(),
                .OutLinearDepth = m_LinearDepth.Get(),
                .OutDepthGradient = m_out.Resources.Motion.Get()
            }};

            m_floorSeedShader.Dispatch(cmdList, cbData, in.AsArray, out.AsArray, dispatchSize);

            std::swap(m_outputBuffer1, m_outputBuffer2);
            inColor = m_outputBuffer2.Get();
        }

        m_smoothFloor = m_outputBuffer2.Get();
    }

    void DispatchFloorFilter(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        const XMFLOAT2 dispatchSize = { desc.RenderSize.x, desc.RenderSize.y };

        // Tukey biweight: W = ( 1 - ( (center - tap) * scale )^2 )^2
        // scale = 2^(i + 1) / norm
        float rcpCrossNorm = (1.0f / 0.5f);
        float rcpLumNorm = (1e-2f / 0.3f);

        for (int i = 0; i < FloorFilter::kPasses; i++)
        {
            FloorFilter::Constants constants = 
            {
                .DstTexSize = desc.RenderSize,
                .RcpCrossBlNorm = rcpCrossNorm,
                .RcpSelfBlNorm = rcpLumNorm,
                .StepSize = 1 << i,
                .FrameIndex = m_floorFilterFrameIndex
            };
            const auto cbData = GetAsByteSpan(constants);

            FloorFilter::Input in = { .Resources = 
            {
                .InColor = m_smoothFloor,
                .InLinearDepth = m_LinearDepth.Get(),
                .InDepthGradient = m_out.Resources.Motion.Get()
            }};

            FloorFilter::Output out = { .Resources = 
            {
                // m_smoothFloor always references m_outputBuffer2 at the start of
                // an iteration. Write the opposite buffer, then swap the handles so
                // the freshly filtered result becomes the next iteration's input.
                .OutColor = m_outputBuffer1.Get()
            }};

            m_floorFilterShader.Dispatch(cmdList, cbData, in.AsArray, out.AsArray, dispatchSize);

            std::swap(m_outputBuffer1, m_outputBuffer2);
            m_smoothFloor = m_outputBuffer2.Get();
        }

        m_floorFilterFrameIndex++;
    }

    void DispatchPackingShader(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc) 
    {
        const XMFLOAT2 dispatchSize = { desc.RenderSize.x, desc.RenderSize.y };

        // Prepare inputs for packing and format conversion
        Conversion::Input in = { .Resources =
        {
            .InColor = desc.Resources.InColor,
            .InDepth = m_LinearDepth.Get(),
            .InMotionVectors = desc.Resources.InMotionVectors,
            .InNormals = desc.Resources.InNormals,
            .InRoughness = desc.Resources.InRoughness,
            .InSpecHitDist = desc.Resources.InSpecHitDist,
            .InDiffAlbedo = desc.Resources.InDiffAlbedo,
            .InSpecAlbedo = desc.Resources.InSpecAlbedo,
            .InBiasMask = desc.Resources.InBiasMask,
            .InBlurColor = m_smoothFloor,
            .InEdgeGuide = desc.Resources.InInspector,
            .InEmissive = desc.Resources.InEmissive,
            .InSpecularRayDirectionHitDistance =
                desc.Resources.InSpecularRayDirectionHitDistance,
            .InDiffuseHitDistance = desc.Resources.InDiffuseHitDistance
        }};

        uint32_t packFlags = desc.Flags | uint32_t(ConvFlags::IsDepthLinear);
        if (desc.ZeroRoughHandover)
            packFlags |= uint32_t(ConvFlags::ZeroRoughHandover);
        if (desc.Resources.InSpecularRayDirectionHitDistance &&
            desc.SpecularHitDistanceFromCombinedAlpha)
        {
            packFlags |= uint32_t(ConvFlags::HasCombinedSpecHitDistance);
        }

        Conversion::Constants packConstants =
        {
            .InvViewMatrix = desc.InvViewMatrix,
            .InvProjMatrix = desc.InvProjMatrix,
            .PrevViewMatrix = desc.PrevViewMatrix,
            .RenderSize = desc.RenderSize,
            .MotionInputSize = desc.MotionInputSize,
            .MotionTransform = desc.MotionTransform,
            .JitterOffsets = desc.JitterOffsets,
            .InputBase0 = desc.InputBase0,
            .InputBase1 = desc.InputBase1,
            .InputBase2 = desc.InputBase2,
            .InputBase3 = desc.InputBase3,
            .InputBase4 = desc.InputBase4,
            .InputBase5 = {
                0u, 0u,
                desc.SpecularHitDistanceBase.x, desc.SpecularHitDistanceBase.y
            },
            .NearPlane = desc.NearPlane,
            .FarPlane = desc.FarPlane,
            .FloorIsolation = desc.FloorIsolation,
            .RoughnessFloor = desc.RoughnessFloor,
            // The packing shader never sees the game's hardware depth. FloorSeed
            // has already converted it to signed linear view-space depth.
            .Flags = packFlags,
            .InspectorChannel = desc.InspectorChannel,
            .InspectorScale = desc.InspectorScale,
            .DebugDepthMax = desc.DebugDepthMax,
            // Only honour a mode the caller actually bound a resource for.
            .DiffuseHitDistanceMode = desc.Resources.InDiffuseHitDistance != nullptr
                ? desc.DiffuseHitDistanceMode
                : 0u,
            .ZeroRoughDetail = desc.ZeroRoughDetail,
            .ZeroRoughDetailMode = static_cast<uint32_t>(desc.ZeroRoughDetailMode),
            ._Padding0 = {}
        };

        const std::span<const byte> convCBData((const byte*) &packConstants, sizeof(packConstants));
        m_convShader.Dispatch(cmdList, convCBData, in.AsArray, m_out.AsRawArray, dispatchSize, true);
    }

    void DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc) 
    {
        if (!cmdList || !m_maxWidth)
            return;

        TransitionDenoiserOutputsToRead(cmdList);

        // Filtered raster lighting estimate
        DispatchFloorSeed(cmdList, desc);
        DispatchFloorFilter(cmdList, desc);

        // DLSS-RR to FSR-RR conversion
        DispatchPackingShader(cmdList, desc);

        // Transition output buffers to UAV after last composition pass or first init.
        // The denoiser will be writing to these.
        AddBarrier(cmdList, m_outputBuffer1.Get(), kSrvState, kUavState);
        AddBarrier(cmdList, m_outputBuffer2.Get(), kSrvState, kUavState);
        AddBarrier(cmdList, m_ambientOcclusionOutput.Get(), kSrvState, kUavState);
        AddBarrier(cmdList, m_specularOcclusionOutput.Get(), kSrvState, kUavState);
        m_radianceOutputsInUavState = true;
        m_ambientOcclusionOutputInUavState = true;
        m_specularOcclusionOutputInUavState = true;
    }

    void DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        if (!cmdList || !m_maxWidth)
            return;

        auto& outResources = m_out.Resources;
        Composition::Input inputs = {};
        Composition::Constants constants = 
        {
            .DstTexSize = desc.DstTexSize,
            .SourceBase = desc.SourceBase,
            .CorrelationBias = desc.CorrelationBias,
            .Flags = UINT(desc.Flags),
            .SourceUvScale = { 1.0f, 1.0f },
            .SourceUvOffset = {},
            .ZeroRoughAnchorClamp = desc.ZeroRoughAnchorClamp,
            .ZeroRoughCorrelationMix = desc.ZeroRoughCorrelationMix,
            ._Padding0 = {}
        };

        // Transition denoiser output buffers to SRV for composition.
        TransitionDenoiserOutputsToRead(cmdList);

        inputs.Resources =
        {
            .InIndirectSpecular = m_outputBuffer1.Get(),
            .InSpecularAlbedo = outResources.SpecAlbedo.Get(),
            .InDirectDiffuse = m_outputBuffer2.Get(),
            .InDiffuseAlbedo = outResources.DiffAlbedo.Get(),
            .InSkipSignal = outResources.SkipSignal.Get(),
            .InRawColor = desc.InRawColor,
            .InColorBeforeParticles = desc.InColorBeforeParticles,
            .InRawIndirectSpecular = outResources.Signals.IndirectSpecular.Get(),
            .InNormals = outResources.Normals.Get(),
            .InHandover = outResources.Handover.Get()
        };

        std::array<ID3D12Resource*, 1> uavs { m_out.Resources.Motion.Get() };
        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));
        const XMFLOAT2 dstDim = { constants.DstTexSize.x, constants.DstTexSize.y };

        m_compShader.Dispatch(cmdList, cbData, inputs.AsArray, uavs, dstDim, true);
    }

    void TransitionDenoiserOutputsToRead(ID3D12GraphicsCommandList* cmdList) noexcept
    {
        if (!cmdList)
            return;

        if (m_radianceOutputsInUavState)
        {
            std::array<ID3D12Resource*, 2> buffers = { m_outputBuffer1.Get(), m_outputBuffer2.Get() };
            AddBarriers(cmdList, buffers, kUavState, kSrvState);
            m_radianceOutputsInUavState = false;
        }

        if (m_ambientOcclusionOutputInUavState)
        {
            AddBarrier(cmdList, m_ambientOcclusionOutput.Get(), kUavState, kSrvState);
            m_ambientOcclusionOutputInUavState = false;
        }

        if (m_specularOcclusionOutputInUavState)
        {
            AddBarrier(cmdList, m_specularOcclusionOutput.Get(), kUavState, kSrvState);
            m_specularOcclusionOutputInUavState = false;
        }
    }

    void CopyAmbientOcclusionOutput(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* dstTex,
                                    D3D12_RESOURCE_STATES dstState,
                                    uint32_t logicalWidth, uint32_t logicalHeight)
    {
        if (!cmdList || !dstTex || !m_ambientOcclusionOutputInUavState ||
            logicalWidth == 0 || logicalHeight == 0)
            throw std::runtime_error("Ambient-occlusion output is unavailable for publication");

        const D3D12_RESOURCE_DESC srcDesc = m_ambientOcclusionOutput->GetDesc();
        const D3D12_RESOURCE_DESC dstDesc = dstTex->GetDesc();
        if (srcDesc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            dstDesc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            logicalWidth > srcDesc.Width || logicalHeight > srcDesc.Height ||
            logicalWidth > dstDesc.Width || logicalHeight > dstDesc.Height ||
            dstDesc.DepthOrArraySize != 1 || dstDesc.MipLevels != 1)
        {
            throw std::runtime_error(
                "Ambient-occlusion destination is incompatible with the allocation ceiling");
        }

        AddBarrier(cmdList, m_ambientOcclusionOutput.Get(), kUavState,
                   D3D12_RESOURCE_STATE_COPY_SOURCE);
        if (dstState != D3D12_RESOURCE_STATE_COPY_DEST)
            AddBarrier(cmdList, dstTex, dstState, D3D12_RESOURCE_STATE_COPY_DEST);

        D3D12_TEXTURE_COPY_LOCATION srcLocation {};
        srcLocation.pResource = m_ambientOcclusionOutput.Get();
        srcLocation.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        srcLocation.SubresourceIndex = 0;
        D3D12_TEXTURE_COPY_LOCATION dstLocation {};
        dstLocation.pResource = dstTex;
        dstLocation.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dstLocation.SubresourceIndex = 0;
        const D3D12_BOX sourceBox {
            0, 0, 0, logicalWidth, logicalHeight, 1
        };
        cmdList->CopyTextureRegion(
            &dstLocation, 0, 0, 0, &srcLocation, &sourceBox);

        AddBarrier(cmdList, m_ambientOcclusionOutput.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
                   kSrvState);
        if (dstState != D3D12_RESOURCE_STATE_COPY_DEST)
            AddBarrier(cmdList, dstTex, D3D12_RESOURCE_STATE_COPY_DEST, dstState);

        m_ambientOcclusionOutputInUavState = false;
    }

    ID3D12Resource* PrepareDebugViewOutput(ID3D12GraphicsCommandList* cmdList, UINT width, UINT height)
    {
        if (!cmdList || !m_pDev || width == 0 || height == 0)
            throw std::runtime_error("Invalid AMD RR debug-view output request");

        if (!m_debugViewOutput || m_debugViewWidth != width || m_debugViewHeight != height)
        {
            auto newOutput = CreateTexture2D(m_pDev, width, height, FSRDFormats::DebugView,
                                             L"FSR_RR_DebugView_Output", kUavState);
            // Retire rather than release. The ring matches this preprocessor's
            // frames-in-flight reuse horizon even when DRS reallocates every frame.
            m_retiredDebugViewOutputs[m_retiredDebugViewOutputIndex] =
                std::move(m_debugViewOutput);
            m_retiredDebugViewOutputIndex =
                (m_retiredDebugViewOutputIndex + 1u) % kBackBufferCount;
            m_debugViewOutput = std::move(newOutput);
            m_debugViewWidth = width;
            m_debugViewHeight = height;
            m_debugViewOutputInUavState = true;

            LOG_INFO("[RR_DIAG] created dedicated AMD debug-view output: {}x{}, "
                     "DXGI_FORMAT_R16G16B16A16_FLOAT, UAV", width, height);
        }
        else if (!m_debugViewOutputInUavState)
        {
            AddBarrier(cmdList, m_debugViewOutput.Get(), kSrvState, kUavState);
            m_debugViewOutputInUavState = true;
        }

        return m_debugViewOutput.Get();
    }

    void TransitionDebugViewOutputToRead(ID3D12GraphicsCommandList* cmdList) noexcept
    {
        if (!cmdList || !m_debugViewOutput || !m_debugViewOutputInUavState)
            return;

        AddBarrier(cmdList, m_debugViewOutput.Get(), kUavState, kSrvState);
        m_debugViewOutputInUavState = false;
    }

    void Blit(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* srcTex,
              ID3D12Resource* dstTex, XMFLOAT2 dstDim, XMFLOAT2 logicalSrcDim,
              XMFLOAT2 logicalSrcBase)
    {
        if (!cmdList || !srcTex || !dstTex)
            return;

        const D3D12_RESOURCE_DESC srcDesc = srcTex->GetDesc();
        const XMFLOAT2 physicalSrcDim {
            static_cast<float>(srcDesc.Width), static_cast<float>(srcDesc.Height)
        };
        if (logicalSrcDim.x == 0.0f || logicalSrcDim.y == 0.0f)
            logicalSrcDim = physicalSrcDim;

        if (dstDim.x == 0 || dstDim.y == 0)
        {
            D3D12_RESOURCE_DESC dstDesc = dstTex->GetDesc();
            dstDim.x = (float)dstDesc.Width;
            dstDim.y = (float)dstDesc.Height;
        }

        if (physicalSrcDim.x == 0.0f || physicalSrcDim.y == 0.0f ||
            logicalSrcDim.x <= 0.0f || logicalSrcDim.y <= 0.0f ||
            logicalSrcBase.x < 0.0f || logicalSrcBase.y < 0.0f ||
            logicalSrcBase.x + logicalSrcDim.x > physicalSrcDim.x ||
            logicalSrcBase.y + logicalSrcDim.y > physicalSrcDim.y ||
            dstDim.x <= 0.0f || dstDim.y <= 0.0f)
            return;

        Composition::Input inputs = {};
        inputs.Resources.InIndirectSpecular = srcTex;

        const Composition::Constants constants = 
        {
            .DstTexSize = 
            {
                dstDim.x,           dstDim.y,
                (1.0f / dstDim.x),  (1.0f / dstDim.y)
            },
            .Flags = (UINT)CompFlags::RawSourceBlit | (UINT)CompFlags::ScaleSrc,
            .SourceUvScale = {
                logicalSrcDim.x / physicalSrcDim.x,
                logicalSrcDim.y / physicalSrcDim.y
            },
            .SourceUvOffset = {
                logicalSrcBase.x / physicalSrcDim.x,
                logicalSrcBase.y / physicalSrcDim.y
            }
        };

        std::array<ID3D12Resource*, 1> uavs { dstTex };
        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));

        m_compShader.Dispatch(cmdList, cbData, inputs.AsArray, uavs, dstDim, false);
    }

    void SetDescResources(ffxDispatchDescHeader& signalHeader, ffxDispatchDescDenoiser& dispatchDesc)
    {
        auto& outResources = m_out.Resources;

        dispatchDesc.header = 
        { 
            .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER,
            .pNext = &signalHeader // Link signal desc to main header
        };

        dispatchDesc.linearDepth = ffxApiGetResourceDX12(m_LinearDepth.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
        dispatchDesc.motionVectors = ffxApiGetResourceDX12(outResources.Motion.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
        dispatchDesc.normals = ffxApiGetResourceDX12(
            outResources.Normals.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
        dispatchDesc.specularAlbedo = ffxApiGetResourceDX12(
            outResources.SpecAlbedo.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
        dispatchDesc.diffuseAlbedo = ffxApiGetResourceDX12(
            outResources.DiffAlbedo.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
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
        m_impl->Initialize(GetAsByteSpan(FSRDFloorSeed_cso), GetAsByteSpan(FSRDFloor_cso),
                           GetAsByteSpan(FSRDInputConv_cso),
                           GetAsByteSpan(FSRDOutputComp_cso));
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

bool FSRDPreprocessor_Dx12::SetMaxRenderSize(UINT width, UINT height)
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

bool FSRDPreprocessor_Dx12::DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
{ 
    try
    {
        m_impl->DispatchConversion(cmdList, desc);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD input conversion failed. Details: {}", err.what());
    }

    return false;
}

void FSRDPreprocessor_Dx12::GetSignals(ffxDispatchDescDenoiser& dispatchDesc,
                                       ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
                                       ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular) const
{
    auto& outResources = m_impl->m_out.Resources;
    auto& signalData = outResources.Signals;
    ID3D12Resource* diffuseInput = signalData.DirectDiffuse.Get();
    ID3D12Resource* specularInput = signalData.IndirectSpecular.Get();

    directDiffuse =
    {
        .header =
        {
            .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE,
            .pNext = &indirectSpecular.header
        },
        .signal =
        {
            .input = ffxApiGetResourceDX12(diffuseInput, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
            .output = ffxApiGetResourceDX12(m_impl->m_outputBuffer2.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
            .checkerboardOrigin = 0
        }
    };

    indirectSpecular =
    {
        .header = { .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR },
        .signal =
        {
            .input = ffxApiGetResourceDX12(specularInput, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
            .output = ffxApiGetResourceDX12(m_impl->m_outputBuffer1.Get(), FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
            .checkerboardOrigin = 0
        }
    };

    m_impl->SetDescResources(directDiffuse.header, dispatchDesc);
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

void FSRDPreprocessor_Dx12::TransitionDenoiserOutputsToRead(ID3D12GraphicsCommandList* cmdList) noexcept
{
    m_impl->TransitionDenoiserOutputsToRead(cmdList);
}

bool FSRDPreprocessor_Dx12::CopyAmbientOcclusionOutput(
    ID3D12GraphicsCommandList* cmdList, ID3D12Resource* dstTex,
    D3D12_RESOURCE_STATES dstState, uint32_t logicalWidth, uint32_t logicalHeight)
{
    try
    {
        m_impl->CopyAmbientOcclusionOutput(
            cmdList, dstTex, dstState, logicalWidth, logicalHeight);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD ambient-occlusion publication failed. Details: {}", err.what());
    }

    return false;
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetAmbientOcclusionOutput() const
{
    return m_impl->m_ambientOcclusionOutput.Get();
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetSpecularOcclusionOutput() const
{
    return m_impl->m_specularOcclusionOutput.Get();
}

ID3D12Resource* FSRDPreprocessor_Dx12::PrepareDebugViewOutput(
    ID3D12GraphicsCommandList* cmdList, uint32_t width, uint32_t height)
{
    try
    {
        return m_impl->PrepareDebugViewOutput(cmdList, width, height);
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("Failed to prepare AMD RR debug-view output. Details: {}", err.what());
    }

    return nullptr;
}

void FSRDPreprocessor_Dx12::TransitionDebugViewOutputToRead(
    ID3D12GraphicsCommandList* cmdList) noexcept
{
    m_impl->TransitionDebugViewOutputToRead(cmdList);
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetDebugViewOutput() const
{
    return m_impl->m_debugViewOutput.Get();
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetCompositionOutput() const 
{ 
    return m_impl->m_out.Resources.Motion.Get(); 
}

bool FSRDPreprocessor_Dx12::Blit(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* srcTex,
                                 ID3D12Resource* dstTex, XMFLOAT2 dstDim,
                                 XMFLOAT2 logicalSrcDim, XMFLOAT2 logicalSrcBase) const

{
    try
    {
        m_impl->Blit(cmdList, srcTex, dstTex, dstDim, logicalSrcDim, logicalSrcBase);
        return true;
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("FSRD blit failed. Details: {}", err.what());
    }

    return false;
}
