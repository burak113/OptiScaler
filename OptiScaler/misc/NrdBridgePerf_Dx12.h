#pragma once
#include <windows.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <mutex>

namespace NrdBridgePerf
{
enum class Hook : size_t
{
    ConstantBufferView, ShaderResourceView, UnorderedAccessView, Release,
    CopyDescriptors, SetPipelineState, RootSignature, RootTable, RootConstants, RootView,
    Dispatch, ExecuteIndirect, Barrier, ExecuteCommandLists, Present, Count
};
inline const char* HookName(Hook hook) noexcept
{
    constexpr std::array<const char*,size_t(Hook::Count)> names {
        "CBV","SRV","UAV","Release","CopyDescriptors","SetPipelineState","RootSignature","RootTable",
        "RootConstants","RootView","Dispatch","ExecuteIndirect","Barrier","ExecuteCommandLists","Present"};
    return names[size_t(hook)];
}
enum class WaitKind : size_t { Metadata, LifetimeGate, Tracking, Coordinator, DescriptorAdmission, Count };
struct Sample
{
    uint64_t calls = 0, ticks = 0;
    std::array<uint64_t,size_t(WaitKind::Count)> waitTicks {};
};
struct Report
{
    uint32_t frames = 0, firstFrame = UINT32_MAX, lastFrame = UINT32_MAX;
    uint64_t frequency = 0, consumerIntervalTicks = 0;
    std::array<Sample,size_t(Hook::Count)> hooks {};
    // CPU Consumer recording cadence across the same 100 intervals; not GPU time or FG/display FPS.
    bool ConsumerTimeValid() const noexcept { return frames && frequency && consumerIntervalTicks; }
    double ConsumerElapsedMs() const noexcept
    { return ConsumerTimeValid() ? double(consumerIntervalTicks)*1000.0/double(frequency) : 0.0; }
    double AverageConsumerIntervalMs() const noexcept
    { return ConsumerTimeValid() ? ConsumerElapsedMs()/double(frames) : 0.0; }
    double ConsumerIntervalsPerSecond() const noexcept
    { return ConsumerTimeValid() ? double(frames)*double(frequency)/double(consumerIntervalTicks) : 0.0; }
    double AverageUs(Hook hook) const noexcept
    {
        const auto& sample = hooks[size_t(hook)];
        return sample.calls && frequency ? double(sample.ticks)*1000000.0/double(frequency)/double(sample.calls) : 0.0;
    }
    double AverageWaitUs(Hook hook, WaitKind kind) const noexcept
    {
        const auto& sample = hooks[size_t(hook)];
        return sample.calls && frequency ? double(sample.waitTicks[size_t(kind)])*1000000.0/double(frequency)/double(sample.calls) : 0.0;
    }
    double AverageWaitUs(Hook hook) const noexcept
    {
        double total = 0.0;
        for (size_t i=0;i<size_t(WaitKind::Count);++i) total += AverageWaitUs(hook,WaitKind(i));
        return total;
    }
    double SumMsPerFrame(Hook hook, bool waitOnly = false) const noexcept
    {
        const auto& sample = hooks[size_t(hook)]; uint64_t ticks = sample.ticks;
        if (waitOnly) { ticks = 0; for (const auto wait : sample.waitTicks) ticks += wait; }
        return frames && frequency ? double(ticks)*1000.0/double(frequency)/double(frames) : 0.0;
    }
    double SumMsPerFrame(bool waitOnly = false) const noexcept
    {
        double total = 0.0;
        for (size_t i=0;i<size_t(Hook::Count);++i) total += SumMsPerFrame(Hook(i),waitOnly);
        return total;
    }
};
using Reporter = void (*)(const Report&) noexcept;
namespace Detail
{
struct alignas(64) Counter
{
    std::atomic<uint64_t> calls {0}, ticks {0};
    std::array<std::atomic<uint64_t>,size_t(WaitKind::Count)> waitTicks {};
};
struct State
{
    std::mutex frameMutex;
    std::atomic<Reporter> reporter {nullptr};
    std::atomic<uint64_t> inFlight {0};
    std::atomic<bool> requested {false}, reported {false};
    uint32_t frames = 0, firstFrame = UINT32_MAX, lastFrame = UINT32_MAX;
    std::array<uint32_t,100> seenFrames {};
    uint64_t frequency = 0, firstConsumerTick = 0, consumerIntervalTicks = 0;
    std::array<Counter,size_t(Hook::Count)> hooks;
};
inline std::atomic<bool> configured {false}, collecting {false};
inline thread_local std::array<unsigned,size_t(Hook::Count)> depth {};
inline thread_local std::array<uint64_t,size_t(WaitKind::Count)>* currentWaits = nullptr;
inline State& Get()
{
    // Physical hooks can still return during DLL teardown; storage has process lifetime.
    static auto* state = new State;
    return *state;
}
inline void TryReport() noexcept
{
    auto& state = Get();
    if (!state.requested.load(std::memory_order_acquire) || state.inFlight.load(std::memory_order_acquire)) return;
    if (state.reported.exchange(true,std::memory_order_acq_rel)) return;
    Report result;
    // requested is published only after the frame fields are frozen under frameMutex.
    result.frames = state.frames; result.firstFrame = state.firstFrame; result.lastFrame = state.lastFrame;
    result.frequency = state.frequency; result.consumerIntervalTicks = state.consumerIntervalTicks;
    for (size_t i=0;i<result.hooks.size();++i)
    {
        result.hooks[i].calls = state.hooks[i].calls.load(std::memory_order_acquire);
        result.hooks[i].ticks = state.hooks[i].ticks.load(std::memory_order_acquire);
        for (size_t j=0;j<size_t(WaitKind::Count);++j)
            result.hooks[i].waitTicks[j] = state.hooks[i].waitTicks[j].load(std::memory_order_acquire);
    }
    if (const auto report = state.reporter.load(std::memory_order_acquire)) report(result);
}
}
inline void Configure(Reporter reporter) noexcept
{
    try
    {
        if (!reporter) return;
        auto& state = Detail::Get(); std::scoped_lock lock(state.frameMutex);
        if (Detail::configured.load(std::memory_order_relaxed)) return;
        LARGE_INTEGER frequency {};
        if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0) return;
        state.frequency = uint64_t(frequency.QuadPart); state.reporter.store(reporter,std::memory_order_release);
        Detail::configured.store(true,std::memory_order_release);
    } catch (...) {} // Optional profiling allocation must never prevent title startup.
}
// Generic evaluations also occur in menus and never arm this gameplay sampler.
inline void RenderedFrame(uint32_t) noexcept {}
inline bool NeedsConsumerFrames() noexcept
{
    return Detail::configured.load(std::memory_order_acquire) &&
        !Detail::Get().requested.load(std::memory_order_acquire);
}
// Only the full-hash-identified title Consumer dispatch advances gameplay intervals.
// Duplicate SL frame ids (including FG Presents) never advance the sample window.
inline void ConsumerFrame(uint32_t frame) noexcept
{
    if (frame == UINT32_MAX || !Detail::configured.load(std::memory_order_acquire)) return;
    auto& state = Detail::Get(); bool finished = false;
    if (state.requested.load(std::memory_order_acquire)) return;
    {
        std::scoped_lock lock(state.frameMutex);
        if (state.requested.load(std::memory_order_relaxed) ||
            std::find(state.seenFrames.begin(),state.seenFrames.begin()+state.frames,frame) != state.seenFrames.begin()+state.frames) return;
        if (state.frames == 100)
        {
            LARGE_INTEGER end {};
            if (state.firstConsumerTick && QueryPerformanceCounter(&end) && end.QuadPart > 0 && uint64_t(end.QuadPart) >= state.firstConsumerTick)
                state.consumerIntervalTicks = uint64_t(end.QuadPart)-state.firstConsumerTick;
            Detail::collecting.store(false,std::memory_order_release);
            state.requested.store(true,std::memory_order_release); finished = true;
        }
        else
        {
            if (!state.frames)
            {
                state.firstFrame = frame; LARGE_INTEGER start {};
                if (QueryPerformanceCounter(&start) && start.QuadPart > 0) state.firstConsumerTick = uint64_t(start.QuadPart);
            }
            state.seenFrames[state.frames] = frame; state.lastFrame = frame; ++state.frames;
            Detail::collecting.store(true,std::memory_order_release);
        }
    }
    if (finished) Detail::TryReport();
}
// Duration is recorded in the currently measured physical hook, without global
// atomics or QPC calls when the one-shot gameplay profiling window is inactive.
class WaitScope
{
    WaitKind kind_;
    LARGE_INTEGER start_ {};
    std::array<uint64_t,size_t(WaitKind::Count)>* accumulator_ = nullptr;
  public:
    explicit WaitScope(WaitKind kind) noexcept : kind_(kind), accumulator_(Detail::currentWaits)
    {
        if (accumulator_ && !QueryPerformanceCounter(&start_)) accumulator_ = nullptr;
    }
    ~WaitScope()
    {
        if (!accumulator_) return;
        LARGE_INTEGER end {};
        if (QueryPerformanceCounter(&end) && end.QuadPart >= start_.QuadPart)
            (*accumulator_)[size_t(kind_)] += uint64_t(end.QuadPart-start_.QuadPart);
    }
    WaitScope(const WaitScope&) = delete;
    WaitScope& operator=(const WaitScope&) = delete;
};
template<class Mutex, WaitKind Kind> class TimedMutex
{
    Mutex mutex_;
  public:
    void lock() { WaitScope wait(Kind); mutex_.lock(); }
    bool try_lock() { WaitScope wait(Kind); return mutex_.try_lock(); }
    void unlock() noexcept { mutex_.unlock(); }
};
class Scope
{
    Hook hook_;
    LARGE_INTEGER start_ {};
    bool active_ = false, entered_ = false;
    std::array<uint64_t,size_t(WaitKind::Count)> waits_ {};
    std::array<uint64_t,size_t(WaitKind::Count)>* previousWaits_ = nullptr;
  public:
    explicit Scope(Hook hook, bool external) noexcept : hook_(hook)
    {
        if (!external || !Detail::collecting.load(std::memory_order_acquire)) return;
        entered_ = true;
        if (Detail::depth[size_t(hook_)]++) return; // Shared Release aliases count the same physical call once.
        auto& state = Detail::Get(); state.inFlight.fetch_add(1,std::memory_order_acq_rel);
        if (!Detail::collecting.load(std::memory_order_acquire) || !QueryPerformanceCounter(&start_))
        {
            if (state.inFlight.fetch_sub(1,std::memory_order_acq_rel) == 1) Detail::TryReport();
            return;
        }
        active_ = true;
        previousWaits_ = Detail::currentWaits; Detail::currentWaits = &waits_;
    }
    ~Scope()
    {
        if (active_)
        {
            LARGE_INTEGER end {}; QueryPerformanceCounter(&end);
            auto& state = Detail::Get(); auto& sample = state.hooks[size_t(hook_)];
            sample.ticks.fetch_add(uint64_t(end.QuadPart >= start_.QuadPart ? end.QuadPart-start_.QuadPart : 0),std::memory_order_relaxed);
            sample.calls.fetch_add(1,std::memory_order_relaxed);
            for (size_t i=0;i<waits_.size();++i)
                sample.waitTicks[i].fetch_add(waits_[i],std::memory_order_relaxed);
            Detail::currentWaits = previousWaits_;
            if (state.inFlight.fetch_sub(1,std::memory_order_acq_rel) == 1) Detail::TryReport();
        }
        if (entered_) --Detail::depth[size_t(hook_)];
    }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
};
}
