// Stage 0: minimum safe uniform scale per lobe. Stage 1: safe shared sum scale.
#include "FSRDRecoveryDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 5)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InSpecRaw : register(t0);
Texture2D<float4> InDiffuseRaw : register(t1);
Texture2D<half4> InBase : register(t2);
Texture2D<float4> InDC : register(t3);
Texture2D<float4> InLobeScales : register(t4);
RWTexture2D<float4> OutMinimum : register(u0);
cbuffer CB_DetailScaleGroups : register(b0)
{
    float4 DstTexSize;
    uint Stage;
    uint Padding0;
    uint Padding1;
    uint Padding2;
}
groupshared float2 g_Minimum[64];

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 thread : SV_GroupThreadID)
{
    const uint lane = thread.x + 8 * thread.y;
    const int2 p = int2(group.xy * 8 + thread.xy);
    float2 minimum = 1.0f;
    if (all(p < int2(DstTexSize.xy)))
    {
        const float3 base = float3(InBase[p].rgb);
        const float3 spec = DetailNeutral(InSpecRaw[p].rgb, base,
                                          InDC[int2(0, 0)].rgb, InDC[int2(0, 1)].rgb);
        const float3 diffuse = DetailNeutral(InDiffuseRaw[p].rgb, base,
                                             InDC[int2(1, 0)].rgb, InDC[int2(1, 1)].rgb);
        if (Stage == 0)
            minimum = float2(DetailScale(spec, base), DetailScale(diffuse, base));
        else
        {
            const float2 scales = InLobeScales[int2(0, 0)].xy;
            minimum.x = DetailScale(scales.x * spec + scales.y * diffuse, base);
        }
    }
    g_Minimum[lane] = minimum;
    GroupMemoryBarrierWithGroupSync();
    [unroll]
    for (uint stride = 32; stride > 0; stride >>= 1)
    {
        if (lane < stride)
            g_Minimum[lane] = min(g_Minimum[lane], g_Minimum[lane + stride]);
        GroupMemoryBarrierWithGroupSync();
    }
    if (lane == 0)
        OutMinimum[int2(group.xy)] = float4(g_Minimum[0], 0.0f, 0.0f);
}
