// RR colour tracking (task 25 T2), experimental, default off - step 3 of 3, FULL RESOLUTION, IN PLACE.
// Applies the quarter-res gain field to the composite with a bilinear upsample and restores the pixel's own
// luminance exactly, so the pass can only move colour, never level:
//   out = y * g;  out *= luma(y) / luma(out)
// The gain field is very low frequency (a 24-pixel radius over a quarter-res grid), so the bilinear upsample
// adds no structure of its own; the edge-aware smoothing lives in the quarter-res pass above.
// In place: the composite is read through its own UAV, the pattern the flat-detail apply pass uses. Binding the
// same texture as an SRV and a UAV in one dispatch is legal at execution time but fails the debug layer's static
// descriptor check, and a pointwise read of the UAV is the same value.
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 1)), DescriptorTable(UAV(u0, numDescriptors = 1)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
Texture2D<float4> InGain : register(t0);    // rgb the gain, a 1 (quarter resolution)
SamplerState InSampler : register(s0);
RWTexture2D<float4> OutColor : register(u0); // the composite of this frame, read and written
cbuffer CB_ColourTrackApply : register(b0)
{
    float4 Size;    // full width, height, 1/width, 1/height
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy);
    if (any(p >= int2(Size.xy))) return;
    const float3 colour = OutColor[p].rgb;
    const float4 gain = InGain.SampleLevel(InSampler, (float2(p) + 0.5f) / Size.xy, 0.0f);
    float3 tracked = colour * gain.rgb;
    // Exact luminance restore: the correction is chromatic only, the level stays RR's.
    const float luma = GetLuminance(colour);
    tracked *= luma / max(GetLuminance(tracked), 1e-9f);
    OutColor[p] = float4(SanitizeRadiance(tracked), 1.0f);
}
