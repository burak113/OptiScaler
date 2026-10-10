"""Independent surface DC, constant witness, current-certificate safety checks."""
from pathlib import Path
import argparse
import numpy as np
from test_fsrd_recovery_detail_replay import original_gate, checked_output, save, sha256
from test_fsrd_recovery_detail_safety import rgba
from fsrd_recovery_detail_gpu import stored
from fsrd_recovery_detail_geometry_reference import GeometryObservations, GeometryState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", choices=("geometry", "witness"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = checked_output(args.output)
    gate = original_gate(Path("F:/FSRD/recovery_v2/scripts/eval"))
    State = GeometryState
    if args.implementation == "witness":
        from fsrd_recovery_detail_surface_witness_reference import WitnessState
        State = WitnessState
    sources = [Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_geometry_reference.py"),
               Path(__file__).with_name("fsrd_recovery_detail_reference.py")]
    if args.implementation == "witness":
        sources.append(Path(__file__).with_name("fsrd_recovery_detail_surface_witness_reference.py"))
    before = {str(p): sha256(p) for p in sources}
    checks = []
    def check(name, condition, **evidence):
        checks.append(dict(name=name, passed=bool(condition), **evidence))
        print(("PASS " if condition else "FAIL ")+name+" "+str(evidence), flush=True)
        save(args.output/"progress.json", checks)
    h, w = 48, 96
    y, x = np.indices((h, w))
    base = rgba(np.full((h, w, 3), .25, np.float32))
    lobes = [rgba(np.full((h, w, 3), .125, np.float32)) for _ in range(2)]
    guides = [rgba(np.ones((h, w, 3), np.float32), 1.) for _ in range(2)]
    depth = np.full((h, w), 10., np.float32); depth[:, w//2:] = 100.
    normals = rgba(np.broadcast_to([.5, .5, 1.], (h, w, 3)).astype(np.float32), 1.)
    motion = np.zeros((h, w, 4), np.float32); motion[..., 3] = 1.
    signals = [v.copy() for v in lobes]
    signals[0][:, :w//2, :3] += .25
    signals[0][:, w//2:, :3] += .03125
    engine = State(gate, w, h)
    for _ in range(20):
        out = engine.step(signals, lobes, guides, base, depth, normals, motion)
    check("both surface-constant paired differences have no high-pass detail",
          np.array_equal(out, base), maximum=float(abs(out-base).max()))

    # Direct neutralization is checked before FP16 storage: global sum alone
    # would conceal an opposite bias transferred between disconnected regions.
    decoded = gate.decode_normals(stored(normals, 24))
    geometry = GeometryObservations(depth, decoded)
    raw = np.stack((np.sin(x/4)+.5, np.cos(y/5)-.7, np.sin((x+y)/6)+.2), -1).astype(np.float32)*.01
    mask = np.ones_like(raw, bool)
    correction, scale = geometry.neutral(raw, mask, base[..., :3])
    totals = [correction[geometry.labels == label].sum(0, dtype=np.float64)
              for label in range(geometry.count)]
    maximum = float(np.max(abs(np.asarray(totals))))
    check("DC is zero within every disconnected surface before storage", maximum <= 2e-7,
          maximum=maximum, components=geometry.count, nonnegative_scale=scale,
          tolerance=2e-7)
    tiny = np.zeros_like(mask); tiny[0, 0, :] = True; tiny[0, w-1, :] = True
    correction, _ = geometry.neutral(raw, tiny, base[..., :3])
    check("fewer than four contributors per surface and channel abstain", not np.any(correction))

    depth.fill(10.)
    signals = [v.copy() for v in lobes]
    signals[0][..., :3] += (np.sin(2*np.pi*x/18)*.0625)[..., None]
    eligibility = [np.ones((h, w), bool) for _ in range(2)]
    engine = State(gate, w, h)
    for _ in range(20):
        out = engine.step(signals, lobes, guides, base, depth, normals, motion,
                          strengths=(1., 0.), eligibility=eligibility)
    check("fixture has supported detail before current certificate withdrawal", np.any(out != base))
    eligibility[0].fill(False)
    out = engine.step(signals, lobes, guides, base, depth, normals, motion,
                      strengths=(1., 0.), eligibility=eligibility)
    check("current source or Skip certificate withdrawal immediately abstains", np.array_equal(out, base))
    eligibility[0].fill(True)
    startup = []
    for _ in range(7):
        out = engine.step(signals, lobes, guides, base, depth, normals, motion,
                          strengths=(1., 0.), eligibility=eligibility)
        startup.append(bool(np.array_equal(out, base)))
    check("certificate return restarts independent population instead of reusing stale detail", all(startup),
          first_seven_outputs_identity=startup)
    for _ in range(13):
        out = engine.step(signals, lobes, guides, base, depth, normals, motion,
                          strengths=(1., 0.), eligibility=eligibility)
    check("supported detail can return after population rematures", np.any(out != base))
    missing = [v.copy() for v in guides]; missing[0][..., 0] = 0
    out = engine.step(signals, lobes, missing, base, depth, normals, motion, strengths=(1., 0.))
    check("one-channel zero guide cannot receive correction through DC", np.array_equal(out[..., 0], base[..., 0]))
    negative = base.copy(); negative[..., :3] = -.125
    for _ in range(20):
        out = engine.step(signals, lobes, guides, negative, depth, normals, motion)
    check("unsupported negative HDR base is not clamped or increased", np.array_equal(out, negative))
    nonfinite = base.copy(); nonfinite[:, :8, 0] = np.nan; nonfinite[:, 8:16, 1] = np.inf
    out = engine.step(signals, lobes, guides, nonfinite, depth, normals, motion)
    check("nonfinite base channels preserve their input representation",
          np.all(np.isnan(out[:, :8, 0])) and np.all(np.isposinf(out[:, 8:16, 1])))
    check("finite base channels remain finite", np.all(np.isfinite(out[np.isfinite(nonfinite)])))
    after = {str(p): sha256(p) for p in sources}
    check("implementation source remained unchanged", before == after)
    result = dict(implementation=args.implementation, gpu_executed=False, production_enabled=False,
                  passed=all(c["passed"] for c in checks), checks=checks,
                  source_start=before, source_finish=after,
                  limitation="certificate input unit test; actual host routing is not certified")
    save(args.output/"results.json", result)
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
