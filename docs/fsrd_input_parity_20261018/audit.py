"""Inspect live capture contracts before designing any provider experiment."""
import json
import sys
from pathlib import Path
import numpy as np

ROOT = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE')
for short in sys.argv[1:]:
    paths = sorted(ROOT.glob(short + '*'))
    if not paths:
        print(short, 'MISSING')
        continue
    path = paths[0]
    j = json.loads((path / 'capture.json').read_text())
    print('\nCAP', path.name, 'published', j.get('manifest_published_frames'),
          'roi', j.get('roi'), 'render', j.get('render_extent'))
    print('keys', list(j))
    fr = j['frames'][0]
    print('frame keys', list(fr))
    for key in ('settings', 'provider', 'provider_contract', 'provider_dispatch', 'actual_reset'):
        if key in fr:
            print(key, json.dumps(fr[key])[:1400])
    names = {im['name']: im for im in fr['images']}
    print('images', list(names))
    h, w = j['roi']['extent'][1], j['roi']['extent'][0]
    for name in ('input_specular_albedo', 'input_diffuse_albedo', 'input_specular',
                 'input_diffuse', 'specAlbedo', 'diffAlbedo', 'spec', 'diff'):
        if name not in names:
            continue
        im = names[name]
        data = (path / im['file']).read_bytes()
        if len(data) == h * w * 4:
            a = np.frombuffer(data, np.uint8).reshape(h, w, 4).astype(np.float32) / 255
        elif len(data) == h * w * 8:
            a = np.frombuffer(data, np.float16).reshape(h, w, 4).astype(np.float32)
        else:
            print(name, 'bytes', len(data))
            continue
        print(name, 'p0/50/90/99/100', np.quantile(a[..., :3], [0,.5,.9,.99,1]).round(7),
              'white', float(np.all(a[..., :3] == 1, -1).mean()))
