#pragma once
#include "misc/NrdBridgePerf_Dx12.h"
#include "FrameSurveyBufferRanges.h"
#include <array>
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
    uint64_t before_ = 0;
    std::optional<NrdBridgePerf::WaitScope> measured_;
  public:
    explicit MetadataWait(MetadataLock kind) noexcept : kind_(kind),accumulator_(NrdBridgePerf::Detail::currentWaits)
    {
        if (accumulator_) before_ = (*accumulator_)[size_t(NrdBridgePerf::WaitKind::Metadata)];
        measured_.emplace(NrdBridgePerf::WaitKind::Metadata);
    }
    ~MetadataWait()
    {
        measured_.reset();
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
        MetadataWait wait(Kind); mutex_.lock();
    }
    bool try_lock() { MetadataWait wait(Kind); return mutex_.try_lock(); }
    void unlock() noexcept { mutex_.unlock(); }
};
inline constexpr size_t DescriptorShards = 32;
inline size_t DescriptorShard(uint64_t cpuHandle) noexcept
{
    const auto slot = (cpuHandle >> 4)*0x9e3779b97f4a7c15ull;
    return size_t(slot >> 59);
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
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogExclusive);
        try { mutex_.lock(); entry.exclusive = 1; } catch (...) { Retire(entry); throw; }
    }
    bool try_lock()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive) { ++entry.exclusive; return true; }
        if (entry.shared) throw std::logic_error("Metadata shared-to-exclusive upgrade is forbidden");
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogExclusive);
        if (mutex_.try_lock()) { entry.exclusive = 1; return true; }
        Retire(entry); return false;
    }
    void unlock()
    {
        auto& entry = EntryFor(false); assert(entry.exclusive);
        if (!--entry.exclusive) { assert(!entry.shared); mutex_.unlock(); }
        Retire(entry);
    }
    void lock_shared()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive || entry.shared) { ++entry.shared; return; }
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogShared);
        try { mutex_.lock_shared(); entry.shared = 1; } catch (...) { Retire(entry); throw; }
    }
    bool try_lock_shared()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive || entry.shared) { ++entry.shared; return true; }
        MetadataWait wait(snapshot_ ? MetadataLock::Snapshot : MetadataLock::CatalogShared);
        if (mutex_.try_lock_shared()) { entry.shared = 1; return true; }
        Retire(entry); return false;
    }
    void unlock_shared()
    {
        auto& entry = EntryFor(false); assert(entry.shared);
        if (!--entry.shared && !entry.exclusive) mutex_.unlock_shared();
        Retire(entry);
    }
};

// External synchronization: catalog exclusive, OR catalog shared plus the
// descriptor shard. No reference/iterator can outlive that external guard.
template<class Value> class DescriptorMap
{
    using Map = std::unordered_map<uint64_t,Value>;
    std::array<Map,DescriptorShards> maps_;
    std::atomic<size_t> size_ {0};
    template<bool Constant> class Iter
    {
        friend class DescriptorMap;
        using Owner = std::conditional_t<Constant,const DescriptorMap,DescriptorMap>;
        using Native = std::conditional_t<Constant,typename Map::const_iterator,typename Map::iterator>;
        Owner* owner_ = nullptr; size_t shard_ = 0; Native native_ {};
        Iter(Owner* owner,size_t shard,Native native) : owner_(owner),shard_(shard),native_(native) {}
      public:
        using iterator_category = std::forward_iterator_tag;
        using value_type = typename Map::value_type;
        using difference_type = std::ptrdiff_t;
        using pointer = std::conditional_t<Constant,const value_type*,value_type*>;
        using reference = std::conditional_t<Constant,const value_type&,value_type&>;
        Iter() = default;
        Iter operator++(int) { auto before = *this; ++*this; return before; }
        auto& operator*() const { return *native_; }
        auto* operator->() const { return std::addressof(*native_); }
        bool operator==(const Iter& other) const
        { return owner_ == other.owner_ && (!owner_ || (shard_ == other.shard_ && native_ == other.native_)); }
        bool operator!=(const Iter& other) const { return !(*this == other); }
        Iter& operator++()
        {
            if (++native_ != owner_->maps_[shard_].end()) return *this;
            while (++shard_ < DescriptorShards) if (!owner_->maps_[shard_].empty())
            { native_ = owner_->maps_[shard_].begin(); return *this; }
            owner_ = nullptr; return *this;
        }
    };
  public:
    using iterator = Iter<false>; using const_iterator = Iter<true>;
    iterator end() noexcept { return {}; } const_iterator end() const noexcept { return {}; }
    iterator begin()
    { for (size_t i=0;i<DescriptorShards;++i) if (!maps_[i].empty()) return {this,i,maps_[i].begin()}; return {}; }
    const_iterator begin() const
    { for (size_t i=0;i<DescriptorShards;++i) if (!maps_[i].empty()) return {this,i,maps_[i].begin()}; return {}; }
    iterator find(uint64_t key)
    { const auto i = DescriptorShard(key); auto it = maps_[i].find(key); return it == maps_[i].end() ? iterator{} : iterator(this,i,it); }
    const_iterator find(uint64_t key) const
    { const auto i = DescriptorShard(key); auto it = maps_[i].find(key); return it == maps_[i].end() ? const_iterator{} : const_iterator(this,i,it); }
    bool contains(uint64_t key) const { return find(key) != end(); }
    template<class... Args> std::pair<iterator,bool> emplace(uint64_t key,Args&&... args)
    {
        const auto i = DescriptorShard(key); auto [it,inserted] = maps_[i].try_emplace(key,std::forward<Args>(args)...);
        if (inserted) size_.fetch_add(1,std::memory_order_relaxed);
        return {iterator(this,i,it),inserted};
    }
    Value& operator[](uint64_t key) { return emplace(key).first->second; }
    Value& at(uint64_t key) { auto it = find(key); if (it == end()) throw std::out_of_range("Descriptor slot"); return it->second; }
    const Value& at(uint64_t key) const { auto it = find(key); if (it == end()) throw std::out_of_range("Descriptor slot"); return it->second; }
    size_t erase(uint64_t key)
    { const auto erased = maps_[DescriptorShard(key)].erase(key); if (erased) size_.fetch_sub(erased,std::memory_order_relaxed); return erased; }
    void erase(iterator it)
    { assert(it.owner_ == this); maps_[it.shard_].erase(it.native_); size_.fetch_sub(1,std::memory_order_relaxed); }
    size_t size() const noexcept { return size_.load(std::memory_order_relaxed); }
    bool empty() const noexcept { return !size(); }
    void clear() { for (auto& map : maps_) map.clear(); size_.store(0,std::memory_order_relaxed); }
};

// Reverse sets use exactly the slot-map shard. Distinct slot shards never mutate
// the same std::set, even when every view points at one shared resource/heap.
// Bucket storage is lazy so resources without views allocate nothing extra.
class DescriptorHandles
{
    using Set = std::set<uint64_t>;
    std::array<std::unique_ptr<Set>,DescriptorShards> sets_;
    std::atomic<size_t> size_ {0};
    size_t takeShard_ = 0; // Lifecycle-only cursor, always protected by catalog exclusive.
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
            for (const auto& set : owner_->sets_) if (set)
                if (const auto it = set->upper_bound(value_); it != set->end() && (!found || *it < next)) { next = *it; found = true; }
            if (found) value_ = next; else owner_ = nullptr;
            return *this;
        }
    };
    DescriptorHandles() = default;
    DescriptorHandles(const DescriptorHandles& other)
    {
        for (size_t i=0;i<DescriptorShards;++i) if (other.sets_[i]) sets_[i] = std::make_unique<Set>(*other.sets_[i]);
        size_.store(other.size(),std::memory_order_relaxed);
    }
    DescriptorHandles(DescriptorHandles&& other) noexcept : sets_(std::move(other.sets_)),takeShard_(std::exchange(other.takeShard_,0))
    { size_.store(other.size_.exchange(0,std::memory_order_relaxed),std::memory_order_relaxed); }
    DescriptorHandles& operator=(DescriptorHandles other) noexcept
    { sets_.swap(other.sets_); std::swap(takeShard_,other.takeShard_); const auto size = size_.exchange(other.size(),std::memory_order_relaxed); other.size_.store(size,std::memory_order_relaxed); return *this; }
    bool insert(uint64_t key)
    {
        auto& set = sets_[DescriptorShard(key)]; if (!set) set = std::make_unique<Set>();
        const bool added = set->insert(key).second; if (added) size_.fetch_add(1,std::memory_order_relaxed); return added;
    }
    size_t erase(uint64_t key)
    {
        auto& set = sets_[DescriptorShard(key)]; if (!set) return 0;
        const auto erased = set->erase(key); if (erased) size_.fetch_sub(erased,std::memory_order_relaxed); return erased;
    }
    void erase(const_iterator it) { assert(it.owner_ == this); erase(*it); }
    // Retirement order is unobservable. Drain the current bucket before seeking
    // another instead of merging 32 sorted buckets for every affected slot.
    bool PopAny(uint64_t& key)
    {
        if (empty()) return false;
        for (size_t offset=0;offset<DescriptorShards;++offset)
        {
            const auto index = (takeShard_+offset)&(DescriptorShards-1);
            auto& set = sets_[index];
            if (!set || set->empty()) continue;
            const auto it = set->begin(); key = *it; set->erase(it);
            size_.fetch_sub(1,std::memory_order_relaxed); takeShard_ = index; return true;
        }
        assert(false && "Reverse count disagrees with descriptor buckets"); return false;
    }
    // Native retirement holds only this exact slot shard. Other buckets may
    // still change concurrently and are never traversed from here.
    bool PopShard(size_t shard,uint64_t& key)
    {
        assert(shard < DescriptorShards); auto& set = sets_[shard];
        if (!set || set->empty()) return false;
        const auto it = set->begin(); key = *it; set->erase(it);
        size_.fetch_sub(1,std::memory_order_relaxed); return true;
    }
    bool contains(uint64_t key) const { const auto& set = sets_[DescriptorShard(key)]; return set && set->contains(key); }
    size_t size() const noexcept { return size_.load(std::memory_order_relaxed); }
    bool empty() const noexcept { return !size(); }
    const_iterator end() const noexcept { return {}; }
    const_iterator begin() const
    {
        bool found = false; uint64_t first = 0;
        for (const auto& set : sets_) if (set && !set->empty() && (!found || *set->begin() < first)) { first = *set->begin(); found = true; }
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
