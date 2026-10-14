#pragma once

#include "NrdBridgePerf_Dx12.h"

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <map>
#include <mutex>
#include <optional>
#include <unordered_map>

// This registry owns metadata only. It never retains or dereferences a title COM
// object. Native calls, notifications and destruction of detached owned state
// MUST run outside CurrentGuard and the detach/publish callbacks below.
namespace NrdBridgeBirth
{
class Registry;
class CurrentGuard;
class Birth;
class ScopedRelease;
using Token = std::shared_ptr<const Birth>;
using MetadataAction = bool (*)(void* state, const Token& birth) noexcept;
struct MetadataActions
{
    MetadataAction detachOld = nullptr, publish = nullptr;
    void* state = nullptr; // Stable dispatcher; caller/TLS owns per-call retirement effects.
};
struct AliasSnapshot
{
    static constexpr size_t Capacity = 64;
    std::array<Token, Capacity> tokens {};
    size_t count = 0;
    bool complete = false;
    // Reuse/reset only outside metadata/index guards. Tokens contain no COM owner.
    void Reset() noexcept
    {
        for (auto& alias : tokens) alias.reset();
        count = 0; complete = false;
    }
};

namespace Detail
{
inline thread_local const void* heldShard = nullptr;
inline thread_local unsigned scopeDepth = 0, actionDepth = 0;
inline std::atomic<uint64_t> nextSequence {1};
inline std::atomic<uint64_t> nextInstanceStamp {1};
inline std::atomic<unsigned> constructedRegistries {0};
inline uint64_t AllocateMonotonic(std::atomic<uint64_t>& counter) noexcept
{
    auto value = counter.load(std::memory_order_relaxed);
    for (unsigned attempt = 0; attempt != 32 && value && value != UINT64_MAX; ++attempt)
        if (counter.compare_exchange_weak(value, value + 1, std::memory_order_relaxed)) return value;
    return 0; // Exhaustion or exceptional contention fails closed; never wraps/reuses an ID.
}
template<class Mutex> inline void AcquireMetadata(std::unique_lock<Mutex>& lock)
{
    NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Metadata);
    lock.lock(); // Profile only acquisition, never protected callbacks/native work.
}
}

inline bool InMetadataScope() noexcept { return Detail::scopeDepth != 0; }
inline bool InMetadataAction() noexcept { return Detail::actionDepth != 0; }

// This is process-lifetime metadata identity, never a COM refcount or pointer.
// The native helper combines it with its reserved process GUID/nonce protocol.
inline uint64_t AllocateInstanceStamp() noexcept
{
    return Detail::AllocateMonotonic(Detail::nextInstanceStamp);
}

class PhysicalInstance
{
    friend class Registry;
    friend class CurrentGuard;
    friend class ScopedRelease;
    const uint64_t stamp_;
    mutable std::atomic<uint32_t> releasesInFlight_ {0};
    mutable std::mutex aliasesMutex_;
    mutable std::unordered_map<void*, std::weak_ptr<const Birth>> aliases_;
    bool Remember(const Token& token) noexcept;
    bool Forget(const Token& token) noexcept;
  public:
    explicit PhysicalInstance(uint64_t stamp) noexcept : stamp_(stamp) {}
    uint64_t Stamp() const noexcept { return stamp_; }
    uint32_t ReleasesInFlight() const noexcept
    { return releasesInFlight_.load(std::memory_order_acquire); }
    // No custom deleter, registry mutation, COM call or lock on destruction.
};

class Birth
{
    friend class Registry;
    friend class CurrentGuard;
    friend class ScopedRelease;
    Registry* const registry_;
    void* const address_;
    const uint64_t sequence_, instanceStamp_;
    const std::shared_ptr<PhysicalInstance> physical_;
    mutable std::atomic<bool> live_ {true};
    mutable std::atomic<bool> initializing_ {false}, failed_ {false};
  public:
    Birth(Registry* registry, void* address, uint64_t sequence, uint64_t instanceStamp,
          std::shared_ptr<PhysicalInstance> physical,
          bool initializing = false) noexcept
        : registry_(registry), address_(address), sequence_(sequence), instanceStamp_(instanceStamp),
          physical_(std::move(physical)),
          initializing_(initializing) {}
    void* Address() const noexcept { return address_; }
    uint64_t Sequence() const noexcept { return sequence_; }
    uint64_t InstanceStamp() const noexcept { return instanceStamp_; }
    bool Live() const noexcept { return live_.load(std::memory_order_acquire); }
    bool Initializing() const noexcept { return initializing_.load(std::memory_order_acquire); }
    bool Failed() const noexcept { return failed_.load(std::memory_order_acquire); }
    bool Ready() const noexcept { return !Initializing() && !Failed(); }
    bool Admissible() const noexcept { return Live() && Ready(); }
    uint32_t ReleasesInFlight() const noexcept { return physical_->ReleasesInFlight(); }
    bool CacheAdmissible() const noexcept;
};

inline bool PhysicalInstance::Remember(const Token& token) noexcept
{
    try
    {
        std::unique_lock lock(aliasesMutex_, std::defer_lock); Detail::AcquireMetadata(lock);
        // Per-native-instance weak slots only. Expired slots are bounded by the
        // same cap, never searched through the global resource/instance catalog.
        for (auto found = aliases_.begin(); found != aliases_.end();)
            if (found->second.expired()) found = aliases_.erase(found); else ++found;
        const auto found = aliases_.find(token->Address());
        if (found == aliases_.end() && aliases_.size() == AliasSnapshot::Capacity) return false;
        aliases_[token->Address()] = token;
        return true;
    }
    catch (...) { return false; }
}
inline bool PhysicalInstance::Forget(const Token& token) noexcept
{
    try
    {
        std::unique_lock lock(aliasesMutex_, std::defer_lock); Detail::AcquireMetadata(lock);
        const auto found = aliases_.find(token->Address());
        if (found != aliases_.end() && found->second.lock() == token) aliases_.erase(found);
        return true;
    }
    catch (...) { return false; }
}

class Registry
{
    friend class CurrentGuard;
  public:
    static constexpr size_t ShardCount = 64;
  private:
    struct Shard
    {
        std::recursive_mutex mutex;
        std::unordered_map<void*, Token> live;
    };
    struct PhysicalShard
    {
        std::mutex mutex;
        std::map<uint64_t, std::weak_ptr<PhysicalInstance>> instances;
        uint64_t pruneCursor = 0;
    };
    std::array<Shard, ShardCount> shards_;
    std::array<PhysicalShard, ShardCount> physicalShards_;
    std::atomic<bool> healthy_ {true};
    std::atomic<unsigned> actionsState_ {0}; // 0 unset, 1 registering, 2 immutable ready.
    MetadataActions actions_;

    std::shared_ptr<PhysicalInstance> Physical(uint64_t stamp) noexcept
    {
        // Cold publication only. Never hold an address shard while taking this
        // lock, and never scan this map or touch it on the Release hot path.
        if (InMetadataScope()) { Fail(); return {}; }
        try
        {
            auto& shard = physicalShards_[size_t(stamp) & (ShardCount - 1)];
            std::unique_lock lock(shard.mutex, std::defer_lock); Detail::AcquireMetadata(lock);
            // A bounded ordered cursor removes expired weak entries at cold
            // births. Erasing a weak entry destroys no Birth/PhysicalInstance.
            for (unsigned visited = 0; visited != 8 && !shard.instances.empty(); ++visited)
            {
                auto entry = shard.instances.upper_bound(shard.pruneCursor);
                if (entry == shard.instances.end()) entry = shard.instances.begin();
                shard.pruneCursor = entry->first;
                if (entry->second.expired()) shard.instances.erase(entry);
            }
            const auto found = shard.instances.find(stamp);
            if (found != shard.instances.end())
                if (auto existing = found->second.lock()) return existing;
            auto fresh = std::make_shared<PhysicalInstance>(stamp);
            shard.instances[stamp] = fresh;
            return fresh;
        }
        catch (...) { Fail(); return {}; }
    }

    class Lock
    {
        Registry& registry_;
        const void* shard_ = nullptr;
        std::unique_lock<std::recursive_mutex> lock_;
      public:
        bool accepted = false;
        Lock(Registry& registry, Shard& shard) noexcept : registry_(registry)
        {
            // Recursive access to the SAME metadata shard is permitted. Waiting
            // for another shard while a callback holds this one would permit ABBA.
            if (Detail::heldShard && Detail::heldShard != &shard)
            { registry_.Fail(); return; }
            try
            {
                lock_ = std::unique_lock<std::recursive_mutex>(shard.mutex, std::defer_lock);
                Detail::AcquireMetadata(lock_);
                shard_ = &shard; Detail::heldShard = shard_; ++Detail::scopeDepth;
                accepted = true;
            }
            catch (...) { registry_.Fail(); }
        }
        ~Lock()
        {
            if (accepted && !--Detail::scopeDepth) Detail::heldShard = nullptr;
        }
    };

    bool Action(MetadataAction action, void* state, const Token& token) noexcept
    {
        if (!action) { Fail(); return false; }
        ++Detail::actionDepth;
        const bool success = action(state, token);
        --Detail::actionDepth;
        if (!success) Fail();
        return success && Healthy();
    }
  public:
    Registry() noexcept { Detail::constructedRegistries.fetch_add(1, std::memory_order_relaxed); }
    // A Registry must outlive every operation using its tokens/guards. The production registry
    // below has process lifetime; holding a Token holds no COM reference.
    Registry(const Registry&) = delete;
    Registry& operator=(const Registry&) = delete;
    bool Healthy() const noexcept { return healthy_.load(std::memory_order_acquire); }
    void Fail() noexcept { healthy_.store(false, std::memory_order_release); }
    bool ConfigureActions(MetadataActions actions) noexcept
    {
        if (!actions.detachOld || !actions.publish || InMetadataScope()) { Fail(); return false; }
        unsigned expected = 0;
        if (!actionsState_.compare_exchange_strong(expected, 1, std::memory_order_acq_rel))
        {
            const bool same = expected == 2 && actions_.detachOld == actions.detachOld &&
                              actions_.publish == actions.publish && actions_.state == actions.state;
            if (!same) Fail();
            return same;
        }
        actions_ = actions;
        actionsState_.store(2, std::memory_order_release);
        return true;
    }
    MetadataActions Actions() noexcept
    {
        if (actionsState_.load(std::memory_order_acquire) == 2) return actions_;
        Fail(); return {}; // No silent no-op detach of another component's old metadata.
    }
    static size_t ShardIndex(void* address) noexcept
    {
        uint64_t value = uint64_t(reinterpret_cast<uintptr_t>(address));
        value ^= value >> 33; value *= 0xff51afd7ed558ccdull;
        value ^= value >> 33;
        return size_t(value) & (ShardCount - 1);
    }
    Token Capture(void* address, bool enabled = true) noexcept
    {
        if (!enabled || !address) return {};
        auto& shard = shards_[ShardIndex(address)]; Lock lock(*this, shard);
        if (!lock.accepted) return {};
        const auto found = shard.live.find(address);
        return found == shard.live.end() ? Token{} : found->second;
    }
    bool ObserveExisting(const Token& token, bool enabled = true) noexcept;
    bool ObserveInitializing(const Token& token, bool capturedInitializing, bool enabled = true) noexcept;
    bool Finalize(const Token& token, bool success, bool enabled = true) noexcept;
    bool RetireCurrentInstance(const Token& ticket, MetadataAction detachOld,
                               void* state, bool enabled = true) noexcept;
    bool CaptureProvenAliasesForFinalZero(const Token& ticket, AliasSnapshot& snapshot,
                                         bool enabled = true) noexcept;
    size_t RetireProvenAliases(const AliasSnapshot& snapshot, MetadataAction detachOld,
                              void* state, bool enabled = true) noexcept;

    // instanceStamp must identify the ACTUAL native instance, not just its
    // pointer, root bytes, shader hash, creation-observer invocation or TTL.
    // Re-observing an interned root/loaded PSO with the same live stamp preserves
    // its token. An authoritative fresh instance supplies a new nonzero stamp.
    // Compute GetDesc/GetPrivateData/etc. before calling this function. Both
    // actions are POD-only: move detached owners into caller storage and deliver
    // birth-aware notifications after this function returns. A raw-address late
    // notification must never erase a newer role/list/binding.
    Token ObserveInstance(void* address, uint64_t instanceStamp, MetadataAction detachOld,
                          MetadataAction publish, void* state, bool enabled = true,
                          bool initializing = false) noexcept
    {
        if (!enabled || !address) return {};
        if (!instanceStamp || !detachOld || !publish || Detail::actionDepth)
        { Fail(); return {}; }
        if (!Healthy()) return {};
        auto physical = Physical(instanceStamp);
        if (!physical) return {};
        auto& shard = shards_[ShardIndex(address)]; Lock lock(*this, shard);
        if (!lock.accepted || !Healthy()) return {};
        auto found = shard.live.find(address);
        if (found != shard.live.end() && found->second->Live() &&
            found->second->InstanceStamp() == instanceStamp)
        {
            const auto existing = found->second;
            return Action(publish, state, existing) ? existing : Token{};
        }
        try
        {
            const auto sequence = Detail::AllocateMonotonic(Detail::nextSequence);
            if (!sequence) { Fail(); return {}; }
            // Allocate before detaching the old instance; an allocation failure
            // cannot leave a half-published fresh birth or drop any owned state.
            Token fresh = std::make_shared<Birth>(this, address, sequence, instanceStamp,
                                                std::move(physical), initializing);
            if (!fresh->physical_->Remember(fresh)) { Fail(); return {}; }
            if (found != shard.live.end())
            {
                const auto old = found->second;
                old->live_.store(false, std::memory_order_release);
                if (!old->physical_->Forget(old)) Fail();
                const bool detached = Action(detachOld, state, old);
                shard.live.erase(found);
                if (!detached)
                { fresh->live_.store(false, std::memory_order_release); fresh->physical_->Forget(fresh); return {}; }
            }
            shard.live.emplace(address, fresh);
            if (!Action(publish, state, fresh))
            {
                fresh->live_.store(false, std::memory_order_release); fresh->physical_->Forget(fresh);
                shard.live.erase(address); return {};
            }
            return fresh;
        }
        catch (...) { Fail(); return {}; }
    }
    Token PublishFresh(void* address, uint64_t instanceStamp, MetadataAction detachOld,
                       MetadataAction publish, void* state, bool enabled = true) noexcept
    { return ObserveInstance(address, instanceStamp, detachOld, publish, state, enabled); }
    // Nonblocking first-stamp election. expected==nil is an exact comparison too.
    // Native Get/SetPrivateData happens outside this call. A lost comparison is a
    // normal retry result (nil), not a health failure. The elected candidate stays
    // inadmissible until Finalize; a stale zero read can reuse ONLY a still-current
    // candidate whose initializing flag was captured before the native read.
    Token ComparePublish(void* address, const Token& expected, uint64_t instanceStamp,
                         MetadataAction detachOld, MetadataAction publish, void* state,
                         bool enabled = true) noexcept
    {
        if (!enabled || !address) return {};
        if (!instanceStamp || !detachOld || !publish || Detail::actionDepth ||
            (expected && (expected->registry_ != this || expected->Address() != address)))
        { Fail(); return {}; }
        if (!Healthy()) return {};
        // Resolve the physical metadata before taking the address shard. An old
        // pre-retired ticket still pins this same-stamp release counter.
        auto physical = Physical(instanceStamp);
        if (!physical) return {};
        auto& shard = shards_[ShardIndex(address)]; Lock lock(*this, shard);
        if (!lock.accepted || !Healthy()) return {};
        const auto found = shard.live.find(address);
        const Token current = found == shard.live.end() ? Token{} : found->second;
        if (current != expected) return {};
        if (current && current->Live() && current->InstanceStamp() == instanceStamp)
        { Fail(); return {}; } // Elect a unique native stamp; do not restart a live initializer.
        try
        {
            const auto sequence = Detail::AllocateMonotonic(Detail::nextSequence);
            if (!sequence) { Fail(); return {}; }
            Token fresh = std::make_shared<Birth>(this, address, sequence, instanceStamp,
                                                std::move(physical), true);
            if (!fresh->physical_->Remember(fresh)) { Fail(); return {}; }
            if (current)
            {
                current->live_.store(false, std::memory_order_release);
                if (!current->physical_->Forget(current)) Fail();
                const bool detached = Action(detachOld, state, current);
                shard.live.erase(address);
                if (!detached)
                { fresh->live_.store(false, std::memory_order_release); fresh->physical_->Forget(fresh); return {}; }
            }
            shard.live.emplace(address, fresh);
            if (!Action(publish, state, fresh))
            {
                fresh->live_.store(false, std::memory_order_release); fresh->physical_->Forget(fresh);
                shard.live.erase(address); return {};
            }
            return fresh;
        }
        catch (...) { Fail(); return {}; }
    }
    size_t LiveCountForTesting() noexcept
    {
        size_t count = 0;
        for (auto& shard : shards_)
        { Lock lock(*this, shard); if (!lock.accepted) return 0; count += shard.live.size(); }
        return count;
    }
    size_t WeakPhysicalCountForTesting() noexcept
    {
        if (InMetadataScope()) { Fail(); return 0; }
        size_t count = 0;
        for (auto& shard : physicalShards_)
        { std::unique_lock lock(shard.mutex, std::defer_lock); Detail::AcquireMetadata(lock); count += shard.instances.size(); }
        return count;
    }
};

inline bool Birth::CacheAdmissible() const noexcept
{ return registry_->Healthy() && Admissible() && ReleasesInFlight() == 0; }
inline bool CacheAdmissible(const Token& token) noexcept
{ return token && token->CacheAdmissible(); }

class ScopedRelease
{
    Token token_;
    bool counted_ = false;
  public:
    explicit ScopedRelease(const Token& token, bool enabled = true) noexcept : token_(enabled ? token : Token{})
    {
        if (!token_) return;
        // Starts BEFORE the existing native temporary probe. Keep this scope
        // through native caller Release and both pre/post metadata retirements.
        // Independent and cross-nested native releases take no registry lock.
        const auto before = token_->physical_->releasesInFlight_.fetch_add(1, std::memory_order_acq_rel);
        counted_ = true;
        if (before == UINT32_MAX) token_->registry_->Fail();
    }
    ~ScopedRelease()
    {
        if (counted_) token_->physical_->releasesInFlight_.fetch_sub(1, std::memory_order_release);
    }
    ScopedRelease(const ScopedRelease&) = delete;
    ScopedRelease& operator=(const ScopedRelease&) = delete;
    const Token& Ticket() const noexcept { return token_; }
};

class CurrentGuard
{
    Token token_;
    Registry* registry_ = nullptr;
    Registry::Shard* shard_ = nullptr;
    std::optional<Registry::Lock> lock_;
  public:
    explicit CurrentGuard(const Token& token, bool enabled = true) noexcept : token_(token)
    {
        if (!enabled || !token_) return;
        registry_ = token_->registry_;
        shard_ = &registry_->shards_[Registry::ShardIndex(token_->Address())];
        try { lock_.emplace(*registry_, *shard_); }
        catch (...) { registry_->Fail(); }
    }
    CurrentGuard(const CurrentGuard&) = delete;
    CurrentGuard& operator=(const CurrentGuard&) = delete;
    bool MatchesCurrent() const noexcept
    {
        if (!lock_ || !lock_->accepted || !token_->Live()) return false;
        const auto found = shard_->live.find(token_->Address());
        return found != shard_->live.end() && found->second == token_;
    }
    bool AdmitsBorrow() const noexcept { return MatchesCurrent() && token_->CacheAdmissible(); }
    // True means this call detached/retired the current birth. False is an
    // idempotent old/unknown/disabled ticket, unless Healthy() was latched false.
    // Use this for exact pre<=1 retirement. Actual native result0 MUST instead
    // call RetireCurrentInstance, including missed probes/new same-stamp sequences.
    bool Retire(MetadataAction detachOld, void* state) noexcept
    {
        if (!MatchesCurrent()) return false;
        if (!detachOld || Detail::actionDepth) { registry_->Fail(); return false; }
        token_->live_.store(false, std::memory_order_release);
        if (!token_->physical_->Forget(token_)) registry_->Fail();
        const bool detached = registry_->Action(detachOld, state, token_);
        const auto found = shard_->live.find(token_->Address());
        if (found != shard_->live.end() && found->second == token_) shard_->live.erase(found);
        return detached;
    }
    bool Retire() noexcept
    {
        if (!registry_) return false;
        const auto actions = registry_->Actions(); return Retire(actions.detachOld, actions.state);
    }
};

inline bool Registry::ObserveExisting(const Token& token, bool enabled) noexcept
{
    if (!enabled || !token || token->registry_ != this) return false;
    CurrentGuard guard(token); return Healthy() && guard.MatchesCurrent();
}
inline bool Registry::ObserveInitializing(const Token& token, bool capturedInitializing, bool enabled) noexcept
{
    if (!enabled || !capturedInitializing || !token || token->registry_ != this) return false;
    CurrentGuard guard(token); return Healthy() && guard.MatchesCurrent() && !token->Failed();
}
inline bool Registry::Finalize(const Token& token, bool success, bool enabled) noexcept
{
    if (!enabled || !token || token->registry_ != this) return false;
    if (!success)
    {
        Fail();
        token->failed_.store(true, std::memory_order_release);
        token->initializing_.store(false, std::memory_order_release);
    }
    CurrentGuard guard(token);
    if (!guard.MatchesCurrent()) return false;
    if (success && !Healthy()) return false;
    token->initializing_.store(false, std::memory_order_release);
    return success;
}
inline bool Registry::RetireCurrentInstance(const Token& ticket, MetadataAction detachOld,
                                           void* state, bool enabled) noexcept
{
    if (!enabled || !ticket || ticket->registry_ != this) return false;
    auto& shard = shards_[ShardIndex(ticket->Address())]; Lock lock(*this, shard);
    if (!lock.accepted) return false;
    const auto found = shard.live.find(ticket->Address());
    if (found == shard.live.end() || found->second->InstanceStamp() != ticket->InstanceStamp()) return false;
    // pre<=1 retires an exact logical sequence. Actual native result0 retires the
    // PHYSICAL instance, including an interned re-observation after pre-retire.
    // A genuinely recycled allocation has another stamp and survives this check.
    CurrentGuard current(found->second); return current.Retire(detachOld, state);
}
inline bool Registry::CaptureProvenAliasesForFinalZero(const Token& ticket, AliasSnapshot& snapshot,
                                                      bool enabled) noexcept
{
    if (InMetadataScope()) { Fail(); return false; }
    snapshot.Reset();
    if (!enabled || !ticket || ticket->registry_ != this) return false;
    try
    {
        // Only the caller's strong metadata physical node is touched. No address
        // shard, stamp index or callback is entered while holding aliasesMutex.
        const auto physical = ticket->physical_;
        std::unique_lock lock(physical->aliasesMutex_, std::defer_lock); Detail::AcquireMetadata(lock);
        for (const auto& entry : physical->aliases_)
        {
            auto alias = entry.second.lock();
            if (!alias || !alias->Live()) continue;
            if (alias->InstanceStamp() != ticket->InstanceStamp() || alias->registry_ != this ||
                snapshot.count == AliasSnapshot::Capacity)
            { Fail(); return false; }
            snapshot.tokens[snapshot.count++] = std::move(alias);
        }
        snapshot.complete = true;
        return true;
    }
    catch (...) { Fail(); return false; }
}
inline size_t Registry::RetireProvenAliases(const AliasSnapshot& snapshot, MetadataAction detachOld,
                                           void* state, bool enabled) noexcept
{
    if (!enabled) return 0;
    if (InMetadataScope() || !snapshot.complete || snapshot.count > AliasSnapshot::Capacity || !detachOld)
    { Fail(); return 0; }
    size_t detached = 0;
    // This staged phase holds no alias/stamp-index lock. Each addressed callback
    // sees its actual current same-GUID sequence; recycled different GUIDs survive.
    // Count reports successful callbacks; failed health still attempts every slot.
    for (size_t index = 0; index != snapshot.count; ++index)
        if (RetireCurrentInstance(snapshot.tokens[index], detachOld, state)) ++detached;
    return detached;
}
inline Registry& ProcessRegistry()
{
    static auto* registry = new Registry; // Safe for hooks during static teardown.
    return *registry;
}
inline Token Capture(void* address, bool enabled = true) noexcept
{
    if (!enabled || !address) return {};
    try { return ProcessRegistry().Capture(address); } catch (...) { return {}; }
}
inline Token ObserveInstance(void* address, uint64_t stamp, MetadataAction detachOld,
                             MetadataAction publish, void* state, bool enabled = true) noexcept
{
    if (!enabled || !address) return {};
    try { return ProcessRegistry().ObserveInstance(address, stamp, detachOld, publish, state); }
    catch (...) { return {}; }
}
inline Token PublishFresh(void* address, uint64_t stamp, MetadataAction detachOld,
                          MetadataAction publish, void* state, bool enabled = true) noexcept
{ return ObserveInstance(address, stamp, detachOld, publish, state, enabled); }
inline bool ConfigureActions(MetadataActions actions) noexcept
{
    try { return ProcessRegistry().ConfigureActions(actions); } catch (...) { return false; }
}
inline Token ObserveInstance(void* address, uint64_t stamp, bool enabled = true) noexcept
{
    if (!enabled || !address) return {};
    try
    {
        auto& registry = ProcessRegistry(); const auto actions = registry.Actions();
        return registry.ObserveInstance(address, stamp, actions.detachOld, actions.publish, actions.state);
    }
    catch (...) { return {}; }
}
inline Token PublishFresh(void* address, uint64_t stamp, bool enabled = true) noexcept
{ return ObserveInstance(address, stamp, enabled); }
inline Token LinkAlias(uint64_t stamp, void* aliasAddress, bool enabled = true) noexcept
{
    // Only a nonzero reserved native GUID stamp is alias evidence. This shares
    // physical release metadata. Actual0 snapshots every proven alias and stages
    // retirement outside the alias index. No QueryInterface or pointer inference.
    return ObserveInstance(aliasAddress, stamp, enabled);
}
inline Token ComparePublish(void* address, const Token& expected, uint64_t stamp,
                            bool enabled = true) noexcept
{
    if (!enabled || !address) return {};
    try
    {
        auto& registry = ProcessRegistry(); const auto actions = registry.Actions();
        return registry.ComparePublish(address, expected, stamp, actions.detachOld, actions.publish, actions.state);
    }
    catch (...) { return {}; }
}
inline bool ObserveExisting(const Token& token, bool enabled = true) noexcept
{
    if (!enabled || !token) return false;
    try { return ProcessRegistry().ObserveExisting(token); } catch (...) { return false; }
}
inline bool ObserveInitializing(const Token& token, bool capturedInitializing, bool enabled = true) noexcept
{
    if (!enabled || !token) return false;
    try { return ProcessRegistry().ObserveInitializing(token, capturedInitializing); } catch (...) { return false; }
}
inline bool Finalize(const Token& token, bool success, bool enabled = true) noexcept
{
    if (!enabled || !token) return false;
    try { return ProcessRegistry().Finalize(token, success); } catch (...) { return false; }
}
inline bool RetireCurrentInstance(const Token& ticket, bool enabled = true) noexcept
{
    if (!enabled || !ticket) return false;
    try
    {
        auto& registry = ProcessRegistry(); const auto actions = registry.Actions();
        return registry.RetireCurrentInstance(ticket, actions.detachOld, actions.state);
    }
    catch (...) { return false; }
}
inline bool CaptureProvenAliasesForFinalZero(const Token& ticket, AliasSnapshot& snapshot,
                                            bool enabled = true) noexcept
{
    if (!enabled || !ticket)
    {
        if (!InMetadataScope()) snapshot.Reset();
        return false;
    }
    try { return ProcessRegistry().CaptureProvenAliasesForFinalZero(ticket, snapshot); }
    catch (...) { return false; }
}
inline size_t RetireProvenAliases(const AliasSnapshot& snapshot, bool enabled = true) noexcept
{
    if (!enabled) return 0;
    try
    {
        auto& registry = ProcessRegistry(); const auto actions = registry.Actions();
        return registry.RetireProvenAliases(snapshot, actions.detachOld, actions.state);
    }
    catch (...) { return 0; }
}
inline Token ComparePublish(void* address, const Token& expected, uint64_t stamp,
                            MetadataAction detachOld, MetadataAction publish, void* state,
                            bool enabled = true) noexcept
{
    if (!enabled || !address) return {};
    try { return ProcessRegistry().ComparePublish(address, expected, stamp, detachOld, publish, state); }
    catch (...) { return {}; }
}
inline void Fail() noexcept
{
    try { ProcessRegistry().Fail(); } catch (...) {}
}
inline bool Healthy(bool enabled = true) noexcept
{
    if (!enabled) return true;
    try { return ProcessRegistry().Healthy(); } catch (...) { return false; }
}
}
