"""CPU-only inspection of sealed, already completed signed-RR material runs.

No provider, compiler or GPU code is invoked. Previews use one fixed display
transform per domain; the analytic reference is never a native NRD/game image.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import fsrd_nrd_rr_material_quality as model


SELECTED_FRAMES = (2, 17, 33, 49, 65)
DOMAINS = ('demod_spec', 'remod_spec', 'combined')
DISPLAY_EXPOSURE = dict(demod_spec=4., remod_spec=16., combined=16.)
COLORS = ('reference', 'noisy_input') + model.CANDIDATES


def display(value, exposure):
    value = 1. - np.exp(-np.maximum(np.asarray(value, np.float64), 0.) * exposure)
    encoded = np.where(value <= .0031308, value * 12.92,
                       1.055 * np.power(value, 1. / 2.4) - .055)
    return np.rint(np.clip(encoded, 0., 1.) * 255.).astype('u1')


def domain_value(lights, material, domain):
    if domain == 'demod_spec':
        return lights['spec']
    if domain == 'remod_spec':
        return lights['spec'] * material['qs']
    if domain == 'combined':
        return lights['spec'] * material['qs'] + lights['diff'] * material['qd']
    raise ValueError('unrecognized preview domain')


def read_lights(directory, width, height, expected):
    lights = {}
    for signal in ('spec', 'diff'):
        path = directory / (signal + '.bin')
        model.require(model.file_sha(path) == expected[signal], 'preview output hash matches completed signed run')
        value = np.fromfile(path, '<f2').reshape(height, width, 4)
        model.require(np.isfinite(value).all(), 'preview uses finite actual output including opaque alpha')
        lights[signal] = value[..., :3]
    return lights


def run(prepared, completed, output):
    manifest = json.loads((prepared / 'material-sequence.json').read_bytes())
    comparison = json.loads((completed / 'comparison.json').read_bytes())
    runs = json.loads((completed / 'runs.json').read_bytes())
    expected_manifest = model.file_sha(prepared / 'material-sequence.json')
    model.require(comparison['prepared_manifest_sha256'] == runs['prepared_manifest_sha256'] == expected_manifest,
                  'same sealed material sequence for numerical results and previews')
    model.require(tuple(runs['runs']) == model.CANDIDATES, 'all four candidate rows, including worse rows, remain visible')
    source = Path(manifest['source_directory'])
    v1 = model.original(source)
    width, height = v1['width'], v1['height']
    crop_x, crop_y, crop_width, crop_height = v1['comparison_crop']
    output.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in comparison.items() if key not in ('frames', 'native_runs')}
    summary['source_comparison_sha256'] = model.file_sha(completed / 'comparison.json')
    summary['candidate_vs_white_percent'] = {}
    for candidate in model.CANDIDATES[1:]:
        summary['candidate_vs_white_percent'][candidate] = {}
        for domain, values in comparison['summaries'][candidate].items():
            base = comparison['summaries']['white'][domain]
            summary['candidate_vs_white_percent'][candidate][domain] = {
                key: (values[key] / base[key] - 1.) * 100. for key in
                ('rgb_rmse', 'chroma_rmse', 'detail_gradient_rmse', 'gradient_projection_ratio')}
    summary['native_terminal'] = {}
    for candidate, native in [('defaults-probe', runs['probe']), *runs['runs'].items()]:
        sample = [row['gpu_rr_commit_ms'] for row in native['frames']]
        summary['native_terminal'][candidate] = {
            key: native[key] for key in ('checks', 'creates', 'destroys', 'dispatches',
                'debug_errors', 'debug_warnings', 'elapsed_seconds', 'peak_resident_bytes',
                'owned_staging_bytes', 'owned_auxiliary_bytes', 'effective_words', 'default_words')}
        summary['native_terminal'][candidate]['gpu_rr_commit_ms'] = dict(
            mean=statistics.mean(sample), median=statistics.median(sample), samples=sample)
    summary['gpu_timing_scope'] = ('128x128 real RR plus normal RGB-only commit, first/reset frame included; '
        'no material capture/conversion cost or game FPS measurement')
    summary['previews'] = {}
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 17)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    tile_width, tile_height = crop_width * 2, crop_height * 2
    margin_x, heading, footer, row_label = 12, 92, 44, 66
    canvases = {domain: Image.new('RGB', (row_label + len(COLORS) * (tile_width + margin_x),
        heading + len(SELECTED_FRAMES) * (tile_height + 22) + footer), '#181818') for domain in DOMAINS}
    for domain, image in canvases.items():
        pen = ImageDraw.Draw(image)
        pen.text((12, 10), f'Synthetic 128x128 signed RR: {domain}; no native NRD/game pair', font=font, fill='white')
        pen.text((12, 35), f'All columns: exposure {DISPLAY_EXPOSURE[domain]:g}, 1-exp(-exposure*linear), sRGB; crop96px enlarged2x nearest', font=small, fill='#cccccc')
        for column, name in enumerate(COLORS):
            pen.text((row_label + column * (tile_width + margin_x), 65), name, font=small, fill='white')
    for row, frame_number in enumerate(SELECTED_FRAMES):
        frame = next(item for item in manifest['frames'] if item['frame'] == frame_number)
        folder = source / frame['directory']
        payload = frame['source_payloads']
        materials = {name: model.load(prepared / 'dataset' / frame['directory'], info)
                     for name, info in frame['derived'].items() if name in ('qd', 'qs')}
        lights = dict(reference={signal: model.load(folder, payload['reference_' + signal]) for signal in ('spec', 'diff')},
                      noisy_input={signal: model.load(folder, payload[signal])[..., :3] for signal in ('spec', 'diff')})
        for candidate, native in runs['runs'].items():
            lights[candidate] = read_lights(completed / candidate / frame['directory'], width, height,
                                           native['outputs'][str(frame_number)])
        for domain, image in canvases.items():
            top = heading + row * (tile_height + 22)
            ImageDraw.Draw(image).text((8, top + 4), f'F{frame_number}', font=font, fill='white')
            for column, candidate in enumerate(COLORS):
                value = domain_value(lights[candidate], materials, domain)
                rgb = display(value[crop_y:crop_y + crop_height, crop_x:crop_x + crop_width], DISPLAY_EXPOSURE[domain])
                tile = Image.fromarray(rgb).resize((tile_width, tile_height), Image.Resampling.NEAREST)
                image.paste(tile, (row_label + column * (tile_width + margin_x), top))
    for domain, image in canvases.items():
        pen = ImageDraw.Draw(image)
        pen.text((12, image.height - 35), 'Analytic prescribed point-sampled lighting; fixed frames2/17/33/49/65. Material edges are not proof of restored light detail.', font=small, fill='#cccccc')
        path = output / ('material-' + domain + '.png')
        image.save(path)
        summary['previews'][domain] = dict(file=str(path), bytes=path.stat().st_size,
            sha256=model.file_sha(path), frames=list(SELECTED_FRAMES), exposure=DISPLAY_EXPOSURE[domain],
            crop=v1['comparison_crop'], interpolation='nearest2x', native_nrd_paired=False)
    summary['analysis_checks'] = model.CHECKS
    model.write_json(output / 'material-analysis.json', summary)
    print(json.dumps(dict(checks=model.CHECKS, previews=summary['previews'],
        summary=str(output / 'material-analysis.json'), compiler_executed=False, gpu_executed=False), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, default=Path('F:/FSRD/sol_batch/15c-rr/material-v2'))
    parser.add_argument('--completed', type=Path, default=Path('F:/FSRD/sol_batch/15c-rr/material-v2-rr-root-run1'))
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/material-analysis'))
    args = parser.parse_args()
    run(args.prepared, args.completed, args.output)


if __name__ == '__main__':
    main()
