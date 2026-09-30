"""Compact derived result and qualifications after successful full graph audit."""
from pathlib import Path
import json,hashlib
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
r=json.loads((HERE/'audit.json').read_text());rows=[];alpha=[]
for row in r['rows']:
    detail={}
    for name,v in row['metrics'].items():
        windows={}
        for w,m in v['metrics'].items():
            windows[w]={'relative_gate':m['relative_gate'],'actual_STD_ratio':m['actual_STD_ratio_to_native_baseline'],
                        'baseline_STD':row['baseline_metrics'][w]['score']['residual_temporal_std'],
                        'candidate_STD':m['score']['residual_temporal_std'],
                        'absolute_gain_range':[m['absolute_gain_min'],m['absolute_gain_max']],
                        'absolute_phase_max':m['absolute_phase_max'],
                        'absolute_detail_pass':m['per_frame_absolute_detail_pass'],
                        'absolute_gain_failing_frame_indices_local_to_window':m['absolute_gain_failing_frames'],
                        'absolute_phase_failing_frame_indices_local_to_window':m['absolute_phase_failing_frames']}
        detail[name]={'windows':windows,'invalid_pixel_fraction':v['invalid_pixel_fraction'],'atomic_fallback_pixel_fraction':v['fallback_pixel_fraction']}
    base=ROOT/'tools_tmp'/('native_continuous_harmonic_fresh_retry_20260930' if row['scene']=='material' else 'native_continuous_harmonic_remaining_20260930')/'evidence'/row['scene']
    for ctxname,ctx in zip(('observed','null_repeat','harmonic_pilot'),row['contexts']):
        table={}
        for slot,name in ((5,'diffuse_signal'),(6,'specular_signal')):
            p=base/ctxname/f'input{slot}.bin';a=np.fromfile(p,'<f2').reshape(-1,80,128,4)[...,3]
            table[name]={'input_alpha_min':float(a.min()),'input_alpha_max':float(a.max()),'input_payload_sha256':sha(p)}
        alpha.append({'scene':row['scene'],'context':ctxname,'consumed_ray_alpha':table,'native_output_lobe_alpha_range_diffuse_then_specular':ctx['output_alpha_range']})
    rows.append({'scene':row['scene'],'null_RGB_RMS':row['null_RMS_RGB'],'guide_diagnostic_A_changed_fraction':row['guide_RGBA_alpha_changed_fraction'],'variants':detail})
out={'status':'completed_independent_native_diagnostic_not_solution','quality_accepted':False,
     'source_audit_sha256':sha(HERE/'audit.json'),'native_contexts':18,'RR_calls':1152,'completed_GPU_jobs':1920,'separate_zero_native_attempt_GPU_jobs':128,
     'selected_harmonic_dc_current_safe_totals':r['chosen_totals'],'rows':rows,
     'interpretation':'Mature relative success6/6 is not quality acceptance: strict STD improves3/6 and absolute full detail0/6; weak mature fails absolute detail. Same-input null variation remains.'}
(HERE/'compact_report.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
header=ROOT/'external/FidelityFX-SDK-v2/Kits/FidelityFX/denoisers/include/ffx_denoiser.h'
hlsl=ROOT/'OptiScaler/shaders/fsrd_preprocess/precompile/FSRDInputConv.hlsl'
q={'status':'complete_audit_qualifications','quality_accepted':False,'source_audit_sha256':sha(HERE/'audit.json'),
   'auditor_preparation_errors_preserved':[
       {'log':'run.log','mistake':'Expected raw KeyError text without quotes','correction':'Actual Python KeyError str contains quoted absolute_detail_pass; assertion corrected, producer untouched.'},
       {'log':'run_v2.log','mistake':'Expected complete albedo RGBA equality rather than RGB-only contract','correction':'Native input3 diagnostic specularShare A changes with source allocation. Guide RGB, geometry and signal rayA exact; guide A change separately retained, no claim all nonradiance input bytes equal.'}],
   'guide_alpha_scope':{'header_path':str(header),'header_sha256':sha(header),'header_lines':[200,203,207,210],
                       'scope':'SDK describes albedoRGB; no explicit alpha semantics documented in these fields. This does not prove opaque model internals ignore arbitrary bytes.',
                       'conversion_path':str(hlsl),'conversion_sha256':sha(hlsl),'conversion_lines':[1202,1205,1206,1210],
                       'local_contract':'Production shader comments mark albedo alpha no consumer; specularShare and floorCrossing diagnostic values. Native full payload hashes retained, with observed/P RGB equality and A difference measured.'},
   'consumed_signal_alpha_table':alpha,
   'caller_flags':'NON_GAMMA_ALBEDO value2 and RESET value1 in SDK/caller184-byte dispatch records. These are not conversion Flags34/linear-depth flags.',
   'quality_and_metric_scope':['Truth is synthetic fixture construction/authentication and scoring only; estimator inputs raw/controls/optional exposure.',
       'Score excludes5px margin:70x118 pixels. Invalid/fallback fractions cover whole80x128 image.',
       'Mean per-pixel temporal STD does not equal square root of mean temporal variance; no variance-identity substitution in acceptance.',
       'Global gain and dominant frequency phase do not independently certify every dense/close-frequency detail component.',
       'Same-input null is not zero for weak/lighting/reset. It is retained in frozen relative gates and is not cause or confidence evidence.',
       'No runtime implementation or current-alpha game acceptance; historical/source CPU findings and newly installed unrelated game DLL are not game validation.',
       'Conditional covariance omits selected-frequency uncertainty; fullsource sigma includes heldout pixels and slot2 adaptively reuses validation pixels.',
       'Initial zero-child guard and completed-material stdout failure are separate preserved statuses, not discarded/cleaned native outcomes.']}
(HERE/'execution_qualifications.json').write_text(json.dumps(q,indent=2,allow_nan=False)+'\n')
files=[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(HERE.iterdir()) if p.is_file() and p.name!='completion_manifest.json']
(HERE/'completion_manifest.json').write_text(json.dumps({'status':'complete_frozen','quality_accepted':False,'files':files},indent=2)+'\n')
print(json.dumps({name:sha(HERE/name) for name in ('audit.json','compact_report.json','execution_qualifications.json','completion_manifest.json')}))
