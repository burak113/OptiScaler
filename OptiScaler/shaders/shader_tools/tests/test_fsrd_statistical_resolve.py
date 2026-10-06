"""Numerical contracts; passing these is not image-quality acceptance."""
import unittest
import numpy as np
from fsrd_small_regression import nnls_small, applied_fit
from fsrd_statistical_resolve import resolve, observation_evidence


class RegressionTests(unittest.TestCase):
    def test_seed44_applied_model_is_validated(self):
        rng=np.random.default_rng(44);n,k=40,16
        d=rng.uniform(.03,.5,n+k);s=.14+.08*rng.uniform(0,1,n+k)
        x=np.stack((d[:n],s[:n]),1);v=np.stack((d[n:],s[n:]),1)
        y=s[:n]+rng.normal(0,.055,n);t=s[n:]+rng.normal(0,.055,k)
        ols=np.linalg.lstsq(x,y,rcond=None)[0]
        common=np.dot(x.sum(1),y)/np.dot(x.sum(1),x.sum(1))
        gate=.8*np.sqrt(np.mean((t-v.sum(1)*common)**2))
        coef,cov,train,held=applied_fit(x,y,v,t)
        self.assertGreater(np.sqrt(np.mean((t-v@np.maximum(ols,0))**2)),gate)
        self.assertLess(held,gate)
        self.assertAlmostEqual(held,np.sqrt(np.mean((t-v@coef)**2)),places=14)
        self.assertAlmostEqual(train,np.sqrt(np.mean((y-x@coef)**2)),places=14)
        self.assertGreater(cov[0,0],0) # Boundary coefficient is not certain.
        self.assertAlmostEqual(coef[0],0,places=12)

    def test_kkt_conditions_1000_designs(self):
        rng=np.random.default_rng(290929)
        for _ in range(1000):
            x=rng.uniform(.01,1,(32,int(rng.integers(1,4))))*10**rng.uniform(-2,2)
            y=rng.normal(.3,.2,32);k=nnls_small(x,y);g=x.T@(x@k-y)
            tolerance=1e-8*max(1,np.linalg.norm(x)*np.linalg.norm(y))
            self.assertTrue(np.all(k>=0))
            self.assertTrue(np.all(g>=-tolerance))
            self.assertTrue(np.all(abs(g[k>1e-10])<tolerance))

    def test_singular_and_empty_models(self):
        x=np.arange(1,31,dtype=float)
        a=np.c_[x,2*x,np.ones(30)]
        np.testing.assert_allclose(a@nnls_small(a,3*x+.2),3*x+.2,atol=1e-10)
        np.testing.assert_array_equal(nnls_small(np.zeros((10,3)),np.ones(10)),np.zeros(3))
        with self.assertRaises(ValueError): nnls_small(np.ones((3,4)),np.ones(3))


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.rng=np.random.default_rng(931)
        self.f=self.rng.uniform(.05,.8,(24,32,3,3))
        self.z=np.full((24,32),10.);self.n=np.zeros((24,32,3));self.n[...,2]=-1
        self.r=np.full((24,32),.5)
        self.c=.4+.2*self.f[...,0]-.1*self.f[...,1]+.3*self.f[...,2]

    def run_model(self,c=None,features=None,**kwargs):
        c=self.c if c is None else c
        return resolve(c,self.f if features is None else features,c+.08,self.z,self.n,self.r,**kwargs)

    def test_signed_affine_reconstruction_and_residual(self):
        out,d=self.run_model(require_independence=False)
        np.testing.assert_allclose(out,self.c,atol=1e-11)
        np.testing.assert_allclose(d['residual'],self.c-d['prediction'],atol=1e-14)
        self.assertTrue((d['delta']<0).all())
        self.assertTrue((d['confidence']>.99).all())
        np.testing.assert_allclose(d['coefficients'][...,0]+np.sum(d['coefficients'][...,1:]*self.f,axis=-1),
                                   d['prediction'],atol=1e-11)

    def test_no_independence_is_a_fallback_not_success(self):
        out,d=self.run_model()
        np.testing.assert_array_equal(out,self.c+.08)
        self.assertFalse(d['confidence'].any())

    def test_cloned_observations_are_not_four_samples(self):
        out,d=self.run_model(history_raw=np.repeat(self.c[None],4,0),stream_ids=list(range(4)))
        self.assertEqual(d['effective_observations'],1)
        self.assertFalse(d['confidence'].any())

    def test_early_history_and_reset_are_rejected(self):
        hist=self.c+self.rng.normal(0,.001,(4,*self.c.shape))
        for kwargs in (dict(history_raw=hist[:2],stream_ids=[0,1]),
                       dict(history_raw=hist,stream_ids=[0,1,2,3],reset=True)):
            out,d=self.run_model(**kwargs)
            self.assertFalse(d['confidence'].any())

    def test_disocclusion_correspondence_rejected(self):
        out,d=self.run_model(require_independence=False,correspondence=np.zeros(self.z.shape,bool))
        self.assertFalse(d['confidence'].any())
        self.assertTrue((d['reason']==8).all())

    def test_stale_lighting_rejected(self):
        hist=self.c-.1+self.rng.normal(0,.001,(4,*self.c.shape))
        out,d=self.run_model(history_raw=hist,stream_ids=list(range(4)))
        self.assertFalse(d['confidence'].any())
        self.assertTrue((d['reason']==9).all())

    def test_feature_uncertainty_rejected(self):
        out,d=self.run_model(require_independence=False,feature_variance=np.ones_like(self.f))
        self.assertFalse(d['confidence'].any())
        self.assertTrue((d['reason']==6).all())

    def test_same_observation_noise_leak_is_exposed(self):
        noise=self.rng.normal(0,.01,self.c.shape)
        c=.2+noise;f=np.stack((np.full_like(c,.1),.2+.5*noise,np.full_like(c,.3)),-1)
        out,d=self.run_model(c, f,require_independence=False)
        np.testing.assert_allclose(out,c,atol=1e-11)
        self.assertGreater(np.sqrt(np.mean((out-.2)**2)),.009)

    def test_exposure_equivariance_and_invalid_dimensions(self):
        a,_=self.run_model(require_independence=False)
        b,_=resolve(3*self.c,self.f,3*(self.c+.08),self.z,self.n,self.r,require_independence=False)
        np.testing.assert_allclose(b,3*a,atol=1e-10)
        with self.assertRaises(ValueError): self.run_model(features=self.f[:-1])
        with self.assertRaises(ValueError): self.run_model(history_raw=np.ones((4,23,32,3)))

    def test_raw_increment_correlation_reduces_effective_count(self):
        a=self.rng.normal(.2,.01,(4,8,24,32,3))
        self.assertGreater(observation_evidence(a)['effective_count'],3.5)
        a[:]=a[0]
        self.assertAlmostEqual(observation_evidence(a)['effective_count'],1)
        self.assertEqual(observation_evidence(a[:,:1])['effective_count'],1)

    def test_drs_reset_requires_matching_observation_extent(self):
        # Changing resolution invalidates history; it cannot be silently resized.
        out,d=resolve(self.c[:16,:16],self.f[:16,:16],self.c[:16,:16]+.08,
            self.z[:16,:16],self.n[:16,:16],self.r[:16,:16],reset=True)
        self.assertFalse(d['confidence'].any())
        np.testing.assert_array_equal(out,self.c[:16,:16]+.08)

    def test_independent_validation_does_not_reward_a_noisy_baseline(self):
        raw=.2+self.rng.normal(0,.01,self.c.shape)
        other=.2+self.rng.normal(0,.01,self.c.shape)
        features=np.full((*raw.shape,2),.2)
        biased,d=resolve(raw,features,raw,self.z,self.n,self.r,require_independence=False)
        self.assertFalse(d['confidence'].any()) # The noisy baseline exactly matches its own source.
        out,d=resolve(raw,features,raw,self.z,self.n,self.r,require_independence=False,validation_response=other)
        self.assertGreater(d['confidence'].mean(),.9)
        self.assertLess(np.sqrt(np.mean((out-.2)**2)),.002)
        with self.assertRaises(ValueError):
            resolve(raw,features,raw,self.z,self.n,self.r,validation_response=other[:-1])


class StudyContracts(unittest.TestCase):
    def test_distant_support_box_cannot_hide_outside_radial_profile(self):
        from fsrd_quality_contours import island_contours,contour_gate
        clean=np.full((4,64,96,3),.2);base=clean.copy();candidate=clean.copy()
        base[:,30:38,34:42]+=.02
        candidate[:,8:58,14:68]+=.003
        a=island_contours(candidate,clean);b=island_contours(base,clean)
        self.assertGreater(a['radius95'],2.5)
        self.assertFalse(contour_gate(a,b,96,64)['passed'])
        self.assertLess(np.sqrt(np.mean((candidate-clean)**2)),np.sqrt(np.mean((base-clean)**2)))

    def test_uniform_bias_is_separate_from_contour_shape(self):
        from fsrd_quality_contours import island_contours
        clean=np.full((4,64,96,3),.2)
        self.assertEqual(island_contours(clean+.01,clean)['affected_pixels'],0)

    def test_metadata_exposure_does_not_change_radiance(self):
        from probe_fsrd_statistical_resolve import fixture
        a=fixture('material',32,32,8,941)
        b=fixture('metadata_exposure',32,32,8,941)
        for key in ('raw','diff','spec','depth','normals','roughness','controls'):
            np.testing.assert_array_equal(a[key],b[key])
        self.assertFalse(np.array_equal(a['pre_exposure_metadata'],b['pre_exposure_metadata']))
        for scene in ('material','guide_noise'):
            data=fixture(scene,32,32,8,941)
            for key in ('raw','diff','spec'):
                np.testing.assert_array_equal(data[key],data[key].astype(np.float16).astype(np.float32))

    def test_noop_and_null_spread_are_not_improvement(self):
        from probe_fsrd_statistical_resolve import acceptance
        b=dict(rmse=.01,broad_tone_rms=.01,residual_temporal_std=.01,bias_rgb=[0,0,0],
               frame_rmse=[.01]*8,ring_width=.1,contrast_gain=[None]*8,phase_error_radians=[None]*8)
        a=dict(b,rmse=.005)
        self.assertFalse(acceptance(a,b,0,0,'fake_specular')['effective_success'])
        self.assertFalse(acceptance(a,b,.5,.002,'fake_specular')['effective_success'])
        self.assertTrue(acceptance(a,b,.5,0,'fake_specular')['effective_success'])

    def test_first_frame_regression_and_phase_are_gates(self):
        from probe_fsrd_statistical_resolve import acceptance
        b=dict(rmse=.01,broad_tone_rms=.01,residual_temporal_std=.01,bias_rgb=[0,0,0],
               frame_rmse=[.01]*8,ring_width=.1,contrast_gain=[1]*8,phase_error_radians=[0]*8)
        a=dict(b,rmse=.005,frame_rmse=[.02]+[.004]*7,phase_error_radians=[.1]*8)
        g=acceptance(a,b,.5,0,'moving_light')
        self.assertIn('early_or_transition_frame',g['failures'])
        self.assertIn('phase_error_radians',g['failures'])
        self.assertFalse(g['effective_success'])


if __name__=='__main__': unittest.main()
