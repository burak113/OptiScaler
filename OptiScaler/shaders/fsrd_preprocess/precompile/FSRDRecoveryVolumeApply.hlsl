// Volumetric restore, step 3 of 3: add the accumulated positive shortfall back to
// RR's composed output. RR's image is never filtered or replaced; this pass only
// adds a smooth layer of the energy RR removed from the input.
// The tile layer is spread over a 6x6-tile tent (about 40 px) with weights that also
// respect depth, so a foreground silhouette does not inherit the fog behind it. Fog is
// smooth at that scale, and averaging 25+ tiles keeps the unclipped means' noise from
// reaching the screen as flicker.
#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 4)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<half4> InComposed : register(t0);
Texture2D<half4> InHistory : register(t1);    // FSRDRecoveryVolumeAccumulate output
Texture2D<float> InLinearDepth : register(t2);
Texture2D<float4> InVariance : register(t3);
RWTexture2D<half4> OutColor : register(u0);

cbuffer CB_VolumeApply : register(b0)
{
    float4 DstTexSize; // XY = size, ZW = 1 / size
    float Strength;
    uint Debug; // 0: output, 1: signed correction (grey = zero), 2: confidence
    float2 _Reserved0;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    const int2 p = int2(id.xy), size = int2(DstTexSize.xy);
    if (any(p >= size))
        return;
    const float4 composed = InComposed[p];
    // Zero strength preserves all stored channels, including negative HDR values.
    if (Strength <= 0.0f && Debug == 0)
    {
        OutColor[p] = InComposed[p];
        return;
    }
    const int2 tiles = (size + 7) / 8;
    const float z = abs(InLinearDepth[p]);
    const float2 position = (float2(p) + 0.5f) / 8.0f - 0.5f;
    const int2 origin = int2(floor(position));
    float3 layer = 0.0f;
    float total = 0.0f;
    float variance = 0.0f;
    float maturity = 0.0f;
    [unroll]
    for (uint i = 0; i < 36; ++i)
    {
        const int2 offset = int2(i % 6, i / 6) - 2;
        const int2 tile = origin + offset;
        // Do not count clamped duplicate taps as independent evidence.
        if (any(tile < 0) || any(tile >= tiles))
            continue;
        const float4 history = InHistory[tile];
        const float2 axis = saturate(1.0f - abs(position - float2(origin + offset)) / 3.0f);
        float weight = axis.x * axis.y;
        if (isfinite(z) && z > 0.0f)
            weight *= Square(saturate(1.0f - abs(float(history.a) - z) / max(0.1f * z, 1e-3f)));
        const float4 stats = InVariance[tile];
        if (all(isfinite(history)) && all(isfinite(stats)) && stats.x >= 0.0f && history.a > 0.0f)
        {
            total += weight;
            // Two or more temporal observations make a tile mature;
            // an arbitrary long warm-up would erase short static intervals.
            if (stats.y >= 2.0f)
            {
                layer += weight * float3(history.rgb);
                variance += Square(weight) * stats.x;
                maturity += weight;
            }
        }
    }
    // Average signed differences BEFORE clamping:
    // positive-only tile averages would rectify zero-mean noise into light.
    const float3 difference = maturity > 1e-4f ? layer / maturity : 0.0f;
    const float sigma = maturity > 1e-4f ? sqrt(max(variance, 0.0f)) / maturity : 0.0f;
    const float energy = GetLuminance(difference);
    const bool mature = total > 1e-4f && maturity >= 0.5f * total;
    const bool supported = mature && isfinite(z) && z > 0.0f;
    // Confidence is diagnostic only: heavy-tailed energy can have high variance.
    const float confidence = supported ? saturate(energy / max(4.0f * sigma, 1e-6f)) : 0.0f;
    const float3 correction = supported ? Strength * max(difference, 0.0f) : 0.0f;
    if (Debug == 1)
        OutColor[p] = half4(saturate(0.5f + 0.5f * difference / max(abs(composed.rgb), 0.01f)), composed.a);
    else if (Debug == 2)
        OutColor[p] = half4(confidence.xxx, composed.a);
    else
        OutColor[p] = half4(FloorRadiance(composed.rgb + correction), composed.a);
}
