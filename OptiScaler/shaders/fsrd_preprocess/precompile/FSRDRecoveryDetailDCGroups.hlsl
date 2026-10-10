// Independent per-lobe soft confidence, then original global DC summaries.
// This is an offline equivalence prototype. Global DC is not a surface-local guarantee.
#include "FSRDRecoveryDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 7)), DescriptorTable(UAV(u0, numDescriptors = 4))"
Texture2D<float4> InSpecMean : register(t0);
Texture2D<float4> InSpecVariance : register(t1);
Texture2D<float4> InSpecMetadata : register(t2);
Texture2D<float4> InDiffuseMean : register(t3);
Texture2D<float4> InDiffuseVariance : register(t4);
Texture2D<float4> InDiffuseMetadata : register(t5);
Texture2D<half4> InBase : register(t6);
RWTexture2D<float4> OutSpecRaw : register(u0);
RWTexture2D<float4> OutDiffuseRaw : register(u1);
// Summary extent = (2*ceil(width/8), ceil(height/8)); paired sum/count columns.
RWTexture2D<float4> OutSpecSummary : register(u2);
RWTexture2D<float4> OutDiffuseSummary : register(u3);
cbuffer CB_DetailDCGroups : register(b0)
{
    float4 DstTexSize;
    float SpecularStrength;
    float DiffuseStrength;
    float K;
    uint MinimumAge;
    float MinimumEffectiveCount;
    uint LobeMask;
    uint Padding0;
    uint Padding1;
}
groupshared float3 g_SpecSum[64], g_SpecCount[64];
groupshared float3 g_DiffuseSum[64], g_DiffuseCount[64];

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 thread : SV_GroupThreadID)
{
    const uint lane = thread.x + 8 * thread.y;
    const int2 p = int2(group.xy * 8 + thread.xy);
    const bool inside = all(p < int2(DstTexSize.xy));
    const float3 base = inside ? float3(InBase[p].rgb) : 0.0f;
    const float3 spec = inside && (LobeMask & 1u) != 0 ? DetailSupported(
        InSpecMean[p], InSpecVariance[p], InSpecMetadata[p],
        SpecularStrength, K, MinimumAge, MinimumEffectiveCount) : 0.0f;
    const float3 diffuse = inside && (LobeMask & 2u) != 0 ? DetailSupported(
        InDiffuseMean[p], InDiffuseVariance[p], InDiffuseMetadata[p],
        DiffuseStrength, K, MinimumAge, MinimumEffectiveCount) : 0.0f;
    const bool3 specMask = (spec != 0.0f) & isfinite(spec) & isfinite(base) & (base > 0.0f);
    const bool3 diffuseMask = (diffuse != 0.0f) & isfinite(diffuse) & isfinite(base) & (base > 0.0f);
    g_SpecSum[lane] = float3(specMask) * spec;
    g_SpecCount[lane] = float3(specMask);
    g_DiffuseSum[lane] = float3(diffuseMask) * diffuse;
    g_DiffuseCount[lane] = float3(diffuseMask);
    if (inside)
    {
        OutSpecRaw[p] = float4(spec, 0.0f);
        OutDiffuseRaw[p] = float4(diffuse, 0.0f);
    }
    GroupMemoryBarrierWithGroupSync();
    [unroll]
    for (uint stride = 32; stride > 0; stride >>= 1)
    {
        if (lane < stride)
        {
            g_SpecSum[lane] += g_SpecSum[lane + stride];
            g_SpecCount[lane] += g_SpecCount[lane + stride];
            g_DiffuseSum[lane] += g_DiffuseSum[lane + stride];
            g_DiffuseCount[lane] += g_DiffuseCount[lane + stride];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    if (lane == 0)
    {
        const int2 sum = int2(2 * group.x, group.y), count = sum + int2(1, 0);
        OutSpecSummary[sum] = float4(g_SpecSum[0], 0.0f);
        OutSpecSummary[count] = float4(g_SpecCount[0], 0.0f);
        OutDiffuseSummary[sum] = float4(g_DiffuseSum[0], 0.0f);
        OutDiffuseSummary[count] = float4(g_DiffuseCount[0], 0.0f);
    }
}
