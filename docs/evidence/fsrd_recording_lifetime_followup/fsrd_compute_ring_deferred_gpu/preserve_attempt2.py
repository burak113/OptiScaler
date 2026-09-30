from pathlib import Path
import hashlib,json,shutil
HERE=Path(__file__).resolve().parent;DEST=HERE/'build_attempt2';DEST.mkdir(exist_ok=False)
records=[]
for p in sorted(HERE.iterdir()):
    if p.is_file():
        shutil.copyfile(p,DEST/p.name)
        records.append({'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
with (DEST/'manifest.json').open('x',encoding='utf-8',newline='\n')as f:
    json.dump({'status':'failed_CPU_signature_inspection_preserved','error':'Raw RTS0 chunk payload passed to deserializer instead of supported compiled DXBC shader container; HRESULT E_INVALIDARG (2147942487). Both C++ binaries compiled successfully.',
               'GPU_jobs':0,'native_SDK_dispatches':0,'files':records},f,indent=2);f.write('\n')
print('Preserved successful build and failed CPU-only signature inspection; no GPU jobs ran.')
