// Read the exact current title MV when its first chain-A Temporal SRV is bound.
#include "FSRDNrdMotionCommon.hlsli"
#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 32, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InMotion : register(t0);
Texture2D<float> InDepth : register(t1);
Texture2D<float> InPreviousDepth : register(t2);
RWTexture2D<float4> OutMotion : register(u0);
cbuffer MotionConstants : register(b0)
{
    uint2 RenderSize;
    uint PreviousValid;
    uint Reserved;
    float2 MotionScale;
    float2 JitterDeltaUv;
    row_major float4x4 InverseProjection;
    float4 PreviousViewDepthRow;
    float2 CurrentJitterUv;
    uint2 CameraReserved;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const uint2 p = tid.xy;
    if (any(p >= RenderSize)) return;
    OutMotion[p] = ConvertNrdMotion(p, RenderSize, InMotion[p].xy, InDepth[p], PreviousValid,
                                   InPreviousDepth, MotionScale, JitterDeltaUv, Reserved,
                                   InverseProjection, PreviousViewDepthRow, CurrentJitterUv);
}
