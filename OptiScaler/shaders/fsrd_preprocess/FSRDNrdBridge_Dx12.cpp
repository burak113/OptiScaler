#include "pch.h"
#include <cstring>
#include "misc/NrdBridgePerf_Dx12.h"
#include "misc/NrdBridgeStagePerf_Dx12.h"
#include "FSRDNrdBridge_Dx12.h"
#include "FSRDNrdDiscovery.h"
#include "FSRDNrdBridgePass_Dx12.h"
#include "FSRDNrdNativeTemporalConstants_Dx12.h"
#include "FSRDNrdNativeMaterialCapture_Dx12.h"
#include "FSRDNrdNativeMaterialStateWitness.h"
#include "FSRDNrdBridgeRR_Dx12.h"
#include "FSRDNrdRawSignals_Dx12.h"
#include "FSRDGameTraceSession.h"
#include "Config.h"
#include "Logger.h"
#include "Util.h"
#include "hooks/D3D12_Hooks.h"
#include "hooks/Streamline_Hooks.h"
#include "resource_tracking/ResTrack_dx12.h"
#include "misc/NrdBridgeLifetime_Dx12.h"
#include "misc/NrdBridgeBirth_Dx12.h"
#include "misc/NrdBridgeOwned_Dx12.h"
#include "misc/RecordedComputeLease_Dx12.h"
#include "misc/NrdBridgeDevice_Dx12.h"
#include "misc/NrdBridgeDescriptorAdmission_Dx12.h"
#include <atomic>
#include <mutex>
#include <optional>
#include <sstream>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <cctype>

namespace NrdBridge
{
namespace
{
enum class SubmissionPhase : uint8_t { Recorded, Submitting, FencePublished, Poisoned };
struct NativeDebugImageOrder;
struct RecordingToken
{
    std::atomic<bool> submitted {false}, outputCommitted {false}, abandoned {false};
    // Once a title history pass is omitted, this exact recording must commit RR.
    // These latches outlive Service, runtime toggles and later Recon transactions.
    std::atomic<bool> commitRequired {false}, skipInvalidated {false}, submissionRetained {false};
    std::atomic<const char*> invalidationGate {nullptr}; // Static diagnostic labels only.
    std::atomic<SubmissionPhase> phase {SubmissionPhase::Recorded};
    std::mutex publicationMutex;
    RecordedComputeLease::FencePointPtr completion;
    uint64_t submissionId = 0;
    std::shared_ptr<NativeDebugImageOrder> imageOrder; // Allocated only by native-debug capture.
    NrdBridgeStagePerf::Sample stages {};
    bool needsStageSamples = false; // Stamped under gMutex; writes serialize with gInjectionMutex.
};
struct NativeDebugImageOrder
{
    std::mutex mutex;
    std::shared_ptr<RecordingToken> presentation;
};
struct HistoryDomain
{
    ConversionPass conversion;
    NativeTemporalCapture nativeTemporalCapture;
    RawSignalSnapshotPass rawSignals;
    RRWrapper rr;
    RRRecordedOutputLease latestOwned; // Only accessed under injection serialization.
    uint64_t resourceGeneration = 0, id = 0, resetRevision = 0;
    bool nativeContract = false;
    uint32_t semanticChain = 0, width = 0, height = 0, viewport = 0;
    bool materialGuidesKnown = false, materialGuidesUsed = false;
    std::shared_ptr<RecordingToken> latestRecording; // CPU recording order, under gInjectionMutex.
    std::atomic<bool> uncertain {false}, discardPending {false};
    std::mutex submissionMutex;
    RecordedComputeLease::FencePointPtr completion;
    uint64_t latestSubmissionId = 0;
    bool pendingSubmission = false;
};
struct NativeDebugSource
{
    RRWrapperNativeDebugOutputSnapshot image;
    std::shared_ptr<HistoryDomain> history;
    std::shared_ptr<RecordingToken> recording;
    std::shared_ptr<NativeDebugImageOrder> imageOrder;
    RRSettings settings {};
    uint64_t serial = 0, generation = 0, consumer = 0;
};
struct NativeConstantProof
{
    FrameSurvey::ComputeBindings bindings;
    FrameSurvey::BoundConstantBinding constant;
    bool pixel = false;
};
struct NativeCommitProof
{
    // Written only while recording under gInjectionMutex; CLOSED native lists
    // are immutable by the legal D3D contract. No Service/ListState ownership.
    std::vector<FrameSurvey::TextureBindingWitness> textures;
    std::array<NativeConstantProof,3> constants;
    std::array<FrameSurvey::PipelineShaderIdentity,20> pipelines;
    std::array<FrameSurvey::IndirectSignatureInfo,20> signatures;
    std::array<FrameSurvey::RecordedRenderTargets,36> rasterOutputs;
    size_t constantCount = 0, pipelineCount = 0, signatureCount = 0, rasterOutputCount = 0;
    std::weak_ptr<RecordedComputeLease::Recording> recording;
    NrdBridgeBirth::Token listBirth;
    uint64_t recordingId = 0;
    std::atomic<bool> sealed {false};
};
struct RecordingOwnership
{
    std::shared_ptr<HistoryDomain> history;
    std::shared_ptr<RecordingToken> token;
    std::shared_ptr<NativeCommitProof> nativeProof; // Metadata only, survives Reset/Service destruction.
};
struct ResourceIdentity
{
    void* address = nullptr;
    NrdBridgeBirth::Token birth;
    bool operator==(const ResourceIdentity&) const noexcept = default;
};
struct ResourceIdentityHash
{
    size_t operator()(const ResourceIdentity& identity) const noexcept
    { return std::hash<void*>{}(identity.address) ^ (std::hash<const void*>{}(identity.birth.get()) << 1); }
};
struct PipelineIdentity { Role role = Role::None; NrdBridgeBirth::Token birth; bool nativeContract = false; };
struct InterveningPipeline { int profile = -1; NrdBridgeBirth::Token birth; bool testing = false; };
constexpr std::array<const char*,9> NativeInterveningCS {{
    "f50f483dc26a369be13f71426a7212fc37c88511daed5ef43aad6efc71e2c6ae",
    "13a3e4f687ed0da0d83fafa72b1d45c253f26e83638da400e92a03a5d80e6841",
    "3134fb986fbd2ac518859a670a2faf82cc800dabf74da2f37d4aee11bcd34725",
    "ab6deb230e344ef0badfcd29a4c10fda4da50056e721884eb9f08563c0ed24a1",
    "f854724693c3cdb10c513bf7368ec5ba479e34ace37ff90bf51da40352056025",
    "e99a3ca6fb1b04f16934c1dc2cababd31718b5503575fbac7a387b77e87b4aec",
    "9138cd1d0d5d2a53c3c260aaebbb00618706a17eed29f7433ee161e5db1c030f",
    "111e21909ad0260f6b2d86b5706649983ba21995941f18f349956460926d8fe2",
    "ba416a36c394da372ea9e1408966360411a65369aca3ad6d81537d015b07ae36"}};
constexpr const char* NativeInterveningAc7f="ac7f46728fe9cfd07bfe11d934d3ce09363289cc1689a2aa7d8aa99ac3bac7b5";
constexpr std::array<const char*,3> NativeInterveningPS {{
    "b86e70d1d6445513ca5fd3b903c195428c292d78e3423df65b852167c07e3d2f",
    "60b155558e409c232051ca645b23aab89a143007ba57ec3dc25a511ab2fd5c88",
    "0e5b5f0f3219b961fcb715b056f1d9fa81125db7a78c9e47efaefe9675823703"}};
constexpr std::array<const char*,3> NativeInterveningVS {{
    "5406cf74f00ed29c9b1730142efb086d4b9860c92d855f70a730430c2be953cc",
    "b696ecc34fe5f3f2f0794e5bbcaa33456020099d75b115dd3a1ed5c43d03b810",
    "487033c28340b5eae2b77aa327420e52ade4e802c5eb7ad04eb21a32303f348f"}};
int InterveningComputeProfile(const char* hash) noexcept
{
    if (!hash) return -1; const std::string_view value(hash);
    if (value==NativeInterveningAc7f) return 0;
    return std::find_if(NativeInterveningCS.begin(),NativeInterveningCS.end(),[&](const char* candidate){return value==candidate;})!=NativeInterveningCS.end()?1:-1;
}
int InterveningGraphicsProfile(const char* hash) noexcept
{
    if (!hash) return -1;
    for(size_t index=0;index<NativeInterveningPS.size();++index)if(std::string_view(hash)==NativeInterveningPS[index])return int(index)+2;
    return -1;
}
struct MaterialSnapshot
{
    NativeMaterialCapture::SnapshotLease snapshot;
    ID3D12Resource* normal = nullptr;
    NrdBridgeBirth::Token normalBirth;
    uint64_t serial = 0, normalGeneration = 0;
};
// Two independent required transactions may coexist in one native recording.
// A later B commit can never satisfy or replace an incomplete A token.
struct NativeTransaction
{
    uint32_t chain = 0;
    uint64_t frame = 0, serial = 0, resetRevision = 0;
    NrdBridgeBirth::Token birth;
    std::shared_ptr<HistoryDomain> history;
    std::shared_ptr<RecordingToken> recording;
    std::shared_ptr<RecordingOwnership> ownership;
    RawSignalLease raw;
    NativeTemporalCapture::SnapshotLease temporalConstants;
    NativeMaterialCapture::SnapshotLease material;
    ConvertedResources inputs {};
    FrameParameters parameters {};
    SLConstantsSnapshot streamline {};
    RRSettings settings {};
    bool cameraProjectedDepthDelta = false;
    RRRecordedOutputLease owned;
    std::array<FrameSurvey::BoundResource,4> sources {};
    FrameSurvey::BoundResource motion {};
    std::array<FrameSurvey::BoundResource,2> targets {};
    NativeMaterialStateWitness targetStates;
    FSRDGameTraceSession::BridgeFrameToken trace;
    FSRDGameTraceSession::BridgeIdentity traceIdentity {};
    std::array<FSRDGameTraceSession::BridgeSkippedDispatch,64> skipped {};
    uint32_t skipCount = 0;
    std::atomic<bool> geometryReady {false}, motionReady {false}, committed {false}, invalidated {false};
};
struct ListState
{
    Role role = Role::None;
    bool nativeContract = false, rrOnlyTransaction = false, ownedReady = false;
    bool currentDispatchSuppressed = false, earlyTemporalObserved = false, chainB = false, firstPrePass = false;
    NrdBridgeBirth::Token birth, pipelineBirth;
    ChainDiscovery chain;
    std::array<ID3D12Resource*,25> indexedReferences {};
    std::array<NrdBridgeBirth::Token,25> indexedBirths {};
    bool followingRecon = false, converted = false, motionReady = false, temporal = false, atrous = false, nrdList = false;
    std::shared_ptr<RecordingToken> recording;
    std::shared_ptr<HistoryDomain> history;
    std::shared_ptr<RecordingOwnership> ownership;
    RRRecordedOutputLease ownedOutput;
    uint64_t ownedContext = 0, ownedRecording = 0;
    SLConstantsSnapshot streamline {};
    FrameSurvey::BoundResource nativeFirstDepth {};
    std::array<std::shared_ptr<NativeTransaction>,2> native;
    uint32_t nativeChain = 0;
    bool nativeReconPrepared = false, graphicsConsumerCandidate = false;
    ID3D12PipelineState* graphicsConsumer = nullptr;
    NrdBridgeBirth::Token graphicsConsumerBirth;
    bool harmlessPipeline = false;
    ID3D12PipelineState* currentPipeline = nullptr;
    InterveningPipeline intervening;
    uint64_t frame = 0, generation = 0, resetSerial = 0;
    FrameParameters parameters {};
    ConvertedResources inputs {};
    NativeTemporalCapture::SnapshotLease nativeMotionSnapshot;
    MaterialSnapshot pendingMaterial, material;
    NativeMaterialStateWitness materialStates;
    uint64_t materialIdentityRevision = 0;
    DebugMode debug = DebugMode::Off;
    std::array<std::weak_ptr<RecordingToken>,4> debugPresentations {};
};
struct Service
{
    Microsoft::WRL::ComPtr<ID3D12Device> device;
    std::unordered_map<ID3D12PipelineState*,PipelineIdentity> roles;
    std::unordered_map<ID3D12PipelineState*,NrdBridgeBirth::Token> graphicsConsumers;
    std::unordered_map<ID3D12PipelineState*,NrdBridgeBirth::Token> harmlessPipelines;
    std::unordered_map<ID3D12PipelineState*,InterveningPipeline> interveningPipelines;
    std::unordered_map<ID3D12GraphicsCommandList*,ListState> lists;
    std::unordered_map<ResourceIdentity,std::unordered_set<ID3D12GraphicsCommandList*>,ResourceIdentityHash> chainUsers;
    std::unordered_set<ID3D12GraphicsCommandList*> followingChains;
    DiscoveryCache cache;
    NativeMaterialCapture nativeMaterialCapture;
    NativeMaterialIdentityCache materialIdentities; // Fixed weak pairs, never cross-recording states.
    std::shared_ptr<RRRecoveryFamily> recoveryFamily; // Stable across all temporal-domain replacements.
    std::array<NrdBridgeBirth::Token,9> cacheBirths {};
    std::shared_ptr<HistoryDomain> history;
    std::array<std::shared_ptr<HistoryDomain>,2> nativeHistories;
    std::unique_ptr<FSRDGameTraceSession> trace; // Lazy, USER-armed; no default/OFF workers or allocation.
    std::vector<std::weak_ptr<HistoryDomain>> historyDomains;
    uint64_t nextDomain = 0, requestedResetRevision = 1;
    Status status;
    RRSettings rrSettings {};
    RRSettingsState rrSettingsState {};
    std::array<std::shared_ptr<NativeDebugSource>,4> nativeDebugSources {};
    uint32_t nextNativeDebugSource = 0, nativeDebugLastLag = UINT32_MAX;
    std::string nativeDebugError;
    bool cameraProjectedDepthDelta = false, nativeContractSeen = false;
    ID3D12Resource* taggedMotion = nullptr; NrdBridgeBirth::Token taggedMotionBirth;
    ID3D12GraphicsCommandList* pendingList = nullptr;
    uint64_t frame = 0, resetSerial = 1, cancellationSerial = 1, appliedReset = 0, lastLog = 0, activeFrame = 0;
    uint32_t windowPresents = 0, retryPresents = 0, attempts = 0, failures = 0, lastSLFrame = UINT32_MAX;
    bool window = false, windowSawRecon = false, everRecon = false, observedRecon = false, conventionsLogged = false, discardRequested = false;
};
NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Coordinator> gMutex;
std::mutex gInjectionMutex, gWindowMutex;
NrdBridgeStagePerf::Collector gStageCollector; // One process-lifetime window, including device recreation.
std::atomic<bool> gStagesStopped {false};
std::shared_ptr<Service> gService;
std::atomic<bool> gInstalled {false}, gRuntime {false};
std::atomic<int> gStartupSelection {-1}; // -1 unconfigured, -2 configuring, 0 OFF/failed, 1 enabled.
std::atomic<const char*> gStartupFailure {nullptr};
std::string gUnavailableReason;
std::atomic<DebugMode> gDebug {DebugMode::Off};
std::atomic<bool> gNativeDebug {false};
std::atomic<bool> gNativeMaterials {false};
std::atomic<bool> gNativeTransactions {false};
thread_local ID3D12GraphicsCommandList* gDispatchCandidate = nullptr; // Set by the immediately preceding public BeforeDispatch.
// Lock-free "may be relevant" filters for the title's hottest calls (SetPipelineState,
// Dispatch, ResourceBarrier). Every pointer that is ever inserted into the Service's
// role/consumer/intervening maps, list map or material identity cache is also inserted
// here, before or under the same gMutex section. Entries are never removed: a stale or
// reused pointer only sends that call down the existing locked path. A full table
// answers "may contain" for everything, which is the previous behaviour.
template<size_t Capacity> class PointerFilter
{
    static_assert((Capacity & (Capacity-1)) == 0);
    std::array<std::atomic<uintptr_t>,Capacity> slots_ {};
    std::atomic<bool> saturated_ {false};
    static size_t Start(uintptr_t value) noexcept
    {
        uint64_t x = uint64_t(value) >> 4; x ^= x >> 33; x *= 0xff51afd7ed558ccdull; x ^= x >> 33;
        return size_t(x) & (Capacity-1);
    }
  public:
    void Insert(const void* pointer) noexcept
    {
        const auto value = reinterpret_cast<uintptr_t>(pointer); if (!value) return;
        for (size_t probe=0, index=Start(value); probe<Capacity; ++probe, index=(index+1)&(Capacity-1))
        {
            uintptr_t current = slots_[index].load(std::memory_order_acquire);
            if (current == value) return;
            if (!current && slots_[index].compare_exchange_strong(current,value,std::memory_order_acq_rel)) return;
            if (current == value) return;
        }
        saturated_.store(true,std::memory_order_release);
    }
    bool MayContain(const void* pointer) const noexcept
    {
        if (saturated_.load(std::memory_order_acquire)) return true;
        const auto value = reinterpret_cast<uintptr_t>(pointer); if (!value) return false;
        for (size_t probe=0, index=Start(value); probe<Capacity; ++probe, index=(index+1)&(Capacity-1))
        {
            const uintptr_t current = slots_[index].load(std::memory_order_acquire);
            if (current == value) return true;
            if (!current) return false;
        }
        return true;
    }
};
PointerFilter<4096> gRelevantPipelines, gTrackedLists;
PointerFilter<1024> gMaterialResources;
bool MaterialTransitionMayMatch(UINT count, const D3D12_RESOURCE_BARRIER* barriers) noexcept
{
    for (UINT index=0;index<count;++index)
        if (barriers[index].Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION &&
            gMaterialResources.MayContain(barriers[index].Transition.pResource)) return true;
    return false;
}
// The supported full-hash profile uses owned raw A/B inputs and required output
// admission, including checkerboard and intervening native binding witnesses.
constexpr bool kNativeElisionContractReady = true;
#ifdef FSRD_NRD_BRIDGE_TEST
std::atomic<bool> gNativeElisionForTesting {false};
#endif
bool NativeElisionReady() noexcept
{
#ifdef FSRD_NRD_BRIDGE_TEST
    return kNativeElisionContractReady || gNativeElisionForTesting.load(std::memory_order_relaxed);
#else
    return kNativeElisionContractReady;
#endif
}
#ifdef FSRD_NRD_BRIDGE_TEST
void (*gBeforeConversionLockForTesting)() = nullptr;
void (*gBeforeBindingWindowPublishForTesting)() = nullptr;
void (*gBeforeOutputLockForTesting)() = nullptr;
#endif

NrdBridgeStagePerf::Sample* StageSample(const std::shared_ptr<RecordingToken>& recording) noexcept
{
    return recording && recording->needsStageSamples && !gStagesStopped.load(std::memory_order_acquire)
        ? &recording->stages : nullptr;
}
void MergeStageSamples(NrdBridgeStagePerf::Sample& destination, const NrdBridgeStagePerf::Sample& source) noexcept
{
    if (!destination.Enabled()) return;
    for (size_t index=0;index<NrdBridgeStagePerf::StageCount;++index)
    {
        auto& target = destination.stages[index]; const auto& value = source.stages[index];
        if (target.invalid) continue;
        if (value.invalid || value.ticks > UINT64_MAX-target.ticks || value.events > UINT64_MAX-target.events)
        { target.invalid = true; continue; }
        target.ticks += value.ticks; target.events += value.events;
    }
}
void ReportStages(const NrdBridgeStagePerf::Report& report) noexcept
{
    try
    {
        std::ostringstream text; text.setf(std::ios::fixed); text.precision(3);
        text << "frames=" << report.frames << " SL_frame=" << report.firstSL << ".." << report.lastSL
             << " window=first100_successful_unique_Consumer_output_recordings scope=CPU_elapsed_not_GPU_or_display_FPS"
             << " time_valid=" << bool(report.frequency) << " overlapping_spans_do_not_sum=1"
             << " consumer_physical_spans=metadata+injection recon_prepare_scope=reset+settings+SL+conversion_initialize+retain"
             << " provider_scope=FfxApiProxy_D3D12_Dispatch output_commit_scope=Context_Commit_CPU";
        for (size_t index=0;index<NrdBridgeStagePerf::StageCount;++index)
        {
            const auto& value = report.stages[index];
            text << ' ' << NrdBridgeStagePerf::StageName(NrdBridgeStagePerf::Stage(index))
                 << "{samples=" << value.observedSamples << ",events=" << value.events
                 << ",mean_ms=" << value.MeanMs(report.frequency) << ",max_ms=" << value.MaxMs(report.frequency)
                 << ",p95_ms=" << value.P95Ms(report.frequency) << ",invalid=" << value.invalidSamples
                 << ",saturated=" << value.saturated << '}';
        }
        LOG_INFO("[NRD_BRIDGE] stages {}",text.str());
        FlushLogger();
    } catch (...) {}
}
void CompleteStageSample(uint32_t slFrame, const NrdBridgeStagePerf::Sample& complete, bool committed) noexcept
{
    try
    {
        NrdBridgeStagePerf::Report report {}; bool ready = false;
        {
            std::scoped_lock lock(gMutex);
            ready = gStageCollector.AcceptSuccessful(slFrame,complete,committed,report);
            if (ready) gStagesStopped.store(true,std::memory_order_release);
        }
        // The completed sample is a local POD copy. No host/injection/physical lock,
        // native pointer or recording owner is borrowed by the reporter.
        if (ready) gStageCollector.Publish(report,ReportStages);
    } catch (...) {} // Diagnostic failure cannot change a committed title recording.
}

// The wrapper caches its measured conventions after the first valid camera snapshot.
template<class Wrapper> std::string Conventions(const Wrapper& wrapper)
{
    if constexpr (requires { wrapper.CameraConventionDescription(); }) return wrapper.CameraConventionDescription();
    return {};
}
struct InjectionScope
{
    ID3D12GraphicsCommandList* list;
    bool previousTracking;
    FrameSurvey::ScopedInternal survey;
    explicit InjectionScope(ID3D12GraphicsCommandList* cmd)
        : list(cmd), previousTracking(D3D12Hooks::RootSignatureTrackingEnabled())
    { D3D12Hooks::SetRootSignatureTracking(false); }
    ~InjectionScope() { D3D12Hooks::RestoreRoot(list); D3D12Hooks::SetRootSignatureTracking(previousTracking); }
};
void PublishBindingWindow()
{
#ifdef FSRD_NRD_BRIDGE_TEST
    if (gBeforeBindingWindowPublishForTesting) gBeforeBindingWindowPublishForTesting();
#endif
    std::scoped_lock publication(gWindowMutex);
    bool desired = false;
    { std::scoped_lock lock(gMutex); desired = gService && gInstalled.load(std::memory_order_relaxed) &&
        gRuntime.load(std::memory_order_relaxed) && gService->window; }
    FrameSurvey::SetBindingWindow(desired);
}
void SeedForWindow(ID3D12GraphicsCommandList* cmd)
{
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
    FrameSurvey::ComputeBindings bindings;
    if (D3D12Hooks::GetComputeBindingsForBridge(cmd,bindings)) FrameSurvey::SeedComputeBindings(cmd,bindings);
}
void RequireRestoreFlags()
{
    auto* config = Config::Instance();
    if (!config->RestoreComputeSignature.value_or_default()) config->RestoreComputeSignature.set_volatile_value(true);
    if (!config->ExtendedStateRestore.value_or_default()) config->ExtendedStateRestore.set_volatile_value(true);
}
template<class Configuration> RRSettings ReadStartupSettings(const Configuration& config)
{
    RRSettings settings;
    if constexpr (requires { config.FfxDenoiserNrdBridgeUseCustomRR; config.FfxDenoiserUseAmdDefaults;
        config.FfxDenoiserCrossBlNormStr; config.FfxDenoiserStabilityBias; config.FfxDenoiserMaxRadiance;
        config.FfxDenoiserRadianceClip; config.FfxDenoiserGaussKernRelax; config.FfxDenoiserDisocThreshold; })
        if (config.FfxDenoiserNrdBridgeUseCustomRR.value_or_default() && !config.FfxDenoiserUseAmdDefaults.value_or_default())
        {
            settings.overrideMask = 0x3fu;
            settings.values = {config.FfxDenoiserCrossBlNormStr.value_or_default(), config.FfxDenoiserStabilityBias.value_or_default(),
                config.FfxDenoiserMaxRadiance.value_or_default(), config.FfxDenoiserRadianceClip.value_or_default(),
                config.FfxDenoiserGaussKernRelax.value_or_default(), config.FfxDenoiserDisocThreshold.value_or_default(),0.0f,0.0f};
        }
    if constexpr (requires { config.FfxDenoiserNrdBridgeNativeDebugView; config.FfxDenoiserNrdBridgeNativeDebugViewport; })
    {
        settings.nativeDebugView = config.FfxDenoiserNrdBridgeNativeDebugView.value_or_default();
        settings.nativeDebugViewport = uint32_t(config.FfxDenoiserNrdBridgeNativeDebugViewport.value_or_default());
    }
    if constexpr (requires { config.FfxDenoiserNrdBridgeMaterialIDs; })
        settings.preserveNativeMaterialIDs = config.FfxDenoiserNrdBridgeMaterialIDs.value_or_default();
    if constexpr (requires { config.FfxDenoiserNrdBridgeNativeSpecularBlend; })
        settings.nativeSpecularBlend = NormalizeNativeSpecularBlend(config.FfxDenoiserNrdBridgeNativeSpecularBlend.value_or_default());
    if constexpr (requires { config.FfxDenoiserNrdBridgeNativeMaterialGuides; })
        settings.nativeMaterialGuides = config.FfxDenoiserNrdBridgeNativeMaterialGuides.value_or_default();
    if constexpr (requires { config.FfxDenoiserNrdBridgeNativeTemporalMotion; })
        settings.nativeTemporalMotion = config.FfxDenoiserNrdBridgeNativeTemporalMotion.value_or_default();
    if constexpr (requires { config.FfxDenoiserNrdBridgeLobeRecovery; config.FfxDenoiserNrdBridgeRecoverySpecular;
        config.FfxDenoiserNrdBridgeRecoveryDiffuse; })
    {
        settings.lobeRecovery = config.FfxDenoiserNrdBridgeLobeRecovery.value_or_default();
        settings.recoverySpecular = NormalizeLobeRecoveryStrength(config.FfxDenoiserNrdBridgeRecoverySpecular.value_or_default());
        settings.recoveryDiffuse = NormalizeLobeRecoveryStrength(config.FfxDenoiserNrdBridgeRecoveryDiffuse.value_or_default());
    }
    settings.flatAlbedo = ReadFlatAlbedoSettings(config);
    if constexpr (requires { config.FfxDenoiserNrdBridgeSurfaceValidFill; })
        settings.surfaceValidFill = config.FfxDenoiserNrdBridgeSurfaceValidFill.value_or_default();
    if constexpr (requires { config.FfxDenoiserNrdBridgeLegacyMotionDepth; })
        settings.legacyMotionDepth = config.FfxDenoiserNrdBridgeLegacyMotionDepth.value_or_default();
    return settings;
}
template<class Configuration> bool ReadStartupCameraDepth(const Configuration& config)
{
    if constexpr (requires { config.FfxDenoiserNrdBridgeMotionDepthMode; })
        return config.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default();
    return false;
}
bool BirthMode() noexcept { return NrdBridgeLifetime::ConcurrentReleasesEnabled(); }
bool BirthLive(const NrdBridgeBirth::Token& birth) noexcept
{ return !BirthMode() || (birth && birth->Admissible()); }
bool ListLive(const ListState& list) noexcept
{ return BirthLive(list.birth) && (list.role == Role::None || BirthLive(list.pipelineBirth)); }
bool ChainLive(const ChainDiscovery& chain) noexcept
{
    if (!BirthMode()) return true;
    const auto resources = chain.ReferencedResources(); const auto births = chain.ReferencedResourceBirths();
    for (size_t i=0;i<resources.size();++i) if (resources[i] && !BirthLive(births[i])) return false;
    return true;
}
// Native transactions own a current typed chain; the output-discovery cache is
// diagnostic and may rotate independently while that transaction remains valid.
bool CurrentFrameProfile(const Service& owner, const ListState& list) noexcept
{
    return list.rrOnlyTransaction ? list.chain.Valid() && list.generation == list.frame :
        owner.cache.Valid() && list.generation == owner.cache.Generation();
}
bool SameProfileBirths(const std::array<NrdBridgeBirth::Token,9>& a, const std::array<NrdBridgeBirth::Token,9>& b) noexcept
{
    if (!BirthMode()) return true;
    for (const size_t i : {0u,1u,4u,5u,6u,7u,8u}) if (a[i] != b[i]) return false;
    return true;
}
std::array<NrdBridgeBirth::Token,9> CacheBirths(const ChainDiscovery& chain)
{
    std::array<NrdBridgeBirth::Token,9> result;
    for (size_t i=0;i<result.size();++i) result[i] = chain.Bindings()[i].resourceBirth;
    return result;
}
bool CacheUsesBirth(const Service& owner, void* object, const NrdBridgeBirth::Token& birth) noexcept
{
    if (!owner.cache.Valid()) return false;
    const auto& r = owner.cache.Get();
    const std::array<ID3D12Resource*,9> resources {r.inputSpec,r.inputDiff,r.normals,r.viewDepth,r.reconSpec,r.reconDiff,r.motion,r.outputSpec,r.outputDiff};
    for (size_t i=0;i<resources.size();++i) if (resources[i] == object && owner.cacheBirths[i] == birth) return true;
    return false;
}
Role PipelineRole(const Service& owner, ID3D12PipelineState* pipeline, const NrdBridgeBirth::Token& birth = {})
{
    const auto found = owner.roles.find(pipeline);
    return found == owner.roles.end() || found->second.birth != birth || !BirthLive(birth) ? Role::None : found->second.role;
}
// Caller holds gMutex. The exact address/birth pair prevents delayed old Release
// notifications from removing an already published newborn's reverse references.
void UpdateChainUsers(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list,
                      const std::array<ID3D12Resource*,25>& next, const std::array<NrdBridgeBirth::Token,25>& births)
{
    const auto& prior = list.indexedReferences;
    auto contains = [](const auto& resources,const auto& tokens,void* address,const NrdBridgeBirth::Token& birth) {
        for (size_t i=0;i<resources.size();++i) if (resources[i] == address && tokens[i] == birth) return true;
        return false;
    };
    for (size_t i=0;i<prior.size();++i)
        if (prior[i] && !contains(next,births,prior[i],list.indexedBirths[i]))
            if (const auto found = owner.chainUsers.find({prior[i],list.indexedBirths[i]}); found != owner.chainUsers.end())
            { found->second.erase(cmd); if (found->second.empty()) owner.chainUsers.erase(found); }
    for (size_t i=0;i<next.size();++i)
        if (next[i] && !contains(prior,list.indexedBirths,next[i],births[i])) owner.chainUsers[{next[i],births[i]}].insert(cmd);
    list.indexedReferences = next; list.indexedBirths = births;
}
void RemoveChainUsers(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list)
{ UpdateChainUsers(owner,cmd,list,{},{}); }
void RefreshChainUsers(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list)
{
    std::array<ID3D12Resource*,25> resources {}; std::array<NrdBridgeBirth::Token,25> births {};
    if (list.chain.Valid())
    {
        const auto chainResources = list.chain.ReferencedResources(); const auto chainBirths = list.chain.ReferencedResourceBirths();
        std::copy(chainResources.begin(),chainResources.end(),resources.begin());
        std::copy(chainBirths.begin(),chainBirths.end(),births.begin());
    }
    size_t index = 11;
    for (const auto& stage : list.native)
    {
        if (!stage) { index += 7; continue; }
        auto add = [&](const FrameSurvey::BoundResource& bound) {
            resources[index] = bound.resource; births[index++] = bound.resourceBirth;
        };
        for (const auto& source : stage->sources) add(source);
        add(stage->motion); for (const auto& target : stage->targets) add(target);
    }
    UpdateChainUsers(owner,cmd,list,resources,births);
}
void StopFollowing(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list)
{ list.followingRecon = false; owner.followingChains.erase(cmd); }
bool SameDebugSettings(const RRSettings& a, const RRSettings& b) noexcept
{
    if (a.overrideMask != b.overrideMask || a.nativeDebugView != b.nativeDebugView ||
        a.nativeDebugViewport != b.nativeDebugViewport || a.preserveNativeMaterialIDs != b.preserveNativeMaterialIDs ||
        a.nativeTemporalMotion != b.nativeTemporalMotion || a.nativeMaterialGuides != b.nativeMaterialGuides ||
        a.lobeRecovery != b.lobeRecovery || a.flatAlbedo != b.flatAlbedo || a.recoverySpecular != b.recoverySpecular ||
        a.recoveryDiffuse != b.recoveryDiffuse) return false;
    for (uint32_t i=0;i<8;++i)
        if ((a.overrideMask & (1u << (i == 7 ? 6 : i))) && a.values[i] != b.values[i]) return false;
    return true;
}
bool RequiredOutputComplete(const RecordingToken& recording) noexcept
{
    return !recording.commitRequired.load(std::memory_order_acquire) ||
        (recording.outputCommitted.load(std::memory_order_acquire) &&
         !recording.skipInvalidated.load(std::memory_order_acquire) && !recording.abandoned.load(std::memory_order_acquire));
}
bool AdmitRecordingSubmission(const RecordingToken& recording) noexcept
{
    // An incomplete RR commit is reported to the caller, which forwards the title's
    // own Execute anyway: denying it stalls the game and latches a restart, while
    // forwarding only shows last frame's committed lighting once. Lease lifetime and
    // GPU ordering gates are unaffected and still deny on their own.
    return RequiredOutputComplete(recording);
}
// First 16 occurrences, then every 512th.
bool SoftSubmitLogDue(std::atomic<uint64_t>& counter) noexcept
{
    const auto n = counter.fetch_add(1,std::memory_order_relaxed);
    return n < 16 || n % 512 == 0;
}
std::atomic<uint64_t> gSoftIncompleteSubmissions {0}, gSoftProofSubmissions {0};
bool MandatoryOutputPending(const Service& owner) noexcept
{
    for (const auto& [cmd,list] : owner.lists)
    {
        for (const auto& stage : list.native)
            if (stage && !stage->committed && !stage->invalidated &&
                !stage->recording->skipInvalidated.load(std::memory_order_acquire) &&
                !stage->recording->abandoned.load(std::memory_order_acquire)) return true;
        if (list.rrOnlyTransaction && list.recording && list.recording->commitRequired.load(std::memory_order_acquire) &&
            !list.recording->outputCommitted.load(std::memory_order_acquire) &&
            !list.recording->skipInvalidated.load(std::memory_order_acquire) &&
            !list.recording->abandoned.load(std::memory_order_acquire)) return true;
    }
    return false;
}
void RefreshNativeTransactions(const Service& owner) noexcept
{
    bool pending=false;
    for(const auto& [cmd,list]:owner.lists)
        for(const auto& stage:list.native) pending |= stage && !stage->committed && !stage->invalidated;
    gNativeTransactions.store(pending,std::memory_order_release);
}
void RetireNativeRecording(Service& owner, ListState& list) noexcept
{
    for(const auto& stage:list.native)
        if(stage && !stage->recording->submitted.load(std::memory_order_acquire))
        {
            stage->recording->abandoned.store(true,std::memory_order_release);stage->invalidated=true;
            stage->history->uncertain.store(true,std::memory_order_release);
            stage->history->discardPending.store(true,std::memory_order_release);owner.discardRequested=true;
        }
}
void InvalidateSkippedRecording(ListState& list, const char* gate="recording_invalidated") noexcept
{
    for (const auto& stage : list.native) if (stage && !stage->committed)
    {
        const char* empty=nullptr;stage->recording->invalidationGate.compare_exchange_strong(empty,gate,std::memory_order_acq_rel);
        stage->invalidated = true; stage->recording->skipInvalidated.store(true,std::memory_order_release);
        stage->history->uncertain.store(true,std::memory_order_release);
        stage->history->discardPending.store(true,std::memory_order_release);
    }
    if (!list.recording || !list.recording->commitRequired.load(std::memory_order_acquire) ||
        list.recording->outputCommitted.load(std::memory_order_acquire)) return;
    list.recording->skipInvalidated.store(true,std::memory_order_release);
    if (list.history) { list.history->uncertain.store(true,std::memory_order_release); list.history->discardPending.store(true,std::memory_order_release); }
}
using RetiredDebugSources = std::array<std::shared_ptr<NativeDebugSource>,4>;
// A hook may cancel twice, but cannot publish a new source while it owns gMutex.
// Preserve each detached owner until that hook has left the state lock.
void ClearNativeDebugSources(Service& owner, RetiredDebugSources& retired) noexcept
{
    for (size_t i=0;i<owner.nativeDebugSources.size();++i)
        if (owner.nativeDebugSources[i]) retired[i] = std::move(owner.nativeDebugSources[i]);
    owner.nextNativeDebugSource = 0; owner.nativeDebugLastLag = UINT32_MAX;
}
void AbandonDebugPresentations(ListState& list, std::array<std::shared_ptr<RecordingToken>,4>& retired) noexcept
{
    for (size_t i=0;i<list.debugPresentations.size();++i)
        if ((retired[i] = list.debugPresentations[i].lock()) && !retired[i]->submitted.load(std::memory_order_acquire))
            retired[i]->abandoned.store(true,std::memory_order_release);
    list.debugPresentations = {};
}
void ReplaceList(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list,
                 const NrdBridgeBirth::Token& birth, std::optional<ListState>& retiredList,
                 std::array<std::shared_ptr<RecordingToken>,4>& retiredPresentations, RetiredDebugSources& retired)
{
    AbandonDebugPresentations(list,retiredPresentations);RetireNativeRecording(owner,list);
    const bool unsubmitted = list.recording && !list.recording->submitted.load(std::memory_order_acquire);
    if (unsubmitted && list.history)
    {
        list.recording->abandoned.store(true,std::memory_order_release); list.history->uncertain.store(true,std::memory_order_release);
        list.history->discardPending.store(true,std::memory_order_release); owner.discardRequested = true; ClearNativeDebugSources(owner,retired);
    }
    if (owner.pendingList == cmd) owner.pendingList = nullptr;
    if (owner.activeFrame == list.frame) owner.status.active = false;
    RemoveChainUsers(owner,cmd,list); StopFollowing(owner,cmd,list);
    retiredList.emplace(std::move(list)); list = {}; list.birth = birth; ++owner.resetSerial;
    if (owner.rrSettings.nativeMaterialGuides) owner.materialIdentities.SeedIfChanged(list.materialStates,list.materialIdentityRevision);
    RefreshNativeTransactions(owner);
}
void DropPending(Service& owner, RetiredDebugSources& retired)
{
    owner.pendingList = nullptr; owner.status.active = false; owner.status.nativeMaterialGuidesActive = false; ClearNativeDebugSources(owner,retired);
    for (auto& [cmd,list] : owner.lists)
    {
        InvalidateSkippedRecording(list);
        for (const auto& stage : list.native) if (stage && !stage->committed)
        {
            stage->invalidated = true; stage->recording->skipInvalidated.store(true,std::memory_order_release);
            stage->history->uncertain.store(true,std::memory_order_release);
            stage->history->discardPending.store(true,std::memory_order_release); owner.discardRequested = true;
        }
        list.converted = list.motionReady = list.ownedReady = false;
    }
    ++owner.resetSerial; ++owner.cancellationSerial;RefreshNativeTransactions(owner);
}
void NativeDebugDiagnostic(const std::shared_ptr<Service>& owner, const std::string& reason)
{
    if (!owner) return; bool log = false;
    { std::scoped_lock lock(gMutex); if (gService == owner && owner->nativeDebugError != reason)
      { owner->nativeDebugError = reason; log = true; } }
    if (log) LOG_ERROR("[NRD_BRIDGE] native debug presentation: {}",reason);
}
void NativeDebugOrderingFailure(const std::shared_ptr<Service>& owner)
{
    RetiredDebugSources retired;
    { std::scoped_lock lock(gMutex); if (gService == owner) { DropPending(*owner,retired); owner->window = false;
      owner->status.phase = "Inactive"; owner->status.reason = "Native debug GPU ordering failed; restart the title/device"; } }
    PublishBindingWindow(); NativeDebugDiagnostic(owner,"Native debug GPU ordering failed; restart the title/device");
}
std::shared_ptr<RecordingToken> PresentationTail(const NativeDebugSource& source)
{
    std::scoped_lock lock(source.imageOrder->mutex); return source.imageOrder->presentation;
}
// Retains the AMD debug image a committed RR recording just produced so PresentNativeDebug can
// show it. current() is evaluated under gMutex.
template <class Current>
void RetainNativeDebugSource(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd,
                             const std::shared_ptr<HistoryDomain>& history, const std::shared_ptr<RecordingToken>& recording,
                             uint32_t streamlineFrame, uint32_t width, uint32_t height, uint64_t serial,
                             const Current& current) noexcept
{
    if (!gNativeDebug.load(std::memory_order_relaxed) || !history || !recording) return;
    try
    {
        const auto image = history->rr.GetNativeDebugOutputSnapshot();
        if (!image.resource || !image.owner || image.recording != cmd || image.frameSL != streamlineFrame ||
            image.width != width || image.height != height || image.state != D3D12_RESOURCE_STATE_UNORDERED_ACCESS) return;
        std::shared_ptr<NativeDebugSource> retired;
        auto imageOrder = MakeOwnedShared<NativeDebugImageOrder>();
        auto source = MakeOwnedShared<NativeDebugSource>(); source->image = image; source->history = history; source->imageOrder = imageOrder;
        source->recording = recording; source->serial = serial;
        std::scoped_lock lock(gMutex);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || owner->rrSettings.nativeDebugView < 0 ||
            owner->cancellationSerial != serial || !current(*owner) ||
            !recording->outputCommitted.load(std::memory_order_acquire)) return;
        for (const auto& cached : owner->nativeDebugSources)
            if (cached && cached->image.resource == image.resource && cached->image.owner == image.owner)
                return; // A duplicate getter preserves the image's existing presentation fence tail.
        {
            std::scoped_lock publication(recording->publicationMutex);
            if (recording->imageOrder) source->imageOrder = recording->imageOrder;
            else recording->imageOrder = imageOrder;
        }
        source->generation = owner->cache.Generation();
        source->settings = owner->rrSettings; source->consumer = owner->status.framesBridged;
        auto& slot = owner->nativeDebugSources[owner->nextNativeDebugSource++ % owner->nativeDebugSources.size()];
        retired = std::move(slot); slot = std::move(source);
    }
    catch (...) { try { NativeDebugDiagnostic(owner,"Could not retain a bounded native debug source snapshot"); } catch (...) {} }
}
void CaptureNativeDebugSource(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, const ListState& staged) noexcept
{
    if (staged.debug != DebugMode::Off) return;
    RetainNativeDebugSource(owner,cmd,staged.history,staged.recording,staged.parameters.streamlineFrame,
        staged.inputs.width,staged.inputs.height,staged.resetSerial,[&](const Service& service) { return CurrentFrameProfile(service,staged); });
}
// RR-only native transactions commit through CommitNativeTransaction, not the legacy Consumer;
// without this their debug image was never offered and the AMD view silently stayed off.
// Only chain A is offered: the main signal, and the only chain the legacy path ever showed.
void CaptureNativeDebugSource(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, const NativeTransaction& stage) noexcept
{
    if (stage.chain != 0 || !stage.committed.load(std::memory_order_acquire) || stage.invalidated.load(std::memory_order_acquire)) return;
    RetainNativeDebugSource(owner,cmd,stage.history,stage.recording,stage.parameters.streamlineFrame,
        stage.inputs.width,stage.inputs.height,stage.serial,[](const Service&) { return true; });
}
// Startup or a newer unsubmitted image skip presentation quietly for a frame or two. A persistent
// skip used to hide the view with no trace, so each new reason is logged (rate limited).
std::atomic<const char*> gNativeDebugQuiet {nullptr};
std::atomic<int64_t> gNativeDebugQuietMs {INT64_MIN/2};
void NativeDebugQuiet(const char* reason) noexcept
{
    const auto now = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
    if (gNativeDebugQuiet.load(std::memory_order_relaxed) == reason || now - gNativeDebugQuietMs.load(std::memory_order_relaxed) < 2000) return;
    gNativeDebugQuiet.store(reason,std::memory_order_relaxed); gNativeDebugQuietMs.store(now,std::memory_order_relaxed);
    try { LOG_INFO("[NRD_BRIDGE] native AMD debug not presented: {}",reason); } catch (...) {}
}
bool PublishedToken(const std::shared_ptr<RecordingToken>& token, RecordedComputeLease::FencePointPtr& point, uint64_t& id)
{
    if (!token || token->abandoned.load(std::memory_order_acquire)) return false;
    std::scoped_lock lock(token->publicationMutex);
    if (token->phase.load(std::memory_order_acquire) != SubmissionPhase::FencePublished || !token->completion ||
        !token->completion->IsPublished()) return false;
    point = token->completion; id = token->submissionId; return true;
}
bool OwnsToken(const std::weak_ptr<RecordingToken>& weak, const std::shared_ptr<RecordingToken>& token) noexcept
{ return !weak.owner_before(token) && !token.owner_before(weak); }
struct DebugDependency
{
    std::shared_ptr<RecordingToken> token;
    RecordedComputeLease::FencePointPtr point;
    uint64_t submission = 0;
    bool sameRecording = false;
};
bool DebugDependencyBeforeSubmit(const DebugDependency& dependency, const RecordedComputeLease::SubmissionInfo& info)
{
    if (!dependency.token) return true;
    bool valid = false;
    {
        std::scoped_lock lock(dependency.token->publicationMutex);
        const auto phase = dependency.token->phase.load(std::memory_order_acquire);
        valid = !dependency.token->abandoned.load(std::memory_order_acquire) &&
            (dependency.sameRecording ? (phase == SubmissionPhase::Submitting && dependency.token->submissionId == info.submissionId) :
                (phase == SubmissionPhase::FencePublished && dependency.token->submissionId == dependency.submission &&
                 dependency.token->completion == dependency.point));
    }
    if (!valid) { RecordedComputeLease::DenySubmission(E_FAIL); return false; }
    return dependency.sameRecording || SUCCEEDED(RecordedComputeLease::WaitForFence(info.queue,dependency.point));
}
struct DebugPresentationOwnership
{
    std::shared_ptr<NativeDebugSource> source;
    std::shared_ptr<RecordingToken> token, retiredPresentation;
    DebugDependency producer, previous;
    std::atomic<bool> recorded {false};
};
void IdentityChanged(Service& owner, const char* reason, RetiredDebugSources& retired)
{
    owner.cache.Invalidate(); DropPending(owner,retired); owner.status.active = false;
    owner.status.phase = "Discovering"; owner.status.reason = reason; owner.status.resources.clear();
    owner.status.width = owner.status.height = 0;
}
void StartWindow(Service& owner)
{
    owner.window = true; owner.windowSawRecon = false; owner.windowPresents = 0; owner.retryPresents = 0;
    if (!owner.cache.Valid()) { owner.status.active = false; owner.status.phase = "Discovering"; }
}
void Invalidate(Service& owner, const std::string& reason, RetiredDebugSources& retired)
{
    owner.cache.Invalidate(); DropPending(owner,retired); owner.status.active = false;
    owner.status.reason = reason; owner.status.phase = "Discovering"; owner.status.resources.clear();
    owner.status.width = owner.status.height = 0; owner.attempts = owner.failures = 0;
    if (owner.status.runtimeEnabled) StartWindow(owner);
    else { owner.window = false; owner.status.phase = "Inactive"; }
}
void Failure(const std::shared_ptr<Service>& owner, const std::string& reason)
{
    bool log = false; RetiredDebugSources retired;
    {
        std::scoped_lock lock(gMutex);
        if (gService != owner) return;
        log = owner->status.reason != reason;
        owner->cache.Invalidate(); DropPending(*owner,retired); owner->window = false; owner->retryPresents = 0;
        for (auto& [cmd,list] : owner->lists) list.followingRecon = false;
        owner->followingChains.clear();
        owner->status.active = false; owner->status.phase = "Inactive"; owner->status.reason = reason;
        owner->status.resources.clear(); owner->status.width = owner->status.height = 0;
        ++owner->failures;
        if (owner->failures >= 3) owner->status.reason = "Failed after 3 bridge attempts: " + reason;
    }
    PublishBindingWindow();
    if (log) LOG_ERROR("[NRD_BRIDGE] inactive: {}",reason);
}
void CoordinatorException(const char* reason) noexcept
{
    try
    {
        std::shared_ptr<Service> owner;
        { std::scoped_lock lock(gMutex); owner = gService; }
        if (owner) Failure(owner,reason);
    } catch (...) {}
}
void WaitingForBindings(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, const char* reason)
{
    bool log = false; RetiredDebugSources retired;
    {
        std::scoped_lock lock(gMutex);
        if (gService != owner || !owner->window) return;
        if (owner->cache.Valid()) owner->cache.Invalidate();
        DropPending(*owner,retired);
        if (const auto found = owner->lists.find(cmd); found != owner->lists.end()) StopFollowing(*owner,cmd,found->second);
        log = owner->status.reason != reason;
        owner->status.active = false; owner->status.phase = "Discovering"; owner->status.reason = reason;
        owner->status.resources.clear(); owner->status.width = owner->status.height = 0;
    }
    if (log) LOG_INFO("[NRD_BRIDGE] {}; waiting for a complete command-list Reset inside the bounded window",reason);
}
bool Tables(ID3D12GraphicsCommandList* cmd, Role role, std::vector<FrameSurvey::BoundResource>& srv,
            std::vector<FrameSurvey::BoundResource>& uav)
{
    constexpr std::array<FrameSurvey::ComputeTableRequest,4> recon {{
        {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1,1,0},
        {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,2,2,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,3,3,0}}};
    constexpr std::array<FrameSurvey::ComputeTableRequest,2> outputs {{
        {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,1,0}}};
    constexpr std::array<FrameSurvey::ComputeTableRequest,1> motion {{
        {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,2,2,0}}};
    if (role == Role::Recon)
        return FrameSurvey::ResolveComputeBindings(cmd,1,recon,srv) && FrameSurvey::ResolveComputeBindings(cmd,5,outputs,uav);
    if (role == Role::Temporal) return FrameSurvey::ResolveComputeBindings(cmd,1,motion,srv);
    if (role == Role::ATrous || role == Role::Consumer) return FrameSurvey::ResolveComputeBindings(cmd,5,outputs,uav);
    return true;
}
bool CurrentConsumerOutputs(const FrameSurvey::ComputeBindings& current,
    const std::array<FrameSurvey::BoundResource,2>& expected, std::vector<FrameSurvey::BoundResource>& scratch) noexcept
{
    constexpr std::array<FrameSurvey::ComputeTableRequest,2> requests {{
        {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,1,0}}};
    if (!FrameSurvey::ResolveComputeBindings(current,5,requests,scratch) || scratch.size() != expected.size()) return false;
    for (size_t i=0;i<expected.size();++i)
    {
        const auto& a = scratch[i]; const auto& b = expected[i];
        if (a.resource != b.resource || a.resourceGeneration != b.resourceGeneration || a.resourceBirth != b.resourceBirth ||
            a.viewFormat != b.viewFormat || a.subresource != b.subresource || a.kind != b.kind ||
            a.descriptorOffset != b.descriptorOffset || a.descriptorIndex != b.descriptorIndex) return false;
    }
    return true;
}
void LogDiscovery(const ChainDiscovery& chain, ID3D12Resource* motionTag)
{
    constexpr std::array<const char*,9> names {"IN_SPEC","IN_DIFF","NR","VIEWZ","RECON_SPEC","RECON_DIFF","MV","OUT_SPEC","OUT_DIFF"};
    for (size_t i=0;i<names.size();++i)
    {
        const auto& bound = chain.Bindings()[i];
        LOG_INFO("[NRD_BRIDGE] {} pointer={} format={} size={}x{} flags={} descriptor_offset={}",names[i],
            static_cast<void*>(bound.resource),uint32_t(bound.viewFormat),bound.description.Width,bound.description.Height,
            uint32_t(bound.description.Flags),bound.descriptorOffset);
    }
    LOG_INFO("[NRD_BRIDGE] discovery complete; chain A ATrous={} (diagnostic only), MV tag={} comparison={}",
        chain.ChainAIterations(),static_cast<void*>(motionTag),motionTag ? "equal" : "tag not yet known");
}
std::string ResourceSummary(const Resources& resources)
{
    std::ostringstream text;
    text << resources.width << 'x' << resources.height << "  RECON spec=" << resources.reconSpec << " diff=" << resources.reconDiff
         << "  OUT spec=" << resources.outputSpec << " diff=" << resources.outputDiff << "  MV=" << resources.motion;
    return text.str();
}
bool AppendNativeTextureProof(const std::shared_ptr<NativeCommitProof>& proof,
    std::span<const FrameSurvey::TextureBindingWitness> witnesses) noexcept
{
    if (!proof || proof->sealed.load(std::memory_order_relaxed) || witnesses.empty() ||
        proof->textures.size() > FrameSurvey::MaximumTextureBindingWitnesses ||
        witnesses.size() > FrameSurvey::MaximumTextureBindingWitnesses-proof->textures.size() ||
        proof->textures.capacity()-proof->textures.size() < witnesses.size()) return false;
    // Capacity is reserved before mandatory Track. Preserve each actual use;
    // repeated slots are deliberately checked too, without a quadratic dedup scan.
    proof->textures.insert(proof->textures.end(),witnesses.begin(),witnesses.end());
    return true;
}
bool AppendNativeConstantProof(const std::shared_ptr<NativeCommitProof>& proof,
    const FrameSurvey::ComputeBindings& bindings, const FrameSurvey::BoundConstantBinding& constant, bool pixel)
{
    if (!proof || proof->sealed.load(std::memory_order_relaxed) || proof->constantCount == proof->constants.size()) return false;
    auto& row = proof->constants[proof->constantCount];
    row.bindings = bindings; row.constant = constant; row.pixel = pixel; ++proof->constantCount;
    return true;
}
struct NativeCommitDiagnostic { const char* gate="unavailable";size_t row=0; };
bool ValidateNativeCommitProof(const NativeCommitProof& proof,
    const RecordedComputeLease::SubmissionInfo& info, NativeCommitDiagnostic& diagnostic) noexcept
{
    const auto reject=[&](const char* gate,size_t row=0){diagnostic={gate,row};return false;};
    if (!NrdBridgeDescriptorAdmission::SubmissionHeldByCurrentThread() || !NrdBridgeDescriptorAdmission::Healthy()) return reject("descriptor_admission");
    if (!proof.sealed.load(std::memory_order_acquire) || !proof.recordingId || proof.recordingId != info.recordingId) return reject("recording_seal");
    if (!FrameSurvey::MetadataHealthy()) return reject("metadata");
    NrdBridgeLifetime::ScopedBorrow borrow;
    if (!borrow.Acquired() || !BirthLive(proof.listBirth)) return reject("recording_lifetime");
    const auto recording = proof.recording.lock();
    if (!recording || recording->id != info.recordingId || proof.textures.empty()) return reject("recording_identity");
    if (!FrameSurvey::ValidateTextureBindingWitnesses(proof.textures))
    {
        for(size_t row=0;row<proof.textures.size();++row)
            if(!FrameSurvey::ValidateTextureBindingWitnesses(std::span(&proof.textures[row],1)))return reject("texture_binding",row);
        return reject("texture_binding");
    }
    for (size_t index=0;index<proof.constantCount;++index)
    {
        const auto& row=proof.constants[index];
        if (!(row.pixel ? FrameSurvey::ValidateGraphicsConstantBinding(row.bindings,6,0,row.constant) :
            FrameSurvey::ValidateComputeConstantBinding(row.bindings,6,0,row.constant))) return reject(row.pixel ? "pixel_constant" : "compute_constant",index);
    }
    for (size_t index=0;index<proof.pipelineCount;++index)
        if (!FrameSurvey::ValidatePipelineShaderIdentity(proof.pipelines[index])) return reject("pipeline_identity",index);
    for (size_t index=0;index<proof.signatureCount;++index)
        if (!FrameSurvey::ValidateIndirectSignature(proof.signatures[index])) return reject("indirect_signature",index);
    for (size_t index=0;index<proof.rasterOutputCount;++index)
        if (proof.rasterOutputs[index].receiverBirth!=proof.listBirth ||
            !FrameSurvey::ValidateRecordedRenderTargets(proof.rasterOutputs[index])) return reject("raster_resource_birth",index);
    return true;
}
RecordedComputeLease::SubmissionCallbacks RecordingCallbacks(const std::shared_ptr<Service>& owner,
    const std::shared_ptr<RecordingOwnership>& ownership)
{
    RecordedComputeLease::SubmissionCallbacks submission;
    submission.beforeSubmit = [ownership](const RecordedComputeLease::SubmissionInfo& info) {
        const bool outputComplete = AdmitRecordingSubmission(*ownership->token);
        if (!outputComplete)
        {
            if (SoftSubmitLogDue(gSoftIncompleteSubmissions))
                LOG_INFO("[NRD_BRIDGE] submit forwarded without RR commit cause={} chain={} recording={} submission={} committed={} invalidated={} abandoned={} count={}",
                    ownership->token->invalidationGate.load(std::memory_order_acquire) ? ownership->token->invalidationGate.load(std::memory_order_relaxed) : "consumer_missing",
                    ownership->history->semanticChain,info.recordingId,info.submissionId,
                    ownership->token->outputCommitted.load(std::memory_order_acquire),
                    ownership->token->skipInvalidated.load(std::memory_order_acquire),
                    ownership->token->abandoned.load(std::memory_order_acquire),gSoftIncompleteSubmissions.load(std::memory_order_relaxed));
            ownership->history->uncertain.store(true,std::memory_order_release);
            ownership->history->discardPending.store(true,std::memory_order_release);
        }
        NativeCommitDiagnostic diagnostic;
        if (outputComplete && ownership->nativeProof && !ValidateNativeCommitProof(*ownership->nativeProof,info,diagnostic))
        {
            const auto& proof=*ownership->nativeProof;
            if (SoftSubmitLogDue(gSoftProofSubmissions))
                LOG_INFO("[NRD_BRIDGE] submit forwarded with stale commit proof reason={} witness={} chain={} recording={} submission={} sealed={} textures={} constants={} pipelines={} signatures={} raster_outputs={} descriptor_admission={} count={}",
                    diagnostic.gate,diagnostic.row,ownership->history->semanticChain,info.recordingId,info.submissionId,proof.sealed.load(std::memory_order_acquire),
                    proof.textures.size(),proof.constantCount,proof.pipelineCount,proof.signatureCount,proof.rasterOutputCount,
                    NrdBridgeDescriptorAdmission::SubmissionHeldByCurrentThread(),gSoftProofSubmissions.load(std::memory_order_relaxed));
            ownership->token->skipInvalidated.store(true,std::memory_order_release);
            ownership->history->uncertain.store(true,std::memory_order_release);
            ownership->history->discardPending.store(true,std::memory_order_release);
        }
        auto& domain = *ownership->history;
        RecordedComputeLease::FencePointPtr retiredPoint;
        std::shared_ptr<NativeDebugImageOrder> imageOrder;
        {
            std::scoped_lock lock(ownership->token->publicationMutex);
            ownership->token->submitted.store(true,std::memory_order_release);
            ownership->token->submissionId = info.submissionId; retiredPoint = std::move(ownership->token->completion);
            imageOrder = ownership->token->imageOrder;
            ownership->token->phase.store(SubmissionPhase::Submitting,std::memory_order_release);
        }
        // Replaying a closed recording changes temporal causality. Existing work is
        // still ordered and retained; the next recording gets a fresh RESET domain.
        if (info.recordingSubmission > 1 || info.snapshotFallback)
            domain.uncertain.store(true,std::memory_order_release);
        if (info.recordingSubmission > 1 && imageOrder)
        {
            std::shared_ptr<RecordingToken> tail;
            { std::scoped_lock lock(imageOrder->mutex); tail = imageOrder->presentation; }
            if (tail)
            {
                RecordedComputeLease::FencePointPtr point; uint64_t submissionId = 0;
                if (!PublishedToken(tail,point,submissionId)) { RecordedComputeLease::DenySubmission(E_FAIL); return false; }
                if (FAILED(RecordedComputeLease::WaitForFence(info.queue,point))) return false;
            }
        }
        RecordedComputeLease::FencePointPtr predecessor;
        {
            std::scoped_lock lock(domain.submissionMutex);
            // A prior Execute without a newly published fence cannot be ordered by
            // an older completion point. Already-recorded successors must stop too.
            if (domain.pendingSubmission && domain.latestSubmissionId != info.submissionId)
            {
                LOG_ERROR("[NRD_BRIDGE] submit rejected gate=history_pending chain={} recording={} submission={} prior_submission={}",
                    domain.semanticChain,info.recordingId,info.submissionId,domain.latestSubmissionId);
                RecordedComputeLease::DenySubmission(E_FAIL); return false;
            }
            predecessor = domain.completion;
            domain.latestSubmissionId = info.submissionId; domain.pendingSubmission = true;
        }
        return SUCCEEDED(RecordedComputeLease::WaitForFence(info.queue,predecessor));
    };
    submission.fencePublished = [ownership](const RecordedComputeLease::SubmissionInfo& info,
                                            const RecordedComputeLease::FencePointPtr& point) {
        auto& domain = *ownership->history; RecordedComputeLease::FencePointPtr retiredDomainPoint, retiredPoint;
        {
            std::scoped_lock lock(domain.submissionMutex);
            if (domain.latestSubmissionId == info.submissionId)
            { retiredDomainPoint = std::move(domain.completion); domain.completion = point; domain.pendingSubmission = false; }
        }
        {
            std::scoped_lock lock(ownership->token->publicationMutex);
            if (ownership->token->submissionId == info.submissionId &&
                ownership->token->phase.load(std::memory_order_acquire) == SubmissionPhase::Submitting)
            {
                retiredPoint = std::move(ownership->token->completion); ownership->token->completion = point;
                ownership->token->phase.store(SubmissionPhase::FencePublished,std::memory_order_release);
            }
        }
    };
    const std::weak_ptr<Service> weakOwner = owner;
    submission.failed = [ownership,weakOwner](const auto& info, auto failure) {
        LOG_ERROR("[NRD_BRIDGE] submission failed phase={} chain={} recording={} submission={} replay={}",
            uint32_t(failure),ownership->history->semanticChain,info.recordingId,info.submissionId,info.recordingSubmission);
        ownership->history->uncertain.store(true,std::memory_order_release);
        RecordedComputeLease::FencePointPtr retiredPoint; bool nativeReplay = false;
        {
            std::scoped_lock lock(ownership->token->publicationMutex);
            if (ownership->token->submissionId == info.submissionId)
            { retiredPoint = std::move(ownership->token->completion); ownership->token->phase.store(SubmissionPhase::Poisoned,std::memory_order_release); }
            nativeReplay = bool(ownership->token->imageOrder) && info.recordingSubmission > 1;
        }
        if (const auto service = weakOwner.lock())
        {
            if (nativeReplay && failure == RecordedComputeLease::SubmissionFailure::Ordering) NativeDebugOrderingFailure(service);
            else Failure(service,"NRD submission ordering or fence tracking failed; restart the title/device");
        }
    };
    return submission;
}
void Convert(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, uint64_t frame)
{
    bool mandatory = false, requiredRetained = false;
    try
    {
    Resources resources; uint64_t generation = 0, serial = 0, resetRevision = 0; bool reset = false, discard = false;
    const auto streamline = StreamlineHooks::getSLConstantsSnapshot();
    RRSettings rrSettings; bool cameraProjectedDepthDelta = false, stageSampling = false;
    NativeMaterialCapture::SnapshotLease materialSnapshot;
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) ||
            found == owner->lists.end() || found->second.frame != frame ||
            !found->second.followingRecon || !found->second.chain.Valid() || !ListLive(found->second) || !ChainLive(found->second.chain)) return;
        mandatory = found->second.rrOnlyTransaction;
        if (!mandatory && !owner->cache.Valid()) return;
        resources = mandatory ? found->second.chain.Get() : owner->cache.Get();
        // Every recording uses its current validated guides, including the first
        // native transaction before a Consumer/output profile has ever existed.
        resources.normals = found->second.chain.Get().normals;
        resources.viewDepth = found->second.chain.Get().viewDepth;
        generation = mandatory ? frame : owner->cache.Generation(); serial = owner->cancellationSerial;
        resetRevision = owner->requestedResetRevision;
        reset = serial != owner->appliedReset;
        stageSampling = gStageCollector.Active();
    }
    #ifdef FSRD_NRD_BRIDGE_TEST
    if (gBeforeConversionLockForTesting) gBeforeConversionLockForTesting();
#endif
    // Reuse the recording's existing allocation; no native work moves before its lifetime borrow.
    auto recording = MakeOwnedShared<RecordingToken>();
    recording->commitRequired.store(mandatory,std::memory_order_relaxed);
    recording->needsStageSamples = stageSampling; recording->stages.stopped = &gStagesStopped;
    NrdBridgeStagePerf::Sample injectionWait {}; injectionWait.stopped = &gStagesStopped;
    std::unique_lock injection(gInjectionMutex,std::defer_lock);
    NrdBridgeStagePerf::StackTimer waitTimer(stageSampling ? &injectionWait : nullptr,NrdBridgeStagePerf::Stage::ReconInjectionWait);
    injection.lock(); waitTimer.Stop();
    auto* profile = StageSample(recording);
    if (profile) MergeStageSamples(*profile,injectionWait);
    NrdBridgeStagePerf::StackTimer injectionHold(profile,NrdBridgeStagePerf::Stage::ReconInjectionHold);
    NrdBridgeStagePerf::StackTimer physicalWait(profile,NrdBridgeStagePerf::Stage::ReconPhysicalWait);
    NrdBridgeLifetime::ScopedBorrow borrow; physicalWait.Stop(); if (!borrow.Acquired()) return;
    NrdBridgeStagePerf::StackTimer physicalHold(profile,NrdBridgeStagePerf::Stage::ReconPhysicalHold);
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) ||
            (!mandatory && (!owner->cache.Valid() || owner->cache.Generation() != generation)) ||
            owner->cancellationSerial != serial || found == owner->lists.end() ||
            found->second.frame != frame || found->second.rrOnlyTransaction != mandatory ||
            !found->second.followingRecon || !found->second.chain.Valid() || !ListLive(found->second) || !ChainLive(found->second.chain) ||
            found->second.chain.Get().normals != resources.normals ||
            found->second.chain.Get().viewDepth != resources.viewDepth) return;
        discard = owner->discardRequested;
        rrSettings = owner->rrSettings; cameraProjectedDepthDelta = owner->cameraProjectedDepthDelta;
        if (rrSettings.nativeMaterialGuides)
        {
            const auto& material = found->second.material;
            if (material.serial != serial || material.normal != resources.normals || !BirthLive(material.normalBirth) ||
                !material.normalGeneration || material.normalGeneration != found->second.chain.Bindings()[2].resourceGeneration ||
                (BirthMode() && material.normalBirth != found->second.chain.Bindings()[2].resourceBirth))
                materialSnapshot.reset(); // White fallback until a fresh state/identity proof exists.
            else materialSnapshot = material.snapshot;
        }
    }
    if (!FrameSurvey::MetadataHealthy()) { if (mandatory) RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL); Failure(owner,"Creation or binding metadata is unhealthy; restart the title/device"); return; }
    if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { if (mandatory) RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL); Failure(owner,"Title compute state cannot be restored after Recon"); return; }
    std::string error, conventions; FrameParameters parameters; ConvertedResources converted;
    bool succeeded = false;
    std::shared_ptr<HistoryDomain> history = owner->history;
    if (discard)
    {
        for (const auto& weak : owner->historyDomains)
            if (const auto abandoned = weak.lock(); abandoned && abandoned->discardPending.exchange(false,std::memory_order_acq_rel))
            {
                abandoned->uncertain.store(true,std::memory_order_release);
                FrameSurvey::ScopedInternal internal;
                if (abandoned->latestOwned) abandoned->rr.AbandonOwned(abandoned->latestOwned);
                else abandoned->rr.DiscardRecordingHistory();
            }
    }
    const bool sameHistoryKey = history && history->nativeContract == mandatory && (mandatory ?
        history->semanticChain == 0 && history->width == resources.width && history->height == resources.height &&
            history->viewport == streamline.viewport : history->resourceGeneration == generation);
    const bool reusable = sameHistoryKey &&
        !history->uncertain.load(std::memory_order_acquire) && (!history->latestRecording ||
            (history->latestRecording->outputCommitted.load(std::memory_order_acquire) &&
             history->latestRecording->phase.load(std::memory_order_acquire) == SubmissionPhase::FencePublished));
    if (!reusable)
    {
        // Drop an otherwise unowned retired generation before applying the live bound.
        if (history && history.use_count() == 2)
        { owner->history.reset(); history.reset(); }
        std::erase_if(owner->historyDomains,[](const auto& domain) { return domain.expired(); });
        // Entire temporal generations are bounded as well as their descriptor slots.
        // An outstanding, unsubmitted predecessor cannot seed GPU depth/SDK history.
        if (owner->historyDomains.size() >= 8)
        { if (mandatory) RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL); Failure(owner,"NRD has 8 unretired temporal generations; submit/reset recordings before retrying"); return; }
        history = MakeOwnedShared<HistoryDomain>();
        history->resourceGeneration = generation; history->id = ++owner->nextDomain;
        history->nativeContract = mandatory; history->width = resources.width; history->height = resources.height;
        history->viewport = streamline.viewport;
        owner->historyDomains.push_back(history); owner->history = history;
        reset = true;
    }
    reset = reset || history->resetRevision != resetRevision;
    const bool materialApplied = rrSettings.nativeMaterialGuides && NativeMaterialCapture::Resource(materialSnapshot);
    const bool materialModeReset = rrSettings.nativeMaterialGuides && history->materialGuidesKnown &&
        history->materialGuidesUsed != materialApplied;
    if (materialModeReset) reset = true;
    history->latestRecording = recording;
    auto ownership = MakeOwnedShared<RecordingOwnership>(); ownership->history = history; ownership->token = recording;
    auto submission = RecordingCallbacks(owner,ownership);
    {
        InjectionScope guard(cmd);
        NrdBridgeStagePerf::StackTimer prepare(profile,NrdBridgeStagePerf::Stage::ReconPrepare);
        if (discard)
        {
            std::scoped_lock lock(gMutex);
            if (gService == owner && owner->cancellationSerial == serial) owner->discardRequested = false;
        }
        // Retain the mandatory gate before provider/configuration/conversion can fail.
        succeeded = true;
        if (mandatory)
        {
            succeeded = ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),cmd,ownership,{},std::move(submission));
            if (succeeded) { recording->submissionRetained.store(true,std::memory_order_release); requiredRetained = true; }
            else RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);
        }
        if (reset) { history->conversion.ResetHistory(); history->rr.ResetHistory(); }
        if (succeeded) succeeded = history->rr.Configure(rrSettings,error);
        if (succeeded && rrSettings.lobeRecovery &&
            (rrSettings.recoverySpecular > 0.0f || rrSettings.recoveryDiffuse > 0.0f))
        {
            if (!owner->recoveryFamily) owner->recoveryFamily = CreateRRRecoveryFamily();
            history->rr.SetRecoveryFamily(owner->recoveryFamily);
        }
        if (succeeded) succeeded = history->rr.PrepareFrame(streamline,reset,parameters,error);
        parameters.cameraProjectedDepthDelta = cameraProjectedDepthDelta;
        parameters.nativeTemporalMotion = rrSettings.nativeTemporalMotion;
        parameters.legacyMotionDepth = rrSettings.legacyMotionDepth;
        parameters.nativeMaterialGuides = rrSettings.nativeMaterialGuides;
        parameters.preserveNativeMaterialIDs = rrSettings.preserveNativeMaterialIDs;
        if (succeeded && parameters.reset) history->conversion.ResetHistory();
        if (succeeded) succeeded = history->conversion.Initialize(owner->device.Get(),resources.width,resources.height,error);
        if (succeeded && !mandatory)
        {
            succeeded = ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),cmd,ownership,{},std::move(submission));
            if (succeeded) { recording->submissionRetained.store(true,std::memory_order_release); requiredRetained = true; }
        }
        if (!succeeded && error.empty()) error = "Could not prepare retained NRD recording";
        prepare.Stop();
        if (succeeded)
        {
            const ConversionInputs inputs {resources.reconSpec,resources.reconDiff,resources.normals,resources.viewDepth,nullptr,
                NativeMaterialCapture::Resource(materialSnapshot),NativeMaterialCapture::RoughnessResource(materialSnapshot)};
            NrdBridgeStagePerf::StackTimer conversion(profile,NrdBridgeStagePerf::Stage::ReconConvert);
            succeeded = history->conversion.Dispatch(cmd,inputs,parameters,converted,error);
        }
        if (succeeded)
        {
            history->resetRevision = resetRevision;
            history->materialGuidesKnown = true; history->materialGuidesUsed = materialApplied;
            conventions = Conventions(history->rr);
        }
    }
    if (!succeeded) { Failure(owner,error.empty() ? "NRD input conversion failed" : error); return; }
    bool logConventions = false;
    std::shared_ptr<RecordingToken> retiredRecording; std::shared_ptr<HistoryDomain> retiredHistory;
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) ||
            (!mandatory && (!owner->cache.Valid() || owner->cache.Generation() != generation)) ||
            owner->cancellationSerial != serial || found == owner->lists.end() ||
            found->second.frame != frame || found->second.rrOnlyTransaction != mandatory) return;
        auto& list = found->second;
        retiredRecording = std::move(list.recording); retiredHistory = std::move(list.history);
        list.converted = true; list.motionReady = list.ownedReady = false; list.recording = recording; list.history = history; list.ownership = ownership;
        list.generation = generation; list.resetSerial = serial;
        list.parameters = parameters; list.streamline = streamline; list.inputs = converted; list.debug = gDebug.load(std::memory_order_relaxed);
        owner->rrSettingsState = history->rr.GetSettingsState();
        owner->pendingList = cmd; owner->appliedReset = serial;
        owner->status.nativeMaterialGuidesActive = materialApplied;
        if (materialApplied) ++owner->status.nativeMaterialFramesApplied;
        if (materialModeReset) ++owner->status.nativeMaterialModeResets;
        const auto provenance = history->conversion.MotionProvenance();
        owner->status.motionProvenanceDispatches = provenance.dispatches;
        owner->status.motionProvenanceNative = provenance.native;
        owner->status.motionProvenanceCameraOnly = provenance.cameraOnly;
        owner->status.motionProvenanceUnknown = provenance.unknown;
        owner->status.motionProvenanceLegacy = provenance.legacyVisible;
        logConventions = !owner->conventionsLogged && !conventions.empty();
        if (logConventions) owner->conventionsLogged = true;
    }
    if (logConventions) LOG_INFO("[NRD_BRIDGE] SL conventions: {}",conventions);
    }
    catch (...)
    {
        if (mandatory && !requiredRetained) RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);
        throw;
    }
}
bool CaptureMaterialForCurrentPipeline(ID3D12GraphicsCommandList* cmd)
{
    std::shared_ptr<Service> owner; NrdBridgeBirth::Token receiverBirth; uint64_t serial = 0;
    MaterialSnapshot retiredMaterial;
    {
        std::scoped_lock lock(gMutex); owner = gService; if (!owner) return false;
        const auto found = owner->lists.find(cmd);
        if (found == owner->lists.end() || found->second.role != Role::MaterialGuide) return false;
        retiredMaterial = std::move(found->second.pendingMaterial); // Tombstone even if this writer cannot borrow/capture.
        if (!owner->rrSettings.nativeMaterialGuides || !owner->window || !ListLive(found->second)) return true;
        ++owner->status.nativeMaterialAttempts;
        receiverBirth = found->second.birth; serial = owner->cancellationSerial;
    }
    std::scoped_lock injection(gInjectionMutex);
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return true;
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || found == owner->lists.end() ||
            found->second.birth != receiverBirth || !ListLive(found->second) ||
            !owner->rrSettings.nativeMaterialGuides || serial != owner->cancellationSerial) return true;
    }
    constexpr std::array<FrameSurvey::ComputeTableRequest,1> baseRequest {{{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,7,7,0}}};
    constexpr std::array<FrameSurvey::ComputeTableRequest,1> paramRequest {{{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1,9,0}}};
    constexpr std::array<FrameSurvey::ComputeTableRequest,1> normalRequest {{{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,4,4,0}}};
    std::vector<FrameSurvey::BoundResource> base,params,normal;
    if (!FrameSurvey::MetadataHealthy() || !D3D12Hooks::CanRestoreRootSignature(cmd) ||
        !FrameSurvey::ResolveComputeBindings(cmd,1,baseRequest,base) ||
        !FrameSurvey::ResolveComputeBindings(cmd,2,paramRequest,params) ||
        !FrameSurvey::ResolveComputeBindings(cmd,5,normalRequest,normal) ||
        base.size()!=1 || params.size()!=1 || normal.size()!=1 || !normal[0].resource ||
        base[0].viewFormat!=DXGI_FORMAT_R10G10B10A2_UNORM || params[0].viewFormat!=DXGI_FORMAT_R8G8B8A8_UNORM ||
        normal[0].viewFormat!=DXGI_FORMAT_R10G10B10A2_UNORM || base[0].subresource || params[0].subresource || normal[0].subresource)
    { return true; } // Optional unsupported provenance retains white guides.
    NativeMaterialCapture::SourceStates sourceStates {};
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end() || found->second.birth != receiverBirth || serial != owner->cancellationSerial) return true;
        gMaterialResources.Insert(base[0].resource); gMaterialResources.Insert(params[0].resource);
        owner->materialIdentities.Remember(base[0],params[0]);
        auto& witness = found->second.materialStates;
        witness.Select(base[0],params[0]);
        if (!witness.TryKnownStates(serial,sourceStates))
        { ++owner->status.nativeMaterialUnknownState; return true; }
        if (std::any_of(sourceStates.begin(),sourceStates.end(),[](auto state) {
            return (state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE) &&
                   !(state & D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE); }))
            ++owner->status.nativeMaterialKnownPSR;
    }
    if (!NativeMaterialCapture::CanCaptureStates(sourceStates,cmd->GetType()))
    {
        std::scoped_lock lock(gMutex);
        if (gService == owner) ++owner->status.nativeMaterialUnsupportedState;
        return true;
    }
    const auto extent = normal[0].description;
    std::string error; NativeMaterialCapture::SnapshotLease snapshot; bool captured = false;
    {
        InjectionScope guard(cmd);
        captured = owner->nativeMaterialCapture.InitializeParams(owner->device.Get(),uint32_t(extent.Width),extent.Height,error) &&
            owner->nativeMaterialCapture.CaptureParams(cmd,base[0].resource,params[0].resource,sourceStates,snapshot,error);
    }
    if (!captured)
    {
        std::scoped_lock lock(gMutex);
        if (gService == owner) ++owner->status.nativeMaterialCaptureFailures;
        return true; // Failed preparation/retain records no borrowed GPU commands.
    }
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end() || found->second.birth != receiverBirth || serial != owner->cancellationSerial) return true;
        auto& pending = found->second.pendingMaterial;
        pending.snapshot = std::move(snapshot); pending.normal = normal[0].resource;
        pending.normalBirth = normal[0].resourceBirth; pending.serial = serial;
        pending.normalGeneration = normal[0].resourceGeneration;
        ++owner->status.nativeMaterialSnapshots;
    }
    return true;
}

void CaptureTemporalMotion(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd)
{
    std::scoped_lock injection(gInjectionMutex);
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
    ListState staged;
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || found == owner->lists.end()) return;
        const auto& list = found->second;
        if (!ListLive(list) || !ChainLive(list.chain) || !list.converted || list.temporal ||
            !list.followingRecon || !list.parameters.nativeTemporalMotion || !list.history ||
            list.resetSerial != owner->cancellationSerial || !CurrentFrameProfile(*owner,list)) return;
        staged = list;
    }
    std::string error;
    FrameSurvey::BoundConstantBinding binding;
    if (!FrameSurvey::MetadataHealthy() || !D3D12Hooks::CanRestoreRootSignature(cmd) ||
        !FrameSurvey::ResolveComputeConstantBinding(cmd,6,0,binding))
    { Failure(owner,"Native Temporal b6 binding/state unavailable before dispatch"); return; }
    NativeTemporalCapture::SnapshotLease snapshot;
    bool captured = false;
    {
        InjectionScope guard(cmd);
        captured = staged.history->nativeTemporalCapture.Initialize(owner->device.Get(),error) &&
            staged.history->nativeTemporalCapture.Capture(cmd,binding,snapshot,error);
    }
    if (!captured) { Failure(owner,error.empty() ? "Native Temporal GPU constant capture failed" : error); return; }
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end()) return;
        auto& list = found->second;
        if (list.frame == staged.frame && list.generation == staged.generation && list.converted &&
            list.resetSerial == owner->cancellationSerial && list.recording == staged.recording)
            list.nativeMotionSnapshot = std::move(snapshot);
    }
}

template<class Pass> bool DispatchCurrentMotion(Pass& pass, ID3D12GraphicsCommandList* cmd,
    const ConvertedResources& converted, ID3D12Resource* motion, const FrameParameters& frame, std::string& error,
    const NativeMotionSource& native)
{
    if constexpr (requires { pass.DispatchMotion(cmd,converted,motion,frame,error,native); })
        return pass.DispatchMotion(cmd,converted,motion,frame,error,native);
    if constexpr (requires { pass.DispatchMotion(cmd,converted,motion,frame,error); })
        return pass.DispatchMotion(cmd,converted,motion,frame,error);
    error = "NRD motion finalization interface is unavailable"; return false;
}
void FinalizeMotion(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, uint64_t frame,
                    ID3D12Resource* currentMotion)
{
    std::scoped_lock injection(gInjectionMutex);
    NrdBridgeStagePerf::Sample motionStages {}; motionStages.stopped = &gStagesStopped;
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
    NrdBridgeStagePerf::StackTimer physicalHold(motionStages.Enabled() ? &motionStages : nullptr,NrdBridgeStagePerf::Stage::MotionPhysicalHold);
    ListState staged;
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || found == owner->lists.end()) return;
        const auto& list = found->second;
        if (!ListLive(list) || !ChainLive(list.chain) || !list.converted || list.motionReady || list.frame != frame ||
            !CurrentFrameProfile(*owner,list) || list.resetSerial != owner->cancellationSerial ||
            (list.rrOnlyTransaction ? list.chain.Get().motion : owner->cache.Get().motion) != currentMotion) return;
        staged = list;
    }
    if (!FrameSurvey::MetadataHealthy()) { Failure(owner,"Creation or binding metadata is unhealthy; restart the title/device"); return; }
    if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored at first Temporal"); return; }
    std::string error; bool succeeded = false;
    NativeMotionSource native;
    if (staged.parameters.nativeTemporalMotion)
    {
        constexpr std::array<FrameSurvey::ComputeTableRequest,1> depth {{{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,4,0}}};
        std::vector<FrameSurvey::BoundResource> resolved;
        native.constants = NativeTemporalCapture::Resource(staged.nativeMotionSnapshot);
        if (!native.constants || !FrameSurvey::ResolveComputeBindings(cmd,1,depth,resolved) || resolved.size() != 1 ||
            !NativeTemporalDepthViewSupported(resolved[0],staged.inputs.width,staged.inputs.height))
        { Failure(owner,"Native Temporal motion has no same-recording constants/current ViewZ"); return; }
        native.viewDepth = resolved[0].resource;
        if (staged.rrOnlyTransaction && (resolved[0].resource != staged.nativeFirstDepth.resource ||
            resolved[0].resourceGeneration != staged.nativeFirstDepth.resourceGeneration ||
            (BirthMode() && resolved[0].resourceBirth != staged.nativeFirstDepth.resourceBirth)))
        { Failure(owner,"Native Temporal ViewZ differs from the current first PrePass output"); return; }
    }
    RRRecordedOutputLease owned; RRRecordedOutputSnapshot ownedSnapshot;
    {
        InjectionScope guard(cmd);
        succeeded = DispatchCurrentMotion(staged.history->conversion,cmd,staged.inputs,currentMotion,staged.parameters,error,native);
        physicalHold.Stop(); // Motion span excludes the separately measured provider recording.
        if (succeeded && staged.rrOnlyTransaction)
        {
            if (staged.streamline.frameIndex != staged.parameters.streamlineFrame)
            { succeeded = false; error = "Captured Streamline frame differs from early owned RR parameters"; }
            else
            {
                auto* profile = StageSample(staged.recording);
                NrdBridgeStagePerf::StackTimer rrDispatch(profile,NrdBridgeStagePerf::Stage::ConsumerRRDispatch);
                succeeded = staged.history->rr.RecordOwned(cmd,staged.inputs,staged.parameters,owned,error,profile);
                if (succeeded) ownedSnapshot = staged.history->rr.GetOwnedOutputSnapshot(owned);
            }
        }
    }
    if (!succeeded) { Failure(owner,error.empty() ? "NRD current motion / early RR recording failed" : error); return; }
    const auto actualRecording = staged.rrOnlyTransaction ? RecordedComputeLease::Capture(cmd) : nullptr;
    if (staged.rrOnlyTransaction && (!owned || !actualRecording || !actualRecording->id ||
        ownedSnapshot.recording != cmd || ownedSnapshot.recordingId != actualRecording->id ||
        ownedSnapshot.frameSL != staged.parameters.streamlineFrame || ownedSnapshot.frameIndex != staged.parameters.frameIndex ||
        ownedSnapshot.contextGeneration != staged.history->rr.ContextGeneration()))
    { staged.history->rr.AbandonOwned(owned); Failure(owner,"Early RR output has no exact recording/frame/context identity"); return; }
    if (owned) staged.history->latestOwned = owned; // Outside gMutex; old context/slot owners may release here.
    bool accepted = false; RRRecordedOutputLease retiredOutput;
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService == owner && found != owner->lists.end())
        {
            auto& list = found->second;
            if (list.frame == frame && CurrentFrameProfile(*owner,list) && list.resetSerial == owner->cancellationSerial &&
                list.converted && list.recording == staged.recording && !list.recording->skipInvalidated.load(std::memory_order_acquire))
            {
                list.motionReady = true; accepted = true;
                if (owned)
                {
                    retiredOutput = std::move(list.ownedOutput); list.ownedOutput = owned; list.ownedReady = true;
                    list.ownedContext = ownedSnapshot.contextGeneration; list.ownedRecording = ownedSnapshot.recordingId;
                }
            }
        }
    }
    if (!accepted && owned) staged.history->rr.AbandonOwned(owned);
    physicalHold.Stop(); // End before the physical borrow's destructor.
    if (auto* profile = StageSample(staged.recording)) MergeStageSamples(*profile,motionStages);
}
void PrepareEarlyTemporal(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd)
{
    uint64_t frame = 0; ID3D12Resource* motion = nullptr; bool capture = false, invalid = false;
    std::string error; RetiredDebugSources retired;
    {
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        std::vector<FrameSurvey::BoundResource> srv,uav;
        if (!Tables(cmd,Role::Temporal,srv,uav)) { Failure(owner,"Current Temporal motion table is unavailable before native elision"); return; }
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end()) return;
        auto& list = found->second;
        if (!list.rrOnlyTransaction || !list.nativeContract || !list.converted || list.temporal || list.earlyTemporalObserved ||
            !list.firstPrePass || !list.followingRecon || list.resetSerial != owner->cancellationSerial ||
            !ListLive(list) || !ChainLive(list.chain)) return;
        invalid = !list.chain.Observe(Role::Temporal,srv,uav,owner->taggedMotion,error);
        RefreshChainUsers(*owner,cmd,list);
        if (!invalid)
        {
            motion = list.chain.Get().motion; frame = list.frame;
            list.earlyTemporalObserved = true; capture = list.parameters.nativeTemporalMotion;
        }
    }
    if (invalid) { Failure(owner,error); return; }
    if (!frame) return;
    if (capture) CaptureTemporalMotion(owner,cmd);
    FinalizeMotion(owner,cmd,frame,motion);
}


bool NativeTransactionCurrent(const Service& owner, const ListState& list,
    const std::shared_ptr<NativeTransaction>& stage) noexcept
{
    return stage && stage->chain < list.native.size() && list.native[stage->chain] == stage &&
        list.frame == stage->frame && list.birth == stage->birth && ListLive(list) &&
        stage->serial == owner.cancellationSerial && !stage->invalidated && !stage->committed &&
        stage->recording && stage->recording->submissionRetained.load(std::memory_order_acquire) &&
        !stage->recording->skipInvalidated.load(std::memory_order_acquire) &&
        !stage->recording->abandoned.load(std::memory_order_acquire);
}
void NativeTransactionFailure(const std::shared_ptr<Service>& owner,
    const std::shared_ptr<NativeTransaction>& stage, const std::string& error)
{
    // The caller owns gInjectionMutex. Do not destroy private COM/provider state
    // under gMutex, and never abandon a newer physical context through an old lease.
    if (stage && stage->history && stage->owned) stage->history->rr.AbandonOwned(stage->owned);
    {
        std::scoped_lock lock(gMutex);
        if (stage)
        {
            stage->invalidated = true;
            if (stage->recording) stage->recording->skipInvalidated.store(true,std::memory_order_release);
            if (stage->history)
            {
                stage->history->uncertain.store(true,std::memory_order_release);
                stage->history->discardPending.store(true,std::memory_order_release);
            }
        }
        if (gService == owner) owner->discardRequested = true;
    }
    if (stage && stage->trace && owner->trace) owner->trace->CancelBridgeFrame(stage->trace,error);
    Failure(owner,error);
}
bool NativeRawSource(const FrameSurvey::ComputeBindings& bindings,
    const FrameSurvey::BoundConstantBinding& constants, uint32_t width, uint32_t height,
    uint32_t chain, ID3D12Device* device, RawSignalSource& source) noexcept
{
    D3D12_GPU_DESCRIPTOR_HANDLE table {};
    for (const auto& [parameter,handle] : bindings.tables)
        if (parameter == 1) { if (table.ptr) return false; table = handle; }
    if (!table.ptr) return false;
    const auto increment = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    if (!increment || table.ptr > UINT64_MAX-increment) return false;
    ID3D12DescriptorHeap* heap = nullptr;
    for (auto* candidate : bindings.heaps)
    {
        const auto description = candidate->GetDesc();
        if (description.Type != D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV ||
            !(description.Flags & D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE)) continue;
        const auto base = candidate->GetGPUDescriptorHandleForHeapStart().ptr;
        const uint64_t bytes = uint64_t(description.NumDescriptors)*increment;
        if (table.ptr < base || table.ptr-base >= bytes || (table.ptr-base)%increment ||
            bytes-(table.ptr-base) < uint64_t(increment)*2) continue;
        if (heap) return false; heap = candidate;
    }
    if (!heap) return false;
    source.nativeHeap = heap; source.specSrv = table; source.diffSrv = {table.ptr+increment};
    source.nativeConstants = {nullptr,constants.address,constants.descriptorHeap,constants.descriptor};
    source.width = width; source.height = height;
    source.profile = chain ? NativeRawProfile::PrePassPending : NativeRawProfile::ReconDirect;
    return true;
}
template<class Hooks> const char* ComputeRestoreReason() noexcept
{
    if constexpr (requires { Hooks::ComputeRestoreFailureReason(); })
        if (const auto reason = Hooks::ComputeRestoreFailureReason()) return reason;
    return "unavailable_in_adapter";
}
// This starts before the first omitted native shader. The retained callback is
// independent of current Service/runtime/list state and explicitly denies Execute
// until this exact A or B transaction commits its own RR output.
void BeginNativeTransaction(const std::shared_ptr<Service>& owner,
    ID3D12GraphicsCommandList* cmd, uint32_t chain)
{
    std::shared_ptr<NativeTransaction> stage; bool retained = false;
    const auto currentSL=StreamlineHooks::getSLConstantsSnapshot(); // Before injection wait; never a later list's camera.
    try
    {
        std::scoped_lock injection(gInjectionMutex);
        {
            std::scoped_lock lock(gMutex);
            // Runtime OFF can win injection admission after BeforeDispatch chose
            // this action. Its closed binding window is intentional: do not
            // validate raw bindings or poison submission state for disabled RR.
            if (gService != owner || !gRuntime.load(std::memory_order_relaxed)) return;
            const auto found = owner->lists.find(cmd);
            if (found == owner->lists.end() || !ListLive(found->second) ||
                !found->second.nativeContract || chain > 1) return;
        }
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired())
        { RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL); return; }
        FrameSurvey::ComputeBindings bindings; FrameSurvey::BoundConstantBinding constants;
        std::vector<FrameSurvey::BoundResource> sources, outputs;
        constexpr std::array<FrameSurvey::ComputeTableRequest,4> sourceRequests {{
            {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1,1,0},
            {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,2,2,0},{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,3,3,0}}};
        constexpr std::array<FrameSurvey::ComputeTableRequest,2> outputRequests {{
            {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,1,0}}};
        const char* failedGate = nullptr; const char* gateReason = "unavailable";
        FrameSurvey::ConstantBufferDiagnostic constantDiagnostic;
        if (!FrameSurvey::MetadataHealthy()) failedGate = "metadata";
        else if (!D3D12Hooks::CanRestoreRootSignature(cmd))
        { failedGate = "compute_restore"; gateReason = ComputeRestoreReason<D3D12Hooks>(); }
        else if (!D3D12Hooks::BridgePredicationDisabled(cmd)) failedGate = "predication";
        else if (!D3D12Hooks::GetComputeBindingsForBridge(cmd,bindings)) failedGate = "compute_bindings";
        else if (!FrameSurvey::ResolveComputeBindings(bindings,1,sourceRequests,sources) || sources.size()!=4) failedGate = "source_p1";
        else if (!FrameSurvey::ResolveComputeBindings(bindings,5,outputRequests,outputs) || outputs.size()!=2) failedGate = "target_p5";
        else if (!FrameSurvey::ResolveComputeConstantBinding(bindings,6,0,constants,&constantDiagnostic))
        { failedGate = "b6_space0"; gateReason = constantDiagnostic.reason; }
        if (failedGate)
        {
            RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL);
            // A single bounded failure record identifies the actual failed gate;
            // no owner lookup, GPU readback, registry scan or admission relaxation.
            Failure(owner,std::format("RR-only native admission failed gate={} reason={} chain={} cmd={:#x} root={:#x} heaps={} tables={} views={} sources={} targets={} b6_parameter={} b6_table={} b6_base={:#x} b6_va={:#x}; restart required",
                failedGate,gateReason ? gateReason : "unspecified",chain,reinterpret_cast<uintptr_t>(cmd),
                reinterpret_cast<uintptr_t>(bindings.root),bindings.heaps.size(),bindings.tables.size(),bindings.views.size(),
                sources.size(),outputs.size(),constantDiagnostic.rootParameter,constantDiagnostic.table,
                constantDiagnostic.tableBase,constantDiagnostic.address)); return;
        }
        ChainDiscovery typed; std::string error;
        if (!typed.Begin(sources,outputs,error))
        { RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL); Failure(owner,error); return; }
        stage = MakeOwnedShared<NativeTransaction>(); stage->chain = chain;
        std::optional<ListState> retiredList;
        {
            std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
            if (gService != owner || found == owner->lists.end() || !ListLive(found->second) || !found->second.nativeContract ||
                !gRuntime.load(std::memory_order_relaxed) || chain > 1) return;
            auto& list = found->second;
            if (!chain)
            {
                InvalidateSkippedRecording(list); RemoveChainUsers(*owner,cmd,list); StopFollowing(*owner,cmd,list);
                const auto role = list.role; const auto birth = list.birth, pipelineBirth = list.pipelineBirth;auto* pipeline=list.currentPipeline;
                retiredList.emplace(std::move(list)); list = {};
                list.material = std::move(retiredList->pendingMaterial); list.materialStates = std::move(retiredList->materialStates);
                list.materialIdentityRevision = retiredList->materialIdentityRevision;
                list.role = role; list.birth = birth; list.pipelineBirth = pipelineBirth;list.currentPipeline=pipeline;
                list.nativeContract = list.rrOnlyTransaction = list.nativeReconPrepared = true;
                list.followingRecon = list.nrdList = true; list.frame = ++owner->frame; list.chain = typed;
                list.generation = list.frame; list.resetSerial = owner->cancellationSerial;
                owner->followingChains.insert(cmd); RefreshChainUsers(*owner,cmd,list);
                owner->nativeContractSeen = owner->everRecon = owner->observedRecon = owner->windowSawRecon = true;
                stage->streamline = currentSL;
                stage->settings = owner->rrSettings; stage->resetRevision = owner->requestedResetRevision;
                stage->cameraProjectedDepthDelta = owner->cameraProjectedDepthDelta;
            }
            else
            {
                if (!list.native[0] || list.native[1] || !list.temporal || !list.atrous ||
                    list.native[0]->invalidated || list.native[0]->serial != owner->cancellationSerial)
                { RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL); return; }
                stage->streamline = list.native[0]->streamline; stage->settings = list.native[0]->settings;
                stage->resetRevision = list.native[0]->resetRevision;
                stage->cameraProjectedDepthDelta = list.native[0]->cameraProjectedDepthDelta;
                list.chainB = true; list.nativeChain = 1;
            }
            stage->frame = list.frame; stage->serial = owner->cancellationSerial; stage->birth = list.birth;
            std::copy(sources.begin(),sources.end(),stage->sources.begin());
            const auto& material = list.material;
            if (stage->settings.nativeMaterialGuides && material.serial == stage->serial &&
                material.normal == sources[2].resource && material.normalGeneration == sources[2].resourceGeneration &&
                material.normalBirth == sources[2].resourceBirth && BirthLive(material.normalBirth)) stage->material = material.snapshot;
        }
        auto history = owner->nativeHistories[chain];
        const auto width = uint32_t(sources[0].description.Width), height = sources[0].description.Height;
        const bool reusable = history && history->nativeContract && history->semanticChain == chain &&
            history->width == width && history->height == height && history->viewport == stage->streamline.viewport &&
            !history->uncertain.load(std::memory_order_acquire) && history->latestRecording &&
            history->latestRecording->outputCommitted.load(std::memory_order_acquire) &&
            history->latestRecording->phase.load(std::memory_order_acquire) == SubmissionPhase::FencePublished;
        if (!reusable)
        {
            std::erase_if(owner->historyDomains,[](const auto& old) { return old.expired(); });
            if (owner->historyDomains.size() >= 8)
            { RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL); Failure(owner,"RR-only has eight unretired A/B histories; restart required"); return; }
            history = MakeOwnedShared<HistoryDomain>(); history->nativeContract = true; history->semanticChain = chain;
            history->width = width; history->height = height; history->viewport = stage->streamline.viewport;
            history->id = ++owner->nextDomain; owner->historyDomains.push_back(history); owner->nativeHistories[chain] = history;
        }
        owner->history = history; stage->history = history;
        stage->recording = MakeOwnedShared<RecordingToken>(); stage->recording->commitRequired.store(true,std::memory_order_relaxed);
        stage->recording->stages.stopped = &gStagesStopped;
        { std::scoped_lock lock(gMutex); stage->recording->needsStageSamples = gStageCollector.Active(); }
        stage->ownership = MakeOwnedShared<RecordingOwnership>(); stage->ownership->history = history; stage->ownership->token = stage->recording;
        stage->ownership->nativeProof = MakeOwnedShared<NativeCommitProof>();
        stage->ownership->nativeProof->textures.reserve(FrameSurvey::MaximumTextureBindingWitnesses);
        history->latestRecording = stage->recording;
        {
            InjectionScope guard(cmd);
            retained = ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),cmd,stage->ownership,{},RecordingCallbacks(owner,stage->ownership));
        }
        if (!retained)
        { RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY); NativeTransactionFailure(owner,stage,"Could not retain mandatory RR-only recording gate"); return; }
        stage->recording->submissionRetained.store(true,std::memory_order_release);
        auto& proof = *stage->ownership->nativeProof;
        const auto actualRecording=RecordedComputeLease::Capture(cmd);
        if (!actualRecording || !actualRecording->id)
        { NativeTransactionFailure(owner,stage,"Mandatory raw stage has no exact native recording identity"); return; }
        proof.recording=actualRecording;proof.recordingId=actualRecording->id;proof.listBirth=stage->birth;
        std::array<FrameSurvey::TextureTableRequest,4> proofRequests;
        for(size_t index=0;index<proofRequests.size();++index)proofRequests[index]={1,sourceRequests[index]};
        std::vector<FrameSurvey::BoundResource> proofSources;
        std::vector<FrameSurvey::TextureBindingWitness> sourceWitnesses;
        if (!FrameSurvey::ResolveComputeTextureBindings(bindings,proofRequests,proofSources,&sourceWitnesses) ||
            proofSources.size()!=sources.size() || !AppendNativeTextureProof(stage->ownership->nativeProof,sourceWitnesses) ||
            !AppendNativeConstantProof(stage->ownership->nativeProof,bindings,constants,false))
        { NativeTransactionFailure(owner,stage,"Native raw sources have no retained descriptor/constant proof"); return; }
        for(size_t index=0;index<sources.size();++index)
            if (proofSources[index].resource!=sources[index].resource ||
                proofSources[index].resourceGeneration!=sources[index].resourceGeneration ||
                proofSources[index].resourceBirth!=sources[index].resourceBirth)
            { NativeTransactionFailure(owner,stage,"Native raw source descriptor changed during preparation"); return; }
        bool reset = !reusable || history->resetRevision != stage->resetRevision;
        const bool materialApplied = stage->settings.nativeMaterialGuides && NativeMaterialCapture::Resource(stage->material);
        if (stage->settings.nativeMaterialGuides && history->materialGuidesKnown && history->materialGuidesUsed != materialApplied) reset = true;
        if (FSRDGameTraceSession::IsNrdBridgeCaptureActive() && FSRDGameTraceSession::WantsNrdBridgeSignal(chain))
        {
            try { if (!owner->trace) owner->trace = std::make_unique<FSRDGameTraceSession>(); } catch (...) {}
            if (owner->trace && FSRDGameTraceSession::TakeNrdBridgeHistoryResetRequest(history->id)) reset = true;
        }
        RawSignalSource rawSource;
        if (!NativeRawSource(bindings,constants,width,height,chain,owner->device.Get(),rawSource))
        { NativeTransactionFailure(owner,stage,"Raw native signal table cannot be captured exactly"); return; }
        bool prepared = false;
        {
            InjectionScope guard(cmd);
            auto* profile = StageSample(stage->recording);
            NrdBridgeStagePerf::StackTimer prepare(profile,NrdBridgeStagePerf::Stage::ReconPrepare);
            if (reset) { history->rr.ResetHistory(); history->conversion.ResetHistory(); }
            prepared = history->rr.Configure(stage->settings,error) &&
                history->rr.PrepareFrame(stage->streamline,reset,stage->parameters,error);
            stage->parameters.nativeTemporalMotion = stage->settings.nativeTemporalMotion;
            // D01 A/B rollback must reach the native RR-only frame exactly like the
            // conversion path; without this transfer the advertised INI/menu
            // rollback stays false in every native frame parameter set.
            stage->parameters.legacyMotionDepth = stage->settings.legacyMotionDepth;
            stage->parameters.nativeMaterialGuides = stage->settings.nativeMaterialGuides;
            stage->parameters.preserveNativeMaterialIDs = stage->settings.preserveNativeMaterialIDs;
            stage->parameters.cameraProjectedDepthDelta = stage->cameraProjectedDepthDelta;
            if (prepared && stage->settings.lobeRecovery &&
                (stage->settings.recoverySpecular > 0.0f || stage->settings.recoveryDiffuse > 0.0f))
            {
                if (!owner->recoveryFamily) owner->recoveryFamily = CreateRRRecoveryFamily();
                history->rr.SetRecoveryFamily(owner->recoveryFamily);
            }
            if (prepared) prepared = history->conversion.Initialize(owner->device.Get(),width,height,error) &&
                history->rawSignals.Initialize(owner->device.Get(),width,height,error);
            if (prepared) prepared = history->rawSignals.Capture(cmd,rawSource,stage->parameters.streamlineFrame,
                stage->parameters.frameIndex,stage->raw,error);
            prepare.Stop();
            if (prepared)
            {
                NrdBridgeStagePerf::StackTimer geometry(profile,NrdBridgeStagePerf::Stage::ReconConvert);
                const ConversionInputs inputs {nullptr,nullptr,sources[2].resource,sources[3].resource,nullptr,
                    NativeMaterialCapture::Resource(stage->material),NativeMaterialCapture::RoughnessResource(stage->material)};
                prepared = history->conversion.DispatchGeometry(cmd,inputs,stage->parameters,stage->raw,stage->inputs,error);
            }
        }
        if (!prepared) { NativeTransactionFailure(owner,stage,error.empty() ? "Owned native raw/geometry preparation failed" : error); return; }
        bool admitted = false;
        {
            std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
            if (gService == owner && found != owner->lists.end() && found->second.frame == stage->frame &&
                found->second.birth == stage->birth && owner->cancellationSerial == stage->serial && ListLive(found->second))
            {
                auto& list = found->second; list.native[chain] = stage; list.nativeChain = chain;
                stage->geometryReady = true; admitted = true; RefreshChainUsers(*owner,cmd,list);
                history->resetRevision = stage->resetRevision; history->materialGuidesKnown = true; history->materialGuidesUsed = materialApplied;
                owner->status.nativeMaterialGuidesActive = materialApplied;
                if (materialApplied) ++owner->status.nativeMaterialFramesApplied;
                const auto provenance = history->conversion.MotionProvenance();
                owner->status.motionProvenanceDispatches = provenance.dispatches;
                owner->status.motionProvenanceNative = provenance.native;
                owner->status.motionProvenanceCameraOnly = provenance.cameraOnly;
                owner->status.motionProvenanceUnknown = provenance.unknown;
                owner->status.motionProvenanceLegacy = provenance.legacyVisible;
                owner->rrSettingsState = history->rr.GetSettingsState(); owner->rrSettingsState.requested = owner->rrSettings;
                gNativeTransactions.store(true,std::memory_order_release);
            }
        }
        if (!admitted) NativeTransactionFailure(owner,stage,"Native source recording changed before required transaction publication");
        else
        {
            {std::scoped_lock lock(gMutex);if(gService==owner)
             {bool legacy=false;for(const auto& [listKey,list]:owner->lists)legacy |= list.followingRecon&&!list.rrOnlyTransaction;owner->window=legacy;}}
            PublishBindingWindow(); // Native resolvers use current snapshots rather than the weak mirror window.
        }
    }
    catch (...)
    {
        if (!retained) RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);
        if (stage && stage->recording) stage->recording->skipInvalidated.store(true,std::memory_order_release);
        CoordinatorException("Exception while preparing mandatory native raw transaction");
    }
}


void PrepareNativeMotion(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd)
{
    std::scoped_lock injection(gInjectionMutex);
    NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
    std::shared_ptr<NativeTransaction> stage;
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end()) return;
        auto& list = found->second; stage = list.native[list.nativeChain];
        if (!NativeTransactionCurrent(*owner,list,stage) || !stage->geometryReady || stage->motionReady ||
            list.role != Role::Temporal || !list.nativeContract) return;
    }
    FrameSurvey::ComputeBindings bindings; FrameSurvey::BoundConstantBinding constants;
    std::vector<FrameSurvey::BoundResource> motion;
    constexpr std::array<FrameSurvey::ComputeTableRequest,1> request {{{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,2,2,0}}};
    if (!FrameSurvey::MetadataHealthy() || !D3D12Hooks::CanRestoreRootSignature(cmd) ||
        !D3D12Hooks::BridgePredicationDisabled(cmd) || !D3D12Hooks::GetComputeBindingsForBridge(cmd,bindings) ||
        !FrameSurvey::ResolveComputeBindings(bindings,1,request,motion) || motion.size()!=1 ||
        motion[0].viewFormat != DXGI_FORMAT_R16G16B16A16_FLOAT || motion[0].subresource ||
        motion[0].description.Width != stage->inputs.width || motion[0].description.Height != stage->inputs.height ||
        !FrameSurvey::ResolveComputeConstantBinding(bindings,6,0,constants))
    { NativeTransactionFailure(owner,stage,"Native Temporal has no exact current motion/constant/root proof"); return; }
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end() || !NativeTransactionCurrent(*owner,found->second,stage)) return;
        if (owner->taggedMotion && (owner->taggedMotion != motion[0].resource ||
            (BirthMode() && owner->taggedMotionBirth != motion[0].resourceBirth)))
        { stage->invalidated = true; stage->recording->skipInvalidated.store(true,std::memory_order_release); }
    }
    if (stage->invalidated) { NativeTransactionFailure(owner,stage,"Native Temporal differs from the current Streamline motion tag"); return; }
    const std::array<FrameSurvey::TextureTableRequest,1> motionRequest {{{1,request[0]}}};
    std::vector<FrameSurvey::BoundResource> proofMotion;
    std::vector<FrameSurvey::TextureBindingWitness> motionWitnesses;
    if (!FrameSurvey::ResolveComputeTextureBindings(bindings,motionRequest,proofMotion,&motionWitnesses) ||
        proofMotion.size()!=1 || proofMotion[0].resource!=motion[0].resource ||
        proofMotion[0].resourceGeneration!=motion[0].resourceGeneration || proofMotion[0].resourceBirth!=motion[0].resourceBirth ||
        !AppendNativeTextureProof(stage->ownership->nativeProof,motionWitnesses) ||
        !AppendNativeConstantProof(stage->ownership->nativeProof,bindings,constants,false))
    { NativeTransactionFailure(owner,stage,"Native motion lost its retained descriptor/constant proof"); return; }
    std::string error; bool ready = true;
    {
        InjectionScope guard(cmd);
        NativeMotionSource native;
        if (stage->parameters.nativeTemporalMotion)
        {
            ready = stage->history->nativeTemporalCapture.Initialize(owner->device.Get(),error) &&
                stage->history->nativeTemporalCapture.Capture(cmd,constants,stage->temporalConstants,error);
            native.constants = NativeTemporalCapture::Resource(stage->temporalConstants);
            native.viewDepth = stage->history->conversion.OwnedPositiveViewDepth(stage->inputs,stage->parameters);
            ready = ready && native.constants && native.viewDepth;
        }
        if (ready) ready = DispatchCurrentMotion(stage->history->conversion,cmd,stage->inputs,motion[0].resource,stage->parameters,error,native);
    }
    if (!ready) { NativeTransactionFailure(owner,stage,error.empty() ? "Owned native motion preparation failed" : error); return; }
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end() || !NativeTransactionCurrent(*owner,found->second,stage)) return;
        stage->motion = motion[0]; stage->motionReady = true;
        auto& list = found->second;
        if (!stage->chain)
        {
            if (!list.chain.Observe(Role::Temporal,motion,{},owner->taggedMotion,error))
            { stage->invalidated = true; stage->recording->skipInvalidated.store(true,std::memory_order_release); }
        }
        list.temporal = true; RefreshChainUsers(*owner,cmd,list);
    }
    if (stage->invalidated) NativeTransactionFailure(owner,stage,error.empty() ? "Native motion chain identity failed" : error);
}


bool SameNativeTexture(const FrameSurvey::BoundResource& a, const FrameSurvey::BoundResource& b) noexcept
{
    return a.resource && a.resource == b.resource && a.resourceGeneration == b.resourceGeneration &&
        a.resourceBirth == b.resourceBirth && a.viewFormat == b.viewFormat && a.subresource == b.subresource &&
        a.description.Width == b.description.Width && a.description.Height == b.description.Height;
}
bool NativeTargets(const FrameSurvey::ComputeBindings& bindings, bool graphics,
    std::vector<FrameSurvey::BoundResource>& out, std::vector<FrameSurvey::TextureBindingWitness>* witnesses=nullptr) noexcept
{
    constexpr std::array<FrameSurvey::TextureTableRequest,2> compute {{{5,
        {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0,0,0}},{5,{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,1,0}}}};
    constexpr std::array<FrameSurvey::TextureTableRequest,2> pixel {{{24,
        {D3D12_DESCRIPTOR_RANGE_TYPE_SRV,3,11,0}},{24,{D3D12_DESCRIPTOR_RANGE_TYPE_SRV,4,12,0}}}};
    return graphics ? FrameSurvey::ResolveGraphicsTextureBindings(bindings,pixel,out,witnesses) :
        FrameSurvey::ResolveComputeTextureBindings(bindings,compute,out,witnesses);
}

bool NativeConstants(const FrameSurvey::ComputeBindings& bindings, bool graphics,
    FrameSurvey::BoundConstantBinding& out) noexcept
{
    return graphics ? FrameSurvey::ResolveGraphicsConstantBinding(bindings,6,0,out) :
        FrameSurvey::ResolveComputeConstantBinding(bindings,6,0,out);
}
bool ValidateNativeConstants(const FrameSurvey::ComputeBindings& bindings, bool graphics,
    const FrameSurvey::BoundConstantBinding& expected) noexcept
{
    return graphics ? FrameSurvey::ValidateGraphicsConstantBinding(bindings,6,0,expected) :
        FrameSurvey::ValidateComputeConstantBinding(bindings,6,0,expected);
}
struct NativeInjectionScope
{
    ID3D12GraphicsCommandList* list;
    bool graphics, previousTracking;
    std::shared_ptr<RecordingToken> token;
    FrameSurvey::ScopedInternal survey;
    NativeInjectionScope(ID3D12GraphicsCommandList* cmd, bool pixel, const std::shared_ptr<RecordingToken>& recording)
        : list(cmd), graphics(pixel), previousTracking(D3D12Hooks::RootSignatureTrackingEnabled()), token(recording)
    { D3D12Hooks::SetRootSignatureTracking(false); }
    ~NativeInjectionScope()
    {
        bool restored=false;
        if (graphics) restored=D3D12Hooks::RestoreGraphicsRootForBridge(list);
        else if (D3D12Hooks::CanRestoreRootSignature(list)) { D3D12Hooks::RestoreRoot(list);restored=true; }
        if(!restored && token) token->skipInvalidated.store(true,std::memory_order_release);
        D3D12Hooks::SetRootSignatureTracking(previousTracking);
    }
};
thread_local const char* gNativeWorkFailure="unclassified_work";
// Narrow sub-reason detail for the last rejected gate. Diagnostic/audit only:
// it is never read by an admission decision and no whitelist is derived from it.
thread_local const char* gNativeWorkDetail=nullptr;
bool PreserveNativeWork(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd,
    ID3D12CommandSignature* signature, bool pixel)
{
    gNativeWorkFailure="unclassified_work";gNativeWorkDetail=nullptr;
    const auto reject=[](const char* gate){gNativeWorkFailure=gate;return false;};
    const auto rejectDetail=[](const char* gate,const char* detail){gNativeWorkFailure=gate;gNativeWorkDetail=detail;return false;};
    // Caller owns injection serialization and physical Borrow. Only recognized
    // pipeline candidates reach binding vectors/metadata snapshots.
    std::array<std::shared_ptr<NativeTransaction>,2> pending;
    ID3D12PipelineState* pipeline=nullptr;InterveningPipeline selected;size_t count=0;
    {
        std::scoped_lock lock(gMutex);const auto found=owner->lists.find(cmd);
        if(gService!=owner||found==owner->lists.end()||!ListLive(found->second))return reject("work_list_birth");
        const auto& list=found->second;pipeline=list.currentPipeline;selected=list.intervening;
        // Fail-closed: every sub-reason below still rejects the unknown work. The
        // full-hash identity/overlap contract for this pipeline is never inferred
        // from selection state alone.
        if(!pipeline)return rejectDetail("work_pipeline_profile","pipeline_absent");
        if(selected.profile<0)return rejectDetail("work_pipeline_profile","profile_unclassified");
        if(selected.birth!=list.pipelineBirth)return rejectDetail("work_pipeline_profile","pipeline_birth_changed");
        for(const auto& stage:list.native)if(stage&&!stage->committed&&!stage->invalidated)pending[count++]=stage;
    }
    if(!count)return true;
    FrameSurvey::PipelineShaderIdentity identity;
    if(!D3D12Hooks::BridgePredicationDisabled(cmd)||!FrameSurvey::ResolvePipelineShaderIdentity(pipeline,identity)||
        !identity.complete||identity.pipelineBirth!=selected.birth)return reject("work_pipeline_identity_or_predication");
    if(pixel?identity.presentStages!=(FrameSurvey::PipelineVS|FrameSurvey::PipelinePS):identity.presentStages!=FrameSurvey::PipelineCS)return reject("work_pipeline_stages");
    if(!selected.testing)
    {
        if(pixel)
        {
            if(selected.profile<2||selected.profile>4||std::string_view(identity.pixel.data())!=NativeInterveningPS[selected.profile-2]||
                std::string_view(identity.vertex.data())!=NativeInterveningVS[selected.profile-2])return reject("work_graphics_hashes");
        }
        else if(selected.profile>1||InterveningComputeProfile(identity.compute.data())!=selected.profile)return reject("work_compute_hash");
    }
    FrameSurvey::IndirectSignatureInfo indirect;
    if(signature&&(!FrameSurvey::ResolveIndirectSignature(signature,indirect)||
        indirect.kind!=(pixel?FrameSurvey::IndirectSignatureKind::DrawIndexed:FrameSurvey::IndirectSignatureKind::Dispatch)||
        indirect.byteStride!=(pixel?20u:12u)))return reject("work_indirect_signature");
    // These exact shader families have only fixed Texture2D accesses; structured
    // buffer and cube declarations cannot alias single-slice B Texture2D targets.
    // A graphics draw can also write RTV/DSV. RTV capability alone is not an
    // overlap: the native B outputs themselves have RTV|UAV flags. Check the
    // actual bind-time outputs. Keep the depth-capable target case denied.
    bool needsRasterOutputs=false;
    for(size_t index=0;index<count;++index)for(const auto& target:pending[index]->targets)
    {
        if(!target.resource||target.description.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||target.description.DepthOrArraySize!=1)return reject("work_target_dimension");
        if(pixel&&(target.description.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL))return reject("work_target_depth_capability");
        needsRasterOutputs|=pixel && (target.description.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    }
    FrameSurvey::RecordedRenderTargets rasterOutputs;
    if(needsRasterOutputs)
    {
        if(!FrameSurvey::ResolveRecordedRenderTargets(cmd,rasterOutputs))return reject("raster_outputs_unknown");
        for(UINT output=0;output<rasterOutputs.count;++output)
            for(size_t index=0;index<count;++index)for(const auto& target:pending[index]->targets)
                if(rasterOutputs.targets[output].resource==target.resource ||
                    (rasterOutputs.targets[output].birth && target.resourceBirth &&
                     rasterOutputs.targets[output].birth->InstanceStamp()==target.resourceBirth->InstanceStamp()))return reject("raster_output_overlap");
    }
    std::array<FrameSurvey::TextureTableRequest,9> requests;size_t requestCount=0;
    auto add=[&](D3D12_DESCRIPTOR_RANGE_TYPE kind,UINT reg){requests[requestCount++]={UINT_MAX,{kind,UINT_MAX,reg,0}};};
    if(selected.profile==0){add(D3D12_DESCRIPTOR_RANGE_TYPE_SRV,0);add(D3D12_DESCRIPTOR_RANGE_TYPE_SRV,1);add(D3D12_DESCRIPTOR_RANGE_TYPE_SRV,64);add(D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0);}
    else if(selected.profile==1){for(const UINT reg:{0u,1u,2u,4u,5u,9u,12u})add(D3D12_DESCRIPTOR_RANGE_TYPE_SRV,reg);add(D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0);add(D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1);}
    else if(selected.profile==3){for(const UINT reg:{1u,2u,4u})add(D3D12_DESCRIPTOR_RANGE_TYPE_SRV,reg);}
    else if(selected.profile==4){for(const UINT reg:{3u,5u,6u,68u})add(D3D12_DESCRIPTOR_RANGE_TYPE_SRV,reg);}
    FrameSurvey::ComputeBindings bindings;ID3D12PipelineState* current=nullptr;
    if(!(pixel?D3D12Hooks::GetGraphicsBindingsForBridge(cmd,bindings,current):D3D12Hooks::GetComputeBindingsForBridge(cmd,bindings))||
        (pixel&&current!=pipeline))return reject("work_root_bindings");
    std::vector<FrameSurvey::BoundResource> resources;
    std::vector<FrameSurvey::TextureBindingWitness> witnesses;
    if(requestCount)
    {
        const auto requested=std::span(requests.data(),requestCount);
        FrameSurvey::TextureBindingDiagnostic diagnostic;
        constexpr auto purpose=FrameSurvey::TextureBindingPurpose::ResourceExclusion;
        if(!(pixel?FrameSurvey::ResolveGraphicsTextureBindings(bindings,requested,resources,&witnesses,purpose,&diagnostic):
            FrameSurvey::ResolveComputeTextureBindings(bindings,requested,resources,&witnesses,purpose,&diagnostic))||resources.size()!=requestCount)
        {
            LOG_ERROR("[NRD_BRIDGE] work texture binding failed reason={} profile={} request={} kind={} register={} space={} root_parameter={} descriptor_offset={} descriptor_cpu={:#x} view_format={} snapshot_supported={} texture2D={}",
                diagnostic.reason,selected.profile,diagnostic.request,uint32_t(diagnostic.kind),diagnostic.shaderRegister,
                diagnostic.registerSpace,diagnostic.parameter,diagnostic.descriptorOffset,diagnostic.descriptorCpu,
                uint32_t(diagnostic.viewFormat),diagnostic.snapshotSupported,diagnostic.texture2D);
            return reject("work_texture_bindings");
        }
        for(const auto& resource:resources)for(size_t index=0;index<count;++index)for(const auto& target:pending[index]->targets)
            if(resource.resource==target.resource || (resource.resourceBirth&&target.resourceBirth&&
                resource.resourceBirth->InstanceStamp()&&resource.resourceBirth->InstanceStamp()==target.resourceBirth->InstanceStamp()))return reject("work_texture_overlap");
    }
    for(size_t index=0;index<count;++index)
    {
        auto& proof=*pending[index]->ownership->nativeProof;
        if(needsRasterOutputs)
        {
            if(rasterOutputs.receiverBirth!=proof.listBirth)return reject("raster_proof_capacity_or_birth");
            // Only distinct bind-time sets need retention; repeated actor draws
            // into the same output must not consume a finite proof slot each time.
            const auto end=proof.rasterOutputs.begin()+proof.rasterOutputCount;
            if(std::find(proof.rasterOutputs.begin(),end,rasterOutputs)==end)
            {
                if(proof.rasterOutputCount==proof.rasterOutputs.size())return reject("raster_proof_capacity_or_birth");
                proof.rasterOutputs[proof.rasterOutputCount++]=rasterOutputs;
            }
        }
        if(requestCount&&!AppendNativeTextureProof(pending[index]->ownership->nativeProof,witnesses))return reject("work_texture_proof_capacity");
        bool known=false;for(size_t p=0;p<proof.pipelineCount;++p)known|=proof.pipelines[p].pipeline==identity.pipeline&&proof.pipelines[p].pipelineBirth==identity.pipelineBirth;
        if(!known){if(proof.pipelineCount==proof.pipelines.size())return reject("work_pipeline_proof_capacity");proof.pipelines[proof.pipelineCount++]=identity;}
        if(signature)
        {
            known=false;for(size_t p=0;p<proof.signatureCount;++p)known|=proof.signatures[p].signature==signature&&proof.signatures[p].birth==indirect.birth;
            if(!known){if(proof.signatureCount==proof.signatures.size())return reject("work_signature_proof_capacity");proof.signatures[proof.signatureCount++]=indirect;}
        }
    }
    return true;
}
void CommitNativeTransaction(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, bool graphics)
{
    std::shared_ptr<NativeTransaction> stage;
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || found == owner->lists.end()) return;
        auto& list = found->second; stage = list.native[graphics ? 1 : 0];
        if (!NativeTransactionCurrent(*owner,list,stage) || !stage->geometryReady || !stage->motionReady ||
            (graphics ? !list.graphicsConsumerCandidate : list.role != Role::Consumer || !list.nativeContract)) return;
    }
    NrdBridgeStagePerf::Sample complete {}; bool sampled = false, committed = false;
    {
        std::unique_lock injection(gInjectionMutex);
        NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return;
        auto* profile = StageSample(stage->recording);
        NrdBridgeStagePerf::StackTimer physical(profile,NrdBridgeStagePerf::Stage::ConsumerPhysicalHold);
        FrameSurvey::ComputeBindings bindings; ID3D12PipelineState* pixelPipeline = nullptr;
        auto currentBindings = [&]() {
            return graphics ? D3D12Hooks::GetGraphicsBindingsForBridge(cmd,bindings,pixelPipeline) :
                D3D12Hooks::GetComputeBindingsForBridge(cmd,bindings);
        };
        FrameSurvey::BoundConstantBinding constants; std::vector<FrameSurvey::BoundResource> targets; targets.reserve(2);
        std::vector<FrameSurvey::TextureBindingWitness> targetWitnesses;targetWitnesses.reserve(2);
        if (!FrameSurvey::MetadataHealthy() || !D3D12Hooks::BridgePredicationDisabled(cmd) ||
            !(graphics ? D3D12Hooks::CanRestoreGraphicsRootSignature(cmd) : D3D12Hooks::CanRestoreRootSignature(cmd)) ||
            !currentBindings() || !NativeTargets(bindings,graphics,targets,&targetWitnesses) || targets.size()!=2 ||
            !NativeConstants(bindings,graphics,constants))
        { NativeTransactionFailure(owner,stage,"Late native Consumer binding/root/predicate proof is unavailable"); return; }
        NativeMaterialStateWitness::SourceStates targetStates {D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
        bool valid = false; ChainDiscovery discovered; bool publish = false;
        {
            std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
            if (gService != owner || found == owner->lists.end() || !NativeTransactionCurrent(*owner,found->second,stage)) return;
            auto& list = found->second;
            valid = SameNativeTexture(targets[0],stage->targets[1]) && SameNativeTexture(targets[1],stage->targets[0]);
            if (graphics)
            {
                valid = valid && list.graphicsConsumerCandidate && pixelPipeline == list.graphicsConsumer &&
                    BirthLive(list.graphicsConsumerBirth) && stage->targetStates.TryKnownStates(stage->serial,targetStates);
                constexpr auto writable = D3D12_RESOURCE_STATE_RENDER_TARGET | D3D12_RESOURCE_STATE_UNORDERED_ACCESS |
                    D3D12_RESOURCE_STATE_DEPTH_WRITE | D3D12_RESOURCE_STATE_COPY_DEST | D3D12_RESOURCE_STATE_RESOLVE_DEST;
                for (const auto state : targetStates)
                    valid = valid && (state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE) && !(state & writable);
            }
            else
            {
                std::string error;
                valid = valid && list.chain.Observe(Role::Consumer,{},targets,owner->taggedMotion,error);
                if (valid)
                {
                    publish = owner->cache.Publish(list.chain); owner->cacheBirths = CacheBirths(list.chain);
                    discovered = list.chain; owner->status.width = stage->inputs.width; owner->status.height = stage->inputs.height;
                    owner->status.resources = ResourceSummary(list.chain.Get()); owner->attempts = 0;
                }
            }
            RefreshChainUsers(*owner,cmd,list);
        }
        if (!valid) { NativeTransactionFailure(owner,stage,"Late Consumer pair/state differs from this exact native transaction"); return; }
        if (publish) LogDiscovery(discovered,nullptr);
        if (!AppendNativeTextureProof(stage->ownership->nativeProof,targetWitnesses) ||
            !AppendNativeConstantProof(stage->ownership->nativeProof,bindings,constants,graphics))
        { NativeTransactionFailure(owner,stage,"Late Consumer has no retained native target/constant proof"); return; }
        std::string error;
        FrameParameters commitFrame = stage->parameters;
        const TitleSignalConstants nativeConstants {nullptr,constants.address,constants.descriptorHeap,constants.descriptor,graphics ? 36u : 303u};
        bool ready = false;
        {
            NativeInjectionScope guard(cmd,graphics,stage->recording);
            // D02/WP08 experiment selector; the gated profile fails closed without
            // this frame's owned validity channel, so flipping it cannot degrade
            // the production path.
            ready = stage->history->rawSignals.Decode(cmd,stage->raw,stage->inputs,nativeConstants,error,
                stage->history->rr.GetSettingsState().requested.surfaceValidFill);
            if (ready)
            {
                const auto decoded = RawSignalSnapshotPass::GetSnapshot(stage->raw);
                ready = decoded.decoded && decoded.recording == cmd && decoded.frameSL == stage->parameters.streamlineFrame &&
                    decoded.bridgeFrame == stage->parameters.frameIndex;
                commitFrame.outputConstants = decoded.decodedEncodingConstants;
            }
            if (ready)
            {
                NrdBridgeStagePerf::StackTimer provider(profile,NrdBridgeStagePerf::Stage::ConsumerRRDispatch);
                ready = stage->history->rr.RecordOwned(cmd,stage->inputs,stage->parameters,stage->owned,error,profile);
                if (ready) stage->history->latestOwned = stage->owned;
            }
        }
        if (!ready) { NativeTransactionFailure(owner,stage,error.empty() ? "Owned raw decode / signed RR recording failed" : error); return; }
        if (FSRDGameTraceSession::IsNrdBridgeCaptureActive() && FSRDGameTraceSession::WantsNrdBridgeSignal(stage->chain) && owner->trace)
        {
            const auto snapshot = stage->history->rr.GetOwnedOutputSnapshot(stage->owned);
            stage->traceIdentity = {stage->history->id,snapshot.recordingId,stage->frame,stage->serial,0,stage->parameters.streamlineFrame};
            const auto settings = stage->history->rr.GetSettingsState();
            stage->trace = owner->trace->RecordBridgeOwned(owner->device.Get(),cmd,stage->traceIdentity,stage->inputs,
                stage->ownership,stage->parameters,stage->streamline.constants,stage->streamline.frameIndex,stage->streamline.viewport,
                settings,snapshot,{stage->history->rr.GetOwnedOutputProviderAttestation(stage->owned)},true);
            if (stage->trace)
            {
                for (uint32_t i=0;i<stage->skipCount;++i) owner->trace->RecordBridgeSkipped(stage->trace,cmd,stage->traceIdentity,stage->skipped[i]);
                const auto raw=RawSignalSnapshotPass::GetSnapshot(stage->raw);
                FSRDGameTraceSession::BridgeControlHeader control;
                control.profile=stage->chain?FSRDGameTraceSession::BridgeControlHeader::Profile::PrePassB:
                    FSRDGameTraceSession::BridgeControlHeader::Profile::ReconA;
                control.image={raw.resource,raw.state};control.owner=raw.owner;control.recordingId=raw.recordingId;
                control.streamlineFrame=raw.frameSL;control.bridgeFrame=raw.bridgeFrame;
                constexpr std::array<uint32_t,4> aOffsets{448,452,456,460};
                constexpr std::array<uint32_t,8> bOffsets{456,460,472,476,516,520,576,580};
                control.wordCount=stage->chain?uint32_t(bOffsets.size()):uint32_t(aOffsets.size());
                for(uint32_t index=0;index<control.wordCount;++index)
                {const auto offset=stage->chain?bOffsets[index]:aOffsets[index];control.words[index]={offset,offset};}
                control.hasStatus=raw.hasStatus;control.statusByteOffset=raw.statusByteOffset;
                control.statusObserver=+[](const FSRDGameTraceSession::BridgeIdentity&,uint32_t)noexcept{
                    RecordedComputeLease::FailUntrackedRequiredSubmission(E_INVALIDARG);
                };
                // Optional forensic copies only. Raw B's always-on completion
                // observer enforces future-fatal status independently of Trace.
                owner->trace->RecordBridgeControlHeader(stage->trace,cmd,stage->traceIdentity,control);
            }
        }
        struct Ticket
        {
            Service* owner; ID3D12GraphicsCommandList* cmd; std::shared_ptr<NativeTransaction> stage;
            bool graphics; ID3D12PipelineState* pixel; FrameSurvey::BoundConstantBinding constants;
            std::array<FrameSurvey::BoundResource,2> targets; NativeMaterialStateWitness::SourceStates states;
            FrameSurvey::ComputeBindings bindings; std::vector<FrameSurvey::BoundResource> scratch;
            bool cancelled = false;
            static bool Admit(void* value, OutputCommitGuard::Action action, void* prepared) noexcept
            {
                auto& t = *static_cast<Ticket*>(value); std::scoped_lock lock(gMutex);
                const auto found = t.owner->lists.find(t.cmd);
                if (gService.get()!=t.owner || !gRuntime.load(std::memory_order_relaxed) || !FrameSurvey::MetadataHealthy() ||
                    found==t.owner->lists.end() || !NativeTransactionCurrent(*t.owner,found->second,t.stage) ||
                    !D3D12Hooks::BridgePredicationDisabled(t.cmd)) { t.cancelled=true;return false; }
                ID3D12PipelineState* pixel = nullptr;
                const bool current = t.graphics ? D3D12Hooks::GetGraphicsBindingsForBridge(t.cmd,t.bindings,pixel) :
                    D3D12Hooks::GetComputeBindingsForBridge(t.cmd,t.bindings);
                if (!current || (t.graphics && (pixel!=t.pixel || !found->second.graphicsConsumerCandidate)) ||
                    !ValidateNativeConstants(t.bindings,t.graphics,t.constants) || !NativeTargets(t.bindings,t.graphics,t.scratch) || t.scratch.size()!=2 ||
                    !SameNativeTexture(t.scratch[0],t.targets[0]) || !SameNativeTexture(t.scratch[1],t.targets[1]))
                { t.cancelled=true;return false; }
                D3D12_RESOURCE_BARRIER barriers[2] {};
                if (t.graphics)
                {
                    NativeMaterialStateWitness::SourceStates currentStates;
                    if (!t.stage->targetStates.TryKnownStates(t.stage->serial,currentStates) || currentStates!=t.states)
                    { t.cancelled=true;return false; }
                    for (size_t i=0;i<2;++i)
                    {
                        barriers[i].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
                        // states/targets are spec,diff internally; current pixel SRVs are diff,spec.
                        barriers[i].Transition={t.stage->targets[i].resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                            t.states[i],D3D12_RESOURCE_STATE_UNORDERED_ACCESS};
                    }
                    t.cmd->ResourceBarrier(2,barriers);
                }
                action(prepared);
                if (t.graphics)
                {
                    for (auto& barrier:barriers) std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);
                    t.cmd->ResourceBarrier(2,barriers);
                }
                t.stage->ownership->nativeProof->sealed.store(true,std::memory_order_release);
                t.stage->recording->outputCommitted.store(true,std::memory_order_release);
                t.stage->committed.store(true,std::memory_order_release);
                t.owner->status.active=true;t.owner->activeFrame=t.stage->frame;t.owner->failures=0;
                t.owner->status.phase="Active";
                if (!t.owner->status.runtimeDisablePending) t.owner->status.reason.clear();
                ++t.owner->status.framesBridged;
                if(t.stage->parameters.reset) ++t.owner->status.resets;
                bool pending=false;for(const auto& other:found->second.native) pending |= other && !other->committed && !other->invalidated;
                if (!pending) StopFollowing(*t.owner,t.cmd,found->second);
                RefreshNativeTransactions(*t.owner);
                bool legacy=false;for(const auto& [listKey,list]:t.owner->lists)legacy |= list.followingRecon&&!list.rrOnlyTransaction;
                t.owner->window=legacy;return true;
            }
        } ticket {owner.get(),cmd,stage,graphics,pixelPipeline,constants,{targets[0],targets[1]},targetStates};
        ticket.scratch.reserve(2); ticket.bindings.heaps.reserve(2); ticket.bindings.heapBirths.reserve(2);
        ticket.bindings.tables.reserve(64); ticket.bindings.views.reserve(64);
        {
            NativeInjectionScope guard(cmd,graphics,stage->recording);
            ready = stage->history->rr.CommitOwned(cmd,stage->owned,targets[1].resource,targets[0].resource,commitFrame,error,
                {&ticket,Ticket::Admit},profile);
        }
        if (!ready || !RequiredOutputComplete(*stage->recording))
        { NativeTransactionFailure(owner,stage,error.empty() ? "Mandatory native RR output admission or root restoration failed" : error); return; }
        committed=stage->recording->outputCommitted.load(std::memory_order_acquire);
        if (stage->trace && owner->trace)
        {
            const auto snapshot=stage->history->rr.GetOwnedOutputSnapshot(stage->owned);
            // Final sources are encoded title targets; no native filtered RGB is used by RR or Commit.
            const std::array<FSRDGameTraceSession::Source,2> outputs {{
                {targets[1].resource,graphics ? targetStates[0] : D3D12_RESOURCE_STATE_UNORDERED_ACCESS},
                {targets[0].resource,graphics ? targetStates[1] : D3D12_RESOURCE_STATE_UNORDERED_ACCESS}}};
            owner->trace->CompleteBridgeFrame(stage->trace,cmd,stage->traceIdentity,outputs,snapshot,nativeConstants);
        }
        if (committed) CaptureNativeDebugSource(owner,cmd,*stage);
        physical.Stop();
        {
            std::scoped_lock lock(gMutex); const auto found=owner->lists.find(cmd);
            if (gService==owner)
            {
                owner->rrSettingsState=stage->history->rr.GetSettingsState();owner->rrSettingsState.requested=owner->rrSettings;
                if(found!=owner->lists.end())
                {
                    const auto& a=found->second.native[0];const auto& b=found->second.native[1];
                    if(a && a->committed && (!b || b->committed) && a->recording->needsStageSamples)
                    {
                        complete=a->recording->stages;
                        if(b) MergeStageSamples(complete,b->recording->stages);
                        sampled=true;
                    }
                }
            }
        }
        physical.Stop();
    }
    // Report/callbacks run after coordinator, injection and physical lifetime guards.
    PublishBindingWindow();
    if(sampled) CompleteStageSample(stage->parameters.streamlineFrame,complete,committed);
}


void ObserveNativeDispatch(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, Role role)
{
    NrdBridgeLifetime::ScopedBorrow borrow;if(!borrow.Acquired())return;
    FrameSurvey::ComputeBindings bindings;std::vector<FrameSurvey::BoundResource> targets;
    if(role==Role::ATrous)
    {
        constexpr std::array<FrameSurvey::ComputeTableRequest,2> request {{
            {D3D12_DESCRIPTOR_RANGE_TYPE_UAV,0,0,0},{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,1,0}}};
        if(!D3D12Hooks::GetComputeBindingsForBridge(cmd,bindings) ||
            !FrameSurvey::ResolveComputeBindings(bindings,5,request,targets) || targets.size()!=2)
        { Failure(owner,"Native ATrous output profile unavailable after an omitted dispatch");return; }
    }
    std::scoped_lock lock(gMutex);const auto found=owner->lists.find(cmd);
    if(gService!=owner || found==owner->lists.end())return;
    auto& list=found->second;const auto& stage=list.native[list.nativeChain];
    if(!NativeTransactionCurrent(*owner,list,stage))return;
    std::string error;
    if(role==Role::ATrous)
    {
        for(const auto& target:targets)
            if(target.viewFormat!=DXGI_FORMAT_R16G16B16A16_FLOAT || target.subresource ||
                target.description.Width!=stage->inputs.width || target.description.Height!=stage->inputs.height ||
                !(target.description.Flags&D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS))
            { stage->invalidated=true;stage->recording->skipInvalidated.store(true,std::memory_order_release);return; }
        stage->targets={targets[0],targets[1]};stage->targetStates.Select(targets[0],targets[1]);
        list.atrous=true;
    }
    if(role==Role::Temporal)list.temporal=true;
    if(role!=Role::Recon && role!=Role::Temporal && role!=Role::Consumer &&
        !list.chain.Observe(role,{},targets,owner->taggedMotion,error))
    { stage->invalidated=true;stage->recording->skipInvalidated.store(true,std::memory_order_release); }
    list.currentDispatchSuppressed=false;RefreshChainUsers(*owner,cmd,list);
}

}
bool SupportedExecutable() noexcept
{
    try
    {
        static const bool supported = [] {
            auto executable = Util::ExePath().filename().string();
            for (auto& character : executable) character = char(std::tolower(static_cast<unsigned char>(character)));
            return executable == "cyberpunk2077.exe";
        }();
        return supported;
    } catch (...) { return false; }
}
enum class NativeRetirementStartup { LegacyAdapter, Ready, Failed };
template<class Tracker> NativeRetirementStartup ConfigureNativeRetirement() noexcept
{
    if constexpr (requires { Tracker::ConfigureNrdNativeBirthRetirement(); })
        return Tracker::ConfigureNrdNativeBirthRetirement() ? NativeRetirementStartup::Ready : NativeRetirementStartup::Failed;
    return NativeRetirementStartup::LegacyAdapter; // Minimal test adapters deliberately retain the legacy gate.
}
void ConfigureStartup(bool enabled) noexcept
{
    int unconfigured = -1;
    if (!gStartupSelection.compare_exchange_strong(unconfigured,-2,std::memory_order_acq_rel,std::memory_order_relaxed)) return;
    // Only the initial winner may configure native retirement. In particular,
    // startup OFF remains side-effect free when later callers request ON.
    bool accepted = enabled && SupportedExecutable();
    if (accepted && ConfigureNativeRetirement<ResTrack_Dx12>() == NativeRetirementStartup::Failed)
    {
        constexpr const char* reason = "Native title lifetime initialization failed; restart the title/device";
        gStartupFailure.store(reason,std::memory_order_release);
        FrameSurvey::MetadataHookFailed(reason); NrdBridgeBirth::Fail();
        accepted = false;
    }
    gStartupSelection.store(accepted ? 1 : 0,std::memory_order_release);
}
bool StartupEnabled() noexcept
{
    return gStartupSelection.load(std::memory_order_acquire) == 1;
}
// Session-long hook cost row, every ~10 s. Frame counts come from Streamline frame
// ids, so they are real rendered frames (Frame Generation presents do not count).
void ReportPeriodicPerf(const NrdBridgePerf::Periodic::Interval& interval) noexcept
{
    try
    {
        using H = NrdBridgePerf::Hook;
        namespace P = NrdBridgePerf::Periodic;
        static uint32_t lastSlFrame = UINT32_MAX;
        const uint32_t slFrame = StreamlineHooks::getSLConstantsSnapshot().frameIndex;
        uint64_t frames = 0;
        if (slFrame != UINT32_MAX && lastSlFrame != UINT32_MAX && slFrame >= lastSlFrame) frames = slFrame-lastSlFrame;
        lastSlFrame = slFrame;
        const double perFrame = frames ? 1.0/double(frames) : 0.0;
        const auto& d = interval.delta;
        uint64_t hookTicks = 0, waitTicks = 0;
        for (size_t i=0;i<d.ticks.size();++i) { hookTicks += d.ticks[i]; waitTicks += d.waitTicks[i]; }
        std::string hooks, subs, locks, kinds;
        for (size_t i=0;i<size_t(H::Count);++i)
        {
            if (!d.calls[i]) continue;
            hooks += std::format(" {}={:.0f}/f,{:.2f}us,w{:.2f}us",NrdBridgePerf::HookName(H(i)),double(d.calls[i])*perFrame,
                interval.Ms(d.ticks[i])*1000.0/double(d.calls[i]),interval.Ms(d.waitTicks[i])*1000.0/double(d.calls[i]));
        }
        for (size_t i=0;i<size_t(P::Sub::Count);++i)
            if (d.subCalls[i]) subs += std::format(" {}={:.3f}ms/f({:.0f}/f)",P::SubName(P::Sub(i)),interval.Ms(d.subTicks[i])*perFrame,double(d.subCalls[i])*perFrame);
        for (size_t i=0;i<P::LockKinds;++i)
            if (d.lockEvents[i]) locks += std::format(" {}={:.3f}ms/f({:.0f}/f)",P::LockName(i),interval.Ms(d.lockTicks[i])*perFrame,double(d.lockEvents[i])*perFrame);
        constexpr std::array<const char*,size_t(NrdBridgePerf::WaitKind::Count)> kindNames {"Metadata","LifetimeGate","Tracking","Coordinator","DescriptorAdmission"};
        for (size_t i=0;i<kindNames.size();++i)
            if (d.kindEvents[i]) kinds += std::format(" {}={:.3f}ms/f({:.0f}/f)",kindNames[i],interval.Ms(d.kindTicks[i])*perFrame,double(d.kindEvents[i])*perFrame);
        bool runtime = gRuntime.load(std::memory_order_relaxed), active = false; std::string phase = "n/a";
        uint64_t skipped = 0;
        {
            std::unique_lock lock(gMutex,std::try_to_lock);
            if (lock.owns_lock() && gService) { active = gService->status.active; phase = gService->status.phase; skipped = gService->status.nativeDispatchesSkipped; }
        }
        LOG_INFO("[NRD_BRIDGE] perf2 #{} seconds={:.1f} rendered_frames={} fps={:.1f} threads={} runtime={} active={} phase={} survey_bindings={} (bridge_window={} survey_armed={}) native_skipped_total={} "
            "hook_thread_ms_per_frame={:.3f} wait_ms_per_frame={:.3f} descriptors_copied_per_frame={:.0f} copy_calls_per_frame={:.0f} bridge_consumers={} | hooks:{} | parts:{} | locks:{} | waits:{}",
            interval.index,interval.seconds,frames,interval.seconds > 0.0 ? double(frames)/interval.seconds : 0.0,interval.threads,
            runtime,active,phase,FrameSurvey::BindingMirrorActive(),FrameSurvey::BindingWindow(),FrameSurvey::SurveyBindingsArmed(),skipped,
            interval.Ms(hookTicks)*perFrame,interval.Ms(waitTicks)*perFrame,double(d.descriptorsCopied)*perFrame,double(d.copyCalls)*perFrame,
            interval.consumerFrames,hooks,subs,locks,kinds);
        FlushLogger();
    } catch (...) {}
}
// Hang watch output: a stall report is rare and must reach the disk even if the
// title is killed right after, so every report ends with an explicit flush.
void ReportHangLine(const char* line) noexcept
{
    try
    {
        if (line) LOG_INFO("[NRD_BRIDGE] {}",line);
        else FlushLogger();
    } catch (...) {}
}
bool Initialize(ID3D12Device* device) noexcept
{
    if (!device || !StartupEnabled() || FrameSurvey::Internal()) return false;
    const auto native = NrdBridgeDevice::Native(device);
    if (!native) return false;
    try
    {
        std::shared_ptr<Service> previous;
        {
            std::scoped_lock injection(gInjectionMutex);
            {
                std::scoped_lock lock(gMutex);
                if (gService && NrdBridgeDevice::Same(gService->device.Get(), native.Get())) return true;
                auto owner = std::shared_ptr<Service>(new Service,[](Service* service) { FrameSurvey::ScopedInternal internal; delete service; }); owner->device = native;
                owner->status.installed = true; owner->status.runtimeEnabled = Config::Instance()->FfxDenoiserNrdBridgeEnabled.value_or_default();
                owner->rrSettings = ReadStartupSettings(*Config::Instance());
                owner->cameraProjectedDepthDelta = ReadStartupCameraDepth(*Config::Instance());
                owner->rrSettingsState.requested = owner->rrSettings;
                owner->status.phase = owner->status.runtimeEnabled ? "Discovering" : "Waiting for NRD";
                owner->status.reason = owner->status.runtimeEnabled ? "Waiting for the Recon to Consumer chain" : "Runtime toggle is off";
                owner->window = owner->status.runtimeEnabled;
                previous = std::move(gService); gService = std::move(owner);
                gUnavailableReason.clear();
                gNativeDebug.store(gService->rrSettings.nativeDebugView >= 0,std::memory_order_release);
                gNativeMaterials.store(gService->rrSettings.nativeMaterialGuides,std::memory_order_release);
                gRuntime.store(gService->status.runtimeEnabled,std::memory_order_release); gInstalled.store(true,std::memory_order_release);
            }
            // Publish observers under lifecycle serialization, outside the state lock.
            FrameSurvey::SetPipelineObserver(OnPipelineCreated); FrameSurvey::SetGraphicsPipelineObserver(OnGraphicsPipelineCreated);
            FrameSurvey::SetReleaseObserver(OnReleased); FrameSurvey::SetBirthReleaseObserver(OnBirthReleased);
            PublishBindingWindow();
        }
        // Owned D3D12 releases may re-enter hooks. Destroy outside both coordinator locks.
        { FrameSurvey::ScopedInternal internal; previous.reset(); }
        NrdBridgePerf::Periodic::Configure(ReportPeriodicPerf,10.0,ReportHangLine);
        NrdBridgePerf::Configure([](const NrdBridgePerf::Report& perf) noexcept {
            try
            {
                using H = NrdBridgePerf::Hook;
                std::array<H,size_t(H::Count)> ranked {};
                for (size_t i=0;i<ranked.size();++i) ranked[i] = H(i);
                std::partial_sort(ranked.begin(),ranked.begin()+3,ranked.end(),[&](H a,H b) { return perf.SumMsPerFrame(a)>perf.SumMsPerFrame(b); });
                const auto top = std::format("{}:{:.3f},{}:{:.3f},{}:{:.3f}",
                    NrdBridgePerf::HookName(ranked[0]),perf.SumMsPerFrame(ranked[0]),
                    NrdBridgePerf::HookName(ranked[1]),perf.SumMsPerFrame(ranked[1]),
                    NrdBridgePerf::HookName(ranked[2]),perf.SumMsPerFrame(ranked[2]));
                uint64_t admissionTicks=0;
                for(const auto& hook:perf.hooks) admissionTicks+=hook.waitTicks[size_t(NrdBridgePerf::WaitKind::DescriptorAdmission)];
                const double admissionUs=perf.frames&&perf.frequency ? double(admissionTicks)*1000000.0/double(perf.frequency)/double(perf.frames) : 0.0;
                LOG_INFO("[NRD_BRIDGE] perf frames={} SL_frame={}..{} window=100_gameplay_Consumer_intervals scope=all_external_hook_wall_times_including_native consumer_time_valid={} consumer_elapsed_ms={:.3f} consumer_avg_interval_ms={:.3f} consumer_intervals_per_second={:.3f} cadence_scope=CPU_Consumer_recording_not_GPU_or_FG_display_FPS consumer_interval_p50_ms={:.3f} consumer_interval_p95_ms={:.3f} consumer_interval_p99_ms={:.3f} consumer_interval_quantile_scope=actual_per_interval_CPU_Consumer_recording_samples cpu_hook_thread_time_sum_ms_per_interval={:.3f} lock_wait_thread_time_sum_ms_per_interval={:.3f} top_thread_time_sum_ms_per_interval={} time_scope=thread_time_sums_over_overlapping_threads_never_frame_critical_path;sum_of_per_hook_p95_is_not_frame_p95 admission_wait_us_per_consumer={:.3f} admission_scope=per_Consumer_interval wait_scope=metadata+physical_borrow+tracking+coordinator+descriptor_admission;serial_region_not_measured_in_this_window CBV_avg_us={:.3f} CBV_wait_us={:.3f} CBV_metadata_wait_us={:.3f} CBV_calls={} SRV_avg_us={:.3f} SRV_wait_us={:.3f} SRV_metadata_wait_us={:.3f} SRV_calls={} UAV_avg_us={:.3f} UAV_wait_us={:.3f} UAV_metadata_wait_us={:.3f} UAV_calls={} Release_avg_us={:.3f} Release_wait_us={:.3f} Release_metadata_wait_us={:.3f} Release_borrow_wait_us={:.3f} Release_tracking_wait_us={:.3f} Release_coordinator_wait_us={:.3f} Release_calls={}",
                    perf.frames,perf.firstFrame,perf.lastFrame,perf.ConsumerTimeValid(),perf.ConsumerElapsedMs(),perf.AverageConsumerIntervalMs(),perf.ConsumerIntervalsPerSecond(),
                    perf.ConsumerIntervalP50Ms(),perf.ConsumerIntervalP95Ms(),perf.ConsumerIntervalP99Ms(),
                    perf.ThreadTimeSumMsPerInterval(),perf.ThreadTimeSumMsPerInterval(true),top,admissionUs,perf.AverageUs(H::ConstantBufferView),perf.AverageWaitUs(H::ConstantBufferView),
                    perf.AverageWaitUs(H::ConstantBufferView,NrdBridgePerf::WaitKind::Metadata),perf.hooks[size_t(H::ConstantBufferView)].calls,
                    perf.AverageUs(H::ShaderResourceView),perf.AverageWaitUs(H::ShaderResourceView),
                    perf.AverageWaitUs(H::ShaderResourceView,NrdBridgePerf::WaitKind::Metadata),perf.hooks[size_t(H::ShaderResourceView)].calls,
                    perf.AverageUs(H::UnorderedAccessView),perf.AverageWaitUs(H::UnorderedAccessView),
                    perf.AverageWaitUs(H::UnorderedAccessView,NrdBridgePerf::WaitKind::Metadata),perf.hooks[size_t(H::UnorderedAccessView)].calls,
                    perf.AverageUs(H::Release),perf.AverageWaitUs(H::Release),perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::Metadata),
                    perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::LifetimeGate),perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::Tracking),
                    perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::Coordinator),perf.hooks[size_t(H::Release)].calls);
                FlushLogger();
            } catch (...) {}
        });
        LOG_INFO("[NRD_BRIDGE] startup enabled for Cyberpunk; runtime={}; discovery windows bounded to 8 Presents / 3 attempts; empty loading windows do not consume attempts",
            gRuntime.load(std::memory_order_relaxed));
        return true;
    } catch (...) { CoordinatorException("NRD bridge initialization failed"); return false; }
}
void Shutdown() noexcept
{
    try
    {
        std::shared_ptr<Service> previous;
        {
            std::scoped_lock injection(gInjectionMutex);
            gInstalled.store(false,std::memory_order_release); gRuntime.store(false,std::memory_order_release);
            gNativeMaterials.store(false,std::memory_order_release);gNativeTransactions.store(false,std::memory_order_release);
            gNativeDebug.store(false,std::memory_order_release);
            FrameSurvey::SetPipelineObserver(nullptr); FrameSurvey::SetGraphicsPipelineObserver(nullptr);
            FrameSurvey::SetReleaseObserver(nullptr); FrameSurvey::SetBirthReleaseObserver(nullptr); PublishBindingWindow();
            { std::scoped_lock lock(gMutex); previous = std::move(gService); }
        }
        { FrameSurvey::ScopedInternal internal; previous.reset(); }
    } catch (...) {}
}
void OnPipelineCreated(ID3D12PipelineState* pipeline, const char* hash) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !pipeline) return;
    try
    {
        const auto birth = NrdBridgeBirth::Capture(pipeline,BirthMode());
        const auto role = hash ? IdentifyRole(hash) : Role::None; std::scoped_lock lock(gMutex);
        if (!gService || !BirthLive(birth)) return;
        if (role == Role::None) gService->roles.erase(pipeline); else { gRelevantPipelines.Insert(pipeline); gService->roles[pipeline] = {role,birth,true}; }
        // Exact published intervening CS: bound B diffuse is unused by its actual
        // instructions. A changed/unknown hash never inherits this allowance.
        if(hash && std::string_view(hash)=="ac7f46728fe9cfd07bfe11d934d3ce09363289cc1689a2aa7d8aa99ac3bac7b5")
            { gRelevantPipelines.Insert(pipeline); gService->harmlessPipelines[pipeline]=birth; }
        else gService->harmlessPipelines.erase(pipeline);
        const int profile=InterveningComputeProfile(hash);
        if(profile>=0){gRelevantPipelines.Insert(pipeline);gService->interveningPipelines[pipeline]={profile,birth,false};}
        else gService->interveningPipelines.erase(pipeline);
    } catch (...) {}
}
void OnGraphicsPipelineCreated(ID3D12PipelineState* pipeline, const char* hash) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !pipeline) return;
    try
    {
        const auto birth = NrdBridgeBirth::Capture(pipeline,BirthMode());
        const bool consumer = hash && std::string_view(hash) ==
            "051b199b86af56c7bae475bc150a7e5572b53daa44b117e473295100d9c38cc4";
        std::scoped_lock lock(gMutex);
        if (!gService || !BirthLive(birth)) return;
        if (consumer) { gRelevantPipelines.Insert(pipeline); gService->graphicsConsumers[pipeline] = birth; }
        else gService->graphicsConsumers.erase(pipeline);
        const int profile=InterveningGraphicsProfile(hash);
        if(profile>=0){gRelevantPipelines.Insert(pipeline);gService->interveningPipelines[pipeline]={profile,birth,false};}
        else if(hash)gService->interveningPipelines.erase(pipeline);
    } catch (...) {}
}
void OnSetPipeline(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* pipeline) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !cmd) return;
    // An unclassified pipeline on a list the bridge never tracked changes nothing below.
    if (!gRelevantPipelines.MayContain(pipeline) && !gTrackedLists.MayContain(cmd)) return;
    try
    {
        bool open = false, seed = false; RetiredDebugSources retired; std::optional<ListState> retiredList;
        std::array<std::shared_ptr<RecordingToken>,4> retiredPresentations;
        const auto receiverBirth = NrdBridgeBirth::Capture(cmd,BirthMode()), pipelineBirth = NrdBridgeBirth::Capture(pipeline,BirthMode());
        {
            std::scoped_lock lock(gMutex); if (!gService || !BirthLive(receiverBirth) || (pipeline && !BirthLive(pipelineBirth))) return; auto& owner = *gService;
            const auto role = PipelineRole(owner,pipeline,pipelineBirth);
            const auto graphics = owner.graphicsConsumers.find(pipeline);
            const bool pixelConsumer = graphics != owner.graphicsConsumers.end() && graphics->second == pipelineBirth;
            const auto harmless=owner.harmlessPipelines.find(pipeline);
            const bool harmlessPipeline=harmless!=owner.harmlessPipelines.end() && harmless->second==pipelineBirth;
            if (const auto found = owner.lists.find(cmd); found != owner.lists.end() && found->second.birth != receiverBirth)
                ReplaceList(owner,cmd,found->second,receiverBirth,retiredList,retiredPresentations,retired);
            if (role != Role::None)
            {
                gTrackedLists.Insert(cmd); auto& list = owner.lists[cmd]; list.role = role; list.birth = receiverBirth; list.pipelineBirth = pipelineBirth;
                list.nativeContract = owner.roles.at(pipeline).nativeContract;
                if (owner.rrSettings.nativeMaterialGuides) owner.materialIdentities.SeedIfChanged(list.materialStates,list.materialIdentityRevision);
            }
            else if (const auto found = owner.lists.find(cmd); found != owner.lists.end())
            { found->second.role = Role::None; found->second.nativeContract = false; found->second.pipelineBirth = pipelineBirth; }
            if (const auto found = owner.lists.find(cmd); found != owner.lists.end())
            {
                found->second.harmlessPipeline=harmlessPipeline;
                found->second.currentPipeline=pipeline;
                const auto profile=owner.interveningPipelines.find(pipeline);
                found->second.intervening=profile!=owner.interveningPipelines.end()&&profile->second.birth==pipelineBirth?
                    profile->second:InterveningPipeline{};
                found->second.graphicsConsumerCandidate = pixelConsumer;
                found->second.graphicsConsumer = pixelConsumer ? pipeline : nullptr;
                found->second.graphicsConsumerBirth = pixelConsumer ? pipelineBirth : NrdBridgeBirth::Token {};
            }
            if (gRuntime.load(std::memory_order_relaxed) && !owner.window && owner.attempts < 3 && owner.failures < 3 &&
                (role == Role::PrepLast || role == Role::Recon || (role == Role::MaterialGuide && owner.rrSettings.nativeMaterialGuides)) && (owner.cache.Valid() || owner.nativeContractSeen || owner.retryPresents >= 60 ||
                    (role == Role::Recon && !owner.everRecon)))
            {
                StartWindow(owner); if (!owner.cache.Valid()) owner.status.reason = "NRD pipeline observed; waiting for complete bindings"; open = true;
            }
            seed = owner.window && (role == Role::PrepLast || role == Role::Recon ||
                (role == Role::MaterialGuide && owner.rrSettings.nativeMaterialGuides));
        }
        if (open) PublishBindingWindow();
        if (seed) SeedForWindow(cmd);
    } catch (...) {}
}
void OnReset(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* initial) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !cmd) return;
    if (!gRelevantPipelines.MayContain(initial) && !gTrackedLists.MayContain(cmd))
    {
        if (gRuntime.load(std::memory_order_relaxed)) RequireRestoreFlags();
        return; // No ListState exists and an unclassified initial pipeline creates none.
    }
    try
    {
        bool open = false; RetiredDebugSources retired; std::optional<ListState> retiredList;
        std::array<std::shared_ptr<RecordingToken>,4> retiredPresentations;
        const auto receiverBirth = NrdBridgeBirth::Capture(cmd,BirthMode()), pipelineBirth = NrdBridgeBirth::Capture(initial,BirthMode());
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            if (!BirthLive(receiverBirth) || (initial && !BirthLive(pipelineBirth))) return;
            if (gRuntime.load(std::memory_order_relaxed)) RequireRestoreFlags();
            const auto found = owner.lists.find(cmd);
            if (found != owner.lists.end())
            {
                const bool nrdList = found->second.birth == receiverBirth && found->second.nrdList; AbandonDebugPresentations(found->second,retiredPresentations);
                RetireNativeRecording(owner,found->second);
                const bool unsubmitted = found->second.recording && !found->second.recording->submitted.load(std::memory_order_acquire);
                if (unsubmitted && found->second.history)
                {
                    found->second.recording->abandoned.store(true,std::memory_order_release);
                    found->second.history->uncertain.store(true,std::memory_order_release);
                    found->second.history->discardPending.store(true,std::memory_order_release);
                    owner.discardRequested = true; ClearNativeDebugSources(owner,retired);
                }
                if (found->second.converted || owner.pendingList == cmd || unsubmitted)
                {
                    if (owner.pendingList == cmd) owner.pendingList = nullptr;
                    if (owner.activeFrame == found->second.frame) owner.status.active = false;
                    ++owner.resetSerial;
                }
                NativeMaterialStateWitness rememberedMaterialStates;
                uint64_t rememberedMaterialRevision = 0;
                if (found->second.birth == receiverBirth)
                { rememberedMaterialStates = found->second.materialStates; rememberedMaterialRevision = found->second.materialIdentityRevision; }
                rememberedMaterialStates.Invalidate(); // Keep bounded selections, never a preceding recording's proof.
                RemoveChainUsers(owner,cmd,found->second); StopFollowing(owner,cmd,found->second);
                retiredList.emplace(std::move(found->second)); found->second = {};
                found->second.materialStates = std::move(rememberedMaterialStates); found->second.nrdList = nrdList; found->second.role = PipelineRole(owner,initial,pipelineBirth);
                found->second.nativeContract = found->second.role != Role::None && owner.roles.at(initial).nativeContract;
                found->second.birth = receiverBirth; found->second.pipelineBirth = pipelineBirth;found->second.currentPipeline=initial;
                found->second.materialIdentityRevision = rememberedMaterialRevision;
                if (owner.rrSettings.nativeMaterialGuides)
                    owner.materialIdentities.SeedIfChanged(found->second.materialStates,found->second.materialIdentityRevision);
                if (nrdList && gRuntime.load(std::memory_order_relaxed) && !owner.window && owner.attempts < 3 && owner.failures < 3 &&
                    (owner.cache.Valid() || owner.nativeContractSeen || owner.retryPresents >= 60 || !owner.everRecon))
                { StartWindow(owner); open = true; }
            }
            else if (const auto role = PipelineRole(owner,initial,pipelineBirth); role != Role::None)
            {
                gTrackedLists.Insert(cmd); auto& list = owner.lists[cmd]; list.role = role; list.birth = receiverBirth; list.pipelineBirth = pipelineBirth;
                list.nativeContract = owner.roles.at(initial).nativeContract;
                if (owner.rrSettings.nativeMaterialGuides) owner.materialIdentities.SeedIfChanged(list.materialStates,list.materialIdentityRevision);
                if (gRuntime.load(std::memory_order_relaxed) && !owner.window && owner.attempts < 3 && owner.failures < 3 &&
                    (role == Role::PrepLast || role == Role::Recon || (role == Role::MaterialGuide && owner.rrSettings.nativeMaterialGuides)) && (owner.cache.Valid() || owner.nativeContractSeen || owner.retryPresents >= 60 ||
                        (role == Role::Recon && !owner.everRecon)))
                { StartWindow(owner); open = true; }
            }
            RefreshNativeTransactions(owner);
        }
        if (open) PublishBindingWindow();
    } catch (...) { CoordinatorException("Exception while resetting NRD command-list recording"); }
}
void AfterDispatch(ID3D12GraphicsCommandList* cmd) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || !gRuntime.load(std::memory_order_relaxed) || FrameSurvey::Internal()) return;
    if (!gTrackedLists.MayContain(cmd)) return;
    try
    {
        RetiredDebugSources retired; std::optional<ListState> retiredList; const auto receiverBirth = NrdBridgeBirth::Capture(cmd,BirthMode());
        std::shared_ptr<Service> nativeOwner; Role nativeRole=Role::None;bool nativeRecording=false;
        { std::scoped_lock lock(gMutex);nativeOwner=gService;if(nativeOwner)
          if(const auto found=nativeOwner->lists.find(cmd);found!=nativeOwner->lists.end())
          {nativeRecording=NativeElisionReady()&&found->second.rrOnlyTransaction&&found->second.nativeReconPrepared;nativeRole=found->second.role;} }
        if(nativeRecording){ObserveNativeDispatch(nativeOwner,cmd,nativeRole);return;}
        std::shared_ptr<Service> owner; Role role = Role::None; uint64_t frame = 0;
        bool firstTemporal = false, observedEarly = false, firstPrePass = false, invalid = false; ID3D12Resource* currentMotion = nullptr; std::string error;
        {
            NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return; // Ends before taking the native injection mutex.
            bool window = false, cooldown = false;
            {
                std::scoped_lock lock(gMutex); owner = gService; if (!owner) return;
                const auto found = owner->lists.find(cmd); if (found == owner->lists.end() || found->second.birth != receiverBirth || !ListLive(found->second)) return;
                role = found->second.role; window = owner->window;
                if (!window) { StopFollowing(*owner,cmd,found->second); cooldown = true; } // Retry cooldown records no owned work.
                else if (role == Role::Recon)
                {
                    auto& list = found->second; RemoveChainUsers(*owner,cmd,list); StopFollowing(*owner,cmd,list);
                    const bool nativeContract = list.nativeContract; InvalidateSkippedRecording(list);
                    const auto birth = list.birth, pipelineBirth = list.pipelineBirth;
                    retiredList.emplace(std::move(list)); list = {};
                    list.recording = retiredList->recording; list.history = retiredList->history; list.birth = birth; list.pipelineBirth = pipelineBirth;
                    list.material = std::move(retiredList->pendingMaterial); list.materialStates = std::move(retiredList->materialStates);
                    // Prior unsubmitted RR work survives a second incomplete Recon.
                    list.role = role; list.nativeContract = nativeContract; list.rrOnlyTransaction = nativeContract && NativeElisionReady();
                    owner->nativeContractSeen |= nativeContract;
                    list.followingRecon = list.nrdList = true; owner->followingChains.insert(cmd);
                    list.frame = frame = ++owner->frame; owner->observedRecon = owner->everRecon = true;
                    if (window) owner->windowSawRecon = true;
                }
                else
                {
                    if (!found->second.followingRecon || role == Role::None || role == Role::Consumer) return;
                    firstTemporal = role == Role::Temporal && !found->second.temporal;
                    observedEarly = firstTemporal && found->second.earlyTemporalObserved;
                    firstPrePass = role == Role::PrePass && found->second.rrOnlyTransaction && !found->second.firstPrePass;
                    frame = found->second.frame;
                }
            }
            if (cooldown) return;
            if (!window) { Failure(owner,"Current NRD bindings have no frame-local validation window"); return; }
            std::vector<FrameSurvey::BoundResource> srv, uav;
            if (!Tables(cmd,role,srv,uav)) { WaitingForBindings(owner,cmd,"Current NRD table metadata is incomplete"); return; }
            std::vector<FrameSurvey::BoundResource> preparedDepth;
            if (firstPrePass)
            {
                constexpr std::array<FrameSurvey::ComputeTableRequest,1> request {{{D3D12_DESCRIPTOR_RANGE_TYPE_UAV,2,2,0}}};
                if (!FrameSurvey::ResolveComputeBindings(cmd,5,request,preparedDepth) || preparedDepth.size()!=1)
                { Failure(owner,"First native PrePass has no deterministic ViewZ output binding"); return; }
            }
            {
                std::scoped_lock lock(gMutex); if (gService != owner) return;
                const auto found = owner->lists.find(cmd); if (found == owner->lists.end() || found->second.frame != frame || found->second.birth != receiverBirth || !ListLive(found->second)) return;
                auto& list = found->second;
                if (role == Role::Recon) invalid = !list.chain.Begin(srv,uav,error);
                else if (!observedEarly) invalid = !list.chain.Observe(role,srv,uav,owner->taggedMotion,error);
                if (firstPrePass)
                {
                    auto depth = preparedDepth[0]; depth.kind = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
                    if (!NativeTemporalDepthViewSupported(depth,list.chain.Get().width,list.chain.Get().height))
                    { invalid = true; error = "First native PrePass ViewZ type/extent is unsupported"; }
                    else { list.firstPrePass = true; list.nativeFirstDepth = preparedDepth[0]; }
                }
                if (role == Role::PrePass && list.temporal && list.atrous) list.chainB = true;
                RefreshChainUsers(*owner,cmd,list);
                if (role == Role::Temporal) { list.temporal = true; list.earlyTemporalObserved = false; }
                if (role == Role::ATrous && list.temporal) list.atrous = true;
                if (!invalid && role == Role::Recon && !list.rrOnlyTransaction && owner->cache.Valid())
                {
                    const auto& a = list.chain.Get(); const auto& b = owner->cache.Get();
                    if (a.width != b.width || a.height != b.height || a.inputSpec != b.inputSpec || a.inputDiff != b.inputDiff ||
                        a.reconSpec != b.reconSpec || a.reconDiff != b.reconDiff || (BirthMode() &&
                        (list.chain.Bindings()[0].resourceBirth != owner->cacheBirths[0] || list.chain.Bindings()[1].resourceBirth != owner->cacheBirths[1] ||
                         list.chain.Bindings()[4].resourceBirth != owner->cacheBirths[4] || list.chain.Bindings()[5].resourceBirth != owner->cacheBirths[5])))
                    {
                        IdentityChanged(*owner,"Current Recon resource identity changed",retired);
                    }
                }
                if (!invalid && firstTemporal)
                {
                    currentMotion = list.chain.Get().motion;
                    if (!list.rrOnlyTransaction && owner->cache.Valid() && (owner->cache.Get().motion != currentMotion || (BirthMode() && list.chain.Bindings()[6].resourceBirth != owner->cacheBirths[6])))
                    {
                        IdentityChanged(*owner,"Current Temporal motion resource changed",retired);
                    }
                }
            }
        }
        if (invalid) { Failure(owner,error); return; }
        if (role == Role::Recon) Convert(owner,cmd,frame);
        else if (firstTemporal && !observedEarly) FinalizeMotion(owner,cmd,frame,currentMotion);
    } catch (...) { CoordinatorException("Exception while preparing current NRD input bindings"); }
}
// Title work that is not on the attested list but runs between the raw capture and
// the commit is forwarded unchanged and the RR commit is kept. Invalidating the
// recording here would deny the title's own ExecuteCommandLists (native filters are
// already omitted), which stalls the game and latches "restart required". Worst case
// for forwarding: that work reads last frame's committed lighting for one frame.
std::atomic<uint64_t> gToleratedInterveningWork {0};
// A proven read/write of an RR-only A/B target by intervening work is a real
// data hazard, not merely unknown work: keep the original invalidation for it.
bool DefiniteTargetOverlap(const char* gate) noexcept
{
    return gate && (!std::strcmp(gate,"raster_output_overlap") || !std::strcmp(gate,"work_texture_overlap"));
}
void ToleratedInterveningWork(ID3D12GraphicsCommandList* cmd, bool graphics, const char* gate) noexcept
{
    gToleratedInterveningWork.fetch_add(1,std::memory_order_relaxed);
    const char* detail=gNativeWorkDetail;gNativeWorkDetail=nullptr;
    try
    {
        ID3D12PipelineState* pipeline=nullptr;
        { std::scoped_lock lock(gMutex); if(gService){const auto found=gService->lists.find(cmd);if(found!=gService->lists.end())pipeline=found->second.currentPipeline;} }
        static std::mutex logMutex; static std::unordered_set<ID3D12PipelineState*> logged;
        {
            std::scoped_lock lock(logMutex);
            if(logged.size()>=64 || !logged.insert(pipeline).second)return;
        }
        FrameSurvey::PipelineShaderIdentity identity;
        const bool recorded=pipeline&&FrameSurvey::ResolvePipelineShaderIdentity(pipeline,identity);
        LOG_INFO("[NRD_BRIDGE] tolerated unattested {} work inside the RR-only interval (forwarded unchanged, RR commit kept) gate={} subreason={} identity_recorded={} CS={} VS={} PS={} total={}",
            graphics?"graphics":"compute",gate?gate:"unclassified_work",detail?detail:"none",recorded,
            identity.compute.data(),identity.vertex.data(),identity.pixel.data(),gToleratedInterveningWork.load(std::memory_order_relaxed));
    } catch (...) {}
}
void InvalidateRecordingProof(ID3D12GraphicsCommandList* cmd, const char* reason, const char* gate) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !cmd) return;
    try
    {
        std::unique_lock lock(gMutex); if (!gService) return;
        const auto found = gService->lists.find(cmd); if (found == gService->lists.end()) return;
        auto& list = found->second;
        uint32_t pending=0;
        for(size_t index=0;index<list.native.size();++index)
            if(list.native[index]&&!list.native[index]->committed&&!list.native[index]->invalidated)pending|=1u<<index;
        auto* pipeline=list.currentPipeline;
        InvalidateSkippedRecording(list,gate ? gate : "recording_invalidated");
        list.nativeContract = false; list.role = Role::None; list.pipelineBirth.reset();
        list.currentPipeline=nullptr;list.intervening={};
        list.converted = list.motionReady = list.ownedReady = false;
        StopFollowing(*gService,cmd,list);RefreshNativeTransactions(*gService);
        if (gService->pendingList == cmd) gService->pendingList = nullptr;
        if (pending || (list.recording && !RequiredOutputComplete(*list.recording)))
        {
            gService->status.active = false; gService->status.phase = "Inactive";
            gService->status.reason = reason ? reason : "RR-only recording proof was invalidated; submission requires restart";
        }
        lock.unlock();
        if(pending)
        {
            // Cold reject path only. The identity record is already retained by the
            // creation observer; resolve it here for this exact pipeline hash set
            // (no DXIL parse, no descriptor scan, no new admission input).
            FrameSurvey::PipelineShaderIdentity identity;
            const bool identityRecorded=FrameSurvey::ResolvePipelineShaderIdentity(pipeline,identity);
            const int knownComputeProfile=identityRecorded&&identity.presentStages==FrameSurvey::PipelineCS?
                InterveningComputeProfile(identity.compute.data()):-1;
            const int knownGraphicsProfile=identityRecorded&&
                identity.presentStages==(FrameSurvey::PipelineVS|FrameSurvey::PipelinePS)?
                InterveningGraphicsProfile(identity.pixel.data()):-1;
            const char* detail=gNativeWorkDetail;gNativeWorkDetail=nullptr;
            LOG_ERROR("[NRD_BRIDGE] recording invalidated gate={} subreason={} identity_recorded={} stages={} known_compute_profile={} known_graphics_profile={} pending_chain_mask={} cmd={:#x} pipeline={:#x} CS={} VS={} PS={} reason={}",
                gate ? gate : "recording_invalidated",detail ? detail : "none",
                identityRecorded,identity.presentStages,knownComputeProfile,knownGraphicsProfile,pending,
                reinterpret_cast<uintptr_t>(cmd),reinterpret_cast<uintptr_t>(pipeline),
                identity.compute.data(),identity.vertex.data(),identity.pixel.data(),reason ? reason : "unavailable");
        }
    } catch (...) {}
}
DispatchDisposition OriginalDispatchDisposition(ID3D12GraphicsCommandList* cmd, DispatchKind kind) noexcept
{
    if (kind != DispatchKind::Direct)
    {
        InvalidateRecordingProof(cmd,kind == DispatchKind::Bundle ? "ExecuteBundle invalidated an incomplete RR-only recording" : "ExecuteIndirect invalidated an incomplete RR-only recording",
            kind == DispatchKind::Bundle ? "opaque_bundle" : gNativeWorkFailure);
        return DispatchDisposition::Forward;
    }
    if(!gInstalled.load(std::memory_order_relaxed) || !gRuntime.load(std::memory_order_relaxed) || FrameSurvey::Internal() ||
        gDispatchCandidate!=cmd || !NativeElisionReady() || !gNativeTransactions.load(std::memory_order_relaxed))return DispatchDisposition::Forward;
    try
    {
        std::scoped_lock injection(gInjectionMutex);
        NrdBridgeLifetime::ScopedBorrow borrow;if(!borrow.Acquired())return DispatchDisposition::Forward;
        std::shared_ptr<Service> owner;std::shared_ptr<NativeTransaction> stage;Role role=Role::None;bool otherWork=false;
        {
            std::scoped_lock lock(gMutex);owner=gService;if(!owner)return DispatchDisposition::Forward;
            const auto found=owner->lists.find(cmd);if(found==owner->lists.end())return DispatchDisposition::Forward;
            auto& list=found->second;role=list.role;
            if(role==Role::None)otherWork=true;
            if(!otherWork)switch(role)
            {
            case Role::Recon:case Role::PrePass:case Role::Temporal:case Role::Chain3:
            case Role::HistSave:case Role::HistFix:case Role::Clamp:case Role::ATrous:break;
            default:return DispatchDisposition::Forward;
            }
            if(!otherWork&&(!list.nativeContract || !list.rrOnlyTransaction || !list.nativeReconPrepared))return DispatchDisposition::Forward;
            if(!otherWork)stage=list.native[list.nativeChain];
            if(!otherWork&&(!NativeTransactionCurrent(*owner,list,stage) || !stage->geometryReady ||
                ((role!=Role::Recon && role!=Role::PrePass) && !stage->motionReady)))return DispatchDisposition::Forward;
        }
        if(otherWork)
        {
            if(!PreserveNativeWork(owner,cmd,nullptr,false))
            {
                if(DefiniteTargetOverlap(gNativeWorkFailure))InvalidateRecordingProof(cmd,"Compute work overlaps an incomplete RR-only interval's targets",gNativeWorkFailure);
                else ToleratedInterveningWork(cmd,false,gNativeWorkFailure);
            }
            return DispatchDisposition::Forward;
        }
        const auto snapshot=RawSignalSnapshotPass::GetSnapshot(stage->raw);
        const auto actual=RecordedComputeLease::Capture(cmd);const auto captured=snapshot.nativeRecording.lock();
        if(!FrameSurvey::MetadataHealthy() || !D3D12Hooks::BridgePredicationDisabled(cmd) ||
            !D3D12Hooks::CanRestoreRootSignature(cmd) || !actual || actual!=captured || !actual->id ||
            snapshot.recording!=cmd || snapshot.recordingId!=actual->id || snapshot.frameSL!=stage->parameters.streamlineFrame ||
            snapshot.bridgeFrame!=stage->parameters.frameIndex || stage->streamline.frameIndex!=stage->parameters.streamlineFrame)
        {NativeTransactionFailure(owner,stage,"Native omission lost its exact raw/recording/frame/root proof");return DispatchDisposition::Forward;}
        {
            std::scoped_lock lock(gMutex);const auto found=owner->lists.find(cmd);
            if(gService!=owner || found==owner->lists.end() || found->second.role!=role ||
                !NativeTransactionCurrent(*owner,found->second,stage))return DispatchDisposition::Forward;
            auto& list=found->second;list.currentDispatchSuppressed=true;
            owner->status.nativeHistoryDirty=true;++owner->status.nativeDispatchesSkipped;
            if(stage->skipCount<stage->skipped.size())
            {
                auto& event=stage->skipped[stage->skipCount];event.sequence=++stage->skipCount;event.role=uint32_t(role);
                for(const auto& shader:ShaderRoles)if(shader.role==role)
                {
                    auto hex=[](char c){return c<='9'?c-'0':c-'a'+10;};
                    for(size_t i=0;i<32;++i)event.shaderSha256[i]=uint8_t((hex(shader.sha256[i*2])<<4)|hex(shader.sha256[i*2+1]));
                    event.shaderKnown=true;break;
                }
            }
        }
        return DispatchDisposition::Suppress;
    }
    catch(...)
    {
        RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);
        CoordinatorException("Exception while admitting native RR-only dispatch omission");
        return DispatchDisposition::Forward;
    }
}
bool PreserveIndirectRecording(ID3D12GraphicsCommandList* cmd,ID3D12CommandSignature* signature) noexcept
{
    gNativeWorkFailure="work_indirect_signature_or_state";gNativeWorkDetail=nullptr;
    if(!cmd||!signature||FrameSurvey::Internal()||!NativeElisionReady())return false;
    bool required = false;
    try
    {
        // Supported native NRD roles enter through direct Dispatch, where raw
        // capture/omission or late RR commit is admitted. A pure signature proves
        // binding inheritance, not permission to run an NRD filter indirectly.
        // Reject that unsupported entry even before any pending token exists.
        std::shared_ptr<Service> unsupportedOwner;Role unsupportedRole=Role::None;
        if(gRuntime.load(std::memory_order_relaxed))
        {
            std::scoped_lock lock(gMutex);
            if(gService)if(const auto found=gService->lists.find(cmd);found!=gService->lists.end()&&found->second.nativeContract)
            {
                const auto role=found->second.role;
                if(role==Role::Recon||role==Role::PrePass||role==Role::Temporal||role==Role::Chain3||
                   role==Role::HistSave||role==Role::HistFix||role==Role::Clamp||role==Role::ATrous||role==Role::Consumer)
                {unsupportedOwner=gService;unsupportedRole=role;}
            }
        }
        if(unsupportedOwner)
        {
            RecordedComputeLease::FailUntrackedRequiredSubmission(E_FAIL);
            Failure(unsupportedOwner,std::format("RR-only unsupported_native_indirect role={}; native profile requires direct Dispatch; restart required",uint32_t(unsupportedRole)));
            return false;
        }
        // No required native interval can start on this same validly recorded
        // command list during an ExecuteIndirect call. Avoid the injection mutex
        // for the common pre-Recon/OFF path; immutable signature metadata alone
        // proves that its CPU bindings survive this execution-only invocation.
        if(!gNativeTransactions.load(std::memory_order_acquire))
        {
            NrdBridgeLifetime::ScopedBorrow borrow;if(!borrow.Acquired())return false;
            FrameSurvey::IndirectSignatureInfo info;
            return FrameSurvey::ResolveIndirectSignature(signature,info)&&FrameSurvey::ValidateIndirectSignature(info);
        }
        std::scoped_lock injection(gInjectionMutex);NrdBridgeLifetime::ScopedBorrow borrow;if(!borrow.Acquired())return false;
        FrameSurvey::IndirectSignatureInfo info;if(!FrameSurvey::ResolveIndirectSignature(signature,info))return false;
        std::shared_ptr<Service> owner;
        {
            std::scoped_lock lock(gMutex);owner=gService;if(!owner)return false;
            if(const auto found=owner->lists.find(cmd);found!=owner->lists.end())
            {
                const auto& list=found->second;
                if(list.recording)required |= !RequiredOutputComplete(*list.recording);
                for(const auto& stage:list.native)
                    if(stage&&stage->recording)required |= !RequiredOutputComplete(*stage->recording);
            }
        }
        // An attested execution-only signature does not change root arguments,
        // heaps or PSO. Before any required RR interval, preserving that CPU
        // binding snapshot needs no shader/resource exclusion profile. Erasing
        // it here broke the first Recon when the title reused its bound heaps.
        // Once RR owns an incomplete output, the original exact access/retained
        // witness proof remains mandatory, including for these same signatures.
        if(!required)return FrameSurvey::ValidateIndirectSignature(info);
        return PreserveNativeWork(owner,cmd,signature,info.kind==FrameSurvey::IndirectSignatureKind::DrawIndexed);
    }
    catch(...){if(required)RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);return false;}
}
void BeforeDispatch(ID3D12GraphicsCommandList* cmd) noexcept
{
    gDispatchCandidate=nullptr;
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() ||
        (!gRuntime.load(std::memory_order_relaxed) && !NrdBridgePerf::NeedsConsumerFrames())) return;
    if (!gTrackedLists.MayContain(cmd)) return; // Untracked lists have no ListState below.
    try
    {
        RetiredDebugSources retired; const auto receiverBirth = NrdBridgeBirth::Capture(cmd,BirthMode());
        std::shared_ptr<Service> owner; bool runtimeEnabled = false, window = false, following = false, captureNative = false, captureMaterial = false, earlyNative = false, stageSampling = false; Role role = Role::None;
        {
            std::scoped_lock lock(gMutex); owner = gService; if (!owner) return;
            const auto found = owner->lists.find(cmd);
            if (found == owner->lists.end() || found->second.birth != receiverBirth || !ListLive(found->second)) return;
            role = found->second.role;
            runtimeEnabled = gRuntime.load(std::memory_order_relaxed);
            if (!runtimeEnabled)
            {
                if (role != Role::Consumer) return;
            }
            else
            {
                if(NativeElisionReady()&&owner->status.nativeHistoryDirty)
                {
                    // Once native history was omitted, a later known filter cannot
                    // enter through a no-participant list after Reset/profile loss.
                    const bool nativeDenoising=role==Role::PrePass||role==Role::Temporal||role==Role::Chain3||
                        role==Role::HistSave||role==Role::HistFix||role==Role::Clamp||role==Role::ATrous||role==Role::Consumer;
                    if(!FrameSurvey::MetadataHealthy()||(found->second.nativeContract&&nativeDenoising&&
                        (!found->second.nativeReconPrepared||!found->second.rrOnlyTransaction)))
                    {
                        // The native filter runs unchanged on its older history (it
                        // reconverges within a few frames). Latching a global submission
                        // denial here would stop every later title Execute.
                        static std::atomic<uint64_t> occurrences {0};
                        if (SoftSubmitLogDue(occurrences))
                            LOG_INFO("[NRD_BRIDGE] native NRD filter ran without its RR-only transaction role={} metadata_healthy={} count={}",
                                uint32_t(role),FrameSurvey::MetadataHealthy(),occurrences.load(std::memory_order_relaxed));
                        owner->status.reason="Native NRD filter ran without an RR-only transaction (forwarded)";return;
                    }
                }
                if(found->second.rrOnlyTransaction || (found->second.nativeContract && role==Role::Recon))gDispatchCandidate=cmd;
                if (role != Role::Consumer && role != Role::Temporal && role != Role::MaterialGuide &&
                    !(found->second.nativeContract && (role==Role::Recon || role==Role::PrePass))) return;
                window = owner->window; following = found->second.followingRecon;
                captureNative = found->second.parameters.nativeTemporalMotion && found->second.converted && !found->second.temporal;
                earlyNative = found->second.rrOnlyTransaction && found->second.converted && !found->second.temporal;
                captureMaterial = owner->rrSettings.nativeMaterialGuides;
                stageSampling = role == Role::Consumer && found->second.recording && found->second.recording->needsStageSamples &&
                    found->second.converted && gStageCollector.Active();
            }
        }
        // The profiler observes identified gameplay Consumers even while RR is
        // disabled. Report outside gMutex; no raw capture, validation or omission
        // may be reached from this diagnostic-only path.
        if (!runtimeEnabled)
        {
            NrdBridgePerf::ConsumerFrame(StreamlineHooks::getSLConstantsSnapshot().frameIndex);
            return;
        }
        bool nativePath=false;uint32_t nativeAction=0;
        {
            std::scoped_lock lock(gMutex);const auto found=owner->lists.find(cmd);
            if(gService==owner && found!=owner->lists.end())
            {
                const auto& list=found->second;
                nativePath=NativeElisionReady() && list.nativeContract && (role==Role::Recon || list.rrOnlyTransaction);
                if(nativePath)
                {
                    if(role==Role::Recon)nativeAction=1;
                    else if(role==Role::PrePass && !list.native[1] && list.temporal && list.atrous)nativeAction=2;
                    else if(role==Role::Temporal)nativeAction=3;
                    else if(role==Role::Consumer)nativeAction=4;
                }
            }
        }
        if(nativePath)
        {
            if(nativeAction==1)BeginNativeTransaction(owner,cmd,0);
            else if(nativeAction==2)BeginNativeTransaction(owner,cmd,1);
            else if(nativeAction==3)PrepareNativeMotion(owner,cmd);
            else if(nativeAction==4)
            {
                NrdBridgePerf::ConsumerFrame(StreamlineHooks::getSLConstantsSnapshot().frameIndex);
                CommitNativeTransaction(owner,cmd,false);
            }
            return;
        }
        if (role == Role::MaterialGuide)
        {
            if (gRuntime.load(std::memory_order_relaxed) && captureMaterial) CaptureMaterialForCurrentPipeline(cmd);
            return;
        }
        if (role == Role::Temporal)
        {
            if (gRuntime.load(std::memory_order_relaxed) && following)
            {
                if (earlyNative) PrepareEarlyTemporal(owner,cmd);
                else if (captureNative) CaptureTemporalMotion(owner,cmd);
            }
            return;
        }
        NrdBridgePerf::ConsumerFrame(StreamlineHooks::getSLConstantsSnapshot().frameIndex);
        if (!gRuntime.load(std::memory_order_relaxed) || !following) return;
        if (!window)
        {
            std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
            if (gService == owner && found != owner->lists.end())
            {
                if (found->second.converted) DropPending(*owner,retired);
                StopFollowing(*owner,cmd,found->second);
            }
            return;
        }
        std::string error; ChainDiscovery discovered; bool published = false, invalid = false;
        ID3D12Resource* motionTag = nullptr; Resources resources; ListState staged; bool inject = false, keepWindow = false;
        FrameSurvey::BoundConstantBinding consumerConstants;
        std::array<FrameSurvey::BoundResource,2> consumerTargets {};
        std::vector<FrameSurvey::BoundResource> currentTargets; currentTargets.reserve(2);
        NrdBridgeStagePerf::Sample consumerStages {}; consumerStages.stopped = &gStagesStopped;
        auto* consumerProfile = stageSampling && consumerStages.Enabled() ? &consumerStages : nullptr;
        {
        NrdBridgeStagePerf::StackTimer physicalWait(consumerProfile,NrdBridgeStagePerf::Stage::ConsumerPhysicalWait);
        NrdBridgeLifetime::ScopedBorrow borrow; physicalWait.Stop(); if (!borrow.Acquired()) return;
        NrdBridgeStagePerf::StackTimer physicalHold(consumerProfile,NrdBridgeStagePerf::Stage::ConsumerPhysicalHold);
        std::vector<FrameSurvey::BoundResource> srv, uav;
        if (!window) { Failure(owner,"Consumer has no current binding-validation window"); return; }
        if (!Tables(cmd,Role::Consumer,srv,uav) || uav.size() != consumerTargets.size())
        { WaitingForBindings(owner,cmd,"Consumer compute table bindings/registers are unavailable in discovery window"); return; }
        std::copy(uav.begin(),uav.end(),consumerTargets.begin());
        FrameSurvey::ConstantBufferDiagnostic constantDiagnostic;
        if (!FrameSurvey::ResolveComputeConstantBinding(cmd,6,0,consumerConstants,&constantDiagnostic))
        {
            LOG_ERROR("[NRD_BRIDGE] cbv_binding_failed b6 space0 reason={} parameter={} table={} table_base={:#x} slot_cpu={:#x} va={:#x}",
                constantDiagnostic.reason,constantDiagnostic.rootParameter,constantDiagnostic.table,constantDiagnostic.tableBase,
                constantDiagnostic.descriptorCpu,constantDiagnostic.address);
            Failure(owner,std::string("Consumer b6 space0 constants unavailable: ")+constantDiagnostic.reason); return;
        }
        {
            std::scoped_lock lock(gMutex); if (gService != owner) return;
            const auto found = owner->lists.find(cmd); if (found == owner->lists.end() || found->second.birth != receiverBirth || !ListLive(found->second)) return;
            auto& list = found->second;
            if (window)
            {
                invalid = !list.chain.Observe(Role::Consumer,srv,uav,owner->taggedMotion,error);
                RefreshChainUsers(*owner,cmd,list);
                if (!invalid)
                {
                    const auto births = CacheBirths(list.chain);
                    if (owner->cache.Valid() && !SameProfileBirths(owner->cacheBirths,births)) owner->cache.Invalidate();
                    published = owner->cache.Publish(list.chain); owner->cacheBirths = births; discovered = list.chain; motionTag = owner->taggedMotion;
                    if (published && !list.rrOnlyTransaction) { DropPending(*owner,retired); owner->status.active = false; }
                    owner->window = false; owner->attempts = 0; owner->status.phase = "Waiting for NRD";
                    owner->status.reason = "Resources validated; waiting for the next Recon";
                    owner->status.width = owner->cache.Get().width; owner->status.height = owner->cache.Get().height;
                    owner->status.resources = ResourceSummary(owner->cache.Get());
                }
            }
            inject = !invalid && CurrentFrameProfile(*owner,list) && list.converted && list.motionReady && list.temporal && list.atrous &&
                (!list.rrOnlyTransaction || (list.ownedReady && list.ownedOutput && list.recording &&
                    !list.recording->skipInvalidated.load(std::memory_order_acquire))) &&
                list.resetSerial == owner->cancellationSerial;
            if (inject)
            {
                resources = list.rrOnlyTransaction ? list.chain.Get() : owner->cache.Get(); staged = list;
                staged.parameters.outputConstants = {nullptr,consumerConstants.address,
                    consumerConstants.descriptorHeap,consumerConstants.descriptor};
            }
            StopFollowing(*owner,cmd,list);
            keepWindow = !owner->followingChains.empty();
            owner->window = keepWindow;
        }
        } // Release physical-resource borrow before waiting for native injection serialization.
        if (invalid) { Failure(owner,error); return; }
        if (window && !keepWindow) PublishBindingWindow();
        if (published) LogDiscovery(discovered,motionTag);
        if (!inject) return;
#ifdef FSRD_NRD_BRIDGE_TEST
        if (gBeforeOutputLockForTesting) gBeforeOutputLockForTesting();
#endif
        NrdBridgeStagePerf::Sample completeStages {}; bool committed = false;
        {
        std::unique_lock injection(gInjectionMutex,std::defer_lock);
        NrdBridgeStagePerf::StackTimer waitTimer(consumerProfile,NrdBridgeStagePerf::Stage::ConsumerInjectionWait);
        injection.lock(); waitTimer.Stop();
        NrdBridgeStagePerf::StackTimer injectionHold(consumerProfile,NrdBridgeStagePerf::Stage::ConsumerInjectionHold);
        {
        NrdBridgeStagePerf::StackTimer physicalWait(consumerProfile,NrdBridgeStagePerf::Stage::ConsumerPhysicalWait);
        NrdBridgeLifetime::ScopedBorrow borrow; physicalWait.Stop(); if (!borrow.Acquired()) return;
        NrdBridgeStagePerf::StackTimer physicalHold(consumerProfile,NrdBridgeStagePerf::Stage::ConsumerPhysicalHold);
        {
            std::scoped_lock lock(gMutex);
            if (gService != owner || !gRuntime.load(std::memory_order_relaxed) ||
                !CurrentFrameProfile(*owner,staged) || staged.resetSerial != owner->cancellationSerial) return;
            const auto found = owner->lists.find(cmd);
            if (found == owner->lists.end() || found->second.frame != staged.frame ||
                found->second.recording != staged.recording || !found->second.converted || !found->second.motionReady || !ListLive(found->second) || !ChainLive(found->second.chain)) return;
            // Captured parameters and private provider output remain immutable across
            // deferred UI/reset requests. The deprecated blend ABI is always zero.
            staged.parameters.nativeSpecularBlend = 0.0f;
        }
        if (!FrameSurvey::MetadataHealthy()) { Failure(owner,"Creation or binding metadata is unhealthy; restart the title/device"); return; }
        FrameSurvey::ComputeBindings currentBindings;
        if (!D3D12Hooks::GetComputeBindingsForBridge(cmd,currentBindings) ||
            !FrameSurvey::ValidateComputeConstantBinding(currentBindings,6,0,consumerConstants) ||
            !CurrentConsumerOutputs(currentBindings,consumerTargets,currentTargets))
        { Failure(owner,"Consumer native b6 binding changed while awaiting injection; waiting for rediscovery"); return; }
        if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored before Consumer"); return; }
        struct CommitTicket
        {
            Service* owner;
            ID3D12GraphicsCommandList* list;
            const ListState* staged;
            const FrameSurvey::BoundConstantBinding* constants;
            const std::array<FrameSurvey::BoundResource,2>* targets;
            std::vector<FrameSurvey::BoundResource>* targetScratch;
            bool cancelled = false, metadataFailed = false, bindingFailed = false, log = false;
            uint64_t frames = 0, resets = 0;
            static bool Admit(void* state, OutputCommitGuard::Action action, void* prepared) noexcept
            {
                auto& ticket = *static_cast<CommitTicket*>(state);
                std::scoped_lock lock(gMutex);
                const auto found = ticket.owner->lists.find(ticket.list);
                const auto& staged = *ticket.staged;
                ticket.metadataFailed = !FrameSurvey::MetadataHealthy();
                if (gService.get() != ticket.owner || !gRuntime.load(std::memory_order_relaxed) ||
                    !CurrentFrameProfile(*ticket.owner,staged) || ticket.metadataFailed ||
                    staged.resetSerial != ticket.owner->cancellationSerial ||
                    found == ticket.owner->lists.end() ||
                    found->second.frame != staged.frame || !found->second.converted || !found->second.motionReady ||
                    found->second.recording != staged.recording || found->second.birth != staged.birth ||
                    (staged.rrOnlyTransaction && (!found->second.ownedReady || found->second.ownedOutput != staged.ownedOutput ||
                        staged.recording->skipInvalidated.load(std::memory_order_acquire))) ||
                    !ListLive(found->second) || !ChainLive(found->second.chain))
                { ticket.cancelled = true; return false; }
                FrameSurvey::ComputeBindings current;
                if (!D3D12Hooks::GetComputeBindingsForBridge(ticket.list,current) ||
                    (BirthMode() && current.receiverBirth != staged.birth) ||
                    !FrameSurvey::ValidateComputeConstantBinding(current,6,0,*ticket.constants) ||
                    !CurrentConsumerOutputs(current,*ticket.targets,*ticket.targetScratch))
                { ticket.bindingFailed = true; return false; }
                // This is the output admission point: reset/tag/release invalidation
                // cannot pass between the final ticket check and the prepared write.
                action(prepared);
                staged.recording->outputCommitted.store(true,std::memory_order_release);
                found->second.converted = false;
                if (ticket.owner->pendingList == ticket.list) ticket.owner->pendingList = nullptr;
                ticket.owner->failures = 0;
                ticket.frames = ++ticket.owner->status.framesBridged;
                if (staged.parameters.reset) ++ticket.owner->status.resets;
                ticket.resets = ticket.owner->status.resets;
                ticket.owner->status.active = true; ticket.owner->activeFrame = staged.frame;
                ticket.owner->status.phase = "Active";
                if (ticket.owner->status.runtimeDisablePending)
                    ticket.owner->status.reason = "Restart required to return to native NRD; RR-only histories have replaced native temporal work";
                else ticket.owner->status.reason.clear();
                if (staged.debug != DebugMode::Off)
                { ++ticket.owner->resetSerial; staged.history->uncertain.store(true,std::memory_order_release); }
                ticket.log = ticket.frames == 1 || ticket.frames-ticket.owner->lastLog >= 600;
                if (ticket.log) ticket.owner->lastLog = ticket.frames;
                return true;
            }
        } ticket {owner.get(), cmd, &staged, &consumerConstants, &consumerTargets, &currentTargets};
        const OutputCommitGuard admission {&ticket, CommitTicket::Admit};
        bool succeeded = false;
        {
            InjectionScope guard(cmd);
            if (staged.debug == DebugMode::Off)
            {
                if (staged.rrOnlyTransaction)
                    succeeded = staged.history->rr.CommitOwned(cmd,staged.ownedOutput,resources.outputSpec,resources.outputDiff,staged.parameters,error,admission,consumerProfile);
                else
                {
                    NrdBridgeStagePerf::StackTimer rrDispatch(consumerProfile,NrdBridgeStagePerf::Stage::ConsumerRRDispatch);
                    succeeded = staged.history->rr.Dispatch(cmd,staged.inputs,resources.outputSpec,resources.outputDiff,staged.parameters,error,admission,consumerProfile);
                }
            }
            else succeeded = staged.history->conversion.WriteDebug(cmd,staged.inputs,resources.outputSpec,resources.outputDiff,staged.debug,error,admission,
                    staged.parameters.outputEncoding,staged.parameters.outputConstants);
        }
        if (ticket.metadataFailed)
        { Failure(owner,"Creation or binding metadata is unhealthy; restart the title/device"); return; }
        if (ticket.bindingFailed)
        { Failure(owner,"Consumer native b6 binding changed before output admission; waiting for rediscovery"); return; }
        if (ticket.cancelled) return; // Preserve the newer reset/discovery status and epoch.
        {
            std::scoped_lock lock(gMutex);
            if (gService == owner)
            {
                owner->rrSettingsState = staged.history->rr.GetSettingsState();
                owner->rrSettingsState.requested = owner->rrSettings;
            }
        }
        if (!succeeded) { Failure(owner,error.empty() ? "NRD output dispatch failed" : error); return; }
        CaptureNativeDebugSource(owner,cmd,staged);
        if (ticket.log)
        {
            // Frame-level effective motion-Z provenance of this domain; per-pixel
            // populations need a user-armed capture, never a synchronous readback.
            const auto provenance = staged.history->conversion.MotionProvenance();
            LOG_INFO("[NRD_BRIDGE] active frames={} resets={} SL_frame={} bridge_frame={} render={}x{} debug={} motionZ=dispatches{}_native{}_cameraOnly{}_unknown{}_legacyVisible{} scope=frame_level_effective_path_not_per_pixel",
                ticket.frames,ticket.resets,staged.parameters.streamlineFrame,staged.parameters.frameIndex,
                resources.width,resources.height,uint32_t(staged.debug),
                provenance.dispatches,provenance.native,provenance.cameraOnly,provenance.unknown,provenance.legacyVisible);
        }
        committed = staged.recording->outputCommitted.load(std::memory_order_acquire);
        } // Physical hold timer ends before Borrow; native recording boundaries are unchanged.
        injectionHold.Stop();
        if (stageSampling)
        {
            completeStages = staged.recording->stages;
            MergeStageSamples(completeStages,consumerStages);
        }
        } // Injection hold has ended and the injection mutex is now unlocked.
        if (stageSampling) CompleteStageSample(staged.parameters.streamlineFrame,completeStages,committed);
    } catch (...) { CoordinatorException("Exception while preparing NRD output dispatch"); }
}
void BeforeGraphicsConsumer(ID3D12GraphicsCommandList* cmd) noexcept
{
    if(!gInstalled.load(std::memory_order_relaxed)||!gRuntime.load(std::memory_order_relaxed)||
        !gNativeTransactions.load(std::memory_order_relaxed)||FrameSurvey::Internal())return;
    if(!gTrackedLists.MayContain(cmd))return; // Draws on untracked lists have no ListState.
    try
    {
        std::shared_ptr<Service> owner;bool intervening=false,unknown=false;
        {
            std::scoped_lock lock(gMutex);owner=gService;if(!owner)return;
            const auto found=owner->lists.find(cmd);if(found==owner->lists.end())return;
            auto& list=found->second;
            if(!list.graphicsConsumerCandidate)
            {
                unknown=list.intervening.profile<2;
                intervening=!unknown;
            }
            else if(!list.native[1]||list.native[1]->committed)return;
        }
        if(unknown)
            ToleratedInterveningWork(cmd,true,"work_graphics_profile");
        else if(intervening)
        {
            std::scoped_lock injection(gInjectionMutex);NrdBridgeLifetime::ScopedBorrow borrow;
            if(!borrow.Acquired())InvalidateRecordingProof(cmd,"Graphics work lost its physical lifetime proof","work_physical_borrow");
            else if(!PreserveNativeWork(owner,cmd,nullptr,true))
            {
                if(DefiniteTargetOverlap(gNativeWorkFailure))InvalidateRecordingProof(cmd,"Graphics work overlaps an incomplete RR-only interval's targets",gNativeWorkFailure);
                else ToleratedInterveningWork(cmd,true,gNativeWorkFailure);
            }
        }
        else CommitNativeTransaction(owner,cmd,true);
    }
    catch(...){RecordedComputeLease::FailUntrackedRequiredSubmission(E_OUTOFMEMORY);CoordinatorException("Exception while observing native pixel-composition work");}
}

void ReleaseObserved(void* object, const NrdBridgeBirth::Token& birth) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || !object) return;
    try
    {
        bool reopen = false; RetiredDebugSources retired; std::optional<ListState> retiredList;
        std::array<std::shared_ptr<RecordingToken>,4> retiredPresentations;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            if (const auto role = owner.roles.find(reinterpret_cast<ID3D12PipelineState*>(object)); role != owner.roles.end() && role->second.birth == birth)
                owner.roles.erase(role);
            if (const auto pixel = owner.graphicsConsumers.find(reinterpret_cast<ID3D12PipelineState*>(object));
                pixel != owner.graphicsConsumers.end() && pixel->second == birth) owner.graphicsConsumers.erase(pixel);
            if(const auto safe=owner.harmlessPipelines.find(reinterpret_cast<ID3D12PipelineState*>(object));
                safe!=owner.harmlessPipelines.end() && safe->second==birth)owner.harmlessPipelines.erase(safe);
            if(const auto profile=owner.interveningPipelines.find(reinterpret_cast<ID3D12PipelineState*>(object));
                profile!=owner.interveningPipelines.end()&&profile->second.birth==birth)owner.interveningPipelines.erase(profile);
            if (const auto found = owner.lists.find(reinterpret_cast<ID3D12GraphicsCommandList*>(object)); found != owner.lists.end() && found->second.birth == birth)
            {
                AbandonDebugPresentations(found->second,retiredPresentations);RetireNativeRecording(owner,found->second);
                const bool unsubmitted = found->second.recording && !found->second.recording->submitted.load(std::memory_order_acquire);
                if (unsubmitted && found->second.history)
                {
                    found->second.recording->abandoned.store(true,std::memory_order_release);
                    found->second.history->uncertain.store(true,std::memory_order_release);
                    found->second.history->discardPending.store(true,std::memory_order_release);
                    owner.discardRequested = true; ClearNativeDebugSources(owner,retired);
                }
                if (found->second.converted || unsubmitted)
                {
                    if (owner.pendingList == reinterpret_cast<ID3D12GraphicsCommandList*>(object)) owner.pendingList = nullptr;
                    if (owner.activeFrame == found->second.frame) owner.status.active = false;
                    ++owner.resetSerial;
                }
                RemoveChainUsers(owner,found->first,found->second); StopFollowing(owner,found->first,found->second);
                retiredList.emplace(std::move(found->second)); owner.lists.erase(found);
            }
            bool currentReleased = false;
            // An address can be shared by a few NRD recordings. Visit those users only.
            // RemoveChainUsers may erase this map entry, so reacquire it per iteration.
            for (;;)
            {
                const auto users = owner.chainUsers.find({object,birth});
                if (users == owner.chainUsers.end() || users->second.empty()) break;
                const auto cmd = *users->second.begin();
                // Pop before any secondary cleanup: a failed index allocation may
                // have published this pair before indexedReferences was committed.
                users->second.erase(cmd); if (users->second.empty()) owner.chainUsers.erase(users);
                const auto found = owner.lists.find(cmd);
                if (found == owner.lists.end()) continue;
                auto& list = found->second;
                const auto& resources = list.indexedReferences; const auto& births = list.indexedBirths; bool matches = false;
                for (size_t i=0;i<resources.size();++i) matches |= resources[i] == object && births[i] == birth;
                if (!matches) continue; // A partially inserted or delayed old pair cannot invalidate a newborn chain.
                if(list.rrOnlyTransaction)
                {
                    for(const auto& stage:list.native)if(stage && !stage->committed)
                    {
                        bool used=stage->motion.resource==object && stage->motion.resourceBirth==birth;
                        for(const auto& bound:stage->sources)used |= bound.resource==object && bound.resourceBirth==birth;
                        for(const auto& bound:stage->targets)used |= bound.resource==object && bound.resourceBirth==birth;
                        if(used){stage->invalidated=true;stage->recording->skipInvalidated.store(true,std::memory_order_release);currentReleased=true;}
                    }
                    (void)list.chain.Released(object);
                }
                else if (list.chain.Released(object)) currentReleased |= list.followingRecon || list.converted;
                RemoveChainUsers(owner,cmd,list); StopFollowing(owner,cmd,list);
            }
            if (owner.taggedMotion == object && owner.taggedMotionBirth == birth) { owner.taggedMotion = nullptr; owner.taggedMotionBirth.reset(); }
            const bool cachedReleased = CacheUsesBirth(owner,object,birth) && owner.cache.Released(object);
            if (currentReleased || (cachedReleased && !owner.nativeContractSeen))
            { Invalidate(owner,"A discovered or current-recording title resource was released",retired); reopen = true; }
            RefreshNativeTransactions(owner);
        }
        if (reopen && gRuntime.load(std::memory_order_relaxed))
        { PublishBindingWindow(); LOG_INFO("[NRD_BRIDGE] resource release invalidated discovery; restarting bounded window"); }
    } catch (...) {}
}
void OnResourceBarriers(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_RESOURCE_BARRIER* barriers) noexcept
{
    if ((!gNativeMaterials.load(std::memory_order_relaxed) && !gNativeTransactions.load(std::memory_order_relaxed)) ||
        !gInstalled.load(std::memory_order_relaxed) || !gRuntime.load(std::memory_order_relaxed) ||
        FrameSurvey::Internal() || !barriers || !count) return;
    // Barriers on untracked lists matter only when they transition a remembered material target.
    if (!gTrackedLists.MayContain(cmd) && !MaterialTransitionMayMatch(count,barriers)) return;
    try
    {
        std::shared_ptr<Service> owner;
        {
            std::scoped_lock lock(gMutex); owner = gService; if (!owner || !cmd) return;
            const auto found = owner->lists.find(cmd);
            if (found != owner->lists.end() && ListLive(found->second))
            {
                if(gNativeMaterials.load(std::memory_order_relaxed))
                {
                    owner->materialIdentities.SeedIfChanged(found->second.materialStates,found->second.materialIdentityRevision);
                    // Existing lists must see every packet, including wildcard aliases.
                    found->second.materialStates.Observe(count,barriers,owner->cancellationSerial);
                }
                for(const auto& stage:found->second.native)
                    if(stage && !stage->committed && !stage->invalidated)stage->targetStates.Observe(count,barriers,stage->serial);
                return;
            }
            if (!owner->materialIdentities.MatchesAnyTransition(count,barriers)) return;
        }
        // The rare first relevant transition needs a receiver identity; known
        // lists avoid a Birth registry lookup in the steady barrier path.
        RetiredDebugSources retired; std::optional<ListState> retiredList;
        std::array<std::shared_ptr<RecordingToken>,4> retiredPresentations;
        const auto receiverBirth = NrdBridgeBirth::Capture(cmd,BirthMode());
        std::scoped_lock lock(gMutex);
        if (gService != owner || !BirthLive(receiverBirth) ||
            !owner->materialIdentities.MatchesAnyTransition(count,barriers)) return;
        auto found = owner->lists.find(cmd);
        if (found == owner->lists.end())
        { gTrackedLists.Insert(cmd); found = owner->lists.try_emplace(cmd).first; found->second.birth = receiverBirth; }
        else if (found->second.birth != receiverBirth)
            ReplaceList(*owner,cmd,found->second,receiverBirth,retiredList,retiredPresentations,retired);
        if (ListLive(found->second))
        {
            owner->materialIdentities.SeedIfChanged(found->second.materialStates,found->second.materialIdentityRevision);
            found->second.materialStates.Observe(count,barriers,owner->cancellationSerial);
        }
    } catch (...) {}
}
void OnRecordingClosed(ID3D12GraphicsCommandList* cmd, HRESULT result) noexcept
{
    if ((!gNativeMaterials.load(std::memory_order_relaxed) && !gNativeTransactions.load(std::memory_order_relaxed)) ||
        FrameSurvey::Internal() || FAILED(result)) return;
    if (!gTrackedLists.MayContain(cmd)) return;
    try
    {
        std::scoped_lock lock(gMutex); if (!gService) return;
        const auto found = gService->lists.find(cmd);
        if (found != gService->lists.end())
        {
            found->second.materialStates.Invalidate();
            // Missing late Consumer remains an explicit BeforeSubmission denial;
            // Close never makes an incomplete native transaction submittable.
            for(const auto& stage:found->second.native)
                if(stage && !stage->committed)
                {
                    const char* empty=nullptr;stage->recording->invalidationGate.compare_exchange_strong(empty,"consumer_missing",std::memory_order_acq_rel);
                    stage->recording->skipInvalidated.store(true,std::memory_order_release);
                }
        }
    } catch (...) {}
}
void OnReleased(void* object) noexcept
{
    if (BirthMode()) return; // Native retirement uses its captured exact token; raw late notifications are legacy only.
    ReleaseObserved(object,{});
}
void OnBirthReleased(const NrdBridgeBirth::Token& birth) noexcept
{
    if (birth && !birth->Live()) ReleaseObserved(birth->Address(),birth);
}
void OnTitleTag(ID3D12GraphicsCommandList*, const char* name, ID3D12Resource* resource) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !name) return;
    try
    {
        if (std::string_view(name) != "MotionVectors") return;
        if (!resource)
        {
            std::scoped_lock lock(gMutex); if (gService) { gService->taggedMotion = nullptr; gService->taggedMotionBirth.reset(); }
            return;
        }
        // D3D12 resource extents are immutable; a different pointer invalidates independently of its size.
        // Tagging is metadata-only so a normal joined callback never waits for the injector's borrow.
        bool reopen = false; RetiredDebugSources retired; const auto birth = NrdBridgeBirth::Capture(resource,BirthMode());
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            owner.taggedMotion = resource; owner.taggedMotionBirth = birth;
            if (!owner.nativeContractSeen && owner.cache.Valid() && (owner.cache.Get().motion != resource || (BirthMode() && owner.cacheBirths[6] != birth)))
            { Invalidate(owner,"Streamline motion tag or render size changed",retired); reopen = true; }
        }
        if (reopen && gRuntime.load(std::memory_order_relaxed)) PublishBindingWindow();
    } catch (...) {}
}
void OnPresent() noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || !gRuntime.load(std::memory_order_relaxed)) return;
    try
    {
        const auto snapshot = StreamlineHooks::getSLConstantsSnapshot(); bool change = false, log = false;
        std::string reason; RetiredDebugSources retired;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            // FG Presents do not imply new rendered frames. Count missing Recon only when SL's frame id advances.
            if (snapshot.frameIndex != UINT32_MAX && snapshot.frameIndex != owner.lastSLFrame)
            {
                owner.lastSLFrame = snapshot.frameIndex;
                if (owner.cache.Frame(owner.observedRecon))
                { Invalidate(owner,"Recon missing for 30 consecutive Streamline frames",retired); change = log = true; }
                owner.observedRecon = false;
            }
            if (owner.window && ++owner.windowPresents >= 8)
            {
                owner.window = false; owner.retryPresents = 0; change = true; owner.status.active = false;
                if (owner.windowSawRecon)
                {
                    ++owner.attempts; owner.status.phase = "Inactive";
                    owner.status.reason = owner.attempts >= 3 ? "NRD discovery exhausted 3 bounded windows: " + owner.status.reason :
                        "Waiting for a complete NRD chain; retrying after 60 Presents";
                    log = true;
                }
                else
                {
                    owner.status.phase = "Waiting for NRD";
                    owner.status.reason = "No Recon in the loading/menu window; waiting for NRD pipeline activity";
                }
                reason = owner.status.reason;
            }
            else if (!owner.window && !owner.cache.Valid() && owner.attempts < 3 && owner.failures < 3)
            {
                owner.retryPresents = std::min(60u,owner.retryPresents+1);
                if (owner.retryPresents >= 60 && owner.everRecon && (owner.attempts || owner.failures))
                { StartWindow(owner); change = true; }
            }
            if (reason.empty()) reason = owner.status.reason;
        }
        if (change) PublishBindingWindow();
        if (log) LOG_INFO("[NRD_BRIDGE] {}",reason);
    } catch (...) {}
}
void ReportUnavailable(const char* reason) noexcept
{
    Shutdown();
    try
    {
        std::scoped_lock lock(gMutex);
        gUnavailableReason = reason ? reason : "Selected title device is unavailable";
    } catch (...) {}
}
Status GetStatus()
{
    std::scoped_lock lock(gMutex);
    if (gService)
    {
        auto status = gService->status;
        // P05 live memory counters are read fresh under the same lock; they are
        // metadata atomics, never an allocation or GPU query. Every retained
        // history domain reports through its wrapper-owned staging ledger, so
        // the totals stay correct while old generations are still alive.
        for (const auto& weak : gService->historyDomains)
            if (const auto domain = weak.lock())
            {
                const auto ledger = domain->rr.SnapshotStagingLedger();
                status.stagingRetainedBytes += ledger.retainedBytes;
                status.stagingRetainedPeakBytes = std::max(status.stagingRetainedPeakBytes,ledger.retainedPeakBytes);
                status.stagingRetiredTotalBytes += ledger.retiredTotalBytes;
                status.stagingRetainedSlots += ledger.retainedSlots;
                status.stagingRejections += ledger.rejections;
            }
        const auto recovery = SnapshotRecoveryFamilyMemory(gService->recoveryFamily);
        status.recoveryGraphBytes = recovery.graphBytes;
        status.recoveryFamilyRetainedPeakBytes = recovery.familyRetainedPeakBytes;
        status.recoverySlotBytes = recovery.slotBytes;
        status.recoverySlots = recovery.slots;
        return status;
    }
    Status status;
    if (const auto reason = gStartupFailure.load(std::memory_order_acquire))
    { status.phase = "Inactive"; status.reason = reason; }
    else if (StartupEnabled() && !gUnavailableReason.empty())
    {
        status.installed = true; status.phase = "Inactive"; status.reason = gUnavailableReason;
    }
    return status;
}
void SetRuntimeEnabled(bool enabled) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed)) return;
    try
    {
        std::scoped_lock injection(gInjectionMutex);
        if (enabled) { std::scoped_lock lock(gMutex); if (gService) RequireRestoreFlags(); }
        {
            std::scoped_lock lock(gMutex);
            if (!enabled && gService && gService->status.nativeHistoryDirty)
            {
                gService->status.runtimeDisablePending = true;
                gService->status.reason = "Restart required to return to native NRD; RR-only histories have replaced native temporal work";
                return; // Keep RR enabled: native history cannot silently resume.
            }
            if (enabled && gService) gService->status.runtimeDisablePending = false;
        }
        const bool previous = gRuntime.exchange(enabled,std::memory_order_acq_rel); if (previous == enabled) return;
        bool window = false; RetiredDebugSources retired;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            DropPending(owner,retired); owner.status.runtimeEnabled = enabled; owner.status.active = false;
            owner.status.phase = enabled ? "Waiting for NRD" : "Inactive";
            owner.status.reason = enabled ? "Waiting for the next Recon" : "Runtime toggle is off";
            if (enabled) owner.attempts = owner.failures = 0;
            if (enabled && !owner.cache.Valid()) StartWindow(owner);
            else owner.window = false;
            window = owner.window;
        }
        PublishBindingWindow();
        LOG_INFO("[NRD_BRIDGE] runtime={} (RR and depth history will reset at next Recon)",enabled);
    } catch (...) {}
}
bool RuntimeEnabled() noexcept { return gRuntime.load(std::memory_order_relaxed); }
void SetDebugMode(DebugMode mode) noexcept
{
    if (mode != DebugMode::Off && mode != DebugMode::RawSignals && mode != DebugMode::RRInputs) return;
    if (mode != DebugMode::Off && NativeDebugEnabled()) return;
    if (gDebug.exchange(mode,std::memory_order_acq_rel) != mode) RequestHistoryReset();
}
DebugMode GetDebugMode() noexcept { return gDebug.load(std::memory_order_relaxed); }
void RequestHistoryReset() noexcept
{
    try
    {
        RetiredDebugSources retired; std::scoped_lock lock(gMutex);
        if (!gService) return;
        ++gService->requestedResetRevision;
        // A user reset changes the next chain. It must not retire the immutable
        // private provider output required by an already recorded omission.
        if (MandatoryOutputPending(*gService)) return;
        DropPending(*gService,retired);
        if (gService->status.runtimeEnabled)
        { gService->status.phase = "Waiting for NRD"; gService->status.reason = "RR history reset requested; waiting for the next Recon"; }
    } catch (...) {}
}
bool ApplyRRSettings(const RRSettings& requested, bool cameraProjectedDepthDelta, std::string& error) noexcept
{
    try
    {
        RRSettings settings = requested;
        settings.nativeSpecularBlend = NormalizeNativeSpecularBlend(settings.nativeSpecularBlend);
        if (!ValidateRRSettings(settings,error)) return false;
        std::scoped_lock injection(gInjectionMutex);
        std::shared_ptr<Service> owner; std::shared_ptr<HistoryDomain> history;
        RRSettingsState before; RetiredDebugSources retired;
        {
            std::scoped_lock lock(gMutex); owner = gService;
            if (!owner) { error = "NRD bridge is not installed on the selected title device"; return false; }
            if (MandatoryOutputPending(*owner))
            {
                const bool changed = !SameDebugSettings(owner->rrSettings,settings) ||
                    owner->cameraProjectedDepthDelta != cameraProjectedDepthDelta ||
                    owner->rrSettings.legacyMotionDepth != settings.legacyMotionDepth ||
                    owner->rrSettings.surfaceValidFill != settings.surfaceValidFill;
                if (changed) ++owner->requestedResetRevision;
                if (!SameDebugSettings(owner->rrSettings,settings)) ClearNativeDebugSources(*owner,retired);
                owner->rrSettings = settings; owner->cameraProjectedDepthDelta = cameraProjectedDepthDelta;
                owner->rrSettingsState.requested = settings;
                gNativeDebug.store(settings.nativeDebugView >= 0,std::memory_order_release);
                gNativeMaterials.store(settings.nativeMaterialGuides,std::memory_order_release);
                if (settings.nativeDebugView >= 0) gDebug.store(DebugMode::Off,std::memory_order_release);
                error.clear(); return true; // No Configure/Discard/epoch change for the captured context.
            }
            history = owner->history; before = owner->rrSettingsState;
        }
        RRSettingsState after; bool configured = true;
        if (history)
        {
            configured = history->rr.Configure(settings,error);
            after = history->rr.GetSettingsState();
        }
        else after.requested = settings;
        {
            std::scoped_lock lock(gMutex);
            if (gService != owner) { error = "NRD bridge device changed while applying settings"; return false; }
            bool requestedScalarChanged = before.requested.overrideMask != settings.overrideMask;
            for (size_t i=0;i<6;++i)
                if ((settings.overrideMask & (1u<<i)) && before.requested.values[i] != settings.values[i]) requestedScalarChanged = true;
            const bool scalarChanged = before.ready && after.ready
                ? !std::equal(before.effective.begin(),before.effective.begin()+6,after.effective.begin()) : requestedScalarChanged;
            const bool motionChanged = owner->cameraProjectedDepthDelta != cameraProjectedDepthDelta ||
                owner->rrSettings.nativeTemporalMotion != settings.nativeTemporalMotion ||
                owner->rrSettings.legacyMotionDepth != settings.legacyMotionDepth;
            const bool debugChanged = owner->rrSettings.nativeDebugView != settings.nativeDebugView ||
                (settings.nativeDebugView >= 0 && owner->rrSettings.nativeDebugViewport != settings.nativeDebugViewport);
            const bool materialChanged = owner->rrSettings.preserveNativeMaterialIDs != settings.preserveNativeMaterialIDs ||
                owner->rrSettings.nativeMaterialGuides != settings.nativeMaterialGuides;
            // D02/WP08 fill flips select another decode profile for later frames;
            // like the material selector they reset bridge histories instead of
            // silently mixing profiles inside one history.
            const bool fillChanged = owner->rrSettings.surfaceValidFill != settings.surfaceValidFill;
            const bool recoveryChanged = owner->rrSettings.lobeRecovery != settings.lobeRecovery ||
                owner->rrSettings.recoverySpecular != settings.recoverySpecular ||
                owner->rrSettings.recoveryDiffuse != settings.recoveryDiffuse;
            const bool rawDebugCleared = settings.nativeDebugView >= 0 && gDebug.exchange(DebugMode::Off,std::memory_order_acq_rel) != DebugMode::Off;
            if (!SameDebugSettings(owner->rrSettings,settings)) ClearNativeDebugSources(*owner,retired);
            owner->rrSettings = settings; owner->cameraProjectedDepthDelta = cameraProjectedDepthDelta;
            owner->rrSettingsState = after; owner->rrSettingsState.requested = settings;
            gNativeDebug.store(settings.nativeDebugView >= 0,std::memory_order_release);
            gNativeMaterials.store(settings.nativeMaterialGuides,std::memory_order_release);
            if (scalarChanged || motionChanged || materialChanged || fillChanged || recoveryChanged || debugChanged || rawDebugCleared || !configured)
            {
                ++owner->requestedResetRevision;
                DropPending(*owner,retired);
                if (owner->status.runtimeEnabled)
                { owner->status.phase = "Waiting for NRD"; owner->status.reason = "RR settings changed; waiting for the next Recon"; }
            }
        }
        if (!configured) { Failure(owner,error.empty() ? "RR settings could not be applied" : error); return false; }
        error.clear(); return true;
    }
    catch (...) { error = "Exception while applying NRD RR settings"; return false; }
}
RRSettingsState GetRRSettingsState() noexcept
{
    try { std::scoped_lock lock(gMutex); if (gService) return gService->rrSettingsState; }
    catch (...) {}
    return {};
}
bool CameraProjectedDepthEnabled() noexcept
{
    try { std::scoped_lock lock(gMutex); return gService && gService->cameraProjectedDepthDelta; }
    catch (...) { return false; }
}
bool PresentNativeDebug(ID3D12GraphicsCommandList* cmd, ID3D12Resource* output,
                        D3D12_RESOURCE_STATES outputState, std::string& error) noexcept
{
    error.clear(); if (!NativeDebugEnabled()) return false;
    std::shared_ptr<Service> owner;
    try
    {
        std::scoped_lock injection(gInjectionMutex); NrdBridgeLifetime::ScopedBorrow borrow; if (!borrow.Acquired()) return false;
        const auto receiverBirth = NrdBridgeBirth::Capture(cmd,BirthMode()); if (!BirthLive(receiverBirth)) return false;
        RetiredDebugSources retired; std::optional<ListState> retiredList;
        std::array<std::shared_ptr<RecordingToken>,4> replacedPresentations;
        std::array<std::shared_ptr<NativeDebugSource>,4> candidates; uint64_t serial = 0, generation = 0, consumer = 0;
        std::shared_ptr<RecordingToken> sameProducer; std::array<std::weak_ptr<RecordingToken>,4> samePresentations;
        std::array<std::shared_ptr<RecordingToken>,2> sameNativeProducers; // RR-only transactions keep their own tokens.
        const auto targetSL = StreamlineHooks::getSLConstantsSnapshot().frameIndex;
        if (!cmd || !output || targetSL == UINT32_MAX) return false;
        {
            std::scoped_lock lock(gMutex); owner = gService;
            if (!owner || !NativeDebugEnabled() || owner->rrSettings.nativeDebugView < 0) return false;
            if (!owner->cache.Valid()) owner.reset(); // Logged below, outside gMutex.
            else
            {
                candidates = owner->nativeDebugSources; serial = owner->cancellationSerial; generation = owner->cache.Generation(); consumer = owner->status.framesBridged;
                if (const auto found = owner->lists.find(cmd); found != owner->lists.end() && found->second.birth == receiverBirth && ListLive(found->second))
                {
                    sameProducer = found->second.recording; samePresentations = found->second.debugPresentations;
                    for (size_t i = 0; i < sameNativeProducers.size(); ++i)
                        if (const auto& stage = found->second.native[i]) sameNativeProducers[i] = stage->recording;
                }
            }
        }
        if (!owner) { NativeDebugQuiet("the bridge discovery cache is not valid"); return false; }
        std::sort(candidates.begin(),candidates.end(),[](const auto& a,const auto& b) { return a && (!b || a->consumer > b->consumer); });
        std::shared_ptr<NativeDebugSource> source; DebugDependency producer,previous;
        uint32_t lag = UINT32_MAX;
        // Reason of the newest rejected candidate; candidates are sorted newest first.
        const char* quiet = nullptr;
        const auto skip = [&](const char* reason) { if (!quiet) quiet = reason; };
        for (const auto& candidate : candidates)
        {
            if (!candidate) continue;
            if (candidate->serial != serial || candidate->generation != generation)
            { skip("the retained image predates a reset or discovery generation"); continue; }
            if (consumer < candidate->consumer || consumer-candidate->consumer > 4)
            { skip("the retained image is more than 4 Consumer commits old"); continue; }
            if (candidate->history->uncertain.load(std::memory_order_acquire) ||
                candidate->recording->abandoned.load(std::memory_order_acquire) || !candidate->recording->outputCommitted.load(std::memory_order_acquire))
            { skip("the retained image's RR history or recording is not committed"); continue; }
            const auto distance = uint32_t(targetSL-candidate->image.frameSL);
            if (distance > 4) { skip("the retained image is more than 4 Streamline frames old"); continue; }
            {
                std::scoped_lock lock(gMutex);
                if (gService != owner || owner->cancellationSerial != serial || !SameDebugSettings(candidate->settings,owner->rrSettings))
                { skip("the debug settings changed after the image was retained"); continue; }
            }
            DebugDependency nextProducer {candidate->recording}, nextPrevious;
            nextProducer.sameRecording = candidate->image.recording == cmd &&
                (sameProducer == candidate->recording ||
                 std::find(sameNativeProducers.begin(),sameNativeProducers.end(),candidate->recording) != sameNativeProducers.end()) &&
                candidate->recording->phase.load(std::memory_order_acquire) == SubmissionPhase::Recorded;
            if (!nextProducer.sameRecording && !PublishedToken(nextProducer.token,nextProducer.point,nextProducer.submission))
            { skip("the image's RR recording has not been submitted yet"); continue; }
            if (const auto tail = PresentationTail(*candidate); tail && !tail->abandoned.load(std::memory_order_acquire))
            {
                nextPrevious.token = tail;
                nextPrevious.sameRecording = tail->phase.load(std::memory_order_acquire) == SubmissionPhase::Recorded &&
                    std::any_of(samePresentations.begin(),samePresentations.end(),[&](const auto& weak) { return OwnsToken(weak,tail); });
                if (!nextPrevious.sameRecording && !PublishedToken(tail,nextPrevious.point,nextPrevious.submission))
                { skip("the previous presentation of the image has not been submitted yet"); continue; }
            }
            source = candidate; producer = std::move(nextProducer); previous = std::move(nextPrevious); lag = distance; break;
        }
        // Startup, a newer unsubmitted image, or an aged image is an ordinary quiet skip.
        if (!source) { NativeDebugQuiet(quiet ? quiet : "no committed RR debug image has been retained"); return false; }
        if (!FrameSurvey::MetadataHealthy() || !D3D12Hooks::CanRestoreRootSignature(cmd))
        { error = "Native debug target compute state cannot be restored or binding metadata is unhealthy"; NativeDebugDiagnostic(owner,error); return false; }
        auto ownership = MakeOwnedShared<DebugPresentationOwnership>(); ownership->source = source;
        ownership->token = MakeOwnedShared<RecordingToken>(); ownership->retiredPresentation = PresentationTail(*source);
        ownership->producer = std::move(producer); ownership->previous = std::move(previous);
        std::array<std::shared_ptr<RecordingToken>,4> retiredPresentations;
        {
            std::scoped_lock lock(gMutex);
            if (gService != owner || owner->cancellationSerial != serial || !NativeDebugEnabled() || !BirthLive(receiverBirth)) return false;
            gTrackedLists.Insert(cmd); auto& destination = owner->lists[cmd];
            if (destination.birth != receiverBirth) ReplaceList(*owner,cmd,destination,receiverBirth,retiredList,replacedPresentations,retired);
            destination.birth = receiverBirth;
            auto& slots = destination.debugPresentations; size_t i = 0;
            auto free = std::find_if(slots.begin(),slots.end(),[&](const auto& weak) {
                const auto& token = retiredPresentations[i++] = weak.lock();
                return !token || token->abandoned.load(std::memory_order_acquire) || token->submitted.load(std::memory_order_acquire); });
            if (free == slots.end()) return false;
            *free = ownership->token;
        }
        RecordedComputeLease::SubmissionCallbacks submission; const std::weak_ptr<Service> weakOwner = owner;
        submission.beforeSubmit = [ownership](const RecordedComputeLease::SubmissionInfo& info) {
            if (!ownership->recorded.load(std::memory_order_acquire)) return true;
            RecordedComputeLease::FencePointPtr retiredPoint;
            {
                std::scoped_lock lock(ownership->token->publicationMutex);
                ownership->token->submitted.store(true,std::memory_order_release); ownership->token->submissionId = info.submissionId;
                retiredPoint = std::move(ownership->token->completion); ownership->token->phase.store(SubmissionPhase::Submitting,std::memory_order_release);
            }
            if (ownership->token->abandoned.load(std::memory_order_acquire) || info.recordingSubmission > 1 || info.snapshotFallback)
            { RecordedComputeLease::DenySubmission(E_FAIL); return false; }
            return DebugDependencyBeforeSubmit(ownership->producer,info) && DebugDependencyBeforeSubmit(ownership->previous,info);
        };
        submission.fencePublished = [ownership](const RecordedComputeLease::SubmissionInfo& info,const RecordedComputeLease::FencePointPtr& point) {
            if (!ownership->recorded.load(std::memory_order_acquire)) return;
            RecordedComputeLease::FencePointPtr retiredPoint; std::scoped_lock lock(ownership->token->publicationMutex);
            if (ownership->token->submissionId == info.submissionId && ownership->token->phase.load(std::memory_order_acquire) == SubmissionPhase::Submitting)
            { retiredPoint = std::move(ownership->token->completion); ownership->token->completion = point; ownership->token->phase.store(SubmissionPhase::FencePublished,std::memory_order_release); }
        };
        submission.failed = [ownership,weakOwner](const auto&,auto) {
            if (!ownership->recorded.load(std::memory_order_acquire)) return;
            RecordedComputeLease::FencePointPtr retiredPoint;
            {
                std::scoped_lock lock(ownership->token->publicationMutex); retiredPoint = std::move(ownership->token->completion);
                ownership->token->phase.store(SubmissionPhase::Poisoned,std::memory_order_release);
            }
            if (const auto service = weakOwner.lock())
            {
                NativeDebugOrderingFailure(service);
            }
        };
        if (!ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),cmd,ownership,{},std::move(submission)))
        { ownership->token->abandoned.store(true,std::memory_order_release); error = "Native debug submission lifetime tracking is unavailable"; NativeDebugDiagnostic(owner,error); return false; }
        struct PresentationTicket
        {
            std::shared_ptr<Service> owner;
            std::shared_ptr<DebugPresentationOwnership> ownership;
            ID3D12GraphicsCommandList* cmd;
            uint32_t lag;
            NrdBridgeBirth::Token receiverBirth;
            bool cancelled = false, log = false;
            static bool Admit(void* state, OutputCommitGuard::Action action, void* prepared) noexcept
            {
                auto& ticket = *static_cast<PresentationTicket*>(state); const auto& source = *ticket.ownership->source;
                std::scoped_lock lock(gMutex); const auto found = ticket.owner->lists.find(ticket.cmd);
                if (gService != ticket.owner || !NativeDebugEnabled() || !FrameSurvey::MetadataHealthy() || !ticket.owner->cache.Valid() ||
                    ticket.owner->cancellationSerial != source.serial || ticket.owner->cache.Generation() != source.generation ||
                    !SameDebugSettings(source.settings,ticket.owner->rrSettings) || source.history->uncertain.load(std::memory_order_acquire) ||
                    source.recording->abandoned.load(std::memory_order_acquire) || found == ticket.owner->lists.end() ||
                    found->second.birth != ticket.receiverBirth || !ListLive(found->second) ||
                    !std::any_of(found->second.debugPresentations.begin(),found->second.debugPresentations.end(),[&](const auto& weak) { return OwnsToken(weak,ticket.ownership->token); }))
                { ticket.cancelled = true; return false; }
                action(prepared);
                { std::scoped_lock imageLock(source.imageOrder->mutex); source.imageOrder->presentation = ticket.ownership->token; }
                ticket.ownership->token->outputCommitted.store(true,std::memory_order_release); ticket.ownership->recorded.store(true,std::memory_order_release);
                ticket.log = ticket.owner->nativeDebugLastLag != ticket.lag; ticket.owner->nativeDebugLastLag = ticket.lag; ticket.owner->nativeDebugError.clear(); return true;
            }
        } ticket {owner,ownership,cmd,lag,receiverBirth};
        bool presented = false;
        {
            InjectionScope guard(cmd); const OutputCommitGuard admission {&ticket,PresentationTicket::Admit};
            presented = source->history->rr.PresentNativeDebug(cmd,output,outputState,source->image,error,!ownership->producer.sameRecording,admission);
        }
        if (!presented)
        {
            ownership->token->abandoned.store(true,std::memory_order_release);
            if (ticket.cancelled) { error.clear(); return false; }
            if (!error.empty()) NativeDebugDiagnostic(owner,error); return false;
        }
        gNativeDebugQuiet.store(nullptr,std::memory_order_relaxed); // A later persistent skip is reported again.
        if (ticket.log) LOG_INFO("[NRD_BRIDGE] native AMD debug source_SL={} target_SL={} SL_distance={} view={} viewport={} (submitted snapshot or same recording)",
            source->image.frameSL,targetSL,lag,source->settings.nativeDebugView,source->settings.nativeDebugViewport);
        return true;
    }
    catch (...) { try { error = "Exception while preparing native debug presentation"; if (owner) NativeDebugDiagnostic(owner,error); } catch (...) {} return false; }
}
bool NativeDebugEnabled() noexcept
{ return gInstalled.load(std::memory_order_relaxed) && gRuntime.load(std::memory_order_relaxed) && gNativeDebug.load(std::memory_order_relaxed); }
#ifdef FSRD_NRD_BRIDGE_TEST
void SetNativeElisionContractForTesting(bool enabled) noexcept
{
    std::scoped_lock lock(gMutex);
    if (!enabled && gService && gService->status.nativeHistoryDirty) return;
    gNativeElisionForTesting.store(enabled,std::memory_order_release);
}
bool RegisterInterveningPipelineForTesting(ID3D12PipelineState* pipeline,uint32_t profile) noexcept
{
    // Only the shader-family selection is an adapter. Keep the REAL native PSO
    // hash/stamp, actual roots/typed descriptors and submission witness checks.
    FrameSurvey::PipelineShaderIdentity actual;
    if(profile>4||!FrameSurvey::ResolvePipelineShaderIdentity(pipeline,actual)||!actual.complete||
        (profile<2?actual.presentStages!=FrameSurvey::PipelineCS:
            actual.presentStages!=(FrameSurvey::PipelineVS|FrameSurvey::PipelinePS)))return false;
    try
    {
        std::scoped_lock lock(gMutex);if(!gService)return false;
        gRelevantPipelines.Insert(pipeline);gService->interveningPipelines[pipeline]={int(profile),actual.pipelineBirth,true};return true;
    }
    catch(...){return false;}
}
void RegisterPipelineRoleForTesting(ID3D12PipelineState* pipeline, Role role, bool nativeContract) noexcept
{
    try { const auto birth = NrdBridgeBirth::Capture(pipeline,BirthMode()); std::scoped_lock lock(gMutex);
        if (gService && pipeline && BirthLive(birth)) { gRelevantPipelines.Insert(pipeline); gService->roles[pipeline] = {role,birth,nativeContract}; } } catch (...) {}
}
#endif
}
