// Open-loop input-history validation. Lighting itself is never filtered or replaced.
// Each group covers 32x32 pixels; 16 temporal statistics live on an 8x8 sub-block grid.
#include "FSRDNrdLightingGuard_Common.hlsli"

groupshared float2 SumL[256],SumMV[256];
groupshared float2 C[16],Mean[16],Var[16],Fast[16];
groupshared uint Event,Pending,PositiveEvent,PositiveLobes,NextFlags;
static const float3 LUMA=float3(.2126,.7152,.0722);
float2 Clean(float2 x) { return float2(isfinite(x.x)?max(x.x,0):0,isfinite(x.y)?max(x.y,0):0); }
float4 ReadMeanVar(int2 p,int2 extent) { return PrevMeanVar.Load(int3(clamp(p,0,extent-1),0)); }
float2 ReadFast(int2 p,int2 extent) { return PrevFast.Load(int3(clamp(p,0,extent-1),0)); }
[RootSignature(RS_STATS)]
[numthreads(16,16,1)]
void CSMain(uint3 group:SV_GroupID,uint3 tid:SV_GroupThreadID,uint lane:SV_GroupIndex)
{
    uint2 origin=group.xy*32+tid.xy*2;
    float2 l=0,mv=0;
    [unroll] for(uint y=0;y<2;y++) [unroll] for(uint x=0;x<2;x++)
    {
        uint2 p=min(origin+uint2(x,y),uint2(Width-1,Height-1));
        l+=Clean(float2(dot(InDiffuse.Load(int3(p,0)).rgb,LUMA),dot(InSpecular.Load(int3(p,0)).rgb,LUMA)));
        mv+=InMotion.Load(int3(p,0)).xy*float2(Width,Height);
    }
    SumL[lane]=l;SumMV[lane]=mv;
    GroupMemoryBarrierWithGroupSync();
    if(lane<16)
    {
        uint2 sub=uint2(lane%4,lane/4);float2 a=0,b=0;
        [unroll] for(uint y=0;y<4;y++) [unroll] for(uint x=0;x<4;x++)
        { uint index=(sub.y*4+y)*16+sub.x*4+x;a+=SumL[index];b+=SumMV[index]; }
        a/=64;b/=64;C[lane]=a;
        int2 extent=int2((Width+31)/32*4,(Height+31)/32*4);
        float2 q=float2(group.xy*4+sub)+b/8;
        bool valid=all(q>=-.5)&&all(q<=float2(extent)-.5)&&all(isfinite(q));
        q=clamp(q,0,float2(extent-1));int2 p=int2(floor(q));float2 f=q-p;
        float4 v=lerp(lerp(ReadMeanVar(p,extent),ReadMeanVar(p+int2(1,0),extent),f.x),
                      lerp(ReadMeanVar(p+int2(0,1),extent),ReadMeanVar(p+1,extent),f.x),f.y);
        float2 fast=lerp(lerp(ReadFast(p,extent),ReadFast(p+int2(1,0),extent),f.x),
                         lerp(ReadFast(p+int2(0,1),extent),ReadFast(p+1,extent),f.x),f.y);
        if(Reset||!valid) { v=float4(a,max(a*a,1e-12));fast=a; }
        Mean[lane]=v.xy;Var[lane]=max(v.zw,1e-12);Fast[lane]=fast+.5*(a-fast);
    }
    GroupMemoryBarrierWithGroupSync();
    if(lane==0)
    {
        float2 mean=0,fast=0,var=0;
        [unroll] for(uint k=0;k<16;k++) { mean+=Mean[k];fast+=Fast[k];var+=Var[k]; }
        mean/=16;float2 d=fast/16-mean;
        // Empirically calibrated noise multiplier, NOT a four-sigma independence guarantee.
        float2 noise=sqrt(max(var/384,1e-20));
        float2 z=abs(d)/max(noise,.02*mean+1e-10),rel=abs(d)/max(mean,1e-8),agree=0;
        [unroll] for(uint k=0;k<16;k++) agree+=float2(sign(Fast[k]-Mean[k])==sign(d));
        // Replicated edge pixels cannot supply a coherent 16-cell seed.
        // Keep their moments/support for interpolation from fully observed neighbours.
        const bool fullRoot=(group.x+1)*32<=Width&&(group.y+1)*32<=Height;
        bool2 candidate=(z>4)&(rel>.2)&(agree>=14)&(mean>1e-7)&(Age>16)&fullRoot;
        uint old=Reset?0:PrevTile.Load(int3(group.xy,0));
        uint2 count=uint2(old&15,(old>>4)&15),negative=uint2(d<0);
        bool2 same=negative==uint2((old>>20)&1,(old>>21)&1);
        count=uint2(candidate.x?(same.x?count.x+1:1):0,candidate.y?(same.y?count.y+1:1):0);
        bool2 events=count>=2;Event=any(events);
        const bool negativeEvent=any(events&(d<0));PositiveEvent=Event&&!negativeEvent;
        PositiveLobes=PositiveEvent?((events.x&&d.x>0?1u:0u)|(events.y&&d.y>0?2u:0u)):0;
        uint ttl=(old>>8)&15;
        if(negativeEvent)ttl=1;
        if(PositiveEvent)ttl=0;
        Pending=ttl>0;
        if(Event)count=0;
        NextFlags=count.x|(count.y<<4)|((ttl?ttl-1:0)<<8)|(Pending<<16)|(PositiveEvent<<17)|(PositiveLobes<<18)|(negative.x<<20)|(negative.y<<21);
        NextTile[group.xy]=NextFlags;
    }
    GroupMemoryBarrierWithGroupSync();
    if(lane<16)
    {
        float2 mean=Mean[lane],var=Var[lane],a=C[lane],delta=a-mean,fast=Fast[lane];
        uint2 p=group.xy*4+uint2(lane%4,lane/4);
        // Locate confirmed positive change before the detector takes its new baseline.
        // Every padded cell is written, including zero in unconfirmed neighbouring tiles.
        float2 change=min(max((fast-mean)/max(mean,1e-8),0),4);
        NextChange[p]=change*float2((PositiveLobes&1)!=0,(PositiveLobes&2)!=0);
        // Unmasked evidence is separate from the established confirmed-cell support.
        // This is empirical local SNR, not a sigma/independence guarantee.
        precise float2 localZ=abs(fast-mean)/sqrt(max(var*(2.0/3.0),1e-20));
        NextSupport[p]=float4(change,localZ);
        if(Event) { var*=pow(clamp(a/max(mean,1e-8),.25,4),2);mean=a;fast=a; }
        else { var=.95*var+.05*delta*delta;mean+=.05*delta; }
        NextMeanVar[p]=float4(mean,var);NextFast[p]=fast;
    }

}
