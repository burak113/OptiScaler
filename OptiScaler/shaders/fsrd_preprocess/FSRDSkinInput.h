#pragma once
#include <d3d12.h>
#include <cstdint>

namespace FSRD
{
    // Typed SRVs must preserve a signed floating-point guide. A present binding
    // is not enough: reject incompatible views and out-of-range subrectangles.
    inline bool CompatibleSkinInput(bool present, const D3D12_RESOURCE_DESC& desc,
                                    DXGI_FORMAT viewFormat, uint32_t baseX, uint32_t baseY,
                                    uint32_t width, uint32_t height, bool scalar)
    {
        if (!present || width == 0 || height == 0 ||
            desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.DepthOrArraySize != 1 ||
            desc.SampleDesc.Count != 1 || desc.MipLevels == 0 ||
            (desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) != 0 ||
            baseX > desc.Width || baseY > desc.Height ||
            uint64_t(width) > desc.Width - baseX || uint64_t(height) > uint64_t(desc.Height) - baseY)
            return false;
        if (scalar)
            return viewFormat == DXGI_FORMAT_R16_FLOAT || viewFormat == DXGI_FORMAT_R32_FLOAT ||
                   viewFormat == DXGI_FORMAT_R16G16B16A16_FLOAT || viewFormat == DXGI_FORMAT_R32G32B32A32_FLOAT;
        return viewFormat == DXGI_FORMAT_R16G16B16A16_FLOAT || viewFormat == DXGI_FORMAT_R32G32B32A32_FLOAT ||
               viewFormat == DXGI_FORMAT_R11G11B10_FLOAT || viewFormat == DXGI_FORMAT_R8G8B8A8_UNORM;
    }
}
