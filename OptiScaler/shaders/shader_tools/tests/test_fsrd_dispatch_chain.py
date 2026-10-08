"""Exercise the production RR dispatch validator with all radiance layouts.

Compiles the actual validator, signal mapping and FFX ABI without a GPU. Checks
all descriptor permutations plus malformed, mismatched and cyclic chains.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp

PREAMBLE = r'''
#include <algorithm>
#include <array>
#include <iostream>
#include <vector>
struct ID3D12GraphicsCommandList {};
#define LOG_ERROR(...) ((void)0)
'''

HARNESS = r'''
int main()
{
    constexpr auto AO = FFX_API_DISPATCH_DESC_TYPE_DENOISER_AMBIENT_OCCLUSION;
    constexpr auto DEBUG = FFX_API_DISPATCH_DESC_TYPE_DENOISER_DEBUG_VIEW;
    ID3D12GraphicsCommandList cmd, otherCmd;
    unsigned checks = 0, failures = 0, validChains = 0;
    for (unsigned mask = 1; mask < 16; ++mask)
    for (bool ao : {false, true}) for (bool debug : {false, true})
    {
        std::vector<ffxStructType_t> types;
        for (int i = 0; i < 4; ++i)
            if (mask & FSRDSignals::Bit(i)) types.push_back(SignalDescriptors[i]);
        if (ao) types.push_back(AO);
        std::sort(types.begin(), types.end());
        auto checkChain = [&](const std::vector<ffxStructType_t>& chain, bool wanted,
                              const char* name, int invalid = 0) {
            std::vector<ffxDispatchDescHeader> headers(chain.size());
            for (size_t i = 0; i < chain.size(); ++i)
                headers[i] = {chain[i], i + 1 < chain.size() ? &headers[i + 1] : nullptr};
            if (invalid == 4 && !headers.empty()) headers.back().pNext = headers.data();
            ffxDispatchDescDenoiser desc {};
            desc.header = {FFX_API_DISPATCH_DESC_TYPE_DENOISER,
                           headers.empty() ? nullptr : headers.data()};
            desc.commandList = invalid == 2 ? &otherCmd : &cmd;
            if (invalid == 3) desc.header.type = AO;
            const bool actual = ValidateRRDispatchChain(invalid == 1 ? nullptr : &cmd, desc, mask, ao);
            ++checks;
            if (actual != wanted)
            {
                ++failures;
                std::cerr << "FAIL " << name << " mask=" << mask << '\n';
            }
        };
        do {
            auto chain = types;
            if (debug) chain.push_back(DEBUG);
            checkChain(chain, true, "valid layout permutation");
            ++validChains;
        } while (std::next_permutation(types.begin(), types.end()));

        if (debug) types.push_back(DEBUG);
        checkChain(types, false, "null command list", 1);
        checkChain(types, false, "mismatched command list", 2);
        checkChain(types, false, "wrong dispatch head", 3);
        checkChain(types, false, "cyclic chain", 4);
        for (size_t i = 0; i < types.size(); ++i)
        {
            auto changed = types;
            changed.insert(changed.begin() + i, types[i]);
            checkChain(changed, false, "duplicate descriptor");
            if (types[i] == DEBUG) continue;
            changed = types;
            changed.erase(changed.begin() + i);
            checkChain(changed, false, "missing required signal");
        }
        auto changed = types;
        changed.insert(changed.begin(), 0x5ffff);
        checkChain(changed, false, "unknown signal");
        changed = types;
        changed.insert(changed.begin(), DEBUG);
        checkChain(changed, false, "debug must be unique and at tail");
        for (int i = 0; i < 4; ++i)
        {
            if (mask & FSRDSignals::Bit(i)) continue;
            changed = types;
            changed.insert(changed.begin(), SignalDescriptors[i]);
            checkChain(changed, false, "signal absent from context");
        }
    }
    std::cout << "{\"checks\":" << checks << ",\"failures\":" << failures
              << ",\"valid_chains\":" << validChains << "}\n";
    return failures ? 1 : 0;
}
'''


def run():
    source = ROOT / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
    text = source.read_text(encoding='utf-8-sig')
    start = text.index('static bool ValidateRRDispatchChain(')
    # The validator is a free function. End at its closing brace so members defined
    # after it (the game trace dispatch snapshot) stay out of the harness.
    end = text.index('\n}\n', start) + 3
    function = text[start:end]
    start = text.index('static constexpr ffxStructType_t SignalDescriptors[]')
    mapping = text[start:text.index('};', start) + 2]
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', str(ROOT / 'tools_tmp/dispatch_chain'))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    header = ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h'
    policy = ROOT / 'OptiScaler/upscalers/fsr31/FSRDSignalPolicy.h'
    cpp = output / 'fsrd_dispatch_chain_test.cpp'
    cpp.write_text(f'#include "{header.as_posix()}"\n#include "{policy.as_posix()}"\n'
                   + PREAMBLE + mapping + '\n' + function + HARNESS, encoding='utf-8')
    executable = cpp.with_suffix('.exe')
    compile_cpp(cpp, executable)
    result = subprocess.run([str(executable)], text=True, capture_output=True)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    report = json.loads(result.stdout)
    report.update(source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  validator_sha256=hashlib.sha256(function.encode()).hexdigest())
    (output / 'dispatch_chain_result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    result.check_returncode()


if __name__ == '__main__':
    run()
