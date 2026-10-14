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
cbuffer CommitConstants : register(b0) { uint2 RenderSize; uint OutputEncoding; uint NativeConstantsPresent; float NativeSpecularBlend; }
cbuffer TitleConsumer : register(b6) { uint4 TitleConsumerConstants[76]; }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    const uint encoding = NativeConstantsPresent ? (TitleConsumerConstants[75].w != 0u ? 1u : 0u) : OutputEncoding;
    // RR1.2 writes denoised RGB; the title owns its auxiliary alpha payload.
    // Read and preserve the current title alpha just as a direct RGB RR write would.
    // A pointwise NRD-assisted hybrid: it neither changes RR's private history
    // nor estimates confidence/noise. Every thread owns exactly one output pixel.
    const float blend = isfinite(NativeSpecularBlend) ? saturate(NativeSpecularBlend) : 0.0f;
    if (blend == 0.0f)
        TitleSpec[tid.xy] = float4(EncodeNrdSignal(StagedSpec[tid.xy].rgb, encoding), TitleSpec[tid.xy].a);
    else if (blend < 1.0f)
    {
        const float4 native = TitleSpec[tid.xy];
        if (all(isfinite(native.rgb)))
        {
            // Exact attested Consumer inverse, using the same live word303 as encoding.
            precise float3 nativeRgb = native.rgb;
            if (encoding != 0u)
                nativeRgb = max(float3(native.x - native.z + native.y, native.x + native.z,
                                       native.x - native.z - native.y), 0.0f);
            precise float3 mixed = StagedSpec[tid.xy].rgb * (1.0f - blend) + nativeRgb * blend;
            // Extreme finite native YCoCg can decode beyond the half range.
            // Bound only the intermediate hybrid; both endpoints retain their old bits.
            mixed = clamp(mixed, -65504.0f, 65504.0f);
            TitleSpec[tid.xy] = float4(EncodeNrdSignal(mixed, encoding), native.a);
        }
        else
            TitleSpec[tid.xy] = float4(EncodeNrdSignal(StagedSpec[tid.xy].rgb, encoding), native.a);
    }
    // At blend1 there is no specular store: encoded RGB and opaque alpha stay exact.
    TitleDiff[tid.xy] = float4(EncodeNrdSignal(StagedDiff[tid.xy].rgb, encoding), TitleDiff[tid.xy].a);
}
