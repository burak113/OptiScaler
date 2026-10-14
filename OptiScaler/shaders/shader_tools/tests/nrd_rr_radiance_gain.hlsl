// RESEARCH ONLY. Never linked into the OptiScaler DLL or selected in production.
// Source/destination are fixture-owned RGBA16 resources. The same fixed gain is
// used throughout a physically fresh RR history; the inverse runs after RR and
// before the Consumer and image metrics. Alpha is copied without arithmetic.
#include "../../fsrd_preprocess/precompile/FSRDNrdSignalEncoding.hlsli"

#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants = 4, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 1)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

cbuffer GainParameters : register(b0)
{
    uint2 RenderSize;
    float FixedGain;
    uint Reserved;
}
Texture2D<float4> Source : register(t0);
RWTexture2D<float4> Target : register(u0);

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const float4 value = Source.Load(int3(tid.xy, 0));
    precise float3 rgb = value.rgb * FixedGain;
    // Make FP16 rounding explicit, including subnormal/tie cases. Typed stores
    // receive already representable half values; the CPU oracle uses IEEE RNE.
    rgb = f16tof32(uint3(NrdNearestHalfBits(rgb.x), NrdNearestHalfBits(rgb.y), NrdNearestHalfBits(rgb.z)));
    Target[tid.xy] = float4(rgb, value.a);
}
