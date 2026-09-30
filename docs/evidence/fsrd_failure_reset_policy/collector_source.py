from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT/'docs/evidence/fsrd_failure_reset_policy'
BUILD = ROOT/'tools_tmp/fsrd_failure_reset_policy_build_20260930'
REVIEW = ROOT/'tools_tmp/fsrd_failure_reset_policy_review_20260930/review.json'
CPP = ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'

def sha(path):
    d = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            d.update(block)
    return d.hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def check(row):
    path = Path(row['path'])
    if not path.is_absolute():
        path = ROOT/path
    assert sha(path) == row['sha256'], str(path)
    if 'bytes' in row:
        assert path.stat().st_size == row['bytes'], str(path)

assert not DEST.exists(), 'Preserve archive'
assert sha(CPP) == 'd2cb58c65f6e9d3699e56e34675e6d50593b2bd89bd568025083cb8e09fdd628'
assert sha(REVIEW) == '5fb9a25cdf765a41d117ceaad143efcdc8f0f9a696f6db4256db586a6a623be0'
assert sha(BUILD/'completion_manifest.json') == '867371c78dbfafc0ec76ee69c37d98119bd7c0b2e7894aa968403ced17ecb609'
assert sha(BUILD/'completion_cleanup_manifest.json') == 'a2697b3c1c6a0b29a07a06907d95710ac06052a3be4e1f3ed9d1ac77cfa62777'
assert subprocess.check_output(['git','diff','--numstat','--',str(CPP)],cwd=ROOT,text=True).strip() == '8\t0\tOptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
assert not (ROOT/'OptiScaler.sln.metaproj').exists()
review = read(REVIEW)
for row in review['source_pins']:
    check(row)
build = read(BUILD/'completion_manifest.json')
cleanup = read(BUILD/'completion_cleanup_manifest.json')
for row in build['compact_files']+build['external_output_files']+cleanup['original_completion_pins']+cleanup['new_supplement_files']:
    check(row)
summary = read(BUILD/'completion_summary.json')
assert summary['status'] == 'full_Release_x64_compile_link_passed'
assert summary['actual_build_attempts'] == 1 and summary['actual_compiler_or_linker_returncode'] == 0
assert summary['before_after_byte_identity_file_count'] == 273
assert summary['all_production_shader_provider_project_resource_header_before_after_bytes_exact']
assert summary['nativeSDK_dispatches'] == summary['GPU_jobs'] == summary['game_runs'] == 0
assert not summary['DLL_deployment']
DEST.mkdir(parents=True)
copied = []
seen = set()

def collect(source, relative):
    source = Path(source)
    relative = Path(relative)
    assert '..' not in relative.parts and not relative.is_absolute()
    if relative.as_posix() in seen:
        return
    seen.add(relative.as_posix())
    target = DEST/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
    digest = sha(source)
    assert sha(target) == digest
    copied.append(dict(source=str(source),archive=relative.as_posix(),bytes=source.stat().st_size,sha256=digest))

for row in build['compact_files']+cleanup['original_completion_pins']+cleanup['new_supplement_files']:
    source = Path(row['path'])
    collect(source,Path('build')/source.relative_to(BUILD))
collect(BUILD/'completion_cleanup_manifest.json',Path('build/completion_cleanup_manifest.json'))
collect(REVIEW,Path('independent_source_review/review.json'))
collect(CPP,Path('reviewed_source/OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'))
collect(Path(__file__),Path('collector_source.py'))
manifest = dict(
    schema='fsrd-failure-reset-policy-reviewed-build-archive-v1',
    branch='ffxD-experimental-alpha',base_commit='5cb10122b7de5c802fe93e90c6ba860be240d72e',
    changed_source='OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp',added_lines=8,removed_lines=0,
    production_change='Existing native/composition history invalidation before composition/upscale false returns.',
    build_status=summary['status'],actual_full_builds=1,metadata_only_preparation_attempts=1,
    MSBuild_warnings=76,MSBuild_errors=0,warning_novelty='No pre-change baseline build; warnings retained without novelty claim.',
    compiled_DLL=summary['DLL'],production_shader_provider_project_resource_identities_unchanged=273,
    copied_file_count=len(copied),copied_files=copied,
    external_payload_count=len(build['external_output_files']),external_payloads=build['external_output_files'],
    pre_policy_snapshot='docs/evidence/fsrd_native_gap_call_presence/outer_failure_pre_policy_source_snapshot',
    new_native_contexts=0,new_API_RR_recordings=0,new_GPU_jobs=0,game_run=False,DLL_deployed=False,
    current_total_contexts=398,current_total_API_RR_recordings=21050,current_total_queued_RR=21042,
    current_total_recorded_only_discards=8,current_separate_no_API_omissions=4,
    quality_accepted=False,stain_wave_solution_accepted=False,
    limits=['Source control-flow and compile/link verification, no executed production fault injection.',
            'Conservative reset can lose useful accumulation if the failed RR prefix executes.',
            'Successful caller discards, already-recorded successors, SR reset and pending resource lifetime remain outside this patch.',
            'No current-alpha game evidence or stain-cause confirmation.'],
)
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(DEST/'.gitattributes').write_text('* -text\n')
print(json.dumps(dict(copied_file_count=len(copied),external_payload_count=3,manifest_sha256=sha(DEST/'manifest.json'))))
