"""Freeze held-input/camera/normal diagnostics separately from earlier evidence."""
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/evidence/fsrd_held_input_normal_followup'
PACKAGES=('current_camera_conformance_20260930','current_camera_gpu_conformance_20260930',
    'current_camera_gpu_independent_audit_20260930','frozen_source_context_repeat_20260930',
    'frozen_source_context_independent_audit_20260930','oct_corner_native_equivalence_20260930',
    'oct_corner_native_independent_audit_20260930','held_normal_followup_plot_20260930')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    if DEST.exists():raise ValueError('Preserve earlier archive')
    for name in ('current_camera_gpu_independent_audit_20260930','frozen_source_context_independent_audit_20260930','oct_corner_native_independent_audit_20260930'):
        if not (ROOT/'tools_tmp'/name/'audit.json').exists():raise ValueError('Wait for independent audit: '+name)
    DEST.mkdir(parents=True);(DEST/'.gitattributes').write_text('* -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n')
    manifest=dict(schema='fsrd-held-input-normal-followup-archive-v1',quality_accepted=False,game_run=False,
        runtime_implemented=False,archive_parent_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        archived_files=[],external_files=[],packages=[],conversion_dispatches=8,
        held_native_contexts=4,held_native_RR_dispatches=256,oct_native_contexts=12,oct_native_RR_dispatches=768,
        previous_completed_native_contexts=289,previous_completed_native_RR_dispatches=14128,
        completed_native_total_including_metadata_failed=305,completed_native_RR_total_including_metadata_failed=15152,
        limitations=['No stain/wave quality solution accepted. Prior archives and installed game DLL preserved.',
            'Ordinary debug diagnostics do not imply GPU-based validation or hidden provider determinism.',
            'Observed repeat spread is not a population confidence bound.',
            'Large full native outputs/binaries remain external with exact byte hashes.'])
    def copy(p,rel):
        target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);before=sha(p);shutil.copyfile(p,target)
        if sha(p)!=before or sha(target)!=before:raise ValueError('Archive changed bytes')
        manifest['archived_files'].append(dict(path=rel.as_posix(),source=str(p),sha256=before,bytes=target.stat().st_size))
    for name in PACKAGES:
        folder=ROOT/'tools_tmp'/name
        if not folder.is_dir():raise ValueError('Missing package '+name)
        count=0
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:continue
            rel=Path(name)/p.relative_to(folder)
            compact=p.suffix in ('.py','.json','.md','.log','.txt','.cmd','.png')
            binary_contract=p.name in ('dispatch_controls.bin','cb.bin') or (
                name=='current_camera_gpu_conformance_20260930' and p.suffix=='.bin') or (
                p.suffix=='.bin' and ('frozen_inputs' in p.parts or 'normal_inputs' in p.parts))
            cpu_fixture=name=='current_camera_conformance_20260930' and p.suffix=='.npz'
            if compact or binary_contract or cpu_fixture:copy(p,rel);count+=1
            elif p.suffix in ('.npz','.exe','.obj','.bin'):
                manifest['external_files'].append(dict(package=name,path=str(p),sha256=sha(p),bytes=p.stat().st_size))
        manifest['packages'].append(dict(name=name,archived_count=count))
    for p in (Path(__file__),ROOT/'tools_tmp/verify_fsrd_held_input_normal_archive_20260930.py',ROOT/'tools_tmp/plot_fsrd_held_normal_followup_20260930.py'):
        copy(p,Path('support')/p.name)
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    for row in manifest['archived_files']:
        if sha(DEST/row['path'])!=row['sha256']:raise ValueError('Archive final hash mismatch')
    print(json.dumps(dict(archived=len(manifest['archived_files']),external=len(manifest['external_files']),path=str(DEST))))
if __name__=='__main__':main()
