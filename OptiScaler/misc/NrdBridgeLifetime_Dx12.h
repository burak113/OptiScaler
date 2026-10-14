#pragma once
#include <cassert>
#include <atomic>
#include <mutex>
#include <shared_mutex>
#include "NrdBridgePerf_Dx12.h"

// Default gate preserves the legacy protocol. Concurrent releases are enabled
// only after generation-aware metadata retirement is installed. They share the
// physical gate; weak title CPU use takes it exclusively. Native COM never runs
// under a per-object metadata lock.
namespace NrdBridgeLifetime
{
namespace Detail
{
inline std::shared_mutex& Mutex()
{
    static auto* mutex = new std::shared_mutex; // Process lifetime, including teardown hooks.
    return *mutex;
}
inline std::atomic<bool> concurrentReleases {false};
inline thread_local unsigned borrowDepth = 0, releaseDepth = 0;
}
inline bool ConcurrentReleasesEnabled() noexcept
{ return Detail::concurrentReleases.load(std::memory_order_acquire); }
inline bool EnableConcurrentReleases() noexcept
{
    if (Detail::borrowDepth || Detail::releaseDepth) return false;
    try
    {
        std::unique_lock gate(Detail::Mutex());
        Detail::concurrentReleases.store(true,std::memory_order_release);
        return true;
    }
    catch (...) { return false; }
}
class ScopedBorrow
{
    bool active_ = false, acquired_ = true;
    std::shared_lock<std::shared_mutex> legacyLock_;
    std::unique_lock<std::shared_mutex> exclusiveLock_;
  public:
    explicit ScopedBorrow(bool enabled = true)
    {
        if (!enabled) return;
        if (!Detail::borrowDepth && Detail::releaseDepth && ConcurrentReleasesEnabled())
        {
            // Upgrading an outer shared Release deadlocks. Weak CPU callers must
            // skip their optional bridge work; the original title call continues.
            acquired_ = false; return;
        }
        if (!Detail::borrowDepth && !Detail::releaseDepth)
        {
            NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::LifetimeGate);
            if (ConcurrentReleasesEnabled()) exclusiveLock_ = std::unique_lock(Detail::Mutex());
            else
            {
                legacyLock_ = std::shared_lock(Detail::Mutex());
                // A borrower may have queued before bootstrap switched modes.
                // Recheck AFTER acquiring: an old shared borrow cannot overlap
                // newly enabled shared Releases.
                if (ConcurrentReleasesEnabled())
                { legacyLock_.unlock(); exclusiveLock_ = std::unique_lock(Detail::Mutex()); }
            }
        }
        ++Detail::borrowDepth; active_ = true;
    }
    bool Acquired() const noexcept { return acquired_; }
    ~ScopedBorrow() { if (active_) --Detail::borrowDepth; }
    ScopedBorrow(const ScopedBorrow&) = delete;
    ScopedBorrow& operator=(const ScopedBorrow&) = delete;
};
class ScopedRelease
{
    bool active_ = false;
    std::unique_lock<std::shared_mutex> legacyLock_;
    std::shared_lock<std::shared_mutex> sharedLock_;
  public:
    explicit ScopedRelease(bool enabled)
    {
        if (!enabled) return; // Startup OFF has no allocation or registry access.
        if (!Detail::releaseDepth)
        {
            const bool concurrent = ConcurrentReleasesEnabled();
            if (Detail::borrowDepth && concurrent)
            {
                // A transient canonical-interface Release on this thread is
                // already protected by its exclusive borrow. Birth retirement
                // still invalidates any genuinely dying object's weak metadata.
            }
            else
            {
                assert(!Detail::borrowDepth && "Owned releases inside a legacy borrow must be internal");
                NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::LifetimeGate);
                if (concurrent) sharedLock_ = std::shared_lock(Detail::Mutex());
                else legacyLock_ = std::unique_lock(Detail::Mutex());
            }
        }
        ++Detail::releaseDepth; active_ = true;
    }
    ~ScopedRelease() { if (active_) --Detail::releaseDepth; }
    ScopedRelease(const ScopedRelease&) = delete;
    ScopedRelease& operator=(const ScopedRelease&) = delete;
};
}
