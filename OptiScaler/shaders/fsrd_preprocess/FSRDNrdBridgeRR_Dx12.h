#pragma once
#include "FSRDNrdBridge_Types.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <memory>
#include <string>
struct SLConstantsSnapshot;

namespace NrdBridgeStagePerf { struct Sample; }

namespace NrdBridge
{
struct RRRecoveryFamily;
// D06/D07 proposed control-model vocabulary for requested/effective recovery
// tiers and fallback reasons. Diagnostic names only; not INI/API keys.
enum class LobeRecoveryTier : uint32_t { None = 0, FullPrecision = 1, MixedPrecision = 2 };
enum class LobeRecoveryFallbackReason : uint32_t
{
    None = 0, NotRequested = 1, DebugConstraint = 2, ZeroStrength = 3,
    ExternalFamilyUnavailable = 4, FamilyCapacity = 5, PreparationFailed = 6
};
// Optional graph budgets survive replacement temporal domains in one Service.
std::shared_ptr<RRRecoveryFamily> CreateRRRecoveryFamily() noexcept;
// P05 service-level owned-memory counters of one recovery family. These are
// metadata atomics of the allocation extents this service counts itself;
// provider-internal cost stays unknown and resident VRAM is never measured.
struct RRRecoveryFamilyMemory
{
    uint64_t graphBytes = 0, familyRetainedPeakBytes = 0, slotBytes = 0;
    uint32_t slots = 0;
};
RRRecoveryFamilyMemory SnapshotRecoveryFamilyMemory(const std::shared_ptr<RRRecoveryFamily>& family) noexcept;
// Config/UI inputs use a safe default; direct API validation remains strict.
static inline float NormalizeLobeRecoveryStrength(float value) noexcept
{
    return std::isfinite(value) ? std::clamp(value, 0.0f, 1.0f) : 1.0f;
}

struct FlatAlbedoSettings
{
    bool enabled = false, temporal = true;
    uint32_t roughness = 2, historyLength = 6;
    float strength = 1, anchor = 4, mix = 0, temporalDenoise = 1;
    // Bridge only, default off: specular blends to RR where the recovery output has collapsed; diffuse uses RR.
    bool rrFallback = false, diffuseRR = false;
    // Bridge only, default off, Temporal off: the specular recovery runs on a running mean along the reflection's
    // virtual motion and blends to RR (at the history's level) where that mean is still noisy.
    bool reflectionHistory = false;
    // Share of the history mean's fine detail kept over the robust fit (0 = the fit's softer result).
    float reflectionDetail = 1;
    // Optional reflection-history polish. Zero preserves the v4 graph and output.
    float reflectionPolish = 0;
    bool operator==(const FlatAlbedoSettings&) const = default;
};
// Shared by startup and live menu snapshots. This is the existing Flat Albedo
// Recovery configuration, independent of the optional non-flat lobe graph.
template<class Configuration> inline FlatAlbedoSettings ReadFlatAlbedoSettings(const Configuration& config)
{
    FlatAlbedoSettings out;
    if constexpr (requires { config.FfxDenoiserRecoveryFlatAlbedo; config.FfxDenoiserRecoveryFlatAlbedoStrength;
        config.FfxDenoiserRecoveryFlatRoughness; config.FfxDenoiserRecoveryFlatAnchor; config.FfxDenoiserRecoveryFlatMix;
        config.FfxDenoiserRecoveryFlatTemporal; config.FfxDenoiserRecoveryFlatHistoryLength; config.FfxDenoiserRecoveryFlatTemporalDenoise; })
    {
        const auto finite = [](float x,float fallback,float lo,float hi) { return std::isfinite(x) ? std::clamp(x,lo,hi) : fallback; };
        out.enabled = config.FfxDenoiserRecoveryFlatAlbedo.value_or_default();
        out.temporal = config.FfxDenoiserRecoveryFlatTemporal.value_or_default();
        out.roughness = uint32_t(std::clamp(config.FfxDenoiserRecoveryFlatRoughness.value_or_default(),0,1023));
        out.historyLength = uint32_t(std::clamp(config.FfxDenoiserRecoveryFlatHistoryLength.value_or_default(),1,6));
        out.strength = finite(config.FfxDenoiserRecoveryFlatAlbedoStrength.value_or_default(),1,0,1);
        out.anchor = finite(config.FfxDenoiserRecoveryFlatAnchor.value_or_default(),4,0,8);
        out.mix = finite(config.FfxDenoiserRecoveryFlatMix.value_or_default(),0,0,1);
        out.temporalDenoise = finite(config.FfxDenoiserRecoveryFlatTemporalDenoise.value_or_default(),1,0,2);
    }
    // Separate so configurations without these keys keep every other flat setting.
    if constexpr (requires { config.FfxDenoiserRecoveryFlatRRFallback; config.FfxDenoiserRecoveryFlatDiffuseRR; })
    {
        out.rrFallback = config.FfxDenoiserRecoveryFlatRRFallback.value_or_default();
        out.diffuseRR = config.FfxDenoiserRecoveryFlatDiffuseRR.value_or_default();
    }
    if constexpr (requires { config.FfxDenoiserRecoveryFlatReflectionHistory; config.FfxDenoiserRecoveryFlatReflectionDetail; })
    {
        out.reflectionHistory = config.FfxDenoiserRecoveryFlatReflectionHistory.value_or_default();
        const float detail = config.FfxDenoiserRecoveryFlatReflectionDetail.value_or_default();
        out.reflectionDetail = std::isfinite(detail) ? std::clamp(detail,0.0f,1.0f) : 1.0f;
    }
    if constexpr (requires { config.FfxDenoiserRecoveryFlatReflectionPolish; })
    {
        const float polish = config.FfxDenoiserRecoveryFlatReflectionPolish.value_or_default();
        out.reflectionPolish = std::isfinite(polish) ? std::clamp(polish,0.0f,1.0f) : 0.0f;
    }
    return out;
}
struct RRSettings
{
    // Bits0..5 select AMD scalar keys1..6 in values0..5; bit6 selects
    // key7's absolute debug-depth bounds in values6/7. Mask0 uses AMD defaults.
    uint32_t overrideMask = 0;
    std::array<float, 8> values {};
    // -1 is the integration's OFF value; AMD defines overview0/fullscreen1.
    int32_t nativeDebugView = -1;
    uint32_t nativeDebugViewport = 0;
    bool preserveNativeMaterialIDs = false;
    bool nativeTemporalMotion = false;
    bool nativeMaterialGuides = false;
    // A/B rollback: restore the pre-fix previous-visible-depth motion Z instead of the
    // camera-only estimate. Conversion-side only; the provider never sees this flag.
    bool legacyMotionDepth = false;
    bool lobeRecovery = false;
    FlatAlbedoSettings flatAlbedo {};
    // D02/WP08 experiment selector; recorded so traces can distinguish the gated fill.
    bool surfaceValidFill = false;
    float recoverySpecular = 1.0f, recoveryDiffuse = 1.0f;
    float nativeSpecularBlend = 0.0f; // Deprecated source ABI; ignored. Native NRD output never corrects RR.
};
struct RRSettingsState
{
    bool ready = false;
    bool lobeRecoveryActive = false, lobeRecoveryFallback = false;
    bool flatAlbedoActive = false, flatAlbedoFallback = false;
    std::string flatAlbedoLastError;
    RRSettings requested {};
    std::array<float, 8> defaults {}, effective {};
    // D06/D07 proposed diagnostic vocabulary, NOT INI/API keys: requested and
    // effective recovery tier plus the machine fallback reason of the last
    // recorded chain. The real optional error text travels in LastError.
    uint32_t lobeRecoveryRequestedTier = 0, lobeRecoveryTier = 0, lobeRecoveryFallbackReason = 0;
    std::string lobeRecoveryLastError; // Exact recovery prepare error; empty when none/fixed.
};
// Stable names for GameTrace/menu presentation. Proposed control-model labels.
const char* LobeRecoveryTierName(uint32_t tier) noexcept;
const char* LobeRecoveryFallbackReasonName(uint32_t reason) noexcept;
bool ValidateRRSettings(const RRSettings&, std::string& error);

struct RRWrapperNativeDebugOutputSnapshot
{
    ID3D12Resource* resource = nullptr;
    std::shared_ptr<void> owner;
    ID3D12GraphicsCommandList* recording = nullptr;
    uint32_t frameSL = UINT32_MAX, width = 0, height = 0;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
};

struct RRRecordedOutput;
using RRRecordedOutputLease = std::shared_ptr<const RRRecordedOutput>;
// Owned linear, demodulated RGB only. Keep owner alive through every trace/copy submission.
struct RRRecordedOutputSnapshot
{
    ID3D12Resource *rawSpec = nullptr, *rawDiff = nullptr, *selectedSpec = nullptr, *selectedDiff = nullptr;
    std::shared_ptr<void> owner;
    ID3D12GraphicsCommandList* recording = nullptr;
    uint32_t frameSL = UINT32_MAX, width = 0, height = 0, frameIndex = 0;
    uint64_t contextGeneration = 0, recordingId = 0;
    bool outputCommitted = false, recoveryActive = false, recoveryFallback = false;
    // Exact provider geometry and separate original-roughness recovery policy.
    ID3D12Resource* providerNormals = nullptr;
    bool flatAlbedoActive = false, flatAlbedoFallback = false;
    uint32_t flatAlbedoRoughness = 0;
    std::string flatAlbedoError;
    float providerRadianceScale = 256.0f;
    // D06/D07 per-frame recovery diagnostics (control-model vocabulary; names
    // are proposed, not keys). Text travels outside the hashed settings lineage.
    uint32_t recoveryTier = 0, recoveryFallbackReason = 0;
    std::string recoveryErrorText;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
    // Published only after late native flag capture is recorded; this is an owned snapshot, never the title CBV.
    ID3D12Resource* encodingFlag = nullptr;
    bool nativeEncodingCaptured = false;
    D3D12_RESOURCE_STATES encodingFlagState = D3D12_RESOURCE_STATE_COMMON;
    // Actual AMD1.2 dispatch tail, not reconstructed FrameParameters (448-byte ABI, offset264).
    std::array<uint8_t, 184> providerControl {};
    uint64_t providerVersionId = 0;
    uint32_t providerApiVersion = 0, providerSignalFlags = 0, providerContextFlags = 0;
    std::array<char, 128> providerName {};
    uint32_t providerCheckerboardSignalFlags = 0, diffuseCheckerboardOrigin = 0, specularCheckerboardOrigin = 0;
};

class RRWrapper
{
    struct Impl;
    std::shared_ptr<Impl> impl_;
    bool RecordOwnedImpl(ID3D12GraphicsCommandList*, const ConvertedResources&, const FrameParameters&,
                         RRRecordedOutputLease&, std::string&, NrdBridgeStagePerf::Sample*, bool prepareNativeCommit);
  public:
    RRWrapper();
    ~RRWrapper();
    bool PrepareFrame(const SLConstantsSnapshot&, bool requestedReset, FrameParameters& out, std::string& error);
    // Record only into owned RR stages. No title output/Consumer binding is consulted.
    bool RecordOwned(ID3D12GraphicsCommandList*, const ConvertedResources&, const FrameParameters&,
                     RRRecordedOutputLease& output, std::string& error, NrdBridgeStagePerf::Sample* profiling = nullptr);
    // Same native recording/frame/generation, one successful commit; caller holds physical borrow/serialization.
    bool CommitOwned(ID3D12GraphicsCommandList*, const RRRecordedOutputLease&, ID3D12Resource* outputSpec,
                     ID3D12Resource* outputDiff, const FrameParameters&, std::string& error,
                     const OutputCommitGuard& = {}, NrdBridgeStagePerf::Sample* profiling = nullptr);
    // Caller holds injection serialization, outside coordinator gMutex. Cancelled/unsubmitted work never retires a newer physical generation.
    void AbandonOwned(const RRRecordedOutputLease&) noexcept;
    RRRecordedOutputSnapshot GetOwnedOutputSnapshot(const RRRecordedOutputLease&) const noexcept;
    // Cold, explicitly armed trace only. Empty means this adapter has no actual-route witness.
    std::string GetOwnedOutputProviderAttestation(const RRRecordedOutputLease&) const noexcept;
    bool Dispatch(ID3D12GraphicsCommandList*, const ConvertedResources&, ID3D12Resource* outputSpec,
                  ID3D12Resource* outputDiff, const FrameParameters&, std::string& error,
                  const OutputCommitGuard& = {}, NrdBridgeStagePerf::Sample* profiling = nullptr);
    // Coordinator serializes this snapshot with dispatch; Config is never read here.
    bool Configure(const RRSettings&, std::string& error);
    RRSettingsState GetSettingsState() const noexcept;
    // Call after Configure under the coordinator's existing injection serialization.
    void SetRecoveryFamily(const std::shared_ptr<RRRecoveryFamily>&) noexcept;
    RRWrapperNativeDebugOutputSnapshot GetNativeDebugOutputSnapshot() const noexcept;
    // The coordinator proves same-recording or fence-published source ordering
    // before presentation. Output is borrowed for recording, then restored.
    bool PresentNativeDebug(ID3D12GraphicsCommandList*, ID3D12Resource* output,
                            D3D12_RESOURCE_STATES outputState, uint32_t frameSL, std::string& error,
                            bool orderedAcrossLists = false, const OutputCommitGuard& = {});
    bool PresentNativeDebug(ID3D12GraphicsCommandList*, ID3D12Resource* output,
                            D3D12_RESOURCE_STATES outputState, const RRWrapperNativeDebugOutputSnapshot& source,
                            std::string& error, bool orderedAcrossLists = false, const OutputCommitGuard& = {});
    void ResetHistory() noexcept;
    void DiscardRecordingHistory() noexcept;
    uint64_t ContextGeneration() const noexcept;
    uint64_t OwnedStagingBytes() const noexcept;
    uint64_t OwnedAuxiliaryBytes() const noexcept;
    // D07/WP10 proposed staging ledger snapshot (metadata only; names are
    // control-model vocabulary). limitBytes 0 marks admission disabled.
    // retirementGuards counts saturated retirements that could not return
    // their full charge; a matched charge/retire lifecycle keeps it zero.
    struct StagingLedgerSnapshot
    {
        uint64_t limitBytes = 0, retainedBytes = 0, retainedPeakBytes = 0, retiredTotalBytes = 0;
        uint32_t retainedSlots = 0, rejections = 0, retirementGuards = 0;
        bool byteAdmissionActive = false;
    };
    StagingLedgerSnapshot SnapshotStagingLedger() const noexcept;
    const std::string& CameraConventionDescription() const noexcept;
};
}
