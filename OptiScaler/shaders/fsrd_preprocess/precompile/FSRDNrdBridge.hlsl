// Cyberpunk NRD inputs are already demodulated. Preserve RGB and their native
// hit-distance metric; white albedos require no further demodulation.
#include "FSRDPreprocessCommon.hlsli"
#include "FSRDNrdMotionCommon.hlsli"

#ifdef FSRD_NRD_MATERIAL_GUIDES
#include "FSRDNrdMaterialGuides.hlsli"
#define NrdGuideSrvCount "5"
#else
#define NrdGuideSrvCount "4"
#endif

#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 52, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = " NrdGuideSrvCount ")), " \
    "DescriptorTable(UAV(u0, numDescriptors = 9))"

Texture2D<float4> InNormalRoughness : register(t0);
Texture2D<float> InViewDepth : register(t1);
Texture2D<float4> InMotion : register(t2);
Texture2D<float> InPreviousDepth : register(t3);
#ifdef FSRD_NRD_MATERIAL_GUIDES
Texture2D<float4> InNativeBaseMetal : register(t4);
#endif
// Recon just wrote these through UAVs. They must be read as UAVs, never SRVs.
RWTexture2D<float4> InReconSpec : register(u0);
RWTexture2D<float4> InReconDiff : register(u1);
RWTexture2D<float4> OutSpec : register(u2);
RWTexture2D<float4> OutDiff : register(u3);
RWTexture2D<float> OutDepth : register(u4);
RWTexture2D<float4> OutMotion : register(u5);
RWTexture2D<float4> OutNormalRoughness : register(u6);
RWTexture2D<float4> OutSpecAlbedo : register(u7);
RWTexture2D<float4> OutDiffAlbedo : register(u8);

cbuffer BridgeConstants : register(b0)
{
    uint2 RenderSize;
    float NearPlane;
    float FarPlane;
    float DepthSign;
    uint PreviousValid;
    float2 MotionScale;
    float2 JitterDeltaUv;
    uint2 Reserved;
    // FSRDCamera stores column transforms. Explicit row-major storage keeps the
    // root-constant bytes identical to XMStoreFloat4x4; mul(M,v) applies them.
    row_major float4x4 InverseProjection;
    row_major float4x4 WorldToView;
    float4 PreviousViewDepthRow;
    float2 CurrentJitterUv;
    uint2 CameraReserved;
}

float3 SafeRadiance(float3 value)
{
    return float3(isfinite(value.x) ? max(value.x, 0.0f) : 0.0f,
                  isfinite(value.y) ? max(value.y, 0.0f) : 0.0f,
                  isfinite(value.z) ? max(value.z, 0.0f) : 0.0f);
}

float SafeSignalAlpha(float value)
{
    // Zero is active/finite. Preserve every finite native value, including
    // negative inactive sentinels; malformed NaN/Inf must never reach RR1.2.
    return isfinite(value) ? value : 0.0f;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const uint2 p = tid.xy;
    if (any(p >= RenderSize)) return;
    const float4 spec = InReconSpec[p];
    const float4 diff = InReconDiff[p];
    OutSpec[p] = float4(SafeRadiance(spec.rgb), SafeSignalAlpha(spec.a));
    OutDiff[p] = float4(SafeRadiance(diff.rgb), SafeSignalAlpha(diff.a));

    const float rawDepth = InViewDepth[p];
    const float depth = DepthSign * (isfinite(rawDepth)
        ? clamp(abs(rawDepth), NearPlane, FarPlane) : FarPlane);
    OutDepth[p] = depth;

    // A null-MV Recon conversion defers this read until the current Temporal table is known.
    [branch] if (Reserved.x == 0u)
        OutMotion[p] = ConvertNrdMotion(p, RenderSize, InMotion[p].xy, depth, PreviousValid,
                                        InPreviousDepth, MotionScale, JitterDeltaUv, Reserved.y,
                                        InverseProjection, PreviousViewDepthRow, CurrentJitterUv);
    else OutMotion[p] = float4(0.0f, 0.0f, 0.0f, 1.0f);

    const float4 normalRoughness = InNormalRoughness[p];
    // Native A equality-gates title spatial/temporal taps; preserve its four
    // normalized categories only for the independent OFF-default experiment.
    OutNormalRoughness[p] = float4(normalRoughness.rgb, CameraReserved.x != 0u ? normalRoughness.a : 0.0f);
    const float3 worldNormal = OctahedralDecode(normalRoughness.xy);
    const float3 viewNormal = normalize(mul((float3x3)WorldToView, worldNormal));
    const float2 uv = (float2(p) + 0.5f) / float2(RenderSize);
    // An interior clip depth handles both standard/reversed and infinite planes.
    const float4 projected = mul(InverseProjection, float4(UVToNDC(uv), 0.5f, 1.0f));
    const float signW = projected.w < 0.0f ? -1.0f : 1.0f;
    const float3 toCamera = -normalize(projected.xyz * signW);
    const float noV = saturate(dot(viewNormal, toCamera));
#ifdef FSRD_NRD_MATERIAL_GUIDES
    const float4 baseMetal = InNativeBaseMetal[p];
    // Guide outputs keep the provider's preferred RGBA8_UNORM format; its
    // normalized store clamps/rounds directly, without an intermediate half conversion.
    OutSpecAlbedo[p] = float4(NrdSpecularMaterialGuide(baseMetal, normalRoughness.a, normalRoughness.b, noV), noV);
    OutDiffAlbedo[p] = float4(NrdDiffuseMaterialGuide(baseMetal, normalRoughness.a), 0.0f);
#else
    OutSpecAlbedo[p] = float4(1.0f, 1.0f, 1.0f, noV);
    OutDiffAlbedo[p] = float4(1.0f, 1.0f, 1.0f, 0.0f);
#endif
}
