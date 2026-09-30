"""Freeze failed alpha/phase hypotheses without modifying earlier archives."""
from pathlib import Path
import hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/evidence/fsrd_phase_response_followup'
PACKAGES=('native_hit_alpha_contract_review_20260930','specular_hit_native_ablation_20260930',
    'specular_hit_native_independent_audit_20260930','phase_aligned_pilot_feasibility_20260930',
    'phase_uncertainty_formula_check_20260930','phase_uncertainty_independent_audit_20260930',
    'phase_covariance_formula_check_20260930','significant_phase_pilot_feasibility_20260930',
    'native_significant_phase_initial_20260930','native_significant_phase_independent_audit_20260930',
    'significant_phase_native_noise_attribution_20260930','response_global_dc_offline_20260930',
    'response_global_dc_independent_review_20260930','phase_response_followup_plot_20260930',
    'phase_response_followup_plot_v2_20260930')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while chunk:=f.read(1024*1024):h.update(chunk)
    return h.hexdigest()

def main():
    if DEST.exists():raise ValueError('Preserve previous archive')
    for name in ('specular_hit_native_independent_audit_20260930','phase_uncertainty_independent_audit_20260930',
                 'native_significant_phase_independent_audit_20260930','response_global_dc_independent_review_20260930'):
        if not (ROOT/'tools_tmp'/name/'audit.json').exists():raise ValueError('Wait for independent audit: '+name)
    native=ROOT/'tools_tmp/native_significant_phase_initial_20260930/evidence'
    j=json.loads((native/'results.json').read_text())
    assert j['status']=='completed_research_not_solution' and j['amd_completed_sequences']==18
    jobs=list((native/'shader_jobs').glob('*/job.txt'))
    assert len(jobs)==1920
    conversions=sum('FSRDInputConvAdditive' in p.parent.name for p in jobs)
    compositions=sum('FSRDOutputComp' in p.parent.name for p in jobs)
    assert conversions==768 and compositions==1152
    DEST.mkdir(parents=True)
    (DEST/'.gitattributes').write_text('* -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n')
    manifest=dict(schema='fsrd-phase-response-followup-archive-v1',quality_accepted=False,game_run=False,
        runtime_implemented=False,parent_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        archived_files=[],external_files=[],packages=[],hit_native_contexts=12,hit_native_RR_dispatches=768,
        significant_phase_native_contexts=18,significant_phase_native_RR_dispatches=1152,
        conversion_dispatches=conversions,composition_dispatches=compositions,
        previous_completed_native_contexts=305,previous_completed_native_RR_dispatches=15152,
        completed_native_total_including_metadata_failed=335,completed_native_RR_total_including_metadata_failed=17072,
        installed_game_dll_sha256=sha('F:/SteamLibrary/steamapps/common/Cyberpunk 2077/bin/x64/dxgi.dll'),
        limitations=['No stain/wave solution accepted. Earlier archives and installed game DLL preserved.',
          'Ordinary debug logs do not establish GPU-based validation or hidden provider determinism.',
          'Initial six native scenes do not replace all13 families, captured geometry, or true game history.',
          'Significant-phase native raw seven inputs, outputs, controls/logs retained; converter/composition CB/resources were cleaned.',
          'Global-DC model is failed posthoc reuse, not new native validation.',
          'Oracle covariance formula check uses known simulated noise covariance, unavailable to the pilot.',
          'Full native arrays/binaries remain at original external paths with exact byte hashes.'])
    def copy(p,rel):
        target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True)
        before=sha(p);shutil.copyfile(p,target)
        if sha(p)!=before or sha(target)!=before:raise ValueError('Archive source changed')
        manifest['archived_files'].append(dict(path=rel.as_posix(),source=str(p),sha256=before,bytes=target.stat().st_size))
    for name in PACKAGES:
        folder=ROOT/'tools_tmp'/name
        if not folder.is_dir():raise ValueError('Missing package '+name)
        count=0
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:continue
            rel=Path(name)/p.relative_to(folder)
            compact=p.suffix in ('.py','.json','.md','.log','.txt','.cmd','.png')
            contract=p.name=='dispatch_controls.bin' or 'specular_inputs' in p.parts
            if compact or contract:copy(p,rel);count+=1
            else:manifest['external_files'].append(dict(package=name,path=str(p),sha256=sha(p),bytes=p.stat().st_size))
        manifest['packages'].append(dict(name=name,archived_count=count))
    for p in (Path(__file__),ROOT/'tools_tmp/verify_fsrd_phase_response_archive_20260930.py',ROOT/'tools_tmp/plot_fsrd_phase_response_followup_20260930.py'):
        copy(p,Path('support')/p.name)
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    assert all(sha(DEST/r['path'])==r['sha256'] for r in manifest['archived_files'])
    print(json.dumps(dict(archived=len(manifest['archived_files']),external=len(manifest['external_files']),path=str(DEST),manifest_sha256=sha(DEST/'manifest.json'))))
if __name__=='__main__':main()
