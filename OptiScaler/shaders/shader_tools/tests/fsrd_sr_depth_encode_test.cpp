// The SR depth re-encoding (shaders/depth_encode/precompile/depth_encode.hlsl) against the
// decode FFX SR applies: deviceToViewDepth from ffx_fsr3upscaler.cpp
// (setupDeviceDepthToViewSpaceDepthParams) and GetViewSpaceDepth from
// ffx_fsr3upscaler_common.h, copied here unchanged in substance.
#include <algorithm>
#include <cfloat>
#include <cmath>
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
            std::cerr << "FAIL line " << __LINE__ << ": " #__VA_ARGS__ "\n";                                           \
            std::exit(1);                                                                                              \
        }                                                                                                              \
    } while (false)

// Mirror of depth_encode.hlsl, in T so the math can be checked exactly (double) and as the GPU
// runs it (float).
template <class T> T Encode(T linear, T n, T f, bool inverted, bool infinite)
{
    const T raw = std::abs(linear);
    T d = 1;
    if (!std::isnan(raw))
    {
        const T z = std::min(std::max(raw, n), f); // clamp: max then min, as DXIL lowers it
        d = infinite ? T(1) - n / z : (f * (z - n)) / (z * (f - n));
    }
    d = inverted ? T(1) - d : d;
    return std::min(std::max(d, T(0)), T(1));
}

template <class T> struct Decoder
{
    T a = 0, b = 0;
    Decoder(T cameraNear, T cameraFar, bool bInverted, bool bInfinite)
    {
        T fMin = std::min(cameraNear, cameraFar);
        T fMax = std::max(cameraNear, cameraFar);
        if (bInverted)
            std::swap(fMin, fMax);
        const T fQ = fMax / (fMin - fMax);
        const T d = -1;
        const T c[2][2] = { { fQ, T(-1) - T(FLT_EPSILON) }, { fQ, T(0) + T(FLT_EPSILON) } };
        const T e[2][2] = { { fQ * fMin, -fMin - T(FLT_EPSILON) }, { fQ * fMin, fMax } };
        a = d * c[bInverted][bInfinite];
        b = e[bInverted][bInfinite];
    }
    T ViewDepth(T deviceDepth) const { return b / (deviceDepth - a); }
};

template <class T> static void RoundTrip(T n, T f, bool inverted, bool infinite, T tolerance)
{
    const Decoder<T> decode(n, f, inverted, infinite);
    // Infinite planes: FSR's epsilons perturb the decode by about FLT_EPSILON / (1 - d).
    const T top = infinite ? std::min(f, n * T(1000)) : f;
    for (int i = 0; i <= 400; ++i)
    {
        const T z = n * std::pow(top / n, T(i) / T(400));
        const T d = Encode<T>(z, n, f, inverted, infinite);
        CHECK(d >= 0 && d <= 1);
        const T back = std::abs(decode.ViewDepth(d));
        if (std::abs(back - z) > tolerance * z)
        {
            std::cerr << "n=" << n << " f=" << f << " inv=" << inverted << " inf=" << infinite << " z=" << z
                      << " d=" << d << " back=" << back << "\n";
            CHECK(false);
        }
        // A negative (signed view) depth encodes like its distance.
        CHECK(Encode<T>(-z, n, f, inverted, infinite) == d);
    }
}

int main()
{
    for (const bool inverted : { false, true })
        for (const bool infinite : { false, true })
        {
            for (const double n : { 0.01, 0.1, 1.0 })
                for (const double f : { 100.0, 1000.0, 65504.0 })
                    // Exact inverse; on infinite planes FSR's own FLT_EPSILON terms shift its
                    // decode by up to FLT_EPSILON / (n / z) relative (z <= 1000 n here).
                    RoundTrip<double>(n, f, inverted, infinite, infinite ? 5e-4 : 1e-6);
            // As the GPU computes it: float, within device depth's own precision at that range.
            for (const float n : { 0.1f, 1.0f })
                for (const float f : { 100.0f, 1000.0f })
                    RoundTrip<float>(n, f, inverted, infinite, 2e-3f);

            const float n = 0.1f, f = 1000.0f;
            const float nearD = Encode(n, n, f, inverted, infinite);
            const float farD = Encode(f, n, f, inverted, infinite);
            // Beyond the planes clamps; a NaN reads as the far plane.
            CHECK(Encode(0.0f, n, f, inverted, infinite) == nearD);
            CHECK(Encode(1e9f, n, f, inverted, infinite) == farD);
            CHECK(Encode(std::numeric_limits<float>::infinity(), n, f, inverted, infinite) == farD);
            CHECK(Encode(std::numeric_limits<float>::quiet_NaN(), n, f, inverted, infinite) == (inverted ? 0.0f : 1.0f));
            if (!infinite)
                CHECK(farD == (inverted ? 0.0f : 1.0f));
            CHECK(nearD == (inverted ? 1.0f : 0.0f));
        }
    // The audit's example: near 0.1, far 1000, view Z 10 -> about 0.990099.
    CHECK(std::abs(Encode(10.0, 0.1, 1000.0, false, false) - 0.990099) < 1e-6);
    std::cout << "PASS: " << checks << " SR depth encode checks\n";
}
