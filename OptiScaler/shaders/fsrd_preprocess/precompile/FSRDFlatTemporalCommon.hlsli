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

float CubicWeight(float distance)
{
    const float a=FSRD_TEMPORAL_CUBIC_A;
    const float x=abs(distance), x2=x*x, x3=x2*x;
    return x<=1.0f ? (a+2.0f)*x3-(a+3.0f)*x2+1.0f :
           (x<2.0f ? a*x3-5.0f*a*x2+8.0f*a*x-4.0f*a : 0.0f);
}

float2 DecodeTemporalNormalUV(float2 uv)
{
    return float2(uv.x < -1.0f ? -2.0f-uv.x : uv.x,uv.y);
}

bool TemporalInBounds(int2 p)
{
    return all(p>=0) && all(p<int2(DstTexSize.xy));
}
#endif
