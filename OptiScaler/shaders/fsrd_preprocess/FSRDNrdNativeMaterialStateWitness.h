#pragma once

#include "misc/NrdBridgeBirth_Dx12.h"
#include "resource_tracking/FrameSurvey_Dx12.h"

#include <array>
#include <cstddef>
#include <cstdint>

namespace NrdBridge
{
// Externally serialized, recording-local evidence for the two optional material
// SRVs. These are weak addresses and metadata tokens only: no COM owner, native
// query, allocation, resource scan or retained barrier pointer. The four-pair
// FIFO lets alternating title buffers receive barriers before their next Select.
struct NativeMaterialStateWitness
{
    void Select(const FrameSurvey::BoundResource& base,
                const FrameSurvey::BoundResource& params) noexcept
    { selected_ = EnsurePair(base,params); }

    // Seed identities before the recording's first barriers without selecting a
    // source or importing state from another list/recording.
    void Seed(const FrameSurvey::BoundResource& base,
              const FrameSurvey::BoundResource& params) noexcept
    { (void)EnsurePair(base,params); }

    // Reset/Close/cancellation preserves selections for early barriers in the
    // next recording, but never carries state evidence across that boundary.
    void Invalidate() noexcept
    {
        for (auto& pair : pairs_)
            for (auto& target : pair.targets) target.Forget("recording_invalidated");
    }

    void Observe(UINT count, const D3D12_RESOURCE_BARRIER* barriers,
                 uint64_t cancellationSerial) noexcept
    {
        if (count && !barriers) { Invalidate(); return; }
        for (UINT index = 0; index != count; ++index)
        {
            const auto& barrier = barriers[index];
            for (auto& pair : pairs_)
            {
                if (!pair.used) continue;
                for (auto& target : pair.targets)
                {
                    if (!target.resource) continue;
                    if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING)
                    {
                        const auto& alias = barrier.Aliasing;
                        // A null alias endpoint may stand for any placed resource;
                        // with no heap scan available the only safe result is unknown.
                        if (!alias.pResourceBefore || !alias.pResourceAfter ||
                            alias.pResourceBefore == target.resource ||
                            alias.pResourceAfter == target.resource)
                            target.Forget("alias_barrier");
                    }
                    else if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION &&
                             barrier.Transition.pResource == target.resource)
                        target.Observe(barrier, cancellationSerial);
                    // UAV barriers order access; they never establish an SRV state.
                }
            }
        }
    }

    using SourceStates = std::array<D3D12_RESOURCE_STATES,2>;
    // Diagnostics only: never turns unknown state into an admission witness.
    const char* StateReason(size_t target, uint64_t serial) const noexcept
    {
        if (selected_ == pairs_.size() || target >= 2) return "not_selected";
        const auto& value = pairs_[selected_].targets[target];
        if (!value.Live()) return "identity_not_live";
        if (value.Known(serial)) return "observed";
        if (value.known && value.serial != serial) return "serial_changed";
        return value.reason;
    }
    bool TryKnownStates(uint64_t serial, SourceStates& states) const noexcept
    {
        if (selected_ == pairs_.size()) return false;
        const auto& pair = pairs_[selected_];
        if (!pair.targets[0].Known(serial) || !pair.targets[1].Known(serial)) return false;
        states = {pair.targets[0].state,pair.targets[1].state};
        return true;
    }

    bool Readable(uint64_t serial) const noexcept
    {
        if (selected_ == pairs_.size()) return false;
        const auto& pair = pairs_[selected_];
        return pair.targets[0].Readable(serial) && pair.targets[1].Readable(serial);
    }

  private:
    struct Target
    {
        ID3D12Resource* resource = nullptr;
        NrdBridgeBirth::Token birth;
        uint64_t generation = 0;
        uint32_t subresource = UINT32_MAX;
        uint64_t serial = 0;
        D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
        D3D12_RESOURCE_STATES splitBefore = D3D12_RESOURCE_STATE_COMMON;
        D3D12_RESOURCE_STATES splitAfter = D3D12_RESOURCE_STATE_COMMON;
        UINT splitSubresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        bool known = false, pending = false;
        const char* reason = "no_local_transition";

        bool Matches(const FrameSurvey::BoundResource& bound) const noexcept
        { return resource == bound.resource && birth == bound.resourceBirth &&
                 generation == bound.resourceGeneration && subresource == bound.subresource; }

        void Select(const FrameSurvey::BoundResource& bound) noexcept
        {
            resource = bound.resource;
            birth = bound.resourceBirth;
            generation = bound.resourceGeneration;
            subresource = bound.subresource;
            Forget();
        }

        void Forget(const char* why = "no_local_transition") noexcept
        { known = pending = false; serial = 0; reason = why; }

        bool Live() const noexcept
        {
            // Legacy bindings require the exact nonzero registry generation
            // selected under the caller's title lifetime borrow. A Birth token
            // proves its own exact native instance and must match this address.
            return resource && subresource == 0 &&
                   (birth ? (birth->Address() == resource && birth->CacheAdmissible()) : generation != 0);
        }

        void Observe(const D3D12_RESOURCE_BARRIER& barrier, uint64_t currentSerial) noexcept
        {
            const auto& transition = barrier.Transition;
            if (subresource != 0 ||
                (transition.Subresource != 0 &&
                 transition.Subresource != D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES)) return;
            if (serial != currentSerial) { Forget(); serial = currentSerial; }
            if (!Live()) { Forget(); return; }
            if (barrier.Flags == D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY)
            {
                known = false; pending = true;
                reason = "split_pending";
                splitBefore = transition.StateBefore; splitAfter = transition.StateAfter;
                splitSubresource = transition.Subresource;
            }
            else if (barrier.Flags == D3D12_RESOURCE_BARRIER_FLAG_END_ONLY)
            {
                known = pending && splitBefore == transition.StateBefore &&
                        splitAfter == transition.StateAfter && splitSubresource == transition.Subresource;
                reason = known ? "observed" : "unmatched_split_end";
                pending = false;
                state = transition.StateAfter;
            }
            else if (barrier.Flags == D3D12_RESOURCE_BARRIER_FLAG_NONE)
            {
                known = !pending;
                reason = known ? "observed" : "incomplete_split";
                pending = false;
                state = transition.StateAfter;
            }
            else Forget();
        }

        bool Known(uint64_t currentSerial) const noexcept
        { return known && !pending && serial == currentSerial && Live(); }

        bool Readable(uint64_t currentSerial) const noexcept
        {
            constexpr auto writable = D3D12_RESOURCE_STATE_RENDER_TARGET |
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS | D3D12_RESOURCE_STATE_DEPTH_WRITE |
                D3D12_RESOURCE_STATE_STREAM_OUT | D3D12_RESOURCE_STATE_COPY_DEST |
                D3D12_RESOURCE_STATE_RESOLVE_DEST | D3D12_RESOURCE_STATE_VIDEO_DECODE_WRITE |
                D3D12_RESOURCE_STATE_VIDEO_PROCESS_WRITE | D3D12_RESOURCE_STATE_VIDEO_ENCODE_WRITE;
            return Known(currentSerial) &&
                    (state & D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE) != 0 && (state & writable) == 0;
        }
    };
    size_t EnsurePair(const FrameSurvey::BoundResource& base,
                      const FrameSurvey::BoundResource& params) noexcept
    {
        for (size_t index = 0; index != pairs_.size(); ++index)
            if (pairs_[index].used && pairs_[index].targets[0].Matches(base) &&
                pairs_[index].targets[1].Matches(params)) return index;
        const auto index = next_;
        // An evicted selection cannot accidentally refer to the new identity.
        if (selected_ == index) selected_ = pairs_.size();
        auto& pair = pairs_[index];
        pair.targets[0].Select(base); pair.targets[1].Select(params); pair.used = true;
        next_ = (next_ + 1) % pairs_.size();
        return index;
    }
    struct Pair { std::array<Target, 2> targets {}; bool used = false; };
    std::array<Pair, 4> pairs_ {};
    size_t selected_ = pairs_.size(), next_ = 0;
};

// Service-wide bounded discovery remembers weak identities only. Every target
// list must observe its own current-recording barriers after these are seeded.
// In particular no state, queue order or preceding recording is copied here.
struct NativeMaterialIdentityCache
{
    bool Empty() const noexcept
    { for (const auto& pair : pairs_) if (pair.used) return false; return true; }
    void Remember(const FrameSurvey::BoundResource& base,
                  const FrameSurvey::BoundResource& params) noexcept
    {
        for (const auto& pair : pairs_)
            if (pair.used && Same(pair.base,base) && Same(pair.params,params)) return;
        pairs_[next_] = {Identity(base),Identity(params),true};
        next_ = (next_ + 1) % pairs_.size();
        ++revision_;
    }
    uint64_t Revision() const noexcept { return revision_; }
    bool SeedIfChanged(NativeMaterialStateWitness& witness, uint64_t& seenRevision) const noexcept
    {
        if (seenRevision == revision_) return false;
        Seed(witness); seenRevision = revision_; return true;
    }
    // Unknown lists are relevant only when an actual supplied transition names
    // an exact cached live target. Aliases alone establish no state proof.
    bool MatchesAnyTransition(UINT count, const D3D12_RESOURCE_BARRIER* barriers) const noexcept
    {
        if (!barriers) return false;
        for (UINT index = 0; index != count; ++index)
        {
            const auto& barrier = barriers[index];
            if (barrier.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                (barrier.Transition.Subresource != 0 &&
                 barrier.Transition.Subresource != D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES)) continue;
            for (const auto& pair : pairs_)
                if (pair.used && (MatchesTransition(pair.base,barrier.Transition.pResource) ||
                                  MatchesTransition(pair.params,barrier.Transition.pResource))) return true;
        }
        return false;
    }
    void Seed(NativeMaterialStateWitness& witness) const noexcept
    {
        for (const auto& pair : pairs_)
            if (pair.used) witness.Seed(pair.base,pair.params);
    }
  private:
    static bool MatchesTransition(const FrameSurvey::BoundResource& bound, ID3D12Resource* resource) noexcept
    {
        return resource && bound.resource == resource && bound.subresource == 0 &&
            (bound.resourceBirth ? (bound.resourceBirth->Address() == resource &&
                                   bound.resourceBirth->CacheAdmissible()) : bound.resourceGeneration != 0);
    }
    static bool Same(const FrameSurvey::BoundResource& a,
                     const FrameSurvey::BoundResource& b) noexcept
    { return a.resource == b.resource && a.resourceBirth == b.resourceBirth &&
             a.resourceGeneration == b.resourceGeneration && a.subresource == b.subresource; }
    static FrameSurvey::BoundResource Identity(const FrameSurvey::BoundResource& bound) noexcept
    {
        FrameSurvey::BoundResource identity;
        identity.resource = bound.resource; identity.resourceBirth = bound.resourceBirth;
        identity.resourceGeneration = bound.resourceGeneration; identity.subresource = bound.subresource;
        return identity;
    }
    struct Pair { FrameSurvey::BoundResource base,params; bool used = false; };
    std::array<Pair,4> pairs_ {};
    size_t next_ = 0;
    uint64_t revision_ = 0;
};
}
