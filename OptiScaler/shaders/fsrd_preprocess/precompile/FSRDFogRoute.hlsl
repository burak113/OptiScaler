// Fog-consistent guides, pass 5 of 5: rewrite the pair RR and the composition use, energy-exact.
//
// With kappa the share of the guides' texture the image carries (bilinear from the tiles):
// 1. Every depth: each lobe's guide is flattened toward the mean guide of the same surface (a depth-aware 5x5-tile
//    mean), Q1 = kappa Q + (1 - kappa) T. The level is kept, only the texture the image does not show goes.
// 2. With distance (weight w from Near to Far, log scale) the fog share m = w (1 - kappa) also leaves the
//    diffuse lobe and joins the specular lobe, whose guide moves toward 1, the sky's: haze and the sky behind a
//    silhouette then demodulate to the same light and RR has no step to smear into the ridge. Near surfaces are
//    left in their lobes: in noisy night scenes RR's specular path keeps a different share of heavy-tailed
//    light, and moving near light there brightened pavement by 5-14%.
// Per channel the radiance each lobe hands RR is preserved exactly (lighting x guide); a kappa of 1 keeps the
// pair bit-exact. The diffuse lobe is left alone where any channel is at or below the divisor floor (its light
// is negligible and per-channel decisions there made colour bands), and its kept share fades out continuously
// as its scaled guide approaches the floor.
//
// Quality depends on capture, history and measurement definition. Historical c2cbdeeb
// ridge improvements do not imply general fine-detail, motion or night-energy acceptance.
// Current per-capture native RR results, retained failures and source identities are in
// tools_tmp/team_20261010/fog_handoff.md; the 8-60 m routing ramp remains unchanged.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 8), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 4), visibility = SHADER_VISIBILITY_ALL), "

#define FLAGS_DEBUG_KAPPA (1 << 0) // write kappa into the guides' alpha for inspection (no rewrite)

Texture2D<float4> InSpecAlbedo : register(t0);  // the pair to rewrite (UNORM8 guides)
Texture2D<float4> InDiffAlbedo : register(t1);
Texture2D<float4> InSpecSignal : register(t2);  // A: hit distance (kept)
Texture2D<float4> InDiffSignal : register(t3);
Texture2D<float> InLinearDepth : register(t4);
Texture2D<float> InKappa : register(t5);        // FSRDFogSmooth output
Texture2D<float4> InG : register(t6);           // tile specular guide mean.rgb, mean log depth
Texture2D<float4> InH : register(t7);           // tile diffuse guide mean.rgb, fraction with depth

RWTexture2D<float4> OutSpecAlbedo : register(u0);
RWTexture2D<float4> OutDiffAlbedo : register(u1);
RWTexture2D<float4> OutSpecSignal : register(u2);
RWTexture2D<float4> OutDiffSignal : register(u3);

cbuffer CB_FogRoute : register(b0)
{
    float4 DstTexSize;    // XY: render size, ZW: 1 / size
    float2 TileSize;
    float DivisorFloor;
    float LogNear;        // log of the distance where moving the fog share starts
    float InvLogRange;    // 1 / log(Far / Near)
    float TargetZSigma;   // log-depth tolerance of the same-surface guide mean
    uint Flags;
    float _Reserved0;
}

int2 ClampTile(int2 t) { return clamp(t, int2(0, 0), int2(TileSize) - 1); }

// Every pixel of an 8x8 group reads its guide means from the same 7x7 tiles around the group's tile.
groupshared float4 g_G[49];
groupshared float4 g_H[49];

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID, uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const int2 px = int2(dtID.xy);
    const int2 size = int2(DstTexSize.xy);
    const int2 blockOrigin = int2(groupID.xy) - 3;
    const uint flatID = gtID.x + gtID.y * 8;
    if (flatID < 49)
    {
        const int2 t = blockOrigin + int2(flatID % 7, flatID / 7);
        const bool inside = all(t >= 0) && all(t < int2(TileSize));
        g_G[flatID] = inside ? InG[t] : 0.0f;
        g_H[flatID] = inside ? InH[t] : 0.0f;   // W = 0: no weight
    }
    GroupMemoryBarrierWithGroupSync();
    if (any(px >= size))
        return;
    const float4 specGuide = InSpecAlbedo[px];
    const float4 diffGuide = InDiffAlbedo[px];
    const float4 specSignal = InSpecSignal[px];
    const float4 diffSignal = InDiffSignal[px];
    const int2 tiles = int2(TileSize);

    // Kappa, bilinear between tile centres.
    const float2 tp = (float2(px) + 0.5f) / 8.0f - 0.5f;
    const int2 t0 = int2(floor(tp));
    const float2 f = tp - float2(t0);
    const float kappa = saturate(
        lerp(lerp(InKappa[ClampTile(t0)], InKappa[ClampTile(t0 + int2(1, 0))], f.x),
             lerp(InKappa[ClampTile(t0 + int2(0, 1))], InKappa[ClampTile(t0 + int2(1, 1))], f.x), f.y));

    if ((Flags & FLAGS_DEBUG_KAPPA) != 0)
    {
        OutSpecAlbedo[px] = float4(specGuide.rgb, kappa);
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }
    const float floorLevel = DivisorFloor * 255.0f;
    const float3 qs = specGuide.rgb, qd = diffGuide.rgb;
    const float3 qs8 = round(saturate(qs) * 255.0f), qd8 = round(saturate(qd) * 255.0f);
    const bool3 vs = qs > DivisorFloor, vd = qd > DivisorFloor;
    if (kappa >= 1.0f)
    {
        OutSpecAlbedo[px] = specGuide;
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }

    // Same-surface guide means: 6x6 tiles around the pixel, tent weights, log-depth agreement.
    const float z = abs(InLinearDepth[px]);
    const bool zValid = isfinite(z) && z > 0.0f;
    const float logZ = zValid ? log(max(z, 1e-6f)) : 0.0f;
    float3 meanSpec = 0.0f, meanDiff = 0.0f;
    float weight = 0.0f;
    [unroll]
    for (int j = -2; j <= 3; ++j)
    {
        [unroll]
        for (int i = -2; i <= 3; ++i)
        {
            const int2 t = t0 + int2(i, j);
            if (any(t < 0) || any(t >= tiles))
                continue;
            const uint slot = uint((t.y - blockOrigin.y) * 7 + (t.x - blockOrigin.x));
            const float4 g = g_G[slot];
            const float4 h = g_H[slot];
            const float2 axis = saturate(1.0f - abs(tp - float2(t)) / 3.0f);
            const float w = axis.x * axis.y * exp(-Square(g.w - logZ) / (2.0f * TargetZSigma * TargetZSigma)) * h.w;
            meanSpec += w * g.rgb;
            meanDiff += w * h.rgb;
            weight += w;
        }
    }
    const float3 Ts = weight > 1e-6f ? meanSpec / weight : qs;
    const float3 Td = weight > 1e-6f ? meanDiff / weight : qd;

    // Lobe radiance handed to RR (channels at or below the floor went to Skip and stay there).
    const float3 Rs = select(vs, specSignal.rgb * (qs8 / 255.0f), 0.0f);
    const float3 Rd = select(vd, diffSignal.rgb * (qd8 / 255.0f), 0.0f);

    const float distanceWeight = zValid ? saturate((logZ - LogNear) * InvLogRange) : 1.0f;
    const float3 q1s = kappa * (qs8 / 255.0f) + (1.0f - kappa) * Ts;
    const float3 q1d = kappa * (qd8 / 255.0f) + (1.0f - kappa) * Td;
    const float m = distanceWeight * (1.0f - kappa);

    const bool allDiffuse = all(vd);
    const float3 q1dValid = select(vd, q1d, 1.0f);
    const float q1dMin = min(min(q1dValid.x, q1dValid.y), q1dValid.z);
    float kd = (1.0f - m) * saturate(((1.0f - m) * q1dMin - DivisorFloor) / DivisorFloor);
    if (!allDiffuse)
        kd = 1.0f;
    const float3 qdLevel = round(saturate(kd * q1d) * 255.0f);
    const bool keep = all(qdLevel > floorLevel) && kd > 0.0f;
    const float3 Rd2 = !allDiffuse ? Rd : (keep ? kd * Rd : 0.0f);
    const float3 moved = Rd - Rd2;

    const float3 qsLevel = round(saturate((1.0f - m) * q1s + m) * 255.0f);
    if (!all(qsLevel > floorLevel))
    {
        OutSpecAlbedo[px] = specGuide;
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }
    const float3 specLighting = (Rs + moved) / (qsLevel / 255.0f);
    float3 diffOut = qd8 / 255.0f;
    float3 diffLighting = diffSignal.rgb;
    if (allDiffuse)
    {
        diffOut = keep ? qdLevel / 255.0f : 0.0f;
        diffLighting = keep ? Rd2 / (qdLevel / 255.0f) : 0.0f;
    }
    // A finite FP16 source pair can carry more radiance than its rewritten guides can represent.
    // Preserve both lobes together: clipping either carrier would lose HDR energy, and reverting just
    // one lobe after moving diffuse radiance would duplicate or remove that moved share.
    const bool representable = all(isfinite(specLighting)) && all(isfinite(diffLighting)) &&
        all(abs(specLighting) <= 65504.0f) && all(abs(diffLighting) <= 65504.0f);
    if (!representable)
    {
        OutSpecAlbedo[px] = specGuide;
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }
    OutSpecAlbedo[px] = float4(qsLevel / 255.0f, specGuide.a);
    OutDiffAlbedo[px] = float4(diffOut, diffGuide.a);
    OutSpecSignal[px] = float4(specLighting, specSignal.a);
    OutDiffSignal[px] = float4(diffLighting, diffSignal.a);
}
