"""Source-extracted title/reset regression. Default emits C++ only. --run builds CPU stubs in scratch."""
import sys,os,argparse,subprocess,importlib.util,json,hashlib
from pathlib import Path
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding="utf8",errors="replace")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUTPUT = Path(os.environ["FSRD_GPU_TEST_OUTPUT"])
OUTPUT.mkdir(parents=True,exist_ok=True)
p=argparse.ArgumentParser();p.add_argument("--generate-only",action="store_true");a=p.parse_args()
a.run=not a.generate_only
TEST=ROOT/"OptiScaler/shaders/shader_tools/tests/test_fsrd_postflick_order.py"
spec=importlib.util.spec_from_file_location("order",TEST);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
members="""
    bool m_motionHistoryValid = true, m_recoveryHistoryValid = true, m_gameTraceFrameRecorded = false;
    struct AbortSink { void Abort(const char*) {} } m_research, m_gameTrace;
    float recordedHistory = -1, recordedRefresh = -1;
    uint32_t recordedApplyHistory = 999;
    PostMotionAnchorMath::State m_postMotionState {};
    bool m_postMotionWasEnabled = false, m_postMotionActive = false;
"""
if "bool m_motionHistoryValid" in m.PREAMBLE:
    members=members.replace("    bool m_motionHistoryValid = true, m_recoveryHistoryValid = true, m_gameTraceFrameRecorded = false;","    bool m_recoveryHistoryValid = true, m_gameTraceFrameRecorded = false;")
pre=m.PREAMBLE.replace("struct Host\n{","struct Host\n{"+members,1)
pre=pre.replace('#include "___COLOUR_TRACK_HEADER___"','#include "___COLOUR_TRACK_HEADER___"\n#include "'+(ROOT/"OptiScaler/shaders/fsrd_preprocess/FSRDPostMotionAnchorConstants.h").as_posix()+'"')
pre=pre.replace("___POSTFLICK_HEADER___",m.POSTFLICK_HEADER.as_posix()).replace("___COLOUR_TRACK_HEADER___",m.COLOUR_TRACK_HEADER.as_posix())
dispatch=m.DISPATCH_DEFINITION.replace("std::span<const byte>,","std::span<const byte> cbData,",1)
dispatch=dispatch.replace("    host->note_dispatch(name, inputs, outputs);","""    host->note_dispatch(name, inputs, outputs);
    if (std::string(name) == "post-flick-prepare") {
        float constants[8]; std::memcpy(constants,cbData.data(),sizeof(constants));
        host->recordedHistory=constants[7]; host->recordedRefresh=constants[6];
    }
    if (std::string(name) == "post-flick-apply")
        std::memcpy(&host->recordedApplyHistory,cbData.data()+32*sizeof(float),sizeof(uint32_t));""",1)
main=r"""
static int failures=0, checks=0;
static void need(const char* name,bool ok) {
    ++checks; if(!ok) ++failures;
    std::cout<<"CHECK\t"<<name<<"\t"<<(ok?"PASS":"FAIL")<<"\n";
}
int main() {
    ID3D12GraphicsCommandList list;
    XMFLOAT4X4 identity{};for(int i=0;i<4;++i) identity.m[i][i]=1;
    CompositionDesc desc{};
    desc.DstTexSize=XMFLOAT4(64,32,1.f/64,1.f/32);
    desc.PostFlickFix=true;desc.PostFlickStrength=1;
    desc.ViewMatrix=desc.ProjectionMatrix=desc.PrevViewMatrix=identity;
    const auto seed=[&](Host& h) {
        h.m_postFlickValid=h.m_postFlickWasEnabled=h.m_postFlickActive=true;
        h.m_colourTrackValid=h.m_colourTrackWasEnabled=h.m_colourTrackActive=true;
        h.m_postMotionWasEnabled=h.m_postMotionActive=true;
        h.m_postMotionState.WasEnabled=h.m_postMotionState.Armed=true;
        h.m_postMotionState.Ring[0].Valid=true;h.m_postMotionState.Frame=7;
        h.m_postFlickWidth=64;h.m_postFlickHeight=32;
        h.m_postFlickKeyState.Valid=true;h.m_postFlickKeyState.KeyAge=17;
        h.m_postFlickKeyState.FramesSinceFlick=0;h.m_postFlickKeyState.SettledFrames=0;
        h.m_postFlickKeyState.View=h.m_postFlickKeyState.Projection=identity;
    };
    { Host h;seed(h);h.m_motionHistoryValid=false;
      h.DispatchPostFlick(&list,desc);
      need("title-reset-prepare-history-zero",h.recordedHistory==0);
      need("title-reset-apply-history-zero",h.recordedApplyHistory==0);
      need("title-reset-refreshes-stale-key",h.recordedRefresh==1 && h.m_postFlickKeyState.KeyAge==0);
    }
    { Host h;seed(h);h.DispatchPostFlick(&list,desc);
      need("continuous-frame-keeps-history",h.recordedHistory==1 && h.recordedApplyHistory==1);
      need("continuous-frame-keeps-held-key",h.recordedRefresh==0 && h.m_postFlickKeyState.KeyAge==18);
    }
    { Host h;seed(h);FSRDPreprocessor_Dx12 wrapper{&h};wrapper.InvalidateCompositionHistory();
      need("explicit-invalidation-clears-pf",!h.m_postFlickValid && !h.m_postFlickWasEnabled && !h.m_postFlickActive);
      need("explicit-invalidation-clears-colour-track",!h.m_colourTrackValid && !h.m_colourTrackWasEnabled && !h.m_colourTrackActive);
      need("explicit-invalidation-clears-anchor-ring",!h.m_postMotionWasEnabled && !h.m_postMotionActive &&
          !h.m_postMotionState.WasEnabled && !h.m_postMotionState.Armed &&
          !h.m_postMotionState.Ring[0].Valid && h.m_postMotionState.Frame==0);
      h.DispatchPostFlick(&list,desc);
      need("invalidation-first-dispatch-does-not-read-history",h.recordedHistory==0 && h.recordedApplyHistory==0 && h.recordedRefresh==1);
    }
    { Host h;seed(h);FSRDPreprocessor_Dx12 wrapper{&h};wrapper.FinishCompositionHistory(false);
      need("failed-recording-clears-pf",!h.m_postFlickValid && !h.m_postFlickWasEnabled && !h.m_postFlickActive);
      need("failed-recording-clears-colour-track",!h.m_colourTrackValid && !h.m_colourTrackWasEnabled && !h.m_colourTrackActive);
      need("failed-recording-clears-anchor-ring",!h.m_postMotionWasEnabled && !h.m_postMotionActive &&
          !h.m_postMotionState.WasEnabled && !h.m_postMotionState.Armed &&
          !h.m_postMotionState.Ring[0].Valid && h.m_postMotionState.Frame==0);
      h.DispatchPostFlick(&list,desc);
      need("failed-recording-first-dispatch-does-not-read-history",h.recordedHistory==0 && h.recordedApplyHistory==0 && h.recordedRefresh==1);
    }
    { Host h;seed(h);FSRDPreprocessor_Dx12 wrapper{&h};wrapper.FinishCompositionHistory(true);
      h.DispatchPostFlick(&list,desc);
      need("successful-recording-preserves-history",h.recordedHistory==1 && h.recordedApplyHistory==1);
      need("successful-recording-preserves-colour-anchor",h.m_colourTrackValid && h.m_colourTrackWasEnabled &&
          h.m_colourTrackActive && h.m_postMotionWasEnabled && h.m_postMotionActive &&
          h.m_postMotionState.WasEnabled && h.m_postMotionState.Ring[0].Valid && h.m_postMotionState.Frame==7);
    }
    { Host h;seed(h);h.m_postFlickWasEnabled=false;h.DispatchPostFlick(&list,desc);
      need("option-rising-edge-control-resets",h.recordedHistory==0 && h.recordedApplyHistory==0 && h.recordedRefresh==1);
    }
    std::cout<<"SUMMARY checks="<<checks<<" failures="<<failures<<"\n"; return failures?1:0;
}
"""
sources={}
rel="OptiScaler/shaders/fsrd_preprocess/FSRDPreprocessor_Dx12.cpp"
sources["old"]=subprocess.check_output(["git","-C",str(ROOT),"show","a79473353d7bc93920f881dbe88f5dfbcf761d1f:"+rel]).decode("utf8").replace("\r\n","\n")
sources["fixed"]=(ROOT/rel).read_text(encoding="utf8")
results={}
for name,text in sources.items():
    methods="\n".join(m.method(text,sig) for sig in [m.SIGNATURES[0],m.SIGNATURES[3]])
    inv=m.method(text,"void FSRDPreprocessor_Dx12::InvalidateCompositionHistory() noexcept")
    fin=m.method(text,"void FSRDPreprocessor_Dx12::FinishCompositionHistory(bool successfulNormalFrame) noexcept")
    wrapper="struct FSRDPreprocessor_Dx12 { Host* m_impl; void InvalidateCompositionHistory() noexcept; void FinishCompositionHistory(bool successfulNormalFrame) noexcept; };\n"
    cpp=pre+methods+"\n};\n"+dispatch+wrapper+inv+"\n"+fin+"\n"+main
    out=OUTPUT/("cpu_title_history_"+name);out.mkdir(exist_ok=True)
    source=out/"test.cpp";source.write_text(cpp,encoding="utf8",newline="\n")
    results[name]={"source_sha256_lf":hashlib.sha256(text.encode()).hexdigest(),"generated":str(source)}
    print(name,"generated",source,flush=True)
    if a.run:
        exe=out/"test.exe"
        os.environ["FSRD_CPP_CACHE"]=str(OUTPUT/"cpu_cpp_cache")
        m.compile_cpp(source,exe)
        proc=subprocess.run([str(exe)],capture_output=True,text=True,encoding="utf8",errors="replace")
        (out/"stdout.txt").write_text(proc.stdout+proc.stderr,encoding="utf8")
        results[name].update(exit_code=proc.returncode,stdout=proc.stdout,stderr=proc.stderr)
        print(name,proc.stdout,flush=True)
(OUTPUT/"cpu_title_history_results.json").write_text(json.dumps(results,indent=2),encoding="utf8")
if a.run:
    assert results["old"]["exit_code"]!=0,"old implementation escaped the regression"
    assert results["fixed"]["exit_code"]==0,"fixed implementation failed the regression"
    print("PASS old FAIL / fixed PASS with production method extraction",flush=True)
else: print("C++ generated only; --run is for lead-authorized CPU compile.",flush=True)
