from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tools_tmp/native_output_initialization_independent_audit_20260930'
DEST=ROOT/'docs/evidence/fsrd_native_output_initialization_audit'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if DEST.exists():raise ValueError('Preserve completed archive')
assert sha(SOURCE/'completion_manifest_v2.json')=='e51a1094ab85a02fdb9b3c87d7f28a0c2f1e611586e56e071d5483bc5f90f513'
completion=json.loads((SOURCE/'completion_manifest_v2.json').read_text())
for row in completion['files']:
 p=Path(row['path']);assert p.stat().st_size==row['bytes']and sha(p)==row['sha256']
DEST.mkdir(parents=True);items=[]
for p in sorted(SOURCE.rglob('*')):
 if not p.is_file()or'__pycache__'in p.parts:continue
 rel=p.relative_to(SOURCE);target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
 assert sha(target)==sha(p);items.append(dict(source=str(p),archive=rel.as_posix(),bytes=p.stat().st_size,sha256=sha(p)))
p=Path(__file__);target=DEST/'collector_source.py';shutil.copyfile(p,target)
items.append(dict(source=str(p),archive=target.name,bytes=p.stat().st_size,sha256=sha(p)))
manifest=dict(schema='fsrd-output-initialization-audit-archive-v1',branch='ffxD-experimental-alpha',
 base_commit='81bf64ac98905d355ddb729c596786ef76ad817d',audited_commit=completion['head'],
 status='completed_passed_with_qualifications',quality_accepted=False,new_native_contexts=0,new_native_RR_calls=0,
 completed_total_contexts=382,completed_total_RR_calls=20080,previous_contexts_independently_verified=12,
 previous_RR_calls_independently_verified=768,copied_file_count=len(items),copied_files=items,
 canonical_compact='compact_v2.json',canonical_completion='completion_manifest_v2.json',
 payloads='Previous raw buffers/build binaries stay retained and pinned in the producer archive; no copied evidence modified.')
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(DEST/'.gitattributes').write_text('* -text\n')
print(json.dumps(dict(archive=str(DEST),copied_files=len(items),manifest_sha256=sha(DEST/'manifest.json')),indent=2))
