"""CPU-only hostile fixtures for optional full-native diagnostic RR heads.

Manufactured metadata/pixels exercise parser authentication only. They are not
game captures, IQ references, clean truth, or evidence that RR quality improved.
No GPU work, native build, or existing test suite is invoked.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('full_context_reader_fixture', HERE/'test_fsrd_game_trace_v5_reader.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
reader = fixtures.reader

INPUT_ROLES = [('linear_depth', 'linear_depth', 41, 28), ('motion_vectors', 'motion_vectors', 10, 4),
               ('normals', 'normals', 24, 17), ('specular_albedo', 'specular_albedo', 28, 10),
               ('diffuse_albedo', 'diffuse_albedo', 28, 10),
               ('DirectDiffuse.input', 'chain.0.DirectDiffuse.input', 10, 4),
               ('IndirectSpecular.input', 'chain.1.IndirectSpecular.input', 10, 4)]


def native_words(controls, native_frame, flags):
    # Follow official ffxDispatchDescDenoiser declaration order, not the
    # existing replay's private transfer layout.
    result = b''
    for key in ('motion_vector_scale', 'jitter', 'camera_delta', 'view', 'projection', 'depth_bounds'):
        values = controls[key]
        result += struct.pack('<'+str(len(values))+'f', *values)
    result += struct.pack('<2I', *controls['render_size'])
    result += struct.pack('<2I', native_frame, flags)
    assert len(result) == 184
    return result


def full_context_fixture(path):
    manifest = fixtures.fixture(path, count=2, render=[288, 64], origin=[40, 0],
                                region_mode='full_height_strip', target_frames=128)
    manifest['full_context_reference_requested'] = True
    for frame in manifest['frames']:
        ordinal = frame['ordinal']; extent = manifest['render_extent']; size = manifest['roi']['extent']
        # Distinct physical matrix/vector patterns expose native field swaps.
        # These manufactured values are parser fixtures, not a game scene.
        frame['controls'].update(
            motion_vector_scale=[.5, -.5, 1.25], jitter=[.375, -.25], camera_delta=[.01, -.02, .03],
            view=[.8660254, 0, .5, 0, 0, 1, 0, 0, -.5, 0, .8660254, 0,
                  1.25+ordinal, -2.5, 3.75, 1],
            projection=[1.125, 0, 0, 0, 0, 1.5, 0, 0, 0, 0, 1.001, 1, 0, 0, -.1001, 0],
            depth_bounds=[.125, 2048.25])
        flags = 2 | int(frame['reset']); frame['dispatch_flags'] = flags
        contract = dict(provider_id=4311875584, provider_index=0, provider_name='FSR Ray Regeneration - 1.2.0',
                        provider_selection_provenance='enumerated_override_accepted_by_successful_creation_not_context_provider_query',
                        api_version=4202496, max_render_size=extent, create_flags=0, signal_flags=34,
                        checkerboard_signal_flags=0)
        frame['settings'].update(rr_create_contract=contract, sdk_debug_depth_bounds=[0, 1024])
        frame['settings_canonical_json'] = json.dumps(frame['settings'], sort_keys=True, separators=(',', ':'))
        frame['settings_sha256'] = hashlib.sha256(frame['settings_canonical_json'].encode()).hexdigest()
        bindings = []; clones = []
        for index, (role, binding_role, dxgi, ffx_format) in enumerate(INPUT_ROLES):
            source = dict(alignment=65536, dimension=3, width=extent[0], height=extent[1],
                          depth_or_array_size=1, mip_levels=1, sample_count=1, sample_quality=0,
                          format=dxgi, flags=4, layout=0)
            ffx = dict(type=2, width_or_size=extent[0], height_or_stride=extent[1], depth_or_alignment=1,
                       mip_count=1, format=ffx_format, flags=0, usage=2)
            address = 10000+index*16
            bindings.append(dict(role=binding_role, present=True, resource_address_process_local=address,
                                 native_description=copy.deepcopy(source), ffx_description=copy.deepcopy(ffx),
                                 ffx_declared_state=12))
            clones.append(dict(role=role, original_resource_address_process_local=address,
                               clone_resource_address_process_local=20000+index*16,
                               source_native_description=copy.deepcopy(source), clone_native_description=copy.deepcopy(source),
                               ffx_description=copy.deepcopy(ffx), ffx_declared_state=12, source_state=192,
                               clone_entry_exit_state=192, copy_subresource=0, copy_mip=0, copy_array_slice=0,
                               copy_plane=0, copy_extent=extent,
                               allocation_size_bytes=((extent[0]*extent[1]*reader.V5_FORMAT_WORDS[dxgi][0]+65535)//65536)*65536,
                               allocation_alignment_bytes=65536))
        for index, role in enumerate(('chain.0.DirectDiffuse.output', 'chain.1.IndirectSpecular.output')):
            binding = copy.deepcopy(bindings[-1]); binding.update(role=role, resource_address_process_local=30000+index*16,
                                                                  ffx_declared_state=2)
            bindings.append(binding)
        frame['controls']['rr_dispatch'] = dict(schema='actual_RR_pre_SDK_dispatch_v1', bindings=bindings,
            context_generation=15, dispatch_flags=flags, evaluation_id=frame['evaluation_id'],
            native_frame_index=frame['native_frame_index'], render_size=extent,
            command_list=dict(address_process_local=60000+ordinal*16, type=0))
        for index, info in enumerate(frame['images']):
            info['source_resource_address_process_local'] = 40000+index*16
        controls = {key: copy.deepcopy(frame['controls'][key]) for key in
                    ('motion_vector_scale', 'render_size', 'view', 'projection', 'jitter', 'camera_delta', 'depth_bounds')}
        boundary = dict(wireformat='ffxDispatchDescDenoiser_native_ABI_suffix_264_184', native_dispatch_bytes=448,
                        controls_byte_count=184, controls_offset_in_dispatch=264, controls_flags_offset_in_segment=180,
                        evaluation_id=frame['evaluation_id'], frame_index=frame['native_frame_index'],
                        primary_dispatch_flags=flags, dispatch_flags=flags | 1, render_size=extent,
                        primary_context_generation=15, primary_pre_sdk_boundary=copy.deepcopy(frame['controls']['rr_dispatch']),
                        command_list_address_process_local=60000+ordinal*16, command_list_type=0,
                        context_generation=3, reference_evaluation_id=ordinal+1, controls=controls,
                        primary_control_words_hex=native_words(controls, frame['native_frame_index'], flags).hex(),
                        diagnostic_control_words_hex=native_words(controls, frame['native_frame_index'], flags | 1).hex(),
                        create_contract=copy.deepcopy(contract), sdk_tuning=copy.deepcopy(frame['settings']['sdk_tuning']),
                        sdk_debug_depth_bounds=[0, 1024], clones=clones)
        for index, lobe in enumerate(('specular', 'diffuse')):
            role = 'rr_full_context_reset_'+lobe
            blob = (bytes([31+ordinal+index])*size[0]*size[1]*8)
            file = f'frames/{ordinal}/{role}.bin'; (path/file).write_bytes(blob)
            frame['diagnostics'].append(dict(name=role, file=file, bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(),
                active=True, available=True, bound=True, dxgi_format=10, bytes_per_pixel=8, channels=4,
                extent=size, crop_origin=manifest['roi']['origin'], source_extent=extent, source_base=[0, 0],
                source_state=8, source_resource_address_process_local=50000+index*16,
                source_subresource=0, source_mip=0, source_array_slice=0, source_plane=0,
                source_native_resource_desc=dict(alignment=65536, dimension=3, width=extent[0], height=extent[1],
                    dxgi_format=10, flags=4, depth_or_array_size=1, mip_levels=1, sample_count=1, sample_quality=0, layout=0),
                storage='original_little_endian_gpu_words', mode=reader.V5_FULL_CONTEXT_REFERENCE_MODE,
                role='diagnostic_sdk_reset_each_lobe', stage='post_diagnostic_sdk_pre_sr_capture', lobe=lobe,
                evaluation_id=frame['evaluation_id'], reference_boundary=copy.deepcopy(boundary)))
    (path/'capture.json').write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def references(frame):
    return [info for info in frame['diagnostics'] if info['name'] in reader.V5_FULL_CONTEXT_REFERENCE_ROLES]


def boundary_change(manifest, change, ordinal=0):
    for info in references(manifest['frames'][ordinal]):
        change(info['reference_boundary'])


def witness_word(boundary, offset, value, which=('primary_control_words_hex', 'diagnostic_control_words_hex')):
    for key in which:
        words = bytearray.fromhex(boundary[key]); struct.pack_into('<I', words, offset, value)
        boundary[key] = words.hex()


class FullContextReferenceReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = Path(os.environ.get('FSRD_TEST_OUTPUT', os.environ.get('TEMP', tempfile.gettempdir())))
        scratch.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='fsrd-full-context-reader-', dir=scratch)
        cls.base = Path(cls.temp.name)
        cls.path = cls.base/'full-context'; cls.manifest = full_context_fixture(cls.path)
        cls.legacy = cls.base/'legacy'; fixtures.fixture(cls.legacy, count=2)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def assert_reject(self, change, payload=False, no_reads=False):
        mutated = copy.deepcopy(self.manifest); change(mutated)
        (self.path/'capture.json').write_text(json.dumps(mutated), encoding='utf-8')
        try:
            if no_reads:
                with patch.object(Path, 'read_bytes') as pixels:
                    with self.assertRaises(ValueError): reader.inspect_capture(self.path, payload=payload, limit=1)
                    pixels.assert_not_called()
            else:
                with self.assertRaises(ValueError): reader.inspect_capture(self.path, payload=payload)
        finally:
            (self.path/'capture.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_legacy_without_opt_in_is_unchanged(self):
        row, arrays = reader.inspect_capture(self.legacy, payload=True)
        self.assertNotIn('full_context_reference_requested', row)
        self.assertNotIn('full_context_reference_metadata', arrays)
        self.assertEqual(set(arrays['image_original_words']), set(reader.V5_IMAGE_FORMATS) | reader.V5_DIAGNOSTICS)

    def test_full_native_dispatch_strip_readback_original_words(self):
        row, arrays = reader.inspect_capture(self.path, payload=True)
        self.assertFalse(row['full_frame']); self.assertTrue(row['full_context_reference_requested'])
        self.assertFalse(row['full_context_reference_is_clean_truth'])
        self.assertEqual(row['full_context_reference_mode'], 'full_native_reset_each_not_solution')
        self.assertIn('not a solution', row['full_context_reference_limitation'])
        for ordinal in range(2):
            for role in reader.V5_FULL_CONTEXT_REFERENCE_ROLES:
                words = arrays['image_original_words'][role][ordinal]
                self.assertEqual(words.shape, (64, 128, 4))
                self.assertEqual(words.tobytes(), (self.path/f'frames/{ordinal}/{role}.bin').read_bytes())
                boundary = arrays['full_context_reference_metadata'][ordinal][role]['reference_boundary']
                self.assertEqual(boundary['render_size'], [288, 64])
                self.assertEqual(boundary['dispatch_flags'], self.manifest['frames'][ordinal]['dispatch_flags'] | 1)
        self.assertEqual(len(row['authenticated_payload_files']), 50)
        self.assertEqual(arrays['native_full1'][0].tobytes(), (self.path/'frames/0/native_full1.bin').read_bytes())

    def test_opt_in_role_set_is_closed(self):
        changes = [lambda m: m.pop('full_context_reference_requested'),
                   lambda m: m.update(full_context_reference_requested=False),
                   lambda m: m.update(full_context_reference_requested=1),
                   lambda m: m['frames'][0]['diagnostics'].pop(),
                   lambda m: m['frames'][0]['diagnostics'].append(copy.deepcopy(references(m['frames'][0])[0])),
                   lambda m: references(m['frames'][0])[0].update(name='rr_full_context_warm_specular')]
        for change in changes:
            with self.subTest(change=change): self.assert_reject(change)
        self.assert_reject(lambda m: [f.update(diagnostics=[d for d in f['diagnostics'] if d['name'] not in
                                                               reader.V5_FULL_CONTEXT_REFERENCE_ROLES]) for f in m['frames']])

    def test_reference_scope_geometry_and_identity_hostilities(self):
        updates = [dict(active=False), dict(available=False), dict(active=1), dict(file=None),
                   dict(mode='full_native_warm'), dict(role='sdk_output_lobe'), dict(stage='post_sdk_pre_sr_capture'),
                   dict(lobe='diffuse'), dict(dxgi_format=11), dict(source_extent=[128, 64]),
                   dict(crop_origin=[41, 0]), dict(extent=[128, 63]), dict(source_base=[False, False]),
                   dict(source_state=192), dict(source_state=8.0), dict(evaluation_id=11),
                   dict(source_resource_address_process_local=10000), dict(source_resource_address_process_local=20000),
                   dict(source_resource_address_process_local=30000), dict(source_resource_address_process_local=40000),
                   dict(source_subresource=1)]
        for update in updates:
            with self.subTest(update=update):
                self.assert_reject(lambda m: references(m['frames'][0])[0].update(update))
        for key, value in [('width', 128), ('height', 63), ('flags', 0), ('mip_levels', 2), ('sample_count', 2)]:
            with self.subTest(key=key):
                self.assert_reject(lambda m: references(m['frames'][0])[0]['source_native_resource_desc'].update({key: value}))

    def test_native_control_layout_flags_and_frame_hostilities(self):
        updates = [dict(wireformat='canonical_runner_controls_v1'), dict(native_dispatch_bytes=447),
                   dict(controls_byte_count=180), dict(controls_offset_in_dispatch=0),
                   dict(controls_flags_offset_in_segment=4), dict(primary_dispatch_flags=3),
                   dict(dispatch_flags=2), dict(evaluation_id=11), dict(frame_index=101),
                   dict(context_generation=0), dict(reference_evaluation_id=0), dict(render_size=[128, 64]),
                   dict(primary_context_generation=16), dict(primary_pre_sdk_boundary={}),
                   dict(primary_control_words_hex='00'*183), dict(diagnostic_control_words_hex='AA'*184)]
        for update in updates:
            with self.subTest(update=update): self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(update)))
        for offset, value in [(0, 0), (168, 128), (176, 101), (180, 7)]:
            with self.subTest(offset=offset):
                self.assert_reject(lambda m: boundary_change(m, lambda b: witness_word(b, offset, value)))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b['controls'].update(jitter=[.5, .5])))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b['controls'].update(jitter=[True, 0])))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b['controls'].update(jitter=[float('nan'), 0])))

    def test_native_field_order_and_canonical_impostor_rejected(self):
        frame = self.manifest['frames'][0]
        boundary = references(frame)[0]['reference_boundary']
        words = bytes.fromhex(boundary['primary_control_words_hex'])
        # Offsets follow the official typed ffxDispatchDescDenoiser declaration:
        # motion, jitter, camera, view, projection, depth, render, frame, flags.
        self.assertEqual(struct.unpack_from('<2f', words, 12), (.375, -.25))
        self.assertEqual(words[20:32], struct.pack('<3f', .01, -.02, .03))
        self.assertEqual(words[32:96], struct.pack('<16f', *frame['controls']['view']))
        self.assertEqual(words[96:160], struct.pack('<16f', *frame['controls']['projection']))
        self.assertNotEqual(words[32:96], words[96:160])
        self.assertEqual(struct.unpack_from('<2f', words, 160), (.125, 2048.25))
        self.assertEqual(struct.unpack_from('<2I', words, 168), (288, 64))
        reader.inspect_capture(self.path)

        def canonical_impostor(boundary):
            controls = boundary['controls']
            prefix = struct.pack('<3f2I', *controls['motion_vector_scale'], *controls['render_size'])
            for key in ('view', 'projection', 'jitter', 'camera_delta', 'depth_bounds'):
                values = controls[key]; prefix += struct.pack('<'+str(len(values))+'f', *values)
            prefix += struct.pack('<I', boundary['frame_index'])
            self.assertEqual(len(prefix), 180)
            boundary['primary_control_words_hex'] = (prefix+struct.pack('<I', boundary['primary_dispatch_flags'])).hex()
            boundary['diagnostic_control_words_hex'] = (prefix+struct.pack('<I', boundary['dispatch_flags'])).hex()
            # Keep native wireformat/byte-count labels: matching 184-byte length
            # and only-RESET difference must not authenticate the wrong order.
        self.assert_reject(lambda m: boundary_change(m, canonical_impostor), payload=True, no_reads=True)
        for offset in (12, 28, 32, 96, 160):
            with self.subTest(native_offset=offset):
                self.assert_reject(lambda m: boundary_change(m, lambda b: witness_word(b, offset, 0)))

    def test_signed_zero_native_witness_preserves_sign(self):
        modified = copy.deepcopy(self.manifest)
        # view[1] is zero: legacy JSON may discard its sign, but both exact
        # witnesses carry -0 and remain identical except for the final RESET.
        boundary_change(modified, lambda b: witness_word(b, 36, 0x80000000))
        (self.path/'capture.json').write_text(json.dumps(modified), encoding='utf-8')
        try: reader.inspect_capture(self.path)
        finally: (self.path/'capture.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        self.assert_reject(lambda m: boundary_change(m, lambda b: witness_word(b, 36, 0x80000000,
                                                                               ('diagnostic_control_words_hex',))))
        self.assert_reject(lambda m: boundary_change(m, lambda b: witness_word(b, 36, 1)))

    def test_create_provider_tuning_and_clone_hostilities(self):
        changes = [lambda b: b['create_contract'].update(provider_id=1),
                   lambda b: b['create_contract'].update(create_flags=False),
                   lambda b: b['create_contract'].update(max_render_size=[128, 64]),
                   lambda b: b.update(sdk_tuning=[.5, .5, 40000, 40, .5, .2]),
                   lambda b: b.update(sdk_debug_depth_bounds=[0, 512]),
                   lambda b: b['clones'].pop(), lambda b: b['clones'].reverse(),
                   lambda b: b['clones'][0].update(role='motion_vectors'),
                   lambda b: b['clones'][0].update(original_resource_address_process_local=10016),
                   lambda b: b['clones'][0].update(clone_resource_address_process_local=10000),
                   lambda b: b['clones'][0].update(clone_resource_address_process_local=20016),
                   lambda b: b['clones'][0].update(copy_extent=[128, 64]),
                   lambda b: b['clones'][0].update(copy_mip=1),
                   lambda b: b['clones'][0].update(source_state=8),
                   lambda b: b['clones'][0].update(ffx_declared_state=2),
                   lambda b: b['clones'][0].update(allocation_size_bytes=0),
                   lambda b: b['clones'][0].update(allocation_size_bytes=65536),
                   lambda b: b['clones'][0].update(allocation_alignment_bytes=3),
                   lambda b: b['clones'][0].update(allocation_size_bytes=131073),
                   lambda b: b['clones'][0]['clone_native_description'].update(width=128),
                   lambda b: b['clones'][0]['source_native_description'].update(format=41.0),
                   lambda b: b['clones'][0]['source_native_description'].update(width=128),
                   lambda b: b['clones'][0]['ffx_description'].update(width_or_size=128)]
        for change in changes:
            with self.subTest(change=change): self.assert_reject(lambda m: boundary_change(m, change))

    def test_head_and_context_lineage_hostilities(self):
        self.assert_reject(lambda m: references(m['frames'][0])[1].update(source_resource_address_process_local=50000))
        self.assert_reject(lambda m: references(m['frames'][0])[1]['reference_boundary'].update(reference_evaluation_id=9))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(context_generation=4), ordinal=1))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(reference_evaluation_id=1), ordinal=1))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(reference_evaluation_id=2)))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(reference_evaluation_id=3), ordinal=1))
        self.assert_reject(lambda m: m['frames'][1]['controls']['rr_dispatch'].update(context_generation=16))

    def test_whole_published_prefix_is_validated_before_any_payload_read(self):
        self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(dispatch_flags=0), ordinal=1),
                           payload=True, no_reads=True)
        self.assert_reject(lambda m: references(m['frames'][0])[0].update(file='../outside.bin'),
                           payload=True, no_reads=True)

    def test_full_context_direct_list_and_one_actual_queue_required(self):
        def compute_list(manifest):
            frame = manifest['frames'][0]
            frame['controls']['rr_dispatch']['command_list']['type'] = 2
            boundary_change(manifest, lambda b: b.update(command_list_type=2,
                primary_pre_sdk_boundary=copy.deepcopy(frame['controls']['rr_dispatch'])))
        self.assert_reject(compute_list)
        self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(command_list_address_process_local=60016)))
        self.assert_reject(lambda m: boundary_change(m, lambda b: b.update(command_list_type=2)))
        self.assert_reject(lambda m: m['frames'][1]['ticket_proof'].update(queue_address_process_local=3456),
                           payload=True, no_reads=True)
        self.assert_reject(lambda m: m['frames'][0]['ticket_proof'].update(queue_address_process_local=0))
        self.assert_reject(lambda m: m['frames'][0]['ticket_proof'].update(queue_address_process_local=True))
        legacy_manifest = json.loads((self.legacy/'capture.json').read_text(encoding='utf-8'))
        changed = copy.deepcopy(legacy_manifest); changed['frames'][1]['ticket_proof']['queue_address_process_local'] = 3456
        (self.legacy/'capture.json').write_text(json.dumps(changed), encoding='utf-8')
        try: reader.inspect_capture(self.legacy)
        finally: (self.legacy/'capture.json').write_text(json.dumps(legacy_manifest), encoding='utf-8')

    def test_diagnostic_payload_hash_is_authenticated(self):
        self.assert_reject(lambda m: references(m['frames'][0])[0].update(sha256='0'*64), payload=True)


if __name__ == '__main__':
    unittest.main()
