#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>

namespace FSROutputScaling
{
struct Size
{
    uint32_t width = 0;
    uint32_t height = 0;
    bool operator==(const Size&) const = default;
};

inline float NormalizeMultiplier(float multiplier)
{
    // Invalid configuration must never reach a floating-point to integer conversion.
    if (!std::isfinite(multiplier) || multiplier <= 0.0f)
        return 1.0f;

    return std::clamp(multiplier, 0.5f, 3.0f);
}

inline bool IsValidSize(Size size, uint32_t limit)
{
    return size.width > 0 && size.height > 0 && size.width <= limit && size.height <= limit;
}

inline uint32_t ResolveDimension(uint32_t dimension, float multiplier, uint32_t limit)
{
    if (dimension == 0 || limit == 0)
        return 0;

    // Keep the existing float product and truncate only after multiplication. Compare
    // in double so even a limit of UINT32_MAX cannot round up before the bounds check.
    const double scaled = static_cast<float>(dimension) * NormalizeMultiplier(multiplier);
    if (scaled >= static_cast<double>(limit))
        return limit;
    if (scaled < 1.0)
        return 1;

    return static_cast<uint32_t>(scaled);
}

inline Size ResolveSize(Size size, float multiplier, uint32_t limit)
{
    return { ResolveDimension(size.width, multiplier, limit), ResolveDimension(size.height, multiplier, limit) };
}

struct ContextSizes
{
    Size target;
    Size maxRender;
    Size maxUpscale;
    float multiplier = 1.0f;
    bool valid = false;
};

inline ContextSizes ResolveContextSizes(Size display, Size render, bool outputScalingEnabled, bool lowResMV,
                                        bool extendedLimits, float multiplier, uint32_t dimensionLimit)
{
    ContextSizes sizes {};
    sizes.multiplier = NormalizeMultiplier(multiplier);
    if (!IsValidSize(display, dimensionLimit) || !IsValidSize(render, dimensionLimit))
        return sizes;

    const bool useOutputScaling = outputScalingEnabled && lowResMV;
    sizes.target = useOutputScaling ? ResolveSize(display, sizes.multiplier, dimensionLimit) : display;

    // Preserve the extended-limits contract: render above display at native size,
    // then let the external output scaler downsample when it is active.
    if (extendedLimits && render.width > display.width)
    {
        sizes.multiplier = 1.0f;
        sizes.maxRender = render;
        if (useOutputScaling)
            sizes.target = render;
    }
    else
    {
        sizes.maxRender = { std::max(sizes.target.width, display.width),
                            std::max(sizes.target.height, display.height) };
    }

    sizes.maxUpscale = sizes.target;
    sizes.valid = true;
    return sizes;
}

// The SR dispatch extent. Parent pipeline allocations use target; the SDK allocations use
// contextMaximum, so the dispatch cannot grow past either.
//
// A title's dynamic upscaleSize request is not followed here. Without output scaling the
// feature has always dispatched its target. With it, the output scaler reads the whole target
// (its sampling spans the texture) and writes the whole display, so an SR dispatch smaller than
// the target leaves the scaler reading texels SR never wrote this frame: a one-axis request,
// any smaller request, and even a request equal to the display under ExtendedLimits (whose
// target is the render size, not display x multiplier). Features that rebuild on a new output
// size (IFeature::UpdateOutputResolution) get a target that already matches the request.
inline Size ResolveDispatchSize(Size target, Size contextMaximum)
{
    const Size size { std::min(target.width, contextMaximum.width), std::min(target.height, contextMaximum.height) };
    return size.width == 0 || size.height == 0 ? Size {} : size;
}

// The SR dispatch extent of a feature that follows the title's dynamic upscaleSize request
// without recreation. Without the output scaler the request is honoured on both axes, within
// the target the context and the output were sized for. With the scaler the dispatch is the
// whole target (see ResolveDispatchSize); the caller recreates the feature for a new size.
inline Size ResolveDynamicDispatchSize(Size target, bool outputScalerActive, std::optional<uint32_t> requestWidth,
                                       std::optional<uint32_t> requestHeight)
{
    if (outputScalerActive || requestWidth.value_or(0) == 0 || requestHeight.value_or(0) == 0)
        return target;
    return { std::min(*requestWidth, target.width), std::min(*requestHeight, target.height) };
}

// A dynamic output request (FSR.upscaleSize) names the display size and needs both axes.
// Returns the new display size when it differs from the current one on either axis; the
// target follows from it when the feature is recreated, exactly as at creation.
inline std::optional<Size> ResolveDynamicDisplay(int requestWidth, int requestHeight, Size currentDisplay)
{
    if (requestWidth <= 0 || requestHeight <= 0)
        return std::nullopt;
    const Size requested { static_cast<uint32_t>(requestWidth), static_cast<uint32_t>(requestHeight) };
    if (requested == currentDisplay)
        return std::nullopt;
    return requested;
}
} // namespace FSROutputScaling
