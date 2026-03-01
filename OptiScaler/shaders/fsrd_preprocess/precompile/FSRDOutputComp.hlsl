// FSR-RR Composition Utility
#define THREAD_GROUP_SIZE_X 8
#define THREAD_GROUP_SIZE_Y 8
#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 4), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 1), visibility = SHADER_VISIBILITY_ALL), " \
    "StaticSampler(s0, " \
        "filter = FILTER_MIN_MAG_MIP_LINEAR, " \
        "addressU = TEXTURE_ADDRESS_CLAMP, " \
        "addressV = TEXTURE_ADDRESS_CLAMP, " \
        "addressW = TEXTURE_ADDRESS_CLAMP, " \
        "visibility = SHADER_VISIBILITY_ALL)"

#define FLAGS_RAW_SOURCE_BLIT           (1 << 0)
#define FLAGS_SCALE_SRC                 (1 << 1)

Texture2D<float4> InPrimaryColor : register(t0);
Texture2D<float4> InFusedModulator : register(t1);
Texture2D<float3> InColorBeforeParticles : register(t2);
Texture2D<float4> InSkipSignal : register(t3);

RWTexture2D<float4> OutColor : register(u0);

SamplerState LinearSampler : register(s0);

cbuffer CB_Comp : register(b0)
{
    float4 DstTexSize;
    uint Flags;
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

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
            OutColor[id.xy] = InPrimaryColor.SampleLevel(LinearSampler, uv, 0);
        }
        else
        {
            OutColor[id.xy] = InPrimaryColor[id.xy];
        } 
    }
    else
    {
        const float4 skip = InSkipSignal[id.xy];
        const float3 particles = InColorBeforeParticles[id.xy];
        const float3 remod = InFusedModulator[id.xy].rgb;
        float3 denoisedColor = 0.0f;
        
        [branch]
        if (IsSet(FLAGS_SCALE_SRC))
        {
            const float2 uv = (float2(id.xy) + 0.5f) * DstTexSize.zw;
            denoisedColor = InPrimaryColor.SampleLevel(LinearSampler, uv, 0).rgb * remod;
        }
        else
        {
            denoisedColor = InPrimaryColor[id.xy].rgb * remod;
        }
        
        // Sanity check for extrema that slipped through
        const float normSkip = dot(skip.rgb, 1.0f) * rcp(dot(denoisedColor.rgb, 1.0f) + 1e-2f);   
        // -> 1 as the denoised and skip values converge
        const float gateDelta = 1.0f - saturate(abs(1.0f - normSkip));
        const bool canSkip = gateDelta > 0.5f || skip.a >= 1.0f;
        const float coherence = skip.a * float(canSkip);
        
        const float3 outColor = lerp(denoisedColor, skip.rgb, saturate(coherence)) + particles.rgb;
                
        OutColor[id.xy] = float4(outColor, 1.0f);
    }
}