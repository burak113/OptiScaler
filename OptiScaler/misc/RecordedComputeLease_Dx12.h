#pragma once

#include <d3d12.h>
#include <wrl/client.h>
#include <algorithm>
#include <functional>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

// ComputeState ownership only: this does not retire the opaque RR provider/context.
// COM calls and destruction of retained objects always occur outside the registry lock.
namespace RecordedComputeLease
{
using Microsoft::WRL::ComPtr;
struct Recording
{
    IUnknown* identity = nullptr; // weak canonical identity; owning it prevents final Release
    std::vector<void*> aliases;
    std::vector<std::shared_ptr<void>> leases;
    // Optional gated work can learn the ACTUAL queue immediately before Execute.
    // Every gate starts denied and owns its private upload storage through a lease.
    std::vector<std::function<void(ID3D12CommandQueue*)>> prepareSubmission;
    size_t releasesInFlight = 0;
};
struct Submission
{
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12Fence> fence; // distinct fence per submission; no cross-thread value ordering
    std::vector<std::shared_ptr<void>> leases;
    std::vector<std::function<void(ID3D12CommandQueue*)>> prepareSubmission;
    bool signalPublished = false;
};
struct Registry
{
    std::mutex mutex;
    bool listHooks = false, queueHook = false, completionFailed = false;
    std::unordered_map<IUnknown*, std::shared_ptr<Recording>> recordings;
    std::unordered_map<void*, std::weak_ptr<Recording>> aliases;
    std::vector<std::shared_ptr<Submission>> submissions;
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
inline void Poll() noexcept
{
    try
    {
        auto& r = GetRegistry();
        std::vector<std::shared_ptr<Submission>> candidates, garbage;
        {
            std::lock_guard lock(r.mutex);
            for (const auto& s : r.submissions)
                if (s->signalPublished) candidates.push_back(s);
        }
        for (const auto& s : candidates)
        {
            // UINT64_MAX means removed device: it can no longer consume this submission.
            if (s->fence->GetCompletedValue() < 1) continue;
            std::lock_guard lock(r.mutex);
            auto it = std::find(r.submissions.begin(), r.submissions.end(), s);
            if (it != r.submissions.end())
            {
                garbage.push_back(std::move(*it));
                r.submissions.erase(it);
            }
        }
        // garbage/candidates (and their COM objects) die after every lock is released.
    }
    catch (...) { FailCompletion(); }
}
inline bool Track(IUnknown* identity, const std::vector<void*>& aliases,
                  const std::shared_ptr<void>& lease,
                  std::function<void(ID3D12CommandQueue*)> prepareSubmission = {})
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
    for (void* alias : aliases)
    {
        if (!alias) continue;
        if (std::find(rec->aliases.begin(), rec->aliases.end(), alias) == rec->aliases.end())
            rec->aliases.push_back(alias);
        r.aliases[alias] = rec;
    }
    rec->leases.push_back(lease);
    if (prepareSubmission) rec->prepareSubmission.push_back(std::move(prepareSubmission));
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
inline std::shared_ptr<Submission> BeforeSubmission(
    ID3D12CommandQueue* queue, const std::vector<IUnknown*>& identities) noexcept
{
    try
    {
        if (!queue) return nullptr;
        Poll();
        auto s = std::make_shared<Submission>();
        s->queue = queue; // retain real queue identity before registry lock
        auto& r = GetRegistry();
        {
            std::lock_guard lock(r.mutex);
            try
            {
                for (auto key : identities)
                {
                    auto it = r.recordings.find(key);
                    if (it == r.recordings.end()) continue;
                    s->leases.insert(s->leases.end(), it->second->leases.begin(), it->second->leases.end());
                    s->prepareSubmission.insert(s->prepareSubmission.end(),
                        it->second->prepareSubmission.begin(), it->second->prepareSubmission.end());
                }
                if (s->leases.empty()) return nullptr;
                // Registry owns the intent BEFORE Execute; Reset in the post-call gap is safe.
                r.submissions.push_back(s);
            }
            catch (...)
            {
                // Latch before unlock/unwinding so Reset/Release cannot discard the
                // recording when a PRE snapshot allocation was incomplete.
                r.completionFailed = true;
                throw;
            }
        }
        // Do not call consumers, COM or queue methods under the registry lock.
        // This function completes before the hook calls the real ExecuteCommandLists.
        // Consumers must keep work denied if preparation throws; uncertainty also
        // latches the existing completion failure policy and retains every lease.
        for (const auto& prepare : s->prepareSubmission)
        {
            try { prepare(s->queue.Get()); }
            catch (...) { FailCompletion(); }
        }
        return s;
    }
    catch (...) { FailCompletion(); return nullptr; }
}
inline void AfterSubmission(const std::shared_ptr<Submission>& s) noexcept
{
    if (!s) return;
    try
    {
        ComPtr<ID3D12Device> device;
        ComPtr<ID3D12Fence> fence;
        if (FAILED(s->queue->GetDevice(IID_PPV_ARGS(&device))) ||
            FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence))))
        {
            FailCompletion(); // registry retains intent forever, rejects new tracked work
            return;
        }
        s->fence = std::move(fence);
        if (FAILED(s->queue->Signal(s->fence.Get(), 1)))
        {
            FailCompletion(); // retain even the fence on an uncertain Signal result
            return;
        }
        auto& r = GetRegistry();
        std::lock_guard lock(r.mutex);
        s->signalPublished = true;
    }
    catch (...) { FailCompletion(); }
}
}
