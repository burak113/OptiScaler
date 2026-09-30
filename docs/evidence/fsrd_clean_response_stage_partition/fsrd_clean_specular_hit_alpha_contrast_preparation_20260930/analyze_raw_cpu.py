"""Frozen descriptive all-six-pair raw reader. No SDK/GPU/model or quality score."""
from pathlib import Path
import argparse,hashlib,itertools,json,sys
sys.dont_write_bytecode=True
import numpy as np
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metrics(a,b):
    aa=a.view('<u2');bb=b.view('<u2');d=a[...,:3].astype('f8')-b[...,:3].astype('f8')
    return dict(RGBA_bits_exact=bool(np.array_equal(aa,bb)),RGB_bits_exact=bool(np.array_equal(aa[...,:3],bb[...,:3])),
        alpha_bits_exact=bool(np.array_equal(aa[...,3],bb[...,3])),RGB_RMS=float(np.sqrt(np.mean(d*d))),
        RGB_max_abs=float(np.max(abs(d))),RGB_per_source_frame_RMS=np.sqrt(np.mean(d*d,axis=(1,2,3))).tolist(),
        RGB_per_source_frame_bits_exact=[bool(np.array_equal(x,y))for x,y in zip(aa[...,:3],bb[...,:3])])
def main():
    p=argparse.ArgumentParser();p.add_argument('--analyze-raw',action='store_true',required=True);p.parse_args()
    reg=json.loads((HERE/'registration.json').read_text());run=json.loads((HERE/'execution_results.json').read_text());target=HERE/'raw_comparisons.json'
    assert run['status']=='completed_specular_alpha_native_raw_only_not_composed_not_quality_accepted'and run['accepted_contexts']==4 and not target.exists()
    actual={r['tag']:r for r in run['jobs']};outputs={}
    for c in reg['cases']:
        f=Path(c['job']).parent;assert actual[c['tag']]['accepted'];outputs[c['tag']]={}
        assert(f/'dispatch_controls.bin').read_bytes()==(f/'expected_applied_dispatch_controls.bin').read_bytes()
        for n in('diffuse.bin','specular.bin'):
            assert sha(f/n)==actual[c['tag']]['outputs'][n]['sha256'];outputs[c['tag']][n]=np.fromfile(f/n,'<f2').reshape(64,80,128,4)
    doses={c['tag']:c['specular_input_A']for c in reg['cases']};pairs=[]
    for a,b in itertools.combinations(reg['fixed_order'],2):
        pairs.append(dict(left=a,right=b,kind='within_dose_repeat'if doses[a]==doses[b]else'between_dose',
            same_actual_controls184=True,lobes={n:metrics(outputs[a][n],outputs[b][n])for n in('diffuse.bin','specular.bin')}))
    result=dict(schema='four-context-alpha-contrast-raw-descriptive-only',execution_sha256=sha(HERE/'execution_results.json'),source_frame_indices=list(range(64)),pairs=pairs,
        pair_count=6,lobe_comparison_count=12,quality_scores=None,composition_results=None,quality_accepted=False,new_native_GPU=0,
        limits='A10 is a view-depth proxy, not traced ray length. Separate within-dose repeats from conditional between-dose sensitivity. OutputA storage descriptive only. Native RGB is demodulated, not composed truth; no private mechanism, API violation, quality or game-cause inference.')
    with target.open('x',encoding='utf-8',newline='\n')as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
