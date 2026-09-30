"""Source-pilot-only history ablation. Native responses are not reused as new predictions."""
from pathlib import Path
import hashlib,json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests';sys.path.insert(0,str(TESTS))
from fsrd_response_soft_pilot import make_soft_temporal_spectral_pilot
from probe_fsrd_statistical_resolve import score
EVIDENCE=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce')
STUDY=EVIDENCE/'response_temporal_spectral_alpha_holdout'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    out=Path(__file__).with_name('results.json')
    if out.exists():raise ValueError('Preserve prior results')
    report_path=STUDY/'results.json';rh=sha(report_path);original=json.loads(report_path.read_text())
    report=dict(schema='soft-pilot-source-only-history-ablation-v1',native_rerun=False,native_quality_measured=False,
        quality_accepted=False,game_run=False,script_sha256=sha(Path(__file__)),pilot_source_sha256=sha(TESTS/'fsrd_response_soft_pilot.py'),
        original_report_sha256=rh,rows=[],limitations=[
            'Scores are pilot appearance, not denoised native candidate quality.',
            'Same development observations; history choice is not an independent holdout.',
            'Long corresponding history is assumed within fixed synthetic reset/jitter epochs.',
            'No native response from the old pilot is substituted for the new pilot response.'])
    for row in original['rows']:
        scene=row['scene'];path=STUDY/scene/'sequences.npz';sh=sha(path)
        control=STUDY/scene/'observed/frame_controls.txt';ch=sha(control)
        controls=np.loadtxt(control,ndmin=2);variants={};cache={}
        with np.load(path) as a:
            for history in (16,64):
                pilot,active,diag=make_soft_temporal_spectral_pilot(a['observed'],controls,history)
                pilot=pilot.astype(np.float16).astype(np.float32);cache[history]=pilot
                variants[str(history)]=dict(full=score(pilot,a['clean_reference'],None),
                    mature=score(pilot[-16:],a['clean_reference'][-16:],None),active_frames=int(active.sum()),
                    mature_weight_square_sum_mean=float(np.mean([r['spectral_weight_square_sum'] for r in diag['frames'][-16:]])))
            # Every first-16 pilot uses the exact same corresponding sources.
            np.testing.assert_array_equal(cache[16][:16],cache[64][:16])
        unchanged=sha(path)==sh and sha(control)==ch and sha(report_path)==rh
        if not unchanged:raise ValueError('Original native evidence changed')
        report['rows'].append(dict(scene=scene,provenance=dict(sequences_sha256=sh,controls_sha256=ch),source_unchanged=unchanged,variants=variants))
        print(scene,{k:dict(rmse=v['mature']['rmse'],std=v['mature']['residual_temporal_std']) for k,v in variants.items()},flush=True)
    report['status']='completed_source_only_not_native_acceptance'
    out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
if __name__=='__main__':main()
