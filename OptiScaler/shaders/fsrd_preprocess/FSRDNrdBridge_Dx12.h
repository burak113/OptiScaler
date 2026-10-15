#pragma once
#include "FSRDNrdBridge_Types.h"
#include "misc/NrdBridgeBirth_Dx12.h"
#include "FSRDNrdBridgeRR_Dx12.h"

namespace NrdBridge
{
struct Status
{
    bool installed = false, runtimeEnabled = false, active = false;
    bool nativeMaterialGuidesActive = false;
    bool nativeHistoryDirty = false, runtimeDisablePending = false;
    uint64_t nativeDispatchesSkipped = 0;
    std::string phase = "Off", reason = "Set [FSR-RR] NrdBridge=true and restart.", resources;
    uint64_t framesBridged = 0, resets = 0;
    // Service totals: capture/Recon admission, not per-pixel material coverage.
    uint64_t nativeMaterialAttempts = 0, nativeMaterialSnapshots = 0, nativeMaterialFramesApplied = 0;
    uint64_t nativeMaterialUnknownState = 0, nativeMaterialKnownPSR = 0, nativeMaterialUnsupportedState = 0;
    uint64_t nativeMaterialCaptureFailures = 0, nativeMaterialModeResets = 0;
    uint32_t width = 0, height = 0;
};
bool SupportedExecutable() noexcept;
// Called once after loading configuration, before any device hooks are attached.
void ConfigureStartup(bool enabled) noexcept;
bool StartupEnabled() noexcept;
bool Initialize(ID3D12Device*) noexcept;
void Shutdown() noexcept;
void ReportUnavailable(const char* reason) noexcept;
void OnPipelineCreated(ID3D12PipelineState*, const char* csSha256) noexcept;
void OnSetPipeline(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept;
void OnReset(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept;
void BeforeDispatch(ID3D12GraphicsCommandList*) noexcept;
void AfterDispatch(ID3D12GraphicsCommandList*) noexcept;
enum class DispatchKind : uint8_t { Direct, Indirect, Bundle };
enum class DispatchDisposition : uint8_t { Forward, Suppress };
// Query after BeforeDispatch, immediately before forwarding the title call.
// Suppression belongs to an admitted recording transaction, never a shader hash alone.
DispatchDisposition OriginalDispatchDisposition(ID3D12GraphicsCommandList*, DispatchKind) noexcept;
void InvalidateRecordingProof(ID3D12GraphicsCommandList*, const char* reason) noexcept;
void OnResourceBarriers(ID3D12GraphicsCommandList*, UINT, const D3D12_RESOURCE_BARRIER*) noexcept;
void OnRecordingClosed(ID3D12GraphicsCommandList*, HRESULT) noexcept;
void OnReleased(void*) noexcept;
void OnBirthReleased(const NrdBridgeBirth::Token&) noexcept;
void OnPresent() noexcept;
void OnTitleTag(ID3D12GraphicsCommandList*, const char*, ID3D12Resource*) noexcept;
Status GetStatus();
void SetRuntimeEnabled(bool) noexcept;
bool RuntimeEnabled() noexcept;
void SetDebugMode(DebugMode) noexcept;
DebugMode GetDebugMode() noexcept;
void RequestHistoryReset() noexcept;
bool ApplyRRSettings(const RRSettings&, bool cameraProjectedDepthDelta, std::string& error) noexcept;
RRSettingsState GetRRSettingsState() noexcept;
bool CameraProjectedDepthEnabled() noexcept;
bool NativeDebugEnabled() noexcept;
// Quiet false means no eligible completed/same-recording diagnostic image.
bool PresentNativeDebug(ID3D12GraphicsCommandList*, ID3D12Resource*, D3D12_RESOURCE_STATES, std::string& error) noexcept;
#ifdef FSRD_NRD_BRIDGE_TEST
void RegisterPipelineRoleForTesting(ID3D12PipelineState*, Role, bool nativeContract = false) noexcept;
#endif
}
