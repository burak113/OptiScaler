#include "../../../upscalers/fsr31/FSRDSignalPolicy.h"
#include <cassert>
#include <iostream>
int main()
{
    using namespace FSRDSignals;
    assert(Resolve(1, { IndirectSpecular, -1, -1, -1 }, Available(false, false, false, false)).mask ==
           Bit(DirectSpecular));
    assert(Resolve(1, { IndirectDiffuse, -1, -1, -1 }, Available(false, false, false, false)).mask ==
           Bit(DirectDiffuse));
    unsigned checks = 0;
    for (int spec = 0; spec < 2; ++spec)
        for (int ray = 0; ray < 2; ++ray)
            for (int approxSpec = 0; approxSpec < 2; ++approxSpec)
                for (int approxRay = 0; approxRay < 2; ++approxRay)
                {
                    const auto available = Available(spec, ray, approxSpec, approxRay);
                    assert(bool(available & Bit(IndirectSpecular)) == bool(spec || approxSpec));
                    assert(bool(available & Bit(IndirectDiffuse)) == bool(ray || approxRay));
                    for (int count = -1; count <= 5; ++count)
                        for (int a = -1; a < 5; ++a)
                            for (int b = -1; b < 5; ++b)
                                for (int c = -1; c < 5; ++c)
                                    for (int d = -1; d < 5; ++d)
                                    {
                                        const std::array<int, 4> requested { a, b, c, d };
                                        const auto layout = Resolve(count, requested, available);
                                        assert(layout.count == std::min(std::clamp(count, 1, 4), Count(available)));
                                        assert(Count(layout.mask) == layout.count);
                                        assert((layout.mask & available) == layout.mask);
                                        uint32_t mask = 0;
                                        for (int i = 0; i < layout.count; ++i)
                                        {
                                            assert(layout.slots[i] >= 0 && layout.slots[i] < 4);
                                            assert(!(mask & Bit(layout.slots[i])));
                                            mask |= Bit(layout.slots[i]);
                                        }
                                        assert(mask == layout.mask);
                                        // Valid user choices must survive fallback, even when a previous slot is
                                        // invalid.
                                        for (int i = 0; i < std::clamp(count, 1, 4); ++i)
                                            if (available & Bit(requested[i]))
                                                assert(layout.mask & Bit(requested[i]));
                                        ++checks;
                                    }
                }
    for (uint32_t mask = 1; mask <= All; ++mask)
    {
        const bool expected = (mask & Bit(DirectSpecular)) && (mask & Bit(IndirectSpecular)) && (mask & 5u);
        assert(SupportsUnsupportedAlbedo(mask) == expected);
    }
    std::cout << checks << " signal-layout cases passed\n";
}
