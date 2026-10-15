// Native PrePass442e... raw coordinates only. No native interpolation/color filter.
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
cbuffer NativePrePassConstants : register(b6) { uint4 NativeGeometry[37]; }
Texture2D<float4> NativeRawSpec : register(t0);
Texture2D<float4> NativeRawDiff : register(t1);
RWByteAddressBuffer PrivateRaw : register(u0);
uint2 PackNativeHalf4(float4 value)
{
    return uint2(NrdNearestHalfBits(value.x)|(NrdNearestHalfBits(value.y)<<16u),
                 NrdNearestHalfBits(value.z)|(NrdNearestHalfBits(value.w)<<16u));
}
uint NativePrePassStatus()
{
    uint sw,sh,dw,dh;NativeRawSpec.GetDimensions(sw,sh);NativeRawDiff.GetDimensions(dw,dh);
    const uint2 modes=NativeGeometry[36].xy;const int2 origin=asint(NativeGeometry[28].zw);
    uint status=any(modes>2u)?1u:0u;
    // Actual rect operands are UINT2; never reinterpret these words as floats.
    status|=any(NativeGeometry[29].zw!=RenderSize)||any(RenderSize==0u)?2u:0u;
    if(any(origin<0)||any(uint2(origin)>0x7fffffffu-(RenderSize-1u)))return status|4u;
    const uint2 last=uint2(origin)+RenderSize-1u;
    const uint sx=last.x>>(modes.y==2u?0u:1u),dx=last.x>>(modes.x==2u?0u:1u);
    status|=(sx>=sw||last.y>=sh||dx>=dw||last.y>=dh)?8u:0u;
    status|=(RenderSize.x<2u&&any(modes!=2u))?16u:0u;
    return status;
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if(any(tid.xy>=RenderSize))return;
    const uint status=NativePrePassStatus();
    if(all(tid.xy==0u))
    {
        // One writer initializes and publishes the uniform status. There is no
        // racing per-group atomic OR against a first-thread header clear.
        [unroll]for(uint row=0;row<96u;++row)PrivateRaw.Store4(row*16u,0u);
        PrivateRaw.Store2(28u*16u+8u,NativeGeometry[28].zw);
        PrivateRaw.Store2(29u*16u+8u,NativeGeometry[29].zw);
        PrivateRaw.Store2(32u*16u+4u,NativeGeometry[32].yz);
        PrivateRaw.Store2(36u*16u,NativeGeometry[36].xy);
        PrivateRaw.Store(0u,status);
    }
    const uint address=1536u+(tid.y*RenderSize.x+tid.x)*16u;
    if(status!=0u){PrivateRaw.Store4(address,0u);return;}
    const int2 logical=int2(tid.xy)+asint(NativeGeometry[28].zw);
    const uint2 modes=NativeGeometry[36].xy;
    const int2 specPixel=int2(logical.x>>(modes.y==2u?0u:1u),logical.y);
    const int2 diffPixel=int2(logical.x>>(modes.x==2u?0u:1u),logical.y);
    PrivateRaw.Store4(address,uint4(PackNativeHalf4(NativeRawSpec.Load(int3(specPixel,0))),
                                    PackNativeHalf4(NativeRawDiff.Load(int3(diffPixel,0)))));
}
