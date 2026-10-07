// Volumetric restore, step 3 of 3: add the accumulated positive shortfall back to
// RR's composed output. RR's image is never filtered or replaced; this pass only
// adds a smooth layer of the energy RR removed from the input.
// The tile layer is spread with bilinear weights that also respect depth, so a
// foreground silhouette does not inherit the fog behind it.
#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<half4> InComposed : register(t0);
Texture2D<half4> InHistory : register(t1);    // FSRDVolumeAccumulate output
Texture2D<float> InLinearDepth : register(t2);
RWTexture2D<half4> OutColor : register(u0);

cbuffer CB_VolumeApply : register(b0)
{
    float4 DstTexSize; // XY = size, ZW = 1 / size
    float Strength;
    float3 _Reserved0;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    const int2 p = int2(id.xy), size = int2(DstTexSize.xy);
    if (any(p >= size))
        return;
    const float4 composed = InComposed[p];
    const int2 tiles = (size + 7) / 8;
    const float z = abs(InLinearDepth[p]);
    const float2 position = (float2(p) + 0.5f) / 8.0f - 0.5f;
    const int2 origin = int2(floor(position));
    const float2 fraction = position - float2(origin);
    float3 layer = 0.0f;
    float total = 0.0f;
    [unroll]
    for (uint i = 0; i < 4; ++i)
    {
        const int2 offset = int2(i & 1, i >> 1);
        const int2 tile = clamp(origin + offset, 0, tiles - 1);
        const float4 history = InHistory[tile];
        const float2 axis = lerp(1.0f - fraction, fraction, float2(offset));
        float weight = axis.x * axis.y;
        if (isfinite(z) && z > 0.0f)
            weight *= Square(saturate(1.0f - abs(float(history.a) - z) / max(0.1f * z, 1e-3f)));
        if (all(isfinite(history.rgb)))
        {
            layer += weight * max(float3(history.rgb), 0.0f);
            total += weight;
        }
    }
    const float3 restored = total > 1e-4f ? layer / total : 0.0f;
    OutColor[p] = half4(FloorRadiance(composed.rgb + Strength * restored), composed.a);
}
