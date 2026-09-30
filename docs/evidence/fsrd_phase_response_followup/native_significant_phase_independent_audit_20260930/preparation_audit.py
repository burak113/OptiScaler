"""Read-only generated-driver lineage review; preparation is not measured success."""
from pathlib import Path
import ast,hashlib,json
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent;CASE=ROOT/'tools_tmp/native_significant_phase_initial_20260930';E=CASE/'evidence'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
d=json.loads((CASE/'derivation.json').read_text());pairs=[(CASE/'generate.py','generator_sha256'),(CASE/'probe_significant_phase.py','generated_driver_sha256'),(CASE/'native_helper.py','generated_helper_sha256'),(Path(d['original_calibration_path']),'original_calibration_sha256'),(Path(d['original_helper_path']),'original_helper_sha256'),(Path(d['prototype_source_path']),'prototype_sha256'),(Path(d['guard_source_path']),'guard_sha256')]
for p,k in pairs:assert sha(p)==d[k]
assert (CASE/'significant_pilot.py').read_bytes()==Path(d['prototype_source_path']).read_bytes()
assert (CASE/'native_resource_guard.py').read_bytes()==Path(d['guard_source_path']).read_bytes()
driver=(CASE/'probe_significant_phase.py').read_text();original=Path(d['original_calibration_path']).read_text();helper=(CASE/'native_helper.py').read_text()
oldfunc={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(original).body if isinstance(n,ast.FunctionDef)}
newfunc={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(driver).body if isinstance(n,ast.FunctionDef)}
assert oldfunc.keys()==newfunc.keys();unchanged=[name for name in oldfunc if name!='main'];assert all(oldfunc[name]==newfunc[name] for name in unchanged)
src=Path(d['original_helper_path']).read_text();node=next(n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name=='run_amd');expected=ast.get_source_segment(src,node)
replacements=[('    folder.mkdir(parents=True, exist_ok=True)',"    if folder.exists(): raise ValueError('Preserve existing native context folder')\n    folder.mkdir(parents=True)"),
 ('    proc = subprocess.run([str(executable), str(job)], capture_output=True, text=True, timeout=300)',"    guard = run_guarded([str(executable), str(job)], folder)\n    if guard['status'] != 'completed':\n        raise RuntimeError('Owned-child guard/native failure; preserved raw logs at '+str(folder))\n    proc = subprocess.CompletedProcess([str(executable), str(job)], guard['returncode'],\n        (folder/'stdout.log').read_text(encoding='utf-8',errors='replace'),\n        (folder/'stderr.log').read_text(encoding='utf-8',errors='replace'))"),
 ('    for path in inputs+[od, ospec]:\n        path.unlink()', '    # Retain actual consumed input and output bytes for independent audit.')]
for old,new in replacements:assert expected.count(old)==1;expected=expected.replace(old,new)
actual=next(n for n in ast.parse(helper).body if isinstance(n,ast.FunctionDef) and n.name=='run_amd');assert ast.dump(actual,include_attributes=False)==ast.dump(ast.parse(expected).body[0],include_attributes=False)
assert driver.index('from native_helper import run_amd')>driver.index('from probe_fsrd_additive_split import run_amd')
assert "a.pilot_mode=='significant_phase' and (a.history!=64 or a.reuse_oracle_study or a.reuse_blind_study or not a.skip_oracle)" in driver
assert "pilot, active, diagnostics = make_significant_phase_pilot(observed,data['controls'])" in driver
assert "response = execute(pilot_inputs, 'blind_pilot')" in driver and "baseline = execute(source_inputs, 'observed')" in driver and "repeat = execute(source_inputs, 'null_repeat')" in driver
assert "blind = baseline + active[:, None, None, None]*(pilot-response)" in driver
assert 'fresh_native_response_requested=True' in driver and 'fresh_native_response_measured' not in driver
assert "report['amd_completed_sequences'] += 1" in driver and "report['runner_path']=str(exe)" in driver
prototype=ast.parse((CASE/'significant_pilot.py').read_text());fun=next(n for n in prototype.body if isinstance(n,ast.FunctionDef));assert [a.arg for a in fun.args.args]==['raw','controls']
snapshot_hashes={}
if E.exists():
 for p in (E/'source_snapshot').iterdir():
  if p.is_file():snapshot_hashes[p.name]=sha(p)
 for name in ('significant_pilot.py','native_helper.py','native_resource_guard.py','probe_significant_phase.py','generate.py','derivation.json','preregistration.md'):
  assert (E/'source_snapshot'/name).read_bytes()==(CASE/name).read_bytes()
out=dict(schema='significant-phase-fresh-native-preparation-independent-audit-v1',analysis_sha256=sha(__file__),derivation_sha256=sha(CASE/'derivation.json'),authenticated_source_hashes={str(p):sha(p) for p,k in pairs},source_snapshot_sha256=snapshot_hashes,
 unchanged_original_function_AST=unchanged,helper_AST_exact_three_documented_changes=True,pilot_bytes_exact_frozen_CPU=True,guard_bytes_exact=True,significant_mode_disallows_oracle_and_reuse=True,
 source_pilot_call_inputs=['observedRGB','reset/jitter controls'],distinct_source_null_pilot_context_calls=True,old_native_TP_reuse=False,baseline_plus_active_P_minus_fresh_TP=True,
 quality_accepted=False,successful_native_measurement_claim=False,new_GPU_native_calls=0,
 qualifications=['Preparation lineage is verified; completed context/control/raw-output validation and quality await finalized evidence.',
 'The driver retains unused oracle/reuse branches for other modes, but significantmode rejects them. Native helper shadows original run_amd deliberately after its import.',
 'CurrentDC/radiance fallback/fixture/scoring functions are AST-equal to original; only main research mode, pinned runner, snapshots and retained guarded helper are derived.',
 'Global requested flag is preparation intent, not native completion evidence. Source-stage diagnostics native_measuredFalse do not describe the later independent GPU response.'])
p=HERE/'preparation_audit.json';assert not p.exists();p.write_text(json.dumps(out,indent=2)+'\n');print('preparation_audit_sha256',sha(p))
