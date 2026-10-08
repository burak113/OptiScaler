#pragma once
#include <d3d12.h>
#include <array>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>

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
        std::string outputRoot; // Absolute UTF-8 path; blank keeps DLL/GAME_TRACE.
    };
    struct Status
    {
        std::string phase = "idle", message = "No game trace requested.", captureId, folder;
        uint32_t captured = 0, recorded = 0, target = FrameCount;
        uint32_t manifestPublished = 0;
        uint32_t pending = 0, staged = 0, awaitingDetach = 0, delayRemainingMs = 0;
        bool active = false;
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
                       std::span<const uint8_t> floorSeedConstants = {},
                       std::span<const uint8_t> floorFilterConstants = {},
                       bool submissionHooksAvailable = true) noexcept;
    // native_full1.bin is a legacy replay filename for the actual configured
    // pre-SR composition. Metadata explicitly makes no neutral Full1 claim.
    void RecordNative(ID3D12GraphicsCommandList*, Source actualNativeOutput, const FrameInfo&,
                      std::span<const DiagnosticSource> diagnostics = {}) noexcept;
    void CompleteFrame(ID3D12GraphicsCommandList*, Source actualCurrentOutput) noexcept;
    void CompleteSrFrame(ID3D12GraphicsCommandList*, Source actualSrOutput, const SrInfo&) noexcept;
    void Poll() noexcept;
    void Abort(std::string_view reason) noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> m_impl;
};
