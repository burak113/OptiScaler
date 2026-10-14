#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 4, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 1)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<float4> NativeDebug : register(t0);
RWTexture2D<float4> Output : register(u0);
cbuffer PresentConstants : register(b0) { uint2 SourceSize; uint2 OutputSize; }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= OutputSize)) return;
    const uint2 source = min((tid.xy * SourceSize) / OutputSize, SourceSize - 1u);
    const float4 pixel = NativeDebug.Load(int3(source, 0));
    // AMD's fourth component marks coverage. Preserve both the game's pixels
    // outside that coverage and its auxiliary alpha inside it.
    if (pixel.a > 0.0f) Output[tid.xy] = float4(pixel.rgb, Output[tid.xy].a);
}
