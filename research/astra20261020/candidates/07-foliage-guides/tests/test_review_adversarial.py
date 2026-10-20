"""Independent reviewer regressions and frozen adversarial contract probes.

Tests consume only the public observer API. They do not tune a candidate or
assert that guide agreement identifies physical coverage/history correctness.
"""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from foliage_guides import GuideFrame, SupportFlag, observe_guides, pack_normal_roughness, unpack_normal_roughness


def uniform_frame(*, frame_id=101, depth=12.0, previous_depth_delta=0.0, origin=(0, 0), category=3):
    shape = (5, 7)
    normal = np.broadcast_to(np.array([0, 0, 1], dtype=np.float32), shape + (3,))
    packed = pack_normal_roughness(normal, .375, category=category)
    motion = np.zeros(shape + (4,), dtype=np.float32)
    motion[..., 2] = previous_depth_delta
    # An untouched A-channel payload; not part of the guide evidence contract.
    motion.view(np.uint32)[..., 3] = np.uint32(0x7FC00171)
    return GuideFrame(packed, np.full(shape, depth, np.float32), motion,
                      frame_id, origin, (128, 64), depth_is_positive_linear=True)


class TestIndependentGuideContract(unittest.TestCase):
    def test_enabled_api_and_all_input_words_unchanged(self):
        previous = uniform_frame(frame_id=100)
        current = uniform_frame()
        before = [(a.copy().tobytes(), a) for f in (current, previous)
                  for a in (f.packed_normal_roughness, f.depth, f.motion)]
        output = observe_guides(current, previous, enabled=True)
        self.assertEqual(int(output.temporal_supported.sum()), 24)
        for raw, array in before:
            self.assertEqual(raw, array.tobytes())
        # NumPy 2.3 exposed IntFlag/int64 in-place OR into uint16 here.
        self.assertEqual(output.flags.dtype, np.uint16)

    def test_crop_origin_and_motion_b_sign(self):
        previous = uniform_frame(frame_id=100, depth=14)
        current = uniform_frame(origin=(2, 1), depth=12, previous_depth_delta=2)
        current.motion[..., 0] = -1 / 128
        current.motion[..., 1] = -1 / 64
        output = observe_guides(current, previous, enabled=True)
        # q=(x+1,y): origin changes and full-render UV must both contribute.
        expected = np.zeros((5, 7), dtype=bool)
        expected[:4, :5] = True
        np.testing.assert_array_equal(output.temporal_supported, expected)
        wrong_b = current.motion.copy()
        wrong_b[..., 2] = -2
        self.assertFalse(observe_guides(replace(current, motion=wrong_b), previous, enabled=True).temporal_supported.any())

    def test_negative_and_overflowed_predicted_depth_rejected(self):
        # These finite-input adversaries previously manufactured valid support.
        for depth, delta in ((1e-10, -2e-10), (3e38, 3e38)):
            with self.subTest(depth=depth, delta=delta):
                previous = uniform_frame(frame_id=100, depth=depth)
                current = uniform_frame(depth=depth, previous_depth_delta=delta)
                with np.errstate(over="ignore", invalid="ignore"):
                    result = observe_guides(current, previous, enabled=True)
                self.assertFalse(result.temporal_supported.any())
                self.assertFalse((result.flags & np.uint16(SupportFlag.DEPTH_MATCH)).any())
                np.testing.assert_array_equal(result.experimental_history_multiplier, 1)

    def test_unsupported_is_explicit_identity_not_positive_evidence(self):
        previous = uniform_frame(frame_id=100)
        current = uniform_frame()
        far_motion = current.motion.copy()
        far_motion[..., 0] = 2
        variants = (
            (current, None, True),
            (replace(current, reset=True), previous, True),
            (replace(current, frame_id=103), previous, True),
            (replace(current, depth_is_positive_linear=False), previous, True),
            (replace(current, motion=far_motion), previous, True),
            (current, previous, False),
        )
        for cur, prev, enabled in variants:
            result = observe_guides(cur, prev, enabled=enabled)
            self.assertFalse(result.temporal_supported.any())
            np.testing.assert_array_equal(result.experimental_history_multiplier, 1)

    def test_nonfinite_motion_and_missing_material_agreement(self):
        previous = uniform_frame(frame_id=100)
        current = uniform_frame()
        motion = current.motion.copy()
        motion[1, 2, 0] = np.nan
        motion[2, 3, 2] = np.inf
        output = observe_guides(replace(current, motion=motion), previous, enabled=True)
        self.assertFalse(output.temporal_supported[1, 2])
        self.assertFalse(output.temporal_supported[2, 3])
        self.assertTrue(np.isfinite(output.temporal_innovation).all())
        changed_category = uniform_frame(frame_id=100, category=0)
        self.assertFalse(observe_guides(current, changed_category, enabled=True).temporal_supported.any())

    def test_known_normals_and_category_bits(self):
        normals = np.array([[0, 0, 1], [0, 0, -1], [1, 0, 0], [-1, 0, 0],
                            [0, 1, 0], [0, -1, 0], [1, -1, -1]], dtype=np.float32)
        normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
        for category in range(4):
            packed = pack_normal_roughness(normals, .375, category)
            decoded, roughness, categories = unpack_normal_roughness(packed)
            self.assertGreater(float(np.min(np.sum(normals * decoded, axis=-1))), .99998)
            np.testing.assert_array_equal(categories, category)
            self.assertLess(float(np.max(np.abs(roughness - .375))), 1 / 1023)


if __name__ == "__main__":
    unittest.main()
