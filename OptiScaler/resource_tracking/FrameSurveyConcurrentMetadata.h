#pragma once
#include "misc/NrdBridgePerf_Dx12.h"
#include <array>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <memory>
#include <iterator>
#include <mutex>
#include <set>
#include <shared_mutex>
#include <stdexcept>
#include <type_traits>
#include <unordered_map>
#include <utility>

namespace FrameSurveyMetadata
{
inline constexpr size_t DescriptorShards = 32;
inline size_t DescriptorShard(uint64_t cpuHandle) noexcept
{
    const auto slot = (cpuHandle >> 4)*0x9e3779b97f4a7c15ull;
    return size_t(slot >> 59);
}

// Catalog readers can update independent descriptor shards concurrently. Catalog
// writers drain all readers before resource/heap lifetime or recorder traversal.
// Recursive exclusive scopes preserve existing recorder/read helper contracts.
class RecursiveSharedMutex
{
    std::shared_mutex mutex_;
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
    void lock()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive) { ++entry.exclusive; return; }
        if (entry.shared) throw std::logic_error("Metadata shared-to-exclusive upgrade is forbidden");
        NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Metadata);
        try { mutex_.lock(); entry.exclusive = 1; } catch (...) { Retire(entry); throw; }
    }
    bool try_lock()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive) { ++entry.exclusive; return true; }
        if (entry.shared) throw std::logic_error("Metadata shared-to-exclusive upgrade is forbidden");
        NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Metadata);
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
        NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Metadata);
        try { mutex_.lock_shared(); entry.shared = 1; } catch (...) { Retire(entry); throw; }
    }
    bool try_lock_shared()
    {
        auto& entry = EntryFor(true);
        if (entry.exclusive || entry.shared) { ++entry.shared; return true; }
        NrdBridgePerf::WaitScope wait(NrdBridgePerf::WaitKind::Metadata);
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
}
