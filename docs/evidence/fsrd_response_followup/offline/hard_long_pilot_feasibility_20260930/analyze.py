"""Frozen hard/soft history ablation; source-pilot scores, never native quality."""
from pathlib import Path
import hashlib, json, sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
sys.path.insert(0,str(TESTS))
from fsrd_response_pilot import make_temporal_spectral_pilot
from fsrd_response_soft_pilot import make_soft_temporal_spectral_pilot
from probe_fsrd_statistical_resolve import score

STUDY=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_temporal_spectral_alpha_holdout')
MODELS=(('hard16',make_temporal_spectral_pilot,16),('hard64',make_temporal_spectral_pilot,64),
        ('soft16',make_soft_temporal_spectral_pilot,16),('soft64',make_soft_temporal_spectral_pilot,64))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def metrics(p,truth):
    s=score(p,truth,None);gain=[v for v in s['contrast_gain'] if v is not None]
    return dict(score=s,absolute_gain_min=min(gain) if gain else None,
        absolute_gain_max=max(gain) if gain else None,
        absolute_gain_mean=float(np.mean(gain)) if gain else None,
        all_frames_gain_within_five_percent=all(.95<=v<=1.05 for v in gain) if gain else None)
def main():
    output=Path(__file__).with_name('results.json')
    if output.exists():raise ValueError('Preserve prior experiment')
    rp=STUDY/'results.json';rh=sha(rp);native=json.loads(rp.read_text())
    report=dict(schema='fixed-hard-soft-source-pilot-history-ablation-v1',quality_accepted=False,
        native_measured=False,native_response_reused=False,game_run=False,
        preregistration_sha256=sha(Path(__file__).with_name('preregistration.md')),
        script_sha256=sha(__file__),original_report_sha256=rh,
        pilot_source_sha256={name:sha(TESTS/name) for name in ('fsrd_response_pilot.py','fsrd_response_soft_pilot.py')},
        models=[name for name,_,_ in MODELS],rows=[],limitations=[
            'Existing development sequences; no independent validation or new native response.',
            'Clean truth enters score only; the estimators accept observed RGB and controls.',
            'Corresponding IID source noise and exact reset/jitter epochs are fixture assumptions.',
            'Binary support retains coefficient noise and may chatter; soft support shrinks genuine detail.',
            'Absolute detail failures and all transition/shared-bias families remain mandatory.'])
    for row in native['rows']:
        scene=row['scene'];sp=STUDY/scene/'sequences.npz';cp=STUDY/scene/'observed/frame_controls.txt'
        hashes=dict(sequences=sha(sp),controls=sha(cp));variants={};cache={}
        with np.load(sp) as a:
            ctrl=np.loadtxt(cp,ndmin=2)
            for name,fn,history in MODELS:
                p,active,diag=fn(a['observed'],ctrl,history=history)
                p=p.astype(np.float16).astype(np.float32);cache[name]=p
                variants[name]=dict(full=metrics(p,a['clean_reference']),
                    mature=metrics(p[-16:],a['clean_reference'][-16:]),active_frames=int(active.sum()))
            for kind in ('hard','soft'):
                np.testing.assert_array_equal(cache[kind+'16'][:16],cache[kind+'64'][:16])
        unchanged=sha(sp)==hashes['sequences'] and sha(cp)==hashes['controls'] and sha(rp)==rh
        if not unchanged:raise ValueError('Source evidence changed')
        report['rows'].append(dict(scene=scene,source_sha256=hashes,source_unchanged=unchanged,variants=variants))
        print(scene,{name:dict(std=v['mature']['score']['residual_temporal_std'],
            gain_min=v['full']['absolute_gain_min'],gain_max=v['full']['absolute_gain_max']) for name,v in variants.items()},flush=True)
    report['status']='completed_source_only_not_native_acceptance'
    output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
if __name__=='__main__':main()
