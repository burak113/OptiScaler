"""FP32 per-channel journal from the production estimator, on frozen inputs.

Diagnostic estimates are not ground truth. Rejection bits have a separate evaluated
mask: an early return must never be interpreted as passing the remaining checks.
"""
from pathlib import Path
import hashlib
import subprocess
import shutil
import numpy as np
import run_fsrd_gpu_tests as t
from fsrd_toolchain import dxc
from fsrd_alpha_common import convert, save_json

FIELDS = (
    'rejected', 'evaluated', 'eligible', 'preflight_count', 'fit_count',
    'mean_albedo', 'variance_albedo', 'min_specular', 'max_specular', 'mean_specular',
    'mean_residual', 'variance_residual', 'covariance', 'ridge_lambda', 'data_weight',
    'prior_slope', 'unregularized_slope', 'ridge_slope', 'intercept_unclamped',
    'intercept', 'intercept_error', 'fit_rmse', 'applied_slope', 'applied_intercept',
    'center_prediction', 'center_prediction_error', 'p0', 'p', 'delta_p',
    'transferred_rgb', 'eligible_rgb', 'skip_rgb', 'skip_fraction',
    'remodulated_fraction', 'raw_rgb', 'spatial_floor_rgb', 'eligible_fraction',
    'specular_signal', 'diffuse_signal', 'settings')
REASONS = {
    1:'conversion_route', 2:'center_source_or_surface', 4:'preflight_sample_count',
    8:'specular_minimum', 16:'specular_divisor', 32:'specular_variation',
    64:'preflight_albedo_variance', 128:'fit_sample_count', 256:'fit_albedo_variance',
    512:'intercept_evidence', 1024:'negative_slope', 2048:'model_nonpositive',
    4096:'nonfinite_model', 8192:'fp16_overflow'}


def build_journal(output):
    """Each page has one bytecode shared by strength 0 and 1."""
    directories=[]
    for page in range(5):
        directory=Path(output)/f'journal_page{page}'
        directory.mkdir(parents=True, exist_ok=True)
        for src in t.PRE.glob('*.hlsl*'):
            shutil.copy2(src, directory/src.name)
        wrapper=directory/'FSRDInputConvAdditive.hlsl'
        wrapper.write_text(f'#define FSRD_ADDITIVE_DIAGNOSTICS {page+1}\n'
            '#define FSRD_CONV_UAV_TYPE float4\n#define FSRD_ADDITIVE_SPLIT_ENABLED 1\n'
            '#include "FSRDInputConv.hlsl"\n',encoding='utf-8')
        subprocess.run([str(dxc()),'-T','cs_6_2','-E','CSMain','-enable-16bit-types',
            '-O3','-Qstrip_debug','-Qstrip_reflect',str(wrapper),'-Fo',
            str(directory/'FSRDInputConvAdditive_Shader.cso')],check=True,capture_output=True)
        directories.append(directory)
    return directories


def journal(directories, raw, diff, spec, strength, **kwargs):
    arrays=[]
    for directory in directories:
        arrays.extend(convert(raw,diff,spec,strength,directory=directory,
            kernel='additive',output_formats=[2]*8,**kwargs))
    return {name:array[...,:3] for name,array in zip(FIELDS,arrays)}


def summarize(fields, roi=None):
    roi=np.ones(fields['eligible'].shape[:2],bool) if roi is None else roi
    rejected=fields['rejected'][roi].astype(np.uint32)
    evaluated=fields['evaluated'][roi].astype(np.uint32)
    return dict(eligible_fraction=fields['eligible'][roi].mean(0).tolist(),
        changed_fraction=(abs(fields['delta_p'][roi])>1e-6).mean(0).tolist(),
        mean_abs_transfer=abs(fields['transferred_rgb'][roi]).mean(0).tolist(),
        mean_skip_fraction=fields['skip_fraction'][roi].mean(0).tolist(),
        mean_eligible_fraction=fields['eligible_fraction'][roi].mean(0).tolist(),
        reasons={name:dict(rejected=((rejected&bit)!=0).mean(0).tolist(),
                          evaluated=((evaluated&bit)!=0).mean(0).tolist())
                 for bit,name in REASONS.items()})


def capture_pair(output, directories, raw, diff, spec, **kwargs):
    """Persist estimates and actual stored outputs; do not conflate the two."""
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    if (output/'capture.json').exists():
        raise ValueError('Refusing to overwrite capture evidence')
    pair=[convert(raw,diff,spec,v,kernel='additive',**kwargs) for v in (0,1)]
    snapshots=[journal(directories,raw,diff,spec,v,**kwargs) for v in (0,1)]
    arrays={f'strength{v}_{k}':a for v,j in enumerate(snapshots) for k,a in j.items()}
    arrays.update({f'strength{v}_stored_{i}':a for v,p in enumerate(pair) for i,a in enumerate(p)})
    np.savez_compressed(output/'channels.npz',**arrays)
    report=dict(schema='fsrd-additive-channel-capture-v1',channel_order=['R','G','B'],
        comparison='Same experimental conversion bytecode and same source arrays, strength 0/1',
        diagnostic_notes='FP32 estimate journal is separately compiled; actual stored outputs use production experimental DXIL. Reconcile both, never infer activity from original-vs-experimental differences.',
        rejected_bits={str(k):v for k,v in REASONS.items()},
        summaries=[summarize(j) for j in snapshots],
        actual_changed=[(pair[0][i][...,:3]!=pair[1][i][...,:3]).mean((0,1)).tolist() for i in range(8)],
        shader_sha256=hashlib.sha256((t.PRE/'FSRDInputConvAdditive_Shader.cso').read_bytes()).hexdigest(),
        diagnostic_sha256=[hashlib.sha256((d/'FSRDInputConvAdditive_Shader.cso').read_bytes()).hexdigest() for d in directories],
        npz_sha256=hashlib.sha256((output/'channels.npz').read_bytes()).hexdigest())
    save_json(output/'capture.json',report)
    return report,snapshots,pair
