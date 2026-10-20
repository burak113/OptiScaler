// Job 07, observation only. No production input is an output of this pass.
// Reference: ../src/foliage_guides.py, observe_guides().
// Pending local compilation/parity: cs_6_2, CSMain, -HV 2021 -O3 -Gis.
// Read the exact host admission/lifetime contract in PRODUCTION_SPEC.md.

#define MainRS \
    "RootFlags(0), RootConstants(num32BitConstants=16,b0), " \
    "DescriptorTable(SRV(t0,numDescriptors=5)), " \
    "DescriptorTable(UAV(u0,numDescriptors=2))"

Texture2D<float4> CurrentNormalRoughness : register(t0);
Texture2D<float> CurrentDepth : register(t1);
Texture2D<float4> CurrentMotion : register(t2);
Texture2D<float4> PreviousNormalRoughness : register(t3);
Texture2D<float> PreviousDepth : register(t4);
RWTexture2D<float4> Observation : register(u0); // R32G32B32A32_FLOAT
RWTexture2D<uint> SupportFlags : register(u1); // R16_UINT, not a native guide channel

// Four 16-byte registers, 16 DWORDs total. See INTERFACE.json byte offsets.
cbuffer ObservationConstants : register(b0)
{
    uint2 CurrentExtent;                 // 0, 8 bytes, width/height
    uint2 PreviousExtent;                // 8, 8 bytes, width/height
    uint2 RenderExtent;                  // 16, 8 bytes, original full render
    float2 CurrentCropOrigin;            // 24, 8 bytes, original render pixels
    float2 PreviousCropOrigin;           // 32, 8 bytes, original render pixels
    uint Enabled;                       // 40, 4 bytes
    uint Chronological;                 // 44, 4 bytes, host-proven pair admission
    uint CurrentPositiveLinearDepth;     // 48, 4 bytes, explicit semantic admission
    uint PreviousPositiveLinearDepth;    // 52, 4 bytes
    float DepthRelativeTolerance;        // 56, 4 bytes, default 0.02
    uint Reserved;                       // 60, 4 bytes, must be zero
}

static const uint CURRENT_FINITE = 1u;
static const uint SPATIAL = 2u;
static const uint MOTION_FINITE = 4u;
static const uint CHRONOLOGICAL = 8u;
static const uint IN_PREVIOUS_CROP = 16u;
static const uint CATEGORY_MATCH = 32u;
static const uint DEPTH_MATCH = 64u;
static const uint TEMPORAL_SUPPORTED = 128u;

precise float OrderedSquaredLength(float3 v)
{
    precise float sum = v.x * v.x;
    sum = sum + v.y * v.y;
    sum = sum + v.z * v.z;
    return sum;
}

precise float3 UnitNormal(float3 v)
{
    precise float magnitude = sqrt(OrderedSquaredLength(v));
    return v / max(magnitude, 1e-20f);
}

// The host binds the real RGB10A2_UNORM view. Recover exact 10-bit integers
// before explicit division so no R32_UINT reinterpretation is assumed.
precise float3 DecodeNormal(float4 packed)
{
    const uint2 bits = uint2(round(packed.xy * 1023.0f));
    precise float2 uv = float2(bits) / 1023.0f;
    uv = uv * 2.0f - 1.0f;
    precise float z = 1.0f - abs(uv.x);
    z = z - abs(uv.y);
    const float t = max(-z, 0.0f);
    precise float3 n = float3(uv.x + (uv.x >= 0.0f ? -t : t),
                              uv.y + (uv.y >= 0.0f ? -t : t), z);
    return UnitNormal(n);
}

uint DecodeCategory(float4 packed)
{
    return uint(round(packed.a * 3.0f)); // Equality code only; zero is valid.
}

bool FinitePositiveDepth(float depth)
{
    return isfinite(depth) && depth > 0.0f;
}

precise float AngularDisagreement(float3 a, float3 b)
{
    precise float sum = a.x * b.x;
    sum = sum + a.y * b.y;
    sum = sum + a.z * b.z;
    return clamp(1.0f - sum, 0.0f, 2.0f);
}

[RootSignature(MainRS)]
[numthreads(8,8,1)]
void CSMain(uint3 dispatchThreadId : SV_DispatchThreadID)
{
    const uint2 p = dispatchThreadId.xy;
    if (any(p >= CurrentExtent)) return;
    // The real host OFF path records no pass and allocates no observation.
    // This branch is the isolated-kernel OFF parity control, including no SRV reads.
    if (Enabled == 0u)
    {
        Observation[p] = float4(0.0f, 0.0f, 0.0f, 1.0f);
        SupportFlags[p] = 0u;
        return;
    }

    const float4 currentPacked = CurrentNormalRoughness.Load(int3(p, 0));
    const float3 n = DecodeNormal(currentPacked);
    const uint category = DecodeCategory(currentPacked);
    const float depth = CurrentDepth.Load(int3(p, 0));
    const bool currentFinite = FinitePositiveDepth(depth) && all(isfinite(n));
    uint flags = currentFinite ? CURRENT_FINITE : 0u;
    precise float3 normalSum = 0.0f;
    uint count = 0u;
    float minimumDepth = asfloat(0x7f800000u);
    float maximumDepth = asfloat(0xff800000u);
    [unroll] for (int dy = -1; dy <= 1; ++dy)
    {
        [unroll] for (int dx = -1; dx <= 1; ++dx)
        {
            // NumPy's source/destination slices reverse the iteration delta.
            // Keep its exact top-level accumulation order, not only its footprint.
            const int2 q = int2(p) - int2(dx, dy);
            if (all(q >= 0) && all(q < int2(CurrentExtent)))
            {
                const float neighborDepth = CurrentDepth.Load(int3(q, 0));
                const float3 neighborNormal = DecodeNormal(CurrentNormalRoughness.Load(int3(q, 0)));
                if (FinitePositiveDepth(neighborDepth) && all(isfinite(neighborNormal)))
                {
                    normalSum = normalSum + neighborNormal;
                    count += 1u;
                    minimumDepth = min(minimumDepth, neighborDepth);
                    maximumDepth = max(maximumDepth, neighborDepth);
                }
            }
        }
    }
    const bool spatialSupported = currentFinite && count >= 3u;
    float dispersion = 0.0f;
    float relativeDepthSpan = 0.0f;
    if (spatialSupported)
    {
        flags |= SPATIAL;
        precise float3 meanNormal = normalSum / float(max(count, 1u));
        dispersion = clamp(1.0f - sqrt(OrderedSquaredLength(meanNormal)), 0.0f, 1.0f);
        precise float rawSpan = (maximumDepth - minimumDepth) / max(depth, 1e-20f);
        // Diagnostic range saturation matches the CPU hardening. It does not
        // claim the clamped input is a physically supported surface.
        relativeDepthSpan = isfinite(rawSpan) ? max(rawSpan, 0.0f) :
                            (rawSpan > 0.0f ? asfloat(0x7f7fffffu) : 0.0f);
    }
    const float4 motion = CurrentMotion.Load(int3(p, 0));
    const bool finiteMotion = all(isfinite(motion.xyz));
    if (finiteMotion) flags |= MOTION_FINITE;
    precise float innovation = 0.0f;
    float multiplier = 1.0f;

    if (Chronological != 0u)
    {
        flags |= CHRONOLOGICAL;
        // Explicit ordered arithmetic matches the CPU coordinate formula.
        precise float2 previousPixel = float2(p) + CurrentCropOrigin;
        previousPixel = previousPixel - PreviousCropOrigin;
        previousPixel = previousPixel + motion.xy * float2(RenderExtent);
        const bool inside = all(isfinite(motion.xy)) && all(isfinite(previousPixel)) &&
                            all(previousPixel >= 0.0f) &&
                            all(previousPixel < float2(PreviousExtent) - 1.0f);
        if (inside)
        {
            flags |= IN_PREVIOUS_CROP;
            // Test the entire float footprint BEFORE casting. Huge finite motion
            // never becomes an out-of-range integer coordinate or a clamped history.
            const int2 q = int2(floor(previousPixel));
            precise float2 f = previousPixel - float2(q);
            const int2 offsets[4] = {int2(0,0), int2(1,0), int2(0,1), int2(1,1)};
            precise float weights[4];
            weights[0] = (1.0f - f.x) * (1.0f - f.y);
            weights[1] = f.x * (1.0f - f.y);
            weights[2] = (1.0f - f.x) * f.y;
            weights[3] = f.x * f.y;
            precise float predictedDepth = depth + motion.z;
            const bool validPrediction = FinitePositiveDepth(predictedDepth);
            const float safePrediction = validPrediction ? predictedDepth : 0.0f;
            bool previousFinite = true;
            bool categoryMatch = true;
            bool depthMatch = validPrediction;
            precise float angular = 0.0f;
            [unroll] for (uint index = 0u; index < 4u; ++index)
            {
                const int2 priorPixel = q + offsets[index];
                const float priorDepth = PreviousDepth.Load(int3(priorPixel, 0));
                const float4 priorPacked = PreviousNormalRoughness.Load(int3(priorPixel, 0));
                const float3 priorNormal = DecodeNormal(priorPacked);
                previousFinite = previousFinite && FinitePositiveDepth(priorDepth);
                categoryMatch = categoryMatch && DecodeCategory(priorPacked) == category;
                const float scale = max(max(abs(safePrediction), abs(priorDepth)), 1e-6f);
                depthMatch = depthMatch && abs(safePrediction - priorDepth) <= DepthRelativeTolerance * scale;
                // Deliberately evaluate all four point taps, including zero-weight
                // taps, for finite/category/depth support. No D3D sampler is used.
                angular = angular + weights[index] * AngularDisagreement(n, priorNormal);
            }
            if (categoryMatch) flags |= CATEGORY_MATCH;
            const bool trustedDepth = CurrentPositiveLinearDepth != 0u && PreviousPositiveLinearDepth != 0u;
            if (previousFinite && depthMatch && trustedDepth) flags |= DEPTH_MATCH;
            if (currentFinite && finiteMotion && previousFinite && categoryMatch && depthMatch && trustedDepth)
            {
                flags |= TEMPORAL_SUPPORTED;
                innovation = angular;
                multiplier = clamp(1.0f - angular, 0.0f, 1.0f);
            }
        }
    }
    Observation[p] = float4(dispersion, relativeDepthSpan, innovation, multiplier);
    SupportFlags[p] = flags;
}
