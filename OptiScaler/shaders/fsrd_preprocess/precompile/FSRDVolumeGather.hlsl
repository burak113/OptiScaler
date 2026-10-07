// Volumetric restore, step 1 of 3: the current frame's radiance per 8x8 tile.
//
// RR demodulates by albedo and keeps what the surface guides explain. Light that is
// not on a surface (fog, beams, transparent layers) is partly erased. RR itself is
// unbiased on noise, so a systematic shortfall of its output against the input's
// tile mean is energy it removed. This pass records that input mean while the
// game's colour is guaranteed readable (conversion time). One group is one tile.
// A firefly is not volumetric light: luminance above mean + 3 sigma is clipped
// before the mean, so isolated spikes RR rightly rejects are not restored.
#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 1)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<float4> InColor : register(t0);
// RGB: clipped tile mean radiance. A: standard error of the tile's mean luminance.
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
    const float luma = GetLuminance(colour);

    // A single spike inflates the deviation it is judged by, so the ceiling is
    // re-derived from the already clipped population a few times.
    float ceiling = 65504.0f, deviation = 0.0f, count = 1.0f;
    [unroll]
    for (uint iteration = 0; iteration < 8; ++iteration)
    {
        const float clippedLuma = min(luma, ceiling);
        g_Sum[flatID] = float4(clippedLuma, clippedLuma * clippedLuma, inside ? 1.0f : 0.0f, 0.0f);
        Reduce(flatID);
        count = max(g_Sum[0].z, 1.0f);
        const float mean = g_Sum[0].x / count;
        deviation = sqrt(max(g_Sum[0].y / count - mean * mean, 0.0f));
        ceiling = mean + 3.0f * deviation;
        GroupMemoryBarrierWithGroupSync();
    }

    const float3 clipped = luma > ceiling ? colour * (ceiling / luma) : colour;
    g_Sum[flatID] = float4(clipped, 0.0f);
    Reduce(flatID);
    if (flatID == 0)
        OutRawTiles[groupID.xy] = half4(min(g_Sum[0].rgb / count, 65500.0f),
                                        min(deviation * rsqrt(count), 65500.0f));
}
