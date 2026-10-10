#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0,numDescriptors=1)), DescriptorTable(UAV(u0,numDescriptors=1))"
Texture2D<float4> Source : register(t0);
RWTexture2D<float4> Result : register(u0);
cbuffer Probe : register(b0)
{
    uint2 Extent;
    uint2 Base;
    float4 ChannelMask;
    uint Row;
    uint3 Padding;
}
groupshared float4 S[256], M[256], N[256], F[256];
[RootSignature(MainRS)]
[numthreads(256,1,1)]
void CSMain(uint i : SV_GroupIndex)
{
    float4 sum=0, maximum=0, nonzero=0, nonfinite=0;
    for(uint n=i;n<4096;n+=256)
    {
        uint2 grid=uint2(n%64,n/64);
        uint2 p=min(uint2((grid+0.5)*float2(Extent)/64.0),Extent-1)+Base;
        float4 v=Source[p]*ChannelMask;
        bool4 good=isfinite(v);
        nonfinite+=float4(!good)*ChannelMask;
        v=float4(good.x?v.x:0,good.y?v.y:0,good.z?v.z:0,good.w?v.w:0);
        sum+=v; maximum=max(maximum,abs(v)); nonzero+=float4(v!=0);
    }
    S[i]=sum; M[i]=maximum; N[i]=nonzero; F[i]=nonfinite;
    GroupMemoryBarrierWithGroupSync();
    for(uint step=128;step>0;step>>=1)
    {
        if(i<step) { S[i]+=S[i+step]; M[i]=max(M[i],M[i+step]); N[i]+=N[i+step]; F[i]+=F[i+step]; }
        GroupMemoryBarrierWithGroupSync();
    }
    if(i==0) { Result[uint2(0,Row)]=S[0]/4096; Result[uint2(1,Row)]=M[0]; Result[uint2(2,Row)]=N[0]/4096; Result[uint2(3,Row)]=F[0]/4096; }
}
