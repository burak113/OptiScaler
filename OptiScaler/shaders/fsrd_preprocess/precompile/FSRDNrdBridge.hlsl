// Cyberpunk NRD inputs are already demodulated. Preserve their RGB and world-unit
// hit distances; white albedos tell RR that no further demodulation is required.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 44, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 4)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 9))"

Texture2D<float4> InNormalRoughness : register(t0);
Texture2D<float> InViewDepth : register(t1);
Texture2D<float4> InMotion : register(t2);
Texture2D<float> InPreviousDepth : register(t3);
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
}

float3 SafeRadiance(float3 value)
{
    return float3(isfinite(value.x) ? max(value.x, 0.0f) : 0.0f,
                  isfinite(value.y) ? max(value.y, 0.0f) : 0.0f,
                  isfinite(value.z) ? max(value.z, 0.0f) : 0.0f);
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const uint2 p = tid.xy;
    if (any(p >= RenderSize)) return;
    const float4 spec = InReconSpec[p];
    const float4 diff = InReconDiff[p];
    OutSpec[p] = float4(SafeRadiance(spec.rgb), spec.a);
    OutDiff[p] = float4(SafeRadiance(diff.rgb), diff.a);

    const float rawDepth = InViewDepth[p];
    const float depth = DepthSign * (isfinite(rawDepth)
        ? clamp(abs(rawDepth), NearPlane, FarPlane) : FarPlane);
    OutDepth[p] = depth;

    const float2 rawMotion = InMotion[p].xy;
    const float2 safeMotion = float2(isfinite(rawMotion.x) ? rawMotion.x : 0.0f,
                                    isfinite(rawMotion.y) ? rawMotion.y : 0.0f);
    const float2 motion = safeMotion * MotionScale + JitterDeltaUv;
    const float2 previousPixel = float2(p) + 0.5f + motion * float2(RenderSize);
    float deltaDepth = 0.0f;
    // Test bounds before conversion to int: very large finite title vectors must
    // not overflow integer conversion or produce a clamped false correspondence.
    if (PreviousValid != 0u && all(isfinite(previousPixel)) &&
        all(previousPixel >= 0.0f) && all(previousPixel < float2(RenderSize)))
    {
        const float previousDepth = InPreviousDepth[int2(floor(previousPixel))];
        if (isfinite(previousDepth)) deltaDepth = clamp(previousDepth - depth, -65504.0f, 65504.0f);
    }
    OutMotion[p] = float4(clamp(motion, -65504.0f, 65504.0f), deltaDepth, 1.0f);

    const float3 normalRoughness = InNormalRoughness[p].rgb;
    OutNormalRoughness[p] = float4(normalRoughness, 0.0f);
    const float3 worldNormal = OctahedralDecode(normalRoughness.xy);
    const float3 viewNormal = normalize(mul((float3x3)WorldToView, worldNormal));
    const float2 uv = (float2(p) + 0.5f) / float2(RenderSize);
    // An interior clip depth handles both standard/reversed and infinite planes.
    const float4 projected = mul(InverseProjection, float4(UVToNDC(uv), 0.5f, 1.0f));
    const float signW = projected.w < 0.0f ? -1.0f : 1.0f;
    const float3 toCamera = -normalize(projected.xyz * signW);
    const float noV = saturate(dot(viewNormal, toCamera));
    OutSpecAlbedo[p] = float4(1.0f, 1.0f, 1.0f, noV);
    OutDiffAlbedo[p] = float4(1.0f, 1.0f, 1.0f, 0.0f);
}
