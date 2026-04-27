#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 2), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 2), visibility = SHADER_VISIBILITY_ALL), " \
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

// Flags
#define FLAGS_UPSCALE           (1 << 0)

Texture2D<half4> InColor : register(t0);
Texture2D<half> InEdgeGuide : register(t1);

RWTexture2D<half4> OutColor : register(u0);
RWTexture2D<half> OutEdgeGuide : register(u1);

SamplerState LinearSampler : register(s0);

cbuffer CB_Analysis : register(b0)
{
    float4 SrcTexSize;
    float4 DstTexSize;

    uint Flags;
    
    float3 _Padding;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

static const float2 UpsampleOffsets[4] =
{
    float2(-1.0f, -1.0f), float2(1.0f, -1.0f),
    float2(-1.0f, 1.0f), float2(1.0f, 1.0f)
};

static const float2 DownsampleOffsets[5] =
{
    float2(0, 0),
    float2(-0.5f, -0.5f), float2(0.5f, -0.5f),
    float2(-0.5f, 0.5f), float2(0.5f, 0.5f)
};

static const float s_CrossBiweightScale = 0.3f;
static const float s_HaloSupressionScale = 0.5f;

static const float s_CrossBlNorm = 1.0f / s_CrossBiweightScale;
static const float s_HaloBlNorm = 1.0f / s_HaloSupressionScale;

float GetRangeWeight(const float delta, const float scale)
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
        
    // Modified Dual Kawase filter with cross bilateral edge stopping.
    //
    // When downsampling DstTexSize.xy = 0.5f * SrcTexSize.xy and DstTexSize.zw = 2.0f * SrcTexSize.zw
    // When upsampling DstTexSize.xy = 2.0f * SrcTexSize.xy and DstTexSize.zw = 0.5f * SrcTexSize.zw    
    float4 mean = 0.0f;
    float totalWeight = 0.0f;
    
    [branch]
    if (IsSet(FLAGS_UPSCALE))
    {
        const float2 uv = (float2(px)) * DstTexSize.zw;
        const float guideCenter = InEdgeGuide.SampleLevel(LinearSampler, uv, 0.0f).r;
        const float lumCenter = GetLuminance(InColor.SampleLevel(LinearSampler, uv, 0.0f).rgb);

        [unroll]
        for (int i = 0; i < 4; i++)
        {
            // SrcTexSize.zw = 2.0f * DstTexSize.zw
            const float2 offset = UpsampleOffsets[i] * DstTexSize.zw;
            const float2 tapUV = clamp(uv + offset, 0.0f, 1.0f);
            
            const float guideCurrent = InEdgeGuide.SampleLevel(LinearSampler, tapUV, 0.0f);
            float rangeWeight = GetRangeWeight(guideCenter - guideCurrent, s_CrossBlNorm);
            
            const float4 color = InColor.SampleLevel(LinearSampler, tapUV, 0.0f);
            const float lumCurrent = GetLuminance(color.rgb);
            float lumDelta = lumCenter - lumCurrent;
            lumDelta = max(0.1f * lumDelta, -lumDelta);
            
            const float lumWeight = GetRangeWeight(lumDelta, s_HaloBlNorm);
            rangeWeight *= lumWeight;
            
            mean += rangeWeight * color;
            totalWeight += rangeWeight;
        }
    }
    else
    {        
        const float2 uv = (float2(px) + 0.5f) * DstTexSize.zw;
        const float lumCenter = GetLuminance(InColor.SampleLevel(LinearSampler, uv, 0.0f).rgb);
        const float guideCenter = InEdgeGuide.SampleLevel(LinearSampler, uv, 0.0f).r;
        
        [unroll]
        for (int i = 0; i < 5; i++)
        {
            // SrcTexelSize.zw = 0.5f * DstTexelSize.zw
            const float2 offset = DownsampleOffsets[i] * DstTexSize.zw;
            const float2 tapUV = clamp(uv + offset, 0.0f, 1.0f);
            const float4 color = InColor.SampleLevel(LinearSampler, tapUV, 0.0f);
            const float lumCurrent = GetLuminance(color.rgb);
            const float guideCurrent = InEdgeGuide.SampleLevel(LinearSampler, tapUV, 0.0f);
            
            const float crossDelta = guideCenter - guideCurrent;
            float rangeWeight = GetRangeWeight(crossDelta, s_CrossBlNorm);
            
            float lumDelta = lumCenter - lumCurrent;
            lumDelta = max(0.1f * lumDelta, -lumDelta);
            
            const float lumWeight = GetRangeWeight(lumDelta, s_HaloBlNorm);
            rangeWeight *= lumWeight;
            
            mean += rangeWeight * color;
            totalWeight += rangeWeight;
        }
        
        OutEdgeGuide[px] = guideCenter;
    }
    
    mean *= rcp(totalWeight);
    OutColor[px] = GetSafeFP16(mean);
}