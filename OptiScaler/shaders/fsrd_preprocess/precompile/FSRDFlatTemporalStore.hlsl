#include "FSRDFlatTemporalCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 6)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float4> InReference : register(t0);
Texture2D<float4> InNormals : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InMotion : register(t3);
Texture2D<float4> InSkip : register(t4);
Texture2D<float2> InLP : register(t5);
RWTexture2DArray<float4> OutHistoryReference : register(u0);
RWTexture2DArray<uint2> OutHistoryAux : register(u1);
RWTexture2DArray<float2> OutHistoryLP : register(u2);

[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 dispatch:SV_DispatchThreadID)
{
    const int2 p=int2(dispatch.xy);
    if(!TemporalInBounds(p)) return;
    const uint slice=HistoryHead%6u;
    // The thread at each 4x4 block's corner keeps this frame's low-pass lumas.
    if(all((p&3)==0)) OutHistoryLP[uint3(p/4,slice)]=InLP[p/4];
    const uint3 address=uint3(dispatch.xy,slice);
    const float z=InDepth[p];
    const float4 motion=InMotion[p];
    const float4 normals=InNormals[p];
    const float4 md=float4(motion.xy*FullRenderSize+JitterDelta,z,motion.z);
    const bool valid=abs(normals.a-1.0f/3.0f)<0.1f && InSkip[p].a!=-1.0f &&
        all(isfinite(md)) && all(abs(md)<=65504.0f) && abs(z)>1e-5f;
    if(!valid)
    {
        OutHistoryReference[address]=0;
        OutHistoryAux[address]=0;
        return;
    }
    const float4 reference=InReference[p];
    // Alpha carries the depth (0 = invalid) so every tap validates from one load.
    OutHistoryReference[address]=float4(log(max(reference.rgb,Epsilon)),z);
    OutHistoryAux[address]=PackTemporalAux(md.xy,md.w,normals.xy,motion.w>=0.5f);
}
