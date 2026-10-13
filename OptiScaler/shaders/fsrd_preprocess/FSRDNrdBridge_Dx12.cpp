#include "pch.h"
#include "FSRDNrdBridge_Dx12.h"
namespace NrdBridge
{
bool SupportedExecutable() noexcept { return false; }
bool StartupEnabled() noexcept { return false; }
bool Initialize(ID3D12Device*) noexcept { return false; }
void Shutdown() noexcept {}
void OnPipelineCreated(ID3D12PipelineState*, const char*) noexcept {}
void OnSetPipeline(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept {}
void OnReset(ID3D12GraphicsCommandList*, ID3D12PipelineState*) noexcept {}
void BeforeDispatch(ID3D12GraphicsCommandList*) noexcept {}
void AfterDispatch(ID3D12GraphicsCommandList*) noexcept {}
void OnReleased(void*) noexcept {}
void OnPresent() noexcept {}
void OnTitleTag(ID3D12GraphicsCommandList*, const char*, ID3D12Resource*) noexcept {}
Status GetStatus() { return {}; }
void SetRuntimeEnabled(bool) noexcept {}
bool RuntimeEnabled() noexcept { return false; }
void SetDebugMode(DebugMode) noexcept {}
DebugMode GetDebugMode() noexcept { return DebugMode::Off; }
void RequestHistoryReset() noexcept {}
}
