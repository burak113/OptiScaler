#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 4, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 7)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2))"

Texture2D<float4> InSpec : register(t0);
Texture2D<float4> InDiff : register(t1);
Texture2D<float4> InNormalRoughness : register(t2);
Texture2D<float> InDepth : register(t3);
Texture2D<float4> InMotion : register(t4);
Texture2D<float4> InSpecAlbedo : register(t5);
Texture2D<float4> InDiffAlbedo : register(t6);
RWTexture2D<float4> OutSpec : register(u0);
RWTexture2D<float4> OutDiff : register(u1);

cbuffer CopyConstants : register(b0)
{
    uint2 RenderSize;
    uint Mode;
    uint Reserved;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const uint2 p = tid.xy;
    if (any(p >= RenderSize)) return;
    float3 spec = InSpec[p].rgb;
    float3 diff = InDiff[p].rgb;
    if (Mode == 2u)
    {
        // Three vertical diagnostic bands in each title output. Spec: decoded
        // world normal, roughness, NoV. Diff: log depth, signed motion, albedo.
        const uint band = min((p.x * 3u) / RenderSize.x, 2u);
        const float4 nr = InNormalRoughness[p];
        const float3 motion = InMotion[p].xyz;
        spec = band == 0u ? OctahedralDecode(nr.xy) * 0.5f + 0.5f
             : band == 1u ? nr.zzz : InSpecAlbedo[p].aaa;
        diff = band == 0u ? saturate(log2(1.0f + abs(InDepth[p])) / 16.0f).xxx
             : band == 1u ? float3(saturate(0.5f + motion.xy * float2(RenderSize) / 32.0f),
                                     saturate(0.5f + motion.z / 32.0f))
             : InDiffAlbedo[p].rgb;
    }
    // The title's Consumer expects denoised RGB and zero alpha, unlike RR inputs.
    OutSpec[p] = float4(spec, 0.0f);
    OutDiff[p] = float4(diff, 0.0f);
}
