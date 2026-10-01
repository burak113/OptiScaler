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
    assert run['status']=='completed_fork_versus_defaults_native_raw_only_not_composed_not_quality_accepted'and run['accepted_contexts']==4 and not target.exists()
    actual={r['tag']:r for r in run['jobs']};outputs={}
    for c in reg['cases']:
        f=Path(c['job']).parent;assert actual[c['tag']]['accepted'];outputs[c['tag']]={}
        assert(f/'dispatch_controls.bin').read_bytes()==(f/'expected_applied_dispatch_controls.bin').read_bytes()
        for n in('diffuse.bin','specular.bin'):
            assert sha(f/n)==actual[c['tag']]['outputs'][n]['sha256'];outputs[c['tag']][n]=np.fromfile(f/n,'<f2').reshape(64,80,128,4)
    doses={c['tag']:c['tuning_vector']for c in reg['cases']};pairs=[]
    for a,b in itertools.combinations(reg['fixed_order'],2):
        pairs.append(dict(left=a,right=b,kind='within_vector_repeat'if doses[a]==doses[b]else'between_vectors',
            same_actual_controls184=True,lobes={n:metrics(outputs[a][n],outputs[b][n])for n in('diffuse.bin','specular.bin')}))
    historical=[]
    for old in reg['historical_A0_references']:
        old_outputs={}
        for n,r in old['outputs'].items():
            assert sha(r['path'])==r['sha256']
            old_outputs[n]=np.fromfile(r['path'],'<f2').reshape(64,80,128,4)
        for c in reg['cases']:
            if c['tuning_vector']=='Fork':
                historical.append(dict(current=c['tag'],historical=old['tag'],kind='same_setting_historical_cohort_qualified',
                    lobes={n:metrics(outputs[c['tag']][n],old_outputs[n])for n in('diffuse.bin','specular.bin')},
                    qualification='Historical B342 EXE/source and fresh process/cohort differ from new common sidecar EXE; descriptive comparison does not isolate the six-value intervention.'))
    result=dict(schema='four-context-scalar-vector-contrast-raw-descriptive-only',execution_sha256=sha(HERE/'execution_results.json'),source_frame_indices=list(range(64)),pairs=pairs,
        historical_same_setting_comparisons=historical,historical_pair_count=4,pair_count=6,lobe_comparison_count=12,quality_scores=None,composition_results=None,quality_accepted=False,new_native_GPU=0,
        limits='All six queried public defaults form one vector contrast versus the fork tuple, not individual-key causal isolation. Separate within-vector repeats from between-vector sensitivity. Specular hitA remains0. OutputA storage descriptive only. Native RGB is demodulated, not composed truth; composition and unchanged quality functions require later separate preparation. No private mechanism, quality or game-cause inference.')
    with target.open('x',encoding='utf-8',newline='\n')as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
