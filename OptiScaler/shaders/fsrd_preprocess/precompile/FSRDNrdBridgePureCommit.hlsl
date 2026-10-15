#include "FSRDNrdSignalEncoding.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 5, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2)), " \
    "CBV(b6, space = 0)"

Texture2D<float4> StagedSpec : register(t0);
Texture2D<float4> StagedDiff : register(t1);
RWTexture2D<float4> TitleSpec : register(u0);
RWTexture2D<float4> TitleDiff : register(u1);
// The fifth DWORD remains ABI padding. It must never influence any output.
cbuffer CommitConstants : register(b0) { uint2 RenderSize; uint OutputEncoding; uint NativeConstantsPresent; float LegacyUnusedBlend; }
cbuffer TitleConsumer : register(b6) { uint4 TitleConsumerConstants[76]; }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const uint encoding = NativeConstantsPresent ? (TitleConsumerConstants[75].w != 0u ? 1u : 0u) : OutputEncoding;
    // Lighting comes exclusively from staged RR. The title owns opaque alpha;
    // no title RGB is read, decoded, blended, copied, or used as a fallback.
    const float specAlpha = TitleSpec[tid.xy].a;
    const float diffAlpha = TitleDiff[tid.xy].a;
    TitleSpec[tid.xy] = float4(EncodeNrdSignal(StagedSpec[tid.xy].rgb, encoding), specAlpha);
    TitleDiff[tid.xy] = float4(EncodeNrdSignal(StagedDiff[tid.xy].rgb, encoding), diffAlpha);
}
