"""Check useful arithmetic discriminators and explicit non-parity limits."""
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE/"src"))
sys.path.insert(0, str(HERE/"experiments"))
from native_subset import capped_history_variance, hybrid_select, seed_flat_patch
from causal_probes import reflection_probe, selector_probe


class CausalProbeContracts(unittest.TestCase):
    def test_flat_noiseless_patch_preserves_level(self):
        patch = np.full((5, 5, 3), .03125, np.float32)
        result, info = seed_flat_patch(patch)
        np.testing.assert_array_equal(result, patch[2, 2])
        self.assertGreater(info["weight_effective_support"], 20)

    def test_support_is_not_mutated_and_invalid_support_rejected(self):
        support = np.zeros((5, 5)); original = support.copy()
        result, info = seed_flat_patch(np.full((5, 5, 3), .5), support)
        np.testing.assert_array_equal(support, original)
        np.testing.assert_array_equal(result, np.full(3, .5))
        self.assertTrue(info["fallback_to_centre"])
        with self.assertRaises(ValueError):
            seed_flat_patch(np.ones((5, 5, 3)), np.full((5, 5), np.nan))
        with self.assertRaises(ValueError):
            seed_flat_patch(np.full((5, 5, 3), 65505))

    def test_count_only_uncertainty_is_falsified_by_correlated_input(self):
        independent = capped_history_variance(0.0)
        self.assertAlmostEqual(independent["actual_mean_variance"], 1/31)
        correlated = capped_history_variance(.85)
        self.assertGreater(correlated["actual_over_source_estimate"], 6)
        # Mutation: calling 1/count the true variance would fail this assertion.
        self.assertNotAlmostEqual(correlated["actual_mean_variance"], 1/16, places=2)

    def test_selector_and_gain_replacements_have_distinct_signatures(self):
        result = selector_probe()
        controls = result["controls"]
        self.assertEqual(controls["selector_only"]["replace_selector_only"]["rmse_from_fixed_selector_gain_truth"], 0)
        self.assertEqual(controls["gain_only"]["replace_gain_only"]["rmse_from_fixed_selector_gain_truth"], 0)
        self.assertGreater(controls["selector_only"]["replace_gain_only"]["rmse_from_fixed_selector_gain_truth"], 0)
        self.assertLess(result["different_latent_decomposition_max_output_error"], 1e-15)
        self.assertEqual(controls["both"]["freeze_output_first_frame"]["light_step_ratio_frame24_over23"], 1)

    def test_surface_motion_cannot_follow_moving_reflected_feature(self):
        result = reflection_probe()["controls"]
        self.assertGreater(result["surface_zero_motion"]["feature_mae"],
                           5*result["true_virtual_feature_motion"]["feature_mae"])
        self.assertGreater(result["true_virtual_feature_motion"]["first_light_change_feature_relative_error"], 0)


if __name__ == "__main__":
    unittest.main()
