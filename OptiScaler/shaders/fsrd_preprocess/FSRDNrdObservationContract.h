#pragma once

// Portable metadata and byte contracts for opt-in native diagnostics. No GPU,
// allocation, logging, filtering or semantic material inference belongs here.
// Serialize named fields, not the in-memory C++ representation of these structs.
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace FSRDNrdObservation
{
inline constexpr uint32_t AbiVersion = 1;

enum class Availability : uint32_t { Unknown, Present, Missing, Invalid };
enum class Lobe : uint32_t { Unknown, None, Diffuse, Specular };
enum class Role : uint32_t
{
    Unknown, PhysicalSource, EffectivePhysical, RawRR, SelectedOutput,
    NativeNormalRoughness, ProviderNormalRoughness, RawDepth, ProviderDepth,
    NativeMotion, ProviderMotion, AnchorSums, EncodingFlag, GeometryValidity
};
enum class Encoding : uint32_t
{
    Unknown, Rgba16FloatWords, R10G10B10A2UnormWords, R32FloatWords,
    Rgba32FloatWords, NativeAnchorSums32, R32UintWords, Rg16FloatWords, R8UintWords
};
enum class SelectionPath : uint32_t { Unknown, RawRR, LobeRecovery, FlatAlbedo, ProtectedNative };
enum class Authority : uint32_t { Unknown, RawRR, Protected };
enum class EqualityGuard : uint32_t { Unknown, EqualWords, DifferentWords };
enum class MotionUnits : uint32_t { Unknown, FullRenderUv, FullRenderPixels, NativeUninterpreted };
enum class MotionDirection : uint32_t { Unknown, PreviousMinusCurrent, CurrentMinusPrevious };
enum class JitterConvention : uint32_t { Unknown, AlreadyEncodedNoExtraDelta, ExcludedNeedsExplicitDelta };
enum class Reason : uint32_t
{
    None, MissingObservation, UnknownObservation, InvalidObservation, UnknownStamp,
    WrongStream, StaleFrame, StaleResetEpoch, StaleResourceEpoch, UnknownRole,
    WrongRole, WrongLobe, UnknownScale, WrongScale, WrongFormat, InvalidExtent,
    WrongOrigin, TruncatedPayload, UnknownMotionConvention, UnknownSelection,
    ProtectedSelection, ResourceMismatch, EqualityUnavailable, UnequalWords,
    NonfiniteSample, WrongDepthSign, InvalidNormalPayload, MissingCarryWords
};

struct Extent { uint32_t width = 0, height = 0; };
struct Origin { uint32_t x = 0, y = 0; };
struct Stamp
{
    uint64_t streamId = 0, frame = 0, resetEpoch = 0, resourceEpoch = 0;
    uint32_t known = 0;
};

// Provider scale records the actual dispatch scale (D16/S256 when selected).
// Stored scale is the multiplier still present in this payload's RGB words.
// A post-restore resource uses 1, but it is NOT claimed bit-identical to a
// pre-scale source; only a separately timed source observation proves that.
struct Scale
{
    uint32_t known = 0, providerMultiplier = 0, storedMultiplier = 0;
};

struct Layout
{
    uint32_t dxgiFormat = 0;
    Encoding encoding = Encoding::Unknown;
    Extent allocation {}, active {}, captured {};
    Origin cropOrigin {};
    uint64_t byteOffset = 0, rowPitch = 0, rowBytes = 0, payloadBytes = 0;
};

struct Surface
{
    Availability availability = Availability::Unknown;
    Reason unavailableReason = Reason::UnknownObservation;
    Role role = Role::Unknown;
    Lobe lobe = Lobe::Unknown;
    Stamp stamp {};
    uint64_t resourceId = 0; // Recording-local resource identity, never a persistent pointer.
    Layout layout {};
    Scale scale {};
};

struct MotionConvention
{
    MotionUnits units = MotionUnits::Unknown;
    MotionDirection direction = MotionDirection::Unknown;
    JitterConvention jitter = JitterConvention::Unknown;
};

// The host fills this at its actual selected-resource assignment. Equality is
// deliberately absent: equal values cannot manufacture an ownership decision.
// This is an ABI trust boundary, not a cryptographic attestation of its caller.
struct SelectionWitness
{
    SelectionPath path = SelectionPath::Unknown;
    Stamp stamp {};
    Lobe lobe = Lobe::Unknown;
    uint64_t rawResourceId = 0, selectedResourceId = 0;
};

inline bool Same(Extent a, Extent b) noexcept { return a.width == b.width && a.height == b.height; }
inline bool Same(Origin a, Origin b) noexcept { return a.x == b.x && a.y == b.y; }
inline bool IsLobe(Lobe lobe) noexcept { return lobe == Lobe::Diffuse || lobe == Lobe::Specular; }
inline bool IsRadiance(Role role) noexcept
{
    return role == Role::PhysicalSource || role == Role::EffectivePhysical ||
           role == Role::RawRR || role == Role::SelectedOutput;
}
inline bool ValidMultiplier(uint32_t value) noexcept
{
    return value >= 1 && value <= 4096 && (value & (value - 1)) == 0;
}
inline Reason CompareStamp(const Stamp& actual, const Stamp& expected) noexcept
{
    if (actual.known != 1 || expected.known != 1 || !actual.streamId || !expected.streamId)
        return Reason::UnknownStamp;
    if (actual.streamId != expected.streamId) return Reason::WrongStream;
    if (actual.frame != expected.frame) return Reason::StaleFrame;
    if (actual.resetEpoch != expected.resetEpoch) return Reason::StaleResetEpoch;
    if (actual.resourceEpoch != expected.resourceEpoch) return Reason::StaleResourceEpoch;
    return Reason::None;
}
inline uint32_t BytesPerPixel(Encoding encoding) noexcept
{
    switch (encoding)
    {
    case Encoding::Rgba16FloatWords: return 8;
    case Encoding::R10G10B10A2UnormWords:
    case Encoding::R32FloatWords:
    case Encoding::R32UintWords:
    case Encoding::Rg16FloatWords: return 4;
    case Encoding::Rgba32FloatWords: return 16;
    case Encoding::R8UintWords: return 1;
    default: return 0;
    }
}
inline bool FormatMatches(uint32_t dxgi, Encoding encoding) noexcept
{
    // Fixed DXGI numeric values keep this header independent of Windows headers.
    switch (encoding)
    {
    case Encoding::Rgba16FloatWords: return dxgi == 10;
    case Encoding::R10G10B10A2UnormWords: return dxgi == 24;
    case Encoding::R32FloatWords: return dxgi == 41;
    case Encoding::Rgba32FloatWords: return dxgi == 2;
    case Encoding::R32UintWords: return dxgi == 42;
    case Encoding::Rg16FloatWords: return dxgi == 34;
    case Encoding::R8UintWords: return dxgi == 62;
    case Encoding::NativeAnchorSums32: return dxgi == 0; // Raw 32-byte buffer.
    default: return false;
    }
}
inline bool RoleMatches(Role role, Encoding encoding) noexcept
{
    switch (role)
    {
    case Role::PhysicalSource:
    case Role::EffectivePhysical:
    case Role::RawRR:
    case Role::SelectedOutput: return encoding == Encoding::Rgba16FloatWords;
    case Role::NativeNormalRoughness:
    case Role::ProviderNormalRoughness: return encoding == Encoding::R10G10B10A2UnormWords;
    case Role::RawDepth:
    case Role::ProviderDepth: return encoding == Encoding::R32FloatWords;
    case Role::NativeMotion:
    case Role::ProviderMotion:
        return encoding == Encoding::Rgba16FloatWords || encoding == Encoding::Rg16FloatWords ||
               encoding == Encoding::Rgba32FloatWords;
    case Role::AnchorSums: return encoding == Encoding::NativeAnchorSums32;
    case Role::EncodingFlag: return encoding == Encoding::R32UintWords;
    case Role::GeometryValidity: return encoding == Encoding::R32UintWords || encoding == Encoding::R8UintWords;
    default: return false;
    }
}
inline Reason ValidateLayout(const Layout& layout) noexcept
{
    if (!FormatMatches(layout.dxgiFormat, layout.encoding)) return Reason::WrongFormat;
    if (layout.encoding == Encoding::NativeAnchorSums32)
    {
        if (layout.rowBytes != 32 || layout.rowPitch != 32 || layout.captured.width != 8 ||
            layout.captured.height != 1 || layout.byteOffset > layout.payloadBytes ||
            layout.payloadBytes - layout.byteOffset < 32) return Reason::MissingCarryWords;
        return Reason::None;
    }
    if (!layout.allocation.width || !layout.allocation.height || !layout.active.width ||
        !layout.active.height || !layout.captured.width || !layout.captured.height ||
        layout.active.width > layout.allocation.width || layout.active.height > layout.allocation.height ||
        layout.captured.width > layout.active.width || layout.captured.height > layout.active.height)
        return Reason::InvalidExtent;
    if (layout.cropOrigin.x > layout.active.width - layout.captured.width ||
        layout.cropOrigin.y > layout.active.height - layout.captured.height) return Reason::WrongOrigin;
    const uint64_t logicalRow = uint64_t(layout.captured.width) * BytesPerPixel(layout.encoding);
    if (layout.rowBytes != logicalRow || layout.rowPitch < logicalRow ||
        layout.byteOffset > layout.payloadBytes) return Reason::TruncatedPayload;
    const uint64_t remaining = layout.payloadBytes - layout.byteOffset;
    if (logicalRow > remaining || (layout.captured.height > 1 &&
        layout.rowPitch > (remaining - logicalRow) / (layout.captured.height - 1))) return Reason::TruncatedPayload;
    return Reason::None;
}
inline Reason ValidateSurface(const Surface& observation) noexcept
{
    if (observation.availability == Availability::Missing) return Reason::MissingObservation;
    if (observation.availability == Availability::Unknown) return Reason::UnknownObservation;
    if (observation.availability != Availability::Present) return Reason::InvalidObservation;
    if (observation.role == Role::Unknown || uint32_t(observation.role) > uint32_t(Role::GeometryValidity))
        return Reason::UnknownRole;
    if (!RoleMatches(observation.role, observation.layout.encoding)) return Reason::WrongFormat;
    const auto stamp = CompareStamp(observation.stamp, observation.stamp);
    if (stamp != Reason::None) return stamp;
    if (!observation.resourceId) return Reason::ResourceMismatch;
    const auto layout = ValidateLayout(observation.layout);
    if (layout != Reason::None) return layout;
    if (IsRadiance(observation.role))
    {
        if (!IsLobe(observation.lobe)) return Reason::WrongLobe;
        if (observation.layout.encoding != Encoding::Rgba16FloatWords) return Reason::WrongFormat;
        if (observation.scale.known != 1) return Reason::UnknownScale;
        if (!ValidMultiplier(observation.scale.providerMultiplier) ||
            !ValidMultiplier(observation.scale.storedMultiplier)) return Reason::WrongScale;
    }
    else if (observation.lobe != Lobe::None) return Reason::WrongLobe;
    return Reason::None;
}
inline Reason CompareDomain(const Surface& actual, const Surface& expected) noexcept
{
    const auto a = ValidateSurface(actual);
    if (a != Reason::None) return a;
    const auto b = ValidateSurface(expected);
    if (b != Reason::None) return b;
    const auto stamp = CompareStamp(actual.stamp, expected.stamp);
    if (stamp != Reason::None) return stamp;
    if (!Same(actual.layout.active, expected.layout.active) ||
        !Same(actual.layout.captured, expected.layout.captured)) return Reason::InvalidExtent;
    if (!Same(actual.layout.cropOrigin, expected.layout.cropOrigin)) return Reason::WrongOrigin;
    // Allocation/pitch are intentionally independent for two resources.
    if (actual.lobe != expected.lobe) return Reason::WrongLobe;
    if (IsRadiance(actual.role) != IsRadiance(expected.role)) return Reason::WrongRole;
    if (IsRadiance(actual.role) && (actual.scale.providerMultiplier != expected.scale.providerMultiplier ||
        actual.scale.storedMultiplier != expected.scale.storedMultiplier)) return Reason::WrongScale;
    return Reason::None;
}

inline Authority SelectionAuthority(const SelectionWitness& selection) noexcept
{
    if (CompareStamp(selection.stamp, selection.stamp) != Reason::None || !IsLobe(selection.lobe) ||
        !selection.rawResourceId || !selection.selectedResourceId) return Authority::Unknown;
    switch (selection.path)
    {
    case SelectionPath::RawRR:
        return selection.rawResourceId == selection.selectedResourceId ? Authority::RawRR : Authority::Unknown;
    case SelectionPath::LobeRecovery:
    case SelectionPath::FlatAlbedo:
    case SelectionPath::ProtectedNative: return Authority::Protected;
    default: return Authority::Unknown;
    }
}
inline Reason ValidateRawAuthority(const SelectionWitness& selection, const Surface& raw,
                                   const Surface& selected, EqualityGuard equality) noexcept
{
    const auto authority = SelectionAuthority(selection);
    if (authority == Authority::Unknown) return Reason::UnknownSelection;
    if (authority == Authority::Protected) return Reason::ProtectedSelection;
    if (raw.role != Role::RawRR || selected.role != Role::SelectedOutput) return Reason::WrongRole;
    const auto domain = CompareDomain(raw, selected);
    if (domain != Reason::None) return domain;
    const auto stamp = CompareStamp(selection.stamp, raw.stamp);
    if (stamp != Reason::None) return stamp;
    if (selection.lobe != raw.lobe) return Reason::WrongLobe;
    if (selection.rawResourceId != raw.resourceId || selection.selectedResourceId != selected.resourceId)
        return Reason::ResourceMismatch;
    if (equality == EqualityGuard::Unknown) return Reason::EqualityUnavailable;
    if (equality != EqualityGuard::EqualWords) return Reason::UnequalWords;
    return Reason::None;
}

// No float conversion, finite checks, normalization or alpha arithmetic. An
// RGBA16 word containing -0 or any NaN payload is as observable as any other.
inline bool EqualWords(const void* first, const void* second, size_t bytes) noexcept
{
    return first && second && std::memcmp(first, second, bytes) == 0;
}
inline bool CopyWords(const void* source, size_t sourceBytes, void* destination, size_t destinationBytes) noexcept
{
    if (!source || !destination || destinationBytes < sourceBytes) return false;
    std::memmove(destination, source, sourceBytes);
    return true;
}
inline bool ReadPixelWords(const Surface& observation, const void* payload, size_t availableBytes,
                           uint32_t x, uint32_t y, void* destination, size_t destinationBytes) noexcept
{
    if (ValidateSurface(observation) != Reason::None || !payload || !destination ||
        observation.layout.payloadBytes > availableBytes || x >= observation.layout.captured.width ||
        y >= observation.layout.captured.height) return false;
    const auto stride = BytesPerPixel(observation.layout.encoding);
    if (!stride || destinationBytes < stride) return false;
    const uint64_t offset = observation.layout.byteOffset + uint64_t(y) * observation.layout.rowPitch + uint64_t(x) * stride;
    if (offset > availableBytes || stride > availableBytes - offset) return false;
    std::memcpy(destination, static_cast<const uint8_t*>(payload) + static_cast<size_t>(offset), stride);
    return true;
}

inline Reason ValidateDepth(float value, int32_t expectedSign) noexcept
{
    if (!std::isfinite(value)) return Reason::NonfiniteSample;
    if ((expectedSign != 1 && expectedSign != -1) || value * float(expectedSign) <= 0.0f)
        return Reason::WrongDepthSign;
    return Reason::None;
}
struct DecodedNormal
{
    std::array<float, 3> normal {};
    float roughness = 0.0f;
    uint32_t category = 0; // Original two-bit code, not a semantic/material class.
};
inline DecodedNormal DecodeNormalRoughness(uint32_t word) noexcept
{
    float x = float(word & 1023u) / 1023.0f * 2.0f - 1.0f;
    float y = float((word >> 10) & 1023u) / 1023.0f * 2.0f - 1.0f;
    const float z = 1.0f - std::abs(x) - std::abs(y);
    const float t = z < 0.0f ? -z : 0.0f;
    x += x >= 0.0f ? -t : t;
    y += y >= 0.0f ? -t : t;
    const float inverseLength = 1.0f / std::sqrt(x*x + y*y + z*z);
    return {{x*inverseLength, y*inverseLength, z*inverseLength},
            float((word >> 20) & 1023u) / 1023.0f, (word >> 30) & 3u};
}
inline Reason UnpackNormal11(float packed, std::array<float, 2>& uv) noexcept
{
    if (!std::isfinite(packed) || packed < 0.0f || packed > 2047.0f || std::floor(packed) != packed)
        return Reason::InvalidNormalPayload;
    const auto word = static_cast<uint32_t>(packed);
    uv = {float(word >> 5) / 63.0f, float(word & 31u) / 31.0f};
    return Reason::None;
}
inline uint64_t ComposeCarryWords(uint32_t low, uint32_t high) noexcept
{
    return uint64_t(low) | (uint64_t(high) << 32);
}
inline bool ReadAnchorSums(const void* bytes, size_t size, std::array<uint32_t, 8>& words) noexcept
{
    if (!bytes || size != 32) return false;
    // Explicit little-endian assembly is independent of host endianness.
    const auto* p = static_cast<const uint8_t*>(bytes);
    for (size_t i = 0; i < words.size(); ++i)
        words[i] = uint32_t(p[4*i]) | (uint32_t(p[4*i+1]) << 8) |
                   (uint32_t(p[4*i+2]) << 16) | (uint32_t(p[4*i+3]) << 24);
    return true;
}
struct PreviousCoordinate { double x = 0.0, y = 0.0; Reason reason = Reason::UnknownMotionConvention; };
inline PreviousCoordinate PreviousPixel(uint32_t x, uint32_t y, float motionX, float motionY,
                                       Origin currentOrigin, Origin previousOrigin, Extent render,
                                       const MotionConvention& convention) noexcept
{
    PreviousCoordinate result;
    if (convention.units != MotionUnits::FullRenderUv ||
        convention.direction != MotionDirection::PreviousMinusCurrent ||
        convention.jitter != JitterConvention::AlreadyEncodedNoExtraDelta) return result;
    if (!std::isfinite(motionX) || !std::isfinite(motionY))
    { result.reason = Reason::NonfiniteSample; return result; }
    if (!render.width || !render.height) { result.reason = Reason::InvalidExtent; return result; }
    if (currentOrigin.x >= render.width || currentOrigin.y >= render.height ||
        previousOrigin.x >= render.width || previousOrigin.y >= render.height)
    { result.reason = Reason::WrongOrigin; return result; }
    if (uint64_t(x) + currentOrigin.x >= render.width || uint64_t(y) + currentOrigin.y >= render.height)
    { result.reason = Reason::InvalidExtent; return result; }
    // Integer local indices denote texel centres. This is a coordinate contract,
    // not a claim about D3D sampler precision, coverage or temporal validity.
    // Reason::None certifies arithmetic only. Consumers must separately check
    // prior crop containment, frame/reset lineage and actual correspondence.
    result.x = double(x) + double(currentOrigin.x) - double(previousOrigin.x) + double(motionX) * render.width;
    result.y = double(y) + double(currentOrigin.y) - double(previousOrigin.y) + double(motionY) * render.height;
    result.reason = Reason::None;
    return result;
}
}
