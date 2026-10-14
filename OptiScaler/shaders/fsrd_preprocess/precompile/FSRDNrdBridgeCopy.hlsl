#include "FSRDPreprocessCommon.hlsli"
#include "FSRDNrdSignalEncoding.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 5, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 7)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2)), " \
    "CBV(b6, space = 0)"

Texture2D<float4> InSpec : register(t0);
Texture2D<float4> InDiff : register(t1);
Texture2D<float4> InNormalRoughness : register(t2);
Texture2D<float> InDepth : register(t3);
Texture2D<float4> InMotion : register(t4);
Texture2D<float4> InSpecAlbedo : register(t5);
Texture2D<float4> InDiffAlbedo : register(t6);
RWTexture2D<float4> OutSpec : register(u0);
RWTexture2D<float4> OutDiff : register(u1);

cbuffer CopyConstants : register(b0)
{
    uint2 RenderSize;
    uint Mode;
    uint OutputEncoding;
    uint NativeConstantsPresent;
}
cbuffer TitleConsumer : register(b6) { uint4 TitleConsumerConstants[76]; }

uint DiagnosticStoredHalfBits(float value)
{
    // Diagnostic colors are finite and clamped to [0,1]. Reproduce their
    // existing RGB typed-store truncation before optional YCoCg coding.
    const uint bits = asuint(value), sign = (bits >> 16u) & 0x8000u;
    const uint magnitude = bits & 0x7fffffffu;
    if (magnitude >= 0x38800000u) return sign | ((magnitude >> 13u) - 0x1c000u);
    const uint exponent = magnitude >> 23u;
    if (exponent < 103u) return sign;
    return sign | (((magnitude & 0x7fffffu) | 0x800000u) >> (126u - exponent));
}
float3 DiagnosticStoredRgb(float3 rgb)
{
    return f16tof32(uint3(DiagnosticStoredHalfBits(rgb.x), DiagnosticStoredHalfBits(rgb.y), DiagnosticStoredHalfBits(rgb.z)));
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const uint2 p = tid.xy;
    if (any(p >= RenderSize)) return;
    const uint encoding = NativeConstantsPresent ? (TitleConsumerConstants[75].w != 0u ? 1u : 0u) : OutputEncoding;
    float3 spec = InSpec[p].rgb;
    float3 diff = InDiff[p].rgb;
    if (Mode == 2u)
    {
        // Three vertical diagnostic bands in each title output. Spec: decoded
        // world normal, roughness, NoV. Diff: log depth, signed motion, albedo.
        const uint band = min((p.x * 3u) / RenderSize.x, 2u);
        const float4 nr = InNormalRoughness[p];
        const float3 motion = InMotion[p].xyz;
        spec = band == 0u ? OctahedralDecode(nr.xy) * 0.5f + 0.5f
             : band == 1u ? nr.zzz : InSpecAlbedo[p].aaa;
        diff = band == 0u ? saturate(log2(1.0f + abs(InDepth[p])) / 16.0f).xxx
             : band == 1u ? float3(saturate(0.5f + motion.xy * float2(RenderSize) / 32.0f),
                                     saturate(0.5f + motion.z / 32.0f))
             : InDiffAlbedo[p].rgb;
        if (encoding != 0u)
        {
            spec = DiagnosticStoredRgb(spec);
            diff = DiagnosticStoredRgb(diff);
        }
    }
    // Diagnostic views write zero alpha; production RR preserves the native title payload.
    OutSpec[p] = float4(EncodeNrdSignal(spec, encoding), 0.0f);
    OutDiff[p] = float4(EncodeNrdSignal(diff, encoding), 0.0f);
}
