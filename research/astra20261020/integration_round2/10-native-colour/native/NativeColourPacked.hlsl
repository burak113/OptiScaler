// REJECTED QUALITY CANDIDATE. New standalone host adapter; default OFF.
// No GPU execution is implied by shipping this source. See native/README.md.
// Native one-lobe physical RGB before title remod; default Enabled=0.
// Integer-word staging is intentional: a typed float4 FP16 round-trip is not a
// proof of arbitrary native alpha NaN-payload / signed-zero preservation.
// See README.md for copy footprints, ordering, costs and local parity gates.
// Proposed compiler: DXC 1.8, -T cs_6_2 -E CSMain -HV 2021 -Ges -Gis -O3
// No -enable-16bit-types. Native RGB storage is explicitly packed to half RTZ.

#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 7)), DescriptorTable(UAV(u0, numDescriptors = 2))"

ByteAddressBuffer InSourceWords : register(t0);
ByteAddressBuffer InRawRRWords : register(t1);
ByteAddressBuffer InSelectedWords : register(t2);
Texture2D<float> InDepth : register(t3);
Texture2D<float4> InNormalRoughness : register(t4); // native R10G10B10A2_UNORM
Texture2D<uint> InAuthority : register(t5); // R32_UINT: exactly 1 is authorized.
Texture2D<uint> InSupport : register(t6); // R32_UINT: exactly 1 certifies full radius footprint.
RWByteAddressBuffer OutWords : register(u0);
RWTexture2D<float4> OutDiagnostic : register(u1); // FP32: eligible,supported,confidence,Neff

cbuffer Constants : register(b0)
{
    uint4 Extent;     // active W,H; allocation W,H
    uint4 RowPitch;   // source,raw,selected,output bytes per row
    uint4 ByteOffset; // copied footprint starts; 512-byte-aligned host allocation
    uint4 Control;    // Enabled; Representation 0=log,1=linear; Radius; estimator version=1
    float4 Support;  // spatial sigma, depth tolerance, normal cosine, roughness tolerance
    float4 Colour;   // RR guide chroma radius, max log delta, support prior, strength
    uint4 ByteSize;   // Complete source, raw, selected and output buffer capacities.
};

static const float3 L = float3(0.2126f, 0.7152f, 0.0722f);
static const float Epsilon = 1.0e-4f;

uint Address(uint2 p, uint pitch, uint offset)
{
    return offset + p.y * pitch + p.x * 8u;
}
float3 Rgb(uint2 packed)
{
    return float3(f16tof32(packed.x & 0xffffu), f16tof32(packed.x >> 16u),
                  f16tof32(packed.y & 0xffffu));
}
bool ValidRgb(float3 rgb)
{
    return all(isfinite(rgb)) && all(rgb >= 0.0f);
}
float3 Chroma(float3 rgb)
{
    const float y = dot(L, rgb);
    return y > 0.0f ? rgb / y : 0.0f;
}
float2 Opponent(float3 rgb)
{
    const float3 c = max(Chroma(rgb), 0.0f) + Epsilon;
    return log(c.rb / c.g);
}
float3 DecodeNormal(float2 oct)
{
    const float2 uv = 2.0f * (oct - 0.5f);
    float3 n = float3(uv, 1.0f - abs(uv.x) - abs(uv.y));
    const float t = max(-n.z, 0.0f);
    n.xy += float2(n.x >= 0.0f ? -t : t, n.y >= 0.0f ? -t : t);
    return normalize(n);
}
bool ValidGeometry(float z, float3 n, float roughness)
{
    return isfinite(z) && z != 0.0f && all(isfinite(n)) && dot(n, n) > 0.0f
        && isfinite(roughness) && roughness >= 0.0f && roughness <= 1.0f;
}
float Compact(float distance)
{
    const float t = max(1.0f - distance * distance, 0.0f);
    return t * t;
}
uint HalfRtz(float v)
{
    // Call only for finite nonnegative RGB <=65504. The explicit correction
    // makes this independent of the f32tof16 nearest-rounding direction.
    uint h = f32tof16(v) & 0xffffu;
    if (f16tof32(h) > v) h -= 1u;
    return h;
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const uint2 p = dispatch.xy;
    if (any(p >= Extent.xy) || any(p >= Extent.zw)) return;
    OutDiagnostic[p] = 0.0f;
    // Host must copy ALL original selected words to OutWords before this
    // dispatch, including allocation padding. Early return is therefore exact.
    if (Control.x != 1u || Control.y > 1u || Control.z > 8u || Control.w != 1u) return;
    if (Colour.w == 0.0f || Colour.y == 0.0f) return;
    // Host validates every buffer/layout and constant before dispatch. Capacity
    // checks remain defensive for standalone fixture harness use.
    const uint4 address = ByteOffset + p.y * RowPitch + p.x * 8u;
    if (any(ByteSize < 8u) || any(address > ByteSize - 8u)) return;
    const uint2 selected = InSelectedWords.Load2(address.z);
    const uint2 rawWords = InRawRRWords.Load2(Address(p, RowPitch.y, ByteOffset.y));
    const bool eligible = all(selected == rawWords) && InAuthority.Load(int3(p, 0)) == 1u
        && InSupport.Load(int3(p, 0)) == 1u;
    OutDiagnostic[p] = float4(eligible ? 1.0f : 0.0f, 0.0f, 0.0f, 0.0f);
    if (!eligible) return;
    const float3 centreSource = Rgb(InSourceWords.Load2(Address(p, RowPitch.x, ByteOffset.x)));
    const float3 centre = Rgb(rawWords);
    const float z = InDepth.Load(int3(p, 0));
    const float4 nr = InNormalRoughness.Load(int3(p, 0));
    const float3 n = DecodeNormal(nr.xy);
    if (!ValidRgb(centreSource) || !ValidRgb(centre) || !ValidGeometry(z, n, nr.z)) return;
    const float2 centreGuide = Opponent(centre);
    float3 sourceSum = 0.0f, colourSum = 0.0f;
    float sumW = 0.0f, sumW2 = 0.0f;
    const int radius = int(Control.z); // host validates 0..8, default3
    [loop] for (int dy = -radius; dy <= radius; ++dy)
    {
        [loop] for (int dx = -radius; dx <= radius; ++dx)
        {
            const int2 q = int2(p) + int2(dx, dy);
            // Missing support is missing; never clamp a crop into new samples.
            if (any(q < 0) || any(q >= int2(Extent.xy))) continue;
            // Unknown/reserved evidence is not donor support. Complete-footprint
            // provenance belongs to the producer; noisy chroma cannot certify it.
            if (InAuthority.Load(int3(q, 0)) != 1u || InSupport.Load(int3(q, 0)) != 1u) continue;
            const float3 source = Rgb(InSourceWords.Load2(Address(uint2(q), RowPitch.x, ByteOffset.x)));
            const float3 colour = Rgb(InRawRRWords.Load2(Address(uint2(q), RowPitch.y, ByteOffset.y)));
            const float tapZ = InDepth.Load(int3(q, 0));
            const float4 tapNR = InNormalRoughness.Load(int3(q, 0));
            const float3 tapN = DecodeNormal(tapNR.xy);
            if (!ValidRgb(source) || !ValidRgb(colour) || !ValidGeometry(tapZ, tapN, tapNR.z)
                || ((asuint(tapZ) ^ asuint(z)) & 0x80000000u) != 0u) continue;
            const float spatial = exp(-0.5f * float(dx * dx + dy * dy) / (Support.x * Support.x));
            const float wz = Compact((z - tapZ) / max(Support.y * abs(z), 1.0e-3f));
            const float nd = saturate((clamp(dot(n, tapN), -1.0f, 1.0f) - Support.z) / (1.0f - Support.z));
            const float wr = Compact((nr.z - tapNR.z) / Support.w);
            const float2 dc = centreGuide - Opponent(colour);
            const float c = max(1.0f - dot(dc, dc) / (Colour.x * Colour.x), 0.0f);
            const float w = spatial * wz * nd * nd * wr * c * c;
            // Source zero is INCLUDED with the same w: physical means precede
            // normalization. Do not replace by a positive-only/log sample mean.
            sourceSum += w * source;
            colourSum += w * colour;
            sumW += w;
            sumW2 += w * w;
        }
    }
    if (sumW <= 0.0f || sumW2 <= 0.0f) return;
    const float3 sourceMean = sourceSum / sumW;
    const float3 colourMean = colourSum / sumW;
    const float pixelY = dot(L, centre);
    if (dot(L, sourceMean) <= 0.0f || dot(L, colourMean) <= 0.0f || pixelY <= 0.0f) return;
    const float effectiveSamples = sumW * sumW / sumW2;
    const float extra = max(effectiveSamples - 1.0f, 0.0f);
    const float confidence = extra + Colour.z > 0.0f ? extra / (extra + Colour.z) : 0.0f;
    const float amount = confidence * Colour.w;
    OutDiagnostic[p] = float4(1.0f, 1.0f, confidence, effectiveSamples);
    if (amount <= 0.0f) return;
    float3 transported;
    if (Control.y == 0u)
    {
        const float2 delta = clamp(Opponent(sourceMean) - Opponent(colourMean), -Colour.y, Colour.y) * amount;
        if (all(delta == 0.0f)) return;
        transported = centre * float3(exp(delta.x), 1.0f, exp(delta.y));
    }
    else
    {
        const float3 colourChroma = Chroma(colourMean);
        const float3 limit = max(colourChroma, Epsilon) * (exp(Colour.y) - 1.0f);
        const float3 delta = clamp(Chroma(sourceMean) - colourChroma, -limit, limit) * amount;
        if (all(delta == 0.0f)) return;
        transported = max(Chroma(centre) + delta, 0.0f);
    }
    const float transportedY = dot(L, transported);
    if (transportedY <= 0.0f) return;
    const float3 corrected = (transported * pixelY) / transportedY;
    if (!all(isfinite(corrected)) || any(corrected < 0.0f) || any(corrected > 65504.0f)) return;
    const uint r = HalfRtz(corrected.r), g = HalfRtz(corrected.g), b = HalfRtz(corrected.b);
    const uint2 result = uint2(r | (g << 16u), b | (selected.y & 0xffff0000u));
    OutWords.Store2(Address(p, RowPitch.w, ByteOffset.w), result);
}
