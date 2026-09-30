"""Freeze new contract diagnostics without changing the earlier archive."""
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];DEST=ROOT/'docs/evidence/fsrd_native_contract_followup'
PACKAGES=('synthetic_camera_contract_review_20260930','matched_camera_input_contract_20260930',
    'matched_camera_independent_audit_20260930','native_tuning_contract_review_20260930',
    'provider_defaults_query_20260930','default_tuning_context_repeat_20260930',
    'default_tuning_context_repeat_v2_20260930','default_tuning_independent_audit_20260930',
    'gpu_based_validation_20260930','gpu_based_validation_retry_20260930',
    'native_variation_spatial_attribution_20260930','rotating_camera_conformance_20260930',
    'rotating_camera_gpu_conformance_20260930','rotating_camera_gpu_capture_20260930','rotating_camera_gpu_independent_audit_20260930')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    if DEST.exists():raise ValueError('Preserve previous archive')
    required=ROOT/'tools_tmp/rotating_camera_gpu_independent_audit_20260930/capture_audit.json'
    if not required.exists():raise ValueError('Wait for independent camera audit')
    DEST.mkdir(parents=True);(DEST/'.gitattributes').write_text('* -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n')
    manifest=dict(schema='fsrd-native-contract-followup-archive-v1',quality_accepted=False,game_run=False,runtime_implemented=False,
        archive_parent_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        archived_files=[],external_files=[],packages=[],
        completed_four_repeat_native_contexts=4,completed_four_repeat_native_dispatches=256,
        metadata_failed_but_native_completed_contexts=1,metadata_failed_but_native_completed_dispatches=64,
        default_query_contexts=1,default_query_native_dispatches=0,
        instrumented_GPU_validation_completed_native_contexts=0,instrumented_GPU_validation_completed_dispatches=0,
        created_instrumented_retry_contexts_confirmed=1,first_instrumented_context_creation_completion_unknown=True,
        conversion_dispatches=12,
        previous_completed_native_contexts=284,previous_completed_native_dispatches=13808,
        completed_native_total_including_metadata_failed=289,completed_native_dispatch_total_including_metadata_failed=14128,
        limitations=['All quality changes remain unaccepted; diagnostics do not demonstrate stain/wave resolution.',
            'Instrumented validation produced no completed frame; its exit cause and requested stop completion are unknown.',
            'Default query is a separate utility and not a live-state query of repeated contexts.',
            'Large raw outputs, input arrays and binaries remain external with exact hashes. Prior archive is preserved.'])
    def copy(p,rel):
        target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);before=sha(p)
        shutil.copyfile(p,target)
        if sha(p)!=before or sha(target)!=before:raise ValueError('Archive changed bytes')
        manifest['archived_files'].append(dict(path=rel.as_posix(),source=str(p),sha256=before,bytes=target.stat().st_size))
    for name in PACKAGES:
        folder=ROOT/'tools_tmp'/name
        if not folder.is_dir():raise ValueError('Missing package '+name)
        files=0
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:continue
            rel=Path(name)/p.relative_to(folder)
            compact=p.suffix in ('.py','.json','.md','.log','.cpp','.txt','.cmd','.png')
            binary_contract=p.name in ('dispatch_controls.bin','cb.bin') or name in ('matched_camera_input_contract_20260930','rotating_camera_gpu_capture_20260930') and p.suffix=='.bin'
            cpu_fixture=name=='rotating_camera_conformance_20260930' and p.name.startswith('fixture_r') and p.suffix=='.npz'
            if compact or binary_contract or cpu_fixture:copy(p,rel);files+=1
            elif p.suffix in ('.npz','.exe','.obj','.bin'):
                manifest['external_files'].append(dict(package=name,path=str(p),sha256=sha(p),bytes=p.stat().st_size))
        manifest['packages'].append(dict(name=name,archived_count=files))
    follow=ROOT/'tools_tmp/reset_repeat_independent_audit_20260930/alpha_measurement_followup.json'
    copy(follow,Path('support/alpha_measurement_followup.json'))
    copy(Path(__file__),Path('support')/Path(__file__).name)
    verifier=ROOT/'tools_tmp/verify_fsrd_native_contract_archive_20260930.py'
    copy(verifier,Path('support')/verifier.name)
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    for r in manifest['archived_files']:
        if sha(DEST/r['path'])!=r['sha256']:raise ValueError('Final archive hash check')
    print(json.dumps(dict(files=len(manifest['archived_files']),external=len(manifest['external_files']),new_native_dispatches=320,path=str(DEST))))
if __name__=='__main__':main()
