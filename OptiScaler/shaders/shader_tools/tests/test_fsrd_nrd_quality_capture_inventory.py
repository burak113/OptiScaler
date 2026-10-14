"""CPU-only publication and comparison-scope tests; no binary pixels or GPU jobs."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import fsrd_nrd_quality_capture_inventory as inventory


def camera():
    return dict(view=[1.0]*16, projection=[2.0]*16, jitter=[0.25, -0.25],
                camera_delta=[0.0, 0.0, 0.0], motion_vector_scale=[1.0, 1.0], depth_bounds=[0.01, 100.0])


class PublicationTests(unittest.TestCase):
    def test_publication_slice_excludes_unpublished_frame(self):
        document=dict(manifest_published_frames=1, frames=[dict(ordinal=0), dict(ordinal=1)])
        frames, error=inventory.published_frames(document)
        self.assertEqual(frames, [dict(ordinal=0)])
        self.assertIsNone(error)

    def test_no_legacy_or_boolean_publication_exception(self):
        for bound in (None, True, -1, 1.0, 3):
            document=dict(manifest_published_frames=bound, frames=[{}, {}])
            self.assertEqual(inventory.published_frames(document)[0], [])
        self.assertEqual(inventory.published_frames(dict(complete=True, frames=[{}]*128))[0], [])

    def test_zero_publication_cannot_access_payloads(self):
        frames, reason=inventory.published_frames(dict(manifest_published_frames=0, frames=[{'images':[{'file':'frames/0/private.bin'}]}]))
        self.assertEqual(frames, [])
        self.assertEqual(reason, 'zero_published_frames')

    def test_camera_inspection_uses_published_frames_only(self):
        first=dict(controls=camera(), reset=False)
        second=dict(controls=camera(), reset=True)
        second['controls']['camera_delta']=[100.0, 0.0, 0.0]
        frames, _=inventory.published_frames(dict(manifest_published_frames=1, frames=[first, second]))
        self.assertEqual(inventory.camera_coverage(frames)['nonzero_camera_delta_frames'], 0)
        self.assertEqual(inventory.camera_coverage(frames)['captured_reset_frames'], 0)

    def test_reserve_data_rejected_before_read(self):
        with self.assertRaises(ValueError):
            inventory.safe_path(Path(tempfile.gettempdir())/'reserve_data'/'capture.json')

    def test_payload_wrong_ordinal_path_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            result=inventory.payload_metadata_coverage(Path(folder).resolve(), [dict(images=[dict(file='frames/1/image.bin', bytes=1)])])
            self.assertEqual(result['unsafe_paths'], 1)
            self.assertEqual(result['present_expected_size'], 0)

    def test_frame_survey_command_lists_are_not_temporal_or_combined_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'capture.json'
            document=dict(schema='fsrd-frame-survey-v1', manifest_published_frames=1,
                          payload_ordinal_unit='command_list_recording', frames=[dict(list_id=1, images=[])],
                          reference=None, command_lists=[])
            path.write_text(json.dumps(document))
            result=inventory.inspect_capture(path, {})
            self.assertFalse(result['temporal_native_nrd_replay_ready'])
            self.assertFalse(result['combined_color_same_input_replay_ready'])
            self.assertFalse(result['native_b6_word303_captured'])

    def test_complete_combined_metadata_cannot_claim_native_pair_or_load_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'frames/0').mkdir(parents=True)
            images=[]
            for name in inventory.COMBINED_ROLES:
                file=f'frames/0/{name}.bin'; (root/file).write_bytes(b'x')
                images.append(dict(name=name, file=file, bytes=1))
            path=root/'capture.json'
            path.write_text(json.dumps(dict(schema='fsrd-game-trace-v5', manifest_published_frames=1,
                           frames=[dict(images=images, controls=camera())], reference=dict(available=False))))
            original=Path.read_bytes
            def metadata_only(target):
                if target.suffix=='.bin':
                    raise AssertionError('binary pixel read attempted')
                return original(target)
            with patch.object(Path, 'read_bytes', metadata_only):
                result=inventory.inspect_capture(path, {})
            self.assertTrue(result['combined_color_same_input_replay_ready'])
            self.assertFalse(result['temporal_native_nrd_replay_ready'])
            self.assertFalse(result['clean_reference_available'])
            self.assertFalse(result['binary_pixels_loaded'])


if __name__=='__main__':
    unittest.main()
