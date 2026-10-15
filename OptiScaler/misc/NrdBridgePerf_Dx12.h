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
    // Per-interval CPU Consumer recording ticks between consecutive identified
    // Consumer frames (interval i = frame i+1 minus frame i). 0 = not sampled.
    std::array<uint64_t,100> intervalTicks {};
    std::array<Sample,size_t(Hook::Count)> hooks {};
    // CPU Consumer recording cadence across the same 100 intervals; not GPU time or FG/display FPS.
    bool ConsumerTimeValid() const noexcept { return frames && frequency && consumerIntervalTicks; }
    double ConsumerElapsedMs() const noexcept
    { return ConsumerTimeValid() ? double(consumerIntervalTicks)*1000.0/double(frequency) : 0.0; }
    double AverageConsumerIntervalMs() const noexcept
    { return ConsumerTimeValid() ? ConsumerElapsedMs()/double(frames) : 0.0; }
    double ConsumerIntervalsPerSecond() const noexcept
    { return ConsumerTimeValid() ? double(frames)*double(frequency)/double(consumerIntervalTicks) : 0.0; }
    // Per-interval cadence quantiles (ms) over the complete 100-interval window.
    // These are actual per-interval wall samples: summing per-hook p95 values
    // never produces them, and they are not GPU kernel or displayed-FPS times.
    double ConsumerIntervalQuantileMs(double quantile) const noexcept
    {
        if (!frames || !frequency) return 0.0;
        if (quantile < 0.0) quantile = 0.0; if (quantile > 1.0) quantile = 1.0;
        std::array<double,100> values {}; size_t count = 0;
        for (size_t index = 0; index < frames && index < intervalTicks.size(); ++index)
            if (intervalTicks[index]) { values[count] = double(intervalTicks[index])*1000.0/double(frequency); ++count; }
        if (!count) return 0.0;
        std::sort(values.begin(),values.begin()+count);
        const double position = quantile*double(count-1); const size_t lower = size_t(position);
        const size_t upper = std::min(lower+1,count-1);
        return values[lower]+(values[upper]-values[lower])*(position-double(lower));
    }
    double ConsumerIntervalP50Ms() const noexcept { return ConsumerIntervalQuantileMs(0.50); }
    double ConsumerIntervalP95Ms() const noexcept { return ConsumerIntervalQuantileMs(0.95); }
    double ConsumerIntervalP99Ms() const noexcept { return ConsumerIntervalQuantileMs(0.99); }
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
    // Thread-time per Consumer interval: the sum of measured CPU intervals across
    // every thread and physical alias that shared one hook. Concurrent callers
    // overlap, so this is never a frame duration and never the frame critical path.
    double ThreadTimeSumMsPerInterval(Hook hook, bool waitOnly = false) const noexcept
    { return SumMsPerFrame(hook,waitOnly); }
    double ThreadTimeSumMsPerInterval(bool waitOnly = false) const noexcept
    { return SumMsPerFrame(waitOnly); }
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
    uint64_t frequency = 0, firstConsumerTick = 0, previousConsumerTick = 0, consumerIntervalTicks = 0;
    std::array<uint64_t,100> intervalTicks {};
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
    result.intervalTicks = state.intervalTicks;
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
        LARGE_INTEGER tick {}; const bool sampled = QueryPerformanceCounter(&tick) && tick.QuadPart > 0;
        if (state.frames && sampled && state.previousConsumerTick && uint64_t(tick.QuadPart) >= state.previousConsumerTick)
            state.intervalTicks[state.frames-1] = uint64_t(tick.QuadPart)-state.previousConsumerTick;
        if (sampled) state.previousConsumerTick = uint64_t(tick.QuadPart);
        if (state.frames == 100)
        {
            if (state.firstConsumerTick && sampled && uint64_t(tick.QuadPart) >= state.firstConsumerTick)
                state.consumerIntervalTicks = uint64_t(tick.QuadPart)-state.firstConsumerTick;
            Detail::collecting.store(false,std::memory_order_release);
            state.requested.store(true,std::memory_order_release); finished = true;
        }
        else
        {
            if (!state.frames)
            {
                state.firstFrame = frame;
                if (sampled) state.firstConsumerTick = uint64_t(tick.QuadPart);
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
