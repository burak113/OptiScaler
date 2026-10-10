// FSR-RR texture leak views (26 Sep)
//
// How much of the albedo pattern is still in the lighting handed to the denoiser, per lobe. Reads
// the packing shader's outputs, i.e. exactly what the denoiser receives: demodulated lighting
// (SpecRadiance / DiffRadiance) and the albedos the composition multiplies back in.
//
// For each pixel, over a 7x7 window on the same surface (depth within 2%, normals within ~25 deg),
// fits log2(lighting) = beta * log2(albedo) + c by least squares:
//
//   beta = cov(log L, log A) / var(log A)
//
//   beta  0  clean demodulation: the lighting doesn't follow the texture
//   beta +1  none at all: the texture is fully in the lighting (divided by nothing that matches)
//   beta -1  inverse imprint: light the surface didn't reflect (fog, glass, particles, emission)
//            divided by the surface's albedo
//
// Noise in the lighting that is uncorrelated with the albedo leaves beta unbiased, only noisier. Where
// the albedo hardly varies over the window there is nothing that could leak and beta means nothing, so
// the colour fades with the albedo's own contrast (log2 standard deviation 0.05 -> 0.3).
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 6), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), "

#define THREAD_GROUP_SIZE_X     8
#define THREAD_GROUP_SIZE_Y     8

#define FLAGS_DIFFUSE           (1 << 0) // diffuse lobe; clear = specular

#define LEAK_RADIUS             3

Texture2D<half4> InSpecRadiance : register(t0); // demodulated specular lighting, alpha = hit distance
Texture2D<half4> InDiffRadiance : register(t1); // demodulated diffuse lighting
Texture2D<half4> InSpecAlbedo : register(t2);   // stored specular albedo (linear)
Texture2D<half4> InDiffAlbedo : register(t3);   // stored diffuse albedo (linear)
Texture2D<float> InLinearDepth : register(t4);
Texture2D<float4> InNormals : register(t5);     // RG: octahedral normal, B: roughness

RWTexture2D<half4> OutView : register(u0);

cbuffer CB_Leak : register(b0)
{
    float4 DstTexSize; // XY = size, ZW = 1 / size
    uint Flags;
    float3 _Padding;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

void ReadLobe(const int2 p, out float lighting, out float albedo)
{
    if (IsSet(FLAGS_DIFFUSE))
    {
        lighting = GetLuminance(float3(InDiffRadiance[p].rgb));
        albedo = GetLuminance(float3(InDiffAlbedo[p].rgb));
    }
    else
    {
        lighting = GetLuminance(float3(InSpecRadiance[p].rgb));
        albedo = GetLuminance(float3(InSpecAlbedo[p].rgb));
    }
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    const int2 px = int2(dtID.xy);
    const int2 maxPx = int2(DstTexSize.xy) - 1;

    if (any(px > maxPx))
        return;

    float centerLighting;
    float centerAlbedo;
    ReadLobe(px, centerLighting, centerAlbedo);

    // Skipped pixels (sky, no albedo) have zero albedo and zero lighting: nothing to show.
    if (centerAlbedo < 1e-3f)
    {
        OutView[px] = half4(0.0f, 0.0f, 0.0f, 1.0f);
        return;
    }

    const float centerDepth = abs(InLinearDepth[px]);
    const float3 centerNormal = OctahedralDecode(InNormals[px].rg);

    float w = 0.0f;
    float sx = 0.0f;
    float sy = 0.0f;
    float sxx = 0.0f;
    float sxy = 0.0f;

    [loop]
    for (int y = -LEAK_RADIUS; y <= LEAK_RADIUS; y++)
    {
        [loop]
        for (int x = -LEAK_RADIUS; x <= LEAK_RADIUS; x++)
        {
            const int2 p = clamp(px + int2(x, y), int2(0, 0), maxPx);

            float lighting;
            float albedo;
            ReadLobe(p, lighting, albedo);

            const float depth = abs(InLinearDepth[p]);
            const float3 normal = OctahedralDecode(InNormals[p].rg);
            const bool sameSurface = (albedo >= 1e-3f) && (abs(depth - centerDepth) < 0.02f * centerDepth) &&
                                     (dot(normal, centerNormal) > 0.9f);

            if (!sameSurface)
                continue;

            const float lx = log2(albedo);
            const float ly = log2(max(lighting, 1e-4f));

            w += 1.0f;
            sx += lx;
            sy += ly;
            sxx += lx * lx;
            sxy += lx * ly;
        }
    }

    float3 color = float3(0.0f, 0.0f, 0.0f);

    if (w >= 8.0f)
    {
        const float mx = sx / w;
        const float my = sy / w;
        const float varX = max(sxx / w - mx * mx, 0.0f);
        const float covXY = sxy / w - mx * my;

        const float beta = covXY / max(varX, 1e-6f);
        const float confidence = smoothstep(0.05f, 0.3f, sqrt(varX));

        // Diverging map around a grey zero: red toward +1 (texture in the lighting), yellow past +1,
        // blue toward -1 (inverse imprint). Faded to black where the albedo has no texture to leak.
        const float3 grey = float3(0.25f, 0.25f, 0.25f);
        float3 mapped;

        if (beta >= 0.0f)
            mapped = (beta <= 1.0f) ? lerp(grey, float3(1.0f, 0.0f, 0.0f), beta)
                                    : lerp(float3(1.0f, 0.0f, 0.0f), float3(1.0f, 1.0f, 0.0f), saturate(beta - 1.0f));
        else
            mapped = lerp(grey, float3(0.0f, 0.3f, 1.0f), saturate(-beta));

        color = mapped * confidence;
    }

    OutView[px] = half4(color, 1.0f);
}
