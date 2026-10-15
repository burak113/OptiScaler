// Pass1: causal jitter-gradient noisy reference, CURRENT RR subtraction.
// Histories/reference/pyramid are FP32 for the first parity/cost experiment.
#include "FSRDNrdLobeRecoveryCommon.hlsli"
#define MainRS "RootFlags(0),CBV(b0),DescriptorTable(SRV(t0,numDescriptors=11)),DescriptorTable(UAV(u0,numDescriptors=7))"
Texture2D<float4> NoisySpec : register(t0);
Texture2D<float4> NoisyDiff : register(t1);
Texture2D<float4> RRSpec : register(t2);
Texture2D<float4> RRDiff : register(t3);
Texture2D<float> Depth : register(t4);
Texture2D<float4> Normal : register(t5);
Texture2D<float4> Motion : register(t6);
Texture2D<float4> PrevSpec : register(t7); // RGB reference, A independent lobe age
Texture2D<float4> PrevDiff : register(t8);
Texture2D<uint4> PrevGeometry : register(t9); // depth bits,nativeNR word,qSpec bits,qDiff bits
Texture2D<float4> PrevGradient : register(t10);
RWTexture2D<float4> NextSpec : register(u0);
RWTexture2D<float4> NextDiff : register(u1);
RWTexture2D<uint4> NextGeometry : register(u2);
RWTexture2D<float4> NextGradient : register(u3);
RWTexture2D<float4> LevelSpec : register(u4); // reference-currentRR, innovation luma
RWTexture2D<float4> LevelDiff : register(u5);
RWTexture2D<float4> LevelMetadata : register(u6); // ageSpec,ageDiff,qSpec,qDiff

groupshared float sDepth[12][12];
groupshared float4 sNormal[12][12];
groupshared float3 sReferenceS[10][10],sReferenceD[10][10];
groupshared float2 sAge[10][10],sInnovation[10][10],sWeights[10][10];

struct NrdReferenceHistory
{
    float3 spec,diff;
    float4 gradient;
    float2 age,q;
    bool2 valid;
};
NrdReferenceHistory ReadReference(float2 position,float expectedDepth,float4 nr)
{
    NrdReferenceHistory h;
    h.spec=h.diff=0.0f;h.gradient=0.0f;h.age=1e20f;h.q=0.0f;h.valid=false;
    float2 weight=0.0f;
    const int2 size=int2(FullSize.xy),base=int2(floor(position));
    const float2 f=position-base;
    [unroll]for(int t=0;t<4;++t)
    {
        const int2 offset=int2(t&1,t>>1),p=base+offset;
        if(any(p<0)||any(p>=size))continue;
        const uint4 g=PrevGeometry[p];
        const float4 s=PrevSpec[p],d=PrevDiff[p],gradient=PrevGradient[p];
        if(!NrdRecoverySameGeometry(asfloat(g.x),NrdUnpackNormal(g.y),expectedDepth,nr))continue;
        const float w=(offset.x?f.x:1-f.x)*(offset.y?f.y:1-f.y);
        const float2 oldQ=asfloat(g.zw);
        const bool2 counted=bool2(s.a>0&&all(isfinite(s))&&all(isfinite(gradient.xy))&&isfinite(oldQ.x)&&oldQ.x>0&&oldQ.x<=1,
                                  d.a>0&&all(isfinite(d))&&all(isfinite(gradient.zw))&&isfinite(oldQ.y)&&oldQ.y>0&&oldQ.y<=1)&&(w>0);
        const float2 weights=float2(counted.x?w:0,counted.y?w:0);
        const float2 shift=position-p;
        if(counted.x)
        {
            h.spec+=w*(s.rgb+dot(gradient.xy,shift)*NrdGradientColour(s.rgb));
            h.gradient.xy+=w*gradient.xy;
        }
        if(counted.y)
        {
            h.diff+=w*(d.rgb+dot(gradient.zw,shift)*NrdGradientColour(d.rgb));
            h.gradient.zw+=w*gradient.zw;
        }
        h.age=min(h.age,float2(counted.x?s.a:1e20f,counted.y?d.a:1e20f));
        h.q=max(h.q,float2(counted.x?asfloat(g.z):0,counted.y?asfloat(g.w):0));
        weight+=weights;
    }
    h.valid=weight>=Surface.w;
    h.spec/=max(weight.x,1e-20f);h.diff/=max(weight.y,1e-20f);
    h.gradient/=max(float4(weight.xx,weight.yy),1e-20f);
    h.age=float2(h.valid.x?h.age.x:0,h.valid.y?h.age.y:0);
    return h;
}
float3 UpdateReference(float3 sample,float2 jitterOffset,float age,inout float3 value,
                      inout float2 gradient,out float innovation)
{
    const float rate=max(rcp(age+1.0f),Temporal.x);
    const float3 error=sample-(value+dot(gradient,jitterOffset)*NrdGradientColour(value));
    innovation=NrdRecoveryLuma(error);
    value+=rate*error;
    if(age>=Temporal.w)gradient+=12.0f*rate*innovation*jitterOffset;
    return max(value+dot(gradient,jitterOffset)*NrdGradientColour(value),0.0f);
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 threadID:SV_GroupThreadID,uint3 groupID:SV_GroupID)
{
    const uint thread=threadID.y*8+threadID.x;
    const int2 tile=int2(groupID.xy)*8,size=int2(FullSize.xy);
    for(uint i=thread;i<144;i+=64)
    {
        const int2 p=clamp(tile-2+int2(i%12,i/12),0,size-1);
        sDepth[i/12][i%12]=Depth[p];sNormal[i/12][i%12]=Normal[p];
    }
    GroupMemoryBarrierWithGroupSync();
    for(uint i=thread;i<100;i+=64)
    {
        const int2 l=int2(i%10,i/10),r=tile-1+l,p=clamp(r,0,size-1),c=l+1;
        const float z=sDepth[c.y][c.x];const float4 nr=sNormal[c.y][c.x],mv=Motion[p];
        const float4 inputS=NoisySpec[p],inputD=NoisyDiff[p];
        bool geometry=isfinite(z)&&abs(z)>1e-5f&&nr.b>0&&all(isfinite(mv))&&mv.w>=.5f;
        const float3 n=NrdDecodeOct(nr.xy);float nearZ=z,farZ=z;
        [unroll]for(int dy=-1;dy<=1;++dy)[unroll]for(int dx=-1;dx<=1;++dx)
        {
            const float otherZ=sDepth[c.y+dy][c.x+dx];const float4 other=sNormal[c.y+dy][c.x+dx];
            nearZ=min(nearZ,otherZ);farZ=max(farZ,otherZ);
            geometry=geometry&&isfinite(otherZ)&&dot(n,NrdDecodeOct(other.xy))>Surface.y&&
                uint(round(other.a*3.0f))==uint(round(nr.a*3.0f));
        }
        geometry=geometry&&(farZ-nearZ<=Surface.x*max(abs(z),1e-3f));
        const bool2 eligible=bool2(geometry&&all(isfinite(inputS))&&inputS.a>0,
                                   geometry&&all(isfinite(inputD))&&inputD.a>0);
        NrdReferenceHistory h;h.valid=false;h.age=0;h.q=1;h.gradient=0;h.spec=h.diff=0;
        if(NrdRecoveryFlag(NRD_RECOVERY_HISTORY)&&geometry)
            h=ReadReference(float2(p)+(mv.xy-PixelJitters.zw)*FullSize.xy,z+mv.z,nr);
        h.valid=h.valid&&eligible;
        float3 valueS=inputS.rgb,valueD=inputD.rgb,referenceS=inputS.rgb,referenceD=inputD.rgb;
        float4 gradient=0;float2 age=float2(eligible.x?1:0,eligible.y?1:0),q=1,innovation=0;
        if(h.valid.x)
        {
            valueS=h.spec;gradient.xy=h.gradient.xy;
            float2 gs=gradient.xy;referenceS=UpdateReference(inputS.rgb,-PixelJitters.xy,h.age.x,valueS,gs,innovation.x);gradient.xy=gs;
            const float rate=max(rcp(h.age.x+1),Temporal.x);q.x=(1-rate)*(1-rate)*h.q.x+rate*rate;age.x=min(h.age.x+1,1024.0f);
        }
        if(h.valid.y)
        {
            valueD=h.diff;gradient.zw=h.gradient.zw;
            float2 gd=gradient.zw;referenceD=UpdateReference(inputD.rgb,-PixelJitters.xy,h.age.y,valueD,gd,innovation.y);gradient.zw=gd;
            const float rate=max(rcp(h.age.y+1),Temporal.x);q.y=(1-rate)*(1-rate)*h.q.y+rate*rate;age.y=min(h.age.y+1,1024.0f);
        }
        sReferenceS[l.y][l.x]=max(referenceS,0.0f);sReferenceD[l.y][l.x]=max(referenceD,0.0f);
        sAge[l.y][l.x]=age;sInnovation[l.y][l.x]=innovation;sWeights[l.y][l.x]=q;
        if(all(l>=1)&&all(l<=8)&&all(r==p))
        {
            NextSpec[p]=float4(valueS,age.x);NextDiff[p]=float4(valueD,age.y);
            NextGradient[p]=all(isfinite(gradient))?gradient:0;
            NextGeometry[p]=uint4(asuint(geometry?z:0),NrdPackNormal(nr),asuint(q.x),asuint(q.y));
        }
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 p=tile+int2(threadID.xy),l=int2(threadID.xy)+1;
    if(any(p>=size))return;
    float3 lowS=1e20f,highS=-1e20f,lowD=1e20f,highD=-1e20f;
    [unroll]for(int dy=-1;dy<=1;++dy)[unroll]for(int dx=-1;dx<=1;++dx)
    {
        if(dx==0&&dy==0)continue;
        const int2 q=l+int2(dx,dy);const float2 age=sAge[q.y][q.x];
        if(age.x>0){lowS=min(lowS,sReferenceS[q.y][q.x]);highS=max(highS,sReferenceS[q.y][q.x]);}
        if(age.y>0){lowD=min(lowD,sReferenceD[q.y][q.x]);highD=max(highD,sReferenceD[q.y][q.x]);}
    }
    const float2 age=sAge[l.y][l.x];
    const float3 referenceS=all(lowS<=highS)?clamp(sReferenceS[l.y][l.x],lowS,highS):sReferenceS[l.y][l.x];
    const float3 referenceD=all(lowD<=highD)?clamp(sReferenceD[l.y][l.x],lowD,highD):sReferenceD[l.y][l.x];
    LevelSpec[p]=float4(age.x>0?referenceS-RRSpec[p].rgb:0,sInnovation[l.y][l.x].x);
    LevelDiff[p]=float4(age.y>0?referenceD-RRDiff[p].rgb:0,sInnovation[l.y][l.x].y);
    LevelMetadata[p]=float4(age,sWeights[l.y][l.x]);
}
