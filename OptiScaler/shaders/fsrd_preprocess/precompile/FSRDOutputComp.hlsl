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
#define KERNEL_SIZE        5
#define KERNEL_RANGE_MIN          (-KERNEL_SIZE / 2)
#define KERNEL_RANGE_MAX          (KERNEL_SIZE / 2)

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

// Correlates raw noisy input with denoised color, using a modified SSIM.
void CorrelateDemodulatedColor(const uint2 gtID, out float strucCorrelation, out float conCorrelation, out float lumCorrelation)
{
    const int2 smCenter = gtID + s_SM_HaloOffset;
    const float denoisedCenter = g_DenoisedColor[smCenter.x][smCenter.y].a; // D       
    const float rawCenter = g_RawColor[smCenter.x][smCenter.y].a; // R    
    
    float rawLuma = rawCenter;
    float sumD = denoisedCenter;
    float sumR = rawLuma;
    float sumDD = Square(denoisedCenter); // D^2
    float sumRR = Square(rawLuma); // R^2
    float sumRD = rawLuma * denoisedCenter; // R*D
    float minD = 1e7f;
    float maxD = 1e-7f;
    
    for (int x1 = KERNEL_RANGE_MIN; x1 <= KERNEL_RANGE_MAX; x1++)
    {
        for (int y1 = KERNEL_RANGE_MIN; y1 <= KERNEL_RANGE_MAX; y1++)
        {
            if (x1 != 0 || y1 != 0)
            {
                const int2 smID = smCenter + int2(x1, y1);
                const float lum = g_DenoisedColor[smID.x][smID.y].a;
                
                sumD += lum;
                sumDD += Square(lum);
                minD = min(minD, lum);
                maxD = max(maxD, lum);
            }
        }
    }
    
    // Neighborhood around raw input is clamped to prevent neighbors from dominating
    // too much if they're noisy/sparse.
    const float lumRange = 5.0f * max(maxD - minD, 0.1f);
    const float rcpLumRange = rcp(lumRange);
    const float lumRangeMin = rawCenter - 0.5f * lumRange;
    const float lumRangeMax = rawCenter + 0.5f * lumRange;
    
    for (int x2 = KERNEL_RANGE_MIN; x2 <= KERNEL_RANGE_MAX; x2++)
    {
        for (int y2 = KERNEL_RANGE_MIN; y2 <= KERNEL_RANGE_MAX; y2++)
        {
            if (x2 != 0 || y2 != 0)
            {
                const int2 smID = smCenter + int2(x2, y2);
                const float lum = g_RawColor[smID.x][smID.y].a;
                
                rawLuma = lum;
                rawLuma = rawCenter + lumRange * tanh((rawLuma - rawCenter) * rcpLumRange);
                
                sumR += rawLuma;
                sumRR += Square(rawLuma);
                sumRD += rawLuma * g_DenoisedColor[smID.x][smID.y].a;
            }
        }
    }

    const float avgD = sumD * s_InvKernelSize;
    const float avgR = sumR * s_InvKernelSize;
    const float avgDSq = Square(avgD);
    const float avgRSq = Square(avgR);
    
    // Variances (std.dev^2)
    // E[X^2] - (E[X])^2 - Average of squares, less the square of the average
    const float varD = max((sumDD * s_InvKernelSize) - avgDSq, 0.0f);
    const float varR = max((sumRR * s_InvKernelSize) - avgRSq, 2e-3f);
    
    // Std. Deviation
    const float devD = sqrt(varD);
    const float devR = sqrt(varR);
    
    // Covariance
    // E[X*Y] - E[X]E[Y] - Average of R*D product, less product of their averages
    const float covRD = (sumRD * s_InvKernelSize) - (avgD * avgR);
        
    // Correlation
    const float relaxation = 1.0f;
    const float c1 = Square(1e-2f * relaxation);
    const float c2 = Square(3e-2f * relaxation);
    const float c3 = 1.0f * c2;
    
    // Standard SSIM components
    strucCorrelation = ((covRD + c3) * rcp(devD * devR + c3));
    conCorrelation = ((2.0f * devD * devR + c2) * rcp(varD + varR + c2));
    lumCorrelation = (2.0f * avgD * avgR) * rcp(avgDSq + avgRSq + c1);
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
            
            const float3 skipColor = InSkipSignal[px].rgb;
            denoisedColor += skipColor;
            const float denoisedLuma = GetLuminance(denoisedColor);

            // Constrain raw color to denosied chroma
            const float rawLuma = GetLuminance(InRawColor[px]);
            const float rawScale = rawLuma * rcp(max(denoisedLuma, 1e-2f));
            const float3 rawColor = rawScale * denoisedColor;

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
        float strucCorrelation, conCorrelation, lumCorrelation;    
        CorrelateDemodulatedColor(gtID.xy, strucCorrelation, conCorrelation, lumCorrelation);
        
        float lowConfWeight = strucCorrelation * conCorrelation * lumCorrelation;
        lowConfWeight = saturate(CorrelationBias * lowConfWeight);
                
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
            const half3 denoisedColor = g_DenoisedColor[smID.x][smID.y].rgb;
            const half3 rawColor = g_RawColor[smID.x][smID.y].rgb;
            const half4 particles = InColorBeforeParticles[px];
            
            const half3 outColor = half3(lerp(denoisedColor, rawColor, lowConfWeight));

            OutColor[px] = (half4)GetSafeFP16(float4(outColor, 1.0f));
        }
    }
}