"""Run offline, or add --trace-root for independent original-source bit checks."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from clip_loader import load_clip, previous_coordinates, sample_previous, array_sha
from export_clips import FIELDS


def speed_mask(mv, render_extent):
    from numpy.lib.stride_tricks import sliding_window_view
    m = mv.astype(np.float32)
    speed = np.hypot(m[..., 0] * int(render_extent[0]), m[..., 1] * int(render_extent[1])) > 12
    return sliding_window_view(np.pad(speed, 2, constant_values=False), (5, 5)).all((-1, -2))


def test_synthetic_coordinates():
    # A changing crop origin must be included even when the physical motion cancels it.
    a = {"input_motion": np.zeros((2, 5, 5, 4), np.float64), "crop_origin_render": np.array([[10, 20], [12, 21]]), "render_extent": np.array([100, 100])}
    a["input_motion"][1, ..., :2] = [-.02, -.01]
    qx, qy, ok = previous_coordinates(a, 1)
    yy, xx = np.mgrid[:5, :5]
    assert np.allclose(qx, xx) and np.allclose(qy, yy)
    ramp = yy * 10 + xx
    result, valid = sample_previous(ramp, qx, qy)
    assert np.allclose(result[valid], ramp[valid])
    assert np.isnan(result[~valid]).all() and valid.sum() == 16
    try:
        previous_coordinates(a, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("First partial frame incorrectly had history")


def test_one(npz, trace_root=None):
    a, meta = load_clip(npz)
    n = len(meta["source_frame_indices"])
    w, h = meta["crop_extent"]
    assert np.array_equal(a["frame_indices"], meta["source_frame_indices"])
    assert np.all(np.diff(a["frame_indices"]) == 1)
    assert meta["partial_history"] and meta["no_frame_looping"] and not meta["ground_truth"]
    assert a["provider_controls"].shape == (n, 46) and a["provider_controls"].dtype == np.dtype("<u4")
    assert a["crop_origin_render"].shape == (n, 2)
    assert np.array_equal(a["crop_origin_render"], a["crop_origin_source"] + a["source_roi_origin"])
    for field, (dtype, channels) in FIELDS.items():
        assert a[field].dtype == np.dtype(dtype)
        assert a[field].shape == ((n, h, w, channels) if channels > 1 else (n, h, w))
    assert a["view_u32"].shape == (n, 4, 4) and a["projection_u32"].shape == (n, 4, 4)
    for key in ("view_u32", "projection_u32", "camera_position_u32", "previous_camera_position_u32"):
        assert np.isfinite(a[key].view("<f4")).all()
    result = {"fixture": meta["fixture_id"], "offline_hash_dtype_shape_finite": "PASS", "source_bit_checks": 0, "bottle_motion_support": []}
    for k in range(1, n):
        qx, qy, ok = previous_coordinates(a, k)
        if meta["fixture_id"] == "bottle_track7":
            mask = speed_mask(a["input_motion"][k], a["render_extent"])
            assert mask.any() and ok[mask].all()
            result["bottle_motion_support"].append({"frame": int(a["frame_indices"][k]), "pixels": int(mask.sum()), "prior_inside_track_fraction": float(ok[mask].mean())})
    # Ensure published JSON contains relative source filenames, never host absolute paths.
    for row in meta["source_files"]:
        p = Path(row["relative_file"])
        assert not p.is_absolute() and ":" not in row["relative_file"] and ".." not in p.parts
    if trace_root is not None:
        source = trace_root / meta["source_capture_uuid"]
        payload = (source / "capture.json").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == meta["source_capture_manifest_sha256"]
        manifest = json.loads(payload)
        sw, sh = meta["source_roi_extent"]
        frame_lookup = {int(t): k for k, t in enumerate(a["frame_indices"])}
        aggregate = hashlib.sha256()
        import struct
        for row in meta["source_files"]:
            payload = (source / row["relative_file"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == row["source_file_sha256"]
            aggregate.update(row["relative_file"].encode("utf-8") + b"\0")
            aggregate.update(struct.pack("<Q", len(payload)))
            aggregate.update(payload)
            k, field = frame_lookup[row["frame_index"]], row["field"]
            if field == "provider_controls":
                crop = np.frombuffer(payload, "<u4")
            else:
                dtype, channels = FIELDS[field]
                shape = (sh, sw, channels) if channels > 1 else (sh, sw)
                full = np.frombuffer(payload, dtype).reshape(shape)
                x0, y0, x1, y1 = row["crop_local_xyxy"]
                crop = full[y0:y1, x0:x1]
                if field == "input_motion" and meta["fixture_id"] == "bottle_track7":
                    full_mask = speed_mask(full, a["render_extent"])
                    assert full_mask[y0:y1, x0:x1].sum() == full_mask.sum()
            assert array_sha(crop) == row["crop_raw_sha256"]
            # Compare bytes, not float equality: preserves signed zero and all FP16 words.
            assert crop.tobytes(order="C") == a[field][k].tobytes(order="C")
            result["source_bit_checks"] += 1
        assert aggregate.hexdigest() == meta["source_input_sha256"]
        for k, t in enumerate(a["frame_indices"]):
            fp = manifest["frames"][int(t)]["frame_parameters"]
            for key, expected in (("view_u32", fp["camera"]["view"]), ("projection_u32", fp["camera"]["projection"]), ("camera_position_u32", fp["camera_position"]), ("previous_camera_position_u32", fp["previous_camera_position"])):
                assert np.asarray(expected, dtype="<u4").tobytes() == a[key][k].tobytes()
                result["source_bit_checks"] += 1
        result["source_aggregate_and_manifest"] = "PASS"
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--trace-root", type=Path)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    test_synthetic_coordinates()
    rows = [test_one(args.directory / (name + ".npz"), args.trace_root) for name in ("bottle_track7", "foliage23", "facade16")]
    summary = {"pass": True, "synthetic_origin_and_invalid_border": "PASS", "fixtures": rows, "npz_bytes": sum(p.stat().st_size for p in args.directory.glob("*.npz")), "source_access_required_offline": False}
    if args.report:
        args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
