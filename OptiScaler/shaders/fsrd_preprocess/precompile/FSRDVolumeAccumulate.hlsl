// Volumetric restore, step 2 of 3: per 8x8 tile, the radiance RR's output lacks
// against the input's clipped mean, accumulated over time.
//
// A single frame's tile difference still carries the input noise, and after a
// sudden lighting change it jumps. An exponential average reprojected with the
// canonical motion keeps it as stable as RR's own history. The signed difference is
// averaged, so noise cancels instead of being rectified; only the final restore
// clamps it to positive energy. A depth change of the tile restarts its history.
#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 5)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<half4> InComposed : register(t0);   // RR + Skip composition, render resolution
Texture2D<half4> InRawTiles : register(t1);   // FSRDVolumeGather output
Texture2D<half4> InHistory : register(t2);    // previous accumulated difference
Texture2D<float> InLinearDepth : register(t3);
Texture2D<half4> InMotion : register(t4);
// RGB: accumulated signed difference (input - RR output). A: tile mean |depth|.
RWTexture2D<half4> OutHistory : register(u0);

cbuffer CB_VolumeAccumulate : register(b0)
{
    float4 DstTexSize;        // XY = size, ZW = 1 / size
    float2 HistoryJitterDelta;
    uint HistoryValid;
    float Response;           // weight of the current frame
}

groupshared float4 g_Sum[64];

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const uint flatID = gtID.x + gtID.y * 8;
    const int2 size = int2(DstTexSize.xy);
    const int2 px = int2(groupID.xy * 8 + gtID.xy);
    const bool inside = all(px < size);
    const float3 composed = inside ? FloorRadiance(InComposed[px].rgb) : 0.0f;
    const float z = inside ? InLinearDepth[px] : 0.0f;
    const bool depthValid = inside && isfinite(z) && z != 0.0f;
    g_Sum[flatID] = float4(composed, inside ? 1.0f : 0.0f);
    GroupMemoryBarrierWithGroupSync();
    [unroll]
    for (uint stride = 32; stride > 0; stride >>= 1)
    {
        if (flatID < stride)
            g_Sum[flatID] += g_Sum[flatID + stride];
        GroupMemoryBarrierWithGroupSync();
    }
    const float4 composedSum = g_Sum[0];
    GroupMemoryBarrierWithGroupSync();
    g_Sum[flatID] = float4(depthValid ? abs(z) : 0.0f, depthValid ? 1.0f : 0.0f, 0.0f, 0.0f);
    GroupMemoryBarrierWithGroupSync();
    [unroll]
    for (uint stride2 = 32; stride2 > 0; stride2 >>= 1)
    {
        if (flatID < stride2)
            g_Sum[flatID] += g_Sum[flatID + stride2];
        GroupMemoryBarrierWithGroupSync();
    }
    if (flatID != 0)
        return;

    const int2 tile = int2(groupID.xy);
    const int2 tiles = (size + 7) / 8;
    const float3 output = composedSum.rgb / max(composedSum.a, 1.0f);
    const float tileDepth = g_Sum[0].x / max(g_Sum[0].y, 1.0f);
    const float3 difference = InRawTiles[tile].rgb - output;

    // Reproject the tile centre. The tile's history is reused only when its
    // previous mean depth agrees, so a surface moving across fog does not drag
    // the old layer with it.
    const int2 centre = min(tile * 8 + 4, size - 1);
    const float4 motion = InMotion[centre];
    bool reuse = HistoryValid != 0 && motion.a >= 0.5f && all(isfinite(motion)) && g_Sum[0].y > 0.0f;
    const float2 previous = float2(centre) + 0.5f + motion.xy * DstTexSize.xy + HistoryJitterDelta;
    const int2 previousTile = int2(floor(previous / 8.0f));
    reuse = reuse && all(previous >= 0.0f) && all(previousTile < tiles);
    float3 accumulated = difference;
    if (reuse)
    {
        const float4 history = InHistory[previousTile];
        if (all(isfinite(history)) && history.a > 0.0f &&
            abs(float(history.a) - tileDepth) <= 0.1f * max(tileDepth, 1e-3f))
            accumulated = lerp(float3(history.rgb), difference, Response);
    }
    OutHistory[tile] = half4(clamp(accumulated, -65500.0f, 65500.0f), min(tileDepth, 65500.0f));
}
