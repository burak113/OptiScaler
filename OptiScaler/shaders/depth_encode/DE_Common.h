#pragma once

#include "SysUtils.h"

// Runtime-compiled copy of precompile/depth_encode.hlsl (UsePrecompiledShaders=false).
// test_fsrd_sr_depth_encode checks that both stay identical.
inline static std::string depthEncodeShader = R"(// Re-encodes a linear view distance as the device depth FFX SR decodes.
//
// FFX SR has no linear-depth mode: it recovers view depth as
// deviceToViewDepth[1] / (d - deviceToViewDepth[0]) from cameraNear/cameraFar and the
// context's inverted/infinite flags. This writes the standard D3D projection depth for
// the same planes and flags, so that decode returns the input distance exactly:
//   finite:   d = f (z - n) / (z (f - n))    inverted: 1 - d
//   infinite: d = 1 - n / z                  inverted: n / z
// Distances outside [n, f] clamp to the nearer plane; a NaN reads as the far plane.

cbuffer Params : register(b0)
{
    float CameraNear;
    float CameraFar;
    uint Inverted;
    uint Infinite;
    uint Width;
    uint Height;
};

Texture2D<float> LinearDepth : register(t0);
RWTexture2D<float> DeviceDepth : register(u0);

[numthreads(16, 16, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= Width || id.y >= Height)
        return;

    const float n = CameraNear;
    const float f = CameraFar;
    // Test before clamping: min/max return the non-NaN operand, which would turn an
    // invalid distance into the near plane.
    const float raw = abs(LinearDepth.Load(int3(id.xy, 0)));
    float d = 1.0f; // an invalid distance reads as the far plane, like the sky
    if (!isnan(raw))
    {
        const float z = clamp(raw, n, f);
        d = Infinite != 0 ? 1.0f - n / z : (f * (z - n)) / (z * (f - n));
    }

    DeviceDepth[id.xy] = saturate(Inverted != 0 ? 1.0f - d : d);
}
)";
