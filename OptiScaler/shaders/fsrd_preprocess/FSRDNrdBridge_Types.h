#pragma once
#include <d3d12.h>
#include <DirectXMath.h>
#include <cstdint>
#include <cmath>
#include <string>
#include "upscalers/fsr31/FSRDCameraMatrices.h"

namespace NrdBridge
{
enum class Role : uint8_t { None, PrepLast, Recon, PrePass, Temporal, Chain3, HistSave, HistFix, Clamp, ATrous, Consumer, MaterialGuide, MaterialRead };
enum class DebugMode : uint8_t { Off, RawSignals, RRInputs };
enum class SignalEncoding : uint8_t { Rgb, YCoCg };
// Deprecated compatibility input: the RR bridge never uses native NRD denoised RGB.
inline float NormalizeNativeSpecularBlend(float) noexcept
{
    return 0.0f;
}
struct TitleSignalConstants
{
    ID3D12Resource* resource = nullptr; // Optional diagnostic identity; native flag capture never dereferences or retains it.
    D3D12_GPU_VIRTUAL_ADDRESS address = 0;
    ID3D12DescriptorHeap* nativeHeap = nullptr;
    D3D12_GPU_DESCRIPTOR_HANDLE cbvHandle {};
    uint32_t wordIndex = 303; // Exact consumer ABI: compute word303 or pixel-composition word36.
};
// Run a prepared, infallible output recording while the coordinator ticket is
// still admitted. A plain callback needs no allocation after provider dispatch.
struct OutputCommitGuard
{
    using Action = void (*)(void*) noexcept;
    void* state = nullptr;
    bool (*admit)(void*, Action, void*) noexcept = nullptr;
};
struct Resources
{
    ID3D12Resource* inputSpec = nullptr;
    ID3D12Resource* inputDiff = nullptr;
    ID3D12Resource* normals = nullptr;
    ID3D12Resource* viewDepth = nullptr;
    ID3D12Resource* reconSpec = nullptr;
    ID3D12Resource* reconDiff = nullptr;
    ID3D12Resource* motion = nullptr;
    ID3D12Resource* outputSpec = nullptr;
    ID3D12Resource* outputDiff = nullptr;
    uint32_t width = 0, height = 0;
};
struct ConversionInputs
{
    ID3D12Resource* reconSpec = nullptr;
    ID3D12Resource* reconDiff = nullptr;
    ID3D12Resource* normals = nullptr;
    ID3D12Resource* viewDepth = nullptr;
    ID3D12Resource* motion = nullptr;
    ID3D12Resource* nativeMaterial = nullptr; // Owned same-recording baseColorLinear/metal snapshot.
    ID3D12Resource* nativeMaterialRoughness = nullptr; // Optional owned R16F raw materialParams.G, COMMON before/after conversion.
};
// Both resources are borrowed only while recording; constants is bridge-owned and GPU-leased.
struct NativeMotionSource
{
    ID3D12Resource* constants = nullptr;
    ID3D12Resource* viewDepth = nullptr;
};
struct ConvertedResources
{
    ID3D12Resource* spec = nullptr;
    ID3D12Resource* diff = nullptr;
    ID3D12Resource* linearDepth = nullptr;
    ID3D12Resource* motion = nullptr;
    ID3D12Resource* normals = nullptr;
    ID3D12Resource* specAlbedo = nullptr;
    ID3D12Resource* diffAlbedo = nullptr;
    ID3D12Resource* validity = nullptr; // R8_UINT depth-validity class from the geometry pass; null on the legacy conversion path.
    uint32_t width = 0, height = 0;
    bool materialGuidesApplied = false; // Actual conversion input admission, not the requested checkbox.
};
struct FrameParameters
{
    FSRDCamera::Matrices camera {};
    float nearPlane = 0.01f, farPlane = 65504.0f, depthSign = -1.0f;
    DirectX::XMFLOAT2 motionScale {1.0f, 1.0f};
    DirectX::XMFLOAT2 jitter {}, previousJitter {};
    DirectX::XMFLOAT3 cameraPosition {}, previousCameraPosition {};
    uint32_t streamlineFrame = UINT32_MAX, frameIndex = 0;
    bool motionVectorsJittered = false, motionVectors3D = false;
    bool reset = true, previousValid = false;
    bool nativeMaterialGuides = false; // Same-writer material cues; no further lighting demodulation.
    bool nativeTemporalMotion = false; // Same-binding native Temporal surface reprojection, captured with Recon.
    bool cameraProjectedDepthDelta = false; // Requested camera-only B (now the default); kept for the Recon ticket flow.
    bool legacyMotionDepth = false; // A/B rollback: pre-fix previous-visible-depth B instead of camera-only.
    bool preserveNativeMaterialIDs = false; // Experimental native categorical A; capture with the Recon ticket.
    float nativeSpecularBlend = 0.0f; // Deprecated source ABI; ignored and canonicalized to positive zero.
    SignalEncoding outputEncoding = SignalEncoding::Rgb;
    TitleSignalConstants outputConstants {};
};
// Host-side motion-Z provenance of finalized motion dispatches for one
// conversion domain. This is the frame-level effective path; per-pixel
// populations need a user-armed GPU capture, never a synchronous readback.
struct MotionProvenanceTotals
{
    uint64_t dispatches = 0, native = 0, cameraOnly = 0, unknown = 0, legacyVisible = 0;
};
}
