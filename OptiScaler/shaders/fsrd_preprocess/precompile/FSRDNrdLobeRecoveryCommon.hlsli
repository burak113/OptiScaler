// Separate demodulated NRD lobes. Research graph; not enabled by production.
// All lighting has already passed through RR. No Skip colour, remodulation,
// zero-roughness route, Mix-to-noisy, or global reduction is present.
#ifndef FSRD_NRD_LOBE_RECOVERY_COMMON
#define FSRD_NRD_LOBE_RECOVERY_COMMON
#include "FSRDNrdRecoveryResearchSupport.hlsli"
#include "FSRDNrdMaterialQuantization.hlsli"

#define NRD_RECOVERY_HISTORY 1u
#define NRD_RECOVERY_COARSEST 2u
#define NRD_RECOVERY_FINAL 4u

// Eight16-byte rows, owned by this NEW graph. No existing shared CB is changed.
cbuffer NrdLobeRecoveryConstants : register(b0)
{
    float4 FullSize;       // width,height,reciprocals
    float4 LevelSize;      // this width,height,next-coarser width,height
    float4 LobeStrength;   // spec,diff,local Anchor,negative fraction cap
    float4 PixelJitters;  // currentXY,previousXY; signed render-pixel units
    float4 Temporal;      // response,band noise threshold,minimum age,gradient age
    float4 Surface;       // relative depth,normal dot,roughness delta,min footprint
    float4 Confidence;    // minimum effective count,noise response,unused,unused
    uint4 Control;        // flags,level,successful frame index,unused
}

bool NrdRecoveryFlag(uint mask) { return (Control.x & mask) != 0; }
float NrdRecoveryLuma(float3 v) { return dot(v,float3(.2126f,.7152f,.0722f)); }
float3 NrdGradientColour(float3 v)
{
    const float3 positive=max(v,0.0f);
    return positive/max(NrdRecoveryLuma(positive),1e-4f);
}
float3 NrdDecodeOct(float2 oct)
{
    const float2 xy=oct*2.0f-1.0f;
    const float z=1.0f-abs(xy.x)-abs(xy.y);
    const float2 folded=(1.0f-abs(xy.yx))*float2(xy.x>=0?1.0f:-1.0f,xy.y>=0?1.0f:-1.0f);
    return normalize(float3(z<0?folded:xy,z));
}
uint NrdPackNormal(float4 v)
{
    const uint4 code=uint4(round(saturate(v)*float4(1023,1023,1023,3)));
    return code.x|(code.y<<10)|(code.z<<20)|(code.w<<30);
}
float4 NrdUnpackNormal(uint v)
{
    return float4(v&1023u,(v>>10)&1023u,(v>>20)&1023u,v>>30)/float4(1023,1023,1023,3);
}
bool NrdRecoverySameGeometry(float oldDepth,float4 oldNormal,float expectedDepth,float4 currentNormal)
{
    return isfinite(oldDepth)&&isfinite(expectedDepth)&&
        abs(oldDepth-expectedDepth)<=Surface.x*max(abs(expectedDepth),1e-3f)&&
        dot(NrdDecodeOct(oldNormal.xy),NrdDecodeOct(currentNormal.xy))>Surface.y&&
        uint(round(oldNormal.a*3.0f))==uint(round(currentNormal.a*3.0f))&&
        abs(oldNormal.b-currentNormal.b)<=Surface.z;
}
float4 NrdLoadLinear(Texture2D<float4> image,float2 p,int2 size)
{
    p=clamp(p,0.0f,float2(size-1));
    const int2 a=int2(floor(p)),b=min(a+1,size-1);
    const float2 f=p-a;
    return lerp(lerp(image[a],image[int2(b.x,a.y)],f.x),
                lerp(image[int2(a.x,b.y)],image[b],f.x),f.y);
}
float NrdWeightSquares(float age,float response)
{
    const float start=rcp(max(response,1e-6f));
    if(age<=start)return rcp(max(age,1.0f));
    const float limit=response/(2.0f-response);
    return limit+(rcp(start)-limit)*pow((1.0f-response)*(1.0f-response),age-start);
}
#endif
