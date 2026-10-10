// Fog-consistent guides, pass 4 of 5: depth-aware Gaussian of kappa over tiles.
//
// Kappa sets the guide level the composition multiplies by. Where it changes faster than RR's filter footprint,
// RR mixes lighting demodulated by different guide levels and the remodulation leaves rectangles and colour
// bands; a 3-tile sigma keeps every change wider than that. Tiles at a very different depth do not mix.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), "

Texture2D<float> InKappa : register(t0);
Texture2D<float4> InA : register(t1); // W: age (0: tile without geometry)
Texture2D<float4> InC : register(t2); // W: mean log depth
RWTexture2D<float> OutKappa : register(u0);

cbuffer CB_FogSmooth : register(b0)
{
    float2 TileSize;
    float Sigma;     // tiles
    float ZSigma;    // log depth
    int Radius;      // tiles
    float3 _Reserved0;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    const int2 tiles = int2(TileSize);
    const int2 t = int2(dtID.xy);
    if (any(t >= tiles))
        return;
    const float logZ = InC[t].w;
    float sum = 0.0f, weight = 0.0f;
    for (int y = -Radius; y <= Radius; ++y)
    {
        for (int x = -Radius; x <= Radius; ++x)
        {
            // Edge tiles repeat, as a clamped image border does.
            const int2 q = clamp(t + int2(x, y), int2(0, 0), tiles - 1);
            const float w = exp(-float(x * x + y * y) / (2.0f * Sigma * Sigma)) *
                exp(-Square(InC[q].w - logZ) / (2.0f * ZSigma * ZSigma)) *
                max(InA[q].w > 0.0f ? 1.0f : 0.0f, 1e-3f);
            sum += w * InKappa[q];
            weight += w;
        }
    }
    OutKappa[t] = saturate(sum / weight);
}
