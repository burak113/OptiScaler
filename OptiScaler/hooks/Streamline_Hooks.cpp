#include <pch.h>

#include "Streamline_Hooks.h"

#include <json.hpp>
#include "detours/detours.h"

#include <Util.h>
#include <Config.h>
#include <proxies/KernelBase_Proxy.h>
#include <menu/menu_overlay_base.h>
#include <hooks/Reflex_Hooks.h>
#include <magic_enum.hpp>
#include <sl1_reflex.h>
#include <nvapi/fakenvapi.h>
#include <inputs/FG/DLSSG_Mod.h>
#include <NVNGX_Parameter.h>

sl::RenderAPI StreamlineHooks::renderApi = sl::RenderAPI::eCount;
std::mutex StreamlineHooks::setConstantsMutex {};
std::mutex StreamlineHooks::rrSignalTagMutex {};
RRSignalTagDiagnostics StreamlineHooks::rrSignalTagDiagnostics {};
std::array<Microsoft::WRL::ComPtr<ID3D12Resource>,
           static_cast<size_t>(RRTaggedSignal::Count)> StreamlineHooks::rrTaggedD3D12Resources {};
SLTagInventoryDiagnostics StreamlineHooks::slTagInventoryDiagnostics {};
RRNGXPointerDiagnostics StreamlineHooks::rrNGXPointerDiagnostics {};
SystemCaps* StreamlineHooks::systemCaps = nullptr;
SystemCapsSl15* StreamlineHooks::systemCapsSl15 = nullptr;

namespace
{
thread_local uint32_t g_rrActiveEvaluationFrame = UINT32_MAX;
thread_local uint32_t g_rrActiveEvaluationViewport = UINT32_MAX;

class ScopedRRActiveEvaluationFrame
{
  public:
    ScopedRRActiveEvaluationFrame(uint32_t frame, uint32_t viewport) noexcept
        : m_previousFrame(g_rrActiveEvaluationFrame),
          m_previousViewport(g_rrActiveEvaluationViewport)
    {
        g_rrActiveEvaluationFrame = frame;
        g_rrActiveEvaluationViewport = viewport;
    }

    ~ScopedRRActiveEvaluationFrame()
    {
        g_rrActiveEvaluationFrame = m_previousFrame;
        g_rrActiveEvaluationViewport = m_previousViewport;
    }

  private:
    uint32_t m_previousFrame;
    uint32_t m_previousViewport;
};
}

// interposer
decltype(&slInit) StreamlineHooks::o_slInit = nullptr;
decltype(&slSetTag) StreamlineHooks::o_slSetTag = nullptr;
decltype(&slSetTagForFrame) StreamlineHooks::o_slSetTagForFrame = nullptr;
decltype(&slEvaluateFeature) StreamlineHooks::o_slEvaluateFeature = nullptr;
decltype(&slAllocateResources) StreamlineHooks::o_slAllocateResources = nullptr;
decltype(&slSetConstants) StreamlineHooks::o_slSetConstants = nullptr;
decltype(&slGetNativeInterface) StreamlineHooks::o_slGetNativeInterface = nullptr;
decltype(&slSetD3DDevice) StreamlineHooks::o_slSetD3DDevice = nullptr;
decltype(&slGetNewFrameToken) StreamlineHooks::o_slGetNewFrameToken = nullptr;

decltype(&sl1::slInit) StreamlineHooks::o_slInit_sl1 = nullptr;

sl::PFun_LogMessageCallback* StreamlineHooks::o_logCallback = nullptr;
sl1::pfunLogMessageCallback* StreamlineHooks::o_logCallback_sl1 = nullptr;

// DLSS
StreamlineHooks::PFN_slGetPluginFunction StreamlineHooks::o_dlss_slGetPluginFunction = nullptr;
StreamlineHooks::PFN_slOnPluginLoad StreamlineHooks::o_dlss_slOnPluginLoad = nullptr;
decltype(&slDLSSGetOptimalSettings) StreamlineHooks::o_slDLSSGetOptimalSettings = nullptr;

// DLSSG
StreamlineHooks::PFN_slGetPluginFunction StreamlineHooks::o_dlssg_slGetPluginFunction = nullptr;
StreamlineHooks::PFN_slOnPluginLoad StreamlineHooks::o_dlssg_slOnPluginLoad = nullptr;
decltype(&slDLSSGSetOptions) StreamlineHooks::o_slDLSSGSetOptions = nullptr;
decltype(&slDLSSGGetState) StreamlineHooks::o_slDLSSGGetState = nullptr;

// Reflex
StreamlineHooks::PFN_slGetPluginFunction StreamlineHooks::o_reflex_slGetPluginFunction = nullptr;
StreamlineHooks::PFN_slSetConstants_sl1 StreamlineHooks::o_reflex_slSetConstants_sl1 = nullptr;
StreamlineHooks::PFN_slOnPluginLoad StreamlineHooks::o_reflex_slOnPluginLoad = nullptr;
decltype(&slReflexSetOptions) StreamlineHooks::o_slReflexSetOptions = nullptr;
sl::ReflexMode StreamlineHooks::reflexGamesLastMode = sl::ReflexMode::eOff;

static bool TryGetRRTaggedSignal(sl::BufferType type, RRTaggedSignal& signal)
{
    switch (type)
    {
    case sl::kBufferTypeNormalRoughness:
        signal = RRTaggedSignal::NormalRoughness;
        return true;
    case sl::kBufferTypeEmissive:
        signal = RRTaggedSignal::Emissive;
        return true;
    case sl::kBufferTypeSpecularMotionVectors:
        signal = RRTaggedSignal::SpecularMotionVectors;
        return true;
    case sl::kBufferTypeReflectionMotionVectors:
        signal = RRTaggedSignal::ReflectionMotionVectors;
        return true;
    case sl::kBufferTypeSpecularHitDistance:
        signal = RRTaggedSignal::SpecularHitDistance;
        return true;
    case sl::kBufferTypeSpecularRayDirectionHitDistance:
        signal = RRTaggedSignal::SpecularRayDirectionHitDistance;
        return true;
    case sl::kBufferTypeDiffuseHitNoisy:
        signal = RRTaggedSignal::DiffuseNoisy;
        return true;
    case sl::kBufferTypeDiffuseHitDenoised:
        signal = RRTaggedSignal::DiffuseDenoised;
        return true;
    case sl::kBufferTypeSpecularHitNoisy:
        signal = RRTaggedSignal::SpecularNoisy;
        return true;
    case sl::kBufferTypeSpecularHitDenoised:
        signal = RRTaggedSignal::SpecularDenoised;
        return true;
    case sl::kBufferTypeShadowNoisy:
        signal = RRTaggedSignal::ShadowNoisy;
        return true;
    case sl::kBufferTypeShadowDenoised:
        signal = RRTaggedSignal::ShadowDenoised;
        return true;
    case sl::kBufferTypeAmbientOcclusionNoisy:
        signal = RRTaggedSignal::AmbientOcclusionNoisy;
        return true;
    case sl::kBufferTypeAmbientOcclusionDenoised:
        signal = RRTaggedSignal::AmbientOcclusionDenoised;
        return true;
    case sl::kBufferTypeShadowHint:
        signal = RRTaggedSignal::ShadowHint;
        return true;
    case sl::kBufferTypeReflectionHint:
        signal = RRTaggedSignal::ReflectionHint;
        return true;
    default:
        return false;
    }
}

static bool IsRRCheckerboardInput(RRTaggedSignal signal)
{
    return signal == RRTaggedSignal::DiffuseNoisy ||
           signal == RRTaggedSignal::SpecularNoisy ||
           signal == RRTaggedSignal::ShadowNoisy ||
           signal == RRTaggedSignal::AmbientOcclusionNoisy;
}

static const char* GetRRTagSourceName(RRTagSource source)
{
    switch (source)
    {
    case RRTagSource::SetTag:
        return "slSetTag";
    case RRTagSource::SetTagForFrame:
        return "slSetTagForFrame";
    case RRTagSource::EvaluateFeature:
        return "slEvaluateFeature";
    default:
        return "unknown";
    }
}

const char* StreamlineHooks::getSLBufferTypeName(sl::BufferType type)
{
    static constexpr std::array<const char*, 68> names {
        "Depth",
        "MotionVectors",
        "HUDLessColor",
        "ScalingInputColor",
        "ScalingOutputColor",
        "Normals",
        "Roughness",
        "Albedo",
        "SpecularAlbedo",
        "IndirectAlbedo",
        "SpecularMotionVectors",
        "DisocclusionMask",
        "Emissive",
        "Exposure",
        "NormalRoughness",
        "DiffuseHitNoisy",
        "DiffuseHitDenoised",
        "SpecularHitNoisy",
        "SpecularHitDenoised",
        "ShadowNoisy",
        "ShadowDenoised",
        "AmbientOcclusionNoisy",
        "AmbientOcclusionDenoised",
        "UIColorAndAlpha",
        "ShadowHint",
        "ReflectionHint",
        "ParticleHint",
        "TransparencyHint",
        "AnimatedTextureHint",
        "BiasCurrentColorHint",
        "RaytracingDistance",
        "ReflectionMotionVectors",
        "Position",
        "InvalidDepthMotionHint",
        "Alpha",
        "OpaqueColor",
        "ReactiveMaskHint",
        "TransparencyAndCompositionMaskHint",
        "ReflectedAlbedo",
        "ColorBeforeParticles",
        "ColorBeforeTransparency",
        "ColorBeforeFog",
        "SpecularHitDistance",
        "SpecularRayDirectionHitDistance",
        "SpecularRayDirection",
        "DiffuseHitDistance",
        "DiffuseRayDirectionHitDistance",
        "DiffuseRayDirection",
        "HiResDepth",
        "LinearDepth",
        "BidirectionalDistortionField",
        "TransparencyLayer",
        "TransparencyLayerOpacity",
        "Backbuffer",
        "NoWarpMask",
        "ColorAfterParticles",
        "ColorAfterTransparency",
        "ColorAfterFog",
        "ScreenSpaceSubsurfaceScatteringGuide",
        "ColorBeforeScreenSpaceSubsurfaceScattering",
        "ColorAfterScreenSpaceSubsurfaceScattering",
        "ScreenSpaceRefractionGuide",
        "ColorBeforeScreenSpaceRefraction",
        "ColorAfterScreenSpaceRefraction",
        "DepthOfFieldGuide",
        "ColorBeforeDepthOfField",
        "ColorAfterDepthOfField",
        "ScalingOutputAlpha"
    };

    return type < names.size() ? names[type] : "Unknown/custom";
}

const char* StreamlineHooks::getRRTaggedSignalName(RRTaggedSignal signal)
{
    switch (signal)
    {
    case RRTaggedSignal::NormalRoughness:
        return "NormalRoughness";
    case RRTaggedSignal::Emissive:
        return "Emissive";
    case RRTaggedSignal::SpecularMotionVectors:
        return "SpecularMotionVectors";
    case RRTaggedSignal::ReflectionMotionVectors:
        return "ReflectionMotionVectors";
    case RRTaggedSignal::SpecularHitDistance:
        return "SpecularHitDistance";
    case RRTaggedSignal::SpecularRayDirectionHitDistance:
        return "SpecularRayDirectionHitDistance";
    case RRTaggedSignal::DiffuseNoisy:
        return "Diffuse.Noisy";
    case RRTaggedSignal::DiffuseDenoised:
        return "Diffuse.Denoised";
    case RRTaggedSignal::SpecularNoisy:
        return "Specular.Noisy";
    case RRTaggedSignal::SpecularDenoised:
        return "Specular.Denoised";
    case RRTaggedSignal::ShadowNoisy:
        return "Shadow.Noisy";
    case RRTaggedSignal::ShadowDenoised:
        return "Shadow.Denoised";
    case RRTaggedSignal::AmbientOcclusionNoisy:
        return "AmbientOcclusion.Noisy";
    case RRTaggedSignal::AmbientOcclusionDenoised:
        return "AmbientOcclusion.Denoised";
    case RRTaggedSignal::ShadowHint:
        return "ShadowHint";
    case RRTaggedSignal::ReflectionHint:
        return "ReflectionHint";
    default:
        return "Unknown";
    }
}

const char* StreamlineHooks::getRRPreferredTagFormat(RRTaggedSignal signal)
{
    switch (signal)
    {
    case RRTaggedSignal::NormalRoughness:
        return "game-defined";
    case RRTaggedSignal::Emissive:
        return "shader-readable color texture";
    case RRTaggedSignal::SpecularMotionVectors:
    case RRTaggedSignal::ReflectionMotionVectors:
        return "DXGI_FORMAT_R16G16_FLOAT, DXGI_FORMAT_R32G32_FLOAT, "
               "DXGI_FORMAT_R16G16B16A16_FLOAT, or DXGI_FORMAT_R32G32B32A32_FLOAT";
    case RRTaggedSignal::SpecularHitDistance:
        return "DXGI_FORMAT_R16_FLOAT or DXGI_FORMAT_R32_FLOAT";
    case RRTaggedSignal::SpecularRayDirectionHitDistance:
        return "DXGI_FORMAT_R16G16B16A16_FLOAT or DXGI_FORMAT_R32G32B32A32_FLOAT";
    case RRTaggedSignal::DiffuseNoisy:
    case RRTaggedSignal::DiffuseDenoised:
    case RRTaggedSignal::SpecularNoisy:
    case RRTaggedSignal::SpecularDenoised:
        return "DXGI_FORMAT_R16G16B16A16_FLOAT";
    case RRTaggedSignal::ShadowNoisy:
        return "DXGI_FORMAT_R16_FLOAT";
    case RRTaggedSignal::ShadowDenoised:
    case RRTaggedSignal::AmbientOcclusionNoisy:
    case RRTaggedSignal::AmbientOcclusionDenoised:
        return "DXGI_FORMAT_R8_UNORM";
    case RRTaggedSignal::ShadowHint:
    case RRTaggedSignal::ReflectionHint:
        return "hint only; not an RR signal";
    default:
        return "unknown";
    }
}

bool StreamlineHooks::isRRPreferredTagFormat(RRTaggedSignal signal, DXGI_FORMAT format)
{
    switch (signal)
    {
    case RRTaggedSignal::NormalRoughness:
        return format != DXGI_FORMAT_UNKNOWN;
    case RRTaggedSignal::Emissive:
        switch (format)
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
    case RRTaggedSignal::SpecularMotionVectors:
    case RRTaggedSignal::ReflectionMotionVectors:
        switch (format)
        {
        case DXGI_FORMAT_R16G16_FLOAT:
        case DXGI_FORMAT_R32G32_FLOAT:
        case DXGI_FORMAT_R16G16B16A16_FLOAT:
        case DXGI_FORMAT_R32G32B32A32_FLOAT:
            return true;
        default:
            return false;
        }
    case RRTaggedSignal::SpecularHitDistance:
        return format == DXGI_FORMAT_R16_FLOAT || format == DXGI_FORMAT_R32_FLOAT;
    case RRTaggedSignal::SpecularRayDirectionHitDistance:
        return format == DXGI_FORMAT_R16G16B16A16_FLOAT ||
               format == DXGI_FORMAT_R32G32B32A32_FLOAT;
    case RRTaggedSignal::DiffuseNoisy:
    case RRTaggedSignal::DiffuseDenoised:
    case RRTaggedSignal::SpecularNoisy:
    case RRTaggedSignal::SpecularDenoised:
        return format == DXGI_FORMAT_R16G16B16A16_FLOAT;
    case RRTaggedSignal::ShadowNoisy:
        return format == DXGI_FORMAT_R16_FLOAT;
    case RRTaggedSignal::ShadowDenoised:
    case RRTaggedSignal::AmbientOcclusionNoisy:
    case RRTaggedSignal::AmbientOcclusionDenoised:
        return format == DXGI_FORMAT_R8_UNORM;
    default:
        return false;
    }
}

const char* StreamlineHooks::getRRCheckerboardAssessment(
    RRTaggedSignal signal, const RRTaggedResourceDiagnostic& diagnostic,
    uint32_t renderWidth, uint32_t renderHeight)
{
    if (!diagnostic.observed)
        return "not-observed";
    if (!diagnostic.present)
        return "cleared";
    if (!IsRRCheckerboardInput(signal))
        return "not-applicable";
    if (renderWidth == 0 || renderHeight == 0)
        return "render-size-unknown";
    if (diagnostic.effectiveHeight != renderHeight)
        return "resolution-mismatch";
    if (diagnostic.effectiveWidth == renderWidth)
        return "full-resolution";

    const uint64_t doubledWidth = static_cast<uint64_t>(diagnostic.effectiveWidth) * 2u;
    const uint64_t renderWidth64 = renderWidth;
    if (doubledWidth + 1u >= renderWidth64 && doubledWidth <= renderWidth64 + 1u)
        return "half-width-candidate";

    return "resolution-mismatch";
}

RRSignalTagDiagnostics StreamlineHooks::getRRSignalTagDiagnostics()
{
    std::scoped_lock lock(rrSignalTagMutex);
    return rrSignalTagDiagnostics;
}

Microsoft::WRL::ComPtr<ID3D12Resource> StreamlineHooks::getRRTaggedD3D12Resource(RRTaggedSignal signal)
{
    std::scoped_lock lock(rrSignalTagMutex);
    return rrTaggedD3D12Resources[static_cast<size_t>(signal)];
}

RRD3D12SignalTagSnapshot StreamlineHooks::getRRD3D12SignalTagSnapshot()
{
    std::scoped_lock lock(rrSignalTagMutex);
    RRD3D12SignalTagSnapshot snapshot {};
    snapshot.generation = rrSignalTagDiagnostics.generation;
    snapshot.activeEvaluationFrame = g_rrActiveEvaluationFrame;
    snapshot.activeEvaluationViewport = g_rrActiveEvaluationViewport;
    for (size_t i = 0; i < snapshot.resources.size(); ++i)
    {
        snapshot.resources[i].diagnostic = rrSignalTagDiagnostics.resources[i];
        snapshot.resources[i].resource = rrTaggedD3D12Resources[i];
    }
    return snapshot;
}

SLConstantsSnapshot StreamlineHooks::getSLConstantsSnapshot()
{
    std::scoped_lock lock(setConstantsMutex);
    const auto& state = State::Instance();
    return {
        .constants = state.slLastConstants,
        .frameIndex = state.slLastConstantsFrame,
        .viewport = state.slLastConstantsViewport
    };
}

void StreamlineHooks::resetRRSignalTagDiagnostics()
{
    std::scoped_lock lock(rrSignalTagMutex);
    rrSignalTagDiagnostics = {};
    rrTaggedD3D12Resources = {};
}

static bool HasResourceMetadataChanged(const RRTaggedResourceDiagnostic& previous,
                                       const RRTaggedResourceDiagnostic& next)
{
    return
        !previous.observed ||
        previous.present != next.present ||
        previous.debugName != next.debugName ||
        previous.nativeWidth != next.nativeWidth ||
        previous.nativeHeight != next.nativeHeight ||
        previous.effectiveWidth != next.effectiveWidth ||
        previous.effectiveHeight != next.effectiveHeight ||
        previous.extentLeft != next.extentLeft ||
        previous.extentTop != next.extentTop ||
        previous.format != next.format ||
        previous.dimension != next.dimension ||
        previous.resourceFlags != next.resourceFlags ||
        previous.mipLevels != next.mipLevels ||
        previous.arraySize != next.arraySize ||
        previous.sampleCount != next.sampleCount ||
        previous.state != next.state ||
        previous.lifecycle != next.lifecycle ||
        previous.viewport != next.viewport;
}

static std::string GetD3D12DebugObjectName(ID3D12Object* object)
{
    if (object == nullptr)
        return {};

    UINT nameSize = 0;
    object->GetPrivateData(WKPDID_D3DDebugObjectName, &nameSize, nullptr);
    if (nameSize > 1)
    {
        std::string name(nameSize, '\0');
        if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectName, &nameSize, name.data())))
        {
            name.resize(strnlen(name.c_str(), name.size()));
            return name;
        }
    }

    nameSize = 0;
    object->GetPrivateData(WKPDID_D3DDebugObjectNameW, &nameSize, nullptr);
    if (nameSize > sizeof(wchar_t))
    {
        std::vector<wchar_t> name(nameSize / sizeof(wchar_t), L'\0');
        if (SUCCEEDED(object->GetPrivateData(WKPDID_D3DDebugObjectNameW, &nameSize, name.data())))
            return wstring_to_string(name.data());
    }

    return {};
}

static RRTaggedResourceDiagnostic CaptureSLResourceTag(
    const sl::ResourceTag& tag, uint32_t frameIndex, uint32_t viewport,
    RRTagSource source)
{
    RRTaggedResourceDiagnostic result {};
    result.observed = true;
    result.present = tag.resource != nullptr && tag.resource->native != nullptr;
    result.frameIndex = frameIndex;
    result.viewport = viewport;
    result.source = source;
    result.lifecycle = tag.lifecycle;

    if (!result.present)
        return result;

    result.resourceAddress = tag.resource->native;
    result.state = tag.resource->state;

    auto* resource = reinterpret_cast<ID3D12Resource*>(tag.resource->native);
    const D3D12_RESOURCE_DESC desc = resource->GetDesc();
    result.debugName = GetD3D12DebugObjectName(resource);
    result.nativeWidth = desc.Width;
    result.nativeHeight = desc.Height;
    result.format = desc.Format;
    result.dimension = desc.Dimension;
    result.resourceFlags = desc.Flags;
    result.mipLevels = desc.MipLevels;
    result.arraySize = desc.DepthOrArraySize;
    result.sampleCount = desc.SampleDesc.Count;

    result.usesExtent = static_cast<bool>(tag.extent);
    result.extentLeft = tag.extent.left;
    result.extentTop = tag.extent.top;
    result.effectiveWidth = result.usesExtent
        ? tag.extent.width
        : static_cast<uint32_t>(std::min<uint64_t>(desc.Width, UINT32_MAX));
    result.effectiveHeight = result.usesExtent ? tag.extent.height : desc.Height;
    return result;
}

SLTagInventoryDiagnostics StreamlineHooks::getSLTagInventoryDiagnostics()
{
    std::scoped_lock lock(rrSignalTagMutex);
    return slTagInventoryDiagnostics;
}

void StreamlineHooks::probeSLResourceTag(
    const sl::ResourceTag& tag, uint32_t frameIndex, uint32_t viewport,
    RRTagSource source)
{
    RRTaggedResourceDiagnostic next =
        CaptureSLResourceTag(tag, frameIndex, viewport, source);
    bool shouldLog = false;

    {
        std::scoped_lock lock(rrSignalTagMutex);
        auto entry = std::find_if(
            slTagInventoryDiagnostics.resources.begin(), slTagInventoryDiagnostics.resources.end(),
            [&tag](const SLTaggedResourceInventoryEntry& candidate) { return candidate.type == tag.type; });

        if (entry == slTagInventoryDiagnostics.resources.end())
        {
            slTagInventoryDiagnostics.resources.push_back({ tag.type, next });
            entry = std::prev(slTagInventoryDiagnostics.resources.end());
            shouldLog = true;
        }
        else
        {
            next.updateCount = entry->resource.updateCount + 1;
            shouldLog = HasResourceMetadataChanged(entry->resource, next);
            entry->resource = next;
        }

        if (entry->resource.updateCount == 0)
            entry->resource.updateCount = 1;

        std::sort(
            slTagInventoryDiagnostics.resources.begin(), slTagInventoryDiagnostics.resources.end(),
            [](const SLTaggedResourceInventoryEntry& left, const SLTaggedResourceInventoryEntry& right) {
                return left.type < right.type;
            });
        ++slTagInventoryDiagnostics.generation;
    }

    if (!shouldLog)
        return;

    if (!next.present)
    {
        LOG_INFO("[SL_TAG_INVENTORY] {} type={} ({}) frame={} cleared",
                 GetRRTagSourceName(source), tag.type, getSLBufferTypeName(tag.type), frameIndex);
        return;
    }

    const auto formatName = magic_enum::enum_name(next.format);
    LOG_INFO(
        "[SL_TAG_INVENTORY] {} type={} ({}) frame={} ptr={}, debugName='{}', native={}x{}, effective={}x{}, "
        "extent=[{},{}], format={}({}), dimension={}, mips={}, arrays={}, samples={}, "
        "resourceFlags={:#x}, state={:#x}",
        GetRRTagSourceName(source), tag.type, getSLBufferTypeName(tag.type), frameIndex,
        next.resourceAddress, next.debugName, next.nativeWidth, next.nativeHeight,
        next.effectiveWidth, next.effectiveHeight, next.extentLeft, next.extentTop,
        formatName.empty() ? "UNKNOWN" : formatName, static_cast<uint32_t>(next.format),
        static_cast<uint32_t>(next.dimension), next.mipLevels, next.arraySize, next.sampleCount,
        static_cast<uint32_t>(next.resourceFlags), next.state);
}

void StreamlineHooks::logSLTagInventoryDiagnostics(uint32_t renderWidth, uint32_t renderHeight)
{
    const auto diagnostics = getSLTagInventoryDiagnostics();
    LOG_INFO("[SL_TAG_INVENTORY] snapshot: generation={}, observedTypes={}, render={}x{}",
             diagnostics.generation, diagnostics.resources.size(), renderWidth, renderHeight);

    for (const auto& entry : diagnostics.resources)
    {
        const auto& diagnostic = entry.resource;
        if (!diagnostic.present)
        {
            LOG_INFO("[SL_TAG_INVENTORY] snapshot type={} ({}): cleared, updates={}",
                     entry.type, getSLBufferTypeName(entry.type), diagnostic.updateCount);
            continue;
        }

        const auto formatName = magic_enum::enum_name(diagnostic.format);
        const bool fullResolution =
            renderWidth != 0 && renderHeight != 0 &&
            diagnostic.effectiveWidth == renderWidth && diagnostic.effectiveHeight == renderHeight;
        const bool halfWidthCandidate =
            renderWidth != 0 && renderHeight != 0 &&
            diagnostic.effectiveHeight == renderHeight &&
            static_cast<uint64_t>(diagnostic.effectiveWidth) * 2u + 1u >= renderWidth &&
            static_cast<uint64_t>(diagnostic.effectiveWidth) * 2u <= static_cast<uint64_t>(renderWidth) + 1u;

        LOG_INFO(
            "[SL_TAG_INVENTORY] snapshot type={} ({}): ptr={}, debugName='{}', effective={}x{}, native={}x{}, "
            "format={}({}), state={:#x}, updates={}, resolutionClass={}",
            entry.type, getSLBufferTypeName(entry.type), diagnostic.resourceAddress,
            diagnostic.debugName,
            diagnostic.effectiveWidth, diagnostic.effectiveHeight,
            diagnostic.nativeWidth, diagnostic.nativeHeight,
            formatName.empty() ? "UNKNOWN" : formatName, static_cast<uint32_t>(diagnostic.format),
            diagnostic.state, diagnostic.updateCount,
            fullResolution ? "full-resolution" : halfWidthCandidate ? "half-width-candidate" : "other");
    }
}

RRNGXPointerDiagnostics StreamlineHooks::getRRNGXPointerDiagnostics()
{
    std::scoped_lock lock(rrSignalTagMutex);
    return rrNGXPointerDiagnostics;
}

static const char* GetNGXPointerKindName(RRNGXPointerKind kind)
{
    switch (kind)
    {
    case RRNGXPointerKind::OpaquePointer:
        return "opaque-pointer";
    case RRNGXPointerKind::D3D11Resource:
        return "D3D11-resource";
    case RRNGXPointerKind::D3D12Resource:
        return "D3D12-resource";
    default:
        return "unknown";
    }
}

void StreamlineHooks::probeRRNGXPointerParameters(const NVSDK_NGX_Parameter& parameters)
{
    static std::atomic_uint64_t probeCalls = 0;
    const uint64_t probeCall = probeCalls.fetch_add(1, std::memory_order_relaxed);
    {
        std::scoped_lock lock(rrSignalTagMutex);
        if (rrNGXPointerDiagnostics.generation != 0 && probeCall % 120u != 0)
            return;
    }

    uint32_t allocationType = NGX_AllocTypes::Unknown;
    if (parameters.Get(NGX_AllocTypes::AllocKey.data(), &allocationType) != NVSDK_NGX_Result_Success ||
        (allocationType != NGX_AllocTypes::InternDynamic &&
         allocationType != NGX_AllocTypes::InternPersistent))
    {
        std::scoped_lock lock(rrSignalTagMutex);
        rrNGXPointerDiagnostics.tableInspectable = false;
        return;
    }

    const auto& internalParameters = static_cast<const NVNGX_Parameters&>(parameters);
    const auto pointers = internalParameters.enumeratePointerParameters();

    std::vector<RRNGXPointerDiagnostic> nextEntries;
    nextEntries.reserve(pointers.size());
    for (const auto& pointer : pointers)
    {
        RRNGXPointerDiagnostic next {};
        next.name = pointer.name;
        next.present = pointer.address != nullptr;
        next.address = pointer.address;

        switch (pointer.kind)
        {
        case NGXPointerParameterKind::D3D11Resource:
            next.kind = RRNGXPointerKind::D3D11Resource;
            break;
        case NGXPointerParameterKind::D3D12Resource:
            next.kind = RRNGXPointerKind::D3D12Resource;
            break;
        default:
            next.kind = RRNGXPointerKind::OpaquePointer;
            break;
        }

        // Only exact D3D12 resource values are dereferenced. NGX void pointers
        // can also contain matrices, callbacks, or backend-specific objects.
        if (next.present && next.kind == RRNGXPointerKind::D3D12Resource)
        {
            const auto desc = static_cast<ID3D12Resource*>(pointer.address)->GetDesc();
            next.nativeWidth = desc.Width;
            next.nativeHeight = desc.Height;
            next.format = desc.Format;
            next.dimension = desc.Dimension;
            next.resourceFlags = desc.Flags;
            next.mipLevels = desc.MipLevels;
            next.arraySize = desc.DepthOrArraySize;
            next.sampleCount = desc.SampleDesc.Count;
        }

        nextEntries.push_back(std::move(next));
    }

    std::sort(nextEntries.begin(), nextEntries.end(),
              [](const RRNGXPointerDiagnostic& left, const RRNGXPointerDiagnostic& right) {
                  return left.name < right.name;
              });

    std::vector<RRNGXPointerDiagnostic> changedEntries;
    {
        std::scoped_lock lock(rrSignalTagMutex);
        for (auto& next : nextEntries)
        {
            const auto previous = std::find_if(
                rrNGXPointerDiagnostics.parameters.begin(), rrNGXPointerDiagnostics.parameters.end(),
                [&next](const RRNGXPointerDiagnostic& candidate) { return candidate.name == next.name; });

            if (previous != rrNGXPointerDiagnostics.parameters.end())
            {
                next.updateCount = previous->updateCount + 1;
                const bool changed =
                    previous->kind != next.kind ||
                    previous->present != next.present ||
                    previous->nativeWidth != next.nativeWidth ||
                    previous->nativeHeight != next.nativeHeight ||
                    previous->format != next.format ||
                    previous->dimension != next.dimension ||
                    previous->resourceFlags != next.resourceFlags ||
                    previous->mipLevels != next.mipLevels ||
                    previous->arraySize != next.arraySize ||
                    previous->sampleCount != next.sampleCount;
                if (changed)
                    changedEntries.push_back(next);
            }
            else
            {
                next.updateCount = 1;
                changedEntries.push_back(next);
            }
        }

        rrNGXPointerDiagnostics.tableInspectable = true;
        rrNGXPointerDiagnostics.parameters = nextEntries;
        ++rrNGXPointerDiagnostics.generation;
    }

    for (const auto& entry : changedEntries)
    {
        if (entry.kind != RRNGXPointerKind::D3D12Resource || !entry.present)
        {
            LOG_INFO("[RR_NGX_INVENTORY] key='{}', kind={}, ptr={}, present={}",
                     entry.name, GetNGXPointerKindName(entry.kind), entry.address, entry.present);
            continue;
        }

        const auto formatName = magic_enum::enum_name(entry.format);
        LOG_INFO(
            "[RR_NGX_INVENTORY] key='{}', kind={}, ptr={}, size={}x{}, format={}({}), "
            "dimension={}, mips={}, arrays={}, samples={}, resourceFlags={:#x}",
            entry.name, GetNGXPointerKindName(entry.kind), entry.address,
            entry.nativeWidth, entry.nativeHeight,
            formatName.empty() ? "UNKNOWN" : formatName, static_cast<uint32_t>(entry.format),
            static_cast<uint32_t>(entry.dimension), entry.mipLevels, entry.arraySize,
            entry.sampleCount, static_cast<uint32_t>(entry.resourceFlags));
    }
}

void StreamlineHooks::logRRNGXPointerDiagnostics()
{
    const auto diagnostics = getRRNGXPointerDiagnostics();
    LOG_INFO("[RR_NGX_INVENTORY] snapshot: inspectable={}, generation={}, pointerParameters={}",
             diagnostics.tableInspectable, diagnostics.generation, diagnostics.parameters.size());

    for (const auto& entry : diagnostics.parameters)
    {
        if (entry.kind != RRNGXPointerKind::D3D12Resource || !entry.present)
        {
            LOG_INFO("[RR_NGX_INVENTORY] snapshot key='{}': kind={}, ptr={}, present={}, updates={}",
                     entry.name, GetNGXPointerKindName(entry.kind), entry.address,
                     entry.present, entry.updateCount);
            continue;
        }

        const auto formatName = magic_enum::enum_name(entry.format);
        LOG_INFO(
            "[RR_NGX_INVENTORY] snapshot key='{}': kind={}, ptr={}, size={}x{}, "
            "format={}({}), dimension={}, updates={}",
            entry.name, GetNGXPointerKindName(entry.kind), entry.address,
            entry.nativeWidth, entry.nativeHeight,
            formatName.empty() ? "UNKNOWN" : formatName, static_cast<uint32_t>(entry.format),
            static_cast<uint32_t>(entry.dimension), entry.updateCount);
    }
}

void StreamlineHooks::resetRRInputInventoryDiagnostics()
{
    std::scoped_lock lock(rrSignalTagMutex);
    slTagInventoryDiagnostics = {};
    rrNGXPointerDiagnostics = {};
}

void StreamlineHooks::probeRRResourceTag(
    const sl::ResourceTag& tag, uint32_t frameIndex, uint32_t viewport,
    RRTagSource source)
{
    RRTaggedSignal signal;
    if (!TryGetRRTaggedSignal(tag.type, signal))
        return;

    RRTaggedResourceDiagnostic next =
        CaptureSLResourceTag(tag, frameIndex, viewport, source);

    RRTaggedResourceDiagnostic previous {};
    bool shouldLog = false;
    {
        std::scoped_lock lock(rrSignalTagMutex);
        auto& stored = rrSignalTagDiagnostics.resources[static_cast<size_t>(signal)];
        previous = stored;
        next.updateCount = previous.updateCount + 1;

        shouldLog = HasResourceMetadataChanged(previous, next);

        stored = next;
        auto& retainedResource = rrTaggedD3D12Resources[static_cast<size_t>(signal)];
        // eOnlyValidNow submitted through SetTag cannot be cached after that call
        // returns. A local ResourceTag passed directly to EvaluateFeature remains
        // inside its declaring call, however, and is retained only until the local
        // overlay is restored when that evaluation returns.
        retainedResource = next.present &&
                (next.lifecycle != sl::ResourceLifecycle::eOnlyValidNow ||
                 source == RRTagSource::EvaluateFeature)
            ? reinterpret_cast<ID3D12Resource*>(next.resourceAddress)
            : nullptr;
        ++rrSignalTagDiagnostics.generation;
    }

    if (!shouldLog)
        return;

    if (!next.present)
    {
        LOG_INFO("[RR_TAG_DIAG] {} {} frame={} cleared",
                 GetRRTagSourceName(source), getRRTaggedSignalName(signal), frameIndex);
        return;
    }

    const auto formatName = magic_enum::enum_name(next.format);
    const auto lifecycleName = magic_enum::enum_name(next.lifecycle);
    LOG_INFO(
        "[RR_TAG_DIAG] {} {} frame={} ptr={}, debugName='{}', native={}x{}, effective={}x{}, "
        "extent=[{},{}], format={}({}), dimension={}, mips={}, arrays={}, samples={}, "
        "resourceFlags={:#x}, state={:#x}, lifecycle={}, preferredFormat={} ({})",
        GetRRTagSourceName(source), getRRTaggedSignalName(signal), frameIndex,
        next.resourceAddress, next.debugName, next.nativeWidth, next.nativeHeight,
        next.effectiveWidth, next.effectiveHeight, next.extentLeft, next.extentTop,
        formatName.empty() ? "UNKNOWN" : formatName, static_cast<uint32_t>(next.format),
        static_cast<uint32_t>(next.dimension), next.mipLevels, next.arraySize, next.sampleCount,
        static_cast<uint32_t>(next.resourceFlags), next.state,
        lifecycleName.empty() ? "UNKNOWN" : lifecycleName,
        isRRPreferredTagFormat(signal, next.format), getRRPreferredTagFormat(signal));
}

void StreamlineHooks::logRRSignalTagDiagnostics(uint32_t renderWidth, uint32_t renderHeight)
{
    const RRSignalTagDiagnostics diagnostics = getRRSignalTagDiagnostics();
    LOG_INFO("[RR_TAG_DIAG] snapshot: generation={}, render={}x{}",
             diagnostics.generation, renderWidth, renderHeight);

    for (size_t i = 0; i < diagnostics.resources.size(); ++i)
    {
        const auto signal = static_cast<RRTaggedSignal>(i);
        const auto& diagnostic = diagnostics.resources[i];
        if (!diagnostic.observed)
        {
            LOG_INFO("[RR_TAG_DIAG] snapshot {}: not observed",
                     getRRTaggedSignalName(signal));
            continue;
        }

        if (!diagnostic.present)
        {
            LOG_INFO("[RR_TAG_DIAG] snapshot {}: cleared, updates={}",
                     getRRTaggedSignalName(signal), diagnostic.updateCount);
            continue;
        }

        const auto formatName = magic_enum::enum_name(diagnostic.format);
        LOG_INFO(
            "[RR_TAG_DIAG] snapshot {}: ptr={}, debugName='{}', effective={}x{}, native={}x{}, "
            "format={}({}), state={:#x}, updates={}, checkerboard={}, preferredFormat={} ({})",
            getRRTaggedSignalName(signal), diagnostic.resourceAddress,
            diagnostic.debugName,
            diagnostic.effectiveWidth, diagnostic.effectiveHeight,
            diagnostic.nativeWidth, diagnostic.nativeHeight,
            formatName.empty() ? "UNKNOWN" : formatName, static_cast<uint32_t>(diagnostic.format),
            diagnostic.state, diagnostic.updateCount,
            getRRCheckerboardAssessment(signal, diagnostic, renderWidth, renderHeight),
            isRRPreferredTagFormat(signal, diagnostic.format), getRRPreferredTagFormat(signal));
    }
}

// PCL
StreamlineHooks::PFN_slGetPluginFunction StreamlineHooks::o_pcl_slGetPluginFunction = nullptr;
StreamlineHooks::PFN_slOnPluginLoad StreamlineHooks::o_pcl_slOnPluginLoad = nullptr;
decltype(&slPCLSetMarker) StreamlineHooks::o_slPCLSetMarker = nullptr;

// Common
StreamlineHooks::PFN_slGetPluginFunction StreamlineHooks::o_common_slGetPluginFunction = nullptr;
StreamlineHooks::PFN_slOnPluginLoad StreamlineHooks::o_common_slOnPluginLoad = nullptr;
StreamlineHooks::PFN_slSetParameters_sl1 StreamlineHooks::o_common_slSetParameters_sl1 = nullptr;
StreamlineHooks::PFN_setVoid StreamlineHooks::o_setVoid = nullptr;

char* StreamlineHooks::trimStreamlineLog(const char* msg)
{
    int bracket_count = 0;

    char* result = (char*) malloc(strlen(msg) + 1);
    if (!result)
        return nullptr;

    strcpy(result, msg);

    size_t length = strlen(result);
    if (length > 0 && result[length - 1] == '\n')
    {
        result[length - 1] = '\0';
    }

    return result;
}

void StreamlineHooks::streamlineLogCallback(sl::LogType type, const char* msg)
{
    if (msg == nullptr)
        return;

    char* trimmed_msg = trimStreamlineLog(msg);
    if (trimmed_msg != nullptr)
    {
        switch (type)
        {
        case sl::LogType::eWarn:
            LOG_WARN("{}", trimmed_msg);
            break;
        case sl::LogType::eInfo:
            LOG_INFO("{}", trimmed_msg);
            break;
        case sl::LogType::eError:
            LOG_ERROR("{}", trimmed_msg);
            break;
        case sl::LogType::eCount:
            LOG_ERROR("{}", trimmed_msg);
            break;
        }

        free(trimmed_msg);
    }

    if (o_logCallback != nullptr)
        o_logCallback(type, msg);
}

sl::Result StreamlineHooks::hkslInit(const sl::Preferences& pref, uint64_t sdkVersion)
{
    LOG_FUNC();

    sl::Preferences localPref = pref;

    if (localPref.logMessageCallback != &streamlineLogCallback)
        o_logCallback = localPref.logMessageCallback;
    localPref.logLevel = sl::LogLevel::eCount;
    localPref.logMessageCallback = &streamlineLogCallback;

    // renderAPI is optional so need to be careful, should only matter for Vulkan
    renderApi = localPref.renderAPI;

    State::Instance().slFGInputs.reportEngineType(localPref.engine);

    // Treat engine type set in Streamline as ground truth
    if (localPref.engine == sl::EngineType::eUnreal)
        State::Instance().gameQuirks |= GameQuirk::ForceUnrealEngine;

    // bool hookSetTag =
    //     (State::Instance().activeFgInput == FGInput::Nukems || State::Instance().activeFgInput == FGInput::DLSSG);

    // if (hookSetTag)
    //     localPref->flags &= ~(sl::PreferenceFlags::eAllowOTA | sl::PreferenceFlags::eLoadDownloadedPlugins);

    return o_slInit(localPref, sdkVersion);
}

sl::Result StreamlineHooks::hkslSetTag(const sl::ViewportHandle& viewport, const sl::ResourceTag* tags,
                                       uint32_t numTags, sl::CommandBuffer* cmdBuffer)
{
    if (renderApi == sl::RenderAPI::eD3D11 || renderApi == sl::RenderAPI::eVulkan)
        return o_slSetTag(viewport, tags, numTags, cmdBuffer);

    if (renderApi == sl::RenderAPI::eCount)
        LOG_WARN("Incomplete Streamline hooks");

    if (tags == nullptr)
    {
        LOG_WARN("Game trying to remove a tag");
        return o_slSetTag(viewport, tags, numTags, cmdBuffer);
    }

    for (uint32_t i = 0; i < numTags; i++)
    {
        if (renderApi == sl::RenderAPI::eD3D12)
        {
            probeSLResourceTag(
                tags[i], UINT32_MAX, static_cast<uint32_t>(viewport),
                RRTagSource::SetTag);
            probeRRResourceTag(
                tags[i], UINT32_MAX, static_cast<uint32_t>(viewport),
                RRTagSource::SetTag);
        }

        if (tags[i].resource == nullptr || tags[i].resource->native == nullptr)
        {
            LOG_TRACE("Resource of type: {} is null, continuing", tags[i].type);
            continue;
        }

        // Cyberpunk hudless state fix for RDNA 2
        if (State::Instance().gameQuirks & GameQuirk::CyberpunkHudlessState &&
            tags[i].resource->state ==
                (D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE) &&
            tags[i].type == sl::kBufferTypeHUDLessColor)
        {
            tags[i].resource->state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
            LOG_TRACE("Changing hudless resource state");
        }

        if (State::Instance().activeFgInput == FGInput::DLSSG &&
            (tags[i].type == sl::kBufferTypeHUDLessColor || tags[i].type == sl::kBufferTypeDepth ||
             tags[i].type == sl::kBufferTypeHiResDepth || tags[i].type == sl::kBufferTypeLinearDepth ||
             tags[i].type == sl::kBufferTypeMotionVectors || tags[i].type == sl::kBufferTypeUIColorAndAlpha ||
             tags[i].type == sl::kBufferTypeBidirectionalDistortionField))
        {
            State::Instance().slFGInputs.reportResource(tags[i], (ID3D12GraphicsCommandList*) cmdBuffer, 0);
        }
        else if (State::Instance().activeFgInput == FGInput::Nukems)
        {
            LOG_TRACE("Tagging resource of type: {}", tags[i].type);
        }
    }

    auto result = o_slSetTag(viewport, tags, numTags, cmdBuffer);
    return result;
}

sl::Result StreamlineHooks::hkslSetTagForFrame(const sl::FrameToken& frame, const sl::ViewportHandle& viewport,
                                               const sl::ResourceTag* resources, uint32_t numResources,
                                               sl::CommandBuffer* cmdBuffer)
{
    if (renderApi == sl::RenderAPI::eD3D11 || renderApi == sl::RenderAPI::eVulkan)
        return o_slSetTagForFrame(frame, viewport, resources, numResources, cmdBuffer);

    if (renderApi == sl::RenderAPI::eCount)
        LOG_WARN("Incomplete Streamline hooks");

    if (resources == nullptr)
    {
        LOG_WARN("Game trying to remove a tag");
        return o_slSetTagForFrame(frame, viewport, resources, numResources, cmdBuffer);
    }

    LOG_DEBUG("frameIndex: {}", static_cast<uint32_t>(frame));

    for (uint32_t i = 0; i < numResources; i++)
    {
        if (renderApi == sl::RenderAPI::eD3D12)
        {
            probeSLResourceTag(
                resources[i], static_cast<uint32_t>(frame),
                static_cast<uint32_t>(viewport), RRTagSource::SetTagForFrame);
            probeRRResourceTag(
                resources[i], static_cast<uint32_t>(frame),
                static_cast<uint32_t>(viewport), RRTagSource::SetTagForFrame);
        }

        if (resources[i].resource == nullptr || resources[i].resource->native == nullptr)
        {
            LOG_TRACE("Resource of type: {} is null, continuing", resources[i].type);
            continue;
        }

        if (State::Instance().activeFgInput == FGInput::DLSSG &&
            (resources[i].type == sl::kBufferTypeHUDLessColor || resources[i].type == sl::kBufferTypeDepth ||
             resources[i].type == sl::kBufferTypeHiResDepth || resources[i].type == sl::kBufferTypeLinearDepth ||
             resources[i].type == sl::kBufferTypeMotionVectors || resources[i].type == sl::kBufferTypeUIColorAndAlpha ||
             resources[i].type == sl::kBufferTypeBidirectionalDistortionField))
        {
            State::Instance().slFGInputs.reportResource(resources[i], (ID3D12GraphicsCommandList*) cmdBuffer,
                                                        (uint32_t) frame);
        }
        else if (State::Instance().activeFgInput == FGInput::Nukems)
        {
            LOG_TRACE("Tagging resource of type: {}", resources[i].type);
        }
    }

    auto result = o_slSetTagForFrame(frame, viewport, resources, numResources, cmdBuffer);
    return result;
}

sl::Result StreamlineHooks::hkslEvaluateFeature(sl::Feature feature, const sl::FrameToken& frame,
                                                const sl::BaseStructure** inputs, uint32_t numInputs,
                                                sl::CommandBuffer* cmdBuffer)
{
    uint32_t activeViewport = UINT32_MAX;
    if (numInputs > 0 && inputs != nullptr)
    {
        for (uint32_t i = 0; i < numInputs; ++i)
        {
            if (inputs[i] != nullptr &&
                inputs[i]->structType == sl::ViewportHandle::s_structType)
            {
                activeViewport = static_cast<uint32_t>(
                    *reinterpret_cast<const sl::ViewportHandle*>(inputs[i]));
                break;
            }
        }
    }

    const ScopedRRActiveEvaluationFrame activeEvaluationFrame(
        static_cast<uint32_t>(frame), activeViewport);
    LOG_DEBUG("frameIndex: {}", static_cast<uint32_t>(frame));

    // ResourceTag inputs to slEvaluateFeature are local to this evaluation and
    // must not replace tags submitted through slSetTag/slSetTagForFrame. Overlay
    // them while the intercepted feature runs, then restore the global entries.
    constexpr size_t rrSignalCount = static_cast<size_t>(RRTaggedSignal::Count);
    std::array<bool, rrSignalCount> localTagOverrides {};
    std::array<RRTaggedResourceDiagnostic, rrSignalCount> savedGlobalDiagnostics {};
    std::array<Microsoft::WRL::ComPtr<ID3D12Resource>, rrSignalCount> savedGlobalResources {};
    if (renderApi == sl::RenderAPI::eD3D12 && numInputs > 0 && inputs != nullptr)
    {
        std::scoped_lock lock(rrSignalTagMutex);
        for (uint32_t i = 0; i < numInputs; ++i)
        {
            if (inputs[i] == nullptr || inputs[i]->structType != sl::ResourceTag::s_structType)
                continue;

            const auto* tag = reinterpret_cast<const sl::ResourceTag*>(inputs[i]);
            RRTaggedSignal signal;
            if (!TryGetRRTaggedSignal(tag->type, signal))
                continue;

            const size_t signalIndex = static_cast<size_t>(signal);
            if (localTagOverrides[signalIndex])
                continue;

            localTagOverrides[signalIndex] = true;
            savedGlobalDiagnostics[signalIndex] = rrSignalTagDiagnostics.resources[signalIndex];
            savedGlobalResources[signalIndex] = rrTaggedD3D12Resources[signalIndex];
        }
    }

    if (numInputs > 0 && inputs != nullptr)
    {
        for (uint32_t i = 0; i < numInputs; i++)
        {
            if (inputs[i] == nullptr)
                continue;

            if (inputs[i]->structType == sl::ResourceTag::s_structType)
            {
                auto tag = (const sl::ResourceTag*) inputs[i];

                if (renderApi == sl::RenderAPI::eD3D12)
                {
                    probeSLResourceTag(
                        *tag, static_cast<uint32_t>(frame), activeViewport,
                        RRTagSource::EvaluateFeature);
                    probeRRResourceTag(
                        *tag, static_cast<uint32_t>(frame), activeViewport,
                        RRTagSource::EvaluateFeature);
                }

                if (State::Instance().activeFgInput == FGInput::DLSSG &&
                    (tag->type == sl::kBufferTypeHUDLessColor || tag->type == sl::kBufferTypeDepth ||
                     tag->type == sl::kBufferTypeHiResDepth || tag->type == sl::kBufferTypeLinearDepth ||
                     tag->type == sl::kBufferTypeMotionVectors || tag->type == sl::kBufferTypeUIColorAndAlpha ||
                     tag->type == sl::kBufferTypeBidirectionalDistortionField))
                {
                    State::Instance().slFGInputs.reportResource(*tag, (ID3D12GraphicsCommandList*) cmdBuffer,
                                                                (uint32_t) frame);
                }
            }
        }
    }

    auto result = o_slEvaluateFeature(feature, frame, inputs, numInputs, cmdBuffer);

    if (renderApi == sl::RenderAPI::eD3D12)
    {
        std::scoped_lock lock(rrSignalTagMutex);
        bool resourcesChanged = false;
        for (size_t i = 0; i < rrSignalCount; ++i)
        {
            if (localTagOverrides[i])
            {
                rrSignalTagDiagnostics.resources[i] = std::move(savedGlobalDiagnostics[i]);
                rrTaggedD3D12Resources[i] = std::move(savedGlobalResources[i]);
                resourcesChanged = true;
            }

            const auto& diagnostic = rrSignalTagDiagnostics.resources[i];
            const bool belongsToEvaluation =
                diagnostic.viewport == activeViewport &&
                (diagnostic.frameIndex == UINT32_MAX ||
                 diagnostic.frameIndex == static_cast<uint32_t>(frame));
            if (belongsToEvaluation &&
                diagnostic.lifecycle == sl::ResourceLifecycle::eValidUntilEvaluate &&
                rrTaggedD3D12Resources[i])
            {
                // The declared lifetime ends as this evaluation returns. Keep
                // the last metadata for diagnostics, but release the retained
                // native resource so it cannot be rebound by a later frame.
                rrTaggedD3D12Resources[i].Reset();
                resourcesChanged = true;
            }
        }

        if (resourcesChanged)
            ++rrSignalTagDiagnostics.generation;
    }

    return result;
}

sl::Result StreamlineHooks::hkslAllocateResources(sl::CommandBuffer* cmdBuffer, sl::Feature feature,
                                                  const sl::ViewportHandle& viewport)
{
    LOG_FUNC();
    auto result = o_slAllocateResources(cmdBuffer, feature, viewport);
    return result;
}

sl::Result StreamlineHooks::hkslGetNativeInterface(void* proxyInterface, void** baseInterface)
{
    LOG_FUNC();
    auto result = o_slGetNativeInterface(proxyInterface, baseInterface);
    return result;
}

sl::Result StreamlineHooks::hkslSetD3DDevice(void* d3dDevice)
{
    LOG_FUNC();
    auto result = o_slSetD3DDevice(d3dDevice);
    return result;
}

void StreamlineHooks::streamlineLogCallback_sl1(sl1::LogType type, const char* msg)
{
    char* trimmed_msg = trimStreamlineLog(msg);

    if (trimmed_msg != nullptr)
    {
        switch (type)
        {
        case sl1::LogType::eLogTypeWarn:
            LOG_WARN("{}", trimmed_msg);
            break;
        case sl1::LogType::eLogTypeInfo:
            LOG_INFO("{}", trimmed_msg);
            break;
        case sl1::LogType::eLogTypeError:
            LOG_ERROR("{}", trimmed_msg);
            break;
        case sl1::LogType::eLogTypeCount:
            LOG_ERROR("{}", trimmed_msg);
            break;
        }

        free(trimmed_msg);
    }

    if (o_logCallback_sl1)
        o_logCallback_sl1(type, msg);
}

bool StreamlineHooks::hkslInit_sl1(const sl1::Preferences& pref, int applicationId)
{
    LOG_FUNC();

    sl1::Preferences localPref = pref;

    if (localPref.logMessageCallback != &streamlineLogCallback_sl1)
        o_logCallback_sl1 = localPref.logMessageCallback;
    localPref.logLevel = sl1::LogLevel::eLogLevelCount;
    localPref.logMessageCallback = &streamlineLogCallback_sl1;
    return o_slInit_sl1(localPref, applicationId);
}

void StreamlineHooks::hookSystemCaps(sl::param::IParameters* params)
{
    if (State::Instance().streamlineVersion.major > 1)
    {
        if (!systemCaps)
            sl::param::getPointerParam(params, sl::param::common::kSystemCaps, &systemCaps);
    }
    else if (State::Instance().streamlineVersion.major == 1)
    {
        // This should be Streamline 1.5 as previous versions don't even have slOnPluginLoad
        if (!systemCapsSl15)
        {
            LOG_TRACE(
                "Attempting to get system caps for Streamline v1, this could fail depending on the exact version");
            sl::param::getPointerParam(params, sl::param::common::kSystemCaps, &systemCapsSl15);
        }
    }
}

uint32_t StreamlineHooks::getSystemCapsArch()
{
    uint32_t highestArch = 0;

    if (!fakenvapi::isUsingFakenvapi() && State::Instance().isRunningOnNvidia)
    {
        if (State::Instance().streamlineVersion.major > 1)
        {
            if (systemCaps)
            {
                for (auto& adapter : systemCaps->adapters)
                {
                    if (adapter.architecture > highestArch)
                        highestArch = adapter.architecture;
                }
            }
        }
        else if (State::Instance().streamlineVersion.major == 1)
        {
            if (systemCapsSl15)
            {
                for (uint32_t i = 0; i < systemCapsSl15->gpuCount; i++)
                {
                    if (systemCapsSl15->architecture[i] > highestArch)
                        highestArch = systemCapsSl15->architecture[i];
                }
            }
        }
    }

    // By default spoof Pascal, gets Reflex but not DLSSD
    // Could be problematic if not using fakenvapi but nvapi might not be initialized yet
    if (highestArch == 0)
        highestArch = NV_GPU_ARCHITECTURE_GP100;

    return highestArch;
}

void StreamlineHooks::setArch(uint32_t arch)
{
    if (State::Instance().streamlineVersion.major > 1)
    {
        if (systemCaps)
        {
            for (uint32_t i = 0; i < systemCaps->gpuCount; i++)
            {
                systemCaps->adapters[i].architecture = arch;
                systemCaps->adapters[i].vendor = VendorId::Nvidia;
            }

            if (fakenvapi::isUsingFakenvapi() || !State::Instance().isRunningOnNvidia)
                systemCaps->driverVersionMajor = 999;

            systemCaps->hwsSupported = true;
        }
    }
    else if (State::Instance().streamlineVersion.major == 1)
    {
        if (systemCapsSl15)
        {
            for (uint32_t i = 0; i < systemCapsSl15->gpuCount; i++)
                systemCapsSl15->architecture[i] = arch;

            if (fakenvapi::isUsingFakenvapi() || !State::Instance().isRunningOnNvidia)
                systemCapsSl15->driverVersionMajor = 999;

            systemCapsSl15->hwSchedulingEnabled = true;
        }
    }
}

// Spoof arch based on feature and current arch
void StreamlineHooks::spoofArch(uint32_t currentArch, sl::Feature feature)
{
    constexpr uint32_t maxArch = 0xFFFFFFFF;

    // Don't change arch for DLSS/DLSSD with turing and above
    if (feature == sl::kFeatureDLSS)
    {
        if (currentArch < NV_GPU_ARCHITECTURE_TU100)
            return setArch(maxArch);
    }

    // Don't spoof DLSSD at all
    else if (feature == sl::kFeatureDLSS_RR)
    {
        return;
    }

    // Don't change arch for DLSSG with ada and above
    else if (feature == sl::kFeatureDLSS_G)
    {
        if (State::Instance().activeFgOutput == FGOutput::Nukems)
        {
            DLSSGMod::InitDLSSGMod_Dx12();
            DLSSGMod::InitDLSSGMod_Vulkan();
            if (!DLSSGMod::isDx12Available() && !DLSSGMod::isVulkanAvailable())
                return setArch(0);
        }

        if (currentArch < NV_GPU_ARCHITECTURE_AD100)
            return setArch(maxArch);
    }

    else if (feature == sl::kFeatureReflex || feature == sl::kFeaturePCL)
    {
        if (fakenvapi::isUsingFakenvapi())
            return setArch(maxArch);
    }
}

bool StreamlineHooks::hkdlss_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON,
                                            const char** pluginJSON)
{
    LOG_FUNC();

    // TODO: do it better than "static" and hoping for the best
    static std::string config;

    uint32_t currentArch = 0;
    if (Config::Instance()->StreamlineSpoofing.value_or_default())
    {
        hookSystemCaps(params);
        currentArch = getSystemCapsArch();
        spoofArch(currentArch, sl::kFeatureDLSS);
    }

    auto result = o_dlss_slOnPluginLoad(params, loaderJSON, pluginJSON);

    if (Config::Instance()->StreamlineSpoofing.value_or_default())
        setArch(currentArch);

    nlohmann::json configJson = nlohmann::json::parse(*pluginJSON);

    if (!State::Instance().isRunningOnNvidia || State::Instance().isPascalOrOlder)
    {
        if (Config::Instance()->VulkanExtensionSpoofing.value_or_default())
        {
            if (configJson.contains("/external/vk/instance/extensions"_json_pointer))
                configJson["external"]["vk"]["instance"]["extensions"].clear();

            if (configJson.contains("/external/vk/device/extensions"_json_pointer))
                configJson["external"]["vk"]["device"]["extensions"].clear();

            if (configJson.contains("/external/vk/device/1.2_features"_json_pointer))
                configJson["external"]["vk"]["device"]["1.2_features"].clear();

            if (configJson.contains("/external/vk/device/1.3_features"_json_pointer))
                configJson["external"]["vk"]["device"]["1.3_features"].clear();
        }
    }

    config = configJson.dump();

    *pluginJSON = config.c_str();

    return result;
}

sl::Result StreamlineHooks::hkslDLSSGetOptimalSettings(const sl::DLSSOptions& options,
                                                       sl::DLSSOptimalSettings& settings)
{
    static bool modesBroken = false;

    auto localOptions = options;

    if (localOptions.mode == sl::DLSSMode::eOff)
        modesBroken = true;

    if (modesBroken)
    {
        if (localOptions.mode == sl::DLSSMode::eMaxPerformance)
            localOptions.mode = sl::DLSSMode::eUltraPerformance;
        else if (localOptions.mode == sl::DLSSMode::eBalanced)
            localOptions.mode = sl::DLSSMode::eMaxPerformance;
        else if (localOptions.mode == sl::DLSSMode::eMaxQuality)
            localOptions.mode = sl::DLSSMode::eBalanced;
        else if (localOptions.mode == sl::DLSSMode::eUltraQuality)
            localOptions.mode = sl::DLSSMode::eMaxQuality;
        else if (localOptions.mode == sl::DLSSMode::eUltraPerformance)
            localOptions.mode = sl::DLSSMode::eDLAA;
    }

    return o_slDLSSGetOptimalSettings(localOptions, settings);
}

bool StreamlineHooks::hkdlssg_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON,
                                             const char** pluginJSON)
{
    LOG_FUNC();

    // TODO: do it better than "static" and hoping for the best
    static std::string config;

    bool shouldSpoofArch =
        Config::Instance()->StreamlineSpoofing.value_or_default() &&
        (Config::Instance()->FGInput == FGInput::Nukems || Config::Instance()->FGInput == FGInput::DLSSG);

    uint32_t currentArch = 0;
    if (shouldSpoofArch)
    {
        hookSystemCaps(params);
        currentArch = getSystemCapsArch();
        spoofArch(currentArch, sl::kFeatureDLSS_G);
    }

    auto result = o_dlssg_slOnPluginLoad(params, loaderJSON, pluginJSON);

    if (shouldSpoofArch)
        setArch(currentArch);

    nlohmann::json configJson = nlohmann::json::parse(*pluginJSON);

    // Kill the DLSSG streamline swapchain hooks
    if (State::Instance().activeFgInput == FGInput::DLSSG)
    {
        if (configJson.contains("/hooks"_json_pointer))
            configJson["hooks"].clear();

        if (configJson.contains("/exclusive_hooks"_json_pointer))
            configJson["exclusive_hooks"].clear();

        if (configJson.contains("/external/feature/tags"_json_pointer))
            configJson["external"]["feature"]["tags"].clear(); // We handle the DLSSG resources

        if (configJson.contains("/external/vk/device/queues/compute/count"_json_pointer))
            configJson["external"]["vk"]["device"]["queues"]["compute"]["count"] = 0;

        if (configJson.contains("/external/vk/device/queues/graphics/count"_json_pointer))
            configJson["external"]["vk"]["device"]["queues"]["graphics"]["count"] = 0;

        if (configJson.contains("/external/vk/device/1.2_features"_json_pointer))
            configJson["external"]["vk"]["device"]["1.2_features"].clear();

        if (configJson.contains("/external/vk/device/1.3_features"_json_pointer))
            configJson["external"]["vk"]["device"]["1.3_features"].clear();
    }

    if (State::Instance().activeFgInput == FGInput::DLSSG || State::Instance().activeFgInput == FGInput::Nukems)
    {
        if (configJson.contains("/vsync/supported"_json_pointer))
            configJson["vsync"]["supported"] = true; // disable eVSyncOffRequired

        if (configJson.contains("/external/hws/required"_json_pointer))
            configJson["external"]["hws"]["required"] = false; // disable eHardwareSchedulingRequired

        // if (configJson.contains("/external/vk/opticalflow/supported"_json_pointer))
        //     configJson["external"]["vk"]["opticalflow"]["supported"] = true;
    }

    if (Config::Instance()->VulkanExtensionSpoofing.value_or_default())
    {
        if (configJson.contains("/external/vk/instance/extensions"_json_pointer))
            configJson["external"]["vk"]["instance"]["extensions"].clear();

        if (configJson.contains("/external/vk/device/extensions"_json_pointer))
            configJson["external"]["vk"]["device"]["extensions"].clear();
    }

    config = configJson.dump();

    *pluginJSON = config.c_str();

    return result;
}

sl::Result StreamlineHooks::hkslSetConstants(const sl::Constants& values, const sl::FrameToken& frame,
                                             const sl::ViewportHandle& viewport)
{
    LOG_TRACE("called with frameIndex: {}, viewport: {}", (unsigned int) frame, (unsigned int) viewport);

    {
        std::scoped_lock lock(setConstantsMutex);
        State::Instance().slLastConstants = values;
        State::Instance().slLastConstantsFrame = static_cast<uint32_t>(frame);
        State::Instance().slLastConstantsViewport = static_cast<uint32_t>(viewport);
        State::Instance().slFGInputs.setConstants(values, (uint32_t) frame);
    }

    return o_slSetConstants(values, frame, viewport);
}

bool StreamlineHooks::hkcommon_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON,
                                              const char** pluginJSON)
{
    LOG_FUNC();

    // TODO: do it better than "static" and hoping for the best
    static std::string config;

    auto result = o_common_slOnPluginLoad(params, loaderJSON, pluginJSON);

    // Completely disables Streamline hooks
    // if (true)
    //{
    //    nlohmann::json configJson = nlohmann::json::parse(*pluginJSON);

    //    configJson["hooks"].clear();
    //    configJson["exclusive_hooks"].clear();

    //    config = configJson.dump();

    //    *pluginJSON = config.c_str();
    //}

    return result;
}

sl::Result StreamlineHooks::hkslDLSSGSetOptions(const sl::ViewportHandle& viewport, const sl::DLSSGOptions& options)
{
    // Make DLSSG auto always mean On
    sl::DLSSGOptions newOptions = options;
    newOptions.mode = newOptions.mode == sl::DLSSGMode::eOff ? sl::DLSSGMode::eOff : sl::DLSSGMode::eOn;

    if (State::Instance().swapchainApi == API::Vulkan)
    {
        // Only matters for Vulkan, DX doesn't use this delay
        if (options.mode != sl::DLSSGMode::eOff && !MenuOverlayBase::IsVisible())
            State::Instance().delayMenuRenderBy = 10;

        if (MenuOverlayBase::IsVisible())
        {
            newOptions.mode = sl::DLSSGMode::eOff;
            newOptions.flags |= sl::DLSSGFlags::eRetainResourcesWhenOff;
            ReflexHooks::setDlssgDetectedState(false);
        }
    }

    LOG_TRACE("DLSSG Modified Mode: {}", magic_enum::enum_name(newOptions.mode));

    return o_slDLSSGSetOptions(viewport, newOptions);
}

sl::Result StreamlineHooks::hkslDLSSGGetState(const sl::ViewportHandle& viewport, sl::DLSSGState& state,
                                              const sl::DLSSGOptions* options)
{
    auto result = o_slDLSSGGetState(viewport, state, options);

    auto& s = State::Instance();

    if (s.activeFgInput == FGInput::DLSSG)
    {
        auto fg = s.currentFG;

        if (fg != nullptr)
        {
            if (options != nullptr && options->flags & sl::DLSSGFlags::eRequestVRAMEstimate)
                state.estimatedVRAMUsageInBytes = static_cast<uint64_t>(256 * 1024) * 1024;

            if (fg->IsActive() && !fg->IsPaused())
            {
                state.numFramesActuallyPresented = fg->GetInterpolatedFrameCount() + 1;
            }
            else
            {
                state.numFramesActuallyPresented = 1;
            }
        }
        else
        {
            state.numFramesActuallyPresented = 1;
        }

        state.numFramesToGenerateMax = 1;

        LOG_DEBUG("Status: {}, numFramesActuallyPresented: {}", magic_enum::enum_name(state.status),
                  state.numFramesActuallyPresented);
    }

    return result;
}

bool StreamlineHooks::hkreflex_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON,
                                              const char** pluginJSON)
{
    LOG_FUNC();

    // TODO: do it better than "static" and hoping for the best
    static std::string config;

    uint32_t currentArch = 0;
    if (Config::Instance()->StreamlineSpoofing.value_or_default())
    {
        hookSystemCaps(params);
        currentArch = getSystemCapsArch();
        spoofArch(currentArch, sl::kFeatureReflex);
    }

    auto result = o_reflex_slOnPluginLoad(params, loaderJSON, pluginJSON);

    if (Config::Instance()->StreamlineSpoofing.value_or_default())
        setArch(currentArch);

    nlohmann::json configJson = nlohmann::json::parse(*pluginJSON);

    if (!State::Instance().isRunningOnNvidia && Config::Instance()->VulkanExtensionSpoofing.value_or_default())
    {
        if (configJson.contains("/external/vk/instance/extensions"_json_pointer))
            configJson["external"]["vk"]["instance"]["extensions"].clear();

        if (configJson.contains("/external/vk/device/extensions"_json_pointer))
            configJson["external"]["vk"]["device"]["extensions"].clear();

        if (configJson.contains("/external/vk/device/1.2_features"_json_pointer))
            configJson["external"]["vk"]["device"]["1.2_features"].clear();

        if (configJson.contains("/external/vk/device/1.3_features"_json_pointer))
            configJson["external"]["vk"]["device"]["1.3_features"].clear();
    }

    config = configJson.dump();

    *pluginJSON = config.c_str();

    return result;
}

sl::Result StreamlineHooks::hkslReflexSetOptions(const sl::ReflexOptions& options)
{
    reflexGamesLastMode = options.mode;

    sl::ReflexOptions newOptions = options;

    if (Config::Instance()->FN_ForceReflex == 2)
        newOptions.mode = sl::ReflexMode::eLowLatencyWithBoost;

    // Will cause a pink screen when used with DLSSG
    // if (Config::Instance()->FN_ForceReflex == 1)
    //     newOptions.mode = sl::ReflexMode::eOff;

    return o_slReflexSetOptions(newOptions);
}

void* StreamlineHooks::hkdlss_slGetPluginFunction(const char* functionName)
{
    LOG_DEBUG("{}", functionName);

    if (strcmp(functionName, "slOnPluginLoad") == 0)
    {
        o_dlss_slOnPluginLoad = (PFN_slOnPluginLoad) o_dlss_slGetPluginFunction(functionName);
        return &hkdlss_slOnPluginLoad;
    }

    if (strcmp(functionName, "slDLSSGetOptimalSettings") == 0 &&
        State::Instance().gameQuirks & GameQuirk::PregmataFixDLSSModes)
    {
        o_slDLSSGetOptimalSettings = (decltype(&slDLSSGetOptimalSettings)) o_dlss_slGetPluginFunction(functionName);
        return &hkslDLSSGetOptimalSettings;
    }

    return o_dlss_slGetPluginFunction(functionName);
}

void* StreamlineHooks::hkdlssg_slGetPluginFunction(const char* functionName)
{
    // LOG_DEBUG("{}", functionName);

    if (strcmp(functionName, "slOnPluginLoad") == 0)
    {
        o_dlssg_slOnPluginLoad = (PFN_slOnPluginLoad) o_dlssg_slGetPluginFunction(functionName);
        return &hkdlssg_slOnPluginLoad;
    }

    if (strcmp(functionName, "slDLSSGSetOptions") == 0)
    {
        // Give steam overlay the original as it seems to be hooking it
        auto steamOverlay = KernelBaseProxy::GetModuleHandleA_()("gameoverlayrenderer64.dll");
        if (steamOverlay != nullptr)
        {
            if (HMODULE callerModule = Util::GetCallerModule(_ReturnAddress()); callerModule == steamOverlay)
            {
                return o_dlssg_slGetPluginFunction(functionName);
            }
        }

        o_slDLSSGSetOptions = (decltype(&slDLSSGSetOptions)) o_dlssg_slGetPluginFunction(functionName);
        return &hkslDLSSGSetOptions;
    }

    if (strcmp(functionName, "slDLSSGGetState") == 0)
    {
        // Give steam overlay the original as it seems to be hooking it
        auto steamOverlay = KernelBaseProxy::GetModuleHandleA_()("gameoverlayrenderer64.dll");
        if (steamOverlay != nullptr)
        {
            if (HMODULE callerModule = Util::GetCallerModule(_ReturnAddress()); callerModule == steamOverlay)
            {
                return o_dlssg_slGetPluginFunction(functionName);
            }
        }

        o_slDLSSGGetState = (decltype(&slDLSSGGetState)) o_dlssg_slGetPluginFunction(functionName);
        return &hkslDLSSGGetState;
    }

    return o_dlssg_slGetPluginFunction(functionName);
}

bool StreamlineHooks::hkreflex_slSetConstants_sl1(const void* data, uint32_t frameIndex, uint32_t id)
{
    // Streamline v1's version of slReflexSetOptions + slPCLSetMarker
    static sl1::ReflexConstants constants {};
    constants = *(const sl1::ReflexConstants*) data;

    reflexGamesLastMode = (sl::ReflexMode) constants.mode;

    LOG_DEBUG("mode: {}, frameIndex: {}, id: {}", (uint32_t) constants.mode, frameIndex, id);

    if (Config::Instance()->FN_ForceReflex == 2)
        constants.mode = sl1::ReflexMode::eReflexModeLowLatencyWithBoost;

    // Will cause a pink screen when used with DLSSG
    // else if (Config::Instance()->FN_ForceReflex == 1)
    //     constants.mode = sl1::ReflexMode::eReflexModeOff;

    return o_reflex_slSetConstants_sl1(&constants, frameIndex, id);
}

void* StreamlineHooks::hkreflex_slGetPluginFunction(const char* functionName)
{
    // LOG_DEBUG("{}", functionName);

    if (strcmp(functionName, "slSetConstants") == 0 && State::Instance().streamlineVersion.major == 1)
    {
        o_reflex_slSetConstants_sl1 = (PFN_slSetConstants_sl1) o_reflex_slGetPluginFunction(functionName);
        return &hkreflex_slSetConstants_sl1;
    }

    if (strcmp(functionName, "slOnPluginLoad") == 0)
    {
        o_reflex_slOnPluginLoad = (PFN_slOnPluginLoad) o_reflex_slGetPluginFunction(functionName);
        return &hkreflex_slOnPluginLoad;
    }

    if (strcmp(functionName, "slReflexSetOptions") == 0)
    {
        o_slReflexSetOptions = (decltype(&slReflexSetOptions)) o_reflex_slGetPluginFunction(functionName);
        return &hkslReflexSetOptions;
    }

    return o_reflex_slGetPluginFunction(functionName);
}

sl::Result StreamlineHooks::hkslPCLSetMarker(sl::PCLMarker marker, const sl::FrameToken& frame)
{
    // HACK for broken games
    static uint64_t last_simulation_end_id = 0;
    if (marker == sl::PCLMarker::eSimulationEnd)
    {
        last_simulation_end_id = frame;
    }

    if (marker == sl::PCLMarker::eSimulationStart && last_simulation_end_id >= frame && o_slGetNewFrameToken)
    {
        const uint64_t correction_offset = last_simulation_end_id - frame + 1;
        uint32_t newFrameId = static_cast<uint32_t>(frame + correction_offset);

        sl::FrameToken* newFramePointer {};
        auto result = o_slGetNewFrameToken(newFramePointer, &newFrameId);

        LOG_WARN("Simulation start marker sent after end marker, offset: {}", correction_offset);

        result = o_slPCLSetMarker(marker, *newFramePointer);
        return result;
    }

    return o_slPCLSetMarker(marker, frame);
}

bool StreamlineHooks::hkpcl_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON,
                                           const char** pluginJSON)
{
    LOG_FUNC();

    uint32_t currentArch = 0;
    if (Config::Instance()->StreamlineSpoofing.value_or_default())
    {
        hookSystemCaps(params);
        currentArch = getSystemCapsArch();
        spoofArch(currentArch, sl::kFeaturePCL);
    }

    auto result = o_pcl_slOnPluginLoad(params, loaderJSON, pluginJSON);

    if (Config::Instance()->StreamlineSpoofing.value_or_default())
        setArch(currentArch);

    return result;
}

void* StreamlineHooks::hkpcl_slGetPluginFunction(const char* functionName)
{
    // LOG_DEBUG("{}", functionName);

    if (strcmp(functionName, "slPCLSetMarker") == 0 && State::Instance().gameQuirks & GameQuirk::FixSlSimulationMarkers)
    {
        o_slPCLSetMarker = (decltype(&slPCLSetMarker)) o_pcl_slGetPluginFunction(functionName);
        return &hkslPCLSetMarker;
    }

    if (strcmp(functionName, "slOnPluginLoad") == 0)
    {
        o_pcl_slOnPluginLoad = (PFN_slOnPluginLoad) o_pcl_slGetPluginFunction(functionName);
        return &hkpcl_slOnPluginLoad;
    }

    return o_pcl_slGetPluginFunction(functionName);
}

bool StreamlineHooks::hk_setVoid(void* self, const char* key, void** value)
{
    // LOG_DEBUG("{}", key);

    if (strcmp(key, sl::param::common::kSystemCaps) == 0)
    {
        LOG_TRACE("Attempting to change system caps for Streamline v1, this could fail depending on the exact version");

        // SystemCapsSl15 is not entirely correct for Streamline 1.3
        // But we here only use the beginning that matches + extra
        auto caps = (SystemCapsSl15*) value;

        if (caps)
        {
            caps->gpuCount = 1;
            caps->architecture[0] = UINT_MAX;
            caps->driverVersionMajor = 999;

            // HAGS
            *((char*) value + 56) = (char) 0x01;
        }
    }

    return o_setVoid(self, key, value);
}

void StreamlineHooks::hkcommon_slSetParameters_sl1(void* params)
{
    LOG_FUNC();

    if (o_setVoid == nullptr && params)
    {
        void** vtable = *(void***) params;

        // It's flipped, 0 -> set void*, 7 -> get void*
        o_setVoid = (PFN_setVoid) vtable[0];

        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        if (o_setVoid != nullptr)
            DetourAttach(&(PVOID&) o_setVoid, hk_setVoid);

        DetourTransactionCommit();
    }

    o_common_slSetParameters_sl1(params);
}

void* StreamlineHooks::hkcommon_slGetPluginFunction(const char* functionName)
{
    // LOG_DEBUG("{}", functionName);

    if (strcmp(functionName, "slOnPluginLoad") == 0)
    {
        o_common_slOnPluginLoad = (PFN_slOnPluginLoad) o_common_slGetPluginFunction(functionName);
        return &hkcommon_slOnPluginLoad;
    }

    // Used around Streamline v1.3, as 1.5 doesn't seem to have it anymore
    if (strcmp(functionName, "slSetParameters") == 0)
    {
        o_common_slSetParameters_sl1 = (PFN_slSetParameters_sl1) o_common_slGetPluginFunction(functionName);
        return &hkcommon_slSetParameters_sl1;
    }

    return o_common_slGetPluginFunction(functionName);
}

void StreamlineHooks::updateForceReflex()
{
    // Not needed for Streamline v1 as slSetConstants is sent every frame
    if (o_slReflexSetOptions)
    {
        sl::ReflexOptions options;

        auto forceReflex = Config::Instance()->FN_ForceReflex.value_or_default();

        if (forceReflex == 2)
            options.mode = sl::ReflexMode::eLowLatencyWithBoost;
        else if (forceReflex == 1)
            options.mode = sl::ReflexMode::eOff;
        else if (forceReflex == 0)
            options.mode = reflexGamesLastMode;

        auto result = o_slReflexSetOptions(options);
    }
}

// SL INTERPOSER

void StreamlineHooks::unhookInterposer()
{
    LOG_FUNC();

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_slSetTag)
    {
        DetourDetach(&(PVOID&) o_slSetTag, hkslSetTag);
        o_slSetTag = nullptr;
    }

    if (o_slSetTagForFrame)
    {
        DetourDetach(&(PVOID&) o_slSetTagForFrame, hkslSetTagForFrame);
        o_slSetTagForFrame = nullptr;
    }

    if (o_slInit)
    {
        DetourDetach(&(PVOID&) o_slInit, hkslInit);
        o_slInit = nullptr;
    }

    if (o_slInit_sl1)
    {
        DetourDetach(&(PVOID&) o_slInit_sl1, hkslInit_sl1);
        o_slInit_sl1 = nullptr;
    }

    o_logCallback_sl1 = nullptr;
    o_logCallback = nullptr;

    DetourTransactionCommit();
}

// Call it just after sl.interposer's load or if sl.interposer is already loaded
void StreamlineHooks::hookInterposer(HMODULE slInterposer)
{
    LOG_FUNC();

    if (!slInterposer)
    {
        LOG_WARN("Streamline module in NULL");
        return;
    }

    // Interposer needs this or it might end in an infinite loop calling itself
    static HMODULE last_slInterposer = nullptr;

    if (last_slInterposer == slInterposer)
        return;

    last_slInterposer = slInterposer;

    // Looks like when reading DLL version load methods are called
    // To prevent loops disabling checks for sl.interposer.dll
    State::DisableChecks(7, "sl.interposer");

    if (o_slSetTag || o_slInit || o_slInit_sl1)
        unhookInterposer();

    {
        char dllPath[MAX_PATH];
        GetModuleFileNameA(slInterposer, dllPath, MAX_PATH);

        LOG_TRACE("slInterposer path: {}", dllPath);

        Util::version_t sl_version;
        Util::GetDLLVersion(string_to_wstring(dllPath), &sl_version);

        State::Instance().streamlineVersion.major = sl_version.major;
        State::Instance().streamlineVersion.minor = sl_version.minor;
        State::Instance().streamlineVersion.patch = sl_version.patch;

        LOG_INFO("Streamline version: {}.{}.{}", sl_version.major, sl_version.minor, sl_version.patch);

        if (sl_version.major >= 2)
        {
            o_slSetTag =
                reinterpret_cast<decltype(&slSetTag)>(KernelBaseProxy::GetProcAddress_()(slInterposer, "slSetTag"));
            o_slSetTagForFrame = reinterpret_cast<decltype(&slSetTagForFrame)>(
                KernelBaseProxy::GetProcAddress_()(slInterposer, "slSetTagForFrame"));
            o_slInit = reinterpret_cast<decltype(&slInit)>(KernelBaseProxy::GetProcAddress_()(slInterposer, "slInit"));
            o_slEvaluateFeature = reinterpret_cast<decltype(&slEvaluateFeature)>(
                KernelBaseProxy::GetProcAddress_()(slInterposer, "slEvaluateFeature"));
            o_slAllocateResources = reinterpret_cast<decltype(&slAllocateResources)>(
                KernelBaseProxy::GetProcAddress_()(slInterposer, "slAllocateResources"));
            o_slSetConstants = reinterpret_cast<decltype(&slSetConstants)>(
                KernelBaseProxy::GetProcAddress_()(slInterposer, "slSetConstants"));
            o_slGetNativeInterface = reinterpret_cast<decltype(&slGetNativeInterface)>(
                KernelBaseProxy::GetProcAddress_()(slInterposer, "slGetNativeInterface"));
            o_slSetD3DDevice = reinterpret_cast<decltype(&slSetD3DDevice)>(
                KernelBaseProxy::GetProcAddress_()(slInterposer, "slSetD3DDevice"));
            o_slGetNewFrameToken = reinterpret_cast<decltype(&slGetNewFrameToken)>(
                KernelBaseProxy::GetProcAddress_()(slInterposer, "slGetNewFrameToken")); // Not hooked

            if (o_slInit != nullptr)
            {
                LOG_TRACE("Hooking v2");
                DetourTransactionBegin();
                DetourUpdateThread(GetCurrentThread());

                DetourAttach(&(PVOID&) o_slInit, hkslInit);

                // RR signal discovery must remain available even when frame generation is disabled.
                // The hooks only inspect DX12 tag metadata and forward the original calls unchanged.
                if (o_slSetTag != nullptr)
                    DetourAttach(&(PVOID&) o_slSetTag, hkslSetTag);

                if (o_slSetTagForFrame != nullptr)
                    DetourAttach(&(PVOID&) o_slSetTagForFrame, hkslSetTagForFrame);

                // Allow constants to be hooked without DLSSG
                if (o_slSetConstants != nullptr)
                    DetourAttach(&(PVOID&) o_slSetConstants, hkslSetConstants);

                if (o_slEvaluateFeature != nullptr)
                    DetourAttach(&(PVOID&) o_slEvaluateFeature, hkslEvaluateFeature);

                // if (o_slAllocateResources != nullptr)
                //     DetourAttach(&(PVOID&) o_slAllocateResources, hkslAllocateResources);

                // if (o_slGetNativeInterface != nullptr)
                //     DetourAttach(&(PVOID&) o_slGetNativeInterface, hkslGetNativeInterface);

                // if (o_slSetD3DDevice != nullptr)
                //     DetourAttach(&(PVOID&) o_slSetD3DDevice, hkslSetD3DDevice);

                DetourTransactionCommit();
            }
        }
        else if (sl_version.major == 1)
        {
            if (State::Instance().activeFgInput == FGInput::DLSSG)
                State::Instance().activeFgInput = FGInput::NoFG;

            o_slInit_sl1 =
                reinterpret_cast<decltype(&sl1::slInit)>(KernelBaseProxy::GetProcAddress_()(slInterposer, "slInit"));

            if (o_slInit_sl1)
            {
                LOG_TRACE("Hooking v1");
                DetourTransactionBegin();
                DetourUpdateThread(GetCurrentThread());

                DetourAttach(&(PVOID&) o_slInit_sl1, hkslInit_sl1);

                DetourTransactionCommit();
            }
        }
    }

    State::EnableChecks(7);
}

// SL DLSS

void StreamlineHooks::unhookDlss()
{
    LOG_FUNC();

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_dlss_slGetPluginFunction)
    {
        DetourDetach(&(PVOID&) o_dlss_slGetPluginFunction, hkdlss_slGetPluginFunction);
        o_dlss_slGetPluginFunction = nullptr;
    }

    DetourTransactionCommit();
}

void StreamlineHooks::hookDlss(HMODULE slDlss)
{
    LOG_FUNC();

    if (!slDlss)
    {
        LOG_WARN("Dlss module in NULL");
        return;
    }

    if (o_dlss_slGetPluginFunction)
        unhookDlss();

    o_dlss_slGetPluginFunction =
        reinterpret_cast<PFN_slGetPluginFunction>(KernelBaseProxy::GetProcAddress_()(slDlss, "slGetPluginFunction"));

    if (o_dlss_slGetPluginFunction != nullptr)
    {
        LOG_TRACE("Hooking slGetPluginFunction in sl.dlss");
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        DetourAttach(&(PVOID&) o_dlss_slGetPluginFunction, hkdlss_slGetPluginFunction);

        DetourTransactionCommit();
    }
}

// SL DLSSG

void StreamlineHooks::unhookDlssg()
{
    LOG_FUNC();

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_dlssg_slGetPluginFunction)
    {
        DetourDetach(&(PVOID&) o_dlssg_slGetPluginFunction, hkdlssg_slGetPluginFunction);
        o_dlssg_slGetPluginFunction = nullptr;
    }

    DetourTransactionCommit();
}

void StreamlineHooks::hookDlssg(HMODULE slDlssg)
{
    LOG_FUNC();

    if (!slDlssg)
    {
        LOG_WARN("Dlssg module in NULL");
        return;
    }

    if (o_dlssg_slGetPluginFunction)
        unhookDlssg();

    o_dlssg_slGetPluginFunction =
        reinterpret_cast<PFN_slGetPluginFunction>(KernelBaseProxy::GetProcAddress_()(slDlssg, "slGetPluginFunction"));

    if (o_dlssg_slGetPluginFunction != nullptr)
    {
        LOG_TRACE("Hooking slGetPluginFunction in sl.dlssg");
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        DetourAttach(&(PVOID&) o_dlssg_slGetPluginFunction, hkdlssg_slGetPluginFunction);

        DetourTransactionCommit();
    }
}

// SL REFLEX

void StreamlineHooks::unhookReflex()
{
    LOG_FUNC();

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_reflex_slGetPluginFunction)
    {
        DetourDetach(&(PVOID&) o_reflex_slGetPluginFunction, hkreflex_slGetPluginFunction);
        o_reflex_slGetPluginFunction = nullptr;
    }

    DetourTransactionCommit();
}

void StreamlineHooks::hookReflex(HMODULE slReflex)
{
    LOG_FUNC();

    if (!slReflex)
    {
        LOG_WARN("Reflex module in NULL");
        return;
    }

    if (o_reflex_slGetPluginFunction)
        unhookReflex();

    o_reflex_slGetPluginFunction =
        reinterpret_cast<PFN_slGetPluginFunction>(KernelBaseProxy::GetProcAddress_()(slReflex, "slGetPluginFunction"));

    if (o_reflex_slGetPluginFunction != nullptr)
    {
        LOG_TRACE("Hooking slGetPluginFunction in sl.reflex");
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        DetourAttach(&(PVOID&) o_reflex_slGetPluginFunction, hkreflex_slGetPluginFunction);

        DetourTransactionCommit();
    }
}

// SL PCL

void StreamlineHooks::unhookPcl()
{
    LOG_FUNC();

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_pcl_slGetPluginFunction)
    {
        DetourDetach(&(PVOID&) o_pcl_slGetPluginFunction, hkpcl_slGetPluginFunction);
        o_pcl_slGetPluginFunction = nullptr;
    }

    DetourTransactionCommit();
}

void StreamlineHooks::hookPcl(HMODULE slPcl)
{
    LOG_FUNC();

    if (!slPcl)
    {
        LOG_WARN("Pcl module in NULL");
        return;
    }

    if (o_pcl_slGetPluginFunction)
        unhookPcl();

    o_pcl_slGetPluginFunction =
        reinterpret_cast<PFN_slGetPluginFunction>(KernelBaseProxy::GetProcAddress_()(slPcl, "slGetPluginFunction"));

    if (o_pcl_slGetPluginFunction != nullptr)
    {
        LOG_TRACE("Hooking slGetPluginFunction in sl.pcl");
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        DetourAttach(&(PVOID&) o_pcl_slGetPluginFunction, hkpcl_slGetPluginFunction);

        DetourTransactionCommit();
    }
}

// SL COMMON

void StreamlineHooks::unhookCommon()
{
    LOG_FUNC();

    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (o_common_slGetPluginFunction)
    {
        DetourDetach(&(PVOID&) o_common_slGetPluginFunction, hkcommon_slGetPluginFunction);
        o_common_slGetPluginFunction = nullptr;
    }

    systemCaps = nullptr;
    systemCapsSl15 = nullptr;

    DetourTransactionCommit();
}

void StreamlineHooks::hookCommon(HMODULE slCommon)
{
    LOG_FUNC();

    if (!slCommon)
    {
        LOG_WARN("Common module in NULL");
        return;
    }

    if (o_common_slGetPluginFunction)
        unhookCommon();

    o_common_slGetPluginFunction =
        reinterpret_cast<PFN_slGetPluginFunction>(KernelBaseProxy::GetProcAddress_()(slCommon, "slGetPluginFunction"));

    if (o_common_slGetPluginFunction != nullptr)
    {
        LOG_TRACE("Hooking slGetPluginFunction in sl.common");
        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());

        DetourAttach(&(PVOID&) o_common_slGetPluginFunction, hkcommon_slGetPluginFunction);

        DetourTransactionCommit();
    }
}

bool StreamlineHooks::isInterposerHooked() { return o_slInit != nullptr || o_slInit_sl1 != nullptr; }

bool StreamlineHooks::isDlssHooked() { return o_dlss_slGetPluginFunction != nullptr; }

bool StreamlineHooks::isDlssgHooked() { return o_dlssg_slGetPluginFunction != nullptr; }

bool StreamlineHooks::isCommonHooked() { return o_common_slGetPluginFunction != nullptr; }

bool StreamlineHooks::isSetConstantsHooked() { return o_slSetConstants != nullptr; }

bool StreamlineHooks::isPclHooked() { return o_pcl_slGetPluginFunction != nullptr; }

bool StreamlineHooks::isReflexHooked() { return o_reflex_slGetPluginFunction != nullptr; }
