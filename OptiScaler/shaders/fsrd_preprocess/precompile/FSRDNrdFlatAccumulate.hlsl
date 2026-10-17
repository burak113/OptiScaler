// Near Zero-Rough Recovery reference for the NRD bridge: a reprojected, linear running mean
// of one noisy demodulated lobe. Mirror-like lobes are sparse 1spp signals (about half the
// pixels are exactly zero in a frame, the rest heavy tailed), so robust or log-domain
// averaging biases them dark; only a plain linear mean over many frames is unbiased. Their noise
// is independent from frame to frame, so a mature mean beats any spatial filter (NRD's approach).
// Reflections follow the surface motion only under camera rotation; camera translation adds
// parallax, which caps the history (ParallaxTolerance / (ParallaxPixels / depth) frames).
// Alpha of the reference: >= 0 the relative deviation of the mean (Base's temporal residual),
// < 0 a thin history (-1 - confidence), which Base fades out exactly like the slice resolve.
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 7)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float4> InNoisy : register(t0);
Texture2D<float4> InMask : register(t1);   // rgb normal, a = 1/3 on active flat pixels of this lobe
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InMotion : register(t3);   // xy previous-current UV, z depth delta, w validity
Texture2D<float4> InHistory : register(t4);  // rgb mean, a sample count
Texture2D<float4> InMoment : register(t5);   // x level luma (parallax-free), y depth (0 = invalid), z RR luma running mean, w mean luma^2
Texture2D<float4> InRR : register(t6);       // current RR output of this lobe (clean, follows lighting changes)
RWTexture2D<float4> OutHistory : register(u0);
RWTexture2D<float4> OutMoment : register(u1);
RWTexture2D<float4> OutReference : register(u2);
cbuffer CB_FlatAccumulate : register(b0)
{
    float4 DstTexSize;
    uint HistoryValid;
    float MaxCount;     // running-mean length cap at rest
    float MovingCount;  // cap once the surface moves MotionEnd pixels per frame
    float MotionStart;
    float MotionEnd;
    float FullCount;    // count at which the reference reports a residual instead of a confidence
    float Epsilon;
    float ChangeStart;  // relative RR change at which the mean starts to restart (lighting changed)
    float ParallaxPixels;    // camera translation x focal length in pixels; / depth = parallax bound per frame
    float ParallaxTolerance; // frames x parallax pixels allowed in the history (smear budget)
    float2 Reserved;
}
static const float kChangeEnd = 2.5f; // ChangeEnd = ChangeStart * kChangeEnd
// Level history: follows the mature mean, and carries on as a slow EMA while parallax keeps the
// mean short, so Base can hold the reference level (RR darkens mirror lobes) while walking.
static const float kLevelRate = 1.0f/16.0f;
static const float kLevelMature = 16.0f;
static const float kCubic = -0.5f;
float Cubic(float d)
{
    const float x = abs(d), x2 = x*x, x3 = x2*x;
    return x <= 1.0f ? (kCubic+2.0f)*x3-(kCubic+3.0f)*x2+1.0f : (x < 2.0f ? kCubic*x3-5.0f*kCubic*x2+8.0f*kCubic*x-4.0f*kCubic : 0.0f);
}
bool Inside(int2 p) { return all(p >= 0) && all(p < int2(DstTexSize.xy)); }
bool Active(int2 p)
{
    const float z = InDepth[p];
    return abs(InMask[p].a - 1.0f/3.0f) < 0.1f && isfinite(z) && abs(z) > 1e-5f;
}
bool TapValid(int2 q, float expected)
{
    if (!Inside(q)) return false;
    const float depth = InMoment[q].y;
    return depth != 0.0f && abs(depth - expected) <= 0.03f*max(abs(expected), 1e-3f);
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy);
    if (!Inside(p)) return;
    if (!Active(p))
    {
        OutHistory[p] = 0.0f; OutMoment[p] = 0.0f; OutReference[p] = float4(0.0f, 0.0f, 0.0f, -1.0f);
        return;
    }
    const float3 current = SanitizeRadiance(InNoisy[p].rgb);
    const float z = InDepth[p];
    const float4 motion = InMotion[p];
    float3 mean = 0.0f; float square = 0.0f, count = 0.0f, rrMean = 0.0f, level = 0.0f; bool continued = false;
    const float rr = GetLuminance(SanitizeRadiance(InRR[p].rgb));
    const float2 pixels = motion.xy*DstTexSize.xy;
    const bool usable = HistoryValid != 0u && motion.w >= 0.5f && all(isfinite(motion)) && all(abs(pixels) < 4096.0f);
    if (usable)
    {
        const float2 position = float2(p) + pixels;
        const float expected = z + motion.z;
        const int2 base = int2(floor(position));
        const float2 f = position - float2(base);
        // Bilinear footprint decides validity; Catmull-Rom keeps the mean from blurring under
        // the per-frame jitter shift, clamped to the footprint to avoid ringing on sparse data.
        float4 bilinear = 0.0f; float bilinearSquare = 0.0f, bilinearWeight = 0.0f, bilinearRR = 0.0f, bilinearLevel = 0.0f;
        float4 lo = 1e30f, hi = -1e30f;
        [unroll] for (int by = 0; by < 2; ++by) [unroll] for (int bx = 0; bx < 2; ++bx)
        {
            const int2 q = base + int2(bx, by);
            if (!TapValid(q, expected)) continue;
            const float w = (bx ? f.x : 1.0f-f.x)*(by ? f.y : 1.0f-f.y);
            const float4 h = InHistory[q];
            const float4 m = InMoment[q];
            bilinear += w*h; bilinearSquare += w*m.w; bilinearRR += w*m.z; bilinearLevel += w*m.x; bilinearWeight += w;
            lo = min(lo, h); hi = max(hi, h);
        }
        if (bilinearWeight >= 0.999f)
        {
            float4 cubic = 0.0f; float cubicSquare = 0.0f, cubicWeight = 0.0f; bool complete = true;
            [unroll] for (int cy = -1; cy <= 2; ++cy) [unroll] for (int cx = -1; cx <= 2; ++cx)
            {
                const int2 q = base + int2(cx, cy);
                const float w = Cubic(f.x - float(cx))*Cubic(f.y - float(cy));
                if (!TapValid(q, expected)) { complete = complete && abs(w) < 1e-6f; continue; }
                cubic += w*InHistory[q]; cubicSquare += w*InMoment[q].w; cubicWeight += w;
            }
            float4 h = bilinear; float hs = bilinearSquare;
            if (complete && cubicWeight > 0.5f) { h = clamp(cubic/cubicWeight, lo, hi); hs = max(cubicSquare/cubicWeight, 0.0f); }
            mean = max(h.rgb, 0.0f); square = hs; count = max(h.a, 0.0f); rrMean = max(bilinearRR, 0.0f);
            level = max(bilinearLevel, 0.0f); continued = true;
            // RR rejects its own history when the lighting changes; follow it instead of
            // keeping up to MaxCount frames of the old lighting (flicker, moving lights).
            const float change = abs(rr - rrMean)/max(max(rr, rrMean), Epsilon);
            const float keep = 1.0f - smoothstep(ChangeStart, ChangeStart*kChangeEnd, change);
            count *= keep;
            level = lerp(GetLuminance(current), level, keep);
        }
    }
    const float speed = length(pixels);
    float cap = lerp(MaxCount, MovingCount, smoothstep(MotionStart, max(MotionEnd, MotionStart+1e-3f), speed));
    if (ParallaxPixels > 0.0f) cap = min(cap, max(ParallaxTolerance*abs(z)/ParallaxPixels, 1.0f));
    count = min(count, max(cap - 1.0f, 0.0f)) + 1.0f;
    const float rate = 1.0f/count;
    const float l = GetLuminance(current);
    mean = lerp(mean, current, rate);
    square = lerp(square, l*l, rate);
    rrMean = count > 1.0f ? lerp(rrMean, rr, rate) : rr;
    const float meanLuma = GetLuminance(mean);
    level = !continued ? l : (count >= kLevelMature ? meanLuma : lerp(level, l, kLevelRate));
    OutHistory[p] = float4(SanitizeRadiance(mean), count);
    OutMoment[p] = float4(max(level, 0.0f), z, rrMean, square);
    const float deviation = sqrt(max(square - meanLuma*meanLuma, 0.0f)/count)/max(meanLuma, Epsilon);
    const float alpha = count < FullCount ? -1.0f - count/FullCount : min(deviation, 65504.0f);
    OutReference[p] = float4(SanitizeRadiance(mean), alpha);
}
