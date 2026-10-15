#include "FSRDNrdMaterialQuantization.hlsli"
#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 2, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

cbuffer MaterialExtent : register(b0) { uint2 RenderSize; }
Texture2D<float4> NativeBaseColor : register(t0);
Texture2D<float4> NativeMaterialParams : register(t1);
RWTexture2D<float4> PrivateBaseColorMetallic : register(u0);

// Exact title compositor051b199b...38cc4 uses baseColor.rgb^2 and material.r.
// No noisy signal is read, divided, discarded, or routed around RR here.
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const float3 encoded = NativeBaseColor[tid.xy].rgb;
    const float4 material = float4(encoded * encoded, NativeMaterialParams[tid.xy].r);
    // Pre-round explicitly; the final D3D typed-FLOAT store uses RTZ.
    PrivateBaseColorMetallic[tid.xy] = NrdRoundMaterialHalfNearestEven(material);
}
