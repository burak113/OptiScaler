#pragma once
#include <algorithm>
#include <cmath>

namespace NrdBridge
{
struct MotionStabilitySettings
{
    bool enabled = false;
    float still = 0.85f, moving = 0.5f;
    float rotationDegrees = 0.1f, translationMetres = 0.0015f, ramp = 0.035f;
    bool operator==(const MotionStabilitySettings&) const = default;
};
inline bool ValidMotionThresholds(const MotionStabilitySettings& s) noexcept
{
    return std::isfinite(s.rotationDegrees) && s.rotationDegrees > 0 && s.rotationDegrees <= 180 &&
        std::isfinite(s.translationMetres) && s.translationMetres > 0 && s.translationMetres <= 1;
}
inline bool ValidMotionStability(const MotionStabilitySettings& s) noexcept
{
    return !s.enabled || (std::isfinite(s.still) && std::isfinite(s.moving) && s.moving >= 0 && s.still <= 1 &&
        s.moving <= s.still && ValidMotionThresholds(s) &&
        std::isfinite(s.ramp) && s.ramp > 0 && s.ramp <= 1);
}
inline float NextMotionStability(const MotionStabilitySettings& s, float previous, bool validPrevious,
                                 float degrees, float metres) noexcept
{
    if (!validPrevious || !std::isfinite(degrees) || !std::isfinite(metres) ||
        degrees > s.rotationDegrees || metres > s.translationMetres) return s.moving;
    return std::min(s.still, std::max(s.moving, previous) + s.ramp);
}
template<class Configuration> inline bool ReadLightingValidation(const Configuration& config)
{
    if constexpr (requires { config.FfxDenoiserNrdBridgeLightingValidation; })
        return config.FfxDenoiserNrdBridgeLightingValidation.value_or_default();
    return false;
}
template<class Configuration> inline MotionStabilitySettings ReadMotionStabilitySettings(const Configuration& config)
{
    MotionStabilitySettings s;
    if constexpr (requires { config.FfxDenoiserNrdBridgeMotionAdaptiveStability; config.FfxDenoiserNrdBridgeStillStability;
        config.FfxDenoiserNrdBridgeMovingStability; config.FfxDenoiserNrdBridgeStabilityRotation;
        config.FfxDenoiserNrdBridgeStabilityTranslation; config.FfxDenoiserNrdBridgeStabilityRamp; })
    {
        const auto finite = [](float x, float d, float lo, float hi) { return std::isfinite(x) ? std::clamp(x,lo,hi) : d; };
        s.enabled = config.FfxDenoiserNrdBridgeMotionAdaptiveStability.value_or_default();
        s.still = finite(config.FfxDenoiserNrdBridgeStillStability.value_or_default(),.85f,0,1);
        s.moving = finite(config.FfxDenoiserNrdBridgeMovingStability.value_or_default(),std::min(.5f,s.still),0,s.still);
        s.rotationDegrees = finite(config.FfxDenoiserNrdBridgeStabilityRotation.value_or_default(),.1f,.001f,180);
        s.translationMetres = finite(config.FfxDenoiserNrdBridgeStabilityTranslation.value_or_default(),.0015f,.00001f,1);
        s.ramp = finite(config.FfxDenoiserNrdBridgeStabilityRamp.value_or_default(),.035f,.0001f,1);
    }
    return s;
}
}
