#pragma once
#include "DLSSDFeature.h"
#include <upscalers/IFeature_Dx12.h>
#include <shaders/rcas/RCAS_Dx12.h>
#include <memory>
#include <string>

class DLSSDFeatureDx12 : public DLSSDFeature, public IFeature_Dx12
{
  private:
    bool _recordedComputeLifetime = false;

    // Owns the NGX feature handle and its storage. Like FfxContextOwner for FFX contexts: a
    // recorded-lifetime owner (FSRD's native fallback) leases it to every list it evaluates
    // into, so ReleaseFeature runs only after the feature, every recording that can still be
    // submitted and every unfinished submission let go.
    struct HandleOwner
    {
        NVSDK_NGX_Handle storage {};
        NVSDK_NGX_Handle* handle = &storage;
        bool created = false;
        ~HandleOwner();
    };
    std::shared_ptr<HandleOwner> _handleOwner;
  protected:
    bool InitDLSSD(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters);

  public:
    bool InitInternal(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters) override;
    bool EvaluateInternal(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters) override;

    feature_version Version() override { return DLSSDFeature::Version(); }
    Upscaler GetUpscalerType() const final { return DLSSDFeature::GetUpscalerType(); }
    API Api() const override { return IFeature_Dx12::Api(); }
    bool CallsUpscalerEndByItself() override { return IFeature_Dx12::CallsUpscalerEndByItself(); }

    bool IsWithDx12() override { return false; }
    bool UsesRecordedComputeLifetime() const override { return _recordedComputeLifetime; }

    DLSSDFeatureDx12(unsigned int InHandleId, NVSDK_NGX_Parameter* InParameters, bool recordedComputeLifetime = false);
    ~DLSSDFeatureDx12();
};
