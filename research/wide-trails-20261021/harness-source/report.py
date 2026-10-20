"""Static HTML viewers (open in any browser, no server): reports/<name>/index.html, reports/index.html,
reports/captures.html.

build(name, capture, variants, frames=None, window=None, extras=('input', 'game')) runs (cached) every variant,
writes lossless WebP frames at ONE exposure for all slots, temporal-CV (boiling) heat maps over `window`, the metric
table with deltas against the first variant, and the camera-motion graph."""
import html
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image
from . import metrics as M
from . import runner
from . import variants as V
from .captures import Capture, list_captures
from .imgutil import LUMA, tonemap, heat
from .paths import REPORTS, CACHE

_TEMPLATE = (Path(__file__).with_name('viewer.html'))


def _webp(arr, path, lossless=True):
    Image.fromarray(arr).save(path, 'WEBP', lossless=lossless, quality=100 if lossless else 92, method=0)


def _exposure(img, mask):
    med = float(np.median((img @ LUMA)[mask])) if mask.any() else 0.05
    return 0.3 / max(med, 1e-6)


def build(name, capture, variants, frames=None, window=None, extras=('input', 'game'), title=None, owner='rrlab', posts=None):
    """posts: optional list of dict(id, label, rgb=[N,H,W,3]) - post-RR candidates (e.g. NZR modes) that
    are not replay variants. They become viewer slots plus window-CV table rows, at the same exposure."""
    c = capture if isinstance(capture, Capture) else Capture(capture)
    frames = list(range(c.n)) if frames is None else list(frames)
    out = REPORTS / name
    (out / 'img').mkdir(parents=True, exist_ok=True)
    results = [runner.run(c, v, frames, owner=owner) for v in variants]
    slots = [dict(id=f'v{k}', label=V.label(v), kind='variant') for k, v in enumerate(variants)]
    arrays = {f'v{k}': r.rgb for k, r in enumerate(results)}
    if 'input' in extras:
        slots.append(dict(id='in', label='RR input (noisy)', kind='input'))
        arrays['in'] = np.stack([c.rgb(t, 'in') for t in frames])
    if 'game' in extras and getattr(c, 'src', None) is None:
        slots.append(dict(id='game', label='game output (selected_rr, after NZR)', kind='game'))
        arrays['game'] = np.stack([c.rgb(t, 'rr') for t in frames])
    post_results = {}
    for item in (posts or []):
        pid = item['id']
        slots.append(dict(id=pid, label=item['label'], kind=item.get('kind', 'post')))
        arrays[pid] = np.asarray(item['rgb'], np.float32)
        post = type('Post', (), {})()
        post.cap, post.frames, post.rgb, post.variant, post.meta = c, list(frames), arrays[pid], 'post', {}
        post_results[pid] = post

    z = np.abs(c.depth(frames[0]))
    valid = (z > 0) & (z < 500)
    reference = arrays['v0'][len(frames) // 2] if results else arrays[next(iter(arrays))][len(frames) // 2]
    exposure = _exposure(reference, valid)
    for sid, a in arrays.items():
        for k, t in enumerate(frames):
            _webp(tonemap(a[k], exposure), out / 'img' / f'{sid}_{t:03d}.webp')

    # boiling window: the longest still run inside the frames, else everything after warm-up
    if window is None:
        runs = [(b - a, a, b) for kind, a, b in c.segments()['runs'] if kind == 'still' and a >= frames[0] and b - 1 <= frames[-1]]
        window = (max(runs)[1], max(runs)[2] - 1) if runs else (frames[min(10, len(frames) - 1)], frames[-1])
    wa, wb = window
    wf = [t for t in frames if wa <= t <= wb]
    ref = wf[len(wf) // 2]
    cv = {}
    for k, r in enumerate(results):
        b = M.boiling(r, ref, wf, flat=False)
        cv[f'v{k}'] = (b['cv_map'], b['mask'])
    for pid, r in post_results.items():
        b = M.boiling(r, ref, wf, flat=False)
        cv[pid] = (b['cv_map'], b['mask'])
    hi = 2.0 * float(np.quantile(cv['v0'][0][cv['v0'][1]], 0.9)) if results and cv['v0'][1].any() else 0.5
    for sid, (m, mk) in cv.items():
        h = heat(np.where(mk, m, 0), hi)
        h[~mk] = (h[~mk] * 0.25).astype(np.uint8)
        _webp(h, out / 'img' / f'{sid}_cv.webp')

    rows = []
    for k, r in enumerate(results):
        ev = M.flatten(M.evaluate(r))
        ev[f'window{wa}-{wb}.p50'] = float(np.median(cv[f'v{k}'][0][cv[f'v{k}'][1]]))
        ev[f'window{wa}-{wb}.p90'] = float(np.quantile(cv[f'v{k}'][0][cv[f'v{k}'][1]], 0.9))
        ev['level'] = M.level(r, wf)
        ev['run_s'] = r.meta.get('seconds')
        rows.append(dict(slot=f'v{k}', label=V.label(variants[k]), metrics=ev, variant=r.variant))
    for pid, r in post_results.items():
        b = M.boiling(r, ref, wf, flat=False)
        rows.append(dict(slot=pid, label=r.meta.get('label', slots[[s['id'] for s in slots].index(pid)]['label']),
                         metrics={'detail': b['detail'], f'window{wa}-{wb}.p50': b['p50'], f'window{wa}-{wb}.p90': b['p90'],
                                  'level': M.level(r, wf)},
                         variant='post'))

    rot, tr = c.motion()
    data = dict(name=name, title=title or f'{c.id}: ' + ' vs '.join(V.label(v) for v in variants),
                capture=c.uuid, capture_id=c.id, frames=frames, size=[c.W, c.H], roi=[c.X0, c.Y0], slots=slots,
                rows=rows, rot=[float(rot[t]) for t in frames], runs=c.segments()['runs'], window=[wa, wb],
                cv_hi=hi, exposure=exposure, created=time.strftime('%Y-%m-%d %H:%M'))
    page = _TEMPLATE.read_text(encoding='utf-8').replace('/*DATA*/null', json.dumps(data))
    (out / 'index.html').write_text(page, encoding='utf-8')
    (out / 'meta.json').write_text(json.dumps({k: data[k] for k in ('name', 'title', 'capture_id', 'created')} |
                                              dict(rows=[dict(label=r['label'], metrics=r['metrics']) for r in rows]), indent=1))
    index()
    return out / 'index.html'


def index():
    items = []
    for m in sorted(REPORTS.glob('*/meta.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        j = json.loads(m.read_text())
        items.append(f'<tr><td><a href="{html.escape(m.parent.name)}/index.html">{html.escape(j["name"])}</a></td>'
                     f'<td>{html.escape(j["capture_id"])}</td><td>{html.escape(j["title"])}</td><td>{j["created"]}</td></tr>')
    page = _PAGE.format(title='RR Lab reports', body=f'<p><a href="captures.html">Capture browser</a></p>'
                        f'<table><tr><th>Report</th><th>Capture</th><th>Variants</th><th>Created</th></tr>{"".join(items)}</table>')
    (REPORTS / 'index.html').write_text(page, encoding='utf-8')


def _thumb(c):
    p = CACHE / 'thumbs' / f'{c.id}.webp'
    if p.exists():
        return p
    p.parent.mkdir(exist_ok=True)
    t = c.n // 2
    if c.kind == 'bridge':
        a = c.rgb(t, 'rr')
    else:
        a = np.frombuffer(c.raw(t, 'current_output'), np.float16)
        if a.size != c.W * c.H * 4:
            return None
        a = a.reshape(c.H, c.W, 4)[..., :3].astype(np.float32)
    img = tonemap(a, _exposure(a, np.isfinite(a).all(-1)))
    im = Image.fromarray(img)
    im.thumbnail((256, 256))
    im.save(p, 'WEBP', quality=85)
    return p


def captures_page():
    idx = list_captures()
    rows = []
    for uuid, e in sorted(idx.items(), key=lambda kv: -kv[1].get('mtime', 0)):
        thumb = ''
        if e['kind'] in ('bridge', 'combined'):
            try:
                tp = _thumb(Capture(uuid))
                thumb = f'<img src="../cache/thumbs/{tp.name}" loading="lazy">' if tp else ''
            except Exception:
                thumb = ''
        runs = ' '.join(f'{k[0]}{a}-{b - 1}' for k, a, b in e.get('runs', []))
        rows.append(f'<tr class="{e["kind"]}"><td>{thumb}</td><td><code>{e["id"]}</code></td><td>{e["kind"]}</td>'
                    f'<td>{e.get("frames", "")}</td><td>{e.get("roi", "")}</td><td>{runs}</td>'
                    f'<td>{e.get("last_fast_turn", "") if e.get("last_fast_turn") is not None else ""}</td>'
                    f'<td>{e.get("max_rot", 0):.2f}</td><td>{e.get("date", "")}</td></tr>')
    body = ('<p>Bridge captures replay through real AMD RR (<code>rrlab.cmd run &lt;id&gt; ...</code>); combined captures '
            'are listed for reference. Runs: s = still, m = moving (frames). Turn = last frame rotating &gt; 3&deg;/frame.</p>'
            '<label><input type="checkbox" id="onlyb" checked> bridge only</label>'
            '<table id="t"><tr><th></th><th>Id</th><th>Kind</th><th>Frames</th><th>ROI x,y,w,h</th><th>Runs</th>'
            f'<th>Turn</th><th>Max &deg;/f</th><th>Date</th></tr>{"".join(rows)}</table>'
            '<script>const f=()=>document.querySelectorAll("#t tr.combined,#t tr.empty,#t tr.error").forEach(r=>'
            'r.style.display=onlyb.checked?"none":"");onlyb.onchange=f;f();</script>')
    (REPORTS / 'captures.html').write_text(_PAGE.format(title='RR Lab captures', body=body), encoding='utf-8')
    return REPORTS / 'captures.html'


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{--bg:#f6f6f4;--fg:#1d1d1b;--mut:#6b6b66;--line:#d9d9d4;--card:#fff;--acc:#1f6feb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#e8e8e4;--mut:#9a9a93;--line:#33332f;--card:#1d1d1b;--acc:#58a6ff}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif;margin:0;padding:16px}}
h1{{font-size:18px;margin:0 0 12px}}a{{color:var(--acc)}}table{{border-collapse:collapse;background:var(--card)}}
td,th{{border-bottom:1px solid var(--line);padding:4px 10px;text-align:left;vertical-align:middle}}
th{{color:var(--mut);font-weight:600}}img{{display:block;max-height:96px;image-rendering:pixelated}}code{{font-size:13px}}
</style></head><body><h1>{title}</h1>{body}</body></html>"""
