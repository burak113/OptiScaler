"""Fixture-only native operand encoder for the independent world-surface oracle.

The expected previous surface depth is obtained from world/object/camera poses.
The title's attested screen-space expression is then INVERTED to encode native
MV.z, with an intentionally nonidentity previous basis. This is a synthetic native
packet, never a claim about unpublished game constants. Original oracle files
are immutable; the excluded title-binding probe border has a separate manifest.
"""
from pathlib import Path
import json
import os
import struct
import numpy as np
from fsrd_nrd_motion_quality_oracle import load, put, sha


def prepare(inputs, destination):
    inputs, destination = Path(inputs), Path(destination)
    original = json.loads((inputs / 'sequence.json').read_text(encoding='utf-8'))
    destination.mkdir(parents=True, exist_ok=True)
    width, height = original['width'], original['height']
    y, x = np.mgrid[:height, :width]
    interior = (x >= 16) & (x < width - 16) & (y >= 16) & (y < height - 16)
    uv = np.stack((x + .5, y + .5), axis=-1) / (width, height)
    frames, previous_depth, previous_jitter = [], None, None
    for index, frame in enumerate(original['frames']):
        folder = destination / frame['directory']
        folder.mkdir(exist_ok=True)
        data = {name: load(inputs / frame['directory'], record) for name, record in frame['payloads'].items()}
        p = np.asarray(frame['view'], np.float64)
        previous = original['frames'][max(0, index - 1)]
        previous_view = np.asarray(previous['view'], np.float64)
        previous_projection = np.asarray(previous['projection'], np.float64)
        raw_z = -data['depth'].astype(np.float64)
        raw_z[~interior] = 5.
        # General affine native basis, not an identity-basis shortcut. The native
        # view row is deliberately nonorthogonal to the previous ray basis.
        right = previous_view[0, :3] / previous_projection[0, 0]
        up = previous_view[1, :3] / previous_projection[1, 1]
        forward = -2. * previous_view[2, :3]
        row = -previous_view[2, :3] + .13 * previous_view[0, :3] - .07 * previous_view[1, :3]
        delta = np.array([.025, -.018, .04])
        row_w = .19
        raw_motion = np.zeros((height, width, 4), '<f2')
        raw_motion[..., :2] = data['canonical_motion']
        previous_native_uv = uv + raw_motion[..., :2].astype(np.float64)
        n = 2 * previous_native_uv - 1
        basis = n[..., 0, None] * right - n[..., 1, None] * up + forward
        coefficient = basis @ row
        offset = float(delta @ row + row_w)
        expected_positive = -data['previous_surface_depth'].astype(np.float64)
        previous_input_z = (expected_positive - offset) / coefficient
        scale_z = -.5
        raw_motion[..., 2] = ((previous_input_z - raw_z) / scale_z).astype('<f2')
        raw_motion[~interior] = 0
        expected_surface = data['previous_surface_depth'].astype(np.float64) + raw_z
        current_world = data['current_world'].astype(np.float64)
        previous_camera = np.asarray(previous['camera'])
        camera_b = ((current_world - previous_camera) @ previous_view[2, :3]) + raw_z
        fallback = index == 24
        expected = camera_b if fallback else expected_surface
        if index == 0:
            expected.fill(0)
        # Camera-only default: the current surface's previous-camera depth. The
        # first frame has no coherent previous camera row and stays exactly 0;
        # the native fallback index is the same static-surface estimate.
        expected_camera = camera_b.copy()
        if index == 0:
            expected_camera.fill(0)
        # Native half-MV quantization has a known bounded effect on decoded B.
        # Check the encoder against the independent unquantized geometry NOW.
        decoded = (raw_z - (coefficient * (raw_z + raw_motion[..., 2].astype(np.float64) * scale_z) + offset))
        if np.max(np.abs(decoded[interior] - expected_surface[interior])) >= .005:
            raise AssertionError('encoded native half Z exceeds the existing005 world-depth tolerance')
        b6 = bytearray(1536)
        def floats(register, values):
            for component, value in enumerate(values):
                struct.pack_into('<f', b6, register * 16 + component * 4, float(value))
        # Unused screen-branch clip coefficients preserve the exact title CBV
        # checksum word; this case does not assert native world-space clip mode.
        struct.pack_into('<I', b6, 0, 55)
        for register, value in zip(range(4, 8), [*row, row_w]):
            struct.pack_into('<f', b6, register * 16 + 8, float(value))
        floats(20, p[0, :3] / frame['projection'][0][0])
        floats(21, p[1, :3] / frame['projection'][1][1])
        floats(22, -p[2, :3])
        for register, value in ((23, right), (24, up), (25, forward), (26, delta), (27, [1, 1, scale_z])):
            floats(register, value)
        struct.pack_into('<2i', b6, 28 * 16 + 8, 0, 0)
        struct.pack_into('<2I', b6, 29 * 16 + 8, width + int(fallback), height)
        struct.pack_into('<2f', b6, 30 * 16 + 8, 1 / width, 1 / height)
        struct.pack_into('<2fIf', b6, 31 * 16, width, height, 0, 0.)
        shadow = bytearray(256)
        # Independent serialization of the published selected-native-operand
        # layout. The production GPU capture must reproduce every byte.
        for target, component in ((0, 0), (16, 1), (32, 3)):
            for column in range(4):
                shadow[target + 4 * column:target + 4 * column + 4] = b6[16 * column + 4 * component:16 * column + 4 * component + 4]
        for column in range(4):
            shadow[48 + 4 * column:52 + 4 * column] = b6[(4 + column) * 16 + 8:(4 + column) * 16 + 12]
        for target, register in zip(range(64, 177, 16), range(20, 28)):
            shadow[target:target + 12] = b6[register * 16:register * 16 + 12]
        shadow[192:200] = b6[28 * 16 + 8:29 * 16]
        shadow[200:208] = b6[29 * 16 + 8:30 * 16]
        shadow[208:216] = b6[30 * 16 + 8:31 * 16]
        shadow[216:232] = b6[31 * 16:32 * 16]
        struct.pack_into('<2I', shadow, 232, 0x4e544d31, 1)
        payloads = {}
        for signal, probe in (('spec', [.03125, .0625, .015625, 5]), ('diff', [.125, .0625, .03125, 7])):
            value = data[signal].copy();value[~interior] = probe
            payloads[signal] = put(folder, signal + '.bin', value)
        normals = data['normals'].copy();normals[~interior] = 512 | (512 << 10) | (768 << 20)
        payloads['normals'] = put(folder, 'normals.bin', normals)
        payloads['raw_view_z'] = put(folder, 'raw-view-z.bin', raw_z.astype('<f4'))
        payloads['native_motion'] = put(folder, 'native-motion.bin', raw_motion)
        payloads['native_constants'] = put(folder, 'native-constants.bin', np.frombuffer(b6, 'u1'))
        payloads['native_shadow'] = put(folder, 'native-shadow.bin', np.frombuffer(shadow, 'u1'))
        payloads['expected_b'] = put(folder, 'expected-b.bin', expected.astype('<f4'))
        payloads['expected_camera_b'] = put(folder, 'expected-camera-b.bin', expected_camera.astype('<f4'))
        jitter = np.asarray(frame['jitter'])
        rr_xy = raw_motion[..., :2].astype(np.float64) + (np.zeros(2) if previous_jitter is None else previous_jitter - jitter) / (width, height)
        pixel = (uv + rr_xy) * (width, height)
        inside = ((pixel >= 0) & (pixel < (width, height))).all(axis=-1)
        legacy = np.zeros((height, width))
        if previous_depth is not None:
            sx, sy = np.floor(pixel[..., 0][inside]).astype(int), np.floor(pixel[..., 1][inside]).astype(int)
            legacy[inside] = previous_depth[sy, sx] + raw_z[inside]
        payloads['expected_legacy_b'] = put(folder, 'expected-legacy-b.bin', legacy.astype('<f4'))
        previous_depth, previous_jitter = -raw_z, jitter
        record = {key: frame[key] for key in ('frame', 'index', 'directory', 'view', 'projection', 'camera', 'jitter', 'reset')}
        record.update(payloads=payloads, fallback=fallback,
                      native_coefficient_range=[float(coefficient[interior].min()), float(coefficient[interior].max())],
                      native_offset=offset, native_z_scale=scale_z)
        frames.append(record)
    result = dict(schema='fsrd-world-native-motion-e2e-v1', width=width, height=height,
                  submitted_frames=len(frames), frames=frames,
                  world_oracle_manifest_sha256=sha((inputs / 'sequence.json').read_bytes()),
                  probe_border='excluded16pixels pin old exact native title GPU binding assertions',
                  native_operand_scope='synthetic full native screen-space operand codec; current/previous world poses independently define the oracle; not a game CB6 dump',
                  native_world_mode_tested=False, camera_fallback_index=24)
    (destination / 'sequence.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result
