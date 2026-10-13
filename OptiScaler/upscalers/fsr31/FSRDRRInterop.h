#pragma once
#include <DirectXMath.h>
#include <fsr-rr/ffx_denoiser.h>
#include <algorithm>
#include <cmath>
using DirectX::XMMATRIX;
using DirectX::XMFLOAT4X4;
using DirectX::XMStoreFloat4x4;
using DirectX::XMMatrixTranspose;

inline FfxApiMatrix4x4 GetRRMatrix(const XMMATRIX& columnVectorMatrix)
{
    static_assert(sizeof(FfxApiMatrix4x4) == sizeof(XMFLOAT4X4));
    FfxApiMatrix4x4 result = {};
    XMStoreFloat4x4(reinterpret_cast<XMFLOAT4X4*>(&result), XMMatrixTranspose(columnVectorMatrix));
    return result;
}

struct ViewPlanes
{
    float nearPlane;
    float farPlane;
    bool isInfinite;
    bool isRightHanded;
};

inline ViewPlanes GetViewPlanes(const DirectX::XMMATRIX& projection, bool isInverted)
{
    ViewPlanes planes = {};

    // Internal projection convention: row-major storage with column vectors.
    // clip.z = A * view.z + B; clip.w = W * view.z.
    const float A = projection.r[2].m128_f32[2];
    const float B = projection.r[2].m128_f32[3];
    const float W = projection.r[3].m128_f32[2];

    // A is the projection's depth term and W its perspective divide. On an infinite
    // far plane A is mathematically zero, but it survives matrix inversion as float
    // noise - values around 1e-6 are routine - so an absolute epsilon misclassifies
    // the projection as finite and the far plane below is then computed by dividing
    // by that noise. Cyberpunk lands on A = -1.19e-6 and produces a fabricated
    // 16777 unit far plane that way. Scale the test to W so it measures a ratio.
    const float infiniteCheckVal = isInverted ? A : (A - W);
    const float infiniteCheckScale = std::max(std::abs(W), 1e-12f);
    planes.isInfinite = std::abs(infiniteCheckVal) < 1e-4f * infiniteCheckScale;
    // W is +1 for LH projections and -1 for RH projections, independent of Z direction.
    planes.isRightHanded = W < 0.0f;

    // An infinite projection has no true far plane, but this value is consumed as a
    // log-normalisation denominator, as a depth clamp, and as RR's linearDepthBounds.
    // FLT_MAX degrades all three - log(3.4e38) is 88.7, which flattens every
    // realistic depth to the bottom tenth of the range - so report a large finite
    // horizon instead. FP16 max keeps it representable everywhere downstream.
    constexpr float kInfiniteHorizon = 65504.0f;

    if (isInverted)
    {
        // Inverted: Near is at D=1, Far is at D=0
        // 1 = A/W + B/(n*W) -> n = B / (W - A)
        planes.nearPlane = std::abs(B / (W - A));

        // 0 = A/W + B/(f*W) -> f = -B / A
        planes.farPlane = planes.isInfinite ? kInfiniteHorizon : std::abs(-B / A);
    }
    else
    {
        // Standard: Near is at D=0, Far is at D=1
        // 0 = A/W + B/(n*W) -> n = -B / A
        planes.nearPlane = std::abs(-B / A);

        // 1 = A/W + B/(f*W) -> f = B / (W - A)
        planes.farPlane = planes.isInfinite
            ? kInfiniteHorizon
            : std::abs(B / (W - A));
    }

    // A finite branch that survived the ratio test can still be wildly off if the
    // projection terms are noisy, so keep the result inside a range that cannot
    // break the consumers above.
    if (!std::isfinite(planes.nearPlane) || planes.nearPlane <= 0.0f)
    {
        // A degenerate or noisy projection divides by a term that is effectively
        // zero above. The near plane is consumed directly as RR's
        // linearDepthBounds.min and as the conversion shaders' depth clamp, so a
        // NaN here spreads into every reconstructed view-space position. Substitute
        // a usable default; the caller logs the resulting planes when they change.
        constexpr float kDefaultNearPlane = 0.01f;
        planes.nearPlane = kDefaultNearPlane;
        planes.farPlane = kInfiniteHorizon;
    }
    else if (!std::isfinite(planes.farPlane))
    {
        // std::clamp propagates NaN rather than replacing it, so filter it first.
        planes.farPlane = kInfiniteHorizon;
    }
    else
    {
        planes.farPlane = std::clamp(
            planes.farPlane, planes.nearPlane * 2.0f, kInfiniteHorizon);
    }

    return planes;
}
