// Post-motion level anchor (task 25 T3 ii), experimental, default off - step 3 of 3, FULL RESOLUTION.
// Multiplies RR's input signals by the anchored luminance gain, in place, so the denoiser integrates the
// corrected level instead of the post-flick excess. The gain is a 1/8-resolution field, read with hardware
// bilinear filtering (the clamp address mode reproduces the edge behaviour); the same factor goes on R, G and B,
// which keeps the noise white and the chroma exactly RR's input chroma. The alpha channel (the signal's own
// payload) is passed through untouched.
// The read and the write are the same texture: the static descriptor cannot be SRV and UAV in one dispatch (the
// debug layer rejects it), and a pointwise UAV read is the same value (the flat-detail apply's pattern).
#pragma once
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 1)), DescriptorTable(UAV(u0, numDescriptors = 2)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
RWTexture2D<float4> InOutDiffuse : register(u0);   // RR's input diffuse, in place
RWTexture2D<float4> InOutSpecular : register(u1);  // RR's input specular, in place
Texture2D<float4> InGain : register(t0);           // the 1/8-resolution gain field
SamplerState InSampler : register(s0);
cbuffer CB_PostMotionAnchorApply : register(b0)
{
    float4 Size; // full width, height, 1/width, 1/height
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 size = int2(Size.xy);
    const int2 p = int2(dispatch.xy);
    if (any(p >= size)) return;
    const float2 uv = (float2(p) + 0.5f) * float2(Size.z, Size.w);
    const float gain = saturate(InGain.SampleLevel(InSampler, uv, 0.0f).x);
    const float4 diffuse = InOutDiffuse[p];
    const float4 specular = InOutSpecular[p];
    InOutDiffuse[p] = float4(SanitizeRadiance(diffuse.rgb * gain), diffuse.a);
    InOutSpecular[p] = float4(SanitizeRadiance(specular.rgb * gain), specular.a);
}
