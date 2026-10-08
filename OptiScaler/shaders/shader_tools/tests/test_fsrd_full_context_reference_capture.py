"""Focused production-recorder diagnostic contract host; no IQ/game pixels.

Preparation and compilation are separate from execution. The CPU host never
creates a D3D device, adapter, command queue, WARP instance, or SDK context.
Root serializes any separate GPU recorder validation.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp

ROOT = Path(__file__).resolve().parents[4]
CPP = r'''
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#define FSRD_GAME_TRACE_TEST
#include "__RECORDER__"
using Trace = FSRDGameTraceSession;
void Need(bool okay,const char* message) { if (!okay) throw std::runtime_error(message); }
template<class F> void Reject(F body,const char* message)
{ bool failed=false; try { body(); } catch (const std::exception&) { failed=true; } Need(failed,message); }
std::string Hex(const std::array<uint8_t,184>& bytes)
{
    constexpr char digits[]="0123456789abcdef";
    std::string result; result.reserve(368);
    for (auto b:bytes) { result.push_back(digits[b>>4]); result.push_back(digits[b&15]); }
    return result;
}
void Put(std::array<uint8_t,184>& bytes,size_t offset,uint32_t value) { memcpy(bytes.data()+offset,&value,4); }
int main(int argc,char** argv)
{
    try
    {
        Need(argc==2,"supply an absolute F: scratch output root");
        g_dllPath=std::filesystem::path(argv[1])/"test-only.dll";
        Trace::Request request;
        Need(!request.fullContextReference,"diagnostic mode is not opt-in");
        Need(!Trace::WantsFullContextReference(),"idle diagnostic gate enabled");
        Need(Trace::RequestStart(request),"legacy request rejected");
        Need(!Trace::WantsFullContextReference(),"legacy request enables diagnostics");
        { std::scoped_lock lock(Global().mutex);
          Need(!Global().current->manifest.contains("full_context_reference_requested"),"legacy manifest shape changed"); }
        Trace::RequestStop();
        request.fullContextReference=true;
        request.outputRoot=argv[1];
        Need(Trace::RequestStart(request),"diagnostic request rejected");
        Need(Trace::WantsFullContextReference(),"actual diagnostic request not enabled");
        { std::scoped_lock lock(Global().mutex);
          Need(Global().current->manifest["full_context_reference_requested"]==true,"manifest lacks diagnostic admission");
          Need(!Global().current->defaultPayloadQuota,"diagnostic extended payload quota missing"); }
        Trace::RequestStop();
        Need(!Trace::WantsFullContextReference(),"stopped diagnostic gate enabled");
        Frame legacy, diagnostic(true);
        Need(legacy.diagnosticCount==19 && diagnostic.diagnosticCount==21,"legacy/reference diagnostic role count mismatch");
        Session session;
        session.width=128; session.height=847; session.rw=1505; session.rh=847;
        session.fullContextReference=true; session.defaultPayloadQuota=false;
        session.diskAvailable=UINT64_MAX;
        Need(FullContextReferencePayloadBytes(session)==128ull*847*16,"two RGBA16F head payload omitted from preflight");
        const uint64_t base=128ull*847*121;
        PreflightPayload(session,base+FullContextReferencePayloadBytes(session));
        Need(session.status.estimatedPayloadBytes==(base+128ull*847*16)*128,"target diagnostic payload estimate wrong");
        session.diskAvailable=session.manifest["destination_required_bytes"].get<uint64_t>()-1;
        Reject([&] { PreflightPayload(session,base+FullContextReferencePayloadBytes(session)); },"insufficient disk admitted diagnostic source copies");
        session.fullContextReference=false;
        Need(FullContextReferencePayloadBytes(session)==0,"legacy payload budget changed");
        session.fullContextReference=true;
        ObserveFullContextReferenceQueue(session,777);
        ObserveFullContextReferenceQueue(session,777);
        Reject([&] { ObserveFullContextReferenceQueue(session,778); },"mixed actual submission queues admitted");
        Reject([&] { ObserveFullContextReferenceQueue(session,0); },"unknown actual submission queue admitted");
        session.fullContextReference=false;
        ObserveFullContextReferenceQueue(session,778);
        Need(session.referenceSubmissionQueue==777,"legacy mode changed diagnostic queue identity");
        session.fullContextReference=true;
        Trace::FrameInfo info; info.evaluationId=71; info.frameIndex=99; info.dispatchFlags=2;
        Frame frame(true);
        frame.controls={{"motion_vector_scale",{1.0,2.0,3.0}},{"render_size",{1505,847}},
            {"view",Json::array()},{"projection",Json::array()},{"jitter",{.25,-.125}},
            {"camera_delta",{.01,0.0,-.375}},{"depth_bounds",{.02,1000.0}}};
        for (size_t i=0;i<16;++i)
        {
            frame.controls["view"].push_back(double(i+1)*.03125);
            frame.controls["projection"].push_back(double(i+17)*.015625);
        }
        frame.controls["rr_dispatch"]={{"context_generation",uint64_t(8)},{"evaluation_id",info.evaluationId}};
        frame.settings={{"rr_create_contract",{{"provider_id",uint64_t(4311875584)}, {"max_render_size",{1505,847}}}},
            {"sdk_tuning",{.5,.5,40000.0,40.0,.5,.1}},{"sdk_debug_depth_bounds",{0.0,1024.0}}};
        // Serialize the ACTUAL native type. A shared hand-packed parser layout
        // previously hid an ABI error that the independent WARP fixture found.
        ffxDispatchDescDenoiser nativePrimary {};
        auto applyFloats=[](auto& field,const Json& values) {
            std::vector<float> exact;
            for (const auto& value:values) exact.push_back(value.get<float>());
            Need(exact.size()*4==sizeof(field),"actual SDK field size differs from controls");
            memcpy(&field,exact.data(),sizeof(field));
        };
        applyFloats(nativePrimary.motionVectorScale,frame.controls["motion_vector_scale"]);
        applyFloats(nativePrimary.jitterOffsets,frame.controls["jitter"]);
        applyFloats(nativePrimary.cameraPositionDelta,frame.controls["camera_delta"]);
        applyFloats(nativePrimary.view,frame.controls["view"]);
        applyFloats(nativePrimary.projection,frame.controls["projection"]);
        applyFloats(nativePrimary.linearDepthBounds,frame.controls["depth_bounds"]);
        nativePrimary.renderSize={1505,847}; nativePrimary.frameIndex=info.frameIndex; nativePrimary.flags=info.dispatchFlags;
        static_assert(offsetof(ffxDispatchDescDenoiser,motionVectorScale)==264);
        static_assert(offsetof(ffxDispatchDescDenoiser,jitterOffsets)==276);
        static_assert(offsetof(ffxDispatchDescDenoiser,cameraPositionDelta)==284);
        static_assert(offsetof(ffxDispatchDescDenoiser,view)==296);
        static_assert(offsetof(ffxDispatchDescDenoiser,projection)==360);
        static_assert(offsetof(ffxDispatchDescDenoiser,linearDepthBounds)==424);
        static_assert(offsetof(ffxDispatchDescDenoiser,renderSize)==432);
        static_assert(offsetof(ffxDispatchDescDenoiser,frameIndex)==440);
        static_assert(offsetof(ffxDispatchDescDenoiser,flags)==444 && sizeof(ffxDispatchDescDenoiser)==448);
        std::array<uint8_t,184> primary {};
        memcpy(primary.data(),reinterpret_cast<const uint8_t*>(&nativePrimary)+offsetof(ffxDispatchDescDenoiser,motionVectorScale),primary.size());
        auto nativeReference=nativePrimary; nativeReference.flags|=FFX_DENOISER_DISPATCH_RESET;
        std::array<uint8_t,184> reference {};
        memcpy(reference.data(),reinterpret_cast<const uint8_t*>(&nativeReference)+offsetof(ffxDispatchDescDenoiser,motionVectorScale),reference.size());
        Json boundary={{"wireformat","ffxDispatchDescDenoiser_native_ABI_suffix_264_184"},{"native_dispatch_bytes",448},
            {"controls_byte_count",184},{"controls_offset_in_dispatch",264},{"controls_flags_offset_in_segment",180},
            {"evaluation_id",info.evaluationId},{"frame_index",info.frameIndex},{"primary_dispatch_flags",info.dispatchFlags},
            {"dispatch_flags",info.dispatchFlags|1u},{"render_size",{1505,847}},
            {"context_generation",uint64_t(3)},{"reference_evaluation_id",uint64_t(1)},
            {"primary_context_generation",uint64_t(8)},{"primary_pre_sdk_boundary",frame.controls["rr_dispatch"]},
            {"create_contract",frame.settings["rr_create_contract"]},{"sdk_tuning",frame.settings["sdk_tuning"]},
            {"sdk_debug_depth_bounds",frame.settings["sdk_debug_depth_bounds"]},
            {"controls",frame.controls},{"primary_control_words_hex",Hex(primary)},{"diagnostic_control_words_hex",Hex(reference)}};
        ValidateFullContextReferenceBoundary(boundary,frame,session,info);
        unsigned rejected=0;
        // Canonical replay controls have a distinct wire order. Even with a
        // dishonest native label they must never be accepted as this suffix.
        std::array<uint8_t,184> canonical {}; size_t canonicalOffset=8;
        Put(canonical,0,info.frameIndex); Put(canonical,4,info.dispatchFlags);
        for (const auto* key:{"view","projection","jitter","camera_delta","motion_vector_scale","depth_bounds"})
            for (const auto& value:frame.controls[key])
            {
                const float applied=value.get<float>(); uint32_t bits=0; memcpy(&bits,&applied,4);
                Put(canonical,canonicalOffset,bits); canonicalOffset+=4;
            }
        Put(canonical,canonicalOffset,1505); Put(canonical,canonicalOffset+4,847);
        auto canonicalReference=canonical; Put(canonicalReference,4,info.dispatchFlags|1u);
        auto wrongWire=boundary; wrongWire["primary_control_words_hex"]=Hex(canonical);
        wrongWire["diagnostic_control_words_hex"]=Hex(canonicalReference);
        Reject([&] { ValidateFullContextReferenceBoundary(wrongWire,frame,session,info); },"canonical replay controls admitted as native SDK suffix"); ++rejected;
        for (size_t i=0;i<180;++i)
        {
            auto changed=reference; changed[i]^=1;
            auto bad=boundary; bad["diagnostic_control_words_hex"]=Hex(changed);
            Reject([&] { ValidateFullContextReferenceBoundary(bad,frame,session,info); },"non-RESET native byte change admitted"); ++rejected;
        }
        for (const auto* key:{"evaluation_id","frame_index","primary_dispatch_flags","dispatch_flags","native_dispatch_bytes","controls_byte_count","controls_offset_in_dispatch","controls_flags_offset_in_segment"})
        {
            auto bad=boundary; bad[key]=bad[key].get<uint64_t>()+1;
            Reject([&] { ValidateFullContextReferenceBoundary(bad,frame,session,info); },"mismatched boundary admitted"); ++rejected;
        }
        auto bad=boundary; bad["controls"]["jitter"][0]=.5;
        Reject([&] { ValidateFullContextReferenceBoundary(bad,frame,session,info); },"different JSON controls admitted"); ++rejected;
        for (const auto* key:{"sdk_tuning","sdk_debug_depth_bounds"})
        {
            bad=boundary; bad[key][0]=bad[key][0].get<double>()+.25;
            Reject([&] { ValidateFullContextReferenceBoundary(bad,frame,session,info); },"changed RR tuning admitted"); ++rejected;
        }
        bad=boundary; bad["create_contract"]["provider_id"]=uint64_t(1);
        Reject([&] { ValidateFullContextReferenceBoundary(bad,frame,session,info); },"changed provider create contract admitted"); ++rejected;
        bad=boundary; bad["reference_evaluation_id"]=uint64_t(2);
        Reject([&] { ValidateFullContextReferenceBoundary(bad,frame,session,info); },"reference begins with skipped evaluation"); ++rejected;
        Reject([&] { ValidateFullContextReferenceSources(session,frame,info,{}); },"required two-head source omission admitted"); ++rejected;
        session.fullContextReference=false;
        std::array<Trace::DiagnosticSource,1> unrequested {{ {"rr_full_context_reset_specular",{}} }};
        Reject([&] { ValidateFullContextReferenceSources(session,frame,info,unrequested); },"unrequested extra source admitted"); ++rejected;
        session.fullContextReference=true;
        constexpr size_t cameraYOffset=offsetof(ffxDispatchDescDenoiser,cameraPositionDelta)-NativeControlOffset+sizeof(float);
        Put(primary,cameraYOffset,0x80000000u); reference=primary; Put(reference,180,3);
        boundary["primary_control_words_hex"]=Hex(primary); boundary["diagnostic_control_words_hex"]=Hex(reference);
        ValidateFullContextReferenceBoundary(boundary,frame,session,info); // Legacy JSON can lose -0 spelling.
        Put(reference,cameraYOffset,0); bad=boundary; bad["diagnostic_control_words_hex"]=Hex(reference);
        Reject([&] { ValidateFullContextReferenceBoundary(bad,frame,session,info); },"signed-zero native mutation admitted"); ++rejected;
        Trace::FrameInfo alreadyReset=info; alreadyReset.dispatchFlags=3; alreadyReset.reset=true;
        Put(primary,180,3); reference=primary;
        boundary["primary_dispatch_flags"]=3; boundary["dispatch_flags"]=3;
        boundary["primary_control_words_hex"]=Hex(primary); boundary["diagnostic_control_words_hex"]=Hex(reference);
        ValidateFullContextReferenceBoundary(boundary,frame,session,alreadyReset);
        std::cout<<Json{{"schema","fsrd-full-context-reference-recorder-cpu-v1"},{"status","PASS"},
            {"native_control_mutation_rejections",rejected},{"gpu_work",0},{"sdk_dispatches",0},
            {"reference_payload_bytes_per_128x847_frame",128ull*847*16},
            {"limitations","CPU contract assertions and manufactured bytes; no GPU copy or IQ claim"}}.dump(2)<<'\n';
        return 0;
    }
    catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--compile-only', action='store_true')
    mode.add_argument('--cpu-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.drive.upper() != 'F:':
        raise ValueError('Diagnostic host and generated data must stay on F:')
    output.mkdir(parents=True, exist_ok=True)
    stubs = output/'stubs'; stubs.mkdir(exist_ok=True)
    (stubs/'pch.h').write_text('#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n')
    (stubs/'Util.h').write_text('#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\n'
                              'namespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n')
    source = output/'fsrd_full_context_reference_recorder.cpp'
    source.write_text(CPP.replace('__RECORDER__', (ROOT/'OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp').as_posix()))
    exe = output/'fsrd_full_context_reference_recorder.exe'
    if args.compile_only:
        compile_cpp(source, exe, ('d3d12.lib', 'dxgi.lib', 'bcrypt.lib'),
                    (stubs, ROOT/'external/nlohmann', ROOT/'external/FidelityFX-SDK/ffx-api/include/ffx_api'))
    elif args.cpu_only:
        result = subprocess.run([str(exe), str(output)], check=True, capture_output=True, text=True)
        report = json.loads(result.stdout)
        (output/'recorder_cpu_receipt.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps({'status':'PREPARED_ONLY','source':str(source),'gpu_work':0,'builds':0}))


if __name__ == '__main__':
    main()
