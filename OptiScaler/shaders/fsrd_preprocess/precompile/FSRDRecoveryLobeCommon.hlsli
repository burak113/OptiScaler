// Recovery v2 lobe recovery: helpers shared by its accumulate, down and band passes.
//
// The recovery corrects RR's output only where RR measurably lost lighting detail. Per lobe (specular U,
// diffuse V, both demodulated) it keeps its own temporal reference of RR's input on the jitter-free raster:
// a value and a sub-pixel luminance gradient per pixel, fitted to each frame's sample at its jitter offset
// (least mean squares). The gradient is what keeps the reference sharp at this frame's samples: an average
// over all jitter offsets is a one-pixel box blur of the scene, and no resampling brings that back.
// The difference reference - RR is split into Laplacian bands (1-2 ... 32-64 px). Each band is transferred
// with a Wiener weight max(E - k N, 0) / E (E: local band energy, N: the reference's own noise in that
// band), so noise-level differences are suppressed and real lost detail passes; Mix moves the weight
// towards 1 (all of the reference's detail). Specular and Diffuse recovery act on every band. Flat albedo
// recovery acts on zero-roughness surfaces (screens and signs, where all visible detail is lighting and RR is
// given an adjustable RR roughness). An RR-guided current-frame reference follows changing video; its own
// Mix and Anchor apply there. Coarse-band noise margins increase from level 2, preserving the fine bands.
// At the end, Anchor limits each lobe to RR's local mean +- Anchor standard deviations (RR's local spread
// with a small RR-relative floor), independent of reference noise.
#include "FSRDPreprocessCommon.hlsli"

#define RECOVERY_LOBE_LEVELS 6

#define RECOVERY_FLAGS_HISTORY_VALID (1u << 0) // the references and noise histories may be reprojected
#define RECOVERY_FLAGS_EXTRA_DIFFUSE (1u << 1) // the diffuse lobe was split over two RR signals
#define RECOVERY_FLAGS_NO_SPECULAR   (1u << 2) // the specular lobe was split; leave it alone
#define RECOVERY_FLAGS_COARSEST      (1u << 3) // band pass: no coarser correction to add
#define RECOVERY_FLAGS_FINAL         (1u << 4) // band pass at level 0: write the output colour

cbuffer CB_RecoveryLobe : register(b0)
{
    float4 DstTexSize;          // XY: render size, ZW: 1 / size
    float4 LevelSize;           // band/down passes: XY this level, ZW the next coarser (down: the finer source)
    float4 Strength;            // X specular, Y diffuse, Z unused, W flat albedo
    float2 Jitter;              // this frame's jitter, render pixels (pixel p samples p - Jitter)
    float2 Modulation;          // the composition's specular / diffuse albedo modulation
    float Response;             // smallest weight of a new frame in the references (running mean before that)
    float Threshold;            // base Wiener k; coarse levels use a larger noise margin
    float MatureAge;            // temporal warm-up; current-frame display detail is available immediately
    uint Flags;
    uint Level;
    uint FrameIndex;
    uint Debug;
    float GradientAge;          // frames before the sub-pixel gradient is fitted
    float4 Blend;               // X: Mix, Y: Anchor (specular / diffuse), Z: Mix, W: Anchor (flat albedo)
}

bool IsSet(uint mask) { return (Flags & mask) == mask; }

// Sum of the squared weights of the reference after `age` samples: a running mean (weight 1 / k for sample
// k) until that weight reaches Response, then an exponential average. The reference's variance is the
// single-frame variance times this.
float ReferenceWeightSquares(float age, float response)
{
    const float start = 1.0f / max(response, 1e-6f);
    age = max(age, 1.0f);
    if (age <= start)
        return 1.0f / age;
    const float limit = response / (2.0f - response);
    const float decay = (1.0f - response) * (1.0f - response);
    return limit + (1.0f / start - limit) * pow(decay, age - start);
}

uint RecoveryHash(uint x)
{
    x ^= x >> 16; x *= 0x7feb352du;
    x ^= x >> 15; x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

// Rounds to one of the two neighbouring FP16 values with probabilities that make the stored value unbiased.
// Round-to-nearest stalls an exponential average with a small weight: increments below half a unit are lost,
// and a converged reference would stop up to ~1.6% away from the mean on clean surfaces.
float StochasticHalf(float x, float u)
{
    x = clamp(x, -65504.0f, 65504.0f);
    if (!isfinite(x))
        return 0.0f;
    const uint h = f32tof16(x);
    const float y = f16tof32(h);
    if (y == x)
        return y;
    uint other;
    if (y == 0.0f)
        other = x < 0.0f ? 0x8001u : 0x0001u;
    else if (abs(x) > abs(y))
        other = h + 1u;
    else
        other = h - 1u;
    const float z = f16tof32(other);
    return u < saturate((x - y) / (z - y)) ? z : y;
}

float3 StochasticHalf3(float3 x, uint seed)
{
    const float scale = 1.0f / 4294967296.0f;
    return float3(StochasticHalf(x.r, float(RecoveryHash(seed)) * scale),
                  StochasticHalf(x.g, float(RecoveryHash(seed ^ 0x68e31da4u)) * scale),
                  StochasticHalf(x.b, float(RecoveryHash(seed ^ 0xb5297a4du)) * scale));
}

// Bilinear read at a level coordinate (pixel centres at integers), clamped to the level, as the reference
// implementation's up-sampling.
float4 LoadBilinear(Texture2D<float4> source, float2 coordinate, int2 size)
{
    coordinate = clamp(coordinate, 0.0f, float2(size - 1));
    const int2 base = int2(floor(coordinate));
    const int2 next = min(base + 1, size - 1);
    const float2 f = coordinate - float2(base);
    return lerp(lerp(source[base], source[int2(next.x, base.y)], f.x),
                lerp(source[int2(base.x, next.y)], source[next], f.x), f.y);
}
