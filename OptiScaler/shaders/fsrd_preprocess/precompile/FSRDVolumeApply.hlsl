// Volumetric restore, step 3 of 3: add the accumulated positive shortfall back to
// RR's composed output. RR's image is never filtered or replaced; this pass only
// adds a smooth layer of the energy RR removed from the input.
// The tile layer is spread over a 6x6-tile tent (about 40 px) with weights that also
// respect depth, so a foreground silhouette does not inherit the fog behind it. Fog is
// smooth at that scale, and averaging 25+ tiles keeps the unclipped means' noise from
// reaching the screen as flicker.
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
    float3 layer = 0.0f;
    float total = 0.0f;
    [unroll]
    for (uint i = 0; i < 36; ++i)
    {
        const int2 offset = int2(i % 6, i / 6) - 2;
        const int2 tile = clamp(origin + offset, 0, tiles - 1);
        const float4 history = InHistory[tile];
        const float2 axis = saturate(1.0f - abs(position - float2(origin + offset)) / 3.0f);
        float weight = axis.x * axis.y;
        if (isfinite(z) && z > 0.0f)
            weight *= Square(saturate(1.0f - abs(float(history.a) - z) / max(0.1f * z, 1e-3f)));
        if (all(isfinite(history.rgb)))
        {
            layer += weight * float3(history.rgb);
            total += weight;
        }
    }
    // Average the signed differences first: clamping each noisy tile before the average would
    // turn their noise into added light where RR lost nothing.
    const float3 restored = total > 1e-4f ? max(layer / total, 0.0f) : 0.0f;
    OutColor[p] = half4(FloorRadiance(composed.rgb + Strength * restored), composed.a);
}
