"""AST-only fixture derivation and pre-score source pinning; no scoring."""
from pathlib import Path
import ast,json,hashlib,datetime
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];SRC=ROOT/'tools_tmp/source_continuous_harmonic_feasibility_20260930'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
tree=ast.parse((SRC/'analyze.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='adversaries')
add=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='add')
add.body=ast.parse("observed=truth+noise if observed is None else observed\nout.append(dict(family=name,raw=observed.astype('f4'),truth=truth.astype('f4'),controls=ctrl if controls is None else controls,exposure=exposure))").body
(HERE/'adversary_generator.py').write_text('import numpy as np\n'+ast.unparse(ast.fix_missing_locations(node))+'\n')
design=ROOT/'tools_tmp/harmonic_response_dc_innovation_design_20260930'
inputs=[*HERE.glob('*.py'),HERE/'selfcheck_results.json',*design.glob('*.json'),SRC/'analyze.py',SRC/'harmonic_pilot.py',SRC/'results.json',
        ROOT/'tools_tmp/native_continuous_harmonic_independent_audit_20260930/audit.json']
original=json.loads((SRC/'pre_score_freeze.json').read_text())
inputs.extend(ROOT/p for p in original['sources'])
old=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_temporal_spectral_alpha_holdout')
inputs.append(old/'results.json');oldr=json.loads((old/'results.json').read_text())
for name in oldr['source_sha256']:inputs.append(old/'source_snapshot'/name)
for r in oldr['rows']:inputs.extend((old/r['scene']/'sequences.npz',old/r['scene']/'observed/frame_controls.txt'))
for folder in ('native_continuous_harmonic_fresh_retry_20260930','native_continuous_harmonic_remaining_20260930'):
    E=ROOT/'tools_tmp'/folder/'evidence';inputs.append(E/'results.json');nr=json.loads((E/'results.json').read_text())
    for r in nr['rows']:inputs.extend((E/r['scene']/'sequences.npz',E/r['scene']/'observed/frame_controls.txt'))
freeze=dict(status='frozen_before_any_source_or_saved_response_score',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),candidate_count=1,
            source_generator_derivation='Original harmonic adversaries AST all constructors unchanged; only nested add score/evaluate/print body replaced by raw/truth/controls/exposure collection.',
            sources={str(p):sha(p) for p in sorted(set(inputs))},parameters_changed_after_scores=False)
(HERE/'pre_score_freeze.json').write_text(json.dumps(freeze,indent=2)+'\n');print('freeze SHA',sha(HERE/'pre_score_freeze.json'))
