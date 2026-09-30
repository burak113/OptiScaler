"""Preserve the metadata-failed first attempt and prepare a separate corrected attempt."""
from pathlib import Path
import hashlib,json
folder=Path(__file__).resolve().parent
retry=folder.with_name('default_tuning_context_repeat_v2_20260930')
if retry.exists():raise ValueError('Preserve retry')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
raw=folder/'evidence/repeat_0';log=raw/'runner.log'
if 'dispatches=64 validation_errors=0 validation_warnings=0 sdk_errors=0 sdk_warnings=0' not in log.read_text():raise ValueError('Unexpected incomplete native run')
failure=dict(status='native_complete_metadata_python_failure',error='NameError: Path not imported in derived native_helper.py',
    completed_native_contexts=1,completed_native_dispatches=64,quality_accepted=False,
    context_in_quality_or_four_repeat_comparison=False,
    retained_files={str(p.relative_to(folder)):dict(size=p.stat().st_size,sha256=sha(p)) for p in raw.iterdir() if p.is_file()},
    parent_script_sha256=sha(folder/'analyze.py'),helper_sha256=sha(folder/'native_helper.py'),
    explanation='Native executable completed64 frames; Python failed writing process identity before reading/deleting outputs. Keep all original input and output bytes. Retry separately with missing pathlib import fixed.')
(folder/'failure.json').write_text(json.dumps(failure,indent=2)+'\n')
retry.mkdir()
source=(folder/'generate.py').read_text()
anchor="hp.write_text('from probe_fsrd_additive_split import DLL,write_texture,save_json\\n"
if source.count(anchor)!=1:raise ValueError('Helper import anchor')
source=source.replace(anchor,"hp.write_text('from pathlib import Path\\nfrom probe_fsrd_additive_split import DLL,write_texture,save_json\\n",1)
(retry/'generate.py').write_text(source,encoding='utf-8')
(retry/'preregistration.md').write_text((folder/'preregistration.md').read_text()+'\nThe prior attempt completed one native context/64dispatches, then failed in\nPython metadata recording due to a missing pathlib import. It is retained\nseparately and excluded from this four-repeat analysis. This retry changes\nonly that import, not native runner bytes or requested controls.\n',encoding='utf-8')
(retry/'retry_derivation.json').write_text(json.dumps(dict(previous_failure_path=str(folder/'failure.json'),previous_failure_sha256=sha(folder/'failure.json'),
    previous_generator_sha256=sha(folder/'generate.py'),new_generator_sha256=sha(retry/'generate.py'),only_fix='Import pathlib.Path in Python metadata helper',prepare_script_sha256=sha(Path(__file__))),indent=2)+'\n')
