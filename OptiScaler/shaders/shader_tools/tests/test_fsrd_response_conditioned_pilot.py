"""Noise/lighting/correspondence falsifications for source-only DC conditioning."""
import unittest
import numpy as np
from fsrd_response_pilot import make_temporal_spectral_pilot
from fsrd_response_conditioned_pilot import make_dc_conditioned_pilot


class DCPilotTests(unittest.TestCase):
    def source(self,frames=64):
        rng=np.random.default_rng(140731)
        raw=.2+rng.normal(0,.012,(frames,64,96,3))
        controls=np.zeros((frames,3));controls[0,0]=1
        return raw,controls

    def test_quiet_dc_noise_decreases_without_erasing_non_dc_structure(self):
        raw,ctrl=self.source();y,x=np.indices(raw.shape[1:3])
        raw+=.02*np.cos(2*np.pi*x/96)[None,...,None]
        old,oa,_=make_temporal_spectral_pilot(raw,ctrl)
        new,na,_=make_dc_conditioned_pilot(raw,ctrl)
        self.assertTrue(na.all());np.testing.assert_array_equal(na,oa)
        self.assertLess(float(new[-16:].mean((1,2)).std(0).mean()),
                        .65*float(old[-16:].mean((1,2)).std(0).mean()))
        np.testing.assert_allclose(new-new.mean((1,2),keepdims=True),
                                   old-old.mean((1,2),keepdims=True),atol=1e-14)

    def test_bright_step_uses_current_mean_immediately(self):
        raw,ctrl=self.source();raw[32:]+=.12
        pilot,active,d=make_dc_conditioned_pilot(raw,ctrl)
        self.assertTrue(d['frames'][32]['dc_innovation'])
        np.testing.assert_allclose(pilot[32].mean((0,1)),raw[32].mean((0,1)),atol=1e-14)
        self.assertTrue(active.all())

    def test_one_channel_light_step_selects_all_current_rgb(self):
        raw,ctrl=self.source();raw[32:,...,1]+=.1
        pilot,_,d=make_dc_conditioned_pilot(raw,ctrl)
        self.assertTrue(d['frames'][32]['dc_innovation'])
        np.testing.assert_allclose(pilot[32].mean((0,1)),raw[32].mean((0,1)),atol=1e-14)

    def test_reset_and_jitter_cut_global_mean_history(self):
        raw,ctrl=self.source();ctrl[24,0]=1;ctrl[48:,1:]=[.25,-.125]
        pilot,_,d=make_dc_conditioned_pilot(raw,ctrl)
        for i in (0,24,48):
            self.assertEqual(d['frames'][i]['preceding_observations'],0)
            np.testing.assert_allclose(pilot[i].mean((0,1)),raw[i].mean((0,1)),atol=1e-14)

    def test_future_change_cannot_affect_prior_output(self):
        raw,ctrl=self.source();a,aa,_=make_dc_conditioned_pilot(raw,ctrl)
        changed=raw.copy();changed[41:]+=.1;b,ba,_=make_dc_conditioned_pilot(changed,ctrl)
        np.testing.assert_array_equal(a[:41],b[:41]);np.testing.assert_array_equal(aa[:41],ba[:41])

    def test_dc_subthreshold_real_drift_is_explicit_counterexample(self):
        raw,ctrl=self.source()
        # Fix each constructed noise realization's mean to zero, so a random
        # final sample cannot conceal the deterministic lighting lag.
        raw=raw-raw.mean((1,2),keepdims=True)+.2
        raw+=np.arange(len(raw))[:,None,None,None]*1e-5
        p,_,d=make_dc_conditioned_pilot(raw,ctrl)
        self.assertLess(float(p[-1].mean()),float(raw[-1].mean()))
        self.assertIn('Subthreshold',d['limitations'][1])

    def test_history_count_is_bounded_and_constant_source_is_unchanged(self):
        raw,ctrl=self.source();raw[:]=.2;p,active,d=make_dc_conditioned_pilot(raw,ctrl)
        np.testing.assert_allclose(p,raw,rtol=0,atol=1e-14);self.assertTrue(active.all())
        self.assertEqual(max(r['total_observations'] for r in d['frames']),16)

    def test_invalid_observed_radiance_is_rejected(self):
        raw,ctrl=self.source();raw[0,0,0,0]=-.01
        with self.assertRaises(ValueError):make_dc_conditioned_pilot(raw,ctrl)


if __name__=='__main__':unittest.main()
