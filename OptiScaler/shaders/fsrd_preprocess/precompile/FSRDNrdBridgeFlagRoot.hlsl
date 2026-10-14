#define MainRS \
    "RootFlags(0), " \
    "CBV(b6, flags = DATA_VOLATILE), " \
    "UAV(u0, flags = DATA_VOLATILE)"

cbuffer TitleConsumer : register(b6) { uint4 TitleConsumerConstants[76]; }
RWByteAddressBuffer PrivateSnapshot : register(u0);

// Read the title's exact root CBV address at Execute; no buffer owner or inferred range.
[RootSignature(MainRS)]
[numthreads(1, 1, 1)]
void CSMain()
{
    PrivateSnapshot.Store(1212u, TitleConsumerConstants[75].w);
}
