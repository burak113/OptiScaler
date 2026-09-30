"""Future descriptive raw-lobe reader only; no composition/native launch or score."""
from pathlib import Path
import argparse,hashlib,json
import numpy as np
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metrics(a,b):
    result={'RGBA_bits_exact':bool(np.array_equal(a.view('<u2'),b.view('<u2'))),'RGB_bits_exact':bool(np.array_equal(a[...,:3].view('<u2'),b[...,:3].view('<u2')))}
    d=a[...,:3].astype('f8')-b[...,:3].astype('f8')
    result.update(RGB_RMS=float(np.sqrt(np.mean(d*d))),RGB_max_abs=float(np.max(abs(d))),RGB_per_source_frame_RMS=np.sqrt(np.mean(d*d,axis=(1,2,3))).tolist())
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument('--analyze-raw',action='store_true',required=True);p.parse_args()
    reg=json.loads((HERE/'registration.json').read_text());run=json.loads((HERE/'execution_results.json').read_text());target=HERE/'raw_comparisons.json'
    assert run['status']=='completed_clean_native_raw_only_not_composed_not_quality_accepted'and run['accepted_contexts']==2 and not target.exists()
    actual={r['tag']:r for r in run['jobs']};outputs={}
    for c in reg['cases']:
        f=Path(c['job']).parent;assert actual[c['tag']]['accepted'];outputs[c['tag']]={}
        for n in('diffuse.bin','specular.bin'):
            assert sha(f/n)==actual[c['tag']]['outputs'][n]['sha256'];outputs[c['tag']][n]=np.fromfile(f/n,'<f2').reshape(64,80,128,4)
    result={'schema':'genuine-clean-native-raw-two-context-descriptive-only','execution_sha256':sha(HERE/'execution_results.json'),'source_frame_indices':list(range(64)),
        'C0_C1':{n:metrics(outputs['C0'][n],outputs['C1'][n])for n in('diffuse.bin','specular.bin')},
        'historical_references_not_new_native':{},'composition_results':None,'quality_scores':None,'quality_accepted':False,'new_native_GPU':0,
        'limits':'Demodulated native lobe RGB is not composed raw radiance truth. OutputA may remain unwritten; raw bit-exact RGBA comparison is descriptive only, no outputA quality/finiteness inference. C0 then C1 is a clean-only repeat, not balanced treatment; two repeats do not identify covariance or game cause.'}
    for ref in reg['historical_references']:
        f=Path(ref['folder']);result['historical_references_not_new_native'][ref['name']]={}
        for n in('diffuse.bin','specular.bin'):
            assert sha(f/n)==ref['outputs'][n]['sha256'];old=np.fromfile(f/n,'<f2').reshape(64,80,128,4)
            result['historical_references_not_new_native'][ref['name']][n]={c:metrics(outputs[c][n],old)for c in('C0','C1')}
    with target.open('x',encoding='utf-8',newline='\n')as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
