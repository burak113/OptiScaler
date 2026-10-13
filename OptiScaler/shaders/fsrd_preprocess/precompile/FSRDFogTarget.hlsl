// Lighting-consistent guides, pass 5 of 6: the level each flattened guide moves toward.
//
// Where the image does not show the guides' texture (kappa < 1) the route flattens the guide toward this target.
// The target must be smooth at RR's filter scale: a guide step the image does not have becomes an inverse step in
// the demodulated lighting, RR blurs it, and the remodulation prints a contour. Water hands RR the sea floor's
// guides, depth and normals, so a "same surface" test by depth splits the water along the floor's own relief and
// keeps the print sharp (a 0.3-log-depth step at a sand bank). Here each tile averages the guide means of the
// tiles around it (Gaussian, sigma 4 tiles), weighted by how little of their texture the image shows (1 - kappa):
// water averages with water, not with the pier or a textured shore beside it. A loose log-depth term only keeps
// the sky and far haze apart from the ground.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2), visibility = SHADER_VISIBILITY_ALL), "

Texture2D<float> InKappa : register(t0); // FSRDFogSmooth output
Texture2D<float4> InG : register(t1);    // tile specular guide mean.rgb, mean log depth
Texture2D<float4> InH : register(t2);    // tile diffuse guide mean.rgb, fraction with depth
RWTexture2D<float4> OutTargetSpec : register(u0);
RWTexture2D<float4> OutTargetDiff : register(u1);

cbuffer CB_FogTarget : register(b0)
{
    float2 TileSize;
    float Sigma;     // tiles
    float ZSigma;    // log depth
    int Radius;      // tiles
    float3 _Reserved0;
}

// The Gaussian is wide (sigma 4 tiles) and the target only has to be smooth, so every second tile in each
// direction is enough: 9x9 taps instead of 17x17.
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    const int2 tiles = int2(TileSize);
    const int2 t = int2(dtID.xy);
    if (any(t >= tiles))
        return;
    const float4 g0 = InG[t];
    const float4 h0 = InH[t];
    const float logZ = g0.w;
    float3 sumSpec = 0.0f, sumDiff = 0.0f;
    float weight = 0.0f;
    for (int y = -Radius; y <= Radius; y += 2)
    {
        for (int x = -Radius; x <= Radius; x += 2)
        {
            const int2 q = t + int2(x, y);
            if (any(q < 0) || any(q >= tiles))
                continue;
            const float4 g = InG[q];
            const float4 h = InH[q];
            if (h.w <= 0.0f)
                continue;   // a tile without geometry has no surface to average
            const float w = exp(-float(x * x + y * y) / (2.0f * Sigma * Sigma)) *
                (saturate(1.0f - InKappa[q]) + 1e-3f) *
                exp(-Square(g.w - logZ) / (2.0f * ZSigma * ZSigma));
            sumSpec += w * g.rgb;
            sumDiff += w * h.rgb;
            weight += w;
        }
    }
    const bool has = weight > 1e-9f;
    OutTargetSpec[t] = float4(has ? sumSpec / weight : g0.rgb, 0.0f);
    OutTargetDiff[t] = float4(has ? sumDiff / weight : h0.rgb, 0.0f);
}
