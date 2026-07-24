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

    struct DenoiserConfiguration
    {
        static constexpr uint32_t kScalarCount = FFX_API_CONFIGURE_DENOISER_KEY_DISOCCLUSION_THRESHOLD;
        static constexpr uint32_t kKeyCount = FFX_API_CONFIGURE_DENOISER_KEY_DEBUG_VIEW_LINEAR_DEPTH_BOUNDS;

        // Ordered by FfxApiConfigureDenoiserKey
        union
        {
            struct
            {
                float m_CrossBilateralNormalStrength;
                float m_StabilityBias;
                float m_MaxRadiance;
                float m_RadianceClipStdK;
                float m_GaussianKernelRelaxation;
                float m_DisocclusionThreshold;
            };

            float ScalarValues[kScalarCount];
        };

        FfxApiFloatBounds m_DebugViewLinearDepthBounds;

        static FfxApiConfigureDenoiserKey GetIndexKey(int index)
        {
            index = std::clamp(index + 1, 1, static_cast<int>(kKeyCount));
            return static_cast<FfxApiConfigureDenoiserKey>(index);
        }

        void* GetData(FfxApiConfigureDenoiserKey key)
        {
            if (key == FFX_API_CONFIGURE_DENOISER_KEY_DEBUG_VIEW_LINEAR_DEPTH_BOUNDS)
                return &m_DebugViewLinearDepthBounds;

            const int index = static_cast<int>(key) - 1;
            return index >= 0 && index < static_cast<int>(kScalarCount)
                ? &ScalarValues[index]
                : nullptr;
        }
    };

    ffxContext _pDenoiserCtx;
    ffxCreateContextDescDenoiser _denoiserCtxDesc;
    DenoiserConfiguration _denoiserSettings;
    ffxStructType_t _diffuseSignalDescType = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DIRECT_DIFFUSE;
    ffxStructType_t _specularSignalDescType = FFX_API_DISPATCH_DESC_TYPE_DENOISER_INDIRECT_SPECULAR;

    static bool s_isHWDepth;
    static bool s_isRoughnessPacked;

    FSRDConvDesc _convDesc;
    // Diagnostic-only DLSS-RR probes. These are not bound to the converter or RR dispatch yet.
    ID3D12Resource* _diffuseHitDistanceProbe = nullptr;
    ID3D12Resource* _diffuseRayDirectionHitDistanceProbe = nullptr;
    uint32_t _diffuseHitDistanceBaseX = 0;
    uint32_t _diffuseHitDistanceBaseY = 0;
    uint32_t _diffuseRayDirectionHitDistanceBaseX = 0;
    uint32_t _diffuseRayDirectionHitDistanceBaseY = 0;
    DirectX::XMFLOAT3 _lastCamPos {}; // Last successfully dispatched world-space camera position
    float _appliedRoughnessFloor = -1.0f;
    float _appliedRoughnessFloorDistance = -1.0f;
    bool _hasDenoiserHistory = false;
    bool _viewFromStreamline = false;
    bool _projectionFromStreamline = false;
    bool _logNextDenoiserDispatch = true;
    bool _lastDispatchRequestedReset = false;
    uint64_t _denoiserDispatchAttempts = 0;
    uint64_t _denoiserDispatchSuccesses = 0;
    uint64_t _denoiserDispatchFailures = 0;

    // Matrices
    // Row-major storage with column-vector multiplication semantics.
    DirectX::XMMATRIX _invViewMatrix;   // Camera rotation and translation
    DirectX::XMMATRIX _viewMatrix;      // World to camera space
    DirectX::XMMATRIX _prevViewMatrix;  // Last world to camera space
    DirectX::XMMATRIX _projMatrix;      // Unjittered perspective projection
    bool _isRightHanded;                // True if the camera matrix is right handed

    std::unique_ptr<FSRDPreprocessor_Dx12> FSRDConvShader;

    bool InitFSR3(const NVSDK_NGX_Parameter* InParameters) override;

    bool CreateDenoiserContext();

    bool QueryDenoiserVersions();

    void DestroyDenoiserContext();

    bool UpdateSize();

    /**
     * @brief Generates FFX denoiser configuration and input buffers from DLSS-RR inputs and NGX configurations.
     * Converts and repacks resources internally.
     */
    bool PrepareDenoiserInput(ID3D12GraphicsCommandList* InCommandList, const NVSDK_NGX_Parameter& ngxParams,
                              ffxDispatchDescDenoiser& dispatchDesc,
                              ffxDispatchDescDenoiserDirectDiffuse& directDiffuse,
                              ffxDispatchDescDenoiserIndirectSpecular& indirectSpecular);

    /**
     * @brief Retrieves DLSS-RR inputs to populate the inputs for the interop layer in order to generate
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

    void CommitDenoiserHistory() noexcept;

    void InvalidateDenoiserHistory() noexcept
    {
        _hasDenoiserHistory = false;
        _lastDispatchRequestedReset = false;
    }

    bool SetDefaultConfiguration();

    ffxReturnCode_t SetDefaultConfiguration(FfxApiConfigureDenoiserKey key);

    ffxReturnCode_t ApplyConfiguration(FfxApiConfigureDenoiserKey key);
};
