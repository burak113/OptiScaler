#include "../../../upscalers/fsr31/FSROutputScaling.h"

#include <cstdlib>
#include <iostream>
#include <limits>

static unsigned checks = 0;
#define CHECK(...)                                                                                                     \
    do                                                                                                                 \
    {                                                                                                                  \
        ++checks;                                                                                                      \
        if (!(__VA_ARGS__))                                                                                            \
        {                                                                                                              \
            std::cerr << "FAIL line " << __LINE__ << ": " #__VA_ARGS__ "\n";                                             \
            std::exit(1);                                                                                              \
        }                                                                                                              \
    } while (false)

using namespace FSROutputScaling;
static constexpr uint32_t TextureLimit = 16384;

static void CheckFractionalScaling()
{
    const Size display { 1920, 1080 };
    const Size render { 1280, 720 };
    struct Example
    {
        float multiplier;
        Size expected;
    };
    for (const Example example : { Example { 0.75f, { 1440, 810 } }, Example { 1.5f, { 2880, 1620 } },
                                   Example { 2.5f, { 4800, 2700 } } })
    {
        const auto context = ResolveContextSizes(display, render, true, true, false, example.multiplier, TextureLimit);
        CHECK(context.valid);
        CHECK(context.target == example.expected);
        CHECK(context.maxUpscale == example.expected);
        CHECK(context.maxRender.width >= display.width && context.maxRender.width >= context.target.width);
        CHECK(context.maxRender.height >= display.height && context.maxRender.height >= context.target.height);
        CHECK(ResolveDispatchSize(context.target, context.maxUpscale, true, example.multiplier,
                                  display.width, display.height) == example.expected);
        CHECK(ResolveDispatchSize(context.target, context.maxUpscale, true, example.multiplier,
                                  std::nullopt, std::nullopt) == example.expected);
    }

    // Fractional pixels truncate after the float product, as target allocation did before.
    CHECK(ResolveDimension(101, 0.75f, TextureLimit) == 75);
    CHECK(ResolveDimension(101, 1.5f, TextureLimit) == 151);
    CHECK(ResolveDimension(101, 2.5f, TextureLimit) == 252);
    CHECK(ResolveDimension(1920, 1.3f, TextureLimit) == 2496);
}

static void CheckOverridesAndBounds()
{
    const Size target { 2880, 1620 };
    CHECK(ResolveDispatchSize(target, target, true, 1.5f, 1280, std::nullopt) == Size { 1920, 1620 });
    CHECK(ResolveDispatchSize(target, target, true, 1.5f, std::nullopt, 720) == Size { 2880, 1080 });
    CHECK(ResolveDispatchSize(target, target, true, 1.5f, 0, 0) == target);
    CHECK(ResolveDispatchSize(target, target, true, 1.5f, 1280, 0) == Size { 1920, 1620 });
    CHECK(ResolveDispatchSize(target, target, true, 1.5f, 99999, 99999) == target);
    CHECK(ResolveDispatchSize(target, { 2000, 1200 }, true, 1.5f, 99999, 99999) == Size { 2000, 1200 });
    CHECK(ResolveDispatchSize({ 2000, 1200 }, target, true, 1.5f, 99999, 99999) == Size { 2000, 1200 });
    CHECK(ResolveDispatchSize(target, { 0, 1620 }, true, 1.5f, 1920, 1080) == Size {});
    CHECK(ResolveDispatchSize({ 0, 1620 }, target, true, 1.5f, 1920, 1080) == Size {});

    // Disabled scaling and display-resolution MV ignore scaling-only size overrides.
    for (const bool lowResMV : { false, true })
    {
        const auto context = ResolveContextSizes({ 1920, 1080 }, { 1280, 720 }, false, lowResMV, false,
                                                2.5f, TextureLimit);
        CHECK(context.valid && context.target == Size { 1920, 1080 });
        CHECK(ResolveDispatchSize(context.target, context.maxUpscale, false, 2.5f, 1280, 720) == context.target);
    }
    const auto displayMotion = ResolveContextSizes({ 1920, 1080 }, { 1280, 720 }, true, false, false,
                                                  2.5f, TextureLimit);
    CHECK(displayMotion.target == Size { 1920, 1080 });
    CHECK(ResolveDispatchSize(displayMotion.target, displayMotion.maxUpscale, false, 2.5f, 1920, 1080) ==
          displayMotion.target);

    const auto saturated = ResolveContextSizes({ 7680, 4320 }, { 3840, 2160 }, true, true, false, 3.0f, TextureLimit);
    CHECK(saturated.valid && saturated.target == Size { 16384, 12960 });
    CHECK(ResolveDispatchSize(saturated.target, saturated.maxUpscale, true, 3.0f, 7680, 4320) == saturated.target);
    CHECK(ResolveDimension(1, 0.5f, TextureLimit) == 1);
    CHECK(ResolveDimension(0, 1.5f, TextureLimit) == 0);
    CHECK(ResolveDimension(1920, 1.5f, 0) == 0);
    CHECK(ResolveDimension(std::numeric_limits<uint32_t>::max(), 3.0f,
                           std::numeric_limits<uint32_t>::max()) == std::numeric_limits<uint32_t>::max());
}

static void CheckInvalidAndExtendedLimits()
{
    CHECK(NormalizeMultiplier(0.25f) == 0.5f);
    CHECK(NormalizeMultiplier(4.0f) == 3.0f);
    for (const float invalid : { 0.0f, -1.0f, std::numeric_limits<float>::quiet_NaN(),
                                 std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity() })
    {
        CHECK(NormalizeMultiplier(invalid) == 1.0f);
        const auto context = ResolveContextSizes({ 1920, 1080 }, { 1280, 720 }, true, true, false,
                                                invalid, TextureLimit);
        CHECK(context.valid && context.target == Size { 1920, 1080 });
        CHECK(ResolveDispatchSize(context.target, context.maxUpscale, true, invalid, 1920, 1080) == context.target);
    }
    for (const Size invalid : { Size { 0, 1080 }, Size { 1920, 0 }, Size { 16385, 1080 }, Size { 1920, 16385 } })
    {
        const auto badDisplay = ResolveContextSizes(invalid, { 1280, 720 }, true, true, false, 1.5f, TextureLimit);
        const auto badRender = ResolveContextSizes({ 1920, 1080 }, invalid, true, true, true, 1.5f, TextureLimit);
        CHECK(!badDisplay.valid && badDisplay.target == Size {} && badDisplay.maxUpscale == Size {});
        CHECK(!badRender.valid && badRender.target == Size {} && badRender.maxRender == Size {});
    }
    CHECK(!ResolveContextSizes({ 1920, 1080 }, { 1280, 720 }, true, true, false, 1.5f, 0).valid);

    const auto extended = ResolveContextSizes({ 1920, 1080 }, { 2560, 1440 }, true, true, true, 2.5f, TextureLimit);
    CHECK(extended.valid && extended.multiplier == 1.0f);
    CHECK(extended.target == Size { 2560, 1440 });
    CHECK(extended.maxUpscale == extended.target && extended.maxRender == extended.target);
    CHECK(ResolveDispatchSize(extended.target, extended.maxUpscale, true, extended.multiplier,
                              std::nullopt, std::nullopt) == extended.target);
    CHECK(ResolveDispatchSize(extended.target, extended.maxUpscale, true, extended.multiplier,
                              1920, 1080) == Size { 1920, 1080 });
    const auto extendedDisplayMV = ResolveContextSizes({ 1920, 1080 }, { 2560, 1440 }, true, false, true,
                                                      2.5f, TextureLimit);
    CHECK(extendedDisplayMV.target == Size { 1920, 1080 });
    CHECK(extendedDisplayMV.maxRender == Size { 2560, 1440 });
    CHECK(extendedDisplayMV.maxUpscale == extendedDisplayMV.target && extendedDisplayMV.multiplier == 1.0f);
}

static void CheckAllocationDispatchAgreement()
{
    for (const float multiplier : { 0.25f, 0.5f, 0.75f, 1.0f, 1.3f, 1.5f, 2.5f, 3.0f, 4.0f })
        for (uint32_t width : { 1u, 101u, 1920u, 3840u, 7680u, 16384u })
            for (uint32_t height : { 1u, 99u, 1080u, 2160u, 4320u, 16384u })
            {
                const Size display { width, height };
                const auto context = ResolveContextSizes(display, display, true, true, false, multiplier, TextureLimit);
                CHECK(context.valid && IsValidSize(context.target, TextureLimit));
                CHECK(ResolveDispatchSize(context.target, context.maxUpscale, true, context.multiplier,
                                          width, height) == context.target);
                CHECK(ResolveDispatchSize(context.target, context.maxUpscale, true, context.multiplier,
                                          std::nullopt, std::nullopt) == context.target);
                const auto oversized = ResolveDispatchSize(context.target, context.maxUpscale, true, multiplier,
                                                           std::numeric_limits<uint32_t>::max(),
                                                           std::numeric_limits<uint32_t>::max());
                CHECK(oversized == context.target);
            }
}

int main()
{
    CheckFractionalScaling();
    CheckOverridesAndBounds();
    CheckInvalidAndExtendedLimits();
    CheckAllocationDispatchAgreement();
    std::cout << "PASS: " << checks << " FSR output scaling checks\n";
}
