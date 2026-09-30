"""Supplement frozen audit with every-frame absolute phase and observable P variation."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'OptiScaler/shaders/shader_tools/tests'))
from probe_fsrd_statistical_resolve import score
STUDY=ROOT/'tools_tmp/response_soft_temporal_long_captured_alpha_fresh'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
rp=STUDY/'results.json';before=sha(rp);r=json.loads(rp.read_text())
result=dict(schema='captured96-pilot-and-absolute-phase-v1',script_sha256=sha(Path(__file__)),report_sha256=before,
    clean_reference_only_in_score_calls=True,phase_measurement_halo_xywh=[0,20,90,70],rows=[])
for row in r['rows']:
    p=Path(row['evidence_directory'])/'sequences.npz';h=sha(p)
    with np.load(p) as a:
        record=dict(scene=row['scene'],sequences_sha256=h,windows={})
        for window,sl in (('full',slice(None)),('mature',slice(-16,None))):
            metrics={}
            for label in ('observed','pilot','pilot_response','baseline','soft_temporal_dc_current_safe'):
                value=a[label][sl]
                full=score(value,a['clean_reference'][sl],None)
                water=score(value[:,20:90,0:90],a['clean_reference'][sl,20:90,0:90],None)
                variation=value[:,25:85,5:85].astype(np.float64)
                means=variation.mean((1,2));dc=means-means.mean(0)
                spatial=variation-means[:,None,None,:];non_dc=spatial-spatial.mean(0)
                metrics[label]=dict(full_temporal_std=full['residual_temporal_std'],water_temporal_std=water['residual_temporal_std'],
                    water_rmse=water['rmse'],water_gain_by_frame=water['contrast_gain'],halo_phase_by_frame=water['phase_error_radians'],
                    halo_phase_within_0_05_radian_every_frame=all(p is None or p<=.05 for p in water['phase_error_radians']),
                    water_mean_DC_temporal_RMS=float(np.sqrt(np.mean(dc**2))),water_non_DC_temporal_RMS=float(np.sqrt(np.mean(non_dc**2))))
            record['windows'][window]=metrics
        result['rows'].append(record)
    assert sha(p)==h
assert sha(rp)==before
result['conclusion']='Candidate ROI relative gates and absolute gain pass, but early halo phase exceeds .05 rad and mature water temporal std exceeds native baseline. Source P and response statistics are diagnostics, not a game quality claim.'
out=HERE/'pilot_phase_statistics.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n')
print('sha256',sha(out))
for row in result['rows']:
 for window,m in row['windows'].items():
  print(row['scene'],window,{k:(v['water_temporal_std'],v['water_non_DC_temporal_RMS']) for k,v in m.items()})
