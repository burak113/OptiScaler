#include "../../fsrd_preprocess/FSRDCompositionVariant.h"
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>

using FSRD::Composition::ChoosePipeline;
using FSRD::Composition::PipelineVariant;

const char* Name(PipelineVariant value)
{
    switch (value)
    {
    case PipelineVariant::Light: return "FSRDOutputCompLight";
    case PipelineVariant::NoRecovery: return "FSRDOutputCompNoRecovery";
    default: return "FSRDOutputComp";
    }
}

int main(int argc, char** argv)
{
    if (argc == 6 && std::string(argv[1]) == "--select")
    {
        std::cout << Name(ChoosePipeline(std::strtoul(argv[2], nullptr, 0),
                         std::strtof(argv[3], nullptr), std::strtoul(argv[4], nullptr, 0),
                         std::strtoul(argv[5], nullptr, 0))) << '\n';
        return 0;
    }
    unsigned checked = 0;
    for (uint32_t flags : {0u, 1u, 2u, 3u, 1u << 16, (1u << 16) | (24u << 17),
                           3u | (1u << 16) | (19u << 17)})
        for (float detail : {-1.f, 0.f, .35f, 1.f, 2.f,
                             std::numeric_limits<float>::infinity(),
                             -std::numeric_limits<float>::infinity(),
                             std::numeric_limits<float>::quiet_NaN()})
            for (uint32_t recovery = 0; recovery != 16; ++recovery)
                for (uint32_t light = 0; light != 16; ++light)
                {
                    const auto selected = ChoosePipeline(flags, detail, recovery, light);
                    PipelineVariant expected = PipelineVariant::Generic;
                    if ((flags & ((1u << 16) | 1u)) == 0)
                    {
                        // Independently enumerate selected classes and whether any
                        // can send radiance to the original Anchor branch.
                        if (detail <= 0 || recovery == 0) expected = PipelineVariant::NoRecovery;
                        else if (std::isfinite(detail) && recovery < 8 && light < 8)
                        {
                            bool hasAnchor = false;
                            for (unsigned bit = 0; bit != 3; ++bit)
                                hasAnchor |= ((recovery >> bit) & 1) && !((light >> bit) & 1);
                            if (!hasAnchor) expected = PipelineVariant::Light;
                        }
                    }
                    if (selected != expected)
                    {
                        std::cerr << "unsafe composition selection: flags=" << flags
                                  << " detail=" << detail << " recovery=" << recovery
                                  << " light=" << light << '\n';
                        return 1;
                    }
                    ++checked;
                }
    std::cout << "selector checks=" << checked << " passed\n";
}
