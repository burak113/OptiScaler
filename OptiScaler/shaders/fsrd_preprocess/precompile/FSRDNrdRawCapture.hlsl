#include "FSRDNrdSignalEncoding.hlsli"
#ifdef FSRD_NRD_RAW_ROOT_CBV
#define NativeBinding "CBV(b6), "
#else
#define NativeBinding "DescriptorTable(CBV(b6, numDescriptors=1, flags=DESCRIPTORS_VOLATILE | DATA_VOLATILE)), "
#endif
#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants=2, b0), " \
    "DescriptorTable(SRV(t0, numDescriptors=1, flags=DESCRIPTORS_VOLATILE | DATA_VOLATILE)), " \
    "DescriptorTable(SRV(t1, numDescriptors=1, flags=DESCRIPTORS_VOLATILE | DATA_VOLATILE)), " \
    NativeBinding "UAV(u0)"
cbuffer CaptureExtent : register(b0) { uint2 RenderSize; }
cbuffer NativeGeometryConstants : register(b6) { uint4 NativeGeometry[29]; }
Texture2D<float4> NativeRawSpec : register(t0);
Texture2D<float4> NativeRawDiff : register(t1);
RWByteAddressBuffer PrivateRaw : register(u0);
uint2 PackNativeHalf4(float4 value)
{
    // Typed half loads widen exactly for finite values, including signed zero.
    // Canonical NaN/Inf stay nonfinite until late decode; no radiance clamp here.
    return uint2(NrdNearestHalfBits(value.x) | (NrdNearestHalfBits(value.y) << 16u),
                 NrdNearestHalfBits(value.z) | (NrdNearestHalfBits(value.w) << 16u));
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if (any(tid.xy >= RenderSize)) return;
    // Recon ec37... RGB loads use local DTid, unlike NR/ViewZ's source origin.
    // Preserve raw A here too; its role-specific unit conversion is a late step.
    const uint address = 1536u + (tid.y * RenderSize.x + tid.x) * 16u;
    PrivateRaw.Store4(address, uint4(PackNativeHalf4(NativeRawSpec[tid.xy]), PackNativeHalf4(NativeRawDiff[tid.xy])));
    if (all(tid.xy == 0u))
    {
        // Copy only the exact operand this profile consumes. The native source
        // CBV need not contain a Consumer-sized 1536-byte constant buffer.
        [unroll] for (uint word = 0u; word < 96u; ++word) PrivateRaw.Store4(word * 16u, 0u);
        PrivateRaw.Store4(28u * 16u, NativeGeometry[28]);
    }
}
