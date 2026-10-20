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

    // The composition desc stores the TRANSPOSE of the matrix HLSL sees: FSRDCameraMatrices.h builds the camera
    // basis with the position in column 3 (the column-vector form, camera.view = B^-1, camera.inverseView = B), and
    // StoreHlslColumnVectorMatrix writes XMMatrixTranspose of it, which is exactly what a column-major cbuffer
    // read turns back into the column-vector matrix for the HLSL consumers. Everything in this file therefore
    // transposes once when loading a desc matrix, and the apply pass receives the relative matrix row by row.
    inline DirectX::XMMATRIX LoadDesc(const DirectX::XMFLOAT4X4& value)
    {
        return DirectX::XMMatrixTranspose(DirectX::XMLoadFloat4x4(&value));
    }

    // The conversion desc carries the HLSL column-vector form of the inverse matrices (FSRDFeature_Dx12.cpp
    // transposes with StoreHlslColumnVectorMatrix before uploading, and the shipped skin/additive HLSL consumes
    // desc.InvViewMatrix as mul(Matrix, vector)), so inverting them yields the HLSL form of the forward matrices
    // the passes need. The previous view is already a forward view. Kept here so the GPU fixture drives the same
    // code the product runs instead of a hand-written copy of it.
    struct ConversionMatrices
    {
        const DirectX::XMFLOAT4X4& InverseView;
        const DirectX::XMFLOAT4X4& InverseProjection;
        const DirectX::XMFLOAT4X4& PreviousView;
    };

    inline void FillFromConversion(DirectX::XMFLOAT4X4& view, DirectX::XMFLOAT4X4& projection,
        DirectX::XMFLOAT4X4& previousView, const ConversionMatrices& source)
    {
        DirectX::XMStoreFloat4x4(&view, DirectX::XMMatrixInverse(nullptr, DirectX::XMLoadFloat4x4(&source.InverseView)));
        DirectX::XMStoreFloat4x4(&projection,
            DirectX::XMMatrixInverse(nullptr, DirectX::XMLoadFloat4x4(&source.InverseProjection)));
        previousView = source.PreviousView;
    }

    // The composition desc carries the HLSL column-vector form of the matrices (the conversion desc stores the
    // transposed inverses and the feature inverts them once), so the relative matrix is built in that form and the
    // apply pass consumes it as clip = M * view. The keyframe projection contributes only its P32 element.
    inline bool BuildFrame(KeyState& key, uint32_t width, uint32_t height, bool historyValid, float strength,
        const DirectX::XMFLOAT4X4& view, const DirectX::XMFLOAT4X4& projection, const DirectX::XMFLOAT4X4& previousView,
        Outputs& outputs)
    {
        const DirectX::XMMATRIX currentView = LoadDesc(view);
        const DirectX::XMMATRIX previous = LoadDesc(previousView);
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
        const DirectX::XMMATRIX keyView = LoadDesc(key.View);
        const DirectX::XMMATRIX keyProjection = LoadDesc(key.Projection);
        DirectX::XMStoreFloat4x4(&relative, keyProjection * keyView *
            DirectX::XMMatrixInverse(nullptr, currentView));
        const DirectX::XMMATRIX currentProjection = LoadDesc(projection);
        float* constants = outputs.Apply;
        constants[0] = float(width);
        constants[1] = float(height);
        constants[2] = 1.0f / std::max(1.0f, float(width));
        constants[3] = 1.0f / std::max(1.0f, float(height));
        for (int i = 0; i < 16; ++i)
            constants[4 + i] = (&relative.m[0][0])[i];
        // The apply pass reads the projection as the column-vector matrix: P00, P11, P02, P12 and P32.
        constants[20] = DirectX::XMVectorGetX(currentProjection.r[0]);
        constants[21] = DirectX::XMVectorGetY(currentProjection.r[1]);
        constants[22] = DirectX::XMVectorGetZ(currentProjection.r[0]);
        constants[23] = DirectX::XMVectorGetZ(currentProjection.r[1]);
        constants[24] = DirectX::XMVectorGetZ(currentProjection.r[3]);
        constants[25] = DirectX::XMVectorGetZ(keyProjection.r[3]);
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
