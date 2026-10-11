#include "FSRDFlatTemporalCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 10)), DescriptorTable(UAV(u0, numDescriptors = 2))"
Texture2D<float4> InReference : register(t0);
Texture2D<float4> InNormals : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InMotion : register(t3);
Texture2D<float4> InSkip : register(t4);
ByteAddressBuffer InTiles : register(t5);
Texture2D<float2> InLP : register(t6);
Texture2DArray<float4> HistoryReference : register(t7);
Texture2DArray<uint2> HistoryAux : register(t8);
Texture2DArray<float2> HistoryLP : register(t9);
RWTexture2D<float4> OutReference : register(u0);
RWTexture2D<float2> OutDiagnostics : register(u1);

// Original reference log/sigma of the tile and a one-pixel ring. 1,600 bytes.
groupshared float4 WindowReference[10][10];

bool FlatPixel(int2 p)
{
    if (!TemporalInBounds(p)) return false;
    const float z=InDepth[p];
    return abs(InNormals[p].a-1.0f/3.0f)<0.1f && InSkip[p].a!=-1.0f && isfinite(z) && abs(z)>1e-5f;
}

float2 CurrentLP(float2 position)
{
    int2 b0,b1;float2 f;LPFootprint(position,b0,b1,f);
    return BlendLP(InLP[b0],InLP[int2(b1.x,b0.y)],InLP[int2(b0.x,b1.y)],InLP[b1],f);
}

float2 HistoryLPAt(float2 position,uint slice)
{
    int2 b0,b1;float2 f;LPFootprint(position,b0,b1,f);
    return BlendLP(HistoryLP.Load(int4(b0,slice,0)),HistoryLP.Load(int4(b1.x,b0.y,slice,0)),
                   HistoryLP.Load(int4(b0.x,b1.y,slice,0)),HistoryLP.Load(int4(b1,slice,0)),f);
}

// Bilinear footprint: depth from the reference alpha, motion/normal from the aux.
bool HistoryTap(int2 p,uint slice,float expectedDepth,float3 currentNormal,out float3 motionDepth,out bool motionValid)
{
    motionDepth=0;motionValid=false;
    if (!TemporalInBounds(p)) return false;
    const float depth=HistoryReference.Load(int4(p,slice,0)).a;
    const uint2 aux=HistoryAux.Load(int4(p,slice,0));
    motionDepth=UnpackTemporalMotion(aux);motionValid=UnpackTemporalMotionValid(aux);
    return depth!=0.0f && all(isfinite(motionDepth)) &&
        abs(depth-expectedDepth)<=0.03f*max(abs(expectedDepth),1e-3f) &&
        dot(OctahedralDecode(UnpackTemporalNormal(aux)),currentNormal)>0.95f;
}

// Cubic taps: depth-only validation from the reference alpha (the bilinear footprint already checked normals).
bool CubicTap(int2 p,uint slice,float expectedDepth,out float3 logReference)
{
    logReference=0;
    if (!TemporalInBounds(p)) return false;
    const float4 r=HistoryReference.Load(int4(p,slice,0));
    logReference=r.rgb;
    return r.a!=0.0f && abs(r.a-expectedDepth)<=0.03f*max(abs(expectedDepth),1e-3f);
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
    for (uint i=lane;i<100;i+=64)
    {
        const int2 q=origin+int2(i%10,i/10)-1;
        const bool valid=FlatPixel(q);
        const float4 r=valid ? InReference[q] : float4(0,0,0,-1);
        WindowReference[i/10][i%10]=valid ? float4(log(max(r.rgb,Epsilon)),r.a) : float4(0,0,0,-1);
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 p=origin+int2(local.xy),w=int2(local.xy)+1;
    if (!TemporalInBounds(p)) return;
    OutDiagnostics[p]=0;
    if (!FlatPixel(p)) return;
    const float4 original=InReference[p];
    const float4 motion=InMotion[p];
    const float z=InDepth[p];
    const float2 currentLP=CurrentLP(float2(p));
    // Alpha: residual deviation of the temporal mean (log units) once the history weight reaches
    // kFullHistory, else -1 - confidence (no or thin history: moving reflections, disocclusion).
    OutReference[p]=float4(original.rgb,-1.0f);
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
    const float3 normal=OctahedralDecode(InNormals[p].xy);
    float2 position=float2(p)+initialMotion;
    float expected=z+motion.z;
    float3 sum=current;float total=1,used=0,accepted=0;
    const float currentL=dot(current,1.0f/3.0f);
    float sumL2=currentL*currentL,sumW2=1.0f;
    const uint n=min(min(HistoryCount,HistoryLength),6u);
    [loop] for(uint age=0;age<n;++age)
    {
        if(!all(isfinite(position)) || !isfinite(expected)) break;
        const uint slice=(HistoryHead+5u-age)%6u;
        const int2 base=int2(floor(position));
        const float2 fraction=position-float2(base);
        float3 oldMotion=0;float geometry=0,motionValid=0;
        [unroll] for(int by=0;by<2;++by) [unroll] for(int bx=0;bx<2;++bx)
        {
            const float weight=(bx!=0 ? fraction.x : 1.0f-fraction.x)*(by!=0 ? fraction.y : 1.0f-fraction.y);
            float3 md;bool mv;
            if(HistoryTap(base+int2(bx,by),slice,expected,normal,md,mv))
            {
                geometry+=weight;oldMotion+=md*weight;
                if(mv) motionValid+=weight;
            }
        }
        if(geometry<0.999f) break;
        oldMotion/=max(geometry,1e-6f);
        const float2 oldLP=HistoryLPAt(position,slice);
        const float2 relative=abs(oldLP-currentLP)/(0.5f*(abs(oldLP)+abs(currentLP))+0.01f);
        const float change=oldLP.x<0.0f || currentLP.x<0.0f ? 1.0f :
            max(smoothstep(0.065f,0.23f,relative.x),smoothstep(0.09f,0.28f,relative.y));
        float weight=pow(1.0f-change,3.0f)*exp(-float(age)/max(HistoryDecay,1e-3f))*motionGate;
        if(CenterSigma>0) { const float2 delta=position-round(position);weight*=exp(-dot(delta,delta)/(2.0f*CenterSigma*CenterSigma)); }
        if(change>=0.92f) weight=0;
        if(weight>0)
        {
            float3 value=0;float signedWeight=0,absoluteValid=0,absoluteAll=0;
            [unroll] for(int cy=-1;cy<=2;++cy) [unroll] for(int cx=-1;cx<=2;++cx)
            {
                const float cw=CubicWeight(fraction.x-float(cx))*CubicWeight(fraction.y-float(cy));
                float3 r;
                const bool valid=CubicTap(base+int2(cx,cy),slice,expected,r);
                absoluteAll+=abs(cw);
                if(valid) { value+=r*cw;signedWeight+=cw;absoluteValid+=abs(cw); }
            }
            if(absoluteValid>=0.99f*max(absoluteAll,1e-6f) && signedWeight>0.25f)
            {
                value=clamp(value/max(signedWeight,1e-6f),lo,hi);
                sum+=weight*value;total+=weight;used+=weight;accepted+=1;
                const float l=dot(value,1.0f/3.0f);sumL2+=weight*l*l;sumW2+=weight*weight;
            }
        }
        if(motionValid<0.999f) break;
        expected+=oldMotion.z;position+=oldMotion.xy;
    }
    if(used>0)
    {
        const float3 recovered=exp(clamp(sum/total,-12.0f,12.0f));
        const float3 result=lerp(original.rgb,recovered,saturate(TemporalStrength));
        // Weighted spread of the accepted log samples around their mean, scaled to the mean's own deviation.
        const float meanL=dot(sum,1.0f/3.0f)/total;
        const float residual=sqrt(max(sumL2/total-meanL*meanL,0.0f)*sumW2)/total;
        const float alpha=used<kFullHistory ? -1.0f-used/kFullHistory : (isfinite(residual) ? residual : 0.0f);
        if(all(isfinite(result))) OutReference[p]=float4(SanitizeRadiance(result),alpha);
    }
    OutDiagnostics[p]=float2(accepted,used);
}
