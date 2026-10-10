// Fog-consistent guides, pass 3 of 5: depth-aware median of kappa over (2r+1)^2 tiles.
//
// Fog and haze cover large areas. A lone tile with low kappa is the tile model failing, not fog: on cars, kerbs
// and foliage edges the lighting changes with the material (glass, paint, tyres), so the image does not follow
// tile lighting x guide. Flattening those guides moves real material contrast into the lighting, where RR blurs
// it and carries it through its history. The median over tiles at a similar depth drops islands that cover less
// than half of the window and keeps the typical value of extended regions (a maximum filter would also erase
// fog, whose estimates are noisy).
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), "

#define FOG_RANK_MAX_RADIUS 3
#define FOG_RANK_MAX_COUNT ((2 * FOG_RANK_MAX_RADIUS + 1) * (2 * FOG_RANK_MAX_RADIUS + 1))

Texture2D<float> InKappa : register(t0);
Texture2D<float4> InA : register(t1); // W: age (0: tile without geometry)
Texture2D<float4> InC : register(t2); // W: mean log depth
RWTexture2D<float> OutKappa : register(u0);

cbuffer CB_FogRank : register(b0)
{
    float2 TileSize;
    float ZTolerance; // log depth
    float Percentile; // 0..100, linear interpolation between ranks
    int Radius;       // tiles, at most FOG_RANK_MAX_RADIUS
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
    const float self = InKappa[t];
    if (!(InA[t].w > 0.0f))
    {
        OutKappa[t] = self;
        return;
    }
    const float logZ = InC[t].w;
    const int r = clamp(Radius, 0, FOG_RANK_MAX_RADIUS);

    // Insertion sort of the same-depth neighbours (at most 49 values per tile).
    float v[FOG_RANK_MAX_COUNT];
    int n = 0;
    for (int y = -r; y <= r; ++y)
    {
        for (int x = -r; x <= r; ++x)
        {
            const int2 q = t + int2(x, y);
            if (any(q < 0) || any(q >= tiles) || !(InA[q].w > 0.0f) || !(abs(InC[q].w - logZ) <= ZTolerance))
                continue;
            const float k = InKappa[q];
            int i = n;
            while (i > 0 && v[i - 1] > k)
            {
                v[i] = v[i - 1];
                --i;
            }
            v[i] = k;
            ++n;
        }
    }
    if (n == 0)
    {
        OutKappa[t] = self;
        return;
    }
    const float position = float(n - 1) * saturate(Percentile / 100.0f);
    const int i0 = int(floor(position));
    const int i1 = min(i0 + 1, n - 1);
    OutKappa[t] = lerp(v[i0], v[i1], position - float(i0));
}
