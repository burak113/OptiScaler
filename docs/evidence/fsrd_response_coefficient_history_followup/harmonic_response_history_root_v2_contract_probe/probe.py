"""Independent post-DC exact-fallback repro; no native launch or oracle input."""
from pathlib import Path
import copy, hashlib, importlib.util, json
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PATH = ROOT/'tools_tmp/harmonic_response_coefficient_history_feasibility_v2_20260930/model.py'
EXPECTED = 'afb2fd6ce80e46a79fb97509c5eb2bb53860182b3268f6ede26046628043c874'

def main():
    target = HERE/'probe.json'
    if target.exists():
        raise ValueError('Preserve completed probe')
    digest = hashlib.sha256(PATH.read_bytes()).hexdigest()
    assert digest == EXPECTED
    sp = importlib.util.spec_from_file_location('independent_v2_contract_probe', PATH)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    n, h, w = 3, 19, 23
    raw = np.full((n,h,w,3), .3, np.float32)
    B = np.full_like(raw, .2)
    controls = np.zeros((n,3)); controls[0,0] = 1
    desc = dict(frequencies=[[3.23,1.17]], chosen=[0,1,2], groups=[[1,2]], original_groups=[[1,2]])
    base_diag = {'frames':[{'epoch_start':0, 'atom_diagnostics':[dict(phase_used=True, phase_increment=0., innovation=False)]} for _ in range(n)]}
    rows = []
    cases = [('P',np.nan),('TP',np.inf),('P',-.01),('TP',65505.),('phase',np.nan),('inactive',0.)]
    for kind, value in cases:
        P=raw.copy(); TP=raw.copy(); active=np.ones(n,bool); diag=copy.deepcopy(base_diag)
        if kind in ('P','TP'):
            (P if kind=='P' else TP)[1,0,0,2]=value  # Outside fitting ROI, blue only.
        elif kind=='phase':
            diag['frames'][1]['atom_diagnostics'][0]['phase_increment']=value
        else:
            active[1]=False
        with np.errstate(invalid='ignore'):
            out, info, candidate = m.make_response_history(raw,P,TP,B,active,controls,diag,[desc]*n)
        exact = out[1].tobytes()==B[1].tobytes()
        assert exact and candidate[1].tobytes()==B[1].tobytes()
        assert info['application_eligible'][1] is False
        assert info['application']['frames'][1]['applied'] is False
        assert info['frames'][2]['history_frames']==[2]
        rows.append(dict(case=kind,value=str(value),reported_reason=info['frames'][1]['reason'],
                         final_whole_RGB_frame_exact_B=exact,next_history_frames=info['frames'][2]['history_frames']))
    # Eligible no-response control does get DC shift, proving the failure test is active.
    out, info, _ = m.make_response_history(raw,raw,raw,B,np.ones(n,bool),controls,base_diag,[desc]*n)
    assert out.tobytes()!=B.tobytes() and all(info['application_eligible'])
    result=dict(schema='root-v2-post-DC-fallback-contract-v1',status='passed',quality_accepted=False,
                model_sha256=digest,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                cases=rows,valid_control_DC_changes_B=True,first_valid_output_RGB=out[0,0,0].tolist(),
                new_native_contexts=0,new_native_RR_calls=0)
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
