// One 8x8 group reduces all group summaries, writing a 2x2 FP32 texture.
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 2)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InSpecSummary : register(t0);
Texture2D<float4> InDiffuseSummary : register(t1);
// Row 0: RGB DC offset (specular,diffuse). Row 1: channel population >=4 masks.
RWTexture2D<float4> OutDC : register(u0);
cbuffer CB_DetailDCGlobal : register(b0)
{
    uint2 GroupSize;
    uint GroupCount;
    uint Padding0;
}
groupshared float3 g_SpecSum[64], g_SpecCount[64];
groupshared float3 g_DiffuseSum[64], g_DiffuseCount[64];

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 thread : SV_GroupThreadID)
{
    const uint lane = thread.x + 8 * thread.y;
    float3 spec = 0.0f, sc = 0.0f, diffuse = 0.0f, dc = 0.0f;
    for (uint i = lane; i < GroupCount; i += 64)
    {
        const int2 sum = int2(2 * (i % GroupSize.x), i / GroupSize.x);
        spec += InSpecSummary[sum].rgb;
        sc += InSpecSummary[sum + int2(1, 0)].rgb;
        diffuse += InDiffuseSummary[sum].rgb;
        dc += InDiffuseSummary[sum + int2(1, 0)].rgb;
    }
    g_SpecSum[lane] = spec; g_SpecCount[lane] = sc;
    g_DiffuseSum[lane] = diffuse; g_DiffuseCount[lane] = dc;
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
        OutDC[int2(0, 0)] = float4(g_SpecSum[0] / max(g_SpecCount[0], 1.0f), 0.0f);
        OutDC[int2(1, 0)] = float4(g_DiffuseSum[0] / max(g_DiffuseCount[0], 1.0f), 0.0f);
        OutDC[int2(0, 1)] = float4(float3(g_SpecCount[0] >= 4.0f), 0.0f);
        OutDC[int2(1, 1)] = float4(float3(g_DiffuseCount[0] >= 4.0f), 0.0f);
    }
}
