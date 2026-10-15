#include "FSRDNrdMaterialQuantization.hlsli"
#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 2, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2))"

cbuffer MaterialExtent : register(b0) { uint2 RenderSize; }
Texture2D<float4> NativeBaseColor : register(t0);
Texture2D<float4> NativeMaterialParams : register(t1);
RWTexture2D<float4> PrivateBaseColorMetallic : register(u0);
RWTexture2D<float> PrivateMaterialRoughness : register(u1);

// A distinct ABI preserves the legacy one-output capture asset. Sources are
// already state-proven and borrowed by the host; only private outputs change.
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const float3 encoded = NativeBaseColor[tid.xy].rgb;
    const float2 material = NativeMaterialParams[tid.xy].rg;
    PrivateBaseColorMetallic[tid.xy] = NrdRoundMaterialHalfNearestEven(float4(encoded * encoded, material.r));
    // Keep raw G: only analytic specular-albedo evaluation applies the .04 floor.
    PrivateMaterialRoughness[tid.xy] = NrdRoundMaterialHalfNearestEven(float4(material.g, 0.0f, 0.0f, 0.0f)).x;
}
