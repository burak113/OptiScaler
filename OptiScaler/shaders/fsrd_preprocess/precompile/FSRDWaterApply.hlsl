#include "FSRDPreprocessCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 2)), DescriptorTable(UAV(u0, numDescriptors = 5))"
// Water stain fix, pass 2: the pixel leaves demodulation when the bilinear block vote exceeds VoteThreshold (fills
// small holes in the water), or when it is water-like itself and the vote exceeds LowVoteThreshold (water next to a
// pier or shore, where the blocks also hold other surfaces). Requiring water-like neighbours as well was measured
// worse: the jittered floor edge flips that test every frame and the material class flickered with it. Its signals are multiplied back by their guides, the
// guides become 1 (composition remodulates by 1) and it gets RR material type 2, so RR never mixes unmodulated water
// with modulated neighbours, in space or in time. A band narrower than about a quarter block never reaches either
// vote, so isolated material classes (no neighbours for RR) do not appear. Every other pixel is left untouched.
cbuffer CB_Water : register(b0)
{
    float4 DstTexSize;
    float ShareThreshold;
    float UpThreshold;
    float VoteThreshold;
    float LowVoteThreshold;
}
Texture2D<float> InVote : register(t0);
Texture2D<float> InLike : register(t1); // FSRDWaterVote per-pixel test, read before any pixel changes
RWTexture2D<float4> SpecAlbedo : register(u0);
RWTexture2D<float4> DiffAlbedo : register(u1);
RWTexture2D<float4> SpecSignal : register(u2);
RWTexture2D<float4> DiffSignal : register(u3);
RWTexture2D<float4> Normals : register(u4);

static const int kBlock = 16;

float Vote(int2 p)
{
    const int2 size = (int2(DstTexSize.xy) + kBlock - 1) / kBlock;
    const float2 u = clamp((float2(p) - 0.5f * (kBlock - 1)) / kBlock, 0.0f, float2(size - 1));
    const int2 b0 = int2(floor(u)), b1 = min(b0 + 1, size - 1);
    const float2 f = u - float2(b0);
    return lerp(lerp(InVote[b0], InVote[int2(b1.x, b0.y)], f.x), lerp(InVote[int2(b0.x, b1.y)], InVote[b1], f.x), f.y);
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy);
    if (any(p >= int2(DstTexSize.xy))) return;
    const float vote = Vote(p);
    if (vote <= LowVoteThreshold) return;
    const float4 normal = Normals[p];
    // Material 0 only; zero guides mean a skipped pixel with nothing demodulated.
    const float4 specularAlbedo = SpecAlbedo[p], diffuseAlbedo = DiffAlbedo[p];
    if (normal.a > 1.0f / 6.0f || dot(specularAlbedo.rgb + diffuseAlbedo.rgb, 1.0f) <= 0.0f) return;
    if (vote <= VoteThreshold && InLike[p] < 0.5f) return;
    const float4 specular = SpecSignal[p], diffuse = DiffSignal[p];
    SpecSignal[p] = float4(min(specular.rgb * specularAlbedo.rgb, 65504.0f), specular.a);
    DiffSignal[p] = float4(min(diffuse.rgb * diffuseAlbedo.rgb, 65504.0f), diffuse.a);
    SpecAlbedo[p] = float4(1.0f, 1.0f, 1.0f, specularAlbedo.a);
    DiffAlbedo[p] = float4(1.0f, 1.0f, 1.0f, diffuseAlbedo.a);
    Normals[p] = float4(normal.xyz, 2.0f / 3.0f);
}
