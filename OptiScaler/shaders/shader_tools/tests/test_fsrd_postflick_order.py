"""Production dispatch-order regression for the post-flick blotch fix (task 24 T2 c, F5).

The GPU fixture drives the two post-flick passes standalone with hand-built inputs; no
test in the repo drives the feature's own dispatch order. This one does: it extracts
CompositionColor, DispatchComposition, DispatchFlatDetail and DispatchPostFlick from
OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp and compiles that real text
into a CPU-only stub host (no D3D12 device, no GPU work). The host records, at every
production call site that reads CompositionColor(), the value of m_postFlickActive and
the resource the real CompositionColor() returns. The methods are never copied: if the
production text moves or the stubbed member layout changes, this test follows it or
stops compiling.

Invariants (SA9 F2/F5, SA8's per-frame flag rule):
  * option ON: the in-place flat-detail (Near-zero-rough) apply writes the recovery
    output, never the previous frame's post-flick texture (the F2 regression);
  * option ON: the post-flick passes read the same resource the flat-detail apply wrote,
    so the NZR correction reaches the image;
  * option ON: no consumer before the post-flick apply sees the flag set; after
    DispatchPostFlick the skin pass and the caller see the post-flick texture;
  * option OFF: no consumer ever sees the post-flick texture and the flag ends false;
  * every early return inside DispatchPostFlick (resolution mismatch, zero render size,
    EnsurePostFlick failure) leaves the flag false;
  * ON, ON, OFF, ON: the flag is cleared before the first consumer of every frame.

The same harness is also compiled with two wrong flag placements restored inside the
extracted copy and must then fail the invariants that name them: (1) the pre-7ac28ffd9
ownership (the clear inside DispatchPostFlick, after the in-place flat-detail pass) and
(2) the clear at the end of the extracted body, which drops the pass output from what the
caller sees. The test therefore proves its own power on every run.
FSRD_POSTFLICK_ORDER_MUTANT=<name|1> runs only a mutated copy (the harness must fail and
the caught invariants are printed; a mutant that passes everything is an error).

Run through the task wrapper:
  cd F:/FSRD/sol_batch && python lead_ops/run_task_test.py --task 24-glass-hfix \
      --name sa11_order --cpu --script \
      F:/OptiRevelations/OSA-24-glass-hfix/OptiScaler/shaders/shader_tools/tests/test_fsrd_postflick_order.py

Not covered, by construction: there is no D3D12 device, so no resource-state
transitions, no real bindings and no shader execution. The stubbed call boundaries are
DispatchRecoveryChain, ReblurSkin, ResolveFlatTemporal (and with it the flat-temporal LP
input read of CompositionColor()), TransitionDenoiserOutputsToRead, DispatchAlbedoTrust,
the compare view and EnsurePostFlick; PrepareSkin's per-frame skin-flag clear is mirrored
by the harness. The four extracted methods are the real production text, so the dispatch
order, the resource preference and the flag ownership under test are the production ones.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
PREPROCESSOR = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp'
POSTFLICK_HEADER = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDPostFlickConstants.h'
COLOUR_TRACK_HEADER = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDColourTrackConstants.h'

# The frame-start clear. It is the anchor of the historical mutant, so the test fails
# loudly (instead of silently skipping the power check) if the production text moves it.
FRAME_START_CLEAR = '        m_postFlickActive = false;\n'

SIGNATURES = (
    'ID3D12Resource* CompositionColor() const',
    'void DispatchComposition(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)',
    'void DispatchFlatDetail(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)',
    'void DispatchPostFlick(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)',
    # Post-RR colour tracking (task 25 T2): the same treatment - the production text, so the
    # order it dispatches in and the option-OFF path are the production ones.
    'bool ColourTrackFrame(const CompositionDesc& desc) const',
    'bool PrepareColourTrack(const CompositionDesc& desc)',
    'void DispatchColourTrack(ID3D12GraphicsCommandList* cmdList, const CompositionDesc& desc)',
)


def method(source, signature):
    """The production method text, brace balanced, exactly as it stands in the file."""
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


PREAMBLE = r'''
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>
#include "___POSTFLICK_HEADER___"
#include "___COLOUR_TRACK_HEADER___"

// The extracted methods are compiled against these doubles: the resource, command-list,
// pipeline-state and shader types are opaque handles the production text only passes
// around. Nothing here is a production substitute except the stubbed call boundaries
// listed in the report.
using byte = unsigned char;
using UINT = unsigned int;
using DirectX::XMFLOAT2;
using DirectX::XMFLOAT4;
using DirectX::XMFLOAT4X4;
using DirectX::XMUINT3;

struct ID3D12Resource { int id = -1; };
struct ID3D12Device {};
struct ID3D12PipelineState {};
struct ID3D12CommandSignature {};
struct ID3D12GraphicsCommandList
{
    unsigned copies = 0;
    void CopyBufferRegion(ID3D12Resource*, uint64_t, ID3D12Resource*, uint64_t, uint64_t) { ++copies; }
};
template <class T> struct ComPtr
{
    T* p = nullptr;
    ComPtr() = default;
    ComPtr(T* value) : p(value) {}
    T* Get() const { return p; }
    void Reset() { p = nullptr; }
    explicit operator bool() const { return p != nullptr; }
    ComPtr& operator=(T* value) { p = value; return *this; }
};

constexpr int kSrvState = 1, kUavState = 16;
constexpr int D3D12_RESOURCE_STATE_COPY_DEST = 4, D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT = 8;
inline void AddBarrier(ID3D12GraphicsCommandList*, ID3D12Resource*, int, int) {}
template <typename T> std::span<const byte> GetAsByteSpan(const T& data)
{
    return { reinterpret_cast<const byte*>(&data), sizeof(data) };
}
namespace ResTrack_Dx12
{
    inline bool RetainComputeDispatch(ID3D12Device*, ID3D12GraphicsCommandList*, const std::shared_ptr<void>&)
    {
        return true;
    }
}

struct FSRDRuntimeSnapshot
{
    enum Step { Inputs, Conversion, RayRegeneration, Composition, AlbedoRecovery, SuperResolution, StepCount };
    static constexpr int Disabled = -1;
    int steps[StepCount] = {};
    void Begin(Step) {}
    void Complete(Step) {}
};
struct FSRDStageTimings
{
    enum Kind { Composition, SkinReblur, FlatDetail, PassCompositionMain, PassFlatClassify, PassFlatSeed,
                PassFlatRefine, PassFlatBase, PassFlatApply, PassFlatTemporalResolve, PassFlatTemporalStore };
    struct Scope { Scope(FSRDStageTimings&, Kind) {} };
    struct PassScope { PassScope(FSRDStageTimings&, Kind) {} };
};

// Field order mirrors FSRDPreprocessor_Dx12.h and FSRDShaderData.h. The compiler
// enforces it: the extracted designated initializers must list these names in this
// order, so a production rename or reorder stops this build instead of drifting.
enum class CompFlags : uint32_t
{
    None = 0,
    RawSourceBlit = 1 << 0,
    DiffuseSignalDisabled = 1 << 4,
    SpecularSignalDisabled = 1 << 5,
    ExtraDiffuse = 1 << 6,
    ExtraSpecular = 1 << 7,
    ColourTrackTarget = 1 << 10,
    Debug = 1 << 16,
    DebugModeMask = 0xFF << 16,
    DebugFlatDetail = 25 << 17 | Debug,
    DebugFlatDetailReference = 26 << 17 | Debug,
};

struct CompositionDesc
{
    XMFLOAT4 DstTexSize;
    uint32_t Flags = 0;
    uint32_t RecoveryMask = 1;
    float SpecularAlbedoDemodulation = 1.0f;
    float DiffuseAlbedoModulation = 1.0f;
    float UnsupportedAlbedoRecovery = 0.0f;
    float DemodDivisorFloor = 8e-3f;
    bool RecoveryV2 = false;
    float RecoverySpecularStrength = 0.0f;
    float RecoveryDiffuseStrength = 0.0f;
    float RecoveryFlatAlbedoStrength = 0.0f;
    float RecoveryAnchor = 4.0f;
    float RecoveryMix = 0.0f;
    float RecoveryFlatAnchor = 4.0f;
    float RecoveryFlatMix = 0.0f;
    bool RecoveryFlatTemporal = true;
    uint32_t RecoveryFlatHistoryLength = 6;
    float RecoveryFlatTemporalDenoise = 1.0f;
    uint32_t RecoveryDebug = 0;
    bool PostFlickFix = false;
    float PostFlickStrength = 1.0f;
    XMFLOAT4X4 ViewMatrix {};
    XMFLOAT4X4 ProjectionMatrix {};
    XMFLOAT4X4 PrevViewMatrix {};
    bool ColourTrack = false;
    float ColourTrackStrength = 1.0f;
    float ColourTrackEmaWeight = 0.25f;
    float ColourTrackRadius = 16.0f;
    uint32_t CompareView = 0;
};

namespace Composition
{
    constexpr UINT kOutputCount = 2;
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
    union Output
    {
        struct Data { ID3D12Resource* OutColor; ID3D12Resource* OutTarget; };
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
            ID3D12Resource* InIndirectSpecularSignal;
            ID3D12Resource* InDirectDiffuseSignal;
        };
        static constexpr uint32_t kCount = 14;
        Data Resources;
        ID3D12Resource* AsArray[kCount];
    };
}

namespace FlatDetail
{
    constexpr UINT kRefinementPasses = 1;
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
        float TemporalDenoise;
        float VerticalStrength;
        uint32_t VerticalMode;
        uint32_t VerticalReserved;
    };
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
        static constexpr uint32_t kCount = 14;
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
}

enum Res : int
{
    kCompositionOutput, kRecoveryOutput0, kRecoveryOutput1, kPostFlickOutput, kSkinResult,
    kLinearDepth, kMotion, kNormals, kSpecAlbedo, kDiffAlbedo, kSkipSignal, kDirectSpecular,
    kIndirectSpecular, kDirectDiffuse, kOutputBuffer1, kOutputBuffer2, kDirectSpecularOutput,
    kIndirectDiffuseOutput, kAlbedoTrust0, kAlbedoTrust1, kFlatDetailTiles, kFlatDetailArguments,
    kFlatDetailReset, kFlatDetailReference0, kFlatDetailReference1, kFlatDetailStatistics0,
    kFlatDetailStatistics1, kFlatDetailBase, kFlatDetailMean, kFlatDetailVariance,
    kPostFlickKey0, kPostFlickKey1, kPostFlickKeyAux0, kPostFlickKeyAux1, kPostFlickAux0,
    kPostFlickAux1, kPostFlickCur,
    kColourTrackInput, kColourTrackStats, kColourTrackTarget, kColourTrackMotion, kColourTrackGain,
    kColourTrackHistory0, kColourTrackHistory1, kResourceCount
};
constexpr const char* kResourceNames[kResourceCount] =
{
    "composition", "recovery0", "recovery1", "post-flick-output", "skin-result",
    "linear-depth", "motion", "normals", "spec-albedo", "diff-albedo", "skip", "direct-specular",
    "indirect-specular", "direct-diffuse", "buffer1", "buffer2", "direct-specular-output",
    "indirect-diffuse-output", "albedo-trust0", "albedo-trust1", "flat-tiles", "flat-arguments",
    "flat-reset", "flat-reference0", "flat-reference1", "flat-statistics0",
    "flat-statistics1", "flat-base", "flat-mean", "flat-variance",
    "post-flick-key0", "post-flick-key1", "post-flick-key-aux0", "post-flick-key-aux1", "post-flick-aux0",
    "post-flick-aux1", "post-flick-cur",
    "colour-track-input", "colour-track-stats", "colour-track-target", "colour-track-motion", "colour-track-gain",
    "colour-track-history0", "colour-track-history1"
};
inline ID3D12Resource* Res(int id)
{
    static ID3D12Resource pool[kResourceCount];
    pool[id].id = id;
    return &pool[id];
}
inline int ResId(const ID3D12Resource* resource) { return resource ? resource->id : -1; }
inline const char* ResName(int id) { return id >= 0 && id < kResourceCount ? kResourceNames[id] : "none"; }

// One recorded production call site: which pass, the flag value at that instant and the
// resource the real CompositionColor() returned. `target` is the dispatch output,
// `source` the first dispatch input and `last_input` the 14th (FlatDetail::InComposed for
// the flat-detail passes, unused elsewhere).
struct Record
{
    std::string site;
    bool flag = false;
    int color = -1, target = -1, source = -1, last_input = -1;
};

struct Host;
struct ComputeState
{
    const char* name = "?";
    Host* host = nullptr;
    void Dispatch(ID3D12GraphicsCommandList* cmdList, std::span<const byte> cbData,
                  std::span<ID3D12Resource* const> inputs, std::span<ID3D12Resource*> outputs, XMFLOAT2 outDim,
                  bool autoBarrierOutput = true, ID3D12PipelineState* pipelineState = nullptr,
                  ID3D12CommandSignature* indirectSignature = nullptr, ID3D12Resource* indirectArguments = nullptr);
};

struct Host
{
    // ---- production members the extracted methods touch (FSRDPreprocessor_Dx12.cpp Impl) ----
    FSRDRuntimeSnapshot runtime;
    FSRDRuntimeSnapshot* m_runtime = &runtime;
    FSRDStageTimings m_stageTimings;
    ID3D12Device* m_pDev = nullptr;
    UINT m_maxWidth = 1920, m_maxHeight = 1080;
    int m_recoveryOutputIndex = -1;
    bool m_postFlickActive = false, m_postFlickValid = false, m_postFlickWasEnabled = false;
    bool m_skinOutputActive = false, m_flatDetailActive = false, m_flatTemporalActive = false;
    bool m_compareSnapshotsReady = false, m_compareFrozenValid = false;
    uint32_t m_postFlickParity = 0, m_postFlickWidth = 0, m_postFlickHeight = 0;
    // Post-RR colour tracking (task 25 T2) state the extracted methods touch.
    bool m_colourTrackValid = false, m_colourTrackWasEnabled = false, m_colourTrackActive = false;
    uint32_t m_colourTrackWidth = 0, m_colourTrackHeight = 0, m_colourTrackHistoryIndex = 0;
    uint32_t m_compareView = 0, m_comparePresentWidth = 0, m_comparePresentHeight = 0;
    uint32_t m_albedoTrustResult = 0;
    PostFlickMath::KeyState m_postFlickKeyState {};
    FlatDetail::Constants m_flatDetailConstants {};
    ComPtr<ID3D12Resource> m_compositionOutput, m_LinearDepth, m_postFlickCur, m_postFlickOutput;
    ComPtr<ID3D12Resource> m_skinResult, m_compareSnapshotA, m_compareSnapshotB, m_comparePresent, m_compareFrozen;
    ComPtr<ID3D12Resource> m_recoveryOutput[2];
    ComPtr<ID3D12Resource> m_outputBuffer1, m_outputBuffer2, m_directSpecularOutput, m_indirectDiffuseOutput;
    ComPtr<ID3D12Resource> m_albedoTrust[2];
    ComPtr<ID3D12Resource> m_flatDetailTiles, m_flatDetailArguments, m_flatDetailReset;
    ComPtr<ID3D12Resource> m_flatDetailReference[2], m_flatDetailStatistics[2];
    ComPtr<ID3D12Resource> m_flatDetailBase, m_flatDetailMean, m_flatDetailVariance;
    ComPtr<ID3D12Resource> m_flatDetailSignatureResource;
    ComPtr<ID3D12CommandSignature> m_flatDetailSignature;
    std::array<ComPtr<ID3D12Resource>, 2> m_postFlickKey, m_postFlickKeyAux, m_postFlickAux;
    ComPtr<ID3D12Resource> m_colourTrackInput, m_colourTrackStats, m_colourTrackTarget, m_colourTrackMotion,
        m_colourTrackGain;
    std::array<ComPtr<ID3D12Resource>, 2> m_colourTrackHistory;
    struct
    {
        struct
        {
            ComPtr<ID3D12Resource> Motion, Normals, SpecAlbedo, SkipSignal, DiffAlbedo, DirectSpecular;
            struct { ComPtr<ID3D12Resource> IndirectSpecular, DirectDiffuse; } Signals;
        } Resources;
    } m_out;
    ComputeState m_compShader, m_flatDetailClassifyShader, m_flatDetailSeedShader, m_flatDetailRefineShader,
        m_flatDetailBaseShader, m_flatDetailApplyShader, m_postFlickPrepareShader, m_postFlickApplyShader,
        m_colourTrackStatsShader, m_colourTrackTrackShader, m_colourTrackApplyShader;

    // ---- harness-only controls and the recording ----
    std::vector<Record> records;
    bool skinWritesOutput = false;
    bool ensurePostFlickSucceeds = true;
    bool ensureColourTrackSucceeds = true;

    explicit Host()
    {
        m_compositionOutput = Res(kCompositionOutput);
        m_recoveryOutput[0] = Res(kRecoveryOutput0);
        m_recoveryOutput[1] = Res(kRecoveryOutput1);
        m_postFlickOutput = Res(kPostFlickOutput);
        m_postFlickCur = Res(kPostFlickCur);
        m_skinResult = Res(kSkinResult);
        m_LinearDepth = Res(kLinearDepth);
        m_flatDetailTiles = Res(kFlatDetailTiles);
        m_flatDetailArguments = Res(kFlatDetailArguments);
        m_flatDetailReset = Res(kFlatDetailReset);
        m_flatDetailReference[0] = Res(kFlatDetailReference0);
        m_flatDetailReference[1] = Res(kFlatDetailReference1);
        m_flatDetailStatistics[0] = Res(kFlatDetailStatistics0);
        m_flatDetailStatistics[1] = Res(kFlatDetailStatistics1);
        m_flatDetailBase = Res(kFlatDetailBase);
        m_flatDetailMean = Res(kFlatDetailMean);
        m_flatDetailVariance = Res(kFlatDetailVariance);
        m_flatDetailSignatureResource = Res(kFlatDetailReset);
        m_albedoTrust[0] = Res(kAlbedoTrust0);
        m_albedoTrust[1] = Res(kAlbedoTrust1);
        m_outputBuffer1 = Res(kOutputBuffer1);
        m_outputBuffer2 = Res(kOutputBuffer2);
        m_directSpecularOutput = Res(kDirectSpecularOutput);
        m_indirectDiffuseOutput = Res(kIndirectDiffuseOutput);
        for (uint32_t parity = 0; parity < 2; ++parity)
        {
            m_postFlickKey[parity] = Res(kPostFlickKey0 + int(parity));
            m_postFlickKeyAux[parity] = Res(kPostFlickKeyAux0 + int(parity));
            m_postFlickAux[parity] = Res(kPostFlickAux0 + int(parity));
        }
        auto& r = m_out.Resources;
        r.Motion = Res(kMotion); r.Normals = Res(kNormals); r.SpecAlbedo = Res(kSpecAlbedo);
        r.SkipSignal = Res(kSkipSignal); r.DiffAlbedo = Res(kDiffAlbedo); r.DirectSpecular = Res(kDirectSpecular);
        r.Signals.IndirectSpecular = Res(kIndirectSpecular); r.Signals.DirectDiffuse = Res(kDirectDiffuse);
        const std::pair<ComputeState*, const char*> shaders[] =
        {
            {&m_compShader, "composition-main"}, {&m_flatDetailClassifyShader, "flat-detail-classify"},
            {&m_flatDetailSeedShader, "flat-detail-seed"}, {&m_flatDetailRefineShader, "flat-detail-refine"},
            {&m_flatDetailBaseShader, "flat-detail-base"}, {&m_flatDetailApplyShader, "flat-detail-apply"},
            {&m_postFlickPrepareShader, "post-flick-prepare"}, {&m_postFlickApplyShader, "post-flick-apply"},
            {&m_colourTrackStatsShader, "colour-track-stats"}, {&m_colourTrackTrackShader, "colour-track-track"},
            {&m_colourTrackApplyShader, "colour-track-apply"},
        };
        for (const auto& entry : shaders) { entry.first->host = this; entry.first->name = entry.second; }
    }

    // Mirrors PrepareSkin, which owns m_skinOutputActive in the conversion phase: the skin
    // flag is decided before DispatchComposition and only ReblurSkin raises it.
    void FrameStart() { m_skinOutputActive = false; }

    void note(const char* site)
    {
        Record record;
        record.site = site;
        record.flag = m_postFlickActive;
        record.color = ResId(CompositionColor());
        records.push_back(record);
    }
    void note_dispatch(const char* site, std::span<ID3D12Resource* const> inputs, std::span<ID3D12Resource*> outputs)
    {
        Record record;
        record.site = site;
        record.flag = m_postFlickActive;
        record.color = ResId(CompositionColor());
        record.source = inputs.empty() ? -1 : ResId(inputs[0]);
        record.last_input = inputs.size() >= FlatDetail::Input::kCount
            ? ResId(inputs[FlatDetail::Input::kCount - 1]) : -1;
        record.target = outputs.empty() ? -1 : ResId(outputs[0]);
        records.push_back(record);
    }

    // ---- stubbed call boundaries: every one records the state production would see ----
    void TransitionDenoiserOutputsToRead(ID3D12GraphicsCommandList*) noexcept { note("transition-to-read"); }
    void DispatchAlbedoTrust(ID3D12GraphicsCommandList*, const CompositionDesc&, ID3D12Resource*)
    {
        note("albedo-trust");
    }
    void DispatchRecoveryChain(ID3D12GraphicsCommandList*, const CompositionDesc&)
    {
        note("recovery-chain-enter");
        m_recoveryOutputIndex = 0;  // the real chain ping-pongs into one of the two recovery outputs
        note("recovery-chain-exit");
    }
    ID3D12Resource* ResolveFlatTemporal(ID3D12GraphicsCommandList*, const CompositionDesc&,
                                        ID3D12Resource* originalReference, ID3D12Resource*, uint32_t)
    {
        note("flat-temporal-resolve-enter");
        return originalReference;   // the temporal-off path returns the original reference
    }
    void ReblurSkin(ID3D12GraphicsCommandList*, const CompositionDesc&)
    {
        note("reblur-skin-enter");  // production reads CompositionColor() here
        if (skinWritesOutput) { m_skinOutputActive = true; note("reblur-skin-write"); }
    }
    bool EnsurePostFlick() { note("ensure-post-flick"); return ensurePostFlickSucceeds; }
    // The production EnsureColourTrack creates the size-bound textures; the harness only gives the members
    // identities, because the dispatch guards and the records are what is under test here (the GPU fixture owns
    // the real allocation, the pass arithmetic and the cost).
    bool EnsureColourTrack()
    {
        note("ensure-colour-track");
        if (!ensureColourTrackSucceeds) return false;
        m_colourTrackInput = Res(kColourTrackInput);
        m_colourTrackStats = Res(kColourTrackStats);
        m_colourTrackTarget = Res(kColourTrackTarget);
        m_colourTrackMotion = Res(kColourTrackMotion);
        m_colourTrackGain = Res(kColourTrackGain);
        m_colourTrackHistory[0] = Res(kColourTrackHistory0);
        m_colourTrackHistory[1] = Res(kColourTrackHistory1);
        return true;
    }
    void ResetFlatTemporalHistory() {}
    void EnsureFlatDetail() {}
    void EnsureCompareSnapshots(UINT, UINT) {}
    bool CaptureCompare(ID3D12GraphicsCommandList*, ID3D12Resource*, ComPtr<ID3D12Resource>&) { return false; }

    // ---- production methods, appended verbatim by the test ----
'''

DISPATCH_DEFINITION = r'''
inline void ComputeState::Dispatch(ID3D12GraphicsCommandList*, std::span<const byte>,
                                   std::span<ID3D12Resource* const> inputs, std::span<ID3D12Resource*> outputs,
                                   XMFLOAT2, bool, ID3D12PipelineState*, ID3D12CommandSignature*, ID3D12Resource*)
{
    host->note_dispatch(name, inputs, outputs);
}
'''

MAIN = r'''
static int failures = 0;
static void check(const std::string& name, bool ok, const std::string& detail)
{
    if (!ok) ++failures;
    std::cout << "CHECK\t" << name << '\t' << (ok ? "PASS" : "FAIL") << '\t' << detail << '\n';
}

struct Frame
{
    std::vector<Record> records;
    bool flagEnd = false;
    int colorEnd = -1;
    bool colourTrackActive = false, colourTrackWasEnabled = false;
    int colourTrackTarget = -1, colourTrackInput = -1;
};

int main()
{
    ID3D12GraphicsCommandList list;
    Host h;
    CompositionDesc desc {};
    desc.DstTexSize = XMFLOAT4(1920.0f, 1080.0f, 1.0f / 1920.0f, 1.0f / 1080.0f);
    desc.RecoveryV2 = true;
    desc.RecoveryFlatAlbedoStrength = 1.0f;  // Config.h default: the flat detail is on
    desc.RecoveryFlatTemporal = false;       // the temporal resolve is a stub here
    desc.PostFlickFix = true;
    desc.PostFlickStrength = 1.0f;
    const XMFLOAT4X4 identity = []
    {
        XMFLOAT4X4 matrix {};
        matrix.m[0][0] = matrix.m[1][1] = matrix.m[2][2] = matrix.m[3][3] = 1.0f;
        return matrix;
    }();
    desc.ViewMatrix = desc.ProjectionMatrix = desc.PrevViewMatrix = identity;

    std::vector<Frame> frames;
    const auto run = [&](bool fix, bool skinWrites, bool colourTrack = false)
    {
        h.FrameStart();
        desc.PostFlickFix = fix;
        desc.ColourTrack = colourTrack;
        h.skinWritesOutput = skinWrites;
        h.records.clear();
        h.DispatchComposition(&list, desc);
        Frame frame;
        frame.records = h.records;
        frame.flagEnd = h.m_postFlickActive;
        frame.colorEnd = ResId(h.CompositionColor());
        frame.colourTrackActive = h.m_colourTrackActive;
        frame.colourTrackWasEnabled = h.m_colourTrackWasEnabled;
        frame.colourTrackTarget = ResId(h.m_colourTrackTarget.Get());
        frame.colourTrackInput = ResId(h.m_colourTrackInput.Get());
        frames.push_back(std::move(frame));
    };
    const auto find = [](const Frame& frame, const char* site) -> const Record*
    {
        for (const auto& record : frame.records)
            if (record.site == site) return &record;
        return nullptr;
    };
    const auto show = [](const Record* record)
    {
        if (!record) return std::string("(no record)");
        return std::string("flag=") + (record->flag ? "1" : "0") + " color=" + ResName(record->color) +
               " target=" + ResName(record->target) + " source=" + ResName(record->source) +
               " last_input=" + ResName(record->last_input);
    };
    const auto end = [](const Frame& frame)
    {
        return std::string("frame_end_flag=") + (frame.flagEnd ? "1" : "0") +
               " frame_end_color=" + ResName(frame.colorEnd);
    };
    const auto joined = [&show](const std::vector<const Record*>& found)
    {
        std::string text;
        for (size_t index = 0; index < found.size() && index < 4; ++index) text += show(found[index]) + " ";
        if (found.size() > 4) text += "(+" + std::to_string(found.size() - 4) + " more) ";
        return text;
    };

    // Frame 1-4: ON, ON, OFF, ON (the two-frame lifecycle the audits found broken).
    run(true, false);   // 1: ON, skin inactive -> the caller sees the post-flick texture
    run(true, true);    // 2: ON, skin writes -> the F2 frame (a stale flag would target frame 1's output)
    run(false, false);  // 3: OFF
    run(true, false);   // 4: ON again after OFF (rising edge)
    const Frame& on1 = frames[0];
    const Frame& on2 = frames[1];
    const Frame& off = frames[2];
    const Frame& on3 = frames[3];

    // --- invariant (a): the in-place flat-detail apply targets the recovery output ---
    const Record* apply1 = find(on1, "flat-detail-apply");
    check("on-frame-1-flat-detail-apply-targets-the-recovery-output",
          apply1 && !apply1->flag && apply1->target == kRecoveryOutput0,
          show(apply1) + " expected target=" + ResName(kRecoveryOutput0));
    const Record* apply2 = find(on2, "flat-detail-apply");
    check("on-frame-2-flat-detail-apply-targets-the-recovery-output",
          apply2 && !apply2->flag && apply2->target == kRecoveryOutput0,
          show(apply2) + " expected target=" + ResName(kRecoveryOutput0));
    const Record* base2 = find(on2, "flat-detail-base");
    check("on-frame-2-flat-detail-base-freezes-the-corrected-composite",
          base2 && !base2->flag && base2->last_input == kRecoveryOutput0,
          show(base2) + " expected last_input=" + ResName(kRecoveryOutput0));
    const Record* classify2 = find(on2, "flat-detail-classify");
    check("on-frame-2-flat-detail-entered-with-the-flag-false",
          classify2 && !classify2->flag && classify2->color == kRecoveryOutput0,
          show(classify2) + " expected color=" + ResName(kRecoveryOutput0));

    // --- the post-flick passes read what the flat-detail apply wrote (the correction survives) ---
    const Record* prepare1 = find(on1, "post-flick-prepare");
    check("on-frame-1-post-flick-reads-the-flat-detail-corrected-composite",
          prepare1 && apply1 && prepare1->source == apply1->target && prepare1->source == kRecoveryOutput0,
          show(prepare1) + " flat_apply_target=" + ResName(apply1 ? apply1->target : -1));
    const Record* prepare2 = find(on2, "post-flick-prepare");
    check("on-frame-2-post-flick-reads-the-flat-detail-corrected-composite",
          prepare2 && apply2 && prepare2->source == apply2->target && prepare2->source == kRecoveryOutput0,
          show(prepare2) + " flat_apply_target=" + ResName(apply2 ? apply2->target : -1));

    // --- invariant (b): after DispatchPostFlick the later passes and the caller see the post-flick texture ---
    const Record* postApply1 = find(on1, "post-flick-apply");
    check("on-frame-1-post-flick-apply-writes-the-post-flick-texture-before-the-flag-is-raised",
          postApply1 && !postApply1->flag && postApply1->target == kPostFlickOutput,
          show(postApply1) + " expected target=" + ResName(kPostFlickOutput));
    const Record* skin1 = find(on1, "reblur-skin-enter");
    check("on-frame-1-skin-sees-the-post-flick-texture",
          skin1 && skin1->flag && skin1->color == kPostFlickOutput,
          show(skin1) + " expected color=" + ResName(kPostFlickOutput));
    check("on-frame-1-frame-end-is-the-post-flick-texture",
          on1.flagEnd && on1.colorEnd == kPostFlickOutput, end(on1));
    const Record* skin2 = find(on2, "reblur-skin-enter");
    check("on-frame-2-skin-reads-the-post-flick-texture-and-becomes-the-output",
          skin2 && skin2->flag && skin2->color == kPostFlickOutput && on2.flagEnd && on2.colorEnd == kSkinResult,
          show(skin2) + " " + end(on2) + " expected color=" + ResName(kPostFlickOutput));

    // --- invariant (c): OFF never sees the post-flick texture and never keeps the flag ---
    std::vector<const Record*> seen, stale, early;
    for (const auto& record : off.records)
        if (record.color == kPostFlickOutput || record.site == std::string("post-flick-prepare") ||
            record.site == std::string("post-flick-apply"))
            seen.push_back(&record);
    check("off-frame-never-returns-the-post-flick-texture", seen.empty(),
          seen.empty() ? "no post-flick texture at any consumer" : joined(seen));
    for (const auto& record : off.records)
        if (record.flag) stale.push_back(&record);
    check("off-frame-keeps-the-flag-false-at-every-consumer", stale.empty(),
          stale.empty() ? "flag false at every consumer" : joined(stale));
    const Record* applyOff = find(off, "flat-detail-apply");
    check("off-frame-flat-detail-apply-still-targets-the-recovery-output",
          applyOff && !applyOff->flag && applyOff->target == kRecoveryOutput0,
          show(applyOff) + " expected target=" + ResName(kRecoveryOutput0));
    check("off-frame-end-flag-is-false-and-the-output-is-the-recovery-output",
          !off.flagEnd && off.colorEnd == kRecoveryOutput0, end(off));

    // --- invariant (e): ON, ON, OFF, ON and the frame-start clear on every frame ---
    const Record* apply3 = find(on3, "flat-detail-apply");
    check("on-frame-after-off-resumes",
          on3.flagEnd && on3.colorEnd == kPostFlickOutput && find(on3, "post-flick-apply") &&
          apply3 && apply3->target == kRecoveryOutput0, end(on3) + " " + show(apply3));
    check("frame-end-flag-sequence-on-on-off-on",
          on1.flagEnd && on2.flagEnd && !off.flagEnd && on3.flagEnd,
          end(on1) + " | " + end(on2) + " | " + end(off) + " | " + end(on3));
    for (const Frame* frame : {&on1, &on2, &off, &on3})
        for (const auto& record : frame->records)
        {
            if (record.site == std::string("post-flick-apply")) break;  // the flag is raised after this dispatch
            if (record.flag) early.push_back(&record);
        }
    check("no-consumer-before-the-post-flick-apply-sees-the-flag-set", early.empty(),
          early.empty() ? "flag false at every consumer up to the post-flick apply" : joined(early));
    // --- invariant (d): early returns inside DispatchPostFlick cannot leave the flag set ---
    // --- post-RR colour tracking (task 25 T2): the option's own order and OFF path ---
    run(false, false, true);    // colour tracking ON, post-flick OFF: its own frame
    run(false, false, false);   // colour tracking OFF
    const Frame& track = frames[4];
    const Frame& trackOff = frames[5];
    const auto indexOf = [](const Frame& frame, const char* site)
    {
        for (size_t index = 0; index < frame.records.size(); ++index)
            if (frame.records[index].site == site) return int(index);
        return -1;
    };
    const int composition = indexOf(track, "composition-main");
    const int stats = indexOf(track, "colour-track-stats");
    const int reproject = indexOf(track, "colour-track-track");
    const int apply = indexOf(track, "colour-track-apply");
    const int recovery = indexOf(track, "recovery-chain-enter");
    check("colour-track-runs-after-composition-and-before-the-recovery-chain",
          composition >= 0 && stats == composition + 1 && reproject == stats + 1 && apply == reproject + 1 &&
          recovery == apply + 1,
          "composition=" + std::to_string(composition) + " stats=" + std::to_string(stats) + " track=" +
          std::to_string(reproject) + " apply=" + std::to_string(apply) + " recovery=" + std::to_string(recovery));
    check("colour-track-apply-corrects-the-composition-output",
          apply >= 0 && track.records[apply].target == kCompositionOutput &&
          track.records[stats].source == kCompositionOutput,
          show(apply >= 0 ? &track.records[apply] : nullptr) + " " +
          show(stats >= 0 ? &track.records[stats] : nullptr) + " expected target/source=" +
          ResName(kCompositionOutput));
    check("colour-track-allocates-before-the-composition-writes-the-target",
          indexOf(track, "ensure-colour-track") >= 0 &&
          indexOf(track, "ensure-colour-track") < composition,
          "ensure_colour_track=" + std::to_string(indexOf(track, "ensure-colour-track")) +
          " composition=" + std::to_string(composition));
    check("colour-track-on-frame-reports-active",
          track.colourTrackActive && track.colourTrackWasEnabled,
          "active=" + std::to_string(track.colourTrackActive) + " was_enabled=" +
          std::to_string(track.colourTrackWasEnabled));
    check("colour-track-off-frame-dispatches-nothing-and-stays-inactive",
          indexOf(trackOff, "colour-track-stats") < 0 && indexOf(trackOff, "colour-track-track") < 0 &&
          indexOf(trackOff, "colour-track-apply") < 0 && indexOf(trackOff, "ensure-colour-track") < 0 &&
          !trackOff.colourTrackActive && !trackOff.colourTrackWasEnabled,
          "stats=" + std::to_string(indexOf(trackOff, "colour-track-stats")) + " apply=" +
          std::to_string(indexOf(trackOff, "colour-track-apply")) + " ensure=" +
          std::to_string(indexOf(trackOff, "ensure-colour-track")) + " active=" +
          std::to_string(trackOff.colourTrackActive));
    check("colour-track-off-frame-keeps-the-composition-output-as-the-colour",
          trackOff.colorEnd == kRecoveryOutput0,
          end(trackOff) + " expected color=" + ResName(kRecoveryOutput0));

    h.m_postFlickWidth = 64; h.m_postFlickHeight = 64;  // a previous resolution, not the current one
    run(true, false);
    const Frame& mismatch = frames[6];
    check("resolution-mismatch-cannot-leave-the-flag-set",
          !mismatch.flagEnd && !find(mismatch, "post-flick-apply") &&
          std::none_of(mismatch.records.begin(), mismatch.records.end(),
                       [](const Record& record) { return record.color == kPostFlickOutput; }),
          end(mismatch) + " post_flick_apply=" + (find(mismatch, "post-flick-apply") ? "present" : "absent"));
    h.m_postFlickWidth = 0; h.m_postFlickHeight = 0;    // SetMaxRenderSize releases the size-bound textures
    const XMFLOAT4 renderSize = desc.DstTexSize;
    desc.DstTexSize = XMFLOAT4(0, 0, 0, 0);
    run(true, false);
    const Frame& zero = frames[7];
    check("zero-render-size-cannot-leave-the-flag-set",
          !zero.flagEnd && !find(zero, "post-flick-apply") &&
          std::none_of(zero.records.begin(), zero.records.end(),
                       [](const Record& record) { return record.color == kPostFlickOutput; }),
          end(zero) + " post_flick_apply=" + (find(zero, "post-flick-apply") ? "present" : "absent"));
    desc.DstTexSize = renderSize;
    h.ensurePostFlickSucceeds = false;                  // injected failure on the real early-return path
    run(true, false);
    const Frame& failed = frames[8];
    check("ensure-post-flick-failure-cannot-leave-the-flag-set",
          !failed.flagEnd && !find(failed, "post-flick-apply") && find(failed, "ensure-post-flick") &&
          std::none_of(failed.records.begin(), failed.records.end(),
                       [](const Record& record) { return record.color == kPostFlickOutput; }),
          end(failed) + " ensure_post_flick=" + (find(failed, "ensure-post-flick") ? "called" : "not called"));
    h.ensurePostFlickSucceeds = true;

    // The recorded call order, so the log shows the production sequence the invariants
    // above are read from rather than only the verdicts.
    for (size_t index = 0; index < frames.size(); ++index)
    {
        std::cout << "TRACE\tframe" << (index + 1) << "\t";
        for (const auto& record : frames[index].records) std::cout << record.site << ' ';
        std::cout << "| end_flag=" << (frames[index].flagEnd ? 1 : 0)
                  << " end_color=" << ResName(frames[index].colorEnd) << '\n';
    }

    std::cout << "HARNESS\tframes=" << frames.size() << "\tfailures=" << failures << '\n';
    return failures ? 1 : 0;
}
'''


def parse(output):
    """CHECK lines from one harness run, plus the exit code."""
    checks = []
    for line in output.splitlines():
        if line.startswith('CHECK\t'):
            _, name, verdict, detail = line.split('\t', 3)
            checks.append(dict(name=name, passed=verdict == 'PASS', detail=detail))
    return checks


def build_and_run(name, methods, output):
    source = output / f'fsrd_postflick_order_{name}.cpp'
    source.write_text(PREAMBLE.replace('___POSTFLICK_HEADER___', POSTFLICK_HEADER.as_posix())
                      .replace('___COLOUR_TRACK_HEADER___', COLOUR_TRACK_HEADER.as_posix())
                      + '\n'.join(methods) + '\n};\n' + DISPATCH_DEFINITION + MAIN, encoding='utf-8')
    exe = output / f'fsrd_postflick_order_{name}.exe'
    compile_cpp(source, exe)
    process = subprocess.run([str(exe)], capture_output=True, text=True)
    print(f'--- {name} harness (exit {process.returncode}) ---', flush=True)
    print(process.stdout, end='', flush=True)
    if process.stderr:
        print(process.stderr, end='', flush=True)
    return dict(exit_code=process.returncode, checks=parse(process.stdout),
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())


def historical_mutant(methods):
    """The pre-7ac28ffd9 ownership: the clear lived inside DispatchPostFlick, after the
    in-place flat-detail pass. The mutation is applied to the extracted copy only."""
    composition, post_flick = methods[1], methods[3]
    if composition.count(FRAME_START_CLEAR) != 1:
        raise RuntimeError('the frame-start clear anchor moved in DispatchComposition; '
                           're-derive the historical mutant before trusting the power check')
    composition = composition.replace(FRAME_START_CLEAR, '')
    brace = post_flick.index('{') + 1
    post_flick = post_flick[:brace] + '\n        m_postFlickActive = false;' + post_flick[brace:]
    return (methods[0], composition, methods[2], post_flick) + tuple(methods[4:])


def frame_end_mutant(methods):
    """The clear moved to the end of the extracted body: every frame starts with the
    previous frame's flag and the caller never sees the post-flick texture."""
    composition = methods[1]
    if composition.count(FRAME_START_CLEAR) != 1:
        raise RuntimeError('the frame-start clear anchor moved in DispatchComposition; '
                           're-derive the frame-end mutant before trusting the power check')
    composition = composition.replace(FRAME_START_CLEAR, '')
    closing = composition.rindex('}')
    composition = composition[:closing] + '        m_postFlickActive = false;\n    ' + composition[closing:]
    return (methods[0], composition, methods[2], methods[3]) + tuple(methods[4:])


# Each mutant must be caught by at least these invariants. The first reproduces the bug
# the fix removed (flat detail targeting the previous post-flick texture, then the OFF
# frame inheriting the flag); the second is the task's "clear at the end of the body"
# variant, which drops the pass output from what the caller sees.
MUTANTS = (
    ('historical-ownership', historical_mutant,
     ('on-frame-2-flat-detail-apply-targets-the-recovery-output',
      'off-frame-never-returns-the-post-flick-texture')),
    ('frame-end-clear', frame_end_mutant,
     ('on-frame-1-frame-end-is-the-post-flick-texture',
      'on-frame-after-off-resumes')),
)


def run():
    # The reported hash is of the file as it stands (CRLF included, so it matches any
    # hashing tool); the extraction and the mutant anchors work on LF-normalised text.
    production_bytes = PREPROCESSOR.read_bytes()
    production = production_bytes.decode('utf-8').replace('\r\n', '\n')
    methods = tuple(method(production, signature) for signature in SIGNATURES)
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT',
                                 Path(os.environ.get('TEMP', 'F:/FSRD/tmp')) / 'fsrd_postflick_order'))
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('FSRD_CPP_CACHE', str(output / 'cpp_cache'))
    only = os.environ.get('FSRD_POSTFLICK_ORDER_MUTANT', '')

    report = dict(
        task='24-glass-hfix', test='post-flick dispatch order',
        production=PREPROCESSOR.relative_to(ROOT).as_posix(),
        production_sha256=hashlib.sha256(production_bytes).hexdigest(),
        extracted_sha256=hashlib.sha256('\n'.join(methods).encode('utf-8')).hexdigest(),
        mutants={name: dict(must_fail=list(expected)) for name, _, expected in MUTANTS},
        checks=[], passed=False)

    selected = [(name, transform, expected) for name, transform, expected in MUTANTS
                if only in ('', '1', name)]
    if only and only != '1' and not selected:
        raise SystemExit(f'unknown FSRD_POSTFLICK_ORDER_MUTANT={only!r}; '
                         f'expected one of {[name for name, _, _ in MUTANTS]}')

    if not only:
        report['production_run'] = build_and_run('production', methods, output)
        report['checks'] = report['production_run']['checks']

    caught = {}
    for name, transform, expected in selected:
        run_result = build_and_run(name, transform(methods), output)
        failed = [check['name'] for check in run_result['checks'] if not check['passed']]
        run_result['failed_checks'] = failed
        run_result['must_fail'] = list(expected)
        run_result['caught'] = all(check in failed for check in expected) and bool(failed)
        report['mutants'][name].update(run_result)
        caught[name] = run_result

    # Mutant-only mode is the explicit "prove it has power" run: the harness must fail
    # (exit 1) and the invariants that catch it are printed as FAIL lines. A mutant that
    # passes every invariant means the test has no power, and that is the error.
    if only:
        name = selected[0][0]
        run_result = caught[name]
        report['checks'] = run_result['checks']
        report['passed'] = not run_result['caught']  # the harness verdict, not the power claim
        print(json.dumps(report, indent=2), flush=True)
        assert run_result['caught'], f'mutant {name} passed every invariant; the test has no power'
        print(f'mutant {name}: caught by {len(run_result["failed_checks"])} invariants '
              f'(harness exit {run_result["exit_code"]})', flush=True)
        return

    # Default: the production harness must pass every invariant and every mutant must be
    # caught by its expected invariants, so the test proves its power on every run.
    report['passed'] = (all(check['passed'] for check in report['checks']) and
                        all(run_result['caught'] for run_result in caught.values()))
    print(json.dumps(report, indent=2), flush=True)
    if not all(check['passed'] for check in report['checks']):
        raise AssertionError('invariant failed: ' + ', '.join(
            check['name'] for check in report['checks'] if not check['passed']))
    for name, run_result in caught.items():
        assert run_result['caught'], \
            f'the {name} mutant was not caught by {run_result["must_fail"]}; ' \
            f'it failed {run_result["failed_checks"]}'


if __name__ == '__main__':
    run()
