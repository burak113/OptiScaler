#pragma once
#include "FSRDShaderUtils.h"

#include <cstddef>

namespace FSRD
{
    namespace FloorSeed
    {
        constexpr UINT kBackBufferCount = 3;

        enum class Flags : uint32_t
        {
            None = 0,
            LinearDepth = (1 << 0),
            NegativeViewDepth = (1 << 1),
            // The title publishes its own linearised view depth: InTitleLinearDepth is
            // the source the canonical signed output is derived from.
            TitleLinearDepth = (1 << 2)
        };

        struct alignas(16) Constants
        {
            XMFLOAT4X4 InvProjMatrix;
            XMFLOAT4 RenderSize;
            float NearPlane;
            float FarPlane;
            uint32_t Flags;
            float _Padding;
            XMFLOAT2 CurrentJitter;
            XMFLOAT2 _JitterPadding;
            XMUINT4 InputBase;
            XMUINT2 NormalBase;
            XMFLOAT2 _NormalPadding;
            XMUINT2 TitleDepthBase;
            XMFLOAT2 _TitleDepthPadding;
            XMUINT2 AlbedoBase;
            float NoiseSuppression;
            uint32_t FloorEnabled;
        };

        static_assert(offsetof(Constants, InvProjMatrix) == 0, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, RenderSize) == 64, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, NearPlane) == 80, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, FarPlane) == 84, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, Flags) == 88, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, CurrentJitter) == 96, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, InputBase) == 112, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, NormalBase) == 128, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, TitleDepthBase) == 144, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, AlbedoBase) == 160, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, NoiseSuppression) == 168, "FSRDFloorSeed layout");
        static_assert(offsetof(Constants, FloorEnabled) == 172, "FSRDFloorSeed layout");
        static_assert(sizeof(Constants) == 176, "FSRDFloorSeed constant-buffer layout");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor;
                ID3D12Resource* InNormals;
                ID3D12Resource* InDepth;
                // Optional: bound for every dispatch, read only when Flags carries
                // TitleLinearDepth.
                ID3D12Resource* InTitleLinearDepth;
                ID3D12Resource* InDiffAlbedo;
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
                ID3D12Resource* OutDetailReference;
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

        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            int32_t StepSize;
            float NoiseSuppression;
            XMUINT2 AlbedoBase;
        };

        static_assert(offsetof(Constants, DstTexSize) == 0, "FSRDFloor layout");
        static_assert(offsetof(Constants, StepSize) == 16, "FSRDFloor layout");
        static_assert(offsetof(Constants, NoiseSuppression) == 20, "FSRDFloor layout");
        static_assert(offsetof(Constants, AlbedoBase) == 24, "FSRDFloor layout");
        static_assert(sizeof(Constants) == 32, "FSRDFloor constant-buffer layout");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor;
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InDepthGradient; // RG: depth gradient, BA: octahedral normal
                ID3D12Resource* InDiffAlbedo;    // material guide - see FloorSurfaceWeight
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
            XMFLOAT4X4 InvViewMatrix;
            XMFLOAT4X4 InvProjMatrix;
            XMFLOAT4X4 PrevViewMatrix;
            XMFLOAT4 DstTexSize;
            XMFLOAT4 MotionInputSize;
            XMFLOAT4 MotionTransform;
            XMFLOAT4 JitterOffsets;
            XMUINT4 InputBase0;
            XMUINT4 InputBase1;
            XMUINT4 InputBase2;
            XMUINT4 InputBase3;
            XMUINT4 InputBase4;
            XMUINT4 InputBase5;
            float NearPlane;
            float FarPlane;
            float FloorDetailPreservation;
            uint32_t Flags;
            uint32_t InspectorChannel;
            float InspectorScale;
            float DebugDepthMax;
            uint32_t DiffuseHitDistanceMode;
            float ResponsivityTrustThreshold;
            uint32_t ResponsivityInvert;
            float BiasMaskStrength;
            float DemodDivisorFloor;
            float _Padding0;
            float _Padding1;
            float _Padding2;
        };

        static_assert(offsetof(Constants, InvViewMatrix) == 0, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InvProjMatrix) == 64, "FSRDInputConv layout");
        static_assert(offsetof(Constants, PrevViewMatrix) == 128, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DstTexSize) == 192, "FSRDInputConv layout");
        static_assert(offsetof(Constants, MotionInputSize) == 208, "FSRDInputConv layout");
        static_assert(offsetof(Constants, MotionTransform) == 224, "FSRDInputConv layout");
        static_assert(offsetof(Constants, JitterOffsets) == 240, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InputBase0) == 256, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InputBase1) == 272, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InputBase2) == 288, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InputBase3) == 304, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InputBase4) == 320, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InputBase5) == 336, "FSRDInputConv layout");
        static_assert(offsetof(Constants, NearPlane) == 352, "FSRDInputConv layout");
        static_assert(offsetof(Constants, FarPlane) == 356, "FSRDInputConv layout");
        static_assert(offsetof(Constants, FloorDetailPreservation) == 360, "FSRDInputConv layout");
        static_assert(offsetof(Constants, Flags) == 364, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InspectorChannel) == 368, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InspectorScale) == 372, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DebugDepthMax) == 376, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DiffuseHitDistanceMode) == 380, "FSRDInputConv layout");
        static_assert(offsetof(Constants, ResponsivityTrustThreshold) == 384, "FSRDInputConv layout");
        static_assert(offsetof(Constants, ResponsivityInvert) == 388, "FSRDInputConv layout");
        static_assert(offsetof(Constants, BiasMaskStrength) == 392, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DemodDivisorFloor) == 396, "FSRDInputConv layout");
        static_assert(sizeof(Constants) == 416, "FSRDInputConv constant-buffer layout");

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

                // The floor this pipeline built for the frame, not a title resource: the
                // shader reads it as a guide and never as an input to denoise.
                ID3D12Resource* InFloorColor;
                // The resource-inspector view, likewise ours rather than the title's.
                ID3D12Resource* InInspector;
                ID3D12Resource* InEmissive;  // t11
                ID3D12Resource* InSpecularRayDirectionHitDistance; // t12
                ID3D12Resource* InDiffuseHitDistance;              // t13
                ID3D12Resource* InTitleLinearDepth;                 // t14
                ID3D12Resource* InResponsivityMask;
                ID3D12Resource* InDetailReference;                 // t16
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

                // RGB: cleaned reference. A: sigma, or -1 for explicitly bypassed content.
                ComPtr<ID3D12Resource> DetailReference;

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
            XMFLOAT4 DstTexSize;
            uint32_t Flags;
            float DetailPreservation;
            float NoiseSuppression;
            float FloorHandoverAnchorClamp;
            XMFLOAT2 SourceUvScale;
            XMFLOAT2 SourceUvOffset;
            float FloorHandoverCorrelationMix;
            XMFLOAT3 _Padding0;
        };

        static_assert(offsetof(Constants, DstTexSize) == 0, "FSRDOutputComp layout");
        static_assert(offsetof(Constants, Flags) == 16, "FSRDOutputComp layout");
        static_assert(offsetof(Constants, DetailPreservation) == 20, "FSRDOutputComp layout");
        static_assert(offsetof(Constants, NoiseSuppression) == 24, "FSRDOutputComp layout");
        static_assert(offsetof(Constants, SourceUvScale) == 32, "FSRDOutputComp layout");
        static_assert(offsetof(Constants, SourceUvOffset) == 40, "FSRDOutputComp layout");
        static_assert(offsetof(Constants, FloorHandoverAnchorClamp) == 28, "FSRDOutputComp layout");
        static_assert(offsetof(Constants, FloorHandoverCorrelationMix) == 48, "FSRDOutputComp layout");
        static_assert(sizeof(Constants) == 64, "FSRDOutputComp constant-buffer layout");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InIndirectSpecular;
                ID3D12Resource* InSpecularAlbedo;

                ID3D12Resource* InDirectDiffuse;
                ID3D12Resource* InDiffuseAlbedo;

                ID3D12Resource* InSkipSignal;
                ID3D12Resource* InNormals;
                ID3D12Resource* InDetailReference;
                ID3D12Resource* InLinearDepth;
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
    static_assert(FloorSeed::Input::kCount == 5, "FSRDFloorSeed MainRS SRV count");
    static_assert(FloorSeed::Output::kCount == 4, "FSRDFloorSeed MainRS UAV count");
    static_assert(FloorFilter::Input::kCount == 4, "FSRDFloor MainRS SRV count");
    static_assert(FloorFilter::Output::kCount == 1, "FSRDFloor MainRS UAV count");
    static_assert(Conversion::Input::kCount == 17, "FSRDInputConv MainRS SRV count");
    static_assert(Conversion::Output::kCount == 8, "FSRDInputConv MainRS UAV count");
    static_assert(Composition::Input::kCount == 8, "FSRDOutputComp MainRS SRV count");
    static_assert(Composition::kOutputCount == 1, "FSRDOutputComp MainRS UAV count");
}
