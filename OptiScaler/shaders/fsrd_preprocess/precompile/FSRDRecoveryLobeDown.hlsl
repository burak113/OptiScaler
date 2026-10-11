// Recovery v2 lobe recovery, pass 2 of 3: one level of the band pyramid (see FSRDRecoveryLobeCommon.hlsli).
//
// Each texel of level l is the mean of its 2x2 block at level l-1; a block that runs past an odd edge repeats
// the last row or column. Dispatched once per level, 1 to 6, after the accumulate pass wrote level 0.
#include "FSRDRecoveryLobeCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 3), visibility = SHADER_VISIBILITY_ALL), "

Texture2D<float4> InLevelA : register(t0);
Texture2D<float4> InLevelB : register(t1);
Texture2D<float4> InLevelC : register(t2);
RWTexture2D<float4> OutLevelA : register(u0);
RWTexture2D<float4> OutLevelB : register(u1);
RWTexture2D<float4> OutLevelC : register(u2);


[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    const int2 px = int2(dtID.xy);
    if (any(px >= int2(LevelSize.xy)))
        return;
    const int2 last = int2(LevelSize.zw) - 1;
    float4 a = 0.0f, b = 0.0f, c = 0.0f;
    [unroll]
    for (int i = 0; i < 4; ++i)
    {
        const int2 q = min(2 * px + int2(i & 1, i >> 1), last);
        a += InLevelA[q];
        b += InLevelB[q];
        c += InLevelC[q];
    }
    OutLevelA[px] = 0.25f * a;
    OutLevelB[px] = 0.25f * b;
    OutLevelC[px] = 0.25f * c;
}
