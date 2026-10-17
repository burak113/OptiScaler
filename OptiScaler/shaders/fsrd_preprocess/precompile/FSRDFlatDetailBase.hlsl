#include "FSRDFlatDetailBindings.hlsli"
// Combine reconstructed reference texture with RR lighting. The 21x21, stride-2
// bilateral ratio uses a flat-normalized sigma-1 Gaussian log-luma guide. A plain
// ratio of sums mixed bright-letter gains into dark backgrounds and drew a rim.
// One 28x28 window feeds everything: each texel is classified once, RR reuses that
// tag, and the guide's Gaussian is truncated (renormalised) at the window edge.
// Gates retain Base semantics: each neighbourhood uses the centre pixel's light.
// Noise is the lower quartile of quiet reference pairs, scaled by that light.
// With temporal history, reference alpha carries the residual deviation of the
// temporal mean (log units): its 5x5 lower quartile floors the noise, and a
// per-pixel Wiener factor drops detail the history samples disagree on. A negative
// alpha is -1 - confidence of a thin history (light moving over the surface, as a
// reflection does, or disocclusion): the single-frame detail fades out with it.
// Anchor bounds the target with RR's local spread; Mix monotonically opens gates.
static const int kWindow = 10;
static const int kSpan = 8 + 2 * kWindow;
static const float kRangeSigma = 0.35f;
static const float kRangeExp2 = -1.4426950409f / (2.0f * kRangeSigma * kRangeSigma);
static const float kQuietToNoise = 3.0f;
static const float kTemporalToNoise = 3.0f;
static const float Gaussian[7] = {
    0.0044330482f, 0.0540055826f, 0.2420362294f, 0.3990502797f,
    0.2420362294f, 0.0540055826f, 0.0044330482f
};
// 19,456 LDS bytes per group. Reference alpha: >=0 valid (temporal residual or 0; thin history reads 0),
// -1 non-flat, -2 outside the image but edge-clamped to a flat pixel (guide only).
groupshared uint2 WindowRR[kSpan][kSpan];
groupshared uint2 WindowReference[kSpan][kSpan];
groupshared uint GaussianHorizontal[kSpan][kSpan];
groupshared float LogLuma[kSpan][kSpan];
groupshared float QuietPair[12][12];
float4 Ref(int2 w) { return FlatUnpack(WindowReference[w.y][w.x]); }
float3 Rr(int2 w) { return FlatUnpack(WindowRR[w.y][w.x]).rgb; }
float2 GuideSample(int y, int x)
{
    const float4 value=FlatUnpack(WindowReference[y][x]);
    return value.a == -1.0f ? 0.0f : float2(GetLuminance(value.rgb),1.0f);
}
// Lower quartile of at most 25 values: the 7 smallest are kept in order.
struct Quartile
{
    float smallest[7];
    uint count;
    void Reset() { [unroll] for (uint n=0;n<7;++n) smallest[n]=1e30f; count=0; }
    void Add(float v)
    {
        ++count;
        [unroll] for (uint n=0;n<7;++n) { const float lo=min(smallest[n],v); v=max(smallest[n],v); smallest[n]=lo; }
    }
    float Value()
    {
        float result=smallest[0];
        [unroll] for (uint n=0;n<7;++n) if (n==(max(count,1u)-1u)/4u) result=smallest[n];
        return result;
    }
};
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint tile=group.x+65535u*group.y;
    if (tile>=InTiles.Load(0)) return;
    const int2 origin=FlatOrigin(tile);
    const uint lane=local.y*8+local.x;
    const bool temporalNoise=TemporalDenoise>0.0f;
    for (uint i=lane;i<uint(kSpan*kSpan);i+=64)
    {
        const int2 q=origin+int2(i%kSpan,i/kSpan)-kWindow;
        const int2 safe=clamp(q,int2(0,0),int2(DstTexSize.xy)-1);
        const bool valid=FlatPixel(safe);
        const bool inside=all(q==safe);
        const float4 sampled=valid ? InReference[safe] : 0.0f;
        const float residual=temporalNoise && isfinite(sampled.a) ? max(sampled.a,0.0f) : 0.0f;
        const float tag=valid ? (inside ? residual : -2.0f) : -1.0f;
        WindowReference[i/kSpan][i%kSpan]=FlatPack(float4(valid ? SanitizeRadiance(sampled.rgb) : 0.0f,tag));
        WindowRR[i/kSpan][i%kSpan]=FlatPack(valid && inside ? float4(SanitizeRadiance(InComposed[q].rgb),0.0f) : 0.0f);
    }
    GroupMemoryBarrierWithGroupSync();
    for (uint i=lane;i<uint(kSpan*kSpan);i+=64)
    {
        const int y=i/kSpan, x=i%kSpan;
        float2 sum=0.0f;
        [unroll] for (int k=-3;k<=3;++k)
            if (x+k>=0 && x+k<kSpan) sum+=Gaussian[k+3]*GuideSample(y,x+k);
        GaussianHorizontal[y][x]=f32tof16(sum.x)|(f32tof16(sum.y)<<16);
    }
    GroupMemoryBarrierWithGroupSync();
    for (uint i=lane;i<uint(kSpan*kSpan);i+=64)
    {
        const int y=i/kSpan, x=i%kSpan;
        float2 sum=0.0f;
        [unroll] for (int k=-3;k<=3;++k)
            if (y+k>=0 && y+k<kSpan)
            {
                const uint h=GaussianHorizontal[y+k][x];
                sum+=Gaussian[k+3]*f16tof32(uint2(h&65535u,h>>16));
            }
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
    if (Ref(w).a<0.0f) return;
    float3 sumRR=0, sumReference=0;
    const float centreLogLuma=LogLuma[w.y][w.x];
    for (int y=-kWindow;y<=kWindow;y+=2) for (int x=-kWindow;x<=kWindow;x+=2)
    {
        const int2 q=w+int2(x,y);
        const float4 value=Ref(q);
        const float delta=LogLuma[q.y][q.x]-centreLogLuma;
        const float bilateral=value.a<0.0f ? 0.0f : exp2(delta*delta*kRangeExp2);
        sumRR+=bilateral*Rr(q);
        sumReference+=bilateral*value.rgb;
    }
    const float3 light=clamp(sumRR/max(sumReference,1e-9f),0.0f,8.0f);
    const float lightScale=dot(light,1.0f/3.0f);
    const float4 centre=InReference[p];
    const float3 rr=Rr(w), reference=centre.rgb, target=reference*light;
    Quartile quiet; quiet.Reset();
    for (int qy=-2;qy<=2;++qy) for (int qx=-2;qx<=2;++qx)
    {
        const float v=QuietPair[s.y+qy][s.x+qx];
        if (v>=0) quiet.Add(v);
    }
    float noise=quiet.count>=9u ? kQuietToNoise*sqrt(quiet.Value())*lightScale : 0.0f;
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
    float residual=0.0f;
    if (temporalNoise)
    {
        // Static texture agrees over time; heavy-tailed lighting noise does not, and the quiet-pair
        // estimate under-reads it. Floor the noise with the 5x5 lower quartile of the residuals.
        Quartile temporal; temporal.Reset();
        float local3=0.0f, count3=0.0f;
        for (int ty=-2;ty<=2;++ty) for (int tx=-2;tx<=2;++tx)
        {
            const float v=Ref(w+int2(tx,ty)).a;
            if (v<0) continue;
            temporal.Add(v);
            if (abs(tx)<=1 && abs(ty)<=1) { local3+=v; count3+=1; }
        }
        if (temporal.count>=9u)
            noise=max(noise,kTemporalToNoise*TemporalDenoise*temporal.Value()*GetLuminance(mean));
        residual=TemporalDenoise*(local3/max(count3,1.0f))*GetLuminance(target);
    }
    const float snr=amplitude/max(noise,1e-5f);
    const float structure=smoothstep(1.2f,1.8f,snr)*
        max(smoothstep(0.22f,0.28f,amplitude/max(noise+GetLuminance(mean),1e-5f)),smoothstep(4.0f,8.0f,snr));
    const float agreement=1.0f-smoothstep(0.8f,1.2f,rmsDifference/max(noise,1e-5f));
    // Same-lighting reference: its noise is measured (temporal residual), so only the Wiener
    // factor below decides; the screen-texture gates switch whole patches on and off.
    float weight=(Flags&4u)!=0u && residual>0.0f ? 1.0f : structure*(1.0f-agreement);
    if (residual>0.0f)
    {
        const float detail=GetLuminance(target-rr);
        weight*=detail*detail/max(detail*detail+residual*residual,1e-20f);
    }
    if (temporalNoise && centre.a<0.0f) weight*=lerp(1.0f,saturate(-centre.a-1.0f),saturate(TemporalDenoise));
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
    // Same-lighting reference (NRD bridge): no texture separates the two, so the light ratio is
    // RR's level bias, not lighting. Express the result at the reference level, as far as the
    // reference history is mature enough to carry it.
    if ((Flags&4u)!=0u)
    {
        const float confidence=centre.a>=0.0f ? 1.0f : saturate(-centre.a-1.0f);
        // A thin history (parallax while walking) still has the accumulator's level history
        // (InStatistics x, y = depth or 0): its sparse 17x17 ratio to RR keeps the brightness.
        float thinLevel=1.0f;
        if ((Flags&8u)!=0u && confidence<1.0f)
        {
            float levelSum=0.0f, rrSum=0.0f;
            for (int gy=-2;gy<=2;++gy) for (int gx=-2;gx<=2;++gx)
            {
                const int2 o=int2(gx,gy)*4;
                if (Ref(w+o).a<0.0f) continue;
                const float2 history=InStatistics[p+o];
                if (history.y==0.0f) continue;
                levelSum+=history.x; rrSum+=GetLuminance(Rr(w+o));
            }
            if (rrSum>1e-12f && levelSum>0.0f) thinLevel=clamp(levelSum/rrSum,0.125f,8.0f);
        }
        result*=lerp(thinLevel,rcp(clamp(light,0.125f,8.0f)),confidence);
    }
    // Reference trust (NRD bridge): a mature unbiased running mean is the output; the RR-based
    // recovery above only carries thin histories. Alpha >= 0 is mature, -1 - c ramps in at c 0.5..1.
    if ((Flags&8u)!=0u)
    {
        const float trust=centre.a>=0.0f ? 1.0f : saturate(2.0f*saturate(-centre.a-1.0f)-1.0f);
        result=lerp(result,max(reference,0.0f),trust*saturate(Strength));
    }
    if (!all(isfinite(result))) { result=rr; weight=0; }
    OutColor[p]=float4(SanitizeRadiance(result),weight);
    OutStatistics[p]=float4(structure,1.0f-agreement,min(noise,65504.0f),0);
}
