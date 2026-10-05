#include "../../../upscalers/fsr31/FSRDCameraMatrices.h"
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>

using namespace DirectX;
using namespace FSRDCamera;

static unsigned checks = 0;
#define CHECK(condition)                                                                                               \
    do                                                                                                                 \
    {                                                                                                                  \
        ++checks;                                                                                                      \
        if (!(condition))                                                                                              \
        {                                                                                                              \
            std::cerr << "FAIL line " << __LINE__ << ": " #condition "\n";                                             \
            std::exit(1);                                                                                              \
        }                                                                                                              \
    } while (false)

static bool Near(float a, float b, float tolerance = 0.00001f)
{
    return std::isfinite(a) && std::abs(a - b) <= tolerance;
}

static bool Exact(const XMMATRIX& a, const XMMATRIX& b)
{
    XMFLOAT4X4 av, bv;
    XMStoreFloat4x4(&av, a);
    XMStoreFloat4x4(&bv, b);
    return std::memcmp(&av, &bv, sizeof(av)) == 0;
}

static XMFLOAT4 Transform(const XMMATRIX& columnMatrix, float x, float y, float z)
{
    XMFLOAT4 result;
    XMStoreFloat4(&result, XMVector4Transform(XMVectorSet(x, y, z, 1.0f), XMMatrixTranspose(columnMatrix)));
    return result;
}

static float ClipDepth(const XMMATRIX& projection, float z)
{
    const auto clip = Transform(projection, 0.0f, 0.0f, z);
    return clip.z / clip.w;
}

static void SetProjection(sl::Constants& camera, const XMMATRIX& rowProjection)
{
    XMFLOAT4X4 values;
    XMStoreFloat4x4(&values, rowProjection);
    for (int row = 0; row < 4; ++row)
        camera.cameraViewToClip[row] = sl::float4(values.m[row][0], values.m[row][1],
                                                values.m[row][2], values.m[row][3]);
}

static sl::Constants Basis(bool rightHanded)
{
    sl::Constants camera;
    camera.cameraRight = sl::float3(1.0f, 0.0f, 0.0f);
    camera.cameraUp = sl::float3(0.0f, 1.0f, 0.0f);
    camera.cameraFwd = sl::float3(0.0f, 0.0f, rightHanded ? -1.0f : 1.0f);
    camera.cameraPos = sl::float3(0.0f, 0.0f, 0.0f);
    return camera;
}

static sl::Constants Scalars(bool rightHanded)
{
    auto camera = Basis(rightHanded);
    // The complete projection is unavailable. A supplied perspective W still
    // establishes the convention needed to rebuild it from valid measurements.
    camera.cameraViewToClip[2].w = rightHanded ? -1.0f : 1.0f;
    camera.cameraFOV = 1.0f;
    camera.cameraAspectRatio = 1.6f;
    camera.cameraNear = 0.1f;
    camera.cameraFar = 100.0f;
    return camera;
}

static void CheckForwardAndSourcePrecedence()
{
    auto rh = Basis(true);
    SetProjection(rh, XMMatrixPerspectiveFovRH(1.0f, 1.6f, 0.1f, 100.0f));
    const auto right = Resolve(nullptr, nullptr, &rh, false);
    CHECK(right.Complete());
    CHECK(right.isRightHanded);
    CHECK(right.viewSource == Source::StreamlineBasis);
    CHECK(right.projectionSource == Source::StreamlineMatrix);
    // The old +cameraFwd basis reflects view z=-5 to world z=+5.
    const auto legacy = Transform(XMMatrixScaling(1.0f, 1.0f, -1.0f), 0.0f, 0.0f, -5.0f);
    const auto corrected = Transform(right.inverseView, 0.0f, 0.0f, -5.0f);
    CHECK(Near(legacy.z, 5.0f));
    CHECK(Near(corrected.z, -5.0f));

    auto lh = Basis(false);
    SetProjection(lh, XMMatrixPerspectiveFovLH(1.0f, 1.6f, 0.1f, 100.0f));
    const auto left = Resolve(nullptr, nullptr, &lh, false);
    CHECK(left.Complete() && !left.isRightHanded);
    CHECK(Near(Transform(left.inverseView, 0.0f, 0.0f, 5.0f).z, 5.0f));

    // A translated, rotated RH basis still maps a point ahead to cameraPos + 5*cameraFwd.
    rh.cameraRight = sl::float3(0.0f, 0.0f, 1.0f);
    rh.cameraFwd = sl::float3(1.0f, 0.0f, 0.0f);
    rh.cameraPos = sl::float3(2.0f, 3.0f, 4.0f);
    const auto rotated = Resolve(nullptr, nullptr, &rh, false);
    const auto ahead = Transform(rotated.inverseView, 0.0f, 0.0f, -5.0f);
    CHECK(rotated.Complete());
    CHECK(Near(ahead.x, 7.0f) && Near(ahead.y, 3.0f) && Near(ahead.z, 4.0f));
    CHECK(Near(Transform(rotated.view, ahead.x, ahead.y, ahead.z).z, -5.0f));

    const XMMATRIX ngxView = XMMatrixTranspose(XMMatrixLookAtRH(
        XMVectorSet(7.0f, 11.0f, 13.0f, 1.0f), XMVectorSet(5.0f, 10.0f, 6.0f, 1.0f),
        XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f)));
    const XMMATRIX ngxProjection = XMMatrixTranspose(XMMatrixPerspectiveFovLH(0.8f, 1.9f, 0.2f, 500.0f));
    const auto ngx = Resolve(&ngxView, &ngxProjection, &rh, false);
    CHECK(ngx.Complete());
    CHECK(ngx.viewSource == Source::NGX && ngx.projectionSource == Source::NGX);
    CHECK(Exact(ngx.view, ngxView) && Exact(ngx.projection, ngxProjection));
    CHECK(!ngx.isRightHanded); // Selected NGX projection wins over the SL RH convention.
    const auto mixed = Resolve(nullptr, &ngxProjection, &rh, false);
    CHECK(mixed.Complete() && !mixed.isRightHanded);
    CHECK(Near(Transform(mixed.inverseView, 0.0f, 0.0f, 5.0f).x, 7.0f));
    const auto ngxOnly = Resolve(&ngxView, &ngxProjection, nullptr, false);
    CHECK(ngxOnly.Complete() && Exact(ngxOnly.view, ngxView));
    const sl::Constants unusableStreamline;
    const auto ngxWithBadFallback = Resolve(&ngxView, &ngxProjection, &unusableStreamline, false);
    CHECK(ngxWithBadFallback.Complete() && Exact(ngxWithBadFallback.view, ngxView));
    CHECK(Exact(ngxWithBadFallback.projection, ngxProjection));
}

static void CheckAsymmetricFullProjection()
{
    for (bool rightHanded : { false, true })
        for (bool reversed : { false, true })
        {
            auto camera = Basis(rightHanded);
            // Scalar fields stay INVALID_FLOAT: a full projection stands on its own.
            const float nearArgument = reversed ? 100.0f : 0.1f;
            const float farArgument = reversed ? 0.1f : 100.0f;
            const XMMATRIX rows = rightHanded
                ? XMMatrixPerspectiveOffCenterRH(-0.13f, 0.27f, -0.2f, 0.12f, nearArgument, farArgument)
                : XMMatrixPerspectiveOffCenterLH(-0.13f, 0.27f, -0.2f, 0.12f, nearArgument, farArgument);
            SetProjection(camera, rows);
            const auto resolved = Resolve(nullptr, nullptr, &camera, reversed);
            CHECK(resolved.Complete());
            CHECK(resolved.projectionSource == Source::StreamlineMatrix);
            CHECK(resolved.isRightHanded == rightHanded);
            CHECK(Exact(resolved.projection, XMMatrixTranspose(rows)));
            XMFLOAT4X4 columnValues;
            XMStoreFloat4x4(&columnValues, resolved.projection);
            CHECK(Near(columnValues.m[0][2], camera.cameraViewToClip[2].x));
            CHECK(Near(columnValues.m[1][2], camera.cameraViewToClip[2].y));
            CHECK(std::abs(columnValues.m[0][2]) > 0.01f && std::abs(columnValues.m[1][2]) > 0.01f);

            // Compare projection against SL's actual row-vector transform at an off-axis point.
            const float viewZ = rightHanded ? -5.0f : 5.0f;
            XMFLOAT4 slClip;
            XMStoreFloat4(&slClip, XMVector4Transform(XMVectorSet(0.3f, -0.2f, viewZ, 1.0f), rows));
            const auto clip = Transform(resolved.projection, 0.3f, -0.2f, viewZ);
            CHECK(Near(clip.x, slClip.x) && Near(clip.y, slClip.y) &&
                  Near(clip.z, slClip.z) && Near(clip.w, slClip.w));
            CHECK(Near(ClipDepth(resolved.projection, rightHanded ? -0.1f : 0.1f), reversed ? 1.0f : 0.0f));
            CHECK(Near(ClipDepth(resolved.projection, rightHanded ? -100.0f : 100.0f), reversed ? 0.0f : 1.0f));

            // Valid scalars that describe a different symmetric camera must never overwrite it.
            camera.cameraFOV = 0.5f;
            camera.cameraAspectRatio = 2.4f;
            camera.cameraNear = 0.2f;
            camera.cameraFar = 300.0f;
            CHECK(Exact(Resolve(nullptr, nullptr, &camera, reversed).projection, resolved.projection));
        }
}

static void CheckScalarFallback()
{
    for (bool rightHanded : { false, true })
        for (bool reversed : { false, true })
            for (bool infinite : { false, true })
            {
                auto camera = Scalars(rightHanded);
                if (infinite)
                    camera.cameraFar = 0.0f;
                const auto resolved = Resolve(nullptr, nullptr, &camera, reversed);
                CHECK(resolved.Complete());
                CHECK(resolved.projectionSource == Source::StreamlineScalars);
                CHECK(resolved.isRightHanded == rightHanded);
                const float sign = rightHanded ? -1.0f : 1.0f;
                CHECK(Near(ClipDepth(resolved.projection, sign * camera.cameraNear), reversed ? 1.0f : 0.0f));
                CHECK(Near(ClipDepth(resolved.projection, sign * (infinite ? 1.0e8f : camera.cameraFar)),
                           reversed ? 0.0f : 1.0f));
                CHECK(Near(Transform(resolved.inverseView, 0.0f, 0.0f, sign * 5.0f).z, sign * 5.0f));
            }
    auto degrees = Scalars(true);
    degrees.cameraFOV = 60.0f;
    const auto resolved = Resolve(nullptr, nullptr, &degrees, false);
    CHECK(resolved.Complete());
    CHECK(Exact(resolved.projection, XMMatrixTranspose(
        XMMatrixPerspectiveFovRH(60.0f * (XM_PI / 180.0f), 1.6f, 0.1f, 100.0f))));
}

static void CheckInvalidData()
{
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float infinity = std::numeric_limits<float>::infinity();
    auto camera = Scalars(true);
    const XMMATRIX zero {};
    const XMMATRIX sentinel = XMMatrixSet(
        sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT,
        sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT,
        sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT,
        sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT, sl::INVALID_FLOAT);
    const XMMATRIX singular = XMMatrixScaling(1.0f, 1.0f, 0.0f);
    const XMMATRIX nonfinite = XMMatrixSet(1, 0, 0, nan, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1);
    // A single finite sentinel in an otherwise invertible affine matrix is also absent data.
    const XMMATRIX partialSentinel = XMMatrixSet(1, 0, 0, sl::INVALID_FLOAT,
                                                0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1);
    for (const auto& invalid : { zero, sentinel, singular, nonfinite, partialSentinel })
    {
        const auto fallback = Resolve(&invalid, &invalid, &camera, false);
        CHECK(fallback.Complete());
        CHECK(fallback.viewSource == Source::StreamlineBasis);
        CHECK(fallback.projectionSource == Source::StreamlineScalars);
        CHECK(!Resolve(&invalid, &invalid, nullptr, false).Complete());
    }
    const sl::Constants absent;
    CHECK(!Resolve(nullptr, nullptr, &absent, false).Complete());
    CHECK(!Resolve(nullptr, nullptr, nullptr, false).Complete());

    // Corruption anywhere in the complete SL matrix selects scalars only when
    // a real perspective W and valid scalar measurements remain available.
    for (float bad : { sl::INVALID_FLOAT, nan, infinity })
    {
        auto invalidFull = camera;
        SetProjection(invalidFull, XMMatrixPerspectiveFovRH(1.0f, 1.6f, 0.1f, 100.0f));
        invalidFull.cameraViewToClip[0].y = bad;
        const auto fallback = Resolve(nullptr, nullptr, &invalidFull, false);
        CHECK(fallback.Complete() && fallback.projectionSource == Source::StreamlineScalars);
    }
    auto singularFull = camera;
    SetProjection(singularFull, XMMatrixPerspectiveFovRH(1.0f, 1.6f, 0.1f, 100.0f));
    singularFull.cameraViewToClip[0] = sl::float4(0, 0, 0, 0);
    CHECK(Resolve(nullptr, nullptr, &singularFull, false).projectionSource == Source::StreamlineScalars);

    for (float bad : { sl::INVALID_FLOAT, nan, infinity, 0.0f, -1.0f, XM_PI, 180.0f, 360.0f })
    {
        auto invalid = camera;
        invalid.cameraFOV = bad;
        const auto rejected = Resolve(nullptr, nullptr, &invalid, false);
        CHECK(!rejected.Complete());
        CHECK(rejected.projectionSource == Source::Missing && !rejected.isRightHanded);
    }
    for (float bad : { sl::INVALID_FLOAT, nan, infinity, 0.0f, -1.0f })
    {
        auto invalid = camera;
        invalid.cameraAspectRatio = bad;
        CHECK(!Resolve(nullptr, nullptr, &invalid, false).Complete());
        invalid = camera;
        invalid.cameraNear = bad;
        CHECK(!Resolve(nullptr, nullptr, &invalid, false).Complete());
    }
    for (float bad : { sl::INVALID_FLOAT, nan, infinity, -1.0f, 0.1f, 0.05f })
    {
        auto invalid = camera;
        invalid.cameraFar = bad;
        CHECK(!Resolve(nullptr, nullptr, &invalid, false).Complete());
    }
    for (float bad : { sl::INVALID_FLOAT, nan, infinity, 0.0f })
    {
        auto invalid = camera;
        invalid.cameraViewToClip[2].w = bad;
        CHECK(!Resolve(nullptr, nullptr, &invalid, false).Complete());
    }
    for (const auto& badBasis : { sl::float3(0, 0, 0), sl::float3(1, 0, 0),
                                  sl::float3(nan, 0, -1), sl::float3(sl::INVALID_FLOAT, 0, -1) })
    {
        auto invalid = camera;
        invalid.cameraFwd = badBasis;
        const auto rejected = Resolve(nullptr, nullptr, &invalid, false);
        CHECK(!rejected.Complete() && rejected.viewSource == Source::Missing);
        CHECK(Exact(rejected.view, zero) && Exact(rejected.inverseView, zero));
    }
    for (float bad : { sl::INVALID_FLOAT, nan, infinity })
    {
        auto invalid = camera;
        invalid.cameraPos.x = bad;
        CHECK(!Resolve(nullptr, nullptr, &invalid, false).Complete());
    }
    auto orthographicScalars = camera;
    orthographicScalars.orthographicProjection = sl::Boolean::eTrue;
    CHECK(!Resolve(nullptr, nullptr, &orthographicScalars, false).Complete());

    // Finite/invertible alone cannot establish perspective handedness for basis fallback.
    SetProjection(camera, XMMatrixIdentity());
    CHECK(!Resolve(nullptr, nullptr, &camera, false).Complete());
    const XMMATRIX suppliedView = XMMatrixIdentity();
    const auto explicitView = Resolve(&suppliedView, nullptr, &camera, false);
    CHECK(explicitView.Complete() && Exact(explicitView.view, suppliedView));
}

int main()
{
    CheckForwardAndSourcePrecedence();
    CheckAsymmetricFullProjection();
    CheckScalarFallback();
    CheckInvalidData();
    std::cout << "PASS: " << checks << " production camera matrix checks\n";
}
