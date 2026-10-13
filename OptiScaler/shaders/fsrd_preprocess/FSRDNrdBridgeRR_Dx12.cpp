#include "pch.h"
#include "FSRDNrdBridgeRR_Dx12.h"
namespace NrdBridge
{
struct RRWrapper::Impl {};
RRWrapper::RRWrapper() = default;
RRWrapper::~RRWrapper() = default;
bool RRWrapper::PrepareFrame(const SLConstantsSnapshot&, bool, FrameParameters&, std::string& error)
{ error = "NRD RR is not initialized"; return false; }
bool RRWrapper::Dispatch(ID3D12GraphicsCommandList*, const ConvertedResources&, ID3D12Resource*,
                        ID3D12Resource*, const FrameParameters&, std::string& error)
{ error = "NRD RR is not initialized"; return false; }
void RRWrapper::ResetHistory() noexcept {}
uint64_t RRWrapper::ContextGeneration() const noexcept { return 0; }
}
