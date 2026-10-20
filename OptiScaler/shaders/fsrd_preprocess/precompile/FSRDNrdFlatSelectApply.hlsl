#include "FSRDFlatDetailBindings.hlsli"
// Near Zero-Rough RR fallback, step 4 of 4 (flat tiles, replaces Apply): the RR weight grows by two pixels only into
// pixels where OFF is darker than half of RR (the black rim next to bright signs); bright OFF edges and dark strokes
// inside signs have no RR-weighted neighbour and stay OFF. Output = OFF + w (RR - OFF).
// Bindings: InBase = hole-filled OFF, InMean = decision (x RR weight, w darker), OutColor = RR composition.
float Weight(int2 q)
{
    q = clamp(q, int2(0, 0), int2(DstTexSize.xy) - 1);
    return InMean[q].x;
}
bool Darker(int2 q)
{
    q = clamp(q, int2(0, 0), int2(DstTexSize.xy) - 1);
    return InMean[q].w > 0.5f;
}
float Grown(int2 q)
{
    float w = Weight(q);
    if (Darker(q))
        [unroll] for (int k = 0; k < 9; ++k) w = max(w, Weight(q + int2(k % 3 - 1, k / 3 - 1)));
    return w;
}
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint tile = group.x + 65535u * group.y;
    if (tile >= InTiles.Load(0)) return;
    const int2 p = FlatOrigin(tile) + int2(local.xy);
    if (!FlatPixel(p)) return;
    const float4 current = OutColor[p];
    float w = Grown(p);
    if (Darker(p))
        [unroll] for (int k = 0; k < 9; ++k) w = max(w, Grown(p + int2(k % 3 - 1, k / 3 - 1)));
    const float3 off = InBase[p].rgb, rr = SanitizeRadiance(current.rgb);
    float3 result = off + w * (rr - off);
    // NZR on vertical surfaces (glass grain): at most VerticalStrength of the OFF result is kept there
    // (mode 1 keeps none); horizontal pixels and mode 0 keep the exact expression above.
    if (VerticalMode == 1u || VerticalMode == 2u)
    {
        const float gate = GlassGate(InNormals[p].rg);
        if (gate > 0.0f)
        {
            const float3 policy = VerticalMode == 1u ? rr : lerp(rr,result,VerticalStrength);
            result = lerp(result,policy,gate);
        }
    }
    if (!all(isfinite(result))) result = rr;
    OutColor[p] = float4(SanitizeRadiance(result), current.a);
}
