"""Optional real signed-AMD RRWrapper CPU/GPU cost experiment, source-only by default.

Includes the current production RRWrapper unchanged through the existing signed
provider fixture. Its Host/ResTrack/ScopedInternal adapters are explicit: this is
standalone provider plus live b6 capture/Commit cost, not title hooks, conversion,
upscaling, FrameSurvey, game FPS or a quality comparison. --run requires the lead
resource wrapper and shared gpu_lock grant; default preparation invokes no tools.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys

HERE = Path(__file__).resolve().parent
OWN = HERE.parents[3]
DLL = Path("F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll")
DLL_SHA256 = "48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3"

CPP = r'''
// All existing wrapper regression bodies/assertions remain present, unchanged.
#define main ExistingNrdRRRegressionMain
#include "__FIXTURE__"
#undef main
#include <chrono>
#include <iomanip>
#include <sstream>

namespace StandaloneCost
{
using Clock=std::chrono::steady_clock;
double ms(Clock::time_point a,Clock::time_point b)
{return std::chrono::duration<double,std::milli>(b-a).count();}
PfnFfxDispatch actualDispatch=nullptr;
ID3D12QueryHeap* query=nullptr;
std::ostream* evidence=nullptr; // Dedicated stream: provider diagnostics never share its file handle.
unsigned exportCalls=0;
double currentExportCpuMs=0;
ffxReturnCode_t timedExport(ffxContext* context,const ffxDispatchDescHeader* header)
{
    need(header&&header->type==FFX_API_DISPATCH_DESC_TYPE_DENOISER,"benchmark intercepts actual denoiser export only");
    const auto* dispatch=reinterpret_cast<const ffxDispatchDescDenoiser*>(header);
    auto* list=static_cast<ID3D12GraphicsCommandList*>(dispatch->commandList);
    need(list&&query&&actualDispatch,"native timing scope fully configured");
    list->EndQuery(query,D3D12_QUERY_TYPE_TIMESTAMP,1);
    const auto before=Clock::now();
    const auto result=actualDispatch(context,header);
    const auto after=Clock::now();
    currentExportCpuMs=ms(before,after);++exportCalls;
    list->EndQuery(query,D3D12_QUERY_TYPE_TIMESTAMP,2);
    return result;
}
struct Row{unsigned frame;double prepareCpu,wrapperCpu,exportCpu,submitWaitCpu,gpuBefore,gpuProvider,gpuCommit,gpuTotal;};
void sample(const Row& r,uint32_t width,uint32_t height,bool warm)
{
    *evidence<<"SAMPLE {\"width\":"<<width<<",\"height\":"<<height<<",\"frame\":"<<r.frame<<",\"warmup\":"<<(warm?"true":"false")
        <<",\"cpu_prepare_ms\":"<<r.prepareCpu<<",\"cpu_wrapper_record_ms\":"<<r.wrapperCpu
        <<",\"cpu_signed_export_ms\":"<<r.exportCpu<<",\"cpu_submit_wait_ms\":"<<r.submitWaitCpu
        <<",\"gpu_before_export_ms\":"<<r.gpuBefore<<",\"gpu_provider_ms\":"<<r.gpuProvider
        <<",\"gpu_flag_capture_commit_ms\":"<<r.gpuCommit<<",\"gpu_wrapper_ms\":"<<r.gpuTotal<<"}\n";
}
void run(Host& host,uint32_t width,uint32_t height,unsigned warm,unsigned count)
{
    const unsigned creates=FfxApiProxy::creates,destroys=FfxApiProxy::destroys,dispatches=FfxApiProxy::dispatches,actual=exportCalls;
    Scene scene(host,width,height);host.submit();host.reset();
    ConsumerBuffer native(host);native.flag(0); // Actual b6 capture, RGB Consumer branch.
    NativeTableConsumer consumer(host,scene.spec(),scene.diff(),width,height);
    consumer.Overwrite(host.device.Get(),native.constants().address);
    ComPtr<ID3D12QueryHeap> queries;D3D12_QUERY_HEAP_DESC desc{D3D12_QUERY_HEAP_TYPE_TIMESTAMP,4,0};
    hr(host.device->CreateQueryHeap(&desc,IID_PPV_ARGS(&queries)));query=queries.Get();
    auto readback=buffer(host.device.Get(),32,D3D12_HEAP_TYPE_READBACK);UINT64 frequency=0;
    hr(host.queue->GetTimestampFrequency(&frequency));need(frequency>0,"real hardware timestamp frequency");
    uint64_t staging=0,auxiliary=0;
    {
        RRWrapper wrapper;std::string error;RRSettings settings;
        const bool configured=wrapper.Configure(settings,error);need(configured,error.c_str());
        for(unsigned index=0;index!=warm+count;++index)
        {
            auto sl=camera(index,float(width)/height,.02f);
            sl.constants.jitterOffset={0,0};sl.constants.mvecScale={1,1};
            FrameParameters frame;const auto prepareBegin=Clock::now();
            const bool prepared=wrapper.PrepareFrame(sl,false,frame,error);need(prepared,error.c_str());
            const auto prepareEnd=Clock::now();
            need(frame.reset==(index==0)&&frame.frameIndex==index,"history resets first frame only");
            frame.outputConstants={native.binding.Get(),native.constants().address,consumer.heap.Get(),consumer.Handle()};
            host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
            const auto recordBegin=Clock::now();
            const bool dispatched=wrapper.Dispatch(host.list.Get(),scene.resources,scene.spec(),scene.diff(),frame,error);
            need(dispatched,error.c_str());
            const auto recordEnd=Clock::now();
            host.list->EndQuery(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,3);
            host.list->ResolveQueryData(queries.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,4,readback.Get(),0);
            need(exportCalls==actual+index+1&&FfxApiProxy::dispatches==dispatches+index+1,"each frame reaches signed provider export exactly once");
            need(FfxApiProxy::creates==creates+1&&wrapper.ContextGeneration()==1,"one physical context per resolution, no per-frame creation");
            need(FfxApiProxy::lastCreate.signalFlags==(FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE|FFX_DENOISER_SIGNAL_INDIRECT_SPECULAR),"production DD+IS context unchanged");
            need(((FfxApiProxy::lastDispatch.flags&FFX_DENOISER_DISPATCH_RESET)!=0)==(index==0),"SDK first-only reset");
            need(FfxApiProxy::nativeDebugDispatches==0&&!FfxApiProxy::lastSpecular.header.pNext,"no provider debug branch in timing");
            if(index==0){staging=wrapper.OwnedStagingBytes();auxiliary=wrapper.OwnedAuxiliaryBytes();}
            need(wrapper.OwnedStagingBytes()==staging&&wrapper.OwnedAuxiliaryBytes()==auxiliary,"warm owned staging/flag buffers do not grow");
            const auto submitBegin=Clock::now();host.submit();const auto submitEnd=Clock::now();
            UINT64* ticks=nullptr;hr(readback->Map(0,nullptr,reinterpret_cast<void**>(&ticks)));
            std::array<UINT64,4> t{};std::copy_n(ticks,4,t.begin());readback->Unmap(0,nullptr);
            need(t[0]<=t[1]&&t[1]<=t[2]&&t[2]<=t[3],"four real GPU timestamps ordered");
            const double scale=1000./double(frequency);
            sample({index,ms(prepareBegin,prepareEnd),ms(recordBegin,recordEnd),currentExportCpuMs,ms(submitBegin,submitEnd),
                (t[1]-t[0])*scale,(t[2]-t[1])*scale,(t[3]-t[2])*scale,(t[3]-t[0])*scale},width,height,index<warm);
            host.reset();
        }
    }
    query=nullptr;RecordedComputeLease::Poll();
    need(FfxApiProxy::destroys==destroys+1,"completed standalone context destroys exactly once");
    *evidence<<"RESOLUTION {\"width\":"<<width<<",\"height\":"<<height<<",\"warmup\":"<<warm<<",\"samples\":"<<count
        <<",\"staging_bytes\":"<<staging<<",\"auxiliary_bytes\":"<<auxiliary<<",\"contexts_created\":1,\"contexts_destroyed\":1}\n";
}
}
int main(int argc,char** argv)try
{
    SetPriorityClass(GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS);
    need(argc==4,"standalone timing requires warmup/sample counts and dedicated evidence path");
    const unsigned warm=std::stoul(argv[1]),count=std::stoul(argv[2]);
    need(warm>=4&&warm<=16&&count>=8&&count<=64,"bounded standalone timing sample budget");
    std::ofstream evidence(argv[3],std::ios::binary);need(bool(evidence),"dedicated machine evidence file opened");
    evidence<<std::setprecision(12);StandaloneCost::evidence=&evidence;
    loadReal();need(FfxApiProxy::real,"signed provider required");
    StandaloneCost::actualDispatch=FfxApiProxy::dispatchFunction;
    FfxApiProxy::dispatchFunction=&StandaloneCost::timedExport;
    Host host;ComPtr<IDXGIFactory6> factory;ComPtr<IDXGIAdapter1> adapter;DXGI_ADAPTER_DESC1 adapterDesc{};
    hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));hr(factory->EnumAdapterByLuid(host.device->GetAdapterLuid(),IID_PPV_ARGS(&adapter)));
    hr(adapter->GetDesc1(&adapterDesc));need(!(adapterDesc.Flags&DXGI_ADAPTER_FLAG_SOFTWARE),"timing requires hardware adapter, never WARP fallback");
    evidence<<"ADAPTER {\"vendor_id\":"<<adapterDesc.VendorId<<",\"device_id\":"<<adapterDesc.DeviceId
        <<",\"software\":false,\"debug_layer\":true,\"gpu_based_validation\":false,\"queue\":\"DIRECT\"}\n";
    StandaloneCost::run(host,1505,847,warm,count);StandaloneCost::run(host,2560,1440,warm,count);
    FfxApiProxy::dispatchFunction=StandaloneCost::actualDispatch;
    need(FfxApiProxy::creates==2&&FfxApiProxy::destroys==2&&FfxApiProxy::live.empty(),"two resolutions balance provider lifetime");
    hr(host.list->Close());host.checkDebug();
    evidence.flush();need(bool(evidence),"all80 samples and metadata flushed before final PASS");
    evidence.close();need(!evidence.fail(),"dedicated machine evidence closed successfully");
    StandaloneCost::evidence=nullptr;
    std::cout<<"PASS checks="<<checks<<" signed_export_calls="<<StandaloneCost::exportCalls
        <<" context_creates=2 context_destroys=2 real_detours=0 game_hooks=0 conversion=0 upscaler=0 debug_errors=0 debug_warnings=0\n";
    return 0;
}
catch(const std::exception& error){std::cerr<<"FAIL "<<error.what()<<'\n';return 1;}
'''


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summary(values):
    ordered = sorted(values)
    def percentile(p):
        position = (len(ordered) - 1) * p
        lower = int(position)
        return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower)
    return {"mean_ms": statistics.fmean(values), "median_ms": statistics.median(values),
            "p95_ms": percentile(.95), "p99_ms": percentile(.99), "max_ms": max(values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--production-root", type=Path, default=Path(os.environ.get("FSRD_NRD_PRODUCTION_ROOT", OWN)))
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--samples", type=int, default=32)
    args = parser.parse_args()
    if not 4 <= args.warmup <= 16 or not 8 <= args.samples <= 64:
        raise ValueError("Warmup4..16/samples8..64 required")
    root = args.production_root.resolve()
    fixture_dir = root / "OptiScaler/shaders/shader_tools/tests"
    fixture = fixture_dir / "nrd_bridge_rr_fixture.cpp"
    work = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/rr-perf-prepare")).resolve()
    if work.drive.upper() != "F:" or "FSRD" not in work.parts:
        raise RuntimeError("Performance scratch must remain in F:/FSRD")
    work.mkdir(parents=True, exist_ok=True)
    source = work / "nrd_rr_standalone_perf.cpp"
    source.write_text(CPP.replace("__FIXTURE__", fixture.as_posix()), encoding="utf-8")
    if fingerprint(DLL) != DLL_SHA256:
        raise RuntimeError("Signed provider SHA differs from the attested1.2 baseline")
    paths = [fixture, fixture_dir / "nrd_bridge_rr_test_support.h",
             root / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp",
             root / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h",
             root / "OptiScaler/misc/RecordedComputeLease_Dx12.h"]
    contract = {"scope": __doc__, "source": str(source), "source_sha256": fingerprint(source),
                "production_root": str(root), "inputs": {str(p): fingerprint(p) for p in paths},
                "provider": str(DLL), "provider_sha256": DLL_SHA256, "resolutions": [[1505, 847], [2560, 1440]],
                "warmup": args.warmup, "samples": args.samples, "prepared_only": not args.run,
                "timing_scopes": {"GPU": ["pre-export", "signed-provider", "native-b6-capture+Commit", "full-wrapper"],
                                  "CPU": ["PrepareFrame", "full-wrapper-record", "signed-export-only", "submit+wait"]},
                "adapters": "existing Host, ScopedInternal and ResTrack lifetime ABI seams; no physical detours or FrameSurvey"}
    (work / "contract.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    if not args.run:
        print(json.dumps({"source": str(source), "compiled": False, "executed": False, "resolutions": contract["resolutions"]}))
        return
    sys.path[:0] = [str(fixture_dir), str(root / "OptiScaler/shaders/shader_tools")]
    from fsrd_toolchain import compile_cpp, dxc
    from test_fsrd_nrd_bridge_rr import bounded_run
    (work / "pch.h").write_text("#pragma once\n", encoding="utf-8")
    shader = work / "consumer.cso"
    subprocess.run([str(dxc()), "-T", "cs_6_2", "-E", "CSMain", "-O3", "-force-rootsig-ver", "rootsig_1_0",
                    str(fixture_dir / "nrd_bridge_consumer_fixture.hlsl"), "-Fo", str(shader)], check=True)
    (work / "consumer_shader.h").write_text("const unsigned char ConsumerShaderBytes[]={" + ",".join(map(str, shader.read_bytes())) + "};\n", encoding="utf-8")
    exe = work / "nrd_rr_standalone_perf.exe"
    build = compile_cpp(source, exe, ("d3d12.lib", "dxgi.lib", "d3dcompiler.lib"),
                        (work, root / "OptiScaler", root / "OptiScaler/include", root / "external/streamline",
                         root / "external/FidelityFX-SDK/ffx-api/include/ffx_api"))
    (work / "build.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    machine = work / "samples.jsonl"
    text, peak, seconds, log = bounded_run([str(exe), str(args.warmup), str(args.samples), str(machine)], work / "standalone")
    records = machine.read_text(encoding="utf-8").splitlines()
    samples = [json.loads(line[7:]) for line in records if line.startswith("SAMPLE ")]
    summaries = [json.loads(line[11:]) for line in records if line.startswith("RESOLUTION ")]
    adapters = [json.loads(line[8:]) for line in records if line.startswith("ADAPTER ")]
    assert len(samples) == 2 * (args.warmup + args.samples) and len(summaries) == 2
    assert len(records) == len(samples) + len(summaries) + len(adapters)
    assert len(adapters) == 1 and not adapters[0]["software"]
    assert "real_detours=0 game_hooks=0 conversion=0 upscaler=0 debug_errors=0 debug_warnings=0" in text
    for row in summaries:
        selected = [value for value in samples if (value["width"], value["height"]) == (row["width"], row["height"])]
        steady = [value for value in selected if not value["warmup"]]
        assert len(steady) == args.samples
        row["first_frame"] = selected[0]
        row["steady"] = {key: summary([value[key] for value in steady]) for key in steady[0] if key.endswith("_ms")}
    result = {"contract": contract, "samples": samples, "resolutions": summaries, "adapter": adapters[0], "seconds": seconds,
              "peak_resident_bytes": peak, "native_log": str(log), "machine_evidence": str(machine),
              "machine_sha256": fingerprint(machine), "exe_sha256": fingerprint(exe)}
    (work / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
