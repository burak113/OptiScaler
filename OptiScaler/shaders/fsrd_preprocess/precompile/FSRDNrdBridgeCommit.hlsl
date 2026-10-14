#include "FSRDNrdSignalEncoding.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 4, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2)), " \
    "CBV(b6, space = 0)"

Texture2D<float4> StagedSpec : register(t0);
Texture2D<float4> StagedDiff : register(t1);
RWTexture2D<float4> TitleSpec : register(u0);
RWTexture2D<float4> TitleDiff : register(u1);
cbuffer CommitConstants : register(b0) { uint2 RenderSize; uint OutputEncoding; uint NativeConstantsPresent; }
cbuffer TitleConsumer : register(b6) { uint4 TitleConsumerConstants[76]; }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const uint encoding = NativeConstantsPresent ? (TitleConsumerConstants[75].w != 0u ? 1u : 0u) : OutputEncoding;
    // RR1.2 writes denoised RGB; the title owns its auxiliary alpha payload.
    // Read and preserve the current title alpha just as a direct RGB RR write would.
    TitleSpec[tid.xy] = float4(EncodeNrdSignal(StagedSpec[tid.xy].rgb, encoding), TitleSpec[tid.xy].a);
    TitleDiff[tid.xy] = float4(EncodeNrdSignal(StagedDiff[tid.xy].rgb, encoding), TitleDiff[tid.xy].a);
}
