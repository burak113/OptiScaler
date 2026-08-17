#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 3), visibility = SHADER_VISIBILITY_ALL), " \
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

// A-Trous kernel config
#define KERNEL_SIZE             3
#define KERNEL_RANGE_MIN        (-KERNEL_SIZE / 2)
#define KERNEL_RANGE_MAX        (KERNEL_SIZE / 2)

static const float s_Kernel1D[2] = { 0.44198f, 0.27901f };

Texture2D<half4> InColor : register(t0);
Texture2D<float> InLinearDepth : register(t1);
Texture2D<half2> InDepthGradient : register(t2);

RWTexture2D<half4> OutColor : register(u0);

SamplerState LinearSampler : register(s0);

cbuffer CB_Analysis : register(b0)
{
    float4 DstTexSize;

    float RcpCrossBlNorm;
    float RcpSelfBlNorm;
    
    int StepSize;
    uint FrameIndex;
    
    uint Flags;
    float3 _Padding;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

float GetSpatialWeight(int x, int y)
{
    return s_Kernel1D[abs(x)] * s_Kernel1D[abs(y)];
}

float GetRangeWeight(float delta, float scale)
{
    // W = ( 1 - ( (center - tap) * scale )^2 )^2
    // scale = 1 / norm
    return Square(max(1.0f - Square(delta * scale), 1e-2f));
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const int2 px = groupID.xy * s_ThreadGroupSize + gtID.xy;
    
    if (px.x >= DstTexSize.x || px.y >= DstTexSize.y)
        return;
    
    const float4 centerColor = InColor[px];    
    const float centerLum = GetLuminance(centerColor.rgb);
    const float rcpCenterLum = rcp(max(centerLum, 1e-1f));   
    
    const float centerDepth = InLinearDepth[px];
    const float2 centerDepthGrad = InDepthGradient[px];

    // As the scaling increases, bilateral weighting becomes stricter. As smoothness increases,
    // blur strength should decrease. Where smoothness remains low, the weights should allow
    // more blending.
    //
    // StepSize scaling keeps luma strictness consistent as the stride increases.
    const float smoothness = saturate(1.0f - 2.0f * centerColor.a);
    const float adaptiveScale = float(StepSize) * (1.0f + 2.0f * smoothness);
    const float selfNormScale = adaptiveScale * RcpSelfBlNorm;

    // Depth tolerance is deliberately stride-independent. The tap test below measures
    // distance from the center pixel's tangent plane, not raw depth difference, so the
    // first-order change across the tap offset is already predicted and a coplanar tap
    // scores the same residual at every stride.
    //
    // The old form wrote this as StepSize * ... * rcp(... * StepSize), which cancels to
    // the same value. That cancellation was never the defect: it is the correct
    // behaviour for a plane-relative test. The defect was that the plane term was
    // missing, so the outer passes compared a stride-16 depth difference against a
    // stride-1 tolerance and rejected nearly every tap on sloped geometry.
    const float depthNormScale =
        (1.0f + 2.0f * smoothness) * RcpCrossBlNorm * rcp(1.0f + abs(centerDepth));
    
    const int2 maxBounds = int2(DstTexSize.xy) - 1;
    float4 mean = 0;
    float totalWeight = 0;
    
    [unroll]
    for (int x = KERNEL_RANGE_MIN; x <= KERNEL_RANGE_MAX; x++)
    {
        [unroll]
        for (int y = KERNEL_RANGE_MIN; y <= KERNEL_RANGE_MAX; y++)
        {
            const bool isCenter = (x != 0 || y != 0);
            const int2 tapPX = clamp(px + (StepSize * int2(x, y)), 0, maxBounds);
            const float4 color = isCenter ? InColor[tapPX] : centerColor;
            const float lum = isCenter ? GetLuminance(color.rgb) : centerLum;

            // Bilateral luma weight            
            float lumDelta = (centerLum - lum) * rcpCenterLum;
            const float wLum = GetRangeWeight(lumDelta, selfNormScale);

            // Coplanarity weight. FloorSeed stores a per-pixel central difference of
            // view-space depth, so scaling it by the tap offset predicts the depth this
            // tap would carry if the surface were locally planar. Measuring the residual
            // against that plane is what makes this a coplanarity test rather than a
            // plain depth difference, and it is why the gradient is produced at all.
            // The offset comes from the clamped position so border taps stay honest.
            const float depth = InLinearDepth[tapPX];
            const float2 tapOffset = float2(tapPX - px);
            const float predictedDepth = centerDepth + dot(centerDepthGrad, tapOffset);
            const float depthDelta = depth - predictedDepth;
            const float wDepth = GetRangeWeight(depthDelta, depthNormScale);

            const float wSpatial = GetSpatialWeight(x, y);
            const float w = wSpatial * wDepth * wLum;

            mean += w * color;
            totalWeight += w;
        }
    }

    mean *= rcp(max(totalWeight, 1e-2f));

    OutColor[px] = GetSafeFP16(mean);
}
