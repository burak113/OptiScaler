"""Adversarial filesystem/provenance contracts for the published survey loader."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_nrd_survey_dataset import (
    ContractError, PREPASS_SHA256, analysis_sets, index_capture, load_image, payload_path, published_frames, roles_from_header, writable_output,
)


class DatasetContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name) / ("a" * 32)
        self.folder.mkdir()
        data = b"\x00\x3c\x00\x40\x00\x42\x00\x44"  # exact RG16F [1,2], [3,4]
        path = self.folder / "frames/0/test.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        self.image = {"name": "test", "file": "frames/0/test.bin", "extent": [2, 1],
                      "bytes": 8, "bytes_per_pixel": 4, "channels": 2, "dxgi_format": 34,
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "storage": "original_little_endian_gpu_words"}
        self.frame = {"ordinal": 0, "list_id": 7, "command_list": 123,
                      "cpu_snapshot_immutable": True, "gpu_submission_verified": True,
                      "submission_gate_protected": True, "images": [self.image],
                      "ticket_proof": {"submitted": True, "pending_signals": 0,
                                       "fence_completed": 1, "fence_expected": 1}}
        self.manifest = {"capture_uuid": self.folder.name, "schema": "fsrd-frame-survey-v1",
                         "manifest_published_frames": 1, "frames": [self.frame],
                         "payload_ordinal_unit": "command_list_recording"}
        self.save()

    def tearDown(self):
        self.temporary.cleanup()

    def save(self):
        (self.folder / "capture.json").write_text(json.dumps(self.manifest))
        (self.folder / "frames/0/frame.json").write_text(json.dumps(self.frame))

    def test_exact_rg16_shape_words_and_readonly(self):
        capture = index_capture(self.folder, {})
        image = capture["images"][0]
        array = load_image(capture, image)
        self.assertEqual(array.shape, (1, 2, 2))
        self.assertEqual(array.tolist(), [[[1.0, 2.0], [3.0, 4.0]]])
        self.assertFalse(array.flags.writeable)
        self.assertFalse(capture["consecutive_rendered_frames_proved"])
        self.assertFalse(capture["camera_snapshot_present"])
        del array

    def test_only_published_files_touched(self):
        private = deepcopy(self.frame)
        private["ordinal"] = 1
        private["images"][0]["file"] = "frames/1/absent.bin"
        self.manifest["frames"].append(private)
        self.save()
        self.assertEqual(len(index_capture(self.folder, {})["images"]), 1)

    def test_requested_capture_has_no_payload_reads(self):
        self.manifest["manifest_published_frames"] = 0
        self.save()
        (self.folder / "frames/0/test.bin").unlink()
        self.assertEqual(index_capture(self.folder, {})["images"], [])

    def test_missing_publication_bound_rejected(self):
        del self.manifest["manifest_published_frames"]
        with self.assertRaises(ContractError):
            published_frames(self.manifest)

    def test_duplicate_or_missing_ordinals_rejected(self):
        self.manifest["frames"].append(deepcopy(self.frame))
        with self.assertRaises(ContractError):
            published_frames(self.manifest)
        self.manifest["frames"] = []
        with self.assertRaises(ContractError):
            published_frames(self.manifest)

    def test_ambiguous_or_incomplete_gpu_ticket_rejected(self):
        for key in ("invalid", "abandoned", "ambiguous_submission", "signal_failed"):
            other = deepcopy(self.manifest)
            other["frames"][0]["ticket_proof"][key] = True
            with self.assertRaises(ContractError):
                published_frames(other)
        self.frame["ticket_proof"]["fence_completed"] = 0
        with self.assertRaises(ContractError):
            published_frames(self.manifest)

    def test_zero_fence_cannot_fabricate_gpu_completion(self):
        self.frame["ticket_proof"].update(fence_completed=0, fence_expected=0)
        with self.assertRaises(ContractError):
            published_frames(self.manifest)

    def test_mutable_or_unsubmitted_rows_rejected(self):
        for key in ("cpu_snapshot_immutable", "gpu_submission_verified", "submission_gate_protected"):
            other = deepcopy(self.manifest)
            other["frames"][0][key] = False
            with self.assertRaises(ContractError):
                published_frames(other)

    def test_path_traversal_absolute_and_cross_ordinal_rejected(self):
        for file in ("../outside.bin", "/outside.bin", "frames/1/test.bin", "frames\\0\\test.bin"):
            with self.assertRaises(ContractError):
                payload_path(self.folder, dict(self.image, file=file), 0)

    def test_corrupt_hash_or_length_rejected(self):
        target = self.folder / self.image["file"]
        target.write_bytes(b"\x00" * 8)
        with self.assertRaises(ContractError):
            index_capture(self.folder, {})
        target.write_bytes(b"\x00")
        with self.assertRaises(ContractError):
            index_capture(self.folder, {})

    def test_durable_frame_cannot_disagree(self):
        (self.folder / "frames/0/frame.json").write_text("{}")
        with self.assertRaises(ContractError):
            index_capture(self.folder, {})

    def test_duplicate_payload_name_rejected(self):
        self.frame["images"].append(deepcopy(self.image))
        self.save()
        with self.assertRaises(ContractError):
            index_capture(self.folder, {})

    def test_exact_list_snapshot_join_not_resource_only(self):
        self.manifest["snapshots"] = [
            {"list_id": 8, "key": "test", "resource": 9, "writer_local_pass": 1},
            {"list_id": 7, "key": "test", "resource": 9, "writer_local_pass": 2}]
        self.manifest["tags"] = [
            {"list_id": 8, "snapshot_key": "test", "name": "MotionVectors", "resource": 9},
            {"list_id": 7, "snapshot_key": "test", "name": "MotionVectors", "resource": 9,
             "source": "current_Streamline_tag_call"}]
        self.save()
        capture = index_capture(self.folder, {})
        self.assertEqual([row["writer_local_pass"] for row in capture["snapshots"]], [2])
        self.assertEqual(capture["tags"][0]["payloads"], [])
        self.assertEqual(capture["tags"][1]["payloads"], ["frames/0/test.bin"])
        self.assertEqual(capture["tags"][1]["source_scope"], "Streamline")

    def test_typeless_depth_needs_explicit_interpretation(self):
        import numpy as np
        data = np.array([1.0, 2.0], dtype="<f4").tobytes()
        (self.folder / self.image["file"]).write_bytes(data)
        self.image.update(dxgi_format=39, channels=1, sha256=hashlib.sha256(data).hexdigest())
        self.save()
        capture = index_capture(self.folder, {})
        with self.assertRaises(ContractError):
            load_image(capture, capture["images"][0])
        array = load_image(capture, capture["images"][0], "r32f")
        self.assertEqual(array.tolist(), [[[1.0], [2.0]]])
        del array

    def test_replaced_payload_after_index_rejected(self):
        capture = index_capture(self.folder, {})
        (self.folder / self.image["file"]).write_bytes(b"\x00" * 8)
        with self.assertRaises(ContractError):
            load_image(capture, capture["images"][0])

    def test_production_roles_require_full_sha(self):
        roles = roles_from_header()
        self.assertEqual(len(roles), 10)
        self.assertNotIn("ec37e0d8", roles)
        self.assertIn("Recon", roles.values())

    def test_protected_game_and_capture_export_rejected(self):
        for name in ("F:/Ultra Yedek 2/overwrite/export.json",
                     "F:/SteamLibrary/steamapps/common/Cyberpunk 2077/export.json"):
            with self.assertRaises(ContractError):
                writable_output(Path(name))

    def test_replay_map_keeps_writer_time_and_reversed_consumer_order(self):
        binding = lambda offset, resource, fmt: {"offset_from_lowest_observed_descriptor": offset,
                                               "resource": resource, "view_format": fmt}
        recon = {"role": "Recon", "list_id": 7, "local_pass": 20,
                 "root1_srv": [binding(i, 10 + i, f) for i, f in enumerate((10, 10, 24, 41))],
                 "root5_uav": [binding(0, 30, 10), binding(1, 31, 10)]}
        consumer = {"role": "Consumer", "list_id": 7, "local_pass": 40,
                    "root5_uav": [binding(0, 50, 10), binding(1, 51, 10)]}
        snapshot = lambda resource, writer, file, owner=7: {"list_id": owner, "resource": resource,
                                                            "writer_local_pass": writer, "payloads": [file]}
        capture = {"nrd_passes": [recon, consumer], "tags": [], "snapshots": [
            snapshot(10, 15, "before"), snapshot(10, 25, "later_wrong"),
            snapshot(11, 15, "other_list_wrong", owner=8),
            snapshot(30, 20, "recon_spec"), snapshot(31, 20, "recon_diff"),
            snapshot(50, 40, "consumer_diff"), snapshot(51, 40, "consumer_spec")]}
        result = analysis_sets(capture)[0]
        self.assertEqual(result["signals"]["input_spec"]["payloads"], ["before"])
        self.assertEqual(result["signals"]["input_diff"]["payloads"], [])
        self.assertEqual(result["signals"]["consumer_diff"]["binding"]["resource"], 50)
        self.assertEqual(result["signals"]["consumer_spec"]["binding"]["resource"], 51)
        self.assertTrue(result["native_recon_pair_complete"])
        self.assertFalse(result["temporal_RR_replay_ready"])
        self.assertIn("contamination_possible", result["signals"]["consumer_spec"]["content_scope"])

    def test_incomplete_recon_profile_cannot_receive_named_signal_contract(self):
        capture = {"nrd_passes": [{"role": "Recon", "root1_srv": [], "root5_uav": [],
                                   "list_id": 7, "local_pass": 20}], "snapshots": [], "tags": []}
        self.assertEqual(analysis_sets(capture), [])

    def test_viewz_magnitude_requires_exact_prepass_shader_and_writer(self):
        binding = lambda offset, resource, fmt: {"offset_from_lowest_observed_descriptor": offset,
                                               "resource": resource, "view_format": fmt}
        recon = {"role": "Recon", "list_id": 7, "local_pass": 20,
                 "root1_srv": [binding(i, 10 + i, f) for i, f in enumerate((10, 10, 24, 41))],
                 "root5_uav": [binding(0, 30, 10), binding(1, 31, 10)]}
        prepass = {"role": "PrePass", "list_id": 7, "local_pass": 25,
                   "shader_sha256": PREPASS_SHA256, "root5_uav": [binding(2, 40, 41)]}
        capture = {"nrd_passes": [recon, prepass], "tags": [], "snapshots": [
            {"list_id": 7, "resource": 40, "writer_local_pass": 25, "payloads": ["absolute_viewz"]}]}
        named = analysis_sets(capture)[0]["signals"]["view_z_magnitude"]
        self.assertEqual(named["payloads"], ["absolute_viewz"])
        self.assertIn("original ViewZ sign is lost", named["semantic_proof"]["scope"])
        prepass["shader_sha256"] = "a" * 64
        self.assertNotIn("view_z_magnitude", analysis_sets(capture)[0]["signals"])


if __name__ == "__main__":
    unittest.main()
