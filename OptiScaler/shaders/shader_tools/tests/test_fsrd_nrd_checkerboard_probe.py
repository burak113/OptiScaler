"""Controlled signed-RR probe, not evidence of the title's live checkerboard mode.

Compare full-resolution negative-alpha inactive samples with the SDK's documented
packed checkerboard input. Invoke only through the machine-wide GPU-lock wrapper.
The frozen standalone runner is adapted into a new TU; its source is never edited.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_toolchain import compile_cpp
from test_fsrd_nrd_bridge_rr import bounded_run, DLL

def signal_flag(name):
    header = (ROOT / 'OptiScaler/include/fsr-rr/ffx_denoiser.h').read_text()
    match = re.search(r'FFX_DENOISER_SIGNAL_' + name + r'\s*=\s*\(1\s*<<\s*(\d+)\)', header)
    assert match, name
    return 1 << int(match[1])


DIFFUSE_FLAG = signal_flag('DIRECT_DIFFUSE')
SPECULAR_FLAG = signal_flag('INDIRECT_SPECULAR')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace_once(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)


def adapted_runner():
    original = HERE / 'fsrd_rr_runner.cpp'
    source = original.read_text(encoding='utf-8')
    headers = {
        '../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/ffx_api_loader.h':
            ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/ffx_api_loader.h',
        '../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/dx12/ffx_api_dx12.h':
            ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include/dx12/ffx_api_dx12.h',
        '../../../../external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h':
            ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h',
    }
    for old, new in headers.items():
        source = replace_once(source, old, new.resolve().as_posix())
    source = replace_once(source, '    bool alternates=false;',
                          '    const bool packed = getenv("FSRD_CB_PACKED") != nullptr;\n    bool alternates=false;')
    source = replace_once(source, '        t.format=DXGI_FORMAT(fmt);',
                          '        const unsigned tw = w; // Signed provider validates full physical input width, even for packed signals.\n        t.format=DXGI_FORMAT(fmt);')
    source = replace_once(source, 'd.Width=w; d.Height=h;', 'd.Width=tw; d.Height=h;')
    source = replace_once(source, 'ffxApiGetSurfaceFormatDX12(t.format),w,h,1,1,0,',
                          'ffxApiGetSurfaceFormatDX12(t.format),tw,h,1,1,0,')
    source = replace_once(source, 'uint64_t(w)*h*t.bpp*t.frames', 'uint64_t(tw)*h*t.bpp*t.frames')
    source = replace_once(source, 'signalMask,0,FFX_DENOISER_ENABLE_VALIDATION',
                          'signalMask,packed ? signalMask : 0,FFX_DENOISER_ENABLE_VALIDATION')
    source = replace_once(source, 'size_t(w)*t.bpp);', 'size_t(t.api.description.width)*t.bpp);')
    source = replace_once(source, '        dispatch.frameIndex=frame;',
                          '        diff.signal.checkerboardOrigin = spec.signal.checkerboardOrigin = packed ? (frame & 1) : 0;\n        dispatch.frameIndex=frame;')
    return source, sha(original)


def write_inputs(folder, mode, width=128, height=128, frames=32):
    import numpy as np
    folder.mkdir(parents=True, exist_ok=True)
    y, x = np.mgrid[:height, :width]
    # Deliberately synthetic, static geometry: no claim about game camera/NRD inputs.
    z = np.full((height, width), 4, dtype='<f4')
    z.tofile(folder / 'depth.bin')
    motion = np.zeros((height, width, 4), dtype='<f2')
    motion[..., 3] = 1
    motion.tofile(folder / 'motion.bin')
    normal = np.full((height, width), 512 | (512 << 10) | (256 << 20), dtype='<u4')
    normal.tofile(folder / 'normal.bin')
    albedo = np.full((height, width, 4), 255, dtype='u1')
    albedo.tofile(folder / 'spec_albedo.bin')
    albedo[..., 3] = 0
    albedo.tofile(folder / 'diff_albedo.bin')
    base = np.empty((height, width, 3), dtype='f4')
    base[...] = [1.0, 0.4, 0.15]
    base[(x >= 40) & (x < 88) & (y >= 32) & (y < 96)] = [0.1, 0.9, 1.8]
    base[(x % 16) == 0] = [3.0, 0.2, 0.7]
    rng = np.random.default_rng(20261015)
    radiance = np.maximum(base[None] + rng.normal(0, .15, (frames, height, width, 3)), 0)
    signal = np.empty((frames, height, width, 4), dtype='<f2')
    signal[..., :3] = radiance.astype('<f2')
    signal[..., 3] = 4
    inactive = np.empty((frames, height, width), dtype='?')
    for frame in range(frames):
        inactive[frame] = ((x ^ y ^ frame) & 1) != 0
    if mode in ('inactive', 'inactive_poison', 'zero_alpha'):
        signal[inactive, :3] = [12, 0, 0] if mode == 'inactive_poison' else 0
        signal[inactive, 3] = 0 if mode == 'zero_alpha' else -1
    if mode == 'packed_padded':
        # The actual provider rejected a physical half-width input (R4, FFX=6).
        # Retain the half-width logical layout in the left half of a full-width
        # allocation. Poison padding makes unintended reads observable.
        packed = np.empty((frames, height, width, 4), dtype='<f2')
        packed[...] = [31, 7, 19, 4]
        for frame in range(frames):
            xx = 2 * np.arange(width // 2)[None] + ((np.arange(height)[:, None] ^ frame) & 1)
            packed[frame, :, :width // 2] = signal[frame, np.arange(height)[:, None], xx]
        signal = packed
    signal.tofile(folder / 'diff.bin')
    signal.tofile(folder / 'spec.bin')
    base.tofile(folder / 'reference.f32')
    # Fixed explicit DLL path, all seven inputs, production direct diffuse / indirect specular.
    lines = [f'{width} {height} {frames} {DIFFUSE_FLAG} {SPECULAR_FLAG} 0 0 0 {json.dumps(str(DLL))}']
    for name, fmt, count in [('depth', 41, 1), ('motion', 10, 1), ('normal', 24, 1),
                             ('spec_albedo', 28, 1), ('diff_albedo', 28, 1),
                             ('diff', 10, frames), ('spec', 10, frames)]:
        lines.append(f'{json.dumps(str(folder / (name + ".bin")))} {fmt} {count}')
    lines += [json.dumps(str(folder / 'out_diff.bin')), json.dumps(str(folder / 'out_spec.bin'))]
    (folder / 'job.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return base, inactive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    work = Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15-nrd-ghosting/tests/checkerboard-probe'))
    work.mkdir(parents=True, exist_ok=True)
    generated, original_sha = adapted_runner()
    source = work / 'checkerboard_probe_runner.cpp'
    source.write_text(generated, encoding='utf-8')
    modes = ('dense', 'inactive', 'inactive_poison', 'zero_alpha', 'packed_padded')
    rows = {}
    for mode in modes:
        base, inactive = write_inputs(work / mode, mode)
        rows[mode] = {'input_sha256': sha(work / mode / 'diff.bin')}
    if args.prepare_only:
        print(json.dumps({'prepared': True, 'compiled': False, 'gpu': False, 'source': str(source), 'legacy_sha256': original_sha}))
        return
    import numpy as np
    report = Path(os.environ.get('FSRD_NRD_REPORT_OUTPUT', 'E:/FSRD/sol_batch/15-nrd-ghosting/tests/checkerboard-probe'))
    report.mkdir(parents=True, exist_ok=True)
    assert not (report / 'checkerboard-probe.json').exists(), 'Fresh name required; retain prior evidence'
    os.environ['FSRD_CPP_CACHE'] = str(work / 'cache')
    exe = work / 'checkerboard_probe_runner.exe'
    compile_cpp(source, exe, ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib'],
                [ROOT / 'external/FidelityFX-SDK-v2/Kits/FidelityFX/api/include'])
    outputs = {}
    for mode in modes:
        if mode == 'packed_padded':
            os.environ['FSRD_CB_PACKED'] = '1'
        else:
            os.environ.pop('FSRD_CB_PACKED', None)
        text, peak, seconds, log = bounded_run([str(exe), str(work / mode / 'job.txt')], work / mode / 'runner')
        assert 'validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' in text
        for lobe in ('diff', 'spec'):
            output = np.fromfile(work / mode / ('out_' + lobe + '.bin'), dtype='<f2').reshape(32, 128, 128, 4).astype('f4')
            assert np.isfinite(output).all(), (mode, lobe)
            outputs[mode, lobe] = output
            error = output[8:, ..., :3] - base
            lum_error = error @ np.array([.2126, .7152, .0722], dtype='f4')
            rows[mode][lobe] = {
                'rgb_rmse': float(np.sqrt(np.mean(error ** 2))),
                'luminance_rmse': float(np.sqrt(np.mean(lum_error ** 2))),
                'inactive_rgb_mean': output[8:, ..., :3][inactive[8:]].mean(axis=0).tolist(),
                'active_rgb_mean': output[8:, ..., :3][~inactive[8:]].mean(axis=0).tolist(),
                'inactive_negative_alpha_fraction': float(np.mean(output[8:, ..., 3][inactive[8:]] < 0)),
                'sha256': sha(work / mode / ('out_' + lobe + '.bin')),
            }
        rows[mode].update(seconds=seconds, peak_resident_bytes=peak, log=str(log))
    result = {'scope': 'Controlled signed SDK synthetic; not live title flags, game quality or checkerboard support proof',
              'width': 128, 'height': 128, 'frames': 32, 'signal_flags': DIFFUSE_FLAG | SPECULAR_FLAG,
              'packed_storage': 'Half-width logical active samples in left half of full-width allocation; right padding poisoned. Physical half-width rejected by actual provider in preserved R4.',
              'provider_path': str(DLL), 'provider_sha256': sha(DLL),
              'legacy_runner_sha256_before': original_sha, 'legacy_runner_sha256_after': sha(HERE / 'fsrd_rr_runner.cpp'),
              'generated_runner_sha256': sha(source), 'executable_sha256': sha(exe), 'rows': rows}
    assert result['legacy_runner_sha256_before'] == result['legacy_runner_sha256_after']
    (report / 'checkerboard-probe.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
