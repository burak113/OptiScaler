#include "FSRDFlatDetailCommon.hlsli"
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 14)), DescriptorTable(UAV(u0, numDescriptors = 2)), StaticSampler(s0, filter = FILTER_MIN_MAG_MIP_LINEAR, addressU = TEXTURE_ADDRESS_CLAMP, addressV = TEXTURE_ADDRESS_CLAMP, addressW = TEXTURE_ADDRESS_CLAMP)"
#define FLAGS_RAW_SOURCE_BLIT (1 << 0)
#define FLAGS_SCALE_SRC (1 << 1)
#define FLAGS_DIFFUSE_SIGNAL_INDIRECT (1 << 2)
#define FLAGS_SPECULAR_SIGNAL_INDIRECT (1 << 3)
#define FLAGS_DEBUG (1 << 16)
#define FLAGS_DEBUG_MODE_MASK (0xFF << 16)
#define FLAGS_DEBUG_SKIP_SIGNAL (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DENOISER_OUTPUT (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DIRECT_SPECULAR (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DIRECT_DIFFUSE (5 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_INDIRECT_DIFFUSE (6 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_INDIRECT_SPECULAR (12 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RECONSTRUCTED_COLOR (13 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_COMPOSITION_BEFORE_CLAMP (18 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_COMPOSITION_FINAL (19 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_ALBEDO_TRUST (24 << 17 | FLAGS_DEBUG)
#define FLAGS_EXTRA_DIFFUSE (1 << 6)
#define FLAGS_EXTRA_SPECULAR (1 << 7)
#define FLAGS_DIFFUSE_ALTERNATE (1 << 8)
#define FLAGS_STREAK_FILTER (1 << 9)
#define FLAGS_DIFFUSE_SIGNAL_DISABLED (1 << 4)
#define FLAGS_SPECULAR_SIGNAL_DISABLED (1 << 5)
#define FLAGS_DEBUG_FLAT_DETAIL (25 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_FLAT_REFERENCE (26 << 17 | FLAGS_DEBUG)
// Post-RR colour tracking (task 25 T2, experimental): write RR's input colour in output units into u1 so the
// tracking passes read the same domain this pass reconstructs from, instead of re-deriving the albedo
// modulation elsewhere. Set only while the option is on and never on a debug or raw-blit frame.
#define FLAGS_COLOUR_TRACK_TARGET (1 << 10)
Texture2D<half4> InIndirectSpecular : register(t0);
Texture2D<half4> InSpecularAlbedo : register(t1);
Texture2D<half4> InDirectDiffuse : register(t2);
Texture2D<half4> InDiffuseAlbedo : register(t3);
Texture2D<half4> InSkipSignal : register(t4);
Texture2D<half4> InNormals : register(t5);
Texture2D<float> InLinearDepth : register(t6);
Texture2D<half4> InMotion : register(t7);
Texture2D<half4> InDirectSpecularDenoised : register(t8);
Texture2D<half4> InDirectSpecularSignal : register(t9);
Texture2D<float2> InAlbedoTrust : register(t10);
Texture2D<half4> InIndirectDiffuseDenoised : register(t11);
Texture2D<half4> InIndirectSpecularSignal : register(t12);
Texture2D<half4> InDirectDiffuseSignal : register(t13);
RWTexture2D<half4> OutColor : register(u0);
// RR's input colour in output units, for the post-RR colour tracker (task 25 T2). Written only under
// FLAGS_COLOUR_TRACK_TARGET; while the option is off the descriptor is null and nothing here is reached.
RWTexture2D<half4> OutTarget : register(u1);
SamplerState LinearSampler : register(s0);
cbuffer CB_Comp : register(b0)
{
    float4 DstTexSize;
    uint Flags;
    uint3 _Padding;
    float2 SourceUvScale;
    float2 SourceUvOffset;
    float SpecularAlbedoDemodulation;
    float DiffuseAlbedoModulation;
    float UnsupportedAlbedoRecovery;
    float DemodDivisorFloor;
}
bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return Flags & FLAGS_DEBUG_MODE_MASK; }
float3 SpecularMultiplier(int2 p)
{
    return lerp(1.0f, float3(InSpecularAlbedo[p].rgb), saturate(SpecularAlbedoDemodulation));
}
float3 DiffuseMultiplier(int2 p)
{
    return lerp(1.0f, float3(InDiffuseAlbedo[p].rgb), saturate(DiffuseAlbedoModulation));
}
// The demodulated diffuse lobe conversion produced. Two diffuse signals each received half.
float3 DiffuseSignalInput(int2 p)
{
    return float3(InDirectDiffuseSignal[p].rgb) * (IsSet(FLAGS_EXTRA_DIFFUSE) ? 2.0f : 1.0f);
}
// RR's input colour in output units (task 25 T2): the two signals the denoiser consumed, remodulated with the
// same multipliers this pass reconstructs with. Writing it here is what keeps the tracker's "truth" in the same
// domain as the composite without re-deriving the albedo modulation (or the extra-diffuse factor) anywhere else.
float3 ColourTrackTarget(int2 p)
{
    const float4 skip = InSkipSignal[p];
    // The composite contains Skip too. Current-source authority is already a complete colour.
    if (skip.a == -1.0f) return float3(skip.rgb);
    return float3(InIndirectSpecularSignal[p].rgb) * SpecularMultiplier(p) +
           DiffuseSignalInput(p) * DiffuseMultiplier(p) + float3(skip.rgb);
}
// Blend weight toward the unmodulated specular path: how much of the nearby same-surface
// albedo structure the light does not show (see FSRDAlbedoTrustEvidence/Propagate). Zero
// where conversion excluded the pixel or where the surface has no albedo structure at all.
float UnsupportedAlbedoWeight(int2 p)
{
    if (UnsupportedAlbedoRecovery <= 0.0f || InDirectSpecularSignal[p].a < 0.5f)
        return 0.0f;
    const float2 votes = InAlbedoTrust[p];
    const float weight = saturate(UnsupportedAlbedoRecovery) *
        smoothstep(0.4f, 0.8f, votes.x / max(votes.y, 1e-3f)) * smoothstep(0.5f, 3.0f, votes.y);
    // A lobe clamped at the FP16 limit left an unknown amount of energy in Skip, so its
    // specular part cannot be rebuilt. Such isolated highlights keep path A. GetSafeFP16's
    // 65500 ceiling is stored as 65472.
    [branch]
    if (weight > 0.0f && (any(float3(InIndirectSpecularSignal[p].rgb) >= 65472.0f) ||
                          any(DiffuseSignalInput(p) >= 65472.0f)))
        return 0.0f;
    return weight;
}
// The specular part of Skip. Below the demodulation divisor floor (an albedo channel under
// DemodDivisorFloor) conversion cannot represent a lobe's full energy and leaves the rest in
// Skip; that loss belongs to its own lobe, not to the albedo ratio. Rebuild each lobe's loss
// from its RR input exactly as conversion divided it; the remaining Skip
// was split by the albedo ratio, like the unmodulated alternate.
float3 SpecularSkip(int2 p, float3 spec, float3 diff, float3 share)
{
    const float3 specLoss = float3(InIndirectSpecularSignal[p].rgb) * (max(max(spec, DemodDivisorFloor), 1e-4f) - spec);
    const float3 diffLoss = DiffuseSignalInput(p) * (max(max(diff, DemodDivisorFloor), 1e-4f) - diff);
    return (float3(InSkipSignal[p].rgb) - specLoss - diffLoss) * share + specLoss;
}
float3 SpecularRadiance(int2 p)
{
    return float3(InIndirectSpecular[p].rgb) +
        (IsSet(FLAGS_EXTRA_SPECULAR) ? float3(InDirectSpecularDenoised[p].rgb) : 0.0f);
}
float3 DiffuseRadiance(int2 p)
{
    return float3(InDirectDiffuse[p].rgb) +
        (IsSet(FLAGS_EXTRA_DIFFUSE) ? float3(InIndirectDiffuseDenoised[p].rgb) : 0.0f);
}

// Streak-orthogonal filter (diagnostic, off unless FLAGS_STREAK_FILTER).
//
// Where this frame magnifies the previous one along one axis - stair treads are stretched
// vertically while climbing - each column's RR history is its own noisy chain drawn out
// along that axis, and neighbouring columns do not share its error: coloured stripes along
// the stretch. Averaging RR's demodulated lighting a few pixels across the stripes, on the
// same surface only, cancels that error; detail along the stretch and all albedo texture
// stay. Crop replays of captured stairs, together with the Light magnified-history reset in
// conversion: streaks -64%, fine noise -8%, still and descending views untouched.
//
// Per-axis history stretch |1 + d(motion px)/d(px)|, as a least-squares slope over +-2
// same-surface neighbours: InMotion is FP16, and the wider stencil keeps its rounding out of
// the gate.
float2 CompositionHistoryStretch(int2 p)
{
    const int2 bounds = int2(DstTexSize.xy) - 1;
    const float z = InLinearDepth[p];
    const float2 motionPx = float2(InMotion[p].xy) * DstTexSize.xy;
    float2 stretch = 1.0f;
    [unroll]
    for (int axis = 0; axis < 2; ++axis)
    {
        float numerator = 0.0f;
        float denominator = 0.0f;
        [unroll]
        for (int o = -2; o <= 2; ++o)
        {
            const int2 q = p + (axis == 0 ? int2(o, 0) : int2(0, o));
            if (o == 0 || any(q < 0) || any(q > bounds))
                continue;
            const float4 tapMotion = InMotion[q];
            if (!(abs(InLinearDepth[q] - z) <= 0.05f * abs(z)) || tapMotion.a < 0.5f)
                continue;
            numerator += o * (tapMotion[axis] * DstTexSize[axis] - motionPx[axis]);
            denominator += o * o;
        }
        stretch[axis] = denominator > 0.0f ? abs(1.0f + numerator / denominator) : 1.0f;
    }
    return stretch;
}

void StreakFilter(int2 p, inout float3 specular, inout float3 diffuse)
{
    const float4 motion = InMotion[p];
    if (motion.a < 0.5f)
        return;
    // Most pixels are nowhere near magnified. Plain +-1 differences of motion alone are four
    // loads and can only overstate the magnification at a silhouette, where motion jumps; the
    // same-surface estimate below decides everything they let through.
    {
        const int2 bounds = int2(DstTexSize.xy) - 1;
        const float dx = float(InMotion[min(p + int2(1, 0), bounds)].x) - float(InMotion[max(p - int2(1, 0), 0)].x);
        const float dy = float(InMotion[min(p + int2(0, 1), bounds)].y) - float(InMotion[max(p - int2(0, 1), 0)].y);
        if (min(abs(1.0f + 0.5f * dx * DstTexSize.x), abs(1.0f + 0.5f * dy * DstTexSize.y)) >= 0.95f)
            return;
    }
    const float2 stretch = CompositionHistoryStretch(p);
    // Full below a stretch of 0.8, none from 0.9.
    const float gate = saturate((0.9f - min(stretch.x, stretch.y)) * 10.0f);
    [branch]
    if (gate <= 0.0f)
        return;
    // Filter across the stripes: along X when the vertical axis is the magnified one.
    const bool alongX = stretch.y <= stretch.x;
    const int2 bounds = int2(DstTexSize.xy) - 1;
    const float z = InLinearDepth[p];
    const float3 n = OctahedralDecode(InNormals[p].xy);
    float3 specularSum = 0.0f;
    float3 diffuseSum = 0.0f;
    float weightSum = 0.0f;
    [unroll]
    for (int o = -5; o <= 5; ++o)
    {
        const int2 q = p + (alongX ? int2(o, 0) : int2(0, o));
        if (any(q < 0) || any(q > bounds))
            continue;
        if (!(abs(InLinearDepth[q] - z) <= 0.02f * abs(z)) || dot(n, OctahedralDecode(InNormals[q].xy)) <= 0.9f)
            continue;
        const float w = exp(-0.125f * float(o * o)); // Gaussian, sigma two pixels
        specularSum += w * SpecularRadiance(q);
        diffuseSum += w * DiffuseRadiance(q);
        weightSum += w;
    }
    if (weightSum <= 0.0f)
        return;
    specular = lerp(specular, specularSum / weightSum, gate);
    diffuse = lerp(diffuse, diffuseSum / weightSum, gate);
}
// Replaces the specular part of the reconstruction - RR's remodulated specular plus the
// specular part of Skip - with RR's denoising of the same share never divided by albedo.
// With the diffuse alternate the diffuse part follows on mostly reflective surfaces: the
// diffuse albedo of water or glass is the surface seen through it, while on a diffuse-
// dominant surface it is the surface itself (real-RR replays: the stain edge drops by a
// further quarter to two fifths, with no change off the water).
float3 UnsupportedAlbedoCorrection(int2 p, float3 specular, inout float3 carriedSkip)
{
    const float weight = UnsupportedAlbedoWeight(p);
    if (weight <= 0.0f)
        return 0.0f;
    const float3 spec = InSpecularAlbedo[p].rgb, diff = InDiffuseAlbedo[p].rgb;
    const float3 total = spec + diff;
    const float3 splitT = saturate((total - 0.5f * DemodDivisorFloor) / (0.5f * DemodDivisorFloor));
    const float3 share = spec * rcp(max(total, DemodDivisorFloor)) * splitT * splitT * (3.0f - 2.0f * splitT);
    const float3 specularSkip = SpecularSkip(p, spec, diff, share);
    float3 correction = weight * (float3(InDirectSpecularDenoised[p].rgb) - (specular + specularSkip));
    carriedSkip -= weight * specularSkip;
    [branch]
    if (IsSet(FLAGS_DIFFUSE_ALTERNATE))
    {
        const float reflective = smoothstep(0.5f, 0.7f, GetLuminance(spec) / max(GetLuminance(total), 1e-4f));
        // Skip less its specular part is the diffuse part, divisor-floor loss included.
        const float3 diffusePath = DiffuseRadiance(p) * DiffuseMultiplier(p) + float3(InSkipSignal[p].rgb) - specularSkip;
        correction += weight * reflective * (float3(InIndirectDiffuseDenoised[p].rgb) - diffusePath);
        carriedSkip -= weight * reflective * (float3(InSkipSignal[p].rgb) - specularSkip);
    }
    return correction;
}
float3 Reconstruct(int2 p, out float3 independentRR, out float3 carriedSkip)
{
    const float4 skip=InSkipSignal[p];
    float3 specularLight = SpecularRadiance(p);
    float3 diffuseLight = DiffuseRadiance(p);
    [branch]
    if (IsSet(FLAGS_STREAK_FILTER))
        StreakFilter(p, specularLight, diffuseLight);
    const float3 specular = specularLight * SpecularMultiplier(p);
    const float3 denoised = specular + diffuseLight * DiffuseMultiplier(p);
    // The RR copy keeps history warm; the current-source certificate selects
    // one complete colour and excludes stale RR radiance during transitions.
    // Complete radiance still feeds colour reconstruction; support-only tags
    // keep its different RR domain out of a noisy neighbour's corroboration.
    if(skip.a==-1.0f)
    {
        // Current-source authority controls the final colour, but is not a
        // native RR observation. Its kept-warm RR signals retain their actual
        // values, while the recovery witness marks the domain boundary.
        // Counting full raw here would itself introduce a false edge against
        // residual-only RR.
        independentRR = SanitizeRadiance(denoised);
        carriedSkip = SanitizeRadiance(skip.rgb) - independentRR;
        return SanitizeRadiance(skip.rgb);
    }
    float3 radiance = denoised + float3(InSkipSignal[p].rgb);
    carriedSkip = skip.rgb;
    [branch]
    if (UnsupportedAlbedoRecovery > 0.0f)
        radiance += UnsupportedAlbedoCorrection(p, specular, carriedSkip);
    independentRR = SanitizeRadiance(radiance - carriedSkip);
    return SanitizeRadiance(radiance);
}
float3 Reconstruct(int2 p, out float3 independentRR)
{
    float3 carriedSkip;
    return Reconstruct(p, independentRR, carriedSkip);
}
float3 Reconstruct(int2 p)
{
    float3 independentRR;
    return Reconstruct(p, independentRR);
}


[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    const int2 p=int2(id.xy);
    if (any(p>=int2(DstTexSize.xy))) return;
    if (IsSet(FLAGS_RAW_SOURCE_BLIT))
    {
        const float2 uv=(float2(p)+0.5f)*DstTexSize.zw;
        OutColor[p]=IsSet(FLAGS_SCALE_SRC) ? InIndirectSpecular.SampleLevel(LinearSampler,uv*SourceUvScale+SourceUvOffset,0) : InIndirectSpecular[p];
        return;
    }
    float3 colour=Reconstruct(p);
    [branch]
    if (IsSet(FLAGS_COLOUR_TRACK_TARGET))
        OutTarget[p]=half4(SanitizeRadiance(ColourTrackTarget(p)), InSkipSignal[p].a == -1.0f ? 0.0f : 1.0f);
    if (IsSet(FLAGS_DEBUG))
    {
        switch (GetDebugMode())
        {
            case FLAGS_DEBUG_SKIP_SIGNAL: colour=InSkipSignal[p].rgb; break;
            case FLAGS_DEBUG_DENOISER_OUTPUT: colour=SpecularRadiance(p)+DiffuseRadiance(p); break;
            case FLAGS_DEBUG_DIRECT_SPECULAR: colour=InDirectSpecularDenoised[p].rgb; break;
            case FLAGS_DEBUG_DIRECT_DIFFUSE: colour=InDirectDiffuse[p].rgb; break;
            case FLAGS_DEBUG_INDIRECT_DIFFUSE: colour=InIndirectDiffuseDenoised[p].rgb; break;
            case FLAGS_DEBUG_INDIRECT_SPECULAR: colour=InIndirectSpecular[p].rgb; break;
            case FLAGS_DEBUG_ALBEDO_TRUST: colour=UnsupportedAlbedoWeight(p); break;
            case FLAGS_DEBUG_FLAT_DETAIL:
            case FLAGS_DEBUG_FLAT_REFERENCE:
                if (abs(InNormals[p].a-1.0f/3.0f)>=0.1f || InSkipSignal[p].a==-1.0f) colour=0;
                break;
        }
    }
    OutColor[p]=half4(SanitizeRadiance(colour),1);
}
