#include "FSRDFlatDetailBindings.hlsli"
// Packed FP16 colour/normal and 8-bit geometry weights keep the repeated robust-fit walks in LDS.
groupshared uint2 Colour[12][12], Normal[12][12];
groupshared float Depth[12][12];
groupshared uint Weights[7][64];
struct Fit
{
    float w;
    float2 p;
    float3 pp, c, cx, cy, cc;
};
void AddFit(inout Fit f, float w, float2 p, float3 c)
{
    f.w += w; f.p += w * p; f.pp += w * float3(p.x*p.x, p.x*p.y, p.y*p.y);
    f.c += w*c; f.cx += w*p.x*c; f.cy += w*p.y*c; f.cc += w*c*c;
}
void SolveFit(Fit f, out float3 centre, out float3 dx, out float3 dy, out float variance)
{
    const float inv = rcp(max(f.w, 1e-6f));
    const float2 p = f.p * inv;
    const float3 c = f.c * inv;
    const float3 v = f.pp * inv - float3(p.x*p.x, p.x*p.y, p.y*p.y);
    const float3 x = f.cx * inv - p.x*c, y = f.cy * inv - p.y*c;
    const float det = v.x*v.z-v.y*v.y;
    dx = det > 1e-5f ? (x*v.z-y*v.y)/det : 0.0f;
    dy = det > 1e-5f ? (y*v.x-x*v.y)/det : 0.0f;
    centre = c-dx*p.x-dy*p.y;
    variance = max(dot(f.cc*inv-c*c-dx*x-dy*y, 1.0f/3.0f), 0.0f);
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint tile=group.x+65535u*group.y;
    if (tile>=InTiles.Load(0)) return;
    const int2 origin = FlatOrigin(tile);
    const uint lane = local.y*8+local.x;
    for (uint i=lane; i<144; i+=64)
    {
        const int2 q=origin+int2(i%12,i/12)-2;
        const bool valid=FlatPixel(q);
        Colour[i/12][i%12]=FlatPack(float4(valid ? FlatRaw(q) : 0.0f, valid ? 1.0f : 0.0f));
        Normal[i/12][i%12]=FlatPack(valid ? InNormals[q] : 0.0f);
        Depth[i/12][i%12]=valid ? InDepth[q] : 0.0f;
    }
    GroupMemoryBarrierWithGroupSync();
    const int2 p=origin+int2(local.xy), c=int2(local.xy)+2;
    if (!FlatPixel(p)) return;
    const float3 raw=FlatUnpack(Colour[c.y][c.x]).rgb;
    const float3 normal=OctahedralDecode(FlatUnpack(Normal[c.y][c.x]).xy);
    const float z=Depth[c.y][c.x];
    const float2 gradient=float2(DepthDerivative(Depth[c.y][c.x-1],z,Depth[c.y][c.x+1]),
                                DepthDerivative(Depth[c.y-1][c.x],z,Depth[c.y+1][c.x]));
    float directional=1e30f;
    const int2 axes[4]={int2(1,0),int2(0,1),int2(1,1),int2(1,-1)};
    [unroll] for (uint a=0;a<4;++a)
    {
        const int2 l=c-axes[a], h=c+axes[a];
        if (FlatUnpack(Colour[l.y][l.x]).a>0 && FlatUnpack(Colour[h.y][h.x]).a>0 &&
            FlatSurfaceWeight(z,Depth[l.y][l.x],gradient,-float2(axes[a]),normal,OctahedralDecode(FlatUnpack(Normal[l.y][l.x]).xy))>0.1f &&
            FlatSurfaceWeight(z,Depth[h.y][h.x],gradient,float2(axes[a]),normal,OctahedralDecode(FlatUnpack(Normal[h.y][h.x]).xy))>0.1f)
        {
            const float3 e=raw-0.5f*(FlatUnpack(Colour[l.y][l.x]).rgb+FlatUnpack(Colour[h.y][h.x]).rgb);
            directional=min(directional,dot(e,e)*(2.0f/9.0f));
        }
    }
    const float small=max(dot(raw,raw)*(0.0025f*0.0025f/3.0f), Epsilon*Epsilon);
    if (directional==1e30f) directional=small;
    const float range=16.0f*max(directional,small);
    Fit first=(Fit)0;
    float3 mean=0, square=0;
    float total=0;
    [loop] for (uint t=0;t<25;++t)
    {
        const int2 o=int2(t%5,t/5)-2, q=c+o;
        const float4 v=FlatUnpack(Colour[q.y][q.x]);
        const float surface=v.a>0 ? FlatSurfaceWeight(z,Depth[q.y][q.x],gradient,float2(o),normal,
            OctahedralDecode(FlatUnpack(Normal[q.y][q.x]).xy)) : 0.0f;
        const uint w8=t==12 ? 255u : uint(round(saturate(surface)*255.0f));
        if ((t&3u)==0u) Weights[t/4][lane]=0;
        Weights[t/4][lane] |= w8 << (8*(t&3u));
        const float w=float(w8)*(1.0f/255.0f);
        const float3 delta=v.rgb-raw;
        mean+=w*delta; square+=w*delta*delta; total+=w;
        if (abs(o.x)+abs(o.y)<=2)
        {
            const float appearance=rcp(1.0f+dot(delta,delta)/(3.0f*range));
            AddFit(first,w*appearance,float2(o),delta);
        }
    }
    float3 estimate,dx,dy;
    float firstVariance;
    SolveFit(first,estimate,dx,dy,firstVariance);
    const float sigma2=max(min(firstVariance,4.0f*max(directional,small)),small);
    Fit second=(Fit)0;
    float weightedResidual=0, weightSquares=0;
    [loop] for (uint t=0;t<25;++t)
    {
        const int2 o=int2(t%5,t/5)-2,q=c+o;
        const float3 value=FlatUnpack(Colour[q.y][q.x]).rgb-raw;
        const float3 residual=value-estimate-dx*o.x-dy*o.y;
        const float u=dot(residual,residual)/(3.0f*4.0f*sigma2); // Tukey cutoff: 2 x first-fit sigma
        const float robust=saturate(1.0f-u);
        const float geometry=float((Weights[t/4][lane]>>(8*(t&3u)))&255u)*(1.0f/255.0f);
        const float w=geometry*robust*robust;
        AddFit(second,w,float2(o),value);
        weightedResidual+=w*min(dot(residual,residual)/3.0f,4.0f*sigma2);
        weightSquares+=w*w;
    }
    float refinedVariance;
    if (second.w>=1.5f) SolveFit(second,estimate,dx,dy,refinedVariance);
    else estimate=0.0f;
    const float noiseVariance=second.w>=1.5f ? max(weightedResidual/max(second.w-1.0f,1.0f),small) : sigma2;
    const float inv=rcp(max(total,1.0f));
    const float localVariance=max(dot(square*inv-mean*mean*inv*inv,1.0f/3.0f),0.0f);
    const float seedVariance=noiseVariance*min(1.0f,weightSquares/max(second.w*second.w,1.0f));
    OutColor[p]=float4(SanitizeRadiance(raw+estimate),min(sqrt(seedVariance),65504.0f));
    OutStatistics[p]=float4(min(sqrt(seedVariance),65504.0f),min(sqrt(max(localVariance-noiseVariance,0.0f)),65504.0f),0,0);
}
