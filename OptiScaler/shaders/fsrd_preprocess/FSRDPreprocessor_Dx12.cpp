#include "pch.h"
#include "RRTraceFence.h"
#include "FSRDGameTraceSession.h"
#include <json.hpp>
#include "RRTraceAdditiveIO.h"
#include "precompile/RRTraceAdditive_Shader.h"
#include "resource_tracking/ResTrack_dx12.h"
#include "misc/RecordedComputeLease_Dx12.h"
#include "Util.h"
#include <optional>
#include <mutex>
#include "FSRDPreprocessor_Dx12.h"
#include "FSRDSkinInput.h"
#include "FSRDSkinDispatch.h"
#include "FSRDBlitMapping.h"
#include "gpu_time/FSRDStageTimings_Dx12.h"
#include "FSRDShaderUtils.h"
#include "FSRDShaderData.h"
#include "precompile/FSRDInputConv_Shader.h" 
#include "precompile/FSRDInputConvAdditive_Shader.h"
#include "precompile/FSRDSssPrepare_Shader.h"
#include "precompile/FSRDSssBlur_Shader.h"
#include "precompile/FSRDSkinPrefilter_Shader.h"
#include "precompile/FSRDInputConvSkin_Shader.h"
#include "precompile/FSRDInputConvSkinAdditive_Shader.h"
#include "precompile/FSRDInputConvSkinBounds_Shader.h"
#include "precompile/FSRDInputConvSkinBoundsAdditive_Shader.h"
#include "precompile/FSRDSkinBounds_Shader.h"
#include "precompile/FSRDSkinPrefilterTiled_Shader.h"
#include "precompile/FSRDInputConvSkinFused_Shader.h"
#include "precompile/FSRDInputConvSkinFusedAdditive_Shader.h"
#include "precompile/FSRDSssKernel_Shader.h"
#include "precompile/FSRDSssBlurTiled_Shader.h"
#include "precompile/FSRDOutputComp_Shader.h"
#include "precompile/FSRDCompareView_Shader.h"
#include "precompile/FSRDGeometry_Shader.h"
#include "precompile/FSRDFlatDetailClassify_Shader.h"
#include "precompile/FSRDFlatDetailSeed_Shader.h"
#include "precompile/FSRDFlatDetailRefine_Shader.h"
#include "precompile/FSRDFlatDetailBase_Shader.h"
#include "precompile/FSRDFlatDetailApply_Shader.h"
#include "FSRDPostFlickConstants.h"
#include "FSRDColourTrackConstants.h"
#include "precompile/FSRDPostFlickPrepare_Shader.h"
#include "precompile/FSRDPostFlickApply_Shader.h"
#include "precompile/FSRDColourTrackStats_Shader.h"
#include "precompile/FSRDColourTrackTrack_Shader.h"
#include "precompile/FSRDColourTrackApply_Shader.h"
#include "FSRDPostMotionAnchorConstants.h"
#include "precompile/FSRDPostMotionAnchorStatsRecall_Shader.h"
#include "precompile/FSRDPostMotionAnchorGain_Shader.h"
#include "precompile/FSRDPostMotionAnchorApply_Shader.h"
#include "precompile/FSRDFlatTemporal_Shader.h"
#include "precompile/FSRDFlatTemporalLP_Shader.h"
#include "precompile/FSRDFlatTemporalStore_Shader.h"

#include "precompile/FSRDAlbedoTrustEvidence_Shader.h"
#include "precompile/FSRDAlbedoTrustPropagate_Shader.h"
#include "precompile/FSRDAlbedoStabilise_Shader.h"
#include "precompile/FSRDFogStats_Shader.h"
#include "precompile/FSRDFogKappa_Shader.h"
#include "precompile/FSRDFogRank_Shader.h"
#include "precompile/FSRDFogSmooth_Shader.h"
#include "precompile/FSRDFogTarget_Shader.h"
#include "precompile/FSRDFogRoute_Shader.h"
#include "precompile/FSRDRRMotion_Shader.h"
#include "precompile/FSRDRecoveryLobeAccumulate_Shader.h"
#include "precompile/FSRDRecoveryLobeDown_Shader.h"
#include "precompile/FSRDRecoveryLobeBand_Shader.h"

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
#include <cstring>
#include <utility>

#pragma comment(lib, "d3dcompiler.lib")

using Microsoft::WRL::ComPtr;
using namespace DirectX;
using namespace FSRD;

// Keep the portable pipeline selector tied to the actual shader flag contract.
static_assert(uint32_t(FSRDPreprocessor_Dx12::CompFlags::RawSourceBlit) == 1u);
static_assert(uint32_t(FSRDPreprocessor_Dx12::CompFlags::Debug) == (1u << 16));

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


    constexpr DXGI_FORMAT OutputBuffer1 = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT OutputBuffer2 = DXGI_FORMAT_R16G16B16A16_FLOAT;

    constexpr DXGI_FORMAT AmbientOcclusion = DXGI_FORMAT_R8_UNORM;
    constexpr DXGI_FORMAT SpecularOcclusion = DXGI_FORMAT_R8_UNORM;
    constexpr DXGI_FORMAT DebugView = DXGI_FORMAT_R16G16B16A16_FLOAT;

    // Unsupported-albedo recovery: RR direct-specular input/output and the
    // (unsupported, structure) vote sums, which reach several thousand after propagation.
    constexpr DXGI_FORMAT DirectSpecular = DXGI_FORMAT_R16G16B16A16_FLOAT;
    constexpr DXGI_FORMAT AlbedoTrust = DXGI_FORMAT_R32G32_FLOAT;
}

// The conversion shader pre-quantizes its albedo outputs to the storage format's levels,
// because the divisor it demodulates with, the value its residual closure accounts for and
// the texel composition remodulates from all have to be the same number - quantizing after
// the arithmetic is what let an albedo of 0.01 store as 3/255 and return 17.6% more light
// than the residual had budgeted. The pairing is cross-language (s_AlbedoStoreLevels in
// FSRDInputConv.hlsl), so a format that stops being the 8-bit UNORM the shader quantizes for
// fails the build here instead of quietly reintroducing that gap.
static_assert(FSRDFormats::SpecAlbedo == DXGI_FORMAT_R8G8B8A8_UNORM,
              "FSRDInputConv quantizes specular albedo to 8-bit UNORM levels");
static_assert(FSRDFormats::DiffAlbedo == DXGI_FORMAT_R8G8B8A8_UNORM,
              "FSRDInputConv quantizes diffuse albedo to 8-bit UNORM levels");

struct ComputeState
{
    ID3D12Device* m_pDev = nullptr;
    
    ComPtr<ID3D12RootSignature> m_rootSig;
    ComPtr<ID3D12PipelineState> m_pso;
    struct DispatchSlot
    {
        FrameDescriptorHeap heap;
        ComPtr<ID3D12Resource> upload;
        byte* mapped = nullptr;
        ~DispatchSlot() { if (upload && mapped) upload->Unmap(0, nullptr); }
    };
    struct DispatchLease
    {
        std::shared_ptr<DispatchSlot> slot;
        ComPtr<ID3D12Device> device;
        ComPtr<ID3D12RootSignature> root;
        ComPtr<ID3D12PipelineState> pipeline;
        std::vector<ComPtr<ID3D12Resource>> resources;
        ComPtr<ID3D12CommandSignature> indirectSignature;
    };
    ComPtr<ID3D12Device> m_device;
    std::mutex m_poolMutex;
    std::vector<std::shared_ptr<DispatchSlot>> m_slots;
    UINT m_cbSlotSize = 0;
    UINT m_numSrvs = 0, m_numUavs = 0;
    std::wstring m_cbName;

    std::shared_ptr<DispatchSlot> AcquireSlot()
    {
        {
            std::lock_guard lock(m_poolMutex);
            for (const auto& slot : m_slots)
                if (slot.use_count() == 1) return slot;
        }
        // No pool/registry lock across resource allocation, mapping or heap creation.
        auto slot = std::make_shared<DispatchSlot>();
        D3D12_HEAP_PROPERTIES heapProps = { D3D12_HEAP_TYPE_UPLOAD };
        D3D12_RESOURCE_DESC bufferDesc = {};
        bufferDesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        bufferDesc.Width = m_cbSlotSize;
        bufferDesc.Height = 1;
        bufferDesc.DepthOrArraySize = 1;
        bufferDesc.MipLevels = 1;
        bufferDesc.SampleDesc.Count = 1;
        bufferDesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ThrowIfFailed(m_pDev->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE, &bufferDesc,
            D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&slot->upload)), "Failed to create dispatch constants");
        slot->upload->SetName(m_cbName.c_str());
        D3D12_RANGE readRange = { 0, 0 };
        ThrowIfFailed(slot->upload->Map(0, &readRange, reinterpret_cast<void**>(&slot->mapped)), "Failed to map dispatch constants");
        if (!slot->heap.Initialize(m_pDev, m_numSrvs, m_numUavs, 0, 0))
            throw std::runtime_error("Failed to create dispatch descriptor heap");
        {
            std::lock_guard lock(m_poolMutex);
            m_slots.push_back(slot);
        }
        return slot;
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
        m_device = pDev;
        m_slots.reserve(backBufferCount); // reservation is not a GPU-completion bound
        m_numSrvs = numSrvs;
        m_numUavs = numUavs;
        m_cbName = cbName;

        // Create Root Signature
        ThrowIfFailed(m_pDev->CreateRootSignature(0, bytecode.data(), bytecode.size(), IID_PPV_ARGS(&m_rootSig)),
              "Failed to create Root Signature");

        // Create PSO
        D3D12_COMPUTE_PIPELINE_STATE_DESC psoDesc = {};
        psoDesc.pRootSignature = m_rootSig.Get();
        psoDesc.CS = { bytecode.data(), bytecode.size() };
        ThrowIfFailed(m_pDev->CreateComputePipelineState(&psoDesc, IID_PPV_ARGS(&m_pso)), "Failed to create PSO");

        m_cbSlotSize = AlignTo256(cbDataSize);
    }

    void Dispatch(
        ID3D12GraphicsCommandList* cmdList,
        std::span<const byte> cbData,
        std::span<ID3D12Resource* const> inputs,
        std::span<const MipChainDesc> inputMips,
        std::span<ID3D12Resource*> output,
        std::span<const UINT> outputMips,
        XMFLOAT2 outDim,
        bool autoBarrierOutput = true,
        ID3D12PipelineState* pipelineState = nullptr,
        ID3D12CommandSignature* indirectSignature = nullptr,
        ID3D12Resource* indirectArguments = nullptr
    )
    {
        if (!cmdList) 
            return;

        ScopedSkipHeapCapture skipHeapCapture {};

        if (cbData.size() > m_cbSlotSize)
            throw std::runtime_error("Oversized dispatch constants");
        auto lease = std::make_shared<DispatchLease>();
        lease->slot = AcquireSlot();
        lease->device = m_device;
        lease->root = m_rootSig;
        lease->pipeline = pipelineState ? pipelineState : m_pso.Get();
        lease->indirectSignature = indirectSignature;
        if (indirectArguments) lease->resources.emplace_back(indirectArguments);
        for (auto* resource : inputs) if (resource) lease->resources.emplace_back(resource);
        for (auto* resource : output) if (resource) lease->resources.emplace_back(resource);
        if (!ResTrack_Dx12::RetainComputeDispatch(m_pDev, cmdList, lease))
            throw std::runtime_error("Compute dispatch lifetime tracking unavailable");
        memcpy(lease->slot->mapped, cbData.data(), cbData.size());
        D3D12_GPU_VIRTUAL_ADDRESS cbAddress = lease->slot->upload->GetGPUVirtualAddress();

        // Transitions SRV -> UAV
        if (autoBarrierOutput)
            AddBarriers(cmdList, output, outputMips, kSrvState, kUavState);

        // Update descriptors
        FrameDescriptorHeap& currentHeap = lease->slot->heap;
        CreateSRVs(m_pDev, currentHeap, inputs, inputMips);
        CreateUAVs(m_pDev, currentHeap, output, outputMips);

        // Configure pipeline
        cmdList->SetPipelineState(pipelineState ? pipelineState : m_pso.Get());
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
        if (indirectSignature && indirectArguments)
            cmdList->ExecuteIndirect(indirectSignature, 1, indirectArguments, 0, nullptr, 0);
        else
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
        bool autoBarrierOutput = true,
        ID3D12PipelineState* pipelineState = nullptr,
        ID3D12CommandSignature* indirectSignature = nullptr,
        ID3D12Resource* indirectArguments = nullptr
    )
    {
        Dispatch(cmdList, cbData, inputs, {}, output, {}, outDim, autoBarrierOutput, pipelineState, indirectSignature, indirectArguments);
    }
};


#include "FSRDResearchTools.inl"

namespace {
std::mutex g_additiveTraceMutex;
std::optional<std::array<UINT,3>> g_additiveTraceRequest;
bool g_additiveTraceBusy=false;
std::string g_additiveTraceStatus="No additive channel capture requested.";
constexpr const char* kAdditiveFieldNames[] = {"rejected","evaluated","eligible","preflight_count","fit_count","mean_albedo","variance_albedo","min_specular","max_specular","mean_specular","mean_residual","variance_residual","covariance","ridge_lambda","data_weight","prior_slope","unregularized_slope","ridge_slope","intercept_unclamped","intercept","intercept_error","fit_rmse","applied_slope","applied_intercept","center_prediction","center_prediction_error","p0","p","delta_p","transferred_rgb","eligible_rgb","skip_rgb","skip_fraction","remodulated_fraction","raw_rgb","reserved_rgb","eligible_fraction","specular_signal","diffuse_signal","settings","source_diffuse","source_specular","source_normal","source_roughness","linear_depth","source_motion","stored_specular","stored_diffuse"};
}
bool FSRDPreprocessor_Dx12::RequestAdditiveCapture(uint32_t x,uint32_t y,uint32_t size)
{
    std::scoped_lock lock(g_additiveTraceMutex);
    if (g_additiveTraceBusy || g_additiveTraceRequest || size<16 || size>128) return false;
    g_additiveTraceRequest=std::array<UINT,3>{x,y,size};
    g_additiveTraceStatus="Additive capture requested; waiting for FSR-RR conversion.";
    return true;
}
std::string FSRDPreprocessor_Dx12::GetAdditiveCaptureStatus()
{
    std::scoped_lock lock(g_additiveTraceMutex);
    return g_additiveTraceStatus;
}

// Private implementation
struct FSRDPreprocessor_Dx12::Impl
{
    ID3D12Device* m_pDev = nullptr;
#include "RRTraceAdditive.inl"
    ~Impl()
    {
        m_gameTrace.Abort("Preprocessor owner ended before capture completion.");
        ReleaseInputProbe();
        if (m_additiveCapture)
        {
            std::scoped_lock lock(g_additiveTraceMutex);
            g_additiveTraceBusy=false;
            g_additiveTraceStatus="Additive capture owner ended; unfinished capture not exported.";
        }
    }

    FSRDGameTraceSession m_gameTrace;
    FSRDResearch::Session m_research;
    ComputeState m_leakShader;
    ComPtr<ID3D12Resource> m_leakView;
    // Albedo guide stabilisation: ping-pong history (stabilised guides, view Z, normal) and spare packing
    // outputs that are swapped with the packed ones after the pass.
    ComputeState m_albedoStabShader;
    std::array<ComPtr<ID3D12Resource>, 2> m_albedoStabSpec, m_albedoStabDiff, m_albedoStabNormal;
    ComPtr<ID3D12Resource> m_albedoStabSpareSpecAlbedo, m_albedoStabSpareDiffAlbedo;
    ComPtr<ID3D12Resource> m_albedoStabSpareSpecSignal, m_albedoStabSpareDiffSignal;
    uint32_t m_albedoStabIndex = 0, m_albedoStabMode = 0;
    bool m_albedoStabValid = false;
    // True when this frame's packed pair was replaced; the packing shader's own pair is then in the spares.
    bool m_albedoStabActive = false;
    // RR's motion vectors with the jitter difference (FSRDRRMotion.hlsl); m_out keeps the canonical field.
    ComputeState m_rrMotionShader;
    ComPtr<ID3D12Resource> m_rrMotion;
    bool m_rrMotionActive = false;
    XMFLOAT4 m_albedoStabSize {};

    // Fog-consistent guides (FSRDFog*.hlsl): tile statistics history (A, B, C), per-frame tile guide means (G, H),
    // kappa before and after smoothing, and spares for the rewritten pair.
    ComputeState m_fogStatsShader, m_fogKappaShader, m_fogRankShader, m_fogSmoothShader, m_fogTargetShader,
        m_fogRouteShader;
    std::array<ComPtr<ID3D12Resource>, 2> m_fogA, m_fogB, m_fogC, m_fogGuides;
    ComPtr<ID3D12Resource> m_fogG, m_fogH, m_fogKappaRaw, m_fogKappaRank, m_fogKappa, m_fogTargetSpec, m_fogTargetDiff;
    ComPtr<ID3D12Resource> m_fogSpareSpecAlbedo, m_fogSpareDiffAlbedo, m_fogSpareSpecSignal, m_fogSpareDiffSignal;
    uint32_t m_fogIndex = 0;
    bool m_fogValid = false;
    XMFLOAT4 m_fogSize {};
    std::array<uint8_t,sizeof(Geometry::Constants)> m_gameTraceGeometryConstants {};
    bool m_gameTraceFrameRecorded = false;
    bool m_gameTraceCaptureRequested = false;

    ComputeState m_geometryShader;
    ComputeState m_flatDetailClassifyShader, m_flatDetailSeedShader, m_flatDetailRefineShader;
    // Post-flick blotch fix (task 24 T2 c), default off: half-resolution keyframe/band/age textures plus the two
    // passes that recall the last settled frame band on pixels whose history is young. Created on first use only.
    ComputeState m_postFlickPrepareShader, m_postFlickApplyShader;
    std::array<ComPtr<ID3D12Resource>, 2> m_postFlickKey, m_postFlickKeyAux, m_postFlickAux;
    ComPtr<ID3D12Resource> m_postFlickCur, m_postFlickOutput;
    uint32_t m_postFlickParity = 0, m_postFlickWidth = 0, m_postFlickHeight = 0;
    bool m_postFlickValid = false, m_postFlickActive = false, m_postFlickWasEnabled = false;
    PostFlickMath::KeyState m_postFlickKeyState {};
    // Post-RR colour tracking (task 25 T2), default off: RR's input colour in output units (written by the
    // composition pass), the quarter-res statistics of the composite and of that input colour, the reprojected
    // EMA target ping-pong, the gain field and the in-place apply. Created on first use only.
    ComputeState m_colourTrackStatsShader, m_colourTrackTrackShader, m_colourTrackApplyShader;
    ComPtr<ID3D12Resource> m_colourTrackInput;   // full resolution, RR's input colour in output units
    ComPtr<ID3D12Resource> m_colourTrackStats, m_colourTrackTarget, m_colourTrackMotion, m_colourTrackGain;
    std::array<ComPtr<ID3D12Resource>, 2> m_colourTrackHistory;
    uint32_t m_colourTrackHistoryIndex = 0;
    uint32_t m_colourTrackWidth = 0, m_colourTrackHeight = 0;
    // Post-motion level anchor (task 25 T3 ii), default off: a luminance-only gain on RR's input during the
    // post-motion window, measured against a ring of settled keyframes of the input's own level. The memory is the
    // input BEFORE the gain, so the anchor's own corrections cannot pollute the reference. Two 1/8-resolution
    // passes (statistics + recall, then the gain field) and a full-resolution in-place apply on the two signals.
    ComputeState m_postMotionStatsRecallShader, m_postMotionGainShader, m_postMotionApplyShader;
    ComPtr<ID3D12Resource> m_postMotionKeyLevel, m_postMotionKeyDepth; // 8-slice ring, 1/8 resolution
    ComPtr<ID3D12Resource> m_postMotionStats, m_postMotionRecalled, m_postMotionGain;
    // 16 bytes of frame-level fixed-point sums (num, den, count, spare): the statistics pass accumulates them with
    // atomics and the gain pass consumes and clears them, which is what makes the reject guard frame-level (the
    // measured prototype) instead of per-cell (measured: not equivalent on 2405).
    ComPtr<ID3D12Resource> m_postMotionSums;
    // A persistent 16-byte zero buffer: the sums are cleared by a copy before the statistics pass, so the gain
    // pass only ever reads them (a reset inside that dispatch would race its own reads - the audit's M1).
    ComPtr<ID3D12Resource> m_postMotionSumsReset;
    D3D12_RESOURCE_STATES m_postMotionSumsState = D3D12_RESOURCE_STATE_COMMON;
    PostMotionAnchorMath::State m_postMotionState {};
    uint32_t m_postMotionWidth = 0, m_postMotionHeight = 0;
    bool m_postMotionWasEnabled = false, m_postMotionActive = false;
    bool m_colourTrackValid = false, m_colourTrackWasEnabled = false;
    // True on the frame whose composite the tracking passes have corrected in place; the composition clears it.
    bool m_colourTrackActive = false;
    ComputeState m_flatDetailBaseShader, m_flatDetailApplyShader;
    ComPtr<ID3D12CommandSignature> m_flatDetailSignature;
    ComPtr<ID3D12Resource> m_flatDetailTiles, m_flatDetailArguments, m_flatDetailReset;
    std::array<ComPtr<ID3D12Resource>, 2> m_flatDetailReference, m_flatDetailStatistics;
    ComPtr<ID3D12Resource> m_flatDetailBase, m_flatDetailMean, m_flatDetailVariance;
    FlatDetail::Constants m_flatDetailConstants {};
    bool m_flatDetailActive = false;
    ComputeState m_flatTemporalShader, m_flatTemporalStoreShader, m_flatTemporalLPShader;
    // Six-slice arrays hold ORIGINAL references (RGBA16F log + depth) and their validation metadata
    // (R32G32_UINT aux); low-pass lumas use a 4x4 block grid ring. 16.25 bytes per pixel and slice.
    ComPtr<ID3D12Resource> m_flatHistoryReference, m_flatHistoryAux, m_flatHistoryLP;
    ComPtr<ID3D12Resource> m_flatTemporalLP, m_flatTemporalDiagnostics;
    FlatTemporal::Constants m_flatTemporalConstants {};
    UINT m_flatHistoryHead = 0, m_flatHistoryCount = 0, m_flatHistoryLength = 0;
    XMFLOAT4 m_flatHistorySize {};
    bool m_flatTemporalActive = false, m_flatTemporalWasEnabled = false;
    ComputeState m_convShader;
    ComputeState m_skinConvShader;
    ComputeState m_sssPrepareShader;
    ComputeState m_sssBlurShader;
    ComputeState m_skinPrefilterShader;
    ComputeState m_skinBoundsConvShader, m_skinBoundsShader, m_skinTiledPrefilterShader;
    ComPtr<ID3D12PipelineState> m_skinAdditivePso, m_skinBoundsAdditivePso;
    ComPtr<ID3D12Resource> m_skinBounds8, m_skinBounds16;
    ComputeState m_skinFusedConvShader, m_sssKernelShader, m_sssTiledBlurShader;
    ComPtr<ID3D12PipelineState> m_skinFusedAdditivePso;
    ComPtr<ID3D12Resource> m_sssKernel;
    bool m_skinFused = false;
    ComPtr<ID3D12Resource> m_skinPrepared, m_skinGuide, m_skinBlur, m_skinResult, m_skinDiffuse;
    uint32_t m_skinMode = 0;
    uint32_t m_skinDebug = 0;
    float m_skinRadiusMm = 2.18f, m_skinStrength = 0.56f, m_skinFalloff = 1.0f, m_skinSigma = 4.0f;
    float m_skinFocalPixels = 0.0f;
    bool m_skinOutputActive = false;
    ComputeState m_compShader;
    ComputeState m_trustEvidenceShader;
    ComputeState m_trustPropagateShader;
    // Shares conversion's root signature, per-dispatch descriptors and constants.
    // The original PSO remains usable if optional pipeline creation fails.
    ComPtr<ID3D12PipelineState> m_additiveConvPso;
    bool m_additiveConvPsoFailed = false;
    // Every post-composition pass reads the last result and writes a distinct SRV-resting target.
    ComPtr<ID3D12Resource> m_recoveryOutput[2];
    int m_recoveryOutputIndex = -1;
    // Temporal recovery references survive only consecutive successful normal frames.
    bool m_recoveryHistoryValid = false;
    // Recovery v2 lobe recovery: per-lobe references and geometry (ping-pong), the band pyramid (levels 0-6),
    // collapsed coarse corrections (levels 1-5), per-level band noise (ping-pong) and unused-slot dummies.
    ComputeState m_lobeAccumulateShader, m_lobeDownShader, m_lobeBandShader;
    std::array<ComPtr<ID3D12Resource>, 2> m_lobeSpecular, m_lobeDiffuse, m_lobeGeometry, m_lobeGradient;
    std::array<ComPtr<ID3D12Resource>, RecoveryLobe::kLevels + 1> m_lobeLevelA, m_lobeLevelB, m_lobeLevelC;
    std::array<ComPtr<ID3D12Resource>, RecoveryLobe::kLevels> m_lobeCorrectionS, m_lobeCorrectionD;
    std::array<std::array<ComPtr<ID3D12Resource>, RecoveryLobe::kLevels>, 2> m_lobeNoise;
    std::array<ComPtr<ID3D12Resource>, 4> m_lobeDummy;
    UINT m_lobeIndex = 0;
    uint32_t m_lobeFrame = 0;
    bool m_lobeValid = false;
    XMFLOAT4 m_lobeSize {};

    UINT m_maxWidth = 0;
    UINT m_maxHeight = 0;

    // Output Targets
    // Internal storage
    Conversion::Output m_out;
    ComPtr<ID3D12Resource> m_LinearDepth;
    // Last frame's m_LinearDepth for the geometric disocclusion check, copied before geometry
    // seed overwrites it. m_linearDepthSize is the render size of the complete frame
    // m_LinearDepth holds; zero until the geometry pass has written one.
    ComPtr<ID3D12Resource> m_PrevLinearDepth;
    XMFLOAT4 m_linearDepthSize {};
    bool m_previousDepthValid = false;
    ComPtr<ID3D12Resource> m_compositionOutput;
    // Compare (split) view. Snapshots are render-sized (pre-SR); present/frozen are
    // output-sized and display-only. All are allocated lazily while the view is active.
    ComputeState m_compareShader;
    ComPtr<ID3D12Resource> m_compareSnapshotA, m_compareSnapshotB;
    ComPtr<ID3D12Resource> m_comparePresent, m_compareFrozen;
    bool m_compareFrozenValid = false, m_compareSnapshotsReady = false;
    uint32_t m_compareView = 0;
    UINT m_comparePresentWidth = 0, m_comparePresentHeight = 0;
    bool m_motionHistoryValid = false;
    XMFLOAT2 m_currentJitter {};
    XMFLOAT2 m_flatHistoryJitterDelta {};
    ComPtr<ID3D12Resource> m_outputBuffer1;
    ComPtr<ID3D12Resource> m_outputBuffer2;
    // RR direct-specular output (denoised unmodulated specular) and the trust ping-pong.
    FSRDStageTimings* m_stageTimings = nullptr;
    FSRDRuntimeSnapshot* m_runtime = nullptr;
    bool m_extraDiffuse = false, m_extraSpecular = false, m_albedoRecovery = false;
    ComPtr<ID3D12Resource> m_directSpecularOutput;
    ComPtr<ID3D12Resource> m_indirectDiffuseOutput;
    std::array<ComPtr<ID3D12Resource>, 2> m_albedoTrust;
    UINT m_albedoTrustResult = 0;

    ComPtr<ID3D12Resource> m_ambientOcclusionOutput;
    ComPtr<ID3D12Resource> m_specularOcclusionOutput;
    ComPtr<ID3D12Resource> m_debugViewOutput;
    UINT m_debugViewWidth = 0;
    UINT m_debugViewHeight = 0;


    // The RR-facing linear depth for this frame, and the state it was validated in. When
    // a title-published linear depth is being consumed it is that resource - every
    // reconstructed position and the denoiser's own depth input must be the same field.
    ID3D12Resource* m_rrLinearDepth = nullptr;
    uint32_t m_rrLinearDepthState = 0;
    uint32_t m_rrLinearDepthDeclaredState = 0;
    bool m_rrLinearDepthForwarded = false;

    bool m_radianceOutputsInUavState = false;
    bool m_ambientOcclusionOutputInUavState = false;
    bool m_specularOcclusionOutputInUavState = false;
    bool m_debugViewOutputInUavState = false;

    // Diagnostic readback of the three RR-facing g-buffer textures. Presence and
    // the debug views cannot answer whether their *values* are usable: every depth
    // debug view normalises with abs() and a turbo ramp, so a collapsed or
    // mirrored depth field renders as a believable image. Recording happens in
    // DispatchConversion, immediately after the packing dispatch - see
    // RecordInputProbe for why that instant is the only safe one.
    static constexpr UINT kInputProbeTargetCount = 7;
    static constexpr UINT kInputProbeInterval = 60; // conversions between recordings
    ComPtr<ID3D12Resource> m_inputProbeReadback[kInputProbeTargetCount];
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT m_inputProbeFootprint[kInputProbeTargetCount] = {};
    UINT m_inputProbeRowPitch[kInputProbeTargetCount] = {};
    XMFLOAT4 m_inputProbeMotionTransform = {};
    UINT m_inputProbeWidth = 0;
    UINT m_inputProbeHeight = 0;
    UINT m_inputProbeCountdown = 1; // record on the first conversion, then every interval
    // A CPU frame delay or a value copied into a readback heap is not a GPU fence.
    // The ticket also waits for Reset, so a still-executable list cannot overwrite
    // these buffers while the CPU reads them or after the next capture reuses them.
    std::shared_ptr<RRTraceFence::Ticket> m_inputProbeTicket;

    void ReleaseInputProbe()
    {
        if (!m_inputProbeTicket) return;
        m_inputProbeTicket->Abandon();
        RRTraceFence::Forget(m_inputProbeTicket);
        m_inputProbeTicket.reset();
        // An invalid/resubmitted recording may still use the old buffers. Its
        // abandoned ticket retains them; the next capture gets a fresh allocation.
        for (auto& buffer : m_inputProbeReadback) buffer.Reset();
    }

    void UpdateInputProbe(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        if (m_inputProbeTicket)
        {
            if (m_inputProbeTicket->Invalid())
                ReleaseInputProbe();
            else if (m_inputProbeTicket->Ready() && (!desc.DiagnosticsEnabled || LogInputProbe()))
            {
                // Completed, detached buffers can be reused without reallocating.
                RRTraceFence::Forget(m_inputProbeTicket);
                m_inputProbeTicket.reset();
            }
        }

        // Poll outstanding captures even after diagnostics are disabled.
        if (!desc.DiagnosticsEnabled || m_inputProbeTicket)
            return;

        if (m_inputProbeCountdown > 0 && --m_inputProbeCountdown > 0)
            return;

        m_inputProbeWidth = static_cast<UINT>(desc.RenderSize.x);
        m_inputProbeHeight = static_cast<UINT>(desc.RenderSize.y);
        m_inputProbeMotionTransform = desc.MotionTransform;
        // Also back off after an allocation/hook failure; diagnostics must not
        // retry an expensive failing allocation on every rendered frame.
        m_inputProbeCountdown = kInputProbeInterval;
        RecordInputProbe(cmdList);
    }

    // Copies linear depth, motion vectors and normals into readback buffers.
    //
    // Called from DispatchConversion right after DispatchPackingShader, whose
    // autoBarrierOutput has just returned every output to kSrvState - a state this
    // code owns and can therefore barrier away from. The same three resources must
    // NOT be probed after the denoiser dispatch: the FFX backend records its own
    // barriers over them, and transitioning from an assumed state there removed
    // the device (GPUCrashReport 0xCCCF0D).
    bool RecordInputProbe(ID3D12GraphicsCommandList* cmdList)
    {
        if (m_pDev == nullptr || cmdList == nullptr || !ResTrack_Dx12::EnsureRRTraceHooks(m_pDev))
            return false;

        ID3D12Resource* sources[kInputProbeTargetCount] = {
            m_LinearDepth.Get(),
            m_out.Resources.Motion.Get(),
            m_out.Resources.Normals.Get(),
            m_out.Resources.Signals.IndirectSpecular.Get(),
            m_out.Resources.SpecAlbedo.Get(),
            m_out.Resources.SkipSignal.Get(),
            m_out.Resources.DiffAlbedo.Get()
        };

        for (UINT i = 0; i < kInputProbeTargetCount; i++)
        {
            if (sources[i] == nullptr)
                return false;
        }

        UINT64 maxBufferBytes = 0;
        for (UINT i = 0; i < kInputProbeTargetCount; i++)
        {
            const D3D12_RESOURCE_DESC srcDesc = sources[i]->GetDesc();
            UINT64 rowBytes = 0;
            UINT64 bufferBytes = 0;
            m_pDev->GetCopyableFootprints(
                &srcDesc, 0, 1, 0, &m_inputProbeFootprint[i], nullptr, &rowBytes, &bufferBytes);
            if (bufferBytes == 0)
                return false;

            m_inputProbeRowPitch[i] = m_inputProbeFootprint[i].Footprint.RowPitch;
            maxBufferBytes = std::max(maxBufferBytes, bufferBytes);
        }

        // Every buffer has to be present and large enough, not just the first one: the copy loop
        // below indexes the whole set, so the invariant it depends on is about the whole set.
        // Testing element 0 alone is what let a resize that failed part way through be read as
        // complete - the element that had already been replaced was the right size, the test
        // passed, and the next attempt copied into a null or undersized buffer.
        bool needsReadbackBuffers = false;
        for (UINT i = 0; i < kInputProbeTargetCount; i++)
        {
            if (m_inputProbeReadback[i] == nullptr ||
                m_inputProbeReadback[i]->GetDesc().Width < maxBufferBytes)
            {
                needsReadbackBuffers = true;
                break;
            }
        }

        if (needsReadbackBuffers)
        {
            D3D12_HEAP_PROPERTIES heapProps = {};
            heapProps.Type = D3D12_HEAP_TYPE_READBACK;

            D3D12_RESOURCE_DESC bufDesc = {};
            bufDesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
            bufDesc.Width = maxBufferBytes;
            bufDesc.Height = 1;
            bufDesc.DepthOrArraySize = 1;
            bufDesc.MipLevels = 1;
            bufDesc.SampleDesc = { 1, 0 };
            bufDesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;

            // Build the whole set before any of it is committed, so the array is never observed
            // holding a mixture of new, null and stale buffers. A partial commit is exactly the
            // state the sizing test above can no longer see, and the copies below cannot
            // survive it. The set being replaced also stays alive until replacements exist.
            std::array<ComPtr<ID3D12Resource>, kInputProbeTargetCount> allocated;
            for (UINT i = 0; i < kInputProbeTargetCount; i++)
            {
                if (FAILED(m_pDev->CreateCommittedResource(
                        &heapProps, D3D12_HEAP_FLAG_NONE, &bufDesc,
                        D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                        IID_PPV_ARGS(&allocated[i]))))
                {
                    LOG_ERROR("[RR_INPUT_PROBE] readback buffer creation failed");
                    return false;
                }
            }

            for (UINT i = 0; i < kInputProbeTargetCount; i++)
                m_inputProbeReadback[i] = std::move(allocated[i]);
        }

        // Arm and retain everything before recording the first copy or barrier.
        // Failure is diagnostic-only and must not abort the rendering chain.
        try
        {
            m_inputProbeTicket = RRTraceFence::Arm(m_pDev, cmdList);
            for (UINT i = 0; i < kInputProbeTargetCount; ++i)
            {
                m_inputProbeTicket->Retain(sources[i]);
                m_inputProbeTicket->Retain(m_inputProbeReadback[i].Get());
            }
        }
        catch (const std::exception& error)
        {
            if (m_inputProbeTicket) m_inputProbeTicket->CancelUnrecorded();
            ReleaseInputProbe();
            LOG_ERROR("[RR_INPUT_PROBE] capture lifetime setup failed: {}", error.what());
            return false;
        }

        D3D12_RESOURCE_BARRIER toCopy[kInputProbeTargetCount] = {};
        D3D12_RESOURCE_BARRIER toSrv[kInputProbeTargetCount] = {};
        for (UINT i = 0; i < kInputProbeTargetCount; i++)
        {
            toCopy[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            toCopy[i].Transition.pResource = sources[i];
            toCopy[i].Transition.StateBefore = kSrvState;
            toCopy[i].Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
            toCopy[i].Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;

            toSrv[i].Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            toSrv[i].Transition.pResource = sources[i];
            toSrv[i].Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
            toSrv[i].Transition.StateAfter = kSrvState;
            toSrv[i].Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        }

        cmdList->ResourceBarrier(kInputProbeTargetCount, toCopy);
        for (UINT i = 0; i < kInputProbeTargetCount; i++)
        {
            D3D12_TEXTURE_COPY_LOCATION dst = {};
            dst.pResource = m_inputProbeReadback[i].Get();
            dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            dst.PlacedFootprint = m_inputProbeFootprint[i];

            D3D12_TEXTURE_COPY_LOCATION src = {};
            src.pResource = sources[i];
            src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            src.SubresourceIndex = 0;

            cmdList->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        }
        cmdList->ResourceBarrier(kInputProbeTargetCount, toSrv);

        m_inputProbeTicket->Recorded();

        return true;
    }

    // IEEE 754 half -> float for the readbacks (this translation unit has no
    // DirectXPackedVector, and the probe must not depend on one).
    static float ProbeHalfToFloat(uint16_t h)
    {
        const uint32_t sign = (h >> 15) & 1u;
        uint32_t exponent = (h >> 10) & 0x1Fu;
        uint32_t mantissa = h & 0x3FFu;

        uint32_t bits = 0;
        if (exponent == 0u)
        {
            if (mantissa != 0u)
            {
                exponent = 1u;
                while ((mantissa & 0x400u) == 0u)
                {
                    mantissa <<= 1;
                    exponent--;
                }
                mantissa &= 0x3FFu;
                bits = (sign << 31) | ((exponent - 15u + 127u) << 23) | (mantissa << 13);
            }
            else
                bits = sign << 31;
        }
        else if (exponent == 0x1Fu)
            bits = (sign << 31) | 0x7F800000u | (mantissa << 13);
        else
            bits = (sign << 31) | ((exponent - 15u + 127u) << 23) | (mantissa << 13);

        float result = 0.0f;
        std::memcpy(&result, &bits, sizeof(result));
        return result;
    }

    static float PercentileOf(std::vector<float>& sorted, float fraction)
    {
        if (sorted.empty())
            return 0.0f;

        const size_t index = static_cast<size_t>(fraction * float(sorted.size() - 1));
        return sorted[index];
    }

    struct ProbeSampling
    {
        UINT strideX = 1;
        UINT strideY = 1;
        UINT samples = 0;
    };

    static ProbeSampling GetProbeSampling(UINT width, UINT height)
    {
        ProbeSampling sampling;
        sampling.strideX = std::max(width / 128u, 1u);
        sampling.strideY = std::max(height / 72u, 1u);
        sampling.samples =
            ((width + sampling.strideX - 1) / sampling.strideX) *
            ((height + sampling.strideY - 1) / sampling.strideY);
        return sampling;
    }

    // Reports the RR-facing view depth. The question this answers is scale, not
    // sign: a world reconstructed at a fraction of a metre and one at hundreds of
    // metres are the same picture in every normalised debug view, but only the
    // second can drive RR's reprojection.
    void LogLinearDepthProbe(const uint8_t* data, UINT rowPitch, const ProbeSampling& sampling)
    {
        const UINT sampleWidth = std::min(m_inputProbeWidth, m_maxWidth);
        const UINT sampleHeight = std::min(m_inputProbeHeight, m_maxHeight);

        std::vector<float> magnitudes;
        magnitudes.reserve(sampling.samples);

        float minValue = 0.0f;
        float maxValue = 0.0f;
        bool first = true;
        UINT negatives = 0;
        UINT zeros = 0;
        UINT nonFinite = 0;
        double sum = 0.0;
        UINT buckets[6] = {}; // |v| < 0.1, < 1, < 10, < 100, < 1000, >= 1000

        for (UINT y = sampling.strideY / 2; y < sampleHeight; y += sampling.strideY)
        {
            const float* row = reinterpret_cast<const float*>(data + size_t(y) * rowPitch);
            for (UINT x = sampling.strideX / 2; x < sampleWidth; x += sampling.strideX)
            {
                const float value = row[x];
                if (!std::isfinite(value))
                {
                    ++nonFinite;
                    continue;
                }

                const float magnitude = std::abs(value);
                magnitudes.push_back(magnitude);
                sum += double(magnitude);

                if (value < 0.0f)
                    ++negatives;
                if (value == 0.0f)
                    ++zeros;

                if (first)
                {
                    minValue = value;
                    maxValue = value;
                    first = false;
                }
                else
                {
                    minValue = std::min(minValue, value);
                    maxValue = std::max(maxValue, value);
                }

                const UINT bucket = magnitude < 0.1f ? 0u
                    : magnitude < 1.0f ? 1u
                    : magnitude < 10.0f ? 2u
                    : magnitude < 100.0f ? 3u
                    : magnitude < 1000.0f ? 4u : 5u;
                ++buckets[bucket];
            }
        }

        if (magnitudes.empty())
        {
            LOG_WARN("[RR_INPUT_PROBE] linearDepth: no finite samples");
            return;
        }

        std::sort(magnitudes.begin(), magnitudes.end());
        const float rcpCount = 100.0f / float(magnitudes.size());

        LOG_INFO(
            "[RR_INPUT_PROBE] linearDepth (R32_FLOAT, RR-facing) {}x{}: samples={}, min={:.4f}, max={:.4f}, "
            "mean|v|={:.4f}, p50|v|={:.4f}, p95|v|={:.4f}, negative={:.1f}%, exactZero={:.1f}%, nonFinite={}",
            sampleWidth, sampleHeight, UINT(magnitudes.size()), minValue, maxValue,
            sum / double(magnitudes.size()), PercentileOf(magnitudes, 0.50f),
            PercentileOf(magnitudes, 0.95f), float(negatives) * rcpCount,
            float(zeros) * rcpCount, nonFinite);

        const char* bucketNames[6] = {
            "<0.1 (sub-metre)", "0.1-1", "1-10", "10-100", "100-1000", ">=1000"
        };
        LOG_INFO("[RR_INPUT_PROBE] linearDepth |v| distribution: {}={:.1f}%, {}={:.1f}%, {}={:.1f}%, "
                 "{}={:.1f}%, {}={:.1f}%, {}={:.1f}%",
                 bucketNames[0], float(buckets[0]) * rcpCount,
                 bucketNames[1], float(buckets[1]) * rcpCount,
                 bucketNames[2], float(buckets[2]) * rcpCount,
                 bucketNames[3], float(buckets[3]) * rcpCount,
                 bucketNames[4], float(buckets[4]) * rcpCount,
                 bucketNames[5], float(buckets[5]) * rcpCount);
    }

    // Reports the canonical motion field in pixels, the range actually stored in the
    // source texture, and its depth delta.
    //
    // Two questions need separate answers here. Whether the field is alive at all is
    // read from the pixel magnitudes: a moving camera produces tens of pixels, a
    // frozen scene produces exact zeros. Whether the stored values are pixel- or
    // UV-space is read by dividing the canonical value back out by the transform the
    // converter applied - the number that comes back is what the title wrote, and
    // its magnitude says which convention it used.
    void LogMotionProbe(const uint8_t* data, UINT rowPitch, const ProbeSampling& sampling)
    {
        const UINT sampleWidth = std::min(m_inputProbeWidth, m_maxWidth);
        const UINT sampleHeight = std::min(m_inputProbeHeight, m_maxHeight);

        std::vector<float> pixelMagnitudes;
        std::vector<float> depthDeltas;
        std::vector<float> storedMagnitudes;
        pixelMagnitudes.reserve(sampling.samples);
        depthDeltas.reserve(sampling.samples);
        storedMagnitudes.reserve(sampling.samples);

        UINT nonFinite = 0;
        UINT zeroXy = 0;
        UINT activeXy = 0;

        const float transformX = m_inputProbeMotionTransform.x;
        const float transformY = m_inputProbeMotionTransform.y;
        const bool transformInvertible =
            std::isfinite(transformX) && std::isfinite(transformY) &&
            transformX != 0.0f && transformY != 0.0f;

        for (UINT y = sampling.strideY / 2; y < sampleHeight; y += sampling.strideY)
        {
            const uint16_t* row = reinterpret_cast<const uint16_t*>(data + size_t(y) * rowPitch);
            for (UINT x = sampling.strideX / 2; x < sampleWidth; x += sampling.strideX)
            {
                const float motionX = ProbeHalfToFloat(row[x * 4 + 0]);
                const float motionY = ProbeHalfToFloat(row[x * 4 + 1]);
                const float depthDelta = ProbeHalfToFloat(row[x * 4 + 2]);

                if (!std::isfinite(motionX) || !std::isfinite(motionY) || !std::isfinite(depthDelta))
                {
                    ++nonFinite;
                    continue;
                }

                // Canonical motion is a UV displacement, so pixels need the render extent.
                const float pixelsX = motionX * float(sampleWidth);
                const float pixelsY = motionY * float(sampleHeight);
                const float magnitude = std::sqrt(pixelsX * pixelsX + pixelsY * pixelsY);
                pixelMagnitudes.push_back(magnitude);
                depthDeltas.push_back(std::abs(depthDelta));

                if (transformInvertible)
                {
                    const float storedX = motionX / transformX;
                    const float storedY = motionY / transformY;
                    storedMagnitudes.push_back(std::sqrt(storedX * storedX + storedY * storedY));
                }

                if (motionX == 0.0f && motionY == 0.0f)
                    ++zeroXy;
                if (magnitude > 0.05f)
                    ++activeXy;
            }
        }

        if (pixelMagnitudes.empty())
        {
            LOG_WARN("[RR_INPUT_PROBE] motion: no finite samples");
            return;
        }

        std::sort(pixelMagnitudes.begin(), pixelMagnitudes.end());
        std::sort(depthDeltas.begin(), depthDeltas.end());
        std::sort(storedMagnitudes.begin(), storedMagnitudes.end());
        const float rcpCount = 100.0f / float(pixelMagnitudes.size());

        LOG_INFO(
            "[RR_INPUT_PROBE] motion (RGBA16F, RR-facing) {}x{}: samples={}, canonicalPixels p50={:.3f}, "
            "p95={:.3f}, max={:.3f}, exactZeroXY={:.1f}%, moving(>0.05px)={:.1f}%, |depthDelta| p50={:.6f}, "
            "p95={:.6f}, max={:.6f}, nonFinite={}",
            sampleWidth, sampleHeight, UINT(pixelMagnitudes.size()),
            PercentileOf(pixelMagnitudes, 0.50f), PercentileOf(pixelMagnitudes, 0.95f),
            pixelMagnitudes.back(), float(zeroXy) * rcpCount, float(activeXy) * rcpCount,
            PercentileOf(depthDeltas, 0.50f), PercentileOf(depthDeltas, 0.95f),
            depthDeltas.back(), nonFinite);

        // The converter multiplies the stored value by MotionTransform to reach UV. A
        // transform of 1/renderWidth means the stored value was assumed to be a
        // render-pixel delta; a stored magnitude near 1e-3 with that transform is the
        // signature of a title that supplies UV-space motion instead.
        if (!storedMagnitudes.empty())
        {
            LOG_INFO(
                "[RR_INPUT_PROBE] motion transform=(x={:.8f}, y={:.8f}) => impliedScale=({:.4f}, {:.4f}); "
                "stored-in-texture|v| p50={:.6f}, p95={:.6f}, max={:.6f}",
                transformX, transformY,
                transformX * float(sampleWidth), transformY * float(sampleHeight),
                PercentileOf(storedMagnitudes, 0.50f), PercentileOf(storedMagnitudes, 0.95f),
                storedMagnitudes.back());
        }
    }

    // Reports the octahedrally encoded world normals, their packed roughness and the
    // material type. A decoded length far from one means RR's edge weights are being
    // computed from something that is not a direction.
    void LogNormalsProbe(const uint8_t* data, UINT rowPitch, const ProbeSampling& sampling)
    {
        const UINT sampleWidth = std::min(m_inputProbeWidth, m_maxWidth);
        const UINT sampleHeight = std::min(m_inputProbeHeight, m_maxHeight);

        std::vector<float> decodedLengths;
        std::vector<float> upComponents;
        decodedLengths.reserve(sampling.samples);
        upComponents.reserve(sampling.samples);

        UINT degenerate = 0;
        UINT exactZeroRoughness = 0;
        UINT typeZero = 0;
        UINT pointingDown = 0;
        UINT horizontal = 0;
        double roughnessSum = 0.0;

        for (UINT y = sampling.strideY / 2; y < sampleHeight; y += sampling.strideY)
        {
            const uint32_t* row = reinterpret_cast<const uint32_t*>(data + size_t(y) * rowPitch);
            for (UINT x = sampling.strideX / 2; x < sampleWidth; x += sampling.strideX)
            {
                // R10G10B10A2_UNORM: R in bits 0-9, G 10-19, B 20-29, A 30-31.
                const uint32_t packed = row[x];
                const float encodedX = float(packed & 0x3FFu) / 1023.0f;
                const float encodedY = float((packed >> 10) & 0x3FFu) / 1023.0f;
                const float roughness = float((packed >> 20) & 0x3FFu) / 1023.0f;
                const uint32_t materialType = (packed >> 30) & 0x3u;

                // Mirrors OctahedralDecode in FSRDPreprocessCommon.hlsli.
                const float octX = 2.0f * (encodedX - 0.5f);
                const float octY = 2.0f * (encodedY - 0.5f);
                float normalX = octX;
                float normalY = octY;
                const float normalZ = 1.0f - std::abs(octX) - std::abs(octY);
                const float fold = std::max(-normalZ, 0.0f);
                normalX += (normalX >= 0.0f) ? -fold : fold;
                normalY += (normalY >= 0.0f) ? -fold : fold;

                const float length = std::sqrt(
                    normalX * normalX + normalY * normalY + normalZ * normalZ);
                decodedLengths.push_back(length);
                if (length > 1e-6f)
                {
                    const float normalizedY = normalY / length;
                    upComponents.push_back(normalizedY);
                    if (normalizedY < -0.9f)
                        ++pointingDown;
                    else if (std::abs(normalizedY) < 0.1f)
                        ++horizontal;
                }

                if (length < 0.5f)
                    ++degenerate;
                if (roughness == 0.0f)
                    ++exactZeroRoughness;
                if (materialType == 0u)
                    ++typeZero;
                roughnessSum += double(roughness);
            }
        }

        if (decodedLengths.empty())
        {
            LOG_WARN("[RR_INPUT_PROBE] normals: no samples");
            return;
        }

        std::sort(decodedLengths.begin(), decodedLengths.end());
        std::sort(upComponents.begin(), upComponents.end());
        const float rcpCount = 100.0f / float(decodedLengths.size());

        LOG_INFO(
            "[RR_INPUT_PROBE] normals (R10G10B10A2, RR-facing) {}x{}: samples={}, |octDecode| p50={:.4f}, "
            "p95={:.4f}, max={:.4f}, degenerate(<0.5)={:.1f}%, decodedWorldY p50={:.4f}, p95={:.4f}, "
            "downward(Y<-0.9)={:.1f}%, horizontal(|Y|<0.1)={:.1f}%",
            sampleWidth, sampleHeight, UINT(decodedLengths.size()),
            PercentileOf(decodedLengths, 0.50f), PercentileOf(decodedLengths, 0.95f),
            decodedLengths.back(), float(degenerate) * rcpCount,
            PercentileOf(upComponents, 0.50f), PercentileOf(upComponents, 0.95f),
            float(pointingDown) * rcpCount, float(horizontal) * rcpCount);

        LOG_INFO(
            "[RR_INPUT_PROBE] normals channels: roughness mean={:.4f}, exactZero={:.1f}%, "
            "materialType 0={:.1f}%, >=1={:.1f}%",
            float(roughnessSum / double(decodedLengths.size())),
            float(exactZeroRoughness) * rcpCount,
            float(typeZero) * rcpCount, float(decodedLengths.size() - typeZero) * rcpCount);
    }

    // Reports the specular signal the converter hands RR: RGB is demodulated radiance,
    // A is the ray length. The diffuse counterpart is probed from the feature side; this
    // one has never been measured, and it is the signal whose alpha carries the
    // hit-distance contract, so a dead or sentinel-only field here would be invisible
    // in every debug view that shows the composed image.
    void LogSignalProbe(const uint8_t* data, UINT rowPitch, const ProbeSampling& sampling)
    {
        const UINT sampleWidth = std::min(m_inputProbeWidth, m_maxWidth);
        const UINT sampleHeight = std::min(m_inputProbeHeight, m_maxHeight);

        UINT samples = 0;
        UINT dead = 0;
        UINT bright = 0;
        UINT nonFinite = 0;
        UINT negativeAlpha = 0;
        UINT missingAlpha = 0; // the FP16-max "ray miss" sentinel
        double lumaSum = 0.0;
        double alphaSum = 0.0;
        float lumaMax = 0.0f;
        float alphaMax = 0.0f;
        float alphaMin = 0.0f;
        float dumped[4][4] = {};

        for (UINT y = sampling.strideY / 2; y < sampleHeight; y += sampling.strideY)
        {
            const uint16_t* row = reinterpret_cast<const uint16_t*>(data + size_t(y) * rowPitch);
            for (UINT x = sampling.strideX / 2; x < sampleWidth; x += sampling.strideX)
            {
                const float r = ProbeHalfToFloat(row[x * 4 + 0]);
                const float g = ProbeHalfToFloat(row[x * 4 + 1]);
                const float b = ProbeHalfToFloat(row[x * 4 + 2]);
                const float a = ProbeHalfToFloat(row[x * 4 + 3]);

                if (!std::isfinite(r) || !std::isfinite(g) || !std::isfinite(b) || !std::isfinite(a))
                {
                    ++nonFinite;
                    continue;
                }

                const float luma = 0.2126f * r + 0.7152f * g + 0.0722f * b;
                ++samples;
                lumaSum += double(luma);
                alphaSum += double(a);
                lumaMax = std::max(lumaMax, luma);
                alphaMax = std::max(alphaMax, a);

                if (luma < 1e-5f)
                    ++dead;
                if (luma > 1e-2f)
                    ++bright;
                if (a < 0.0f)
                    ++negativeAlpha;
                else if (a >= 65504.0f)
                    ++missingAlpha;

                alphaMin = (samples == 1u) ? a : std::min(alphaMin, a);

                if (samples <= 4u)
                {
                    dumped[samples - 1u][0] = luma;
                    dumped[samples - 1u][1] = a;
                }
            }
        }

        // Keep the first four luminance samples in the same record as the statistics so a
        // value-level reading does not need a second pass.
        if (samples == 0)
        {
            LOG_WARN("[RR_INPUT_PROBE] specular signal: no finite samples");
            return;
        }

        const float rcpCount = 100.0f / float(samples);
        LOG_INFO(
            "[RR_INPUT_PROBE] specular signal input (RGBA16F, RR-facing) {}x{}: samples={}, avgLuma={:.6f}, "
            "maxLuma={:.6f}, dead(<1e-5)={:.1f}%, bright(>1e-2)={:.1f}%, alpha min={:.4f}, mean={:.4f}, "
            "max={:.4f}, negative={:.1f}%, FP16maxSentinel={:.1f}%, nonFinite={}",
            sampleWidth, sampleHeight, samples, lumaSum / double(samples), lumaMax,
            float(dead) * rcpCount, float(bright) * rcpCount,
            alphaMin, alphaSum / double(samples), alphaMax,
            float(negativeAlpha) * rcpCount, float(missingAlpha) * rcpCount, nonFinite);

    }

    // Reports how much of the frame reaches the denoiser through the specular signal rather than
    // the diffuse one, read from the share the conversion shader leaves in the specular albedo's
    // unused alpha. It is the title's own material split, so it says how much of the image is
    // exposed to the specular signal's handling - including a ray-length guide the denoiser may
    // refuse to denoise at all, which is a failure mode this probe makes visible as a number.
    void LogSpecularShareProbe(const uint8_t* data, UINT rowPitch, const ProbeSampling& sampling)
    {
        const UINT sampleWidth = std::min(m_inputProbeWidth, m_maxWidth);
        const UINT sampleHeight = std::min(m_inputProbeHeight, m_maxHeight);

        UINT samples = 0;
        UINT specularDominant = 0;
        double shareSum = 0.0;

        for (UINT y = sampling.strideY / 2; y < sampleHeight; y += sampling.strideY)
        {
            const uint8_t* row = data + size_t(y) * rowPitch;
            for (UINT x = sampling.strideX / 2; x < sampleWidth; x += sampling.strideX)
            {
                ++samples;
                const uint32_t share = row[x * 4 + 3];
                shareSum += double(share) / 255.0;
                if (share >= 128u)
                    ++specularDominant;
            }
        }

        if (samples == 0)
            return;

        LOG_INFO("[RR_INPUT_PROBE] specular signal share: mean {:.2f}%, specular-dominant "
                 "{:.2f}% ({}/{}) - the share of the frame the denoiser receives through the "
                 "specular signal",
                 float(shareSum) * 100.0f / float(samples),
                 float(specularDominant) * 100.0f / float(samples), specularDominant, samples);
    }

    // Magnitude of a colour texture, which is all the skip signal needs: the question is how
    // much colour it carries and whether that quantity is what the visible noise tracks.
    void LogMagnitudeProbe(const char* name, const uint8_t* data, UINT rowPitch,
                           const ProbeSampling& sampling, bool halfPrecision)
    {
        const UINT sampleWidth = std::min(m_inputProbeWidth, m_maxWidth);
        const UINT sampleHeight = std::min(m_inputProbeHeight, m_maxHeight);

        UINT samples = 0;
        UINT dead = 0;
        double lumaSum = 0.0;
        float lumaMax = 0.0f;

        for (UINT y = sampling.strideY / 2; y < sampleHeight; y += sampling.strideY)
        {
            const uint8_t* row = data + size_t(y) * rowPitch;
            for (UINT x = sampling.strideX / 2; x < sampleWidth; x += sampling.strideX)
            {
                float r = 0.0f, g = 0.0f, b = 0.0f, a = 0.0f;
                if (halfPrecision)
                {
                    const uint16_t* h = reinterpret_cast<const uint16_t*>(row) + size_t(x) * 4;
                    r = ProbeHalfToFloat(h[0]);
                    g = ProbeHalfToFloat(h[1]);
                    b = ProbeHalfToFloat(h[2]);
                    a = ProbeHalfToFloat(h[3]);
                }
                else
                {
                    const uint8_t* p = row + size_t(x) * 4;
                    r = float(p[0]) / 255.0f;
                    g = float(p[1]) / 255.0f;
                    b = float(p[2]) / 255.0f;
                    a = float(p[3]) / 255.0f;
                }

                if (!std::isfinite(r) || !std::isfinite(g) || !std::isfinite(b) || !std::isfinite(a))
                    continue;

                ++samples;
                const float luma = 0.2126f * r + 0.7152f * g + 0.0722f * b;
                lumaSum += double(luma);
                lumaMax = std::max(lumaMax, luma);
                if (luma < 1e-5f)
                    ++dead;
            }
        }

        if (samples == 0)
            return;

        LOG_INFO("[RR_INPUT_PROBE] {}: samples={}, avgLuma={:.6f}, maxLuma={:.6f}, dead(<1e-5)={:.1f}%",
                 name, samples, lumaSum / double(samples), lumaMax,
                 float(dead) * 100.0f / float(samples));
    }


    // Returns false when the capture's copy submission has not executed yet, or the
    // readback could not be mapped this attempt; the caller retries on a later
    // conversion. Returning true consumes the pending log whatever the outcome.
    bool LogInputProbe()
    {
        if (m_pDev == nullptr || m_inputProbeWidth == 0 || m_inputProbeHeight == 0)
            return true;

        // The map loop below indexes the whole set, so it checks the whole set rather than
        // taking element 0 as a proxy for it - the assumption that let a partially rebuilt
        // array through on the allocation side would be a null dereference here.
        for (UINT i = 0; i < kInputProbeTargetCount; i++)
        {
            if (m_inputProbeReadback[i] == nullptr)
                return true;
        }

        if (!m_inputProbeTicket || !m_inputProbeTicket->Ready())
            return false;

        void* mapped[kInputProbeTargetCount] = {};
        for (UINT i = 0; i < kInputProbeTargetCount; i++)
        {
            if (FAILED(m_inputProbeReadback[i]->Map(0, nullptr, &mapped[i])) || mapped[i] == nullptr)
            {
                LOG_ERROR("[RR_INPUT_PROBE] readback map failed for target {}", i);
                for (UINT j = 0; j < i; j++)
                    m_inputProbeReadback[j]->Unmap(0, nullptr);
                return false;
            }
        }

        const ProbeSampling sampling = GetProbeSampling(m_inputProbeWidth, m_inputProbeHeight);
        LOG_INFO("[RR_INPUT_PROBE] reading back {}x{} render extent from the conversion",
                 m_inputProbeWidth, m_inputProbeHeight);

        LogLinearDepthProbe(
            static_cast<const uint8_t*>(mapped[0]), m_inputProbeRowPitch[0], sampling);
        LogMotionProbe(
            static_cast<const uint8_t*>(mapped[1]), m_inputProbeRowPitch[1], sampling);
        LogNormalsProbe(
            static_cast<const uint8_t*>(mapped[2]), m_inputProbeRowPitch[2], sampling);
        LogSignalProbe(
            static_cast<const uint8_t*>(mapped[3]), m_inputProbeRowPitch[3], sampling);
        LogSpecularShareProbe(
            static_cast<const uint8_t*>(mapped[4]), m_inputProbeRowPitch[4], sampling);
        LogMagnitudeProbe("skip signal (RR-facing)", static_cast<const uint8_t*>(mapped[5]),
                          m_inputProbeRowPitch[5], sampling, true);

        for (UINT i = 0; i < kInputProbeTargetCount; i++)
            m_inputProbeReadback[i]->Unmap(0, nullptr);

        return true;
    }

    void Initialize(
        std::span<const byte> geometryByteCode, 
        std::span<const byte> convByteCode, 
        std::span<const byte> compByteCode
    )
    {
        ScopedSkipHeapCapture skipHeapCapture {};

        LOG_DEBUG("Creating FSRD interop shaders...");

        m_geometryShader.Initialize(m_pDev, geometryByteCode, sizeof(Geometry::Constants),
            Geometry::Input::kCount, Geometry::Output::kCount, L"FSRD_Geometry_Constants");
        m_convShader.Initialize(m_pDev, convByteCode, sizeof(Conversion::Constants), 
            Conversion::Input::kCount, Conversion::Output::kCount, L"FSRD_Conv_Constants", Conversion::kBackBufferCount);
        m_compShader.Initialize(m_pDev, compByteCode, sizeof(Composition::Constants), 
            Composition::Input::kCount, Composition::kOutputCount, L"FSRD_Comp_Constants", Composition::kBackBufferCount);
        m_trustEvidenceShader.Initialize(m_pDev,
            { reinterpret_cast<const byte*>(FSRDAlbedoTrustEvidence_cso), sizeof(FSRDAlbedoTrustEvidence_cso) },
            sizeof(TrustEvidence::Constants), TrustEvidence::Input::kCount, TrustEvidence::Output::kCount,
            L"FSRD_TrustEvidence_Constants", TrustEvidence::kBackBufferCount);
        m_trustPropagateShader.Initialize(m_pDev,
            { reinterpret_cast<const byte*>(FSRDAlbedoTrustPropagate_cso), sizeof(FSRDAlbedoTrustPropagate_cso) },
            sizeof(TrustPropagate::Constants), TrustPropagate::Input::kCount, TrustPropagate::Output::kCount,
            L"FSRD_TrustPropagate_Constants", TrustPropagate::kBackBufferCount);
        LOG_DEBUG("FSRD interop shaders and resources initialized.");
    }


    void SetMaxRenderSize(UINT width, UINT height)
    {
        if (m_maxWidth == width && m_maxHeight == height)
            return;
        m_gameTrace.Abort("Render resources resized during capture.");
        m_research.Abort("Reference aborted: render resources resized.");
        m_leakView.Reset();


        // Clear the latch before allocating rather than after. CreateTexture2D
        // throws on failure, which leaves the object holding a mix of new- and
        // old-sized textures; if the requested dimensions were already latched, an
        // identical retry would hit the early-out above and silently "succeed" with
        // that mix still in place. The latch is set at the end, once every
        // allocation has actually completed.
        m_maxWidth = 0;
        m_maxHeight = 0;
        m_skinPrepared.Reset(); m_skinGuide.Reset(); m_skinBlur.Reset(); m_skinResult.Reset(); m_skinDiffuse.Reset();
        m_skinBounds8.Reset(); m_skinBounds16.Reset();
        m_sssKernel.Reset(); m_skinFused = false;
        m_skinOutputActive = false; m_skinMode = 0;
        // Post-flick textures are size bound: drop them so EnsurePostFlick rebuilds them at the new extent instead
        // of leaving the option silently dead (a size change is a context rebuild, not a toggle).
        for (auto* set : {&m_postFlickKey, &m_postFlickKeyAux, &m_postFlickAux})
            for (auto& resource : *set) resource.Reset();
        m_postFlickCur.Reset(); m_postFlickOutput.Reset();
        m_postFlickParity = 0; m_postFlickWidth = 0; m_postFlickHeight = 0;
        m_postFlickValid = false; m_postFlickActive = false; m_postFlickWasEnabled = false;
        m_postFlickKeyState = PostFlickMath::KeyState {};
        // The colour-tracking textures are size bound as well: drop them so EnsureColourTrack rebuilds them at the
        // new extent instead of leaving the option silently dead (a size change is a context rebuild, not a toggle).
        m_colourTrackInput.Reset(); m_colourTrackStats.Reset(); m_colourTrackTarget.Reset();
        m_colourTrackMotion.Reset(); m_colourTrackGain.Reset();
        for (auto& resource : m_colourTrackHistory) resource.Reset();
        m_colourTrackHistoryIndex = 0; m_colourTrackWidth = 0; m_colourTrackHeight = 0;
        m_colourTrackValid = false; m_colourTrackWasEnabled = false; m_colourTrackActive = false;
        // The anchor's ring and fields are size bound: drop them so EnsurePostMotionAnchor rebuilds them at the
        // new extent (a size change is a context rebuild, not a toggle), and restart the ring state.
        m_postMotionKeyLevel.Reset(); m_postMotionKeyDepth.Reset();
        m_postMotionStats.Reset(); m_postMotionRecalled.Reset(); m_postMotionGain.Reset();
        m_postMotionWidth = 0; m_postMotionHeight = 0;
        m_postMotionWasEnabled = false; m_postMotionActive = false;
        m_postMotionState = PostMotionAnchorMath::State {};
        for (auto* set : {&m_albedoStabSpec, &m_albedoStabDiff, &m_albedoStabNormal})
            for (auto& resource : *set) resource.Reset();
        m_albedoStabSpareSpecAlbedo.Reset(); m_albedoStabSpareDiffAlbedo.Reset();
        m_albedoStabSpareSpecSignal.Reset(); m_albedoStabSpareDiffSignal.Reset();
        m_albedoStabValid = false;
        for (auto* set : {&m_fogA, &m_fogB, &m_fogC, &m_fogGuides})
            for (auto& resource : *set) resource.Reset();
        m_fogG.Reset(); m_fogH.Reset(); m_fogKappaRaw.Reset(); m_fogKappaRank.Reset(); m_fogKappa.Reset();
        m_fogTargetSpec.Reset(); m_fogTargetDiff.Reset();
        m_fogSpareSpecAlbedo.Reset(); m_fogSpareDiffAlbedo.Reset();
        m_fogSpareSpecSignal.Reset(); m_fogSpareDiffSignal.Reset();
        m_fogValid = false;
        m_rrMotion.Reset();
        m_rrMotionActive = false;
        ResetLobeRecovery();
        m_flatDetailTiles.Reset(); m_flatDetailArguments.Reset(); m_flatDetailReset.Reset();
        for (auto& resource : m_flatDetailReference) resource.Reset();
        for (auto& resource : m_flatDetailStatistics) resource.Reset();
        m_flatDetailBase.Reset(); m_flatDetailMean.Reset(); m_flatDetailVariance.Reset();
        m_flatDetailActive = false;
        m_flatHistoryReference.Reset(); m_flatHistoryAux.Reset(); m_flatHistoryLP.Reset();
        m_flatTemporalLP.Reset(); m_flatTemporalDiagnostics.Reset();
        ResetFlatTemporalHistory();

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
        outResources.Diagnostic = CreateTexture2D(m_pDev, 1, 1, FSRDFormats::SkipSignal, L"FSR_Conv_UnusedJournal", kSrvState);
        const auto optional = [&](bool enabled, DXGI_FORMAT format, LPCWSTR name) {
            return CreateTexture2D(m_pDev, enabled ? width : 1u, enabled ? height : 1u, format, name, kSrvState);
        };
        outResources.DirectSpecular = optional(m_albedoRecovery, FSRDFormats::DirectSpecular, L"FSR_Conv_DirectSpecular");
        outResources.IndirectDiffuse = optional(m_albedoRecovery, FSRDFormats::DirectSpecular, L"FSR_Conv_IndirectDiffuse");
        m_directSpecularOutput = optional(m_extraSpecular, FSRDFormats::DirectSpecular, L"FSR_RR_DirectSpecular_Output");
        m_indirectDiffuseOutput = optional(m_extraDiffuse, FSRDFormats::DirectSpecular, L"FSR_RR_IndirectDiffuse_Output");
        m_albedoTrust[0] = optional(m_albedoRecovery, FSRDFormats::AlbedoTrust, L"FSR_AlbedoTrust_0");
        m_albedoTrust[1] = optional(m_albedoRecovery, FSRDFormats::AlbedoTrust, L"FSR_AlbedoTrust_1");
        m_albedoTrustResult = 0;
        m_LinearDepth = CreateTex(FSRDFormats::LinearDepth, L"FSR_Conv_LinearDepth");
        m_PrevLinearDepth = CreateTex(FSRDFormats::LinearDepth, L"FSR_Conv_PreviousLinearDepth");
        m_linearDepthSize = {};
        m_previousDepthValid = false;
        m_outputBuffer1 = CreateTex(FSRDFormats::OutputBuffer1, L"FSR_Conv_OutputBuffer1");
        m_outputBuffer2 = CreateTex(FSRDFormats::OutputBuffer2, L"FSR_Conv_OutputBuffer2");
        m_ambientOcclusionOutput =
            CreateTex(FSRDFormats::AmbientOcclusion, L"FSR_RR_AmbientOcclusion_Output");
        m_specularOcclusionOutput =
            CreateTex(FSRDFormats::SpecularOcclusion, L"FSR_RR_SpecularOcclusion_Output");

        m_compositionOutput = CreateTex(DXGI_FORMAT_R16G16B16A16_FLOAT, L"FSR_Composition_Output");
        for (auto& target : m_recoveryOutput)
            target = CreateTex(DXGI_FORMAT_R16G16B16A16_FLOAT, L"FSR_Recovery_Output");
        m_recoveryOutputIndex = -1;
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

    void DispatchGeometry(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        Geometry::Constants constants {
            .InvProjMatrix = desc.InvProjMatrix,
            .RenderSize = desc.RenderSize,
            .NearPlane = desc.NearPlane,
            .FarPlane = desc.FarPlane,
            .Flags = ((desc.Flags & uint32_t(ConvFlags::IsDepthLinear)) ? Geometry::LinearDepth : 0u) |
                     ((desc.Flags & uint32_t(ConvFlags::RightHanded)) ? Geometry::NegativeViewDepth : 0u) |
                     ((desc.Flags & uint32_t(ConvFlags::TitleLinearDepth)) && desc.Resources.InTitleLinearDepth
                        ? Geometry::TitleLinearDepth : 0u),
            .CurrentJitter = {desc.JitterOffsets.x, desc.JitterOffsets.y},
            .DepthBase = {desc.ColorDepthBase.z, desc.ColorDepthBase.w},
            .TitleDepthBase = desc.TitleLinearDepthBase
        };
        Geometry::Input in {{desc.Resources.InDepth, desc.Resources.InTitleLinearDepth}};
        Geometry::Output out {{m_LinearDepth.Get()}};
        if (m_gameTraceCaptureRequested)
            memcpy(m_gameTraceGeometryConstants.data(), &constants, sizeof(constants));
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassGeometryDepth);
            m_geometryShader.Dispatch(cmdList, GetAsByteSpan(constants), in.AsArray, out.AsArray,
                                      {desc.RenderSize.x, desc.RenderSize.y});
        }
    }

    void EnsureFlatDetail()
    {
        if (m_flatDetailTiles) return;
        ScopedSkipHeapCapture skipHeapCapture {};
        if (!m_flatDetailSeedShader.m_pso)
        {
            m_flatDetailClassifyShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatDetailClassify_cso),
                sizeof(XMFLOAT4), 2, 2, L"FSRD_FlatDetail_Classify");
            m_flatDetailSeedShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatDetailSeed_cso),
                sizeof(FlatDetail::Constants), FlatDetail::Input::kCount, FlatDetail::Output::kCount, L"FSRD_FlatDetail_Seed");
            m_flatDetailRefineShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatDetailRefine_cso),
                sizeof(FlatDetail::Constants), FlatDetail::Input::kCount, FlatDetail::Output::kCount, L"FSRD_FlatDetail_Refine");
            m_flatDetailBaseShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatDetailBase_cso),
                sizeof(FlatDetail::Constants), FlatDetail::Input::kCount, FlatDetail::Output::kCount, L"FSRD_FlatDetail_Base");
            m_flatDetailApplyShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatDetailApply_cso),
                sizeof(FlatDetail::Constants), FlatDetail::Input::kCount, FlatDetail::Output::kCount, L"FSRD_FlatDetail_Apply");
        }
        if (!m_flatDetailSignature)
        {
            D3D12_INDIRECT_ARGUMENT_DESC argument {};
            argument.Type = D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH;
            D3D12_COMMAND_SIGNATURE_DESC signature {sizeof(D3D12_DISPATCH_ARGUMENTS), 1, &argument, 0};
            ThrowIfFailed(m_pDev->CreateCommandSignature(&signature, nullptr, IID_PPV_ARGS(&m_flatDetailSignature)),
                          "Flat Detail indirect signature");
        }
        const auto buffer = [&](UINT64 bytes, LPCWSTR name, D3D12_RESOURCE_STATES state, bool upload = false) {
            D3D12_HEAP_PROPERTIES heap {upload ? D3D12_HEAP_TYPE_UPLOAD : D3D12_HEAP_TYPE_DEFAULT};
            auto desc = CD3DX12_RESOURCE_DESC::Buffer(bytes, upload ? D3D12_RESOURCE_FLAG_NONE : D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
            ComPtr<ID3D12Resource> resource;
            ThrowIfFailed(m_pDev->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr,
                          IID_PPV_ARGS(&resource)), "Flat Detail buffer");
            resource->SetName(name);
            return resource;
        };
        const auto texture = [&](LPCWSTR name) {
            return CreateTexture2D(m_pDev, m_maxWidth, m_maxHeight, DXGI_FORMAT_R16G16B16A16_FLOAT, name, kSrvState);
        };
        for (auto& resource : m_flatDetailReference) resource = texture(L"FSRD_FlatDetail_Reference");
        for (auto& resource : m_flatDetailStatistics) resource = texture(L"FSRD_FlatDetail_Statistics");
        m_flatDetailBase = texture(L"FSRD_FlatDetail_Base");
        m_flatDetailMean = texture(L"FSRD_FlatDetail_RRMean");
        m_flatDetailVariance = texture(L"FSRD_FlatDetail_AnchorSigma");
        auto arguments = buffer(sizeof(D3D12_DISPATCH_ARGUMENTS), L"FSRD_FlatDetail_Arguments", D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT);
        auto reset = buffer(28, L"FSRD_FlatDetail_Reset", D3D12_RESOURCE_STATE_GENERIC_READ, true);
        const uint32_t initial[] {0, 0, 0, 0, 0, 1, 1};
        void* mapped = nullptr;
        const D3D12_RANGE empty {0, 0};
        ThrowIfFailed(reset->Map(0, &empty, &mapped), "Flat Detail reset map");
        memcpy(mapped, initial, sizeof(initial));
        reset->Unmap(0, nullptr);
        const UINT64 tiles = UINT64((m_maxWidth + 7) / 8) * ((m_maxHeight + 7) / 8);
        auto list = buffer(16 + tiles * 8, L"FSRD_FlatDetail_Tiles", kSrvState);
        m_flatDetailArguments = std::move(arguments);
        m_flatDetailReset = std::move(reset);
        m_flatDetailTiles = std::move(list);
    }

    void ResetFlatTemporalHistory() noexcept
    {
        // Count gates every history read; uninitialised/stale array slices need no physical clear.
        m_flatHistoryHead = m_flatHistoryCount = m_flatHistoryLength = 0;
        m_flatHistorySize = {};
        m_flatTemporalWasEnabled = m_flatTemporalActive = false;
    }

    void EnsureFlatTemporal()
    {
        if (m_flatHistoryReference && m_flatHistoryAux && m_flatHistoryLP && m_flatTemporalLP &&
            m_flatTemporalDiagnostics) return;
        ScopedSkipHeapCapture skipHeapCapture {};
        if (!m_flatTemporalShader.m_pso)
            m_flatTemporalShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatTemporal_cso),
                sizeof(FlatTemporal::Constants), FlatTemporal::ResolveInput::kCount,
                FlatTemporal::ResolveOutput::kCount, L"FSRD_FlatTemporal");
        if (!m_flatTemporalStoreShader.m_pso)
            m_flatTemporalStoreShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatTemporalStore_cso),
                sizeof(FlatTemporal::Constants), FlatTemporal::StoreInput::kCount,
                FlatTemporal::StoreOutput::kCount, L"FSRD_FlatTemporal_Store");
        if (!m_flatTemporalLPShader.m_pso)
            m_flatTemporalLPShader.Initialize(m_pDev, GetAsByteSpan(FSRDFlatTemporalLP_cso),
                sizeof(FlatTemporal::Constants), FlatTemporal::LPInput::kCount, 1, L"FSRD_FlatTemporal_LP");
        const UINT lpWidth = (m_maxWidth + FlatTemporal::kLPBlock - 1) / FlatTemporal::kLPBlock;
        const UINT lpHeight = (m_maxHeight + FlatTemporal::kLPBlock - 1) / FlatTemporal::kLPBlock;
        const auto history = [&](LPCWSTR name, DXGI_FORMAT format, UINT width, UINT height) {
            D3D12_RESOURCE_DESC texture {};
            texture.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            texture.Width = width; texture.Height = height;
            texture.DepthOrArraySize = FlatTemporal::kHistorySlots; texture.MipLevels = 1;
            texture.Format = format; texture.SampleDesc.Count = 1;
            texture.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
            texture.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
            D3D12_HEAP_PROPERTIES heap {D3D12_HEAP_TYPE_DEFAULT};
            ComPtr<ID3D12Resource> resource;
            ThrowIfFailed(m_pDev->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,
                kSrvState, nullptr, IID_PPV_ARGS(&resource)), "Flat temporal history array");
            resource->SetName(name);
            return resource;
        };
        m_flatHistoryReference = history(L"FSRD_FlatTemporal_HistoryReference", DXGI_FORMAT_R16G16B16A16_FLOAT,
                                         m_maxWidth, m_maxHeight);
        m_flatHistoryAux = history(L"FSRD_FlatTemporal_HistoryAux", DXGI_FORMAT_R32G32_UINT, m_maxWidth, m_maxHeight);
        m_flatHistoryLP = history(L"FSRD_FlatTemporal_HistoryLP", DXGI_FORMAT_R16G16_FLOAT, lpWidth, lpHeight);
        m_flatTemporalLP = CreateTexture2D(m_pDev, lpWidth, lpHeight, DXGI_FORMAT_R16G16_FLOAT,
            L"FSRD_FlatTemporal_LP", kSrvState);
        m_flatTemporalDiagnostics = CreateTexture2D(m_pDev, m_maxWidth, m_maxHeight,
            DXGI_FORMAT_R16G16_FLOAT, L"FSRD_FlatTemporal_ValidCountWeight", kSrvState);
        ResetFlatTemporalHistory();
    }

    // Writes the temporal reference into `output` (the free ping-pong reference) and returns it.
    ID3D12Resource* ResolveFlatTemporal(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc,
                                      ID3D12Resource* originalReference, ID3D12Resource* output, uint32_t flags)
    {
        if (!desc.RecoveryFlatTemporal)
        {
            ResetFlatTemporalHistory();
            return originalReference;
        }
        EnsureFlatTemporal();
        const UINT length = std::clamp(desc.RecoveryFlatHistoryLength, 1u, FlatTemporal::kHistorySlots);
        const bool sameSize = memcmp(&m_flatHistorySize, &desc.DstTexSize, sizeof(desc.DstTexSize)) == 0;
        if (!m_flatTemporalWasEnabled || !m_motionHistoryValid || !sameSize || length != m_flatHistoryLength)
            ResetFlatTemporalHistory();
        FlatTemporal::Constants constants {
            .DstTexSize = desc.DstTexSize,
            .FullRenderSize = {desc.DstTexSize.x, desc.DstTexSize.y},
            .JitterDelta = m_flatHistoryJitterDelta,
            .Modulation = {desc.SpecularAlbedoDemodulation, desc.DiffuseAlbedoModulation},
            .TemporalStrength = 1.0f,
            .Epsilon = FlatDetail::kEpsilon,
            .HistoryCount = m_flatHistoryCount,
            .HistoryHead = m_flatHistoryHead,
            .HistoryLength = length,
            .Flags = flags,
            .CenterSigma = FlatTemporal::kCenterSigma,
            .MotionStart = FlatTemporal::kMotionStart,
            .MotionEnd = FlatTemporal::kMotionEnd,
            .HistoryDecay = FlatTemporal::kHistoryDecay,
        };
        auto& r = m_out.Resources;
        // Every 4x4 block of the current frame's low-pass lumas, before the resolve reads them.
        FlatTemporal::LPInput lpIn {{CompositionColor(), r.Normals.Get(), m_LinearDepth.Get(),
            r.Signals.IndirectSpecular.Get(), r.Signals.DirectDiffuse.Get(), r.SpecAlbedo.Get(), r.DiffAlbedo.Get(),
            r.SkipSignal.Get()}};
        ID3D12Resource* lpOut[] {m_flatTemporalLP.Get()};
        const float block = float(FlatTemporal::kLPBlock);
        FlatTemporal::ResolveInput in {{originalReference, r.Normals.Get(), m_LinearDepth.Get(), r.Motion.Get(),
            r.SkipSignal.Get(), m_flatDetailTiles.Get(), m_flatTemporalLP.Get(),
            m_flatHistoryReference.Get(), m_flatHistoryAux.Get(), m_flatHistoryLP.Get()}};
        FlatTemporal::ResolveOutput out {{output, m_flatTemporalDiagnostics.Get()}};
        {
            // The low-pass blocks are timed with the resolve: PassCount is at the 32-bit mask limit.
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassFlatTemporalResolve);
            m_flatTemporalLPShader.Dispatch(cmdList, GetAsByteSpan(constants), lpIn.AsArray, lpOut,
                {std::ceil(desc.DstTexSize.x / block), std::ceil(desc.DstTexSize.y / block)});
            m_flatTemporalShader.Dispatch(cmdList, GetAsByteSpan(constants), in.AsArray, out.AsArray, {0,0},
                true, nullptr, m_flatDetailSignature.Get(), m_flatDetailArguments.Get());
        }
        // Read only the original reference. Accumulated output must never re-enter the ring.
        // Store copies the current low-pass blocks into the ring after the resolve has read the old slot.
        FlatTemporal::StoreInput storeIn {{originalReference, r.Normals.Get(), m_LinearDepth.Get(),
            r.Motion.Get(), r.SkipSignal.Get(), m_flatTemporalLP.Get()}};
        FlatTemporal::StoreOutput storeOut {{m_flatHistoryReference.Get(), m_flatHistoryAux.Get(),
            m_flatHistoryLP.Get()}};
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassFlatTemporalStore);
            m_flatTemporalStoreShader.Dispatch(cmdList, GetAsByteSpan(constants), storeIn.AsArray, storeOut.AsArray,
                {desc.DstTexSize.x, desc.DstTexSize.y});
        }
        m_flatTemporalConstants = constants;
        m_flatHistoryHead = (m_flatHistoryHead + 1u) % FlatTemporal::kHistorySlots;
        m_flatHistoryCount = std::min(m_flatHistoryCount + 1u, FlatTemporal::kHistorySlots);
        m_flatHistoryLength = length;
        m_flatHistorySize = desc.DstTexSize;
        m_flatTemporalWasEnabled = m_flatTemporalActive = true;
        return output;
    }

    // --- Post-flick blotch fix (task 24 T2 c), default off ------------------------------------------------
    // A half-resolution keyframe/band/age pass pair that runs after the flat detail and before the skin, so the
    // skin copies the corrected composite. Nothing is allocated, bound or dispatched while the option is off.
    bool EnsurePostFlick()
    {
        // The textures are size bound and released on a resolution change, so the pipeline state alone is not
        // enough: recreate both whenever either is missing.
        if (m_postFlickPrepareShader.m_pso && m_postFlickOutput) return true;
        ScopedSkipHeapCapture skipHeapCapture {};
        if (!m_postFlickPrepareShader.m_pso)
        {
            m_postFlickPrepareShader.Initialize(m_pDev, GetAsByteSpan(FSRDPostFlickPrepare_cso), 32, 6, 4,
                L"FSRD_PostFlick_Prepare_Constants");
            m_postFlickApplyShader.Initialize(m_pDev, GetAsByteSpan(FSRDPostFlickApply_cso), 144, 5, 1,
                L"FSRD_PostFlick_Apply_Constants");
        }
        const uint32_t halfW = std::max(1u, m_postFlickWidth / 2), halfH = std::max(1u, m_postFlickHeight / 2);
        const auto create = [&](ComPtr<ID3D12Resource>& target, DXGI_FORMAT format, uint32_t w, uint32_t h, LPCWSTR name) {
            target = CreateTexture2D(m_pDev, w, h, format, name, kSrvState);
        };
        for (uint32_t parity = 0; parity < 2; ++parity)
        {
            create(m_postFlickKey[parity], DXGI_FORMAT_R16G16B16A16_FLOAT, halfW, halfH, L"FSR_PostFlick_Key");
            create(m_postFlickKeyAux[parity], DXGI_FORMAT_R16G16_FLOAT, halfW, halfH, L"FSR_PostFlick_KeyAux");
            create(m_postFlickAux[parity], DXGI_FORMAT_R16G16_FLOAT, halfW, halfH, L"FSR_PostFlick_Aux");
        }
        create(m_postFlickCur, DXGI_FORMAT_R16G16B16A16_FLOAT, halfW, halfH, L"FSR_PostFlick_Band");
        create(m_postFlickOutput, DXGI_FORMAT_R16G16B16A16_FLOAT, m_postFlickWidth, m_postFlickHeight, L"FSR_PostFlick_Output");
        m_postFlickParity = 0; m_postFlickValid = false;
        m_postFlickKeyState = PostFlickMath::KeyState {};
        return true;
    }
    // Reads the composite (SRV), the converted motion and the linear depth; writes the corrected composite into
    // m_postFlickOutput, which CompositionColor() then prefers over the recovery output until the next frame.
    void DispatchPostFlick(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        // The active flag is owned by DispatchComposition, which clears it at the start of the frame.
        if (!desc.PostFlickFix)
        {
            m_postFlickWasEnabled = false;
            return;
        }
        // Diagnostic frames are not the image: the other composition-phase consumers skip them too (recovery, flat
        // detail, skin). Without this the keyframe would be refreshed from a debug view's band and the real image
        // would keep debug colours for up to kMaxKeyAge frames after the debug view is closed; neither the angle
        // gate nor the depth test can see that, because both use the real camera and depth.
        if ((desc.Flags & (uint32_t(CompFlags::Debug) | uint32_t(CompFlags::RawSourceBlit))) != 0u)
        {
            m_postFlickWasEnabled = false;
            return;
        }
        const uint32_t requestedWidth = uint32_t(desc.DstTexSize.x), requestedHeight = uint32_t(desc.DstTexSize.y);
        if (!requestedWidth || !requestedHeight) return;
        // A render-size change (dynamic resolution) releases the size-bound textures and starts over next frame
        // instead of going silently dead: SetMaxRenderSize is not the only path that can change the extent.
        if ((m_postFlickWidth && m_postFlickWidth != requestedWidth) ||
            (m_postFlickHeight && m_postFlickHeight != requestedHeight))
        {
            for (auto* set : {&m_postFlickKey, &m_postFlickKeyAux, &m_postFlickAux})
                for (auto& resource : *set) resource.Reset();
            m_postFlickCur.Reset(); m_postFlickOutput.Reset();
            m_postFlickParity = 0; m_postFlickWidth = 0; m_postFlickHeight = 0;
            m_postFlickValid = false; m_postFlickWasEnabled = false;
            m_postFlickKeyState = PostFlickMath::KeyState {};
            return;
        }
        m_postFlickWidth = requestedWidth; m_postFlickHeight = requestedHeight;
        const uint32_t width = m_postFlickWidth, height = m_postFlickHeight;
        const uint32_t halfW = std::max(1u, width / 2), halfH = std::max(1u, height / 2);
        if (!EnsurePostFlick()) return;
        if (!m_postFlickWasEnabled)
        {
            // Rising edge: the first frame after the option is switched on must not reuse the previous run's
            // keyframe, age or history flag (up to six frames of stale recall).
            m_postFlickValid = false;
            m_postFlickKeyState = PostFlickMath::KeyState {};
            m_postFlickWasEnabled = true;
        }
        // Camera and constants: shared with the GPU fixture, see FSRDPostFlickConstants.h.
        PostFlickMath::Outputs outputs {};
        PostFlickMath::BuildFrame(m_postFlickKeyState, width, height, m_postFlickValid, desc.PostFlickStrength,
            desc.ViewMatrix, desc.ProjectionMatrix, desc.PrevViewMatrix, outputs);
        ID3D12Resource* composite = CompositionColor();
        // --- prepare (half resolution) ---
        ID3D12Resource* prepareInputs[] {composite, m_out.Resources.Motion.Get(), m_LinearDepth.Get(),
            m_postFlickAux[m_postFlickParity].Get(), m_postFlickKey[m_postFlickParity].Get(),
            m_postFlickKeyAux[m_postFlickParity].Get()};
        ID3D12Resource* prepareOutputs[] {m_postFlickCur.Get(), m_postFlickKey[m_postFlickParity ^ 1u].Get(),
            m_postFlickAux[m_postFlickParity ^ 1u].Get(), m_postFlickKeyAux[m_postFlickParity ^ 1u].Get()};
        m_postFlickPrepareShader.Dispatch(cmdList, GetAsByteSpan(outputs.Prepare), prepareInputs, prepareOutputs,
                                         {float(halfW), float(halfH)}, true);
        // --- apply (full resolution) ---
        ID3D12Resource* applyInputs[] {composite, m_postFlickAux[m_postFlickParity ^ 1u].Get(), m_postFlickCur.Get(),
            m_postFlickKey[m_postFlickParity ^ 1u].Get(), m_postFlickKeyAux[m_postFlickParity ^ 1u].Get()};
        ID3D12Resource* applyOutputs[] {m_postFlickOutput.Get()};
        m_postFlickApplyShader.Dispatch(cmdList, GetAsByteSpan(outputs.Apply), applyInputs, applyOutputs,
                                       {float(width), float(height)}, true);
        m_postFlickParity ^= 1u;
        m_postFlickValid = true;
        m_postFlickActive = true;
    }

    // --- Post-RR colour tracking (task 25 T2), default off ------------------------------------------------
    // RR's colour lags a smooth global change (about 60 frames to show half of one under the user's D16+G2), so
    // after a flick its chroma holds the pre-flick colour while the game's input has already moved. Three passes
    // run at the start of composition: quarter-res statistics of the composite and of RR's input colour, the
    // motion-reprojected EMA of that input colour, and the luminance-preserving per-channel gain applied in place
    // to the composite - so the recovery chain, the flat detail and NZR all see the corrected colour. Nothing is
    // allocated, bound or dispatched while the option is off.
    // True when this frame's composite can be colour tracked: the option is on, the frame is a real image, the
    // extent is usable and the size-bound textures (if any) match it. The composition pass writes its target
    // under this same decision, so the writer and the reader can never disagree about whether the pass runs.
    bool ColourTrackFrame(const CompositionDesc& desc) const
    {
        if (!desc.ColourTrack) return false;
        if ((desc.Flags & (uint32_t(CompFlags::Debug) | uint32_t(CompFlags::RawSourceBlit))) != 0u) return false;
        const uint32_t width = uint32_t(desc.DstTexSize.x), height = uint32_t(desc.DstTexSize.y);
        if (!width || !height) return false;
        return (m_colourTrackWidth == 0 || (m_colourTrackWidth == width && m_colourTrackHeight == height));
    }
    bool EnsureColourTrack()
    {
        // The textures are size bound and released on a resolution change, so the pipeline state alone is not
        // enough: recreate both whenever either is missing.
        if (m_colourTrackStatsShader.m_pso && m_colourTrackInput) return true;
        ScopedSkipHeapCapture skipHeapCapture {};
        if (!m_colourTrackStatsShader.m_pso)
        {
            m_colourTrackStatsShader.Initialize(m_pDev, GetAsByteSpan(FSRDColourTrackStats_cso),
                sizeof(ColourTrackMath::StatsConstants), 5, 3, L"FSRD_ColourTrack_Stats_Constants");
            m_colourTrackTrackShader.Initialize(m_pDev, GetAsByteSpan(FSRDColourTrackTrack_cso),
                sizeof(ColourTrackMath::TrackConstants), 4, 2, L"FSRD_ColourTrack_Track_Constants");
            m_colourTrackApplyShader.Initialize(m_pDev, GetAsByteSpan(FSRDColourTrackApply_cso),
                sizeof(ColourTrackMath::ApplyConstants), 1, 1, L"FSRD_ColourTrack_Apply_Constants");
        }
        const uint32_t width = m_colourTrackWidth, height = m_colourTrackHeight;
        const uint32_t quarterW = std::max(1u, width / 4), quarterH = std::max(1u, height / 4);
        const auto create = [&](ComPtr<ID3D12Resource>& target, uint32_t w, uint32_t h, LPCWSTR name) {
            target = CreateTexture2D(m_pDev, w, h, DXGI_FORMAT_R16G16B16A16_FLOAT, name, kSrvState);
        };
        create(m_colourTrackInput, width, height, L"FSR_ColourTrack_Input");
        create(m_colourTrackStats, quarterW, quarterH, L"FSR_ColourTrack_Stats");
        create(m_colourTrackTarget, quarterW, quarterH, L"FSR_ColourTrack_Target");
        create(m_colourTrackMotion, quarterW, quarterH, L"FSR_ColourTrack_Motion");
        create(m_colourTrackGain, quarterW, quarterH, L"FSR_ColourTrack_Gain");
        create(m_colourTrackHistory[0], quarterW, quarterH, L"FSR_ColourTrack_History");
        create(m_colourTrackHistory[1], quarterW, quarterH, L"FSR_ColourTrack_History");
        m_colourTrackHistoryIndex = 0; m_colourTrackValid = false;
        return true;
    }
    // Owns the size rules, the allocation and the rising edge, and runs before the composition dispatch because
    // the composition pass is what fills the target texture this pass reads. Returns false on a frame that must
    // not be tracked (option off, debug/raw frame, no extent, allocation failure).
    bool PrepareColourTrack(const CompositionDesc& desc)
    {
        if (!desc.ColourTrack)
        {
            m_colourTrackWasEnabled = false;
            return false;
        }
        if ((desc.Flags & (uint32_t(CompFlags::Debug) | uint32_t(CompFlags::RawSourceBlit))) != 0u)
        {
            m_colourTrackWasEnabled = false;
            m_colourTrackValid = false;
            return false;
        }
        const uint32_t width = uint32_t(desc.DstTexSize.x), height = uint32_t(desc.DstTexSize.y);
        if (!width || !height) return false;
        // A render-size change (dynamic resolution) releases the size-bound textures and rebuilds them here, so
        // the option keeps working instead of going silently dead: SetMaxRenderSize is not the only path that can
        // change the extent. The EMA restarts, which is the same fresh start a toggle gets.
        if (m_colourTrackWidth && (m_colourTrackWidth != width || m_colourTrackHeight != height))
        {
            m_colourTrackInput.Reset(); m_colourTrackStats.Reset(); m_colourTrackTarget.Reset();
            m_colourTrackMotion.Reset(); m_colourTrackGain.Reset();
            for (auto& resource : m_colourTrackHistory) resource.Reset();
            m_colourTrackHistoryIndex = 0; m_colourTrackWidth = 0; m_colourTrackHeight = 0;
            m_colourTrackValid = false; m_colourTrackWasEnabled = false;
        }
        m_colourTrackWidth = width; m_colourTrackHeight = height;
        if (!EnsureColourTrack())
        {
            m_colourTrackWasEnabled = false;
            return false;
        }
        if (!m_colourTrackWasEnabled)
        {
            // Rising edge: the first frame after the option is switched on must not reuse the previous run's EMA
            // (the target then starts from this frame's input colour, the prototype's t = 0 behaviour).
            m_colourTrackValid = false;
            m_colourTrackWasEnabled = true;
        }
        return true;
    }
    // Reads the composite and writes the corrected colour back into it (in place), so CompositionColor() needs no
    // extra preference: every later consumer of this frame sees the corrected composite.
    void DispatchColourTrack(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        if (!ColourTrackFrame(desc) || !m_colourTrackInput) return;
        const uint32_t width = m_colourTrackWidth, height = m_colourTrackHeight;
        const uint32_t quarterW = std::max(1u, width / 4), quarterH = std::max(1u, height / 4);
        const float tapStep = ColourTrackMath::TapStepFromRadius(std::clamp(desc.ColourTrackRadius,
            ColourTrackMath::kMinRadiusPixels, ColourTrackMath::kMaxRadiusPixels));
        // --- statistics (quarter resolution) ---
        const ColourTrackMath::StatsConstants statsConstants {
            .Size = {float(width), float(height), float(quarterW), float(quarterH)}};
        ID3D12Resource* statsInputs[] {m_compositionOutput.Get(), m_colourTrackInput.Get(),
            m_out.Resources.Motion.Get(), m_LinearDepth.Get(), m_out.Resources.Normals.Get()};
        ID3D12Resource* statsOutputs[] {m_colourTrackStats.Get(), m_colourTrackTarget.Get(),
            m_colourTrackMotion.Get()};
        m_colourTrackStatsShader.Dispatch(cmdList, GetAsByteSpan(statsConstants), statsInputs, statsOutputs,
            {float(quarterW), float(quarterH)});
        // --- reprojected EMA and the luminance-preserving gain (quarter resolution) ---
        const ColourTrackMath::TrackConstants trackConstants {
            .Size = {float(width), float(height), float(quarterW), float(quarterH)},
            .Params = {std::clamp(desc.ColourTrackEmaWeight, 0.05f, 1.0f), 0.02f,
                       std::clamp(desc.ColourTrackStrength, 0.0f, 1.0f), m_colourTrackValid ? 1.0f : 0.0f},
            .Params2 = {tapStep, 0.0f, 0.0f, 0.0f}};
        ID3D12Resource* trackInputs[] {m_colourTrackStats.Get(), m_colourTrackTarget.Get(),
            m_colourTrackMotion.Get(), m_colourTrackHistory[m_colourTrackHistoryIndex].Get()};
        ID3D12Resource* trackOutputs[] {m_colourTrackGain.Get(),
            m_colourTrackHistory[m_colourTrackHistoryIndex ^ 1u].Get()};
        m_colourTrackTrackShader.Dispatch(cmdList, GetAsByteSpan(trackConstants), trackInputs, trackOutputs,
            {float(quarterW), float(quarterH)});
        // --- apply (full resolution, in place) ---
        const ColourTrackMath::ApplyConstants applyConstants {
            .Size = {float(width), float(height), 1.0f / float(width), 1.0f / float(height)}};
        ID3D12Resource* applyInputs[] {m_colourTrackGain.Get()};
        ID3D12Resource* applyOutputs[] {m_compositionOutput.Get()};
        m_colourTrackApplyShader.Dispatch(cmdList, GetAsByteSpan(applyConstants), applyInputs, applyOutputs,
            {float(width), float(height)});
        m_colourTrackHistoryIndex ^= 1u;
        m_colourTrackValid = true;
        m_colourTrackActive = true;
    }

    // --- Post-motion level anchor (task 25 T3 ii) ---------------------------------------------------------
    // True when this frame may carry the anchor: the option is on, the frame is a real image and the extent is
    // usable. Every pass, barrier and write is gated on the same decision, so the off path can never allocate,
    // bind or dispatch anything.
    bool PostMotionAnchorFrame(const ConversionDesc& desc) const
    {
        if (!desc.PostMotionAnchor) return false;
        if ((desc.Flags & (uint32_t(ConvFlags::Debug))) != 0u) return false;
        const uint32_t width = uint32_t(desc.RenderSize.x), height = uint32_t(desc.RenderSize.y);
        if (!width || !height) return false;
        return m_postMotionWidth == 0 || (m_postMotionWidth == width && m_postMotionHeight == height);
    }
    bool EnsurePostMotionAnchor(uint32_t width, uint32_t height)
    {
        if (m_postMotionStatsRecallShader.m_pso && m_postMotionKeyLevel) return true;
        ScopedSkipHeapCapture skipHeapCapture {};
        if (!m_postMotionStatsRecallShader.m_pso)
        {
            m_postMotionStatsRecallShader.Initialize(m_pDev, GetAsByteSpan(FSRDPostMotionAnchorStatsRecall_cso),
                sizeof(PostMotionAnchorMath::StatsRecallConstants), 6, 3,
                L"FSRD_PostMotionAnchor_StatsRecall_Constants");
            m_postMotionGainShader.Initialize(m_pDev, GetAsByteSpan(FSRDPostMotionAnchorGain_cso),
                sizeof(PostMotionAnchorMath::GainConstants), 2, 4, L"FSRD_PostMotionAnchor_Gain_Constants");
            m_postMotionApplyShader.Initialize(m_pDev, GetAsByteSpan(FSRDPostMotionAnchorApply_cso),
                sizeof(PostMotionAnchorMath::ApplyConstants), 1, 2, L"FSRD_PostMotionAnchor_Apply_Constants");
        }
        const uint32_t cellsX = std::max(1u, width / 8u), cellsY = std::max(1u, height / 8u);
        m_postMotionKeyLevel = CreateTexture2DArraySlice(m_pDev, cellsX, cellsY, PostMotionAnchorMath::kRingSize,
            DXGI_FORMAT_R16G16B16A16_FLOAT, L"FSR_PostMotionAnchor_KeyLevel", kSrvState);
        m_postMotionKeyDepth = CreateTexture2DArraySlice(m_pDev, cellsX, cellsY, PostMotionAnchorMath::kRingSize,
            DXGI_FORMAT_R32_FLOAT, L"FSR_PostMotionAnchor_KeyDepth", kSrvState);
        m_postMotionStats = CreateTexture2D(m_pDev, cellsX, cellsY, DXGI_FORMAT_R16G16B16A16_FLOAT,
            L"FSR_PostMotionAnchor_Stats", kSrvState);
        m_postMotionRecalled = CreateTexture2D(m_pDev, cellsX, cellsY, DXGI_FORMAT_R16G16B16A16_FLOAT,
            L"FSR_PostMotionAnchor_Recalled", kSrvState);
        m_postMotionGain = CreateTexture2D(m_pDev, cellsX, cellsY, DXGI_FORMAT_R16G16B16A16_FLOAT,
            L"FSR_PostMotionAnchor_Gain", kSrvState);
        D3D12_RESOURCE_DESC sumsDesc {};
        sumsDesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        sumsDesc.Width = 16; sumsDesc.Height = 1; sumsDesc.DepthOrArraySize = 1; sumsDesc.MipLevels = 1;
        sumsDesc.SampleDesc.Count = 1; sumsDesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        sumsDesc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES sumsHeap { D3D12_HEAP_TYPE_DEFAULT };
        // Buffers are effectively created in COMMON (the debug layer ignores any other initial state for a buffer);
        // the first barrier promotes COMMON -> UAV for the statistics pass.
        ThrowIfFailed(m_pDev->CreateCommittedResource(&sumsHeap, D3D12_HEAP_FLAG_NONE, &sumsDesc,
            D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&m_postMotionSums)),
            "Failed to create the post-motion anchor sums");
        m_postMotionSums->SetName(L"FSR_PostMotionAnchor_Sums");
        {
            D3D12_RESOURCE_DESC resetDesc = sumsDesc;
            resetDesc.Flags = D3D12_RESOURCE_FLAG_NONE; // an upload-heap resource may not be UAV
            D3D12_HEAP_PROPERTIES resetHeap { D3D12_HEAP_TYPE_UPLOAD };
            ThrowIfFailed(m_pDev->CreateCommittedResource(&resetHeap, D3D12_HEAP_FLAG_NONE, &resetDesc,
                D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&m_postMotionSumsReset)),
                "Failed to create the post-motion anchor sums reset");
            m_postMotionSumsReset->SetName(L"FSR_PostMotionAnchor_SumsReset");
            const uint32_t zeros[4] {0u, 0u, 0u, 0u};
            void* mapped = nullptr;
            const D3D12_RANGE empty {0, 0};
            ThrowIfFailed(m_postMotionSumsReset->Map(0, &empty, &mapped), "Post-motion sums reset map");
            std::memcpy(mapped, zeros, sizeof(zeros));
            m_postMotionSumsReset->Unmap(0, nullptr);
        }
        m_postMotionSumsState = D3D12_RESOURCE_STATE_COMMON;
        return m_postMotionKeyLevel && m_postMotionKeyDepth && m_postMotionStats && m_postMotionRecalled &&
               m_postMotionGain && m_postMotionSums;
    }
    // The whole anchor: the host-side state machine decides whether this frame is inside the post-motion window,
    // whether a keyframe is due and in which priority order the ring is recalled; the passes measure and apply.
    void DispatchPostMotionAnchor(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        m_postMotionActive = false;
        if (!desc.PostMotionAnchor)
        {
            m_postMotionWasEnabled = false;
            return;
        }
        if ((desc.Flags & (uint32_t(ConvFlags::Debug))) != 0u) return;
        const uint32_t width = uint32_t(desc.RenderSize.x), height = uint32_t(desc.RenderSize.y);
        if (!width || !height) return;
        if (m_postMotionWidth && (m_postMotionWidth != width || m_postMotionHeight != height))
        {
            m_postMotionKeyLevel.Reset(); m_postMotionKeyDepth.Reset();
            m_postMotionStats.Reset(); m_postMotionRecalled.Reset(); m_postMotionGain.Reset();
            m_postMotionWidth = 0; m_postMotionHeight = 0; m_postMotionWasEnabled = false;
            m_postMotionState = PostMotionAnchorMath::State {};
        }
        if (!EnsurePostMotionAnchor(width, height)) return;
        m_postMotionWidth = width; m_postMotionHeight = height;
        // The conversion desc carries the transpose of the inverse view/projection and the previous view; the
        // anchor needs the forward matrices, which is exactly how the post-flick fix fills the same three.
        DirectX::XMFLOAT4X4 view {}, projection {}, previousView {};
        PostFlickMath::FillFromConversion(view, projection, previousView,
            {desc.InvViewMatrix, desc.InvProjMatrix, desc.PrevViewMatrix});
        PostMotionAnchorMath::StatsRecallConstants statsConstants {};
        PostMotionAnchorMath::GainConstants gainConstants {};
        const bool active = PostMotionAnchorMath::BuildFrame(m_postMotionState, view, projection, previousView,
            true, desc.PostMotionAnchorStrength, statsConstants, gainConstants);
        m_postMotionWasEnabled = true;
        if (!active) return;
        PostMotionAnchorMath::ApplyConstants applyConstants {};
        PostMotionAnchorMath::SetSize(statsConstants, gainConstants, applyConstants, width, height);
        auto& signals = m_out.Resources.Signals;
        const uint32_t cellsX = std::max(1u, width / 8u), cellsY = std::max(1u, height / 8u);
        // --- statistics and recall (1/8 resolution) ---
        ID3D12Resource* statsInputs[] {signals.DirectDiffuse.Get(), signals.IndirectSpecular.Get(),
            m_LinearDepth.Get(), m_out.Resources.Motion.Get(), m_postMotionKeyLevel.Get(),
            m_postMotionKeyDepth.Get()};
        // The ring is an SRV here and a UAV in the gain pass: one texture may not be both in one dispatch (the
        // fixture's debug layer rejects it), which is why the keyframe capture lives in the gain pass.
        ID3D12Resource* statsOutputs[] {m_postMotionStats.Get(), m_postMotionRecalled.Get(),
            m_postMotionSums.Get()};
        AddBarrier(cmdList, m_postMotionStats.Get(), kSrvState, kUavState);
        AddBarrier(cmdList, m_postMotionRecalled.Get(), kSrvState, kUavState);
        // Clear the frame-level sums with a copy from the persistent zero buffer: the ordering is explicit in the
        // command list (no in-dispatch reset racing the reads) and the copy is 16 bytes.
        AddBarrier(cmdList, m_postMotionSums.Get(), m_postMotionSumsState, D3D12_RESOURCE_STATE_COPY_DEST);
        cmdList->CopyBufferRegion(m_postMotionSums.Get(), 0, m_postMotionSumsReset.Get(), 0, 16);
        AddBarrier(cmdList, m_postMotionSums.Get(), D3D12_RESOURCE_STATE_COPY_DEST, kUavState);
        m_postMotionSumsState = kUavState;
        // The anchor's passes manage their own barriers (autoBarrierOutput = false): the sums buffer lives in the
        // UAV state across the pair, which the automatic SRV -> UAV assumption would get wrong, and the manual
        // transitions below are then the only ones (no duplicates).
        m_postMotionStatsRecallShader.Dispatch(cmdList, GetAsByteSpan(statsConstants), statsInputs, statsOutputs,
            {float(cellsX), float(cellsY)}, false);
        AddBarrier(cmdList, m_postMotionStats.Get(), kUavState, kSrvState);
        AddBarrier(cmdList, m_postMotionRecalled.Get(), kUavState, kSrvState);
        // --- the gain field and the keyframe capture (1/8 resolution) ---
        // The sums stay in the UAV state for the gain pass (it reads them through their own UAV and clears them):
        // an SRV and a UAV of one resource may not share a dispatch, which the fixture's debug layer rejects.
        ID3D12Resource* gainInputs[] {m_postMotionStats.Get(), m_postMotionRecalled.Get()};
        ID3D12Resource* gainOutputs[] {m_postMotionGain.Get(), m_postMotionKeyLevel.Get(),
            m_postMotionKeyDepth.Get(), m_postMotionSums.Get()};
        AddBarrier(cmdList, m_postMotionGain.Get(), kSrvState, kUavState);
        AddBarrier(cmdList, m_postMotionKeyLevel.Get(), kSrvState, kUavState);
        AddBarrier(cmdList, m_postMotionKeyDepth.Get(), kSrvState, kUavState);
        m_postMotionGainShader.Dispatch(cmdList, GetAsByteSpan(gainConstants), gainInputs, gainOutputs,
            {float(cellsX), float(cellsY)}, false);
        AddBarrier(cmdList, m_postMotionGain.Get(), kUavState, kSrvState);
        AddBarrier(cmdList, m_postMotionKeyLevel.Get(), kUavState, kSrvState);
        AddBarrier(cmdList, m_postMotionKeyDepth.Get(), kUavState, kSrvState);
        // --- apply (full resolution, in place on RR's input signals) ---
        // The signals are the bridge's denoiser inputs: shader-readable when the packing left them, and returned to
        // that state so the provider dispatch sees exactly what it always saw, scaled by the anchored level.
        AddBarrier(cmdList, signals.DirectDiffuse.Get(), kSrvState, kUavState);
        AddBarrier(cmdList, signals.IndirectSpecular.Get(), kSrvState, kUavState);
        ID3D12Resource* applyInputs[] {m_postMotionGain.Get()};
        ID3D12Resource* applyOutputs[] {signals.DirectDiffuse.Get(), signals.IndirectSpecular.Get()};
        m_postMotionApplyShader.Dispatch(cmdList, GetAsByteSpan(applyConstants), applyInputs, applyOutputs,
            {float(width), float(height)});
        AddBarrier(cmdList, signals.DirectDiffuse.Get(), kUavState, kSrvState);
        AddBarrier(cmdList, signals.IndirectSpecular.Get(), kUavState, kSrvState);
        m_postMotionActive = true;
    }

    void DispatchFlatDetail(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        m_flatDetailActive = false;
        m_flatTemporalActive = false;
        const auto debugMode = desc.Flags & uint32_t(CompFlags::DebugModeMask);
        const bool debugWeight = debugMode == uint32_t(CompFlags::DebugFlatDetail) || desc.RecoveryDebug == 4u;
        const bool debugReference = debugMode == uint32_t(CompFlags::DebugFlatDetailReference) || desc.RecoveryDebug == 5u;
        if (!desc.RecoveryV2 || (desc.Flags & uint32_t(CompFlags::RawSourceBlit)) != 0 ||
            ((desc.Flags & uint32_t(CompFlags::Debug)) != 0 && !debugWeight && !debugReference) ||
            (desc.RecoveryFlatAlbedoStrength <= 0.0f && !debugWeight && !debugReference))
        {
            ResetFlatTemporalHistory();
            return;
        }
        EnsureFlatDetail();
        FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::FlatDetail);
        // Copies and all descriptors keep their resources alive until this recording retires.
        auto retained = std::make_shared<std::array<ComPtr<ID3D12Resource>,3>>(
            std::array<ComPtr<ID3D12Resource>,3>{m_flatDetailTiles,m_flatDetailArguments,m_flatDetailReset});
        if (!ResTrack_Dx12::RetainComputeDispatch(m_pDev, cmdList, retained))
            throw std::runtime_error("Flat Detail copy lifetime tracking unavailable");
        AddBarrier(cmdList,m_flatDetailTiles.Get(),kSrvState,D3D12_RESOURCE_STATE_COPY_DEST);
        AddBarrier(cmdList,m_flatDetailArguments.Get(),D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT,D3D12_RESOURCE_STATE_COPY_DEST);
        cmdList->CopyBufferRegion(m_flatDetailTiles.Get(),0,m_flatDetailReset.Get(),0,16);
        cmdList->CopyBufferRegion(m_flatDetailArguments.Get(),0,m_flatDetailReset.Get(),16,12);
        AddBarrier(cmdList,m_flatDetailTiles.Get(),D3D12_RESOURCE_STATE_COPY_DEST,kUavState);
        AddBarrier(cmdList,m_flatDetailArguments.Get(),D3D12_RESOURCE_STATE_COPY_DEST,kUavState);
        auto& r = m_out.Resources;
        ID3D12Resource* classifyIn[] {r.Normals.Get(),r.SkipSignal.Get()};
        ID3D12Resource* classifyOut[] {m_flatDetailTiles.Get(),m_flatDetailArguments.Get()};
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassFlatClassify);
            m_flatDetailClassifyShader.Dispatch(cmdList,GetAsByteSpan(desc.DstTexSize),classifyIn,classifyOut,
                                                {desc.DstTexSize.x,desc.DstTexSize.y},false);
        }
        AddBarrier(cmdList,m_flatDetailTiles.Get(),kUavState,kSrvState);
        AddBarrier(cmdList,m_flatDetailArguments.Get(),kUavState,D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT);
        FlatDetail::Constants constants {
            .DstTexSize = desc.DstTexSize,
            .Modulation = {desc.SpecularAlbedoDemodulation,desc.DiffuseAlbedoModulation},
            .Strength = desc.RecoveryFlatAlbedoStrength,
            .Anchor = desc.RecoveryFlatAnchor,
            .Mix = desc.RecoveryFlatMix,
            .NoiseScale = FlatDetail::kNoiseScale,
            .Epsilon = FlatDetail::kEpsilon,
            .Radius = FlatDetail::kRadius,
            .Pass = 0,
            .Debug = debugReference ? 2u : (debugWeight ? 1u : 0u),
            .Flags = ((desc.Flags & uint32_t(CompFlags::ExtraSpecular)) != 0 ? 1u : 0u) |
                     ((desc.Flags & uint32_t(CompFlags::ExtraDiffuse)) != 0 ? 2u : 0u)
        };
        FlatDetail::Input in {{r.Signals.IndirectSpecular.Get(),r.Signals.DirectDiffuse.Get(),r.SpecAlbedo.Get(),
            r.DiffAlbedo.Get(),r.SkipSignal.Get(),r.Normals.Get(),m_LinearDepth.Get(),nullptr,nullptr,
            m_flatDetailTiles.Get(),nullptr,nullptr,nullptr,nullptr}};
        FlatDetail::Output out {{m_flatDetailReference[0].Get(),m_flatDetailStatistics[0].Get(),nullptr}};
        const auto dispatch = [&](ComputeState& shader) {
            shader.Dispatch(cmdList,GetAsByteSpan(constants),in.AsArray,out.AsArray,{0,0},true,nullptr,
                            m_flatDetailSignature.Get(),m_flatDetailArguments.Get());
        };
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassFlatSeed);
            dispatch(m_flatDetailSeedShader);
        }
        UINT source = 0;
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassFlatRefine);
            for (UINT pass = 0; pass < FlatDetail::kRefinementPasses; ++pass)
            {
                const UINT target = source ^ 1u;
                constants.Pass = pass;
                in.Resources.InReference = m_flatDetailReference[source].Get();
                in.Resources.InStatistics = m_flatDetailStatistics[source].Get();
                out.Resources.OutColor = m_flatDetailReference[target].Get();
                out.Resources.OutStatistics = m_flatDetailStatistics[target].Get();
                dispatch(m_flatDetailRefineShader);
                source = target;
            }
        }
        // The resolve writes into the ping-pong reference Refine no longer needs.
        in.Resources.InReference = ResolveFlatTemporal(cmdList, desc, m_flatDetailReference[source].Get(),
            m_flatDetailReference[source ^ 1u].Get(), constants.Flags);
        in.Resources.InStatistics = m_flatDetailStatistics[source].Get();
        // Only the temporal resolve writes the residual into the reference alpha.
        constants.TemporalDenoise = m_flatTemporalActive ? std::clamp(desc.RecoveryFlatTemporalDenoise, 0.0f, 2.0f) : 0.0f;
        // The base/Anchor moments are frozen before the in-place apply. No inter-tile read/write race.
        in.Resources.InComposed = CompositionColor();
        out = {{m_flatDetailBase.Get(),m_flatDetailMean.Get(),m_flatDetailVariance.Get()}};
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassFlatBase);
            dispatch(m_flatDetailBaseShader);
        }
        in.Resources.InComposed = nullptr;
        in.Resources.InBase = m_flatDetailBase.Get();
        in.Resources.InMean = m_flatDetailMean.Get();
        in.Resources.InVariance = m_flatDetailVariance.Get();
        out = {{CompositionColor(),nullptr,nullptr}};
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassFlatApply);
            dispatch(m_flatDetailApplyShader);
        }
        m_flatDetailConstants = constants;
        m_flatDetailActive = true;
    }

    ID3D12Resource* CompositionColor() const
    {
        if (m_skinOutputActive) return m_skinResult.Get();
        // Post-flick blotch fix (task 24 T2 c): while active the corrected composite is the composition output.
        if (m_postFlickActive) return m_postFlickOutput.Get();
        return m_recoveryOutputIndex < 0 ? m_compositionOutput.Get()
                                        : m_recoveryOutput[m_recoveryOutputIndex].Get();
    }

    // Recovery v2 lobe recovery (FSRDRecoveryLobe*.hlsl): references and noise histories ping-pong; the band
    // pyramid and the coarse corrections are rebuilt every frame. Allocated on first use at the maximum size.
    bool EnsureLobeRecovery()
    {
        if (m_lobeLevelA[0])
            return true;
        ScopedSkipHeapCapture skipHeapCapture {};
        if (!m_lobeAccumulateShader.m_pso)
        {
            m_lobeAccumulateShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDRecoveryLobeAccumulate_cso), sizeof(FSRDRecoveryLobeAccumulate_cso)},
                sizeof(RecoveryLobe::Constants), RecoveryLobeAccumulate::Input::kCount, RecoveryLobeAccumulate::Output::kCount,
                L"FSRD_RecoveryLobeAccumulate_Constants", RecoveryLobe::kBackBufferCount);
            m_lobeDownShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDRecoveryLobeDown_cso), sizeof(FSRDRecoveryLobeDown_cso)},
                sizeof(RecoveryLobe::Constants), RecoveryLobeDown::Input::kCount, RecoveryLobeDown::Output::kCount,
                L"FSRD_RecoveryLobeDown_Constants", RecoveryLobe::kBackBufferCount);
            m_lobeBandShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDRecoveryLobeBand_cso), sizeof(FSRDRecoveryLobeBand_cso)},
                sizeof(RecoveryLobe::Constants), RecoveryLobeBand::Input::kCount, RecoveryLobeBand::Output::kCount,
                L"FSRD_RecoveryLobeBand_Constants", RecoveryLobe::kBackBufferCount);
        }
        const auto create = [&](UINT width, UINT height, LPCWSTR name) {
            return CreateTexture2D(m_pDev, std::max(width, 1u), std::max(height, 1u), DXGI_FORMAT_R16G16B16A16_FLOAT, name, kSrvState);
        };
        for (UINT i = 0; i < 2; ++i)
        {
            m_lobeSpecular[i] = create(m_maxWidth, m_maxHeight, L"FSRD_RecoveryLobe_Specular");
            m_lobeDiffuse[i] = create(m_maxWidth, m_maxHeight, L"FSRD_RecoveryLobe_Diffuse");
            m_lobeGeometry[i] = create(m_maxWidth, m_maxHeight, L"FSRD_RecoveryLobe_Geometry");
            m_lobeGradient[i] = create(m_maxWidth, m_maxHeight, L"FSRD_RecoveryLobe_Gradient");
        }
        UINT width = m_maxWidth, height = m_maxHeight;
        for (UINT level = 0; level <= RecoveryLobe::kLevels; ++level)
        {
            m_lobeLevelA[level] = create(width, height, L"FSRD_RecoveryLobe_LevelA");
            m_lobeLevelB[level] = create(width, height, L"FSRD_RecoveryLobe_LevelB");
            m_lobeLevelC[level] = create(width, height, L"FSRD_RecoveryLobe_LevelC");
            if (level < RecoveryLobe::kLevels)
            {
                for (UINT i = 0; i < 2; ++i)
                    m_lobeNoise[i][level] = create(width, height, L"FSRD_RecoveryLobe_Noise");
                if (level > 0)
                {
                    m_lobeCorrectionS[level] = create(width, height, L"FSRD_RecoveryLobe_CorrectionS");
                    m_lobeCorrectionD[level] = create(width, height, L"FSRD_RecoveryLobe_CorrectionD");
                }
            }
            width = (width + 1) / 2;
            height = (height + 1) / 2;
        }
        for (auto& dummy : m_lobeDummy)
            dummy = create(1, 1, L"FSRD_RecoveryLobe_Unused");
        m_lobeValid = false;
        return true;
    }

    void ResetLobeRecovery()
    {
        for (auto* set : {&m_lobeSpecular, &m_lobeDiffuse, &m_lobeGeometry, &m_lobeGradient})
            for (auto& resource : *set) resource.Reset();
        for (auto& resource : m_lobeLevelA) resource.Reset();
        for (auto& resource : m_lobeLevelB) resource.Reset();
        for (auto& resource : m_lobeLevelC) resource.Reset();
        for (auto& resource : m_lobeCorrectionS) resource.Reset();
        for (auto& resource : m_lobeCorrectionD) resource.Reset();
        for (auto& set : m_lobeNoise)
            for (auto& resource : set) resource.Reset();
        for (auto& resource : m_lobeDummy) resource.Reset();
        m_lobeValid = false;
    }

    void DispatchRecoveryChain(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        // No copies and no rounding when the enabled pass list is empty.
        const bool active = desc.RecoveryV2 && (desc.Flags & (uint32_t(CompFlags::Debug) | uint32_t(CompFlags::RawSourceBlit) |
            uint32_t(CompFlags::DiffuseSignalDisabled) | uint32_t(CompFlags::SpecularSignalDisabled))) == 0 &&
            (desc.RecoverySpecularStrength > 0.0f || desc.RecoveryDiffuseStrength > 0.0f);
        if (!active)
        {
            m_lobeValid = m_recoveryHistoryValid = false;
            return;
        }
        if (!EnsureLobeRecovery())
            return;
        FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::Recovery);
        const UINT width = UINT(desc.DstTexSize.x), height = UINT(desc.DstTexSize.y);
        std::array<XMUINT2, RecoveryLobe::kLevels + 1> levels {};
        levels[0] = {width, height};
        for (UINT level = 1; level <= RecoveryLobe::kLevels; ++level)
            levels[level] = {(levels[level - 1].x + 1) / 2, (levels[level - 1].y + 1) / 2};
        const bool sameSize = m_lobeSize.x == desc.DstTexSize.x && m_lobeSize.y == desc.DstTexSize.y;
        const bool historyValid = m_lobeValid && m_recoveryHistoryValid && m_motionHistoryValid && sameSize;
        const UINT previous = m_lobeIndex, current = previous ^ 1u;
        auto& r = m_out.Resources;
        const bool extraDiffuse = (desc.Flags & uint32_t(CompFlags::ExtraDiffuse)) != 0;
        RecoveryLobe::Constants constants {};
        constants.DstTexSize = desc.DstTexSize;
        constants.LevelSize = {desc.DstTexSize.x, desc.DstTexSize.y, desc.DstTexSize.x, desc.DstTexSize.y};
        constants.Strength = {std::clamp(desc.RecoverySpecularStrength, 0.0f, 1.0f), std::clamp(desc.RecoveryDiffuseStrength, 0.0f, 1.0f),
                              0.0f, 0.0f};
        const auto anchor = [](float value) { return std::isfinite(value) ? std::clamp(value, 0.0f, 8.0f) : 0.0f; };
        const auto unit = [](float value) { return std::isfinite(value) ? std::clamp(value, 0.0f, 1.0f) : 0.0f; };
        constants.Blend = {unit(desc.RecoveryMix), anchor(desc.RecoveryAnchor), 0.0f, 0.0f};
        constants.Jitter = m_currentJitter;
        constants.Modulation = {desc.SpecularAlbedoDemodulation, desc.DiffuseAlbedoModulation};
        // A running mean, then about thirty frames of memory (a converged reference averages ~65 frames of RR's
        // input). Bands transfer with a Wiener weight at three noise variances; the sub-pixel gradient is fitted
        // from the eighth sample on (earlier it turned the first frames' noise into false detail).
        constants.Response = 0.03f;
        constants.Threshold = 3.0f;
        constants.MatureAge = 8.0f;
        constants.GradientAge = 8.0f;
        constants.Flags = (historyValid ? uint32_t(RecoveryLobe::HistoryValid) : 0u) |
                          (extraDiffuse ? uint32_t(RecoveryLobe::ExtraDiffuse) : 0u) |
                          ((desc.Flags & uint32_t(CompFlags::ExtraSpecular)) != 0 ? uint32_t(RecoveryLobe::NoSpecular) : 0u);
        constants.FrameIndex = m_lobeFrame++;
        constants.Debug = std::min(desc.RecoveryDebug, 2u);
        {
            RecoveryLobeAccumulate::Input in {{
                r.Signals.IndirectSpecular.Get(), r.Signals.DirectDiffuse.Get(), m_outputBuffer1.Get(), m_outputBuffer2.Get(),
                m_indirectDiffuseOutput.Get(), r.SpecAlbedo.Get(), r.DiffAlbedo.Get(), m_LinearDepth.Get(), r.Normals.Get(),
                r.Motion.Get(), r.SkipSignal.Get(), m_lobeSpecular[previous].Get(), m_lobeDiffuse[previous].Get(),
                m_lobeGeometry[previous].Get(), m_lobeGradient[previous].Get()}};
            RecoveryLobeAccumulate::Output out {{m_lobeSpecular[current].Get(), m_lobeDiffuse[current].Get(),
                m_lobeGeometry[current].Get(), m_lobeLevelA[0].Get(), m_lobeLevelB[0].Get(), m_lobeLevelC[0].Get(),
                m_lobeGradient[current].Get()}};
            {
                FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassRecoveryAccumulate);
                m_lobeAccumulateShader.Dispatch(cmdList, GetAsByteSpan(constants), in.AsArray, out.AsArray, {float(width), float(height)});
            }
        }
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassRecoveryDown);
            for (UINT level = 1; level <= RecoveryLobe::kLevels; ++level)
            {
                RecoveryLobe::Constants c = constants;
                c.Level = level;
                c.LevelSize = {float(levels[level].x), float(levels[level].y), float(levels[level - 1].x), float(levels[level - 1].y)};
                RecoveryLobeDown::Input in {{m_lobeLevelA[level - 1].Get(), m_lobeLevelB[level - 1].Get(), m_lobeLevelC[level - 1].Get()}};
                RecoveryLobeDown::Output out {{m_lobeLevelA[level].Get(), m_lobeLevelB[level].Get(), m_lobeLevelC[level].Get()}};
                m_lobeDownShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                          {float(levels[level].x), float(levels[level].y)});
            }
        }
        const int target = m_recoveryOutputIndex == 0 ? 1 : 0;
        {
            FSRDStageTimings::PassScope timing(m_stageTimings, FSRDStageTimings::PassRecoveryBand);
            for (int level = int(RecoveryLobe::kLevels) - 1; level >= 0; --level)
            {
                const bool coarsest = level == int(RecoveryLobe::kLevels) - 1, isFinal = level == 0;
                RecoveryLobe::Constants c = constants;
                c.Level = UINT(level);
                c.LevelSize = {float(levels[level].x), float(levels[level].y), float(levels[level + 1].x), float(levels[level + 1].y)};
                c.Flags |= (coarsest ? uint32_t(RecoveryLobe::Coarsest) : 0u) | (isFinal ? uint32_t(RecoveryLobe::Final) : 0u);
                RecoveryLobeBand::Input in {{
                    m_lobeLevelA[level].Get(), m_lobeLevelB[level].Get(), m_lobeLevelC[level].Get(),
                    m_lobeLevelA[level + 1].Get(), m_lobeLevelB[level + 1].Get(),
                    coarsest ? m_lobeDummy[0].Get() : m_lobeCorrectionS[level + 1].Get(),
                    coarsest ? m_lobeDummy[0].Get() : m_lobeCorrectionD[level + 1].Get(),
                    m_lobeNoise[previous][level].Get(), r.Motion.Get(), CompositionColor(),
                    r.SpecAlbedo.Get(), r.DiffAlbedo.Get(), r.SkipSignal.Get(),
                    m_outputBuffer1.Get(), m_outputBuffer2.Get(), m_indirectDiffuseOutput.Get()}};
                RecoveryLobeBand::Output out {{
                    isFinal ? m_lobeDummy[1].Get() : m_lobeCorrectionS[level].Get(),
                    isFinal ? m_lobeDummy[2].Get() : m_lobeCorrectionD[level].Get(),
                    m_lobeNoise[current][level].Get(),
                    isFinal ? m_recoveryOutput[target].Get() : m_lobeDummy[3].Get()}};
                m_lobeBandShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                          {float(levels[level].x), float(levels[level].y)});
            }
        }
        m_recoveryOutputIndex = target;
        m_lobeIndex = current;
        m_lobeSize = desc.DstTexSize;
        m_lobeValid = m_recoveryHistoryValid = true;
    }

    bool EnsureAdditiveConversionPipeline()
    {
        if (m_additiveConvPso)
            return true;
        if (m_additiveConvPsoFailed)
            return false;

        ScopedSkipHeapCapture skipHeapCapture {};
        D3D12_COMPUTE_PIPELINE_STATE_DESC psoDesc = {};
        psoDesc.pRootSignature = m_convShader.m_rootSig.Get();
        psoDesc.CS = { FSRDInputConvAdditive_cso, sizeof(FSRDInputConvAdditive_cso) };
        ComPtr<ID3D12PipelineState> additivePso;
        const HRESULT result = m_pDev->CreateComputePipelineState(&psoDesc, IID_PPV_ARGS(&additivePso));
        if (FAILED(result))
        {
            m_additiveConvPsoFailed = true;
            LOG_ERROR("FSRD additive conversion pipeline failed to initialize (HRESULT: {}); disable Additive Light Split to use the original pipeline",
                      static_cast<uint32_t>(result));
            return false;
        }
        m_additiveConvPso = std::move(additivePso);
        return true;
    }

    void EnsureSkinShaders()
    {
        if (m_skinConvShader.m_pso) return;
        m_skinConvShader.Initialize(m_pDev,
            {reinterpret_cast<const byte*>(FSRDInputConvSkin_cso), sizeof(FSRDInputConvSkin_cso)},
            sizeof(SkinConversion::Constants), SkinConversion::kInputCount, Conversion::Output::kCount,
            L"FSRD_SkinConversion", 3);
        m_sssPrepareShader.Initialize(m_pDev,
            {reinterpret_cast<const byte*>(FSRDSssPrepare_cso), sizeof(FSRDSssPrepare_cso)},
            sizeof(SssPrepare::Constants), SssPrepare::Input::kCount, SssPrepare::Output::kCount,
            L"FSRD_SssPrepare", 3);
        m_sssBlurShader.Initialize(m_pDev,
            {reinterpret_cast<const byte*>(FSRDSssBlur_cso), sizeof(FSRDSssBlur_cso)},
            sizeof(SssBlur::Constants), SssBlur::Input::kCount, SssBlur::Output::kCount,
            L"FSRD_SssBlur", 3);
        m_skinPrefilterShader.Initialize(m_pDev,
            {reinterpret_cast<const byte*>(FSRDSkinPrefilter_cso), sizeof(FSRDSkinPrefilter_cso)},
            sizeof(SkinPrefilter::Constants), SkinPrefilter::Input::kCount, SkinPrefilter::Output::kCount,
            L"FSRD_SkinPrefilter", 3);
    }

    void EnsureSkinBoundsShaders()
    {
        if (!m_skinBoundsConvShader.m_pso)
            m_skinBoundsConvShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDInputConvSkinBounds_cso), sizeof(FSRDInputConvSkinBounds_cso)},
                sizeof(SkinConversion::Constants), SkinConversion::kInputCount, SkinConversionBounds::kOutputCount,
                L"FSRD_SkinConversionBounds", 3);
        if (!m_skinBoundsShader.m_pso)
            m_skinBoundsShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDSkinBounds_cso), sizeof(FSRDSkinBounds_cso)},
                sizeof(SkinPrefilter::Constants), SkinBounds::Input::kCount, SkinBounds::Output::kCount,
                L"FSRD_SkinBounds", 3);
        if (!m_skinTiledPrefilterShader.m_pso)
            m_skinTiledPrefilterShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDSkinPrefilterTiled_cso), sizeof(FSRDSkinPrefilterTiled_cso)},
                sizeof(SkinPrefilter::Constants), SkinTiledPrefilter::Input::kCount, SkinTiledPrefilter::Output::kCount,
                L"FSRD_SkinTiledPrefilter", 3);
    }

    void EnsureFusedSssShaders()
    {
        if (!m_skinFusedConvShader.m_pso)
            m_skinFusedConvShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDInputConvSkinFused_cso), sizeof(FSRDInputConvSkinFused_cso)},
                sizeof(SkinConversion::Constants), SkinFusedConversion::kInputCount,
                SkinFusedConversion::kOutputCount, L"FSRD_SkinFusedConversion", 3);
        if (!m_sssKernelShader.m_pso)
            m_sssKernelShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDSssKernel_cso), sizeof(FSRDSssKernel_cso)},
                sizeof(SssBlur::Constants), SssKernel::Input::kCount, SssKernel::Output::kCount,
                L"FSRD_SssKernel", 3);
        if (!m_sssTiledBlurShader.m_pso)
            m_sssTiledBlurShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDSssBlurTiled_cso), sizeof(FSRDSssBlurTiled_cso)},
                sizeof(SssBlur::Constants), SssTiledBlur::Input::kCount, SssBlur::Output::kCount,
                L"FSRD_SssBlurTiled", 3);
    }

    void PrepareSkin(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        m_skinOutputActive = false;
        m_skinFused = false;
        auto* guide = desc.Resources.InSssGuide;
        const auto guideDesc = guide ? guide->GetDesc() : D3D12_RESOURCE_DESC{};
        const bool guideValid = FSRD::CompatibleSkinInput(guide != nullptr, guideDesc,
            FSRD::GetViewFormat(guideDesc.Format), desc.SssGuideBase.x, desc.SssGuideBase.y,
            UINT(desc.RenderSize.x), UINT(desc.RenderSize.y), true);
        m_skinMode = guideValid ? std::min(desc.SkinMode, 2u) : 0u;
        m_skinDebug = desc.SkinDebug;
        m_skinRadiusMm = desc.SssRadiusMm; m_skinStrength = desc.SssStrength;
        m_skinFalloff = desc.SssFalloff; m_skinSigma = desc.SkinSigma;
        if (m_skinMode == 0u) return;
        EnsureSkinShaders();
        if (!m_skinPrepared)
        {
            const auto color = [&](LPCWSTR name) {
                return CreateTexture2D(m_pDev, m_maxWidth, m_maxHeight, DXGI_FORMAT_R16G16B16A16_FLOAT, name, kSrvState);
            };
            m_skinPrepared = color(L"FSRD_SssPrepared");
            m_skinGuide = CreateTexture2D(m_pDev, m_maxWidth, m_maxHeight, DXGI_FORMAT_R32_FLOAT,
                                          L"FSRD_SssGuide", kSrvState);
            m_skinBlur = color(L"FSRD_SssBlur"); m_skinResult = color(L"FSRD_SssResult");
            m_skinDiffuse = color(L"FSRD_SkinDiffuse");
        }
        if (m_skinMode == 2u)
        {
            EnsureSkinBoundsShaders();
            if (!m_skinBounds8)
            {
                const auto size = SkinBoundsExtent(m_maxWidth, m_maxHeight, 8u);
                m_skinBounds8 = CreateTexture2D(m_pDev, size.x, size.y,
                    DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_SkinBounds8", kSrvState);
            }
            if (!m_skinBounds16)
            {
                const auto size = SkinBoundsExtent(m_maxWidth, m_maxHeight, 16u);
                m_skinBounds16 = CreateTexture2D(m_pDev, size.x * 2u, size.y,
                    DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_SkinBounds16", kSrvState);
            }
            return; // The prefilter consumes the original guide directly.
        }
        const XMMATRIX projection = XMMatrixInverse(nullptr, XMLoadFloat4x4(&desc.InvProjMatrix));
        XMFLOAT4X4 proj; XMStoreFloat4x4(&proj, projection);
        m_skinFocalPixels = 0.5f * desc.RenderSize.y * std::abs(proj._22);
        bool capture = m_gameTraceCaptureRequested || bool(m_additiveCapture);
        {
            std::lock_guard lock(g_additiveTraceMutex);
            capture = capture || g_additiveTraceBusy || g_additiveTraceRequest.has_value();
        }
        // InputBase4.zw carries the raw-depth origin in the fused ABI. A bound
        // diffuse-hit source can share it only when its own origin agrees.
        const bool diffuseBaseMatches = desc.DiffuseHitDistanceMode == 0u ||
            desc.Resources.InDiffuseHitDistance == nullptr ||
            (desc.InputBase4.z == desc.ColorDepthBase.z && desc.InputBase4.w == desc.ColorDepthBase.w);
        const bool basesMatch = desc.ColorDepthBase.x == desc.InputBase0.x &&
            desc.ColorDepthBase.y == desc.InputBase0.y && diffuseBaseMatches;
        const bool depthSourceValid = (desc.Flags & uint32_t(ConvFlags::TitleLinearDepth)) == 0u ||
            desc.Resources.InTitleLinearDepth != nullptr;
        m_skinFused = CanFuseSssInput(m_skinMode,
            (desc.Flags & uint32_t(ConvFlags::InputChroma)) != 0u,
            (desc.Flags & uint32_t(ConvFlags::Debug)) != 0u || desc.SkinDebug != 0u,
            capture, basesMatch, depthSourceValid);
        if (m_skinFused)
        {
            EnsureFusedSssShaders();
            if (!m_skinBounds8)
            {
                const auto size = SkinBoundsExtent(m_maxWidth, m_maxHeight, 8u);
                m_skinBounds8 = CreateTexture2D(m_pDev, size.x, size.y,
                    DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_SkinBounds8", kSrvState);
            }
            if (!m_sssKernel)
            {
                const auto size = SssKernelExtent(m_maxWidth, m_maxHeight);
                m_sssKernel = CreateTexture2D(m_pDev, size.x, size.y,
                    DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_SssKernel", kSrvState);
            }
            return;
        }
        SssPrepare::Constants c {
            .InvProjMatrix = desc.InvProjMatrix, .DstTexSize = desc.RenderSize,
            .ColorDepthBase = desc.ColorDepthBase,
            .AlbedoBase = {desc.InputBase2.z, desc.InputBase2.w, desc.InputBase3.x, desc.InputBase3.y},
            .GuideBiasBase = {desc.SssGuideBase.x, desc.SssGuideBase.y, desc.InputBase3.z, desc.InputBase3.w},
            .TitleDepthBase = desc.TitleLinearDepthBase,
            .CurrentJitter = {desc.JitterOffsets.x, desc.JitterOffsets.y},
            .NearPlane = desc.NearPlane, .FarPlane = desc.FarPlane,
            .BiasStrength = desc.BiasMaskStrength,
            .Flags = desc.Flags | (desc.Resources.InBiasMask ? uint32_t(ConvFlags::HasBiasMask) : 0u),
            .Mode = m_skinMode
        };
        SssPrepare::Input in {.Resources = {desc.Resources.InColor, desc.Resources.InDepth,
            desc.Resources.InDiffAlbedo, desc.Resources.InSpecAlbedo, desc.Resources.InSssGuide,
            desc.Resources.InBiasMask, desc.Resources.InTitleLinearDepth}};
        SssPrepare::Output out {.Resources = {m_skinPrepared.Get(), m_skinGuide.Get()}};
        FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::SkinPrepare);
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinPrepare);
            m_sssPrepareShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                       {desc.RenderSize.x, desc.RenderSize.y});
        }
    }

    void FilterSkinDiffuse(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        if (m_skinMode != 2u) return;
        const auto width = UINT(desc.RenderSize.x), height = UINT(desc.RenderSize.y);
        SkinPrefilter::Constants c {.DstTexSize = desc.RenderSize, .Sigma = m_skinSigma,
            .GuideBase = desc.SssGuideBase};
        FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::SkinPrefilter);
        SkinBounds::Input boundsIn {.Resources = {m_skinBounds8.Get()}};
        SkinBounds::Output boundsOut {.Resources = {m_skinBounds16.Get()}};
        const auto boundsSize = SkinBoundsExtent(width, height, 16u);
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinPrefilterBounds);
            m_skinBoundsShader.Dispatch(cmdList, GetAsByteSpan(c), boundsIn.AsArray, boundsOut.AsArray,
                                       {float(boundsSize.x), float(boundsSize.y)});
        }
        SkinTiledPrefilter::Input in {.Resources = {m_out.Resources.Signals.DirectDiffuse.Get(),
            desc.Resources.InSssGuide, m_LinearDepth.Get(), m_out.Resources.Normals.Get(), m_skinBounds16.Get()}};
        SkinTiledPrefilter::Output out {.Resources = {m_skinBlur.Get()}};
        auto dispatch = SkinPrefilterDispatch(width, height, false);
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinPrefilterH);
            m_skinTiledPrefilterShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                               {float(dispatch.x), float(dispatch.y)});
        }
        c.Vertical = 1u;
        in.Resources.InDiffuse = m_skinBlur.Get();
        out.Resources.OutDiffuse = m_skinDiffuse.Get();
        dispatch = SkinPrefilterDispatch(width, height, true);
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinPrefilterV);
            m_skinTiledPrefilterShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                               {float(dispatch.x), float(dispatch.y)});
        }
        std::swap(m_skinDiffuse, m_out.Resources.Signals.DirectDiffuse);
        if (desc.SkinDebug == 3u)
            Blit(cmdList, m_out.Resources.Signals.DirectDiffuse.Get(), m_out.Resources.Signals.IndirectSpecular.Get(),
                 {desc.RenderSize.x, desc.RenderSize.y}, {desc.RenderSize.x, desc.RenderSize.y}, {});
    }

    void ReblurSkin(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        if (m_skinMode != 1u || m_skinStrength <= 0.0f ||
            (desc.Flags & (uint32_t(CompFlags::Debug) | uint32_t(CompFlags::RawSourceBlit))) != 0u) return;
        FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::SkinReblur);
        ID3D12Resource* original = CompositionColor();
        SssBlur::Constants c {.DstTexSize = desc.DstTexSize,
            .SigmaScale = m_skinRadiusMm * 0.001f * m_skinFocalPixels,
            .RadiusMeters = m_skinRadiusMm * 0.001f, .Strength = m_skinStrength, .Falloff = m_skinFalloff};
        if (m_skinFused)
        {
            const auto width = UINT(desc.DstTexSize.x), height = UINT(desc.DstTexSize.y);
            SssKernel::Input kernelIn {.Resources = {m_skinBounds8.Get(), m_LinearDepth.Get()}};
            SssKernel::Output kernelOut {.Resources = {m_sssKernel.Get()}};
            auto dispatch = SssKernelDispatch(width, height);
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinReblurKernel);
                m_sssKernelShader.Dispatch(cmdList, GetAsByteSpan(c), kernelIn.AsArray, kernelOut.AsArray,
                                          {float(dispatch.x), float(dispatch.y)});
            }
            SssTiledBlur::Input in {.Resources = {original, m_skinGuide.Get(), m_LinearDepth.Get(),
                original, m_sssKernel.Get()}};
            SssBlur::Output out {.Resources = {m_skinBlur.Get()}};
            dispatch = SssBlurDispatch(width, height, false);
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinReblurH);
                m_sssTiledBlurShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                             {float(dispatch.x), float(dispatch.y)});
            }
            c.Vertical = 1u;
            in.Resources.InColor = m_skinBlur.Get(); out.Resources.OutColor = m_skinResult.Get();
            dispatch = SssBlurDispatch(width, height, true);
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinReblurV);
                m_sssTiledBlurShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                             {float(dispatch.x), float(dispatch.y)});
            }
            m_skinOutputActive = true;
            return;
        }
        SssBlur::Input in {.Resources = {original, m_skinGuide.Get(), m_LinearDepth.Get(), original}};
        SssBlur::Output out {.Resources = {m_skinBlur.Get()}};
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinReblurH);
            m_sssBlurShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                    {desc.DstTexSize.x, desc.DstTexSize.y});
        }
        c.Vertical = 1u; in.Resources.InColor = m_skinBlur.Get(); out.Resources.OutColor = m_skinResult.Get();
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassSkinReblurV);
            m_sssBlurShader.Dispatch(cmdList, GetAsByteSpan(c), in.AsArray, out.AsArray,
                                    {desc.DstTexSize.x, desc.DstTexSize.y});
        }
        m_skinOutputActive = true;
    }

    // Albedo guide stabilisation (FSRDAlbedoStabilise.hlsl). Runs after packing on its outputs: the stabilised
    // guides and the matching rescaled lighting go to spare textures that are then swapped in, so everything
    // after this point (RR, skin, composition, captures) sees one consistent pair.
    void StabiliseAlbedo(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        const uint32_t mode = (desc.Flags & uint32_t(ConvFlags::Debug)) != 0u ? 0u : std::min(desc.AlbedoStabilisation, 2u);
        m_albedoStabActive = false;
        if (mode == 0u)
        {
            m_albedoStabValid = false;
            return;
        }
        if (!m_albedoStabShader.m_pso)
            m_albedoStabShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDAlbedoStabilise_cso), sizeof(FSRDAlbedoStabilise_cso)},
                32, 10, 7, L"FSRD_AlbedoStabilise");
        if (!m_albedoStabSpareSpecAlbedo)
        {
            const auto create = [&](DXGI_FORMAT format, LPCWSTR name) {
                return CreateTexture2D(m_pDev, m_maxWidth, m_maxHeight, format, name, kSrvState);
            };
            for (UINT i = 0; i < 2; ++i)
            {
                m_albedoStabSpec[i] = create(DXGI_FORMAT_R16G16B16A16_FLOAT, L"FSRD_AlbedoStab_Specular");
                m_albedoStabDiff[i] = create(DXGI_FORMAT_R16G16B16A16_FLOAT, L"FSRD_AlbedoStab_Diffuse");
                m_albedoStabNormal[i] = create(DXGI_FORMAT_R16G16_FLOAT, L"FSRD_AlbedoStab_Normal");
            }
            m_albedoStabSpareSpecAlbedo = create(FSRDFormats::SpecAlbedo, L"FSRD_AlbedoStab_SpecAlbedo");
            m_albedoStabSpareDiffAlbedo = create(FSRDFormats::DiffAlbedo, L"FSRD_AlbedoStab_DiffAlbedo");
            m_albedoStabSpareSpecSignal = create(FSRDFormats::IndirectSpecular, L"FSRD_AlbedoStab_SpecSignal");
            m_albedoStabSpareDiffSignal = create(FSRDFormats::DirectDiffuse, L"FSRD_AlbedoStab_DiffSignal");
            m_albedoStabValid = false;
        }
        const bool reset = !m_albedoStabValid || !desc.MotionHistoryValid || mode != m_albedoStabMode ||
            memcmp(&m_albedoStabSize, &desc.RenderSize, sizeof(desc.RenderSize)) != 0;
        struct Constants { XMFLOAT4 DstTexSize; float Rate, DivisorFloor, DepthTolerance; uint32_t Flags; };
        static_assert(sizeof(Constants) == 32);
        const Constants c {desc.RenderSize, std::clamp(desc.AlbedoStabilisationRate, 1.0f / 32.0f, 1.0f),
            desc.DemodDivisorFloor, 0.03f,
            (reset ? 1u : 0u) | (mode == 2u ? 2u : 0u) | (desc.AlbedoStabilisationClamp ? 4u : 0u)};
        const uint32_t previous = m_albedoStabIndex, current = previous ^ 1u;
        auto& r = m_out.Resources;
        const auto inputs = std::to_array<ID3D12Resource*>({r.SpecAlbedo.Get(), r.DiffAlbedo.Get(),
            r.Signals.IndirectSpecular.Get(), r.Signals.DirectDiffuse.Get(), r.Motion.Get(), m_LinearDepth.Get(),
            r.Normals.Get(), m_albedoStabSpec[previous].Get(), m_albedoStabDiff[previous].Get(),
            m_albedoStabNormal[previous].Get()});
        auto outputs = std::to_array<ID3D12Resource*>({m_albedoStabSpec[current].Get(), m_albedoStabDiff[current].Get(),
            m_albedoStabNormal[current].Get(), m_albedoStabSpareSpecAlbedo.Get(), m_albedoStabSpareDiffAlbedo.Get(),
            m_albedoStabSpareSpecSignal.Get(), m_albedoStabSpareDiffSignal.Get()});
        {
            FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::AlbedoStabilisation);
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassAlbedoStabilise);
                m_albedoStabShader.Dispatch(cmdList, GetAsByteSpan(c), inputs, outputs, {desc.RenderSize.x, desc.RenderSize.y});
            }
        }
        std::swap(m_albedoStabSpareSpecAlbedo, r.SpecAlbedo);
        std::swap(m_albedoStabSpareDiffAlbedo, r.DiffAlbedo);
        std::swap(m_albedoStabSpareSpecSignal, r.Signals.IndirectSpecular);
        std::swap(m_albedoStabSpareDiffSignal, r.Signals.DirectDiffuse);
        m_albedoStabIndex = current;
        m_albedoStabMode = mode;
        m_albedoStabSize = desc.RenderSize;
        m_albedoStabValid = true;
        m_albedoStabActive = true;
    }

    // Lighting-consistent guides (FSRDFogStats/Kappa/Rank/Smooth/Target/Route.hlsl), after stabilisation. Kappa, the
    // share of the guides' texture the image carries, is measured on the packing shader's own pair against the
    // guides' history from earlier frames (CP77's guides flicker with the image inside a frame); the pair handed on
    // (stabilised or not) is rewritten into spares that are swapped in, energy-exact per channel, so RR, skin,
    // composition and captures all see the same pair.
    void FogGuides(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        if (!desc.FogGuides || (desc.Flags & uint32_t(ConvFlags::Debug)) != 0u)
        {
            m_fogValid = false;
            return;
        }
        if (!m_fogStatsShader.m_pso)
        {
            m_fogStatsShader.Initialize(m_pDev, {reinterpret_cast<const byte*>(FSRDFogStats_cso), sizeof(FSRDFogStats_cso)},
                                        sizeof(FogStats::Constants), FogStats::Input::kCount, FogStats::Output::kCount,
                                        L"FSRD_FogStats");
            m_fogKappaShader.Initialize(m_pDev, {reinterpret_cast<const byte*>(FSRDFogKappa_cso), sizeof(FSRDFogKappa_cso)},
                                        sizeof(FogKappa::Constants), FogKappa::Input::kCount, FogKappa::Output::kCount,
                                        L"FSRD_FogKappa");
            m_fogRankShader.Initialize(m_pDev, {reinterpret_cast<const byte*>(FSRDFogRank_cso), sizeof(FSRDFogRank_cso)},
                                       sizeof(FogRank::Constants), FogRank::Input::kCount, FogRank::Output::kCount,
                                       L"FSRD_FogRank");
            m_fogSmoothShader.Initialize(m_pDev, {reinterpret_cast<const byte*>(FSRDFogSmooth_cso), sizeof(FSRDFogSmooth_cso)},
                                         sizeof(FogSmooth::Constants), FogSmooth::Input::kCount, FogSmooth::Output::kCount,
                                         L"FSRD_FogSmooth");
            m_fogTargetShader.Initialize(m_pDev, {reinterpret_cast<const byte*>(FSRDFogTarget_cso), sizeof(FSRDFogTarget_cso)},
                                         sizeof(FogTarget::Constants), FogTarget::Input::kCount, FogTarget::Output::kCount,
                                         L"FSRD_FogTarget");
            m_fogRouteShader.Initialize(m_pDev, {reinterpret_cast<const byte*>(FSRDFogRoute_cso), sizeof(FSRDFogRoute_cso)},
                                        sizeof(FogRoute::Constants), FogRoute::Input::kCount, FogRoute::Output::kCount,
                                        L"FSRD_FogRoute");
        }
        const UINT maxTilesX = (m_maxWidth + 7) / 8, maxTilesY = (m_maxHeight + 7) / 8;
        if (!m_fogSpareSpecAlbedo)
        {
            const auto tile = [&](DXGI_FORMAT format, LPCWSTR name) {
                return CreateTexture2D(m_pDev, maxTilesX, maxTilesY, format, name, kSrvState);
            };
            for (UINT i = 0; i < 2; ++i)
            {
                m_fogA[i] = tile(DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_Fog_A");
                m_fogB[i] = tile(DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_Fog_B");
                m_fogC[i] = tile(DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_Fog_C");
            }
            m_fogG = tile(DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_Fog_G");
            m_fogH = tile(DXGI_FORMAT_R32G32B32A32_FLOAT, L"FSRD_Fog_H");
            m_fogKappaRaw = tile(DXGI_FORMAT_R32_FLOAT, L"FSRD_Fog_KappaRaw");
            m_fogKappaRank = tile(DXGI_FORMAT_R32_FLOAT, L"FSRD_Fog_KappaRank");
            m_fogKappa = tile(DXGI_FORMAT_R32_FLOAT, L"FSRD_Fog_Kappa");
            m_fogTargetSpec = tile(DXGI_FORMAT_R16G16B16A16_FLOAT, L"FSRD_Fog_TargetSpec");
            m_fogTargetDiff = tile(DXGI_FORMAT_R16G16B16A16_FLOAT, L"FSRD_Fog_TargetDiff");
            const auto full = [&](DXGI_FORMAT format, LPCWSTR name) {
                return CreateTexture2D(m_pDev, m_maxWidth, m_maxHeight, format, name, kSrvState);
            };
            m_fogSpareSpecAlbedo = full(FSRDFormats::SpecAlbedo, L"FSRD_Fog_SpecAlbedo");
            m_fogSpareDiffAlbedo = full(FSRDFormats::DiffAlbedo, L"FSRD_Fog_DiffAlbedo");
            m_fogSpareSpecSignal = full(FSRDFormats::IndirectSpecular, L"FSRD_Fog_SpecSignal");
            m_fogSpareDiffSignal = full(FSRDFormats::DirectDiffuse, L"FSRD_Fog_DiffSignal");
            // Per-pixel guide history for the kappa regressor: luminance EMA of both guides, log depth, valid.
            for (UINT i = 0; i < 2; ++i)
                m_fogGuides[i] = full(DXGI_FORMAT_R10G10B10A2_UNORM, L"FSRD_Fog_GuideHistory");
            m_fogValid = false;
        }
        const bool reset = !m_fogValid || !desc.MotionHistoryValid ||
            memcmp(&m_fogSize, &desc.RenderSize, sizeof(desc.RenderSize)) != 0;
        const XMFLOAT2 tiles {std::ceil(desc.RenderSize.x / 8.0f), std::ceil(desc.RenderSize.y / 8.0f)};
        const uint32_t previous = m_fogIndex, current = previous ^ 1u;
        auto& r = m_out.Resources;
        // The packing shader's pair: in the stabilisation spares when stabilisation replaced it this frame.
        ID3D12Resource* origSpec = m_albedoStabActive ? m_albedoStabSpareSpecAlbedo.Get() : r.SpecAlbedo.Get();
        ID3D12Resource* origDiff = m_albedoStabActive ? m_albedoStabSpareDiffAlbedo.Get() : r.DiffAlbedo.Get();
        ID3D12Resource* origSpecSignal = m_albedoStabActive ? m_albedoStabSpareSpecSignal.Get() : r.Signals.IndirectSpecular.Get();
        ID3D12Resource* origDiffSignal = m_albedoStabActive ? m_albedoStabSpareDiffSignal.Get() : r.Signals.DirectDiffuse.Get();

        // Constants shared with fsrd_fog_reference.py (validated with real AMD RR on fog, night, water, stairs,
        // reveal and turn captures).
        constexpr float kRate = 1.0f / 16.0f, kFillRadius = 4.0f, kFillSigma = kFillRadius / 1.5f;
        constexpr float kNear = 8.0f, kFar = 60.0f;
        // Guide history: rate, relative depth tolerance, and the log-depth range its 10-bit depth spans.
        constexpr float kGuideRate = 1.0f / 8.0f, kGuideDepthTolerance = 0.03f;
        constexpr float kGuideDepthMin = 1e-3f, kGuideDepthMax = 1e5f;
        FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::FogGuides);
        {
            // Motion is canonical unjittered previous-UV minus current-UV. Fog runs before
            // the composition's history delta is updated, so use this frame's descriptor.
            const XMFLOAT2 historyJitterDelta {desc.JitterOffsets.z - desc.JitterOffsets.x,
                                               desc.JitterOffsets.w - desc.JitterOffsets.y};
            // The history stores depth as normalised log depth; the tolerance is compared in that domain.
            const float invLogZRange = 1.0f / std::log(kGuideDepthMax / kGuideDepthMin);
            const FogStats::Constants c {desc.RenderSize, tiles, kRate, desc.DemodDivisorFloor, 0.1f,
                                         reset ? 1u : 0u, historyJitterDelta, kGuideRate,
                                         std::log1p(kGuideDepthTolerance) * invLogZRange, std::log(kGuideDepthMin),
                                         invLogZRange};
            const FogStats::Input inputs {{origSpec, origDiff, origSpecSignal, origDiffSignal,
                r.SpecAlbedo.Get(), r.DiffAlbedo.Get(), m_LinearDepth.Get(), r.Motion.Get(),
                m_fogA[previous].Get(), m_fogB[previous].Get(), m_fogC[previous].Get(), m_fogGuides[previous].Get()}};
            FogStats::Output outputs {{m_fogA[current].Get(), m_fogB[current].Get(), m_fogC[current].Get(),
                m_fogG.Get(), m_fogH.Get(), m_fogGuides[current].Get()}};
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassFogStats);
                m_fogStatsShader.Dispatch(cmdList, GetAsByteSpan(c), inputs.AsArray, outputs.AsArray,
                                          {desc.RenderSize.x, desc.RenderSize.y});
            }
        }
        {
            const FogKappa::Constants c {tiles, 0.35f, 1.0f, 2.0f, 0.0f, 144.0f, 64.0f * 2.0f * 3.14159265f * kFillSigma * kFillSigma,
                               0.005f, 0.015f, kFillSigma, 0.6f, int32_t(kFillRadius), {}};
            const FogKappa::Input inputs {{m_fogA[current].Get(), m_fogB[current].Get(), m_fogC[current].Get()}};
            FogKappa::Output outputs {{m_fogKappaRaw.Get()}};
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassFogKappa);
                m_fogKappaShader.Dispatch(cmdList, GetAsByteSpan(c), inputs.AsArray, outputs.AsArray, tiles);
            }
        }
        {
            // Median over 5x5 same-depth tiles: lone low-kappa tiles (cars, kerbs, foliage edges, where the tile
            // model fails) are not fog; flattening them blurred and smeared those objects through RR.
            const FogRank::Constants c {tiles, 0.3f, 50.0f, 2, {}};
            const FogRank::Input inputs {{m_fogKappaRaw.Get(), m_fogA[current].Get(), m_fogC[current].Get()}};
            FogRank::Output outputs {{m_fogKappaRank.Get()}};
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassFogRank);
                m_fogRankShader.Dispatch(cmdList, GetAsByteSpan(c), inputs.AsArray, outputs.AsArray, tiles);
            }
        }
        {
            const FogSmooth::Constants c {tiles, 3.0f, 0.6f, 6, {}};
            const FogSmooth::Input inputs {{m_fogKappaRank.Get(), m_fogA[current].Get(), m_fogC[current].Get()}};
            FogSmooth::Output outputs {{m_fogKappa.Get()}};
            // The flatten target follows in the same timing slot (the pass mask is full).
            const FogTarget::Constants t {tiles, 4.0f, 1.0f, 8, {}};
            const FogTarget::Input targetInputs {{m_fogKappa.Get(), m_fogG.Get(), m_fogH.Get()}};
            FogTarget::Output targetOutputs {{m_fogTargetSpec.Get(), m_fogTargetDiff.Get()}};
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassFogSmooth);
                m_fogSmoothShader.Dispatch(cmdList, GetAsByteSpan(c), inputs.AsArray, outputs.AsArray, tiles);
                m_fogTargetShader.Dispatch(cmdList, GetAsByteSpan(t), targetInputs.AsArray, targetOutputs.AsArray, tiles);
            }
        }
        {
            const FogRoute::Constants c {desc.RenderSize, tiles, desc.DemodDivisorFloor, std::log(kNear), 1.0f / std::log(kFar / kNear),
                               0.0f, 0u, 0.0f};
            const FogRoute::Input inputs {{r.SpecAlbedo.Get(), r.DiffAlbedo.Get(),
                r.Signals.IndirectSpecular.Get(), r.Signals.DirectDiffuse.Get(), m_LinearDepth.Get(), m_fogKappa.Get(),
                m_fogTargetSpec.Get(), m_fogTargetDiff.Get(), m_fogGuides[current].Get()}};
            FogRoute::Output outputs {{m_fogSpareSpecAlbedo.Get(), m_fogSpareDiffAlbedo.Get(),
                m_fogSpareSpecSignal.Get(), m_fogSpareDiffSignal.Get()}};
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassFogRoute);
                m_fogRouteShader.Dispatch(cmdList, GetAsByteSpan(c), inputs.AsArray, outputs.AsArray,
                                          {desc.RenderSize.x, desc.RenderSize.y});
            }
        }
        std::swap(m_fogSpareSpecAlbedo, r.SpecAlbedo);
        std::swap(m_fogSpareDiffAlbedo, r.DiffAlbedo);
        std::swap(m_fogSpareSpecSignal, r.Signals.IndirectSpecular);
        std::swap(m_fogSpareDiffSignal, r.Signals.DirectDiffuse);
        m_fogIndex = current;
        m_fogSize = desc.RenderSize;
        m_fogValid = true;
    }

    // RR ignores jitterOffsets and reads its motion vectors as the texel-to-texel displacement between the
    // jittered rasters (measured with real RR: with the canonical unjittered field its output trails the
    // current frame by the current jitter). Every other consumer keeps the canonical field in m_out, so RR
    // gets its own copy with (J_prev - J_cur) / size added. After a reset the previous jitter is the
    // current one and the copy equals the canonical field.
    void RRMotion(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        m_rrMotionActive = false;
        if (!desc.RRMotionJitterDelta || (desc.Flags & uint32_t(ConvFlags::Debug)) != 0u)
            return;
        if (!m_rrMotionShader.m_pso)
            m_rrMotionShader.Initialize(m_pDev, {reinterpret_cast<const byte*>(FSRDRRMotion_cso), sizeof(FSRDRRMotion_cso)},
                                        UINT(sizeof(RRMotion::Constants)), RRMotion::Input::kCount, RRMotion::Output::kCount,
                                        L"FSRD_RRMotion");
        if (!m_rrMotion)
            m_rrMotion = CreateTexture2D(m_pDev, m_maxWidth, m_maxHeight, FSRDFormats::Motion, L"FSRD_RRMotion", kSrvState);
        const RRMotion::Constants c {desc.RenderSize,
            {(desc.JitterOffsets.z - desc.JitterOffsets.x) * desc.RenderSize.z,
             (desc.JitterOffsets.w - desc.JitterOffsets.y) * desc.RenderSize.w}, {}};
        const RRMotion::Input inputs {{m_out.Resources.Motion.Get()}};
        RRMotion::Output outputs {{m_rrMotion.Get()}};
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassRrMotionCopy);
            m_rrMotionShader.Dispatch(cmdList, GetAsByteSpan(c), inputs.AsArray, outputs.AsArray,
                                      {desc.RenderSize.x, desc.RenderSize.y});
        }
        m_rrMotionActive = true;
    }

    void DispatchPackingShader(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc,
                               ID3D12PipelineState* conversionPipeline)
    {
        const XMFLOAT2 dispatchSize = { desc.RenderSize.x, desc.RenderSize.y };

        // Prepare inputs for packing and format conversion
        Conversion::Input in = { .Resources =
        {
            .InColor = m_skinMode == 1u ? m_skinPrepared.Get() : desc.Resources.InColor,
            .InDepth = m_LinearDepth.Get(),
            .InMotionVectors = desc.Resources.InMotionVectors,
            .InNormals = desc.Resources.InNormals,
            .InRoughness = desc.Resources.InRoughness,
            .InSpecHitDist = desc.Resources.InSpecHitDist,
            .InDiffAlbedo = desc.Resources.InDiffAlbedo,
            .InSpecAlbedo = desc.Resources.InSpecAlbedo,
            .InBiasMask = desc.Resources.InBiasMask,
            .Reserved0 = nullptr,
            .InInspector = desc.Resources.InInspector,
            .InEmissive = desc.Resources.InEmissive,
            .InSpecularRayDirectionHitDistance =
                desc.Resources.InSpecularRayDirectionHitDistance,
            .InDiffuseHitDistance = desc.Resources.InDiffuseHitDistance,
            .InTitleLinearDepth = desc.Resources.InTitleLinearDepth,
            .InResponsivityMask = desc.Resources.InResponsivityMask,
            .Reserved1 = nullptr,
            .Reserved2 = nullptr,
            .InPreviousDepth = m_PrevLinearDepth.Get()
        }};

        uint32_t packFlags = desc.Flags | uint32_t(ConvFlags::IsDepthLinear);
        if (!m_previousDepthValid)
            packFlags &= ~uint32_t(ConvFlags::DisocclusionCheck);
        // A null SRV reads as zero, so the shader is safe either way, but the flag keeps the
        // "no mask provided" case explicit and visible in the debug views.
        if (desc.Resources.InBiasMask != nullptr)
            packFlags |= uint32_t(ConvFlags::HasBiasMask);
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
            .DstTexSize = desc.RenderSize,
            .MotionInputSize = desc.MotionInputSize,
            .MotionTransform = desc.MotionTransform,
            .JitterOffsets = desc.JitterOffsets,
            .InputBase0 = m_skinMode == 1u ? XMUINT4{0, 0, desc.InputBase0.z, desc.InputBase0.w} : desc.InputBase0,
            .InputBase1 = desc.InputBase1,
            .InputBase2 = desc.InputBase2,
            .InputBase3 = desc.InputBase3,
            .InputBase4 = desc.InputBase4,
            .InputBase5 = {
                desc.TitleLinearDepthBase.x, desc.TitleLinearDepthBase.y,
                desc.SpecularHitDistanceBase.x, desc.SpecularHitDistanceBase.y
            },
            .NearPlane = desc.NearPlane,
            .FarPlane = desc.FarPlane,
            ._ConversionPadding = 0.0f,
            // The packing shader never sees the game's hardware depth. Geometry
            // has already converted it to signed linear view-space depth.
            .Flags = packFlags,
            .InspectorChannel = desc.InspectorChannel,
            .InspectorScale = desc.InspectorScale,
            .DebugDepthMax = desc.DebugDepthMax,
            // Only honour a mode the caller actually bound a resource for.
            .DiffuseHitDistanceMode = desc.Resources.InDiffuseHitDistance != nullptr
                ? desc.DiffuseHitDistanceMode
                : 0u,
            .ResponsivityTrustThreshold = desc.ResponsivityTrustThreshold,
            .ResponsivityInvert = desc.ResponsivityInvert ? 1u : 0u,
            .BiasMaskStrength = desc.BiasMaskStrength,
            .DemodDivisorFloor = desc.DemodDivisorFloor,
            .SpecularAlbedoDemodulation = desc.SpecularAlbedoDemodulation,
            .DiffuseAlbedoModulation = desc.DiffuseAlbedoModulation,
            // roughness, carried in bits 8-17 (1/1023).
            .RecoveryMask = (desc.RecoveryMask & 1u) | (std::min(desc.FlatAlbedoRoughness, 1023u) << 8),
            .AdditiveLightSplit = desc.AdditiveLightSplit,
        };

        // A request arriving after PrepareSkin is retained for the next legacy frame.
        if (!m_skinFused) CaptureAdditive(cmdList, packConstants, in.AsArray);
        const std::span<const byte> convCBData((const byte*) &packConstants, sizeof(packConstants));
        if (m_skinFused)
        {
            uint32_t rawFlags = desc.Flags;
            if (desc.Resources.InBiasMask) rawFlags |= uint32_t(ConvFlags::HasBiasMask);
            const uint32_t motionFlags = (desc.ObjectDepthDelta ? 1u : 0u) |
                (desc.ReflectionsFollowSurface ? 2u : 0u) | (m_previousDepthValid ? 4u : 0u);
            SkinConversion::Constants c {.Base = packConstants,
                .SkinOptions = {desc.InputBase0.x, desc.InputBase0.y, 1u, motionFlags},
                .SkinDebug = {desc.SkinDebug, desc.SssGuideBase.x, desc.SssGuideBase.y, rawFlags}};
            c.Base.InputBase4.z = desc.ColorDepthBase.z;
            c.Base.InputBase4.w = desc.ColorDepthBase.w;
            std::array<ID3D12Resource*, SkinFusedConversion::kInputCount> inputs {};
            std::copy(std::begin(in.AsArray), std::end(in.AsArray), inputs.begin());
            inputs[0] = desc.Resources.InColor;
            inputs[1] = desc.Resources.InDepth;
            inputs[9] = inputs[16] = inputs[17] = nullptr;
            inputs[19] = desc.Resources.InSssGuide;
            inputs[20] = desc.Resources.InColor;
            inputs[21] = desc.Resources.InDiffAlbedo;
            inputs[22] = desc.Resources.InSpecAlbedo;
            inputs[23] = desc.Resources.InBiasMask;
            std::array<ID3D12Resource*, SkinFusedConversion::kOutputCount> outputs {};
            std::copy(std::begin(m_out.AsRawArray), std::end(m_out.AsRawArray), outputs.begin());
            outputs[10] = m_LinearDepth.Get(); outputs[11] = m_skinPrepared.Get();
            outputs[12] = m_skinGuide.Get(); outputs[13] = m_skinBounds8.Get();
            ID3D12PipelineState* pso = nullptr;
            if (desc.AdditiveLightSplit > 0.0f)
            {
                if (!m_skinFusedAdditivePso)
                {
                    D3D12_COMPUTE_PIPELINE_STATE_DESC psoDesc {};
                    psoDesc.pRootSignature = m_skinFusedConvShader.m_rootSig.Get();
                    psoDesc.CS = {FSRDInputConvSkinFusedAdditive_cso, sizeof(FSRDInputConvSkinFusedAdditive_cso)};
                    ThrowIfFailed(m_pDev->CreateComputePipelineState(&psoDesc, IID_PPV_ARGS(&m_skinFusedAdditivePso)),
                                  "Fused skin additive pipeline creation failed");
                }
                pso = m_skinFusedAdditivePso.Get();
            }
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassConversionPack);
                m_skinFusedConvShader.Dispatch(cmdList, GetAsByteSpan(c), inputs, outputs, dispatchSize, true, pso);
            }
        }
        else if (m_skinMode != 0u || desc.ObjectDepthDelta || desc.ReflectionsFollowSurface)
        {
            EnsureSkinShaders();
            uint32_t motionFlags = (desc.ObjectDepthDelta ? 1u : 0u) |
                (desc.ReflectionsFollowSurface ? 2u : 0u) | (m_previousDepthValid ? 4u : 0u);
            SkinConversion::Constants c {.Base = packConstants,
                .SkinOptions = {desc.InputBase0.x, desc.InputBase0.y, m_skinMode, motionFlags},
                .SkinDebug = {desc.SkinDebug, m_skinMode == 2u ? desc.SssGuideBase.x : 0u,
                    m_skinMode == 2u ? desc.SssGuideBase.y : 0u, 0u}};
            std::array<ID3D12Resource*, SkinConversion::kInputCount> skinInputs {};
            std::copy(std::begin(in.AsArray), std::end(in.AsArray), skinInputs.begin());
            skinInputs[19] = m_skinMode == 2u ? desc.Resources.InSssGuide :
                (m_skinMode == 1u ? m_skinGuide.Get() : nullptr);
            skinInputs[20] = desc.Resources.InColor;
            const bool useBounds = m_skinMode == 2u;
            ComputeState& skinShader = useBounds ? m_skinBoundsConvShader : m_skinConvShader;
            auto& additive = useBounds ? m_skinBoundsAdditivePso : m_skinAdditivePso;
            ID3D12PipelineState* skinPso = nullptr;
            if (desc.AdditiveLightSplit > 0.0f)
            {
                if (!additive)
                {
                    D3D12_COMPUTE_PIPELINE_STATE_DESC pso {};
                    pso.pRootSignature = skinShader.m_rootSig.Get();
                    pso.CS = useBounds
                        ? D3D12_SHADER_BYTECODE{FSRDInputConvSkinBoundsAdditive_cso, sizeof(FSRDInputConvSkinBoundsAdditive_cso)}
                        : D3D12_SHADER_BYTECODE{FSRDInputConvSkinAdditive_cso, sizeof(FSRDInputConvSkinAdditive_cso)};
                    ThrowIfFailed(m_pDev->CreateComputePipelineState(&pso, IID_PPV_ARGS(&additive)), "Skin additive pipeline creation failed");
                }
                skinPso = additive.Get();
            }
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassConversionPack);
            if (useBounds)
            {
                std::array<ID3D12Resource*, SkinConversionBounds::kOutputCount> outputs {};
                std::copy(std::begin(m_out.AsRawArray), std::end(m_out.AsRawArray), outputs.begin());
                outputs.back() = m_skinBounds8.Get();
                skinShader.Dispatch(cmdList, GetAsByteSpan(c), skinInputs, outputs, dispatchSize, true, skinPso);
            }
            else
                skinShader.Dispatch(cmdList, GetAsByteSpan(c), skinInputs, m_out.AsRawArray,
                                    dispatchSize, true, skinPso);
        }
        else
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassConversionPack);
            m_convShader.Dispatch(cmdList, convCBData, in.AsArray, m_out.AsRawArray, dispatchSize, true,
                                  conversionPipeline);
        }
        StabiliseAlbedo(cmdList, desc);
        FogGuides(cmdList, desc);
        FilterSkinDiffuse(cmdList, desc);
        RRMotion(cmdList, desc);
        if(desc.LeakLobe)
        {
            FSRDStageTimings::Scope timing(m_stageTimings,FSRDStageTimings::TextureLeak);
            if(!m_leakShader.m_pso) m_leakShader.Initialize(m_pDev,
                {reinterpret_cast<const byte*>(FSRDLeak_cso),sizeof(FSRDLeak_cso)},32,6,1,L"FSRD_TextureLeak");
            if(!m_leakView || m_leakView->GetDesc().Width!=UINT(desc.RenderSize.x) || m_leakView->GetDesc().Height!=UINT(desc.RenderSize.y))
                m_leakView=CreateTexture2D(m_pDev,UINT(desc.RenderSize.x),UINT(desc.RenderSize.y),DXGI_FORMAT_R16G16B16A16_FLOAT,L"FSRD_TextureLeak",kSrvState);
            struct Constants { XMFLOAT4 size; uint32_t flags,padding[3]; };
            Constants c {desc.RenderSize,desc.LeakLobe==2u?1u:0u,{}};
            auto inputs=std::to_array({m_out.Resources.Signals.IndirectSpecular.Get(),m_out.Resources.Signals.DirectDiffuse.Get(),
                m_out.Resources.SpecAlbedo.Get(),m_out.Resources.DiffAlbedo.Get(),m_LinearDepth.Get(),m_out.Resources.Normals.Get()});
            auto outputs=std::to_array({m_leakView.Get()});
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassTextureLeak);
                m_leakShader.Dispatch(cmdList,GetAsByteSpan(c),inputs,outputs,{desc.RenderSize.x,desc.RenderSize.y});
                Blit(cmdList,m_leakView.Get(),m_out.Resources.Signals.IndirectSpecular.Get(),
                     {desc.RenderSize.x,desc.RenderSize.y},{desc.RenderSize.x,desc.RenderSize.y},{});
            }
        }
        if (m_gameTraceCaptureRequested) RecordGameTraceSources(cmdList, desc, packConstants);
    }

    void RecordGameTraceSources(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc,
                                 const Conversion::Constants& constants)
    {
        auto& r = m_out.Resources;
        const std::array<FSRDGameTraceSession::Source, FSRDGameTraceSession::SourceCount> sources {{
            {r.Signals.IndirectSpecular.Get(), kSrvState}, {r.Signals.DirectDiffuse.Get(), kSrvState},
            {r.SpecAlbedo.Get(), kSrvState}, {r.DiffAlbedo.Get(), kSrvState},
            {r.SkipSignal.Get(), kSrvState}, {r.Normals.Get(), kSrvState},
            {m_LinearDepth.Get(), kSrvState}, {r.Motion.Get(), kSrvState}
        }};
        const bool hooksAvailable = ResTrack_Dx12::EnsureRRTraceHooks(m_pDev);
        try
        {
            // Title resources are still read-only here. Keep their original
            // typed words and actual subrect bases; these are diagnostics only.
            using CaptureJson = nlohmann::json;
            uint32_t actualSeedFlags = 0;
            memcpy(&actualSeedFlags,m_gameTraceGeometryConstants.data()+offsetof(Geometry::Constants,Flags),sizeof(actualSeedFlags));
            const bool seedUsesTitleDepth = (actualSeedFlags & uint32_t(Geometry::TitleLinearDepth)) != 0;
            const CaptureJson captureControl {
                {"source_flags", desc.Flags}, {"geometry_flags",actualSeedFlags},
                {"color_depth_base", {desc.ColorDepthBase.x,desc.ColorDepthBase.y,desc.ColorDepthBase.z,desc.ColorDepthBase.w}},
                {"skin_mode", m_skinMode}, {"skin_debug", desc.SkinDebug},
                {"sss_radius_mm", desc.SssRadiusMm}, {"sss_strength", desc.SssStrength},
                {"sss_falloff", desc.SssFalloff}, {"skin_sigma", desc.SkinSigma},
                {"object_depth_delta", desc.ObjectDepthDelta}, {"reflections_follow_surface", desc.ReflectionsFollowSurface},
                {"albedo_stabilisation", desc.AlbedoStabilisation}, {"albedo_stabilisation_clamp", desc.AlbedoStabilisationClamp},
                {"albedo_stabilisation_rate", desc.AlbedoStabilisationRate}, {"fog_guides", desc.FogGuides},
                {"rr_motion_jitter_delta", desc.RRMotionJitterDelta},
                {"bias_strength", constants.BiasMaskStrength},
                {"specular_hit_distance_from_combined_alpha", desc.SpecularHitDistanceFromCombinedAlpha},
                {"diffuse_hit_distance_mode", constants.DiffuseHitDistanceMode},
                {"responsivity_threshold", constants.ResponsivityTrustThreshold},
                {"responsivity_invert", constants.ResponsivityInvert},
                {"inspector_channel", constants.InspectorChannel}, {"inspector_scale", constants.InspectorScale}
            };
            const auto flag = [&](ConvFlags value) { return (constants.Flags & uint32_t(value)) != 0; };
            auto original = [&](const char* name, ID3D12Resource* resource, uint32_t x, uint32_t y,
                                bool selected, const char* role = "original_caller_input")
            {
                FSRDGameTraceSession::DiagnosticSource source {name,{resource,kSrvState},x,y};
                source.active = resource && selected;
                source.inactiveReason = !resource ? "Resource not bound to this evaluation."
                    : "Not selected by the actual converter/seed flags or mode.";
                source.required = source.active;
                source.metadataJson = CaptureJson{{"role",role},{"conversion_flags",constants.Flags},{"selected_by_flags",selected},
                    {"control",captureControl}}.dump();
                return source;
            };
            // Snapshot final geometry before the SDK reuses the ping-pong
            // buffers. Motion here is already canonical motion, not seed gradient.
            std::vector<FSRDGameTraceSession::DiagnosticSource> originalSources {
                original("raw_color",desc.Resources.InColor,desc.InputBase0.x,desc.InputBase0.y,true),
                original("raw_normals",desc.Resources.InNormals,constants.InputBase1.x,constants.InputBase1.y,true),
                original("raw_specular_albedo",desc.Resources.InSpecAlbedo,constants.InputBase3.x,constants.InputBase3.y,true),
                original("raw_diffuse_albedo",desc.Resources.InDiffAlbedo,constants.InputBase2.z,constants.InputBase2.w,true),
                original("raw_bias_mask",desc.Resources.InBiasMask,constants.InputBase3.z,constants.InputBase3.w,flag(ConvFlags::HasBiasMask)),
                original("raw_specular_hit_distance",desc.Resources.InSpecHitDist,constants.InputBase5.z,constants.InputBase5.w,flag(ConvFlags::HasSpecHitDistance)),
                original("raw_specular_direction_hit_distance",desc.Resources.InSpecularRayDirectionHitDistance,constants.InputBase5.z,constants.InputBase5.w,
                    !flag(ConvFlags::HasSpecHitDistance) && flag(ConvFlags::HasCombinedSpecHitDistance)),
                original("raw_diffuse_hit_distance",desc.Resources.InDiffuseHitDistance,constants.InputBase4.z,constants.InputBase4.w,constants.DiffuseHitDistanceMode != 0),
                original("raw_responsivity",desc.Resources.InResponsivityMask,0,0,flag(ConvFlags::HasResponsivityMask)),
                original("raw_emissive",desc.Resources.InEmissive,constants.InputBase4.x,constants.InputBase4.y,flag(ConvFlags::HasEmissiveInput),"original_caller_debug_input"),
                original("raw_motion",desc.Resources.InMotionVectors,constants.InputBase0.z,constants.InputBase0.w,true),
                original("raw_depth",desc.Resources.InDepth,desc.ColorDepthBase.z,desc.ColorDepthBase.w,!seedUsesTitleDepth),
                original("raw_roughness",desc.Resources.InRoughness,constants.InputBase1.z,constants.InputBase1.w,!flag(ConvFlags::IsRoughnessPacked)),
                original("raw_title_linear_depth",desc.Resources.InTitleLinearDepth,desc.TitleLinearDepthBase.x,desc.TitleLinearDepthBase.y,seedUsesTitleDepth),
                original("raw_inspector",desc.Resources.InInspector,0,0,
                    (constants.Flags & uint32_t(ConvFlags::DebugModeMask)) == uint32_t(ConvFlags::DebugResourceInspector),"original_caller_debug_input"),
                original("raw_sss_guide",desc.Resources.InSssGuide,desc.SssGuideBase.x,desc.SssGuideBase.y,true,"signed_lum4_after_minus_before"),
                original("raw_color_before_sss",desc.Resources.InColorBeforeSss,desc.ColorBeforeSssBase.x,desc.ColorBeforeSssBase.y,true),
                original("raw_color_after_sss",desc.Resources.InColorAfterSss,desc.ColorAfterSssBase.x,desc.ColorAfterSssBase.y,true)
            };
            auto& rawMotion = originalSources[12];
            rawMotion.motionAddressed = true;
            rawMotion.displayResolutionMotion = flag(ConvFlags::DisplayResolutionMotion);
            rawMotion.motionWidth = constants.MotionInputSize.x; rawMotion.motionHeight = constants.MotionInputSize.y;
            rawMotion.jitterX = constants.JitterOffsets.x; rawMotion.jitterY = constants.JitterOffsets.y;
            auto motionMetadata = CaptureJson::parse(rawMotion.metadataJson);
            motionMetadata["mapping"] = {{"kind","converter_motion_source_bounding_rectangle"},
                {"display_resolution",rawMotion.displayResolutionMotion},
                {"motion_vectors_jittered",flag(ConvFlags::MotionVectorsJittered)},
                {"render_extent",{constants.DstTexSize.x,constants.DstTexSize.y}},
                {"motion_input_extent",{constants.MotionInputSize.x,constants.MotionInputSize.y}},
                {"current_jitter",{constants.JitterOffsets.x,constants.JitterOffsets.y}},
                {"motion_transform",{constants.MotionTransform.x,constants.MotionTransform.y,constants.MotionTransform.z,constants.MotionTransform.w}},
                {"formula","display: clamp(floor((p+0.5-Jcur)*renderReciprocal*motionExtent),0,motionExtent-1)+sourceBase; otherwise clamp(p,0,motionExtent-1)+sourceBase"},
                {"bounding_halo_texels",rawMotion.displayResolutionMotion ? 1 : 0}};
            rawMotion.metadataJson = motionMetadata.dump();
            for(const auto& input:desc.ResearchInputs)
            {
                const bool particleGuide = input.name == "ColorBeforeParticles" || input.name == "ColorBeforeTransparency";
                if (particleGuide && !FSRDGameTraceSession::WantsParticleLayerDiagnostics()) continue;
                const auto row=FSRDResearch::Describe(m_pDev,input);
                const std::string name = particleGuide ? (input.name == "ColorBeforeParticles" ?
                    "raw_color_before_particles" : "raw_color_before_transparency") : "input_"+input.name;
                FSRDGameTraceSession::DiagnosticSource source {name,{input.resource,kSrvState},input.x,input.y};
                source.active=row.sampled; source.required=false;
                source.inactiveReason=row.status;
                source.metadataJson=CaptureJson{{"role","optional_ngx_input"},{"key",input.key}}.dump();
                originalSources.push_back(std::move(source));
            }
            m_gameTraceFrameRecorded = m_gameTrace.RecordSources(m_pDev, cmdList, sources,
                static_cast<uint32_t>(desc.RenderSize.x), static_cast<uint32_t>(desc.RenderSize.y),
                {reinterpret_cast<const uint8_t*>(&constants), sizeof(constants)}, originalSources,
                m_gameTraceGeometryConstants,
                {},hooksAvailable);
        }

        catch (const std::exception& error) { m_gameTrace.Abort(error.what()); }
        catch (...) { m_gameTrace.Abort("Game trace source metadata unavailable."); }
    }

    // The post-motion anchor's keyframe ring is a texture array (the recall pass indexes the slice), which the
    // shared CreateTexture2D helper cannot build.
    static ComPtr<ID3D12Resource> CreateTexture2DArraySlice(ID3D12Device* pDev, UINT width, UINT height, UINT slices,
        DXGI_FORMAT format, LPCWSTR name, D3D12_RESOURCE_STATES initialState)
    {
        ScopedSkipHeapCapture skipHeapCapture {};
        D3D12_RESOURCE_DESC desc = {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = width;
        desc.Height = height;
        desc.DepthOrArraySize = UINT16(slices);
        desc.MipLevels = 1;
        desc.Format = format;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        D3D12_HEAP_PROPERTIES heapProps = { D3D12_HEAP_TYPE_DEFAULT };
        ComPtr<ID3D12Resource> resource;
        ThrowIfFailed(pDev->CreateCommittedResource(&heapProps, D3D12_HEAP_FLAG_NONE, &desc, initialState, nullptr,
            IID_PPV_ARGS(&resource)), "Failed to create internal texture array");
        resource->SetName(name);
        return resource;
    }

    bool DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConversionDesc& desc)
    {
        m_research.SetTimings(m_stageTimings);
        m_research.Begin(m_pDev,cmdList,desc.ResearchInputs,uint32_t(desc.RenderSize.x),uint32_t(desc.RenderSize.y),
                         desc.InvViewMatrix,(desc.Flags & uint32_t(ConvFlags::Debug))==0 && desc.LeakLobe==0);
        m_gameTraceCaptureRequested = FSRDGameTraceSession::IsActive();
        m_gameTraceFrameRecorded = false;
        if (m_gameTraceCaptureRequested)
        {
            m_gameTrace.Poll();
            if ((desc.Flags & uint32_t(ConvFlags::Debug)) != 0)
            {
                m_gameTrace.Abort("Debug rendering interrupted the normal RR capture.");
                m_gameTraceCaptureRequested = false;
            }
        }
        if (m_runtime) m_runtime->Begin(FSRDRuntimeSnapshot::Geometry);
        if (!cmdList || !m_maxWidth)
            return false;

        const bool useAdditivePipeline = std::isfinite(desc.AdditiveLightSplit) && desc.AdditiveLightSplit > 0.0f;
        // Resolve the optional PSO before recording any geometry work or barriers.
        if (useAdditivePipeline && !EnsureAdditiveConversionPipeline())
            return false;
        ID3D12PipelineState* conversionPipeline = useAdditivePipeline
            ? m_additiveConvPso.Get() : m_convShader.m_pso.Get();
        // nullptr selects the default Seed PSO.

        m_motionHistoryValid=desc.MotionHistoryValid;
        m_currentJitter={desc.JitterOffsets.x,desc.JitterOffsets.y};
        m_flatHistoryJitterDelta = {desc.JitterOffsets.z - desc.JitterOffsets.x,
                                    desc.JitterOffsets.w - desc.JitterOffsets.y};
        // MotionHistoryValid includes explicit title reset/camera-cut and continuity validation.
        if (!desc.MotionHistoryValid) ResetFlatTemporalHistory();

        // A title-published linear depth reaches every consumer of view-space position
        // - the geometry pass/filter, the packing shader and the denoiser's own depth
        // input - through the canonical signed copy the geometry pass writes into
        // m_LinearDepth, never as a raw hand-off: the descriptor carries no sign
        // convention, and a positive distance where an RH view matrix implies negative
        // view Z leaves RR unable to reproject anything. The raw resource stays bound
        // for this frame's own reads of it (the debug views that show it as published,
        // against the canonical copy), so its declared state is carried through rather
        // than assumed: declaring a wider state than the resource is in records an
        // invalid barrier.
        if ((desc.Flags & uint32_t(ConvFlags::TitleLinearDepth)) != 0 &&
            desc.Resources.InTitleLinearDepth != nullptr)
        {
            m_rrLinearDepth = desc.Resources.InTitleLinearDepth;
            m_rrLinearDepthState = desc.TitleLinearDepthState;
            m_rrLinearDepthDeclaredState = desc.TitleLinearDepthDeclaredState;
        }
        else
        {
            m_rrLinearDepth = nullptr;
        }

        // The title's resource is in whatever state it declared - COMMON for titles that tag
        // without committing to one. Transition it in for the geometry and packing reads;
        // the caller hands it back once the denoiser has finished with it.
        m_rrLinearDepthForwarded = false;
        if (m_rrLinearDepth != nullptr &&
            m_rrLinearDepthDeclaredState != static_cast<uint32_t>(kSrvState))
        {
            AddBarrier(cmdList, m_rrLinearDepth,
                       static_cast<D3D12_RESOURCE_STATES>(m_rrLinearDepthDeclaredState), kSrvState);
            m_rrLinearDepthForwarded = true;
        }

        TransitionDenoiserOutputsToRead(cmdList);

        // Geometric disocclusion check: keep last frame's canonical depth before geometry
        // seed overwrites it. Only a complete frame of the same size that this frame's motion
        // continues counts; otherwise the check stays off for this frame.
        m_previousDepthValid = false;
        if (((desc.Flags & uint32_t(ConvFlags::DisocclusionCheck)) != 0 || desc.ObjectDepthDelta) &&
            m_PrevLinearDepth && desc.MotionHistoryValid &&
            memcmp(&m_linearDepthSize, &desc.RenderSize, sizeof(desc.RenderSize)) == 0)
        {
            AddBarrier(cmdList, m_LinearDepth.Get(), kSrvState, D3D12_RESOURCE_STATE_COPY_SOURCE);
            AddBarrier(cmdList, m_PrevLinearDepth.Get(), kSrvState, D3D12_RESOURCE_STATE_COPY_DEST);
            cmdList->CopyResource(m_PrevLinearDepth.Get(), m_LinearDepth.Get());
            AddBarrier(cmdList, m_PrevLinearDepth.Get(), D3D12_RESOURCE_STATE_COPY_DEST, kSrvState);
            AddBarrier(cmdList, m_LinearDepth.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, kSrvState);
            m_previousDepthValid = true;
        }

        {
            FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::Geometry);
            PrepareSkin(cmdList, desc);
            if (!m_skinFused) DispatchGeometry(cmdList, desc);
        }
        m_linearDepthSize = desc.RenderSize;
        if (m_runtime)
        {
            m_runtime->Complete(FSRDRuntimeSnapshot::Geometry);
            m_runtime->Begin(FSRDRuntimeSnapshot::Conversion);
        }

        // DLSS-RR to FSR-RR conversion
        {
            FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::Conversion);
            DispatchPackingShader(cmdList, desc, conversionPipeline);
        }
        if (m_runtime) m_runtime->Complete(FSRDRuntimeSnapshot::Conversion);

        // Post-motion level anchor (task 25 T3 ii, default off): the luminance gain rides on RR's input signals
        // after the packing wrote them and before the bridge scales and feeds them to the provider. Off: the call
        // returns before any allocation, barrier or dispatch.
        DispatchPostMotionAnchor(cmdList, desc);

        // Diagnostic: read back the RR-facing linear depth, motion and normals while
        // their state is still the one this code set. The denoiser dispatch below
        // records FFX's own barriers over these resources, so this must stay here.
        UpdateInputProbe(cmdList, desc);

        // Transition output buffers to UAV after last composition pass or first init.
        // The denoiser will be writing to these.
        {
            AddBarrier(cmdList, m_outputBuffer1.Get(), kSrvState, kUavState);
            AddBarrier(cmdList, m_outputBuffer2.Get(), kSrvState, kUavState);
            AddBarrier(cmdList, m_directSpecularOutput.Get(), kSrvState, kUavState);
            AddBarrier(cmdList, m_indirectDiffuseOutput.Get(), kSrvState, kUavState);
            AddBarrier(cmdList, m_ambientOcclusionOutput.Get(), kSrvState, kUavState);
            AddBarrier(cmdList, m_specularOcclusionOutput.Get(), kSrvState, kUavState);
            m_radianceOutputsInUavState = true;
            m_ambientOcclusionOutputInUavState = true;
            m_specularOcclusionOutputInUavState = true;
        }
        return true;
    }

    // --- Compare (split) view -------------------------------------------------------------
    // Snapshot captures happen during composition (pre-SR, render size). The composite is
    // built later at the output size and only ever presented after the canonical SR pass;
    // it never becomes the composition the upscaler or GAME_TRACE reads.
    void EnsureCompareShader()
    {
        if (m_compareShader.m_pso)
            return;
        m_compareShader.Initialize(m_pDev, GetAsByteSpan(FSRDCompareView_cso),
            sizeof(CompareView::Constants), CompareView::Input::kCount, CompareView::Output::kCount,
            L"FSRD_CompareView_Constants", kBackBufferCount);
    }

    ComPtr<ID3D12Resource> CreateCompareTarget(LPCWSTR name, UINT width, UINT height)
    {
        return CreateTexture2D(m_pDev, std::max(width, 1u), std::max(height, 1u),
                               DXGI_FORMAT_R16G16B16A16_FLOAT, name, kSrvState);
    }

    void EnsureCompareSnapshots(UINT width, UINT height)
    {
        if (!m_compareSnapshotA || m_compareSnapshotA->GetDesc().Width != width ||
            m_compareSnapshotA->GetDesc().Height != height)
        {
            m_compareFrozenValid = false;
            m_compareSnapshotA = CreateCompareTarget(L"FSRD_Compare_VariantA", width, height);
            m_compareSnapshotB = CreateCompareTarget(L"FSRD_Compare_VariantB", width, height);
        }
    }

    void EnsureComparePresentation(UINT width, UINT height)
    {
        EnsureCompareShader();
        if (m_comparePresent && m_comparePresentWidth == width && m_comparePresentHeight == height)
            return;
        m_comparePresent = CreateCompareTarget(L"FSRD_Compare_Present", width, height);
        m_compareFrozen = CreateCompareTarget(L"FSRD_Compare_Frozen", width, height);
        m_comparePresentWidth = width;
        m_comparePresentHeight = height;
        m_compareFrozenValid = false;
    }

    // Copy-only presentation resources must survive even an abandoned evaluation's executable prefix.
    bool CopyCompareTexture(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* src,
                            ID3D12Resource* dst)
    {
        if (!cmdList || !src || !dst) return false;
        const auto sourceDesc = src->GetDesc(), targetDesc = dst->GetDesc();
        if (sourceDesc.Width < targetDesc.Width || sourceDesc.Height < targetDesc.Height ||
            targetDesc.Width > UINT_MAX || sourceDesc.Format != targetDesc.Format) return false;
        auto lease = std::make_shared<std::array<ComPtr<ID3D12Resource>,2>>();
        (*lease)[0] = src; (*lease)[1] = dst;
        if (!ResTrack_Dx12::RetainComputeDispatch(m_pDev,cmdList,lease)) return false;
        AddBarrier(cmdList, src, kSrvState, D3D12_RESOURCE_STATE_COPY_SOURCE);
        AddBarrier(cmdList, dst, kSrvState, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION source {}, target {};
        source.pResource = src; source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        target.pResource = dst; target.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        // Only the valid render region, not the source's possibly larger max-render allocation.
        const D3D12_BOX box {0,0,0,UINT(targetDesc.Width),targetDesc.Height,1};
        cmdList->CopyTextureRegion(&target,0,0,0,&source,&box);
        AddBarrier(cmdList, src, D3D12_RESOURCE_STATE_COPY_SOURCE, kSrvState);
        AddBarrier(cmdList, dst, D3D12_RESOURCE_STATE_COPY_DEST, kSrvState);
        return true;
    }
    bool CaptureCompare(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* src,
                        ComPtr<ID3D12Resource>& dst)
    { return CopyCompareTexture(cmdList,src,dst.Get()); }

    // Builds the output-sized split from the render-sized A/B snapshots into m_comparePresent.
    // Both halves get the same bilinear filter only when the source and output sizes differ.
    void DispatchCompare(ID3D12GraphicsCommandList* cmdList, uint32_t dstWidth, uint32_t dstHeight,
                         bool swap, float split)
    {
        EnsureComparePresentation(dstWidth, dstHeight);
        const bool resample = m_compareSnapshotA->GetDesc().Width != m_comparePresentWidth ||
                              m_compareSnapshotA->GetDesc().Height != m_comparePresentHeight;
        uint32_t flags = uint32_t(CompareView::DrawDivider) | uint32_t(CompareView::DrawLabels);
        if (swap)
            flags |= uint32_t(CompareView::SwapSides);
        if (resample)
            flags |= uint32_t(CompareView::Resample);
        uint32_t divider = uint32_t(std::clamp(split, 0.0f, 1.0f) * float(dstWidth) + 0.5f);
        divider = std::min(divider, dstWidth);
        CompareView::Constants constants {
            .DstTexSize = {float(dstWidth), float(dstHeight), 1.0f / float(dstWidth), 1.0f / float(dstHeight)},
            .Flags = flags, .DividerPx = divider, ._Padding0 = 0, ._Padding1 = 0
        };
        CompareView::Input in {{m_compareSnapshotA.Get(), m_compareSnapshotB.Get()}};
        CompareView::Output out {{m_comparePresent.Get()}};
        m_compareShader.Dispatch(cmdList, GetAsByteSpan(constants), in.AsArray, out.AsArray,
                                 {float(dstWidth), float(dstHeight)});
    }

    ID3D12Resource* PrepareComparePresentation(ID3D12GraphicsCommandList* cmdList,
                                               uint32_t dstWidth, uint32_t dstHeight,
                                               bool swap, float split, bool hold)
    {
        if (!cmdList || !m_compareSnapshotA || !m_compareSnapshotB || !dstWidth || !dstHeight)
            return nullptr;
        // Validate the output size before reusing a held image after a resolution change.
        EnsureComparePresentation(dstWidth,dstHeight);
        // Hold: compose once, then keep returning the frozen output-sized copy.
        if (hold && m_compareFrozenValid)
            return m_compareFrozen.Get();
        if (!m_compareSnapshotsReady) return nullptr;
        DispatchCompare(cmdList, dstWidth, dstHeight, swap, split);
        if (hold)
        {
            if (!CopyCompareTexture(cmdList,m_comparePresent.Get(),m_compareFrozen.Get())) return nullptr;
            m_compareFrozenValid = true;
            return m_compareFrozen.Get();
        }
        m_compareFrozenValid = false;
        return m_comparePresent.Get();
    }

    void DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)
    {
        if (m_runtime) m_runtime->Begin(FSRDRuntimeSnapshot::Composition);
        if (!cmdList || !m_maxWidth)
            throw std::runtime_error("Composition requires a command list and allocated resources");

        m_recoveryOutputIndex = -1;
        // Post-flick (T2 c): the flag belongs to the frame that produced the texture, so it is cleared here, at the
        // start of the composition phase, before any CompositionColor() consumer runs. Clearing it later (inside
        // DispatchPostFlick, after the flat detail) made the in-place flat-detail pass read and write the previous
        // frame's post-flick texture, which silently dropped the NZR correction while the option was on.
        m_postFlickActive = false;
        // Post-RR colour tracking (T2): same rule, the flag describes this frame's composite.
        m_colourTrackActive = false;
        // The target texture must exist before the composition pass writes it and before the tracking passes read
        // it, so the allocation and the size rules run here, ahead of the composition dispatch.
        const bool colourTrackFrame = PrepareColourTrack(desc);
        auto& outResources = m_out.Resources;
        Composition::Input inputs = {};
        Composition::Constants constants = 
        {
            .DstTexSize = desc.DstTexSize,
            .Flags = UINT(desc.Flags) | (colourTrackFrame ? uint32_t(CompFlags::ColourTrackTarget) : 0u),
            .SourceUvScale = {1.0f, 1.0f},
            .SourceUvOffset = {},
            .SpecularAlbedoDemodulation = desc.SpecularAlbedoDemodulation,
            .DiffuseAlbedoModulation = desc.DiffuseAlbedoModulation,
            .UnsupportedAlbedoRecovery = desc.UnsupportedAlbedoRecovery,
            .DemodDivisorFloor = desc.DemodDivisorFloor
        };

        // Transition denoiser output buffers to SRV for composition.
        TransitionDenoiserOutputsToRead(cmdList);

        // A signal excluded from the denoiser chain (single-signal denoise mode) is
        // never written this frame, and its ping-pong buffer is shared with the floor
        // passes - so it still holds that an unwritten image. Multiplied by
        // signal. The packed raw signal is the demodulated radiance the denoiser
        // would otherwise have consumed, so it is the energy-preserving passthrough.
        ID3D12Resource* const specularRadiance =
            (desc.Flags & (uint32_t) CompFlags::SpecularSignalDisabled) != 0
                ? outResources.Signals.IndirectSpecular.Get()
                : m_outputBuffer1.Get();
        ID3D12Resource* const diffuseRadiance =
            (desc.Flags & (uint32_t) CompFlags::DiffuseSignalDisabled) != 0
                ? outResources.Signals.DirectDiffuse.Get()
                : m_outputBuffer2.Get();

        if (desc.UnsupportedAlbedoRecovery > 0.0f)
        {
            if (m_runtime) m_runtime->Begin(FSRDRuntimeSnapshot::AlbedoRecovery);
            DispatchAlbedoTrust(cmdList, desc, diffuseRadiance);
            if (m_runtime) m_runtime->Complete(FSRDRuntimeSnapshot::AlbedoRecovery);
        }
        else if (m_runtime)
            m_runtime->steps[FSRDRuntimeSnapshot::AlbedoRecovery] = FSRDRuntimeSnapshot::Disabled;
        if (m_runtime) m_runtime->Begin(FSRDRuntimeSnapshot::Composition);

        inputs.Resources =
        {
            .InIndirectSpecular = specularRadiance,
            .InSpecularAlbedo = outResources.SpecAlbedo.Get(),
            .InDirectDiffuse = diffuseRadiance,
            .InDiffuseAlbedo = outResources.DiffAlbedo.Get(),
            .InSkipSignal = outResources.SkipSignal.Get(),
            .InNormals = outResources.Normals.Get(),
            .InLinearDepth = m_LinearDepth.Get(),
            .InMotion = outResources.Motion.Get(),
            // Always bound; read only while UnsupportedAlbedoRecovery is nonzero.
            .InDirectSpecularDenoised = m_directSpecularOutput.Get(),
            .InDirectSpecularSignal = outResources.DirectSpecular.Get(),
            .InAlbedoTrust = m_albedoTrust[m_albedoTrustResult].Get(),
            .InIndirectDiffuseDenoised = m_indirectDiffuseOutput.Get(),
            .InIndirectSpecularSignal = outResources.Signals.IndirectSpecular.Get(),
            .InDirectDiffuseSignal = outResources.Signals.DirectDiffuse.Get(),
        };

        Composition::Output outputs { .Resources = { .OutColor=m_compositionOutput.Get(),
            .OutTarget = colourTrackFrame ? m_colourTrackInput.Get() : nullptr } };
        const std::span<const byte> cbData((const byte*) &constants, sizeof(constants));
        const XMFLOAT2 dstDim = { constants.DstTexSize.x, constants.DstTexSize.y };

        {
            FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::Composition);
            {
                FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassCompositionMain);
                m_compShader.Dispatch(cmdList, cbData, inputs.AsArray, outputs.AsArray, dstDim);
            }
            // Compare view snapshots. Pairs are isolated at their own pipeline point so the
            // two halves differ only by the feature under test. Skipped entirely when off.
            const uint32_t compare = desc.CompareView;
            m_compareSnapshotsReady = false;
            if (compare != m_compareView)
            {
                m_compareFrozenValid = false;
                m_compareView = compare;
                if (compare == 0u)
                {
                    m_compareSnapshotA.Reset(); m_compareSnapshotB.Reset();
                    m_comparePresent.Reset(); m_compareFrozen.Reset();
                    m_comparePresentWidth = m_comparePresentHeight = 0;
                }
            }
            bool capturedA = false, capturedB = false;
            if (compare != 0u)
                EnsureCompareSnapshots(UINT(desc.DstTexSize.x), UINT(desc.DstTexSize.y));
            if (compare == 1u || compare == 2u)
                capturedA = CaptureCompare(cmdList,m_compositionOutput.Get(),m_compareSnapshotA);
            // Post-RR colour tracking (T2) runs before the recovery chain, the flat detail and NZR, so those
            // passes see the corrected colour and their own writers keep the last word where they replace it.
            // The compare view's A snapshot above is still the raw composition (RR only), which is what that
            // view compares against.
            if (colourTrackFrame)
                DispatchColourTrack(cmdList, desc);
            DispatchRecoveryChain(cmdList, desc);
            if (compare == 2u)
                capturedB = CaptureCompare(cmdList,CompositionColor(),m_compareSnapshotB);
            else if (compare == 3u)
                capturedA = CaptureCompare(cmdList,CompositionColor(),m_compareSnapshotA);
            DispatchFlatDetail(cmdList, desc);
            DispatchPostFlick(cmdList, desc);
            if (compare == 3u)
                capturedB = CaptureCompare(cmdList,CompositionColor(),m_compareSnapshotB);
            else if (compare == 4u)
                capturedA = CaptureCompare(cmdList,CompositionColor(),m_compareSnapshotA);
            ReblurSkin(cmdList, desc);
            if (compare == 1u || compare == 4u)
                capturedB = CaptureCompare(cmdList,CompositionColor(),m_compareSnapshotB);
            m_compareSnapshotsReady = capturedA && capturedB;
        }
        if (m_runtime) m_runtime->Complete(FSRDRuntimeSnapshot::Composition);
    }

    // Unsupported-albedo evidence from RR's unmodulated specular output, then six
    // same-surface a-trous steps that spread it over continuous surfaces. Requires the
    // denoiser outputs in SRV state; leaves the result in m_albedoTrust[m_albedoTrustResult].
    void DispatchAlbedoTrust(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc,
                             ID3D12Resource* diffuseRadiance)
    {
        FSRDStageTimings::Scope timing(m_stageTimings, FSRDStageTimings::AlbedoRecovery);
        auto& outResources = m_out.Resources;
        const XMFLOAT2 dim = { desc.DstTexSize.x, desc.DstTexSize.y };
        TrustEvidence::Constants evidenceConstants = {
            .DstTexSize = desc.DstTexSize,
            .StepSize = 0,
            .Flags = ((desc.Flags & uint32_t(CompFlags::ExtraDiffuse)) != 0 ? 1u : 0u) |
                     ((desc.Flags & uint32_t(CompFlags::DiffuseAlternate)) != 0 ? 2u : 0u),
            .DemodDivisorFloor = desc.DemodDivisorFloor
        };
        TrustEvidence::Input evidenceIn = { .Resources = {
            .InDirectSpecularDenoised = m_directSpecularOutput.Get(),
            .InDirectDiffuse = diffuseRadiance,
            .InSpecularAlbedo = outResources.SpecAlbedo.Get(),
            .InDiffuseAlbedo = outResources.DiffAlbedo.Get(),
            .InSkipSignal = outResources.SkipSignal.Get(),
            .InLinearDepth = m_LinearDepth.Get(),
            .InNormals = outResources.Normals.Get(),
            .InDirectSpecularSignal = outResources.DirectSpecular.Get(),
            .InIndirectDiffuseDenoised = m_indirectDiffuseOutput.Get(),
            .InIndirectSpecularSignal = outResources.Signals.IndirectSpecular.Get(),
            .InDirectDiffuseSignal = outResources.Signals.DirectDiffuse.Get()
        }};
        TrustEvidence::Output evidenceOut = { .Resources = { .OutAlbedoTrust = m_albedoTrust[0].Get() } };
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassAlbedoTrustEvidence);
            m_trustEvidenceShader.Dispatch(cmdList, GetAsByteSpan(evidenceConstants), evidenceIn.AsArray,
                                           evidenceOut.AsArray, dim);
        }

        UINT read = 0;
        {
            FSRDStageTimings::PassScope passTiming(m_stageTimings, FSRDStageTimings::PassAlbedoTrustPropagate);
            for (UINT pass = 0; pass < TrustPropagate::kPasses; ++pass)
            {
                TrustPropagate::Constants constants = {
                    .DstTexSize = desc.DstTexSize,
                    .StepSize = 1 << pass,
                    .Flags = 0,
                    .DemodDivisorFloor = desc.DemodDivisorFloor
                };
                TrustPropagate::Input in = { .Resources = {
                    .InAlbedoTrust = m_albedoTrust[read].Get(),
                    .InLinearDepth = m_LinearDepth.Get(),
                    .InNormals = outResources.Normals.Get()
                }};
                TrustPropagate::Output out = { .Resources = { .OutAlbedoTrust = m_albedoTrust[1 - read].Get() } };
                m_trustPropagateShader.Dispatch(cmdList, GetAsByteSpan(constants), in.AsArray, out.AsArray, dim);
                read = 1 - read;
            }
        }
        m_albedoTrustResult = read;
    }

    void TransitionDenoiserOutputsToRead(ID3D12GraphicsCommandList* cmdList) noexcept
    {
        if (!cmdList)
            return;

        if (m_radianceOutputsInUavState)
        {
            // The direct-specular output shares the radiance outputs' state lifetime.
            std::array<ID3D12Resource*, 4> buffers = { m_outputBuffer1.Get(), m_outputBuffer2.Get(),
                m_directSpecularOutput.Get(), m_indirectDiffuseOutput.Get() };
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

    void TransitionDenoiserOutputsToUav(ID3D12GraphicsCommandList* cmdList) noexcept
    {
        if (!cmdList)
            return;

        if (!m_radianceOutputsInUavState)
        {
            std::array<ID3D12Resource*, 4> buffers = { m_outputBuffer1.Get(), m_outputBuffer2.Get(),
                m_directSpecularOutput.Get(), m_indirectDiffuseOutput.Get() };
            AddBarriers(cmdList, buffers, kSrvState, kUavState);
            m_radianceOutputsInUavState = true;
        }

        if (!m_ambientOcclusionOutputInUavState)
        {
            AddBarrier(cmdList, m_ambientOcclusionOutput.Get(), kSrvState, kUavState);
            m_ambientOcclusionOutputInUavState = true;
        }

        if (!m_specularOcclusionOutputInUavState)
        {
            AddBarrier(cmdList, m_specularOcclusionOutput.Get(), kSrvState, kUavState);
            m_specularOcclusionOutputInUavState = true;
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
            m_debugViewOutput = std::move(newOutput);
            m_debugViewWidth = width;
            m_debugViewHeight = height;
            m_debugViewOutputInUavState = true;

            LOG_INFO("[RR_DIAG] created dedicated AMD debug-view output: {}x{}, "
                     "DXGI_FORMAT_R16G16B16A16_FLOAT, UAV", width, height);
        }
        // RR may record writes even if its dispatch or the following blit fails.
        // Retain the target before either happens, through Reset and every queued
        // submission. A fixed number of CPU frames is not a retirement guarantee.
        auto lease = std::make_shared<ComPtr<ID3D12Resource>>(m_debugViewOutput);
        if (!ResTrack_Dx12::RetainComputeDispatch(m_pDev, cmdList, lease))
            throw std::runtime_error("Debug-view output lifetime tracking unavailable");
        if (!m_debugViewOutputInUavState)
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
            throw std::runtime_error("Blit requires a command list, source and destination");

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
            throw std::runtime_error("Blit source subrect or destination extent is invalid");

        Composition::Input inputs = {};
        inputs.Resources.InIndirectSpecular = srcTex;

        const auto mapX = FSRDBlitMapping::Resolve(logicalSrcDim.x, logicalSrcBase.x, physicalSrcDim.x, dstDim.x);
        const auto mapY = FSRDBlitMapping::Resolve(logicalSrcDim.y, logicalSrcBase.y, physicalSrcDim.y, dstDim.y);
        const Composition::Constants constants = 
        {
            .DstTexSize = 
            {
                dstDim.x,           dstDim.y,
                (1.0f / dstDim.x),  (1.0f / dstDim.y)
            },
            .Flags = (UINT)CompFlags::RawSourceBlit | (UINT)CompFlags::ScaleSrc,
            .SourceUvScale = { mapX.scale, mapY.scale },
            .SourceUvOffset = { mapX.offset, mapY.offset }
        };

        std::array<ID3D12Resource*, Composition::kOutputCount> uavs { dstTex };
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

        // Always the converter's own field: it is the one whose sign convention is known,
        // and the one every other consumer reads - the geometry pass writes it from the
        // title's published linear depth when one is provided, so the denoiser sees the
        dispatchDesc.linearDepth = ffxApiGetResourceDX12(
            m_LinearDepth.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
        dispatchDesc.motionVectors = ffxApiGetResourceDX12(
            m_rrMotionActive ? m_rrMotion.Get() : outResources.Motion.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
        dispatchDesc.normals = ffxApiGetResourceDX12(
            outResources.Normals.Get(), FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
        dispatchDesc.specularAlbedo = ffxApiGetResourceDX12(
            outResources.SpecAlbedo.Get(),
            FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);
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
        m_impl->Initialize(GetAsByteSpan(FSRDGeometry_cso),
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
    if (!m_IsInitialized)
        return false;
    try
    {
        return m_impl->DispatchConversion(cmdList, desc);
    }
    catch (const std::exception& err)
    {
        m_impl->m_gameTrace.Abort(err.what());
        LOG_ERROR("FSRD input conversion failed. Details: {}", err.what());
    }

    return false;
}

void FSRDPreprocessor_Dx12::SetStageTimings(FSRDStageTimings* timings)
{
    m_impl->m_stageTimings = timings;
}

void FSRDPreprocessor_Dx12::SetRuntimeSnapshot(FSRDRuntimeSnapshot* snapshot)
{
    m_impl->m_runtime = snapshot;
}

bool FSRDPreprocessor_Dx12::ConfigureSignalResources(bool extraDiffuse, bool extraSpecular, bool albedoRecovery)
{
    if (m_impl->m_maxWidth != 0) return false;
    m_impl->m_extraDiffuse = extraDiffuse;
    m_impl->m_extraSpecular = extraSpecular;
    m_impl->m_albedoRecovery = albedoRecovery;
    return true;
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

void FSRDPreprocessor_Dx12::GetDirectSpecularSignal(ffxDispatchDescDenoiserDirectSpecular& directSpecular, bool unmodulated) const
{
    directSpecular =
    {
        .header = { .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR },
        .signal =
        {
            .input = ffxApiGetResourceDX12(unmodulated ? m_impl->m_out.Resources.DirectSpecular.Get()
                : m_impl->m_out.Resources.Signals.IndirectSpecular.Get(),
                                           FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
            .output = ffxApiGetResourceDX12(m_impl->m_directSpecularOutput.Get(),
                                            FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
            .checkerboardOrigin = 0
        }
    };
}

void FSRDPreprocessor_Dx12::GetIndirectDiffuseSignal(ffxDispatchDescDenoiserIndirectDiffuse& indirectDiffuse,
                                                     bool unmodulated) const
{
    indirectDiffuse = {
        .header = { .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE },
        .signal = {
            .input = ffxApiGetResourceDX12(unmodulated ? m_impl->m_out.Resources.IndirectDiffuse.Get()
                                                       : m_impl->m_out.Resources.Signals.DirectDiffuse.Get(),
                                           FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
            .output = ffxApiGetResourceDX12(m_impl->m_indirectDiffuseOutput.Get(),
                                            FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
            .checkerboardOrigin = 0
        }
    };
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
        m_impl->m_gameTrace.Abort(err.what());
        LOG_ERROR("FSRD output composition failed. Details: {}", err.what());
    }

    return false;
}

void FSRDPreprocessor_Dx12::InvalidateCompositionHistory() noexcept
{
    m_impl->m_recoveryHistoryValid = false;
    m_impl->ResetFlatTemporalHistory();
}

void FSRDPreprocessor_Dx12::FinishCompositionHistory(bool successfulNormalFrame) noexcept
{
    // A failed or debug frame leaves the recovery history unproven.
    if (!successfulNormalFrame)
    {
        m_impl->m_research.Abort("Reference aborted: normal evaluation failed or was bypassed.");
        m_impl->m_recoveryHistoryValid=false;
        m_impl->ResetFlatTemporalHistory();
        if (m_impl->m_gameTraceFrameRecorded)
            m_impl->m_gameTrace.Abort("Normal evaluation failed or bypassed after recording.");
    }
}

void FSRDPreprocessor_Dx12::TransitionDenoiserOutputsToRead(ID3D12GraphicsCommandList* cmdList) noexcept
{
    m_impl->TransitionDenoiserOutputsToRead(cmdList);
}

void FSRDPreprocessor_Dx12::TransitionDenoiserOutputsToUav(ID3D12GraphicsCommandList* cmdList) noexcept
{
    m_impl->TransitionDenoiserOutputsToUav(cmdList);
}

void FSRDPreprocessor_Dx12::RestoreTitleInputStates(ID3D12GraphicsCommandList* cmdList) noexcept
{
    if (m_impl->m_rrLinearDepthForwarded && m_impl->m_rrLinearDepth != nullptr && cmdList != nullptr)
    {
        AddBarrier(cmdList, m_impl->m_rrLinearDepth, kSrvState,
                   static_cast<D3D12_RESOURCE_STATES>(m_impl->m_rrLinearDepthDeclaredState));
        m_impl->m_rrLinearDepthForwarded = false;
    }
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
    // With a recovery pass active its output is the final composition.
    return m_impl->CompositionColor();
}

ID3D12Resource* FSRDPreprocessor_Dx12::PrepareComparePresentation(
    ID3D12GraphicsCommandList* cmdList, uint32_t dstWidth, uint32_t dstHeight,
    bool swap, float split, bool hold)
{
    try
    {
        return m_impl->PrepareComparePresentation(cmdList, dstWidth, dstHeight, swap, split, hold);
    }
    catch (const std::exception& err)
    {
        LOG_ERROR("Failed to prepare the compare (split) view presentation. Details: {}", err.what());
    }
    return nullptr;
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetDenoiserDiffuseOutput() const
{
    return m_impl->m_outputBuffer2.Get();
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetDenoiserDiffuseInputSignal() const
{
    return m_impl->m_out.Resources.Signals.DirectDiffuse.Get();
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetDenoiserSpecularOutput() const
{
    return m_impl->m_outputBuffer1.Get();
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetDenoiserNormalsInput() const
{
    return m_impl->m_out.Resources.Normals.Get();
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetDenoiserMotionInput() const
{
    return m_impl->m_out.Resources.Motion.Get();
}

void FSRDPreprocessor_Dx12::CompleteAdditiveCapture(ID3D12GraphicsCommandList* cmdList,
    const ffxDispatchDescDenoiser& dispatch, const CompositionDesc& composition,
    float preExposure, bool preExposureProvided) noexcept
{
    m_impl->CompleteAdditiveCapture(cmdList,dispatch,composition,preExposure,preExposureProvided);
}

ID3D12Resource* FSRDPreprocessor_Dx12::GetDenoiserLinearDepthInput() const
{
    return m_impl->m_LinearDepth.Get();
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

void FSRDPreprocessor_Dx12::CompleteGameTraceFrame(ID3D12GraphicsCommandList* cmdList,
    const ffxDispatchDescDenoiser& dispatch, uint64_t contextGeneration, uint64_t evaluationId,
    const std::string& controlsJson, const std::string& settingsJson,
    std::span<const FSRDGameTraceSession::DiagnosticSource> diagnostics) noexcept
{
    auto& impl = *m_impl;
    if (!impl.m_gameTraceFrameRecorded) return;
    try
    {
    FSRDGameTraceSession::FrameInfo frame {};
    frame.contextId = std::format("RR-generation-{}", contextGeneration);
    frame.evaluationId = evaluationId;
    frame.frameIndex = dispatch.frameIndex;
    frame.dispatchFlags = dispatch.flags;
    frame.reset = (dispatch.flags & FFX_DENOISER_DISPATCH_RESET) != 0;
    frame.controlsJson = controlsJson;
    frame.settingsJson = settingsJson;
    std::array<FSRDGameTraceSession::DiagnosticSource,2> lobes {{
        {"rr_specular", {impl.m_outputBuffer1.Get(), kSrvState}, 0, 0},
        {"rr_diffuse", {impl.m_outputBuffer2.Get(), kSrvState}, 0, 0}
    }};
    const auto settings = nlohmann::json::parse(settingsJson);
    for (size_t i=0; i<lobes.size(); ++i)
    {
        lobes[i].active = settings.at(i == 0 ? "denoise_specular" : "denoise_diffuse").get<bool>();
        if (!lobes[i].active)
        {
            lobes[i].image.resource = nullptr;
            lobes[i].inactiveReason = "This SDK lobe was disabled for the captured evaluation.";
        }
    }
    auto* output = GetCompositionOutput();
    {
        std::vector<FSRDGameTraceSession::DiagnosticSource> allDiagnostics(lobes.begin(),lobes.end());
        if (impl.m_flatDetailActive)
        {
            const auto add = [&](const char* name, ID3D12Resource* resource) {
                FSRDGameTraceSession::DiagnosticSource source {name,{resource,kSrvState},0,0};
                source.metadataJson = nlohmann::json{{"stage","post_flat_detail"},{"current_frame_only",!impl.m_flatTemporalActive},
                    {"radius",impl.m_flatDetailConstants.Radius},{"noise_scale",impl.m_flatDetailConstants.NoiseScale},
                    {"epsilon",impl.m_flatDetailConstants.Epsilon},{"strength",impl.m_flatDetailConstants.Strength},
                    {"anchor",impl.m_flatDetailConstants.Anchor},{"mix",impl.m_flatDetailConstants.Mix},
                    {"temporal_denoise",impl.m_flatDetailConstants.TemporalDenoise},
                    {"valid_pixels","packed_normals alpha = 1/3; skip alpha != -1"}}.dump();
                allDiagnostics.push_back(std::move(source));
            };
            add("flat_detail_reference",impl.m_flatDetailReference[(FlatDetail::kRefinementPasses & 1u) ^
                (impl.m_flatTemporalActive ? 1u : 0u)].Get());
            add("flat_detail_statistics",impl.m_flatDetailStatistics[FlatDetail::kRefinementPasses & 1u].Get());
            add("flat_detail_base",impl.m_flatDetailBase.Get());
            add("flat_detail_rr_mean",impl.m_flatDetailMean.Get());
            add("flat_detail_anchor_sigma",impl.m_flatDetailVariance.Get());
            if (impl.m_flatTemporalActive)
            {
                const auto& t = impl.m_flatTemporalConstants;
                const auto historyDiagnostic = [&](const char* name, unsigned channel) {
                    FSRDGameTraceSession::DiagnosticSource source {name,{impl.m_flatTemporalDiagnostics.Get(),kSrvState},0,0};
                    source.metadataJson = nlohmann::json{{"stage","post_flat_temporal"},{"channel",channel},
                        {"channel_names",{"valid_sample_count","summed_history_weight"}},
                        {"history_count",t.HistoryCount},{"history_head",t.HistoryHead},{"history_length",t.HistoryLength},
                        {"temporal_strength",t.TemporalStrength},{"epsilon",t.Epsilon},
                        {"center_sigma",t.CenterSigma},{"motion_start",t.MotionStart},{"motion_end",t.MotionEnd},
                        {"history_decay",t.HistoryDecay},{"flags",t.Flags},
                        {"jitter_delta",{t.JitterDelta.x,t.JitterDelta.y}},
                        {"full_render_size",{t.FullRenderSize.x,t.FullRenderSize.y}},
                        {"valid_pixels","flat mask only; zero count/weight on reset or rejected history"}}.dump();
                    allDiagnostics.push_back(std::move(source));
                };
                historyDiagnostic("flat_detail_history_valid_count",0);
                historyDiagnostic("flat_detail_history_weight",1);
            }
        }
        allDiagnostics.insert(allDiagnostics.end(),diagnostics.begin(),diagnostics.end());
        impl.m_gameTrace.RecordNative(cmdList, {output,kSrvState}, frame, allDiagnostics);
    }
    impl.m_gameTrace.CompleteFrame(cmdList, {output,kSrvState});
    }
    catch (const std::exception& error) { impl.m_gameTrace.Abort(error.what()); }
    catch (...) { impl.m_gameTrace.Abort("Game trace output metadata unavailable."); }
}

void FSRDPreprocessor_Dx12::AbortGameTrace(const std::string& reason) noexcept
{
    m_impl->m_gameTrace.Abort(reason);
    m_impl->m_gameTraceFrameRecorded = false;
}
bool FSRDPreprocessor_Dx12::HasAdmittedGameTraceFrame() const noexcept
{ return m_impl->m_gameTraceFrameRecorded; }

void FSRDPreprocessor_Dx12::CompleteGameTraceSr(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* output,
    uint32_t width, uint32_t height, uint64_t evaluationId, const std::string& contextId,
    bool reset, const std::string& controlsJson) noexcept
{
    if (!m_impl->m_gameTraceFrameRecorded) return;
    try
    {
        FSRDGameTraceSession::SrInfo info {};
        info.contextId = contextId; info.evaluationId = evaluationId; info.width = width; info.height = height;
        info.reset = reset; info.controlsJson = controlsJson;
        m_impl->m_gameTrace.CompleteSrFrame(cmdList,{output,D3D12_RESOURCE_STATE_UNORDERED_ACCESS},info);
    }
    catch (const std::exception& error) { m_impl->m_gameTrace.Abort(error.what()); }
    catch (...) { m_impl->m_gameTrace.Abort("Game trace SR metadata unavailable."); }
}

void FSRDPreprocessor_Dx12::CompleteResearchFrame(ID3D12GraphicsCommandList* cmdList,
    const std::string& settings,const std::string& controls)
{
    m_impl->m_research.Finish(cmdList,GetCompositionOutput(),m_impl->m_LinearDepth.Get(),
        m_impl->m_out.Resources.Normals.Get(),settings,controls);
}

void FSRDPreprocessor_Dx12::AbortResearch(const char* reason) {m_impl->m_research.Abort(reason);}
