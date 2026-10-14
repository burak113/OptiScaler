#pragma once
#include <windows.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <mutex>

namespace NrdBridgePerf
{
enum class Hook : size_t { ConstantBufferView, ShaderResourceView, UnorderedAccessView, Release, Count };
struct Sample { uint64_t calls = 0, ticks = 0; };
struct Report
{
    uint32_t frames = 0, firstFrame = UINT32_MAX, lastFrame = UINT32_MAX;
    uint64_t frequency = 0;
    std::array<Sample,size_t(Hook::Count)> hooks {};
    double AverageUs(Hook hook) const noexcept
    {
        const auto& sample = hooks[size_t(hook)];
        return sample.calls && frequency ? double(sample.ticks)*1000000.0/double(frequency)/double(sample.calls) : 0.0;
    }
};
using Reporter = void (*)(const Report&) noexcept;
namespace Detail
{
struct alignas(64) Counter { std::atomic<uint64_t> calls {0}, ticks {0}; };
struct State
{
    std::mutex frameMutex;
    std::atomic<Reporter> reporter {nullptr};
    std::atomic<uint64_t> inFlight {0};
    std::atomic<bool> requested {false}, reported {false};
    uint32_t frames = 0, firstFrame = UINT32_MAX, lastFrame = UINT32_MAX;
    std::array<uint32_t,100> seenFrames {};
    uint64_t frequency = 0;
    std::array<Counter,size_t(Hook::Count)> hooks;
};
inline std::atomic<bool> configured {false}, collecting {false};
inline thread_local std::array<unsigned,size_t(Hook::Count)> depth {};
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
    result.frequency = state.frequency;
    for (size_t i=0;i<result.hooks.size();++i)
    { result.hooks[i].calls = state.hooks[i].calls.load(std::memory_order_acquire); result.hooks[i].ticks = state.hooks[i].ticks.load(std::memory_order_acquire); }
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
// Called only by a real title render evaluation or the verified NRD Recon role.
// Duplicate SL frame ids (including FG Presents) never advance the sample window.
inline void RenderedFrame(uint32_t frame) noexcept
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
            Detail::collecting.store(false,std::memory_order_release);
            state.requested.store(true,std::memory_order_release); finished = true;
        }
        else
        {
            if (!state.frames) state.firstFrame = frame;
            state.seenFrames[state.frames] = frame; state.lastFrame = frame; ++state.frames;
            Detail::collecting.store(true,std::memory_order_release);
        }
    }
    if (finished) Detail::TryReport();
}
class Scope
{
    Hook hook_;
    LARGE_INTEGER start_ {};
    bool active_ = false, entered_ = false;
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
    }
    ~Scope()
    {
        if (active_)
        {
            LARGE_INTEGER end {}; QueryPerformanceCounter(&end);
            auto& state = Detail::Get(); auto& sample = state.hooks[size_t(hook_)];
            sample.ticks.fetch_add(uint64_t(end.QuadPart >= start_.QuadPart ? end.QuadPart-start_.QuadPart : 0),std::memory_order_relaxed);
            sample.calls.fetch_add(1,std::memory_order_relaxed);
            if (state.inFlight.fetch_sub(1,std::memory_order_acq_rel) == 1) Detail::TryReport();
        }
        if (entered_) --Detail::depth[size_t(hook_)];
    }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
};
}
