// Native post-motion anchor: bounded non-brightening recalled/current level ratio.
// Ratios outside the configured model band are rejected heuristically; a ratio is not proof
// that a change came from camera motion, and moderate genuine lighting steps can be corrected.
// Native fallback is identity. Params4.w requires a static centre and recall in its 3x3 tap
// neighbourhood; the centre does not need its own recall. Sparse neighbouring measurements
// can still affect new surfaces. Full-resolution bilinear gain sampling can cross moving edges.
// Captured key depth is positive; signed physical input depth itself is unchanged.
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 2)), DescriptorTable(UAV(u0, numDescriptors = 4)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
Texture2D<float4> InStats : register(t0);
Texture2D<float4> InRecalled : register(t1);
SamplerState InSampler : register(s0);
RWTexture2D<float4> OutGain : register(u0);
RWTexture2DArray<float4> OutKeyLevel : register(u1);
RWTexture2DArray<float> OutKeyDepth : register(u2);
RWByteAddressBuffer InSums : register(u3);

cbuffer CB_PostMotionAnchorGain : register(b0)
{
    float4 Size;
    float4 Params;
    float4 Params2;
    float4 Params3;
    float4 Params4;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 grid = int2(Size.z, Size.w);
    const int2 p = int2(dispatch.xy);
    if (any(p >= grid)) return;
    const float4 cell = InStats[p];

    if (Params4.x > 0.5f)
    {
        const int slice = int(clamp(Params4.y, 0.0f, max(Params4.z - 1.0f, 0.0f)));

        const bool valid = cell.z > 0.5f;
        OutKeyLevel[int3(p, slice)] = float4(valid ? cell.x : 0.0f, 0.0f, 0.0f, 0.0f);
        OutKeyDepth[int3(p, slice)] = valid ? abs(cell.y) : 0.0f;
    }
    const int step = int(clamp(Params2.z, 1.0f, 4.0f) + 0.5f);
    float numerator = 0.0f, denominator = 0.0f, coverage = 0.0f;
    [unroll] for (int dy = -1; dy <= 1; ++dy)
    {
        [unroll] for (int dx = -1; dx <= 1; ++dx)
        {
            const int2 q = clamp(p + int2(dx, dy) * step, int2(0, 0), grid - 1);
            const float4 stats = InStats[q];
            const float4 recalled = InRecalled[q];
            const float weight = recalled.y * recalled.w;
            numerator += recalled.x * weight;
            denominator += stats.x * weight;
            coverage += weight;
        }
    }

    const float frameLevel = float(InSums.Load(0u)) + float(InSums.Load(4u)) * 4294967296.0f;
    const float frameRecalled = float(InSums.Load(8u)) + float(InSums.Load(12u)) * 4294967296.0f;
    const uint frameCount = InSums.Load(16u);
    const float cells = max(Size.z * Size.w, 1.0f);
    const bool frameMeasured = frameLevel > 0u && frameCount > 0u;
    const float frameRatio = frameMeasured ? min(float(frameRecalled) / float(frameLevel), 4.0f) : 1.0f;
    const float modelExcess = Params.x * exp(-max(Params3.w, 0.0f) / max(Params.y, 1e-3f));
    const float frameCoverage = float(frameCount) / cells;
    if (frameMeasured && frameCoverage >= 0.15f &&
        (1.0f - frameRatio) > max(Params3.x * modelExcess, Params3.y))
    {
        OutGain[p] = float4(1.0f, 0.0f, 0.0f, 0.0f);
        return;
    }

    const float fallback = 1.0f;
    if (Params4.w > 0.5f && (cell.z < 0.5f || coverage < 0.5f))
    { OutGain[p] = float4(1.0f, 0.0f, 0.0f, 0.0f); return; }

    float measured = fallback;
    const bool measurable = coverage >= 0.5f && denominator > 1e-9f;
    if (measurable) measured = numerator / denominator;
    if (measurable && (1.0f - measured) > max(Params3.x * modelExcess, Params3.y))
    {

        OutGain[p] = float4(1.0f, 0.0f, 0.0f, 0.0f);
        return;
    }
    const float blend = saturate(coverage / max(Params2.w, 1e-3f));
    float gain = blend * measured + (1.0f - blend) * fallback;
    const float cap = min(modelExcess + Params.z, Params.w);
    gain = clamp(gain, Params3.z, 1.0f);
    gain = max(gain, 1.0f - cap);
    gain = 1.0f + saturate(Params2.x) * (gain - 1.0f);
    OutGain[p] = float4(gain, 0.0f, 0.0f, 0.0f);
}
