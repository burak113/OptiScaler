// Pass2: separate-lobe Laplacian pyramid. Ages=min and squared weights=max;
// an invalid source footprint cannot be healed by averaging its metadata.
#include "FSRDNrdLobeRecoveryCommon.hlsli"
#define MainRS "RootFlags(0),CBV(b0),DescriptorTable(SRV(t0,numDescriptors=3)),DescriptorTable(UAV(u0,numDescriptors=3))"
Texture2D<float4> InSpec : register(t0);
Texture2D<float4> InDiff : register(t1);
Texture2D<float4> InMetadata : register(t2);
RWTexture2D<float4> OutSpec : register(u0);
RWTexture2D<float4> OutDiff : register(u1);
RWTexture2D<float4> OutMetadata : register(u2);
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 id:SV_DispatchThreadID)
{
    const int2 p=int2(id.xy),size=int2(LevelSize.xy),sourceSize=int2(LevelSize.zw);
    if(any(p>=size))return;
    float4 s=0,d=0;float2 age=1e20f,q=0;
    [unroll]for(int y=0;y<2;++y)[unroll]for(int x=0;x<2;++x)
    {
        const int2 source=min(p*2+int2(x,y),sourceSize-1);
        s+=InSpec[source];d+=InDiff[source];const float4 meta=InMetadata[source];
        age=min(age,meta.xy);q=max(q,meta.zw);
    }
    OutSpec[p]=s*.25f;OutDiff[p]=d*.25f;OutMetadata[p]=float4(age,q);
}
