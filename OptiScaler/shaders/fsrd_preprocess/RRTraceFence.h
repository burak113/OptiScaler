#pragma once
// Header-only so source integration does not depend on adding a .cpp to the
// Visual Studio project. No PCH include in headers.
#include "RRTraceFenceState.h"
#include <d3d12.h>
#include <wrl/client.h>
#include <memory>
#include <mutex>
#include <vector>
#include <stdexcept>
#include <algorithm>

namespace RRTraceFence
{
using Microsoft::WRL::ComPtr;
struct Ticket
{
    std::mutex mutex;
    State state;
    ComPtr<IUnknown> identity;
    ComPtr<ID3D12Fence> fence;
    ComPtr<ID3D12CommandQueue> queue;
    std::vector<ComPtr<IUnknown>> resources;
    HRESULT signalResult = S_OK;
    std::uint64_t completion = 0;
    std::uint64_t generation = 0; // Unique ticket arm, not a guessed list lifetime.
    HANDLE waitEvent = nullptr;
    ~Ticket() { if (waitEvent) CloseHandle(waitEvent); }

    enum class WaitResult { Completed, Timeout, NotWaitable, Failed };
    WaitResult WaitBounded(DWORD milliseconds)
    {
        ComPtr<ID3D12Fence> waitingFence;
        std::uint64_t value = 0;
        HANDLE event = nullptr;
        {
            std::scoped_lock lock(mutex);
            if (!state.CanWait() || FAILED(signalResult)) return WaitResult::NotWaitable;
            completion = fence->GetCompletedValue();
            if (completion == UINT64_MAX) return WaitResult::Failed;
            if (completion >= state.expected) return WaitResult::Completed;
            waitingFence = fence; value = state.expected;
            if (!waitEvent) waitEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            event = waitEvent;
        }
        if (!event) return WaitResult::Failed;
        const HRESULT result = waitingFence->SetEventOnCompletion(value, event);
        const DWORD waited = SUCCEEDED(result) ? WaitForSingleObject(event, milliseconds) : WAIT_FAILED;
        // A timed-out registration still belongs to this fence. The ticket and
        // its event stay alive until proven completion permits resource release.
        return waited == WAIT_OBJECT_0 ? WaitResult::Completed
            : waited == WAIT_TIMEOUT ? WaitResult::Timeout : WaitResult::Failed;
    }

    void Retain(IUnknown* object)
    {
        if (!object) throw std::runtime_error("Null RRTrace lifetime object");
        resources.emplace_back(object);
    }
    bool Ready()
    {
        std::scoped_lock lock(mutex);
        completion = fence->GetCompletedValue();
        return state.Ready(completion);
    }
    bool Invalid()
    {
        std::scoped_lock lock(mutex);
        return state.invalid || state.signalFailed || fence->GetCompletedValue() == UINT64_MAX;
    }
    void CancelUnrecorded()
    {
        std::scoped_lock lock(mutex);
        state.invalid = true;
        state.detached = true;
    }
    bool Releasable()
    {
        std::scoped_lock lock(mutex);
        completion = fence->GetCompletedValue();
        return state.CanRelease(completion);
    }
    void Recorded()
    {
        std::scoped_lock lock(mutex);
        state.recorded = true;
    }
    void Invalidate()
    {
        std::scoped_lock lock(mutex);
        state.invalid = true;
    }
    void Abandon()
    {
        std::scoped_lock lock(mutex);
        state.abandoned = true;
    }
};
struct Registry
{
    std::mutex mutex;
    std::vector<std::shared_ptr<Ticket>> tickets;
    std::uint64_t nextGeneration = 0;
};
struct Snapshot
{
    State state;
    std::uint64_t identity = 0, generation = 0, queue = 0, completed = 0;
    HRESULT signalResult = S_OK;
};
inline Snapshot Inspect(const std::shared_ptr<Ticket>& ticket)
{
    if (!ticket) return {};
    std::scoped_lock lock(ticket->mutex);
    return {ticket->state, std::uint64_t(reinterpret_cast<uintptr_t>(ticket->identity.Get())),
        ticket->generation, std::uint64_t(reinterpret_cast<uintptr_t>(ticket->queue.Get())),
        ticket->fence ? ticket->fence->GetCompletedValue() : 0, ticket->signalResult};
}
inline Registry& GetRegistry()
{
    // Do not destroy uncertain in-flight captures during DLL/static teardown.
    // At most four unresolved tickets are allowed. Completed abandoned tickets
    // are reclaimed on the next submission/arm. No detached worker thread.
    static auto* registry = new Registry;
    return *registry;
}
// Freeze completed readback bytes before a still-executable list can submit
// again. BeforeSubmission holds this same registry gate BEFORE the original
// ExecuteCommandLists call; any earlier intent is visible in the ticket state.
// The copier receives immutable proof from this exact critical section. It
// must only Map/memcpy/Unmap into preallocated CPU storage: no allocation,
// hashing, disk I/O, GPU waits, or calls back into this registry/ticket.
// Reset/release ownership remains unchanged, even after a successful copy.
template<class Copier>
inline bool WithCompletedSnapshot(const std::shared_ptr<Ticket>& ticket, Copier&& copier)
{
    if (!ticket) return false;
    auto& registry = GetRegistry();
    std::scoped_lock registryLock(registry.mutex);
    if (std::find(registry.tickets.begin(), registry.tickets.end(), ticket) == registry.tickets.end())
        return false;
    std::scoped_lock ticketLock(ticket->mutex);
    ticket->completion = ticket->fence->GetCompletedValue();
    if (FAILED(ticket->signalResult) || !ticket->state.CanSnapshot(ticket->completion))
        return false;
    const Snapshot proof {ticket->state,
        std::uint64_t(reinterpret_cast<uintptr_t>(ticket->identity.Get())), ticket->generation,
        std::uint64_t(reinterpret_cast<uintptr_t>(ticket->queue.Get())), ticket->completion,
        ticket->signalResult};
    copier(proof);
    return true;
}
inline void ReapLocked(Registry& r)
{
    std::erase_if(r.tickets, [](const auto& t) {
        std::scoped_lock lock(t->mutex);
        return t->state.abandoned && t->state.CanRelease(t->fence->GetCompletedValue());
    });
}
inline std::shared_ptr<Ticket> Arm(ID3D12Device* device, ID3D12CommandList* list)
{
    if (!device || !list ||
        (list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT &&
         list->GetType() != D3D12_COMMAND_LIST_TYPE_COMPUTE))
        throw std::runtime_error("RRTrace requires a real direct/compute command list");
    auto t = std::make_shared<Ticket>();
    if (FAILED(list->QueryInterface(IID_PPV_ARGS(&t->identity))) ||
        FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&t->fence))))
        throw std::runtime_error("RRTrace fence/command identity allocation failed");
    auto& r = GetRegistry();
    std::scoped_lock lock(r.mutex);
    ReapLocked(r);
    if (r.tickets.size() >= 4)
        throw std::runtime_error("RRTrace has unresolved captures; refusing unsafe resource reuse");
    t->generation = ++r.nextGeneration;
    r.tickets.push_back(t);
    return t;
}
inline void Forget(const std::shared_ptr<Ticket>& ticket)
{
    if (!ticket || !ticket->Releasable()) return;
    auto& r = GetRegistry();
    std::scoped_lock lock(r.mutex);
    std::erase(r.tickets, ticket);
}
struct Submission
{
    std::shared_ptr<Ticket> ticket;
    std::uint64_t value;
};
// The appender is separate so the allocation-failure path can be exercised
// deterministically. It must not call back into registry/ticket operations.
template<class Appender>
inline void RecordSubmissionIntents(ID3D12CommandQueue* queue, UINT count,
                                   ID3D12CommandList* const* lists, Appender&& append) noexcept
{
    try
    {
        if (!queue || !lists) return;
        auto& r = GetRegistry();
        std::scoped_lock lock(r.mutex);
        ReapLocked(r);
        if (r.tickets.empty()) return;
        for (UINT i = 0; i < count; ++i)
        {
            if (!lists[i]) continue;
            ComPtr<IUnknown> identity;
            if (FAILED(lists[i]->QueryInterface(IID_PPV_ARGS(&identity))) || !identity)
                throw std::runtime_error("RRTrace submission identity unavailable");
            for (auto& t : r.tickets)
            {
                std::scoped_lock ticketLock(t->mutex);
                if (t->identity.Get() != identity.Get() || !t->state.Submit()) continue;
                t->queue = queue;
                append(Submission {t,t->state.expected});
            }
        }
    }
    catch (...)
    {
        // The original ExecuteCommandLists still runs. Failure may occur before
        // a later batch member was visited, so quarantine every executable
        // recording, not just the ticket whose vector append failed. Merely
        // setting invalid would still let Reset + an OLD fence release storage.
        try
        {
            auto& r = GetRegistry();
            std::scoped_lock lock(r.mutex);
            for (auto& ticket : r.tickets)
            {
                std::scoped_lock ticketLock(ticket->mutex);
                if (!ticket->state.detached) ticket->state.UntrackedSubmission();
            }
        }
        catch (...) { /* Synchronization failure cannot be recovered here. */ }
    }
}
// Register submission intent BEFORE the original call. Otherwise a legal Reset
// from another thread could be observed between ExecuteCommandLists returning
// and the post-call fence, and falsely classify submitted work as discarded.
inline std::vector<Submission> BeforeSubmission(
    ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) noexcept
{
    std::vector<Submission> submissions;
    RecordSubmissionIntents(queue,count,lists,[&](const Submission& submission) {
        submissions.push_back(submission);
    });
    return submissions;
}
// This call is AFTER the original ExecuteCommandLists on the same actual queue.
inline void AfterSubmission(ID3D12CommandQueue* queue,
                            const std::vector<Submission>& submissions) noexcept
{
    for (const auto& submission : submissions)
    {
        try
        {
            auto& t = *submission.ticket;
            // Do not hold our mutex across an external COM/queue call.
            const HRESULT result = queue->Signal(t.fence.Get(),submission.value);
            std::scoped_lock lock(t.mutex);
            t.signalResult = result;
            t.state.SignalEnqueued(SUCCEEDED(result));
        }
        catch (...) { /* Unpaired pending signal prevents both export and release. */ }
    }
}
// Called only AFTER a successful original graphics-command-list Reset.
inline void ResetSucceeded(ID3D12GraphicsCommandList* list) noexcept
{
    try
    {
        if (!list) return;
        auto& r = GetRegistry();
        std::scoped_lock lock(r.mutex);
        if (r.tickets.empty()) return;
        ComPtr<IUnknown> identity;
        if (FAILED(list->QueryInterface(IID_PPV_ARGS(&identity)))) return;
        for (auto& t : r.tickets)
        {
            std::scoped_lock ticketLock(t->mutex);
            if (t->identity.Get() == identity.Get()) t->state.ResetSucceeded();
        }
    }
    catch (...) {}
}
}
