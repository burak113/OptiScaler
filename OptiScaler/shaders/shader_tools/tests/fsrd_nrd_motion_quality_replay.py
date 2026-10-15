"""Seal/inspect CPU inputs by default; --run needs the lead's shared GPU/build slot.

Every measured candidate has the same radiance/noise/camera/depth/normal/albedo
bytes and one physically fresh signed-provider history. Only motion B differs.
The actual production RR wrapper, RGB commit, Consumer and GPU guide readbacks
are exercised; native title motion conversion/coordinator proof is separate.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys

os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2',
                  OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))
from fsrd_nrd_motion_quality_oracle import SCHEMA, MODES, load, metrics, sha, write_sequence

DLL = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/external/FidelityFX-SDK-v2/Kits/FidelityFX/signedbin/amd_fidelityfx_denoiser_dx12.dll')
DLL_SHA = '48f1e5888ba6a0a3d59a98b9751e37c392b0f7b8c223d0082d5c1f40642879d3'
COMMON = ('spec', 'diff', 'depth', 'normals', 'spec_albedo', 'diff_albedo')
CHECKS = 0


def require(value, message):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(message)


def file_sha(path):
    return sha(Path(path).read_bytes())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def validate(directory):
    directory = Path(directory)
    value = json.loads((directory / 'sequence.json').read_text(encoding='utf-8'))
    require(value['schema'] == SCHEMA and value['width'] == value['height'] == 128, 'exact world-surface128 manifest')
    require(56 <= value['submitted_frames'] <= 96 and len(value['frames']) == value['submitted_frames'], 'bounded complete temporal scene')
    meta = value['native_replay']
    require(Path(meta['file']).name == meta['file'], 'metadata path is local')
    data = (directory / meta['file']).read_bytes()
    require(len(data) == meta['bytes'] and sha(data) == meta['sha256'], 'sealed native camera-table hash')
    for index, frame in enumerate(value['frames']):
        require(frame['frame'] == index + 2 and frame['index'] == index and frame['reset'] == (index == 0), 'whole scene temporal alignment/reset')
        require(Path(frame['directory']).name == frame['directory'], 'frame folder is local')
        for record in frame['payloads'].values():
            load(directory / frame['directory'], record)
    return value


def link(source, target):
    if target.exists():
        require(file_sha(source) == file_sha(target), 'existing immutable candidate view must match source exactly')
    else:
        os.link(source, target)


def candidate_view(inputs, manifest, destination, mode):
    destination.mkdir(parents=True, exist_ok=True)
    link(inputs / manifest['native_replay']['file'], destination / 'native-replay.txt')
    for frame in manifest['frames']:
        origin, folder = inputs / frame['directory'], destination / frame['directory']
        folder.mkdir(exist_ok=True)
        for name in COMMON:
            link(origin / frame['payloads'][name]['file'], folder / (name + '.bin'))
        link(origin / frame['payloads']['motion_' + mode]['file'], folder / 'motion.bin')
    write_json(destination / 'view.json', dict(input_manifest_sha256=file_sha(inputs / 'sequence.json'),
               motion_mode=mode, common_payloads_unchanged=True, hardlinks_read_only_by_contract=True))


def build(output):
    from fsrd_toolchain import compile_cpp, dxc
    output.mkdir(parents=True, exist_ok=True)
    os.environ['FSRD_CPP_CACHE'] = str(output / 'cache')
    (output / 'pch.h').write_text('#pragma once\n', encoding='utf-8')
    source = HERE / 'nrd_bridge_consumer_fixture.hlsl'
    shader = output / 'consumer.cso'
    subprocess.run([str(dxc()), '-T', 'cs_6_2', '-E', 'CSMain', '-O3', '-force-rootsig-ver',
                    'rootsig_1_0', str(source), '-Fo', str(shader)], check=True)
    (output / 'consumer_shader.h').write_text('const unsigned char ConsumerShaderBytes[] = {' +
                                            ','.join(map(str, shader.read_bytes())) + '};\n', encoding='utf-8')
    exe = output / 'world_motion_quality.exe'
    compile_cpp(HERE / 'fsrd_nrd_motion_quality_replay.cpp', exe,
                ['d3d12.lib', 'dxgi.lib', 'd3dcompiler.lib', 'bcrypt.lib'],
                [output, ROOT / 'OptiScaler', ROOT / 'OptiScaler/include', ROOT / 'external/nlohmann',
                 ROOT / 'external/streamline', ROOT / 'external/FidelityFX-SDK/ffx-api/include/ffx_api'])
    return exe, dict(executable_sha256=file_sha(exe), cpp_sha256=file_sha(HERE / 'fsrd_nrd_motion_quality_replay.cpp'),
                     rr_source_sha256=file_sha(ROOT / 'OptiScaler/shaders/fsrd_preprocess/FSRDNrdBridgeRR_Dx12.cpp'),
                     wrapper_fixture_sha256=file_sha(HERE / 'nrd_bridge_rr_fixture.cpp'),
                     consumer_shader_sha256=file_sha(shader))


def native(exe, view, output, route, settings=None, probe=False):
    from test_fsrd_nrd_bridge_rr import bounded_run
    output.mkdir(parents=True, exist_ok=True)
    command = [str(exe), str(view), str(output), route, 'DEFAULT' if probe else str(settings), '1' if probe else 'ALL']
    text, peak, elapsed, native_log = bounded_run(command, output / 'native')
    value = json.loads((output / 'native-result.json').read_text(encoding='utf-8'))
    require('PASS world_motion ' in text, 'actual native process reached final strict assertions')
    require(value['debug_errors'] == value['debug_warnings'] == 0, 'actual D3D12 debug layer clean')
    require(value['creates'] == value['destroys'] == 1 and value['route'] == route, 'fresh signed-provider context balanced')
    require(value['signal_flags'] == (0x30 if route == 'id' else 0x22), 'actual create route flags')
    require(value['diffuse_descriptor_type'] == (0x50047 if route == 'id' else 0x50044) and
            value['specular_descriptor_type'] == 0x50048, 'actual ordered DD-ID/IS public ABI descriptor chain')
    require(value['native_birth_ready'] is False, 'standalone wrapper adapter boundary explicit')
    value.update(elapsed_seconds=elapsed, peak_resident_bytes=peak, native_log=str(native_log))
    write_json(output / 'native-result.json', value)
    return value


def tail_summary(rows):
    result = {}
    for age in [str(n) for n in range(9)] + ['9..16']:
        values = [row['reveal_tail'][age] for row in rows if age in row['reveal_tail']]
        support = sum(v['pixels'] for v in values)
        if support:
            result[age] = dict(pixels=support)
            for name in ('mean_signed_stale_fraction', 'positive_stale_energy', 'error_energy'):
                result[age][name] = sum(v[name] * v['pixels'] for v in values) / support
            result[age]['rgb_rmse'] = float(np.sqrt(sum(v['rgb_rmse'] ** 2 * v['pixels'] for v in values) / support))
    return result


def compare(inputs, manifest, runs):
    frames, all_metrics = [], {name: [] for name in runs}
    for frame in manifest['frames']:
        directory = inputs / frame['directory']
        age = load(directory, frame['payloads']['reveal_age'])
        row = dict(frame=frame['frame'], signals={})
        for signal in ('spec', 'diff'):
            reference = load(directory, frame['payloads']['reference_' + signal])
            ghost = load(directory, frame['payloads']['ghost_' + signal])
            values = {'noisy_input': metrics(load(directory, frame['payloads'][signal]), reference, age, ghost, manifest['comparison_crop'])}
            for name, run in runs.items():
                record = run['outputs'][str(frame['frame'])][signal]
                path = Path(run['directory']) / frame['directory'] / (signal + '.bin')
                data = path.read_bytes()
                require(sha(data) == record and len(data) == 128 * 128 * 8, 'same-frame actual output integrity')
                out = np.frombuffer(data, dtype='<f2').reshape(128, 128, 4)
                values[name] = metrics(out, reference, age, ghost, manifest['comparison_crop'])
                all_metrics[name].append(values[name])
            row['signals'][signal] = values
        frames.append(row)
    summaries = {}
    for name in list(runs) + ['noisy_input']:
        rows = [frame['signals'][signal][name] for frame in frames for signal in ('spec', 'diff')]
        late = [frame['signals'][signal][name] for frame in frames[-8:] for signal in ('spec', 'diff')]
        summaries[name] = dict(mean_frame_rgb_rmse=float(np.mean([v['rgb_rmse'] for v in rows])),
                              settled_last8_rgb_rmse=float(np.mean([v['rgb_rmse'] for v in late])),
                              mean_frame_chroma_rmse=float(np.mean([v['chroma_rmse'] for v in rows])),
                              mean_frame_chroma_p99=float(np.mean([v['chroma_absolute_p99'] for v in rows])),
                              mean_detail_gradient_rmse=float(np.mean([v['detail_gradient_rmse'] for v in rows])),
                              mean_gradient_projection_ratio=float(np.mean([v['gradient_projection_ratio'] for v in rows])),
                              reveal_age_curve=tail_summary(rows))
    noisy = summaries['noisy_input']['reveal_age_curve']
    for summary in summaries.values():
        supported = [str(n) for n in range(9) if str(n) in summary['reveal_age_curve'] and str(n) in noisy]
        good = [age for age in supported if all(summary['reveal_age_curve'][later]['rgb_rmse'] <= noisy[later]['rgb_rmse']
                                               for later in supported if int(later) >= int(age))]
        summary['first_age_below_input_noise_for_all_remaining_supported_ages'] = int(good[0]) if good else None
    return dict(input_manifest_sha256=file_sha(inputs / 'sequence.json'), frames=frames, summaries=summaries,
                no_quality_improvement_assertion=True, native_nrd_paired=False, game_fps_measured=False,
                scope='same-input synthetic world/object/camera/noise and actual signed RR, independent current-frame analytic radiance; no game-native NRD or combined-color truth',
                caveats=['Primary-surface MV does not equal reflected-environment feature motion; correct geometry alone does not guarantee specular denoising quality.',
                         'Point-sampled prescribed radiance is not path-integrated antialiasing ground truth.',
                         'Reveal support excludes exact-ray/nearest-grid silhouette disagreements.',
                         'Scalar guide candidates are independent preconverted inputs; production native temporal conversion is verified separately.'])


def export_crops(inputs, manifest, runs, output):
    from PIL import Image, ImageDraw
    output.mkdir(exist_ok=True)
    support = []
    for frame in manifest['frames']:
        age = load(inputs / frame['directory'], frame['payloads']['reveal_age'])
        support.append((int(np.count_nonzero(age == 0)), int(np.count_nonzero(age == 4)), frame))
    selected = [max(support, key=lambda v: v[0])[2], max(support, key=lambda v: v[1])[2], manifest['frames'][-1]]
    panels = ['reference', 'noisy_input'] + list(runs)
    crop = manifest['comparison_crop'];x, y, width, height = crop;scale = 2
    paths = []
    for frame in selected:
        image = Image.new('RGB', (len(panels) * width * scale, 2 * (height * scale + 24) + 28), (20, 20, 20))
        draw = ImageDraw.Draw(image)
        draw.text((4, 5), f'Frame{frame["frame"]} synthetic reference; fixed gain3 + gamma2.2 display; metrics linearRGB', fill='white')
        for row, signal in enumerate(('spec', 'diff')):
            for column, name in enumerate(panels):
                if name in ('reference', 'noisy_input'):
                    key = 'reference_' + signal if name == 'reference' else signal
                    value = load(inputs / frame['directory'], frame['payloads'][key])[..., :3]
                else:
                    value = np.fromfile(Path(runs[name]['directory']) / frame['directory'] / (signal + '.bin'), '<f2').reshape(128, 128, 4)[..., :3]
                shown = np.rint(np.clip(value[y:y+height, x:x+width].astype(np.float32)*3, 0, 1) ** (1/2.2) * 255).astype('u1')
                panel = Image.fromarray(shown).resize((width*scale, height*scale), Image.Resampling.NEAREST)
                px, py = column*width*scale, 28 + row*(height*scale + 24)
                draw.text((px+3, py+4), signal+' '+name, fill='white');image.paste(panel, (px, py+24))
        path = output / f'frame{frame["frame"]:03d}.png';image.save(path);paths.append(str(path))
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15e-quality/replay')))
    parser.add_argument('--modes', nargs='+', choices=MODES, default=list(MODES))
    parser.add_argument('--routes', nargs='+', choices=('dd', 'id'), default=['dd'])
    parser.add_argument('--run', action='store_true', help='compile and run real GPU work ONLY when lead grants the shared slot')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not (args.inputs / 'sequence.json').exists():
        write_sequence(args.inputs)
    manifest = validate(args.inputs)
    prepared = {}
    for mode in args.modes:
        path = args.output / 'views' / mode
        candidate_view(args.inputs, manifest, path, mode)
        prepared[mode] = path
    result = dict(input_manifest_sha256=file_sha(args.inputs / 'sequence.json'),
                  prepared_views={key: str(value) for key, value in prepared.items()},
                  submitted_frames=manifest['submitted_frames'], compiler_executed=False, gpu_executed=False,
                  python_checks=CHECKS, native_nrd_paired=False)
    if not args.run:
        write_json(args.output / 'prepared.json', result)
        print(json.dumps(result, indent=2))
        return
    require(file_sha(DLL) == DLL_SHA, 'exact sealed signed AMD provider binary')
    exe, source_hashes = build(args.output / 'build')
    probe = native(exe, prepared[args.modes[0]], args.output / 'defaults-probe', 'dd', probe=True)
    settings = args.output / 'common-effective-settings.txt'
    numbers = struct.unpack('<8f', struct.pack('<8I', *probe['effective_words']))
    settings.write_text(' '.join(format(float(v), '.9g') for v in numbers) + '\n')
    runs = {}
    for route in args.routes:
        for mode in args.modes:
            name = route + '_' + mode
            directory = args.output / name
            value = native(exe, prepared[mode], directory, route, settings=settings)
            require(value['dispatches'] == manifest['submitted_frames'], 'actual complete quality history dispatch count')
            require([f['frame'] for f in value['frames']] == [f['frame'] for f in manifest['frames']], 'native output temporal alignment')
            require([f['reset'] for f in value['frames']] == [True] + [False] * (len(manifest['frames'])-1), 'first-only RESET throughout each actual history')
            require(value['effective_words'] == probe['effective_words'], 'all actual candidates use the same effective SDK settings bits')
            value['outputs'] = {}
            for frame in manifest['frames']:
                folder = directory / frame['directory']
                expected_motion = frame['payloads']['motion_' + mode]
                require(file_sha(folder / 'motion.bin') == expected_motion['sha256'], 'actual GPU motion readback equals selected independent guide mode')
                value['outputs'][str(frame['frame'])] = {signal: file_sha(folder / (signal + '.bin')) for signal in ('spec', 'diff')}
            value.update(directory=str(directory), mode=mode, input_manifest_sha256=result['input_manifest_sha256'])
            write_json(directory / 'native-result.json', value)
            runs[name] = value
    comparison = compare(args.inputs, manifest, runs)
    comparison['crops'] = export_crops(args.inputs, manifest, runs, args.output / 'crops')
    result.update(compiler_executed=True, gpu_executed=True, dll_sha256=DLL_SHA, source_hashes=source_hashes,
                  runs=runs, comparison=comparison, python_checks=CHECKS)
    write_json(args.output / 'comparison.json', result)
    report = Path('E:/FSRD/sol_batch/15e-quality');report.mkdir(parents=True, exist_ok=True)
    write_json(report / 'comparison.json', result)
    print(json.dumps(dict(result=str(args.output / 'comparison.json'), checks=CHECKS,
                          actual_signed_frames=sum(v['dispatches'] for v in runs.values()),
                          summaries=comparison['summaries']), indent=2))


if __name__ == '__main__':
    main()
