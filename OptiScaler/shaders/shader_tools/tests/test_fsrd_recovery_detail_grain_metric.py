"""Holdout validation of the predeclared additional dark coarse-error gate."""
from pathlib import Path
import argparse
import numpy as np
from fsrd_recovery_detail_grain_metrics import score_dark, checks_dark, SPECIFICATION
from test_fsrd_recovery_detail_replay import original_gate, checked_output, save, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = checked_output(args.output)
    gate = original_gate(Path("F:/FSRD/recovery_v2/scripts/eval"))
    metric = Path(__file__).with_name("fsrd_recovery_detail_grain_metrics.py")
    before = sha256(metric)
    # Specification is saved before any holdout/candidate is evaluated.
    save(output/"specification_at_start.json", dict(**SPECIFICATION, source_sha256=before,
         historical_q13_threshold_available=False,
         provenance="Q13 quantitative failure not located in accessible report/snapshot; thresholds derive from paired-RR nonincrease"))
    h, w = 96, 128; y, x = np.indices((h, w)); frames = list(range(8))
    truth = np.full((h, w), .5, np.float32)
    reference = [dict(mean=truth, split=[truth, truth])]
    def rgb(luminance):
        return np.repeat(luminance[..., None], 3, -1)
    def score(value, target=reference):
        return score_dark(value, [frames], target, h, w, gate.blur)
    baseline = score(lambda f: rgb(truth))
    checks = []
    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))
        print(("PASS " if passed else "FAIL ")+name+" "+str(evidence), flush=True)
    check("RR identity has no false dark coarse error", all(v == 0 for scale in baseline[0]["scales"].values() for v in scale.values()))
    for size in (8, 16):
        blocks = ((x//size+y//size)%2).astype(np.float32)
        noisy = score(lambda f: rgb(truth-.08*blocks))
        check(f"persistent{size}px black block grain is rejected", not all(c["passed"] for c in checks_dark(noisy, baseline)), measured=noisy)
        alternating = score(lambda f: rgb(truth+.08*(2*(f%2)-1)*(2*blocks-1)))
        check(f"zero-mean alternating{size}px block noise cannot hide in temporal mean", not all(c["passed"] for c in checks_dark(alternating, baseline)), measured=alternating)
    structure = truth-.1*(.5+.5*np.sin(x/11)*np.cos(y/13)).astype(np.float32)
    # Raw truth follows the exact original RGB->luminance conversion. A scalar
    # fixture bypasses FP32 dot rounding and manufactures a ~1e-15 "error".
    structure_luminance = rgb(structure)@gate.LUMA
    structured_truth = [dict(mean=structure_luminance, split=[structure_luminance, structure_luminance])]
    rr = score(lambda f: rgb(truth), structured_truth)
    repaired = score(lambda f: rgb(structure), structured_truth)
    check("correct true dark structure is not classified as coarse black grain", all(c["passed"] for c in checks_dark(repaired, rr)), repaired=repaired)
    overdarker = score(lambda f: rgb(structure-.03), structured_truth)
    check("overshoot below actual dark structure is rejected", not all(c["passed"] for c in checks_dark(overdarker, rr)))
    check("metric source remained fixed after declaration", sha256(metric) == before)
    result = dict(passed=all(c["passed"] for c in checks), checks=checks, specification=SPECIFICATION,
                  source_sha256=before, gpu_executed=False, production_enabled=False)
    save(output/"results.json", result)
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
