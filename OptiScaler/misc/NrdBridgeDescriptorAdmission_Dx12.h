#pragma once
#include <windows.h>
#include <array>
#include <atomic>
#include <cstdint>
#include "NrdBridgePerf_Dx12.h"
#pragma comment(lib,"Synchronization.lib")

// Native descriptor writes and their metadata publication form one transaction.
// A participant queue submission closes this gate before validating retained
// descriptor witnesses, and keeps it closed through the actual Execute call.
// The normal writer path has two atomic RMWs and no mutex, allocation or QPC.
namespace NrdBridgeDescriptorAdmission
{
namespace Detail
{
static_assert(std::atomic<uint32_t>::is_always_lock_free);
static_assert(sizeof(std::atomic<uint32_t>)==sizeof(uint32_t));
struct alignas(64) Counter { std::atomic<uint32_t> value {0}; };
inline std::array<Counter,64> writers;
inline Counter gate;
inline std::atomic<bool> healthy {true};
inline thread_local uint32_t mutationDepth = 0, submissionDepth = 0;
inline uint32_t WriterShard() noexcept
{
    static thread_local const uint32_t shard=[]() noexcept {
        uint32_t value=GetCurrentThreadId();
        value^=value>>16; value*=0x7feb352du; value^=value>>15;
        value*=0x846ca68bu; value^=value>>16;
        return value&63u;
    }();
    return shard;
}

inline void Violation() noexcept
{
    healthy.store(false,std::memory_order_release);
    // A failed/reentrant participant must also release sleepers so that failure
    // is reported rather than waiting forever on an unrelated active writer.
    WakeByAddressAll(&gate.value);
    for (auto& shard:writers) WakeByAddressAll(&shard.value);
}
inline void Pause(std::atomic<uint32_t>& value,uint32_t expected) noexcept
{
    // A value change before WaitOnAddress is observed by its comparison. All
    // last-writer/gate releases wake potential waiters. The bounded fallback
    // also observes a failure published just before this thread starts waiting
    // (healthy is a separate address, so its wake alone cannot prevent a race).
    if (!WaitOnAddress(&value,&expected,sizeof(expected),20) && GetLastError()!=ERROR_TIMEOUT) Violation();
}
inline bool WaitForOpen() noexcept
{
    if (!gate.value.load(std::memory_order_acquire)) return true;
    NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::DescriptorAdmission);
    while (gate.value.load(std::memory_order_acquire))
    {
        if (!healthy.load(std::memory_order_acquire)) return false;
        Pause(gate.value,1);
    }
    return healthy.load(std::memory_order_acquire);
}
inline void LeaveWriter(uint32_t shard) noexcept
{
    auto& counter=writers[shard].value;
    if (counter.fetch_sub(1,std::memory_order_seq_cst)==1 && gate.value.load(std::memory_order_seq_cst))
        WakeByAddressAll(&counter);
}
}
inline bool Healthy() noexcept { return Detail::healthy.load(std::memory_order_acquire); }
inline bool SubmissionHeldByCurrentThread() noexcept { return Detail::submissionDepth!=0; }

class Mutation
{
    bool outer_ = false, entered_ = false, acquired_ = true;
    uint32_t shard_ = 0;
  public:
    explicit Mutation(bool enabled) noexcept
    {
        if (!enabled) return;
        if (Detail::submissionDepth)
        {
            // Never deadlock a provider/decorator that unexpectedly mutates a
            // descriptor on the submitting thread. Its original API still runs;
            // the hook must latch failure, and no later batch may be admitted.
            Detail::Violation(); acquired_=false; return;
        }
        if (Detail::mutationDepth) { ++Detail::mutationDepth; entered_=true; return; }
        shard_=Detail::WriterShard();
        for (;;)
        {
            if (!Healthy() || !Detail::WaitForOpen()) { acquired_=false; return; }
            Detail::writers[shard_].value.fetch_add(1,std::memory_order_seq_cst);
            // The second read closes the entry race with the submitter's CAS.
            // A writer that lost the race withdraws BEFORE its native API runs.
            // Sequential consistency forbids both the writer and the draining
            // submitter observing the pre-entry values on different atomics.
            if (!Detail::gate.value.load(std::memory_order_seq_cst)) break;
            Detail::LeaveWriter(shard_);
        }
        ++Detail::mutationDepth; entered_=outer_=true;
    }
    ~Mutation()
    {
        if (!entered_) return;
        --Detail::mutationDepth;
        if (outer_) Detail::LeaveWriter(shard_);
    }
    bool Acquired() const noexcept { return acquired_ && Healthy(); }
    Mutation(const Mutation&)=delete;
    Mutation& operator=(const Mutation&)=delete;
};

class Submission
{
    bool outer_ = false, entered_ = false, acquired_ = true;
  public:
    explicit Submission(bool enabled) noexcept
    {
        if (!enabled) return;
        if (Detail::mutationDepth || !Healthy()) { Detail::Violation(); acquired_=false; return; }
        if (Detail::submissionDepth) { ++Detail::submissionDepth; entered_=true; return; }
        for (;;)
        {
            uint32_t expected=0;
            if (Detail::gate.value.compare_exchange_weak(expected,1,std::memory_order_seq_cst)) break;
            if (!Detail::WaitForOpen()) { acquired_=false; return; }
        }
        ++Detail::submissionDepth; entered_=outer_=true;
        // A closed gate prevents new native mutations. Drain every fixed shard;
        // this is 64 counters, independent of resource/heap/descriptor counts.
        for (auto& shard:Detail::writers)
        {
            auto active=shard.value.load(std::memory_order_seq_cst);
            if (!active) continue;
            NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::DescriptorAdmission);
            do
            {
                Detail::Pause(shard.value,active);
                if (!Healthy()) { acquired_=false; return; }
                active=shard.value.load(std::memory_order_seq_cst);
            } while(active);
        }
        acquired_=Healthy();
    }
    ~Submission()
    {
        if (!entered_) return;
        --Detail::submissionDepth;
        if (outer_)
        {
            Detail::gate.value.store(0,std::memory_order_seq_cst);
            WakeByAddressAll(&Detail::gate.value);
        }
    }
    bool Acquired() const noexcept { return acquired_ && Healthy(); }
    Submission(const Submission&)=delete;
    Submission& operator=(const Submission&)=delete;
};
}
