"""Meaningful source-only causal/history and failure controls; no AMD claim."""
import inspect,json,unittest
import numpy as np
from fsrd_response_pilot import make_pilot,_fit,make_constant_pilot,make_spectral_pilot,make_temporal_spectral_pilot

class PilotTests(unittest.TestCase):
    def fixture(self,frames=24,seed=31):
        y,x=np.indices((16,24));pattern=.5+.5*np.sin(.4*x+.2*y)
        d=np.broadcast_to((.08+.3*pattern)[None,...,None]*[.7,.85,1],(frames,16,24,3)).copy()
        s=np.full_like(d,.05);clean=.4*(d+s)+[.06,.07,.08]
        raw=clean+np.random.default_rng(seed).normal(0,.012,clean.shape)
        controls=np.zeros((frames,3));controls[0,0]=1
        return raw,d,s,controls,clean
    def test_no_clean_reference_parameter(self):
        self.assertFalse(any('truth' in n or 'clean' in n for n in inspect.signature(make_pilot).parameters))
    def test_early_history_and_bounded_state(self):
        c,d,s,ctrl,_=self.fixture();p,a,j=make_pilot(c,d,s,ctrl,history=8)
        self.assertFalse(a[:8].any());np.testing.assert_array_equal(p[:8],c[:8])
        self.assertTrue(a[8:].all());self.assertLessEqual(max(r['preceding_observations'] for r in j['frames']),8)
        json.dumps(j,allow_nan=False)
    def test_future_changes_do_not_affect_earlier_pilots(self):
        c,d,s,ctrl,_=self.fixture();p,a,_=make_pilot(c,d,s,ctrl)
        c2=c.copy();d2=d.copy();c2[18:]*=1.5;d2[18:]*=.5
        q,b,_=make_pilot(c2,d2,s,ctrl)
        np.testing.assert_array_equal(p[:18],q[:18]);np.testing.assert_array_equal(a[:18],b[:18])
    def test_reset_discards_prior_observations(self):
        c,d,s,ctrl,_=self.fixture();ctrl[12,0]=1;p,a,j=make_pilot(c,d,s,ctrl)
        self.assertFalse(a[12:20].any());self.assertTrue(j['frames'][12]['reset'])
        np.testing.assert_array_equal(p[12:20],c[12:20])
    def test_light_step_rejects_then_rebuilds_history(self):
        c,d,s,ctrl,_=self.fixture(frames=32);c[16:]*=1.6
        p,a,j=make_pilot(c,d,s,ctrl)
        self.assertFalse(a[16:24].any());self.assertEqual(j['frames'][16]['reason'],'innovation_rejected')
        self.assertTrue(a[24]);np.testing.assert_array_equal(p[16:24],c[16:24])
    def test_current_guide_keeps_material_translation(self):
        c,d,s,ctrl,clean=self.fixture();d[16:]=np.roll(d[16:],5,axis=2)
        # Current material movement is explained by current guides, without
        # using old RGB texture as an output replacement.
        c[16:]=.4*(d[16:]+s[16:])+[.06,.07,.08]+(c[16:]-clean[16:])
        p,a,_=make_pilot(c,d,s,ctrl)
        expected=.4*(d[16]+s[16])+[.06,.07,.08]
        self.assertTrue(a[16]);self.assertLess(np.sqrt(np.mean((p[16]-expected)**2)),.001)
    def test_invalid_guides_and_masks_cannot_enter_fit(self):
        c,d,s,ctrl,_=self.fixture();mask=np.ones(c.shape[:3],bool);mask[:,:,:4]=False
        d[:,:,:4]=np.nan;p,a,j=make_pilot(c,d,s,ctrl,valid_masks=mask)
        self.assertTrue(a[8:].all());np.testing.assert_array_equal(p[:,:,:4],c[:,:,:4])
        self.assertTrue(np.isfinite(p).all())
    def test_invalid_current_support_clears_history(self):
        c,d,s,ctrl,_=self.fixture();mask=np.ones(c.shape[:3],bool);mask[12]=False
        p,a,j=make_pilot(c,d,s,ctrl,valid_masks=mask)
        self.assertFalse(a[12:21].any());self.assertEqual(j['frames'][12]['reason'],'invalid_current_support')
    def test_shared_static_source_bias_remains_in_prediction(self):
        c,d,s,ctrl,clean=self.fixture();c+=.01
        p,a,_=make_pilot(c,d,s,ctrl)
        self.assertTrue(a[8:].all());self.assertGreater(np.mean((p-clean)[8:]),.009)
    def test_guide_independent_wave_is_unrepresented(self):
        c,d,s,ctrl,_=self.fixture();d[:]=.2;s[:]=.05
        y,x=np.indices(d.shape[1:3]);wave=.022*np.sin(.53*x+.21*y)
        c[:]=.2+wave[None,...,None]+np.random.default_rng(13).normal(0,.012,c.shape)
        p,a,j=make_pilot(c,d,s,ctrl)
        # If accepted, rank-zero guide prediction has no wave. Guard may reject.
        for i in np.flatnonzero(a):self.assertLess(p[i].std((0,1)).max(),1e-12)
        self.assertTrue('No restoration of guide-independent waves' in j['limitations'])
    def test_inputs_preserved_and_shape_validation(self):
        arrays=self.fixture();copies=[a.copy() for a in arrays[:4]];make_pilot(*arrays[:4])
        for before,after in zip(copies,arrays):np.testing.assert_array_equal(before,after)
        with self.assertRaises(ValueError):make_pilot(*arrays[:4],history=7)
        with self.assertRaises(ValueError):make_pilot(arrays[0],arrays[1][:-1],arrays[2],arrays[3])
    def test_constant_pilot_uses_observed_mean_from_first_frame(self):
        c,_,_,_,_=self.fixture();p,a,j=make_constant_pilot(c)
        self.assertTrue(a.all());self.assertLess(p.std((1,2)).max(),1e-14)
        np.testing.assert_allclose(p.mean((1,2)),c.mean((1,2)),rtol=0,atol=1e-14)
        json.dumps(j,allow_nan=False)
    def test_conservative_flat_classifier_rejects_supported_material(self):
        c,_,_,_,_=self.fixture();_,a,j=make_constant_pilot(c,require_flat=True)
        self.assertFalse(a.any())
    def test_flat_iid_source_activates_without_history_switch(self):
        c=np.broadcast_to([.14,.17,.2],(24,32,48,3)).copy()
        c+=np.random.default_rng(941).normal(0,.012,c.shape)
        _,a,_=make_constant_pilot(c,require_flat=True)
        self.assertTrue(a.all())
    def test_flat_classifier_rejects_coherent_wave(self):
        y,x=np.indices((32,48));c=.2+.022*np.sin(.53*x+.21*y)[None,...,None]
        c=np.broadcast_to(c,(24,32,48,3)).copy()
        c+=np.random.default_rng(941).normal(0,.012,c.shape)
        _,a,_=make_constant_pilot(c,require_flat=True);self.assertFalse(a.any())
    def test_low_contrast_material_can_pass_flat_heuristic(self):
        y,x=np.indices((32,48));c=.2+.001*np.sin(.53*x+.21*y)[None,...,None]
        c=np.broadcast_to(c,(24,32,48,3)).copy()
        c+=np.random.default_rng(941).normal(0,.012,c.shape)
        _,a,_=make_constant_pilot(c,require_flat=True)
        # Explicit limitation; a passing flat test is not proof of no detail.
        self.assertTrue(a.all())
    def test_high_frequency_real_texture_can_pass_flat_heuristic(self):
        y,x=np.indices((32,48));checker=2*((x+y)%2)-1
        c=np.broadcast_to(.2+.03*checker[None,...,None],(8,32,48,3)).copy()
        _,a,j=make_constant_pilot(c,require_flat=True)
        # Binomial cancellation and MAD inflation confuse clean Nyquist texture
        # with noise. This is a deliberate failed-classification counterexample.
        self.assertTrue(a.all());self.assertGreater(c.std(),.029)
    def test_guide_veto_rejects_real_checker_without_changing_pilot(self):
        y,x=np.indices((32,48));checker=(x+y)%2
        d=np.broadcast_to((.1+.3*checker)[None,...,None],(8,32,48,3)).copy();s=np.full_like(d,.05)
        c=.9*(d+s)+np.random.default_rng(941).normal(0,.012,d.shape)
        old,old_active,_=make_constant_pilot(c,require_flat=True)
        p,a,j=make_constant_pilot(c,require_flat=True,diff=d,spec=s,guard_guides=True)
        np.testing.assert_array_equal(old,p);self.assertTrue(old_active.all());self.assertFalse(a.any())
        self.assertIsNone(j['frames'][0]['guide_rejection']['effective_spatial_samples'])
    def test_guide_veto_leaves_independent_fake_island_eligible(self):
        y,x=np.indices((32,48));island=((x-20)**2+(y-16)**2)<64
        d=np.broadcast_to((.2+.28*island)[None,...,None],(8,32,48,3)).copy();s=np.full_like(d,.05)
        c=.2+np.random.default_rng(941).normal(0,.012,d.shape)
        _,a,_=make_constant_pilot(c,require_flat=True,diff=d,spec=s,guard_guides=True)
        self.assertTrue(a.all())
    def test_same_frame_noise_guide_coupling_can_only_veto(self):
        c=.2+np.random.default_rng(941).normal(0,.012,(8,32,48,3))
        d=np.full_like(c,.2);s=.2+.5*(c-.2)
        _,a,_=make_constant_pilot(c,require_flat=True,diff=d,spec=s,guard_guides=True)
        self.assertFalse(a.any())
    def test_weak_real_material_below_cutoff_remains_ambiguous(self):
        y,x=np.indices((32,48));checker=(x+y)%2
        d=np.broadcast_to((.2+.001*checker)[None,...,None],(8,32,48,3)).copy();s=np.full_like(d,.05)
        c=.9*(d+s)+np.random.default_rng(941).normal(0,.012,d.shape)
        _,a,_=make_constant_pilot(c,require_flat=True,diff=d,spec=s,guard_guides=True)
        self.assertTrue(a.all())
    def test_guide_veto_requires_valid_optional_sources(self):
        c,_,_,_,_=self.fixture()
        with self.assertRaises(ValueError):make_constant_pilot(c,guard_guides=True)


class SpectralTests(unittest.TestCase):
    def test_current_source_only_and_no_future_dependence(self):
        self.assertEqual(list(inspect.signature(make_spectral_pilot).parameters),['raw'])
        c=.2+np.random.default_rng(12).normal(0,.012,(4,32,48,3));copy=c.copy()
        p,a,j=make_spectral_pilot(c);c[2:]*=1.4;q,b,_=make_spectral_pilot(c)
        np.testing.assert_array_equal(p[:2],q[:2]);np.testing.assert_array_equal(a[:2],b[:2])
        np.testing.assert_array_equal(copy[:2],c[:2]);json.dumps(j,allow_nan=False)
    def test_constant_noise_reduction_and_nominal_sigma(self):
        c=.2+np.random.default_rng(41).normal(0,.012,(8,64,96,3))
        p,a,j=make_spectral_pilot(c)
        self.assertTrue(a.all());self.assertLess(np.sqrt(np.mean((p-.2)**2)),.0003)
        sigma=np.mean([r['nominal_iid_pixel_sigma'] for r in j['frames']])
        self.assertAlmostEqual(sigma,.012,delta=.0005)
        self.assertLess(abs(p.mean((1,2))-c.mean((1,2))).max(),1e-13)
    def test_weak_checker_retained_above_frozen_threshold(self):
        y,x=np.indices((80,128));signal=.001*(2*((x+y)%2)-1)
        c=.2+signal[None,...,None]+np.random.default_rng(618203).normal(0,.012,(8,80,128,3))
        p,a,_=make_spectral_pilot(c)
        gain=np.sum((p-.2)*signal[None,...,None])/np.sum(np.broadcast_to(signal[None,...,None],p.shape)**2)
        self.assertTrue(a.all());self.assertAlmostEqual(float(gain),1,delta=.1)
        self.assertLess(np.sqrt(np.mean((p-(.2+signal[None,...,None]))**2)),.0003)
    def test_strong_clean_checker_preserved(self):
        y,x=np.indices((32,48));c=np.broadcast_to(.2+.06*(2*((x+y)%2)-1)[None,...,None],(4,32,48,3)).copy()
        p,a,_=make_spectral_pilot(c);self.assertTrue(a.all());np.testing.assert_allclose(p,c,atol=1e-13)
    def test_current_wave_phase_preserved_without_guide(self):
        y,x=np.indices((64,96));phase=np.arange(8)*.8
        signal=.022*np.sin(2*np.pi*(5*x/96+3*y/64)+phase[:,None,None])
        c=.2+signal[...,None]+np.random.default_rng(91743).normal(0,.012,(8,64,96,3))
        p,a,_=make_spectral_pilot(c);self.assertTrue(a.all())
        for i in range(8):
            expected=np.fft.rfft2(signal[i])[3,5];actual=np.fft.rfft2((p[i]-.2).mean(-1))[3,5]
            self.assertLess(abs(np.angle(actual/expected)),.05)
    def test_persistent_coherent_source_bias_is_not_identifiable(self):
        y,x=np.indices((64,96));bias=.015*np.sin(2*np.pi*3*x/96)
        c=.2+bias[None,...,None]+np.random.default_rng(941).normal(0,.012,(8,64,96,3))
        p,a,j=make_spectral_pilot(c);self.assertTrue(a.all())
        self.assertGreater(np.sqrt(np.mean((p-.2)**2)),.01)
        self.assertIn('Shared persistent source bias is unidentifiable',j['limitations'])
    def test_invalid_source_rejected_and_unclamped_output_recorded(self):
        c=np.full((1,32,48,3),.2);c[0,0,0,0]=np.nan
        with self.assertRaises(ValueError):make_spectral_pilot(c)
        y,x=np.indices((48,64));box=(x>20)&(x<43)&(y>14)&(y<35)
        c=.001+.2*box[None,...,None]+np.random.default_rng(4).uniform(0,.012,(1,48,64,3))
        p,a,j=make_spectral_pilot(c)
        self.assertFalse(a[0]);np.testing.assert_array_equal(p,c)
        self.assertLess(j['frames'][0]['prediction_min'],0)

class TemporalSpectralTests(unittest.TestCase):
    def controls(self,n):
        result=np.zeros((n,3));result[0,0]=1;return result
    def wave(self,n=32,phase=None):
        y,x=np.indices((64,96));phase=np.zeros(n) if phase is None else np.asarray(phase)
        signal=.022*np.sin(2*np.pi*(5*x/96+3*y/64)+phase[:,None,None])
        clean=np.broadcast_to(.2+signal[...,None],(n,64,96,3)).copy()
        raw=clean+np.random.default_rng(91743).normal(0,.012,clean.shape)
        return raw,clean,signal
    def test_stable_periodic_wave_temporal_noise_reduction(self):
        c,clean,_=self.wave();p,a,j=make_temporal_spectral_pilot(c,self.controls(len(c)))
        stateless,_,_=make_spectral_pilot(c)
        self.assertTrue(a.all())
        self.assertLess(np.std((p-clean)[16:]),.6*np.std((stateless-clean)[16:]))
        self.assertLessEqual(max(r['total_observations'] for r in j['frames']),16)
        np.testing.assert_allclose(p.mean((1,2)),c.mean((1,2)),rtol=0,atol=1e-14)
        json.dumps(j,allow_nan=False)
    def test_large_phase_and_light_changes_keep_current_information(self):
        phase=np.arange(32)*.8;c,clean,signal=self.wave(phase=phase)
        c[16:]+=.12;clean[16:]+=.12
        p,a,j=make_temporal_spectral_pilot(c,self.controls(len(c)));self.assertTrue(a.all())
        for i in range(len(c)):
            expected=np.fft.rfft2(signal[i])[3,5];actual=np.fft.rfft2(p[i].mean(-1))[3,5]
            self.assertLess(abs(np.angle(actual/expected)),.05)
        np.testing.assert_allclose(p.mean((1,2)),c.mean((1,2)),rtol=0,atol=1e-14)
        self.assertGreater(j['frames'][16]['current_innovation_frequencies'],0)
    def test_reset_jitter_and_future_isolation(self):
        c,_,_=self.wave();ctrl=self.controls(len(c));ctrl[12,0]=1;ctrl[20:,1:]=[.25,.125]
        copy=c.copy();control_copy=ctrl.copy();p,a,j=make_temporal_spectral_pilot(c,ctrl)
        stateless,_,_=make_spectral_pilot(c)
        for index in (0,12,20):
            np.testing.assert_allclose(p[index],stateless[index],rtol=0,atol=1e-14)
            self.assertEqual(j['frames'][index]['preceding_observations'],0)
            self.assertEqual(j['epoch_start_by_frame'][index],index)
        c2=c.copy();c2[24:]*=1.5;q,b,_=make_temporal_spectral_pilot(c2,ctrl)
        np.testing.assert_array_equal(p[:24],q[:24]);np.testing.assert_array_equal(a[:24],b[:24])
        np.testing.assert_array_equal(copy,c);np.testing.assert_array_equal(control_copy,ctrl)
    def test_weak_checker_contrast_retained(self):
        y,x=np.indices((80,128));signal=.001*(2*((x+y)%2)-1)
        clean=np.broadcast_to(.2+signal[None,...,None],(24,80,128,3)).copy()
        c=clean+np.random.default_rng(618203).normal(0,.012,clean.shape)
        p,a,_=make_temporal_spectral_pilot(c,self.controls(len(c)));self.assertTrue(a.all())
        gain=np.sum((p[16:]-.2)*signal[None,...,None])/np.sum(np.broadcast_to(signal[None,...,None],p[16:].shape)**2)
        self.assertAlmostEqual(float(gain),1,delta=.1)
    def test_persistent_shared_bias_remains_unidentifiable(self):
        c,clean,signal=self.wave();c+=.01
        p,a,j=make_temporal_spectral_pilot(c,self.controls(len(c)))
        self.assertTrue(a.all());self.assertGreater((p-clean).mean(),.009)
        # A coherent apparent wave is retained even if its actual provenance is bias.
        self.assertGreater(np.std(p[16:].mean(0)),.014)
        self.assertIn('Shared persistent source bias is unidentifiable',j['limitations'])
    def test_gibbs_negative_falls_back_without_clipping(self):
        y,x=np.indices((48,64));box=(x>20)&(x<43)&(y>14)&(y<35)
        c=.001+.2*box[None,...,None]+np.random.default_rng(4).uniform(0,.012,(1,48,64,3))
        p,a,j=make_temporal_spectral_pilot(c,self.controls(1))
        self.assertFalse(a[0]);np.testing.assert_array_equal(p,c)
        self.assertLess(j['frames'][0]['prediction_min'],0)
    def test_slow_subthreshold_phase_can_lag(self):
        phase=np.arange(32)*.001;c,clean,signal=self.wave(phase=phase)
        p,a,j=make_temporal_spectral_pilot(c,self.controls(len(c)))
        expected=np.fft.rfft2(signal[-1])[3,5];actual=np.fft.rfft2(p[-1].mean(-1))[3,5]
        # Deliberate limitation: history is not motion compensation.
        self.assertLess(float(np.angle(actual/expected)),-.003)
        self.assertIn('Slow subthreshold phase changes can lag',j['limitations'])
    def test_validation_and_source_only_signature(self):
        self.assertEqual(list(inspect.signature(make_temporal_spectral_pilot).parameters),['raw','controls','history'])
        c,_,_=self.wave(4);ctrl=self.controls(4)
        with self.assertRaises(ValueError):make_temporal_spectral_pilot(c,ctrl,history=1)
        with self.assertRaises(ValueError):make_temporal_spectral_pilot(c,ctrl[:-1])
        ctrl[1,0]=.5
        with self.assertRaises(ValueError):make_temporal_spectral_pilot(c,ctrl)

if __name__=='__main__':unittest.main(verbosity=2)
