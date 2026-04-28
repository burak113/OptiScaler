#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2), visibility = SHADER_VISIBILITY_ALL), " \
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
static const float s_RcpCrossBlNorm = 1.0f / 0.2f;
static const float s_RcpSelfBlNorm = 1.0f / 0.5f;

Texture2D<half4> InColor : register(t0);
Texture2D<half> InEdgeGuide : register(t1);

RWTexture2D<half4> OutColor : register(u0);

SamplerState LinearSampler : register(s0);

cbuffer CB_Analysis : register(b0)
{
    float4 DstTexSize;

    int StepSize;
    uint Flags;   
    
    float2 _Padding;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

static const float s_Kernel1D[3] = { .375f, 0.25f, 0.0625f };

float GetSpatialWeight(int x, int y)
{
    return s_Kernel1D[abs(x)] * s_Kernel1D[abs(y)];
}

float GetRangeWeight(float delta, float scale)
{
    return Square(max(1.0f - Square(delta * scale), 1e-2f));
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const int2 px = groupID.xy * s_ThreadGroupSize + gtID.xy;
    
    if (px.x >= DstTexSize.x || px.y >= DstTexSize.y)
    {
        OutColor[px] = float4(0, 0, 0, 0);
        return;
    }
        
    const float4 centerColor = InColor[px];
    const float centerGuide = InEdgeGuide[px];
    const float centerLum = GetLuminance(centerColor.rgb);
    const int2 maxBounds = int2(DstTexSize.xy) - 1;

    float4 mean = 0;
    float totalWeight = 0;

    [unroll]
    for (int y = -2; y <= 2; y++)
    {
        [unroll]
        for (int x = -2; x <= 2; x++)
        {
            const int2 tapPX = clamp(px + StepSize * int2(x, y), 0, maxBounds);

            const float4 color = InColor[tapPX];
            const float guide = InEdgeGuide[tapPX];
            const float lum = GetLuminance(color.rgb);

            float lumDelta = centerLum - lum;
            lumDelta = max(0.1f * lumDelta, -lumDelta);

            const float wSpatial = GetSpatialWeight(x, y);
            const float wGuide = GetRangeWeight(centerGuide - guide, s_RcpCrossBlNorm);
            const float wLum = GetRangeWeight(lumDelta, s_RcpSelfBlNorm);
            const float w = wSpatial * min(wGuide, wLum);

            mean += w * color;
            totalWeight += w;
        }
    }

    OutColor[px] = GetSafeFP16(mean * rcp(max(totalWeight, .15f)));
}