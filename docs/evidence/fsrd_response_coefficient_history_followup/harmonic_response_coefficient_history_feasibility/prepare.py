"""Authenticate unchanged source and read-only model columns before scores."""
from pathlib import Path
import json,hashlib
import numpy as np
import capture_source
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
SCENES=['material','wave','moving_light','weak_material','lighting_step','reset']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def native_path(scene):return ROOT/'tools_tmp'/('native_continuous_harmonic_fresh_retry_20260930' if scene=='material' else 'native_continuous_harmonic_remaining_20260930')/'evidence'
def main():
    if (HERE/'pre_score_freeze.json').exists():raise ValueError('Preserve freeze')
    authentication=dict(status='running_before_score',rows=[])
    pins={}
    for scene in SCENES:
        folder=native_path(scene);rp=folder/'results.json';row=next(r for r in read(rp)['rows'] if r['scene']==scene);npz=folder/scene/'sequences.npz';cp=folder/scene/'observed/frame_controls.txt'
        pins[str(rp)]=sha(rp);pins[str(npz)]=sha(npz);pins[str(cp)]=sha(cp)
        with np.load(npz) as z:
            raw=z['observed'];saved=z['pilot'];active=z['active'];ctrl=np.loadtxt(cp,ndmin=2)
            P,a,diag,descriptors=capture_source.capture(raw,ctrl)
            assert P.astype('f2').astype('f4').tobytes()==saved.tobytes() and a.tobytes()==active.tobytes() and diag==row['pilot_diagnostics']
            prefix=None
            if scene=='material':
                edited=raw.copy();edited[32:]=.22+np.random.default_rng(142).normal(0,.005,edited[32:].shape)
                changed=ctrl.copy();changed[32:,1:]=[.25,.125]
                alt,aa,ad,acs=capture_source.capture(edited,changed,verify=False)
                assert P[:32].tobytes()==alt[:32].tobytes() and a[:32].tobytes()==aa[:32].tobytes() and diag['frames'][:32]==ad['frames'][:32] and descriptors[:32]==acs[:32]
                prefix=dict(cutoff=32,source_and_control_future_changed=True,output_active_diagnostics_columns_prefix_exact=True)
            authentication['rows'].append(dict(scene=scene,NPZ_sha256=pins[str(npz)],source_report_SHA=pins[str(rp)],controls_SHA=pins[str(cp)],
                untouched_hooked_P_active_diagnostics_exact=True,saved_FP16_P_active_diagnostics_exact=True,future_prefix=prefix,
                descriptors=descriptors,source_diagnostics=diag))
        print('source authentication',scene,flush=True)
    # Actual source selector chooses sine at the centered even-width Nyquist seam.
    n,h,w=24,24,32;y,x=np.indices((h,w));raw=np.broadcast_to(.2+.02*((-1.)**x)[None,...,None],(n,h,w,3)).copy()
    ctrl=np.zeros((n,3));ctrl[0,0]=1
    P,a,d,ds=capture_source.capture(raw,ctrl)
    actual=[z for z in ds if z is not None]
    assert actual and any(len(g)==1 and z['chosen'][g[0]]%2==0 for z in actual for g in z['groups'])
    authentication['canonical_rank1_source_selector_control']=dict(untouched_hooked_exact=True,descriptors=ds,source_diagnostics=d,
        label='known_source_algebra_control_not_native_quality')
    authentication['status']='passed_source_hook_authentication_before_scores'
    (HERE/'source_authentication.json').write_text(json.dumps(authentication,indent=2,allow_nan=False)+'\n')
    sources=[HERE/p for p in ['model.py','capture_source.py','selfchecks.py','prepare.py','analyze.py','known_operators.py','preregistration.json','selfcheck_results.json','source_authentication.json','pre_execution_notes.json']]
    sources += [capture_source.SOURCE,ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930/significant_pilot.py',ROOT/'tools_tmp/harmonic_response_dc_innovation_feasibility_20260930/model.py',ROOT/'tools_tmp/harmonic_response_dc_innovation_feasibility_20260930/results.json',ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930/analyze.py',ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930/analyze.py',ROOT/'OptiScaler/shaders/shader_tools/tests/probe_fsrd_statistical_resolve.py',ROOT/'tools_tmp/harmonic_response_coefficient_history_design_20260930/design_preregistration_draft.json']
    pins.update({str(p):sha(p) for p in sources})
    (HERE/'pre_score_freeze.json').write_text(json.dumps(dict(schema='physical-delta-history-pre-score-freeze-v1',sources=pins,score_rows=0,new_native_contexts=0),indent=2)+'\n')
    print('freeze SHA',sha(HERE/'pre_score_freeze.json'),flush=True)
if __name__=='__main__':main()
