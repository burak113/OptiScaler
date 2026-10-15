#include "FSRDNrdMaterialQuantization.hlsli"
#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants = 2, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 1)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2))"
cbuffer Extent : register(b0) { uint2 RenderSize; }
Texture2D<float4> Input : register(t0);
RWTexture2D<float4> RoundedFloat : register(u0);
RWTexture2D<float4> RoundedHalf : register(u1);
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const float4 rounded = NrdRoundMaterialHalfNearestEven(Input[tid.xy]);
    RoundedFloat[tid.xy] = rounded;
    RoundedHalf[tid.xy] = rounded;
}
