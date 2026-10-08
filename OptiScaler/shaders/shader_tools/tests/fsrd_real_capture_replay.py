"""Replay live-game ROI sequences through production Floor, signed AMD RR and Bleed.

The capture's ROI is explicit: this tool never calls a crop a full-frame replay.
It retains one native RR context and every frame's matrices, jitter, camera delta,
depth bounds and motion scale. No synthetic RR or repeated single-frame inputs
are used. An optional --reset-frame is an injected reset probe, not a captured
camera cut. Metrics use the late raw temporal mean as a stationary-scene proxy;
they are not ground-truth disocclusion or texture-quality gates.

Set TEMP/TMP and FSRD_CPP_CACHE to a drive with free space. Example:
  python fsrd_real_capture_replay.py --capture TRACE/UUID --shader-dir SNAPSHOT
      --output E:/FSRD/run --cases 0:0 0:1 1:0 1:1 --frames 128
  python fsrd_real_capture_replay.py --inventory TRACE --output E:/FSRD/inventory

reserve_data is excluded before traversal and rejected even as an explicit path.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp
import fsrd_floor_rr_replay as native

spec = importlib.util.spec_from_file_location('capture_mirrors', HERE.parent / 'verify_fsrd_mirrors.py')
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)
MARKERS = dict(FSRDFloorSeed='CB_Median', FSRDFloor='CB_Analysis', FSRDInputConv='CB_Packing',
               FSRDOutputComp='CB_Comp', FSRDAlbedoTrustEvidence='CB_AlbedoTrust',
               FSRDAlbedoTrustPropagate='CB_AlbedoTrust')


def safe_path(value):
    path = Path(value).resolve()
    if any(part.lower() == 'reserve_data' for part in path.parts):
        raise ValueError('reserve_data holdout must not be accessed')
    return path


def digest(path):
    return native._sha256(path)


def camera_crop(extent, roi):
    fw, fh = extent
    w, h = roi['extent']; x, y = roi['origin']
    crop = np.eye(4, dtype=np.float64)
    crop[0, 0], crop[1, 1] = w / fw, h / fh
    crop[0, 3], crop[1, 3] = (2*x+w) / fw - 1, 1 - (2*y+h) / fh
    return crop


V5_SCHEMA = 'fsrd-game-trace-v5'
V5_REGION_MODES = {'square', 'full_height_strip', 'full_render'}
V5_TARGET_FRAMES = {128, 256, 512}
V5_IMAGE_FORMATS = dict(U=10, V=10, Qs=28, Qd=28, Skip=10, packed=24,
                        depth=41, motion=10, native_full1=10, current_output=10)
V5_FORMAT_WORDS = {2: (16, 4, '<f4', 4), 6: (12, 3, '<f4', 3),
                   10: (8, 4, '<f2', 4), 11: (8, 4, '<u2', 4), 16: (8, 2, '<f4', 2),
                   24: (4, 4, '<u4', 1), 26: (4, 3, '<u4', 1),
                   28: (4, 4, 'u1', 4), 87: (4, 4, 'u1', 4),
                   34: (4, 2, '<f2', 2), 35: (4, 2, '<u2', 2),
                   39: (4, 1, '<u4', 1), 40: (4, 1, '<u4', 1), 41: (4, 1, '<f4', 1),
                   44: (4, 1, '<u4', 1), 45: (4, 1, '<u4', 1), 46: (4, 1, '<u4', 1),
                   54: (2, 1, '<f2', 1), 56: (2, 1, '<u2', 1), 61: (1, 1, 'u1', 1)}
V5_POST_FORMATS = {2, 6, 10, 11, 24, 26, 28, 87}
V5_DIAGNOSTICS = {'raw_color', 'raw_normals', 'raw_specular_albedo', 'raw_diffuse_albedo',
                  'rr_specular', 'rr_diffuse', 'raw_bias_mask', 'raw_specular_hit_distance',
                  'raw_specular_direction_hit_distance', 'raw_diffuse_hit_distance',
                  'raw_responsivity', 'raw_emissive',
                  'raw_motion', 'raw_depth', 'raw_roughness', 'raw_title_linear_depth',
                  'raw_inspector', 'floor', 'floor_reference'}
V5_FULL_CONTEXT_REFERENCE_ROLES = {'rr_full_context_reset_specular', 'rr_full_context_reset_diffuse'}
V5_FULL_CONTEXT_REFERENCE_MODE = 'full_native_reset_each_not_solution'


def _v5_int(value, label, minimum=0, maximum=(1 << 64)-1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('v5 invalid integer: '+label)
    return value


def _v5_pair(value, label, minimum=1):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('v5 invalid extent/origin: '+label)
    return [_v5_int(v, label, minimum, 16384) for v in value]


def _v5_finite(value, label, count=None):
    values = value if count is not None else [value]
    if count is not None and (not isinstance(values, list) or len(values) != count):
        raise ValueError('v5 invalid control shape: '+label)
    if any(type(v) not in (int, float) or not np.isfinite(v) for v in values):
        raise ValueError('v5 nonfinite/nonnumeric control: '+label)


def _v5_same_json(left, right):
    # Python equality conflates bool/int and int/float. Native descriptor and
    # create-contract JSON retains those types, so compare the typed spelling.
    return json.dumps(left, sort_keys=True, separators=(',', ':')) == \
        json.dumps(right, sort_keys=True, separators=(',', ':'))


def _v5_payload_path(root, ordinal, role, info):
    expected = f'frames/{ordinal}/{role}.bin'
    value = info.get('file')
    if not isinstance(value, str) or value != expected or str(PurePosixPath(value)) != value:
        raise ValueError('v5 payload role/path mismatch: '+role)
    file = safe_path(root/value)
    if not file.is_relative_to(root):
        raise ValueError('v5 payload escapes capture directory')
    _v5_int(info.get('bytes'), role+' bytes', 1)
    if not isinstance(info.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', info['sha256']):
        raise ValueError('v5 invalid payload hash: '+role)
    return file


def _v5_image(root, ordinal, role, info):
    file = _v5_payload_path(root, ordinal, role, info)
    fmt = _v5_int(info.get('dxgi_format'), role+' DXGI format')
    if fmt not in V5_FORMAT_WORDS:
        raise ValueError('v5 image DXGI format needs reader support: '+role)
    bpp, channels, _, _ = V5_FORMAT_WORDS[fmt]
    if info.get('bytes_per_pixel') != bpp or type(info.get('bytes_per_pixel')) is not int or \
            info.get('channels') != channels or type(info.get('channels')) is not int:
        raise ValueError('v5 image format/channels/word-size mismatch: '+role)
    size = _v5_pair(info.get('extent'), role+' extent')
    source = _v5_pair(info.get('source_extent'), role+' source extent')
    origin = _v5_pair(info.get('crop_origin'), role+' crop origin', 0)
    if any(a+b > c for a, b, c in zip(origin, size, source)):
        raise ValueError('v5 image crop lies outside source: '+role)
    if info['bytes'] != size[0]*size[1]*bpp:
        raise ValueError('v5 image byte extent mismatch: '+role)
    if info.get('storage') != 'original_little_endian_gpu_words':
        raise ValueError('v5 image storage must preserve original GPU words: '+role)
    return file


def _v5_replay_crop_aligned(info, origin, size):
    # Plain diagnostic copies use render ROI + the title resource's subrect
    # base. Replay binds those cropped words at base zero, so another equally
    # sized rectangle cannot be treated as the same aligned input.
    base = info.get('source_base', [0, 0])
    if not isinstance(base, list) or len(base) != 2 or any(type(v) is not int or v < 0 for v in base):
        return False
    if info['crop_origin'] != [a+b for a, b in zip(origin, base)]:
        return False
    mapping = info.get('mapping')
    if info['name'] == 'raw_motion' and mapping is not None:
        # Display-resolution motion needs its original bounding-rectangle
        # addressing, which the replay's fixed raw-MV binding does not provide.
        if not isinstance(mapping, dict) or mapping.get('display_resolution') is not False:
            return False
        try:
            if _v5_pair(mapping.get('render_roi_origin'), 'motion render ROI origin', 0) != origin or \
                    ('render_roi_extent' in mapping and
                     _v5_pair(mapping['render_roi_extent'], 'motion render ROI extent') != size):
                return False
        except ValueError:
            return False
    return True


def _v5_full_context_boundary(boundary, frame, extent):
    """Authenticate the recorded native dispatch controls, with only RESET changed.

    This is a separate diagnostic dispatch, not a substitute for primary pixels
    or an independent clean reference. The native words retain signed zero even
    when the older primary JSON formatter spells it as integer zero.
    """
    if not isinstance(boundary, dict):
        raise ValueError('v5 full-context reference boundary must be an object')
    if boundary.get('wireformat') != 'ffxDispatchDescDenoiser_native_ABI_suffix_264_184':
        raise ValueError('v5 full-context native control wireformat mismatch')
    for key, expected in [('native_dispatch_bytes', 448), ('controls_byte_count', 184), ('controls_offset_in_dispatch', 264),
                          ('controls_flags_offset_in_segment', 180)]:
        if type(boundary.get(key)) is not int or boundary[key] != expected:
            raise ValueError('v5 full-context native control layout mismatch: '+key)
    flags = _v5_int(frame.get('dispatch_flags'), 'primary dispatch flags', 0, (1 << 32)-1)
    native_frame = _v5_int(frame['native_frame_index'], 'primary native frame', 0, (1 << 32)-1)
    for key, expected in [('evaluation_id', frame['evaluation_id']), ('frame_index', native_frame),
                          ('primary_dispatch_flags', flags), ('dispatch_flags', flags | 1)]:
        if type(boundary.get(key)) is not int or boundary[key] != expected:
            raise ValueError('v5 full-context reference dispatch identity mismatch: '+key)
    if bool(flags & 1) != frame['reset']:
        raise ValueError('v5 full-context primary reset flag mismatch')
    _v5_int(boundary.get('context_generation'), 'diagnostic context generation', 1)
    _v5_int(boundary.get('reference_evaluation_id'), 'diagnostic evaluation ID', 1)
    if _v5_pair(boundary.get('render_size'), 'diagnostic native render size') != extent:
        raise ValueError('v5 full-context reference render extent mismatch')
    words = []
    for key in ('primary_control_words_hex', 'diagnostic_control_words_hex'):
        value = boundary.get(key)
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{368}', value):
            raise ValueError('v5 full-context control witness must contain 184 lowercase-hex bytes')
        words.append(bytes.fromhex(value))
    primary, diagnostic = words
    if primary[:180] != diagnostic[:180] or struct.unpack_from('<I', primary, 180)[0] != flags or \
            struct.unpack_from('<I', diagnostic, 180)[0] != flags | 1 or \
            struct.unpack_from('<I', primary, 176)[0] != native_frame or \
            list(struct.unpack_from('<II', primary, 168)) != extent:
        raise ValueError('v5 full-context native controls differ beyond RESET')
    controls = boundary.get('controls')
    if not isinstance(controls, dict):
        raise ValueError('v5 full-context controls must be an object')
    # Official ffxDispatchDescDenoiser native suffix order: motion scale,
    # jitter, camera delta, view, projection, depth bounds, render size,
    # native frame and flags. This differs from the replay wire format.
    for key, count, offset in [('motion_vector_scale', 3, 0), ('jitter', 2, 12),
                               ('camera_delta', 3, 20), ('view', 16, 32),
                               ('projection', 16, 96), ('depth_bounds', 2, 160)]:
        _v5_finite(controls.get(key), 'diagnostic '+key, count)
        for index, (actual, reference) in enumerate(zip(frame['controls'][key], controls[key])):
            try:
                actual_bits = struct.unpack('<I', struct.pack('<f', actual))[0]
                reference_bits = struct.unpack('<I', struct.pack('<f', reference))[0]
            except (OverflowError, struct.error) as error:
                raise ValueError('v5 full-context controls exceed float32 range') from error
            native_bits = struct.unpack_from('<I', primary, offset+4*index)[0]
            zero = actual == 0 and reference == 0 and native_bits & 0x7fffffff == 0
            if not zero and (actual_bits != native_bits or actual_bits != reference_bits):
                raise ValueError('v5 full-context native witness/control mismatch: '+key)
    if _v5_pair(controls.get('render_size'), 'diagnostic control render size') != extent:
        raise ValueError('v5 full-context diagnostic control render extent mismatch')
    contract = boundary.get('create_contract')
    expected_contract = frame['settings'].get('rr_create_contract')
    if not isinstance(contract, dict) or not isinstance(expected_contract, dict) or not _v5_same_json(contract, expected_contract):
        raise ValueError('v5 full-context create/provider contract mismatch')
    for key in ('provider_id', 'api_version'):
        _v5_int(contract.get(key), 'diagnostic create '+key, 1)
    for key in ('provider_index', 'create_flags', 'signal_flags', 'checkerboard_signal_flags'):
        _v5_int(contract.get(key), 'diagnostic create '+key, 0, (1 << 32)-1)
    for key in ('provider_name', 'provider_selection_provenance'):
        if not isinstance(contract.get(key), str) or not contract[key]:
            raise ValueError('v5 full-context create/provider identity missing: '+key)
    maximum = _v5_pair(contract.get('max_render_size'), 'diagnostic create max render size')
    if any(a < b for a, b in zip(maximum, extent)):
        raise ValueError('v5 full-context create maximum does not contain render extent')
    for key, count in [('sdk_tuning', 6), ('sdk_debug_depth_bounds', 2)]:
        values = boundary.get(key); expected = frame['settings'].get(key)
        _v5_finite(values, 'diagnostic '+key, count)
        _v5_finite(expected, 'primary '+key, count)
        try:
            equal = struct.pack('<'+str(count)+'f', *values) == struct.pack('<'+str(count)+'f', *expected)
        except (OverflowError, struct.error) as error:
            raise ValueError('v5 full-context tuning exceeds float32 range') from error
        if not equal:
            raise ValueError('v5 full-context tuning differs from primary dispatch')
    dispatch = frame['controls'].get('rr_dispatch')
    if not isinstance(dispatch, dict) or dispatch.get('schema') != 'actual_RR_pre_SDK_dispatch_v1' or \
            type(dispatch.get('dispatch_flags')) is not int or dispatch['dispatch_flags'] != flags or \
            type(dispatch.get('native_frame_index')) is not int or dispatch['native_frame_index'] != native_frame or \
            type(dispatch.get('evaluation_id')) is not int or dispatch['evaluation_id'] != frame['evaluation_id'] or \
            dispatch.get('render_size') != extent:
        raise ValueError('v5 full-context primary RR boundary identity mismatch')
    _v5_int(dispatch.get('context_generation'), 'primary RR context generation', 1)
    if type(boundary.get('primary_context_generation')) is not int or \
            boundary['primary_context_generation'] != dispatch['context_generation'] or \
            not _v5_same_json(boundary.get('primary_pre_sdk_boundary'), dispatch):
        raise ValueError('v5 full-context primary pre-SDK boundary mismatch')
    command_list = dispatch.get('command_list')
    if not isinstance(command_list, dict) or type(command_list.get('type')) is not int or command_list['type'] != 0 or \
            type(boundary.get('command_list_type')) is not int or boundary['command_list_type'] != 0:
        raise ValueError('v5 full-context reference requires recorded DIRECT command lists')
    address = _v5_int(command_list.get('address_process_local'), 'primary DIRECT command-list identity', 1)
    if type(boundary.get('command_list_address_process_local')) is not int or \
            boundary['command_list_address_process_local'] != address:
        raise ValueError('v5 full-context reference command-list identity differs from primary')
    bindings = dispatch.get('bindings')
    if not isinstance(bindings, list) or len(bindings) != 9 or \
            any(not isinstance(binding, dict) or not isinstance(binding.get('role'), str) for binding in bindings):
        raise ValueError('v5 full-context primary RR bindings missing')
    by_role = {binding['role']: binding for binding in bindings}
    mapping = [('linear_depth', 'linear_depth'), ('motion_vectors', 'motion_vectors'), ('normals', 'normals'),
               ('specular_albedo', 'specular_albedo'), ('diffuse_albedo', 'diffuse_albedo'),
               ('DirectDiffuse.input', 'chain.0.DirectDiffuse.input'),
               ('IndirectSpecular.input', 'chain.1.IndirectSpecular.input')]
    expected_roles = {name for _, name in mapping} | {'chain.0.DirectDiffuse.output', 'chain.1.IndirectSpecular.output'}
    if len(by_role) != 9 or set(by_role) != expected_roles:
        raise ValueError('v5 full-context primary RR binding roles ambiguous')
    primary_addresses = set()
    for binding in bindings:
        if binding.get('present') is not True:
            raise ValueError('v5 full-context primary RR binding absent')
        primary_addresses.add(_v5_int(binding.get('resource_address_process_local'), 'primary RR resource identity', 1))
    clones = boundary.get('clones')
    if not isinstance(clones, list) or len(clones) != len(mapping):
        raise ValueError('v5 full-context immutable input clones missing')
    clone_addresses = set()
    for clone, (name, primary_name) in zip(clones, mapping):
        if not isinstance(clone, dict) or clone.get('role') != name:
            raise ValueError('v5 full-context clone roles duplicate or out of order')
        binding = by_role[primary_name]
        original = _v5_int(clone.get('original_resource_address_process_local'), 'original clone resource identity', 1)
        address = _v5_int(clone.get('clone_resource_address_process_local'), 'cloned resource identity', 1)
        if original != binding['resource_address_process_local'] or address in primary_addresses or address in clone_addresses:
            raise ValueError('v5 full-context clone aliases or mismatches primary resource')
        clone_addresses.add(address)
        source = clone.get('source_native_description'); copied = clone.get('clone_native_description')
        ffx = clone.get('ffx_description')
        if not isinstance(source, dict) or not isinstance(copied, dict) or not isinstance(ffx, dict) or \
                not _v5_same_json(source, binding.get('native_description')) or not _v5_same_json(copied, source) or \
                not _v5_same_json(ffx, binding.get('ffx_description')):
            raise ValueError('v5 full-context clone resource/FFX descriptor mismatch')
        if any(type(source.get(k)) is not int or source[k] != value
               for k, value in [('dimension', 3), ('width', extent[0]), ('height', extent[1]),
                                ('depth_or_array_size', 1), ('mip_levels', 1), ('sample_count', 1)]) or \
                type(source.get('flags')) is not int or source['flags'] & 4 != 4:
            raise ValueError('v5 full-context clone does not retain the full native extent')
        if any(type(ffx.get(k)) is not int or ffx[k] != value
               for k, value in [('type', 2), ('width_or_size', extent[0]), ('height_or_stride', extent[1]),
                                ('depth_or_alignment', 1), ('mip_count', 1), ('usage', 2)]):
            raise ValueError('v5 full-context clone FFX geometry/usage mismatch')
        for key, expected in [('ffx_declared_state', 12), ('source_state', 192), ('clone_entry_exit_state', 192),
                              ('copy_subresource', 0), ('copy_mip', 0), ('copy_array_slice', 0), ('copy_plane', 0)]:
            if type(clone.get(key)) is not int or clone[key] != expected:
                raise ValueError('v5 full-context clone copy/state contract mismatch: '+key)
        if _v5_pair(clone.get('copy_extent'), 'diagnostic clone copy extent') != extent or \
                type(binding.get('ffx_declared_state')) is not int or binding['ffx_declared_state'] != 12:
            raise ValueError('v5 full-context clone extent/declared-state mismatch')
        allocation = _v5_int(clone.get('allocation_size_bytes'), 'diagnostic clone allocation bytes', 1)
        alignment = _v5_int(clone.get('allocation_alignment_bytes'), 'diagnostic clone allocation alignment', 1)
        native_format = _v5_int(source.get('format'), 'diagnostic clone native format')
        if native_format not in V5_FORMAT_WORDS or alignment & (alignment-1) or allocation % alignment or \
                allocation < extent[0]*extent[1]*V5_FORMAT_WORDS[native_format][0]:
            raise ValueError('v5 full-context clone allocation contract cannot contain native words')
    return primary_addresses | clone_addresses


def _v5_full_context_image(info, frame, extent, origin, size):
    if info.get('active') is not True or info.get('available') is not True or not info.get('file'):
        raise ValueError('v5 requested full-context reference lacks verified pixels')
    if info.get('mode') != V5_FULL_CONTEXT_REFERENCE_MODE or \
            info.get('role') != 'diagnostic_sdk_reset_each_lobe' or \
            info.get('stage') != 'post_diagnostic_sdk_pre_sr_capture':
        raise ValueError('v5 full-context reference mode/role/stage mismatch')
    if info.get('dxgi_format') != 10 or info.get('extent') != size or \
            info.get('source_extent') != extent or info.get('crop_origin') != origin or \
            _v5_pair(info.get('source_base'), 'diagnostic source base', 0) != [0, 0] or \
            type(info.get('source_state')) is not int or info['source_state'] != 8:
        raise ValueError('v5 full-context reference is not a full-native RGBA16F UAV/ROI')
    if type(info.get('evaluation_id')) is not int or info['evaluation_id'] != frame['evaluation_id']:
        raise ValueError('v5 full-context reference evaluation mismatch')
    native_desc = info.get('source_native_resource_desc')
    if not isinstance(native_desc, dict) or any(type(native_desc.get(k)) is not int or native_desc[k] != value
            for k, value in [('dimension', 3), ('width', extent[0]), ('height', extent[1]),
                             ('dxgi_format', 10), ('depth_or_array_size', 1), ('mip_levels', 1), ('sample_count', 1)]) or \
            type(native_desc.get('flags')) is not int or native_desc['flags'] & 4 != 4:
        raise ValueError('v5 full-context native source descriptor mismatch')
    for key in ('source_subresource', 'source_mip', 'source_array_slice', 'source_plane'):
        if type(info.get(key)) is not int or info[key] != 0:
            raise ValueError('v5 full-context reference source subresource mismatch')
    address = _v5_int(info.get('source_resource_address_process_local'), 'diagnostic output resource identity', 1)
    boundary = info.get('reference_boundary')
    if address in _v5_full_context_boundary(boundary, frame, extent) or \
            any(address == image.get('source_resource_address_process_local') for image in frame['images']):
        raise ValueError('v5 full-context output aliases a primary or cloned input resource')
    expected_lobe = 'specular' if info['name'].endswith('specular') else 'diffuse'
    if info.get('lobe') != expected_lobe:
        raise ValueError('v5 full-context reference output lobe mismatch')
    return boundary


def _validate_v5_capture(path, manifest, frames):
    """Validate v5 metadata before any optional payload read; v4 stays unchanged."""
    extent = _v5_pair(manifest.get('render_extent'), 'render extent')
    roi = manifest['roi']; size = _v5_pair(roi.get('extent'), 'ROI extent')
    origin = _v5_pair(roi.get('origin'), 'ROI origin', 0)
    # Older v5 recorders published square ROIs without an explicit mode. A
    # rectangle is only accepted when the manifest declares how it was resolved
    # against the first render extent; that rectangle stays fixed for the trace.
    region = manifest.get('region_mode', 'square')
    if not isinstance(region, str) or region not in V5_REGION_MODES:
        raise ValueError('v5 invalid requested region mode')
    if region == 'square':
        supported = size in ([128, 128], [512, 512])
    elif region == 'full_height_strip':
        supported = size[0] in (128, 512) and size[1] == extent[1] and origin[1] == 0
    else:
        supported = size == extent and origin == [0, 0]
    if not supported:
        raise ValueError('v5 unsupported requested ROI extent')
    if 'geometry_resolved' in roi and roi['geometry_resolved'] is not True:
        raise ValueError('v5 published ROI geometry is unresolved')
    target = manifest.get('target_frames')
    if 'target_frames' in manifest and _v5_int(target, 'target frames') not in V5_TARGET_FRAMES:
        raise ValueError('v5 unsupported requested frame count')
    if type(manifest.get('complete')) is not bool:
        raise ValueError('v5 completeness must be a captured boolean')
    if target is not None and (len(frames) > target or manifest['complete'] and len(frames) != target):
        raise ValueError('v5 published prefix contradicts requested frame count')
    mode = manifest.get('post_sr_mode')
    if mode not in ('off', 'mapped_render_roi', 'full_logical_output'):
        raise ValueError('v5 invalid post-SR observation mode')
    requested = manifest.get('full_context_reference_requested', False)
    if type(requested) is not bool:
        raise ValueError('v5 full-context reference request must be a boolean')
    diagnostic_roles = V5_DIAGNOSTICS | (V5_FULL_CONTEXT_REFERENCE_ROLES if requested else set())
    post_context = None; post_layout = None; descriptors = []; post = []
    reference_context = None; reference_evaluation = None; primary_generation = None; reference_queue = None
    for f in frames:
        ordinal = _v5_int(f['ordinal'], 'ordinal')
        _v5_int(f.get('evaluation_id'), 'evaluation ID', 1)
        _v5_int(f.get('native_frame_index'), 'native frame index')
        _v5_int(f.get('recording_qpc'), 'recording timestamp', 1)
        if not isinstance(f.get('context_id'), str) or not f['context_id']:
            raise ValueError('v5 missing RR context identity')
        if type(f.get('reset')) is not bool:
            raise ValueError('v5 reset must be captured boolean')
        if f.get('gpu_submission_verified') is not True or f.get('gpu_completed') is not True:
            raise ValueError('v5 GPU completion/submission must be verified booleans')
        if f.get('cpu_snapshot_immutable') is not True or f.get('submission_gate_protected') is not True:
            raise ValueError('v5 lacks verified immutable CPU snapshot gate')
        proof = f.get('ticket_proof')
        if not isinstance(proof, dict):
            raise ValueError('v5 missing immutable CPU snapshot ticket proof')
        for key in ('recorded', 'submitted', 'cpu_snapshot_immutable', 'submission_gate_protected'):
            if proof.get(key) is not True:
                raise ValueError('v5 unverified snapshot proof: '+key)
        for key in ('invalid', 'abandoned', 'signal_failed', 'ambiguous_submission'):
            if proof.get(key) is not False:
                raise ValueError('v5 invalid/ambiguous snapshot proof: '+key)
        if _v5_int(proof.get('pending_signals'), 'pending signals') != 0 or \
                _v5_int(proof.get('fence_expected'), 'expected fence', 1) != 1:
            raise ValueError('v5 snapshot proof has unresolved/repeated submission')
        _v5_int(proof.get('fence_completed'), 'completed fence', 1, (1 << 64)-2)
        _v5_int(proof.get('signal_hresult'), 'signal HRESULT', 0, (1 << 31)-1)
        for key in ('identity_address_process_local', 'ticket_generation', 'queue_address_process_local'):
            _v5_int(proof.get(key), key, 1)
        detached = proof.get('detached')
        if type(detached) is not bool or type(f.get('command_list_detached')) is not bool or \
                f['command_list_detached'] != detached:
            raise ValueError('v5 command-list detach proof mismatch')
        expected_kind = 'successful_command_list_reset' if detached else 'not_observed'
        if proof.get('detach_kind') != expected_kind:
            raise ValueError('v5 detach kind contradicts immutable snapshot proof')
        # CanWait/CanRelease still require a real Reset. An immutable CPU copy
        # may be published before that Reset under the submission snapshot gate.
        if type(proof.get('waitable')) is not bool or proof['waitable'] != detached:
            raise ValueError('v5 waitable proof contradicts command-list detachment')
        controls = f['controls']
        if not isinstance(controls, dict):
            raise ValueError('v5 RR controls must be an object')
        if _v5_pair(controls.get('render_size'), 'RR render size') != extent:
            raise ValueError('v5 RR control/render extent mismatch')
        for key, count in [('view', 16), ('projection', 16), ('jitter', 2),
                           ('camera_delta', 3), ('motion_vector_scale', 3), ('depth_bounds', 2)]:
            _v5_finite(controls.get(key), 'RR '+key, count)
        _v5_finite(controls.get('pre_exposure'), 'RR pre-exposure')
        if controls['pre_exposure'] <= 0 or type(controls.get('pre_exposure_provided')) is not bool:
            raise ValueError('v5 invalid captured pre-exposure')
        if type(controls.get('motion_history_valid')) is not bool:
            raise ValueError('v5 motion history validity must be captured boolean')
        canonical = f.get('settings_canonical_json')
        if not isinstance(f.get('settings'), dict) or not isinstance(canonical, str) or \
                hashlib.sha256(canonical.encode('utf-8')).hexdigest() != f.get('settings_sha256') or \
                json.loads(canonical) != f.get('settings'):
            raise ValueError('v5 settings fingerprint mismatch')
        if f.get('output_scope') != 'actual_configured_composition_before_sr' or \
                controls.get('output_scope') != f['output_scope']:
            raise ValueError('v5 pre-SR observation scope mismatch')
        images = f.get('images')
        if not isinstance(images, list) or len(images) != len(V5_IMAGE_FORMATS):
            raise ValueError('v5 main image roles are incomplete/ambiguous')
        by_name = {}
        for info in images:
            if not isinstance(info, dict):
                raise ValueError('v5 main image descriptor must be an object')
            name = info.get('name')
            if name not in V5_IMAGE_FORMATS or name in by_name:
                raise ValueError('v5 duplicate/unsupported main image role')
            file = _v5_image(path, ordinal, name, info)
            if info['dxgi_format'] != V5_IMAGE_FORMATS[name] or info['extent'] != size or info['crop_origin'] != origin:
                raise ValueError('v5 main image format/ROI role mismatch: '+name)
            if any(a < b for a, b in zip(info['source_extent'], extent)):
                raise ValueError('v5 main source does not contain logical render extent')
            by_name[name] = info; descriptors.append((file, info, None))
        if any(by_name['native_full1'][k] != by_name['current_output'][k]
               for k in ('sha256', 'bytes', 'dxgi_format', 'extent', 'crop_origin', 'source_extent')):
            raise ValueError('v5 native_full1/current_output pre-SR alias mismatch')
        names = set(by_name)
        diagnostics = f.get('diagnostics', [])
        if not isinstance(diagnostics, list):
            raise ValueError('v5 diagnostics must be a list')
        reference_boundary = None; reference_addresses = set()
        for info in diagnostics:
            if not isinstance(info, dict):
                raise ValueError('v5 diagnostic descriptor must be an object')
            name = info.get('name')
            if name not in diagnostic_roles or name in names:
                raise ValueError('v5 duplicate/unsupported diagnostic role')
            names.add(name)
            if type(info.get('active')) is not bool or type(info.get('available')) is not bool:
                raise ValueError('v5 diagnostic availability/activity must be booleans')
            if info['active'] != info['available']:
                raise ValueError('v5 active diagnostic lacks verified pixels')
            if info.get('file'):
                if info.get('available') is not True or info.get('active') is False:
                    raise ValueError('v5 unavailable/inactive diagnostic declares pixels')
                file = _v5_image(path, ordinal, name, info); descriptors.append((file, info, None))
            elif info.get('available') is True:
                raise ValueError('v5 available diagnostic lacks payload')
            if name in V5_FULL_CONTEXT_REFERENCE_ROLES:
                boundary = _v5_full_context_image(info, f, extent, origin, size)
                address = info['source_resource_address_process_local']
                if address in reference_addresses or reference_boundary is not None and not _v5_same_json(boundary, reference_boundary):
                    raise ValueError('v5 full-context reference heads alias or have different boundaries')
                reference_addresses.add(address); reference_boundary = boundary
        if names - set(by_name) != diagnostic_roles:
            raise ValueError('v5 diagnostic roles are incomplete')
        if requested:
            generation = reference_boundary['context_generation']
            evaluation = reference_boundary['reference_evaluation_id']
            primary = f['controls']['rr_dispatch']['context_generation']
            if reference_context is None and evaluation != 1 or reference_context is not None and \
                    (generation != reference_context or primary != primary_generation or evaluation != reference_evaluation+1):
                raise ValueError('v5 full-context diagnostic/primary context or evaluation lineage changed')
            queue = proof['queue_address_process_local']
            if reference_queue is not None and queue != reference_queue:
                raise ValueError('v5 full-context shared diagnostic resources require one actual submission queue')
            reference_queue = queue
            reference_context, reference_evaluation, primary_generation = generation, evaluation, primary
        for key in ('conversion_constants', 'floor_seed_constants', 'floor_filter_constants'):
            info = f.get(key)
            if not isinstance(info, dict):
                raise ValueError('v5 missing recorded constants descriptor: '+key)
            if key == 'conversion_constants':
                expected_bytes = 416
            else:
                if type(info.get('available')) is not bool:
                    raise ValueError('v5 constants availability must be boolean: '+key)
                if key == 'floor_seed_constants':
                    if _v5_int(info.get('abi_bytes'), 'floor seed ABI bytes') != 176 or \
                            info.get('stage') != 'pre_floor_seed_dispatch':
                        raise ValueError('v5 floor seed constants ABI/stage mismatch')
                    expected_bytes = 176
                else:
                    passes = _v5_int(info.get('pass_count'), 'floor filter pass count')
                    if _v5_int(info.get('record_bytes'), 'floor filter record bytes') != 32 or \
                            info.get('stage') != 'pre_floor_filter_dispatches' or \
                            passes not in ((3, 5) if info['available'] else (0,)):
                        raise ValueError('v5 floor filter constants ABI/stage/pass mismatch')
                    expected_bytes = 32*passes
                if not info['available']:
                    if any(k in info for k in ('file', 'bytes', 'sha256')):
                        raise ValueError('v5 unavailable constants declare payload: '+key)
                    continue
            file = _v5_payload_path(path, ordinal, key, info)
            if info['bytes'] != expected_bytes:
                raise ValueError('v5 recorded constants byte size mismatch: '+key)
            descriptors.append((file, info, None))
        observed = f.get('post_sr')
        if not isinstance(observed, dict) or type(observed.get('available')) is not bool:
            raise ValueError('v5 missing post-SR observation availability')
        post.append(observed)
        if mode == 'off':
            if observed['available'] or observed.get('file'):
                raise ValueError('v5 off post-SR mode declares pixels')
            continue
        if not observed['available']:
            raise ValueError('v5 requested post-SR observation is unavailable')
        file = _v5_image(path, ordinal, 'post_sr', observed)
        if observed['dxgi_format'] not in V5_POST_FORMATS or observed.get('mode') != mode or \
                observed.get('stage') != 'after_sr_before_rcas_output_scaling_overlay':
            raise ValueError('v5 post-SR format/mode/stage mismatch')
        if observed.get('evaluation_id') != f['evaluation_id'] or type(observed.get('evaluation_id')) is not int:
            raise ValueError('v5 post-SR evaluation identity mismatch')
        logical = _v5_pair(observed.get('logical_extent'), 'post-SR logical extent')
        if any(a > b for a, b in zip(logical, observed['source_extent'])):
            raise ValueError('v5 post-SR logical extent lies outside allocation')
        if mode == 'full_logical_output':
            wanted_origin, wanted_size = [0, 0], logical
        else:
            wanted_origin = [a*b//c for a, b, c in zip(origin, logical, extent)]
            end = [(a+b)*d//c + int(((a+b)*d) % c != 0)
                   for a, b, d, c in zip(origin, size, logical, extent)]
            wanted_size = [a-b for a, b in zip(end, wanted_origin)]
        if observed['crop_origin'] != wanted_origin or observed['extent'] != wanted_size:
            raise ValueError('v5 post-SR mapped logical ROI mismatch')
        sr_context = observed.get('context_id')
        if not isinstance(sr_context, str) or not re.fullmatch(r'SR-process-context-\d+-owner-\d+', sr_context):
            raise ValueError('v5 post-SR process context identity missing')
        if any(int(v) == 0 for v in re.findall(r'\d+', sr_context)):
            raise ValueError('v5 post-SR context/owner identity is zero')
        layout = (tuple(logical), observed['dxgi_format'])
        if post_context is not None and (sr_context != post_context or layout != post_layout):
            raise ValueError('v5 post-SR context/layout history changed')
        post_context, post_layout = sr_context, layout
        sr = observed.get('dispatch_controls')
        if not isinstance(sr, dict) or _v5_pair(sr.get('render_size'), 'SR render size') != extent or \
                _v5_pair(sr.get('upscale_size'), 'SR upscale size') != logical:
            raise ValueError('v5 post-SR dispatch/extent mismatch')
        for key in ('jitter', 'motion_vector_scale'):
            _v5_finite(sr.get(key), 'SR '+key, 2)
        for key in ('frame_time_delta', 'pre_exposure', 'camera_near', 'camera_far',
                    'camera_fov_vertical', 'view_space_to_meters', 'sharpness'):
            _v5_finite(sr.get(key), 'SR '+key)
        if sr['pre_exposure'] <= 0 or sr['frame_time_delta'] < 0 or sr['view_space_to_meters'] <= 0:
            raise ValueError('v5 post-SR dispatch scalar is invalid')
        if type(observed.get('reset')) is not bool or sr.get('reset') != observed['reset'] or \
                type(sr.get('reset')) is not bool or type(sr.get('enable_sharpening')) is not bool:
            raise ValueError('v5 post-SR reset/sharpening controls are ambiguous')
        for key in ('flags', 'create_flags'):
            _v5_int(sr.get(key), 'SR '+key)
        descriptors.append((file, observed, ordinal))
    if any(b['evaluation_id'] <= a['evaluation_id'] or b['recording_qpc'] <= a['recording_qpc']
           for a, b in zip(frames, frames[1:])):
        raise ValueError('v5 evaluation/timestamp lineage is not increasing')
    return descriptors, post


def inspect_capture(path, payload=False, limit=None):
    path = safe_path(path)
    manifest = json.loads((path / 'capture.json').read_text(encoding='utf-8'))
    if manifest.get('source') != 'live_game_gpu':
        raise ValueError('a live_game_gpu capture is required')
    schema = manifest.get('schema')
    if schema not in ('fsrd-game-trace-v3', 'fsrd-game-trace-v4', V5_SCHEMA):
        raise ValueError('unsupported GAME_TRACE schema version')
    v5 = schema == V5_SCHEMA
    frames = manifest['frames'][:limit]
    # A selected prefix limits payload reads, not validation of the original
    # published lineage. Private/pending rows are never part of this frame list.
    published = manifest['frames'] if v5 else frames
    if not frames or [f['ordinal'] for f in published] != list(range(len(published))):
        raise ValueError('capture must publish a nonempty contiguous ordinal prefix')
    if any(not f.get('gpu_submission_verified') or not f.get('gpu_completed') for f in published):
        raise ValueError('capture frame lacks verified GPU submission/completion')
    if any(f['context_id']!=published[0]['context_id'] for f in published) or any(
            b['native_frame_index']!=a['native_frame_index']+1 for a,b in zip(published,published[1:])):
        raise ValueError('capture context/native frame history is not contiguous')
    extent, roi = manifest['render_extent'], manifest['roi']
    if roi.get('space') != 'render_pixels_fixed':
        raise ValueError('unsupported capture ROI space')
    w, h = roi['extent']; x, y = roi['origin']
    if not (0 <= x and 0 <= y and 0 < w <= extent[0]-x and 0 < h <= extent[1]-y):
        raise ValueError('ROI lies outside render extent')
    v5_descriptors, post_metadata = _validate_v5_capture(path, manifest, published) if v5 else ([], [])
    if v5:
        v5_descriptors = [item for item in v5_descriptors
                          if int(item[1]['file'].split('/')[1]) < len(frames)]
        post_metadata = post_metadata[:len(frames)]
    controls = [f['controls'] for f in frames]
    views = np.asarray([c['view'] for c in controls], np.float32).reshape(-1, 4, 4)
    row = dict(capture=str(path), capture_uuid=manifest['capture_uuid'], schema=manifest['schema'],
               complete=manifest['complete'], frames=len(frames), render_extent=extent, roi=roi,
               full_frame=(roi['extent'] == extent and roi['origin'] == [0, 0]),
               original_reset_frames=[i for i, f in enumerate(frames) if f['reset']],
               elapsed_capture_seconds=(frames[-1]['recording_qpc']-frames[0]['recording_qpc']) / manifest['qpc_frequency'],
               maximum_camera_delta=float(np.max(np.abs([c['camera_delta'] for c in controls]))),
               maximum_rotation_change=float(np.max(np.abs(views[:, :3]-views[0, :3]))),
               settings=frames[0]['settings'], capture_manifest_sha256=digest(path / 'capture.json'),
               limitation='Fixed ROI; missing off-ROI history and neighbours. A reset at replay frame 0 starts fresh history.')
    if v5:
        row.update(region_mode=manifest.get('region_mode', 'square'),
                   target_frames=manifest.get('target_frames'), published_frames=len(published),
                   post_sr_mode=manifest['post_sr_mode'],
                   post_sr_is_pre_sr_reference=False,
                   immutable_cpu_snapshot_verified=True,
                   missing_floor_seed_constants=[f['ordinal'] for f in frames
                                                 if not f['floor_seed_constants']['available']],
                   post_sr_limitation='Optional after-SR observation before RCAS/output scaling/overlay; kept separate from the pre-SR captured comparator.')
        if row['region_mode'] == 'full_render':
            row['limitation'] = ('Full logical render extent is recorded; opaque initial RR state and pre-capture history '
                                 'remain unavailable. Replay frame 0 starts fresh history.')
        elif row['region_mode'] == 'full_height_strip':
            row['limitation'] = ('Full-height strip; horizontal/off-ROI spatial context, opaque initial RR state and '
                                 'pre-capture history remain unavailable. Replay frame 0 starts fresh history.')
        if manifest.get('full_context_reference_requested') is True:
            row.update(full_context_reference_requested=True,
                       full_context_reference_mode=V5_FULL_CONTEXT_REFERENCE_MODE,
                       full_context_reference_is_clean_truth=False,
                       full_context_reference_submission_queue_address_process_local=frames[0]['ticket_proof']['queue_address_process_local'],
                       full_context_reference_submission_queue_scope=('All published submission tickets use one actual queue; '
                           'primary/reference recorded DIRECT command-list identities match. Queue type follows the '
                           'command-list compatibility contract; runtime queue type is not separately recorded.'),
                       full_context_reference_limitation=('Separate full-native RESET-each RR heads, cropped only for '
                           'readback. Primary logical controls/history/composition selection are unchanged; extra '
                           'copies/transitions/dispatch may change scheduling, residency and fps; pixel identity is '
                           'not asserted. This diagnostic is not a solution or independent clean truth.'))
    if not payload:
        return row
    arrays = {}
    authenticated=[]
    layouts = dict(raw_color=('<f2', 4), raw_normals=('<f2', 4), raw_motion=('<f2', 4),
                   raw_depth=('<f4', 1), raw_specular_hit_distance=('<f4', 1),
                   raw_diffuse_albedo=('u1', 4), raw_specular_albedo=('u1', 4), raw_bias_mask=('u1', 1),
                   native_full1=('<f2', 4))
    supported_formats = dict(raw_color={10}, raw_normals={10}, raw_motion={10},
                             raw_depth={39, 40, 41}, raw_specular_hit_distance={39, 41},
                             raw_diffuse_albedo={28}, raw_specular_albedo={28}, raw_bias_mask={61},
                             native_full1={10})
    for name, (dtype, channels) in (() if v5 else layouts.items()):
        shape = (h, w, channels) if channels != 1 else (h, w)
        data=[]
        for f in frames:
            descriptions={e['name']:e for e in f['images']+f.get('diagnostics',[]) if e.get('file')}
            info=descriptions.get(name)
            if info is None:raise ValueError(f'capture frame {f["ordinal"]} lacks provenance for {name}')
            if info.get('dxgi_format') not in supported_formats[name]:
                raise ValueError(f'capture {name} DXGI format {info.get("dxgi_format")} needs reader support')
            if info.get('extent') != [w, h]:
                raise ValueError(f'capture {name} extent {info.get("extent")} needs reader support for this ROI')
            file=safe_path(path/info['file'])
            if not file.is_relative_to(path):raise ValueError('capture payload escapes capture directory')
            blob=file.read_bytes()
            if len(blob)!=info['bytes'] or hashlib.sha256(blob).hexdigest()!=info['sha256']:
                raise ValueError('capture payload hash/size mismatch: '+str(file))
            data.append(np.frombuffer(blob,dtype).reshape(shape))
            authenticated.append(dict(file=info['file'],sha256=info['sha256']))
        arrays[name]=np.stack(data)
    for f in frames:
        for key in (() if v5 else ('conversion_constants','floor_seed_constants')):
            info=f[key];file=safe_path(path/info['file'])
            if not file.is_relative_to(path):raise ValueError('capture constants escape capture directory')
            if file.stat().st_size!=info['bytes'] or digest(file)!=info['sha256']:
                raise ValueError('capture constant hash/size mismatch: '+str(file))
            authenticated.append(dict(file=info['file'],sha256=info['sha256']))
    if v5:
        already = {item['file'] for item in authenticated}
        post_words = []
        optional_roles = V5_FULL_CONTEXT_REFERENCE_ROLES if manifest.get('full_context_reference_requested') is True else set()
        image_words = {name: [None]*len(frames) for name in sorted(set(V5_IMAGE_FORMATS) | V5_DIAGNOSTICS | optional_roles)}
        image_descriptors = {name: [None]*len(frames) for name in image_words}
        for file, info, post_ordinal in v5_descriptors:
            if info['file'] in already:
                continue
            blob = file.read_bytes()
            if len(blob) != info['bytes'] or hashlib.sha256(blob).hexdigest() != info['sha256']:
                raise ValueError('v5 capture payload hash/size mismatch: '+str(file))
            authenticated.append(dict(file=info['file'], sha256=info['sha256']))
            already.add(info['file'])
            if 'dxgi_format' in info:
                _, _, dtype, words = V5_FORMAT_WORDS[info['dxgi_format']]
                pw, ph = info['extent']; shape = (ph, pw) if words == 1 else (ph, pw, words)
                original_words = np.frombuffer(blob, dtype).reshape(shape)
                if post_ordinal is not None:
                    post_words.append(original_words)
                else:
                    ordinal = int(info['file'].split('/')[1])
                    image_words[info['name']][ordinal] = original_words
                    image_descriptors[info['name']][ordinal] = info
        # Authentication accepts every recorded diagnostic format and crop.
        # The replay still has a narrower set of raw-input bindings; only expose
        # those decoded arrays when every frame fits that existing interface.
        for name, (dtype, channels) in layouts.items():
            if all(info is not None and info['dxgi_format'] in supported_formats[name] and
                   info['extent'] == [w, h] and _v5_replay_crop_aligned(info, [x, y], [w, h])
                   for info in image_descriptors[name]):
                shape = (h, w, channels) if channels != 1 else (h, w)
                arrays[name] = np.stack([words.view(dtype).reshape(shape) for words in image_words[name]])
        arrays['image_original_words'] = image_words
        arrays['post_sr_original_words'] = post_words
        arrays['post_sr_metadata'] = post_metadata
        arrays['schema'] = V5_SCHEMA
        arrays['missing_floor_seed_constants'] = row['missing_floor_seed_constants']
        if optional_roles:
            arrays['full_context_reference_metadata'] = [
                {info['name']: info for info in f['diagnostics'] if info['name'] in optional_roles} for f in frames]
    arrays['frame_metadata'] = frames
    arrays['extent'], arrays['roi'] = extent, roi
    arrays['capture'] = path
    raw_words = image_words['raw_color'] if v5 else arrays['raw_color']
    row['payload_unique_raw_frames'] = len({hashlib.sha256(a.tobytes()).hexdigest() for a in raw_words if a is not None})
    row['input_mode'] = 'genuine_captured_sequence'
    row['authenticated_payload_files']=authenticated
    return row, arrays


def require_replay_seed_controls(capture, floor):
    if capture.get('schema') == V5_SCHEMA and capture['missing_floor_seed_constants']:
        ordinal = capture['missing_floor_seed_constants'][0]
        variant = 'ON' if floor else 'OFF'
        raise ValueError(f'v5 capture frame {ordinal} lacks actual floor_seed_constants; '
                         f'Floor {variant} replay reruns Seed for canonical depth and requires its captured controls. '
                         'Payload inspection/authentication is supported; replay from captured intermediate buffers is a separate path.')


def require_replay_inputs(cap, floor):
    require_replay_seed_controls(cap, floor)
    if cap.get('schema') == V5_SCHEMA:
        for name in ('raw_color', 'raw_normals', 'raw_motion', 'raw_depth', 'raw_specular_hit_distance',
                     'raw_diffuse_albedo', 'raw_specular_albedo', 'raw_bias_mask', 'native_full1'):
            if name not in cap:
                raise ValueError(f'v5 captured {name} cannot feed this replay\'s aligned ROI/format inputs; '
                                 'payload inspection/authentication is supported')


class Constants:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.cache = {}

    def fields(self, shader):
        if shader not in self.cache:
            source = (self.directory / (shader+'.hlsl')).read_text(encoding='utf-8')
            body = mirror.brace_body(source, 'cbuffer '+MARKERS[shader])
            fields, size = mirror.hlsl_cbuffer_fields(body, shader)
            if mirror.errors:
                raise ValueError(mirror.errors)
            result = []
            for name, _, offset, length in fields:
                kind = re.search(r'\b(\w+)\s+'+re.escape(name)+r'\s*;', body)[1]
                fmt = 'I' if kind.startswith('uint') else 'i' if kind.startswith('int') else 'f'
                result.append((name, offset, length, fmt))
            self.cache[shader] = result, size
        return self.cache[shader]

    def unpack(self, shader, blob):
        fields, size = self.fields(shader)
        if len(blob) < size:
            raise ValueError(f'captured {shader} constants {len(blob)} bytes smaller than ABI {size}')
        return {name: list(struct.unpack_from('<'+fmt*(length//4), blob, offset))
                for name, offset, length, fmt in fields}

    def pack(self, shader, values):
        fields, size = self.fields(shader)
        blob = bytearray(size)
        for name, offset, length, fmt in fields:
            if name not in values:
                continue
            value = values[name]
            value = [value] if np.isscalar(value) else np.asarray(value).ravel().tolist()
            if len(value)*4 != length:
                raise ValueError(f'constant {name} byte count mismatch')
            struct.pack_into('<'+fmt*len(value), blob, offset, *value)
        return blob


class Gpu:
    def __init__(self, work, shaders, executable):
        self.work = safe_path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.shaders, self.executable = Path(shaders), Path(executable)
        self.constants, self.records = Constants(shaders), []
        self.stderr = (self.work/'gpu_stderr.log').open('w', encoding='utf-8')
        self.worker = subprocess.Popen([str(executable), '--server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=self.stderr, text=True, bufsize=1)

    def dispatch(self, shader, values, inputs, outputs, size, schema=None):
        w, h = size
        cb = self.work/'constants.bin'
        cb.write_bytes(self.constants.pack(schema or shader, values))
        lines = [f'"{(self.shaders/(shader+"_Shader.cso")).as_posix()}" "{cb.as_posix()}" '
                 f'{w} {h} {len(inputs)} {len(outputs)} 1']
        types = {10: ('<f2', 4), 41: ('<f4', 1), 28: ('u1', 4), 24: ('<u4', 1),
                 34: ('<f2', 2), 16: ('<f4', 2), 61: ('u1', 1), 3: ('<u4', 4)}
        for index, (value, fmt) in enumerate(inputs):
            array = np.asarray(value)
            dtype, channels = types[fmt]
            expected = (h, w) + (() if channels == 1 else (channels,))
            if array.shape != expected:
                raise ValueError(f'{shader} input {index} shape {array.shape} expected {expected}')
            path = self.work/f'in{index}.bin'
            np.ascontiguousarray(array, dtype=dtype).tofile(path)
            lines.append(f'"{path.as_posix()}" {w} {h} {fmt}')
        for index, fmt in enumerate(outputs):
            lines.append(f'"{(self.work / ("out"+str(index)+".bin")).as_posix()}" {w} {h} {fmt}')
        job = self.work/'job.txt'
        job.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        started = time.monotonic()
        self.worker.stdin.write(str(job)+'\n'); self.worker.stdin.flush()
        log = []
        for line in self.worker.stdout:
            if line.startswith('job_complete='):
                code = int(line.split('=', 1)[1]); break
            log.append(line)
        else:
            raise RuntimeError('GPU worker exited; inspect '+str(self.work/'gpu_stderr.log'))
        log = ''.join(log)
        if code or not re.search(r'validation_errors=0 validation_warnings=0\b', log):
            raise RuntimeError(f'{shader} GPU job failed\n{log}')
        self.records.append(dict(shader=shader, shader_sha256=digest(self.shaders/(shader+'_Shader.cso')),
                                 seconds=time.monotonic()-started, log=log, constants_sha256=digest(cb),
                                 applied_constants=self.constants.unpack(schema or shader,cb.read_bytes()),
                                 formats=dict(inputs=[fmt for _, fmt in inputs], outputs=outputs)))
        result = []
        for index, fmt in enumerate(outputs):
            dtype, channels = types[fmt]
            shape = (h, w) + (() if channels == 1 else (channels,))
            result.append(np.fromfile(self.work/f'out{index}.bin', dtype).reshape(shape).copy())
        return result

    def close(self):
        self.worker.stdin.close()
        self.worker.wait(timeout=30)
        self.stderr.close()
        (self.work/'gpu_dispatches.json').write_text(json.dumps(self.records, indent=2)+'\n')


def floor_step_sequence(mode='full'):
    if mode == 'full':return (1,2,4,8,16)
    if mode == 'fast':return (1,2,16)
    raise ValueError('Floor steps must be full or fast')


def floor_producer_profile(floor=True, floor_steps='full'):
    steps=list(floor_step_sequence(floor_steps))
    return dict(floor_steps_mode=floor_steps,configured_floor_pass_steps=steps,
        floor_pass_steps=steps if floor else [],floor_enabled=bool(floor),
        floor_pass_policy='Explicit '+floor_steps+' Floor override, not inferred from capture settings')


def preprocessing_cache_identity(provenance, hashes, floor, bleed, floor_steps='full'):
    return dict(capture_manifest_sha256=provenance['capture_manifest_sha256'],frames=provenance['frames'],
        floor=int(floor),bleed=int(bleed),shader_hashes=hashes,floor_steps_mode=floor_steps,
        floor_pass_steps=floor_producer_profile(floor,floor_steps)['floor_pass_steps'])


def preprocessing_cache_matches(recorded, expected):
    # Original authenticated caches predate the choice and explicitly used full5.
    # Preserve them only for full; absent or partial metadata never grants fast.
    keys=('floor_steps_mode','floor_pass_steps')
    if not any(k in recorded for k in keys):
        return expected['floor_steps_mode']=='full' and recorded=={k:v for k,v in expected.items() if k not in keys}
    return all(k in recorded for k in keys) and recorded==expected


def preprocess(cap, gpu, floor, bleed, recovery_mask=3, floor_steps='full'):
    require_replay_inputs(cap, floor)
    steps=floor_step_sequence(floor_steps)
    w, h = cap['roi']['extent']; size = (w, h)
    crop = camera_crop(cap['extent'], cap['roi'])
    zero = np.zeros((h, w, 4), np.float16); scalar = np.zeros((h, w), np.float32)
    records = []
    for index, metadata in enumerate(cap['frame_metadata']):
        frame = cap['capture']/'frames'/str(metadata['ordinal'])
        values = gpu.constants.unpack('FSRDFloorSeed', (frame/'floor_seed_constants.bin').read_bytes())
        if int(values['Flags'][0]) & ~3:
            raise ValueError('capture Seed needs a title depth resource this replay does not provide')
        inv = np.asarray(values['InvProjMatrix']).reshape(4, 4).T
        values['InvProjMatrix'] = (inv@crop).astype(np.float32).T.ravel()
        values.update(RenderSize=[w, h, 1/w, 1/h], FloorEnabled=int(floor),
                      InputBase=[0]*4, NormalBase=[0]*2, TitleDepthBase=[0]*2, AlbedoBase=[0]*2)
        seed, depth, gradient, reference, model = gpu.dispatch('FSRDFloorSeed', values,
            [(cap['raw_color'][index],10), (cap['raw_normals'][index],10), (cap['raw_depth'][index],41),
             (scalar,41), (cap['raw_diffuse_albedo'][index],28)], [10,41,10,10,10], size)
        base = seed
        if floor:
            for step in steps:
                base, model = gpu.dispatch('FSRDFloor', dict(DstTexSize=[w,h,1/w,1/h],StepSize=step,AlbedoBase=[0,0]),
                    [(base,10),(depth,41),(gradient,10),(cap['raw_diffuse_albedo'][index],28),
                     (reference,10),(model,10)], [10,10],size)
        values = gpu.constants.unpack('FSRDInputConv', (frame/'conversion_constants.bin').read_bytes())
        supported_flags=(1<<1)|(1<<2)|(1<<3)|(1<<4)|(1<<5)|(1<<7)|(1<<8)|(1<<11)|(1<<15)
        original_flags=int(values['Flags'][0])
        if original_flags & ~supported_flags:
            raise ValueError(f'capture conversion flags {original_flags:#x} require unsupported optional/routing inputs')
        if not original_flags & (1<<2) or not original_flags & (1<<5):
            raise ValueError('replay requires packed title roughness and an indirect-specular main signal')
        inv = np.asarray(values['InvProjMatrix']).reshape(4,4).T
        values['InvProjMatrix'] = (inv@crop).astype(np.float32).T.ravel()
        transform = values['MotionTransform']; transform[0] *= cap['extent'][0]/w; transform[1] *= cap['extent'][1]/h
        # Seed now owns canonical signed-linear depth, even though these older
        # captures stored the pre-canonical conversion flag (hardware depth).
        flags = (original_flags & ~(1<<7)) | (1<<1)
        if floor: flags |= 1<<7
        if bleed: flags |= 1<<28
        if index==0 or metadata['reset']:
            values['PrevViewMatrix']=metadata['controls']['view']
            values['JitterOffsets'][2:]=values['JitterOffsets'][:2]
        values.update(DstTexSize=[w,h,1/w,1/h], MotionInputSize=[w,h,1/w,1/h], MotionTransform=transform,
                      Flags=flags, RecoveryMask=recovery_mask, FloorDetailPreservation=1,
                      SpecularAlbedoDemodulation=1, DiffuseAlbedoModulation=1,
                      **{f'InputBase{i}':[0]*4 for i in range(6)})
        packed = gpu.dispatch('FSRDInputConv', values,
            [(cap['raw_color'][index],10),(depth,41),(cap['raw_motion'][index],10),(cap['raw_normals'][index],10),
             (scalar,41),(cap['raw_specular_hit_distance'][index],41),(cap['raw_diffuse_albedo'][index],28),
             (cap['raw_specular_albedo'][index],28),(cap['raw_bias_mask'][index],61),(base,10),(zero,10),
             (zero,10),(zero,10),(zero,10),(scalar,41),(scalar,41),(reference,10),(model,10)],
            [10,10,10,24,28,28,10,10,10,10],size)
        records.append([seed,base,depth,reference,model]+packed)
        if index%16==0: print(f'preprocess floor={int(floor)} bleed={int(bleed)} frame={index}/{len(cap["frame_metadata"])}',flush=True)
    names = ['seed','floor','depth','reference','model','specular','diffuse','motion','normals',
             'specular_albedo','diffuse_albedo','skip','detail','direct_specular','indirect_diffuse']
    return {name:np.stack([r[index] for r in records]) for index,name in enumerate(names)}


def replay(cap, packed, folder, executable, bleed, reset_frames):
    controls = [f['controls'] for f in cap['frame_metadata']]
    crop = camera_crop(cap['extent'], cap['roi'])
    projections = np.asarray([c['projection'] for c in controls],np.float64).reshape(-1,4,4)@np.linalg.inv(crop).T
    resets = np.asarray([int(f['reset']) for f in cap['frame_metadata']],np.uint32)
    for frame in reset_frames:
        if not 0 <= frame < len(resets): raise ValueError('injected reset frame outside capture')
        resets[frame]=1
    resets[0]=1
    camera_deltas=np.asarray([c['camera_delta'] for c in controls],np.float32)
    camera_deltas[resets!=0]=0
    scales = np.asarray([c['motion_vector_scale']+[1] if len(c['motion_vector_scale'])==2 else c['motion_vector_scale'] for c in controls])
    # Conversion emits canonical ROI UV motion, so the captured RR scale is kept.
    inputs = dict(diffuse=packed['diffuse'],specular=packed['specular'],depth=packed['depth'],motion=packed['motion'],
                  normals=packed['normals'],diffuse_albedo=packed['diffuse_albedo'],specular_albedo=packed['specular_albedo'],
                  resets=resets,jitters=np.asarray([c['jitter'] for c in controls]),
                  view=np.asarray([c['view'] for c in controls]).reshape(-1,4,4),projection=projections,
                  depth_bounds=np.asarray([c['depth_bounds'] for c in controls]),
                  camera_position_delta=camera_deltas,motion_vector_scale=scales)
    if bleed:
        inputs.update(direct_specular=packed['direct_specular'],indirect_diffuse=packed['indirect_diffuse'])
    return native.run_rr(folder,**inputs,executable=executable)


def compose(cap, packed, rr, gpu, bleed, full_witness, recovery=1, floor=True,
            composition_shader='FSRDOutputComp', cached_trust=None,
            recovery_mask=3, spatial_temporal_mask=2):
    w,h=cap['roi']['extent']; size=(w,h); n=len(packed['depth'])
    zero=np.zeros((h,w,4),np.float16); uintzero=np.zeros((h,w,4),np.uint32)
    history=np.full((h,w,4),-1,np.float16); history_metadata=uintzero.copy()
    history_valid=False
    if cached_trust is not None:
        cached_trust=np.asarray(cached_trust)
        if cached_trust.shape!=(n,h,w,2) or not np.isfinite(cached_trust).all():
            raise ValueError('cached trust must be finite [frames,height,width,2]')
    reset_frames=set(rr['metadata']['reset_frames'])
    if not 0<=recovery<=1 or recovery_mask&~7 or spatial_temporal_mask&~recovery_mask:
        raise ValueError('invalid recovery strength/selection/noise-method mask')
    detail_preservation=float(recovery) if floor else 0.0
    write_history=bool(detail_preservation>0 and recovery_mask)
    out=[]; votes=[]
    for frame in range(n):
        trust=np.zeros((h,w,2),np.float16)
        if bleed and cached_trust is not None:
            trust=cached_trust[frame].astype(np.float16)
        elif bleed:
            trust=gpu.dispatch('FSRDAlbedoTrustEvidence',dict(DstTexSize=[w,h,1/w,1/h],StepSize=0,
                Flags=(1<<1) if full_witness else 0,DemodDivisorFloor=.008),
                [(rr['direct_specular'][frame],10),(rr['diffuse'][frame],10),(packed['specular_albedo'][frame],28),
                 (packed['diffuse_albedo'][frame],28),(packed['skip'][frame],10),(packed['depth'][frame],41),
                 (packed['normals'][frame],24),(packed['direct_specular'][frame],10),(rr['indirect_diffuse'][frame],10),
                 (packed['specular'][frame],10),(packed['diffuse'][frame],10)], [34],size)[0]
            for step in (1,2,4,8,16,32):
                trust=gpu.dispatch('FSRDAlbedoTrustPropagate',dict(DstTexSize=[w,h,1/w,1/h],StepSize=step),
                    [(trust,34),(packed['depth'][frame],41),(packed['normals'][frame],24)],[34],size)[0]
        flags=(1<<3) | ((1<<8) if bleed else 0)
        reset=frame in reset_frames
        current_jitter=np.asarray(cap['frame_metadata'][frame]['controls']['jitter'],np.float32)
        previous_jitter=(current_jitter if reset or frame==0 else
                         np.asarray(cap['frame_metadata'][frame-1]['controls']['jitter'],np.float32))
        values=dict(DstTexSize=[w,h,1/w,1/h],Flags=flags,DetailPreservation=detail_preservation,
                    RecoveryMask=recovery_mask,SpatialTemporalMask=spatial_temporal_mask,
                    FloorHandoverAnchorClamp=4,FloorHandoverCorrelationMix=1,SourceUvScale=[1,1],SourceUvOffset=[0,0],
                    HistoryValid=int(write_history and history_valid and not reset),
                    HistoryJitterDelta=previous_jitter-current_jitter,WriteHistory=int(write_history),
                    SpecularAlbedoDemodulation=1,DiffuseAlbedoModulation=1,LumaRecovery=1,ChromaRecovery=1,
                    UnsupportedAlbedoRecovery=int(bleed),DemodDivisorFloor=.008)
        image,new_history,new_metadata=gpu.dispatch(composition_shader,values,
            [(rr['specular'][frame],10),(packed['specular_albedo'][frame],28),(rr['diffuse'][frame],10),
             (packed['diffuse_albedo'][frame],28),(packed['skip'][frame],10),(packed['normals'][frame],24),
             (packed['detail'][frame],10),(packed['depth'][frame],41),(packed['motion'][frame],10),(history,10),(history_metadata,3),
             (rr['direct_specular'][frame] if bleed else zero,10),(packed['direct_specular'][frame],10),(trust,34),
             (rr['indirect_diffuse'][frame] if bleed else zero,10),(packed['specular'][frame],10),
             (packed['diffuse'][frame],10)],[10,10,3],size,schema='FSRDOutputComp')
        if write_history:
            history,history_metadata=new_history,new_metadata
            history_valid=True
        out.append(image);votes.append(trust)
    return np.stack(out),np.stack(votes)


def luminance(a):
    return np.asarray(a,np.float32)[...,:3]@np.array([.2126,.7152,.0722],np.float32)


def box(a,r=2):
    p=np.pad(np.asarray(a,np.float64),r,mode='edge')
    c=np.pad(p.cumsum(0).cumsum(1),((1,0),(1,0)))
    k=2*r+1
    return (c[k:,k:]-c[:-k,k:]-c[k:,:-k]+c[:-k,:-k])/(k*k)


def composition_profile(floor=True,recovery=1,recovery_mask=3,spatial_temporal_mask=2,floor_steps='full'):
    producer=floor_producer_profile(floor,floor_steps)
    return dict(provenance='Explicit current-production-default recovery override; capture settings describe comparator, not this profile.',
        DetailPreservation=float(recovery) if floor else 0.,RecoveryMask=recovery_mask,
        SpatialTemporalMask=spatial_temporal_mask,LumaRecovery=1.,ChromaRecovery=1.,
        shader='Generic mixed flat Full Anchor / specular Light; diffuse disabled',
        floor_pass_steps=producer['floor_pass_steps'],floor_steps_mode=floor_steps,
        floor_pass_policy=producer['floor_pass_policy'])


def recovery_eligibility(packed,mask=3,method=2):
    if 'specular_albedo' not in packed:return dict(available=False)
    classes=(packed['normals']>>30)&3
    spec=packed['specular_albedo'][...,:3].astype(np.float32)
    diffuse=packed['diffuse_albedo'][...,:3].astype(np.float32)
    material=spec+diffuse;share=spec/np.maximum(material,1e-4)
    flat=((classes==1)&bool(mask&1));valid=material>0
    selected_spec=(~flat)&bool(mask&2)&((share*valid)>0).any(-1)
    selected_diffuse=(~flat)&bool(mask&4)&(((1-share)*valid)>0).any(-1)
    return dict(available=True,normal_class_fractions={str(i):float((classes==i).mean()) for i in range(4)},
        selected_flat_fraction=float(flat.mean()),selected_specular_fraction=float(selected_spec.mean()),
        selected_diffuse_fraction=float(selected_diffuse.mean()),
        selected_any_lobe_fraction=float((flat|selected_spec|selected_diffuse).mean()),
        flat_filtered=bool(method&1),specular_filtered=bool(method&2),diffuse_filtered=bool(method&4),
        limitation='Selection eligibility only; it does not prove a nonzero recovery correction.')


def measure(cap,packed,image,trust,reset_frames,recovery_mask=3,spatial_temporal_mask=2):
    raw=np.asarray(cap['raw_color'],np.float32)[...,:3]
    proxy=raw[len(raw)//2:].mean(0); target=luminance(proxy)
    mask=np.zeros(target.shape,bool);mask[8:-8,8:-8]=True
    luma=luminance(image); denom=np.maximum(target,.01)
    rgb=np.asarray(image,np.float32)[...,:3]
    chroma=rgb/np.maximum(rgb.sum(-1,keepdims=True),1e-5)
    detail=target-box(target); detail_energy=np.mean(detail[mask]**2)
    model=packed['model'].astype(np.float32); ref=packed['reference'].astype(np.float32)
    noisy=(model[...,3]>=.5)&(model[...,3]<2)&(ref[...,3]>=0)
    represented=(model[...,:3]>-99)
    all_channels=noisy&represented.all(-1);partial=noisy&represented.any(-1)&~represented.all(-1)
    residual_zero=(packed['specular'][...,:3]==0).all(-1)&(packed['diffuse'][...,:3]==0).all(-1)
    mass=trust[...,1].astype(np.float32)
    ratio=np.divide(trust[...,0].astype(np.float32),np.maximum(mass,1e-5))
    windows={}
    target_mean=max(float(target[mask].mean()),1e-5)
    raw_luma=luminance(raw)

    def window(start,end):
        mean=luma[start:end].mean(0)
        high=mean-box(mean)
        return dict(temporal_luma_sd_relative=float(np.mean(luma[start:end].std(0)[mask]/denom[mask])),
            global_temporal_luma_sd_relative=float(luma[start:end].std(0)[mask].mean()/target_mean),
            raw_temporal_luma_sd_relative=float(raw_luma[start:end].std(0)[mask].mean()/target_mean),
            temporal_noise_remaining_ratio=float(luma[start:end].std(0)[mask].mean()/max(raw_luma[start:end].std(0)[mask].mean(),1e-8)),
            consecutive_luma_delta_rms_relative=float(np.sqrt(np.mean(((np.diff(luma[start:end],axis=0)/denom)[:,mask])**2))) if end-start>1 else None,
            mean_luma_proxy_bias_relative=float(np.mean((mean[mask]-target[mask])/denom[mask])),
            texture_proxy_projection=float(np.mean(high[mask]*detail[mask])/max(detail_energy,1e-12)),
            severe_dark_tail_fraction=float(np.mean(luma[start:end][:,mask] < .25*target[mask])),
            temporal_chroma_sd_mean=float(chroma[start:end].std(0)[mask].mean()),
            trust_ratio_mean=float(ratio[start:end][:,mask].mean()))

    for start,end in ((0,4),(4,16),(16,32),(32,64),(64,len(raw))):
        if start>=len(raw):continue
        end=min(end,len(raw)); windows[f'{start}:{end}']=window(start,end)
    reset_indices=sorted({0,*reset_frames,*[i for i,f in enumerate(cap['frame_metadata']) if f['reset']]})
    reset_windows={}
    for ordinal,reset in enumerate(reset_indices):
        end_reset=reset_indices[ordinal+1] if ordinal+1<len(reset_indices) else len(raw)
        measurements={}
        for first,last in ((0,1),(1,4),(4,8),(8,16),(16,32)):
            start,end=reset+first,min(reset+last,end_reset)
            if start<end:measurements[f'+{first}:+{end-reset}']=dict(frames=[start,end],**window(start,end))
        reset_windows[str(reset)]=measurements
    relative_error=(luma-target)/denom
    frame_delta=np.sqrt(np.mean(((np.diff(luma,axis=0)/denom)[:,mask])**2,axis=1))
    reference_by_model={}
    for name,selection in (('all_rgb',all_channels),('partial_rgb',partial)):
        if selection.any():reference_by_model[name]=np.quantile(ref[...,3][selection],[0,.1,.5,.9,.99,1]).tolist()
    motion_pixels=np.linalg.norm(packed['motion'][...,:2].astype(np.float32)*np.array([target.shape[1],target.shape[0]]),axis=-1)
    return dict(metric_reference='Late raw temporal mean: stationary-scene proxy, not clean truth; crop borders excluded by 8px.',
        resets=dict(captured=[i for i,f in enumerate(cap['frame_metadata']) if f['reset']],replay_start=[0],injected=reset_frames),
        windows=windows,reset_relative_windows=reset_windows,
        recovery_lobe_eligibility=recovery_eligibility(packed,recovery_mask,spatial_temporal_mask),
        per_frame_proxy_metrics=dict(mean_luma_bias_relative=relative_error[:,mask].mean(1).tolist(),
            luma_proxy_rmse_relative=np.sqrt(np.mean(relative_error[:,mask]**2,axis=1)).tolist(),
            severe_dark_tail_fraction=(luma[:,mask]<.25*target[mask]).mean(1).tolist(),
            consecutive_luma_delta_rms_relative=[None,*frame_delta.tolist()]),
        all_channel_noise_model_fraction=float(all_channels.mean()),partial_channel_noise_model_fraction=float(partial.mean()),
        zero_main_residual_fraction_on_all_channel_models=float(residual_zero[all_channels].mean()) if all_channels.any() else None,
        reference_sigma_quantiles=np.quantile(ref[...,3],[0,.1,.5,.9,.99,1]).tolist(),
        reference_sigma_quantiles_by_model=reference_by_model,
        captured_motion_pixel_quantiles=np.quantile(motion_pixels,[0,.5,.9,.99,1]).tolist(),
        reference_bypassed_fraction=float((ref[...,3]<0).mean()),
        trust_nonzero_mass_fraction=float((mass>0).mean()),trust_nonfinite_fraction=float((~np.isfinite(trust)).mean()),
        output_nonfinite_fraction=float((~np.isfinite(image)).mean()),
        authentic_camera_turn_or_disocclusion_verified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--inventory',type=Path);source.add_argument('--capture',type=Path)
    parser.add_argument('--shader-dir',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frames',type=int,default=128)
    parser.add_argument('--cases',nargs='+',default=['0:0','0:1','1:0','1:1'])
    parser.add_argument('--reset-frame',type=int,action='append',default=[])
    parser.add_argument('--floor-steps',choices=('full','fast'),default='full',help='Floor producer: full1/2/4/8/16 or runtime Fast1/2/16; default preserves full5 replays')
    parser.add_argument('--full-witness',action='store_true',help='Candidate bit1; baseline must omit it')
    parser.add_argument('--packed-dir',type=Path,help='Reuse authenticated preprocessing from a prior run, useful for reset-only probes')
    parser.add_argument('--build-only',action='store_true')
    args=parser.parse_args()
    output=safe_path(args.output);output.mkdir(parents=True,exist_ok=True)
    if args.inventory:
        root=safe_path(args.inventory)
        # Do not enumerate or recurse inside the reserved holdout.
        rows=[inspect_capture(p) for p in sorted(root.iterdir())
              if p.name.lower()!='reserve_data' and p.is_dir() and (p/'capture.json').is_file()]
        (output/'capture_inventory.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(json.dumps([{k:r[k] for k in ('capture_uuid','frames','full_frame','original_reset_frames')} for r in rows],indent=2))
        return
    if args.shader_dir is None:parser.error('--shader-dir required for replay')
    shaders=safe_path(args.shader_dir)
    cases=[]
    if not args.build_only:
        for case in args.cases:
            floor,bleed=[int(v) for v in case.split(':')]
            if floor not in (0,1) or bleed not in (0,1):raise ValueError('cases must be Floor:Bleed binary pairs')
            cases.append((case,floor,bleed))
        # Missing actual Seed controls are a replay limitation, not an invalid
        # capture. Reject that replay before decoding arrays, builds or GPU work.
        provenance=inspect_capture(args.capture,False,args.frames)
        require_replay_seed_controls(provenance,any(floor for _,floor,_ in cases))
        provenance,cap=inspect_capture(args.capture,True,args.frames)
        require_replay_inputs(cap,any(floor for _,floor,_ in cases))
    os.environ.setdefault('FSRD_VS_ROOT','F:/VisualStudio')
    gpu_exe=output/'build/fsrd_gpu_runner.exe';gpu_exe.parent.mkdir(parents=True,exist_ok=True)
    compile_cpp(HERE/'fsrd_gpu_runner.cpp',gpu_exe,('d3d12.lib','dxgi.lib'))
    rr_exe=native.build_native(output/'build/fsrd_floor_rr_replay.exe')
    if args.build_only:
        print('build_only=passed');return
    provenance['replay_producer_configuration']=floor_producer_profile(True,args.floor_steps)
    (output/'capture_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    shader_hashes={p.name:digest(p) for p in shaders.iterdir() if p.suffix in ('.cso','.hlsl','.hlsli')}
    (output/'shader_provenance.json').write_text(json.dumps(shader_hashes,indent=2)+'\n')
    result={}
    for case,floor,bleed in cases:
        folder=output/f'floor{floor}_bleed{bleed}';folder.mkdir(exist_ok=True)
        cache_root=safe_path(args.packed_dir) if args.packed_dir else output
        cache=cache_root/f'packed_floor{floor}_bleed{bleed}.npz'
        cache_identity=preprocessing_cache_identity(provenance,shader_hashes,floor,bleed,args.floor_steps)
        cache_manifest=cache.with_suffix('.json')
        if cache.is_file():
            identity=json.loads(cache_manifest.read_text()) if cache_manifest.is_file() else {}
            cache_sha256=identity.pop('npz_sha256',None)
            if not preprocessing_cache_matches(identity,cache_identity) or cache_sha256!=digest(cache):
                raise ValueError('preprocessing cache identity differs or lacks a manifest: '+str(cache))
            with np.load(cache,allow_pickle=False) as archive:packed={k:archive[k] for k in archive.files}
        else:
            gpu=Gpu(output/f'preprocess_floor{floor}_bleed{bleed}',shaders,gpu_exe)
            try:packed=preprocess(cap,gpu,bool(floor),bool(bleed),floor_steps=args.floor_steps)
            finally:gpu.close()
            np.savez_compressed(cache,**packed)
            cache_manifest.write_text(json.dumps(dict(cache_identity,npz_sha256=digest(cache)),indent=2)+'\n')
        # A capture normally begins inside an existing game history. Replay and
        # injected resets must instead use current view/jitter as previous inputs.
        # Reconvert only those frames; the authenticated ordinary-frame cache is
        # reusable between no-reset and reset probes without losing provenance.
        patch_frames=sorted({0,*args.reset_frame,*provenance['original_reset_frames']})
        gpu=Gpu(folder/'reset_control_preprocess',shaders,gpu_exe)
        try:
            for frame in patch_frames:
                if not 0<=frame<provenance['frames']:raise ValueError('reset frame outside sequence')
                single={k:(v[frame:frame+1] if isinstance(v,np.ndarray) else v) for k,v in cap.items()}
                single['frame_metadata']=[cap['frame_metadata'][frame]]
                corrected=preprocess(single,gpu,bool(floor),bool(bleed),floor_steps=args.floor_steps)
                for name,array in corrected.items():packed[name][frame]=array[0]
        finally:gpu.close()
        (folder/'reset_control_patch.json').write_text(json.dumps(dict(frames=patch_frames,
            producer=floor_producer_profile(bool(floor),args.floor_steps),
            policy='current view/jitter as previous on reset; native cameraPositionDelta=0; composition history invalid'),indent=2)+'\n')
        rr=replay(cap,packed,folder/'rr',rr_exe,bool(bleed),args.reset_frame)
        gpu=Gpu(folder/'composition',shaders,gpu_exe)
        try:image,trust=compose(cap,packed,rr,gpu,bool(bleed),args.full_witness,floor=bool(floor))
        finally:gpu.close()
        np.savez_compressed(folder/'final.npz',image=image,trust=trust)
        metrics=measure(cap,packed,image,trust,args.reset_frame)
        metrics['composition_history']=dict(enabled=bool(floor),write_history=bool(floor),
                                             invalidated_frames=patch_frames,successful_frame_commit=True)
        metrics['composition_profile']=composition_profile(bool(floor),floor_steps=args.floor_steps)
        metrics['floor_producer']=floor_producer_profile(bool(floor),args.floor_steps)
        metrics['native_metadata']=str(folder/'rr/metadata.json')
        (folder/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
        result[case]=metrics
        (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(case=case,native_dispatches=rr['metadata']['counters'],metrics=metrics),indent=2),flush=True)
    if shader_hashes != {p.name:digest(p) for p in shaders.iterdir() if p.suffix in ('.cso','.hlsl','.hlsli')}:
        raise RuntimeError('shader snapshot changed during replay')


if __name__=='__main__':
    main()
