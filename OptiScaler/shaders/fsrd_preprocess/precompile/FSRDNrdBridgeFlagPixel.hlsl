#define MainRS \
    "RootFlags(0), " \
    "DescriptorTable(CBV(b6, numDescriptors = 1, flags = DESCRIPTORS_VOLATILE | DATA_VOLATILE)), " \
    "UAV(u0, flags = DATA_VOLATILE)"

cbuffer TitlePixelConsumer : register(b6) { uint4 TitlePixelConstants[10]; }
RWByteAddressBuffer PrivateSnapshot : register(u0);

// Read the actual pixel-composition flag, preserving its native volatile slot.
// The private sink uses the existing commit ABI; native word303 is never read.
[RootSignature(MainRS)]
[numthreads(1, 1, 1)]
void CSMain()
{
    PrivateSnapshot.Store(1212u, TitlePixelConstants[9].x);
}
