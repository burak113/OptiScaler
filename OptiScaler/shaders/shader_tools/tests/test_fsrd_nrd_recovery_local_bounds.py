"""Local bounds preserve support, tile energy and distant independent detail."""
import unittest
import numpy as np
from fsrd_nrd_recovery_local_bounds import project_local_box,tile_view
from fsrd_nrd_lobe_reference_prototype import finish,ReferenceSettings


class LocalProjectionContracts(unittest.TestCase):
    def test_random_bounds_support_and_tile_zero_dc(self):
        rng = np.random.default_rng(22945830)
        c = rng.normal(0,.2,(19,27,3)).astype(np.float32)
        lower = -rng.uniform(0,.1,c.shape).astype(np.float32)
        upper = rng.uniform(0,.1,c.shape).astype(np.float32)
        mask = rng.uniform(size=c.shape)>.25
        for tile in (8,16):
            out,_ = project_local_box(c,lower,upper,mask,tile)
            self.assertTrue(np.all(out>=lower)&np.all(out<=upper))
            self.assertTrue(np.all(out[~mask]==0))
            blocks,_ = tile_view(out,tile)
            # A reduction over at most tile^2 FP32 contributions per channel.
            bound = 8*np.finfo(np.float32).eps*tile*tile*max(float(np.max(np.abs(out))),1e-20)
            self.assertLessEqual(float(np.max(np.abs(blocks.astype(np.float64).sum(1)))),bound)

    def test_a_dark_constraint_cannot_attenuate_a_distant_tile(self):
        yy,xx = np.mgrid[:8,:16]
        c = np.repeat(np.where((xx+yy)%2,.05,-.05)[...,None],3,-1).astype(np.float32)
        lower,upper = np.full_like(c,-1),np.full_like(c,1)
        lower[0,0] = -.0001
        out,_ = project_local_box(c,lower,upper,np.ones(c.shape,bool),8)
        self.assertTrue(np.array_equal(out[:,8:],c[:,8:]))
        self.assertGreater(float(np.std(out[:,:8,0])),.04)

    def test_feasible_zero_dc_input_is_unchanged(self):
        yy,xx = np.mgrid[:8,:8]
        c = np.repeat(np.where((xx+yy)%2,.125,-.125)[...,None],3,-1).astype(np.float32)
        out,_ = project_local_box(c,np.full_like(c,-1),np.full_like(c,1),np.ones(c.shape,bool))
        self.assertTrue(np.array_equal(out,c))

    def test_projection_is_closer_to_target_than_global_uniform_bound(self):
        rng = np.random.default_rng(22945830)
        c = rng.normal(size=(8,8,3)).astype(np.float32)
        c -= c.mean((0,1),keepdims=True)
        lower,upper = np.full_like(c,-1),np.full_like(c,1)
        lower[0,0] = -.00001
        ratio = np.ones_like(c)
        np.divide(upper,c,out=ratio,where=c>0)
        np.divide(lower,c,out=ratio,where=c<0)
        uniform = c*np.clip(ratio.min(),0,1)
        out,_ = project_local_box(c,lower,upper,np.ones(c.shape,bool))
        self.assertLess(float(np.sum((out-c)**2)),float(np.sum((uniform-c)**2)))

    def test_empty_and_one_sided_boxes_cannot_add_energy(self):
        c = np.ones((17,23,3),np.float32)
        for mask in (np.ones(c.shape,bool),np.zeros(c.shape,bool)):
            out,_ = project_local_box(c,np.zeros_like(c),np.ones_like(c),mask)
            self.assertTrue(np.all(out==0))

    def test_invalid_intervals_and_unbounded_tile_are_rejected(self):
        c = np.zeros((8,8,3),np.float32)
        with self.assertRaises(ValueError):project_local_box(c,c+.1,c+1,np.ones(c.shape,bool))
        with self.assertRaises(ValueError):project_local_box(c,c-1,c+1,np.ones(c.shape,bool),1024)

    def test_local_anchor_distant_support_or_contrast_cannot_change_another_tile(self):
        yy,xx = np.mgrid[:17,:27]
        rr = np.full((17,27,3),.5,np.float32)
        c = np.repeat(np.where((xx+yy)%2,.05,-.05)[...,None],3,-1).astype(np.float32)
        safe = np.ones((17,27),bool)
        settings = ReferenceSettings(bound_projection='local_anchor')
        original,_ = finish(rr,c,safe,settings)
        rr[:,:8] *= .0001
        safe[:,:8] = False
        changed,_ = finish(rr,c,safe,settings)
        self.assertTrue(np.array_equal(changed[:,10:],original[:,10:]))
        self.assertTrue(np.all(changed[:,:8]==0))

    def test_local_anchor_has_no_hidden_eight_pixel_grid_seam(self):
        yy,xx = np.mgrid[:24,:32]
        rr = np.repeat((.5+.1*np.sin(xx*.7))[...,None],3,-1).astype(np.float32)
        c = np.repeat((.05*np.cos(xx*.37+yy*.53))[...,None],3,-1).astype(np.float32)
        safe = np.ones((24,32),bool)
        settings = ReferenceSettings(bound_projection='local_anchor')
        original,_ = finish(rr,c,safe,settings)
        shifted,_ = finish(np.roll(rr,1,1),np.roll(c,1,1),safe,settings)
        self.assertTrue(np.array_equal(shifted[:,2:-2],np.roll(original,1,1)[:,2:-2]))

    def test_local_anchor_obeys_the_same_rr_bounds_without_global_gain(self):
        yy,xx = np.mgrid[:17,:27]
        rr = np.repeat((.5+.1*np.sin(xx*.7))[...,None],3,-1).astype(np.float32)
        c = np.repeat((.7*np.cos(xx*.37+yy*.53))[...,None],3,-1).astype(np.float32)
        settings = ReferenceSettings(bound_projection='local_anchor')
        out,stats = finish(rr,c,np.ones(rr.shape[:2],bool),settings)
        self.assertTrue(np.all(out>=-.25*rr))
        self.assertTrue(np.all(rr+out>=0))
        self.assertIsNone(stats['uniform_bound_scale'])


if __name__ == '__main__':
    unittest.main()
