// Isolated lifetime fixture. Same three root-binding kinds/order and default
// descriptor flags as production ComputeState shaders; one SRV/UAV only.
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 1)), DescriptorTable(UAV(u0, numDescriptors = 1))"
cbuffer Constants : register(b0) { uint cbValue; uint cbTag; uint2 padding; }
Texture2D<uint> Input : register(t0);
RWTexture2D<uint4> Output : register(u0);
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid != uint3(0,0,0))) return;
    Output[uint2(0,0)] = uint4(cbValue, Input.Load(int3(0,0,0)), cbTag, 0xD1A60001);
}
