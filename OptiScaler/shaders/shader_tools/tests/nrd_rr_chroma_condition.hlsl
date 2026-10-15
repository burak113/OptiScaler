// RESEARCH ONLY. All output RGB is subsequently sent through real AMD RR.
// No raw-light bypass, fake motion, fake hit distance, or SDK confidence input.
// Missing/disoccluded history is an exact identity path. History is raw input,
// never conditioned output, so the conditioner has no recursive color feedback.
#include "../../fsrd_preprocess/precompile/FSRDNrdSignalEncoding.hlsli"

#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants = 12, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 11)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2))"

cbuffer ConditionParameters : register(b0)
{
    uint2 RenderSize;
    uint HistoryCount;
    uint Mode; // 0 identity; 1 one raw history; 2 two raw histories.
    float Strength;
    float ChromaFloor;
    float MadScale;
    float DepthRelativeTolerance;
    float NormalOctTolerance;
    float RoughnessTolerance;
    float LumaFloor;
    float TemporalTolerance;
}
Texture2D<float4> Current : register(t0);
Texture2D<float4> Previous : register(t1);
Texture2D<float4> Older : register(t2);
Texture2D<float> CurrentDepth : register(t3);
Texture2D<float> PreviousDepth : register(t4);
Texture2D<float> OlderDepth : register(t5);
Texture2D<float4> CurrentNormal : register(t6);
Texture2D<float4> PreviousNormal : register(t7);
Texture2D<float4> OlderNormal : register(t8);
Texture2D<float4> CurrentMotion : register(t9);
Texture2D<float4> PreviousMotion : register(t10);
RWTexture2D<float4> Conditioned : register(u0);
// flags, accepted spatial taps, radius float bits, normalized correction bits.
RWTexture2D<uint4> Evidence : register(u1);

bool ActiveFinite(float4 value)
{
    return all(isfinite(value)) && all(value.rgb >= 0.0f) && all(value.rgb <= 65504.0f) && value.a >= 0.0f;
}
float Luma(float3 value)
{
    precise float y = (value.r + 2.0f * value.g + value.b) * 0.25f;
    return y;
}
float2 Chroma(float3 value)
{
    precise float2 c = float2((value.r - value.b) * 0.5f,
        (-value.r + 2.0f * value.g - value.b) * 0.25f);
    return c / max(Luma(value), LumaFloor);
}
bool SameGuide(float depth, float4 normal, float otherDepth, float4 otherNormal)
{
    return isfinite(depth) && isfinite(otherDepth) && depth != 0.0f && otherDepth != 0.0f &&
        all(isfinite(normal)) && all(isfinite(otherNormal)) &&
        abs(depth - otherDepth) <= DepthRelativeTolerance * max(abs(depth), 0.001f) &&
        all(abs(normal.rg - otherNormal.rg) <= NormalOctTolerance) &&
        abs(normal.b - otherNormal.b) <= RoughnessTolerance && normal.a == otherNormal.a;
}
float2 Median(inout float2 values[8], uint count)
{
    // Sort each opponent component independently. Only initialized taps count.
    [loop] for (uint i = 1u; i < count; ++i)
    {
        float2 carry = values[i];
        [loop] for (uint j = 0u; j < i; ++j)
        {
            const float2 low = min(values[j], carry);
            carry = max(values[j], carry);
            values[j] = low;
        }
        values[i] = carry;
    }
    return (values[(count - 1u) / 2u] + values[count / 2u]) * 0.5f;
}
bool Reproject(float2 uv, float4 motion, out float2 previousUV, out int2 pixel)
{
    previousUV = uv + motion.xy;
    pixel = 0;
    if (!all(isfinite(motion.xyz)) || !all(isfinite(previousUV)) ||
        any(previousUV < 0.0f) || any(previousUV >= 1.0f)) return false;
    pixel = int2(floor(previousUV * float2(RenderSize)));
    return all(pixel >= 0) && all(pixel < int2(RenderSize));
}
float3 GamutAtLuma(float y, float2 chroma)
{
    const float2 c = chroma * max(y, LumaFloor);
    const float3 delta = float3(c.x - c.y, c.y, -c.x - c.y);
    float scale = 1.0f;
    [unroll] for (uint i = 0u; i < 3u; ++i)
    {
        if (delta[i] < 0.0f) scale = min(scale, y / -delta[i]);
        if (delta[i] > 0.0f) scale = min(scale, (65504.0f - y) / delta[i]);
    }
    return y.xxx + delta * saturate(scale);
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const int2 p = int2(tid.xy);
    if (any(tid.xy >= RenderSize)) return;
    const float4 current = Current.Load(int3(p, 0));
    Conditioned[p] = current;
    uint flags = 0u, count = 0u;
    Evidence[p] = 0u;
    const float strength = isfinite(Strength) ? saturate(Strength) : 0.0f;
    if (Mode == 0u || strength == 0.0f || Mode > 2u || HistoryCount < Mode) return;
    if (!ActiveFinite(current)) { Evidence[p] = uint4(256u, 0u, 0u, 0u); return; }
    if (any(p < 1) || any(p >= int2(RenderSize) - 1)) return;
    const float depth = CurrentDepth.Load(int3(p, 0));
    const float4 normal = CurrentNormal.Load(int3(p, 0));
    const float y = Luma(current.rgb);
    const float2 c = Chroma(current.rgb);
    float2 taps[8];
    float minY = 65504.0f, maxY = 0.0f;
    [unroll] for (int dy = -1; dy <= 1; ++dy)
    [unroll] for (int dx = -1; dx <= 1; ++dx)
    {
        if (dx == 0 && dy == 0) continue;
        const int2 q = p + int2(dx, dy);
        const float4 value = Current.Load(int3(q, 0));
        if (ActiveFinite(value) && SameGuide(depth, normal, CurrentDepth.Load(int3(q, 0)), CurrentNormal.Load(int3(q, 0))))
        {
            taps[count++] = Chroma(value.rgb);
            minY = min(minY, Luma(value.rgb)); maxY = max(maxY, Luma(value.rgb));
        }
    }
    if (count < 5u) { Evidence[p] = uint4(flags, count, 0u, 0u); return; }
    flags |= 1u;
    // Isolated luma detail is not a chroma impulse. Preserve it exactly.
    const float lumaMargin = max(y * 0.1f, LumaFloor);
    if (y < minY - lumaMargin || y > maxY + lumaMargin)
    { Evidence[p] = uint4(flags | 128u, count, 0u, 0u); return; }
    const float2 median = Median(taps, count);
    [loop] for (uint i = 0u; i < count; ++i) taps[i] = abs(taps[i] - median);
    const float2 radius = max(ChromaFloor.xx, Median(taps, count) * MadScale);
    const float2 clipped = clamp(c, median - radius, median + radius);
    const float correction = max(abs(c.x - clipped.x), abs(c.y - clipped.y));
    if (correction == 0.0f) { Evidence[p] = uint4(flags, count, asuint(max(radius.x, radius.y)), 0u); return; }
    flags |= 2u;
    const float2 uv = (float2(p) + 0.5f) / float2(RenderSize);
    const float4 motion = CurrentMotion.Load(int3(p, 0));
    float2 previousUV; int2 q;
    bool valid = Reproject(uv, motion, previousUV, q);
    if (valid)
    {
        const float4 value = Previous.Load(int3(q, 0));
        const float previousDepth = PreviousDepth.Load(int3(q, 0));
        const float4 previousNormal = PreviousNormal.Load(int3(q, 0));
        valid = ActiveFinite(value) && SameGuide(depth + motion.z, normal, previousDepth, previousNormal);
        if (valid) flags |= 4u;
        valid = valid && all(abs(Chroma(value.rgb) - median) <= radius * TemporalTolerance) &&
            abs(Luma(value.rgb) - y) <= max(y * 0.25f, LumaFloor);
        if (valid) flags |= 8u;
        if (valid && Mode == 2u)
        {
            const float4 previousMotion = PreviousMotion.Load(int3(q, 0));
            float2 olderUV; int2 r;
            valid = Reproject(previousUV, previousMotion, olderUV, r);
            if (valid)
            {
                const float4 older = Older.Load(int3(r, 0));
                valid = ActiveFinite(older) && SameGuide(previousDepth + previousMotion.z, previousNormal,
                    OlderDepth.Load(int3(r, 0)), OlderNormal.Load(int3(r, 0)));
                if (valid) flags |= 16u;
                valid = valid && all(abs(Chroma(older.rgb) - median) <= radius * TemporalTolerance) &&
                    abs(Luma(older.rgb) - y) <= max(y * 0.25f, LumaFloor);
                if (valid) flags |= 32u;
            }
        }
    }
    if (valid)
    {
        precise float2 selected = c + strength * (clipped - c);
        precise float3 rgb = GamutAtLuma(y, selected);
        rgb = f16tof32(uint3(NrdNearestHalfBits(rgb.x), NrdNearestHalfBits(rgb.y), NrdNearestHalfBits(rgb.z)));
        if (all(isfinite(rgb))) { Conditioned[p] = float4(rgb, current.a); flags |= 64u; }
    }
    Evidence[p] = uint4(flags, count, asuint(max(radius.x, radius.y)), asuint(correction));
}
