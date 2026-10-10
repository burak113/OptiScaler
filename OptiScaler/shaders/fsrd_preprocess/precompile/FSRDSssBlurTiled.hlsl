#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=5)), DescriptorTable(UAV(u0, numDescriptors=1))"
Texture2D<half4> InColor : register(t0);
Texture2D<float> InGuide : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<half4> InOriginal : register(t3);
Texture2D<float4> InKernel : register(t4);
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
void ScalarMain(uint3 tid : SV_DispatchThreadID)
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


groupshared float3 BatchCoefficients[65];
float3 ReadCoefficient(uint index)
{
    // These calls are reached with the complete wave active and one
    // group-uniform index. The shared value is identical for every lane.
    float3 value=0.0f;
    if(WaveIsFirstLane()) value=BatchCoefficients[index];
    return WaveReadLaneFirst(value);
}

groupshared uint BatchRG[64*16];
groupshared float BatchB[64*16];
float3 ReadBatch(int index)
{
    const uint rg=BatchRG[index];
    return float3(f16tof32(uint2(rg&65535u,rg>>16u)),BatchB[index]);
}
void BatchFallback(int2 groupOrigin,uint localIndex)
{
    const int along=int(localIndex&31u),across=int(localIndex>>5u);
    [unroll] for(int batch=0;batch<2;++batch)
    {
        const int row=across+batch*8;
        const int2 p=groupOrigin+(Vertical!=0u?int2(row,along):int2(along,row));
        ScalarMain(uint3(p,0));
    }
}
[RootSignature(MainRS)]
[numthreads(16,16,1)]
void CSMain(uint3 gid:SV_GroupID,uint localIndex:SV_GroupIndex)
{
    const int2 extent=int2(DstTexSize.xy);
    const int2 groupOrigin=int2(gid.xy)*(Vertical!=0u?int2(16,32):int2(32,16));
    const uint tileWidth=32u;
    const uint columns=(uint(DstTexSize.x)+tileWidth-1u)/tileWidth;
    const uint bands=(columns+127u)/128u;
    const uint2 owner=uint2(groupOrigin)>>5u;
    const int2 kernelBase=int2((owner.x&127u)*66u,owner.y*bands+(owner.x>>7u));
    const float4 header=InKernel[kernelBase];
    if(Strength==0.0f || header.x!=1.0f || header.y>16.0f ||
       any(groupOrigin+(Vertical!=0u?int2(16,32):int2(32,16))>extent))
    {
        BatchFallback(groupOrigin,localIndex);
        return;
    }
    const int count=int(header.y);
    if(localIndex < 2u*uint(count))
        BatchCoefficients[localIndex]=InKernel[kernelBase+int2(localIndex+1u,0)].rgb;
    if(localIndex == 64u)
        BatchCoefficients[64]=InKernel[kernelBase+int2(65,0)].rgb;
    const int2 origin=groupOrigin-(Vertical!=0u?int2(0,count):int2(count,0));
    const uint alongSize=32u+2u*uint(count);
    for(uint item=localIndex;item<1024u;item+=256u)
    {
        const uint along=item&63u,across=item>>6u;
        if(along>=alongSize) continue;
        const int2 q=origin+(Vertical!=0u?int2(across,along):int2(along,across));
        const float3 value=float3(InColor[q].rgb);
        const uint index=across*64u+along;
        const uint2 bits=f32tof16(value.rg);
        BatchRG[index]=bits.x|(bits.y<<16u);BatchB[index]=value.b;
    }
    GroupMemoryBarrierWithGroupSync();
    const int along=int(localIndex&31u),across=int(localIndex>>5u);
    const int2 p0=groupOrigin+(Vertical!=0u?int2(across,along):int2(along,across));
    const int2 p1=groupOrigin+(Vertical!=0u?int2(across+8,along):int2(along,across+8));
    const int index0=across*64+along+count,index1=index0+8*64;
    const float3 center0=ReadBatch(index0),center1=ReadBatch(index1);
    float3 sum0=0.0f,sum1=0.0f;
    const int axis=Vertical!=0u?p0.y:p0.x;
    const int axisExtent=Vertical!=0u?extent.y:extent.x;
    const int axisOrigin=Vertical!=0u?groupOrigin.y:groupOrigin.x;
    const bool completeSupport=axisOrigin>=count && axisOrigin+32+count<=axisExtent;
    float3 weight=ReadCoefficient(64);
    if(completeSupport)
    {
        [unroll] for(int i=1;i<=16;++i)
        {
            if(i>count) break;
            const float3 left=ReadCoefficient(2*i-2),right=ReadCoefficient(2*i-1);
            sum0+=(ReadBatch(index0-i)-center0)*left;
            sum1+=(ReadBatch(index1-i)-center1)*left;
            sum0+=(ReadBatch(index0+i)-center0)*right;
            sum1+=(ReadBatch(index1+i)-center1)*right;
        }
    }
    else
    {
        weight=1.0f;
        [unroll] for(int i=1;i<=16;++i)
        {
            if(i>count) break;
            const float3 left=ReadCoefficient(2*i-2),right=ReadCoefficient(2*i-1);
            if(axis-i>=0)
            {
                sum0+=(ReadBatch(index0-i)-center0)*left;
                sum1+=(ReadBatch(index1-i)-center1)*left;
                weight+=left;
            }
            if(axis+i<axisExtent)
            {
                sum0+=(ReadBatch(index0+i)-center0)*right;
                sum1+=(ReadBatch(index1+i)-center1)*right;
                weight+=right;
            }
        }
    }
    const half4 original0=InOriginal[p0],original1=InOriginal[p1];
    const float3 blurred0=center0+sum0/weight,blurred1=center1+sum1/weight;
    const float3 result0=Vertical!=0u?lerp(float3(original0.rgb),blurred0,Strength):blurred0;
    const float3 result1=Vertical!=0u?lerp(float3(original1.rgb),blurred1,Strength):blurred1;
    OutColor[p0]=half4(result0,original0.a);
    OutColor[p1]=half4(result1,original1.a);
}
