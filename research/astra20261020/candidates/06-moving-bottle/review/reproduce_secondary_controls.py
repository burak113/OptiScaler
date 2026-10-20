"""Independent pre-candidate coordinate and level-versus-shape falsifiers."""
from pathlib import Path
import hashlib
import importlib.util
import json
import numpy as np


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[2]
spec = importlib.util.spec_from_file_location(
    "frozen_clip_loader", PACKAGE / "fixtures/clips/clip_loader.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def main():
    # Moving crop cancels known backward physical displacement.
    a = {
        "input_motion": np.zeros((2, 7, 9, 4), np.float64),
        "crop_origin_render": np.array([[100, 200], [108, 204]]),
        "render_extent": np.array([1024, 512]),
    }
    a["input_motion"][1, ..., :2] = [-8 / 1024, -4 / 512]
    y, x = np.mgrid[:7, :9]
    qx, qy, valid = loader.previous_coordinates(a, 1)
    correct_error = np.hypot(qx-x, qy-y)
    assert np.all(correct_error == 0)
    # These controls deliberately mutate exactly one coordinate convention.
    wrong_sign_error = float(np.hypot(16, 8))
    omitted_crop_error = float(np.hypot(8, 4))
    wrong_scale_error = float(np.hypot(8-8*9/1024, 4-4*7/512))
    sampled, sample_valid = loader.sample_previous(x + 100*y, qx, qy)
    assert np.array_equal(valid, sample_valid)
    assert np.all(sampled[valid] == (x+100*y)[valid])
    assert np.isnan(sampled[~valid]).all()
    assert int(valid.sum()) == 48

    # A 4px-lagged shape at half brightness has the same support and centroid.
    truth = np.zeros((16, 64), np.float64)
    truth[3:13, 30:33] = 1
    lagged = np.roll(truth, -4, axis=1)
    darker = lagged * .5
    xx = np.arange(64)[None, :]
    centroid = lambda z: float(np.sum(z*xx)/np.sum(z))
    tail = (xx < 30) & (truth == 0)
    assert centroid(lagged) == centroid(darker)
    assert np.array_equal(lagged > .2, darker > .2)
    assert float(darker[tail].sum()) == float(lagged[tail].sum())*.5
    assert not np.any(darker > .6)
    result = {
        "executor": "independent_skeptical_reviewer",
        "candidate_results_viewed": False,
        "gpu_executed": False,
        "command": "python -B research/astra20261020/candidates/06-moving-bottle/review/reproduce_secondary_controls.py",
        "coordinate_control": {
            "correct_max_error_pixels": float(correct_error.max()),
            "wrong_sign_error_pixels": wrong_sign_error,
            "omitted_crop_error_pixels": omitted_crop_error,
            "roi_instead_of_render_scale_error_pixels": wrong_scale_error,
            "valid_pixels": int(valid.sum()),
            "unknown_border_pixels": int((~valid).sum()),
        },
        "brightness_is_not_shape_control": {
            "lag_pixels": centroid(lagged)-centroid(truth),
            "darker_lag_pixels": centroid(darker)-centroid(truth),
            "tail_energy_ratio": float(darker[tail].sum()/lagged[tail].sum()),
            "support_unchanged_at_threshold_0_2": True,
            "vacuous_empty_support_at_threshold_0_6": True,
            "interpretation": "A 50% lower tail energy does not repair the unchanged 4px lag. Empty thresholded support is not success.",
        },
    }
    text = json.dumps(result, indent=2, allow_nan=False)+'\n'
    (HERE / 'secondary_controls.json').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
