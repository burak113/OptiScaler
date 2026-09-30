"""Preserve and remove only our untracked MSBuild generated solution helper."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,subprocess
HERE=Path(__file__).resolve().parent
ROOT=Path('F:/OptiRevelations/OptiScaler-ffxD-alpha')
TARGET=ROOT/'OptiScaler.sln.metaproj'
def ident(p):
    p=Path(p);return{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def save(p,v):
    with p.open('x',encoding='utf-8',newline='\n')as f:json.dump(v,f,indent=2,allow_nan=False);f.write('\n')
def main():
    assert TARGET.resolve()==Path('F:/OptiRevelations/OptiScaler-ffxD-alpha/OptiScaler.sln.metaproj').resolve()
    before=(HERE/'attempt2/git_status_before.bin').read_bytes()
    assert b'OptiScaler.sln.metaproj' not in before
    tracked=subprocess.run(['git','-C',str(ROOT),'ls-files','--error-unmatch','--','OptiScaler.sln.metaproj'],capture_output=True)
    assert tracked.returncode!=0
    manifest=json.loads((HERE/'completion_manifest.json').read_text())
    for x in manifest['compact_files']+manifest['external_output_files']:assert ident(x['path'])==x
    preserved=[]
    for p in (HERE/'completion_manifest.json',HERE/'completion_manifest.sha256'):preserved.append(ident(p))
    original=ident(TARGET);raw=TARGET.read_bytes()
    assert b'<MSBuildFileVersion>17.14.51.32402</MSBuildFileVersion>' in raw
    with (HERE/'generated_OptiScaler.sln.metaproj').open('xb')as f:f.write(raw)
    # Exact absolute path, no recursion or computed path enumeration.
    command=['powershell.exe','-NoProfile','-Command',
        "$buildTarget = 'F:\\OptiRevelations\\OptiScaler-ffxD-alpha\\OptiScaler.sln.metaproj'; $preservedTarget = 'F:\\OptiRevelations\\OptiScaler-ffxD-alpha\\tools_tmp\\fsrd_failure_reset_policy_build_20260930\\generated_OptiScaler.sln.metaproj'; if ((Get-FileHash -LiteralPath $buildTarget -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $preservedTarget -Algorithm SHA256).Hash) { throw 'Generated helper changed before cleanup'; }; Remove-Item -LiteralPath $buildTarget -ErrorAction Stop"]
    cleaned=subprocess.run(command,capture_output=True)
    for suffix,data in(('stdout.bin',cleaned.stdout),('stderr.bin',cleaned.stderr)):
        with(HERE/f'generated_helper_cleanup.{suffix}').open('xb')as f:f.write(data)
    assert cleaned.returncode==0 and not TARGET.exists()
    for x in preserved+manifest['compact_files']+manifest['external_output_files']:assert ident(x['path'])==x
    after=subprocess.check_output(['git','-C',str(ROOT),'status','--short'])
    with(HERE/'git_status_after_generated_helper_cleanup.bin').open('xb')as f:f.write(after)
    summary={'schema':'generated-solution-helper-cleanup-supplement-v1','UTC':datetime.now(timezone.utc).isoformat(),
        'qualification':'Build process-only MSBUILDEMITSOLUTION was set to string0. Its presence caused a solution metaproj dump outside isolated output; this was detected after compile/link and original completion seal. Original build and completion bytes remain unchanged.',
        'scope':'Only the exact untracked generated OptiScaler.sln.metaproj was removed after retaining its actual bytes. No production source/script/header/provider edit; no new build/native/GPU/game or deployment.',
        'before_build_git_status':ident(HERE/'attempt2/git_status_before.bin'),'generated_original_identity':original,
        'generated_preserved_copy':ident(HERE/'generated_OptiScaler.sln.metaproj'),'cleanup_args':command,'cleanup_exitcode':cleaned.returncode,
        'generated_external_path_absent_after_cleanup':True,'all_old_completion_compact_and_external_hashes_exact':True,
        'old_completion_manifest':preserved[0],'final_git_status':ident(HERE/'git_status_after_generated_helper_cleanup.bin')}
    save(HERE/'completion_cleanup_supplement.json',summary)
    names=['preserve_generated_metaproj_cleanup.py','generated_OptiScaler.sln.metaproj','generated_helper_cleanup.stdout.bin','generated_helper_cleanup.stderr.bin','git_status_after_generated_helper_cleanup.bin','completion_cleanup_supplement.json']
    newmanifest={'schema':'generated-solution-helper-cleanup-completion-manifest-v1','UTC':datetime.now(timezone.utc).isoformat(),
        'original_completion_pins':preserved,'new_supplement_files':[ident(HERE/n)for n in names],
        'new_compiles':0,'new_nativeSDK_dispatches':0,'new_GPU_jobs':0,'new_game_runs':0}
    save(HERE/'completion_cleanup_manifest.json',newmanifest)
    print(json.dumps({'status':'cleanup_completed_old_seal_exact','completion_manifest':preserved[0],'cleanup_manifest':ident(HERE/'completion_cleanup_manifest.json')}))
if __name__=='__main__':main()
