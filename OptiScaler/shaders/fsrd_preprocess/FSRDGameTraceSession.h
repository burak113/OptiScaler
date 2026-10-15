#pragma once
#include <d3d12.h>
#include <array>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>

namespace sl { struct Constants; }
namespace NrdBridge
{
struct ConvertedResources;
struct FrameParameters;
struct TitleSignalConstants;
struct RRSettingsState;
struct RRRecordedOutputSnapshot;
}

// Capture only. Never feeds recorded data back into the denoiser/model.
class FSRDGameTraceSession
{
public:
    static constexpr uint32_t FrameCount = 128;
    static constexpr uint32_t TileSize = 128;
    enum class SrMode { Off, MappedRoi, FullOutput };
    struct Request
    {
        enum class RegionMode { Square, FullHeightStrip, FullRender };
        uint32_t x = 0, y = 0, size = TileSize, delaySeconds = 0;
        RegionMode regionMode = RegionMode::Square;
        uint32_t frameCount = FrameCount;
        SrMode srMode = SrMode::Off;
        // Transient diagnostic only: separate full-native RR RESET_each heads.
        // Never changes the primary RR context, history, or game composition.
        bool fullContextReference = false;
        bool particleLayerDiagnostics = false; // Optional original title guides; capture only.
        std::string outputRoot; // Absolute UTF-8 path; blank keeps DLL/GAME_TRACE.
        enum class CapturePath { Legacy, NrdBridge };
        CapturePath capturePath = CapturePath::Legacy;
        uint64_t bridgeDomain = 0; // Zero binds the first eligible selected-signal domain; never merges chains.
        bool bridgeWaitForReset = false; // Only a dedicated explicit USER reset request sets this.
        uint32_t bridgeSignal = 0; // 0=A Recon, 1=B PrePass. API default A preserves older callers.
    };
    struct Status
    {
        std::string phase = "idle", message = "No game trace requested.", captureId, folder;
        uint32_t captured = 0, recorded = 0, target = FrameCount;
        uint32_t manifestPublished = 0;
        uint32_t pending = 0, staged = 0, awaitingDetach = 0, delayRemainingMs = 0;
        bool active = false, nrdBridge = false;
        uint32_t bridgeSignal = 0;
        uint64_t cpuQueuedBytes = 0, retainedReadbackBytes = 0, estimatedPayloadBytes = 0;
        uint64_t estimatedFrameReadbackBytes = 0;
        uint64_t manifestWrites = 0, manifestBytesWritten = 0;
    };
    // Menu requests are transient, never saved as startup capture settings.
    static bool RequestStart(uint32_t x, uint32_t y, uint32_t delaySeconds = 0) noexcept;
    static bool RequestStart(const Request&) noexcept;
    static void RequestStop() noexcept;
    static Status GetStatus();
    static bool IsActive() noexcept;
    static bool WantsSrOutput() noexcept;
    static bool WantsFullContextReference() noexcept;
    static bool WantsParticleLayerDiagnostics() noexcept;
    static bool IsNrdBridgeCaptureActive() noexcept; // Atomic OFF gate, before metadata/native work.
    static bool WantsNrdBridgeSignal(uint32_t index) noexcept; // Filter BEFORE owner claim/reset/native work; 0=A, 1=B.
    static bool TakeNrdBridgeHistoryResetRequest(uint64_t domain = 0) noexcept;

    enum Slot : size_t { U, V, Qs, Qd, Skip, Packed, Depth, Motion, SourceCount };
    struct Source
    {
        ID3D12Resource* resource = nullptr;
        D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                      D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    };
    struct DiagnosticSource
    {
        std::string name;
        Source image;
        uint32_t baseX = 0, baseY = 0;
        // Capture metadata only; these fields never influence conversion.
        bool active = true;
        std::string inactiveReason;
        std::string metadataJson = "{}";
        bool required = false; // An active v3 source cannot silently lose its snapshot.
        bool motionAddressed = false, displayResolutionMotion = false;
        float motionWidth = 0, motionHeight = 0, jitterX = 0, jitterY = 0;
    };
    struct FrameInfo
    {
        std::string contextId; // Must include context creation generation, not just an address.
        uint64_t evaluationId = 0; // Monotonic actual native invocation ID; gaps reject.
        uint32_t frameIndex = 0, dispatchFlags = 0;
        bool reset = false;
        // JSON objects, serialized from actual applied controls/settings. No truth/reference.
        std::string controlsJson = "{}", settingsJson = "{}";
    };
    struct SrInfo
    {
        std::string contextId; // Actual process-local provider/owner identity.
        uint64_t evaluationId = 0;
        uint32_t width = 0, height = 0; // Valid dispatch extent, not allocation size.
        bool reset = false;
        std::string controlsJson = "{}";
    };
    struct BridgeIdentity
    {
        uint64_t domain = 0, recordingId = 0, recordingGeneration = 0;
        uint64_t cancellationSerial = 0, cacheGeneration = 0;
        uint32_t streamlineFrame = UINT32_MAX;
        bool operator==(const BridgeIdentity&) const noexcept = default;
    };
    struct BridgeSkippedDispatch
    {
        uint64_t sequence = 0;
        uint32_t role = 0; // Actual coordinator Role enum value, no inferred shader role.
        std::array<uint8_t,32> shaderSha256 {};
        std::array<uint32_t,3> groups {};
        bool shaderKnown = false, dimensionsKnown = false, indirect = false;
    };
    struct BridgeProviderBinaryIdentity
    {
        // Actual per-context FfxApiProxy route witness, resolved only while USER-armed.
        std::string routeAttestationJson;
    };
    using BridgeControlStatusObserver = void(*)(const BridgeIdentity&, uint32_t) noexcept;
    struct BridgeControlHeader
    {
        enum class Profile { ReconA, PrePassB };
        struct Word { uint32_t nativeByteOffset = 0, sourceBufferByteOffset = 0; };
        Profile profile = Profile::ReconA;
        Source image; // Exclusively owned raw snapshot buffer, never the title CBV.
        std::shared_ptr<void> owner;
        uint64_t recordingId = 0;
        uint32_t streamlineFrame = UINT32_MAX, bridgeFrame = 0, wordCount = 0;
        std::array<Word,8> words {};
        bool hasStatus = false;
        uint32_t statusByteOffset = 0; // Bridge-generated raw-capture status, never a native operand.
        BridgeControlStatusObserver statusObserver = nullptr; // Called post-fence, outside trace locks, nonzero only.
    };
    using BridgeFrameToken = std::shared_ptr<void>;
    // Caller owns the input/output leases, same-recording admission and injection
    // serialization. Call ONLY after motion is finalized and RecordOwned succeeds.
    // No reset/history mutation. The whole-frame budget is checked before copies.
    BridgeFrameToken RecordBridgeOwned(ID3D12Device*, ID3D12GraphicsCommandList*,
        const BridgeIdentity&, const NrdBridge::ConvertedResources&, const std::shared_ptr<void>& inputOwner,
        const NrdBridge::FrameParameters&, const sl::Constants&, uint32_t slFrame, uint32_t slViewport,
        const NrdBridge::RRSettingsState&,
        const NrdBridge::RRRecordedOutputSnapshot&, const BridgeProviderBinaryIdentity&,
        bool submissionHooksAvailable = true) noexcept;
    void RecordBridgeSkipped(const BridgeFrameToken&, ID3D12GraphicsCommandList*, const BridgeIdentity&,
                             const BridgeSkippedDispatch&) noexcept;
    // Optional actual captured words only. Zero-filled uncaptured header bytes
    // are never accepted as another profile's evidence. Shares the already planned
    // 40-byte shared readback: flag4B, up to8 native DWORDs, separate owned status4B; no new committed allocation.
    bool RecordBridgeControlHeader(const BridgeFrameToken&, ID3D12GraphicsCommandList*,
                                   const BridgeIdentity&, const BridgeControlHeader&) noexcept;
    // Synchronous borrowed sources only: caller holds live physical Borrow and
    // proves the current native targets. Never AddRef/queue a title source pointer.
    // The updated owned snapshot supplies the GPU-captured live encoding flag.
    bool CompleteBridgeFrame(const BridgeFrameToken&, ID3D12GraphicsCommandList*, const BridgeIdentity&,
        const std::array<Source,2>& encodedTargets, const NrdBridge::RRRecordedOutputSnapshot&,
        const NrdBridge::TitleSignalConstants& sourceConstants) noexcept;
    void CancelBridgeFrame(const BridgeFrameToken&, std::string_view reason) noexcept;

    FSRDGameTraceSession();
    ~FSRDGameTraceSession();
    FSRDGameTraceSession(const FSRDGameTraceSession&) = delete;
    FSRDGameTraceSession& operator=(const FSRDGameTraceSession&) = delete;

    // Caller installs real queue/Reset hooks before recording. All three stages
    // must occur on the SAME list/evaluation. Completed bytes are frozen under
    // the real submission gate; GPU resource release still requires real Reset.
    bool RecordSources(ID3D12Device*, ID3D12GraphicsCommandList*,
                       const std::array<Source, SourceCount>&, uint32_t renderWidth,
                       uint32_t renderHeight, std::span<const uint8_t> conversionConstants,
                       std::span<const DiagnosticSource> diagnostics = {},
                       std::span<const uint8_t> geometryConstants = {},
                       std::span<const uint8_t> flatDetailConstants = {},
                       bool submissionHooksAvailable = true) noexcept;
    // native_full1.bin is a legacy replay filename for the actual configured
    // pre-SR composition. Metadata explicitly makes no neutral Full1 claim.
    void RecordNative(ID3D12GraphicsCommandList*, Source actualNativeOutput, const FrameInfo&,
                      std::span<const DiagnosticSource> diagnostics = {}) noexcept;
    void CompleteFrame(ID3D12GraphicsCommandList*, Source actualCurrentOutput) noexcept;
    void CompleteSrFrame(ID3D12GraphicsCommandList*, Source actualSrOutput, const SrInfo&) noexcept;
    // Frame survey uses the SAME allocation ledger, fence registry, protected
    // CPU snapshots and disk writer as GAME_TRACE, with dynamic image slots.
    // Tokens own one real command-list recording, not a guessed frame lifetime.
    bool StartSurvey(uint32_t width, uint32_t height) noexcept;
    Status SurveyStatus() const;
    std::shared_ptr<void> BeginSurveyBatch(ID3D12Device*, ID3D12GraphicsCommandList*, uint64_t listId = 0) noexcept;
    bool SurveyTexture(const std::shared_ptr<void>& batch, std::string_view key,
                       Source, uint32_t subresource = 0, uint32_t x = 0, uint32_t y = 0,
                       uint32_t width = 0, uint32_t height = 0) noexcept;
    bool SurveyBuffer(const std::shared_ptr<void>& batch, std::string_view key,
                      Source, uint64_t byteOffset, uint32_t bytes) noexcept;
    void SealSurveyBatch(const std::shared_ptr<void>&) noexcept;
    void FinishSurvey(std::string_view metadataJson) noexcept;
    void Poll() noexcept;
    void Abort(std::string_view reason) noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};
