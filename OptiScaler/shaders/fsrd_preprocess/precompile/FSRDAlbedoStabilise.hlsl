// Albedo guide stabilisation (10 Oct)
//
// Cyberpunk's albedo guides flicker from frame to frame:
// - on water the specular guide varies ~35% per pixel over time and the diffuse guide ~30%;
// - on a wet street a third of the pixels flicker by more than 5%.
// The flicker follows the game's 4-frame sampling cycle (lag-1 autocorrelation -0.1, lag-4 +0.3), so it is
// sampling noise, not animation.
//
// RR denoises the demodulated lighting, but the composition multiplies the result by this frame's guide again,
// and that puts the flicker back on screen. Feeding RR a calm guide alone changes nothing: the composition has
// to remodulate with the calm guide too. Measured on the water captures with real AMD RR, relative RMSE against
// the raw temporal mean: 0.179 -> 0.106 and 0.218 -> 0.152.
//
// This pass runs after the packing shader. Per lobe it keeps an exponential average of the guide along the
// motion vectors:
// - bilinear history;
// - valid where last frame's depth at the target matches the expected previous depth (current depth plus the
//   depth delta) within DepthTolerance and the normal within ~25 deg;
// - otherwise it restarts from the current guide;
// - optionally clamped to the current guide's 3x3 range first.
// The stabilised guide replaces the packed one, and the lobe's demodulated lighting is rescaled so that, per
// channel, lighting * guide is unchanged:
//
//   L' = L * Q / Q'      with Q' stored exactly (UNORM8)
//
// Every pixel therefore hands RR the same energy as before, and the composition, which multiplies by the packed
// guide, reproduces it. Channels at or below the demodulation divisor floor keep their original pair.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 10), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 7), visibility = SHADER_VISIBILITY_ALL), "

#define THREAD_GROUP_SIZE_X     8
#define THREAD_GROUP_SIZE_Y     8

#define FLAGS_RESET             (1 << 0) // history invalid this frame: restart from the current guides
#define FLAGS_DIFFUSE           (1 << 1) // stabilise the diffuse guide as well (the specular one always)
#define FLAGS_CLAMP             (1 << 2) // clamp the reprojected history to the current guide's 3x3 range

Texture2D<float4> InSpecAlbedo : register(t0);   // packed specular guide (UNORM8), A: kept
Texture2D<float4> InDiffAlbedo : register(t1);   // packed diffuse guide (UNORM8), A: kept
Texture2D<float4> InSpecSignal : register(t2);   // demodulated specular lighting, A: hit distance (kept)
Texture2D<float4> InDiffSignal : register(t3);   // demodulated diffuse lighting, A: kept
Texture2D<float4> InMotion : register(t4);       // XY: previous UV - current UV, Z: previous - current view Z, W: valid
Texture2D<float> InLinearDepth : register(t5);   // signed linear view-space depth
Texture2D<float4> InNormals : register(t6);      // XY: octahedral normal (UNORM)
Texture2D<float4> InPrevSpec : register(t7);     // RGB: last frame's stabilised specular guide, A: its view Z
Texture2D<float4> InPrevDiff : register(t8);     // RGB: last frame's stabilised diffuse guide
Texture2D<float2> InPrevNormal : register(t9);   // last frame's octahedral normal (UNORM)

RWTexture2D<float4> OutHistSpec : register(u0);
RWTexture2D<float4> OutHistDiff : register(u1);
RWTexture2D<float2> OutHistNormal : register(u2);
RWTexture2D<float4> OutSpecAlbedo : register(u3);
RWTexture2D<float4> OutDiffAlbedo : register(u4);
RWTexture2D<float4> OutSpecSignal : register(u5);
RWTexture2D<float4> OutDiffSignal : register(u6);

cbuffer CB_AlbedoStabilise : register(b0)
{
    float4 DstTexSize;      // XY: render size, ZW: 1 / size
    float Rate;             // weight of the current frame in the average
    float DivisorFloor;     // the packing shader's demodulation divisor floor
    float DepthTolerance;   // relative depth agreement for a history tap
    uint Flags;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

float3 DecodeOctahedral(float2 encoded)
{
    const float2 e = encoded * 2.0f - 1.0f;
    float3 n = float3(e, 1.0f - abs(e.x) - abs(e.y));
    const float t = saturate(-n.z);
    n.x += n.x >= 0.0f ? -t : t;
    n.y += n.y >= 0.0f ? -t : t;
    return normalize(n);
}

// Replaces the guide where both the old and the new value are above the divisor floor, and rescales the
// lighting so that lighting * guide stays the same. Works on the UNORM8 levels: a channel whose level does not
// change keeps its original pair bit-exactly, and a changed one is rescaled by the exact ratio of the levels.
void Apply(float3 guide, float3 stabilised, float4 lighting, out float3 guideOut, out float4 lightingOut)
{
    const float3 levelIn = round(saturate(guide) * 255.0f);
    const float3 levelOut = round(saturate(stabilised) * 255.0f);
    const float minimumLevel = DivisorFloor * 255.0f;
    guideOut = guide;
    lightingOut = lighting;
    [unroll]
    for (int c = 0; c < 3; ++c)
    {
        if (levelOut[c] != levelIn[c] && levelIn[c] > minimumLevel && levelOut[c] > minimumLevel)
        {
            guideOut[c] = levelOut[c] / 255.0f;
            lightingOut[c] = min(lighting[c] * (levelIn[c] / levelOut[c]), 65504.0f);
        }
    }
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    const int2 px = int2(dtID.xy);
    const int2 size = int2(DstTexSize.xy);
    if (any(px >= size))
        return;

    const float4 specGuide = InSpecAlbedo[px];
    const float4 diffGuide = InDiffAlbedo[px];
    const float viewZ = InLinearDepth[px];
    const float2 octahedral = InNormals[px].xy;
    const bool diffuse = IsSet(FLAGS_DIFFUSE);

    float3 specStable = specGuide.rgb;
    float3 diffStable = diffGuide.rgb;
    const float4 motion = InMotion[px];
    [branch]
    if (!IsSet(FLAGS_RESET) && motion.w > 0.0f && isfinite(viewZ) && viewZ != 0.0f)
    {
        // Last frame's texel q holds the surface at (q + 0.5) / size, as this frame's does.
        const float2 position = float2(px) + motion.xy * DstTexSize.xy;
        const int2 base = int2(floor(position));
        const float2 f = position - float2(base);
        const float expectedZ = viewZ + motion.z;
        const float3 normal = DecodeOctahedral(octahedral);
        float3 specSum = 0.0f, diffSum = 0.0f;
        float weight = 0.0f;
        [unroll]
        for (int i = 0; i < 4; ++i)
        {
            const int2 offset = int2(i & 1, i >> 1);
            const int2 q = base + offset;
            if (any(q < 0) || any(q >= size))
                continue;
            const float w = (offset.x != 0 ? f.x : 1.0f - f.x) * (offset.y != 0 ? f.y : 1.0f - f.y);
            const float4 previous = InPrevSpec[q];
            if (!(abs(previous.a - expectedZ) <= DepthTolerance * abs(viewZ)))
                continue;
            if (dot(DecodeOctahedral(InPrevNormal[q]), normal) <= 0.9f)
                continue;
            specSum += w * previous.rgb;
            diffSum += w * InPrevDiff[q].rgb;
            weight += w;
        }
        // Rejected taps are left out and the rest renormalised; with less than half the footprint on this
        // surface the history is not trusted. (Requiring the full footprint restarted water every few frames:
        // one neighbour whose depth flickered past the tolerance was enough.)
        if (weight > 0.5f)
        {
            float3 specHistory = specSum / weight;
            float3 diffHistory = diffSum / weight;
            [branch]
            if (IsSet(FLAGS_CLAMP))
            {
                float3 specLow = specGuide.rgb, specHigh = specGuide.rgb;
                float3 diffLow = diffGuide.rgb, diffHigh = diffGuide.rgb;
                [unroll]
                for (int j = 0; j < 9; ++j)
                {
                    const int2 n = clamp(px + int2(j % 3 - 1, j / 3 - 1), int2(0, 0), size - 1);
                    const float3 s = InSpecAlbedo[n].rgb, d = InDiffAlbedo[n].rgb;
                    specLow = min(specLow, s); specHigh = max(specHigh, s);
                    diffLow = min(diffLow, d); diffHigh = max(diffHigh, d);
                }
                specHistory = clamp(specHistory, specLow, specHigh);
                diffHistory = clamp(diffHistory, diffLow, diffHigh);
            }
            specStable = specHistory + Rate * (specGuide.rgb - specHistory);
            if (diffuse)
                diffStable = diffHistory + Rate * (diffGuide.rgb - diffHistory);
        }
    }

    OutHistSpec[px] = float4(specStable, viewZ);
    OutHistDiff[px] = float4(diffStable, 0.0f);
    OutHistNormal[px] = octahedral;

    float3 specOut, diffOut;
    float4 specLighting, diffLighting;
    Apply(specGuide.rgb, specStable, InSpecSignal[px], specOut, specLighting);
    if (diffuse)
        Apply(diffGuide.rgb, diffStable, InDiffSignal[px], diffOut, diffLighting);
    else
    {
        diffOut = diffGuide.rgb;
        diffLighting = InDiffSignal[px];
    }
    OutSpecAlbedo[px] = float4(specOut, specGuide.a);
    OutDiffAlbedo[px] = float4(diffOut, diffGuide.a);
    OutSpecSignal[px] = specLighting;
    OutDiffSignal[px] = diffLighting;
}
