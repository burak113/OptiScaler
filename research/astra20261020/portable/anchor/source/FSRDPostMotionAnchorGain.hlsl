// Post-motion level anchor (task 25 T3 ii), experimental, default off - step 2 of 3, 1/8 RESOLUTION.
// The luminance gain: over a 3x3 tap window (kTapStepCells cells apart, sparse when the cell is small) the
// brightness-weighted ratio between the recalled settled level and the current level, weighted by the recall
// validity and the static mask so moving content and unreproducible cells cannot enter the measurement.
//   g = sum(recalled * w) / sum(level * w),  w = valid * static
// The gain is then bounded by the T1 model band (dose(k) = A exp(-k/tau) + margin, hard cap), clamped to
// [kGainLow, 1] so it can never brighten, and rejected outright when the measured excess is far above the band:
// a real light change, an explosion or a muzzle flash is not the post-motion excess and keeps gain 1.
// Cells with no recall fall back to NO correction (gain 1, the N2 guard), blended in with the coverage; the
// model band still caps whatever the measurement does produce.
// This pass also captures the keyframe the ring's next slice receives, for the frames the host marked settled.
// The output is a single scalar per cell; the apply pass puts the same factor on R, G and B (luma only, so the
// chroma is untouched - the pre-test's per-channel gain is what made the pink trail worse).
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 2)), DescriptorTable(UAV(u0, numDescriptors = 4)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
Texture2D<float4> InStats : register(t0);     // x current level, y depth, z static, w refresh
Texture2D<float4> InRecalled : register(t1);  // x recalled level, y valid, z slice, w static
SamplerState InSampler : register(s0);
RWTexture2D<float4> OutGain : register(u0);
RWTexture2DArray<float4> OutKeyLevel : register(u1);
RWTexture2DArray<float> OutKeyDepth : register(u2);
RWByteAddressBuffer InSums : register(u3);      // frame-level sums, read only (the host clears them before the
                                                // statistics pass: a reset inside this dispatch would race the reads)
cbuffer CB_PostMotionAnchorGain : register(b0)
{
    float4 Size;    // full width, height, 1/8 width, 1/8 height
    float4 Params;  // x band A, y band tau, z cap extra, w cap hard
    float4 Params2; // x strength, y fallback A, z tap step (cells), w coverage taps
    float4 Params3; // x reject mult, y reject abs, z gain low, w window k
    float4 Params4; // x refresh (0/1), y ring write slice, zw unused
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 grid = int2(Size.z, Size.w);
    const int2 p = int2(dispatch.xy);
    if (any(p >= grid)) return;
    const float4 cell = InStats[p];
    // The keyframe capture (host decision: settled camera, at most every kSampleFrames frames). The stored
    // level is the input BEFORE the gain, so the anchor can never pollute its own reference, and only a cell
    // whose motion the camera alone explains is stored: a moving object must not become the settled level.
    if (Params4.x > 0.5f)
    {
        const int slice = int(clamp(Params4.y, 0.0f, max(Params4.z - 1.0f, 0.0f)));
        // Every cell is overwritten on slot reuse: invalid/moving cells may not keep
        // an older frame's level/depth under this frame's newly published camera.
        const bool valid = cell.z > 0.5f;
        OutKeyLevel[int3(p, slice)] = float4(valid ? cell.x : 0.0f, 0.0f, 0.0f, 0.0f);
        OutKeyDepth[int3(p, slice)] = valid ? cell.y : 0.0f;
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
    // The frame-level measurement: the brightness-weighted ratio over every static cell of the frame, which is the
    // prototype's guard (the per-cell version could not reproduce it: on 2405 the local excesses sit below the
    // threshold while the frame-level one does not). A frame whose measured excess is far above the band is a real
    // lighting change, not the post-motion excess: the whole frame keeps gain 1.
    const uint frameLevel = InSums.Load(0u), frameRecalled = InSums.Load(4u), frameCount = InSums.Load(8u);
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
    // The fallback is the frame-level measured ratio (the prototype's shape) where the frame has a usable
    // measurement, and NO correction where it has none (SA18 2026-10-20, task 25 N2): the model gain darkened
    // whole flick frames by 12-15 % unmeasured - the frames whose recall coverage falls under the gate are the
    // fast-motion frames, where the keyframes cannot match by construction, and the measured prototype does
    // nothing there. Measured out/in at the affected frames: 2405 f43 0.988 -> 0.840, 22f9 f13 0.971 -> 0.832,
    // 87ee f8 0.952 -> 0.810; with this guard all of them return to the prototype's value within 0.004, and the
    // 87ee f60 / 22f9 f52 / 2405 f92 table numbers are unchanged (<= 0.2 %).
    const float fallback = (frameMeasured && frameCoverage >= 0.15f) ? min(frameRatio, 1.0f) : 1.0f;
    // A cell with no recalled, static data at all cannot measure anything: with the N2 guard the fallback is 1
    // (no correction), matching the measured prototype on the low-coverage frames.
    float measured = fallback;
    const bool measurable = coverage >= 0.5f && denominator > 1e-9f;
    if (measurable) measured = numerator / denominator;
    if (measurable && (1.0f - measured) > max(Params3.x * modelExcess, Params3.y))
    {
        // Far above the model band: this is not the post-motion excess (a light switch, a flash, drifting
        // content), so the cell keeps gain 1 instead of correcting a real change away.
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
