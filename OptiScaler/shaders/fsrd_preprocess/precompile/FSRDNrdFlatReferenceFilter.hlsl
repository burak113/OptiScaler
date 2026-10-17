// Near Zero-Rough Recovery: small same-surface Gaussian over the running-mean reference. A thin
// mean (negative alpha) only feeds Base's RR-based detail recovery and gets Sigma; a mature mean is
// the output and only gets MatureSigma (~0.5 px), which removes per-pixel grain of the sparse lobe
// while keeping the 3+ px detail. Weights use only geometry (depth plane, normal, flat mask),
// never the noisy colour. Alpha passes through.
#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 3)), DescriptorTable(UAV(u0, numDescriptors = 1))"
Texture2D<float4> InReference : register(t0);
Texture2D<float4> InMask : register(t1);
Texture2D<float> InDepth : register(t2);
RWTexture2D<float4> OutReference : register(u0);
cbuffer CB_FlatReferenceFilter : register(b0)
{
    float4 DstTexSize;
    float Sigma;       // thin history; <= 0 copies the reference
    uint Radius;       // 1 or 2
    float MatureSigma; // mature history (alpha >= 0); <= 0 copies the reference
    float Reserved;
}
bool Active(int2 p)
{
    if (any(p < 0) || any(p >= int2(DstTexSize.xy))) return false;
    const float z = InDepth[p];
    return abs(InMask[p].a - 1.0f/3.0f) < 0.1f && isfinite(z) && abs(z) > 1e-5f;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const int2 p = int2(dispatch.xy);
    if (any(p >= int2(DstTexSize.xy))) return;
    const float4 centre = InReference[p];
    const float sigma = centre.a >= 0.0f ? MatureSigma : Sigma;
    if (!Active(p) || sigma <= 0.0f) { OutReference[p] = centre; return; }
    const float z = InDepth[p];
    const float3 n = OctahedralDecode(InMask[p].xy);
    const float2 gradient = float2(
        DepthDerivative(Active(p-int2(1,0)) ? InDepth[p-int2(1,0)] : z, z, Active(p+int2(1,0)) ? InDepth[p+int2(1,0)] : z),
        DepthDerivative(Active(p-int2(0,1)) ? InDepth[p-int2(0,1)] : z, z, Active(p+int2(0,1)) ? InDepth[p+int2(0,1)] : z));
    const float k = -0.5f/(sigma*sigma);
    float3 sum = 0.0f; float total = 0.0f;
    const int r = int(min(Radius, 2u));
    [loop] for (int y = -r; y <= r; ++y) [loop] for (int x = -r; x <= r; ++x)
    {
        const int2 q = p + int2(x, y);
        if (!Active(q)) continue;
        const float surface = FlatSurfaceWeight(z, InDepth[q], gradient, float2(x, y), n, OctahedralDecode(InMask[q].xy));
        const float w = exp(k*float(x*x+y*y))*surface;
        if (w <= 0.0f) continue;
        sum += w*InReference[q].rgb; total += w;
    }
    if (total <= 0.0f) { OutReference[p] = centre; return; }
    OutReference[p] = float4(SanitizeRadiance(sum/total), centre.a);
}
