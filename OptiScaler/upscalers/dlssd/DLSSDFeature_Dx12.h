#pragma once
#include "DLSSDFeature.h"
#include <upscalers/IFeature_Dx12.h>
#include <shaders/rcas/RCAS_Dx12.h>
#include <string>

class DLSSDFeatureDx12 : public DLSSDFeature, public IFeature_Dx12
{
  private:
    bool _recordedComputeLifetime = false;
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
