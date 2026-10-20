"""Small, CPU-only comparisons. No files are written by this command."""
import argparse
import json
from pathlib import Path

import numpy as np
import colour_portable as cp


FIXTURE = Path(__file__).parent / "fixtures" / "soft2_gpu_87ee63.npz"


def differences(a, b):
    d = np.abs(np.asarray(a, np.float32) - np.asarray(b, np.float32))
    half_step = np.abs(np.spacing(np.asarray(b, np.float16))).astype(np.float32)
    half_step = np.maximum(half_step, np.float32(2 ** -24))
    return {"max_abs": float(d.max()), "p99_abs": float(np.percentile(d, 99)),
            "mean_abs": float(d.mean()), "max_half_ulp": float((d / half_step).max()),
            "different_elements": int(np.count_nonzero(d)),
            "array_equal": bool(np.array_equal(a, b))}


def fixture_comparison(path=FIXTURE):
    with np.load(path, allow_pickle=False) as f:
        model = cp.rejected_soft2_model()
        model.hist = f["prev_history"].copy()
        args = [f[k] for k in ("input_rgb", "rr_rgb", "depth", "normals_oct", "motion_px")]
        bilinear, data = model.frame(*args)
        soft2 = cp.rejected_soft2_apply(args[1], args[2], args[3], data)
        stats = np.concatenate([data["colour"], data["z"][..., None]], -1)
        packed = cp.half_rtz(cp.pack_new(cp.box(args[3], 8)))
        actual = {"expected_bilinear": bilinear, "expected_soft2": soft2,
                  "expected_history": model.hist, "expected_gain": data["g"],
                  "expected_stats": stats, "expected_packed_normal": packed}
        result = {k: differences(v, f[k]) for k, v in actual.items()}
    return {"scope": "One captured frame with CPU-warmed prior state; not chronological GPU parity.",
            "soft2_precision_note": "Original JBU guide used pre-UAV float32 RR low bits absent from rounded rr_rgb; see provenance.json.",
            "comparisons": result}


def synthetic_scene(phase, kind):
    """A known target change on the left must not tint the unchanged right."""
    width, height = 256, 128
    edge = 120 + phase
    yy, xx = np.indices((height, width))
    boundary = edge + (yy - height // 2) // 2 if kind == "diagonal" else edge
    left = xx < boundary
    raw = np.full((height, width, 3), .33, np.float32)
    target = raw.copy()
    raw[left], target[left] = [.6, .2, .2], [.5, .25, .25]
    depth = np.full((height, width), 10, np.float32)
    normals = np.full((height, width, 2), .5, np.float32)
    if kind == "depth":
        depth[~left] = 20
    if kind == "normal":
        normals[~left] = [.75, .5]
    band = (xx >= boundary) & (xx < boundary + 4)
    motion = np.zeros((height, width, 4), np.float32)
    return target, raw, depth, normals, motion, band


def edge_phase_comparison():
    rows = []
    for kind in ("same_plane", "depth", "normal", "diagonal"):
        for phase in range(8):
            target, raw, depth, normals, motion, band = synthetic_scene(phase, kind)
            baseline, _ = cp.baseline_model().frame(target, raw, depth, normals, motion)
            _, data = cp.rejected_soft2_model().frame(target, raw, depth, normals, motion)
            candidate = cp.rejected_soft2_apply(raw, depth, normals, data)
            qraw = cp.half_rtz(raw)
            def bleed(out):
                delta = np.abs(out - qraw).sum(-1) / np.maximum(cp.lum(qraw), 1e-9)
                return float(delta[band].mean())
            rows.append({"kind": kind, "phase": phase,
                         "B4_right_bleed_mean": bleed(baseline),
                         "soft2_right_bleed_mean": bleed(candidate)})
    worse = [r for r in rows if r["soft2_right_bleed_mean"] > r["B4_right_bleed_mean"] + 1e-4]
    return {"verdict": "rejected_halo_regression" if worse else "no_counterexample_in_this_fixture",
            "scope": "32 synthetic CPU cases. This is a falsification set, not a calibrated whole-game quality score.",
            "worse_cases": len(worse), "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--quality-gate", action="store_true",
                        help="Return 1 when soft2 worsens a tested edge; expected for this rejected candidate.")
    args = parser.parse_args()
    report = {"fixture": fixture_comparison(args.fixture), "edges": edge_phase_comparison()}
    print(json.dumps(report, indent=2))
    return int(args.quality_gate and report["edges"]["worse_cases"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
