// Private research capture only. Physical/perceptual meaning of native t5.A is
// unproven. This shader preserves its exact UNORM8 code, including genuine zero.
#define MainRS \
    "RootFlags(0), " \
    "DescriptorTable(SRV(t5, numDescriptors = 1, flags = DESCRIPTORS_VOLATILE | DATA_VOLATILE)), " \
    "UAV(u0, flags = DATA_VOLATILE), " \
    "RootConstants(num32BitConstants = 2, b0)"
Texture2D<float4> NativeNormal : register(t5);
RWByteAddressBuffer PrivateRawRoughness : register(u0);
cbuffer Extent : register(b0) { uint2 RenderSize; }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 threadId : SV_DispatchThreadID)
{
    const uint2 p = threadId.xy;
    if (any(p >= RenderSize)) return;
    const float rawAlpha = NativeNormal.Load(int3(p, 0)).a;
    const uint rawCode = (uint)(rawAlpha * 255.0f + 0.5f);
    PrivateRawRoughness.Store((p.y * RenderSize.x + p.x) * 4u, rawCode);
}
