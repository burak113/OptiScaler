"""Capture evidence integrity, malformed inputs and invalid-source attribution."""
from pathlib import Path
import hashlib
import json
import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from inspect_fsrd_additive_capture import LIVE_FIELDS, read_live, main as inspect_main


class CaptureReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        constants=bytes(416)
        (self.folder/'conversion_constants.bin').write_bytes(constants)
        self.meta=dict(schema='fsrd-additive-live-v1',size=[2,3],
            constants_sha256=hashlib.sha256(constants).hexdigest(),images=[])
        for strength in (0,1):
            for field in LIVE_FIELDS:
                name=f'strength{strength}_{field}'
                image=np.full((3,2,4),strength,np.float32).tobytes()
                (self.folder/(name+'.f32')).write_bytes(image)
                self.meta['images'].append(dict(name=name,file=name+'.f32',
                    format='RGBA32_FLOAT',sha256=hashlib.sha256(image).hexdigest()))
        self.save()

    def tearDown(self): self.temp.cleanup()
    def save(self): (self.folder/'capture.json').write_text(json.dumps(self.meta),encoding='utf-8')

    def set_nonfinite(self,field):
        item=next(i for i in self.meta['images'] if i['name']=='strength0_'+field)
        data=np.full((3,2,4),np.nan,np.float32).tobytes()
        (self.folder/item['file']).write_bytes(data)
        item['sha256']=hashlib.sha256(data).hexdigest()
        self.save()

    def test_complete_round_trip(self):
        _,arrays=read_live(self.folder)
        self.assertEqual(len(arrays),96)
        self.assertTrue(np.all(arrays['strength1_p']==1))
        self.assertEqual(arrays['strength0_p'].shape,(3,2,3))

    def test_corrupt_image_rejected(self):
        (self.folder/'strength0_p.f32').write_bytes(bytes(96))
        # This endpoint was already zero; alter one byte to corrupt its digest.
        data=bytearray((self.folder/'strength0_p.f32').read_bytes()); data[0]=1
        (self.folder/'strength0_p.f32').write_bytes(data)
        with self.assertRaisesRegex(ValueError,'hash/size'): read_live(self.folder)

    def test_corrupt_constants_rejected(self):
        (self.folder/'conversion_constants.bin').write_bytes(bytes(415))
        with self.assertRaisesRegex(ValueError,'Constant buffer'): read_live(self.folder)

    def test_missing_field_rejected(self):
        self.meta['images'].pop(); self.save()
        with self.assertRaisesRegex(ValueError,'Incomplete'): read_live(self.folder)

    def test_duplicate_identity_rejected(self):
        self.meta['images'].append(self.meta['images'][0]); self.save()
        with self.assertRaisesRegex(ValueError,'duplicate'): read_live(self.folder)

    def test_path_escape_rejected(self):
        self.meta['images'][0]['file']='../outside.f32'; self.save()
        with self.assertRaisesRegex(ValueError,'identity'): read_live(self.folder)

    def test_nonfinite_fit_rejected(self):
        self.set_nonfinite('ridge_slope')
        with self.assertRaisesRegex(ValueError,'Nonfinite computed'): read_live(self.folder)

    def test_incorrect_format_rejected(self):
        self.meta['images'][0]['format']='RGBA16_FLOAT'; self.save()
        with self.assertRaisesRegex(ValueError,'format'): read_live(self.folder)

    def test_nonfinite_source_preserved_as_evidence(self):
        self.set_nonfinite('source_specular')
        _,arrays=read_live(self.folder)
        self.assertTrue(np.isnan(arrays['strength0_source_specular']).all())

    def test_summary_uses_matching_material_multipliers(self):
        for item in self.meta['images']:
            strength=int(item['name'][8]); field=item['name'].split('_',1)[1]
            values=dict(raw_rgb=.3,stored_specular=.2,stored_diffuse=.5,
                specular_signal=1.5 if strength else 1.,diffuse_signal=0. if strength else .2,
                settings=[strength,1,1])
            array=np.zeros((3,2,4),np.float32); array[...,:3]=values.get(field,0)
            data=array.tobytes(); (self.folder/item['file']).write_bytes(data)
            item['sha256']=hashlib.sha256(data).hexdigest()
        self.save(); output=self.folder/'analysis'
        with patch('sys.argv',['inspect','--capture',str(self.folder),'--output',str(output)]),contextlib.redirect_stdout(io.StringIO()):
            inspect_main()
        summary=json.loads((output/'summary.json').read_text())
        stored=summary['stored_domain']
        np.testing.assert_allclose(stored['mean_signed_specular_transfer'],[.1]*3,atol=1e-7)
        np.testing.assert_allclose(stored['mean_signed_diffuse_transfer'],[-.1]*3,atol=1e-7)
        self.assertLess(max(stored['maximum_absolute_closure_delta']),1e-7)
        self.assertTrue(all(summary['source_same'].values()))

    def paired(self):
        self.meta['schema']='fsrd-additive-live-v2'
        self.meta['paired']=dict(frame_index=91,reset=True,dispatch_flags=1,pre_exposure=2.,
            view=np.eye(4).ravel().tolist(),projection=np.eye(4).ravel().tolist(),
            jitter=[.25,-.25],motion_scale=[1,1,1],camera_delta=[0,0,0],
            linear_depth_bounds=[.1,1000],composition_controls=[0,4,1,1,1,1,1])
        data=np.full((3,2,4),.25,dtype='<f2').tobytes()
        (self.folder/'pre_sr_output.f16').write_bytes(data)
        self.meta['images'].append(dict(name='pre_sr_output',file='pre_sr_output.f16',
            format='RGBA16_FLOAT',sha256=hashlib.sha256(data).hexdigest()))
        self.save()

    def test_paired_output_preserves_fp16_and_metadata(self):
        self.paired();m,a=read_live(self.folder)
        self.assertEqual(len(a),97)
        np.testing.assert_array_equal(a['pre_sr_output'],.25)
        self.assertEqual(m['paired']['frame_index'],91)

    def test_paired_output_required(self):
        self.paired();self.meta['images'].pop();self.save()
        with self.assertRaisesRegex(ValueError,'Incomplete'): read_live(self.folder)

    def test_paired_output_integrity(self):
        self.paired();(self.folder/'pre_sr_output.f16').write_bytes(bytes(48))
        with self.assertRaisesRegex(ValueError,'hash/size'): read_live(self.folder)

    def test_paired_controls_must_be_finite_consistent(self):
        self.paired();self.meta['paired']['view'][0]=float('nan');self.save()
        with self.assertRaisesRegex(ValueError,'paired view'): read_live(self.folder)
        self.paired();self.meta['paired']['reset']=False;self.save()
        with self.assertRaisesRegex(ValueError,'paired reset'): read_live(self.folder)


if __name__=='__main__': unittest.main()
