"""Check which native NRD stages actually exist in captured RR-on frames."""
import json
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, 'F:/OptiRevelations/OSA-11-frame-survey/tools/fsrd_frame_survey')
from survey import Survey
ROOT=Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE/FRAME_SURVEY')
ROLES={'3e09f2e0':'material','87d570aa':'prep','ec37e0d8':'recon','442e2282':'prepass',
       'bedaacc6':'temporal','c3f6fb8e':'consumer'}
for cid in sys.argv[1:]:
    c=Survey(next(ROOT.glob(cid+'*')))
    print('\nSURVEY',c.folder.name,'resources',len(c.resources),'snapshots',len(c.snapshots),
          'passes',len(c.passes),'extent',c.extent,flush=True)
    found=Counter()
    for p in c.passes:
        hashes=p.get('pso',{}).get('shader_hashes',{})
        for hash in hashes.values():
            if hash[:8] in ROLES:
                found[ROLES[hash[:8]]]+=1
                print(ROLES[hash[:8]],'list',p['list_id'],'pass',p['local_pass'],
                      'reads',[v['resource'] for v in p.get('reads',[])],
                      'writes',[v['resource'] for v in p.get('writes',[])])
    print('roles',dict(found))
    # All RGBA16F render-size intermediates and their potential producers/consumers.
    for rid,r in c.resources.items():
        if r.get('format')!=10 or (r.get('width'),r.get('height'))!=tuple(c.extent):
            continue
        writers=[]; readers=[]
        for p in c.passes:
            sh=p.get('pso',{}).get('shader_hashes',{})
            hashes=','.join(v[:8] for v in sh.values())
            if any(v['resource']==rid for v in p.get('writes',[])):
                writers.append(f"{p['list_id']}:{p['local_pass']}:{hashes}")
            if any(v['resource']==rid for v in p.get('reads',[])):
                readers.append(f"{p['list_id']}:{p['local_pass']}:{hashes}")
        print('rgba16',rid,'writers',writers,'readers',readers[:12],flush=True)
