#define MainRS \
    "RootFlags(0), " \
    "DescriptorTable(CBV(b6, numDescriptors = 1, flags = DESCRIPTORS_VOLATILE | DATA_VOLATILE)), " \
    "UAV(u0, flags = DATA_VOLATILE)"

cbuffer TitleConsumer : register(b6) { uint4 TitleConsumerConstants[76]; }
RWByteAddressBuffer PrivateSnapshot : register(u0);

// The original title descriptor may be overwritten after command recording.
// Read its native volatile table at Execute, immediately before output commit.
[RootSignature(MainRS)]
[numthreads(1, 1, 1)]
void CSMain()
{
    PrivateSnapshot.Store(1212u, TitleConsumerConstants[75].w);
}
