from dataclasses import replace
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE/'portable'))
from packed_model import Config, Evidence, Identity, Layout, constants, pack, process, unpack
from fixtures import make_case, CASES


class PackedContracts(unittest.TestCase):
    def test_exact_passthrough_for_all_admission_failures(self):
        for name in ('off','unacknowledged','strength0','reset','resize','unknown_authority',
                     'unknown_support','post_scale_source','stale_recording'):
            c = make_case(name)
            self.assertNotEqual(c['decision'], 'Ready', name)
            np.testing.assert_array_equal(c['output'], c['selected'].view(np.uint16))
            self.assertFalse(c['diagnostic'].any())

    def test_off_needs_no_optional_input(self):
        selected = np.array([[[0x8000,0x7d55,0xfc01,0x8000]]], np.uint16)
        output, _, reason = process(None,None,selected,None,None,None,None)
        self.assertEqual(reason,'Off')
        np.testing.assert_array_equal(output,selected)

    def test_every_alpha_word_survives_active_correction(self):
        h=w=256
        raw=np.full((h,w,4),.25,np.float16)
        raw.view(np.uint16)[...,3]=np.arange(65536,dtype=np.uint16).reshape(h,w)
        source=raw.copy()
        source[...,0]*=np.float16(.9)
        source[...,2]*=np.float16(1.1)
        identity=Identity(render_width=w,render_height=h,active_width=w,active_height=h)
        evidence=Evidence(identity,1,1,1,1,1,1)
        out,diag,reason=process(source,raw,raw,np.full((h,w),10,np.float32),
            np.full((h,w),512|(512<<10)|(600<<20),np.uint32),np.ones((h,w),np.uint32),
            np.ones((h,w),np.uint32),config=Config(enabled=True,acknowledge_rejected_research=True,radius=1),
            identity=identity,evidence=evidence)
        self.assertEqual(reason,'Ready')
        self.assertTrue(diag[...,0].all())
        self.assertTrue(np.any(out[...,:3]!=raw.view(np.uint16)[...,:3]))
        np.testing.assert_array_equal(out[...,3],raw.view(np.uint16)[...,3])

    def test_selection_includes_alpha_and_one_ulp(self):
        c=make_case()
        for y,x in ((1,2),(2,3),(2,4)):
            np.testing.assert_array_equal(c['output'][y,x],c['selected'].view(np.uint16)[y,x])
            self.assertEqual(c['diagnostic'][y,x,0],0)
        self.assertGreater(np.count_nonzero(np.any(c['output']!=c['selected'].view(np.uint16),axis=-1)),0)

    def test_reserved_authority_and_support_codes_are_not_truthy(self):
        c=make_case()
        for y,x in ((3,4),(3,5),(4,5),(4,6)):
            np.testing.assert_array_equal(c['output'][y,x],c['selected'].view(np.uint16)[y,x])
        c=make_case('all_unknown_pixels')
        np.testing.assert_array_equal(c['output'],c['selected'].view(np.uint16))

    def test_full_pitched_buffer_padding_and_inactive_texels_preserved(self):
        c=make_case()
        layout=c['layouts'][3]
        before=c['packed']['initial_output']
        after=c['packed']['expected_output']
        canary=np.ones(layout.size,bool)
        for y in range(c['identity'].active_height):
            start=layout.offset+y*layout.row_pitch
            canary[start:start+c['identity'].active_width*8]=False
        np.testing.assert_array_equal(after[canary],before[canary])
        np.testing.assert_array_equal(unpack(after,layout),c['output'])

    def test_invalid_centres_passthrough_and_do_not_poison_neighbours(self):
        c=make_case('invalid_samples')
        for y,x in ((1,1),(2,1),(3,1),(1,7),(2,7),(5,0),(5,1),(5,2),(5,3)):
            np.testing.assert_array_equal(c['output'][y,x],c['selected'].view(np.uint16)[y,x])
        valid=np.all(np.isfinite(c['selected'].astype(np.float32)[...,:3]),axis=-1)
        self.assertTrue(np.isfinite(c['output'].view(np.float16)[...,:3][valid]).all())
        self.assertTrue(np.any(c['output']!=c['selected'].view(np.uint16)))

    def test_constant_values_that_break_gpu_denominators_are_rejected(self):
        for config in (Config(strength=float('nan')),Config(spatial_sigma=1e-30),
                       Config(spatial_sigma=1e30),Config(normal_cosine=1.-1e-10),
                       Config(guide_chroma_radius=1e-24),Config(depth_tolerance=1e-50),
                       Config(support_prior=1e300),Config(representation=9),Config(radius=True),
                       Config(strength=1e-40),Config(max_log_delta=1e-40),
                       Config(normal_cosine=-1e-40),Config(support_prior=1e-40)):
            with self.assertRaises(ValueError):
                config.uploaded()
            output,_,reason=process(None,None,np.ones((1,1,4),np.float16),None,None,None,None,config=config)
            self.assertEqual(reason,'InvalidConfig')
            np.testing.assert_array_equal(output,np.ones((1,1,4),np.float16).view(np.uint16))

    def test_layout_rejects_truncation_alignment_and_uint32_overflow(self):
        good=Layout(13,9,256,512,512+9*256+512)
        good.validate((13,9))
        for bad in (replace(good,size=512+8*256+13*8),replace(good,row_pitch=255),
                    replace(good,offset=4),replace(good,size=1<<32),replace(good,width=33),
                    replace(good,offset=0xfffffe00),replace(good,height=0)):
            with self.assertRaises(ValueError): bad.validate((13,9))

    def test_cbv_layout_and_output_initialization(self):
        c=make_case()
        self.assertEqual(len(c['constants']),112)
        with self.assertRaises(ValueError):
            constants(c['config'],c['identity'],(*c['layouts'][:3],replace(c['layouts'][3],offset=2048)))
        self.assertEqual(c['layouts'][2],c['layouts'][3])

    def test_unequal_allocations_same_active_inputs_are_invariant(self):
        c=make_case()
        h,w=c['identity'].active_height,c['identity'].active_width
        out,diag,reason=process(*(c[key][:h,:w].copy() for key in
            ('source','raw','selected','depth','normal','authority','support')),
            config=c['config'],identity=c['identity'],evidence=c['evidence'])
        self.assertEqual(reason,'Ready')
        np.testing.assert_array_equal(out,c['output'][:h,:w])
        np.testing.assert_array_equal(diag,c['diagnostic'][:h,:w])

    def test_crop_translation_is_not_reprojection(self):
        c=make_case()
        ident=replace(c['identity'],crop_x=8,crop_y=11,render_width=40,render_height=40)
        out,_,_=process(*(c[key] for key in ('source','raw','selected','depth','normal','authority','support')),
            config=c['config'],identity=ident,evidence=replace(c['evidence'],identity=ident))
        np.testing.assert_array_equal(out,c['output'])

    def test_d16_s256_metadata_does_not_change_physical_rgb(self):
        a,b=make_case('log_d16'),make_case('log_s256')
        np.testing.assert_array_equal(a['output'],b['output'])
        self.assertFalse(replace(a['identity'],provider_scale=256).valid())
        self.assertFalse(replace(b['identity'],provider_scale=16).valid())

    def test_sources_are_immutable(self):
        c=make_case()
        names=('source','raw','selected','depth','normal','authority','support')
        before={key:c[key].tobytes() for key in names}
        process(*(c[key] for key in names),config=c['config'],identity=c['identity'],evidence=c['evidence'])
        self.assertEqual(before,{key:c[key].tobytes() for key in names})

    def test_snapshot_alias_cannot_survive_later_provider_writes(self):
        c=make_case()
        for source in (c['raw'],c['selected']):
            output,_,reason=process(source,*(c[key] for key in
                ('raw','selected','depth','normal','authority','support')),
                config=c['config'],identity=c['identity'],evidence=c['evidence'])
            self.assertEqual(reason,'InvalidNativeResource')
            np.testing.assert_array_equal(output,c['selected'].view(np.uint16))
        self.assertFalse(replace(c['identity'],recording=1<<64).valid())

    def test_deterministic_fixture_output(self):
        for name in CASES:
            a,b=make_case(name),make_case(name)
            self.assertEqual(a['constants'],b['constants'])
            self.assertEqual(a['packed']['expected_output'].tobytes(),b['packed']['expected_output'].tobytes())

    def test_noncontiguous_snapshot_alias_still_rejected(self):
        c=make_case()
        selected=np.ones((15,46,4),np.float16)[:,::2,:]
        self.assertFalse(selected.flags.c_contiguous)
        out,_,reason=process(selected,c['raw'],selected,*(c[key] for key in
            ('depth','normal','authority','support')),config=c['config'],identity=c['identity'],evidence=c['evidence'])
        self.assertEqual(reason,'InvalidNativeResource')
        np.testing.assert_array_equal(out,selected.view(np.uint16))

    def test_each_texture_allocation_must_fit_native_dimension_limit(self):
        c=make_case()
        names=('source','raw','selected','depth','normal','authority','support')
        for name in names:
            for axis in (0,1):
                arrays={key:c[key] for key in names}
                shape=list(c[name].shape)
                shape[axis]=16385
                arrays[name]=np.ones(shape,dtype=c[name].dtype)
                out,_,reason=process(*(arrays[key] for key in names),config=c['config'],
                    identity=c['identity'],evidence=c['evidence'])
                self.assertEqual(reason,'InvalidNativeResource',(name,axis))
                np.testing.assert_array_equal(out,arrays['selected'].view(np.uint16))

    def test_support_producer_version_must_fit_native_uint64(self):
        c=make_case()
        for version in (0,-1,1<<64,1.25,True):
            out,_,reason=process(*(c[key] for key in
                ('source','raw','selected','depth','normal','authority','support')),
                config=c['config'],identity=c['identity'],evidence=replace(c['evidence'],producer_version=version))
            self.assertEqual(reason,'UnknownSupport')
            np.testing.assert_array_equal(out,c['selected'].view(np.uint16))


if __name__=='__main__':
    unittest.main(verbosity=2)
