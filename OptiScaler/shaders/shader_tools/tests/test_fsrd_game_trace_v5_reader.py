"""CPU fixtures for the v5 immutable snapshot and separate post-SR contract.

These are manufactured parser fixtures, never game captures or IQ references.
Set TEMP/TMP to scratch before running; no GPU or compilation is performed.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('trace_v5_reader', HERE/'fsrd_real_capture_replay.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def fixture(path, tile=128, mode='off', count=2, post_format=10):
    path.mkdir(parents=True)
    render = [tile+160, tile+192]; origin = [40, 56]; size = [tile, tile]
    logical = [render[0]*2+1, render[1]*2+3]
    canonical = json.dumps({'floor_enabled': False, 'sdk_tuning': [.5, .5, 40000, 40, .5, .1]},
                           sort_keys=True, separators=(',', ':'))
    manifest = dict(schema='fsrd-game-trace-v5', source='live_game_gpu',
                    capture_uuid='29b54d6b-e252-4a71-b917-0f771bc469d0', complete=False,
                    render_extent=render, roi=dict(space='render_pixels_fixed', origin=origin, extent=size),
                    qpc_frequency=1000000, post_sr_mode=mode, frames=[])
    for ordinal in range(count):
        reset = ordinal == 1
        controls = dict(view=np.eye(4).ravel().tolist(), projection=np.eye(4).ravel().tolist(),
                        jitter=[.25, -.125], camera_delta=[.01, 0, 0], depth_bounds=[.02, 1000],
                        motion_vector_scale=[1, 1, 1], render_size=render,
                        pre_exposure=1., pre_exposure_provided=True, motion_history_valid=not reset,
                        output_scope='actual_configured_composition_before_sr')
        f = dict(ordinal=ordinal, context_id='RR-fixture-context', evaluation_id=ordinal+10,
                 native_frame_index=ordinal+100, recording_qpc=1000+ordinal*100,
                 reset=reset, controls=controls, settings=json.loads(canonical),
                 settings_canonical_json=canonical, settings_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
                 gpu_submission_verified=True, gpu_completed=True, command_list_detached=False,
                 cpu_snapshot_immutable=True, submission_gate_protected=True,
                 ticket_proof=dict(recorded=True, submitted=True, waitable=False, detached=False,
                                   invalid=False, abandoned=False, signal_failed=False, ambiguous_submission=False,
                                   pending_signals=0, fence_expected=1, fence_completed=1, signal_hresult=0,
                                   identity_address_process_local=1234, ticket_generation=ordinal+1,
                                   queue_address_process_local=2345, detach_kind='not_observed',
                                   cpu_snapshot_immutable=True, submission_gate_protected=True),
                 output_scope='actual_configured_composition_before_sr', images=[], diagnostics=[])
        def payload(role, extent=size, fmt=10, crop=origin, source=render, salt=0):
            bpp, channels, _, _ = reader.V5_FORMAT_WORDS[fmt]
            amount=extent[0]*extent[1]*bpp
            pattern=np.arange(256, dtype=np.uint8)
            blob=(pattern.astype(np.uint16)+ordinal+salt).astype(np.uint8).tobytes()
            blob=(blob*((amount+255)//256))[:amount]
            file=f'frames/{ordinal}/{role}.bin';p=path/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob)
            return dict(name=role,file=file,bytes=amount,sha256=hashlib.sha256(blob).hexdigest(),
                        extent=extent,crop_origin=crop,source_extent=source,dxgi_format=fmt,
                        channels=channels,bytes_per_pixel=bpp,storage='original_little_endian_gpu_words')
        for role,fmt in reader.V5_IMAGE_FORMATS.items():
            f['images'].append(payload(role,fmt=fmt,salt=0 if role in ('native_full1','current_output') else 2))
        for role,fmt in [('raw_color',10),('raw_normals',10),('raw_motion',10),('raw_depth',39),
                         ('raw_specular_hit_distance',41),('raw_specular_albedo',28),
                         ('raw_diffuse_albedo',28),('raw_bias_mask',61),('rr_specular',10),('rr_diffuse',10)]:
            info=payload(role,fmt=fmt,salt=3);info.update(active=True,available=True);f['diagnostics'].append(info)
        supplied = {d['name'] for d in f['diagnostics']}
        for role in sorted(reader.V5_DIAGNOSTICS-supplied):
            f['diagnostics'].append(dict(name=role,available=False,active=False,reason='Fixture unbound'))
        for role,amount in [('conversion_constants',416),('floor_seed_constants',176),('floor_filter_constants',96)]:
            file=f'frames/{ordinal}/{role}.bin';blob=bytes([ordinal+1])*amount;(path/file).write_bytes(blob)
            f[role]=dict(file=file,bytes=amount,sha256=hashlib.sha256(blob).hexdigest())
        f['floor_seed_constants'].update(available=True,abi_bytes=176,stage='pre_floor_seed_dispatch')
        f['floor_filter_constants'].update(available=True,pass_count=3,record_bytes=32,stage='pre_floor_filter_dispatches')
        f['post_sr']=dict(available=False,reason='Not requested')
        if mode!='off':
            crop=[0,0] if mode=='full_logical_output' else [a*b//c for a,b,c in zip(origin,logical,render)]
            end=logical if mode=='full_logical_output' else [((a+b)*d+c-1)//c for a,b,d,c in zip(origin,size,logical,render)]
            psize=[a-b for a,b in zip(end,crop)]
            p=payload('post_sr',psize,post_format,crop,[logical[0]+8,logical[1]+16],salt=5)
            p.update(available=True,logical_extent=logical,mode=mode,
                     stage='after_sr_before_rcas_output_scaling_overlay',evaluation_id=f['evaluation_id'],
                     context_id='SR-process-context-4567-owner-5678',reset=not reset,
                     dispatch_controls=dict(jitter=[.1,.2],motion_vector_scale=[1,1],render_size=render,
                         upscale_size=logical,frame_time_delta=.016,pre_exposure=1.,reset=not reset,
                         flags=0,camera_near=.02,camera_far=1000.,camera_fov_vertical=1.,
                         view_space_to_meters=1.,enable_sharpening=False,sharpness=0.,create_flags=0))
            f['post_sr']=p
        manifest['frames'].append(f)
    (path/'capture.json').write_text(json.dumps(manifest),encoding='utf-8')
    return manifest


class ReaderV5Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch=Path(os.environ.get('FSRD_TEST_OUTPUT',os.environ.get('TEMP',tempfile.gettempdir())))
        scratch.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(prefix='fsrd-v5-reader-',dir=scratch)
        cls.base=Path(cls.temp.name)
        cls.off=cls.base/'off';cls.off_manifest=fixture(cls.off)
        cls.mapped=cls.base/'mapped';cls.mapped_manifest=fixture(cls.mapped,mode='mapped_render_roi')
        cls.full=cls.base/'full';cls.full_manifest=fixture(cls.full,mode='full_logical_output',count=1,post_format=87)
        cls.wide=cls.base/'wide';cls.wide_manifest=fixture(cls.wide,tile=512,count=1)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def assertReject(self,change,path=None,original=None,payload=False):
        path=path or self.mapped;original=original or self.mapped_manifest
        mutated=copy.deepcopy(original);change(mutated);(path/'capture.json').write_text(json.dumps(mutated))
        try:
            with self.assertRaises(ValueError):reader.inspect_capture(path,payload=payload)
        finally:(path/'capture.json').write_text(json.dumps(original))

    def test_immutable_complete_without_reset_detach(self):
        row,arrays=reader.inspect_capture(self.off,payload=True)
        self.assertTrue(row['immutable_cpu_snapshot_verified'])
        self.assertEqual(row['original_reset_frames'],[1])
        self.assertEqual(arrays['post_sr_original_words'],[])
        self.assertEqual(arrays['raw_color'][0].tobytes(),(self.off/'frames/0/raw_color.bin').read_bytes())

    def test_wide512_preserves_original_words(self):
        _,a=reader.inspect_capture(self.wide,payload=True)
        self.assertEqual(a['raw_color'].shape,(1,512,512,4))
        self.assertEqual(a['native_full1'][0].tobytes(),(self.wide/'frames/0/native_full1.bin').read_bytes())

    def test_mapped_and_full_are_separate_observations(self):
        for path,m in [(self.mapped,self.mapped_manifest),(self.full,self.full_manifest)]:
            row,a=reader.inspect_capture(path,payload=True)
            self.assertFalse(row['post_sr_is_pre_sr_reference'])
            self.assertEqual(len(a['post_sr_original_words']),len(m['frames']))
            for i,words in enumerate(a['post_sr_original_words']):
                self.assertEqual(words.tobytes(),(path/f'frames/{i}/post_sr.bin').read_bytes())
            self.assertNotEqual(a['post_sr_metadata'][0]['context_id'],a['frame_metadata'][0]['context_id'])
            self.assertNotEqual(a['post_sr_metadata'][0]['reset'],a['frame_metadata'][0]['reset'])

    def test_snapshot_and_fence_hostilities(self):
        cases=[lambda f:f.pop('cpu_snapshot_immutable'),lambda f:f.update(submission_gate_protected=False),
               lambda f:f.update(command_list_detached=True),lambda f:f['ticket_proof'].pop('cpu_snapshot_immutable'),
               lambda f:f['ticket_proof'].update(ambiguous_submission=True),
               lambda f:f['ticket_proof'].update(pending_signals=1),lambda f:f['ticket_proof'].update(fence_expected=2),
               lambda f:f['ticket_proof'].update(fence_completed=0),
               lambda f:f['ticket_proof'].update(fence_completed=(1<<64)-1),
               lambda f:f['ticket_proof'].update(signal_hresult=-1),
               lambda f:f['ticket_proof'].update(waitable=True),
               lambda f:f['ticket_proof'].update(waitable=0),
               lambda f:f['ticket_proof'].update(recorded=1),lambda f:f['ticket_proof'].update(detach_kind='final_release')]
        for c in cases:
            with self.subTest(case=c):self.assertReject(lambda m:c(m['frames'][0]))

    def test_actual_reset_detachment_remains_waitable(self):
        m=copy.deepcopy(self.off_manifest)
        for f in m['frames']:
            f['command_list_detached']=True
            f['ticket_proof'].update(detached=True,waitable=True,detach_kind='successful_command_list_reset')
        (self.off/'capture.json').write_text(json.dumps(m))
        try:
            row,_=reader.inspect_capture(self.off,payload=True)
            self.assertTrue(row['immutable_cpu_snapshot_verified'])
            self.assertReject(lambda a:a['frames'][0]['ticket_proof'].update(waitable=False),self.off,m)
        finally:(self.off/'capture.json').write_text(json.dumps(self.off_manifest))

    def test_unused_floor_constants_have_no_payload(self):
        m=copy.deepcopy(self.off_manifest)
        for f in m['frames']:
            for key in ('floor_seed_constants','floor_filter_constants'):
                f[key]={k:v for k,v in f[key].items() if k not in ('file','bytes','sha256')}
                f[key]['available']=False
            f['floor_filter_constants']['pass_count']=0
        (self.off/'capture.json').write_text(json.dumps(m))
        try:
            row,_=reader.inspect_capture(self.off,payload=True)
            self.assertFalse(any('floor_' in d['file'] for d in row['authenticated_payload_files']))
            self.assertReject(lambda a:a['frames'][0]['floor_seed_constants'].update(available=True),self.off,m)
            self.assertReject(lambda a:a['frames'][0]['floor_filter_constants'].update(pass_count=3),self.off,m)
        finally:(self.off/'capture.json').write_text(json.dumps(self.off_manifest))

    def test_missing_seed_replay_rejects_before_build_or_gpu(self):
        m=copy.deepcopy(self.off_manifest)
        for f in m['frames']:
            for key in ('floor_seed_constants','floor_filter_constants'):
                f[key]={k:v for k,v in f[key].items() if k not in ('file','bytes','sha256')}
                f[key]['available']=False
            f['floor_filter_constants']['pass_count']=0
        (self.off/'capture.json').write_text(json.dumps(m))
        try:
            row,a=reader.inspect_capture(self.off,payload=True)
            self.assertEqual(row['missing_floor_seed_constants'],[0,1])
            for floor in (False,True):
                variant='ON' if floor else 'OFF'
                with self.assertRaisesRegex(ValueError,f'Floor {variant} replay.*canonical depth'):
                    reader.preprocess(a,object(),floor,False)
                args=['replay','--capture',str(self.off),'--shader-dir',str(HERE),
                      '--output',str(self.base/'unused-replay'),'--cases',f'{int(floor)}:0']
                with patch.object(sys,'argv',args),patch.object(reader,'compile_cpp') as build, \
                     patch.object(reader.native,'build_native') as native_build, \
                     patch.object(reader,'Gpu') as gpu,patch.object(reader.np,'stack') as decode:
                    with self.assertRaisesRegex(ValueError,f'Floor {variant} replay.*canonical depth'):
                        reader.main()
                    build.assert_not_called();native_build.assert_not_called();gpu.assert_not_called();decode.assert_not_called()
        finally:(self.off/'capture.json').write_text(json.dumps(self.off_manifest))

    def test_optional_diagnostics_keep_original_formats_and_crops(self):
        m=copy.deepcopy(self.off_manifest)
        for f in m['frames']:
            for i,d in enumerate(f['diagnostics']):
                if d['name']=='raw_bias_mask':
                    f['diagnostics'][i]=dict(name='raw_bias_mask',available=False,active=False,reason='Flag inactive')
                elif d['name']=='raw_motion':
                    d.update(dxgi_format=16,channels=2,extent=[256,64],crop_origin=[70,40],source_extent=[512,256])
        (self.off/'capture.json').write_text(json.dumps(m))
        try:
            row,a=reader.inspect_capture(self.off,payload=True)
            self.assertNotIn('raw_bias_mask',a);self.assertNotIn('raw_motion',a)
            self.assertEqual(a['image_original_words']['raw_bias_mask'],[None,None])
            motion=a['image_original_words']['raw_motion'][0]
            self.assertEqual(motion.shape,(64,256,2))
            self.assertEqual(motion.tobytes(),(self.off/'frames/0/raw_motion.bin').read_bytes())
            self.assertFalse(any(d['file'].endswith('/raw_bias_mask.bin') for d in row['authenticated_payload_files']))
            with self.assertRaisesRegex(ValueError,'captured raw_motion.*ROI/format'):
                reader.require_replay_inputs(a,False)
        finally:(self.off/'capture.json').write_text(json.dumps(self.off_manifest))

    def test_same_size_shifted_diagnostic_rejects_replay(self):
        m=copy.deepcopy(self.off_manifest)
        for f in m['frames']:
            d=next(d for d in f['diagnostics'] if d['name']=='raw_color')
            d.update(source_base=[8,4],crop_origin=[48,60])
        (self.off/'capture.json').write_text(json.dumps(m))
        try:
            # A real nonzero title subrect base remains aligned to the ROI.
            _,a=reader.inspect_capture(self.off,payload=True)
            self.assertIn('raw_color',a);reader.require_replay_inputs(a,False)
            d=next(d for d in m['frames'][0]['diagnostics'] if d['name']=='raw_color')
            d['crop_origin']=[49,60]
            (self.off/'capture.json').write_text(json.dumps(m))
            row,a=reader.inspect_capture(self.off,payload=True)
            self.assertNotIn('raw_color',a)
            self.assertEqual(a['image_original_words']['raw_color'][0].shape,(128,128,4))
            self.assertEqual(a['image_original_words']['raw_color'][0].tobytes(),
                             (self.off/'frames/0/raw_color.bin').read_bytes())
            self.assertIn('frames/0/raw_color.bin',[d['file'] for d in row['authenticated_payload_files']])
            with patch.object(reader.np,'zeros') as allocate:
                with self.assertRaisesRegex(ValueError,'captured raw_color.*ROI/format'):
                    reader.preprocess(a,object(),False,False)
                allocate.assert_not_called()
        finally:(self.off/'capture.json').write_text(json.dumps(self.off_manifest))

    def test_full_five_filter_records_are_authenticated(self):
        m=copy.deepcopy(self.off_manifest);f=m['frames'][0]
        p=self.off/'frames/0/floor_filter_constants.bin';original=p.read_bytes()
        blob=bytes([7])*160;p.write_bytes(blob)
        f['floor_filter_constants'].update(pass_count=5,bytes=160,sha256=hashlib.sha256(blob).hexdigest())
        (self.off/'capture.json').write_text(json.dumps(m))
        try:
            row,_=reader.inspect_capture(self.off,payload=True)
            self.assertIn('frames/0/floor_filter_constants.bin',[d['file'] for d in row['authenticated_payload_files']])
        finally:
            p.write_bytes(original);(self.off/'capture.json').write_text(json.dumps(self.off_manifest))

    def test_active_diagnostics_and_constants_contract(self):
        cases=[lambda f:f['diagnostics'][0].update(available=False),
               lambda f:f['diagnostics'][0].update(active=1),
               lambda f:f['diagnostics'][-1].update(active=True),
               lambda f:f['diagnostics'].pop(),
               lambda f:f['conversion_constants'].update(bytes=412),
               lambda f:f['floor_seed_constants'].update(available=False),
               lambda f:f['floor_seed_constants'].update(abi_bytes=160),
               lambda f:f['floor_seed_constants'].update(abi_bytes=176.),
               lambda f:f['floor_filter_constants'].update(pass_count=2),
               lambda f:f['floor_filter_constants'].update(record_bytes=32.),
               lambda f:f['floor_filter_constants'].update(bytes=64)]
        for c in cases:
            with self.subTest(case=c):self.assertReject(lambda m:c(m['frames'][0]))

    def test_lineage_and_control_hostilities(self):
        cases=[lambda m:m.update(schema='fsrd-game-trace-v6'),
               lambda m:m['frames'][1].update(evaluation_id=10),
               lambda m:m['frames'][1].update(recording_qpc=1000),
               lambda m:m['frames'][1].update(native_frame_index=102),
               lambda m:m['frames'][0]['controls'].update(jitter=[float('nan'),0]),
               lambda m:m['frames'][0].update(settings_sha256='0'*64),
               lambda m:m['roi'].update(extent=[256,256])]
        for c in cases:
            with self.subTest(case=c):self.assertReject(c)

    def test_post_sr_hostilities(self):
        cases=[lambda p:p.update(available=False),lambda p:p.update(evaluation_id=999),
               lambda p:p.update(stage='before_sr'),lambda p:p.update(context_id='fake-context'),
               lambda p:p.update(crop_origin=[0,0]),lambda p:p.update(extent=[1,1]),
               lambda p:p.update(dxgi_format=39),lambda p:p.update(reset=not p['reset']),
               lambda p:p['dispatch_controls'].update(render_size=[1,1]),
               lambda p:p['dispatch_controls'].update(pre_exposure=0)]
        for c in cases:
            with self.subTest(case=c):self.assertReject(lambda m:c(m['frames'][0]['post_sr']))
        self.assertReject(lambda m:m['frames'][1]['post_sr'].update(context_id='SR-process-context-4567-owner-6789'))
        self.assertReject(lambda m:m.update(post_sr_mode='off'))

    def test_payload_role_and_format_hostilities(self):
        cases=[lambda f:f['images'].append(copy.deepcopy(f['images'][0])),
               lambda f:f['images'][0].update(file='frames/1/U.bin'),
               lambda f:f['images'][0].update(file='../U.bin'),
               lambda f:f['images'][0].update(bytes=1),
               lambda f:f['images'][0].update(channels=3),
               lambda f:f['images'][0].update(storage='decoded_normalized'),
               lambda f:f['images'][-1].update(sha256='0'*64)]
        for c in cases:
            with self.subTest(case=c):self.assertReject(lambda m:c(m['frames'][0]))

    def test_authenticate_extras_and_post_words(self):
        for role in ['U','rr_diffuse','post_sr','floor_filter_constants']:
            p=self.mapped/f'frames/0/{role}.bin';original=p.read_bytes();p.write_bytes(bytes([original[0]^1])+original[1:])
            try:
                with self.assertRaises(ValueError):reader.inspect_capture(self.mapped,payload=True)
            finally:p.write_bytes(original)

    def test_legacy_v4_retains_existing_checks(self):
        m=copy.deepcopy(self.off_manifest);m['schema']='fsrd-game-trace-v4';m.pop('post_sr_mode')
        for f in m['frames']:
            for k in ['cpu_snapshot_immutable','submission_gate_protected','ticket_proof','post_sr']:f.pop(k)
        (self.off/'capture.json').write_text(json.dumps(m))
        try:
            row,a=reader.inspect_capture(self.off,payload=True)
            self.assertEqual(row['schema'],'fsrd-game-trace-v4')
            self.assertNotIn('post_sr_original_words',a)
            self.assertReject(lambda t:t['frames'][0]['diagnostics'].pop(7),self.off,m,payload=True)
        finally:(self.off/'capture.json').write_text(json.dumps(self.off_manifest))


if __name__=='__main__':unittest.main()
