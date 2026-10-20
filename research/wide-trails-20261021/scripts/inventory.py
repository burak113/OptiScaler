import sys,json
from pathlib import Path
sys.path.insert(0,'E:/FSRD/rrlab')
from rrlab.captures import Capture
records=[]
for prefix in ['c37d3609','87ee','22f9','2405','d6d2','f2ef','06fad']:
 c=Capture(prefix);s=c.frames[0]['settings'];seg=c.segments()
 r=dict(id=c.id,frames=c.n,roi=[c.W,c.H],names=sorted(c.names),turn=s.get('turn_colour'),anchor=s.get('post_motion_anchor'),tuning=c.requested_tuning(),segments=seg['runs'],fast=[i for i,x in enumerate(seg['rot']) if x>3])
 records.append(r)
 print(c.id,c.n,seg['runs'],'fast',r['fast'],'turn',r['turn'],flush=True)
Path(__file__).with_name('inventory.json').write_text(json.dumps(records,indent=2))
