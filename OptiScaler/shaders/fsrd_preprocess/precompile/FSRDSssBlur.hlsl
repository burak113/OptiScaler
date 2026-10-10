#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=4)), DescriptorTable(UAV(u0, numDescriptors=1))"
Texture2D<half4> InColor : register(t0);
Texture2D<float> InGuide : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<half4> InOriginal : register(t3);
RWTexture2D<half4> OutColor : register(u0);
cbuffer CB_SssBlur : register(b0)
{
    float4 DstTexSize;
    float SigmaScale;
    float RadiusMeters;
    float Strength;
    float Falloff;
    uint Vertical;
    uint Debug;
    uint2 Padding;
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    const int2 p = tid.xy;
    if (any(p >= int2(DstTexSize.xy))) return;
    if (Strength == 0.0f || InGuide[p] == 0.0f)
    {
        OutColor[p] = Vertical != 0u ? InOriginal[p] : InColor[p];
        return;
    }
    const float depth = InDepth[p];
    const float z = abs(depth);
    if (!isfinite(z) || z <= 0.0f)
    {
        OutColor[p] = Vertical != 0u ? InOriginal[p] : InColor[p];
        return;
    }
    const half4 center = InColor[p];
    const half4 original = InOriginal[p];
    const float3 scale = float3(1.0f, 1.0f - 0.6f * Falloff, 1.0f - 0.7f * Falloff);
    // e643bf5f / 12becec2: the reach stays continuous when taps widen.
    const float sigmaPx = SigmaScale / max(z, 1e-3f);
    const float3 sigma = max(sigmaPx * scale, 1e-3f);
    const float reach = 3.0f * sigmaPx;
    const int count = int(min(ceil(reach), 32.0f));
    const float stride = max(reach / 32.0f, 1.0f);
    const float tolerance = 6.0f * RadiusMeters + 0.01f * z;
    float3 sum = 0.0f, weight = 1.0f;
    const float3 firstWeight=exp(-0.5f/(sigma*sigma));
    const float3 ratioStep=firstWeight*firstWeight;
    float3 tapWeight=firstWeight, tapRatio=firstWeight*ratioStep;
    [loop] for (int i = 1; i <= count; ++i)
    {
        const int delta = int(round(float(i) * stride));
        const float3 w=stride==1.0f?tapWeight:exp(-0.5f*float(delta*delta)/(sigma*sigma));
        tapWeight*=tapRatio;tapRatio*=ratioStep;
        [unroll] for (int sign = -1; sign <= 1; sign += 2)
        {
            const int2 q = p + (Vertical != 0u ? int2(0,sign*delta) : int2(sign*delta,0));
            if (any(q < 0) || any(q >= int2(DstTexSize.xy)) || InGuide[q] == 0.0f) continue;
            const float depthWeight = saturate(1.0f - abs(abs(InDepth[q]) - z) / tolerance);
            if (depthWeight <= 0.0f) continue;
            const float3 sampleWeight = w * depthWeight;
            sum += (float3(InColor[q].rgb) - float3(center.rgb)) * sampleWeight;
            weight += sampleWeight;
        }
    }
    const float3 blurred = float3(center.rgb) + sum / weight;
    const float3 result = Vertical != 0u ? lerp(float3(original.rgb), blurred, Strength) : blurred;
    OutColor[p] = half4(result, original.a);
}
