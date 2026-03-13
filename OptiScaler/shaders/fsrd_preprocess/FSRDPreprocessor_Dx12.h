#pragma once
#include "SysUtils.h"

#include <DirectXMath.h>
#include <cstdint>
#include <memory>
#include <string_view>

struct ID3D12Device;
struct ID3D12GraphicsCommandList;
struct ID3D12Resource;

struct ffxDispatchDescDenoiserInput1Signal;
struct ffxDispatchDescDenoiserInput2Signals;
struct ffxDispatchDescDenoiser;

/**
 * @brief Converts DLSS Ray Reconstruction inputs into the format expected by FSR Ray Regeneration,
 * and handles composition for FSR-RR outputs.
 */
class FSRDPreprocessor_Dx12
{
  public:

    enum class ConvFlags : uint32_t
    {
        None = 0,

        NonGammaAlbedo =        1 << 0, // If true, FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO should ALSO be set
        UseInfiniteFarPlane =   1 << 1, 
        IsRoughnessPacked =     1 << 2, // Roughness = InNormals.A - NVSDK_NGX_DLSS_Roughness_Mode_Packed (Init param)
        Mode2Signal =           1 << 3, // Enables mode 2 denoiser outputs with discrete diffuse and specular lighting
        IsRightHanded =         1 << 4,

        Debug =                 1 << 16, // Denoiser and upscaler bypassed for debug out if this is set
        DebugModeMask =         0xFF << 16,

        DebugOutRadiance =      Debug, // Default debug vis

        DebugInSpecHitDist =    1 << 17 | Debug,
        DebugInDepth =          2 << 17 | Debug,
        DebugInMotion =         3 << 17 | Debug,
        DebugInNormals =        4 << 17 | Debug,
        DebugInRoughness =      5 << 17 | Debug,
        DebugInDiffAlbedo =     6 << 17 | Debug,
        DebugInSpecAlbedo =     7 << 17 | Debug,

        DebugOutFusedAlbedo =   8 << 17 | Debug,
        DebugOutLinearDepth =   9 << 17 | Debug,
        DebugOutMotion =        10 << 17 | Debug,
        DebugOutNormals =       11 << 17 | Debug,
        DebugOutSpecAlbedo =    12 << 17 | Debug,
        DebugOutDiffAlbedo =    13 << 17 | Debug,

        DebugOutDepthDelta =    14 << 17 | Debug,
        DebugOutNormDotView =   15 << 17 | Debug,
        DebugOutMetalicty =     16 << 17 | Debug,

        DebugColorMask =        17 << 17 | Debug,
        DebugAlbedoError =      18 << 17 | Debug,
    };

    enum class CompFlags : uint32_t
    {
        None =                  0,
        RawSourceBlit =         1 << 0, // Bypass composition and write unmodified input
        ScaleSrc =              1 << 1, // Enable bilinear scaling to output
        Mode2Signal =           1 << 2,

        Debug =                 1 << 16,
        DebugModeMask =         0xFF << 16,

        DebugCorrelation =      1 << 17 | Debug,
        DebugSkipSignal =       2 << 17 | Debug,
        DebugDenoiserOutput =   3 << 17 | Debug,
        DebugSpecularColor =    4 << 17 | Debug,
        DebugDiffuseColor =     5 << 17 | Debug,
    };

    /**
     * @brief Constant buffer data passed to the conversion shader.
     */
    struct alignas(16) ConvConstants
    {
        DirectX::XMFLOAT4X4 InvViewMatrix; // DLSSD WorldToView^1 - Camera matrix
        DirectX::XMFLOAT4X4 InvProjMatrix;   // DLSSD ViewToClip^-1 - Projection
        DirectX::XMFLOAT4X4 InvViewProjMatrix;  // DLSSD (WorldToView x ViewToClip)^-1
        DirectX::XMFLOAT4X4 PrevViewMatrix; // DLSSD WorldToView from last frame

        DirectX::XMFLOAT2 RenderSize; // Resolution of inputs
        DirectX::XMFLOAT2 RenderSizeInv; // 1.0 / Resolution

        float NearPlane; // Near < Far - IsInverted flag accounts for inversion
        float FarPlane;  // Near < Far - IsInverted flag accounts for inversion

        uint32_t Flags; // Dynamic configuration flags. See: ConfigFlags
    };

    /**
     * @brief Input resources matching DLSS Ray Reconstruction / NGX parameter names.
     * All resources must be in readable state before dispatch.
     */
    union ConvInput
    {
        struct
        {
            ID3D12Resource* InColor; // RGB - NVSDK_NGX_Parameter_Color - HDR or SDR
            ID3D12Resource* InDepth; // R - NVSDK_NGX_Parameter_Depth - 24/32bits
            ID3D12Resource* InMotionVectors; // RG - NVSDK_NGX_Parameter_MotionVectors - RG16/RG32
            ID3D12Resource* InNormals; // RGB: Normals, A: Roughness (Optional) - NVSDK_NGX_Parameter_GBuffer_Normals - RGB16_FLOAT/RG32_FLOAT
            ID3D12Resource* InRoughness; // R - May be packed in normals. NVSDK_NGX_Parameter_GBuffer_Roughness
            ID3D12Resource* InSpecHitDist; // R - NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance - FP16/FP32
            ID3D12Resource* InDiffAlbedo; // RGB - NVSDK_NGX_Parameter_GBuffer_DiffuseAlbedo - RGBA32
            ID3D12Resource* InSpecAlbedo; // RGB - NVSDK_NGX_Parameter_GBuffer_SpecularAlbedo - RGBA32
            ID3D12Resource* InBiasMask; // R8 - NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask
        };

        ID3D12Resource* AsArray[9];
    };

    /**
     * @brief Configuration and external resources used for compositing denoiser output into final result.
     */
    struct CompositionDesc
    {
        DirectX::XMFLOAT4 DstTexSize; // XY = Tex Size - ZW = 1 / XY
        float CorrelationBias; // Controls the contribution of stable elements to the final image
        uint32_t Flags;

        ID3D12Resource* InColorBeforeParticles; // NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles (Optional)
        ID3D12Resource* DstTex; // Destination texture used for compositing denoiser result
    };

  public:

    FSRDPreprocessor_Dx12(std::string_view name, ID3D12Device* pDev, bool isMode2);

    ~FSRDPreprocessor_Dx12();

    /**
     * @brief Indicates whether the converter has been successfully initialized.
     */
    bool IsInit() const;

    /**
     * @brief Returns the name of the shader instance
     */
    std::string_view GetName() const;

    /**
     * @brief (Re)allocates internal resources to match the specified render resolution.
     * Must be called at least once before any Dispatch().
     * @return True if resize succeeded
     */
    bool SetMaxRenderSize(uint32_t width, uint32_t height);

    /**
     * @brief Executes the input conversion shader.
     * Input resources must already be in shader-readable state.
     * Output resources are automatically transitioned to SRV state upon completion.
     *
     * @param inputs Input resource pointers
     * @param constants Per-frame constant buffer values
     * @return True if dispatch completed successfully
     */
    bool DispatchConversion(ID3D12GraphicsCommandList* cmdList, const ConvInput& inputs, const ConvConstants& constants);

    /**
     * @brief Configures input/output resources after input conversion for FSR-RR with Mode-1 fused inputs.
     * Resources are transitioned to SRV state and valid until the next conversion dispatch.
     * Must be re-acquired after each dispatch (lifetime managed internally).
     */
    void GetSignal(ffxDispatchDescDenoiserInput1Signal& signalDesc, ffxDispatchDescDenoiser& dispatchDesc) const;

    /**
     * @brief Configures input/output resources after input conversion for FSR-RR with Mode-2 discrete diffuse/specular color.
     * Resources are transitioned to SRV state and valid until the next conversion dispatch.
     * Must be re-acquired after each dispatch (lifetime managed internally).
     */
    void GetSignal(ffxDispatchDescDenoiserInput2Signals& signalDesc, ffxDispatchDescDenoiser& dispatchDesc) const;

    /**
     * @brief Composes the denoised radiance from FSR-RR with the skip signal previously generated 
     * by the converter, and writes the result to the given destination texture.
     */
    bool DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc);

    /**
     * @brief Copies the contents of the given source texture. Does not automatically set resource barriers.
     */
    bool Blit(ID3D12GraphicsCommandList* cmdList, ID3D12Resource* srcTex, ID3D12Resource* dstTex,
              DirectX::XMFLOAT2 dim = {}) const;

  private:
    struct Impl;

    std::unique_ptr<Impl> m_impl;
    std::string_view m_InstanceName;
    bool m_IsInitialized;
};
