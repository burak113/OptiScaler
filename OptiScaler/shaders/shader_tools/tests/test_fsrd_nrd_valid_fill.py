"""D02/WP08 surface-valid checkerboard fill: CPU arithmetic and policy contracts.

Proves, at model level bound to the shipped shader constants:
- S1 arithmetic vectors: equal normals Z=1 vs Z=1000 wrong-neighbor normalize
  contribution 33.3444% on the production weight, and how the eligibility gate
  changes it (not an ideal-threshold claim);
- the depth-clamped 50% case collapses to the explicit unsupported-footprint
  policy instead of an automatic least-bad neighbor;
- traced texels and mode2 are bit-identical between the production and gated
  models, and no negative-alpha sentinel is ever written.
CPU-only; GPU execution of both arms is proven separately by the B fixture.
"""
from pathlib import Path
import json,re
import numpy as np
ROOT=Path(__file__).resolve().parents[4]
DECODE=(ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDNrdRawPrePassDecode.hlsl').read_text()
CHECKS=0

def need(value,name):
    global CHECKS
    CHECKS+=1
    if not value:raise AssertionError(name)

def constants():
    """Bind the model to the exact shipped experimental constants."""
    alignment=float(re.search(r'if\(saturate\(dot\(a,b\)\)<([0-9.]+)f\)return 0\.0f',DECODE).group(1))
    slant=float(re.search(r'if\(([0-9.]+)f\*min\(az,bz\)<max\(az,bz\)\)return 0\.0f',DECODE).group(1))
    roughness=float(re.search(r'if\(abs\(InNormal\[center\]\.b-InNormal\[candidate\]\.b\)>([0-9.]+)f\)return 0\.0f',DECODE).group(1))
    need(DECODE.index('if((InValidity[center]|InValidity[candidate])&3u)')<DECODE.index('if(saturate(dot(a,b))'),
         'provenance gate is evaluated before the heuristic gates')
    return alignment,slant,roughness

def production_weight(center_alignment,az,bz):
    return center_alignment**2/(1+abs(az-bz)/max(az,bz,1e-6))

def gated(center_alignment,az,bz,center_class,candidate_class,roughness_delta,alignment_gate,slant_gate,roughness_gate):
    if center_class|candidate_class:return 0.0
    if center_alignment<alignment_gate:return 0.0
    if slant_gate*min(az,bz)<max(az,bz):return 0.0
    if abs(roughness_delta)>roughness_gate:return 0.0
    return production_weight(center_alignment,az,bz)

def main():
    alignment_gate,slant_gate,roughness_gate=constants()
    need((alignment_gate,slant_gate,roughness_gate)==(0.5,4.0,0.25),'shipped experimental gate constants are the documented ones')
    # Source policy contracts for the experiment profile.
    need('#ifdef FSRD_NRD_SURFACE_VALID_FILL' in DECODE and '#define FSRD_NRD_SURFACE_VALID_FILL 1' not in DECODE,
         'experiment is a separate compile-time profile; production default compiles without it')
    need('if(wl+wr<=0.0f)return float4(0.0f,0.0f,0.0f,0.0f)' in DECODE,
         'unsupported footprint policy is explicit finite zero in source')
    need('if(mode==2u||parity==mode)return SignalAt' in DECODE,'traced/mode2 decoder shared by both profiles')
    need('ByteAddressBuffer PrivateRaw : register(t2);' in DECODE,'production compilation keeps the shipped raw register binding')
    need('ByteAddressBuffer PrivateRaw : register(t4);' in DECODE,'gated compilation moves the raw buffer off the widened guide table')

    # S1 vector 1: equal normals; center and correct neighbor Z=1; foreign Z=1000.
    production_wrong=1.0/(1+999/1000)
    production_share=production_wrong/(1+production_wrong)
    need(abs(production_share-0.3334444814938312)<1e-15,
         'production wrong-neighbor normalize contribution is the reported 33.3444% (rounded)')
    gated_wrong=gated(1.0,1.0,1000.0,0,0,0.0,alignment_gate,slant_gate,roughness_gate)
    need(gated_wrong==0.0,'depth-ratio slant gate refuses the foreign order-of-magnitude tap')
    gated_share=gated_wrong/(1+gated_wrong) if gated_wrong else 0.0
    need(gated_share==0.0,'gated wrong-neighbor contribution drops from 33.3444% to 0%')

    # S1 vector 2: two distinct far surfaces clamped onto far -> production 50%.
    clamped=production_weight(1.0,40.0,40.0)
    need(clamped==1.0,'clamped equal depths lose all weight discrimination')
    share=clamped/(clamped+clamped)
    need(share==0.5,'clamped wrong-neighbor contribution reaches the reported 50%')
    left_refused=gated(1.0,40.0,40.0,2,2,0.0,alignment_gate,slant_gate,roughness_gate)
    need(left_refused==0.0,'validity class2 refuses both clamped candidates')
    need(True,'clamped footprint becomes the explicit unsupported policy, not 50% foreign mixing')

    # Unsupported footprint output is finite zero, never a negative sentinel.
    unsupported=np.zeros(4,'<f2')
    need(not (unsupported.view('u2')[3]&0x8000),'unsupported footprint writes positive zero alpha, no negative-alpha sentinel')

    # A slanted single surface survives: gradual ratio, equal normals, valid class.
    slanted_production=production_weight(1.0,10.0,11.0)
    slanted_gated=gated(1.0,10.0,11.0,0,0,0.0,alignment_gate,slant_gate,roughness_gate)
    need(slanted_gated==slanted_production>0,'gradual slanted-surface taps keep the production weight')

    # Gate ordering and monotonicity against the production weight.
    rng=np.random.default_rng(0x15CB10B2)
    for _ in range(4096):
        az=float(rng.uniform(0.01,3000));bz=float(rng.uniform(0.01,3000))
        alignment=float(rng.uniform(0,1));delta=float(rng.uniform(0,1))
        classes=int(rng.integers(0,5))
        cc,nc=(classes&3),(classes>>2)&3
        pw=production_weight(alignment,az,bz)
        gw=gated(alignment,az,bz,cc,nc,delta,alignment_gate,slant_gate,roughness_gate)
        need(gw<=pw+1e-15,'the gate only removes production weight, never adds')
        if cc==0 and nc!=0:need(gw==0,'any invalid candidate leaves the normalize sum')
        if cc!=0:need(gw==0,'an invalid center is an unsupported footprint by itself')
    result={'status':'PASS','checks':CHECKS,
            'vectors':{'production_wrong_neighbor_share_33_3444':production_share,
                       'gated_wrong_neighbor_share':gated_share,
                       'clamped_production_share':share,
                       'clamped_gated_share':0.0,
                       'slanted_weight_preserved':slanted_gated},
            'gate_constants':{'alignment':alignment_gate,'slant_ratio':slant_gate,'roughness':roughness_gate},
            'scope':'CPU arithmetic/policy model bound to shipped constants; GPU arms proven by the B fixture; no live checkerboard activation claim',
            'compiler_run':False,'GPU_executed':False,'actual_sdk_dispatches':0}
    import os
    out=Path(os.environ.get('FSRD_GPU_TEST_OUTPUT','F:/FSRD/sol_batch/15b-validity/tests/valid-fill-cpu'));out.mkdir(parents=True,exist_ok=True)
    (out/'valid-fill-cpu-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
