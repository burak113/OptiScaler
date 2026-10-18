"""Validate a published NRD-to-RR GAME_TRACE prefix and write a replay-input index.

This is a payload/provenance contract, not an image-quality oracle. It never
loads native NRD denoised output and never invents hidden SDK history. A valid
ROI capture can remain ineligible for a complete temporal replay: inspection
(identity, selector, phase, ROI views) stays available for every schema-valid
capture, while full temporal replay additionally demands a complete full-render
prefix that starts with an actual SDK RESET, a 64-frame sample, and the
manifest provenance fields (commit, provider binary identity, guide/motion
policy, source time, reset reason).
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import math
import re
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
AUXILIARY_FORMATS = {"recovery_original_normal_roughness": (24, 4)}
MAX_FRAME = 256 << 20
# G03/WP07 inspection names for the attested per-profile native control words.
# Offsets are the already-captured native_byte_offset values; names only make
# the recorded bytes self-describing. They never redefine the capture.
NATIVE_CONTROL_FIELDS = {
    "A_Recon_direct": {448: "native_word28_x", 452: "native_word28_y",
                       456: "signed_source_origin_x", 460: "signed_source_origin_y"},
    "B_PrePass": {456: "signed_source_origin_x", 460: "signed_source_origin_y",
                  472: "integer_rect_width", 476: "integer_rect_height",
                  516: "local_checkerboard_phase", 520: "reserved_native_word32_z",
                  576: "diffuse_mode_0_1_checkerboard_2_full_rate",
                  580: "specular_mode_0_1_checkerboard_2_full_rate"},
}
MINIMUM_REPLAY_PREFIX_FRAMES = 64


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


def inspect_native_control_header(root, frame, ordinal, identity, verify_payload):
    header = frame.get("native_control_header", {"available": False})
    require(type(header.get("available")) is bool, "native control header availability missing")
    if not header["available"]:
        require("file" not in header and "words" not in header, "uncaptured native controls invented payload")
        return dict(header), 0
    version = uint(header.get("contract_version", 1), "native control contract version", 2)
    require(version in (1, 2), "unsupported native control contract")
    expected = {"A_Recon_direct": [448, 452, 456, 460],
                "B_PrePass": [456, 460, 472, 476, 516, 520, 576, 580] if version == 2 else
                            [456, 460, 472, 476, 516, 576, 580]}.get(header.get("profile"))
    require(expected is not None, "unknown native control profile")
    require(header.get("recording_id") == identity["recording_id"]
            and header.get("streamline_frame") == identity["streamline_frame"]
            and header.get("bridge_frame") == frame["sdk_frame_index"], "native control source frame differs")
    mapping = header.get("words")
    require(isinstance(mapping, list) and len(mapping) == len(expected), "native control profile word count differs")
    size = 4 * len(expected)
    require(header.get("dxgi_format") == 0 and header.get("bytes_per_pixel") == 1
            and header.get("extent") == [size, 1], "native control packed layout differs")
    require(header.get("copy_footprint", {}).get("committed_buffer_bytes") == 0
            and header.get("readback_allocation_shared_with") == "private_encoding_flag_reserved_readback",
            "native control shared allocation charge differs")
    payload = verify_file(root, header, ordinal, size, verify_payload)
    data = safe_file(root, payload["file"]).read_bytes() if verify_payload else None
    source = header.get("source_native_resource_desc", {})
    source_width = uint(source.get("width"), "owned native control buffer width")
    require(source.get("dimension") == 1 and header.get("source_state") in (0, 2048), "native control owned buffer/state differs")
    allocation = uint(header.get("shared_committed_buffer_bytes"), "native control shared committed bytes")
    require(allocation >= 32 and allocation % (64 << 10) == 0, "native control reserved readback charge differs")
    field_names = NATIVE_CONTROL_FIELDS[header["profile"]]
    private_offsets = set()
    for index, row in enumerate(mapping):
        offset = uint(row.get("source_buffer_byte_offset"), "native control private offset", 0xffffffff)
        require(row.get("native_byte_offset") == expected[index] and offset % 4 == 0
                and offset + 4 <= source_width and offset not in private_offsets and row.get("payload_byte_offset") == 4 * index,
                "native/private control word mapping differs")
        private_offsets.add(offset)
        row = dict(row, field=field_names[expected[index]])
        mapping[index] = row
        value = uint(row.get("captured_uint32"), "captured native control word", 0xffffffff)
        if data is not None:
            require(struct.unpack_from("<I", data, 4 * index)[0] == value, "native control decoded value differs from payload")
    status = header.get("owned_status", {"available": False, "reason": "legacy_v1_status_not_captured"})
    require(type(status.get("available")) is bool, "owned validation status availability missing")
    if version == 2 and header["profile"] == "B_PrePass":
        require(status["available"] is True, "B_v2 owned validation status missing")
        require(status.get("origin") == "bridge_generated_raw_capture_validation; NOT_a_native_operand"
                and status.get("source_buffer_byte_offset") == 0 and status.get("readback_buffer_byte_offset") == 36,
                "owned status misdeclared as a native operand")
        require(status.get("dxgi_format") == 0 and status.get("bytes_per_pixel") == 1
                and status.get("extent") == [4, 1] and status.get("copy_footprint", {}).get("committed_buffer_bytes") == 0
                and status.get("readback_allocation_shared_with") == "private_encoding_flag_reserved_readback",
                "owned status typed/shared layout differs")
        status_payload = verify_file(root, status, ordinal, 4, verify_payload)
        code = uint(status.get("captured_uint32"), "bridge owned status", 0xffffffff)
        if verify_payload:
            require(struct.unpack("<I", safe_file(root, status_payload["file"]).read_bytes())[0] == code,
                    "owned status decoded value differs from payload")
        status = dict(status, payload=status_payload)
        size += 4
    else:
        require(status["available"] is False and "file" not in status, "uncaptured/A status invented payload")
    return dict(header, payload=payload, owned_status=status,
                recorded_fields=[field_names[offset] for offset in expected]), size


def provider_radiance_scales(frame):
    scale = frame.get("provider_radiance_scale", 1)
    scales = frame.get("provider_radiance_scales", {"diffuse": scale, "specular": scale})
    require(isinstance(scales, dict) and set(scales) == {"diffuse", "specular"}, "invalid provider radiance scales")
    for value in scales.values():
        require(type(value) in (int, float) and value in tuple(2**k for k in range(13)), "unsupported provider radiance scale")
    require(type(scale) in (int, float) and scale == (scales["diffuse"] if scales["diffuse"] == scales["specular"] else 0), "inconsistent legacy provider radiance scale")
    policy = frame.get("settings", {}).get("radiance_scale")
    if policy is not None:
        require(isinstance(policy, dict) and type(policy.get("enabled")) is bool, "invalid radiance scale policy")
        expected = {name: policy.get(name) for name in ("diffuse", "specular")} if policy["enabled"] else {"diffuse": 256, "specular": 256}
        require(scales == expected, "actual provider radiance scales contradict the frozen settings")
    return scale, scales


def inspect_capture(folder, *, verify_payload=True, strict_continuity=True):
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
    # G06: optional replay-provenance fields. Present-but-invalid content is
    # rejected outright; absence keeps the capture inspect-only.
    commit = manifest.get("bridge_commit")
    require(commit is None or (isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit) is not None),
            "invalid bridge_commit")
    provider_hash = manifest.get("provider_binary_sha256")
    require(provider_hash is None or (isinstance(provider_hash, str) and re.fullmatch(r"[0-9a-f]{64}", provider_hash) is not None),
            "invalid provider_binary_sha256")
    policy = manifest.get("guide_motion_policy")
    require(policy is None or (isinstance(policy, str) and policy != ""), "invalid guide_motion_policy")
    captured_at = manifest.get("captured_at_utc")
    require(captured_at is None or (isinstance(captured_at, str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z", captured_at) is not None),
            "invalid captured_at_utc")
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
    reset_reason_missing = False
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
                and type(proof.get("fence_expected")) is int and proof["fence_expected"] == 1
                and type(proof.get("fence_completed")) is int and 1 <= proof["fence_completed"] < (1 << 64) - 1
                and type(proof.get("signal_hresult")) is int and 0 <= proof["signal_hresult"] < 0x80000000, "invalid/incomplete GPU submission proof")
        identity = frame.get("identity", {})
        for key in ("domain", "recording_id", "recording_generation", "cancellation_serial", "cache_generation", "streamline_frame"):
            uint(identity.get(key), key, 0xffffffff if key == "streamline_frame" else (1 << 64) - 1)
        require(identity["domain"] > 0 and identity["recording_id"] > 0 and identity["recording_generation"] > 0
                and identity["streamline_frame"] != 0xffffffff, "incomplete recording identity")
        require(identity["domain"] == manifest.get("captured_domain"), "mixed chain/domain payload")
        require(frame.get("native_nrd_output_captured") is False, "forbidden native output stage")
        settings = frame.get("settings", {})
        turn = settings.get("turn_colour")
        require(turn is None or (isinstance(turn, dict) and type(turn.get("enabled")) is bool and
                type(turn.get("brightness", False)) is bool), "invalid post-turn RR input policy")
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
        required_controls = ("checkerboard_signal_flags", "diffuse_checkerboard_origin", "specular_checkerboard_origin")
        if not all(key in provider for key in required_controls):
            if "actual_checkerboard_create_and_signal_controls_unavailable" not in reasons:
                reasons.append("actual_checkerboard_create_and_signal_controls_unavailable")
        else:
            signal_flags = uint(provider.get("signal_flags"), "actual provider signal flags", 0xffffffff)
            cb_flags = uint(provider["checkerboard_signal_flags"], "actual provider checkerboard flags", 0xffffffff)
            require(cb_flags & ~signal_flags == 0, "checkerboard flags are not a subset of actual signals")
            for key in required_controls[1:]:
                uint(provider[key], "actual " + key, 1)
        witness = provider.get("route_attestation", {})
        binary = witness.get("creation", {}).get("implementation_identity", {})
        binary_hash = binary.get("disk_sha256") if isinstance(binary, dict) else None
        attested = (witness.get("attested") is True and provider.get("binary_identity_available") is True
                    and isinstance(binary_hash, str) and len(binary_hash) == 64)
        if not attested and "actual_provider_binary_attestation_unavailable" not in reasons:
            reasons.append("actual_provider_binary_attestation_unavailable")
        if provider_hash is not None and attested:
            require(binary_hash == provider_hash, "manifest provider binary hash differs from the attested frame binary")
        reset_reason = frame.get("reset_reason")
        require(reset_reason is None or isinstance(reset_reason, str), "invalid reset_reason type")
        if isinstance(reset_reason, str):
            require(reset_reason != "", "empty reset_reason")
        if frame.get("actual_reset") and not (isinstance(reset_reason, str) and reset_reason):
            reset_reason_missing = True
        current = (identity["domain"], frame.get("context_generation"), frame.get("settings_sha256"),
                   provider.get("version_id"), provider.get("api_version"), binary_hash,
                   provider.get("signal_flags"), provider.get("context_flags"), provider.get("checkerboard_signal_flags"))
        if stable is None:
            stable = current
            if not flags & 1:
                reasons.append("first_captured_provider_invocation_has_no_actual_RESET; prior_SDK_history_unavailable")
        broken = (stable != current) or (current[1] <= 0)
        if prior is not None:
            broken = broken or not (identity["streamline_frame"] == prior[0] + 1 and sdk_frame == prior[1] + 1
                                    and identity["recording_id"] > prior[2])
        if broken:
            if strict_continuity:
                require(stable == current and current[1] > 0,
                        "context/settings/provider changed inside published sequence")
                require(prior is None or (identity["streamline_frame"] == prior[0] + 1 and sdk_frame == prior[1] + 1
                        and identity["recording_id"] > prior[2]),
                        "nonconsecutive provider/SL/recording sequence")
            else:
                if "provider_context_or_recording_chain_changed_mid_sequence" not in reasons:
                    reasons.append("provider_context_or_recording_chain_changed_mid_sequence")
                break
        prior = identity["streamline_frame"], sdk_frame, identity["recording_id"]
        images = frame.get("images")
        require(isinstance(images, list) and 1 <= len(images) <= 15, "unexpected bridge image count")
        physical, charges, charged, payload_bytes = {}, {}, 0, 184
        for row in images:
            name = row.get("name")
            require(name in (FORMATS | AUXILIARY_FORMATS) and name not in physical, "unknown/duplicate image stage")
            fmt, bpp = (FORMATS | AUXILIARY_FORMATS)[name]
            expected_extent = [4, 1] if name == "consumer_word303" else extent
            require(row.get("dxgi_format") == fmt and row.get("bytes_per_pixel") == bpp
                    and row.get("extent") == expected_extent, "image typed layout mismatch")
            if name != "consumer_word303":
                require(row.get("crop_origin") == origin, "image ROI/source frame differs")
            size = expected_extent[0] * expected_extent[1] * bpp
            physical[name] = dict(verify_file(root, row, ordinal, size, verify_payload),
                                  dxgi_format=fmt, bytes_per_pixel=bpp,
                                  source_native_resource_desc=row.get("source_native_resource_desc", {}),
                                  source_state=row.get("source_state"))
            footprint = row.get("copy_footprint", {})
            allocation = uint(footprint.get("committed_buffer_bytes"), "readback allocation")
            require(allocation >= size and allocation % (64 << 10) == 0, "invalid committed readback charge")
            charges[name] = allocation
            charged += allocation
            payload_bytes += size
        native_controls, native_bytes = inspect_native_control_header(root, frame, ordinal, identity, verify_payload)
        payload_bytes += native_bytes
        if native_controls.get("owned_status", {}).get("captured_uint32", 0) != 0:
            if "bridge_owned_raw_capture_status_nonzero" not in reasons:
                reasons.append("bridge_owned_raw_capture_status_nonzero")
        if native_controls["available"]:
            reserved = native_controls["shared_committed_buffer_bytes"]
            if "consumer_word303" in charges:
                require(charges["consumer_word303"] == reserved, "native control shared buffer charge not same as flag")
            else:
                charged += reserved
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
        for name in INPUTS:
            actual = resolved[name].get("source_native_resource_desc", {})
            layout_complete = (isinstance(actual, dict) and actual.get("dimension") == 3
                and actual.get("width") == render[0] and actual.get("height") == render[1]
                and actual.get("depth_or_array_size") == actual.get("mip_levels") == actual.get("sample_count") == 1
                and actual.get("sample_quality") == actual.get("layout") == 0
                and actual.get("dxgi_format") == FORMATS[name][0]
                and type(actual.get("flags")) is int and actual["flags"] in (0, 4)
                and type(resolved[name].get("source_state")) is int and resolved[name]["source_state"] == 64)
            reason = "actual_RR_input_resource_layout_incomplete_or_has_uncaptured_extent"
            if not layout_complete and reason not in reasons:
                reasons.append(reason)
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
        flat = frame.get("flat_albedo", {})
        require(isinstance(flat, dict), "invalid flat recovery metadata")
        if flat.get("graph_recorded", False):
            require("recovery_original_normal_roughness" in physical, "flat recovery lacks original geometry payload")
            require(uint(flat.get("roughness_floor"), "flat roughness floor", 1023) > 0, "flat recovery floor is zero")
        scale, scales = provider_radiance_scales(frame)
        result.append({"ordinal": ordinal, "identity": identity, "context_generation": current[1],
                       "sdk_frame_index": sdk_frame, "actual_dispatch_flags": flags,
                       "provider_controls": controls, "provider": provider, "frame_parameters": params,
                       "settings": settings, "inputs": {name: resolved[name] for name in INPUTS},
                       "observations": {name: row for name, row in resolved.items() if name not in INPUTS},
                       "encoding": encoding, "native_control_header": native_controls, "payload_bytes": payload_bytes,
                       "provider_radiance_scale": scale, "provider_radiance_scales": scales, "flat_albedo": flat,
                       "auxiliary_inputs": {name: physical[name] for name in AUXILIARY_FORMATS if name in physical},
                       "skipped_original_dispatches": events})
    if published < MINIMUM_REPLAY_PREFIX_FRAMES:
        reasons.append("replay_prefix_below_64_full_render_frames")
    if commit is None:
        reasons.append("replay_manifest_missing_bridge_commit")
    if provider_hash is None:
        reasons.append("replay_manifest_missing_provider_binary_sha256")
    if policy is None:
        reasons.append("replay_manifest_missing_guide_motion_policy")
    if captured_at is None:
        reasons.append("replay_manifest_missing_capture_time_utc")
    if reset_reason_missing:
        reasons.append("reset_frame_missing_reset_reason")
    # The preserved turn pass writes private RR-only copies. This recorder's
    # input payloads predate that pass, so inspection remains valid but an exact
    # provider replay cannot silently use the unfiltered samples instead.
    if any(frame['settings'].get('turn_colour', {}).get(key, False)
           for frame in result for key in ('enabled', 'brightness')):
        reasons.append('post_turn_RR_input_copies_not_captured')
    eligible = not reasons and verify_payload
    chain_broken = "provider_context_or_recording_chain_changed_mid_sequence" in reasons
    return {"schema": "fsrd-nrd-bridge-replay-inputs-v1", "capture_uuid": manifest.get("capture_uuid"),
            "capture_root": str(root), "published_frames": published, "payload_hashes_verified": verify_payload,
            "captured_domain": stable[0], "full_temporal_replay_eligible": eligible,
            "recording_class": "replay_eligible" if eligible else "inspect_only",
            "inspection": {"identity_and_controls": True,
                           "selector_phase_words_available": any(frame["native_control_header"].get("available")
                                                                 for frame in result),
                           "recorded_control_fields": {frame["native_control_header"]["profile"]:
                                                       frame["native_control_header"]["recorded_fields"]
                                                       for frame in result
                                                       if frame["native_control_header"].get("available")},
                           "roi": {"origin": origin, "extent": extent, "region_mode": manifest.get("region_mode")},
                           "validated_frames": len(result)},
            "chain_continuity": "broken" if chain_broken else "intact",
            "replay_requirements": {"minimum_full_render_prefix_frames": MINIMUM_REPLAY_PREFIX_FRAMES,
                                    "starts_with_actual_sdk_reset": True,
                                    "provider_binary_attestation": True,
                                    "manifest_provenance_fields": ["bridge_commit", "provider_binary_sha256",
                                                                   "guide_motion_policy", "captured_at_utc",
                                                                   "reset_reason_on_reset_frames"]},
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
