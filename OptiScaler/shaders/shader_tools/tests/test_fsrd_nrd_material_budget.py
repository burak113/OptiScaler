"""Actual MaterialCapture class and native resources across retained contexts.

Application hook/lease adapters reuse the unchanged conversion fixture. Only
private owned-allocation forwards and dispatch are counted; one passive Slot
destruction observer and one pre-lock race trigger are explicit test adapters.
No detour installation, NativeBirth, signed RR or title capture claim is made.
--prepare-only does not build a shader, invoke a compiler, or create a device.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    actual = ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdNativeMaterialCapture_Dx12.h"
    production = actual.read_text()

    def replace(old, new):
        nonlocal production
        assert production.count(old) == 1, old
        production = production.replace(old, new)

    for include in ['#include "resource_tracking/ResTrack_Dx12.h"', '#include "State.h"']:
        replace(include, "")
    replace("class NativeMaterialCapture\n{", "class NativeMaterialCapture\n{\n  public: // Test visibility only; actual function bodies remain intact.")
    replace("    struct Slot\n    {", "    struct Slot\n    {\n        BudgetSlotFinalProbe finalProbe;")
    replace("context.device->CreateCommittedResource(", "BudgetCreateSnapshot(context.device.Get(),")
    replace("context.device->CreateDescriptorHeap(", "BudgetCreateHeap(context.device.Get(),")
    replace("            std::lock_guard lock(owner->mutex);", "            BudgetBeforeContextLock();\n            std::lock_guard lock(owner->mutex);")
    replace("            list->Dispatch(", "            BudgetDispatch(list,")
    (out / "production_material_budget.h").write_text(production, encoding="utf-8")
    prefix = (HERE / "fsrd_nrd_conversion_fixture.cpp").read_text().split("static ULONG References(")[0]
    assert prefix.count('#include "production_nrd_pass.cpp"') == 1
    audit = r'''
#include <atomic>
#include <cstdlib>
#include <functional>
#include <new>
#include <thread>
static unsigned snapshotCreates=0,heapCreates=0,captureDispatches=0,slotFinals=0,underLocks=0;
static bool failSnapshot=false,throwSnapshot=false,failHeap=false;
static thread_local bool allocationMeter=false;
static unsigned warmAllocations=0;
void* operator new(size_t n){if(allocationMeter)++warmAllocations;if(auto*p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](size_t n){return ::operator new(n);}
void operator delete(void*p)noexcept{std::free(p);}void operator delete[](void*p)noexcept{std::free(p);}
void operator delete(void*p,size_t)noexcept{std::free(p);}void operator delete[](void*p,size_t)noexcept{std::free(p);}
static std::function<void()> beforeContextLock;
static void BudgetBeforeContextLock(){if(beforeContextLock){auto action=std::move(beforeContextLock);beforeContextLock={};action();}}
static void BudgetAfterSlotFinal() noexcept;
struct BudgetSlotFinalProbe {~BudgetSlotFinalProbe(){BudgetAfterSlotFinal();}};
static HRESULT BudgetCreateSnapshot(ID3D12Device* device,const D3D12_HEAP_PROPERTIES* heap,D3D12_HEAP_FLAGS flags,
 const D3D12_RESOURCE_DESC* desc,D3D12_RESOURCE_STATES state,const D3D12_CLEAR_VALUE* clear,REFIID iid,void** out){
 ++snapshotCreates;if(throwSnapshot){throwSnapshot=false;throw std::bad_alloc();}if(failSnapshot){failSnapshot=false;return E_OUTOFMEMORY;}
 return device->CreateCommittedResource(heap,flags,desc,state,clear,iid,out);
}
static HRESULT BudgetCreateHeap(ID3D12Device* device,const D3D12_DESCRIPTOR_HEAP_DESC* desc,REFIID iid,void** out){
 ++heapCreates;if(failHeap){failHeap=false;return E_OUTOFMEMORY;}return device->CreateDescriptorHeap(desc,iid,out);
}
static void BudgetDispatch(ID3D12GraphicsCommandList* list,UINT x,UINT y,UINT z){++captureDispatches;list->Dispatch(x,y,z);}
#include "production_material_budget.h"
static NrdBridge::NativeMaterialCapture* watchedCapture=nullptr;
static std::array<std::weak_ptr<NrdBridge::NativeMaterialCapture::Context>,16> watchedContexts;
static unsigned watchedCount=0;
static void WatchContext(NrdBridge::NativeMaterialCapture& capture){
 watchedCapture=&capture;for(unsigned i=0;i<watchedCount;++i)if(watchedContexts[i].lock()==capture.context_)return;
 if(watchedCount>=watchedContexts.size())throw std::runtime_error("bounded fixture context inventory full");watchedContexts[watchedCount++]=capture.context_;
}
static void BudgetAfterSlotFinal() noexcept{
 ++slotFinals;if(!watchedCapture)return;
 try{unsigned blocked=0;std::thread worker([&]{
  if(watchedCapture->mutex_.try_lock())watchedCapture->mutex_.unlock();else ++blocked;
  for(unsigned i=0;i<watchedCount;++i)if(auto context=watchedContexts[i].lock()){
   if(context->mutex.try_lock())context->mutex.unlock();else ++blocked;}
 });worker.join();underLocks+=blocked;}catch(...){++underLocks;}
}
'''
    support = (HERE / "dx12_shader_test_support.h").as_posix()
    prefix = prefix.replace('#include "production_nrd_pass.cpp"', f'#include "{support}"\n' + audit)
    original = "ScopedInternal::ScopedInternal() noexcept : previous_(false) {}\nScopedInternal::~ScopedInternal() {}"
    assert original in prefix
    prefix = prefix.replace(original, "static thread_local bool budgetInternal=false;\n"
        "ScopedInternal::ScopedInternal() noexcept : previous_(budgetInternal) {budgetInternal=true;}\n"
        "ScopedInternal::~ScopedInternal() {budgetInternal=previous_;}")
    source = out / "material_budget.cpp"
    source.write_text(prefix + (HERE / "fsrd_nrd_material_budget_fixture.cpp").read_text(), encoding="utf-8")
    paths = [actual, ROOT / "OptiScaler/misc/NrdBridgeCaptureSlotBudget_Dx12.h", source]
    contract = dict(scope=__doc__, source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
                    cap=32, production_shader_rebuilt=False,
                    scenarios=["pending32_resize_block33", "pending32_device_replacement_block33", "idle32_resize_prune31", "late_old_capture", "failed_buffer",
                               "throwing_buffer", "failed_descriptors", "failed_retention", "warm_acquire", "family_bytes"])
    (out / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    return source


def main():
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/material-budget-prepare"))
    source = prepare(out)
    if "--prepare-only" in sys.argv:
        print(json.dumps(dict(source=str(source), scenarios=10, compiled=False, executed=False)))
        return
    sys.path[:0] = [str(HERE.parent), str(HERE)]
    from fsrd_toolchain import compile_cpp
    from test_fsrd_nrd_bridge_rr import bounded_run
    exe = out / "material_budget.exe"
    compile_cpp(source, exe, ("d3d12.lib", "dxgi.lib"),
                (out, HERE, ROOT / "OptiScaler/shaders/fsrd_preprocess", ROOT / "OptiScaler", ROOT / "OptiScaler/include", ROOT / "external/streamline", ROOT / "external/nlohmann"))
    text, peak, elapsed, log = bounded_run([str(exe), str(out)], out / "native_run")
    value = json.loads((out / "material-budget-result.json").read_text(encoding="utf-8"))
    assert value["under_helper_locks"] == 0 and value["warm_acquire_cpp_allocations"] == 0
    assert value["debug_errors"] == value["debug_warnings"] == 0
    value.update(peak_resident_bytes=peak, elapsed_seconds=elapsed, native_log=str(log))
    (out / "material-budget-result.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
