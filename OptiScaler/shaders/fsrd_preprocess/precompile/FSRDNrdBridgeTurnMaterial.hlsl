// Experimental same-surface aperture for the existing post-turn input colour filter.
// Albedo defines neighbourhood support only. Lighting is already demodulated:
// never divide it by these guides or tint it towards their RGB.
// Each lobe keeps its own sample luminance and opaque alpha. No temporal state.
#include "FSRDPreprocessCommon.hlsli"
#define MainRS "RootFlags(0), RootConstants(num32BitConstants=4,b0), " \
    "DescriptorTable(SRV(t0,numDescriptors=6),UAV(u0,numDescriptors=2))"
Texture2D<float4> InSignal[2] : register(t0); // specular, diffuse
Texture2D<float4> InAlbedo[2] : register(t2);
Texture2D<float4> InNormalRoughness : register(t4); // original, before NZR's roughness override
Texture2D<float> InDepth : register(t5);
RWTexture2D<float4> OutSignal[2] : register(u0);
cbuffer Params : register(b0) { uint2 RenderSize; float Weight,Gain; }
#define GROUP 16
#define RADIUS 5
#define TILE (GROUP+2*RADIUS)
groupshared float16_t4 Signal[TILE*TILE];
groupshared uint Albedo[TILE*TILE];
groupshared float4 Geometry[TILE*TILE];
groupshared float Depth[TILE*TILE];
groupshared float4 Rows[TILE*GROUP]; // weighted RGB sum, support (never fp16)
static const float3 LUMA=float3(.2126,.7152,.0722);
float Max3(float3 v) { return max(v.x,max(v.y,v.z)); }
float3 Guide(uint k)
{
    uint q=Albedo[k];return float3(q&255,(q>>8)&255,(q>>16)&255)/255.0;
}
float SurfaceWeight(uint k,float3 q0,float4 nr0,float z0)
{
    float3 q=Guide(k);float4 nr=Geometry[k];
    float qe=Max3(abs(q-q0))/(max(Max3(q),Max3(q0))+.04);
    float4 gates=saturate(float4(1-qe/.35,(dot(nr0.xyz,nr.xyz)-.85)/.15,
        1-abs(Depth[k]-z0)/(max(z0,1e-5)*.025),1-abs(nr.w-nr0.w)/.2));
    float w=gates.x*gates.y*gates.z*gates.w;return w*w;
}

[RootSignature(MainRS)]
[numthreads(GROUP,GROUP,1)]
void CSMain(uint3 id:SV_DispatchThreadID,uint3 group:SV_GroupID,uint3 local:SV_GroupThreadID,uint lane:SV_GroupIndex)
{
    const int2 origin=int2(group.xy)*GROUP-RADIUS;
    for(uint k=lane;k<TILE*TILE;k+=GROUP*GROUP)
    {
        int2 p=clamp(origin+int2(k%TILE,k/TILE),0,int2(RenderSize)-1);
        float4 nr=InNormalRoughness.Load(int3(p,0));
        Geometry[k]=float4(OctahedralDecode(nr.xy),nr.z);
        Depth[k]=abs(InDepth.Load(int3(p,0)));
    }
    GroupMemoryBarrierWithGroupSync();
    uint centre=(local.y+RADIUS)*TILE+local.x+RADIUS;
    float4 nr0=Geometry[centre];float z0=Depth[centre];
    [unroll] for(uint lobe=0;lobe<2;lobe++)
    {
        for(uint k=lane;k<TILE*TILE;k+=GROUP*GROUP)
        {
            int2 p=clamp(origin+int2(k%TILE,k/TILE),0,int2(RenderSize)-1);
            float3 rgb=InSignal[lobe].Load(int3(p,0)).rgb;
            Signal[k]=float16_t4(all(isfinite(rgb))?max(rgb,0):0,0);
            uint3 q=uint3(round(InAlbedo[lobe].Load(int3(p,0)).rgb*255.0));
            Albedo[k]=q.x|(q.y<<8)|(q.z<<16);
        }
        GroupMemoryBarrierWithGroupSync();
        // Separable, two-hop surface support. Every horizontal and vertical hop
        // crosses the same guide gates. 11+11 taps instead of 121 per output.
        for(uint j=lane;j<TILE*GROUP;j+=GROUP*GROUP)
        {
            uint row=j/GROUP,col=j%GROUP,c=row*TILE+col+RADIUS;
            float3 q0=Guide(c);float4 g0=Geometry[c];float d0=Depth[c];float4 sum=0;
            [loop] for(uint x=0;x<2*RADIUS+1;x++)
            {
                uint k=row*TILE+col+x;float w=SurfaceWeight(k,q0,g0,d0);
                sum+=float4(w*float3(Signal[k].rgb),w);
            }
            Rows[j]=sum;
        }
        GroupMemoryBarrierWithGroupSync();
        if(all(id.xy<RenderSize))
        {
            float4 source=InSignal[lobe].Load(int3(id.xy,0));float3 rgb=source.rgb;
            if(all(isfinite(rgb)))
            {
                float3 sum=0;float support=0;float3 q0=Guide(centre);
                [loop] for(uint y=0;y<2*RADIUS+1;y++)
                {
                    uint k=(local.y+y)*TILE+local.x+RADIUS;
                    float w=SurfaceWeight(k,q0,nr0,z0);float4 r=Rows[(local.y+y)*GROUP+local.x];
                    sum+=w*r.rgb;support+=w*r.a;
                }
                float l=dot(sum,LUMA);
                // Sparse/thin surfaces must not borrow a different material's colour.
                if(support>=4 && l>1e-12)
                {
                    float3 delta=sum*(dot(max(source.rgb,0),LUMA)/l)-rgb;
                    // Stay inside half's finite gamut by reducing the chroma move,
                    // not by clipping channels (which would change luminance).
                    float3 room=(65504.0-rgb)/max(delta,1e-20);
                    float safe=min(Weight,min(room.x,min(room.y,room.z)));
                    rgb+=max(safe,0)*delta;
                }
                rgb*=Gain;
            }
            OutSignal[lobe][id.xy]=float4(rgb,source.a);
        }
        GroupMemoryBarrierWithGroupSync();
    }
}
