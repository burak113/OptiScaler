#include "FSRDNrdMaterialGuides.hlsli"
#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants = 2, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2))"
cbuffer Extent : register(b0) { uint2 RenderSize; }
Texture2D<float4> Material : register(t0);
Texture2D<float4> NativeNormalRoughness : register(t1);
Texture2D<float> NoV : register(t2);
RWTexture2D<float4> Diffuse : register(u0);
RWTexture2D<float4> Specular : register(u1);
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const float4 material = Material[tid.xy];
    const float4 nr = NativeNormalRoughness[tid.xy];
    Diffuse[tid.xy] = float4(NrdDiffuseMaterialGuide(material,nr.a),nr.a);
    Specular[tid.xy] = float4(NrdSpecularMaterialGuide(material,nr.a,nr.b,NoV[tid.xy]),NoV[tid.xy]);
}
