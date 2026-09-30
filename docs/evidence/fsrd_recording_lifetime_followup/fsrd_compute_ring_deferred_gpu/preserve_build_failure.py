from pathlib import Path
import hashlib,json,shutil
HERE=Path(__file__).resolve().parent;DEST=HERE/'build_attempt1';DEST.mkdir(exist_ok=False)
records=[]
for p in sorted(HERE.iterdir()):
    if p.is_file():
        target=DEST/p.name;shutil.copyfile(p,target)
        records.append({'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
with (DEST/'manifest.json').open('x',encoding='utf-8',newline='\n')as f:
    json.dump({'status':'failed_MSVC_preserved','error':'root_inspector.cpp missing <string> for std::to_string',
               'GPU_jobs':0,'native_SDK_dispatches':0,'files':records},f,indent=2);f.write('\n')
print('Preserved first build attempt; no GPU jobs ran.')
