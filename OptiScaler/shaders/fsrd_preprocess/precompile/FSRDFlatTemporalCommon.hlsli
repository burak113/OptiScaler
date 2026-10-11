#ifndef FSRD_FLAT_TEMPORAL_COMMON
#define FSRD_FLAT_TEMPORAL_COMMON
#include "FSRDFlatDetailCommon.hlsli"

// Stable 80-byte host contract. HistoryHead is the NEXT WRITE slot.
cbuffer CB_FlatTemporal : register(b0)
{
    float4 DstTexSize;
    float2 FullRenderSize;
    float2 JitterDelta;
    float2 Modulation;
    float TemporalStrength;
    float Epsilon;
    uint HistoryCount;
    uint HistoryHead;
    uint HistoryLength;
    uint Flags;
    float CenterSigma;
    float MotionStart;
    float MotionEnd;
    float HistoryDecay;
}

// Selected by the fixed GPU tuning grid before production parity is accepted.
#ifndef FSRD_TEMPORAL_CUBIC_A
#define FSRD_TEMPORAL_CUBIC_A (-0.5f)
#endif

// Below this summed history weight the resolve reports a confidence instead of a residual:
// reference alpha = -1 - used/kFullHistory. Base fades Flat Detail out with that confidence.
static const float kFullHistory = 0.5f;

float CubicWeight(float distance)
{
    const float a=FSRD_TEMPORAL_CUBIC_A;
    const float x=abs(distance), x2=x*x, x3=x2*x;
    return x<=1.0f ? (a+2.0f)*x3-(a+3.0f)*x2+1.0f :
           (x<2.0f ? a*x3-5.0f*a*x2+8.0f*a*x-4.0f*a : 0.0f);
}

bool TemporalInBounds(int2 p)
{
    return all(p>=0) && all(p<int2(DstTexSize.xy));
}

// History aux (R32G32_UINT). x: half2 motion in pixels (jitter delta included).
// y: half depth delta | bit 16 motion valid | bits 17-24 / 25-31 octahedral normal u (8 bit) / v (7 bit).
uint2 PackTemporalAux(float2 motion,float depthDelta,float2 octahedral,bool motionValid)
{
    const uint2 n=uint2(round(saturate(octahedral)*float2(255.0f,127.0f)));
    return uint2(f32tof16(motion.x)|(f32tof16(motion.y)<<16),
                 f32tof16(depthDelta)|(motionValid ? 0x10000u : 0u)|(n.x<<17)|(n.y<<25));
}
float3 UnpackTemporalMotion(uint2 aux) { return f16tof32(uint3(aux.x&65535u,aux.x>>16,aux.y&65535u)); }
float2 UnpackTemporalNormal(uint2 aux) { return float2((aux.y>>17)&255u,aux.y>>25)/float2(255.0f,127.0f); }
bool UnpackTemporalMotionValid(uint2 aux) { return (aux.y&0x10000u)!=0u; }

// Low-pass lumas on a 4x4 block grid. Block b averages the flat pixels' RR luma over
// [4b-2,4b+5] and raw luma over [4b-4,4b+7]; x<0 marks a block without flat pixels.
// Bilinear between block centres (4b+1.5) gives about the old 9x9 / 13x13 box widths.
int2 LPSize() { return int2((uint2(DstTexSize.xy)+3u)/4u); }
void LPFootprint(float2 position,out int2 b0,out int2 b1,out float2 fraction)
{
    const float2 u=(position-1.5f)*0.25f;
    const int2 b=int2(floor(u));
    fraction=u-float2(b);
    b0=clamp(b,0,LPSize()-1);b1=clamp(b+1,0,LPSize()-1);
}
float2 BlendLP(float2 v00,float2 v10,float2 v01,float2 v11,float2 f)
{
    const float4 w=float4((1.0f-f.x)*(1.0f-f.y),f.x*(1.0f-f.y),(1.0f-f.x)*f.y,f.x*f.y)*
        float4(v00.x>=0.0f,v10.x>=0.0f,v01.x>=0.0f,v11.x>=0.0f);
    const float total=dot(w,1.0f);
    return total>1e-3f ? (w.x*v00+w.y*v10+w.z*v01+w.w*v11)/total : float2(-1.0f,-1.0f);
}
#endif
