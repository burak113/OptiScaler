// FSR-RR Conversion & Packing Shader
#include "FSRDPreprocessCommon.hlsli"

#define MainRS \
    "RootFlags(0), " \
    "CBV(b0), " \
    "DescriptorTable(SRV(t0, numDescriptors = 14), visibility = SHADER_VISIBILITY_ALL), " \
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

// Five-tap Gaussian run along the steered axis. Deliberately broad: the whole point
// of steering is that a long kernel is safe once it is known not to cross an edge.
static const float s_SteerWeights[5] = { 0.15f, 0.22f, 0.26f, 0.22f, 0.15f };

// Flags
#define FLAGS_NON_GAMMA_ALBEDO          (1 << 0)
#define FLAGS_LINEAR_DEPTH              (1 << 1)

#define FLAGS_PACKED_ROUGHNESS          (1 << 2)
#define FLAGS_NEGATIVE_VIEW_DEPTH       (1 << 3)
#define FLAGS_HAS_SPEC_HIT_DISTANCE     (1 << 4)
#define FLAGS_SPECULAR_SIGNAL_INDIRECT  (1 << 5)
#define FLAGS_HAS_EMISSIVE_INPUT        (1 << 6)
#define FLAGS_ZERO_ROUGH_HANDOVER       (1 << 7)
#define FLAGS_MOTION_VECTORS_JITTERED   (1 << 8)
#define FLAGS_DISPLAY_RESOLUTION_MOTION (1 << 9)
#define FLAGS_NORMALS_VIEW_SPACE        (1 << 11)
#define FLAGS_HAS_COMBINED_SPEC_HIT_DISTANCE (1 << 14)
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

#define FLAGS_DEBUG_FLOOR_VARIANCE      (16 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_FLOOR_COLOR         (17 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RAW_INDIRECT_SPEC   (18 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_EFFECTIVE_ROUGHNESS (19 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RAW_ROUGHNESS       (20 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_EMISSIVE_MASK       (21 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_APPLIED_ROUGHNESS_FLOOR (22 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RESOURCE_INSPECTOR  (23 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_MATERIAL_TYPE       (24 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_IN_EMISSIVE         (25 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_RR_MATERIAL_TYPE    (26 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_ALBEDO_STRUCTURE    (27 << 17 | FLAGS_DEBUG)
#define FLAGS_DEBUG_ZERO_ROUGH_FLOOR    (28 << 17 | FLAGS_DEBUG)

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

// RGB: the finished handover image for this pixel, A: 1 on handed-over pixels and 0
// everywhere else. Composition reads the weight rather than re-deriving which pixels
// qualify, so the type-1 classification lives in exactly one place.
RWTexture2D<half4> OutHandover : register(u7);

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
    
    float FloorIsolation;
    float RoughnessFloor;

    uint Flags;
    uint InspectorChannel;
    float InspectorScale;

    float DebugDepthMax;
    // 0 = absent, 1 = scalar in R, 2 = combined ray-direction resource, distance in A.
    uint DiffuseHitDistanceMode;

    // Blends the handover between FloorSeed's isotropic floor (0) and the selected
    // detail filter (1).
    float ZeroRoughDetail;
    // Which detail filter that blend targets. See ZERO_ROUGH_DETAIL_* below.
    uint ZeroRoughDetailMode;
    float _Padding0;
};

#define ZERO_ROUGH_DETAIL_HYBRID_MEDIAN 0u
#define ZERO_ROUGH_DETAIL_STEERED       1u
#define ZERO_ROUGH_DETAIL_KUWAHARA      2u
#define ZERO_ROUGH_DETAIL_ADAPTIVE_RANK 3u
#define ZERO_ROUGH_DETAIL_ALBEDO_GUIDED 4u

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

    // Do not reinterpret invalid vectors as stationary history. Retain a zero XY
    // fallback for RR; the caller uses the third helper component to decide whether
    // OutMotion.a may publish an independent predicted previous-surface depth.
    const bool valid = all(isfinite(rawMotion)) && all(isfinite(motionUv)) &&
        all(abs(motionUv) <= 16.0f);
    return float3(valid ? motionUv : 0.0f, valid ? 1.0f : 0.0f);
}

float3 GetViewSpacePos(const int2 px)
{
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

// Detail-preserving floor for the zero-roughness handover.
//
// FloorSeed's floor starts from a 5x5 full median, which is isotropic: it removes any
// feature thinner than roughly half its kernel. Glyph strokes on a display panel are
// one or two pixels wide at render resolution, so they are exactly what it deletes,
// and the a-trous passes then blend what survives into the surrounding colour.
//
// A hybrid median takes its medians ALONG the cross and diagonal directions and keeps
// the middle of those two plus the centre. Impulse noise loses in every direction and
// is still rejected, but a stroke that is coherent along its own axis wins in at least
// one, so thin lines, corners and text survive.
//
// The correction is applied as a luminance ratio, so the title's chroma is carried
// through untouched and a pixel whose brightness was never an outlier keeps its
// original colour exactly.
float3 GetDetailPreservingFloor(int2 centerPx, float3 centerColor, float centerLuma)
{
    const int2 maxBounds = int2(DstTexSize.xy) - 1;
    const int2 base = int2(InputBase0.xy);

#define FSRD_TAP_LUMA(ox, oy) GetLuminance((float3) GetSafeFP16( \
    InColor[clamp(centerPx + int2(ox, oy), int2(0, 0), maxBounds) + base].rgb))

    const float crossMedian = Median5(
        FSRD_TAP_LUMA(-1, 0), FSRD_TAP_LUMA(1, 0),
        FSRD_TAP_LUMA(0, -1), FSRD_TAP_LUMA(0, 1), centerLuma);
    const float diagonalMedian = Median5(
        FSRD_TAP_LUMA(-1, -1), FSRD_TAP_LUMA(1, -1),
        FSRD_TAP_LUMA(-1, 1), FSRD_TAP_LUMA(1, 1), centerLuma);

#undef FSRD_TAP_LUMA

    const float hybridLuma = Median3(crossMedian, diagonalMedian, centerLuma);
    return centerColor * (hybridLuma * rcp(max(centerLuma, 1e-4f)));
}

// Structure-tensor steered floor.
//
// The hybrid median above is a rank filter, so it only rejects samples that are
// outliers among their own neighbours. That works on isolated impulses and fails on
// clustered noise, where several adjacent samples are wrong together and none of them
// reads as an outlier. Averaging is what removes that, but an isotropic average is
// what destroys the text.
//
// This resolves the conflict by measuring which direction is safe to average in. The
// local gradient covariance - the structure tensor - has one eigenvector pointing
// across the dominant edge and one along it, and the gap between the eigenvalues says
// how strongly oriented the neighbourhood actually is. Running the kernel along the
// minor axis sends it down the length of a glyph stroke and never across it, so a
// stroke survives a far stronger blur than any isotropic kernel could apply. Where
// nothing is oriented - flat panel background, which is where the noise lives -
// coherence collapses and the result falls back to an isotropic mean, which is
// exactly the aggressive smoothing that region wants.
//
// Applied as a luminance ratio, so the title's chroma is carried through untouched.
// Shared 5x5 luminance window. Every detail filter below works from this, and all
// indices into it are compile-time, so it stays in registers rather than scratch.
void LoadLumaWindow5x5(int2 centerPx, out float window[25])
{
    const int2 maxBounds = int2(DstTexSize.xy) - 1;
    const int2 base = int2(InputBase0.xy);

    [unroll]
    for (int wy = 0; wy < 5; ++wy)
    {
        [unroll]
        for (int wx = 0; wx < 5; ++wx)
        {
            const int2 tapPx = clamp(
                centerPx + int2(wx - 2, wy - 2), int2(0, 0), maxBounds) + base;
            window[wy * 5 + wx] = GetLuminance((float3) GetSafeFP16(InColor[tapPx].rgb));
        }
    }
}

float3 GetSteeredFloor(int2 centerPx, float3 centerColor, float centerLuma)
{
    const int2 maxBounds = int2(DstTexSize.xy) - 1;
    const int2 base = int2(InputBase0.xy);

    // The tensor takes central differences across the inner 3x3, which reaches one
    // pixel beyond it in every direction.
    float window[25];
    LoadLumaWindow5x5(centerPx, window);

    // Gradient outer products over the inner 3x3, Gaussian weighted so the tensor
    // describes this pixel rather than its whole block.
    float jxx = 0.0f;
    float jxy = 0.0f;
    float jyy = 0.0f;

    [unroll]
    for (int gy = 1; gy <= 3; ++gy)
    {
        [unroll]
        for (int gx = 1; gx <= 3; ++gx)
        {
            const int idx = gy * 5 + gx;
            const float dx = 0.5f * (window[idx + 1] - window[idx - 1]);
            const float dy = 0.5f * (window[idx + 5] - window[idx - 5]);
            const float w = (gx == 2 && gy == 2)
                ? 4.0f
                : ((gx == 2 || gy == 2) ? 2.0f : 1.0f);

            jxx += w * dx * dx;
            jxy += w * dx * dy;
            jyy += w * dy * dy;
        }
    }

    // Closed-form eigenvalues of the symmetric 2x2.
    const float trace = jxx + jyy;
    const float delta = sqrt(max(Square(jxx - jyy) + 4.0f * Square(jxy), 0.0f));
    const float lambdaMajor = 0.5f * (trace + delta);

    // (major - minor) / (major + minor), which reduces to delta / trace. 1 means a
    // single dominant orientation, 0 means isotropic.
    const float coherence = saturate(delta * rcp(max(trace, 1e-6f)));

    // Eigenvector of the major eigenvalue points across the edge. Both closed forms
    // degenerate on different inputs, so take whichever is better conditioned.
    float2 across = float2(jxy, lambdaMajor - jxx);
    const float2 acrossAlt = float2(lambdaMajor - jyy, jxy);
    if (dot(acrossAlt, acrossAlt) > dot(across, across))
        across = acrossAlt;

    const float acrossLengthSq = dot(across, across);
    const float2 alongEdge = acrossLengthSq > 1e-12f
        ? float2(-across.y, across.x) * rsqrt(acrossLengthSq)
        : float2(1.0f, 0.0f);

    // Steered pass. InputConv binds no sampler, so taps are rounded to the nearest
    // texel; duplicates at small offsets simply reweight the centre.
    float steeredLuma = 0.0f;
    float steeredWeight = 0.0f;

    [unroll]
    for (int t = -2; t <= 2; ++t)
    {
        const int2 tapPx = clamp(
            centerPx + int2(round(alongEdge * float(t))), int2(0, 0), maxBounds) + base;
        const float w = s_SteerWeights[t + 2];
        steeredLuma += w * GetLuminance((float3) GetSafeFP16(InColor[tapPx].rgb));
        steeredWeight += w;
    }

    steeredLuma *= rcp(max(steeredWeight, 1e-6f));

    // Isotropic fallback for the incoherent case, reusing the window already loaded.
    float isotropicLuma = 0.0f;
    [unroll]
    for (int iy = 1; iy <= 3; ++iy)
    {
        [unroll]
        for (int ix = 1; ix <= 3; ++ix)
        {
            const float w = (ix == 2 && iy == 2)
                ? 4.0f
                : ((ix == 2 || iy == 2) ? 2.0f : 1.0f);
            isotropicLuma += w * window[iy * 5 + ix];
        }
    }
    isotropicLuma *= (1.0f / 16.0f);

    const float filteredLuma = lerp(isotropicLuma, steeredLuma, coherence);
    return centerColor * (filteredLuma * rcp(max(centerLuma, 1e-4f)));
}

// Generalized Kuwahara floor.
//
// Nine overlapping 3x3 candidate windows, one centred on each pixel of the inner 3x3.
// The lowest-variance candidate is the one least likely to straddle an edge, so
// publishing its mean smooths hard inside a region while never averaging across a
// boundary. Unlike a rank filter it is an averaging filter, so it clears clustered
// noise; unlike a plain blur it cannot bleed across a stroke.
//
// The classic four-quadrant form rounds corners badly, which matters for glyphs.
// Using nine symmetric candidates instead of four leaves a corner with a candidate
// that fits inside it.
float3 GetKuwaharaFloor(int2 centerPx, float3 centerColor, float centerLuma)
{
    float window[25];
    LoadLumaWindow5x5(centerPx, window);

    float bestMean = window[12];
    float bestVariance = 1e30f;

    [unroll]
    for (int cy = 1; cy <= 3; ++cy)
    {
        [unroll]
        for (int cx = 1; cx <= 3; ++cx)
        {
            float sum = 0.0f;
            float sumSq = 0.0f;

            [unroll]
            for (int sy = -1; sy <= 1; ++sy)
            {
                [unroll]
                for (int sx = -1; sx <= 1; ++sx)
                {
                    const float v = window[(cy + sy) * 5 + (cx + sx)];
                    sum += v;
                    sumSq += v * v;
                }
            }

            const float mean = sum * (1.0f / 9.0f);
            const float variance = GetVariance(sumSq * (1.0f / 9.0f), mean);

            if (variance < bestVariance)
            {
                bestVariance = variance;
                bestMean = mean;
            }
        }
    }

    return centerColor * (bestMean * rcp(max(centerLuma, 1e-4f)));
}

// Adaptive-radius rank floor.
//
// The classic adaptive median. A rank filter fails on clustered noise because a
// cluster is not an outlier among its own neighbours - but it stops being a cluster
// once the window is large enough to contain more clean samples than dirty ones. So
// rather than fixing a radius, this grows it only where the smaller window could not
// resolve a trustworthy median.
//
// Its key property is the one the hybrid median already showed matters here: whenever
// the centre is not itself an extreme of the smallest trustworthy window, the centre
// is published unchanged. Clean pixels come out bit-identical, text included, and only
// samples that genuinely look like impulses are replaced.
float3 GetAdaptiveRankFloor(int2 centerPx, float3 centerColor, float centerLuma)
{
    float window[25];
    LoadLumaWindow5x5(centerPx, window);

    const float center = window[12];

    // Inner 3x3.
    const float innerMedian = Median9(
        window[6], window[7], window[8],
        window[11], window[12], window[13],
        window[16], window[17], window[18]);

    // Extremes of the NEIGHBOURS, with the centre excluded.
    //
    // The question this filter asks is whether the centre is an outlier relative to
    // its surroundings, so the surroundings are the population and the centre is the
    // sample being tested. Including the centre makes the test partly circular: a
    // stroke peak is by definition the brightest pixel of its own neighbourhood, so a
    // window that counts it would find the centre equal to the maximum and reject the
    // very structure the filter exists to keep.
    float innerMin = window[6];
    float innerMax = window[6];
    [unroll]
    for (int iy = 1; iy <= 3; ++iy)
    {
        [unroll]
        for (int ix = 1; ix <= 3; ++ix)
        {
            if (ix == 2 && iy == 2)
                continue;

            const float v = window[iy * 5 + ix];
            innerMin = min(innerMin, v);
            innerMax = max(innerMax, v);
        }
    }

    // Full 5x5. The exact median of 25 needs a 131-comparator network, so this stays
    // an approximation - but a symmetric one.
    //
    // Median-of-row-medians alone is anisotropic: it resolves horizontal structure
    // differently from vertical, because rows are collapsed first and columns never
    // are. On a vertical glyph stem every row median lands off-stem and the estimate
    // is pulled away from the stem entirely, which matters here because this value is
    // not only a decision input - it is the replacement published for any pixel the
    // filter escalates to. Folding in the column pass and the exact inner median
    // cancels that orientation bias for the cost of five more Median5 calls.
    float rowMedians[5];
    float colMedians[5];
    [unroll]
    for (int ry = 0; ry < 5; ++ry)
    {
        rowMedians[ry] = Median5(
            window[ry * 5 + 0], window[ry * 5 + 1], window[ry * 5 + 2],
            window[ry * 5 + 3], window[ry * 5 + 4]);
        colMedians[ry] = Median5(
            window[0 * 5 + ry], window[1 * 5 + ry], window[2 * 5 + ry],
            window[3 * 5 + ry], window[4 * 5 + ry]);
    }

    const float outerMedian = Median3(
        Median5(rowMedians[0], rowMedians[1], rowMedians[2], rowMedians[3], rowMedians[4]),
        Median5(colMedians[0], colMedians[1], colMedians[2], colMedians[3], colMedians[4]),
        innerMedian);

    float outerMin = window[0];
    float outerMax = window[0];
    [unroll]
    for (int oi = 1; oi < 25; ++oi)
    {
        if (oi == 12)
            continue;

        outerMin = min(outerMin, window[oi]);
        outerMax = max(outerMax, window[oi]);
    }

    // How far each median sits from the extremes of its own window, as a fraction of
    // that window's range.
    //
    // A median pinned against an extreme means the window is mostly noise and the
    // median describes it badly; a centred one means the population is well resolved.
    // The classic algorithm makes this a hard yes/no, but the inputs are noisy, so a
    // pixel sitting near the boundary flips stages between frames - and with nothing
    // temporal in this path that reads as flicker. Grading the confidence lets the two
    // stages blend through the ambiguous band instead of snapping across it.
    //
    // Where both stages accept the centre the blend is the centre either way, so the
    // exact-centre property this filter depends on is untouched.
    const float innerRange = max(innerMax - innerMin, 1e-5f);
    const float outerRange = max(outerMax - outerMin, 1e-5f);

    const float innerConfidence = saturate(
        2.0f * min(innerMedian - innerMin, innerMax - innerMedian) / innerRange);
    const float outerConfidence = saturate(
        2.0f * min(outerMedian - outerMin, outerMax - outerMedian) / outerRange);

    // Acceptance by magnitude, not by rank.
    //
    // An impulse is a value separated from its population, not merely the largest of
    // its neighbours - and a stroke peak is always the largest of its neighbours. A
    // rank test cannot tell those apart, so it flattens every stroke peak in the
    // image while claiming to remove noise.
    //
    // The margin is a fraction of the neighbourhood's own range, which makes the test
    // self-scaling in the way this content needs: over flat panel background the
    // range collapses and the margin with it, so an isolated firefly is still
    // rejected outright, while across a stroke the range spans background to ink and
    // the peak is comfortably inside a generous margin. Nothing here needs an
    // absolute threshold, which is what previous attempts kept failing to calibrate.
    static const float s_ImpulseMargin = 0.5f;

    const float innerMargin = s_ImpulseMargin * innerRange;
    const float innerResult =
        (center >= innerMin - innerMargin && center <= innerMax + innerMargin)
            ? center
            : innerMedian;

    const float outerMargin = s_ImpulseMargin * outerRange;
    const float outerResult =
        (center >= outerMin - outerMargin && center <= outerMax + outerMargin)
            ? center
            : outerMedian;

    // Escalate only as far as the confidence warrants. The 3x3 answer is preferred
    // wherever it is well resolved, the 5x5 takes over as that confidence falls, and
    // when neither window resolves a trustworthy median the coarse median is all
    // that is left.
    const float result = lerp(
        lerp(outerMedian, outerResult, outerConfidence),
        innerResult,
        innerConfidence);

    return centerColor * (result * rcp(max(centerLuma, 1e-4f)));
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

// Albedo-guided joint bilateral floor.
//
// Every filter above has to infer where the edges are from the noisy signal itself.
// The albedo buffers are G-buffer data and carry no noise at all, so when the panel's
// structure is present in them they can supply edge weights directly - no inference,
// no chance of noise being mistaken for structure. That is the textbook arrangement
// for denoising a demodulated signal.
//
// The catch is that flat display albedo carries nothing to guide with, and then every
// weight collapses to one and this degenerates into a plain 5x5 blur. So the guide's
// own contrast is measured, and where it has none the result falls back to the hybrid
// median rather than smearing the panel.
float3 GetAlbedoGuidedFloor(int2 centerPx, float3 centerColor, float centerLuma)
{
    static const float s_GuideSpatial[5] = { 1.0f, 4.0f, 6.0f, 4.0f, 1.0f };
    static const float s_GuideSigma = 0.05f;

    float window[25];
    LoadLumaWindow5x5(centerPx, window);

    const float3 guideCenter = GetGuideAlbedoAt(centerPx);
    const float guideCenterLuma = GetLuminance(guideCenter);

    const float rcpSigmaSq = rcp(Square(s_GuideSigma));
    float guideMin = guideCenterLuma;
    float guideMax = guideCenterLuma;
    float weightedLuma = 0.0f;
    float totalWeight = 0.0f;

    [unroll]
    for (int wy = 0; wy < 5; ++wy)
    {
        [unroll]
        for (int wx = 0; wx < 5; ++wx)
        {
            const float3 guide = GetGuideAlbedoAt(centerPx + int2(wx - 2, wy - 2));
            const float guideLuma = GetLuminance(guide);
            guideMin = min(guideMin, guideLuma);
            guideMax = max(guideMax, guideLuma);

            // Rational falloff rather than an exponential: same shape where it
            // matters and no transcendental per tap.
            const float3 guideDelta = guide - guideCenter;
            const float rangeWeight = rcp(1.0f + dot(guideDelta, guideDelta) * rcpSigmaSq);
            const float weight = s_GuideSpatial[wx] * s_GuideSpatial[wy] * rangeWeight;

            weightedLuma += weight * window[wy * 5 + wx];
            totalWeight += weight;
        }
    }

    const float guidedLuma = weightedLuma * rcp(max(totalWeight, 1e-6f));
    const float3 guided = centerColor * (guidedLuma * rcp(max(centerLuma, 1e-4f)));

    // Below roughly one sigma of spread the guide is flat and tells us nothing.
    const float guideStructure = saturate((guideMax - guideMin) * rcp(s_GuideSigma));
    return lerp(
        GetDetailPreservingFloor(centerPx, centerColor, centerLuma),
        guided,
        guideStructure);
}

// Main Kernel
//
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
        max(GetSafeFP16(InSpecAlbedo[specAlbedoPx].rgb), 0.0f);
    const float3 inputDiffAlbedo =
        max(GetSafeFP16(InDiffAlbedo[diffAlbedoPx].rgb), 0.0f);
    float3 specReflectance = inputSpecReflectance;
    float3 diffAlbedo = inputDiffAlbedo;
    const float rawRoughness = saturate(
        IsSet(FLAGS_PACKED_ROUGHNESS)
            ? InNormals[normalPx].a
            : InRoughness[roughnessPx]);

    // R10G10B10A2_UNORM stores material type in two normalized alpha bits.
    // Select only roughness values that quantize to exact zero, avoiding the
    // unstable 1/1023 boundary. All exact-zero candidates share type 1.
    // Resolved here rather than at the normal write below because the floor split
    // needs it too.
    const float isZeroRoughness = step(rawRoughness, s_Type1RoughnessThreshold);

    const float totalAlbedo = dot(specReflectance.rgb + diffAlbedo.rgb, 1.0f);
    const float isEmissive = (totalAlbedo > 5.9f);
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
    specReflectance.rgb = max(specReflectance.rgb, 1e-4f);
    diffAlbedo.rgb = max(diffAlbedo.rgb, 1e-4f);
    
    // Denoiser input color and floor residual
    const float3 rawColor = GetSafeFP16(InColor[colorPx].rgb);
    const float rawLuma = GetLuminance(rawColor);
    float4 floorColor = InFloorColor[px];
    const float floorLuma = GetLuminance(floorColor.rgb);
    floorColor.a = floorLuma;

    // The filtered floor before any blend toward raw. This is the median and a-trous
    // result on its own, which is what the zero-roughness handover below publishes.
    const float3 filteredFloor = min(rawColor, floorColor.rgb);

    // Floor color blending
    //
    // Diffuse dominant surfaces are relatively well behaved.
    const float avgSpecular = dot(specReflectance.rgb, 0.33f);
    const float diffuseDominance = smoothstep(0.08f, 0.0f, avgSpecular);
    const float similarityThreshold = lerp(0.5f, 0.2f, diffuseDominance);

    // Clamp floor to minimum and blend in raw values where similar to preserve microcontrast.
    const float floorSimilarity = GetRelativeSimilarity(floorLuma, rawLuma, similarityThreshold);
    floorColor.rgb = FloorIsolation * lerp(floorColor.rgb, rawColor, saturate(floorSimilarity));
    floorColor.rgb = min(rawColor, floorColor.rgb);
    float3 denoiserColor = rawColor - floorColor.rgb;

    // Zero-roughness handover
    //
    // RR reads exact-zero roughness as a perfect mirror and reprojects it through a
    // virtual hit position derived from the specular ray length. Titles that publish
    // no such length leave that reconstruction undefined, so RR accumulates confident
    // but misaligned history over these surfaces. Hand them to the spatial floor
    // instead and withhold the residual, which is the high-frequency part the floor's
    // median and a-trous passes already rejected. This is a spatial denoise, not a
    // passthrough: the published colour is the filtered floor, never the raw input.
    // Every type-1 pixel is handed over whole. A partial handover only ever produced a
    // ratio of the two paths' faults, and composition now separates them by frequency
    // instead, which is a better answer to the same question.
    const float zeroRoughHandover = IsSet(FLAGS_ZERO_ROUGH_HANDOVER) ? isZeroRoughness : 0.0f;

    // The isotropic floor is the wrong tool for panel content: it is what removes the
    // text. Blend toward a directional median that keeps thin structure and leaves
    // non-outlier pixels at their original colour.
    float3 handoverColor = filteredFloor;
    [branch]
    if (zeroRoughHandover > 0.0f)
    {
        float3 detailFloor;
        switch (ZeroRoughDetailMode)
        {
            case ZERO_ROUGH_DETAIL_STEERED:
                detailFloor = GetSteeredFloor(int2(px), rawColor, rawLuma);
                break;
            case ZERO_ROUGH_DETAIL_KUWAHARA:
                detailFloor = GetKuwaharaFloor(int2(px), rawColor, rawLuma);
                break;
            case ZERO_ROUGH_DETAIL_ADAPTIVE_RANK:
                detailFloor = GetAdaptiveRankFloor(int2(px), rawColor, rawLuma);
                break;
            case ZERO_ROUGH_DETAIL_ALBEDO_GUIDED:
                detailFloor = GetAlbedoGuidedFloor(int2(px), rawColor, rawLuma);
                break;
            default:
                detailFloor = GetDetailPreservingFloor(int2(px), rawColor, rawLuma);
                break;
        }

        handoverColor = lerp(filteredFloor, detailFloor, saturate(ZeroRoughDetail));
    }

    // RR's input is never attenuated. The two paths meet in composition, where they
    // are separated by frequency rather than mixed by ratio, so RR stays on the
    // absolute scale its radiance clipping and learned noise priors expect.

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
    
    if (((compressedDepth < 0.99f) && totalAlbedo > 1e-2f) || IsSet(FLAGS_DEBUG))
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

        // isZeroRoughness is resolved above, where the floor split also consumes it.
        const float materialType = isZeroRoughness * (1.0f / 3.0f);

        // Exact-zero roughness makes RR treat the surface as a perfect mirror. The
        // optional compatibility floor lifts it to a value the denoiser can filter.
        const float appliedRoughnessFloor =
            saturate(RoughnessFloor) * isZeroRoughness;
        const float roughness = max(inputRoughness, appliedRoughnessFloor);
        
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
        // Preserve the title's specular-ray classification verbatim. A finite value is
        // a geometry hit and FP16_MAX is a real environment miss; primary-surface depth
        // is not a substitute for either.
        const float reflectionHitDistance = hasInputHitDist
            ? rawHitDist
            : s_InvalidSpecularHitDistance;

        const float2 motionUv = canonicalMotion.xy;
        const float depthDelta = isfinite(prevViewSpacePos.z)
            ? prevViewSpacePos.z - viewSpacePos.z
            : 0.0f;

        const float3 motionOut = float3(motionUv, depthDelta);
        OutMotion[px] = half4(GetSafeSignedFP16(motionOut), 0.0f);

        const float3 specWeight = saturate(specReflectance.rgb);
        const float3 diffWeight = saturate(diffAlbedo.rgb);
        const float3 rcpTotalWeight = rcp(diffWeight + specWeight);
        const float3 specularColor = denoiserColor * (specWeight * rcpTotalWeight);
        const float3 diffuseColor = denoiserColor - specularColor;

        const half3 demodSpecular = GetSafeFP16(specularColor / specReflectance.rgb);
        const half3 demodDiffuse = GetSafeFP16(diffuseColor / diffAlbedo.rgb);

        // Anything that cannot survive modulation and FP16 clamping remains in the skip signal.
        const float3 remodColor = (demodSpecular * specReflectance.rgb) + (demodDiffuse * diffAlbedo.rgb);
        floorColor.rgb += max(0.0f, denoiserColor - remodColor);

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
            ? half(reflectionHitDistance)
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

        // May be for better perceptual encoding efficiency in some configurations.
        //
        // WARNING: demodulation above divided by the LINEAR reflectance, but both
        // consumers (FSRDOutputComp and the structured-proxy/detail passes) remodulate with
        // whatever is stored here. Taking this branch therefore multiplies by
        // sqrt(a) where it divided by a, brightening every surface with albedo < 1.
        // It is currently unreachable because FSRDFeature_Dx12 always sets
        // NonGammaAlbedo; making the flag configurable requires matching the
        // demodulation above and both remodulation sites first.
        [branch]
        if (!IsSet(FLAGS_NON_GAMMA_ALBEDO))
        {
            specReflectance = sqrt(specReflectance);
            diffAlbedo = sqrt(diffAlbedo);
        }
        
        OutSpecAlbedo[px] = half4(GetSafeFP16(specReflectance), 0.0f);
        OutDiffAlbedo[px] = half4(GetSafeFP16(diffAlbedo), 0.0f);
        // Skip-signal alpha is the luminance of its own RGB - the composition pass
        // adds it to the denoised luminance to build the raw-correlation reference,
        // and the skip path below writes it that way. floorColor.rgb has been
        // rewritten three times since floorLuma was sampled (isolation blend, raw
        // clamp, unrepresentable residual), so derive it from the final colour
        // instead of shipping the stale raw-floor luminance.
        // Emissive rejoins here rather than in the denoised signal, so composition
        // restores it at full sharpness alongside the floor.
        const float3 safeFloorColor = GetSafeFP16(floorColor.rgb);
        OutSkipSignal[px] = half4(safeFloorColor, GetLuminance(safeFloorColor));

        OutHandover[px] = half4(GetSafeFP16(handoverColor), half(zeroRoughHandover));
        
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

                case FLAGS_DEBUG_FLOOR_VARIANCE:
                    debugColor = TurboColormap(InFloorColor[px].a);
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
                case FLAGS_DEBUG_APPLIED_ROUGHNESS_FLOOR:
                    debugColor = (appliedRoughnessFloor > 0.0f)
                        ? TurboColormap(saturate(
                            appliedRoughnessFloor / max(RoughnessFloor, 2.0f / 1023.0f)))
                        : 0.0f;
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

                case FLAGS_DEBUG_ZERO_ROUGH_FLOOR:
                    // What the handover actually publishes. Non-handover pixels stay
                    // black so the affected surfaces are unambiguous, and the colour
                    // shown is the exact value composition will receive.
                    debugColor = zeroRoughHandover > 0.0f ? handoverColor : 0.0f;
                    break;

                case FLAGS_DEBUG_ALBEDO_OVERSHOOT:
                    debugColor = albedoOvershoot;
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
        // Skipped pixels have no handover image; a zero weight leaves composition's
        // own result untouched.
        OutHandover[px] = 0.0f;
    }
}
