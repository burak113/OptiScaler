// Job 05 research adapter, glass-correction-uncertainty-v1.
// CPU counterpart: src/glass_candidate.py::shrink_specular.
// This shader is NOT connected to the native graph. No CSO/header is supplied.
// OFF in production means no additional dispatch; Enabled=0 is a parity control.
// Physical linear specular RGB only, before the EXISTING Glass policy.
// Separate immutable SRVs and output UAV are mandatory; never dispatch in-place.
#define MainRS "RootFlags(0), CBV(b0), DescriptorTable(SRV(t0, numDescriptors = 5)), DescriptorTable(UAV(u0, numDescriptors = 1))"

Texture2D<float4> InRawRR : register(t0);       // Original physical raw RR lobe.
Texture2D<float4> InSelectedNZR : register(t1); // Pre-Glass S, float32 scratch.
Texture2D<uint> InEligible : register(t2);      // Immutable BASE mask, R32_UINT.
Texture2D<float2> InUncertainty : register(t3); // trace Cov(S-R), effective count.
Texture2D<int4> InSupport : register(t4);       // valid, spatial independence, surface, version.
RWTexture2D<float4> OutPreGlass : register(u0); // R32G32B32A32_FLOAT, distinct resource.

cbuffer GlassConstants : register(b0)
{
    uint2 Size;
    uint Enabled;          // Default zero; host must also skip scheduling when OFF.
    uint ContractVersion;  // Exactly 1 for this ABI.
    float NoiseScale;      // Preregistered value 1.0; finite and >= 0.
    float MinEffectiveCount; // Preregistered value 8.0; finite and >= 2.
    uint2 Reserved;        // Must be zero; source epoch/provenance checked by host.
}

static const float HalfMax = 65504.0f;

bool ValidRadiance(float3 value)
{
    return all(isfinite(value)) && all(value >= 0.0f) && all(value <= HalfMax);
}

[RootSignature(MainRS)]
[numthreads(8, 8, 1)]
void CSMain(uint3 dispatch : SV_DispatchThreadID)
{
    const uint2 p = dispatch.xy;
    if (any(p >= Size)) return;
    const float4 original = InSelectedNZR[p];
    // No optional sidecar read before the OFF branch. This is a shader parity
    // control, not evidence of native no-dispatch OFF equivalence.
    if (Enabled == 0u || ContractVersion != 1u || any(Reserved != 0u) ||
        !isfinite(NoiseScale) || NoiseScale < 0.0f ||
        !isfinite(MinEffectiveCount) || MinEffectiveCount < 2.0f)
    {
        OutPreGlass[p] = original;
        return;
    }

    // Full-render origin (0,0) is required. Never reset block phase at an odd
    // crop origin; job 08 must pass an even aligned crop or dispatch full frame.
    const uint2 origin = p & uint2(0xfffffffeu, 0xfffffffeu);
    if (any(origin + uint2(1u, 1u) >= Size))
    {
        OutPreGlass[p] = original;
        return;
    }

    precise float3 raw[4];
    precise float3 correction[4];
    precise float noise[4];
    int surface = -1;
    bool supported = true;
    [unroll] for (uint i = 0u; i < 4u; ++i)
    {
        const uint2 q = origin + uint2(i & 1u, i >> 1u);
        const float3 r = InRawRR[q].rgb;
        const float3 s = InSelectedNZR[q].rgb;
        const float2 uncertainty = InUncertainty[q];
        const int4 support = InSupport[q];
        const bool valid = InEligible[q] != 0u && support.x != 0 && support.y != 0 &&
            support.z >= 0 && support.w == 1 && all(isfinite(uncertainty)) &&
            uncertainty.x >= 0.0f && uncertainty.y >= MinEffectiveCount &&
            ValidRadiance(r) && ValidRadiance(s);
        if (i == 0u) surface = support.z;
        supported = supported && valid && support.z == surface;
        // Unsupported values are arithmetically inert before the shared-block
        // decision. No input alpha/hit distance is repurposed as uncertainty.
        raw[i] = valid ? r : 0.0f;
        correction[i] = valid ? s - r : 0.0f;
        noise[i] = valid ? uncertainty.x : 0.0f;
    }
    if (!supported)
    {
        OutPreGlass[p] = original;
        return;
    }

    const float3 a = correction[0], b = correction[1];
    const float3 c = correction[2], d = correction[3];
    precise float3 ll = 0.5f * (a + b + c + d);
    precise float3 high[3];
    high[0] = 0.5f * (a - b + c - d);
    high[1] = 0.5f * (a + b - c - d);
    high[2] = 0.5f * (a - b - c + d);
    // +/-1/2 orthonormal coefficients. This variance formula REQUIRES proven
    // spatial independence of correction noise in these four samples.
    precise float variance = 0.25f * (noise[0] + noise[1] + noise[2] + noise[3]);
    precise float scaledVariance = NoiseScale * variance;
    if (!isfinite(scaledVariance))
    {
        OutPreGlass[p] = original;
        return;
    }
    bool needsChange = false;
    [unroll] for (uint i = 0u; i < 3u; ++i)
    {
        precise float energy = high[i].x * high[i].x + high[i].y * high[i].y + high[i].z * high[i].z;
        precise float gain = saturate(1.0f - scaledVariance / max(energy, 1e-30f));
        needsChange = needsChange || (gain < 1.0f && energy > 0.0f);
        high[i] *= gain;
    }
    // Avoid changing constant/zero-variance corrections by round-trip rounding.
    if (!needsChange)
    {
        OutPreGlass[p] = original;
        return;
    }

    precise float3 reconstructed[4];
    reconstructed[0] = raw[0] + 0.5f * (ll + high[0] + high[1] + high[2]);
    reconstructed[1] = raw[1] + 0.5f * (ll - high[0] + high[1] - high[2]);
    reconstructed[2] = raw[2] + 0.5f * (ll + high[0] - high[1] - high[2]);
    reconstructed[3] = raw[3] + 0.5f * (ll - high[0] - high[1] + high[2]);
    bool inRange = true;
    [unroll] for (uint i = 0u; i < 4u; ++i) inRange = inRange && ValidRadiance(reconstructed[i]);
    // Reject the WHOLE block on a range violation; per-channel clipping would
    // violate the low-band constraint. Final native policy still sanitizes.
    const uint index = (p.x & 1u) + 2u * (p.y & 1u);
    OutPreGlass[p] = inRange ? float4(reconstructed[index], original.a) : original;
}
