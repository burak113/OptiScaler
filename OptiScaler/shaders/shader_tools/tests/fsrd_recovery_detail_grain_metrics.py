"""Predeclared additional coarse black-grain gate, independent of M3.

For each unchanged static run, use its raw-color temporal-mean luminance truth.
At approximate 8px/16px footprints (9x9/17x17 odd boxes, radii4/8), measure
the negative low-pass error max(box(truth)-box(output_frame),0). Average its
level-normalized squared energy and its99th-percentile squared error over
frames. BOTH values at BOTH scales must not exceed the paired RR-only values.
No post-candidate tolerance or threshold tuning is allowed. This supplements
the original four strict band improvements and LF<=1.10, never replaces them.
Real dark structure in truth has zero false-dark error at the correct output.
"""
import numpy as np

LUMA = np.array([.2126, .7152, .0722], np.float32)
RADII = (4, 8)
SPECIFICATION = dict(scales={"8px": 4, "16px": 8}, actual_odd_footprints=[9, 17],
    fields=["mean_negative_error_squared", "p99_negative_error_squared"],
    threshold="each value <= same raw-truth/paired-RR value; no multiplicative or additive tolerance",
    reference="unchanged static-run unclipped raw temporal mean",
    scope="per-frame artifacts, not just the temporal mean",
    original_m3_criteria_changed=False)


def score_dark(get_frame, runs, truth, h, w, blur):
    margin = min(16, h//8, w//8)
    crop = (slice(margin, h-margin), slice(margin, w-margin))
    result = []
    for frames, reference in zip(runs, truth):
        target = np.asarray(reference["mean"], np.float32)
        level = max(float(target[crop].mean()), 1e-6)
        targets = {radius: blur(target, radius) for radius in RADII}
        totals = {radius: np.zeros(2, np.float64) for radius in RADII}
        for frame in frames:
            luminance = np.asarray(get_frame(frame), np.float32)[..., :3]@LUMA
            for radius in RADII:
                error = np.maximum(targets[radius]-blur(luminance, radius), 0)[crop].astype(np.float64)/level
                energy = error*error
                totals[radius] += [energy.mean(), np.quantile(energy, .99, method="linear")]
        result.append(dict(frames=[frames[0], frames[-1]],
            scales={label: dict(mean_negative_error_squared=float(totals[radius][0]/len(frames)),
                                p99_negative_error_squared=float(totals[radius][1]/len(frames)))
                    for label, radius in (("8px", 4), ("16px", 8))}))
    return result


def checks_dark(measured, baseline):
    if len(measured) != len(baseline):
        raise ValueError("Static run count changed")
    rows = []
    for candidate, rr in zip(measured, baseline):
        if candidate["frames"] != rr["frames"]:
            raise ValueError("Static frame ranges changed")
        checks = {scale: {field: candidate["scales"][scale][field] <= rr["scales"][scale][field]
                          for field in SPECIFICATION["fields"]}
                  for scale in SPECIFICATION["scales"]}
        rows.append(dict(frames=candidate["frames"], passed=all(all(v.values()) for v in checks.values()),
                         checks=checks))
    return rows
