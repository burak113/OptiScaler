#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0,numDescriptors=2)), DescriptorTable(UAV(u0,numDescriptors=3))"
Texture2D<float4> Raw : register(t0);
Texture2D<float4> Final : register(t1);
RWTexture2D<float4> RawSum : register(u0);
RWTexture2D<float4> RawSquareSum : register(u1);
RWTexture2D<float4> FinalSum : register(u2);
cbuffer Reference : register(b0)
{
    uint2 Extent;
    uint2 RawBase;
    uint Count;
    uint Target;
    uint2 Padding;
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    uint2 p=id.xy; if(any(p>=Extent)) return;
    float4 r=Raw[p+RawBase], d=Final[p];
    precise float4 s=r, q=r*r, f=d;
    if(Count>1) { s+=RawSum[p]; q+=RawSquareSum[p]; f+=FinalSum[p]; }
    if(Count==Target)
    {
        s/=Count; q=max(q/Count-s*s,0); f/=Count;
    }
    RawSum[p]=s; RawSquareSum[p]=q; FinalSum[p]=f;
}
