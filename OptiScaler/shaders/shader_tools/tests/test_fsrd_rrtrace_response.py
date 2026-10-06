"""CPU provenance, cropped camera closure and frozen-source semantics tests."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
import numpy as np
import probe_fsrd_rrtrace_response as p


class RRTraceResponseTests(unittest.TestCase):
    def capture(self,root):
        h,w=96,112;y,x=np.indices((h,w));arrays={}
        for name in p.SOURCE_NAMES:
            a=np.zeros((h,w,4),np.float32);a[...,3]=1
            if name=='raw_rgba':a[...,:3]=(.1+.001*x+.0003*y)[...,None]*[1,.8,.6]
            if name=='source_diffuse_albedo':a[...,:3]=(.1+.001*x)[...,None]
            if name=='source_specular_albedo':a[...,:3]=(.5+.0001*y)[...,None]
            if name=='source_normals':a[...,2]=1;a[...,3]=.34+.0002*x
            if name=='rr_linear_depth':a[...,0]=10+.01*x
            if name=='source_specular_hit_distance':a[...,0]=3+.01*y
            arrays[name]=a
        images=[]
        for name,a in arrays.items():
            path=root/(name+'.rgba32f');path.write_bytes(a.astype('<f4').tobytes())
            images.append(dict(name=name,file=path.name,sha256=p.digest(path),width=w,height=h,channels=4))
        projection=np.array([[1.2,0,0,0],[0,1.4,0,0],[0,0,1.001,1],[0,0,-.1,0]],float)
        view=np.eye(4);view[3,:3]=[2,-3,4]
        m=dict(complete=True,gpu_completion_verified=True,format='rgba32f_le',width=w,height=h,
            backend='JointFieldV1',frame_index=33098,render_size=[160,120],origin_xy=[24,16],
            settings=dict(conversion_flags=52),images=images,
            dispatch=dict(view=view.ravel().tolist(),projection=projection.ravel().tolist(),
                jitter=[.4375,.240740716],depth_bounds=[.02,65504]))
        metadata=root/'capture.json';metadata.write_text(json.dumps(m));return metadata,m,arrays

    def test_authenticated_crop_and_fp16_source_without_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata,m,a=self.capture(Path(tmp));d=p.load_recorded(metadata)
            self.assertFalse(any('truth' in k or 'clean' in k for k in d))
            expected=a['raw_rgba'][25:85,5:85,:3].astype(np.float16).astype(np.float32)
            np.testing.assert_array_equal(d['observed'][0],expected)
            np.testing.assert_array_equal(d['observed'],np.broadcast_to(expected,d['observed'].shape))
            for name,source in a.items():
                np.testing.assert_array_equal(d['source_arrays'][name],source[25:85,5:85])
                self.assertEqual(d['provenance']['cropped_payload_sha256'][name],
                    hashlib.sha256(source[25:85,5:85].astype('<f4').tobytes()).hexdigest())
            self.assertEqual(d['observed'].shape,(32,60,80,3))
            self.assertFalse(d['provenance']['independent_observations'])
            self.assertFalse(d['provenance']['true_game_history'])
            self.assertFalse(d['provenance']['clean_reference_available'])
            json.dumps(d['provenance'],allow_nan=False)

    def test_double_crop_homogeneous_projection_and_inverse_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata,m,_=self.capture(Path(tmp));d=p.load_recorded(metadata)
            final=np.array(d['camera'][16:32]).reshape(4,4)
            original=np.array(m['dispatch']['projection']).reshape(4,4)
            direct=original@p.crop_transform((160,120),(29,41),(80,60))
            np.testing.assert_allclose(final,direct,rtol=0,atol=1e-14)
            inverse=np.array(d['overrides']['InvProjMatrix']).reshape(4,4)
            view=np.array(d['camera'][:16]).reshape(4,4)
            np.testing.assert_allclose(final@inverse,np.eye(4),rtol=0,atol=1e-14)
            np.testing.assert_allclose(view@np.array(d['overrides']['InvViewMatrix']).reshape(4,4),np.eye(4),atol=1e-14)
            # Two pixel centers reconstruct the same view ray in full-render and
            # final crop coordinates, without guessing camera aspect/near plane.
            for sx,sy in ((.5,.5),(79.5,59.5),(40.5,30.5)):
                crop_clip=np.array([2*sx/80-1,1-2*sy/60,.7,1])
                full_clip=np.array([2*(29+sx)/160-1,1-2*(41+sy)/120,.7,1])
                a=crop_clip@inverse;b=full_clip@np.linalg.inv(original)
                np.testing.assert_allclose(a/a[3],b/b[3],rtol=0,atol=1e-13)

    def test_geometry_hit_flags_and_controls_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata,m,a=self.capture(Path(tmp));d=p.load_recorded(metadata)
            np.testing.assert_array_equal(d['roughness'],a['source_normals'][25:85,5:85,3])
            np.testing.assert_array_equal(d['resources'][5],a['source_specular_hit_distance'][25:85,5:85,0])
            np.testing.assert_array_equal(d['depth'],a['rr_linear_depth'][25:85,5:85,0])
            self.assertEqual(d['overrides']['Flags'],50)
            self.assertEqual(d['controls'][0,0],1);self.assertFalse(d['controls'][1:,0].any())
            np.testing.assert_allclose(d['controls'][:,1:],np.tile(m['dispatch']['jitter'],(32,1)),atol=1e-8)
            self.assertFalse(d['motion'].any());self.assertFalse(d['diff'][...,3].any())
            self.assertEqual(d['provenance']['render_origin_xy'],[29,41])

    def test_payload_tampering_and_shape_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata,m,_=self.capture(Path(tmp));root=Path(tmp)
            path=root/'raw_rgba.rgba32f';old=path.read_bytes();bad=bytearray(old);bad[13]^=1;path.write_bytes(bad)
            with self.assertRaisesRegex(ValueError,'SHA/size'):p.load_recorded(metadata)
            path.write_bytes(old);m['width']+=1;metadata.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'dimensions'):p.load_recorded(metadata)

    def test_invalid_camera_crop_and_roughness_provenance_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata,m,_=self.capture(Path(tmp))
            with self.assertRaisesRegex(ValueError,'outside'):p.load_recorded(metadata,(100,25,80,60))
            with self.assertRaisesRegex(ValueError,'8x8'):p.load_recorded(metadata,(0,0,7,7))
            m['settings']['conversion_flags']=48;metadata.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'roughness'):p.load_recorded(metadata)
            m['settings']['conversion_flags']=52;m['dispatch']['jitter']=[float('nan'),0];metadata.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'camera'):p.load_recorded(metadata)

    def test_view_space_normals_flag_is_carried(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata,m,_=self.capture(Path(tmp));m['settings']['conversion_flags']|=1<<11
            metadata.write_text(json.dumps(m));d=p.load_recorded(metadata)
            self.assertEqual(d['overrides']['Flags'],50|(1<<11))

    def test_current_source_association_and_attribution_stats(self):
        y,x=np.indices((16,24));raw=np.repeat((.2+.001*x)[...,None],3,axis=-1)
        diff=np.concatenate((raw,np.zeros((*raw.shape[:2],1))),axis=-1);spec=np.zeros_like(diff)
        d=p.guide_correlations(raw,diff,spec)
        np.testing.assert_allclose(d['rho_diffuse_specular_rgb'][0],1,atol=1e-14)
        self.assertIsNone(d['effective_independent_pixels'])
        repeated=np.repeat(raw[None],8,axis=0);stats=p.appearance_stats(repeated)
        self.assertLess(max(stats['frozen_operator_temporal_std_rgb']),1e-15)
        self.assertNotIn('rmse',stats);self.assertEqual(stats['invalid_pixel_fraction'],0)

    def test_nonfinite_attribution_moments_remain_invalid_serializable_evidence(self):
        a=np.full((2,8,8,3),.2);a[0,1,2,0]=np.nan;a[1,2,3,1]=np.inf
        stats=p.appearance_stats(a)
        self.assertGreater(stats['invalid_pixel_fraction'],0)
        self.assertIsNone(stats['mean_rgb'][0]);self.assertIsNone(stats['mean_rgb'][1])
        self.assertAlmostEqual(stats['mean_rgb'][2],.2)
        json.dumps(stats,allow_nan=False)

    def test_native_probe_rejects_unsupported_extent_but_loader_stays_generic(self):
        self.assertEqual(p.DEFAULT_NATIVE_ROI,(0,24,96,64))
        with self.assertRaisesRegex(ValueError,'not a universal SDK'):p.validate_native_roi((5,25,80,60))
        p.validate_native_roi(p.DEFAULT_NATIVE_ROI)
        with tempfile.TemporaryDirectory() as tmp:
            metadata,_,_=self.capture(Path(tmp));d=p.load_recorded(metadata,(5,25,80,60))
            self.assertEqual(d['observed'].shape,(32,60,80,3))

    def test_native_aligned_96x64_crop_homogeneous_closure(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata,m,_=self.capture(Path(tmp));d=p.load_recorded(metadata,p.DEFAULT_NATIVE_ROI)
            self.assertEqual(d['observed'].shape,(32,64,96,3))
            original=np.array(m['dispatch']['projection']).reshape(4,4)
            final=np.array(d['camera'][16:32]).reshape(4,4)
            np.testing.assert_allclose(final,original@p.crop_transform((160,120),(24,40),(96,64)),atol=1e-14)
            inverse=np.array(d['overrides']['InvProjMatrix']).reshape(4,4)
            for sx,sy in ((.5,.5),(95.5,63.5),(48.5,32.5)):
                a=np.array([2*sx/96-1,1-2*sy/64,.7,1])@inverse
                b=np.array([2*(24+sx)/160-1,1-2*(40+sy)/120,.7,1])@np.linalg.inv(original)
                np.testing.assert_allclose(a/a[3],b/b[3],atol=1e-13)


if __name__=='__main__':unittest.main(verbosity=2)
