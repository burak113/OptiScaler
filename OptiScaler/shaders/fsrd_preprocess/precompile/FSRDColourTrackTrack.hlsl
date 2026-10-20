// RR colour tracking (task 25 T2), experimental, default off - step 2 of 3, QUARTER RESOLUTION.
// Edge-aware smoothing of the quarter-res colour fields (5x5 taps `Params2.x` quarter-res cells apart, weighted by
// depth and normal similarity, so a coloured sign or a neon does not tint the grey wall next to it), then the
// reprojected EMA of RR's input colour (the target) and the luminance-preserving per-channel gain:
//   g = chroma(target) / chroma(RR colour), renormalised so luma(RR * g) == luma(RR) in the smoothed domain.
// The EMA is reprojected with the provider motion vectors and a relative depth test; a pixel whose warp is
// invalid (off screen, or the previous view held another surface) restarts from the current input colour.
// The default tap step of 2 cells is the measured production shape (a 16-pixel outer tap); the radius control
// only ever quantises to an integer number of cells, so the default reproduces the measured kernel exactly.
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 4)), DescriptorTable(UAV(u0, numDescriptors = 2)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
Texture2D<float4> InStats : register(t0);   // rgb this frame's colour, a depth (quarter resolution)
Texture2D<float4> InTarget : register(t1);  // rgb RR's input colour, a packed normal
Texture2D<float4> InMotion : register(t2);  // xy mean motion in full-res pixels, z mean depth delta, w 1
Texture2D<float4> InPrev : register(t3);    // rgb previous EMA target, a previous depth (quarter resolution)
SamplerState InSampler : register(s0);
RWTexture2D<float4> OutGain : register(u0);   // rgb the gain, a 1
RWTexture2D<float4> OutHist : register(u1);   // rgb the new EMA target, a this frame's depth
cbuffer CB_ColourTrackTrack : register(b0)
{
    float4 Size;    // full width, height, quarter width, quarter height
    float4 Params;  // x EMA weight, y depth tolerance, z strength, w previous history valid (0/1)
    float4 Params2; // x tap step in quarter-res cells (1..4), yzw unused
}
float2 UnpackNormal(float packed)
{
    const float q = floor(packed * 65535.0f + 0.5f);
    return (float2(floor(q / 256.0f), q - floor(q / 256.0f) * 256.0f) / 255.0f) * 2.0f - 1.0f;
}
// Same relative depth tolerance the reprojection test uses (the measured 2 %): a tap from another surface must
// not contribute to the smoothed colour, so the two gates agree instead of the smoothing being twice as strict.
float SurfaceWeight(float z, float tapZ, float3 n, float3 tapN, float tolerance)
{
    const float depth = saturate(1.0f - abs(z - tapZ) / max(tolerance * abs(z), 1e-3f));
    const float normal = saturate((dot(n, tapN) - 0.9f) * 10.0f);
    return isfinite(z) && isfinite(tapZ) && z * tapZ > 0.0f ? depth * depth * normal * normal : 0.0f;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 quarter = int2(Size.z, Size.w);
    const int2 p = int2(dispatch.xy);
    if (any(p >= quarter)) return;
    const float4 centre = InStats[p];
    const float4 centreTarget = InTarget[p];
    const float3 n = OctahedralDecode(UnpackNormal(centreTarget.a));
    const int step = int(clamp(Params2.x, 1.0f, 4.0f) + 0.5f);
    float3 colourSum = 0.0f, targetSum = 0.0f;
    float weightSum = 0.0f;
    [unroll] for (int dy = -2; dy <= 2; ++dy)
    {
        [unroll] for (int dx = -2; dx <= 2; ++dx)
        {
            const int2 q = clamp(p + int2(dx, dy) * step, int2(0, 0), quarter - 1);
            const float4 tap = InStats[q];
            const float4 tapTarget = InTarget[q];
            const float spatial = exp(-0.5f * float(dx * dx + dy * dy));
            const float w = spatial * SurfaceWeight(centre.a, tap.a, n,
                                                    OctahedralDecode(UnpackNormal(tapTarget.a)), Params.y);
            colourSum += w * tap.rgb;
            targetSum += w * tapTarget.rgb;
            weightSum += w;
        }
    }
    const float rcp = 1.0f / max(weightSum, 1e-6f);
    const float3 colour = colourSum * rcp;      // the smoothed RR output colour
    float3 source = targetSum * rcp;            // the smoothed RR input colour
    // The target the gain pushes towards: a reprojected EMA of the input colour (the truth), which is what RR's
    // own history lags. The warp uses the provider motion vectors and a relative depth test.
    float3 target = source;
    if (Params.w > 0.5f)
    {
        const float4 motion = InMotion[p];
        const float2 previous = (float2(p) + motion.xy / 4.0f);            // quarter-res cell -> previous frame
        const float2 uv = (previous + 0.5f) / float2(Size.zw);
        const float4 history = InPrev.SampleLevel(InSampler, uv, 0.0f);
        // A warp that leaves the frame is invalid even where clamp addressing would return a plausible edge
        // texel, and an invalid history is discarded once it is older than the depth tolerance allows.
        // Depth can be signed, so the sentinel is zero, not "not positive".
        if (all(uv >= 0.0f) && all(uv <= 1.0f) && abs(history.a) > 1e-9f)
        {
            const float expected = centre.a + motion.z;
            const bool valid = abs(history.a - expected) <= Params.y * max(abs(expected), 1e-3f);
            target = valid ? lerp(history.rgb, source, Params.x) : source;
        }
    }
    OutHist[p] = float4(target, centre.a);
    // Luminance-preserving per-channel gain from the smoothed RR colour to the target's chromaticity.
    const float lumaTarget = max(GetLuminance(target), 1e-9f);
    const float lumaColour = max(GetLuminance(colour), 1e-9f);
    float3 g = (target / lumaTarget) / max(colour / lumaColour, 1e-6f);
    g /= max(GetLuminance((colour / lumaColour) * g), 1e-9f);
    g = 1.0f + (clamp(g, 0.75f, 1.33f) - 1.0f) * Params.z;
    OutGain[p] = float4(g, 1.0f);
}
