#pragma once
#include "FSRDNrdBridge_Types.h"
#include <memory>
struct SLConstantsSnapshot;

namespace NrdBridge
{
class RRWrapper
{
    struct Impl;
    std::shared_ptr<Impl> impl_;
  public:
    RRWrapper();
    ~RRWrapper();
    bool PrepareFrame(const SLConstantsSnapshot&, bool requestedReset, FrameParameters& out, std::string& error);
    bool Dispatch(ID3D12GraphicsCommandList*, const ConvertedResources&, ID3D12Resource* outputSpec,
                  ID3D12Resource* outputDiff, const FrameParameters&, std::string& error);
    void ResetHistory() noexcept;
    uint64_t ContextGeneration() const noexcept;
};
}
