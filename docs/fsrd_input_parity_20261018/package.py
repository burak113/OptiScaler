"""Export this committed research build to E: only; never install into the game."""
from pathlib import Path
import datetime
import hashlib
import json
import shutil
import subprocess
import zipfile

root = Path(__file__).resolve().parents[2]
research = Path(__file__).parent
work = Path('F:/FSRD/sol_batch/21-input-parity')
out = Path('E:/FSRD/sol_batch/21-input-parity')
base = '93f53b814'
out.mkdir(parents=True, exist_ok=True)

def git(*args):
    return subprocess.check_output(['git', *args], cwd=root)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

assert not git('status', '--porcelain').strip(), 'Commit the reviewed source before packaging'
commit = git('rev-parse', 'HEAD').decode().strip()
tag = (root / 'OptiScaler/resource_build_commit.h').read_text()
assert git('rev-parse', '--short', 'HEAD').decode().strip() in tag, 'Rebuild after committing'
for source, target in ((work/'build/out/OptiScaler.dll', out/'dxgi.dll'),
                       (work/'build/out/OptiScaler.pdb', out/'OptiScaler.pdb'),
                       (work/'build.log', out/'build.log'),
                       (research/'REPORT.md', out/'REPORT.md'),
                       (research/'OKU.txt', out/'OKU.txt'),
                       (research/'reproduce.txt', out/'reproduce.txt')):
    shutil.copyfile(source, target)
    assert digest(source) == digest(target)
(out/'source.patch').write_bytes(git('diff', '--binary', base, 'HEAD'))
(out/'changed-files.txt').write_bytes(git('diff', '--name-only', base, 'HEAD'))
files = git('ls-files', 'docs/fsrd_input_parity_20261018').decode().splitlines()
with zipfile.ZipFile(out/'research-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in files:
        archive.write(root/name, str(Path(name).relative_to(research.relative_to(root))))
with zipfile.ZipFile(out/'Input_Parity_AB.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ('dxgi.dll', 'OKU.txt', 'REPORT.md'):
        archive.write(out/name, name)

sdk = root/'external/FidelityFX-SDK-v2/Kits/FidelityFX'
captures = {}
capture_root = Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE')
for prefix in ('f2ef375f','d6d2a083','cb550300','06fadf38','dc96ece3','8ab8afe7','daa6'):
    folder = next(capture_root.glob(prefix+'*'))
    source = folder/'capture.json'
    metadata = json.loads(source.read_text())
    captures[folder.name] = {'capture_json_sha256': digest(source),
        'published_frames': metadata.get('manifest_published_frames'),
        'render_extent': metadata.get('render_extent'), 'roi': metadata.get('roi'),
        'quality_scope': 'cropped research replay; no complete off-ROI history'}

compiled = work/'replay-compile/native-replay.exe'
(out/'strict-replay-compile.json').write_text(json.dumps({
    'status':'COMPILED_ONLY', 'native_execution':False,
    'source_sha256':digest(work/'replay-compile/native-replay.cpp'),
    'exe_sha256':digest(compiled)}, indent=2))
names = ('dxgi.dll','OptiScaler.pdb','source.patch','research-source.zip',
         'Input_Parity_AB.zip','REPORT.md','OKU.txt','reproduce.txt','build.log',
         'f2ef375f_final_comparison.gif','f2ef375f_final_same_frame.png',
         'UltraPlus_Input_Parity_Optional.zip','strict-replay-compile.json')
manifest = {
    'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'branch':git('branch','--show-current').decode().strip(),
    'base':git('rev-parse',base).decode().strip(), 'commit':commit,
    'worktree':str(root), 'build':'Release x64; OptiScaler.sln; MSBuild exit 0',
    'settings_default':{'enabled':False,'diffuse':16,'specular':256},
    'build_commit_header':tag.strip(),
    'provider_disk_hashes':{str(p.relative_to(sdk)):digest(p) for p in (
        sdk/'signedbin/amd_fidelityfx_loader_dx12.dll',
        sdk/'signedbin/amd_fidelityfx_denoiser_dx12.dll')},
    'provider_scope':'explicit loader path, enumerated FSR Ray Regeneration 1.2.0; disk hashes, not loaded-memory attestation',
    'captures':captures,
    'installed_to_game':False, 'optional_mod_installed':False,
    'in_game_quality_verified':False, 'full_RR_on_native_ingress_proved':False,
    'artifacts':{name:{'bytes':(out/name).stat().st_size,'sha256':digest(out/name)} for name in names}}
(out/'delivery-manifest.json').write_text(json.dumps(manifest, indent=2))
(out/'SHA256SUMS.txt').write_text(''.join(f'{row["sha256"]}  {name}\n' for name,row in manifest['artifacts'].items()))
total = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
assert total < 1024**3, f'E: task output exceeds 1 GiB: {total}'
print(json.dumps({'commit':commit,'dll_sha256':digest(out/'dxgi.dll'),
                  'task_bytes':total,'installed':False}, indent=2))
