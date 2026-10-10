// Fog-consistent guides, pass 1 of 5: per 8x8 tile, how much of the guides' texture the image carries.
//
// RR demodulates the game's colour by the surface albedo guides and the composition multiplies the result by
// them again. Where light does not come from the surface (fog, haze, a volume in front of it, water over a sea
// floor), the remodulation prints the surface texture at full strength: distant geometry comes out of the haze,
// and the sea floor shows through water. In a fog capture (c2cbdeeb) the guide texture the output printed was
// 2-9x what the image held, while the mean energy was right.
//
// Local linear guide model per tile (the guided filter's): hp(C) = kappa * P, with
//   P = Lbar_s * hp(Qs) + Lbar_d * hp(Qd)        (luminance; hp = minus the tile mean)
// Lbar is the tile's demodulated lighting averaged over time, so the regressor is free of the image's noise and
// the estimate is not attenuated. The sums of hp(C) P, P^2 and hp(C)^2 are averaged over time along the motion
// (ratio of averages, not average of ratios). Statistics come from the packing shader's own pair: a stabilised
// guide has less texture and makes the estimate noisier.
//
// Outputs per tile (history: A, B, C; per frame: G, H):
//   A: Lbar_s.rgb, age          B: Lbar_d.rgb, mean radiance (luminance, averaged over time)
//   C: N, D, S, mean log depth  G: current pair's specular guide mean.rgb, mean log depth
//   H: current pair's diffuse guide mean.rgb, fraction of pixels with depth
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 11), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 5), visibility = SHADER_VISIBILITY_ALL), "

#define FLAGS_RESET (1 << 0)

Texture2D<float4> InOrigSpecAlbedo : register(t0); // packing shader's specular guide (UNORM8)
Texture2D<float4> InOrigDiffAlbedo : register(t1); // packing shader's diffuse guide (UNORM8)
Texture2D<float4> InOrigSpecSignal : register(t2); // packing shader's demodulated specular lighting
Texture2D<float4> InOrigDiffSignal : register(t3); // packing shader's demodulated diffuse lighting
Texture2D<float4> InCurSpecAlbedo : register(t4);  // the pair this frame hands on (stabilised or not)
Texture2D<float4> InCurDiffAlbedo : register(t5);
Texture2D<float> InLinearDepth : register(t6);     // signed linear view-space depth
Texture2D<float4> InMotion : register(t7);         // XY: unjittered previous UV - current UV, W: valid
Texture2D<float4> InPrevA : register(t8);
Texture2D<float4> InPrevB : register(t9);
Texture2D<float4> InPrevC : register(t10);

RWTexture2D<float4> OutA : register(u0);
RWTexture2D<float4> OutB : register(u1);
RWTexture2D<float4> OutC : register(u2);
RWTexture2D<float4> OutG : register(u3);
RWTexture2D<float4> OutH : register(u4);

cbuffer CB_FogStats : register(b0)
{
    float4 DstTexSize;      // XY: render size, ZW: 1 / size
    float2 TileSize;        // tiles in X and Y
    float Rate;             // weight of the current frame in the averages
    float DivisorFloor;     // the packing shader's demodulation divisor floor
    float DepthTolerance;   // largest change of a tile's mean log depth that keeps its history
    uint Flags;
    float2 HistoryJitterDelta; // previous jitter - current jitter, in render pixels
}

groupshared float4 g_Sum[6][64];
groupshared float4 g_Broadcast[4];

void Reduce(uint flatID, uint slots)
{
    [unroll]
    for (uint stride = 32; stride > 0; stride >>= 1)
    {
        GroupMemoryBarrierWithGroupSync();
        if (flatID < stride)
        {
            for (uint i = 0; i < slots; ++i)
                g_Sum[i][flatID] += g_Sum[i][flatID + stride];
        }
    }
    GroupMemoryBarrierWithGroupSync();
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const uint flatID = gtID.x + gtID.y * 8;
    const int2 size = int2(DstTexSize.xy);
    const int2 tile = int2(groupID.xy);
    const int2 px = tile * 8 + int2(gtID.xy);
    const bool inside = all(px < size);

    float3 qs = 0.0f, qd = 0.0f, U = 0.0f, V = 0.0f, qsCur = 0.0f, qdCur = 0.0f;
    float C = 0.0f, logZ = 0.0f, hasZ = 0.0f;
    if (inside)
    {
        qs = InOrigSpecAlbedo[px].rgb;
        qd = InOrigDiffAlbedo[px].rgb;
        U = InOrigSpecSignal[px].rgb;
        V = InOrigDiffSignal[px].rgb;
        qsCur = InCurSpecAlbedo[px].rgb;
        qdCur = InCurDiffAlbedo[px].rgb;
        // Radiance each lobe carries in RR; channels at or below the divisor floor went to Skip.
        const float3 rs = select(qs > DivisorFloor, U * qs, 0.0f);
        const float3 rd = select(qd > DivisorFloor, V * qd, 0.0f);
        C = GetLuminance(rs + rd);
        const float z = abs(InLinearDepth[px]);
        if (isfinite(z) && z > 0.0f)
        {
            logZ = log(max(z, 1e-6f));
            hasZ = 1.0f;
        }
    }

    // Tile means.
    g_Sum[0][flatID] = float4(U, C);
    g_Sum[1][flatID] = float4(V, inside ? 1.0f : 0.0f);
    g_Sum[2][flatID] = float4(qs, logZ);
    g_Sum[3][flatID] = float4(qd, hasZ);
    g_Sum[4][flatID] = float4(qsCur, 0.0f);
    g_Sum[5][flatID] = float4(qdCur, 0.0f);
    Reduce(flatID, 6);

    if (flatID == 0)
    {
        const float count = max(g_Sum[1][0].w, 1.0f);
        const float zCount = g_Sum[3][0].w;
        const float3 ls = g_Sum[0][0].rgb / count;
        const float3 ld = g_Sum[1][0].rgb / count;
        const float cbar = g_Sum[0][0].w / count;
        const float tileLogZ = zCount > 0.0f ? g_Sum[2][0].w / zCount : 0.0f;

        // Reproject the tile centre; its previous tile's history is kept when its mean depth agrees.
        const int2 tiles = int2(TileSize);
        const int2 centre = min(tile * 8 + 4, size - 1);
        const float4 motion = InMotion[centre];
        const float2 previous = float2(centre) + 0.5f + motion.xy * DstTexSize.xy + HistoryJitterDelta;
        const int2 previousTile = int2(floor(previous / 8.0f));
        bool reuse = (Flags & FLAGS_RESET) == 0 && motion.w > 0.0f && zCount > 0.0f &&
            all(previousTile >= 0) && all(previousTile < tiles);
        float4 prevA = 0.0f, prevB = 0.0f, prevC = 0.0f;
        if (reuse)
        {
            prevA = InPrevA[previousTile];
            prevB = InPrevB[previousTile];
            prevC = InPrevC[previousTile];
            reuse = prevA.w > 0.0f && abs(prevC.w - tileLogZ) <= DepthTolerance &&
                all(isfinite(prevA)) && all(isfinite(prevB)) && all(isfinite(prevC));
        }
        const float3 Ls = reuse ? prevA.rgb + Rate * (ls - prevA.rgb) : ls;
        const float3 Ld = reuse ? prevB.rgb + Rate * (ld - prevB.rgb) : ld;
        const float Cb = reuse ? prevB.w + Rate * (cbar - prevB.w) : cbar;
        g_Broadcast[0] = float4(Ls, cbar);
        g_Broadcast[1] = float4(Ld, reuse ? 1.0f : 0.0f);
        g_Broadcast[2] = float4(g_Sum[2][0].rgb / count, Cb);
        g_Broadcast[3] = float4(g_Sum[3][0].rgb / count, tileLogZ);
        OutG[tile] = float4(g_Sum[4][0].rgb / count, tileLogZ);
        OutH[tile] = float4(g_Sum[5][0].rgb / count, zCount / count);
    }
    GroupMemoryBarrierWithGroupSync();

    const float3 Ls = g_Broadcast[0].rgb;
    const float cbar = g_Broadcast[0].w;
    const float3 Ld = g_Broadcast[1].rgb;
    float n = 0.0f, d = 0.0f, s = 0.0f;
    if (inside)
    {
        const float P = GetLuminance(Ls * (qs - g_Broadcast[2].rgb) + Ld * (qd - g_Broadcast[3].rgb));
        const float hp = C - cbar;
        n = hp * P;
        d = P * P;
        s = hp * hp;
    }
    g_Sum[0][flatID] = float4(n, d, s, 0.0f);
    Reduce(flatID, 1);

    if (flatID == 0)
    {
        const bool reuse = g_Broadcast[1].w > 0.0f;
        const float zCount = g_Sum[3][0].w;
        float3 sums = g_Sum[0][0].xyz;
        float age = 1.0f;
        if (reuse)
        {
            const int2 centre = min(tile * 8 + 4, size - 1);
            const float2 previous = float2(centre) + 0.5f + InMotion[centre].xy * DstTexSize.xy + HistoryJitterDelta;
            const int2 previousTile = int2(floor(previous / 8.0f));
            const float4 prevC = InPrevC[previousTile];
            sums = prevC.xyz + Rate * (sums - prevC.xyz);
            age = min(InPrevA[previousTile].w + 1.0f, 1.0f / Rate);
        }
        // A tile without geometry holds no history.
        if (zCount <= 0.0f)
            age = 0.0f;
        OutA[tile] = float4(Ls, age);
        OutB[tile] = float4(Ld, g_Broadcast[2].w);
        OutC[tile] = float4(sums, g_Broadcast[3].w);
    }
}
