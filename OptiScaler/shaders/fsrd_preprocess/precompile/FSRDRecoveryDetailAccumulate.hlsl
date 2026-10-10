// Vertical means and startup-normalized causal paired band moments.
// Explicit 1x128 groups; host dispatch is (width, ceil(height/128), 1).
#include "FSRDRecoveryDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 8)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float4> InSmall : register(t0);
Texture2D<float4> InLarge : register(t1);
Texture2D<float4> InMean : register(t2);       // RGB signed band mean; A EMA mass
Texture2D<float4> InVariance : register(t3);   // RGB central sample moment; A squared weights q
Texture2D<float4> InMetadata : register(t4);   // R depth, GB oct-normal, A age
Texture2D<float> InDepth : register(t5);
Texture2D<float4> InNormal : register(t6);     // original R10G10B10A2_UNORM oct-normal
Texture2D<half4> InMotion : register(t7);      // normalized XY, signed depth delta, validity
RWTexture2D<float4> OutMean : register(u0);
RWTexture2D<float4> OutVariance : register(u1);
RWTexture2D<float4> OutMetadata : register(u2);
cbuffer CB_DetailAccumulate : register(b0)
{
    float4 DstTexSize;
    float2 HistoryJitterDelta;
    uint HistoryValid;
    float Response;
    float DepthRelativeTolerance;
    float NormalDotMinimum;
    uint MinimumAge;
    float MinimumEffectiveCount;
}
groupshared float3 g_Small[256];
groupshared float3 g_Large[256];

[RootSignature(MainRS)]
[numthreads(1, 128, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 thread : SV_GroupThreadID)
{
    const int2 size = int2(DstTexSize.xy);
    const uint lane = thread.y;
    const int origin = int(group.y) * 128 - 40;
    [unroll]
    for (uint block = 0; block < 2; ++block)
    {
        const uint i = lane + block * 128;
        const int2 p = int2(min(int(group.x), size.x - 1),
                            clamp(origin + int(i), 0, size.y - 1));
        g_Small[i] = i < 208 ? InSmall[p].rgb : 0.0f;
        g_Large[i] = i < 208 ? InLarge[p].rgb : 0.0f;
    }
    GroupMemoryBarrierWithGroupSync();
    [unroll]
    for (uint stride = 1; stride < 256; stride <<= 1)
    {
        precise float3 sa = g_Small[lane], sb = g_Small[lane + 128];
        precise float3 la = g_Large[lane], lb = g_Large[lane + 128];
        sa += lane >= stride ? g_Small[lane - stride] : 0.0f;
        sb += lane + 128 >= stride ? g_Small[lane + 128 - stride] : 0.0f;
        la += lane >= stride ? g_Large[lane - stride] : 0.0f;
        lb += lane + 128 >= stride ? g_Large[lane + 128 - stride] : 0.0f;
        GroupMemoryBarrierWithGroupSync();
        g_Small[lane] = sa; g_Small[lane + 128] = sb;
        g_Large[lane] = la; g_Large[lane + 128] = lb;
        GroupMemoryBarrierWithGroupSync();
    }
    const int2 p = int2(int(group.x), int(group.y) * 128 + int(lane));
    if (any(p >= size))
        return;
    const uint center = lane + 40;
    precise float3 observed = (g_Small[center + 3] - g_Small[center - 4]) / 7.0f -
                             (g_Large[center + 40] - (center > 40 ? g_Large[center - 41] : 0.0f)) / 81.0f;
    const bool finite = all(isfinite(observed));
    observed = finite ? observed : 0.0f;
    const float depth = InDepth[p];
    const float2 oct = InNormal[p].xy;
    const float3 normal = DetailNormal(oct);
    const float4 motion = float4(InMotion[p]);
    precise float2 previous = float2(p) + motion.xy * DstTexSize.xy + HistoryJitterDelta;
    bool reuse = HistoryValid != 0 && finite && all(isfinite(motion)) &&
                 all(isfinite(previous)) && motion.a >= 0.5f &&
                 all(previous >= 0.0f) && all(previous <= float2(size - 1)) &&
                 isfinite(depth) && abs(depth) > 1e-5f;
    const int2 originPrevious = int2(floor(reuse ? previous : 0.0f));
    const float2 fraction = reuse ? previous - float2(originPrevious) : 0.0f;
    precise float3 oldMean = 0.0f, oldDeviation = 0.0f;
    precise float oldMass = 0.0f, oldQ = 0.0f, oldAge = 0.0f, total = 0.0f;
    const float predictedDepth = depth + motion.z;
    [unroll]
    for (uint tap = 0; tap < 4; ++tap)
    {
        const int2 offset = int2(tap & 1, tap >> 1);
        const int2 q = clamp(originPrevious + offset, 0, size - 1);
        const float4 meta = InMetadata[q];
        const float4 mean = InMean[q], variance = InVariance[q];
        precise float weight = (offset.x != 0 ? fraction.x : 1.0f - fraction.x) *
                               (offset.y != 0 ? fraction.y : 1.0f - fraction.y);
        const bool same = isfinite(meta.r) &&
            abs(meta.r - predictedDepth) <= DepthRelativeTolerance * max(abs(predictedDepth), 0.001f) &&
            dot(normal, DetailNormal(meta.gb)) > NormalDotMinimum &&
            all(isfinite(mean)) && all(isfinite(variance)) && all(isfinite(meta));
        weight = same && reuse ? weight : 0.0f;
        total += weight;
        // Multiplication by a zero weight does not remove a NaN/Inf tap.
        // Rejected contributors must not execute any moment arithmetic.
        if (weight > 0.0f)
        {
            oldMean += weight * mean.rgb;
            oldDeviation += weight * sqrt(max(variance.rgb, 0.0f));
            oldMass += weight * mean.a;
            oldQ += weight * variance.a;
            oldAge += weight * meta.a;
        }
    }
    reuse = reuse && total > 0.0f;
    const float normalization = total > 0.0f ? 1.0f / total : 0.0f;
    oldMean *= normalization; oldDeviation *= normalization;
    oldMass *= normalization; oldQ *= normalization; oldAge *= normalization;
    precise float mass = reuse ? (1.0f - Response) * oldMass + Response : Response;
    precise float a = Response / max(mass, 1e-20f);
    precise float3 delta = observed - oldMean;
    precise float3 meanNow = reuse ? oldMean + a * delta : observed;
    precise float3 varianceNow = reuse ? (1.0f - a) * (oldDeviation * oldDeviation + a * delta * delta) : 0.0f;
    precise float qNow = reuse ? (1.0f - a) * (1.0f - a) * oldQ + a * a : 1.0f;
    const float ageNow = reuse ? oldAge + 1.0f : 1.0f;
    OutMean[p] = float4(meanNow, mass);
    OutVariance[p] = float4(varianceNow, qNow);
    // Invalid geometry restarts and cannot poison future history allocations.
    OutMetadata[p] = float4(isfinite(depth) ? depth : 0.0f,
                            all(isfinite(oct)) ? oct : 0.0f, ageNow);
}
