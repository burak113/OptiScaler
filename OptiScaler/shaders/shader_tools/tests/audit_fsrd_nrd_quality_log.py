"""Read-only, streaming NRD quality-log evidence; no replay or GPU work.

Present intervals include the application and hook work. They are not GPU pass
timings or a controlled image-quality comparison. Unknown startup runtime state
is kept separate from explicit runtime ON/OFF intervals.
"""
import argparse
import ctypes
import json
import re
from pathlib import Path
from collections import deque


def stats(values):
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {"count": len(values), "mean_ms": sum(values) / len(values),
            "p50_ms": ordered[len(values) // 2],
            "p95_ms": ordered[min(len(values) - 1, int(len(values) * .95))]}


def run(path):
    timestamp = re.compile(r"^\[(\d\d):(\d\d):(\d\d\.\d+)\]")
    active = re.compile(r"active frames=(\d+) resets=(\d+) SL_frame=(\d+) bridge_frame=(\d+)")
    runtime = re.compile(r"\[NRD_BRIDGE\] runtime=(true|false)")
    fg_interval = re.compile(r"FGHooks::FGPresent flags:.*?Frametime: ([\d.]+)")
    local_interval = re.compile(r"LocalPresent SyncInterval:.*?Frametime: ([\d.]+) ms")
    counts = {"lines": 0, "runtime_on": 0, "runtime_off": 0,
              "discovery_complete": 0, "resource_release_invalidation": 0,
              "active_samples": 0, "trace_lines": 0,
              "restore_trace_lines": 0, "restore_argument_warning_lines": 0,
              "survey_recordings_started": 0, "inspector_snapshot_lines": 0}
    segments = []
    current = {"runtime": None, "start_seconds": None, "fg_ms": [], "local_ms": []}
    samples, conventions, performance, events = [], [], [], []
    last_time = None
    flow = deque(maxlen=12)
    flow_windows = []
    evaluation_frame = None
    flow_counts = {"sr_evaluate_lines": 0, "native_queue_hook_lines": 0,
                   "queue_list_identity_lines": 0, "fence_publish_lines": 0}
    sl_evaluation = re.compile(r"hkslEvaluateFeature frameIndex: (\d+)")
    sr_evaluation = re.compile(r"NVSDK_NGX_D3D12_EvaluateFeature EvaluateFeature.*CmdList: (0x[0-9a-fA-F]+)")
    root_restore = re.compile(r"D3D12Hooks::RestoreRoot Restored PipelineState for CmdList: ([0-9a-fA-F]+)")
    with path.open(encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            counts["lines"] += 1
            counts["trace_lines"] += " [T] " in line
            counts["restore_trace_lines"] += " [T] " in line and "D3D12Hooks::Restore" in line
            counts["restore_argument_warning_lines"] += " [W] " in line and "D3D12Hooks::Restore" in line and "Can't restore index" in line
            counts["survey_recordings_started"] += "[FRAME_SURVEY] started at Present" in line
            counts["inspector_snapshot_lines"] += "[RR_RESOURCE_CANDIDATE] snapshot" in line or "[RR_RESOURCE_INVENTORY]" in line
            match = timestamp.match(line)
            if not match:
                continue
            seconds = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
            last_time = seconds
            flow_counts["native_queue_hook_lines"] += "ResTrack_Dx12::hkExecuteCommandLists" in line
            flow_counts["queue_list_identity_lines"] += "ppCommandLists[" in line
            flow_counts["fence_publish_lines"] += any(text in line for text in ("FencePublished", "fencePublished", "signalPublished"))
            match = sl_evaluation.search(line)
            if match:
                evaluation_frame = int(match[1])
            match = sr_evaluation.search(line)
            event = None
            if match:
                flow_counts["sr_evaluate_lines"] += 1
                event = {"line": number, "seconds": seconds, "kind": "sr_evaluate",
                         "latest_sl_evaluation_frame": evaluation_frame, "command_list": match[1].lower()}
            match = root_restore.search(line)
            if match:
                event = {"line": number, "seconds": seconds, "kind": "root_restore_complete",
                         "latest_sl_evaluation_frame": evaluation_frame, "command_list": "0x" + match[1].lower()}
            if event:
                for window in flow_windows:
                    if len(window["following_markers"]) < 8:
                        window["following_markers"].append(event)
                flow.append(event)
            if current["start_seconds"] is None:
                current["start_seconds"] = seconds
            match = runtime.search(line)
            if match:
                current["end_seconds"] = seconds
                segments.append(current)
                enabled = match[1] == "true"
                counts["runtime_on" if enabled else "runtime_off"] += 1
                events.append({"kind": "runtime_on" if enabled else "runtime_off", "seconds": seconds})
                current = {"runtime": enabled, "start_seconds": seconds, "fg_ms": [], "local_ms": []}
            for expression, key in ((fg_interval, "fg_ms"), (local_interval, "local_ms")):
                match = expression.search(line)
                if match:
                    current[key].append(float(match[1]))
            if "[NRD_BRIDGE]" not in line:
                continue
            counts["discovery_complete"] += "discovery complete" in line
            if "discovery complete" in line:
                events.append({"kind": "discovery", "seconds": seconds})
            counts["resource_release_invalidation"] += "resource release invalidated discovery" in line
            match = active.search(line)
            if match:
                counts["active_samples"] += 1
                flow_windows.append({"active_line": number, "active_seconds": seconds,
                                     "active_SL_frame": int(match[3]),
                                     "preceding_markers": list(flow), "following_markers": []})
                samples.append({"line": number, "timestamp": line[1:line.index("]")],
                                "seconds": seconds,
                                "active_frames": int(match[1]), "resets": int(match[2]),
                                "SL_frame": int(match[3]), "bridge_frame": int(match[4])})
            if "SL conventions:" in line:
                conventions.append({"line": number, "text": line.strip()})
            if "perf frames=" in line:
                performance.append({"line": number, "text": line.strip()})
    current["end_seconds"] = last_time
    segments.append(current)
    summaries = []
    reset_intervals = []
    previous_seconds, previous_resets = -1, 0
    for sample in samples:
        between = [event for event in events if previous_seconds < event["seconds"] <= sample["seconds"]]
        reset_intervals.append({"through_active_frame": sample["active_frames"],
                               "observed_reset_increment": sample["resets"] - previous_resets,
                               "explicit_runtime_on_events": sum(event["kind"] == "runtime_on" for event in between),
                               "discovery_events": sum(event["kind"] == "discovery" for event in between)})
        previous_seconds, previous_resets = sample["seconds"], sample["resets"]
    grouped = {False: {"fg_ms": [], "local_ms": []}, True: {"fg_ms": [], "local_ms": []}}
    for segment in segments:
        duration = segment["end_seconds"] - segment["start_seconds"]
        summaries.append({"runtime": segment["runtime"], "duration_s": duration,
                          "fg_present": stats(segment["fg_ms"]), "local_present": stats(segment["local_ms"])})
        # Short switching intervals and unknown startup state are not pooled.
        if segment["runtime"] is not None and duration >= 2:
            for key in ("fg_ms", "local_ms"):
                grouped[segment["runtime"]][key].extend(segment[key])
    return {"source": str(path), "counts": counts, "active_samples": samples,
            "sampled_reset_intervals": reset_intervals,
            "conventions": conventions, "performance": performance,
            "command_flow": {"counts": flow_counts, "active_windows": flow_windows,
                             "limits": "Active has no command/queue/submission identity; log lines have no unique thread pairing. Adjacent root restores are source-list candidates, and latest SL evaluation frame is a chronological marker, not proof of camera/CB6 or GPU-frame association."},
            "segments": summaries,
            "pooled_explicit_segments_at_least_2s": {
                "on": {key: stats(value) for key, value in grouped[True].items()},
                "off": {key: stats(value) for key, value in grouped[False].items()}},
            "limits": "observed inclusive Present intervals; no scene/camera matching, GPU timestamps or quality verdict"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(ctypes.windll.kernel32.GetCurrentProcess()), 0x4000)
    result = run(args.log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("counts", "sampled_reset_intervals", "pooled_explicit_segments_at_least_2s")}, indent=2))
