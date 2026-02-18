#pragma once
#include "SysUtils.h"

#include <DirectXMath.h>
#include <cstdint>
#include <memory>
#include <string_view>

struct ID3D12Device;
struct ID3D12GraphicsCommandList;
struct ID3D12Resource;

/**
 * @brief Converts DLSS Ray Reconstruction inputs into the format expected by FSR Ray Regeneration.
 * Manages shader compilation, resource allocation, format conversion, and state transitions.
 */
class FSRDInputConv_Dx12
{
  public:

    /**
     * @brief Constant buffer data passed to the conversion shader.
     */
    struct alignas(16) Constants
    {
        DirectX::XMFLOAT4X4 InvViewMatrix; // DLSSD WorldToView^1 - Camera matrix
        DirectX::XMFLOAT4X4 InvProjMatrix;   // DLSSD ViewToClip^-1 - Projection
        DirectX::XMFLOAT4X4 InvViewProjMatrix;  // DLSSD (WorldToView x ViewToClip)^-1
        DirectX::XMFLOAT4X4 PrevViewMatrix; // DLSSD WorldToView from last frame

        DirectX::XMFLOAT2 RenderSize; // Resolution of inputs
        DirectX::XMFLOAT2 RenderSizeInv; // 1.0 / Resolution

        float UseSqrtEncodingOnSecondaries; // If true, FFX_DENOISER_DISPATCH_NON_GAMMA_ALBEDO should NOT be set
        float NearPlane; // Near < Far - IsInverted flag accounts for inversion
        float FarPlane;  // Near < Far - IsInverted flag accounts for inversion
        float UseInfiniteFarPlane;

        float IsRoughnessPacked; // Roughness = InNormals.A - NVSDK_NGX_DLSS_Roughness_Mode_Packed (Init param)
    };

    /**
     * @brief Input resources matching DLSS Ray Reconstruction / NGX parameter names.
     * All resources must be in readable state before dispatch.
     */
    union InputResources
    {
        struct
        {
            ID3D12Resource* InColor;         // RGB - NVSDK_NGX_Parameter_Color - HDR or SDR
            ID3D12Resource* InDepth;         // R - NVSDK_NGX_Parameter_Depth - 24/32bits
            ID3D12Resource* InMotionVectors; // RG - NVSDK_NGX_Parameter_MotionVectors - RG16/RG32
            ID3D12Resource* InNormals; // RGB: Normals, A: Roughness (Optional) - NVSDK_NGX_Parameter_GBuffer_Normals - RG16_FLOAT/RG32_FLOAT
            ID3D12Resource* InRoughness;      // R - May be packed in normals. NVSDK_NGX_Parameter_GBuffer_Roughness
            ID3D12Resource* InSpecHitDist;    // R - NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance - FP16/FP32
            ID3D12Resource* InDiffAlbedo;  // RGB - NVSDK_NGX_Parameter_GBuffer_DiffuseAlbedo - RGBA32
            ID3D12Resource* InSpecAlbedo; // RGB - NVSDK_NGX_Parameter_GBuffer_SpecularAlbedo - RGBA32
        };

        ID3D12Resource* AsArray[8];
    };

    /**
     * @brief Output resources formatted for direct consumption by FSR Ray Regeneration.
     * All resources are automatically transitioned to SRV state after dispatch.
     */
    union OutputResources
    {
        struct
        {
            // ffxDispatchDescDenoiserInput1Signal
            ID3D12Resource* OutRadiance;    // RGB: Combined noisy color A: Specular Ray Length - RGBA16_FLOAT
            ID3D12Resource* OutFusedAlbedo; // RGB: max(specularAlbedo, diffuseAlbedo) A: NoV - RGBA8_UNORM

            // ffxDispatchDescDenoiser
            ID3D12Resource* OutMotion;  // RG: Standard TSR motion vectors, B: Linear Depth Delta (CurrentLinearDepth - PrevLinearDepth) - RGBA16_FLOAT
            ID3D12Resource* OutNormals; // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional) - RGB10A2_UNORM
            ID3D12Resource* OutSpecAlbedo;  // RGB: Specular Albedo, A: saturate(dot(Normal, ViewDir)) - RGBA8_UNORM
            ID3D12Resource* OutDiffAlbedo;  // RGB: Diffuse Albedo, A: Metalness (heuristic approximate) - RGBA8_UNORM
            ID3D12Resource* OutLinearDepth; // R - R32_FLOAT
        };

        ID3D12Resource* AsArray[7];
    };

  public:

    FSRDInputConv_Dx12(std::string_view name, ID3D12Device* pDev);

    ~FSRDInputConv_Dx12();

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
    bool Dispatch(ID3D12GraphicsCommandList* cmdList, const InputResources& inputs, const Constants& constants);

    /**
     * @brief Returns output resources for FSR-RR after dispatch.
     * Resources are transitioned to SRV state and valid until the next dispatch.
     * Must be re-acquired after each dispatch (lifetime managed internally).
     */
    OutputResources GetOutputs() const;

  private:
    struct Impl;

    std::unique_ptr<Impl> m_impl;
    std::string_view m_InstanceName;
    bool m_IsInitialized;

    FSRDInputConv_Dx12(std::string_view name, ID3D12Device* pDev, std::string_view hlslSrc);
};