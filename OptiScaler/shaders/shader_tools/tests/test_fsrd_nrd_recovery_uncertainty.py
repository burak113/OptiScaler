"""Checks prevent a visually favourable replica from hiding the other one."""
import unittest
import numpy as np
from fsrd_nrd_recovery_uncertainty import PairedMSE


class PairedUncertaintyContracts(unittest.TestCase):
    def score(self,baseline,candidate,a,b):
        estimator = PairedMSE((0,0,4,4))
        image = np.ones((4,4,3))
        for frame in range(64):
            estimator.update(frame,image*baseline,image*candidate,dict(mean=image*(a+b)/2,a=image*a,b=image*b))
        return estimator.summarize()

    def test_equal_candidate_has_exact_zero_delta_and_interval(self):
        result = self.score(1,1,0,2)
        self.assertFalse(result['both_replicas_improve'])
        for values in result['references'].values():
            self.assertEqual(values['candidate_minus_baseline_mse'],0)
            self.assertEqual(values['paired_temporal_block_95'],[0,0])

    def test_true_shared_improvement_passes_both_replicas(self):
        result = self.score(1,0,0,0)
        self.assertTrue(result['both_replicas_improve'])
        self.assertTrue(result['both_replica_block_upper_below_zero'])
        self.assertEqual(result['references']['mean']['candidate_minus_baseline_mse'],-1)

    def test_shared_degradation_cannot_be_presented_as_improvement(self):
        result = self.score(0,.25,0,0)
        self.assertFalse(result['both_replicas_improve'])
        self.assertGreater(result['references']['a']['paired_temporal_block_95'][0],0)

    def test_disagreeing_replica_winners_fail_the_joint_claim(self):
        result = self.score(1,.5,0,2)
        self.assertLess(result['references']['a']['candidate_minus_baseline_mse'],0)
        self.assertGreater(result['references']['b']['candidate_minus_baseline_mse'],0)
        self.assertFalse(result['both_replicas_improve'])
        self.assertEqual(result['reference_replica_disagreement_rmse'],2)
        self.assertEqual(result['mean_reference_independent_mc_noise_rmse_estimate'],1)

    def test_frame_selection_and_missing_mean_are_rejected(self):
        image = np.ones((4,4,3))
        estimator = PairedMSE((0,0,4,4))
        with self.assertRaises(ValueError):estimator.update(1,image,image,dict(mean=image))
        with self.assertRaises(ValueError):estimator.update(0,image,image,dict(a=image,b=image))


if __name__ == '__main__':
    unittest.main()
