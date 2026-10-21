#pragma once
// Standalone research adapter; deliberately absent from OptiScaler's build.
#include "NativeColourContract.h"
#include <d3d12.h>
#include <atomic>
#include <memory>

namespace NativeColour
{
struct Budget
{
    // A service-owned family survives all retained recordings. These atomics may
    // refer directly to LobeRecovery::Family and its slots; no private bypass.
    std::shared_ptr<void> owner;
    std::atomic<uint64_t>* bytes = nullptr;
    std::atomic<uint64_t>* peakBytes = nullptr;
    std::atomic<uint32_t>* slots = nullptr;
    uint64_t byteLimit = 0;
    uint32_t slotLimit = 0;
};
struct Texture
{
    ID3D12Resource* resource = nullptr;
    // Required pool/graph owner in addition to the COM reference, preventing
    // reuse while commands are in flight. Never pass the enclosing DispatchLease
    // here: that would create a cycle. Pass the original slot/producer owner.
    std::shared_ptr<void> owner;
    Identity identity {};
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
};
struct Inputs
{
    Texture source, rawRR, selected, depth, normalRoughness, authority, support;
    Frame frame {};
    Evidence evidence {};
};
struct Memory
{
    uint64_t defaultAllocationBytes = 0;
    uint64_t uploadAllocationBytes = 0;
    uint64_t descriptorReservationBytes = 0;
    uint64_t budgetChargeBytes = 0;
    uint64_t uploadLogicalBytes = 0;
    std::array<Layout,4> packed {}; // source/raw/selected/output
};

class NativeColourPass
{
    struct Recording;
  public:
    struct Prepared
    {
        std::shared_ptr<Recording> owner;
        ID3D12Resource* output = nullptr; // Owned RGBA16F; enters/leaves UAV.
        ID3D12Resource* diagnostic = nullptr; // Owned RGBA32F; enters/leaves UAV.
        ID3D12Resource* packedOutput = nullptr; // Owned buffer; enters/leaves COPY_DEST.
        Memory memory {};
        Decision decision = Decision::Off;
        explicit operator bool() const noexcept { return owner != nullptr; }
    };
    // All fallible operations, native validation, budget admission and allocation
    // happen here before provider commands. It records ZERO GPU commands.
    // shader must be this package's DXC-built NativeColourPacked.hlsl, CSMain cs_6_2.
    static Decision Prepare(ID3D12Device* device, ID3D12GraphicsCommandList* list,
        const Inputs& inputs, const Config& config, const Budget& budget,
        D3D12_SHADER_BYTECODE shader, Prepared& prepared) noexcept;

    // Pair integration calls CanRecord on BOTH lobes before calling Record for
    // either. Mismatched list/recording/repeated recording returns false without
    // emitting commands. No allocation, validation calls, or fallible work here.
    static bool CanRecord(ID3D12GraphicsCommandList* list, uint64_t recording,
        const Prepared& prepared) noexcept;
    static bool Record(ID3D12GraphicsCommandList* list, uint64_t recording,
        const Prepared& prepared) noexcept;
};
} // namespace NativeColour
