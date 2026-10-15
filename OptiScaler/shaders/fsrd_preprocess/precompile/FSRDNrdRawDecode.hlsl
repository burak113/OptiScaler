#include "FSRDNrdSignalEncoding.hlsli"
#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants=2, b0), SRV(t0), " \
    "DescriptorTable(UAV(u0, numDescriptors=2)), CBV(b6)"
cbuffer DecodeExtent : register(b0) { uint2 RenderSize; }
cbuffer OwnedEncoding : register(b6) { uint4 ConsumerConstants[76]; }
ByteAddressBuffer PrivateRaw : register(t0);
RWTexture2D<float4> OutSpec : register(u0);
RWTexture2D<float4> OutDiff : register(u1);
float4 UnpackNative(uint2 value)
{
    return f16tof32(uint4(value.x & 65535u,value.x >> 16u,value.y & 65535u,value.y >> 16u));
}
float4 DecodeNative(float4 value,uint encoding)
{
    // Exact native Consumer inverse. Never clamp signed chroma before this operation.
    const float3 rgb = encoding ? float3(value.x-value.z+value.y,value.x+value.z,value.x-value.z-value.y) : value.rgb;
    const float3 finiteRgb = float3(isfinite(rgb.x)?clamp(rgb.x,0.0f,65504.0f):0.0f,
                                    isfinite(rgb.y)?clamp(rgb.y,0.0f,65504.0f):0.0f,
                                    isfinite(rgb.z)?clamp(rgb.z,0.0f,65504.0f):0.0f);
    // Recon's intermediate1000 is a central SAMPLE WEIGHT, cancelled by final
    // normalization. It is not an alpha unit conversion. Keep finite native A.
    const float alpha = isfinite(value.a) ? value.a : 0.0f;
    return f16tof32(uint4(NrdNearestHalfBits(finiteRgb.x),NrdNearestHalfBits(finiteRgb.y),
                          NrdNearestHalfBits(finiteRgb.z),NrdNearestHalfBits(alpha)));
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if(any(tid.xy>=RenderSize))return;
    const uint4 raw=PrivateRaw.Load4(1536u+(tid.y*RenderSize.x+tid.x)*16u);
    const uint encoding=ConsumerConstants[75].w!=0u;
    OutSpec[tid.xy]=DecodeNative(UnpackNative(raw.xy),encoding);
    OutDiff[tid.xy]=DecodeNative(UnpackNative(raw.zw),encoding);
}
