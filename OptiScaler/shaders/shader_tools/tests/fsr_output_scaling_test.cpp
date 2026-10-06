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
        CHECK(ResolveDispatchSize(context.target, context.maxUpscale) == example.expected);
    }

    // Fractional pixels truncate after the float product, as target allocation did before.
    CHECK(ResolveDimension(101, 0.75f, TextureLimit) == 75);
    CHECK(ResolveDimension(101, 1.5f, TextureLimit) == 151);
    CHECK(ResolveDimension(101, 2.5f, TextureLimit) == 252);
    CHECK(ResolveDimension(1920, 1.3f, TextureLimit) == 2496);
}

// The output scaler reads the whole target, so the SR dispatch always writes all of it.
static void CheckDispatchCoversScalerSource()
{
    const Size target { 2880, 1620 };
    CHECK(ResolveDispatchSize(target, target) == target);
    CHECK(ResolveDispatchSize(target, { 2000, 1200 }) == Size { 2000, 1200 });
    CHECK(ResolveDispatchSize({ 2000, 1200 }, target) == Size { 2000, 1200 });
    CHECK(ResolveDispatchSize(target, { 0, 1620 }) == Size {});
    CHECK(ResolveDispatchSize({ 0, 1620 }, target) == Size {});

    // ExtendedLimits: the target is the render size; a request equal to the display used to
    // shrink the dispatch to 1920x1080 while the scaler read 2560x1440.
    const auto extended = ResolveContextSizes({ 1920, 1080 }, { 2560, 1440 }, true, true, true, 2.5f, TextureLimit);
    CHECK(ResolveDispatchSize(extended.target, extended.maxUpscale) == extended.target);

    const auto saturated = ResolveContextSizes({ 7680, 4320 }, { 3840, 2160 }, true, true, false, 3.0f, TextureLimit);
    CHECK(saturated.valid && saturated.target == Size { 16384, 12960 });
    CHECK(ResolveDispatchSize(saturated.target, saturated.maxUpscale) == saturated.target);
    CHECK(ResolveDimension(1, 0.5f, TextureLimit) == 1);
    CHECK(ResolveDimension(0, 1.5f, TextureLimit) == 0);
    CHECK(ResolveDimension(1920, 1.5f, 0) == 0);
    CHECK(ResolveDimension(std::numeric_limits<uint32_t>::max(), 3.0f,
                           std::numeric_limits<uint32_t>::max()) == std::numeric_limits<uint32_t>::max());
}

// A dynamic output request is a display size: one axis alone, either axis changing, or both.
static void CheckDynamicDisplay()
{
    const Size display { 1920, 1080 };
    CHECK(!ResolveDynamicDisplay(1920, 1080, display).has_value());
    CHECK(ResolveDynamicDisplay(1920, 1200, display) == Size { 1920, 1200 });
    CHECK(ResolveDynamicDisplay(2560, 1080, display) == Size { 2560, 1080 });
    CHECK(ResolveDynamicDisplay(2560, 1440, display) == Size { 2560, 1440 });
    CHECK(ResolveDynamicDisplay(16384, 16384, display) == Size { 16384, 16384 });
    // Incomplete requests never resize.
    for (const auto& request : { std::pair { 0, 1200 }, std::pair { 1920, 0 }, std::pair { -1, 1200 }, std::pair { 0, 0 } })
        CHECK(!ResolveDynamicDisplay(request.first, request.second, display).has_value());
    // The old check compared the request with the scaled target and gave up when either axis
    // matched: at 1.0 a 1920x1080 -> 1920x1200 request was dropped. The display decides now,
    // whatever the multiplier.
    for (const float multiplier : { 1.0f, 0.75f, 1.5f, 3.0f })
    {
        const auto context = ResolveContextSizes(display, { 1280, 720 }, true, true, false, multiplier, TextureLimit);
        const auto next = ResolveDynamicDisplay(1920, 1200, display);
        CHECK(next == Size { 1920, 1200 });
        const auto rebuilt = ResolveContextSizes(*next, { 1280, 720 }, true, true, false, multiplier, TextureLimit);
        CHECK(rebuilt.valid && rebuilt.target.height >= context.target.height);
        CHECK(!ResolveDynamicDisplay(1920, 1200, *next).has_value());
    }
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
        CHECK(ResolveDispatchSize(context.target, context.maxUpscale) == context.target);
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
    CHECK(ResolveDispatchSize(extended.target, extended.maxUpscale) == extended.target);
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
                CHECK(ResolveDispatchSize(context.target, context.maxUpscale) == context.target);
            }
}

// FSR 3.1 features that follow upscaleSize without recreation (FFX on DX12/Vulkan, FSR 3.1 on DX11).
static void CheckDynamicDispatch()
{
    const Size target { 1920, 1080 };
    // No output scaler: the request is honoured on both axes, inside the target.
    CHECK(ResolveDynamicDispatchSize(target, false, 1280, 720) == Size { 1280, 720 });
    CHECK(ResolveDynamicDispatchSize(target, false, 1920, 1080) == target);
    CHECK(ResolveDynamicDispatchSize(target, false, 2560, 720) == Size { 1920, 720 });
    for (const auto& [w, h] : { std::pair { std::optional<uint32_t> {}, std::optional<uint32_t> { 720u } },
                                std::pair { std::optional<uint32_t> { 1280u }, std::optional<uint32_t> {} },
                                std::pair { std::optional<uint32_t> { 0u }, std::optional<uint32_t> { 720u } } })
        CHECK(ResolveDynamicDispatchSize(target, false, w, h) == target);
    // With the scaler the dispatch always covers the target it reads: 1.5x, and ExtendedLimits
    // where the request equals the display but the target is the render size.
    const auto scaled = ResolveContextSizes(target, { 1280, 720 }, true, true, false, 1.5f, TextureLimit);
    CHECK(ResolveDynamicDispatchSize(scaled.target, true, 1280, 720) == scaled.target);
    CHECK(ResolveDynamicDispatchSize(scaled.target, true, 1920, 1080) == scaled.target);
    const auto extended = ResolveContextSizes(target, { 2560, 1440 }, true, true, true, 2.5f, TextureLimit);
    CHECK(ResolveDynamicDispatchSize(extended.target, true, 1920, 1080) == Size { 2560, 1440 });
    // The recreation that applies the new size derives a target matching the request.
    const auto display = ResolveDynamicDisplay(1280, 720, target);
    CHECK(display == Size { 1280, 720 });
    const auto rebuilt = ResolveContextSizes(*display, { 853, 480 }, true, true, false, 1.5f, TextureLimit);
    CHECK(ResolveDynamicDispatchSize(rebuilt.target, true, 1280, 720) == Size { 1920, 1080 });
}

int main()
{
    CheckDynamicDispatch();
    CheckFractionalScaling();
    CheckDispatchCoversScalerSource();
    CheckDynamicDisplay();
    CheckInvalidAndExtendedLimits();
    CheckAllocationDispatchAgreement();
    std::cout << "PASS: " << checks << " FSR output scaling checks\n";
}
