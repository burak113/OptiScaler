from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'tools_tmp/native_output_initialization_diagnostic_20260930';DEST=ROOT/'docs/evidence/fsrd_native_output_initialization'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if DEST.exists():raise ValueError('Preserve output-init archive')
DEST.mkdir(parents=True);items=[];external=[]
for p in sorted(SOURCE.rglob('*')):
 if not p.is_file()or'__pycache__'in p.parts:continue
 info={'source':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
 if p.suffix.lower()in('.exe','.obj','.pdb')or(p.suffix=='.bin'and p.name!='dispatch_controls.bin'):
  external.append(info);continue
 rel=p.relative_to(SOURCE);t=DEST/rel;t.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,t);assert sha(t)==info['sha256'];info['archive']=rel.as_posix();items.append(info)
p=Path(__file__);t=DEST/'collector_source.py';shutil.copyfile(p,t);items.append({'source':str(p),'archive':t.name,'bytes':p.stat().st_size,'sha256':sha(p)})
manifest={'schema':'native-output-initialization-diagnostic-compact-evidence-v1','branch':'ffxD-experimental-alpha',
 'base_commit':'7105fc4778c0eb3562a55e0c8a6188a0da095028','quality_accepted':False,'new_native_contexts':12,'new_native_RR_calls':768,
 'completed_total_contexts':382,'completed_total_RR_calls':20080,'new_conversion_or_composition_jobs':0,
 'runner_C_sha256':'9c9e15c2c0eb1f4f8a59cf67d105eef3db05377b8c296869e6e253b9a0786496',
 'copied_file_count':len(items),'copied_files':items,'retained_external_payloads':external,
 'runtime_implemented':False,'game_run':False,'audit_status':'producer bytes retained; independent audit will be a separate immutable package',
 'limitations':['One128x80x64 synthetic wave P; two repeats per lifecycle mode, no universal causation/determinism conclusion',
 'Mode1 heap/binding/barrier control separates those changes fromzero/sentinel clears; only registered lifecycle modes vary']}
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(DEST/'.gitattributes').write_text('* -text\n')
print(json.dumps({'copied_files':len(items),'external_payloads':len(external),'manifest_sha256':sha(DEST/'manifest.json')},indent=2))
