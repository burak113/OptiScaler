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
    # A forward declaration is not the next function's body.
    while source.find(';', start, brace) != -1:
        start = source.index(signature, source.index(';', start) + 1)
        brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def run():
    source = (ROOT/'OptiScaler/hooks/D3D12_Hooks.cpp').read_text()
    state = source[source.index('// Common'):source.index('// Intel Atomic Extension')]
    state = state.replace('ankerl::unordered_dense::map', 'std::unordered_map')
    names = ('hkSetComputeRoot32BitConstants', 'hkSetComputeRoot32BitConstant',
             'hkSetComputeRoot32BitConstantsLate', 'hkSetComputeRoot32BitConstantLate',
             'hkSetComputeRootSignature', 'hkSetComputeRootSignatureLate')
    bodies = '\n'.join(function(source, 'static void '+name+'(') for name in names)
    control = '\n'.join(function(source, signature).replace('D3D12Hooks::', '') for signature in (
        'void D3D12Hooks::SetRootSignatureTracking(', 'bool D3D12Hooks::RootSignatureTrackingEnabled(',
        'bool D3D12Hooks::GetComputeBindingsForBridge('))
    cpp = r'''
#define NOMINMAX
#include <d3d12.h>
#include "__ROOT__/OptiScaler/misc/NrdBridgePerf_Dx12.h"
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
namespace FrameSurvey {
thread_local bool internalScope=false; bool Internal() { return internalScope; }
struct ComputeRootView { UINT parameter=UINT_MAX; D3D12_DESCRIPTOR_RANGE_TYPE kind=D3D12_DESCRIPTOR_RANGE_TYPE_CBV; D3D12_GPU_VIRTUAL_ADDRESS address=0; };
struct ComputeBindings {
 ID3D12RootSignature* root = nullptr;
 std::vector<ID3D12DescriptorHeap*> heaps;
 std::vector<std::pair<UINT,D3D12_GPU_DESCRIPTOR_HANDLE>> tables;
 std::vector<ComputeRootView> views;
};
}
struct DescriptorHeap { UINT NumDescriptorHeaps=0; ID3D12DescriptorHeap* Heaps[2]={nullptr,nullptr}; };
std::shared_mutex descriptorHeapsMutex;
std::unordered_map<ID3D12GraphicsCommandList*,DescriptorHeap> descriptorHeaps;
std::unordered_map<ID3D12GraphicsCommandList*,ID3D12RootSignature*> bridgeComputeRoots;
enum class SignatureEntryType { Compute, Graphics };
struct SignatureEntry { SignatureEntryType type; ID3D12RootSignature* ptr; };
std::shared_mutex rootSignatureMutex;
std::unordered_map<ID3D12GraphicsCommandList*,SignatureEntry> signatures;
struct Option { bool current=true; bool value_or_default() const { return current; } };
struct Config { Option RestoreComputeSignature; static Config* Instance() { static Config value; return &value; } };
UINT GetRootParameterCount(ID3D12RootSignature*) { return 6; }
bool gNrdBridgeDeviceWrappers = true, isUpscalerActive = false;
thread_local bool isNrdBridgeInjection = false;
thread_local bool lateInProgressSetComputeRoot32BitConstants = false, lateInProgressSetComputeRoot32BitConstant = false;
thread_local bool lateInProgressSetComputeRootSignature = false;
std::shared_mutex rootStatesMutex;
std::unordered_map<ID3D12GraphicsCommandList*, std::vector<RootState>> rootStates;
void many(ID3D12GraphicsCommandList*,UINT,UINT,const void*,UINT) {}
void one(ID3D12GraphicsCommandList*,UINT,UINT,UINT) {}
struct { decltype(&many) o_earlyHook = many, o_lateHook = many; } s_SetComputeRoot32BitConstants;
struct { decltype(&one) o_earlyHook = one, o_lateHook = one; } s_SetComputeRoot32BitConstant;
void bindRoot(ID3D12GraphicsCommandList*,ID3D12RootSignature*) {}
struct { decltype(&bindRoot) o_earlyHook = bindRoot, o_lateHook = bindRoot; } s_SetComputeRootSignature;
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
 FrameSurvey::ComputeBindings bindings;
 need(!GetComputeBindingsForBridge(list,bindings) && !bindings.root && bindings.heaps.empty(), "missing tracker state fails without partial snapshot");
 auto* root = reinterpret_cast<ID3D12RootSignature*>(3);
 auto* heap = reinterpret_cast<ID3D12DescriptorHeap*>(4);
 auto* bindingList = reinterpret_cast<ID3D12GraphicsCommandList*>(5);
 bridgeComputeRoots[bindingList]=root; descriptorHeaps[bindingList]={1,{heap,nullptr}};
 rootStates[bindingList].resize(6);
 rootStates[bindingList][1].type=RootEntryType::Table; rootStates[bindingList][1].rootDescriptorTable.ptr=101;
 rootStates[bindingList][5].type=RootEntryType::Table; rootStates[bindingList][5].rootDescriptorTable.ptr=505;
 need(GetComputeBindingsForBridge(bindingList,bindings), "existing restore cache seeds a newly opened NRD window");
 need(bindings.root==root && bindings.heaps==std::vector<ID3D12DescriptorHeap*>({heap}), "root and heap identity copied exactly");
 need(bindings.tables.size()==2 && bindings.tables[0].first==1 && bindings.tables[0].second.ptr==101 &&
      bindings.tables[1].first==5 && bindings.tables[1].second.ptr==505, "p1 and p5 current GPU handles preserved in index order");
 descriptorHeaps[bindingList].NumDescriptorHeaps=3;
 need(!GetComputeBindingsForBridge(bindingList,bindings) && !bindings.root && bindings.tables.empty(), "invalid heap count fails closed");
 descriptorHeaps[bindingList]={1,{nullptr,nullptr}};
 need(!GetComputeBindingsForBridge(bindingList,bindings) && bindings.heaps.empty(), "null heap cannot publish a partial snapshot");
 descriptorHeaps[bindingList]={1,{heap,nullptr}};
 auto* earlyRoot = reinterpret_cast<ID3D12RootSignature*>(6);
 auto* lateRoot = reinterpret_cast<ID3D12RootSignature*>(7);
 Config::Instance()->RestoreComputeSignature.current=false;
 hkSetComputeRootSignature(bindingList,earlyRoot);
 need(bridgeComputeRoots[bindingList]==earlyRoot && signatures[bindingList].ptr==earlyRoot,
      "early bridge root tracking remains current through a false restore flag");
 need(rootStates[bindingList][1].type==RootEntryType::Invalid && rootStates[bindingList][5].type==RootEntryType::Invalid,
      "early root change during disabled restoration clears stale tables");
 need(GetComputeBindingsForBridge(bindingList,bindings) && bindings.root==earlyRoot && bindings.tables.empty(),
      "binding seed cannot retain the previous root or arguments after an early root change");
 hkSetComputeRootSignatureLate(bindingList,lateRoot);
 need(bridgeComputeRoots[bindingList]==lateRoot && signatures[bindingList].ptr==lateRoot,
      "late bridge root tracking remains current through a false restore flag");
 need(GetComputeBindingsForBridge(bindingList,bindings) && bindings.root==lateRoot && bindings.tables.empty(),
      "late binding seed contains exactly the newly bound root");
 Config::Instance()->RestoreComputeSignature.current=true;
 need(GetComputeBindingsForBridge(bindingList,bindings) && bindings.root==lateRoot,
      "re-enabling restoration cannot make the prior root current again");
 gNrdBridgeDeviceWrappers = false;
 Config::Instance()->RestoreComputeSignature.current=false;
 hkSetComputeRootSignature(bindingList,earlyRoot);
 hkSetComputeRootSignatureLate(bindingList,earlyRoot);
 need(signatures[bindingList].ptr==lateRoot && bridgeComputeRoots[bindingList]==lateRoot,
      "startup OFF preserves disabled early and late legacy root tracking");
 Config::Instance()->RestoreComputeSignature.current=true;
 need(!GetComputeBindingsForBridge(list,bindings) && !bindings.root, "disabled getter does no snapshot work");
 need(!GetComputeBindingsForBridge(nullptr,bindings), "null list fails closed");
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
    # Reuse the modern metadata-only declaration adapter, keeping every original
    # assertion below unchanged. NativeBirth is intentionally unconfigured here;
    # the activated exact-generation suite is test_fsrd_nrd_root_birth.py.
    import test_fsrd_nrd_restore_locks as declarations
    prefix = declarations.CPP.split('__STATE__', 1)[0] + '__STATE__\n'
    prefix += ('struct Option { bool current=true; bool value_or_default() const { return current; } };\n'
               'struct Config { Option RestoreComputeSignature; static Config* Instance() { static Config value; return &value; } };\n'
               'UINT GetRootParameterCount(ID3D12RootSignature*, const NrdBridgeBirth::Token&) { return 6; }\n')
    cpp = prefix + cpp[cpp.index('void many('):]
    for declaration in (
        'struct { decltype(&many) o_earlyHook = many, o_lateHook = many; } s_SetComputeRoot32BitConstants;',
        'struct { decltype(&one) o_earlyHook = one, o_lateHook = one; } s_SetComputeRoot32BitConstant;',
        'struct { decltype(&bindRoot) o_earlyHook = bindRoot, o_lateHook = bindRoot; } s_SetComputeRootSignature;'):
        assert cpp.count(declaration) == 1
        cpp = cpp.replace(declaration, '')
    cpp = cpp.replace('int main() {', 'int main() {\n s_SetComputeRoot32BitConstants={many,many}; s_SetComputeRoot32BitConstant={one,one}; s_SetComputeRootSignature={bindRoot,bindRoot};')
    cpp = cpp.replace('__ROOT__', ROOT.as_posix()).replace('__STATE__', state).replace('__BODIES__', bodies).replace('__CONTROL__', control)
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
