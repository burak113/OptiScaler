// Unsupported-albedo evidence, the first of the recovery passes that run after RR.
//
// A transparent layer such as water hands the denoiser the material guides of the surface
// beneath it: the sea floor's albedo and roughness arrive with radiance that is the water's
// reflection and volume. Demodulating by that albedo and remodulating after RR prints the
// sea floor into the image, which the water's own volume would have hidden. The local test
// for it is that the albedo varies while the light does not: on a real texture the light
// carries the albedo's structure (or structure of its own), on a hidden surface it is flat.
//
// The light is judged on RR's own output of the unmodulated specular path plus the
// remodulated diffuse path and the diffuse share of Skip. That witness is denoised and,
// unlike the final image, contains no albedo imprint of its own, so a strong existing stain
// cannot vouch for the albedo that caused it. Output: x = unsupported structure, y = albedo
// structure mass; FSRDAlbedoTrustPropagate spreads both over the surface before
// composition takes their ratio.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 9)), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<half4> InDirectSpecularDenoised : register(t0);
Texture2D<half4> InDirectDiffuse : register(t1);
Texture2D<half4> InSpecularAlbedo : register(t2);
Texture2D<half4> InDiffuseAlbedo : register(t3);
Texture2D<half4> InSkipSignal : register(t4);
Texture2D<float> InLinearDepth : register(t5);
Texture2D<half4> InNormals : register(t6);
// A: conversion's eligibility; ineligible pixels neither vote nor receive the blend.
Texture2D<half4> InDirectSpecularSignal : register(t7);
Texture2D<half4> InIndirectDiffuseDenoised : register(t8);
RWTexture2D<float2> OutAlbedoTrust : register(u0);

cbuffer CB_AlbedoTrust : register(b0)
{
    float4 DstTexSize;
    int StepSize;
    uint Flags;
    float DemodDivisorFloor;
    float _Reserved0;
}

#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
#define NUM_THREADS 64
// Radius four: the 9x9 window the replayed captures were evaluated with.
DEFINE_LDS_CONFIG(s_SM, 9);
groupshared float g_LogAlbedo[16][16];
groupshared float g_LogLight[16][16];
groupshared float g_Depth[16][16];
groupshared half3 g_Normal[16][16];

// The share of a channel the conversion allocated to the specular lobe; the remaining
// share of Skip belongs to the diffuse half of the witness.
float3 SpecularShare(float3 spec, float3 diff)
{
    const float3 total = spec + diff;
    const float3 splitT = saturate((total - 0.5f * DemodDivisorFloor) / (0.5f * DemodDivisorFloor));
    return spec * rcp(max(total, DemodDivisorFloor)) * splitT * splitT * (3.0f - 2.0f * splitT);
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const int2 bounds = int2(DstTexSize.xy) - 1;
    const int2 origin = int2(groupID.xy * 8) - int2(s_SM_HaloOffset);
    const uint tid = gtID.x + gtID.y * 8;
    [unroll] for (uint i = 0; i < s_SM_LoadsPerThread; ++i)
    {
        const uint flat = tid + i * 64;
        if (flat < 256)
        {
            const int2 s = int2(flat % 16, flat / 16);
            const int2 source = origin + s;
            const int2 q = clamp(source, 0, bounds);
            const float3 spec = InSpecularAlbedo[q].rgb, diff = InDiffuseAlbedo[q].rgb;
            const float3 witness = float3(InDirectSpecularDenoised[q].rgb) +
                (float3(InDirectDiffuse[q].rgb) +
                 ((Flags & 1u) != 0 ? float3(InIndirectDiffuseDenoised[q].rgb) : 0.0f)) * diff +
                float3(InSkipSignal[q].rgb) * (1.0f - SpecularShare(spec, diff));
            // Clamping makes loads safe, but repeated border texels cannot count
            // as independent support. Mark them invalid once while loading LDS.
            const bool eligible = all(source >= 0) && all(source <= bounds) &&
                InDirectSpecularSignal[q].a >= 0.5f;
            const float z = InLinearDepth[q];
            g_LogAlbedo[s.y][s.x] = log(max(GetLuminance(spec + diff), 1.0f / 255.0f));
            g_LogLight[s.y][s.x] = log(max(GetLuminance(max(witness, 0.0f)), 1e-4f));
            // An ineligible tap carries no depth, which removes it from every window.
            g_Depth[s.y][s.x] = eligible && isfinite(z) ? z : 0.0f;
            g_Normal[s.y][s.x] = half3(OctahedralDecode(InNormals[q].xy));
        }
    }
    GroupMemoryBarrierWithGroupSync();

    const int2 p = int2(groupID.xy * 8 + gtID.xy);
    if (any(p > bounds))
        return;
    const int2 c = int2(gtID.xy) + int2(s_SM_HaloOffset);
    const float z = g_Depth[c.y][c.x];
    if (z == 0.0f)
    {
        OutAlbedoTrust[p] = 0.0f;
        return;
    }
    const float3 n = float3(g_Normal[c.y][c.x]);
    const float depthTolerance = max(0.02f * abs(z), 1e-3f);
    float count = 0, sumA = 0, sumAA = 0, sumL = 0, sumLL = 0;
    [unroll] for (int y = -4; y <= 4; ++y)
    {
        [unroll] for (int x = -4; x <= 4; ++x)
        {
            const int2 s = c + int2(x, y);
            const float tapZ = g_Depth[s.y][s.x];
            const float reach = 1.0f + 0.5f * float(max(abs(x), abs(y)));
            if (tapZ * z > 0.0f && abs(tapZ - z) <= depthTolerance * reach &&
                dot(float3(g_Normal[s.y][s.x]), n) >= 0.9f)
            {
                const float a = g_LogAlbedo[s.y][s.x], l = g_LogLight[s.y][s.x];
                count += 1.0f;
                sumA += a; sumAA += a * a;
                sumL += l; sumLL += l * l;
            }
        }
    }
    if (count <= 10.0f)
    {
        OutAlbedoTrust[p] = 0.0f;
        return;
    }
    const float meanA = sumA / count, meanL = sumL / count;
    const float albedoVariance = max(sumAA / count - meanA * meanA, 0.0f);
    const float lightVariance = max(sumLL / count - meanL * meanL, 0.0f);
    // Structure mass: enough albedo variation over enough same-surface samples that the
    // question is meaningful. Thin poles and silhouettes abstain rather than vote.
    const float structure = smoothstep(0.02f, 0.06f, albedoVariance) * smoothstep(10.0f, 30.0f, count);
    // Unsupported: the light varies much less than the albedo would make it.
    const float unsupported = structure *
        (1.0f - smoothstep(0.05f, 0.2f, lightVariance / max(albedoVariance, 1e-4f)));
    OutAlbedoTrust[p] = float2(unsupported, structure);
}
