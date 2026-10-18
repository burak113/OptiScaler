// Optional colour-noise filter for the two RR lighting inputs after a fast camera turn.
// During a turn the title's 1-spp lighting carries more heavy, strongly coloured samples, and RR's young history
// keeps them as coloured marks that fade over ~30 frames. Each sample keeps its own luminance and takes the
// energy-weighted colour of its 11x11 neighbourhood (box sum of RGB scaled by own / box luminance); Weight blends
// it in (the host fades it out over the frames after the turn). Alpha (specular hit distance) is copied.
// Gain (<= 1) then scales RGB: the title's lighting is ~15 % too bright for ~12 frames after a fast turn, and RR's
// restarted history averages those frames equally, so the excess would fade only as 1/N (seconds). 1 = unchanged.
// Reads the RR-scaled inputs as SRVs and writes RR-only copies; the title's inputs are never modified.
// 16x16 groups and an fp16 tile (sums stay fp32): 0.49 ms at 2560x1440 on RDNA4 vs 0.92 ms for 8x8 fp32.
#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 4, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2), UAV(u0, numDescriptors = 2))"

Texture2D<float4> InSignal[2] : register(t0);
RWTexture2D<float4> OutSignal[2] : register(u0);
cbuffer TurnConstants : register(b0) { uint2 RenderSize; float Weight; float Gain; }

#define RADIUS 5
#define GROUP 16
#define TILE (GROUP + 2 * RADIUS)
groupshared float16_t4 sTile[TILE][TILE]; // rgb, luminance (the inputs are fp16)
groupshared float4 sRows[TILE][GROUP];    // horizontal box sums

float4 Load(uint lobe, int2 p)
{
    p = clamp(p, int2(0, 0), int2(RenderSize) - 1);
    const float3 rgb = InSignal[lobe][p].rgb;
    if (!all(isfinite(rgb))) return 0.0f;
    return float4(rgb, dot(rgb, float3(0.2126f, 0.7152f, 0.0722f)));
}

[RootSignature(MainRS)]
[numthreads(GROUP, GROUP, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID, uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID, uint index : SV_GroupIndex)
{
    const int2 origin = int2(group.xy) * GROUP - RADIUS;
    const int2 p = int2(dispatch.xy);
    [unroll] for (uint lobe = 0; lobe < 2; ++lobe)
    {
        for (uint i = index; i < TILE * TILE; i += GROUP * GROUP)
            sTile[i / TILE][i % TILE] = float16_t4(Load(lobe, origin + int2(i % TILE, i / TILE)));
        GroupMemoryBarrierWithGroupSync();
        for (uint j = index; j < TILE * GROUP; j += GROUP * GROUP)
        {
            const uint row = j / GROUP, column = j % GROUP;
            float4 sum = 0.0f;
            [unroll] for (uint x = 0; x <= 2 * RADIUS; ++x) sum += float4(sTile[row][column + x]);
            sRows[row][column] = sum;
        }
        GroupMemoryBarrierWithGroupSync();
        float4 box = 0.0f;
        [unroll] for (uint y = 0; y <= 2 * RADIUS; ++y) box += sRows[local.y + y][local.x];
        if (all(p < int2(RenderSize)))
        {
            const float4 source = InSignal[lobe][p];
            float3 rgb = source.rgb;
            const float4 centre = float4(sTile[local.y + RADIUS][local.x + RADIUS]);
            if (all(isfinite(rgb)))
            {
                if (box.w > 1e-12f) rgb += Weight * (box.rgb * (centre.w / box.w) - rgb);
                rgb *= Gain;
            }
            OutSignal[lobe][p] = float4(rgb, source.a);
        }
        GroupMemoryBarrierWithGroupSync();
    }
}
