#include "FSRDPreprocessCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 2)), DescriptorTable(UAV(u0, numDescriptors = 2))"
Texture2D<float4> InNormals : register(t0);
Texture2D<float4> InSkip : register(t1);
RWByteAddressBuffer OutTiles : register(u0);
RWByteAddressBuffer OutArguments : register(u1);
cbuffer CB_Classify : register(b0) { float4 DstTexSize; }
groupshared uint HasFlat;
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    if (all(local.xy == 0)) HasFlat = 0;
    GroupMemoryBarrierWithGroupSync();
    const uint2 p = group.xy * 8 + local.xy;
    if (all(p < uint2(DstTexSize.xy)) && abs(InNormals[p].a - 1.0f / 3.0f) < 0.1f && InSkip[p].a != -1.0f)
        InterlockedOr(HasFlat, 1);
    GroupMemoryBarrierWithGroupSync();
    if (all(local.xy == 0) && HasFlat != 0)
    {
        uint index;
        OutTiles.InterlockedAdd(0, 1, index);
        OutTiles.Store2(16 + index * 8, group.xy);
        OutArguments.InterlockedMax(0, index % 65535u + 1u);
        OutArguments.InterlockedMax(4, index / 65535u + 1u);
    }
}
