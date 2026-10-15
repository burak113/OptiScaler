"""Response recovery is not allowed to introduce noisy input colour."""
import unittest
import numpy as np
from fsrd_nrd_rr_band_gain_prototype import RRBandGainRecovery,BandGainSettings
from test_fsrd_nrd_recovery_prototype import packet


class RRBandGainContracts(unittest.TestCase):
    def attenuation(self):
        noisy,rr,z,n,m = packet()
        rr[...,:3] += .4*(noisy[...,:3]-.5)
        return noisy,rr,z,n,m

    def test_known_attenuated_clean_band_is_recovered_from_rr(self):
        noisy,rr,z,n,m = self.attenuation()
        model = RRBandGainRecovery(BandGainSettings(anchor=0))
        for frame in range(2,18):out = model.step(noisy,rr,z,n,m,frame)
        self.assertLess(float(np.mean((out[...,:3]-noisy[...,:3])**2)),
                        .01*float(np.mean((rr[...,:3]-noisy[...,:3])**2)))
        self.assertLessEqual(model.last_stats['maximum_excess_gain'],3)
        self.assertTrue(np.array_equal(out[...,3],rr[...,3]))

    def test_first_reset_and_zero_roughness_are_exact(self):
        noisy,rr,z,n,m = self.attenuation()
        model = RRBandGainRecovery()
        for frame in range(2,9):self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,frame),rr))
        n &= np.uint32(~(1023<<20)&0xffffffff)
        for frame in range(9,34):self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,frame),rr))

    def test_raw_chroma_cannot_enter_an_achromatic_rr_band(self):
        noisy,rr,z,n,m = self.attenuation()
        noisy[...,:3] = np.array((.2,.5,.8))+(noisy[...,:3]-.5)
        model = RRBandGainRecovery(BandGainSettings(anchor=0))
        for frame in range(2,18):out = model.step(noisy,rr,z,n,m,frame)
        self.assertGreater(float(np.std(out[...,0])),float(np.std(rr[...,0])))
        self.assertTrue(np.array_equal(out[...,0],out[...,1]))
        self.assertTrue(np.array_equal(out[...,1],out[...,2]))

    def test_constant_rr_has_no_band_to_replace_with_noisy_input(self):
        noisy,rr,z,n,m = packet()
        model = RRBandGainRecovery(BandGainSettings(anchor=0))
        for frame in range(2,34):self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,frame),rr))

    def test_alternating_rr_noise_has_no_coherent_band(self):
        noisy,rr,z,n,m = self.attenuation()
        delta = rr-.5
        model = RRBandGainRecovery(BandGainSettings(anchor=0))
        for frame in range(2,66):
            sign = 1 if frame%2 else -1
            current = rr.copy();current[...,:3] = .5+delta[...,:3]*sign
            raw = noisy.copy();raw[...,:3] = .5+2*delta[...,:3]*sign
            self.assertTrue(np.array_equal(model.step(raw,current,z,n,m,frame),current))

    def test_current_rr_convergence_stops_gain_immediately(self):
        noisy,rr,z,n,m = self.attenuation()
        model = RRBandGainRecovery(BandGainSettings(anchor=0))
        for frame in range(2,18):model.step(noisy,rr,z,n,m,frame)
        self.assertTrue(np.array_equal(model.step(noisy,noisy,z,n,m,18),noisy))


if __name__ == '__main__':
    unittest.main()
