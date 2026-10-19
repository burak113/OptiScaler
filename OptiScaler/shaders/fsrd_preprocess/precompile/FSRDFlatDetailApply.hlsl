#include "FSRDFlatDetailBindings.hlsli"
// Writes Base's combined result (texture from the reference, light from RR) into the composition output on flat pixels.
// Base reads RR's neighbourhood from the composition, so the write is a separate pass.
[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 group : SV_GroupID, uint3 local : SV_GroupThreadID)
{
    const uint tile=group.x+65535u*group.y;
    if (tile>=InTiles.Load(0)) return;
    const int2 p=FlatOrigin(tile)+int2(local.xy);
    if (!FlatPixel(p)) return;
    const float4 current=OutColor[p];
    const float4 combined=InBase[p];
    float3 result=all(isfinite(combined.rgb)) ? combined.rgb : SanitizeRadiance(current.rgb);
    // NZR on vertical surfaces (glass grain); mode 0, the post-RR Flat Detail path and horizontal pixels skip this.
    if (VerticalMode == 1u || VerticalMode == 2u)
    {
        const float gate = GlassGate(InNormals[p].rg);
        if (gate > 0.0f)
        {
            const float3 rr = SanitizeRadiance(current.rgb);
            const float3 policy = VerticalMode == 1u ? rr : lerp(rr,result,VerticalStrength);
            result = lerp(result,policy,gate);
        }
    }
    if (Debug==1u) result=float3(1.0f,combined.a,InMean[p].x);
    if (Debug==2u) result=InReference[p].rgb;
    OutColor[p]=float4(SanitizeRadiance(result),current.a);
}
