// Volumetric restore, step 1 of 3: the current frame's radiance per 8x8 tile.
//
// RR demodulates by albedo and keeps what the surface guides explain. Light that is
// not on a surface (fog, beams, transparent layers) is partly erased. RR itself is
// unbiased on noise, so a systematic shortfall of its output against the input's
// tile mean is energy it removed. This pass records that input mean while the
// game's colour is guaranteed readable (conversion time). One group is one tile.
// The mean is not clipped: volumetric scattering is exactly the heavy-tailed light
// whose energy sits in rare bright samples. An 8-pass 3-sigma clip here held fog tiles
// 25-40% below the input mean (a7038a3d), at RR's own level, so the restore never
// found a shortfall. The unclipped mean's noise is left to the slow accumulation and
// the wide apply.
#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 1)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<float4> InColor : register(t0);
// RGB: tile mean radiance. A: standard error of the tile's mean luminance.
RWTexture2D<half4> OutRawTiles : register(u0);

cbuffer CB_VolumeGather : register(b0)
{
    float4 RenderSize; // XY = size, ZW = 1 / size
    uint2 InputBase;   // origin of the colour inside the game's texture
    uint2 _Reserved0;
}

groupshared float4 g_Sum[64];

void Reduce(uint flatID)
{
    [unroll]
    for (uint stride = 32; stride > 0; stride >>= 1)
    {
        GroupMemoryBarrierWithGroupSync();
        if (flatID < stride)
            g_Sum[flatID] += g_Sum[flatID + stride];
    }
    GroupMemoryBarrierWithGroupSync();
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const uint flatID = gtID.x + gtID.y * 8;
    const int2 px = int2(groupID.xy * 8 + gtID.xy);
    const bool inside = all(px < int2(RenderSize.xy));
    const float3 colour = inside ? FloorRadiance(InColor[px + int2(InputBase)].rgb) : 0.0f;
    g_Sum[flatID] = float4(colour, inside ? 1.0f : 0.0f);
    Reduce(flatID);
    const float count = max(g_Sum[0].w, 1.0f);
    const float3 mean = g_Sum[0].rgb / count;
    GroupMemoryBarrierWithGroupSync();
    const float offset = inside ? GetLuminance(colour) - GetLuminance(mean) : 0.0f;
    g_Sum[flatID] = float4(offset * offset, 0.0f, 0.0f, 0.0f);
    Reduce(flatID);
    if (flatID == 0)
        OutRawTiles[groupID.xy] = half4(min(mean, 65500.0f),
                                        min(sqrt(g_Sum[0].x / count) * rsqrt(count), 65500.0f));
}
