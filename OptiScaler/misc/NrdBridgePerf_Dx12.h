#pragma once
#include <windows.h>
#include <tlhelp32.h>
#include <intrin.h>
#include <cstdio>
#include <iterator>
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <vector>

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

// Whole-session periodic profiler. Every counter lives in a block owned by one
// thread (single writer, relaxed load+store, no RMW), so measuring adds no shared
// cache-line traffic to the title's threads. Durations use the TSC; the reporter
// converts them with a QPC-calibrated rate. Lock waits are recorded only when a
// lock was actually contended (callers try_lock first).
namespace Periodic
{
enum class Sub : size_t { SurveyCopy, BaseCopy, NativeCopy, SurveyTable, BaseTable, SurveyView, SnapshotHold, RenderTargets, Count };
inline const char* SubName(Sub sub) noexcept
{
    constexpr std::array<const char*,size_t(Sub::Count)> names {"SurveyCopy","BaseCopy","NativeCopy","SurveyTable","BaseTable","SurveyView","SnapshotHold","RenderTargets"};
    return names[size_t(sub)];
}
inline constexpr size_t LockKinds = 8; // FrameSurveyMetadata::MetadataLock::Count fits.
inline const char* LockName(size_t kind) noexcept
{
    constexpr std::array<const char*,LockKinds> names {"CatalogShared","CatalogExclusive","Descriptor","Identity","Range","Snapshot","Mirror","Other"};
    return kind < LockKinds ? names[kind] : "Other";
}
struct alignas(64) ThreadBlock
{
    std::array<std::atomic<uint64_t>,size_t(Hook::Count)> calls {}, ticks {}, waitTicks {};
    std::array<std::atomic<uint64_t>,size_t(WaitKind::Count)> kindTicks {}, kindEvents {};
    std::array<std::atomic<uint64_t>,LockKinds> lockTicks {}, lockEvents {};
    std::array<std::atomic<uint64_t>,size_t(Sub::Count)> subCalls {}, subTicks {};
    std::atomic<uint64_t> descriptorsCopied {0}, copyCalls {0};
    // Live state for the hang watch: what this thread is doing right now.
    std::atomic<uint32_t> tid {0}, liveHook {UINT32_MAX}, liveWait {UINT32_MAX};
    std::atomic<uint64_t> liveHookTsc {0}, liveWaitTsc {0};
};
struct Totals
{
    std::array<uint64_t,size_t(Hook::Count)> calls {}, ticks {}, waitTicks {};
    std::array<uint64_t,size_t(WaitKind::Count)> kindTicks {}, kindEvents {};
    std::array<uint64_t,LockKinds> lockTicks {}, lockEvents {};
    std::array<uint64_t,size_t(Sub::Count)> subCalls {}, subTicks {};
    uint64_t descriptorsCopied = 0, copyCalls = 0;
};
struct Interval
{
    Totals delta;
    double seconds = 0.0, ticksPerMs = 0.0;
    uint64_t consumerFrames = 0;
    uint32_t threads = 0, index = 0;
    double Ms(uint64_t ticks) const noexcept { return ticksPerMs > 0.0 ? double(ticks)/ticksPerMs : 0.0; }
};
using Reporter = void (*)(const Interval&) noexcept;
// Receives one formatted hang-report line; nullptr asks the sink to flush.
using HangSink = void (*)(const char*) noexcept;
namespace Detail
{
struct Registry
{
    std::mutex mutex;
    std::vector<ThreadBlock*> blocks; // Blocks are never freed: hooks may run during teardown.
    Totals previous;
    LARGE_INTEGER qpc0 {}, qpcPrevious {};
    uint64_t tsc0 = 0, tscPrevious = 0;
    uint32_t index = 0;
};
inline std::atomic<bool> enabled {false};
inline std::atomic<Reporter> reporter {nullptr};
inline std::atomic<uint64_t> nextReportTsc {UINT64_MAX}, reportPeriodTsc {0}, consumerFrames {0};
inline std::atomic<bool> reporting {false};
inline std::atomic<double> tscPerMs {0.0};
inline thread_local ThreadBlock* block = nullptr;
inline thread_local uint32_t depth = 0;
inline thread_local size_t currentHook = size_t(Hook::Count);
inline Registry& Get() { static auto* registry = new Registry; return *registry; }
inline ThreadBlock* Block() noexcept
{
    if (block) return block;
    try
    {
        auto* created = new ThreadBlock;
        created->tid.store(GetCurrentThreadId(),std::memory_order_relaxed);
        auto& registry = Get(); std::scoped_lock lock(registry.mutex);
        registry.blocks.push_back(created); block = created;
    } catch (...) {}
    return block;
}
inline void Add(std::atomic<uint64_t>& counter, uint64_t value) noexcept
{ counter.store(counter.load(std::memory_order_relaxed)+value,std::memory_order_relaxed); }
inline void Report() noexcept
{
    try
    {
        auto& registry = Get(); Interval interval; Totals now;
        LARGE_INTEGER qpc {}; QueryPerformanceCounter(&qpc); const uint64_t tsc = __rdtsc();
        {
            std::scoped_lock lock(registry.mutex);
            for (const auto* block : registry.blocks)
            {
                for (size_t i=0;i<now.calls.size();++i)
                {
                    now.calls[i] += block->calls[i].load(std::memory_order_relaxed);
                    now.ticks[i] += block->ticks[i].load(std::memory_order_relaxed);
                    now.waitTicks[i] += block->waitTicks[i].load(std::memory_order_relaxed);
                }
                for (size_t i=0;i<now.kindTicks.size();++i)
                {
                    now.kindTicks[i] += block->kindTicks[i].load(std::memory_order_relaxed);
                    now.kindEvents[i] += block->kindEvents[i].load(std::memory_order_relaxed);
                }
                for (size_t i=0;i<LockKinds;++i)
                {
                    now.lockTicks[i] += block->lockTicks[i].load(std::memory_order_relaxed);
                    now.lockEvents[i] += block->lockEvents[i].load(std::memory_order_relaxed);
                }
                for (size_t i=0;i<now.subCalls.size();++i)
                {
                    now.subCalls[i] += block->subCalls[i].load(std::memory_order_relaxed);
                    now.subTicks[i] += block->subTicks[i].load(std::memory_order_relaxed);
                }
                now.descriptorsCopied += block->descriptorsCopied.load(std::memory_order_relaxed);
                now.copyCalls += block->copyCalls.load(std::memory_order_relaxed);
            }
            interval.threads = uint32_t(registry.blocks.size());
            const auto delta = [](auto& out, const auto& a, const auto& b) { for (size_t i=0;i<out.size();++i) out[i] = a[i]-b[i]; };
            delta(interval.delta.calls,now.calls,registry.previous.calls); delta(interval.delta.ticks,now.ticks,registry.previous.ticks);
            delta(interval.delta.waitTicks,now.waitTicks,registry.previous.waitTicks);
            delta(interval.delta.kindTicks,now.kindTicks,registry.previous.kindTicks);
            delta(interval.delta.kindEvents,now.kindEvents,registry.previous.kindEvents);
            delta(interval.delta.lockTicks,now.lockTicks,registry.previous.lockTicks);
            delta(interval.delta.lockEvents,now.lockEvents,registry.previous.lockEvents);
            delta(interval.delta.subCalls,now.subCalls,registry.previous.subCalls);
            delta(interval.delta.subTicks,now.subTicks,registry.previous.subTicks);
            interval.delta.descriptorsCopied = now.descriptorsCopied-registry.previous.descriptorsCopied;
            interval.delta.copyCalls = now.copyCalls-registry.previous.copyCalls;
            registry.previous = now;
            LARGE_INTEGER frequency {}; QueryPerformanceFrequency(&frequency);
            if (frequency.QuadPart > 0 && qpc.QuadPart > registry.qpc0.QuadPart && tsc > registry.tsc0)
                interval.ticksPerMs = double(tsc-registry.tsc0)*double(frequency.QuadPart)/double(qpc.QuadPart-registry.qpc0.QuadPart)/1000.0;
            if (frequency.QuadPart > 0 && qpc.QuadPart > registry.qpcPrevious.QuadPart)
                interval.seconds = double(qpc.QuadPart-registry.qpcPrevious.QuadPart)/double(frequency.QuadPart);
            registry.qpcPrevious = qpc; registry.tscPrevious = tsc;
            interval.index = ++registry.index;
        }
        interval.consumerFrames = consumerFrames.exchange(0,std::memory_order_acq_rel);
        if (const auto report = reporter.load(std::memory_order_acquire)) report(interval);
    } catch (...) {}
}
inline void MaybeReport(uint64_t tsc) noexcept
{
    if (tsc < nextReportTsc.load(std::memory_order_relaxed)) return;
    if (reporting.exchange(true,std::memory_order_acquire)) return;
    nextReportTsc.store(tsc+reportPeriodTsc.load(std::memory_order_relaxed),std::memory_order_relaxed);
    Report();
    reporting.store(false,std::memory_order_release);
}
}
inline bool Enabled() noexcept { return Detail::enabled.load(std::memory_order_relaxed); }
// Live wait codes: metadata lock kinds are 0..LockKinds-1, WaitKinds are 100+kind.
inline uint32_t BeginLiveWait(uint32_t code, uint64_t tsc) noexcept
{
    if (!Enabled()) return UINT32_MAX;
    auto* block = Detail::Block(); if (!block) return UINT32_MAX;
    const auto previous = block->liveWait.load(std::memory_order_relaxed);
    block->liveWaitTsc.store(tsc,std::memory_order_relaxed); block->liveWait.store(code,std::memory_order_relaxed);
    return previous;
}
inline void EndLiveWait(uint32_t previous) noexcept
{
    if (auto* block = Detail::block) block->liveWait.store(previous,std::memory_order_relaxed);
}
// Hang watch: a private thread notices when no Present completes for several
// seconds, then samples every thread's stack (module+offset) and this
// profiler's live hook/wait state, and writes them to the log with a flush.
// It never runs on a title thread and adds nothing to the hooks themselves.
namespace HangWatch
{
inline std::atomic<HangSink> sink {nullptr};
struct Row { DWORD tid = 0; uint32_t frames = 0; uint64_t pcs[40] {}; };
inline Row rows[768];
struct Live { DWORD tid = 0; uint32_t hook = UINT32_MAX, wait = UINT32_MAX; uint64_t hookTsc = 0, waitTsc = 0; };
inline Live live[512];
inline bool PresentCalls(uint64_t& total) noexcept
{
    auto& registry = Detail::Get();
    if (!registry.mutex.try_lock()) return false;
    total = 0;
    for (const auto* block : registry.blocks) total += block->calls[size_t(Hook::Present)].load(std::memory_order_relaxed);
    registry.mutex.unlock(); return true;
}
// No C++ objects with destructors here: __try needs a plain frame.
inline uint32_t Walk(HANDLE thread, uint64_t* pcs, uint32_t capacity) noexcept
{
    alignas(16) CONTEXT context {}; context.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
    if (!GetThreadContext(thread,&context)) return 0;
    uint32_t count = 0;
    __try
    {
        while (count < capacity && context.Rip)
        {
            pcs[count++] = context.Rip;
            DWORD64 imageBase = 0;
            auto* function = RtlLookupFunctionEntry(context.Rip,&imageBase,nullptr);
            if (!function) { context.Rip = *reinterpret_cast<const DWORD64*>(context.Rsp); context.Rsp += 8; }
            else
            {
                PVOID handler = nullptr; DWORD64 establisher = 0;
                RtlVirtualUnwind(UNW_FLAG_NHANDLER,imageBase,context.Rip,function,&context,&handler,&establisher,nullptr);
            }
        }
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {}
    return count;
}
inline void ModuleOffset(uint64_t pc, char* out, size_t size) noexcept
{
    HMODULE module = nullptr; char path[MAX_PATH] {};
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCSTR>(pc),&module) || !module || !GetModuleFileNameA(module,path,MAX_PATH))
    { snprintf(out,size,"?+0x%llx",static_cast<unsigned long long>(pc)); return; }
    const char* name = path; for (const char* c = path; *c; ++c) if (*c == '\\' || *c == '/') name = c+1;
    snprintf(out,size,"%s+0x%llx",name,static_cast<unsigned long long>(pc-reinterpret_cast<uint64_t>(module)));
}
inline const char* WaitName(uint32_t code) noexcept
{
    constexpr std::array<const char*,size_t(WaitKind::Count)> kinds {"Metadata","LifetimeGate","Tracking","Coordinator","DescriptorAdmission"};
    if (code == UINT32_MAX) return "-";
    if (code < LockKinds) return LockName(code);
    if (code >= 100 && code-100 < kinds.size()) return kinds[code-100];
    return "?";
}
inline void Dump(uint64_t stalledMs, uint32_t index) noexcept
{
    const auto write = sink.load(std::memory_order_acquire); if (!write) return;
    size_t liveCount = 0;
    auto& registry = Detail::Get();
    if (registry.mutex.try_lock())
    {
        for (const auto* block : registry.blocks)
        {
            if (liveCount >= std::size(live)) break;
            auto& entry = live[liveCount++];
            entry.tid = block->tid.load(std::memory_order_relaxed);
            entry.hook = block->liveHook.load(std::memory_order_relaxed); entry.hookTsc = block->liveHookTsc.load(std::memory_order_relaxed);
            entry.wait = block->liveWait.load(std::memory_order_relaxed); entry.waitTsc = block->liveWaitTsc.load(std::memory_order_relaxed);
        }
        registry.mutex.unlock();
    }
    const uint64_t tscNow = __rdtsc(); const double perMs = Detail::tscPerMs.load(std::memory_order_relaxed);
    const DWORD self = GetCurrentThreadId(), process = GetCurrentProcessId();
    size_t count = 0;
    // Stacks are sampled one thread at a time: suspend, unwind, resume. No
    // allocation or logging happens while any title thread is suspended.
    const HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
    if (snapshot != INVALID_HANDLE_VALUE)
    {
        THREADENTRY32 entry {}; entry.dwSize = sizeof(entry);
        for (BOOL ok = Thread32First(snapshot,&entry); ok && count < std::size(rows); ok = Thread32Next(snapshot,&entry))
        {
            if (entry.th32OwnerProcessID != process || entry.th32ThreadID == self) continue;
            auto& row = rows[count++]; row.tid = entry.th32ThreadID; row.frames = 0;
            const HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION,FALSE,row.tid);
            if (!thread) continue;
            if (SuspendThread(thread) != DWORD(-1)) { row.frames = Walk(thread,row.pcs,uint32_t(std::size(row.pcs))); ResumeThread(thread); }
            CloseHandle(thread);
        }
        CloseHandle(snapshot);
    }
    HMODULE self_module = nullptr;
    GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCSTR>(&Dump),&self_module);
    char line[6144];
    snprintf(line,sizeof(line),"hang #%u: no Present for %llu ms; threads=%zu profiled_threads=%zu (stacks are module+offset)",
        index,static_cast<unsigned long long>(stalledMs),count,liveCount);
    write(line);
    for (size_t i=0;i<count;++i)
    {
        const auto& row = rows[i];
        const Live* state = nullptr;
        for (size_t j=0;j<liveCount;++j) if (live[j].tid == row.tid) { state = &live[j]; break; }
        bool ours = false;
        for (uint32_t f=0;f<row.frames && !ours;++f)
        {
            HMODULE module = nullptr;
            ours = GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<LPCSTR>(row.pcs[f]),&module) && module == self_module;
        }
        int used = 0;
        const auto ms = [&](uint64_t tsc) { return perMs > 0.0 && tscNow > tsc ? double(tscNow-tsc)/perMs : 0.0; };
        if (state && (state->hook != UINT32_MAX || state->wait != UINT32_MAX))
            used = snprintf(line,sizeof(line),"hang #%u tid=%lu ours=%d hook=%s(%.0fms) wait=%s(%.0fms) stack:",index,row.tid,int(ours),
                state->hook < size_t(Hook::Count) ? HookName(Hook(state->hook)) : "-",state->hook != UINT32_MAX ? ms(state->hookTsc) : 0.0,
                WaitName(state->wait),state->wait != UINT32_MAX ? ms(state->waitTsc) : 0.0);
        else used = snprintf(line,sizeof(line),"hang #%u tid=%lu ours=%d stack:",index,row.tid,int(ours));
        const uint32_t frames = ours ? row.frames : std::min<uint32_t>(row.frames,12);
        for (uint32_t f=0;f<frames && used > 0 && size_t(used) < sizeof(line)-160;++f)
        {
            char frame[160]; ModuleOffset(row.pcs[f],frame,sizeof(frame));
            used += snprintf(line+used,sizeof(line)-size_t(used)," %s",frame);
        }
        write(line);
    }
    write(nullptr);
}
inline DWORD WINAPI Thread(void*) noexcept
{
    uint64_t last = 0; ULONGLONG changed = GetTickCount64(), lastDump = 0; uint32_t dumps = 0;
    for (;;)
    {
        Sleep(500);
        uint64_t presents = 0; const ULONGLONG now = GetTickCount64();
        if (PresentCalls(presents) && presents != last) { last = presents; changed = now; continue; }
        if (!last || now-changed < 5000 || dumps >= 4 || (lastDump && now-lastDump < 30000)) continue;
        lastDump = now; Dump(now-changed,++dumps);
    }
}
}
// Starts session-long sampling; the first row is written after periodSeconds.
inline void Configure(Reporter reporter, double periodSeconds = 10.0, HangSink hangSink = nullptr) noexcept
{
    try
    {
        if (!reporter || Detail::enabled.load(std::memory_order_acquire)) return;
        auto& registry = Detail::Get();
        LARGE_INTEGER frequency {}, start {};
        if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0 || !QueryPerformanceCounter(&start)) return;
        const uint64_t tsc0 = __rdtsc();
        // Calibrate the TSC period against QPC over ~2 ms once, at startup only.
        LARGE_INTEGER now {}; uint64_t tsc1 = tsc0;
        do { QueryPerformanceCounter(&now); tsc1 = __rdtsc(); } while (now.QuadPart-start.QuadPart < frequency.QuadPart/500);
        const double tscPerSecond = double(tsc1-tsc0)*double(frequency.QuadPart)/double(now.QuadPart-start.QuadPart);
        {
            std::scoped_lock lock(registry.mutex);
            registry.qpc0 = start; registry.tsc0 = tsc0; registry.qpcPrevious = now; registry.tscPrevious = tsc1;
        }
        Detail::reporter.store(reporter,std::memory_order_release);
        Detail::tscPerMs.store(tscPerSecond/1000.0,std::memory_order_relaxed);
        Detail::reportPeriodTsc.store(uint64_t(tscPerSecond*periodSeconds),std::memory_order_relaxed);
        Detail::nextReportTsc.store(tsc1+uint64_t(tscPerSecond*periodSeconds),std::memory_order_relaxed);
        Detail::enabled.store(true,std::memory_order_release);
        if (hangSink)
        {
            HangWatch::sink.store(hangSink,std::memory_order_release);
            if (const HANDLE thread = CreateThread(nullptr,0,&HangWatch::Thread,nullptr,0,nullptr)) CloseHandle(thread);
        }
    } catch (...) {}
}
inline void ConsumerFrame() noexcept
{ if (Enabled()) Detail::consumerFrames.fetch_add(1,std::memory_order_relaxed); }
inline void AddDescriptorCopy(uint64_t descriptors) noexcept
{
    if (!Enabled()) return;
    if (auto* block = Detail::Block()) { Detail::Add(block->descriptorsCopied,descriptors); Detail::Add(block->copyCalls,1); }
}
inline void AddLockWait(size_t kind, uint64_t ticks) noexcept
{
    if (!Enabled()) return;
    if (auto* block = Detail::Block())
    {
        const auto slot = kind < LockKinds ? kind : LockKinds-1;
        Detail::Add(block->lockTicks[slot],ticks); Detail::Add(block->lockEvents[slot],1);
    }
}
inline void AddWait(WaitKind kind, uint64_t ticks) noexcept
{
    if (!Enabled()) return;
    if (auto* block = Detail::Block())
    {
        Detail::Add(block->kindTicks[size_t(kind)],ticks); Detail::Add(block->kindEvents[size_t(kind)],1);
        if (Detail::currentHook < size_t(Hook::Count)) Detail::Add(block->waitTicks[Detail::currentHook],ticks);
    }
}
// Measures a nested part of a hook (survey bookkeeping, base OptiScaler work, native call).
class SubScope
{
    Sub sub_; uint64_t start_ = 0;
  public:
    explicit SubScope(Sub sub) noexcept : sub_(sub) { if (Enabled()) start_ = __rdtsc(); }
    ~SubScope()
    {
        if (!start_) return;
        const uint64_t end = __rdtsc();
        if (auto* block = Detail::Block())
        { Detail::Add(block->subTicks[size_t(sub_)],end > start_ ? end-start_ : 0); Detail::Add(block->subCalls[size_t(sub_)],1); }
    }
    SubScope(const SubScope&) = delete;
    SubScope& operator=(const SubScope&) = delete;
};
// Outermost external hook only; nested hooks on the same thread are part of it.
class HookScope
{
    size_t hook_ = size_t(Hook::Count), previous_ = size_t(Hook::Count); uint64_t start_ = 0;
    bool nested_ = false;
  public:
    HookScope(Hook hook, bool external) noexcept
    {
        if (!external || !Enabled()) return;
        if (Detail::depth++) { nested_ = true; return; }
        hook_ = size_t(hook); previous_ = Detail::currentHook; Detail::currentHook = hook_; start_ = __rdtsc();
        if (auto* block = Detail::Block())
        { block->liveHookTsc.store(start_,std::memory_order_relaxed); block->liveHook.store(uint32_t(hook_),std::memory_order_relaxed); }
    }
    ~HookScope()
    {
        if (nested_) { --Detail::depth; return; }
        if (!start_) return;
        const uint64_t end = __rdtsc();
        if (auto* block = Detail::Block())
        {
            Detail::Add(block->ticks[hook_],end > start_ ? end-start_ : 0); Detail::Add(block->calls[hook_],1);
            block->liveHook.store(UINT32_MAX,std::memory_order_relaxed);
        }
        Detail::currentHook = previous_; --Detail::depth;
        Detail::MaybeReport(end);
    }
    HookScope(const HookScope&) = delete;
    HookScope& operator=(const HookScope&) = delete;
};
}
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
    uint64_t periodicStart_ = 0;
    uint32_t previousLive_ = UINT32_MAX;
  public:
    explicit WaitScope(WaitKind kind) noexcept : kind_(kind), accumulator_(Detail::currentWaits)
    {
        if (Periodic::Enabled())
        { periodicStart_ = __rdtsc(); previousLive_ = Periodic::BeginLiveWait(100u+uint32_t(kind),periodicStart_); }
        if (accumulator_ && !QueryPerformanceCounter(&start_)) accumulator_ = nullptr;
    }
    ~WaitScope()
    {
        if (periodicStart_)
        {
            Periodic::EndLiveWait(previousLive_);
            const uint64_t end = __rdtsc();
            Periodic::AddWait(kind_,end > periodicStart_ ? end-periodicStart_ : 0);
        }
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
    // An uncontended acquisition is not a wait and is not timed.
    void lock()
    {
        if constexpr (requires(Mutex& m) { m.try_lock(); }) { if (mutex_.try_lock()) return; }
        WaitScope wait(Kind); mutex_.lock();
    }
    bool try_lock() { return mutex_.try_lock(); }
    void unlock() noexcept { mutex_.unlock(); }
};
class Scope
{
    Periodic::HookScope periodic_;
    Hook hook_;
    LARGE_INTEGER start_ {};
    bool active_ = false, entered_ = false;
    std::array<uint64_t,size_t(WaitKind::Count)> waits_ {};
    std::array<uint64_t,size_t(WaitKind::Count)>* previousWaits_ = nullptr;
  public:
    explicit Scope(Hook hook, bool external) noexcept : periodic_(hook,external), hook_(hook)
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
