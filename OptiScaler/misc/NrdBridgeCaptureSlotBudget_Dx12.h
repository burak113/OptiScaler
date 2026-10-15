#pragma once
#include <atomic>
#include <cstdint>
#include <memory>
#include <utility>

// One lazily-created family spans every retained context of one capture helper.
// Reserve only for a NEW allocated slot; reusing a cached slot does not touch
// these counters. This contains metadata only: no native calls or heap allocation.
namespace NrdBridgeCaptureBudget
{
struct Family
{
    static constexpr uint32_t Capacity = 32;
    std::atomic<uint32_t> allocatedSlots {0};
    std::atomic<uint64_t> allocatedBytes {0};
};

class Permit
{
    std::shared_ptr<Family> family_;
    uint64_t bytes_ = 0;
  public:
    Permit() noexcept = default;
    Permit(const Permit&) = delete;
    Permit& operator=(const Permit&) = delete;
    Permit(Permit&& other) noexcept
        : family_(std::move(other.family_)), bytes_(std::exchange(other.bytes_,0)) {}
    Permit& operator=(Permit&&) = delete;
    ~Permit()
    {
        if (!family_) return;
        family_->allocatedBytes.fetch_sub(bytes_,std::memory_order_acq_rel);
        family_->allocatedSlots.fetch_sub(1,std::memory_order_acq_rel);
    }
    static Permit TryAcquire(const std::shared_ptr<Family>& family) noexcept
    {
        Permit result;
        if (!family) return result;
        auto count = family->allocatedSlots.load(std::memory_order_acquire);
        while (count < Family::Capacity)
            if (family->allocatedSlots.compare_exchange_weak(count,count+1,std::memory_order_acq_rel))
            { result.family_ = family; break; }
        return result;
    }
    explicit operator bool() const noexcept { return bool(family_); }
    bool SetBytes(uint64_t bytes) noexcept
    {
        if (!family_ || bytes_ || !bytes || bytes == UINT64_MAX) return false;
        auto total = family_->allocatedBytes.load(std::memory_order_acquire);
        for (;;)
        {
            if (bytes > UINT64_MAX-total) return false;
            if (family_->allocatedBytes.compare_exchange_weak(total,total+bytes,std::memory_order_acq_rel))
            { bytes_ = bytes; return true; }
        }
    }
};
}
