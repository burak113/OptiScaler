#pragma once
#include <cstddef>
#include <cstdint>

// Proposal only; no production caller or enabled setting is introduced.
namespace fsrd::research::job07
{
struct alignas(16) Constants final
{
    std::uint32_t currentExtent[2] {};            // byte 0
    std::uint32_t previousExtent[2] {};           // byte 8
    std::uint32_t renderExtent[2] {};             // byte 16
    float currentCropOrigin[2] {};               // byte 24
    float previousCropOrigin[2] {};              // byte 32
    std::uint32_t enabled = 0;                   // byte 40
    std::uint32_t chronological = 0;             // byte 44
    std::uint32_t currentPositiveLinearDepth = 0; // byte 48
    std::uint32_t previousPositiveLinearDepth = 0;// byte 52
    float depthRelativeTolerance = 0.02f;        // byte 56
    std::uint32_t reserved = 0;                  // byte 60
};
static_assert(sizeof(float) == 4);
static_assert(sizeof(Constants) == 64);
static_assert(alignof(Constants) == 16);
static_assert(offsetof(Constants, currentExtent) == 0);
static_assert(offsetof(Constants, previousExtent) == 8);
static_assert(offsetof(Constants, renderExtent) == 16);
static_assert(offsetof(Constants, currentCropOrigin) == 24);
static_assert(offsetof(Constants, previousCropOrigin) == 32);
static_assert(offsetof(Constants, enabled) == 40);
static_assert(offsetof(Constants, chronological) == 44);
static_assert(offsetof(Constants, currentPositiveLinearDepth) == 48);
static_assert(offsetof(Constants, previousPositiveLinearDepth) == 52);
static_assert(offsetof(Constants, depthRelativeTolerance) == 56);
static_assert(offsetof(Constants, reserved) == 60);

// Exact wire values, not a native material or geometry-validity encoding.
enum Support : std::uint16_t
{
    CurrentFinite = 1u,
    Spatial = 2u,
    MotionFinite = 4u,
    Chronological = 8u,
    InPreviousCrop = 16u,
    CategoryMatch = 32u,
    DepthMatch = 64u,
    TemporalSupported = 128u,
};
static_assert(sizeof(Support) == 2);
} // namespace fsrd::research::job07
