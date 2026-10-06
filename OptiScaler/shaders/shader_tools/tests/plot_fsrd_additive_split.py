"""Plot actual saved independent truth and AMD outputs, with fixed error scales."""
from pathlib import Path
import argparse
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont

LUMA = np.array([.2126, .7152, .0722], np.float32)


def render(roots, destination, error_scale=.04):
    cell_w, cell_h = 320, 224
    rows = []
    for root in roots:
        report = json.loads((root/'results.json').read_text())
        for scene in ('fake_island', 'material_additive'):
            for floor in (False, True):
                matches = [r for r in report['results'] if r['scene']==scene and r['floor']==floor]
                if not any(r['strength']==1 for r in matches):
                    continue
                base = next(r for r in matches if r['variant']=='baseline')
                alpha = next(r for r in matches if r['strength']==1)
                truth = np.load(root/(scene+'_truth.npz'))['clean']
                state = 'on' if floor else 'off'
                baseline = np.load(root/(scene+'_floor_'+state+'_baseline')/'preview.npz')['mean']
                candidate = np.load(root/(scene+'_floor_'+state+'_alpha1.0')/'preview.npz')['mean']
                rows.append((scene, state, truth, baseline, candidate, base, alpha))
    if not rows:
        raise ValueError('No completed baseline/alpha1 comparison')
    font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 14)
    title_font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 17)
    stride = cell_h+70
    canvas = Image.new('RGB', (5*cell_w, len(rows)*stride+85), (22, 25, 30))
    draw = ImageDraw.Draw(canvas)
    def tone(a):
        return np.rint(np.clip(a, 0, 1)**(1/2.2)*255).astype('u1')
    def signed(e):
        q = np.clip(e/error_scale, -1, 1)
        neutral = np.full((*q.shape, 3), .5)
        neutral[..., 0] += .5*q
        neutral[..., 2] -= .5*q
        neutral[..., 1] -= .30*abs(q)
        return np.rint(np.clip(neutral, 0, 1)*255).astype('u1')
    for row, (scene, floor, truth, baseline, candidate, base, alpha) in enumerate(rows):
        top = row*stride
        draw.text((8, top+2), f'{scene} | Floor {floor} | {base["metrics"]["target_rmse"]:.6f} -> {alpha["metrics"]["target_rmse"]:.6f} RGB RMSE', font=title_font, fill='white')
        panels = [('Independent clean truth', tone(truth)), ('Frozen base mean', tone(baseline)),
                  ('Alpha strength 1 mean', tone(candidate)),
                  ('Base signed luma error', signed((baseline-truth)@LUMA)),
                  ('Alpha signed luma error', signed((candidate-truth)@LUMA))]
        for col, (label, pixels) in enumerate(panels):
            left = col*cell_w
            draw.text((left+7, top+27), label, font=font, fill=(210, 215, 224))
            image = Image.fromarray(pixels).resize((cell_w-6, cell_h), Image.Resampling.NEAREST)
            canvas.paste(image, (left+3, top+47))
    bottom = len(rows)*stride
    draw.text((8, bottom+5), 'All RGB views: same exposure, gamma 2.2, no per-panel rescaling. Means use the reported score window.', font=font, fill='white')
    draw.text((8, bottom+28), f'Error maps: fixed linear luma range -{error_scale:g} (blue), 0 (gray), +{error_scale:g} (red), clipped at endpoints.', font=font, fill='white')
    draw.text((8, bottom+51), 'Controlled synthetic evidence. A better global RMSE can coexist with increased low-frequency error or RGB bias.', font=font, fill=(220, 195, 150))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--reports', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--error-scale', type=float, default=.04)
    args = parser.parse_args()
    render(args.reports, args.output, args.error_scale)
