import json
from pathlib import Path
import numpy as np
O=Path(__file__).parent
report={}
for filename,names in [('normalize-steps.json',[('step_down','down_endpoint'),('step_small','small_endpoint'),('chroma','chroma_endpoint')]),('guard-steps.json',[('down','down_endpoint'),('small','small_endpoint'),('chroma','chroma_endpoint'),('local','local_endpoint')]),('gain-steps.json',[('down','down_endpoint'),('small','small_endpoint'),('chroma','chroma_endpoint'),('local','local_endpoint')])]:
 p=O/filename
 if not p.exists():continue
 data=json.loads(p.read_text());rows=[]
 for label,endpoint in names:
  if label not in data or endpoint not in data:continue
  for variant in data[label]:
   old=data['control'][variant];step=data[label][variant];ref=data[endpoint][variant]
   if isinstance(old,dict):
    region='inside' if label=='local' else 'all';old,step,ref=[a[region] for a in [old,step,ref]]
   old,step,ref=[np.asarray(a) for a in [old,step,ref]]
   distance=abs(old-ref).mean(-1);relative=abs(step-ref).mean(-1)/np.maximum(distance,1e-8)
   rows.append({'case':label,'variant':variant,'remaining_at16':float(relative[64]),'remaining_at64':float(relative[112]),'mean_remaining_first32':float(relative[48:80].mean())})
 report[filename]=rows
 if filename in ('gain-steps.json','guard-steps.json') and 'local' in data:
  for variant in ['old','gain']:
   control=np.asarray(data['control'][variant]['outside']);local=np.asarray(data['local'][variant]['outside'])
   rows.append({'case':'local_outside_unchanged','variant':variant,'mean_relative_change':float(abs(local[48:]-control[48:]).sum()/abs(control[48:]).sum()),'max_frame_relative_change':float((abs(local[48:]-control[48:]).sum(-1)/abs(control[48:]).sum(-1)).max())})
(O/'step-summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
