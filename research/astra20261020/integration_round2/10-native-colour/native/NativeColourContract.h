#pragma once
// Portable host ABI. No D3D12 dependency; tested by contract_tests.cpp.
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace NativeColour
{
constexpr uint32_t EstimatorVersion = 1;
constexpr uint32_t MaxTextureDimension = 16384;
enum class Representation : uint32_t { Log = 0, Linear = 1 };
enum class Lobe : uint32_t { Diffuse = 0, Specular = 1 };
enum class SourceStage : uint32_t { Unknown = 0, PreProviderPhysicalSnapshot = 1 };
enum class EvidenceKind : uint32_t { Unknown = 0, SyntheticFixture = 1, ExternalCertificate = 2 };
enum class Decision : uint32_t
{
    Ready, Off, ZeroStrength, ResetOrResize, UnknownAuthority, UnknownSupport,
    InvalidConfig, InvalidIdentity, InvalidLayout, UnsupportedSource, MissingBudget,
    InvalidNativeResource, BudgetExceeded, AllocationFailed, InvalidRecording
};

struct Config
{
    bool enabled = false;
    bool acknowledgeRejectedResearch = false;
    Representation representation = Representation::Log;
    uint32_t radius = 3;
    float spatialSigma = 2.0f, depthTolerance = 0.02f, normalCosine = 0.9f;
    float roughnessTolerance = 0.15f, guideChromaRadius = 0.35f;
    float maxLogDelta = 0.2231435513f, supportPrior = 4.0f, strength = 1.0f;
};

struct Identity
{
    uint64_t frame = 0, generation = 0, recording = 0;
    uint32_t renderWidth = 0, renderHeight = 0;
    int32_t cropX = 0, cropY = 0;
    uint32_t activeWidth = 0, activeHeight = 0;
    Lobe lobe = Lobe::Diffuse;
    uint32_t providerScale = 16;
};
inline bool SameIdentity(const Identity& a, const Identity& b) noexcept
{
    return a.frame == b.frame && a.generation == b.generation && a.recording == b.recording &&
        a.renderWidth == b.renderWidth && a.renderHeight == b.renderHeight &&
        a.cropX == b.cropX && a.cropY == b.cropY && a.activeWidth == b.activeWidth &&
        a.activeHeight == b.activeHeight && a.lobe == b.lobe && a.providerScale == b.providerScale;
}
inline bool ValidIdentity(const Identity& x) noexcept
{
    if (!x.generation || !x.recording || !x.renderWidth || !x.renderHeight ||
        !x.activeWidth || !x.activeHeight || x.renderWidth > MaxTextureDimension ||
        x.renderHeight > MaxTextureDimension || x.cropX < 0 || x.cropY < 0) return false;
    if (uint64_t(x.cropX) + x.activeWidth > x.renderWidth ||
        uint64_t(x.cropY) + x.activeHeight > x.renderHeight) return false;
    return (x.lobe == Lobe::Diffuse && x.providerScale == 16) ||
        (x.lobe == Lobe::Specular && x.providerScale == 256);
}

// Every resource is annotated with the same immutable recording identity.
// The certificate binds ALL potential donor taps in the clipped radius square,
// before guide weights or candidate-derived exclusions. Code 1 in support R32_UINT
// certifies that complete footprint; 0 and all reserved codes mean unknown.
// The host cannot infer this certificate from selected/raw equality or alpha.
struct Evidence
{
    Identity identity {};
    EvidenceKind authority = EvidenceKind::Unknown;
    EvidenceKind support = EvidenceKind::Unknown;
    SourceStage sourceStage = SourceStage::Unknown;
    uint32_t estimatorVersion = EstimatorVersion;
    uint32_t radius = 0;
    uint64_t producerVersion = 0;
};
struct Frame
{
    Identity identity {};
    bool reset = false, resized = false;
};
struct Layout
{
    uint32_t width = 0, height = 0, rowPitch = 0;
    uint64_t offset = 0, bytes = 0;
};
inline bool FinitePositive(float x) noexcept { return std::isfinite(x) && x > 0; }
inline bool NormalPositive(float x) noexcept { return std::isnormal(x) && x > 0; }
inline bool ValidConfig(const Config& c) noexcept
{
    if (uint32_t(c.representation) > 1 || c.radius > 8) return false;
    const std::array<float,8> values {c.spatialSigma,c.depthTolerance,c.normalCosine,
        c.roughnessTolerance,c.guideChromaRadius,c.maxLogDelta,c.supportPrior,c.strength};
    for (float x : values)
        if (!std::isfinite(x) || (x!=0 && !std::isnormal(x))) return false;
    if (c.strength < 0 || c.strength > 1 || c.maxLogDelta < 0 || c.maxLogDelta > 2 ||
        c.normalCosine < -1 || c.normalCosine >= 1 || c.supportPrior < 0) return false;
    // Validate *stored float32* and arithmetic denominators, including squaring.
    // Subnormal scales can flush to zero on GPU and are therefore unsupported.
    if (!NormalPositive(c.spatialSigma) || !NormalPositive(c.spatialSigma*c.spatialSigma) ||
        !NormalPositive(c.depthTolerance) || !NormalPositive(c.roughnessTolerance) ||
        !NormalPositive(c.guideChromaRadius) || !NormalPositive(c.guideChromaRadius*c.guideChromaRadius) ||
        !NormalPositive(1.0f-c.normalCosine)) return false;
    // Bound products used before division; these generous diagnostic bounds are
    // contract restrictions, not quality tuning. They exclude FP32 overflow.
    if (c.depthTolerance > 1 || c.roughnessTolerance > 1 || c.spatialSigma > 4096 ||
        c.guideChromaRadius > 64 || c.supportPrior > 1048576) return false;
    return true;
}
inline bool ValidLayout(const Layout& x, uint32_t aw, uint32_t ah) noexcept
{
    if (!x.width || !x.height || x.width > MaxTextureDimension || x.height > MaxTextureDimension ||
        !aw || !ah || aw > x.width || ah > x.height || x.rowPitch % 256 || x.offset % 512 ||
        uint64_t(x.rowPitch) < uint64_t(x.width)*8 || x.bytes % 4 || !x.bytes ||
        x.bytes > UINT32_MAX || x.offset > UINT32_MAX) return false;
    // Require the FULL pitched allocation, including the final row's padding.
    const uint64_t end = x.offset + uint64_t(x.rowPitch)*x.height;
    return end <= x.bytes && end <= UINT32_MAX;
}
inline bool ValidLayouts(const std::array<Layout,4>& all, uint32_t aw, uint32_t ah) noexcept
{
    for(const auto& x:all) if(!ValidLayout(x,aw,ah)) return false;
    const auto& s=all[2]; const auto& o=all[3];
    return s.width==o.width && s.height==o.height && s.rowPitch==o.rowPitch &&
        s.offset==o.offset && s.bytes==o.bytes;
}
inline Decision Validate(const Config& c, const Frame& f, const Evidence& e) noexcept
{
    if (!ValidConfig(c)) return Decision::InvalidConfig;
    if (!c.enabled) return Decision::Off;
    if (!c.acknowledgeRejectedResearch) return Decision::Off;
    if (c.strength == 0 || c.maxLogDelta == 0) return Decision::ZeroStrength;
    if (f.reset || f.resized) return Decision::ResetOrResize;
    if (!ValidIdentity(f.identity) || !SameIdentity(f.identity,e.identity)) return Decision::InvalidIdentity;
    if (e.sourceStage != SourceStage::PreProviderPhysicalSnapshot) return Decision::UnsupportedSource;
    if (e.authority != EvidenceKind::SyntheticFixture && e.authority != EvidenceKind::ExternalCertificate)
        return Decision::UnknownAuthority;
    if ((e.support != EvidenceKind::SyntheticFixture && e.support != EvidenceKind::ExternalCertificate) ||
        !e.producerVersion || e.estimatorVersion != EstimatorVersion || e.radius != c.radius)
        return Decision::UnknownSupport;
    return Decision::Ready;
}

// HLSL cbuffer (b0): seven 16-byte registers; upload placement remains 256 bytes.
struct alignas(16) Constants
{
    std::array<uint32_t,4> extent {}, rowPitch {}, byteOffset {}, control {};
    std::array<float,4> support {}, colour {};
    std::array<uint32_t,4> byteSize {};
};
static_assert(sizeof(Constants) == 112);
static_assert(offsetof(Constants,support) == 64 && offsetof(Constants,colour) == 80 &&
              offsetof(Constants,byteSize) == 96);
constexpr uint32_t ConstantAllocationBytes = 256;
inline Constants MakeConstants(const Config& c, const Frame& f, const std::array<Layout,4>& l) noexcept
{
    Constants out;
    out.extent = {f.identity.activeWidth,f.identity.activeHeight,l[2].width,l[2].height};
    for (size_t i=0;i<4;++i)
    { out.rowPitch[i]=l[i].rowPitch; out.byteOffset[i]=uint32_t(l[i].offset); out.byteSize[i]=uint32_t(l[i].bytes); }
    out.control = {1,uint32_t(c.representation),c.radius,EstimatorVersion};
    out.support = {c.spatialSigma,c.depthTolerance,c.normalCosine,c.roughnessTolerance};
    out.colour = {c.guideChromaRadius,c.maxLogDelta,c.supportPrior,c.strength};
    return out;
}
} // namespace NativeColour
