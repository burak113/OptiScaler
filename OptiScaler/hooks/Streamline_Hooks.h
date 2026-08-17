#pragma once
#include "SysUtils.h"

#include <sl.h>
#include <sl1.h>
#include <sl_dlss_g.h>
#include <sl_dlss.h>
#include <sl_pcl.h>
#include <sl_reflex.h>

#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <cstdint>
#include <string>
#include <vector>
#include "include/sl.param/parameters.h"

#include "Hook_Utils.h"

struct NVSDK_NGX_Parameter;

struct Adapter
{
    LUID id {};
    VendorId::Value vendor {};
    uint32_t bit; // in the adapter bit-mask
    uint32_t architecture {};
    uint32_t implementation {};
    uint32_t revision {};
    uint32_t deviceId {};
    void* nativeInterface {};
};

constexpr uint32_t kMaxNumSupportedGPUs = 8;

struct SystemCaps
{
    uint32_t gpuCount {};
    uint32_t osVersionMajor {};
    uint32_t osVersionMinor {};
    uint32_t osVersionBuild {};
    uint32_t driverVersionMajor {};
    uint32_t driverVersionMinor {};
    Adapter adapters[kMaxNumSupportedGPUs] {};
    uint32_t gpuLoad[kMaxNumSupportedGPUs] {}; // percentage
    bool hwsSupported {};                      // OS wide setting, not per adapter
    bool laptopDevice {};
};

struct SystemCapsSl15
{
    uint32_t gpuCount {};
    uint32_t osVersionMajor {};
    uint32_t osVersionMinor {};
    uint32_t osVersionBuild {};
    uint32_t driverVersionMajor {};
    uint32_t driverVersionMinor {};
    uint32_t architecture[kMaxNumSupportedGPUs] {};
    uint32_t implementation[kMaxNumSupportedGPUs] {};
    uint32_t revision[kMaxNumSupportedGPUs] {};
    uint32_t gpuLoad[kMaxNumSupportedGPUs] {}; // percentage
    bool hwSchedulingEnabled {};
};

enum class RRTaggedSignal : uint32_t
{
    NormalRoughness,
    Emissive,
    SpecularMotionVectors,
    ReflectionMotionVectors,
    SpecularHitDistance,
    SpecularRayDirectionHitDistance,
    DiffuseNoisy,
    DiffuseDenoised,
    SpecularNoisy,
    SpecularDenoised,
    ShadowNoisy,
    ShadowDenoised,
    AmbientOcclusionNoisy,
    AmbientOcclusionDenoised,
    ShadowHint,
    ReflectionHint,
    Count
};

enum class RRTagSource : uint32_t
{
    SetTag,
    SetTagForFrame,
    EvaluateFeature
};

struct RRTaggedResourceDiagnostic
{
    bool observed = false;
    bool present = false;
    bool usesExtent = false;
    std::string debugName;
    void* resourceAddress = nullptr;
    uint64_t nativeWidth = 0;
    uint32_t nativeHeight = 0;
    uint32_t effectiveWidth = 0;
    uint32_t effectiveHeight = 0;
    uint32_t extentLeft = 0;
    uint32_t extentTop = 0;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    D3D12_RESOURCE_DIMENSION dimension = D3D12_RESOURCE_DIMENSION_UNKNOWN;
    D3D12_RESOURCE_FLAGS resourceFlags = D3D12_RESOURCE_FLAG_NONE;
    uint32_t mipLevels = 0;
    uint32_t arraySize = 0;
    uint32_t sampleCount = 0;
    uint32_t state = UINT32_MAX;
    sl::ResourceLifecycle lifecycle = sl::ResourceLifecycle::eOnlyValidNow;
    uint32_t frameIndex = UINT32_MAX;
    uint32_t viewport = UINT32_MAX;
    RRTagSource source = RRTagSource::SetTag;
    uint64_t updateCount = 0;
};

struct RRSignalTagDiagnostics
{
    std::array<RRTaggedResourceDiagnostic, static_cast<size_t>(RRTaggedSignal::Count)> resources {};
    uint64_t generation = 0;
};

struct RRTaggedD3D12ResourceSnapshot
{
    RRTaggedResourceDiagnostic diagnostic {};
    Microsoft::WRL::ComPtr<ID3D12Resource> resource;
};

struct RRD3D12SignalTagSnapshot
{
    std::array<RRTaggedD3D12ResourceSnapshot,
               static_cast<size_t>(RRTaggedSignal::Count)> resources {};
    uint64_t generation = 0;
    uint32_t activeEvaluationFrame = UINT32_MAX;
    uint32_t activeEvaluationViewport = UINT32_MAX;
};

struct SLConstantsSnapshot
{
    sl::Constants constants {};
    uint32_t frameIndex = UINT32_MAX;
    uint32_t viewport = UINT32_MAX;
};

struct SLTaggedResourceInventoryEntry
{
    sl::BufferType type = UINT32_MAX;
    RRTaggedResourceDiagnostic resource {};
};

struct SLTagInventoryDiagnostics
{
    std::vector<SLTaggedResourceInventoryEntry> resources;
    uint64_t generation = 0;
};

enum class RRNGXPointerKind : uint32_t
{
    OpaquePointer,
    D3D11Resource,
    D3D12Resource
};

struct RRNGXPointerDiagnostic
{
    std::string name;
    RRNGXPointerKind kind = RRNGXPointerKind::OpaquePointer;
    bool present = false;
    void* address = nullptr;
    uint64_t nativeWidth = 0;
    uint32_t nativeHeight = 0;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    D3D12_RESOURCE_DIMENSION dimension = D3D12_RESOURCE_DIMENSION_UNKNOWN;
    D3D12_RESOURCE_FLAGS resourceFlags = D3D12_RESOURCE_FLAG_NONE;
    uint32_t mipLevels = 0;
    uint32_t arraySize = 0;
    uint32_t sampleCount = 0;
    uint64_t updateCount = 0;
};

struct RRNGXPointerDiagnostics
{
    bool tableInspectable = false;
    std::vector<RRNGXPointerDiagnostic> parameters;
    uint64_t generation = 0;
};

class StreamlineHooks
{
  public:
    typedef void* (*PFN_slGetPluginFunction)(const char* functionName);
    typedef bool (*PFN_slOnPluginLoad)(sl::param::IParameters* params, const char* loaderJSON, const char** pluginJSON);
    typedef sl::Result (*PFN_slSetData)(const sl::BaseStructure* inputs, sl::CommandBuffer* cmdBuffer);
    typedef bool (*PFN_slSetConstants_sl1)(const void* data, uint32_t frameIndex, uint32_t id);
    typedef void (*PFN_slSetParameters_sl1)(void* params);
    typedef bool (*PFN_setVoid)(void* self, const char* key, void** value);

    static void updateForceReflex();

    static void unhookInterposer();
    static void hookInterposer(HMODULE slInterposer);

    static void unhookDlss();
    static void hookDlss(HMODULE slDlss);

    static void unhookDlssg();
    static void hookDlssg(HMODULE slDlssg);

    static void unhookReflex();
    static void hookReflex(HMODULE slReflex);

    static void unhookPcl();
    static void hookPcl(HMODULE slPcl);

    static void unhookCommon();
    static void hookCommon(HMODULE slCommon);

    static bool isInterposerHooked();
    static bool isDlssHooked();
    static bool isDlssgHooked();
    static bool isSetConstantsHooked();
    static bool isCommonHooked();
    static bool isPclHooked();
    static bool isReflexHooked();

    static RRSignalTagDiagnostics getRRSignalTagDiagnostics();
    static Microsoft::WRL::ComPtr<ID3D12Resource> getRRTaggedD3D12Resource(RRTaggedSignal signal);
    static RRD3D12SignalTagSnapshot getRRD3D12SignalTagSnapshot();
    static SLConstantsSnapshot getSLConstantsSnapshot();
    static void resetRRSignalTagDiagnostics();
    static void logRRSignalTagDiagnostics(uint32_t renderWidth, uint32_t renderHeight);
    static const char* getRRTaggedSignalName(RRTaggedSignal signal);
    static const char* getRRCheckerboardAssessment(RRTaggedSignal signal,
                                                   const RRTaggedResourceDiagnostic& diagnostic,
                                                   uint32_t renderWidth, uint32_t renderHeight);
    static bool isRRPreferredTagFormat(RRTaggedSignal signal, DXGI_FORMAT format);
    static const char* getRRPreferredTagFormat(RRTaggedSignal signal);
    static SLTagInventoryDiagnostics getSLTagInventoryDiagnostics();
    static const char* getSLBufferTypeName(sl::BufferType type);
    static void logSLTagInventoryDiagnostics(uint32_t renderWidth, uint32_t renderHeight);
    static RRNGXPointerDiagnostics getRRNGXPointerDiagnostics();
    static void probeRRNGXPointerParameters(const NVSDK_NGX_Parameter& parameters);
    static void logRRNGXPointerDiagnostics();
    static void resetRRInputInventoryDiagnostics();

  private:
    static sl::RenderAPI renderApi;
    static std::mutex setConstantsMutex;
    static std::mutex rrSignalTagMutex;
    static RRSignalTagDiagnostics rrSignalTagDiagnostics;
    static std::array<Microsoft::WRL::ComPtr<ID3D12Resource>,
                      static_cast<size_t>(RRTaggedSignal::Count)> rrTaggedD3D12Resources;
    static SLTagInventoryDiagnostics slTagInventoryDiagnostics;
    static RRNGXPointerDiagnostics rrNGXPointerDiagnostics;

    static void probeRRResourceTag(const sl::ResourceTag& tag, uint32_t frameIndex,
                                   uint32_t viewport, RRTagSource source);
    static void probeSLResourceTag(const sl::ResourceTag& tag, uint32_t frameIndex,
                                   uint32_t viewport, RRTagSource source);

    // System caps
    static SystemCaps* systemCaps;
    static SystemCapsSl15* systemCapsSl15;
    static void hookSystemCaps(sl::param::IParameters* params);
    static uint32_t getSystemCapsArch();
    static void setArch(uint32_t arch);
    static void spoofArch(uint32_t currentArch, sl::Feature feature);

    // Interposer
    static decltype(&slInit) o_slInit;
    static decltype(&slSetTag) o_slSetTag;
    static decltype(&slSetTagForFrame) o_slSetTagForFrame;
    static decltype(&slEvaluateFeature) o_slEvaluateFeature;
    static decltype(&slAllocateResources) o_slAllocateResources;
    static decltype(&slSetConstants) o_slSetConstants;
    static decltype(&slGetNativeInterface) o_slGetNativeInterface;
    static decltype(&slSetD3DDevice) o_slSetD3DDevice;
    static decltype(&slGetNewFrameToken) o_slGetNewFrameToken;

    static decltype(&sl1::slInit) o_slInit_sl1;

    static sl::PFun_LogMessageCallback* o_logCallback;
    static sl1::pfunLogMessageCallback* o_logCallback_sl1;

    static sl::Result hkslInit(const sl::Preferences& pref, uint64_t sdkVersion);
    static bool hkslInit_sl1(const sl1::Preferences& pref, int applicationId);
    static sl::Result hkslSetTag(const sl::ViewportHandle& viewport, const sl::ResourceTag* tags, uint32_t numTags,
                                 sl::CommandBuffer* cmdBuffer);

    static sl::Result hkslSetTagForFrame(const sl::FrameToken& frame, const sl::ViewportHandle& viewport,
                                         const sl::ResourceTag* resources, uint32_t numResources,
                                         sl::CommandBuffer* cmdBuffer);

    static sl::Result hkslEvaluateFeature(sl::Feature feature, const sl::FrameToken& frame,
                                          const sl::BaseStructure** inputs, uint32_t numInputs,
                                          sl::CommandBuffer* cmdBuffer);

    static sl::Result hkslAllocateResources(sl::CommandBuffer* cmdBuffer, sl::Feature feature,
                                            const sl::ViewportHandle& viewport);

    static sl::Result hkslGetNativeInterface(void* proxyInterface, void** baseInterface);

    static sl::Result hkslSetD3DDevice(void* d3dDevice);

    // DLSS
    static PFN_slGetPluginFunction o_dlss_slGetPluginFunction;
    static PFN_slOnPluginLoad o_dlss_slOnPluginLoad;
    static decltype(&slDLSSGetOptimalSettings) o_slDLSSGetOptimalSettings;

    static bool hkdlss_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON, const char** pluginJSON);
    static sl::Result hkslDLSSGetOptimalSettings(const sl::DLSSOptions& options, sl::DLSSOptimalSettings& settings);
    static void* hkdlss_slGetPluginFunction(const char* functionName);

    // DLSSG
    static PFN_slGetPluginFunction o_dlssg_slGetPluginFunction;
    static PFN_slOnPluginLoad o_dlssg_slOnPluginLoad;
    static decltype(&slDLSSGSetOptions) o_slDLSSGSetOptions;
    static decltype(&slDLSSGGetState) o_slDLSSGGetState;

    static bool hkdlssg_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON, const char** pluginJSON);
    static sl::Result hkslSetConstants(const sl::Constants& values, const sl::FrameToken& frame,
                                       const sl::ViewportHandle& viewport);
    static sl::Result hkslDLSSGSetOptions(const sl::ViewportHandle& viewport, const sl::DLSSGOptions& options);
    static sl::Result hkslDLSSGGetState(const sl::ViewportHandle& viewport, sl::DLSSGState& state,
                                        const sl::DLSSGOptions* options);
    static void* hkdlssg_slGetPluginFunction(const char* functionName);

    // Reflex
    static sl::ReflexMode reflexGamesLastMode;
    static PFN_slGetPluginFunction o_reflex_slGetPluginFunction;
    static PFN_slSetConstants_sl1 o_reflex_slSetConstants_sl1;
    static PFN_slOnPluginLoad o_reflex_slOnPluginLoad;
    static decltype(&slReflexSetOptions) o_slReflexSetOptions;

    static bool hkreflex_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON,
                                        const char** pluginJSON);
    static sl::Result hkslReflexSetOptions(const sl::ReflexOptions& options);
    static bool hkreflex_slSetConstants_sl1(const void* data, uint32_t frameIndex, uint32_t id);
    static void* hkreflex_slGetPluginFunction(const char* functionName);

    // PCL
    static PFN_slGetPluginFunction o_pcl_slGetPluginFunction;
    static PFN_slOnPluginLoad o_pcl_slOnPluginLoad;
    static decltype(&slPCLSetMarker) o_slPCLSetMarker;

    static bool hkpcl_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON, const char** pluginJSON);
    static void* hkpcl_slGetPluginFunction(const char* functionName);
    static sl::Result hkslPCLSetMarker(sl::PCLMarker marker, const sl::FrameToken& frame);

    // Common
    static PFN_slGetPluginFunction o_common_slGetPluginFunction;
    static PFN_slOnPluginLoad o_common_slOnPluginLoad;
    static PFN_slSetParameters_sl1 o_common_slSetParameters_sl1;
    static PFN_setVoid o_setVoid;

    static bool hkcommon_slOnPluginLoad(sl::param::IParameters* params, const char* loaderJSON,
                                        const char** pluginJSON);
    static void* hkcommon_slGetPluginFunction(const char* functionName);
    static void hkcommon_slSetParameters_sl1(void* params);
    static bool hk_setVoid(void* self, const char* key, void** value);

    // Logging
    static char* trimStreamlineLog(const char* msg);
    static void streamlineLogCallback(sl::LogType type, const char* msg);
    static void streamlineLogCallback_sl1(sl1::LogType type, const char* msg);

    // Function signature checking
    VALIDATE_MEMBER_HOOK(hkslInit, decltype(&slInit))
    VALIDATE_MEMBER_HOOK(hkslInit_sl1, decltype(&sl1::slInit))
    VALIDATE_MEMBER_HOOK(hkslSetTag, decltype(&slSetTag))
    VALIDATE_MEMBER_HOOK(hkslSetTagForFrame, decltype(&slSetTagForFrame))
    VALIDATE_MEMBER_HOOK(hkslEvaluateFeature, decltype(&slEvaluateFeature))
    VALIDATE_MEMBER_HOOK(hkslAllocateResources, decltype(&slAllocateResources))
    VALIDATE_MEMBER_HOOK(hkslGetNativeInterface, decltype(&slGetNativeInterface))
    VALIDATE_MEMBER_HOOK(hkslSetD3DDevice, decltype(&slSetD3DDevice))
    VALIDATE_MEMBER_HOOK(hkdlss_slOnPluginLoad, PFN_slOnPluginLoad)
    VALIDATE_MEMBER_HOOK(hkslDLSSGetOptimalSettings, decltype(&slDLSSGetOptimalSettings))
    VALIDATE_MEMBER_HOOK(hkdlss_slGetPluginFunction, PFN_slGetPluginFunction)
    VALIDATE_MEMBER_HOOK(hkdlssg_slOnPluginLoad, PFN_slOnPluginLoad)
    VALIDATE_MEMBER_HOOK(hkslSetConstants, decltype(&slSetConstants))
    VALIDATE_MEMBER_HOOK(hkslDLSSGSetOptions, decltype(&slDLSSGSetOptions))
    VALIDATE_MEMBER_HOOK(hkslDLSSGGetState, decltype(&slDLSSGGetState))
    VALIDATE_MEMBER_HOOK(hkdlssg_slGetPluginFunction, PFN_slGetPluginFunction)
    VALIDATE_MEMBER_HOOK(hkreflex_slOnPluginLoad, PFN_slOnPluginLoad)
    VALIDATE_MEMBER_HOOK(hkslReflexSetOptions, decltype(&slReflexSetOptions))
    VALIDATE_MEMBER_HOOK(hkreflex_slSetConstants_sl1, PFN_slSetConstants_sl1)
    VALIDATE_MEMBER_HOOK(hkreflex_slGetPluginFunction, PFN_slGetPluginFunction)
    VALIDATE_MEMBER_HOOK(hkpcl_slOnPluginLoad, PFN_slOnPluginLoad)
    VALIDATE_MEMBER_HOOK(hkpcl_slGetPluginFunction, PFN_slGetPluginFunction)
    VALIDATE_MEMBER_HOOK(hkslPCLSetMarker, decltype(&slPCLSetMarker))
    VALIDATE_MEMBER_HOOK(hkcommon_slOnPluginLoad, PFN_slOnPluginLoad)
    VALIDATE_MEMBER_HOOK(hkcommon_slGetPluginFunction, PFN_slGetPluginFunction)
    VALIDATE_MEMBER_HOOK(hkcommon_slSetParameters_sl1, PFN_slSetParameters_sl1)
    VALIDATE_MEMBER_HOOK(hk_setVoid, PFN_setVoid)
};
