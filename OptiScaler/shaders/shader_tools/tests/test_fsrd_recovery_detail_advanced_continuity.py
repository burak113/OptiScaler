"""Independent tiny-candidate RR-spike continuity safety diagnostic.

The parent's frozen negative report distinguishes large opposite-direction
anchor damage from ordinary RR+raw-RR FP32 cancellation at0/0. This test does
not relabel the original reports. It checks exact pre-neutralization ray bounds
on the new model, then verifies vanishing stored changes after surface DC.
"""
from pathlib import Path
import argparse
import itertools
import numpy as np
from fsrd_recovery_detail_advanced_reference import AnchorObservations, apply_controls
from test_fsrd_recovery_detail_replay import checked_output, save, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control-model", choices=("ray", "advanced"), default="advanced")
    args = parser.parse_args()
    output = checked_output(args.output)
    paths = [Path(__file__), Path(__file__).with_name("fsrd_recovery_detail_advanced_reference.py"),
             Path(__file__).with_name("fsrd_recovery_detail_anchor_reference.py")]
    before = {str(p): sha256(p) for p in paths}
    h = w = 33
    y, x = np.indices((h, w))
    rr = np.full((h, w, 3), .1, np.float16).astype(np.float32)
    rr[h//2, w//2] = 1.
    geometry = AnchorObservations(np.full((h, w), 10., np.float32),
                                 np.broadcast_to([0., 0., 1.], (h, w, 3)))
    pattern = np.repeat(np.cos(x/5)[..., None], 3, -1).astype(np.float32)
    noise = np.full_like(rr, .001)
    rows = []
    for epsilon, anchor, mix in itertools.product((0., 2**-24, 2**-20, 2**-16, .01), (0., 4.), (0., .5, 1.)):
        raw = (epsilon*pattern).astype(np.float32)
        counter = {}
        controlled = apply_controls(raw, rr, geometry, noise, anchor, mix,
                                    counters=counter, control_model=args.control_model)
        same_ray = bool(np.all(controlled*raw >= 0))
        bounded = bool(np.all(abs(controlled) <= abs(raw)))
        zero_exact = epsilon != 0 or not np.any(controlled)
        neutral, scale = geometry.neutral(controlled, controlled != 0, rr)
        stored = (rr+neutral).astype(np.float16).astype(np.float32)
        maximum_raw = float(abs(raw).max())
        # Subtracting the same-surface mean has infinity norm<=2*max(raw).
        # A conservative FP32 rounding-sum allowance covers the one-pivot DC
        # projection without turning the pre-DC exact ray bound into a tolerance.
        post_dc_bound = 2*maximum_raw+2*h*w*float(np.spacing(np.float32(2*maximum_raw)))
        post_dc_continuous = bool(float(abs(neutral).max()) <= post_dc_bound)
        # FP16 storage can quantize a legitimate tiny transfer. At<=2^-20 the
        # two-times raw range and rounding residue remain below half the .1 ULP.
        stored_identity = epsilon > 2**-20 or np.array_equal(stored, rr)
        dc = np.bincount(geometry.labels.ravel(), weights=neutral[..., 0].ravel(), minlength=geometry.count)
        rows.append(dict(epsilon=epsilon, anchor=anchor, mix=mix,
            maximum_raw=maximum_raw, maximum_controlled=float(abs(controlled).max()),
            spike_controlled=controlled[h//2, w//2].tolist(), same_signed_ray=same_ray,
            nonexpansive=bounded, zero_exact=zero_exact, vanishing_stored_identity=stored_identity,
            maximum_stored_change=float(abs(stored-rr).max()), scale=scale,
            maximum_post_dc_correction=float(abs(neutral).max()), spike_post_dc=neutral[h//2, w//2].tolist(),
            post_dc_continuity_bound=post_dc_bound, post_dc_continuous=post_dc_continuous,
            per_surface_dc=float(abs(dc).max()), dc_bound=float(abs(dc).max()) <= 2e-7,
            counters=counter, passed=same_ray and bounded and zero_exact and stored_identity and
                                    post_dc_continuous and float(abs(dc).max()) <= 2e-7))
    after = {str(p): sha256(p) for p in paths}
    result = dict(passed=all(r["passed"] for r in rows) and before == after,
        records=rows, record_count=len(rows), control_model=args.control_model,
        source_start=before, source_finish=after, gpu_executed=False,
        frozen_negative_reference="tools_tmp/team_20261010/control_continuity/results.json",
        distinction="old0/0 FP32 cancellation is separate; new ray projection guarantees exact candidate direction/range before DC",
        original_m3_criteria_changed=False)
    save(output/"results.json", result)
    print("PASS" if result["passed"] else "FAIL", args.control_model, len(rows), flush=True)
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
