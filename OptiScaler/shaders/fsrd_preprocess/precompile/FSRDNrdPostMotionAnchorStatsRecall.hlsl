// Native post-motion anchor: physical linear lobe inputs; shared host camera/ring policy.
// Each 8x8 cell uses four bilinear taps (sixteen selected source texels), not a full 64-texel mean.
// Current/recalled levels remain in physical units. Frame sums use emulated uint64 at 16.16:
// current low/high 0/4, recalled low/high 8/12, count 16, padded buffer size 32 bytes.
// A physical per-cell cap of 16 bounds each increment. The host clears all 32 bytes and
// records a UAV barrier before Gain. This measurement cannot identify the cause of a level change.
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 6)), DescriptorTable(UAV(u0, numDescriptors = 3)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
Texture2D<float4> InDiffuse : register(t0);
Texture2D<float4> InSpecular : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InMotion : register(t3);
Texture2DArray<float4> InKeyLevel : register(t4);
Texture2DArray<float> InKeyDepth : register(t5);
SamplerState InSampler : register(s0);
RWTexture2D<float4> OutStats : register(u0);
RWTexture2D<float4> OutRecalled : register(u1);
RWByteAddressBuffer OutSums : register(u2);
cbuffer CB_PostMotionAnchorStatsRecall : register(b0)
{
    float4 Size;
    float4 Projection;
    float4 Extra;
    float4 Params;
    float4 PrevRel[4];
    float4 ProjRow[4];
    uint4 KeySlice[2];
    float4 KeyRel[8][4];
    float4 SlotExtra[8];
}
static const float3 kLuma = float3(0.2126f, 0.7152f, 0.0722f);

struct Cell { float level; float depth; float2 motion; };
Cell BoxCell(int2 cell, float2 full)
{
    const float2 base = float2(cell) * 8.0f;

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

float StaticCell(float2 centre, float z, float2 motionUv, float2 full)
{
    if (!(abs(z) > 1e-5f) || !isfinite(z)) return 0.0f;
    const float4 v = float4(ViewPosition(centre, z, full), 1.0f);
    const float4 previous = float4(dot(PrevRel[0], v), dot(PrevRel[1], v), dot(PrevRel[2], v), dot(PrevRel[3], v));

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

        OutRecalled[p] = float4(0.0f, 0.0f, 0.0f, staticCell);
        return;
    }
    float recalled = 0.0f, valid = 0.0f, slice = 0.0f;
    const int2 gridSize = grid;
    if (staticCell > 0.5f)
    {
        const float4 v = float4(ViewPosition(centre, z, full), 1.0f);

        const uint ringSize = uint(max(Params.w, 1.0f));
        [loop] for (uint k = 0; k < 8u; ++k)
        {
            const uint slot = k < 4u ? KeySlice[0][k] : KeySlice[1][k - 4u];

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

    if (staticCell > 0.5f && valid > 0.5f)
    {
        const uint currentValue = uint(min(max(level, 0.0f), 16.0f) * 65536.0f);
        const uint recalledValue = uint(min(max(recalled, 0.0f), 16.0f) * 65536.0f);
        uint currentOld, recalledOld;
        OutSums.InterlockedAdd(0u, currentValue, currentOld);
        if (currentOld > 0xffffffffu - currentValue) OutSums.InterlockedAdd(4u, 1u);
        OutSums.InterlockedAdd(8u, recalledValue, recalledOld);
        if (recalledOld > 0xffffffffu - recalledValue) OutSums.InterlockedAdd(12u, 1u);
        OutSums.InterlockedAdd(16u, 1u);
    }
}
