#pragma once
#include <cstdint>

namespace FSRD
{
    struct SkinExtent { uint32_t x, y; };
    constexpr bool CanFuseSssInput(uint32_t mode, bool floorEnabled, bool inputChroma,
                                   bool debug, bool capture, bool basesMatch, bool depthSourceValid)
    {
        return mode == 1u && !floorEnabled && !inputChroma && !debug && !capture &&
            basesMatch && depthSourceValid;
    }
    constexpr uint32_t SkinDivideUp(uint32_t value, uint32_t divisor)
    {
        return value / divisor + (value % divisor != 0u);
    }
    constexpr SkinExtent SkinBoundsExtent(uint32_t width, uint32_t height, uint32_t tile)
    {
        return {SkinDivideUp(width, tile), SkinDivideUp(height, tile)};
    }
    constexpr SkinExtent SssKernelExtent(uint32_t width, uint32_t height)
    {
        const auto columns = SkinDivideUp(width, 32u);
        return {(columns < 128u ? columns : 128u) * 66u,
                SkinDivideUp(height, 32u) * SkinDivideUp(columns, 128u)};
    }
    constexpr SkinExtent SssKernelDispatch(uint32_t width, uint32_t height)
    {
        return {8u * SkinDivideUp(width, 32u), 8u * SkinDivideUp(height, 32u)};
    }
    constexpr SkinExtent SssBlurDispatch(uint32_t width, uint32_t height, bool vertical)
    {
        return {8u * SkinDivideUp(width, vertical ? 16u : 32u),
                8u * SkinDivideUp(height, vertical ? 32u : 16u)};
    }
    // ComputeState dispatches ceil(extent / 8); the shader maps each group to
    // 32x8 output pixels horizontally and 8x32 vertically.
    constexpr SkinExtent SkinPrefilterDispatch(uint32_t width, uint32_t height, bool vertical)
    {
        return {8u * SkinDivideUp(width, vertical ? 8u : 32u),
                8u * SkinDivideUp(height, vertical ? 32u : 8u)};
    }
}
