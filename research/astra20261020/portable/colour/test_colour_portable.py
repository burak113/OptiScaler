"""Independent numeric contracts and preserved rejected-candidate counterexamples."""
import ast
from pathlib import Path
import unittest

import numpy as np
import colour_portable as cp
from compare import fixture_comparison, edge_phase_comparison


class NumericContracts(unittest.TestCase):
    def test_rtz_never_overshoots_and_is_idempotent(self):
        values = np.r_[np.linspace(-65000, 65000, 8193, dtype=np.float32),
                       np.array([0, 1e-9, -1e-9, .3, -.3, .1, -.1], np.float32)]
        quantized = cp.half_rtz(values)
        self.assertTrue(np.all(np.abs(quantized) <= np.abs(values)))
        np.testing.assert_array_equal(quantized, cp.half_rtz(quantized))
        np.testing.assert_array_equal(cp.half_rtz(np.array([.3, -.3], np.float32)),
                                      np.array([.2998046875, -.2998046875], np.float32))

    def test_all_11bit_payloads_are_exact_half_values(self):
        payloads = np.arange(2048, dtype=np.float32)
        np.testing.assert_array_equal(payloads, payloads.astype(np.float16).astype(np.float32))
        np.testing.assert_array_equal(payloads, cp.pack_new(cp.unpack_new(payloads)))

    def test_normal_pack_preserves_axes_and_all_decodes_are_unit(self):
        payloads = np.arange(2048, dtype=np.float32)
        normals = cp.octdec(cp.unpack_new(payloads))
        self.assertTrue(np.isfinite(normals).all())
        np.testing.assert_allclose(np.linalg.norm(normals, axis=-1), 1, atol=2e-7, rtol=0)
        axes_oct = np.array([[.5, .5], [1, .5], [.5, 1]], np.float32)
        decoded = cp.octdec(cp.unpack_new(cp.pack_new(axes_oct)))
        reference = np.eye(3, dtype=np.float32)[[2, 0, 1]]
        angle = np.degrees(np.arccos(np.clip((decoded * reference).sum(-1), -1, 1)))
        self.assertLess(float(angle.max()), 5)

    def test_normalized_16bit_payload_cannot_survive_half_storage(self):
        integers = np.arange(65536, dtype=np.float32)
        restored = np.floor(cp.half_rtz(integers / 65535) * 65535 + .5)
        self.assertGreater(int(np.count_nonzero(restored != integers)), 30000)

    def test_ideal_bilinear_has_known_values_and_edge_clamp(self):
        image = np.array([[0, 2], [4, 6]], np.float32)
        x = np.array([.25, .5, -2, 9], np.float32)
        y = np.array([.5, .5, 0, 1], np.float32)
        np.testing.assert_array_equal(cp.bilinear(image, x, y), np.array([2.5, 3, 0, 6], np.float32))

    def test_gray_identity_and_signed_depth(self):
        image = np.full((32, 64, 3), .3, np.float32)
        depth = np.full((32, 64), 10, np.float32)
        normals = np.full((32, 64, 2), .5, np.float32)
        motion = np.zeros((32, 64, 4), np.float32)
        positive, _ = cp.baseline_model().frame(image, image, depth, normals, motion)
        negative, _ = cp.baseline_model().frame(image, image, -depth, normals, motion)
        np.testing.assert_array_equal(positive, cp.half_rtz(image))
        np.testing.assert_array_equal(negative, positive)

    def test_apply_preserves_luma_within_half_storage_error(self):
        rng = np.random.default_rng(64159)
        image = rng.uniform(.02, 2, (32, 64, 3)).astype(np.float32)
        gain = rng.uniform(.75, 1.33, (8, 16, 3)).astype(np.float32)
        out = cp.apply(image, gain)
        error = np.abs(cp.lum(out) - cp.lum(cp.half_rtz(image)))
        self.assertLessEqual(float(error.max()), .002)

    def test_module_imports_only_numpy_and_standard_library(self):
        tree = ast.parse(Path(cp.__file__).read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for n in ast.walk(tree)
                    if isinstance(n, ast.Import) for alias in n.names}
        imported |= {n.module.split(".")[0] for n in ast.walk(tree)
                     if isinstance(n, ast.ImportFrom) and n.module}
        self.assertEqual(imported, {"sys", "numpy"})


class CapturedFixtureContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparison = fixture_comparison()["comparisons"]

    def test_captured_stats_history_gain_packing_and_bilinear_exact(self):
        for name in ("expected_stats", "expected_history", "expected_gain",
                     "expected_packed_normal", "expected_bilinear"):
            with self.subTest(array=name):
                self.assertTrue(self.comparison[name]["array_equal"], self.comparison[name])

    def test_soft2_fixture_precision_caveat_is_bounded(self):
        # Fixture omits pre-UAV RR guide low bits: this is deliberately not an exact-equality assertion.
        self.assertLessEqual(self.comparison["expected_soft2"]["max_half_ulp"], 2)


class RejectedCandidateContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = edge_phase_comparison()

    def test_all_32_phase_cases_are_present(self):
        self.assertEqual(len(self.report["cases"]), 32)

    def test_candidate_remains_rejected_on_shifted_geometry_edges(self):
        # A test PASS records the known failure; it does not approve soft2's image quality.
        self.assertEqual(self.report["verdict"], "rejected_halo_regression")
        for kind in ("normal", "depth"):
            row = next(r for r in self.report["cases"] if r["kind"] == kind and r["phase"] == 4)
            self.assertGreater(row["soft2_right_bleed_mean"], 1.5 * row["B4_right_bleed_mean"])


if __name__ == "__main__":
    unittest.main()
