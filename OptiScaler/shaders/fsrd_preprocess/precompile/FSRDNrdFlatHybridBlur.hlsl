// Near Zero-Rough reflection-history selector, steps 2 and 3 of 4 (full frame): separable Gaussians, sigma 4
// (radius 12) of InSource4 and sigma 2 (radius 6) of InSource2, mirrored at the image border.
// Direction 0 (horizontal): prep -> horizontal sums (OutTarget4, OutTarget2).
// Direction 1 (vertical): sums -> decision on recovery pixels (history count > 0), OutTarget4 = (w, k, 1, 0):
//   collapse  q = clipped Base / RR (sigma 4 means); w_c = 1 - smoothstep(Low -> High, q), with the mature or the
//             thin thresholds by this pixel's history count;
//   noise     R = standard error / mean of the mature history (sigma 2); w_n = smoothstep(NoiseLow -> NoiseHigh, R)
//             where mature pixels support the estimate (sigma-2 share > Support), 0 elsewhere;
//   level     k = clipped history mean / RR (sigma 4), clamped to LevelMin..LevelMax;
//   w = max(w_c, w_n); a thin-history pixel below Dark x RR (the fit dropped it, e.g. at the edges of a newly
//   visible reflection) takes RR (w = 1).
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 4)), DescriptorTable(UAV(u0, numDescriptors = 2))"
Texture2D<float4> InSource4 : register(t0);
Texture2D<float4> InSource2 : register(t1);
Texture2D<float4> InHistory : register(t2);  // a = count (0 off the recovery pixels); vertical pass only
Texture2D<float4> InPrep4 : register(t3);    // x detail luma (clipped), y RR luma; vertical pass only
RWTexture2D<float4> OutTarget4 : register(u0);
RWTexture2D<float4> OutTarget2 : register(u1); // horizontal pass only
cbuffer CB_FlatHybrid : register(b0)
{
    float4 DstTexSize;
    float NoiseLow, NoiseHigh, Support, Epsilon;
    float MatureLow, MatureHigh, ThinLow, ThinHigh;
    float Clip, LevelCap, LevelMin, LevelMax;
    float MinCount;
    uint Direction;
    float Detail, DetailClamp;
    float FadeEnd, Dark, Reserved0, Reserved1;
}
static const int Radius = 12;
int Mirror(int i, int n) { return i < 0 ? -i : (i >= n ? 2 * (n - 1) - i : i); }
float Step01(float x, float a, float b)
{
    const float t = saturate((x - a) / (b - a));
    return t * t * (3.0f - 2.0f * t);
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy), size = int2(DstTexSize.xy);
    if (any(p >= size)) return;
    const int2 axis = Direction == 0u ? int2(1, 0) : int2(0, 1);
    float4 sum4 = 0.0f, sum2 = 0.0f;
    float total4 = 0.0f, total2 = 0.0f;
    for (int k = -Radius; k <= Radius; ++k)
    {
        int2 q = p + axis * k;
        q = int2(Mirror(q.x, size.x), Mirror(q.y, size.y));
        const float g4 = exp(-float(k * k) / 32.0f);
        sum4 += g4 * InSource4[q];
        total4 += g4;
        if (abs(k) <= 6)
        {
            const float g2 = exp(-float(k * k) / 8.0f);
            sum2 += g2 * InSource2[q];
            total2 += g2;
        }
    }
    sum4 /= total4;
    sum2 /= total2;
    if (Direction == 0u)
    {
        OutTarget4[p] = sum4;
        OutTarget2[p] = sum2;
        return;
    }
    const float count = InHistory[p].a;
    if (!(count > 0.0f))
    {
        OutTarget4[p] = 0.0f;
        return;
    }
    const float norm = max(sum4.z, 1e-6f);
    const float q = (sum4.x / norm + Epsilon) / (sum4.y / norm + Epsilon);
    const bool mature = count >= MinCount;
    const float collapse = 1.0f - (mature ? Step01(q, MatureLow, MatureHigh) : Step01(q, ThinLow, ThinHigh));
    const float support = sum2.z / max(sum2.w, 1e-6f);
    const float noise = support > Support ? Step01(sum2.x / max(sum2.y, 1e-12f), NoiseLow, NoiseHigh) : 0.0f;
    const float level = clamp(sum4.w / max(sum4.y, 1e-12f), LevelMin, LevelMax);
    float w = max(collapse, noise);
    const float4 prep = InPrep4[p];
    if (!mature && prep.x < Dark * prep.y) w = 1.0f;
    OutTarget4[p] = float4(isfinite(w) ? w : 1.0f, isfinite(level) ? level : 1.0f, 1.0f, 0.0f);
}
