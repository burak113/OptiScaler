// Read the exact current title MV when its first chain-A Temporal SRV is bound.
#include "FSRDNrdMotionCommon.hlsli"
#ifdef FSRD_NRD_NATIVE_MOTION
#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 32, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 4)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1)), " \
    "CBV(b1, flags = DATA_VOLATILE)"
#else
#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 32, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"
#endif
Texture2D<float4> InMotion : register(t0);
Texture2D<float> InDepth : register(t1);
Texture2D<float> InPreviousDepth : register(t2);
#ifdef FSRD_NRD_NATIVE_MOTION
Texture2D<float> InNativeViewDepth : register(t3);
cbuffer NativeMotionConstants : register(b1) { NrdNativeTemporalData NativeTemporal; }
#endif
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
#ifdef FSRD_NRD_NATIVE_MOTION
    // Missing/invalid native operands use current-surface camera prediction,
    // never the previous visible occluder's unrelated depth.
    const float3 rawMotion = InMotion[p].xyz;
    const float signedDepth = InDepth[p];
    float4 result = ConvertNrdMotion(p, RenderSize, rawMotion.xy, signedDepth, PreviousValid,
                                    InPreviousDepth, MotionScale, JitterDeltaUv, 1u,
                                    InverseProjection, PreviousViewDepthRow, CurrentJitterUv);
    uint nativeWidth, nativeHeight;
    InNativeViewDepth.GetDimensions(nativeWidth, nativeHeight);
    if (all(uint2(nativeWidth, nativeHeight) == RenderSize))
    {
        float nativeDelta;
        if (TryNativeNrdDepthDelta(p, RenderSize, rawMotion, signedDepth, InNativeViewDepth[p],
                                  PreviousValid, NativeTemporal, nativeDelta)) result.z = nativeDelta;
    }
    OutMotion[p] = result;
#else
    OutMotion[p] = ConvertNrdMotion(p, RenderSize, InMotion[p].xy, InDepth[p], PreviousValid,
                                   InPreviousDepth, MotionScale, JitterDeltaUv, Reserved,
                                   InverseProjection, PreviousViewDepthRow, CurrentJitterUv);
#endif
}
