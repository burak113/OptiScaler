#include "FSRDNrdNativeTemporal.hlsli"
#ifdef FSRD_NRD_NATIVE_TEMPORAL_ROOT
#define MainRS \
    "RootFlags(0), " \
    "CBV(b6, flags = DATA_VOLATILE), " \
    "UAV(u0, flags = DATA_VOLATILE)"
#else
#define MainRS \
    "RootFlags(0), " \
    "DescriptorTable(CBV(b6, numDescriptors = 1, flags = DESCRIPTORS_VOLATILE | DATA_VOLATILE)), " \
    "UAV(u0, flags = DATA_VOLATILE)"
#endif
cbuffer TitleTemporal : register(b6) { uint4 TitleTemporalConstants[32]; }
RWByteAddressBuffer PrivateSnapshot : register(u0);

// Read only operands actually used by Temporal bedaacc6... at this same native
// binding. The highest selected word is127 (byte508), below its616-byte ABI.
// No source CBV is synthesized and no source buffer identity is required.
[RootSignature(MainRS)]
[numthreads(1, 1, 1)]
void CSMain()
{
    PrivateSnapshot.Store4(0u, uint4(TitleTemporalConstants[0].x, TitleTemporalConstants[1].x,
                                    TitleTemporalConstants[2].x, TitleTemporalConstants[3].x));
    PrivateSnapshot.Store4(16u, uint4(TitleTemporalConstants[0].y, TitleTemporalConstants[1].y,
                                     TitleTemporalConstants[2].y, TitleTemporalConstants[3].y));
    PrivateSnapshot.Store4(32u, uint4(TitleTemporalConstants[0].w, TitleTemporalConstants[1].w,
                                     TitleTemporalConstants[2].w, TitleTemporalConstants[3].w));
    PrivateSnapshot.Store4(48u, uint4(TitleTemporalConstants[4].z, TitleTemporalConstants[5].z,
                                     TitleTemporalConstants[6].z, TitleTemporalConstants[7].z));
    PrivateSnapshot.Store4(64u, uint4(TitleTemporalConstants[20].xyz, 0u));
    PrivateSnapshot.Store4(80u, uint4(TitleTemporalConstants[21].xyz, 0u));
    PrivateSnapshot.Store4(96u, uint4(TitleTemporalConstants[22].xyz, 0u));
    PrivateSnapshot.Store4(112u, uint4(TitleTemporalConstants[23].xyz, 0u));
    PrivateSnapshot.Store4(128u, uint4(TitleTemporalConstants[24].xyz, 0u));
    PrivateSnapshot.Store4(144u, uint4(TitleTemporalConstants[25].xyz, 0u));
    PrivateSnapshot.Store4(160u, uint4(TitleTemporalConstants[26].xyz, 0u));
    PrivateSnapshot.Store4(176u, uint4(TitleTemporalConstants[27].xyz, 0u));
    PrivateSnapshot.Store4(192u, uint4(TitleTemporalConstants[28].zw, TitleTemporalConstants[29].zw));
    PrivateSnapshot.Store4(208u, uint4(TitleTemporalConstants[30].zw, TitleTemporalConstants[31].xy));
    PrivateSnapshot.Store4(224u, uint4(TitleTemporalConstants[31].zw,
                                      NrdNativeTemporalSignature, NrdNativeTemporalVersion));
    PrivateSnapshot.Store4(240u, uint4(0u, 0u, 0u, 0u));
}
