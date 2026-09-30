"""CPU-only future raw comparisons; never runs native work or fills absent output."""
from pathlib import Path
import hashlib,itertools,json,struct
import numpy as np
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def metrics(a,b):
    r={'RGBA_bits_exact':bool(np.array_equal(a.view('<u2'),b.view('<u2'))),'RGB_bits_exact':bool(np.array_equal(a[...,:3].view('<u2'),b[...,:3].view('<u2'))),
       'all_finite':bool(np.isfinite(a).all()and np.isfinite(b).all())}
    for s,k in[(slice(0,3),'RGB'),(slice(3,4),'alpha'),(slice(None),'RGBA')]:
        d=a[...,s].astype(np.float64)-b[...,s].astype(np.float64)
        r[k]={'RMS':float(np.sqrt(np.mean(d*d))),'max_abs':float(np.max(np.abs(d))),'changed_fraction':float(np.mean(d!=0)),
              'per_frame_RMS':np.sqrt(np.mean(d*d,axis=(1,2,3))).tolist()}
    return r
def main():
    source=HERE/'evidence/results.json';producer=json.loads(source.read_text());assert producer['status']=='completed_H2_native_record_discard_diagnostic_not_solution'
    reg=json.loads((HERE/'registration.json').read_text());cases={c['tag']:c for c in reg['cases']};arrays={};controls={};indices={}
    result={'schema':'discarded-record-H2-descriptive-raw-comparisons-v1','producer_sha256':sha(source),'new_native_contexts':0,'new_API_RR_recordings':0,'quality_accepted':False,
            'comparisons':{},'limits':reg['limitations'],'alignment_qualification':'Ordinal aligns submission position only; logical aligns common observed sourceframe. Both attach flags/control identities; absent discardedframe24 has no measured output.'}
    for tag,c in cases.items():
        folder=HERE/'evidence'/tag;p=producer['cases'][tag];indices[tag]=p['observed_frame_indices']
        raw=(folder/'dispatch_controls.bin').read_bytes();recorded=p['recorded_frame_indices'];controls[tag]={f:raw[i*184:(i+1)*184]for i,f in enumerate(recorded)}
        arrays[tag]={name:np.fromfile(folder/name,'<f2').reshape(c['frames_queued'],80,128,4)for name in('diffuse.bin','specular.bin')}
        assert all(sha(folder/name)==p['lobes'][name]['sha256']for name in arrays[tag])
    for left,right in itertools.combinations(reg['mode_order'],2):
        aidx=indices[left];bidx=indices[right];common=sorted(set(aidx)&set(bidx));ordinals=list(zip(aidx,bidx));n=len(ordinals)
        alignments={}
        for label,pairs in [('submitted_ordinal',ordinals),('common_source_frame',[(f,f)for f in common])]:
            metadata=[{'left_source_frame':a,'right_source_frame':b,'left_submitted_ordinal':aidx.index(a),'right_submitted_ordinal':bidx.index(b),
                       'left_flags':struct.unpack_from('<I',controls[left][a],4)[0],'right_flags':struct.unpack_from('<I',controls[right][b],4)[0],
                       'applied_184_bytes_exact':controls[left][a]==controls[right][b]}for a,b in pairs]
            aa=[aidx.index(a)for a,b in pairs];bb=[bidx.index(b)for a,b in pairs]
            alignments[label]={'frames':metadata,'lobes':{name:metrics(arrays[left][name][aa],arrays[right][name][bb])for name in arrays[left]}}
        result['comparisons'][left+'__'+right]=alignments
    assert len(result['comparisons'])==28;save(HERE/'raw_comparisons.json',result)
    print(json.dumps({'context_pairs':28,'alignments_per_pair':2,'lobes_per_alignment':2,'new_native_contexts':0,'raw_comparisons_sha256':sha(HERE/'raw_comparisons.json')}))
if __name__=='__main__':main()
