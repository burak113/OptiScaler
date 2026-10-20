#pragma once
#include "FSRDShaderUtils.h"

#include <cstddef>

namespace FSRD
{
    namespace FogStats
    {
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            XMFLOAT2 TileSize;
            float Rate;
            float DivisorFloor;
            float DepthTolerance;
            uint32_t Flags;
            XMFLOAT2 HistoryJitterDelta;
            float GuideRate;
            float GuideDepthTolerance;
            float LogZMin;
            float InvLogZRange;
        };
        static_assert(sizeof(Constants) == 64, "FogStats constants");
        static_assert(offsetof(Constants, DstTexSize) == 0, "FogStats layout");
        static_assert(offsetof(Constants, TileSize) == 16, "FogStats layout");
        static_assert(offsetof(Constants, Rate) == 24, "FogStats layout");
        static_assert(offsetof(Constants, DivisorFloor) == 28, "FogStats layout");
        static_assert(offsetof(Constants, DepthTolerance) == 32, "FogStats layout");
        static_assert(offsetof(Constants, Flags) == 36, "FogStats layout");
        static_assert(offsetof(Constants, HistoryJitterDelta) == 40, "FogStats layout");
        static_assert(offsetof(Constants, GuideRate) == 48, "FogStats layout");
        static_assert(offsetof(Constants, InvLogZRange) == 60, "FogStats layout");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InOrigSpecAlbedo;
                ID3D12Resource* InOrigDiffAlbedo;
                ID3D12Resource* InOrigSpecSignal;
                ID3D12Resource* InOrigDiffSignal;
                ID3D12Resource* InCurSpecAlbedo;
                ID3D12Resource* InCurDiffAlbedo;
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InMotion;
                ID3D12Resource* InPrevA;
                ID3D12Resource* InPrevB;
                ID3D12Resource* InPrevC;
                ID3D12Resource* InPrevGuides;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutA;
                ID3D12Resource* OutB;
                ID3D12Resource* OutC;
                ID3D12Resource* OutG;
                ID3D12Resource* OutH;
                ID3D12Resource* OutGuides;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(FogStats::Input::kCount == 12, "FogStats input count");
    static_assert(FogStats::Output::kCount == 6, "FogStats output count");

    namespace FogKappa
    {
        struct alignas(16) Constants
        {
            XMFLOAT2 TileSize;
            float Tau;
            float Z;
            float TauFill;
            float ZFill;
            float MassLocal;
            float MassFill;
            float Sig0;
            float Sig1;
            float FillSigma;
            float FillZSigma;
            int32_t FillRadius;
            XMFLOAT3 _Reserved0;
        };
        static_assert(sizeof(Constants) == 64, "FogKappa constants");
        static_assert(offsetof(Constants, FillRadius) == 48, "FogKappa layout");
        static_assert(offsetof(Constants, _Reserved0) == 52, "FogKappa layout");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InA;
                ID3D12Resource* InB;
                ID3D12Resource* InC;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutKappa;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(FogKappa::Input::kCount == 3, "FogKappa input count");
    static_assert(FogKappa::Output::kCount == 1, "FogKappa output count");

    namespace FogRank
    {
        struct alignas(16) Constants
        {
            XMFLOAT2 TileSize;
            float ZTolerance;
            float Percentile;
            int32_t Radius;
            XMFLOAT3 _Reserved0;
        };
        static_assert(sizeof(Constants) == 32, "FogRank constants");
        static_assert(offsetof(Constants, Percentile) == 12, "FogRank layout");
        static_assert(offsetof(Constants, Radius) == 16, "FogRank layout");
        static_assert(offsetof(Constants, _Reserved0) == 20, "FogRank layout");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InKappa;
                ID3D12Resource* InA;
                ID3D12Resource* InC;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutKappa;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(FogRank::Input::kCount == 3, "FogRank input count");
    static_assert(FogRank::Output::kCount == 1, "FogRank output count");

    namespace FogSmooth
    {
        struct alignas(16) Constants
        {
            XMFLOAT2 TileSize;
            float Sigma;
            float ZSigma;
            int32_t Radius;
            XMFLOAT3 _Reserved0;
        };
        static_assert(sizeof(Constants) == 32, "FogSmooth constants");
        static_assert(offsetof(Constants, Radius) == 16, "FogSmooth layout");
        static_assert(offsetof(Constants, _Reserved0) == 20, "FogSmooth layout");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InKappa;
                ID3D12Resource* InA;
                ID3D12Resource* InC;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutKappa;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(FogSmooth::Input::kCount == 3, "FogSmooth input count");
    static_assert(FogSmooth::Output::kCount == 1, "FogSmooth output count");

    namespace FogTarget
    {
        struct alignas(16) Constants
        {
            XMFLOAT2 TileSize;
            float Sigma;
            float ZSigma;
            int32_t Radius;
            XMFLOAT3 _Reserved0;
        };
        static_assert(sizeof(Constants) == 32, "FogTarget constants");
        static_assert(offsetof(Constants, Radius) == 16, "FogTarget layout");
        static_assert(offsetof(Constants, _Reserved0) == 20, "FogTarget layout");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InKappa;
                ID3D12Resource* InG;
                ID3D12Resource* InH;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutTargetSpec;
                ID3D12Resource* OutTargetDiff;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(FogTarget::Input::kCount == 3, "FogTarget input count");
    static_assert(FogTarget::Output::kCount == 2, "FogTarget output count");

    namespace FogRoute
    {
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            XMFLOAT2 TileSize;
            float DivisorFloor;
            float LogNear;
            float InvLogRange;
            float _Reserved1;
            uint32_t Flags;
            float _Reserved0;
        };
        static_assert(sizeof(Constants) == 48, "FogRoute constants");
        static_assert(offsetof(Constants, DivisorFloor) == 24, "FogRoute layout");
        static_assert(offsetof(Constants, Flags) == 40, "FogRoute layout");
        static_assert(offsetof(Constants, _Reserved0) == 44, "FogRoute layout");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InSpecAlbedo;
                ID3D12Resource* InDiffAlbedo;
                ID3D12Resource* InSpecSignal;
                ID3D12Resource* InDiffSignal;
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InKappa;
                ID3D12Resource* InTargetSpec;
                ID3D12Resource* InTargetDiff;
                ID3D12Resource* InGuides;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutSpecAlbedo;
                ID3D12Resource* OutDiffAlbedo;
                ID3D12Resource* OutSpecSignal;
                ID3D12Resource* OutDiffSignal;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(FogRoute::Input::kCount == 9, "FogRoute input count");
    static_assert(FogRoute::Output::kCount == 4, "FogRoute output count");

    // RR's motion vectors: canonical motion plus the jitter difference (FSRDRRMotion.hlsl).
    namespace RRMotion
    {
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            XMFLOAT2 JitterDeltaUv;
            XMFLOAT2 _Reserved0;
        };
        static_assert(sizeof(Constants) == 32, "RRMotion constants");
        static_assert(offsetof(Constants, JitterDeltaUv) == 16, "RRMotion layout");
        static_assert(offsetof(Constants, _Reserved0) == 24, "RRMotion layout");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InMotion;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutMotion;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(RRMotion::Input::kCount == 1, "RRMotion input count");
    static_assert(RRMotion::Output::kCount == 1, "RRMotion output count");

    // Recovery v2 lobe recovery (FSRDRecoveryLobe*.hlsl): per-lobe temporal reference, band pyramid of
    // reference - RR, gated bands collapsed and remodulated after composition. One constant layout for all
    // three passes.
    namespace RecoveryLobe
    {
        constexpr UINT kLevels = 6;      // bands 0..5; the pyramid holds levels 0..6
        constexpr UINT kBackBufferCount = 3;
        enum Flags : uint32_t
        {
            HistoryValid = 1u << 0,
            ExtraDiffuse = 1u << 1,
            NoSpecular = 1u << 2,
            Coarsest = 1u << 3,
            Final = 1u << 4,
        };
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            XMFLOAT4 LevelSize;
            XMFLOAT4 Strength;
            XMFLOAT2 Jitter; // this frame's jitter, render pixels; the references keep the jitter-free raster
            XMFLOAT2 Modulation;
            float Response;
            float Threshold;
            float MatureAge;
            uint32_t Flags;
            uint32_t Level;
            uint32_t FrameIndex;
            uint32_t Debug;
            float GradientAge; // frames before the sub-pixel gradient is fitted
            XMFLOAT4 Blend;    // X Mix, Y Anchor (specular / diffuse); ZW reserved
        };
        static_assert(sizeof(Constants) == 112, "RecoveryLobe constants");
        static_assert(offsetof(Constants, Blend) == 96, "RecoveryLobe layout");
        static_assert(offsetof(Constants, Jitter) == 48, "RecoveryLobe layout");
        static_assert(offsetof(Constants, Response) == 64, "RecoveryLobe layout");
        static_assert(offsetof(Constants, Level) == 80, "RecoveryLobe layout");
    }

    namespace RecoveryLobeAccumulate
    {
        union Input
        {
            struct Data
            {
                ID3D12Resource* InSpecularSignal;
                ID3D12Resource* InDiffuseSignal;
                ID3D12Resource* InSpecularDenoised;
                ID3D12Resource* InDiffuseDenoised;
                ID3D12Resource* InExtraDiffuseDenoised;
                ID3D12Resource* InSpecularAlbedo;
                ID3D12Resource* InDiffuseAlbedo;
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InNormals;
                ID3D12Resource* InMotion;
                ID3D12Resource* InSkipSignal;
                ID3D12Resource* InPrevSpecular;
                ID3D12Resource* InPrevDiffuse;
                ID3D12Resource* InPrevGeometry;
                ID3D12Resource* InPrevGradient;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutSpecular;
                ID3D12Resource* OutDiffuse;
                ID3D12Resource* OutGeometry;
                ID3D12Resource* OutLevelA;
                ID3D12Resource* OutLevelB;
                ID3D12Resource* OutLevelC;
                ID3D12Resource* OutGradient;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(RecoveryLobeAccumulate::Input::kCount == 15, "FSRDRecoveryLobeAccumulate MainRS SRV count");
    static_assert(RecoveryLobeAccumulate::Output::kCount == 7, "FSRDRecoveryLobeAccumulate MainRS UAV count");

    namespace RecoveryLobeDown
    {
        union Input
        {
            struct Data
            {
                ID3D12Resource* InLevelA;
                ID3D12Resource* InLevelB;
                ID3D12Resource* InLevelC;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutLevelA;
                ID3D12Resource* OutLevelB;
                ID3D12Resource* OutLevelC;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(RecoveryLobeDown::Input::kCount == 3, "FSRDRecoveryLobeDown MainRS SRV count");
    static_assert(RecoveryLobeDown::Output::kCount == 3, "FSRDRecoveryLobeDown MainRS UAV count");

    namespace RecoveryLobeBand
    {
        union Input
        {
            struct Data
            {
                ID3D12Resource* InLevelA;
                ID3D12Resource* InLevelB;
                ID3D12Resource* InLevelC;
                ID3D12Resource* InCoarseA;
                ID3D12Resource* InCoarseB;
                ID3D12Resource* InCoarseSpecular;
                ID3D12Resource* InCoarseDiffuse;
                ID3D12Resource* InPrevNoise;
                ID3D12Resource* InMotion;
                ID3D12Resource* InComposed;
                ID3D12Resource* InSpecularAlbedo;
                ID3D12Resource* InDiffuseAlbedo;
                ID3D12Resource* InSkipSignal;
                ID3D12Resource* InSpecularDenoised;
                ID3D12Resource* InDiffuseDenoised;
                ID3D12Resource* InExtraDiffuseDenoised;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutSpecular;
                ID3D12Resource* OutDiffuse;
                ID3D12Resource* OutNoise;
                ID3D12Resource* OutColor;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(RecoveryLobeBand::Input::kCount == 16,"FSRDRecoveryLobeBand MainRS SRV count");
    static_assert(RecoveryLobeBand::Output::kCount == 4, "FSRDRecoveryLobeBand MainRS UAV count");

    namespace Geometry
    {
        enum Flags : uint32_t { LinearDepth = 1, NegativeViewDepth = 2, TitleLinearDepth = 4 };
        struct alignas(16) Constants
        {
            XMFLOAT4X4 InvProjMatrix;
            XMFLOAT4 RenderSize;
            float NearPlane, FarPlane;
            uint32_t Flags, _Padding;
            XMFLOAT2 CurrentJitter;
            XMUINT2 DepthBase, TitleDepthBase, _Padding2;
        };
        static_assert(sizeof(Constants) == 128, "Geometry constants");
        static_assert(offsetof(Constants, CurrentJitter) == 96, "Geometry jitter");
        static_assert(offsetof(Constants, TitleDepthBase) == 112, "Geometry title depth");
        union Input
        {
            struct Data { ID3D12Resource* InDepth; ID3D12Resource* InTitleLinearDepth; };
            static constexpr uint32_t kCount = 2;
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data { ID3D12Resource* OutLinearDepth; };
            static constexpr uint32_t kCount = 1;
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }

    namespace FlatDetail
    {
        constexpr UINT kRefinementPasses = 1;
        constexpr UINT kTileSize = 8;
        constexpr UINT kRadius = 3;
        constexpr float kNoiseScale = 2.0f;
        constexpr float kEpsilon = 1e-4f;
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            XMFLOAT2 Modulation;
            float Strength, Anchor;
            float Mix, NoiseScale, Epsilon;
            uint32_t Radius;
            uint32_t Pass, Debug, Flags;
            float TemporalDenoise; // Base only: 0 off; >0 the reference alpha is the temporal residual
            float VerticalStrength; // NZR on vertical surfaces: blend share for mode 2, ignored by modes 0 and 1
            uint32_t VerticalMode; // 0 off (byte-identical), 1 RR, 2 blend (mode 3 was removed in task 24)
            uint32_t VerticalReserved;
        };
        static_assert(sizeof(Constants) == 80, "Flat Detail constants");
        static_assert(offsetof(Constants, TemporalDenoise) == 60, "Flat Detail temporal denoise");
        static_assert(offsetof(Constants, Modulation) == 16, "Flat Detail modulation");
        static_assert(offsetof(Constants, Mix) == 32, "Flat Detail mix");
        static_assert(offsetof(Constants, Pass) == 48, "Flat Detail pass");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InSpecular;
                ID3D12Resource* InDiffuse;
                ID3D12Resource* InSpecularAlbedo;
                ID3D12Resource* InDiffuseAlbedo;
                ID3D12Resource* InSkip;
                ID3D12Resource* InNormals;
                ID3D12Resource* InDepth;
                ID3D12Resource* InReference;
                ID3D12Resource* InStatistics;
                ID3D12Resource* InTiles;
                ID3D12Resource* InBase;
                ID3D12Resource* InMean;
                ID3D12Resource* InVariance;
                ID3D12Resource* InComposed;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data { ID3D12Resource* OutColor; ID3D12Resource* OutStatistics; ID3D12Resource* OutVariance; };
            static constexpr uint32_t kCount = 3;
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        static_assert(Input::kCount == 14, "Flat Detail SRVs");
    }

    namespace FlatTemporal
    {
        constexpr UINT kHistorySlots = 6;
        constexpr float kCenterSigma = 0.35f;
        // History stays on through camera motion; per-sample depth/normal/content checks reject stale samples.
        // A 0.5-2 px fade turned history off on every pan and left motion as noisy as history-off.
        constexpr float kMotionStart = 24.0f;
        constexpr float kMotionEnd = 64.0f;
        constexpr float kHistoryDecay = 6.0f;
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            XMFLOAT2 FullRenderSize, JitterDelta, Modulation;
            float TemporalStrength, Epsilon;
            uint32_t HistoryCount, HistoryHead, HistoryLength, Flags;
            float CenterSigma, MotionStart, MotionEnd, HistoryDecay;
        };
        static_assert(sizeof(Constants) == 80, "Flat temporal constants");
        static_assert(offsetof(Constants, FullRenderSize) == 16, "Flat temporal full size");
        static_assert(offsetof(Constants, JitterDelta) == 24, "Flat temporal jitter");
        static_assert(offsetof(Constants, Modulation) == 32, "Flat temporal modulation");
        static_assert(offsetof(Constants, HistoryCount) == 48, "Flat temporal history");
        static_assert(offsetof(Constants, CenterSigma) == 64, "Flat temporal tuning");
        // History per slot: log reference + depth (RGBA16F) and aux (R32G32_UINT: half motion, half depth
        // delta, motion flag, 15-bit normal). Low-pass lumas live on a 4x4 block grid (RG16F): the LP pass
        // writes the current blocks, Store copies them into the ring.
        constexpr UINT kLPBlock = 4;
        union LPInput
        {
            struct Data
            {
                ID3D12Resource* InComposed; ID3D12Resource* InNormals; ID3D12Resource* InDepth;
                ID3D12Resource* InSpecular; ID3D12Resource* InDiffuse;
                ID3D12Resource* InSpecularAlbedo; ID3D12Resource* InDiffuseAlbedo; ID3D12Resource* InSkip;
            };
            static constexpr uint32_t kCount = 8;
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
        union ResolveInput
        {
            struct Data
            {
                ID3D12Resource* InReference; ID3D12Resource* InNormals; ID3D12Resource* InDepth;
                ID3D12Resource* InMotion; ID3D12Resource* InSkip; ID3D12Resource* InTiles; ID3D12Resource* InLP;
                ID3D12Resource* InHistoryReference; ID3D12Resource* InHistoryAux; ID3D12Resource* InHistoryLP;
            };
            static constexpr uint32_t kCount = 10;
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
        union ResolveOutput
        {
            struct Data { ID3D12Resource* OutReference; ID3D12Resource* OutDiagnostics; };
            static constexpr uint32_t kCount = 2;
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
        union StoreInput
        {
            struct Data
            {
                ID3D12Resource* InReference; ID3D12Resource* InNormals; ID3D12Resource* InDepth;
                ID3D12Resource* InMotion; ID3D12Resource* InSkip; ID3D12Resource* InLP;
            };
            static constexpr uint32_t kCount = 6;
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
        union StoreOutput
        {
            struct Data { ID3D12Resource* OutReference; ID3D12Resource* OutAux; ID3D12Resource* OutLP; };
            static constexpr uint32_t kCount = 3;
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
        static_assert(sizeof(LPInput::Data) == sizeof(ID3D12Resource*) * LPInput::kCount);
        static_assert(sizeof(ResolveInput::Data) == sizeof(ID3D12Resource*) * ResolveInput::kCount);
        static_assert(sizeof(StoreInput::Data) == sizeof(ID3D12Resource*) * StoreInput::kCount);
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
            float _ConversionPadding;
            uint32_t Flags;
            uint32_t InspectorChannel;
            float InspectorScale;
            float DebugDepthMax;
            uint32_t DiffuseHitDistanceMode;
            float ResponsivityTrustThreshold;
            uint32_t ResponsivityInvert;
            float BiasMaskStrength;
            float DemodDivisorFloor;
            float SpecularAlbedoDemodulation;
            float DiffuseAlbedoModulation;
            uint32_t RecoveryMask;
            float AdditiveLightSplit;
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
        static_assert(offsetof(Constants, _ConversionPadding) == 360, "FSRDInputConv layout");
        static_assert(offsetof(Constants, Flags) == 364, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InspectorChannel) == 368, "FSRDInputConv layout");
        static_assert(offsetof(Constants, InspectorScale) == 372, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DebugDepthMax) == 376, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DiffuseHitDistanceMode) == 380, "FSRDInputConv layout");
        static_assert(offsetof(Constants, ResponsivityTrustThreshold) == 384, "FSRDInputConv layout");
        static_assert(offsetof(Constants, ResponsivityInvert) == 388, "FSRDInputConv layout");
        static_assert(offsetof(Constants, BiasMaskStrength) == 392, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DemodDivisorFloor) == 396, "FSRDInputConv layout");
        static_assert(offsetof(Constants, SpecularAlbedoDemodulation) == 400, "FSRDInputConv layout");
        static_assert(offsetof(Constants, DiffuseAlbedoModulation) == 404, "FSRDInputConv layout");
        static_assert(offsetof(Constants, RecoveryMask) == 408, "FSRDInputConv layout");
        static_assert(offsetof(Constants, AdditiveLightSplit) == 412, "FSRDInputConv layout");
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

                // Reserved descriptor slots retain the optional skin/capture ABI.
                ID3D12Resource* Reserved0;
                // The resource-inspector view, likewise ours rather than the title's.
                ID3D12Resource* InInspector;
                ID3D12Resource* InEmissive;  // t11
                ID3D12Resource* InSpecularRayDirectionHitDistance; // t12
                ID3D12Resource* InDiffuseHitDistance;              // t13
                ID3D12Resource* InTitleLinearDepth;                 // t14
                ID3D12Resource* InResponsivityMask;
                ID3D12Resource* Reserved1;                         // t16
                ID3D12Resource* Reserved2;                         // t17
                ID3D12Resource* InPreviousDepth;                   // last frame's canonical depth - t18
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

                // Additive capture journal slot; unused by production conversion.
                ComPtr<ID3D12Resource> Diagnostic;

                // RGB: unmodulated specular share for RR's direct-specular signal (unsupported-
                // albedo recovery). A: 1 where composition may blend toward its denoised result.
                ComPtr<ID3D12Resource> DirectSpecular;
                // RGB: the unmodulated diffuse share for RR's indirect-diffuse signal. A: ray length.
                ComPtr<ID3D12Resource> IndirectDiffuse;

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
            XMUINT3 _Padding;
            XMFLOAT2 SourceUvScale;
            XMFLOAT2 SourceUvOffset;
            float SpecularAlbedoDemodulation;
            float DiffuseAlbedoModulation;
            float UnsupportedAlbedoRecovery;
            float DemodDivisorFloor;
        };
        static_assert(sizeof(Constants) == 64, "FSRDOutputComp constants");
        static_assert(offsetof(Constants, Flags) == 16, "FSRDOutputComp flags");
        static_assert(offsetof(Constants, SourceUvScale) == 32, "FSRDOutputComp source UV");
        static_assert(offsetof(Constants, SpecularAlbedoDemodulation) == 48, "FSRDOutputComp modulation");
        union Output
        {
            struct Data { ID3D12Resource* OutColor; };
            Data Resources;
            ID3D12Resource* AsArray[kOutputCount];
        };

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
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InMotion;
                ID3D12Resource* InDirectSpecularDenoised;
                ID3D12Resource* InDirectSpecularSignal;
                ID3D12Resource* InAlbedoTrust;
                ID3D12Resource* InIndirectDiffuseDenoised;
                // Main RR inputs: recovery rebuilds each lobe's divisor-floor loss in Skip.
                ID3D12Resource* InIndirectSpecularSignal;
                ID3D12Resource* InDirectDiffuseSignal;
            };

            // The number of D3D12 resources in the struct
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);

            Data Resources;

            ID3D12Resource* AsArray[kCount];
        };
    }


    // Compare (split) view: selects variant A on the left and variant B on the right of a
    // vertical divider from two already-computed images. Never denoises and never touches a
    // history; dispatched only while the compare view is active.
    namespace CompareView
    {
        constexpr UINT kBackBufferCount = 3;
        enum Flags : uint32_t
        {
            SwapSides = 1u << 0, // left/right variants exchange places
            DrawDivider = 1u << 1,
            DrawLabels = 1u << 2,
            Resample = 1u << 3,  // bilinear-resample A and B (unequal source/output size)
        };
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            uint32_t Flags;
            uint32_t DividerPx;
            uint32_t _Padding0;
            uint32_t _Padding1;
        };
        static_assert(sizeof(Constants) == 32, "FSRDCompareView constants");
        static_assert(offsetof(Constants, Flags) == 16, "FSRDCompareView flags");
        static_assert(offsetof(Constants, DividerPx) == 20, "FSRDCompareView divider");
        union Input
        {
            struct Data { ID3D12Resource* InA; ID3D12Resource* InB; };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data { ID3D12Resource* OutColor; };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(CompareView::Input::kCount == 2, "CompareView input count");
    static_assert(CompareView::Output::kCount == 1, "CompareView output count");


    // Unsupported-albedo recovery evidence: per pixel, whether the albedo's local structure
    // appears in RR's unmodulated light. Runs after RR and before composition.
    namespace TrustEvidence
    {
        constexpr UINT kBackBufferCount = 3;

        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            int32_t StepSize;
            uint32_t Flags; // Bit 0: split diffuse; bit 1: full unmodulated diffuse alternate.
            float DemodDivisorFloor;
            float _Reserved0;
        };
        static_assert(offsetof(Constants, StepSize) == 16, "FSRDAlbedoTrustEvidence layout");
        static_assert(offsetof(Constants, DemodDivisorFloor) == 24, "FSRDAlbedoTrustEvidence layout");
        static_assert(sizeof(Constants) == 32, "FSRDAlbedoTrustEvidence constant-buffer layout");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InDirectSpecularDenoised;
                ID3D12Resource* InDirectDiffuse;
                ID3D12Resource* InSpecularAlbedo;
                ID3D12Resource* InDiffuseAlbedo;
                ID3D12Resource* InSkipSignal;
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InNormals;
                ID3D12Resource* InDirectSpecularSignal;
                ID3D12Resource* InIndirectDiffuseDenoised;
                ID3D12Resource* InIndirectSpecularSignal;
                ID3D12Resource* InDirectDiffuseSignal;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };

        union Output
        {
            struct Data
            {
                ID3D12Resource* OutAlbedoTrust;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }

    // One a-trous step (stride 1 << pass) of the same-surface normalized convolution that
    // spreads the evidence over a continuous surface.
    namespace TrustPropagate
    {
        constexpr UINT kPasses = 6;
        constexpr UINT kBackBufferCount = 3 * kPasses;

        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            int32_t StepSize;
            uint32_t Flags;
            float DemodDivisorFloor;
            float _Reserved0;
        };
        static_assert(offsetof(Constants, StepSize) == 16, "FSRDAlbedoTrustPropagate layout");
        static_assert(sizeof(Constants) == 32, "FSRDAlbedoTrustPropagate constant-buffer layout");

        union Input
        {
            struct Data
            {
                ID3D12Resource* InAlbedoTrust;
                ID3D12Resource* InLinearDepth;
                ID3D12Resource* InNormals;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };

        union Output
        {
            struct Data
            {
                ID3D12Resource* OutAlbedoTrust;
            };
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
    static_assert(Conversion::Input::kCount == 19, "FSRDInputConv MainRS SRV count");
    static_assert(Conversion::Output::kCount == 10, "FSRDInputConv MainRS UAV count");
    static_assert(Composition::Input::kCount == 14, "FSRDOutputComp MainRS SRV count");
    static_assert(Composition::kOutputCount == 1, "FSRDOutputComp MainRS UAV count");
    static_assert(TrustEvidence::Input::kCount == 11, "FSRDAlbedoTrustEvidence MainRS SRV count");
    static_assert(TrustEvidence::Output::kCount == 1, "FSRDAlbedoTrustEvidence MainRS UAV count");
    static_assert(TrustPropagate::Input::kCount == 3, "FSRDAlbedoTrustPropagate MainRS SRV count");
    static_assert(TrustPropagate::Output::kCount == 1, "FSRDAlbedoTrustPropagate MainRS UAV count");
    namespace SkinConversion
    {
        struct alignas(16) Constants
        {
            Conversion::Constants Base;
            XMUINT4 SkinOptions;
            XMUINT4 SkinDebug;
        };
        static_assert(sizeof(Constants) == 448, "Skin conversion constants");
        static_assert(offsetof(Constants, SkinOptions) == 416, "Skin options offset");
        static_assert(offsetof(Constants, SkinDebug) == 432, "Skin debug offset");
        static constexpr UINT kInputCount = Conversion::Input::kCount + 2;
        static_assert(kInputCount == 21, "Skin conversion inputs");
    }

    namespace SssPrepare
    {
        constexpr UINT kBackBufferCount = 3;
        struct alignas(16) Constants
        {
            XMFLOAT4X4 InvProjMatrix;
            XMFLOAT4 DstTexSize;
            XMUINT4 ColorDepthBase;
            XMUINT4 AlbedoBase;
            XMUINT4 GuideBiasBase;
            XMUINT2 TitleDepthBase;
            XMFLOAT2 CurrentJitter;
            float NearPlane;
            float FarPlane;
            float BiasStrength;
            uint32_t Flags;
            uint32_t Mode;
            XMUINT3 Padding;
        };
        static_assert(sizeof(Constants) == 176, "SssPrepare constants");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor;
                ID3D12Resource* InDepth;
                ID3D12Resource* InDiffAlbedo;
                ID3D12Resource* InSpecAlbedo;
                ID3D12Resource* InGuide;
                ID3D12Resource* InBias;
                ID3D12Resource* InTitleDepth;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        static_assert(Input::kCount == 7, "SssPrepare Input count");
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutColor;
                ID3D12Resource* OutGuide;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        static_assert(Output::kCount == 2, "SssPrepare Output count");
    }

    namespace SssBlur
    {
        constexpr UINT kBackBufferCount = 3;
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            float SigmaScale;
            float RadiusMeters;
            float Strength;
            float Falloff;
            uint32_t Vertical;
            uint32_t Debug;
            XMUINT2 Padding;
        };
        static_assert(sizeof(Constants) == 48, "SssBlur constants");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor;
                ID3D12Resource* InGuide;
                ID3D12Resource* InDepth;
                ID3D12Resource* InOriginal;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        static_assert(Input::kCount == 4, "SssBlur Input count");
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutColor;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        static_assert(Output::kCount == 1, "SssBlur Output count");
    }

    namespace SkinPrefilter
    {
        constexpr UINT kBackBufferCount = 3;
        struct alignas(16) Constants
        {
            XMFLOAT4 DstTexSize;
            float Sigma;
            uint32_t Vertical;
            XMUINT2 GuideBase;
        };
        static_assert(sizeof(Constants) == 32, "SkinPrefilter constants");
        union Input
        {
            struct Data
            {
                ID3D12Resource* InDiffuse;
                ID3D12Resource* InGuide;
                ID3D12Resource* InDepth;
                ID3D12Resource* InNormals;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        static_assert(Input::kCount == 4, "SkinPrefilter Input count");
        union Output
        {
            struct Data
            {
                ID3D12Resource* OutDiffuse;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        static_assert(Output::kCount == 1, "SkinPrefilter Output count");
    }

    namespace SkinFusedConversion
    {
        static constexpr UINT kInputCount = 24, kOutputCount = 14;
        static_assert(kOutputCount == Conversion::Output::kCount + 4, "Fused skin conversion outputs");
        static_assert(kInputCount == SkinConversion::kInputCount + 3, "Fused skin conversion inputs");
    }
    namespace SssKernel
    {
        union Input
        {
            struct Data { ID3D12Resource* InBounds; ID3D12Resource* InDepth; };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data { ID3D12Resource* OutKernel; };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
    }
    namespace SssTiledBlur
    {
        union Input
        {
            struct Data
            {
                ID3D12Resource* InColor; ID3D12Resource* InGuide; ID3D12Resource* InDepth;
                ID3D12Resource* InOriginal; ID3D12Resource* InKernel;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources; ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(SssKernel::Input::kCount == 2 && SssKernel::Output::kCount == 1, "SSS kernel descriptors");
    static_assert(SssTiledBlur::Input::kCount == 5, "SSS tiled blur inputs");

    namespace SkinConversionBounds
    {
        static constexpr UINT kOutputCount = Conversion::Output::kCount + 1;
        static_assert(kOutputCount == 11, "Skin bounds conversion outputs");
    }
    namespace SkinBounds
    {
        union Input
        {
            struct Data { ID3D12Resource* InBounds; };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data { ID3D12Resource* OutBounds; };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    namespace SkinTiledPrefilter
    {
        union Input
        {
            struct Data
            {
                ID3D12Resource* InDiffuse;
                ID3D12Resource* InGuide;
                ID3D12Resource* InDepth;
                ID3D12Resource* InNormals;
                ID3D12Resource* InBounds;
            };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
        union Output
        {
            struct Data { ID3D12Resource* OutDiffuse; };
            static constexpr uint32_t kCount = sizeof(Data) / sizeof(ID3D12Resource*);
            Data Resources;
            ID3D12Resource* AsArray[kCount];
        };
    }
    static_assert(SkinBounds::Input::kCount == 1, "SkinBounds input count");
    static_assert(SkinBounds::Output::kCount == 1, "SkinBounds output count");
    static_assert(SkinTiledPrefilter::Input::kCount == 5, "SkinTiledPrefilter input count");
    static_assert(SkinTiledPrefilter::Output::kCount == 1, "SkinTiledPrefilter output count");

    static_assert(SssPrepare::Input::kCount == 7, "SssPrepare input count");
    static_assert(SssPrepare::Output::kCount == 2, "SssPrepare output count");

    static_assert(SssBlur::Input::kCount == 4, "SssBlur input count");
    static_assert(SssBlur::Output::kCount == 1, "SssBlur output count");

    static_assert(SkinPrefilter::Input::kCount == 4, "SkinPrefilter input count");
    static_assert(SkinPrefilter::Output::kCount == 1, "SkinPrefilter output count");

}
