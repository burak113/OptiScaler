// Final signed, DC-neutral, uniformly attenuated additive correction. No clipping.
#include "FSRDRecoveryDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 6)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<half4> InBase : register(t0);
Texture2D<float4> InSpecRaw : register(t1);
Texture2D<float4> InDiffuseRaw : register(t2);
Texture2D<float4> InDC : register(t3);
Texture2D<float4> InLobeScales : register(t4);
Texture2D<float4> InSumScale : register(t5);
RWTexture2D<half4> OutColor : register(u0);
cbuffer CB_DetailApply : register(b0)
{
    float4 DstTexSize;
    uint Debug;
    uint LobeMask;
    uint Padding0;
    uint Padding1;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    const int2 p = int2(id.xy);
    if (any(p >= int2(DstTexSize.xy)))
        return;
    const half4 stored = InBase[p];
    const float3 base = float3(stored.rgb);
    if (LobeMask == 0 && Debug == 0)
    {
        OutColor[p] = stored;
        return;
    }
    const float2 scales = InLobeScales[int2(0, 0)].xy;
    const float sumScale = InSumScale[int2(0, 0)].x;
    const float3 spec = (LobeMask & 1u) != 0 ? DetailNeutral(InSpecRaw[p].rgb, base,
        InDC[int2(0, 0)].rgb, InDC[int2(0, 1)].rgb) : 0.0f;
    const float3 diffuse = (LobeMask & 2u) != 0 ? DetailNeutral(InDiffuseRaw[p].rgb, base,
        InDC[int2(1, 0)].rgb, InDC[int2(1, 1)].rgb) : 0.0f;
    precise float3 correction = sumScale * (scales.x * spec + scales.y * diffuse);
    OutColor[p] = half4(Debug == 1 ? 0.5f + 0.5f * correction /
                                     max(abs(base), 0.01f) : base + correction, stored.a);
}
