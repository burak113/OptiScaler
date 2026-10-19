// Shared private contract for the statistics and motion-application passes.
#define RS_STATS "RootConstants(num32BitConstants=8,b0),DescriptorTable(SRV(t0,numDescriptors=7)),DescriptorTable(UAV(u1,numDescriptors=5))"
#define RS_APPLY "RootConstants(num32BitConstants=8,b0),DescriptorTable(SRV(t2,numDescriptors=2)),DescriptorTable(SRV(t7,numDescriptors=3)),DescriptorTable(UAV(u0,numDescriptors=1))"
cbuffer Params:register(b0) { uint Width,Height,FrameIndex,Reset; uint Age; float Disocclusion,ProjectionToViewY,MaxPreviousDepth; }
Texture2D<float4> InDiffuse:register(t0),InSpecular:register(t1),InMotion:register(t2);
Texture2D<float> InDepth:register(t3);
Texture2D<float4> PrevMeanVar:register(t4);
Texture2D<float2> PrevFast:register(t5);
Texture2D<uint> PrevTile:register(t6),CurrentTile:register(t7);
RWTexture2D<float4> OutMotion:register(u0),NextMeanVar:register(u1);
RWTexture2D<float2> NextFast:register(u2);
RWTexture2D<uint> NextTile:register(u3);
Texture2D<float2> CurrentChange:register(t8);
RWTexture2D<float2> NextChange:register(u4);
Texture2D<float4> CurrentSupport:register(t9);
RWTexture2D<float4> NextSupport:register(u5);
