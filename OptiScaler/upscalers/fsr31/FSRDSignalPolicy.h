#pragma once
#include <algorithm>
#include <array>
#include <cstdint>

namespace FSRDSignals
{
enum Type : int
{
    DirectDiffuse,
    DirectSpecular,
    IndirectDiffuse,
    IndirectSpecular
};
constexpr uint32_t Bit(int type) { return type >= 0 && type < 4 ? 1u << type : 0u; }
constexpr uint32_t All = 15u;
constexpr std::array<int, 4> Preferred { DirectDiffuse, IndirectSpecular, DirectSpecular, IndirectDiffuse };
constexpr const char* Names[] { "Direct Diffuse", "Direct Specular", "Indirect Diffuse", "Indirect Specular" };
constexpr int Count(uint32_t mask)
{
    return int((mask & 1u) != 0) + int((mask & 2u) != 0) + int((mask & 4u) != 0) + int((mask & 8u) != 0);
}
constexpr uint32_t Available(bool specularDistance, bool rayDistance, bool approximateSpec, bool approximateRay)
{
    return Bit(DirectDiffuse) | Bit(DirectSpecular) |
           ((specularDistance || approximateSpec) ? Bit(IndirectSpecular) : 0u) |
           ((rayDistance || approximateRay) ? Bit(IndirectDiffuse) : 0u);
}
struct Layout
{
    std::array<int, 4> slots { -1, -1, -1, -1 };
    uint32_t mask = 0;
    int count = 0;
};
// Keep valid requested assignments first. Fill missing/duplicate entries only after
// reserving later valid slots, so a missing guide cannot steal another slot's signal.
constexpr Layout Resolve(int count, std::array<int, 4> requested, uint32_t available = All)
{
    Layout result;
    count = std::clamp(count, 1, 4);
    available &= All;
    for (int i = 0; i < count; ++i)
        if ((available & Bit(requested[i])) && !(result.mask & Bit(requested[i])))
        {
            result.slots[i] = requested[i];
            result.mask |= Bit(requested[i]);
        }
    for (int i = 0; i < count; ++i)
        if (result.slots[i] < 0)
        {
            const int direct = requested[i] == IndirectSpecular  ? DirectSpecular
                               : requested[i] == IndirectDiffuse ? DirectDiffuse
                                                                 : -1;
            if ((available & Bit(direct)) && !(result.mask & Bit(direct)))
            {
                result.slots[i] = direct;
                result.mask |= Bit(direct);
                continue;
            }
            for (int candidate : Preferred)
                if ((available & Bit(candidate)) && !(result.mask & Bit(candidate)))
                {
                    result.slots[i] = candidate;
                    result.mask |= Bit(candidate);
                    break;
                }
        }
    // Compact the assignments if a previously saved 3/4-signal mode loses a guide.
    auto slots = result.slots;
    result.slots.fill(-1);
    for (int slot : slots)
        if (slot >= 0)
            result.slots[result.count++] = slot;
    return result;
}
constexpr bool SupportsUnsupportedAlbedo(uint32_t mask)
{
    return (mask & (Bit(DirectSpecular) | Bit(IndirectSpecular))) == (Bit(DirectSpecular) | Bit(IndirectSpecular)) &&
           (mask & (Bit(DirectDiffuse) | Bit(IndirectDiffuse))) != 0;
}
} // namespace FSRDSignals
