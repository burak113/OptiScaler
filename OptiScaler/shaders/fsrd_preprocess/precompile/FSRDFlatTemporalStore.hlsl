#include "FSRDFlatTemporalCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 6)), DescriptorTable(UAV(u0, numDescriptors = 3))"
Texture2D<float4> InReference : register(t0);
Texture2D<float4> InNormals : register(t1);
Texture2D<float> InDepth : register(t2);
Texture2D<float4> InMotion : register(t3);
Texture2D<float4> InSkip : register(t4);
Texture2D<float4> InNormalLP : register(t5);
RWTexture2DArray<float4> OutHistoryReference : register(u0);
RWTexture2DArray<float4> OutHistoryMotionDepth : register(u1);
RWTexture2DArray<float4> OutHistoryNormalLP : register(u2);

[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 dispatch:SV_DispatchThreadID)
{
    const int2 p=int2(dispatch.xy);
    if(!TemporalInBounds(p)) return;
    const uint3 address=uint3(dispatch.xy,HistoryHead%6u);
    const float z=InDepth[p];
    const float4 motion=InMotion[p];
    const float4 md=float4(motion.xy*FullRenderSize+JitterDelta,z,motion.z);
    const bool valid=abs(InNormals[p].a-1.0f/3.0f)<0.1f && InSkip[p].a!=-1.0f &&
        all(isfinite(md)) && all(abs(md)<=65504.0f) && abs(z)>1e-5f;
    if(!valid)
    {
        OutHistoryReference[address]=float4(0,0,0,-1);
        OutHistoryMotionDepth[address]=0;
        OutHistoryNormalLP[address]=0;
        return;
    }
    const float4 reference=InReference[p];
    OutHistoryReference[address]=float4(log(max(reference.rgb,Epsilon)),reference.a);
    OutHistoryMotionDepth[address]=md;
    OutHistoryNormalLP[address]=InNormalLP[p];
}
