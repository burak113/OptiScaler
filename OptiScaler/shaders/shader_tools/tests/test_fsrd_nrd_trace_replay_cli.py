"""Replay CLI guard tests and optional actual-provider paired replay.

The CPU guard model is explicitly synthetic metadata, never an attestation or
capture. Native mode requires --capture and an explicit trusted --provider;
it cannot turn the existing CPU/WARP capture adapter into a provider witness.
"""
from pathlib import Path
import argparse
import ast
import copy
import hashlib
import json
import math
import os
import struct
import subprocess
import sys

from fsrd_nrd_trace_replay_cli import API_VERSION, ORDER, check_provider_contract, frozen_provider, prepare_runner
from fsrd_nrd_trace_replay import inspect_capture

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--provider", type=Path)
    args = parser.parse_args()
    output = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/trace-replay-cli-prepared"))
    output.mkdir(parents=True, exist_ok=True)
    for path in (Path(__file__), HERE / "fsrd_nrd_trace_replay_cli.py", HERE / "fsrd_nrd_trace_replay.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"))
    prepare_runner(output)
    if args.prepare_only:
        print(json.dumps({"status": "SOURCE_PREPARED", "compiler_executed": False, "native_executed": False,
                          "manifest": str(output / "runner-source-manifest.json")}))
        return
    checks = []
    values = [struct.unpack("<I", struct.pack("<f", value))[0] for value in (.5, .5, 10000., 3., .5, .05, 0., 1024.)]
    # This isolated model tests admission only. It is never serialized as a capture.
    model = {"full_temporal_replay_eligible": True, "ineligibility_reasons": [], "frames": [{
        "provider": {"api_version": API_VERSION, "version_id": 1, "signal_flags": 34, "context_flags": 0,
                     "checkerboard_signal_flags": 34, "diffuse_checkerboard_origin": 0, "specular_checkerboard_origin": 1,
                     "route_attestation": {"creation": {"implementation_identity": {"disk_sha256": "a" * 64}}}},
        "actual_dispatch_flags": 3, "inputs": {name: {"source_native_resource_desc": {"flags": 4}} for name in ORDER},
        "settings": {"defaults_ready": True, "provider_defaults": values,
        "provider_effective": values, "native_debug_view": -1, "native_debug_viewport": 0}}]}
    assert check_provider_contract(model) == "a" * 64
    checks.append("CPU_model_admission_only_not_actual_provider_attestation")

    def rejected(name, mutate):
        value = copy.deepcopy(model)
        mutate(value)
        try:
            check_provider_contract(value)
        except (ValueError, KeyError):
            checks.append(name)
        else:
            raise AssertionError("invalid replay admission accepted: " + name)

    rejected("ROI_or_hidden_history_inspect_only", lambda m: m.update(full_temporal_replay_eligible=False))
    rejected("unsupported_API", lambda m: m["frames"][0]["provider"].update(api_version=0))
    rejected("AO_not_direct_diffuse", lambda m: m["frames"][0]["provider"].update(signal_flags=33))
    rejected("unknown_context_flags", lambda m: m["frames"][0]["provider"].update(context_flags=4))
    rejected("bool_not_typed_context_flags", lambda m: m["frames"][0]["provider"].update(context_flags=False))
    rejected("no_queried_defaults", lambda m: m["frames"][0]["settings"].update(defaults_ready=False))
    rejected("no_actual_input_usage_flags", lambda m: m["frames"][0]["inputs"][ORDER[0]]["source_native_resource_desc"].pop("flags"))
    rejected("no_checkerboard_snapshot", lambda m: m["frames"][0]["provider"].pop("checkerboard_signal_flags"))
    rejected("checkerboard_flags_unselected_signal", lambda m: m["frames"][0]["provider"].update(checkerboard_signal_flags=1))
    rejected("checkerboard_origin_out_of_range", lambda m: m["frames"][0]["provider"].update(specular_checkerboard_origin=2))
    rejected("unknown_dispatch_flags", lambda m: m["frames"][0].update(actual_dispatch_flags=4))
    rejected("nonfinite_effective_setting", lambda m: m["frames"][0]["settings"]["provider_effective"].__setitem__(0, 0x7fc00000))
    rejected("debug_packet_without_debug_context", lambda m: m["frames"][0]["settings"].update(native_debug_view=0))
    rejected("context_without_debug_packet", lambda m: m["frames"][0]["provider"].update(context_flags=1))
    rejected("bool_not_typed_debug_mode", lambda m: m["frames"][0]["settings"].update(native_debug_view=False))
    drift = copy.deepcopy(model)
    drift["frames"].append(copy.deepcopy(drift["frames"][0]))
    drift["frames"][1]["provider"]["checkerboard_signal_flags"] = 0
    try:
        check_provider_contract(drift)
    except ValueError:
        checks.append("context_create_controls_stable")
    else:
        raise AssertionError("create drift accepted")
    dummy = output / "guard-only-not-a-provider.dll"
    dummy.write_bytes(b"Explicit CPU freeze/hash test only; not an executable provider.\n")
    actual_sha = hashlib.sha256(dummy.read_bytes()).hexdigest()
    try:
        with frozen_provider(dummy, "0" * 64):
            raise AssertionError("wrong DLL hash accepted")
    except ValueError:
        checks.append("wrong_hash_rejected_without_LoadLibrary_or_compiler")
    with frozen_provider(dummy, actual_sha) as frozen:
        assert frozen == dummy.resolve()
        try:
            with dummy.open("wb"):
                pass
        except PermissionError:
            checks.append("provider_handle_denies_write_while_frozen")
        else:
            raise AssertionError("frozen provider remained writable")
    dummy.write_bytes(b"CPU dummy handle was released.\n")
    checks.append("provider_handle_released_after_scope")
    result = {"status": "PASS", "cpu_checks": len(checks), "cases": checks,
              "actual_sdk_dispatches": 0, "scope": "CPU guard models/file freeze only; no capture or provider witness fabricated"}
    if args.capture is not None or args.provider is not None:
        assert args.capture is not None and args.provider is not None, "native mode needs both explicit capture/provider"
        replay = inspect_capture(args.capture)
        expected = check_provider_contract(replay)
        # Predeclared equivalence diagnostic for this same-provider test only.
        # The CLI itself reports metrics without imposing an image-quality verdict.
        native_output = output / "actual-provider"
        command = [sys.executable, str(HERE / "fsrd_nrd_trace_replay_cli.py"), str(args.capture),
                   "--provider", str(args.provider), "--output", str(native_output)]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=660,
                                   creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        (output / "cli.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (output / "cli.stderr.log").write_text(completed.stderr, encoding="utf-8")
        completed.check_returncode()
        native = json.loads((native_output / "native-replay-result.json").read_text(encoding="utf-8"))
        assert native["frames"] == native["actual_sdk_dispatches"] == replay["published_frames"]
        assert native["provider_sha256"] == expected
        assert native["debug_errors"] == native["debug_warnings"] == native["sdk_errors"] == 0
        metrics = [json.loads(line) for line in (native_output / "raw-rr-comparison.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(metrics) == replay["published_frames"]
        for index, frame in enumerate(metrics):
            assert frame["ordinal"] == index
            for lobe in ("specular", "diffuse"):
                row = frame[lobe]
                assert row["nonfinite_pixels"] == 0
                assert math.isfinite(row["rgb_normalized_rmse"]) and row["rgb_normalized_rmse"] <= .02
                if index == 0:
                    assert row["same_pixel_error_delta_rmse"] is None
                else:
                    assert math.isfinite(row["same_pixel_error_delta_rmse"])
        result["actual_replay"] = native
        result["actual_sdk_dispatches"] = native["actual_sdk_dispatches"]
        result["native_scope"] = "same-provider raw-RR observation equivalence;2%normalizedRMSE diagnostic predeclared; not clean truth/game quality"
    (output / "replay-cli-test-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
