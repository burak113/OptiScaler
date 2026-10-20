#!/usr/bin/env python3
"""Small corruption controls for the real native-observation packet reader."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import platform
import struct
import sys
import tempfile
import time
import unittest

import observation_capture_reader as reader


CAPTURE_ID = "11111111-2222-4333-8444-555555555555"


class PacketFixture:
    """A synthetic CPU-written packet, never labelled a real GPU capture."""
    def __init__(self, root, *, recovery=False, count=2, complete=False):
        self.root = Path(root)
        self.manifest = {"schema": "fsrd-nrd-bridge-game-trace-v1", "capture_uuid": CAPTURE_ID,
                         "source": "synthetic_packet_reader_test_not_gpu_capture", "complete": complete,
                         "target_frames": count if complete else count+1, "committed_frames": count,
                         "manifest_published_frames": count, "render_extent": [17,11],
                         "roi": {"origin": [4,5], "extent": [3,2]},
                         "native_observations": {"schema": reader.SCHEMA, "requested": True,
                                                 "default_enabled": False, "capture_only": True}, "frames": []}
        for ordinal in range(count):
            self.manifest["frames"].append(self.make_frame(ordinal, recovery))
        self.save()

    def payload(self, ordinal, name, data):
        relative = f"frames/{ordinal}/{name}.bin"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"file": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def make_frame(self, ordinal, recovery):
        stamp = {"stream_id": 20, "frame": 180+ordinal, "reset_epoch": 5, "resource_epoch": 7, "known": True}
        actual_reset = ordinal == 0
        proof = {key: True for key in ("recorded", "submitted", "cpu_snapshot_immutable", "submission_gate_protected")}
        proof.update({key: False for key in ("invalid", "abandoned", "signal_failed", "ambiguous_submission")})
        proof.update({"fence_expected": 3+ordinal, "fence_completed": 3+ordinal, "pending_signals": 0, "signal_hresult": 0})
        row = {"ordinal": ordinal, "identity": {"domain": 20, "recording_id": 101+ordinal, "streamline_frame": 500+ordinal},
               "context_generation": 7, "sdk_frame_index": 180+ordinal, "context_id": "20:7", "actual_reset": actual_reset,
               "actual_dispatch_flags": 1 if actual_reset else 0,
               "frame_parameters": {"frame_index": 180+ordinal, "streamline_frame": 500+ordinal, "depth_sign": 0x3f800000},
               "provider_radiance_scales": {"specular": 256.0, "diffuse": 16.0},
               "recovery": {"graph_recorded": recovery}, "flat_albedo": {"graph_recorded": False},
               "gpu_submission_verified": True, "cpu_snapshot_immutable": True, "submission_gate_protected": True,
               "ticket_proof": proof, "images": []}
        controls = bytearray(184)
        struct.pack_into("<3I", controls, 0, *(0x3f800000,)*3)
        struct.pack_into("<4I", controls, 168, 17,11,180+ordinal, int(actual_reset))
        row["provider_controls"] = {"wireformat": "ffxDispatchDescDenoiser_native_ABI_suffix_264_184",
                                    "native_dispatch_bytes": 448, "controls_offset": 264, "controls_bytes": 184,
                                    **self.payload(ordinal,"provider_controls",controls)}
        packet = {"schema": reader.SCHEMA, "abi_version": 1, "capture_id": CAPTURE_ID, "stamp": stamp,
                  "recording_id": 101+ordinal, "streamline_frame": 500+ordinal, "actual_reset": actual_reset,
                  "surfaces": {}, "authority": {}, "support": {"version": 1, "valid": False,
                  "reason_bits": 3, "reasons": reader.REASONS.copy()}, "motion_convention": {
                  "units": "full_render_uv", "direction": "previous_minus_current", "jitter": "already_encoded_no_extra_delta",
                  "per_pixel_correspondence": "unknown"}, "provider_depth_sign_float32_bits": 0x3f800000,
                  "alpha_policy": reader.ALPHA, "capture_semantics": reader.SEMANTICS,
                  "unknown": {key: "unavailable_in_synthetic_packet" for key in reader.UNKNOWN_FIELDS}}
        for name, (role,lobe,encodings) in reader.SURFACES.items():
            if name == "depth_validity":
                packet["surfaces"][name] = {"availability": "missing", "reason": "fixture omits native validity"}
                continue
            if name.startswith("selected_rr_") and not recovery:
                surface = copy.deepcopy(packet["surfaces"][name.replace("selected", "raw")])
                surface.update({"role": role, "stage": "actual_selected_resource"})
                packet["surfaces"][name] = surface
                continue
            encoding = min(encodings)
            dxgi,bpp = reader.ENCODINGS[encoding]
            sums = name == "anchor_sums"
            extent, allocation, origin = ([8,1],[8,1],[0,0]) if sums else ([3,2],[19,13],[4,5])
            image_extent = [32,1] if sums else extent.copy()
            image_bpp = 1 if sums else bpp
            rowbytes = image_extent[0]*image_bpp
            footprint = {"offset": 0, "row_pitch": 32 if sums else 256, "extent": image_extent+[1],
                         "dxgi_format": dxgi, "rows": image_extent[1], "row_bytes": rowbytes,
                         "requested_buffer_bytes": (image_extent[1]-1)*(32 if sums else 256)+rowbytes,
                         "committed_buffer_bytes": 65536, "cpu_crop_origin_in_readback": [0,0]}
            if sums:
                data = struct.pack("<8I", 0xffffffff, 2, 0, 3, 17, 0, 0, 0)
            elif bpp == 8:
                # All three special alpha words survive as uninterpreted bytes.
                data = b"".join(struct.pack("<4H",0x3c00,0x8000,0x7e35,a) for a in (0x7e21,0x7d01,0x8000)*2)
            else:
                data = bytes([ordinal+7]) * (rowbytes*image_extent[1])
            image = {"name": name, "dxgi_format": dxgi, "source_extent": [32,1] if sums else allocation.copy(),
                     "extent": image_extent, "crop_origin": origin.copy(), "bytes_per_pixel": image_bpp,
                     "storage": "original_little_endian_gpu_words", "copy_footprint": footprint,
                     **self.payload(ordinal,name,data)}
            row["images"].append(image)
            packet["surfaces"][name] = {"availability": "present", "role": role, "lobe": lobe,
                "stamp": copy.deepcopy(stamp), "resource_id": len(row["images"]), "image": name,
                "stage": "synthetic_observation_contract_probe", "dxgi_format": dxgi, "encoding": encoding,
                "allocation_extent": allocation, "active_extent": [8,1] if sums else [17,11], "captured_extent": extent,
                "crop_origin": origin, "coordinate_space": reader.COORDINATES,
                "payload_layout": {"byte_offset": 0, "row_pitch": extent[0]*bpp, "row_bytes": extent[0]*bpp,
                                   "bytes": extent[0]*extent[1]*bpp}, "copy_footprint": copy.deepcopy(footprint),
                "native_texture_row_pitch": None, "native_texture_row_pitch_reason": "opaque_native_texture_layout",
                "scale": {"known": lobe != 1, "provider_multiplier": 256 if lobe == 3 else (16 if lobe == 2 else 0),
                          "stored_multiplier": 1 if lobe != 1 else 0}}
        for lobe in ("specular", "diffuse"):
            raw,selected = [packet["surfaces"][key+"_rr_"+lobe] for key in ("raw","selected")]
            packet["authority"][lobe] = {"selection_path": "lobe_recovery" if recovery else "raw_rr",
                "selection_path_value": 2 if recovery else 1, "selection_authority": 2 if recovery else 1,
                "raw_resource_id": raw["resource_id"], "selected_resource_id": selected["resource_id"],
                "equality_guard": 1, "raw_authority_valid": not recovery, "raw_edit_eligible": False,
                "equality_status": "original_words_compared_after_protected_fence_snapshot",
                "authority_validation_reason": 20 if recovery else 0}
        row["native_observations"] = packet
        return row

    def save(self):
        for row in self.manifest["frames"]:
            (self.root / f"frames/{row['ordinal']}/frame.json").write_text(json.dumps(row,indent=2)+"\n",encoding="utf-8")
        (self.root / "capture.json").write_text(json.dumps(self.manifest,indent=2)+"\n",encoding="utf-8")


class CaptureReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="astra09_reader_")
        self.addCleanup(self.temp.cleanup)
        self.fixture = PacketFixture(Path(self.temp.name)/"capture")
        self.root = self.fixture.root
        self.row = self.fixture.manifest["frames"][0]
        self.packet = self.row["native_observations"]

    def reject(self, pattern):
        self.fixture.save()
        with self.assertRaisesRegex(reader.CaptureValidationError, pattern):
            reader.validate_capture(self.root)

    def test_partial_prefix_accepts_raw_authority_without_edit_permission(self):
        result = reader.validate_capture(self.root)
        self.assertTrue(result["valid"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["published_frames"],2)
        self.assertTrue(result["frames"][0]["authority"]["specular"]["raw_authority_valid"])
        self.assertFalse(result["frames"][0]["authority"]["specular"]["raw_edit_eligible"])
        self.assertIn("depth_validity",result["frames"][0]["missing_observations"])
        self.assertFalse(result["gpu_executed_by_validator"])

    def test_complete_capture(self):
        self.fixture.manifest.update({"complete": True,"target_frames": 2})
        self.fixture.save()
        self.assertTrue(reader.validate_capture(self.root)["complete"])

    def test_recovery_equal_words_remains_protected(self):
        fixture = PacketFixture(Path(self.temp.name)/"protected",recovery=True,count=1)
        authority = reader.validate_capture(fixture.root)["frames"][0]["authority"]["diffuse"]
        self.assertTrue(authority["equal_words"])
        self.assertFalse(authority["raw_authority_valid"])

    def test_equality_cannot_synthesize_unknown_authority(self):
        for value in self.packet["authority"].values():
            value.update({"selection_path": "unknown", "selection_path_value": 0,"selection_authority": 0,
                          "raw_authority_valid": False,"authority_validation_reason": 19})
        self.fixture.save()
        self.assertTrue(reader.validate_capture(self.root)["valid"])
        self.packet["authority"]["diffuse"]["raw_authority_valid"] = True
        self.reject("synthesized authority")

    def test_wrong_origin(self):
        self.packet["surfaces"]["raw_rr_specular"]["crop_origin"][0] += 1
        self.reject("crop origin")

    def test_stale_surface_epoch(self):
        self.packet["surfaces"]["raw_rr_diffuse"]["stamp"]["reset_epoch"] -= 1
        self.reject("stale surface stamp")

    def test_stale_sequence_epoch_even_if_each_surface_is_relabelled(self):
        packet = self.fixture.manifest["frames"][1]["native_observations"]
        packet["stamp"]["reset_epoch"] = 4
        for surface in packet["surfaces"].values():
            if "stamp" in surface: surface["stamp"]["reset_epoch"] = 4
        self.reject("nonchronological")

    def test_wrong_scale(self):
        self.packet["surfaces"]["physical_source_diffuse"]["scale"]["provider_multiplier"] = 256
        self.reject("wrong lobe/provider scale")

    def test_wrong_lobe(self):
        self.packet["surfaces"]["raw_rr_specular"]["lobe"] = 2
        self.reject("wrong role/lobe")

    def test_boolean_is_not_a_numeric_authority_enum(self):
        self.packet["authority"]["specular"]["selection_authority"] = True
        self.reject("invalid integer")

    def test_malformed_nested_structure_fails_closed(self):
        self.packet["authority"]["specular"] = []
        self.reject("malformed capture structure")

    def test_missing_carry_words_even_with_matching_rehashed_short_file(self):
        image = next(x for x in self.row["images"] if x["name"] == "anchor_sums")
        path = self.root/image["file"]
        data = path.read_bytes()[:16]; path.write_bytes(data)
        image.update({"bytes": 16,"sha256": hashlib.sha256(data).hexdigest(),"extent": [16,1],"source_extent": [16,1]})
        self.reject("anchor sums")

    def test_missing_role_must_be_explicit(self):
        del self.packet["surfaces"]["anchor_sums"]
        self.reject("role declaration omitted")

    def test_invalid_support_reason_cannot_disappear(self):
        self.packet["support"]["reason_bits"] = 1
        self.reject("invalid-support reason")

    def test_invented_support(self):
        self.packet["support"]["valid"] = True
        self.reject("invented support")

    def test_edit_permission_cannot_follow_raw_authority_without_support(self):
        self.packet["authority"]["specular"]["raw_edit_eligible"] = True
        self.reject("edit despite invalid")

    def test_gpu_pitch_cannot_index_tight_disk_payload(self):
        self.packet["surfaces"]["raw_rr_specular"]["payload_layout"]["row_pitch"] = 256
        self.reject("not declared tight")

    def test_invalid_copy_footprint(self):
        image = self.row["images"][0]
        image["copy_footprint"]["requested_buffer_bytes"] = 1
        self.reject("copy footprint")

    def test_original_payload_hash_corruption(self):
        path = self.root/self.row["images"][0]["file"]
        data = bytearray(path.read_bytes()); data[0] ^= 1; path.write_bytes(data)
        self.reject("SHA-256 mismatch")

    def test_frame_json_cannot_disagree_with_manifest(self):
        path = self.root/"frames/0/frame.json"
        row = json.loads(path.read_text()); row["sdk_frame_index"] += 1
        path.write_text(json.dumps(row),encoding="utf-8")
        with self.assertRaisesRegex(reader.CaptureValidationError,"frame.json differs"):
            reader.validate_capture(self.root)

    def test_path_traversal_rejected_before_read(self):
        self.row["images"][0]["file"] = "../outside.bin"
        self.reject("unsafe capture path")

    def test_symlink_to_external_file_rejected(self):
        image = self.row["images"][0]
        path = self.root/image["file"]
        external = Path(self.temp.name)/"outside.bin"
        external.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(external)
        self.reject("escapes folder")

    def test_wrong_capture_id(self):
        self.packet["capture_id"] = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        self.reject("capture identity")

    def test_provider_controls_frame_mismatch_with_valid_file_hash(self):
        descriptor = self.row["provider_controls"]
        path = self.root/descriptor["file"]
        data = bytearray(path.read_bytes()); struct.pack_into("<I",data,176,179); path.write_bytes(data)
        descriptor["sha256"] = hashlib.sha256(data).hexdigest()
        self.reject("provider control words")

    def test_duplicate_json_keys_are_not_silently_accepted(self):
        path = self.root/"capture.json"
        data = path.read_text(); path.write_text(data.replace('"complete": false','"complete": true, "complete": false'))
        with self.assertRaisesRegex(reader.CaptureValidationError,"duplicate JSON key"):
            reader.validate_capture(self.root)

    def test_cli_will_not_write_inside_capture(self):
        target = self.root/"new_report.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(reader.main([str(self.root),"--output",str(target)]),1)
        self.assertFalse(target.exists())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Directory for the execution receipt and test log")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    log = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CaptureReaderTests)
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    sys.stdout.write(log.getvalue())
    exit_status = 0 if result.wasSuccessful() else 1
    if args.output is not None:
        args.output.mkdir(parents=True, exist_ok=True)
        sources = (Path(reader.__file__).resolve(), Path(__file__).resolve())
        receipt = {
            "schema": "fsrd-native-observation-reader-tests-v1",
            "command": [sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)],
            "python": platform.python_version(),
            "platform": platform.platform(),
            "elapsed_seconds": time.perf_counter()-started,
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "passed": result.wasSuccessful(),
            "exit_status": exit_status,
            "gpu_executed": False,
            "fixtures": "synthetic CPU-written packets; no native GPU capture or quality acceptance",
            "sources_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            "log": "observation_capture_reader_tests.txt",
        }
        (args.output/"observation_capture_reader_tests.txt").write_text(log.getvalue(), encoding="utf-8")
        (args.output/"observation_capture_reader_execution.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
