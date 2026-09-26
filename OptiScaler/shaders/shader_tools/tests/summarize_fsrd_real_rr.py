"""Audit recorded real-RR experiments and render reproducible comparison artifacts."""
from pathlib import Path
import argparse
import csv
import json
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def load(root):
    data = json.loads((root / 'results.json').read_text(encoding='utf-8'))
    for row in data['results']:
        row['root'] = root
        log = (root / row['name'] / 'runner.log').read_text(encoding='utf-8')
        assert re.search(rf'dispatches={data["frames"]} validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0', log), row['name']
        assert row['metrics']['finite'], row['name']
        output = root / row['name'] / ('output_diff.bin' if row['case']['signal'] in ('dd', 'id') else 'output_spec.bin')
        assert output.stat().st_size == data['frames'] * np.prod(data['dimensions']) * 8
        if row['case'].get('passthrough'):
            assert row['metrics']['raw_unchanged_fraction'] == 1
            assert row['metrics']['raw_change_rms'] == 0
    return data


def pick(data, **kwargs):
    matches = [r for r in data['results'] if all(r['case'].get(k) == v for k, v in kwargs.items())]
    assert len(matches) == 1, (kwargs, len(matches))
    return matches[0]


def main():
    p = argparse.ArgumentParser()
    for name in ('full', 'causal', 'adversarial', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    assert args.output.resolve().drive.upper() == 'F:'
    args.output.mkdir(parents=True, exist_ok=True)
    full, causal, adversarial = [load(getattr(args, n)) for n in ('full', 'causal', 'adversarial')]
    assert [len(d['results']) for d in (full, causal, adversarial)] == [58, 40, 14], 'Incomplete experiment suite'
    assert len({d['dll_sha256'] for d in (full, causal, adversarial)}) == 1
    assert len({d['frames'] for d in (full, causal, adversarial)}) == 1
    allrows = full['results'] + causal['results'] + adversarial['results']
    # Controls check actual RR behaviour, not a CPU approximation of its algorithm.
    flat = pick(full, signal='dd', path='demod', albedo='flat', roughness=.1, motion='static')
    oracle = pick(full, signal='dd', path='demod', albedo='pattern', roughness=.1, motion='static')
    assert flat['metrics']['raw_change_rms'] > .01
    assert flat['metrics']['quiet_error_ratio'] < .2
    assert oracle['metrics']['structure_contrast_ratio'] > .95
    assert oracle['metrics']['quiet_error_ratio'] < .1
    assert oracle['metrics']['structure_contrast_ratio'] > flat['metrics']['structure_contrast_ratio'] + .3
    for signal in ('dd', 'is'):
        row = pick(causal, signal=signal, roughness=0., reset=True)
        assert row['metrics']['raw_unchanged_fraction'] == 1
        low = pick(causal, signal=signal, roughness=1/1023)
        high = pick(causal, signal=signal, roughness=2/1023)
        assert low['metrics']['structure_contrast_ratio'] > high['metrics']['structure_contrast_ratio'] + .3
    fields = ['name', 'signal', 'path', 'albedo', 'roughness', 'motion', 'noise', 'seed', 'reset', 'passthrough', 'hit',
              'quiet_error_ratio', 'quiet_temporal_std_ratio', 'structure_contrast_ratio',
              'output_rmse', 'mean_structure_rmse', 'raw_change_rms', 'raw_unchanged_fraction', 'case_json']
    with (args.output / 'measurements.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in allrows:
            values = dict(name=r['root'].name + '/' + r['name'], **r['case'], **r['metrics'], case_json=json.dumps(r['case']))
            writer.writerow({k: values.get(k, '') for k in fields})
    noisy = pick(adversarial, signal='dd', albedo='noisy', motion='static')
    guide = pick(full, signal='dd', path='guide', albedo='pattern', roughness=.1, motion='static')
    ref = np.load(oracle['root'] / oracle['name'] / 'preview.npz')
    panels = [('Temiz hedef (bilinen sentetik desen)', ref['clean']),
              ('Gürültülü girdi / aynı örnekler', ref['noisy'])]
    for title, row in [('Desen yalnız albedo rehberinde', guide),
                       ('Düz albedo + bölme / geri çarpma', flat),
                       ('Temiz desen + bölme / geri çarpma', oracle),
                       ('Gürültülü sahte albedo + bölme / geri çarpma', noisy)]:
        panels.append((title, np.load(row['root'] / row['name'] / 'preview.npz')['result']))
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 20)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 18)
    tile_w, tile_h = 536, 434
    sheet = Image.new('RGB', (tile_w * 3, tile_h * 2 + 104), '#111923')
    draw = ImageDraw.Draw(sheet)
    for i, (title, linear) in enumerate(panels):
        x, y = (i % 3) * tile_w + 12, (i // 3) * tile_h + 12
        draw.text((x, y), title, font=font, fill='white')
        # One identical linear-to-sRGB display transform for all panels. No sharpening.
        a = np.clip(linear, 0, 1)
        a = np.where(a <= .0031308, 12.92 * a, 1.055 * np.power(a, 1/2.4) - .055)
        im = Image.fromarray(np.round(a * 255).astype('uint8')).resize((512, 384), Image.Resampling.NEAREST)
        sheet.paste(im, (x, y + 34))
    frames = full['frames']
    draw.text((12, tile_h * 2 + 8), f'Gerçek AMD RR · roughness=0.1 · direct diffuse · {frames}. kare · Floor kapalı', font=font, fill='white')
    draw.text((12, tile_h * 2 + 40), '256×192 girdi, 2× nearest gösterim. Temiz desenli albedo bir üst sınır kontrolüdür; oyundan elde edilmiş değildir.', font=small, fill='#b8cbdc')
    draw.text((12, tile_h * 2 + 67), f'Metrikler {frames//2+1}–{frames}. karelerin lineer HDR verisinden; yalnız bu önizleme sRGB ve [0,1] kırpılmıştır.', font=small, fill='#b8cbdc')
    sheet.save(args.output / 'comparison.png')
    summary = dict(cases=len(allrows), dispatches=sum(d['frames'] * len(d['results']) for d in (full, causal, adversarial)),
                   dimensions=full['dimensions'], frames=full['frames'], dll_sha256=full['dll_sha256'],
                   d3d_errors=0, d3d_warnings=0, sdk_errors=0, sdk_warnings=0, audit='passed')
    (args.output / 'audit.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
