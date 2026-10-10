#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"
#include "FSRDSkinCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=7)), DescriptorTable(UAV(u0, numDescriptors=2))"
Texture2D<float4> InColor : register(t0);
Texture2D<float> InDepth : register(t1);
Texture2D<float4> InDiffAlbedo : register(t2);
Texture2D<float4> InSpecAlbedo : register(t3);
Texture2D<float> InGuide : register(t4);
Texture2D<float> InBias : register(t5);
Texture2D<float> InTitleDepth : register(t6);
RWTexture2D<half4> OutColor : register(u0);
RWTexture2D<float> OutGuide : register(u1);
cbuffer CB_SssPrepare : register(b0)
{
    float4x4 InvProjMatrix;
    float4 DstTexSize;
    uint4 ColorDepthBase;
    uint4 AlbedoBase;
    uint4 GuideBiasBase;
    uint2 TitleDepthBase;
    float2 CurrentJitter;
    float NearPlane;
    float FarPlane;
    float BiasStrength;
    uint Flags;
    uint Mode;
    uint3 Padding;
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    int2 p = tid.xy;
    if (any(p >= int2(DstTexSize.xy))) return;
    const float4 source = InColor[p + int2(ColorDepthBase.xy)];
    float guide = InGuide[p + int2(GuideBiasBase.xy)];
    // Preserve every source bit before any radiance clamp on inactive pixels.
    if (Mode == 0u || guide == 0.0f || !isfinite(guide))
    {
        OutGuide[p] = 0.0f;
        OutColor[p] = half4(source);
        return;
    }
    float d = (Flags & 4096u) != 0u ? InTitleDepth[p + int2(TitleDepthBase)]
                                   : InDepth[p + int2(ColorDepthBase.zw)];
    if ((Flags & (2u | 4096u)) == 0u)
    {
        float2 uv = (float2(p) + 0.5f - CurrentJitter) * DstTexSize.zw;
        d = InvProjectPosition(float3(uv, d), InvProjMatrix).z;
    }
    d = clamp(abs(d), NearPlane, FarPlane);
    const float albedo = dot(FloorRadiance(InDiffAlbedo[p + int2(AlbedoBase.xy)].rgb) +
                             FloorRadiance(InSpecAlbedo[p + int2(AlbedoBase.zw)].rgb), 1.0f);
    const float bias = (Flags & 32768u) != 0u
        ? saturate(InBias[p + int2(GuideBiasBase.zw)] * BiasStrength) : 0.0f;
    // Routed, emissive and sky pixels retain the game's complete post-SSS colour.
    if (Mode == 0u || !isfinite(guide) || !isfinite(d) || d <= 0.0f || bias != 0.0f ||
        SoftAbove(albedo, 5.9f, 0.5f) != 0.0f ||
        log(d + 1.0f) >= 0.99f * log(min(FarPlane, 65504.0f) + 1.0f)) guide = 0.0f;
    OutGuide[p] = guide;
    OutColor[p] = half4(Mode == 1u && guide != 0.0f ? SkinSeparate(FloorRadiance(source.rgb), guide) : source.rgb, source.a);
}
