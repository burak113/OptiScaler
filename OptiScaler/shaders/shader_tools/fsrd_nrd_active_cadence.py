"""Read-only bridge activity/cadence audit of an OptiScaler log.

Active checkpoint spacing measures CPU Consumer-recording cadence. Streamline
feature0 log spacing is reported separately, never as GPU/display/FG FPS. The
first100 aggregate hook wall totals are intentionally not summed into a frame
critical path. Runtime toggles and survey recording windows remain explicit.
"""
import argparse
import bisect
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import statistics

STAMP = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d+)\]")
ACTIVE = re.compile(r"active frames=(\d+) resets=(\d+) SL_frame=(\d+) bridge_frame=(\d+)")
RUNTIME = re.compile(r"\[NRD_BRIDGE\].*runtime=(true|false)")


def quantile(values, p):
    values = sorted(values)
    pos = (len(values) - 1) * p
    low = int(pos)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (pos - low)


def distribution(values):
    if not values:
        return {"count": 0}
    return {"count": len(values), "mean_ms": statistics.fmean(values),
            "p50_ms": quantile(values, .5), "p90_ms": quantile(values, .9),
            "p99_ms": quantile(values, .99), "min_ms": min(values), "max_ms": max(values)}


def audit(path):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    toggles, active, evaluate, contexts, surveys, perf, warnings = [], [], [], [], [], [], []
    date_wrap = 0
    last_time = -1
    last_text = ""
    header = ""
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            digest.update(raw)
            line = raw.decode("utf-8", errors="replace").rstrip()
            match = STAMP.match(line)
            if not match:
                continue
            hh, mm, ss, fraction = match.groups()
            base = int(hh) * 3600 + int(mm) * 60 + int(ss) + int(fraction) / 10 ** len(fraction)
            if last_time >= 0 and base + date_wrap < last_time - 43200:
                date_wrap += 86400
            current = base + date_wrap
            last_time, last_text = current, line
            row = dict(line=number, time=current, timestamp=match.group(0)[1:-1], text=line)
            if not header and "OptiScaler v" in line:
                header = line
            if "[NRD_BRIDGE]" in line:
                if runtime := RUNTIME.search(line):
                    toggles.append(row | {"enabled": runtime.group(1) == "true"})
                if check := ACTIVE.search(line):
                    active.append(row | dict(zip(("active_frames", "resets", "sl_frame", "bridge_frame"), map(int, check.groups()))))
                if "RR context initialized:" in line:
                    contexts.append(row)
                if "window=100_gameplay_Consumer_intervals" in line:
                    perf.append(row)
            if "hkslEvaluateFeature slEvaluateFeature: feature 0" in line:
                evaluate.append(row)
            if "[FRAME_SURVEY]" in line:
                surveys.append(row)
            if "[W]" in line or "[E]" in line:
                warnings.append(row)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("Protected log changed during read; no stable cadence result published")
    toggle_times = [v["time"] for v in toggles]
    segments = []
    for index, event in enumerate(toggles):
        end = toggles[index + 1]["time"] if index + 1 < len(toggles) else last_time
        entries = [v for v in evaluate if event["time"] <= v["time"] < end]
        deltas = [(b["time"] - a["time"]) * 1000 for a, b in zip(entries, entries[1:])]
        tail = [v for v in entries if v["time"] >= end - 20]
        tail_deltas = [(b["time"] - a["time"]) * 1000 for a, b in zip(tail, tail[1:])]
        segments.append({"runtime": event["enabled"], "start": event["timestamp"],
                         "end_seconds": end, "seconds": end - event["time"],
                         "SL_feature0_entries": len(entries), "SL_feature0_spacing": distribution(deltas),
                         "SL_feature0_last20seconds_spacing": distribution(tail_deltas),
                         "scope": "CPU entry spacing; includes loading/menu/capture/present scheduling; not FPS"})
    checkpoints = []
    for first, second in zip(active, active[1:]):
        seconds = second["time"] - first["time"]
        if seconds <= 0 or second["active_frames"] <= first["active_frames"]:
            continue
        boundaries = [first["time"]] + [t for t in toggle_times if first["time"] < t < second["time"]] + [second["time"]]
        runtime_off = 0
        for left, right in zip(boundaries, boundaries[1:]):
            index = bisect.bisect_right(toggle_times, left) - 1
            if index >= 0 and not toggles[index]["enabled"]:
                runtime_off += right - left
        frames = second["active_frames"] - first["active_frames"]
        checkpoints.append({"from": first["timestamp"], "to": second["timestamp"],
                            "active_frame_delta": frames, "SL_frame_delta": second["sl_frame"] - first["sl_frame"],
                            "seconds": seconds, "elapsed_ms_per_active_frame": seconds * 1000 / frames,
                            "active_intervals_per_elapsed_second": frames / seconds,
                            "runtime_off_seconds_inside": runtime_off,
                            "resets_delta": second["resets"] - first["resets"],
                            "survey_events_inside": [v for v in surveys if first["time"] <= v["time"] <= second["time"]],
                            "scope": "Sparse CPU Consumer checkpoint cadence; not display/GPU FPS"})
    warning_types = Counter(re.sub(r"0x[0-9a-fA-F]+|\b\d+\b", "#", row["text"].split("] ", 2)[-1]) for row in warnings)
    long_gaps = sorted(({"from": a["timestamp"], "to": b["timestamp"], "milliseconds": (b["time"] - a["time"]) * 1000}
                        for a, b in zip(evaluate, evaluate[1:])), key=lambda row: row["milliseconds"], reverse=True)[:8]
    return {"schema": "fsrd-nrd-active-log-cadence-v1", "source": str(path),
            "bytes": before.st_size, "mtime_ns": before.st_mtime_ns, "sha256": digest.hexdigest(),
            "header": header, "last_timestamp_line": last_text, "runtime_events": toggles,
            "active_checkpoints": active, "active_checkpoint_intervals": checkpoints,
            "RR_context_creation_count": len(contexts), "RR_context_creation_events": contexts,
            "survey_events": surveys, "first100_reports": perf, "runtime_segments": segments,
            "warning_count": len(warnings), "warning_types_top": warning_types.most_common(10),
            "SL_feature0_longest_gaps": long_gaps, "scope": __doc__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.drive.upper() not in ("E:", "F:") or "FSRD" not in output.parts:
        raise RuntimeError("Audit exports must remain in the FSRD artifact workspace")
    result = audit(args.log)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("bytes", "sha256", "RR_context_creation_count", "active_checkpoint_intervals", "runtime_segments")}, indent=2))


if __name__ == "__main__":
    main()
