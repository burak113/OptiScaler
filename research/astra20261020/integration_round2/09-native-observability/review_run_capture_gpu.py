"""Derived Windows WARP recorder check; source preparation is not native execution.

Reuses the frozen repository fixture's Host, owned resources and stubs, then
replaces only its main with job09 checks. Provider output/selection/scale are
explicit synthetic adapters. The production readback, submission fence, Map,
manifest publisher and new observation recorder execute unchanged on Windows.

Run native execution only through the repository's serialized Windows GPU
wrapper. On Linux use --prepare-only; that never claims compilation or WARP.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TESTS = ROOT / "OptiScaler/shaders/shader_tools/tests"
sys.path[:0] = [str(HERE), str(TESTS), str(TESTS.parent)]
import test_fsrd_nrd_game_trace_bridge as existing
existing.ROOT = ROOT  # Derived source always comes from this checkout, not an inherited overlay.


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(out: Path) -> tuple[Path, tuple]:
    ast.parse(Path(__file__).read_text(encoding="utf-8"))
    exe, args = existing.prepare(out)
    source = args[0]
    original = source.read_text(encoding="utf-8")
    if original.count("int main(") != 1:
        raise RuntimeError("Frozen fixture main boundary is no longer unique")
    source.write_text(original.split("int main(", 1)[0] + "\n" +
                      (HERE / "review_capture_gpu.cpp").read_text(encoding="utf-8"), encoding="utf-8")
    manifest_path = out / "prepared-source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = [Path(__file__), HERE / "review_capture_gpu.cpp", HERE / "observation_capture_reader.py", source,
             TESTS / "test_fsrd_game_trace_capture.py", TESTS.parent / "fsrd_toolchain.py",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdObservationContract.h",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/FSRDNrdSupportContract.h",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/RRTraceFence.h",
             ROOT / "OptiScaler/shaders/fsrd_preprocess/RRTraceFenceState.h"]
    manifest["source_hashes"].update({str(path): sha(path) for path in files})
    manifest.update(scope="job09_real_production_recorder_copy_fence_Map_publication; controlled_provider_output_selection_scale_adapters",
                    status="SOURCE_PREPARED", compiler_executed=False, native_executed=False,
                    AMD_SDK_executed=False, scale_roundtrip_executed=False, quality_accepted=False)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return exe, args


def canary(x: int, y: int, channel: int, lobe: int, phase: int) -> int:
    if channel == 3:
        return (0x7E01, 0x7C01, 0x8000, 0x0001, 0x0000)[(x + 3*y + lobe + phase) % 5]
    return 0x3000 + 0x100*lobe + 0x800*phase + (x + 3*y + channel) % 512


def inspect_result(out: Path) -> dict:
    result_path = out / "review-native-observation-gpu.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(message)

    check(result["actual_sdk_dispatches"] == 0, "fixture unexpectedly claimed an SDK dispatch")
    check(result["scale_roundtrip_executed"] is False, "synthetic scale metadata became a roundtrip claim")
    check(result["quality_accepted"] is False, "recording fixture cannot accept visual quality")
    check(result["off_no_allocation_or_native_access"] is True, "OFF hook failed")
    check(result["stale_epoch_rejected_before_publication"] is True, "stale epoch admitted")
    check(result["debug_errors"] == result["debug_warnings"] == 0, "D3D debug layer reported a warning/error")
    for protected, key in ((False, "raw_capture"), (True, "protected_capture")):
        folder = Path(result[key])
        from observation_capture_reader import validate_capture
        reader_report = validate_capture(folder)
        check(reader_report["valid"] is True and reader_report["published_frames"] == 1,
              "offline reader rejected actual published capture")
        (out / (key + "-offline-reader.json")).write_text(json.dumps(reader_report, indent=2) + "\n", encoding="utf-8")
        manifest = json.loads((folder / "capture.json").read_text(encoding="utf-8"))
        check(manifest["manifest_published_frames"] == 1, "wrong publication count")
        check(manifest["render_extent"] == [137, 131], "odd allocation extent lost")
        check(manifest["roi"]["origin"] == [7, 1] and manifest["roi"]["extent"] == [128, 128], "ROI lost")
        frame = manifest["frames"][0]
        observation = frame["native_observations"]
        check(observation["schema"] == "fsrd-native-observation-v1", "wrong schema")
        check(observation["stamp"] == {"stream_id": 11, "frame": 500, "reset_epoch": 1,
                                        "resource_epoch": 7, "known": True}, "stamp does not match actual early identity")
        check(observation["actual_reset"] is True and observation["recording_id"] == 20,
              "recording/reset identity lost")
        check(observation["support"]["valid"] is False and observation["support"]["reason_bits"] == 3,
              "missing native donor/key proof was accepted")
        for role in ("title_native_normal_roughness", "title_raw_depth", "title_raw_motion",
                     "title_crop_origin", "material_or_layer_identity", "upstream_exposure_and_modulation"):
            check(bool(observation["unknown"].get(role)), "unobserved native fact was not explicit: " + role)
        images = {image["name"]: image for image in frame["images"]}
        payloads = {}
        for name, image in images.items():
            payload = (folder / image["file"]).read_bytes()
            check(len(payload) == image["bytes"], "payload length changed: " + name)
            check(hashlib.sha256(payload).hexdigest() == image["sha256"], "payload checksum mismatch: " + name)
            payloads[name] = payload
        for lobe, lobe_name, scale in ((0, "specular", 256), (1, "diffuse", 16)):
            authority = observation["authority"][lobe_name]
            check(authority["selection_path"] == ("lobe_recovery" if protected else "raw_rr"), "selection path lost")
            check(authority["equality_guard"] == 1, "word-equal adapter was not equal")
            check(authority["selection_authority"] == (2 if protected else 1), "equality manufactured authority")
            check(authority["raw_authority_valid"] is (not protected), "protected equal-word output accepted as raw")
            check(authority["raw_edit_eligible"] is False, "authority bypassed missing support certificate")
            for name, phase in (("physical_source_", 0), ("physical_pre_scale_", 0),
                                ("raw_rr_", 1), ("selected_rr_", 1)):
                role = name + lobe_name
                surface = observation["surfaces"][role]
                check(surface["stamp"] == observation["stamp"], "surface stamp mismatch: " + role)
                check(surface["allocation_extent"] == [137, 131] and surface["active_extent"] == [137, 131],
                      "allocation/active extents lost: " + role)
                check(surface["crop_origin"] == [7, 1] and surface["captured_extent"] == [128, 128],
                      "surface crop lost: " + role)
                check(surface["dxgi_format"] == 10 and surface["encoding"] == 1, "format/encoding lost: " + role)
                check(surface["scale"] == {"known": True, "provider_multiplier": scale, "stored_multiplier": 1},
                      "per-lobe physical scale lost: " + role)
                layout = surface["payload_layout"]
                check(layout == {"byte_offset": 0, "row_pitch": 1024, "row_bytes": 1024, "bytes": 131072},
                      "tight row indexing inconsistent: " + role)
                check(surface["native_texture_row_pitch"] is None, "opaque native tiled pitch was invented")
                words = struct.unpack("<65536H", payloads[surface["image"]])
                expected = tuple(canary(x+7, y+1, channel, lobe, phase)
                                 for y in range(128) for x in range(128) for channel in range(4))
                check(words == expected, "early original RGB/opaque alpha words not preserved: " + role)
            check(observation["surfaces"]["physical_source_" + lobe_name]["image"] ==
                  observation["surfaces"]["physical_pre_scale_" + lobe_name]["image"],
                  "same-time original/effective alias was copied twice")
            check(payloads[images["input_" + lobe_name]["name"]] ==
                  payloads[observation["surfaces"]["raw_rr_" + lobe_name]["image"]],
                  "synthetic overwrite was not visible to late input/raw recording")
        check(observation["surfaces"]["depth_validity"]["availability"] == "missing", "adapter invented validity")
        check(observation["surfaces"]["anchor_sums"]["availability"] == "missing", "adapter invented native carry buffer")
    result["python_checks"] = checks
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(os.environ["FSRD_GPU_TEST_OUTPUT"]) if os.environ.get("FSRD_GPU_TEST_OUTPUT") else None)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.output is None:
        parser.error("--output or the serialized wrapper's FSRD_GPU_TEST_OUTPUT is required")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"command": sys.argv, "platform": platform.platform(), "python": sys.version,
               "status": "STARTED", "compiler_executed": False, "native_executed": False,
               "AMD_SDK_executed": False, "scale_roundtrip_executed": False, "quality_accepted": False}
    receipt_path = out / "review-capture-execution.json"
    try:
        exe, compiler_args = prepare(out)
        receipt["prepared_manifest_sha256"] = sha(out / "prepared-source-manifest.json")
        if args.prepare_only:
            receipt["status"] = "SOURCE_PREPARED_NATIVE_PENDING"
            receipt["exit_code"] = 0
            return 0
        if os.name != "nt":
            raise RuntimeError("Real WARP execution requires Windows; use --prepare-only on this host")
        if not os.environ.get("FSRD_GPU_TEST_OUTPUT"):
            raise RuntimeError("Native run must use lead_ops/run_task_test.py, which supplies FSRD_GPU_TEST_OUTPUT")
        # Run discovery/compiler in a child so even native CL output is captured.
        # Disable the build cache to keep this execution receipt unambiguous.
        compiler_script = ("import json,sys; from pathlib import Path; "
                           "sys.path.insert(0,sys.argv[1]); from fsrd_toolchain import compile_cpp; "
                           "a=json.loads(sys.argv[2]); compile_cpp(Path(a[0]),Path(a[1]),a[2],a[3])")
        serialized_args = [str(compiler_args[0]), str(compiler_args[1]), list(compiler_args[2]),
                           [str(path) for path in compiler_args[3]]]
        environment = dict(os.environ, FSRD_CPP_CACHE="0")
        receipt["compiler_attempted"] = True
        compiled = subprocess.run([sys.executable, "-c", compiler_script, str(TESTS.parent),
                                   json.dumps(serialized_args)], capture_output=True, text=True,
                                  timeout=300, env=environment)
        (out / "compiler.stdout.log").write_text(compiled.stdout, encoding="utf-8")
        (out / "compiler.stderr.log").write_text(compiled.stderr, encoding="utf-8")
        receipt["compiler_exit_code"] = compiled.returncode
        compiled.check_returncode()
        receipt["compiler_executed"] = True
        receipt["executable_sha256"] = sha(exe)
        receipt["native_executed"] = True
        native = subprocess.run([str(exe), str(out)], capture_output=True, text=True, timeout=120,
                                creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (out / "native.stdout.log").write_text(native.stdout, encoding="utf-8")
        (out / "native.stderr.log").write_text(native.stderr, encoding="utf-8")
        receipt["native_exit_code"] = native.returncode
        native.check_returncode()
        receipt["result"] = inspect_result(out)
        receipt["status"] = "WARP_RECORDER_PASSED_PROVIDER_AND_QUALITY_PENDING"
        receipt["exit_code"] = 0
        return 0
    except Exception as error:
        receipt["status"] = "FAILED"
        receipt["exit_code"] = 1
        receipt["error"] = str(error)
        (out / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
