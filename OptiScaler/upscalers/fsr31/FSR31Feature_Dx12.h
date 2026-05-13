#pragma once
#include "FSR31Feature.h"
#include <upscalers/IFeature_Dx12.h>

#include "dx12/ffx_api_dx12.h"
#include "proxies/FfxApi_Proxy.h"

/**
 * @brief DirectX 12 implementation of FSR 3.1/4 for OptiScaler. Translates semi-generalized
 * TSR inputs based on customized Nvidia NGX parameter tables to AMD FFX API calls.
 */
class FSR31FeatureDx12 : public FSR31Feature, public IFeature_Dx12
{
  public:
    struct InputResources
    {
        // Primary resources
        ID3D12Resource* Color;
        ID3D12Resource* MotionVectors;
        ID3D12Resource* Depth;

        // Optional resources
        ID3D12Resource* TransparencyMask;
        ID3D12Resource* ReactiveMask;
        ID3D12Resource* DlssBiasMaskFallback;
        ID3D12Resource* ExposureMap;
    };

    /**
     * @brief Initializes the FSR feature, loads the FFX DX12 proxy methods,
     * and verifies if the backend module is ready.
     */
    FSR31FeatureDx12(unsigned int InHandleId, NVSDK_NGX_Parameter* InParameters);

    ~FSR31FeatureDx12();

    feature_version Version() override { return FSR31Feature::Version(); }

    std::string Name() const override { return FSR31Feature::Name(); }

    /**
     * @brief Initializes the FFX context, selects an FSR version based on configuration and
     availability, and initializes helper shaders.
     * @return true if initialization succeeds.
     */
    bool Init(ID3D12Device* InDevice, ID3D12GraphicsCommandList* InCommandList,
              NVSDK_NGX_Parameter* InParameters) override;

    /**
     * @brief Executes the upscaling pass. Gathers input and output textures and configuration
     * from the NGX parameter table. Includes optional, user-configurable pre and post processing
     * steps for sharpening and scaling.
     */
    bool Evaluate(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters) override;

  protected:
    bool _isInReset;

    NVSDK_NGX_Parameter* SetParameters(NVSDK_NGX_Parameter* InParameters);
    bool IsWithDx12() final { return false; }
    /**
     * @brief Initializes a compatible FSR upscaler based on NGX and OptiScaler configuratons on startup or
     * on mode changes.
     * @param InParameters DLSS-compatible configuration table
     */
    bool InitFSR3(const NVSDK_NGX_Parameter* InParameters) override;

    virtual void ConfigureUpscalerContext(const NVSDK_NGX_Parameter& ngxParams);

    // Evaluate utils

    /**
     * @brief Prepares upscaler inputs and configuration from a generic NGX param table, converting input buffers
     * if needed, into a native ffx descriptor struct.
     */
    bool PrepareUpscalerInput(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& inParams,
                              ffxDispatchDescUpscale& upscalerDesc);

    /**
     * @brief Attempts to populate reactive and transparency masks for FSR input, converting/repurposing DLSS bias mask
     * if provided and configured.
     */
    void GetReactiveAndTransparencyMasks(ID3D12GraphicsCommandList* InCommandList, InputResources& inputs);

    /**
     * @brief Dispatches FSR upscaler using inputs and configuration from a preprepared descriptor struct.
     */
    bool DispatchUpscaler(ID3D12GraphicsCommandList* InCommandList, const ffxDispatchDescUpscale& desc);

    /**
     * @brief Applies optional post-processing to FSR output if configured. Includes options for post-process RCAS,
     FSR output rescaling and ImGui compositing.
     */
    void PostProcess(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& inParams,
                     const ffxDispatchDescUpscale& upscaleDesc);

    /**
     * @brief Sets optional resource transition barriers. Used in conjunction with game quirk workarounds.
     */
    virtual void SetConfigurableBarriers(ID3D12GraphicsCommandList* InCommandList) const;

    /**
     * @brief Resets optional resource transition barriers. Used in conjunction with game quirk workarounds.
     */
    virtual void ResetConfigurableBarriers(ID3D12GraphicsCommandList* InCommandList) const;

  private:
    bool _isSuperScaling;
    bool _isSharpening;

    InputResources _inputBuffers;
    ID3D12Resource* _upscalerOutput;
    ID3D12Resource* _mainOutput;

    bool CreateUpscalerContext(const NVSDK_NGX_Parameter& ngxParams);

    void SetResolutionConfig();

    bool QueryUpscalerVersions();

    uint64_t GetUpscalerOverrideID();

    bool SetUpscalerTarget(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& inParams);

    /**
     * @brief Reads application configuration data from the NGX table the upscaling pass and sets the appropriate FFX
     * configurations in the dispatch descriptor. Executed immediately before FSR dispatch.
     */
    void ConfigureUpscaler(const NVSDK_NGX_Parameter& inParams, ffxDispatchDescUpscale& fsrParams);
};