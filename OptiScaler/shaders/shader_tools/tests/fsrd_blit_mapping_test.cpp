#include "../../fsrd_preprocess/FSRDBlitMapping.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <vector>

static unsigned checks = 0;
#define CHECK(...)                                                                                                     \
    do                                                                                                                 \
    {                                                                                                                  \
        ++checks;                                                                                                      \
        if (!(__VA_ARGS__))                                                                                            \
        {                                                                                                              \
            std::cerr << "FAIL line " << __LINE__ << ": " #__VA_ARGS__ "\n";                                           \
            std::exit(1);                                                                                              \
        }                                                                                                              \
    } while (false)

using namespace FSRDBlitMapping;

// The shader's sampling on one axis: bilinear with a clamp-to-edge sampler.
static std::vector<float> Blit(const std::vector<float>& row, float base, float logical, int dst)
{
    const float physical = float(row.size());
    const Axis axis = Resolve(logical, base, physical, float(dst));
    std::vector<float> out;
    for (int p = 0; p < dst; ++p)
    {
        const float uv = ((p + 0.5f) / dst) * axis.scale + axis.offset;
        const float x = std::clamp(uv * physical - 0.5f, 0.0f, physical - 1.0f);
        const int i = int(std::floor(x));
        const int j = std::min(i + 1, int(row.size()) - 1);
        const float f = x - i;
        out.push_back(row[i] * (1.0f - f) + row[j] * f);
    }
    return out;
}

// float UV arithmetic; a single sentinel texel (+-1000) leaking in would be off by far more.
static bool Near(float a, float b) { return std::fabs(a - b) < 1e-2f; }

int main()
{
    // The report's row: the logical [1,1] sits between two sentinels.
    for (float v : Blit({ 100, 1, 1, 100 }, 1, 2, 4))
        CHECK(Near(v, 1.0f));
    // Every magnification of a sentinel-framed subrect stays inside it.
    for (int logical = 1; logical <= 9; ++logical)
        for (int base = 0; base <= 3; ++base)
            for (int dst = logical; dst <= 4 * logical + 3; ++dst)
            {
                std::vector<float> row(base, 1000.0f);
                for (int k = 0; k < logical; ++k)
                    row.push_back(float(k));
                row.resize(row.size() + 3, -1000.0f);
                const auto out = Blit(row, float(base), float(logical), dst);
                for (float v : out)
                    CHECK(v >= -1e-2f && v <= logical - 1 + 1e-2f);
                CHECK(Near(out.front(), 0.0f) && Near(out.back(), float(logical - 1)));
            }
    // 1:1 and minification keep the original half-pixel mapping exactly.
    for (float logical : { 4.0f, 1280.0f })
        for (float dst : { logical, logical / 2 })
        {
            const Axis a = Resolve(logical, 64.0f, 2048.0f, dst);
            CHECK(Near(a.scale, logical / 2048.0f) && Near(a.offset, 64.0f / 2048.0f));
        }
    // 1:1 copies texel centres.
    const auto copy = Blit({ 7, 1, 2, 3, 9 }, 1, 3, 3);
    CHECK(Near(copy[0], 1) && Near(copy[1], 2) && Near(copy[2], 3));
    std::cout << "PASS: " << checks << " FSRD blit mapping checks\n";
}
