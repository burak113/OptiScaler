#include "../../fsrd_preprocess/FSRDSkinInput.h"
#include <cassert>
#include <iostream>
int main()
{
    D3D12_RESOURCE_DESC d {};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = 132; d.Height = 68; d.DepthOrArraySize = 1; d.MipLevels = 1; d.SampleDesc.Count = 1;
    const auto valid = [&](bool present = true, DXGI_FORMAT fmt = DXGI_FORMAT_R16_FLOAT,
                           unsigned x = 4, unsigned y = 4, unsigned w = 128, unsigned h = 64) {
        return FSRD::CompatibleSkinInput(present, d, fmt, x, y, w, h, true);
    };
    assert(valid()); assert(valid(true, DXGI_FORMAT_R32_FLOAT));
    assert(valid(true, DXGI_FORMAT_R16G16B16A16_FLOAT));
    assert(!valid(false)); assert(!valid(true, DXGI_FORMAT_R16_UINT));
    assert(!valid(true, DXGI_FORMAT_R8_UNORM));
    assert(!valid(true, DXGI_FORMAT_R16_FLOAT, 5));
    assert(!valid(true, DXGI_FORMAT_R16_FLOAT, 4, 5));
    assert(!valid(true, DXGI_FORMAT_R16_FLOAT, 0xffffffffu));
    assert(!valid(true, DXGI_FORMAT_R16_FLOAT, 4, 4, 0));
    d.SampleDesc.Count = 4; assert(!valid()); d.SampleDesc.Count = 1;
    d.DepthOrArraySize = 2; assert(!valid()); d.DepthOrArraySize = 1;
    d.Flags = D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE; assert(!valid()); d.Flags = D3D12_RESOURCE_FLAG_NONE;
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE3D; assert(!valid());
    std::cout << "skin input compatibility: 14 checks, 0 failures\n";
}
