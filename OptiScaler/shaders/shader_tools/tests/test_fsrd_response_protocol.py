"""Counterfactual nonmutation, evidence tampering and DC transition regressions."""
from pathlib import Path
import copy
import hashlib
import json
import tempfile
import unittest
import numpy as np
import probe_fsrd_response_calibration as p


class ProtocolTests(unittest.TestCase):
    def packed(self):
        return [[np.full((8,8,4),.1,np.float32) for _ in range(6)] for _ in range(2)]

    def test_color_change_is_allowed_but_guide_motion_and_alpha_are_not(self):
        source=self.packed()
        changed=copy.deepcopy(source)
        changed[0][0][...,:3]=.2
        p.assert_counterfactual_contract(source,changed)
        for slot,channel in ((0,3),(1,3),(2,0),(3,0),(4,0),(5,0)):
            changed=copy.deepcopy(source);changed[0][slot][...,channel]+=.1
            with self.assertRaises(ValueError):p.assert_counterfactual_contract(source,changed)

    def test_dc_inactive_keeps_baseline_exact(self):
        raw=np.full((24,16,16,3),.32);base=np.full_like(raw,.2)
        controls=np.zeros((24,3));controls[0,0]=1
        out=p.dc_conservation(base,raw,np.zeros(24,bool),controls,16)
        np.testing.assert_array_equal(out,base)

    def test_stale_dc_light_step_falsification_and_current_constraint(self):
        raw=np.full((48,16,16,3),.2);raw[24:]=.32
        controls=np.zeros((48,3));controls[0,0]=1
        active=np.ones(48,bool)
        stale=p.dc_conservation(raw,raw,active,controls,16)
        self.assertLess(float((stale[24]-raw[24]).mean()),-.11)
        current=p.dc_conservation(raw,raw,active,controls,1)
        np.testing.assert_allclose(current,raw,atol=1e-12)

    def test_epoch_boundary_blocks_stale_dc(self):
        raw=np.full((24,16,16,3),.2);raw[12:]=.32
        controls=np.zeros((24,3));epochs=[0]*12+[12]*12
        corrected=p.dc_conservation(raw,raw,np.ones(24,bool),controls,16,epochs)
        np.testing.assert_allclose(corrected,raw,atol=1e-12)

    def test_same_observed_rgb_cannot_authenticate_changed_guides_or_controls(self):
        packed=self.packed();depth=np.full((8,8),10,np.float32)
        controls=np.array([[1,0,0],[0,0,0]],float)
        arrays=[depth,np.stack([v[2] for v in packed]),np.stack([v[3] for v in packed]),
                np.stack([v[4] for v in packed]),np.stack([v[5] for v in packed]),
                np.stack([v[1] for v in packed]),np.stack([v[0] for v in packed])]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ctx=root/'ctx';ctx.mkdir();out=root/'verify';out.mkdir()
            hashes={}
            for i,(array,fmt) in enumerate(zip(arrays,[41,10,24,28,28,10,10])):
                path=ctx/f'input{i}.bin';p.write_texture(path,array,fmt)
                hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            (ctx/'frame_controls.txt').write_text('1 0 0\n0 0 0\n')
            manifest=dict(dimensions=[8,8],frames=2,signals=[2,32],reset_every=0,tuning=1,passthrough=0,
                          dll_sha256=p.digest(p.DLL),inputs=hashes)
            (ctx/'amd_context_identity.json').write_text(json.dumps(manifest))
            p.authenticate_reused_source(ctx,packed,depth,controls,out)
            changed=copy.deepcopy(packed);changed[0][4][...,:3]=.4
            with self.assertRaisesRegex(ValueError,'guide/geometry/radiance'):
                p.authenticate_reused_source(ctx,changed,depth,controls,out)
            bad=controls.copy();bad[1,1]=.5
            with self.assertRaisesRegex(ValueError,'reset/jitter'):
                p.authenticate_reused_source(ctx,packed,depth,bad,out)

    def capture(self, root):
        images=[]
        for name in ('source_diffuse_albedo','source_specular_albedo','source_normals',
                     'rr_linear_depth','source_specular_hit_distance'):
            data=np.full((96,96,4),.2,np.float32)
            if name=='source_normals':data[...,2]=-1;data[...,3]=.37
            if name=='rr_linear_depth':data[...,0]=-10
            if name=='source_specular_hit_distance':data[...,0]=3
            path=root/(name+'.rgba32f');path.write_bytes(data.astype('<f4').tobytes())
            images.append(dict(name=name,file=path.name,width=96,height=96,channels=4,sha256=p.digest(path)))
        view=np.eye(4);view[3,0]=1
        projection=np.diag([1.2,1.4,1,1])
        m=dict(complete=True,gpu_completion_verified=True,frame_index=123,backend='JointFieldV1',
               width=96,height=96,settings=dict(conversion_flags=52),images=images,render_size=[1505,847],origin_xy=[752,423],
               dispatch=dict(view=view.ravel().tolist(),projection=projection.ravel().tolist(),
                             jitter=[.4375,.240740716],depth_bounds=[.1,1000]))
        path=root/'capture.json';path.write_text(json.dumps(m));return path

    def test_captured_fixture_preserves_packed_roughness_hit_camera_and_jitter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);metadata=self.capture(root)
            npz,provenance=p.prepare_capture(metadata,root)
            data=p.captured_research_fixture('recorded_island',24,52,npz,metadata)
            self.assertEqual(provenance['source_backend'],'JointFieldV1')
            self.assertFalse(provenance['true_game_history'])
            with np.load(npz) as z:
                self.assertEqual(int(z['mask'].sum()),4800)
                self.assertEqual(hashlib.sha256(z['mask'].tobytes()).hexdigest(),provenance['mask_sha256'])
            np.testing.assert_allclose(data['roughness'],.37)
            np.testing.assert_allclose(data['resources'][5],3)
            np.testing.assert_allclose(data['depth'],10)
            self.assertEqual(data['diff'].shape,(24,96,96,4))
            self.assertEqual(data['overrides']['Flags'],50)
            self.assertEqual(data['controls'][0,0],1)
            self.assertFalse(data['controls'][1:,0].any())
            np.testing.assert_allclose(data['controls'][:,1:],np.tile(data['camera'][32:34],(24,1)))
            view=np.array(data['camera'][:16]).reshape(4,4)
            proj=np.array(data['camera'][16:32]).reshape(4,4)
            np.testing.assert_allclose(view@np.array(data['overrides']['InvViewMatrix']).reshape(4,4),np.eye(4))
            np.testing.assert_allclose(proj@np.array(data['overrides']['InvProjMatrix']).reshape(4,4),np.eye(4))
            self.assertNotEqual(proj[0,0],1.2)

    def test_captured_payload_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);metadata=self.capture(root)
            path=root/'source_specular_albedo.rgba32f'
            content=bytearray(path.read_bytes());content[11]^=1;path.write_bytes(content)
            with self.assertRaisesRegex(ValueError,'SHA/size mismatch'):
                p.prepare_capture(metadata,root)

    def test_captured_roi_score_excludes_surrounding_surface_error(self):
        truth=np.full((24,96,96,3),.2,np.float32);out=truth.copy()
        out[:,25:85,5:85]+=.01
        out[:,:20]+=1
        m=p.captured_roi_score(out,truth)
        self.assertAlmostEqual(m['rmse'],.01,places=6)
        np.testing.assert_allclose(m['bias_rgb'],.01,atol=1e-6)

    def test_captured_render_extent_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);metadata=self.capture(root)
            m=json.loads(metadata.read_text());m['origin_xy']=[1500,423]
            metadata.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'render extent'):
                p.prepare_capture(metadata,root)

    def test_constant_truth_has_no_spatial_phase_at_any_capture_size(self):
        for size in (96,256):
            truth=np.broadcast_to(np.array([.065,.080,.095],np.float32),(2,size,size,3)).copy()
            measured=p.score(truth+.001,truth,None)
            self.assertEqual(measured['phase_error_radians'],[None,None])
            self.assertEqual(measured['contrast_gain'],[None,None])

    def test_genuine_wave_phase_is_measured_after_dc_exclusion(self):
        h=w=96;y,x=np.indices((h,w));frequency=4*2*np.pi*x/w
        truth=np.repeat((.2+.012*np.cos(frequency))[None,...,None],3,axis=-1)
        candidate=np.repeat((.2+.012*np.cos(frequency+.3))[None,...,None],3,axis=-1)
        measured=p.score(candidate.astype(np.float32),truth.astype(np.float32),None)
        self.assertAlmostEqual(measured['phase_error_radians'][0],.3,places=5)

    def test_radiance_fallback_preserves_entire_rgb_pixel_without_clipping(self):
        baseline=np.full((1,2,3,3),.2)
        candidate=np.full_like(baseline,.3)
        candidate[0,0,0,0]=-.01;candidate[0,0,1,1]=np.inf;candidate[0,0,2,2]=65505
        safe,fraction=p.radiance_fallback(candidate,baseline)
        np.testing.assert_array_equal(safe[0,0],baseline[0,0])
        np.testing.assert_array_equal(safe[0,1],candidate[0,1])
        self.assertEqual(fraction,.5)

    def test_fallback_does_not_convert_an_invalid_baseline_into_a_fix(self):
        baseline=np.full((1,16,16,3),.2);candidate=np.full_like(baseline,-.1)
        safe,fraction=p.radiance_fallback(candidate,baseline)
        np.testing.assert_array_equal(safe,baseline)
        score=p.score(safe,baseline,None)
        self.assertFalse(p.acceptance(score,score,0,0,'wave')['effective_success'])
        self.assertEqual(fraction,1)
        baseline[0,0,0,0]=-1
        with self.assertRaisesRegex(ValueError,'Invalid baseline'):
            p.radiance_fallback(candidate,baseline)


if __name__=='__main__':unittest.main(verbosity=2)
