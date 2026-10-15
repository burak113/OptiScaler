#pragma once
#include "FSRDNrdBridge_Types.h"
#include "FSRDNrdRawSignals_Dx12.h"
#include <memory>

namespace NrdBridge
{
class ConversionPass
{
    struct Impl;
    std::shared_ptr<Impl> impl_;
  public:
    ConversionPass();
    ~ConversionPass();
    bool Initialize(ID3D12Device*, uint32_t width, uint32_t height, std::string& error);
    // Optional nativeMaterialRoughness selects the six-SRV material guide variant; only analytic Qs uses it.
    bool Dispatch(ID3D12GraphicsCommandList*, const ConversionInputs&, const FrameParameters&,
                  ConvertedResources& out, std::string& error);
    // New zero-native-denoise path: no Recon output/light read or write. Native
    // origin comes only from the same-recording owned raw-header snapshot.
    bool DispatchGeometry(ID3D12GraphicsCommandList*, const ConversionInputs&, const FrameParameters&,
                          const RawSignalLease&, ConvertedResources& out, std::string& error);
    ID3D12Resource* OwnedPositiveViewDepth(const ConvertedResources&, const FrameParameters&) const noexcept;
    // When ConversionInputs::motion is null, Recon never reads a cached title MV.
    // Complete the motion guide using the current first chain-A Temporal SRV.
    // The depth mode and camera reprojection were captured at Recon; changing the mode invalidates this ticket.
    bool DispatchMotion(ID3D12GraphicsCommandList*, const ConvertedResources&, ID3D12Resource* titleMotion,
                        const FrameParameters&, std::string& error, const NativeMotionSource& = {});
    bool WriteDebug(ID3D12GraphicsCommandList*, const ConvertedResources&, ID3D12Resource* outputSpec,
                    ID3D12Resource* outputDiff, DebugMode, std::string& error, const OutputCommitGuard& = {},
                    SignalEncoding = SignalEncoding::Rgb, const TitleSignalConstants& = {});
    void ResetHistory() noexcept;
    uint64_t OwnedTextureBytes() const noexcept;
    uint64_t OwnedAuxiliaryBytes() const noexcept;
};
}
