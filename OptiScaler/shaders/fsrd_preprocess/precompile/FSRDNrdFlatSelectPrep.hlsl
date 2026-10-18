// Near Zero-Rough RR fallback, step 1 of 4 (full frame). Near Zero-Rough output ("OFF") is the robust single-frame
// reference: sharp on bright, dense reflections (signs), but its plane fit drops dim heavy-tailed reflections
// almost completely. This step prepares the decision whether OFF or RR (floor 2) should show a mirror pixel.
//  - OFF value of a pixel: Base's result on recovery pixels, RR's elsewhere (what the output would show).
//  - Isolated hole fill: a recovery pixel far below its 3x3 median luma takes the 3x3 median colour.
//  - Decision inputs on recovery pixels: OFF luma clipped to Clip x RR's 3x3 max luma (an isolated survivor must
//    not make a collapsed area look healthy), RR luma, mask, and "darker" (OFF < Dark x RR) for the edge growth.
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 4)), DescriptorTable(UAV(u0, numDescriptors = 2))"
Texture2D<float4> InBase : register(t0);   // Base result (OFF) on recovery pixels
Texture2D<float4> InRR : register(t1);     // RR output of this lobe (the composition before Apply)
Texture2D<float4> InMask : register(t2);   // a = 1/3 on this lobe's recovery pixels
Texture2D<float> InDepth : register(t3);
RWTexture2D<float4> OutFilled : register(u0); // OFF after the isolated hole fill
RWTexture2D<float4> OutPrep : register(u1);   // x clipped OFF luma, y RR luma, z mask, w darker (all 0 off the mask)
cbuffer CB_FlatSelect : register(b0)
{
    float4 DstTexSize;
    float QHigh, QLow, Clip, Dark;
    float Epsilon, HoleFraction;
    uint Direction, Reserved;
}
bool Recovery(int2 p)
{
    const float depth = InDepth[p];
    return abs(InMask[p].a - 1.0f / 3.0f) < 0.1f && isfinite(depth) && abs(depth) > 1e-5f;
}
int2 Clamped(int2 p) { return clamp(p, int2(0, 0), int2(DstTexSize.xy) - 1); }
float3 OffColour(int2 p) { return SanitizeRadiance(Recovery(p) ? InBase[p].rgb : InRR[p].rgb); }
float Median9(float v[9])
{
    // Partial selection: after 5 passes v[4] is the median.
    [unroll] for (int i = 0; i < 5; ++i)
        [unroll] for (int j = i + 1; j < 9; ++j)
        {
            const float a = min(v[i], v[j]), b = max(v[i], v[j]);
            v[i] = a; v[j] = b;
        }
    return v[4];
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy);
    if (any(p >= int2(DstTexSize.xy))) return;
    if (!Recovery(p))
    {
        OutFilled[p] = 0.0f;
        OutPrep[p] = 0.0f;
        return;
    }
    float3 c[9];
    float l[9];
    float rrMax = 0.0f;
    [unroll] for (int k = 0; k < 9; ++k)
    {
        const int2 q = Clamped(p + int2(k % 3 - 1, k / 3 - 1));
        c[k] = OffColour(q);
        l[k] = GetLuminance(c[k]);
        rrMax = max(rrMax, GetLuminance(SanitizeRadiance(InRR[q].rgb)));
    }
    float3 off = c[4];
    if (l[4] < HoleFraction * Median9(l))
    {
        float r[9], g[9], b[9];
        [unroll] for (int k = 0; k < 9; ++k) { r[k] = c[k].r; g[k] = c[k].g; b[k] = c[k].b; }
        off = float3(Median9(r), Median9(g), Median9(b));
    }
    const float lo = GetLuminance(off), lr = GetLuminance(SanitizeRadiance(InRR[p].rgb));
    OutFilled[p] = float4(off, 0.0f);
    OutPrep[p] = float4(min(lo, Clip * rrMax), lr, 1.0f, lo < Dark * lr ? 1.0f : 0.0f);
}
