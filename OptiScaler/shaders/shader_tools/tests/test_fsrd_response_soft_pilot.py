"""Observable continuity, structure and causal-boundary falsifications."""
import inspect,json,unittest
import numpy as np
from fsrd_response_pilot import make_temporal_spectral_pilot
from fsrd_response_soft_pilot import make_soft_temporal_spectral_pilot as make


class SoftPilotTests(unittest.TestCase):
    def controls(self,n):
        result=np.zeros((n,3));result[0,0]=1;return result

    def wave(self,n=32,phase=None):
        y,x=np.indices((64,96));phase=np.zeros(n) if phase is None else np.asarray(phase)
        signal=.022*np.sin(2*np.pi*(5*x/96+3*y/64)+phase[:,None,None])
        clean=np.broadcast_to(.2+signal[...,None],(n,64,96,3)).copy()
        return clean+np.random.default_rng(91743).normal(0,.012,clean.shape),clean,signal

    def test_threshold_crossing_is_continuous_without_binary_support_jump(self):
        y,x=np.indices((80,128));signal=np.cos(2*np.pi*(11*x/128+7*y/80))
        noise=np.random.default_rng(417).normal(0,.012,(80,128,3))
        amplitude=np.linspace(.0007,.0018,80)
        raw=.2+noise[None]+amplitude[:,None,None,None]*signal[None,...,None]
        controls=np.zeros((len(raw),3));controls[:,0]=1
        soft,a,_=make(raw,controls);hard,ha,_=make_temporal_spectral_pilot(raw,controls)
        self.assertTrue(a.all());self.assertTrue(ha.all())
        soft_jump=float(np.max(abs(np.diff(soft,axis=0))))
        hard_jump=float(np.max(abs(np.diff(hard,axis=0))))
        input_jump=float(np.max(abs(np.diff(raw,axis=0))))
        self.assertLess(soft_jump,4*input_jump);self.assertGreater(hard_jump,5*soft_jump)

    def test_stable_wave_noise_reduces_without_erasing_contrast(self):
        raw,clean,signal=self.wave();p,a,d=make(raw,self.controls(len(raw)))
        self.assertTrue(a.all());self.assertLess(float(np.std((p-clean)[16:])),.05*float(np.std((raw-clean)[16:])))
        gain=float(np.sum((p[16:]-.2)*signal[16:,...,None])/np.sum(np.broadcast_to(signal[16:,...,None],p[16:].shape)**2))
        self.assertGreater(gain,.97);self.assertLess(gain,1.03);json.dumps(d,allow_nan=False)

    def test_weak_nyquist_detail_survives_mature_history_but_startup_shrinks(self):
        y,x=np.indices((80,128));signal=.001*(2*((x+y)%2)-1)
        clean=np.broadcast_to(.2+signal[None,...,None],(32,80,128,3)).copy()
        raw=clean+np.random.default_rng(618203).normal(0,.012,clean.shape)
        p,a,d=make(raw,self.controls(len(raw)));self.assertTrue(a.all())
        gain=lambda q:float(np.sum((q-.2)*signal[None,...,None])/np.sum(np.broadcast_to(signal[None,...,None],q.shape)**2))
        self.assertGreater(gain(p[16:]),.9);self.assertLess(gain(p[16:]),1.1)
        self.assertLess(gain(p[:1]),.95);self.assertIn('Weak genuine detail',d['limitations'][2])

    def test_fast_moving_wave_retains_current_phase(self):
        raw,_,signal=self.wave(phase=np.arange(32)*.8);p,a,_=make(raw,self.controls(len(raw)))
        self.assertTrue(a.all())
        for i in range(len(p)):
            expected=np.fft.rfft2(signal[i])[3,5];actual=np.fft.rfft2(p[i].mean(-1))[3,5]
            self.assertLess(abs(np.angle(actual/expected)),.05)

    def test_lighting_step_current_dc_is_exact_and_signed(self):
        raw,_,_=self.wave();raw[16:]+=.12;p,a,d=make(raw,self.controls(len(raw)))
        self.assertTrue(a.all());np.testing.assert_allclose(p.mean((1,2)),raw.mean((1,2)),rtol=0,atol=1e-14)
        self.assertGreater(float(p[16].mean()-p[15].mean()),.119)

    def test_reset_jitter_epochs_match_fresh_current_estimate(self):
        raw,_,_=self.wave();ctrl=self.controls(len(raw));ctrl[12,0]=1;ctrl[20:,1:]=[.25,.125]
        p,a,d=make(raw,ctrl)
        for i in (0,12,20):
            q,b,_=make(raw[i:i+1],self.controls(1));np.testing.assert_array_equal(p[i],q[0]);self.assertEqual(a[i],b[0])
            self.assertEqual(d['epoch_start_by_frame'][i],i);self.assertEqual(d['frames'][i]['preceding_observations'],0)
        self.assertLessEqual(max(f['total_observations'] for f in d['frames']),16)

    def test_future_isolation_and_inputs_are_immutable(self):
        raw,_,_=self.wave();ctrl=self.controls(len(raw));saved=raw.copy();sc=ctrl.copy()
        p,a,_=make(raw,ctrl);changed=raw.copy();changed[24:]*=1.5;q,b,_=make(changed,ctrl)
        np.testing.assert_array_equal(p[:24],q[:24]);np.testing.assert_array_equal(a[:24],b[:24])
        np.testing.assert_array_equal(raw,saved);np.testing.assert_array_equal(ctrl,sc)

    def test_negative_gibbs_prediction_falls_back_exactly_without_clipping(self):
        y,x=np.indices((48,64));box=(x>20)&(x<43)&(y>14)&(y<35)
        raw=.001+.2*box[None,...,None]+np.random.default_rng(4).uniform(0,.012,(1,48,64,3))
        p,a,d=make(raw,self.controls(1));self.assertFalse(a[0]);np.testing.assert_array_equal(p,raw)
        self.assertLess(d['frames'][0]['prediction_min'],0)

    def test_colored_common_weight_preserves_weak_channel_coherent_signal(self):
        y,x=np.indices((64,96));wave=np.sin(2*np.pi*(5*x/96+3*y/64))
        clean=.2+wave[None,...,None]*np.array([.04,.002,.003])
        raw=np.broadcast_to(clean,(32,64,96,3)).copy()+np.random.default_rng(77).normal(0,.012,(32,64,96,3))
        p,a,_=make(raw,self.controls(len(raw)));self.assertTrue(a.all())
        gain=np.sum((p[16:]-.2)*wave[None,...,None],axis=(0,1,2))/(16*np.sum(wave*wave)*np.array([.04,.002,.003]))
        np.testing.assert_allclose(gain,1,atol=.15)

    def test_shared_bias_and_correlated_coherent_noise_are_not_identifiable(self):
        raw,clean,_=self.wave();raw+=.01;p,a,d=make(raw,self.controls(len(raw)))
        self.assertTrue(a.all());self.assertGreater(float((p-clean).mean()),.009)
        self.assertIn('Shared persistent source bias',d['limitations'][7])
        self.assertIn('Correlated source noise and dense material',d['limitations'][1])
        self.assertIsNone(d['frames'][-1]['effective_independent_pixels'])

    def test_slow_phase_counterexample_remains_visible(self):
        raw,_,signal=self.wave(phase=np.arange(32)*.001);p,a,d=make(raw,self.controls(len(raw)));self.assertTrue(a.all())
        angle=np.angle(np.fft.rfft2(p[-1].mean(-1))[3,5]/np.fft.rfft2(signal[-1])[3,5])
        self.assertLess(float(angle),-.003);self.assertIn('Slow subthreshold',d['limitations'][5])

    def test_constant_and_invalid_source_boundary(self):
        raw=np.full((4,16,24,3),.2);ctrl=self.controls(len(raw));p,a,d=make(raw,ctrl)
        np.testing.assert_allclose(p,raw,atol=1e-14);self.assertTrue(a.all())
        self.assertEqual(list(inspect.signature(make).parameters),['raw','controls','history'])
        for value in (-.01,np.inf,65505):
            bad=raw.copy();bad[0,0,0,0]=value
            with self.assertRaises(ValueError):make(bad,ctrl)
        with self.assertRaises(ValueError):make(raw,ctrl,1)
        with self.assertRaises(ValueError):make(raw,ctrl[:-1])
        ctrl[1,0]=.5
        with self.assertRaises(ValueError):make(raw,ctrl)


if __name__=='__main__':unittest.main(verbosity=2)
