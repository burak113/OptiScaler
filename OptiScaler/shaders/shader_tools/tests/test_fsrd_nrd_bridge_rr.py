"""Compile and execute production NRD RRWrapper camera, lifetime and signed-DLL fixtures.

Invoke through lead_ops/run_task_test.py (its shared GPU lock is mandatory except
for --mode camera). The hook/proxy seam forwards real mode to the installed DLL.
"""
from pathlib import Path
import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fsrd_toolchain import compile_cpp, dxc

DLL = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')
CAPTURE = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/FRAME_SURVEY/da9f46edb00fd2144b531c8c0b6fc6a2')
REPORT = Path(os.environ.get('FSRD_NRD_RR_REPORT', 'E:/FSRD/sol_batch/13c-rr'))


def capture_inputs(folder):
    import numpy as np
    manifest = json.loads((CAPTURE / 'capture.json').read_text(encoding='utf-8'))
    frames = manifest['frames'][:manifest.get('manifest_published_frames', 0)]
    images = [(f, image) for f in frames for image in f['images']]

    def read(prefix, dtype, channels):
        matches = [(f, image) for f, image in images if image['name'].startswith(prefix)]
        if not matches:
            raise AssertionError(f'Published capture lacks {prefix}')
        frame, image = matches[-1]
        w, h = image['extent']
        data = np.fromfile(CAPTURE / image['file'], dtype=dtype).reshape(h, w, channels)
        return data, dict(name=image['name'], file=image['file'], list_id=frame['list_id'],
                         dxgi_format=image['dxgi_format'], extent=image['extent'])

    spec, spec_source = read('p7141_r44308', '<f2', 4)
    diff, diff_source = read('p7141_r44310', '<f2', 4)
    view_depth, depth_source = read('p7151_r44307', '<f4', 1)
    height, width = spec.shape[:2]
    assert (width, height) == (1505, 847) and diff.shape == spec.shape
    folder.mkdir(parents=True, exist_ok=True)
    for name, signal in [('spec', spec), ('diff', diff)]:
        converted = signal.copy()
        converted[..., :3] = np.clip(np.nan_to_num(signal[..., :3].astype(np.float32), nan=0,
                                                  posinf=65504, neginf=0), 0, 65504).astype('<f2')
        converted[..., 3] = np.where(np.isfinite(signal[..., 3]), signal[..., 3], np.float16(0))
        converted.tofile(folder / f'{name}.bin')
    (-np.clip(np.abs(view_depth), .02, 65504)).astype('<f4').tofile(folder / 'depth.bin')
    motion = np.zeros_like(spec)
    motion[..., 3] = 1
    motion.tofile(folder / 'motion.bin')
    packed = np.full((height, width), 512 | (512 << 10) | (512 << 20), dtype='<u4')
    packed.tofile(folder / 'normals.bin')
    albedo = np.full(spec.shape, 255, dtype=np.uint8)
    yscale = 1 / np.tan(np.pi / 6)
    xx = ((np.arange(width, dtype=np.float32) + .5) * 2 / width - 1) / (yscale / (width / height))
    yy = (1 - (np.arange(height, dtype=np.float32) + .5) * 2 / height) / yscale
    albedo[..., 3] = np.rint(255 / np.sqrt(1 + xx[None, :]**2 + yy[:, None]**2)).astype(np.uint8)
    albedo.tofile(folder / 'spec_albedo.bin')
    albedo[..., 3] = 0
    albedo.tofile(folder / 'diff_albedo.bin')
    native_sources = {}
    for name, prefix in [('nrd_spec', 'p8892_r44285'), ('nrd_diff', 'p8892_r44283')]:
        array, source = read(prefix, '<f2', 4)
        array.tofile(folder / f'{name}.bin')
        native_sources[name] = source
    assumptions = dict(capture=str(CAPTURE), manifest_published_frames=manifest.get('manifest_published_frames', 0),
                       spec=spec_source, diff=diff_source, substituted_depth=depth_source,
                       missing_exact_guides=['NR 3749', 'VIEWZ 44287'], motion='zero static replay; captured MV unused',
                       normals='synthetic uniform world +Z, roughness 0.5, material 0; camera-facing',
                       projection='near 0.02 derived from exact D=a+b/Z capture fit; 60 degree vertical FOV/RH reverse infinite/aspect 1505/847 remain assumptions',
                       albedos='white demodulated; spec alpha is dot(N,V), diffuse alpha zero',
                       jitter='zero static camera loop; captured jitter/camera unavailable',
                        input_generation='scalar fixture conversion, not evidence of exact in-game camera or guide parity',
                        native_nrd_sources=native_sources,
                        native_nrd_output_encoding='unknown; Consumer b6 space0 word303 was not published',
                        native_nrd_reference_scope='conditional arithmetic interpretations only; not paired RGB quality ground truth')
    (REPORT / 'capture-assumptions.json').write_text(json.dumps(assumptions, indent=2), encoding='utf-8')
    return folder


def bounded_run(command, output):
    """Apply low priority and a measured 2.5 GiB child resident-memory ceiling."""
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                                               'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                                               'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    log = output.with_suffix('.native.log')
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        ctypes.windll.kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, process.pid)
        peak = 0
        started = time.perf_counter()
        try:
            while process.poll() is None:
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                if handle and ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle), ctypes.byref(counters), counters.cb):
                    peak = max(peak, counters.WorkingSetSize)
                    if peak > int(2.5 * 1024**3):
                        process.kill()
                        raise RuntimeError(f'Native fixture exceeded resident memory limit: {peak}')
                if time.perf_counter() - started > 300:
                    process.kill()
                    raise RuntimeError('Native fixture exceeded five-minute limit')
                time.sleep(.1)
        finally:
            if handle:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        if process.returncode:
            print(log.read_text(encoding='utf-8', errors='replace'))
            raise subprocess.CalledProcessError(process.returncode, command)
    text = log.read_text(encoding='utf-8', errors='replace')
    print(text, end='')
    return text, peak, time.perf_counter() - started, log


def native_consumer_rgb_if_ycocg(signal):
    """Exact c3f6fb... Consumer nonzero-flag branch; captured flag remains unknown."""
    import numpy as np
    rgb = np.stack((signal[..., 0] - signal[..., 2] + signal[..., 1],
                    signal[..., 0] + signal[..., 2],
                    signal[..., 0] - signal[..., 2] - signal[..., 1]), axis=-1)
    return np.maximum(rgb, np.float32(0))


def images_and_stats(inputs, output):
    import numpy as np
    from PIL import Image, ImageDraw
    width, height = 1505, 847
    statistics = {}
    canvas = Image.new('RGB', (4 * 752, 2 * 455), (20, 20, 24))
    draw = ImageDraw.Draw(canvas)
    for row, signal in enumerate(['spec', 'diff']):
        arrays = [np.fromfile(inputs / f'{signal}.bin', dtype='<f2').reshape(height, width, 4).astype(np.float32),
                  np.fromfile(output / f'da9f_1505x847_{signal}.rgba16f', dtype='<f2').reshape(height, width, 4).astype(np.float32),
                  np.fromfile(inputs / f'nrd_{signal}.bin', dtype='<f2').reshape(height, width, 4).astype(np.float32)]
        luminance = arrays[2][..., :3] @ np.array([.2126, .7152, .0722], dtype=np.float32)
        scale = .5 / max(float(np.percentile(luminance[luminance > 0], 60)), 1e-6)
        native_if_ycocg = native_consumer_rgb_if_ycocg(arrays[2][..., :3])
        panels = [arrays[0][..., :3], arrays[1][..., :3], arrays[2][..., :3], native_if_ycocg]
        labels = ['Raw Recon', 'RR static replay (assumed guides)',
                  'Captured NRD if RGB (mode UNKNOWN)', 'Captured NRD if YCoCg (mode UNKNOWN)']
        for column, (array, label) in enumerate(zip(panels, labels)):
            rgb = np.maximum(array, 0) * scale
            rgb /= 1 + rgb
            rgb = np.where(rgb <= .0031308, 12.92 * rgb, 1.055 * rgb**(1/2.4) - .055)
            image = Image.fromarray(np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8))
            image.save(REPORT / f'da9f_{signal}_{column}.png')
            canvas.paste(image.resize((752, 423)), (column * 752, row * 455 + 32))
            draw.text((column * 752 + 8, row * 455 + 8), f'{signal}: {label}', fill=(255, 230, 120))
        statistics[signal] = dict(rr_finite_values=int(np.isfinite(arrays[1]).sum()), total_values=int(arrays[1].size),
                                 rr_mean_rgb=float(arrays[1][..., :3].mean()), nrd_mean_rgb=float(arrays[2][..., :3].mean()),
                                 raw_mean_rgb=float(arrays[0][..., :3].mean()), shared_tonemap_scale=scale,
                                 evidence_only=True, native_nrd_output_encoding='unknown',
                                 native_nrd_mode_proven=False,
                                 native_nrd_reference_scope='unpaired assumed-guide static replay; no native RGB quality ground truth',
                                 legacy_numeric_scope='nrd_mean_rgb and shared_tonemap_scale assume native RGB; values preserved conditionally',
                                 nrd_if_ycocg_mean_rgb=float(native_if_ycocg.mean()),
                                 native_consumer_nonzero_formula='max((Y-Cg+Co, Y+Cg, Y-Cg-Co), 0)',
                                 output_scale_scope='before Consumer factor64 and specular exposure; shared tone scale retains legacy ifRGB basis')
    canvas.save(REPORT / 'da9f_raw_rr_nrd.png')
    return statistics


def native_debug_statistics(output):
    import numpy as np
    from PIL import Image
    folder = output / 'native_debug'
    sources = sorted(path for path in folder.glob('*.rgba16f') if not path.stem.endswith('_present'))
    assert len(sources) == 13, 'Actual AMD SDK must render overview and all 12 documented viewports'
    statistics = {}
    for path in sources:
        source = np.fromfile(path, dtype='<f2').reshape(847, 1505, 4)
        shown = np.fromfile(path.with_name(path.stem + '_present.rgba16f'), dtype='<f2').reshape(73, 137, 4)
        assert np.isfinite(source).all() and np.isfinite(shown).all()
        assert np.all(shown[..., 3] == np.float16(7)), 'Native debug must preserve every destination alpha'
        covered = source[..., 3] > 0
        assert covered.any(), 'Native SDK debug target must contain written pixels'
        # This evidence PNG clamps the provider's diagnostic RGB directly; it
        # does not emulate the title's later display transfer function.
        png = REPORT / f'amd_native_{path.stem}.png'
        Image.fromarray(np.rint(np.clip(source[..., :3].astype(np.float32), 0, 1) * 255).astype(np.uint8)).save(png)
        statistics[path.stem] = dict(source=str(path), shown=str(path.with_name(path.stem + '_present.rgba16f')),
                                     finite_values=int(np.isfinite(source).sum()), total_values=int(source.size),
                                     written_pixels=int(covered.sum()), exact_destination_alpha=7,
                                     rgb_min=float(source[..., :3].min()), rgb_max=float(source[..., :3].max()),
                                     evidence_png=str(png), display_transfer='direct clamp for evidence only')
    return statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['camera', 'mock', 'real', 'probe'], default='camera')
    parser.add_argument('--width', type=int, default=128)
    parser.add_argument('--height', type=int, default=128)
    parser.add_argument('--converted-inputs', type=Path)
    args = parser.parse_args()
    os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
    work = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/13c-rr/tests/nrd_rr'))
    work.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    os.environ['FSRD_CPP_CACHE'] = str(work / 'cache')
    exe = work / 'nrd_bridge_rr_fixture.exe'
    (work / 'pch.h').write_text('#pragma once\n', encoding='utf-8')
    shader = work / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver', 'rootsig_1_0',
                    str(Path(__file__).with_name('nrd_bridge_consumer_fixture.hlsl')), '-Fo', str(shader)], check=True)
    (work / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {' +
                                          ','.join(str(x) for x in shader.read_bytes()) + '};\n', encoding='utf-8')
    compile_cpp(Path(__file__).with_name('nrd_bridge_rr_fixture.cpp'), exe, ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib'],
                [work, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/streamline',
                 ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    command = [str(exe), f'--{args.mode}']
    result_name = args.mode
    if args.mode == 'probe':
        command.extend([str(args.width), str(args.height)])
        result_name = f'probe-{args.width}x{args.height}'
    inputs = None
    if args.mode == 'real':
        inputs = capture_inputs(work / 'capture-inputs')
        if args.converted_inputs:
            for target, source in [('spec', 'spec'), ('diff', 'diff'), ('depth', 'depth'), ('motion', 'motion'),
                                   ('normals', 'nr'), ('spec_albedo', 'spec_albedo'), ('diff_albedo', 'diff_albedo')]:
                (inputs / f'{target}.bin').write_bytes((args.converted_inputs / f'out_{source}.bin').read_bytes())
            assumptions_path = REPORT / 'capture-assumptions.json'
            assumptions = json.loads(assumptions_path.read_text(encoding='utf-8'))
            assumptions['input_generation'] = 'production ConversionPass GPU outputs from ' + str(args.converted_inputs)
            assumptions_path.write_text(json.dumps(assumptions, indent=2), encoding='utf-8')
        command.extend([str(inputs), str(REPORT / 'outputs')])
    text, peak, elapsed, log = bounded_run(command, work / result_name)
    match = re.search(r'^PASS checks=(\d+).*$', text, flags=re.M)
    assert match, 'Native fixture did not report PASS'
    assert 'commit_root actual_parameters=4 constants=5 cost_dwords=9' in text
    result = dict(mode=args.mode, native_checks=int(match.group(1)), native_summary=match.group(0),
                  executable=str(exe), native_log=str(log), peak_resident_bytes=peak, seconds=elapsed)
    if args.mode in ('mock', 'real'):
        assert 'native_blend cases=14 endpoints_exact=1 native_nan_alpha_no_store=1 live_root_and_table=1 fallback_wrong=1 closed_recording_immutable=1 extra_dispatches=0 extra_owned_bytes=0 history_resets_on_change=0' in text
        assert 'runtime_settings effective_changes=' in text
        assert 'unchanged_calls=0 debug_bounds_count=1 material_key_calls=0' in text
        assert 'native_debug views=13 ' in text
        assert 'default_extra_dispatch=0 default_extra_image_bytes=0' in text
        assert 'source_fence_complete=1 distinct_recording=1 explicit_source_owner=1' in text
        assert 'native_debug_dispatches=' in match.group(0)
        result['native_blend'] = [line for line in text.splitlines() if line.startswith('native_blend ')]
        result['runtime_settings'] = [line for line in text.splitlines() if line.startswith('runtime_settings ')]
        result['native_debug'] = [line for line in text.splitlines() if line.startswith('native_debug')]
    if args.mode == 'mock':
        assert 'native_blend_failures partial_provider=2 denied_admission=2 native_rgba_exact=1 fresh_recovery_context=1' in text
    if args.mode == 'real':
        result['dll_path'] = str(DLL)
        result['dll_sha256'] = hashlib.sha256(DLL.read_bytes()).hexdigest()
        result['capture_statistics'] = images_and_stats(inputs, REPORT / 'outputs')
        result['timings'] = [line for line in text.splitlines() if line.startswith('timing ')]
        result['capture_input_path'] = str(inputs)
        result['native_debug_statistics'] = native_debug_statistics(REPORT / 'outputs')
        assert any('native_debug_1505x847_to_2560x1440' in line for line in result['timings'])
        assert any('native_debug_2560x1440' in line for line in result['timings'])
    (REPORT / f'{result_name}-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
