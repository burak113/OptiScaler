"""Freeze compact follow-up reports and exact sources; retain external arrays."""
from pathlib import Path
import hashlib,json,shutil,subprocess

ROOT=Path(__file__).resolve().parents[1]
CROOT=Path('C:/Users/burak/.codex/visualizations/2026/09/29/01a0eeeb-48a8-7733-add1-58a3bd1f37ce')
DEST=ROOT/'docs/evidence/fsrd_response_followup'
NATIVE=('response_soft_temporal_alpha_fresh','response_soft_temporal_long_alpha_fresh',
        'response_soft_temporal_long_captured_alpha_fresh')
OFFLINE=('response_affine_spectrum_offline_20260930','response_transfer_offline_20260930',
    'response_noise_attribution_20260930','factorized_pilot_feasibility_20260930',
    'soft_history_feasibility_20260930','hard_long_pilot_feasibility_20260930',
    'soft_fresh_independent_audit_20260930','factorized_coeff_history_feasibility_20260930',
    'soft_long_independent_audit_20260930','soft_captured_independent_audit_20260930',
    'context_repeat_independent_audit_20260930','reset_repeat_independent_audit_20260930')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    if DEST.exists():raise ValueError('Preserve prior archive')
    roots={name:(ROOT/'tools_tmp'/name if name.endswith('captured_alpha_fresh') else CROOT/name) for name in NATIVE}
    reports={name:json.loads((roots[name]/'results.json').read_text()) for name in NATIVE}
    if any(r['status']!='completed_research_not_solution' for r in reports.values()):
        raise ValueError('Only completed native matrices can be archived')
    DEST.mkdir(parents=True)
    (DEST/'.gitattributes').write_text('* -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n',encoding='utf-8')
    manifest=dict(schema='fsrd-response-followup-evidence-v1',quality_accepted=False,game_run=False,
        runtime_implemented=False,archive_parent_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        archived_files=[],external_arrays=[],native_matrices=[],offline_packages=[],
        limitations=['Compact archive excludes large sequence arrays; their external paths and hashes are retained.',
            'Native manifests attest consumed hashes; successful helper deleted original native input/output payloads.',
            'First fresh16 null repeat RGB was not saved; the fresh64 null repeat is saved externally.',
            'All image-quality failures are retained; CPU/GPU/build success does not mean image acceptance.',
            'Source noise samples are fresh, but synthetic scene families are familiar and not game acceptance.'])
    def copy(src,relative):
        src=Path(src);target=DEST/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():raise ValueError('Duplicate archive target')
        before=sha(src);shutil.copyfile(src,target)
        if sha(target)!=before or sha(src)!=before:raise ValueError('Source/archive changed')
        manifest['archived_files'].append(dict(path=target.relative_to(DEST).as_posix(),source=str(src),sha256=before,bytes=target.stat().st_size))
    for name,report in reports.items():
        folder=roots[name]
        copy(folder/'results.json',Path('native')/name/'results.json')
        copy(folder.with_suffix('.log'),Path('native')/name/'run.log')
        for file in (folder/'source_snapshot').iterdir():
            if file.is_file():copy(file,Path('native')/name/'source_snapshot'/file.name)
        contexts=0;dispatches=0
        for row in report['rows']:
            case=Path(row.get('evidence_directory') or folder/row['scene'])
            array=case/'sequences.npz'
            manifest['external_arrays'].append(dict(study=name,scene=row['scene'],path=str(array),sha256=sha(array),bytes=array.stat().st_size,
                null_repeat_saved=bool(row.get('null_repeat_saved',False))))
            for ctx in ('observed','null_repeat','blind_pilot'):
                context=case/ctx
                identity=json.loads((context/'amd_context_identity.json').read_text())
                contexts+=1;dispatches+=identity['frames']
                for file in context.iterdir():
                    if file.is_file() and file.suffix in ('.json','.txt','.log') or file.is_file() and file.name=='dispatch_controls.bin':
                        copy(file,Path('native')/name/row['scene']/ctx/file.name)
        if contexts!=report['amd_completed_sequences']:raise ValueError('Context count differs')
        manifest['native_matrices'].append(dict(name=name,contexts=contexts,dispatches=dispatches,frames=report['frames'],history=report['history'],seed=report['seed']))
    for name in OFFLINE:
        folder=ROOT/'tools_tmp'/name
        if not folder.is_dir():raise ValueError('Missing offline package '+name)
        copied=[]
        for file in folder.iterdir():
            if file.is_file() and file.suffix in ('.py','.json','.md','.log'):
                copy(file,Path('offline')/name/file.name);copied.append(file.name)
        manifest['offline_packages'].append(dict(name=name,files=sorted(copied),native_dispatches=0))
    copy(ROOT/'tools_tmp/delta_history_offline_20260930/analyze.py',Path('support')/'delta_history_reference.py')
    copy(Path(__file__),Path('support')/Path(__file__).name)
    copy(ROOT/'tools_tmp/plot_fsrd_followup_20260930.py',Path('support')/'plot_fsrd_followup_20260930.py')
    copy(ROOT/'tools_tmp/response_followup_registered_cpu.log',Path('cpu')/'response_followup_registered_cpu.log')
    for name in ('test_fsrd_response_conditioned_pilot.py','test_fsrd_response_soft_pilot.py'):
        copy(ROOT/'OptiScaler/shaders/shader_tools/tests'/name,Path('cpu')/name)
    manifest['native_diagnostics']=[]
    for name in ('controlled_context_repeat_20260930','reset_context_repeat_20260930'):
        diagnostic=ROOT/'tools_tmp'/name
        dr=json.loads((diagnostic/'evidence/results.json').read_text())
        if dr['status']!='completed_diagnostic_not_solution':raise ValueError('Only completed repeat diagnostic can be archived')
        for file in diagnostic.iterdir():
            if file.is_file() and file.suffix in ('.py','.md','.log','.json'):
                copy(file,Path('diagnostic')/diagnostic.name/file.name)
        for file in (diagnostic/'evidence').rglob('*'):
            if file.is_file() and file.suffix in ('.json','.txt','.log','.bin'):
                copy(file,Path('diagnostic')/diagnostic.name/'evidence'/file.relative_to(diagnostic/'evidence'))
        for run in dr['runs']:
            p=Path(run['retained_payload_path'])
            if sha(p)!=run['payload_sha256']:raise ValueError('Native diagnostic payload changed')
            manifest['external_arrays'].append(dict(study=name,run=run['run'],path=str(p),sha256=sha(p),bytes=p.stat().st_size,full_native_lobes_retained=True))
        manifest['native_diagnostics'].append(dict(name=name,contexts=dr['contexts'],dispatches=dr['dispatches']))
    alpha=ROOT/'tools_tmp/source_alpha_contract_20260930'
    for relative in ('analyze.py','run.log','evidence/results.json'):
        copy(alpha/relative,Path('input_alpha_inspection')/relative)
    for file in (alpha/'evidence').glob('packed_frame_*.npz'):
        manifest['external_arrays'].append(dict(study='source_alpha_contract_20260930',path=str(file),sha256=sha(file),bytes=file.stat().st_size,native_dispatches=0))
    manifest['new_native_contexts']=sum(r['contexts'] for r in manifest['native_matrices']+manifest['native_diagnostics'])
    manifest['new_native_dispatches']=sum(r['dispatches'] for r in manifest['native_matrices']+manifest['native_diagnostics'])
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    for item in manifest['archived_files']:
        if sha(DEST/item['path'])!=item['sha256']:raise ValueError('Final archive verification failed')
    print(json.dumps(dict(files=len(manifest['archived_files']),contexts=manifest['new_native_contexts'],dispatches=manifest['new_native_dispatches'],path=str(DEST))))
if __name__=='__main__':main()
