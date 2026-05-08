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

    if (InParameters && StreamlineHooks::isSetConstantsHooked())
    {
        if (slData.cameraNear == sl::INVALID_FLOAT || slData.cameraFar == sl::INVALID_FLOAT ||
            slData.cameraFOV == sl::INVALID_FLOAT || slData.cameraFOV == 0)
            return false;

        // This measurement is supposed to be in radians, but some titles supply degrees.
        // Valid FOV in radians never exceeds PI. Realistic FOV in degrees is basically never in the single digits.
        const float fov = (slData.cameraFOV < 4.0f) ? slData.cameraFOV : OptiMath::GetRadiansFromDeg(slData.cameraFOV);
        const float nearPlane = slData.cameraNear;
        const float farPlane = slData.cameraFar;

        // FSR 2/3 mostly uses these value to scale the disocclusion threshold. If these values are unavailable,
        // then the near and far plane default to [0,1]/[1,0]. This effectively disables threshold scaling.
        // FSR 4+ is likely similar. FSR doesn't seem to actually linearize depth (at least the open source ones don't),
        // so these values don't need to be perfect.
        //
        // Assuming reversed hardware depth, the error should be minimal at middle to far distances. Areas near the 
        // camera may become overly sensitive to disocclusions, increasing shimmering.
        InParameters->Set(OptiKeys::FSR_NearPlane, nearPlane);
        InParameters->Set(OptiKeys::FSR_FarPlane, farPlane);
        InParameters->Set(OptiKeys::FSR_CameraFovVertical, fov);

        return true;
    }
    else
        return false;
}
