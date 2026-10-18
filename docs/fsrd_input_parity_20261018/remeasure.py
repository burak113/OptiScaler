"""Apply one frozen, camera-aligned measurement to every saved candidate."""
import json
import sys
import numpy as np
from parity_replay import Cap, WORK, OUT, metrics

for cid in sys.argv[1:]:
    c=Cap(cid)
    fr=list(range(34,c.n)) if cid.startswith('f2ef') else list(range(c.n-24,c.n))
    p=OUT/f'{cid}_results.json'
    rows=json.loads(p.read_text())
    # Discover saved arrays as well: metadata writers may have run at different times.
    variants=sorted(set(rows)|{x.name[len(cid)+1:-6] for x in WORK.glob(cid+'_*_d.npy')})
    for v in variants:
        rows.setdefault(v,{})
        own=OUT/f'{cid}_{v}.json'
        if own.exists():
            rows[v].update(json.loads(own.read_text()))
        dp=WORK/f'{cid}_{v}_d.npy'; sp=WORK/f'{cid}_{v}_s.npy'
        if not dp.exists() or not sp.exists():
            continue
        d,s=np.load(dp,mmap_mode='r'),np.load(sp,mmap_mode='r')
        rows[v]['aligned_metrics']=metrics(c,d,s,fr)
        m=rows[v]['aligned_metrics']
        print(cid,v,'cv90',round(m['cv_p90'],5),'chroma90',round(m['chroma_std_p90'],5),
              'level',round(m['mean_luma'],7),'detail',round(m['mean_detail'],8),flush=True)
    p.write_text(json.dumps(rows,indent=2))
