#pragma once

#include <windows.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <type_traits>

// CPU elapsed spans only. Stages overlap (provider is inside RR/physical hold),
// so their totals must never be added to infer a frame critical path/GPU time.
// Callers serialize Sample writes with existing recording/injection ownership,
// and serialize Collector::Active/AcceptSuccessful with an existing host lock.
// Accept only AFTER all timers for a successfully committed recording have ended.
namespace NrdBridgeStagePerf
{
enum class Stage : uint8_t
{
    ReconInjectionWait, ReconInjectionHold, ReconPhysicalWait, ReconPhysicalHold,
    ReconPrepare, ReconConvert, MotionPhysicalHold,
    ConsumerInjectionWait, ConsumerInjectionHold, ConsumerPhysicalWait, ConsumerPhysicalHold,
    ConsumerRRDispatch, ProviderDispatch, OutputCommit, Count
};
inline constexpr size_t StageCount = size_t(Stage::Count);
inline constexpr uint32_t Capacity = 100;
inline constexpr const char* StageName(Stage stage) noexcept
{
    constexpr std::array<const char*, StageCount> names {
        "recon_injection_wait", "recon_injection_hold", "recon_physical_wait", "recon_physical_hold",
        "recon_prepare", "recon_convert", "motion_physical_hold",
        "consumer_injection_wait", "consumer_injection_hold", "consumer_physical_wait", "consumer_physical_hold",
        "consumer_rr_dispatch", "provider_dispatch", "output_commit"};
    return size_t(stage) < names.size() ? names[size_t(stage)] : "invalid";
}

struct StageValue
{
    uint64_t ticks, events;
    bool invalid;
};
struct Sample
{
    std::array<StageValue, StageCount> stages;
    const std::atomic<bool>* stopped; // Optional process-lifetime stop flag; never a title/native pointer.

    bool Enabled() const noexcept
    { return !stopped || !stopped->load(std::memory_order_acquire); }

    // A recording starts with Sample{}. Zero elapsed ticks are a valid observed
    // event; events==0 means missing, which is excluded from statistics.
    bool Add(Stage stage, uint64_t elapsed) noexcept
    {
        if (!Enabled() || size_t(stage) >= StageCount) return false;
        auto& value = stages[size_t(stage)];
        if (value.invalid) return false;
        if (elapsed > UINT64_MAX - value.ticks || value.events == UINT64_MAX)
        { value.invalid = true; return false; }
        value.ticks += elapsed; ++value.events; return true;
    }
    void Invalidate(Stage stage) noexcept
    { if (Enabled() && size_t(stage) < StageCount) stages[size_t(stage)].invalid = true; }
};
static_assert(std::is_trivial_v<Sample> && std::is_standard_layout_v<Sample> && std::is_trivially_copyable_v<Sample>);

class StackTimer
{
    Sample* sample_ = nullptr;
    Stage stage_ = Stage::Count;
    LARGE_INTEGER begin_ {};
  public:
    StackTimer(Sample* sample, Stage stage) noexcept : sample_(sample), stage_(stage)
    {
        if (!sample_ || !sample_->Enabled()) { sample_ = nullptr; return; }
        if (size_t(stage_) >= StageCount) { sample_ = nullptr; return; }
        if (!::QueryPerformanceCounter(&begin_) || begin_.QuadPart < 0)
        { sample_->Invalidate(stage_); sample_ = nullptr; }
    }
    bool Stop() noexcept
    {
        auto* sample = sample_;
        if (!sample) return false;
        sample_ = nullptr; // Explicit Stop and destruction can never double count.
        if (!sample->Enabled()) return false;
        LARGE_INTEGER end {};
        if (!::QueryPerformanceCounter(&end) || end.QuadPart < begin_.QuadPart)
        { sample->Invalidate(stage_); return false; }
        return sample->Add(stage_, uint64_t(end.QuadPart) - uint64_t(begin_.QuadPart));
    }
    ~StackTimer() { Stop(); }
    StackTimer(const StackTimer&) = delete;
    StackTimer& operator=(const StackTimer&) = delete;
};

struct StageStatistics
{
    uint32_t observedSamples, invalidSamples;
    uint64_t events, totalTicks, maxTicks, p95Ticks;
    bool saturated;
    // These describe totals per OBSERVED successful recording, not per event.
    double MeanMs(uint64_t frequency) const noexcept
    { return frequency && observedSamples && !saturated ? double(totalTicks) * 1000.0 / double(frequency) / observedSamples : 0.0; }
    double MaxMs(uint64_t frequency) const noexcept
    { return frequency && observedSamples ? double(maxTicks) * 1000.0 / double(frequency) : 0.0; }
    double P95Ms(uint64_t frequency) const noexcept
    { return frequency && observedSamples ? double(p95Ticks) * 1000.0 / double(frequency) : 0.0; }
};
struct Report
{
    uint32_t frames, firstSL, lastSL;
    uint64_t frequency;
    std::array<StageStatistics, StageCount> stages;
    const void* collector; // Identity only; never dereferenced or logged.
};
static_assert(std::is_trivial_v<Report> && std::is_standard_layout_v<Report> && std::is_trivially_copyable_v<Report>);
using Reporter = void (*)(const Report&) noexcept;

class Collector
{
    struct Entry { uint32_t frame; Sample sample; };
    std::array<Entry, Capacity> entries_ {};
    uint32_t count_ = 0;
    std::atomic<bool> ready_ {false};
    std::atomic<bool> published_ {false};

    static void AddSaturated(uint64_t& total, uint64_t value, bool& saturated) noexcept
    {
        if (value > UINT64_MAX - total) { total = UINT64_MAX; saturated = true; }
        else total += value;
    }
    void Build(Report& report) const noexcept
    {
        report = {};
        report.frames = count_; report.firstSL = entries_[0].frame; report.lastSL = entries_[count_ - 1].frame;
        report.collector = this;
        LARGE_INTEGER frequency {};
        if (::QueryPerformanceFrequency(&frequency) && frequency.QuadPart > 0)
            report.frequency = uint64_t(frequency.QuadPart);
        for (size_t index = 0; index != StageCount; ++index)
        {
            auto& stats = report.stages[index];
            std::array<uint64_t, Capacity> sorted {}; // Stack storage; sort observed entries only.
            for (uint32_t frame = 0; frame != count_; ++frame)
            {
                const auto& value = entries_[frame].sample.stages[index];
                if (value.invalid) { ++stats.invalidSamples; continue; }
                if (!value.events) continue;
                sorted[stats.observedSamples++] = value.ticks;
                AddSaturated(stats.totalTicks, value.ticks, stats.saturated);
                AddSaturated(stats.events, value.events, stats.saturated);
            }
            if (!stats.observedSamples) continue;
            std::sort(sorted.begin(), sorted.begin() + stats.observedSamples);
            stats.maxTicks = sorted[stats.observedSamples - 1];
            // Defined nearest-rank p95: ceil(.95 * observed count), 1-based.
            const auto rank = (95u * stats.observedSamples + 99u) / 100u;
            stats.p95Ticks = sorted[rank - 1];
        }
    }

  public:
    Collector() noexcept = default;
    Collector(const Collector&) = delete;
    Collector& operator=(const Collector&) = delete;
    // No clock/registry/heap/native COM calls before the first successful sample.
    bool Active() const noexcept { return count_ < Capacity; }
    uint32_t Accepted() const noexcept { return count_; }
    bool AcceptSuccessful(uint32_t slFrame, const Sample& completeSample,
                          bool committed, Report& report) noexcept
    {
        if (!committed || slFrame == UINT32_MAX || !Active()) return false;
        for (uint32_t index = 0; index != count_; ++index)
            if (entries_[index].frame == slFrame) return false;
        entries_[count_++] = {slFrame, completeSample};
        if (count_ != Capacity) return false;
        Build(report); // POD-only result; no reporter can run under the host lock.
        ready_.store(true, std::memory_order_release);
        return true;
    }
    // Caller MUST leave all host/root/physical locks before this call and retain
    // this Collector through it. A single process-lifetime Collector yields one
    // process-lifetime line. There is deliberately no reset/rearm API.
    bool Publish(const Report& report, Reporter reporter) noexcept
    {
        if (!reporter || !ready_.load(std::memory_order_acquire) ||
            report.collector != this || report.frames != Capacity) return false;
        bool expected = false;
        if (!published_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) return false;
        reporter(report); return true;
    }
};
static_assert(std::atomic<bool>::is_always_lock_free);
static_assert(sizeof(Collector) <= 65536, "CPU profiling storage must remain fixed and bounded");
}
