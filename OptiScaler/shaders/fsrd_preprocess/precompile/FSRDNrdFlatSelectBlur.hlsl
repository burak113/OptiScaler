// Near Zero-Rough RR fallback, steps 2 and 3 of 4 (full frame): mask-normalised Gaussian (sigma 4, radius 12,
// mirrored at the image border) of clipped OFF luma and RR luma over recovery pixels.
// Direction 0 (horizontal): InPrep -> OutSum (x, y, z sums).
// Direction 1 (vertical): InSum -> q = (OFF + eps) / (RR + eps) of the normalised means, RR weight
// w = smoothstep(QHigh -> QLow, q) on recovery pixels, written in place as OutPrep.x (z mask and w darker kept).
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 1)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InSource : register(t0);   // horizontal: prep; vertical: horizontal sums
RWTexture2D<float4> OutTarget : register(u0); // horizontal: sums; vertical: prep (updated in place, same pixel only)
cbuffer CB_FlatSelect : register(b0)
{
    float4 DstTexSize;
    float QHigh, QLow, Clip, Dark;
    float Epsilon, HoleFraction;
    uint Direction, Reserved;
}
static const int Radius = 12;
static const float Sigma = 4.0f;
int Mirror(int i, int n) { return i < 0 ? -i : (i >= n ? 2 * (n - 1) - i : i); }
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy), size = int2(DstTexSize.xy);
    if (any(p >= size)) return;
    const int2 axis = Direction == 0u ? int2(1, 0) : int2(0, 1);
    float3 sum = 0.0f;
    float total = 0.0f;
    for (int k = -Radius; k <= Radius; ++k)
    {
        const float g = exp(-float(k * k) / (2.0f * Sigma * Sigma));
        int2 q = p + axis * k;
        q = int2(Mirror(q.x, size.x), Mirror(q.y, size.y));
        sum += g * InSource[q].xyz;
        total += g;
    }
    sum /= total;
    if (Direction == 0u)
    {
        OutTarget[p] = float4(sum, 0.0f);
        return;
    }
    const float4 prep = OutTarget[p];
    float w = 0.0f;
    if (prep.z > 0.5f)
    {
        const float norm = max(sum.z, 1e-6f);
        const float q = (sum.x / norm + Epsilon) / (sum.y / norm + Epsilon);
        const float t = saturate((QHigh - q) / (QHigh - QLow));
        w = t * t * (3.0f - 2.0f * t);
    }
    OutTarget[p] = float4(w, prep.y, prep.z, prep.w);
}
