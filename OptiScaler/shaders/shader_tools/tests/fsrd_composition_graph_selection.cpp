#include "../../fsrd_preprocess/FSRDCompositionVariant.h"
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>

int main(int argc, char** argv)
{
    using namespace FSRD::Composition;
    if (argc == 6 && std::string(argv[1]) == "--select")
    {
        const auto flags = std::strtoul(argv[2], nullptr, 0);
        const auto detail = std::strtof(argv[3], nullptr);
        const auto recovery = std::strtoul(argv[4], nullptr, 0);
        const auto light = std::strtoul(argv[5], nullptr, 0);
        if (CanSplitTiles(flags, detail, recovery, light)) std::cout << "Split";
        else switch (ChoosePipeline(flags, detail, recovery, light))
        {
        case PipelineVariant::Light: std::cout << "FSRDOutputCompLight"; break;
        case PipelineVariant::NoRecovery: std::cout << "FSRDOutputCompNoRecovery"; break;
        default: std::cout << "FSRDOutputComp"; break;
        }
        std::cout << '\n';
        return 0;
    }
    unsigned checks = 0;
    for (unsigned flags : {0u,1u,2u,3u,1u<<16,(1u<<16)|(19u<<17)})
        for (float detail : {-1.f,0.f,.35f,1.f,std::numeric_limits<float>::infinity(),
                              -std::numeric_limits<float>::infinity(),std::numeric_limits<float>::quiet_NaN()})
            for (unsigned recovery=0; recovery<16; ++recovery)
                for (unsigned light=0; light<16; ++light)
                {
                    bool anchorClass=false, lightClass=false;
                    for (unsigned bit=0; bit<3; ++bit) if ((recovery>>bit)&1)
                    {
                        anchorClass |= !((light>>bit)&1);
                        lightClass |= ((light>>bit)&1)!=0;
                    }
                    const bool expected = !(flags&((1u<<16)|1u)) && std::isfinite(detail) && detail>0 &&
                                          recovery<8 && light<8 && anchorClass && lightClass;
                    if (CanSplitTiles(flags, detail, recovery, light) != expected) return 1;
                    ++checks;
                }
    std::cout << "split selector checks=" << checks << " passed\n";
}
