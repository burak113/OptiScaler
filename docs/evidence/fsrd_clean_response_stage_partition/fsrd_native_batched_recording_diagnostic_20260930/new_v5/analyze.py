"""Future descriptive CPU comparisons only; never import or call from preparation."""
from pathlib import Path
import hashlib,itertools,json
import numpy as np
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metrics(a,b):
    r={'RGBA_bits_exact':bool(np.array_equal(a.view('<u2'),b.view('<u2'))),'RGB_bits_exact':bool(np.array_equal(a[...,:3].view('<u2'),b[...,:3].view('<u2'))),
       'all_finite':bool(np.isfinite(a).all()and np.isfinite(b).all())}
    for s,k in[(slice(0,3),'RGB'),(slice(3,4),'alpha'),(slice(None),'RGBA')]:
        d=a[...,s].astype(np.float64)-b[...,s].astype(np.float64)
        r[k]={'RMS':float(np.sqrt(np.mean(d*d))),'max_abs':float(np.max(np.abs(d))),'changed_fraction':float(np.mean(d!=0)),
              'per_frame_RMS':np.sqrt(np.mean(d*d,axis=(1,2,3))).tolist()}
    return r
def main():
    target=HERE/'raw_comparisons.json';assert not target.exists(),'Preserve prior analysis'
    producer_path=HERE/'evidence/results.json';producer=json.loads(producer_path.read_text());reg=json.loads((HERE/'registration.json').read_text())
    assert producer['status']=='completed_native_batched_recording_diagnostic_not_solution_V5_accounting'and producer['accepted_contexts']==6
    arrays={};controls={}
    for c in reg['cases']:
        tag=c['tag'];p=producer['cases'][tag];assert p['accepted'];folder=Path(p['native_runtime_folder']);assert folder==Path(c['command'][1]).parent==Path(c['native_runtime_folder'])
        controls[tag]=(folder/'dispatch_controls.bin').read_bytes();assert controls[tag]==(folder/'expected_applied_dispatch_controls.bin').read_bytes()
        arrays[tag]={}
        for name in('diffuse.bin','specular.bin'):
            assert sha(folder/name)==p['lobes'][name]['sha256'];arrays[tag][name]=np.fromfile(folder/name,'<f2').reshape(64,80,128,4)
    comparisons={}
    for left,right in itertools.combinations(reg['mode_order'],2):
        assert controls[left]==controls[right]
        comparisons[left+'__'+right]={'source_frame_indices':list(range(64)),'applied_184_bytes_exact_all_frames':True,
            'lobes':{name:metrics(arrays[left][name],arrays[right][name])for name in('diffuse.bin','specular.bin')}}
    assert len(comparisons)==15
    result={'schema':'batched-recording-all15-source-aligned-descriptive-pairs-v1','producer_sha256':sha(producer_path),'comparisons':comparisons,
        'new_native_contexts':0,'new_API_RR_recordings':0,'quality_scores':False,'quality_accepted':False,'limits':reg['limitations']}
    with target.open('x',encoding='utf-8',newline='\n')as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
