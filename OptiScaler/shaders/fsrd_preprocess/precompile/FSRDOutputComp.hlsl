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
#define FLAGS_MODE_2_SIGNAL             (1 << 2)

// Debug Flags
#define FLAGS_DEBUG                     (1 << 16)
#define FLAGS_DEBUG_MODE_MASK           (0xFF << 16)

#define FLAGS_DEBUG_CORRELATION_BIAS    (1 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_SKIP_SIGNAL         (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DENOISER_OUTPUT     (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_SPECULAR_COLOR      (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DIFFUSE_COLOR       (5 << 17 | FLAGS_DEBUG)

// Mode 1/2 Signal
Texture2D<half4> InDenoisedSignal1 : register(t0); // Fused or specular denoiser output
Texture2D<half4> InAlbedo1 : register(t1); // Fused or specular albedo

// Mode 2 Signal
Texture2D<half4> InDenoisedSignal2 : register(t2); // Diffuse denoiser output
Texture2D<half4> InAlbedo2 : register(t3); // Diffuse albedo

// Secondary buffers
Texture2D<half4> InSkipSignal : register(t4);
Texture2D<half3> InRawColor : register(t5);
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
float GetRawColorSimilarity(const uint2 gtID)
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
            float w = exp(-(Square(x1) + Square(y1)) * s_RcpSigma);
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
    static const float s_SSIMStrictness = 1.0f;
    static const float s_COVThreshold = 0.2f;
    
    const float c1 = Square(1e-2f * s_SSIMStrictness);
    const float c2 = Square(3e-2f * s_SSIMStrictness);
    const float c3 = 1.0f * c2;
    
    // Standard SSIM components
    const float strucCorrelation = ((covRD + c3) * rcp(devD * devR + c3));
    const float conCorrelation = ((2.0f * devD * devR + c2) * rcp(varD + varR + c2));
    const float lumCorrelation = (2.0f * meanD * meanR) * rcp(meanDSq + meanRSq + c1);    
    const float ssim = strucCorrelation * conCorrelation * lumCorrelation;  
    
    // Variance gating. The denoiser doesn't destroy genuine detail. It might attenuate details, or even
    // hallucinate, but if it says it's flat, then almost certainly flat.
    const float covD = devD * rcp(max(meanD, 1e-2f));
    
    return smoothstep(0.0f, 0.5f, ssim) * smoothstep(0.0f, s_COVThreshold, covD);
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
            float3 denoisedColor;
            float3 totalAlbedo;
            
            [branch]
            if (IsSet(FLAGS_MODE_2_SIGNAL))
            {
                const float3 denoisedSpecColor = InDenoisedSignal1[px].rgb;
                const float3 denoisedDiffColor = InDenoisedSignal2[px].rgb;
                const float3 specReflectance = InAlbedo1[px].rgb;
                const float3 diffAlbedo = InAlbedo2[px].rgb;
                
                totalAlbedo = specReflectance + diffAlbedo;
                denoisedColor = (denoisedSpecColor * specReflectance) + (denoisedDiffColor * diffAlbedo);
            }
            else
            {
                totalAlbedo = InAlbedo1[px].rgb;
                denoisedColor = InDenoisedSignal1[px].rgb * totalAlbedo;
            }
            
            denoisedColor += InSkipSignal[px].rgb;
            const float3 rawColor = InRawColor[px];

            // Use demodulated color for luma references, but use modulated color for RGB
            const float3 rcpTotalAlbedo = rcp(max(totalAlbedo, 1e-3f));
            const float rawRef = GetLuminance(rawColor * rcpTotalAlbedo);
            const float denoisedRef = GetLuminance(denoisedColor * rcpTotalAlbedo);
                        
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
            OutColor[px] = InDenoisedSignal1.SampleLevel(LinearSampler, uv, 0);
        else
            OutColor[px] = InDenoisedSignal1[px];
    }
    else
    {
        const int2 smID = gtID.xy + s_SM_HaloOffset;      
        PopulateSharedMemory(groupID.xy, gtID.xy);

        // Correlate raw RT input with denoiser output
        float lowConfWeight = GetRawColorSimilarity(gtID.xy) * CorrelationBias;
                
        [branch]
        if (IsSet(FLAGS_DEBUG))
        {
            switch (GetDebugMode())
            {
                case FLAGS_DEBUG_CORRELATION_BIAS:
                    OutColor[px] = half4(TurboColormap(lowConfWeight), 1.0f);
                    break;
                case FLAGS_DEBUG_SKIP_SIGNAL:
                    OutColor[px] = half4(InSkipSignal[px].rgb, 1.0f);
                    break;
                case FLAGS_DEBUG_SPECULAR_COLOR:
                    OutColor[px] = half4(InDenoisedSignal1[px].rgb * InAlbedo1[px].rgb, 1.0f);
                    break;
                case FLAGS_DEBUG_DIFFUSE_COLOR:
                    OutColor[px] = half4(InDenoisedSignal2[px].rgb * InAlbedo2[px].rgb, 1.0f);
                    break;
                default:
                    if (IsSet(FLAGS_MODE_2_SIGNAL))
                        OutColor[px] = half4(InDenoisedSignal1[px].rgb + InDenoisedSignal2[px].rgb, 1.0f);
                    else
                        OutColor[px] = half4(InDenoisedSignal1[px].rgb, 1.0f);
                
                    break;
            }    
        }
        else
        {
            const half4 denoisedColor = g_DenoisedColor[smID.x][smID.y];
            const half4 rawColor = g_RawColor[smID.x][smID.y];
            const half4 particles = InColorBeforeParticles[px]; // TODO

            const half3 outColor = half3(lerp(denoisedColor.rgb, rawColor.rgb, lowConfWeight));

            OutColor[px] = (half4)GetSafeFP16(float4(outColor, 1.0f));
        }
    }
}