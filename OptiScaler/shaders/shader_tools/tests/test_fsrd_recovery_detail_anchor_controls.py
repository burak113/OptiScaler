"""Targeted eligible CPU fixtures for functional anchor/mix, with counters."""
from pathlib import Path
import argparse
import numpy as np
from fsrd_recovery_detail_anchor_reference import AnchorObservations, apply_controls
from test_fsrd_recovery_detail_replay import checked_output, save, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = checked_output(args.output)
    source = Path(__file__).with_name("fsrd_recovery_detail_anchor_reference.py")
    before = sha256(source)
    h, w = 48, 96; y, x = np.indices((h, w))
    geometry = AnchorObservations(np.full((h, w), 10., np.float32),
                                 np.broadcast_to([0., 0., 1.], (h, w, 3)))
    checks = []
    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))
        print(("PASS " if passed else "FAIL ")+name+" "+str(evidence), flush=True)
    rr = np.full((h, w, 3), .25, np.float32)
    raw = np.repeat((.03*np.cos(x/5))[..., None], 3, -1).astype(np.float32)
    noise = np.full_like(raw, .01)
    off_counter, on_counter = {}, {}
    off = apply_controls(raw, rr, geometry, noise, anchor=0, mix=0, counters=off_counter)
    on = apply_controls(raw, rr, geometry, noise, anchor=4, mix=0, counters=on_counter)
    check("eligible noisy flat-RR fixture executes positive anchor and changes A/B output",
        on_counter["anchor_branch"] > 0 and on_counter["anchor_changed"] > 0 and np.any(on != off),
        off=off_counter, on=on_counter, maximum_difference=float(abs(on-off).max()))
    check("anchor-flat bound removes unsupported persistent coarse excursion", not np.any(on))
    rr = np.stack((.3+.08*np.sin(x/5), .2+.03*np.cos(y/4), .18+.04*np.sin((x+y)/8)), -1).astype(np.float32)
    high = rr-geometry.box(rr, 3)
    raw = .4*high+np.repeat((.004*np.sin((x-y)/6))[..., None], 3, -1).astype(np.float32)
    # Exercise actual positive missing-gain headroom, still above the clean
    # temporal SEM tolerance. The initial .01 noise correctly vetoed extensions
    # and cannot prove their active branches; that failed fixture is preserved.
    noise = np.full_like(raw, .002)
    off_counter, on_counter = {}, {}
    off = apply_controls(raw, rr, geometry, noise, anchor=0, mix=0, counters=off_counter)
    on = apply_controls(raw, rr, geometry, noise, anchor=0, mix=1, counters=on_counter)
    check("eligible correlated fixture executes positive mix and changes A/B output",
        on_counter["mix_branch"] > 0 and on_counter["mix_changed"] > 0 and np.any(on != off),
        off=off_counter, on=on_counter, maximum_difference=float(abs(on-off).max()))
    chroma_off = apply_controls(raw, rr, geometry, noise, anchor=0, mix=1, chroma=0)
    luma_off = apply_controls(raw, rr, geometry, noise, anchor=0, mix=1, luma=0)
    check("luma and chroma extensions are functionally routed through correlation mix",
        np.any(chroma_off != on) and np.any(luma_off != on) and on_counter["chroma_extension"] > 0 and on_counter["luma_extension"] > 0,
        chroma_difference=float(abs(chroma_off-on).max()), luma_difference=float(abs(luma_off-on).max()), counters=on_counter)
    clean_counter = {}
    clean = apply_controls(raw, rr, geometry, np.zeros_like(noise), anchor=4, mix=1, counters=clean_counter)
    check("clean temporal exception is visible and cannot be confused with disabled branches",
          clean_counter["clean_exception"] > 0 and clean_counter["anchor_branch"] == 0 and clean_counter["mix_branch"] == 0,
          counters=clean_counter, caveat="equal clean A/B output is not a global disable proof")
    check("control source remained fixed during targeted tests", sha256(source) == before)
    save(output/"results.json", dict(passed=all(c["passed"] for c in checks), checks=checks,
         source_sha256=before, gpu_executed=False, gpu_branch_counters_verified=False,
         scope="CPU control functions only; actual GPU eligible branch counters remain required"))
    return int(not all(c["passed"] for c in checks))


if __name__ == "__main__":
    raise SystemExit(main())
