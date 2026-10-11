// Recovery v2 lobe recovery, pass 3 of 3: weight one band and collapse (see FSRDRecoveryLobeCommon.hlsli).
//
// Dispatched per level from the coarsest (5) to level 0. Per lobe:
//   band     B = level - up(next coarser level), for reference - RR and for the innovation luma;
//   noise    v = running mean, then exponential average (1/16), of the innovation band power, reprojected at
//            this level with the motion of the texel's centre; the reference's band noise is N = v q / (1 + q),
//            q being its sum of squared weights;
//   weight   Wiener: w = max(E - k N, 0) / E, E the 3x3 mean of the band's luma power. k = Threshold at levels 0/1; levels 2+
//            increase toward Threshold * (1 + 0.5 * Level^2) over 4-20 render pixels of motion.
//            The current-frame flat reference keeps that margin at rest as well. Mix
//            moves it towards 1: w + Mix (1 - w); times the reference's maturity. Specular / Diffuse strength
//   collapse C = weighted band minus its own next-level mean (a weight must not move energy into coarser
//            scales) plus the up-sampled correction of the coarser levels.
// Level 0 limits each lobe to RR's 3x3 mean +- Anchor sqrt(RR's 3x3 variance + a small RR-relative floor)
// composition's guides and adds them to the composed colour. Each negative lobe correction is limited to
// 25% of that lobe's RR value; the final non-negative guard remains in place.
// Pixels whose colour is the current source are untouched.
#include "FSRDRecoveryLobeCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 16), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 4), visibility = SHADER_VISIBILITY_ALL), "

Texture2D<float4> InLevelA : register(t0);         // this level: specular reference - RR, A: innovation luma
Texture2D<float4> InLevelB : register(t1);         // this level: diffuse
Texture2D<float4> InLevelC : register(t2);         // this level: flat albedo class, maturity, squared weights
Texture2D<float4> InCoarseA : register(t3);        // next coarser level
Texture2D<float4> InCoarseB : register(t4);
Texture2D<float4> InCoarseSpecular : register(t5); // collapsed specular correction of the coarser levels
Texture2D<float4> InCoarseDiffuse : register(t6);
Texture2D<float4> InPrevNoise : register(t7);      // this level, last frame: XY band noise (std), Z: noise age
Texture2D<float4> InMotion : register(t8);         // render resolution
Texture2D<float4> InComposed : register(t9);       // level 0: the composed colour
Texture2D<float4> InSpecularAlbedo : register(t10);
Texture2D<float4> InDiffuseAlbedo : register(t11);
Texture2D<float4> InSkipSignal : register(t12);
Texture2D<float4> InSpecularDenoised : register(t13);     // level 0: RR's lobes, for Anchor
Texture2D<float4> InDiffuseDenoised : register(t14);
Texture2D<float4> InExtraDiffuseDenoised : register(t15);

RWTexture2D<float4> OutSpecular : register(u0);    // collapsed specular correction down to this level
RWTexture2D<float4> OutDiffuse : register(u1);
RWTexture2D<float4> OutNoise : register(u2);
RWTexture2D<float4> OutColor : register(u3);       // level 0 only

// Group memory holds FP16 values packed two to a word (the levels themselves are FP16): 6.4 KB instead of 11.7 KB
// per group, which otherwise limits RDNA occupancy to ~2.5 waves per SIMD.
groupshared uint2 s_BandS[14][14]; // tile with a three-texel halo: RGB band, A innovation band
groupshared uint2 s_BandD[14][14];
groupshared uint2 s_CorrS[12][12]; // tile with a two-texel halo: weighted band
groupshared uint2 s_CorrD[12][12];
groupshared float3 s_DownS[6][6];   // the weighted band's next-level mean over that region
groupshared float3 s_DownD[6][6];

uint2 PackHalf4(float4 v)
{
    const uint4 h = f32tof16(clamp(v, -65504.0f, 65504.0f));
    return uint2(h.x | (h.y << 16), h.z | (h.w << 16));
}

float4 UnpackHalf4(uint2 p)
{
    return f16tof32(uint4(p.x, p.x >> 16, p.y, p.y >> 16));
}

float3 Bilerp(float3 a, float3 b, float3 c, float3 d, float2 f)
{
    return lerp(lerp(a, b, f.x), lerp(c, d, f.x), f.y);
}

float3 DiffuseDenoised(int2 q)
{
    return InDiffuseDenoised[q].rgb + (IsSet(RECOVERY_FLAGS_EXTRA_DIFFUSE) ? InExtraDiffuseDenoised[q].rgb : 0.0f);
}

// The correction, limited so that RR's lobe value plus it stays within RR's 3x3 mean +- anchor standard deviations
// (only RR's local spread determines its width). The limit only acts on the correction: where
// RR's own value lies outside that range, the range is widened to it. At level 0 the band arrays hold RR's lobes
// over the tile and a one-texel halo (FP16, as RR writes them).
float3 AnchorLobe(float3 correction, int2 l, bool diffuse, float anchor)
{
    if (anchor <= 0.0f)
        return correction;
    float3 sum = 0.0f, sumSquare = 0.0f, centre = 0.0f;
    [unroll]
    for (int dy = -1; dy <= 1; ++dy)
    {
        [unroll]
        for (int dx = -1; dx <= 1; ++dx)
        {
            const float3 v = UnpackHalf4(diffuse ? s_BandD[l.y + dy][l.x + dx] : s_BandS[l.y + dy][l.x + dx]).rgb;
            sum += v;
            sumSquare += v * v;
            if (dx == 0 && dy == 0)
                centre = v;
        }
    }
    const float3 mean = sum * (1.0f / 9.0f);
    const float3 variance = max(sumSquare * (1.0f / 9.0f) - mean * mean, 0.0f);
    const float3 deviation = anchor * sqrt(variance + 1e-4f * mean * mean);
    return clamp(centre + correction, min(mean - deviation, centre), max(mean + deviation, centre)) - centre;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 gtID : SV_GroupThreadID, uint3 gID : SV_GroupID)
{
    const int2 size = int2(LevelSize.xy);
    const int2 coarseSize = int2(LevelSize.zw);
    const int2 tile = int2(gID.xy) * 8;
    const uint thread = gtID.y * 8 + gtID.x;

    for (uint i = thread; i < 196; i += 64)
    {
        const int2 q = clamp(tile - 3 + int2(i % 14, i / 14), int2(0, 0), size - 1);
        const float2 coarse = (float2(q) + 0.5f) * 0.5f - 0.5f;
        s_BandS[i / 14][i % 14] = PackHalf4(InLevelA[q] - LoadBilinear(InCoarseA, coarse, coarseSize));
        s_BandD[i / 14][i % 14] = PackHalf4(InLevelB[q] - LoadBilinear(InCoarseB, coarse, coarseSize));
    }
    GroupMemoryBarrierWithGroupSync();

    const float scale = float(1u << Level);
    for (uint j = thread; j < 144; j += 64)
    {
        const int2 local = int2(j % 12, j / 12);
        const int2 r = tile - 2 + local;
        const int2 q = clamp(r, int2(0, 0), size - 1);
        // Past the level's edge the texel repeats the edge texel's weighted band, as the next level's mean does.
        const int2 b = q - (tile - 3);
        float2 energy = 0.0f;
        [unroll]
        for (int dy = -1; dy <= 1; ++dy)
        {
            [unroll]
            for (int dx = -1; dx <= 1; ++dx)
            {
                const float ls = GetLuminance(UnpackHalf4(s_BandS[b.y + dy][b.x + dx]).rgb);
                const float ld = GetLuminance(UnpackHalf4(s_BandD[b.y + dy][b.x + dx]).rgb);
                energy += float2(ls * ls, ld * ld);
            }
        }
        energy *= 1.0f / 9.0f;
        const float4 bandS = UnpackHalf4(s_BandS[b.y][b.x]);
        const float4 bandD = UnpackHalf4(s_BandD[b.y][b.x]);
        const float4 levelC = InLevelC[q];

        float2 variance = float2(bandS.a * bandS.a, bandD.a * bandD.a);
        float age = 1.0f;
        const float2 centre = (float2(q) + 0.5f) * scale;
        const float4 motion = InMotion[min(int2(centre), int2(DstTexSize.xy) - 1)];
        [branch]
        if (IsSet(RECOVERY_FLAGS_HISTORY_VALID) && levelC.z > 0.0f && motion.w >= 0.5f)
        {
            const float2 previous = (centre + motion.xy * DstTexSize.xy) / scale - 0.5f;
            // Variances are interpolated, not the stored standard deviations (which would bias them low).
            const float2 h = clamp(previous, 0.0f, float2(size - 1));
            const int2 h0 = int2(floor(h));
            const int2 h1 = min(h0 + 1, size - 1);
            const float2 hf = h - float2(h0);
            const float4 n00 = InPrevNoise[h0], n10 = InPrevNoise[int2(h1.x, h0.y)];
            const float4 n01 = InPrevNoise[int2(h0.x, h1.y)], n11 = InPrevNoise[h1];
            const float2 previousVariance = lerp(lerp(n00.xy * n00.xy, n10.xy * n10.xy, hf.x),
                                                 lerp(n01.xy * n01.xy, n11.xy * n11.xy, hf.x), hf.y);
            const float4 history = lerp(lerp(n00, n10, hf.x), lerp(n01, n11, hf.x), hf.y);
            const float rate = max(1.0f / (history.z + 1.0f), 1.0f / 16.0f);
            variance = previousVariance + rate * (variance - previousVariance);
            age = min(history.z + 1.0f, 1024.0f);
        }
        const float weights = levelC.w;
        const float2 noiseVariance = max(variance * weights / (1.0f + weights), 1e-20f);
        float coarseMargin = 0.0f;
        if (Level >= 2u)
            coarseMargin = smoothstep(4.0f, 20.0f, length(motion.xy * DstTexSize.xy));
        const float k = Threshold * (1.0f + 0.5f * float(Level * Level) * coarseMargin);
        const float2 wiener = saturate((energy - k * noiseVariance) / max(energy, 1e-30f));
        const float2 maturity = levelC.z * smoothstep(2.0f, 4.0f, age);
        const float2 ordinary = Strength.xy * (wiener + Blend.x * (1.0f - wiener));
        float2 weight = ordinary * maturity;
        if (IsSet(RECOVERY_FLAGS_NO_SPECULAR))
            weight.x = 0.0f;
        s_CorrS[local.y][local.x] = PackHalf4(float4(bandS.rgb * weight.x, 0.0f));
        s_CorrD[local.y][local.x] = PackHalf4(float4(bandD.rgb * weight.y, 0.0f));
        if (all(r == q) && all(local >= 2) && all(local < 10))
            OutNoise[q] = float4(min(sqrt(variance), 65504.0f), age, 0.0f);
    }
    GroupMemoryBarrierWithGroupSync();

    if (thread < 36)
    {
        const int2 c = int2(thread % 6, thread / 6);
        const int2 f = 2 * c;
        s_DownS[c.y][c.x] = 0.25f * (UnpackHalf4(s_CorrS[f.y][f.x]).rgb + UnpackHalf4(s_CorrS[f.y][f.x + 1]).rgb +
                                     UnpackHalf4(s_CorrS[f.y + 1][f.x]).rgb + UnpackHalf4(s_CorrS[f.y + 1][f.x + 1]).rgb);
        s_DownD[c.y][c.x] = 0.25f * (UnpackHalf4(s_CorrD[f.y][f.x]).rgb + UnpackHalf4(s_CorrD[f.y][f.x + 1]).rgb +
                                     UnpackHalf4(s_CorrD[f.y + 1][f.x]).rgb + UnpackHalf4(s_CorrD[f.y + 1][f.x + 1]).rgb);
    }
    // Level 0: the bands are consumed; their arrays take RR's lobes for Anchor (one load per texel, not nine).
    if (IsSet(RECOVERY_FLAGS_FINAL))
    {
        for (uint k = thread; k < 100; k += 64)
        {
            const int2 q = clamp(tile - 1 + int2(k % 10, k / 10), int2(0, 0), size - 1);
            s_BandS[k / 10][k % 10] = PackHalf4(float4(InSpecularDenoised[q].rgb, 0.0f));
            s_BandD[k / 10][k % 10] = PackHalf4(float4(DiffuseDenoised(q), 0.0f));
        }
    }
    GroupMemoryBarrierWithGroupSync();

    const int2 p = tile + int2(gtID.xy);
    if (any(p >= size))
        return;
    const int2 local = int2(gtID.xy) + 2;
    const float2 u = clamp((float2(p) + 0.5f) * 0.5f - 0.5f, 0.0f, float2(coarseSize - 1));
    const int2 g0 = int2(floor(u));
    const int2 g1 = min(g0 + 1, coarseSize - 1);
    const float2 f = u - float2(g0);
    const int2 origin = tile / 2 - 1;
    const int2 l0 = g0 - origin, l1 = g1 - origin;
    float3 specular = UnpackHalf4(s_CorrS[local.y][local.x]).rgb -
        Bilerp(s_DownS[l0.y][l0.x], s_DownS[l0.y][l1.x], s_DownS[l1.y][l0.x], s_DownS[l1.y][l1.x], f);
    float3 diffuse = UnpackHalf4(s_CorrD[local.y][local.x]).rgb -
        Bilerp(s_DownD[l0.y][l0.x], s_DownD[l0.y][l1.x], s_DownD[l1.y][l0.x], s_DownD[l1.y][l1.x], f);
    if (!IsSet(RECOVERY_FLAGS_COARSEST))
    {
        specular += LoadBilinear(InCoarseSpecular, u, coarseSize).rgb;
        diffuse += LoadBilinear(InCoarseDiffuse, u, coarseSize).rgb;
    }
    if (!IsSet(RECOVERY_FLAGS_FINAL))
    {
        OutSpecular[p] = float4(clamp(specular, -65504.0f, 65504.0f), 0.0f);
        OutDiffuse[p] = float4(clamp(diffuse, -65504.0f, 65504.0f), 0.0f);
        return;
    }

    const float4 composed = InComposed[p];
    float3 correction = 0.0f;
    if (InSkipSignal[p].a != -1.0f && all(InLevelC[p].xy < 0.5f))
    {
        if (!IsSet(RECOVERY_FLAGS_NO_SPECULAR))
            specular = AnchorLobe(specular, int2(gtID.xy) + 1, false, Blend.y);
        diffuse = AnchorLobe(diffuse, int2(gtID.xy) + 1, true, Blend.y);
        // A noisy low-albedo lobe must not dig an isolated dark hole into RR.
        specular = max(specular, -0.25f * max(UnpackHalf4(s_BandS[gtID.y + 1][gtID.x + 1]).rgb, 0.0f));
        diffuse = max(diffuse, -0.25f * max(UnpackHalf4(s_BandD[gtID.y + 1][gtID.x + 1]).rgb, 0.0f));
        correction = specular * lerp(1.0f, InSpecularAlbedo[p].rgb, saturate(Modulation.x)) +
                     diffuse * lerp(1.0f, InDiffuseAlbedo[p].rgb, saturate(Modulation.y));
        float limit = 1.0f;
        [unroll]
        for (int c = 0; c < 3; ++c)
        {
            if (composed[c] + correction[c] < 0.0f && correction[c] < 0.0f)
                limit = min(limit, max(composed[c], 0.0f) / -correction[c]);
        }
        correction *= saturate(limit);
        if (!all(isfinite(correction)))
            correction = 0.0f;
    }
    float3 color = composed.rgb + correction;
    [branch]
    if (Debug != 0u && all(InLevelC[p].xy < 0.5f))
    {
        const float relative = GetLuminance(correction) / max(GetLuminance(composed.rgb), 1e-4f);
        color = Debug == 1u ? float3(saturate(8.0f * relative), 0.1f, saturate(-8.0f * relative))
                            : float3(saturate(8.0f * abs(relative)), InLevelC[p].z, saturate(InLevelC[p].y));
    }
    OutColor[p] = float4(clamp(color, -65504.0f, 65504.0f), composed.a);
}
