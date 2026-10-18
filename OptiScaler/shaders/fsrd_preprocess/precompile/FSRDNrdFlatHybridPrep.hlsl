// Near Zero-Rough reflection-history selector, step 1 of 4 (full frame).
// Detail: the robust fit (Base) is a single-frame denoiser; run on the clean history mean it still smooths fine
// detail (poster text keeps ~55 % of its fine band, the mean itself ~100 %). The mean's departure from Base,
// D = mean - Base (luma), is kept with the Wiener factor D^2 / (D^2 + se^2), se = the mean's standard error, on mature
// pixels (count >= MinCount). D is first clamped to DetailClamp x the range of its mature 8 neighbours' departures:
// an isolated outlier (a firefly or a persistent hole in the mean) has no neighbour departing alike, a stroke or an
// edge does. The kept part fades in with the history count (MinCount -> FadeEnd) and is scaled by Detail
// (0 = Base). OutDetail = Base + kept part.
// Selector: with the reflection history Base no longer collapses on dim reflections; there it shows the residual
// noise of a heavy-tailed sparse lobe as blotches instead. The selector shows the detail result where the history's
// mean is reliable (bright, dense reflections such as signs) and RR, at the history's level, where it is not; thin
// histories (new mirror pixels, disocclusions) use the collapse rule of the RR fallback.
// Outputs on recovery pixels (zero elsewhere), blurred by HybridBlur:
//   OutPrep4 (sigma 4): x detail luma clipped to Clip x RR's 3x3 max, y RR luma, z 1, w history mean luma clipped to
//            LevelCap x RR's 3x3 max (fireflies must not paint discs into the level ratio);
//   OutPrep2 (sigma 2): x standard error of the history mean, y history mean luma (both on mature pixels, count >=
//            MinCount), z mature, w 1.
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 6)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float4> InBase : register(t0);     // Base result on recovery pixels
Texture2D<float4> InRR : register(t1);       // RR output of this lobe (the composition before Apply)
Texture2D<float4> InMask : register(t2);     // a = 1/3 on this lobe's recovery pixels
Texture2D<float> InDepth : register(t3);
Texture2D<float4> InHistory : register(t4);  // rgb running mean, a = count (0 off the recovery pixels)
Texture2D<float2> InMoment : register(t5);   // x luma second moment
RWTexture2D<float4> OutPrep4 : register(u0);
RWTexture2D<float4> OutPrep2 : register(u1);
RWTexture2D<float4> OutDetail : register(u2); // rgb Base + kept detail, a = kept fraction
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
bool Recovery(int2 p)
{
    const float depth = InDepth[p];
    return abs(InMask[p].a - 1.0f / 3.0f) < 0.1f && isfinite(depth) && abs(depth) > 1e-5f;
}
bool Mature(int2 q)
{
    return all(q >= 0) && all(q < int2(DstTexSize.xy)) && InHistory[q].a >= MinCount;
}
float Departure(int2 q)
{
    return GetLuminance(SanitizeRadiance(InHistory[q].rgb)) - GetLuminance(SanitizeRadiance(InBase[q].rgb));
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy), size = int2(DstTexSize.xy);
    if (any(p >= size)) return;
    if (!Recovery(p))
    {
        OutPrep4[p] = 0.0f;
        OutPrep2[p] = 0.0f;
        OutDetail[p] = 0.0f;
        return;
    }
    float rrMax = 0.0f;
    [unroll] for (int k = 0; k < 9; ++k)
    {
        const int2 q = clamp(p + int2(k % 3 - 1, k / 3 - 1), int2(0, 0), size - 1);
        rrMax = max(rrMax, GetLuminance(SanitizeRadiance(InRR[q].rgb)));
    }
    const float4 history = InHistory[p];
    const float3 base = SanitizeRadiance(InBase[p].rgb), meanColour = SanitizeRadiance(history.rgb);
    const float rr = GetLuminance(SanitizeRadiance(InRR[p].rgb));
    const float mean = GetLuminance(meanColour), count = max(history.a, 1.0f);
    const float variance = max(InMoment[p].x - mean * mean, 0.0f) / count;
    const float error = sqrt(variance);
    const bool matureHere = history.a >= MinCount;
    float kept = 0.0f;
    if (matureHere && Detail > 0.0f)
    {
        const float d = mean - GetLuminance(base);
        float lo = 3.0e38f, hi = -3.0e38f;
        [unroll] for (int k = 0; k < 9; ++k)
        {
            if (k == 4) continue;
            const int2 q = p + int2(k % 3 - 1, k / 3 - 1);
            if (!Mature(q)) continue;
            const float n = Departure(q);
            lo = min(lo, n); hi = max(hi, n);
        }
        const float clamped = clamp(d, DetailClamp * min(lo, 0.0f), DetailClamp * max(hi, 0.0f));
        const float alpha = clamped * clamped / max(clamped * clamped + variance, 1e-12f);
        // A young history (new mirror pixels) can hold only zeros of a sparse lobe: variance 0 reads as a certain
        // black. Detail fades in from MinCount to FadeEnd frames.
        const float young = saturate((history.a - MinCount) / max(FadeEnd - MinCount, 1e-3f));
        kept = abs(d) > 1e-12f ? Detail * young * alpha * clamped / d : 0.0f;
        if (!isfinite(kept)) kept = 0.0f;
    }
    const float3 detail = SanitizeRadiance(base + kept * (meanColour - base));
    const float mature = matureHere ? 1.0f : 0.0f;
    OutDetail[p] = float4(detail, kept);
    OutPrep4[p] = float4(min(GetLuminance(detail), Clip * rrMax), rr, 1.0f, min(mean, LevelCap * rrMax));
    OutPrep2[p] = float4(isfinite(error) ? error * mature : 0.0f, mean * mature, mature, 1.0f);
}
