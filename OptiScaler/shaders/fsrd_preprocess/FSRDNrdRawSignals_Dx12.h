#pragma once
#include "FSRDNrdBridge_Types.h"
#include <memory>

namespace RecordedComputeLease { struct Recording; }
namespace NrdBridge
{
// Profiles name proved native instruction addressing, never CPU guesses about CB values.
enum class NativeRawProfile : uint32_t { Unknown = 0, ReconDirect = 1, PrePassPending = 2 };
struct RawSignalSource
{
    ID3D12DescriptorHeap* nativeHeap = nullptr;
    D3D12_GPU_DESCRIPTOR_HANDLE specSrv {}, diffSrv {};
    TitleSignalConstants nativeConstants {};
    uint32_t width = 0, height = 0;
    NativeRawProfile profile = NativeRawProfile::Unknown;
};
struct RawSignalRecord;
using RawSignalLease = std::shared_ptr<const RawSignalRecord>;
struct RawSignalSnapshot
{
    // Only bridge-owned resources. The 1536-byte prefix holds exact required CB operands;
    // packed native half4 spec/diff follow at 16 bytes per output pixel, before any codec.
    ID3D12Resource* resource = nullptr;
    D3D12_GPU_VIRTUAL_ADDRESS geometryConstants = 0;
    ID3D12Resource* encodingFlag = nullptr;
    std::shared_ptr<void> owner;
    std::weak_ptr<RecordedComputeLease::Recording> nativeRecording;
    ID3D12GraphicsCommandList* recording = nullptr;
    uint64_t recordingId = 0;
    uint32_t width = 0, height = 0, frameSL = UINT32_MAX, bridgeFrame = 0;
    NativeRawProfile profile = NativeRawProfile::Unknown;
    bool decoded = false;
    D3D12_RESOURCE_STATES state = D3D12_RESOURCE_STATE_COMMON;
    // The executed native303/36 value always lands at owned byte1212. Reuse this
    // GPU value for final encoding so decode and commit cannot select different modes.
    TitleSignalConstants decodedEncodingConstants {};
};
class RawSignalSnapshotPass
{
    friend struct RawSignalRecord;
    struct Impl;
    std::shared_ptr<Impl> impl_;
  public:
    RawSignalSnapshotPass();
    ~RawSignalSnapshotPass();
    bool Initialize(ID3D12Device*, uint32_t width, uint32_t height, std::string& error) noexcept;
    // Caller holds physical Borrow/restoration and proves these exact native SRV
    // slots are shader-readable in this recording. No source transitions/AddRefs.
    bool Capture(ID3D12GraphicsCommandList*, const RawSignalSource&, uint32_t frameSL,
                 uint32_t bridgeFrame, RawSignalLease& out, std::string& error) noexcept;
    bool Decode(ID3D12GraphicsCommandList*, const RawSignalLease&, const ConvertedResources&,
                const TitleSignalConstants&, std::string& error) noexcept;
    static RawSignalSnapshot GetSnapshot(const RawSignalLease&) noexcept;
    uint64_t OwnedBytes() const noexcept;
    uint32_t OwnedSlots() const noexcept;
};
}
