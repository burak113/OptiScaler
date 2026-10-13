#pragma once
#include <d3d12.h>
#include <DirectXMath.h>
#include <cstdint>
#include <string>
#include "upscalers/fsr31/FSRDCameraMatrices.h"

namespace NrdBridge
{
enum class Role : uint8_t { None, PrepLast, Recon, PrePass, Temporal, Chain3, HistSave, HistFix, Clamp, ATrous, Consumer };
enum class DebugMode : uint8_t { Off, RawSignals, RRInputs };
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
};
}
