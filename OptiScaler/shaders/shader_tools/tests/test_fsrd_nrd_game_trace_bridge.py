"""Production bridge recorder with real WARP copies/fences, explicit RR-output adapter.

--prepare-only writes the exact source/manifest of inputs without a compiler or
native process. Native execution must use the lead's serialized GPU wrapper.
"""
from pathlib import Path
import ast
import hashlib
import json
import os
import subprocess
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("FSRD_NRD_PRODUCTION_ROOT", HERE.parents[3])).resolve()
sys.path[:0] = [str(HERE), str(HERE.parent)]
from fsrd_toolchain import compile_cpp
import test_fsrd_game_trace_capture as original
from fsrd_nrd_trace_replay import inspect_capture
from test_fsrd_nrd_trace_replay_contract import exercise
from test_fsrd_temporal_trace_contract import exercise_adaptive


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    stubs = out / "stubs"
    stubs.mkdir(exist_ok=True)
    (stubs / "pch.h").write_text("#pragma once\n#define NOMINMAX\n#include <windows.h>\n#include <filesystem>\n", encoding="utf-8")
    (stubs / "Util.h").write_text("#pragma once\n#include <filesystem>\ninline std::filesystem::path g_dllPath;\n"
                                  "namespace Util { inline std::filesystem::path DllPath() { return g_dllPath; } }\n", encoding="utf-8")
    feature = (ROOT / "OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp").read_text(encoding="utf-8-sig")
    begin = feature.index("const auto array =", feature.index("if (FSRDGameTraceSession::IsActive())"))
    end = feature.index("// Fingerprint applied semantic controls only.", begin)
    (stubs / "fsrd_game_trace_controls.inc").write_text(feature[begin:end], encoding="utf-8")
    begin = feature.index("const CaptureJson controls {", feature.index("if (FSRDConvShader && FSRDGameTraceSession::WantsSrOutput())"))
    end = feature.index("// FSR's output is UAV here.", begin)
    (stubs / "fsrd_game_trace_sr_controls.inc").write_text(feature[begin:end], encoding="utf-8")
    # Original Host's format/queue/Reset/Map forwarding is retained. This fixture
    # creates its converted inputs in the production NPSR state instead of the
    # ordinary recorder's combined PSR|NPSR state; no assertion body is changed.
    prefix = original.CPP.split("void CpuChecks(", 1)[0]
    old_state = "constexpr auto srv = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;"
    assert prefix.count(old_state) == 1
    prefix = prefix.replace(old_state, "constexpr auto srv = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;")
    prefix = prefix.replace("__RECORDER__", (ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp").as_posix())
    prefix = prefix.replace("__RR_HEADER__", (ROOT / "OptiScaler/include/fsr-rr/ffx_denoiser.h").as_posix())
    # Thread-local instrumentation cannot perturb concurrent disk-worker allocations.
    allocation = "std::atomic<bool> g_testFailHeapAllocation {false};"
    assert prefix.count(allocation) == 1
    prefix = prefix.replace(allocation, allocation + "\nthread_local uint64_t bridgeAllocations=0;\nthread_local bool bridgeCountAllocations=false;")
    allocation_check = "    if (g_testFailHeapAllocation.load(std::memory_order_relaxed)) throw std::bad_alloc();"
    assert prefix.count(allocation_check) == 1
    prefix = prefix.replace(allocation_check, "    if(bridgeCountAllocations)++bridgeAllocations;\n" + allocation_check)
    cpp = HERE / "fsrd_nrd_game_trace_bridge.cpp"
    source, exe = out / "bridge_trace.cpp", out / "bridge_trace.exe"
    source.write_text(prefix + "\n" + cpp.read_text(encoding="utf-8"), encoding="utf-8")
    files = [Path(__file__), cpp, ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.cpp",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceSession.h",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDGameTraceBridgeMetadata.h",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.h",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridge_Types.h", source]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    (out / "prepared-source-manifest.json").write_text(json.dumps({"source_hashes": hashes,
        "scope": "real_recorder_WARP_copy_fence_Map_publication; CPU_RR_output_and_commit_adapter",
        "compiler_executed": False, "native_executed": False, "AMD_SDK_executed": False}, indent=2) + "\n", encoding="utf-8")
    args = (source, exe, ("d3d12.lib", "dxgi.lib", "bcrypt.lib"),
            (stubs, ROOT / "OptiScaler", ROOT / "OptiScaler/include", ROOT / "external/streamline",
             ROOT / "external/nlohmann", ROOT / "external/FidelityFX-SDK/ffx-api/include/ffx_api"))
    return exe, args


def run():
    out = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/bridge-trace"))
    for path in (Path(__file__), HERE / "fsrd_nrd_trace_replay.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"))
    exe, args = prepare(out)
    if "--prepare-only" in sys.argv:
        print(json.dumps({"status": "SOURCE_PREPARED", "compiler_executed": False,
                          "native_executed": False, "source_manifest": str(out / "prepared-source-manifest.json")}))
        return
    compile_cpp(*args)
    native = subprocess.run([str(exe), str(out)], capture_output=True, text=True,
                            creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS, timeout=120)
    (out / "native.stdout.log").write_text(native.stdout, encoding="utf-8")
    (out / "native.stderr.log").write_text(native.stderr, encoding="utf-8")
    native.check_returncode()
    result = json.loads((out / "bridge-trace-result.json").read_text(encoding="utf-8"))
    replay = inspect_capture(result["capture"])
    checks = 0
    def check(value):
        nonlocal checks
        checks += 1
        assert value
    check(replay["published_frames"] == 2)
    check(replay["full_temporal_replay_eligible"] is False)
    check(replay["ineligibility_reasons"] == [
        "actual_provider_binary_attestation_unavailable", "replay_prefix_below_64_full_render_frames",
        "replay_manifest_missing_bridge_commit", "replay_manifest_missing_provider_binary_sha256",
        "replay_manifest_missing_guide_motion_policy", "replay_manifest_missing_capture_time_utc",
        "reset_frame_missing_reset_reason"])
    check(all(frame["encoding"]["captured_encoding_word"] == 1 for frame in replay["frames"]))
    check([frame["encoding"]["native_source_word"] for frame in replay["frames"]] == [36, 303])
    check([frame["native_control_header"]["profile"] for frame in replay["frames"]] == ["A_Recon_direct", "B_PrePass"])
    for frame, offsets in zip(replay["frames"], ([448, 452, 456, 460], [456, 460, 472, 476, 516, 520, 576, 580])):
        header = frame["native_control_header"]
        check(header["available"] is True)
        check([word["native_byte_offset"] for word in header["words"]] == offsets)
        check([word["captured_uint32"] for word in header["words"]] == [0x51000000 + offset for offset in offsets])
        check(header["payload"]["bytes"] == 4 * len(offsets))
        check(header["copy_footprint"]["committed_buffer_bytes"] == 0)
    check(replay["frames"][0]["native_control_header"]["owned_status"]["available"] is False)
    check(replay["frames"][1]["native_control_header"]["owned_status"]["captured_uint32"] == 0)
    check(replay["frames"][1]["native_control_header"]["owned_status"]["bytes"] == 4)
    check(result["owned_status_callback"] == 5 and result["status_callback_outside_trace_locks"] is True)
    bad_status = inspect_capture(result["nonzero_status_capture"])
    check("bridge_owned_raw_capture_status_nonzero" in bad_status["ineligibility_reasons"])
    check(bad_status["full_temporal_replay_eligible"] is False)
    check(all(frame["frame_parameters"]["jitter"][0] == 0x80000000 for frame in replay["frames"]))
    check([frame["provider"]["signal_flags"] for frame in replay["frames"]] == [34, 34])
    check([frame["provider"]["checkerboard_signal_flags"] for frame in replay["frames"]] == [34, 34])
    check([frame["provider"]["diffuse_checkerboard_origin"] for frame in replay["frames"]] == [0, 1])
    check([frame["provider"]["specular_checkerboard_origin"] for frame in replay["frames"]] == [1, 0])
    check(replay["frames"][0]["actual_dispatch_flags"] & 1)
    check(not replay["frames"][1]["actual_dispatch_flags"] & 1)
    for frame in replay["frames"]:
        check(frame["observations"]["raw_rr_specular"] == frame["observations"]["selected_rr_specular"])
        check(len(frame["skipped_original_dispatches"]) == 1)
    # This validates the real recorder/Map/publisher, not the CPU snapshot adapter.
    for active,key in ((False,"anchor_inactive_capture"),(True,"anchor_active_capture")):
        folder=Path(result[key]);manifest=json.loads((folder/"capture.json").read_text(encoding="utf-8"))
        check(manifest["manifest_published_frames"]==1)
        check(manifest["render_extent"]==[137,131] and manifest["roi"]["origin"]==[7,1] and manifest["roi"]["extent"]==[128,128])
        frame=manifest["frames"][0];images={image["name"]:image for image in frame["images"]}
        check(("post_motion_anchor_gain" in images)==active)
        check(frame["post_motion_anchor"]["active"]==active)
        for role,base in (("input_specular",0x3400 if active else 0x3000),("input_diffuse",0x3800 if active else None)):
            image=images[role];check(image["extent"]==[128,128] and image["crop_origin"]==[7,1])
            payload=(folder/image["file"]).read_bytes();actual=struct.unpack('<'+'H'*(128*128*4),payload)
            expected=tuple(0 if base is None else base+x+7+y+1+c for y in range(128) for x in range(128) for c in range(4))
            check(actual==expected)
        if active:
            image=images["post_motion_anchor_gain"]
            check(image["source_extent"]==[17,16] and image["extent"]==[17,16] and image["crop_origin"]==[0,0])
            check(image["channels"]==4 and image["bytes_per_pixel"]==8 and image["dxgi_format"]==10)
            payload=(folder/image["file"]).read_bytes();check(len(payload)==17*16*8)
            expected=tuple(0x3a00+x+y if c==0 else 0 for y in range(16) for x in range(17) for c in range(4))
            check(struct.unpack('<'+'H'*(17*16*4),payload)==expected)
            check(frame["settings"]["post_motion_anchor"]["local_static_and_neighborhood_recall_required"] is True)
        else:
            check("post_motion_anchor" not in frame["settings"])
    check(result["anchor_preflight"]["active"]["reserved_payload_bytes"]-result["anchor_preflight"]["inactive"]["reserved_payload_bytes"]==17*16*8)
    check(result["actual_sdk_dispatches"] == 0 and result["debug_errors"] == result["debug_warnings"] == 0)
    (out / "replay-inputs.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    contract = exercise(result["capture"], out / "offline-negative-contract")
    adaptive_contract = exercise_adaptive(result["adaptive_capture"], result["capture"], out / "adaptive-negative-contract")
    result["adaptive_contract"] = adaptive_contract
    checks += adaptive_contract["checks"]
    result["offline_contract"] = contract
    result["python_checks"] = checks + contract["checks"]
    result["scope"] = "real_WARP_trace_copy_fence_Map_publication; CPU_RR_output_and_commit_adapter; no_AMD_SDK"
    (out / "bridge-trace-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run()
