// Geometry-only native NRD bridge path. No noisy or native-denoised lighting is
// read or written. The unchanged lighting textures are filled only by late raw decode.
#include "FSRDPreprocessCommon.hlsli"
#ifdef FSRD_NRD_MATERIAL_GUIDES
#include "FSRDNrdMaterialGuides.hlsli"
#ifdef FSRD_NRD_MATERIAL_PARAMS
#define NrdGeometrySrvCount "6"
#else
#define NrdGeometrySrvCount "5"
#endif
#else
#define NrdGeometrySrvCount "4"
#endif
#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants=52, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors=" NrdGeometrySrvCount ")), " \
    "DescriptorTable(UAV(u0, numDescriptors=9)), CBV(b6)"
Texture2D<float4> InNormalRoughness : register(t0);
Texture2D<float> InViewDepth : register(t1);
#ifdef FSRD_NRD_MATERIAL_GUIDES
Texture2D<float4> InNativeBaseMetal : register(t4);
#ifdef FSRD_NRD_MATERIAL_PARAMS
Texture2D<float> InNativeMaterialRoughness : register(t5);
#endif
#endif
RWTexture2D<float> OutPositiveViewDepth : register(u0);
RWTexture2D<float> OutDepth : register(u4);
RWTexture2D<float4> OutMotion : register(u5);
RWTexture2D<float4> OutNormalRoughness : register(u6);
RWTexture2D<float4> OutSpecAlbedo : register(u7);
RWTexture2D<float4> OutDiffAlbedo : register(u8);
cbuffer BridgeConstants : register(b0)
{
    uint2 RenderSize;
    float NearPlane, FarPlane;
    float DepthSign;
    uint PreviousValid;
    float2 MotionScale, JitterDeltaUv;
    uint2 Reserved;
    row_major float4x4 InverseProjection, WorldToView;
    float4 PreviousViewDepthRow;
    float2 CurrentJitterUv;
    uint2 CameraReserved;
}
cbuffer OwnedNativeGeometry : register(b6) { uint4 NativeGeometry[29]; }
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const uint2 p = tid.xy;
    if (any(p >= RenderSize)) return;
    const int2 source = int2(p) + asint(NativeGeometry[28].zw);
    const float rawDepth = InViewDepth.Load(int3(source, 0));
    // Exact native PrePass u2, independent of its color filter. Do not clamp it
    // to RR's depth bounds: the native Temporal expression needs this positive Z.
    OutPositiveViewDepth[p] = max(abs(rawDepth), asfloat(0x358637bdu));
    OutDepth[p] = DepthSign * (isfinite(rawDepth) ? clamp(abs(rawDepth), NearPlane, FarPlane) : FarPlane);
    // Current Temporal motion is deliberately supplied in the separate same-list step.
    OutMotion[p] = float4(0.0f,0.0f,0.0f,1.0f);
    const float4 normalRoughness = InNormalRoughness.Load(int3(source, 0));
    OutNormalRoughness[p] = float4(normalRoughness.rgb, CameraReserved.x ? normalRoughness.a : 0.0f);
    const float3 worldNormal = OctahedralDecode(normalRoughness.xy);
    const float3 viewNormal = normalize(mul((float3x3)WorldToView, worldNormal));
    const float2 uv = (float2(p) + 0.5f) / float2(RenderSize);
    const float4 projected = mul(InverseProjection,float4(UVToNDC(uv),0.5f,1.0f));
    const float signW = projected.w < 0.0f ? -1.0f : 1.0f;
    const float noV = saturate(dot(viewNormal,-normalize(projected.xyz*signW)));
#ifdef FSRD_NRD_MATERIAL_GUIDES
    const float4 baseMetal = InNativeBaseMetal.Load(int3(source, 0));
#ifdef FSRD_NRD_MATERIAL_PARAMS
    const float rawRoughness = InNativeMaterialRoughness.Load(int3(source, 0));
    const float guideRoughness = isfinite(rawRoughness) ? clamp(rawRoughness,0.04f,1.0f) : rawRoughness;
#else
    const float guideRoughness = normalRoughness.b;
#endif
    OutSpecAlbedo[p] = float4(NrdSpecularMaterialGuide(baseMetal,normalRoughness.a,guideRoughness,noV),noV);
    OutDiffAlbedo[p] = float4(NrdDiffuseMaterialGuide(baseMetal,normalRoughness.a),0.0f);
#else
    OutSpecAlbedo[p] = float4(1.0f,1.0f,1.0f,noV);
    OutDiffAlbedo[p] = float4(1.0f,1.0f,1.0f,0.0f);
#endif
}
