"""Prepare a retained, guarded fresh native study; this generator executes no GPU."""
from pathlib import Path
import ast,hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
TESTS=ROOT/'OptiScaler/shaders/shader_tools/tests'
PILOT=ROOT/'tools_tmp/significant_phase_pilot_feasibility_20260930/significant_pilot.py'
PILOT_HASH='8c68c808482226284377734d941c95553d91e29ebfb33ede121d184585c3fa48'
GUARD=ROOT/'tools_tmp/frozen_source_context_repeat_20260930/native_resource_guard.py'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('Unexpected source transformation: '+old)
    return source.replace(old,new)

def main():
    target=HERE/'probe_significant_phase.py'
    if target.exists():raise ValueError('Preserve generated native study')
    if sha(PILOT)!=PILOT_HASH:raise ValueError('Unexpected fixed significant pilot')
    for source in (PILOT,GUARD):
        copied=HERE/source.name;shutil.copyfile(source,copied)
        if sha(copied)!=sha(source):raise ValueError('Snapshot changed bytes')
    original_helper=TESTS/'probe_fsrd_additive_split.py'
    old=original_helper.read_text();tree=ast.parse(old)
    node=next(v for v in tree.body if isinstance(v,ast.FunctionDef) and v.name=='run_amd')
    helper=ast.get_source_segment(old,node)
    helper=replace_once(helper,'    folder.mkdir(parents=True, exist_ok=True)',
        "    if folder.exists(): raise ValueError('Preserve existing native context folder')\n    folder.mkdir(parents=True)")
    helper=replace_once(helper,'    proc = subprocess.run([str(executable), str(job)], capture_output=True, text=True, timeout=300)',
        "    guard = run_guarded([str(executable), str(job)], folder)\n"
        "    if guard['status'] != 'completed':\n"
        "        raise RuntimeError('Owned-child guard/native failure; preserved raw logs at '+str(folder))\n"
        "    proc = subprocess.CompletedProcess([str(executable), str(job)], guard['returncode'],\n"
        "        (folder/'stdout.log').read_text(encoding='utf-8',errors='replace'),\n"
        "        (folder/'stderr.log').read_text(encoding='utf-8',errors='replace'))")
    helper=replace_once(helper,'    for path in inputs+[od, ospec]:\n        path.unlink()',
        "    # Retain actual consumed input and output bytes for independent audit.")
    helper_prefix="from pathlib import Path\nfrom probe_fsrd_additive_split import DLL,write_texture,save_json\nfrom native_resource_guard import run_guarded\nimport numpy as np\nimport re,json,hashlib,subprocess\n"
    (HERE/'native_helper.py').write_text(helper_prefix+helper+'\n')
    parent=TESTS/'probe_fsrd_response_calibration.py';source=parent.read_text()
    doc=ast.parse(source).body[0];lines=source.splitlines(keepends=True)
    bootstrap="\nfrom pathlib import Path\nimport sys\nRESEARCH_ROOT=Path(__file__).resolve().parents[2]\nTESTS=RESEARCH_ROOT/'OptiScaler/shaders/shader_tools/tests'\nsys.path.insert(0,str(TESTS))\nfrom significant_pilot import make_significant_phase_pilot\n\n"
    source=''.join(lines[:doc.end_lineno])+bootstrap+''.join(lines[doc.end_lineno:])
    source=replace_once(source,'from fsrd_response_soft_pilot import make_soft_temporal_spectral_pilot',
        'from fsrd_response_soft_pilot import make_soft_temporal_spectral_pilot\nfrom native_helper import run_amd')
    source=replace_once(source,"'dc_conditioned', 'soft_temporal'), default='causal')", "'dc_conditioned', 'soft_temporal', 'significant_phase'), default='causal')")
    source=replace_once(source,'    a = p.parse_args()',
        "    a = p.parse_args()\n    if a.pilot_mode=='significant_phase' and (a.history!=64 or a.reuse_oracle_study or a.reuse_blind_study or not a.skip_oracle):\n        raise ValueError('Significant phase requires history64, fresh contexts and --skip-oracle')")
    source=replace_once(source,'        src=Path(__file__).with_name(name)','        src=TESTS/name')
    source=replace_once(source,'        if not src.exists():src=Path(__file__).parent.parent/name','        if not src.exists():src=TESTS.parent/name')
    source=replace_once(source,'    identity = shader_identity(t.PRE)',
        "    for name in ('probe_significant_phase.py','native_helper.py','native_resource_guard.py','significant_pilot.py','generate.py','preregistration.md','derivation.json'):\n"
        "        shutil.copy2(Path(__file__).with_name(name),snapshot/name)\n"
        "    identity = shader_identity(t.PRE)")
    source=replace_once(source,"                  noise_distribution=a.noise_distribution,",
        "                  noise_distribution=a.noise_distribution,\n"
        "                  actual_research_driver_sha256=digest(__file__),\n"
        "                  pilot_prototype_sha256=digest(Path(__file__).with_name('significant_pilot.py')),\n"
        "                  native_raw_inputs_and_outputs_retained=True,owned_child_resource_guard=True,\n"
        "                  fresh_native_response_requested=True,source_stage_diagnostics_do_not_measure_native_response=True,")
    source=replace_once(source,"    exe = out/'fsrd_rr_runner.exe'\n    compile_cpp(Path(__file__).with_name('fsrd_rr_runner.cpp'), exe, ('d3d12.lib', 'dxgi.lib'))",
        "    exe = Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce/response_soft_temporal_long_alpha_fresh/fsrd_rr_runner.exe')\n"
        "    if digest(exe)!='3427689a4764380f885545c353250277e4d71944d3310c8a17b3cbba0f3c21d2':\n"
        "        raise ValueError('Pinned native runner changed')\n"
        "    report['runner_path']=str(exe)")
    source=replace_once(source,"        elif a.pilot_mode == 'soft_temporal':",
        "        elif a.pilot_mode == 'significant_phase':\n"
        "            pilot, active, diagnostics = make_significant_phase_pilot(observed,data['controls'])\n"
        "            diagnostics['epoch_start_by_frame']=[row['epoch_start'] for row in diagnostics['frames']]\n"
        "        elif a.pilot_mode == 'soft_temporal':")
    ast.parse(source);ast.parse(helper_prefix+helper)
    target.write_text(source)
    (HERE/'derivation.json').write_text(json.dumps(dict(schema='retained-guarded-significant-phase-native-derivation-v1',
        native_calls_by_generator=0,GPU_calls_by_generator=0,generator_sha256=sha(__file__),
        original_calibration_path=str(parent),original_calibration_sha256=sha(parent),original_helper_path=str(original_helper),original_helper_sha256=sha(original_helper),
        generated_driver_sha256=sha(target),generated_helper_sha256=sha(HERE/'native_helper.py'),
        prototype_source_path=str(PILOT),prototype_sha256=PILOT_HASH,guard_source_path=str(GUARD),guard_sha256=sha(GUARD),
        changes=['New explicit significant_phase mode/API, exact prototype snapshot; current causal DC epoch list derived from diagnostics.',
            'Pinned existing native runner B rather than a fresh build.',
            'Native owned-child memory/timeout monitoring and preservation of all consumed/raw output bytes.',
            'Extra source snapshots and actual driver/prototype identities; no old native source or response reuse.',
            'Synthetic fixture, six native configuration values, GPU conversion/composition, scoring/fallback unchanged.']),indent=2)+'\n')
    print('prepared_no_GPU_calls',sha(target),sha(HERE/'native_helper.py'))

if __name__=='__main__':main()
