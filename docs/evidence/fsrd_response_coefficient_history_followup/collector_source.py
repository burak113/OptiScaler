"""Immutable compact archive; retain both the failed contract and its repair."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/evidence/fsrd_response_coefficient_history_followup'
PACKAGES=['harmonic_response_coefficient_history_design','harmonic_response_coefficient_history_feasibility',
 'harmonic_response_coefficient_history_feasibility_v2','harmonic_response_history_root_contract_probe',
 'harmonic_response_history_root_v2_contract_probe','fsrd_native_output_alpha_consumers']
PINS={
 'harmonic_response_coefficient_history_design/design_manifest.json':'f725a24b3761c2d6c45855a86ff370b548751d7b6bcf5b9c0a7f2b326533624f',
 'harmonic_response_coefficient_history_feasibility/model.py':'84c710ae293e102091d15f70fb08d33edd5ebe1c5a10397c2845303d37e809f0',
 'harmonic_response_coefficient_history_feasibility/results.json':'fb0dc0d7e42fc68cba665b35cf3be7c780dc4798e7446d9e08b3127bef564ef5',
 'harmonic_response_coefficient_history_feasibility_v2/model.py':'afb2fd6ce80e46a79fb97509c5eb2bb53860182b3268f6ede26046628043c874',
 'harmonic_response_coefficient_history_feasibility_v2/results.json':'0e9342a8692f65f187f37a4d64b9f7c3d235033f53be95ba6ffd292bdc4a090e',
 'harmonic_response_coefficient_history_feasibility_v2/completion_manifest.json':'0037de97f2cd858664da8a2e23d9d915f594353230914a1158f187709be420c5'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
if DEST.exists():raise ValueError('Preserve completed archive')
for rel,digest in PINS.items():
 name,filename=rel.split('/',1);assert sha(ROOT/'tools_tmp'/(name+'_20260930')/filename)==digest,rel
completion=json.loads((ROOT/'tools_tmp/harmonic_response_coefficient_history_feasibility_v2_20260930/completion_manifest.json').read_text())
for row in completion['files']:
 p=Path(row['path']);assert p.stat().st_size==row['bytes']and sha(p)==row['sha256'],str(p)
DEST.mkdir(parents=True);copied=[];external=[]
def collect(p,rel):
 item=dict(source=str(p),bytes=p.stat().st_size,sha256=sha(p))
 if p.suffix.lower()in('.npz','.npy','.exe','.dll'):
  item['retained_external_payload']=True;external.append(item)
 else:
  target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
  assert sha(target)==item['sha256'];item['archive']=rel.as_posix();copied.append(item)
for name in PACKAGES:
 folder=ROOT/'tools_tmp'/(name+'_20260930');assert folder.is_dir()
 for p in sorted(folder.rglob('*')):
  if p.is_file()and'__pycache__'not in p.parts:collect(p,Path(name)/p.relative_to(folder))
collect(Path(__file__),Path('collector_source.py'))
manifest=dict(schema='fsrd-response-coefficient-history-followup-v1',branch='ffxD-experimental-alpha',
 base_commit='18550af88f665103e11c8e08d7c701118be1d156',quality_accepted=False,runtime_implemented=False,game_run=False,
 new_native_contexts=0,new_native_RR_calls=0,completed_total_contexts=382,completed_total_RR_calls=20080,
 saved_matched_native_scenes=6,known_constructed_operator_cases=24,V1_contract_failed=True,V2_contract_repaired=True,
 valid_V1_V2_outputs_and_metrics_unchanged=True,full_absolute_pass_count=0,mature_absolute_pass_count=5,
 mature_strict_STD_pass_count=6,copied_file_count=len(copied),copied_files=copied,
 external_payload_count=len(external),external_payloads=external,
 limits=['Old synthetic matching native responses, no new game quality proof',
 'Output-alpha consumer review is static source mapping, not emitted-blob/runtime validation',
 'Weak-detail/startup/true-delta ramp/phase/covariance failure evidence preserved'])
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(DEST/'.gitattributes').write_text('* -text\n')
print(json.dumps(dict(archive=str(DEST),copied_files=len(copied),external_payloads=len(external),manifest_sha256=sha(DEST/'manifest.json')),indent=2))
