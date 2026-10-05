#pragma once

// The driver supplies the production functions verbatim. This harness only
// substitutes input acquisition, resource descriptions and downstream failures.
#include <d3d12.h>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <map>
#include <string>
#include "../../../upscalers/fsr31/FSRDRetryPolicy.h"

using FSRD::RRResult;

struct RoughnessTestResource
{
    D3D12_RESOURCE_DESC desc {};
    explicit RoughnessTestResource(DXGI_FORMAT format = DXGI_FORMAT_R32_FLOAT)
    {
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = 64;
        desc.Height = 48;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Format = format;
    }
    D3D12_RESOURCE_DESC GetDesc() const { return desc; }
};
#define ID3D12Resource RoughnessTestResource
#define LOG_ERROR(...) ((void) 0)
#define LOG_INFO(...) ((void) 0)
#define LOG_WARN(...) ((void) 0)
#define LOG_DEBUG(...) ((void) 0)

struct XMUINT2 { uint32_t x = 0, y = 0; };
struct XMUINT4 { uint32_t x = 0, y = 0, z = 0, w = 0; };
struct XMFLOAT2 { float x = 0, y = 0; };
struct XMFLOAT4 { float x = 0, y = 0, z = 0, w = 0; };
enum class FSRDConvFlags : uint32_t { IsRoughnessPacked = 1 };

#include "roughness_keys.inc"

constexpr int NVSDK_NGX_Result_Success = 1;
struct NVSDK_NGX_Parameter
{
    std::map<std::string, ID3D12Resource*> resources;
    std::map<std::string, double> scalars;
    template <typename T> int Get(const char* key, T* result) const
    {
        const auto found = scalars.find(key);
        if (found == scalars.end()) return 0;
        *result = static_cast<T>(found->second);
        return NVSDK_NGX_Result_Success;
    }
};

template <typename T>
bool TryGetNGXVoidPointer(const NVSDK_NGX_Parameter& params, const char* key, T*& result)
{
    const auto found = params.resources.find(key);
    result = found == params.resources.end() ? nullptr : found->second;
    return result != nullptr;
}
template <typename T>
bool TryGetLoggedResource(const NVSDK_NGX_Parameter& params, const char* key, T*& result)
{
    return TryGetNGXVoidPointer(params, key, result);
}

struct Config
{
    static const Config* Instance() { static Config config; return &config; }
};
struct TestSLConstants {};
struct SLConstantsSnapshot
{
    TestSLConstants constants;
    uint32_t frameIndex = UINT32_MAX, viewport = UINT32_MAX;
};
struct RRD3D12SignalTagSnapshot
{
    uint32_t activeEvaluationFrame = UINT32_MAX, activeEvaluationViewport = UINT32_MAX;
};
namespace StreamlineHooks
{
inline SLConstantsSnapshot getSLConstantsSnapshot() { return {}; }
inline RRD3D12SignalTagSnapshot getRRD3D12SignalTagSnapshot() { return {}; }
}
enum class RRTaggedSignal { Emissive };
enum class TagStatePolicy { RequireShaderRead };
struct RRTaggedResourceDiagnostic
{
    bool present = false, usesExtent = false;
    uint32_t extentLeft = 0, extentTop = 0;
};
struct ResourceReference
{
    ID3D12Resource* resource = nullptr;
    void Reset() { resource = nullptr; }
    ID3D12Resource* Get() const { return resource; }
};
inline bool IsEmissiveProbeCompatible(ID3D12Resource*) { return false; }

struct ConversionResources
{
    ID3D12Resource* InColor = nullptr;
    ID3D12Resource* InMotionVectors = nullptr;
    ID3D12Resource* InDepth = nullptr;
    ID3D12Resource* InNormals = nullptr;
    ID3D12Resource* InRoughness = nullptr;
    ID3D12Resource* InDiffAlbedo = nullptr;
    ID3D12Resource* InSpecAlbedo = nullptr;
    ID3D12Resource* InBiasMask = nullptr;
    ID3D12Resource* InEmissive = nullptr;
    ID3D12Resource* InSpecHitDist = nullptr;
    ID3D12Resource* InSpecularRayDirectionHitDistance = nullptr;
    ID3D12Resource* InDiffuseHitDistance = nullptr;
    ID3D12Resource* InTitleLinearDepth = nullptr;
    ID3D12Resource* InResponsivityMask = nullptr;
};
struct ConversionDesc
{
    ConversionResources Resources;
    XMUINT2 SpecularHitDistanceBase;
    bool SpecularHitDistanceFromCombinedAlpha = false;
    uint32_t Flags = 0;
    XMUINT4 FloorSourceBase, InputBase0, InputBase1, InputBase2, InputBase3, InputBase4;
    XMFLOAT4 MotionInputSize, MotionTransform, JitterOffsets;
    bool MotionHistoryValid = false, DisplayResolutionMotion = false, MotionVectorsJittered = false;
};
struct FSRDRuntimeSnapshot
{
    enum Input
    {
        Color, Depth, Motion, Normals, Roughness, DiffuseAlbedo, SpecularAlbedo,
        SpecularDistance, DiffuseDistance, Bias, Emissive, LinearDepth, Responsivity
    };
    static uint32_t Bit(Input value) { return 1u << value; }
    uint32_t prepared = 0, received = 0;
};

class FSRDFeatureDx12
{
  public:
#include "roughness_enum.inc"
    RoughnessSource _roughnessSource = RoughnessSource::Unknown;
    ConversionDesc _convDesc;
    FSRDRuntimeSnapshot _runtime;
    ResourceReference _specularHitDistanceTaggedResource, _specularRayDirectionHitDistanceTaggedResource;
    ResourceReference _emissiveTaggedResource;
    ID3D12Resource* _emissiveProbe = nullptr;
    ID3D12Resource* _materialIdProbe = nullptr;
    ID3D12Resource* _shadingModelIdProbe = nullptr;
    bool _emissiveProbeCompatible = false, _emissiveProbeFromStreamline = false;
    bool _isInReset = false, _hasDenoiserHistory = false;
    XMFLOAT2 _previousDenoiserJitter;
    bool cameraValid = true;
    RRResult signalResult = RRResult::Success;
    uint32_t renderWidth = 64, renderHeight = 48;

    RRResult PrepareDenoiseConvInput(const NVSDK_NGX_Parameter& params);
    void ApplyRoughnessFlag();
    uint32_t RenderWidth() const { return renderWidth; }
    uint32_t RenderHeight() const { return renderHeight; }
    uint32_t DisplayWidth() const { return 128; }
    uint32_t DisplayHeight() const { return 96; }
    bool LowResMV() const { return true; }
    bool JitteredMV() const { return false; }
    void InvalidateDenoiserHistory() { _hasDenoiserHistory = false; }
    template <typename... Args> bool AcquireSLTaggedResource(Args&&...) { return false; }
    template <typename... Args> void ResolveSpecularHitDistance(Args&&...) {}
    template <typename... Args> void AcquireOptionalInputs(Args&&...) {}
    template <typename... Args> void ResolveDiffuseHitDistance(Args&&...) {}
    template <typename... Args> bool ResolveCameraMatrices(Args&&...) { return cameraValid; }
    RRResult ResolveSignalTypes(bool ready) const
    {
        return ready ? signalResult : RRResult::RetryableInputFailure;
    }
};

#include "roughness_production.inc"

static unsigned checks = 0;
#define CHECK(condition) \
    do { ++checks; if (!(condition)) { \
        std::cerr << "FAIL line " << __LINE__ << ": " #condition "\n"; std::exit(1); \
    } } while (false)

using Source = FSRDFeatureDx12::RoughnessSource;

struct Frame
{
    ID3D12Resource color, depth, motion, diffuse, specular, roughness;
    ID3D12Resource normals { DXGI_FORMAT_R16G16B16A16_FLOAT };
    NVSDK_NGX_Parameter params;
    explicit Frame(Source source)
    {
        params.resources = {
            { NVSDK_NGX_Parameter_Color, &color }, { NVSDK_NGX_Parameter_Depth, &depth },
            { NVSDK_NGX_Parameter_MotionVectors, &motion }, { NVSDK_NGX_Parameter_GBuffer_Normals, &normals },
            { NVSDK_NGX_Parameter_DiffuseAlbedo, &diffuse }, { NVSDK_NGX_Parameter_SpecularAlbedo, &specular }
        };
        if (source == Source::Separate)
        {
            normals.desc.Format = DXGI_FORMAT_R16G16_FLOAT; // Cannot supply packed alpha.
            params.resources[NVSDK_NGX_Parameter_GBuffer_Roughness] = &roughness;
        }
    }
};

static void CheckFlag(FSRDFeatureDx12& feature, Source expected)
{
    feature._convDesc.Flags = 0;
    feature.ApplyRoughnessFlag();
    CHECK(bool(feature._convDesc.Flags & uint32_t(FSRDConvFlags::IsRoughnessPacked)) ==
          (expected == Source::Packed));
}

static void CheckRejectedAlbedo(Source firstSource)
{
    FSRDFeatureDx12 feature;
    const Source secondSource = firstSource == Source::Packed ? Source::Separate : Source::Packed;
    Frame rejected(firstSource), accepted(secondSource);
    rejected.params.resources.erase(NVSDK_NGX_Parameter_DiffuseAlbedo);
    const RRResult firstResult = feature.PrepareDenoiseConvInput(rejected.params);
    const Source sourceAfterRejection = feature._roughnessSource;
    const RRResult secondResult = feature.PrepareDenoiseConvInput(accepted.params);
    feature.ApplyRoughnessFlag();
    std::cout << (firstSource == Source::Packed ? "packed-then-separate" : "separate-then-packed")
              << ": missing-albedo result=" << int(firstResult)
              << ", source after rejection=" << int(sourceAfterRejection)
              << ", valid-frame result=" << int(secondResult)
              << ", final source=" << int(feature._roughnessSource)
              << ", packed flag=" << bool(feature._convDesc.Flags & uint32_t(FSRDConvFlags::IsRoughnessPacked))
              << "\n";
    CHECK(firstResult == RRResult::RetryableInputFailure);
    CHECK(sourceAfterRejection == Source::Unknown);
    CHECK(secondResult == RRResult::Success);
    CHECK(feature._roughnessSource == secondSource);
    CheckFlag(feature, secondSource);
}

static void CheckRejectedFirstFrames()
{
    const char* required[] = {
        NVSDK_NGX_Parameter_Color, NVSDK_NGX_Parameter_Depth, NVSDK_NGX_Parameter_MotionVectors,
        NVSDK_NGX_Parameter_GBuffer_Normals, NVSDK_NGX_Parameter_DiffuseAlbedo, NVSDK_NGX_Parameter_SpecularAlbedo
    };
    for (Source firstSource : { Source::Packed, Source::Separate })
    {
        const Source secondSource = firstSource == Source::Packed ? Source::Separate : Source::Packed;
        for (const char* key : required)
        {
            for (bool missing : { false, true })
            {
                FSRDFeatureDx12 feature;
                Frame rejected(firstSource), accepted(secondSource);
                if (missing) rejected.params.resources.erase(key);
                else rejected.params.resources.at(key)->desc.Width = 63;
                CHECK(feature.PrepareDenoiseConvInput(rejected.params) == RRResult::RetryableInputFailure);
                CHECK(feature._roughnessSource == Source::Unknown);
                CHECK(feature._runtime.prepared == 0);
                CheckFlag(feature, Source::Unknown);
                CHECK(feature.PrepareDenoiseConvInput(accepted.params) == RRResult::Success);
                CHECK(feature._roughnessSource == secondSource);
                CheckFlag(feature, secondSource);
            }
        }
        for (RRResult failure : { RRResult::RetryableInputFailure, RRResult::NeedsRecreation,
                                  RRResult::UnsupportedProvider, RRResult::DeviceLost })
        {
            FSRDFeatureDx12 feature;
            Frame rejected(firstSource), accepted(secondSource);
            feature.signalResult = failure;
            CHECK(feature.PrepareDenoiseConvInput(rejected.params) == failure);
            CHECK(feature._roughnessSource == Source::Unknown);
            feature.signalResult = RRResult::Success;
            CHECK(feature.PrepareDenoiseConvInput(accepted.params) == RRResult::Success);
            CHECK(feature._roughnessSource == secondSource);
        }
        FSRDFeatureDx12 feature;
        Frame rejected(firstSource), accepted(secondSource);
        feature.cameraValid = false;
        CHECK(feature.PrepareDenoiseConvInput(rejected.params) == RRResult::RetryableInputFailure);
        CHECK(feature._roughnessSource == Source::Unknown);
        feature.cameraValid = true;
        CHECK(feature.PrepareDenoiseConvInput(accepted.params) == RRResult::Success);
        CHECK(feature._roughnessSource == secondSource);
    }
}

static void CheckInvalidRoughness()
{
    for (DXGI_FORMAT format : { DXGI_FORMAT_UNKNOWN, DXGI_FORMAT_R32_UINT, DXGI_FORMAT_D32_FLOAT,
                                DXGI_FORMAT_BC4_UNORM })
    {
        FSRDFeatureDx12 feature;
        Frame rejected(Source::Separate), accepted(Source::Packed);
        rejected.roughness.desc.Format = format;
        CHECK(feature.PrepareDenoiseConvInput(rejected.params) == RRResult::RetryableInputFailure);
        CHECK(feature._roughnessSource == Source::Unknown);
        CHECK(feature.PrepareDenoiseConvInput(accepted.params) == RRResult::Success);
        CHECK(feature._roughnessSource == Source::Packed);
    }
    for (double origin : { 1.0, double(UINT32_MAX) })
    {
        FSRDFeatureDx12 feature;
        Frame rejected(Source::Separate), accepted(Source::Packed);
        rejected.params.scalars[NVSDK_NGX_Parameter_DLSS_Input_Roughness_Subrect_Base_X] = origin;
        CHECK(feature.PrepareDenoiseConvInput(rejected.params) == RRResult::RetryableInputFailure);
        CHECK(feature._roughnessSource == Source::Unknown);
        CHECK(feature.PrepareDenoiseConvInput(accepted.params) == RRResult::Success);
        CHECK(feature._roughnessSource == Source::Packed);
    }
    for (DXGI_FORMAT format : { DXGI_FORMAT_R16G16_FLOAT, DXGI_FORMAT_R32G32B32_FLOAT,
                                DXGI_FORMAT_R8G8B8A8_UINT })
    {
        FSRDFeatureDx12 feature;
        Frame rejected(Source::Packed), accepted(Source::Separate);
        rejected.normals.desc.Format = format;
        CHECK(feature.PrepareDenoiseConvInput(rejected.params) == RRResult::RetryableInputFailure);
        CHECK(feature._roughnessSource == Source::Unknown);
        CHECK(feature.PrepareDenoiseConvInput(accepted.params) == RRResult::Success);
        CHECK(feature._roughnessSource == Source::Separate);
    }
    for (unsigned layout = 0; layout < 3; ++layout)
    {
        FSRDFeatureDx12 feature;
        Frame rejected(Source::Separate), accepted(Source::Packed);
        if (layout == 0) rejected.roughness.desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        if (layout == 1) rejected.roughness.desc.DepthOrArraySize = 2;
        if (layout == 2) rejected.roughness.desc.SampleDesc.Count = 4;
        CHECK(feature.PrepareDenoiseConvInput(rejected.params) == RRResult::RetryableInputFailure);
        CHECK(feature._roughnessSource == Source::Unknown);
        CHECK(feature.PrepareDenoiseConvInput(accepted.params) == RRResult::Success);
        CHECK(feature._roughnessSource == Source::Packed);
    }
}

static void CheckAcceptedAndDeclaredStability()
{
    for (Source source : { Source::Packed, Source::Separate })
    {
        for (bool creationDeclared : { false, true })
        {
            FSRDFeatureDx12 feature;
            if (creationDeclared) feature._roughnessSource = source;
            Frame valid(source);
            CHECK(feature.PrepareDenoiseConvInput(valid.params) == RRResult::Success);
            CHECK(feature._roughnessSource == source);
            CheckFlag(feature, source);
            Frame opposite(source == Source::Packed ? Source::Separate : Source::Packed);
            CHECK(feature.PrepareDenoiseConvInput(opposite.params) == RRResult::RetryableInputFailure);
            CHECK(feature._roughnessSource == source);
            CheckFlag(feature, source);
            CHECK(feature.PrepareDenoiseConvInput(valid.params) == RRResult::Success);
            CHECK(feature._roughnessSource == source);
            feature.cameraValid = false;
            CHECK(feature.PrepareDenoiseConvInput(valid.params) == RRResult::RetryableInputFailure);
            CHECK(feature._roughnessSource == source);
            feature.cameraValid = true;
            feature.signalResult = RRResult::NeedsRecreation;
            CHECK(feature.PrepareDenoiseConvInput(valid.params) == RRResult::NeedsRecreation);
            CHECK(feature._roughnessSource == source);
        }
        // Metadata must also survive a rejected very first frame.
        FSRDFeatureDx12 declared;
        declared._roughnessSource = source;
        Frame invalid(source);
        invalid.params.resources.erase(NVSDK_NGX_Parameter_DiffuseAlbedo);
        CHECK(declared.PrepareDenoiseConvInput(invalid.params) == RRResult::RetryableInputFailure);
        CHECK(declared._roughnessSource == source);
    }
    // A packed instance still consumes alpha when an extra separate texture appears.
    FSRDFeatureDx12 packed;
    Frame frame(Source::Packed);
    CHECK(packed.PrepareDenoiseConvInput(frame.params) == RRResult::Success);
    frame.params.resources[NVSDK_NGX_Parameter_GBuffer_Roughness] = &frame.roughness;
    CHECK(packed.PrepareDenoiseConvInput(frame.params) == RRResult::Success);
    CHECK(packed._roughnessSource == Source::Packed);
    CheckFlag(packed, Source::Packed);

    for (DXGI_FORMAT format : { DXGI_FORMAT_R8_TYPELESS, DXGI_FORMAT_R8_UNORM,
                                DXGI_FORMAT_R16_TYPELESS, DXGI_FORMAT_R16_FLOAT,
                                DXGI_FORMAT_R32_TYPELESS, DXGI_FORMAT_R32_FLOAT,
                                DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_R8G8B8A8_UNORM })
    {
        FSRDFeatureDx12 feature;
        Frame separate(Source::Separate);
        separate.roughness.desc.Format = format;
        CHECK(feature.PrepareDenoiseConvInput(separate.params) == RRResult::Success);
        CHECK(feature._roughnessSource == Source::Separate);
    }
}

int main(int argc, char** argv)
{
    if (argc == 2)
    {
        CheckRejectedAlbedo(std::string(argv[1]) == "packed-then-separate" ? Source::Packed : Source::Separate);
        return 0;
    }
    CheckRejectedAlbedo(Source::Packed);
    CheckRejectedAlbedo(Source::Separate);
    CheckRejectedFirstFrames();
    CheckInvalidRoughness();
    CheckAcceptedAndDeclaredStability();
    std::cout << checks << " roughness acceptance checks passed (production PrepareDenoiseConvInput)\n";
}
