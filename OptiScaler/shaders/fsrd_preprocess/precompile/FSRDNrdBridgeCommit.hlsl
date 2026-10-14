#define MainRS \
    "RootFlags(0), " \
    "RootConstants(num32BitConstants = 2, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2))"

Texture2D<float4> StagedSpec : register(t0);
Texture2D<float4> StagedDiff : register(t1);
RWTexture2D<float4> TitleSpec : register(u0);
RWTexture2D<float4> TitleDiff : register(u1);
cbuffer CommitConstants : register(b0) { uint2 RenderSize; }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    // RR1.2 writes denoised RGB; the title owns its auxiliary alpha payload.
    // Read and preserve the current title alpha just as a direct RGB RR write would.
    TitleSpec[tid.xy] = float4(StagedSpec[tid.xy].rgb, TitleSpec[tid.xy].a);
    TitleDiff[tid.xy] = float4(StagedDiff[tid.xy].rgb, TitleDiff[tid.xy].a);
}
