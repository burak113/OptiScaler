"""CPU preparation by default; --run requires the lead's exclusive GPU slot.

Only native half RGB changes by an exactly reversible power of two. Alpha,
surface motion, camera, depth, normals and albedo retain the sealed V1 bytes.
Actual signed-RR outputs are divided in float64 before the unchanged oracle's
metrics. Raw output hashes remain evidence; no noisy light bypasses RR.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import struct
import sys

os.environ.update(TEMP='F:/FSRD/tmp', TMP='F:/FSRD/tmp', OMP_NUM_THREADS='2',
                  OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
import numpy as np

SCALES = (.25, 1., 4., 16., 64., 256.)
V1_SHA = '27545e6db81e5214b2c0622a57ae05efa9ca2ed8148666e86e9542c63fd9974d'
MAIN_TESTS = Path('F:/OptiRevelations/OSA-15-nrd-ghosting/OptiScaler/shaders/shader_tools/tests')
DEFAULT_REPLAY = MAIN_TESTS / 'fsrd_nrd_motion_quality_replay.py'
DEFAULT_SETTINGS = Path('F:/FSRD/sol_batch/15-nrd-ghosting/tests/physical-motion-rr/comparison.json')
CHECKS = 0


def require(value, message):
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def safe_output(path):
    path = Path(path).resolve()
    spelling = str(path).replace('\\', '/').casefold()
    require('/reserve_data/' not in spelling and 'authenticated_arrays.npz' not in spelling,
            'forbidden data is never a source or destination')
    for forbidden in ('f:/ultra yedek 2', 'f:/steamlibrary/steamapps/common/cyberpunk 2077'):
        require(not (spelling == forbidden or spelling.startswith(forbidden + '/')),
                'no protected game/capture destination')
    return path


def source_module(path, name):
    path = Path(path).resolve()
    sys.path.insert(0, str(path.parent))
    sys.path.insert(1, str(path.parent.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def scale_signal(source, scale):
    """Reject a whole candidate on any loss; never clip or mask its pixels."""
    require(scale in SCALES, 'one of the six declared power-of-two scales')
    require(source.dtype == np.dtype('<f2') and source.ndim == 3 and source.shape[-1] == 4,
            'native little-endian half RGBA signal')
    rgb = source[..., :3].astype(np.float32)
    require(np.isfinite(rgb).all() and (rgb >= 0).all(), 'finite nonnegative sealed RGB')
    with np.errstate(over='ignore', under='ignore'):
        scaled_rgb = (rgb * np.float32(scale)).astype('<f2')
    require(np.isfinite(scaled_rgb).all(), 'whole sequence scale has no overflow')
    require(not np.any((rgb != 0) & (scaled_rgb == 0)), 'whole sequence scale has no nonzero-to-zero underflow')
    restored = scaled_rgb.astype(np.float32) / np.float32(scale)
    require(np.array_equal(restored, rgb), 'every scaled half RGB value inversely restores exactly')
    result = source.copy()
    result[..., :3] = scaled_rgb
    require(np.array_equal(result.view(np.uint16)[..., 3], source.view(np.uint16)[..., 3]),
            'every alpha/hit-distance bit is identical')
    values = scaled_rgb.astype(np.float32)
    positive = values[values > 0]
    return result, dict(components=int(values.size), exact_nonzero_subnormal_components=int(
        ((values > 0) & (values < np.float32(2**-14))).sum()),
        min_positive=float(positive.min()) if positive.size else None,
        maximum=float(values.max()), overflow=0, nonzero_to_zero_underflow=0,
        inverse_roundtrip_mismatches=0)


def write_immutable(path, data):
    if path.exists():
        require(path.read_bytes() == data, 'existing preparation is immutable and exact')
    else:
        path.write_bytes(data)


def prepare_views(replay, inputs, manifest, destination):
    prepared = {}
    for scale in SCALES:
        name = 'scale_' + format(scale, 'g').replace('.', 'p')
        view = destination / name
        view.mkdir(parents=True, exist_ok=True)
        replay.link(inputs / manifest['native_replay']['file'], view / 'native-replay.txt')
        rows = []
        for frame in manifest['frames']:
            origin, folder = inputs / frame['directory'], view / frame['directory']
            folder.mkdir(exist_ok=True)
            row = dict(frame=frame['frame'], unchanged={}, signals={})
            for signal in ('spec', 'diff'):
                record = frame['payloads'][signal]
                source = replay.load(origin, record)
                scaled, stats = scale_signal(source, scale)
                data = scaled.tobytes()
                write_immutable(folder / (signal + '.bin'), data)
                row['signals'][signal] = dict(source_sha256=record['sha256'], scaled_sha256=digest(data),
                    alpha_sha256=digest(source.view(np.uint16)[..., 3].tobytes()), **stats)
            for name_common in ('depth', 'normals', 'spec_albedo', 'diff_albedo'):
                record = frame['payloads'][name_common]
                replay.link(origin / record['file'], folder / (name_common + '.bin'))
                require(file_sha(folder / (name_common + '.bin')) == record['sha256'], 'unchanged exact guide byte hash')
                row['unchanged'][name_common] = record['sha256']
            motion = frame['payloads']['motion_surface']
            replay.link(origin / motion['file'], folder / 'motion.bin')
            require(file_sha(folder / 'motion.bin') == motion['sha256'], 'same exact surfaceB guide for every scale')
            row['unchanged']['motion_surface'] = motion['sha256']
            rows.append(row)
        meta = dict(schema='fsrd-radiance-domain-view-v1', source_manifest_sha256=V1_SHA,
            rgb_scale=scale, inverse_output_scale=1 / scale, motion_mode='surface', frames=rows,
            camera_table_sha256=manifest['native_replay']['sha256'],
            alpha_and_guides_exact=True, input_scale_admitted=True,
            hardlinks_read_only_by_contract=True, source_v1_written=False)
        write_json(view / 'view.json', meta)
        prepared['scale_' + format(scale, 'g').replace('.', 'p')] = dict(directory=str(view), **meta)
    return prepared


def sealed_settings(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    require(value['input_manifest_sha256'] == V1_SHA, 'settings source uses exact sealed V1')
    words = value['runs']['dd_surface']['effective_words']
    require(len(words) == 8 and all(type(v) is int for v in words), 'actual eight SDK words')
    require(all(v['effective_words'] == words for v in value['runs'].values()), 'sealed actual contexts used identical settings bits')
    numbers = struct.unpack('<8f', struct.pack('<8I', *words))
    text = ' '.join(format(float(v), '.9g') for v in numbers) + '\n'
    require(list(struct.unpack('<8I', struct.pack('<8f', *map(float, text.split())))) == words,
            'nine-digit settings text recovers every exact float32 bit')
    return dict(source=str(path), source_sha256=file_sha(path), words=words, numbers=numbers), text


def normalize_output(actual, scale):
    require(scale in SCALES, 'inverse uses the same declared RGB scale')
    require(actual.dtype == np.dtype('<f2') and actual.ndim == 3 and actual.shape[-1] == 4,
            'actual signed provider output is native half RGBA')
    require(np.isfinite(actual[..., :3]).all(), 'raw actual RR RGB finite before normalization')
    normalized = actual.astype(np.float64)
    normalized[..., :3] /= scale
    require(np.array_equal(normalized[..., 3], actual[..., 3].astype(np.float64)),
            'output alpha is not radiance-scaled')
    return normalized


def published_quantiles(loader_path, index_path):
    loader = source_module(loader_path, '_radiance_published_loader')
    index = json.loads(index_path.read_text(encoding='utf-8'))
    quantiles = [0, .001, .01, .1, .25, .5, .75, .9, .95, .99, .999, 1]
    result = []
    for capture in index['captures']:
        frames = loader.published_frames(capture)
        published = {frame['ordinal'] for frame in frames}
        images = {image['file']: image for image in capture['images']}
        used = set()
        for chain in capture.get('analysis_sets', []):
            for signal in ('recon_spec', 'recon_diff'):
                node = chain['signals'][signal]
                for spelling in node['payloads']:
                    if spelling in used:
                        continue
                    used.add(spelling)
                    image = images[spelling]
                    require(image['ordinal'] in published, 'Recon snapshot belongs to a published immutable recording')
                    require(node['state'] == 'published_exact_writer_snapshot' and image['dxgi_format'] == 10,
                            'exact post-Recon RGBA16F snapshot, never later Consumer output')
                    require(0 < image['bytes'] <= 128 * 1024 * 1024, 'one bounded payload at a time')
                    array = loader.load_image(capture, image)
                    require(not array.flags.writeable, 'capture loader maps original words read-only')
                    rgb = array[..., :3].astype(np.float64)
                    require(np.isfinite(rgb).all() and (rgb >= 0).all(), 'published native Recon RGB finite/nonnegative')
                    luma = rgb @ np.array([.2126, .7152, .0722])
                    positive = luma[luma > 0]
                    scaled_domains = {}
                    for scale in SCALES:
                        with np.errstate(over='ignore', under='ignore'):
                            half = (rgb * scale).astype(np.float16)
                        restored = half.astype(np.float64) / scale
                        scaled_domains[format(scale, 'g')] = dict(nonfinite=int((~np.isfinite(half)).sum()),
                            nonzero_to_zero=int(((rgb > 0) & (half == 0)).sum()),
                            inverse_roundtrip_mismatches=int((restored != rgb).sum()))
                    result.append(dict(capture_uuid=capture['capture_uuid'], ordinal=image['ordinal'],
                        list_id=chain['list_id'], recon_pass=chain['recon_pass'], signal=signal,
                        payload=spelling, sha256=image['sha256'], extent=image['extent'],
                        quantile_levels=quantiles, luminance_proxy_quantiles=np.quantile(luma, quantiles).tolist(),
                        positive_luminance_proxy_quantiles=np.quantile(positive, quantiles).tolist() if positive.size else [],
                        black_pixel_fraction=float(np.mean(luma == 0)), max_rgb=float(rgb.max()),
                        alpha_unchanged_scope='Only RGB statistics; no temporal or normal-space inference',
                        fp16_scale_domains=scaled_domains))
                    del array, rgb, luma, positive, half, restored
    require(bool(result), 'at least one exact published Recon pair available')
    return dict(index=str(index_path), index_sha256=file_sha(index_path), loader_sha256=file_sha(loader_path),
        luminance_proxy='0.2126R+0.7152G+0.0722B of pre-Consumer native demod RGB; no absolute photometric calibration',
        one_payload_at_a_time=True, temporal_quality_claim=False, rows=result)


def normalized_metrics(replay, inputs, manifest, raw_runs):
    frames, summaries = [], {}
    for frame in manifest['frames']:
        origin = inputs / frame['directory']
        age = replay.load(origin, frame['payloads']['reveal_age'])
        row = dict(frame=frame['frame'], signals={})
        for signal in ('spec', 'diff'):
            reference = replay.load(origin, frame['payloads']['reference_' + signal]).astype(np.float64)
            ghost = replay.load(origin, frame['payloads']['ghost_' + signal]).astype(np.float64)
            noisy = replay.load(origin, frame['payloads'][signal])
            values = {'noisy_input': replay.metrics(noisy, reference, age, ghost, manifest['comparison_crop'])}
            outputs = {'noisy_input': noisy[..., :3].astype(np.float64)}
            for name, run in raw_runs.items():
                path = Path(run['directory']) / frame['directory'] / (signal + '.bin')
                raw = path.read_bytes()
                require(digest(raw) == run['outputs'][str(frame['frame'])][signal], 'actual raw signed-RR output hash before normalization')
                require(len(raw) == 128 * 128 * 8, 'native half RGBA output extent')
                actual = np.frombuffer(raw, '<f2').reshape(128, 128, 4)
                # No extra FP16 quantization after inversion. Alpha remains the
                # actual raw provider output, never divided by radiance scale.
                normalized = normalize_output(actual, run['rgb_scale'])
                values[name] = replay.metrics(normalized, reference, age, ghost, manifest['comparison_crop'])
                outputs[name] = normalized[..., :3]
            x, y, width, height = manifest['comparison_crop']
            cut = np.s_[y:y + height, x:x + width]
            ref = reference[cut]
            ref_energy = float(np.sum(ref))
            for name, output in outputs.items():
                current = output[cut]
                values[name].update(reference_rgb_sum=ref_energy, output_rgb_sum=float(np.sum(current)),
                    signed_mean_rgb_error=float(np.mean(current - ref)),
                    energy_ratio=float(np.sum(current) / ref_energy) if ref_energy else None,
                    consumer_rgb_rmse=values[name]['rgb_rmse'] * 64)
            row['signals'][signal] = values
        frames.append(row)
    for name in list(raw_runs) + ['noisy_input']:
        rows = [f['signals'][s][name] for f in frames for s in ('spec', 'diff')]
        late = [f['signals'][s][name] for f in frames[-8:] for s in ('spec', 'diff')]
        summaries[name] = dict(mean_frame_rgb_rmse=float(np.mean([v['rgb_rmse'] for v in rows])),
            settled_last8_rgb_rmse=float(np.mean([v['rgb_rmse'] for v in late])),
            mean_frame_chroma_rmse=float(np.mean([v['chroma_rmse'] for v in rows])),
            mean_frame_chroma_p99=float(np.mean([v['chroma_absolute_p99'] for v in rows])),
            mean_detail_gradient_rmse=float(np.mean([v['detail_gradient_rmse'] for v in rows])),
            mean_gradient_projection_ratio=float(np.mean([v['gradient_projection_ratio'] for v in rows])),
            total_energy_ratio=float(sum(v['output_rgb_sum'] for v in rows) / sum(v['reference_rgb_sum'] for v in rows)),
            mean_signed_rgb_error=float(np.mean([v['signed_mean_rgb_error'] for v in rows])),
            mean_consumer_rgb_rmse=float(np.mean([v['consumer_rgb_rmse'] for v in rows])),
            reveal_age_curve=replay.tail_summary(rows))
    return dict(frames=frames, summaries=summaries, inverse_scale_before_all_metrics=True,
        normalization_dtype='float64 exact power-of-two; alpha untouched',
        consumer_metric_scope='Derived from already inverse-scaled actual RR RGB using native Consumer64 with unity exposure in the unchanged C++ fixture. Its .75/2 values are title alpha sentinels, not exposures. Game exposure is not serialized.',
        no_quality_improvement_assertion=True, no_game_temporal_claim=True)


def run_gpu(replay, inputs, manifest, prepared, output, settings_contract, settings_text):
    require(file_sha(replay.DLL) == replay.DLL_SHA, 'exact immutable signed AMD provider binary')
    exe, source_hashes = replay.build(output / 'build')
    settings = output / 'common-effective-settings.txt'
    write_immutable(settings, settings_text.encode('ascii'))
    runs = {}
    for name, view in prepared.items():
        probe = replay.native(exe, Path(view['directory']), output / (name + '-probe'), 'dd', probe=True)
        require(probe['effective_words'] == settings_contract['words'], 'fresh scale probe equals sealed actual SDK default bits')
        directory = output / name
        native = replay.native(exe, Path(view['directory']), directory, 'dd', settings=settings)
        require(native['dispatches'] == manifest['submitted_frames'], 'complete fresh64-sample scale history')
        require(native['effective_words'] == settings_contract['words'], 'all scale contexts forced to identical8-word settings')
        require([f['frame'] for f in native['frames']] == [f['frame'] for f in manifest['frames']], 'identical temporal/camera sequence')
        require([f['reset'] for f in native['frames']] == [True] + [False] * 63, 'first-only reset without hidden scale-dependent gaps')
        native['outputs'] = {}
        for frame in manifest['frames']:
            folder = directory / frame['directory']
            require(file_sha(folder / 'motion.bin') == frame['payloads']['motion_surface']['sha256'], 'actual GPU motion unchanged')
            native['outputs'][str(frame['frame'])] = {s: file_sha(folder / (s + '.bin')) for s in ('spec', 'diff')}
        native.update(directory=str(directory), rgb_scale=view['rgb_scale'], source_manifest_sha256=V1_SHA,
                      fresh_probe=probe, alpha_and_guides_exact=True)
        write_json(directory / 'native-result.json', native)
        runs[name] = native
    comparison = normalized_metrics(replay, inputs, manifest, runs)
    return dict(runs=runs, comparison=comparison, source_hashes=source_hashes, provider_sha256=replay.DLL_SHA)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=Path('F:/FSRD/sol_batch/15e-quality/inputs'))
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT', 'F:/FSRD/sol_batch/15b-inputs/radiance-domain-preparation')))
    parser.add_argument('--replay-source', type=Path, default=DEFAULT_REPLAY)
    parser.add_argument('--settings-source', type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument('--survey-index', type=Path, default=Path('F:/FSRD/sol_batch/15d-guides/index.json'))
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    output = safe_output(args.output)
    output.mkdir(parents=True, exist_ok=True)
    before = file_sha(args.inputs / 'sequence.json')
    require(before == V1_SHA, 'exact sealed V1 source; never regenerate the old oracle')
    replay = source_module(args.replay_source, '_radiance_actual_root_replay')
    manifest = replay.validate(args.inputs)
    require(manifest['submitted_frames'] == 64 and manifest['seed'] == 22945830, 'exact sealed64 samples and seed')
    settings, text = sealed_settings(args.settings_source)
    quantiles = published_quantiles(args.replay_source.parent.parent / 'fsrd_nrd_survey_dataset.py', args.survey_index)
    write_json(output / 'published-recon-quantiles.json', quantiles)
    prepared = prepare_views(replay, args.inputs, manifest, output / 'views')
    require(file_sha(args.inputs / 'sequence.json') == before, 'sealed V1 manifest unchanged after preparation')
    replay.validate(args.inputs)
    result = dict(schema='fsrd-radiance-domain-experiment-v1', input_manifest_sha256=before,
        submitted_frames=64, source_v1_written=False, scales=list(SCALES), prepared_views=prepared,
        settings=settings, published_quantiles=str(output / 'published-recon-quantiles.json'),
        replay_python_sha256=file_sha(args.replay_source),
        oracle_sha256=file_sha(args.replay_source.with_name('fsrd_nrd_motion_quality_oracle.py')),
        actual_rr_cpp_sha256=file_sha(args.replay_source.with_suffix('.cpp')),
        compiler_executed=False, gpu_executed=False, native_nrd_paired=False, game_fps_measured=False,
        hypothesis='Absolute NN radiance-domain sensitivity, not evidence that native Consumer64 belongs before RR')
    if args.run:
        result.update(run_gpu(replay, args.inputs, manifest, prepared, output, settings, text))
        require(file_sha(args.inputs / 'sequence.json') == before, 'V1 manifest unchanged after every actual RR run')
        replay.validate(args.inputs)
        result.update(compiler_executed=True, gpu_executed=True)
    result.update(python_checks=CHECKS, root_replay_python_checks=replay.CHECKS)
    write_json(output / ('comparison.json' if args.run else 'prepared.json'), result)
    print(json.dumps(dict(output=str(output), checks=CHECKS, replay_checks=replay.CHECKS,
        scales=list(SCALES), prepared_histories=len(prepared), gpu_executed=args.run,
        summaries=result.get('comparison', {}).get('summaries')), indent=2))


if __name__ == '__main__':
    main()
