// Lighting-consistent guides, pass 6 of 6: rewrite the pair RR and the composition use, energy-exact.
//
// With kappa the share of the guides' texture the image carries (bilinear from the tiles):
// 1. Every depth: each lobe's guide is flattened toward its target T (FSRDFogTarget: the guide means of the
//    surfaces around whose texture the image does not show either), Q1 = kappa Q + (1 - kappa) T. The level is
//    kept, only the texture the image does not show goes.
// 2. With distance (weight w from Near to Far, log scale) the fog share m = w (1 - kappa) also leaves the
//    diffuse lobe and joins the specular lobe, whose guide takes that share at the surface's own flattened level,
//    Q1s + m Q1d. A sky-like neutral guide of 1 here made RR's specular path brighten: once kappa measured what
//    the image shows (low over water and haze), moving water came out +7% with bright blotches in the shape of
//    the sea floor, and a static haze band +40%. Near surfaces are left in their lobes: in noisy night scenes
//    RR's specular path keeps a different share of heavy-tailed light.
// The kappa share keeps the frame's guide only in its colour: its luminance comes from the per-pixel guide history
// (FSRDFogStats). CP77's guides flicker with the image inside each frame; remodulating by that flicker printed a
// fine speckle on moving water wherever the sea floor's guide showed through, and the stable level does not.
// Per channel the radiance each lobe hands RR is preserved exactly (lighting x guide); a kappa of 1 keeps the
// pair bit-exact. The diffuse lobe is left alone where any channel of its FLATTENED guide is at or below the
// divisor floor (its light is negligible and per-channel decisions there made colour bands), and its kept share
// fades out continuously as its scaled guide approaches the floor. The test uses the flattened guide, not the
// frame's: at a sea-floor edge the jittered sample flips between a sand guide and a weed guide whose blue channel
// sits at the floor, the lobe was handled one frame and left alone the next, and RR, which keeps the two lobes'
// energy differently, drew a dark contour along every edge of the floor's print.
//
// Quality depends on capture, history and measurement definition. Historical c2cbdeeb
// ridge improvements do not imply general fine-detail, motion or night-energy acceptance.
// Current per-capture native RR results, retained failures and source identities are in
// tools_tmp/team_20261010/fog_handoff.md; the 8-60 m routing ramp remains unchanged.
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 9), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 4), visibility = SHADER_VISIBILITY_ALL), "

#define FLAGS_DEBUG_KAPPA (1 << 0) // write kappa into the guides' alpha for inspection (no rewrite)

Texture2D<float4> InSpecAlbedo : register(t0);  // the pair to rewrite (UNORM8 guides)
Texture2D<float4> InDiffAlbedo : register(t1);
Texture2D<float4> InSpecSignal : register(t2);  // A: hit distance (kept)
Texture2D<float4> InDiffSignal : register(t3);
Texture2D<float> InLinearDepth : register(t4);
Texture2D<float> InKappa : register(t5);        // FSRDFogSmooth output
Texture2D<float4> InTargetSpec : register(t6);  // FSRDFogTarget: flatten target of the specular guide (tiles)
Texture2D<float4> InTargetDiff : register(t7);  // and of the diffuse guide
Texture2D<float4> InGuides : register(t8);      // this frame's per-pixel guide history: Hs, Hd, log depth, valid

RWTexture2D<float4> OutSpecAlbedo : register(u0);
RWTexture2D<float4> OutDiffAlbedo : register(u1);
RWTexture2D<float4> OutSpecSignal : register(u2);
RWTexture2D<float4> OutDiffSignal : register(u3);

cbuffer CB_FogRoute : register(b0)
{
    float4 DstTexSize;    // XY: render size, ZW: 1 / size
    float2 TileSize;
    float DivisorFloor;
    float LogNear;        // log of the distance where moving the fog share starts
    float InvLogRange;    // 1 / log(Far / Near)
    float _Reserved1;
    uint Flags;
    float _Reserved0;
}

int2 ClampTile(int2 t) { return clamp(t, int2(0, 0), int2(TileSize) - 1); }

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dtID : SV_DispatchThreadID)
{
    const int2 px = int2(dtID.xy);
    const int2 size = int2(DstTexSize.xy);
    if (any(px >= size))
        return;
    const float4 specGuide = InSpecAlbedo[px];
    const float4 diffGuide = InDiffAlbedo[px];
    const float4 specSignal = InSpecSignal[px];
    const float4 diffSignal = InDiffSignal[px];

    // Kappa and the targets, bilinear between tile centres.
    const float2 tp = (float2(px) + 0.5f) / 8.0f - 0.5f;
    const int2 t0 = int2(floor(tp));
    const float2 f = tp - float2(t0);
    const int2 t00 = ClampTile(t0), t10 = ClampTile(t0 + int2(1, 0)), t01 = ClampTile(t0 + int2(0, 1)),
               t11 = ClampTile(t0 + int2(1, 1));
    const float kappa = saturate(lerp(lerp(InKappa[t00], InKappa[t10], f.x), lerp(InKappa[t01], InKappa[t11], f.x), f.y));

    if ((Flags & FLAGS_DEBUG_KAPPA) != 0)
    {
        OutSpecAlbedo[px] = float4(specGuide.rgb, kappa);
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }
    const float floorLevel = DivisorFloor * 255.0f;
    const float3 qs = specGuide.rgb, qd = diffGuide.rgb;
    const float3 qs8 = round(saturate(qs) * 255.0f), qd8 = round(saturate(qd) * 255.0f);
    const bool3 vs = qs > DivisorFloor, vd = qd > DivisorFloor;
    if (kappa >= 1.0f)
    {
        OutSpecAlbedo[px] = specGuide;
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }

    const float3 Ts = lerp(lerp(InTargetSpec[t00].rgb, InTargetSpec[t10].rgb, f.x),
                           lerp(InTargetSpec[t01].rgb, InTargetSpec[t11].rgb, f.x), f.y);
    const float3 Td = lerp(lerp(InTargetDiff[t00].rgb, InTargetDiff[t10].rgb, f.x),
                           lerp(InTargetDiff[t01].rgb, InTargetDiff[t11].rgb, f.x), f.y);
    const float z = abs(InLinearDepth[px]);
    const bool zValid = isfinite(z) && z > 0.0f;
    const float logZ = zValid ? log(max(z, 1e-6f)) : 0.0f;

    // Lobe radiance handed to RR (channels at or below the floor went to Skip and stay there).
    const float3 Rs = select(vs, specSignal.rgb * (qs8 / 255.0f), 0.0f);
    const float3 Rd = select(vd, diffSignal.rgb * (qd8 / 255.0f), 0.0f);

    const float distanceWeight = zValid ? saturate((logZ - LogNear) * InvLogRange) : 1.0f;
    // The kappa share at the guide history's stable luminance (ratio bounded to [1/4, 4]).
    const float4 history = InGuides[px];
    const float ls = GetLuminance(qs8 / 255.0f), ld = GetLuminance(qd8 / 255.0f);
    const float rs = history.w > 0.5f && ls > DivisorFloor ? clamp(history.x / ls, 0.25f, 4.0f) : 1.0f;
    const float rd = history.w > 0.5f && ld > DivisorFloor ? clamp(history.y / ld, 0.25f, 4.0f) : 1.0f;
    const float3 q1s = kappa * (qs8 / 255.0f) * rs + (1.0f - kappa) * Ts;
    const float3 q1d = kappa * (qd8 / 255.0f) * rd + (1.0f - kappa) * Td;
    const float m = distanceWeight * (1.0f - kappa);

    const bool allDiffuse = all(q1d > DivisorFloor);
    const float3 q1dValid = select(vd, q1d, 1.0f);
    const float q1dMin = min(min(q1dValid.x, q1dValid.y), q1dValid.z);
    float kd = (1.0f - m) * saturate(((1.0f - m) * q1dMin - DivisorFloor) / DivisorFloor);
    if (!allDiffuse)
        kd = 1.0f;
    const float3 qdLevel = round(saturate(kd * q1d) * 255.0f);
    const bool keep = all(qdLevel > floorLevel) && kd > 0.0f;
    const float3 Rd2 = !allDiffuse ? Rd : (keep ? kd * Rd : 0.0f);
    const float3 moved = Rd - Rd2;

    const float3 qsLevel = round(saturate(q1s + m * q1d) * 255.0f);
    if (!all(qsLevel > floorLevel))
    {
        OutSpecAlbedo[px] = specGuide;
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }
    const float3 specLighting = (Rs + moved) / (qsLevel / 255.0f);
    float3 diffOut = qd8 / 255.0f;
    float3 diffLighting = diffSignal.rgb;
    if (allDiffuse)
    {
        diffOut = keep ? qdLevel / 255.0f : 0.0f;
        diffLighting = keep ? Rd2 / (qdLevel / 255.0f) : 0.0f;
    }
    // A finite FP16 source pair can carry more radiance than its rewritten guides can represent.
    // Preserve both lobes together: clipping either carrier would lose HDR energy, and reverting just
    // one lobe after moving diffuse radiance would duplicate or remove that moved share.
    const bool representable = all(isfinite(specLighting)) && all(isfinite(diffLighting)) &&
        all(abs(specLighting) <= 65504.0f) && all(abs(diffLighting) <= 65504.0f);
    if (!representable)
    {
        OutSpecAlbedo[px] = specGuide;
        OutDiffAlbedo[px] = diffGuide;
        OutSpecSignal[px] = specSignal;
        OutDiffSignal[px] = diffSignal;
        return;
    }
    OutSpecAlbedo[px] = float4(qsLevel / 255.0f, specGuide.a);
    OutDiffAlbedo[px] = float4(diffOut, diffGuide.a);
    OutSpecSignal[px] = float4(specLighting, specSignal.a);
    OutDiffSignal[px] = float4(diffLighting, diffSignal.a);
}
