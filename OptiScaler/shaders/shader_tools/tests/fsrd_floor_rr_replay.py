"""Replay actual Floor conversion signals through the signed native AMD RR DLL.

NPZ keys: diffuse/specular [F,H,W,4] (RGB radiance, A hit distance), depth
[H,W] or [F,H,W], motion [H,W,4] or [F,H,W,4] (UV xy, depth delta z), normals
with the same RGBA shape (oct-normal xy, roughness z, material w), and
diffuse_albedo/specular_albedo with the same RGBA shape. Normals can instead
be packed uint32 [H,W]/[F,H,W]; albedos can be native uint8. Float guides are
quantized to the production R10G10B10A2/R8G8B8A8 UNORM storage. Depth is R32F;
motion and signals are RGBA16F. No filtering or demodulation runs in this helper.

Optional keys: resets [F], jitters [F,2], view/projection [4,4] or [F,4,4] in AMD's
row-major row-vector convention, depth_bounds [2] or [F,2], camera_position_delta
[3] or [F,3], motion_vector_scale [3] or [F,3]. Every supplied dispatch control
is checked against the native binary record. The default camera is identity view
with a 60-degree LH perspective, near .1, far 1000. Defaults match Config.h RR
tuning. One native context persists for the entire sequence; frame 0 resets.
readback.npz stores the actual native GPU results, metadata.json their provenance.
For linear-depth fixtures whose HLSL InvProjMatrix is identity, explicitly pass
linear_identity_projection(): the shader rescales the NDC-z=.5 ray to linear
depth, giving xy/z=2*NDC. A perspective with x/y scale .5 matches those rays.
An identity RR projection is accepted by the API but does not match these rays.
For a logical extent below 64, pad_native=True adds inactive physical guard
texels, adjusts projection and UV motion, and crops outputs to the logical ROI.

python fsrd_floor_rr_replay.py --input-npz converted.npz --output tools_tmp/replay
python fsrd_floor_rr_replay.py --smoke --output tools_tmp/replay_smoke
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp

DLL = ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll'
NATIVE = ROOT / 'tools_tmp/fsrd_floor_replay/native/fsrd_floor_rr_replay.exe'
TUNING = dict(disocclusion_threshold=.1, cross_bilateral_normal_strength=.5,
              stability_bias=.5, max_radiance=40000., radiance_clip_std_k=40.,
              gaussian_kernel_relaxation=.5)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value, name):
    array = np.asarray(value)
    if not np.issubdtype(array.dtype, np.number) or not np.isfinite(array).all():
        raise ValueError(f'{name} must contain finite numeric values')
    return array


def _guide(value, name, frames, height, width, channels):
    array = _finite(value, name)
    expected = (height, width) + (() if channels is None else (channels,))
    if array.shape == expected:
        return array[None]
    if array.shape in ((1,) + expected, (frames,) + expected):
        return array
    raise ValueError(f'{name} shape {array.shape} must be {expected} or {(frames,) + expected}')


def pack_normals(value):
    """Quantize Floor's oct-normal/roughness/material guide to DXGI format 24."""
    array = _finite(value, 'normals')
    if array.dtype == np.uint32:
        return np.ascontiguousarray(array, dtype='<u4')
    if array.shape[-1] != 4 or np.any(array < 0) or np.any(array > 1):
        raise ValueError('float normals must be RGBA in [0,1]')
    q = np.rint(array.astype(np.float64) * np.array([1023, 1023, 1023, 3])).astype(np.uint32)
    return np.ascontiguousarray(q[..., 0] | (q[..., 1] << 10) | (q[..., 2] << 20) | (q[..., 3] << 30), dtype='<u4')


def _albedo(value, name):
    if value.dtype == np.uint8:
        return np.ascontiguousarray(value)
    if np.any(value < 0) or np.any(value > 1):
        raise ValueError(f'{name} float guide must be in [0,1]')
    return np.ascontiguousarray(np.rint(value.astype(np.float64) * 255), dtype='u1')


def _half(value, name):
    if np.max(np.abs(value), initial=0) > np.finfo(np.float16).max:
        raise ValueError(f'{name} exceeds RGBA16F finite storage')
    return np.ascontiguousarray(value, dtype='<f2')


def _signature(dll):
    # The path is supplied as an argument, never interpolated into PowerShell code.
    script = "& { param($p) $ErrorActionPreference='Stop'; $s=Get-AuthenticodeSignature -FilePath $p; $v=(Get-Item -LiteralPath $p).VersionInfo; [pscustomobject]@{status=[string]$s.Status; signer=$s.SignerCertificate.Subject; thumbprint=$s.SignerCertificate.Thumbprint; file_version=$v.FileVersion; product_version=$v.ProductVersion} | ConvertTo-Json -Compress }"
    shell = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
    if shell is None:
        raise RuntimeError('PowerShell is required to verify the AMD DLL Authenticode signature')
    environment = os.environ.copy()
    environment.pop('PSModulePath', None)  # Avoid importing PS7 modules into Windows PowerShell.
    result = subprocess.run([shell, '-NoProfile', '-Command', script, str(dll)], env=environment,
                            capture_output=True, text=True, check=True)
    signature = json.loads(result.stdout)
    if signature.get('status') != 'Valid' or 'Advanced Micro Devices' not in signature.get('signer', ''):
        raise RuntimeError(f'Expected valid signed AMD denoiser DLL: {signature}')
    return signature


def build_native(output=None):
    native = NATIVE if output is None else Path(output).resolve()
    native.parent.mkdir(parents=True, exist_ok=True)
    if not os.environ.get('FSRD_VS_ROOT') and Path('F:/VisualStudio/VC/Auxiliary/Build/vcvars64.bat').is_file():
        os.environ['FSRD_VS_ROOT'] = 'F:/VisualStudio'
    compile_cpp(HERE / 'fsrd_floor_rr_replay.cpp', native, ('d3d12.lib', 'dxgi.lib'))
    return native


def _camera(view, projection, height, width, depth_bounds):
    view = np.eye(4) if view is None else _finite(view, 'view')
    if projection is None:
        scale = 1 / np.tan(np.pi / 6)
        near, far = .1, 1000.
        projection = np.array([[scale * height / width, 0, 0, 0], [0, scale, 0, 0],
                               [0, 0, far / (far - near), 1], [0, 0, -near * far / (far - near), 0]])
    projection = _finite(projection, 'projection')
    bounds = _finite(depth_bounds, 'depth_bounds')
    if view.shape != (4, 4) or projection.shape != (4, 4) or bounds.shape != (2,) or not bounds[0] < bounds[1]:
        raise ValueError('view/projection must be [4,4]; depth_bounds must be ascending [2]')
    return np.asarray(view, np.float32), np.asarray(projection, np.float32), np.asarray(bounds, np.float32)


def _control_sequence(value, name, frames, shape, default):
    array = _finite(default if value is None else value, name)
    if array.shape == shape:
        return np.broadcast_to(array, (frames,) + shape).astype(np.float32).copy()
    if array.shape == (frames,) + shape:
        return array.astype(np.float32)
    raise ValueError(f'{name} must have shape {shape} or {(frames,) + shape}')


def _camera_sequence(view, projection, height, width, depth_bounds, frames):
    defaults = _camera(None, None, height, width, (0, 1024))
    views = _control_sequence(view, 'view', frames, (4, 4), defaults[0])
    projections = _control_sequence(projection, 'projection', frames, (4, 4), defaults[1])
    bounds = _control_sequence(depth_bounds, 'depth_bounds', frames, (2,), defaults[2])
    if np.any(bounds[:, 0] >= bounds[:, 1]):
        raise ValueError('depth_bounds must ascend on every frame')
    return views, projections, bounds


def _run_native_rr(output, *, diffuse, specular, depth, motion, normals, diffuse_albedo,
           specular_albedo, resets=None, jitters=None, view=None, projection=None,
           depth_bounds=(0, 1024), camera_position_delta=None, motion_vector_scale=None,
           direct_specular=None, indirect_diffuse=None, tuning=True, signals='both', executable=None):
    """Return {'diffuse': RGBA, 'specular': RGBA, 'metadata': JSON-compatible dict}."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    diffuse, specular = _finite(diffuse, 'diffuse'), _finite(specular, 'specular')
    if diffuse.ndim != 4 or diffuse.shape[-1] != 4 or diffuse.shape != specular.shape:
        raise ValueError('diffuse and specular must have identical [F,H,W,4] shapes')
    frames, height, width, _ = diffuse.shape
    if not frames or not height or not width:
        raise ValueError('empty sequence')
    if signals not in ('both', 'diffuse', 'specular'):
        raise ValueError('signals must be both/diffuse/specular')
    depth = _guide(depth, 'depth', frames, height, width, None).astype('<f4')
    motion = _half(_guide(motion, 'motion', frames, height, width, 4), 'motion')
    normal_array = _finite(normals, 'normals')
    normals = pack_normals(_guide(normal_array, 'normals', frames, height, width,
                                None if normal_array.dtype == np.uint32 else 4))
    diffuse_albedo = _albedo(_guide(diffuse_albedo, 'diffuse_albedo', frames, height, width, 4), 'diffuse_albedo')
    specular_albedo = _albedo(_guide(specular_albedo, 'specular_albedo', frames, height, width, 4), 'specular_albedo')
    diffuse, specular = _half(diffuse, 'diffuse'), _half(specular, 'specular')
    alternates = direct_specular is not None or indirect_diffuse is not None
    if alternates:
        if direct_specular is None or indirect_diffuse is None or signals != 'both':
            raise ValueError('direct_specular and indirect_diffuse must be supplied together with both main signals')
        direct_specular = _half(_finite(direct_specular, 'direct_specular'), 'direct_specular')
        indirect_diffuse = _half(_finite(indirect_diffuse, 'indirect_diffuse'), 'indirect_diffuse')
        if direct_specular.shape != diffuse.shape or indirect_diffuse.shape != diffuse.shape:
            raise ValueError('alternate signals must have the same [F,H,W,4] shape as main signals')
    resets = np.zeros(frames, dtype=np.uint32) if resets is None else _finite(resets, 'resets')
    if resets.shape != (frames,) or np.any((resets != 0) & (resets != 1)):
        raise ValueError('resets must be [F] containing zero or one')
    resets = np.asarray(resets, np.uint32).copy()
    resets[0] = 1
    jitters = np.zeros((frames, 2), dtype=np.float32) if jitters is None else _finite(jitters, 'jitters')
    if jitters.shape != (frames, 2):
        raise ValueError('jitters must be [F,2]')
    views, projections, bounds = _camera_sequence(view, projection, height, width, depth_bounds, frames)
    camera_deltas = _control_sequence(camera_position_delta, 'camera_position_delta', frames, (3,), [0, 0, 0])
    motion_scales = _control_sequence(motion_vector_scale, 'motion_vector_scale', frames, (3,), [1, 1, 1])
    if not DLL.is_file():
        raise FileNotFoundError(DLL)
    signature = _signature(DLL)
    executable = build_native() if executable is None else Path(executable).resolve()
    entries = []
    names = ('depth', 'motion', 'normal', 'specular_albedo', 'diffuse_albedo', 'diffuse', 'specular')
    for name, array, fmt in zip(names, (depth, motion, normals, specular_albedo, diffuse_albedo, diffuse, specular),
                                (41, 10, 24, 28, 28, 10, 10)):
        path = output / f'input_{name}.bin'
        array.tofile(path)
        entries.append(dict(name=name, path=str(path), format=fmt, frames=len(array), sha256=_sha256(path)))
    if alternates:
        for name, array in (('direct_specular', direct_specular), ('indirect_diffuse', indirect_diffuse)):
            path = output / f'input_{name}.bin'
            array.tofile(path)
            entries.append(dict(name=name, path=str(path), format=10, frames=len(array), sha256=_sha256(path)))
    diff_flag, spec_flag = (2 if signals != 'specular' else 0), (32 if signals != 'diffuse' else 0)
    out_diff, out_spec = output / 'output_diffuse.bin', output / 'output_specular.bin'
    lines = [f'{width} {height} {frames} {diff_flag} {spec_flag} 0 {int(bool(tuning))} 0 "{DLL.as_posix()}"']
    lines += [f'"{Path(e["path"]).as_posix()}" {e["format"]} {e["frames"]}' for e in entries]
    out_direct_spec = output / 'output_direct_specular.bin'
    out_indirect_diff = output / 'output_indirect_diffuse.bin'
    output_records = f'"{out_diff.as_posix()}" "{out_spec.as_posix()}"'
    if alternates:
        output_records += f' "{out_direct_spec.as_posix()}" "{out_indirect_diff.as_posix()}"'
    lines += [output_records]
    job = output / 'job.txt'
    job.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    controls = np.column_stack((resets, jitters)).astype(np.float64)
    np.savetxt(output / 'frame_controls.txt', controls, fmt=('%u', '%.9g', '%.9g'))
    np.savetxt(output / 'camera.txt', np.concatenate((views[0].ravel(), projections[0].ravel(), [0, 0], bounds[0]))[None], fmt='%.9g')
    frame_camera = np.column_stack((np.arange(frames), motion_scales, camera_deltas,
                                   views.reshape(frames, 16), projections.reshape(frames, 16), bounds))
    np.savetxt(output / 'frame_camera.txt', frame_camera, fmt=['%u'] + ['%.9g'] * 40,
               header=f'fsrd_frame_camera_v1 {frames}', comments='')
    started = time.monotonic()
    environment = os.environ.copy()
    environment.pop('FSRD_RR_ALTERNATES', None)
    if alternates:
        environment['FSRD_RR_ALTERNATES'] = '1'
    result = subprocess.run([str(executable), str(job)], cwd=output, capture_output=True, text=True,
                            timeout=max(120, frames * 10), env=environment)
    log = result.stdout + result.stderr
    (output / 'runner.log').write_text(log, encoding='utf-8')
    counters = {k: int(v) for k, v in re.findall(r'\b(dispatches|validation_errors|validation_warnings|sdk_errors|sdk_warnings)=(\d+)', log)}
    adapter = re.search(r'^adapter=(.+?) driver=(-?\d+) debug_layer=(\d+)$', log, re.M)
    provider = re.search(r'^provider=(.*?) id=(\d+) version_query_result=(\d+) requested_api=(\d+)$', log, re.M)
    metadata = dict(kind='actual_signed_amd_rr_gpu_readback', status='failed', dimensions=[width, height],
                    input_provenance='Caller-supplied buffers; this helper does not establish their Floor provenance.',
                    frames=frames, signal_flags=[diff_flag, spec_flag] + ([4, 16] if alternates else []),
                    signal_chain_order=(['direct_diffuse','direct_specular','indirect_diffuse','indirect_specular']
                                        if alternates else ['direct_diffuse','indirect_specular']),
                    context_lifetime='sequence', passthrough=False,
                    dll=str(DLL), dll_sha256=_sha256(DLL), signature=signature,
                    executable=str(executable), executable_sha256=_sha256(executable),
                    source_sha256=_sha256(HERE / 'fsrd_floor_rr_replay.cpp'),
                    shared_runner_sha256=_sha256(HERE / 'fsrd_rr_runner.cpp'),
                    seconds=time.monotonic()-started, return_code=result.returncode, counters=counters,
                    adapter=(dict(name=adapter[1], driver=int(adapter[2]), debug_layer=bool(int(adapter[3]))) if adapter else None),
                    provider=(dict(name=provider[1], id=int(provider[2]), version_query_result=int(provider[3]),
                                   requested_api=int(provider[4])) if provider else None),
                    inputs=entries, tuning=TUNING if tuning else 'AMD defaults', reset_frames=np.flatnonzero(resets).tolist(),
                    jitters=np.asarray(jitters).tolist(), view=views[0].tolist(), projection=projections[0].tolist(),
                    depth_bounds=bounds[0].tolist(),
                    frame_camera=dict(path=str(output / 'frame_camera.txt'), sha256=_sha256(output / 'frame_camera.txt'),
                                      views=views.tolist(), projections=projections.tolist(), depth_bounds=bounds.tolist(),
                                      camera_position_deltas=camera_deltas.tolist(), motion_vector_scales=motion_scales.tolist()))
    metadata_path = output / 'metadata.json'
    def save_metadata():
        metadata_path.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    save_metadata()
    if result.returncode or counters.get('dispatches') != frames or counters.get('validation_errors') != 0 or counters.get('sdk_errors') != 0:
        raise RuntimeError(f'Native RR failed ({result.returncode}); inspect {output / "runner.log"}\n{log}')
    control_path = output / 'dispatch_controls.bin'
    control_record = struct.Struct('<4I42f')
    control_data = control_path.read_bytes()
    if len(control_data) != frames * control_record.size:
        raise RuntimeError('native dispatch control readback byte count mismatch')
    applied = []
    for frame, record in enumerate(control_record.iter_unpack(control_data)):
        if record[:4] != (frame, 2 | int(resets[frame]), width, height) or not np.array_equal(
                np.asarray(record[10:12], np.float32), np.asarray(jitters[frame], np.float32)):
            raise RuntimeError(f'native frame {frame} did not apply requested reset/jitter controls')
        if not np.array_equal(np.asarray(record[12:14], np.float32), bounds[frame]) or not np.array_equal(
                np.asarray(record[14:30], np.float32), views[frame].ravel()) or not np.array_equal(
                np.asarray(record[30:46], np.float32), projections[frame].ravel()) or not np.array_equal(
                np.asarray(record[4:7], np.float32), motion_scales[frame]) or not np.array_equal(
                np.asarray(record[7:10], np.float32), camera_deltas[frame]):
            raise RuntimeError(f'native frame {frame} did not apply requested camera/depth controls')
        applied.append(dict(frame=record[0], flags=record[1], reset=bool(record[1] & 1), jitter=list(record[10:12])))
    metadata['applied_controls'] = dict(path=str(control_path), sha256=_sha256(control_path),
                                       record_bytes=control_record.size, frames=applied)
    readback = {}
    output_sources = [('diffuse', out_diff, diff_flag, diffuse), ('specular', out_spec, spec_flag, specular)]
    if alternates:
        output_sources += [('direct_specular', out_direct_spec, 4, direct_specular),
                           ('indirect_diffuse', out_indirect_diff, 16, indirect_diffuse)]
    for name, path, enabled, source in output_sources:
        if not enabled:
            continue
        if path.stat().st_size != frames * height * width * 8:
            raise RuntimeError(f'{name} GPU readback byte count mismatch')
        array = np.fromfile(path, dtype='<f2').astype(np.float32).reshape(frames, height, width, 4)
        if not np.isfinite(array).all():
            raise RuntimeError(f'{name} GPU readback contains nonfinite values')
        readback[name] = array
        rgb_delta = array[..., :3] - source[..., :3].astype(np.float32)
        metadata.setdefault('readback', {})[name] = dict(path=str(path), sha256=_sha256(path), finite=True,
                                                       input_delta_rms=float(np.sqrt(np.mean(rgb_delta.astype(np.float64)**2))),
                                                       unchanged_rgb_fraction=float(np.mean(np.all(rgb_delta == 0, axis=-1))))
    np.savez_compressed(output / 'readback.npz', **readback)
    metadata['status'] = 'passed'
    save_metadata()
    readback['metadata'] = metadata
    return readback


def linear_identity_projection(near=.1, far=1000.):
    """AMD row-major/row-vector LH projection matching the fixture's linear ray.

    HLSL identity inverse-projection reconstructs [NDC.x,NDC.y,.5], then
    multiplies all coordinates by linearDepth/.5. The matching pinhole
    projection has x/y scale .5 and clip.w=view.z. Near/far control only clip.z.
    This utility applies to that synthetic linear-depth path, not an arbitrary
    hardware-depth or orthographic camera.
    """
    if not np.isfinite([near, far]).all() or not 0 < near < far:
        raise ValueError('projection near/far must be finite and 0 < near < far')
    return np.array([[.5, 0, 0, 0], [0, .5, 0, 0], [0, 0, far/(far-near), 1],
                     [0, 0, -near*far/(far-near), 0]], dtype=np.float32)


def run_rr(output, *, diffuse, specular, depth, motion, normals, diffuse_albedo,
           specular_albedo, resets=None, jitters=None, view=None, projection=None,
           depth_bounds=(0, 1024), camera_position_delta=None, motion_vector_scale=None,
           direct_specular=None, indirect_diffuse=None, tuning=True, signals='both', executable=None,
           pad_native=False):
    """Replay native RR and return logical RGBA outputs and complete provenance.

    Padding is explicit: the signed runtime crashes creating sub-64 contexts,
    and larger context allocation alone produces zero-thread GPU dispatches for
    a sub-64 render extent. pad_native uses a physical extent >=64 in both axes,
    keeps the original viewport at (0,0), and scores no added texels. Guard depth
    is outside the denoising bounds and both signal alpha channels are -1, the
    SDK's inactive-signal convention. Camera crop transforms preserve original
    logical pixel positions; motion xy changes from logical to physical UV units.
    """
    diffuse, specular = _finite(diffuse, 'diffuse'), _finite(specular, 'specular')
    if diffuse.ndim != 4 or diffuse.shape[-1] != 4 or diffuse.shape != specular.shape:
        raise ValueError('diffuse and specular must have identical [F,H,W,4] shapes')
    frames, logical_h, logical_w, _ = diffuse.shape
    if not frames or not logical_h or not logical_w:
        raise ValueError('empty sequence')
    views, logical_projections, bounds = _camera_sequence(view, projection, logical_h, logical_w, depth_bounds, frames)
    physical_h = max(64, logical_h) if pad_native else logical_h
    physical_w = max(64, logical_w) if pad_native else logical_w
    padded = (physical_h, physical_w) != (logical_h, logical_w)
    original = dict(diffuse=diffuse, specular=specular, depth=np.asarray(depth), motion=np.asarray(motion),
                    normals=np.asarray(normals), diffuse_albedo=np.asarray(diffuse_albedo),
                    specular_albedo=np.asarray(specular_albedo))
    native = original.copy()
    for name, value in (('direct_specular', direct_specular), ('indirect_diffuse', indirect_diffuse)):
        if value is not None:
            native[name] = original[name] = _finite(value, name)
    crop = np.eye(4, dtype=np.float64)
    crop[0, 0], crop[1, 1] = logical_w/physical_w, logical_h/physical_h
    crop[3, 0], crop[3, 1] = (logical_w-physical_w)/physical_w, (physical_h-logical_h)/physical_h
    physical_projections = np.asarray(logical_projections.astype(np.float64) @ crop, np.float32)
    maximum_depth = float(bounds[:, 1].max())
    guard_depth = maximum_depth + max(1., abs(maximum_depth) * .01)
    if padded:
        def pad(array, fill=0):
            # Normalized inputs always carry a frame axis, including static guides.
            shape = (len(array), physical_h, physical_w) + array.shape[3:]
            result = np.full(shape, fill, dtype=array.dtype)
            result[:, :logical_h, :logical_w] = array
            return result
        for name in ('diffuse', 'specular', 'direct_specular', 'indirect_diffuse'):
            if name not in original:
                continue
            native[name] = pad(_half(original[name], name))
            native[name][:, logical_h:, :, 3] = -1
            native[name][:, :, logical_w:, 3] = -1
        native['depth'] = pad(_guide(original['depth'], 'depth', frames, logical_h, logical_w, None).astype('<f4'), guard_depth)
        logical_motion = _guide(original['motion'], 'motion', frames, logical_h, logical_w, 4).astype(np.float32)
        native['motion'] = pad(logical_motion)
        native['motion'][..., 0] *= logical_w/physical_w
        native['motion'][..., 1] *= logical_h/physical_h
        normal_channels = None if original['normals'].dtype == np.uint32 else 4
        native['normals'] = pad(_guide(original['normals'], 'normals', frames, logical_h, logical_w, normal_channels))
        for name in ('diffuse_albedo', 'specular_albedo'):
            native[name] = pad(_guide(original[name], name, frames, logical_h, logical_w, 4))
    result = _run_native_rr(output, **native, resets=resets, jitters=jitters, view=views,
                            projection=physical_projections, depth_bounds=bounds,
                            camera_position_delta=camera_position_delta, motion_vector_scale=motion_vector_scale, tuning=tuning,
                            signals=signals, executable=executable)
    output = Path(output).resolve()
    metadata = result['metadata']
    metadata['python_helper_sha256'] = _sha256(Path(__file__))
    metadata['dimensions'] = [logical_w, logical_h]
    metadata['native_dimensions'] = [physical_w, physical_h]
    metadata['viewport'] = dict(pad_native_requested=bool(pad_native), padded=padded,
                                logical_extent=[logical_w, logical_h], physical_extent=[physical_w, physical_h],
                                logical_origin=[0, 0], scored_added_texels=0,
                                guard_policy='outside-depth-bounds and inactive signal alpha=-1' if padded else None,
                                guard_depth=guard_depth if padded else None,
                                motion_uv_scale=[logical_w/physical_w, logical_h/physical_h],
                                logical_projection=logical_projections[0].tolist(),
                                physical_projection=physical_projections[0].tolist(), row_vector_crop_transform=crop.tolist())
    metadata['logical_inputs'] = [dict(name=name, shape=list(array.shape), dtype=str(array.dtype),
                                      sha256=hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest())
                                   for name, array in original.items()]
    if padded:
        physical_readback = output / 'physical_readback.npz'
        (output / 'readback.npz').replace(physical_readback)
        for name in ('diffuse', 'specular', 'direct_specular', 'indirect_diffuse'):
            if name in result:
                result[name] = result[name][:, :logical_h, :logical_w].copy()
        np.savez_compressed(output / 'readback.npz', **{k: v for k, v in result.items() if k != 'metadata'})
        metadata['physical_readback_npz'] = dict(path=str(physical_readback), sha256=_sha256(physical_readback))
    metadata['logical_readback_npz'] = dict(path=str(output / 'readback.npz'), sha256=_sha256(output / 'readback.npz'))
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return result


def smoke_inputs(frames=12, width=128, height=96):
    """Native availability smoke only; these signals are not a Floor quality claim."""
    rng = np.random.default_rng(92149)
    yy, xx = np.mgrid[:height, :width]
    truth = np.repeat((.25 + .15 * ((xx // 4) % 2))[..., None], 3, axis=-1)
    diffuse = np.zeros((frames, height, width, 4), np.float32)
    diffuse[..., :3] = np.maximum(truth + .1 * rng.normal(size=diffuse[..., :3].shape), 0)
    diffuse[..., 3] = 10
    specular = diffuse.copy()
    specular[..., :3] *= .2
    depth = np.full((frames, height, width), 10, np.float32)
    depth[frames // 2:, :, :width // 3] = 5
    normals = np.broadcast_to([1., 1., .3, 0.], (height, width, 4)).copy()
    albedo = np.broadcast_to([.5, .5, .5, 0.], (height, width, 4)).copy()
    return dict(diffuse=diffuse, specular=specular, depth=depth, motion=np.zeros((height, width, 4)),
                normals=normals, diffuse_albedo=albedo, specular_albedo=albedo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input-npz', type=Path)
    source.add_argument('--smoke', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--signals', choices=('both', 'diffuse', 'specular'), default='both')
    parser.add_argument('--amd-defaults', action='store_true')
    parser.add_argument('--pad-native', action='store_true', help='Use explicit inactive physical padding for logical extents below 64; outputs remain logical')
    parser.add_argument('--linear-identity-camera', action='store_true', help='Match the HLSL identity-inverse-projection linear-depth reconstruction')
    args = parser.parse_args()
    if args.smoke:
        inputs = smoke_inputs()
    else:
        with np.load(args.input_npz, allow_pickle=False) as archive:
            allowed = {'diffuse', 'specular', 'depth', 'motion', 'normals', 'diffuse_albedo', 'specular_albedo',
                       'resets', 'jitters', 'view', 'projection', 'depth_bounds',
                       'camera_position_delta', 'motion_vector_scale', 'direct_specular', 'indirect_diffuse'}
            inputs = {key: archive[key] for key in archive.files if key in allowed}
    if args.linear_identity_camera:
        inputs['view'] = np.eye(4, dtype=np.float32)
        inputs['projection'] = linear_identity_projection()
    result = run_rr(args.output, **inputs, signals=args.signals, tuning=not args.amd_defaults, pad_native=args.pad_native)
    result['metadata']['input_provenance'] = ('Native availability smoke; independent synthetic signals, no Floor quality claim.'
                                             if args.smoke else dict(npz=str(args.input_npz.resolve()), sha256=_sha256(args.input_npz)))
    (args.output / 'metadata.json').write_text(json.dumps(result['metadata'], indent=2) + '\n', encoding='utf-8')
    metadata = result['metadata']
    print(json.dumps(dict(status=metadata['status'], frames=metadata['frames'], dimensions=metadata['dimensions'],
                          adapter=metadata['adapter'], counters=metadata['counters'], readback=metadata['readback'],
                          metadata=str((args.output / 'metadata.json').resolve())), indent=2))


if __name__ == '__main__':
    main()
