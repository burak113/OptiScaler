#pragma once
#include "FSRDShaderUtils.h"

namespace FSRD
{
    namespace FloorSeed
    {
        constexpr UINT kPasses = 1;
        constexpr UINT kBackBufferCount = std::max(3 * (kPasses + 1), 1u);

        enum class Flags : uint32_t
        {
            None = 0,
            LinearDepth = (1 << 0),
            NegativeViewDepth = (1 << 1)
        };

        struct alignas(16) Constants
        {
            XMFLOAT4X4 InvProjMatrix;
            XMFLOAT4 RenderSize;

            float NearPlane;
            float FarPlane;

            uint32_t Flags;
            float _Padding[1];

            XMFLOAT2 CurrentJitter;
            float _JitterPadding[2];

            XMUINT4 InputBase; // XY: color origin, ZW: depth origin
        };

        static_assert(sizeof(Constants) == 128,
                      "FSRD floor-seed constant-buffer layout must match HLSL");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor;
                ID3D12Resource* InNormals;
                ID3D12Resource* InDepth;
            };

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ID3D12Resource* AsArray[kCount];
        };

        union Output
        {
            struct Data
            {
                ID3D12Resource* OutColor;
                ID3D12Resource* OutLinearDepth;
                ID3D12Resource* OutDepthGradient;
            };

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ID3D12Resource* AsArray[kCount];
        };
    }

    namespace FloorFilter
    {
        constexpr UINT kPasses = 5;
        constexpr UINT kBackBufferCount = std::max(3 * (kPasses + 1), 1u);

        enum class Flags : uint32_t
        {
            None = 0,
        };

        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;

            float RcpCrossBlNorm;
            float RcpSelfBlNorm;

            int32_t StepSize;
            uint32_t FrameIndex;

            uint32_t Flags;
            float _Padding[3];
        };

        static_assert(sizeof(Constants) == 48,
                      "FSRD floor-filter constant-buffer layout must match HLSL");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor;
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InDepthGradient;
            };

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ID3D12Resource* AsArray[kCount];
        };

        union Output
        {
            struct Data
            {
                ID3D12Resource* OutColor;
            };

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ID3D12Resource* AsArray[kCount];
        };
    }

    namespace Conversion
    {
        constexpr UINT kBackBufferCount = 3;

        struct SignalResources
        {
            ComPtr<ID3D12Resource> IndirectSpecular; // RGB: demodulated indirect specular, A: hit distance
            ComPtr<ID3D12Resource> DirectDiffuse;    // RGB: demodulated direct diffuse
        };

        /**
         * @brief Constant buffer data passed to the conversion shader.
         */
        struct alignas(16) Constants
        {
            XMFLOAT4X4 InvViewMatrix;  // DLSSD WorldToView^1 - Camera matrix
            XMFLOAT4X4 InvProjMatrix;  // DLSSD ViewToClip^-1 - Projection
            XMFLOAT4X4 PrevViewMatrix; // DLSSD WorldToView from last frame

            XMFLOAT4 RenderSize;
            XMFLOAT4 MotionInputSize;
            XMFLOAT4 MotionTransform;
            XMFLOAT4 JitterOffsets;

            XMUINT4 InputBase0;
            XMUINT4 InputBase1;
            XMUINT4 InputBase2;
            XMUINT4 InputBase3;
            XMUINT4 InputBase4;
            XMUINT4 InputBase5; // XY: reserved, ZW: specular hit-distance source

            float NearPlane; // Near < Far - IsInverted flag accounts for inversion
            float FarPlane;  // Near < Far - IsInverted flag accounts for inversion

            float FloorIsolation;
            float RoughnessFloor; // Minimum linear roughness supplied to RR; zero disables the adjustment

            uint32_t Flags;  // Dynamic configuration flags. See: ConfigFlags
            uint32_t InspectorChannel;
            float InspectorScale;

            // Full-scale view depth for the linear depth debug view. Adjustable so
            // the reading is a controllable measurement rather than a fixed encoding
            // against a far plane that may itself be wrong.
            float DebugDepthMax;

            // How to read InDiffuseHitDistance. 0 = absent, so the signal keeps the
            // FP16-max "ray miss" sentinel; 1 = scalar in R; 2 = combined
            // ray-direction resource with the distance in A.
            uint32_t DiffuseHitDistanceMode;

            // Blends the handover between FloorSeed's isotropic floor (0) and the
            // selected detail filter (1).
            float ZeroRoughDetail;

            // Which detail filter that blend targets.
            // 0 = hybrid median, 1 = structure-tensor steered.
            uint32_t ZeroRoughDetailMode;
            float _Padding0;
        };

        static_assert(sizeof(Constants) == 400, "FSRD conversion constant-buffer layout must match HLSL");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor;         // RGB - NVSDK_NGX_Parameter_Color - HDR or SDR
                ID3D12Resource* InDepth;         // R - NVSDK_NGX_Parameter_Depth - 24/32bits
                ID3D12Resource* InMotionVectors; // RG - NVSDK_NGX_Parameter_MotionVectors - RG16/RG32
                ID3D12Resource* InNormals; // RGB: Normals, A: Roughness (Optional) - NVSDK_NGX_Parameter_GBuffer_Normals - RGB16_FLOAT/RG32_FLOAT
                ID3D12Resource* InRoughness;   // R - May be packed in normals. NVSDK_NGX_Parameter_GBuffer_Roughness
                ID3D12Resource* InSpecHitDist; // R - NVSDK_NGX_Parameter_DLSSD_SpecularHitDistance - FP16/FP32
                ID3D12Resource* InDiffAlbedo;  // RGB - NVSDK_NGX_Parameter_GBuffer_DiffuseAlbedo - RGBA32
                ID3D12Resource* InSpecAlbedo;  // RGB - NVSDK_NGX_Parameter_GBuffer_SpecularAlbedo - RGBA32
                ID3D12Resource* InBiasMask;    // R8 - NVSDK_NGX_Parameter_DLSS_Input_Bias_Current_Color_Mask

                ID3D12Resource* InBlurColor;
                ID3D12Resource* InEdgeGuide;
                ID3D12Resource* InEmissive;
                ID3D12Resource* InSpecularRayDirectionHitDistance; // t12
                ID3D12Resource* InDiffuseHitDistance;              // t13
            };

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ID3D12Resource* AsArray[kCount];
        };

        /**
         * @brief Output resources formatted for direct consumption by FSR Ray Regeneration.
         * All resources are automatically transitioned to SRV state after dispatch.
         */
        union Output
        {
            struct Data
            {
                SignalResources Signals;

                // RG: unjittered PreviousUV-CurrentUV, B: corresponding-surface depth delta.
                ComPtr<ID3D12Resource> Motion;
                ComPtr<ID3D12Resource> Normals; // RG: Octahedrally encoded normals, B: Linear Roughness, A: Material Type (Optional) - RGB10A2_UNORM
                ComPtr<ID3D12Resource> SpecAlbedo; // RGB: Specular Albedo, A: saturate(dot(Normal, ViewDir)) - RGBA8_UNORM
                ComPtr<ID3D12Resource> DiffAlbedo; // RGB: Diffuse Albedo, A: Metalness (heuristic approximate) - RGBA8_UNORM

                ComPtr<ID3D12Resource> SkipSignal;

                // RGB: the finished handover image for this pixel, A: how much of it
                // composition should mix over the RR result. Zero alpha everywhere in
                // input-blend mode, so composition needs no mode of its own.
                ComPtr<ID3D12Resource> Handover;

                Data() {}
                ~Data() {}
            };

            Output()
            {
                for (auto& resource : AsArray)
                    resource = ComPtr<ID3D12Resource>();
            }

            ~Output()
            {
                for (auto& resource : AsArray)
                    resource.~ComPtr();
            }

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ComPtr<ID3D12Resource> AsArray[kCount];

            ID3D12Resource* AsRawArray[kCount];
        };
    }

    namespace Composition
    {
        constexpr UINT kBackBufferCount = 9;
        constexpr UINT kOutputCount = 1;

        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize; // XY = Tex Size - ZW = 1 / XY
            XMUINT4 SourceBase; // XY = raw color origin, ZW = color-before-particles origin

            float CorrelationBias; // Controls the contribution of stable elements to the final image
            uint32_t Flags;

            XMFLOAT2 SourceUvScale; // Logical source extent / physical source allocation
            XMFLOAT2 SourceUvOffset; // Logical source origin / physical source allocation

            // Handover refinements, each disabled at zero. They modify the handover image or
            // its weight rather than the frequency split that combines it with RR.
            //
            // Standard deviations of RR's local distribution the handover may deviate
            // by. A purely spatial filter has no temporal stability of its own, so
            // this lends it RR's without lending it RR's blur.
            float ZeroRoughAnchorClamp;
            // How far the mix weight follows per-pixel agreement between the two
            // paths instead of the flat handover weight.
            float ZeroRoughCorrelationMix;
            float _Padding0[2];
        };

        static_assert(sizeof(Constants) == 80, "FSRD composition constant-buffer layout must match HLSL");

        /**
         * @brief Resources used for composition after denoising
         */
        union Input
        {
            struct Data
            {
                ID3D12Resource* InIndirectSpecular;
                ID3D12Resource* InSpecularAlbedo;

                ID3D12Resource* InDirectDiffuse;
                ID3D12Resource* InDiffuseAlbedo;

                ID3D12Resource* InSkipSignal;
                ID3D12Resource* InRawColor;
                ID3D12Resource* InColorBeforeParticles; // NVSDK_NGX_Parameter_DLSSD_ColorBeforeParticles
                ID3D12Resource* InRawIndirectSpecular;
                ID3D12Resource* InNormals;
                ID3D12Resource* InHandover; // RGB: handover image, A: mix weight
            };

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ID3D12Resource* AsArray[kCount];
        };
    }

    // Each shader declares its descriptor-table sizes as a literal inside its
    // "MainRS" root-signature string, and nothing else compares those literals to
    // these structs. ComputeState sizes its heap from kCount, so if a resource is
    // added here without editing the matching HLSL literal the two drift apart with
    // no diagnostic: the table overruns and descriptors land in the wrong range.
    // These assertions are the missing third leg of that contract - update the
    // numDescriptors literal in the named shader whenever one of them fires.
    static_assert(FloorSeed::Input::kCount == 3, "FSRDFloorSeed MainRS SRV count");
    static_assert(FloorSeed::Output::kCount == 3, "FSRDFloorSeed MainRS UAV count");
    static_assert(FloorFilter::Input::kCount == 3, "FSRDFloor MainRS SRV count");
    static_assert(FloorFilter::Output::kCount == 1, "FSRDFloor MainRS UAV count");
    static_assert(Conversion::Input::kCount == 14, "FSRDInputConv MainRS SRV count");
    static_assert(Conversion::Output::kCount == 8, "FSRDInputConv MainRS UAV count");
    static_assert(Composition::Input::kCount == 10, "FSRDOutputComp MainRS SRV count");
    static_assert(Composition::kOutputCount == 1, "FSRDOutputComp MainRS UAV count");
}
