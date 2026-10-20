"""Executable mathematical/storage contracts, not game-quality acceptance.

Run from the repository root:
python -B -m unittest discover -s research/astra20261020/candidates/03-native-colour/tests -p test_native_contract.py -v
"""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_colour import (Config, NativeColourModel, exact_selected_mask, half_rtz,
                           luminance, opponent_encode, opponent_inverse, rgba_words)


def scene(height=17, width=19, dtype=np.float16):
    source = np.empty((height, width, 4), dtype)
    raw = np.empty_like(source)
    source[..., :3], raw[..., :3] = [0.45, 0.27, 0.33], [0.3, 0.3, 0.3]
    source[..., 3], raw[..., 3] = 0, 0
    selected = raw.copy()
    depth = np.full((height, width), 10, np.float32)
    normal = np.zeros((height, width, 3), np.float32)
    normal[..., 2] = 1
    roughness = np.full((height, width), 0.35, np.float32)
    authority = np.ones((height, width), bool)
    return source, raw, selected, depth, normal, roughness, authority


def evaluate(values, config=None, **kwargs):
    src, raw, selected, depth, normal, roughness, authority = values
    model = NativeColourModel(config or Config(enabled=True))
    return model.frame(src, raw, selected, depth, normal, roughness=roughness,
                       authority=authority, **kwargs)


class NativeProtection(unittest.TestCase):
    def test_default_off_and_strength_zero_preserve_arbitrary_words(self):
        values = list(scene())
        payload = np.arange(values[2].size, dtype=np.uint16).reshape(values[2].shape)
        payload += np.uint16(0x7c00)
        values[2] = payload.view(np.float16)
        for config in (Config(), Config(enabled=True, strength=0)):
            out, diagnostic = evaluate(values, config)
            np.testing.assert_array_equal(rgba_words(out), rgba_words(values[2]))
            self.assertFalse(diagnostic["changed"].any())

    def test_rgba_bit_authority_preserves_every_protected_pixel(self):
        for dtype, wordtype, sign, nan in ((np.float16, np.uint16, 0x8000, 0x7e21),
                                         (np.float32, np.uint32, 0x80000000, 0x7fc00021)):
            values = list(scene(dtype=dtype))
            raw, selected = values[1], values[2]
            rw, sw = raw.view(wordtype), selected.view(wordtype)
            # One RGB ULP, alpha-only mutation, signed-zero RGB and signed-zero
            # alpha all remain protected, even if numeric == says equal.
            sw[3, 3, 0] += 1
            sw[4, 4, 3] = 1
            rw[5, 5, 0] = 0
            sw[5, 5, 0] = sign
            sw[6, 6, 3] = sign
            # An eligible alpha NaN payload must survive without interpretation.
            rw[7, 7, 3] = sw[7, 7, 3] = nan
            sw[8, 8, 3] = nan + 1
            before = sw.copy()
            out, diagnostic = evaluate(values)
            expected = np.all(rw == before, axis=-1)
            np.testing.assert_array_equal(diagnostic["raw_equal"], expected)
            np.testing.assert_array_equal(rgba_words(out)[~expected], before[~expected])
            np.testing.assert_array_equal(rgba_words(out)[..., 3], before[..., 3])
            self.assertTrue(diagnostic["eligible"][7, 7])
            self.assertTrue(diagnostic["changed"][7, 7])
            # This explicit mutant proves numeric RGBA equality cannot replace
            # the word predicate; +0/-0 mutations would become writable.
            numeric_mutant = np.all(raw == selected, axis=-1)
            self.assertTrue(numeric_mutant[5, 5])
            self.assertFalse(expected[5, 5])
            self.assertFalse(np.array_equal(numeric_mutant, expected))

    def test_native_alpha_zero_is_not_combined_skip_authority(self):
        values = list(scene())
        values[-1][:, :4] = False
        out, diagnostic = evaluate(values)
        self.assertTrue(diagnostic["changed"][:, 4:].all())
        np.testing.assert_array_equal(rgba_words(out)[:, :4], rgba_words(values[2])[:, :4])
        np.testing.assert_array_equal(rgba_words(out)[..., 3], rgba_words(values[2])[..., 3])
        # The known combined-alpha-as-authority mutation would disable every
        # pixel: the ON canary above must fail for that mutation.
        mutant_authority = values[0][..., 3] >= 0.5
        self.assertFalse(mutant_authority.any())

    def test_authority_must_be_explicit_bool_not_native_alpha(self):
        values = list(scene())
        values[-1] = None
        with self.assertRaises(TypeError):
            evaluate(values)
        values[-1] = np.zeros(values[1].shape[:2], np.float16)
        with self.assertRaises(TypeError):
            evaluate(values)

    def test_odd_active_extent_and_allocation_padding_are_untouched(self):
        values = list(scene(height=21, width=27))
        # The unused allocation can contain arbitrary data and must not enter
        # the support of the active edge. Compare with a physically cropped call.
        values[0][13:, :, :3] = 100
        values[0][:, 15:, :3] = 100
        out, diagnostic = evaluate(values, active_extent=(15, 13))
        cropped = [v[:13, :15].copy() for v in values]
        reference, _ = evaluate(cropped)
        np.testing.assert_array_equal(rgba_words(out)[:13, :15], rgba_words(reference))
        outside = ~diagnostic["active"]
        np.testing.assert_array_equal(rgba_words(out)[outside], rgba_words(values[2])[outside])
        self.assertEqual(diagnostic["active_extent"], (15, 13))

    def test_per_lobe_protection_cannot_be_inferred_from_lobe_sum(self):
        diffuse, specular = list(scene()), list(scene())
        # Opposite selected changes cancel in a sum but protect BOTH lobes.
        diffuse[2][5, 5, 0] += np.float16(0.125)
        specular[2][5, 5, 0] -= np.float16(0.125)
        np.testing.assert_array_equal(diffuse[1][5, 5, :3].astype(np.float32) + specular[1][5, 5, :3],
                                      diffuse[2][5, 5, :3].astype(np.float32) + specular[2][5, 5, :3])
        for values in (diffuse, specular):
            out, diagnostic = evaluate(values)
            self.assertFalse(diagnostic["eligible"][5, 5])
            np.testing.assert_array_equal(rgba_words(out)[5, 5], rgba_words(values[2])[5, 5])


class RepresentationAndSupport(unittest.TestCase):
    def test_transform_inverse_and_uniform_scale_invariance(self):
        rgb = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [.3, .3, .3],
                        [.05, .2, 1.4], [2.1, .02, .3]], np.float32)
        encoded = opponent_encode(rgb)
        restored = opponent_inverse(encoded, luminance(rgb))
        np.testing.assert_allclose(restored, rgb, rtol=2e-6, atol=3e-7)
        for scale in (2**-20, 2**-4, 2**8):
            np.testing.assert_array_equal(opponent_encode(rgb * np.float32(scale)), encoded)

    def test_arbitrary_colour_closure_is_word_identical(self):
        values = list(scene())
        rng = np.random.default_rng(101)
        values[1][..., :3] = rng.uniform(.001, 20, values[1][..., :3].shape).astype(np.float16)
        values[0] = values[1].copy()
        values[2] = values[1].copy()
        for mode in ("log", "linear"):
            out, diagnostic = evaluate(values, Config(enabled=True, representation=mode))
            np.testing.assert_array_equal(rgba_words(out), rgba_words(values[2]))
            self.assertFalse(diagnostic["changed"].any())

    def test_zero_stochastic_input_pixel_can_still_receive_supported_correction(self):
        values = list(scene())
        values[0][8, 9, :3] = 0
        out, diagnostic = evaluate(values)
        self.assertTrue(diagnostic["eligible"][8, 9])
        self.assertTrue(diagnostic["supported"][8, 9])
        self.assertGreater(float(diagnostic["confidence"][8, 9]), .5)
        self.assertTrue(diagnostic["changed"][8, 9])
        # Stochastic zero contributes to the mean denominator: do not silently
        # replace the physical estimator by E[RGB | RGB>0].
        self.assertLess(float(diagnostic["source_mean"][8, 9, 0]), float(values[0][0, 0, 0]))

    def test_zero_support_and_invalid_data_remain_identity_without_poisoning_neighbors(self):
        values = list(scene())
        values[0][..., :3] = 0
        out, diagnostic = evaluate(values)
        np.testing.assert_array_equal(rgba_words(out), rgba_words(values[2]))
        self.assertFalse(diagnostic["supported"].any())
        values = list(scene())
        values[0][3, 3, 0] = -1
        values[1][4, 4, 1] = np.nan
        values[2] = values[1].copy()
        values[3][5, 5] = 0
        values[4][6, 6, 0] = np.nan
        values[5][7, 7] = np.inf
        out, diagnostic = evaluate(values)
        for index in ((3, 3), (4, 4), (5, 5), (6, 6), (7, 7)):
            self.assertFalse(diagnostic["supported"][index])
            np.testing.assert_array_equal(rgba_words(out)[index], rgba_words(values[2])[index])
        self.assertTrue(np.isfinite(diagnostic["source_mean"]).all())
        self.assertTrue(np.isfinite(diagnostic["confidence"]).all())
        self.assertTrue(diagnostic["changed"][12, 12])

    def test_signed_depth_and_source_scale_do_not_make_a_dark_gate(self):
        values = list(scene(dtype=np.float32))
        positive, _ = evaluate(values)
        values[3] *= -1
        negative, _ = evaluate(values)
        np.testing.assert_array_equal(positive, negative)
        for scale in (2**-20, 2**-4, 2**8):
            scaled = [v.copy() for v in values]
            for rgba in scaled[:3]:
                rgba[..., :3] *= scale
            out, _ = evaluate(scaled)
            np.testing.assert_allclose(out[..., :3] / scale, positive[..., :3], rtol=8e-7, atol=1e-7)

    def test_pointwise_luminance_and_detail_are_preserved_up_to_store_error(self):
        values = list(scene(height=23, width=29))
        yy, xx = np.indices(values[1].shape[:2])
        detail = (1 + .3 * ((xx + yy) % 2))[..., None]
        values[1][..., :3] *= detail
        values[2] = values[1].copy()
        reference_y = luminance(values[1])
        for mode in ("log", "linear"):
            out, diagnostic = evaluate(values, Config(enabled=True, representation=mode))
            error = np.abs(luminance(out) - reference_y)
            self.assertLessEqual(float(error.max()), float(reference_y.max()) * .0011)
            contrast_before = reference_y[0, 1] - reference_y[0, 0]
            contrast_after = luminance(out)[0, 1] - luminance(out)[0, 0]
            self.assertLess(abs(float(contrast_after / contrast_before - 1)), .003)
            self.assertTrue(diagnostic["changed"].any())

    def test_geometry_boundary_is_applied_before_averaging(self):
        values = list(scene(height=17, width=25))
        edge = 11  # deliberately not a former 4px/8px cell boundary
        values[0][:, edge:, :3] = values[1][:, edge:, :3]
        values[3][:, edge:] = 20
        out, diagnostic = evaluate(values)
        np.testing.assert_array_equal(rgba_words(out)[:, edge:], rgba_words(values[2])[:, edge:])
        np.testing.assert_allclose(diagnostic["source_mean"][:, edge:], values[1][:, edge:, :3], atol=2e-7)
        self.assertTrue(diagnostic["changed"][:, :edge].all())

    def test_temporal_metadata_cannot_manufacture_history(self):
        values = list(scene())
        model = NativeColourModel(Config(enabled=True))
        args = values[:5]
        kwargs = dict(roughness=values[5], authority=values[6])
        a, first = model.frame(*args, **kwargs, frame_id=180, render_extent=(1505, 847), crop_origin=(50, 200))
        b, second = model.frame(*args, **kwargs, frame_id=186, render_extent=(1505, 847), crop_origin=(55, 205), reset=True)
        np.testing.assert_array_equal(rgba_words(a), rgba_words(b))
        self.assertFalse(first["history_used"].any())
        self.assertFalse(second["history_used"].any())
        self.assertEqual(second["temporal_mode"], "none_current_frame_only")

    def test_half_rtz_rounding_is_explicit_and_alpha_independent(self):
        rgb = np.array([.3, -.3, .1, -.1, 0, 65504, 1e-9], np.float32)
        rounded = half_rtz(rgb)
        self.assertTrue(np.all(np.abs(rounded.astype(np.float32)) <= np.abs(rgb)))
        np.testing.assert_array_equal(rounded, half_rtz(rounded))
        self.assertEqual(float(rounded[0]), .2998046875)


if __name__ == "__main__":
    unittest.main()
