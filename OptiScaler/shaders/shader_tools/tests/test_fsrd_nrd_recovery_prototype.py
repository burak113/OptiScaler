"""Operator contracts, not a signed-RR or game-quality substitute."""
from dataclasses import replace
import unittest
import numpy as np
from fsrd_nrd_recovery_prototype import Recovery, Settings, down, up


def packet(height=32, width=32, roughness=.12):
    rr = np.full((height,width,4), .5, np.float32)
    rr[...,3] = 9
    depth = np.full((height,width), -8, np.float32)
    words = np.full((height,width), 512 | (512<<10) | (int(round(roughness*1023))<<20), np.uint32)
    motion = np.zeros((height,width,4), np.float32)
    motion[...,3] = 1
    yy,xx = np.mgrid[:height,:width]
    noisy = rr.copy()
    noisy[...,:3] += np.where((xx+yy)%2, .05, -.05)[...,None]
    return noisy,rr,depth,words,motion


class RecoveryContracts(unittest.TestCase):
    def test_constant_odd_pyramid(self):
        value = np.full((17,23,3), .25, np.float32)
        for _ in range(6):
            coarse = down(value)
            self.assertTrue(np.array_equal(up(coarse,value.shape[:2]),value))
            value = coarse

    def test_off_is_exact_and_has_no_history(self):
        noisy,rr,z,n,m = packet()
        model = Recovery(Settings(strength=0))
        self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,2),rr))
        self.assertIsNone(model.states)

    def test_equal_noisy_and_rr_never_adds_a_band(self):
        _,rr,z,n,m = packet()
        model = Recovery(Settings(anchor=0))
        for frame in range(2,18):
            self.assertTrue(np.array_equal(model.step(rr,rr,z,n,m,frame),rr))

    def test_first_reset_and_cold_history_are_exact_noops(self):
        noisy,rr,z,n,m = packet()
        model = Recovery(Settings(anchor=0))
        for frame in range(2,9):
            self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,frame),rr))

    def test_zero_roughness_is_never_ordinary_lobe_recovery(self):
        noisy,rr,z,n,m = packet(roughness=0)
        model = Recovery(Settings(anchor=0))
        for frame in range(2,34):
            self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,frame),rr))

    def test_supported_lost_band_is_signed_dc_neutral_and_alpha_exact(self):
        noisy,rr,z,n,m = packet()
        model = Recovery(Settings(anchor=0))
        for frame in range(2,18):
            out = model.step(noisy,rr,z,n,m,frame)
        self.assertGreater(float(np.std(out[...,0])), .01)
        self.assertTrue(np.array_equal(out[...,3],rr[...,3]))
        self.assertTrue(np.isfinite(out).all() and (out[...,:3]>=0).all())
        # Explicit accumulated FP32 arithmetic bound, not an image-quality gate.
        bound = 10*np.finfo(np.float32).eps*rr.shape[0]*rr.shape[1]*float(rr[...,:3].max())
        self.assertLessEqual(float(np.max(np.abs(np.sum((out-rr)[...,:3],axis=(0,1))))),bound)

    def test_disocclusion_and_frame_gap_restart_before_any_correction(self):
        noisy,rr,z,n,m = packet()
        model = Recovery(Settings(anchor=0))
        for frame in range(2,18):model.step(noisy,rr,z,n,m,frame)
        z = np.full_like(z,-3)
        for frame in range(18,25):
            self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,frame),rr))
        self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,40),rr))

    def test_alternating_zero_mean_noise_cannot_be_supported_detail(self):
        noisy,rr,z,n,m = packet()
        error = noisy-rr
        model = Recovery(Settings(anchor=0))
        for frame in range(2,66):
            current = rr+error*(1 if frame%2 else -1)
            self.assertTrue(np.array_equal(model.step(current,rr,z,n,m,frame),rr))

    def test_material_change_and_invalid_motion_restart(self):
        noisy,rr,z,n,m = packet()
        model = Recovery(Settings(anchor=0))
        for frame in range(2,18):model.step(noisy,rr,z,n,m,frame)
        self.assertTrue(np.array_equal(model.step(noisy,rr,z,n|(1<<30),m,18),rr))
        m[...,3] = 0
        self.assertTrue(np.array_equal(model.step(noisy,rr,z,n,m,19),rr))

    def test_current_normal_edge_has_no_recovery_halo(self):
        noisy,rr,z,n,m = packet()
        n[:,16:] = np.uint32(1023 | (512<<10) | (123<<20))
        model = Recovery(Settings(anchor=0))
        for frame in range(2,18):
            out = model.step(noisy,rr,z,n,m,frame)
        self.assertTrue(np.array_equal(out[:,15:17],rr[:,15:17]))
        self.assertGreater(float(np.std(out[:,:8,0])), .01)

    def test_nonfinite_lighting_fails_before_recovery(self):
        noisy,rr,z,n,m = packet()
        noisy[0,0,0] = np.nan
        with self.assertRaises(ValueError):Recovery().step(noisy,rr,z,n,m,2)


if __name__ == '__main__':
    unittest.main()
