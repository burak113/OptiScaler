#include "FSRDPreprocessCommon.hlsli"

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

// Dispatch config
#define THREAD_GROUP_SIZE_X     8
#define THREAD_GROUP_SIZE_Y     8
#define NUM_THREADS             (THREAD_GROUP_SIZE_X * THREAD_GROUP_SIZE_Y)

static const uint2 s_ThreadGroupSize = uint2(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y);

// Kernel config
#define SSIM_KERNEL_SIZE        5
#define SSIM_RANGE_MIN          (-SSIM_KERNEL_SIZE / 2)
#define SSIM_RANGE_MAX          (SSIM_KERNEL_SIZE / 2)

static const float s_InvKernelSize = 1.0f / (SSIM_KERNEL_SIZE * SSIM_KERNEL_SIZE);

// Shared memory config
#define SHARED_HALO_SIZE        (SSIM_KERNEL_SIZE / 2)
#define SHARED_DIM_X            (THREAD_GROUP_SIZE_X + 2 * SHARED_HALO_SIZE)
#define SHARED_DIM_Y            (THREAD_GROUP_SIZE_Y + 2 * SHARED_HALO_SIZE)
#define NUM_SHARED_ELEMENTS     (SHARED_DIM_X * SHARED_DIM_Y)

static const uint2 s_SMHaloOffset = uint2(SHARED_HALO_SIZE, SHARED_HALO_SIZE);
static const uint2 s_SMSize = uint2(SHARED_DIM_X, SHARED_DIM_Y);
static const uint s_SMLoadsPerThread = (NUM_SHARED_ELEMENTS + NUM_THREADS - 1) / NUM_THREADS;

groupshared half g_DenoisedDemodLuma[SHARED_DIM_X][SHARED_DIM_Y];
groupshared half g_DemodLuma[SHARED_DIM_X][SHARED_DIM_Y];
groupshared half g_RawLuma[SHARED_DIM_X][SHARED_DIM_Y];

// Feature Flags
#define FLAGS_RAW_SOURCE_BLIT           (1 << 0)
#define FLAGS_SCALE_SRC                 (1 << 1)

// Debug Flags
#define FLAGS_DEBUG                     (1 << 16)
#define FLAGS_DEBUG_MODE_MASK           (0xFF << 16)
#define FLAGS_DEBUG_CORRELATION_BIAS    (1 << 17 | FLAGS_DEBUG)

Texture2D<half4> InDenoisedColor : register(t0); // Denoiser output
Texture2D<half4> InDemodulatedColor : register(t1); // Denoiser input
Texture2D<half4> InFusedModulator : register(t2);
Texture2D<half3> InColorBeforeParticles : register(t3);
Texture2D<half4> InSkipSignal : register(t4);

RWTexture2D<half4> OutColor : register(u0);

SamplerState LinearSampler : register(s0);

cbuffer CB_Comp : register(b0)
{
    float4 DstTexSize;
    
    float CorrelationBias;
    uint Flags;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return (Flags & FLAGS_DEBUG_MODE_MASK); }

// Calculates normalized SNR for the original raw input, compressed into [0, 1]
float CalculateRawSNR(const uint2 gtID)
{
    const int2 center = gtID + s_SMHaloOffset;
    float sum = 0.0f;
    float sumSq = 0.0f;
    
    for (int x1 = SSIM_RANGE_MIN; x1 <= SSIM_RANGE_MAX; x1++)
    {
        for (int y1 = SSIM_RANGE_MIN; y1 <= SSIM_RANGE_MAX; y1++)
        {
            const int2 idx = center + int2(x1, y1);
            const float lum = g_RawLuma[idx.x][idx.y];
                
            sum += lum;
            sumSq += Square(lum);
        }
    }
    
    const float mean = sum * s_InvKernelSize;
    const float meanSq = sumSq * s_InvKernelSize;
    const float var = max(meanSq - Square(mean), 0.0f);
    const float snr = (mean) * rcp(mean + sqrt(var) + 1e-5f);
    
    return snr;
}

// Correlates raw noisy input with denoised color, using a modified SSIM.
void CorrelateDemodulatedColor(const uint2 gtID, out float strucCorrelation, out float conCorrelation, out float lumCorrelation)
{
    const int2 smCenter = gtID + s_SMHaloOffset;
    const float denoisedCenter = g_DenoisedDemodLuma[smCenter.x][smCenter.y]; // D       
    const float rawCenter = g_DemodLuma[smCenter.x][smCenter.y]; // R    
    
    float rawLuma = rawCenter;
    float sumD = denoisedCenter;
    float sumR = rawLuma;
    float sumDD = Square(denoisedCenter); // D^2
    float sumRR = Square(rawLuma); // R^2
    float sumRD = rawLuma * denoisedCenter; // R*D
    float minD = 1e7f;
    float maxD = 1e-7f;
    
    for (int x1 = SSIM_RANGE_MIN; x1 <= SSIM_RANGE_MAX; x1++)
    {
        for (int y1 = SSIM_RANGE_MIN; y1 <= SSIM_RANGE_MAX; y1++)
        {
            if (x1 != 0 || y1 != 0)
            {
                const int2 smID = smCenter + int2(x1, y1);
                const float lum = g_DenoisedDemodLuma[smID.x][smID.y];
                
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
    
    for (int x2 = SSIM_RANGE_MIN; x2 <= SSIM_RANGE_MAX; x2++)
    {
        for (int y2 = SSIM_RANGE_MIN; y2 <= SSIM_RANGE_MAX; y2++)
        {
            if (x2 != 0 || y2 != 0)
            {
                const int2 smID = smCenter + int2(x2, y2);
                const float lum = g_DemodLuma[smID.x][smID.y];
                
                rawLuma = lum;
                rawLuma = rawCenter + lumRange * tanh((rawLuma - rawCenter) * rcpLumRange);
                
                sumR += rawLuma;
                sumRR += Square(rawLuma);
                sumRD += rawLuma * g_DenoisedDemodLuma[smID.x][smID.y];
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
    const int2 pxOrigin = groupID.xy * s_ThreadGroupSize - s_SMHaloOffset;
    const uint flatID = gtID.x + gtID.y * s_ThreadGroupSize.x;
    const int2 maxBounds = int2(DstTexSize.xy) - 1;

    for (int i = 0; i < s_SMLoadsPerThread; i++)
    {
        const uint smFlatID = flatID + i * NUM_THREADS;
        
        if (smFlatID < NUM_SHARED_ELEMENTS)
        {
            const int2 smID = int2(smFlatID % s_SMSize.x, smFlatID / s_SMSize.x);
            int2 px = pxOrigin + smID;
            px = clamp(px, int2(0, 0), maxBounds);
            
            const float3 remod = InFusedModulator[px].rgb;
            const float3 rawDemodColor = InDemodulatedColor[px].rgb;
            
            g_DenoisedDemodLuma[smID.x][smID.y] = (half) dot(InDenoisedColor[px].rgb, 0.33f);
            g_DemodLuma[smID.x][smID.y] = (half) dot(rawDemodColor, 0.33f);
            g_RawLuma[smID.x][smID.y] = (half) dot(rawDemodColor * remod, 0.33f);
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
            OutColor[px] = InDenoisedColor.SampleLevel(LinearSampler, uv, 0);
        else
            OutColor[px] = InDenoisedColor[px];
    }
    else
    {
        PopulateSharedMemory(groupID.xy, gtID.xy);

        // Correlate raw RT input with denoiser output
        float strucCorrelation, conCorrelation, lumCorrelation;    
        CorrelateDemodulatedColor(gtID.xy, strucCorrelation, conCorrelation, lumCorrelation);
        
        float lowConfWeight = strucCorrelation * conCorrelation * lumCorrelation;
        lowConfWeight *= CorrelationBias;
        
        [branch]
        if (IsSet(FLAGS_DEBUG_CORRELATION_BIAS))
        {
            OutColor[px] = half4(TurboColormap(lowConfWeight), 1.0f);
        }
        else
        {
            const float3 remod = InFusedModulator[px].rgb;
            const float3 denoisedColor = InDenoisedColor[px].rgb * remod;
            const float4 skip = InSkipSignal[px];
            const float3 particles = InColorBeforeParticles[px]; // Not quite right
            const float skipWeight = saturate(lowConfWeight + skip.a);
            const float3 outColor = lerp(denoisedColor, skip.rgb, skipWeight);
                
            OutColor[px] = (half4)GetSafeFP16(float4(outColor + particles.rgb, 1.0f));
        }
    }
}