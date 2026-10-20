// RR colour tracking (task 25 T2), experimental, default off - step 1 of 3, QUARTER RESOLUTION.
// Downsampled colour statistics for the gain field: RR's output colour, RR's input colour (the truth RR's lag
// lost), the motion field (mean MV and mean depth delta for the reprojection) and the guides (depth, octahedral
// normal). Every field is a 4x4 box mean taken with four hardware bilinear taps per quarter-res texel: a bilinear
// tap on the boundary between a 2x2 group returns that group's mean, so four taps reproduce the 16-texel box.
// The tap offset is i*2 + 1 (not + 0.5): with the (index + 0.5)/size texel-centre convention, an offset of 1.0
// from the box origin is the midpoint of texels {base, base+1} and an offset of 3.0 of {base+2, base+3}. The
// earlier + 0.5 sampled exact texels base and base+2 instead, which made this a sparse four-texel sample of the
// 16-texel cell rather than its mean (a single firefly would then pass through at weight 1/4).
// The motion is read in the conversion's canonical form - XY is a UV displacement, Z the depth delta - and is
// scaled to full-resolution pixels here, because the tracking pass works in quarter-res cells.
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 5)), DescriptorTable(UAV(u0, numDescriptors = 3)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
Texture2D<float4> InColor : register(t0);      // the composite of this frame (RR's output), full resolution
Texture2D<float4> InTarget : register(t1);     // RR's input colour in output units, full resolution
Texture2D<float4> InMotion : register(t2);     // xy current-previous ROI UV, z previous-current linear depth
Texture2D<float> InDepth : register(t3);       // linear depth
Texture2D<float4> InNormals : register(t4);    // xy octahedral normal (world, Z up)
SamplerState InSampler : register(s0);
RWTexture2D<float4> OutStats : register(u0);   // rgb the frame's colour, a its quarter-res depth
RWTexture2D<float4> OutTarget : register(u1);  // rgb RR's input colour, a the packed octahedral normal
RWTexture2D<float4> OutMotion : register(u2);  // xy mean motion in full-res pixels, z mean depth delta, w 1
cbuffer CB_ColourTrackStats : register(b0)
{
    float4 Size;    // full width, height, quarter width, quarter height
}
float2 BoxUv(float2 base, float2 sub, float2 full)
{
    return (base + sub) / full;
}
float4 SampleBox(Texture2D<float4> source, int2 box, float2 full)
{
    const float2 base = float2(box) * 4.0f;
    float4 sum = 0.0f;
    [unroll] for (int j = 0; j < 2; ++j)
        [unroll] for (int i = 0; i < 2; ++i)
            sum += source.SampleLevel(InSampler, BoxUv(base, float2(i * 2 + 1.0f, j * 2 + 1.0f), full), 0.0f);
    return sum * 0.25f;
}
float SampleBoxDepth(int2 box, float2 full)
{
    const float2 base = float2(box) * 4.0f;
    float sum = 0.0f;
    [unroll] for (int j = 0; j < 2; ++j)
        [unroll] for (int i = 0; i < 2; ++i)
            sum += InDepth.SampleLevel(InSampler, BoxUv(base, float2(i * 2 + 1.0f, j * 2 + 1.0f), full), 0.0f);
    return sum * 0.25f;
}
// Two 8-bit octahedral components in one half; a normal similarity test needs no more.
float PackNormal(float2 octahedral)
{
    const float2 q = floor(saturate(octahedral * 0.5f + 0.5f) * 255.0f + 0.5f);
    return (q.x * 256.0f + q.y) / 65535.0f;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 quarter = int2(Size.z, Size.w);
    const int2 p = int2(dispatch.xy);
    if (any(p >= quarter)) return;
    const float2 full = Size.xy;
    const float4 colour = SampleBox(InColor, p, full);
    const float4 target = SampleBox(InTarget, p, full);
    const float4 motion = SampleBox(InMotion, p, full);
    const float depth = SampleBoxDepth(p, full);
    const float4 normals = SampleBox(InNormals, p, full);
    OutStats[p] = float4(SanitizeRadiance(colour.rgb), depth);
    OutTarget[p] = float4(SanitizeRadiance(target.rgb), PackNormal(normals.xy));
    // Canonical motion is a UV displacement; the tracking pass reprojects in quarter-res cells, so the mean
    // full-resolution pixel motion is what it needs (uv * size).
    OutMotion[p] = float4(motion.xy * Size.xy, motion.z, 1.0f);
}
