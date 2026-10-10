// Fog-consistent guides, pass 2 of 5: kappa per tile, the share of the guides' texture the image carries.
//
// Two estimates, both MAP with a prior centred on 1 (today's demodulation):
// - local: the tile's statistics pooled over a 3x3-tile tent, with a conservative bound (mean + Z sd), so that
//   noisy evidence keeps the guide. It is used where the guides have texture.
// - fill: a depth-aware Gaussian over (2r+1)^2 tiles without the bound. Where the guides have no texture, kappa
//   does not change what is printed, only how the guide level continues; it then follows the surroundings at a
//   similar depth instead of the prior, which would leave islands of kappa = 1 inside fog.
// The blend weight is the guides' texture contrast against the tile's radiance.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), "

Texture2D<float4> InA : register(t0); // Lbar_s.rgb, age
Texture2D<float4> InB : register(t1); // Lbar_d.rgb, mean radiance
Texture2D<float4> InC : register(t2); // N, D, S, mean log depth
RWTexture2D<float> OutKappa : register(u0);

cbuffer CB_FogKappa : register(b0)
{
    float2 TileSize;
    float Tau;          // prior sd of the local estimate
    float Z;            // conservative bound of the local estimate, in sd
    float TauFill;      // prior sd of the fill estimate
    float ZFill;
    float MassLocal;    // residual normaliser of the local sums
    float MassFill;     // residual normaliser of the fill sums
    float Sig0;         // texture contrast below which the fill is used
    float Sig1;         // contrast range of the blend
    float FillSigma;    // tiles
    float FillZSigma;   // log depth
    int FillRadius;     // tiles
    float3 _Reserved0;
}

float Solve(float N, float D, float S, float age, float mass, float tau, float z)
{
    const float k1 = N / max(D, 1e-30f);
    const float s2 = max(S - k1 * N, 0.0f) / mass;
    const float w1 = max(age, 1.0f) / max(s2, 1e-30f);
    const float ip = 1.0f / (tau * tau);
    const float P1 = D * w1 + ip;
    const float m1 = (N * w1 + ip) / P1;
    const float k = saturate(m1 + z * sqrt(1.0f / P1));
    return isfinite(k) ? k : 1.0f;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    const int2 tiles = int2(TileSize);
    const int2 t = int2(dtID.xy);
    if (any(t >= tiles))
        return;
    const float age = InA[t].w;
    if (!(age > 0.0f))
    {
        OutKappa[t] = 1.0f;
        return;
    }
    const float logZ = InC[t].w;

    // Local: edge-normalised 3x3 tent average of the tile sums.
    float4 local = 0.0f;
    float weightSum = 0.0f;
    [unroll]
    for (int j = -1; j <= 1; ++j)
    {
        [unroll]
        for (int i = -1; i <= 1; ++i)
        {
            const int2 q = t + int2(i, j);
            if (any(q < 0) || any(q >= tiles))
                continue;
            const float w = (i == 0 ? 2.0f : 1.0f) * (j == 0 ? 2.0f : 1.0f);
            local += w * float4(InC[q].xyz, InB[q].w);
            weightSum += w;
        }
    }
    local /= weightSum;
    const float kLocal = Solve(local.x, local.y, local.z, age, MassLocal, Tau, Z);

    // Fill: depth-aware Gaussian sums (tiles outside the screen or without geometry add nothing).
    float3 fill = 0.0f;
    for (int y = -FillRadius; y <= FillRadius; ++y)
    {
        for (int x = -FillRadius; x <= FillRadius; ++x)
        {
            const int2 q = t + int2(x, y);
            if (any(q < 0) || any(q >= tiles) || !(InA[q].w > 0.0f))
                continue;
            const float4 c = InC[q];
            const float w = exp(-float(x * x + y * y) / (2.0f * FillSigma * FillSigma)) *
                exp(-Square(c.w - logZ) / (2.0f * FillZSigma * FillZSigma));
            fill += w * c.xyz;
        }
    }
    const float kFill = Solve(fill.x, fill.y, fill.z, age, MassFill, TauFill, ZFill);

    const float contrast = sqrt(max(local.y, 0.0f) / MassLocal) / max(local.w, 1e-8f);
    const float w = saturate((contrast - Sig0) / Sig1);
    OutKappa[t] = w * kLocal + (1.0f - w) * kFill;
}
