"""CPU parser tests for v2 B8/native words versus distinct owned status.

Controlled CPU byte files only. No capture manifest, GPU observation, provider
witness, command submission, LoadLibrary or SDK call is fabricated here.
"""
from pathlib import Path
import copy
import hashlib
import json
import os
import struct

from fsrd_nrd_trace_replay import inspect_native_control_header


def main():
    output = Path(os.environ.get("FSRD_GPU_TEST_OUTPUT", "F:/FSRD/sol_batch/15d-guides/control-header-cpu"))
    folder = output / "frames/0"
    folder.mkdir(parents=True, exist_ok=True)
    offsets = [456, 460, 472, 476, 516, 520, 576, 580]
    values = [0x51000000 + offset for offset in offsets]

    def payload(name, data):
        (folder / name).write_bytes(data)
        return {"file": "frames/0/" + name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    header = {"available": True, "contract_version": 2, "profile": "B_PrePass",
              "recording_id": 2, "streamline_frame": 3, "bridge_frame": 4,
              "dxgi_format": 0, "bytes_per_pixel": 1, "extent": [32, 1], "source_state": 0,
              "source_native_resource_desc": {"dimension": 1, "width": 1536},
              "copy_footprint": {"committed_buffer_bytes": 0}, "shared_committed_buffer_bytes": 65536,
              "readback_allocation_shared_with": "private_encoding_flag_reserved_readback",
              "words": [{"native_byte_offset": offset, "source_buffer_byte_offset": offset,
                         "payload_byte_offset": 4 * i, "captured_uint32": values[i]} for i, offset in enumerate(offsets)]}
    header.update(payload("native_control_header.bin", struct.pack("<8I", *values)))
    status = {"available": True, "origin": "bridge_generated_raw_capture_validation; NOT_a_native_operand",
              "source_buffer_byte_offset": 0, "readback_buffer_byte_offset": 36,
              "dxgi_format": 0, "bytes_per_pixel": 1, "extent": [4, 1], "captured_uint32": 0,
              "copy_footprint": {"committed_buffer_bytes": 0},
              "readback_allocation_shared_with": "private_encoding_flag_reserved_readback"}
    status.update(payload("owned_raw_status.bin", struct.pack("<I", 0)))
    header["owned_status"] = status
    frame = {"native_control_header": header, "sdk_frame_index": 4}
    identity = {"recording_id": 2, "streamline_frame": 3}
    checks = []

    def parse(value):
        return inspect_native_control_header(output, value, 0, identity, True)

    got, size = parse(frame)
    assert size == 36 and got["payload"]["bytes"] == 32 and got["owned_status"]["payload"]["bytes"] == 4
    assert [word["native_byte_offset"] for word in got["words"]] == offsets
    assert got["owned_status"]["source_buffer_byte_offset"] == 0
    checks.append("CPU_B8_payload_and_separate_status_not_native_operand")

    def rejected(name, mutate):
        value = copy.deepcopy(frame)
        mutate(value["native_control_header"])
        try:
            parse(value)
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError("invalid control header accepted: " + name)

    rejected("B8_missing_520", lambda h: h["words"].pop(5))
    rejected("B8_wrong_520_offset", lambda h: h["words"][5].update(native_byte_offset=512))
    rejected("B8_native_value_not_CPU_payload", lambda h: h["words"][5].update(captured_uint32=0))
    rejected("B8_status_unavailable", lambda h: h["owned_status"].update(available=False))
    rejected("B8_status_not_a_native_operand", lambda h: h["owned_status"].update(origin="native_b6"))
    rejected("B8_status_source_offset_exact0", lambda h: h["owned_status"].update(source_buffer_byte_offset=520))
    rejected("B8_status_readback_offset_exact36", lambda h: h["owned_status"].update(readback_buffer_byte_offset=32))
    rejected("B8_status_code_not_CPU_payload", lambda h: h["owned_status"].update(captured_uint32=1))
    rejected("B8_status_4bytes", lambda h: h["owned_status"].update(bytes=32))
    rejected("B8_status_no_second_allocation_charge", lambda h: h["owned_status"]["copy_footprint"].update(committed_buffer_bytes=65536))
    rejected("B8_source_range_bound", lambda h: h["source_native_resource_desc"].update(width=580))
    rejected("B8_same_recording", lambda h: h.update(recording_id=5))
    for code in (1, 2, 4, 8, 16, 31):
        value = copy.deepcopy(frame)
        value["native_control_header"]["owned_status"].update(payload("owned_raw_status.bin", struct.pack("<I", code)))
        value["native_control_header"]["owned_status"]["captured_uint32"] = code
        got, size = parse(value)
        assert got["owned_status"]["captured_uint32"] == code and size == 36
        checks.append("CPU_owned_status_raw_bits_" + str(code))
    status.update(payload("owned_raw_status.bin", struct.pack("<I", 0)))
    legacy = copy.deepcopy(frame)
    legacy_header = legacy["native_control_header"]
    legacy_header["contract_version"] = 1
    legacy_header.pop("owned_status")
    legacy_header["words"].pop(5)
    for i, word in enumerate(legacy_header["words"]):
        word["payload_byte_offset"] = 4 * i
    legacy_header["extent"] = [28, 1]
    legacy_header.update(payload("legacy_native_control_header.bin", struct.pack("<7I", *[v for i, v in enumerate(values) if i != 5])))
    got, size = parse(legacy)
    assert size == 28 and got["owned_status"]["available"] is False
    assert "captured_uint32" not in got["owned_status"]
    checks.append("legacy_v1_B7_preserved_status_UNKNOWN_not_zero")
    result = {"status": "PASS", "checks": len(checks), "cases": checks,
              "scope": "controlled CPU parser byte files only; no actual capture/provider/GPU proof",
              "compiler_executed": False, "GPU_executed": False, "actual_sdk_dispatches": 0}
    (output / "control-header-cpu-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
