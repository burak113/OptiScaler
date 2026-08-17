#include "pch.h"
#include <nvsdk_ngx_defs_dlssd.h>
#include <DirectXMath.h>
#include <d3d12sdklayers.h>
#include <cmath>
#include "NVNGX_Parameter.h"
#include "hooks/Streamline_Hooks.h"
#include "resource_tracking/ResTrack_Dx12.h"
#include "FSRDFeature_Dx12.h"
#include "shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.h"
#include "shaders/fsrd_preprocess/FSRDShaderUtils.h"
#include "MathUtils.h"

using namespace DirectX;
using namespace OptiMath;

using FSRDConvDesc = FSRDPreprocessor_Dx12::ConversionDesc;
using FSRDCompDesc = FSRDPreprocessor_Dx12::CompositionDesc;

// RR 1.2 uses the existing FFX effect-id field. These assertions prevent a
// descriptor-id packing change from silently routing RR calls to another module.
static_assert(FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER == 0x00050001u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER == 0x00050041u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_AMBIENT_OCCLUSION == 0x00050043u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE == 0x00050044u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR == 0x00050045u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE == 0x00050047u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR == 0x00050048u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_SPECULAR_OCCLUSION == 0x00050049u);
static_assert(sizeof(ffxCreateContextDescDenoiser) == 40u);
static_assert(sizeof(ffxDispatchDescDenoiser) == 448u);
static_assert(sizeof(ffxDispatchDescDenoiserAmbientOcclusion) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserDirectDiffuse) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserDirectSpecular) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserIndirectDiffuse) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserIndirectSpecular) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserSpecularOcclusion) == 120u);

static bool UseIndirectSignal(const CustomOptional<int>& setting)
{
    return std::clamp(setting.value_or_default(), 0, 1) == 1;
}

static ffxStructType_t GetDiffuseSignalDescType(
    const Config& cfg, ffxStructType_t automaticSignalType)
{
    if (!cfg.FfxDenoiserDiffuseSignalType.has_value())
        return automaticSignalType;

    return UseIndirectSignal(cfg.FfxDenoiserDiffuseSignalType)
        ? FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE
        : FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
}

static ffxStructType_t GetSpecularSignalDescType(
    const Config& cfg, ffxStructType_t automaticSignalType)
{
    if (!cfg.FfxDenoiserSpecularSignalType.has_value())
        return automaticSignalType;

    return UseIndirectSignal(cfg.FfxDenoiserSpecularSignalType)
        ? FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR
        : FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR;
}

static uint32_t GetSignalFlag(ffxStructType_t descriptorType)
{
    switch (descriptorType)
    {
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_AMBIENT_OCCLUSION:
        return FFX_DENOISER_SIGNAL_AMBIENT_OCCLUSION;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE:
        return FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR:
        return FFX_DENOISER_SIGNAL_DIRECT_SPECULAR;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE:
        return FFX_DENOISER_SIGNAL_INDIRECT_DIFFUSE;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR:
        return FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_SPECULAR_OCCLUSION:
        return FFX_DENOISER_SIGNAL_SPECULAR_OCCLUSION;
    default:
        return FFX_DENOISER_SIGNAL_NONE;
    }
}

static const char* GetSignalTypeName(ffxStructType_t descriptorType)
{
    switch (descriptorType)
    {
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_AMBIENT_OCCLUSION:
        return "AmbientOcclusion";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE:
        return "DirectDiffuse";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR:
        return "DirectSpecular";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE:
        return "IndirectDiffuse";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR:
        return "IndirectSpecular";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_SPECULAR_OCCLUSION:
        return "SpecularOcclusion";
    default:
        return "Unknown";
    }
}

class DenoiserOutputStateGuard
{
  public:
    DenoiserOutputStateGuard(
        const std::unique_ptr<FSRDPreprocessor_Dx12>& preprocessor,
        ID3D12GraphicsCommandList* commandList) :
        _preprocessor(&preprocessor), _commandList(commandList)
    {
    }

    ~DenoiserOutputStateGuard()
    {
        // Context recreation may replace the preprocessor during an evaluation
        // (for example when Auto resolves a signal type). Follow the owning
        // unique_ptr instead of retaining a raw pointer to the destroyed object.
        if (_preprocessor && *_preprocessor)
            (*_preprocessor)->TransitionDenoiserOutputsToRead(_commandList);
    }

    DenoiserOutputStateGuard(const DenoiserOutputStateGuard&) = delete;
    DenoiserOutputStateGuard& operator=(const DenoiserOutputStateGuard&) = delete;

  private:
    const std::unique_ptr<FSRDPreprocessor_Dx12>* _preprocessor;
    ID3D12GraphicsCommandList* _commandList;
};

class EvaluationFrameGuard
{
  public:
    explicit EvaluationFrameGuard(long& frameCount) : _frameCount(frameCount) {}
    ~EvaluationFrameGuard() { ++_frameCount; }

    EvaluationFrameGuard(const EvaluationFrameGuard&) = delete;
    EvaluationFrameGuard& operator=(const EvaluationFrameGuard&) = delete;

  private:
    long& _frameCount;
};

/**
 * @brief Retrieves a column-major NGX matrix into the interop layer's row-major storage,
 * while retaining column-vector multiplication semantics.
 */
static bool TryGetNGXColumnVectorMatrix(const NVSDK_NGX_Parameter& ngxParams, const char* key,
                                        DirectX::XMMATRIX& outValue)
{
    float* pMat = nullptr;

    if (ngxParams.Get(key, (void**) &pMat) == NVSDK_NGX_Result_Success && pMat != nullptr)
    {
        XMMATRIX packedMatrix = {};
        memcpy_s(&packedMatrix, sizeof(packedMatrix), pMat, sizeof(float) * 16);
        outValue = XMMatrixTranspose(packedMatrix);
        return true;
    }

    return false;
}

template <typename T>
static bool TryGetLoggedResource(const NVSDK_NGX_Parameter& ngxParams, const char* key, T*& outValue)
{
    const bool success = TryGetNGXVoidPointer(ngxParams, key, outValue);

    if (success)
        LOG_DEBUG("{} exists..", key);
    else
        LOG_ERROR("{} is missing!!", key);

    return success;
}

static XMUINT2 GetSubrectBase(const NVSDK_NGX_Parameter& ngxParams,
                              const char* xKey, const char* yKey)
{
    unsigned int x = 0;
    unsigned int y = 0;
    ngxParams.Get(xKey, &x);
    ngxParams.Get(yKey, &y);
    return { x, y };
}

static bool ValidateSourceExtent(const char* name, ID3D12Resource* resource,
                                 const XMUINT2& base, uint32_t width, uint32_t height)
{
    if (!resource)
        return false;

    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    const bool valid = desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        desc.SampleDesc.Count == 1 && desc.DepthOrArraySize == 1 &&
        uint64_t(base.x) + uint64_t(width) <= desc.Width &&
        uint64_t(base.y) + uint64_t(height) <= desc.Height;
    if (!valid)
    {
        LOG_ERROR(
            "[RR_INPUT] {} does not cover requested Texture2D subrect: resource={}x{}, base=({}, {}), extent={}x{}, dimension={}, arrays={}, samples={}",
            name, desc.Width, desc.Height, base.x, base.y, width, height,
            static_cast<uint32_t>(desc.Dimension), desc.DepthOrArraySize,
            desc.SampleDesc.Count);
    }

    return valid;
}

enum class DepthResourceKind : uint8_t
{
    Unknown,       // Neither format nor flags say anything conclusive.
    HardwareDepth, // Depth-stencil capable, so it cannot hold a linear distance.
    GameWritten,   // Render-target or UAV capable: the title produced these contents.
};

/**
 * @brief Classifies the depth resource from its D3D12 description.
 *
 * A depth-stencil format or ALLOW_DEPTH_STENCIL is conclusive - no engine writes
 * linearized view-space distance into a depth-stencil attachment. Conversely a
 * render-target or UAV capable resource was produced by the title's own shaders,
 * which makes a linear declaration credible. Everything else, typically a plain
 * copy destination or a bare typeless resource, is genuinely undecidable here.
 */
static DepthResourceKind ClassifyDepthResource(ID3D12Resource* depth)
{
    if (!depth)
        return DepthResourceKind::Unknown;

    const D3D12_RESOURCE_DESC desc = depth->GetDesc();

    if ((desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) != 0)
        return DepthResourceKind::HardwareDepth;

    switch (desc.Format)
    {
    case DXGI_FORMAT_D32_FLOAT:
    case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:
    case DXGI_FORMAT_D24_UNORM_S8_UINT:
    case DXGI_FORMAT_D16_UNORM:
    case DXGI_FORMAT_R32G8X24_TYPELESS:
    case DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS:
    case DXGI_FORMAT_R24G8_TYPELESS:
    case DXGI_FORMAT_R24_UNORM_X8_TYPELESS:
        return DepthResourceKind::HardwareDepth;

    default:
        break;
    }

    if ((desc.Flags & (D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET |
                       D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS)) != 0)
    {
        return DepthResourceKind::GameWritten;
    }

    return DepthResourceKind::Unknown;
}

static bool SupportsPackedRoughness(ID3D12Resource* normals)
{
    if (!normals)
        return false;

    switch (normals->GetDesc().Format)
    {
    case DXGI_FORMAT_R32G32B32A32_TYPELESS:
    case DXGI_FORMAT_R32G32B32A32_FLOAT:
    case DXGI_FORMAT_R16G16B16A16_TYPELESS:
    case DXGI_FORMAT_R16G16B16A16_FLOAT:
    case DXGI_FORMAT_R16G16B16A16_UNORM:
    case DXGI_FORMAT_R16G16B16A16_SNORM:
    case DXGI_FORMAT_R10G10B10A2_TYPELESS:
    case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R8G8B8A8_TYPELESS:
    case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_SNORM:
        return true;
    default:
        return false;
    }
}

static void SetColumn(const XMVECTOR& vec, int col, XMMATRIX& mat)
{
    mat.r[0].m128_f32[col] = vec.m128_f32[0];
    mat.r[1].m128_f32[col] = vec.m128_f32[1];
    mat.r[2].m128_f32[col] = vec.m128_f32[2];
    mat.r[3].m128_f32[col] = vec.m128_f32[3];
}

static XMFLOAT3 GetFloat3Column(const XMMATRIX& mat, int col)
{
    return { mat.r[0].m128_f32[col], mat.r[1].m128_f32[col], mat.r[2].m128_f32[col] };
}

/**
 * @brief Converts the interop layer's column-vector matrix into RR 1.2's canonical
 * row-major, row-vector layout.
 */
static FfxApiMatrix4x4 GetRRMatrix(const XMMATRIX& columnVectorMatrix)
{
    static_assert(sizeof(FfxApiMatrix4x4) == sizeof(XMFLOAT4X4));
    FfxApiMatrix4x4 result = {};
    XMStoreFloat4x4(reinterpret_cast<XMFLOAT4X4*>(&result), XMMatrixTranspose(columnVectorMatrix));
    return result;
}

/**
 * @brief Uploads a column-vector matrix for HLSL's default column-major cbuffer
 * storage and mul(Matrix, Vector) usage.
 */
static void StoreHlslColumnVectorMatrix(XMFLOAT4X4& destination, const XMMATRIX& columnVectorMatrix)
{
    XMStoreFloat4x4(&destination, XMMatrixTranspose(columnVectorMatrix));
}

/**
 * @brief Creates an unjittered perspective projection in the interop layer's
 * column-vector convention. A zero far distance is treated as an infinite far plane.
 */
static XMMATRIX CreateColumnVectorPerspectiveProjection(float verticalFov, float aspectRatio,
                                                        float nearPlane, float farPlane,
                                                        bool isRightHanded, bool isDepthInverted)
{
    XMMATRIX rowVectorProjection = {};

    if (farPlane == 0.0f)
    {
        const float yScale = 1.0f / std::tan(verticalFov * 0.5f);
        const float xScale = yScale / aspectRatio;
        const float W = isRightHanded ? -1.0f : 1.0f;
        const float A = isDepthInverted ? 0.0f : W;
        const float B = isDepthInverted ? nearPlane : -nearPlane;

        rowVectorProjection = XMMatrixSet(
            xScale, 0.0f,   0.0f, 0.0f,
            0.0f,   yScale, 0.0f, 0.0f,
            0.0f,   0.0f,   A,    W,
            0.0f,   0.0f,   B,    0.0f);
    }
    else
    {
        // Swapping the physical near/far arguments produces a reversed-Z projection.
        const float matrixNear = isDepthInverted ? farPlane : nearPlane;
        const float matrixFar = isDepthInverted ? nearPlane : farPlane;

        rowVectorProjection = isRightHanded
            ? XMMatrixPerspectiveFovRH(verticalFov, aspectRatio, matrixNear, matrixFar)
            : XMMatrixPerspectiveFovLH(verticalFov, aspectRatio, matrixNear, matrixFar);
    }

    return XMMatrixTranspose(rowVectorProjection);
}

static ID3D12Resource* GetD3D12ResFromFFX(const FfxApiResource& resource)
{
    return static_cast<ID3D12Resource*>(resource.resource);
}

struct RequiredRRResource
{
    const char* name;
    FfxApiResource resource;
    DXGI_FORMAT format;
};

using RequiredRRResources = std::vector<RequiredRRResource>;

static RequiredRRResources GetRequiredRRResources(
    const ffxDispatchDescDenoiser& dispatchDesc,
    const ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
    const ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular,
    const ffxDispatchDescDenoiserAmbientOcclusion* ambientOcclusion)
{
    RequiredRRResources resources {
        { "LinearDepth", dispatchDesc.linearDepth, DXGI_FORMAT_R32_FLOAT },
        { "MotionVectors", dispatchDesc.motionVectors, DXGI_FORMAT_R16G16B16A16_FLOAT },
        { "Normals", dispatchDesc.normals, DXGI_FORMAT_R10G10B10A2_UNORM },
        { "SpecularAlbedo", dispatchDesc.specularAlbedo, DXGI_FORMAT_R8G8B8A8_UNORM },
        { "DiffuseAlbedo", dispatchDesc.diffuseAlbedo, DXGI_FORMAT_R8G8B8A8_UNORM },
        { "DiffuseSignal.Input", directDiffuse.signal.input, DXGI_FORMAT_R16G16B16A16_FLOAT },
        { "DiffuseSignal.Output", directDiffuse.signal.output, DXGI_FORMAT_R16G16B16A16_FLOAT },
        { "SpecularSignal.Input", indirectSpecular.signal.input, DXGI_FORMAT_R16G16B16A16_FLOAT },
        { "SpecularSignal.Output", indirectSpecular.signal.output, DXGI_FORMAT_R16G16B16A16_FLOAT },
    };

    if (ambientOcclusion)
    {
        resources.push_back(
            { "AmbientOcclusion.Input", ambientOcclusion->signal.input, DXGI_FORMAT_R8_UNORM });
        resources.push_back(
            { "AmbientOcclusion.Output", ambientOcclusion->signal.output, DXGI_FORMAT_R8_UNORM });
    }

    return resources;
}

static bool ValidateRequiredRRResources(const ffxDispatchDescDenoiser& dispatchDesc,
                                        const ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
                                        const ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular,
                                        const ffxDispatchDescDenoiserAmbientOcclusion* ambientOcclusion)
{
    const RequiredRRResources requirements =
        GetRequiredRRResources(dispatchDesc, directDiffuse, indirectSpecular, ambientOcclusion);

    bool valid = true;

    for (const auto& requirement : requirements)
    {
        ID3D12Resource* resource = GetD3D12ResFromFFX(requirement.resource);

        if (!resource)
        {
            LOG_ERROR("Required RR 1.2 resource {} is null", requirement.name);
            valid = false;
            continue;
        }

        const D3D12_RESOURCE_DESC desc = resource->GetDesc();

        if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            desc.SampleDesc.Count != 1 || desc.DepthOrArraySize != 1 ||
            desc.Width < dispatchDesc.renderSize.width ||
            desc.Height < dispatchDesc.renderSize.height)
        {
            LOG_ERROR("Required RR 1.2 resource {} has unsupported layout or insufficient coverage: dimension={}, arraySize={}, samples={}, size={}x{}; required coverage={}x{}",
                      requirement.name, magic_enum::enum_name(desc.Dimension),
                      desc.DepthOrArraySize, desc.SampleDesc.Count, desc.Width, desc.Height,
                      dispatchDesc.renderSize.width, dispatchDesc.renderSize.height);
            valid = false;
        }

        const DXGI_FORMAT viewFormat = FSRD::GetViewFormat(desc.Format);

        if (viewFormat != requirement.format)
        {
            LOG_ERROR("Required RR 1.2 resource {} has incompatible format {}; expected {}",
                      requirement.name, magic_enum::enum_name(viewFormat),
                      magic_enum::enum_name(requirement.format));
            valid = false;
        }
    }

    return valid;
}

static void LogRRDispatchSnapshot(const ffxDispatchDescDenoiser& dispatchDesc,
                                  const ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
                                  const ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular,
                                  const ffxDispatchDescDenoiserAmbientOcclusion* ambientOcclusion)
{
    ID3D12GraphicsCommandList* commandList =
        static_cast<ID3D12GraphicsCommandList*>(dispatchDesc.commandList);
    const D3D12_COMMAND_LIST_TYPE commandListType =
        commandList ? commandList->GetType() : D3D12_COMMAND_LIST_TYPE(-1);

    LOG_INFO(
        "[RR_DIAG] dispatch snapshot: frame={}, reset={}, render={}x{}, commandList={:X}, commandListType={}, "
        "depthBounds=[{:.6f}, {:.6f}], mvScale=[{:.6f}, {:.6f}, {:.6f}], jitterPixels=[{:.6f}, {:.6f}], "
        "cameraDelta=[{:.6f}, {:.6f}, {:.6f}], flags={:#x}",
        dispatchDesc.frameIndex,
        !!(dispatchDesc.flags & FFX_DENOISER_DISPATCH_RESET),
        dispatchDesc.renderSize.width, dispatchDesc.renderSize.height,
        reinterpret_cast<uintptr_t>(dispatchDesc.commandList),
        magic_enum::enum_name(commandListType),
        dispatchDesc.linearDepthBounds.min, dispatchDesc.linearDepthBounds.max,
        dispatchDesc.motionVectorScale.x, dispatchDesc.motionVectorScale.y, dispatchDesc.motionVectorScale.z,
        dispatchDesc.jitterOffsets.x, dispatchDesc.jitterOffsets.y,
        dispatchDesc.cameraPositionDelta.x, dispatchDesc.cameraPositionDelta.y,
        dispatchDesc.cameraPositionDelta.z, dispatchDesc.flags);

    std::string chain = std::format("head={:#x}", dispatchDesc.header.type);
    for (const ffxDispatchDescHeader* signal = dispatchDesc.header.pNext;
         signal != nullptr; signal = signal->pNext)
    {
        chain += std::format(" -> {}={:#x}", GetSignalTypeName(signal->type), signal->type);
    }
    LOG_INFO("[RR_DIAG] chain: {} -> tail=0x0", chain);

    const RequiredRRResources requirements =
        GetRequiredRRResources(dispatchDesc, directDiffuse, indirectSpecular, ambientOcclusion);

    for (const RequiredRRResource& requirement : requirements)
    {
        ID3D12Resource* resource = GetD3D12ResFromFFX(requirement.resource);
        if (!resource)
        {
            LOG_ERROR("[RR_DIAG] resource {}: null", requirement.name);
            continue;
        }

        const D3D12_RESOURCE_DESC desc = resource->GetDesc();
        LOG_INFO(
            "[RR_DIAG] resource {}: ptr={:X}, size={}x{}, format={}, dimension={}, mips={}, samples={}, "
            "resourceFlags={:#x}, declaredFfxState={:#x}",
            requirement.name, reinterpret_cast<uintptr_t>(resource),
            desc.Width, desc.Height, magic_enum::enum_name(FSRD::GetViewFormat(desc.Format)),
            magic_enum::enum_name(desc.Dimension), desc.MipLevels, desc.SampleDesc.Count,
            static_cast<uint32_t>(desc.Flags), requirement.resource.state);
    }
}

static bool IsDiffuseHitDistanceFormat(DXGI_FORMAT format)
{
    return format == DXGI_FORMAT_R16_FLOAT || format == DXGI_FORMAT_R32_FLOAT;
}

static bool IsDiffuseRayDirectionHitDistanceFormat(DXGI_FORMAT format)
{
    return format == DXGI_FORMAT_R16G16B16A16_FLOAT ||
           format == DXGI_FORMAT_R32G32B32A32_FLOAT;
}

static bool CoversSourceExtent(ID3D12Resource* resource, const XMUINT2& base,
                               uint32_t width, uint32_t height)
{
    if (!resource)
        return false;

    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    return desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        desc.SampleDesc.Count == 1 &&
        uint64_t(base.x) + uint64_t(width) <= desc.Width &&
        uint64_t(base.y) + uint64_t(height) <= desc.Height;
}

using SourceFormatValidator = bool (*)(DXGI_FORMAT);

static bool ValidateReprojectionGuideSource(
    const char* name, ID3D12Resource* resource, const XMUINT2& base,
    uint32_t width, uint32_t height, SourceFormatValidator validateFormat,
    const char* expectedFormat)
{
    if (!resource)
        return false;

    const DXGI_FORMAT viewFormat = FSRD::GetViewFormat(resource->GetDesc().Format);
    if (!validateFormat(viewFormat))
    {
        LOG_ERROR("[RR_INPUT] {} has incompatible format {}; expected {}",
                  name, magic_enum::enum_name(viewFormat), expectedFormat);
        return false;
    }

    return ValidateSourceExtent(name, resource, base, width, height);
}

static bool IsEmissiveProbeCompatible(ID3D12Resource* resource)
{
    if (!resource)
        return false;

    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
        desc.Width == 0 || desc.Height == 0 ||
        desc.SampleDesc.Count != 1 || desc.DepthOrArraySize != 1)
    {
        return false;
    }

    const DXGI_FORMAT viewFormat = FSRD::GetViewFormat(desc.Format);
    switch (viewFormat)
    {
    case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8A8_UNORM:
    case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
    case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R11G11B10_FLOAT:
    case DXGI_FORMAT_R16G16B16A16_FLOAT:
    case DXGI_FORMAT_R32G32B32A32_FLOAT:
        return true;
    default:
        return false;
    }
}

static void LogRREmissiveProbe(ID3D12Resource* resource,
                               bool compatible,
                               bool fromStreamline,
                               uint32_t renderWidth,
                               uint32_t renderHeight)
{
    if (!resource)
    {
        LOG_INFO("[RR_DIAG] emissive probe: absent (checked NGX {} and Streamline Emissive tag)",
                 NVSDK_NGX_Parameter_GBuffer_Emissive);
        return;
    }

    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    const DXGI_FORMAT viewFormat = FSRD::GetViewFormat(desc.Format);
    LOG_INFO(
        "[RR_DIAG] emissive probe: present, source={}, ptr={:X}, size={}x{}, format={}, dimension={}, mips={}, samples={}, "
        "resourceFlags={:#x}, renderSize={}x{}, exactRenderSize={}, previewCompatible={}",
        fromStreamline ? "Streamline.Emissive" : NVSDK_NGX_Parameter_GBuffer_Emissive,
        reinterpret_cast<uintptr_t>(resource),
        desc.Width, desc.Height, magic_enum::enum_name(viewFormat),
        magic_enum::enum_name(desc.Dimension), desc.MipLevels, desc.SampleDesc.Count,
        static_cast<uint32_t>(desc.Flags), renderWidth, renderHeight,
        desc.Width == renderWidth && desc.Height == renderHeight,
        compatible);
}

static void LogRRDiffuseHitDistanceProbe(const char* parameterName,
                                         ID3D12Resource* resource,
                                         uint32_t subrectBaseX,
                                         uint32_t subrectBaseY,
                                         uint32_t renderWidth,
                                         uint32_t renderHeight,
                                         bool combinedDirectionAndDistance)
{
    if (!resource)
    {
        LOG_INFO("[RR_DIAG] NGX probe {}: absent", parameterName);
        return;
    }

    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    const DXGI_FORMAT viewFormat = FSRD::GetViewFormat(desc.Format);
    const bool compatibleFormat = combinedDirectionAndDistance
        ? IsDiffuseRayDirectionHitDistanceFormat(viewFormat)
        : IsDiffuseHitDistanceFormat(viewFormat);
    const uint64_t requiredWidth = static_cast<uint64_t>(subrectBaseX) + renderWidth;
    const uint64_t requiredHeight = static_cast<uint64_t>(subrectBaseY) + renderHeight;
    const bool coversRenderArea =
        desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        desc.Width >= requiredWidth && desc.Height >= requiredHeight;

    LOG_INFO(
        "[RR_DIAG] NGX probe {}: present, ptr={:X}, size={}x{}, format={}, dimension={}, mips={}, samples={}, "
        "resourceFlags={:#x}, subrectBase=[{}, {}], expected={}, compatibleFormat={}, coversRenderArea={}",
        parameterName, reinterpret_cast<uintptr_t>(resource),
        desc.Width, desc.Height, magic_enum::enum_name(viewFormat),
        magic_enum::enum_name(desc.Dimension), desc.MipLevels, desc.SampleDesc.Count,
        static_cast<uint32_t>(desc.Flags), subrectBaseX, subrectBaseY,
        combinedDirectionAndDistance ? "RGBA16_FLOAT/RGBA32_FLOAT (distance in A)"
                                     : "R16_FLOAT/R32_FLOAT",
        compatibleFormat, coversRenderArea);
}

static void LogRRGBufferIdentityProbe(const char* parameterName,
                                      ID3D12Resource* resource,
                                      uint32_t renderWidth,
                                      uint32_t renderHeight)
{
    if (!resource)
    {
        LOG_INFO("[RR_DIAG] NGX identity probe {}: absent", parameterName);
        return;
    }

    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    const DXGI_FORMAT viewFormat = FSRD::GetViewFormat(desc.Format);
    const bool exactRenderSize =
        desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        desc.Width == renderWidth && desc.Height == renderHeight;

    LOG_INFO(
        "[RR_DIAG] NGX identity probe {}: present, ptr={:X}, size={}x{}, format={}, dimension={}, mips={}, samples={}, "
        "resourceFlags={:#x}, exactRenderSize={}; diagnostic-only, value encoding and temporal stability are unverified",
        parameterName, reinterpret_cast<uintptr_t>(resource),
        desc.Width, desc.Height, magic_enum::enum_name(viewFormat),
        magic_enum::enum_name(desc.Dimension), desc.MipLevels, desc.SampleDesc.Count,
        static_cast<uint32_t>(desc.Flags), exactRenderSize);
}

static void LogRRD3D12Messages(ID3D12InfoQueue* infoQueue, uint64_t firstMessage,
                               std::string_view scope)
{
    if (!infoQueue)
        return;

    const uint64_t messageCount = infoQueue->GetNumStoredMessagesAllowedByRetrievalFilter();
    firstMessage = std::min(firstMessage, messageCount);

    constexpr uint64_t kMaxLoggedMessages = 32;
    uint64_t loggedMessages = 0;
    uint64_t matchingMessages = 0;

    for (uint64_t messageIndex = firstMessage; messageIndex < messageCount; ++messageIndex)
    {
        SIZE_T messageSize = 0;
        if (FAILED(infoQueue->GetMessage(messageIndex, nullptr, &messageSize)) || messageSize == 0)
            continue;

        std::vector<uint8_t> storage(messageSize);
        D3D12_MESSAGE* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
        if (FAILED(infoQueue->GetMessage(messageIndex, message, &messageSize)))
            continue;

        if (message->Severity > D3D12_MESSAGE_SEVERITY_WARNING)
            continue;

        ++matchingMessages;
        if (loggedMessages >= kMaxLoggedMessages)
            continue;

        ++loggedMessages;
        LOG_WARN("[RR_DIAG][D3D12][{}] severity={}, category={}, id={} ({}) - {}",
                 scope, magic_enum::enum_name(message->Severity),
                 magic_enum::enum_name(message->Category), static_cast<uint32_t>(message->ID),
                 magic_enum::enum_name(message->ID), message->pDescription);
    }

    if (matchingMessages == 0)
    {
        LOG_INFO("[RR_DIAG][D3D12][{}] no corruption/error/warning messages were captured", scope);
    }
    else if (matchingMessages > loggedMessages)
    {
        LOG_WARN("[RR_DIAG][D3D12][{}] {} additional messages were omitted",
                 scope, matchingMessages - loggedMessages);
    }
}

struct ViewPlanes
{
    float nearPlane;
    float farPlane;
    bool isInfinite;
    bool isRightHanded;
};

static ViewPlanes GetViewPlanes(const DirectX::XMMATRIX& projection, bool isInverted)
{
    ViewPlanes planes = {};

    // Internal projection convention: row-major storage with column vectors.
    // clip.z = A * view.z + B; clip.w = W * view.z.
    const float A = projection.r[2].m128_f32[2];
    const float B = projection.r[2].m128_f32[3];
    const float W = projection.r[3].m128_f32[2];

    // A is the projection's depth term and W its perspective divide. On an infinite
    // far plane A is mathematically zero, but it survives matrix inversion as float
    // noise - values around 1e-6 are routine - so an absolute epsilon misclassifies
    // the projection as finite and the far plane below is then computed by dividing
    // by that noise. Cyberpunk lands on A = -1.19e-6 and produces a fabricated
    // 16777 unit far plane that way. Scale the test to W so it measures a ratio.
    const float infiniteCheckVal = isInverted ? A : (A - W);
    const float infiniteCheckScale = std::max(std::abs(W), 1e-12f);
    planes.isInfinite = std::abs(infiniteCheckVal) < 1e-4f * infiniteCheckScale;
    // W is +1 for LH projections and -1 for RH projections, independent of Z direction.
    planes.isRightHanded = W < 0.0f;

    // An infinite projection has no true far plane, but this value is consumed as a
    // log-normalisation denominator, as a depth clamp, and as RR's linearDepthBounds.
    // FLT_MAX degrades all three - log(3.4e38) is 88.7, which flattens every
    // realistic depth to the bottom tenth of the range - so report a large finite
    // horizon instead. FP16 max keeps it representable everywhere downstream.
    constexpr float kInfiniteHorizon = 65504.0f;

    if (isInverted)
    {
        // Inverted: Near is at D=1, Far is at D=0
        // 1 = A/W + B/(n*W) -> n = B / (W - A)
        planes.nearPlane = std::abs(B / (W - A));

        // 0 = A/W + B/(f*W) -> f = -B / A
        planes.farPlane = planes.isInfinite ? kInfiniteHorizon : std::abs(-B / A);
    }
    else
    {
        // Standard: Near is at D=0, Far is at D=1
        // 0 = A/W + B/(n*W) -> n = -B / A
        planes.nearPlane = std::abs(-B / A);

        // 1 = A/W + B/(f*W) -> f = B / (W - A)
        planes.farPlane = planes.isInfinite
            ? kInfiniteHorizon
            : std::abs(B / (W - A));
    }

    // A finite branch that survived the ratio test can still be wildly off if the
    // projection terms are noisy, so keep the result inside a range that cannot
    // break the consumers above.
    if (!std::isfinite(planes.nearPlane) || planes.nearPlane <= 0.0f)
    {
        // A degenerate or noisy projection divides by a term that is effectively
        // zero above. The near plane is consumed directly as RR's
        // linearDepthBounds.min and as the conversion shaders' depth clamp, so a
        // NaN here spreads into every reconstructed view-space position. Substitute
        // a usable default; the caller logs the resulting planes when they change.
        constexpr float kDefaultNearPlane = 0.01f;
        planes.nearPlane = kDefaultNearPlane;
        planes.farPlane = kInfiniteHorizon;
    }
    else if (!std::isfinite(planes.farPlane))
    {
        // std::clamp propagates NaN rather than replacing it, so filter it first.
        planes.farPlane = kInfiniteHorizon;
    }
    else
    {
        planes.farPlane = std::clamp(
            planes.farPlane, planes.nearPlane * 2.0f, kInfiniteHorizon);
    }

    return planes;
}

using FSRDConvFlags = FSRDPreprocessor_Dx12::ConvFlags;
using FSRDCompFlags = FSRDPreprocessor_Dx12::CompFlags;

enum class DebugModes : uint64_t
{
    None = 0,
    DenoiserBypass = 1,
    UpscalerBypass = 2,
    RawColor = 3,
    DlssBias = 4,
    DlssColorBeforeParticles = 5,
    DlssColorBeforeTransparency = 6,
    DlssTransparencyLayer = 7,
    FfxDebug = 8,
    AmbientOcclusionInput = 9,
    AmbientOcclusionOutput = 10,

    ConversionDebug = FSRDConvFlags::Debug,
    ConversionDebugMask = FSRDConvFlags::DebugModeMask,

    OutRadiance = FSRDConvFlags::DebugOutRadiance,

    InSpecHitDist = FSRDConvFlags::DebugInSpecHitDist,
    InMotion = FSRDConvFlags::DebugInMotion,
    InNormals = FSRDConvFlags::DebugInNormals,
    InRoughness = FSRDConvFlags::DebugInRoughness,
    InDiffAlbedo = FSRDConvFlags::DebugInDiffAlbedo,
    InSpecAlbedo = FSRDConvFlags::DebugInSpecAlbedo,

    OutSignalSplit = FSRDConvFlags::DebugOutSignalSplit,
    OutLinearDepth = FSRDConvFlags::DebugOutLinearDepth,
    OutMotion = FSRDConvFlags::DebugOutMotion,
    OutNormals = FSRDConvFlags::DebugOutNormals,
    OutSpecAlbedo = FSRDConvFlags::DebugOutSpecAlbedo,
    OutDiffAlbedo = FSRDConvFlags::DebugOutDiffAlbedo,

    OutDepthDelta = FSRDConvFlags::DebugOutDepthDelta,
    NormDepth = FSRDConvFlags::DebugNormDepth,
    AlbedoError = FSRDConvFlags::DebugAlbedoError,

    FloorVariance = FSRDConvFlags::DebugFloorVariance,
    FloorColor = FSRDConvFlags::DebugFloorColor,
    RawIndirectSpecular = FSRDConvFlags::DebugRawIndirectSpecular,
    EffectiveRoughness = FSRDConvFlags::DebugEffectiveRoughness,
    RawRoughness = FSRDConvFlags::DebugRawRoughness,
    EmissiveMask = FSRDConvFlags::DebugEmissiveMask,
    AppliedRoughnessFloor = FSRDConvFlags::DebugAppliedRoughnessFloor,
    ResourceInspector = FSRDConvFlags::DebugResourceInspector,
    MaterialType = FSRDConvFlags::DebugMaterialType,
    InEmissive = FSRDConvFlags::DebugInEmissive,
    RRMaterialType = FSRDConvFlags::DebugRRMaterialType,
    AlbedoStructure = FSRDConvFlags::DebugAlbedoStructure,
    ZeroRoughFloor = FSRDConvFlags::DebugZeroRoughFloor,

    CompositionDebugOffset = 16u,
    CompositionDebug = (uint64_t) FSRDCompFlags::Debug << CompositionDebugOffset,
    CompositionDebugMask = (uint64_t)FSRDCompFlags::DebugModeMask,

    Correlation = (uint64_t)FSRDCompFlags::DebugCorrelation << CompositionDebugOffset,
    SkipSignal = (uint64_t) FSRDCompFlags::DebugSkipSignal << CompositionDebugOffset,
    DenoiserOutput = (uint64_t) FSRDCompFlags::DebugDenoiserOutput << CompositionDebugOffset,
    DirectSpecular = (uint64_t) FSRDCompFlags::DebugDirectSpecular << CompositionDebugOffset,
    IndirectSpecular = (uint64_t) FSRDCompFlags::DebugIndirectSpecular << CompositionDebugOffset,
    DirectDiffuse = (uint64_t) FSRDCompFlags::DebugDirectDiffuse << CompositionDebugOffset,
    IndirectDiffuse = (uint64_t) FSRDCompFlags::DebugIndirectDiffuse << CompositionDebugOffset,
    HandoverRRBand = (uint64_t) FSRDCompFlags::DebugHandoverRRBand << CompositionDebugOffset,
    HandoverDetailBand = (uint64_t) FSRDCompFlags::DebugHandoverDetailBand << CompositionDebugOffset,
    HandoverBandMix = (uint64_t) FSRDCompFlags::DebugHandoverBandMix << CompositionDebugOffset,
    HandoverAnchor = (uint64_t) FSRDCompFlags::DebugHandoverAnchor << CompositionDebugOffset,
    HandoverWeight = (uint64_t) FSRDCompFlags::DebugHandoverWeight << CompositionDebugOffset,
};

static FSRDConvFlags GetConvDebugFlags(DebugModes mode) 
{ 
    uint32_t flags = uint32_t(mode);
    flags &= uint32_t(DebugModes::ConversionDebugMask);
    return FSRDConvFlags(flags);
}

static FSRDCompFlags GetCompDebugFlags(DebugModes mode) 
{ 
    uint64_t flags = uint64_t(mode);
    flags >>= uint64_t(DebugModes::CompositionDebugOffset);
    flags &= uint64_t(DebugModes::CompositionDebugMask);
    return FSRDCompFlags(flags);
}

using ModeNamePair = std::pair<const char*, uint64_t>;
constexpr auto kDebugModes = std::to_array<ModeNamePair>(
{
    { "None", (uint64_t) DebugModes::None },
    { "DebugOverview", (uint64_t) DebugModes::FfxDebug },

    { "DenoiserBypass", (uint64_t) DebugModes::DenoiserBypass },
    { "UpscalerBypass", (uint64_t) DebugModes::UpscalerBypass },
    { "DenoiserOutput", (uint64_t) DebugModes::DenoiserOutput },
    { "SkipSignal", (uint64_t) DebugModes::SkipSignal },

    { "RawColor", (uint64_t) DebugModes::RawColor },
    { "DlssBias", (uint64_t) DebugModes::DlssBias },
    { "DlssColorBeforeParticles", (uint64_t) DebugModes::DlssColorBeforeParticles },
    { "DlssColorBeforeTransparency", (uint64_t) DebugModes::DlssColorBeforeTransparency },
    { "DlssTransparencyLayer", (uint64_t) DebugModes::DlssTransparencyLayer },
    { "AmbientOcclusionInput", (uint64_t) DebugModes::AmbientOcclusionInput },
    { "AmbientOcclusionOutput", (uint64_t) DebugModes::AmbientOcclusionOutput },

    { "InputMotionVectors", (uint64_t) DebugModes::InMotion },
    { "InNormals", (uint64_t) DebugModes::InNormals },
    { "InputRoughness", (uint64_t) DebugModes::InRoughness },
    { "RawRoughness", (uint64_t) DebugModes::RawRoughness },
    { "EmissiveMask", (uint64_t) DebugModes::EmissiveMask },
    { "AppliedRoughnessFloor", (uint64_t) DebugModes::AppliedRoughnessFloor },
    { "ZeroRoughnessMaterialType", (uint64_t) DebugModes::MaterialType },
    { "ResourceInspector", (uint64_t) DebugModes::ResourceInspector },
    { "SpecularHitDistance", (uint64_t) DebugModes::InSpecHitDist },
    { "InDiffAlbedo", (uint64_t) DebugModes::InDiffAlbedo },
    { "InSpecAlbedo", (uint64_t) DebugModes::InSpecAlbedo },
    { "InputEmissive", (uint64_t) DebugModes::InEmissive },
    { "RRMaterialType", (uint64_t) DebugModes::RRMaterialType },
    { "AlbedoStructureAvailability", (uint64_t) DebugModes::AlbedoStructure },
    { "ZeroRoughFloorOutput", (uint64_t) DebugModes::ZeroRoughFloor },

    { "OutRadiance", (uint64_t) DebugModes::OutRadiance },
    { "OutSignalSplit", (uint64_t) DebugModes::OutSignalSplit },
    { "OutLinearDepth", (uint64_t) DebugModes::OutLinearDepth },
    { "RRMotionVectors", (uint64_t) DebugModes::OutMotion },
    { "OutNormals", (uint64_t) DebugModes::OutNormals },
    { "OutSpecAlbedo", (uint64_t) DebugModes::OutSpecAlbedo },
    { "OutDiffAlbedo", (uint64_t) DebugModes::OutDiffAlbedo },
    { "OutDepthDelta", (uint64_t) DebugModes::OutDepthDelta },
    { "NormDepth", (uint64_t) DebugModes::NormDepth },

    { "AlbedoError", (uint64_t) DebugModes::AlbedoError },
    { "Correlation", (uint64_t) DebugModes::Correlation },

    { "HandoverRRLowBand", (uint64_t) DebugModes::HandoverRRBand },
    { "HandoverDetailHighBand", (uint64_t) DebugModes::HandoverDetailBand },
    { "HandoverBandMix", (uint64_t) DebugModes::HandoverBandMix },
    { "HandoverRRAnchor", (uint64_t) DebugModes::HandoverAnchor },
    { "HandoverEffectiveWeight", (uint64_t) DebugModes::HandoverWeight },

    { "FloorVariance", (uint64_t) DebugModes::FloorVariance },
    { "FloorColor", (uint64_t) DebugModes::FloorColor },
    
    { "RawSpecularSignal", (uint64_t) DebugModes::RawIndirectSpecular },
    { "DenoisedDirectSpecSignal", (uint64_t) DebugModes::DirectSpecular },
    { "DenoisedIndirectSpecSignal", (uint64_t) DebugModes::IndirectSpecular },
    { "EffectiveRoughness", (uint64_t) DebugModes::EffectiveRoughness },
    { "DenoisedDirectDiffuseSignal", (uint64_t) DebugModes::DirectDiffuse },
    { "DenoisedIndirectDiffuseSignal", (uint64_t) DebugModes::IndirectDiffuse },
});

FSRDFeatureDx12::FSRDFeatureDx12(uint32_t InHandleId, NVSDK_NGX_Parameter* InParameters) : 
    FSR31FeatureDx12(InHandleId, InParameters),
    IFeature(InHandleId, SetParameters(InParameters)),  
    _pDenoiserCtx(nullptr), 
    _denoiserCtxDesc({}),
    _denoiserSettings({}), 
    _convDesc({})
{
    _moduleLoaded = FfxApiProxy::IsDenoiserApiImplementedDx12();

    if (_moduleLoaded)
        LOG_INFO("amd_fidelityfx_denoiser_dx12.dll methods loaded!");
    else if (FfxApiProxy::IsDenoiserReady())
    {
        const feature_version version = FfxApiProxy::VersionDx12_RR();
        LOG_ERROR("amd_fidelityfx_denoiser_dx12.dll {}.{}.{} loaded, but this dispatch backend is not implemented",
                  version.major, version.minor, version.patch);
    }
    else
        LOG_ERROR("can't load amd_fidelityfx_denoiser_dx12.dll methods!");
}

FSRDFeatureDx12::~FSRDFeatureDx12() 
{
    if (State::Instance().isShuttingDown)
        return;

    DestroyDenoiserContext();
}

bool FSRDFeatureDx12::AcquireSLTaggedResource(
    const RRD3D12SignalTagSnapshot& snapshot, RRTaggedSignal signal,
    const char* sourceName, bool requireShaderRead,
    Microsoft::WRL::ComPtr<ID3D12Resource>& resource,
    RRTaggedResourceDiagnostic& diagnostic)
{
    resource.Reset();
    diagnostic = {};

    const size_t index = static_cast<size_t>(signal);
    if (index >= snapshot.resources.size())
        return false;

    const auto& entry = snapshot.resources[index];
    diagnostic = entry.diagnostic;
    if (!diagnostic.observed || !diagnostic.present)
        return false;

    if (diagnostic.lifecycle == sl::ResourceLifecycle::eOnlyValidNow &&
        diagnostic.source != RRTagSource::EvaluateFeature)
    {
        LOG_DEBUG(
            "[RR_INPUT] {} uses Streamline eOnlyValidNow outside the active EvaluateFeature call; refusing a cached binding",
            sourceName);
        return false;
    }

    const uint32_t activeFrame = snapshot.activeEvaluationFrame;
    const uint32_t activeViewport = snapshot.activeEvaluationViewport;
    if (activeFrame == UINT32_MAX || activeViewport == UINT32_MAX)
    {
        LOG_DEBUG(
            "[RR_INPUT] {} has no active Streamline frame/viewport; refusing an uncorrelated tag",
            sourceName);
        return false;
    }

    if (diagnostic.viewport != activeViewport)
    {
        LOG_DEBUG(
            "[RR_INPUT] {} belongs to Streamline viewport {}, active viewport is {}; rejecting cross-viewport tag",
            sourceName, diagnostic.viewport, activeViewport);
        return false;
    }

    const bool isLegacyTag = diagnostic.frameIndex == UINT32_MAX;

    if (!isLegacyTag)
    {
        if (diagnostic.frameIndex != activeFrame)
        {
            LOG_DEBUG(
                "[RR_INPUT] {} belongs to Streamline frame {}, active frame is {}; rejecting stale tag",
                sourceName, diagnostic.frameIndex, activeFrame);
            return false;
        }
    }
    else
    {
        // Legacy slSetTag has no frame token. Allow a newly submitted update and
        // repeated acquisition during this same evaluation, but never reuse it in
        // a later frame after its Present/Evaluate lifetime may have expired.
        const uint64_t lastUpdate = _lastConsumedSLTagUpdates[index];
        const uint32_t lastFrame = _lastConsumedSLTagFrames[index];
        if (diagnostic.updateCount < lastUpdate ||
            (diagnostic.updateCount == lastUpdate && lastFrame != activeFrame))
        {
            LOG_DEBUG(
                "[RR_INPUT] {} legacy tag update {} was already consumed in frame {}; rejecting stale reuse in frame {}",
                sourceName, diagnostic.updateCount, lastFrame, activeFrame);
            return false;
        }
    }

    if (!entry.resource || entry.resource.Get() != diagnostic.resourceAddress)
    {
        LOG_WARN(
            "[RR_INPUT] {} atomic tag snapshot has no matching retained D3D12 resource (generation={})",
            sourceName, snapshot.generation);
        return false;
    }

    if (diagnostic.state == UINT32_MAX)
    {
        LOG_WARN("[RR_INPUT] {} has no declared D3D12 resource state", sourceName);
        return false;
    }

    const D3D12_RESOURCE_STATES declaredState =
        static_cast<D3D12_RESOURCE_STATES>(diagnostic.state);
    if (requireShaderRead &&
        (declaredState & D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE) == 0)
    {
        LOG_WARN(
            "[RR_INPUT] {} is not declared NON_PIXEL_SHADER_RESOURCE (state={:#x}); refusing an untracked external-state transition",
            sourceName, diagnostic.state);
        return false;
    }

    const D3D12_RESOURCE_DESC desc = entry.resource->GetDesc();
    if (desc.Width != diagnostic.nativeWidth ||
        desc.Height != diagnostic.nativeHeight ||
        desc.Format != diagnostic.format ||
        desc.Dimension != diagnostic.dimension ||
        desc.DepthOrArraySize != diagnostic.arraySize ||
        desc.MipLevels != diagnostic.mipLevels ||
        desc.SampleDesc.Count != diagnostic.sampleCount)
    {
        LOG_WARN(
            "[RR_INPUT] {} resource description no longer matches its atomic tag metadata",
            sourceName);
        return false;
    }

    // Record legacy-tag consumption only after the tag has cleared every check.
    // Recording it earlier marks a tag consumed that we then reject, and the
    // staleness rule above would refuse that same updateCount on every later frame
    // unless the game happens to re-submit the tag.
    if (isLegacyTag)
    {
        _lastConsumedSLTagUpdates[index] = diagnostic.updateCount;
        _lastConsumedSLTagFrames[index] = activeFrame;
    }

    resource = entry.resource;
    return true;
}

bool FSRDFeatureDx12::AcquireTaggedAmbientOcclusionResources(bool logFailure)
{
    _ambientOcclusionNoisy.Reset();
    _ambientOcclusionDenoised.Reset();

    const RRD3D12SignalTagSnapshot snapshot =
        StreamlineHooks::getRRD3D12SignalTagSnapshot();
    RRTaggedResourceDiagnostic noisy {};
    RRTaggedResourceDiagnostic denoised {};
    Microsoft::WRL::ComPtr<ID3D12Resource> noisyResource;
    Microsoft::WRL::ComPtr<ID3D12Resource> denoisedResource;
    const bool acquiredNoisy = AcquireSLTaggedResource(
        snapshot, RRTaggedSignal::AmbientOcclusionNoisy,
        "Streamline.AmbientOcclusionNoisy", true, noisyResource, noisy);
    const bool acquiredDenoised = AcquireSLTaggedResource(
        snapshot, RRTaggedSignal::AmbientOcclusionDenoised,
        "Streamline.AmbientOcclusionDenoised", false,
        denoisedResource, denoised);

    const auto validMetadata = [this](const RRTaggedResourceDiagnostic& resource) {
        return resource.observed && resource.present &&
            resource.dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
            resource.format == DXGI_FORMAT_R8_UNORM &&
            resource.nativeWidth >= RenderWidth() && resource.nativeHeight >= RenderHeight() &&
            resource.effectiveWidth == RenderWidth() && resource.effectiveHeight == RenderHeight() &&
            resource.extentLeft == 0 && resource.extentTop == 0 &&
            resource.mipLevels == 1 && resource.arraySize == 1 && resource.sampleCount == 1 &&
            resource.state != UINT32_MAX;
    };

    if (!acquiredNoisy || !acquiredDenoised ||
        !validMetadata(noisy) || !validMetadata(denoised))
    {
        if (logFailure)
        {
            LOG_WARN(
                "[RR_AO] tagged AO requested but the noisy/denoised pair is not dispatch-safe. "
                "noisyPresent={}, denoisedPresent={}, noisy={}x{} {}, denoised={}x{} {}, noisyState={:#x}. "
                "Required: full-resolution R8_UNORM Texture2D resources and a shader-readable noisy input.",
                noisy.present, denoised.present,
                noisy.effectiveWidth, noisy.effectiveHeight, magic_enum::enum_name(noisy.format),
                denoised.effectiveWidth, denoised.effectiveHeight, magic_enum::enum_name(denoised.format),
                noisy.state);
        }
        return false;
    }

    _ambientOcclusionNoisy = std::move(noisyResource);
    _ambientOcclusionDenoised = std::move(denoisedResource);

    _ambientOcclusionNoisyState = static_cast<D3D12_RESOURCE_STATES>(noisy.state);
    _ambientOcclusionDenoisedState = static_cast<D3D12_RESOURCE_STATES>(denoised.state);
    return true;
}

bool FSRDFeatureDx12::PublishAmbientOcclusionOutput(ID3D12GraphicsCommandList* commandList)
{
    if (!_ambientOcclusionEnabled)
        return true;

    if (!_ambientOcclusionDenoised)
    {
        LOG_ERROR("[RR_AO] tagged AO output disappeared before publication");
        return false;
    }

    return FSRDConvShader->CopyAmbientOcclusionOutput(
        commandList, _ambientOcclusionDenoised.Get(), _ambientOcclusionDenoisedState,
        RenderWidth(), RenderHeight());
}

bool FSRDFeatureDx12::s_ngxDepthTypeSeen = false;
bool FSRDFeatureDx12::s_ngxReportedHWDepth = false;

bool FSRDFeatureDx12::InitFSR3(const NVSDK_NGX_Parameter* InParameters)
{
    LOG_FUNC();

    // Init upscaler first - borrow some init boilerplate and some cfg
    if (FSR31FeatureDx12::InitFSR3(InParameters))
    {
        SetInit(false);

        LOG_DEBUG("FSR Ray Regeneration Initializing");
        _name = OptiTexts::FSR_RR_Name;

        if (int value; InParameters->Get(NVSDK_NGX_Parameter_Use_HW_Depth, &value) == NVSDK_NGX_Result_Success)
        {
            _hasNGXDepthType = true;
            _ngxReportedHWDepth = value == NVSDK_NGX_DLSS_Depth_Type_HW;
            s_ngxDepthTypeSeen = true;
            s_ngxReportedHWDepth = _ngxReportedHWDepth;
        }
        else if (s_ngxDepthTypeSeen)
        {
            // The depth type is a property of the title, not of one feature instance.
            // NGX only publishes it on a creation carrying DLSSD create params, so a
            // later recreation - a resolution or preset change, or a backend switch -
            // can arrive without it. Re-deriving per instance therefore loses a
            // declaration the title already made, and the resource inference below
            // then has to guess for the rest of the session.
            _hasNGXDepthType = true;
            _ngxReportedHWDepth = s_ngxReportedHWDepth;
            LOG_INFO("[RR_INPUT] {} absent on this creation; reusing the {} type this "
                     "title declared earlier",
                     NVSDK_NGX_Parameter_Use_HW_Depth,
                     s_ngxReportedHWDepth ? "hardware" : "linear");
        }
        else
        {
            // NVSDK_NGX_DLSS_Depth_Type_Linear is zero, so a title that never fills
            // the field reads as linear. Most DLSS-RR titles actually supply a
            // hardware depth buffer, and interpreting one as a view-space distance
            // clamps the entire scene into [near, 1]: RR then sees a metre-deep
            // world, disocclusion and the depth delta stop working, and the linear
            // depth debug view goes black. Warn loudly and name the override.
            _hasNGXDepthType = false;
            _ngxReportedHWDepth = false;
            LOG_WARN(
                "[RR_INPUT] title did not publish {}; the depth type will be inferred from the "
                "depth resource, falling back to LINEAR if its format is ambiguous. If the "
                "linear-depth debug view is black or geometry-dependent behaviour looks wrong, "
                "set [FSR-RR] HardwareDepth=true in OptiScaler.ini or use Depth Input in the menu.",
                NVSDK_NGX_Parameter_Use_HW_Depth);
        }
        _isHWDepth = _ngxReportedHWDepth;

        if (int value; InParameters->Get(NVSDK_NGX_Parameter_DLSS_Roughness_Mode, &value) == NVSDK_NGX_Result_Success)
        {
            if (value == NVSDK_NGX_DLSS_Roughness_Mode_Packed)
                _roughnessSource = RoughnessSource::Packed;
            else if (value == NVSDK_NGX_DLSS_Roughness_Mode_Unpacked)
                _roughnessSource = RoughnessSource::Separate;
            else
                LOG_WARN("Unknown DLSSD roughness mode {}; deferring source selection", value);
        }

        const char* roughnessSource = _roughnessSource == RoughnessSource::Packed
            ? "packed"
            : (_roughnessSource == RoughnessSource::Separate ? "separate" : "undetermined");
        LOG_INFO("DLSSD Flags HWDepth: {} (NGX reported: {}) - RoughnessSource: {}", _isHWDepth,
                 _hasNGXDepthType ? (_ngxReportedHWDepth ? "hardware" : "linear") : "absent",
                 roughnessSource);

        _autoSpecularSignalDescType = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR;
        _autoSpecularSignalResolved = false;
        _autoDiffuseSignalDescType = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
        _autoDiffuseSignalResolved = false;

        if (!CreateDenoiserContext())
            return false;

        LOG_INFO("FSR Ray Regeneration Initialized");

        SetInit(true);
        return true;
    }
 
    return false;
}

bool FSRDFeatureDx12::CreateDenoiserContext() 
{
    ScopedSkipSpoofing skipSpoofing {};
    auto& state = State::Instance();
    const auto& cfg = *Config::Instance();

    if (!QueryDenoiserVersions())
        return false;

    InvalidateDenoiserHistory();

    const int requestedDenoiserIndex = cfg.FfxDenoiserIndex.value_or_default();
    const size_t denoiserIndex = std::clamp<size_t>(
        requestedDenoiserIndex < 0 ? 0u : static_cast<size_t>(requestedDenoiserIndex),
        0u, state.ffxDenoiserVersionIds.size() - 1u);

    if (denoiserIndex != static_cast<size_t>(std::max(requestedDenoiserIndex, 0)))
    {
        LOG_WARN("Configured RR provider index {} is unavailable; using provider index {}",
                 requestedDenoiserIndex, denoiserIndex);
    }

    const char* providerName = state.ffxDenoiserVersionNames[denoiserIndex]
        ? state.ffxDenoiserVersionNames[denoiserIndex]
        : "<unnamed>";

    state.ffxDenoiserUpscalerVersion = Version();
    parse_version(providerName);

    _diffuseSignalDescType = GetDiffuseSignalDescType(
        cfg, _autoDiffuseSignalDescType);
    _specularSignalDescType = GetSpecularSignalDescType(
        cfg, _autoSpecularSignalDescType);
    _ambientOcclusionEnabled =
        cfg.FfxDenoiserTaggedAmbientOcclusion.value_or_default() &&
        AcquireTaggedAmbientOcclusionResources(true);
    // RR 1.2 supports specular occlusion, and the preprocessor reserves an R8 output for it,
    // but Streamline exposes no semantic SO tag. Keep it source-gated until a real input exists.
    _specularOcclusionEnabled = false;

    uint32_t selectedSignalFlags =
        GetSignalFlag(_diffuseSignalDescType) | GetSignalFlag(_specularSignalDescType);
    if (_ambientOcclusionEnabled)
        selectedSignalFlags |= FFX_DENOISER_SIGNAL_AMBIENT_OCCLUSION;

    ffxOverrideVersion vidOverride = 
    {
        .header = { .type = FFX_API_DESC_TYPE_OVERRIDE_VERSION },
        .versionId = state.ffxDenoiserVersionIds[denoiserIndex]
    };
    // Create context
    // Backend desc
    ffxCreateBackendDX12Desc backendDesc = 
    { 
        .header = 
        { 
            .type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12,
            .pNext = &vidOverride.header // Chain override into backend desc
        },
        .device = Device
    };    
    // Chain: ContextDesc -> BackendDesc -> OverrideVersion.
    // DLSS-RR exposes generic diffuse/specular lighting, while RR 1.2 requires
    // direct/indirect classification. The selected approximation is configurable.
    // Preserve the allocation ceiling when this context is recreated for a
    // signal-policy change while DRS is currently below its creation size.
    const uint32_t maxRenderWidth = std::max(
        _denoiserCtxDesc.maxRenderSize.width, RenderWidth());
    const uint32_t maxRenderHeight = std::max(
        _denoiserCtxDesc.maxRenderSize.height, RenderHeight());
    _denoiserCtxDesc = 
    {
        .header = 
        { 
            .type = FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER,
            // Chain backend desc into context desc
            .pNext = &backendDesc.header
        },
        .version = FFX_DENOISER_VERSION,
        .maxRenderSize = { maxRenderWidth, maxRenderHeight },
        .signalFlags = selectedSignalFlags,
        .checkerboardSignalFlags = FFX_DENOISER_SIGNAL_NONE,
        .flags = 0
    };

    if (cfg.FfxDenoiserInternalDebugViews.value_or_default())
    {
        _denoiserCtxDesc.flags |= FFX_DENOISER_ENABLE_DEBUGGING;
        LOG_INFO("[RR_DIAG] AMD internal debug views enabled for this denoiser context");
    }

#ifdef _DEBUG
    LOG_INFO("Debug views and validation enabled for denoiser!");
    _denoiserCtxDesc.flags |= FFX_DENOISER_ENABLE_DEBUGGING | FFX_DENOISER_ENABLE_VALIDATION;
#endif

    LOG_INFO(
        "[RR_DIAG] creating context: providerIndex={}, providerName='{}', providerId={:#x}, "
        "api={}.{}.{}, maxRenderSize={}x{}, signalFlags={:#x}, checkerboardFlags={:#x}, createFlags={:#x}",
        denoiserIndex, providerName, state.ffxDenoiserVersionIds[denoiserIndex],
        FFX_DENOISER_VERSION_MAJOR, FFX_DENOISER_VERSION_MINOR, FFX_DENOISER_VERSION_PATCH,
        _denoiserCtxDesc.maxRenderSize.width, _denoiserCtxDesc.maxRenderSize.height,
        _denoiserCtxDesc.signalFlags, _denoiserCtxDesc.checkerboardSignalFlags,
        _denoiserCtxDesc.flags);
    LOG_INFO("[RR_DIAG] signal classification: diffuse={}, specular={}, ambientOcclusion={}, "
             "specularOcclusion={} (no semantic source)",
             GetSignalTypeName(_diffuseSignalDescType), GetSignalTypeName(_specularSignalDescType),
             _ambientOcclusionEnabled, _specularOcclusionEnabled);
    WLOG_INFO(L"[RR_DIAG] denoiser module: {}", FfxApiProxy::Dx12Module_Denoiser_Path());

    // Create the denoiser context
    {   
        ScopedSkipHeapCapture skipHeapCapture {};
        auto ret = FfxApiProxy::D3D12_CreateContext(&_pDenoiserCtx, &_denoiserCtxDesc.header, NULL);

        if (ret != FFX_API_RETURN_OK)
        {
            LOG_ERROR("_denoiserCtx error: {0}", FfxApiProxy::ReturnCodeToString(ret));
            return false;
        }

        LOG_INFO("[RR_DIAG] context creation succeeded: context={:X}",
                 reinterpret_cast<uintptr_t>(_pDenoiserCtx));
    }

    // Query default settings
    if (!SetDefaultConfiguration())
    {
        LOG_ERROR("Failed to query the RR 1.2 default configuration");
        DestroyDenoiserContext();
        return false;
    }

    // The queried values are AMD's tuned baseline, but the per-frame configure pass
    // overwrites every one of them with the INI values. Keep a copy so the A/B switch
    // can push AMD's numbers back without a context recreation, and record both so a
    // temporal artefact can be attributed to - or cleared of - an over-aggressive
    // override without guessing what RR would have used on its own.
    _denoiserAmdDefaults = _denoiserSettings;

    LOG_INFO("[RR_DIAG] configure baseline (AMD default -> fork default), active source={}: "
             "disocclusionThreshold={:.4f} -> {:.4f}, crossBilateralNormalStrength={:.4f} -> {:.4f}, "
             "stabilityBias={:.4f} -> {:.4f}, maxRadiance={:.1f} -> {:.1f}, "
             "radianceClipStdK={:.4f} -> {:.4f}, gaussianKernelRelaxation={:.4f} -> {:.4f}",
             cfg.FfxDenoiserUseAmdDefaults.value_or_default() ? "AMD" : "fork",
             _denoiserSettings.m_DisocclusionThreshold, cfg.FfxDenoiserDisocThreshold.value_or_default(),
             _denoiserSettings.m_CrossBilateralNormalStrength, cfg.FfxDenoiserCrossBlNormStr.value_or_default(),
             _denoiserSettings.m_StabilityBias, cfg.FfxDenoiserStabilityBias.value_or_default(),
             _denoiserSettings.m_MaxRadiance, cfg.FfxDenoiserMaxRadiance.value_or_default(),
             _denoiserSettings.m_RadianceClipStdK, cfg.FfxDenoiserRadianceClip.value_or_default(),
             _denoiserSettings.m_GaussianKernelRelaxation, cfg.FfxDenoiserGaussKernRelax.value_or_default());

    // Create DLSS-RR to FSR-RR input converter
    auto newConverter =
        std::make_unique<FSRDPreprocessor_Dx12>("FSRD Converter", Device);

    if (!newConverter->IsInit())
    {
        LOG_ERROR("Failed to initialize the FSR-RR input converter");
        DestroyDenoiserContext();
        return false;
    }

    if (!newConverter->SetMaxRenderSize(
            _denoiserCtxDesc.maxRenderSize.width,
            _denoiserCtxDesc.maxRenderSize.height))
    {
        LOG_ERROR("Failed to allocate the FSR-RR input converter");
        DestroyDenoiserContext();
        return false;
    }

    FSRDConvShader = std::move(newConverter);

    // The converter is brand new, so nothing in flight can reference its resources.
    _preprocessorHasRecordedWork = false;
    _logNextDenoiserDispatch = true;
    _lastDispatchRequestedReset = false;

    return true;
}

bool FSRDFeatureDx12::QueryDenoiserVersions() 
{
    ScopedSkipSpoofing skipSpoofing {};
    auto& state = State::Instance();

    // Get version count
    uint64_t versionCount = 0;
    ffxQueryDescGetVersions queryVersionsDesc = 
    { 
        .header = { .type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS },
        .createDescType = FFX_API_EFFECT_ID_DENOISER,
        .device = Device,
        .outputCount = &versionCount
    };
    const ffxReturnCode_t countResult = FfxApiProxy::D3D12_Query(nullptr, &queryVersionsDesc.header);

    if (countResult != FFX_API_RETURN_OK)
    {
        LOG_ERROR("Failed to query RR provider count: {}",
                  FfxApiProxy::ReturnCodeToString(countResult));
        return false;
    }

    state.ffxDenoiserVersionIds.resize(versionCount);
    state.ffxDenoiserVersionNames.resize(versionCount);

    state.ffxDenoiserDebugModes.clear();
    state.ffxDenoiserDebugModeNames.clear();

    for (const auto& mode : kDebugModes)
    {
        state.ffxDenoiserDebugModes.push_back(mode.second);
        state.ffxDenoiserDebugModeNames.emplace(mode.second, mode.first);
    }

    if (versionCount == 0)
    {
        LOG_ERROR("No FSR-RR denoisers were found.");
        return false;
    }
    else
        LOG_DEBUG("Found {} versions of FSR-RR", versionCount);

    LOG_DEBUG("Initialising FSR denoiser context");

    // Get version IDs
    queryVersionsDesc.versionIds = state.ffxDenoiserVersionIds.data();
    queryVersionsDesc.versionNames = state.ffxDenoiserVersionNames.data();
    const ffxReturnCode_t versionsResult = FfxApiProxy::D3D12_Query(nullptr, &queryVersionsDesc.header);
    if (versionsResult != FFX_API_RETURN_OK)
    {
        LOG_ERROR("Failed to query RR providers: {}",
                  FfxApiProxy::ReturnCodeToString(versionsResult));
        return false;
    }

    for (size_t i = 0; i < state.ffxDenoiserVersionIds.size(); ++i)
    {
        LOG_INFO("[RR_DIAG] provider[{}]: name='{}', id={:#x}", i,
                 state.ffxDenoiserVersionNames[i] ? state.ffxDenoiserVersionNames[i] : "<unnamed>",
                 state.ffxDenoiserVersionIds[i]);
    }

    return true;
}

void FSRDFeatureDx12::DestroyDenoiserContext() 
{
    if (_pDenoiserCtx != nullptr)
    {
        const uintptr_t contextAddress = reinterpret_cast<uintptr_t>(_pDenoiserCtx);
        const ffxReturnCode_t result = FfxApiProxy::D3D12_DestroyContext(&_pDenoiserCtx, nullptr);

        if (result == FFX_API_RETURN_OK)
        {
            LOG_INFO("[RR_DIAG] context destruction succeeded: context={:X}", contextAddress);
        }
        else
        {
            LOG_ERROR("[RR_DIAG] context destruction failed: context={:X}, result={}",
                      contextAddress, FfxApiProxy::ReturnCodeToString(result));
        }
    }

    _pDenoiserCtx = nullptr;
    _ambientOcclusionEnabled = false;
    _specularOcclusionEnabled = false;
    _ambientOcclusionNoisy.Reset();
    _ambientOcclusionDenoised.Reset();
    InvalidateDenoiserHistory();
}

bool FSRDFeatureDx12::UpdateSize()
{
    const uint32_t renderWidth = RenderWidth();
    const uint32_t renderHeight = RenderHeight();
    const uint32_t maxWidth = _denoiserCtxDesc.maxRenderSize.width;
    const uint32_t maxHeight = _denoiserCtxDesc.maxRenderSize.height;

    // maxRenderSize is an allocation ceiling; each dispatch supplies the current
    // logical size. Never release context resources while recording a frame because
    // earlier submitted command lists may still reference them.
    if (renderWidth > maxWidth || renderHeight > maxHeight)
    {
        LOG_ERROR(
            "[RR_DIAG] render size {}x{} exceeds the FSR-RR creation ceiling {}x{}; requesting feature recreation instead of releasing in-flight resources",
            renderWidth, renderHeight, maxWidth, maxHeight);
        InvalidateDenoiserHistory();
        State::Instance().changeBackend[Handle()->Id] = true;
        return false;
    }

    if (_lastDenoiserRenderWidth != 0 &&
        (_lastDenoiserRenderWidth != renderWidth ||
         _lastDenoiserRenderHeight != renderHeight))
    {
        LOG_INFO(
            "[RR_DIAG] logical render size changed within the allocation ceiling: {}x{} -> {}x{}; resetting temporal history without recreating resources",
            _lastDenoiserRenderWidth, _lastDenoiserRenderHeight,
            renderWidth, renderHeight);
        InvalidateDenoiserHistory();
    }

    _lastDenoiserRenderWidth = renderWidth;
    _lastDenoiserRenderHeight = renderHeight;

    return true;
}

bool FSRDFeatureDx12::Evaluate(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters) 
{
    LOG_FUNC();

    if (!IsInited())
        return false;

    // The application submitted a new evaluation even when a later validation,
    // composition, or upscaler step fails. Keep RR frame indices unique on every
    // exit path; in particular, never reuse an index after RR already advanced
    // its internal temporal history.
    EvaluationFrameGuard evaluationFrameGuard(_frameCount);

    auto& state = State::Instance();
    auto& cfg = *Config::Instance();
    const auto& inParams = *InParameters;

    // Refresh the current render subrect before deciding whether RR must resize.
    // PrepareUpscalerInput also queries it, but that happens after conversion and
    // is skipped entirely by several debug/bypass paths.
    unsigned int currentRenderWidth = RenderWidth();
    unsigned int currentRenderHeight = RenderHeight();
    GetRenderResolution(InParameters, &currentRenderWidth, &currentRenderHeight);
    if (currentRenderWidth == 0 || currentRenderHeight == 0)
    {
        LOG_ERROR("[RR_INPUT] current render resolution is zero");
        InvalidateDenoiserHistory();
        return false;
    }

    if (!UpdateSize())
        return false;

    StreamlineHooks::probeRRNGXPointerParameters(inParams);

    // Conversion leaves the RR signal outputs in UAV state. Always close that
    // state lifetime, including bypass and error paths where composition is skipped.
    DenoiserOutputStateGuard denoiserOutputStateGuard(FSRDConvShader, InCommandList);

    const auto dbgMode = static_cast<DebugModes>(cfg.FfxDenoiserDebugMode.value_or_default());
    const bool isDebugVis = (uint32_t)dbgMode & (uint32_t) DebugModes::ConversionDebug;
    const bool isDebugComp = ((uint64_t)dbgMode & (uint64_t)DebugModes::CompositionDebug);
    const bool isFfxDebug = dbgMode == DebugModes::FfxDebug;
    const bool isAmbientOcclusionDebug =
        dbgMode == DebugModes::AmbientOcclusionInput ||
        dbgMode == DebugModes::AmbientOcclusionOutput;
    const bool hasAnyDebug = (dbgMode != DebugModes::None);
    _convDesc.FrameIndex = static_cast<uint64_t>(_frameCount);

    // Denoise is bypassed if we are debugging something OTHER than the final outputs
    const bool isDenoiseBypassed = !isFfxDebug && !isDebugComp && 
        hasAnyDebug && !isAmbientOcclusionDebug &&
        dbgMode != DebugModes::DenoiserOutput && dbgMode != DebugModes::UpscalerBypass;

    // Upscale is bypassed if we are in a debug mode that isn't the DenoiserBypass (final raw)
    const bool isUpscaleBypassed = hasAnyDebug && dbgMode != DebugModes::DenoiserBypass;

    // Validate helper features
    if (!RCAS->IsInit())
        cfg.RcasEnabled.set_volatile_value(false);
    if (!OutputScaler->IsInit())
        cfg.OutputScalingEnabled.set_volatile_value(false);

    _isInReset = false;

    if (uint32_t value = 0; inParams.Get(NVSDK_NGX_Parameter_Reset, &value) == NVSDK_NGX_Result_Success)
        _isInReset = value > 0;

    // Denoiser start
    ffxDispatchDescDenoiserAmbientOcclusion ambientOcclusion = {};
    ffxDispatchDescDenoiserDirectDiffuse directDiffuse = {};
    ffxDispatchDescDenoiserIndirectSpecular indirectSpecular = {};
    ffxDispatchDescDenoiser denoiserDesc = {};
    bool isDenoiserReady = false;

    // Pull configuration and input buffers for DLSS-RR from the param table, convert and 
    // repack input buffers into intermediate FSR-RR input buffers, and configure descriptors.
    if (!PrepareDenoiserInput(InCommandList, *InParameters, denoiserDesc, ambientOcclusion,
                              directDiffuse, indirectSpecular))
    {
        InvalidateDenoiserHistory();
        return false;
    }

    // Dispatch denoiser
    if (!isDenoiseBypassed)
    {
        ffxDispatchDescDenoiserDebugView dispatchDebugView = {};

        if (isFfxDebug)
        {
            if (!(_denoiserCtxDesc.flags & FFX_DENOISER_ENABLE_DEBUGGING))
            {
                LOG_ERROR("RR debug view requested, but this denoiser context was not created with debugging enabled");
                InvalidateDenoiserHistory();
                return false;
            }

            ID3D12Resource* debugOutput = FSRDConvShader->PrepareDebugViewOutput(
                InCommandList, TargetWidth(), TargetHeight());
            if (!debugOutput)
            {
                InvalidateDenoiserHistory();
                return false;
            }

            const D3D12_RESOURCE_DESC debugOutputDesc = debugOutput->GetDesc();
            const bool isCompatibleDebugOutput =
                debugOutputDesc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
                debugOutputDesc.Width == TargetWidth() &&
                debugOutputDesc.Height == TargetHeight() &&
                debugOutputDesc.DepthOrArraySize == 1 &&
                debugOutputDesc.MipLevels == 1 &&
                debugOutputDesc.Format == DXGI_FORMAT_R16G16B16A16_FLOAT &&
                debugOutputDesc.SampleDesc.Count == 1 &&
                (debugOutputDesc.Flags & D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS) != 0;
            if (!isCompatibleDebugOutput)
            {
                LOG_ERROR(
                    "[RR_DIAG] dedicated AMD debug-view target is incompatible: size={}x{}, "
                    "format={}, dimension={}, arraySize={}, mips={}, samples={}, flags={:#x}",
                    debugOutputDesc.Width, debugOutputDesc.Height,
                    static_cast<uint32_t>(debugOutputDesc.Format),
                    static_cast<uint32_t>(debugOutputDesc.Dimension),
                    debugOutputDesc.DepthOrArraySize, debugOutputDesc.MipLevels,
                    debugOutputDesc.SampleDesc.Count, static_cast<uint32_t>(debugOutputDesc.Flags));
                InvalidateDenoiserHistory();
                return false;
            }

            const int debugViewport =
                std::clamp(cfg.FfxDenoiserDebugViewport.value_or_default(), -1,
                           FFX_API_DENOISER_DEBUG_VIEW_MAX_VIEWPORTS - 1);
            dispatchDebugView = 
            { 
                .header = { .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW },
                .output = ffxApiGetResourceDX12(debugOutput, FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
                .outputSize = { static_cast<uint32_t>(debugOutputDesc.Width), debugOutputDesc.Height },
                .mode = static_cast<uint32_t>(debugViewport < 0
                    ? FFX_API_DENOISER_DEBUG_VIEW_MODE_OVERVIEW
                    : FFX_API_DENOISER_DEBUG_VIEW_MODE_FULLSCREEN_VIEWPORT),
                .viewportIndex = static_cast<uint32_t>(std::max(debugViewport, 0))
            };

            // Debug view is optional and must be the tail of the typed-signal chain.
            ffxDispatchDescHeader* chainTail = denoiserDesc.header.pNext;
            while (chainTail && chainTail->pNext)
                chainTail = chainTail->pNext;

            if (!chainTail)
            {
                LOG_ERROR("RR 1.2 debug view could not find the typed-signal chain tail");
                InvalidateDenoiserHistory();
                return false;
            }

            chainTail->pNext = &dispatchDebugView.header;
        }

        isDenoiserReady = DispatchDenoiser(InCommandList, denoiserDesc);

        if (isFfxDebug)
            FSRDConvShader->TransitionDebugViewOutputToRead(InCommandList);

        if (!isDenoiserReady)
        {
            InvalidateDenoiserHistory();
            return false;
        }

        if (!PublishAmbientOcclusionOutput(InCommandList))
        {
            InvalidateDenoiserHistory();
            return false;
        }

        CommitDenoiserHistory();

        // Compose denoised signals
        uint32_t compositionFlags = (uint32_t)GetCompDebugFlags(dbgMode);
        if (_diffuseSignalDescType == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE)
            compositionFlags |= (uint32_t)FSRDCompFlags::DiffuseSignalIndirect;
        if (_specularSignalDescType == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR)
            compositionFlags |= (uint32_t) FSRDCompFlags::SpecularSignalIndirect;

        FSRDCompDesc compDesc =
        { 
            .DstTexSize = _convDesc.RenderSize,
            .CorrelationBias = std::clamp(cfg.FfxDenoiserCorrelationBias.value_or_default(), 0.0f, 1.0f),
            .Flags = compositionFlags,
            .ZeroRoughAnchorClamp =
                std::clamp(cfg.FfxDenoiserZeroRoughAnchorClamp.value_or_default(), 0.0f, 4.0f),
            .ZeroRoughCorrelationMix =
                std::clamp(cfg.FfxDenoiserZeroRoughCorrelationMix.value_or_default(), 0.0f, 1.0f)
        };

        const XMUINT2 rawColorBase = GetSubrectBase(
            inParams, NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_X,
            NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_Y);
        const XMUINT2 colorBeforeParticlesBase = GetSubrectBase(
            inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles_Subrect_Base_X,
            NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles_Subrect_Base_Y);
        compDesc.SourceBase = {
            rawColorBase.x, rawColorBase.y,
            colorBeforeParticlesBase.x, colorBeforeParticlesBase.y
        };

        if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Color, compDesc.InRawColor) ||
            !ValidateSourceExtent("CompositionColor", compDesc.InRawColor, rawColorBase,
                                  RenderWidth(), RenderHeight()))
        {
            InvalidateDenoiserHistory();
            return false;
        }
        TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles, compDesc.InColorBeforeParticles);
        if (compDesc.InColorBeforeParticles &&
            !ValidateSourceExtent("ColorBeforeParticles", compDesc.InColorBeforeParticles,
                                  colorBeforeParticlesBase, RenderWidth(), RenderHeight()))
        {
            InvalidateDenoiserHistory();
            return false;
        }

        if (!isFfxDebug)
        {
            if (!FSRDConvShader->DispatchComposition(InCommandList, compDesc))
                return false;
        }

        isDenoiserReady = true;
    }
    else
    {
        // A skipped RR frame breaks temporal continuity. The next real dispatch
        // must reset instead of reusing history across the gap.
        InvalidateDenoiserHistory();
    }

    // Upscaler start
    if (!isUpscaleBypassed)
    {
        ffxDispatchDescUpscale upscalerDesc = {};

        if (!PrepareUpscalerInput(InCommandList, inParams, upscalerDesc))
            return false;

        // Override upscaler config. The composition output is left in
        // NON_PIXEL | PIXEL shader-resource state, so declare both: the default
        // argument is COMPUTE_READ alone, which would leave the resource in a
        // narrower state than the preprocessor expects on the next frame.
        if (isDenoiserReady)
            upscalerDesc.color = ffxApiGetResourceDX12(
                FSRDConvShader->GetCompositionOutput(),
                FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ);

        // Sets optional, configurable resource barriers
        FSR31FeatureDx12::SetConfigurableBarriers(InCommandList);

        bool isUpscalerReady = DispatchUpscaler(InCommandList, upscalerDesc);

        // Post-Process
        if (isUpscalerReady)
            PostProcess(InCommandList, inParams, upscalerDesc);

        // Cleanup
        FSR31FeatureDx12::ResetConfigurableBarriers(InCommandList);
    }
    else // Debug visualization
    {
        ID3D12Resource* srcTex = nullptr;
        XMUINT2 debugSourceBase {};
        XMFLOAT2 debugSourceLogicalSize {
            static_cast<float>(RenderWidth()), static_cast<float>(RenderHeight())
        };

        if (isFfxDebug)
        {
            srcTex = FSRDConvShader->GetDebugViewOutput();
            debugSourceLogicalSize = {
                static_cast<float>(TargetWidth()), static_cast<float>(TargetHeight())
            };
        }
        else if (dbgMode == DebugModes::DlssColorBeforeParticles)
        {
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles, srcTex);
            debugSourceBase = GetSubrectBase(
                inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles_Subrect_Base_X,
                NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles_Subrect_Base_Y);
        }
        else if (dbgMode == DebugModes::DlssColorBeforeTransparency)
        {
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeTransparency, srcTex);
            debugSourceBase = GetSubrectBase(
                inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeTransparency_Subrect_Base_X,
                NVSDK_NGX_Parameter_DLSSD_ColorBeforeTransparency_Subrect_Base_Y);
        }
        else if (dbgMode == DebugModes::DlssTransparencyLayer)
        {
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSS_TransparencyLayer, srcTex);
            debugSourceBase = GetSubrectBase(
                inParams, NVSDK_NGX_Parameter_DLSS_TransparencyLayer_Subrect_Base_X,
                NVSDK_NGX_Parameter_DLSS_TransparencyLayer_Subrect_Base_Y);
        }
        else if (dbgMode == DebugModes::DlssBias)
        {
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask, srcTex);
            debugSourceBase = GetSubrectBase(
                inParams, NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_SubrectBase_X,
                NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_SubrectBase_Y);
        }
        else if (dbgMode == DebugModes::RawColor)
        {
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_Color, srcTex);
            debugSourceBase = GetSubrectBase(
                inParams, NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_X,
                NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_Y);
        }
        else if (dbgMode == DebugModes::AmbientOcclusionInput)
            srcTex = _ambientOcclusionEnabled ? _ambientOcclusionNoisy.Get() : nullptr;
        else if (dbgMode == DebugModes::AmbientOcclusionOutput)
            srcTex = _ambientOcclusionEnabled ? FSRDConvShader->GetAmbientOcclusionOutput() : nullptr;
        else if (isDebugVis)
            srcTex = GetD3D12ResFromFFX(indirectSpecular.signal.input);
        else
            srcTex = FSRDConvShader->GetCompositionOutput();

        ID3D12Resource* dstTex;

        if (!srcTex || !TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Output, dstTex))
            return true;

        FSRDConvShader->Blit(
            InCommandList, srcTex, dstTex, {}, debugSourceLogicalSize,
            { static_cast<float>(debugSourceBase.x),
              static_cast<float>(debugSourceBase.y) });
    }

    return isDenoiserReady || isDenoiseBypassed;
}

bool FSRDFeatureDx12::PrepareDenoiserInput(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& inParams,
    ffxDispatchDescDenoiser& dispatchDesc, ffxDispatchDescDenoiserAmbientOcclusion& ambientOcclusion,
    ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
    ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular)
{
    const auto& cfg = *Config::Instance(); 

    if (_ambientOcclusionEnabled && !AcquireTaggedAmbientOcclusionResources(true))
    {
        LOG_ERROR("[RR_AO] context requires AO, but a valid tagged pair was unavailable for this frame");
        return false;
    }

    // Gather DLSS-RR input buffers for conversion and repacking for FSR-RR
    if (!PrepareDenoiseConvInput(inParams))
        return false;   

    if (!ConvertDenoiserBuffers(InCommandList))
        return false;

    // Camera matrix - translation and rotation, from viewMatrix^-1
    const XMFLOAT3 camPos = GetFloat3Column(_invViewMatrix, 3);
    const bool resetHistory = _isInReset || !_hasDenoiserHistory;
    const XMFLOAT3 camDelta = resetHistory
        ? XMFLOAT3 {}
        : XMFLOAT3 { _lastCamPos.x - camPos.x, _lastCamPos.y - camPos.y, _lastCamPos.z - camPos.z };

    // Pack dispatch configuration
    dispatchDesc = 
    {
        .commandList = InCommandList,
        .motionVectorScale = { 1.0f, 1.0f, 1.0f },
        // Camera movement since last frame (PreviousPosition - CurrentPosition)
        .cameraPositionDelta = { camDelta.x, camDelta.y, camDelta.z },
        .view = GetRRMatrix(_viewMatrix),
        .projection = GetRRMatrix(_projMatrix),
        .linearDepthBounds = { _convDesc.NearPlane, _convDesc.FarPlane },
        .renderSize = { RenderWidth(), RenderHeight() }, 
        .frameIndex = (uint32_t)_frameCount,
        .flags = FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO
    };

    // Populate resources and link signal header
    FSRDConvShader->GetSignals(dispatchDesc, directDiffuse, indirectSpecular);
    directDiffuse.header.type = _diffuseSignalDescType;
    indirectSpecular.header.type = _specularSignalDescType;

    const ffxDispatchDescDenoiserAmbientOcclusion* activeAmbientOcclusion = nullptr;
    if (_ambientOcclusionEnabled)
    {
        // Acquisition only guarantees NON_PIXEL_SHADER_RESOURCE. Declaring the wider
        // PIXEL_COMPUTE_READ when the title tagged a narrower state makes the FFX
        // backend record a transition whose "before" state the resource is not in.
        // Report the state that was actually validated.
        const uint32_t ambientOcclusionInputState =
            (_ambientOcclusionNoisyState & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE) != 0
                ? FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ
                : FFX_API_RESOURCE_STATE_COMPUTE_READ;

        ambientOcclusion =
        {
            .header = { .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_AMBIENT_OCCLUSION },
            .signal =
            {
                .input = ffxApiGetResourceDX12(
                    _ambientOcclusionNoisy.Get(), ambientOcclusionInputState),
                .output = ffxApiGetResourceDX12(
                    FSRDConvShader->GetAmbientOcclusionOutput(),
                    FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
                .checkerboardOrigin = 0
            }
        };
        activeAmbientOcclusion = &ambientOcclusion;
    }

    // RR 1.2 descriptors are ordered by their ABI type, matching AMD's sample chain.
    // Keeping this generic prevents future AO/SO additions from hard-coding pairwise links.
    std::array<ffxDispatchDescHeader*, 3> signals {
        &directDiffuse.header, &indirectSpecular.header, nullptr
    };
    size_t signalCount = 2;
    if (activeAmbientOcclusion)
        signals[signalCount++] = &ambientOcclusion.header;

    std::sort(signals.begin(), signals.begin() + signalCount,
              [](const ffxDispatchDescHeader* left, const ffxDispatchDescHeader* right) {
                  return left->type < right->type;
              });

    dispatchDesc.header.pNext = signals[0];
    for (size_t i = 0; i < signalCount; ++i)
        signals[i]->pNext = i + 1 < signalCount ? signals[i + 1] : nullptr;

    if (!ValidateRequiredRRResources(
            dispatchDesc, directDiffuse, indirectSpecular, activeAmbientOcclusion))
        return false;
    
    if (resetHistory)
        dispatchDesc.flags |= FFX_DENOISER_DISPATCH_RESET;

    // Conversion has already normalized source motion into unjittered UV space.
    // RR therefore consumes XY with a unit scale; Z remains signed-linear depth.
    dispatchDesc.motionVectorScale = { 1.0f, 1.0f, 1.0f };
    dispatchDesc.jitterOffsets.x = _convDesc.JitterOffsets.x;
    dispatchDesc.jitterOffsets.y = _convDesc.JitterOffsets.y;

    LOG_DEBUG("Jitter pixels [{:.6f}, {:.6f}]", dispatchDesc.jitterOffsets.x, dispatchDesc.jitterOffsets.y);

    return true;
}

bool FSRDFeatureDx12::PrepareDenoiseConvInput(const NVSDK_NGX_Parameter& inParams)
{
    const auto& cfg = *Config::Instance();
    const SLConstantsSnapshot slConstantsSnapshot =
        StreamlineHooks::getSLConstantsSnapshot();
    const auto& slData = slConstantsSnapshot.constants;

    // Gather DLSS-RR input buffers for conversion and repacking for FSR-RR
    bool isReady = true;
    _convDesc.Resources = {};
    _convDesc.SpecularHitDistanceBase = {};
    _convDesc.SpecularHitDistanceFromCombinedAlpha = false;
    _specularHitDistanceTaggedResource.Reset();
    _specularRayDirectionHitDistanceTaggedResource.Reset();
    const RRD3D12SignalTagSnapshot rrTagSnapshot =
        StreamlineHooks::getRRD3D12SignalTagSnapshot();
    const bool hasCurrentSLConstants =
        rrTagSnapshot.activeEvaluationFrame != UINT32_MAX &&
        rrTagSnapshot.activeEvaluationViewport != UINT32_MAX &&
        slConstantsSnapshot.frameIndex == rrTagSnapshot.activeEvaluationFrame &&
        slConstantsSnapshot.viewport == rrTagSnapshot.activeEvaluationViewport;
    RRTaggedResourceDiagnostic emissiveTagDiagnostic {};

    // Standard TSR buffers
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Color, _convDesc.Resources.InColor))
        isReady = false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_MotionVectors, _convDesc.Resources.InMotionVectors))
        isReady = false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Depth, _convDesc.Resources.InDepth))
        isReady = false;

    // DLSSD-specific buffers
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_GBuffer_Normals, _convDesc.Resources.InNormals))
        isReady = false;

    // Roughness mode is instance state. When creation metadata is absent, lock it
    // once from the first usable frame; never flip modes because one resource is
    // temporarily missing, as that changes shader bindings and invalidates history.
    const bool hasSeparateRoughness = TryGetNGXVoidPointer(
        inParams, NVSDK_NGX_Parameter_GBuffer_Roughness,
        _convDesc.Resources.InRoughness);
    if (_roughnessSource == RoughnessSource::Unknown)
    {
        if (hasSeparateRoughness)
        {
            _roughnessSource = RoughnessSource::Separate;
            LOG_INFO("DLSSD roughness metadata absent; locked this instance to the separate resource");
        }
        else if (SupportsPackedRoughness(_convDesc.Resources.InNormals))
        {
            _roughnessSource = RoughnessSource::Packed;
            LOG_INFO("DLSSD roughness metadata absent; locked this instance to normals alpha");
        }
        else
        {
            LOG_ERROR(
                "DLSSD roughness metadata and separate texture are absent, and normals format has no alpha channel");
            isReady = false;
        }
    }
    else if (_roughnessSource == RoughnessSource::Separate && !hasSeparateRoughness)
    {
        LOG_ERROR("DLSSD instance requires separate roughness, but the resource is missing this frame");
        InvalidateDenoiserHistory();
        isReady = false;
    }

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_DiffuseAlbedo, _convDesc.Resources.InDiffAlbedo))
        isReady = false;

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_SpecularAlbedo, _convDesc.Resources.InSpecAlbedo))
        isReady = false;

    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask, _convDesc.Resources.InBiasMask);

    // Optional diagnostic-only emissive input. Do not use it for RR signal
    // separation until its contents, exposure and composition semantics are verified.
    _emissiveProbe = nullptr;
    _emissiveTaggedResource.Reset();
    _emissiveProbeCompatible = false;
    _emissiveProbeFromStreamline = false;
    _convDesc.Resources.InEmissive = nullptr;
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_GBuffer_Emissive, _emissiveProbe);
    if (!_emissiveProbe)
    {
        _emissiveProbeFromStreamline = AcquireSLTaggedResource(
            rrTagSnapshot, RRTaggedSignal::Emissive, "Streamline.Emissive",
            true, _emissiveTaggedResource, emissiveTagDiagnostic);
        if (_emissiveProbeFromStreamline)
            _emissiveProbe = _emissiveTaggedResource.Get();
    }
    _emissiveProbeCompatible = IsEmissiveProbeCompatible(_emissiveProbe);
    if (_emissiveProbeCompatible)
        _convDesc.Resources.InEmissive = _emissiveProbe;

    // Optional legacy NGX GBuffer identifiers. NRD can use a material identifier
    // to reject history across material boundaries, but DLSS-RR does not require
    // either resource. Probe only; do not consume an unverified title-specific
    // encoding as temporal-history metadata.
    _materialIdProbe = nullptr;
    _shadingModelIdProbe = nullptr;
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_GBuffer_MaterialId,
                         _materialIdProbe);
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_GBuffer_ShadingModelId,
                         _shadingModelIdProbe);

    // Optional specular hit-distance inputs. Selection is deferred until all source
    // origins and extents are known, so an invalid high-priority candidate can never
    // reach an SRV binding.
    ID3D12Resource* ngxSpecularHitDistance = nullptr;
    ID3D12Resource* ngxSpecularRayDirectionHitDistance = nullptr;
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance,
                         ngxSpecularHitDistance);
    TryGetNGXVoidPointer(inParams,
                         NVSDK_NGX_Parameter_DLSSD_SpecularRayDirectionHitDistance,
                         ngxSpecularRayDirectionHitDistance);

    const XMUINT2 colorBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSS_Input_Color_Subrect_Base_Y);
    const XMUINT2 depthBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSS_Input_Depth_Subrect_Base_Y);
    const XMUINT2 declaredMotionBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_X,
        NVSDK_NGX_Parameter_DLSS_Input_MV_SubrectBase_Y);
    XMUINT2 motionBase = declaredMotionBase;
    const XMUINT2 normalBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_Normals_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSS_Input_Normals_Subrect_Base_Y);
    const XMUINT2 roughnessBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_Roughness_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSS_Input_Roughness_Subrect_Base_Y);
    const XMUINT2 diffuseAlbedoBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_DiffuseAlbedo_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSS_Input_DiffuseAlbedo_Subrect_Base_Y);
    const XMUINT2 specularAlbedoBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_SpecularAlbedo_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSS_Input_SpecularAlbedo_Subrect_Base_Y);
    const XMUINT2 ngxSpecularHitDistanceBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance_Subrect_Base_Y);
    const XMUINT2 ngxSpecularRayDirectionHitDistanceBase = GetSubrectBase(
        inParams,
        NVSDK_NGX_Parameter_DLSSD_SpecularRayDirectionHitDistance_Subrect_Base_X,
        NVSDK_NGX_Parameter_DLSSD_SpecularRayDirectionHitDistance_Subrect_Base_Y);
    const XMUINT2 biasBase = GetSubrectBase(
        inParams, NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_SubrectBase_X,
        NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_SubrectBase_Y);

    XMUINT2 emissiveBase = colorBase;
    if (_emissiveProbeFromStreamline)
    {
        if (emissiveTagDiagnostic.present && emissiveTagDiagnostic.usesExtent)
            emissiveBase = {
                emissiveTagDiagnostic.extentLeft, emissiveTagDiagnostic.extentTop
            };
    }
    if (_convDesc.Resources.InEmissive &&
        !ValidateSourceExtent(
            "Emissive", _convDesc.Resources.InEmissive, emissiveBase,
            RenderWidth(), RenderHeight()))
    {
        _convDesc.Resources.InEmissive = nullptr;
        _emissiveProbeCompatible = false;
    }

    _convDesc.FloorSourceBase = { colorBase.x, colorBase.y, depthBase.x, depthBase.y };
    _convDesc.InputBase1 = { normalBase.x, normalBase.y, roughnessBase.x, roughnessBase.y };
    _convDesc.InputBase2 = { ngxSpecularHitDistanceBase.x, ngxSpecularHitDistanceBase.y,
                             diffuseAlbedoBase.x, diffuseAlbedoBase.y };
    _convDesc.InputBase3 = { specularAlbedoBase.x, specularAlbedoBase.y,
                             biasBase.x, biasBase.y };
    _convDesc.InputBase4 = { emissiveBase.x, emissiveBase.y, 0u, 0u };

    const uint32_t renderWidth = RenderWidth();
    const uint32_t renderHeight = RenderHeight();
    uint32_t motionWidth = LowResMV() ? RenderWidth() : DisplayWidth();
    uint32_t motionHeight = LowResMV() ? RenderHeight() : DisplayHeight();
    bool displayResolutionMotion = !LowResMV();

    // Streamline may replace a title's display-resolution MV with its own
    // camera-completed render-resolution texture before forwarding the NGX call.
    // Feature-creation metadata still describes the original resource, so the
    // actual D3D12 extent must win when the two contracts no longer fit.
    if (_convDesc.Resources.InMotionVectors)
    {
        const D3D12_RESOURCE_DESC motionDesc =
            _convDesc.Resources.InMotionVectors->GetDesc();
        const bool declaredExtentFits =
            uint64_t(motionBase.x) + motionWidth <= motionDesc.Width &&
            uint64_t(motionBase.y) + motionHeight <= motionDesc.Height;
        const bool zeroBasedLogicalExtentFits =
            uint64_t(motionWidth) <= motionDesc.Width &&
            uint64_t(motionHeight) <= motionDesc.Height;
        const bool zeroBasedRenderExtentFits =
            uint64_t(RenderWidth()) <= motionDesc.Width &&
            uint64_t(RenderHeight()) <= motionDesc.Height;
        if (!declaredExtentFits && zeroBasedLogicalExtentFits)
        {
            LOG_WARN(
                "[RR_INPUT] NGX motion resource is {}x{} and cannot contain the declared "
                "subrect {}x{}+({},{}); retaining its logical resolution with a "
                "zero-based origin",
                motionDesc.Width, motionDesc.Height, motionWidth, motionHeight,
                motionBase.x, motionBase.y);
            motionBase = { 0u, 0u };
        }
        else if (!declaredExtentFits && displayResolutionMotion &&
                 zeroBasedRenderExtentFits)
        {
            LOG_WARN(
                "[RR_INPUT] NGX motion resource is {}x{} and cannot contain the declared "
                "display-resolution subrect {}x{}+({},{}); treating it as Streamline's "
                "zero-based render-resolution camera-completed motion",
                motionDesc.Width, motionDesc.Height, motionWidth, motionHeight,
                motionBase.x, motionBase.y);
            motionWidth = RenderWidth();
            motionHeight = RenderHeight();
            motionBase = { 0u, 0u };
            displayResolutionMotion = false;
        }
    }

    _convDesc.InputBase0 = { colorBase.x, colorBase.y, motionBase.x, motionBase.y };
    if (motionWidth == 0 || motionHeight == 0)
    {
        LOG_ERROR("[RR_INPUT] motion-vector extent is zero");
        isReady = false;
    }
    else
    {
        float motionScaleX = 1.0f;
        float motionScaleY = 1.0f;
        const bool validMotionScaleX =
            inParams.Get(NVSDK_NGX_Parameter_MV_Scale_X, &motionScaleX) == NVSDK_NGX_Result_Success &&
            std::isfinite(motionScaleX) && motionScaleX != 0.0f;
        const bool validMotionScaleY =
            inParams.Get(NVSDK_NGX_Parameter_MV_Scale_Y, &motionScaleY) == NVSDK_NGX_Result_Success &&
            std::isfinite(motionScaleY) && motionScaleY != 0.0f;
        if (!validMotionScaleX)
            motionScaleX = 1.0f;
        if (!validMotionScaleY)
            motionScaleY = 1.0f;
        if (!validMotionScaleX || !validMotionScaleY)
        {
            // NGX helper APIs normalize a missing, non-finite, or zero component
            // to one. Preserve a valid negative component because it can encode
            // the title's axis convention.
            LOG_WARN(
                "[RR_INPUT] MV scale component missing/invalid/zero (x={}, y={}); "
                "using NGX's unit fallback per component",
                validMotionScaleX, validMotionScaleY);
        }

        _convDesc.MotionInputSize = {
            static_cast<float>(motionWidth), static_cast<float>(motionHeight),
            1.0f / static_cast<float>(motionWidth), 1.0f / static_cast<float>(motionHeight)
        };
        _convDesc.MotionTransform = {
            // NGX MV scale converts the stored value to render-pixel motion.
            // The texture extent only controls where that value is fetched; UV
            // normalization always uses the render extent, including high-res MV.
            motionScaleX / static_cast<float>(RenderWidth()),
            motionScaleY / static_cast<float>(RenderHeight()), 0.0f, 0.0f
        };
    }

    struct SpecularHitDistanceSelection
    {
        ID3D12Resource* Resource = nullptr;
        XMUINT2 Base {};
        bool CombinedAlpha = false;
        const char* SourceName = nullptr;
    } specularHitDistanceSelection;

    auto tryNGXSpecularHitDistance = [&](const char* sourceName,
                                         ID3D12Resource* resource,
                                         const XMUINT2& base,
                                         bool combinedAlpha) -> bool {
        if (!resource)
            return false;

        const SourceFormatValidator formatValidator = combinedAlpha
            ? IsDiffuseRayDirectionHitDistanceFormat
            : IsDiffuseHitDistanceFormat;
        const char* expectedFormat = combinedAlpha
            ? "RGBA16F or RGBA32F (hit distance in alpha)"
            : "R16F or R32F";
        if (!ValidateReprojectionGuideSource(
                sourceName, resource, base, renderWidth, renderHeight,
                formatValidator, expectedFormat))
        {
            return false;
        }

        specularHitDistanceSelection = {
            resource, base, combinedAlpha, sourceName
        };
        return true;
    };

    auto trySLSpecularHitDistance = [&](RRTaggedSignal signal,
                                        const char* sourceName,
                                        bool combinedAlpha) -> bool {
        Microsoft::WRL::ComPtr<ID3D12Resource> taggedResource;
        RRTaggedResourceDiagnostic diagnostic {};
        if (!AcquireSLTaggedResource(
                rrTagSnapshot, signal, sourceName, true,
                taggedResource, diagnostic))
            return false;

        const XMUINT2 base = diagnostic.usesExtent
            ? XMUINT2 { diagnostic.extentLeft, diagnostic.extentTop }
            : XMUINT2 {};
        if (diagnostic.effectiveWidth != renderWidth ||
            diagnostic.effectiveHeight != renderHeight)
        {
            LOG_ERROR(
                "[RR_INPUT] {} tag extent {}x{} does not exactly match the one-to-one render extent {}x{}",
                sourceName, diagnostic.effectiveWidth, diagnostic.effectiveHeight,
                renderWidth, renderHeight);
            return false;
        }

        const SourceFormatValidator formatValidator = combinedAlpha
            ? IsDiffuseRayDirectionHitDistanceFormat
            : IsDiffuseHitDistanceFormat;
        const char* expectedFormat = combinedAlpha
            ? "RGBA16F or RGBA32F (hit distance in alpha)"
            : "R16F or R32F";
        if (!ValidateReprojectionGuideSource(
                sourceName, taggedResource.Get(), base,
                diagnostic.effectiveWidth, diagnostic.effectiveHeight,
                formatValidator, expectedFormat))
        {
            return false;
        }

        specularHitDistanceSelection = {
            taggedResource.Get(), base, combinedAlpha, sourceName
        };
        if (combinedAlpha)
            _specularRayDirectionHitDistanceTaggedResource =
                std::move(taggedResource);
        else
            _specularHitDistanceTaggedResource = std::move(taggedResource);
        return true;
    };

    if (!tryNGXSpecularHitDistance(
            NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance,
            ngxSpecularHitDistance, ngxSpecularHitDistanceBase, false) &&
        !tryNGXSpecularHitDistance(
            NVSDK_NGX_Parameter_DLSSD_SpecularRayDirectionHitDistance,
            ngxSpecularRayDirectionHitDistance,
            ngxSpecularRayDirectionHitDistanceBase, true) &&
        !trySLSpecularHitDistance(
            RRTaggedSignal::SpecularHitDistance,
            "Streamline.SpecularHitDistance", false))
    {
        trySLSpecularHitDistance(
            RRTaggedSignal::SpecularRayDirectionHitDistance,
            "Streamline.SpecularRayDirectionHitDistance", true);
    }

    if (specularHitDistanceSelection.Resource)
    {
        _convDesc.SpecularHitDistanceBase = specularHitDistanceSelection.Base;
        _convDesc.SpecularHitDistanceFromCombinedAlpha =
            specularHitDistanceSelection.CombinedAlpha;
        if (specularHitDistanceSelection.CombinedAlpha)
        {
            _convDesc.Resources.InSpecularRayDirectionHitDistance =
                specularHitDistanceSelection.Resource;
        }
        else
        {
            _convDesc.Resources.InSpecHitDist =
                specularHitDistanceSelection.Resource;
            // The legacy signal splitter consumes scalar hit distance directly.
            _convDesc.InputBase2.x = specularHitDistanceSelection.Base.x;
            _convDesc.InputBase2.y = specularHitDistanceSelection.Base.y;
        }

        LOG_DEBUG(
            "[RR_INPUT] selected {} for specular hit distance: base=({}, {}), combinedAlpha={}",
            specularHitDistanceSelection.SourceName,
            specularHitDistanceSelection.Base.x,
            specularHitDistanceSelection.Base.y,
            specularHitDistanceSelection.CombinedAlpha);
    }

    float jitterX = 0.0f;
    float jitterY = 0.0f;
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_X, &jitterX);
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_Y, &jitterY);
    if (!std::isfinite(jitterX))
        jitterX = 0.0f;
    if (!std::isfinite(jitterY))
        jitterY = 0.0f;

    const XMFLOAT2 currentJitter { jitterX, jitterY };
    const XMFLOAT2 previousJitter = (_isInReset || !_hasDenoiserHistory)
        ? currentJitter
        : _previousDenoiserJitter;
    _convDesc.JitterOffsets = {
        currentJitter.x, currentJitter.y, previousJitter.x, previousJitter.y
    };
    _convDesc.MotionHistoryValid = _hasDenoiserHistory && !_isInReset;
    _convDesc.DisplayResolutionMotion = displayResolutionMotion;
    _convDesc.MotionVectorsJittered = JitteredMV();

    isReady &= ValidateSourceExtent("Color", _convDesc.Resources.InColor,
                                    colorBase, renderWidth, renderHeight);
    isReady &= ValidateSourceExtent("Depth", _convDesc.Resources.InDepth,
                                    depthBase, renderWidth, renderHeight);
    isReady &= ValidateSourceExtent("MotionVectors", _convDesc.Resources.InMotionVectors,
                                    motionBase, motionWidth, motionHeight);
    isReady &= ValidateSourceExtent("Normals", _convDesc.Resources.InNormals,
                                    normalBase, renderWidth, renderHeight);
    if (_roughnessSource == RoughnessSource::Separate)
        isReady &= ValidateSourceExtent("Roughness", _convDesc.Resources.InRoughness,
                                        roughnessBase, renderWidth, renderHeight);
    isReady &= ValidateSourceExtent("DiffuseAlbedo", _convDesc.Resources.InDiffAlbedo,
                                    diffuseAlbedoBase, renderWidth, renderHeight);
    isReady &= ValidateSourceExtent("SpecularAlbedo", _convDesc.Resources.InSpecAlbedo,
                                    specularAlbedoBase, renderWidth, renderHeight);
    if (_convDesc.Resources.InBiasMask)
        isReady &= ValidateSourceExtent("BiasCurrentColor", _convDesc.Resources.InBiasMask,
                                        biasBase, renderWidth, renderHeight);

    // Diagnostic-only probes for the two DLSS-RR diffuse hit-distance representations.
    // Do not bind or consume them until a title is confirmed to provide a compatible resource.
    _diffuseHitDistanceProbe = nullptr;
    _diffuseRayDirectionHitDistanceProbe = nullptr;
    _diffuseHitDistanceBaseX = 0;
    _diffuseHitDistanceBaseY = 0;
    _diffuseRayDirectionHitDistanceBaseX = 0;
    _diffuseRayDirectionHitDistanceBaseY = 0;
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_DiffuseHitDistance,
                         _diffuseHitDistanceProbe);
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_DiffuseRayDirectionHitDistance,
                         _diffuseRayDirectionHitDistanceProbe);
    inParams.Get(NVSDK_NGX_Parameter_DLSSD_DiffuseHitDistance_Subrect_Base_X,
                 &_diffuseHitDistanceBaseX);
    inParams.Get(NVSDK_NGX_Parameter_DLSSD_DiffuseHitDistance_Subrect_Base_Y,
                 &_diffuseHitDistanceBaseY);
    inParams.Get(NVSDK_NGX_Parameter_DLSSD_DiffuseRayDirectionHitDistance_Subrect_Base_X,
                 &_diffuseRayDirectionHitDistanceBaseX);
    inParams.Get(NVSDK_NGX_Parameter_DLSSD_DiffuseRayDirectionHitDistance_Subrect_Base_Y,
                 &_diffuseRayDirectionHitDistanceBaseY);

    // Bind the diffuse ray length instead of only probing it. RR's non-PSR handling
    // of reflected geometry is driven by hit distance, and the diffuse signal has
    // been declaring every pixel a ray miss at infinity - the strongest possible
    // claim, and almost always false when the title actually supplies a length.
    _convDesc.Resources.InDiffuseHitDistance = nullptr;
    _convDesc.DiffuseHitDistanceBase = {};
    _convDesc.DiffuseHitDistanceMode = 0;

    if (cfg.FfxDenoiserDiffuseHitDistance.value_or_default())
    {
        const XMUINT2 scalarBase {
            _diffuseHitDistanceBaseX, _diffuseHitDistanceBaseY
        };
        const XMUINT2 combinedBase {
            _diffuseRayDirectionHitDistanceBaseX, _diffuseRayDirectionHitDistanceBaseY
        };

        if (_diffuseHitDistanceProbe &&
            ValidateReprojectionGuideSource(
                NVSDK_NGX_Parameter_DLSSD_DiffuseHitDistance, _diffuseHitDistanceProbe,
                scalarBase, renderWidth, renderHeight, IsDiffuseHitDistanceFormat,
                "R16F or R32F"))
        {
            _convDesc.Resources.InDiffuseHitDistance = _diffuseHitDistanceProbe;
            _convDesc.DiffuseHitDistanceBase = scalarBase;
            _convDesc.DiffuseHitDistanceMode = 1;
        }
        else if (_diffuseRayDirectionHitDistanceProbe &&
                 ValidateReprojectionGuideSource(
                     NVSDK_NGX_Parameter_DLSSD_DiffuseRayDirectionHitDistance,
                     _diffuseRayDirectionHitDistanceProbe, combinedBase,
                     renderWidth, renderHeight, IsDiffuseRayDirectionHitDistanceFormat,
                     "RGBA16F or RGBA32F (hit distance in alpha)"))
        {
            _convDesc.Resources.InDiffuseHitDistance =
                _diffuseRayDirectionHitDistanceProbe;
            _convDesc.DiffuseHitDistanceBase = combinedBase;
            _convDesc.DiffuseHitDistanceMode = 2;
        }
    }

    // InputBase4.zw was reserved; it now carries the diffuse hit-distance origin.
    _convDesc.InputBase4.z = _convDesc.DiffuseHitDistanceBase.x;
    _convDesc.InputBase4.w = _convDesc.DiffuseHitDistanceBase.y;

    // Get DLSSD matrices and derive related values
    // World to view/camera space (V)
    _viewMatrix = {};
    _viewFromStreamline = false;

    if (!TryGetNGXColumnVectorMatrix(inParams, NVSDK_NGX_Parameter_DLSS_WORLD_TO_VIEW_MATRIX, _viewMatrix))
    {
        if (StreamlineHooks::isSetConstantsHooked() && hasCurrentSLConstants)
        {
            SetColumn(XMLoadFloat3((XMFLOAT3*) &slData.cameraRight), 0, _invViewMatrix);
            SetColumn(XMLoadFloat3((XMFLOAT3*) &slData.cameraUp), 1, _invViewMatrix);
            SetColumn(XMLoadFloat3((XMFLOAT3*) &slData.cameraFwd), 2, _invViewMatrix);
            SetColumn(XMLoadFloat3((XMFLOAT3*) &slData.cameraPos), 3, _invViewMatrix);
            _invViewMatrix.r[3].m128_f32[3] = 1.0f;

            _viewMatrix = XMMatrixInverse(nullptr, _invViewMatrix);
            _viewFromStreamline = true;
        }
        else
        {
            LOG_ERROR("View matrix missing! Denoiser not ready.");
            isReady = false;
        }
    }
    else
    {
        // Camera rotation and position
        _invViewMatrix = XMMatrixInverse(nullptr, _viewMatrix);
    }

    if (_isInReset || !_hasDenoiserHistory)
        _prevViewMatrix = _viewMatrix;

    // Perspective projection matrix (P)
    _projMatrix = {};
    _projectionFromStreamline = false;

    if (!TryGetNGXColumnVectorMatrix(inParams, NVSDK_NGX_Parameter_DLSS_VIEW_TO_CLIP_MATRIX, _projMatrix))
    {
        if (StreamlineHooks::isSetConstantsHooked() && hasCurrentSLConstants)
        {
            if (slData.cameraFOV != sl::INVALID_FLOAT &&
                slData.cameraNear != sl::INVALID_FLOAT &&
                slData.cameraFar != sl::INVALID_FLOAT &&
                slData.cameraAspectRatio != sl::INVALID_FLOAT &&
                slData.cameraNear != slData.cameraFar)
            {
                // These measurements are supposed to be in radians, but some titles supply degrees.
                // Valid FOV in radians never exceeds PI. Realistic FOV in degrees is basically never in the single
                // digits.
                const float fov = (slData.cameraFOV < 4.0f) ? slData.cameraFOV : GetRadiansFromDeg(slData.cameraFOV);
                const float nearPlane = slData.cameraNear;
                const float farPlane = slData.cameraFar;
                _isRightHanded = slData.cameraViewToClip[2].w < 0.0f;

                // Actual SL view-to-clip matrices are unreliable in some titles, so reconstruct
                // an unjittered projection from the scalar camera data.
                _projMatrix = CreateColumnVectorPerspectiveProjection(
                    fov, slData.cameraAspectRatio, nearPlane, farPlane,
                    _isRightHanded, DepthInverted());
                _projectionFromStreamline = true;
            }
            else
            {
                LOG_ERROR("Streamline projection data is incomplete! Denoiser not ready.");
                isReady = false;
            }
        }
        else
        {
            LOG_ERROR("Projection matrix missing! Denoiser not ready.");
            isReady = false;
        }
    }

    // AMD RR 1.2 requires a valid ray length in alpha for every active indirect-
    // specular pixel. The INI's unset value is Auto: resolve it once from a
    // semantically named, format/extent-validated guide, then keep the context
    // classification stable even if an optional tag temporarily disappears.
    //
    // This runs last, and only for a frame that cleared every validation above. The
    // lock is permanent, so a frame that is about to be rejected must not set it -
    // the first Evaluate frequently arrives before the title has tagged its optional
    // guides, and locking there would pin the classification to Direct for good.
    if (isReady && !cfg.FfxDenoiserSpecularSignalType.has_value() &&
        !_autoSpecularSignalResolved)
    {
        const ffxStructType_t resolvedType = specularHitDistanceSelection.Resource
            ? FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR
            : FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR;

        LOG_INFO(
            "[RR_INPUT] automatic specular classification resolved to {} on the first validated frame ({})",
            GetSignalTypeName(resolvedType),
            specularHitDistanceSelection.Resource
                ? "validated hit-distance guide present"
                : "no validated hit-distance guide; keeping every specular pixel active");

        if (_specularSignalDescType == resolvedType)
        {
            _autoSpecularSignalDescType = resolvedType;
            _autoSpecularSignalResolved = true;
        }
        else if (_preprocessorHasRecordedWork)
        {
            // Recreating in place here would destroy converter textures that an
            // already-submitted command list can still reference. UpdateSize refuses
            // exactly this for exactly this reason; take the same escape hatch and let
            // the rebuilt instance resolve on its own first frame, where nothing has
            // been recorded yet. The resolution is deliberately not latched, so the
            // fresh instance repeats it rather than inheriting a stale decision.
            LOG_INFO(
                "[RR_INPUT] automatic specular classification needs {} -> {}; requesting a feature rebuild because this instance has already recorded GPU work",
                GetSignalTypeName(_specularSignalDescType),
                GetSignalTypeName(resolvedType));
            InvalidateDenoiserHistory();
            State::Instance().changeBackend[Handle()->Id] = true;
            return false;
        }
        else
        {
            LOG_INFO(
                "[RR_INPUT] recreating RR context for automatic specular classification: {} -> {}",
                GetSignalTypeName(_specularSignalDescType),
                GetSignalTypeName(resolvedType));
            _autoSpecularSignalDescType = resolvedType;
            _autoSpecularSignalResolved = true;
            DestroyDenoiserContext();
            if (!CreateDenoiserContext())
            {
                LOG_ERROR(
                    "[RR_INPUT] failed to recreate RR context for automatic specular classification; requesting a feature rebuild");
                State::Instance().changeBackend[Handle()->Id] = true;
                return false;
            }
        }
    }

    // Same contract for the diffuse signal, resolved from the guide that signal
    // actually consumes: indirect diffuse reads a ray length from its alpha, direct
    // diffuse leaves that channel undefined. A title that supplies no diffuse ray
    // length therefore has nothing for the indirect path to work from, and every
    // pixel is better served staying active on the direct one.
    //
    // Deliberately a separate block rather than folded into the specular one above:
    // that block can return early to request a rebuild, and the two classifications
    // must not become order-dependent on each other.
    if (isReady && !cfg.FfxDenoiserDiffuseSignalType.has_value() &&
        !_autoDiffuseSignalResolved)
    {
        const bool hasDiffuseRayLength = _convDesc.Resources.InDiffuseHitDistance != nullptr &&
            _convDesc.DiffuseHitDistanceMode != 0u;

        const ffxStructType_t resolvedType = hasDiffuseRayLength
            ? FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE
            : FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;

        LOG_INFO(
            "[RR_INPUT] automatic diffuse classification resolved to {} on the first validated frame ({})",
            GetSignalTypeName(resolvedType),
            hasDiffuseRayLength
                ? "validated diffuse ray length present"
                : "no diffuse ray length; keeping every diffuse pixel active");

        if (_diffuseSignalDescType == resolvedType)
        {
            _autoDiffuseSignalDescType = resolvedType;
            _autoDiffuseSignalResolved = true;
        }
        else if (_preprocessorHasRecordedWork)
        {
            LOG_INFO(
                "[RR_INPUT] automatic diffuse classification needs {} -> {}; requesting a feature rebuild because this instance has already recorded GPU work",
                GetSignalTypeName(_diffuseSignalDescType), GetSignalTypeName(resolvedType));
            InvalidateDenoiserHistory();
            State::Instance().changeBackend[Handle()->Id] = true;
            return false;
        }
        else
        {
            LOG_INFO("[RR_INPUT] recreating RR context for automatic diffuse classification: {} -> {}",
                     GetSignalTypeName(_diffuseSignalDescType), GetSignalTypeName(resolvedType));
            _autoDiffuseSignalDescType = resolvedType;
            _autoDiffuseSignalResolved = true;
            DestroyDenoiserContext();
            if (!CreateDenoiserContext())
            {
                LOG_ERROR(
                    "[RR_INPUT] failed to recreate RR context for automatic diffuse classification; requesting a feature rebuild");
                State::Instance().changeBackend[Handle()->Id] = true;
                return false;
            }
        }
    }

    return isReady;
}

bool FSRDFeatureDx12::ConvertDenoiserBuffers(ID3D12GraphicsCommandList* InCommandList)
{
    const auto& cfg = *Config::Instance(); 
    const auto dbgMode = static_cast<DebugModes>(cfg.FfxDenoiserDebugMode.value_or_default());
    // Prepare input converter
    _convDesc.RenderSize = 
    { 
        (float) RenderWidth(), (float) RenderHeight(), 
        1.0f / (float) RenderWidth(), 1.0f / (float) RenderHeight()
    };
    _convDesc.Flags = (uint32_t)FSRDConvFlags::NonGammaAlbedo |
        (uint32_t)GetConvDebugFlags(dbgMode);
    if (_convDesc.MotionVectorsJittered)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::MotionVectorsJittered;
    if (_convDesc.DisplayResolutionMotion)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::DisplayResolutionMotion;
    const bool normalsInViewSpace = cfg.FfxDenoiserNormalsInViewSpace.value_or_default();
    if (normalsInViewSpace)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::NormalsViewSpace;

    const int appliedNormalsInViewSpace = normalsInViewSpace ? 1 : 0;
    if (_appliedNormalsInViewSpace != appliedNormalsInViewSpace)
    {
        if (_appliedNormalsInViewSpace >= 0)
        {
            LOG_INFO(
                "[RR_INPUT] normal space changed: {}->{}; resetting denoiser history",
                _appliedNormalsInViewSpace != 0 ? "view" : "world",
                normalsInViewSpace ? "view" : "world");
            InvalidateDenoiserHistory();
        }
        _appliedNormalsInViewSpace = appliedNormalsInViewSpace;
    }
    if (_specularSignalDescType == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::SpecularSignalIndirect;
    _convDesc.FloorIsolation = std::clamp(cfg.FfxDenoiserFloorIsolation.value_or_default(), 0.0f, 1.0f);
    _convDesc.RoughnessFloor = std::clamp(
        cfg.FfxDenoiserRoughnessFloor.value_or_default(), 0.0f, 1.0f);
    _convDesc.ZeroRoughHandover = cfg.FfxDenoiserZeroRoughHandover.value_or_default();
    _convDesc.ZeroRoughDetail = std::clamp(
        cfg.FfxDenoiserZeroRoughDetail.value_or_default(), 0.0f, 1.0f);
    _convDesc.ZeroRoughDetailMode = static_cast<FSRDConvDesc::ZeroRoughDetailFilter>(
        std::clamp(cfg.FfxDenoiserZeroRoughDetailMode.value_or_default(), 0,
                   static_cast<int>(FSRDConvDesc::ZeroRoughDetailFilter::Count) - 1));

    _convDesc.Resources.InInspector = nullptr;
    _convDesc.InspectorChannel = ResTrack_Dx12::GetRRResourceChannel();
    _convDesc.InspectorScale = ResTrack_Dx12::GetRRResourceViewScale();
    // Same clamp as the RR debug-bounds configure key below and as the menu slider.
    // They previously disagreed - max(v, 1.0) here against clamp(v, 0.001, 1024)
    // there - so any value under 1.0 normalized OptiScaler's own NormDepth view
    // differently from AMD's, and the two could not be compared.
    _convDesc.DebugDepthMax =
        std::clamp(cfg.FfxDenoiserDebugDepthMax.value_or_default(), 0.001f, 1024.0f);

    Microsoft::WRL::ComPtr<ID3D12Resource> inspectorResource;
    if (ResTrack_Dx12::IsRRResourceInspectorEnabled())
    {
        ResTrack_Dx12::NotifyRRResourceInspectorFrame(_frameCount);
        ResTrack_Dx12::RefreshRRResourceCandidates(RenderWidth(), RenderHeight());
        if (dbgMode == DebugModes::ResourceInspector)
        {
            inspectorResource.Attach(ResTrack_Dx12::AcquireRRResourceCandidate());
            _convDesc.Resources.InInspector = inspectorResource.Get();
        }
    }

    if (_convDesc.RoughnessFloor != _appliedRoughnessFloor)
    {
        if (_appliedRoughnessFloor >= 0.0f)
        {
            LOG_INFO(
                "[RR_DIAG] RR roughness floor changed: floor {:.4f}->{:.4f}; "
                "resetting denoiser history",
                _appliedRoughnessFloor, _convDesc.RoughnessFloor);
        }
        else
        {
            LOG_INFO("[RR_DIAG] RR roughness floor initialized: floor={:.4f}",
                     _convDesc.RoughnessFloor);
        }

        _appliedRoughnessFloor = _convDesc.RoughnessFloor;
        InvalidateDenoiserHistory();
    }

    // The change check above can invalidate history after
    // PrepareDenoiseConvInput already froze the reprojection inputs from the old
    // value of _hasDenoiserHistory. Re-derive them, or the conversion pass would
    // reproject against a previous-frame depth produced under the previous setting
    // on the very frame the RR dispatch resets.
    if (!_hasDenoiserHistory || _isInReset)
    {
        _convDesc.MotionHistoryValid = false;
        _convDesc.JitterOffsets.z = _convDesc.JitterOffsets.x;
        _convDesc.JitterOffsets.w = _convDesc.JitterOffsets.y;
    }

    if (_roughnessSource == RoughnessSource::Packed)
        _convDesc.Flags |= (uint32_t) FSRDConvFlags::IsRoughnessPacked;

    if (_convDesc.Resources.InSpecHitDist)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::HasSpecHitDistance;
    if (_convDesc.Resources.InEmissive)
        _convDesc.Flags |= (uint32_t) FSRDConvFlags::HasEmissiveInput;

    StoreHlslColumnVectorMatrix(_convDesc.InvViewMatrix, _invViewMatrix);

    // Inverse perspective projection
    const XMMATRIX invProjMatrix = XMMatrixInverse(nullptr, _projMatrix);
    StoreHlslColumnVectorMatrix(_convDesc.InvProjMatrix, invProjMatrix);

    // Previous world to view for linear depth delta
    StoreHlslColumnVectorMatrix(_convDesc.PrevViewMatrix, _prevViewMatrix);

    // Near and far planes
    const ViewPlanes planes = GetViewPlanes(_projMatrix, DepthInverted());
    _convDesc.NearPlane = planes.nearPlane;
    _convDesc.FarPlane = planes.farPlane;
    _isRightHanded = planes.isRightHanded;

    // Every geometric quantity downstream - linearised depth, world-position
    // reconstruction and the far-plane skip test - is derived from these two numbers
    // and the raw projection terms behind them. Report them directly rather than inferring
    // them from debug-view colours, which cannot distinguish a depth clamped to
    // near from one clamped to far. Logged only when the values change.
    {
        static float loggedNear = -1.0f;
        static float loggedFar = -1.0f;
        if (planes.nearPlane != loggedNear || planes.farPlane != loggedFar)
        {
            loggedNear = planes.nearPlane;
            loggedFar = planes.farPlane;
            LOG_INFO(
                "[RR_DIAG] view planes: near={}, far={}, infinite={}, rightHanded={}, "
                "depthInverted={}, hardwareDepth={}, projectionFromStreamline={}, "
                "clipA={}, clipB={}, clipW={}",
                planes.nearPlane, planes.farPlane, planes.isInfinite,
                planes.isRightHanded, DepthInverted(), _isHWDepth,
                _projectionFromStreamline,
                _projMatrix.r[2].m128_f32[2], _projMatrix.r[2].m128_f32[3],
                _projMatrix.r[3].m128_f32[2]);
        }
    }

    if (_isRightHanded)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::RightHanded;

    // Resolve the effective depth interpretation. A user override wins over whatever
    // NGX reported, and it is applied per frame rather than latched at init so it can
    // be toggled while watching the depth debug view. Switching changes the units of
    // the internal previous-depth texture, so it has to reset temporal history.
    //
    // Precedence: user override, then conclusive evidence from the resource itself,
    // then the NGX declaration, then a base-rate assumption.
    //
    // The declaration deliberately does NOT outrank a depth-stencil resource. NGX
    // publishes DLSS.Use.HW.Depth from NVSDK_NGX_DLSSD_Create_Params::depthType, and
    // Linear is zero - so every title that zero-initializes that struct "declares"
    // linear without meaning to. A declaration is therefore only trustworthy when the
    // resource does not contradict it, and nothing writes a linearized view-space
    // distance into a depth-stencil attachment.
    const DepthResourceKind depthKind = ClassifyDepthResource(_convDesc.Resources.InDepth);

    bool hardwareDepth;
    const char* depthSource;

    if (cfg.FfxDenoiserHardwareDepth.has_value())
    {
        hardwareDepth = cfg.FfxDenoiserHardwareDepth.value();
        depthSource = "user override";
    }
    else if (depthKind == DepthResourceKind::HardwareDepth)
    {
        hardwareDepth = true;
        depthSource = (_hasNGXDepthType && !_ngxReportedHWDepth)
            ? "depth-stencil resource, overriding the title's linear declaration"
            : "depth-stencil resource";
    }
    else if (_hasNGXDepthType)
    {
        hardwareDepth = _ngxReportedHWDepth;
        depthSource = "NGX declaration";
    }
    else if (depthKind == DepthResourceKind::GameWritten)
    {
        // Render-target or UAV capable and not depth-stencil: the title's own shaders
        // filled this, which is what a pre-linearized depth target looks like.
        hardwareDepth = false;
        depthSource = "undeclared; game-written target, assuming linear";
    }
    else
    {
        // Undeclared and unclassifiable. Hardware depth is the overwhelmingly common
        // case in DLSS-RR titles, and guessing linear here is the failure that
        // collapses the whole scene into [near, 1].
        hardwareDepth = true;
        depthSource = "undeclared and unclassifiable, assuming hardware";
    }

    const int appliedHardwareDepth = hardwareDepth ? 1 : 0;

    if (_appliedHardwareDepth != appliedHardwareDepth)
    {
        if (_appliedHardwareDepth >= 0)
        {
            LOG_INFO("[RR_INPUT] depth interpretation changed: {} -> {}; resetting denoiser history",
                     _appliedHardwareDepth != 0 ? "hardware" : "linear",
                     hardwareDepth ? "hardware" : "linear");
            InvalidateDenoiserHistory();
        }
        else
        {
            // Report the evidence, not just the verdict: when the resource is
            // unclassifiable this is the only way to tell why auto chose what it did.
            DXGI_FORMAT depthFormat = DXGI_FORMAT_UNKNOWN;
            uint32_t depthFlags = 0;
            if (_convDesc.Resources.InDepth)
            {
                const D3D12_RESOURCE_DESC depthDesc = _convDesc.Resources.InDepth->GetDesc();
                depthFormat = depthDesc.Format;
                depthFlags = static_cast<uint32_t>(depthDesc.Flags);
            }

            LOG_INFO(
                "[RR_INPUT] depth interpretation: {} (source: {}); resource format={}, "
                "resourceFlags={:#x}, ngxDeclared={}",
                hardwareDepth ? "hardware" : "linear", depthSource,
                magic_enum::enum_name(depthFormat), depthFlags,
                _hasNGXDepthType ? (_ngxReportedHWDepth ? "hardware" : "linear") : "absent");
        }

        _appliedHardwareDepth = appliedHardwareDepth;
    }

    _isHWDepth = hardwareDepth;

    if (!_isHWDepth)
        _convDesc.Flags |= (uint32_t) FSRDConvFlags::IsDepthLinear;

    LOG_DEBUG("Distpaching FSRD Input Converter");

    // Dispatch resource converter. Outputs are automatically transitioned for reading.
    if (!FSRDConvShader->DispatchConversion(InCommandList, _convDesc))
    {
        _convDesc.Resources.InInspector = nullptr;
        return false;
    }

    // From here on the converter's textures are referenced by a command list the
    // application will submit, so they must not be released out from under it.
    _preprocessorHasRecordedWork = true;

    _convDesc.Resources.InInspector = nullptr;
    return true;
}

static bool ValidateRRDispatchChain(ID3D12GraphicsCommandList* commandList,
                                    const ffxDispatchDescDenoiser& dispatchDesc,
                                    ffxStructType_t expectedDiffuseType,
                                    ffxStructType_t expectedSpecularType,
                                    bool expectedAmbientOcclusion)
{
    if (!commandList || dispatchDesc.commandList != commandList)
    {
        LOG_ERROR("RR 1.2 dispatch has a null or mismatched D3D12 command list");
        return false;
    }

    if (dispatchDesc.header.type != FFX_API_DISPATCH_DESC_TYPE_DENOISER)
    {
        LOG_ERROR("RR 1.2 dispatch head has an invalid descriptor type: {0:X}", dispatchDesc.header.type);
        return false;
    }

    bool foundDiffuse = false;
    bool foundSpecular = false;
    bool foundAmbientOcclusion = false;
    bool foundDebugView = false;

    for (const ffxDispatchDescHeader* signal = dispatchDesc.header.pNext;
         signal != nullptr; signal = signal->pNext)
    {
        if (signal->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW)
        {
            if (foundDebugView || signal->pNext)
            {
                LOG_ERROR("RR 1.2 debug descriptor must appear once at the chain tail");
                return false;
            }

            foundDebugView = true;
            continue;
        }

        bool* found = nullptr;
        if (signal->type == expectedDiffuseType)
            found = &foundDiffuse;
        else if (signal->type == expectedSpecularType)
            found = &foundSpecular;
        else if (signal->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_AMBIENT_OCCLUSION)
            found = &foundAmbientOcclusion;
        else
        {
            LOG_ERROR("RR 1.2 dispatch contains unexpected descriptor {} ({:#x})",
                      GetSignalTypeName(signal->type), signal->type);
            return false;
        }

        if (*found)
        {
            LOG_ERROR("RR 1.2 dispatch contains duplicate {} descriptor",
                      GetSignalTypeName(signal->type));
            return false;
        }
        *found = true;
    }

    if (!foundDiffuse || !foundSpecular || foundAmbientOcclusion != expectedAmbientOcclusion)
    {
        LOG_ERROR("RR 1.2 dispatch signal mismatch: diffuse={}, specular={}, AO={}; "
                  "expected diffuse=true, specular=true, AO={}",
                  foundDiffuse, foundSpecular, foundAmbientOcclusion, expectedAmbientOcclusion);
        return false;
    }

    return true;
}

bool FSRDFeatureDx12::DispatchDenoiser(ID3D12GraphicsCommandList* InCommandList,
                                       const ffxDispatchDescDenoiser& dispatchDesc)
{
    auto& state = State::Instance();
    const auto& cfg = *Config::Instance();

    if (!_pDenoiserCtx)
    {
        LOG_ERROR("RR 1.2 dispatch attempted without a denoiser context");
        return false;
    }

    if (!ValidateRRDispatchChain(InCommandList, dispatchDesc,
                                 _diffuseSignalDescType, _specularSignalDescType,
                                 _ambientOcclusionEnabled))
        return false;

    const ffxDispatchDescHeader* diffuseHeader = nullptr;
    const ffxDispatchDescHeader* specularHeader = nullptr;
    const ffxDispatchDescHeader* ambientOcclusionHeader = nullptr;
    for (const ffxDispatchDescHeader* signal = dispatchDesc.header.pNext;
         signal != nullptr; signal = signal->pNext)
    {
        if (signal->type == _diffuseSignalDescType)
            diffuseHeader = signal;
        else if (signal->type == _specularSignalDescType)
            specularHeader = signal;
        else if (signal->type == FFX_API_DISPATCH_DESC_TYPE_DENOISER_AMBIENT_OCCLUSION)
            ambientOcclusionHeader = signal;
    }

    // All four RR 1.2 diffuse/specular descriptor structures have the same
    // header + signal ABI; these concrete types provide named signal access.
    const auto& directDiffuse =
        *reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(diffuseHeader);
    const auto& indirectSpecular =
        *reinterpret_cast<const ffxDispatchDescDenoiserIndirectSpecular*>(specularHeader);
    const auto* ambientOcclusion = ambientOcclusionHeader
        ? reinterpret_cast<const ffxDispatchDescDenoiserAmbientOcclusion*>(ambientOcclusionHeader)
        : nullptr;
    const bool resetRequested = !!(dispatchDesc.flags & FFX_DENOISER_DISPATCH_RESET);
    const bool resetTransition = resetRequested && !_lastDispatchRequestedReset;
    const bool logDispatchSnapshot = _logNextDenoiserDispatch || resetTransition;

    if (logDispatchSnapshot)
    {
        LogRRDispatchSnapshot(dispatchDesc, directDiffuse, indirectSpecular, ambientOcclusion);
        LogRRDiffuseHitDistanceProbe(
            NVSDK_NGX_Parameter_DLSSD_DiffuseHitDistance,
            _diffuseHitDistanceProbe,
            _diffuseHitDistanceBaseX,
            _diffuseHitDistanceBaseY,
            dispatchDesc.renderSize.width,
            dispatchDesc.renderSize.height,
            false);
        LogRRDiffuseHitDistanceProbe(
            NVSDK_NGX_Parameter_DLSSD_DiffuseRayDirectionHitDistance,
            _diffuseRayDirectionHitDistanceProbe,
            _diffuseRayDirectionHitDistanceBaseX,
            _diffuseRayDirectionHitDistanceBaseY,
            dispatchDesc.renderSize.width,
            dispatchDesc.renderSize.height,
            true);
        LogRREmissiveProbe(
            _emissiveProbe,
            _emissiveProbeCompatible,
            _emissiveProbeFromStreamline,
            dispatchDesc.renderSize.width,
            dispatchDesc.renderSize.height);
        LogRRGBufferIdentityProbe(
            NVSDK_NGX_Parameter_GBuffer_MaterialId,
            _materialIdProbe,
            dispatchDesc.renderSize.width,
            dispatchDesc.renderSize.height);
        LogRRGBufferIdentityProbe(
            NVSDK_NGX_Parameter_GBuffer_ShadingModelId,
            _shadingModelIdProbe,
            dispatchDesc.renderSize.width,
            dispatchDesc.renderSize.height);
        StreamlineHooks::logRRSignalTagDiagnostics(
            dispatchDesc.renderSize.width, dispatchDesc.renderSize.height);
        StreamlineHooks::logSLTagInventoryDiagnostics(
            dispatchDesc.renderSize.width, dispatchDesc.renderSize.height);
        StreamlineHooks::logRRNGXPointerDiagnostics();
        ResTrack_Dx12::LogRRScalarResourceCandidates(
            dispatchDesc.renderSize.width, dispatchDesc.renderSize.height);
        LOG_INFO(
            "[RR_DIAG] conversion snapshot: viewSource={}, projectionSource={}, handedness={}, depthInput={}, "
            "depthDirection={}, motionResolution={}, roughness={}, roughnessFloor={:.4f}, "
            "zeroRoughnessMaterialType=unified-type-1, "
            "specularHitDistance={} (invalid={}), diffuseHitDistance={}, diffuseDirectionHitDistance={}, "
            "emissiveInput={} (previewCompatible={})",
            _viewFromStreamline ? "Streamline" : "NGX",
            _projectionFromStreamline ? "StreamlineReconstruction" : "NGX",
            _isRightHanded ? "RH" : "LH",
            _isHWDepth ? "hardware" : "linear",
            DepthInverted() ? "reversed-Z" : "standard-Z",
            LowResMV() ? "render" : "output",
            _roughnessSource == RoughnessSource::Packed ? "packed" : "separate",
            _convDesc.RoughnessFloor,
            (_convDesc.Resources.InSpecHitDist ||
             _convDesc.Resources.InSpecularRayDirectionHitDistance)
                ? "present"
                : "absent",
            _specularSignalDescType == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR
                ? "negative"
                : "zero",
            _diffuseHitDistanceProbe ? "present" : "absent",
            _diffuseRayDirectionHitDistanceProbe ? "present" : "absent",
            _emissiveProbe ? "present" : "absent",
            _emissiveProbeCompatible);
    }

    // A/B reference: push AMD's queried baseline instead of the fork's tuned values.
    // The INI/menu values are left untouched so toggling back restores them, and the
    // comparison below re-applies whichever source just became active.
    const bool useAmdDefaults = cfg.FfxDenoiserUseAmdDefaults.value_or_default();

    const auto updateConfiguration = [this, useAmdDefaults](
                                         const CustomOptional<float>& cfgValue, float amdDefault,
                                         float& currentValue, FfxApiConfigureDenoiserKey key)
    {
        const float requestedValue = useAmdDefaults ? amdDefault : cfgValue.value_or_default();
        if (requestedValue == currentValue)
            return true;

        const float previousValue = currentValue;
        currentValue = requestedValue;

        const ffxReturnCode_t result = ApplyConfiguration(key);
        if (result == FFX_API_RETURN_OK)
            return true;

        // Retry on the next frame instead of treating the failed value as applied.
        currentValue = previousValue;
        LOG_ERROR("[RR_DIAG] RR 1.2 configure key {} failed: {}", static_cast<uint64_t>(key),
                  FfxApiProxy::ReturnCodeToString(result));
        return false;
    };

    if (!updateConfiguration(cfg.FfxDenoiserDisocThreshold, _denoiserAmdDefaults.m_DisocclusionThreshold,
                             _denoiserSettings.m_DisocclusionThreshold,
                             FFX_API_CONFIGURE_DENOISER_KEY_DISOCCLUSION_THRESHOLD) ||
        !updateConfiguration(cfg.FfxDenoiserCrossBlNormStr, _denoiserAmdDefaults.m_CrossBilateralNormalStrength,
                             _denoiserSettings.m_CrossBilateralNormalStrength,
                             FFX_API_CONFIGURE_DENOISER_KEY_CROSS_BILATERAL_NORMAL_STRENGTH) ||
        !updateConfiguration(cfg.FfxDenoiserStabilityBias, _denoiserAmdDefaults.m_StabilityBias,
                             _denoiserSettings.m_StabilityBias,
                             FFX_API_CONFIGURE_DENOISER_KEY_STABILITY_BIAS) ||
        !updateConfiguration(cfg.FfxDenoiserMaxRadiance, _denoiserAmdDefaults.m_MaxRadiance,
                             _denoiserSettings.m_MaxRadiance,
                             FFX_API_CONFIGURE_DENOISER_KEY_MAX_RADIANCE) ||
        !updateConfiguration(cfg.FfxDenoiserRadianceClip, _denoiserAmdDefaults.m_RadianceClipStdK,
                             _denoiserSettings.m_RadianceClipStdK,
                             FFX_API_CONFIGURE_DENOISER_KEY_RADIANCE_CLIP_STD_K) ||
        !updateConfiguration(cfg.FfxDenoiserGaussKernRelax, _denoiserAmdDefaults.m_GaussianKernelRelaxation,
                             _denoiserSettings.m_GaussianKernelRelaxation,
                             FFX_API_CONFIGURE_DENOISER_KEY_GAUSSIAN_KERNEL_RELAXATION))
    {
        return false;
    }

    const float requestedDebugDepthMax =
        std::clamp(cfg.FfxDenoiserDebugDepthMax.value_or_default(), 0.001f, 1024.0f);
    if (requestedDebugDepthMax != _denoiserSettings.m_DebugViewLinearDepthBounds.max)
    {
        const FfxApiFloatBounds previousBounds = _denoiserSettings.m_DebugViewLinearDepthBounds;
        _denoiserSettings.m_DebugViewLinearDepthBounds.max = requestedDebugDepthMax;

        const ffxReturnCode_t result =
            ApplyConfiguration(FFX_API_CONFIGURE_DENOISER_KEY_DEBUG_VIEW_LINEAR_DEPTH_BOUNDS);
        if (result != FFX_API_RETURN_OK)
        {
            _denoiserSettings.m_DebugViewLinearDepthBounds = previousBounds;
            LOG_ERROR("[RR_DIAG] RR 1.2 debug linear-depth bounds configure failed: {}",
                      FfxApiProxy::ReturnCodeToString(result));
            return false;
        }
    }

    ID3D12InfoQueue* infoQueue = nullptr;
    uint64_t firstD3D12Message = 0;
    const bool hasScopedInfoQueue =
        logDispatchSnapshot && Device &&
        SUCCEEDED(Device->QueryInterface(IID_PPV_ARGS(&infoQueue)));

    if (hasScopedInfoQueue)
    {
        firstD3D12Message = infoQueue->GetNumStoredMessagesAllowedByRetrievalFilter();
    }
    else if (logDispatchSnapshot)
    {
        LOG_INFO(
            "[RR_DIAG][D3D12] InfoQueue unavailable. Dispatch return codes and device-removal reason are still "
            "captured; enable the D3D12 debug layer before device creation for validation messages.");
    }

    ++_denoiserDispatchAttempts;
    LOG_DEBUG("Dispatching FSR-RR 1.2 frame {} with {} + {}",
              dispatchDesc.frameIndex,
              GetSignalTypeName(_diffuseSignalDescType),
              GetSignalTypeName(_specularSignalDescType));
    const ffxReturnCode_t result = FfxApiProxy::D3D12_Dispatch(&_pDenoiserCtx, &dispatchDesc.header);
    _lastDispatchRequestedReset = resetRequested;

    if (hasScopedInfoQueue)
    {
        const std::string scope = std::format("frame {}", dispatchDesc.frameIndex);
        LogRRD3D12Messages(infoQueue, firstD3D12Message, scope);
    }

    if (result != FFX_API_RETURN_OK)
    {
        ++_denoiserDispatchFailures;
        LOG_ERROR(
            "[RR_DIAG] dispatch failed: frame={}, result={}, attempts={}, successes={}, failures={}",
            dispatchDesc.frameIndex, FfxApiProxy::ReturnCodeToString(result),
            _denoiserDispatchAttempts, _denoiserDispatchSuccesses, _denoiserDispatchFailures);

        if (!hasScopedInfoQueue && Device &&
            SUCCEEDED(Device->QueryInterface(IID_PPV_ARGS(&infoQueue))))
        {
            const uint64_t messageCount = infoQueue->GetNumStoredMessagesAllowedByRetrievalFilter();
            const uint64_t firstRecentMessage = messageCount > 32u ? messageCount - 32u : 0u;
            const std::string scope = std::format("recent messages after failed frame {}", dispatchDesc.frameIndex);
            LogRRD3D12Messages(infoQueue, firstRecentMessage, scope);
        }

        if (Device)
        {
            const HRESULT removedReason = Device->GetDeviceRemovedReason();
            if (removedReason == S_OK)
            {
                LOG_INFO("[RR_DIAG] D3D12 device remains operational after the failed RR dispatch");
            }
            else
            {
                LOG_ERROR("[RR_DIAG] D3D12 device is removed: HRESULT={:#x}",
                          static_cast<uint32_t>(removedReason));
                Util::GetDeviceRemovedReason(Device);
            }
        }

        if (result == FFX_API_RETURN_ERROR_RUNTIME_ERROR)
        {
            LOG_WARN("Trying to recover by recreating the feature");
            state.changeBackend[Handle()->Id] = true;
        }

        if (infoQueue)
            infoQueue->Release();

        return false;
    }

    ++_denoiserDispatchSuccesses;

    if (_logNextDenoiserDispatch)
    {
        LOG_INFO(
            "[RR_DIAG] first dispatch succeeded: frame={}, context={:X}, attempts={}, reset={}",
            dispatchDesc.frameIndex, reinterpret_cast<uintptr_t>(_pDenoiserCtx),
            _denoiserDispatchAttempts, resetRequested);
        _logNextDenoiserDispatch = false;
    }
    else if (resetTransition)
    {
        LOG_INFO("[RR_DIAG] reset dispatch succeeded: frame={}", dispatchDesc.frameIndex);
    }
    else if (_denoiserDispatchSuccesses == 60u || _denoiserDispatchSuccesses == 600u)
    {
        LOG_INFO("[RR_DIAG] dispatch stability milestone: {} successful dispatches, {} failures",
                 _denoiserDispatchSuccesses, _denoiserDispatchFailures);
    }

    if (infoQueue)
        infoQueue->Release();

    return true;
}

void FSRDFeatureDx12::CommitDenoiserHistory() noexcept
{
    _lastCamPos = GetFloat3Column(_invViewMatrix, 3);
    _prevViewMatrix = _viewMatrix;
    _previousDenoiserJitter = {
        _convDesc.JitterOffsets.x,
        _convDesc.JitterOffsets.y
    };
    _hasDenoiserHistory = true;
}

bool FSRDFeatureDx12::SetDefaultConfiguration()
{
    for (int i = 0; i < DenoiserConfiguration::kKeyCount; i++)
    {
        const FfxApiConfigureDenoiserKey key = DenoiserConfiguration::GetIndexKey(i);
        const ffxReturnCode_t result = SetDefaultConfiguration(key);
        if (result != FFX_API_RETURN_OK)
        {
            LOG_ERROR("RR 1.2 default query for key {} failed: {}", static_cast<uint64_t>(key),
                      FfxApiProxy::ReturnCodeToString(result));
            return false;
        }
    }

    return true;
}

ffxReturnCode_t FSRDFeatureDx12::SetDefaultConfiguration(FfxApiConfigureDenoiserKey key)
{
    void* data = _denoiserSettings.GetData(key);
    if (!data)
        return FFX_API_RETURN_ERROR_PARAMETER;

    ffxQueryDescDenoiserGetDefaultKeyValue queryDesc = 
    {
        .header = { .type = FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_KEYVALUE }, 
        .key = (uint64_t)key, 
        .count = 1u,
        .data = data
    };

    const ffxReturnCode_t code = FfxApiProxy::D3D12_Query(&_pDenoiserCtx, &queryDesc.header);
    return code;
}

ffxReturnCode_t FSRDFeatureDx12::ApplyConfiguration(FfxApiConfigureDenoiserKey key)
{
    const void* data = _denoiserSettings.GetData(key);
    if (!data)
        return FFX_API_RETURN_ERROR_PARAMETER;

    ffxConfigureDescDenoiserKeyValue configureDesc =
    {
        .header = { .type = FFX_API_CONFIGURE_DESC_TYPE_DENOISER_KEYVALUE }, 
        .key = (uint64_t)key, 
        .count = 1u,
        .data = data
    };

    const ffxReturnCode_t code = FfxApiProxy::D3D12_Configure(&_pDenoiserCtx, &configureDesc.header);
    return code;
}
