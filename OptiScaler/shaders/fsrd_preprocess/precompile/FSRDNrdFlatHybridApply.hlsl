#include "FSRDFlatDetailBindings.hlsli"
// Near Zero-Rough reflection-history selector, step 4 of 4 (flat tiles, replaces Apply):
// output = Base + w (k RR - Base), with the decision (x = w, y = k) from HybridBlur.
// Bindings: InBase = Base result, InMean = decision, OutColor = RR composition.
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint tile = group.x + 65535u * group.y;
    if (tile >= InTiles.Load(0)) return;
    const int2 p = FlatOrigin(tile) + int2(local.xy);
    if (!FlatPixel(p)) return;
    const float4 current = OutColor[p], decision = InMean[p];
    const float3 base = SanitizeRadiance(InBase[p].rgb), rr = SanitizeRadiance(current.rgb);
    float3 result = base + saturate(decision.x) * (decision.y * rr - base);
    // NZR on vertical surfaces (glass grain): horizontal pixels (puddles) are untouched, and mode 0 skips this.
    if (VerticalMode != 0u)
    {
        const float gate = GlassGate(InNormals[p].rg);
        if (gate > 0.0f)
        {
            const float3 policy = VerticalMode == 1u ? rr
                : (VerticalMode == 2u ? lerp(rr,result,VerticalStrength) : result);
            result = lerp(result,policy,gate);
        }
    }
    if (!all(isfinite(result))) result = rr;
    OutColor[p] = float4(SanitizeRadiance(result), current.a);
}
