"""Adversarial replay-contract checks on a copy of an actual recorder fixture.

Mutations are negative contract controls, not alternative game observations.
Source captures are read only and only their published prefix is copied.
"""
from pathlib import Path
import copy
import json
import shutil
from fsrd_nrd_trace_replay import inspect_capture


def exercise(source, output):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads((source / "capture.json").read_text(encoding="utf-8-sig"))
    count = original["manifest_published_frames"]
    assert count == 2
    for frame in original["frames"][:count]:
        extras = [frame["native_control_header"]] if frame.get("native_control_header", {}).get("available") else []
        status = frame.get("native_control_header", {}).get("owned_status", {})
        if status.get("available"):
            extras.append(status)
        for row in frame["images"] + [frame["provider_controls"]] + extras:
            dst = output / row["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / row["file"], dst)
    checks = []

    def write(value):
        (output / "capture.json").write_text(json.dumps(value) + "\n", encoding="utf-8")

    def rejected(name, mutate):
        value = copy.deepcopy(original)
        mutate(value)
        write(value)
        try:
            inspect_capture(output)
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError("invalid trace accepted: " + name)

    write(original)
    baseline = inspect_capture(output)
    assert baseline["published_frames"] == 2 and baseline["payload_hashes_verified"]
    checks.append("actual_fenced_recorder_prefix_verified")
    assert baseline["full_temporal_replay_eligible"] is False
    assert "actual_provider_binary_attestation_unavailable" in baseline["ineligibility_reasons"]
    checks.append("CPU_provider_adapter_never_signed_replay_eligible")
    assert inspect_capture(output, verify_payload=False)["full_temporal_replay_eligible"] is False
    checks.append("unverified_payloads_not_replay_eligible")
    private = copy.deepcopy(original)
    private["frames"].append({"ordinal": 2, "images": [{"file": "../../forbidden.bin"}]})
    write(private)
    assert inspect_capture(output)["published_frames"] == 2
    checks.append("unpublished_forensic_rows_never_read")
    roi = copy.deepcopy(original)
    roi["region_mode"] = "square"
    write(roi)
    assert "cropped_inputs_cannot_reconstruct_full_frame_temporal_history" in inspect_capture(output)["ineligibility_reasons"]
    checks.append("ROI_inspect_only_not_complete_replay")
    assert baseline["frames"][0]["native_control_header"]["profile"] == "A_Recon_direct"
    assert baseline["frames"][1]["native_control_header"]["profile"] == "B_PrePass"
    checks.append("actual_postfence_native_control_words_profiled")
    rejected("A_zero_header_not_B_proof", lambda m: m["frames"][0]["native_control_header"].update(profile="B_PrePass"))
    rejected("native_control_unavailable_with_payload", lambda m: m["frames"][0]["native_control_header"].update(available=False))
    rejected("native_control_wrong_frame", lambda m: m["frames"][0]["native_control_header"].update(bridge_frame=1))
    rejected("native_control_wrong_native_offset", lambda m: m["frames"][0]["native_control_header"]["words"][0].update(native_byte_offset=576))
    rejected("native_control_wrong_private_alignment", lambda m: m["frames"][0]["native_control_header"]["words"][0].update(source_buffer_byte_offset=1))
    rejected("native_control_decoded_value_not_payload", lambda m: m["frames"][0]["native_control_header"]["words"][0].update(captured_uint32=0))
    rejected("native_control_wrong_size", lambda m: m["frames"][0]["native_control_header"].update(bytes=28))
    if original["frames"][1]["native_control_header"].get("contract_version") == 2:
        rejected("owned_status_cannot_be_native_operand", lambda m: m["frames"][1]["native_control_header"]["owned_status"].update(origin="native_b6"))
        rejected("owned_status_missing_B_v2", lambda m: m["frames"][1]["native_control_header"]["owned_status"].update(available=False))
        rejected("owned_status_wrong_private_offset", lambda m: m["frames"][1]["native_control_header"]["owned_status"].update(source_buffer_byte_offset=520))
        rejected("owned_status_decoded_value_not_payload", lambda m: m["frames"][1]["native_control_header"]["owned_status"].update(captured_uint32=1))
    rejected("native_control_double_allocation_charge", lambda m: m["frames"][0]["native_control_header"]["copy_footprint"].update(committed_buffer_bytes=65536))
    for field, value in (("width", 256), ("mip_levels", 2), ("flags", 8)):
        incomplete_layout = copy.deepcopy(original)
        incomplete_layout["frames"][0]["images"][0]["source_native_resource_desc"][field] = value
        write(incomplete_layout)
        assert "actual_RR_input_resource_layout_incomplete_or_has_uncaptured_extent" in inspect_capture(output)["ineligibility_reasons"]
        checks.append("input_GPU_description_" + field + "_inspect_only")
    rejected("checkerboard_flags_outside_actual_signals", lambda m: m["frames"][0]["provider"].update(checkerboard_signal_flags=1))
    rejected("checkerboard_origin_not_binary", lambda m: m["frames"][0]["provider"].update(diffuse_checkerboard_origin=2))
    rejected("checkerboard_create_flag_changed_in_context", lambda m: m["frames"][1]["provider"].update(checkerboard_signal_flags=0))
    missing_cb = copy.deepcopy(original)
    for frame in missing_cb["frames"][:count]:
        for key in ("checkerboard_signal_flags", "diffuse_checkerboard_origin", "specular_checkerboard_origin"):
            del frame["provider"][key]
    write(missing_cb)
    assert "actual_checkerboard_create_and_signal_controls_unavailable" in inspect_capture(output)["ineligibility_reasons"]
    checks.append("older_missing_checkerboard_controls_inspect_only")
    rejected("mixed_domain", lambda m: m["frames"][1]["identity"].update(domain=22))
    rejected("zero_recording_generation", lambda m: m["frames"][0]["identity"].update(recording_generation=0))
    rejected("SL_gap", lambda m: m["frames"][1]["identity"].update(streamline_frame=123))
    rejected("context_change", lambda m: m["frames"][1].update(context_generation=99))
    rejected("settings_hash_mismatch", lambda m: m["frames"][0]["settings"].update(native_material_guides=True))
    rejected("actual_controls_frame_mismatch", lambda m: m["frames"][0].update(sdk_frame_index=123))
    rejected("missing_actual_RESET_proof", lambda m: m["frames"][0].update(actual_reset=False))
    rejected("uncommitted_output", lambda m: m["frames"][0].update(output_committed=False))
    rejected("missing_submission_gate", lambda m: m["frames"][0]["ticket_proof"].update(submission_gate_protected=False))
    rejected("ambiguous_submission", lambda m: m["frames"][0]["ticket_proof"].update(ambiguous_submission=True))
    rejected("fence_not_completed", lambda m: m["frames"][0]["ticket_proof"].update(fence_completed=0))
    rejected("repeated_submission_fence", lambda m: m["frames"][0]["ticket_proof"].update(fence_expected=2))
    rejected("device_removed_fence_sentinel", lambda m: m["frames"][0]["ticket_proof"].update(fence_completed=(1 << 64) - 1))
    rejected("failed_signal_hresult", lambda m: m["frames"][0]["ticket_proof"].update(signal_hresult=-1))
    rejected("forbidden_native_output", lambda m: m["frames"][0]["images"][0].update(name="native_nrd_specular"))
    rejected("wrong_typed_format", lambda m: m["frames"][0]["images"][0].update(dxgi_format=28))
    rejected("wrong_payload_size", lambda m: m["frames"][0]["images"][0].update(bytes=1))
    rejected("payload_path_traversal", lambda m: m["frames"][0]["images"][0].update(file="frames/0/../../forbidden.bin"))
    rejected("cross_frame_payload", lambda m: m["frames"][0]["images"][0].update(file="frames/1/input_specular.bin"))
    rejected("cyclic_alias", lambda m: m["frames"][0]["roles"].update(raw_rr_specular="selected_rr_specular"))
    rejected("encoded_stage_not_raw_alias", lambda m: m["frames"][0]["roles"].update(encoded_commit_specular="raw_rr_specular"))
    rejected("native_source_word_not_private_sink", lambda m: m["frames"][0]["encoding"].update(native_source_word=37))
    rejected("native_flag_false_with_payload", lambda m: m["frames"][0]["encoding"].update(native_flag_captured=False))
    rejected("invented_native_skip_payload", lambda m: m["frames"][0]["skipped_original_dispatches"][0].update(native_output_payload=True))
    rejected("skip_bound", lambda m: m["frames"][0].update(skipped_original_dispatches=[m["frames"][0]["skipped_original_dispatches"][0]] * 65))
    write(original)
    row = original["frames"][0]["images"][0]
    path = output / row["file"]
    unchanged = path.read_bytes()
    path.write_bytes(bytes([unchanged[0] ^ 1]) + unchanged[1:])
    try:
        inspect_capture(output)
    except ValueError as error:
        assert "SHA-256" in str(error)
        checks.append("corrupt_payload_hash")
    else:
        raise AssertionError("corrupt payload accepted")
    finally:
        path.write_bytes(unchanged)
    write(original)
    assert inspect_capture(output)["published_frames"] == count
    checks.append("negative_controls_restore_unchanged_source_contract")
    return {"status": "PASS", "checks": len(checks), "cases": checks,
            "scope": "actual recorder fixture plus adversarial offline metadata/payload mutations; no SDK/IQ claim"}
