#include "pch.h"
#include "FSRDNrdBridgePass_Dx12.h"
namespace NrdBridge
{
struct ConversionPass::Impl {};
ConversionPass::ConversionPass() = default;
ConversionPass::~ConversionPass() = default;
bool ConversionPass::Initialize(ID3D12Device*, uint32_t, uint32_t, std::string& error)
{ error = "NRD conversion is not initialized"; return false; }
bool ConversionPass::Dispatch(ID3D12GraphicsCommandList*, const ConversionInputs&, const FrameParameters&,
                              ConvertedResources&, std::string& error)
{ error = "NRD conversion is not initialized"; return false; }
bool ConversionPass::WriteDebug(ID3D12GraphicsCommandList*, const ConvertedResources&, ID3D12Resource*,
                                ID3D12Resource*, DebugMode, std::string& error)
{ error = "NRD conversion is not initialized"; return false; }
void ConversionPass::ResetHistory() noexcept {}
uint64_t ConversionPass::OwnedTextureBytes() const noexcept { return 0; }
}
