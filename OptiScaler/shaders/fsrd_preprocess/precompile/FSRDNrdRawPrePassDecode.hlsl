// Reconstruct only proven untraced native checkerboard inputs, then feed all
// lighting to RR. This is not a native NRD filter or a post-RR correction.
// FSRD_NRD_SURFACE_VALID_FILL compiles the separate D02/WP08 experiment: an
// eligibility-gated fill behind its config key. The default compilation below
// is the unchanged production path.
#include "FSRDNrdSignalEncoding.hlsli"
#include "FSRDPreprocessCommon.hlsli"
#ifdef FSRD_NRD_SURFACE_VALID_FILL
#define NrdDecodeMainRS \
    "RootFlags(0), RootConstants(num32BitConstants=2, b0), SRV(t4), " \
    "DescriptorTable(SRV(t0, numDescriptors=3)), " \
    "DescriptorTable(UAV(u0, numDescriptors=2)), CBV(b6)"
#else
#define NrdDecodeMainRS \
    "RootFlags(0), RootConstants(num32BitConstants=2, b0), SRV(t2), " \
    "DescriptorTable(SRV(t0, numDescriptors=2)), " \
    "DescriptorTable(UAV(u0, numDescriptors=2)), CBV(b6)"
#endif
#define MainRS NrdDecodeMainRS
cbuffer DecodeExtent : register(b0) { uint2 RenderSize; }
cbuffer OwnedEncoding : register(b6) { uint4 ConsumerConstants[76]; }
Texture2D<float4> InNormal : register(t0);
Texture2D<float> InDepth : register(t1);
#ifdef FSRD_NRD_SURFACE_VALID_FILL
// Geometry validity channel (D04/WP06). Bit0-1: 0 finite inside RR bounds.
Texture2D<uint> InValidity : register(t2);
// The raw byte buffer moves to its own standalone root SRV (t4) so the guide
// table can grow by one without overlapping the raw address binding. The
// production compilation below keeps t2 exactly as shipped.
ByteAddressBuffer PrivateRaw : register(t4);
#else
ByteAddressBuffer PrivateRaw : register(t2);
#endif
RWTexture2D<float4> OutSpec : register(u0);
RWTexture2D<float4> OutDiff : register(u1);
float4 UnpackNative(uint2 value)
{
    return f16tof32(uint4(value.x&65535u,value.x>>16u,value.y&65535u,value.y>>16u));
}
float4 DecodeNative(float4 value,uint encoding)
{
    const float3 rgb=encoding?float3(value.x-value.z+value.y,value.x+value.z,value.x-value.z-value.y):value.rgb;
    const float3 clean=float3(isfinite(rgb.x)?clamp(rgb.x,0.0f,65504.0f):0.0f,
                              isfinite(rgb.y)?clamp(rgb.y,0.0f,65504.0f):0.0f,
                              isfinite(rgb.z)?clamp(rgb.z,0.0f,65504.0f):0.0f);
    const float alpha=isfinite(value.a)?value.a:0.0f;
    return f16tof32(uint4(NrdNearestHalfBits(clean.x),NrdNearestHalfBits(clean.y),NrdNearestHalfBits(clean.z),NrdNearestHalfBits(alpha)));
}
float4 SignalAt(uint2 p,uint lobe,uint encoding)
{
    const uint4 value=PrivateRaw.Load4(1536u+(p.y*RenderSize.x+p.x)*16u);
    return DecodeNative(UnpackNative(lobe?value.zw:value.xy),encoding);
}
float GeometryWeight(uint2 center,uint2 neighbor)
{
    const float3 a=OctahedralDecode(InNormal[center].xy),b=OctahedralDecode(InNormal[neighbor].xy);
    const float alignment=saturate(dot(a,b));
    const float az=abs(InDepth[center]),bz=abs(InDepth[neighbor]);
    // Dimensionless geometry only. No noisy color, oracle, variance estimate,
    // temporal history, or denoised native output participates in these weights.
    return alignment*alignment/(1.0f+abs(az-bz)/max(max(az,bz),1.0e-6f));
}
#ifdef FSRD_NRD_SURFACE_VALID_FILL
// D02/WP08 experiment step 1: candidate surface eligibility gate, applied
// before any weighting. Documented experimental criteria, not invented ideal
// thresholds; a candidate failing any criterion is a different surface for
// this footprint and never enters the normalize sum.
float GateWeight(uint2 center,uint2 candidate)
{
    // Provenance first (D04): a clamped or nonfinite depth on either side
    // means this footprint has no trustworthy geometry at all.
    if((InValidity[center]|InValidity[candidate])&3u)return 0.0f;
    const float3 a=OctahedralDecode(InNormal[center].xy),b=OctahedralDecode(InNormal[candidate].xy);
    // Same-hemisphere alignment; chosen conservative constant 0.5.
    if(saturate(dot(a,b))<0.5f)return 0.0f;
    const float az=abs(InDepth[center]),bz=abs(InDepth[candidate]);
    // Footprint slant: an order-of-magnitude depth ratio along the tap marks
    // a foreign surface, while a gradual single-surface slope survives.
    // Chosen 4x ratio; explicitly not claimed ideal.
    if(4.0f*min(az,bz)<max(az,bz))return 0.0f;
    // Material boundary: a large roughness step on the owned linear B channel
    // marks a different material. Chosen 0.25 absolute; not claimed ideal.
    if(abs(InNormal[center].b-InNormal[candidate].b)>0.25f)return 0.0f;
    return GeometryWeight(center,candidate);
}
#endif
float4 Reconstruct(uint2 p,uint mode,uint phase,uint lobe,uint encoding)
{
    const uint parity=(p.x^p.y^phase)&1u;
    // Every traced sample and every mode2 pixel uses exactly the plain decoder.
    if(mode==2u||parity==mode)return SignalAt(p,lobe,encoding);
    const bool haveLeft=p.x>0u,haveRight=p.x+1u<RenderSize.x;
    const uint2 left=uint2(haveLeft?p.x-1u:p.x,p.y),right=uint2(haveRight?p.x+1u:p.x,p.y);
#ifdef FSRD_NRD_SURFACE_VALID_FILL
    // Single-tap edges clear the same gate; no ungated edge selection.
    if(!haveLeft)return GateWeight(p,right)>0.0f?SignalAt(right,lobe,encoding):float4(0.0f,0.0f,0.0f,0.0f);
    if(!haveRight)return GateWeight(p,left)>0.0f?SignalAt(left,lobe,encoding):float4(0.0f,0.0f,0.0f,0.0f);
    const float wl=GateWeight(p,left),wr=GateWeight(p,right);
    // Explicit unsupported-footprint policy: finite zero marks "no same-surface
    // support". The old least-bad neighbor default is gone and no negative
    // alpha sentinel is used (poisoned RGB leak was the measured outcome).
    if(wl+wr<=0.0f)return float4(0.0f,0.0f,0.0f,0.0f);
    const float4 value=(SignalAt(left,lobe,encoding)*wl+SignalAt(right,lobe,encoding)*wr)/(wl+wr);
#else
    if(!haveLeft)return SignalAt(right,lobe,encoding);
    if(!haveRight)return SignalAt(left,lobe,encoding);
    const float wl=GeometryWeight(p,left),wr=GeometryWeight(p,right);
    const float4 a=SignalAt(left,lobe,encoding),b=SignalAt(right,lobe,encoding);
    float4 value;
    if(wl+wr>0.0f)value=(a*wl+b*wr)/(wl+wr);
    else value=abs(InDepth[left]-InDepth[p])<=abs(InDepth[right]-InDepth[p])?a:b;
#endif
    // The untraced alpha is a neighboring-hit reconstruction, not an attested
    // current secondary-ray measurement; compare this prototype to SDK CB mode.
    return f16tof32(uint4(NrdNearestHalfBits(value.x),NrdNearestHalfBits(value.y),NrdNearestHalfBits(value.z),NrdNearestHalfBits(value.w)));
}
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 tid : SV_DispatchThreadID)
{
    if(any(tid.xy>=RenderSize))return;
    // Unsupported input is finite/zero and explicitly flagged for the async
    // fatal path. This does not claim CPU rejection of the current GPU batch.
    if(PrivateRaw.Load(0u)!=0u){OutSpec[tid.xy]=0.0f;OutDiff[tid.xy]=0.0f;return;}
    const uint2 modes=PrivateRaw.Load2(36u*16u);const uint phase=PrivateRaw.Load(32u*16u+4u);
    const uint encoding=ConsumerConstants[75].w!=0u;
    OutSpec[tid.xy]=Reconstruct(tid.xy,modes.y,phase,0u,encoding);
    OutDiff[tid.xy]=Reconstruct(tid.xy,modes.x,phase,1u,encoding);
}
