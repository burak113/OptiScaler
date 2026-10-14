#pragma once

#include <d3d12.h>
#include <dxgi.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <functional>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>
#include "NrdBridgePerf_Dx12.h"

// Leases are opaque owners: helper-shader state and, for recorded-lifetime features, the
// FFX provider contexts (FfxContextOwner) whose dispatches the list recorded.
// COM calls and destruction of retained objects always occur outside the registry lock.
namespace RecordedComputeLease
{
using Microsoft::WRL::ComPtr;
struct Submission;
inline void AfterSubmission(const std::shared_ptr<Submission>& s) noexcept;
struct FencePoint
{
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12Fence> fence;
    uint64_t value = 1;
    bool IsPublished() const noexcept { return published_; }
  private:
    bool published_ = false;
    friend void AfterSubmission(const std::shared_ptr<Submission>&) noexcept;
};
using FencePointPtr = std::shared_ptr<const FencePoint>;
struct SubmissionInfo
{
    ID3D12CommandQueue* queue = nullptr; // borrowed during the callback; never dereference a recording identity
    uint64_t submissionId = 0, recordingId = 0, recordingSubmission = 0;
    bool snapshotFallback = false;
};
struct SubmissionDecision
{
    bool allowed = true;
    HRESULT orderingFailure = S_OK;
};
inline thread_local SubmissionDecision* gSubmissionDecision = nullptr;
struct DecisionScope
{
    SubmissionDecision* previous;
    explicit DecisionScope(SubmissionDecision& current) noexcept : previous(gSubmissionDecision)
    { gSubmissionDecision = &current; }
    ~DecisionScope() { gSubmissionDecision = previous; }
};
enum class SubmissionFailure { Snapshot, Prepare, FenceCreate, Signal, Publish, Ordering };
struct SubmissionCallbacks
{
    // Necessary ordering must run even during a failed snapshot. Keep that work
    // allocation-free. False rejects private preparation; unrepaired required
    // ordering must also call DenySubmission, which denies the original Execute.
    std::function<bool(const SubmissionInfo&)> beforeSubmit;
    std::function<void(const SubmissionInfo&, const FencePointPtr&)> fencePublished;
    std::function<void(const SubmissionInfo&, SubmissionFailure)> failed;
    bool Empty() const noexcept { return !beforeSubmit && !fencePublished && !failed; }
};
// Resolve one strong canonical identity on the stack. This avoids allocating a
// list of identities before the allocation-failure ordering fallback can run.
struct IdentityRange
{
    const void* context = nullptr;
    size_t count = 0;
    HRESULT (*identityAt)(const void*, size_t, IUnknown**) = nullptr;
    void* (*aliasAt)(const void*, size_t) = nullptr;
    IdentityRange(const void* sources, size_t size,
                  HRESULT (*resolve)(const void*, size_t, IUnknown**), void* (*alias)(const void*, size_t)) noexcept
        : context(sources), count(size), identityAt(resolve), aliasAt(alias) {}
};
struct Recording
{
    IUnknown* identity = nullptr; // weak canonical identity; owning it prevents final Release
    std::vector<void*> aliases;
    std::vector<std::shared_ptr<void>> leases;
    // Optional gated work can learn the ACTUAL queue immediately before Execute.
    // Every gate starts denied and owns its private upload storage through a lease.
    std::vector<std::function<void(ID3D12CommandQueue*)>> prepareSubmission;
    std::vector<SubmissionCallbacks> callbacks;
    uint64_t id = 0, submissionCount = 0;
    size_t releasesInFlight = 0;
};
struct Submission
{
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12Fence> fence; // distinct fence per submission; no cross-thread value ordering
    std::vector<std::shared_ptr<void>> leases;
    std::vector<std::function<void(ID3D12CommandQueue*)>> prepareSubmission;
    struct Callback { SubmissionInfo info; SubmissionCallbacks callbacks; };
    struct Occurrence { std::shared_ptr<Recording> recording; size_t first = 0, count = 0; };
    std::vector<Callback> callbacks;
    std::vector<Occurrence> occurrences;
    std::shared_ptr<FencePoint> point; // contains no leases/callbacks/domain references: no ownership cycle
    SubmissionDecision decision;
    bool preparationFailed = false, failureNotified = false;
    bool signalPublished = false;
    // Registry-mutex-only membership. Nodes stay stable while vector owners move.
    static constexpr size_t Unregistered = size_t(-1);
    size_t registrySlot = Unregistered;
    Submission* pollPrevious = nullptr;
    Submission* pollNext = nullptr;
    bool pollQueued = false;
};
struct Registry
{
    NrdBridgePerf::TimedMutex<std::mutex,NrdBridgePerf::WaitKind::Tracking> mutex;
    bool listHooks = false, queueHook = false, completionFailed = false;
    std::unordered_map<IUnknown*, std::shared_ptr<Recording>> recordings;
    std::unordered_map<void*, std::weak_ptr<Recording>> aliases;
    std::vector<std::shared_ptr<Submission>> submissions;
    // Only successfully signalled submissions enter this non-owning round-robin.
    // Unpublished/uncertain intents remain owned by submissions indefinitely.
    Submission* pollHead = nullptr;
    Submission* pollTail = nullptr;
    size_t publishedCount = 0;
    uint64_t nextRecording = 1, nextSubmission = 1;
};
inline Registry& GetRegistry()
{
    // Unsubmitted/unknown work cannot safely be destroyed during DLL/static teardown.
    static auto* registry = new Registry;
    return *registry;
}
inline void FailCompletion() noexcept
{
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    r.completionFailed = true;
}
inline void DenySubmission(HRESULT reason = E_FAIL) noexcept
{
    if (gSubmissionDecision)
    {
        if (gSubmissionDecision->allowed) gSubmissionDecision->orderingFailure = FAILED(reason) ? reason : E_FAIL;
        gSubmissionDecision->allowed = false;
    }
    FailCompletion();
}
inline void SetHooksAvailable(bool listHooks, bool queueHook) noexcept
{
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    if ((!listHooks || !queueHook) && (!r.recordings.empty() || !r.submissions.empty()))
        r.completionFailed = true;
    r.listHooks = listHooks;
    r.queueHook = queueHook;
}
inline bool Available() noexcept
{
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    return r.listHooks && r.queueHook && !r.completionFailed;
}
// The selector must first resolve/pin native and canonical identities outside
// every registry lock. Unknown/failing identity cannot prove a safe bypass.
inline bool HasSubmissionParticipant(IUnknown* canonical, void* alias) noexcept
{
    if (!canonical) return true;
    try
    {
        auto& r = GetRegistry();
        std::lock_guard lock(r.mutex);
        if (r.completionFailed || r.recordings.contains(canonical)) return true;
        const auto found = r.aliases.find(alias);
        // A live weak alias is conservatively retained, including Release gaps
        // and a partially prepared recording. No strong owner dies under lock.
        return found != r.aliases.end() && !found->second.expired();
    }
    catch (...) { return true; }
}
inline constexpr size_t PollBudget = 64;
namespace Detail
{
// Caller holds Registry::mutex; these operations touch POD and move existing
// shared owners only. No allocation, native call or last-owner destruction.
inline bool RegisteredLocked(const Registry& r, const Submission& s) noexcept
{
    return s.registrySlot < r.submissions.size() && r.submissions[s.registrySlot].get() == &s;
}
inline bool PublishLocked(Registry& r, Submission& s) noexcept
{
    if (!RegisteredLocked(r,s) || s.pollQueued || s.signalPublished) return false;
    s.pollPrevious = r.pollTail;
    s.pollNext = nullptr;
    if (r.pollTail) r.pollTail->pollNext = &s;
    else r.pollHead = &s;
    r.pollTail = &s;
    s.pollQueued = s.signalPublished = true;
    ++r.publishedCount;
    return true;
}
inline void RotateHeadLocked(Registry& r) noexcept
{
    auto* first = r.pollHead;
    if (first == r.pollTail) return;
    r.pollHead = first->pollNext;
    r.pollHead->pollPrevious = nullptr;
    first->pollPrevious = r.pollTail;
    first->pollNext = nullptr;
    r.pollTail->pollNext = first;
    r.pollTail = first;
}
inline bool RetireLocked(Registry& r, const std::shared_ptr<Submission>& s,
                         std::shared_ptr<Submission>& detached) noexcept
{
    // A concurrent Poll may already have retired this same strong snapshot.
    if (!RegisteredLocked(r,*s)) return false;
    if (!s->pollQueued || !s->signalPublished || detached)
    { r.completionFailed = true; return false; }
    if (s->pollPrevious) s->pollPrevious->pollNext = s->pollNext;
    else r.pollHead = s->pollNext;
    if (s->pollNext) s->pollNext->pollPrevious = s->pollPrevious;
    else r.pollTail = s->pollPrevious;
    s->pollPrevious = s->pollNext = nullptr;
    s->pollQueued = false;
    --r.publishedCount;
    const auto slot = s->registrySlot;
    s->registrySlot = Submission::Unregistered;
    // Empty the removed slot before overwriting it; pop only a null owner.
    detached = std::move(r.submissions[slot]);
    if (slot != r.submissions.size()-1)
    {
        r.submissions[slot] = std::move(r.submissions.back());
        r.submissions[slot]->registrySlot = slot;
    }
    r.submissions.pop_back();
    return true;
}
}
inline void Poll() noexcept
{
    try
    {
        auto& r = GetRegistry();
        std::array<std::shared_ptr<Submission>,PollBudget> candidates {}, detached {};
        std::array<bool,PollBudget> completed {};
        size_t count = 0;
        {
            std::lock_guard lock(r.mutex);
            const auto budget = std::min(PollBudget,r.publishedCount);
            while (count < budget)
            {
                auto* first = r.pollHead;
                if (!first || !Detail::RegisteredLocked(r,*first) || !first->pollQueued || !first->signalPublished)
                { r.completionFailed = true; break; }
                candidates[count++] = r.submissions[first->registrySlot];
                Detail::RotateHeadLocked(r);
            }
        }
        bool anyCompleted = false;
        for (size_t i=0;i<count;++i)
        {
            // Signal publication pins a complete fence before entering the queue.
            if (!candidates[i]->fence) { FailCompletion(); continue; }
            // UINT64_MAX means removed device: it can no longer consume this submission.
            completed[i] = candidates[i]->fence->GetCompletedValue() >= 1;
            anyCompleted |= completed[i];
        }
        if (anyCompleted)
        {
            std::lock_guard lock(r.mutex);
            for (size_t i=0;i<count;++i)
                if (completed[i]) Detail::RetireLocked(r,candidates[i],detached[i]);
        }
        // Every candidate/detached owner dies after the mutex is released. FIFO
        // rotation and tail insertion give finite-backlog progress despite swaps.
    }
    catch (...) { FailCompletion(); }
}
#if defined(FSRD_RECORDED_COMPUTE_LEASE_TEST)
// Fixture-only teardown. Call after all native work/publishers have drained.
// Swapping the public ownership vector alone would strand non-owning queue links.
inline void ResetRegistryForTesting(bool listHooks = true, bool queueHook = true)
{
    auto& r = GetRegistry();
    decltype(r.recordings) recordings;
    decltype(r.aliases) aliases;
    decltype(r.submissions) submissions;
    {
        std::lock_guard lock(r.mutex);
        for (const auto& s : r.submissions)
        {
            s->registrySlot = Submission::Unregistered;
            s->pollPrevious = s->pollNext = nullptr;
            s->pollQueued = false;
        }
        r.pollHead = r.pollTail = nullptr;
        r.publishedCount = 0;
        recordings.swap(r.recordings); aliases.swap(r.aliases); submissions.swap(r.submissions);
        r.completionFailed = false; r.listHooks = listHooks; r.queueHook = queueHook;
    }
    // Old recordings, callbacks, leases, native fences and queues die outside.
}
#endif
inline bool Track(IUnknown* identity, const std::vector<void*>& aliases,
                  const std::shared_ptr<void>& lease,
                  std::function<void(ID3D12CommandQueue*)> prepareSubmission = {},
                  SubmissionCallbacks callbacks = {})
{
    if (!identity || !lease) return false;
    Poll();
    auto fresh = std::make_shared<Recording>();
    fresh->identity = identity;
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    if (!r.listHooks || !r.queueHook || r.completionFailed) return false;
    auto existing = r.recordings.find(identity);
    if (existing != r.recordings.end() && existing->second->releasesInFlight) return false;
    for (void* alias : aliases)
    {
        auto a = r.aliases.find(alias);
        if (a != r.aliases.end())
            if (auto rec = a->second.lock(); rec && rec->releasesInFlight) return false;
    }
    auto& rec = r.recordings.try_emplace(identity, std::move(fresh)).first->second;
    if (!rec->id) rec->id = r.nextRecording++;
    for (void* alias : aliases)
    {
        if (!alias) continue;
        if (std::find(rec->aliases.begin(), rec->aliases.end(), alias) == rec->aliases.end())
            rec->aliases.push_back(alias);
        r.aliases[alias] = rec;
    }
    rec->leases.push_back(lease);
    if (prepareSubmission) rec->prepareSubmission.push_back(std::move(prepareSubmission));
    if (!callbacks.Empty()) rec->callbacks.push_back(std::move(callbacks));
    return true;
}
// Capture BEFORE real Reset/Release. The generation token prevents post-call address ABA.
inline std::shared_ptr<Recording> Capture(void* alias) noexcept
{
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    auto it = r.aliases.find(alias);
    return it == r.aliases.end() ? nullptr : it->second.lock();
}
inline void Detach(const std::shared_ptr<Recording>& rec) noexcept
{
    if (!rec) return;
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    // On uncertainty retain recordings too; this also covers a failed PRE snapshot allocation.
    if (r.completionFailed) return;
    auto it = r.recordings.find(rec->identity);
    if (it == r.recordings.end() || it->second != rec) return;
    for (void* alias : rec->aliases)
    {
        auto a = r.aliases.find(alias);
        if (a != r.aliases.end() && a->second.lock() == rec) r.aliases.erase(a);
    }
    r.recordings.erase(it); // caller's strong rec keeps lease destructors out of this lock
}
// Block address reuse admission over the real Release/post-hook gap without
// keeping a registry lock across COM. The token still owns the old generation.
inline std::shared_ptr<Recording> BeginRelease(void* alias) noexcept
{
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    auto it = r.aliases.find(alias);
    auto rec = it == r.aliases.end() ? nullptr : it->second.lock();
    if (rec) ++rec->releasesInFlight;
    return rec;
}
inline void EndRelease(const std::shared_ptr<Recording>& rec, bool finalRelease) noexcept
{
    if (!rec) return;
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    if (rec->releasesInFlight) --rec->releasesInFlight;
    auto it = r.recordings.find(rec->identity);
    if (!finalRelease || r.completionFailed || it == r.recordings.end() || it->second != rec) return;
    for (void* alias : rec->aliases)
    {
        auto a = r.aliases.find(alias);
        if (a != r.aliases.end() && a->second.lock() == rec) r.aliases.erase(a);
    }
    r.recordings.erase(it); // caller keeps destruction outside the lock
}
inline void NotifyFailure(const std::shared_ptr<Submission>& s, SubmissionFailure reason) noexcept
{
    if (!s || s->failureNotified) return;
    s->failureNotified = true;
    for (const auto& callback : s->callbacks)
        if (callback.callbacks.failed)
            try { callback.callbacks.failed(callback.info, reason); } catch (...) {}
}
inline HRESULT WaitForFence(ID3D12CommandQueue* queue, const FencePointPtr& predecessor) noexcept
{
    if (!predecessor) return S_OK;
    if (!queue || !predecessor->IsPublished() || !predecessor->queue || !predecessor->fence || !predecessor->value)
    { DenySubmission(E_INVALIDARG); return E_INVALIDARG; }
    if (queue == predecessor->queue.Get()) return S_OK;
    HRESULT result = E_FAIL;
    constexpr uint32_t maxAttempts = 3;
    for (uint32_t attempt = 0; attempt < maxAttempts; ++attempt)
    {
        result = queue->Wait(predecessor->fence.Get(), predecessor->value);
        if (SUCCEEDED(result)) return result;
        const auto completed = predecessor->fence->GetCompletedValue();
        if (completed == UINT64_MAX) { result = DXGI_ERROR_DEVICE_REMOVED; break; }
        if (completed >= predecessor->value) return S_OK; // actual completion proves the edge unnecessary
        if (result == E_INVALIDARG || result == DXGI_ERROR_DEVICE_REMOVED || result == DXGI_ERROR_DEVICE_RESET) break;
    }
    // Do not CPU-wait: the producer may need a gate signalled by this same
    // submitting thread after Execute returns. Persistent failure cannot order
    // already recorded shared commands, so the caller must deny their Execute.
    DenySubmission(result);
    return result;
}
inline std::shared_ptr<Recording> FindRecording(IUnknown* identity, void* alias)
{
    auto& r = GetRegistry();
    std::lock_guard lock(r.mutex);
    if (identity)
        if (const auto it = r.recordings.find(identity); it != r.recordings.end()) return it->second;
    if (alias)
        if (const auto it = r.aliases.find(alias); it != r.aliases.end()) return it->second.lock();
    return {};
}
inline std::shared_ptr<Recording> ResolveRecording(const IdentityRange& identities, size_t index, bool* unknownFailure = nullptr)
{
    ComPtr<IUnknown> identity;
    const auto result = identities.identityAt ? identities.identityAt(identities.context, index, identity.GetAddressOf()) : E_POINTER;
    const auto alias = identities.aliasAt ? identities.aliasAt(identities.context, index) : nullptr;
    auto recording = FindRecording(SUCCEEDED(result) ? identity.Get() : nullptr, alias);
    if (FAILED(result))
    {
        FailCompletion();
        // An exact known alias still identifies its necessary ordering callback.
        // Catastrophic QI failure with no known alias cannot establish ordering.
        if (!recording && unknownFailure) *unknownFailure = true;
    }
    return recording;
}
inline void OrderingFallback(ID3D12CommandQueue* queue, const IdentityRange& identities, uint64_t submissionId) noexcept
{
    // Failure is latched first. Track now refuses mutations and Reset/Release
    // keep every Recording, so its callback vectors are immutable and pinned.
    FailCompletion();
    for (size_t i = 0; i < identities.count; ++i)
    {
        try
        {
            auto recording = ResolveRecording(identities, i); // one strong owner, no callback/vector copies
            if (!recording) continue;
            SubmissionInfo info {queue, submissionId, recording->id, 0, true};
            { auto& r = GetRegistry(); std::lock_guard lock(r.mutex); info.recordingSubmission = ++recording->submissionCount; }
            for (const auto& prepare : recording->prepareSubmission)
                try { prepare(queue); } catch (...) {}
            for (const auto& callback : recording->callbacks)
                if (callback.beforeSubmit) try { callback.beforeSubmit(info); } catch (...) {}
            for (const auto& callback : recording->callbacks)
                if (callback.failed) try { callback.failed(info,
                    gSubmissionDecision && !gSubmissionDecision->allowed ? SubmissionFailure::Ordering : SubmissionFailure::Snapshot); } catch (...) {}
        }
        catch (...) { /* Unknown identity stays pinned; do not invent an unrelated queue dependency. */ }
    }
}
inline std::shared_ptr<Submission> BeforeSubmission(ID3D12CommandQueue* queue, const IdentityRange& identities,
                                                   SubmissionDecision* decision = nullptr) noexcept
{
    SubmissionDecision local;
    auto& admission = decision ? *decision : local;
    admission = {};
    DecisionScope decisionScope(admission);
    if (!queue) { DenySubmission(E_INVALIDARG); return nullptr; }
    auto& r = GetRegistry();
    uint64_t submissionId = 0;
    { std::lock_guard lock(r.mutex); submissionId = r.nextSubmission++; }
    try
    {
        Poll();
        auto s = std::make_shared<Submission>();
        s->queue = queue; // COM ownership and point allocation precede registry locks/Execute.
        for (size_t i = 0; i < identities.count; ++i)
        {
            bool unknownFailure = false;
            auto recording = ResolveRecording(identities, i, &unknownFailure);
            if (unknownFailure) { OrderingFallback(queue, identities, submissionId); return nullptr; }
            if (!recording) continue;
            std::lock_guard lock(r.mutex);
            try
            {
                s->leases.insert(s->leases.end(), recording->leases.begin(), recording->leases.end());
                s->prepareSubmission.insert(s->prepareSubmission.end(), recording->prepareSubmission.begin(), recording->prepareSubmission.end());
                if (!recording->callbacks.empty())
                {
                    const auto first = s->callbacks.size();
                    for (const auto& callbacks : recording->callbacks)
                        s->callbacks.push_back({{queue, submissionId, recording->id, 0, false}, callbacks});
                    s->occurrences.push_back({recording, first, recording->callbacks.size()});
                }
            }
            catch (...) { r.completionFailed = true; throw; }
        }
        if (s->leases.empty()) return nullptr;
        // Existing users with no new callbacks allocate no fence point/occurrence.
        if (!s->callbacks.empty()) { s->point = std::make_shared<FencePoint>(); s->point->queue = queue; }
        {
            std::lock_guard lock(r.mutex);
            try { r.submissions.push_back(s); } catch (...) { r.completionFailed = true; throw; }
            s->registrySlot = r.submissions.size()-1;
            // Commit counters only after every snapshot allocation succeeded.
            for (const auto& occurrence : s->occurrences)
            {
                const auto ordinal = ++occurrence.recording->submissionCount;
                for (size_t i = occurrence.first; i < occurrence.first + occurrence.count; ++i)
                    s->callbacks[i].info.recordingSubmission = ordinal;
            }
        }
        // Every necessary wait runs before Execute and outside all registry locks.
        for (const auto& prepare : s->prepareSubmission)
            try { prepare(queue); } catch (...) { s->preparationFailed = true; FailCompletion(); }
        for (const auto& callback : s->callbacks)
            if (callback.callbacks.beforeSubmit)
                try { if (!callback.callbacks.beforeSubmit(callback.info)) { s->preparationFailed = true; FailCompletion(); } }
                catch (...) { s->preparationFailed = true; FailCompletion(); }
        if (!admission.allowed) s->preparationFailed = true;
        if (s->preparationFailed) NotifyFailure(s, !admission.allowed ? SubmissionFailure::Ordering : SubmissionFailure::Prepare);
        s->decision = admission;
        return s;
    }
    catch (...) { OrderingFallback(queue, identities, submissionId); return nullptr; }
}
inline std::shared_ptr<Submission> BeforeSubmission(ID3D12CommandQueue* queue, const std::vector<IUnknown*>& identities,
                                                   SubmissionDecision* decision = nullptr) noexcept
{
    const IdentityRange range {&identities, identities.size(),
        [](const void* context, size_t index, IUnknown** out) -> HRESULT {
            auto* identity = (*static_cast<const std::vector<IUnknown*>*>(context))[index];
            *out = identity; if (identity) identity->AddRef(); return S_OK;
        },
        [](const void* context, size_t index) -> void* { return (*static_cast<const std::vector<IUnknown*>*>(context))[index]; }};
    return BeforeSubmission(queue, range, decision);
}
inline void AfterSubmission(const std::shared_ptr<Submission>& s) noexcept
{
    if (!s || !s->decision.allowed) return;
    auto failure = SubmissionFailure::FenceCreate;
    try
    {
        ComPtr<ID3D12Device> device;
        ComPtr<ID3D12Fence> fence;
        if (FAILED(s->queue->GetDevice(IID_PPV_ARGS(&device))) ||
            FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence))))
        {
            FailCompletion(); // registry retains intent forever, rejects new tracked work
            NotifyFailure(s, SubmissionFailure::FenceCreate);
            return;
        }
        s->fence = std::move(fence);
        if (s->point) s->point->fence = s->fence;
        failure = SubmissionFailure::Signal;
        if (FAILED(s->queue->Signal(s->fence.Get(), 1)))
        {
            FailCompletion(); // retain even the fence on an uncertain Signal result
            NotifyFailure(s, SubmissionFailure::Signal);
            return;
        }
        auto& r = GetRegistry();
        bool published = false;
        {
            std::lock_guard lock(r.mutex);
            published = Detail::PublishLocked(r,*s);
            if (!published) r.completionFailed = true;
        }
        if (!published) { NotifyFailure(s,SubmissionFailure::Publish); return; }
        if (s->point) s->point->published_ = true;
        failure = SubmissionFailure::Publish;
        if (!s->preparationFailed)
        {
            const FencePointPtr point = s->point;
            for (const auto& callback : s->callbacks)
                if (callback.callbacks.fencePublished) callback.callbacks.fencePublished(callback.info, point);
        }
    }
    catch (...) { FailCompletion(); NotifyFailure(s, failure); }
}
}
