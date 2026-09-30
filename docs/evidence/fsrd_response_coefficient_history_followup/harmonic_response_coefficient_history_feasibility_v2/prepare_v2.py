from pathlib import Path
import ast,json,hashlib
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];OLD=ROOT/'tools_tmp/harmonic_response_coefficient_history_feasibility_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def main():
    if (HERE/'pre_score_freeze.json').exists():raise ValueError('Preserve freeze')
    oldfreeze=read(OLD/'pre_score_freeze.json');assert all(sha(p)==s for p,s in oldfreeze['sources'].items())
    assert sha(HERE/'source_authentication.json')==sha(OLD/'source_authentication.json')
    for name in ['capture_source.py','known_operators.py','analyze.py','preregistration.json']:assert sha(HERE/name)==sha(OLD/name)
    assert read(HERE/'selfcheck_results.json')['model_sha256']==sha(HERE/'model.py')
    # Whitelist the exact model AST difference: eligibility init/false assignments, application active argument and assertion/diagnostic only.
    oldtext=(OLD/'model.py').read_text();expected=oldtext.replace('candidate=C.copy();history=[]','candidate=C.copy();eligible=active.copy();history=[]')
    expected=expected.replace('candidate[i]=B[i];cut(i+1)','candidate[i]=B[i];eligible[i]=False;cut(i+1)')
    expected=expected.replace('dc.apply_target(candidate,B,active,T,V,True)','dc.apply_target(candidate,B,eligible,T,V,True)')
    expected=expected.replace('assert out[~active].tobytes()==B[~active].tobytes()','assert out[~active].tobytes()==B[~active].tobytes()\n    assert out[~eligible].tobytes()==B[~eligible].tobytes()')
    expected=expected.replace('effective_independent_observations=None,exposure_unknown','application_eligible=eligible.tolist(),effective_independent_observations=None,exposure_unknown')
    assert ast.dump(ast.parse(expected))==ast.dump(ast.parse((HERE/'model.py').read_text()))
    sources=dict(oldfreeze['sources'])
    for p in HERE.iterdir():
        if p.suffix in ('.py','.json') and p.name!='pre_score_freeze.json':sources[str(p)]=sha(p)
    sources[str(OLD/'results.json')]=sha(OLD/'results.json')
    result=dict(schema='physical-delta-history-V2-pre-score-freeze',sources=sources,score_rows=0,new_native_contexts=0,
        source_capture_exact_reuse=True,only_model_eligibility_AST_whitelist_passed=True,scorer_knownoperators_constants_exact_V1=True)
    (HERE/'pre_score_freeze.json').write_text(json.dumps(result,indent=2)+'\n');print('V2 freeze',sha(HERE/'pre_score_freeze.json'))
if __name__=='__main__':main()
