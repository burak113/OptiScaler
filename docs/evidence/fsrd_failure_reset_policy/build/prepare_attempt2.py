"""Preserve metadata-only attempt1 and prepare a fresh isolated build attempt."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json
HERE = Path(__file__).resolve().parent
def ident(p):
    return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
old = [p for p in HERE.iterdir() if p.is_file() and p.name != Path(__file__).name]
assert not (HERE / 'build_command.json').exists()
assert not (HERE / 'owned_build_job_guard.json').exists()
assert all(not list((HERE / n).iterdir()) for n in ('tmp', 'out', 'obj'))
qualification = {
    'schema': 'metadata-only-build-preparation-attempt1-qualification-v1',
    'UTC': datetime.now(timezone.utc).isoformat(),
    'actual_compile_or_link_started': False,
    'nativeSDK_dispatches': 0, 'GPU_jobs': 0, 'game_runs': 0,
    'observed_result': 'build_release.py exit1 at linker-help CGTHREADS assertion; evaluation of Release/x64/v143, disabled build events and all ClCompile MultiProcessorCompilation=false already passed.',
    'limitation': 'The outer tool console traceback was observed in the conversation but not separately captured as a file. Retained binary probe outputs are actual bytes; this qualification does not invent a missing log.',
    'correction': 'Attempt2 removes unnecessary /cgthreads:1 override and help-token assertion. /m1 and all ClCompile /MP disabled enforce one compiler process. Link internal worker parallelism remains the configured tool default; owned Job memory/process monitoring remains active.',
    'preserved_attempt1_files': [ident(p) for p in sorted(old)],
}
with (HERE / 'preparation_attempt1_qualification.json').open('x', encoding='utf-8', newline='\n') as f:
    json.dump(qualification, f, indent=2); f.write('\n')
second = HERE / 'attempt2'
second.mkdir()
script = (HERE / 'build_release.py').read_text(encoding='utf-8')
script = script.replace(";assert b'CGTHREADS'in(linkhelp.stdout+linkhelp.stderr).upper()", '')
script = script.replace("'link_LTCG_threads':1", "'link_LTCG_threads':'configured tool default, not constrained or claimed single-thread'")
assert 'CGTHREADS' not in script
with (second / 'build_release.py').open('x', encoding='utf-8', newline='\n') as f: f.write(script)
with (second / 'owned_build_job_guard.py').open('xb') as f: f.write((HERE / 'owned_build_job_guard.py').read_bytes())
overrides = '''<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemDefinitionGroup>
    <ClCompile><MultiProcessorCompilation>false</MultiProcessorCompilation></ClCompile>
  </ItemDefinitionGroup>
  <Target Name="VerifyOwnedSingleCompiler" BeforeTargets="ClCompile">
    <Error Condition="'%(ClCompile.MultiProcessorCompilation)' != 'false'" Text="Owned build requires every ClCompile item to disable /MP." />
  </Target>
</Project>
'''
with (second / 'isolated_build_overrides.targets').open('x', encoding='utf-8', newline='\n') as f: f.write(overrides)
print(json.dumps({'status':'attempt2_prepared_no_compile_yet', 'path':str(second), 'preserved_attempt1_files':len(old)}))
