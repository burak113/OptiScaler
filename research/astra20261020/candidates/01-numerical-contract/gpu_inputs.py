"""Generate small exact numerical GPU requests from analytic/source-shaped cases.

No GPU call or HLSL compilation occurs. Large constant textures are represented
procedurally; only required returned observations are requested in GPU_REQUEST.
"""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np

from numerical_contract.sampling import sample_bilinear, sample_point
from numerical_contract.guards import colour_history_valid
from numerical_contract.storage import fp16_bits, store_fp16

HERE=Path(__file__).resolve().parent


def arithmetic_staging_case():
    """Full four-term source-shaped mean in f32/f64, with/without one store.

    This is the COMPLETE stated micro-formula, not a float64 colour estimator.
    The four terms were independently precommitted before candidate inspection.
    """
    terms=np.array([1,2**-11,2**-11,2**-11],np.float32)
    mean32=np.float32(np.sum(terms,dtype=np.float32)*np.float32(.25))
    mean64=np.sum(terms.astype(np.float64),dtype=np.float64)*.25
    stored=store_fp16(mean32,rounding='rtz')
    threshold=(float(mean32)+float(stored))/2
    return {'terms':terms.tolist(),'entire_formula':'(a+b+c+d)*0.25',
            'f32_without_store':float(mean32),'f64_without_store':float(mean64),
            'actual_boundary_rtz_model':float(stored),'fixed_threshold':threshold,
            'f32_without_store_decision':bool(mean32>threshold),
            'f64_without_store_decision':bool(mean64>threshold),
            'with_boundary_store_decision':bool(stored>threshold),
            'scope':'analytic CPU staging counterexample; no whole-estimator float64 or GPU claim'}


def microcases():
    depths=np.array([[1,1.0625]],np.float32)
    phase=np.arange(4097,dtype=np.float64)/4096
    uv=np.stack(((phase+.5)/2,np.full(phase.shape,.5)),-1).astype(np.float32)
    sampled={mode:sample_bilinear(depths,uv,mode=mode).values for mode in ('ideal','source','observed')}
    gates={mode:colour_history_valid(value,np.ones_like(phase),np.zeros_like(phase),uv,
                                    dtype=np.float64 if mode=='ideal' else np.float32)
           for mode,value in sampled.items()}
    nearest=sample_point(depths,uv,mode='source').values
    nearest_gate=colour_history_valid(nearest,np.ones_like(phase),np.zeros_like(phase),uv)
    # Stored as raw integer words: JSON contains no NaN or Infinity tokens.
    depth_cases=np.array([0.,-0.,2**-25,-2**-25,2**-24,-2**-24,
        2**-14-2**-25,2**-14,1+2**-11,-1-2**-11,
        1+3*2**-11,-1-3*2**-11,65500.,-65500.,65504.,65520.,
        -65520.,1e10,-1e10,np.inf,-np.inf,np.nan],np.float32)
    rows=[]
    for gx,gy in ((65,64),(129,128)):
        count=gx*gy;total=count*1048576
        words=np.array([total&0xffffffff,total>>32,total&0xffffffff,total>>32,count,0,0,0],dtype='<u4')
        rows.append({'grid_xy':[gx,gy],'full_extent_xy':[gx*8,gy*8],
                     'diffuse_rgb_constant':32,'specular_rgb_constant':32,'key_level_constant':64,
                     'linear_depth_constant':1,'motion_uv':[0,0],'expected_count':count,
                     'expected_increment':1048576,'expected_words':words.tolist(),
                     'expected_32_bytes_hex':words.tobytes().hex(),'low_word_wraps':total>>32})
    packed=np.arange(2048,dtype=np.uint16).astype(np.float32)
    arrays={'depth_texture':depths.astype(np.float16),'phase_uv':uv,'phase':phase,
            'storage_input_f32_words':depth_cases.view(np.uint32),
            'expected_rne_half_bits':fp16_bits(depth_cases,rounding='rne'),
            'expected_rtz_half_bits':fp16_bits(depth_cases,rounding='rtz'),
            'normal_payloads':packed,'normal_payload_half_bits':fp16_bits(packed),
            **{f'phase_sample_{k}':v for k,v in sampled.items()},
            **{f'phase_gate_{k}':v for k,v in gates.items()}}
    guard=np.array([[np.inf,0,1],[-np.inf,0,-1],[1,np.inf,1],
                    [50,0,51],[-50,0,-51],[1,0,1],[1,0,2],
                    [np.nan,0,1],[1,0,0]],np.float16)
    arrays['guard_current_motion_history_half_bits']=guard.view(np.uint16)
    summary={'schema':'fsrd.numerical-gpu-microcases.v1','gpu_executed':False,
        'arithmetic_staging':arithmetic_staging_case(),
        'phase_sweep':{'samples':len(phase),'depth_texels':depths.tolist(),'current_depth':1,'motion_depth':0,
                      'threshold':.02,'changed_source_vs_ideal':int(np.count_nonzero(gates['source']!=gates['ideal'])),
                      'changed_observed_vs_ideal':int(np.count_nonzero(gates['observed']!=gates['ideal'])),
                      'nearest_mutant_changed_vs_ideal':int(np.count_nonzero(nearest_gate!=gates['ideal'])),
                      'interpretation':'analytic affine depth plane sampled at fixed phases; no image-quality score'},
        'sum_cases':rows,'reset_expected_32_bytes_hex':bytes(32).hex(),
        'finite_guard':{'columns':['current_depth','motion_depth_delta','history_depth'],
                        'row_roles':['positive_infinite_expected','negative_infinite_expected','infinite_motion',
                                     'finite_inclusive_positive','finite_inclusive_negative',
                                     'finite_match','finite_mismatch','nan_expected','zero_history_sentinel'],
                        'source_expected_validity':[True,True,True,True,True,True,False,False,False],
                        'adapter_expected_validity':[False,False,False,True,True,True,False,False,False],
                        'note':'Inf is an actual representable FP16 payload. Two finite FP16 operands cannot overflow a float32 sum; that case is not claimed here.'},
        'storage_expected_authority':'Two selected CPU rounding profiles. Nonfinite payload bits are model-only; actual GPU behavior must be recorded.',
        'arrays':{k:{'shape':list(a.shape),'dtype':a.dtype.str,'raw_sha256':hashlib.sha256(a.tobytes()).hexdigest()} for k,a in arrays.items()}}
    return summary,arrays


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'evidence')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    summary,arrays=microcases()
    (args.output/'gpu_microcases.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'gpu_microcases.npz',**arrays)
    print(json.dumps(summary['phase_sweep'],indent=2))


if __name__=='__main__':main()
