#pragma once

#include <d3d12.h>
#include <wrl/client.h>
#include "Util.h"

namespace NrdBridgeDevice
{
// Streamline's private interface returns a borrowed native object. Hold the
// queried device while installing hooks or comparing its canonical identity.
inline Microsoft::WRL::ComPtr<ID3D12Device> Native(ID3D12Device* device) noexcept
{
    Microsoft::WRL::ComPtr<ID3D12Device> native;
    if (!device) return native;
    try
    {
        IUnknown* object = nullptr;
        if (Util::CheckForRealObject("NRD bridge device", device, &object) && object)
            object->QueryInterface(IID_PPV_ARGS(&native));
        else
            native = device;
    }
    catch (...) { native.Reset(); }
    return native;
}

inline bool Same(ID3D12Device* first, ID3D12Device* second) noexcept
{
    if (!first || !second) return false;
    Microsoft::WRL::ComPtr<IUnknown> a, b;
    return SUCCEEDED(first->QueryInterface(IID_PPV_ARGS(&a))) &&
           SUCCEEDED(second->QueryInterface(IID_PPV_ARGS(&b))) && a.Get() == b.Get();
}

inline bool Selected(ID3D12Device* native, ID3D12Device* selected) noexcept
{
    const auto title = Native(selected);
    return Same(native, title.Get());
}
}
