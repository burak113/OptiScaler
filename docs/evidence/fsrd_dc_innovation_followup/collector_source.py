from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1];DEST=ROOT/'docs/evidence/fsrd_dc_innovation_followup'
PACKAGES=['harmonic_response_dc_innovation_design','harmonic_response_dc_innovation_feasibility',
 'harmonic_dc_innovation_root_review','harmonic_correction_subspace_attribution','native_guide_alpha_independent_audit']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
if DEST.exists():raise ValueError('Preserve archive')
DEST.mkdir(parents=True);items=[]
assert sha(ROOT/'tools_tmp/harmonic_response_dc_innovation_feasibility_20260930/completion_manifest.json')=='b9ace4302b7ef437fdf958ef6524ae23dc6b652d5f966bbcd2f560ec7a6e16aa'
assert sha(ROOT/'tools_tmp/native_guide_alpha_independent_audit_20260930/completion_manifest.json')=='d3d52594427b0dc594044c79fb3213099d343810da7a65c9ec501c689b822f5d'
for name in PACKAGES:
 folder=ROOT/'tools_tmp'/(name+'_20260930')
 for p in sorted(folder.rglob('*')):
  if not p.is_file()or'__pycache__'in p.parts:continue
  rel=Path(name)/p.relative_to(folder);target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
  assert sha(target)==sha(p);items.append({'source':str(p),'archive':rel.as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
p=Path(__file__);target=DEST/'collector_source.py';shutil.copyfile(p,target)
items.append({'source':str(p),'archive':target.relative_to(DEST).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
manifest={'schema':'fsrd-dc-innovation-followup-evidence-v1','branch':'ffxD-experimental-alpha',
 'base_commit':'59d06afc722bb0f522015edff31d4a4d0b1a3c90','quality_accepted':False,'runtime_implemented':False,
 'new_native_contexts':0,'new_native_RR_calls':0,'completed_total_contexts':370,'completed_total_RR_calls':19312,
 'independently_audited_previous_guide_contexts':11,'independently_audited_previous_guide_RR':704,
 'source_proxy_families':13,'source_proxy_adversaries':22,'saved_matched_native_scenes':6,
 'copied_file_count':len(items),'copied_files':items,
 'coverage':'New DC target scores use previously measured matching P/T(P), not a new native or game run. Source13+22 proxies do not establish native coverage.',
 'payload_retention':'All previous actual GPU/native payload SHA/size pins remain in fsrd_continuous_harmonic_followup/manifest.json; no payload or prior file changed.'}
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(DEST/'.gitattributes').write_text('* -text\n')
print(json.dumps({'copied_files':len(items),'manifest_sha256':sha(DEST/'manifest.json'),'archive':str(DEST)},indent=2))
