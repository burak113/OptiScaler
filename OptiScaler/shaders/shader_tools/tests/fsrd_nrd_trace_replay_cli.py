"""Inspect or replay a published bridge GAME_TRACE with an explicit trusted DLL.

Replay reproduces captured RR provider work. Metrics compare two observations;
they are neither clean truth nor a game-quality verdict. Native NRD denoised
output is never loaded. Run native work only through the shared test wrapper.
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
import struct
import subprocess
import sys

from fsrd_nrd_trace_replay import inspect_capture, require, safe_file

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("FSRD_NRD_PRODUCTION_ROOT", HERE.parents[3])).resolve()
sys.path.insert(0, str(HERE.parent))
API_VERSION = (1 << 22) | (2 << 12)
SIGNALS = 2 | 32  # Exact bridge packet: direct diffuse and indirect specular.
ORDER = ("input_depth", "input_motion", "input_normal_roughness",
         "input_specular_albedo", "input_diffuse_albedo", "input_diffuse", "input_specular")


def check_provider_contract(replay):
    require(replay["full_temporal_replay_eligible"],
            "inspect-only capture: " + "; ".join(replay["ineligibility_reasons"]))
    first = replay["frames"][0]
    provider = first["provider"]
    require(type(provider.get("version_id")) is int and 0 < provider["version_id"] < (1 << 64),
            "actual provider version id unavailable")
    require(provider.get("api_version") == API_VERSION, "unsupported captured RR API version")
    require(provider.get("signal_flags") == SIGNALS, "unsupported captured signal packet")
    require(provider.get("context_flags") in (0, 1, 2, 3), "unsupported captured context flags")
    require(first["settings"].get("defaults_ready") is True, "queried provider defaults unavailable")
    stable, stable_input_flags = None, None
    for frame in replay["frames"]:
        p = frame["provider"]
        require(all(type(p.get(key)) is int and 0 <= p[key] <= 0xffffffff
                    for key in ("api_version", "signal_flags", "context_flags")), "invalid typed provider create controls")
        for key in ("checkerboard_signal_flags", "diffuse_checkerboard_origin", "specular_checkerboard_origin"):
            require(type(p.get(key)) is int, "captured actual " + key + " unavailable")
        require(p["checkerboard_signal_flags"] & ~SIGNALS == 0
                and p["diffuse_checkerboard_origin"] in (0, 1)
                and p["specular_checkerboard_origin"] in (0, 1), "invalid captured checkerboard controls")
        current = tuple(p.get(key) for key in ("api_version", "version_id", "signal_flags", "context_flags", "checkerboard_signal_flags"))
        require(stable is None or stable == current, "context creation controls changed inside replay")
        stable = current
        input_flags = tuple(frame.get("inputs", {}).get(name, {}).get("source_native_resource_desc", {}).get("flags") for name in ORDER)
        require(all(type(value) is int and value in (0, 4) for value in input_flags), "actual input GPU usage flags unavailable")
        require(stable_input_flags is None or stable_input_flags == input_flags, "input GPU usage flags changed inside replay")
        stable_input_flags = input_flags
        require(frame["actual_dispatch_flags"] & ~3 == 0, "unsupported captured dispatch flags")
        for key in ("provider_defaults", "provider_effective"):
            values = [struct.unpack("<f", struct.pack("<I", value))[0] for value in frame["settings"][key]]
            require(all(math.isfinite(value) for value in values), "nonfinite captured provider settings")
        debugging = bool(p["context_flags"] & 1)
        mode, viewport = frame["settings"].get("native_debug_view"), frame["settings"].get("native_debug_viewport")
        require(type(mode) is int and ((debugging and mode in (0, 1) and type(viewport) is int and 0 <= viewport < 12)
                or (not debugging and mode == -1)), "native debug descriptor differs from context")
    return provider["route_attestation"]["creation"]["implementation_identity"]["disk_sha256"]


@contextmanager
def frozen_provider(path, expected_sha):
    """Keep a read handle denying mutation/deletion through compilation and run.

    The native runner independently hashes/rechecks its loaded file identity.
    This attests disk bytes, never the equality of a loaded memory image.
    """
    require(os.name == "nt", "native replay requires Windows")
    path = Path(path).resolve(strict=True)
    require(path.is_file() and path.suffix.lower() == ".dll", "--provider must name an explicit local DLL")
    require(isinstance(expected_sha, str) and len(expected_sha) == 64
            and all(c in "0123456789abcdef" for c in expected_sha), "invalid captured provider SHA-256")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    read = kernel.ReadFile
    read.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
    read.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes, close.restype = (wintypes.HANDLE,), wintypes.BOOL
    handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
    require(handle != wintypes.HANDLE(-1).value, "could not freeze explicit provider file")
    try:
        digest = hashlib.sha256()
        buffer, length = ctypes.create_string_buffer(1 << 20), wintypes.DWORD()
        while True:
            require(bool(read(handle, buffer, len(buffer), ctypes.byref(length), None)), "provider read failed")
            if not length.value:
                break
            digest.update(buffer.raw[:length.value])
        require(digest.hexdigest() == expected_sha, "explicit provider SHA-256 differs from captured routed provider")
        yield path
    finally:
        close(handle)


def make_job(replay, provider, output):
    root = Path(replay["capture_root"])
    frames = []
    for frame in replay["frames"]:
        def payload(row):
            return dict(row, file=str(safe_file(root, row["file"])))
        frames.append({"ordinal": frame["ordinal"], "sdk_frame_index": frame["sdk_frame_index"],
                       "provider_radiance_scale": frame.get("provider_radiance_scale", 1),
                       "provider_radiance_scales": frame.get("provider_radiance_scales", {"diffuse": frame.get("provider_radiance_scale",1), "specular": frame.get("provider_radiance_scale",1)}),
                       "actual_dispatch_flags": frame["actual_dispatch_flags"],
                       "provider": frame["provider"], "settings": frame["settings"],
                       "controls": payload(frame["provider_controls"]),
                       "inputs": [payload(frame["inputs"][name]) for name in ORDER],
                       "reference_diffuse": payload(frame["observations"]["raw_rr_diffuse"]),
                       "reference_specular": payload(frame["observations"]["raw_rr_specular"])})
    # Exact ABI controls carry renderSize; no camera or guide inference.
    tail = safe_file(root, replay["frames"][0]["provider_controls"]["file"]).read_bytes()
    width, height = struct.unpack_from("<2I", tail, 168)
    return {"schema": "fsrd-nrd-bridge-native-replay-job-v1", "provider": str(provider),
            "provider_sha256": check_provider_contract(replay), "render_extent": [width, height],
            "metrics_file": str(output / "raw-rr-comparison.jsonl"),
            "summary_file": str(output / "native-replay-result.json"), "frames": frames,
            "scope": "actual_RR_only; raw_RR_observation_comparison; no_native_NRD_output; no_quality_oracle"}


def prepare_runner(output):
    sdk = (ROOT / "external/FidelityFX-SDK-v2/Kits/FidelityFX").resolve()
    text = (HERE / "fsrd_nrd_trace_replay_runner.cpp").read_text(encoding="utf-8-sig")
    includes = {"__FFX_LOADER__": sdk / "api/include/ffx_api_loader.h",
                "__FFX_DX12__": sdk / "api/include/dx12/ffx_api_dx12.h",
                "__FFX_DENOISER__": sdk / "denoisers/include/ffx_denoiser.h"}
    for marker, path in includes.items():
        require(path.is_file(), "coherent standalone SDK header missing: " + str(path))
        text = text.replace(marker, path.resolve().as_posix())
    source, executable = output / "native-replay.cpp", output / "native-replay.exe"
    source.write_text(text, encoding="utf-8")
    inputs = [Path(__file__), HERE / "fsrd_nrd_trace_replay_runner.cpp", HERE / "fsrd_nrd_trace_replay.py", *includes.values(), source]
    (output / "runner-source-manifest.json").write_text(json.dumps({"source_sha256": {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
        "compiler_executed": False, "native_executed": False}, indent=2) + "\n", encoding="utf-8")
    return (source, executable, ("d3d12.lib", "dxgi.lib", "bcrypt.lib"),
            ((sdk / "api/include").resolve(), (sdk / "denoisers/include").resolve(),
             (ROOT / "OptiScaler/include").resolve(), (ROOT / "external/nlohmann").resolve()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", type=Path, help="explicit trusted local DLL, exact capture SHA required")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="generate coherent native source; never compile/load/dispatch")
    args = parser.parse_args()
    output = args.output.resolve()
    require(not output.is_relative_to(args.capture.resolve()), "output must be outside source capture")
    replay = inspect_capture(args.capture)
    if args.inspect_only:
        output.mkdir(parents=True, exist_ok=True)
        (output / "replay-inputs.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in replay.items() if key != "frames"}, indent=2))
        return
    if args.prepare_only and args.provider is None:
        output.mkdir(parents=True, exist_ok=True)
        prepare_runner(output)
        print("SOURCE_PREPARED; compiler/native/SDK not executed")
        return
    require(args.provider is not None, "native replay requires an explicit trusted --provider")
    expected = check_provider_contract(replay)
    with frozen_provider(args.provider, expected) as provider:
        output.mkdir(parents=True, exist_ok=True)
        job = make_job(replay, provider, output)
        job_path = output / "native-replay-job.json"
        job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
        compile_args = prepare_runner(output)
        if args.prepare_only:
            print("JOB_AND_SOURCE_PREPARED; compiler/native/SDK not executed")
            return
        from fsrd_toolchain import compile_cpp
        compile_cpp(*compile_args)
        completed = subprocess.run([str(compile_args[1]), str(job_path)], text=True, capture_output=True,
                                   creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS, timeout=600)
        (output / "native.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (output / "native.stderr.log").write_text(completed.stderr, encoding="utf-8")
        completed.check_returncode()
        result = json.loads((output / "native-replay-result.json").read_text(encoding="utf-8"))
        require(result["frames"] == replay["published_frames"], "native replay did not process exact published prefix")
        require(result["provider_sha256"] == expected and result["debug_errors"] == result["sdk_errors"] == 0,
                "native replay provider/validation failed")
        (output / "replay-inputs.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
