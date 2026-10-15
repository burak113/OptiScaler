#define MainRS \
    "RootFlags(0), " \
    "CBV(b6, flags = DATA_VOLATILE), " \
    "UAV(u0, flags = DATA_VOLATILE)"

cbuffer TitlePixelConsumer : register(b6) { uint4 TitlePixelConstants[10]; }
RWByteAddressBuffer PrivateSnapshot : register(u0);

// Read word36 at the title's exact current root CBV address without owner lookup.
// The owned sink is word303 solely to keep the private PureCommit ABI unchanged.
[RootSignature(MainRS)]
[numthreads(1, 1, 1)]
void CSMain()
{
    PrivateSnapshot.Store(1212u, TitlePixelConstants[9].x);
}
