// Edge-replicated horizontal paired radiance means, at radii 3 and 40.
// Explicit 128x1 groups; host dispatch is (ceil(width/128), height, 1).
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 3)), DescriptorTable(UAV(u0, numDescriptors = 2))"
Texture2D<half4> InSignal : register(t0);
Texture2D<half4> InDenoised : register(t1);
Texture2D<float4> InAlbedo : register(t2);
RWTexture2D<float4> OutSmall : register(u0);
RWTexture2D<float4> OutLarge : register(u1);
cbuffer CB_DetailHorizontal : register(b0)
{
    float4 DstTexSize;
    uint SmallRadius;
    uint LargeRadius;
    uint Flags;
    uint Padding0;
    float AlbedoModulation;
    float3 Padding1;
}
groupshared float3 g_Prefix[256];

[RootSignature(MainRS)]
[numthreads(128, 1, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 thread : SV_GroupThreadID)
{
    const int2 size = int2(DstTexSize.xy);
    const uint lane = thread.x;
    const int origin = int(group.x) * 128 - 40;
    [unroll]
    for (uint block = 0; block < 2; ++block)
    {
        const uint i = lane + block * 128;
        const int2 p = int2(clamp(origin + int(i), 0, size.x - 1),
                            min(int(group.y), size.y - 1));
        precise float3 difference = float3(InSignal[p].rgb) - float3(InDenoised[p].rgb);
        precise float3 multiplier = lerp(1.0f, InAlbedo[p].rgb, saturate(AlbedoModulation));
        g_Prefix[i] = i < 208 ? difference * multiplier : 0.0f;
    }
    GroupMemoryBarrierWithGroupSync();
    [unroll]
    for (uint stride = 1; stride < 256; stride <<= 1)
    {
        precise float3 a = g_Prefix[lane];
        precise float3 b = g_Prefix[lane + 128];
        a += lane >= stride ? g_Prefix[lane - stride] : 0.0f;
        b += lane + 128 >= stride ? g_Prefix[lane + 128 - stride] : 0.0f;
        GroupMemoryBarrierWithGroupSync();
        g_Prefix[lane] = a;
        g_Prefix[lane + 128] = b;
        GroupMemoryBarrierWithGroupSync();
    }
    const int2 output = int2(int(group.x) * 128 + int(lane), int(group.y));
    if (any(output >= size))
        return;
    const uint center = lane + 40;
    const uint small = min(SmallRadius, 40u), large = min(LargeRadius, 40u);
    precise float3 sumSmall = g_Prefix[center + small] -
                             (center > small ? g_Prefix[center - small - 1] : 0.0f);
    precise float3 sumLarge = g_Prefix[center + large] -
                             (center > large ? g_Prefix[center - large - 1] : 0.0f);
    OutSmall[output] = float4(sumSmall / float(2 * small + 1), 0.0f);
    OutLarge[output] = float4(sumLarge / float(2 * large + 1), 0.0f);
}
