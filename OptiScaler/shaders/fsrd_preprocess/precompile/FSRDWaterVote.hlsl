#include "FSRDPreprocessCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 4)), DescriptorTable(UAV(u0, numDescriptors = 2))"
// Water stain fix, pass 1: share of water-like pixels per 16x16 block (one 8x8 group per block).
// Water hands RR the guides of the surface below it: the sea floor's albedo, a 3x step at its features while
// the image is flat. Demodulating by it and remodulating after RR draws the floor's outline on the water.
// Water-like = specular share of the stored guides above ShareThreshold, world normal facing up, RR material 0.
cbuffer CB_Water : register(b0)
{
    float4 DstTexSize;
    float ShareThreshold;
    float UpThreshold;
    float VoteThreshold;
    float LowVoteThreshold;
}
Texture2D<float4> InSpecAlbedo : register(t0);
Texture2D<float4> InDiffAlbedo : register(t1);
Texture2D<float4> InNormals : register(t2);
Texture2D<float4> InSkip : register(t3);
RWTexture2D<float> OutVote : register(u0);
RWTexture2D<float> OutLike : register(u1); // per pixel: water-like (1) or not (0)

groupshared uint Counts[64];

bool WaterLike(int2 p)
{
    const float4 normal = InNormals[p];
    // Material 0 only: Flat Detail owns type 1; skipped and bias-routed pixels carry no guides.
    if (normal.a > 1.0f / 6.0f || InSkip[p].a == -1.0f) return false;
    const float specular = GetLuminance(InSpecAlbedo[p].rgb), diffuse = GetLuminance(InDiffAlbedo[p].rgb);
    return specular + diffuse > 1e-3f && specular > ShareThreshold * (specular + diffuse) &&
        OctahedralDecode(normal.xy).z > UpThreshold;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint lane = local.y * 8 + local.x;
    const int2 base = int2(group.xy) * 16 + int2(local.xy) * 2;
    uint water = 0, total = 0;
    [unroll] for (int y = 0; y < 2; ++y) [unroll] for (int x = 0; x < 2; ++x)
    {
        const int2 p = base + int2(x, y);
        if (any(p >= int2(DstTexSize.xy))) continue;
        ++total;
        const bool like = WaterLike(p);
        OutLike[p] = like ? 1.0f : 0.0f;
        if (like) ++water;
    }
    Counts[lane] = water | (total << 16);
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint step = 32; step > 0; step >>= 1)
    {
        if (lane < step) Counts[lane] += Counts[lane + step];
        GroupMemoryBarrierWithGroupSync();
    }
    if (lane == 0)
    {
        const uint sum = Counts[0];
        OutVote[group.xy] = (sum >> 16) > 0u ? float(sum & 65535u) / float(sum >> 16) : 0.0f;
    }
}
