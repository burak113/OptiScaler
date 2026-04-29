#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 4), visibility = SHADER_VISIBILITY_ALL), " \
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
#define FLAGS_LINEAR_DEPTH              (1 << 0)

// 5x5 Median filter config
#define SORT_KERNEL_SIZE       5
#define SORT_KERNEL_RANGE_MIN  (-SORT_KERNEL_SIZE / 2)
#define SORT_KERNEL_RANGE_MAX  (SORT_KERNEL_SIZE / 2)

DEFINE_LDS_CONFIG(s_SM_Med, SORT_KERNEL_SIZE);
DECLARE_LDS_ARRAY_2D(half4, g_Color, SORT_KERNEL_SIZE);

// 3x3 Depth gradient
#define DEPTH_KERNEL_SIZE       3
#define DEPTH_KERNEL_RANGE_MIN  (-DEPTH_KERNEL_SIZE / 2)
#define DEPTH_KERNEL_RANGE_MAX  (DEPTH_KERNEL_SIZE / 2)

DEFINE_LDS_CONFIG(s_SM_Depth, DEPTH_KERNEL_SIZE);
DECLARE_LDS_ARRAY_2D(float, g_Depth, DEPTH_KERNEL_SIZE);

Texture2D<half3> InColor : register(t0);
Texture2D<half3> InSpecAlbedo : register(t1);
Texture2D<half3> InDiffAlbedo : register(t2);
Texture2D<float> InDepth : register(t3);

RWTexture2D<half4> OutColor : register(u0);
RWTexture2D<half> OutEdgeGuide : register(u1);

SamplerState LinearSampler : register(s0);

cbuffer CB_Median : register(b0)
{
    float4x4 InvProjMatrix; // DLSSD ViewToClip^-1
    float4 RenderSize;
    
    float NearPlane;
    float FarPlane;
    uint Flags;
    
    float _Padding;
}

// Full sorting network for 25 values
static const uint kSortNetworkSize = 131;
static const uint2 SortNetwork[kSortNetworkSize] =
{
    uint2(0, 1), uint2(2, 3), uint2(4, 5), uint2(6, 7), uint2(8, 9), uint2(10, 11), uint2(12, 13), uint2(14, 15), uint2(16, 17), uint2(18, 19), uint2(20, 21), uint2(22, 23),
    uint2(0, 2), uint2(1, 3), uint2(4, 6), uint2(5, 7), uint2(8, 10), uint2(9, 11), uint2(12, 14), uint2(13, 15), uint2(16, 18), uint2(17, 19), uint2(20, 22), uint2(21, 24),
    uint2(0, 4), uint2(1, 5), uint2(2, 6), uint2(3, 7), uint2(8, 12), uint2(9, 13), uint2(10, 14), uint2(11, 15), uint2(16, 20), uint2(21, 22), uint2(23, 24),
    uint2(0, 8), uint2(1, 12), uint2(2, 10), uint2(3, 14), uint2(4, 9), uint2(5, 13), uint2(6, 11), uint2(7, 15), uint2(17, 22), uint2(18, 21), uint2(19, 24),
    uint2(1, 18), uint2(3, 9), uint2(5, 17), uint2(6, 20), uint2(7, 13), uint2(11, 14), uint2(12, 22), uint2(15, 24), uint2(21, 23),
    uint2(1, 16), uint2(3, 12), uint2(5, 21), uint2(6, 18), uint2(7, 11), uint2(10, 17), uint2(14, 23), uint2(19, 20),
    uint2(0, 1), uint2(2, 5), uint2(4, 16), uint2(6, 8), uint2(7, 18), uint2(9, 21), uint2(10, 14), uint2(11, 13), uint2(12, 19), uint2(15, 23), uint2(20, 22),
    uint2(1, 2), uint2(3, 5), uint2(4, 6), uint2(7, 9), uint2(8, 12), uint2(10, 16), uint2(11, 20), uint2(13, 22), uint2(14, 17), uint2(15, 18), uint2(19, 21),
    uint2(1, 4), uint2(2, 6), uint2(3, 7), uint2(5, 9), uint2(8, 10), uint2(11, 14), uint2(12, 16), uint2(13, 17), uint2(15, 19), uint2(18, 20), uint2(22, 23),
    uint2(2, 4), uint2(3, 8), uint2(5, 10), uint2(7, 12), uint2(9, 16), uint2(11, 15), uint2(13, 19), uint2(14, 21), uint2(17, 18), uint2(20, 22),
    uint2(3, 4), uint2(5, 8), uint2(6, 7), uint2(9, 12), uint2(10, 11), uint2(13, 16), uint2(14, 15), uint2(17, 19), uint2(18, 21),
    uint2(5, 6), uint2(7, 8), uint2(9, 10), uint2(11, 12), uint2(13, 14), uint2(15, 16), uint2(17, 18), uint2(20, 21),
    uint2(4, 5), uint2(6, 7), uint2(8, 9), uint2(10, 11), uint2(12, 13), uint2(14, 15), uint2(16, 17), uint2(18, 19)
};

bool IsSet(uint mask)
{
    return (Flags & mask) == mask;
}

int2 GetSortID(const half2 key, const int2 gtID)
{
    const int i = (int) key.y;
    const int offsetX = i / SORT_KERNEL_SIZE;
    const int offsetY = i % SORT_KERNEL_SIZE;
    return gtID + int2(offsetX, offsetY);
}

half4 GetStableColor(const uint2 groupID, const int2 gtID)
{
    half2 sortKeys[25];

    // Populate sorting keys: luminance in X, flat index (0-24) in Y
    [unroll]
    for (int i1 = 0; i1 < 25; i1++)
    {
        const int offsetX = i1 / SORT_KERNEL_SIZE;
        const int offsetY = i1 % SORT_KERNEL_SIZE;
        const int2 smID = gtID + int2(offsetX, offsetY);

        const half lum = g_Color[smID.x][smID.y].a;
        sortKeys[i1].x = lum;
        sortKeys[i1].y = (half) i1;
    }

    // Sorting network
    [unroll]
    for (int i2 = 0; i2 < kSortNetworkSize; i2++)
    {
        const uint2 pair = SortNetwork[i2];
        const half2 a = sortKeys[pair.x];
        const half2 b = sortKeys[pair.y];

        sortKeys[pair.x] = (a.x <= b.x) ? a : b;
        sortKeys[pair.y] = (a.x > b.x) ? a : b;
    }

    // Stable areas have a well behaved, flatter median. Noise and hard edges introduce
    // jump discontinuties in the distribution. If this value is low, then the median is 
    // well behaved and this area is probably flat or at least not unstable.
    const float medianSpread = abs(sortKeys[11].x - sortKeys[13].x) * rcp(sortKeys[12].x + 1e-2f);
    const float variance = saturate(10.0f * medianSpread);
    const float stability = 1.0f - variance;
    
    const int2 minID = GetSortID(sortKeys[0], gtID);   
    const half4 minColor = g_Color[minID.x][minID.y];
    
    return half4(minColor.rgb * stability, variance);
}

half GetDepthGradientStrength(const uint2 groupID, const int2 gtID)
{
    const int2 smID = gtID + s_SM_Depth_HaloOffset;
    
    float2 gradient = 0.0f;
    gradient.x = g_Depth[smID.x + 1][smID.y] - g_Depth[smID.x - 1][smID.y];
    gradient.y = g_Depth[smID.x][smID.y + 1] - g_Depth[smID.x][smID.y - 1];

    const float center = g_Depth[smID.x][smID.y];
    
    return half(saturate(length(gradient) * rcp(max(center, 0.1f))));
}

float3 GetViewSpacePos(const int2 px)
{
    const float inDepth = InDepth[px];
    const float2 uv = (float2(px) + 0.5) * RenderSize.zw;
    float3 viewSpacePos = 0.0f;
    
    [branch]
    if (IsSet(FLAGS_LINEAR_DEPTH))
    {
        viewSpacePos = InvProjectPosition(float3(uv, 1.0f), InvProjMatrix);
        viewSpacePos *= (inDepth / viewSpacePos.z);
    }
    else
    {
        viewSpacePos = InvProjectPosition(float3(uv, inDepth), InvProjMatrix);
    }
    
    viewSpacePos.z = clamp(abs(viewSpacePos.z), NearPlane, FarPlane);
    return viewSpacePos;
}

void PopulateSharedMemory(const uint2 groupID, const int2 gtID)
{
    const uint flatID = gtID.x + gtID.y * s_ThreadGroupSize.x;
    const int2 maxBounds = int2(RenderSize.xy) - 1;
    const int2 pxMedOrigin = groupID.xy * s_ThreadGroupSize - s_SM_Med_HaloOffset;
    
    [unroll]
    for (int i1 = 0; i1 < s_SM_Med_LoadsPerThread; i1++)
    {
        const uint smFlatID = flatID + i1 * NUM_THREADS;
        
        if (smFlatID < s_SM_Med_ElementCount)
        {
            const int2 smID = int2(smFlatID % s_SM_Med_Size.x, smFlatID / s_SM_Med_Size.x);
            const int2 px = clamp(pxMedOrigin + smID, int2(0, 0), maxBounds);
            const float3 color = GetSafeFP16(InColor[px].rgb);
            
            g_Color[smID.x][smID.y] = half4(color, GetLuminance(color));
        }
    }
    
    const int2 pxDepthOrigin = groupID.xy * s_ThreadGroupSize - s_SM_Depth_HaloOffset;
    
    [unroll]
    for (int i2 = 0; i2 < s_SM_Depth_LoadsPerThread; i2++)
    {
        const uint smFlatID = flatID + i2 * NUM_THREADS;
        
        if (smFlatID < s_SM_Depth_ElementCount)
        {
            const int2 smID = int2(smFlatID % s_SM_Depth_Size.x, smFlatID / s_SM_Depth_Size.x);
            const int2 px = clamp(pxDepthOrigin + smID, int2(0, 0), maxBounds);
            const float3 color = GetSafeFP16(InColor[px].rgb);
            
            g_Depth[smID.x][smID.y] = GetViewSpacePos(px).z;
        }
    }
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const int2 px = groupID.xy * s_ThreadGroupSize + gtID.xy;
    PopulateSharedMemory(groupID.xy, gtID.xy);
    GroupMemoryBarrierWithGroupSync();

    if (px.x >= RenderSize.x || px.y >= RenderSize.y)
        return;
    
    const half3 specAlbedo = GetSafeFP16(InSpecAlbedo[px].rgb);
    const half3 diffAlbedo = GetSafeFP16(InDiffAlbedo[px].rgb);
    const half avgAlbedo = dot(specAlbedo + diffAlbedo, 0.33f);
    
    const half depthGuide = GetDepthGradientStrength(groupID.xy, gtID.xy);
    const half edgeGuide = GetSafeFP16(avgAlbedo + 0.2f * depthGuide);
    const half4 color = GetStableColor(groupID.xy, gtID.xy);
    
    OutColor[px] = color;
    OutEdgeGuide[px] = edgeGuide;
}