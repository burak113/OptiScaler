"""Validate a published NRD-to-RR GAME_TRACE prefix and write a replay-input index.

This is a payload/provenance contract, not an image-quality oracle. It never
loads native NRD denoised output and never invents hidden SDK history. A valid
ROI capture can remain ineligible for a complete temporal replay.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import math
import struct

SCHEMA = "fsrd-nrd-bridge-game-trace-v1"
FORMATS = {
    "input_specular": (10, 8), "input_diffuse": (10, 8), "input_depth": (41, 4),
    "input_motion": (10, 8), "input_normal_roughness": (24, 4),
    "input_specular_albedo": (28, 4), "input_diffuse_albedo": (28, 4),
    "raw_rr_specular": (10, 8), "raw_rr_diffuse": (10, 8),
    "selected_rr_specular": (10, 8), "selected_rr_diffuse": (10, 8),
    "encoded_commit_specular": (10, 8), "encoded_commit_diffuse": (10, 8),
    "consumer_word303": (0, 1),
}
INPUTS = tuple(FORMATS)[:7]
MAX_FRAME = 256 << 20


def require(condition, message):
    if not condition:
        raise ValueError(message)


def uint(value, label, maximum=(1 << 64) - 1):
    require(type(value) is int and 0 <= value <= maximum, f"invalid {label}")
    return value


def words(value, size, label):
    require(isinstance(value, list) and len(value) == size, f"invalid {label} words")
    for word in value:
        uint(word, label, 0xffffffff)


def safe_file(root, relative):
    require(isinstance(relative, str) and "\\" not in relative and ":" not in relative,
            "unsafe payload path")
    path = PurePosixPath(relative)
    require(not path.is_absolute() and len(path.parts) == 3 and path.parts[0] == "frames"
            and path.parts[1].isdigit() and path.parts[2] not in ("", ".", ".."),
            "payload outside published frame folder")
    candidate = root.joinpath(*path.parts).resolve()
    require(candidate.is_relative_to(root), "payload symlink escapes capture")
    return candidate


def verify_file(root, row, ordinal, expected_bytes, verify):
    require(row.get("bytes") == expected_bytes, "payload byte count differs from typed layout")
    path = safe_file(root, row.get("file"))
    require(PurePosixPath(row["file"]).parts[1] == str(ordinal), "cross-frame payload path")
    digest = row.get("sha256")
    require(isinstance(digest, str) and len(digest) == 64 and
            all(c in "0123456789abcdef" for c in digest), "invalid payload hash")
    if verify:
        require(path.is_file() and path.stat().st_size == expected_bytes, "payload size/file mismatch")
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                hasher.update(block)
        require(hasher.hexdigest() == digest, "payload SHA-256 mismatch")
    return {"file": row["file"], "bytes": expected_bytes, "sha256": digest}


def inspect_capture(folder, *, verify_payload=True):
    root = Path(folder).resolve()
    manifest_path = root / "capture.json"
    require(manifest_path.stat().st_size <= 32 << 20, "manifest exceeds bounded reader size")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    require(manifest.get("schema") == SCHEMA, "unsupported trace schema")
    require(manifest.get("capture_path") == "nrd_bridge", "capture path is not the bridge")
    published = uint(manifest.get("manifest_published_frames"), "published prefix", 512)
    require(published > 0, "no published frames")
    frames = manifest.get("frames")
    require(isinstance(frames, list) and len(frames) >= published, "published prefix is absent")
    require(manifest.get("maximum_frame_readback_bytes") == MAX_FRAME, "unexpected capture budget")
    roi = manifest.get("roi", {})
    extent, origin = roi.get("extent"), roi.get("origin")
    require(isinstance(extent, list) and len(extent) == 2 and all(type(x) is int and x > 0 for x in extent), "invalid ROI extent")
    require(isinstance(origin, list) and len(origin) == 2 and all(type(x) is int and x >= 0 for x in origin), "invalid ROI origin")
    render = manifest.get("render_extent")
    require(isinstance(render, list) and len(render) == 2 and all(type(x) is int and x > 0 for x in render)
            and all(origin[i] + extent[i] <= render[i] for i in (0, 1)), "ROI outside render extent")
    require(manifest.get("native_nrd_outputs") == {"captured": False, "used_as_reference": False, "used_as_correction": False},
            "native NRD output is forbidden in this replay contract")
    reasons, result, prior, stable = [], [], None, None
    if manifest.get("region_mode") != "full_render" or origin != [0, 0] or extent != render:
        reasons.append("cropped_inputs_cannot_reconstruct_full_frame_temporal_history")
    for ordinal, frame in enumerate(frames[:published]):
        require(frame.get("ordinal") == ordinal and frame.get("output_committed") is True, "uncommitted/noncontiguous frame")
        require(frame.get("cpu_snapshot_immutable") is True and frame.get("submission_gate_protected") is True
                and frame.get("gpu_submission_verified") is True, "missing protected snapshot proof")
        proof = frame.get("ticket_proof", {})
        require(proof.get("submitted") is True and proof.get("submission_gate_protected") is True,
                "missing actual submission proof")
        require(proof.get("cpu_snapshot_immutable") is True and proof.get("recorded") is True
                and proof.get("invalid") is False and proof.get("signal_failed") is False
                and proof.get("ambiguous_submission") is False and proof.get("pending_signals") == 0
                and type(proof.get("fence_expected")) is int and proof["fence_expected"] > 0
                and proof.get("fence_completed", -1) >= proof["fence_expected"]
                and proof.get("signal_hresult") == 0, "invalid/incomplete GPU submission proof")
        identity = frame.get("identity", {})
        for key in ("domain", "recording_id", "recording_generation", "cancellation_serial", "cache_generation", "streamline_frame"):
            uint(identity.get(key), key, 0xffffffff if key == "streamline_frame" else (1 << 64) - 1)
        require(identity["domain"] > 0 and identity["recording_id"] > 0 and identity["recording_generation"] > 0
                and identity["streamline_frame"] != 0xffffffff, "incomplete recording identity")
        require(identity["domain"] == manifest.get("captured_domain"), "mixed chain/domain payload")
        require(frame.get("native_nrd_output_captured") is False, "forbidden native output stage")
        settings = frame.get("settings", {})
        require(settings.get("native_nrd_output_used") is False, "forbidden native output correction")
        encoded_settings = json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        require(hashlib.sha256(encoded_settings).hexdigest() == frame.get("settings_sha256"), "settings hash mismatch")
        for key in ("requested_values", "provider_defaults", "provider_effective"):
            words(settings.get(key), 8, key)
        for key in ("recovery_specular", "recovery_diffuse"):
            uint(settings.get(key), key, 0xffffffff)
        params = frame.get("frame_parameters", {})
        require(params.get("float_encoding") == "ieee754_binary32_uint32_words", "lossy frame controls")
        require(params.get("streamline_frame") == identity["streamline_frame"]
                and params.get("frame_index") == frame.get("sdk_frame_index"), "frame controls identity differs")
        for key, count in (("motion_scale", 2), ("jitter", 2), ("previous_jitter", 2),
                           ("camera_position", 3), ("previous_camera_position", 3)):
            words(params.get(key), count, key)
        for key in ("near_plane", "far_plane", "depth_sign"):
            uint(params.get(key), key, 0xffffffff)
        for key in ("view", "inverse_view", "projection"):
            words(params.get("camera", {}).get(key), 16, key)
        sl = params.get("streamline", {})
        require(sl.get("frame") == identity["streamline_frame"], "Streamline snapshot belongs to another frame")
        for key in ("camera_view_to_clip", "clip_to_camera_view", "clip_to_lens_clip", "clip_to_previous_clip", "previous_clip_to_clip"):
            words(sl.get(key), 16, key)
        controls = verify_file(root, frame.get("provider_controls", {}), ordinal, 184, verify_payload)
        flags = uint(frame.get("actual_dispatch_flags"), "actual flags", 0xffffffff)
        sdk_frame = uint(frame.get("sdk_frame_index"), "SDK frame", 0xffffffff)
        require(frame.get("actual_reset") == bool(flags & 1), "RESET differs from actual SDK flags")
        if verify_payload:
            tail = safe_file(root, controls["file"]).read_bytes()
            require(all(math.isfinite(x) for x in struct.unpack_from("<42f", tail)), "nonfinite provider controls")
            require(struct.unpack_from("<4I", tail, 168) == (render[0], render[1], sdk_frame, flags),
                    "actual provider tail differs from frame/extent/flags")
        provider = frame.get("provider", {})
        witness = provider.get("route_attestation", {})
        binary = witness.get("creation", {}).get("implementation_identity", {})
        binary_hash = binary.get("disk_sha256") if isinstance(binary, dict) else None
        attested = (witness.get("attested") is True and provider.get("binary_identity_available") is True
                    and isinstance(binary_hash, str) and len(binary_hash) == 64)
        if not attested and "actual_provider_binary_attestation_unavailable" not in reasons:
            reasons.append("actual_provider_binary_attestation_unavailable")
        current = (identity["domain"], frame.get("context_generation"), frame.get("settings_sha256"),
                   provider.get("version_id"), provider.get("api_version"), binary_hash)
        if stable is None:
            stable = current
            if not flags & 1:
                reasons.append("first_captured_provider_invocation_has_no_actual_RESET; prior_SDK_history_unavailable")
        require(stable == current and current[1] > 0, "context/settings/provider changed inside published sequence")
        if prior is not None:
            require(identity["streamline_frame"] == prior[0] + 1 and sdk_frame == prior[1] + 1
                    and identity["recording_id"] > prior[2], "nonconsecutive provider/SL/recording sequence")
        prior = identity["streamline_frame"], sdk_frame, identity["recording_id"]
        images = frame.get("images")
        require(isinstance(images, list) and 1 <= len(images) <= 14, "unexpected bridge image count")
        physical, charged, payload_bytes = {}, 0, 184
        for row in images:
            name = row.get("name")
            require(name in FORMATS and name not in physical, "unknown/duplicate image stage")
            fmt, bpp = FORMATS[name]
            expected_extent = [4, 1] if name == "consumer_word303" else extent
            require(row.get("dxgi_format") == fmt and row.get("bytes_per_pixel") == bpp
                    and row.get("extent") == expected_extent, "image typed layout mismatch")
            if name != "consumer_word303":
                require(row.get("crop_origin") == origin, "image ROI/source frame differs")
            size = expected_extent[0] * expected_extent[1] * bpp
            physical[name] = verify_file(root, row, ordinal, size, verify_payload)
            footprint = row.get("copy_footprint", {})
            allocation = uint(footprint.get("committed_buffer_bytes"), "readback allocation")
            require(allocation >= size and allocation % (64 << 10) == 0, "invalid committed readback charge")
            charged += allocation
            payload_bytes += size
        require(charged <= MAX_FRAME, "frame readback budget exceeded")
        roles = frame.get("roles", {})
        require(set(roles) == set(FORMATS), "missing or invented bridge role")
        require(all(roles[name] == name for name in ("encoded_commit_specular", "encoded_commit_diffuse")),
                "encoded commit cannot alias an earlier observation")
        resolved = {}
        for name in FORMATS:
            cursor, seen = name, set()
            while roles.get(cursor) != cursor:
                require(cursor in roles and cursor not in seen, "cyclic/dangling stage alias")
                seen.add(cursor)
                cursor = roles[cursor]
            if name == "consumer_word303" and not frame.get("encoding", {}).get("native_flag_captured"):
                require(cursor not in physical, "unused native flag must not invent payload")
                continue
            require(cursor in physical and FORMATS[cursor] == FORMATS[name], "missing/incompatible aliased stage")
            resolved[name] = physical[cursor]
        encoding = frame.get("encoding", {})
        if encoding.get("native_flag_captured"):
            require(encoding.get("native_source_word") in (36, 303) and encoding.get("private_payload_word") == 303
                    and encoding.get("private_payload_byte_offset") == 1212, "native/private encoding word provenance missing")
            if verify_payload:
                flag = struct.unpack("<I", safe_file(root, resolved["consumer_word303"]["file"]).read_bytes())[0]
                encoding = dict(encoding, captured_encoding_word=flag)
        else:
            uint(encoding.get("fallback_encoding"), "fallback encoding", 1)
        events = frame.get("skipped_original_dispatches")
        require(isinstance(events, list) and len(events) <= 64, "skip metadata bound exceeded")
        sequence = 0
        for event in events:
            require(event.get("original_suppressed") is True and event.get("native_output_payload") is False,
                    "skipped original cannot claim native output")
            require(uint(event.get("sequence"), "skip sequence") > sequence, "skip order not increasing")
            sequence = event["sequence"]
        result.append({"ordinal": ordinal, "identity": identity, "context_generation": current[1],
                       "sdk_frame_index": sdk_frame, "actual_dispatch_flags": flags,
                       "provider_controls": controls, "provider": provider, "frame_parameters": params,
                       "settings": settings, "inputs": {name: resolved[name] for name in INPUTS},
                       "observations": {name: row for name, row in resolved.items() if name not in INPUTS},
                       "encoding": encoding, "payload_bytes": payload_bytes,
                       "skipped_original_dispatches": events})
    return {"schema": "fsrd-nrd-bridge-replay-inputs-v1", "capture_uuid": manifest.get("capture_uuid"),
            "capture_root": str(root), "published_frames": published, "payload_hashes_verified": verify_payload,
            "captured_domain": stable[0], "full_temporal_replay_eligible": not reasons and verify_payload,
            "ineligibility_reasons": reasons + ([] if verify_payload else ["payloads_not_verified"]),
            "source_contract": manifest.get("source_contract"), "frames": result,
            "replay_scope": "actual_RR_provider_inputs_and_raw_outputs; selected_recovery_and_encoded_commit_are_observations",
            "limitations": ["disk_file_attestation_does_not_prove_loaded_memory_image_equality",
                            "one_selected_chain_only; no_full_game_coverage_claim",
                            "captured_RR_outputs_are_observations_not_clean_truth",
                            "no_native_NRD_denoised_output_reference_or_correction"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.capture.resolve()), "replay manifest output must be outside source capture")
    result = inspect_capture(args.capture)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "frames"}, indent=2))


if __name__ == "__main__":
    main()
