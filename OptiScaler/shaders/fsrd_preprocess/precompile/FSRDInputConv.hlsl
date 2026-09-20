// FSR-RR Conversion & Packing Shader
#include "FSRDPreprocessCommon.hlsli"
#include "FSRDFloorCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 17), visibility = SHADER_VISIBILITY_ALL), " \
    "DescriptorTable(UAV(u0, numDescriptors = 8), visibility = SHADER_VISIBILITY_ALL), "

// Dispatch config
#define THREAD_GROUP_SIZE_X     8
#define THREAD_GROUP_SIZE_Y     8
#define NUM_THREADS             (THREAD_GROUP_SIZE_X * THREAD_GROUP_SIZE_Y)

static const uint2 s_ThreadGroupSize = uint2(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y);
// Largest distance representable in FP16. RR's docs describe the indirect hit
// distance as "must be valid if the signal is active; otherwise negative", which reads
// per-pixel - but AMD's own sample settles it the other way: with the signal enabled
// it writes this value for sky pixels and for untraced checkerboard pixels alike
// (trace_rays_denoiser.hlsl), and never writes a negative. "Active" means the signal
// is enabled at context creation, not that a particular pixel carries a ray.
//
// So a pixel with no ray information takes a very distant hit rather than a negative,
// which is also the physically sensible reading: a miss is not an absence of light, it
// is light arriving from infinity.
static const float s_MaxRayHitDistance = 65504.0f;
static const float s_MissingDiffuseHitDistance = s_MaxRayHitDistance;

// The specular path instead publishes a negative when the title supplies no hit
// distance at all. That predates this note and does not match the sample; see the
// comment at the specular write below.
static const float s_InvalidSpecularHitDistance = -1.0f;
static const float s_Type1RoughnessThreshold = 0.5f / 1023.0f;
// Roughness handed to RR in the zero-rough domain while Floor is enabled. Exact-zero
// roughness makes RR treat those pixels as perfect mirrors and leave them unfiltered, which
// is why the domain gets a value it can filter with; the value is this pipeline's own, not a
// user preference and not an SDK threshold. 0.1 is the figure the current comparisons were
// made with, not an established optimum.
static const float s_ZeroRoughRRRoughness = 0.1f;

// The same floor as a runtime value, so the trade it makes can be tuned.
//
// Flooring the demodulation divisor caps the gain on dark surfaces, but it also breaks the
// demodulate/remodulate round trip: whatever the floored divisor could not represent is
// handed to the skip signal, which reaches the screen without passing the denoiser. On a
// noisy input that remainder is noise, so a high floor trades amplified noise inside the
// denoiser for unfiltered noise beside it. Which side of that trade is cheaper depends on the
// title, so the value is exposed rather than fixed.

// Five-tap Gaussian run along the steered axis. Deliberately broad: the whole point
// of steering is that a long kernel is safe once it is known not to cross an edge.

// Flags

#define FLAGS_LINEAR_DEPTH              (1 << 1)

#define FLAGS_PACKED_ROUGHNESS          (1 << 2)
#define FLAGS_NEGATIVE_VIEW_DEPTH       (1 << 3)
#define FLAGS_HAS_SPEC_HIT_DISTANCE     (1 << 4)
#define FLAGS_SPECULAR_SIGNAL_INDIRECT  (1 << 5)
#define FLAGS_HAS_EMISSIVE_INPUT        (1 << 6)
#define FLAGS_FLOOR_ENABLED       (1 << 7)
#define FLAGS_MOTION_VECTORS_JITTERED   (1 << 8)
#define FLAGS_DISPLAY_RESOLUTION_MOTION (1 << 9)
#define FLAGS_NORMALS_VIEW_SPACE        (1 << 11)
#define FLAGS_HAS_COMBINED_SPEC_HIT_DISTANCE (1 << 14)
// Title-published optional inputs. Each is inert unless the resource was validated.
#define FLAGS_TITLE_LINEAR_DEPTH       (1 << 12)
#define FLAGS_HAS_RESPONSIVITY_MASK    (1 << 13)
// InBiasMask holds a real DLSS bias-current-color mask rather than an unused binding.
#define FLAGS_HAS_BIAS_MASK            (1 << 15)
// Diagnostic: right half of the frame runs with the floor disabled.
// Debug Flags
#define FLAGS_DEBUG                     (1 << 16)
#define FLAGS_DEBUG_MODE_MASK           (0xFF << 16)

// Inputs
#define FLAGS_DEBUG_IN_SPEC_HIT_DIST    (1 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_MOTION           (2 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_NORMALS          (3 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_ROUGHNESS        (4 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_DIFF_ALBEDO      (5 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_SPEC_ALBEDO      (6 << 17 | FLAGS_DEBUG)

// Outputs
#define FLAGS_DEBUG_OUT_SIGNAL_SPLIT    (7 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_LINEAR_DEPTH    (8 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_MOTION          (9 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_NORMALS         (10 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_SPEC_ALBEDO     (11 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_OUT_DIFF_ALBEDO     (12 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_OUT_DEPTH_DELTA     (13 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_NORM_DEPTH          (14 << 17 | FLAGS_DEBUG)

#define FLAGS_DEBUG_ALBEDO_OVERSHOOT    (15 << 17 | FLAGS_DEBUG)

// Value 16 was the floor variance view. It visualised the seed's instability channel, which
// is no longer published now the floor confidence gate is gone (see FSRDFloorSeed.hlsl), so
// the view read a constant and went with the channel.
#define FLAGS_DEBUG_FLOOR_COLOR         (17 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RAW_INDIRECT_SPEC   (18 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_EFFECTIVE_ROUGHNESS (19 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RAW_ROUGHNESS       (20 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_EMISSIVE_MASK       (21 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_APPLIED_ROUGHNESS (22 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RESOURCE_INSPECTOR  (23 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_MATERIAL_TYPE       (24 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_EMISSIVE         (25 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RR_MATERIAL_TYPE    (26 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_ALBEDO_STRUCTURE    (27 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_FLOOR_RESIDUAL    (28 << 17 | FLAGS_DEBUG)

// Optional-input validation views
// Value 30 was the removed reflected-image motion disagreement view; it now shows the specular
// signal's share of the demodulated split. Value 29 went with the input itself.
#define FLAGS_DEBUG_SPECULAR_SPLIT      (30 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_TITLE_DEPTH      (31 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_TITLE_DEPTH_DIFF    (32 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_RESPONSIVITY     (33 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_BIAS_MASK        (34 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DEMOD_GAIN          (35 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_HIT_DIST_GATE       (36 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_DENOISER_FRACTION   (37 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_FLOOR_NOISE     (38 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_SKIP_UNMAPPED       (39 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_SKIP_FLOOR          (40 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_FLOOR_EXCESS     (41 << 17 | FLAGS_DEBUG)

// DLSS-RR Inputs
Texture2D<half3> InColor : register(t0); // RGB - NVSDK_NGX_Parameter_Color
Texture2D<float> InDepth : register(t1); // R - NVSDK_NGX_Parameter_Depth - hardware or linear - inverted or not
Texture2D<float3> InMotionVectors : register(t2); // RG - NVSDK_NGX_Parameter_MotionVectors
Texture2D<float4> InNormals : register(t3); // RGB: Normals, A: Roughness (Optional) - NVSDK_NGX_Parameter_GBuffer_Normals
Texture2D<float> InRoughness : register(t4); // R - May be packed in normals. NVSDK_NGX_Parameter_GBuffer_Roughness
Texture2D<float> InSpecHitDist : register(t5); // R - NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance
Texture2D<half3> InDiffAlbedo : register(t6); // RGB - NVSDK_NGX_Parameter_GBuffer_DiffuseAlbedo
Texture2D<half3> InSpecAlbedo : register(t7); // RGB - NVSDK_NGX_Parameter_GBuffer_SpecularAlbedo
Texture2D<half> InBiasMask : register(t8);

Texture2D<half4> InFloorColor : register(t9);
Texture2D<float4> InInspector : register(t10);
Texture2D<float4> InEmissive : register(t11); // Optional NVSDK_NGX_Parameter_GBuffer_Emissive probe
// Optional combined ray-direction resource carrying the specular hit distance in A.
Texture2D<float4> InSpecularRayDirectionHitDistance : register(t12);
// Optional diffuse ray length. Read as .r or .a depending on DiffuseHitDistanceMode.
Texture2D<float4> InDiffuseHitDistance : register(t13);
// Optional already-linearised view depth published by the title.
Texture2D<float> InTitleLinearDepth : register(t14);
// Optional per-pixel responsivity hint. Polarity is a title property, so it is a
// runtime parameter rather than something this shader may assume.
Texture2D<float4> InResponsivityMask : register(t15);
Texture2D<half4> InDetailReference : register(t16);

// RR 1.2 typed signals. Resource order matches Conversion::SignalResources.
RWTexture2D<half4> OutIndirectSpecular : register(u0); // RGB: demodulated radiance, A: hit distance
RWTexture2D<half4> OutDirectDiffuse : register(u1);    // RGB: demodulated radiance, A: diffuse ray hit distance

// ffxDispatchDescDenoiser
// RG: unjittered PreviousUV-CurrentUV, B: corresponding-surface depth delta.
RWTexture2D<half4> OutMotion : register(u2);
RWTexture2D<half4> OutNormals : register(u3); // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional)
RWTexture2D<half4> OutSpecAlbedo : register(u4); // RGB: Specular Albedo, A: dot(Normal, ViewDir)
RWTexture2D<half4> OutDiffAlbedo : register(u5); // RGB: Diffuse Albedo, A: Metalness (not provided)

RWTexture2D<half4> OutSkipSignal : register(u6);

// RGB: cleaned reference; A: noise sigma, or -1 when detail must be bypassed.
RWTexture2D<half4> OutDetailReference : register(u7);

cbuffer CB_Packing : register(b0)
{
    float4x4 InvViewMatrix; // DLSSD WorldToView^-1
    float4x4 InvProjMatrix; // DLSSD ViewToClip^-1
    float4x4 PrevViewMatrix; // DLSSD WorldToView from last frame

    float4 DstTexSize; // Resolution of inputs
    float4 MotionInputSize; // XY: source extent - ZW: reciprocal extent
    float4 MotionTransform; // XY: raw source motion -> UV displacement
    float4 JitterOffsets; // XY: current pixels - ZW: previous pixels

    uint4 InputBase0; // XY: color, ZW: motion
    uint4 InputBase1; // XY: normals, ZW: roughness
    uint4 InputBase2; // XY: spec hit distance, ZW: diffuse albedo
    uint4 InputBase3; // XY: specular albedo, ZW: bias mask
    uint4 InputBase4; // XY: emissive, ZW: reserved
    uint4 InputBase5; // XY: reserved, ZW: specular hit-distance source

    float NearPlane;
    float FarPlane;   
    
    float FloorDetailPreservation;

    uint Flags;
    uint InspectorChannel;
    float InspectorScale;

    float DebugDepthMax;
    // 0 = absent, 1 = scalar in R, 2 = combined ray-direction resource, distance in A.
    uint DiffuseHitDistanceMode;

    float ResponsivityTrustThreshold;
    uint ResponsivityInvert;
    float BiasMaskStrength;
    float DemodDivisorFloor;
    float _Padding0;
    float _Padding1;
    float _Padding2;
};

bool IsSet(uint mask) { return (Flags & mask) == mask; }
uint GetDebugMode() { return (Flags & FLAGS_DEBUG_MODE_MASK); }

int2 GetMotionSourcePx(uint2 px)
{
    float2 localPos = float2(px);
    if (IsSet(FLAGS_DISPLAY_RESOLUTION_MOTION))
    {
        // Match FSR's high-resolution MV addressing: remove current jitter before
        // mapping the render pixel center into the display-resolution grid.
        const float2 unjitteredCenter = float2(px) + 0.5f - JitterOffsets.xy;
        localPos = floor((unjitteredCenter * DstTexSize.zw) * MotionInputSize.xy);
    }

    const int2 maxLocal = max(int2(MotionInputSize.xy) - 1, 0);
    return clamp(int2(localPos), 0, maxLocal) + int2(InputBase0.zw);
}

float3 GetCanonicalMotionUv(uint2 px)
{
    const float2 rawMotion = InMotionVectors[GetMotionSourcePx(px)].rg;
    float2 motionUv = rawMotion * MotionTransform.xy;
    if (IsSet(FLAGS_MOTION_VECTORS_JITTERED))
    {
        const float2 jitterCancellationUv =
            (JitterOffsets.zw - JitterOffsets.xy) * DstTexSize.zw;
        motionUv -= jitterCancellationUv;
    }

    // RR needs a finite XY fallback. The helper also retains validity so a future
    // detail-history consumer must distinguish invalid motion from zero motion.
    const bool valid = all(isfinite(rawMotion)) && all(isfinite(motionUv)) &&
        all(abs(motionUv) <= 16.0f);
    return float3(valid ? motionUv : 0.0f, valid ? 1.0f : 0.0f);
}

// The reflected-image motion input, and the routing it drove, are gone: measured on the one
// title that published the input, the disagreement it reported tracked the camera's speed
// rather than any misalignment - 0% of the frame routed while still, 67% while moving - and
// every routed pixel had its specular radiance republished unfiltered, which put the current
// frame's raw noise on screen. See docs/007FirstLight_PT_Unlock_RE_notes.md.

float3 GetViewSpacePos(const int2 px)
{
    // InDepth is the floor seed's canonical signed-linear depth, produced from the
    // title's published linear depth whenever one was bound and otherwise from the
    // game's own depth. Every consumer of view-space position - this reconstruction,
    // the floor passes' depth guide and the denoiser's own depth input - reads that
    // one field. Re-canonicalising the title's raw resource here instead handed this
    // pass different geometry from the rest of the chain wherever the derived depth
    // disagreed with it: motion-Z and view positions built on one depth while RR
    // reprojected against the other.
    float inDepth = InDepth[px];
    // InvProjMatrix is unjittered, while px addresses the current jittered
    // raster. Remove the current pixel jitter before reconstructing the ray.
    const float2 uv = (float2(px) + 0.5 - JitterOffsets.xy) * DstTexSize.zw;
    const float depthSign = IsSet(FLAGS_NEGATIVE_VIEW_DEPTH) ? -1.0f : 1.0f;
    float3 viewSpacePos;

    [branch]
    if (IsSet(FLAGS_LINEAR_DEPTH))
    {
        // InDepth is the signed-linear output of FloorSeed. Scale the complete
        // view ray so XY and Z describe one internally consistent position.
        inDepth = depthSign * clamp(abs(inDepth), NearPlane, FarPlane);
        // Any non-degenerate NDC depth yields the same ray, because the result is
        // rescaled to inDepth below. Mid-range is the only choice that stays away
        // from the inverse projection's w == 0 singularity for every near/far
        // convention: standard-Z infinite is singular at 1.0, reversed-Z at 0.0.
        viewSpacePos = InvProjectPosition(float3(uv, 0.5f), InvProjMatrix);
        const float safeRayZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= inDepth / safeRayZ;
        viewSpacePos.z = inDepth;
    }
    else
    {
        // Retained as a defensive fallback for direct hardware-depth callers.
        viewSpacePos = InvProjectPosition(float3(uv, inDepth), InvProjMatrix);
        const float signedDepth = depthSign * clamp(abs(viewSpacePos.z), NearPlane, FarPlane);
        const float safeViewZ = (viewSpacePos.z < 0.0f)
            ? min(viewSpacePos.z, -1e-6f)
            : max(viewSpacePos.z, 1e-6f);
        viewSpacePos *= signedDepth / safeViewZ;
        viewSpacePos.z = signedDepth;
    }

    return viewSpacePos;
}

float3 GetWorldSurfaceNormalAt(int2 px)
{
    px = clamp(px, int2(0, 0), int2(DstTexSize.xy) - 1);
    float3 normal = InNormals[px + int2(InputBase1.xy)].xyz;
    if (IsSet(FLAGS_NORMALS_VIEW_SPACE))
        normal = mul((float3x3)InvViewMatrix, normal);

    const float normalLengthSq = dot(normal, normal);
    return isfinite(normalLengthSq) && normalLengthSq > 1e-8f
        ? normal * rsqrt(normalLengthSq)
        : float3(0.0f, 0.0f, 1.0f);
}

float GetRawRoughnessAt(int2 px)
{
    px = clamp(px, int2(0, 0), int2(DstTexSize.xy) - 1);
    const float4 normal = InNormals[px + int2(InputBase1.xy)];
    return saturate(IsSet(FLAGS_PACKED_ROUGHNESS)
        ? normal.a
        : InRoughness[px + int2(InputBase1.zw)]);
}

// Raw colour for a render-space pixel, taken from the title's colour subrect.
//
// The clamp runs on the render-space coordinate and the origin is added after it, in that
// order - the same two steps LoadLumaWindow5x5 takes. Clamping the texture coordinate instead
// bounds it by the render size, and that range is anchored at the texture origin: with a
// non-zero subrect the neighbourhood is read from pixels the render does not cover, and at the
// subrect's right and bottom edges the taps fold back into its interior instead of stopping at
// the edge.
half3 GetRawColorAt(int2 px)
{
    px = clamp(px, int2(0, 0), int2(DstTexSize.xy) - 1);
    return InColor[px + int2(InputBase0.xy)].rgb;
}

// The albedo outputs are 8-bit UNORM, so the value composition remodulates with is not the
// value this shader computed - it is round(x * 255) / 255. Demodulating against the computed
// value and closing the residual against it assumes a round trip the texture cannot perform,
// and the error is largest where the albedo is smallest: an albedo of 0.01 stores as 3/255,
// which returns 17.6% more light than the residual accounted for, and that surplus is added
// rather than filtered because the denoiser never saw it.
//
// Quantizing here, before the value is used for anything, makes the demodulation divisor,
// the residual closure and the stored texel one number, so an identity denoiser returns
// exactly what was demodulated. Saturating is part of the storage contract as well: a UNORM
// texel cannot hold a reflectance above 1, and the arithmetic has to agree with the texel
// rather than with the title's value.
//
// The level count is 2^bits - 1 for FSRDFormats::SpecAlbedo / DiffAlbedo in
// FSRDPreprocessor_Dx12.cpp; verify_fsrd_mirrors.py ties the two together, and the C++
// static_assert beside those formats fails the build if either stops being 8-bit UNORM.
static const float s_AlbedoStoreLevels = 255.0f;

float3 QuantizeStoredAlbedo(float3 albedo)
{
    // Every result is an exact multiple of 1/255, which is what makes the store lossless:
    // the FP16 conversion and the UNORM round-to-nearest that follow both land back on it.
    return round(saturate(albedo) * s_AlbedoStoreLevels) / s_AlbedoStoreLevels;
}

// Measures whether the title-provided albedos contain spatial material structure in
// the same surface/roughness neighborhood. This is diagnostic only: it neither
// synthesizes an albedo nor changes the signals sent to RR. Coherent vending-screen
// texture should appear bright, while a constant-white display albedo remains dark.
float GetAlbedoStructure(
    int2 centerPx, float centerDepth, float3 centerNormal,
    float centerRoughness, float3 centerSpecular, float3 centerDiffuse)
{
    const float centerSpecularLuma = GetLuminance(centerSpecular);
    const float centerDiffuseLuma = GetLuminance(centerDiffuse);
    const float depthTolerance = max(0.01f, abs(centerDepth) * 0.005f);
    float maximumDelta = 0.0f;

    [unroll]
    for (int y = -1; y <= 1; ++y)
    {
        [unroll]
        for (int x = -1; x <= 1; ++x)
        {
            const int2 samplePx = clamp(
                centerPx + int2(x, y), int2(0, 0), int2(DstTexSize.xy) - 1);
            const float sampleRoughness = GetRawRoughnessAt(samplePx);
            const float sampleDepth = GetViewSpacePos(samplePx).z;
            const float3 sampleNormal = GetWorldSurfaceNormalAt(samplePx);
            const bool sameSurface = isfinite(sampleDepth) &&
                abs(sampleDepth - centerDepth) <= depthTolerance &&
                dot(sampleNormal, centerNormal) >= 0.98f &&
                abs(sampleRoughness - centerRoughness) <= max(
                    2.0f / 1023.0f, centerRoughness * 0.05f);

            if (sameSurface)
            {
                const int2 sampleSpecPx = samplePx + int2(InputBase3.xy);
                const int2 sampleDiffPx = samplePx + int2(InputBase2.zw);
                const float sampleSpecularLuma = GetLuminance(max(
                    GetSafeFP16(InSpecAlbedo[sampleSpecPx].rgb), 0.0f));
                const float sampleDiffuseLuma = GetLuminance(max(
                    GetSafeFP16(InDiffAlbedo[sampleDiffPx].rgb), 0.0f));
                maximumDelta = max(maximumDelta, max(
                    abs(sampleSpecularLuma - centerSpecularLuma),
                    abs(sampleDiffuseLuma - centerDiffuseLuma)));
            }
        }
    }

    return saturate(maximumDelta * 8.0f);
}

float3 GetGuideAlbedoAt(int2 px)
{
    px = clamp(px, int2(0, 0), int2(DstTexSize.xy) - 1);
    const float3 spec =
        max((float3) GetSafeFP16(InSpecAlbedo[px + int2(InputBase3.xy)].rgb), 0.0f);
    const float3 diff =
        max((float3) GetSafeFP16(InDiffAlbedo[px + int2(InputBase2.zw)].rgb), 0.0f);
    return spec + diff;
}

[RootSignature(MainRS)]
[numthreads(THREAD_GROUP_SIZE_X, THREAD_GROUP_SIZE_Y, 1)]
void CSMain(uint3 groupID : SV_GroupID, uint3 gtID : SV_GroupThreadID)
{
    const uint2 px = groupID.xy * s_ThreadGroupSize + gtID.xy;
    const float2 uv = (float2(px) + 0.5f) * DstTexSize.zw;
    
    if (px.x >= DstTexSize.x || px.y >= DstTexSize.y)
        return;

    // Albedo / reflectance
    //
    // Zeroed albedos are unusable sentinels and must be skipped.
    // Depth values at the far plane indicate a skybox or other skippable content.
    //
    // DLSS-RR specular albedo is hemispherical specular reflectance at (NoV, roughness).
    // Diffuse albedo is the diffuse component of reflectance.     
    const int2 colorPx = int2(px) + int2(InputBase0.xy);
    const int2 normalPx = int2(px) + int2(InputBase1.xy);
    const int2 roughnessPx = int2(px) + int2(InputBase1.zw);
    const int2 diffAlbedoPx = int2(px) + int2(InputBase2.zw);
    const int2 specAlbedoPx = int2(px) + int2(InputBase3.xy);

    // Retained unmodified for the albedo-structure diagnostic, which must read the
    // title's values rather than the emissive-compatibility rewrite below.
    const float3 inputSpecReflectance =
        FloorRadiance(InSpecAlbedo[specAlbedoPx].rgb);
    const float3 inputDiffAlbedo =
        FloorRadiance(InDiffAlbedo[diffAlbedoPx].rgb);
    float3 specReflectance = inputSpecReflectance;
    float3 diffAlbedo = inputDiffAlbedo;
    const float rawRoughness = saturate(
        IsSet(FLAGS_PACKED_ROUGHNESS)
            ? InNormals[normalPx].a
            : InRoughness[roughnessPx]);

    // R10G10B10A2_UNORM stores material type in two normalized alpha bits.
    // Select only roughness values that quantize to exact zero, avoiding the
    // unstable 1/1023 boundary. All exact-zero candidates share type 1.
    // Material classification only; exact-zero roughness does not authorize detail.
    const float isZeroRoughness = step(rawRoughness, s_Type1RoughnessThreshold);

    const float totalAlbedo = dot(specReflectance.rgb + diffAlbedo.rgb, 1.0f);
    // Emissive reinterpretation, softened.
    //
    // As a hard step this flips per frame on any surface whose albedo sits near the
    // threshold - animated signage and video billboards in particular - and the two sides of
    // the branch demodulate very differently, so the classification itself becomes a source
    // of temporal instability. The transition band costs nothing.
    const float isEmissive = SoftAbove(totalAlbedo, 5.9f, 0.5f);
    // Emissive primary surfaces do not have a meaningful reflection hit distance.
    // Route their radiance through direct diffuse instead of disguising it as
    // indirect specular, where an invalid hit distance can deactivate denoising.
    static const float s_EmissiveSpecularWeight = 1e-4f;
    diffAlbedo.rgb = lerp(
        diffAlbedo.rgb, 1.0f - s_EmissiveSpecularWeight, isEmissive);
    specReflectance.rgb = lerp(
        specReflectance.rgb, s_EmissiveSpecularWeight, isEmissive);
    
    // Clamp albedo
    const float3 albedoOvershoot = max((specReflectance.rgb + diffAlbedo.rgb) - 1.0f, 0.0f);
    specReflectance.rgb = saturate(specReflectance.rgb - albedoOvershoot);
    diffAlbedo.rgb -= max((specReflectance.rgb + diffAlbedo.rgb) - 1.0f, 0.0f);

    // Everything downstream - the demodulation divisor, the residual closure, the albedos the
    // denoiser is handed and the ones composition remodulates with - has to be the value the
    // 8-bit texture holds, so the quantization is applied once here rather than modeled at
    // each use. A reflectance that rounds to zero is not a special case to guard against:
    // composition cannot remodulate it either, so its radiance belongs to the residual by the
    // same arithmetic that already routes it there, and the demodulation divisor carries its
    // own floor rather than depending on the albedo for one.
    specReflectance = QuantizeStoredAlbedo(specReflectance);
    diffAlbedo = QuantizeStoredAlbedo(diffAlbedo);
    
    const float4 detailReference = InDetailReference[px];
    // Keep the spatial light pedestal on zero-rough surfaces as well. Cap it to
    // the current signal in this domain so a dark glyph can never be filled by
    // F>C. The matching nonnegative residual then closes on C for identity RR.
    // This also protects flat volumetry; surface support cannot identify whether
    // the title composited a volume in front of the underlying material.
    const float3 rawColor = FloorRadiance(InColor[colorPx].rgb);
    const float rawLuma = GetLuminance(rawColor);
    float4 floorColor = IsSet(FLAGS_FLOOR_ENABLED) ? float4(InFloorColor[px]) : 0.0f;
    floorColor.rgb = FloorRadiance(floorColor.rgb);
    const float3 spatialFloor = isZeroRoughness > 0.0f
        ? min(floorColor.rgb, rawColor) : floorColor.rgb;
    const float3 floorExcess = max(spatialFloor - rawColor, 0.0f);
    const float biasMask = IsSet(FLAGS_HAS_BIAS_MASK)
        ? saturate((float)InBiasMask[px + int2(InputBase3.zw)]) : 0.0f;
    const float biasWeight = saturate(biasMask * BiasMaskStrength);
    // Route the mask independently: scaling both terms preserves the identity even
    // when the spatial estimate crosses above raw. No detail may touch routed content.
    floorColor.rgb = (1.0f - biasWeight) * spatialFloor + biasWeight * rawColor;
    float3 denoiserColor = (1.0f - biasWeight) * max(rawColor - spatialFloor, 0.0f);
    const float3 floorResidual = denoiserColor;



    // Depth - full position needed for reprojected depth delta
    const float3 viewSpacePos = GetViewSpacePos(px);
    // An infinite far plane reaches this shader as FLT_MAX. Normalising a log
    // against it puts log(3.4e38) = 88.7 in the denominator, which squeezes every
    // realistic depth into the bottom tenth of the range: the depth debug views
    // read as one flat colour, and the far-plane skip test below can never reach
    // its 0.99 threshold, so skybox rejection silently stops working. Normalise
    // against a finite horizon so both behave on infinite projections.
    const float finiteFarPlane = min(FarPlane, 65504.0f);
    const float compressedDepth =
        log(abs(viewSpacePos.z) + 1.0f) / log(finiteFarPlane + 1.0f);
    
    if (compressedDepth < 0.99f || IsSet(FLAGS_DEBUG))
    {
        // RR consumes world-space normals. DLSS-RR does not carry normal-space
        // metadata, so the feature exposes an explicit per-title setting.
        float4 worldSurfaceNormal = InNormals[normalPx];
        if (IsSet(FLAGS_NORMALS_VIEW_SPACE))
        {
            worldSurfaceNormal.xyz =
                mul((float3x3)InvViewMatrix, worldSurfaceNormal.xyz);
        }
        const float normalLengthSq = dot(worldSurfaceNormal.xyz, worldSurfaceNormal.xyz);
        worldSurfaceNormal.xyz = isfinite(normalLengthSq) && normalLengthSq > 1e-8f
            ? worldSurfaceNormal.xyz * rsqrt(normalLengthSq)
            : float3(0.0f, 0.0f, 1.0f);
        const float2 octNormal = OctahedralEncode(worldSurfaceNormal.rgb);
    
        // DLSS-RR provides 3D normals
        // Linear roughness optionally included in the A channel, or in a separate single-channel 
        // buffer (InRoughness).
        // Emission and microsurface roughness are independent material properties.
        // Preserve the game's roughness instead of coercing emissive surfaces into
        // perfect mirrors solely to route their radiance through the specular signal.
        const float inputRoughness = rawRoughness;

        // Preserve the RR material classification independently of detail confidence.
        const float materialType = isZeroRoughness * (1.0f / 3.0f);

        // Exact-zero roughness makes RR treat the surface as a perfect mirror. The
        // automatic compatibility value lifts it to one the denoiser can filter, and only
        // while Floor is enabled - with Floor disabled the title's roughness is published
        // untouched. The classification itself stays the title's exact-zero reading.
        const float appliedRoughness =
            (IsSet(FLAGS_FLOOR_ENABLED) ? 1.0f : 0.0f) * isZeroRoughness * s_ZeroRoughRRRoughness;
        const float roughness = max(inputRoughness, appliedRoughness);
        
        // Output: RG=OctNormal, B=Roughness, A=MaterialID
        OutNormals[px] = GetSafeFP16(float4(octNormal, roughness, materialType));
   
        // Motion Vectors & Depth Delta. XY is canonicalized once into unjittered
        // PreviousUV-CurrentUV. RR's B contract is the previous-camera depth of the
        // corresponding current surface minus its current depth; sampling B from the
        // XY destination would make RR's own disocclusion test validate that target
        // against itself.
        const float3 worldSpacePos = mul(InvViewMatrix, float4(viewSpacePos, 1.0f)).xyz;
        float3 prevViewSpacePos = mul(PrevViewMatrix, float4(worldSpacePos, 1.0f)).xyz;

        const float3 canonicalMotion = GetCanonicalMotionUv(px);

        // Specular motion tracking handover.
        //
        // Scaling the ray length by roughness is a continuous handover with a defensible
        // meaning: a shorter virtual hit distance places the reflection nearer the surface,
        // so the specular reprojects with the surface as the weight goes to zero. As a hard
        // cut it toggles per pixel and per frame wherever roughness varies around the
        // threshold - clearcoat, wet asphalt, painted metal at grazing angles - and each
        // toggle discontinuously changes how RR reprojects that pixel.
        //
        // Bias-masked pixels are excluded: their colour is not a surface reflection and the
        // hit distance that comes with them is not meaningful.
        const float specularTracking =
            SoftBelow(roughness, 0.30f, 0.15f) * (1.0f - isEmissive) * (1.0f - biasWeight);

        // The title's own statement that the specular signal's temporal history cannot be
        // trusted. Inert at zero, so it does nothing until asked for.
        const float responsivityRaw = IsSet(FLAGS_HAS_RESPONSIVITY_MASK)
            ? InResponsivityMask[px].r
            : 0.0f;

        // How much of the specular radiance leaves the temporal path, 0..1, driven only by the
        // title's own responsivity hint. A reflected-image motion field used to drive it too and
        // was measured harmful; see the rejected list in docs/fsrd_pipeline_contract.md.
        float specularRouteWeight = 0.0f;

        // A responsivity hint is a statement rather than a gradient, so it hands the pixel
        // over whole.
        if (IsSet(FLAGS_HAS_RESPONSIVITY_MASK) && ResponsivityTrustThreshold > 0.0f)
        {
            const bool unstable = ResponsivityInvert != 0u
                ? responsivityRaw > ResponsivityTrustThreshold
                : responsivityRaw < ResponsivityTrustThreshold;
            specularRouteWeight = max(specularRouteWeight, unstable ? 1.0f : 0.0f);
        }

        // The specular ray length feeds RR's indirect-specular signal. It does not
        // alter RR's primary-surface motion.
        const float rawHitDist = IsSet(FLAGS_HAS_SPEC_HIT_DISTANCE)
            ? InSpecHitDist[int2(px) + int2(InputBase5.zw)]
            : (IsSet(FLAGS_HAS_COMBINED_SPEC_HIT_DISTANCE)
                ? InSpecularRayDirectionHitDistance[
                    int2(px) + int2(InputBase5.zw)].a
                : s_InvalidSpecularHitDistance);
        const bool hasInputHitDist =
            isfinite(rawHitDist) && rawHitDist >= 0.0f && rawHitDist <= 65504.0f;
        // The title's classification is preserved verbatim: a finite value is a geometry hit and
        // FP16-max is a real environment miss, and primary-surface depth is not a substitute for
        // either. Where a title publishes neither - 007 First Light does not - the indirect path
        // falls back to the primary surface's view distance, because RR writes no denoised output
        // at all for a signal with no finite ray length. See the title quirks in
        // docs/fsrd_pipeline_contract.md.
        const float reflectionHitDistance = hasInputHitDist
            ? rawHitDist
            : (IsSet(FLAGS_SPECULAR_SIGNAL_INDIRECT)
                ? max(abs(viewSpacePos.z), 1e-3f)
                : s_InvalidSpecularHitDistance);

        const float2 motionUv = canonicalMotion.xy;
        const float depthDelta = isfinite(prevViewSpacePos.z)
            ? prevViewSpacePos.z - viewSpacePos.z
            : 0.0f;

        const float3 motionOut = float3(motionUv, depthDelta);
        OutMotion[px] = half4(GetSafeSignedFP16(motionOut), 0.0f);

        const float3 specWeight = saturate(specReflectance.rgb);
        const float3 diffWeight = saturate(diffAlbedo.rgb);
        // Split the composited radiance between the two signals by reflectance ratio. Where
        // both are effectively zero the ratio is meaningless, so the pixel goes down the
        // diffuse path - it carries no reprojection state and cannot smear.
        const float3 totalWeight = diffWeight + specWeight;
        const float3 specFraction = specWeight * rcp(max(totalWeight, DemodDivisorFloor));
        const float3 isSplitValid =
            smoothstep(0.5f * DemodDivisorFloor, DemodDivisorFloor, totalWeight);

        const float3 specularColor = denoiserColor * (specFraction * isSplitValid);
        const float3 diffuseColor = denoiserColor - specularColor;

        // A pixel the title itself reports as unresponsive cannot be reprojected with the
        // primary motion. Publish it through the skip signal instead - composition adds that at
        // full sharpness from the current frame - and hand the denoiser zero radiance there, so
        // there is no misaligned history to smear. Routing adds no further radiance.
        const float3 routedRadiance = specularColor * specularRouteWeight;
        floorColor.rgb += routedRadiance;

        // Demodulate against a floored divisor. The remodulation below runs on the same
        // stored albedo composition will remodulate with, so the only gap left is the one the
        // floor creates - the share of the divisor it could not represent - and the residual
        // catches exactly that rather than a quantization error compounded by it.
        //
        // The divisor carries its own floor: an albedo that quantizes to zero is a legitimate
        // stored value, so nothing upstream is a promise of a finite divisor any more. This
        // mirrors the lower bound the feature clamps DemodDivisorFloor to.
        const float3 specDenom = max(max(specReflectance.rgb, DemodDivisorFloor), 1e-4f);
        const float3 diffDenom = max(max(diffAlbedo.rgb, DemodDivisorFloor), 1e-4f);

        const half3 demodSpecular =
            GetSafeFP16((specularColor - routedRadiance) / specDenom);
        const float demodGain = rcp(min(GetLuminance(specDenom), GetLuminance(diffDenom)));

        const half3 demodDiffuse = GetSafeFP16(diffuseColor / diffDenom);

        // Anything that cannot survive modulation and FP16 clamping remains in the skip signal.
        const float3 remodColor = (demodSpecular * specReflectance.rgb) + (demodDiffuse * diffAlbedo.rgb);
        // The share of the pixel that modulation could not represent. It travels around the
        // denoiser in the skip signal, which is what preserves the pixel's energy - and also
        // what puts it on screen unfiltered, so it is the first place to look when the skip
        // signal reads noisier than the floor it also carries.
        const float3 unmappedShare = max(0.0f, denoiserColor - remodColor - routedRadiance);
        // The routed radiance is already part of the floor colour by this point, so this is the
        // floor's own share of the skip signal rather than a second contribution to it.
        const float3 skipFloorShare = floorColor.rgb;

        // Routed radiance is already in skip; count it once. Floor excess remains separate.
        floorColor.rgb += unmappedShare;

        // A finite value is a geometry hit and FP16-max is a real environment miss;
        // both are valid distances and are preserved verbatim.
        //
        // The negative fallback is the one value AMD's sample never emits - it writes
        // FP16-max even for pixels it did not trace. In practice the exposure is
        // small: the automatic specular classification only selects Indirect once a
        // validated hit-distance guide exists, and without one it selects Direct,
        // whose alpha the contract leaves undefined. A negative can therefore only
        // reach an Indirect dispatch on a per-pixel read that fails validation.
        //
        // RR's Virtual Hit Pos view reconstructs correctly on titles that supply the
        // guide, so this is a conformance gap rather than an observed fault.
        const half hitDist = IsSet(FLAGS_SPECULAR_SIGNAL_INDIRECT)
            ? half(reflectionHitDistance * specularTracking)
            : half(0.0f);

        [branch]
        if (!IsSet(FLAGS_DEBUG))
        {
            // Supply the real ray length whenever the title provides one. Without one
            // the pixel keeps the FP16-max miss, matching what AMD's sample writes for
            // its own untraced and sky pixels.
            float diffuseHitDist = s_MissingDiffuseHitDistance;
            [branch]
            if (DiffuseHitDistanceMode != 0u)
            {
                const int2 diffuseHitPx = int2(px) + int2(InputBase4.zw);
                const float4 diffuseHitSample = InDiffuseHitDistance[diffuseHitPx];
                const float rawDiffuseHit = DiffuseHitDistanceMode == 2u
                    ? diffuseHitSample.a
                    : diffuseHitSample.r;
                if (isfinite(rawDiffuseHit) && rawDiffuseHit >= 0.0f &&
                    rawDiffuseHit <= s_MaxRayHitDistance)
                {
                    diffuseHitDist = rawDiffuseHit;
                }
            }

            OutIndirectSpecular[px] = half4(demodSpecular, hitDist);
            OutDirectDiffuse[px] = half4(demodDiffuse, diffuseHitDist);
        }
        else
        {
            // A debug mode overwrites OutIndirectSpecular with the debug colour below,
            // but nothing writes u1. FLAGS_DEBUG also routes every pixel through this
            // branch, so the skip path no longer clears it either: without this write
            // the diffuse signal keeps the last non-debug frame for the whole session.
            OutDirectDiffuse[px] = half4(0.0f, 0.0f, 0.0f, s_MissingDiffuseHitDistance);
        }

        
        // How much of this pixel's radiance the denoiser receives through the specular signal
        // rather than the diffuse one. It is the albedo ratio's share of the demodulated split,
        // so it is the title's own material split rather than anything this shader decided, and
        // it is what the debug view and the probe both report.
        const float specularShare = saturate(GetLuminance(specularColor) *
                                            rcp(max(GetLuminance(denoiserColor), 1e-3f)));
        // The specular albedo's alpha has no consumer. Carry that share in it, so the probe can
        // report how much of the frame reaches the denoiser through the specular signal at all -
        // a signal it may then refuse to denoise if the ray-length guide is unusable.
        OutSpecAlbedo[px] = half4(GetSafeFP16(specReflectance), half(specularShare));
        // The diffuse albedo's alpha has no consumer. Carry whether this pixel's published floor
        // exceeds any raw channel, so the probe reports crossing pixels. Only the
        // corresponding channels' residuals collapse to zero.
        const float floorCrossing = any(floorExcess > 0.0f) ? 1.0f : 0.0f;
        OutDiffAlbedo[px] = half4(GetSafeFP16(diffAlbedo), half(floorCrossing));
        // Alpha reports the final skip luminance for diagnostics; composition only adds RGB.
        const float3 safeFloorColor = GetSafeFP16(floorColor.rgb);
        OutSkipSignal[px] = half4(safeFloorColor, GetLuminance(safeFloorColor));

        const bool allowDetail = IsSet(FLAGS_FLOOR_ENABLED) && FloorDetailPreservation > 0.0f &&
            detailReference.a >= 0.0f && biasWeight == 0.0f && specularRouteWeight == 0.0f;
        OutDetailReference[px] = half4(GetSafeFP16(detailReference.rgb),
            allowDetail ? half(max(detailReference.a, 0.0f)) : half(-1.0f));
        
        // Values the optional-input views below report, read once so every view shows
        // exactly what the logic above used. The title depth is no longer consumed by
        // any production path - the canonical copy in InDepth replaced it - so this is
        // strictly the raw published value the two title-depth views visualise.
        const float titleDepthRaw = IsSet(FLAGS_TITLE_LINEAR_DEPTH)
            ? InTitleLinearDepth[clamp(int2(px), int2(0, 0), int2(DstTexSize.xy) - 1) +
                                 int2(InputBase5.xy)]
            : 0.0f;

        [branch]
        if (IsSet(FLAGS_DEBUG))
        {
            float3 debugColor = float3(0, 0, 0);
        
            switch (GetDebugMode())
            {
                // Inputs
                case FLAGS_DEBUG_IN_SPEC_HIT_DIST:
                    // Magenta is an invalid/inactive indirect sample. Otherwise,
                    // logarithmic scaling keeps both nearby and distant hits
                    // visible without wrapping the color range.
                    debugColor = (hitDist < 0.0f)
                        ? float3(1.0f, 0.0f, 1.0f)
                        : TurboColormap(saturate(log2(max((float)hitDist, 0.0f) + 1.0f) / 16.0f));
                    break;
                
                case FLAGS_DEBUG_NORM_DEPTH:
                    debugColor = TurboColormap(compressedDepth);
                    break;
                
                case FLAGS_DEBUG_IN_MOTION:
                    debugColor = VisualizeMotionVec(motionUv * DstTexSize.xy, 0.1f);
                    break;
                
                case FLAGS_DEBUG_IN_NORMALS:
                    debugColor = worldSurfaceNormal.rgb * 0.5 + 0.5;
                    break;
                
                case FLAGS_DEBUG_IN_ROUGHNESS:
                    debugColor = inputRoughness;
                    break;
                
                case FLAGS_DEBUG_IN_DIFF_ALBEDO:
                    debugColor = InDiffAlbedo[diffAlbedoPx];
                    break;
                
                case FLAGS_DEBUG_IN_SPEC_ALBEDO:
                    debugColor = InSpecAlbedo[specAlbedoPx];
                    break;

                case FLAGS_DEBUG_IN_EMISSIVE:
                {
                    if (IsSet(FLAGS_HAS_EMISSIVE_INPUT))
                    {
                        const uint2 emissivePx = px + InputBase4.xy;
                        debugColor = InEmissive[emissivePx].rgb;
                    }
                    else
                    {
                        // Missing optional input. Magenta distinguishes absence from a valid black buffer.
                        debugColor = float3(1.0f, 0.0f, 1.0f);
                    }
                    break;
                }
                // Outputs
                case FLAGS_DEBUG_OUT_SIGNAL_SPLIT:
                    debugColor = demodSpecular + demodDiffuse;
                    break;
                
                case FLAGS_DEBUG_OUT_LINEAR_DEPTH:
                    // Linear against an adjustable full scale. The previous frac()
                    // encoding cycled every ten units, which aliases into a flat
                    // field at city depths and cannot be told apart from a depth
                    // buffer that is genuinely constant.
                    debugColor = TurboColormap(
                        saturate(abs(viewSpacePos.z) / max(DebugDepthMax, 1e-3f)));
                    break;
                
                case FLAGS_DEBUG_OUT_MOTION:
                    debugColor = VisualizeMotionVec(motionOut.xy * DstTexSize.xy, 0.1f);
                    break;

                case FLAGS_DEBUG_OUT_DEPTH_DELTA:
                    debugColor = VisualizeSignedDiff(motionOut.z, 5.0f);
                    break;
                
                case FLAGS_DEBUG_OUT_NORMALS:
                    debugColor = OctahedralDecode(octNormal) * 0.5 + 0.5;
                    break;

                case FLAGS_DEBUG_OUT_SPEC_ALBEDO:
                    debugColor = specReflectance.rgb;
                    break;
                
                case FLAGS_DEBUG_OUT_DIFF_ALBEDO:
                    debugColor = diffAlbedo.rgb;
                    break;

                case FLAGS_DEBUG_FLOOR_COLOR:
                    debugColor = InFloorColor[px].rgb;
                    break;

                case FLAGS_DEBUG_RAW_INDIRECT_SPEC:
                    // Match DenoisedSpecularSignal after remodulation.
                    debugColor = demodSpecular * specReflectance.rgb;
                    break;

                case FLAGS_DEBUG_EFFECTIVE_ROUGHNESS:
                    debugColor = roughness;
                    break;

                case FLAGS_DEBUG_RAW_ROUGHNESS:
                    debugColor = rawRoughness;
                    break;

                case FLAGS_DEBUG_EMISSIVE_MASK:
                    debugColor = isEmissive;
                    break;
                case FLAGS_DEBUG_APPLIED_ROUGHNESS:
                    // Turbo highlights the zero-rough domain; zero elsewhere.
                    debugColor = TurboColormap(saturate(
                        appliedRoughness / max(s_ZeroRoughRRRoughness, 2.0f / 1023.0f)));
                    break;
                case FLAGS_DEBUG_RESOURCE_INSPECTOR:
                    debugColor = saturate(InInspector[px][min(InspectorChannel, 3u)] * InspectorScale);
                    break;

                case FLAGS_DEBUG_MATERIAL_TYPE:
                    // Unified type 1 = white, type 0 = black.
                    debugColor = isZeroRoughness.xxx;
                    break;

                case FLAGS_DEBUG_RR_MATERIAL_TYPE:
                    // RR-facing encoded material type. Type 0 = black, type 1 = red,
                    // type 2 = green, type 3 = blue.
                    debugColor = materialType < (0.5f / 3.0f)
                        ? 0.0f
                        : (materialType < (1.5f / 3.0f)
                            ? float3(1.0f, 0.0f, 0.0f)
                            : (materialType < (2.5f / 3.0f)
                                ? float3(0.0f, 1.0f, 0.0f)
                                : float3(0.0f, 0.0f, 1.0f)));
                    break;

                case FLAGS_DEBUG_ALBEDO_STRUCTURE:
                {
                    // Unmasked by design: compare structured vending-machine albedo
                    // directly against the flat albedo supplied for Type-1 displays.
                    const float structure = GetAlbedoStructure(
                        int2(px), viewSpacePos.z, worldSurfaceNormal.xyz,
                        rawRoughness, inputSpecReflectance, inputDiffAlbedo);
                    debugColor = structure > 1e-4f
                        ? TurboColormap(structure)
                        : 0.0f;
                    break;
                }

                case FLAGS_DEBUG_FLOOR_RESIDUAL:
                    debugColor = floorResidual;
                    break;

                case FLAGS_DEBUG_ALBEDO_OVERSHOOT:
                    debugColor = albedoOvershoot;
                    break;

                // Optional-input validation views.

                // The specular signal's share of the demodulated split: how much of this pixel's
                // radiance the denoiser receives through the specular signal rather than the
                // diffuse one. Read from the albedo ratio, so it is the title's material split
                // rather than anything this shader decided.
                case FLAGS_DEBUG_SPECULAR_SPLIT:
                    debugColor = TurboColormap(specularShare);
                    break;

                case FLAGS_DEBUG_IN_TITLE_DEPTH:
                    debugColor = IsSet(FLAGS_TITLE_LINEAR_DEPTH)
                        ? TurboColormap(saturate(
                            abs(titleDepthRaw) / max(DebugDepthMax, 1e-3f)))
                        : float3(1.0f, 0.0f, 1.0f);
                    break;

                case FLAGS_DEBUG_TITLE_DEPTH_DIFF:
                {
                    // The title's published depth against the canonical field this chain
                    // actually consumes. Both come from the title's resource now - the
                    // canonical copy is what the floor seed built from it - so a black
                    // field means the canonicalisation changed nothing, and colour shows
                    // the sign and range adjustments it applied.
                    if (!IsSet(FLAGS_TITLE_LINEAR_DEPTH))
                        debugColor = float3(1.0f, 0.0f, 1.0f);
                    else
                    {
                        // Signed, not magnitude. A title's linear depth may be a positive
                        // distance while the canonical field is a signed view Z, and
                        // comparing magnitudes cannot see that. Green means the title
                        // reports the surface further along +Z than the canonical field
                        // carries, red means the opposite.
                        debugColor = VisualizeSignedDiff(titleDepthRaw - InDepth[px], 1.0f);
                    }
                    break;
                }

                // The two halves of the skip signal, separated. The floor share is what the
                // floor path contributes; the unmapped share is what modulation could not
                // represent and therefore reaches the screen without passing the denoiser.
                // Grain that lives in the second and not the first is not the floor's.
                case FLAGS_DEBUG_SKIP_UNMAPPED:
                    debugColor = TurboColormap(saturate(
                        GetLuminance(unmappedShare) * rcp(max(GetLuminance(rawColor), 1e-3f))));
                    break;

                case FLAGS_DEBUG_SKIP_FLOOR:
                    debugColor = TurboColormap(saturate(
                        GetLuminance(skipFloorShare) * rcp(max(GetLuminance(rawColor), 1e-3f))));
                    break;

                // Positive per-channel excess introduced where the spatial base crosses raw.
                case FLAGS_DEBUG_FLOOR_EXCESS:
                    debugColor = floorExcess;
                    break;

                case FLAGS_DEBUG_FLOOR_NOISE:
                    debugColor = TurboColormap(saturate(detailReference.a / max(rawLuma, 1e-3f)));
                    break;

                case FLAGS_DEBUG_IN_BIAS_MASK:
                    debugColor = TurboColormap(biasWeight);
                    break;

                // Demodulation amplification, log2 scaled over [1, 128]. Red areas are where
                // radiance noise is being multiplied hardest.
                case FLAGS_DEBUG_DEMOD_GAIN:
                    debugColor = TurboColormap(saturate(log2(max(demodGain, 1.0f)) * (1.0f / 7.0f)));
                    break;

                // The specular tracking ramp itself, separated from the buffer it scales.
                // Blue = closed (the specular reprojects with the surface), red = open.
                case FLAGS_DEBUG_HIT_DIST_GATE:
                    debugColor = TurboColormap(specularTracking);
                    break;

                case FLAGS_DEBUG_DENOISER_FRACTION:
                {
                    // Share of the pixel routed to the denoiser rather than around it through
                    // the skip signal. Blue = travelling around the denoiser, blurred by the
                    // floor; red = being denoised. Reflections and shadows reading blue is the
                    // floor capturing lighting it should have passed through.
                    const float rawLum = GetLuminance(rawColor);
                    const float denLum = GetLuminance(denoiserColor);
                    debugColor = TurboColormap(saturate(denLum * rcp(max(rawLum, 1e-3f))));
                    break;
                }

                case FLAGS_DEBUG_IN_RESPONSIVITY:
                    // Magenta when absent. The polarity is printed by the probe rather
                    // than assumed here, because it is a property of the title.
                    debugColor = IsSet(FLAGS_HAS_RESPONSIVITY_MASK)
                        ? TurboColormap(saturate(responsivityRaw))
                        : float3(1.0f, 0.0f, 1.0f);
                    break;
                
                default:
                    debugColor = demodSpecular + demodDiffuse;
                    break;
            }
        
            OutIndirectSpecular[px] = half4(debugColor, 1.0f);
        }
    }
    else // Skip
    {
        // FloorSeed temporarily stores depth gradients in OutMotion. Every packing
        // path must overwrite it before RR consumes the texture as motion vectors.
        OutMotion[px] = 0.0f;
        OutNormals[px] = 0.0f;
        OutSpecAlbedo[px] = 0.0f;
        OutDiffAlbedo[px] = 0.0f;
        OutIndirectSpecular[px] = half4(
            0.0f, 0.0f, 0.0f,
            IsSet(FLAGS_SPECULAR_SIGNAL_INDIRECT) ? s_InvalidSpecularHitDistance : 0.0f);
        OutDirectDiffuse[px] = half4(0.0f, 0.0f, 0.0f, s_MissingDiffuseHitDistance);
        // Nothing was demodulated on this path, so the composite colour passes through whole.
        OutSkipSignal[px] = half4(rawColor, rawLuma);
        // Far-plane skip has no trusted detail reference.
        OutDetailReference[px] = half4(0, 0, 0, -1);
    }
}
