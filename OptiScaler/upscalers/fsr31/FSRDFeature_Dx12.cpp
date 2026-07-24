#include "pch.h"
#include <nvsdk_ngx_defs_dlssd.h>
#include <DirectXMath.h>
#include <d3d12sdklayers.h>
#include "NVNGX_Parameter.h"
#include "hooks/Streamline_Hooks.h"
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
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE == 0x00050044u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR == 0x00050045u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE == 0x00050047u);
static_assert(FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR == 0x00050048u);
static_assert(sizeof(ffxCreateContextDescDenoiser) == 40u);
static_assert(sizeof(ffxDispatchDescDenoiser) == 448u);
static_assert(sizeof(ffxDispatchDescDenoiserDirectDiffuse) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserDirectSpecular) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserIndirectDiffuse) == 120u);
static_assert(sizeof(ffxDispatchDescDenoiserIndirectSpecular) == 120u);

static bool UseIndirectSignal(const CustomOptional<int>& setting)
{
    return std::clamp(setting.value_or_default(), 0, 1) == 1;
}

static ffxStructType_t GetDiffuseSignalDescType(const Config& cfg)
{
    return UseIndirectSignal(cfg.FfxDenoiserDiffuseSignalType)
        ? FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE
        : FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
}

static ffxStructType_t GetSpecularSignalDescType(const Config& cfg)
{
    return UseIndirectSignal(cfg.FfxDenoiserSpecularSignalType)
        ? FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR
        : FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR;
}

static uint32_t GetSignalFlag(ffxStructType_t descriptorType)
{
    switch (descriptorType)
    {
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE:
        return FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR:
        return FFX_DENOISER_SIGNAL_DIRECT_SPECULAR;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE:
        return FFX_DENOISER_SIGNAL_INDIRECT_DIFFUSE;
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR:
        return FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR;
    default:
        return FFX_DENOISER_SIGNAL_NONE;
    }
}

static const char* GetSignalTypeName(ffxStructType_t descriptorType)
{
    switch (descriptorType)
    {
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE:
        return "DirectDiffuse";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_SPECULAR:
        return "DirectSpecular";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE:
        return "IndirectDiffuse";
    case FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR:
        return "IndirectSpecular";
    default:
        return "Unknown";
    }
}

class DenoiserOutputStateGuard
{
  public:
    DenoiserOutputStateGuard(FSRDPreprocessor_Dx12* preprocessor, ID3D12GraphicsCommandList* commandList) :
        _preprocessor(preprocessor), _commandList(commandList)
    {
    }

    ~DenoiserOutputStateGuard()
    {
        if (_preprocessor)
            _preprocessor->TransitionDenoiserOutputsToRead(_commandList);
    }

    DenoiserOutputStateGuard(const DenoiserOutputStateGuard&) = delete;
    DenoiserOutputStateGuard& operator=(const DenoiserOutputStateGuard&) = delete;

  private:
    FSRDPreprocessor_Dx12* _preprocessor;
    ID3D12GraphicsCommandList* _commandList;
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

using RequiredRRResources = std::array<RequiredRRResource, 9>;

static RequiredRRResources GetRequiredRRResources(
    const ffxDispatchDescDenoiser& dispatchDesc,
    const ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
    const ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular)
{
    return RequiredRRResources {
        {
            { "LinearDepth", dispatchDesc.linearDepth, DXGI_FORMAT_R32_FLOAT },
            { "MotionVectors", dispatchDesc.motionVectors, DXGI_FORMAT_R16G16B16A16_FLOAT },
            { "Normals", dispatchDesc.normals, DXGI_FORMAT_R10G10B10A2_UNORM },
            { "SpecularAlbedo", dispatchDesc.specularAlbedo, DXGI_FORMAT_R8G8B8A8_UNORM },
            { "DiffuseAlbedo", dispatchDesc.diffuseAlbedo, DXGI_FORMAT_R8G8B8A8_UNORM },
            { "DiffuseSignal.Input", directDiffuse.signal.input, DXGI_FORMAT_R16G16B16A16_FLOAT },
            { "DiffuseSignal.Output", directDiffuse.signal.output, DXGI_FORMAT_R16G16B16A16_FLOAT },
            { "SpecularSignal.Input", indirectSpecular.signal.input, DXGI_FORMAT_R16G16B16A16_FLOAT },
            { "SpecularSignal.Output", indirectSpecular.signal.output, DXGI_FORMAT_R16G16B16A16_FLOAT },
        }
    };
}

static bool ValidateRequiredRRResources(const ffxDispatchDescDenoiser& dispatchDesc,
                                        const ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
                                        const ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular)
{
    const RequiredRRResources requirements =
        GetRequiredRRResources(dispatchDesc, directDiffuse, indirectSpecular);

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

        if (desc.Width != dispatchDesc.renderSize.width || desc.Height != dispatchDesc.renderSize.height)
        {
            LOG_ERROR("Required RR 1.2 resource {} has resolution {}x{}; expected {}x{}",
                      requirement.name, desc.Width, desc.Height,
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
                                  const ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular)
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

    const ffxDispatchDescHeader* firstSignal = dispatchDesc.header.pNext;
    const ffxDispatchDescHeader* secondSignal = firstSignal ? firstSignal->pNext : nullptr;
    const ffxDispatchDescHeader* optionalTail = secondSignal ? secondSignal->pNext : nullptr;
    LOG_INFO("[RR_DIAG] chain: head={:#x} -> {}={:#x} -> {}={:#x} -> tail={:#x}",
             dispatchDesc.header.type,
             firstSignal ? GetSignalTypeName(firstSignal->type) : "Missing",
             firstSignal ? firstSignal->type : ffxStructType_t {},
             secondSignal ? GetSignalTypeName(secondSignal->type) : "Missing",
             secondSignal ? secondSignal->type : ffxStructType_t {},
             optionalTail ? optionalTail->type : ffxStructType_t {});

    const RequiredRRResources requirements =
        GetRequiredRRResources(dispatchDesc, directDiffuse, indirectSpecular);

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

    const float infiniteCheckVal = isInverted ? A : (A - W);
    planes.isInfinite = std::abs(infiniteCheckVal) < 1e-6f;
    // W is +1 for LH projections and -1 for RH projections, independent of Z direction.
    planes.isRightHanded = W < 0.0f;

    if (isInverted)
    {
        // Inverted: Near is at D=1, Far is at D=0
        // 1 = A/W + B/(n*W) -> n = B / (W - A)
        planes.nearPlane = std::abs(B / (W - A));

        // 0 = A/W + B/(f*W) -> f = -B / A
        planes.farPlane = planes.isInfinite ? std::numeric_limits<float>::max() : std::abs(-B / A);
    }
    else
    {
        // Standard: Near is at D=0, Far is at D=1
        // 0 = A/W + B/(n*W) -> n = -B / A
        planes.nearPlane = std::abs(-B / A);

        // 1 = A/W + B/(f*W) -> f = B / (W - A)
        planes.farPlane = planes.isInfinite
            ? std::numeric_limits<float>::max()
            : std::abs(B / (W - A));
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

    CompositionDebugOffset = 16u,
    CompositionDebug = (uint64_t) FSRDCompFlags::Debug << CompositionDebugOffset,
    CompositionDebugMask = (uint64_t)FSRDCompFlags::DebugModeMask,

    Correlation = (uint64_t)FSRDCompFlags::DebugCorrelation << CompositionDebugOffset,
    SkipSignal = (uint64_t) FSRDCompFlags::DebugSkipSignal << CompositionDebugOffset,
    DenoiserOutput = (uint64_t) FSRDCompFlags::DebugDenoiserOutput << CompositionDebugOffset,
    IndirectSpecular = (uint64_t) FSRDCompFlags::DebugIndirectSpecular << CompositionDebugOffset,
    DirectDiffuse = (uint64_t) FSRDCompFlags::DebugDirectDiffuse << CompositionDebugOffset,
    IndirectDiffuse = (uint64_t) FSRDCompFlags::DebugIndirectDiffuse << CompositionDebugOffset,
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

    { "InputMotionVectors", (uint64_t) DebugModes::InMotion },
    { "InNormals", (uint64_t) DebugModes::InNormals },
    { "InputRoughness", (uint64_t) DebugModes::InRoughness },
    { "RawRoughness", (uint64_t) DebugModes::RawRoughness },
    { "EmissiveMask", (uint64_t) DebugModes::EmissiveMask },
    { "AppliedRoughnessFloor", (uint64_t) DebugModes::AppliedRoughnessFloor },
    { "SpecularHitDistance", (uint64_t) DebugModes::InSpecHitDist },
    { "InDiffAlbedo", (uint64_t) DebugModes::InDiffAlbedo },
    { "InSpecAlbedo", (uint64_t) DebugModes::InSpecAlbedo },

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

    { "FloorVariance", (uint64_t) DebugModes::FloorVariance },
    { "FloorColor", (uint64_t) DebugModes::FloorColor },
    
    { "RawSpecularSignal", (uint64_t) DebugModes::RawIndirectSpecular },
    { "DenoisedSpecularSignal", (uint64_t) DebugModes::IndirectSpecular },
    { "EffectiveRoughness", (uint64_t) DebugModes::EffectiveRoughness },
    { "DenoisedDirectDiffuseSignal", (uint64_t) DebugModes::DirectDiffuse },
    { "DenoisedIndirectDiffuseSignal", (uint64_t) DebugModes::IndirectDiffuse },
});

bool FSRDFeatureDx12::s_isHWDepth = false;
bool FSRDFeatureDx12::s_isRoughnessPacked = false;

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
            s_isHWDepth = value == NVSDK_NGX_DLSS_Depth_Type_HW;

        if (int value; InParameters->Get(NVSDK_NGX_Parameter_DLSS_Roughness_Mode, &value) == NVSDK_NGX_Result_Success)
            s_isRoughnessPacked = value == NVSDK_NGX_DLSS_Roughness_Mode_Packed;

        LOG_INFO("DLSSD Flags HWDepth: {} - IsRoughnessPacked: {}", s_isHWDepth, s_isRoughnessPacked);

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

    _diffuseSignalDescType = GetDiffuseSignalDescType(cfg);
    _specularSignalDescType = GetSpecularSignalDescType(cfg);
    const uint32_t selectedSignalFlags =
        GetSignalFlag(_diffuseSignalDescType) | GetSignalFlag(_specularSignalDescType);

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
    _denoiserCtxDesc = 
    {
        .header = 
        { 
            .type = FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER,
            // Chain backend desc into context desc
            .pNext = &backendDesc.header
        },
        .version = FFX_DENOISER_VERSION,
        .maxRenderSize = { RenderWidth(), RenderHeight() },
        .signalFlags = selectedSignalFlags,
        .checkerboardSignalFlags = FFX_DENOISER_SIGNAL_NONE,
        .flags = 0
    };

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
    LOG_INFO("[RR_DIAG] signal classification: diffuse={}, specular={}",
             GetSignalTypeName(_diffuseSignalDescType), GetSignalTypeName(_specularSignalDescType));
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

    // Create DLSS-RR to FSR-RR input converter
    FSRDConvShader = std::make_unique<FSRDPreprocessor_Dx12>("FSRD Converter", Device);

    if (!FSRDConvShader->IsInit())
        return false;

    if (!FSRDConvShader->SetMaxRenderSize(_denoiserCtxDesc.maxRenderSize.width, _denoiserCtxDesc.maxRenderSize.height))
        return false;

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
    InvalidateDenoiserHistory();
}

bool FSRDFeatureDx12::UpdateSize()
{
    // FSR-RR doesn't currently have proper DRS support. The example implementation 
    // reinits on resolution change as well.
    const bool needsReInit = 
        _denoiserCtxDesc.maxRenderSize.width != RenderWidth() ||
        _denoiserCtxDesc.maxRenderSize.height != RenderHeight();

    if (needsReInit)
    {
        LOG_INFO(
            "[RR_DIAG] reinitializing context for resolution change. "
            "Previous: {} x {}, New: {} x {}",
            _denoiserCtxDesc.maxRenderSize.width, _denoiserCtxDesc.maxRenderSize.height,
            RenderWidth(), RenderHeight());

        DestroyDenoiserContext();
        if (!CreateDenoiserContext())
        {
            LOG_ERROR("Failed to reinitialize FSR-RR after a resolution change");
            SetInit(false);
            return false;
        }
    }

    return true;
}

bool FSRDFeatureDx12::Evaluate(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters) 
{
    LOG_FUNC();

    if (!IsInited())
        return false;

    auto& state = State::Instance();
    auto& cfg = *Config::Instance();
    const auto& inParams = *InParameters;

    if (!UpdateSize())
        return false;

    // Conversion leaves the RR signal outputs in UAV state. Always close that
    // state lifetime, including bypass and error paths where composition is skipped.
    DenoiserOutputStateGuard denoiserOutputStateGuard(FSRDConvShader.get(), InCommandList);

    const auto dbgMode = static_cast<DebugModes>(cfg.FfxDenoiserDebugMode.value_or_default());
    const bool isDebugVis = (uint32_t)dbgMode & (uint32_t) DebugModes::ConversionDebug;
    const bool isDebugComp = ((uint64_t)dbgMode & (uint64_t)DebugModes::CompositionDebug);
    const bool isFfxDebug = dbgMode == DebugModes::FfxDebug;
    const bool hasAnyDebug = (dbgMode != DebugModes::None);

    // Denoise is bypassed if we are debugging something OTHER than the final outputs
    const bool isDenoiseBypassed = !isFfxDebug && !isDebugComp && 
        hasAnyDebug && dbgMode != DebugModes::DenoiserOutput && dbgMode != DebugModes::UpscalerBypass;

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
    ffxDispatchDescDenoiserDirectDiffuse directDiffuse = {};
    ffxDispatchDescDenoiserIndirectSpecular indirectSpecular = {};
    ffxDispatchDescDenoiser denoiserDesc = {};
    bool isDenoiserReady = false;

    // Pull configuration and input buffers for DLSS-RR from the param table, convert and 
    // repack input buffers into intermediate FSR-RR input buffers, and configure descriptors.
    if (!PrepareDenoiserInput(InCommandList, *InParameters, denoiserDesc, directDiffuse, indirectSpecular))
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

            ID3D12Resource* dstTex = nullptr;
            if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Output, dstTex))
            {
                InvalidateDenoiserHistory();
                return false;
            }

            dispatchDebugView = 
            { 
                .header = { .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW },
                .output = ffxApiGetResourceDX12(dstTex, FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
                .outputSize = { TargetWidth(), TargetHeight() },
                .mode = FFX_API_DENOISER_DEBUG_VIEW_MODE_OVERVIEW,
                .viewportIndex = 0
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

        if (!isDenoiserReady)
        {
            InvalidateDenoiserHistory();
            return false;
        }

        CommitDenoiserHistory();

        // Compose denoised signals
        uint32_t compositionFlags = (uint32_t)GetCompDebugFlags(dbgMode);
        if (_diffuseSignalDescType == FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_DIFFUSE)
            compositionFlags |= (uint32_t)FSRDCompFlags::DiffuseSignalIndirect;

        FSRDCompDesc compDesc =
        { 
            .DstTexSize = _convDesc.RenderSize,
            .CorrelationBias = std::clamp(cfg.FfxDenoiserCorrelationBias.value_or_default(), 0.0f, 1.0f),
            .Flags = compositionFlags
        };

        TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_Color, compDesc.InRawColor);
        TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles, compDesc.InColorBeforeParticles);

        if (!isFfxDebug && !FSRDConvShader->DispatchComposition(InCommandList, compDesc))
            return false;

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

        // Override upscaler config
        if (isDenoiserReady)
            upscalerDesc.color = ffxApiGetResourceDX12(FSRDConvShader->GetCompositionOutput());

        // Sets optional, configurable resource barriers
        FSR31FeatureDx12::SetConfigurableBarriers(InCommandList);

        bool isUpscalerReady = DispatchUpscaler(InCommandList, upscalerDesc);

        // Post-Process
        if (isUpscalerReady)
            PostProcess(InCommandList, inParams, upscalerDesc);

        // Cleanup
        FSR31FeatureDx12::ResetConfigurableBarriers(InCommandList);
    }
    else if (!isFfxDebug) // Debug visualization
    {
        ID3D12Resource* srcTex = nullptr;

        if (dbgMode == DebugModes::DlssColorBeforeParticles)
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles, srcTex);
        else if (dbgMode == DebugModes::DlssColorBeforeTransparency)
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_ColorBeforeTransparency, srcTex);
        else if (dbgMode == DebugModes::DlssTransparencyLayer)
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSS_TransparencyLayer, srcTex);
        else if (dbgMode == DebugModes::DlssBias)
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask, srcTex);
        else if (dbgMode == DebugModes::RawColor)
            TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_Color, srcTex);
        else if (isDebugVis)
            srcTex = GetD3D12ResFromFFX(indirectSpecular.signal.input);
        else
            srcTex = FSRDConvShader->GetCompositionOutput();

        ID3D12Resource* dstTex;

        if (!srcTex || !TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Output, dstTex))
        {
            _frameCount++;
            return true;
        }

        FSRDConvShader->Blit(InCommandList, srcTex, dstTex);
    }

    _frameCount++;
    return isDenoiserReady || isDenoiseBypassed;
}

bool FSRDFeatureDx12::PrepareDenoiserInput(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& inParams,
    ffxDispatchDescDenoiser& dispatchDesc, ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
    ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular)
{
    const auto& cfg = *Config::Instance(); 

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

    // Match the signal ordering used by AMD's RR 1.2 sample. This matters for
    // the Indirect Diffuse + Direct Specular combination, where specular comes first.
    ffxDispatchDescHeader* firstSignal = &directDiffuse.header;
    ffxDispatchDescHeader* secondSignal = &indirectSpecular.header;
    if (firstSignal->type > secondSignal->type)
        std::swap(firstSignal, secondSignal);

    dispatchDesc.header.pNext = firstSignal;
    firstSignal->pNext = secondSignal;
    secondSignal->pNext = nullptr;

    if (!ValidateRequiredRRResources(dispatchDesc, directDiffuse, indirectSpecular))
        return false;
    
    if (resetHistory)
        dispatchDesc.flags |= FFX_DENOISER_DISPATCH_RESET;

    // Motion Vector Scaling
    // Scaling must result in UV space vectors, unlike FSR/DLSS pixel space vectors
    float MVScaleX = 1.0f, MVScaleY = 1.0f;

    if (inParams.Get(NVSDK_NGX_Parameter_MV_Scale_X, &MVScaleX) == NVSDK_NGX_Result_Success &&
        inParams.Get(NVSDK_NGX_Parameter_MV_Scale_Y, &MVScaleY) == NVSDK_NGX_Result_Success)
    {
        dispatchDesc.motionVectorScale.x = MVScaleX / dispatchDesc.renderSize.width;
        dispatchDesc.motionVectorScale.y = MVScaleY / dispatchDesc.renderSize.height;
    }

    float jitterX = 0.0f, jitterY = 0.0f;
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_X, &jitterX);
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_Y, &jitterY);

    // RR 1.2 defines jitter in screen pixels, matching NGX.
    dispatchDesc.jitterOffsets.x = jitterX;
    dispatchDesc.jitterOffsets.y = jitterY;

    LOG_DEBUG("Jitter pixels [{:.6f}, {:.6f}]", dispatchDesc.jitterOffsets.x, dispatchDesc.jitterOffsets.y);

    return true;
}

bool FSRDFeatureDx12::PrepareDenoiseConvInput(const NVSDK_NGX_Parameter& inParams)
{
    const auto& slData = State::Instance().slLastConstants;

    // Gather DLSS-RR input buffers for conversion and repacking for FSR-RR
    bool isReady = true;

    // Standard TSR buffers
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Color, _convDesc.Resources.InColor))
        isReady = false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_MotionVectors, _convDesc.Resources.InMotionVectors))
        isReady = false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Depth, _convDesc.Resources.InDepth) && LowResMV())
        isReady = false;

    // DLSSD-specific buffers
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_GBuffer_Normals, _convDesc.Resources.InNormals))
        isReady = false;

    // If roughness is not packed into normals, then this texture is mandatory.
    // This value should be available in one of these two buffers in any DLSS-RR implementation.
    if (!s_isRoughnessPacked && !TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_GBuffer_Roughness, _convDesc.Resources.InRoughness))
    {
        LOG_WARN("Expected unpacked roughness buffer from DLSS-RR. Defaulting to packed roughness...");
        s_isRoughnessPacked = true;
    }

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_DiffuseAlbedo, _convDesc.Resources.InDiffAlbedo))
        isReady = false;

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_SpecularAlbedo, _convDesc.Resources.InSpecAlbedo))
        isReady = false;

    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask, _convDesc.Resources.InBiasMask);

    // Optional. RR 1.2 uses this as the indirect-specular ray hit distance.
    _convDesc.Resources.InSpecHitDist = nullptr;
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance,
                         _convDesc.Resources.InSpecHitDist);

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
    
    // Get DLSSD matrices and derive related values
    // World to view/camera space (V)
    _viewMatrix = {};
    _viewFromStreamline = false;

    if (!TryGetNGXColumnVectorMatrix(inParams, NVSDK_NGX_Parameter_DLSS_WORLD_TO_VIEW_MATRIX, _viewMatrix))
    {
        if (StreamlineHooks::isSetConstantsHooked())
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
        if (StreamlineHooks::isSetConstantsHooked())
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

    return isReady;
}

bool FSRDFeatureDx12::ConvertDenoiserBuffers(ID3D12GraphicsCommandList* InCommandList)
{
    const uint32_t dbgMode = (uint32_t)Config::Instance()->FfxDenoiserDebugMode.value_or_default(); 
    const auto& cfg = *Config::Instance(); 
    const auto& slData = State::Instance().slLastConstants;

    // Prepare input converter
    _convDesc.RenderSize = 
    { 
        (float) RenderWidth(), (float) RenderHeight(), 
        1.0f / (float) RenderWidth(), 1.0f / (float) RenderHeight()
    };
    _convDesc.Flags = (uint32_t) FSRDConvFlags::NonGammaAlbedo | (dbgMode & (uint32_t) FSRDConvFlags::DebugModeMask);
    _convDesc.FloorIsolation = std::clamp(cfg.FfxDenoiserFloorIsolation.value_or_default(), 0.0f, 1.0f);
    _convDesc.RoughnessFloor = std::clamp(cfg.FfxDenoiserRoughnessFloor.value_or_default(), 0.0f, 0.01f);
    _convDesc.RoughnessFloorDistance =
        std::clamp(cfg.FfxDenoiserRoughnessFloorDistance.value_or_default(), 0.0f, 1000.0f);

    if (_convDesc.RoughnessFloor != _appliedRoughnessFloor ||
        _convDesc.RoughnessFloorDistance != _appliedRoughnessFloorDistance)
    {
        if (_appliedRoughnessFloor >= 0.0f)
        {
            LOG_INFO(
                "[RR_DIAG] RR roughness floor changed: floor {:.4f}->{:.4f}, distance {:.2f}->{:.2f}; "
                "resetting denoiser history",
                _appliedRoughnessFloor, _convDesc.RoughnessFloor,
                _appliedRoughnessFloorDistance, _convDesc.RoughnessFloorDistance);
        }
        else
        {
            LOG_INFO(
                "[RR_DIAG] RR roughness floor initialized: floor={:.4f}, distance={:.2f}",
                _convDesc.RoughnessFloor, _convDesc.RoughnessFloorDistance);
        }

        _appliedRoughnessFloor = _convDesc.RoughnessFloor;
        _appliedRoughnessFloorDistance = _convDesc.RoughnessFloorDistance;
        InvalidateDenoiserHistory();
    }

    if (s_isRoughnessPacked)
        _convDesc.Flags |= (uint32_t) FSRDConvFlags::IsRoughnessPacked;

    if (_convDesc.Resources.InSpecHitDist)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::HasSpecHitDistance;

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

    if (_isRightHanded)
        _convDesc.Flags |= (uint32_t)FSRDConvFlags::RightHanded;

    if (!s_isHWDepth)
        _convDesc.Flags |= (uint32_t) FSRDConvFlags::IsDepthLinear;

    LOG_DEBUG("Distpaching FSRD Input Converter");

    // Dispatch resource converter. Outputs are automatically transitioned for reading.
    if (!FSRDConvShader->DispatchConversion(InCommandList, _convDesc))
        return false;

    return true;
}

static bool ValidateRRDispatchChain(ID3D12GraphicsCommandList* commandList,
                                    const ffxDispatchDescDenoiser& dispatchDesc,
                                    ffxStructType_t expectedDiffuseType,
                                    ffxStructType_t expectedSpecularType)
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

    const ffxDispatchDescHeader* firstSignal = dispatchDesc.header.pNext;
    const ffxDispatchDescHeader* secondSignal = firstSignal ? firstSignal->pNext : nullptr;
    if (!firstSignal || !secondSignal)
    {
        LOG_ERROR("RR 1.2 dispatch is missing one or both selected signal descriptors");
        return false;
    }

    const bool selectedSignalsPresent =
        (firstSignal->type == expectedDiffuseType && secondSignal->type == expectedSpecularType) ||
        (firstSignal->type == expectedSpecularType && secondSignal->type == expectedDiffuseType);
    if (!selectedSignalsPresent)
    {
        LOG_ERROR("RR 1.2 dispatch signal mismatch: expected {} + {}, received {} + {}",
                  GetSignalTypeName(expectedDiffuseType), GetSignalTypeName(expectedSpecularType),
                  GetSignalTypeName(firstSignal->type), GetSignalTypeName(secondSignal->type));
        return false;
    }

    const ffxDispatchDescHeader* optionalTail = secondSignal->pNext;
    if (optionalTail &&
        (optionalTail->type != FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW || optionalTail->pNext))
    {
        LOG_ERROR("RR 1.2 dispatch has an invalid descriptor after the selected signals");
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
                                 _diffuseSignalDescType, _specularSignalDescType))
        return false;

    const ffxDispatchDescHeader* firstSignal = dispatchDesc.header.pNext;
    const ffxDispatchDescHeader* secondSignal = firstSignal->pNext;
    const ffxDispatchDescHeader* diffuseHeader =
        firstSignal->type == _diffuseSignalDescType ? firstSignal : secondSignal;
    const ffxDispatchDescHeader* specularHeader =
        firstSignal->type == _specularSignalDescType ? firstSignal : secondSignal;

    // All four RR 1.2 diffuse/specular descriptor structures have the same
    // header + signal ABI; these concrete types provide named signal access.
    const auto& directDiffuse =
        *reinterpret_cast<const ffxDispatchDescDenoiserDirectDiffuse*>(diffuseHeader);
    const auto& indirectSpecular =
        *reinterpret_cast<const ffxDispatchDescDenoiserIndirectSpecular*>(specularHeader);
    const bool resetRequested = !!(dispatchDesc.flags & FFX_DENOISER_DISPATCH_RESET);
    const bool resetTransition = resetRequested && !_lastDispatchRequestedReset;
    const bool logDispatchSnapshot = _logNextDenoiserDispatch || resetTransition;

    if (logDispatchSnapshot)
    {
        LogRRDispatchSnapshot(dispatchDesc, directDiffuse, indirectSpecular);
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
        LOG_INFO(
            "[RR_DIAG] conversion snapshot: viewSource={}, projectionSource={}, handedness={}, depthInput={}, "
            "depthDirection={}, motionResolution={}, roughness={}, roughnessFloor={:.4f}, "
            "roughnessFloorDistance={:.2f}, "
            "specularHitDistance={}, diffuseHitDistance={}, diffuseDirectionHitDistance={}",
            _viewFromStreamline ? "Streamline" : "NGX",
            _projectionFromStreamline ? "StreamlineReconstruction" : "NGX",
            _isRightHanded ? "RH" : "LH",
            s_isHWDepth ? "hardware" : "linear",
            DepthInverted() ? "reversed-Z" : "standard-Z",
            LowResMV() ? "render" : "output",
            s_isRoughnessPacked ? "packed" : "separate",
            _convDesc.RoughnessFloor,
            _convDesc.RoughnessFloorDistance,
            _convDesc.Resources.InSpecHitDist ? "present" : "absent",
            _diffuseHitDistanceProbe ? "present" : "absent",
            _diffuseRayDirectionHitDistanceProbe ? "present" : "absent");
    }

    const auto updateConfiguration = [this](const CustomOptional<float>& cfgValue, float& currentValue,
                                             FfxApiConfigureDenoiserKey key)
    {
        const float requestedValue = cfgValue.value_or_default();
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

    if (!updateConfiguration(cfg.FfxDenoiserDisocThreshold, _denoiserSettings.m_DisocclusionThreshold,
                             FFX_API_CONFIGURE_DENOISER_KEY_DISOCCLUSION_THRESHOLD) ||
        !updateConfiguration(cfg.FfxDenoiserCrossBlNormStr, _denoiserSettings.m_CrossBilateralNormalStrength,
                             FFX_API_CONFIGURE_DENOISER_KEY_CROSS_BILATERAL_NORMAL_STRENGTH) ||
        !updateConfiguration(cfg.FfxDenoiserStabilityBias, _denoiserSettings.m_StabilityBias,
                             FFX_API_CONFIGURE_DENOISER_KEY_STABILITY_BIAS) ||
        !updateConfiguration(cfg.FfxDenoiserMaxRadiance, _denoiserSettings.m_MaxRadiance,
                             FFX_API_CONFIGURE_DENOISER_KEY_MAX_RADIANCE) ||
        !updateConfiguration(cfg.FfxDenoiserRadianceClip, _denoiserSettings.m_RadianceClipStdK,
                             FFX_API_CONFIGURE_DENOISER_KEY_RADIANCE_CLIP_STD_K) ||
        !updateConfiguration(cfg.FfxDenoiserGaussKernRelax, _denoiserSettings.m_GaussianKernelRelaxation,
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
