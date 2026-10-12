#include "FSRDFlatTemporalCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 8)), DescriptorTable(UAV(u0, numDescriptors = 1))"
// Current frame's low-pass lumas on the 4x4 block grid, one thread per block. Every block is
// written every frame, so the resolve and the history ring never read a stale block.
Texture2D<float4> InComposed : register(t0);
Texture2D<float4> InNormals : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InSpecular : register(t3);
Texture2D<float4> InDiffuse : register(t4);
Texture2D<float4> InSpecularAlbedo : register(t5);
Texture2D<float4> InDiffuseAlbedo : register(t6);
Texture2D<float4> InSkip : register(t7);
RWTexture2D<float2> OutLP : register(u0);

// RR and raw luma of the 8x8 blocks' 40x40 pixel window; RR < 0 marks a non-flat pixel. 12,800 bytes.
groupshared float2 Window[40][40];

bool FlatPixel(int2 p)
{
    if (!TemporalInBounds(p)) return false;
    const float z=InDepth[p];
    return abs(InNormals[p].a-1.0f/3.0f)<0.1f && InSkip[p].a!=-1.0f && isfinite(z) && abs(z)>1e-5f;
}

float3 RawColor(int2 p)
{
    const float3 s=InSpecular[p].rgb*((Flags&1u)!=0u ? 2.0f : 1.0f);
    const float3 d=InDiffuse[p].rgb*((Flags&2u)!=0u ? 2.0f : 1.0f);
    return SanitizeRadiance(s*lerp(1.0f,InSpecularAlbedo[p].rgb,Modulation.x)+
                            d*lerp(1.0f,InDiffuseAlbedo[p].rgb,Modulation.y)+InSkip[p].rgb);
}

[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 group:SV_GroupID,uint3 local:SV_GroupThreadID)
{
    const int2 origin=int2(group.xy)*32-4;
    const uint lane=local.y*8+local.x;
    for (uint i=lane;i<1600;i+=64)
    {
        const int2 q=origin+int2(i%40,i/40);
        Window[i/40][i%40]=FlatPixel(q) ?
            float2(GetLuminance(SanitizeRadiance(InComposed[q].rgb)),GetLuminance(RawColor(q))) : float2(-1.0f,0.0f);
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 block=int2(group.xy)*8+int2(local.xy);
    if (any(block>=LPSize())) return;
    const int2 w=int2(local.xy)*4;
    float rr=0,rrCount=0,raw=0,rawCount=0;
    [loop] for (int y=0;y<12;++y) [loop] for (int x=0;x<12;++x)
    {
        const float2 v=Window[w.y+y][w.x+x];
        if (v.x<0.0f) continue;
        raw+=v.y;rawCount+=1;
        if (x>=2 && x<10 && y>=2 && y<10) { rr+=v.x;rrCount+=1; }
    }
    OutLP[block]=rrCount>0.0f ? float2(rr/rrCount,raw/rawCount) : float2(-1.0f,-1.0f);
}
