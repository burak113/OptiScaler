// Private NRD->RR adapter. Original geometry/noisy signals are read-only.
// RR sees the compatibility floor; Flat Albedo Recovery sees the original surface.
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 4)), DescriptorTable(UAV(u0, numDescriptors = 4))"
Texture2D<float4> InNormals : register(t0);
Texture2D<float4> InSpecular : register(t1);
Texture2D<float4> InDiffuse : register(t2);
Texture2D<float> InDepth : register(t3);
RWTexture2D<float4> OutRRNormals : register(u0);
RWTexture2D<float4> OutSpecularMask : register(u1);
RWTexture2D<float4> OutDiffuseMask : register(u2);
RWTexture2D<float4> OutBlack : register(u3);
cbuffer Parameters : register(b0) { uint2 Size; uint RoughnessFloor; uint Reserved; }
[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const uint2 p = dispatch.xy;
    if (any(p >= Size)) return;
    const float4 normal = InNormals[p];
    const uint roughness = (uint)round(saturate(normal.b) * 1023.0f);
    const float z = InDepth[p];
    const bool flat = roughness < RoughnessFloor && isfinite(z) && abs(z) > 1e-5f;
    // Zero RGB and signed zero hit distance are active. Only the native negative
    // hit-distance sentinel (or nonfinite alpha) disables a lobe's recovery mask.
    const float specAlpha = InSpecular[p].a, diffAlpha = InDiffuse[p].a;
    const bool spec = flat && isfinite(specAlpha) && specAlpha >= 0.0f;
    const bool diff = flat && isfinite(diffAlpha) && diffAlpha >= 0.0f;
    float4 rr = normal;
    if (spec || diff) rr.b = float(RoughnessFloor) / 1023.0f;
    OutRRNormals[p] = rr;
    // Category 1 is FlatPixel's private mask, never a provider material ID.
    OutSpecularMask[p] = float4(normal.rgb, spec ? 1.0f/3.0f : 0.0f);
    OutDiffuseMask[p] = float4(normal.rgb, diff ? 1.0f/3.0f : 0.0f);
    OutBlack[p] = 0.0f;
}
