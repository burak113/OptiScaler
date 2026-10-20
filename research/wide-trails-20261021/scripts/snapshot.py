"""Archive a reviewable research-only snapshot; never touches game/runtime files."""
from pathlib import Path
import shutil,json,hashlib,subprocess,py_compile
O=Path(__file__).parent
repo=Path('F:/OptiRevelations/OSA-27-astra-audit')
dst=repo/'research/wide-trails-20261021'
dst.mkdir(parents=True,exist_ok=True)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
manifest={'scope':'Research only. No accepted runtime feature or new production DLL.',
 'base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
 'files':{},'external_dependencies':{}}
attrs=dst/'.gitattributes';attrs.write_bytes(b'* -text whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol\n')
manifest['files']['.gitattributes']={'sha256':sha(attrs),'bytes':attrs.stat().st_size}
source=list(O.glob('*.py'))+[O/'rrlab_diffuse.cpp',O/'README.txt']
results=list(O.glob('*.json'))+[O/'health-small.log']
images=[O/n for n in ['stages-87ee1fba.png','guard-comparison-87ee1fba.png','normalize-87ee1fba.png','tail-comparison-87ee1fba.png']]
for group,files in [('scripts',source),('results',results),('images',images)]:
 for p in files:
  q=dst/('README.txt' if p.name=='README.txt' else group+'/'+p.name)
  q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
  manifest['files'][q.relative_to(dst).as_posix()]={'sha256':sha(q),'bytes':q.stat().st_size}
  if q.suffix=='.py':py_compile.compile(str(q),cfile=str(O/'syntax-cache'/f'{q.name}.pyc'),doraise=True)
for p in list(Path('E:/FSRD/rrlab/rrlab').glob('*.py'))+[Path('E:/FSRD/rrlab/runner/rrlab_runner.cpp')]:
 q=dst/'harness-source'/p.name;q.parent.mkdir(exist_ok=True);shutil.copyfile(p,q)
 manifest['files'][q.relative_to(dst).as_posix()]={'sha256':sha(q),'bytes':q.stat().st_size}
for p in [Path('E:/FSRD/rrlab/runner/rrlab_runner.cpp'),O/'rrlab_diffuse.exe',Path('E:/FSRD/rrlab/runner/bin/amd_fidelityfx_denoiser_dx12.dll'),Path('E:/FSRD/sol_batch/31-material-trails/gpu_old_hook.py'),Path('E:/FSRD/sol_batch/31-material-trails/gpu-old.npy')]:
 manifest['external_dependencies'][str(p)]={'sha256':sha(p),'bytes':p.stat().st_size}
for p in Path('F:/Ultra Yedek 2/overwrite/bin/x64/GAME_TRACE').glob('*/capture.json'):
 if p.parent.name.startswith(('c37d','87ee','22f9','2405','d6d2','f2ef','06fa')):
  manifest['external_dependencies'][str(p)]={'sha256':sha(p),'bytes':p.stat().st_size}
(dst/'provenance.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Snapshot',len(manifest['files']),'files; script syntax PASS; external dependencies pinned')
