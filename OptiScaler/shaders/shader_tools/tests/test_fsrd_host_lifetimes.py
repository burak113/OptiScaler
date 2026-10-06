"""Execute production probe/debug lifetime and live-routing methods with D3D12.

Only the application's hook entry points and logging are substituted. The actual
recording/fence registries, resource allocation and command lists are exercised.
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
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


PREAMBLE = r'''
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <vector>
using Microsoft::WRL::ComPtr;
#define LOG_INFO(...) ((void)0)
#define LOG_ERROR(...) ((void)0)
constexpr auto kSrvState = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
constexpr auto kUavState = D3D12_RESOURCE_STATE_UNORDERED_ACCESS;
void need(bool ok, const char* text) { if (!ok) throw std::runtime_error(text); }
void hr(HRESULT result) { need(SUCCEEDED(result), "D3D12 call failed"); }
struct XMFLOAT4 { float x=0, y=0, z=0, w=0; };
struct ConversionDesc { XMFLOAT4 RenderSize, MotionTransform; bool DiagnosticsEnabled=true; };
namespace FSRDFormats { constexpr auto DebugView = DXGI_FORMAT_R16G16B16A16_FLOAT; }
ComPtr<ID3D12Resource> CreateTexture2D(ID3D12Device* device, UINT w, UINT h,
    DXGI_FORMAT format, LPCWSTR name, D3D12_RESOURCE_STATES state)
{
    D3D12_RESOURCE_DESC desc {};
    desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width=w; desc.Height=h; desc.DepthOrArraySize=desc.MipLevels=1;
    desc.SampleDesc.Count=1; desc.Format=format; desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
    ComPtr<ID3D12Resource> resource;
    hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&resource)));
    return resource;
}
void AddBarrier(ID3D12GraphicsCommandList* list, ID3D12Resource* resource,
    D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
{
    D3D12_RESOURCE_BARRIER barrier {};
    barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};
    list->ResourceBarrier(1,&barrier);
}
namespace ResTrack_Dx12 {
bool EnsureRRTraceHooks(ID3D12Device*) { return true; }
bool RetainComputeDispatch(ID3D12Device*, ID3D12GraphicsCommandList* list, const std::shared_ptr<void>& lease)
{
    ComPtr<IUnknown> identity; hr(list->QueryInterface(IID_PPV_ARGS(&identity)));
    return RecordedComputeLease::Track(identity.Get(),{list,identity.Get()},lease);
}
}
struct Harness
{
    ID3D12Device* m_pDev;
    ComPtr<ID3D12Resource> m_LinearDepth, m_debugViewOutput;
    UINT m_debugViewWidth=0, m_debugViewHeight=0;
    bool m_debugViewOutputInUavState=false;
    struct {
        struct {
            ComPtr<ID3D12Resource> Motion, Normals, SpecAlbedo, SkipSignal, DiffAlbedo;
            struct { ComPtr<ID3D12Resource> IndirectSpecular; } Signals;
        } Resources;
    } m_out;
    unsigned logs=0;
    bool LogInputProbe() { ++logs; return true; }
    explicit Harness(ID3D12Device* device) : m_pDev(device)
    {
        auto& r=m_out.Resources;
        for (auto* resource : {std::addressof(m_LinearDepth),std::addressof(r.Motion),std::addressof(r.Normals),
                              std::addressof(r.SpecAlbedo),std::addressof(r.SkipSignal),std::addressof(r.DiffAlbedo),
                              std::addressof(r.Signals.IndirectSpecular)})
            *resource=CreateTexture2D(device,4,4,FSRDFormats::DebugView,L"input",kSrvState);
    }
    ~Harness() { ReleaseInputProbe(); }
'''

MAIN = r'''
int main() try
{
    ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))); debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory; hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> warp; hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
    ComPtr<ID3D12Device> device; hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
    ComPtr<ID3D12InfoQueue> info; hr(device.As(&info));
    D3D12_COMMAND_QUEUE_DESC qdesc {};
    ComPtr<ID3D12CommandQueue> queue; hr(device->CreateCommandQueue(&qdesc,IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator; hr(device->CreateCommandAllocator(qdesc.Type,IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> list;
    hr(device->CreateCommandList(0,qdesc.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
    ComPtr<IUnknown> identity; hr(list.As(&identity));
    ComPtr<ID3D12Fence> fence; hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
    HANDLE event=CreateEvent(nullptr,FALSE,FALSE,nullptr); need(event!=nullptr,"event");
    UINT64 value=0;
    RecordedComputeLease::SetHooksAvailable(true,true);
    auto submitAndWait=[&] {
        ID3D12CommandList* lists[]={list.Get()};
        auto trace=RRTraceFence::BeforeSubmission(queue.Get(),1,lists);
        auto compute=RecordedComputeLease::BeforeSubmission(queue.Get(),{identity.Get()});
        queue->ExecuteCommandLists(1,lists);
        RRTraceFence::AfterSubmission(queue.Get(),trace);
        RecordedComputeLease::AfterSubmission(compute);
        hr(queue->Signal(fence.Get(),++value)); hr(fence->SetEventOnCompletion(value,event));
        need(WaitForSingleObject(event,30000)==WAIT_OBJECT_0,"GPU timeout");
        RecordedComputeLease::Poll();
    };
    auto reset=[&] {
        auto recording=RecordedComputeLease::Capture(list.Get());
        hr(allocator->Reset()); hr(list->Reset(allocator.Get(),nullptr));
        RRTraceFence::ResetSucceeded(list.Get()); RecordedComputeLease::Detach(recording);
    };
    ConversionDesc desc {{4,4,.25f,.25f},{1,1,0,0},true};
    {
        Harness h(device.Get()); h.UpdateInputProbe(list.Get(),desc);
        need(bool(h.m_inputProbeTicket),"probe was armed");
        for (unsigned i=0;i<64;++i) h.UpdateInputProbe(list.Get(),desc);
        need(h.logs==0,"CPU frames cannot authorize readback");
        hr(list->Close()); submitAndWait();
        h.UpdateInputProbe(list.Get(),desc);
        need(h.logs==0,"executable command list cannot authorize readback");
        reset(); h.UpdateInputProbe(list.Get(),desc);
        need(h.logs==1 && !h.m_inputProbeTicket,"fence plus Reset authorizes one readback");
        h.m_inputProbeCountdown=1; h.UpdateInputProbe(list.Get(),desc);
        hr(list->Close()); reset(); h.UpdateInputProbe(list.Get(),desc);
        need(h.logs==1 && !h.m_inputProbeTicket,"discard is not logged");
        for (auto& buffer:h.m_inputProbeReadback) need(!buffer,"discarded buffers not reused");
        h.m_inputProbeCountdown=1; h.UpdateInputProbe(list.Get(),desc);
        hr(list->Close()); submitAndWait(); reset();
        desc.DiagnosticsEnabled=false; h.UpdateInputProbe(list.Get(),desc);
        need(h.logs==1 && !h.m_inputProbeTicket,"disabled diagnostics retire pending work");
        desc.DiagnosticsEnabled=true;
    }
    std::shared_ptr<RRTraceFence::Ticket> orphan;
    {
        Harness h(device.Get()); h.UpdateInputProbe(list.Get(),desc); orphan=h.m_inputProbeTicket;
    }
    need(orphan && orphan->resources.size()==14,"owner destruction retains all copy resources");
    hr(list->Close()); submitAndWait(); reset(); RRTraceFence::Forget(orphan); orphan.reset();
    {
        Harness h(device.Get());
        for (unsigned size=4;size<10;++size)
        {
            auto* target=h.PrepareDebugViewOutput(list.Get(),size,size);
            AddBarrier(list.Get(),target,kUavState,kSrvState);
        }
    }
    // Six resized targets, no blit, and a destroyed converter. Each target is still
    // retained by its actual command-list recording rather than by a three-slot ring.
    hr(list->Close()); submitAndWait(); reset();
    RecordedComputeLease::Poll();
    need(RecordedComputeLease::GetRegistry().recordings.empty(),"debug recordings retired");
    {
        RecordedComputeLease::SetHooksAvailable(false,false);
        Harness h(device.Get()); bool rejected=false;
        try { h.PrepareDebugViewOutput(list.Get(),8,8); } catch (const std::exception&) { rejected=true; }
        need(rejected,"untracked debug target must not be dispatched");
        RecordedComputeLease::SetHooksAvailable(true,true);
    }
    RoutingHarness r;
    r.ApplyRoutingSettings(1,0,false); need(r.resets==0,"same routing preserves history");
    r.ApplyRoutingSettings(.5f,0,false); need(r.resets==1,"bias change resets RR");
    r.ApplyRoutingSettings(.5f,.25f,false); need(r.resets==2,"threshold change resets RR");
    r.ApplyRoutingSettings(.5f,.25f,true); need(r.resets==3,"polarity change resets RR");
    r.ApplyRoutingSettings(.5f,.25f,true); need(r.resets==3,"stable routing preserves history");
    r.ApplyRoutingSettings(std::numeric_limits<float>::quiet_NaN(),std::numeric_limits<float>::infinity(),false);
    need(r.resets==4 && r._convDesc.BiasMaskStrength==1 && r._convDesc.ResponsivityTrustThreshold==0,
         "nonfinite routing uses finite defaults");
    r.ApplyRoutingSettings(2,-1,false); need(r.resets==4,"equivalent clamped routing preserves history");
    hr(list->Close()); CloseHandle(event);
    for (UINT64 i=0;i<info->GetNumStoredMessages();++i)
    {
        SIZE_T size=0; hr(info->GetMessage(i,nullptr,&size)); std::vector<char> data(size);
        auto* message=reinterpret_cast<D3D12_MESSAGE*>(data.data()); hr(info->GetMessage(i,message,&size));
        if (message->Severity<=D3D12_MESSAGE_SEVERITY_WARNING)
            throw std::runtime_error(message->pDescription);
    }
    std::cout<<"PASS: production probe retirement, debug-target lifetime, live routing; clean D3D12 validation\n";
}
catch (const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT / 'tools_tmp/fsrd_host_lifetimes'))
    output.mkdir(parents=True, exist_ok=True)
    preprocessor = (ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp').read_text()
    feature = (ROOT / 'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp').read_text()
    fields = preprocessor[preprocessor.index('    static constexpr UINT kInputProbeTargetCount'):
                          preprocessor.index('    void UpdateInputProbe')]
    methods = '\n'.join(method(preprocessor, signature) for signature in
                        ('void UpdateInputProbe(', 'bool RecordInputProbe(', 'ID3D12Resource* PrepareDebugViewOutput('))
    routing = method(feature, 'void FSRDFeatureDx12::ApplyRoutingSettings(').replace('FSRDFeatureDx12::', '')
    includes = ''.join(f'#include "{(ROOT / path).as_posix()}"\n' for path in
                       ('OptiScaler/shaders/fsrd_preprocess/RRTraceFence.h',
                        'OptiScaler/misc/RecordedComputeLease_Dx12.h'))
    source = output / 'fsrd_host_lifetimes.cpp'
    source.write_text('#define NOMINMAX\n' + includes + PREAMBLE + fields + methods + '\n};\n'
                      'struct RoutingHarness { unsigned resets=0;\n'
                      'struct { float BiasMaskStrength=1, ResponsivityTrustThreshold=0; bool ResponsivityInvert=false; } _convDesc;\n'
                      'void InvalidateDenoiserHistory() { ++resets; }\n' + routing + '\n};\n' + MAIN)
    exe = output / 'fsrd_host_lifetimes.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib'))
    subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    run()
