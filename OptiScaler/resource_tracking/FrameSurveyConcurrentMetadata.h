#pragma once
#include "misc/NrdBridgePerf_Dx12.h"
#include "FrameSurveyBufferRanges.h"
#include <array>
#include <intrin.h>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <memory>
#include <iterator>
#include <limits>
#include <mutex>
#include <optional>
#include <set>
#include <shared_mutex>
#include <stdexcept>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

namespace FrameSurveyMetadata
{
enum class MetadataLock : size_t { CatalogShared, CatalogExclusive, Descriptor, Identity, Range, Snapshot, Mirror, Count };
using MetadataLockTicks = std::array<uint64_t,size_t(MetadataLock::Count)>;
inline thread_local MetadataLockTicks gMetadataLockTicks {};
inline MetadataLockTicks ThreadMetadataLockTicks() noexcept { return gMetadataLockTicks; }
// Attribute the SAME WaitScope measurement, not a second QPC interval. Disabled
// outer profiling reads no accumulator and updates no counters.
class MetadataWait
{
    MetadataLock kind_;
    std::array<uint64_t,size_t(NrdBridgePerf::WaitKind::Count)>* accumulator_;
    uint64_t before_ = 0, periodicStart_ = 0;
    uint32_t previousLive_ = UINT32_MAX;
    std::optional<NrdBridgePerf::WaitScope> measured_;
  public:
    explicit MetadataWait(MetadataLock kind) noexcept : kind_(kind),accumulator_(NrdBridgePerf::Detail::currentWaits)
    {
        if (NrdBridgePerf::Periodic::Enabled()) periodicStart_ = __rdtsc();
        if (accumulator_) before_ = (*accumulator_)[size_t(NrdBridgePerf::WaitKind::Metadata)];
        measured_.emplace(NrdBridgePerf::WaitKind::Metadata);
        // After the generic WaitScope so the hang watch sees the exact lock kind.
        if (periodicStart_) previousLive_ = NrdBridgePerf::Periodic::BeginLiveWait(uint32_t(kind),periodicStart_);
    }
    ~MetadataWait()
    {
        if (periodicStart_) NrdBridgePerf::Periodic::EndLiveWait(previousLive_);
        measured_.reset();
        if (periodicStart_)
        {
            const uint64_t end = __rdtsc();
            NrdBridgePerf::Periodic::AddLockWait(size_t(kind_),end > periodicStart_ ? end-periodicStart_ : 0);
        }
        if (accumulator_) gMetadataLockTicks[size_t(kind_)] += (*accumulator_)[size_t(NrdBridgePerf::WaitKind::Metadata)]-before_;
    }
};
#ifdef FSRD_NRD_BRIDGE_TEST_HEAP_MASK
// CPU-only deterministic pause/count seam. Native benchmark and production do
// not compile this hook, so it adds no artificial timed convoy or hot branch.
struct DescriptorLockTestHook
{
    void* state = nullptr;
    void (*attempt)(void*,const void*) = nullptr;
};
inline thread_local DescriptorLockTestHook gDescriptorLockTestHook {};
#endif
// For critical sections of a few hundred nanoseconds (descriptor shards). A
// contended std::mutex parks the waiter in the kernel, and waking it costs several
// microseconds, far longer than the section it waited for; with a dozen title
// threads copying descriptors that becomes a convoy. Spin briefly with pause, then
// yield the time slice so a preempted holder can finish.
// Escalate by elapsed time (TSC cycles, ~3-4 per ns), never by a fixed round
// count: Sleep(1) can last a whole timer tick (up to ~15 ms).
template<class Attempt,class Blocked> void SpinAcquire(Attempt&& attempt,Blocked&& blocked) noexcept
{
    const uint64_t start = __rdtsc();
    for (uint32_t round=0;;++round)
    {
        if (attempt()) return;
        const uint64_t waited = __rdtsc()-start;
        if (waited < 10000) { for (uint32_t i=0, n=4u << std::min(round,4u);i<n && blocked();++i) _mm_pause(); }
        else if (waited < 1000000) { if (!SwitchToThread()) for (uint32_t i=0;i<64 && blocked();++i) _mm_pause(); }
        // A holder preempted by higher-priority spinners only runs again once
        // they really sleep; SwitchToThread/Sleep(0) never yield to lower priority.
        else if (waited < 10000000) Sleep(0);
        else Sleep(1);
    }
}
class ShortSpinMutex
{
    // Writer owns / a writer waits (new readers hold off) / reader count. Copies
    // only read their source slots, and every title thread copies from the same
    // few staging blocks: exclusive source locks made those threads queue.
    static constexpr uint32_t Writer = 1u << 31, Pending = 1u << 30;
    std::atomic<uint32_t> state_ {0};
  public:
    bool try_lock() noexcept
    {
        uint32_t current = state_.load(std::memory_order_relaxed);
        return !(current & ~Pending) && state_.compare_exchange_strong(current,Writer,std::memory_order_acquire,std::memory_order_relaxed);
    }
    void lock() noexcept
    {
        SpinAcquire([this] {
            uint32_t current = state_.load(std::memory_order_relaxed);
            if (!(current & ~Pending))
                return state_.compare_exchange_weak(current,Writer,std::memory_order_acquire,std::memory_order_relaxed);
            if (!(current & Pending)) state_.fetch_or(Pending,std::memory_order_relaxed);
            return false;
        },[this] { return (state_.load(std::memory_order_relaxed) & ~Pending) != 0; });
    }
    void unlock() noexcept { state_.fetch_and(~Writer,std::memory_order_release); }
    bool try_lock_shared() noexcept
    {
        uint32_t current = state_.load(std::memory_order_relaxed);
        return !(current & (Writer|Pending)) &&
            state_.compare_exchange_strong(current,current+1,std::memory_order_acquire,std::memory_order_relaxed);
    }
    void lock_shared() noexcept
    {
        SpinAcquire([this] {
            uint32_t current = state_.load(std::memory_order_relaxed);
            return !(current & (Writer|Pending)) &&
                state_.compare_exchange_weak(current,current+1,std::memory_order_acquire,std::memory_order_relaxed);
        },[this] { return (state_.load(std::memory_order_relaxed) & (Writer|Pending)) != 0; });
    }
    void unlock_shared() noexcept { state_.fetch_sub(1,std::memory_order_release); }
};
template<class Mutex,MetadataLock Kind> class MetadataMutex
{
    Mutex mutex_;
  public:
    void lock()
    {
#ifdef FSRD_NRD_BRIDGE_TEST_HEAP_MASK
        if constexpr (Kind == MetadataLock::Descriptor)
            if (gDescriptorLockTestHook.attempt) gDescriptorLockTestHook.attempt(gDescriptorLockTestHook.state,this);
#endif
        // Uncontended acquisitions are not waits: no timer, no counter update.
        if (mutex_.try_lock()) return;
        MetadataWait wait(Kind); mutex_.lock();
    }
    bool try_lock() { return mutex_.try_lock(); }
    void unlock() noexcept { mutex_.unlock(); }
    void lock_shared()
    {
#ifdef FSRD_NRD_BRIDGE_TEST_HEAP_MASK
        if constexpr (Kind == MetadataLock::Descriptor)
            if (gDescriptorLockTestHook.attempt) gDescriptorLockTestHook.attempt(gDescriptorLockTestHook.state,this);
#endif
        if (mutex_.try_lock_shared()) return;
        MetadataWait wait(Kind); mutex_.lock_shared();
    }
    bool try_lock_shared() { return mutex_.try_lock_shared(); }
    void unlock_shared() noexcept { mutex_.unlock_shared(); }
};
// 256 shards: with 32, a dozen title threads copying descriptors kept colliding
// on the same shard locks (benchmark: 1.5x the copy thread time of 256).
inline constexpr size_t DescriptorShards = 256;
// Shards follow 2 KiB handle blocks (32-64 adjacent descriptors), not single
// slots: a title copy run of a few adjacent descriptors then needs one source
// and one destination shard lock instead of one pair per descriptor.
inline constexpr unsigned DescriptorShardBlockBits = 11;
inline size_t DescriptorShard(uint64_t cpuHandle) noexcept
{
    const auto slot = (cpuHandle >> DescriptorShardBlockBits)*0x9e3779b97f4a7c15ull;
    return size_t(slot >> 56);
}

// Cold immutable bound for a native heap's legal descriptor positions. Never
// derive this from populated reverse buckets: a prechecked writer may be pending.
struct DescriptorShardMask
{
    std::array<uint64_t,(DescriptorShards+63)/64> words {};
    bool Contains(size_t shard) const noexcept
    { assert(shard < DescriptorShards); return (words[shard/64] & (uint64_t(1) << (shard%64))) != 0; }
    static constexpr DescriptorShardMask All() noexcept
    {
        DescriptorShardMask result;
        for (auto& word : result.words) word = std::numeric_limits<uint64_t>::max();
        if constexpr (DescriptorShards%64) result.words.back() = (uint64_t(1) << (DescriptorShards%64))-1;
        return result;
    }
    size_t Count() const noexcept
    { size_t count = 0; for (size_t shard=0;shard<DescriptorShards;++shard) count += Contains(shard); return count; }
    static DescriptorShardMask ForRange(uint64_t cpu,uint64_t count,uint64_t increment) noexcept
    {
        const auto all = All();
        const auto maximum = std::numeric_limits<uint64_t>::max();
        if (!cpu || !count || !increment || count > maximum/increment) return all;
        const auto extent = count*increment;
        if (cpu > maximum-(extent-1)) return all;
        DescriptorShardMask result;
        constexpr uint64_t slotCap = 1024;
        const auto visited = count < slotCap ? count : slotCap;
        for (uint64_t slot=0;slot<visited;++slot)
        {
            const auto shard = DescriptorShard(cpu+slot*increment);
            result.words[shard/64] |= uint64_t(1) << (shard%64);
            if (result.words == all.words) return result;
        }
        return visited < count ? all : result;
    }
};

// Catalog readers can update independent descriptor shards concurrently. Catalog
// writers drain all readers before resource/heap lifetime or recorder traversal.
// Recursive exclusive scopes preserve existing recorder/read helper contracts.
class RecursiveSharedMutex
{
    std::shared_mutex mutex_;
    bool snapshot_ = false;
    // Snapshot mode: every descriptor callback of every title thread takes this
    // lock shared, exclusive holders are rare. Readers count in a cache line of
    // their own instead of all doing atomic RMWs on the one shared_mutex word;
    // a writer serializes on mutex_, raises writer_ and drains every slot.
    struct alignas(64) ReaderSlot { std::atomic<uint32_t> count {0}; };
    static constexpr size_t ReaderSlots = 64;
    std::array<ReaderSlot,ReaderSlots> readers_ {};
    std::atomic<bool> writer_ {false};
    static ReaderSlot& SlotOf(std::array<ReaderSlot,ReaderSlots>& readers) noexcept
    {
        static std::atomic<uint32_t> next {0};
        static thread_local const uint32_t index = next.fetch_add(1,std::memory_order_relaxed)%ReaderSlots;
        return readers[index];
    }
    bool TryReadSlot() noexcept
    {
        auto& slot = SlotOf(readers_).count;
        slot.fetch_add(1,std::memory_order_seq_cst);
        if (!writer_.load(std::memory_order_seq_cst)) return true;
        slot.fetch_sub(1,std::memory_order_release);
        return false;
    }
    bool ReadersDrained() const noexcept
    {
        for (const auto& slot : readers_) if (slot.count.load(std::memory_order_seq_cst)) return false;
        return true;
    }
    void LockWriter()
    {
        mutex_.lock(); writer_.store(true,std::memory_order_seq_cst);
        SpinAcquire([this] { return ReadersDrained(); },[this] { return !ReadersDrained(); });
    }
    bool TryLockWriter()
    {
        if (!mutex_.try_lock()) return false;
        writer_.store(true,std::memory_order_seq_cst);
        if (ReadersDrained()) return true;
        writer_.store(false,std::memory_order_release); mutex_.unlock(); return false;
    }
    void UnlockWriter() noexcept { writer_.store(false,std::memory_order_release); mutex_.unlock(); }
    struct Entry { const void* owner = nullptr; unsigned exclusive = 0, shared = 0; };
    inline static thread_local std::array<Entry,8> entries_ {};
    Entry& EntryFor(bool create)
    {
        for (auto& entry : entries_) if (entry.owner == this) return entry;
        if (create) for (auto& entry : entries_) if (!entry.owner) { entry.owner = this; return entry; }
        throw std::logic_error("Metadata mutex recursion table exhausted or unmatched unlock");
    }
    static void Retire(Entry& entry) noexcept { if (!entry.exclusive && !entry.shared) entry.owner = nullptr; }
  public:
    explicit RecursiveSharedMutex(bool snapshot = false) noexcept : snapshot_(snapshot) {}
    void lock()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive) { ++entry.exclusive; return; }
        if (entry.shared) throw std::logic_error("Metadata shared-to-exclusive upgrade is forbidden");
        if (snapshot_ ? TryLockWriter() : mutex_.try_lock()) { entry.exclusive = 1; return; }
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogExclusive);
        try { if (snapshot_) LockWriter(); else mutex_.lock(); entry.exclusive = 1; } catch (...) { Retire(entry); throw; }
    }
    bool try_lock()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive) { ++entry.exclusive; return true; }
        if (entry.shared) throw std::logic_error("Metadata shared-to-exclusive upgrade is forbidden");
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogExclusive);
        if (snapshot_ ? TryLockWriter() : mutex_.try_lock()) { entry.exclusive = 1; return true; }
        Retire(entry); return false;
    }
    void unlock()
    {
        auto& entry = EntryFor(false); assert(entry.exclusive);
        if (!--entry.exclusive) { assert(!entry.shared); if (snapshot_) UnlockWriter(); else mutex_.unlock(); }
        Retire(entry);
    }
    void lock_shared()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive || entry.shared) { ++entry.shared; return; }
        if (snapshot_ ? TryReadSlot() : mutex_.try_lock_shared()) { entry.shared = 1; return; }
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogShared);
        if (snapshot_)
        {
            SpinAcquire([this] { return TryReadSlot(); },[this] { return writer_.load(std::memory_order_relaxed); });
            entry.shared = 1; return;
        }
        try { mutex_.lock_shared(); entry.shared = 1; } catch (...) { Retire(entry); throw; }
    }
    bool try_lock_shared()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive || entry.shared) { ++entry.shared; return true; }
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogShared);
        if (snapshot_ ? TryReadSlot() : mutex_.try_lock_shared()) { entry.shared = 1; return true; }
        Retire(entry); return false;
    }
    void unlock_shared()
    {
        auto& entry = EntryFor(false); assert(entry.shared);
        if (!--entry.shared && !entry.exclusive)
        {
            if (snapshot_) SlotOf(readers_).count.fetch_sub(1,std::memory_order_release);
            else mutex_.unlock_shared();
        }
        Retire(entry);
    }
};

// External synchronization: catalog exclusive, OR catalog shared plus the
// descriptor shard. No reference/iterator can outlive that external guard.
// One open-addressing table per shard with the values inline (linear probing,
// backward-shift deletion, key 0 = empty; descriptor handles are never 0). A lookup
// touches one or two adjacent cache lines instead of a bucket array plus a list node,
// which matters because the title's shader-visible rings hold hundreds of thousands
// of slots, far more than the CPU caches. Inserting may relocate a shard's entries
// and erasing may move a later entry of that shard back: no reference or iterator
// into a shard survives a mutation of that shard (other shards are unaffected).
template<class Value> class DescriptorMap
{
    using Entry = std::pair<uint64_t,Value>;
    struct Shard
    {
        std::vector<Entry> slots; size_t count = 0;
        // Lock-free prefetch hint only: may be stale; prefetching never faults.
        std::atomic<const Entry*> hintBase {nullptr}; std::atomic<size_t> hintMask {0};
        void PublishHint() noexcept
        {
            hintBase.store(slots.empty() ? nullptr : slots.data(),std::memory_order_relaxed);
            hintMask.store(slots.empty() ? 0 : slots.size()-1,std::memory_order_relaxed);
        }
    };
    std::array<Shard,DescriptorShards> shards_;
    std::atomic<size_t> size_ {0};
    static size_t Hash(uint64_t key) noexcept
    {
        key ^= key >> 33; key *= 0xff51afd7ed558ccdull; key ^= key >> 33; key *= 0xc4ceb9fe1a85ec53ull; key ^= key >> 33;
        return size_t(key);
    }
    static size_t Locate(const Shard& shard,uint64_t key) noexcept
    {
        if (!key || shard.slots.empty()) return SIZE_MAX;
        const size_t mask = shard.slots.size()-1;
        for (size_t index = Hash(key)&mask;; index = (index+1)&mask)
        {
            const uint64_t current = shard.slots[index].first;
            if (current == key) return index;
            if (!current) return SIZE_MAX;
        }
    }
    static size_t Place(std::vector<Entry>& slots,uint64_t key) noexcept
    {
        const size_t mask = slots.size()-1;
        size_t index = Hash(key)&mask;
        while (slots[index].first) index = (index+1)&mask;
        return index;
    }
    static void Reserve(Shard& shard,size_t count)
    {
        if (count*10 <= shard.slots.size()*7) return;
        size_t capacity = shard.slots.empty() ? 64 : shard.slots.size();
        while (count*10 > capacity*7) capacity *= 2;
        std::vector<Entry> grown(capacity);
        for (auto& entry : shard.slots)
            if (entry.first) { auto& target = grown[Place(grown,entry.first)]; target.second = std::move(entry.second); target.first = entry.first; }
        shard.slots.swap(grown); shard.PublishHint();
    }
    static void EraseAt(Shard& shard,size_t hole)
    {
        const size_t mask = shard.slots.size()-1;
        for (size_t next = (hole+1)&mask; shard.slots[next].first; next = (next+1)&mask)
        {
            const size_t home = Hash(shard.slots[next].first)&mask;
            // Move the entry back unless its home lies cyclically in (hole, next].
            const bool stays = hole <= next ? (home > hole && home <= next) : (home > hole || home <= next);
            if (stays) continue;
            shard.slots[hole].second = std::move(shard.slots[next].second); shard.slots[hole].first = shard.slots[next].first;
            hole = next;
        }
        shard.slots[hole].first = 0; shard.slots[hole].second = Value{};
        --shard.count;
    }
    template<bool Constant> class Iter
    {
        friend class DescriptorMap;
        using Owner = std::conditional_t<Constant,const DescriptorMap,DescriptorMap>;
        Owner* owner_ = nullptr; size_t shard_ = 0, index_ = 0;
        Iter(Owner* owner,size_t shard,size_t index) : owner_(owner),shard_(shard),index_(index) {}
        void Settle()
        {
            for (; shard_ < DescriptorShards; ++shard_, index_ = 0)
            {
                const auto& slots = owner_->shards_[shard_].slots;
                for (; index_ < slots.size(); ++index_) if (slots[index_].first) return;
            }
            owner_ = nullptr; shard_ = 0; index_ = 0;
        }
      public:
        using iterator_category = std::forward_iterator_tag;
        using value_type = Entry;
        using difference_type = std::ptrdiff_t;
        using pointer = std::conditional_t<Constant,const value_type*,value_type*>;
        using reference = std::conditional_t<Constant,const value_type&,value_type&>;
        Iter() = default;
        Iter operator++(int) { auto before = *this; ++*this; return before; }
        reference operator*() const { return owner_->shards_[shard_].slots[index_]; }
        pointer operator->() const { return std::addressof(owner_->shards_[shard_].slots[index_]); }
        bool operator==(const Iter& other) const
        { return owner_ == other.owner_ && (!owner_ || (shard_ == other.shard_ && index_ == other.index_)); }
        bool operator!=(const Iter& other) const { return !(*this == other); }
        Iter& operator++() { ++index_; Settle(); return *this; }
    };
  public:
    using iterator = Iter<false>; using const_iterator = Iter<true>;
    iterator end() noexcept { return {}; } const_iterator end() const noexcept { return {}; }
    iterator begin() { iterator it(this,0,0); it.Settle(); return it; }
    const_iterator begin() const { const_iterator it(this,0,0); it.Settle(); return it; }
    iterator find(uint64_t key)
    { const auto i = DescriptorShard(key); const auto index = Locate(shards_[i],key); return index == SIZE_MAX ? iterator{} : iterator(this,i,index); }
    const_iterator find(uint64_t key) const
    { const auto i = DescriptorShard(key); const auto index = Locate(shards_[i],key); return index == SIZE_MAX ? const_iterator{} : const_iterator(this,i,index); }
    bool contains(uint64_t key) const { return find(key) != end(); }
    template<class... Args> std::pair<iterator,bool> emplace(uint64_t key,Args&&... args)
    {
        if (!key) throw std::invalid_argument("Descriptor slot zero");
        const auto i = DescriptorShard(key); auto& shard = shards_[i];
        if (const auto index = Locate(shard,key); index != SIZE_MAX) return {iterator(this,i,index),false};
        Value value(std::forward<Args>(args)...);
        Reserve(shard,shard.count+1);
        const auto index = Place(shard.slots,key);
        shard.slots[index].second = std::move(value); shard.slots[index].first = key; ++shard.count;
        size_.fetch_add(1,std::memory_order_relaxed);
        return {iterator(this,i,index),true};
    }
    Value& operator[](uint64_t key) { return emplace(key).first->second; }
    Value& at(uint64_t key) { auto it = find(key); if (it == end()) throw std::out_of_range("Descriptor slot"); return it->second; }
    const Value& at(uint64_t key) const { auto it = find(key); if (it == end()) throw std::out_of_range("Descriptor slot"); return it->second; }
    size_t erase(uint64_t key)
    {
        auto& shard = shards_[DescriptorShard(key)]; const auto index = Locate(shard,key);
        if (index == SIZE_MAX) return 0;
        EraseAt(shard,index); size_.fetch_sub(1,std::memory_order_relaxed); return 1;
    }
    void erase(iterator it)
    { assert(it.owner_ == this); EraseAt(shards_[it.shard_],it.index_); size_.fetch_sub(1,std::memory_order_relaxed); }
    size_t size() const noexcept { return size_.load(std::memory_order_relaxed); }
    bool empty() const noexcept { return !size(); }
    void clear() { for (auto& shard : shards_) { std::vector<Entry>().swap(shard.slots); shard.count = 0; shard.PublishHint(); } size_.store(0,std::memory_order_relaxed); }
    // Starts loading a slot's cache line without any lock. Callers prefetch a whole
    // copy run so its independent memory misses overlap instead of serializing.
    void Prefetch(uint64_t key) const noexcept
    {
        const auto& shard = shards_[DescriptorShard(key)];
        if (const auto* base = shard.hintBase.load(std::memory_order_relaxed))
            _mm_prefetch(reinterpret_cast<const char*>(base+(Hash(key)&shard.hintMask.load(std::memory_order_relaxed))),_MM_HINT_T0);
    }
};

// Open-addressing set of nonzero descriptor handles (linear probing with
// backward-shift deletion, no tombstones). Inserts and erases never allocate
// per element, unlike std::set, which allocated and freed a node for every
// reverse-index change of every copied descriptor while a shard lock was held.
class FlatHandleSet
{
    std::vector<uint64_t> slots_; // 0 = empty; descriptor handles are never 0.
    size_t size_ = 0, cursor_ = 0;
    static size_t Hash(uint64_t key) noexcept
    {
        key ^= key >> 33; key *= 0xff51afd7ed558ccdull; key ^= key >> 33; key *= 0xc4ceb9fe1a85ec53ull; key ^= key >> 33;
        return size_t(key);
    }
    size_t Mask() const noexcept { return slots_.size()-1; }
    size_t Find(uint64_t key) const noexcept
    {
        if (slots_.empty()) return SIZE_MAX;
        for (size_t index = Hash(key)&Mask();; index = (index+1)&Mask())
        {
            if (slots_[index] == key) return index;
            if (!slots_[index]) return SIZE_MAX;
        }
    }
    void Place(uint64_t key) noexcept
    {
        size_t index = Hash(key)&Mask();
        while (slots_[index]) index = (index+1)&Mask();
        slots_[index] = key;
    }
    void Rehash(size_t capacity)
    {
        std::vector<uint64_t> old(capacity,0); old.swap(slots_); cursor_ = 0;
        for (const auto key : old) if (key) Place(key);
    }
    void EraseAt(size_t hole) noexcept
    {
        const size_t mask = Mask();
        for (size_t next = (hole+1)&mask; slots_[next]; next = (next+1)&mask)
        {
            const size_t home = Hash(slots_[next])&mask;
            // Move the entry back unless its home lies cyclically in (hole, next].
            const bool stays = hole <= next ? (home > hole && home <= next) : (home > hole || home <= next);
            if (!stays) { slots_[hole] = slots_[next]; hole = next; }
        }
        slots_[hole] = 0; --size_;
        if (!size_) { std::vector<uint64_t>().swap(slots_); cursor_ = 0; }
    }
  public:
    bool insert(uint64_t key)
    {
        if (!key) throw std::invalid_argument("Descriptor handle zero");
        if (Find(key) != SIZE_MAX) return false;
        if ((size_+1)*4 > slots_.size()*3) Rehash(slots_.empty() ? 16 : slots_.size()*2);
        Place(key); ++size_; return true;
    }
    size_t erase(uint64_t key) noexcept
    {
        const size_t index = Find(key); if (index == SIZE_MAX) return 0;
        EraseAt(index); return 1;
    }
    bool contains(uint64_t key) const noexcept { return Find(key) != SIZE_MAX; }
    size_t size() const noexcept { return size_; }
    bool empty() const noexcept { return !size_; }
    // Removes some element. Backward shifts only move entries into positions at
    // or after the cursor, so draining a whole set is linear in its capacity.
    bool Pop(uint64_t& key) noexcept
    {
        if (!size_) return false;
        while (!slots_[cursor_]) cursor_ = (cursor_+1)&Mask();
        key = slots_[cursor_]; EraseAt(cursor_); return true;
    }
    // Ordered access is for cold diagnostics only: linear in the capacity.
    bool Min(uint64_t& out) const noexcept
    {
        bool found = false;
        for (const auto key : slots_) if (key && (!found || key < out)) { out = key; found = true; }
        return found;
    }
    bool NextAfter(uint64_t value, uint64_t& out) const noexcept
    {
        bool found = false;
        for (const auto key : slots_) if (key > value && (!found || key < out)) { out = key; found = true; }
        return found;
    }
};

// Reverse sets use exactly the slot-map shard. Distinct slot shards never mutate
// the same set, even when every view points at one shared resource/heap.
// Buckets are grouped and allocated lazily, so a resource or heap without views
// costs one pointer per group, not one per shard. Distinct shards of a group may
// race to create it (published once by CAS); each bucket inside it still belongs
// to exactly one slot shard.
class DescriptorHandles
{
    using Set = FlatHandleSet;
    static constexpr size_t GroupShards = 8, Groups = (DescriptorShards+GroupShards-1)/GroupShards;
    struct Group { std::array<std::unique_ptr<Set>,GroupShards> sets; };
    std::array<std::atomic<Group*>,Groups> groups_ {};
    std::atomic<size_t> size_ {0};
    size_t takeShard_ = 0; // Lifecycle-only cursor, always protected by catalog exclusive.
    Set* Bucket(size_t shard) const noexcept
    {
        const auto* group = groups_[shard/GroupShards].load(std::memory_order_acquire);
        return group ? group->sets[shard%GroupShards].get() : nullptr;
    }
    Set& CreateBucket(size_t shard)
    {
        auto& slot = groups_[shard/GroupShards];
        auto* group = slot.load(std::memory_order_acquire);
        if (!group)
        {
            auto created = std::make_unique<Group>();
            if (slot.compare_exchange_strong(group,created.get(),std::memory_order_acq_rel,std::memory_order_acquire)) group = created.release();
        }
        auto& set = group->sets[shard%GroupShards];
        if (!set) set = std::make_unique<Set>();
        return *set;
    }
    void Clear() noexcept { for (auto& group : groups_) delete group.exchange(nullptr,std::memory_order_acq_rel); }
  public:
    class const_iterator
    {
        friend class DescriptorHandles;
        const DescriptorHandles* owner_ = nullptr; uint64_t value_ = 0;
        const_iterator(const DescriptorHandles* owner,uint64_t value) : owner_(owner),value_(value) {}
      public:
        using iterator_category = std::forward_iterator_tag;
        using value_type = uint64_t;
        using difference_type = std::ptrdiff_t;
        using pointer = const uint64_t*;
        using reference = const uint64_t&;
        const_iterator() = default;
        const uint64_t* operator->() const { return &value_; }
        const_iterator operator++(int) { auto before = *this; ++*this; return before; }
        const uint64_t& operator*() const { return value_; }
        bool operator==(const const_iterator& other) const { return owner_ == other.owner_ && (!owner_ || value_ == other.value_); }
        bool operator!=(const const_iterator& other) const { return !(*this == other); }
        const_iterator& operator++()
        {
            bool found = false; uint64_t next = 0;
            for (size_t shard=0;shard<DescriptorShards;++shard) if (const auto* set = owner_->Bucket(shard))
                if (uint64_t candidate = 0; set->NextAfter(value_,candidate) && (!found || candidate < next)) { next = candidate; found = true; }
            if (found) value_ = next; else owner_ = nullptr;
            return *this;
        }
    };
    DescriptorHandles() = default;
    ~DescriptorHandles() { Clear(); }
    DescriptorHandles(const DescriptorHandles& other)
    {
        try { for (size_t shard=0;shard<DescriptorShards;++shard) if (const auto* set = other.Bucket(shard)) CreateBucket(shard) = *set; }
        catch (...) { Clear(); throw; }
        size_.store(other.size(),std::memory_order_relaxed);
    }
    DescriptorHandles(DescriptorHandles&& other) noexcept : takeShard_(std::exchange(other.takeShard_,0))
    {
        for (size_t i=0;i<Groups;++i) groups_[i].store(other.groups_[i].exchange(nullptr,std::memory_order_acq_rel),std::memory_order_release);
        size_.store(other.size_.exchange(0,std::memory_order_relaxed),std::memory_order_relaxed);
    }
    DescriptorHandles& operator=(DescriptorHandles other) noexcept
    {
        for (size_t i=0;i<Groups;++i)
        {
            auto* mine = groups_[i].load(std::memory_order_acquire);
            groups_[i].store(other.groups_[i].exchange(mine,std::memory_order_acq_rel),std::memory_order_release);
        }
        std::swap(takeShard_,other.takeShard_);
        const auto size = size_.exchange(other.size(),std::memory_order_relaxed); other.size_.store(size,std::memory_order_relaxed);
        return *this;
    }
    bool insert(uint64_t key)
    {
        const bool added = CreateBucket(DescriptorShard(key)).insert(key);
        if (added) size_.fetch_add(1,std::memory_order_relaxed); return added;
    }
    size_t erase(uint64_t key)
    {
        auto* set = Bucket(DescriptorShard(key)); if (!set) return 0;
        const auto erased = set->erase(key); if (erased) size_.fetch_sub(erased,std::memory_order_relaxed); return erased;
    }
    void erase(const_iterator it) { assert(it.owner_ == this); erase(*it); }
    // Retirement order is unobservable. Drain the current bucket before seeking
    // another instead of merging every sorted bucket for each affected slot.
    bool PopAny(uint64_t& key)
    {
        if (empty()) return false;
        for (size_t offset=0;offset<DescriptorShards;++offset)
        {
            const auto index = (takeShard_+offset)&(DescriptorShards-1);
            auto* set = Bucket(index);
            if (!set || !set->Pop(key)) continue;
            size_.fetch_sub(1,std::memory_order_relaxed); takeShard_ = index; return true;
        }
        assert(false && "Reverse count disagrees with descriptor buckets"); return false;
    }
    // Native retirement holds only this exact slot shard. Other buckets may
    // still change concurrently and are never traversed from here.
    bool PopShard(size_t shard,uint64_t& key)
    {
        assert(shard < DescriptorShards); auto* set = Bucket(shard);
        if (!set || !set->Pop(key)) return false;
        size_.fetch_sub(1,std::memory_order_relaxed); return true;
    }
    bool contains(uint64_t key) const { const auto* set = Bucket(DescriptorShard(key)); return set && set->contains(key); }
    size_t size() const noexcept { return size_.load(std::memory_order_relaxed); }
    bool empty() const noexcept { return !size(); }
    const_iterator end() const noexcept { return {}; }
    const_iterator begin() const
    {
        bool found = false; uint64_t first = 0;
        for (size_t shard=0;shard<DescriptorShards;++shard)
            if (const auto* set = Bucket(shard))
                if (uint64_t candidate = 0; set->Min(candidate) && (!found || candidate < first)) { first = candidate; found = true; }
        return found ? const_iterator(this,first) : const_iterator{};
    }
};
// Native-ready pins own metadata only. No node may own a title COM reference or
// invoke external work from its destructor. Component locks end before slot locks.
template<class Key,class Node> class PinnedIdentityMap
{
    struct Shard { std::shared_mutex mutex; std::unordered_map<Key,std::shared_ptr<Node>> nodes; };
    std::array<Shard,32> shards_;
    static size_t Index(Key key) noexcept
    {
        uint64_t value = uint64_t(reinterpret_cast<uintptr_t>(key))>>4;
        value ^= value>>30; value *= 0xbf58476d1ce4e5b9ull; value ^= value>>27;
        return size_t(value)&31;
    }
  public:
    std::shared_ptr<Node> Find(Key key)
    {
        auto& shard = shards_[Index(key)];
        std::shared_lock lock(shard.mutex,std::defer_lock);
        { MetadataWait wait(MetadataLock::Identity); lock.lock(); }
        const auto found = shard.nodes.find(key);
        return found == shard.nodes.end() ? std::shared_ptr<Node>{} : found->second;
    }
    std::shared_ptr<Node> Insert(Key key,const std::shared_ptr<Node>& node)
    {
        auto& shard = shards_[Index(key)];
        std::unique_lock lock(shard.mutex,std::defer_lock);
        { MetadataWait wait(MetadataLock::Identity); lock.lock(); }
        return shard.nodes.try_emplace(key,node).first->second;
    }
    template<class Predicate> std::shared_ptr<Node> EraseIf(Key key,Predicate matches)
    {
        auto& shard = shards_[Index(key)];
        std::unique_lock lock(shard.mutex,std::defer_lock);
        { MetadataWait wait(MetadataLock::Identity); lock.lock(); }
        const auto found = shard.nodes.find(key);
        if (found == shard.nodes.end() || !matches(*found->second)) return {};
        auto result = std::move(found->second); shard.nodes.erase(found); return result;
    }
    size_t Size()
    {
        // Cold diagnostic only. Exact when the caller drained the public snapshot
        // or joined all writers; no global size counter is added to hot retirement.
        size_t result=0;
        for (auto& shard : shards_) { std::shared_lock lock(shard.mutex); result+=shard.nodes.size(); }
        return result;
    }
    void Clear()
    {
        // Caller drains the snapshot gate; no writer or release can still use it.
        for (auto& shard : shards_) { std::unique_lock lock(shard.mutex); shard.nodes.clear(); }
    }
};

// Only interval structure changes take exclusive. A copy never holds this lock
// while walking descriptors, and removal is by exact start+generation.
class NativeRangeIndex
{
    std::shared_mutex mutex_;
    BufferAddressIndex ranges_;
    std::atomic<uint64_t> version_ {1};
  public:
    uint64_t Version() const noexcept { return version_.load(std::memory_order_acquire); }
    void Insert(uint64_t start,uint64_t width,uint64_t generation,void* object)
    {
        std::unique_lock lock(mutex_,std::defer_lock);
        { MetadataWait wait(MetadataLock::Range); lock.lock(); }
        ranges_.Insert(start,width,generation,object); version_.fetch_add(1,std::memory_order_release);
    }
    void Erase(uint64_t start,uint64_t generation)
    {
        std::unique_lock lock(mutex_,std::defer_lock);
        { MetadataWait wait(MetadataLock::Range); lock.lock(); }
        ranges_.Erase(start,generation); version_.fetch_add(1,std::memory_order_release);
    }
    BufferAddressIndex::Match Find(uint64_t address)
    {
        std::shared_lock lock(mutex_,std::defer_lock);
        { MetadataWait wait(MetadataLock::Range); lock.lock(); }
        return ranges_.Find(address);
    }
    size_t Size()
    { std::shared_lock lock(mutex_); return ranges_.Size(); }
    void Clear()
    { std::unique_lock lock(mutex_); ranges_.Clear(); version_.fetch_add(1,std::memory_order_release); }
};

// Ordinary copies retain deep-copy semantics. Explicit Share() is cold-only and
// lets a native immutable node pin the legacy diagnostic reverse storage without
// depending on unordered-map node lifetime. Buckets contain integers, never nodes.
class DescriptorHandleOwner
{
    std::shared_ptr<DescriptorHandles> handles_;
    DescriptorHandles& Mutable()
    { if (!handles_) handles_ = std::make_shared<DescriptorHandles>(); return *handles_; }
  public:
    using const_iterator = DescriptorHandles::const_iterator;
    // Allocate the container at cold record construction. Independent first
    // slot writers must never race to publish the shared backing pointer.
    DescriptorHandleOwner() : handles_(std::make_shared<DescriptorHandles>()) {}
    DescriptorHandleOwner(const DescriptorHandleOwner& other)
    { if (other.handles_) handles_ = std::make_shared<DescriptorHandles>(*other.handles_); }
    DescriptorHandleOwner(DescriptorHandleOwner&&) noexcept = default;
    DescriptorHandleOwner& operator=(DescriptorHandleOwner other) noexcept { handles_.swap(other.handles_); return *this; }
    std::shared_ptr<DescriptorHandles> Share()
    { Mutable(); return handles_; }
    bool insert(uint64_t key) { return Mutable().insert(key); }
    size_t erase(uint64_t key) { return handles_ ? handles_->erase(key) : 0; }
    void erase(const_iterator it) { assert(handles_); handles_->erase(it); }
    bool PopAny(uint64_t& key) { return handles_ && handles_->PopAny(key); }
    bool contains(uint64_t key) const { return handles_ && handles_->contains(key); }
    size_t size() const noexcept { return handles_ ? handles_->size() : 0; }
    bool empty() const noexcept { return !size(); }
    const_iterator begin() const { return handles_ ? handles_->begin() : const_iterator{}; }
    const_iterator end() const noexcept { return {}; }
};
}
