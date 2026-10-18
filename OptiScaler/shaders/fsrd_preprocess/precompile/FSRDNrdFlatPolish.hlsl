// Optional post-denoise reflection stabilization. The current v4 result remains the edge/response guide.
// The clamp includes the current center: a stationary clean extremum is a fixed point, not an outlier.
// History follows the existing virtual reflection point and is rejected on invalid hits or a radiance change.
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 8)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InDetail : register(t0);
Texture2D<float4> InDecision : register(t1);
Texture2D<float4> InRR : register(t2);
Texture2D<float4> InRunning : register(t3);
Texture2D<float2> InMoment : register(t4);
Texture2D<float2> InPrevMoment : register(t5);
Texture2D<float4> InPrevPolish : register(t6); // RGB stabilized v4; a is this history's own validity flag.
Texture2D<float> InDepth : register(t7);
RWTexture2D<float4> OutPolish : register(u0);
cbuffer CB_FlatPolish : register(b0)
{
    float4 DstTexSize;
    float4 PrevClip0, PrevClip1, PrevClip2, PrevClip3;
    float4 Projection;
    float ProjectionW, MaxCount, HitTolerance, HitBias;
    uint HistoryValid, Reserved0, Reserved1, Reserved2;
    float Strength, Sigma, FlatContrast, HistoryWeight;
}
groupshared float4 sCurrent[100];
float4 Current(int2 q)
{
    q = clamp(q,int2(0,0),int2(DstTexSize.xy)-1);
    if (!(InRunning[q].a > 0.0f)) return 0.0f;
    const float3 detail = SanitizeRadiance(InDetail[q].rgb), rr = SanitizeRadiance(InRR[q].rgb);
    const float4 d = InDecision[q];
    float3 rgb = detail + saturate(d.x) * (d.y * rr - detail);
    if (!all(isfinite(rgb))) rgb = rr;
    // Match the FP16 store of v4 HybridApply before estimating its neighbourhood.
    return float4(f16tof32(f32tof16(SanitizeRadiance(rgb))),1.0f);
}
float4 CatmullRom(float x)
{
    const float x2 = x*x, x3 = x2*x;
    return float4((-x3+2.0f*x2-x)*0.5f,(3.0f*x3-5.0f*x2+2.0f)*0.5f,
                  (-3.0f*x3+4.0f*x2+x)*0.5f,(x3-x2)*0.5f);
}
bool Tap(int2 q,float hit)
{
    if (any(q<0) || any(q>=int2(DstTexSize.xy))) return false;
    const float h = InPrevMoment[q].y;
    return InPrevPolish[q].a > 0.0f && h > 0.0f && abs(h-hit) < HitTolerance*hit+HitBias;
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID,uint3 group : SV_GroupID,uint index : SV_GroupIndex)
{
    const int2 origin = int2(group.xy)*8-1;
    for (uint i=index;i<100u;i+=64u) sCurrent[i] = Current(origin+int2(i%10u,i/10u));
    GroupMemoryBarrierWithGroupSync();
    const int2 p = int2(dispatch.xy), size = int2(DstTexSize.xy);
    if (any(p>=size)) return;
    const uint center = (dispatch.y%8u+1u)*10u+dispatch.x%8u+1u;
    const float4 current = sCurrent[center];
    if (!(current.a>0.0f)) { OutPolish[p]=0.0f; return; }
    float3 result = current.rgb;
    const float hit = InMoment[p].y;
    if (HistoryValid != 0u && InRunning[p].a>=4.0f && hit>0.0f && Strength>0.0f)
    {
        const float z = abs(InDepth[p])*(ProjectionW<0.0f ? -1.0f:1.0f);
        const float2 ndc = float2((float(p.x)+0.5f)*DstTexSize.z*2.0f-1.0f,1.0f-(float(p.y)+0.5f)*DstTexSize.w*2.0f);
        const float w = ProjectionW*z;
        float3 view = float3((ndc.x*w-Projection.z*z)/Projection.x,(ndc.y*w-Projection.w*z)/Projection.y,z);
        view *= 1.0f+hit/max(length(view),1e-6f);
        const float4 v = float4(view,1.0f);
        const float4 clip = float4(dot(PrevClip0,v),dot(PrevClip1,v),dot(PrevClip2,v),dot(PrevClip3,v));
        if (clip.w>1e-6f && all(isfinite(clip)))
        {
            const float2 prev = clip.xy/clip.w;
            float2 q = float2((prev.x+1.0f)*0.5f*DstTexSize.x,(1.0f-prev.y)*0.5f*DstTexSize.y)-0.5f;
            // Remove roundoff around an exact pixel center, so a static clean feature is bit-stable.
            const float2 nearest = round(q);
            q = float2(abs(q.x-nearest.x)<1e-4f ? nearest.x:q.x,abs(q.y-nearest.y)<1e-4f ? nearest.y:q.y);
            const int2 b = int2(floor(q)); const float2 f = q-float2(b);
            const float4 wx = CatmullRom(f.x), wy = CatmullRom(f.y);
            float3 bilinear=0.0f,cubic=0.0f,lo=3e38f,hi=-3e38f;
            float weight=0.0f; bool all16=true;
            [unroll] for (int j=0;j<4;++j)
                [unroll] for (int i=0;i<4;++i)
                {
                    const int2 t = b+int2(i-1,j-1);
                    const bool valid = Tap(t,hit); all16 = all16 && valid;
                    const float3 h = InPrevPolish[clamp(t,int2(0,0),size-1)].rgb;
                    cubic += wx[i]*wy[j]*h;
                    if (i>=1 && i<=2 && j>=1 && j<=2 && valid)
                    {
                        const float g = (i==1 ? 1.0f-f.x:f.x)*(j==1 ? 1.0f-f.y:f.y);
                        bilinear += g*h; weight += g; lo=min(lo,h); hi=max(hi,h);
                    }
                }
            if (weight>0.5f)
            {
                float3 h = all16 ? clamp(cubic,lo,hi):bilinear/weight;
                float sum=0.0f,squares=0.0f,n=0.0f,minimum=3e38f,maximum=0.0f;
                [unroll] for (int y=-1;y<=1;++y)
                    [unroll] for (int x=-1;x<=1;++x)
                    {
                        const float4 c = sCurrent[int(center)+y*10+x];
                        if (!(c.a>0.0f)) continue;
                        const float l = GetLuminance(c.rgb);
                        sum+=l; squares+=l*l; n+=1.0f; minimum=min(minimum,l); maximum=max(maximum,l);
                    }
                const float mean=sum/max(n,1.0f), sd=sqrt(max(squares/max(n,1.0f)-mean*mean,0.0f));
                const float lc=GetLuminance(current.rgb), lh=GetLuminance(h);
                const float lower=min(lc,max(mean-Sigma*sd,minimum)), upper=max(lc,min(mean+Sigma*sd,maximum));
                const float target=clamp(lh,lower,upper);
                // Use RGB innovation as well as luma so an isoluminant colour change cannot keep stale colour.
                const float3 delta=abs(h-current.rgb);
                const float peak=max(max(max(h.r,h.g),h.b),max(max(current.r,current.g),current.b));
                const float change=max(max(delta.r,delta.g),delta.b)/max(peak,1e-4f);
                const float flat=saturate(1.0f-sd/max(mean*FlatContrast,1e-4f));
                const float a=Strength*HistoryWeight*flat*saturate((0.8f-change)/0.6f);
                h *= lh>1e-8f ? target/lh:1.0f;
                result=current.rgb+a*(h-current.rgb);
            }
        }
    }
    OutPolish[p]=float4(SanitizeRadiance(result),1.0f);
}
