"""Exercise the production GAME_TRACE recorder with real WARP copy/queue/Reset.

The host supplies controlled GPU words, never game pixels or an IQ reference.
Only DLL-path discovery/PCH are substituted so every capture stays in test
scratch. The actual recorder, hashes, queue fences and publication run unchanged.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]

CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
#include "__RECORDER__"
using Microsoft::WRL::ComPtr;
using Trace = FSRDGameTraceSession;
constexpr auto srv = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
void need(bool okay, const char* message) { if (!okay) throw std::runtime_error(message); }
void hr(HRESULT code) { need(SUCCEEDED(code), "D3D12 call failed"); }
struct Host
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    ComPtr<ID3D12InfoQueue> info;
    std::array<ComPtr<ID3D12Resource>,9> textures;
    std::vector<ComPtr<ID3D12Resource>> uploads;
    std::array<Trace::Source,Trace::SourceCount> sources;
    std::array<Trace::DiagnosticSource,13> diagnostics;
    std::array<uint8_t,416> constants {};
    std::array<uint8_t,176> seed {};
    uint64_t serial=0;
    Host()
    {
        ComPtr<ID3D12Debug> debug; hr(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
        debug->EnableDebugLayer();
        ComPtr<IDXGIFactory4> factory; hr(CreateDXGIFactory2(0,IID_PPV_ARGS(&factory)));
        ComPtr<IDXGIAdapter> warp; hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)));
        hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
        hr(device.As(&info));
        D3D12_COMMAND_QUEUE_DESC q {}; hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)));
        hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
        hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
        const std::array<DXGI_FORMAT,9> formats {DXGI_FORMAT_R16G16B16A16_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R10G10B10A2_UNORM,DXGI_FORMAT_R32_FLOAT,DXGI_FORMAT_R16G16B16A16_FLOAT,
            DXGI_FORMAT_R8_UNORM};
        D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        for (size_t i=0;i<textures.size();++i)
        {
            D3D12_RESOURCE_DESC d {}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            d.Width=d.Height=136; d.DepthOrArraySize=d.MipLevels=1; d.SampleDesc.Count=1; d.Format=formats[i];
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,srv,nullptr,IID_PPV_ARGS(&textures[i])));
        }
        for (size_t i=0;i<sources.size();++i) sources[i]={textures[i].Get(),srv};
        const std::array<const char*,13> names {"raw_color","raw_normals","raw_specular_albedo","raw_diffuse_albedo",
            "floor","floor_reference","raw_bias_mask","raw_specular_hit_distance","raw_motion","raw_depth",
            "raw_roughness","raw_title_linear_depth","raw_inspector"};
        const std::array<int,13> indices {0,1,2,3,0,1,8,6,7,6,-1,-1,-1};
        for (size_t i=0;i<diagnostics.size();++i)
        {
            auto& d=diagnostics[i]; d.name=names[i]; d.active=indices[i]>=0; d.required=d.active;
            d.inactiveReason="Fixture binding absent.";
            if (d.active) d.image={textures[indices[i]].Get(),srv};
        }
        auto word=[&](size_t offset,float value) { memcpy(constants.data()+offset,&value,4); };
        for (size_t i=0;i<4;++i) { word(i*20,1); word(64+i*20,1); word(128+i*20,1); }
        word(192,136); word(196,136); word(200,1.f/136); word(204,1.f/136);
        memcpy(seed.data(),constants.data()+64,64);
        memcpy(seed.data()+64,constants.data()+192,16);
    }
    void Fill(unsigned frame)
    {
        uploads.clear();
        for (size_t i=0;i<textures.size();++i)
        {
            const auto d=textures[i]->GetDesc();
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp {}; UINT64 bytes=0;
            device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&bytes);
            D3D12_HEAP_PROPERTIES heap {}; heap.Type=D3D12_HEAP_TYPE_UPLOAD;
            D3D12_RESOURCE_DESC bd {}; bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
            bd.Width=bytes; bd.Height=1; bd.DepthOrArraySize=bd.MipLevels=1; bd.SampleDesc.Count=1;
            bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            ComPtr<ID3D12Resource> upload;
            hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,
                nullptr,IID_PPV_ARGS(&upload)));
            void* data=nullptr; const D3D12_RANGE empty {0,0}; hr(upload->Map(0,&empty,&data));
            memset(data,0,size_t(bytes));
            if (i==0)
            {
                // HALF pattern varies by frame AND texel, proving exact nonzero
                // ROI addressing, row-pitch removal and genuine frame uniqueness.
                for (unsigned y=0;y<136;++y)
                    for (unsigned x=0;x<136;++x)
                        for (unsigned c=0;c<4;++c)
                        {
                            const uint16_t value=uint16_t(0x3000+frame+x+y+c);
                            memcpy(static_cast<uint8_t*>(data)+fp.Offset+y*fp.Footprint.RowPitch+(x*4+c)*2,&value,2);
                        }
            }
            upload->Unmap(0,nullptr);
            D3D12_RESOURCE_BARRIER b {}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            b.Transition={textures[i].Get(),0,srv,D3D12_RESOURCE_STATE_COPY_DEST}; list->ResourceBarrier(1,&b);
            D3D12_TEXTURE_COPY_LOCATION src {},dst {};
            src.pResource=upload.Get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=fp;
            dst.pResource=textures[i].Get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            std::swap(b.Transition.StateBefore,b.Transition.StateAfter); list->ResourceBarrier(1,&b);
            uploads.push_back(std::move(upload));
        }
    }
    Trace::FrameInfo Frame(unsigned index,bool reset=false,const char* context="fixture-generation-1",int setting=1)
    {
        Trace::FrameInfo frame {}; frame.contextId=context; frame.evaluationId=index+1;
        frame.frameIndex=1000+index; frame.reset=reset; frame.dispatchFlags=reset ? 1 : 0;
        Json view=Json::array({1,0,0,0,0,1,0,0,0,0,1,0,float(index)*.01f,0,0,1});
        Json projection=Json::array({1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1});
        frame.controlsJson=Json{{"view",view},{"projection",projection},
            {"jitter",{float(index%4)*.125f,-.125f}}, {"camera_delta",{float(index)*.01f,0,0}},
            {"motion_vector_scale",{1,1}}, {"depth_bounds",{.1f,1000.f}}, {"render_size",{136,136}},
            {"pre_exposure",1.f},{"pre_exposure_provided",true}}.dump();
        frame.settingsJson=Json{{"sdk_tuning",{1,1,1000,3,1,.1f}},{"fixture_setting",setting}}.dump();
        return frame;
    }
    bool Sources(Trace& capture,uint32_t width=136,bool hooks=true)
    { return capture.RecordSources(device.Get(),list.Get(),sources,width,136,constants,diagnostics,seed,{},hooks); }
    void Record(Trace& capture,unsigned index,bool reset=false,const char* context="fixture-generation-1",int setting=1)
    {
        Fill(index); need(Sources(capture),"source recording unexpectedly rejected");
        const std::array<Trace::DiagnosticSource,2> lobes {{
            {"rr_specular",{textures[0].Get(),srv}},{"rr_diffuse",{textures[1].Get(),srv}}
        }};
        capture.RecordNative(list.Get(),{textures[0].Get(),srv},Frame(index,reset,context,setting),lobes);
        capture.CompleteFrame(list.Get(),{textures[0].Get(),srv});
    }
    void Execute(bool repeat=false)
    {
        hr(list->Close()); ID3D12CommandList* lists[]={list.Get()};
        auto submit=[&] {
            auto tickets=RRTraceFence::BeforeSubmission(queue.Get(),1,lists);
            queue->ExecuteCommandLists(1,lists); RRTraceFence::AfterSubmission(queue.Get(),tickets);
        };
        auto waitGpu=[&] {
            hr(queue->Signal(fence.Get(),++serial));
            HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr); need(event!=nullptr,"test fence event");
            hr(fence->SetEventOnCompletion(serial,event));
            const auto waited=WaitForSingleObject(event,10000); CloseHandle(event);
            need(waited==WAIT_OBJECT_0,"test GPU completion timed out");
        };
        submit(); waitGpu();
        // Re-execution of an un-reset, closed list is legal after its prior
        // execution completed. It still makes a capture lineage ambiguous.
        if (repeat) { submit(); waitGpu(); }
    }
    void Reset()
    { hr(allocator->Reset()); hr(list->Reset(allocator.Get(),nullptr)); RRTraceFence::ResetSucceeded(list.Get()); }
    void Discard() { hr(list->Close()); Reset(); }
    void NoGpuErrors()
    {
        for (uint64_t i=0;i<info->GetNumStoredMessages();++i)
        {
            SIZE_T bytes=0; hr(info->GetMessage(i,nullptr,&bytes)); std::vector<uint8_t> storage(bytes);
            auto* message=reinterpret_cast<D3D12_MESSAGE*>(storage.data()); hr(info->GetMessage(i,message,&bytes));
            if (message->Severity==D3D12_MESSAGE_SEVERITY_ERROR || message->Severity==D3D12_MESSAGE_SEVERITY_CORRUPTION)
                throw std::runtime_error(message->pDescription);
        }
    }
};
int main(int argc,char** argv) try
{
    need(argc==2,"test output directory is required"); g_dllPath=std::filesystem::path(argv[1])/"test_OptiScaler.dll";
    Host host; Json results=Json::object();
    auto snapshot=[&](const char* name) { const auto status=Trace::GetStatus(); results[name]=status.folder; };
    {
        Trace capture; need(Trace::RequestStart(3,5),"full request"); snapshot("complete");
        for (unsigned frame=0;frame<128;++frame)
        {
            host.Record(capture,frame,frame==63);
            need(Trace::GetStatus().recorded==frame+1,"recorded ordinal count");
            host.Execute(); capture.Poll();
            need(Trace::GetStatus().captured==frame,"GPU completion without observed Reset must not publish");
            host.Reset(); capture.Poll();
            need(Trace::GetStatus().captured==frame+1,"completed+Reset frame not published");
        }
        need(Trace::GetStatus().phase=="complete" && !Trace::IsActive(),"128-frame completion");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5,2),"armed request"); snapshot("armed_owner_end");
        const auto started=GetTickCount64(); need(!host.Sources(capture),"armed delay recorded early");
        need(GetTickCount64()-started<1000 && Trace::GetStatus().pending==0,"arming blocked or allocated readbacks");
        need(Trace::GetStatus().delayRemainingMs>0,"armed countdown disappeared after ownership binding");
    }
    need(!Trace::IsActive() && Trace::GetStatus().phase=="incomplete","armed owner teardown did not close request");
    {
        Trace capture; need(Trace::RequestStart(3,5,2),"unclaimed arm request"); snapshot("unclaimed_owner_end");
    }
    need(!Trace::IsActive(),"unclaimed arm survived immediate owner teardown");
    { Trace nextOwner; need(!host.Sources(nextOwner),"next owner adopted a cancelled unclaimed arm"); }
    {
        Trace capture; need(Trace::RequestStart(3,5),"cancel request"); snapshot("cancelled");
        for (unsigned i=0;i<2;++i) { host.Record(capture,i); host.Execute(); host.Reset(); capture.Poll(); }
        Trace::RequestStop(); capture.Poll();
        need(!Trace::IsActive() && Trace::GetStatus().phase=="cancelled" && Trace::GetStatus().captured==2,"cancel lost prefix");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"failed-render request"); snapshot("failed_render");
        host.Record(capture,0); capture.Abort("Normal evaluation failed after composition.");
        host.Execute(); host.Reset(); capture.Poll();
        need(!Trace::IsActive() && Trace::GetStatus().captured==0,"failed rendering exported a false successful frame");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"invalid reset request"); snapshot("discarded");
        host.Record(capture,0); host.Discard(); capture.Poll();
        need(!Trace::IsActive() && Trace::GetStatus().captured==0,"unsubmitted Reset exported frame");
    }
    for (int change=0;change<3;++change)
    {
        Trace capture; need(Trace::RequestStart(3,5),"lineage-change request");
        snapshot(change==0 ? "context_changed" : change==1 ? "settings_changed" : "resize");
        host.Record(capture,0); host.Execute(); host.Reset(); capture.Poll();
        if (change==2) { need(!host.Sources(capture,138),"resize accepted"); }
        else host.Record(capture,1,false,change==0 ? "fixture-generation-2" : "fixture-generation-1",change==1 ? 2 : 1);
        need(!Trace::IsActive() && Trace::GetStatus().captured==1,"lineage change lost prefix or stayed active");
        host.Discard();
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"missing hooks request"); snapshot("missing_hooks");
        need(!host.Sources(capture,136,false) && !Trace::IsActive(),"missing hooks recorded unproved GPU work");
        need(Trace::GetStatus().message.find("hooks unavailable")!=std::string::npos,"missing hooks rejection unclear");
    }
    {
        Trace capture; need(Trace::RequestStart(3,5),"capacity request"); snapshot("capacity");
        std::vector<ComPtr<ID3D12CommandAllocator>> heldAllocators;
        std::vector<ComPtr<ID3D12GraphicsCommandList>> heldLists;
        for (unsigned i=0;i<3;++i)
        {
            host.Record(capture,i); hr(host.list->Close());
            heldAllocators.push_back(host.allocator); heldLists.push_back(host.list);
            host.allocator.Reset(); host.list.Reset();
            hr(host.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&host.allocator)));
            hr(host.device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,host.allocator.Get(),nullptr,IID_PPV_ARGS(&host.list)));
        }
        const auto started=GetTickCount64(); need(!host.Sources(capture),"unsubmitted capacity overflow accepted");
        need(GetTickCount64()-started<1000 && !Trace::IsActive() && Trace::GetStatus().captured==0,"capacity wait was unbounded or fabricated completion");
        for (size_t i=0;i<heldLists.size();++i)
        {
            hr(heldAllocators[i]->Reset()); hr(heldLists[i]->Reset(heldAllocators[i].Get(),nullptr));
            RRTraceFence::ResetSucceeded(heldLists[i].Get());
        }
    }
    {
        // Last: an ambiguous repeated submission is deliberately never recycled.
        Trace capture; need(Trace::RequestStart(3,5),"repeat submission request"); snapshot("repeated_submission");
        host.Record(capture,0); host.Execute(true); host.Reset(); capture.Poll();
        need(!Trace::IsActive() && Trace::GetStatus().captured==0,"repeated submission exported a frame");
    }
    host.NoGpuErrors();
    RRTraceAdditiveIO::WriteText(std::filesystem::path(argv[1])/"captures.json",results.dump(2));
    std::cout<<"GAME_TRACE production WARP capture lifecycle PASS\n";
    return 0;
}
catch (const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
'''


def run():
    output = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', ROOT / 'tools_tmp/fsrd_game_trace_capture')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stubs = output / 'stubs'
    stubs.mkdir(exist_ok=True)
    (stubs / 'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n')
    (stubs / 'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\n'
                                'namespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    recorder = ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp'
    source = output / 'fsrd_game_trace_capture.cpp'
    source.write_text(CPP.replace('__RECORDER__', recorder.as_posix()))
    exe = output / 'fsrd_game_trace_capture.exe'
    compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'bcrypt.lib'),
                (stubs, ROOT / 'external/nlohmann'))
    subprocess.run([str(exe), str(output)], check=True)
    captures = json.loads((output / 'captures.json').read_text())
    capture = Path(captures['complete'])
    manifest = json.loads((capture / 'capture.json').read_text())
    assert manifest['schema'] == 'fsrd-game-trace-v4'
    assert manifest['complete'] and manifest['committed_frames'] == 128
    assert manifest['neutral_full1_comparator'] is False
    assert manifest['output_scope'] == 'actual_configured_composition_before_sr'
    assert [f['ordinal'] for f in manifest['frames']] == list(range(128))
    assert [f['ordinal'] for f in manifest['frames'] if f['reset']] == [63]
    assert all(f['native_full1'] is False and f['command_list_detached'] for f in manifest['frames'])
    assert all(f['gpu_submission_verified'] and f['gpu_completed'] for f in manifest['frames'])
    for frame in manifest['frames']:
        for row in frame['images'] + frame['diagnostics'] + [frame['conversion_constants'], frame['floor_seed_constants']]:
            if 'file' not in row:
                continue
            blob = (capture / row['file']).read_bytes()
            assert len(blob) == row['bytes'] and hashlib.sha256(blob).hexdigest() == row['sha256']
    from fsrd_real_capture_replay import inspect_capture
    provenance, data = inspect_capture(capture, payload=True)
    assert provenance['payload_unique_raw_frames'] == 128
    assert provenance['original_reset_frames'] == [63]
    assert provenance['maximum_camera_delta'] > 0
    # Inspect authenticated, unchanged HALF words at the nonzero ROI origin.
    expected = 0x3000 + 127 + 3 + 5
    assert int(data['raw_color'][-1, 0, 0, 0].view('uint16')) == expected
    assert int(data['native_full1'][-1, 0, 0, 0].view('uint16')) == expected
    for name, folder in captures.items():
        if name == 'complete':
            continue
        partial = json.loads((Path(folder) / 'capture.json').read_text())
        assert partial['complete'] is False, name
        assert [f['ordinal'] for f in partial['frames']] == list(range(len(partial['frames']))), name
    assert json.loads((Path(captures['cancelled']) / 'capture.json').read_text())['committed_frames'] == 2
    assert json.loads((Path(captures['failed_render']) / 'capture.json').read_text())['committed_frames'] == 0
    report = {'schema': 'fsrd-game-trace-capture-host-test-v1', 'status': 'PASS',
              'frames': 128, 'mid_capture_reset': 63, 'reader_schema': manifest['schema'],
              'gpu_backend': 'WARP', 'debug_layer_errors': 0,
              'cases': sorted(captures), 'capture': str(capture),
              'limitation': 'Controlled GPU words; no game capture or image-quality claim.'}
    (output / 'game_trace_capture_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
