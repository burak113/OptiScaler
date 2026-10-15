// Test-only exact Consumer RGB/factor64 model with the second validated native flag location.
#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants = 2, b0), " \
    "DescriptorTable(CBV(b6, numDescriptors = 1)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 4)), UAV(u4)"
cbuffer Size : register(b0) { uint2 RenderSize; }
cbuffer NativeConsumer : register(b6) { uint4 Native[76]; }
RWTexture2D<float4> TitleDiff : register(u0);
RWTexture2D<float4> TitleSpec : register(u1);
RWTexture2D<float4> DecodedDiff : register(u2);
RWTexture2D<float4> DecodedSpec : register(u3);
RWByteAddressBuffer SeenFlag : register(u4);
float3 ConsumerRgb(float3 signal, uint flag)
{
    if (flag == 0u) return signal;
    return max(float3(signal.x-signal.z+signal.y,signal.x+signal.z,signal.x-signal.z-signal.y),0.0f);
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const uint flag = Native[9].x;
    if (all(tid.xy == 0)) SeenFlag.Store(0,flag);
    DecodedDiff[tid.xy] = float4(ConsumerRgb(TitleDiff[tid.xy].rgb,flag)*64.0f,1.0f);
    DecodedSpec[tid.xy] = float4(ConsumerRgb(TitleSpec[tid.xy].rgb,flag)*64.0f,1.0f);
}
