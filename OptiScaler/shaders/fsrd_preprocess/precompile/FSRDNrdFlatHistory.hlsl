// Near Zero-Rough reflection history (full frame, specular lobe). A mirror pixel shows a virtual image behind the
// surface: the reflected point lies on the extension of the view ray at (surface distance + hit distance), and for
// a static planar reflector it is static in world space. Reprojecting that virtual point (NRD's virtual motion)
// follows the reflection instead of the surface; walking over a puddle the surface moves ~100 px per frame while
// the reflection moves ~2 px. The history is a linear running mean of the raw lobe along this motion (count capped
// at MaxCount) plus its luma second moment; Seed/Refine/Base then run on the mean instead of the single frame.
// History taps are valid on previous recovery pixels whose 3x3-median hit distance agrees (HitTolerance x hit +
// HitBias); Catmull-Rom over 16 valid taps (clamped to the bilinear footprint), bilinear over the valid taps
// otherwise, restart below half a tap of weight. Non-recovery pixels write zero (hit 0 marks them invalid).
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 5)), DescriptorTable(UAV(u0, numDescriptors = 2))"
Texture2D<float4> InNoisy : register(t0);        // raw specular lobe, a = hit distance
Texture2D<float4> InMask : register(t1);         // a = 1/3 on this lobe's recovery pixels
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InPrevMean : register(t3);     // rgb running mean, a = count
Texture2D<float2> InPrevMoment : register(t4);   // x luma second moment, y hit distance (0 = not a recovery pixel)
RWTexture2D<float4> OutMean : register(u0);
RWTexture2D<float2> OutMoment : register(u1);
cbuffer CB_FlatHistory : register(b0)
{
    float4 DstTexSize;
    float4 PrevClip0, PrevClip1, PrevClip2, PrevClip3; // rows: current view space -> previous clip space
    float4 Projection;                                 // current P00, P11, P02, P12
    float ProjectionW, MaxCount, HitTolerance, HitBias; // current P32 (clip w = P32 x view z)
    uint HistoryValid, Reserved0, Reserved1, Reserved2;
}
bool Recovery(int2 p)
{
    if (any(p < 0) || any(p >= int2(DstTexSize.xy))) return false;
    const float depth = InDepth[p];
    return abs(InMask[p].a - 1.0f / 3.0f) < 0.1f && isfinite(depth) && abs(depth) > 1e-5f;
}
float Hit(int2 p)
{
    const float h = InNoisy[p].a;
    return isfinite(h) && h > 0.0f ? h : 0.0f;
}
float MedianHit(int2 p)
{
    // Median of the valid hits in the 3x3 recovery neighbourhood (CP77 has short-hit outliers).
    float v[9];
    uint n = 0;
    [unroll] for (int k = 0; k < 9; ++k)
    {
        const int2 q = p + int2(k % 3 - 1, k / 3 - 1);
        const float h = Recovery(q) ? Hit(q) : 0.0f;
        v[k] = h > 0.0f ? h : 3.0e38f;
        n += h > 0.0f ? 1u : 0u;
    }
    [unroll] for (int i = 0; i < 9; ++i)
        [unroll] for (int j = i + 1; j < 9; ++j)
        {
            const float a = min(v[i], v[j]), b = max(v[i], v[j]);
            v[i] = a; v[j] = b;
        }
    if (n == 0u) return 0.0f;
    const uint m = (n - 1u) / 2u;
    float r = v[0];
    [unroll] for (uint k = 1; k < 9; ++k) r = k == m ? v[k] : r;
    return r;
}
float4 CatmullRom(float x)
{
    const float x2 = x * x, x3 = x2 * x;
    return float4((-x3 + 2.0f * x2 - x) * 0.5f, (3.0f * x3 - 5.0f * x2 + 2.0f) * 0.5f,
                  (-3.0f * x3 + 4.0f * x2 + x) * 0.5f, (x3 - x2) * 0.5f);
}
bool Tap(int2 q, float hit)
{
    if (any(q < 0) || any(q >= int2(DstTexSize.xy))) return false;
    const float h = InPrevMoment[q].y;
    return h > 0.0f && abs(h - hit) < HitTolerance * hit + HitBias;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy);
    if (any(p >= int2(DstTexSize.xy))) return;
    if (!Recovery(p))
    {
        OutMean[p] = 0.0f;
        OutMoment[p] = 0.0f;
        return;
    }
    const float3 raw = SanitizeRadiance(InNoisy[p].rgb);
    const float luma = GetLuminance(raw);
    const float hit = MedianHit(p);
    float3 mean = raw;
    float count = 1.0f, moment = luma * luma;
    if (HistoryValid != 0u && hit > 0.0f)
    {
        const float z = abs(InDepth[p]) * (ProjectionW < 0.0f ? -1.0f : 1.0f);
        const float2 ndc = float2((float(p.x) + 0.5f) * DstTexSize.z * 2.0f - 1.0f, 1.0f - (float(p.y) + 0.5f) * DstTexSize.w * 2.0f);
        const float w = ProjectionW * z;
        float3 view = float3((ndc.x * w - Projection.z * z) / Projection.x, (ndc.y * w - Projection.w * z) / Projection.y, z);
        view *= 1.0f + hit / max(length(view), 1e-6f);
        const float4 v = float4(view, 1.0f);
        const float4 clip = float4(dot(PrevClip0, v), dot(PrevClip1, v), dot(PrevClip2, v), dot(PrevClip3, v));
        if (clip.w > 1e-6f && all(isfinite(clip)))
        {
            const float2 prev = clip.xy / clip.w;
            const float2 q = float2((prev.x + 1.0f) * 0.5f * DstTexSize.x, (1.0f - prev.y) * 0.5f * DstTexSize.y) - 0.5f;
            const int2 b = int2(floor(q));
            const float2 f = q - float2(b);
            float3 sum = 0.0f, lo = 3.0e38f, hi = -3.0e38f;
            float weight = 0.0f, countSum = 0.0f, momentSum = 0.0f;
            [unroll] for (int k = 0; k < 4; ++k)
            {
                const int2 o = int2(k & 1, k >> 1), t = b + o;
                const float g = (o.x ? f.x : 1.0f - f.x) * (o.y ? f.y : 1.0f - f.y);
                if (!Tap(t, hit)) continue;
                const float4 h = InPrevMean[t];
                sum += g * h.rgb; weight += g; countSum += g * h.a; momentSum += g * InPrevMoment[t].x;
                lo = min(lo, h.rgb); hi = max(hi, h.rgb);
            }
            if (weight > 0.5f)
            {
                float3 history = sum / weight;
                const float4 wx = CatmullRom(f.x), wy = CatmullRom(f.y);
                float3 cubic = 0.0f;
                bool all16 = true;
                [unroll] for (int j = 0; j < 4; ++j)
                    [unroll] for (int i = 0; i < 4; ++i)
                    {
                        const int2 t = b + int2(i - 1, j - 1);
                        all16 = all16 && Tap(t, hit);
                        cubic += wx[i] * wy[j] * InPrevMean[clamp(t, int2(0, 0), int2(DstTexSize.xy) - 1)].rgb;
                    }
                if (all16) history = clamp(cubic, lo, hi);
                count = min(countSum / weight + 1.0f, MaxCount);
                mean = history + (raw - history) / count;
                const float m = momentSum / weight;
                moment = m + (luma * luma - m) / count;
            }
        }
    }
    OutMean[p] = float4(SanitizeRadiance(mean), count);
    OutMoment[p] = float2(isfinite(moment) ? max(moment, 0.0f) : 0.0f, hit);
}
