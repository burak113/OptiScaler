#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors=1)), DescriptorTable(UAV(u0, numDescriptors=1))"
Texture2D<float4> InBounds : register(t0);
RWTexture2D<float4> OutBounds : register(u0);
cbuffer CB_SkinPrefilter : register(b0)
{
    float4 DstTexSize;
    float Sigma;
    uint Vertical;
    uint2 GuideBase;
}

[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid:SV_DispatchThreadID)
{
    const uint2 p=tid.xy;
    const uint2 size=(uint2(DstTexSize.xy)+15u)/16u;
    if (any(p>=size)) return;
    float4 lower=float4(3.402823e38f,1023.0f,1023.0f,1.0f);
    float4 upper=0.0f;
    bool valid=all(p*16u+16u<=uint2(DstTexSize.xy));
    [unroll] for(uint y=0u;y<2u;++y)
    [unroll] for(uint x=0u;x<2u;++x)
    {
        const float4 b=InBounds[p*2u+uint2(x,y)];
        const uint u=asuint(b.z),v=asuint(b.w);
        valid=valid && (u&0xfff00000u)==0x3f800000u &&
            (v&0xfff00000u)==0x3f900000u;
        lower.xyz=min(lower.xyz,float3(b.x,float(u&1023u),float(v&1023u)));
        upper.xyz=max(upper.xyz,float3(b.y,float((u>>10u)&1023u),float((v>>10u)&1023u)));
    }
    OutBounds[uint2(p.x*2u,p.y)]=valid?lower:0.0f;
    OutBounds[uint2(p.x*2u+1u,p.y)]=valid?float4(upper.xyz,1.0f):0.0f;
}
