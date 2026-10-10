#include "FSRDPreprocessCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=5)), DescriptorTable(UAV(u0, numDescriptors=1))"
Texture2D<half4> InDiffuse : register(t0);
Texture2D<float> InGuide : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InNormals : register(t3);
Texture2D<float4> InBounds : register(t4);
RWTexture2D<half4> OutDiffuse : register(u0);
cbuffer CB_SkinPrefilter : register(b0)
{
    float4 DstTexSize;
    float Sigma;
    uint Vertical;
    uint2 GuideBase;
}
void ScalarMain(uint3 tid : SV_DispatchThreadID)
{
    const int2 p = tid.xy;
    if (any(p >= int2(DstTexSize.xy))) return;
    const half4 center = InDiffuse[p];
    if (InGuide[p + int2(GuideBase)] == 0.0f) { OutDiffuse[p]=center;return; }
    const float z = InDepth[p];
    if (!isfinite(z) || abs(z)<=0.0f) { OutDiffuse[p]=center;return; }
    const float2 centerUv = InNormals[p].xy;
    const float3 normal = OctahedralDecode(centerUv);
    const bool validCenterUv=all(centerUv>=0.0f) && all(centerUv<=1.0f);
    const int radius = int(ceil(2.5f * clamp(Sigma, 0.5f, 6.0f)));
    float3 delta = 0.0f;
    float weight = 1.0f;
    const float firstWeight=exp(-0.5f/(Sigma*Sigma));
    const float ratioStep=firstWeight*firstWeight;
    float tapWeight=firstWeight,tapRatio=firstWeight*ratioStep;
    [loop] for (int i = 1; i <= radius; ++i)
    {
        const float w=tapWeight;tapWeight*=tapRatio;tapRatio*=ratioStep;
        [unroll] for (int sign = -1; sign <= 1; sign += 2)
        {
            const int2 q = clamp(p + (Vertical != 0u ? int2(0,sign*i) : int2(sign*i,0)),
                                 0, int2(DstTexSize.xy)-1);
            if (InGuide[q + int2(GuideBase)] == 0.0f || abs(InDepth[q]-z) > 0.05f*abs(z)) continue;
            const float2 neighbourUv = InNormals[q].xy;
            // The octahedral raw vector has length >= 1/sqrt(3), and its
            // piecewise-linear map is 2*sqrt(3)-Lipschitz in UV. Normalization
            // bounds direction distance by 12*|delta UV|. With each UV delta
            // <= 1/64, the decoded dot is >= 1-144/4096 = 0.96484375 > 0.9.
            // This sufficient test changes no accepted samples; use the exact
            // original decode/dot test for every other pair.
            const bool certainlySame = validCenterUv && all(neighbourUv>=0.0f) &&
                all(neighbourUv<=1.0f) && all(abs(neighbourUv-centerUv) <= (1.0f/64.0f));
            if (!certainlySame && dot(normal, OctahedralDecode(neighbourUv)) <= 0.9f) continue;
            delta += (float3(InDiffuse[q].rgb)-float3(center.rgb))*w;
            weight += w;
        }
    }
    OutDiffuse[p] = half4(float3(center.rgb)+delta/weight, center.a);
}

// Prove that every sample in this wave's complete support rectangle passes
// the existing guide/depth/normal tests. Otherwise use the unchanged path.
// No LDS, thread-layout assumption, mask relaxation or new output threshold.
void IndependentMain(uint3 tid : SV_DispatchThreadID, uint localIndex : SV_GroupIndex)
{
    const int2 extent=int2(DstTexSize.xy);
    const int2 tileBase=(int2(tid.xy)>>4)<<4;
    const uint2 gid=tid.xy>>3u;
    const uint strip=(gid.x&1u)+((gid.y&1u)<<1u);
    const int2 local=int2(localIndex&15u,localIndex>>4u);
    const int2 horizontal=tileBase+int2(local.x,int(strip)*4+local.y);
    const int2 vertical=tileBase+int2(int(strip)*4+local.y,local.x);
    // Complete tiles are a bijective permutation of the original pixels.
    // Partial tiles retain the original mapping, including dispatch padding.
    const int2 p=all(tileBase+16<=extent)?(Vertical!=0u?vertical:horizontal):int2(tid.xy);
    const bool inside=all(p<extent);
    const half4 center=inside?InDiffuse[p]:half4(0,0,0,0);
    const float guide=inside?InGuide[p+int2(GuideBase)]:0.0f;
    if (WaveActiveAllTrue(!inside || guide==0.0f))
    {
        if (inside) OutDiffuse[p]=center;
        return;
    }
    const int radius=int(ceil(2.5f*clamp(Sigma,0.5f,6.0f)));
    // Partial remapping tiles use the unchanged scalar path. Every full
    // logical group is 16 by 4, transposed with the filter direction.
    if (!all(tileBase+16<=extent))
    {
        ScalarMain(uint3(p,0));
        return;
    }
    const int2 groupOrigin=Vertical!=0u?int2((p.x>>2)<<2,(p.y>>4)<<4)
                                           :int2((p.x>>4)<<4,(p.y>>2)<<2);
    const int2 origin=groupOrigin-(Vertical!=0u?int2(0,radius):int2(radius,0));
    const uint alongSize=16u+2u*uint(radius),chunks=(alongSize+7u)>>3u;
    float minDepth=3.402823e38f,maxDepth=-3.402823e38f;
    float2 minUv=3.402823e38f,maxUv=-3.402823e38f;
    bool valid=true;
    for (uint index=WaveGetLaneIndex();index<chunks*32u;index+=WaveGetLaneCount())
    {
        const uint along=(index&7u)+((index>>5u)<<3u);
        const uint across=(index>>3u)&3u;
        if (along>=alongSize) continue;
        const int2 offset=Vertical!=0u?int2(across,along):int2(along,across);
        const int2 q=clamp(origin+offset,0,extent-1);
        const float d=InDepth[q],g=InGuide[q+int2(GuideBase)];
        const float2 uv=InNormals[q].xy;
        valid=valid && isfinite(d) && d>0.0f && g!=0.0f && isfinite(g) &&
              all(isfinite(uv)) && all(uv>=0.0f) && all(uv<=1.0f);
        minDepth=min(minDepth,d);maxDepth=max(maxDepth,d);
        minUv=min(minUv,uv);maxUv=max(maxUv,uv);
    }
    const float low=WaveActiveMin(minDepth),high=WaveActiveMax(maxDepth);
    const float2 uvLow=WaveActiveMin(minUv),uvHigh=WaveActiveMax(maxUv);
    const bool allValid=WaveActiveAllTrue(valid);
    // Any pair then has depth difference <= 5% of the smallest depth.
    // The UV rectangle bounds imply the same >=0.96484375 dot-product bound
    // already used by the production per-neighbour shortcut.
    const bool coherent=allValid && high-low<=0.05f*low && all(uvHigh-uvLow<=1.0f/64.0f);
    if (!coherent)
    {
        ScalarMain(uint3(p,0));
        return;
    }
    if (!inside) return;
    float3 delta=0.0f;
    float weight=1.0f;
    const float firstWeight=exp(-0.5f/(Sigma*Sigma));
    const float ratioStep=firstWeight*firstWeight;
    float tapWeight=firstWeight,tapRatio=firstWeight*ratioStep;
    [unroll] for (int i=1;i<=15;++i)
    {
        if (i>radius) break;
        const float w=tapWeight;tapWeight*=tapRatio;tapRatio*=ratioStep;
        [unroll] for (int sign=-1;sign<=1;sign+=2)
        {
            const int2 q=clamp(p+(Vertical!=0u?int2(0,sign*i):int2(sign*i,0)),0,extent-1);
            delta+=(float3(InDiffuse[q].rgb)-float3(center.rgb))*w;
            weight+=w;
        }
    }
    OutDiffuse[p]=half4(float3(center.rgb)+delta/weight,center.a);
}

groupshared uint CachedRG[64*8];
groupshared float CachedB[64*8];
void StoreColor(uint index,half4 color)
{
    const uint2 bits=f32tof16(float2(color.rg));
    CachedRG[index]=bits.x|(bits.y<<16u);
    CachedB[index]=float(color.b);
}
float3 LoadColor(uint index)
{
    const uint bits=CachedRG[index];
    return float3(f16tof32(uint2(bits&65535u,bits>>16u)),CachedB[index]);
}

groupshared uint GroupCoherent;
[RootSignature(MainRS)]
[numthreads(16,16,1)]
void CSMain(uint3 gid:SV_GroupID,uint localIndex:SV_GroupIndex)
{
    const int2 extent=int2(DstTexSize.xy);
    const int2 groupOrigin=int2(gid.xy)*(Vertical!=0u?int2(8,32):int2(32,8));
    const int2 block=Vertical!=0u?int2(16,32):int2(32,16);
    const int2 tileBase=Vertical!=0u?int2((groupOrigin.x>>4)<<4,groupOrigin.y):
                                        int2(groupOrigin.x,(groupOrigin.y>>4)<<4);
    const uint subGroup=localIndex>>6u,subLane=localIndex&63u;
    // Each fallback wave keeps the production 16x4 logical output group.
    const int2 fallbackPixel=groupOrigin+(Vertical!=0u?
        int2((subGroup>>1u)*4u+(subLane>>4u),(subGroup&1u)*16u+(subLane&15u)):
        int2((subGroup&1u)*16u+(subLane&15u),(subGroup>>1u)*4u+(subLane>>4u)));
    const int2 fallbackTile=(fallbackPixel>>4)<<4;
    const uint strip=Vertical!=0u?uint(fallbackPixel.x&15)>>2u:uint(fallbackPixel.y&15)>>2u;
    const int2 virtualTid=all(fallbackTile+16<=extent)?
        fallbackTile+int2((strip&1u)*8u,(strip>>1u)*8u)+int2(subLane&7u,subLane>>3u):fallbackPixel;
    if (WaveGetLaneCount()!=64u || !all(tileBase+block<=extent))
    {
        IndependentMain(uint3(virtualTid,0),subLane);
        return;
    }
    const int along=int(localIndex&31u),across=int(localIndex>>5u);
    const int2 p=groupOrigin+(Vertical!=0u?int2(across,along):int2(along,across));
    const int radius=int(ceil(2.5f*clamp(Sigma,0.5f,6.0f)));
    const int2 proofOrigin=tileBase-(Vertical!=0u?int2(0,radius):int2(radius,0));
    const int2 proofLast=tileBase+block-1+(Vertical!=0u?int2(0,radius):int2(radius,0));
    const int2 tileLow=clamp(proofOrigin,0,extent-1)>>4;
    const int2 tileHigh=clamp(proofLast,0,extent-1)>>4;
    float4 lower=float4(3.402823e38f,3.402823e38f,3.402823e38f,1.0f);
    float3 upper=0.0f;
    if (localIndex==0u)
    {
        // Bounds UV extrema are exact R10 integer codes. A span <=15 codes
        // is equivalent to a decoded span <=1/64 for all R10 values.
        // The 32x16 / 16x32 block plus a radius <=15 spans at most four
        // bounds tiles along the filtered axis and one across it.
        const int count=Vertical!=0u?tileHigh.y-tileLow.y+1:tileHigh.x-tileLow.x+1;
        float4 lows[4],highs[4];
        [unroll] for (int i=0;i<4;++i)
        {
            lows[i]=float4(3.402823e38f,3.402823e38f,3.402823e38f,1.0f);
            highs[i]=0.0f;
            if (i<count)
            {
                const int2 q=tileLow+(Vertical!=0u?int2(0,i):int2(i,0));
                lows[i]=InBounds[int2(2*q.x,q.y)];
                highs[i]=InBounds[int2(2*q.x+1,q.y)];
            }
        }
        [unroll] for (int i=0;i<4;++i)
        {
            lower.xyz=min(lower.xyz,lows[i].xyz);upper=max(upper,highs[i].xyz);
            lower.w=min(lower.w,lows[i].w);
        }
    }
    if (localIndex==0u)
        GroupCoherent=lower.w==1.0f && upper.x-lower.x<=0.05f*lower.x &&
            all(upper.yz-lower.yz<=15.0f)?1u:0u;
    const int2 origin=groupOrigin-(Vertical!=0u?int2(0,radius):int2(radius,0));
    const uint alongSize=32u+2u*uint(radius);
    for (uint index=localIndex;index<512u;index+=256u)
    {
        const uint a=index&63u,cross=index>>6u;
        if (a>=alongSize) continue;
        const int2 offset=Vertical!=0u?int2(cross,a):int2(a,cross);
        StoreColor(index,InDiffuse[clamp(origin+offset,0,extent-1)]);
    }
    GroupMemoryBarrierWithGroupSync();
    if (GroupCoherent==0u)
    {
        IndependentMain(uint3(virtualTid,0),subLane);
        return;
    }
    const half4 center=InDiffuse[p];
    const uint centerIndex=(localIndex>>5u)*64u+(localIndex&31u)+uint(radius);
    float3 delta=0.0f;
    float weight=1.0f;
    const float firstWeight=exp(-0.5f/(Sigma*Sigma));
    const float ratioStep=firstWeight*firstWeight;
    float tapWeight=firstWeight,tapRatio=firstWeight*ratioStep;
    [unroll] for (int i=1;i<=15;++i)
    {
        if (i>radius) break;
        const float w=tapWeight;tapWeight*=tapRatio;tapRatio*=ratioStep;
        [unroll] for (int sign=-1;sign<=1;sign+=2)
        {
            delta+=(LoadColor(uint(int(centerIndex)+sign*i))-float3(center.rgb))*w;
            weight+=w;
        }
    }
    OutDiffuse[p]=half4(float3(center.rgb)+delta/weight,center.a);
}
