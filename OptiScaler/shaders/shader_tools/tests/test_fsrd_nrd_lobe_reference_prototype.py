"""Deterministic contracts for the NRD adaptation of the existing lobe method."""
import unittest
import numpy as np

from fsrd_nrd_lobe_reference_prototype import LobeReferenceRecovery,ReferenceSettings
from test_fsrd_nrd_recovery_prototype import packet


class LobeReferenceContracts(unittest.TestCase):
    def test_cold_and_roughness_zero_are_exact(self):
        for roughness,frames in ((.12,range(2,9)),(0,range(2,34))):
            noisy,rr,z,n,m = packet(roughness=roughness)
            operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
            for frame in frames:
                self.assertTrue(np.array_equal(operator.step(noisy,rr,z,n,m,frame),rr))

    def test_rr_convergence_cannot_double_add_a_historical_band(self):
        noisy,rr,z,n,m = packet()
        operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
        for frame in range(2,18):
            out = operator.step(noisy,rr,z,n,m,frame)
        self.assertGreater(float(np.std(out[...,0])),.01)
        self.assertTrue(np.array_equal(operator.step(noisy,noisy,z,n,m,18),noisy))

    def test_alpha_and_energy_are_preserved_and_negative_is_bounded(self):
        noisy,rr,z,n,m = packet()
        operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
        for frame in range(2,18):
            out = operator.step(noisy,rr,z,n,m,frame)
        self.assertTrue(np.array_equal(out[...,3],rr[...,3]))
        self.assertTrue(np.all(out[...,:3] >= .75*rr[...,:3]))
        bound = 10*np.finfo(np.float32).eps*rr.shape[0]*rr.shape[1]*float(rr[...,:3].max())
        self.assertLessEqual(float(np.max(np.abs(np.sum((out-rr)[...,:3],axis=(0,1))))),bound)

    def test_alternating_flat_noise_is_not_recovered(self):
        noisy,rr,z,n,m = packet()
        delta = noisy-rr
        operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
        for frame in range(2,66):
            value = rr+delta*(1 if frame%2 else -1)
            self.assertTrue(np.array_equal(operator.step(value,rr,z,n,m,frame),rr))

    def test_exact_rr_raw_control_is_unchanged_after_maturity(self):
        noisy,_,z,n,m = packet()
        operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
        for frame in range(2,34):
            value = noisy.copy()
            value[...,:3] += (frame%3-1)*.02
            self.assertTrue(np.array_equal(operator.step(value,value,z,n,m,frame),value))

    def test_current_depth_and_normal_edges_are_never_recovered(self):
        noisy,rr,z,n,m = packet()
        n[:,16:] = np.uint32(1023 | (512<<10) | (123<<20))
        z[16:] = -3
        operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
        for frame in range(2,18):
            out = operator.step(noisy,rr,z,n,m,frame)
        self.assertTrue(np.array_equal(out[:,15:17],rr[:,15:17]))
        self.assertTrue(np.array_equal(out[15:17],rr[15:17]))

    def test_disocclusion_gap_resize_and_off_clear_histories(self):
        noisy,rr,z,n,m = packet()
        operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
        for frame in range(2,18):operator.step(noisy,rr,z,n,m,frame)
        self.assertTrue(np.array_equal(operator.step(noisy,rr,z+4,n,m,18),rr))
        self.assertTrue(np.array_equal(operator.step(noisy,rr,z,n,m,40),rr))
        args = packet(17,23)
        self.assertTrue(np.array_equal(operator.step(*args,41),args[1]))
        off = LobeReferenceRecovery(ReferenceSettings(strength=0))
        off.step(noisy,rr,z,n,m,2)
        self.assertIsNone(off.reference)

    def test_bad_jitter_is_rejected(self):
        args = packet()
        for jitter in ((1,0),(float('nan'),0),(0,)):
            with self.assertRaises(ValueError):LobeReferenceRecovery().step(*args,2,jitter=jitter)

    def test_jitter_delta_is_removed_exactly_once_from_reference_grid(self):
        noisy,rr,z,n,m = packet()
        operator = LobeReferenceRecovery(ReferenceSettings(anchor=0))
        operator.step(noisy,rr,z,n,m,2,jitter=(-.25,0))
        # World/camera static. Pixel-grid motion is Jprev-Jcur =-.5 pixel.
        m[...,0] = -.5/rr.shape[1]
        guide = (z,operator.reference['normal'],operator.reference['roughness'],
                 operator.reference['material'],np.ones(z.shape,bool))
        value,_,_,_,valid = operator.read_reference(guide,m,np.array((.25,0),np.float32))
        self.assertTrue(valid.all())
        self.assertTrue(np.array_equal(value,noisy[...,:3]))


if __name__ == '__main__':
    unittest.main()
