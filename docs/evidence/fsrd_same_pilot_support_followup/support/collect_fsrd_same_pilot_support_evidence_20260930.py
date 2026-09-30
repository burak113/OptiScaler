"""Freeze same-P covariance, actual shader payload contracts and source failures."""
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/evidence/fsrd_same_pilot_support_followup'
PACKAGES=('same_pilot_context_cohort_20260930','same_pilot_context_independent_audit_20260930',
    'significant_phase_support_decomposition_20260930','phase_source_dc_normalized_feasibility_20260930',
    'phase_source_dc_normalized_root_review_20260930')
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()
def main():
    if DEST.exists():raise ValueError('Preserve earlier archive')
    audit=ROOT/'tools_tmp/same_pilot_context_independent_audit_20260930'
    for p in (audit/'audit.json',audit/'support_review.json',audit/'audit_execution_notes.json',
              ROOT/'tools_tmp/phase_source_dc_normalized_root_review_20260930/review.json'):
        if not p.exists():raise ValueError('Wait for review '+str(p))
    native=ROOT/'tools_tmp/same_pilot_context_cohort_20260930/evidence'
    j=json.loads((native/'results.json').read_text());assert j['status']=='completed_diagnostic_not_solution' and j['completed_native_contexts']==6
    payload=json.loads((native/'persisted_shader_jobs/manifest.json').read_text());assert len(payload['jobs'])==640
    for job in payload['jobs']:
        for f in job['files']:
            p=native/'persisted_shader_jobs'/job['job_name']/f['name'];assert sha(p)==f['sha256']
    DEST.mkdir(parents=True)
    (DEST/'.gitattributes').write_text('* -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n')
    manifest=dict(schema='fsrd-same-pilot-support-followup-archive-v1',quality_accepted=False,game_run=False,runtime_implemented=False,
        parent_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        archived_files=[],external_files=[],packages=[],new_native_contexts=6,new_native_RR_dispatches=384,
        reused_original_contexts_not_counted_again=2,conversion_dispatches=128,composition_dispatches=512,
        actual_shader_payload_jobs=640,previous_completed_native_contexts=335,previous_completed_native_RR_dispatches=17072,
        completed_native_total_including_metadata_failed=341,completed_native_RR_total_including_metadata_failed=17456,
        installed_game_dll_sha256=sha('F:/SteamLibrary/steamapps/common/Cyberpunk 2077/bin/x64/dxgi.dll'),
        limitations=['No stain/wave or game solution accepted. Earlier archives and runtime shaders/settings preserved.',
          'Sample covariance identities do not establish population confidence or pilot-noise causation.',
          'Changing-support decomposition depends on reference mask and covariance; not a false-support percentage.',
          'DC-normalized source candidate has no native response or game validation and fails stationary/dynamic cases.',
          'All actual shader CB/jobs/logs archived; full textures/native lobes/arrays remain external with byte hashes.',
          'Ordinary debug and sampled owned-child resource guard are not GPU-based validation.'])
    def copy(p,rel):
        target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);before=sha(p);shutil.copyfile(p,target)
        if sha(p)!=before or sha(target)!=before:raise ValueError('Archive source changed')
        manifest['archived_files'].append(dict(path=rel.as_posix(),source=str(p),sha256=before,bytes=p.stat().st_size))
    for name in PACKAGES:
        folder=ROOT/'tools_tmp'/name;count=0
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:continue
            rel=Path(name)/p.relative_to(folder)
            if p.suffix in ('.py','.json','.md','.log','.txt','.cmd') or p.name in ('cb.bin','dispatch_controls.bin'):
                copy(p,rel);count+=1
            else:manifest['external_files'].append(dict(package=name,path=str(p),sha256=sha(p),bytes=p.stat().st_size))
        manifest['packages'].append(dict(name=name,archived_count=count))
    for p in (Path(__file__),ROOT/'tools_tmp/verify_fsrd_same_pilot_support_archive_20260930.py'):
        copy(p,Path('support')/p.name)
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    assert all(sha(DEST/r['path'])==r['sha256'] for r in manifest['archived_files'])
    print(json.dumps(dict(archived=len(manifest['archived_files']),external=len(manifest['external_files']),path=str(DEST),manifest_sha256=sha(DEST/'manifest.json'))))
if __name__=='__main__':main()
