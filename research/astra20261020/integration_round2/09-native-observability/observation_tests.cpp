#include "OptiScaler/shaders/fsrd_preprocess/FSRDNrdObservationContract.h"
#include <iostream>
#include <string>

namespace O = FSRDNrdObservation;
namespace
{
int checks = 0, failures = 0;
std::string mutant;
void Check(bool value, const char* label)
{
    ++checks;
    if (!value) { ++failures; std::cerr << "FAIL: " << label << '\n'; }
}
bool Close(double a, double b, double tolerance = 1e-5) { return std::abs(a-b) <= tolerance; }
O::Surface Radiance(O::Role role = O::Role::RawRR, O::Lobe lobe = O::Lobe::Diffuse)
{
    O::Surface out;
    out.availability = O::Availability::Present; out.unavailableReason = O::Reason::None;
    out.role = role; out.lobe = lobe; out.stamp = {7, 180, 3, 9, 1}; out.resourceId = 41;
    out.layout.dxgiFormat = 10; out.layout.encoding = O::Encoding::Rgba16FloatWords;
    out.layout.allocation = {19, 13}; out.layout.active = {17, 11}; out.layout.captured = {3, 2};
    out.layout.cropOrigin = {4, 5}; out.layout.byteOffset = 512; out.layout.rowPitch = 256;
    out.layout.rowBytes = 24; out.layout.payloadBytes = 792;
    out.scale = {1, lobe == O::Lobe::Diffuse ? 16u : 256u, 1};
    return out;
}
O::Reason Authority(const O::SelectionWitness& selection, const O::Surface& raw,
                    const O::Surface& selected, O::EqualityGuard equality)
{
    // Deliberately wrong implementation: a matching capture is asserted to own
    // raw RR even though its host selection decision is unknown/protected.
    if (mutant == "authority" && equality == O::EqualityGuard::EqualWords) return O::Reason::None;
    return O::ValidateRawAuthority(selection, raw, selected, equality);
}
O::PreviousCoordinate Previous(uint32_t x, uint32_t y, float mx, float my, O::Origin current,
                               O::Origin previous, O::Extent render, O::MotionConvention convention)
{
    if (mutant == "origin") previous = current; // Deliberately drop moving-crop offset.
    return O::PreviousPixel(x, y, mx, my, current, previous, render, convention);
}
uint64_t Compose(uint32_t low, uint32_t high)
{
    if (mutant == "carry") return low; // Deliberately discard captured high word.
    return O::ComposeCarryWords(low, high);
}
O::DecodedNormal Normal(uint32_t word)
{
    if (mutant == "normal")
    {
        // Deliberately misread packed RGB as a Cartesian normal, consuming the
        // roughness bits as Z instead of decoding the two-channel octahedron.
        const float x = float(word & 1023u)/1023.0f*2.0f-1.0f;
        const float y = float((word >> 10) & 1023u)/1023.0f*2.0f-1.0f;
        const float z = float((word >> 20) & 1023u)/1023.0f*2.0f-1.0f;
        const float inverse = 1.0f/std::sqrt(x*x+y*y+z*z);
        return {{x*inverse,y*inverse,z*inverse},float((word >> 20) & 1023u)/1023.0f,(word >> 30)&3u};
    }
    return O::DecodeNormalRoughness(word);
}
void MetadataCases()
{
    const auto valid = Radiance();
    Check(O::ValidateSurface(valid) == O::Reason::None, "valid cropped/padded D16 packet");
    auto bad = valid; bad.layout.cropOrigin = {15, 5};
    Check(O::ValidateSurface(bad) == O::Reason::WrongOrigin, "capture cannot extend beyond active crop");
    bad = valid; bad.layout.cropOrigin.x++;
    Check(O::CompareDomain(bad, valid) == O::Reason::WrongOrigin, "different valid origins are different domains");
    bad = valid; bad.stamp.resetEpoch++;
    Check(O::CompareDomain(bad, valid) == O::Reason::StaleResetEpoch, "reset epoch mismatch rejected");
    bad = valid; bad.stamp.resourceEpoch++;
    Check(O::CompareDomain(bad, valid) == O::Reason::StaleResourceEpoch, "resize/device resource generation mismatch rejected");
    bad = valid; bad.stamp.streamId++;
    Check(O::CompareDomain(bad, valid) == O::Reason::WrongStream, "different contexts cannot share history");
    bad = valid; bad.stamp.frame--;
    Check(O::CompareDomain(bad, valid) == O::Reason::StaleFrame, "same epoch does not make stale frame current");
    bad = valid; bad.stamp.known = 0;
    Check(O::ValidateSurface(bad) == O::Reason::UnknownStamp, "unobserved epoch remains unknown");
    bad = valid; bad.lobe = O::Lobe::Specular;
    Check(O::CompareDomain(bad, valid) == O::Reason::WrongLobe, "diffuse/specular identity is explicit");
    bad = valid; bad.scale.providerMultiplier = 256;
    Check(O::CompareDomain(bad, valid) == O::Reason::WrongScale, "D16 cannot be relabelled S256");
    bad = valid; bad.scale.storedMultiplier = 16;
    Check(O::CompareDomain(bad, valid) == O::Reason::WrongScale, "scaled provider payload differs from restored physical units");
    bad = valid; bad.scale.known = 0;
    Check(O::ValidateSurface(bad) == O::Reason::UnknownScale, "missing scale remains unknown");
    bad = valid; bad.layout.dxgiFormat = 2;
    Check(O::ValidateSurface(bad) == O::Reason::WrongFormat, "RGBA32 cannot masquerade as half words");
    bad = valid; bad.role = O::Role::NativeNormalRoughness; bad.lobe = O::Lobe::None;
    bad.layout.dxgiFormat = 41; bad.layout.encoding = O::Encoding::R32FloatWords;
    bad.layout.rowBytes = 12;
    Check(O::ValidateSurface(bad) == O::Reason::WrongFormat, "normal role rejects scalar float instead of packed native guide");
    bad = valid; bad.role = static_cast<O::Role>(999);
    Check(O::ValidateSurface(bad) == O::Reason::UnknownRole, "out of range role cannot bypass radiance rules");
    Check(O::FormatMatches(62, O::Encoding::R8UintWords) && O::RoleMatches(O::Role::GeometryValidity, O::Encoding::R8UintWords),
          "native raw-validity R8_UINT format is explicit");
    bad = valid; bad.layout.payloadBytes--;
    Check(O::ValidateSurface(bad) == O::Reason::TruncatedPayload, "final row byte bounds checked");
    bad = valid; bad.layout.rowPitch = std::numeric_limits<uint64_t>::max();
    Check(O::ValidateSurface(bad) == O::Reason::TruncatedPayload, "row arithmetic overflow rejected");
    bad = valid; bad.availability = O::Availability::Missing;
    Check(O::ValidateSurface(bad) == O::Reason::MissingObservation, "missing observations not zero-filled truth");
    bad = valid; bad.layout.allocation = {31, 27}; bad.layout.rowPitch = 512; bad.layout.payloadBytes = 1048;
    Check(O::CompareDomain(bad, valid) == O::Reason::None, "unequal allocations and pitches are legal");
}
void AuthorityCases()
{
    const auto raw = Radiance();
    auto selected = Radiance(O::Role::SelectedOutput);
    O::SelectionWitness witness {O::SelectionPath::RawRR, raw.stamp, raw.lobe, 41, 41};
    Check(Authority(witness, raw, selected, O::EqualityGuard::EqualWords) == O::Reason::None,
          "actual raw selection plus identity plus equality is eligible");
    witness.path = O::SelectionPath::Unknown;
    Check(Authority(witness, raw, selected, O::EqualityGuard::EqualWords) == O::Reason::UnknownSelection,
          "equal words cannot manufacture unknown selection authority");
    witness.path = O::SelectionPath::LobeRecovery;
    Check(Authority(witness, raw, selected, O::EqualityGuard::EqualWords) == O::Reason::ProtectedSelection,
          "identity-valued recovery remains protected");
    witness.path = O::SelectionPath::FlatAlbedo;
    Check(Authority(witness, raw, selected, O::EqualityGuard::EqualWords) == O::Reason::ProtectedSelection,
          "identity-valued flat recovery remains protected");
    witness.path = O::SelectionPath::RawRR; witness.selectedResourceId = 42;
    Check(O::SelectionAuthority(witness) == O::Authority::Unknown, "declared raw route must alias actual raw resource");
    witness.selectedResourceId = 41;
    Check(Authority(witness, raw, selected, O::EqualityGuard::Unknown) == O::Reason::EqualityUnavailable,
          "unread equality is not assumed");
    Check(Authority(witness, raw, selected, O::EqualityGuard::DifferentWords) == O::Reason::UnequalWords,
          "post-selection mismatch fails additional equality guard");
    witness.stamp.resetEpoch--;
    Check(Authority(witness, raw, selected, O::EqualityGuard::EqualWords) == O::Reason::StaleResetEpoch,
          "stale host selection witness rejected");
}
void WordCases()
{
    const auto packet = Radiance();
    std::array<uint8_t, 900> source {}, copied {};
    source.fill(0xa5); copied.fill(0x7b);
    // Includes quiet/signalling half NaN alpha payloads, negative zero and Inf.
    const std::array<uint16_t, 4> alpha {0x7e35, 0x7d01, 0x8000, 0xfc00};
    for (size_t i = 0; i < alpha.size(); ++i)
    {
        const uint32_t x = uint32_t(i % 3), y = uint32_t(i / 3);
        const size_t offset = 512 + y*256 + x*8;
        const std::array<uint16_t, 4> pixel {0x3c00, 0x8000, 0x7e11, alpha[i]};
        std::memcpy(source.data()+offset, pixel.data(), 8);
    }
    Check(O::CopyWords(source.data(), 792, copied.data(), copied.size()), "complete footprint copied without float conversion");
    Check(O::EqualWords(source.data(), copied.data(), 792), "row padding and all observed words preserved");
    Check(copied[792] == 0x7b && copied.back() == 0x7b, "bytes after observation stay untouched");
    for (size_t i = 0; i < alpha.size(); ++i)
    {
        std::array<uint16_t, 4> pixel {};
        Check(O::ReadPixelWords(packet, copied.data(), copied.size(), uint32_t(i%3), uint32_t(i/3), pixel.data(), 8),
              "padded offset pixel read succeeds");
        Check(pixel[3] == alpha[i], "opaque alpha bits preserved exactly");
    }
    std::array<uint16_t, 4> pixel {};
    Check(!O::ReadPixelWords(packet, source.data(), 700, 0, 0, pixel.data(), 8), "truncated backing storage refused");
    Check(!O::ReadPixelWords(packet, source.data(), source.size(), 3, 0, pixel.data(), 8), "inactive x not clamped into ROI");
    Check(!O::CopyWords(source.data(), 792, copied.data(), 700), "short destination refused before copying");

    const std::array<uint8_t, 32> sumBytes {0xff,0xff,0xff,0xff, 2,0,0,0, 0,0,0,0, 3,0,0,0, 1,0,0,0};
    std::array<uint32_t, 8> words {};
    Check(O::ReadAnchorSums(sumBytes.data(), sumBytes.size(), words), "original eight atomic words retained");
    Check(Compose(words[0], words[1]) == 0x2ffffffffULL && Compose(words[2], words[3]) == 0x300000000ULL,
          "carry high words participate in totals");
    Check(!O::ReadAnchorSums(sumBytes.data(), 16, words), "partial low-only sum capture rejected");
}
void GuideAndCoordinateCases()
{
    const uint32_t word = 512u | (512u << 10) | (683u << 20) | (3u << 30);
    const auto normal = Normal(word);
    Check(normal.normal[2] > .9999f && Close(normal.roughness, 683.0/1023.0) && normal.category == 3,
          "native packed channels and category decoded independently");
    const auto south = Normal((3u << 30) | (17u << 20));
    Check(Close(south.normal[2], -1) && Close(south.roughness, 17.0/1023.0), "octahedral fold uses native convention");
    std::array<float, 2> uv {};
    Check(O::UnpackNormal11(2047, uv) == O::Reason::None && uv[0] == 1 && uv[1] == 1,
          "11-bit stored normal is unnormalised 6+5 payload");
    Check(O::UnpackNormal11(.5f, uv) == O::Reason::InvalidNormalPayload, "legacy normalized pack is not native 11-bit data");
    Check(O::UnpackNormal11(std::numeric_limits<float>::quiet_NaN(), uv) == O::Reason::InvalidNormalPayload,
          "nonfinite normal payload rejected");
    Check(O::ValidateDepth(-4, -1) == O::Reason::None && O::ValidateDepth(4, 1) == O::Reason::None,
          "both declared depth conventions supported");
    Check(O::ValidateDepth(-4, 1) == O::Reason::WrongDepthSign && O::ValidateDepth(-0.0f, 1) == O::Reason::WrongDepthSign,
          "depth sign and signed zero rejected");
    Check(O::ValidateDepth(std::numeric_limits<float>::infinity(), 1) == O::Reason::NonfiniteSample,
          "infinite depth is never sanitized into support");
    const O::MotionConvention convention {O::MotionUnits::FullRenderUv, O::MotionDirection::PreviousMinusCurrent,
                                          O::JitterConvention::AlreadyEncodedNoExtraDelta};
    const auto previous = Previous(10, 12, .125f, -.25f, {40, 20}, {35, 15}, {80, 40}, convention);
    Check(previous.reason == O::Reason::None && previous.x == 25 && previous.y == 7,
          "moving crop offset and full render UV scale both applied");
    Check(O::PreviousPixel(0, 0, 0, 0, {}, {}, {80,40}, {}).reason == O::Reason::UnknownMotionConvention,
          "unobserved native motion is not declared calibrated UV");
    Check(O::PreviousPixel(0, 0, 0, 0, {81,0}, {}, {80,40}, convention).reason == O::Reason::WrongOrigin,
          "origin outside render rejected before reprojection");
}

struct FrozenCase
{
    uint32_t capture, frame, x, y, currentX, currentY, previousX, previousY, width, height, normalWord;
    float motionX, motionY, nx, ny, nz, roughness;
    uint32_t category;
    double previousExpectedX, previousExpectedY;
    bool first;
    std::array<uint16_t, 4> raw, selected;
};
#ifdef OBSERVATION_HAS_FROZEN_CASES
#include "observation_frozen_cases.h"
void FrozenCases()
{
    uint32_t lastCapture = 0, lastFrame = 0;
    for (const auto& item : frozenCases)
    {
        Check(item.capture != lastCapture || item.frame > lastFrame, "frozen sequences stay chronological and unlooped");
        lastCapture = item.capture; lastFrame = item.frame;
        const auto normal = Normal(item.normalWord);
        Check(Close(normal.normal[0], item.nx) && Close(normal.normal[1], item.ny) && Close(normal.normal[2], item.nz) &&
              Close(normal.roughness, item.roughness) && normal.category == item.category,
              "original packed normal agrees with frozen job07 decoder");
        if (!item.first)
        {
            const O::MotionConvention convention {O::MotionUnits::FullRenderUv, O::MotionDirection::PreviousMinusCurrent,
                                                  O::JitterConvention::AlreadyEncodedNoExtraDelta};
            const auto previous = Previous(item.x, item.y, item.motionX, item.motionY, {item.currentX,item.currentY},
                                           {item.previousX,item.previousY}, {item.width,item.height}, convention);
            Check(Close(previous.x, item.previousExpectedX, 1e-3) && Close(previous.y, item.previousExpectedY, 1e-3),
                  "frozen moving crop coordinates agree with original clip loader");
        }
        std::array<uint16_t, 4> copy {};
        Check(O::CopyWords(item.raw.data(), 8, copy.data(), 8) && O::EqualWords(copy.data(), item.raw.data(), 8),
              "captured raw half words remain exact including alpha");
        const auto equality = O::EqualWords(item.raw.data(), item.selected.data(), 8) ?
            O::EqualityGuard::EqualWords : O::EqualityGuard::DifferentWords;
        Check(Authority({}, Radiance(), Radiance(O::Role::SelectedOutput), equality) == O::Reason::UnknownSelection,
              "frozen capture missing host authority stays unknown even with identical raw/selected words");
    }
}
#endif
}
int main(int argc, char** argv)
{
    if (argc > 1) mutant = argv[1];
    MetadataCases(); AuthorityCases(); WordCases(); GuideAndCoordinateCases();
#ifdef OBSERVATION_HAS_FROZEN_CASES
    FrozenCases();
#endif
    std::cout << "{\"checks\":" << checks << ",\"failures\":" << failures << ",\"mutant\":\"" << mutant << "\"}\n";
    return failures ? 1 : 0;
}
