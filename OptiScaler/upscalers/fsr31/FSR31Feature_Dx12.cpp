#include <pch.h>
#include <Config.h>
#include <Util.h>
#include <proxies/FfxApi_Proxy.h>
#include "FSR31Feature_Dx12.h"
#include "NVNGX_Parameter.h"
#include "MathUtils.h"

using namespace OptiMath;

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

static void SetFfxUpscaleKeyValue(ffxContext* ctx, float& currentValue, const CustomOptional<float>& newValue,
                                        uint64_t key, const char* featureName)
{
    const float val = newValue.value_or_default();

    if (currentValue != val)
    {
        currentValue = val;

        ffxConfigureDescUpscaleKeyValue config {};
        config.header.type = FFX_API_CONFIGURE_DESC_TYPE_UPSCALE_KEYVALUE;
        config.key = key;
        config.ptr = &currentValue;

        const ffxReturnCode_t result = FfxApiProxy::D3D12_Configure(ctx, &config.header);

        if (result != FFX_API_RETURN_OK)
            LOG_WARN("{} configure result: {}", featureName, (UINT) result);
    }
}

NVSDK_NGX_Parameter* FSR31FeatureDx12::SetParameters(NVSDK_NGX_Parameter* InParameters)
{
    InParameters->Set("OptiScaler.SupportsUpscaleSize", true);
    return InParameters;
}

FSR31FeatureDx12::FSR31FeatureDx12(unsigned int InHandleId, NVSDK_NGX_Parameter* InParameters)
    : FSR31Feature(InHandleId, InParameters), IFeature_Dx12(InHandleId, InParameters),
      IFeature(InHandleId, SetParameters(InParameters))
{
    InParameters->Set("OptiScaler.SupportsUpscaleSize", true);

    // Initialize FFX API
    FfxApiProxy::InitFfxDx12();
    _moduleLoaded = FfxApiProxy::IsSRReady();

    if (_moduleLoaded)
        LOG_INFO("amd_fidelityfx_dx12.dll methods loaded!");
    else
        LOG_ERROR("can't load amd_fidelityfx_dx12.dll methods!");
}

inline FSR31FeatureDx12::~FSR31FeatureDx12()
{
    if (State::Instance().isShuttingDown)
        return;

    if (_upscaleCtx != nullptr)
        FfxApiProxy::D3D12_DestroyContext(&_upscaleCtx, NULL);
}

bool FSR31FeatureDx12::Init(ID3D12Device* InDevice, ID3D12GraphicsCommandList* InCommandList,
                            NVSDK_NGX_Parameter* InParameters)
{
    LOG_DEBUG("FSR31FeatureDx12::Init");

    if (IsInited())
        return true;

    Device = InDevice;

    // Attempt to create the FSR context
    if (InitFSR3(InParameters))
    {
        // Initialize ImGui if not already disabled/created
        if (!Config::Instance()->OverlayMenu.value_or_default() && (Imgui == nullptr || Imgui.get() == nullptr))
            Imgui = std::make_unique<Menu_Dx12>(Util::GetProcessWindow(), InDevice);

        // OutputScaler: Handles resizing if FSR's internal upscaling isn't used or for custom scaling
        OutputScaler = std::make_unique<OS_Dx12>("Output Scaling", InDevice, (TargetWidth() < DisplayWidth()));

        // RCAS: Robust Contrast Adaptive Sharpening
        RCAS = std::make_unique<RCAS_Dx12>("RCAS", InDevice);

        // Bias: Handles DLSS bias -> reactive mask conversion, if enabled
        Bias = std::make_unique<Bias_Dx12>("Bias", InDevice);

        return true;
    }

    return false;
}

bool FSR31FeatureDx12::InitFSR3(const NVSDK_NGX_Parameter* InParameters)
{
    LOG_FUNC();

    if (!ModuleLoaded())
        return false;

    if (IsInited())
        return true;

    if (Device == nullptr)
    {
        LOG_ERROR("D3D12Device is null!");
        return false;
    }

    {
        ScopedSkipSpoofing skipSpoofing {};
        const auto& ngxParams = *InParameters;
        auto& state = State::Instance();
        auto& cfg = *Config::Instance();

        // Context description
        SetInitFlags(ngxParams);
        GetResolutionConfig();

        ffxCreateContextDescUpscaleVersion contextVersion = 
        {
            .header = { .type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE_VERSION },
            .version = FFX_UPSCALER_VERSION
        };

        // Backend desc
        ffxCreateBackendDX12Desc backendDesc = 
        { 
            .header = { .type = FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12 },
            .device = Device
        };

        // Chain: Context -> Version -> Backend
        _upscaleCtxDesc.header.pNext = &contextVersion.header;
        contextVersion.header.pNext = &backendDesc.header;

        // Set FSR version override
        QueryVersions();

        ffxOverrideVersion vidOverride = { 0 };
        vidOverride.header.type = FFX_API_DESC_TYPE_OVERRIDE_VERSION;
        vidOverride.versionId = GetVersionOverrideID();

        // Chain: Backend -> Override
        backendDesc.header.pNext = &vidOverride.header;

        LOG_DEBUG("_upscaleCtx!");

        {
            ScopedSkipHeapCapture skipHeapCapture {};

            // Final Context Creation
            auto ret = FfxApiProxy::D3D12_CreateContext(&_upscaleCtx, &_upscaleCtxDesc.header, NULL);

            if (ret != FFX_API_RETURN_OK)
            {
                LOG_ERROR("_upscaleCtx error: {0}", FfxApiProxy::ReturnCodeToString(ret));
                return false;
            }
        }

        // Update version info for UI/Logging
        auto version = state.ffxUpscalerVersionNames[cfg.FfxUpscalerIndex.value_or_default()];
        _name = "FSR";
        parse_version(version);
    }

    SetInit(true);

    return true;
}

void FSR31FeatureDx12::SetInitFlags(const NVSDK_NGX_Parameter& ngxParams) 
{
    auto& cfg = *Config::Instance();

    // Init context descriptor
    _upscaleCtxDesc.header.type = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    _upscaleCtxDesc.flags = 0;

#ifdef _DEBUG
    LOG_INFO("Debug checking enabled!");
    _upscaleCtxDesc.fpMessage = FfxLogCallback;
    _upscaleCtxDesc.flags |= FFX_UPSCALE_ENABLE_DEBUG_CHECKING;
#endif

    // [TODO] ADD FFX_UPSCALE_ENABLE_DEPTH_INFINITE

    // Map NGX flags to FFX context flags
    if (DepthInverted())
        _upscaleCtxDesc.flags |= FFX_UPSCALE_ENABLE_DEPTH_INVERTED;

    if (AutoExposure())
        _upscaleCtxDesc.flags |= FFX_UPSCALE_ENABLE_AUTO_EXPOSURE;

    if (IsHdr())
        _upscaleCtxDesc.flags |= FFX_UPSCALE_ENABLE_HIGH_DYNAMIC_RANGE;

    if (JitteredMV())
        _upscaleCtxDesc.flags |= FFX_UPSCALE_ENABLE_MOTION_VECTORS_JITTER_CANCELLATION;

    if (!LowResMV())
        _upscaleCtxDesc.flags |= FFX_UPSCALE_ENABLE_DISPLAY_RESOLUTION_MOTION_VECTORS;

    // Configurable flags (User overrides)
    if (cfg.FsrNonLinearColorSpace.value_or_default())
    {
        _upscaleCtxDesc.flags |= FFX_UPSCALE_ENABLE_NON_LINEAR_COLORSPACE;
        LOG_INFO("contextDesc.initFlags (NonLinearColorSpace) {0:b}", _upscaleCtxDesc.flags);
    }

    if (cfg.Fsr4EnableDebugView.value_or_default())
    {
        LOG_INFO("Debug view enabled!");
        _contextDesc.flags |= 512; // FFX_UPSCALE_ENABLE_DEBUG_VISUALIZATION;
    }
}

void FSR31FeatureDx12::GetResolutionConfig() 
{
    auto& cfg = *Config::Instance();

    // Handle Output Scaling Multiplier (Manual resizing of the output)
    if (cfg.OutputScalingEnabled.value_or_default() && LowResMV())
    {
        const float ssMulti = std::clamp(cfg.OutputScalingMultiplier.value_or_default(), 0.5f, 3.0f);
        cfg.OutputScalingMultiplier.set_volatile_value(ssMulti);

        _targetWidth = static_cast<uint32_t>(DisplayWidth() * ssMulti);
        _targetHeight = static_cast<uint32_t>(DisplayHeight() * ssMulti);
    }
    else
    {
        _targetWidth = DisplayWidth();
        _targetHeight = DisplayHeight();
    }

    // Extended limits: Support rendering at higher than display resolution
    if (cfg.ExtendedLimits.value_or_default() && RenderWidth() > DisplayWidth())
    {
        _upscaleCtxDesc.maxRenderSize.width = RenderWidth();
        _upscaleCtxDesc.maxRenderSize.height = RenderHeight();

        cfg.OutputScalingMultiplier.set_volatile_value(1.0f);

        // If output scaling active, let it handle downsampling
        if (cfg.OutputScalingEnabled.value_or_default() && LowResMV())
        {
            _upscaleCtxDesc.maxUpscaleSize.width = _upscaleCtxDesc.maxRenderSize.width;
            _upscaleCtxDesc.maxUpscaleSize.height = _upscaleCtxDesc.maxRenderSize.height;

            // update target res
            _targetWidth = _upscaleCtxDesc.maxRenderSize.width;
            _targetHeight = _upscaleCtxDesc.maxRenderSize.height;
        }
        else
        {
            _upscaleCtxDesc.maxUpscaleSize.width = DisplayWidth();
            _upscaleCtxDesc.maxUpscaleSize.height = DisplayHeight();
        }
    }
    else
    {
        _upscaleCtxDesc.maxRenderSize.width = TargetWidth() > DisplayWidth() ? TargetWidth() : DisplayWidth();
        _upscaleCtxDesc.maxRenderSize.height = TargetHeight() > DisplayHeight() ? TargetHeight() : DisplayHeight();
        _upscaleCtxDesc.maxUpscaleSize.width = TargetWidth();
        _upscaleCtxDesc.maxUpscaleSize.height = TargetHeight();
    }
}

void FSR31FeatureDx12::QueryVersions()
{
    auto& state = State::Instance();

    // Get available FSR versions from the proxy
    ffxQueryDescGetVersions versionQuery {};
    versionQuery.header.type = FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
    versionQuery.createDescType = FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
    versionQuery.device = Device; // only for DirectX 12 applications

    // Get number of versions for allocation
    uint64_t versionCount = 0;
    versionQuery.outputCount = &versionCount;

    FfxApiProxy::D3D12_Query(nullptr, &versionQuery.header);

    // Store available FSR version IDs and names in vectors
    state.ffxUpscalerVersionIds.resize(versionCount);
    state.ffxUpscalerVersionNames.resize(versionCount);
    versionQuery.versionIds = state.ffxUpscalerVersionIds.data();
    versionQuery.versionNames = state.ffxUpscalerVersionNames.data();
    FfxApiProxy::D3D12_Query(nullptr, &versionQuery.header);
}

uint64_t FSR31FeatureDx12::GetVersionOverrideID()
{
    auto& state = State::Instance();
    auto& cfg = *Config::Instance();

    // Select specific FSR version based on user config index
    if (cfg.FfxUpscalerIndex.value_or_default() < 0 ||
        cfg.FfxUpscalerIndex.value_or_default() >= state.ffxUpscalerVersionIds.size())
        cfg.FfxUpscalerIndex.set_volatile_value(0);

    return state.ffxUpscalerVersionIds[cfg.FfxUpscalerIndex.value_or_default()];
}

bool FSR31FeatureDx12::Evaluate(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters)
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

    // Resource Gathering
    FSRInputResourcesDx12 inputs = {};
    ID3D12Resource* mainOutput = nullptr;

    if (!PrepareInputs(inParams, InCommandList, inputs)) 
        return false;

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Output, mainOutput)) 
        return false;

    // Resolve Output Chain (Main -> Scaler -> RCAS)
    // Track the resource FSR writes into
    const bool useSuperScaling = cfg.OutputScalingEnabled.value_or_default() && LowResMV();
    const bool isSharpeningEnabled = cfg.RcasEnabled.value_or_default() && 
        (_sharpness > 0.0f || (cfg.MotionSharpnessEnabled.value_or_default() && cfg.MotionSharpness.value_or_default() > 0.0f));

    ID3D12Resource* fsrOutput = mainOutput;

    // If super scaling, swap in OutputScaler buffer
    if (useSuperScaling)
    {
        if (OutputScaler->CreateBufferResource(Device, mainOutput, TargetWidth(), TargetHeight(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS))
        {
            OutputScaler->SetBufferState(InCommandList, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            fsrOutput = OutputScaler->Buffer();
        }
    }

    // If RCAS is enabled, swap in RCAS buffer (chains with SS if both are enabled)
    if (isSharpeningEnabled && RCAS->IsInit())
    {
        if (RCAS->CreateBufferResource(Device, fsrOutput, D3D12_RESOURCE_STATE_UNORDERED_ACCESS))
        {
            RCAS->SetBufferState(InCommandList, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            fsrOutput = RCAS->Buffer();
        }
    }

    // Barrier Management
    // 
    // Handle UE Quirks
    if (state.NVNGX_Engine == NVSDK_NGX_ENGINE_TYPE_UNREAL || state.gameQuirks & GameQuirk::ForceUnrealEngine)
    {
        if (!cfg.ColorResourceBarrier.has_value()) 
            cfg.ColorResourceBarrier.set_volatile_value(D3D12_RESOURCE_STATE_RENDER_TARGET);

        if (!cfg.MVResourceBarrier.has_value()) 
            cfg.MVResourceBarrier.set_volatile_value(D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    }

    // Transition FSR inputs to SRVs for reading
    TryResourceBarrier(InCommandList, inputs.Color, cfg.ColorResourceBarrier, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    TryResourceBarrier(InCommandList, inputs.MotionVectors, cfg.MVResourceBarrier, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    TryResourceBarrier(InCommandList, inputs.Depth, cfg.DepthResourceBarrier, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    
    if (inputs.ExposureMap && !AutoExposure())
        TryResourceBarrier(InCommandList, inputs.ExposureMap, cfg.ExposureResourceBarrier, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    // Transition output to UAV for writing
    TryResourceBarrier(InCommandList, mainOutput, cfg.OutputResourceBarrier, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);

    // Map inputs to descriptor
    if (!DispatchFSR(InCommandList, inParams, inputs, fsrOutput))
        return false;

    // Post-Process
    PostProcess(inParams, useSuperScaling, InCommandList, inputs.MotionVectors, fsrOutput, mainOutput);

    // Cleanup
    // 
    // Restore Barriers
    TryResourceBarrier(InCommandList, inputs.Color, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, cfg.ColorResourceBarrier);
    TryResourceBarrier(InCommandList, inputs.MotionVectors, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, cfg.MVResourceBarrier);
    TryResourceBarrier(InCommandList, inputs.Depth, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, cfg.DepthResourceBarrier);
    TryResourceBarrier(InCommandList, mainOutput, D3D12_RESOURCE_STATE_UNORDERED_ACCESS, cfg.OutputResourceBarrier);
    
    if (inputs.ExposureMap)
        TryResourceBarrier(InCommandList, inputs.ExposureMap, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, cfg.ExposureResourceBarrier);
        
    // Note: The original code only restored the reactive mask if it was the fallback dlss mask, 
    // but generally restoring the native mask state is safer if we transitioned it.
    // Assuming original behavior for now:
    TryResourceBarrier(InCommandList, inputs.ReactiveMask, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, cfg.MaskResourceBarrier);

    if (inputs.DlssBiasMaskFallback) // Restore fallback if it was used
         TryResourceBarrier(InCommandList, inputs.DlssBiasMaskFallback, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, cfg.MaskResourceBarrier);

    _frameCount++;

    return true;
}

bool FSR31FeatureDx12::PrepareInputs(const NVSDK_NGX_Parameter& inParams, ID3D12GraphicsCommandList* InCommandList,
                                     FSRInputResourcesDx12& inputs)
{
    auto& state = State::Instance();
    auto& cfg = *Config::Instance();

    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Color, inputs.Color))
        return false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_MotionVectors, inputs.MotionVectors))
        return false;
    if (!TryGetLoggedResource(inParams, NVSDK_NGX_Parameter_Depth, inputs.Depth) && LowResMV())
        return false;

    // Optional Resources
    TryGetNGXVoidPointer(inParams, OptiKeys::FSR_TransparencyAndComp, inputs.TransparencyMask);
    TryGetNGXVoidPointer(inParams, OptiKeys::FSR_Reactive, inputs.ReactiveMask);
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask, inputs.DlssBiasMaskFallback);
    TryGetNGXVoidPointer(inParams, NVSDK_NGX_Parameter_ExposureTexture, inputs.ExposureMap);

    // If not AutoExposure, we must have an exposure texture. If missing, force AutoExposure reset.
    if (!AutoExposure() && !inputs.ExposureMap)
    {
        LOG_DEBUG("AutoExposure disabled but ExposureTexture is missing. Forcing AutoExposure and re-initializing.");
        state.AutoExposure = true;
        state.changeBackend[Handle()->Id] = true;
        return true;
    }

    // Resolve Reactive & Transparency Masks
    GetReactiveAndTransparencyMasks(InCommandList, inputs);

    return true;
}

void FSR31FeatureDx12::GetReactiveAndTransparencyMasks(ID3D12GraphicsCommandList* InCommandList, FSRInputResourcesDx12& inputs)
{
    auto& cfg = *Config::Instance();
    ID3D12Resource* activeReactiveMask = nullptr;
    ID3D12Resource* activeTransparencyMask = nullptr;

    if (!cfg.DisableReactiveMask.value_or(inputs.ReactiveMask == nullptr && inputs.DlssBiasMaskFallback == nullptr))
    {
        // 1. Prefer explicit FSR masks
        if (inputs.TransparencyMask)
            activeTransparencyMask = inputs.TransparencyMask;
        if (inputs.ReactiveMask)
            activeReactiveMask = inputs.ReactiveMask;

        // 2. Fallback to DLSS Bias mask if FSR reactive is missing
        if (!activeReactiveMask && inputs.DlssBiasMaskFallback)
        {
            LOG_DEBUG("Using DLSS Input Bias mask as fallback...");
            cfg.DisableReactiveMask.set_volatile_value(false);

            // Transition Bias mask for reading
            TryResourceBarrier(InCommandList, inputs.DlssBiasMaskFallback, cfg.MaskResourceBarrier,
                               D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

            // Handle Bias generation (Compute Shader)
            if (cfg.DlssReactiveMaskBias.value_or_default() > 0.0f && Bias->IsInit() && Bias->CanRender())
            {
                if (Bias->CreateBufferResource(Device, inputs.DlssBiasMaskFallback,
                                               D3D12_RESOURCE_STATE_UNORDERED_ACCESS))
                {
                    Bias->SetBufferState(InCommandList, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);

                    if (Bias->Dispatch(Device, InCommandList, inputs.DlssBiasMaskFallback,
                                       cfg.DlssReactiveMaskBias.value_or_default(), Bias->Buffer()))
                    {
                        Bias->SetBufferState(InCommandList, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
                        activeReactiveMask = Bias->Buffer(); // Use the processed bias buffer
                    }
                    else
                    {
                        LOG_DEBUG("Skipping reactive mask, Bias: {0}, Bias Init: {1}, Bias CanRender: {2}",
                                  cfg.DlssReactiveMaskBias.value_or_default(), Bias->IsInit(), Bias->CanRender());
                    }
                }
            }

            // Use DLSS mask for Transparency if FSR Transparency is missing and config allows
            if (!activeTransparencyMask && cfg.FsrUseMaskForTransparency.value_or_default())
                activeTransparencyMask = inputs.DlssBiasMaskFallback;
        }
    }

    inputs.TransparencyMask = activeTransparencyMask;
    inputs.ReactiveMask = activeReactiveMask;
}

bool FSR31FeatureDx12::DispatchFSR(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& inParams,
                                   const FSRInputResourcesDx12& inputs, ID3D12Resource* dstTex)
{
    auto& state = State::Instance();
    auto& cfg = *Config::Instance();

    // Map inputs to descriptor
    ffxDispatchDescUpscale fsrParams = {};
    fsrParams.header.type = FFX_API_DISPATCH_DESC_TYPE_UPSCALE;
    fsrParams.commandList = InCommandList;

    // Mandatory Inputs
    fsrParams.color = ffxApiGetResourceDX12(inputs.Color, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    fsrParams.motionVectors = ffxApiGetResourceDX12(inputs.MotionVectors, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    fsrParams.depth = ffxApiGetResourceDX12(inputs.Depth, FFX_API_RESOURCE_STATE_COMPUTE_READ);

    // Output
    fsrParams.output = ffxApiGetResourceDX12(dstTex, FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);

    // Reactive / Transparency
    if (inputs.ReactiveMask)
    {
        LOG_DEBUG("Assigning Reactive Mask");
        fsrParams.reactive = ffxApiGetResourceDX12(inputs.ReactiveMask, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    }

    if (inputs.TransparencyMask)
    {
        LOG_DEBUG("Assigning Transparency Mask");
        fsrParams.transparencyAndComposition =
            ffxApiGetResourceDX12(inputs.TransparencyMask, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    }

    // Exposure
    if (AutoExposure())
        LOG_DEBUG("Using AutoExposure");
    else if (inputs.ExposureMap)
    {
        LOG_DEBUG("Using Exposure Texture");
        fsrParams.exposure = ffxApiGetResourceDX12(inputs.ExposureMap, FFX_API_RESOURCE_STATE_COMPUTE_READ);
    }

    // State Tracking / Debug
    _hasColor = fsrParams.color.resource != nullptr;
    _hasDepth = fsrParams.depth.resource != nullptr;
    _hasMV = fsrParams.motionVectors.resource != nullptr;
    _hasExposure = fsrParams.exposure.resource != nullptr;
    _hasTM = fsrParams.transparencyAndComposition.resource != nullptr;
    _accessToReactiveMask = inputs.ReactiveMask != nullptr; // Keep original logic tracking if "native" mask existed
    _hasOutput = fsrParams.output.resource != nullptr;

    // FSR 4 Format Fixes
    if (Version().major >= 4)
    {
        ffxResolveTypelessFormat(fsrParams.color.description.format);
        ffxResolveTypelessFormat(fsrParams.depth.description.format);
        ffxResolveTypelessFormat(fsrParams.motionVectors.description.format);
        ffxResolveTypelessFormat(fsrParams.exposure.description.format);
        ffxResolveTypelessFormat(fsrParams.transparencyAndComposition.description.format);
        ffxResolveTypelessFormat(fsrParams.output.description.format);
    }

    UpdateConfiguration(inParams, fsrParams);

    // Dispatch
    LOG_DEBUG("Dispatching FSR...");
    const ffxReturnCode_t result = FfxApiProxy::D3D12_Dispatch(&_upscaleCtx, &fsrParams.header);

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


void FSR31FeatureDx12::UpdateConfiguration(const NVSDK_NGX_Parameter& inParams, ffxDispatchDescUpscale& fsrParams)
{
    auto& state = State::Instance();
    auto& cfg = *Config::Instance();

    // Configure Debug Flags
    // Handle FSR 4.0 specific debug view logic or standard FSR debug flags
    if (cfg.FsrDebugView.value_or_default() &&
        (Version() < feature_version { 4, 0, 0 } || cfg.Fsr4EnableDebugView.value_or_default()))
    {
        fsrParams.flags |= FFX_UPSCALE_FLAG_DRAW_DEBUG_VIEW;
    }

    // Color Space Configuration
    if (cfg.FsrNonLinearPQ.value_or_default())
        fsrParams.flags |= FFX_UPSCALE_FLAG_NON_LINEAR_COLOR_PQ;
    else if (cfg.FsrNonLinearSRGB.value_or_default())
        fsrParams.flags |= FFX_UPSCALE_FLAG_NON_LINEAR_COLOR_SRGB;

    // Retrieve Jitter Offsets
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_X, &fsrParams.jitterOffset.x);
    inParams.Get(NVSDK_NGX_Parameter_Jitter_Offset_Y, &fsrParams.jitterOffset.y);

    LOG_DEBUG("Jitter Offset: {0}x{1}", fsrParams.jitterOffset.x, fsrParams.jitterOffset.y);

    // Sharpening
    if (cfg.OverrideSharpness.value_or_default())
        _sharpness = cfg.Sharpness.value_or_default();
    else
        _sharpness = GetSharpness(&inParams);

    // If RCAS is enabled externally, disable FSR built-in sharpening to avoid double sharpening
    if (cfg.RcasEnabled.value_or_default())
    {
        fsrParams.enableSharpening = false;
        fsrParams.sharpness = 0.0f;
    }
    else
    {
        if (_sharpness > 1.0f)
            _sharpness = 1.0f;

        fsrParams.enableSharpening = _sharpness > 0.0f;
        fsrParams.sharpness = _sharpness;
    }

    // Force enable RCAS when in FSR4 debug view mode
    // it crashes when sharpening is disabled
    // Debug view expects RCAS output (not sure why)
    if (Version() >= feature_version { 4, 0, 2 } && cfg.FsrDebugView.value_or_default() &&
        cfg.Fsr4EnableDebugView.value_or_default() && !fsrParams.enableSharpening)
    {
        fsrParams.enableSharpening = true;
        fsrParams.sharpness = 0.01f;
    }

    // Get reset flag
    uint32_t reset = 0;
    inParams.Get(NVSDK_NGX_Parameter_Reset, &reset);
    fsrParams.reset = (reset == 1);

    GetRenderResolution(&inParams, &fsrParams.renderSize.width, &fsrParams.renderSize.height);
    LOG_DEBUG("Input Resolution: {0}x{1}", fsrParams.renderSize.width, fsrParams.renderSize.height);

    // --- Motion Vector Scaling ---
    float MVScaleX = 1.0f;
    float MVScaleY = 1.0f;

    if (inParams.Get(NVSDK_NGX_Parameter_MV_Scale_X, &MVScaleX) == NVSDK_NGX_Result_Success &&
        inParams.Get(NVSDK_NGX_Parameter_MV_Scale_Y, &MVScaleY) == NVSDK_NGX_Result_Success)
    {
        fsrParams.motionVectorScale.x = MVScaleX;
        fsrParams.motionVectorScale.y = MVScaleY;
    }
    else
    {
        LOG_WARN("Can't get motion vector scales!");
        fsrParams.motionVectorScale.x = MVScaleX;
        fsrParams.motionVectorScale.y = MVScaleY;
    }

    LOG_DEBUG("Sharpness: {0}", fsrParams.sharpness);

    // Camera & View Parameters with fallbacks

    // Explicit near plane
    // Not explicitly set in the DLSS path. DLSS assumes near == 0 and far == 1 or the inverse.
    //
    // [TODO!] Review depth inversion logic and config fallback. FsrCameraNear on both branches looks like a typo.
    if (!TryGetToggleableNGXParam(inParams, OptiKeys::FSR_NearPlane, cfg.FsrUseFsrInputValues, fsrParams.cameraNear))
    {
        if (DepthInverted())
            fsrParams.cameraFar = cfg.FsrCameraNear.value_or_default();
        else
            fsrParams.cameraNear = cfg.FsrCameraNear.value_or_default();
    }

    // Explicit far plane
    if (!TryGetToggleableNGXParam(inParams, OptiKeys::FSR_FarPlane, cfg.FsrUseFsrInputValues, fsrParams.cameraFar))
    {
        if (DepthInverted())
            fsrParams.cameraNear = cfg.FsrCameraFar.value_or_default();
        else
            fsrParams.cameraFar = cfg.FsrCameraFar.value_or_default();
    }

    // Not being set in DLSS or XeSS input paths. Inverse VP matrices may be deprecated in modern DLSS.
    if (!TryGetToggleableNGXParam(inParams, OptiKeys::FSR_CameraFovVertical, cfg.FsrUseFsrInputValues,
                                fsrParams.cameraFovAngleVertical))
    {
        if (cfg.FsrVerticalFov.has_value())
            fsrParams.cameraFovAngleVertical = GetRadiansFromDeg(cfg.FsrVerticalFov.value());
        else if (cfg.FsrHorizontalFov.value_or_default() > 0.0f)
        {
            const float hFovRad = GetRadiansFromDeg(cfg.FsrHorizontalFov.value());
            fsrParams.cameraFovAngleVertical =
                GetVerticalFovFromHorizontal(hFovRad, (float) TargetWidth(), (float) TargetHeight());
        }
        else
            fsrParams.cameraFovAngleVertical = GetRadiansFromDeg(60);
    }

    // Use game deltatime or fall back to internal measurements
    if (!TryGetToggleableNGXParam(inParams, OptiKeys::FSR_FrameTimeDelta, cfg.FsrUseFsrInputValues, fsrParams.frameTimeDelta))
    {
        if (inParams.Get(NVSDK_NGX_Parameter_FrameTimeDeltaInMsec, &fsrParams.frameTimeDelta) !=
                NVSDK_NGX_Result_Success || fsrParams.frameTimeDelta < 1.0f)
        {
            fsrParams.frameTimeDelta = (float)GetDeltaTime();
        }
    }

    LOG_DEBUG("FrameTimeDeltaInMsec: {0}", fsrParams.frameTimeDelta);

    if (!TryGetToggleableNGXParam(inParams, OptiKeys::FSR_ViewSpaceToMetersFactor, cfg.FsrUseFsrInputValues,
                                fsrParams.viewSpaceToMetersFactor))
    {
        fsrParams.viewSpaceToMetersFactor = 0.0f;
    }

    fsrParams.upscaleSize.width = TargetWidth();
    fsrParams.upscaleSize.height = TargetHeight();

    if (inParams.Get(NVSDK_NGX_Parameter_DLSS_Pre_Exposure, &fsrParams.preExposure) != NVSDK_NGX_Result_Success)
        fsrParams.preExposure = 1.0f;

    // FSR 3.1+ Advanced Configuration
    // Apply volatile configuration keys using FfxApiProxy::D3D12_Configure

    // Velocity Factor (FSR 3.1.1+)
    if (Version() >= feature_version { 3, 1, 1 })
    {
        SetFfxUpscaleKeyValue(&_upscaleCtx, _velocity, cfg.FsrVelocity,
                                    FFX_API_CONFIGURE_UPSCALE_KEY_FVELOCITYFACTOR, "Velocity");
    }

    // Reactiveness, Shading, and Accumulation (FSR 3.1.4+)
    if (Version() >= feature_version { 3, 1, 4 })
    {
        SetFfxUpscaleKeyValue(&_upscaleCtx, _reactiveScale, cfg.FsrReactiveScale,
                                    FFX_API_CONFIGURE_UPSCALE_KEY_FREACTIVENESSSCALE, "Reactive Scale");
        SetFfxUpscaleKeyValue(&_upscaleCtx, _shadingScale, cfg.FsrShadingScale,
                                    FFX_API_CONFIGURE_UPSCALE_KEY_FSHADINGCHANGESCALE, "Shading Scale");
        SetFfxUpscaleKeyValue(&_upscaleCtx, _accAddPerFrame, cfg.FsrAccAddPerFrame,
                                    FFX_API_CONFIGURE_UPSCALE_KEY_FACCUMULATIONADDEDPERFRAME, "Acc. Add Per Frame");
        SetFfxUpscaleKeyValue(&_upscaleCtx, _minDisOccAcc, cfg.FsrMinDisOccAcc,
                                    FFX_API_CONFIGURE_UPSCALE_KEY_FMINDISOCCLUSIONACCUMULATION,
                                    "Min Disocclusion Acc.");
    }

    // Output Scaling Override
    if (cfg.OutputScalingEnabled.value_or_default())
    {
        // If external output scaling is enabled, we may need to adjust the reported upscale size
        if (inParams.Get(OptiKeys::FSR_UpscaleWidth, &fsrParams.upscaleSize.width) == NVSDK_NGX_Result_Success)
            fsrParams.upscaleSize.width *= static_cast<uint32_t>(cfg.OutputScalingMultiplier.value_or_default());

        if (inParams.Get(OptiKeys::FSR_UpscaleHeight, &fsrParams.upscaleSize.height) == NVSDK_NGX_Result_Success)
            fsrParams.upscaleSize.height *= static_cast<uint32_t>(cfg.OutputScalingMultiplier.value_or_default());
    }
}

void FSR31FeatureDx12::PostProcess(
    const NVSDK_NGX_Parameter& inParams, 
    bool useSS,
    ID3D12GraphicsCommandList* InCommandList, 
    ID3D12Resource* motionVectors,
    ID3D12Resource* fsrDstTex,
    ID3D12Resource* dstTex)
{
    auto& state = State::Instance();
    auto& cfg = *Config::Instance();

    // If enabled, RCAS reads from the FSR output and writes to the next stage, either 
    // the OutputScaler buffer or the final output.
    bool rcasRan = false;
    const bool shouldSharpen = cfg.RcasEnabled.value_or_default() && 
        (_sharpness > 0.0f || (cfg.MotionSharpnessEnabled.value_or_default() && cfg.MotionSharpness.value_or_default() > 0.0f)) && 
        RCAS->CanRender();

    if (shouldSharpen)
    {
        // Transition FSR output for reading by RCAS
        if (fsrDstTex != RCAS->Buffer())
        {
            ResourceBarrier(InCommandList, fsrDstTex,
                            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }

        RCAS->SetBufferState(InCommandList, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        // Configure RCAS
        RcasConstants rcasConstants 
        {
            .Sharpness = _sharpness,
            .DisplaySizeMV = !(GetFeatureFlags() & NVSDK_NGX_DLSS_Feature_Flags_MVLowRes),
            .RenderWidth = (int)RenderWidth(),
            .RenderHeight = (int)RenderHeight(),
            .DisplayWidth = (int)TargetWidth(),
            .DisplayHeight = (int)TargetHeight()
        };

        inParams.Get(NVSDK_NGX_Parameter_MV_Scale_X, &rcasConstants.MvScaleX);
        inParams.Get(NVSDK_NGX_Parameter_MV_Scale_Y, &rcasConstants.MvScaleY);

        // Determine RCAS Output Target
        // If scaling is next, write to the scaler's internal buffer. Otherwise, write to the final app texture.
        ID3D12Resource* rcasOutput = useSS ? OutputScaler->Buffer() : dstTex;

        if (RCAS->Dispatch(Device, InCommandList, fsrDstTex, motionVectors, rcasConstants, rcasOutput))
            rcasRan = true;
        else
        {
            // Fallback if dispatch fails
            cfg.RcasEnabled.set_volatile_value(false);
        }
    }

    // Optional output scaling
    // Input is always OutputScaler->Buffer() here because:
    //  If RCAS ran above, it wrote into OutputScaler->Buffer().
    //  If RCAS did NOT run, Evaluate() configured FSR to write directly into OutputScaler->Buffer().  
    if (useSS)
    {
        LOG_DEBUG("Scaling output...");
        OutputScaler->SetBufferState(InCommandList, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

        if (!OutputScaler->Dispatch(Device, InCommandList, OutputScaler->Buffer(), dstTex))
        {
            cfg.OutputScalingEnabled.set_volatile_value(false);
            state.changeBackend[Handle()->Id] = true;
            return;
        }
    }

    // Composite ImGui overlay
    if (!cfg.OverlayMenu.value_or_default() && _frameCount > 30)
    {
        if (Imgui != nullptr && Imgui.get() != nullptr)
        {
            if (Imgui->IsHandleDifferent())
                Imgui.reset();
            else
                Imgui->Render(InCommandList, dstTex);
        }
        else
        {
            if (Imgui == nullptr || Imgui.get() == nullptr)
                Imgui = std::make_unique<Menu_Dx12>(GetForegroundWindow(), Device);
        }
    }
}
