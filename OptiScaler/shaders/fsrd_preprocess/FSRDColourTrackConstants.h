// Post-RR colour tracking (task 25 T2), experimental, default off.
// The constants of the three passes live here so the GPU fixture can drive the exact values the preprocessor
// binds: a hand-built fixture with its own idea of the tap step or the EMA parameter layout would validate the
// shader against itself rather than against production (task 24's lesson 5).
#pragma once
#include <DirectXMath.h>

namespace ColourTrackMath
{
    // The smoothing taps sit `step` quarter-res cells apart; the measured production shape is step 2, i.e. a
    // 16-full-res-pixel outer tap (5x5 taps, depth+normal weighted). The radius control is quantised to this
    // integer, so the default reproduces the measured kernel exactly.
    inline constexpr float kCellPixels = 4.0f;
    inline constexpr float kMinTapStep = 1.0f, kMaxTapStep = 4.0f;
    inline constexpr float kDefaultRadiusPixels = 16.0f;
    inline constexpr float kMinRadiusPixels = 8.0f, kMaxRadiusPixels = 32.0f;
    // Relative depth tolerance of the reprojection test, and the same tolerance the smoothing weights use.
    inline constexpr float kDepthTolerance = 0.02f;
    constexpr float TapStepFromRadius(float radiusPixels)
    {
        const float outerTaps = 2.0f; // dx, dy run -2..2
        const int step = int(radiusPixels / (outerTaps * kCellPixels) + 0.5f);
        return float(step < 1 ? 1 : (step > 4 ? 4 : step));
    }
    inline constexpr float kDefaultTapStep = TapStepFromRadius(kDefaultRadiusPixels);
    static_assert(kDefaultTapStep == 2.0f, "the default radius reproduces the measured two-cell kernel");

    // Mirrors CB_ColourTrackStats.
    struct alignas(16) StatsConstants
    {
        DirectX::XMFLOAT4 Size; // full width, height, quarter width, quarter height
    };
    static_assert(sizeof(StatsConstants) == 16, "FSRDColourTrackStats constants");
    // Mirrors CB_ColourTrackTrack.
    struct alignas(16) TrackConstants
    {
        DirectX::XMFLOAT4 Size;   // full width, height, quarter width, quarter height
        DirectX::XMFLOAT4 Params; // x EMA weight, y depth tolerance, z strength, w previous history valid
        DirectX::XMFLOAT4 Params2; // x tap step in quarter-res cells, yzw unused
    };
    static_assert(sizeof(TrackConstants) == 48, "FSRDColourTrackTrack constants");
    // Mirrors CB_ColourTrackApply.
    struct alignas(16) ApplyConstants
    {
        DirectX::XMFLOAT4 Size; // full width, height, 1/width, 1/height
    };
    static_assert(sizeof(ApplyConstants) == 16, "FSRDColourTrackApply constants");
}
