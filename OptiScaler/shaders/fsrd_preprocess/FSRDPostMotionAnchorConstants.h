// Experimental post-motion input-level anchor, default off.
// A six-slot settled-key ring estimates a luminance-only reduction before RR.
// This cannot identify the cause of a captured level change: moderate real light
// changes can also be attenuated. The gain never brightens or transfers key chroma.
//
// Shared camera/state math is exercised by the combined and native host fixtures.
// Native and combined Gain shaders have different fallback/coverage policies;
// prototype quality numbers are not production guarantees.
//
// Desc matrices are the TRANSPOSE of the matrix HLSL sees (FSRDPostFlickConstants.h documents the same rule):
// every load goes through LoadDesc, and the conversion desc carries the transpose of the INVERSE view/projection,
// so inverting yields the transpose of the forward matrix.
#pragma once
#include <DirectXMath.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>

namespace PostMotionAnchorMath
{
    // --- keyframe ring --------------------------------------------------------------------------------------
    // Bound reference age/footprint. Matching depth on a fronto-parallel surface
    // does not prove that a view-dependent lighting sample is temporally comparable.
    inline constexpr uint32_t kRingSize = 6u;
    // A keyframe is sampled while the camera is still, at most every kSampleFrames frames, and only after
    // kSettledFrames consecutive still frames: a frame right after its own flick still carries part of that
    // flick's excess, which would bias the measured ratio (SA1: the input's own decay is tau ~10 frames).
    inline constexpr float kStillDegrees = 0.5f;
    inline constexpr uint32_t kSettledFrames = 2u;
    inline constexpr uint32_t kSampleFrames = 4u;

    // --- post-motion window ---------------------------------------------------------------------------------
    // k = frames since the last frame at or above kMotionDegrees. Apply only in
    // this window after a burst reaches kArmDegrees; active motion is included.
    inline constexpr float kMotionDegrees = 1.0f;
    inline constexpr float kArmDegrees = 3.0f;
    inline constexpr uint32_t kWindowFrames = 25u;

    // --- bounded experimental gain --------------------------------------------------------------------------
    // A decaying band limits the correction; it does not classify real light.
    // Native Gain uses identity fallback and a local static/coverage gate.
    // Combined Gain can use the measured frame ratio as fallback.
    // kFallbackA remains in the constant layout but is not read by either pass.
    inline constexpr float kBandA = 0.18f;
    inline constexpr float kBandTau = 10.0f;
    inline constexpr float kCapExtra = 0.05f;
    inline constexpr float kCapHard = 0.30f;
    inline constexpr float kFallbackA = 0.15f;
    inline constexpr float kGainLow = 0.80f;
    // Reject large changes outside this band. Moderate genuine light changes
    // may still pass; this threshold is not a no-light-lag guarantee.
    inline constexpr float kRejectMult = 1.8f;
    inline constexpr float kRejectAbs = 0.30f;
    inline constexpr float kDepthTolerance = 0.02f;
    // Per-cell (1/8 res) guards: the static share of the cell and the recalled share.
    inline constexpr float kMinStatic = 0.05f;
    inline constexpr float kMinRecall = 0.15f;
    // The smoothing taps sit kTapStepCells cells apart (3 at 1/8 res = 24 full-res pixels, the prototype's sigma).
    inline constexpr float kTapStepCells = 3.0f;
    // Coverage blend: 0.3 x the 9 taps, the prototype's cov/0.3 fold with its 9-tap kernel.
    inline constexpr float kCoverageTaps = 2.7f;

    inline constexpr float kStrengthMin = 0.0f, kStrengthMax = 1.0f, kStrengthDefault = 1.0f;

    struct RingSlot
    {
        DirectX::XMFLOAT4X4 View {}, Projection {};
        bool Valid = false;
        uint64_t CaptureFrame = 0;
    };

    struct State
    {
        RingSlot Ring[kRingSize] {};
        uint32_t WriteIndex = 0;
        uint64_t Frame = 0;          // monotone over the frames the anchor runs on
        uint64_t LastSampleFrame = 0;
        uint32_t StillFrames = 0;
        uint32_t SettledFrames = 0;
        bool Moving = false;
        float BoutPeak = 0.0f;       // the current motion bout's peak rotation (deg/frame)
        float LastBoutPeak = 0.0f;   // ...and the last completed one, which is what arms the anchor
        bool Armed = false;
        uint32_t MotionFrames = 100000u; // k
        bool WasEnabled = false;
    };

    // The per-frame constants of the two 1/8-resolution passes. The keyframe reprojection data lives in the
    // stats/recall pass's own buffer (one root CBV per pass, the house pattern) in PRIORITY order: keyframes
    // captured before the motion frame that just ended first (they cannot carry that burst's own excess),
    // newest first, then the rest, newest first.
    struct alignas(16) StatsRecallConstants
    {
        DirectX::XMFLOAT4 Size;         // full width, height, 1/8 width, 1/8 height
        DirectX::XMFLOAT4 Projection;   // current P00, P11, P02, P12
        DirectX::XMFLOAT4 Extra;        // x current P32, y depth tolerance, z active, w refresh
        DirectX::XMFLOAT4 Params;       // x strength, y min static, z min recall, w ring write slice
        DirectX::XMFLOAT4X4 PrevRelative; // current view space -> the previous frame's view space
        DirectX::XMFLOAT4X4 ProjectionRows; // the current projection, row by row (for the static test)
        DirectX::XMUINT4 KeySlice[2];   // 8 ring slice indices, priority order
        // The arrays stay at the shader cbuffer's declared size (8): the ring itself is kRingSize (6), and the
        // recall shader stops at the host-written sentinel (Params.w = kRingSize), so the two unused entries are
        // never read. Resizing them to kRingSize would shrink the upload and shift every slot field the shader
        // reads (caught by SA22: the recall then read 128 bytes past the host's data and went dead).
        DirectX::XMFLOAT4X4 Relative[8]; // current view space -> keyframe clip space, row by row
        DirectX::XMFLOAT4 SlotExtra[8];  // x key P32, y valid, zw unused
    };
    static_assert(sizeof(StatsRecallConstants) == 16 * 4 + 128 + 32 + 64 * 8 + 16 * 8,
        "FSRDPostMotionAnchorStatsRecall constants");

    struct alignas(16) GainConstants
    {
        DirectX::XMFLOAT4 Size;     // full width, height, 1/8 width, 1/8 height
        DirectX::XMFLOAT4 Params;   // x band A, y band tau, z cap extra, w cap hard
        DirectX::XMFLOAT4 Params2;  // x strength, y fallback A, z tap step (cells), w coverage taps
        DirectX::XMFLOAT4 Params3;  // x reject mult, y reject abs, z gain low, w window k
        DirectX::XMFLOAT4 Params4;  // x refresh (0/1), y ring write slice, z ring size, w unused
    };
    static_assert(sizeof(GainConstants) == 80, "FSRDPostMotionAnchorGain constants");

    struct alignas(16) ApplyConstants
    {
        DirectX::XMFLOAT4 Size; // full width, height, 1/width, 1/height
    };
    static_assert(sizeof(ApplyConstants) == 16, "FSRDPostMotionAnchorApply constants");

    inline DirectX::XMMATRIX LoadDesc(const DirectX::XMFLOAT4X4& value)
    {
        return DirectX::XMMatrixTranspose(DirectX::XMLoadFloat4x4(&value));
    }

    inline float ForwardDegrees(const DirectX::XMMATRIX& a, const DirectX::XMMATRIX& b)
    {
        const auto forward = [](const DirectX::XMMATRIX& v) {
            return DirectX::XMVector3Normalize(DirectX::XMVectorSet(
                v.r[2].m128_f32[0], v.r[2].m128_f32[1], v.r[2].m128_f32[2], 0.0f));
        };
        const float cosine = DirectX::XMVectorGetX(DirectX::XMVector3Dot(forward(a), forward(b)));
        return std::acos(std::clamp(cosine, -1.0f, 1.0f)) * 57.2957795f;
    }

    // One frame of host-side state. `view`/`projection`/`previousView` are the conversion desc's forward matrices
    // (see the header note), `enabled` is the option. Returns true when this frame's window is active, i.e. when
    // the three GPU passes may run.
    inline bool BuildFrame(State& state, const DirectX::XMFLOAT4X4& view, const DirectX::XMFLOAT4X4& projection,
        const DirectX::XMFLOAT4X4& previousView, bool enabled, float strength,
        StatsRecallConstants& stats, GainConstants& gain)
    {
        // Reset before deriving active, refresh, or any published keyframe constants.
        if (state.WasEnabled != enabled)
        {
            state = State {};
            state.WasEnabled = enabled;
        }
        if (!enabled) return false;
        const DirectX::XMMATRIX currentView = LoadDesc(view);
        const DirectX::XMMATRIX currentProjection = LoadDesc(projection);
        const float degrees = ForwardDegrees(currentView, LoadDesc(previousView));
        const float safeDegrees = std::isfinite(degrees) ? degrees : 0.0f;

        state.Frame += 1u;
        const bool moving = safeDegrees >= kMotionDegrees;
        if (moving)
        {
            if (!state.Moving) state.BoutPeak = 0.0f; // a new bout replaces the previous one's peak
            state.BoutPeak = std::max(state.BoutPeak, safeDegrees);
            state.LastBoutPeak = state.BoutPeak;
            state.MotionFrames = 0u;
            state.StillFrames = 0u;
            state.SettledFrames = 0u;
        }
        else
        {
            state.MotionFrames = std::min(state.MotionFrames + 1u, 100000u);
            state.StillFrames = std::min(state.StillFrames + 1u, 100000u);
            if (safeDegrees < kStillDegrees) state.SettledFrames = std::min(state.SettledFrames + 1u, 100000u);
            else state.SettledFrames = 0u;
        }
        state.Moving = moving;
        state.Armed = state.LastBoutPeak >= kArmDegrees;
        const bool active = enabled && state.Armed && state.MotionFrames <= kWindowFrames;
        const bool settled = !moving && safeDegrees < kStillDegrees && state.SettledFrames >= kSettledFrames;
        const bool refresh = enabled && settled && (state.Frame - state.LastSampleFrame) >= kSampleFrames;

        // The keyframe this frame writes (if any) takes the next physical slot; the ring's contents are then laid
        // out in priority order: keyframes captured before the motion frame that just ended come first (they cannot
        // carry that burst's own excess), newest first, then the rest, newest first.
        // Recall consumes the OLD slot data. The GPU captures this frame only after recall,
        // so defer publishing the new camera metadata until the constants are complete.
        const uint32_t writeSlice = refresh ? state.WriteIndex : kRingSize;
        uint32_t order[kRingSize]; uint32_t count = 0;
        const uint64_t lastMotionFrame = state.Frame - state.MotionFrames;
        for (int pass = 0; pass < 2; ++pass)
        {
            // Newest first WITHIN a group: the physical slot order only matches the capture order until the ring
            // wraps (SA15 L2), and with the wrong order an old key is tried before the newer ones. Measured
            // (SA18 2026-10-20): 2405 f92's frame ratio 0.810 -> 0.764 and the applied correction 6.2 % -> 4.0 %.
            uint32_t group[kRingSize]; uint32_t groupCount = 0;
            for (int i = 0; i < int(kRingSize); ++i)
            {
                const auto& slot = state.Ring[i];
                if (!slot.Valid) continue;
                const bool preBurst = slot.CaptureFrame < lastMotionFrame;
                if ((pass == 0) != preBurst) continue;
                group[groupCount++] = uint32_t(i);
            }
            std::sort(group, group + groupCount, [&state](uint32_t a, uint32_t b) {
                return state.Ring[a].CaptureFrame > state.Ring[b].CaptureFrame; });
            for (uint32_t i = 0; i < groupCount; ++i) order[count++] = group[i];
        }

        stats.Projection = {DirectX::XMVectorGetX(currentProjection.r[0]), DirectX::XMVectorGetY(currentProjection.r[1]),
                            DirectX::XMVectorGetZ(currentProjection.r[0]), DirectX::XMVectorGetZ(currentProjection.r[1])};
        stats.Extra = {DirectX::XMVectorGetZ(currentProjection.r[3]), kDepthTolerance,
                       active ? 1.0f : 0.0f, refresh ? 1.0f : 0.0f};
        stats.Params = {std::clamp(strength, kStrengthMin, kStrengthMax), kMinStatic, kMinRecall, float(kRingSize)};
        uint32_t* slices = &stats.KeySlice[0].x;
        for (uint32_t k = 0; k < kRingSize; ++k) slices[k] = k < count ? order[k] : kRingSize;
        DirectX::XMFLOAT4X4 previous {};
        DirectX::XMStoreFloat4x4(&previous, LoadDesc(previousView) * DirectX::XMMatrixInverse(nullptr, currentView));
        stats.PrevRelative = previous;
        // Row by row, the convention the static-cell test consumes (the same rows the relative matrices use).
        for (int row = 0; row < 4; ++row)
            std::memcpy(&stats.ProjectionRows.m[row][0], &currentProjection.r[row], sizeof(float) * 4);
        for (uint32_t k = 0; k < kRingSize; ++k)
        {
            DirectX::XMFLOAT4X4 relative {};
            float keyP32 = 0.0f;
            const bool valid = k < count;
            if (valid)
            {
                const auto& slot = state.Ring[order[k]];
                const DirectX::XMMATRIX keyView = LoadDesc(slot.View);
                const DirectX::XMMATRIX keyProjection = LoadDesc(slot.Projection);
                DirectX::XMStoreFloat4x4(&relative, keyProjection * keyView *
                    DirectX::XMMatrixInverse(nullptr, currentView));
                keyP32 = DirectX::XMVectorGetZ(keyProjection.r[3]);
            }
            // SLOT-indexed, not priority-indexed (SA22, 2026-10-20): KeySlice[k] carries the ring slot and the
            // shader reads KeyRel[slot]/SlotExtra[slot], so storing at the priority position made the recall
            // reproject with another keyframe's camera whenever the priority order was not the identity (i.e. on
            // every frame after the ring wraps). The unused slot entries stay zero and are never referenced.
            const uint32_t store = valid ? order[k] : k;
            stats.Relative[store] = relative;
            stats.SlotExtra[store] = {keyP32, valid ? 1.0f : 0.0f, 0.0f, 0.0f};
        }
        gain.Params = {kBandA, kBandTau, kCapExtra, kCapHard};
        gain.Params2 = {std::clamp(strength, kStrengthMin, kStrengthMax), kFallbackA, kTapStepCells, kCoverageTaps};
        gain.Params3 = {kRejectMult, kRejectAbs, kGainLow, float(state.MotionFrames)};
        gain.Params4 = {refresh ? 1.0f : 0.0f, float(writeSlice), float(kRingSize), 0.0f};
        if (refresh)
        {
            auto& slot = state.Ring[writeSlice];
            slot.View = view;
            slot.Projection = projection;
            slot.Valid = true;
            slot.CaptureFrame = state.Frame;
            state.WriteIndex = (state.WriteIndex + 1u) % kRingSize;
            state.LastSampleFrame = state.Frame;
        }
        return active;
    }

    // Fills the descriptor-sized part of the constants that depends on the render size (the passes are size bound
    // and rebuilt on a resolution change, so this runs on every frame the anchor is enabled).
    inline void SetSize(StatsRecallConstants& stats, GainConstants& gain, ApplyConstants& apply,
        uint32_t width, uint32_t height)
    {
        const float cellsX = float(std::max(1u, width / 8u)), cellsY = float(std::max(1u, height / 8u));
        stats.Size = {float(width), float(height), cellsX, cellsY};
        gain.Size = {float(width), float(height), cellsX, cellsY};
        apply.Size = {float(width), float(height), 1.0f / float(std::max(1u, width)),
                      1.0f / float(std::max(1u, height))};
    }
}
