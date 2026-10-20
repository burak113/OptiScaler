#!/usr/bin/env python3
"""Validate published native-observation capture packets without modifying them.

Usage: python observation_capture_reader.py CAPTURE_FOLDER --output REPORT.json
The output must be outside the immutable capture folder. Partial published
prefixes are supported; private/pending frames are never promoted or read.
This verifies metadata/bytes and recorded claims, not GPU execution or quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import uuid


class CaptureValidationError(ValueError):
    """A packet contradicts its declared byte, lineage or authority contract."""


SCHEMA = "fsrd-native-observation-v1"
MAX_JSON_BYTES = 256 * 1024 * 1024
U64 = (1 << 64) - 1
COORDINATES = "bridge_render_pixels; title_native_source_mapping_not_inferred"
ALPHA = "opaque_original_words_at_each_observed_stage; no_float_conversion_or_semantic_validation"
SEMANTICS = "observations_only; no_causal_truth_or_quality_claim"
REASONS = ["unavailable_actual_nonzero_donor_footprint", "unavailable_recalled_key_correspondence"]
UNKNOWN_FIELDS = {"title_native_normal_roughness", "title_raw_depth", "title_raw_motion",
                  "title_crop_origin", "material_or_layer_identity", "upstream_exposure_and_modulation"}
# These are the numeric v1 values in the production header, not DXGI guesses.
ENCODINGS = {1: (10, 8), 2: (24, 4), 3: (41, 4), 4: (2, 16), 5: (0, 4),
             6: (42, 4), 7: (34, 4), 8: (62, 1)}
SURFACES = {
    "physical_source_specular": (1, 3, {1}), "physical_source_diffuse": (1, 2, {1}),
    "physical_pre_scale_specular": (2, 3, {1}), "physical_pre_scale_diffuse": (2, 2, {1}),
    "raw_rr_specular": (3, 3, {1}), "raw_rr_diffuse": (3, 2, {1}),
    "selected_rr_specular": (4, 3, {1}), "selected_rr_diffuse": (4, 2, {1}),
    "provider_normal_roughness": (6, 1, {2}), "bridge_normal_before_flat": (6, 1, {2}),
    "provider_depth": (8, 1, {3}), "provider_motion": (10, 1, {1, 4, 7}),
    "bridge_motion_before_lighting_guard": (10, 1, {1, 4, 7}),
    "depth_validity": (13, 1, {6, 8}), "anchor_sums": (11, 1, {5}),
}
PATHS = {"unknown": 0, "raw_rr": 1, "lobe_recovery": 2, "flat_albedo": 3, "protected_native": 4}


def require(condition, message):
    if not condition:
        raise CaptureValidationError(message)


def integer(value, label, minimum=0, maximum=U64):
    require(type(value) is int and minimum <= value <= maximum, label + ": invalid integer")
    return value


def vector(value, label, count=2, minimum=0):
    require(type(value) is list and len(value) == count, label + ": invalid dimensions")
    return [integer(x, label, minimum, (1 << 32)-1) for x in value]


def text(value, label):
    require(type(value) is str and bool(value), label + ": missing text")
    return value


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key: " + key)
        value[key] = item
    return value


def load_json(path):
    require(path.stat().st_size <= MAX_JSON_BYTES, "JSON exceeds bounded reader size")
    data = path.read_bytes()
    def bad_constant(value):
        raise CaptureValidationError("nonfinite JSON number: " + value)
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=bad_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CaptureValidationError("invalid UTF-8 JSON: " + str(path)) from error
    require(type(parsed) is dict, "JSON root must be an object")
    return parsed, hashlib.sha256(data).hexdigest()


def contained_file(root, name, prefix=None):
    text(name, "payload path")
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and str(relative) == name and "\\" not in name and ":" not in name and
            all(part not in (".", "..") for part in relative.parts), "unsafe capture path: " + name)
    if prefix is not None:
        require(name.startswith(prefix), "payload is outside its published frame: " + name)
    try:
        path = (root / relative).resolve(strict=True)
    except OSError as error:
        raise CaptureValidationError("missing capture file: " + name) from error
    require(path.is_relative_to(root) and path.is_file(), "capture path escapes folder: " + name)
    return path


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payloads(value):
    if isinstance(value, dict):
        if "file" in value:
            yield value
        for item in value.values():
            yield from payloads(item)
    elif isinstance(value, list):
        for item in value:
            yield from payloads(item)


def same_words(first, second):
    if first == second:
        return True
    with first.open("rb") as a, second.open("rb") as b:
        while True:
            left, right = a.read(1 << 20), b.read(1 << 20)
            if left != right:
                return False
            if not left:
                return True


def check_stamp(stamp, row):
    require(type(stamp) is dict and stamp.get("known") is True, "unknown packet stamp")
    for name in ("stream_id", "frame", "reset_epoch", "resource_epoch"):
        integer(stamp.get(name), "stamp." + name, 1 if name in ("stream_id", "resource_epoch") else 0)
    require(stamp["stream_id"] == row["identity"]["domain"] and stamp["frame"] == row["sdk_frame_index"] and
            stamp["resource_epoch"] == row["context_generation"], "packet stamp disagrees with host frame")
    require(row["context_id"] == str(stamp["stream_id"]) + ":" + str(stamp["resource_epoch"]),
            "context identity disagrees with stamp")


def check_footprint(footprint, image):
    require(type(footprint) is dict, "missing copy footprint")
    width, height, depth = vector(footprint.get("extent"), "copy extent", 3, 1)
    bpp = integer(image.get("bytes_per_pixel"), "image bytes per pixel", 1, 16)
    pitch = integer(footprint.get("row_pitch"), "copy pitch", 1)
    offset = integer(footprint.get("offset"), "copy offset")
    row_bytes = integer(footprint.get("row_bytes"), "copy row bytes", 1)
    requested = integer(footprint.get("requested_buffer_bytes"), "copy buffer bytes", 1)
    committed = integer(footprint.get("committed_buffer_bytes"), "copy committed bytes", 1)
    crop_x, crop_y = vector(footprint.get("cpu_crop_origin_in_readback"), "copy CPU crop")
    iw, ih = vector(image.get("extent"), "image extent", minimum=1)
    require(depth == 1 and footprint.get("rows") == height and row_bytes == width*bpp and pitch >= row_bytes and
            footprint.get("dxgi_format") == image.get("dxgi_format"), "invalid copy footprint dimensions/format")
    require(crop_x+iw <= width and crop_y+ih <= height and
            offset+(height-1)*pitch+row_bytes <= requested <= committed,
            "copy footprint does not contain captured rows")
    if image.get("dxgi_format") != 0:
        require(pitch % 256 == 0 and offset % 512 == 0, "texture copy footprint violates D3D12 alignment")


def check_surface(name, surface, packet, row, manifest, images):
    expected_role, lobe, encodings = SURFACES[name]
    require(type(surface) is dict, "missing surface: " + name)
    availability = surface.get("availability")
    if availability in ("missing", "unknown", "invalid"):
        require(name in ("depth_validity", "anchor_sums"), "required native surface unavailable: " + name)
        text(surface.get("reason"), name + " unavailable reason")
        require("image" not in surface and "payload_layout" not in surface, "missing observation carries invented payload")
        return None
    require(availability == "present", "unknown surface availability: " + name)
    require(integer(surface.get("role"), name + " role", 1, 13) == expected_role and
            integer(surface.get("lobe"), name + " lobe", 1, 3) == lobe, "wrong role/lobe: " + name)
    encoding = integer(surface.get("encoding"), name + " encoding", 1, 8)
    require(encoding in encodings, "wrong packed/typed representation: " + name)
    dxgi, bpp = ENCODINGS[encoding]
    require(surface.get("dxgi_format") == dxgi, "DXGI/encoding mismatch: " + name)
    require(surface.get("stamp") == packet["stamp"], "stale surface stamp: " + name)
    integer(surface.get("resource_id"), name + " resource identity", 1)
    text(surface.get("stage"), name + " observation stage")
    require(surface.get("coordinate_space") == COORDINATES, "unobserved title/native coordinates declared")
    image = images.get(surface.get("image"))
    require(image is not None, "surface references absent image: " + name)
    require(image["dxgi_format"] == dxgi and image.get("storage") == "original_little_endian_gpu_words",
            "image words/format mismatch: " + name)
    require(surface.get("copy_footprint") == image.get("copy_footprint"), "surface/image copy footprint mismatch")
    require(surface.get("native_texture_row_pitch") is None, "native texture pitch must remain opaque")
    text(surface.get("native_texture_row_pitch_reason"), "opaque pitch reason")
    allocation = vector(surface.get("allocation_extent"), "allocation extent", minimum=1)
    active = vector(surface.get("active_extent"), "active extent", minimum=1)
    captured = vector(surface.get("captured_extent"), "captured extent", minimum=1)
    origin = vector(surface.get("crop_origin"), "crop origin")
    if name == "anchor_sums":
        require(allocation == active == captured == [8,1] and origin == [0,0] and
                image["extent"] == image["source_extent"] == [32,1] and image["bytes_per_pixel"] == 1,
                "anchor sums must include all eight original uint32 words")
    else:
        require(active == manifest["render_extent"] and captured == manifest["roi"]["extent"] and
                origin == manifest["roi"]["origin"], "wrong active extent or crop origin: " + name)
        require(allocation == image["source_extent"] and captured == image["extent"] and
                origin == image["crop_origin"] and image["bytes_per_pixel"] == bpp,
                "surface/image allocation or crop mismatch: " + name)
        require(all(allocation[i] >= active[i] and origin[i]+captured[i] <= active[i] for i in (0,1)),
                "surface outside active/allocation extent: " + name)
    layout = surface.get("payload_layout", {})
    logical_row = captured[0]*bpp
    require(layout == {"byte_offset": 0, "row_pitch": logical_row, "row_bytes": logical_row,
                       "bytes": logical_row*captured[1]}, "disk payload is not declared tight: " + name)
    require(image["bytes"] == layout["bytes"], "truncated/expanded original words: " + name)
    scale = surface.get("scale", {})
    if lobe in (2,3):
        factor = integer(scale.get("provider_multiplier"), "provider scale", 1, 4096)
        require(scale.get("known") is True and not factor & (factor-1) and scale.get("stored_multiplier") == 1,
                "invalid observed radiance scale")
        require(factor == row["provider_radiance_scales"]["specular" if lobe == 3 else "diffuse"],
                "wrong lobe/provider scale: " + name)
    else:
        require(scale == {"known": False, "provider_multiplier": 0, "stored_multiplier": 0},
                "nonradiance guide given fabricated radiance scale")
    return image


def check_proof(row):
    for flag in ("gpu_submission_verified", "cpu_snapshot_immutable", "submission_gate_protected"):
        require(row.get(flag) is True, "published frame lacks recorded completion/snapshot proof")
    proof = row.get("ticket_proof", {})
    for flag in ("recorded", "submitted", "cpu_snapshot_immutable", "submission_gate_protected"):
        require(proof.get(flag) is True, "incomplete ticket proof: " + flag)
    for flag in ("invalid", "abandoned", "signal_failed", "ambiguous_submission"):
        require(proof.get(flag) is False, "invalid ticket proof: " + flag)
    expected = integer(proof.get("fence_expected"), "fence expected", 1)
    completed = integer(proof.get("fence_completed"), "fence completed", 1, U64-1)
    require(completed >= expected and proof.get("pending_signals") == 0 and proof.get("signal_hresult") == 0,
            "ticket not fence-complete/successfully signalled")


def _validate_capture(folder):
    root = Path(folder).resolve(strict=True)
    require(root.is_dir(), "capture must be a directory")
    manifest_path = contained_file(root, "capture.json")
    manifest, manifest_hash = load_json(manifest_path)
    require(manifest.get("schema") == "fsrd-nrd-bridge-game-trace-v1", "unsupported capture schema")
    capture_id = text(manifest.get("capture_uuid"), "capture UUID")
    try:
        require(str(uuid.UUID(capture_id)) == capture_id, "capture UUID is not canonical")
    except ValueError as error:
        raise CaptureValidationError("invalid capture UUID") from error
    requested = manifest.get("native_observations", {})
    require(requested.get("schema") == SCHEMA and requested.get("requested") is True and
            requested.get("default_enabled") is False and requested.get("capture_only") is True,
            "native capture was not explicitly requested")
    rows = manifest.get("frames")
    require(type(rows) is list, "manifest frames are not an ordered list")
    require(type(manifest.get("complete")) is bool, "unknown capture completion state")
    target = integer(manifest.get("target_frames"), "target frames", 1)
    require(len(rows) <= target and integer(manifest.get("committed_frames"), "committed frames") == len(rows) and
            integer(manifest.get("manifest_published_frames"), "published frames") == len(rows), "published prefix count mismatch")
    require(not manifest["complete"] or len(rows) == target, "complete capture has missing frames")
    if rows:
        vector(manifest.get("render_extent"), "render extent", minimum=1)
        vector(manifest.get("roi", {}).get("origin"), "ROI origin")
        vector(manifest["roi"].get("extent"), "ROI extent", minimum=1)
    result = {"schema": "fsrd.native_observations.offline_validation.v1", "capture_id": capture_id,
              "manifest_sha256": manifest_hash, "complete": manifest["complete"],
              "published_frames": len(rows), "target_frames": target, "frames": [],
              "scope": "published_immutable_prefix_metadata_and_original_word_consistency",
              "gpu_executed_by_validator": False, "capture_origin_authenticated": False,
              "causal_or_quality_acceptance": False, "native_support_available": False,
              "private_or_unpublished_frames_validated": False}
    previous = None
    for ordinal, row in enumerate(rows):
        require(type(row) is dict and integer(row.get("ordinal"), "frame ordinal") == ordinal,
                "frames must be an unlooped contiguous ordinal prefix")
        prefix = f"frames/{ordinal}/"
        disk_row, frame_hash = load_json(contained_file(root, prefix + "frame.json", prefix))
        require(disk_row == row, "immutable frame.json differs from published manifest row")
        check_proof(row)
        files, bytes_total = {}, 0
        for descriptor in payloads(row):
            name = descriptor.get("file")
            path = contained_file(root, name, prefix)
            size = integer(descriptor.get("bytes"), "payload byte count")
            digest = descriptor.get("sha256")
            require(type(digest) is str and re.fullmatch("[0-9a-f]{64}", digest), "invalid SHA-256 declaration")
            require(path.stat().st_size == size, "payload length mismatch: " + name)
            if name not in files:
                require(file_hash(path) == digest, "payload SHA-256 mismatch: " + name)
                files[name] = (path, size, digest); bytes_total += size
            else:
                require(files[name][1:] == (size, digest), "conflicting repeated payload declaration")
        packet = row.get("native_observations", {})
        require(packet.get("schema") == SCHEMA and integer(packet.get("abi_version"), "observation ABI") == 1 and
                packet.get("capture_id") == capture_id, "observation schema/version/capture identity mismatch")
        check_stamp(packet.get("stamp"), row)
        stamp = packet["stamp"]
        require(packet.get("recording_id") == row["identity"]["recording_id"] and
                packet.get("streamline_frame") == row["identity"]["streamline_frame"], "wrong recording/Streamline frame")
        integer(packet["recording_id"], "recording identity", 1)
        integer(packet["streamline_frame"], "Streamline frame", 0, (1 << 32)-2)
        require(type(packet.get("actual_reset")) is bool and packet["actual_reset"] == row.get("actual_reset"),
                "actual reset disagrees with host row")
        require(not packet["actual_reset"] or stamp["reset_epoch"] > 0, "reset did not advance its epoch")
        if previous is not None:
            old = previous["stamp"]
            require(stamp["stream_id"] == old["stream_id"] and stamp["resource_epoch"] == old["resource_epoch"] and
                    stamp["frame"] == old["frame"]+1 and packet["streamline_frame"] == previous["streamline_frame"]+1 and
                    packet["recording_id"] > previous["recording_id"] and
                    stamp["reset_epoch"] == old["reset_epoch"]+int(packet["actual_reset"]),
                    "stale/reset/resize/nonchronological observation sequence")
        previous = packet
        controls = row.get("provider_controls", {})
        require(controls.get("wireformat") == "ffxDispatchDescDenoiser_native_ABI_suffix_264_184" and
                controls.get("native_dispatch_bytes") == 448 and controls.get("controls_offset") == 264 and
                controls.get("controls_bytes") == controls.get("bytes") == 184, "provider control word ABI mismatch")
        control_words = files[controls["file"]][0].read_bytes()
        width, height, sdk_frame, flags = struct.unpack_from("<4I", control_words, 168)
        require([width,height] == manifest["render_extent"] and sdk_frame == stamp["frame"] and
                flags == row.get("actual_dispatch_flags") and bool(flags & 1) == packet["actual_reset"],
                "provider control words disagree with frame/extent/reset")
        params = row.get("frame_parameters", {})
        require(params.get("frame_index") == stamp["frame"] and params.get("streamline_frame") == packet["streamline_frame"] and
                params.get("depth_sign") == packet.get("provider_depth_sign_float32_bits") and
                packet.get("provider_depth_sign_float32_bits") in (0x3f800000,0xbf800000),
                "unknown/wrong provider frame or depth-sign convention")
        motion = packet.get("motion_convention", {})
        require(motion.get("units") == "full_render_uv" and motion.get("direction") == "previous_minus_current" and
                motion.get("jitter") == "already_encoded_no_extra_delta" and motion.get("per_pixel_correspondence") == "unknown" and
                struct.unpack_from("<3I", control_words) == (0x3f800000,)*3,
                "wrong motion scale/convention or fabricated correspondence")
        require(packet.get("alpha_policy") == ALPHA and packet.get("capture_semantics") == SEMANTICS,
                "opaque-word observation contract changed")
        unknown = packet.get("unknown", {})
        require(type(unknown) is dict and set(unknown) == UNKNOWN_FIELDS and all(type(v) is str and v for v in unknown.values()),
                "missing native unknown/provenance declarations")
        support = packet.get("support", {})
        require(integer(support.get("version"), "support version") == 1 and support.get("valid") is False and
                integer(support.get("reason_bits"), "support reason bits") == 3 and
                support.get("reasons") == REASONS, "invented support or missing invalid-support reason bits")
        images = {}
        for image in row.get("images", []):
            key = text(image.get("name"), "image name")
            require(key not in images, "duplicate image name")
            require(image.get("file") in files, "image has no verified payload")
            iw, ih = vector(image.get("extent"), "image extent", minimum=1)
            require(image["bytes"] == iw*ih*integer(image.get("bytes_per_pixel"), "image stride", 1, 16),
                    "image byte count differs from tight stored extent")
            check_footprint(image.get("copy_footprint"), image)
            images[key] = image
        surfaces = packet.get("surfaces", {})
        require(type(surfaces) is dict and set(surfaces) == set(SURFACES), "required observation role declaration omitted/unknown")
        image_ids, resource_ids, missing = {}, {}, []
        for name, surface in surfaces.items():
            image = check_surface(name, surface, packet, row, manifest, images)
            if image is None:
                missing.append(name); continue
            key, rid = surface["image"], surface["resource_id"]
            require(image_ids.setdefault(key, rid) == rid and resource_ids.setdefault(rid, key) == key,
                    "resource alias identity contradicts captured image identity")
        authorities = packet.get("authority", {})
        require(set(authorities) == {"specular", "diffuse"}, "missing per-lobe host selection witness")
        authority_summary = {}
        for lobe, value in authorities.items():
            raw, selected = surfaces["raw_rr_"+lobe], surfaces["selected_rr_"+lobe]
            path = value.get("selection_path")
            for field in ("selection_path_value", "selection_authority", "raw_resource_id", "selected_resource_id",
                          "equality_guard", "authority_validation_reason"):
                integer(value.get(field), "authority."+field)
            require(path in PATHS and value.get("selection_path_value") == PATHS[path], "invalid host selection enum")
            require(value.get("raw_resource_id") == raw["resource_id"] and
                    value.get("selected_resource_id") == selected["resource_id"], "stale raw/selected resource IDs")
            if path != "unknown":
                actual_path = "flat_albedo" if row["flat_albedo"]["graph_recorded"] else (
                    "lobe_recovery" if row["recovery"]["graph_recorded"] else "raw_rr")
                require(path == actual_path, "selection route contradicts actual host graph")
            alias = raw["resource_id"] == selected["resource_id"]
            authority = 1 if path == "raw_rr" and alias else (2 if PATHS[path] in (2,3,4) else 0)
            equal = same_words(files[images[raw["image"]]["file"]][0], files[images[selected["image"]]["file"]][0])
            equality = 1 if equal else 2
            reason = 19 if authority == 0 else (20 if authority == 2 else (0 if equal else 23))
            require(value.get("selection_authority") == authority and value.get("equality_guard") == equality and
                    value.get("raw_authority_valid") is (reason == 0) and value.get("authority_validation_reason") == reason,
                    "synthesized authority or false original-word equality")
            require(value.get("equality_status") == "original_words_compared_after_protected_fence_snapshot" and
                    value.get("raw_edit_eligible") is False, "uncompleted equality or edit despite invalid native support")
            authority_summary[lobe] = {"selection_path": path, "equal_words": equal,
                                       "raw_authority_valid": reason == 0, "raw_edit_eligible": False}
        result["frames"].append({"ordinal": ordinal, "sdk_frame": stamp["frame"], "reset_epoch": stamp["reset_epoch"],
                                 "frame_json_sha256": frame_hash, "verified_payload_files": len(files),
                                 "verified_payload_bytes": bytes_total, "missing_observations": missing,
                                 "authority": authority_summary})
    # Atomic manifest replacement during inspection requires a retry, not a
    # report combining an old prefix with a new manifest identity.
    require(file_hash(manifest_path) == manifest_hash, "capture manifest changed during validation; retry on a stable snapshot")
    result["valid"] = True
    return result


def validate_capture(folder):
    """Validate one published snapshot; malformed nested structures fail closed."""
    try:
        return _validate_capture(folder)
    except (KeyError, TypeError, AttributeError, IndexError, struct.error) as error:
        raise CaptureValidationError("malformed capture structure: " + str(error)) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output:
            require(not args.output.resolve().is_relative_to(args.capture.resolve()), "output must be outside immutable capture")
        report = validate_capture(args.capture)
    except (CaptureValidationError, KeyError, TypeError, OSError) as error:
        report = {"schema": "fsrd.native_observations.offline_validation.v1", "valid": False,
                  "error": str(error), "gpu_executed_by_validator": False, "causal_or_quality_acceptance": False}
    serialized = json.dumps(report, indent=2) + "\n"
    if args.output:
        # Do not write even a failure report inside the source capture.
        if args.output.resolve().is_relative_to(args.capture.resolve()):
            print(serialized, end=""); return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
