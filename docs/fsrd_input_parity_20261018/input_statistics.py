"""Bounded raw-input sampling; statistics do not label every zero as a missing sample."""
import json
import numpy as np
from parity_replay import Cap, LUMA, OUT

rows = {}
for cid in ('f2ef375f', 'd6d2a083', '06fadf38'):
    c = Cap(cid)
    rows[cid] = {}
    for name in ('input_diffuse', 'input_specular'):
        a = np.concatenate([(c.img(i, name)[..., :3] @ LUMA).ravel()[::16]
                            for i in range(0, c.n, 2)])
        rows[cid][name] = {
            'sample_count': len(a), 'zero_fraction': float((a == 0).mean()),
            'negative_fraction': float((a < 0).mean()),
            'quantiles': dict(zip(('p50', 'p90', 'p99', 'p999', 'max'),
                                 map(float, np.quantile(a, [.5, .9, .99, .999, 1]))))}
(OUT / 'input_luminance_statistics.json').write_text(json.dumps(rows, indent=2))
print(json.dumps(rows, indent=2))
