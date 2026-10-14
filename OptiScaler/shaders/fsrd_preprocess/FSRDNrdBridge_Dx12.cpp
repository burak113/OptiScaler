#include "pch.h"
#include "misc/NrdBridgePerf_Dx12.h"
#include "FSRDNrdBridge_Dx12.h"
#include "FSRDNrdDiscovery.h"
#include "FSRDNrdBridgePass_Dx12.h"
#include "FSRDNrdBridgeRR_Dx12.h"
#include "Config.h"
#include "Util.h"
#include "hooks/D3D12_Hooks.h"
#include "hooks/Streamline_Hooks.h"
#include "resource_tracking/ResTrack_dx12.h"
#include "misc/NrdBridgeLifetime_Dx12.h"
#include "misc/NrdBridgeOwned_Dx12.h"
#include "misc/RecordedComputeLease_Dx12.h"
#include "misc/NrdBridgeDevice_Dx12.h"
#include <atomic>
#include <mutex>
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
struct RecordingToken
{
    std::atomic<bool> submitted {false}, outputCommitted {false};
    std::atomic<SubmissionPhase> phase {SubmissionPhase::Recorded};
};
struct HistoryDomain
{
    ConversionPass conversion;
    RRWrapper rr;
    uint64_t resourceGeneration = 0, id = 0;
    std::shared_ptr<RecordingToken> latestRecording; // CPU recording order, under gInjectionMutex.
    std::atomic<bool> uncertain {false}, discardPending {false};
    std::mutex submissionMutex;
    RecordedComputeLease::FencePointPtr completion;
    uint64_t latestSubmissionId = 0;
    bool pendingSubmission = false;
};
struct RecordingOwnership
{
    std::shared_ptr<HistoryDomain> history;
    std::shared_ptr<RecordingToken> token;
};
struct ListState
{
    Role role = Role::None;
    ChainDiscovery chain;
    std::array<ID3D12Resource*,11> indexedReferences {};
    bool followingRecon = false, converted = false, motionReady = false, temporal = false, atrous = false, nrdList = false;
    std::shared_ptr<RecordingToken> recording;
    std::shared_ptr<HistoryDomain> history;
    uint64_t frame = 0, generation = 0, resetSerial = 0;
    FrameParameters parameters {};
    ConvertedResources inputs {};
    DebugMode debug = DebugMode::Off;
};
struct Service
{
    Microsoft::WRL::ComPtr<ID3D12Device> device;
    std::unordered_map<ID3D12PipelineState*,Role> roles;
    std::unordered_map<ID3D12GraphicsCommandList*,ListState> lists;
    std::unordered_map<void*,std::unordered_set<ID3D12GraphicsCommandList*>> chainUsers;
    std::unordered_set<ID3D12GraphicsCommandList*> followingChains;
    DiscoveryCache cache;
    std::shared_ptr<HistoryDomain> history;
    std::vector<std::weak_ptr<HistoryDomain>> historyDomains;
    uint64_t nextDomain = 0;
    Status status;
    RRSettings rrSettings {};
    RRSettingsState rrSettingsState {};
    bool cameraProjectedDepthDelta = false;
    ID3D12Resource* taggedMotion = nullptr;
    ID3D12GraphicsCommandList* pendingList = nullptr;
    uint64_t frame = 0, resetSerial = 1, cancellationSerial = 1, appliedReset = 0, lastLog = 0, activeFrame = 0;
    uint32_t windowPresents = 0, retryPresents = 0, attempts = 0, failures = 0, lastSLFrame = UINT32_MAX;
    bool window = false, windowSawRecon = false, everRecon = false, observedRecon = false, conventionsLogged = false, discardRequested = false;
};
NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Coordinator> gMutex;
std::mutex gInjectionMutex, gWindowMutex;
std::shared_ptr<Service> gService;
std::atomic<bool> gInstalled {false}, gRuntime {false};
std::atomic<int> gStartupSelection {-1};
std::string gUnavailableReason;
std::atomic<DebugMode> gDebug {DebugMode::Off};
std::atomic<bool> gNativeDebug {false};
#ifdef FSRD_NRD_BRIDGE_TEST
void (*gBeforeConversionLockForTesting)() = nullptr;
void (*gBeforeBindingWindowPublishForTesting)() = nullptr;
void (*gBeforeOutputLockForTesting)() = nullptr;
#endif

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
    NrdBridgeLifetime::ScopedBorrow borrow;
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
    return settings;
}
template<class Configuration> bool ReadStartupCameraDepth(const Configuration& config)
{
    if constexpr (requires { config.FfxDenoiserNrdBridgeMotionDepthMode; })
        return config.FfxDenoiserNrdBridgeMotionDepthMode.value_or_default();
    return false;
}
Role PipelineRole(const Service& owner, ID3D12PipelineState* pipeline)
{
    const auto found = owner.roles.find(pipeline); return found == owner.roles.end() ? Role::None : found->second;
}
// Caller holds gMutex. Release looks up only chains which actually use the address;
// descriptor creation or an unrelated final Release never walks all participant lists.
void UpdateChainUsers(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list,
                      const std::array<ID3D12Resource*,11>& next)
{
    const auto& prior = list.indexedReferences;
    for (auto* object : prior)
        if (object && std::find(next.begin(),next.end(),object) == next.end())
            if (const auto found = owner.chainUsers.find(object); found != owner.chainUsers.end())
            { found->second.erase(cmd); if (found->second.empty()) owner.chainUsers.erase(found); }
    for (auto* object : next)
        if (object && std::find(prior.begin(),prior.end(),object) == prior.end()) owner.chainUsers[object].insert(cmd);
    list.indexedReferences = next;
}
void RemoveChainUsers(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list)
{ UpdateChainUsers(owner,cmd,list,{}); }
void RefreshChainUsers(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list)
{ UpdateChainUsers(owner,cmd,list,list.chain.Valid() ? list.chain.ReferencedResources() : std::array<ID3D12Resource*,11>{}); }
void StopFollowing(Service& owner, ID3D12GraphicsCommandList* cmd, ListState& list)
{ list.followingRecon = false; owner.followingChains.erase(cmd); }
void DropPending(Service& owner)
{
    owner.pendingList = nullptr; owner.status.active = false;
    for (auto& [cmd,list] : owner.lists) list.converted = list.motionReady = false;
    ++owner.resetSerial; ++owner.cancellationSerial;
}
void IdentityChanged(Service& owner, const char* reason)
{
    owner.cache.Invalidate(); DropPending(owner); owner.status.active = false;
    owner.status.phase = "Discovering"; owner.status.reason = reason; owner.status.resources.clear();
    owner.status.width = owner.status.height = 0;
}
void StartWindow(Service& owner)
{
    owner.window = true; owner.windowSawRecon = false; owner.windowPresents = 0; owner.retryPresents = 0;
    if (!owner.cache.Valid()) { owner.status.active = false; owner.status.phase = "Discovering"; }
}
void Invalidate(Service& owner, const std::string& reason)
{
    owner.cache.Invalidate(); DropPending(owner); owner.status.active = false;
    owner.status.reason = reason; owner.status.phase = "Discovering"; owner.status.resources.clear();
    owner.status.width = owner.status.height = 0; owner.attempts = owner.failures = 0;
    if (owner.status.runtimeEnabled) StartWindow(owner);
    else { owner.window = false; owner.status.phase = "Inactive"; }
}
void Failure(const std::shared_ptr<Service>& owner, const std::string& reason)
{
    bool log = false;
    {
        std::scoped_lock lock(gMutex);
        if (gService != owner) return;
        log = owner->status.reason != reason;
        owner->cache.Invalidate(); DropPending(*owner); owner->window = false; owner->retryPresents = 0;
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
    bool log = false;
    {
        std::scoped_lock lock(gMutex);
        if (gService != owner || !owner->window) return;
        if (owner->cache.Valid()) owner->cache.Invalidate();
        DropPending(*owner);
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
void Convert(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, uint64_t frame)
{
    Resources resources; uint64_t generation = 0, serial = 0; bool reset = false, discard = false;
    RRSettings rrSettings; bool cameraProjectedDepthDelta = false;
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() ||
            found == owner->lists.end() || found->second.frame != frame ||
            !found->second.followingRecon || !found->second.chain.Valid()) return;
        resources = owner->cache.Get();
        // Capture this Recon's validated guides, rather than the prior Consumer's cached pointers.
        resources.normals = found->second.chain.Get().normals;
        resources.viewDepth = found->second.chain.Get().viewDepth;
        generation = owner->cache.Generation(); serial = owner->cancellationSerial;
        reset = serial != owner->appliedReset;
    }
    #ifdef FSRD_NRD_BRIDGE_TEST
    if (gBeforeConversionLockForTesting) gBeforeConversionLockForTesting();
#endif
    std::scoped_lock injection(gInjectionMutex); // Provider calls never hold the coordinator/registry mutex.
    NrdBridgeLifetime::ScopedBorrow borrow;
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() ||
            owner->cache.Generation() != generation || owner->cancellationSerial != serial || found == owner->lists.end() ||
            found->second.frame != frame || !found->second.followingRecon || !found->second.chain.Valid() ||
            found->second.chain.Get().normals != resources.normals ||
            found->second.chain.Get().viewDepth != resources.viewDepth) return;
        discard = owner->discardRequested;
        rrSettings = owner->rrSettings; cameraProjectedDepthDelta = owner->cameraProjectedDepthDelta;
    }
    if (!FrameSurvey::MetadataHealthy()) { Failure(owner,"Creation or binding metadata is unhealthy; restart the title/device"); return; }
    if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored after Recon"); return; }
    std::string error, conventions; FrameParameters parameters; ConvertedResources converted;
    bool succeeded = false; auto recording = MakeOwnedShared<RecordingToken>();
    std::shared_ptr<HistoryDomain> history = owner->history;
    if (discard)
    {
        for (const auto& weak : owner->historyDomains)
            if (const auto abandoned = weak.lock(); abandoned && abandoned->discardPending.exchange(false,std::memory_order_acq_rel))
            {
                abandoned->uncertain.store(true,std::memory_order_release);
                FrameSurvey::ScopedInternal internal;
                abandoned->rr.DiscardRecordingHistory();
            }
    }
    const bool reusable = history && history->resourceGeneration == generation &&
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
        { Failure(owner,"NRD has 8 unretired temporal generations; submit/reset recordings before retrying"); return; }
        history = MakeOwnedShared<HistoryDomain>();
        history->resourceGeneration = generation; history->id = ++owner->nextDomain;
        owner->historyDomains.push_back(history); owner->history = history;
        reset = true;
    }
    history->latestRecording = recording;
    auto ownership = MakeOwnedShared<RecordingOwnership>(); ownership->history = history; ownership->token = recording;
    RecordedComputeLease::SubmissionCallbacks submission;
    submission.beforeSubmit = [ownership](const RecordedComputeLease::SubmissionInfo& info) {
        auto& domain = *ownership->history;
        ownership->token->submitted.store(true,std::memory_order_release);
        ownership->token->phase.store(SubmissionPhase::Submitting,std::memory_order_release);
        // Replaying a closed recording changes temporal causality. Existing work is
        // still ordered and retained; the next recording gets a fresh RESET domain.
        if (info.recordingSubmission > 1 || info.snapshotFallback)
            domain.uncertain.store(true,std::memory_order_release);
        RecordedComputeLease::FencePointPtr predecessor;
        {
            std::scoped_lock lock(domain.submissionMutex);
            // A prior Execute without a newly published fence cannot be ordered by
            // an older completion point. Already-recorded successors must stop too.
            if (domain.pendingSubmission && domain.latestSubmissionId != info.submissionId)
            { RecordedComputeLease::DenySubmission(E_FAIL); return false; }
            predecessor = domain.completion;
            domain.latestSubmissionId = info.submissionId; domain.pendingSubmission = true;
        }
        return SUCCEEDED(RecordedComputeLease::WaitForFence(info.queue,predecessor));
    };
    submission.fencePublished = [ownership](const RecordedComputeLease::SubmissionInfo& info,
                                            const RecordedComputeLease::FencePointPtr& point) {
        auto& domain = *ownership->history;
        {
            std::scoped_lock lock(domain.submissionMutex);
            if (domain.latestSubmissionId == info.submissionId)
            { domain.completion = point; domain.pendingSubmission = false; }
        }
        ownership->token->phase.store(SubmissionPhase::FencePublished,std::memory_order_release);
    };
    const std::weak_ptr<Service> weakOwner = owner;
    submission.failed = [ownership,weakOwner](const auto&, auto) {
        ownership->history->uncertain.store(true,std::memory_order_release);
        ownership->token->phase.store(SubmissionPhase::Poisoned,std::memory_order_release);
        if (const auto service = weakOwner.lock())
            Failure(service,"NRD submission ordering or fence tracking failed; restart the title/device");
    };
    {
        InjectionScope guard(cmd);
        if (discard)
        {
            std::scoped_lock lock(gMutex);
            if (gService == owner && owner->cancellationSerial == serial) owner->discardRequested = false;
        }
        if (reset) { history->conversion.ResetHistory(); history->rr.ResetHistory(); }
        const auto snapshot = StreamlineHooks::getSLConstantsSnapshot();
        succeeded = history->rr.Configure(rrSettings,error);
        if (succeeded) succeeded = history->rr.PrepareFrame(snapshot,reset,parameters,error);
        parameters.cameraProjectedDepthDelta = cameraProjectedDepthDelta;
        if (succeeded && parameters.reset) history->conversion.ResetHistory();
        if (succeeded) succeeded = history->conversion.Initialize(owner->device.Get(),resources.width,resources.height,error);
        if (succeeded) succeeded = ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),cmd,ownership,{},std::move(submission));
        if (!succeeded && error.empty()) error = "Could not retain NRD recording submission token";
        if (succeeded)
        {
            const ConversionInputs inputs {resources.reconSpec,resources.reconDiff,resources.normals,resources.viewDepth,nullptr};
            succeeded = history->conversion.Dispatch(cmd,inputs,parameters,converted,error);
        }
        if (succeeded) conventions = Conventions(history->rr);
    }
    if (!succeeded) { Failure(owner,error.empty() ? "NRD input conversion failed" : error); return; }
    bool logConventions = false;
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() ||
            owner->cache.Generation() != generation || owner->cancellationSerial != serial || found == owner->lists.end() ||
            found->second.frame != frame) return;
        auto& list = found->second;
        list.converted = true; list.motionReady = false; list.recording = recording; list.history = history;
        list.generation = generation; list.resetSerial = serial;
        list.parameters = parameters; list.inputs = converted; list.debug = gDebug.load(std::memory_order_relaxed);
        owner->rrSettingsState = history->rr.GetSettingsState();
        owner->pendingList = cmd; owner->appliedReset = serial;
        logConventions = !owner->conventionsLogged && !conventions.empty();
        if (logConventions) owner->conventionsLogged = true;
    }
    if (logConventions) LOG_INFO("[NRD_BRIDGE] SL conventions: {}",conventions);
}
template<class Pass> bool DispatchCurrentMotion(Pass& pass, ID3D12GraphicsCommandList* cmd,
    const ConvertedResources& converted, ID3D12Resource* motion, const FrameParameters& frame, std::string& error)
{
    if constexpr (requires { pass.DispatchMotion(cmd,converted,motion,frame,error); })
        return pass.DispatchMotion(cmd,converted,motion,frame,error);
    error = "NRD motion finalization interface is unavailable"; return false;
}
void FinalizeMotion(const std::shared_ptr<Service>& owner, ID3D12GraphicsCommandList* cmd, uint64_t frame,
                    ID3D12Resource* currentMotion)
{
    std::scoped_lock injection(gInjectionMutex);
    NrdBridgeLifetime::ScopedBorrow borrow;
    ListState staged;
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() || found == owner->lists.end()) return;
        const auto& list = found->second;
        if (!list.converted || list.motionReady || list.frame != frame || list.generation != owner->cache.Generation() ||
            list.resetSerial != owner->cancellationSerial || owner->cache.Get().motion != currentMotion) return;
        staged = list;
    }
    if (!FrameSurvey::MetadataHealthy()) { Failure(owner,"Creation or binding metadata is unhealthy; restart the title/device"); return; }
    if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored after first Temporal"); return; }
    std::string error; bool succeeded = false;
    {
        InjectionScope guard(cmd);
        succeeded = DispatchCurrentMotion(staged.history->conversion,cmd,staged.inputs,currentMotion,staged.parameters,error);
    }
    if (!succeeded) { Failure(owner,error.empty() ? "NRD current motion conversion failed" : error); return; }
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || !owner->cache.Valid() || found == owner->lists.end()) return;
        auto& list = found->second;
        if (list.frame == frame && list.generation == owner->cache.Generation() && list.resetSerial == owner->cancellationSerial && list.converted)
            list.motionReady = true;
    }
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
void ConfigureStartup(bool enabled) noexcept
{
    int unconfigured = -1;
    gStartupSelection.compare_exchange_strong(unconfigured, enabled && SupportedExecutable() ? 1 : 0,
        std::memory_order_release, std::memory_order_relaxed);
}
bool StartupEnabled() noexcept
{
    return gStartupSelection.load(std::memory_order_acquire) == 1;
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
                gRuntime.store(gService->status.runtimeEnabled,std::memory_order_release); gInstalled.store(true,std::memory_order_release);
            }
            // Publish observers under lifecycle serialization, outside the state lock.
            FrameSurvey::SetPipelineObserver(OnPipelineCreated); FrameSurvey::SetReleaseObserver(OnReleased);
            PublishBindingWindow();
        }
        // Owned D3D12 releases may re-enter hooks. Destroy outside both coordinator locks.
        { FrameSurvey::ScopedInternal internal; previous.reset(); }
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
                LOG_INFO("[NRD_BRIDGE] perf frames={} SL_frame={}..{} window=100_gameplay_Consumer_intervals scope=all_external_hook_wall_times_including_native cpu_hooks_sum_ms_per_frame={:.3f} lock_wait_sum_ms_per_frame={:.3f} top_sum_ms_per_frame={} wait_scope=metadata+physical_borrow+tracking+coordinator CBV_avg_us={:.3f} CBV_wait_us={:.3f} CBV_metadata_wait_us={:.3f} CBV_calls={} SRV_avg_us={:.3f} SRV_wait_us={:.3f} SRV_metadata_wait_us={:.3f} SRV_calls={} UAV_avg_us={:.3f} UAV_wait_us={:.3f} UAV_metadata_wait_us={:.3f} UAV_calls={} Release_avg_us={:.3f} Release_wait_us={:.3f} Release_metadata_wait_us={:.3f} Release_borrow_wait_us={:.3f} Release_tracking_wait_us={:.3f} Release_coordinator_wait_us={:.3f} Release_calls={}",
                    perf.frames,perf.firstFrame,perf.lastFrame,perf.SumMsPerFrame(),perf.SumMsPerFrame(true),top,perf.AverageUs(H::ConstantBufferView),perf.AverageWaitUs(H::ConstantBufferView),
                    perf.AverageWaitUs(H::ConstantBufferView,NrdBridgePerf::WaitKind::Metadata),perf.hooks[size_t(H::ConstantBufferView)].calls,
                    perf.AverageUs(H::ShaderResourceView),perf.AverageWaitUs(H::ShaderResourceView),
                    perf.AverageWaitUs(H::ShaderResourceView,NrdBridgePerf::WaitKind::Metadata),perf.hooks[size_t(H::ShaderResourceView)].calls,
                    perf.AverageUs(H::UnorderedAccessView),perf.AverageWaitUs(H::UnorderedAccessView),
                    perf.AverageWaitUs(H::UnorderedAccessView,NrdBridgePerf::WaitKind::Metadata),perf.hooks[size_t(H::UnorderedAccessView)].calls,
                    perf.AverageUs(H::Release),perf.AverageWaitUs(H::Release),perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::Metadata),
                    perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::LifetimeGate),perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::Tracking),
                    perf.AverageWaitUs(H::Release,NrdBridgePerf::WaitKind::Coordinator),perf.hooks[size_t(H::Release)].calls);
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
            gNativeDebug.store(false,std::memory_order_release);
            FrameSurvey::SetPipelineObserver(nullptr); FrameSurvey::SetReleaseObserver(nullptr); PublishBindingWindow();
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
        const auto role = hash ? IdentifyRole(hash) : Role::None; std::scoped_lock lock(gMutex);
        if (!gService) return;
        if (role == Role::None) gService->roles.erase(pipeline); else gService->roles[pipeline] = role;
    } catch (...) {}
}
void OnSetPipeline(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* pipeline) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !cmd) return;
    try
    {
        bool open = false, seed = false;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            const auto role = PipelineRole(owner,pipeline);
            if (role != Role::None) owner.lists[cmd].role = role;
            else if (const auto found = owner.lists.find(cmd); found != owner.lists.end()) found->second.role = Role::None;
            if (gRuntime.load(std::memory_order_relaxed) && !owner.window && owner.attempts < 3 && owner.failures < 3 &&
                (role == Role::PrepLast || role == Role::Recon) && (owner.cache.Valid() || owner.retryPresents >= 60 ||
                    (role == Role::Recon && !owner.everRecon)))
            {
                StartWindow(owner); if (!owner.cache.Valid()) owner.status.reason = "NRD pipeline observed; waiting for complete bindings"; open = true;
            }
            seed = owner.window && (role == Role::PrepLast || role == Role::Recon);
        }
        if (open) PublishBindingWindow();
        if (seed) SeedForWindow(cmd);
    } catch (...) {}
}
void OnReset(ID3D12GraphicsCommandList* cmd, ID3D12PipelineState* initial) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !cmd) return;
    try
    {
        bool open = false;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            if (gRuntime.load(std::memory_order_relaxed)) RequireRestoreFlags();
            const auto found = owner.lists.find(cmd);
            if (found != owner.lists.end())
            {
                const bool nrdList = found->second.nrdList;
                const bool unsubmitted = found->second.recording && !found->second.recording->submitted.load(std::memory_order_acquire);
                if (unsubmitted && found->second.history)
                {
                    found->second.history->uncertain.store(true,std::memory_order_release);
                    found->second.history->discardPending.store(true,std::memory_order_release);
                    owner.discardRequested = true;
                }
                if (found->second.converted || owner.pendingList == cmd || unsubmitted)
                {
                    if (owner.pendingList == cmd) owner.pendingList = nullptr;
                    if (owner.activeFrame == found->second.frame) owner.status.active = false;
                    ++owner.resetSerial;
                }
                RemoveChainUsers(owner,cmd,found->second); StopFollowing(owner,cmd,found->second);
                found->second = {}; found->second.nrdList = nrdList; found->second.role = PipelineRole(owner,initial);
                if (nrdList && gRuntime.load(std::memory_order_relaxed) && !owner.window && owner.attempts < 3 && owner.failures < 3 &&
                    (owner.cache.Valid() || owner.retryPresents >= 60 || !owner.everRecon))
                { StartWindow(owner); open = true; }
            }
            else if (const auto role = PipelineRole(owner,initial); role != Role::None)
            {
                owner.lists[cmd].role = role;
                if (gRuntime.load(std::memory_order_relaxed) && !owner.window && owner.attempts < 3 && owner.failures < 3 &&
                    (role == Role::PrepLast || role == Role::Recon) && (owner.cache.Valid() || owner.retryPresents >= 60 ||
                        (role == Role::Recon && !owner.everRecon)))
                { StartWindow(owner); open = true; }
            }
        }
        if (open) PublishBindingWindow();
    } catch (...) { CoordinatorException("Exception while resetting NRD command-list recording"); }
}
void AfterDispatch(ID3D12GraphicsCommandList* cmd) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || !gRuntime.load(std::memory_order_relaxed) || FrameSurvey::Internal()) return;
    try
    {
        std::shared_ptr<Service> owner; Role role = Role::None; uint64_t frame = 0;
        bool firstTemporal = false, invalid = false; ID3D12Resource* currentMotion = nullptr; std::string error;
        {
            NrdBridgeLifetime::ScopedBorrow borrow; // Ends before taking the native injection mutex.
            bool window = false, cooldown = false;
            {
                std::scoped_lock lock(gMutex); owner = gService; if (!owner) return;
                const auto found = owner->lists.find(cmd); if (found == owner->lists.end()) return;
                role = found->second.role; window = owner->window;
                if (!window) { StopFollowing(*owner,cmd,found->second); cooldown = true; } // Retry cooldown records no owned work.
                else if (role == Role::Recon)
                {
                    auto& list = found->second; RemoveChainUsers(*owner,cmd,list); StopFollowing(*owner,cmd,list);
                    auto recording = std::move(list.recording);
                    auto previousHistory = std::move(list.history);
                    list = {}; list.recording = std::move(recording); list.history = std::move(previousHistory);
                    // Prior unsubmitted RR work survives a second incomplete Recon.
                    list.role = role; list.followingRecon = list.nrdList = true; owner->followingChains.insert(cmd);
                    list.frame = frame = ++owner->frame; owner->observedRecon = owner->everRecon = true;
                    if (window) owner->windowSawRecon = true;
                }
                else
                {
                    if (!found->second.followingRecon || role == Role::None || role == Role::Consumer) return;
                    firstTemporal = role == Role::Temporal && !found->second.temporal;
                    frame = found->second.frame;
                }
            }
            if (cooldown) return;
            if (!window) { Failure(owner,"Current NRD bindings have no frame-local validation window"); return; }
            std::vector<FrameSurvey::BoundResource> srv, uav;
            if (!Tables(cmd,role,srv,uav)) { WaitingForBindings(owner,cmd,"Current NRD table metadata is incomplete"); return; }
            {
                std::scoped_lock lock(gMutex); if (gService != owner) return;
                const auto found = owner->lists.find(cmd); if (found == owner->lists.end() || found->second.frame != frame) return;
                auto& list = found->second;
                if (role == Role::Recon) invalid = !list.chain.Begin(srv,uav,error);
                else invalid = !list.chain.Observe(role,srv,uav,owner->taggedMotion,error);
                RefreshChainUsers(*owner,cmd,list);
                if (role == Role::Temporal) list.temporal = true;
                if (role == Role::ATrous && list.temporal) list.atrous = true;
                if (!invalid && role == Role::Recon && owner->cache.Valid())
                {
                    const auto& a = list.chain.Get(); const auto& b = owner->cache.Get();
                    if (a.width != b.width || a.height != b.height || a.inputSpec != b.inputSpec || a.inputDiff != b.inputDiff ||
                        a.reconSpec != b.reconSpec || a.reconDiff != b.reconDiff)
                    {
                        IdentityChanged(*owner,"Current Recon resource identity changed");
                    }
                }
                if (!invalid && firstTemporal)
                {
                    currentMotion = list.chain.Get().motion;
                    if (owner->cache.Valid() && owner->cache.Get().motion != currentMotion)
                    {
                        IdentityChanged(*owner,"Current Temporal motion resource changed");
                    }
                }
            }
        }
        if (invalid) { Failure(owner,error); return; }
        if (role == Role::Recon) Convert(owner,cmd,frame);
        else if (firstTemporal) FinalizeMotion(owner,cmd,frame,currentMotion);
    } catch (...) { CoordinatorException("Exception while preparing current NRD input bindings"); }
}
void BeforeDispatch(ID3D12GraphicsCommandList* cmd) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() ||
        (!gRuntime.load(std::memory_order_relaxed) && !NrdBridgePerf::NeedsConsumerFrames())) return;
    try
    {
        std::shared_ptr<Service> owner; bool window = false, following = false;
        {
            std::scoped_lock lock(gMutex); owner = gService; if (!owner) return;
            const auto found = owner->lists.find(cmd);
            if (found == owner->lists.end() || found->second.role != Role::Consumer) return;
            window = owner->window; following = found->second.followingRecon;
        }
        NrdBridgePerf::ConsumerFrame(StreamlineHooks::getSLConstantsSnapshot().frameIndex);
        if (!gRuntime.load(std::memory_order_relaxed) || !following) return;
        if (!window)
        {
            std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
            if (gService == owner && found != owner->lists.end())
            {
                if (found->second.converted) DropPending(*owner);
                StopFollowing(*owner,cmd,found->second);
            }
            return;
        }
        std::string error; ChainDiscovery discovered; bool published = false, invalid = false;
        ID3D12Resource* motionTag = nullptr; Resources resources; ListState staged; bool inject = false, keepWindow = false;
        FrameSurvey::BoundConstantBinding consumerConstants;
        {
        NrdBridgeLifetime::ScopedBorrow borrow;
        std::vector<FrameSurvey::BoundResource> srv, uav;
        if (!window) { Failure(owner,"Consumer has no current binding-validation window"); return; }
        if (!Tables(cmd,Role::Consumer,srv,uav)) { WaitingForBindings(owner,cmd,"Consumer compute table bindings/registers are unavailable in discovery window"); return; }
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
            const auto found = owner->lists.find(cmd); if (found == owner->lists.end()) return;
            auto& list = found->second;
            if (window)
            {
                invalid = !list.chain.Observe(Role::Consumer,srv,uav,owner->taggedMotion,error);
                RefreshChainUsers(*owner,cmd,list);
                if (!invalid)
                {
                    published = owner->cache.Publish(list.chain); discovered = list.chain; motionTag = owner->taggedMotion;
                    if (published) { DropPending(*owner); owner->status.active = false; }
                    owner->window = false; owner->attempts = 0; owner->status.phase = "Waiting for NRD";
                    owner->status.reason = "Resources validated; waiting for the next Recon";
                    owner->status.width = owner->cache.Get().width; owner->status.height = owner->cache.Get().height;
                    owner->status.resources = ResourceSummary(owner->cache.Get());
                }
            }
            inject = !invalid && owner->cache.Valid() && list.converted && list.motionReady && list.temporal && list.atrous &&
                list.generation == owner->cache.Generation() && list.resetSerial == owner->cancellationSerial;
            if (inject)
            {
                resources = owner->cache.Get(); staged = list;
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
        std::scoped_lock injection(gInjectionMutex);
        NrdBridgeLifetime::ScopedBorrow borrow;
        {
            std::scoped_lock lock(gMutex);
            if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() ||
                staged.generation != owner->cache.Generation() || staged.resetSerial != owner->cancellationSerial) return;
            const auto found = owner->lists.find(cmd);
            if (found == owner->lists.end() || found->second.frame != staged.frame ||
                found->second.recording != staged.recording || !found->second.converted || !found->second.motionReady) return;
        }
        if (!FrameSurvey::MetadataHealthy()) { Failure(owner,"Creation or binding metadata is unhealthy; restart the title/device"); return; }
        FrameSurvey::ComputeBindings currentBindings;
        if (!D3D12Hooks::GetComputeBindingsForBridge(cmd,currentBindings) ||
            !FrameSurvey::ValidateComputeConstantBinding(currentBindings,6,0,consumerConstants))
        { Failure(owner,"Consumer native b6 binding changed while awaiting injection; waiting for rediscovery"); return; }
        if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored before Consumer"); return; }
        struct CommitTicket
        {
            Service* owner;
            ID3D12GraphicsCommandList* list;
            const ListState* staged;
            const FrameSurvey::BoundConstantBinding* constants;
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
                    !ticket.owner->cache.Valid() || ticket.metadataFailed ||
                    staged.generation != ticket.owner->cache.Generation() || staged.resetSerial != ticket.owner->cancellationSerial ||
                    found == ticket.owner->lists.end() ||
                    found->second.frame != staged.frame || !found->second.converted || !found->second.motionReady ||
                    found->second.recording != staged.recording)
                { ticket.cancelled = true; return false; }
                FrameSurvey::ComputeBindings current;
                if (!D3D12Hooks::GetComputeBindingsForBridge(ticket.list,current) ||
                    !FrameSurvey::ValidateComputeConstantBinding(current,6,0,*ticket.constants))
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
                ticket.owner->status.phase = "Active"; ticket.owner->status.reason.clear();
                if (staged.debug != DebugMode::Off)
                { ++ticket.owner->resetSerial; staged.history->uncertain.store(true,std::memory_order_release); }
                ticket.log = ticket.frames == 1 || ticket.frames-ticket.owner->lastLog >= 600;
                if (ticket.log) ticket.owner->lastLog = ticket.frames;
                return true;
            }
        } ticket {owner.get(), cmd, &staged, &consumerConstants};
        const OutputCommitGuard admission {&ticket, CommitTicket::Admit};
        bool succeeded = false;
        {
            InjectionScope guard(cmd);
            if (staged.debug == DebugMode::Off)
                succeeded = staged.history->rr.Dispatch(cmd,staged.inputs,resources.outputSpec,resources.outputDiff,staged.parameters,error,admission);
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
            if (gService == owner) owner->rrSettingsState = staged.history->rr.GetSettingsState();
        }
        if (!succeeded) { Failure(owner,error.empty() ? "NRD output dispatch failed" : error); return; }
        if (ticket.log) LOG_INFO("[NRD_BRIDGE] active frames={} resets={} SL_frame={} bridge_frame={} render={}x{} debug={}",
            ticket.frames,ticket.resets,staged.parameters.streamlineFrame,staged.parameters.frameIndex,
            resources.width,resources.height,uint32_t(staged.debug));
    } catch (...) { CoordinatorException("Exception while preparing NRD output dispatch"); }
}
void OnReleased(void* object) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || !object) return;
    try
    {
        bool reopen = false;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            owner.roles.erase(reinterpret_cast<ID3D12PipelineState*>(object));
            if (const auto found = owner.lists.find(reinterpret_cast<ID3D12GraphicsCommandList*>(object)); found != owner.lists.end())
            {
                const bool unsubmitted = found->second.recording && !found->second.recording->submitted.load(std::memory_order_acquire);
                if (unsubmitted && found->second.history)
                {
                    found->second.history->uncertain.store(true,std::memory_order_release);
                    found->second.history->discardPending.store(true,std::memory_order_release);
                    owner.discardRequested = true;
                }
                if (found->second.converted || unsubmitted)
                {
                    if (owner.pendingList == reinterpret_cast<ID3D12GraphicsCommandList*>(object)) owner.pendingList = nullptr;
                    if (owner.activeFrame == found->second.frame) owner.status.active = false;
                    ++owner.resetSerial;
                }
                RemoveChainUsers(owner,found->first,found->second); StopFollowing(owner,found->first,found->second);
                owner.lists.erase(found);
            }
            bool currentReleased = false;
            // An address can be shared by a few NRD recordings. Visit those users only.
            // RemoveChainUsers may erase this map entry, so reacquire it per iteration.
            for (;;)
            {
                const auto users = owner.chainUsers.find(object);
                if (users == owner.chainUsers.end() || users->second.empty()) break;
                const auto cmd = *users->second.begin();
                // Pop before any secondary cleanup: a failed index allocation may
                // have published this pair before indexedReferences was committed.
                users->second.erase(cmd); if (users->second.empty()) owner.chainUsers.erase(users);
                const auto found = owner.lists.find(cmd);
                if (found == owner.lists.end()) continue;
                auto& list = found->second;
                if (list.chain.Released(object)) currentReleased |= list.followingRecon || list.converted;
                RemoveChainUsers(owner,cmd,list); StopFollowing(owner,cmd,list);
            }
            if (owner.taggedMotion == object) owner.taggedMotion = nullptr;
            if (owner.cache.Released(object) || currentReleased)
            { Invalidate(owner,"A discovered or current-recording title resource was released"); reopen = true; }
        }
        if (reopen && gRuntime.load(std::memory_order_relaxed))
        { PublishBindingWindow(); LOG_INFO("[NRD_BRIDGE] resource release invalidated discovery; restarting bounded window"); }
    } catch (...) {}
}
void OnTitleTag(ID3D12GraphicsCommandList*, const char* name, ID3D12Resource* resource) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || FrameSurvey::Internal() || !name) return;
    try
    {
        if (std::string_view(name) != "MotionVectors") return;
        if (!resource)
        {
            std::scoped_lock lock(gMutex); if (gService) gService->taggedMotion = nullptr;
            return;
        }
        NrdBridgeLifetime::ScopedBorrow borrow;
        const auto description = resource->GetDesc(); bool reopen = false;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            owner.taggedMotion = resource;
            if (owner.cache.Valid() && (owner.cache.Get().motion != resource ||
                owner.cache.Get().width != description.Width || owner.cache.Get().height != description.Height))
            { Invalidate(owner,"Streamline motion tag or render size changed"); reopen = true; }
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
        std::string reason;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            // FG Presents do not imply new rendered frames. Count missing Recon only when SL's frame id advances.
            if (snapshot.frameIndex != UINT32_MAX && snapshot.frameIndex != owner.lastSLFrame)
            {
                owner.lastSLFrame = snapshot.frameIndex;
                if (owner.cache.Frame(owner.observedRecon))
                { Invalidate(owner,"Recon missing for 30 consecutive Streamline frames"); change = log = true; }
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
    if (gService) return gService->status;
    Status status;
    if (StartupEnabled() && !gUnavailableReason.empty())
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
        const bool previous = gRuntime.exchange(enabled,std::memory_order_acq_rel); if (previous == enabled) return;
        bool window = false;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            DropPending(owner); owner.status.runtimeEnabled = enabled; owner.status.active = false;
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
        std::scoped_lock lock(gMutex);
        if (!gService) return;
        DropPending(*gService);
        if (gService->status.runtimeEnabled)
        { gService->status.phase = "Waiting for NRD"; gService->status.reason = "RR history reset requested; waiting for the next Recon"; }
    } catch (...) {}
}
bool ApplyRRSettings(const RRSettings& settings, bool cameraProjectedDepthDelta, std::string& error) noexcept
{
    try
    {
        if (!ValidateRRSettings(settings,error)) return false;
        std::scoped_lock injection(gInjectionMutex);
        std::shared_ptr<Service> owner; std::shared_ptr<HistoryDomain> history;
        RRSettingsState before;
        {
            std::scoped_lock lock(gMutex); owner = gService;
            if (!owner) { error = "NRD bridge is not installed on the selected title device"; return false; }
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
            const bool motionChanged = owner->cameraProjectedDepthDelta != cameraProjectedDepthDelta;
            const bool debugChanged = owner->rrSettings.nativeDebugView != settings.nativeDebugView ||
                (settings.nativeDebugView >= 0 && owner->rrSettings.nativeDebugViewport != settings.nativeDebugViewport);
            const bool rawDebugCleared = settings.nativeDebugView >= 0 && gDebug.exchange(DebugMode::Off,std::memory_order_acq_rel) != DebugMode::Off;
            owner->rrSettings = settings; owner->cameraProjectedDepthDelta = cameraProjectedDepthDelta;
            owner->rrSettingsState = after; owner->rrSettingsState.requested = settings;
            gNativeDebug.store(settings.nativeDebugView >= 0,std::memory_order_release);
            if (scalarChanged || motionChanged || debugChanged || rawDebugCleared || !configured)
            {
                DropPending(*owner);
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
bool NativeDebugEnabled() noexcept
{ return gInstalled.load(std::memory_order_relaxed) && gNativeDebug.load(std::memory_order_relaxed); }
#ifdef FSRD_NRD_BRIDGE_TEST
void RegisterPipelineRoleForTesting(ID3D12PipelineState* pipeline, Role role) noexcept
{
    try { std::scoped_lock lock(gMutex); if (gService && pipeline) gService->roles[pipeline] = role; } catch (...) {}
}
#endif
}
