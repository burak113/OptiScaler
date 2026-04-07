#include "pch.h"
#include "NVNGX_Parameter.h"
#include "hooks/Streamline_Hooks.h"
#include "MathUtils.h"

/**
 * @brief Tries to get additional camera configuration for upscaling from Streamline hooks.
 */
bool TryGetNGXCamConfigFromStreamline(NVSDK_NGX_Parameter* InParameters)
{
    auto& state = State::Instance();
    const auto& slData = state.slLastConstants;

    if (InParameters && StreamlineHooks::isDlssHooked())
    {
        if (slData.cameraNear == sl::INVALID_FLOAT || slData.cameraFar == sl::INVALID_FLOAT ||
            slData.cameraFOV == sl::INVALID_FLOAT || slData.cameraFOV == 0)
            return false;

        // This measurement is supposed to be in radians, but some titles supply degrees.
        // Valid FOV in radians never exceeds PI. Realistic FOV in degrees is basically never in the single digits.
        const float fov = (slData.cameraFOV < 4.0f) ? slData.cameraFOV : OptiMath::GetRadiansFromDeg(slData.cameraFOV);

        // FSR flips near/far plane fields internally when the inverted depth flag is set.
        // DLSS switches the fields explicitly.
        const float nearPlane = (slData.depthInverted) ? slData.cameraFar : slData.cameraNear;
        const float farPlane = (slData.depthInverted) ? slData.cameraNear : slData.cameraFar;

        InParameters->Set(OptiKeys::FSR_NearPlane, nearPlane);
        InParameters->Set(OptiKeys::FSR_FarPlane, farPlane);
        InParameters->Set(OptiKeys::FSR_CameraFovVertical, fov);

        return true;
    }
    else
        return false;
}
