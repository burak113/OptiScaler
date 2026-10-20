"""Lossless chronological CPU fixtures. Requires only Python stdlib and NumPy.

Run: python export_clips.py --trace-root /path/to/GAME_TRACE --out ./clips
Never invokes RR, a GPU, the game, or any shared analysis library.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import numpy as np

FIELDS = {
    "input_depth": ("<f4", 1),
    "input_motion": ("<f2", 4),
    "input_normal_roughness": ("<u4", 1),
    "recovery_original_normal_roughness": ("<u4", 1),
    "input_diffuse": ("<f2", 4),
    "input_specular": ("<f2", 4),
    "raw_rr_diffuse": ("<f2", 4),
    "raw_rr_specular": ("<f2", 4),
    "selected_rr_diffuse": ("<f2", 4),
    "selected_rr_specular": ("<f2", 4),
}
SPECS = {
    "bottle_track7": {"prefix": "2405579e", "frames": list(range(180, 187)), "y0": [160, 176, 208, 272, 384, 480, 560], "x0": 0, "width": 128, "height": 256},
    "foliage23": {"prefix": "87ee1fba", "frames": list(range(43, 66)), "y0": [256] * 23, "x0": 256, "width": 192, "height": 64},
    "facade16": {"prefix": "f2ef375f", "frames": list(range(34, 50)), "y0": [192] * 16, "x0": 192, "width": 96, "height": 96},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def array_sha(a):
    return sha(np.ascontiguousarray(a).tobytes(order="C"))


def safe_relative(name):
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or ":" in str(p):
        raise ValueError("Source filename is not a portable relative path")
    return str(p)


def export_one(trace_root, out, fixture_id, spec, overwrite=False):
    candidates = sorted(p for p in trace_root.glob(spec["prefix"] + "*") if (p / "capture.json").is_file())
    if len(candidates) != 1:
        raise ValueError("Expected one capture for " + spec["prefix"])
    source = candidates[0]
    manifest_bytes = (source / "capture.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    frames = spec["frames"]
    published = int(manifest["manifest_published_frames"])
    if not frames or max(frames) >= published or any(b != a + 1 for a, b in zip(frames, frames[1:])):
        raise ValueError("Fixture must contain consecutive published frames")
    sw, sh = manifest["roi"]["extent"]
    sx, sy = manifest["roi"]["origin"]
    n, w, h = len(frames), spec["width"], spec["height"]
    local_origins = np.array([[spec["x0"], y] for y in spec["y0"]], dtype="<i4")
    global_origins = local_origins + np.array([sx, sy], dtype="<i4")
    if (local_origins < 0).any() or (local_origins[:, 0] + w > sw).any() or (local_origins[:, 1] + h > sh).any():
        raise ValueError("Crop is outside the saved source ROI")
    npz_path, meta_path = out / (fixture_id + ".npz"), out / (fixture_id + ".json")
    if not overwrite and (npz_path.exists() or meta_path.exists()):
        raise FileExistsError("Fixture already exists: " + fixture_id)
    arrays, provenance = {}, []
    selected_source_hash = hashlib.sha256()

    def attest(relative, payload):
        selected_source_hash.update(relative.encode("utf-8") + b"\0")
        selected_source_hash.update(struct.pack("<Q", len(payload)))
        selected_source_hash.update(payload)

    for field, (dtype, channels) in FIELDS.items():
        crops = []
        for k, t in enumerate(frames):
            im = next(x for x in manifest["frames"][t]["images"] if x["name"] == field)
            relative = safe_relative(im["file"])
            payload = (source / relative).read_bytes()
            expected_bytes = sw * sh * np.dtype(dtype).itemsize * channels
            if len(payload) != expected_bytes:
                raise ValueError("Unexpected tight-array size: " + relative)
            source_hash = sha(payload)
            if im.get("sha256") and im["sha256"] != source_hash:
                raise ValueError("Source does not match capture manifest: " + relative)
            attest(relative, payload)
            shape = (sh, sw, channels) if channels > 1 else (sh, sw)
            full = np.frombuffer(payload, dtype=dtype).reshape(shape)
            x, y = map(int, local_origins[k])
            crop = full[y:y + h, x:x + w].copy(order="C")
            if np.issubdtype(crop.dtype, np.floating) and not np.isfinite(crop).all():
                raise ValueError("Nonfinite original source crop: " + relative)
            crops.append(crop)
            provenance.append({"field": field, "frame_index": t, "relative_file": relative, "source_file_bytes": len(payload), "source_file_sha256": source_hash, "crop_local_xyxy": [x, y, x + w, y + h], "crop_raw_sha256": array_sha(crop)})
        arrays[field] = np.stack(crops)

    controls = []
    for t in frames:
        relative = "frames/%d/provider_controls.bin" % t
        payload = (source / relative).read_bytes()
        if len(payload) != 46 * 4:
            raise ValueError("Unexpected controls ABI")
        attest(relative, payload)
        controls.append(np.frombuffer(payload, "<u4").copy())
        provenance.append({"field": "provider_controls", "frame_index": t, "relative_file": relative, "source_file_bytes": len(payload), "source_file_sha256": sha(payload), "crop_raw_sha256": sha(payload)})
    arrays.update(provider_controls=np.stack(controls), frame_indices=np.array(frames, dtype="<i4"), crop_origin_render=global_origins, crop_origin_source=local_origins, source_roi_origin=np.array([sx, sy], dtype="<i4"), source_roi_extent=np.array([sw, sh], dtype="<i4"), render_extent=np.array(manifest["render_extent"], dtype="<i4"))
    fps = [manifest["frames"][t]["frame_parameters"] for t in frames]
    arrays["view_u32"] = np.array([f["camera"]["view"] for f in fps], dtype="<u4").reshape(n, 4, 4)
    arrays["projection_u32"] = np.array([f["camera"]["projection"] for f in fps], dtype="<u4").reshape(n, 4, 4)
    arrays["camera_position_u32"] = np.array([f["camera_position"] for f in fps], dtype="<u4")
    arrays["previous_camera_position_u32"] = np.array([f["previous_camera_position"] for f in fps], dtype="<u4")
    descriptors = {key: {"dtype": a.dtype.str, "shape": list(a.shape), "raw_sha256": array_sha(a), "raw_bytes": a.nbytes} for key, a in arrays.items()}
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz_path, **arrays)
    meta = {
        "schema": "fsrd.cpu_chronological_clip.v1", "fixture_id": fixture_id,
        "source_capture_uuid": source.name, "source_capture_manifest_sha256": sha(manifest_bytes),
        "source_published_frames": published, "source_frame_indices": frames,
        "source_input_sha256": selected_source_hash.hexdigest(),
        "source_input_sha256_scheme": "FIELDS insertion order, then chronological frame; then chronological controls. For each full source file: UTF8(relative filename)+NUL, uint64 little-endian byte length, original file bytes. Includes source pixels outside the exported crop; does not claim a whole-capture input hash.",
        "source_hash_scope": "Every exported source file was hashed in full and checked against its capture image hash when available. Exact crop byte hashes are also stored. Camera word arrays are attested by the capture manifest hash.",
        "arrays": descriptors, "source_files": provenance,
        "archive": {"file": npz_path.name, "bytes": npz_path.stat().st_size, "sha256": file_sha(npz_path)},
        "crop_extent": [w, h], "source_roi_origin": [sx, sy], "source_roi_extent": [sw, sh], "render_extent": manifest["render_extent"],
        "partial_history": True, "first_previous_frame_is_absent": True,
        "saved_rr_outputs_include_pre_fixture_history": True, "no_frame_looping": True,
        "ground_truth": False, "purpose": "Dry CPU research fixture, not a converged reference, game final output, or executable RR replay fixture. Albedos are not included.",
        "coordinate_contract": {"origin_order": "x,y; global original render pixels", "pixel_convention": "local integer pixel centers; the +0.5 terms cancel in correspondence", "motion_rg": "original physical full-render UV; previous minus current; no crop scaling or extra jitter applied", "previous_local_formula": "q_previous_local = current_local + crop_origin_render[t] + input_motion[t, ..., :2] * render_extent - crop_origin_render[t-1]", "valid_bilinear": "finite q and 0 <= qx < width-1 and 0 <= qy < height-1; outside crop is INVALID, never clamp or wrap", "motion_b": "previous minus current linear depth", "first_frame": "No previous fixture frame; do not loop the last frame to the first"},
        "storage_contract": {"radiance": "original little-endian captured FP16 RGBA; input alpha contains hit distance; no gain, normalization, clipping, conversion or exposure", "normal_roughness": "original packed RGB10A2 uint32; oct normal bits0..19, linear roughness bits20..29, material bits30..31; world-space normals", "controls": "original 46 uint32 words; preserve bits and original provider frame index", "camera_arrays": "original capture uint32 IEEE-754 word encodings; .view('<f4') for numeric camera matrices/positions"},
        "material_note": "Original material IDs are globally zero over all published frames of source 2405579e and 87ee1fba, as independently counted in task26. This is not a semantic material fixture; no such global claim is made for f2ef375f.",
        "analysis_note": "The bottle speed mask also includes hand/arm. The foliage band contains multiple depth/coverage surfaces. This small facade tile is not the original whole-ROI bench mask.",
        "exporter_sha256": file_sha(Path(__file__)),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"fixture": fixture_id, "frames": n, "archive_bytes": npz_path.stat().st_size, "metadata_bytes": meta_path.stat().st_size, "finite": True, "source_crop_hashes": len(provenance), "npz_sha256": meta["archive"]["sha256"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--fixture", choices=list(SPECS), action="append")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    for fixture in args.fixture or SPECS:
        export_one(args.trace_root, args.out, fixture, SPECS[fixture], args.overwrite)


if __name__ == "__main__":
    main()
