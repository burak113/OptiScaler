"""Run the production SR reactive/transparency mask selection with controlled inputs.

GetReactiveAndTransparencyMasks is extracted unchanged. The Bias helper is a double that
keeps the production contract: CanRender() needs an allocated buffer, and a recorded-
lifetime helper refuses an allocation without the command list it is leased to.
"""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PREAMBLE = r'''
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>
#define LOG_DEBUG(...) ((void)0)
enum D3D12_RESOURCE_STATES { D3D12_RESOURCE_STATE_UNORDERED_ACCESS = 8, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE = 64 };
struct ID3D12Resource { int id = 0; };
struct ID3D12Device {};
struct ID3D12GraphicsCommandList {};
template <class T> struct Setting
{
    std::optional<T> value;
    T fallback {};
    bool has_value() const { return value.has_value(); }
    T value_or_default() const { return value.value_or(fallback); }
    T value_or(T other) const { return value.value_or(other); }
    void set_volatile_value(T v) { value = v; }
};
struct Config
{
    Setting<int> MaskResourceBarrier;
    Setting<bool> DisableReactiveMask, FsrUseMaskForTransparency { {}, true };
    Setting<float> DlssReactiveMaskBias { {}, 0.45f };
    static Config* Instance() { static Config value; return &value; }
};
static unsigned barriers = 0;
static void TryResourceBarrier(ID3D12GraphicsCommandList*, ID3D12Resource* resource, const Setting<int>& state,
                               D3D12_RESOURCE_STATES)
{
    if (resource && state.has_value()) ++barriers;
}
struct BiasDouble
{
    bool init = true, recorded = true, allocationFails = false, dispatchFails = false;
    ID3D12Resource buffer { 99 };
    ID3D12Resource* _buffer = nullptr;
    unsigned allocations = 0, dispatches = 0;
    bool IsInit() const { return init; }
    bool CanRender() const { return init && _buffer != nullptr; }
    bool CreateBufferResource(ID3D12Device*, ID3D12Resource* source, D3D12_RESOURCE_STATES,
                              ID3D12GraphicsCommandList* list = nullptr)
    {
        ++allocations;
        if (!source || allocationFails || (recorded && !list)) return false;
        _buffer = &buffer;
        return true;
    }
    void SetBufferState(ID3D12GraphicsCommandList*, D3D12_RESOURCE_STATES) {}
    bool Dispatch(ID3D12GraphicsCommandList*, ID3D12Resource*, float, ID3D12Resource* out)
    {
        ++dispatches;
        return !dispatchFails && out == _buffer;
    }
    ID3D12Resource* Buffer() const { return _buffer; }
};
struct FSR31FeatureDx12
{
    struct InputResources
    {
        ID3D12Resource* Color = nullptr; ID3D12Resource* MotionVectors = nullptr; ID3D12Resource* Depth = nullptr;
        ID3D12Resource* TransparencyMask = nullptr; ID3D12Resource* ReactiveMask = nullptr;
        ID3D12Resource* DlssBiasMaskFallback = nullptr; ID3D12Resource* ExposureMap = nullptr;
        bool DlssBiasMaskMisaligned = false;
    };
    ID3D12Device device;
    ID3D12Device* Device = &device;
    std::unique_ptr<BiasDouble> Bias = std::make_unique<BiasDouble>();
    void GetReactiveAndTransparencyMasks(ID3D12GraphicsCommandList* InCommandList, InputResources& inputs);
};
'''

MAIN = r'''
static unsigned checks = 0;
static void need(bool ok, const char* what) { ++checks; if (!ok) throw std::runtime_error(what); }

int main() try
{
    ID3D12GraphicsCommandList list;
    ID3D12Resource biasMask { 1 }, nativeReactive { 2 }, nativeTransparency { 3 };
    for (bool prewarmed : { false, true })
        for (bool recorded : { false, true })
        {
            *Config::Instance() = {};
            FSR31FeatureDx12 f;
            f.Bias->recorded = recorded;
            if (prewarmed) f.Bias->_buffer = &f.Bias->buffer;
            FSR31FeatureDx12::InputResources in;
            in.DlssBiasMaskFallback = &biasMask;
            f.GetReactiveAndTransparencyMasks(&list, in);
            need(f.Bias->allocations == 1 && f.Bias->dispatches == 1, "cold and prewarmed buffers both run the bias pass");
            need(in.ReactiveMask == &f.Bias->buffer, "processed bias mask becomes the reactive mask");
            need(in.TransparencyMask == &biasMask, "raw mask stays the transparency fallback");
        }
    {
        *Config::Instance() = {};
        Config::Instance()->DlssReactiveMaskBias.value = 0.0f;
        FSR31FeatureDx12 f;
        FSR31FeatureDx12::InputResources in;
        in.DlssBiasMaskFallback = &biasMask;
        f.GetReactiveAndTransparencyMasks(&list, in);
        need(f.Bias->allocations == 0 && in.ReactiveMask == nullptr, "bias 0 turns the reactive mask off");
        need(in.TransparencyMask == &biasMask, "bias 0 keeps the transparency fallback");
    }
    for (int failure = 0; failure != 2; ++failure)
    {
        *Config::Instance() = {};
        FSR31FeatureDx12 f;
        (failure == 0 ? f.Bias->allocationFails : f.Bias->dispatchFails) = true;
        FSR31FeatureDx12::InputResources in;
        in.DlssBiasMaskFallback = &biasMask;
        f.GetReactiveAndTransparencyMasks(&list, in);
        need(in.ReactiveMask == nullptr && in.TransparencyMask == &biasMask, "failed bias pass leaves SR without reactive");
    }
    {
        *Config::Instance() = {};
        FSR31FeatureDx12 f;
        FSR31FeatureDx12::InputResources in;
        in.DlssBiasMaskFallback = &biasMask;
        in.ReactiveMask = &nativeReactive;
        in.TransparencyMask = &nativeTransparency;
        f.GetReactiveAndTransparencyMasks(&list, in);
        need(in.ReactiveMask == &nativeReactive && in.TransparencyMask == &nativeTransparency && f.Bias->allocations == 0,
             "native FSR masks win");
    }
    {
        *Config::Instance() = {};
        Config::Instance()->MaskResourceBarrier.value = 4;
        barriers = 0;
        FSR31FeatureDx12 f;
        FSR31FeatureDx12::InputResources in;
        in.DlssBiasMaskFallback = &biasMask;
        in.DlssBiasMaskMisaligned = true;
        f.GetReactiveAndTransparencyMasks(&list, in);
        need(barriers == 1, "an offset bias mask is still transitioned for RR's conversion");
        need(in.ReactiveMask == nullptr && in.TransparencyMask == nullptr && f.Bias->allocations == 0,
             "an offset bias mask never reaches SR");
    }
    std::cout << "SR reactive masks: " << checks << " production mask selection checks passed\n";
    return 0;
}
catch (const std::exception& e)
{
    std::cerr << e.what() << '\n';
    return 1;
}
'''


def run():
    sr = (ROOT / "OptiScaler/upscalers/fsr31/FSR31Feature_Dx12.cpp").read_text(encoding="utf-8-sig")
    body = method(sr, "void FSR31FeatureDx12::GetReactiveAndTransparencyMasks(")
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", ROOT / "tools_tmp/fsr_reactive_masks/tests")) / "reactive_masks"
    out.mkdir(parents=True, exist_ok=True)
    source = out / "fsr_reactive_masks_test.cpp"
    source.write_text(PREAMBLE + body + MAIN, encoding="utf-8")
    exe = source.with_suffix(".exe")
    compile_cpp(source, exe)
    subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    run()
