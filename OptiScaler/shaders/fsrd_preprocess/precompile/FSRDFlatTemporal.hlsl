#include "FSRDFlatTemporalCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 14)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float4> InReference : register(t0);
Texture2D<float4> InComposed : register(t1);
Texture2D<float4> InNormals : register(t2);
Texture2D<float> InDepth : register(t3);
Texture2D<float4> InMotion : register(t4);
Texture2D<float4> InSpecular : register(t5);
Texture2D<float4> InDiffuse : register(t6);
Texture2D<float4> InSpecularAlbedo : register(t7);
Texture2D<float4> InDiffuseAlbedo : register(t8);
Texture2D<float4> InSkip : register(t9);
ByteAddressBuffer InTiles : register(t10);
Texture2DArray<float4> HistoryReference : register(t11);
Texture2DArray<float4> HistoryMotionDepth : register(t12);
Texture2DArray<float4> HistoryNormalLP : register(t13);
RWTexture2D<float4> OutReference : register(u0);
RWTexture2D<float4> OutNormalLP : register(u1);
RWTexture2D<float2> OutDiagnostics : register(u2);

// Original reference log/sigma and current RR/raw luma/mask. 11,200 bytes.
groupshared float4 WindowReference[20][20];
groupshared float3 WindowLight[20][20];

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

bool HistoryTap(int2 p,uint slice,float expectedDepth,float3 currentNormal,
                out float4 reference,out float4 motionDepth,out float4 normalLP)
{
    reference=0;motionDepth=0;normalLP=0;
    if (!TemporalInBounds(p)) return false;
    reference=HistoryReference.Load(int4(p,slice,0));
    motionDepth=HistoryMotionDepth.Load(int4(p,slice,0));
    normalLP=HistoryNormalLP.Load(int4(p,slice,0));
    const float3 normal=OctahedralDecode(DecodeTemporalNormalUV(normalLP.xy));
    return reference.a>=0.0f && all(isfinite(motionDepth)) && all(isfinite(normalLP)) &&
        abs(motionDepth.z-expectedDepth)<=0.03f*max(abs(expectedDepth),1e-3f) && dot(normal,currentNormal)>0.95f;
}

[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 group:SV_GroupID,uint3 local:SV_GroupThreadID)
{
#if defined(FSRD_FLAT_TEST_DIRECT) && FSRD_FLAT_TEST_DIRECT
    const int2 origin=int2(group.xy)*8;
#else
    const uint tile=group.x+65535u*group.y;
    if (tile>=InTiles.Load(0)) return;
    const int2 origin=int2(InTiles.Load2(16+tile*8))*8;
#endif
    const uint lane=local.y*8+local.x;
    for (uint i=lane;i<400;i+=64)
    {
        const int2 q=origin+int2(i%20,i/20)-6;
        const bool valid=FlatPixel(q);
        const float4 r=valid ? InReference[q] : float4(0,0,0,-1);
        WindowReference[i/20][i%20]=valid ? float4(log(max(r.rgb,Epsilon)),r.a) : float4(0,0,0,-1);
        WindowLight[i/20][i%20]=valid ? float3(GetLuminance(SanitizeRadiance(InComposed[q].rgb)),GetLuminance(RawColor(q)),1) : 0;
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 p=origin+int2(local.xy),w=int2(local.xy)+6;
    if (!TemporalInBounds(p)) return;
    OutDiagnostics[p]=0;
    if (!FlatPixel(p)) return;
    const float4 original=InReference[p];
    const float4 motion=InMotion[p];
    const float z=InDepth[p];
    const float2 uv=InNormals[p].xy;
    float3 lpSum=0;float rrCount=0;float rrSum=0;
    [loop] for(int y=-6;y<=6;++y) [loop] for(int x=-6;x<=6;++x)
    {
        const float3 tap=WindowLight[w.y+y][w.x+x];
        lpSum.y+=tap.y;lpSum.z+=tap.z;
        if(abs(x)<=4 && abs(y)<=4) { rrSum+=tap.x;rrCount+=tap.z; }
    }
    const float2 currentLP=float2(rrSum/max(rrCount,1.0f),lpSum.y/max(lpSum.z,1.0f));
    // Round the current LP through FP16 exactly as the stored resource does.
    const float2 currentHalfLP=f16tof32(f32tof16(clamp(currentLP,0.0f,65504.0f)));
    OutNormalLP[p]=float4(motion.w>=0.5f ? uv.x : -2.0f-uv.x,uv.y,currentHalfLP);
    OutReference[p]=original;
    const float2 initialMotion=motion.xy*FullRenderSize+JitterDelta;
    const bool safe=all(isfinite(float4(initialMotion,z,motion.z))) &&
        all(abs(float4(initialMotion,z,motion.z))<=65504.0f);
    const float speed=length(motion.xy*FullRenderSize);
    const float motionGate=1.0f-smoothstep(MotionStart,max(MotionEnd,MotionStart+1e-4f),speed);
    if(HistoryCount==0 || HistoryLength==0 || TemporalStrength<=0 || !(motion.w>=0.5f) || !safe || motionGate<=0) return;
    const float3 current=WindowReference[w.y][w.x].rgb;
    float3 mean=0,square=0;float totalSpatial=0;
    [unroll] for(int sy=-1;sy<=1;++sy) [unroll] for(int sx=-1;sx<=1;++sx)
    {
        const float4 tap=WindowReference[w.y+sy][w.x+sx];
        if(tap.a>=0) {mean+=tap.rgb;square+=tap.rgb*tap.rgb;totalSpatial+=1;}
    }
    mean/=max(totalSpatial,1.0f);
    const float sigma=clamp(original.a/max(GetLuminance(original.rgb),0.01f),0.012f,0.65f);
    const float3 spread=sqrt(max(square/max(totalSpatial,1.0f)-mean*mean,0.0f)+sigma*sigma);
    const float3 lo=min(mean-2.5f*spread,current),hi=max(mean+2.5f*spread,current);
    const float3 normal=OctahedralDecode(uv);
    float2 position=float2(p)+initialMotion;
    float expected=z+motion.z;
    float3 sum=current;float total=1,used=0,accepted=0;
    const uint n=min(min(HistoryCount,HistoryLength),6u);
    [loop] for(uint age=0;age<n;++age)
    {
        if(!all(isfinite(position)) || !isfinite(expected)) break;
        const uint slice=(HistoryHead+5u-age)%6u;
        const int2 base=int2(floor(position));
        const float2 fraction=position-float2(base);
        float4 oldMotion=0;float2 oldLP=0;float geometry=0,motionValid=0;
        [unroll] for(int by=0;by<2;++by) [unroll] for(int bx=0;bx<2;++bx)
        {
            const float weight=(bx!=0 ? fraction.x : 1.0f-fraction.x)*(by!=0 ? fraction.y : 1.0f-fraction.y);
            float4 r,md,nl;
            if(HistoryTap(base+int2(bx,by),slice,expected,normal,r,md,nl))
            {
                geometry+=weight;oldMotion+=md*weight;oldLP+=nl.zw*weight;
                if(nl.x>=-1.0f) motionValid+=weight;
            }
        }
        if(geometry<0.999f) break;
        oldMotion/=max(geometry,1e-6f);oldLP/=max(geometry,1e-6f);
        const float2 relative=abs(oldLP-currentHalfLP)/(0.5f*(abs(oldLP)+abs(currentHalfLP))+0.01f);
        const float change=max(smoothstep(0.065f,0.23f,relative.x),smoothstep(0.09f,0.28f,relative.y));
        float weight=pow(1.0f-change,3.0f)*exp(-float(age)/max(HistoryDecay,1e-3f))*motionGate;
        if(CenterSigma>0) { const float2 delta=position-round(position);weight*=exp(-dot(delta,delta)/(2.0f*CenterSigma*CenterSigma)); }
        if(change>=0.92f) weight=0;
        if(weight>0)
        {
            float3 value=0;float signedWeight=0,absoluteValid=0,absoluteAll=0;
            [unroll] for(int cy=-1;cy<=2;++cy) [unroll] for(int cx=-1;cx<=2;++cx)
            {
                const float cw=CubicWeight(fraction.x-float(cx))*CubicWeight(fraction.y-float(cy));
                float4 r,md,nl;
                const bool valid=HistoryTap(base+int2(cx,cy),slice,expected,normal,r,md,nl);
                absoluteAll+=abs(cw);
                if(valid) { value+=r.rgb*cw;signedWeight+=cw;absoluteValid+=abs(cw); }
            }
            if(absoluteValid>=0.99f*max(absoluteAll,1e-6f) && signedWeight>0.25f)
            {
                value=clamp(value/max(signedWeight,1e-6f),lo,hi);
                sum+=weight*value;total+=weight;used+=weight;accepted+=1;
            }
        }
        if(motionValid<0.999f) break;
        expected+=oldMotion.w;position+=oldMotion.xy;
    }
    if(used>0)
    {
        const float3 recovered=exp(clamp(sum/total,-12.0f,12.0f));
        const float3 result=lerp(original.rgb,recovered,saturate(TemporalStrength));
        if(all(isfinite(result))) OutReference[p]=float4(SanitizeRadiance(result),original.a);
    }
    OutDiagnostics[p]=float2(accepted,used);
}
