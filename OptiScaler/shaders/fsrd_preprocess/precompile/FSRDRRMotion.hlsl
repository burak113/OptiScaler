// Motion vectors handed to RR: the converter's canonical motion plus the jitter difference.
//
// The converter keeps one canonical motion field, the unjittered previous UV minus current UV, and every
// internal consumer (Floor, albedo stabilisation, fog statistics, composition history) adds the jitter
// difference itself. RR does not: it ignores jitterOffsets and treats the vector as the texel-to-texel
// displacement between the two jittered rasters. With the canonical field its history lands one jitter
// difference away (0.25 px on average with the Halton sequence) and its output trails the current frame's
// guides by the current jitter. A texel of frame f holds the surface at unjittered (q + 0.5 - J_f), so the
// displacement RR needs is the canonical motion plus (J_prev - J_cur) / size.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), "

Texture2D<float4> InMotion : register(t0); // XY: unjittered previous UV - current UV, Z: depth delta, W: valid
RWTexture2D<float4> OutMotion : register(u0);

cbuffer CB_RRMotion : register(b0)
{
    float4 DstTexSize;
    float2 JitterDeltaUv; // (previous jitter - current jitter) / render size
    float2 _Reserved0;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    if (any(dtID.xy >= uint2(DstTexSize.xy)))
        return;
    const float4 motion = InMotion[dtID.xy];
    OutMotion[dtID.xy] = float4(motion.xy + JitterDeltaUv, motion.zw);
}
