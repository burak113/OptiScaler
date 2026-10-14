#include "pch.h"
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
#include <atomic>
#include <mutex>
#include <sstream>
#include <unordered_map>
#include <cctype>

namespace NrdBridge
{
namespace
{
struct RecordingToken { std::atomic<bool> submitted {false}; };
struct ListState
{
    Role role = Role::None;
    ChainDiscovery chain;
    bool followingRecon = false, converted = false, motionReady = false, temporal = false, atrous = false, nrdList = false;
    std::shared_ptr<RecordingToken> recording;
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
    DiscoveryCache cache;
    ConversionPass conversion;
    RRWrapper rr;
    Status status;
    ID3D12Resource* taggedMotion = nullptr;
    ID3D12GraphicsCommandList* pendingList = nullptr;
    uint64_t frame = 0, resetSerial = 1, appliedReset = 0, lastLog = 0;
    uint32_t windowPresents = 0, retryPresents = 0, attempts = 0, failures = 0, lastSLFrame = UINT32_MAX;
    bool window = false, windowSawRecon = false, everRecon = false, observedRecon = false, conventionsLogged = false;
};
std::mutex gMutex, gInjectionMutex;
std::shared_ptr<Service> gService;
std::atomic<bool> gInstalled {false}, gRuntime {false};
std::atomic<DebugMode> gDebug {DebugMode::Off};
#ifdef FSRD_NRD_BRIDGE_TEST
void (*gBeforeConversionLockForTesting)() = nullptr;
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
void SeedForWindow(ID3D12GraphicsCommandList* cmd)
{
    NrdBridgeLifetime::ScopedBorrow borrow;
    FrameSurvey::ComputeBindings bindings;
    if (D3D12Hooks::GetComputeBindingsForBridge(cmd,bindings)) FrameSurvey::SeedComputeBindings(cmd,bindings);
}
Role PipelineRole(const Service& owner, ID3D12PipelineState* pipeline)
{
    const auto found = owner.roles.find(pipeline); return found == owner.roles.end() ? Role::None : found->second;
}
void DropPending(Service& owner)
{
    owner.pendingList = nullptr;
    for (auto& [cmd,list] : owner.lists) list.converted = list.motionReady = false;
    ++owner.resetSerial;
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
        owner->status.active = false; owner->status.phase = "Inactive"; owner->status.reason = reason;
        owner->status.resources.clear(); owner->status.width = owner->status.height = 0;
        ++owner->failures;
        if (owner->failures >= 3) owner->status.reason = "Failed after 3 bridge attempts: " + reason;
    }
    FrameSurvey::SetBindingWindow(false);
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
        if (const auto found = owner->lists.find(cmd); found != owner->lists.end()) found->second.followingRecon = false;
        log = owner->status.reason != reason;
        owner->status.active = false; owner->status.phase = "Discovering"; owner->status.reason = reason;
        owner->status.resources.clear(); owner->status.width = owner->status.height = 0;
    }
    if (log) LOG_INFO("[NRD_BRIDGE] {}; waiting for a complete command-list Reset inside the bounded window",reason);
}
bool CompleteOffsets(std::span<const FrameSurvey::BoundResource> table, D3D12_DESCRIPTOR_RANGE_TYPE kind,
                     std::initializer_list<uint32_t> offsets)
{
    for (const auto offset : offsets)
        if (std::none_of(table.begin(),table.end(),[&](const auto& view) {
            return view.kind == kind && view.descriptorOffset == offset && view.resource;
        })) return false;
    return true;
}
bool Tables(ID3D12GraphicsCommandList* cmd, Role role, std::vector<FrameSurvey::BoundResource>& srv,
            std::vector<FrameSurvey::BoundResource>& uav)
{
    if (role == Role::Recon)
        return FrameSurvey::ResolveComputeTable(cmd,1,srv) && FrameSurvey::ResolveComputeTable(cmd,5,uav) &&
            CompleteOffsets(srv,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,{0,1,2,3}) && CompleteOffsets(uav,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,{0,1});
    if (role == Role::Temporal) return FrameSurvey::ResolveComputeTable(cmd,1,srv) && CompleteOffsets(srv,D3D12_DESCRIPTOR_RANGE_TYPE_SRV,{2});
    if (role == Role::ATrous || role == Role::Consumer)
        return FrameSurvey::ResolveComputeTable(cmd,5,uav) && CompleteOffsets(uav,D3D12_DESCRIPTOR_RANGE_TYPE_UAV,{0,1});
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
    Resources resources; uint64_t generation = 0, serial = 0; bool reset = false;
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() ||
            found == owner->lists.end() || found->second.frame != frame) return;
        resources = owner->cache.Get(); generation = owner->cache.Generation(); serial = owner->resetSerial;
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
            owner->cache.Generation() != generation || owner->resetSerial != serial || found == owner->lists.end() ||
            found->second.frame != frame) return;
    }
    if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored after Recon"); return; }
    std::string error, conventions; FrameParameters parameters; ConvertedResources converted;
    bool succeeded = false; auto recording = std::make_shared<RecordingToken>();
    {
        InjectionScope guard(cmd);
        if (reset) { owner->conversion.ResetHistory(); owner->rr.ResetHistory(); }
        const auto snapshot = StreamlineHooks::getSLConstantsSnapshot();
        succeeded = owner->rr.PrepareFrame(snapshot,reset,parameters,error);
        if (succeeded && parameters.reset) owner->conversion.ResetHistory();
        if (succeeded) succeeded = owner->conversion.Initialize(owner->device.Get(),resources.width,resources.height,error);
        if (succeeded) succeeded = ResTrack_Dx12::RetainComputeDispatch(owner->device.Get(),cmd,recording,
            [recording](ID3D12CommandQueue*) { recording->submitted.store(true,std::memory_order_release); });
        if (!succeeded && error.empty()) error = "Could not retain NRD recording submission token";
        if (succeeded)
        {
            const ConversionInputs inputs {resources.reconSpec,resources.reconDiff,resources.normals,resources.viewDepth,nullptr};
            succeeded = owner->conversion.Dispatch(cmd,inputs,parameters,converted,error);
        }
        if (succeeded) conventions = Conventions(owner->rr);
    }
    if (!succeeded) { Failure(owner,error.empty() ? "NRD input conversion failed" : error); return; }
    bool logConventions = false;
    {
        std::scoped_lock lock(gMutex);
        const auto found = owner->lists.find(cmd);
        if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() ||
            owner->cache.Generation() != generation || owner->resetSerial != serial || found == owner->lists.end() ||
            found->second.frame != frame) { DropPending(*owner); return; }
        auto& list = found->second;
        list.converted = true; list.motionReady = false; list.recording = recording; list.generation = generation; list.resetSerial = serial;
        list.parameters = parameters; list.inputs = converted; list.debug = gDebug.load(std::memory_order_relaxed);
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
            list.resetSerial != owner->resetSerial || owner->cache.Get().motion != currentMotion) return;
        staged = list;
    }
    if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored after first Temporal"); return; }
    std::string error; bool succeeded = false;
    {
        InjectionScope guard(cmd);
        succeeded = DispatchCurrentMotion(owner->conversion,cmd,staged.inputs,currentMotion,staged.parameters,error);
    }
    if (!succeeded) { Failure(owner,error.empty() ? "NRD current motion conversion failed" : error); return; }
    {
        std::scoped_lock lock(gMutex); const auto found = owner->lists.find(cmd);
        if (gService != owner || !owner->cache.Valid() || found == owner->lists.end()) return;
        auto& list = found->second;
        if (list.frame == frame && list.generation == owner->cache.Generation() && list.resetSerial == owner->resetSerial && list.converted)
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
bool StartupEnabled() noexcept
{
    return Config::Instance()->FfxDenoiserNrdBridge.value_or_default() && SupportedExecutable();
}
bool Initialize(ID3D12Device* device) noexcept
{
    if (!device || !StartupEnabled()) return false;
    try
    {
        std::shared_ptr<Service> previous;
        {
            std::scoped_lock injection(gInjectionMutex);
            std::scoped_lock lock(gMutex);
            if (gService && gService->device.Get() == device) return true;
            auto owner = std::shared_ptr<Service>(new Service,[](Service* service) { FrameSurvey::ScopedInternal internal; delete service; }); owner->device = device;
            owner->status.installed = true; owner->status.runtimeEnabled = Config::Instance()->FfxDenoiserNrdBridgeEnabled.value_or_default();
            owner->status.phase = owner->status.runtimeEnabled ? "Discovering" : "Waiting for NRD";
            owner->status.reason = owner->status.runtimeEnabled ? "Waiting for the Recon to Consumer chain" : "Runtime toggle is off";
            owner->window = owner->status.runtimeEnabled;
            previous = std::move(gService); gService = std::move(owner);
            gRuntime.store(gService->status.runtimeEnabled,std::memory_order_release); gInstalled.store(true,std::memory_order_release);
        }
        // Destruction may release owned D3D12 objects and re-enter release observers. Never hold gMutex here.
        { FrameSurvey::ScopedInternal internal; previous.reset(); }
        FrameSurvey::SetPipelineObserver(OnPipelineCreated); FrameSurvey::SetReleaseObserver(OnReleased);
        FrameSurvey::SetBindingWindow(gRuntime.load(std::memory_order_relaxed));
        LOG_INFO("[NRD_BRIDGE] startup enabled for Cyberpunk; runtime={}; discovery windows bounded to 8 Presents / 3 attempts; empty loading windows do not consume attempts",
            gRuntime.load(std::memory_order_relaxed));
        return true;
    } catch (...) { CoordinatorException("NRD bridge initialization failed"); return false; }
}
void Shutdown() noexcept
{
    gInstalled.store(false,std::memory_order_release); gRuntime.store(false,std::memory_order_release);
    FrameSurvey::SetPipelineObserver(nullptr); FrameSurvey::SetReleaseObserver(nullptr); FrameSurvey::SetBindingWindow(false);
    try
    {
        std::scoped_lock injection(gInjectionMutex);
        std::shared_ptr<Service> previous;
        { std::scoped_lock lock(gMutex); previous = std::move(gService); }
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
        if (open) FrameSurvey::SetBindingWindow(true);
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
            const auto found = owner.lists.find(cmd);
            if (found != owner.lists.end())
            {
                const bool nrdList = found->second.nrdList;
                if (found->second.converted || owner.pendingList == cmd ||
                    (found->second.recording && !found->second.recording->submitted.load(std::memory_order_acquire))) DropPending(owner);
                found->second = {}; found->second.nrdList = nrdList; found->second.role = PipelineRole(owner,initial);
                if (nrdList && gRuntime.load(std::memory_order_relaxed) && !owner.window && owner.attempts < 3 && owner.failures < 3 &&
                    (owner.cache.Valid() || owner.retryPresents >= 60 || !owner.everRecon))
                { StartWindow(owner); open = true; }
            }
            else if (const auto role = PipelineRole(owner,initial); role != Role::None) owner.lists[cmd].role = role;
        }
        if (open) FrameSurvey::SetBindingWindow(true);
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
            bool window = false;
            {
                std::scoped_lock lock(gMutex); owner = gService; if (!owner) return;
                const auto found = owner->lists.find(cmd); if (found == owner->lists.end()) return;
                role = found->second.role; window = owner->window;
                if (!window) { found->second.followingRecon = false; return; } // Intentional retry cooldown records no owned work.
                if (role == Role::Recon)
                {
                    if (owner->pendingList) DropPending(*owner);
                    auto& list = found->second; list = {}; list.role = role; list.followingRecon = list.nrdList = true;
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
            if (!window) { Failure(owner,"Current NRD bindings have no frame-local validation window"); return; }
            std::vector<FrameSurvey::BoundResource> srv, uav;
            if (!Tables(cmd,role,srv,uav)) { WaitingForBindings(owner,cmd,"Current NRD table metadata is incomplete"); return; }
            {
                std::scoped_lock lock(gMutex); if (gService != owner) return;
                const auto found = owner->lists.find(cmd); if (found == owner->lists.end() || found->second.frame != frame) return;
                auto& list = found->second;
                if (role == Role::Recon) invalid = !list.chain.Begin(srv,uav,error);
                else invalid = !list.chain.Observe(role,srv,uav,owner->taggedMotion,error);
                if (role == Role::Temporal) list.temporal = true;
                if (role == Role::ATrous && list.temporal) list.atrous = true;
                if (!invalid && role == Role::Recon && owner->cache.Valid())
                {
                    const auto& a = list.chain.Get(); const auto& b = owner->cache.Get();
                    if (a.width != b.width || a.height != b.height || a.inputSpec != b.inputSpec || a.inputDiff != b.inputDiff ||
                        a.reconSpec != b.reconSpec || a.reconDiff != b.reconDiff || a.normals != b.normals || a.viewDepth != b.viewDepth)
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
    if (!gInstalled.load(std::memory_order_relaxed) || !gRuntime.load(std::memory_order_relaxed) || FrameSurvey::Internal()) return;
    try
    {
        std::shared_ptr<Service> owner; bool window = false;
        {
            std::scoped_lock lock(gMutex); owner = gService; if (!owner) return;
            const auto found = owner->lists.find(cmd);
            if (found == owner->lists.end() || found->second.role != Role::Consumer || !found->second.followingRecon) return;
            window = owner->window;
            if (!window)
            {
                if (found->second.converted) DropPending(*owner);
                found->second.followingRecon = false; return;
            }
        }
        std::string error; ChainDiscovery discovered; bool published = false, invalid = false;
        ID3D12Resource* motionTag = nullptr; Resources resources; ListState staged; bool inject = false;
        {
        NrdBridgeLifetime::ScopedBorrow borrow;
        std::vector<FrameSurvey::BoundResource> srv, uav;
        if (!window) { Failure(owner,"Consumer has no current binding-validation window"); return; }
        if (!Tables(cmd,Role::Consumer,srv,uav)) { WaitingForBindings(owner,cmd,"Consumer compute table bindings are unavailable in discovery window"); return; }
        {
            std::scoped_lock lock(gMutex); if (gService != owner) return;
            const auto found = owner->lists.find(cmd); if (found == owner->lists.end()) return;
            auto& list = found->second;
            if (window)
            {
                invalid = !list.chain.Observe(Role::Consumer,srv,uav,owner->taggedMotion,error);
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
                list.generation == owner->cache.Generation() && list.resetSerial == owner->resetSerial;
            if (inject) { resources = owner->cache.Get(); staged = list; }
            list.followingRecon = false;
        }
        } // Release physical-resource borrow before waiting for native injection serialization.
        if (invalid) { Failure(owner,error); return; }
        if (window) FrameSurvey::SetBindingWindow(false);
        if (published) LogDiscovery(discovered,motionTag);
        if (!inject) return;
        std::scoped_lock injection(gInjectionMutex);
        NrdBridgeLifetime::ScopedBorrow borrow;
        {
            std::scoped_lock lock(gMutex);
            if (gService != owner || !gRuntime.load(std::memory_order_relaxed) || !owner->cache.Valid() ||
                staged.generation != owner->cache.Generation() || staged.resetSerial != owner->resetSerial || owner->pendingList != cmd) return;
        }
        if (!D3D12Hooks::CanRestoreRootSignature(cmd)) { Failure(owner,"Title compute state cannot be restored before Consumer"); return; }
        bool succeeded = false;
        {
            InjectionScope guard(cmd);
            if (staged.debug == DebugMode::Off)
                succeeded = owner->rr.Dispatch(cmd,staged.inputs,resources.outputSpec,resources.outputDiff,staged.parameters,error);
            else succeeded = owner->conversion.WriteDebug(cmd,staged.inputs,resources.outputSpec,resources.outputDiff,staged.debug,error);
        }
        if (!succeeded) { Failure(owner,error.empty() ? "NRD output dispatch failed" : error); return; }
        bool log = false; Status status;
        {
            std::scoped_lock lock(gMutex); if (gService != owner) return;
            const auto found = owner->lists.find(cmd); if (found != owner->lists.end()) found->second.converted = false;
            owner->pendingList = nullptr; owner->failures = 0; ++owner->status.framesBridged;
            if (staged.parameters.reset) ++owner->status.resets;
            owner->status.active = true; owner->status.phase = "Active"; owner->status.reason.clear();
            if (staged.debug != DebugMode::Off) ++owner->resetSerial; // Debug frames never seed RR temporal history.
            log = owner->status.framesBridged == 1 || owner->status.framesBridged-owner->lastLog >= 600;
            if (log) { owner->lastLog = owner->status.framesBridged; status = owner->status; }
        }
        if (log) LOG_INFO("[NRD_BRIDGE] active frames={} resets={} SL_frame={} bridge_frame={} render={}x{} debug={}",
            status.framesBridged,status.resets,staged.parameters.streamlineFrame,staged.parameters.frameIndex,
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
            { if (found->second.converted || (found->second.recording && !found->second.recording->submitted.load(std::memory_order_acquire))) DropPending(owner); owner.lists.erase(found); }
            for (auto& [cmd,list] : owner.lists) if (list.chain.Released(object)) list.followingRecon = false;
            if (owner.taggedMotion == object) owner.taggedMotion = nullptr;
            if (owner.cache.Released(object)) { Invalidate(owner,"A discovered title resource was released"); reopen = true; }
        }
        if (reopen && gRuntime.load(std::memory_order_relaxed))
        { FrameSurvey::SetBindingWindow(true); LOG_INFO("[NRD_BRIDGE] resource release invalidated discovery; restarting bounded window"); }
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
        if (reopen && gRuntime.load(std::memory_order_relaxed)) FrameSurvey::SetBindingWindow(true);
    } catch (...) {}
}
void OnPresent() noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed) || !gRuntime.load(std::memory_order_relaxed)) return;
    try
    {
        const auto snapshot = StreamlineHooks::getSLConstantsSnapshot(); bool change = false, desired = false, log = false;
        std::string reason;
        {
            std::scoped_lock lock(gMutex); if (!gService) return; auto& owner = *gService;
            // FG Presents do not imply new rendered frames. Count missing Recon only when SL's frame id advances.
            if (snapshot.frameIndex != UINT32_MAX && snapshot.frameIndex != owner.lastSLFrame)
            {
                owner.lastSLFrame = snapshot.frameIndex;
                if (owner.cache.Frame(owner.observedRecon))
                { Invalidate(owner,"Recon missing for 30 consecutive Streamline frames"); change = desired = log = true; }
                owner.observedRecon = false;
            }
            if (owner.window && ++owner.windowPresents >= 8)
            {
                owner.window = false; owner.retryPresents = 0; change = true; desired = false; owner.status.active = false;
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
                { StartWindow(owner); change = desired = true; }
            }
            if (reason.empty()) reason = owner.status.reason;
        }
        if (change) FrameSurvey::SetBindingWindow(desired);
        if (log) LOG_INFO("[NRD_BRIDGE] {}",reason);
    } catch (...) {}
}
Status GetStatus()
{
    std::scoped_lock lock(gMutex); return gService ? gService->status : Status {};
}
void SetRuntimeEnabled(bool enabled) noexcept
{
    if (!gInstalled.load(std::memory_order_relaxed)) return;
    try
    {
        std::scoped_lock injection(gInjectionMutex);
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
        FrameSurvey::SetBindingWindow(window);
        LOG_INFO("[NRD_BRIDGE] runtime={} (RR and depth history will reset at next Recon)",enabled);
    } catch (...) {}
}
bool RuntimeEnabled() noexcept { return gRuntime.load(std::memory_order_relaxed); }
void SetDebugMode(DebugMode mode) noexcept
{
    if (mode != DebugMode::Off && mode != DebugMode::RawSignals && mode != DebugMode::RRInputs) return;
    if (gDebug.exchange(mode,std::memory_order_acq_rel) != mode) RequestHistoryReset();
}
DebugMode GetDebugMode() noexcept { return gDebug.load(std::memory_order_relaxed); }
void RequestHistoryReset() noexcept
{
    try { std::scoped_lock lock(gMutex); if (gService) DropPending(*gService); } catch (...) {}
}
#ifdef FSRD_NRD_BRIDGE_TEST
void RegisterPipelineRoleForTesting(ID3D12PipelineState* pipeline, Role role) noexcept
{
    try { std::scoped_lock lock(gMutex); if (gService && pipeline) gService->roles[pipeline] = role; } catch (...) {}
}
#endif
}
