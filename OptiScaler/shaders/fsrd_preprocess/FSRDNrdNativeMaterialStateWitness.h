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
    {
        for (size_t index = 0; index != pairs_.size(); ++index)
            if (pairs_[index].used && pairs_[index].targets[0].Matches(base) &&
                pairs_[index].targets[1].Matches(params))
            { selected_ = index; return; }

        selected_ = next_;
        auto& pair = pairs_[selected_];
        pair.targets[0].Select(base);
        pair.targets[1].Select(params);
        pair.used = true;
        next_ = (next_ + 1) % pairs_.size();
    }

    // Reset/Close/cancellation preserves selections for early barriers in the
    // next recording, but never carries state evidence across that boundary.
    void Invalidate() noexcept
    {
        for (auto& pair : pairs_)
            for (auto& target : pair.targets) target.Forget();
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
                            target.Forget();
                    }
                    else if (barrier.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION &&
                             barrier.Transition.pResource == target.resource)
                        target.Observe(barrier, cancellationSerial);
                    // UAV barriers order access; they never establish an SRV state.
                }
            }
        }
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
        uint32_t subresource = UINT32_MAX;
        uint64_t serial = 0;
        D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
        D3D12_RESOURCE_STATES splitBefore = D3D12_RESOURCE_STATE_COMMON;
        D3D12_RESOURCE_STATES splitAfter = D3D12_RESOURCE_STATE_COMMON;
        UINT splitSubresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        bool known = false, pending = false;

        bool Matches(const FrameSurvey::BoundResource& bound) const noexcept
        { return resource == bound.resource && birth == bound.resourceBirth && subresource == bound.subresource; }

        void Select(const FrameSurvey::BoundResource& bound) noexcept
        {
            resource = bound.resource;
            birth = bound.resourceBirth;
            subresource = bound.subresource;
            Forget();
        }

        void Forget() noexcept
        { known = pending = false; serial = 0; }

        bool Live() const noexcept
        {
            // Legacy null-birth bindings are accepted only under the caller's
            // existing title lifetime borrow. A token must match this address.
            return resource && subresource == 0 &&
                   (!birth || (birth->Address() == resource && birth->CacheAdmissible()));
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
                splitBefore = transition.StateBefore; splitAfter = transition.StateAfter;
                splitSubresource = transition.Subresource;
            }
            else if (barrier.Flags == D3D12_RESOURCE_BARRIER_FLAG_END_ONLY)
            {
                known = pending && splitBefore == transition.StateBefore &&
                        splitAfter == transition.StateAfter && splitSubresource == transition.Subresource;
                pending = false;
                state = transition.StateAfter;
            }
            else if (barrier.Flags == D3D12_RESOURCE_BARRIER_FLAG_NONE)
            {
                known = !pending;
                pending = false;
                state = transition.StateAfter;
            }
            else Forget();
        }

        bool Readable(uint64_t currentSerial) const noexcept
        {
            constexpr auto writable = D3D12_RESOURCE_STATE_RENDER_TARGET |
                D3D12_RESOURCE_STATE_UNORDERED_ACCESS | D3D12_RESOURCE_STATE_DEPTH_WRITE |
                D3D12_RESOURCE_STATE_STREAM_OUT | D3D12_RESOURCE_STATE_COPY_DEST |
                D3D12_RESOURCE_STATE_RESOLVE_DEST | D3D12_RESOURCE_STATE_VIDEO_DECODE_WRITE |
                D3D12_RESOURCE_STATE_VIDEO_PROCESS_WRITE | D3D12_RESOURCE_STATE_VIDEO_ENCODE_WRITE;
            return known && !pending && serial == currentSerial && Live() &&
                   (state & D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE) != 0 && (state & writable) == 0;
        }
    };
    struct Pair { std::array<Target, 2> targets {}; bool used = false; };
    std::array<Pair, 4> pairs_ {};
    size_t selected_ = pairs_.size(), next_ = 0;
};
}
