#pragma once

// Source UV mapping of the raw debug blit. The composition shader samples bilinearly at
//   srcUv = ((p + 0.5) / dst) * scale + offset
// and its clamp sampler only stops at the physical texture edge, not at the logical subrect.
namespace FSRDBlitMapping
{
struct Axis
{
    float scale = 0.0f;
    float offset = 0.0f;
};

// One axis. Minifying or 1:1, the half-pixel mapping already samples inside the subrect and is
// kept. Magnifying, it would reach half a texel past the first and last logical texel centres
// and blend in the neighbouring texels (the unused tail of a DRS allocation, another viewport),
// so the first and last destination pixels land exactly on those centres instead.
inline Axis Resolve(float logicalSize, float logicalBase, float physicalSize, float dstSize)
{
    if (dstSize <= logicalSize)
        return { logicalSize / physicalSize, logicalBase / physicalSize };

    const float first = (logicalBase + 0.5f) / physicalSize;
    if (logicalSize <= 1.0f || dstSize <= 1.0f)
        return { 0.0f, (logicalBase + 0.5f * logicalSize) / physicalSize };

    const float scale = ((logicalSize - 1.0f) / physicalSize) * (dstSize / (dstSize - 1.0f));
    return { scale, first - scale * (0.5f / dstSize) };
}
} // namespace FSRDBlitMapping
