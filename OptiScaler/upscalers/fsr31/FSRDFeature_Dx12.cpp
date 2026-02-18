#include "pch.h"
#include <nvsdk_ngx_defs_dlssd.h>
#include <DirectXMath.h>
#include "NVNGX_Parameter.h"
#include "FSRDFeature_Dx12.h"
#include "shaders/fsrd_input_conv/FSRDInputConv_Dx12.h"

using namespace DirectX;
using FSRDConvIn = FSRDInputConv_Dx12::InputResources;
using FSRDConvCfg = FSRDInputConv_Dx12::Constants;
using FSRDConvOut = FSRDInputConv_Dx12::OutputResources;

/**
 * @brief Retrieves a matrix from the given parameter table. Matrices used by DLSS are in column-major
 * order, but DirectXMath operations assume row-major. Appropriate for passing to DirectX shaders, but not for
 * CPU-side operations without transposing.
 */
static bool TryGetNGXMatrixTranspose(const NVSDK_NGX_Parameter& ngxParams, const char* key, DirectX::XMMATRIX& outValue)
{
    float* pMat = nullptr;

    if (ngxParams.Get(key, (void**) &pMat) == NVSDK_NGX_Result_Success && pMat != nullptr)
    {
        memcpy_s(&outValue, sizeof(DirectX::XMMATRIX), pMat, sizeof(float) * 16);
        return true;
    }
    else
        return false;
}

/**
 * @brief Retrieves a matrix from the given parameter table and transposes it for CPU-side
 * operations with DirectXMath.
 */
static bool TryGetNGXMatrix(const NVSDK_NGX_Parameter& ngxParams, const char* key, DirectX::XMMATRIX& outValue)
{
    if (TryGetNGXMatrixTranspose(ngxParams, key, outValue))
    {
        outValue = XMMatrixTranspose(outValue);
        return true;
    }
    else
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

/**
 * @brief Calculates vertical FOV according to: FOVv = 2 * arctan( 1 / M22 )
 * @param proj View to Clip / Perspective projection matrix
 * @return Vertical field of view in radians
 */
static float GetVertFovFromProjectionMatrixRad(const XMMATRIX& proj)
{ 
    return float(2.0 * ( std::atan(1.0 / (double)proj.r[1].m128_f32[1]) ));
}

/**
 * @brief Calculates horizontal FOV according to: FOVh = 2 * arctan( 1 / M11 )
 * @param proj View to Clip / Perspective projection matrix
 * @return Horizontal field of view in radians
 */
static float GetHorzFovFromProjectionMatrixRad(const XMMATRIX& proj)
{ 
    return float(2.0 * ( std::atan(1.0 / (double)proj.r[0].m128_f32[0]) ));
}

/**
 * @brief Calculates aspect ratio (width / height) as AR = M22 / M11
 * @param proj View to Clip / Perspective projection matrix
 * @return Aspect ratio as an fp32 decimal e.g. 1.778
 */
static float GetAspectRatioFromProjectionMatrix(const XMMATRIX& proj)
{
    return proj.r[1].m128_f32[1] / proj.r[0].m128_f32[0];
}

static XMFLOAT3 GetFloat3(const XMVECTOR& vec4) 
{
    XMFLOAT3 vec3= {};
    XMStoreFloat3(&vec3, vec4);
    return vec3;
}

static XMFLOAT3 GetFloat3Column(const XMMATRIX& mat, int col)
{
    return { mat.r[0].m128_f32[col], mat.r[1].m128_f32[col], mat.r[2].m128_f32[col] };
}

static FfxApiFloatCoords3D GetFfxFloat3Column(const XMMATRIX& mat, int col)
{
    return { mat.r[0].m128_f32[col], mat.r[1].m128_f32[col], mat.r[2].m128_f32[col] };
}

static FfxApiFloatCoords3D GetFfxFloat3(const XMVECTOR& vec4)
{
    FfxApiFloatCoords3D vec3 = {};
    XMStoreFloat3(reinterpret_cast<XMFLOAT3*>(&vec3), vec4);
    return vec3;
}

static FfxApiFloatCoords3D GetFfxFloat3(const XMFLOAT3& vec3)
{
    return { vec3.x, vec3.y, vec3.z };
}

struct ViewPlanes
{
    float nearPlane;
    float farPlane;
    bool isInfinite;
};

static ViewPlanes GetViewPlanes(const DirectX::XMMATRIX& projection, bool isInverted)
{
    ViewPlanes planes;
    float A = projection.r[2].m128_f32[2]; // M22
    float B = projection.r[2].m128_f32[3]; // M23
    float W = projection.r[3].m128_f32[2]; // M32 (Usually 1)

    float infiniteCheckVal = isInverted ? A : (A - W);
    planes.isInfinite = std::abs(infiniteCheckVal) < 1e-6f;

    if (isInverted)
    {
        // Inverted: Near is at D=1, Far is at D=0
        // 1 = A/W + B/(n*W) -> n = B / (W - A)
        planes.nearPlane = B / (W - A);

            // 0 = A/W + B/(f*W) -> f = -B / A
            planes.farPlane = -B / A;
    }
    else
    {
        // Standard: Near is at D=0, Far is at D=1
        // 0 = A/W + B/(n*W) -> n = -B / A
        planes.nearPlane = -B / A;

            // 1 = A/W + B/(f*W) -> f = B / (W - A)
            planes.farPlane = B / (W - A);
    }

    return planes;
}

FSRDFeatureDx12::FSRDFeatureDx12(uint32_t InHandleId, NVSDK_NGX_Parameter* InParameters) : 
    FSR31FeatureDx12(InHandleId, InParameters),
    IFeature(InHandleId, SetParameters(InParameters)),  
    _pDenoiserCtx(nullptr), 
    _denoiserCtxDesc({}),
    _denoiserSettings({}), 
    _isHWDepth(false), 
    _isRoughnessPacked(false), 
    _convConfig({})
{ }

FSRDFeatureDx12::~FSRDFeatureDx12() 
{
    if (State::Instance().isShuttingDown)
        return;

    if (_pDenoiserCtx != nullptr)
        FfxApiProxy::D3D12_DestroyContext(&_pDenoiserCtx, nullptr);
}

bool FSRDFeatureDx12::InitFSR3(const NVSDK_NGX_Parameter* InParameters)
{
    LOG_FUNC();

    // Init upscaler first - borrow some init boilerplate and some cfg
    if (FSR31FeatureDx12::InitFSR3(InParameters))
    {
        SetInit(false);

        LOG_DEBUG("FSR Ray Regeneration Initializing");
        _name = "FSR Ray Regeneration";

        // Create DLSS-RR to FSR-RR input converter
        FSRDConvShader = std::make_unique<FSRDInputConv_Dx12>("FSRD Converter", Device);

        if (!FSRDConvShader->IsInit())
            return false;

        if (!FSRDConvShader->SetMaxRenderSize(_upscaleCtxDesc.maxRenderSize.width, _upscaleCtxDesc.maxRenderSize.height))
            return false;

        // HW depth flag might not be needed. May be able to handle transparently in conv shader.
        if (int value; InParameters->Get(NVSDK_NGX_Parameter_Use_HW_Depth, &value) == NVSDK_NGX_Result_Success)
            _isHWDepth = value == NVSDK_NGX_DLSS_Depth_Type_HW;
        else
            _isHWDepth = false;

        if (int value; InParameters->Get(NVSDK_NGX_Parameter_DLSS_Roughness_Mode, &value) == NVSDK_NGX_Result_Success)
            _isRoughnessPacked = value == NVSDK_NGX_DLSS_Roughness_Mode_Packed;
        else
            _isRoughnessPacked = false;

        LOG_INFO("DLSSD Flags HWDepth: {} - IsRoughnessPacked: {}", _isHWDepth, _isRoughnessPacked);

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
    const auto& state = State::Instance();
    const auto& cfg = *Config::Instance();

    if (!QueryDenoiserVersions())
        return false;

    ffxOverrideVersion vidOverride = 
    {
        .header = { .type = FFX_API_DESC_TYPE_OVERRIDE_VERSION },
        .versionId = state.ffxDenoiserVersionIds[cfg.FfxDenoiserIndex.value_or_default()]
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
    // Chain: ContextDesc -> BackendDesc -> OverrideVersion
    // Composited radiance with fused albedo without a dominant light source
    _denoiserCtxDesc = 
    {
        .header = 
        { 
            .type = FFX_API_CREATE_CONTEXT_DESC_TYPE_DENOISER,
            // Chain backend desc into context desc
            .pNext = &backendDesc.header
        },
        .version = FFX_DENOISER_VERSION,
        .maxRenderSize = _upscaleCtxDesc.maxRenderSize,       
        .mode = FFX_DENOISER_MODE_1_SIGNAL,
        .flags = 0
    };

#ifdef _DEBUG
    LOG_INFO("Debug checking enabled for denoiser!");
    _denoiserCtxDesc.flags |= FFX_DENOISER_ENABLE_DEBUGGING;
#endif

    // Create the denoiser context
    {   
        ScopedSkipHeapCapture skipHeapCapture {};
        auto ret = FfxApiProxy::D3D12_CreateContext(&_pDenoiserCtx, &_denoiserCtxDesc.header, NULL);

        if (ret != FFX_API_RETURN_OK)
        {
            LOG_ERROR("_denoiserCtx error: {0}", FfxApiProxy::ReturnCodeToString(ret));
            return false;
        }
    }

    // Query default settings
    ffxQueryDescDenoiserGetDefaultSettings queryDefaultSettingsDesc = 
    {
        .header = { .type = FFX_API_QUERY_DESC_TYPE_DENOISER_GET_DEFAULT_SETTINGS },
        .device = Device,
        .defaultSettings = &_denoiserSettings
    };
    FfxApiProxy::D3D12_Query(nullptr, &queryDefaultSettingsDesc.header);

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
    FfxApiProxy::D3D12_Query(nullptr, &queryVersionsDesc.header);

    state.ffxDenoiserVersionIds.resize(versionCount);
    state.ffxDenoiserVersionNames.resize(versionCount);

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
    FfxApiProxy::D3D12_Query(nullptr, &queryVersionsDesc.header);

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

    // Validate helper features
    if (!RCAS->IsInit()) cfg.RcasEnabled.set_volatile_value(false);
    if (!OutputScaler->IsInit()) cfg.OutputScalingEnabled.set_volatile_value(false);

    _isInReset = false;
    
    if (uint32_t value = 0; inParams.Get(NVSDK_NGX_Parameter_Reset, &value) == NVSDK_NGX_Result_Success)
        _isInReset = value > 0;

    // Denoiser start
    ffxDispatchDescDenoiserInput1Signal signalDesc = {};
    ffxDispatchDescDenoiser denoiserDesc = {};
    bool isDenoiserReady = false;

    // Pull configuration and input buffers for DLSS-RR from the param table, convert and 
    // repack input buffers into intermediate FSR-RR input buffers, and configure descriptors.
    if (PrepareDenoiserInput(InCommandList, *InParameters, denoiserDesc, signalDesc))
    {
        // Dispatch denoiser
        if (!DispatchDenoiser(InCommandList, denoiserDesc)) // [TODO] Add bypass option
            return false;

        // Upscale prep
        // Transition overwritten input color back to SRV
        ID3D12Resource* const pInColor = static_cast<ID3D12Resource*>(signalDesc.radiance.output.resource);
        ResourceBarrier(InCommandList, pInColor, 
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        isDenoiserReady = true;
    }
    else
    {
        LOG_ERROR("Denoiser not ready");
    }

    // Upscaler start
    ffxDispatchDescUpscale upscalerDesc = {};

    if (PrepareUpscalerInput(InCommandList, inParams, upscalerDesc))
    {
        // Override upscaler config
        if (isDenoiserReady)
        {
            upscalerDesc.depth = denoiserDesc.linearDepth;
            upscalerDesc.cameraNear = denoiserDesc.cameraNear;
            upscalerDesc.cameraFar = denoiserDesc.cameraFar;
        }

        // Sets optional, configurable resource barriers
        FSR31FeatureDx12::SetConfigurableBarriers(InCommandList);

        if (!DispatchUpscaler(InCommandList, upscalerDesc))
            return false;

        // Post-Process
        PostProcess(InCommandList, inParams);

        // Cleanup
        FSR31FeatureDx12::ResetConfigurableBarriers(InCommandList);
    }
    else
        return false;

    _frameCount++;
    return true;
}

bool FSRDFeatureDx12::PrepareDenoiserInput(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& inParams,
    ffxDispatchDescDenoiser& dispatchDesc, ffxDispatchDescDenoiserInput1Signal& signalDesc)
{
    auto& state = State::Instance();
    auto& cfg = *Config::Instance();

    // Gather DLSS-RR input buffers for conversion and repacking for FSR-RR
    FSRDConvIn convInputs = {};

    if (!PrepareDenoiseConvInput(inParams, convInputs))
        return false;    
    
    FSRDConvOut fsrdData = {};
    
    if (!ConvertDenoiserBuffers(InCommandList, convInputs, fsrdData))
        return false;

    // The denoiser will write to the original color input, which will be consumed by FSR SR.
    // This needs to be transitioned back to SRV after the denoiser dispatch.
    ResourceBarrier(InCommandList, convInputs.InColor, 
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);

    // Camera matrix - translation and rotation, from viewMatrix^-1
    const XMFLOAT3 camPos = GetFloat3Column(_invViewMatrix, 3);

    // Pack dispatch configuration
    signalDesc = 
    {
        .header = { .type = FFX_API_DISPATCH_DESC_INPUT_1_SIGNAL_TYPE_DENOISER },
        .radiance = 
        {
            .input = ffxApiGetResourceDX12(fsrdData.OutRadiance, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
            // Configure FSR-RR to overwrite original input with denoised output
            .output = ffxApiGetResourceDX12(convInputs.InColor, FFX_API_RESOURCE_STATE_UNORDERED_ACCESS),
        },
        .fusedAlbedo = ffxApiGetResourceDX12(fsrdData.OutFusedAlbedo, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ)
    };

    dispatchDesc = 
    {
        .header = 
        { 
            .type = FFX_API_DISPATCH_DESC_TYPE_DENOISER,
            .pNext = &signalDesc.header // Link signal desc to main header
        },
        .commandList = InCommandList,
        .linearDepth = ffxApiGetResourceDX12(fsrdData.OutLinearDepth, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
        .motionVectors = ffxApiGetResourceDX12(fsrdData.OutMotion, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
        .normals = ffxApiGetResourceDX12(fsrdData.OutNormals, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
        .specularAlbedo = ffxApiGetResourceDX12(fsrdData.OutSpecAlbedo, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
        .diffuseAlbedo = ffxApiGetResourceDX12(fsrdData.OutDiffAlbedo, FFX_API_RESOURCE_STATE_PIXEL_COMPUTE_READ),
        // Exactly the same name as the FSR scaling value. Completely different meaning.
        .motionVectorScale = {. x = 1.0f, .y = 1.0f },
        // Camera movement since last frame (PreviousPosition - CurrentPosition)
        .cameraPositionDelta = { (_lastCamPos.x - camPos.x), (_lastCamPos.y - camPos.y), (_lastCamPos.z - camPos.z) },
        .cameraRight = GetFfxFloat3Column(_invViewMatrix, 0),
        .cameraUp = GetFfxFloat3Column(_invViewMatrix, 1),
        .cameraForward = GetFfxFloat3Column(_invViewMatrix, 2),
        .cameraAspectRatio = GetAspectRatioFromProjectionMatrix(_projMatrix),
        .cameraNear = _convConfig.NearPlane,
        .cameraFar = _convConfig.FarPlane,
        .cameraFovAngleVertical = GetVertFovFromProjectionMatrixRad(_projMatrix),
        .renderSize = { RenderWidth(), RenderHeight() },   
        .frameIndex = (uint32_t)_frameCount,
        .flags = FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO
    };

    dispatchDesc.flags |= _isInReset & FFX_DENOISER_DISPATCH_RESET;

    // Update camera position for next frame
    _lastCamPos = camPos;

    if (!TryGetToggleableNGXParam(inParams, OptiKeys::FSR_FrameTimeDelta, cfg.FsrUseFsrInputValues, dispatchDesc.deltaTime))
    {
        if (inParams.Get(NVSDK_NGX_Parameter_FrameTimeDeltaInMsec, &dispatchDesc.deltaTime) !=
                NVSDK_NGX_Result_Success || dispatchDesc.deltaTime < 1.0f)
        {
            dispatchDesc.deltaTime = (float)GetDeltaTime();
    }
    }

    float jitterX = 0.0f, jitterY = 0.0f;
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_X, &jitterX);
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_Y, &jitterY);

    // Convert from pixel to NDC jitter
    dispatchDesc.jitterOffsets.x = 2.0f * (jitterX / (float)RenderWidth());
    dispatchDesc.jitterOffsets.y = -2.0f * (jitterY / (float) RenderHeight());

    LOG_DEBUG("Jitter NDC [{:.6f}, {:.6f}]", dispatchDesc.jitterOffsets.x, dispatchDesc.jitterOffsets.y);


    return true;
}

bool FSRDFeatureDx12::PrepareDenoiseConvInput(const NVSDK_NGX_Parameter& inParams, FSRDConvIn& convInputs)
{
    // Gather DLSS-RR input buffers for conversion and repacking for FSR-RR
    convInputs = {};

    bool isReady = true;

    // Standard TSR buffers
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Color, convInputs.InColor))
        isReady = false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_MotionVectors, convInputs.InMotionVectors))
        isReady = false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Depth, convInputs.InDepth) && LowResMV())
        isReady = false;

    // DLSSD-specific buffers
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_GBuffer_Normals, convInputs.InNormals))
        isReady = false;

    // If roughness is not packed into normals, then this texture is mandatory.
    // This value should be available in one of these two buffers in any DLSS-RR implementation.
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_GBuffer_Roughness, convInputs.InRoughness) &&
        !_isRoughnessPacked)
    {
        LOG_WARN("Expected unpacked roughness buffer from DLSS-RR. Defaulting to packed roughness.");
        _isRoughnessPacked = true;
    }

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_DiffuseAlbedo, convInputs.InDiffAlbedo))
        isReady = false;

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_SpecularAlbedo, convInputs.InSpecAlbedo))
        isReady = false;

    // [LIMITATION] Specular hit distance and the following two matrices are mandatory for FSR-RR, but optional for
    // DLSS-RR. DLSS-RR allows these values to be substituted for Specular Motion Vectors, which FSR-RR cannot use. It
    // may be worth inspecting the Streamline inputs if these values aren't available here.
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance, convInputs.InSpecHitDist))
        isReady = false;
    
    // Get DLSSD matrices and derive related values
    // World to view/camera space (V)
    _prevViewMatrix = _viewMatrix;
    _viewMatrix = {};

    if (!TryGetNGXMatrix(inParams, NVSDK_NGX_Parameter_DLSS_WORLD_TO_VIEW_MATRIX, _viewMatrix))
    {
        LOG_ERROR("View matrix missing!");
        isReady = false;
    }    

    // Perspective projection matrix (P)
    _projMatrix = {};

    if (!TryGetNGXMatrix(inParams, NVSDK_NGX_Parameter_DLSS_VIEW_TO_CLIP_MATRIX, _projMatrix))
    {
        LOG_ERROR("Projection matrix missing!");
        isReady = false;
    }

    // Camera rotation and position
    _invViewMatrix = XMMatrixInverse(nullptr, _viewMatrix);

    return isReady;
}

bool FSRDFeatureDx12::ConvertDenoiserBuffers(ID3D12GraphicsCommandList* InCommandList, 
    const FSRDConvIn& convInputs, FSRDConvOut& convOut)
{
    // Prepare input converter
    _convConfig = 
    {
        .RenderSize = { (float)RenderWidth(), (float)RenderHeight() },
        .RenderSizeInv = { 1.0f / (float)RenderWidth(), 1.0f / (float)RenderHeight() },
        .UseSqrtEncodingOnSecondaries = false, // Non-HDR albedo/specular secondaries e.g. RGBA32
        .IsRoughnessPacked = float(_isRoughnessPacked)
    };
    
    // Store in column major order for GPU
    XMStoreFloat4x4(&_convConfig.InvViewMatrix, XMMatrixTranspose(_invViewMatrix));

    // Inverse perspective projection
    const XMMATRIX invProjMatrix = XMMatrixInverse(nullptr, _projMatrix);
    XMStoreFloat4x4(&_convConfig.InvProjMatrix, XMMatrixTranspose(invProjMatrix));

    // View-Projection (V*P) matrix
    const XMMATRIX viewProjMatrix = XMMatrixMultiply(_viewMatrix, _projMatrix);

    // (V*P)^-1
    const XMMATRIX invViewProjMatrix = XMMatrixInverse(nullptr, viewProjMatrix);
    XMStoreFloat4x4(&_convConfig.InvViewProjMatrix, XMMatrixTranspose(invViewProjMatrix));

    // Previous world to view for linear depth delta
    XMStoreFloat4x4(&_convConfig.PrevViewMatrix, XMMatrixTranspose(_prevViewMatrix));

    // Near and far planes
    const ViewPlanes planes = GetViewPlanes(_projMatrix, DepthInverted());
    _convConfig.NearPlane = planes.nearPlane;
    _convConfig.FarPlane = planes.farPlane;
    _convConfig.UseInfiniteFarPlane = planes.isInfinite;

    LOG_DEBUG("Distpaching FSRD Input Converter");

    // Dispatch resource converter. Outputs are automatically transitioned for reading.
    if (!FSRDConvShader->Dispatch(InCommandList, convInputs, _convConfig))
        return false;

    // Set FSR-RR input texture pointers
    convOut = FSRDConvShader->GetOutputs();

    return true;
}

static void TryUpdateOption(const CustomOptional<float>& cfgValue, float& currentValue, bool& wasUpdated) 
{
    if (cfgValue.value_or_default() != currentValue)
    {
        currentValue = cfgValue.value_or_default();
        wasUpdated = true;
    }
    }

bool FSRDFeatureDx12::DispatchDenoiser(ID3D12GraphicsCommandList* InCommandList, const ffxDispatchDescDenoiser& dispatchDesc)
{
    auto& state = State::Instance();
    const auto& cfg = *Config::Instance();
    bool cfgChanged = false;

    TryUpdateOption(cfg.FfxDenoiserHistRejection, _denoiserSettings.historyRejectionStrength, cfgChanged);
    TryUpdateOption(cfg.FfxDenoiserCrossBlNormStr, _denoiserSettings.crossBilateralNormalStrength, cfgChanged);
    TryUpdateOption(cfg.FfxDenoiserStabilityBias, _denoiserSettings.stabilityBias, cfgChanged);
    TryUpdateOption(cfg.FfxDenoiserMaxRadiance, _denoiserSettings.maxRadiance, cfgChanged);
    TryUpdateOption(cfg.FfxDenoiserRadianceClip, _denoiserSettings.radianceClipStdK, cfgChanged);
    TryUpdateOption(cfg.FfxDenoiserGaussKernRelax, _denoiserSettings.gaussianKernelRelaxation, cfgChanged);

    if (cfgChanged)
    {
    ffxConfigureDescDenoiserSettings cfgDesc = 
    {
        .header = { .type = FFX_API_CONFIGURE_DESC_TYPE_DENOISER_SETTINGS },
        .settings = _denoiserSettings
    };
    FfxApiProxy::D3D12_Configure(&_pDenoiserCtx, &cfgDesc.header);
    }

    LOG_DEBUG("Dispatching FSR-RR...");
    const ffxReturnCode_t result = FfxApiProxy::D3D12_Dispatch(&_pDenoiserCtx, &dispatchDesc.header);

    if (result != FFX_API_RETURN_OK)
    {
        LOG_ERROR("_dispatch error: {0}", FfxApiProxy::ReturnCodeToString(result));

        if (result == FFX_API_RETURN_ERROR_RUNTIME_ERROR)
        {
            LOG_WARN("Trying to recover by recreating the feature");
            state.changeBackend[Handle()->Id] = true;
        }

        return false;
    }

    return true;
}