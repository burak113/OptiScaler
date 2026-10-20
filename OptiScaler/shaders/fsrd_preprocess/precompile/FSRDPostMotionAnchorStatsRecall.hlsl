// Post-motion level anchor (task 25 T3 ii), experimental, default off - step 1 of 3, 1/8 RESOLUTION.
// Per 8x8 cell: the input's composite luminance level (a true 16-texel box mean, four hardware bilinear taps -
// the same construction the colour-track statistics use), the cell's mean depth, and whether the cell's motion is
// explained by the camera alone (the static-geometry mask: moving content must not enter the level comparison).
// The same dispatch recalls, for every cell, the settled level of the most recent keyframe that also saw that
// surface: the cell's depth is unprojected to view space and pushed through the per-slot relative matrix
// (current view space -> keyframe clip space, built on the host), and the keyframe's depth must agree with the
// reprojected depth within the relative tolerance. The recalled level, its validity, the slice it came from and
// the current level all land in one texture, so the gain pass smooths both sides with the identical kernel.
// The ring is only READ here: the keyframe capture lives in the gain pass, because one texture may not be an
// SRV and a UAV in the same dispatch (the fixture's debug layer caught exactly that). The memory the
// gain pass stores is the level BEFORE the gain, which keeps the anchor's own corrections out of the
// reference (the lab prototype measured that a post-RR memory would need "capture only while inert",
// which kills it on rapid flick sequences).
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 6)), DescriptorTable(UAV(u0, numDescriptors = 3)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
Texture2D<float4> InDiffuse : register(t0);   // RR's input diffuse, full resolution, game units
Texture2D<float4> InSpecular : register(t1);  // RR's input specular, full resolution, game units
Texture2D<float> InDepth : register(t2);      // linear depth, full resolution
Texture2D<float4> InMotion : register(t3);    // canonical motion: xy UV displacement, z depth delta
Texture2DArray<float4> InKeyLevel : register(t4); // the ring: composite input level per slice, 1/8 resolution
Texture2DArray<float> InKeyDepth : register(t5);  // the ring: depth per slice, 1/8 resolution
SamplerState InSampler : register(s0);
RWTexture2D<float4> OutStats : register(u0);    // x current level, y depth, z static (0/1), w 0
RWTexture2D<float4> OutRecalled : register(u1); // x recalled level, y valid, z slice, w static
RWByteAddressBuffer OutSums : register(u2);    // frame-level fixed-point sums: num, den, count
cbuffer CB_PostMotionAnchorStatsRecall : register(b0)
{
    float4 Size;        // full width, height, 1/8 width, 1/8 height
    float4 Projection;  // current P00, P11, P02, P12
    float4 Extra;       // x current P32, y depth tolerance, z active, w refresh
    float4 Params;      // x strength, y min static, z min recall, w ring write slice
    float4 PrevRel[4];  // current view space -> the previous frame's view space, row by row
    float4 ProjRow[4];  // the current projection, row by row (the previous frame's is not republished)
    uint4 KeySlice[2];  // 8 ring slice indices, priority order
    float4 KeyRel[8][4]; // current view space -> keyframe clip space, row by row
    float4 SlotExtra[8]; // x key P32, y valid, zw unused
}
static const float3 kLuma = float3(0.2126f, 0.7152f, 0.0722f);
// A bilinear tap on the boundary between a 2x2 group returns that group's mean, so four of them reproduce the
// 16-texel box mean the colour-track statistics also build (the tap offset is i*4 + 2, not i*4 + 0.5: see
// FSRDColourTrackStats.hlsl for the sparse-tap bug that construction exists to avoid).
// The cell keeps the composite level, the mean depth and BOTH motion components: the static-geometry test compares
// the motion field against the camera-only displacement in full-resolution pixels, so dropping the y component
// (an earlier version of this shader did) makes the test fail exactly during a flick, when the displacement is
// mostly vertical - the measurement then dies on the frames the anchor exists for.
struct Cell { float level; float depth; float2 motion; };
Cell BoxCell(int2 cell, float2 full)
{
    const float2 base = float2(cell) * 8.0f;
    // Active render size can be smaller than the allocated source texture in DRS.
    uint diffuseWidth, diffuseHeight, specularWidth, specularHeight;
    uint depthWidth, depthHeight, motionWidth, motionHeight;
    InDiffuse.GetDimensions(diffuseWidth, diffuseHeight);
    InSpecular.GetDimensions(specularWidth, specularHeight);
    InDepth.GetDimensions(depthWidth, depthHeight);
    InMotion.GetDimensions(motionWidth, motionHeight);
    Cell sum;
    sum.level = 0.0f; sum.depth = 0.0f; sum.motion = float2(0.0f, 0.0f);
    [unroll] for (int j = 0; j < 2; ++j)
        [unroll] for (int i = 0; i < 2; ++i)
        {
            const float2 pixel = base + float2(i * 4 + 2.0f, j * 4 + 2.0f);
            sum.level += dot(InDiffuse.SampleLevel(InSampler, pixel / float2(diffuseWidth, diffuseHeight), 0.0f).rgb, kLuma) +
                         dot(InSpecular.SampleLevel(InSampler, pixel / float2(specularWidth, specularHeight), 0.0f).rgb, kLuma);
            sum.depth += InDepth.SampleLevel(InSampler, pixel / float2(depthWidth, depthHeight), 0.0f);
            sum.motion += InMotion.SampleLevel(InSampler, pixel / float2(motionWidth, motionHeight), 0.0f).xy;
        }
    sum.level *= 0.25f; sum.depth *= 0.25f; sum.motion *= 0.25f;
    return sum;
}
// View space position of a full-resolution pixel at linear depth z, in the engine's projection convention
// (P32 turns view z into the clip w - the same reconstruction FSRDPostFlickApply.hlsl uses).
float3 ViewPosition(float2 pixel, float z, float2 full)
{
    const float2 ndc = float2((pixel.x + 0.5f) / full.x * 2.0f - 1.0f, 1.0f - (pixel.y + 0.5f) / full.y * 2.0f);
    const float w = Extra.x * z;
    return float3((ndc.x * w - Projection.z * z) / Projection.x, (ndc.y * w - Projection.w * z) / Projection.y, z);
}
float2 ProjectToPixels(float4 clip, float2 full)
{
    const float2 ndc = clip.xy / clip.w;
    return float2((ndc.x + 1.0f) * 0.5f * full.x, (1.0f - ndc.y) * 0.5f * full.y);
}
// 1 when the cell's centre pixel moved the way the camera alone would have moved it. The motion texture is a UV
// displacement; the camera-induced displacement is reprojected through the previous frame's view (the projection
// is not republished per frame, so a projection change can only make the test stricter, never looser).
float StaticCell(float2 centre, float z, float2 motionUv, float2 full)
{
    if (!(abs(z) > 1e-5f) || !isfinite(z)) return 0.0f;
    const float4 v = float4(ViewPosition(centre, z, full), 1.0f);
    const float4 previous = float4(dot(PrevRel[0], v), dot(PrevRel[1], v), dot(PrevRel[2], v), dot(PrevRel[3], v));
    // The previous view-space point still has to be projected: the projection is not republished per frame, so the
    // current one stands in (a projection change can only make this test stricter, never looser).
    const float4 clip = float4(dot(ProjRow[0], previous), dot(ProjRow[1], previous), dot(ProjRow[2], previous),
                               dot(ProjRow[3], previous));
    if (!(clip.w > 1e-6f) || !all(isfinite(clip))) return 0.0f;
    const float2 analytic = ProjectToPixels(clip, full) - centre;
    const float2 measured = motionUv * full;
    const float2 residual = measured - analytic;
    return dot(residual, residual) <= 4.0f * 4.0f ? 1.0f : 0.0f;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 grid = int2(Size.z, Size.w);
    const int2 p = int2(dispatch.xy);
    if (any(p >= grid)) return;
    const float2 full = Size.xy;
    if ((Extra.z < 0.5f && Extra.w < 0.5f) || Extra.x == 0.0f)
    {
        // Not armed, outside the window, or no usable projection: the pass is inert, but it writes defined values
        // so a later dispatch can never read an unwritten texture.
        OutStats[p] = 0.0f;
        OutRecalled[p] = 0.0f;
        return;
    }
    const Cell cell = BoxCell(p, full);
    const float level = cell.level;
    const float depth = cell.depth;
    const float2 centre = float2(p) * 8.0f + 4.0f;
    const float z = abs(depth) * (Extra.x < 0.0f ? -1.0f : 1.0f);
    const float staticCell = StaticCell(centre, z, cell.motion, full);
    OutStats[p] = float4(level, depth, staticCell, 0.0f);
    if (Extra.z < 0.5f)
    {
        // Capture-only frame: publish statistics, but never recall/apply a level correction.
        OutRecalled[p] = float4(0.0f, 0.0f, 0.0f, staticCell);
        return;
    }
    float recalled = 0.0f, valid = 0.0f, slice = 0.0f;
    const int2 gridSize = grid;
    if (staticCell > 0.5f)
    {
        const float4 v = float4(ViewPosition(centre, z, full), 1.0f);
        // The host writes the ring size into Params.w (it is 6 since the N1 fix, was 8): the sentinel it puts in
        // every unused priority slot IS that value, so the check must use it - with a literal 8 the loop would
        // trust slot 6 and read the constant buffer's stale tail (caught by the anchor fixture after the ring
        // change: the settled-memory recall returned nothing).
        const uint ringSize = uint(max(Params.w, 1.0f));
        [loop] for (uint k = 0; k < 8u; ++k)
        {
            const uint slot = k < 4u ? KeySlice[0][k] : KeySlice[1][k - 4u];
            // The host puts a ring-size sentinel in every unused priority slot, so the loop can stop at the end
            // of the valid list; an invalid slot is skipped rather than trusted.
            if (slot >= ringSize || SlotExtra[slot].y < 0.5f) continue;
            const float4 clip = float4(dot(KeyRel[slot][0], v), dot(KeyRel[slot][1], v), dot(KeyRel[slot][2], v),
                                       dot(KeyRel[slot][3], v));
            const float keyP32 = SlotExtra[slot].x;
            if (!(clip.w > 1e-6f) || !all(isfinite(clip)) || !(abs(keyP32) > 1e-6f)) continue;
            const float2 q = ProjectToPixels(clip, full);
            const float2 uv = q / full;
            if (any(uv < 0.0f) || any(uv > 1.0f)) continue;
            const float expected = abs(clip.w / keyP32);
            const float keyDepth = InKeyDepth.SampleLevel(InSampler, float3(uv, float(slot)), 0.0f);
            const float tolerance = Extra.y * max(expected, 1e-3f);
            if (!(abs(keyDepth - expected) <= tolerance)) continue;
            recalled = InKeyLevel.SampleLevel(InSampler, float3(uv, float(slot)), 0.0f).x;
            valid = 1.0f;
            slice = float(slot);
            break;
        }
    }
    OutRecalled[p] = float4(recalled, valid, slice, staticCell);
    // The frame-level sums the gain pass's guard needs (the prototype's frame-level reject and fallback, which a
    // per-cell measurement cannot reproduce - measured on 2405). BOTH sides accumulate over the SAME set - the
    // static cells that also recalled a keyframe level - because a ratio of two different sets is the true ratio
    // times the recall coverage (rho), and rho < 0.75 then rejects a frame whose real excess is well inside the
    // band: the audit (SA15) measured exactly that on 87ee f41-46 and 22f9 f41-43, the frames that create the
    // trail. Fixed point 1/1024 with a 16.0 ceiling per cell, so the worst case (a whole 1440p frame at the
    // ceiling) stays far inside uint32.
    if (staticCell > 0.5f && valid > 0.5f)
    {
        OutSums.InterlockedAdd(0u, uint(min(level, 16.0f) * 1024.0f));
        OutSums.InterlockedAdd(4u, uint(min(recalled, 16.0f) * 1024.0f));
        OutSums.InterlockedAdd(8u, 1u);
    }
}
