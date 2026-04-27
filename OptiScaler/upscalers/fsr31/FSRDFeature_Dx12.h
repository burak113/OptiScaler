#pragma once
#include "FSR31Feature_Dx12.h"
#include "shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.h"
#include <DirectXMath.h>

/**
 * @brief Unfied denoiser-upscaler utilising AMD FSR Ray Regeneration and Super Resolution with
 * DLSS-RR inputs. Extends FSR 3.1+ upscaler implementation.
 */
class FSRDFeatureDx12 : public FSR31FeatureDx12
{
  public:
    using FSRDConvDesc = FSRDPreprocessor_Dx12::ConversionDesc;

    FSRDFeatureDx12(uint32_t InHandleId, NVSDK_NGX_Parameter* InParameters);

    ~FSRDFeatureDx12();

    feature_version Version() override { return FSR31FeatureDx12::Version(); }

    std::string Name() const override { return FSR31FeatureDx12::Name(); }

    bool Evaluate(ID3D12GraphicsCommandList* InCommandList, NVSDK_NGX_Parameter* InParameters) override;

  private:
    ffxContext _pDenoiserCtx;
    ffxCreateContextDescDenoiser _denoiserCtxDesc;
    FfxApiDenoiserSettings _denoiserSettings;
    bool _isMode2;

    static bool s_isHWDepth;
    static bool s_isRoughnessPacked;

    FSRDConvDesc _convDesc;
    DirectX::XMFLOAT3 _lastCamPos; // Last world space camera position

    // Matrices
    DirectX::XMMATRIX _invViewMatrix;  // Camera rotation and translation
    DirectX::XMMATRIX _viewMatrix;     // World to camera space
    DirectX::XMMATRIX _prevViewMatrix; // Last world to camera space
    DirectX::XMMATRIX _projMatrix;     // Perspective projection matrix

    std::unique_ptr<FSRDPreprocessor_Dx12> FSRDConvShader;

    bool InitFSR3(const NVSDK_NGX_Parameter* InParameters) override;

    bool CreateDenoiserContext();

    bool QueryDenoiserVersions();

    void DestroyDenoiserContext();

    void UpdateSize();

    /**
     * @brief Generates FSR denoiser configuration and input buffers from DLSS-RR inputs and NGX configurations,
     * converts and repacks resources internally.
     */
    template<typename SignalDescT>
    bool PrepareDenoiserInput(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& ngxParams,
                              ffxDispatchDescDenoiser& dispatchDesc, SignalDescT& signalDesc);

    /**
     * @brief Retrieves DLSS-RR inputs to populate the inputs for the conversion shader in order to generate
     FSR-RR compatible buffers.
     */
    bool PrepareDenoiseConvInput(const NVSDK_NGX_Parameter& inParams);

    /**
     * @brief Converts previously retrieved DLSS-RR resources into FSR-RR inputs.
     */
    bool ConvertDenoiserBuffers(ID3D12GraphicsCommandList* InCommandList);

    /**
     * @brief Dispatches FSR-RR denoiser converted inputs. Runs before upscaler.
     */
    bool DispatchDenoiser(ID3D12GraphicsCommandList* InCommandList, const ffxDispatchDescDenoiser& dispatchDesc);
};