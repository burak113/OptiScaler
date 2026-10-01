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
    assert run['status']=='completed_no_scalar_vs_explicit_defaults_native_raw_only_not_composed_not_quality_accepted'and run['accepted_contexts']==4 and not target.exists()
    actual={r['tag']:r for r in run['jobs']};outputs={}
    for c in reg['cases']:
        f=Path(c['job']).parent;assert actual[c['tag']]['accepted'];outputs[c['tag']]={}
        assert(f/'dispatch_controls.bin').read_bytes()==(f/'expected_applied_dispatch_controls.bin').read_bytes()
        for n in('diffuse.bin','specular.bin'):
            assert sha(f/n)==actual[c['tag']]['outputs'][n]['sha256'];outputs[c['tag']][n]=np.fromfile(f/n,'<f2').reshape(64,80,128,4)
    doses={c['tag']:c['scalar_configuration_mode']for c in reg['cases']};pairs=[]
    for a,b in itertools.combinations(reg['fixed_order'],2):
        pairs.append(dict(left=a,right=b,kind='within_configuration_policy_repeat'if doses[a]==doses[b]else'between_scalar_Configure_policies',
            same_actual_controls184=True,lobes={n:metrics(outputs[a][n],outputs[b][n])for n in('diffuse.bin','specular.bin')}))
    historical=[]
    for old in reg['historical_completed_vector_references']:
        old_outputs={}
        for n,r in old['outputs'].items():
            assert sha(r['path'])==r['sha256']
            old_outputs[n]=np.fromfile(r['path'],'<f2').reshape(64,80,128,4)
        for c in reg['cases']:
            historical.append(dict(current=c['tag'],historical=old['tag'],kind='completed_vector_historical_cohort_qualified',
                    lobes={n:metrics(outputs[c['tag']][n],old_outputs[n])for n in('diffuse.bin','specular.bin')},
                    historical_scalar_vector=old['tuning_vector'],historical_scalar_calls=6,
                    qualification='Byte-identical commonEXE/seveninputs/controls; prior Fork or AMD explicitly configured six scalars. Separate process/context/cohort. This is descriptive, not equal configuration for all rows. NoScalar activeinternalsettings are unmeasured.'))
    result=dict(schema='four-context-no-scalar-vs-explicit-defaults-policy-raw-descriptive-only',execution_sha256=sha(HERE/'execution_results.json'),source_frame_indices=list(range(64)),pairs=pairs,
        historical_completed_vector_comparisons=historical,historical_pair_count=16,pair_count=6,lobe_comparison_count=12,quality_scores=None,composition_results=None,quality_accepted=False,new_native_GPU=0,
        limits='Explicit six-key scalar Configure versus no scalar Configure is the policy contrast. NoScalar CPP does not read sidecar and activeinternalsettings are unknown. Samequeried24B file is CPUprevalidated, not evidence of identical active state. Separate within-policy repeats from between-policy sensitivity. GlobaldebugConfigure and informationalversionQuery remain1/context; no scalarQuery here. Flags2 vs productionRelease0/key7/proxy/cache-flow gaps remain. SpecularhitA0 unchanged; outputA storage descriptive only. RawRGB is demodulated notcomposedtruth. No quality/privateSDK/gamecause/fix claim.')
    with target.open('x',encoding='utf-8',newline='\n')as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
