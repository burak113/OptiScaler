// Paired signed lobe detail. This isolated equivalence prototype has no Floor,
// current-source color, Skip RGB or sample-clipping dependency.
#ifndef FSRD_RECOVERY_DETAIL_COMMON
#define FSRD_RECOVERY_DETAIL_COMMON

float3 DetailNormal(float2 oct)
{
    float2 xy = oct * 2.0f - 1.0f;
    float z = 1.0f - abs(xy.x) - abs(xy.y);
    float2 folded = (1.0f - abs(xy.yx)) * sign(xy);
    return normalize(float3(z < 0.0f ? folded : xy, z));
}

float3 DetailSupported(float4 mean, float4 variance, float4 metadata,
                       float strength, float k, uint minimumAge, float minimumCount)
{
    if (strength <= 0.0f || metadata.a < float(minimumAge) ||
        1.0f / max(variance.a, 1e-12f) < minimumCount ||
        !all(isfinite(mean)) || !all(isfinite(variance)) ||
        !all(isfinite(metadata)))
        return 0.0f;
    precise float3 sem2 = max(variance.rgb, 0.0f) * variance.a /
                         max(1.0f - variance.a, 1e-6f);
    precise float3 weight = max(0.0f, 1.0f - (k * k) * sem2 /
                                      max(mean.rgb * mean.rgb, 1e-20f));
    return strength * mean.rgb * weight;
}

float3 DetailNeutral(float3 raw, float3 base, float3 offset, float3 countValid)
{
    bool3 mask = (raw != 0.0f) & isfinite(raw) & isfinite(base) & (base > 0.0f);
    return float3(mask.x ? (raw.x - offset.x) * countValid.x : 0.0f,
                  mask.y ? (raw.y - offset.y) * countValid.y : 0.0f,
                  mask.z ? (raw.z - offset.z) * countValid.z : 0.0f);
}

float DetailScale(float3 value, float3 base)
{
    float3 ratio = float3(value.x < 0.0f ? base.x / -value.x : 1.0f,
                         value.y < 0.0f ? base.y / -value.y : 1.0f,
                         value.z < 0.0f ? base.z / -value.z : 1.0f);
    return max(0.0f, min(1.0f, min(ratio.x, min(ratio.y, ratio.z))));
}
#endif
