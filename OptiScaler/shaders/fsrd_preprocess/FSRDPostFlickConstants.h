// Post-flick blotch fix (task 24 T2 c), default off.
// The camera and constant math of the two passes lives here so the GPU fixture can drive the exact code the
// preprocessor runs. That matters: with a still camera every matrix convention produces the same result, so a
// transposed matrix or a wrong projection element only shows up when the camera actually moves.
#pragma once
#include <DirectXMath.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>

namespace PostFlickMath
{
    inline constexpr float kDepthTolerance = 0.03f;
    inline constexpr float kAgeMax = 32.0f;
    inline constexpr float kRatioLow = 0.7f;
    inline constexpr float kRatioHigh = 1.4f;
    // The recalled frame must be a settled one: refreshing on the first still frame would let the flick's own
    // blotchy frames overwrite the good keyframe, which is where the blotches are actually visible. The validated
    // prototype used a median age of at least six frames for the reference.
    inline constexpr uint32_t kSettledFramesNeeded = 6u;
    inline constexpr float kSettledDegrees = 1.0f;

    struct KeyState
    {
        DirectX::XMFLOAT4X4 View {}, Projection {};
        bool Valid = false;
        uint32_t SettledFrames = 0;
    };

    struct Outputs
    {
        float Prepare[8] {};
        float Apply[36] {};
        bool Refresh = false;
    };

    // The composition desc carries the HLSL column-vector form of the matrices (the conversion desc stores the
    // transposed inverses and the feature inverts them once), so the relative matrix is built in that form and the
    // apply pass consumes it as clip = M * view. The keyframe projection contributes only its P32 element.
    inline bool BuildFrame(KeyState& key, uint32_t width, uint32_t height, bool historyValid, float strength,
        const DirectX::XMFLOAT4X4& view, const DirectX::XMFLOAT4X4& projection, const DirectX::XMFLOAT4X4& previousView,
        Outputs& outputs)
    {
        const DirectX::XMMATRIX currentView = DirectX::XMLoadFloat4x4(&view);
        const DirectX::XMMATRIX previous = DirectX::XMLoadFloat4x4(&previousView);
        const auto forward = [](const DirectX::XMMATRIX& v) {
            return DirectX::XMVector3Normalize(DirectX::XMVectorSet(
                v.r[2].m128_f32[0], v.r[2].m128_f32[1], v.r[2].m128_f32[2], 0.0f));
        };
        const float cosine = DirectX::XMVectorGetX(DirectX::XMVector3Dot(forward(currentView), forward(previous)));
        const float degrees = std::acos(std::clamp(cosine, -1.0f, 1.0f)) * 57.2957795f;
        const bool settled = std::isfinite(degrees) && degrees < kSettledDegrees;
        key.SettledFrames = settled ? std::min(key.SettledFrames + 1u, 100000u) : 0u;
        outputs.Refresh = !key.Valid || key.SettledFrames >= kSettledFramesNeeded;
        if (outputs.Refresh)
        {
            key.View = view;
            key.Projection = projection;
            key.Valid = true;
        }
        const uint32_t halfW = std::max(1u, width / 2u), halfH = std::max(1u, height / 2u);
        outputs.Prepare[0] = float(width);
        outputs.Prepare[1] = float(height);
        outputs.Prepare[2] = float(halfW);
        outputs.Prepare[3] = float(halfH);
        outputs.Prepare[4] = kDepthTolerance;
        outputs.Prepare[5] = kAgeMax;
        outputs.Prepare[6] = outputs.Refresh ? 1.0f : 0.0f;
        // No history yet: the age recursion must start from zero instead of reading an unwritten texture.
        outputs.Prepare[7] = historyValid ? 1.0f : 0.0f;
        DirectX::XMFLOAT4X4 relative {};
        DirectX::XMStoreFloat4x4(&relative, DirectX::XMLoadFloat4x4(&key.Projection) *
            DirectX::XMLoadFloat4x4(&key.View) * DirectX::XMMatrixInverse(nullptr, currentView));
        float* constants = outputs.Apply;
        constants[0] = float(width);
        constants[1] = float(height);
        constants[2] = 1.0f / std::max(1.0f, float(width));
        constants[3] = 1.0f / std::max(1.0f, float(height));
        for (int i = 0; i < 16; ++i)
            constants[4 + i] = (&relative.m[0][0])[i];
        const float* projectionValues = &projection.m[0][0];
        constants[20] = projectionValues[0];
        constants[21] = projectionValues[5];
        constants[22] = projectionValues[2];
        constants[23] = projectionValues[6];
        constants[24] = projectionValues[14];
        constants[25] = key.Projection.m[3][2];
        constants[26] = kDepthTolerance;
        constants[27] = kAgeMax;
        constants[28] = kRatioLow;
        constants[29] = kRatioHigh;
        const uint32_t valid = historyValid ? 1u : 0u;
        std::memcpy(&constants[32], &valid, sizeof(uint32_t));
        constants[33] = std::clamp(strength, 0.0f, 1.0f);
        return settled;
    }
}
