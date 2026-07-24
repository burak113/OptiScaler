#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 7), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), " \
    "StaticSampler(s0, " \
        "filter = FILTER_MIN_MAG_MIP_LINEAR, " \
        "addressU = TEXTURE_ADDRESS_CLAMP, " \
        "addressV = TEXTURE_ADDRESS_CLAMP, " \
        "addressW = TEXTURE_ADDRESS_CLAMP, " \
        "visibility = SHADER_VISIBILITY_ALL)"

// Dispatch config
#define THREAD_GROUP_SIZE_X     8
#define THREAD_GROUP_SIZE_Y     8
#define NUM_THREADS             (THREAD_GROUP_SIZE_X * THREAD_GROUP_SIZE_Y)

static const uint2 s_ThreadGroupSize =  uint2(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y);

// Kernel config
#define KERNEL_SIZE             5
#define KERNEL_RANGE_MIN        (-KERNEL_SIZE / 2)
#define KERNEL_RANGE_MAX        (KERNEL_SIZE / 2)

static const float s_InvKernelSize =    1.0f / (KERNEL_SIZE * KERNEL_SIZE);

// Shared memory config
DEFINE_LDS_CONFIG(s_SM, KERNEL_SIZE);
DECLARE_LDS_ARRAY_2D(half4, g_RawColor, KERNEL_SIZE);
DECLARE_LDS_ARRAY_2D(half4, g_DenoisedColor, KERNEL_SIZE);

// Feature Flags
#define FLAGS_RAW_SOURCE_BLIT           (1 << 0)
#define FLAGS_SCALE_SRC                 (1 << 1)
#define FLAGS_DIFFUSE_SIGNAL_INDIRECT   (1 << 2)

// Debug Flags
#define FLAGS_DEBUG                     (1 << 16)
#define FLAGS_DEBUG_MODE_MASK           (0xFF << 16)

#define FLAGS_DEBUG_CORRELATION_BIAS    (1 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_SKIP_SIGNAL         (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DENOISER_OUTPUT     (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_SPECULAR_COLOR      (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DIRECT_DIFFUSE      (5 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_INDIRECT_DIFFUSE    (6 << 17 | FLAGS_DEBUG)

Texture2D<half4> InIndirectSpecular : register(t0);
Texture2D<half4> InSpecularAlbedo : register(t1);
Texture2D<half4> InDirectDiffuse : register(t2);
Texture2D<half4> InDiffuseAlbedo : register(t3);

// Secondary buffers
Texture2D<half4> InSkipSignal : register(t4);
Texture2D<half4> InRawColor : register(t5);
Texture2D<half4> InColorBeforeParticles : register(t6);

RWTexture2D<half4> OutColor : register(u0);

SamplerState LinearSampler : register(s0);

cbuffer CB_Comp : register(b0)
{
    float4 DstTexSize;
    
    float CorrelationBias;
    uint Flags;
    
    float2 _Padding;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return (Flags & FLAGS_DEBUG_MODE_MASK); }

// Correlates raw noisy input with denoised color using a modified SSIM.
half GetRawColorSimilarity(const uint2 gtID)
{
    const int2 smCenter = gtID + s_SM_HaloOffset;    
    float meanD = 0.0f;
    float meanR = 0.0f;
    float meanDD = 0.0f; // D^2
    float meanRR = 0.0f; // R^2
    float meanRD = 0.0f; // R*D

    static const float s_RcpSigma = 1.0f / 1.2f;
    float totalWeight = 0.0f;
    
    [unroll]
    for (int x1 = KERNEL_RANGE_MIN; x1 <= KERNEL_RANGE_MAX; x1++)
    {
        [unroll]
        for (int y1 = KERNEL_RANGE_MIN; y1 <= KERNEL_RANGE_MAX; y1++)
        {
            const int2 smID = smCenter + int2(x1, y1);
            float w = exp(-(Square(x1) + Square(y1)) * s_RcpSigma); // This is precomputed by DXC
            totalWeight += w;
            
            const float lumD = g_DenoisedColor[smID.x][smID.y].a;
            meanD += w * lumD;
            meanDD += w * Square(lumD);
  
            const float lumR = g_RawColor[smID.x][smID.y].a;
            meanR += w * lumR;
            meanRR += w * Square(lumR);
            meanRD += w * lumR * lumD;
        }
    }
    
    const float rcpTotalWeight = rcp(totalWeight);   
    meanD *= rcpTotalWeight;
    meanR *= rcpTotalWeight;
    meanDD *= rcpTotalWeight;
    meanRR *= rcpTotalWeight;
    meanRD *= rcpTotalWeight;
    
    const float meanDSq = Square(meanD);
    const float meanRSq = Square(meanR);
    
    // Variances (std.dev^2)
    // E[X^2] - (E[X])^2 - Average of squares, less the square of the average
    const float varD = max(meanDD - meanDSq, 0.0f);
    const float varR = max(meanRR - meanRSq, 2e-3f);
    
    // Std. Deviation
    const float devD = sqrt(varD);
    const float devR = sqrt(varR);
    
    // Covariance
    // E[X*Y] - E[X]E[Y] - Average of R*D product, less product of their averages
    const float covRD = meanRD - (meanD * meanR);
        
    // Correlation
    static const float s_SSIMRelaxation = 0.1f;
    static const float s_COVThreshold = 0.2f;
    
    static const float c1 = Square(1e-2f * s_SSIMRelaxation) + 0.1f;
    static const float c2 = Square(3e-2f * s_SSIMRelaxation);
    static const float c3 = 1.0f * c2;
    
    // Standard SSIM components
    const float strucCorrelation = ((covRD + c3) * rcp(devD * devR + c3));
    const float conCorrelation = (2.0f * devD * devR + c2) * rcp(varD + varR + c2);
    const float lumCorrelation = (2.0f * meanD * meanR) * rcp(meanDSq + meanRSq + c1);
    const half ssim = half(strucCorrelation * conCorrelation * lumCorrelation);
    
    // Variance gating. The denoiser doesn't destroy genuine detail. It might attenuate details, or even
    // hallucinate, but if it says it's flat, then almost certainly flat.
    const half covD = half(devD * rcp(max(meanD, 1e-2f)));
    const half similarity = half(smoothstep(0.0f, 0.5f, ssim) * smoothstep(0.0f, s_COVThreshold, covD));
    
    return min(max(similarity, 0.0h), 1.0h);
}

void PopulateSharedMemory(const uint2 groupID, const int2 gtID)
{
    const int2 pxOrigin = groupID.xy * s_ThreadGroupSize - s_SM_HaloOffset;
    const uint flatID = gtID.x + gtID.y * s_ThreadGroupSize.x;
    const int2 maxBounds = int2(DstTexSize.xy) - 1;

    [unroll]
    for (int i = 0; i < s_SM_LoadsPerThread; i++)
    {
        const uint smFlatID = flatID + i * NUM_THREADS;
        
        if (smFlatID < s_SM_ElementCount)
        {
            const int2 smID = int2(smFlatID % s_SM_Size.x, smFlatID / s_SM_Size.x);
            const int2 px = clamp(pxOrigin + smID, int2(0, 0), maxBounds);
            const float3 denoisedSpecColor = InIndirectSpecular[px].rgb;
            const float3 denoisedDiffColor = InDirectDiffuse[px].rgb;
            const float3 specReflectance = InSpecularAlbedo[px].rgb;
            const float3 diffAlbedo = InDiffuseAlbedo[px].rgb;
            const half3 totalAlbedo = GetSafeFP16(specReflectance + diffAlbedo);
            half3 denoisedColor = GetSafeFP16((denoisedSpecColor * specReflectance) +
                                              (denoisedDiffColor * diffAlbedo));
            
            const half3 rawColor = GetSafeFP16(InRawColor[px].rgb);
            const half4 skipColor = GetSafeFP16(InSkipSignal[px]);
            const half skipLuma = skipColor.a;
            
            // Use demodulated color for luma references, but use remodulated color for output colors.
            const float rcpTotalAlbedo = rcp(max(GetLuminance(totalAlbedo), 1e-2f));
            const half rawRef = GetSafeFP16(GetLuminance(rawColor) * rcpTotalAlbedo);
            const half denoisedRef = GetSafeFP16((GetLuminance(denoisedColor) + skipColor.a) * rcpTotalAlbedo);
            denoisedColor += skipColor.rgb;

            g_RawColor[smID.x][smID.y] = half4(rawColor, rawRef);
            g_DenoisedColor[smID.x][smID.y] = half4(denoisedColor, denoisedRef);
        }
    }
    
    GroupMemoryBarrierWithGroupSync();
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const uint2 px = groupID.xy * s_ThreadGroupSize + gtID.xy;
    const float2 uv = (float2(px) + 0.5f) * DstTexSize.zw;
    
    if (px.x >= DstTexSize.x || px.y >= DstTexSize.y)
    {
        OutColor[px] = 0.0f;
        return;
    }
    
    [branch]
    if (IsSet(FLAGS_RAW_SOURCE_BLIT))
    {
        [branch]
        if (IsSet(FLAGS_SCALE_SRC))
            OutColor[px] = InIndirectSpecular.SampleLevel(LinearSampler, uv, 0);
        else
            OutColor[px] = InIndirectSpecular[px];
    }
    else
    {
        const int2 smID = gtID.xy + s_SM_HaloOffset;      
        PopulateSharedMemory(groupID.xy, gtID.xy);

        // Correlate raw RT input with denoiser output
        const half rawWeight = GetRawColorSimilarity(gtID.xy) * CorrelationBias;
        
        [branch]
        if (IsSet(FLAGS_DEBUG))
        {
            switch (GetDebugMode())
            {
                case FLAGS_DEBUG_CORRELATION_BIAS:
                    OutColor[px] = half4(TurboColormap(rawWeight), 1.0f);
                    break;
                case FLAGS_DEBUG_SKIP_SIGNAL:
                    OutColor[px] = half4(InSkipSignal[px].rgb, 1.0f);
                    break;
                case FLAGS_DEBUG_SPECULAR_COLOR:
                    OutColor[px] = half4(InIndirectSpecular[px].rgb * InSpecularAlbedo[px].rgb, 1.0f);
                    break;
                case FLAGS_DEBUG_DIRECT_DIFFUSE:
                    OutColor[px] = IsSet(FLAGS_DIFFUSE_SIGNAL_INDIRECT)
                        ? half4(1.0f, 0.0f, 1.0f, 1.0f)
                        : half4(InDirectDiffuse[px].rgb * InDiffuseAlbedo[px].rgb, 1.0f);
                    break;
                case FLAGS_DEBUG_INDIRECT_DIFFUSE:
                    OutColor[px] = IsSet(FLAGS_DIFFUSE_SIGNAL_INDIRECT)
                        ? half4(InDirectDiffuse[px].rgb * InDiffuseAlbedo[px].rgb, 1.0f)
                        : half4(1.0f, 0.0f, 1.0f, 1.0f);
                    break;
                default:
                    OutColor[px] = half4(InIndirectSpecular[px].rgb + InDirectDiffuse[px].rgb, 1.0f);
                    break;
            }    
        }
        else
        {
            const half4 denoisedColor = g_DenoisedColor[smID.x][smID.y];
            const half4 rawColor = g_RawColor[smID.x][smID.y];
            half3 outColor = GetSafeFP16(lerp(denoisedColor.rgb, rawColor.rgb, rawWeight));
            
            // Clamp final color within +/- 50% of the denoiser output. The SSIM metric generally stays well 
            // clear if this threshold, but not always.
            const half3 minColor = 0.5f * denoisedColor.rgb;
            const half3 maxColor = 1.5f * denoisedColor.rgb;
            outColor.rgb = clamp(outColor.rgb, minColor, maxColor);
            
            // Optional discrete premultiplied alpha buffer
            half4 particles = GetSafeFP16(InColorBeforeParticles[px]);
            particles.a = saturate(particles.a);
            outColor = (1.0f - particles.a) * outColor + particles.rgb;
            
            OutColor[px] = (half4)GetSafeFP16(float4(outColor, 1.0f));
        }
    }
}
