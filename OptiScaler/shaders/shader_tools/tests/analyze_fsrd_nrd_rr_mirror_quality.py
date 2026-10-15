"""CPU-only fixed-display V4 signed-RR previews and reset/tail diagnostics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from analyze_fsrd_nrd_rr_material_quality import display
import fsrd_nrd_rr_material_quality as sealed
import fsrd_nrd_rr_mirror_oracle as mirror


FRAMES = (2, 17, 33, 49, 65)
COLUMNS = ('reference', 'noisy_input') + mirror.CANDIDATES


def run(prepared, completed, output):
    manifest = json.loads((prepared / 'mirror-sequence.json').read_bytes())
    result = json.loads((completed / 'comparison.json').read_bytes())
    runs = json.loads((completed / 'runs.json').read_bytes())
    expected = sealed.file_sha(prepared / 'mirror-sequence.json')
    mirror.need(runs['prepared_manifest_sha256'] == result['prepared_manifest_sha256'] == expected,
                'previews and metrics use exact sealed completed V4')
    mirror.need(tuple(runs['runs']) == mirror.CANDIDATES, 'no worse comparison row omitted')
    output.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in result.items() if key not in ('frames', 'native_runs')}
    summary['source_comparison_sha256'] = sealed.file_sha(completed / 'comparison.json')
    summary['native_terminal'] = {}
    for candidate, native in [('defaults-probe', runs['probe']), *runs['runs'].items()]:
        times = [frame['gpu_rr_commit_ms'] for frame in native['frames']]
        summary['native_terminal'][candidate] = {key: value for key, value in native.items() if key not in ('frames', 'outputs')}
        summary['native_terminal'][candidate]['gpu_rr_commit_ms'] = dict(mean=statistics.mean(times), median=statistics.median(times), all_samples=times)
    summary['first_reset_input_rgb_identity'] = {}
    summary['previews'] = {}
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 17)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    x, y, width, height = manifest['comparison_crop']
    tile_width, tile_height = width * 2, height * 2
    header, row_label, gap, footer = 102, 66, 12, 44
    canvases = {signal: Image.new('RGB', (row_label + len(COLUMNS) * (tile_width + gap),
        header + len(FRAMES) * (tile_height + 22) + footer), '#181818') for signal in ('spec', 'diff')}
    for signal, image in canvases.items():
        pen = ImageDraw.Draw(image)
        pen.text((12, 10), f'V4 coherent ideal mirror: {signal}; signed AMD1.2, no native NRD/game pair', font=font, fill='white')
        pen.text((12, 35), 'All columns exposure4, 1-exp(-4*linear), sRGB; same96px crop/nearest2x', font=small, fill='#cccccc')
        pen.text((12, 56), 'R.12 is a deliberate mirror-model mismatch. ReflectedMV is a nonproduction diagnostic.', font=small, fill='#cccccc')
        for column, name in enumerate(COLUMNS):
            pen.text((row_label + column * (tile_width + gap), 80), name, font=small, fill='white')
    for row, number in enumerate(FRAMES):
        frame = next(item for item in manifest['frames'] if item['frame'] == number)
        folder = prepared / 'dataset' / frame['directory']
        lights = dict(reference={signal: sealed.load(folder, frame['payloads']['reference_' + signal]) for signal in ('spec', 'diff')},
                      noisy_input={signal: sealed.load(folder, frame['payloads'][signal])[..., :3] for signal in ('spec', 'diff')})
        for candidate, native in runs['runs'].items():
            lights[candidate] = {}
            for signal in ('spec', 'diff'):
                path = completed / candidate / frame['directory'] / (signal + '.bin')
                mirror.need(sealed.file_sha(path) == native['outputs'][str(number)][signal], 'actual signed output SHA for preview')
                values = np.fromfile(path, '<f2').reshape(128, 128, 4)
                mirror.need(np.isfinite(values).all(), 'all preview output RGBA finite')
                lights[candidate][signal] = values[..., :3]
                if number == 2:
                    a = np.ascontiguousarray(values[..., :3]).view('<u2')
                    b = np.ascontiguousarray(lights['noisy_input'][signal]).view('<u2')
                    summary['first_reset_input_rgb_identity'].setdefault(candidate, {})[signal] = dict(
                        total_rgb_words=int(a.size), equal_rgb_words=int(np.count_nonzero(a == b)),
                        max_abs_rgb_delta=float(np.max(np.abs(values[..., :3].astype(np.float64) - lights['noisy_input'][signal].astype(np.float64)))))
        for signal, image in canvases.items():
            top = header + row * (tile_height + 22)
            ImageDraw.Draw(image).text((8, top + 4), f'F{number}', font=font, fill='white')
            for column, candidate in enumerate(COLUMNS):
                rgb = display(lights[candidate][signal][y:y + height, x:x + width], 4.)
                image.paste(Image.fromarray(rgb).resize((tile_width, tile_height), Image.Resampling.NEAREST),
                            (row_label + column * (tile_width + gap), top))
    for signal, image in canvases.items():
        ImageDraw.Draw(image).text((12, image.height - 35), 'Exact nearest-hit point sample; no rough-GGX or pixel-area-filtered truth. Same camera, noise and lighting in all views.', font=small, fill='#cccccc')
        path = output / ('mirror-v4-' + signal + '.png')
        image.save(path)
        summary['previews'][signal] = dict(file=str(path), sha256=sealed.file_sha(path), bytes=path.stat().st_size,
            frames=list(FRAMES), crop=manifest['comparison_crop'], exposure=4., tonemap='1-exp(-4*linear) then sRGB', interpolation='nearest2x')
    summary['analysis_checks'] = mirror.CHECKS
    sealed.write_json(output / 'mirror-v4-analysis.json', summary)
    print(json.dumps(dict(checks=mirror.CHECKS, first_reset_input_rgb_identity=summary['first_reset_input_rgb_identity'],
        previews=summary['previews'], output=str(output / 'mirror-v4-analysis.json'), gpu_executed=False, compiler_executed=False), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, default=mirror.BASE / 'mirror-v4')
    parser.add_argument('--completed', type=Path, default=mirror.BASE / 'mirror-v4-rr-run1')
    parser.add_argument('--output', type=Path, default=Path('E:/FSRD/sol_batch/15c-rr/mirror-analysis'))
    args = parser.parse_args()
    run(args.prepared, args.completed, args.output)


if __name__ == '__main__':
    main()
