#pragma once
#include "FSRDNrdBridge_Types.h"
#include <array>
#include <memory>
struct SLConstantsSnapshot;

namespace NrdBridge
{
struct RRSettings
{
    // Bits0..5 select AMD scalar keys1..6 in values0..5; bit6 selects
    // key7's absolute debug-depth bounds in values6/7. Mask0 uses AMD defaults.
    uint32_t overrideMask = 0;
    std::array<float, 8> values {};
    // -1 is the integration's OFF value; AMD defines overview0/fullscreen1.
    int32_t nativeDebugView = -1;
    uint32_t nativeDebugViewport = 0;
};
struct RRSettingsState
{
    bool ready = false;
    RRSettings requested {};
    std::array<float, 8> defaults {}, effective {};
};
bool ValidateRRSettings(const RRSettings&, std::string& error);

struct RRWrapperNativeDebugOutputSnapshot
{
    ID3D12Resource* resource = nullptr;
    std::shared_ptr<void> owner;
    ID3D12GraphicsCommandList* recording = nullptr;
    uint32_t frameSL = UINT32_MAX, width = 0, height = 0;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
};

class RRWrapper
{
    struct Impl;
    std::shared_ptr<Impl> impl_;
  public:
    RRWrapper();
    ~RRWrapper();
    bool PrepareFrame(const SLConstantsSnapshot&, bool requestedReset, FrameParameters& out, std::string& error);
    bool Dispatch(ID3D12GraphicsCommandList*, const ConvertedResources&, ID3D12Resource* outputSpec,
                  ID3D12Resource* outputDiff, const FrameParameters&, std::string& error,
                  const OutputCommitGuard& = {});
    // Coordinator serializes this snapshot with dispatch; Config is never read here.
    bool Configure(const RRSettings&, std::string& error);
    RRSettingsState GetSettingsState() const noexcept;
    RRWrapperNativeDebugOutputSnapshot GetNativeDebugOutputSnapshot() const noexcept;
    // The coordinator proves same-recording or fence-published source ordering
    // before presentation. Output is borrowed for recording, then restored.
    bool PresentNativeDebug(ID3D12GraphicsCommandList*, ID3D12Resource* output,
                            D3D12_RESOURCE_STATES outputState, uint32_t frameSL, std::string& error,
                            bool orderedAcrossLists = false);
    void ResetHistory() noexcept;
    void DiscardRecordingHistory() noexcept;
    uint64_t ContextGeneration() const noexcept;
    uint64_t OwnedStagingBytes() const noexcept;
    uint64_t OwnedAuxiliaryBytes() const noexcept;
    const std::string& CameraConventionDescription() const noexcept;
};
}
