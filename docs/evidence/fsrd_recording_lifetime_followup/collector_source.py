from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs/evidence/fsrd_recording_lifetime_followup'
PACKAGES=['fsrd_response_control_covariance_design','fsrd_unresolved_path_gap_review',
 'fsrd_compute_lifetime_remedy_design','fsrd_compute_ring_deferred_gpu','fsrd_compute_ring_fixture_review']
PINS={
 'fsrd_compute_ring_deferred_gpu/completion_manifest.json':'2da7eb14f5feab978aeef0d5c32df84dfab0bd82266ddb463e70c856a340e31f',
 'fsrd_compute_ring_fixture_review/completion_manifest.json':'2e2bc132a4ba3ccd8a1ab86a660b06b1490eff903dc1826087cd47f5bbe53d3a',
 'fsrd_unresolved_path_gap_review/review.json':'dcfb9f59d5f7aec777d5e498487289ceebc66179c1ae5eae529c174a2bdd20da',
 'fsrd_compute_lifetime_remedy_design/design.json':'1a67e9c408cfd5029919a280ebc2df0f391ab0fb90cc44e18e0b5f0015b2ad75',
 'fsrd_response_control_covariance_design/design.json':'0f4f04d6721c3e3a95a794ceb51ab5404c662f3fba8d4a41c49fd8fe16005bb1'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
if DEST.exists():raise ValueError('Preserve completed archive')
for rel,digest in PINS.items():
 name,filename=rel.split('/',1);p=ROOT/'tools_tmp'/(name+'_20260930')/filename
 assert sha(p)==digest,rel
 if filename=='completion_manifest.json':
  for row in json.loads(p.read_text())['files']:
   q=Path(row['path']);assert q.stat().st_size==row['bytes']and sha(q)==row['sha256'],str(q)
DEST.mkdir(parents=True);copied=[];external=[]
def collect(p,rel):
 item=dict(source=str(p),bytes=p.stat().st_size,sha256=sha(p))
 if p.suffix.lower()in('.exe','.obj','.dll','.cso','.npz','.npy'):
  item['retained_external_payload']=True;external.append(item)
 else:
  target=DEST/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
  assert sha(target)==item['sha256'];item['archive']=rel.as_posix();copied.append(item)
for name in PACKAGES:
 folder=ROOT/'tools_tmp'/(name+'_20260930');assert folder.is_dir()
 for p in sorted(folder.rglob('*')):
  if p.is_file()and'__pycache__'not in p.parts:collect(p,Path(name)/p.relative_to(folder))
collect(Path(__file__),Path('collector_source.py'))
manifest=dict(schema='fsrd-recording-lifetime-followup-archive-v1',branch='ffxD-experimental-alpha',
 base_commit='fe908db8d41cc8d4af73abf07b571a85df56eecf',quality_accepted=False,runtime_implemented=False,game_run=False,
 new_native_contexts=0,new_native_RR_calls=0,completed_total_contexts=382,completed_total_RR_calls=20080,
 new_identity_GPU_jobs=9,new_identity_shader_dispatches=40,queue_executes=20,signals=20,fence_waits=20,
 changed_observation_rows=7,safe_controls_exact=5,fixture_root_signature='1.0',inspected_production_root_signature='1.1 static ranges flags0',
 full_source_review_sealed_after_GPU=True,copied_file_count=len(copied),copied_files=copied,
 external_payload_count=len(external),external_payloads=external,
 limits=['Conditional deferred binding hazard, actual game trigger unmeasured',
 'FullsourceauditpostGPU; preliminary arithmetic/source review preGPU',
 'Discardedrecord native test preparation not counted or copied here',
 'Sourcefailure followup corrects compositionguard behavior; originalreview preserved'])
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(DEST/'.gitattributes').write_text('* -text\n')
print(json.dumps(dict(archive=str(DEST),copied_files=len(copied),external_payloads=len(external),manifest_sha256=sha(DEST/'manifest.json')),indent=2))
