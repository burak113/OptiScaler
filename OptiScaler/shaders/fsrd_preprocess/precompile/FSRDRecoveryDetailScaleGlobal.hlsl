// One 8x8 group; component-wise minimum over summary groups.
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 1)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InMinimum : register(t0);
RWTexture2D<float4> OutScale : register(u0);
cbuffer CB_DetailScaleGlobal : register(b0)
{
    uint2 GroupSize;
    uint GroupCount;
    uint Padding0;
}
groupshared float2 g_Minimum[64];

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 thread : SV_GroupThreadID)
{
    const uint lane = thread.x + 8 * thread.y;
    float2 value = 1.0f;
    for (uint i = lane; i < GroupCount; i += 64)
        value = min(value, InMinimum[int2(i % GroupSize.x, i / GroupSize.x)].xy);
    g_Minimum[lane] = value;
    GroupMemoryBarrierWithGroupSync();
    [unroll]
    for (uint stride = 32; stride > 0; stride >>= 1)
    {
        if (lane < stride)
            g_Minimum[lane] = min(g_Minimum[lane], g_Minimum[lane + stride]);
        GroupMemoryBarrierWithGroupSync();
    }
    if (lane == 0)
        OutScale[int2(0, 0)] = float4(g_Minimum[0], 0.0f, 0.0f);
}
