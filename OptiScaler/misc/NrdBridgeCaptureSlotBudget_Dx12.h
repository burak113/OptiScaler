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

// D07/WP10 staging byte admission ledger. It is shared by every retained
// staging generation of one RR wrapper and counts slot pair bytes only
// (debug targets keep their separate auxiliary class). Byte admission is
// DISABLED at the documented default limit 0: the shipped per-context slot
// cap stays the single active admission. Each TryAdmit reserves bytes and
// one slot unit; each Retire returns exactly one admitted slot's bytes.
// No native calls; the rejections counter and retirement total are metadata.
class StagingLedger
{
    std::atomic<uint64_t> retainedBytes_ {0}, retainedPeakBytes_ {0}, retiredTotal_ {0};
    std::atomic<uint32_t> retainedSlots_ {0}, rejections_ {0};
  public:
    static constexpr uint64_t NoLimit = 0;
    uint64_t limit = NoLimit; // Mutated once before hot use; never during.
    bool byteAdmissionActive() const noexcept { return limit != NoLimit; }
    uint64_t RetainedBytes() const noexcept { return retainedBytes_.load(std::memory_order_acquire); }
    uint64_t RetainedPeakBytes() const noexcept { return retainedPeakBytes_.load(std::memory_order_acquire); }
    uint64_t RetiredTotalBytes() const noexcept { return retiredTotal_.load(std::memory_order_acquire); }
    uint32_t RetainedSlots() const noexcept { return retainedSlots_.load(std::memory_order_acquire); }
    uint32_t Rejections() const noexcept { return rejections_.load(std::memory_order_acquire); }
    bool TryAdmit(uint64_t bytes) noexcept
    {
        auto current = retainedBytes_.load(std::memory_order_acquire);
        for (;;)
        {
            if (limit != NoLimit)
            {
                uint64_t checked = current;
                if (checked > limit || bytes > limit-checked)
                { rejections_.fetch_add(1,std::memory_order_relaxed); return false; }
            }
            if (bytes == 0 || retainedBytes_.compare_exchange_weak(current,current+bytes,std::memory_order_acq_rel)) break;
        }
        const uint64_t updated = retainedBytes_.load(std::memory_order_relaxed);
        auto peak = retainedPeakBytes_.load(std::memory_order_relaxed);
        while (peak < updated && !retainedPeakBytes_.compare_exchange_weak(peak,updated,std::memory_order_relaxed)) {}
        retainedSlots_.fetch_add(1,std::memory_order_acq_rel);
        return true;
    }
    void Retire(uint64_t bytes) noexcept
    {
        // One call returns exactly one admitted slot's bytes (retired total is
        // therefore monotone across every retained generation).
        if (!bytes) return;
        retiredTotal_.fetch_add(bytes,std::memory_order_acq_rel);
        retainedBytes_.fetch_sub(bytes,std::memory_order_acq_rel);
        retainedSlots_.fetch_sub(1,std::memory_order_acq_rel);
    }
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
