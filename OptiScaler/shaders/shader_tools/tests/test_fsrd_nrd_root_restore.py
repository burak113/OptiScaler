"""Execute production root-constant trackers: sparse updates and thread-local bridge suppression."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def run():
    source = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    state = source[source.index('enum class RootEntryType'):source.index('enum class SignatureEntryType')]
    names = ('hkSetComputeRoot32BitConstants', 'hkSetComputeRoot32BitConstant',
             'hkSetComputeRoot32BitConstantsLate', 'hkSetComputeRoot32BitConstantLate')
    bodies = '\n'.join(function(source, 'static void '+name+'(') for name in names)
    control = '\n'.join(function(source, signature).replace('D3D12Hooks::', '') for signature in (
        'void D3D12Hooks::SetRootSignatureTracking(', 'bool D3D12Hooks::RootSignatureTrackingEnabled('))
    cpp = r'''
#define NOMINMAX
#include <d3d12.h>
#include <algorithm>
#include <cstdint>
#include <vector>
#include <unordered_map>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <iostream>
#include <stdexcept>
__STATE__
bool gNrdBridgeDeviceWrappers = true, isUpscalerActive = false;
thread_local bool isNrdBridgeInjection = false;
thread_local bool lateInProgressSetComputeRoot32BitConstants = false, lateInProgressSetComputeRoot32BitConstant = false;
std::shared_mutex rootStatesMutex;
std::unordered_map<ID3D12GraphicsCommandList*, std::vector<RootState>> rootStates;
void many(ID3D12GraphicsCommandList*,UINT,UINT,const void*,UINT) {}
void one(ID3D12GraphicsCommandList*,UINT,UINT,UINT) {}
struct { decltype(&many) o_earlyHook = many, o_lateHook = many; } s_SetComputeRoot32BitConstants;
struct { decltype(&one) o_earlyHook = one, o_lateHook = one; } s_SetComputeRoot32BitConstant;
__BODIES__
__CONTROL__
unsigned checks = 0;
void need(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); ++checks; }
int main() {
 auto* list = reinterpret_cast<ID3D12GraphicsCommandList*>(1);
 rootStates[list].resize(1);
 const uint32_t a[] = {11,22,33,44};
 hkSetComputeRoot32BitConstants(list,0,4,a,0);
 hkSetComputeRoot32BitConstant(list,0,99,1);
 const uint32_t b[] = {77,88}; hkSetComputeRoot32BitConstantsLate(list,0,2,b,5);
 hkSetComputeRoot32BitConstantLate(list,0,66,3);
 const auto& current = rootStates[list][0];
 need(current.type == RootEntryType::Constants, "bridge merged constant kind");
 need(current.Data == std::vector<uint32_t>({11,99,33,66,0,77,88}), "all sparse updates survive");
 need(current.ValidConstants == std::vector<uint8_t>({1,1,1,1,0,1,1}), "unset gap remains unset");
 need(current.Num32BitValues == 7 && current.DestOffset == 0, "canonical merged offsets");
 auto saved = current.Data;
 hkSetComputeRoot32BitConstants(list,0,4,a,UINT_MAX);
 hkSetComputeRoot32BitConstants(list,0,4,a,63);
 hkSetComputeRoot32BitConstant(list,0,12,64);
 hkSetComputeRoot32BitConstants(list,0,0,a,0);
 need(current.Data == saved, "invalid writes cannot corrupt snapshot");
 SetRootSignatureTracking(false);
 hkSetComputeRoot32BitConstant(list,0,1,0);
 need(current.Data == saved, "internal work leaves title arguments intact");
 bool otherTracking = false;
 auto* other = reinterpret_cast<ID3D12GraphicsCommandList*>(2);
 rootStates[other].resize(1);
 std::thread thread([&] { otherTracking = RootSignatureTrackingEnabled(); hkSetComputeRoot32BitConstant(other,0,123,2); });
 thread.join();
 need(otherTracking, "another recording thread keeps tracking");
 need(rootStates[other][0].Data == std::vector<uint32_t>({0,0,123}), "other thread records title state");
 SetRootSignatureTracking(true);
 need(RootSignatureTrackingEnabled(), "tracking restored after bridge");
 gNrdBridgeDeviceWrappers = false;
 hkSetComputeRoot32BitConstants(list,0,4,a,2);
 need(current.Data == std::vector<uint32_t>({11,22,33,44}) && current.DestOffset == 2, "disabled path retains existing plural tracker behavior");
 hkSetComputeRoot32BitConstant(list,0,321,4);
 need(current.type == RootEntryType::Constant && current.Data == std::vector<uint32_t>({321}) && current.DestOffset == 4, "disabled path retains existing single tracker behavior");
 SetRootSignatureTracking(false);
 need(isUpscalerActive && !RootSignatureTrackingEnabled(), "disabled path keeps existing tracking control");
 SetRootSignatureTracking(true);
 need(!isUpscalerActive, "legacy tracking restored");
 std::cout << "PASS: " << checks << " production root restore checks\n";
}
'''
    cpp = cpp.replace('__STATE__', state).replace('__BODIES__', bodies).replace('__CONTROL__', control)
    out = Path(os.environ['FSRD_GPU_TEST_OUTPUT'])
    out.mkdir(parents=True, exist_ok=True)
    file, exe = out/'root_restore.cpp', out/'root_restore.exe'
    file.write_text(cpp)
    compile_cpp(file, exe)
    result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
    print(result.stdout, end='')
    (out/'result.json').write_text(json.dumps({'native_checks':int(result.stdout.split()[1]),'production_trackers_executed':list(names),
        'scope':'CPU root snapshot behavior; GPU restore checks are in the end-to-end fixture'})+'\n')


if __name__ == '__main__':
    run()
