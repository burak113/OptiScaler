"""Independent adversarial checks chosen before reading candidate claims.

This file is owned by the skeptical reviewer, separately from contract tuning.
Test oracles use fixed analytic values, independent integer totals, and NumPy's
standard conversion only where its semantics are the named CPU model.
"""
from pathlib import Path
import sys
import unittest

import numpy as np

CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE))
from adversary_controls import controls, finite_rtz_oracle, overlap_recovery
from numerical_contract import coordinates as C
from numerical_contract import storage as S
from numerical_contract import sampling as T
from numerical_contract import fixedpoint as F
from numerical_contract import arithmetic as A
from numerical_contract import encoding as E
from numerical_contract import guards as G
from numerical_contract.anchor_gain import anchor_gain_unstored


class IndependentBlindedControls(unittest.TestCase):
    def test_precommitted_bad_controls_still_fail(self):
        measured = controls()
        self.assertEqual(measured["old_normal_packing"]["bad_count"], 59383)
        self.assertEqual(measured["missing_high_word"]["high"], 64)
        self.assertNotEqual(measured["premature_rounding"]["correct_final_store"],
                            measured["premature_rounding"]["wrong_per_add_store"])
        self.assertFalse(measured["nonidentifiability"]["exact_reconstruction_possible"])


class IndependentStorageChallenges(unittest.TestCase):
    def test_all_finite_preimage_endpoints_and_neighbors(self):
        payload = np.concatenate((np.arange(0x7C00, dtype=np.uint16),
                                  np.arange(0x8000, 0xFC00, dtype=np.uint16)))
        stored = payload.view(np.float16).astype(np.float32)
        self.assertEqual(len(payload), 63488)
        for rounding in ("rtz", "rne"):
            with self.subTest(rounding=rounding):
                interval = S.fp16_preimage_f32(stored, rounding=rounding)
                for endpoint in (interval.lower, interval.upper):
                    # Cross-check against an independently executed conversion.
                    if rounding == "rtz":
                        actual = finite_rtz_oracle(endpoint).astype(np.float16).view(np.uint16)
                    else:
                        actual = endpoint.astype(np.float16).view(np.uint16)
                    np.testing.assert_array_equal(actual, payload)
                with np.errstate(over="ignore", invalid="ignore"):
                    outside = (np.nextafter(interval.lower, np.float32(-np.inf)),
                               np.nextafter(interval.upper, np.float32(np.inf)))
                for beyond in outside:
                    self.assertFalse(np.any(interval.contains(beyond)))
                    self.assertFalse(np.any(S.fp16_bits(beyond, rounding=rounding) == payload))

    def test_signed_zero_halfway_subnormal_and_overflow_literals(self):
        values = np.array([0., -0., 2**-25, -2**-25, 3 * 2**-25,
                           -3 * 2**-25, 65520., -65520.], np.float32)
        np.testing.assert_array_equal(S.fp16_bits(values, rounding="rne"),
                                      [0, 0x8000, 0, 0x8000, 2, 0x8002, 0x7C00, 0xFC00])
        np.testing.assert_array_equal(S.fp16_bits(values, rounding="rtz"),
                                      [0, 0x8000, 0, 0x8000, 1, 0x8001, 0x7BFF, 0xFBFF])
        zero = S.fp16_preimage_f32(np.array([0., -0.], np.float32), rounding="rtz")
        np.testing.assert_array_equal(zero.contains(np.array([0., -0.], np.float32)), [True, True])
        np.testing.assert_array_equal(zero.contains(np.array([-0., 0.], np.float32)), [False, False])

    def test_seeded_float32_bits_against_independent_rtz_oracle(self):
        rng = np.random.default_rng(0x01ADA203)
        raw = rng.integers(0, 2**32, size=65536, dtype=np.uint32)
        values = raw.view(np.float32)
        values = values[np.isfinite(values)]
        actual = S.store_fp16(values, rounding="rtz")
        expected = finite_rtz_oracle(values)
        np.testing.assert_array_equal(actual.view(np.uint32), expected.view(np.uint32))

    def test_source_sanitization_is_separate_from_typed_store(self):
        values = np.array([-1., 0., 1., 65500., 65504., np.inf, -np.inf, np.nan], np.float32)
        np.testing.assert_array_equal(S.sanitize_radiance(values),
                                      np.array([0., 0., 1., 65500., 65500., 0., 0., 0.], np.float32))
        raw = S.store_fp16(values, rounding="rtz")
        self.assertTrue(np.isposinf(raw[5]))
        self.assertTrue(np.isneginf(raw[6]))
        self.assertTrue(np.isnan(raw[7]))
        self.assertEqual(raw[0], -1)
        self.assertEqual(float(S.store_fp16(S.sanitize_radiance([65500]), rounding="rtz")[0]), 65472.)

    def test_two_same_export_inputs_have_different_atomic_observables(self):
        possible = np.array([1., 1. + 2**-11], np.float32)
        np.testing.assert_array_equal(S.store_fp16(possible, rounding="rtz"), [1., 1.])
        interval = S.fp16_preimage_f32(np.float32(1), rounding="rtz")
        self.assertTrue(np.all(interval.contains(possible)))
        increments = np.trunc(possible * np.float32(65536)).astype(np.uint32)
        np.testing.assert_array_equal(increments, [65536, 65568])
        # An API must not treat the exported half as if it revealed which input occurred.
        self.assertLess(float(interval.lower), float(interval.upper))

    def test_non_half_export_cannot_be_accepted_as_a_half_preimage(self):
        not_a_half = np.nextafter(np.float32(1), np.float32(2))
        for rounding in ("rtz", "rne"):
            with self.assertRaises(ValueError):
                S.fp16_preimage_f32(not_a_half, rounding=rounding)


class IndependentCoordinateChallenges(unittest.TestCase):
    def test_allocation_center_and_wrong_active_scale(self):
        xy = np.array([3., 2.], np.float64)
        correct = C.uv_to_texel(C.texel_to_uv(xy, (17, 11), mode="ideal"),
                                (17, 11), mode="ideal")
        np.testing.assert_allclose(correct, xy, rtol=0, atol=1e-15)
        wrong = C.uv_to_texel(C.texel_to_uv(xy, (13, 7), mode="ideal"),
                              (17, 11), mode="ideal")
        self.assertGreater(float(np.linalg.norm(wrong - xy)), 1)

    def test_moving_crop_is_not_motion_and_original_render_scale_is_kept(self):
        uv_motion = np.array([2 / 1505, -3 / 847], dtype=np.float64)
        pixels = C.motion_uv_to_pixels(uv_motion, (1505, 847), mode="ideal")
        np.testing.assert_allclose(pixels, [2, -3], rtol=0, atol=1e-15)
        previous = C.reproject_crop([10., 12.], pixels,
                                    current_origin=(400, 200), previous_origin=(405, 197), mode="ideal")
        np.testing.assert_allclose(previous, [7., 12.], rtol=0, atol=1e-15)
        stationary_world = C.reproject_crop([10., 12.], [0., 0.],
                                            current_origin=(400, 200), previous_origin=(405, 197), mode="ideal")
        np.testing.assert_array_equal(stationary_world, [5., 15.])

    def test_odd_extent_mapping_is_not_an_assumed_one_eighth_divide(self):
        self.assertEqual(C.grid_extent((137, 131), 8), (17, 16))
        q = C.full_pixel_to_grid_texel([136., 130.], (137, 131), (17, 16), mode="ideal")
        expected = np.array([(136.5 / 137) * 17 - .5, (130.5 / 131) * 16 - .5])
        np.testing.assert_allclose(q, expected, rtol=0, atol=1e-14)
        self.assertGreater(float(np.linalg.norm(q - ((np.array([136., 130.]) + .5) / 8 - .5))), .1)


class IndependentSamplingChallenges(unittest.TestCase):
    def test_partial_crop_keeps_zero_weight_center_and_rejects_absent_tap(self):
        full = (100 * np.arange(7)[:, None] + np.arange(9)[None, :]).astype(np.float32)
        observed = full[2:5, 3:6]
        domain = T.TextureDomain((9, 7), crop_origin=(3, 2))
        for mode in ("ideal", "source", "observed"):
            center = T.bilinear_texel(observed, [5, 4], domain=domain, mode=mode)
            self.assertTrue(center.supported)
            self.assertEqual(float(center.values), 405)
            missing = T.bilinear_texel(observed, [5.2, 3], domain=domain, mode=mode)
            self.assertFalse(missing.supported)
            with self.assertRaises(T.UnsupportedSampleError):
                missing.require_supported()
        # Quantized observed-model support can differ at a vanishing fraction;
        # support masks must be reported, never recomputed into a candidate win.
        ideal = T.bilinear_texel(observed, [5.0001, 4], domain=domain, mode="ideal")
        snapped = T.bilinear_texel(observed, [5.0001, 4], domain=domain, mode="observed")
        self.assertFalse(ideal.supported)
        self.assertTrue(snapped.supported)

    def test_plane_falsifies_nearest_and_wrong_active_normalization(self):
        image = (100 * np.arange(11)[:, None] + np.arange(17)[None, :]).astype(np.float32)
        domain = T.TextureDomain((17, 11), active_extent=(13, 7))
        uv = C.texel_to_uv([3.25, 2.5], (17, 11), mode="ideal")
        linear = T.sample_bilinear(image, uv, domain=domain, mode="ideal")
        nearest = T.sample_point(image, uv, domain=domain, mode="ideal")
        self.assertAlmostEqual(float(linear.values), 253.25, places=12)
        self.assertNotEqual(float(nearest.values), float(linear.values))
        center_uv = C.texel_to_uv([3, 2], (17, 11), mode="ideal")
        center = T.sample_bilinear(image, center_uv, domain=domain, mode="ideal")
        self.assertEqual(float(center.values), 203)
        bad_uv = C.texel_to_uv([3, 2], (13, 7), mode="ideal")
        bad = T.sample_bilinear(image, bad_uv, domain=domain, mode="ideal")
        self.assertGreater(abs(float(bad.values) - 203), 100)

    def test_active_padding_is_observable_but_not_active_support(self):
        image = np.ones((11, 17), np.float32)
        domain = T.TextureDomain((17, 11), active_extent=(13, 7))
        result = T.bilinear_texel(image, [14, 8], domain=domain, mode="source")
        self.assertTrue(result.supported)
        self.assertFalse(result.active_support)
        result.require_supported()
        with self.assertRaises(T.UnsupportedSampleError):
            result.require_supported(active=True)

    def test_four_tap_native_pattern_is_not_a_full_64_texel_mean(self):
        texture = np.zeros((8, 8), np.float32)
        texture[0, 0] = 1
        sampled = T.sample_cell_four_taps(texture, [0, 0], 8, mode="ideal")
        self.assertEqual(float(sampled.values), 0)
        self.assertEqual(float(texture.mean()), 1 / 64)
        # Every one of the 16 quarter-cell texels participates at equal weight.
        for y in range(4):
            for x in range(4):
                impulse = np.zeros((4, 4), np.float32)
                impulse[y, x] = 1
                value = T.sample_cell_four_taps(impulse, [0, 0], 4, mode="ideal").values
                self.assertEqual(float(value), 1 / 16)

    def test_integer_translation_and_constant_field_holdout(self):
        rng = np.random.default_rng(0x01ADA203)
        image = rng.normal(size=(11, 17, 3)).astype(np.float32)
        shifted = np.roll(image, (1, 2), axis=(0, 1))
        positions = np.column_stack((rng.uniform(1, 12, 64), rng.uniform(1, 7, 64)))
        for mode in ("ideal", "source", "observed"):
            # Integer translation must keep the same phase; use exactly
            # representable eighth phases to avoid source-coordinate rounding.
            p = np.rint(positions * 8) / 8
            a = T.bilinear_texel(image, p, mode=mode).values
            b = T.bilinear_texel(shifted, p + [2, 1], mode=mode).values
            np.testing.assert_array_equal(a, b)
            constant = np.full((1, 1, 3), [.25, 2, -4], np.float32)
            result = T.bilinear_texel(constant, positions, mode=mode)
            np.testing.assert_array_equal(result.values, np.broadcast_to([.25, 2, -4], (64, 3)))
            self.assertTrue(np.all(result.supported))

    def test_integer_load_preserves_uint_payload_and_zero_border(self):
        payload = np.array([[0xFFFFFFFF, 0x80000001]], np.uint32)
        result = T.load(payload, np.array([[0, 0], [1, 0], [2, 0], [-1, 0]], np.int64))
        np.testing.assert_array_equal(result.values, [0xFFFFFFFF, 0x80000001, 0, 0])
        self.assertEqual(result.values.dtype, np.uint32)
        self.assertTrue(np.all(result.supported))
        with self.assertRaises(TypeError):
            T.load(payload, [.2, 0])


class IndependentRepresentationChallenges(unittest.TestCase):
    def test_11bit_payload_and_legacy_control_exhaustive(self):
        code = np.arange(2048, dtype=np.float32)
        uv = np.column_stack((np.arange(2048) // 32 / 63,
                              np.arange(2048) % 32 / 31)).astype(np.float32)
        np.testing.assert_array_equal(E.pack_normal11(uv), code)
        for rounding in ("rne", "rtz"):
            stored = S.store_fp16(E.pack_normal11(uv), rounding=rounding)
            np.testing.assert_array_equal(E.pack_normal11(E.unpack_normal11(stored)), code)
        old_codes = np.arange(65536, dtype=np.uint32)
        old_uv = np.column_stack((old_codes // 256, old_codes % 256)).astype(np.float32) / np.float32(255)
        packed = S.store_fp16(E.pack_normal16_old(old_uv), rounding="rtz")
        decoded = E.unpack_normal16_old(packed)
        restored = np.floor(decoded * np.float32(255) + np.float32(.5)).astype(np.uint32)
        restored_code = restored[:, 0] * 256 + restored[:, 1]
        self.assertEqual(int(np.count_nonzero(restored_code != old_codes)), 59383)

    def test_distinct_pole_encodings_are_not_deduplicated(self):
        corners = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], np.float32)
        codes = E.pack_normal11(corners)
        self.assertEqual(len(set(map(int, codes))), 4)
        decoded = E.octahedral_decode(E.unpack_normal11(codes))
        np.testing.assert_array_equal(decoded, np.tile([0, 0, -1], (4, 1)))
        # Direction equality does not imply encoded-payload equality.
        np.testing.assert_array_equal(codes, [0, 2016, 31, 2047])
        with self.assertRaises(ValueError):
            E.octahedral_encode([0, 0, 0])
        self.assertTrue(np.all(np.isnan(E.octahedral_encode([0, 0, 0], degenerate="nan"))))

    def test_emulated_natural_multiple_wraps_and_complete_reset(self):
        count = 262145
        increments = np.full(count, 16 * 65536, dtype=np.uint32)
        sums = F.FrameSums().add_quantized(increments, increments // 2)
        self.assertEqual(sums.current_total, 274878955520)
        self.assertEqual(sums.recalled_total, 137439477760)
        self.assertEqual(int(sums.words[0]), 1048576)
        self.assertEqual(int(sums.words[1]), 64)
        self.assertEqual(sums.count, count)
        self.assertEqual(float(sums.source_ratio()), .5)
        self.assertNotEqual(sums.current_total, int(sums.words[0]))
        # Full64-bit wrap, count wrap and arbitrary padding are separate hazards.
        injected = F.FrameSums([0xFFFFFFF0, 0xFFFFFFFF, 0xFFFFFFFE, 12,
                               0xFFFFFFFF, 0xDEADBEEF, 0xA5A5A5A5, 0xFFFFFFFF])
        injected.add_quantized([32], [3])
        self.assertEqual(injected.current_total, 16)
        self.assertEqual(injected.recalled_total, 13 * 2**32 + 1)
        self.assertEqual(injected.count, 0)
        self.assertEqual(F.FrameSums.from_bytes(injected.to_bytes()).to_bytes(), injected.to_bytes())
        injected.reset()
        self.assertEqual(injected.to_bytes(), bytes(32))

    def test_atomic_bounds_reject_exact_reconstruction_and_keep_support_fixed(self):
        bounds = F.frame_sum_bounds(np.array([1.], np.float32), np.array([.5], np.float32),
                                    np.array([True]), rounding="rtz")
        self.assertEqual((bounds.current_min, bounds.current_max), (65536, 65599))
        self.assertEqual((bounds.recalled_min, bounds.recalled_max), (32768, 32799))
        with self.assertRaises(S.NonIdentifiableError):
            bounds.require_exact_totals()
        np.testing.assert_array_equal(bounds.ratio_interval(),
                                      [float(np.float32(32768) / np.float32(65599)),
                                       float(np.float32(32799) / np.float32(65536))])
        # Poisoned values outside immutable support are not observations.
        current = np.array([1., np.nan, np.inf], np.float32)
        recalled = np.array([.5, -np.inf, np.nan], np.float32)
        fixed_mask = np.array([True, False, False])
        masked = F.frame_sum_bounds(current, recalled, fixed_mask, rounding="rtz")
        self.assertEqual(masked.as_dict(), bounds.as_dict())
        sums = F.FrameSums().add(current, recalled, support=fixed_mask)
        self.assertEqual((sums.current_total, sums.recalled_total, sums.count), (65536, 32768, 1))

    def test_cap16_is_physical_and_not_an_early_half_store(self):
        levels = np.array([-2., 0., 1., 1. + 2**-11, 16., 1000.], np.float32)
        np.testing.assert_array_equal(F.quantize_u16_16(levels),
                                      [0, 0, 65536, 65568, 1048576, 1048576])
        prematurely_stored = F.quantize_u16_16(S.store_fp16(levels, rounding="rtz"))
        self.assertNotEqual(int(prematurely_stored[3]), 65568)
        for value in (np.nan, np.inf, -np.inf):
            with self.assertRaises(ValueError):
                F.quantize_u16_16(value)

    def test_off_and_independent_lobes_preserve_payload(self):
        diffuse = np.array([[.5, 1, 2, -0.], [1, 2, 4, 19]], np.float32)
        specular = np.array([[4, 2, 1, 7], [8, 4, 2, -0.]], np.float32)
        off_d, off_s = A.apply_anchor_lobes(diffuse, specular, object(), enabled=False,
                                           rounding="deliberately unused invalid setting")
        np.testing.assert_array_equal(off_d.view(np.uint32), diffuse.view(np.uint32))
        np.testing.assert_array_equal(off_s.view(np.uint32), specular.view(np.uint32))
        out_d, out_s = A.apply_anchor_lobes(diffuse, specular, [.5, .25], rounding="rtz")
        np.testing.assert_array_equal(out_d[..., :3], diffuse[..., :3] * np.array([.5, .25])[:, None])
        np.testing.assert_array_equal(out_s[..., :3], specular[..., :3] * np.array([.5, .25])[:, None])
        np.testing.assert_array_equal(out_d[..., 3].view(np.uint32), diffuse[..., 3].view(np.uint32))
        np.testing.assert_array_equal(out_s[..., 3].view(np.uint32), specular[..., 3].view(np.uint32))
        changed_specular = specular.copy()
        changed_specular[:, :3] *= 2
        unaffected_d, _ = A.apply_anchor_lobes(diffuse, changed_specular, [.5, .25], rounding="rtz")
        np.testing.assert_array_equal(unaffected_d.view(np.uint32), out_d.view(np.uint32))


class IndependentGuardAndEvidenceChallenges(unittest.TestCase):
    def test_strict_boundary_is_inclusive_and_viewport_rejects_true_outside(self):
        h = np.array([33., np.nextafter(np.float32(33), np.float32(np.inf)), -33., 0.], np.float32)
        c = np.array([32., 32., -32., 32.], np.float32)
        uv = np.array([[0, 0], [1, 1], [.5, .5], [.5, .5]], np.float32)
        valid = G.colour_history_valid(h, c, np.zeros(4), uv, tolerance=.03125)
        np.testing.assert_array_equal(valid, [True, False, True, False])
        uv[0, 0] = np.nextafter(np.float32(0), np.float32(-np.inf))
        self.assertFalse(G.colour_history_valid(h, c, np.zeros(4), uv, tolerance=.03125)[0])

    def test_inactive_history_and_source_authority_ignore_unused_poison(self):
        invalid = G.colour_history_valid(object(), np.array([1., 2.]), object(), object(),
                                          history_enabled=False, tolerance=object())
        np.testing.assert_array_equal(invalid, [False, False])
        colour = np.array([[1, 2, 4, -0.], [2, 4, 8, 19]], np.float32)
        unchanged = G.colour_apply_pixel(colour, object(), [0, 0], rounding="unused invalid setting")
        np.testing.assert_array_equal(unchanged.view(np.uint32), colour.view(np.uint32))
        mixed = G.colour_apply_pixel(colour, [[np.nan] * 3, [1] * 3], [0, 1])
        np.testing.assert_array_equal(mixed[0].view(np.uint32), colour[0].view(np.uint32))
        np.testing.assert_array_equal(mixed[1], [2, 4, 8, 1])

    def test_nonfinite_source_depth_does_not_get_an_invented_finite_guard(self):
        # Source has no isfinite(expected) gate. In the unfused CPU expression
        # Inf <= Inf accepts, while NaN comparison rejects; hardware fast-math
        # handling is explicitly not established by this diagnostic.
        valid = G.colour_history_valid(np.ones(3), np.array([np.inf, -np.inf, np.nan]),
                                        np.zeros(3), np.full((3, 2), .5))
        np.testing.assert_array_equal(valid, [True, True, False])

    def test_unique_observable_actually_rejects_distinct_bytes(self):
        with self.assertRaises(S.NonIdentifiableError):
            G.require_unique_observable([np.array([1], np.float32), np.array([2], np.float32)])
        with self.assertRaises(S.NonIdentifiableError):
            G.require_unique_observable([np.array([0.], np.float32), np.array([-0.], np.float32)])
        with self.assertRaises(ValueError):
            G.require_unique_observable([])
        x = np.array([1], np.float32)
        result = G.require_unique_observable([x, x.copy()])
        result[0] = 4
        self.assertEqual(float(x[0]), 1)

    def test_real_overlap_recovers_only_the_proven_source_rectangle(self):
        summary, mask, recovered = overlap_recovery(return_arrays=True)
        self.assertEqual(int(mask.sum()), 12288)
        self.assertEqual(summary["colour_local_crop_xywh"], [256, 256, 192, 64])
        self.assertTrue(all(x["exact"] for x in summary["same_frame_stage_comparisons"].values()))
        self.assertGreater(summary["baseline_vs_expected_on_observed_support"]["changed"], 0)
        self.assertEqual(summary["restored_vs_expected_on_observed_support"]["changed"], 0)
        self.assertEqual(summary["restored_vs_expected_on_observed_support"]["elements"], 36864)
        witness = summary["admissible_hypothetical_half_lobe_witness"]
        self.assertGreater(witness["output_difference"]["changed"], 0)
        self.assertEqual(witness["observed_rectangle_output_difference"]["changed"], 0)
        self.assertEqual(recovered.shape, (512, 512, 3))


class IndependentGainCalibrationChallenges(unittest.TestCase):
    def test_native_static_half_boundary_uses_neighbor_recall_without_centre_recall(self):
        # Source Params4.w tests cell.z < .5, not <= .5. Its neighbourhood
        # coverage gate is distinct from the key-capture cell.z > .5 test.
        stats = np.zeros((7, 7, 4), np.float32)
        recalled = np.zeros_like(stats)
        stats[..., 0] = 1
        stats[..., 2] = 1
        stats[3, 3, 2] = .5
        recalled[0, 0] = [.875, 1, 0, 1]
        active = anchor_gain_unstored(stats, recalled, 0, 1, frame_count=1,
                                      frame_measured=True, policy="native")
        self.assertEqual(float(active.coverage[3, 3]), 1)
        self.assertEqual(float(recalled[3, 3, 1]), 0)
        self.assertFalse(active.native_local_blocked[3, 3])
        self.assertLess(float(active.gain[3, 3]), 1)
        stats[3, 3, 2] = np.nextafter(np.float16(.5), np.float16(0), dtype=np.float16)
        rejected = anchor_gain_unstored(stats, recalled, 0, 1, frame_count=1,
                                        frame_measured=True, policy="native")
        self.assertTrue(rejected.native_local_blocked[3, 3])
        self.assertEqual(float(rejected.gain[3, 3]), 1)

    def test_recorded_equal_ratio_cell_falsifies_final_store_only_reconstruction(self):
        fixture = CANDIDATE.parents[1] / "portable/anchor/fixtures/combined/87ee1fba.npz"
        with np.load(fixture, allow_pickle=False) as data:
            j = int(np.flatnonzero(data["frames"] == 18)[0])
            stats, recalled = data["stats"][j], data["recalled"][j]
            atoms = data["counters"][j]
            ratio = np.float32(atoms[1]) / np.float32(atoms[0])
            # Independent source-data inspection: precisely one of the nine
            # taps has positive weight, and its stored levels are identical.
            tap_rows = np.array([24, 27, 30])
            tap_cols = np.array([2, 5, 8])
            s = stats[np.ix_(tap_rows, tap_cols)].astype(np.float32)
            r = recalled[np.ix_(tap_rows, tap_cols)].astype(np.float32)
            weight = r[..., 1] * r[..., 3]
            self.assertEqual(int(np.count_nonzero(weight)), 1)
            self.assertEqual(float(weight.sum()), 1)
            np.testing.assert_array_equal(s[..., 0][weight > 0], r[..., 0][weight > 0])
            self.assertEqual(float(s[..., 0][weight > 0][0]), .036468505859375)
            actual = np.float32(data["gain"][j, 27, 5])
            self.assertEqual(float(actual), .99951171875)
            for exp_mode in ("source_exp_f32", "dxil_exp2_f32"):
                result = anchor_gain_unstored(stats, recalled, int(data["k"][j]), ratio,
                                              frame_count=int(atoms[2]), frame_measured=True,
                                              policy="combined", exp_mode=exp_mode)
                self.assertFalse(result.frame_rejected)
                self.assertFalse(result.local_rejected[27, 5])
                self.assertEqual(float(result.fallback), 1)
                self.assertEqual(float(result.gain[27, 5]), 1)
                for rounding in ("rne", "rtz"):
                    # Neither final store can turn the exactly representable
                    # CPU value one into the previous half. Do not hide this
                    # residual with a half-ULP tolerance or another mask.
                    self.assertEqual(float(result.stored(rounding)[27, 5]), 1)
                    self.assertNotEqual(result.stored(rounding)[27, 5], actual)


if __name__ == "__main__":
    unittest.main(verbosity=2)
