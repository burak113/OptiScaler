// FSR-RR Conversion & Packing Shader
#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
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

#define FLAGS_RAW_SOURCE_BLIT   (1 << 0)

Texture2D<float4> InPrimaryColor : register(t0);
Texture2D<float4> InFusedModulator : register(t1);
Texture2D<float4> InSkipSignal : register(t2);

RWTexture2D<float4> OutColor : register(u0);

SamplerState LinearSampler : register(s0);

cbuffer CB_Comp : register(b0)
{
    float2 RenderSize;
    uint Flags;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= RenderSize.x || id.y >= RenderSize.y)
        return;
    
    [branch]
    if (IsSet(FLAGS_RAW_SOURCE_BLIT))
    {
        OutColor[id.xy] = InPrimaryColor[id.xy];
    }
    else
    {
        const float3 color = InPrimaryColor[id.xy].rgb * InFusedModulator[id.xy].rgb;
        OutColor[id.xy] = float4(color + InSkipSignal[id.xy].rgb, 1.0f);
    }
}