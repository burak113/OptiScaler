"""Seal compact build evidence and identities of external large output artifacts."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib, json, re, subprocess
HERE = Path(__file__).resolve().parent
BUILD = HERE / 'attempt2'
ROOT = Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def ident(p):
    p=Path(p); return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):
    with Path(p).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(v,f,indent=2,allow_nan=False); f.write('\n')
def main():
    result=read(BUILD/'build_result.json')
    before=read(BUILD/'production_before.json'); after=read(BUILD/'production_after.json')
    settings=read(BUILD/'tool_and_effective_settings.json'); command=read(BUILD/'build_command.json')
    guard=read(BUILD/'owned_build_job_guard.json')
    assert result['status']=='compile_link_completed' and result['returncode']==0
    assert before['files']==after['files'] and after['all_before_after_byte_identities_exact']
    assert guard['maximum_simultaneous_cl_exe']==1 and not guard['terminated_owned_job']
    assert settings['all_compile_items_MP_false']
    assert settings['properties']['PreBuildEventUseInBuild']==settings['properties']['PostBuildEventUseInBuild']=='false'
    assert '/m:1' in command['args'] and '/nodeReuse:false' in command['args']
    for x in read(HERE/'preparation_attempt1_qualification.json')['preserved_attempt1_files']:
        assert ident(x['path'])==x, x['path']
    assert ident(result['output_DLL']['path'])==result['output_DLL']
    assert ident(result['changed_source_obj']['path'])==result['changed_source_obj']
    source=ROOT/'OptiScaler/upscalers/fsr31/FSRDFeature_Dx12.cpp'
    assert sha(source)==result['source_sha256']=='d2cb58c65f6e9d3699e56e34675e6d50593b2bd89bd568025083cb8e09fdd628'
    text=(BUILD/'full_build.log').read_text(encoding='utf-8-sig',errors='replace')
    warnings=[s for s in text.splitlines() if re.search(r'\bwarning [A-Z]+\d+\b',s,re.I)]
    errors=[s for s in text.splitlines() if re.search(r'\berror [A-Z]+\d+\b',s,re.I)]
    codes=Counter(re.search(r'\bwarning ([A-Z]+\d+)\b',s,re.I).group(1).upper() for s in warnings)
    # Actual code-line logging commonly repeats diagnostics in the MSBuild summary.
    # Keep these counts distinct from the tool's final warning/error totals.
    reported_totals=re.findall(r'^\s*(\d+)\s+(Warning\(s\)|Error\(s\))\s*$',text,re.M|re.I)
    external=[ident(BUILD/'full_build.binlog'),result['output_DLL'],result['changed_source_obj']]
    summary={
        'schema':'fsrd-failure-reset-policy-full-Release-build-completion-v1',
        'UTC':datetime.now(timezone.utc).isoformat(),
        'status':'full_Release_x64_compile_link_passed',
        'actual_build_attempts':1,'metadata_only_prior_preparation_attempts':1,
        'actual_compiler_or_linker_returncode':result['returncode'],
        'build_start_HEAD':before['head'],'build_finish_HEAD':after['head'],
        'seal_HEAD':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD']).decode().strip(),
        'compiled_dirty_source_sha256':result['source_sha256'],'dirty_source_numstat':before['dirty_source_numstat'],
        'source_change_scope':'Eight additions: two calls of the existing InvalidateDenoiserHistory helper before composition/upscale failure returns. Production edits owned by root.',
        'source_ClCompile_item':settings['changed_source_compile_item'],
        'evaluated_ClCompile_items':settings['ClCompile_items'],
        'MSBuild_version_stdout':(BUILD/'MSBuild_version.stdout.bin').read_text().strip(),
        'compiler_version_probe_qualification':'cl.exe /Bv without source intentionally exits with D8003 after printing tool versions; it is a metadata probe, not the actual compile result.',
        'tool_identities':{k:settings[k] for k in ('msbuild','compiler','linker')},
        'single_compiler_evidence':{'all_items_MP_false':True,'MSBuild_max_nodes':1,'node_reuse':False,'maximum_observed_simultaneous_cl_exe':guard['maximum_simultaneous_cl_exe'],
            'sampling_interval_seconds':guard['interval_seconds'],'limitation':'Process counts are sampled. Evaluated metadata and actual command lines also disable /MP. Link internal workers use the configured default.'},
        'owned_resource_guard':{k:guard[k] for k in ('status','elapsed_seconds','samples','peak_tree_working_set_bytes','minimum_observed_available_bytes','maximum_tree_working_set_bytes','minimum_available_memory_bytes','timeout_seconds','terminated_owned_job','termination_reason')},
        'warning_code_log_lines_including_summary_duplicates':dict(sorted(codes.items())),
        'warning_code_log_lines_total_including_summary_duplicates':len(warnings),
        'unique_warning_lines':len(set(warnings)),
        'error_code_log_lines_total_including_summary_duplicates':len(errors),
        'MSBuild_reported_final_totals':reported_totals,
        'all_actual_warning_and_error_bytes_retained_in_full_log':True,
        'before_after_byte_identity_file_count':len(before['files']),
        'all_production_shader_provider_project_resource_header_before_after_bytes_exact':True,
        'DLL':result['output_DLL'],'changed_source_obj':result['changed_source_obj'],
        'postbuild_packaging_status':result['postbuild_packaging_status'],
        'prebuild_metadata_status':result['prebuild_metadata_status'],
        'external_large_output_identities':external,
        'cache_archive_scope':'Disposable obj/pch/tmp and Python bytecode caches are not compact review payload. Changed-source obj, DLL and binlog identities are retained as external output evidence.',
        'nativeSDK_dispatches':0,'GPU_jobs':0,'game_runs':0,'DLL_deployment':False,
        'qualification':'Compilation/link validation only; no runtime game, rendering quality, universal recovery, or stain-cause claim.',
        'preserved_metadata_only_attempt1':ident(HERE/'preparation_attempt1_qualification.json'),
    }
    save(HERE/'completion_summary.json',summary)
    totals=', '.join(f'{n} {label}' for n,label in reported_totals)
    md=(
        f'Full solution Release/x64 compile and link completed with exit 0. The compiled FSRDFeature_Dx12.cpp SHA256 is `{result["source_sha256"]}`; its dirty diff contains eight additions.\n\n'
        f'MSBuild {summary["MSBuild_version_stdout"]}, v143, x64 compiler, `/m:1`, `/nodeReuse:false`, and `/MP` disabled for all {settings["ClCompile_items"]} evaluated compile items. One compiler process was observed at a time. Full tool diagnostics are retained; MSBuild reported {totals or "totals in the full log"}.\n\n'
        f'DLL SHA256 `{result["output_DLL"]["sha256"]}` ({result["output_DLL"]["bytes"]:,} bytes), in the owned isolated output directory. All {len(before["files"])} pinned production/source/shader/provider/project/resource-header bytes matched before and after.\n\n'
        'Prebuild header regeneration and postbuild packaging were disabled. No DLL deployment, native SDK diagnostic, GPU fixture or game run occurred. This validates compilation and linking only.\n\n'
        'Metadata-only preparation attempt1 is preserved: an unnecessary linker-help assertion stopped before compilation. Attempt2 removed that extra linker option/check; the actual build ran once.\n'
    )
    with (HERE/'compact_completion.md').open('x',encoding='utf-8',newline='\n') as f:f.write(md)
    excluded={'__pycache__','tmp','obj','out'}
    compact=[]
    for p in sorted(HERE.rglob('*')):
        if not p.is_file() or any(x in excluded for x in p.relative_to(HERE).parts):continue
        if p.name in ('completion_manifest.json','completion_manifest.sha256') or p==BUILD/'full_build.binlog':continue
        compact.append(ident(p))
    manifest={'schema':'fsrd-failure-reset-policy-compact-completion-manifest-v1','UTC':datetime.now(timezone.utc).isoformat(),
        'compact_files':compact,'external_output_files':external,'compact_count':len(compact),'compact_bytes':sum(x['bytes'] for x in compact),
        'source_sha256':result['source_sha256'],'actual_full_compile_link_attempts':1,'metadata_only_preparation_attempts':1,'nativeSDK_dispatches':0,'GPU_jobs':0,
        'scope':'Compact sources, metadata, exact full logs, source snapshots, effective evaluation, before/after hashes and qualification. Large caches excluded; DLL/binlog/changedobj externally pinned.'}
    save(HERE/'completion_manifest.json',manifest)
    with (HERE/'completion_manifest.sha256').open('x',encoding='ascii',newline='\n') as f:f.write(sha(HERE/'completion_manifest.json')+'  completion_manifest.json\n')
    for x in compact+external:assert ident(x['path'])==x
    print(json.dumps({'status':summary['status'],'summary':ident(HERE/'completion_summary.json'),'manifest':ident(HERE/'completion_manifest.json'),'compact_count':len(compact),'MSBuild_totals':reported_totals,'DLL':result['output_DLL']}))
if __name__=='__main__':main()
