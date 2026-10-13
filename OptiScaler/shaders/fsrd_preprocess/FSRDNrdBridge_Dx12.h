#pragma once
#include "FSRDNrdBridge_Types.h"

namespace NrdBridge
{
struct Status
{
    bool installed = false, runtimeEnabled = false, active = false;
    std::string phase = "Off", reason = "Set [FSR-RR] NrdBridge=true and restart.", resources;
    uint64_t framesBridged = 0, resets = 0;
    uint32_t width = 0, height = 0;
};
bool SupportedExecutable() noexcept;
bool StartupEnabled() noexcept;
bool Initialize(ID3D12Device*) noexcept;
void Shutdown() noexcept;
void OnPipelineCreated(ID3D12PipelineState*, const char* csSha256) noexcept;
void OnSetPipeline(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept;
void OnReset(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept;
void BeforeDispatch(ID3D12GraphicsCommandList*) noexcept;
void AfterDispatch(ID3D12GraphicsCommandList*) noexcept;
void OnReleased(void*) noexcept;
void OnPresent() noexcept;
void OnTitleTag(ID3D12GraphicsCommandList*, const char*, ID3D12Resource*) noexcept;
Status GetStatus();
void SetRuntimeEnabled(bool) noexcept;
bool RuntimeEnabled() noexcept;
void SetDebugMode(DebugMode) noexcept;
DebugMode GetDebugMode() noexcept;
void RequestHistoryReset() noexcept;
#ifdef FSRD_NRD_BRIDGE_TEST
void RegisterPipelineRoleForTesting(ID3D12PipelineState*, Role) noexcept;
#endif
}
