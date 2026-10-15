#pragma once
#include <d3d12.h>
#include <DirectXMath.h>
#include <cstdint>
#include <cmath>
#include <string>
#include "upscalers/fsr31/FSRDCameraMatrices.h"

namespace NrdBridge
{
enum class Role : uint8_t { None, PrepLast, Recon, PrePass, Temporal, Chain3, HistSave, HistFix, Clamp, ATrous, Consumer };
enum class DebugMode : uint8_t { Off, RawSignals, RRInputs };
enum class SignalEncoding : uint8_t { Rgb, YCoCg };
// Optional NRD-assisted specular reference; malformed values disable the hybrid.
inline float NormalizeNativeSpecularBlend(float value) noexcept
{
    if (!std::isfinite(value) || value <= 0.0f) return 0.0f;
    return value >= 1.0f ? 1.0f : value;
}
struct TitleSignalConstants
{
    ID3D12Resource* resource = nullptr; // Optional diagnostic identity; native flag capture never dereferences or retains it.
    D3D12_GPU_VIRTUAL_ADDRESS address = 0;
    ID3D12DescriptorHeap* nativeHeap = nullptr;
    D3D12_GPU_DESCRIPTOR_HANDLE cbvHandle {};
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
    uint32_t width = 0, height = 0;
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
    bool nativeTemporalMotion = false; // Same-binding native Temporal surface reprojection, captured with Recon.
    bool cameraProjectedDepthDelta = false; // Experimental camera-only B; capture with the Recon ticket.
    bool preserveNativeMaterialIDs = false; // Experimental native categorical A; capture with the Recon ticket.
    float nativeSpecularBlend = 0.0f; // Commit-only; capture the coherent setting immediately before Consumer.
    SignalEncoding outputEncoding = SignalEncoding::Rgb;
    TitleSignalConstants outputConstants {};
};
}
