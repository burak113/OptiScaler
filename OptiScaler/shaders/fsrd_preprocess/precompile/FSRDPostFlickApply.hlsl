// Post-flick blotch fix (task 24 T2 c), experimental, default off) - step 2 of 2, FULL RESOLUTION.
// For pixels whose history is young (age < AgeMax, i.e. RR had little or no history after a flick) the
// low-frequency band of the composite is replaced by the keyframe's band, level matched, while the current
// frame's high-frequency detail is untouched. Settled pixels are returned byte-identical.
//   out = cur + w * (keyBand * ratio - curBand),  w = saturate(1 - age/AgeMax) * valid
// The keyframe band is recalled with the camera reprojection the chain already uses for its history
// (current view-space point -> keyframe clip space) and validated against the keyframe's depth.
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 5)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InColor : register(t0);   // the composite of this frame, full resolution
Texture2D<float2> InAux : register(t1);     // x age, y depth (half resolution)
Texture2D<float4> InCur : register(t2);     // rgb this frame's band, a its wide level (half resolution)
Texture2D<float4> InKey : register(t3);     // rgb keyframe band, a keyframe level (half resolution)
Texture2D<float2> InKeyAux : register(t4);  // x keyframe depth, y 1 when the key holds a frame
RWTexture2D<float4> OutColor : register(u0);
cbuffer CB_PostFlickApply : register(b0)
{
    float4 Size;         // full width, height, 1/width, 1/height
    float4 PrevClip0, PrevClip1, PrevClip2, PrevClip3; // current view space -> keyframe clip space
    float4 Projection;   // current P00, P11, P02, P12
    float4 Extra;        // x current P32, y keyframe P32, z depth tolerance, w age max
    float4 Ratio;        // x low, y high
    uint HistoryValid; float Strength, BandClamp, Reserved2;
}
float4 SampleHalf(Texture2D<float4> source, float2 q, int2 half)
{
    const float2 c = q * 0.5f - 0.5f;
    const int2 b = int2(floor(c));
    const float2 f = c - float2(b);
    const int2 c0 = clamp(b, int2(0, 0), half - 1);
    const int2 c1 = clamp(b + int2(1, 1), int2(0, 0), half - 1);
    return lerp(lerp(source[c0], source[int2(c1.x, c0.y)], f.x), lerp(source[int2(c0.x, c1.y)], source[c1], f.x), f.y);
}
float2 SampleHalfAux(Texture2D<float2> source, float2 q, int2 half)
{
    const float2 c = q * 0.5f - 0.5f;
    const int2 b = int2(floor(c));
    const float2 f = c - float2(b);
    const int2 c0 = clamp(b, int2(0, 0), half - 1);
    const int2 c1 = clamp(b + int2(1, 1), int2(0, 0), half - 1);
    return lerp(lerp(source[c0], source[int2(c1.x, c0.y)], f.x), lerp(source[int2(c0.x, c1.y)], source[c1], f.x), f.y);
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy), size = int2(Size.xy);
    if (any(p >= size)) return;
    const int2 half = int2(max(1, size.x / 2), max(1, size.y / 2));
    const float3 cur = SanitizeRadiance(InColor[p].rgb);
    const float2 aux = InAux[p >> 1];
    if (HistoryValid == 0u || !(aux.x < Extra.w))
    {
        OutColor[p] = float4(cur, InColor[p].a);
        return;
    }
    const float z = abs(aux.y) * (Extra.x < 0.0f ? -1.0f : 1.0f);
    if (!(abs(z) > 1e-5f) || !isfinite(z))
    {
        OutColor[p] = float4(cur, InColor[p].a);
        return;
    }
    const float2 ndc = float2((float(p.x) + 0.5f) * Size.z * 2.0f - 1.0f, 1.0f - (float(p.y) + 0.5f) * Size.w * 2.0f);
    const float w = Extra.x * z;
    const float3 view = float3((ndc.x * w - Projection.z * z) / Projection.x,
                               (ndc.y * w - Projection.w * z) / Projection.y, z);
    const float4 v = float4(view, 1.0f);
    const float4 clip = float4(dot(PrevClip0, v), dot(PrevClip1, v), dot(PrevClip2, v), dot(PrevClip3, v));
    float4 key = float4(0.0f, 0.0f, 0.0f, 1.0f);
    bool valid = false;
    if (clip.w > 1e-6f && all(isfinite(clip)) && abs(Extra.y) > 1e-6f)
    {
        const float2 kndc = clip.xy / clip.w;
        const float2 q = float2((kndc.x + 1.0f) * 0.5f * Size.x, (1.0f - kndc.y) * 0.5f * Size.y);
        key = SampleHalf(InKey, q, half);
        const float2 kaux = SampleHalfAux(InKeyAux, q, half);
        const float expected = clip.w / Extra.y; // view z in the keyframe's frame
        valid = kaux.y > 0.0f && abs(kaux.x - abs(expected)) <= Extra.z * max(abs(expected), 1e-3f);
    }
    const float4 curBand = SampleHalf(InCur, float2(float(p.x) + 0.5f, float(p.y) + 0.5f), half);
    const float ratio = clamp(curBand.a / max(key.a, 1e-6f), Ratio.x, Ratio.y);
    const float blend = saturate(1.0f - aux.x / max(Extra.w, 1.0f)) * (valid ? 1.0f : 0.0f) * saturate(Strength);
    const float3 bandDelta = key.rgb * ratio - curBand.rgb;
    // Bound how far the recalled band may move the output: a different surface at the same depth can pass the depth
    // test, and this keeps its error to a fraction of the local wide level (see kBandDeltaClamp).
    const float bandLum = dot(bandDelta, float3(0.2126f, 0.7152f, 0.0722f));
    const float bandScale = min(1.0f, BandClamp * curBand.a / max(abs(bandLum), 1e-6f));
    float3 result = cur + (blend * bandScale) * bandDelta;
    if (!all(isfinite(result))) result = cur;
    OutColor[p] = float4(SanitizeRadiance(result), InColor[p].a);
}
