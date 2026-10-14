#pragma once
#include "FSRDNrdBridge_Types.h"
#include <wrl/client.h>
#include <cstring>

namespace NrdBridge
{
inline bool ValidateTitleSignalConstants(const TitleSignalConstants& constants, ID3D12Device* device, std::string& error)
{
    if (!constants.resource && !constants.address) return true;
    if (!constants.resource || !constants.address || (constants.address & 255u))
    { error = "NRD Consumer CB6 resource/VA is missing or unaligned"; return false; }
    const auto desc = constants.resource->GetDesc();
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER)
    { error = "NRD Consumer CB6 must be a buffer"; return false; }
    const auto base = constants.resource->GetGPUVirtualAddress();
    if (!base || constants.address < base || constants.address - base > desc.Width ||
        desc.Width - (constants.address - base) < 76u * 16u)
    { error = "NRD Consumer CB6 VA range does not cover register75.w"; return false; }
    Microsoft::WRL::ComPtr<ID3D12Device> actual;
    Microsoft::WRL::ComPtr<IUnknown> expectedIdentity, actualIdentity;
    if (!device || FAILED(constants.resource->GetDevice(IID_PPV_ARGS(&actual))) ||
        FAILED(device->QueryInterface(IID_PPV_ARGS(&expectedIdentity))) ||
        FAILED(actual.As(&actualIdentity)) || expectedIdentity.Get() != actualIdentity.Get())
    { error = "NRD Consumer CB6 device mismatch"; return false; }
    return true;
}

inline bool CreateZeroSignalConstants(ID3D12Device* device, Microsoft::WRL::ComPtr<ID3D12Resource>& result, std::string& error)
{
    constexpr uint32_t kBytes = 1536; // 76 registers rounded to a 256-byte CBV boundary.
    D3D12_RESOURCE_DESC desc {}; desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = kBytes; desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1;
    desc.SampleDesc.Count = 1; desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    D3D12_HEAP_PROPERTIES heap {}; heap.Type = D3D12_HEAP_TYPE_UPLOAD;
    const auto code = device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
        D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&result));
    if (FAILED(code)) { error = "NRD fallback CB6 creation failed (HRESULT " + std::to_string(code) + ")"; return false; }
    void* mapped = nullptr; D3D12_RANGE noRead {0,0};
    if (FAILED(result->Map(0, &noRead, &mapped)))
    { error = "NRD fallback CB6 initialization failed"; return false; }
    std::memset(mapped, 0, kBytes); result->Unmap(0, nullptr);
    return true;
}
}
