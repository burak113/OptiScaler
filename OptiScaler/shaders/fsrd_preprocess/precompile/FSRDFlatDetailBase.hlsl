#include "FSRDFlatDetailBindings.hlsli"
// Combine reconstructed reference texture with RR lighting. The 21x21, stride-2
// bilateral ratio uses a flat-normalized sigma-1 Gaussian log-luma guide. A plain
// ratio of sums mixed bright-letter gains into dark backgrounds and drew a rim.
// The guide is local LDS work: no extra texture, pass, or reference-alpha use.
// Gates retain Base semantics: each neighbourhood uses the centre pixel's light.
// Noise is the lower quartile of quiet reference pairs, scaled by that light.
// Anchor bounds the target with RR's local spread; Mix monotonically opens gates.
static const int kWindow = 10;
static const int kSpan = 8 + 2 * kWindow;
static const int kGaussianRadius = 3;
static const int kReferenceRadius = kWindow + kGaussianRadius;
static const int kReferenceSpan = 8 + 2 * kReferenceRadius;
static const float kRangeSigma = 0.35f;
static const float kQuietToNoise = 3.0f;
static const float Gaussian[7] = {
    0.0044330482f, 0.0540055826f, 0.2420362294f, 0.3990502797f,
    0.2420362294f, 0.0540055826f, 0.0044330482f
};
// 26,848 LDS bytes per group. Reference alpha: 0=valid, -1=non-flat,
// -2=outside the image but edge-clamped to a flat pixel for Gaussian extension.
groupshared uint2 WindowRR[kSpan][kSpan];
groupshared uint2 WindowReference[kReferenceSpan][kReferenceSpan];
groupshared float2 GaussianHorizontal[kReferenceSpan][kSpan];
groupshared float LogLuma[kSpan][kSpan];
groupshared float QuietPair[12][12];
float4 Ref(int2 w) { return FlatUnpack(WindowReference[w.y+kGaussianRadius][w.x+kGaussianRadius]); }
float3 Rr(int2 w) { return FlatUnpack(WindowRR[w.y][w.x]).rgb; }
float2 GuideSample(int y, int x)
{
    const float4 value=FlatUnpack(WindowReference[y][x]);
    return value.a == -1.0f ? 0.0f : float2(GetLuminance(value.rgb),1.0f);
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint tile=group.x+65535u*group.y;
    if (tile>=InTiles.Load(0)) return;
    const int2 origin=FlatOrigin(tile);
    const uint lane=local.y*8+local.x;
    for (uint i=lane;i<uint(kReferenceSpan*kReferenceSpan);i+=64)
    {
        const int2 q=origin+int2(i%kReferenceSpan,i/kReferenceSpan)-kReferenceRadius;
        const int2 safe=clamp(q,int2(0,0),int2(DstTexSize.xy)-1);
        const bool valid=FlatPixel(safe);
        const bool inside=all(q>=0) && all(q<int2(DstTexSize.xy));
        const float tag=valid ? (inside ? 0.0f : -2.0f) : -1.0f;
        WindowReference[i/kReferenceSpan][i%kReferenceSpan]=
            FlatPack(float4(valid ? SanitizeRadiance(InReference[safe].rgb) : 0.0f,tag));
    }
    for (uint i=lane;i<uint(kSpan*kSpan);i+=64)
    {
        const int2 q=origin+int2(i%kSpan,i/kSpan)-kWindow;
        WindowRR[i/kSpan][i%kSpan]=FlatPack(FlatPixel(q) ?
            float4(SanitizeRadiance(InComposed[q].rgb),0.0f) : 0.0f);
    }
    GroupMemoryBarrierWithGroupSync();
    for (uint i=lane;i<uint(kReferenceSpan*kSpan);i+=64)
    {
        const int y=i/kSpan, x=i%kSpan;
        float2 sum=0.0f;
        [unroll] for (int k=0;k<7;++k) sum+=Gaussian[k]*GuideSample(y,x+k);
        GaussianHorizontal[y][x]=sum;
    }
    GroupMemoryBarrierWithGroupSync();
    for (uint i=lane;i<uint(kSpan*kSpan);i+=64)
    {
        const int y=i/kSpan, x=i%kSpan;
        float2 sum=0.0f;
        [unroll] for (int k=0;k<7;++k) sum+=Gaussian[k]*GaussianHorizontal[y+k][x];
        LogLuma[y][x]=log(max(sum.x/max(sum.y,1e-6f),1e-5f));
    }
    for (uint j=lane;j<144;j+=64)
    {
        const int2 w=int2(j%12,j/12)+kWindow-2;
        const float4 c=Ref(w);
        float quiet=-1.0f;
        if (c.a>=0)
        {
            const int2 directions[4]={int2(1,0),int2(0,1),int2(1,1),int2(1,-1)};
            [unroll] for (uint d=0;d<4;++d)
            {
                const float4 r=Ref(w+directions[d]);
                if (r.a<0) continue;
                const float3 delta=c.rgb-r.rgb;
                const float value=dot(delta,delta)/6.0f;
                quiet=quiet<0 ? value : min(quiet,value);
            }
        }
        QuietPair[j/12][j%12]=quiet;
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 p=origin+int2(local.xy), w=int2(local.xy)+kWindow, s=int2(local.xy)+2;
    if (!FlatPixel(p)) return;
    float3 sumRR=0, sumReference=0;
    const float centreLogLuma=LogLuma[w.y][w.x];
    for (int y=-kWindow;y<=kWindow;y+=2) for (int x=-kWindow;x<=kWindow;x+=2)
    {
        const int2 q=w+int2(x,y);
        const float4 value=Ref(q);
        if (value.a<0.0f) continue;
        const float delta=LogLuma[q.y][q.x]-centreLogLuma;
        const float bilateral=exp(-(delta*delta)/(2.0f*kRangeSigma*kRangeSigma));
        sumRR+=bilateral*Rr(q);
        sumReference+=bilateral*value.rgb;
    }
    const float3 light=clamp(sumRR/max(sumReference,1e-9f),0.0f,8.0f);
    const float lightScale=dot(light,1.0f/3.0f);
    const float3 rr=Rr(w), reference=InReference[p].rgb, target=reference*light;
    // Noise: the lower quartile of the quiet pairs over 5x5 (the 7 smallest of at most 25 kept in order).
    float smallest[7]={1e30f,1e30f,1e30f,1e30f,1e30f,1e30f,1e30f};
    uint count=0;
    for (int qy=-2;qy<=2;++qy) for (int qx=-2;qx<=2;++qx)
    {
        float v=QuietPair[s.y+qy][s.x+qx];
        if (v<0) continue;
        ++count;
        [unroll] for (uint n=0;n<7;++n) { const float lo=min(smallest[n],v); v=max(smallest[n],v); smallest[n]=lo; }
    }
    float quartile=smallest[0];
    [unroll] for (uint n=0;n<7;++n) if (n==(max(count,1u)-1u)/4u) quartile=smallest[n];
    const float noise=count>=9u ? kQuietToNoise*sqrt(quartile)*lightScale : 0.0f;
    // 9x9 regional amplitude of the target and its RMS difference from RR.
    float3 mean=0, square=0;
    float difference=0, total=0;
    for (int ry=-4;ry<=4;++ry) for (int rx=-4;rx<=4;++rx)
    {
        const int2 q=w+int2(rx,ry);
        const float4 v=Ref(q);
        if (v.a<0) continue;
        const float3 t=v.rgb*light, d=t-Rr(q);
        mean+=t; square+=t*t; difference+=dot(d,d)/3.0f; total+=1;
    }
    mean/=max(total,1.0f);
    const float amplitude=sqrt(max(dot(square/max(total,1.0f)-mean*mean,1.0f/3.0f),0.0f));
    const float rmsDifference=sqrt(max(difference/max(total,1.0f),0.0f));
    const float snr=amplitude/max(noise,1e-5f);
    const float structure=smoothstep(1.2f,1.8f,snr)*
        max(smoothstep(0.22f,0.28f,amplitude/max(noise+GetLuminance(mean),1e-5f)),smoothstep(4.0f,8.0f,snr));
    const float agreement=1.0f-smoothstep(0.8f,1.2f,rmsDifference/max(noise,1e-5f));
    float weight=structure*(1.0f-agreement);
    weight=saturate(Strength)*(weight+saturate(Mix)*(1.0f-weight));
    // RR's 5x5 binomial moments and the 5x5 target range.
    const float binomial[5]={1,4,6,4,1};
    float3 low=0, lowSquare=0, targetMin=target, targetMax=target;
    float lowTotal=0;
    for (int by=-2;by<=2;++by) for (int bx=-2;bx<=2;++bx)
    {
        const int2 q=w+int2(bx,by);
        const float4 v=Ref(q);
        if (v.a<0) continue;
        const float b=binomial[bx+2]*binomial[by+2];
        const float3 r=Rr(q);
        low+=b*r; lowSquare+=b*r*r; lowTotal+=b;
        targetMin=min(targetMin,v.rgb*light); targetMax=max(targetMax,v.rgb*light);
    }
    low/=max(lowTotal,1e-6f);
    const float3 spread=sqrt(max(lowSquare/max(lowTotal,1e-6f)-low*low,0.0f));
    float3 anchored=target;
    if (Anchor>0.0f)
        anchored=clamp(target,min(max(low-Anchor*spread,0.0f),rr),max(low+Anchor*spread,rr));
    float3 result=rr+weight*(anchored-rr);
    result=clamp(result,min(rr,targetMin),max(rr,targetMax));
    result=max(result,0.0f);
    if (!all(isfinite(result))) { result=rr; weight=0; }
    OutColor[p]=float4(SanitizeRadiance(result),weight);
    OutStatistics[p]=float4(structure,1.0f-agreement,min(noise,65504.0f),0);
}
