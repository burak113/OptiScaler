// FSR-RR Composition Utility
#include "FSRDPreprocessCommon.hlsli"

#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 5), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), " \
    "StaticSampler(s0, " \
        "filter = FILTER_MIN_MAG_MIP_LINEAR, " \
        "addressU = TEXTURE_ADDRESS_CLAMP, " \
        "addressV = TEXTURE_ADDRESS_CLAMP, " \
        "addressW = TEXTURE_ADDRESS_CLAMP, " \
        "visibility = SHADER_VISIBILITY_ALL)"

#define FLAGS_RAW_SOURCE_BLIT           (1 << 0)
#define FLAGS_SCALE_SRC                 (1 << 1)

// Debug Flags
#define FLAGS_DEBUG                     (1 << 16)
#define FLAGS_DEBUG_MODE_MASK           (0xFF << 16)

#define FLAGS_DEBUG_CORRELATION_BIAS    (1 << 17 | FLAGS_DEBUG)

Texture2D<float4> InDenoisedColor : register(t0); // Denoiser output
Texture2D<float4> InDemodulatedColor : register(t1); // Denoiser input
Texture2D<float4> InFusedModulator : register(t2);
Texture2D<float3> InColorBeforeParticles : register(t3);
Texture2D<float4> InSkipSignal : register(t4);

RWTexture2D<float4> OutColor : register(u0);

SamplerState LinearSampler : register(s0);

cbuffer CB_Comp : register(b0)
{
    float4 DstTexSize;
    
    float CorrelationBias;
    uint Flags;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return (Flags & FLAGS_DEBUG_MODE_MASK); }

// Correlates raw noisy input with denoised color in demodulated radiance space, 
// using a modified pearson coefficient.
float CorrelateDemodulatedColor(const uint2 id, const float3 denoisedDemodColor)
{
    float denoisedLuma = dot(denoisedDemodColor, 1.0f); // D
    float rawLuma = dot(InDemodulatedColor[id.xy].rgb, 1.0f); // R

    float sumD = denoisedLuma; // Denoised Demodulated
    float sumR = rawLuma; // Raw Demodulated
    float sumDD = denoisedLuma * denoisedLuma; // D^2
    float sumRR = rawLuma * rawLuma; // R^2
    float sumRD = rawLuma * denoisedLuma; // R*D
    
    [unroll]
    for (int x = -1; x < 2; x++)
    {
        [unroll]
        for (int y = -1; y < 2; y++)
        {
            if (x != 0 || y != 0)
            {
                // Raw luma is clamped to a range around the denoised luma to allow 
                // for variations without allowing non-central fireflies/error to dominate
                // the correlation coefficient. The center is unclamped to ensure that if 
                // the current pixel is the outlier, it is strongly rejected.
                const int2 offset = int2(x, y);
                
                denoisedLuma = dot(InDenoisedColor[id.xy + offset], 1.0f);
                rawLuma = dot(InDemodulatedColor[id.xy + offset].rgb, 1.0f);
                rawLuma = clamp(rawLuma, 0.1f * denoisedLuma, 10.0f * denoisedLuma);
                
                sumD += denoisedLuma;
                sumR += rawLuma;
                sumDD += denoisedLuma * denoisedLuma;
                sumRR += rawLuma * rawLuma;
                sumRD += rawLuma * denoisedLuma;
            }
        }
    }

    const float invN = 0.111111f;
    const float avgD = sumD * invN;
    const float avgR = sumR * invN;
    
    // Variances (std.dev^2)
    // E[X^2] - (E[X])^2 - Average of squares, less the square of the average
    const float varD = max((sumDD * invN) - (avgD * avgD), 0.0f);
    const float varR = max((sumRR * invN) - (avgR * avgR), 0.0f);
    
    // Covariance
    // E[X*Y] - E[X]E[Y] - Average of R*D product, less product of their averages
    const float covRD = (sumRD * invN) - (avgD * avgR);
    
    // Pearson correlation - covRD / product of std.dev of D and R
    const float correlation = saturate(covRD * rsqrt(varD * varR + 1e-3f));
    
    return correlation;
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= DstTexSize.x || id.y >= DstTexSize.y)
    {
        OutColor[id.xy] = 0.0f;
        return;
    }
    
    [branch]
    if (IsSet(FLAGS_RAW_SOURCE_BLIT))
    {
        [branch]
        if (IsSet(FLAGS_SCALE_SRC))
        {
            const float2 uv = (float2(id.xy) + 0.5f) * DstTexSize.zw;
            OutColor[id.xy] = InDenoisedColor.SampleLevel(LinearSampler, uv, 0);
        }
        else
        {
            OutColor[id.xy] = InDenoisedColor[id.xy];
        } 
    }
    else
    {
        const float3 denoisedDemodColor = InDenoisedColor[id.xy].rgb; // Demodulated denoised color
        const float correlation = CorrelateDemodulatedColor(id.xy, denoisedDemodColor) * CorrelationBias;
        
        [branch]
        if (IsSet(FLAGS_DEBUG_CORRELATION_BIAS))
        {
            OutColor[id.xy] = float4(TurboColormap(correlation), 1.0f);
        }
        else
        {
            const float4 skip = InSkipSignal[id.xy];
            const float3 particles = InColorBeforeParticles[id.xy];
            const float3 remod = InFusedModulator[id.xy].rgb;
            const float3 denoisedColor = denoisedDemodColor * remod;
            const float skipWeight = saturate(correlation + skip.a);
            const float3 outColor = lerp(denoisedColor, skip.rgb, skipWeight);
                
            OutColor[id.xy] = float4(outColor + particles.rgb, 1.0f);
        }
    }
}