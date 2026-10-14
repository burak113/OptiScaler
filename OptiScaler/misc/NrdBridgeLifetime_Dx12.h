#pragma once
#include <cassert>
#include <mutex>
#include <shared_mutex>
#include "NrdBridgePerf_Dx12.h"

// Borrowed title objects are never retained by the bridge. Serialize physical
// final Release with their CPU use instead: borrow -> coordinator mutex, and
// exclusive release -> lease/reverse-index/registry locks. Owned-object release
// during injected/provider work must be excluded by FrameSurvey::ScopedInternal.
namespace NrdBridgeLifetime
{
namespace Detail
{
inline std::shared_mutex& Mutex()
{
    // Hooks can still run during static teardown; the gate has process lifetime.
    static auto* mutex = new std::shared_mutex;
    return *mutex;
}
inline thread_local unsigned borrowDepth = 0, releaseDepth = 0;
}

class ScopedBorrow
{
    bool active_ = false;
    std::shared_lock<std::shared_mutex> lock_;
  public:
    explicit ScopedBorrow(bool enabled = true)
    {
        if (!enabled) return;
        if (!Detail::borrowDepth && !Detail::releaseDepth)
        {
            NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::LifetimeGate);
            lock_ = std::shared_lock<std::shared_mutex>(Detail::Mutex());
        }
        ++Detail::borrowDepth;
        active_ = true;
    }
    ~ScopedBorrow() { if (active_) --Detail::borrowDepth; }
    ScopedBorrow(const ScopedBorrow&) = delete;
    ScopedBorrow& operator=(const ScopedBorrow&) = delete;
};

class ScopedRelease
{
    bool active_ = false;
    std::unique_lock<std::shared_mutex> lock_;
  public:
    explicit ScopedRelease(bool enabled)
    {
        if (!enabled) return; // Startup OFF: no allocation, registry access or lock.
        if (!Detail::releaseDepth)
        {
            assert(!Detail::borrowDepth && "Owned releases inside a borrow must be internal");
            NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::LifetimeGate);
            lock_ = std::unique_lock<std::shared_mutex>(Detail::Mutex());
        }
        ++Detail::releaseDepth;
        active_ = true;
    }
    ~ScopedRelease() { if (active_) --Detail::releaseDepth; }
    ScopedRelease(const ScopedRelease&) = delete;
    ScopedRelease& operator=(const ScopedRelease&) = delete;
};
}
