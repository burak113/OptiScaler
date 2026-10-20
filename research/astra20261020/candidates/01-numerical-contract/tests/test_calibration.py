"""Integration acceptance on frozen observations, not candidate-selected pixels."""
import unittest
import numpy as np

import calibrate
from numerical_contract.guards import colour_history_valid, colour_apply_pixel, require_unique_observable
from numerical_contract.storage import store_fp16, NonIdentifiableError


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.colour,_=calibrate.colour_calibration()
        cls.anchor=calibrate.anchor_calibration()

    def test_frozen_intermediates_are_exact_but_old_expected_soft2_is_not(self):
        profiles=self.colour['profiles']
        for name in ('frozen','source_sampler32'):
            for field in ('stats','history','gain','packed_normal','bilinear_output'):
                self.assertTrue(profiles[name]['vs_exported_expected'][field]['array_equal'])
        gap=profiles['frozen']['vs_exported_expected']['soft2_output']
        self.assertEqual(gap['max_abs'],2**-14)
        self.assertEqual(gap['nonzero_error_count'],1083)

    def test_hard_gate_gap_is_a_diagnostic_not_a_hidden_tolerance(self):
        decision=self.colour['decision_interventions']
        self.assertEqual(decision['ideal64_vs_frozen'],0)
        self.assertEqual(decision['observed8_vs_frozen'],9)
        self.assertEqual(decision['rne_vs_frozen'],6)
        self.assertFalse(self.colour['historical_gpu_gate_map_available'])

    def test_exact_missing_bits_reconstruction_is_actually_rejected(self):
        witness=self.colour['missing_bits_witness']['half_lobe_admissible_witness']
        self.assertTrue(witness['identical_exported_rr_rgb'])
        self.assertTrue(witness['all_lobes_nonnegative_fp16'])
        self.assertTrue(witness['exact_reconstruction_rejected'])
        self.assertGreater(witness['output_difference']['nonzero_error_count'],0)
        with self.assertRaises(NonIdentifiableError):
            require_unique_observable([np.array([1],np.float32),np.array([1.125],np.float32)])
        refined=self.colour['missing_bits_witness']['overlap_constrained_witness']
        self.assertTrue(refined['exact_reconstruction_rejected'])
        self.assertEqual(refined['known_region_changed_output_lanes'],0)
        self.assertEqual(refined['known_pixels'],12288)
        self.assertGreater(refined['outside_known_region_difference']['nonzero_error_count'],0)

    def test_actual_half_lobe_overlap_restores_identifiable_subset(self):
        overlap=self.colour['verified_overlap_recovery']
        self.assertEqual(overlap['baseline_vs_expected_on_observed_support']['changed'],13)
        self.assertTrue(overlap['restored_vs_expected_on_observed_support']['exact'])
        self.assertEqual(overlap['restored_vs_expected_on_observed_support']['elements'],36864)

    def test_anchor_calibration_stays_bounded_and_native_sums_stay_unidentified(self):
        self.assertEqual(self.anchor['summary']['combined']['frames'],133)
        self.assertEqual(self.anchor['summary']['native_policy']['frames'],7)
        for group in self.anchor['summary'].values():
            self.assertEqual(group['max_abs'],2**-11)
        for row in self.anchor['frames']:
            if row['group']!='native_policy':continue
            for bounds in row['bounds'].values():
                self.assertFalse(bounds['exact_totals_identifiable'])
                self.assertLessEqual(bounds['source_ratio_min'],bounds['source_ratio_estimate'])
                self.assertGreaterEqual(bounds['source_ratio_max'],bounds['source_ratio_estimate'])


class SourceGuardTests(unittest.TestCase):
    def test_float64_entire_mean_formula_cannot_replace_missing_store(self):
        from gpu_inputs import arithmetic_staging_case
        case=arithmetic_staging_case()
        self.assertEqual(case['f32_without_store'],case['f64_without_store'])
        self.assertTrue(case['f64_without_store_decision'])
        self.assertFalse(case['with_boundary_store_decision'])
    def test_signed_depth_inclusive_threshold_sentinel_and_viewport(self):
        z=np.array([-10,-10,10,10,10],np.float32)
        hist=np.array([-10,-10.2,10.21,0,10],np.float32)
        uv=np.full((5,2),.5,np.float32);uv[-1,0]=np.nextafter(np.float32(1),np.float32(2))
        np.testing.assert_array_equal(colour_history_valid(hist,z,np.zeros(5),uv),[1,1,0,0,0])

    def test_history_off_ignores_invalid_unused_values(self):
        first=colour_history_valid(None,np.ones((2,3)),None,None,history_enabled=False)
        second=colour_history_valid(object(),np.ones((2,3)),object(),object(),history_enabled=False)
        np.testing.assert_array_equal(first,second)
        self.assertFalse(first.any())

    def test_colour_current_source_authority_preserves_bytes(self):
        rng=np.random.default_rng(20261021)
        rgba=store_fp16(rng.uniform(.01,3,(7,11,4)),rounding='rtz')
        # No gain is inspected if every pixel takes the source-authority branch.
        np.testing.assert_array_equal(colour_apply_pixel(rgba,object(),0).view(np.uint32),rgba.view(np.uint32))
        np.testing.assert_array_equal(colour_apply_pixel(rgba,object(),object(),enabled=False).view(np.uint32),rgba.view(np.uint32))
        out=colour_apply_pixel(rgba,np.ones((7,11,3),np.float32),np.ones((7,11)))
        self.assertTrue((out[...,3]==1).all())


if __name__=='__main__':unittest.main()
