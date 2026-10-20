#pragma once

// Portable producer/consumer contract; no D3D objects, allocations, image writes,
// or implicit conversions from a geometry tag to estimator authority.
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace NrdBridge::SupportContract
{
inline constexpr uint32_t Version = 1;
inline constexpr uint32_t CellSize = 8;
inline constexpr uint32_t NativeTapMask = 0x1ff;

enum class Reason : uint64_t
{
    None = 0,
    UnavailableDonorFootprint = 1ull << 0,
    UnavailableKeyCorrespondence = 1ull << 1,
    InvalidDomain = 1ull << 2,
    CropGridMismatch = 1ull << 3,
    StaleEpoch = 1ull << 4,
    NonFinite = 1ull << 5,
    DepthSign = 1ull << 6,
    IncompleteCell = 1ull << 7,
    UnobservedSample = 1ull << 8,
    ThinOrMixedSurface = 1ull << 9,
    InvalidPolicy = 1ull << 10,
    WrongFootprint = 1ull << 11,
    InvalidWeight = 1ull << 12,
    UnpublishedKey = 1ull << 13,
    StaleKey = 1ull << 14,
    InvalidKeySlot = 1ull << 15,
    NoNonzeroDonors = 1ull << 16,
    UnobservedGlobalVeto = 1ull << 17,
    InvalidCertificate = 1ull << 18,
    UnavailableCorrespondence = 1ull << 19,
};
inline constexpr uint64_t Bits(Reason r) noexcept { return static_cast<uint64_t>(r); }

struct Domain
{
    uint32_t activeWidth = 0, activeHeight = 0; // FULL active render, never ROI storage extent.
    uint32_t allocationWidth = 0, allocationHeight = 0;
    int32_t cropX = 0, cropY = 0; // Observed crop origin in the original active render.
    uint32_t cropWidth = 0, cropHeight = 0;
    int32_t gridOriginX = 0, gridOriginY = 0; // Native cell grid is anchored at full-render (0,0).
    uint32_t gridWidth = 0, gridHeight = 0;
    int32_t depthSign = 0; // Exactly +1 or -1 for ORIGINAL signed linear view Z.
    uint32_t cell = CellSize;
    uint64_t basisId = 0; // Attested common geometric basis, not a material ID.
    uint64_t resetEpoch = 0, frame = 0;
};

inline bool SameGrid(const Domain& a, const Domain& b) noexcept
{
    return a.activeWidth == b.activeWidth && a.activeHeight == b.activeHeight &&
           a.allocationWidth == b.allocationWidth && a.allocationHeight == b.allocationHeight &&
           a.cropX == b.cropX && a.cropY == b.cropY && a.cropWidth == b.cropWidth &&
           a.cropHeight == b.cropHeight && a.gridOriginX == b.gridOriginX &&
           a.gridOriginY == b.gridOriginY && a.gridWidth == b.gridWidth && a.gridHeight == b.gridHeight &&
           a.depthSign == b.depthSign && a.cell == b.cell && a.basisId == b.basisId;
}

inline uint64_t ValidateDomain(const Domain& d) noexcept
{
    // The actual native host uses floor(active/8), not ceil(active/8).
    // Partial edge cells and off-phase cropped observations cannot be certified.
    if (d.cell != CellSize || d.activeWidth < CellSize || d.activeHeight < CellSize ||
        d.allocationWidth < d.activeWidth || d.allocationHeight < d.activeHeight || !d.basisId ||
        d.cropX < 0 || d.cropY < 0 || !d.cropWidth || !d.cropHeight ||
        uint64_t(d.cropX)+d.cropWidth > d.activeWidth || uint64_t(d.cropY)+d.cropHeight > d.activeHeight ||
        (d.depthSign != 1 && d.depthSign != -1) || d.gridWidth != d.activeWidth / CellSize ||
        d.gridHeight != d.activeHeight / CellSize)
        return Bits(Reason::InvalidDomain);
    if (d.gridOriginX != 0 || d.gridOriginY != 0 || d.cropX % int32_t(CellSize) != 0 ||
        d.cropY % int32_t(CellSize) != 0)
        return Bits(Reason::CropGridMismatch);
    return 0;
}

inline bool CompleteObservedCell(const Domain& d, uint32_t x, uint32_t y) noexcept
{
    return x < d.gridWidth && y < d.gridHeight && d.cropX >= 0 && d.cropY >= 0 &&
           uint64_t(x)*CellSize >= uint64_t(d.cropX) && uint64_t(y)*CellSize >= uint64_t(d.cropY) &&
           (uint64_t(x)+1)*CellSize <= uint64_t(d.cropX)+d.cropWidth &&
           (uint64_t(y)+1)*CellSize <= uint64_t(d.cropY)+d.cropHeight;
}

struct Vec3 { double x = 0, y = 0, z = 0; };
inline Vec3 Sub(Vec3 a, Vec3 b) noexcept { return {a.x-b.x, a.y-b.y, a.z-b.z}; }
inline double Dot(Vec3 a, Vec3 b) noexcept { return a.x*b.x + a.y*b.y + a.z*b.z; }
inline bool Finite(Vec3 a) noexcept { return std::isfinite(a.x) && std::isfinite(a.y) && std::isfinite(a.z); }

struct Policy
{
    double planeAbsolute = 1e-5, planeRelative = 1e-4;
    double normalCosine = 0.9986295347545738; // cos(3 degrees), geometry only.
};
inline bool ValidPolicy(const Policy& p) noexcept
{
    return std::isfinite(p.planeAbsolute) && std::isfinite(p.planeRelative) &&
           std::isfinite(p.normalCosine) && p.planeAbsolute >= 0 && p.planeRelative >= 0 &&
           p.normalCosine > 0 && p.normalCosine <= 1;
}
inline bool SamePolicy(const Policy& a, const Policy& b) noexcept
{
    return a.planeAbsolute == b.planeAbsolute && a.planeRelative == b.planeRelative &&
           a.normalCosine == b.normalCosine;
}

struct Pixel
{
    Vec3 position, normal; // Same attested basis for all current/key observations.
    double signedDepth = 0;
    bool observed = false, correspondenceKnown = false;
};

struct CellCertificate
{
    Domain domain;
    Policy policy;
    uint32_t x = 0, y = 0, sampleCount = 0;
    Vec3 position, normal;
    double depthMagnitude = 0;
    uint64_t reasons = Bits(Reason::IncompleteCell);
};

inline uint64_t ValidateCell(const CellCertificate& c) noexcept
{
    uint64_t reasons = c.reasons | ValidateDomain(c.domain);
    if (!ValidPolicy(c.policy)) reasons |= Bits(Reason::InvalidPolicy);
    if (c.sampleCount != CellSize*CellSize || !CompleteObservedCell(c.domain,c.x,c.y))
        reasons |= Bits(Reason::IncompleteCell);
    const double n2 = Dot(c.normal,c.normal);
    if (!Finite(c.position) || !Finite(c.normal) || !std::isfinite(n2) ||
        std::abs(n2-1.0) > 1e-6 || !std::isfinite(c.depthMagnitude) || !(c.depthMagnitude > 1e-8))
        reasons |= Bits(Reason::NonFinite);
    return reasons;
}

inline CellCertificate CertifyCell(const Domain& domain, uint32_t x, uint32_t y, const Pixel* samples,
                                   size_t count, const Policy& policy = {}) noexcept
{
    CellCertificate out; out.domain = domain; out.policy = policy; out.x = x; out.y = y;
    out.reasons = ValidateDomain(domain);
    if (!ValidPolicy(policy)) out.reasons |= Bits(Reason::InvalidPolicy);
    if (!samples || count != CellSize*CellSize || !CompleteObservedCell(domain,x,y))
        out.reasons |= Bits(Reason::IncompleteCell);
    if (out.reasons) return out;
    out.sampleCount = uint32_t(count);
    Vec3 sumP {}, sumN {};
    for (size_t i = 0; i < count; ++i)
    {
        const auto& s = samples[i];
        if (!s.observed) out.reasons |= Bits(Reason::UnobservedSample);
        if (!s.correspondenceKnown) out.reasons |= Bits(Reason::UnavailableCorrespondence);
        const double n2 = Dot(s.normal, s.normal);
        if (!Finite(s.position) || !Finite(s.normal) || !std::isfinite(s.signedDepth) ||
            !std::isfinite(n2) || !(n2 > 1e-16))
        { out.reasons |= Bits(Reason::NonFinite); continue; }
        if (!(s.signedDepth*domain.depthSign > 1e-8)) out.reasons |= Bits(Reason::DepthSign);
        const double inv = 1 / std::sqrt(n2);
        sumP.x += s.position.x; sumP.y += s.position.y; sumP.z += s.position.z;
        sumN.x += s.normal.x*inv; sumN.y += s.normal.y*inv; sumN.z += s.normal.z*inv;
        const double absDepth = std::abs(s.signedDepth);
        if (absDepth > out.depthMagnitude) out.depthMagnitude = absDepth;
    }
    if (out.reasons) return out;
    const double n2 = Dot(sumN, sumN);
    if (!Finite(sumP) || !std::isfinite(n2) || !(n2 > 1e-16))
    { out.reasons |= Bits(Reason::NonFinite); return out; }
    out.position = {sumP.x/count, sumP.y/count, sumP.z/count};
    const double inv = 1/std::sqrt(n2);
    out.normal = {sumN.x*inv, sumN.y*inv, sumN.z*inv};
    const double tol = policy.planeAbsolute + policy.planeRelative*out.depthMagnitude;
    if (!std::isfinite(tol)) { out.reasons |= Bits(Reason::NonFinite); return out; }
    for (size_t i = 0; i < count; ++i)
    {
        const double length = std::sqrt(Dot(samples[i].normal, samples[i].normal));
        const double normalAgreement = Dot(samples[i].normal, out.normal)/length;
        const auto delta = Sub(samples[i].position, out.position);
        const double residual = Dot(delta, out.normal);
        // Finite original components do not guarantee finite intermediate
        // subtraction or dot products. NaN must not pass an ordered comparison.
        if (!Finite(delta) || !std::isfinite(normalAgreement) || !std::isfinite(residual))
        { out.reasons |= Bits(Reason::NonFinite); continue; }
        if (normalAgreement < policy.normalCosine || std::abs(residual) > tol)
            out.reasons |= Bits(Reason::ThinOrMixedSurface);
    }
    return out;
}

inline uint64_t Compatible(const CellCertificate& a, const CellCertificate& b, const Policy& p) noexcept
{
    uint64_t reasons = ValidateCell(a) | ValidateCell(b);
    if (!ValidPolicy(p)) reasons |= Bits(Reason::InvalidPolicy);
    if (!SamePolicy(a.policy,p) || !SamePolicy(b.policy,p)) reasons |= Bits(Reason::InvalidPolicy);
    if (!SameGrid(a.domain, b.domain)) reasons |= Bits(Reason::CropGridMismatch);
    if (a.domain.resetEpoch != b.domain.resetEpoch) reasons |= Bits(Reason::StaleEpoch);
    if (a.sampleCount != CellSize*CellSize || b.sampleCount != CellSize*CellSize)
        reasons |= Bits(Reason::IncompleteCell);
    if (reasons) return reasons;
    const double scale = a.depthMagnitude > b.depthMagnitude ? a.depthMagnitude : b.depthMagnitude;
    const double tol = p.planeAbsolute + p.planeRelative*scale;
    const auto delta = Sub(a.position, b.position);
    if (!std::isfinite(tol) || !Finite(delta)) return Bits(Reason::NonFinite);
    const double normalAgreement = Dot(a.normal,b.normal);
    const double residualA = Dot(delta,a.normal), residualB = Dot(delta,b.normal);
    if (!std::isfinite(normalAgreement) || !std::isfinite(residualA) || !std::isfinite(residualB))
        return Bits(Reason::NonFinite);
    if (normalAgreement < p.normalCosine || std::abs(residualA) > tol ||
        std::abs(residualB) > tol) reasons |= Bits(Reason::ThinOrMixedSurface);
    return reasons;
}

struct KeyTap
{
    CellCertificate cell;
    double weight = 0; // Actual nonnegative sampler weight, INCLUDING zeros.
};
struct RecallWitness
{
    bool observed = false, keyValid = false, exactFractionsObserved = false;
    uint32_t slot = 6; // Native ring has six physical slots; sentinel is invalid.
    uint64_t resetEpoch = 0, frame = 0, selectedGeneration = 0, capturedGeneration = 0;
    uint64_t submittedFence = 0, completedFence = 0;
    uint64_t submittedTimeline = 0, completedTimeline = 0; // Same observed fence owner; never compare unrelated queues.
    double gridX = 0, gridY = 0; // Actual QUANTIZED sampler coordinate, texel index space.
    std::array<KeyTap,4> taps; // (0,0),(1,0),(0,1),(1,1), before optional native clamp.
};
struct DonorTap
{
    CellCertificate current;
    double weight = 0; // Actual recalled.y*recalled.w; zero taps remain explicit.
    bool weightObserved = false;
    RecallWitness recall;
};
struct Footprint
{
    CellCertificate recipient;
    uint32_t step = 0; // Exact quantized Params2.z, 1..4 (protected default is 3).
    bool globalVetoObserved = false; // Global frame sums are a separate identity veto.
    std::array<DonorTap,9> taps; // dy=-1..1 outer, dx=-1..1 inner, including duplicates.
};

// Certificate is an in-process C++ ABI, never a raw-dumped wire struct. Serialize
// named fields to avoid compiler padding/endianness. Scope is geometric support
// of a correction's nonzero local radiance donors, NOT causal/material truth.
struct Certificate
{
    uint32_t version = Version, valid = 0;
    uint64_t reasons = Bits(Reason::UnavailableDonorFootprint);
    uint32_t scope = 0; // 0=unknown, 1=anchor local donor geometry (never material identity).
    Policy policy;
    Domain domain;
    uint32_t step = 0, observedTapMask = 0, nonzeroDonors = 0, nonzeroKeyDonors = 0;
    uint32_t recipientX = 0, recipientY = 0;
};

inline Certificate InvalidNativeSupport(uint64_t resetEpoch, uint64_t frame) noexcept
{
    Certificate out; out.domain.resetEpoch = resetEpoch; out.domain.frame = frame;
    out.reasons = Bits(Reason::UnavailableDonorFootprint) | Bits(Reason::UnavailableKeyCorrespondence);
    return out;
}

inline Certificate Produce(const Footprint& in, const Policy& policy = {}) noexcept
{
    Certificate out; out.domain = in.recipient.domain; out.step = in.step; out.scope = 1; out.policy = policy;
    out.recipientX = in.recipient.x; out.recipientY = in.recipient.y;
    out.reasons = ValidateCell(in.recipient);
    if (!SamePolicy(in.recipient.policy,policy)) out.reasons |= Bits(Reason::InvalidPolicy);
    if (!ValidPolicy(policy)) out.reasons |= Bits(Reason::InvalidPolicy);
    if (in.step < 1 || in.step > 4) out.reasons |= Bits(Reason::WrongFootprint);
    if (!in.globalVetoObserved) out.reasons |= Bits(Reason::UnobservedGlobalVeto);
    if (out.reasons) return out;
    const auto clampCell = [](int64_t v, uint32_t extent) noexcept -> uint32_t
    { return v < 0 ? 0 : v >= extent ? extent-1 : uint32_t(v); };
    for (uint32_t i = 0; i < 9; ++i)
    {
        const auto& donor = in.taps[i];
        if (!donor.weightObserved) { out.reasons |= Bits(Reason::UnavailableDonorFootprint); continue; }
        out.observedTapMask |= 1u << i;
        const uint32_t x = clampCell(int64_t(in.recipient.x) + (int64_t(i%3)-1)*in.step, out.domain.gridWidth);
        const uint32_t y = clampCell(int64_t(in.recipient.y) + (int64_t(i/3)-1)*in.step, out.domain.gridHeight);
        if (donor.current.x != x || donor.current.y != y) out.reasons |= Bits(Reason::WrongFootprint);
        if (!std::isfinite(donor.weight) || donor.weight < 0 || donor.weight > 1)
        { out.reasons |= Bits(Reason::InvalidWeight); continue; }
        if (donor.weight == 0) continue; // Never discard a positive tiny donor.
        ++out.nonzeroDonors;
        out.reasons |= Compatible(in.recipient, donor.current, policy);
        if (donor.current.domain.frame != out.domain.frame) out.reasons |= Bits(Reason::StaleKey);
        const auto& key = donor.recall;
        if (!key.observed || !key.exactFractionsObserved)
        { out.reasons |= Bits(Reason::UnavailableKeyCorrespondence); continue; }
        if (key.resetEpoch != out.domain.resetEpoch) out.reasons |= Bits(Reason::StaleEpoch);
        if (!key.keyValid || !key.submittedFence || key.completedFence < key.submittedFence ||
            key.submittedFence == UINT64_MAX || key.completedFence == UINT64_MAX ||
            !key.submittedTimeline || key.submittedTimeline != key.completedTimeline)
            out.reasons |= Bits(Reason::UnpublishedKey);
        if (!key.selectedGeneration || key.selectedGeneration != key.capturedGeneration || key.frame >= out.domain.frame)
            out.reasons |= Bits(Reason::StaleKey);
        if (key.slot >= 6) out.reasons |= Bits(Reason::InvalidKeySlot);
        if (!std::isfinite(key.gridX) || !std::isfinite(key.gridY))
        { out.reasons |= Bits(Reason::NonFinite); continue; }
        // Avoid integer overflow before floor-to-index conversion. Out-of-domain
        // history remains unknown even if the native sampler would clamp it.
        if (key.gridX < 0 || key.gridY < 0 || key.gridX >= out.domain.gridWidth || key.gridY >= out.domain.gridHeight)
        { out.reasons |= Bits(Reason::UnavailableCorrespondence); continue; }
        const uint32_t bx = uint32_t(std::floor(key.gridX)), by = uint32_t(std::floor(key.gridY));
        const double fx = key.gridX-bx, fy = key.gridY-by;
        double mass = 0;
        for (uint32_t j = 0; j < 4; ++j)
        {
            const auto& tap = key.taps[j];
            if (!std::isfinite(tap.weight) || tap.weight < 0 || tap.weight > 1)
            { out.reasons |= Bits(Reason::InvalidWeight); continue; }
            const double exactWeight = (j%2 ? fx : 1-fx)*(j/2 ? fy : 1-fy);
            // Actual fixed-point sampler fractions/products are binary-exact.
            // A caller's ideal-UV approximation is not accepted as that witness.
            if (tap.weight != exactWeight) out.reasons |= Bits(Reason::InvalidWeight);
            mass += tap.weight;
            if (tap.weight == 0) continue;
            ++out.nonzeroKeyDonors;
            const uint32_t kx = bx+j%2, ky = by+j/2;
            if (kx >= out.domain.gridWidth || ky >= out.domain.gridHeight)
            { out.reasons |= Bits(Reason::UnavailableCorrespondence); continue; }
            if (tap.cell.x != kx || tap.cell.y != ky) out.reasons |= Bits(Reason::WrongFootprint);
            if (tap.cell.domain.frame != key.frame || tap.cell.domain.resetEpoch != key.resetEpoch)
                out.reasons |= Bits(Reason::StaleKey);
            out.reasons |= Compatible(in.recipient, tap.cell, policy);
        }
        if (!std::isfinite(mass) || std::abs(mass-1.0) > 1e-6) out.reasons |= Bits(Reason::InvalidWeight);
    }
    if (!out.nonzeroDonors || !out.nonzeroKeyDonors) out.reasons |= Bits(Reason::NoNonzeroDonors);
    out.valid = out.reasons == 0 && out.observedTapMask == NativeTapMask ? 1u : 0u;
    return out;
}

inline bool Accepts(const Certificate& c, const Domain& expected, uint32_t expectedStep,
                    uint32_t recipientX, uint32_t recipientY, const Policy& requiredPolicy = {}) noexcept
{
    return c.version == Version && c.valid == 1 && c.reasons == 0 && c.scope == 1 && !ValidateDomain(expected) &&
           ValidPolicy(c.policy) && ValidPolicy(requiredPolicy) &&
           SamePolicy(c.policy,requiredPolicy) &&
           SameGrid(c.domain, expected) && c.domain.resetEpoch == expected.resetEpoch &&
           c.domain.frame == expected.frame && c.step == expectedStep && expectedStep >= 1 && expectedStep <= 4 &&
           c.recipientX == recipientX && c.recipientY == recipientY &&
           CompleteObservedCell(expected,recipientX,recipientY) && c.observedTapMask == NativeTapMask &&
           c.nonzeroDonors >= 1 && c.nonzeroDonors <= 9 && c.nonzeroKeyDonors >= c.nonzeroDonors &&
           c.nonzeroKeyDonors <= 4*c.nonzeroDonors;
}
} // namespace NrdBridge::SupportContract
