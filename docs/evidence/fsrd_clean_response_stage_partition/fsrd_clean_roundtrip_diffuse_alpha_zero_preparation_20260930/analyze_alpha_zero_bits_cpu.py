"""Future saved raw-buffer bit comparisons only; no launcher, scores or64-series."""
from pathlib import Path
import argparse,hashlib,itertools,json
import numpy as np
HERE=Path(__file__).resolve().parent
def rec(p):
 p=Path(p);return dict(path=str(p.resolve()),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def main():
 p=argparse.ArgumentParser();p.add_argument('--analyze-alpha-zero-bits',action='store_true',required=True);p.parse_args()
 target=HERE/'alpha_zero_comparison.json';assert not target.exists(),'Preserve previous comparison'
 reg=json.loads((HERE/'registration.json').read_text());run=json.loads((HERE/'execution_results.json').read_text())
 assert run['status']=='completed_alpha_zero_only_awaiting_independent_review_not_quality_accepted'
 assert run['completed_accepted_jobs']==run['exact_helper_total']==run['exact_shader_dispatch_total']==2
 buffers={};records={}
 for job in reg['jobs']+reg['prior_R_outputs']:
  arm=job['arm'];buffers[arm]=[];records[arm]=[]
  for i,o in enumerate(job['outputs']):
   r=rec(o['path']);assert r['bytes']==o['bytes']
   if arm in ('R0','R1'):assert r['sha256']==o['sha256']
   records[arm].append(r);buffers[arm].append(np.fromfile(o['path'],'<u2'if i<2 else'<u4').reshape(80,128,4))
 pairs=[]
 for a,b in itertools.combinations(('RZ0','RZ1','R0','R1'),2):
  outs=[]
  for i in range(3):
   x,y=buffers[a][i],buffers[b][i]
   outs.append(dict(slot=i,format=10 if i<2 else 3,full_RGBA_serialized_bits_exact=bool(np.array_equal(x,y)),RGB_bits_exact=bool(np.array_equal(x[...,:3],y[...,:3])),alpha_bits_exact=bool(np.array_equal(x[...,3],y[...,3])),differing_channel_elements=int(np.count_nonzero(x!=y))))
  pairs.append(dict(arms=[a,b],outputs=outs))
 report=dict(status='COMPLETED_SAVED_BITS_ONLY_ALPHA_CONTROL_NOT_QUALITY_ACCEPTED',actual_new_helper_observations=2,prior_R_actual_observations=2,static_graphs=1,new_SDK_API=0,new_scores=0,output_records=records,pairs=pairs,
  color_RGB_alpha_caveat_closed_for_this_graph=all(p['outputs'][0]['RGB_bits_exact']for p in pairs),
  no_64_measured_series=True,quality_accepted=False,game_run=False,limits=reg['limitations'])
 with target.open('x',encoding='utf-8',newline='\n')as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
