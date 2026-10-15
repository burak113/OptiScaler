// Pass3: innovation-noise gated Laplacian band, local mean removal/collapse.
// Level0 writes two OWNED demodulated lobes; title alpha/composition are absent.
#include "FSRDNrdLobeRecoveryCommon.hlsli"
#ifndef NRD_RECOVERY_HALF_OUTPUT
#define NRD_RECOVERY_HALF_OUTPUT 1
#endif
#define MainRS "RootFlags(0),CBV(b0),DescriptorTable(SRV(t0,numDescriptors=18)),DescriptorTable(UAV(u0,numDescriptors=5))"
Texture2D<float4> ThisSpec : register(t0);
Texture2D<float4> ThisDiff : register(t1);
Texture2D<float4> ThisMetadata : register(t2);
Texture2D<float4> CoarseSpec : register(t3);
Texture2D<float4> CoarseDiff : register(t4);
Texture2D<float4> CoarseMetadata : register(t5);
Texture2D<float4> CoarseCorrectionS : register(t6);
Texture2D<float4> CoarseCorrectionD : register(t7);
Texture2D<float4> PrevNoise : register(t8); // varianceSpec,varianceDiff,ageSpec,ageDiff
Texture2D<float4> Motion : register(t9);
Texture2D<float> Depth : register(t10);
Texture2D<float4> Normal : register(t11);
Texture2D<float4> RRSpec : register(t12);
Texture2D<float4> RRDiff : register(t13);
Texture2D<float4> NoisySpec : register(t14);
Texture2D<float4> NoisyDiff : register(t15);
Texture2D<uint4> PrevGeometry : register(t16);
Texture2D<float4> FullMetadata : register(t17);
RWTexture2D<float4> OutCorrectionS : register(u0);
RWTexture2D<float4> OutCorrectionD : register(u1);
RWTexture2D<float4> OutNoise : register(u2);
RWTexture2D<float4> OutSpec : register(u3);
RWTexture2D<float4> OutDiff : register(u4);

groupshared float4 sBandS[14][14],sBandD[14][14];
groupshared float3 sCorrectionS[12][12],sCorrectionD[12][12];
groupshared float3 sDownS[6][6],sDownD[6][6];

float2 MinCoarseAge(float2 position,int2 size)
{
    position=clamp(position,0.0f,float2(size-1));
    const int2 base=int2(floor(position)),other=min(base+1,size-1);
    const float2 f=position-base;float2 age=1e20f;
    [unroll]for(int t=0;t<4;++t)
    {
        const int2 off=int2(t&1,t>>1),q=int2(off.x?other.x:base.x,off.y?other.y:base.y);
        const float w=(off.x?f.x:1-f.x)*(off.y?f.y:1-f.y);
        if(w>0)age=min(age,CoarseMetadata[q].xy);
    }
    return age;
}
void ReadNoise(float2 position,float expectedDepth,float4 nr,
               out float2 variance,out float2 age,out bool2 valid)
{
    variance=0;age=1e20f;float2 weight=0;
    const int2 size=int2(LevelSize.xy),base=int2(floor(position));
    const float2 f=position-base;const float scale=float(1u<<Control.y);
    [unroll]for(int t=0;t<4;++t)
    {
        const int2 off=int2(t&1,t>>1),q=base+off;
        if(any(q<0)||any(q>=size))continue;
        const int2 full=min(int2((float2(q)+.5f)*scale),int2(FullSize.xy)-1);
        const uint4 geometry=PrevGeometry[full];
        const float4 noise=PrevNoise[q];
        if(!NrdRecoverySameGeometry(asfloat(geometry.x),NrdUnpackNormal(geometry.y),expectedDepth,nr)||!all(isfinite(noise)))continue;
        const float w=(off.x?f.x:1-f.x)*(off.y?f.y:1-f.y);
        const bool2 counted=(noise.zw>0)&&(w>0);
        const float2 weights=float2(counted.x?w:0,counted.y?w:0);
        variance+=weights*noise.xy;weight+=weights;
        age=min(age,float2(counted.x?noise.z:1e20f,counted.y?noise.w:1e20f));
    }
    variance/=max(weight,1e-20f);valid=weight>=Surface.w;
    age=float2(valid.x?age.x:0,valid.y?age.y:0);
}
float3 Bilinear3(float3 a,float3 b,float3 c,float3 d,float2 f)
{
    return lerp(lerp(a,b,f.x),lerp(c,d,f.x),f.y);
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 threadID:SV_GroupThreadID,uint3 groupID:SV_GroupID)
{
    const uint thread=threadID.y*8+threadID.x;
    const int2 tile=int2(groupID.xy)*8,size=int2(LevelSize.xy),coarseSize=int2(LevelSize.zw);
    for(uint i=thread;i<196;i+=64)
    {
        const int2 p=clamp(tile-3+int2(i%14,i/14),0,size-1);
        const float2 coarse=(float2(p)+.5f)*.5f-.5f;
        sBandS[i/14][i%14]=ThisSpec[p]-NrdLoadLinear(CoarseSpec,coarse,coarseSize);
        sBandD[i/14][i%14]=ThisDiff[p]-NrdLoadLinear(CoarseDiff,coarse,coarseSize);
    }
    GroupMemoryBarrierWithGroupSync();
    const float scale=float(1u<<Control.y);
    for(uint i=thread;i<144;i+=64)
    {
        const int2 l=int2(i%12,i/12),r=tile-2+l,p=clamp(r,0,size-1),b=p-(tile-3);
        float2 energy=0;
        [unroll]for(int dy=-1;dy<=1;++dy)[unroll]for(int dx=-1;dx<=1;++dx)
        {
            const float2 v=float2(NrdRecoveryLuma(sBandS[b.y+dy][b.x+dx].rgb),NrdRecoveryLuma(sBandD[b.y+dy][b.x+dx].rgb));
            energy+=v*v;
        }
        energy*=1.0f/9.0f;
        const float4 bandS=sBandS[b.y][b.x],bandD=sBandD[b.y][b.x],metadata=ThisMetadata[p];
        const float2 coarseAge=MinCoarseAge((float2(p)+.5f)*.5f-.5f,coarseSize);
        const bool2 eligible=(metadata.xy>0)&&(coarseAge>0);
        const float2 centre=(float2(p)+.5f)*scale;
        const int2 full=min(int2(centre),int2(FullSize.xy)-1);
        const float4 mv=Motion[full],nr=Normal[full];const float z=Depth[full];
        float2 variance=float2(bandS.a*bandS.a,bandD.a*bandD.a),noiseAge=float2(eligible.x?1:0,eligible.y?1:0);
        if(NrdRecoveryFlag(NRD_RECOVERY_HISTORY)&&all(isfinite(mv))&&mv.w>=.5f)
        {
            float2 oldVariance,oldAge;bool2 valid;
            ReadNoise((centre+mv.xy*FullSize.xy)/scale-.5f,z+mv.z,nr,oldVariance,oldAge,valid);
            valid=valid&&eligible;
            const float2 rate=max(rcp(oldAge+1.0f),Confidence.y);
            variance=float2(valid.x?oldVariance.x+rate.x*(variance.x-oldVariance.x):variance.x,
                            valid.y?oldVariance.y+rate.y*(variance.y-oldVariance.y):variance.y);
            noiseAge=float2(eligible.x?(valid.x?min(oldAge.x+1,1024.0f):1):0,
                            eligible.y?(valid.y?min(oldAge.y+1,1024.0f):1):0);
        }
        const float2 noise=max(variance*metadata.zw/(1.0f+metadata.zw),1e-20f);
        const float margin=Control.y>=2?smoothstep(4.0f,20.0f,length(mv.xy*FullSize.xy)):0;
        const float threshold=Temporal.y*(1.0f+.5f*float(Control.y*Control.y)*margin);
        const float2 wiener=max(0.0f,1.0f-threshold*noise/max(energy,1e-30f));
        const bool2 mature=eligible&&(metadata.xy>=Temporal.z)&&(noiseAge>=4.0f)&&(rcp(max(metadata.zw,1e-12f))>=Confidence.x);
        sCorrectionS[l.y][l.x]=mature.x?bandS.rgb*wiener.x*LobeStrength.x:0;
        sCorrectionD[l.y][l.x]=mature.y?bandD.rgb*wiener.y*LobeStrength.y:0;
        if(all(l>=2)&&all(l<10)&&all(r==p))OutNoise[p]=float4(variance,noiseAge);
    }
    GroupMemoryBarrierWithGroupSync();
    if(thread<36)
    {
        const int2 c=int2(thread%6,thread/6),f=2*c;
        sDownS[c.y][c.x]=.25f*(sCorrectionS[f.y][f.x]+sCorrectionS[f.y][f.x+1]+sCorrectionS[f.y+1][f.x]+sCorrectionS[f.y+1][f.x+1]);
        sDownD[c.y][c.x]=.25f*(sCorrectionD[f.y][f.x]+sCorrectionD[f.y][f.x+1]+sCorrectionD[f.y+1][f.x]+sCorrectionD[f.y+1][f.x+1]);
    }
    if(NrdRecoveryFlag(NRD_RECOVERY_FINAL))
    {
        for(uint i=thread;i<100;i+=64)
        {
            const int2 p=clamp(tile-1+int2(i%10,i/10),0,int2(FullSize.xy)-1);
            sBandS[i/10][i%10]=RRSpec[p];sBandD[i/10][i%10]=RRDiff[p];
        }
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 p=tile+int2(threadID.xy),local=int2(threadID.xy)+2;
    if(any(p>=size))return;
    const float2 coordinate=clamp((float2(p)+.5f)*.5f-.5f,0.0f,float2(coarseSize-1));
    const int2 a=int2(floor(coordinate)),b=min(a+1,coarseSize-1),origin=tile/2-1,l0=a-origin,l1=b-origin;
    const float2 f=coordinate-a;
    float3 spec=sCorrectionS[local.y][local.x]-Bilinear3(sDownS[l0.y][l0.x],sDownS[l0.y][l1.x],sDownS[l1.y][l0.x],sDownS[l1.y][l1.x],f);
    float3 diff=sCorrectionD[local.y][local.x]-Bilinear3(sDownD[l0.y][l0.x],sDownD[l0.y][l1.x],sDownD[l1.y][l0.x],sDownD[l1.y][l1.x],f);
    if(!NrdRecoveryFlag(NRD_RECOVERY_COARSEST))
    {
        spec+=NrdLoadLinear(CoarseCorrectionS,coordinate,coarseSize).rgb;
        diff+=NrdLoadLinear(CoarseCorrectionD,coordinate,coarseSize).rgb;
    }
    OutCorrectionS[p]=float4(spec,0);OutCorrectionD[p]=float4(diff,0);
    if(!NrdRecoveryFlag(NRD_RECOVERY_FINAL))return;
    const int2 l=int2(threadID.xy)+1;float3 meanS=0,squareS=0,meanD=0,squareD=0;
    [unroll]for(int dy=-1;dy<=1;++dy)[unroll]for(int dx=-1;dx<=1;++dx)
    {
        const float3 s=sBandS[l.y+dy][l.x+dx].rgb,d=sBandD[l.y+dy][l.x+dx].rgb;
        meanS+=s;squareS+=s*s;meanD+=d;squareD+=d*d;
    }
    meanS/=9.0f;meanD/=9.0f;squareS=max(squareS/9.0f-meanS*meanS,0);squareD=max(squareD/9.0f-meanD*meanD,0);
    const float4 rrS=RRSpec[p],rrD=RRDiff[p],meta=FullMetadata[p];
    const bool2 supported=bool2(meta.x>=Temporal.z&&any(NoisySpec[p].rgb!=rrS.rgb),
                               meta.y>=Temporal.z&&any(NoisyDiff[p].rgb!=rrD.rgb));
    spec=supported.x&&all(isfinite(spec))?NrdRecoveryLocalAnchor(spec,rrS.rgb,meanS,squareS,LobeStrength.z,LobeStrength.w):0;
    diff=supported.y&&all(isfinite(diff))?NrdRecoveryLocalAnchor(diff,rrD.rgb,meanD,squareD,LobeStrength.z,LobeStrength.w):0;
    float4 outputS=float4(clamp(rrS.rgb+spec,0.0f,65504.0f),rrS.a),outputD=float4(clamp(rrD.rgb+diff,0.0f,65504.0f),rrD.a);
#if NRD_RECOVERY_HALF_OUTPUT
    outputS.rgb=NrdRoundMaterialHalfNearestEven(float4(outputS.rgb,0)).rgb;
    outputD.rgb=NrdRoundMaterialHalfNearestEven(float4(outputD.rgb,0)).rgb;
#endif
    OutSpec[p]=outputS;OutDiff[p]=outputD;
}
