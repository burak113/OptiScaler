#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 14)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float4> InSpecular : register(t0);
Texture2D<float4> InDiffuse : register(t1);
Texture2D<float4> InSpecularAlbedo : register(t2);
Texture2D<float4> InDiffuseAlbedo : register(t3);
Texture2D<float4> InSkip : register(t4);
Texture2D<float4> InNormals : register(t5);
Texture2D<float> InDepth : register(t6);
Texture2D<float4> InReference : register(t7);
Texture2D<float2> InStatistics : register(t8); // sigma, structure standard deviation
ByteAddressBuffer InTiles : register(t9);
Texture2D<float4> InBase : register(t10);
Texture2D<float4> InMean : register(t11);
Texture2D<float4> InVariance : register(t12); // RR standard deviation, to avoid FP16 variance overflow
Texture2D<float4> InComposed : register(t13);
RWTexture2D<float4> OutColor : register(u0);
RWTexture2D<float4> OutStatistics : register(u1);
RWTexture2D<float4> OutVariance : register(u2);
cbuffer CB_FlatDetail : register(b0)
{
    float4 DstTexSize;
    float2 Modulation;
    float Strength;
    float Anchor;
    float Mix;
    float NoiseScale;
    float Epsilon;
    uint Radius;
    uint Pass;
    uint Debug;
    uint Flags; // bit 0/1: raw specular/diffuse are half lobes; bit 2: reference and RR are the same lighting (Base keeps the reference level); bit 3: a mature reference is the output
    float TemporalDenoise; // Base: 0 off; >0 reference alpha is the temporal residual (noise floor and Wiener strength)
}
bool FlatPixel(int2 p)
{
    if (any(p < 0) || any(p >= int2(DstTexSize.xy))) return false;
    if (abs(InNormals[p].a - 1.0f / 3.0f) >= 0.1f || InSkip[p].a == -1.0f) return false;
    const float depth = InDepth[p];
    return isfinite(depth) && abs(depth) > 1e-5f;
}
int2 FlatOrigin(uint index) { return int2(InTiles.Load2(16 + index * 8)) * 8; }
float3 FlatRaw(int2 p)
{
    const float3 s = InSpecular[p].rgb * ((Flags & 1u) != 0u ? 2.0f : 1.0f);
    const float3 d = InDiffuse[p].rgb * ((Flags & 2u) != 0u ? 2.0f : 1.0f);
    return SanitizeRadiance(s * lerp(1.0f, InSpecularAlbedo[p].rgb, Modulation.x) +
                            d * lerp(1.0f, InDiffuseAlbedo[p].rgb, Modulation.y) + InSkip[p].rgb);
}
