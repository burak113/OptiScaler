#ifndef FSRD_SKIN_COMMON
#define FSRD_SKIN_COMMON
float SkinLuma(float3 c) { return dot(c, float3(0.25f, 0.5f, 0.25f)); }
float3 SkinSeparate(float3 c, float guide)
{
    // A zero guide is an exact bypass, including signed zeros in the source.
    if (guide == 0.0f || !isfinite(guide)) return c;
    const float ratio = clamp(guide / max(SkinLuma(c), 1e-4f), -4.0f, 1.0f);
    return c * (1.0f - ratio);
}
#endif
