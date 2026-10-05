#pragma once
// Isolate application/UI dependencies while compiling the production shader .cpp files.
// Queue, Reset and lifetime adapters below are invoked explicitly; game detours are not tested.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <d3dx/d3dx12.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <functional>
#include <initializer_list>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>
#include "../../../misc/RecordedComputeLease_Dx12.h"

#define LOG_ERROR(...) ((void) 0)
#define LOG_WARN(...) ((void) 0)
#define LOG_DEBUG(...) ((void) 0)
#define SAFE_RELEASE(value) do { if (value) { (value)->Release(); (value) = nullptr; } } while (false)

namespace Util { inline void GetDeviceRemovedReason(ID3D12Device*) {} }
struct State
{
    bool isShuttingDown = false;
    static State& Instance() { static State state; return state; }
};
template <typename T> struct ShaderTestSetting
{
    std::optional<T> value;
    T fallback;
    bool has_value() const { return value.has_value(); }
    T value_or(T other) const { return value.value_or(other); }
    T value_or_default() const { return value.value_or(fallback); }
};
struct Config
{
    ShaderTestSetting<bool> UsePrecompiledShaders { {}, true }, MagnifierEnabled { {}, true };
    ShaderTestSetting<float> MagnifierStaticPosX { 50.f, 50.f }, MagnifierStaticPosY { 50.f, 50.f };
    ShaderTestSetting<float> MagnifierCursorOffsetX { {}, 0.f }, MagnifierCursorOffsetY { {}, 0.f };
    ShaderTestSetting<float> MagnifierSize { {}, 30.f }, MagnifierBorderSize { {}, 3.f };
    ShaderTestSetting<int> MagnifierZoomFactor { {}, 2 };
    static Config* Instance() { static Config config; return &config; }
};
struct MenuOverlayBase { static bool IsVisible() { return false; } };
namespace OptiInput { inline POINT GetMouseScreenPos() { return {}; } }

// Timestamp-ring accuracy is independent of dispatch storage lifetime.
struct GpuTime_Dx12
{
    static inline unsigned starts = 0;
    explicit GpuTime_Dx12(ID3D12Device*) {}
    void Start(ID3D12GraphicsCommandList*) { ++starts; }
    void End(ID3D12GraphicsCommandList*) {}
    std::optional<double> ReadGpuTime(ID3D12CommandQueue*) { return {}; }
};
struct ScopedGpuTime_Dx12
{
    ScopedGpuTime_Dx12(GpuTime_Dx12* timer, ID3D12GraphicsCommandList* list) { timer->Start(list); }
};
struct ScopedSkipHeapCapture {};

inline ID3DBlob* CompileShader(const char*, const char*, const char*)
{
    throw std::runtime_error("This fixture requires the production precompiled shader");
}
struct ResTrack_Dx12
{
    static bool RetainComputeDispatch(ID3D12Device* device, ID3D12GraphicsCommandList* list,
                                     const std::shared_ptr<void>& lease,
                                     std::function<void(ID3D12CommandQueue*)> beforeSubmit = {})
    {
        if (!device || !list || !lease || !RecordedComputeLease::Available()) return false;
        if (list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT &&
            list->GetType() != D3D12_COMMAND_LIST_TYPE_COMPUTE) return false;
        Microsoft::WRL::ComPtr<ID3D12Device> listDevice;
        Microsoft::WRL::ComPtr<IUnknown> deviceIdentity, listDeviceIdentity, identity;
        if (FAILED(list->GetDevice(IID_PPV_ARGS(&listDevice))) ||
            FAILED(device->QueryInterface(IID_PPV_ARGS(&deviceIdentity))) ||
            FAILED(listDevice.As(&listDeviceIdentity)) || listDeviceIdentity.Get() != deviceIdentity.Get() ||
            FAILED(list->QueryInterface(IID_PPV_ARGS(&identity)))) return false;
        return RecordedComputeLease::Track(identity.Get(),
            { list, static_cast<ID3D12CommandList*>(list), identity.Get() }, lease, std::move(beforeSubmit));
    }
};
